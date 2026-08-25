import pandas as pd
#test
import streamlit as st

from utils.store import (
    assign_parts_to_section,
    assembly_sections,
    audit_history,
    create_part_and_assign_to_section,
    delete_process_part_groups,
    fishbone_part_assignments,
    get_planning_scenario,
    move_fishbone_part_assignment,
    parse_yamazumi_model_variants,
    process_element_id_for_yamazumi,
    process_part_groups,
    process_section_for_step,
    project_models,
    project_table,
    reconcile_yamazumi_to_process,
    record_audit_event,
    replace_work_elements,
    save_process_part_group,
    search_parts_and_fishbone,
    update_process_step_details,
    yamazumi_context_for_process,
    yamazumi_elements_for_section,
)
from utils.scope_ui import page_title_with_scope
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
    split_filter_values,
)
from utils.table_ui import (
    dataframe_to_excel,
    editable_table_footer,
    editable_table_heading,
    native_selected_rows,
    required_field_errors,
    selectable_dataframe,
    selected_rows_action_bar,
    standard_details_column_config,
    table_has_unsaved_changes,
)
project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
process_editor_key = f"process_editor_{scenario_id}"
missing_part_dialog_key = f"process_missing_part_dialog_{scenario_id}"
pairing_delete_key = f"process_pairings_pending_remove_{scenario_id}"
detail_pairing_delete_key = f"process_detail_pairing_pending_remove_{scenario_id}"
detail_restore_key = f"process_detail_restore_{scenario_id}"
if not project_id or not scenario_id:
    st.stop()

scenario = get_planning_scenario(project_id, scenario_id)
if not scenario:
    st.error("The active planning scenario no longer exists.")
    st.stop()
page_title_with_scope(
    "Process at a Glance", scope="scenario", scenario_name=scenario["name"]
)
st.caption(
    "Pair fishbone parts to Yamazumi work elements section by section, then complete the ordered "
    "Process at a Glance by pitch. A purchased assembly is handled as one catalog part."
)
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
    section_has_yamazumi_work = not yamazumi_rows.empty
    if not yamazumi_rows.empty:
        yamazumi_rows["model_variants"] = yamazumi_rows.apply(
            lambda row: parse_yamazumi_model_variants(
                row.get("model_variants"), str(row.get("model_variant") or "Base")
            ),
            axis=1,
        )
        reflected_in_process = (
            yamazumi_rows["process_element_id"].fillna("").astype(str).str.strip().ne("")
            & yamazumi_rows["process_sync_status"].fillna("").astype(str).eq("Synced")
        )
        yamazumi_rows = yamazumi_rows.loc[~reflected_in_process].copy()
    section_has_available_yamazumi_work = not yamazumi_rows.empty

    scenario_part_groups = process_part_groups(
        project_id, scenario_id, active_only=True
    )
    paired_part_ids = {
        str(part_id)
        for group in scenario_part_groups
        if str(group.get("section_id") or "") == str(section_id)
        for part_id in group.get("part_ids", [])
    }
    available_parts = fishbone_part_assignments(project_id, scenario_id)
    if not available_parts.empty:
        available_parts = available_parts.loc[
            available_parts["section_id"].astype(str) == section_id
        ].copy()
    section_has_fishbone_parts = not available_parts.empty
    if paired_part_ids and not available_parts.empty:
        available_parts = available_parts.loc[
            ~available_parts["part_id"].astype(str).isin(paired_part_ids)
        ].copy()
    section_has_available_fishbone_parts = not available_parts.empty

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
            if pairing_search and section_has_available_yamazumi_work:
                st.info("No available Yamazumi work matches this filter.")
            elif section_has_yamazumi_work:
                st.info("All synced Yamazumi work in this section is already reflected below.")
            else:
                st.info("No Yamazumi work is linked to this fishbone section.")
            selected_yamazumi = yamazumi_rows
        else:
            work_event = selectable_dataframe(
                yamazumi_rows,
                key=f"process_yamazumi_source_{scenario_id}_{section_id}",
                hide_index=True,
                on_select="rerun",
                selection_mode="multi-row",
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
        st.caption(
            "Don't see your part? Check whether it is in another fishbone section, "
            "or add it to the Parts catalog and this section without leaving the page."
        )
        find_or_add_part = st.button(
            "Find or add a missing part",
            icon=":material/search:",
            type="tertiary",
            key=f"process_find_or_add_part_{scenario_id}_{section_id}",
        )
        if find_or_add_part:
            if table_has_unsaved_changes(process_editor_key, native_row_selection=True):
                st.warning("Save or undo Process at a Glance table edits first.")
            else:
                st.session_state[missing_part_dialog_key] = True
                st.session_state.pop(f"selected_process_step_{scenario_id}", None)
        if available_parts.empty:
            if pairing_search and section_has_available_fishbone_parts:
                st.info("No available fishbone parts match this filter.")
            elif section_has_fishbone_parts:
                st.info("All fishbone parts in this section are already paired below.")
            else:
                st.info("No catalog parts are placed in this fishbone section.")
            selected_parts = available_parts
        else:
            part_event = selectable_dataframe(
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
                    "description": st.column_config.TextColumn("Part Name", width="large"),
                    "quantity": st.column_config.NumberColumn("Fishbone qty."),
                    "use_description": st.column_config.TextColumn("Use", width="medium"),
                    "model_applicability": "Models",
                },
            )
            selected_parts = available_parts.iloc[part_event.selection.rows]


    def close_missing_part_dialog() -> None:
        st.session_state.pop(missing_part_dialog_key, None)


    @st.dialog(
        "Find or add a fishbone part",
        width="large",
        dismissible=False,
        icon=":material/search:",
    )
    def missing_part_dialog(current_section_id: str) -> None:
        current_section_name = section_labels.get(current_section_id, current_section_id)
        st.caption(
            f"Current fishbone section: {current_section_name}. Search the whole project before "
            "creating a new catalog record."
        )
        find_tab, add_tab = st.tabs(["Find existing", "Add new part"])

        with find_tab:
            search_text = st.text_input(
                "Search by part number or name",
                placeholder="Enter all or part of a part number or part name",
                key=f"process_missing_part_search_{scenario_id}_{current_section_id}",
            ).strip()
            if len(search_text) < 2:
                st.info("Enter at least two characters to search the Parts catalog and all fishbone sections.")
            else:
                matches = search_parts_and_fishbone(
                    project_id, search_text, scenario_id
                )
                if matches.empty:
                    st.warning("No similar catalog parts were found. Use Add new part if this is new.")
                else:
                    summary_rows: list[dict] = []
                    for part_id, part_matches in matches.groupby("part_id", sort=False):
                        placed = part_matches.loc[part_matches["assignment_id"].notna()]
                        placements = []
                        for _, placement in placed.iterrows():
                            use_text = str(placement.get("use_description") or "").strip()
                            placement_text = (
                                f"{placement.get('section_name') or 'Unknown section'} "
                                f"(qty {int(placement.get('quantity') or 0)})"
                            )
                            if use_text:
                                placement_text += f" — {use_text}"
                            placements.append(placement_text)
                        first = part_matches.iloc[0]
                        summary_rows.append(
                            {
                                "part_id": str(part_id),
                                "part_number": str(first.get("part_number") or ""),
                                "description": str(first.get("description") or ""),
                                "revision": str(first.get("revision") or ""),
                                "fishbone_locations": " | ".join(placements) or "Not placed",
                            }
                        )
                    result_summary = pd.DataFrame(summary_rows)
                    selectable_dataframe(
                        result_summary.drop(columns=["part_id"]),
                        key=f"process_existing_part_matches_{scenario_id}_{current_section_id}",
                        hide_index=True,
                        column_config={
                            "part_number": st.column_config.TextColumn("Part number", pinned=True),
                            "description": st.column_config.TextColumn("Part Name", width="large"),
                            "revision": "Revision",
                            "fishbone_locations": st.column_config.TextColumn(
                                "Fishbone locations", width="large"
                            ),
                        },
                    )
                    labels_by_part = {
                        row["part_id"]: f"{row['part_number']} — {row['description']}"
                        for row in summary_rows
                    }
                    selected_part_id = st.selectbox(
                        "Part to review or place",
                        list(labels_by_part),
                        format_func=lambda value: labels_by_part.get(value, value),
                        key=f"process_missing_part_match_{scenario_id}_{current_section_id}",
                    )
                    selected_matches = matches.loc[
                        matches["part_id"].astype(str) == str(selected_part_id)
                    ].copy()
                    placements = selected_matches.loc[selected_matches["assignment_id"].notna()].copy()
                    current_placements = placements.loc[
                        placements["section_id"].astype(str) == str(current_section_id)
                    ]
                    other_placements = placements.loc[
                        placements["section_id"].astype(str) != str(current_section_id)
                    ]
                    if not current_placements.empty:
                        st.success("This part is already available in the current fishbone section.")
                        action_options = ["Add another use"]
                    elif not other_placements.empty:
                        st.warning(
                            "This part is placed in another fishbone section. Move that occurrence "
                            "if it was misplaced, or add another use if both placements are intentional."
                        )
                        action_options = ["Move an existing use", "Add another use"]
                    else:
                        st.info("This catalog part has not been placed on the fishbone yet.")
                        action_options = ["Place in selected section"]

                    placement_action = st.segmented_control(
                        "Action",
                        action_options,
                        default=action_options[0],
                        key=f"process_missing_part_action_{scenario_id}_{current_section_id}",
                    )
                    target_section_id = st.selectbox(
                        "Use / installation location",
                        section_ids,
                        index=section_ids.index(current_section_id),
                        format_func=lambda value: section_labels.get(value, value),
                        key=f"process_missing_part_target_section_{scenario_id}_{current_section_id}",
                    )
                    selected_assignment_id = None
                    if placement_action == "Move an existing use":
                        assignment_labels = {
                            str(row["assignment_id"]): (
                                f"{row.get('section_name') or 'Unknown section'} — "
                                f"qty {int(row.get('quantity') or 0)} — "
                                f"{row.get('use_description') or 'No use description'}"
                            )
                            for _, row in other_placements.iterrows()
                        }
                        selected_assignment_id = st.selectbox(
                            "Fishbone use to move",
                            list(assignment_labels),
                            format_func=lambda value: assignment_labels.get(value, value),
                            key=f"process_missing_part_assignment_{scenario_id}_{current_section_id}",
                        )
                    else:
                        placement_row = st.container(horizontal=True, vertical_alignment="bottom")
                        placement_quantity = placement_row.number_input(
                            "Fishbone quantity",
                            min_value=1,
                            value=1,
                            step=1,
                            key=f"process_missing_part_quantity_{scenario_id}_{current_section_id}",
                        )

                    if st.button(
                        placement_action,
                        type="primary",
                        icon=":material/account_tree:",
                        key=f"process_missing_part_apply_{scenario_id}_{current_section_id}",
                    ):
                        try:
                            if placement_action == "Move an existing use":
                                updated_at = move_fishbone_part_assignment(
                                    project_id, str(selected_assignment_id), target_section_id
                                )
                                audit_action = "Move part use"
                            else:
                                count = assign_parts_to_section(
                                    project_id,
                                    [str(selected_part_id)],
                                    target_section_id,
                                    "",
                                    allow_additional_use=not placements.empty,
                                    quantities_by_part={str(selected_part_id): int(placement_quantity)},
                                )
                                if count != 1:
                                    raise ValueError("The part could not be placed in this section.")
                                updated_at = None
                                audit_action = "Place part"
                            record_audit_event(
                                project_id,
                                "Fishbone part assignments",
                                audit_action,
                                1,
                                st.session_state.get("current_editor", ""),
                                {
                                    "part_id": str(selected_part_id),
                                    "section_id": target_section_id,
                                    "updated_at": updated_at,
                                },
                            )
                            close_missing_part_dialog()
                            st.toast(
                                f"{labels_by_part[str(selected_part_id)]} is now in "
                                f"{section_labels.get(target_section_id, target_section_id)}",
                                icon=":material/check_circle:",
                            )
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))

        with add_tab:
            st.caption(
                "This creates a project Parts-catalog record and its first fishbone use together. "
                "Images and advanced applicability can be added later on the Parts page."
            )
            new_part_number = st.text_input(
                "Part number",
                key=f"process_new_part_number_{scenario_id}_{current_section_id}",
            )
            new_description = st.text_input(
                "Part Name",
                key=f"process_new_part_description_{scenario_id}_{current_section_id}",
            )
            new_revision = st.text_input(
                "Revision",
                value="0",
                key=f"process_new_part_revision_{scenario_id}_{current_section_id}",
            )
            new_placement = st.container(horizontal=True, vertical_alignment="bottom")
            new_quantity = new_placement.number_input(
                "Fishbone quantity",
                min_value=1,
                value=1,
                step=1,
                key=f"process_new_part_quantity_{scenario_id}_{current_section_id}",
            )
            new_target_section_id = new_placement.selectbox(
                "Use / installation location",
                section_ids,
                index=section_ids.index(current_section_id),
                format_func=lambda value: section_labels.get(value, value),
                key=f"process_new_part_target_section_{scenario_id}_{current_section_id}",
            )
            new_notes = st.text_area(
                "Part notes",
                key=f"process_new_part_notes_{scenario_id}_{current_section_id}",
            )

            suggestion_text = new_part_number.strip() or new_description.strip()
            if len(suggestion_text) >= 2:
                suggestions = search_parts_and_fishbone(project_id, suggestion_text)
                if not suggestions.empty:
                    suggestion_summary = suggestions[
                        ["part_id", "part_number", "description", "revision", "section_name"]
                    ].drop_duplicates()
                    st.warning("Possible existing matches were found. Review them before creating a duplicate.")
                    selectable_dataframe(
                        suggestion_summary.drop(columns=["part_id"]),
                        key=f"process_new_part_matches_{scenario_id}_{current_section_id}",
                        hide_index=True,
                        column_config={
                            "part_number": "Part number",
                            "description": st.column_config.TextColumn("Part Name", width="large"),
                            "revision": "Revision",
                            "section_name": "Fishbone section",
                        },
                    )

            if st.button(
                "Add part and place it",
                type="primary",
                icon=":material/add_circle:",
                key=f"process_create_missing_part_{scenario_id}_{current_section_id}",
            ):
                try:
                    part_id, assignment_id, updated_at = create_part_and_assign_to_section(
                        project_id,
                        new_target_section_id,
                        {
                            "part_number": new_part_number,
                            "description": new_description,
                            "revision": new_revision,
                            "model_applicability": "All",
                            "notes": new_notes,
                        },
                        int(new_quantity),
                        "",
                    )
                    editor_name = st.session_state.get("current_editor", "")
                    record_audit_event(
                        project_id,
                        "Parts",
                        "Create from Process at a Glance",
                        1,
                        editor_name,
                        {"part_id": part_id, "updated_at": updated_at},
                    )
                    record_audit_event(
                        project_id,
                        "Fishbone part assignments",
                        "Place new part",
                        1,
                        editor_name,
                        {
                            "part_id": part_id,
                            "assignment_id": assignment_id,
                            "section_id": new_target_section_id,
                            "updated_at": updated_at,
                        },
                    )
                    close_missing_part_dialog()
                    st.toast(
                        f"Added {new_part_number.strip()} to Parts and "
                        f"{section_labels.get(new_target_section_id, new_target_section_id)}",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        if st.button(
            "Cancel",
            icon=":material/close:",
            key=f"process_missing_part_cancel_{scenario_id}_{current_section_id}",
        ):
            close_missing_part_dialog()
            st.rerun()


    if st.session_state.get(missing_part_dialog_key):
        missing_part_dialog(section_id)

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
                help=(
                    "Names this group of paired parts. It distinguishes alternatives or optional "
                    "groups, such as a control panel color; for a single Use all group, use a short "
                    "installation label."
                ),
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
                if not str(group_name or "").strip():
                    raise ValueError("Part requirement name is required.")
                if selected_parts.empty:
                    raise ValueError("Select at least one fishbone part.")
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
                project_id, scenario_id, selected_process_id, active_only=True
            )
            if saved_groups:
                st.markdown("##### Existing part pairings")
                pairing_editor_key = (
                    f"existing_process_pairings_{scenario_id}_{selected_process_id}"
                )
                apply_pending_table_editor_reset(pairing_editor_key)
                pairing_rows = pd.DataFrame(
                    [
                        {
                            "id": str(group["id"]),
                            "requirement": str(group["name"]),
                            "selection_rule": str(group["selection_rule"]),
                            "quantity": float(group["quantity"]),
                            "parts": ", ".join(
                                str(option["part_number"])
                                for option in group["options"]
                            ),
                        }
                        for group in saved_groups
                    ]
                )
                st.data_editor(
                    pairing_rows,
                    key=pairing_editor_key,
                    hide_index=True,
                    num_rows="delete",
                    disabled=list(pairing_rows.columns),
                    column_order=[
                        "requirement", "selection_rule", "quantity", "parts"
                    ],
                    column_config={
                        "id": None,
                        "requirement": st.column_config.TextColumn("Part requirement"),
                        "selection_rule": st.column_config.TextColumn("Selection rule"),
                        "quantity": st.column_config.NumberColumn(
                            "Quantity", format="%.2f"
                        ),
                        "parts": st.column_config.TextColumn(
                            "Paired Fishbone Parts", width="large"
                        ),
                    },
                )
                selected_pairings = native_selected_rows(
                    pairing_rows, editor_key=pairing_editor_key
                )
                request_pairing_delete = not selected_pairings.empty
                if request_pairing_delete:
                    selected_ids = set(selected_pairings["id"].astype(str))
                    selected_group_rows = [
                        group
                        for group in saved_groups
                        if str(group["id"]) in selected_ids
                    ]
                    st.session_state[pairing_delete_key] = {
                        "editor_key": pairing_editor_key,
                        "work_element_id": selected_process_id,
                        "work_element": selected_description,
                        "groups": [
                            {
                                "id": str(group["id"]),
                                "requirement": str(group["name"]),
                                "parts": [
                                    str(option["part_number"])
                                    for option in group["options"]
                                ],
                            }
                            for group in selected_group_rows
                        ],
                    }
    else:
        st.caption("Select one Yamazumi work element to pair parts or add it to the plan.")

st.divider()
apply_pending_table_editor_reset(process_editor_key)
elements = project_table("work_elements", project_id, "sequence", scenario_id=scenario_id)
models = project_models(project_id)
model_labels = {
    str(row["model_number"]): (str(row["display_name"]).strip() or "Familiar name not defined")
    for _, row in models.iterrows()
}
model_numbers_by_label = {label: number for number, label in model_labels.items()}
columns = [
    "id", "sequence", "station", "pitch_name", "work_element", "operation", "description", "cycle_time_s",
    "assigned_parts", "part_number", "output_assembly_number", "output_assembly_name",
    "tool", "torque", "quality_requirement", "ergo_requirement", "location", "unit_orientation",
    "conveyor_height_in", "platform_height_in", "pit_depth_in",
    "model_applicability", "status", "details",
]
compact_columns = [
    "station",
    "pitch_name",
    "work_element",
    "assigned_parts",
    "model_applicability",
    "cycle_time_s",
    "details",
    "status",
    "sequence",
]
if elements.empty:
    elements = pd.DataFrame(
        {
            "id": pd.Series(dtype="string"),
            "sequence": pd.Series(dtype="int64"),
            "station": pd.Series(dtype="string"),
            "pitch_name": pd.Series(dtype="string"),
            "work_element": pd.Series(dtype="string"),
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
            "unit_orientation": pd.Series(dtype="string"),
            "conveyor_height_in": pd.Series(dtype="float64"),
            "platform_height_in": pd.Series(dtype="float64"),
            "pit_depth_in": pd.Series(dtype="float64"),
            "model_applicability": pd.Series(dtype="object"),
            "status": pd.Series(dtype="string"),
            "details": pd.Series(dtype="string"),
        }
    )
else:
    elements = elements.copy()
    pairing_summary: dict[str, list[str]] = {}
    for group in process_part_groups(project_id, scenario_id, active_only=True):
        option_numbers = [str(option["part_number"]) for option in group["options"]]
        suffix = " / ".join(option_numbers) if group["selection_rule"] == "Choose one" else ", ".join(option_numbers)
        pairing_summary.setdefault(str(group["work_element_id"]), []).append(
            f"{group['name']}: {suffix}"
        )
    elements["assigned_parts"] = elements["id"].astype(str).map(
        lambda element_id: " | ".join(pairing_summary.get(element_id, []))
    )
    yamazumi_context = yamazumi_context_for_process(project_id, scenario_id)
    if yamazumi_context.empty:
        elements["pitch_name"] = ""
        elements["work_element"] = elements["operation"].fillna("").astype(str)
    else:
        yamazumi_context = yamazumi_context.drop_duplicates(
            subset=["process_element_id"], keep="first"
        ).set_index("process_element_id")
        process_ids = elements["id"].astype(str)
        elements["pitch_name"] = process_ids.map(
            yamazumi_context["pitch_name"].fillna("").astype(str)
        ).fillna("")
        yamazumi_descriptions = process_ids.map(
            yamazumi_context["yamazumi_description"].fillna("").astype(str)
        ).fillna("")
        elements["work_element"] = yamazumi_descriptions.where(
            yamazumi_descriptions.str.strip().ne(""),
            elements["operation"].fillna("").astype(str),
        )
    elements["details"] = ":material/info: Details"
    elements = elements.reindex(columns=columns)

elements["model_applicability"] = elements["model_applicability"].apply(
    lambda value: [
        "All models" if model.casefold() in {"all", "all models"} else model_labels.get(model, model)
        for model in (split_filter_values(value) or ["All"])
    ]
)

editable_table_heading("Process at a Glance by pitch")
st.caption(
    "Enter an output assembly number on the exact step where a new made assembly becomes complete. "
    "That milestone belongs to this scenario's Process at a Glance."
)

visible_elements = filter_table(
    elements,
    key=f"process_filters_{scenario_id}",
    dropdown_columns=["station", "status", "model_applicability"],
    search_columns=[
        "work_element", "pitch_name", "description", "station", "assigned_parts", "output_assembly_number",
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


process_action_slot = st.empty()
edited = st.data_editor(
    visible_elements,
    key=process_editor_key,
    hide_index=True,
    num_rows="delete",
    height=470,
    disabled=["id", "pitch_name", "work_element", "assigned_parts"],
    column_order=compact_columns,
    column_config={
        "id": None,
        "part_number": None,
        "details": standard_details_column_config(
            on_click=open_process_details, key=f"process_details_action_{scenario_id}"
        ),
        "sequence": st.column_config.NumberColumn("Seq.", min_value=0, step=10),
        "station": st.column_config.TextColumn("Pitch", pinned=True),
        "pitch_name": st.column_config.TextColumn("Pitch Name", pinned=True),
        "work_element": st.column_config.TextColumn(
            "Work Element", required=True, pinned=True, width="large"
        ),
        "assigned_parts": st.column_config.TextColumn(
            "Paired Fishbone Parts", width="large"
        ),
        "cycle_time_s": st.column_config.NumberColumn("Time (s)", min_value=0.0, step=0.1, format="%.1f"),
        "model_applicability": st.column_config.MultiselectColumn(
            "Models", options=["All models", *model_labels.values()]
        ),
        "status": st.column_config.SelectboxColumn(
            "Status", options=["Draft", "In review", "Released"]
        ),
    },
)
footer_actions = editable_table_footer(
    editor_key=process_editor_key,
    key_prefix=f"process_plan_{scenario_id}",
    native_row_selection=True,
)

details_blocked = st.session_state.pop(f"process_details_blocked_{scenario_id}", None)
if details_blocked:
    st.warning(details_blocked)

st.download_button(
    "Export filtered Process at a Glance",
    data=dataframe_to_excel(
        visible_elements.drop(columns=["id", "details"], errors="ignore"),
        "Process plan",
    ),
    file_name="process_plan_filtered.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    icon=":material/download:",
)

selected = native_selected_rows(visible_elements, editor_key=process_editor_key)


def current_process_editor_rows() -> pd.DataFrame:
    """Capture cell edits without treating native row selection as deletion."""
    state = st.session_state.get(process_editor_key, {}) or {}
    draft = visible_elements.copy()
    for raw_position, changes in (state.get("edited_rows") or {}).items():
        position = int(raw_position)
        if not 0 <= position < len(draft):
            continue
        for column, value in (changes or {}).items():
            if column in draft.columns:
                draft.at[draft.index[position], column] = value
    return draft


def save_unsaved_process_table_edits(*, paired_removal: bool) -> int:
    """Persist unrelated compact-table edits before a confirmed pairing removal."""
    if not table_has_unsaved_changes(
        process_editor_key, native_row_selection=True
    ):
        return 0
    draft = current_process_editor_rows()
    errors = required_field_errors(draft, {"work_element": "Work Element"})
    if errors:
        raise ValueError(" ".join(errors))
    combined = merge_filtered_edits(elements, visible_elements, draft)
    combined["model_applicability"] = combined["model_applicability"].apply(
        lambda assigned: ", ".join(
            "All" if label == "All models" else model_numbers_by_label.get(label, label)
            for label in (assigned or ["All models"])
        )
    )
    replace_work_elements(project_id, scenario_id, combined)
    changed_count = len(
        (st.session_state.get(process_editor_key, {}) or {}).get("edited_rows") or {}
    )
    record_audit_event(
        project_id,
        "Process plan",
        "Save & Refresh",
        changed_count,
        st.session_state.get("current_editor", ""),
        {
            "scenario_id": scenario_id,
            "saved_with_pairing_removal": paired_removal,
        },
    )
    return changed_count


bulk = selected_rows_action_bar(
    parent=process_action_slot,
)
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
request_bulk_delete = not selected.empty

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
        request_table_editor_reset(process_editor_key)
        st.rerun()
    if actions.button(
        "Delete steps", type="primary", icon=":material/delete:",
        key=f"destructive_confirm_process_delete_{scenario_id}",
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

if footer_actions.undo:
    request_table_editor_reset(process_editor_key)
    st.rerun()

if footer_actions.save_and_refresh:
    try:
        if not selected.empty:
            raise ValueError("Clear selected rows before saving table edits.")
        errors = required_field_errors(edited, {"work_element": "Work Element"})
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
            "Save & Refresh",
            len(combined_elements),
            st.session_state.get("current_editor", ""),
            {"scenario_id": scenario_id},
        )
        request_table_editor_reset(process_editor_key)
        st.toast("Process at a Glance saved", icon=":material/check_circle:")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))


@st.dialog("Remove selected part pairings?")
def confirm_pairing_bulk_removal() -> None:
    pending = st.session_state.get(pairing_delete_key, {})
    groups = pending.get("groups", [])
    st.warning(
        f"Remove {len(groups)} selected part pairing(s)? The parts listed below will be "
        "unpaired from this work element."
    )
    for group in groups:
        parts = ", ".join(group.get("parts", [])) or "No active parts"
        st.write(f"- {group['requirement']}: {parts}")
    st.info(
        "The parts are not deleted. They will return to the available-parts table for "
        "their Fishbone section."
    )
    has_other_edits = table_has_unsaved_changes(
        process_editor_key, native_row_selection=True
    )
    if has_other_edits:
        st.info(
            "Other unsaved Process at a Glance table edits will be saved at the same "
            "time so they are not lost."
        )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_pairing_bulk_remove_{scenario_id}"):
        st.session_state.pop(pairing_delete_key, None)
        pairing_editor_key = str(pending.get("editor_key") or "")
        if pairing_editor_key:
            request_table_editor_reset(pairing_editor_key)
        st.rerun()
    if actions.button(
        "Remove pairings",
        type="primary",
        icon=":material/link_off:",
        key=f"destructive_confirm_pairing_bulk_remove_{scenario_id}",
    ):
        try:
            save_unsaved_process_table_edits(paired_removal=True)
            group_ids = [str(group["id"]) for group in groups]
            removed_count = delete_process_part_groups(
                project_id, scenario_id, group_ids
            )
            record_audit_event(
                project_id,
                "Process part pairings",
                "Remove pairing",
                removed_count,
                st.session_state.get("current_editor", ""),
                {
                    "scenario_id": scenario_id,
                    "work_element_id": pending.get("work_element_id"),
                    "work_element": pending.get("work_element"),
                    "pairings": groups,
                },
            )
            st.session_state.pop(pairing_delete_key, None)
            request_table_editor_reset(process_editor_key)
            pairing_editor_key = str(pending.get("editor_key") or "")
            if pairing_editor_key:
                request_table_editor_reset(pairing_editor_key)
            st.toast(
                f"Removed {removed_count} pairing(s); their parts are available again.",
                icon=":material/check_circle:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


if st.session_state.get(pairing_delete_key):
    confirm_pairing_bulk_removal()


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
    linked_section = process_section_for_step(project_id, scenario_id, element_id)
    restored_state = st.session_state.pop(detail_restore_key, {})
    restored_draft = (
        restored_state.get("draft", {})
        if str(restored_state.get("work_element_id") or "") == str(element_id)
        else {}
    )

    def text_value(field: str) -> str:
        if field in restored_draft:
            value = restored_draft.get(field)
            return "" if value is None or pd.isna(value) else str(value)
        value = step.get(field)
        return "" if value is None or pd.isna(value) else str(value)

    def number_value(field: str) -> float | None:
        if field in restored_draft:
            value = restored_draft.get(field)
            return None if value is None or pd.isna(value) else float(value)
        value = step.get(field)
        return None if value is None or pd.isna(value) else float(value)

    st.subheader(str(step.get("work_element") or step.get("operation") or "Unnamed process step"))
    st.caption(
        f"Pitch: {step.get('station') or 'Unassigned'} · "
        f"Time: {float(step.get('cycle_time_s') or 0):.1f} s"
    )

    step_tab, tool_tab, location_tab, parts_tab, future_tab = st.tabs(
        [
            "Step details",
            "Tool",
            "Unit orientation and heights",
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

    with location_tab:
        location = st.text_input(
            "Location",
            value=text_value("location"),
            key=f"{widget_prefix}_location",
        )
        unit_orientation = st.text_input(
            "Unit orientation",
            value=text_value("unit_orientation"),
            placeholder="Example: Front toward operator",
            key=f"{widget_prefix}_unit_orientation",
        )
        conveyor_height_in = st.number_input(
            "Conveyor height (in)",
            min_value=0.0,
            value=number_value("conveyor_height_in"),
            step=0.1,
            format="%.2f",
            key=f"{widget_prefix}_conveyor_height_in",
        )
        apply_geometry_to_section = st.checkbox(
            "Apply this orientation and conveyor height to every Process step in this Fishbone section",
            value=bool(restored_state.get("apply_geometry_to_section", False)),
            disabled=linked_section is None,
            help=(
                "On Save, this copies both values to existing Process at a Glance steps tied to "
                "the same Fishbone section in this planning scenario."
            ),
            key=f"{widget_prefix}_apply_geometry_to_section",
        )
        if linked_section:
            st.caption(f"Fishbone section: {linked_section['name']}")
        else:
            st.caption(
                "This step is not tied to exactly one Fishbone section, so section-wide fill is unavailable."
            )

    with parts_tab:
        st.markdown("**Paired fishbone parts**")
        st.write(step.get("assigned_parts") or "No fishbone parts are paired to this step.")
        saved_step_groups = process_part_groups(
            project_id, scenario_id, element_id, active_only=True
        )
        if saved_step_groups:
            st.caption("Remove an incorrect pairing here. Its parts will return to the available-parts table.")
            for group in saved_step_groups:
                group_parts = ", ".join(
                    str(option["part_number"]) for option in group["options"]
                )
                group_row = st.container(
                    horizontal=True, vertical_alignment="center", border=True
                )
                group_row.write(
                    f"**{group['name']}** · {group['selection_rule']} · "
                    f"Qty {float(group['quantity']):g} · {group_parts}"
                )
                if group_row.button(
                    "Remove pairing",
                    icon=":material/link_off:",
                    key=f"destructive_{widget_prefix}_remove_pairing_{group['id']}",
                ):
                    detail_draft = {
                        "description": description,
                        "output_assembly_number": output_assembly_number,
                        "output_assembly_name": output_assembly_name,
                        "tool": tool,
                        "location": location,
                        "unit_orientation": unit_orientation,
                        "conveyor_height_in": conveyor_height_in,
                    }
                    details_changed = apply_geometry_to_section or any(
                        (
                            number_value(field) != detail_draft[field]
                            if field == "conveyor_height_in"
                            else text_value(field) != str(detail_draft[field] or "")
                        )
                        for field in detail_draft
                    )
                    st.session_state[detail_pairing_delete_key] = {
                        "group_id": str(group["id"]),
                        "requirement": str(group["name"]),
                        "parts": [
                            str(option["part_number"])
                            for option in group["options"]
                        ],
                        "work_element_id": element_id,
                        "work_element": str(
                            step.get("work_element")
                            or step.get("operation")
                            or "Unnamed process step"
                        ),
                        "draft": detail_draft,
                        "apply_geometry_to_section": apply_geometry_to_section,
                        "details_changed": details_changed,
                    }
                    st.rerun()
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
            updated_at, affected_count, affected_section_id = update_process_step_details(
                project_id,
                scenario_id,
                element_id,
                {
                    "description": description,
                    "output_assembly_number": output_assembly_number,
                    "output_assembly_name": output_assembly_name,
                    "tool": tool,
                    "location": location,
                    "unit_orientation": unit_orientation,
                    "conveyor_height_in": conveyor_height_in,
                },
                apply_geometry_to_section=apply_geometry_to_section,
            )
            record_audit_event(
                project_id,
                "Process plan",
                "Edit details",
                affected_count,
                st.session_state.get("current_editor", ""),
                {
                    "scenario_id": scenario_id,
                    "work_element_id": element_id,
                    "section_id": affected_section_id,
                    "applied_section_wide": apply_geometry_to_section,
                    "updated_at": updated_at,
                },
            )
            close_process_details()
            request_table_editor_reset(process_editor_key)
            toast_message = (
                f"Details saved and geometry applied to {affected_count} section steps"
                if apply_geometry_to_section
                else "Process-step details saved"
            )
            st.toast(toast_message, icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog(
    "Remove process pairing?",
    dismissible=False,
    icon=":material/link_off:",
)
def confirm_detail_pairing_removal() -> None:
    pending = st.session_state.get(detail_pairing_delete_key, {})
    parts = ", ".join(pending.get("parts", [])) or "No active parts"
    st.warning(
        f"Remove the part requirement '{pending.get('requirement', '')}' from "
        f"{pending.get('work_element', 'this process step')}?"
    )
    st.write(f"Parts to unpair: {parts}")
    st.info(
        "The parts are not deleted. They will return to the available-parts table for "
        "their Fishbone section."
    )
    if pending.get("details_changed"):
        st.info(
            "Other unsaved step-detail edits will be saved at the same time so they are "
            "not lost."
        )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_detail_pairing_remove_{scenario_id}"):
        st.session_state[detail_restore_key] = {
            "work_element_id": pending.get("work_element_id"),
            "draft": pending.get("draft", {}),
            "apply_geometry_to_section": pending.get(
                "apply_geometry_to_section", False
            ),
        }
        st.session_state.pop(detail_pairing_delete_key, None)
        st.rerun()
    if actions.button(
        "Remove pairing",
        type="primary",
        icon=":material/link_off:",
        key=f"destructive_confirm_detail_pairing_remove_{scenario_id}",
    ):
        try:
            element_id = str(pending.get("work_element_id") or "")
            if pending.get("details_changed"):
                updated_at, affected_count, affected_section_id = (
                    update_process_step_details(
                        project_id,
                        scenario_id,
                        element_id,
                        pending.get("draft", {}),
                        apply_geometry_to_section=bool(
                            pending.get("apply_geometry_to_section")
                        ),
                    )
                )
                record_audit_event(
                    project_id,
                    "Process plan",
                    "Edit details",
                    affected_count,
                    st.session_state.get("current_editor", ""),
                    {
                        "scenario_id": scenario_id,
                        "work_element_id": element_id,
                        "section_id": affected_section_id,
                        "applied_section_wide": bool(
                            pending.get("apply_geometry_to_section")
                        ),
                        "updated_at": updated_at,
                        "saved_with_pairing_removal": True,
                    },
                )
            removed_count = delete_process_part_groups(
                project_id, scenario_id, [str(pending.get("group_id") or "")]
            )
            record_audit_event(
                project_id,
                "Process part pairings",
                "Remove pairing",
                removed_count,
                st.session_state.get("current_editor", ""),
                {
                    "scenario_id": scenario_id,
                    "work_element_id": element_id,
                    "work_element": pending.get("work_element"),
                    "pairings": [
                        {
                            "id": pending.get("group_id"),
                            "requirement": pending.get("requirement"),
                            "parts": pending.get("parts", []),
                        }
                    ],
                },
            )
            st.session_state.pop(detail_pairing_delete_key, None)
            close_process_details()
            request_table_editor_reset(process_editor_key)
            st.toast(
                "Pairing removed; its parts are available again.",
                icon=":material/check_circle:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


selected_step_id = st.session_state.get(f"selected_process_step_{scenario_id}")
if (
    st.session_state.get(detail_pairing_delete_key)
    and not st.session_state.get(f"process_pending_delete_{scenario_id}")
    and not st.session_state.get(missing_part_dialog_key)
):
    confirm_detail_pairing_removal()
elif (
    selected_step_id
    and not st.session_state.get(f"process_pending_delete_{scenario_id}")
    and not st.session_state.get(pairing_delete_key)
    and not st.session_state.get(missing_part_dialog_key)
):
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
        selectable_dataframe(
            display_history,
            key=f"process_history_table_{project_id}_{scenario_id}",
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
