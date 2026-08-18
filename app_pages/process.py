import pandas as pd
import streamlit as st

from utils.store import (
    assembly_sections,
    audit_history,
    delete_process_part_group,
    fishbone_part_assignments,
    get_planning_scenario,
    parse_yamazumi_model_variants,
    process_element_id_for_yamazumi,
    process_part_groups,
    project_models,
    project_table,
    reconcile_yamazumi_to_process,
    record_audit_event,
    replace_work_elements,
    save_process_part_group,
    update_process_step_details,
    yamazumi_elements_for_section,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
    split_filter_values,
)
from utils.table_ui import (
    dataframe_to_excel,
    editable_table_header,
    native_selected_rows,
    required_field_errors,
    standard_details_column_config,
    table_has_unsaved_changes,
)


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
st.title("Process at a Glance")
st.caption(
    "Pair fishbone parts to Yamazumi work elements section by section, then complete the ordered "
    "Process at a Glance by pitch. A purchased assembly is handled as one catalog part."
)
if not project_id or not scenario_id:
    st.stop()

scenario = get_planning_scenario(project_id, scenario_id)
if not scenario:
    st.error("The active planning scenario no longer exists.")
    st.stop()
st.caption(f"Rev {scenario['revision_label']} · {scenario['name']} · {scenario['status']}")

sections = assembly_sections(project_id)
if not sections.empty:
    sections = sections.loc[sections["active"].fillna(1).astype(bool)].copy()
section_ids = sections["id"].astype(str).tolist() if not sections.empty else []
section_labels = {
    str(row["id"]): f"{row['name']} ({row['section_type']})"
    for _, row in sections.iterrows()
}

st.subheader("Pair work and material")
st.caption(
    "The selected fishbone section controls both lists. Use **Choose one** for alternatives such "
    "as black or silver versions of the same panel."
)
if not section_ids:
    st.info("Create and populate the assembly fishbone before pairing parts to process work.")
else:
    section_id = st.selectbox(
        "Fishbone section",
        section_ids,
        format_func=lambda value: section_labels.get(value, value),
        key=f"process_pairing_section_{scenario_id}",
    )
    pairing_search = st.text_input(
        "Filter work elements or parts",
        placeholder="Search descriptions, pitches, part numbers, or uses",
        key=f"process_pairing_search_{scenario_id}_{section_id}",
    ).strip().casefold()

    yamazumi_rows = yamazumi_elements_for_section(project_id, scenario_id, section_id)
    if not yamazumi_rows.empty:
        yamazumi_rows["model_variants"] = yamazumi_rows.apply(
            lambda row: parse_yamazumi_model_variants(
                row.get("model_variants"), str(row.get("model_variant") or "Base")
            ),
            axis=1,
        )
    available_parts = fishbone_part_assignments(project_id)
    if not available_parts.empty:
        available_parts = available_parts.loc[
            available_parts["section_id"].astype(str) == section_id
        ].copy()

    if pairing_search and not yamazumi_rows.empty:
        yam_mask = pd.Series(False, index=yamazumi_rows.index)
        for column in ["description", "area_name", "pitch_number", "pitch_name", "model_variants"]:
            yam_mask |= yamazumi_rows[column].fillna("").astype(str).str.casefold().str.contains(
                pairing_search, regex=False
            )
        yamazumi_rows = yamazumi_rows.loc[yam_mask].copy()
    if pairing_search and not available_parts.empty:
        part_mask = pd.Series(False, index=available_parts.index)
        for column in ["part_number", "description", "use_description", "model_applicability"]:
            part_mask |= available_parts[column].fillna("").astype(str).str.casefold().str.contains(
                pairing_search, regex=False
            )
        available_parts = available_parts.loc[part_mask].copy()

    work_column, part_column = st.columns(2, vertical_alignment="top")
    with work_column.container(border=True, height="stretch"):
        st.markdown("#### Yamazumi work elements")
        st.caption("Select the work element that consumes the parts.")
        if yamazumi_rows.empty:
            st.info("No Yamazumi work is linked to this fishbone section.")
            selected_yamazumi = yamazumi_rows
        else:
            work_event = st.dataframe(
                yamazumi_rows,
                key=f"process_yamazumi_source_{scenario_id}_{section_id}",
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                column_order=[
                    "pitch_number", "description", "time_s", "model_variants",
                    "material_group_count", "process_sync_status",
                ],
                column_config={
                    "pitch_number": st.column_config.TextColumn("Pitch", pinned=True),
                    "description": st.column_config.TextColumn("Work element", width="large"),
                    "time_s": st.column_config.NumberColumn("Time (s)", format="%.1f"),
                    "model_variants": st.column_config.ListColumn("Models"),
                    "material_group_count": st.column_config.NumberColumn("Part groups"),
                    "process_sync_status": "Plan status",
                },
            )
            selected_yamazumi = yamazumi_rows.iloc[work_event.selection.rows]

    with part_column.container(border=True, height="stretch"):
        st.markdown("#### Available fishbone parts")
        st.caption("Select one or more catalog parts from this section.")
        if available_parts.empty:
            st.info("No catalog parts are placed in this fishbone section.")
            selected_parts = available_parts
        else:
            part_event = st.dataframe(
                available_parts,
                key=f"process_part_source_{scenario_id}_{section_id}",
                hide_index=True,
                on_select="rerun",
                selection_mode="multi-row",
                column_order=[
                    "part_number", "description", "quantity", "use_description",
                    "model_applicability",
                ],
                column_config={
                    "part_number": st.column_config.TextColumn("Part number", pinned=True),
                    "description": st.column_config.TextColumn("Description", width="large"),
                    "quantity": st.column_config.NumberColumn("Fishbone qty."),
                    "use_description": st.column_config.TextColumn("Use", width="medium"),
                    "model_applicability": "Models",
                },
            )
            selected_parts = available_parts.iloc[part_event.selection.rows]

    selected_yamazumi_id = (
        str(selected_yamazumi.iloc[0]["id"]) if len(selected_yamazumi) == 1 else None
    )
    selected_process_id = (
        process_element_id_for_yamazumi(project_id, scenario_id, selected_yamazumi_id)
        if selected_yamazumi_id else None
    )

    if selected_yamazumi_id:
        selected_description = str(selected_yamazumi.iloc[0]["description"])
        pair_controls = st.container(border=True)
        pair_controls.markdown(f"**Selected work:** {selected_description}")
        with pair_controls.form(
            f"pair_parts_{scenario_id}_{section_id}_{selected_yamazumi_id}", border=False
        ):
            form_row = st.container(horizontal=True, vertical_alignment="bottom")
            group_name = form_row.text_input(
                "Part requirement",
                placeholder="Example: Control panel color",
            )
            selection_rule = form_row.selectbox(
                "Selection rule", ["Use all", "Choose one", "Optional"]
            )
            quantity = form_row.number_input("Quantity", min_value=0.01, value=1.0, step=1.0)
            notes = st.text_input(
                "Pairing notes",
                placeholder="Model choice, installation intent, or other IE guidance",
            )
            pair_parts = st.form_submit_button(
                f"Pair selected parts ({len(selected_parts)})",
                type="primary",
                icon=":material/link:",
                disabled=selected_parts.empty,
            )
        add_without_parts = st.button(
            "Add selected work to Process at a Glance without parts",
            icon=":material/playlist_add:",
            key=f"add_work_only_{scenario_id}_{selected_yamazumi_id}",
        )
        if pair_parts:
            try:
                reconcile_yamazumi_to_process(
                    project_id, scenario_id, [selected_yamazumi_id]
                )
                selected_process_id = process_element_id_for_yamazumi(
                    project_id, scenario_id, selected_yamazumi_id
                )
                if not selected_process_id:
                    raise ValueError(
                        "The work element could not be added to Process at a Glance."
                    )
                save_process_part_group(
                    project_id,
                    scenario_id,
                    selected_process_id,
                    section_id,
                    None,
                    group_name,
                    selection_rule,
                    quantity,
                    selected_parts["part_id"].astype(str).tolist(),
                    notes,
                )
                record_audit_event(
                    project_id,
                    "Process part pairings",
                    "Pair parts",
                    len(selected_parts),
                    st.session_state.get("current_editor", ""),
                    {
                        "scenario_id": scenario_id,
                        "work_element": selected_description,
                        "requirement": group_name,
                        "section": section_labels.get(section_id, section_id),
                    },
                )
                st.toast("Parts paired to the process work element", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if add_without_parts:
            reconcile_yamazumi_to_process(project_id, scenario_id, [selected_yamazumi_id])
            record_audit_event(
                project_id,
                "Process plan",
                "Add Yamazumi work",
                1,
                st.session_state.get("current_editor", ""),
                {"scenario_id": scenario_id, "work_element": selected_description},
            )
            st.toast(
                "Work element added to Process at a Glance",
                icon=":material/check_circle:",
            )
            st.rerun()

        if selected_process_id:
            saved_groups = process_part_groups(
                project_id, scenario_id, selected_process_id
            )
            if saved_groups:
                st.markdown("##### Existing part pairings")
                for group in saved_groups:
                    labels = ", ".join(
                        str(option["part_number"]) for option in group["options"]
                    )
                    pairing_row = st.container(
                        horizontal=True, vertical_alignment="center", border=True
                    )
                    pairing_row.write(
                        f"**{group['name']}** · {group['selection_rule']} · "
                        f"Qty {float(group['quantity']):g} · {labels}"
                    )
                    if pairing_row.button(
                        "Remove",
                        icon=":material/link_off:",
                        key=f"remove_process_pairing_{scenario_id}_{group['id']}",
                    ):
                        delete_process_part_group(project_id, scenario_id, str(group["id"]))
                        record_audit_event(
                            project_id,
                            "Process part pairings",
                            "Remove pairing",
                            1,
                            st.session_state.get("current_editor", ""),
                            {"scenario_id": scenario_id, "requirement": group["name"]},
                        )
                        st.rerun()
    else:
        st.caption("Select one Yamazumi work element to pair parts or add it to the plan.")

st.divider()
process_editor_key = f"process_editor_{scenario_id}"
apply_pending_table_editor_reset(process_editor_key)
elements = project_table("work_elements", project_id, "sequence", scenario_id=scenario_id)
models = project_models(project_id)
model_labels = {
    str(row["model_number"]): (str(row["display_name"]).strip() or "Familiar name not defined")
    for _, row in models.iterrows()
}
model_numbers_by_label = {label: number for number, label in model_labels.items()}
columns = [
    "id", "sequence", "station", "operation", "description", "cycle_time_s",
    "assigned_parts", "part_number", "output_assembly_number", "output_assembly_name",
    "tool", "torque", "quality_requirement", "ergo_requirement", "location",
    "conveyor_height_mm", "platform_height_mm", "pit_depth_mm",
    "model_applicability", "status", "details", "delete_step",
]
compact_columns = [
    "sequence",
    "station",
    "operation",
    "cycle_time_s",
    "model_applicability",
    "status",
    "details",
    "delete_step",
]
if elements.empty:
    elements = pd.DataFrame(
        {
            "id": pd.Series(dtype="string"),
            "sequence": pd.Series(dtype="int64"),
            "station": pd.Series(dtype="string"),
            "operation": pd.Series(dtype="string"),
            "description": pd.Series(dtype="string"),
            "cycle_time_s": pd.Series(dtype="float64"),
            "assigned_parts": pd.Series(dtype="string"),
            "part_number": pd.Series(dtype="string"),
            "output_assembly_number": pd.Series(dtype="string"),
            "output_assembly_name": pd.Series(dtype="string"),
            "tool": pd.Series(dtype="string"),
            "torque": pd.Series(dtype="string"),
            "quality_requirement": pd.Series(dtype="string"),
            "ergo_requirement": pd.Series(dtype="string"),
            "location": pd.Series(dtype="string"),
            "conveyor_height_mm": pd.Series(dtype="float64"),
            "platform_height_mm": pd.Series(dtype="float64"),
            "pit_depth_mm": pd.Series(dtype="float64"),
            "model_applicability": pd.Series(dtype="object"),
            "status": pd.Series(dtype="string"),
            "details": pd.Series(dtype="string"),
            "delete_step": pd.Series(dtype="string"),
        }
    )
else:
    elements = elements.copy()
    pairing_summary: dict[str, list[str]] = {}
    for group in process_part_groups(project_id, scenario_id):
        option_numbers = [str(option["part_number"]) for option in group["options"]]
        suffix = " / ".join(option_numbers) if group["selection_rule"] == "Choose one" else ", ".join(option_numbers)
        pairing_summary.setdefault(str(group["work_element_id"]), []).append(
            f"{group['name']}: {suffix}"
        )
    elements["assigned_parts"] = elements["id"].astype(str).map(
        lambda element_id: " | ".join(pairing_summary.get(element_id, []))
    )
    elements["details"] = ":material/info: Details"
    elements["delete_step"] = ":material/delete: Delete"
    elements = elements.reindex(columns=columns)

elements["model_applicability"] = elements["model_applicability"].apply(
    lambda value: [
        "All models" if model.casefold() in {"all", "all models"} else model_labels.get(model, model)
        for model in (split_filter_values(value) or ["All"])
    ]
)

header_actions = editable_table_header(
    "Process at a Glance by pitch",
    editor_key=process_editor_key,
    key_prefix=f"process_plan_{scenario_id}",
    native_row_selection=True,
)
st.caption(
    "Enter an output assembly number on the exact step where a new made assembly becomes complete. "
    "That milestone belongs to this scenario's Process at a Glance."
)

visible_elements = filter_table(
    elements,
    key=f"process_filters_{scenario_id}",
    dropdown_columns=["station", "status", "model_applicability"],
    search_columns=[
        "operation", "description", "station", "assigned_parts", "output_assembly_number",
        "output_assembly_name", "tool", "quality_requirement", "ergo_requirement", "location",
    ],
    reset_widget_keys=[process_editor_key],
    multi_value_columns=["model_applicability"],
    universal_values={"model_applicability": ["All", "All models", ""]},
)


def open_process_details() -> None:
    blocked_key = f"process_details_blocked_{scenario_id}"
    if table_has_unsaved_changes(process_editor_key, native_row_selection=True):
        st.session_state[blocked_key] = (
            "Save or undo table edits before opening step details."
        )
        return
    if not native_selected_rows(visible_elements, editor_key=process_editor_key).empty:
        st.session_state[blocked_key] = (
            "Clear selected rows before opening step details."
        )
        return
    click = st.session_state.get(f"process_details_action_{scenario_id}") or {}
    position = click.get("row")
    if position is not None and 0 <= int(position) < len(visible_elements):
        st.session_state.pop(blocked_key, None)
        st.session_state[f"selected_process_step_{scenario_id}"] = str(
            visible_elements.iloc[int(position)]["id"]
        )


def request_individual_process_delete() -> None:
    click = st.session_state.get(f"process_delete_action_{scenario_id}") or {}
    position = click.get("row")
    if position is not None and 0 <= int(position) < len(visible_elements):
        element_id = str(visible_elements.iloc[int(position)]["id"] or "").strip()
        if element_id:
            st.session_state.pop(f"selected_process_step_{scenario_id}", None)
            st.session_state[f"process_pending_delete_{scenario_id}"] = [element_id]


edited = st.data_editor(
    visible_elements,
    key=process_editor_key,
    hide_index=True,
    num_rows="dynamic",
    height=470,
    disabled=["id"],
    column_order=compact_columns,
    column_config={
        "id": None,
        "part_number": None,
        "details": standard_details_column_config(
            on_click=open_process_details, key=f"process_details_action_{scenario_id}"
        ),
        "delete_step": st.column_config.ButtonColumn(
            "Delete",
            type="tertiary",
            on_click=request_individual_process_delete,
            key=f"process_delete_action_{scenario_id}",
        ),
        "sequence": st.column_config.NumberColumn("Seq.", min_value=0, step=10, pinned=True),
        "station": st.column_config.TextColumn("Pitch", pinned=True),
        "operation": st.column_config.TextColumn("Operation", required=True, pinned=True),
        "cycle_time_s": st.column_config.NumberColumn("Time (s)", min_value=0.0, step=0.1, format="%.1f"),
        "model_applicability": st.column_config.MultiselectColumn(
            "Models", options=["All models", *model_labels.values()]
        ),
        "status": st.column_config.SelectboxColumn(
            "Status", options=["Draft", "In review", "Released"]
        ),
    },
)

details_blocked = st.session_state.pop(f"process_details_blocked_{scenario_id}", None)
if details_blocked:
    st.warning(details_blocked)

st.download_button(
    "Export filtered Process at a Glance",
    data=dataframe_to_excel(
        visible_elements.drop(columns=["id", "details", "delete_step"], errors="ignore"),
        "Process plan",
    ),
    file_name="process_plan_filtered.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    icon=":material/download:",
)

selected = native_selected_rows(visible_elements, editor_key=process_editor_key)
bulk = st.container(horizontal=True, vertical_alignment="bottom")
bulk_station = bulk.text_input("Pitch for selected", key=f"process_bulk_pitch_{scenario_id}")
bulk_status = bulk.selectbox(
    "Status for selected",
    [None, "Draft", "In review", "Released"],
    format_func=lambda value: "No change" if value is None else value,
    key=f"process_bulk_status_{scenario_id}",
)
apply_bulk = bulk.button(
    f"Apply to selected ({len(selected)})",
    type="primary",
    icon=":material/checklist:",
    disabled=selected.empty,
)
request_bulk_delete = bulk.button(
    f"Delete selected ({len(selected)})",
    icon=":material/delete:",
    disabled=selected.empty,
)

if apply_bulk:
    if table_has_unsaved_changes(process_editor_key, native_row_selection=True):
        st.warning("Save or undo other edits before applying a bulk change.")
    elif not bulk_station.strip() and bulk_status is None:
        st.warning("Enter a pitch or choose a status to apply.")
    else:
        updated = elements.copy()
        selected_ids = set(selected["id"].astype(str))
        mask = updated["id"].astype(str).isin(selected_ids)
        if bulk_station.strip():
            updated.loc[mask, "station"] = bulk_station.strip()
        if bulk_status:
            updated.loc[mask, "status"] = bulk_status
        updated["model_applicability"] = updated["model_applicability"].apply(
            lambda assigned: ", ".join(
                "All" if label == "All models" else model_numbers_by_label.get(label, label)
                for label in (assigned or ["All models"])
            )
        )
        replace_work_elements(project_id, scenario_id, updated)
        record_audit_event(
            project_id,
            "Process plan",
            "Bulk edit",
            len(selected_ids),
            st.session_state.get("current_editor", ""),
            {"scenario_id": scenario_id, "pitch": bulk_station, "status": bulk_status},
        )
        request_table_editor_reset(process_editor_key)
        st.rerun()

if request_bulk_delete:
    st.session_state.pop(f"selected_process_step_{scenario_id}", None)
    st.session_state[f"process_pending_delete_{scenario_id}"] = selected["id"].astype(str).tolist()


@st.dialog("Delete Process at a Glance steps?")
def confirm_process_delete() -> None:
    pending_key = f"process_pending_delete_{scenario_id}"
    pending_ids = st.session_state.get(pending_key, [])
    st.warning(
        f"Delete {len(pending_ids)} process step(s)? Their part pairings will also be deleted."
    )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_process_delete_{scenario_id}"):
        st.session_state.pop(pending_key, None)
        st.rerun()
    if actions.button(
        "Delete steps", type="primary", icon=":material/delete:",
        key=f"confirm_process_delete_{scenario_id}",
    ):
        retained = elements.loc[~elements["id"].astype(str).isin(set(pending_ids))].copy()
        retained["model_applicability"] = retained["model_applicability"].apply(
            lambda assigned: ", ".join(
                "All" if label == "All models" else model_numbers_by_label.get(label, label)
                for label in (assigned or ["All models"])
            )
        )
        replace_work_elements(project_id, scenario_id, retained)
        record_audit_event(
            project_id,
            "Process plan",
            "Bulk delete" if len(pending_ids) > 1 else "Delete",
            len(pending_ids),
            st.session_state.get("current_editor", ""),
            {"scenario_id": scenario_id},
        )
        st.session_state.pop(pending_key, None)
        request_table_editor_reset(process_editor_key)
        st.rerun()


if st.session_state.get(f"process_pending_delete_{scenario_id}"):
    confirm_process_delete()

if header_actions.undo:
    request_table_editor_reset(process_editor_key)
    st.rerun()

if header_actions.save_and_refresh:
    try:
        if not selected.empty:
            raise ValueError("Clear selected rows before saving table edits.")
        errors = required_field_errors(edited, {"operation": "Operation"})
        if errors:
            raise ValueError(" ".join(errors))
        combined_elements = merge_filtered_edits(elements, visible_elements, edited)
        combined_elements["model_applicability"] = combined_elements["model_applicability"].apply(
            lambda assigned: ", ".join(
                "All" if label == "All models" else model_numbers_by_label.get(label, label)
                for label in (assigned or ["All models"])
            )
        )
        replace_work_elements(project_id, scenario_id, combined_elements)
        record_audit_event(
            project_id,
            "Process plan",
            "Save & refresh",
            len(combined_elements),
            st.session_state.get("current_editor", ""),
            {"scenario_id": scenario_id},
        )
        request_table_editor_reset(process_editor_key)
        st.toast("Process at a Glance saved", icon=":material/check_circle:")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

def close_process_details() -> None:
    st.session_state.pop(f"selected_process_step_{scenario_id}", None)


@st.dialog(
    "Edit process-step details",
    width="large",
    dismissible=False,
    icon=":material/edit_note:",
)
def edit_process_step_details(element_id: str) -> None:
    selected_step = elements.loc[elements["id"].astype(str) == str(element_id)]
    if selected_step.empty:
        st.error("The selected process step no longer exists.")
        if st.button("Close", icon=":material/close:"):
            close_process_details()
            st.rerun()
        return

    step = selected_step.iloc[0]
    widget_prefix = f"process_details_{scenario_id}_{element_id}"

    def text_value(field: str) -> str:
        value = step.get(field)
        return "" if value is None or pd.isna(value) else str(value)

    def number_value(field: str) -> float | None:
        value = step.get(field)
        return None if value is None or pd.isna(value) else float(value)

    st.subheader(str(step.get("operation") or "Unnamed process step"))
    st.caption(
        f"Pitch: {step.get('station') or 'Unassigned'} · "
        f"Time: {float(step.get('cycle_time_s') or 0):.1f} s"
    )

    (
        step_tab,
        tool_tab,
        requirements_tab,
        location_tab,
        parts_tab,
        future_tab,
    ) = st.tabs(
        [
            "Step details",
            "Tool and torque",
            "Quality and ergonomics",
            "Location and heights",
            "Parts and models",
            "Future equipment and sub-touches",
        ]
    )

    with step_tab:
        description = st.text_area(
            "Step description",
            value=text_value("description"),
            key=f"{widget_prefix}_description",
        )
        output_assembly_number = st.text_input(
            "New assembly number",
            value=text_value("output_assembly_number"),
            help="Leave blank unless this exact step completes a new made assembly.",
            key=f"{widget_prefix}_output_assembly_number",
        )
        output_assembly_name = st.text_input(
            "New assembly name",
            value=text_value("output_assembly_name"),
            key=f"{widget_prefix}_output_assembly_name",
        )

    with tool_tab:
        tool = st.text_area(
            "Tool requirement",
            value=text_value("tool"),
            key=f"{widget_prefix}_tool",
        )
        torque = st.text_area(
            "Torque requirement",
            value=text_value("torque"),
            key=f"{widget_prefix}_torque",
        )

    with requirements_tab:
        quality_requirement = st.text_area(
            "Quality requirement",
            value=text_value("quality_requirement"),
            key=f"{widget_prefix}_quality_requirement",
        )
        ergo_requirement = st.text_area(
            "Ergonomic requirement",
            value=text_value("ergo_requirement"),
            key=f"{widget_prefix}_ergo_requirement",
        )

    with location_tab:
        location = st.text_input(
            "Location",
            value=text_value("location"),
            key=f"{widget_prefix}_location",
        )
        dimension_columns = st.columns(3)
        conveyor_height_mm = dimension_columns[0].number_input(
            "Conveyor height (mm)",
            min_value=0.0,
            value=number_value("conveyor_height_mm"),
            key=f"{widget_prefix}_conveyor_height_mm",
        )
        platform_height_mm = dimension_columns[1].number_input(
            "Platform height (mm)",
            min_value=0.0,
            value=number_value("platform_height_mm"),
            key=f"{widget_prefix}_platform_height_mm",
        )
        pit_depth_mm = dimension_columns[2].number_input(
            "Pit depth (mm)",
            min_value=0.0,
            value=number_value("pit_depth_mm"),
            key=f"{widget_prefix}_pit_depth_mm",
        )

    with parts_tab:
        st.markdown("**Paired fishbone parts**")
        st.write(step.get("assigned_parts") or "No fishbone parts are paired to this step.")
        st.caption("Part pairings are managed in the pairing workspace above the table.")
        st.markdown("**Model applicability**")
        assigned_models = step.get("model_applicability") or ["All models"]
        if not isinstance(assigned_models, list):
            assigned_models = [str(assigned_models)]
        st.write(", ".join(str(model) for model in assigned_models))
        st.caption("Edit model applicability directly in the compact table.")

    with future_tab:
        st.info("Coming in a future phase.")

    actions = st.container(horizontal=True, horizontal_alignment="right")
    if actions.button(
        "Cancel",
        icon=":material/close:",
        key=f"{widget_prefix}_cancel",
    ):
        close_process_details()
        st.rerun()
    if actions.button(
        "Save details",
        type="primary",
        icon=":material/save:",
        key=f"{widget_prefix}_save",
    ):
        try:
            updated_at = update_process_step_details(
                project_id,
                scenario_id,
                element_id,
                {
                    "description": description,
                    "output_assembly_number": output_assembly_number,
                    "output_assembly_name": output_assembly_name,
                    "tool": tool,
                    "torque": torque,
                    "quality_requirement": quality_requirement,
                    "ergo_requirement": ergo_requirement,
                    "location": location,
                    "conveyor_height_mm": conveyor_height_mm,
                    "platform_height_mm": platform_height_mm,
                    "pit_depth_mm": pit_depth_mm,
                },
            )
            record_audit_event(
                project_id,
                "Process plan",
                "Edit details",
                1,
                st.session_state.get("current_editor", ""),
                {
                    "scenario_id": scenario_id,
                    "work_element_id": element_id,
                    "updated_at": updated_at,
                },
            )
            close_process_details()
            request_table_editor_reset(process_editor_key)
            st.toast("Process-step details saved", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


selected_step_id = st.session_state.get(f"selected_process_step_{scenario_id}")
if selected_step_id and not st.session_state.get(f"process_pending_delete_{scenario_id}"):
    edit_process_step_details(str(selected_step_id))

if not edited.empty:
    clean_times = pd.to_numeric(edited["cycle_time_s"], errors="coerce").fillna(0)
    total = float(clean_times.sum())
    stations = edited.assign(cycle_time_s=clean_times).groupby(
        "station", dropna=False
    )["cycle_time_s"].sum().reset_index()
    metric_cols = st.columns(3)
    metric_cols[0].metric("Total work content", f"{total:.1f} s", border=True)
    metric_cols[1].metric("Target takt", f"{float(scenario['takt_time_s']):.1f} s", border=True)
    metric_cols[2].metric("Pitches represented", len(stations), border=True)
    st.subheader("Draft Yamazumi by pitch")
    st.bar_chart(
        stations, x="station", y="cycle_time_s", x_label="Pitch", y_label="Cycle time (s)"
    )

with st.expander("Process at a Glance history", icon=":material/history:"):
    history = audit_history(project_id, "Process plan", limit=50)
    pairing_history = audit_history(project_id, "Process part pairings", limit=50)
    combined_history = pd.concat([history, pairing_history], ignore_index=True)
    if combined_history.empty:
        st.caption("No standardized Process at a Glance changes have been recorded yet.")
    else:
        display_history = combined_history.sort_values("created_at", ascending=False).drop(
            columns=["details"], errors="ignore"
        )
        if "table_name" in display_history.columns:
            display_history["table_name"] = display_history["table_name"].replace(
                {"Process plan": "Process at a Glance"}
            )
        st.dataframe(
            display_history,
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
