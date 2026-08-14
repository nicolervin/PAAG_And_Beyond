import json

import pandas as pd
import streamlit as st

from utils.store import (
    add_yamazumi_element,
    add_yamazumi_pitch,
    assembly_sections,
    clear_yamazumi_data,
    clone_planning_scenario,
    complexity_features,
    delete_yamazumi_element,
    delete_yamazumi_pitch,
    get_planning_scenario,
    generate_yamazumi_pitch_range,
    import_yamazumi_rows,
    move_yamazumi_element,
    next_scenario_revision_label,
    record_audit_event,
    reconcile_yamazumi_to_process,
    rename_yamazumi_variants,
    replace_yamazumi_elements,
    replace_yamazumi_pitches,
    replace_yamazumi_work_regions,
    update_yamazumi_area,
    update_yamazumi_element,
    update_yamazumi_pitch,
    upsert_yamazumi_area,
    yamazumi_areas,
    yamazumi_elements,
    yamazumi_pitches,
    yamazumi_work_regions,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
)
from utils.table_ui import editable_table_header, native_selected_rows, required_field_errors
from utils.yamazumi_board import yamazumi_board


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
WORK_TYPES = ["Cycle", "Periodic", "Fluctuation"]
PITCH_TYPES = ["Pitch", "Waterspider", "Subassembly", "Kitter", "Repacker"]
REGION_COLORS = {
    "Blue": "#1e88e5", "Sky blue": "#54b8d6", "Teal": "#00897b", "Cyan": "#00acc1",
    "Green": "#43a047", "Lime": "#7cb342", "Olive": "#9e9d24", "Yellow": "#fdd835",
    "Amber": "#ffb300", "Orange": "#fb8c00", "Deep orange": "#f4511e", "Red": "#e53935",
    "Pink": "#d81b60", "Purple": "#8e24aa", "Violet": "#6d4cbd", "Indigo": "#3949ab",
    "Brown": "#6d4c41", "Gray": "#757575", "Blue gray": "#546e7a", "Mint": "#26a69a",
}
ELEMENT_VARIANT_HELP = (
    "This list contains only model variants enabled for the selected pitch. "
    "If the variant you need is missing, close this window, choose Edit pitch on the balancing board, "
    "add the variant under Model variants shown on this pitch, and save the pitch first."
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

pitch_editor_key = f"yamazumi_pitch_editor_{scenario_id}"
element_editor_key = f"yamazumi_element_editor_{scenario_id}"
area_selector_key = f"yamazumi_area_{scenario_id}"
apply_pending_table_editor_reset(pitch_editor_key)
apply_pending_table_editor_reset(element_editor_key)
sections = assembly_sections(project_id)
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
rename_yamazumi_variants(project_id, scenario_id, stored_variant_labels)
active_sections = sections.loc[sections["active"].fillna(1).astype(bool)].copy() if not sections.empty else sections
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
if active_sections.empty and areas.empty:
    st.info("Build Fishbone sections first, or import a Yamazumi workbook to create unlinked balancing areas.")
    st.stop()

if not active_sections.empty:
    existing_section_ids = set(areas["section_id"].dropna().astype(str)) if not areas.empty else set()
    missing_sections = active_sections.loc[~active_sections["id"].astype(str).isin(existing_section_ids)]
    if not missing_sections.empty and st.button(
        "Create Yamazumi areas from Fishbone",
        icon=":material/account_tree:",
        help="Creates one balancing area for each Fishbone section that does not have one yet.",
    ):
        for _, section in missing_sections.iterrows():
            upsert_yamazumi_area(
                project_id, scenario_id, str(section["name"]), str(section["id"])
            )
        st.toast(f"Created {len(missing_sections)} Yamazumi areas", icon=":material/check_circle:")
        st.rerun()

areas = yamazumi_areas(project_id, scenario_id)
if areas.empty:
    st.info("Create an area from the Fishbone or import a workbook to begin.")
    st.stop()

area_labels = {
    str(row["id"]): f"{row['name']}" + (f" · Fishbone: {row['section_name']}" if str(row.get("section_name") or "").strip() else " · Unlinked")
    for _, row in areas.iterrows()
}
area_id = st.selectbox(
    "Balancing area / Fishbone spine",
    options=list(area_labels),
    format_func=lambda value: area_labels[value],
    key=area_selector_key,
)
area = areas.loc[areas["id"].astype(str) == str(area_id)].iloc[0].to_dict()

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
linked_section = area_controls.selectbox(
    "Linked Fishbone section",
    options=[None, *section_name_by_id],
    index=([None, *section_name_by_id].index(str(area["section_id"])) if str(area.get("section_id") or "") in section_name_by_id else 0),
    format_func=lambda value: "Unlinked" if value is None else section_name_by_id[value],
)
default_takt = float(scenario.get("takt_time_s") or 0)
takt_time = area_controls.number_input(
    "Yamazumi takt time (seconds)",
    min_value=0.0,
    value=float(area.get("takt_override_s") or default_takt),
    step=0.1,
    help="Enter an area-specific takt or use the active planning scenario's target takt.",
)
if area_controls.button("Save area settings", type="primary", icon=":material/save:"):
    update_yamazumi_area(project_id, area_id, linked_section, takt_time or None)
    record_audit_event(project_id, "Yamazumi", "Area settings", 1, st.session_state.get("current_editor", ""))
    st.rerun()
takt = float(takt_time or default_takt)

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
    elements["model_variant"] = elements["model_variant"].apply(
        lambda value: stored_variant_labels.get(str(value), str(value))
    )

region_definitions = yamazumi_work_regions(project_id, area_id)
region_colors = (
    dict(zip(region_definitions["name"].astype(str), region_definitions["color"].astype(str)))
    if not region_definitions.empty else {}
)
legacy_work_regions = sorted(
    {
        str(value).strip()
        for value in elements.get("work_region", pd.Series(dtype=str)).dropna()
        if str(value).strip() and str(value).strip() != "None" and str(value).strip() not in region_colors
    }
)
work_region_options = ["None", *region_colors, *legacy_work_regions]
legacy_variant_options = [
    value
    for value in elements.get("model_variant", pd.Series(dtype=str)).dropna().astype(str).tolist()
    if value not in defined_variant_options
]
variant_options = list(dict.fromkeys([*defined_variant_options, *legacy_variant_options]))
variants = variant_options
pitch_variants_by_id = {
    str(row["id"]): list(row["model_variants"] or ["Base"])
    for _, row in pitches.iterrows()
}

setup_columns = st.columns(2)
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

with setup_columns[1].expander("Define work regions", icon=":material/palette:"):
    st.caption("Name the area-specific regions used in element dropdowns and choose their Yamazumi highlight colors.")
    region_editor_key = f"yamazumi_region_editor_{area_id}"
    apply_pending_table_editor_reset(region_editor_key)
    color_name_by_hex = {color.casefold(): name for name, color in REGION_COLORS.items()}
    region_rows = pd.DataFrame(
        {
            "id": region_definitions.get("id", pd.Series(dtype=str)),
            "Delete": False,
            "name": region_definitions.get("name", pd.Series(dtype=str)),
            "color": region_definitions.get("color", pd.Series(dtype=str)).apply(
                lambda value: color_name_by_hex.get(str(value).casefold(), "Sky blue")
            ),
        }
    )
    edited_regions = st.data_editor(
        region_rows,
        key=region_editor_key,
        hide_index=True,
        num_rows="dynamic",
        column_order=["Delete", "name", "color"],
        column_config={
            "id": None,
            "Delete": st.column_config.CheckboxColumn("Delete", default=False),
            "name": st.column_config.TextColumn("Region name", required=True),
            "color": st.column_config.SelectboxColumn(
                "Color", options=list(REGION_COLORS), required=True,
                help="Choose one of the 20 standard Yamazumi colors.",
            ),
        },
    )
    if st.button("Save work regions", type="primary", icon=":material/save:", key=f"save_work_regions_{area_id}"):
        try:
            kept_regions = edited_regions.loc[~edited_regions["Delete"].fillna(False).astype(bool)].copy()
            incomplete = kept_regions["name"].fillna("").astype(str).str.strip().eq("") | kept_regions["color"].isna()
            kept_regions = kept_regions.loc[~incomplete]
            region_records = [
                {
                    "id": row.get("id"),
                    "name": str(row["name"]).strip(),
                    "color": REGION_COLORS[str(row["color"])],
                }
                for _, row in kept_regions.iterrows()
            ]
            count = replace_yamazumi_work_regions(project_id, area_id, region_records)
            record_audit_event(
                project_id, "Yamazumi work regions", "Save definitions", count,
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
    move_yamazumi_element(project_id, str(move.get("element_id")), move.get("pitch_id"))
    record_audit_event(
        project_id, "Yamazumi", "Move work element", 1,
        st.session_state.get("current_editor", ""), move,
    )


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
    target_variants = pitch_variants_by_id.get(str(target_pitch_id), variant_options) if target_pitch_id else variant_options
    model_variant = row.selectbox(
        "Model variant",
        options=target_variants,
        index=0,
        help=ELEMENT_VARIANT_HELP,
    )
    work_type = row.selectbox("Work type", WORK_TYPES, index=0)
    work_region = row.selectbox("Work region", work_region_options, index=0)
    flags = st.multiselect("Flags", ["CTQ", "Safety"])
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
                    "model_variant": model_variant,
                    "work_type": work_type,
                    "work_region": work_region,
                    "flags": flags,
                },
            )
            record_audit_event(
                project_id, "Yamazumi elements", "Add from interactive board", 1,
                st.session_state.get("current_editor", ""),
                {"pitch": target.get("pitch_number"), "description": description},
            )
            st.session_state.pop(f"yamazumi_add_element_target_{project_id}_{area_id}", None)
            request_table_editor_reset(element_editor_key)
            st.toast("Added Yamazumi work element", icon=":material/check_circle:")
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
        available_variants = pitch_variants_by_id.get(str(selected_pitch_id), variant_options) if selected_pitch_id else variant_options
        current_variant = str(current.get("model_variant") or "Base")
        if current_variant not in available_variants:
            current_variant = available_variants[0]
        row = st.container(horizontal=True, vertical_alignment="bottom")
        model_variant = row.selectbox(
            "Model variant", available_variants, index=available_variants.index(current_variant),
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
        flags = st.multiselect("Flags", ["CTQ", "Safety"], default=current_flags)
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
                    "pitch_id": selected_pitch_id, "model_variant": model_variant, "work_type": work_type,
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
    "Drag work between pitch addresses. Odd-numbered pitches appear north/top; even-numbered pitches appear south/bottom. "
    "Every move is marked Needs IE review for Process Plan reconciliation."
)
yamazumi_board(
    pitches.to_dict("records"),
    elements.to_dict("records"),
    variants,
    takt,
    region_colors,
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
pitch_columns = ["id", "pitch_number", "pitch_name", "pitch_type", "status", "model_variants", "sequence", "updated_at"]
pitch_rows = pitches.reindex(columns=pitch_columns).copy() if not pitches.empty else pd.DataFrame(columns=pitch_columns)
edited_pitches = st.data_editor(
    pitch_rows,
    key=pitch_editor_key,
    hide_index=True,
    num_rows="dynamic",
    height=280,
    disabled=["id", "updated_at"],
    column_order=["pitch_number", "pitch_name", "pitch_type", "status", "model_variants", "sequence"],
    column_config={
        "id": None,
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
    },
)
if pitch_actions.save_and_refresh:
    if (st.session_state.get(pitch_editor_key, {}) or {}).get("deleted_rows"):
        st.warning("Selected pitches are not deleted during Save. A confirmed bulk-delete workflow will be added after work reassignment rules are finalized.")
    else:
        try:
            errors = required_field_errors(edited_pitches, {"pitch_number": "Pitch address", "status": "Status"})
            if errors:
                raise ValueError(" ".join(errors))
            count = replace_yamazumi_pitches(project_id, area_id, edited_pitches)
            record_audit_event(project_id, "Yamazumi pitches", "Save & refresh", count, st.session_state.get("current_editor", ""))
            request_table_editor_reset(pitch_editor_key)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

st.divider()
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
active_pitches = pitches.loc[pitches["status"] == "Active"].copy() if not pitches.empty else pitches
pitch_label_by_id = dict(zip(active_pitches["id"].astype(str), active_pitches["pitch_number"].astype(str))) if not active_pitches.empty else {}
element_columns = [
    "id", "pitch_id", "model_variant", "work_type", "description", "time_s", "work_region",
    "flags", "sequence", "source", "process_element_id", "process_sync_status", "updated_at",
]
element_rows = elements.reindex(columns=element_columns).copy() if not elements.empty else pd.DataFrame(columns=element_columns)
element_rows["pitch"] = element_rows["pitch_id"].apply(
    lambda value: pitch_label_by_id.get(str(value), "Unassigned") if value is not None and not pd.isna(value) else "Unassigned"
)
visible_elements = filter_table(
    element_rows,
    key="yamazumi_element_filters",
    dropdown_columns=["pitch", "model_variant", "work_type", "work_region", "process_sync_status"],
    search_columns=["description", "pitch", "model_variant", "work_region", "flags"],
    reset_widget_keys=[element_editor_key],
)
pitch_options = ["Unassigned", *pitch_label_by_id.values()]
variant_options_by_pitch_label = {
    pitch_label_by_id[pitch_id]: pitch_variants_by_id.get(pitch_id, ["Base"])
    for pitch_id in pitch_label_by_id
}
edited_elements = st.data_editor(
    visible_elements,
    key=element_editor_key,
    hide_index=True,
    num_rows="dynamic",
    height=420,
    disabled=["id", "source", "process_element_id", "process_sync_status", "updated_at"],
    column_order=["pitch", "model_variant", "work_type", "description", "time_s", "work_region", "flags", "sequence", "process_sync_status"],
    column_config={
        "id": None,
        "pitch_id": None,
        "pitch": st.column_config.SelectboxColumn("Pitch", options=pitch_options, required=True, default="Unassigned"),
        "model_variant": st.column_config.SelectboxColumn(
            "Model variant",
            options=variant_options,
            required=True,
            default="Base",
            help="Base applies to all models. Other choices show Feature = Allowed choice from Model Definitions; imported legacy values remain available.",
        ),
        "work_type": st.column_config.SelectboxColumn("Work type", options=WORK_TYPES, required=True, default="Cycle"),
        "description": st.column_config.TextColumn("Work description", required=True, width="large"),
        "time_s": st.column_config.NumberColumn("Time (s)", min_value=0.0, step=0.1, format="%.1f", required=True),
        "work_region": st.column_config.SelectboxColumn(
            "Work region", options=work_region_options, required=True, default="None"
        ),
        "flags": st.column_config.MultiselectColumn("Flags", options=["CTQ", "Safety"]),
        "sequence": st.column_config.NumberColumn("Order", min_value=1, step=1, format="%d"),
        "source": None,
        "process_element_id": None,
        "process_sync_status": st.column_config.TextColumn("Process Plan sync"),
        "updated_at": None,
    },
)
if element_actions.save_and_refresh:
    if (st.session_state.get(element_editor_key, {}) or {}).get("deleted_rows"):
        st.warning("Selected work elements are not deleted during Save. Use the forthcoming confirmed bulk-delete action.")
    else:
        try:
            errors = required_field_errors(edited_elements, {"model_variant": "Model variant", "description": "Work description", "work_region": "Work region"})
            if errors:
                raise ValueError(" ".join(errors))
            pitch_id_by_label = {label: pitch_id for pitch_id, label in pitch_label_by_id.items()}
            to_save = merge_filtered_edits(element_rows, visible_elements, edited_elements)
            to_save["pitch_id"] = to_save["pitch"].map(pitch_id_by_label)
            invalid_variant_rows = to_save.apply(
                lambda row: (
                    row["pitch"] != "Unassigned"
                    and row["model_variant"] not in variant_options_by_pitch_label.get(row["pitch"], [])
                ),
                axis=1,
            )
            if invalid_variant_rows.any():
                raise ValueError("A work element uses a model variant that is not enabled for its selected pitch.")
            to_save = to_save.drop(columns=["pitch"], errors="ignore")
            count = replace_yamazumi_elements(project_id, area_id, to_save)
            record_audit_event(project_id, "Yamazumi elements", "Save & refresh", count, st.session_state.get("current_editor", ""))
            request_table_editor_reset(element_editor_key)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

pending_review = int((elements.get("process_sync_status", pd.Series(dtype=str)) == "Needs IE review").sum())
st.divider()
st.subheader("IE reconciliation to Process Plan")
st.caption(
    "Accepting a row updates only its Process Plan workstation, cycle time, and model applicability. Existing IE-authored tooling, torque, quality, ergonomic, geometry, part, and location details are preserved."
)
review_rows = elements.loc[elements.get("process_sync_status", pd.Series(index=elements.index, dtype=str)) == "Needs IE review"].copy()
if review_rows.empty:
    st.success("Yamazumi and Process Plan are reconciled for this area.", icon=":material/check_circle:")
else:
    review_columns = ["id", "pitch_number", "model_variant", "description", "time_s", "flags", "updated_at"]
    review_source = review_rows.reindex(columns=review_columns)
    review_editor_key = f"yamazumi_reconciliation_{project_id}_{area_id}"
    st.data_editor(
        review_source,
        key=review_editor_key,
        hide_index=True,
        num_rows="delete",
        disabled=["id", "pitch_number", "model_variant", "description", "time_s", "flags", "updated_at"],
        height=min(420, 70 + len(review_source) * 35),
        column_order=["pitch_number", "model_variant", "description", "time_s", "flags", "updated_at"],
        column_config={
            "id": None,
            "pitch_number": st.column_config.TextColumn("New workstation"),
            "model_variant": st.column_config.TextColumn("Model variant"),
            "description": st.column_config.TextColumn("Work description", width="large"),
            "time_s": st.column_config.NumberColumn("New time (s)", format="%.1f"),
            "flags": st.column_config.ListColumn("Flags"),
            "updated_at": st.column_config.DatetimeColumn("Changed", format="MMM DD, YYYY HH:mm"),
        },
    )
    selected_review = native_selected_rows(review_source, editor_key=review_editor_key)
    if st.button(
        f"Accept selected into Process Plan ({len(selected_review)})",
        type="primary",
        icon=":material/sync:",
        disabled=selected_review.empty,
    ):
        count = reconcile_yamazumi_to_process(
            project_id, scenario_id, selected_review["id"].astype(str).tolist()
        )
        record_audit_event(
            project_id, "Yamazumi", "Accept into Process Plan", count,
            st.session_state.get("current_editor", ""),
        )
        st.session_state.pop(review_editor_key, None)
        st.toast(f"Reconciled {count} work elements to the Process Plan", icon=":material/check_circle:")
        st.rerun()
    st.info(f"{pending_review} Yamazumi work element(s) need IE review.")
