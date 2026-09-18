import json
import math

import pandas as pd
import streamlit as st

from utils.fishbone_ui import (
    normalized_id,
    ordered_yamazumi_area_ids,
    section_breadcrumb_labels,
)
from utils.store import (
    add_yamazumi_element,
    add_yamazumi_pitch,
    assembly_section_walk_order,
    audit_history,
    clear_yamazumi_data,
    complexity_features,
    copy_yamazumi_records,
    delete_yamazumi_element,
    delete_yamazumi_pitch,
    get_planning_scenario,
    generate_yamazumi_pitch_range,
    import_yamazumi_rows,
    parse_yamazumi_model_variants,
    planning_scenarios,
    preview_yamazumi_copy,
    record_audit_event,
    rename_yamazumi_variants,
    replace_yamazumi_elements,
    replace_yamazumi_pitches,
    replace_yamazumi_work_regions,
    save_yamazumi_stack_draft,
    update_yamazumi_element,
    update_yamazumi_pitch,
    update_yamazumi_settings,
    sync_yamazumi_areas_from_fishbone,
    yamazumi_area_link_status,
    yamazumi_areas,
    yamazumi_elements,
    yamazumi_element_delete_impact,
    yamazumi_elements_for_scenario,
    work_element_criticality,
    yamazumi_pitch_delete_blockers,
    yamazumi_pitch_address_conflicts,
    yamazumi_pitch_feed_target_status,
    yamazumi_pitch_address_suggestion,
    yamazumi_pitch_label,
    yamazumi_pitches,
    yamazumi_pitches_for_scenario,
    yamazumi_work_regions,
)
from utils.scope_ui import page_title_with_scope
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
)
from utils.table_ui import (
    dataframe_to_excel,
    drop_untouched_new_rows,
    editable_table_footer,
    editable_table_heading,
    native_selected_rows,
    required_field_errors,
    selectable_dataframe,
    selected_rows_action_bar,
    selected_dataframe_rows,
    stage_native_delete_confirmation,
    direct_entry_editor_rows,
    table_has_unsaved_changes,
)
from utils.yamazumi_board import yamazumi_board
from utils.yamazumi_order import order_yamazumi_pitches_for_board
from utils.time_units import (
    TIME_UNITS,
    display_to_seconds,
    format_seconds,
    normalize_time_unit,
    seconds_to_display,
    time_unit,
)
from utils.yamazumi_stack import (
    apply_stack_draft_to_elements,
    apply_stack_drop,
    build_stack_draft,
    draft_differs,
    remove_element_from_stack_draft,
)


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
WORK_TYPES = ["Cycle", "Periodic", "Fluctuation"]
PITCH_TYPES = ["Pitch", "Waterspider", "Subassembly", "Kitter", "Repacker"]
ELEMENT_VARIANT_HELP = (
    "Choose every model stack where this same work element applies. The destination pitch must "
    "show all selected variants."
)
ADD_ELEMENT_VARIANT_HELP = (
    "Choose every model stack where this same work element applies. Missing stacks are added "
    "automatically to the destination pitch."
)
if not project_id or not scenario_id:
    st.stop()

scenario = get_planning_scenario(project_id, scenario_id)
if not scenario:
    st.error("The active planning scenario no longer exists.")
    st.stop()

yamazumi_time_unit = normalize_time_unit(
    scenario.get("yamazumi_time_unit", "seconds")
)
takt_time_unit = normalize_time_unit(scenario.get("takt_time_unit", "seconds"))
from utils.yamazumi_naming import (
    format_yamazumi_pitch_address,
    normalize_yamazumi_line_code,
    normalize_yamazumi_section_code,
)
time_config = time_unit(yamazumi_time_unit)
takt_config = time_unit(takt_time_unit)
time_column_label = f"Time ({time_config.label.lower()})"


def element_times_to_seconds(rows: pd.DataFrame) -> pd.DataFrame:
    converted = rows.copy()
    numeric = pd.to_numeric(converted["time_s"], errors="coerce")
    if numeric.isna().any() or (numeric < 0).any() or not numeric.map(math.isfinite).all():
        raise ValueError(
            "Time to complete must be a finite number that is zero or greater."
        )
    converted["time_s"] = numeric * time_config.seconds_per_unit
    return converted

page_title_with_scope(
    "Yamazumi", scope="scenario", scenario_name=scenario["name"]
)
st.caption(
    "Draft work directly, balance one operator per physical pitch, and route every change to IE review before updating Process at a Glance."
)

pitch_address_conflicts = yamazumi_pitch_address_conflicts(
    project_id, scenario_id
)
if not pitch_address_conflicts.empty:
    st.error(
        "Duplicate pitch addresses must be corrected before additional pitch "
        "changes can be saved in this planning scenario."
    )
    st.caption(
        "Choose one affected Yamazumi area at a time and rename or delete the "
        "duplicate pitch. Existing records are never changed automatically."
    )
    selectable_dataframe(
        pitch_address_conflicts,
        key=f"yamazumi_pitch_address_conflicts_{scenario_id}",
        hide_index=True,
        column_order=["pitch_number", "pitch_name", "area_name"],
        column_config={
            "id": None,
            "area_id": None,
            "pitch_number": st.column_config.TextColumn("Pitch address"),
            "pitch_name": st.column_config.TextColumn("Pitch name"),
            "area_name": st.column_config.TextColumn("Yamazumi area"),
        },
    )

has_yamazumi_areas = not yamazumi_areas(project_id, scenario_id).empty


with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center"):
    st.caption(
        f"Rev {scenario['revision_label']} · {scenario['name']} · "
        f"{format_seconds(scenario['takt_time_s'], scenario['takt_time_unit'])} takt"
    )
    request_clear_area = st.button(
        "Clear this Yamazumi Section",
        type="primary",
        icon=":material/delete_sweep:",
        help="Remove the selected Yamazumi section's pitches, work elements, and settings only.",
        disabled=not has_yamazumi_areas,
        key="destructive_request_clear_yamazumi_section",
    )
    request_clear_all = st.button(
        "Clear all Yamazumi data",
        type="primary",
        icon=":material/delete_forever:",
        help="Remove every Yamazumi area, pitch, work element, and Yamazumi setting in this scenario.",
        disabled=not has_yamazumi_areas,
        key="destructive_request_clear_all_yamazumi_data",
    )

area_selector_key = f"yamazumi_area_{scenario_id}"
sections = assembly_section_walk_order(project_id)
features = complexity_features(project_id)
active_features = (
    features.loc[features["active"].fillna(1).astype(bool)].copy()
    if not features.empty else features
)
defined_variant_options = ["Base"]
stored_variant_labels: dict[str, str] = {}
for _, feature in active_features.iterrows():
    for choice in json.loads(feature["allowed_values"] or "[]"):
        short_label = f"{feature['name']} = {choice}"
        long_label = f"{feature['category']} · {feature['name']} = {choice}"
        defined_variant_options.append(short_label)
        stored_variant_labels[long_label] = short_label
defined_variant_options = list(dict.fromkeys(defined_variant_options))
variant_rename_result = rename_yamazumi_variants(
    project_id, scenario_id, stored_variant_labels
)
if variant_rename_result["changed_count"]:
    record_audit_event(
        project_id,
        "Yamazumi variants",
        "Automatic variant rename",
        int(variant_rename_result["changed_count"]),
        st.session_state.get("current_editor", ""),
        {
            "scenario_id": scenario_id,
            "element_changes": variant_rename_result["element_changes"],
            "pitch_changes": variant_rename_result["pitch_changes"],
        },
    )
active_sections = sections.loc[sections["active"].fillna(1).astype(bool)].copy() if not sections.empty else sections
fishbone_sections = active_sections
section_name_by_id = dict(zip(active_sections["id"].astype(str), active_sections["name"].astype(str))) if not active_sections.empty else {}
section_option_labels = section_breadcrumb_labels(sections)
section_id_by_name = {name: section_id for section_id, name in section_name_by_id.items()}


def order_areas_by_fishbone(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows
    section_ids = (
        sections["id"].astype(str).tolist()
        if "id" in sections.columns
        else []
    )
    area_ids = ordered_yamazumi_area_ids(
        rows, section_ids
    )
    return (
        rows.assign(_area_id=rows["id"].astype(str))
        .set_index("_area_id", drop=False)
        .loc[area_ids]
        .drop(columns=["_area_id"])
        .reset_index(drop=True)
    )

with st.expander("Import Yamazumi workbook", icon=":material/upload_file:"):
    uploaded = st.file_uploader(
        "Yamazumi Excel file", type=["xlsx"], key=f"yamazumi_import_file_{scenario_id}"
    )
    st.caption(
        f"Imports the current system-style fields. Pitch_Takt_time is interpreted as {takt_config.label.lower()}, "
        f"and Work_Time_to_complete as {time_config.label.lower()}. "
        "Sub-Line is matched to a Fishbone section by name when possible; "
        "unmatched areas remain available to link manually."
    )
    if st.button("Import workbook", type="primary", icon=":material/upload:", disabled=uploaded is None):
        try:
            rows = pd.read_excel(uploaded)
            area_count, pitch_count, element_count = import_yamazumi_rows(
                project_id, scenario_id, rows, section_id_by_name
            )
            record_audit_event(
                project_id, "Yamazumi", "Excel import", element_count,
                st.session_state.get("current_editor", ""),
                {
                    "areas": area_count,
                    "pitches": pitch_count,
                    "file": uploaded.name,
                    "takt_time_unit": takt_time_unit,
                    "work_time_unit": yamazumi_time_unit,
                },
            )
            st.toast(f"Imported {element_count} work elements into {pitch_count} pitches", icon=":material/check_circle:")
            st.rerun()
        except (ValueError, TypeError) as exc:
            st.error(str(exc))

areas = order_areas_by_fishbone(yamazumi_areas(project_id, scenario_id))
if fishbone_sections.empty and areas.empty:
    st.info("Build an active Fishbone section first, or import a Yamazumi workbook to create an unlinked Yamazumi area.")
    st.stop()

if not fishbone_sections.empty:
    link_status = yamazumi_area_link_status(project_id, scenario_id)
    if link_status["needs_sync"] and st.button(
        "Repair Fishbone area links",
        icon=":material/build:",
        help=(
            "Repairs legacy missing, mismatched, or duplicate Fishbone links in this scenario. "
            "New Fishbone sections create their Yamazumi areas automatically."
        ),
    ):
        try:
            summary = sync_yamazumi_areas_from_fishbone(project_id, scenario_id)
            st.toast(
                f"Fishbone areas synchronized: {summary['created']} created, "
                f"{summary['relinked']} relinked, and {summary['conflicts_cleared']} conflicts cleared",
                icon=":material/check_circle:",
            )
            record_audit_event(
                project_id,
                "Yamazumi",
                "Repair Fishbone area links",
                summary["created"] + summary["relinked"] + summary["conflicts_cleared"],
                st.session_state.get("current_editor", ""),
                summary,
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

areas = order_areas_by_fishbone(yamazumi_areas(project_id, scenario_id))
if areas.empty:
    st.info("Create an area from the Fishbone or import a workbook to begin.")
    st.stop()

area_labels = {}
for _, row in areas.iterrows():
    section_id = normalized_id(row.get("section_id"))
    section_name_value = row.get("section_name")
    section_name = (
        "" if section_name_value is None or pd.isna(section_name_value)
        else str(section_name_value).strip()
    )
    fishbone_label = section_option_labels.get(section_id, section_name)
    area_labels[str(row["id"])] = (
        f"{row['name']} · Fishbone: {fishbone_label}" if section_name
        else f"{row['name']} · Unlinked"
    )
area_id = st.selectbox(
    "Yamazumi area",
    options=list(area_labels),
    index=None if area_selector_key in st.session_state else 0,
    format_func=lambda value: area_labels[value],
    key=area_selector_key,
)
area = areas.loc[areas["id"].astype(str) == str(area_id)].iloc[0].to_dict()
pitch_editor_key = f"yamazumi_pitch_editor_{scenario_id}_{area_id}"
element_editor_key = f"yamazumi_element_editor_{scenario_id}_{area_id}"
pitch_delete_key = f"yamazumi_pitches_pending_delete_{scenario_id}_{area_id}"
element_delete_key = f"yamazumi_elements_pending_delete_{scenario_id}_{area_id}"
empty_pitch_dialog_key = (
    f"yamazumi_empty_pitch_prompt_{project_id}_{scenario_id}_{area_id}"
)
pitch_editor_key = apply_pending_table_editor_reset(pitch_editor_key)
element_editor_key = apply_pending_table_editor_reset(element_editor_key)

default_takt = float(scenario.get("takt_time_s") or 0)
if not math.isfinite(default_takt):
    default_takt = 0.0
area_takt_value = area.get("takt_override_s")
area_takt = (
    default_takt
    if area_takt_value is None or pd.isna(area_takt_value)
    else float(area_takt_value)
)
if not math.isfinite(area_takt):
    area_takt = default_takt

section_id_value = area.get("section_id")
current_section_id = (
    None if section_id_value is None or pd.isna(section_id_value)
    else str(section_id_value).strip() or None
)
linked_elsewhere = {
    str(value) for value in areas["section_id"].dropna().astype(str).tolist()
    if str(value).strip()
}
available_sections = [
    section_id for section_id in section_name_by_id
    if section_id not in linked_elsewhere
]

settings_controls = st.container(horizontal=True, vertical_alignment="bottom")
selected_time_unit = settings_controls.segmented_control(
    "Yamazumi time unit",
    options=list(TIME_UNITS),
    default=yamazumi_time_unit,
    format_func=lambda value: TIME_UNITS[value].label,
    help=(
        "Controls Yamazumi time entry, board labels, and workbook values for this "
        "planning scenario. Timing records continue to be stored in seconds."
    ),
    key=f"yamazumi_time_unit_{scenario_id}",
)
takt_time = settings_controls.number_input(
    f"Yamazumi takt time ({takt_config.label.lower()})",
    min_value=0.0,
    value=seconds_to_display(area_takt, takt_time_unit),
    step=takt_config.step,
    format=f"%.{takt_config.decimals}f",
    help="Enter an area-specific takt or use the active planning scenario's target takt.",
    key=f"yamazumi_takt_{scenario_id}_{area_id}_{takt_time_unit}",
)
if current_section_id:
    linked_section = current_section_id
else:
    linked_section = settings_controls.selectbox(
        "Pair with Fishbone section",
        options=[None, *available_sections],
        format_func=lambda value: (
            "Unlinked" if value is None else section_option_labels.get(value, value)
        ),
        help="Manual matching is available only for imported areas that could not be matched by name.",
        key=f"linked_fishbone_for_import_{area_id}",
    )

selected_time_unit = normalize_time_unit(selected_time_unit)
entered_takt_s = (
    display_to_seconds(takt_time, takt_time_unit)
    if takt_time else default_takt
)
submitted_takt_override = (
    None
    if math.isclose(entered_takt_s, default_takt, rel_tol=1e-9, abs_tol=1e-9)
    else entered_takt_s
)
stored_takt_override = (
    None
    if area_takt_value is None or pd.isna(area_takt_value)
    else float(area_takt_value)
)
settings_changed = (
    selected_time_unit != yamazumi_time_unit
    or submitted_takt_override != stored_takt_override
    or linked_section != current_section_id
)
save_settings = settings_controls.button(
    "Save & Refresh",
    type="primary",
    icon=":material/save:",
    disabled=not settings_changed,
    key=f"save_yamazumi_settings_{scenario_id}_{area_id}",
)
if save_settings:
    try:
        time_unit_changed = selected_time_unit != yamazumi_time_unit
        if time_unit_changed:
            has_pending_time_edits = (
                table_has_unsaved_changes(
                    element_editor_key, native_row_selection=True
                )
                or bool(st.session_state.get(pitch_delete_key))
                or bool(st.session_state.get(element_delete_key))
                or bool(st.session_state.get(
                    f"yamazumi_add_element_target_{project_id}_{area_id}"
                ))
                or bool(st.session_state.get(
                    f"yamazumi_edit_element_target_{project_id}_{area_id}"
                ))
            )
            if has_pending_time_edits:
                raise ValueError(
                    "Save or undo Yamazumi work-element edits before changing the time unit."
                )
        result = update_yamazumi_settings(
            project_id,
            scenario_id,
            area_id,
            selected_time_unit,
            linked_section,
            submitted_takt_override,
            st.session_state.get("current_editor", ""),
        )
        if result["time_unit_changed"]:
            request_table_editor_reset(element_editor_key)
        st.toast("Saved Yamazumi settings", icon=":material/check_circle:")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

takt = submitted_takt_override if submitted_takt_override is not None else default_takt

if request_clear_area:
    st.session_state["yamazumi_reset_scope"] = "area"
if request_clear_all:
    st.session_state["yamazumi_reset_scope"] = "all"


@st.dialog("Clear Yamazumi data?")
def confirm_yamazumi_reset() -> None:
    scope = st.session_state.get("yamazumi_reset_scope")
    if scope == "all":
        st.warning(
            "This will permanently remove every Yamazumi area, pitch, work element, takt time, and pending IE review item in this scenario."
        )
    else:
        st.warning(
            f"This will permanently remove the Yamazumi area **{area['name']}**, including all of its pitches, work elements, takt time, and pending IE review items."
        )
    st.caption("Fishbone sections and existing Process at a Glance records will not be deleted or changed.")
    confirmation = st.text_input(
        "Type CLEAR to confirm",
        key="yamazumi_reset_confirmation",
        placeholder="CLEAR",
    )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_yamazumi_reset"):
        st.session_state.pop("yamazumi_reset_scope", None)
        st.rerun()
    if actions.button(
        "Clear Yamazumi data",
        type="primary",
        icon=":material/delete_forever:",
        disabled=confirmation.strip() != "CLEAR",
        key="destructive_confirm_yamazumi_reset",
    ):
        counts = clear_yamazumi_data(
            project_id, scenario_id, area_id if scope == "area" else None
        )
        record_audit_event(
            project_id,
            "Yamazumi",
            "Clear area" if scope == "area" else "Clear all",
            counts["elements"],
            st.session_state.get("current_editor", ""),
            counts,
        )
        for key in (
            "yamazumi_reset_scope", area_selector_key,
            pitch_editor_key, element_editor_key,
        ):
            st.session_state.pop(key, None)
        st.toast(
            f"Cleared {counts['areas']} area(s), {counts['pitches']} pitch(es), and {counts['elements']} work element(s)",
            icon=":material/delete_sweep:",
        )
        st.rerun()


if st.session_state.get("yamazumi_reset_scope") in {"area", "all"}:
    confirm_yamazumi_reset()

pitches = yamazumi_pitches(project_id, area_id)
pitch_address_suggestion = yamazumi_pitch_address_suggestion(project_id, area_id)
empty_pitch_visit_key = f"yamazumi_empty_pitch_visit_{project_id}_{scenario_id}"
if st.session_state.get(empty_pitch_visit_key) != str(area_id):
    st.session_state[empty_pitch_visit_key] = str(area_id)
    if pitches.empty:
        st.session_state[empty_pitch_dialog_key] = True
if not pitches.empty:
    st.session_state.pop(empty_pitch_dialog_key, None)
if not pitches.empty:
    pitches["model_variants"] = pitches["model_variants"].apply(
        lambda value: [stored_variant_labels.get(item, item) for item in json.loads(value or '["Base"]')]
    )
elements = yamazumi_elements(project_id, area_id)
criticality_by_work_element = work_element_criticality(project_id, scenario_id)


def criticality_for_process_link(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return list(criticality_by_work_element.get(str(value), []))


if not elements.empty:
    elements["model_variants"] = elements.apply(
        lambda row: [
            stored_variant_labels.get(item, item)
            for item in parse_yamazumi_model_variants(
                row.get("model_variants"), str(row.get("model_variant") or "Base")
            )
        ],
        axis=1,
    )
    elements["model_variant"] = elements["model_variants"].apply(
        lambda values: values[0] if values else "Base"
    )
    elements["criticality"] = elements["process_element_id"].apply(
        criticality_for_process_link
    )

region_definitions = yamazumi_work_regions(project_id, area_id)
defined_work_regions = (
    set(
        region_definitions.loc[
            region_definitions["active"].fillna(1).astype(bool), "name"
        ].dropna().astype(str)
    )
    if not region_definitions.empty else set()
)
legacy_work_regions = sorted(
    {
        str(value).strip()
        for value in elements.get("work_region", pd.Series(dtype=str)).dropna()
        if str(value).strip() and str(value).strip() != "None" and str(value).strip() not in defined_work_regions
    }
)
work_region_options = ["None", *sorted(defined_work_regions), *legacy_work_regions]
legacy_variant_options = [
    value
    for values in elements.get("model_variants", pd.Series(dtype=object))
    for value in (values or [])
    if value not in defined_variant_options
]
variant_options = list(dict.fromkeys([*defined_variant_options, *legacy_variant_options]))
variants = variant_options
pitch_variants_by_id = {
    str(row["id"]): list(row["model_variants"] or ["Base"])
    for _, row in pitches.iterrows()
}
feed_target_label_by_id = {
    str(row["id"]): yamazumi_pitch_label(row["pitch_number"], row["pitch_name"])
    for _, row in pitches.iterrows()
}


def feed_target_picker(
    label: str,
    *,
    source_pitch_id: str | None,
    current_target_id: str | None,
    key: str,
):
    target_ids = [
        pitch_id for pitch_id in feed_target_label_by_id
        if pitch_id != str(source_pitch_id or "")
    ]
    options = [None, *target_ids]
    current_value = (
        current_target_id if current_target_id in target_ids else None
    )
    return st.selectbox(
        label,
        options=options,
        index=options.index(current_value),
        format_func=lambda value: (
            "Select a feed target"
            if value is None
            else feed_target_label_by_id[value]
        ),
        help="Required for Subassembly and Kitter pitches. Targets are limited to this Yamazumi area.",
        key=key,
    )

def pitch_range_controls(surface: str) -> bool:
    """Render the shared guided pitch-range workflow."""
    st.caption(
        "Addresses use the suggested project and Fishbone codes. Suggestions are "
        "editable and do not restrict imported or existing addresses."
    )
    code_controls = st.container(horizontal=True, vertical_alignment="bottom")
    line_code = code_controls.text_input(
        "Project line code",
        value=pitch_address_suggestion["line_code"],
        max_chars=2,
        help="Saved project-wide for future Yamazumi address suggestions.",
        key=f"yamazumi_line_code_{surface}_{project_id}_{area_id}",
    )
    section_code = code_controls.text_input(
        "Fishbone section code",
        value=pitch_address_suggestion["section_code"],
        max_chars=3,
        help="Suggested from the linked Fishbone section and editable before generation.",
        key=f"yamazumi_section_code_{surface}_{project_id}_{area_id}",
    )
    sequence_controls = st.container(horizontal=True, vertical_alignment="bottom")
    start_number = sequence_controls.number_input(
        "Starting sequence",
        min_value=1,
        max_value=9999,
        value=int(pitch_address_suggestion["next_number"]),
        step=1,
        key=f"yamazumi_range_start_{surface}_{project_id}_{area_id}",
    )
    stop_number = sequence_controls.number_input(
        "Ending sequence",
        min_value=1,
        max_value=9999,
        value=int(pitch_address_suggestion["next_number"]),
        step=1,
        key=f"yamazumi_range_stop_{surface}_{project_id}_{area_id}",
    )
    number_mode = sequence_controls.selectbox(
        "Numbers to create",
        ["All numbers", "Odd only", "Even only"],
        key=f"yamazumi_range_mode_{surface}_{project_id}_{area_id}",
    )
    detail_controls = st.container(horizontal=True, vertical_alignment="bottom")
    generated_status = detail_controls.selectbox(
        "Starting status",
        ["Active", "Open", "Blocked"],
        help="Open and Blocked addresses cannot receive work until changed to Active.",
        key=f"yamazumi_range_status_{surface}_{project_id}_{area_id}",
    )
    available_pitch_types = (
        PITCH_TYPES
        if not pitches.empty
        else ["Pitch", "Waterspider", "Repacker"]
    )
    generated_pitch_type = detail_controls.selectbox(
        "Pitch type",
        available_pitch_types,
        key=f"yamazumi_range_type_{surface}_{project_id}_{area_id}",
    )
    if pitches.empty:
        st.caption(
            "Create a receiving pitch first. Subassembly and Kitter become available "
            "after this area has a valid feed target."
        )
    generated_feed_target_id = None
    if generated_pitch_type in {"Subassembly", "Kitter"}:
        generated_feed_target_id = feed_target_picker(
            "Feeds into pitch",
            source_pitch_id=None,
            current_target_id=None,
            key=f"generated_feed_target_{surface}_{scenario_id}_{area_id}",
        )
    generated_variants = st.multiselect(
        "Model variants shown on generated pitches",
        options=variant_options,
        default=["Base"],
        help="Every generated pitch starts with these visible variant stacks.",
        key=f"yamazumi_range_variants_{surface}_{project_id}_{area_id}",
    )
    try:
        preview_first = format_yamazumi_pitch_address(
            line_code, section_code, start_number
        )
        preview_last = format_yamazumi_pitch_address(
            line_code, section_code, stop_number
        )
        st.caption(f"Preview: {preview_first} through {preview_last}")
    except ValueError:
        preview_first = preview_last = ""
    address_controls = st.container(horizontal=True, vertical_alignment="bottom")
    first_pitch = address_controls.text_input(
        "First pitch address",
        value=preview_first,
        help="Prefilled from the naming suggestion and editable before generation.",
        key=(
            f"yamazumi_first_address_{surface}_{project_id}_{area_id}_"
            f"{line_code}_{section_code}_{start_number}"
        ),
    )
    last_pitch = address_controls.text_input(
        "Last pitch address",
        value=preview_last,
        help="Uses the same editable prefix and an inclusive ending number.",
        key=(
            f"yamazumi_last_address_{surface}_{project_id}_{area_id}_"
            f"{line_code}_{section_code}_{stop_number}"
        ),
    )

    if not st.button(
        "Generate pitches",
        type="primary",
        icon=":material/add:",
        key=f"generate_yamazumi_range_{surface}_{project_id}_{area_id}",
    ):
        return False
    try:
        normalized_line_code = normalize_yamazumi_line_code(line_code)
        normalize_yamazumi_section_code(section_code)
        before_generated_ids = set(pitches["id"].astype(str))
        created, skipped_addresses = generate_yamazumi_pitch_range(
            project_id,
            area_id,
            first_pitch,
            last_pitch,
            number_mode,
            generated_status,
            generated_variants,
            generated_pitch_type,
            generated_feed_target_id,
            project_line_code=normalized_line_code,
        )
        generated_rows = yamazumi_pitches(project_id, area_id)
        generated_rows = generated_rows.loc[
            ~generated_rows["id"].astype(str).isin(before_generated_ids)
        ]
        feed_relationship_changes = [
            {
                "source_pitch_id": str(row["id"]),
                "source_pitch_address": str(row["pitch_number"]),
                "old_feeds_into_pitch_id": None,
                "old_feed_target": None,
                "new_feeds_into_pitch_id": generated_feed_target_id,
                "new_feed_target": feed_target_label_by_id.get(
                    str(generated_feed_target_id), ""
                ),
            }
            for _, row in generated_rows.iterrows()
            if generated_feed_target_id
        ]
        old_line_code = pitch_address_suggestion["line_code"]
        record_audit_event(
            project_id,
            "Yamazumi pitches",
            "Generate range",
            created,
            st.session_state.get("current_editor", ""),
            {
                "area_id": area_id,
                "first": first_pitch,
                "last": last_pitch,
                "number_mode": number_mode,
                "status": generated_status,
                "pitch_type": generated_pitch_type,
                "variants": generated_variants,
                "old_project_line_code": old_line_code,
                "new_project_line_code": normalized_line_code,
                "skipped_addresses": skipped_addresses,
                "new_feeds_into_pitch_id": generated_feed_target_id,
                "new_feed_target": feed_target_label_by_id.get(
                    str(generated_feed_target_id), ""
                ),
                "feed_relationship_changes": feed_relationship_changes,
            },
        )
        result_message = f"Generated {created} new pitch addresses"
        if skipped_addresses:
            result_message += (
                f"; skipped {len(skipped_addresses)} existing address(es)"
            )
        st.toast(result_message, icon=":material/check_circle:")
        return True
    except ValueError as exc:
        st.error(str(exc))
        return False


@st.dialog("Set up pitch addresses", dismissible=False)
def empty_pitch_setup_dialog() -> None:
    st.write("This Yamazumi area has no pitch addresses yet.")
    if pitch_range_controls("empty_dialog"):
        st.session_state.pop(empty_pitch_dialog_key, None)
        request_table_editor_reset(pitch_editor_key)
        st.rerun()
    if st.button(
        "Cancel",
        key=f"cancel_empty_pitch_setup_{project_id}_{scenario_id}_{area_id}",
    ):
        st.session_state.pop(empty_pitch_dialog_key, None)
        st.rerun()


setup_columns = st.columns(2)
with setup_columns[0].expander(
    "Generate pitch addresses",
    icon=":material/format_list_numbered:",
    expanded=pitches.empty,
):
    if pitch_range_controls("expander"):
        request_table_editor_reset(pitch_editor_key)
        st.rerun()

with setup_columns[1].expander("Define work regions", icon=":material/category:"):
    st.caption(
        "Define the area-specific categories used to classify work. Inactive regions remain on "
        "existing elements but cannot be assigned to new ones."
    )
    region_editor_key = f"yamazumi_region_editor_{area_id}"
    region_editor_key = apply_pending_table_editor_reset(region_editor_key)
    region_rows = region_definitions.reindex(
        columns=["id", "name", "description", "active", "color", "sequence", "updated_at"]
    )
    # Empty columns created by reindex default to float64. Streamlit then rejects
    # TextColumn configuration before the first work region can be added.
    region_rows["name"] = region_rows["name"].astype("string").fillna("")
    region_rows["description"] = region_rows["description"].astype("string").fillna("")
    region_rows["active"] = region_rows["active"].fillna(1).astype(bool)

    editable_table_heading("Work regions")
    visible_regions = filter_table(
        region_rows,
        key=f"yamazumi_region_filters_{area_id}",
        dropdown_columns=["active"],
        search_columns=["name", "description"],
        labels={"active": "Active"},
        reset_widget_keys=[region_editor_key],
    )
    region_editor_rows = direct_entry_editor_rows(
        visible_regions,
        editor_key=region_editor_key,
        sort_columns=["name", "description", "active"],
        labels={"name": "Work region name"},
    )
    region_action_slot = st.empty()
    edited_regions = st.data_editor(
        region_editor_rows,
        key=region_editor_key,
        hide_index=True,
        num_rows="dynamic",
        height=300,
        disabled=["id", "color", "sequence", "updated_at"],
        column_order=["name", "description", "active"],
        column_config={
            "id": None,
            "name": st.column_config.TextColumn(
                "Work region name", required=True, pinned=True
            ),
            "description": st.column_config.TextColumn("Description", width="large"),
            "active": st.column_config.CheckboxColumn("Active", default=True),
            "color": None,
            "sequence": None,
            "updated_at": None,
        },
    )
    region_actions = editable_table_footer(
        editor_key=region_editor_key,
        key_prefix=f"yamazumi_regions_{area_id}",
        native_row_selection=True,
    )

    selected_regions = native_selected_rows(
        region_editor_rows, editor_key=region_editor_key
    )
    region_bulk = selected_rows_action_bar(
        parent=region_action_slot,
    )
    bulk_region_active = region_bulk.selectbox(
        "Active for selected regions",
        [None, True, False],
        format_func=lambda value: (
            "No change" if value is None else ("Active" if value else "Inactive")
        ),
        key=f"yamazumi_region_bulk_active_{area_id}",
    )
    apply_region_bulk = region_bulk.button(
        f"Apply to selected ({len(selected_regions)})",
        type="primary",
        icon=":material/checklist:",
        disabled=selected_regions.empty,
        key=f"apply_yamazumi_region_bulk_{area_id}",
    )
    request_region_delete = not selected_regions.empty
    region_bulk.download_button(
        "Export filtered",
        data=dataframe_to_excel(
            visible_regions[["name", "description", "active"]],
            "Work regions",
        ),
        file_name="yamazumi_work_regions_filtered.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        key=f"export_yamazumi_regions_{area_id}",
    )

    def region_records_from(dataframe: pd.DataFrame) -> list[dict]:
        return dataframe.to_dict("records")

    if apply_region_bulk:
        if table_has_unsaved_changes(region_editor_key, native_row_selection=True):
            st.warning("Save or undo other work-region edits before applying a bulk change.")
        elif bulk_region_active is None:
            st.warning("Choose Active or Inactive to apply.")
        else:
            updated_regions = region_rows.copy()
            selected_ids = set(selected_regions["id"].astype(str))
            updated_regions.loc[
                updated_regions["id"].astype(str).isin(selected_ids), "active"
            ] = bulk_region_active
            count = replace_yamazumi_work_regions(
                project_id, area_id, region_records_from(updated_regions)
            )
            record_audit_event(
                project_id,
                "Yamazumi work regions",
                "Bulk edit",
                len(selected_ids),
                st.session_state.get("current_editor", ""),
                {"active": bulk_region_active},
            )
            request_table_editor_reset(region_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast(f"Updated {len(selected_ids)} work regions", icon=":material/check_circle:")
            st.rerun()

    if request_region_delete:
        if table_has_unsaved_changes(region_editor_key, native_row_selection=True):
            st.warning("Save or undo other work-region edits before deleting selected regions.")
        else:
            st.session_state[f"yamazumi_regions_pending_delete_{area_id}"] = (
                selected_regions["id"].astype(str).tolist()
            )
            stage_native_delete_confirmation(region_editor_key)

    @st.dialog("Delete selected work regions?", dismissible=False)
    def confirm_region_delete() -> None:
        pending_key = f"yamazumi_regions_pending_delete_{area_id}"
        pending_ids = st.session_state.get(pending_key, [])
        st.warning(
            f"Delete {len(pending_ids)} work region(s)? Existing elements using them will be "
            "changed to None."
        )
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_yamazumi_region_delete_{area_id}"):
            st.session_state.pop(pending_key, None)
            request_table_editor_reset(region_editor_key)
            st.rerun()
        if actions.button(
            "Delete regions",
            type="primary",
            icon=":material/delete:",
            key=f"destructive_confirm_yamazumi_region_delete_{area_id}",
        ):
            kept_regions = region_rows.loc[
                ~region_rows["id"].astype(str).isin(set(pending_ids))
            ]
            count = replace_yamazumi_work_regions(
                project_id, area_id, region_records_from(kept_regions)
            )
            record_audit_event(
                project_id,
                "Yamazumi work regions",
                "Bulk delete",
                len(pending_ids),
                st.session_state.get("current_editor", ""),
            )
            st.session_state.pop(pending_key, None)
            request_table_editor_reset(region_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast(f"Deleted {len(pending_ids)} work regions", icon=":material/delete:")
            st.rerun()

    if st.session_state.get(f"yamazumi_regions_pending_delete_{area_id}"):
        confirm_region_delete()

    if region_actions.undo:
        request_table_editor_reset(region_editor_key)
        st.rerun()

    if region_actions.save_and_refresh:
        try:
            if not selected_regions.empty:
                raise ValueError("Clear selected rows before saving work-region edits.")
            edited_regions = drop_untouched_new_rows(
                edited_regions, identifying_columns=["name"]
            )
            errors = required_field_errors(
                edited_regions, {"name": "Work region name"}
            )
            if errors:
                raise ValueError(" ".join(errors))
            combined_regions = merge_filtered_edits(
                region_rows, visible_regions, edited_regions
            )
            count = replace_yamazumi_work_regions(
                project_id, area_id, region_records_from(combined_regions)
            )
            record_audit_event(
                project_id, "Yamazumi work regions", "Save & Refresh", count,
                st.session_state.get("current_editor", ""),
            )
            request_table_editor_reset(region_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast(f"Saved {count} work-region definition(s)", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

times = pd.to_numeric(elements.get("time_s", pd.Series(dtype=float)), errors="coerce").fillna(0)
total_work = float(times.sum())
active_pitch_count = int((pitches["status"] == "Active").sum()) if not pitches.empty else 0
theoretical = total_work / takt if takt > 0 else 0
efficiency = total_work / (active_pitch_count * takt) * 100 if active_pitch_count and takt > 0 else 0
pitch_totals = elements.assign(time_s=times).groupby("pitch_number", dropna=True)["time_s"].sum() if not elements.empty else pd.Series(dtype=float)
bottleneck = str(pitch_totals.idxmax()) if not pitch_totals.empty else "—"

metrics = st.container(horizontal=True)
metrics.metric(
    "Total work content",
    format_seconds(total_work, yamazumi_time_unit),
    border=True,
)
metrics.metric("Theoretical operators", f"{theoretical:.2f}", border=True)
metrics.metric("Active pitches / operators", active_pitch_count, border=True)
metrics.metric("Line balance efficiency", f"{efficiency:.1f}%", border=True)
metrics.metric("Bottleneck pitch", bottleneck, border=True)
metrics.metric("Takt", format_seconds(takt, takt_time_unit), border=True)

board_key = f"yamazumi_board_{project_id}_{area_id}"
board_draft_key = f"yamazumi_board_draft_{project_id}_{scenario_id}_{area_id}"
board_draft_error_key = f"yamazumi_board_draft_error_{project_id}_{scenario_id}_{area_id}"
add_pitch_dialog_key = f"yamazumi_show_add_pitch_{project_id}_{area_id}"
add_element_dialog_key = f"yamazumi_add_element_target_{project_id}_{area_id}"
edit_pitch_dialog_key = f"yamazumi_edit_pitch_target_{project_id}_{area_id}"
edit_element_dialog_key = f"yamazumi_edit_element_target_{project_id}_{area_id}"
gui_pitch_delete_key = f"yamazumi_gui_pitch_pending_delete_{project_id}_{scenario_id}_{area_id}"
gui_element_delete_key = f"yamazumi_gui_element_pending_delete_{project_id}_{scenario_id}_{area_id}"
pitch_edit_restore_key = f"yamazumi_gui_pitch_edit_restore_{project_id}_{scenario_id}_{area_id}"
element_edit_restore_key = f"yamazumi_gui_element_edit_restore_{project_id}_{scenario_id}_{area_id}"
delete_element_dialog_key = f"yamazumi_delete_element_target_{project_id}_{area_id}"


def close_other_yamazumi_dialogs(keep: str) -> None:
    """Guarantee that only one Streamlit dialog is eligible in a script run."""
    for dialog_key in (
        empty_pitch_dialog_key,
        add_pitch_dialog_key,
        add_element_dialog_key,
        edit_pitch_dialog_key,
        edit_element_dialog_key,
        delete_element_dialog_key,
    ):
        if dialog_key != keep:
            st.session_state.pop(dialog_key, None)


def handle_yamazumi_move() -> None:
    state = st.session_state.get(board_key)
    move = getattr(state, "move", None) if state is not None else None
    if not move and isinstance(state, dict):
        move = state.get("move")
    if not move:
        return
    persisted_elements = elements.to_dict("records")
    current_draft = st.session_state.get(board_draft_key)
    if not isinstance(current_draft, dict):
        current_draft = build_stack_draft(persisted_elements)
    try:
        updated_draft = apply_stack_drop(
            current_draft,
            element_id=str(move.get("element_id") or ""),
            pitch_id=move.get("pitch_id"),
            before_element_id=move.get("before_element_id"),
            after_element_id=move.get("after_element_id"),
            insert_index=move.get("insert_index"),
        )
        st.session_state.pop(board_draft_error_key, None)
        if draft_differs(persisted_elements, updated_draft):
            st.session_state[board_draft_key] = updated_draft
        else:
            st.session_state.pop(board_draft_key, None)
    except ValueError as exc:
        st.session_state[board_draft_error_key] = str(exc)


def handle_add_pitch_request() -> None:
    close_other_yamazumi_dialogs(add_pitch_dialog_key)
    st.session_state[add_pitch_dialog_key] = True


def handle_add_element_request() -> None:
    state = st.session_state.get(board_key)
    request = getattr(state, "add_element", None) if state is not None else None
    if not request and isinstance(state, dict):
        request = state.get("add_element")
    if request:
        close_other_yamazumi_dialogs(add_element_dialog_key)
        st.session_state[add_element_dialog_key] = dict(request)


def _board_trigger(name: str) -> dict:
    state = st.session_state.get(board_key)
    value = getattr(state, name, None) if state is not None else None
    if not value and isinstance(state, dict):
        value = state.get(name)
    return dict(value) if value else {}


def handle_edit_pitch_request() -> None:
    request = _board_trigger("edit_pitch")
    if request.get("pitch_id"):
        close_other_yamazumi_dialogs(edit_pitch_dialog_key)
        st.session_state[edit_pitch_dialog_key] = str(request["pitch_id"])


def handle_edit_element_request() -> None:
    request = _board_trigger("edit_element")
    if request.get("element_id"):
        close_other_yamazumi_dialogs(edit_element_dialog_key)
        st.session_state[edit_element_dialog_key] = str(request["element_id"])


@st.dialog("Add pitch")
def add_pitch_dialog() -> None:
    st.caption("The new address will appear on the north/top or south/bottom side based on its ending number.")
    pitch_number = st.text_input(
        "Pitch address",
        value=pitch_address_suggestion["suggested_address"],
        placeholder="01-ML1-001",
        help="Must be unique across every Yamazumi area in this planning scenario. Capitalization and surrounding spaces do not create a different address.",
        key=f"add_pitch_number_{project_id}_{scenario_id}_{area_id}",
    )
    pitch_name = st.text_input("Pitch name")
    status = st.selectbox("Status", ["Active", "Open", "Blocked"], index=0)
    pitch_type = st.selectbox("Pitch type", PITCH_TYPES, index=0)
    feed_target_id = None
    if pitch_type in {"Subassembly", "Kitter"}:
        feed_target_id = feed_target_picker(
            "Feeds into pitch",
            source_pitch_id=None,
            current_target_id=None,
            key=f"add_pitch_feed_target_{project_id}_{area_id}",
        )
    selected_pitch_variants = st.multiselect(
        "Model variants shown on this pitch",
        options=variant_options,
        default=["Base"],
        help="Only selected variants appear as stacks on this pitch.",
    )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_interactive_pitch"):
        st.session_state.pop(f"yamazumi_show_add_pitch_{project_id}_{area_id}", None)
        st.rerun()
    if actions.button("Add pitch", type="primary", icon=":material/add:", key="save_interactive_pitch"):
        try:
            new_pitch_id = add_yamazumi_pitch(
                project_id, area_id, pitch_number, pitch_name, status,
                selected_pitch_variants, pitch_type, feed_target_id,
            )
            record_audit_event(
                project_id, "Yamazumi pitches", "Add from interactive board", 1,
                st.session_state.get("current_editor", ""),
                {
                    "source_pitch_id": new_pitch_id,
                    "source_pitch_address": pitch_number,
                    "pitch_type": pitch_type,
                    "old_feeds_into_pitch_id": None,
                    "old_feed_target": None,
                    "new_feeds_into_pitch_id": feed_target_id,
                    "new_feed_target": feed_target_label_by_id.get(
                        str(feed_target_id), ""
                    ),
                },
            )
            st.session_state.pop(f"yamazumi_show_add_pitch_{project_id}_{area_id}", None)
            request_table_editor_reset(pitch_editor_key)
            st.toast(f"Added pitch {pitch_number}", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Add Yamazumi work element")
def add_element_dialog() -> None:
    target = st.session_state.get(f"yamazumi_add_element_target_{project_id}_{area_id}", {})
    target_pitch_id = target.get("pitch_id")
    st.caption(f"Destination: {target.get('pitch_number') or 'Unassigned'}")
    description = st.text_area("Work description", placeholder="Describe one measurable element of work")
    time_value = st.number_input(
        f"Time to complete ({time_config.label.lower()})",
        min_value=0.0,
        value=0.0,
        step=time_config.step,
        format=f"%.{time_config.decimals}f",
    )
    row = st.container(horizontal=True, vertical_alignment="bottom")
    work_type = row.selectbox("Work type", WORK_TYPES, index=0)
    work_region = row.selectbox("Work region", work_region_options, index=0)
    model_variants = st.multiselect(
        "Model variants",
        options=variant_options,
        default=["Base"],
        help=ADD_ELEMENT_VARIANT_HELP,
    )
    target_variants = pitch_variants_by_id.get(str(target_pitch_id), [])
    variants_added_to_pitch = [
        variant for variant in model_variants
        if target_pitch_id and variant not in target_variants
    ]
    if variants_added_to_pitch:
        st.caption(
            f"{', '.join(variants_added_to_pitch)} will also be added to pitch "
            f"{target.get('pitch_number') or ''} as a new Yamazumi stack."
        )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_interactive_element"):
        st.session_state.pop(f"yamazumi_add_element_target_{project_id}_{area_id}", None)
        st.rerun()
    if actions.button("Add element", type="primary", icon=":material/add:", key="save_interactive_element"):
        try:
            add_yamazumi_element(
                project_id,
                area_id,
                target_pitch_id,
                {
                    "description": description,
                    "time_s": display_to_seconds(time_value, yamazumi_time_unit),
                    "model_variants": model_variants,
                    "work_type": work_type,
                    "work_region": work_region,
                },
            )
            record_audit_event(
                project_id, "Yamazumi elements", "Add from interactive board", 1,
                st.session_state.get("current_editor", ""),
                {
                    "pitch": target.get("pitch_number"),
                    "description": description,
                    "model_variants": model_variants,
                    "variants_added_to_pitch": variants_added_to_pitch,
                },
            )
            st.session_state.pop(f"yamazumi_add_element_target_{project_id}_{area_id}", None)
            if variants_added_to_pitch:
                request_table_editor_reset(pitch_editor_key)
            request_table_editor_reset(element_editor_key)
            message = "Added Yamazumi work element"
            if variants_added_to_pitch:
                message += f" and enabled {', '.join(variants_added_to_pitch)} on the pitch"
            st.toast(message, icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Edit pitch")
def edit_pitch_dialog() -> None:
    state_key = f"yamazumi_edit_pitch_target_{project_id}_{area_id}"
    pitch_id = st.session_state.get(state_key)
    matches = pitches.loc[pitches["id"].astype(str) == str(pitch_id)]
    if matches.empty:
        st.warning("That pitch is no longer available.")
        if st.button("Close", key="close_missing_pitch"):
            st.session_state.pop(state_key, None)
            st.rerun()
        return
    current = matches.iloc[0]
    restored = st.session_state.pop(pitch_edit_restore_key, None)
    restored_values = (
        dict(restored.get("values") or {})
        if isinstance(restored, dict) and str(restored.get("id")) == str(pitch_id)
        else {}
    )
    current_variants = list(
        restored_values.get("model_variants")
        or current.get("model_variants")
        or ["Base"]
    )
    pitch_number = st.text_input(
        "Pitch address",
        value=str(restored_values.get("pitch_number", current.get("pitch_number")) or ""),
        help="Must be unique across every Yamazumi area in this planning scenario. Capitalization and surrounding spaces do not create a different address.",
        key=f"edit_pitch_number_{pitch_id}",
    )
    pitch_name = st.text_input(
        "Pitch name",
        value=str(restored_values.get("pitch_name", current.get("pitch_name")) or ""),
        key=f"edit_pitch_name_{pitch_id}",
    )
    statuses = ["Active", "Open", "Blocked"]
    current_status = str(restored_values.get("status", current.get("status")) or "Active")
    status = st.selectbox(
        "Status", statuses, index=statuses.index(current_status) if current_status in statuses else 0,
        key=f"edit_pitch_status_{pitch_id}",
    )
    current_pitch_type = str(
        restored_values.get("pitch_type", current.get("pitch_type")) or "Pitch"
    ).title()
    pitch_type = st.selectbox(
        "Pitch type", PITCH_TYPES,
        index=PITCH_TYPES.index(current_pitch_type) if current_pitch_type in PITCH_TYPES else 0,
        key=f"edit_pitch_type_{pitch_id}",
    )
    current_feed_target_id = (
        str(
            restored_values.get(
                "feeds_into_pitch_id", current.get("feeds_into_pitch_id")
            )
            or ""
        ).strip()
        or None
    )
    feed_target_id = None
    if pitch_type in {"Subassembly", "Kitter"}:
        if not current_feed_target_id:
            st.warning("Feed target required", icon=":material/link_off:")
        feed_target_id = feed_target_picker(
            "Feeds into pitch",
            source_pitch_id=str(pitch_id),
            current_target_id=current_feed_target_id,
            key=f"edit_pitch_feed_target_{pitch_id}",
        )
    selected_variants = st.multiselect(
        "Model variants shown on this pitch",
        options=list(dict.fromkeys([*variant_options, *current_variants])),
        default=current_variants,
        key=f"edit_pitch_variants_{pitch_id}",
        help="Existing work must be moved or retagged before its variant can be removed.",
    )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_edit_pitch_{pitch_id}"):
        st.session_state.pop(state_key, None)
        st.rerun()
    if actions.button("Save pitch", type="primary", icon=":material/save:", key=f"save_edit_pitch_{pitch_id}"):
        try:
            update_yamazumi_pitch(
                project_id, area_id, str(pitch_id),
                {
                    "pitch_number": pitch_number,
                    "pitch_name": pitch_name,
                    "status": status,
                    "model_variants": selected_variants,
                    "pitch_type": pitch_type,
                    "feeds_into_pitch_id": feed_target_id,
                },
            )
            record_audit_event(
                project_id, "Yamazumi pitches", "Edit from interactive board", 1,
                st.session_state.get("current_editor", ""),
                {
                    "source_pitch_id": pitch_id,
                    "source_pitch_address": pitch_number,
                    "old_feeds_into_pitch_id": current_feed_target_id,
                    "old_feed_target": feed_target_label_by_id.get(
                        str(current_feed_target_id), ""
                    ),
                    "new_feeds_into_pitch_id": feed_target_id,
                    "new_feed_target": feed_target_label_by_id.get(
                        str(feed_target_id), ""
                    ),
                },
            )
            st.session_state.pop(state_key, None)
            request_table_editor_reset(pitch_editor_key)
            st.toast(f"Updated pitch {pitch_number}", icon=":material/check_circle:")
            st.rerun(scope="app")
        except ValueError as exc:
            st.error(str(exc))
    delete_pitch_request = actions.button(
        "Delete pitch…",
        icon=":material/delete:",
        key=f"request_delete_pitch_from_board_{pitch_id}",
        disabled=has_board_draft,
        help=(
            "Save or undo the unsaved board arrangement before deleting this pitch."
            if has_board_draft
            else "Review the relationship impact before deleting this pitch."
        ),
    )
    if has_board_draft:
        st.info("Use the board's Save & Refresh or Undo before deleting a pitch.")
    if delete_pitch_request:
        st.session_state.pop(state_key, None)
        st.session_state.pop(gui_element_delete_key, None)
        st.session_state[gui_pitch_delete_key] = {
            "id": str(pitch_id),
            "values": {
                "pitch_number": pitch_number,
                "pitch_name": pitch_name,
                "status": status,
                "pitch_type": pitch_type,
                "feeds_into_pitch_id": feed_target_id,
                "model_variants": list(selected_variants),
            },
        }
        st.rerun(scope="app")


def close_edit_element_dialog() -> None:
    st.session_state.pop(edit_element_dialog_key, None)


@st.dialog("Edit Yamazumi work element", on_dismiss=close_edit_element_dialog)
def edit_element_dialog(
    element_id: str, restored_values: dict[str, object] | None = None
) -> None:
    state_key = f"yamazumi_edit_element_target_{project_id}_{area_id}"
    matches = elements.loc[elements["id"].astype(str) == str(element_id)]
    if matches.empty:
        st.warning("That work element is no longer available.")
        if st.button("Close", key="close_missing_element"):
            st.session_state.pop(state_key, None)
            st.rerun()
        return
    current = matches.iloc[0]
    restored = st.session_state.pop(element_edit_restore_key, None)
    if isinstance(restored, dict) and str(restored.get("id")) == str(element_id):
        restored_values = dict(restored.get("values") or {})
    else:
        restored_values = dict(restored_values or {})
    active_pitches = pitches.loc[pitches["status"] == "Active"].copy()
    pitch_label_by_id = {
        str(row["id"]): f"{row['pitch_number']} — {row['pitch_name']}".rstrip(" —")
        for _, row in active_pitches.iterrows()
    }
    destinations = [None, *pitch_label_by_id]
    current_pitch_id = (
        str(restored_values.get("pitch_id", current.get("pitch_id")) or "") or None
    )
    with st.container():
        selected_pitch_id = st.selectbox(
            "Pitch",
            options=destinations,
            index=destinations.index(current_pitch_id) if current_pitch_id in destinations else 0,
            format_func=lambda value: "Unassigned" if value is None else pitch_label_by_id[value],
            key=f"edit_element_pitch_{element_id}",
        )
        description = st.text_area(
            "Work description",
            value=str(restored_values.get("description", current.get("description")) or ""),
            key=f"edit_element_description_{element_id}",
        )
        time_value = st.number_input(
            f"Time to complete ({time_config.label.lower()})",
            min_value=0.0,
            value=seconds_to_display(
                restored_values.get("time_s", current.get("time_s")) or 0,
                yamazumi_time_unit,
            ),
            step=time_config.step,
            format=f"%.{time_config.decimals}f",
            key=f"edit_element_time_{element_id}",
        )
        current_variants = list(
            restored_values.get("model_variants")
            or current.get("model_variants")
            or ["Base"]
        )
        available_variants = list(dict.fromkeys([*variant_options, *current_variants]))
        row = st.container(horizontal=True, vertical_alignment="bottom")
        model_variants = row.multiselect(
            "Model variants", available_variants, default=current_variants,
            help=ELEMENT_VARIANT_HELP,
            key=f"edit_element_variants_{element_id}",
        )
        current_work_type = str(
            restored_values.get("work_type", current.get("work_type")) or "Cycle"
        ).title()
        work_type = row.selectbox(
            "Work type", WORK_TYPES,
            index=WORK_TYPES.index(current_work_type) if current_work_type in WORK_TYPES else 0,
            key=f"edit_element_work_type_{element_id}",
        )
        current_work_region = str(
            restored_values.get("work_region", current.get("work_region")) or "None"
        )
        edit_region_options = list(dict.fromkeys([*work_region_options, current_work_region]))
        work_region = row.selectbox(
            "Work region", edit_region_options,
            index=edit_region_options.index(current_work_region),
            key=f"edit_element_work_region_{element_id}",
        )
        actions = st.container(horizontal=True)
        save_edit = actions.button(
            "Save element", type="primary", icon=":material/save:",
            key=f"save_edit_element_{element_id}",
        )
        delete_edit = actions.button(
            "Delete work element…",
            icon=":material/delete:",
            key=f"destructive_request_edit_element_delete_{element_id}",
            disabled=has_board_draft and "__unassigned__" in (board_draft or {}),
            help=(
                "Save or undo the unsaved board arrangement before deleting this work element."
                if has_board_draft
                else "Review the relationship impact before deleting this work element."
            ),
        )
        if has_board_draft:
            st.info("Use the board's Save & Refresh or Undo before deleting a work element.")
    if save_edit:
        try:
            update_yamazumi_element(
                project_id, area_id, str(element_id),
                {
                    "pitch_id": selected_pitch_id, "model_variants": model_variants, "work_type": work_type,
                    "description": description,
                    "time_s": display_to_seconds(time_value, yamazumi_time_unit),
                    "work_region": work_region,
                },
            )
            record_audit_event(
                project_id, "Yamazumi elements", "Edit from interactive board", 1,
                st.session_state.get("current_editor", ""), {"element_id": element_id, "description": description},
            )
            st.session_state.pop(state_key, None)
            request_table_editor_reset(element_editor_key)
            st.toast("Updated Yamazumi work element", icon=":material/check_circle:")
            st.rerun(scope="app")
        except ValueError as exc:
            st.error(str(exc))
    if delete_edit:
        close_other_yamazumi_dialogs(delete_element_dialog_key)
        st.session_state[delete_element_dialog_key] = {
            "element_id": str(element_id),
            "draft": {
                "pitch_id": selected_pitch_id,
                "description": description,
                "time_value": float(time_value),
                "model_variants": list(model_variants),
                "work_type": work_type,
                "work_region": work_region,
            },
        }
        st.rerun(scope="app")
    if delete_edit:
        st.session_state.pop(state_key, None)
        st.session_state.pop(gui_pitch_delete_key, None)
        st.session_state[gui_element_delete_key] = {
            "id": str(element_id),
            "values": {
                "pitch_id": selected_pitch_id,
                "description": description,
                "time_s": float(time_s),
                "model_variants": list(model_variants),
                "work_type": work_type,
                "work_region": work_region,
            },
        }
        st.rerun(scope="app")


@st.dialog("Delete pitch?", dismissible=False)
def confirm_gui_pitch_delete() -> None:
    pending = st.session_state.get(gui_pitch_delete_key, {})
    pitch_id = str(pending.get("id") or "")
    matches = pitches.loc[pitches["id"].astype(str) == pitch_id]
    if matches.empty:
        st.error("That pitch is no longer available in the active scenario.")
        if st.button("Close", key=f"close_missing_gui_pitch_{scenario_id}_{area_id}"):
            st.session_state.pop(gui_pitch_delete_key, None)
            st.rerun()
        return
    current = matches.iloc[0]
    pitch_label = str(current.get("pitch_number") or "Unnamed pitch")
    if current.get("pitch_name"):
        pitch_label += f" — {current['pitch_name']}"
    assigned_count = (
        int(elements["pitch_id"].fillna("").astype(str).eq(pitch_id).sum())
        if not elements.empty
        else 0
    )
    blockers = yamazumi_pitch_delete_blockers(project_id, area_id, [pitch_id])
    st.warning(
        f"Delete {pitch_label}? {assigned_count} assigned work element(s) will move "
        "to Unassigned; the work elements themselves will not be deleted."
    )
    if blockers:
        relationships = ", ".join(
            f"{yamazumi_pitch_label(row['source_pitch_number'], row['source_pitch_name'])} → "
            f"{yamazumi_pitch_label(row['target_pitch_number'], row['target_pitch_name'])}"
            for row in blockers
        )
        st.error(
            "Deletion is blocked while these feed relationships remain: "
            + relationships
            + ". Re-point the source pitches or change their type first."
        )
    if has_board_draft:
        st.error("Use the board's Save & Refresh or Undo before deleting this pitch.")
    editor_name = str(st.session_state.get("current_editor") or "").strip()
    if not editor_name:
        st.error("Enter the Current editor before deleting this pitch.")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_gui_pitch_delete_{pitch_id}"):
        st.session_state.pop(gui_pitch_delete_key, None)
        st.session_state[pitch_edit_restore_key] = pending
        close_other_yamazumi_dialogs(edit_pitch_dialog_key)
        st.session_state[edit_pitch_dialog_key] = pitch_id
        st.rerun()
    if actions.button(
        "Delete pitch",
        type="primary",
        icon=":material/delete:",
        key=f"destructive_gui_pitch_delete_{pitch_id}",
        disabled=bool(blockers) or has_board_draft or not editor_name,
    ):
        try:
            moved_count = delete_yamazumi_pitch(
                project_id,
                area_id,
                pitch_id,
                scenario_id=scenario_id,
                audit_editor_name=editor_name,
                audit_details={"source": "interactive_board_gui"},
            )
            st.session_state.pop(gui_pitch_delete_key, None)
            st.session_state.pop(pitch_edit_restore_key, None)
            request_table_editor_reset(pitch_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast(
                f"Deleted pitch; {moved_count} work element(s) moved to Unassigned",
                icon=":material/delete:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Delete Yamazumi work element?", dismissible=False)
def confirm_gui_element_delete() -> None:
    pending = st.session_state.get(gui_element_delete_key, {})
    element_id = str(pending.get("id") or "")
    matches = elements.loc[elements["id"].astype(str) == element_id]
    if matches.empty:
        st.error("That work element is no longer available in the active scenario.")
        if st.button("Close", key=f"close_missing_gui_element_{scenario_id}_{area_id}"):
            st.session_state.pop(gui_element_delete_key, None)
            st.rerun()
        return
    current = matches.iloc[0]
    description = str(current.get("description") or "Unnamed work element")
    pitch_id = str(current.get("pitch_id") or "")
    pitch_matches = pitches.loc[pitches["id"].astype(str) == pitch_id]
    pitch_label = (
        yamazumi_pitch_label(
            pitch_matches.iloc[0].get("pitch_number"),
            pitch_matches.iloc[0].get("pitch_name"),
        )
        if not pitch_matches.empty
        else "Unassigned"
    )
    process_element_value = current.get("process_element_id")
    has_process_link = (
        process_element_value is not None
        and not pd.isna(process_element_value)
        and bool(str(process_element_value).strip())
    )
    st.warning(
        f"Delete {description} ({pitch_label})? This removes the work element from "
        "the active planning scenario."
    )
    if has_process_link:
        st.info("Its linked Process at a Glance step will not be deleted automatically.")
    if has_board_draft:
        st.error("Use the board's Save & Refresh or Undo before deleting this work element.")
    editor_name = str(st.session_state.get("current_editor") or "").strip()
    if not editor_name:
        st.error("Enter the Current editor before deleting this work element.")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_gui_element_delete_{element_id}"):
        st.session_state.pop(gui_element_delete_key, None)
        st.session_state[element_edit_restore_key] = pending
        close_other_yamazumi_dialogs(edit_element_dialog_key)
        st.session_state[edit_element_dialog_key] = element_id
        st.rerun()
    if actions.button(
        "Delete work element",
        type="primary",
        icon=":material/delete:",
        key=f"destructive_gui_element_delete_{element_id}",
        disabled=has_board_draft or not editor_name,
    ):
        try:
            delete_yamazumi_element(
                project_id,
                area_id,
                element_id,
                scenario_id=scenario_id,
                audit_editor_name=editor_name,
                audit_details={
                    "source": "interactive_board_gui",
                    "linked_process_step_preserved": has_process_link,
                },
            )
            st.session_state.pop(gui_element_delete_key, None)
            st.session_state.pop(element_edit_restore_key, None)
            request_table_editor_reset(element_editor_key)
            request_table_editor_reset(pitch_editor_key)
            st.toast("Deleted Yamazumi work element", icon=":material/delete:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Delete Yamazumi work element?", dismissible=False)
def confirm_interactive_element_delete() -> None:
    pending = st.session_state.get(delete_element_dialog_key, {})
    element_id = str(pending.get("element_id") or "")
    try:
        impact = yamazumi_element_delete_impact(
            project_id, scenario_id, area_id, element_id
        )
    except ValueError as exc:
        st.warning(str(exc))
        if st.button(
            "Close",
            key=f"close_missing_interactive_element_{project_id}_{area_id}",
        ):
            st.session_state.pop(delete_element_dialog_key, None)
            st.rerun()
        return

    pitch_label = yamazumi_pitch_label(
        impact.get("pitch_number"), impact.get("pitch_name")
    ) if impact.get("pitch_id") else "Unassigned"
    st.warning(
        f"Delete **{impact['description']}** from **{pitch_label}** in this planning scenario?"
    )
    st.write(
        "This removes the element from the Yamazumi board, stack order, work totals, "
        "and line-balance calculations. Changes made in the edit form will not be saved."
    )
    if impact["process_step_exists"]:
        process_label = impact.get("process_operation") or "the linked Work Element"
        st.info(
            f"The Process at a Glance step **{process_label}** and its downstream part "
            "pairings, reviews, Quality, PFMEA, and Control Plan data will remain. It will "
            "lose its Yamazumi pitch, derived Op ID, and pitch-summary connection."
        )
    else:
        st.info("No current Process at a Glance step is linked to this Yamazumi element.")
    legacy_group_count = int(impact.get("legacy_material_group_count") or 0)
    legacy_option_count = int(impact.get("legacy_material_option_count") or 0)
    if legacy_group_count or legacy_option_count:
        st.write(
            f"This also removes {legacy_group_count} legacy Yamazumi-level material "
            f"requirement(s) and {legacy_option_count} option(s) attached directly to the element."
        )
    st.caption(
        "The pitch, Yamazumi area, Fishbone structure, work-region definition, and audit history remain."
    )
    actions = st.container(horizontal=True)
    if actions.button(
        "Cancel",
        key=f"cancel_interactive_element_delete_{project_id}_{area_id}_{element_id}",
    ):
        st.session_state.pop(delete_element_dialog_key, None)
        st.session_state[edit_element_dialog_key] = {
            "element_id": element_id,
            "draft": dict(pending.get("draft") or {}),
        }
        st.rerun()
    if actions.button(
        "Delete element",
        type="primary",
        icon=":material/delete:",
        key=f"destructive_confirm_interactive_element_delete_{element_id}",
    ):
        try:
            result = delete_yamazumi_element(
                project_id, scenario_id, area_id, element_id
            )
            record_audit_event(
                project_id,
                "Yamazumi elements",
                "Delete from interactive board",
                1,
                st.session_state.get("current_editor", ""),
                {
                    "scenario_id": scenario_id,
                    "area_id": area_id,
                    **result,
                },
            )
            current_draft = st.session_state.get(board_draft_key)
            if isinstance(current_draft, dict):
                updated_draft = remove_element_from_stack_draft(
                    current_draft, element_id
                )
                remaining_elements = [
                    row for row in elements.to_dict("records")
                    if str(row.get("id")) != element_id
                ]
                if draft_differs(remaining_elements, updated_draft):
                    st.session_state[board_draft_key] = updated_draft
                else:
                    st.session_state.pop(board_draft_key, None)
            st.session_state.pop(delete_element_dialog_key, None)
            st.session_state.pop(edit_element_dialog_key, None)
            request_table_editor_reset(element_editor_key)
            st.toast("Deleted Yamazumi work element", icon=":material/delete:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))



st.subheader("Interactive balancing board")
if len(defined_variant_options) == 1:
    st.info(
        "Only Base is available. Add active feature definitions and allowed choices on Model Definitions to create additional Yamazumi variants."
    )
st.caption(
    "Pitch stacks follow Op ID pitch-address order, with Subassembly and Kitter "
    "feeders immediately before the pitch they feed. Drag work within or between "
    "stacks; order is measured outward from the assembly-flow centerline and remains "
    "a draft until Save & Refresh.",
    help=(
        "CTQ comes from a linked PFMEA Classification of E, P, P-, Q, or E-. "
        "Safety comes from an active Safety requirement linked to the same Process step."
    ),
)
persisted_board_elements = elements.to_dict("records")
board_draft = st.session_state.get(board_draft_key)
has_board_draft = (
    isinstance(board_draft, dict)
    and draft_differs(persisted_board_elements, board_draft)
)
board_elements = (
    apply_stack_draft_to_elements(persisted_board_elements, board_draft)
    if has_board_draft else persisted_board_elements
)
board_pitches = order_yamazumi_pitches_for_board(pitches)
yamazumi_board(
    board_pitches.to_dict("records"),
    board_elements,
    variants,
    takt,
    time_unit=yamazumi_time_unit,
    takt_time_unit=takt_time_unit,
    key=board_key,
    on_move=handle_yamazumi_move,
    on_add_pitch=handle_add_pitch_request,
    on_add_element=handle_add_element_request,
    on_edit_pitch=handle_edit_pitch_request,
    on_edit_element=handle_edit_element_request,
)
if draft_error := st.session_state.pop(board_draft_error_key, None):
    st.error(str(draft_error))
board_actions = editable_table_footer(
    editor_key=f"yamazumi_board_footer_{project_id}_{scenario_id}_{area_id}",
    key_prefix=f"yamazumi_board_{project_id}_{scenario_id}_{area_id}",
    additional_unsaved_changes=has_board_draft,
)
if board_actions.undo:
    st.session_state.pop(board_draft_key, None)
    st.session_state.pop(board_draft_error_key, None)
    st.toast("Restored the last-saved Yamazumi stack order", icon=":material/undo:")
    st.rerun()
if board_actions.save_and_refresh:
    try:
        if not has_board_draft:
            raise ValueError("There are no unsaved Yamazumi stack changes to save.")
        result = save_yamazumi_stack_draft(
            project_id, scenario_id, area_id, board_draft
        )
        record_audit_event(
            project_id,
            "Yamazumi",
            "Save stack order",
            len(result["changed_element_ids"]),
            st.session_state.get("current_editor", ""),
            {
                "area_id": result["area_id"],
                "area_name": result["area_name"],
                "centerline_outward_stacks": result["affected_stacks"],
            },
        )
        st.session_state.pop(board_draft_key, None)
        if result["enabled_variants"]:
            request_table_editor_reset(pitch_editor_key)
        request_table_editor_reset(element_editor_key)
        st.toast(
            f"Saved {len(result['affected_stacks'])} Yamazumi stack(s)",
            icon=":material/check_circle:",
        )
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))
gui_delete_dialog_open = bool(
    st.session_state.get(gui_pitch_delete_key)
    or st.session_state.get(gui_element_delete_key)
)
if st.session_state.get(gui_pitch_delete_key):
    confirm_gui_pitch_delete()
elif st.session_state.get(gui_element_delete_key):
    confirm_gui_element_delete()
elif st.session_state.get(empty_pitch_dialog_key):
    close_other_yamazumi_dialogs(empty_pitch_dialog_key)
    empty_pitch_setup_dialog()
elif st.session_state.get(add_pitch_dialog_key):
    add_pitch_dialog()
elif st.session_state.get(add_element_dialog_key):
    add_element_dialog()
elif st.session_state.get(edit_pitch_dialog_key):
    edit_pitch_dialog()
elif st.session_state.get(delete_element_dialog_key):
    confirm_interactive_element_delete()
elif edit_element_target := st.session_state.get(edit_element_dialog_key):
    if isinstance(edit_element_target, dict):
        edit_element_dialog(
            str(edit_element_target.get("element_id") or ""),
            dict(edit_element_target.get("draft") or {}),
        )
    else:
        edit_element_dialog(str(edit_element_target))

ALL_YAMAZUMI_AREAS = "__all_yamazumi_areas__"
yamazumi_area_ids = list(area_labels)


def normalize_table_area_filter(key: str) -> list[str]:
    """Keep existing selections while migrating the old current/all dropdown state."""
    if key not in st.session_state:
        st.session_state[key] = [str(area_id)]
    stored = st.session_state.get(key)
    if stored == ALL_YAMAZUMI_AREAS or stored is None:
        normalized = []
    elif isinstance(stored, (list, tuple, set)):
        normalized = [str(value) for value in stored if str(value) in yamazumi_area_ids]
    else:
        normalized = [str(stored)] if str(stored) in yamazumi_area_ids else []
    if not isinstance(stored, list) or stored != normalized:
        st.session_state[key] = normalized
    return normalized


def current_editor_draft(editor_rows: pd.DataFrame, editor_key: str) -> pd.DataFrame:
    """Capture cell/new-row edits while treating native row deletion as selection."""
    state = st.session_state.get(editor_key, {}) or {}
    draft = editor_rows.copy()
    for raw_position, changes in (state.get("edited_rows") or {}).items():
        position = int(raw_position)
        if not 0 <= position < len(draft):
            continue
        for column, value in (changes or {}).items():
            if column in draft.columns:
                draft.at[draft.index[position], column] = value
    added_rows = state.get("added_rows") or []
    if added_rows:
        draft = pd.concat(
            [draft, pd.DataFrame(added_rows, columns=draft.columns)],
            ignore_index=True,
            sort=False,
        )
    return draft.reset_index(drop=True)


def editor_edit_count(editor_key: str) -> int:
    """Count edited/new rows without counting native row selection."""
    state = st.session_state.get(editor_key, {}) or {}
    return len(state.get("edited_rows") or {}) + len(state.get("added_rows") or [])


pitch_table_area_key = f"yamazumi_pitch_table_area_{scenario_id}"
pitch_table_manual_area_key = f"yamazumi_pitch_table_area_manual_{scenario_id}"


def mark_pitch_table_area_manual() -> None:
    """Stop automatic board-area syncing after the user chooses table areas."""
    st.session_state[pitch_table_manual_area_key] = True


selected_pitch_area_ids = normalize_table_area_filter(pitch_table_area_key)
if not st.session_state.get(pitch_table_manual_area_key, False):
    selected_pitch_area_ids = [str(area_id)]
    if st.session_state.get(pitch_table_area_key) != selected_pitch_area_ids:
        st.session_state[pitch_table_area_key] = selected_pitch_area_ids
effective_pitch_area_ids = selected_pitch_area_ids or yamazumi_area_ids
pitch_combined_view = set(effective_pitch_area_ids) != {str(area_id)}
if pitch_combined_view:
    st.subheader("Pitch addresses")
else:
    editable_table_heading("Pitch addresses")
selected_pitch_area_ids = st.multiselect(
    "Areas shown in pitch-address table",
    options=yamazumi_area_ids,
    format_func=lambda value: area_labels.get(value, value),
    placeholder="All Yamazumi areas",
    key=pitch_table_area_key,
    on_change=mark_pitch_table_area_manual,
    persist_state="session",
)
effective_pitch_area_ids = selected_pitch_area_ids or yamazumi_area_ids
pitch_combined_view = set(effective_pitch_area_ids) != {str(area_id)}
if pitch_combined_view:
    pitch_table_source = yamazumi_pitches_for_scenario(project_id, scenario_id)
    pitch_table_source = pitch_table_source.loc[
        pitch_table_source["area_id"].astype(str).isin(effective_pitch_area_ids)
    ].copy()
    if not pitch_table_source.empty:
        pitch_table_source["model_variants"] = pitch_table_source["model_variants"].apply(
            lambda value: [
                stored_variant_labels.get(item, item)
                for item in json.loads(value or '["Base"]')
            ]
        )
    scope_caption = "every Yamazumi area" if not selected_pitch_area_ids else "the selected Yamazumi areas"
    st.caption(f"Showing {scope_caption} in this scenario. Combined views are read-only.")
else:
    pitch_table_source = pitches.copy()
    pitch_table_source["area_name"] = str(area["name"])
pitch_columns = [
    "id", "area_name", "pitch_number", "pitch_name", "pitch_type", "status",
    "feeds_into_pitch_id", "feed_target", "feed_target_status",
    "model_variants", "sequence", "updated_at",
]
if pitch_table_source.empty:
    pitch_rows = pd.DataFrame({
        "id": pd.Series(dtype="string"),
        "area_name": pd.Series(dtype="string"),
        "pitch_number": pd.Series(dtype="string"),
        "pitch_name": pd.Series(dtype="string"),
        "pitch_type": pd.Series(dtype="string"),
        "status": pd.Series(dtype="string"),
        "feeds_into_pitch_id": pd.Series(dtype="string"),
        "feed_target": pd.Series(dtype="string"),
        "feed_target_status": pd.Series(dtype="string"),
        # MultiselectColumn values are lists, so this column deliberately uses object dtype.
        "model_variants": pd.Series(dtype="object"),
        "sequence": pd.Series(dtype="Int64"),
        "updated_at": pd.Series(dtype="string"),
    })
else:
    pitch_rows = pitch_table_source.reindex(columns=pitch_columns).copy()
    table_pitch_label_by_id = {
        str(row["id"]): yamazumi_pitch_label(row["pitch_number"], row["pitch_name"])
        for _, row in pitch_table_source.iterrows()
    }
    pitch_rows["feed_target"] = pitch_rows["feeds_into_pitch_id"].apply(
        lambda value: table_pitch_label_by_id.get(str(value), "")
        if value is not None and not pd.isna(value) else ""
    )
    pitch_rows["feed_target_status"] = pitch_rows.apply(
        lambda row: yamazumi_pitch_feed_target_status(
            row.get("pitch_type"), row.get("feeds_into_pitch_id")
        ),
        axis=1,
    )
pitch_filter_scope = "combined" if pitch_combined_view else str(area_id)
visible_pitches = filter_table(
    pitch_rows,
    key=f"yamazumi_pitch_filters_{scenario_id}_{pitch_filter_scope}",
    dropdown_columns=["area_name", "pitch_type", "status", "model_variants"],
    search_columns=["area_name", "pitch_number", "pitch_name", "pitch_type", "status", "feed_target", "feed_target_status", "model_variants"],
    labels={
        "area_name": "Yamazumi area",
        "pitch_type": "Pitch type",
        "status": "Status",
        "model_variants": "Model variant",
    },
    multi_value_columns=["model_variants"],
    reset_widget_keys=[] if pitch_combined_view else [pitch_editor_key],
)
pitch_column_order = [
    "area_name", "pitch_number", "pitch_name", "pitch_type", "status",
    "feed_target", "feed_target_status", "model_variants", "sequence",
]
pitch_column_config = {
    "id": None,
    "area_name": st.column_config.TextColumn("Yamazumi area"),
    "pitch_number": st.column_config.TextColumn(
        "Pitch address",
        required=True,
        help="Use the physical line address/nomenclature. It must be unique across every Yamazumi area in this planning scenario; capitalization and surrounding spaces are ignored when checking duplicates.",
    ),
    "pitch_name": st.column_config.TextColumn("Pitch name"),
    "pitch_type": st.column_config.SelectboxColumn("Pitch type", options=PITCH_TYPES, required=True, default="Pitch"),
    "status": st.column_config.SelectboxColumn("Status", options=["Active", "Blocked", "Open"], required=True, default="Active"),
    "feeds_into_pitch_id": None,
    "feed_target": st.column_config.TextColumn(
        "Feeds into pitch",
        help="Shown for Subassembly and Kitter pitches. Use the pitch-card editor to choose a same-area target.",
    ),
    "feed_target_status": st.column_config.TextColumn(
        "Feed target status",
        help="Compatibility-null feeder pitches remain visibly unclassified until manually edited.",
    ),
    "model_variants": st.column_config.MultiselectColumn(
        "Model variants",
        options=variant_options,
        required=True,
        default=["Base"],
        help="Only these variants appear as stacks on this pitch.",
    ),
    "sequence": st.column_config.NumberColumn("Order", min_value=1, step=1, format="%d"),
    "updated_at": None,
}
if pitch_combined_view:
    pitch_read_only_config = {
        **pitch_column_config,
        "model_variants": st.column_config.ListColumn("Model variants"),
        "feed_target": st.column_config.TextColumn("Feeds into pitch"),
    }
    selectable_dataframe(
        visible_pitches,
        key=f"yamazumi_combined_pitches_{scenario_id}",
        hide_index=True,
        height=280,
        column_order=pitch_column_order,
        column_config=pitch_read_only_config,
    )
    edited_pitches = visible_pitches
else:
    pitch_editor_rows = direct_entry_editor_rows(
        visible_pitches,
        editor_key=pitch_editor_key,
        sort_columns=[
            "area_name", "pitch_number", "pitch_name", "pitch_type", "status",
            "model_variants", "sequence"
        ],
        labels={
            "area_name": "Yamazumi area", "pitch_number": "Pitch address",
            "pitch_name": "Pitch name", "pitch_type": "Pitch type",
            "model_variants": "Model variants", "sequence": "Order",
        },
    )
    edited_pitches = st.data_editor(
        pitch_editor_rows,
        key=pitch_editor_key,
        hide_index=True,
        num_rows="dynamic",
        height=280,
        disabled=["id", "area_name", "feeds_into_pitch_id", "feed_target", "feed_target_status", "updated_at"],
        column_order=pitch_column_order,
        column_config=pitch_column_config,
    )
    pitch_actions = editable_table_footer(
        editor_key=pitch_editor_key,
        key_prefix="yamazumi_pitches",
        native_row_selection=True,
    )
    if pitch_actions.undo:
        request_table_editor_reset(pitch_editor_key)
        st.rerun()
    selected_pitches = native_selected_rows(
        pitch_editor_rows, editor_key=pitch_editor_key
    )
    request_pitch_delete = not selected_pitches.empty
    if request_pitch_delete:
        selected_pitch_ids = set(selected_pitches["id"].astype(str))
        close_other_yamazumi_dialogs("")
        st.session_state.pop(element_delete_key, None)
        st.session_state[pitch_delete_key] = {
            "pitches": [
                {
                    "id": str(row["id"]),
                    "source_pitch_id": str(row["id"]),
                    "pitch_number": str(row.get("pitch_number") or ""),
                    "source_pitch_address": str(row.get("pitch_number") or ""),
                    "pitch_name": str(row.get("pitch_name") or ""),
                    "old_feeds_into_pitch_id": (
                        str(row.get("feeds_into_pitch_id"))
                        if row.get("feeds_into_pitch_id") is not None
                        and not pd.isna(row.get("feeds_into_pitch_id"))
                        else None
                    ),
                    "old_feed_target": feed_target_label_by_id.get(
                        str(row.get("feeds_into_pitch_id")), ""
                    ),
                    "new_feeds_into_pitch_id": None,
                    "new_feed_target": None,
                    "assigned_element_count": int(
                        elements["pitch_id"].fillna("").astype(str).eq(str(row["id"])).sum()
                    ) if not elements.empty else 0,
                }
                for _, row in selected_pitches.iterrows()
                if str(row["id"]) in selected_pitch_ids
            ],
            "pitch_draft": current_editor_draft(
                pitch_editor_rows, pitch_editor_key
            ).to_dict("records"),
            "other_pitch_edits": table_has_unsaved_changes(
                pitch_editor_key, native_row_selection=True
            ),
            "pitch_edit_count": editor_edit_count(pitch_editor_key),
            "feed_reference_blockers": yamazumi_pitch_delete_blockers(
                project_id, area_id, list(selected_pitch_ids)
            ),
        }
        stage_native_delete_confirmation(pitch_editor_key)
st.download_button(
    "Export filtered pitches",
    data=dataframe_to_excel(
        visible_pitches.drop(columns=["id", "updated_at"], errors="ignore"),
        "Pitch addresses",
    ),
    file_name=(
        "yamazumi_pitch_addresses_multiple_areas_filtered.xlsx"
        if pitch_combined_view else "yamazumi_pitch_addresses_filtered.xlsx"
    ),
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    icon=":material/download:",
    key=f"export_yamazumi_pitches_{scenario_id}_{pitch_filter_scope}",
)
if not pitch_combined_view and pitch_actions.save_and_refresh:
    try:
        if not selected_pitches.empty:
            raise ValueError("Clear selected rows before saving pitch edits.")
        edited_pitches = drop_untouched_new_rows(
            edited_pitches, identifying_columns=["pitch_number"]
        )
        errors = required_field_errors(edited_pitches, {"pitch_number": "Pitch address", "status": "Status"})
        if errors:
            raise ValueError(" ".join(errors))
        to_save = merge_filtered_edits(pitch_rows, visible_pitches, edited_pitches)
        feed_target_id_by_label = {
            label: pitch_id for pitch_id, label in feed_target_label_by_id.items()
        }
        to_save["feeds_into_pitch_id"] = to_save["feed_target"].map(
            feed_target_id_by_label
        )
        before_pitch_rows = yamazumi_pitches(project_id, area_id)
        count = replace_yamazumi_pitches(project_id, area_id, to_save)
        after_pitch_rows = yamazumi_pitches(project_id, area_id)
        before_by_id = {
            str(row["id"]): row for _, row in before_pitch_rows.iterrows()
        }
        all_labels = {
            str(row["id"]): yamazumi_pitch_label(
                row["pitch_number"], row["pitch_name"]
            )
            for frame in (before_pitch_rows, after_pitch_rows)
            for _, row in frame.iterrows()
        }
        feed_changes = []
        for _, row in after_pitch_rows.iterrows():
            source_id = str(row["id"])
            old_row = before_by_id.get(source_id)
            old_target_id = (
                str(old_row.get("feeds_into_pitch_id") or "").strip() or None
                if old_row is not None else None
            )
            new_target_id = str(row.get("feeds_into_pitch_id") or "").strip() or None
            if old_target_id != new_target_id:
                feed_changes.append(
                    {
                        "source_pitch_id": source_id,
                        "source_pitch_address": str(row["pitch_number"]),
                        "old_feeds_into_pitch_id": old_target_id,
                        "old_feed_target": all_labels.get(str(old_target_id), ""),
                        "new_feeds_into_pitch_id": new_target_id,
                        "new_feed_target": all_labels.get(str(new_target_id), ""),
                    }
                )
        record_audit_event(
            project_id,
            "Yamazumi pitches",
            "Save & Refresh",
            count,
            st.session_state.get("current_editor", ""),
            {"area_id": area_id, "feed_relationship_changes": feed_changes},
        )
        request_table_editor_reset(pitch_editor_key)
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

st.divider()
element_table_area_key = f"yamazumi_element_table_area_{scenario_id}"
selected_element_area_ids = normalize_table_area_filter(element_table_area_key)
effective_element_area_ids = selected_element_area_ids or yamazumi_area_ids
element_combined_view = set(effective_element_area_ids) != {str(area_id)}
if element_combined_view:
    st.subheader("Yamazumi work elements")
else:
    editable_table_heading("Yamazumi work elements")
selected_element_area_ids = st.multiselect(
    "Areas shown in work-elements table",
    options=yamazumi_area_ids,
    format_func=lambda value: area_labels.get(value, value),
    placeholder="All Yamazumi areas",
    key=element_table_area_key,
)
effective_element_area_ids = selected_element_area_ids or yamazumi_area_ids
element_combined_view = set(effective_element_area_ids) != {str(area_id)}
if element_combined_view:
    element_table_source = yamazumi_elements_for_scenario(project_id, scenario_id)
    element_table_source = element_table_source.loc[
        element_table_source["area_id"].astype(str).isin(effective_element_area_ids)
    ].copy()
    if not element_table_source.empty:
        element_table_source["model_variants"] = element_table_source.apply(
            lambda row: [
                stored_variant_labels.get(item, item)
                for item in parse_yamazumi_model_variants(
                    row.get("model_variants"), str(row.get("model_variant") or "Base")
                )
            ],
            axis=1,
        )
        element_table_source["criticality"] = element_table_source[
            "process_element_id"
        ].apply(criticality_for_process_link)
    scope_caption = "every Yamazumi area" if not selected_element_area_ids else "the selected Yamazumi areas"
    st.caption(f"Showing {scope_caption} in this scenario. Combined views are read-only.")
else:
    element_table_source = elements.copy()
    element_table_source["area_name"] = str(area["name"])
active_pitches = pitches.loc[pitches["status"] == "Active"].copy() if not pitches.empty else pitches
pitch_label_by_id = dict(zip(active_pitches["id"].astype(str), active_pitches["pitch_number"].astype(str))) if not active_pitches.empty else {}
element_columns = [
    "id", "area_name", "pitch_id", "model_variants", "work_type", "description", "time_s", "work_region",
    "criticality", "sequence", "source", "process_element_id", "process_sync_status", "updated_at",
]
if element_table_source.empty:
    element_rows = pd.DataFrame({
        "id": pd.Series(dtype="string"),
        "area_name": pd.Series(dtype="string"),
        "pitch_id": pd.Series(dtype="string"),
        # MultiselectColumn values are lists, so this column deliberately uses object dtype.
        "model_variants": pd.Series(dtype="object"),
        "work_type": pd.Series(dtype="string"),
        "description": pd.Series(dtype="string"),
        "time_s": pd.Series(dtype="Float64"),
        "work_region": pd.Series(dtype="string"),
        "criticality": pd.Series(dtype="object"),
        "sequence": pd.Series(dtype="Int64"),
        "source": pd.Series(dtype="string"),
        "process_element_id": pd.Series(dtype="string"),
        "process_sync_status": pd.Series(dtype="string"),
        "updated_at": pd.Series(dtype="string"),
    })
    element_rows["pitch"] = pd.Series(dtype="string")
else:
    element_rows = element_table_source.reindex(columns=element_columns).copy()
    if element_combined_view:
        element_rows["pitch"] = element_table_source["pitch_number"].fillna("Unassigned").astype("string")
    else:
        element_rows["pitch"] = element_rows["pitch_id"].apply(
            lambda value: pitch_label_by_id.get(str(value), "Unassigned") if value is not None and not pd.isna(value) else "Unassigned"
        )
element_rows["time_s"] = (
    pd.to_numeric(element_rows["time_s"], errors="coerce")
    / time_config.seconds_per_unit
)
element_filter_scope = "combined" if element_combined_view else str(area_id)
visible_elements = filter_table(
    element_rows,
    key=f"yamazumi_element_filters_{scenario_id}_{element_filter_scope}",
    dropdown_columns=["area_name", "pitch", "model_variants", "work_type", "work_region", "criticality"],
    search_columns=["area_name", "description", "pitch", "model_variants", "work_region", "criticality"],
    labels={"area_name": "Yamazumi area", "model_variants": "Model variant", "criticality": "Criticality"},
    multi_value_columns=["model_variants", "criticality"],
    reset_widget_keys=[] if element_combined_view else [element_editor_key],
)
pitch_options = ["Unassigned", *pitch_label_by_id.values()]
variant_options_by_pitch_label = {
    pitch_label_by_id[pitch_id]: pitch_variants_by_id.get(pitch_id, ["Base"])
    for pitch_id in pitch_label_by_id
}
element_column_order = [
    "area_name", "pitch", "model_variants", "work_type", "description", "time_s",
    "work_region", "criticality", "sequence",
]
element_column_config = {
    "id": None,
    "area_name": st.column_config.TextColumn("Yamazumi area"),
    "pitch_id": None,
    "pitch": st.column_config.SelectboxColumn("Pitch", options=pitch_options, required=True, default="Unassigned"),
    "model_variants": st.column_config.MultiselectColumn(
        "Model variants",
        options=variant_options,
        required=True,
        default=["Base"],
        help="Choose every model stack where this same work element applies.",
    ),
    "work_type": st.column_config.SelectboxColumn("Work type", options=WORK_TYPES, required=True, default="Cycle"),
    "description": st.column_config.TextColumn("Work description", required=True, width="large"),
    "time_s": st.column_config.NumberColumn(
        time_column_label,
        min_value=0.0,
        step=time_config.step,
        format=f"%.{time_config.decimals}f",
        required=True,
    ),
    "work_region": st.column_config.SelectboxColumn(
        "Work region", options=work_region_options, required=True, default="None"
    ),
    "criticality": st.column_config.MultiselectColumn(
        "Criticality",
        options=["CTQ", "Safety"],
        color=["orange", "red"],
        disabled=True,
        help=(
            "CTQ comes from qualifying PFMEA Classification codes. Safety comes "
            "from active Safety requirements linked to the Process step."
        ),
    ),
    "sequence": st.column_config.NumberColumn("Order", min_value=1, step=1, format="%d"),
    "source": None,
    "process_element_id": None,
    "process_sync_status": None,
    "updated_at": None,
}
if element_combined_view:
    element_read_only_config = {
        **element_column_config,
        "pitch": st.column_config.TextColumn("Pitch"),
        "model_variants": st.column_config.ListColumn("Model variants"),
        "work_region": st.column_config.TextColumn("Work region"),
        "criticality": st.column_config.ListColumn("Criticality"),
    }
    selectable_dataframe(
        visible_elements,
        key=f"yamazumi_combined_elements_{scenario_id}",
        hide_index=True,
        height=420,
        column_order=element_column_order,
        column_config=element_read_only_config,
    )
    edited_elements = visible_elements
else:
    element_editor_rows = direct_entry_editor_rows(
        visible_elements,
        editor_key=element_editor_key,
        sort_columns=[
            "area_name", "pitch", "model_variants", "work_type", "description", "time_s",
            "work_region", "criticality", "sequence",
        ],
        labels={
            "area_name": "Yamazumi area", "model_variants": "Model variants",
            "work_type": "Work type", "description": "Work description",
            "time_s": time_column_label,
            "work_region": "Work region", "sequence": "Order",
        },
    )
    edited_elements = st.data_editor(
        element_editor_rows,
        key=element_editor_key,
        hide_index=True,
        num_rows="dynamic",
        height=420,
        disabled=["id", "area_name", "criticality", "source", "process_element_id", "process_sync_status", "updated_at"],
        column_order=element_column_order,
        column_config=element_column_config,
    )
    element_actions = editable_table_footer(
        editor_key=element_editor_key,
        key_prefix="yamazumi_elements",
        native_row_selection=True,
    )
    if element_actions.undo:
        request_table_editor_reset(element_editor_key)
        st.rerun()
    selected_elements = native_selected_rows(
        element_editor_rows, editor_key=element_editor_key
    )
    request_element_delete = not selected_elements.empty
    if request_element_delete:
        close_other_yamazumi_dialogs("")
        st.session_state.pop(pitch_delete_key, None)
        st.session_state[element_delete_key] = {
            "elements": [
                {
                    "id": str(row["id"]),
                    "description": str(row.get("description") or ""),
                    "pitch": str(row.get("pitch") or "Unassigned"),
                    "process_element_id": str(
                        row.get("process_element_id") or ""
                    ),
                }
                for _, row in selected_elements.iterrows()
            ],
            "element_draft": current_editor_draft(
                element_editor_rows, element_editor_key
            ).to_dict("records"),
            "pitch_draft": (
                current_editor_draft(pitch_editor_rows, pitch_editor_key).to_dict(
                    "records"
                )
                if not pitch_combined_view
                else []
            ),
            "other_element_edits": table_has_unsaved_changes(
                element_editor_key, native_row_selection=True
            ),
            "element_edit_count": editor_edit_count(element_editor_key),
            "other_pitch_edits": (
                table_has_unsaved_changes(
                    pitch_editor_key, native_row_selection=True
                )
                if not pitch_combined_view
                else False
            ),
            "pitch_edit_count": (
                editor_edit_count(pitch_editor_key)
                if not pitch_combined_view
                else 0
            ),
        }
        stage_native_delete_confirmation(element_editor_key)
st.download_button(
    "Export filtered work elements",
    data=dataframe_to_excel(
        visible_elements.rename(
            columns={"time_s": time_column_label}
        ).drop(
            columns=["id", "pitch_id", "process_element_id", "updated_at"],
            errors="ignore",
        ),
        "Yamazumi work elements",
    ),
    file_name=(
        "yamazumi_work_elements_multiple_areas_filtered.xlsx"
        if element_combined_view else "yamazumi_work_elements_filtered.xlsx"
    ),
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    icon=":material/download:",
    key=f"export_yamazumi_elements_{scenario_id}_{element_filter_scope}",
)
if not element_combined_view and element_actions.save_and_refresh:
    try:
        if not selected_elements.empty:
            raise ValueError("Clear selected rows before saving work-element edits.")
        edited_elements = drop_untouched_new_rows(
            edited_elements, identifying_columns=["description"]
        )
        errors = required_field_errors(edited_elements, {"model_variants": "Model variants", "description": "Work description", "work_region": "Work region"})
        if errors:
            raise ValueError(" ".join(errors))
        pitch_id_by_label = {label: pitch_id for pitch_id, label in pitch_label_by_id.items()}
        to_save = merge_filtered_edits(element_rows, visible_elements, edited_elements)
        to_save["pitch_id"] = to_save["pitch"].map(pitch_id_by_label)
        invalid_variant_rows = to_save.apply(
            lambda row: (
                row["pitch"] != "Unassigned"
                and not set(row["model_variants"] or []).issubset(
                    set(variant_options_by_pitch_label.get(row["pitch"], []))
                )
            ),
            axis=1,
        )
        if invalid_variant_rows.any():
            raise ValueError("A work element uses model variants that are not enabled for its selected pitch.")
        to_save = to_save.drop(columns=["pitch"], errors="ignore")
        to_save = element_times_to_seconds(to_save)
        count = replace_yamazumi_elements(project_id, area_id, to_save)
        record_audit_event(project_id, "Yamazumi elements", "Save & Refresh", count, st.session_state.get("current_editor", ""))
        request_table_editor_reset(element_editor_key)
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))


def prepared_pitch_rows(
    draft_records: list[dict], excluded_ids: set[str]
) -> pd.DataFrame:
    draft = pd.DataFrame(draft_records, columns=pitch_editor_rows.columns)
    draft = draft.loc[
        ~draft["id"].fillna("").astype(str).isin(excluded_ids)
    ].copy()
    draft = drop_untouched_new_rows(draft, identifying_columns=["pitch_number"])
    errors = required_field_errors(
        draft, {"pitch_number": "Pitch address", "status": "Status"}
    )
    if errors:
        raise ValueError(" ".join(errors))
    to_save = merge_filtered_edits(pitch_rows, visible_pitches, draft)
    feed_target_id_by_label = {
        label: pitch_id for pitch_id, label in feed_target_label_by_id.items()
    }
    to_save["feeds_into_pitch_id"] = to_save["feed_target"].map(
        feed_target_id_by_label
    )
    return to_save


def prepared_element_rows(
    draft_records: list[dict], excluded_ids: set[str]
) -> pd.DataFrame:
    draft = pd.DataFrame(draft_records, columns=element_editor_rows.columns)
    draft = draft.loc[
        ~draft["id"].fillna("").astype(str).isin(excluded_ids)
    ].copy()
    draft = drop_untouched_new_rows(draft, identifying_columns=["description"])
    errors = required_field_errors(
        draft,
        {
            "model_variants": "Model variants",
            "description": "Work description",
            "work_region": "Work region",
        },
    )
    if errors:
        raise ValueError(" ".join(errors))
    pitch_id_by_label = {
        label: pitch_id for pitch_id, label in pitch_label_by_id.items()
    }
    to_save = merge_filtered_edits(element_rows, visible_elements, draft)
    to_save["pitch_id"] = to_save["pitch"].map(pitch_id_by_label)
    invalid_variant_rows = to_save.apply(
        lambda row: (
            row["pitch"] != "Unassigned"
            and not set(row["model_variants"] or []).issubset(
                set(variant_options_by_pitch_label.get(row["pitch"], []))
            )
        ),
        axis=1,
    )
    if invalid_variant_rows.any():
        raise ValueError(
            "A work element uses model variants that are not enabled for its selected pitch."
        )
    to_save = to_save.drop(columns=["pitch"], errors="ignore")
    return element_times_to_seconds(to_save)


pending_pitch_delete = st.session_state.get(pitch_delete_key)
if pending_pitch_delete and "element_draft" not in pending_pitch_delete:
    pending_pitch_delete["element_draft"] = (
        current_editor_draft(element_editor_rows, element_editor_key).to_dict(
            "records"
        )
        if not element_combined_view
        else []
    )
    pending_pitch_delete["other_element_edits"] = (
        table_has_unsaved_changes(
            element_editor_key, native_row_selection=True
        )
        if not element_combined_view
        else False
    )
    pending_pitch_delete["element_edit_count"] = (
        editor_edit_count(element_editor_key) if not element_combined_view else 0
    )
    if not element_combined_view:
        pitch_id_by_label = {
            label: pitch_id for pitch_id, label in pitch_label_by_id.items()
        }
        edited_pitch_ids = [
            pitch_id_by_label.get(str(row.get("pitch") or "Unassigned"))
            for row in pending_pitch_delete["element_draft"]
        ]
        for pitch in pending_pitch_delete.get("pitches", []):
            pitch["assigned_element_count"] = edited_pitch_ids.count(
                str(pitch["id"])
            )
    st.session_state[pitch_delete_key] = pending_pitch_delete


@st.dialog("Delete selected pitches?", dismissible=False)
def confirm_pitch_bulk_delete() -> None:
    pending = st.session_state.get(pitch_delete_key, {})
    selected_rows = pending.get("pitches", [])
    st.warning(
        f"Delete {len(selected_rows)} selected pitch(es)? Work elements assigned to "
        "these pitches will be moved to Unassigned; the work elements themselves will "
        "not be deleted."
    )
    for pitch in selected_rows:
        label = pitch.get("pitch_number") or "Unnamed pitch"
        if pitch.get("pitch_name"):
            label += f" — {pitch['pitch_name']}"
        st.write(
            f"- {label}: {pitch.get('assigned_element_count', 0)} assigned work "
            "element(s) will move to Unassigned"
        )
    blockers = pending.get("feed_reference_blockers", [])
    if blockers:
        relationships = ", ".join(
            f"{yamazumi_pitch_label(row['source_pitch_number'], row['source_pitch_name'])} → "
            f"{yamazumi_pitch_label(row['target_pitch_number'], row['target_pitch_name'])}"
            for row in blockers
        )
        st.error(
            "Deletion is blocked while these feed relationships remain: "
            + relationships
            + ". Re-point the source pitches or change their type before deleting the targets."
        )
    if pending.get("other_pitch_edits") or pending.get("other_element_edits"):
        st.info(
            "Other unsaved pitch or work-element edits will be saved at the same time "
            "so they are not lost."
        )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_pitch_bulk_delete_{scenario_id}_{area_id}"):
        st.session_state.pop(pitch_delete_key, None)
        request_table_editor_reset(pitch_editor_key)
        st.rerun()
    if actions.button(
        "Delete pitches",
        type="primary",
        icon=":material/delete:",
        key=f"destructive_confirm_pitch_bulk_delete_{scenario_id}_{area_id}",
    ):
        try:
            editor_name = st.session_state.get("current_editor", "")
            if pending.get("other_element_edits"):
                element_save_rows = prepared_element_rows(
                    pending.get("element_draft", []), set()
                )
                replace_yamazumi_elements(project_id, area_id, element_save_rows)
                record_audit_event(
                    project_id,
                    "Yamazumi elements",
                    "Save & Refresh",
                    int(pending.get("element_edit_count") or 0),
                    editor_name,
                    {"area_id": area_id, "saved_with_pitch_delete": True},
                )
            selected_ids = {str(row["id"]) for row in selected_rows}
            pitch_save_rows = prepared_pitch_rows(
                pending.get("pitch_draft", []), selected_ids
            )
            replace_yamazumi_pitches(project_id, area_id, pitch_save_rows)
            if pending.get("other_pitch_edits"):
                record_audit_event(
                    project_id,
                    "Yamazumi pitches",
                    "Save & Refresh",
                    int(pending.get("pitch_edit_count") or 0),
                    editor_name,
                    {"area_id": area_id, "saved_with_bulk_delete": True},
                )
            moved_count = sum(
                int(row.get("assigned_element_count") or 0)
                for row in selected_rows
            )
            record_audit_event(
                project_id,
                "Yamazumi pitches",
                "Bulk delete",
                len(selected_ids),
                editor_name,
                {
                    "area_id": area_id,
                    "pitches": selected_rows,
                    "elements_unassigned": moved_count,
                },
            )
            st.session_state.pop(pitch_delete_key, None)
            request_table_editor_reset(pitch_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast(
                f"Deleted {len(selected_ids)} pitch(es); {moved_count} work element(s) "
                "moved to Unassigned",
                icon=":material/delete:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Delete selected Yamazumi work elements?", dismissible=False)
def confirm_element_bulk_delete() -> None:
    pending = st.session_state.get(element_delete_key, {})
    selected_rows = pending.get("elements", [])
    st.warning(
        f"Delete {len(selected_rows)} selected Yamazumi work element(s)? This removes "
        "the selected work from this planning scenario."
    )
    for element in selected_rows:
        linked_note = (
            " — its linked Process at a Glance step will not be deleted automatically"
            if element.get("process_element_id")
            else ""
        )
        st.write(
            f"- {element.get('description') or 'Unnamed work element'} "
            f"({element.get('pitch') or 'Unassigned'}){linked_note}"
        )
    if pending.get("other_pitch_edits") or pending.get("other_element_edits"):
        st.info(
            "Other unsaved pitch or work-element edits will be saved at the same time "
            "so they are not lost."
        )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_element_bulk_delete_{scenario_id}_{area_id}"):
        st.session_state.pop(element_delete_key, None)
        request_table_editor_reset(element_editor_key)
        st.rerun()
    if actions.button(
        "Delete work elements",
        type="primary",
        icon=":material/delete:",
        key=f"destructive_confirm_element_bulk_delete_{scenario_id}_{area_id}",
    ):
        try:
            editor_name = st.session_state.get("current_editor", "")
            selected_ids = {str(row["id"]) for row in selected_rows}
            element_save_rows = prepared_element_rows(
                pending.get("element_draft", []), selected_ids
            )
            replace_yamazumi_elements(project_id, area_id, element_save_rows)
            if pending.get("other_element_edits"):
                record_audit_event(
                    project_id,
                    "Yamazumi elements",
                    "Save & Refresh",
                    int(pending.get("element_edit_count") or 0),
                    editor_name,
                    {"area_id": area_id, "saved_with_bulk_delete": True},
                )
            if pending.get("other_pitch_edits"):
                pitch_save_rows = prepared_pitch_rows(
                    pending.get("pitch_draft", []), set()
                )
                replace_yamazumi_pitches(project_id, area_id, pitch_save_rows)
                record_audit_event(
                    project_id,
                    "Yamazumi pitches",
                    "Save & Refresh",
                    int(pending.get("pitch_edit_count") or 0),
                    editor_name,
                    {"area_id": area_id, "saved_with_element_delete": True},
                )
            record_audit_event(
                project_id,
                "Yamazumi elements",
                "Bulk delete",
                len(selected_ids),
                editor_name,
                {"area_id": area_id, "elements": selected_rows},
            )
            st.session_state.pop(element_delete_key, None)
            request_table_editor_reset(element_editor_key)
            request_table_editor_reset(pitch_editor_key)
            st.toast(
                f"Deleted {len(selected_ids)} Yamazumi work element(s)",
                icon=":material/delete:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


if not gui_delete_dialog_open:
    if st.session_state.get(pitch_delete_key):
        confirm_pitch_bulk_delete()
    elif st.session_state.get(element_delete_key):
        confirm_element_bulk_delete()


copy_generation_key = f"yamazumi_copy_generation_{project_id}_{scenario_id}"
copy_pending_key = f"yamazumi_copy_pending_{project_id}_{scenario_id}"
copy_generation = int(st.session_state.get(copy_generation_key, 0) or 0)


def yamazumi_copy_has_unsaved_state() -> bool:
    """Keep the copy workflow on persisted rows and away from other drafts."""
    if any(
        str(key).startswith(f"yamazumi_board_draft_{project_id}_") and bool(value)
        for key, value in st.session_state.items()
    ):
        return True
    for editor_key in (pitch_editor_key, element_editor_key):
        editor_state = st.session_state.get(editor_key, {})
        if isinstance(editor_state, dict) and any(
            bool(editor_state.get(field))
            for field in ("edited_rows", "added_rows", "deleted_rows")
        ):
            return True
    return bool(
        st.session_state.get(pitch_delete_key)
        or st.session_state.get(element_delete_key)
        or st.session_state.get(gui_pitch_delete_key)
        or st.session_state.get(gui_element_delete_key)
    )


def copy_scenario_label(value: str, labels: dict[str, str]) -> str:
    return labels.get(str(value), "Unavailable scenario")


def copy_area_label(value: str, labels: dict[str, str]) -> str:
    return labels.get(str(value), "Unavailable Yamazumi area")


copy_plan_for_page = None
with st.expander("Copy to another area", icon=":material/content_copy:"):
    st.caption(
        "Copy saved pitches or Yamazumi work elements without changing the source. "
        "Copied work receives new identities and no Process at a Glance link."
    )
    copy_scenarios = planning_scenarios(project_id)
    copy_scenario_ids = [str(row["id"]) for row in copy_scenarios]
    copy_scenario_labels = {
        str(row["id"]): f"Rev {row['revision_label']} · {row['name']}"
        for row in copy_scenarios
    }
    source_scenario_key = (
        f"yamazumi_copy_source_scenario_{project_id}_{scenario_id}_{copy_generation}"
    )
    source_scenario = st.selectbox(
        "Source planning scenario",
        options=copy_scenario_ids,
        index=(copy_scenario_ids.index(str(scenario_id)) if str(scenario_id) in copy_scenario_ids else 0),
        format_func=lambda value: copy_scenario_label(value, copy_scenario_labels),
        key=source_scenario_key,
        help="Choose the planning scenario containing the saved Yamazumi records to copy.",
    )
    source_areas = yamazumi_areas(project_id, source_scenario)
    source_area_ids = source_areas["id"].astype(str).tolist() if not source_areas.empty else []
    source_area_labels = (
        dict(zip(source_areas["id"].astype(str), source_areas["name"].astype(str)))
        if not source_areas.empty
        else {}
    )
    source_area_key = (
        f"yamazumi_copy_source_area_{project_id}_{scenario_id}_{copy_generation}_{source_scenario}"
    )
    source_area = st.selectbox(
        "Source Yamazumi area",
        options=source_area_ids,
        index=(source_area_ids.index(str(area_id)) if str(area_id) in source_area_ids else 0),
        format_func=lambda value: copy_area_label(value, source_area_labels),
        key=source_area_key,
        disabled=not source_area_ids,
    ) if source_area_ids else None

    target_scenario_key = (
        f"yamazumi_copy_target_scenario_{project_id}_{scenario_id}_{copy_generation}"
    )
    target_scenario = st.selectbox(
        "Target planning scenario",
        options=copy_scenario_ids,
        index=(copy_scenario_ids.index(str(scenario_id)) if str(scenario_id) in copy_scenario_ids else 0),
        format_func=lambda value: copy_scenario_label(value, copy_scenario_labels),
        key=target_scenario_key,
        help="The target must be another Yamazumi area in this project.",
    )
    target_areas = yamazumi_areas(project_id, target_scenario)
    if source_area and str(target_scenario) == str(source_scenario):
        target_areas = target_areas.loc[
            target_areas["id"].astype(str) != str(source_area)
        ].copy()
    target_area_ids = target_areas["id"].astype(str).tolist() if not target_areas.empty else []
    target_area_labels = (
        dict(zip(target_areas["id"].astype(str), target_areas["name"].astype(str)))
        if not target_areas.empty
        else {}
    )
    target_area_key = (
        f"yamazumi_copy_target_area_{project_id}_{scenario_id}_{copy_generation}_{target_scenario}_{source_area or 'none'}"
    )
    target_area = st.selectbox(
        "Target Yamazumi area",
        options=target_area_ids,
        format_func=lambda value: copy_area_label(value, target_area_labels),
        key=target_area_key,
        disabled=not target_area_ids,
    ) if target_area_ids else None

    selected_copy_pitch_ids: list[str] = []
    selected_copy_element_ids: list[str] = []
    source_copy_pitches = pd.DataFrame()
    source_copy_elements = pd.DataFrame()
    if source_area:
        source_copy_pitches = yamazumi_pitches(project_id, source_area)
        source_copy_elements = yamazumi_elements(project_id, source_area)
        pitch_counts = (
            source_copy_elements["pitch_id"].dropna().astype(str).value_counts()
            if not source_copy_elements.empty
            else pd.Series(dtype="Int64")
        )
        pitch_picker = source_copy_pitches.copy()
        if not pitch_picker.empty:
            pitch_picker["work_element_count"] = (
                pitch_picker["id"].astype(str).map(pitch_counts).fillna(0).astype(int)
            )
            pitch_picker = pitch_picker.rename(
                columns={
                    "pitch_number": "Pitch address",
                    "pitch_name": "Pitch name",
                    "pitch_type": "Pitch type",
                    "status": "Status",
                    "work_element_count": "Work elements",
                }
            )
        st.markdown("**Pitches to copy**")
        if pitch_picker.empty:
            st.caption("No saved pitches are available in this source area.")
        else:
            pitch_picker = pitch_picker[
                ["id", "Pitch address", "Pitch name", "Pitch type", "Status", "Work elements"]
            ]
            pitch_selection = selectable_dataframe(
                pitch_picker,
                key=(
                    f"yamazumi_copy_pitch_selector_{project_id}_{scenario_id}_"
                    f"{copy_generation}_{source_scenario}_{source_area}"
                ),
                hide_index=True,
                height=220,
                column_config={"id": None},
            )
            selected_copy_pitch_ids = selected_dataframe_rows(
                pitch_picker, pitch_selection
            )["id"].astype(str).tolist()

        element_picker = source_copy_elements.copy()
        if not element_picker.empty:
            pitch_number_by_id = dict(zip(
                source_copy_pitches["id"].astype(str),
                source_copy_pitches["pitch_number"].astype(str),
            )) if not source_copy_pitches.empty else {}
            element_picker["Pitch"] = element_picker["pitch_id"].apply(
                lambda value: (
                    pitch_number_by_id.get(str(value), "Unassigned")
                    if value is not None and not pd.isna(value)
                    else "Unassigned"
                )
            )
            element_picker["Model variants"] = element_picker.apply(
                lambda row: parse_yamazumi_model_variants(
                    row.get("model_variants"), row.get("model_variant")
                ),
                axis=1,
            )
            element_picker = element_picker.rename(
                columns={
                    "description": "Work description",
                    "time_s": "Time (s)",
                    "work_type": "Work type",
                    "work_region": "Work region",
                }
            )
        st.markdown("**Additional work elements to copy**")
        st.caption(
            "Work elements already contained in a selected pitch are copied once with that pitch."
        )
        if element_picker.empty:
            st.caption("No saved work elements are available in this source area.")
        else:
            element_picker = element_picker[
                [
                    "id", "pitch_id", "Pitch", "Work description", "Time (s)",
                    "Work type", "Model variants", "Work region",
                ]
            ]
            element_selection = selectable_dataframe(
                element_picker,
                key=(
                    f"yamazumi_copy_element_selector_{project_id}_{scenario_id}_"
                    f"{copy_generation}_{source_scenario}_{source_area}"
                ),
                hide_index=True,
                height=260,
                column_config={
                    "id": None,
                    "pitch_id": None,
                    "Model variants": st.column_config.ListColumn("Model variants"),
                },
            )
            selected_copy_element_ids = selected_dataframe_rows(
                element_picker, element_selection
            )["id"].astype(str).tolist()

    selected_pitch_id_set = set(selected_copy_pitch_ids)
    standalone_selected_ids = []
    if selected_copy_element_ids and not source_copy_elements.empty:
        selected_element_rows = source_copy_elements.loc[
            source_copy_elements["id"].astype(str).isin(selected_copy_element_ids)
        ]
        standalone_selected_ids = [
            str(row["id"])
            for _, row in selected_element_rows.iterrows()
            if str(row.get("pitch_id") or "") not in selected_pitch_id_set
        ]

    target_copy_pitches = (
        yamazumi_pitches(project_id, target_area) if target_area else pd.DataFrame()
    )
    active_target_copy_pitches = (
        target_copy_pitches.loc[target_copy_pitches["status"].astype(str) == "Active"].copy()
        if not target_copy_pitches.empty
        else target_copy_pitches
    )
    target_pitch_labels = (
        {
            str(row["id"]): yamazumi_pitch_label(
                row.get("pitch_number"), row.get("pitch_name")
            )
            for _, row in target_copy_pitches.iterrows()
        }
        if not target_copy_pitches.empty
        else {}
    )
    standalone_target_pitch = None
    if standalone_selected_ids and target_area:
        standalone_options = [None, *active_target_copy_pitches["id"].astype(str).tolist()]
        standalone_target_pitch = st.selectbox(
            "Destination for additional work elements",
            options=standalone_options,
            format_func=lambda value: (
                "Unassigned" if value is None else target_pitch_labels.get(str(value), "Unavailable pitch")
            ),
            key=(
                f"yamazumi_copy_standalone_target_{project_id}_{scenario_id}_"
                f"{copy_generation}_{target_scenario}_{target_area}"
            ),
            help="Copied work is appended to the selected Active pitch or the target area's Unassigned stack.",
        )

    pitch_number_overrides: dict[str, str] = {}
    feed_target_overrides: dict[str, str] = {}
    base_copy_plan = None
    copy_error = ""
    if target_area and (selected_copy_pitch_ids or selected_copy_element_ids):
        try:
            base_copy_plan = preview_yamazumi_copy(
                project_id,
                source_scenario,
                source_area,
                target_scenario,
                target_area,
                selected_copy_pitch_ids,
                selected_copy_element_ids,
                standalone_target_pitch_id=standalone_target_pitch,
            )
        except ValueError as exc:
            copy_error = str(exc)

    if base_copy_plan:
        for conflict in base_copy_plan["number_conflicts"]:
            source_pitch_id = str(conflict["source_pitch_id"])
            pitch_number_overrides[source_pitch_id] = st.text_input(
                f"New pitch address for {conflict['source_pitch_number']}",
                value="",
                placeholder="Enter an unused target-area address",
                key=(
                    f"yamazumi_copy_pitch_number_{project_id}_{scenario_id}_"
                    f"{copy_generation}_{source_pitch_id}_{target_area}"
                ),
                help=conflict["reason"],
            )
        feed_target_options = target_copy_pitches["id"].astype(str).tolist() if not target_copy_pitches.empty else []
        for required_mapping in base_copy_plan["feed_mapping_required"]:
            source_pitch_id = str(required_mapping["source_pitch_id"])
            mapped_target = st.selectbox(
                f"Feeds into pitch for {required_mapping['source_pitch_number']}",
                options=[None, *feed_target_options],
                format_func=lambda value: (
                    "Select a target-area pitch"
                    if value is None
                    else target_pitch_labels.get(str(value), "Unavailable pitch")
                ),
                key=(
                    f"yamazumi_copy_feed_target_{project_id}_{scenario_id}_"
                    f"{copy_generation}_{source_pitch_id}_{target_area}"
                ),
                help="Subassembly and Kitter pitches must feed into another pitch in the target Yamazumi area.",
            )
            if mapped_target:
                feed_target_overrides[source_pitch_id] = str(mapped_target)
        try:
            copy_plan_for_page = preview_yamazumi_copy(
                project_id,
                source_scenario,
                source_area,
                target_scenario,
                target_area,
                selected_copy_pitch_ids,
                selected_copy_element_ids,
                standalone_target_pitch_id=standalone_target_pitch,
                pitch_number_overrides=pitch_number_overrides,
                feed_target_overrides=feed_target_overrides,
            )
        except ValueError as exc:
            copy_error = str(exc)

    if copy_plan_for_page:
        with st.container(border=True):
            st.markdown("**Copy preflight**")
            st.write(
                f"{len(copy_plan_for_page['selected_pitches'])} pitch(es) and "
                f"{len(copy_plan_for_page['elements_to_copy'])} work element(s) will be created in "
                f"**{copy_plan_for_page['target']['name']}**."
            )
            if copy_plan_for_page["variant_additions"]:
                additions = sorted({
                    variant
                    for values in copy_plan_for_page["variant_additions"].values()
                    for variant in values
                })
                st.info("The target pitch will also enable: " + ", ".join(additions) + ".")
            if copy_plan_for_page["legacy_work_regions"]:
                st.warning(
                    "These Work regions are not defined in the target area and will be retained as legacy values: "
                    + ", ".join(copy_plan_for_page["legacy_work_regions"])
                    + "."
                )
            st.caption(
                "Process at a Glance links will not be copied. Copied work starts as Needs IE review."
            )
            for conflict in copy_plan_for_page["number_conflicts"]:
                st.error(
                    f"{conflict['source_pitch_number']}: {conflict['reason']}"
                )
            for mapping in copy_plan_for_page["feed_mapping_required"]:
                st.error(
                    f"Choose a target-area feed destination for {mapping['source_pitch_number']}."
                )
    elif copy_error:
        st.error(copy_error)
    elif not target_area:
        st.info("No different target Yamazumi area is available for the selected source area.")

    copy_blocked_by_draft = yamazumi_copy_has_unsaved_state()
    if copy_blocked_by_draft:
        st.warning(
            "Use Save & Refresh or Undo for current Yamazumi board/table changes before copying saved records."
        )
    current_copy_editor = str(st.session_state.get("current_editor", "")).strip()
    if not current_copy_editor:
        st.info("Enter the Current editor before confirming a copy.")
    copy_actions = st.container(horizontal=True)
    if copy_actions.button(
        "Reset copy",
        icon=":material/undo:",
        key=f"yamazumi_copy_reset_{project_id}_{scenario_id}_{copy_generation}",
    ):
        st.session_state.pop(copy_pending_key, None)
        st.session_state[copy_generation_key] = copy_generation + 1
        st.rerun()
    if copy_actions.button(
        "Review copy",
        type="primary",
        icon=":material/rate_review:",
        disabled=(
            copy_plan_for_page is None
            or not copy_plan_for_page.get("ready")
            or copy_blocked_by_draft
            or not current_copy_editor
        ),
        key=f"yamazumi_copy_review_{project_id}_{scenario_id}_{copy_generation}",
    ):
        st.session_state[copy_pending_key] = {
            "active_scenario_id": str(scenario_id),
            "source_scenario_id": str(source_scenario),
            "source_area_id": str(source_area),
            "target_scenario_id": str(target_scenario),
            "target_area_id": str(target_area),
            "pitch_ids": list(selected_copy_pitch_ids),
            "element_ids": list(selected_copy_element_ids),
            "standalone_target_pitch_id": standalone_target_pitch,
            "pitch_number_overrides": dict(pitch_number_overrides),
            "feed_target_overrides": dict(feed_target_overrides),
        }
        st.rerun()


@st.dialog("Copy to another area?", dismissible=False)
def confirm_yamazumi_copy() -> None:
    pending = st.session_state.get(copy_pending_key, {})
    if str(pending.get("active_scenario_id") or "") != str(scenario_id):
        st.error("The active planning scenario changed. Close this request and select the records again.")
        if st.button("Close", key=f"yamazumi_copy_stale_close_{project_id}_{scenario_id}"):
            st.session_state.pop(copy_pending_key, None)
            st.rerun()
        return
    try:
        pending_plan = preview_yamazumi_copy(
            project_id,
            pending["source_scenario_id"],
            pending["source_area_id"],
            pending["target_scenario_id"],
            pending["target_area_id"],
            pending.get("pitch_ids", []),
            pending.get("element_ids", []),
            standalone_target_pitch_id=pending.get("standalone_target_pitch_id"),
            pitch_number_overrides=pending.get("pitch_number_overrides", {}),
            feed_target_overrides=pending.get("feed_target_overrides", {}),
        )
        if not pending_plan["ready"]:
            raise ValueError("The copy choices are no longer valid. Cancel and review them again.")
        st.write(
            f"Create **{len(pending_plan['selected_pitches'])} pitch(es)** and "
            f"**{len(pending_plan['elements_to_copy'])} work element(s)** in "
            f"**{pending_plan['target']['scenario_name']} · {pending_plan['target']['name']}**?"
        )
        if pending_plan["proposed_pitch_numbers"]:
            st.write(
                "Pitch addresses: "
                + ", ".join(pending_plan["proposed_pitch_numbers"].values())
            )
        if pending_plan["feed_mappings"]:
            st.caption("All copied feeder pitches have a validated target-area feed mapping.")
        if pending_plan["variant_additions"]:
            st.info("Missing model variants will be enabled on the selected destination pitch.")
        if pending_plan["legacy_work_regions"]:
            st.warning("Unmatched Work region text will be retained as legacy values.")
        st.caption(
            "The source remains unchanged. New work has fresh IDs and no Process at a Glance link."
        )
    except (KeyError, ValueError) as exc:
        st.error(str(exc))
        pending_plan = None

    actions = st.container(horizontal=True)
    if actions.button(
        "Cancel",
        key=f"yamazumi_copy_cancel_{project_id}_{scenario_id}_{copy_generation}",
    ):
        st.session_state.pop(copy_pending_key, None)
        st.rerun()
    if actions.button(
        "Copy to another area",
        type="primary",
        icon=":material/content_copy:",
        disabled=pending_plan is None,
        key=f"yamazumi_copy_confirm_{project_id}_{scenario_id}_{copy_generation}",
    ):
        try:
            if yamazumi_copy_has_unsaved_state():
                raise ValueError(
                    "Use Save & Refresh or Undo for current Yamazumi changes before copying."
                )
            result = copy_yamazumi_records(
                project_id,
                pending["source_scenario_id"],
                pending["source_area_id"],
                pending["target_scenario_id"],
                pending["target_area_id"],
                pending.get("pitch_ids", []),
                pending.get("element_ids", []),
                standalone_target_pitch_id=pending.get("standalone_target_pitch_id"),
                pitch_number_overrides=pending.get("pitch_number_overrides", {}),
                feed_target_overrides=pending.get("feed_target_overrides", {}),
                editor_name=st.session_state.get("current_editor", ""),
            )
            if (
                str(pending["target_scenario_id"]) == str(scenario_id)
                and str(pending["target_area_id"]) == str(area_id)
            ):
                request_table_editor_reset(pitch_editor_key)
                request_table_editor_reset(element_editor_key)
            st.session_state.pop(copy_pending_key, None)
            st.session_state[copy_generation_key] = copy_generation + 1
            st.toast(
                f"Copied {result['pitches_created']} pitch(es) and "
                f"{result['elements_created']} work element(s)",
                icon=":material/check_circle:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


if st.session_state.get(copy_pending_key):
    confirm_yamazumi_copy()


with st.expander("Yamazumi history", icon=":material/history:"):
    (
        yamazumi_history_tab,
        pitch_history_tab,
        element_history_tab,
        variant_history_tab,
        region_history_tab,
    ) = st.tabs(
        [
            "Yamazumi actions",
            "Pitches",
            "Work elements",
            "Variants",
            "Work regions",
        ]
    )
    with yamazumi_history_tab:
        yamazumi_history = audit_history(project_id, "Yamazumi", limit=50)
        if yamazumi_history.empty:
            st.caption("No Yamazumi action history has been recorded yet.")
        else:
            selectable_dataframe(
                yamazumi_history.drop(columns=["details"], errors="ignore"),
                key=f"yamazumi_action_history_{project_id}_{scenario_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
    with pitch_history_tab:
        pitch_history = audit_history(project_id, "Yamazumi pitches", limit=50)
        if pitch_history.empty:
            st.caption("No Yamazumi pitch history has been recorded yet.")
        else:
            selectable_dataframe(
                pitch_history.drop(columns=["details"], errors="ignore"),
                key=f"yamazumi_pitch_history_{project_id}_{scenario_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
    with element_history_tab:
        element_history = audit_history(project_id, "Yamazumi elements", limit=50)
        if element_history.empty:
            st.caption("No Yamazumi work-element history has been recorded yet.")
        else:
            selectable_dataframe(
                element_history.drop(columns=["details"], errors="ignore"),
                key=f"yamazumi_element_history_{project_id}_{scenario_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
    with variant_history_tab:
        variant_history = audit_history(project_id, "Yamazumi variants", limit=50)
        if variant_history.empty:
            st.caption("No Yamazumi variant history has been recorded yet.")
        else:
            selectable_dataframe(
                variant_history.drop(columns=["details"], errors="ignore"),
                key=f"yamazumi_variant_history_{project_id}_{scenario_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
    with region_history_tab:
        region_history = audit_history(
            project_id, "Yamazumi work regions", limit=50
        )
        if region_history.empty:
            st.caption("No standardized work-region changes have been recorded yet.")
        else:
            selectable_dataframe(
                region_history.drop(columns=["details"], errors="ignore"),
                key=f"yamazumi_region_history_{project_id}_{scenario_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
