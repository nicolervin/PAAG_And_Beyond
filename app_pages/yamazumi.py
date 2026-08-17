import json
import math

import pandas as pd
import streamlit as st

from utils.store import (
    add_yamazumi_element,
    add_yamazumi_pitch,
    assembly_sections,
    audit_history,
    clear_yamazumi_data,
    clone_planning_scenario,
    complexity_features,
    delete_yamazumi_element,
    delete_yamazumi_flag_definitions,
    delete_yamazumi_pitch,
    get_planning_scenario,
    generate_yamazumi_pitch_range,
    import_yamazumi_rows,
    move_yamazumi_element,
    next_scenario_revision_label,
    parse_yamazumi_model_variants,
    record_audit_event,
    rename_yamazumi_variants,
    replace_yamazumi_elements,
    replace_yamazumi_flag_definitions,
    replace_yamazumi_pitches,
    replace_yamazumi_work_regions,
    update_yamazumi_area,
    update_yamazumi_element,
    update_yamazumi_pitch,
    sync_yamazumi_areas_from_fishbone,
    yamazumi_area_link_status,
    yamazumi_areas,
    yamazumi_elements,
    yamazumi_elements_for_scenario,
    yamazumi_flag_definitions,
    yamazumi_pitches,
    yamazumi_pitches_for_scenario,
    yamazumi_work_regions,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
)
from utils.table_ui import (
    dataframe_to_excel,
    editable_table_header,
    native_selected_rows,
    required_field_errors,
    table_has_unsaved_changes,
)
from utils.yamazumi_board import yamazumi_board


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
st.title("Yamazumi & workstation balancing")
st.caption(
    "Draft work directly, balance one operator per physical pitch, and route every change to IE review before updating the Process Plan."
)
if not project_id or not scenario_id:
    st.stop()

scenario = get_planning_scenario(project_id, scenario_id)
if not scenario:
    st.error("The active planning scenario no longer exists.")
    st.stop()

suggested_revision = next_scenario_revision_label(project_id, scenario["revision_label"])


@st.dialog("Save as planning scenario")
def save_as_scenario_dialog() -> None:
    st.caption(
        f"Copy Rev {scenario['revision_label']} · {scenario['name']}. The source scenario will remain unchanged."
    )
    with st.form(f"save_as_scenario_{scenario_id}"):
        name = st.text_input("New scenario name", value=f"{scenario['name']} · Rev {suggested_revision}")
        revision_label = st.text_input("Revision label", value=suggested_revision)
        takt_time = st.number_input(
            "Target takt time (seconds)", min_value=0.1, value=float(scenario["takt_time_s"]), step=0.1
        )
        change_summary = st.text_area(
            "What is changing?",
            placeholder="Example: Higher demand; rebalance the same work across six stations.",
        )
        if st.form_submit_button("Create scenario", type="primary", icon=":material/content_copy:"):
            try:
                new_scenario_id = clone_planning_scenario(
                    project_id,
                    scenario_id,
                    name,
                    revision_label,
                    takt_time,
                    change_summary,
                    st.session_state.get("current_editor", ""),
                )
                st.session_state.scenario_id = new_scenario_id
                st.session_state.pop("global_scenario", None)
                st.toast("Scenario created; the new branch is now active", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center"):
    st.caption(
        f"Rev {scenario['revision_label']} · {scenario['name']} · "
        f"{float(scenario['takt_time_s']):.1f} s takt"
    )
    if st.button("Save as scenario", type="primary", icon=":material/content_copy:"):
        save_as_scenario_dialog()

area_selector_key = f"yamazumi_area_{scenario_id}"
sections = assembly_sections(project_id)
features = complexity_features(project_id)
flag_definitions = yamazumi_flag_definitions(project_id)
active_flag_options = (
    flag_definitions.loc[
        flag_definitions["active"].fillna(1).astype(bool), "name"
    ].astype(str).tolist()
    if not flag_definitions.empty else ["CTQ", "Safety"]
)
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
rename_yamazumi_variants(project_id, scenario_id, stored_variant_labels)
active_sections = sections.loc[sections["active"].fillna(1).astype(bool)].copy() if not sections.empty else sections
fishbone_sections = active_sections
section_name_by_id = dict(zip(active_sections["id"].astype(str), active_sections["name"].astype(str))) if not active_sections.empty else {}
section_id_by_name = {name: section_id for section_id, name in section_name_by_id.items()}

with st.expander("Import Yamazumi workbook", icon=":material/upload_file:"):
    uploaded = st.file_uploader(
        "Yamazumi Excel file", type=["xlsx"], key=f"yamazumi_import_file_{scenario_id}"
    )
    st.caption(
        "Imports the current system-style fields. Sub-Line is matched to a Fishbone section by name when possible; unmatched areas remain available to link manually."
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
                {"areas": area_count, "pitches": pitch_count, "file": uploaded.name},
            )
            st.toast(f"Imported {element_count} work elements into {pitch_count} pitches", icon=":material/check_circle:")
            st.rerun()
        except (ValueError, TypeError) as exc:
            st.error(str(exc))

areas = yamazumi_areas(project_id, scenario_id)
if fishbone_sections.empty and areas.empty:
    st.info("Build an active Fishbone section first, or import a Yamazumi workbook to create an unlinked balancing area.")
    st.stop()

if not fishbone_sections.empty:
    link_status = yamazumi_area_link_status(project_id, scenario_id)
    if link_status["needs_sync"] and st.button(
        "Create Yamazumi areas from Fishbone",
        icon=":material/account_tree:",
        help="Creates or repairs one linked balancing area for every active Fishbone section, including subassemblies with no assigned parts.",
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
                "Synchronize Fishbone areas",
                summary["created"] + summary["relinked"] + summary["conflicts_cleared"],
                st.session_state.get("current_editor", ""),
                summary,
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

areas = yamazumi_areas(project_id, scenario_id)
if areas.empty:
    st.info("Create an area from the Fishbone or import a workbook to begin.")
    st.stop()

area_labels = {}
for _, row in areas.iterrows():
    section_name_value = row.get("section_name")
    section_name = (
        "" if section_name_value is None or pd.isna(section_name_value)
        else str(section_name_value).strip()
    )
    area_labels[str(row["id"])] = (
        f"{row['name']} · Fishbone: {section_name}" if section_name
        else f"{row['name']} · Unlinked"
    )
area_id = st.selectbox(
    "Balancing area / Fishbone spine",
    options=list(area_labels),
    format_func=lambda value: area_labels[value],
    key=area_selector_key,
)
area = areas.loc[areas["id"].astype(str) == str(area_id)].iloc[0].to_dict()
pitch_editor_key = f"yamazumi_pitch_editor_{scenario_id}_{area_id}"
element_editor_key = f"yamazumi_element_editor_{scenario_id}_{area_id}"
apply_pending_table_editor_reset(pitch_editor_key)
apply_pending_table_editor_reset(element_editor_key)

reset_actions = st.container(horizontal=True, horizontal_alignment="right")
request_clear_area = reset_actions.button(
    "Clear this area",
    icon=":material/delete_sweep:",
    help="Remove this area's Yamazumi pitches, work elements, and settings only.",
)
request_clear_all = reset_actions.button(
    "Clear all Yamazumi data",
    icon=":material/delete_forever:",
    help="Remove every Yamazumi area, pitch, work element, and Yamazumi setting in this scenario.",
)
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
    st.caption("Fishbone sections and existing Process Plan records will not be deleted or changed.")
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
        key="confirm_yamazumi_reset",
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

area_controls = st.container(horizontal=True, vertical_alignment="bottom")
section_id_value = area.get("section_id")
current_section_id = (
    None if section_id_value is None or pd.isna(section_id_value)
    else str(section_id_value).strip() or None
)
if current_section_id:
    linked_section = current_section_id
    area_controls.text_input(
        "Linked Fishbone section",
        value=str(area.get("section_name") or section_name_by_id.get(current_section_id, "Linked section")),
        disabled=True,
        help="This link is fixed because the area is already matched to the Fishbone.",
        key=f"linked_fishbone_read_only_{area_id}",
    )
else:
    linked_elsewhere = {
        str(value) for value in areas["section_id"].dropna().astype(str).tolist()
        if str(value).strip()
    }
    available_sections = [
        section_id for section_id in section_name_by_id
        if section_id not in linked_elsewhere
    ]
    linked_section = area_controls.selectbox(
        "Linked Fishbone section",
        options=[None, *available_sections],
        format_func=lambda value: "Unlinked" if value is None else section_name_by_id[value],
        help="Manual matching is available only for imported areas that could not be matched by name.",
        key=f"linked_fishbone_for_import_{area_id}",
    )
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
takt_time = area_controls.number_input(
    "Yamazumi takt time (seconds)",
    min_value=0.0,
    value=area_takt,
    step=0.1,
    help="Enter an area-specific takt or use the active planning scenario's target takt.",
)
if area_controls.button("Save area settings", type="primary", icon=":material/save:"):
    try:
        update_yamazumi_area(project_id, area_id, linked_section, takt_time or None)
        record_audit_event(project_id, "Yamazumi", "Area settings", 1, st.session_state.get("current_editor", ""))
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))
takt = float(takt_time or default_takt)
if not math.isfinite(takt):
    takt = default_takt

pitches = yamazumi_pitches(project_id, area_id)
if not pitches.empty:
    pitches["model_variants"] = pitches["model_variants"].apply(
        lambda value: [stored_variant_labels.get(item, item) for item in json.loads(value or '["Base"]')]
    )
elements = yamazumi_elements(project_id, area_id)
if not elements.empty:
    elements["flags"] = elements["flags"].apply(
        lambda value: json.loads(value or "[]") if isinstance(value, str) else (value or [])
    )
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

setup_columns = st.columns(3)
with setup_columns[0].expander("Generate pitch addresses", icon=":material/format_list_numbered:", expanded=pitches.empty):
    st.caption(
        "Enter the first and last physical addresses. The ending numbers are generated inclusively while preserving the shared prefix and leading zeros."
    )
    range_controls = st.container(horizontal=True, vertical_alignment="bottom")
    first_pitch = range_controls.text_input("First pitch", placeholder="01-ML1-001")
    last_pitch = range_controls.text_input("Last pitch", placeholder="01-ML1-020")
    number_mode = range_controls.selectbox("Numbers to create", ["All numbers", "Odd only", "Even only"])
    generated_status = range_controls.selectbox(
        "Starting status",
        ["Active", "Open", "Blocked"],
        help="Open and Blocked addresses cannot receive work until changed to Active.",
    )
    generated_pitch_type = range_controls.selectbox("Pitch type", PITCH_TYPES, index=0)
    generated_variants = st.multiselect(
        "Model variants shown on generated pitches",
        options=variant_options,
        default=["Base"],
        help="Every generated pitch starts with these visible variant stacks.",
    )
    if range_controls.button("Generate pitches", type="primary", icon=":material/add:"):
        try:
            created = generate_yamazumi_pitch_range(
                project_id, area_id, first_pitch, last_pitch, number_mode, generated_status, generated_variants,
                generated_pitch_type,
            )
            record_audit_event(
                project_id, "Yamazumi pitches", "Generate range", created,
                st.session_state.get("current_editor", ""),
                {"first": first_pitch, "last": last_pitch, "number_mode": number_mode, "status": generated_status, "pitch_type": generated_pitch_type, "variants": generated_variants},
            )
            st.toast(f"Generated {created} new pitch addresses", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

with setup_columns[1].expander("Define work regions", icon=":material/category:"):
    st.caption(
        "Define the area-specific categories used to classify work. Inactive regions remain on "
        "existing elements but cannot be assigned to new ones."
    )
    region_editor_key = f"yamazumi_region_editor_{area_id}"
    apply_pending_table_editor_reset(region_editor_key)
    region_rows = region_definitions.reindex(
        columns=["id", "name", "description", "active", "color", "sequence", "updated_at"]
    )
    # Empty columns created by reindex default to float64. Streamlit then rejects
    # TextColumn configuration before the first work region can be added.
    region_rows["name"] = region_rows["name"].astype("string").fillna("")
    region_rows["description"] = region_rows["description"].astype("string").fillna("")
    region_rows["active"] = region_rows["active"].fillna(1).astype(bool)

    region_header = editable_table_header(
        "Work regions",
        editor_key=region_editor_key,
        key_prefix=f"yamazumi_regions_{area_id}",
        native_row_selection=True,
    )
    visible_regions = filter_table(
        region_rows,
        key=f"yamazumi_region_filters_{area_id}",
        dropdown_columns=["active"],
        search_columns=["name", "description"],
        labels={"active": "Active"},
        reset_widget_keys=[region_editor_key],
    )
    edited_regions = st.data_editor(
        visible_regions,
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

    selected_regions = native_selected_rows(
        visible_regions, editor_key=region_editor_key
    )
    region_bulk = st.container(horizontal=True, vertical_alignment="bottom")
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
    request_region_delete = region_bulk.button(
        f"Delete selected ({len(selected_regions)})",
        icon=":material/delete:",
        disabled=selected_regions.empty,
        key=f"request_yamazumi_region_delete_{area_id}",
    )
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

    @st.dialog("Delete selected work regions?")
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
            st.rerun()
        if actions.button(
            "Delete regions",
            type="primary",
            icon=":material/delete:",
            key=f"confirm_yamazumi_region_delete_{area_id}",
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

    if region_header.undo:
        request_table_editor_reset(region_editor_key)
        st.rerun()

    if region_header.save_and_refresh:
        try:
            if not selected_regions.empty:
                raise ValueError("Clear selected rows before saving work-region edits.")
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
                project_id, "Yamazumi work regions", "Save & refresh", count,
                st.session_state.get("current_editor", ""),
            )
            request_table_editor_reset(region_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast(f"Saved {count} work-region definition(s)", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    if st.toggle("Show work-region history", key=f"show_yamazumi_region_history_{area_id}"):
        region_history = audit_history(project_id, "Yamazumi work regions", limit=50)
        if region_history.empty:
            st.caption("No standardized work-region changes have been recorded yet.")
        else:
            st.dataframe(
                region_history.drop(columns=["details"], errors="ignore"),
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

with setup_columns[2].expander("Define element flags", icon=":material/label:"):
    st.caption(
        "CTQ and Safety are permanent project flags. Add custom tags for other conditions that "
        "should be visible to the IE when editing a work element."
    )
    flag_editor_key = f"yamazumi_flag_editor_{project_id}"
    apply_pending_table_editor_reset(flag_editor_key)
    flag_rows = flag_definitions.copy()
    flag_rows["name"] = flag_rows["name"].astype("string").fillna("")
    flag_rows["description"] = flag_rows["description"].astype("string").fillna("")
    flag_rows["active"] = flag_rows["active"].fillna(1).astype(bool)
    flag_rows["system_flag"] = flag_rows["system_flag"].fillna(0).astype(bool)

    flag_header = editable_table_header(
        "Flag definitions",
        editor_key=flag_editor_key,
        key_prefix=f"yamazumi_flags_{project_id}",
        native_row_selection=True,
    )
    visible_flags = filter_table(
        flag_rows,
        key=f"yamazumi_flag_filters_{project_id}",
        dropdown_columns=["active"],
        search_columns=["name", "description"],
        labels={"active": "Active"},
        reset_widget_keys=[flag_editor_key],
    )

    edited_flags = st.data_editor(
        visible_flags,
        key=flag_editor_key,
        hide_index=True,
        num_rows="dynamic",
        height=300,
        disabled=["id", "system_flag", "sequence", "updated_at"],
        column_order=["name", "description", "active"],
        column_config={
            "id": None,
            "name": st.column_config.TextColumn("Flag name", required=True, pinned=True),
            "description": st.column_config.TextColumn("Description", width="large"),
            "active": st.column_config.CheckboxColumn(
                "Active", default=True,
                help="Inactive custom flags remain on existing work but cannot be added to new elements.",
            ),
            "system_flag": None,
            "sequence": None,
            "updated_at": None,
        },
    )

    selected_flags = native_selected_rows(visible_flags, editor_key=flag_editor_key)
    custom_selected_flags = selected_flags.loc[
        ~selected_flags["system_flag"].fillna(False).astype(bool)
    ] if not selected_flags.empty else selected_flags
    flag_bulk = st.container(horizontal=True, vertical_alignment="bottom")
    bulk_active = flag_bulk.selectbox(
        "Active for selected custom flags",
        [None, True, False],
        format_func=lambda value: "No change" if value is None else ("Active" if value else "Inactive"),
        key=f"yamazumi_flag_bulk_active_{project_id}",
    )
    apply_flag_bulk = flag_bulk.button(
        f"Apply to selected ({len(custom_selected_flags)})",
        type="primary",
        icon=":material/checklist:",
        disabled=custom_selected_flags.empty,
        key=f"apply_yamazumi_flag_bulk_{project_id}",
    )
    request_flag_bulk_delete = flag_bulk.button(
        f"Delete selected ({len(custom_selected_flags)})",
        icon=":material/delete:",
        disabled=custom_selected_flags.empty,
        key=f"request_yamazumi_flag_delete_{project_id}",
    )
    flag_bulk.download_button(
        "Export filtered",
        data=dataframe_to_excel(
            visible_flags[["name", "description", "active"]],
            "Yamazumi flags",
        ),
        file_name="yamazumi_flags_filtered.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        key=f"export_yamazumi_flags_{project_id}",
    )

    if apply_flag_bulk:
        if table_has_unsaved_changes(flag_editor_key, native_row_selection=True):
            st.warning("Save or undo other flag edits before applying a bulk change.")
        elif bulk_active is None:
            st.warning("Choose Active or Inactive to apply.")
        else:
            updated_flags = flag_rows.copy()
            selected_ids = set(custom_selected_flags["id"].astype(str))
            updated_flags.loc[
                updated_flags["id"].astype(str).isin(selected_ids), "active"
            ] = bulk_active
            count = replace_yamazumi_flag_definitions(project_id, updated_flags)
            record_audit_event(
                project_id,
                "Yamazumi flag definitions",
                "Bulk edit",
                len(selected_ids),
                st.session_state.get("current_editor", ""),
                {"active": bulk_active},
            )
            request_table_editor_reset(flag_editor_key)
            st.toast(f"Updated {len(selected_ids)} custom flags", icon=":material/check_circle:")
            st.rerun()

    if request_flag_bulk_delete:
        if table_has_unsaved_changes(flag_editor_key, native_row_selection=True):
            st.warning("Save or undo other flag edits before deleting selected flags.")
        else:
            st.session_state[f"yamazumi_flags_pending_delete_{project_id}"] = (
                custom_selected_flags["id"].astype(str).tolist()
            )

    @st.dialog("Delete custom Yamazumi flags?")
    def confirm_flag_delete() -> None:
        pending_key = f"yamazumi_flags_pending_delete_{project_id}"
        pending_ids = st.session_state.get(pending_key, [])
        st.warning(
            f"Delete {len(pending_ids)} custom flag(s)? The deleted tags will be removed from "
            "existing Yamazumi elements and those elements will return to IE review."
        )
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_yamazumi_flag_delete_{project_id}"):
            st.session_state.pop(pending_key, None)
            st.rerun()
        if actions.button(
            "Delete flags",
            type="primary",
            icon=":material/delete:",
            key=f"confirm_yamazumi_flag_delete_{project_id}",
        ):
            try:
                count = delete_yamazumi_flag_definitions(project_id, pending_ids)
                record_audit_event(
                    project_id,
                    "Yamazumi flag definitions",
                    "Bulk delete" if count > 1 else "Delete",
                    count,
                    st.session_state.get("current_editor", ""),
                )
                st.session_state.pop(pending_key, None)
                request_table_editor_reset(flag_editor_key)
                st.toast(f"Deleted {count} custom flags", icon=":material/delete:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if st.session_state.get(f"yamazumi_flags_pending_delete_{project_id}"):
        confirm_flag_delete()

    if flag_header.undo:
        request_table_editor_reset(flag_editor_key)
        st.rerun()

    if flag_header.save_and_refresh:
        try:
            if not selected_flags.empty:
                raise ValueError("Clear selected rows before saving flag edits.")
            errors = required_field_errors(edited_flags, {"name": "Flag name"})
            if errors:
                raise ValueError(" ".join(errors))
            combined_flags = merge_filtered_edits(flag_rows, visible_flags, edited_flags)
            count = replace_yamazumi_flag_definitions(project_id, combined_flags)
            record_audit_event(
                project_id,
                "Yamazumi flag definitions",
                "Save & refresh",
                count,
                st.session_state.get("current_editor", ""),
            )
            request_table_editor_reset(flag_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast(f"Saved {count} flag definitions", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    if st.toggle("Show flag-definition history", key=f"show_yamazumi_flag_history_{project_id}"):
        flag_history = audit_history(project_id, "Yamazumi flag definitions", limit=50)
        if flag_history.empty:
            st.caption("No standardized flag-definition changes have been recorded yet.")
        else:
            st.dataframe(
                flag_history.drop(columns=["details"], errors="ignore"),
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

times = pd.to_numeric(elements.get("time_s", pd.Series(dtype=float)), errors="coerce").fillna(0)
total_work = float(times.sum())
active_pitch_count = int((pitches["status"] == "Active").sum()) if not pitches.empty else 0
theoretical = total_work / takt if takt > 0 else 0
efficiency = total_work / (active_pitch_count * takt) * 100 if active_pitch_count and takt > 0 else 0
pitch_totals = elements.assign(time_s=times).groupby("pitch_number", dropna=True)["time_s"].sum() if not elements.empty else pd.Series(dtype=float)
bottleneck = str(pitch_totals.idxmax()) if not pitch_totals.empty else "—"

metrics = st.container(horizontal=True)
metrics.metric("Total work content", f"{total_work:.1f} s", border=True)
metrics.metric("Theoretical operators", f"{theoretical:.2f}", border=True)
metrics.metric("Active pitches / operators", active_pitch_count, border=True)
metrics.metric("Line balance efficiency", f"{efficiency:.1f}%", border=True)
metrics.metric("Bottleneck pitch", bottleneck, border=True)
metrics.metric("Takt", f"{takt:.1f} s", border=True)

board_key = f"yamazumi_board_{project_id}_{area_id}"
add_pitch_dialog_key = f"yamazumi_show_add_pitch_{project_id}_{area_id}"
add_element_dialog_key = f"yamazumi_add_element_target_{project_id}_{area_id}"
edit_pitch_dialog_key = f"yamazumi_edit_pitch_target_{project_id}_{area_id}"
edit_element_dialog_key = f"yamazumi_edit_element_target_{project_id}_{area_id}"


def close_other_yamazumi_dialogs(keep: str) -> None:
    """Guarantee that only one Streamlit dialog is eligible in a script run."""
    for dialog_key in (
        add_pitch_dialog_key,
        add_element_dialog_key,
        edit_pitch_dialog_key,
        edit_element_dialog_key,
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
    enabled_variants = move_yamazumi_element(
        project_id, str(move.get("element_id")), move.get("pitch_id")
    )
    details = {**move, "variants_added_to_pitch": enabled_variants}
    record_audit_event(
        project_id, "Yamazumi", "Move work element", 1,
        st.session_state.get("current_editor", ""), details,
    )
    if enabled_variants:
        request_table_editor_reset(pitch_editor_key)


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
    pitch_number = st.text_input("Pitch address", placeholder="01-ML1-001")
    pitch_name = st.text_input("Pitch name")
    status = st.selectbox("Status", ["Active", "Open", "Blocked"], index=0)
    pitch_type = st.selectbox("Pitch type", PITCH_TYPES, index=0)
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
            add_yamazumi_pitch(
                project_id, area_id, pitch_number, pitch_name, status, selected_pitch_variants, pitch_type
            )
            record_audit_event(
                project_id, "Yamazumi pitches", "Add from interactive board", 1,
                st.session_state.get("current_editor", ""), {"pitch_number": pitch_number, "status": status, "pitch_type": pitch_type},
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
    time_s = st.number_input("Time to complete (seconds)", min_value=0.0, value=0.0, step=0.1)
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
    flags = st.multiselect("Flags", active_flag_options)
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
                    "time_s": time_s,
                    "model_variants": model_variants,
                    "work_type": work_type,
                    "work_region": work_region,
                    "flags": flags,
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
    current_variants = list(current.get("model_variants") or ["Base"])
    pitch_number = st.text_input(
        "Pitch address", value=str(current.get("pitch_number") or ""), key=f"edit_pitch_number_{pitch_id}"
    )
    pitch_name = st.text_input(
        "Pitch name", value=str(current.get("pitch_name") or ""), key=f"edit_pitch_name_{pitch_id}"
    )
    statuses = ["Active", "Open", "Blocked"]
    current_status = str(current.get("status") or "Active")
    status = st.selectbox(
        "Status", statuses, index=statuses.index(current_status) if current_status in statuses else 0,
        key=f"edit_pitch_status_{pitch_id}",
    )
    current_pitch_type = str(current.get("pitch_type") or "Pitch").title()
    pitch_type = st.selectbox(
        "Pitch type", PITCH_TYPES,
        index=PITCH_TYPES.index(current_pitch_type) if current_pitch_type in PITCH_TYPES else 0,
        key=f"edit_pitch_type_{pitch_id}",
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
                {"pitch_number": pitch_number, "pitch_name": pitch_name, "status": status, "model_variants": selected_variants, "pitch_type": pitch_type},
            )
            record_audit_event(
                project_id, "Yamazumi pitches", "Edit from interactive board", 1,
                st.session_state.get("current_editor", ""), {"pitch_id": pitch_id, "pitch_number": pitch_number},
            )
            st.session_state.pop(state_key, None)
            request_table_editor_reset(pitch_editor_key)
            st.toast(f"Updated pitch {pitch_number}", icon=":material/check_circle:")
            st.rerun(scope="app")
        except ValueError as exc:
            st.error(str(exc))
    st.divider()
    assigned_count = int((elements["pitch_id"].astype(str) == str(pitch_id)).sum()) if not elements.empty else 0
    delete_confirmed = st.checkbox(
        "Confirm pitch deletion",
        key=f"confirm_delete_pitch_{pitch_id}",
        help=(
            f"The pitch will be deleted and its {assigned_count} assigned work element(s) will move to Unassigned."
            if assigned_count else "The pitch will be permanently deleted."
        ),
    )
    if st.button(
        "Delete pitch", icon=":material/delete:", disabled=not delete_confirmed,
        key=f"delete_pitch_{pitch_id}",
    ):
        try:
            moved = delete_yamazumi_pitch(project_id, area_id, str(pitch_id))
            record_audit_event(
                project_id, "Yamazumi pitches", "Delete from interactive board", 1,
                st.session_state.get("current_editor", ""), {"pitch_id": pitch_id, "elements_unassigned": moved},
            )
            st.session_state.pop(state_key, None)
            request_table_editor_reset(pitch_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast(
                f"Deleted pitch; {moved} work element(s) moved to Unassigned",
                icon=":material/delete:",
            )
            st.rerun(scope="app")
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Edit Yamazumi work element")
def edit_element_dialog(element_id: str) -> None:
    state_key = f"yamazumi_edit_element_target_{project_id}_{area_id}"
    matches = elements.loc[elements["id"].astype(str) == str(element_id)]
    if matches.empty:
        st.warning("That work element is no longer available.")
        if st.button("Close", key="close_missing_element"):
            st.session_state.pop(state_key, None)
            st.rerun()
        return
    current = matches.iloc[0]
    active_pitches = pitches.loc[pitches["status"] == "Active"].copy()
    pitch_label_by_id = {
        str(row["id"]): f"{row['pitch_number']} — {row['pitch_name']}".rstrip(" —")
        for _, row in active_pitches.iterrows()
    }
    destinations = [None, *pitch_label_by_id]
    current_pitch_id = str(current.get("pitch_id") or "") or None
    with st.form(f"edit_element_form_{element_id}"):
        selected_pitch_id = st.selectbox(
            "Pitch",
            options=destinations,
            index=destinations.index(current_pitch_id) if current_pitch_id in destinations else 0,
            format_func=lambda value: "Unassigned" if value is None else pitch_label_by_id[value],
        )
        description = st.text_area("Work description", value=str(current.get("description") or ""))
        time_s = st.number_input(
            "Time to complete (seconds)", min_value=0.0, value=float(current.get("time_s") or 0), step=0.1
        )
        current_variants = list(current.get("model_variants") or ["Base"])
        available_variants = list(dict.fromkeys([*variant_options, *current_variants]))
        row = st.container(horizontal=True, vertical_alignment="bottom")
        model_variants = row.multiselect(
            "Model variants", available_variants, default=current_variants,
            help=ELEMENT_VARIANT_HELP,
        )
        current_work_type = str(current.get("work_type") or "Cycle").title()
        work_type = row.selectbox(
            "Work type", WORK_TYPES,
            index=WORK_TYPES.index(current_work_type) if current_work_type in WORK_TYPES else 0,
        )
        current_work_region = str(current.get("work_region") or "None")
        edit_region_options = list(dict.fromkeys([*work_region_options, current_work_region]))
        work_region = row.selectbox(
            "Work region", edit_region_options,
            index=edit_region_options.index(current_work_region),
        )
        current_flags = list(current.get("flags") or [])
        edit_flag_options = list(dict.fromkeys([*active_flag_options, *current_flags]))
        flags = st.multiselect("Flags", edit_flag_options, default=current_flags)
        actions = st.container(horizontal=True)
        # The first submit button is Streamlit's Ctrl+Enter target. Keep Save
        # first so the text-area keyboard hint performs the expected action.
        save_edit = actions.form_submit_button("Save element", type="primary", icon=":material/save:")
        cancel_edit = actions.form_submit_button("Cancel", shortcut="Esc")
    if save_edit:
        try:
            update_yamazumi_element(
                project_id, area_id, str(element_id),
                {
                    "pitch_id": selected_pitch_id, "model_variants": model_variants, "work_type": work_type,
                    "description": description, "time_s": time_s, "work_region": work_region, "flags": flags,
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
    if cancel_edit:
        st.session_state.pop(state_key, None)
        st.rerun(scope="app")

    st.divider()
    delete_confirmed = st.checkbox(
        "Confirm element deletion", key=f"confirm_delete_element_{element_id}"
    )
    if st.button(
        "Delete element", icon=":material/delete:", disabled=not delete_confirmed,
        key=f"delete_element_{element_id}",
    ):
        try:
            delete_yamazumi_element(project_id, area_id, str(element_id))
            record_audit_event(
                project_id, "Yamazumi elements", "Delete from interactive board", 1,
                st.session_state.get("current_editor", ""), {"element_id": element_id},
            )
            st.session_state.pop(state_key, None)
            request_table_editor_reset(element_editor_key)
            st.toast("Deleted Yamazumi work element", icon=":material/delete:")
            st.rerun(scope="app")
        except ValueError as exc:
            st.error(str(exc))


st.subheader("Interactive balancing board")
if len(defined_variant_options) == 1:
    st.info(
        "Only Base is available. Add active feature definitions and allowed choices on Model Definitions to create additional Yamazumi variants."
    )
st.caption(
    "Drag work between pitch addresses. Odd-numbered pitches appear north/top; even-numbered pitches appear south/bottom."
)
yamazumi_board(
    pitches.to_dict("records"),
    elements.to_dict("records"),
    variants,
    takt,
    key=board_key,
    on_move=handle_yamazumi_move,
    on_add_pitch=handle_add_pitch_request,
    on_add_element=handle_add_element_request,
    on_edit_pitch=handle_edit_pitch_request,
    on_edit_element=handle_edit_element_request,
)
if st.session_state.get(add_pitch_dialog_key):
    add_pitch_dialog()
elif st.session_state.get(add_element_dialog_key):
    add_element_dialog()
elif st.session_state.get(edit_pitch_dialog_key):
    edit_pitch_dialog()
elif edit_element_target := st.session_state.pop(edit_element_dialog_key, None):
    # Treat a board click as a one-shot event. The dialog fragment retains its
    # argument during interaction, while page navigation cannot replay it.
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


pitch_table_area_key = f"yamazumi_pitch_table_area_{scenario_id}"
selected_pitch_area_ids = normalize_table_area_filter(pitch_table_area_key)
effective_pitch_area_ids = selected_pitch_area_ids or yamazumi_area_ids
pitch_combined_view = set(effective_pitch_area_ids) != {str(area_id)}
if pitch_combined_view:
    st.subheader("Pitch addresses")
else:
    pitch_actions = editable_table_header(
        "Pitch addresses",
        editor_key=pitch_editor_key,
        key_prefix="yamazumi_pitches",
        save_label="Save & refresh",
        native_row_selection=True,
    )
    if pitch_actions.undo:
        st.session_state.pop(pitch_editor_key, None)
        st.rerun()
selected_pitch_area_ids = st.multiselect(
    "Areas shown in pitch-address table",
    options=yamazumi_area_ids,
    format_func=lambda value: area_labels.get(value, value),
    placeholder="All Yamazumi areas",
    key=pitch_table_area_key,
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
        # MultiselectColumn values are lists, so this column deliberately uses object dtype.
        "model_variants": pd.Series(dtype="object"),
        "sequence": pd.Series(dtype="Int64"),
        "updated_at": pd.Series(dtype="string"),
    })
else:
    pitch_rows = pitch_table_source.reindex(columns=pitch_columns).copy()
pitch_filter_scope = "combined" if pitch_combined_view else str(area_id)
visible_pitches = filter_table(
    pitch_rows,
    key=f"yamazumi_pitch_filters_{scenario_id}_{pitch_filter_scope}",
    dropdown_columns=["area_name", "pitch_type", "status", "model_variants"],
    search_columns=["area_name", "pitch_number", "pitch_name", "pitch_type", "status", "model_variants"],
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
    "model_variants", "sequence",
]
pitch_column_config = {
    "id": None,
    "area_name": st.column_config.TextColumn("Yamazumi area"),
    "pitch_number": st.column_config.TextColumn("Pitch address", required=True, help="Use the physical line address/nomenclature."),
    "pitch_name": st.column_config.TextColumn("Pitch name"),
    "pitch_type": st.column_config.SelectboxColumn("Pitch type", options=PITCH_TYPES, required=True, default="Pitch"),
    "status": st.column_config.SelectboxColumn("Status", options=["Active", "Blocked", "Open"], required=True, default="Active"),
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
    }
    st.dataframe(
        visible_pitches,
        hide_index=True,
        height=280,
        column_order=pitch_column_order,
        column_config=pitch_read_only_config,
    )
    edited_pitches = visible_pitches
else:
    edited_pitches = st.data_editor(
        visible_pitches,
        key=pitch_editor_key,
        hide_index=True,
        num_rows="dynamic",
        height=280,
        disabled=["id", "area_name", "updated_at"],
        column_order=pitch_column_order,
        column_config=pitch_column_config,
    )
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
    if (st.session_state.get(pitch_editor_key, {}) or {}).get("deleted_rows"):
        st.warning("Selected pitches are not deleted during Save. A confirmed bulk-delete workflow will be added after work reassignment rules are finalized.")
    else:
        try:
            errors = required_field_errors(edited_pitches, {"pitch_number": "Pitch address", "status": "Status"})
            if errors:
                raise ValueError(" ".join(errors))
            to_save = merge_filtered_edits(pitch_rows, visible_pitches, edited_pitches)
            count = replace_yamazumi_pitches(project_id, area_id, to_save)
            record_audit_event(project_id, "Yamazumi pitches", "Save & refresh", count, st.session_state.get("current_editor", ""))
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
    element_actions = editable_table_header(
        "Yamazumi work elements",
        editor_key=element_editor_key,
        key_prefix="yamazumi_elements",
        save_label="Save & refresh",
        native_row_selection=True,
    )
    if element_actions.undo:
        st.session_state.pop(element_editor_key, None)
        st.rerun()
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
        element_table_source["flags"] = element_table_source["flags"].apply(
            lambda value: json.loads(value or "[]") if isinstance(value, str) else (value or [])
        )
        element_table_source["model_variants"] = element_table_source.apply(
            lambda row: [
                stored_variant_labels.get(item, item)
                for item in parse_yamazumi_model_variants(
                    row.get("model_variants"), str(row.get("model_variant") or "Base")
                )
            ],
            axis=1,
        )
    scope_caption = "every Yamazumi area" if not selected_element_area_ids else "the selected Yamazumi areas"
    st.caption(f"Showing {scope_caption} in this scenario. Combined views are read-only.")
else:
    element_table_source = elements.copy()
    element_table_source["area_name"] = str(area["name"])
active_pitches = pitches.loc[pitches["status"] == "Active"].copy() if not pitches.empty else pitches
pitch_label_by_id = dict(zip(active_pitches["id"].astype(str), active_pitches["pitch_number"].astype(str))) if not active_pitches.empty else {}
element_columns = [
    "id", "area_name", "pitch_id", "model_variants", "work_type", "description", "time_s", "work_region",
    "flags", "sequence", "source", "process_element_id", "process_sync_status", "updated_at",
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
        # MultiselectColumn values are lists, so this column deliberately uses object dtype.
        "flags": pd.Series(dtype="object"),
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
element_filter_scope = "combined" if element_combined_view else str(area_id)
visible_elements = filter_table(
    element_rows,
    key=f"yamazumi_element_filters_{scenario_id}_{element_filter_scope}",
    dropdown_columns=["area_name", "pitch", "model_variants", "work_type", "work_region", "flags"],
    search_columns=["area_name", "description", "pitch", "model_variants", "work_region", "flags"],
    labels={"area_name": "Yamazumi area", "model_variants": "Model variant", "flags": "Flag"},
    multi_value_columns=["model_variants", "flags"],
    reset_widget_keys=[] if element_combined_view else [element_editor_key],
)
pitch_options = ["Unassigned", *pitch_label_by_id.values()]
variant_options_by_pitch_label = {
    pitch_label_by_id[pitch_id]: pitch_variants_by_id.get(pitch_id, ["Base"])
    for pitch_id in pitch_label_by_id
}
element_column_order = [
    "area_name", "pitch", "model_variants", "work_type", "description", "time_s",
    "work_region", "flags", "sequence",
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
    "time_s": st.column_config.NumberColumn("Time (s)", min_value=0.0, step=0.1, format="%.1f", required=True),
    "work_region": st.column_config.SelectboxColumn(
        "Work region", options=work_region_options, required=True, default="None"
    ),
    "flags": st.column_config.MultiselectColumn(
        "Flags",
        options=list(dict.fromkeys([
            *active_flag_options,
            *[
                str(flag)
                for stored_flags in element_table_source.get("flags", pd.Series(dtype=object))
                for flag in (stored_flags or [])
            ],
        ])),
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
        "flags": st.column_config.ListColumn("Flags"),
    }
    st.dataframe(
        visible_elements,
        hide_index=True,
        height=420,
        column_order=element_column_order,
        column_config=element_read_only_config,
    )
    edited_elements = visible_elements
else:
    edited_elements = st.data_editor(
        visible_elements,
        key=element_editor_key,
        hide_index=True,
        num_rows="dynamic",
        height=420,
        disabled=["id", "area_name", "source", "process_element_id", "process_sync_status", "updated_at"],
        column_order=element_column_order,
        column_config=element_column_config,
    )
st.download_button(
    "Export filtered work elements",
    data=dataframe_to_excel(
        visible_elements.drop(
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
    if (st.session_state.get(element_editor_key, {}) or {}).get("deleted_rows"):
        st.warning("Selected work elements are not deleted during Save. Use the forthcoming confirmed bulk-delete action.")
    else:
        try:
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
            count = replace_yamazumi_elements(project_id, area_id, to_save)
            record_audit_event(project_id, "Yamazumi elements", "Save & refresh", count, st.session_state.get("current_editor", ""))
            request_table_editor_reset(element_editor_key)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
