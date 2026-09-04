import pandas as pd
import streamlit as st

from utils.pfmea_ui import render_pfmea_tab
from utils.quality_store import (
    TORQUE_TOOL_ORIENTATIONS,
    TORQUE_TOOL_TYPES,
    assign_quality_requirement,
    bulk_update_quality_requirement_pass_fail,
    delete_quality_requirement_assignments,
    delete_quality_requirement_torque_details,
    delete_quality_requirements,
    push_quality_requirements,
    quality_assignment_pfmea_impact,
    quality_process_steps,
    quality_requirement_assignment,
    quality_requirement_links,
    quality_requirement_torque_details,
    quality_requirements,
    save_quality_requirement_torque_detail,
    save_quality_requirement_rows,
    torque_screw_bit_types,
)
from utils.scope_ui import page_title_with_scope, section_heading_with_scope
from utils.store import audit_history, planning_scenarios, record_audit_event
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
)
from utils.table_ui import (
    dataframe_to_excel,
    direct_entry_editor_rows,
    drop_untouched_new_rows,
    editable_table_footer,
    editable_table_heading,
    native_selected_rows,
    required_field_errors,
    selected_rows_action_bar,
    selectable_dataframe,
    stage_native_delete_confirmation,
    table_has_unsaved_changes,
)


def render_quality_history(project_id: str) -> None:
    """Render the page's one bottom History expander with workflow tabs."""
    with st.expander("History", icon=":material/history:"):
        requirements_history_tab, pfmea_history_tab = st.tabs(
            ["Requirements", "PFMEA"], key=f"quality_history_tabs_{project_id}"
        )
        with requirements_history_tab:
            history = audit_history(project_id, "Quality requirements", limit=50)
            if history.empty:
                st.caption("No Quality requirement changes have been recorded yet.")
            else:
                selectable_dataframe(
                    history.drop(columns=["details"], errors="ignore"),
                    key=f"quality_requirements_history_{project_id}",
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
        with pfmea_history_tab:
            history = audit_history(project_id, "PFMEA", limit=50)
            if history.empty:
                st.caption("No PFMEA changes have been recorded yet.")
            else:
                selectable_dataframe(
                    history.drop(columns=["details"], errors="ignore"),
                    key=f"pfmea_history_{project_id}",
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


project_id = st.session_state.get("project_id")
page_title_with_scope(
    "Quality",
    scope="scenario-aware",
    help_text=(
        "The Quality requirements repository is shared across every scenario. "
        "PFMEA records belong only to the currently selected scenario."
    ),
)
st.caption(
    "Maintain reusable checks and specifications, then deliberately publish saved "
    "updates to linked Process at a Glance steps."
)
if not project_id:
    st.stop()

logical_editor_key = f"quality_requirements_editor_{project_id}"
editor_key = apply_pending_table_editor_reset(logical_editor_key)
pending_delete_key = f"quality_requirements_pending_delete_{project_id}"
pending_push_key = f"quality_requirements_pending_push_{project_id}"
pending_unlink_key = f"quality_requirement_pending_unlink_{project_id}"

scenarios = planning_scenarios(project_id)
scenario_by_id = {str(scenario["id"]): scenario for scenario in scenarios}
scenario_id = str(st.session_state.get("scenario_id") or "")
active_scenario = scenario_by_id.get(scenario_id)

requirements_repository_tab, pfmea_tab, control_plan_tab = st.tabs(
    ["Requirements repository", "PFMEA", "Control Plan"],
    key=f"quality_page_tabs_{project_id}",
    on_change="rerun",
)
if pfmea_tab.open:
    with pfmea_tab:
        if not active_scenario:
            st.info("Select an active planning scenario before opening PFMEA.")
        else:
            render_pfmea_tab(project_id, scenario_id, str(active_scenario["name"]))
    render_quality_history(project_id)
    st.stop()
if control_plan_tab.open:
    with control_plan_tab:
        st.subheader("Control Plan")
        st.info(
            "Control Plan generation is reserved for a later approved phase. "
            "No Control Plan records or automatic PFMEA action dispositions are created here."
        )
    render_quality_history(project_id)
    st.stop()

# The existing repository workflow remains in its own lazy tab without moving or
# duplicating its established widgets and state keys.
requirements_repository_tab.__enter__()

table_columns = [
    "id", "requirement_type", "description", "unique_identifier", "pass_fail",
    "target_value", "tolerances", "unit", "assignment_count",
    "pending_assignment_count", "updated_at",
    "torque_detail_count",
]
requirements = quality_requirements(project_id)
if requirements.empty:
    requirements = pd.DataFrame(
        {
            "id": pd.Series(dtype="string"),
            "requirement_type": pd.Series(dtype="string"),
            "description": pd.Series(dtype="string"),
            "unique_identifier": pd.Series(dtype="string"),
            "pass_fail": pd.Series(dtype="bool"),
            "target_value": pd.Series(dtype="float64"),
            "tolerances": pd.Series(dtype="string"),
            "unit": pd.Series(dtype="string"),
            "assignment_count": pd.Series(dtype="int64"),
            "pending_assignment_count": pd.Series(dtype="int64"),
            "torque_detail_count": pd.Series(dtype="int64"),
            "updated_at": pd.Series(dtype="string"),
        }
    )
else:
    requirements = requirements.reindex(columns=table_columns).copy()
    requirements["pass_fail"] = requirements["pass_fail"].fillna(0).astype(bool)
    requirements["target_value"] = pd.to_numeric(
        requirements["target_value"], errors="coerce"
    )
    for count_column in [
        "assignment_count", "pending_assignment_count", "torque_detail_count",
    ]:
        requirements[count_column] = (
            pd.to_numeric(requirements[count_column], errors="coerce")
            .fillna(0)
            .astype(int)
        )

editable_table_heading("Quality requirements")
visible_requirements = filter_table(
    requirements,
    key=f"quality_requirements_filters_{project_id}",
    dropdown_columns=["requirement_type", "unit"],
    search_columns=[
        "requirement_type", "description", "unique_identifier", "tolerances", "unit",
    ],
    labels={"requirement_type": "Type", "unit": "Unit"},
    reset_widget_keys=[editor_key],
)
editor_rows = direct_entry_editor_rows(
    visible_requirements,
    editor_key=editor_key,
    sort_columns=[
        "requirement_type", "unique_identifier", "description", "pass_fail",
        "target_value", "unit", "assignment_count", "pending_assignment_count",
        "updated_at",
    ],
    labels={
        "requirement_type": "Type",
        "unique_identifier": "Unique identifier",
        "pass_fail": "Pass/fail",
        "target_value": "Target value",
        "assignment_count": "Linked Process steps",
        "pending_assignment_count": "Pending linked updates",
        "updated_at": "Updated",
    },
)
edited_requirements = st.data_editor(
    editor_rows,
    key=editor_key,
    num_rows="dynamic",
    hide_index=True,
    height=430,
    disabled=["id", "assignment_count", "pending_assignment_count", "updated_at"],
    column_order=[
        "requirement_type", "description", "unique_identifier", "pass_fail",
        "target_value", "tolerances", "unit", "assignment_count",
        "pending_assignment_count", "updated_at",
    ],
    column_config={
        "id": None,
        "requirement_type": st.column_config.TextColumn(
            "Type", required=True, pinned=True,
            help=(
                "Describe the kind of check, such as dimensional, torque, present and "
                "fully seated, or vision-system validation."
            ),
        ),
        "description": st.column_config.TextColumn(
            "Description", required=True, width="large",
            help="State what must be checked and what acceptable work looks like.",
        ),
        "unique_identifier": st.column_config.TextColumn(
            "Unique identifier", required=True,
            help=(
                "Use a stable project identifier so this definition remains recognizable "
                "when its description changes."
            ),
        ),
        "pass_fail": st.column_config.CheckboxColumn(
            "Pass/fail", default=False,
            help="Turn on when the result is recorded as a pass-or-fail check.",
        ),
        "target_value": st.column_config.NumberColumn(
            "Target value", help="Enter the required numeric value when the check has one.",
        ),
        "tolerances": st.column_config.TextColumn(
            "Tolerances", help="Describe the permitted variation around the target value.",
        ),
        "unit": st.column_config.TextColumn(
            "Unit",
            help=(
                "Use the measurement unit appropriate to the requirement. Linear "
                "dimensions must use inches."
            ),
        ),
        "assignment_count": st.column_config.NumberColumn(
            "Linked Process steps",
            help="Number of Process at a Glance steps currently using this requirement.",
        ),
        "pending_assignment_count": st.column_config.NumberColumn(
            "Pending linked updates",
            help=(
                "Number of linked Process requirements still carrying the previously "
                "published values."
            ),
        ),
        "updated_at": st.column_config.DatetimeColumn(
            "Updated", format="MMM DD, YYYY HH:mm"
        ),
        "torque_detail_count": None,
    },
)
footer_actions = editable_table_footer(
    editor_key=editor_key,
    key_prefix=f"quality_requirements_{project_id}",
    native_row_selection=True,
)
if footer_actions.undo:
    request_table_editor_reset(editor_key)
    st.toast("Discarded the unsaved Quality requirement edits", icon=":material/undo:")
    st.rerun()

st.caption(
    "Type or paste new requirements into the blank entry row. Save repository edits "
    "before publishing them to linked Process at a Glance steps."
)
export_columns = [
    "requirement_type", "description", "unique_identifier", "pass_fail",
    "target_value", "tolerances", "unit", "assignment_count",
    "pending_assignment_count", "updated_at",
]
st.download_button(
    "Export filtered rows",
    data=dataframe_to_excel(
        visible_requirements.reindex(columns=export_columns), "Quality requirements"
    ),
    file_name="quality_requirements_filtered.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    icon=":material/download:",
)

selected_requirements = native_selected_rows(editor_rows, editor_key=editor_key)
bulk_controls = selected_rows_action_bar()
bulk_pass_fail = bulk_controls.selectbox(
    "Pass/fail setting for selected requirements",
    options=["Keep current", "Pass/fail check", "Measured value"],
    key=f"quality_requirements_bulk_pass_fail_{project_id}",
    help="Apply one Pass/fail setting to every selected Quality requirement.",
)
apply_bulk_pass_fail = bulk_controls.button(
    f"Apply to selected ({len(selected_requirements)})",
    type="primary",
    icon=":material/checklist:",
    disabled=selected_requirements.empty or bulk_pass_fail == "Keep current",
    key=f"quality_requirements_apply_bulk_pass_fail_{project_id}",
)

if apply_bulk_pass_fail:
    if table_has_unsaved_changes(editor_key, native_row_selection=True):
        st.warning("Save or undo other table edits before applying a bulk change.")
    else:
        try:
            selected_ids = selected_requirements["id"].astype(str).tolist()
            result = bulk_update_quality_requirement_pass_fail(
                project_id,
                selected_ids,
                pass_fail=bulk_pass_fail == "Pass/fail check",
            )
            changed_count = int(result["row_count"])
            if changed_count:
                record_audit_event(
                    project_id,
                    "Quality requirements",
                    "Bulk edit",
                    changed_count,
                    st.session_state.get("current_editor", ""),
                    {
                        "requirement_ids": result["updated_ids"],
                        "pass_fail": bulk_pass_fail == "Pass/fail check",
                        "store_timestamp": result["timestamp"],
                    },
                )
            request_table_editor_reset(editor_key)
            st.toast(
                (
                    f"Updated {changed_count} Quality requirement(s)"
                    if changed_count
                    else "Selected Quality requirements are already up to date"
                ),
                icon=":material/check_circle:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
elif not selected_requirements.empty:
    if table_has_unsaved_changes(editor_key, native_row_selection=True):
        st.warning(
            "Save or undo other table edits before deleting selected Quality requirements."
        )
    else:
        st.session_state[pending_delete_key] = [
            {
                "id": str(row["id"]),
                "unique_identifier": str(row["unique_identifier"]),
                "description": str(row["description"]),
                "assignment_count": int(row.get("assignment_count") or 0),
                "torque_detail_count": int(row.get("torque_detail_count") or 0),
            }
            for _, row in selected_requirements.iterrows()
        ]
        stage_native_delete_confirmation(editor_key)


@st.dialog("Delete selected Quality requirements?", dismissible=False)
def confirm_quality_requirement_delete() -> None:
    pending = st.session_state.get(pending_delete_key, [])
    linked_count = sum(int(item["assignment_count"]) for item in pending)
    torque_detail_count = sum(int(item["torque_detail_count"]) for item in pending)
    st.warning(
        f"Delete {len(pending)} selected Quality requirement(s)? This permanently "
        "removes the project repository definitions."
    )
    for item in pending:
        st.write(
            f"- {item['unique_identifier']}: {item['description']} "
            f"— {item['assignment_count']} linked Process step(s), "
            f"{item['torque_detail_count']} Torque tool detail record(s)"
        )
    if linked_count:
        st.error(
            "These definitions cannot be deleted until their linked Process requirement "
            "assignments are removed."
        )
    if torque_detail_count:
        st.error(
            "These definitions cannot be deleted until their linked Torque tool "
            "details are removed."
        )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_quality_requirement_delete_{project_id}"):
        st.session_state.pop(pending_delete_key, None)
        request_table_editor_reset(editor_key)
        st.rerun()
    if actions.button(
        "Delete", type="primary", icon=":material/delete:",
        disabled=bool(linked_count or torque_detail_count),
        key=f"destructive_confirm_quality_requirement_delete_{project_id}",
    ):
        try:
            requirement_ids = [item["id"] for item in pending]
            deleted_count = delete_quality_requirements(project_id, requirement_ids)
            record_audit_event(
                project_id, "Quality requirements", "Bulk delete", deleted_count,
                st.session_state.get("current_editor", ""),
                {
                    "requirement_ids": requirement_ids,
                    "unique_identifiers": [item["unique_identifier"] for item in pending],
                },
            )
            st.session_state.pop(pending_delete_key, None)
            request_table_editor_reset(editor_key)
            st.toast(
                f"Deleted {deleted_count} Quality requirement(s)", icon=":material/delete:"
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


if st.session_state.get(pending_delete_key):
    confirm_quality_requirement_delete()

if footer_actions.save_and_refresh:
    try:
        if not selected_requirements.empty:
            raise ValueError(
                "Clear selected rows before saving table edits. Selection is reserved "
                "for the confirmed deletion workflow."
            )
        edited_requirements = drop_untouched_new_rows(
            edited_requirements,
            identifying_columns=["requirement_type", "description", "unique_identifier"],
        )
        validation_errors = required_field_errors(
            edited_requirements,
            {
                "requirement_type": "Type",
                "description": "Description",
                "unique_identifier": "Unique identifier",
            },
        )
        if validation_errors:
            raise ValueError(" ".join(validation_errors))
        combined_requirements = merge_filtered_edits(
            requirements, visible_requirements, edited_requirements
        )
        result = save_quality_requirement_rows(
            project_id,
            combined_requirements.reindex(
                columns=[
                    "id", "requirement_type", "description", "unique_identifier",
                    "pass_fail", "target_value", "tolerances", "unit",
                ]
            ),
        )
        changed_count = int(result["row_count"])
        if changed_count:
            record_audit_event(
                project_id, "Quality requirements", "Save & Refresh", changed_count,
                st.session_state.get("current_editor", ""),
                {
                    "created_ids": result["created_ids"],
                    "updated_ids": result["updated_ids"],
                    "store_timestamp": result["timestamp"],
                },
            )
        request_table_editor_reset(editor_key)
        st.toast(
            (
                f"Saved {changed_count} Quality requirement(s)"
                if changed_count else "Quality requirements are already up to date"
            ),
            icon=":material/check_circle:",
        )
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

has_unsaved_edits = table_has_unsaved_changes(
    editor_key, native_row_selection=True
)

st.divider()
section_heading_with_scope("Torque tool details", scope="project")
st.caption(
    "Select a saved Torque requirement to maintain its project-wide tool details. "
    "Each Torque requirement can have one detail record."
)
torque_requirements = requirements.loc[
    requirements["requirement_type"].fillna("").astype(str).str.strip().str.casefold().eq(
        "torque"
    )
].copy()
torque_requirement_labels = {
    str(row["id"]): f"{row['unique_identifier']} — {row['description']}"
    for _, row in torque_requirements.iterrows()
}
selected_torque_requirement_id = st.selectbox(
    "Saved Torque requirement",
    options=list(torque_requirement_labels),
    index=None,
    placeholder="Choose a saved Torque requirement",
    format_func=lambda requirement_id: torque_requirement_labels.get(
        str(requirement_id), "Unavailable Torque requirement"
    ),
    disabled=not torque_requirement_labels or has_unsaved_edits,
    key=f"quality_torque_detail_requirement_{project_id}",
    help=(
        "Only saved Quality requirements whose Type is Torque appear here. "
        "Tool details stay linked to the selected repository requirement."
    ),
)
if not torque_requirement_labels:
    st.caption("Create and save a Quality requirement with Type set to Torque first.")
elif has_unsaved_edits:
    st.info("Save or undo repository edits before maintaining Torque tool details.")

if selected_torque_requirement_id and not has_unsaved_edits:
    selected_torque_requirement_id = str(selected_torque_requirement_id)
    torque_editor_key = apply_pending_table_editor_reset(
        f"quality_torque_details_editor_{project_id}_{selected_torque_requirement_id}"
    )
    torque_pending_delete_key = (
        f"quality_torque_details_pending_delete_{project_id}_"
        f"{selected_torque_requirement_id}"
    )
    torque_details = quality_requirement_torque_details(
        project_id, selected_torque_requirement_id
    )
    if torque_details.empty:
        torque_details = pd.DataFrame(
            [
                {
                    "id": "",
                    "project_id": project_id,
                    "quality_requirement_id": selected_torque_requirement_id,
                    "tool_type": "",
                    "tool_orientation": "",
                    "screw_bit_type": "",
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        )
    current_screw_bit_type = str(
        torque_details.iloc[0].get("screw_bit_type") or ""
    ).strip()
    screw_bit_options = torque_screw_bit_types(project_id)
    if current_screw_bit_type and current_screw_bit_type not in screw_bit_options:
        screw_bit_options.append(current_screw_bit_type)
        screw_bit_options.sort(key=str.casefold)
    screw_bit_key = (
        f"quality_torque_screw_bit_type_{project_id}_{selected_torque_requirement_id}"
    )
    screw_bit_type = st.selectbox(
        "Screw bit type",
        options=screw_bit_options,
        index=(
            screw_bit_options.index(current_screw_bit_type)
            if current_screw_bit_type else None
        ),
        placeholder="Choose a previous value or enter a new one",
        accept_new_options=True,
        key=screw_bit_key,
        help=(
            "Choose a Screw bit type already used in this project or type a new value. "
            "New values become available after Save & Refresh."
        ),
    )
    torque_details = torque_details.copy()
    torque_details["screw_bit_type"] = str(screw_bit_type or "").strip()
    torque_editor_rows = direct_entry_editor_rows(
        torque_details,
        editor_key=torque_editor_key,
        sort_columns=["tool_type", "tool_orientation", "screw_bit_type"],
        labels={
            "tool_type": "Tool type",
            "tool_orientation": "Tool orientation",
            "screw_bit_type": "Screw bit type",
        },
    )
    edited_torque_details = st.data_editor(
        torque_editor_rows,
        key=torque_editor_key,
        num_rows="dynamic",
        hide_index=True,
        disabled=[
            "id", "project_id", "quality_requirement_id", "screw_bit_type",
            "created_at", "updated_at",
        ],
        column_order=[
            "tool_type", "tool_orientation", "screw_bit_type", "updated_at",
        ],
        column_config={
            "id": None,
            "project_id": None,
            "quality_requirement_id": None,
            "tool_type": st.column_config.SelectboxColumn(
                "Tool type",
                options=TORQUE_TOOL_TYPES,
                required=True,
                help="Select the power and control category used by the torque tool.",
            ),
            "tool_orientation": st.column_config.SelectboxColumn(
                "Tool orientation",
                options=TORQUE_TOOL_ORIENTATIONS,
                required=True,
                help="Select how the torque tool is held or positioned during use.",
            ),
            "screw_bit_type": st.column_config.TextColumn(
                "Screw bit type",
                required=True,
                help="Use the selector above to choose a previous value or enter a new one.",
            ),
            "created_at": None,
            "updated_at": st.column_config.DatetimeColumn(
                "Updated", format="MMM DD, YYYY HH:mm"
            ),
        },
    )
    screw_bit_changed = current_screw_bit_type != str(screw_bit_type or "").strip()
    torque_footer_actions = editable_table_footer(
        editor_key=torque_editor_key,
        key_prefix=(
            f"quality_torque_details_{project_id}_{selected_torque_requirement_id}"
        ),
        native_row_selection=True,
        additional_unsaved_changes=screw_bit_changed,
    )
    if torque_footer_actions.undo:
        st.session_state.pop(screw_bit_key, None)
        request_table_editor_reset(torque_editor_key)
        st.toast("Discarded the unsaved Torque tool detail edits", icon=":material/undo:")
        st.rerun()

    selected_torque_details = native_selected_rows(
        torque_editor_rows, editor_key=torque_editor_key
    )
    if not selected_torque_details.empty:
        if table_has_unsaved_changes(
            torque_editor_key, native_row_selection=True
        ) or screw_bit_changed:
            st.warning("Save or undo other edits before deleting Torque tool details.")
        else:
            st.session_state[torque_pending_delete_key] = [
                {
                    "id": str(row["id"]),
                    "tool_type": str(row["tool_type"]),
                    "tool_orientation": str(row["tool_orientation"]),
                    "screw_bit_type": str(row["screw_bit_type"]),
                }
                for _, row in selected_torque_details.iterrows()
            ]
            stage_native_delete_confirmation(torque_editor_key)

    @st.dialog("Delete selected Torque tool details?", dismissible=False)
    def confirm_torque_detail_delete() -> None:
        pending = st.session_state.get(torque_pending_delete_key, [])
        st.warning(
            "Delete the selected Torque tool detail record? The linked Quality "
            "requirement and its Process-step assignments will be preserved."
        )
        for item in pending:
            st.write(
                f"- {item['tool_type']} · {item['tool_orientation']} · "
                f"{item['screw_bit_type']}"
            )
        actions = st.container(horizontal=True)
        if actions.button(
            "Cancel",
            key=(
                f"cancel_quality_torque_detail_delete_{project_id}_"
                f"{selected_torque_requirement_id}"
            ),
        ):
            st.session_state.pop(torque_pending_delete_key, None)
            request_table_editor_reset(torque_editor_key)
            st.rerun()
        if actions.button(
            "Delete",
            type="primary",
            icon=":material/delete:",
            key=(
                f"destructive_confirm_quality_torque_detail_delete_{project_id}_"
                f"{selected_torque_requirement_id}"
            ),
        ):
            try:
                detail_ids = [str(item["id"]) for item in pending]
                deleted_count = delete_quality_requirement_torque_details(
                    project_id, selected_torque_requirement_id, detail_ids
                )
                record_audit_event(
                    project_id,
                    "Quality requirements",
                    "Delete Torque tool details",
                    deleted_count,
                    st.session_state.get("current_editor", ""),
                    {
                        "quality_requirement_id": selected_torque_requirement_id,
                        "detail_ids": detail_ids,
                    },
                )
                st.session_state.pop(torque_pending_delete_key, None)
                st.session_state.pop(screw_bit_key, None)
                request_table_editor_reset(torque_editor_key)
                st.toast("Deleted the Torque tool details", icon=":material/delete:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if st.session_state.get(torque_pending_delete_key):
        confirm_torque_detail_delete()

    if torque_footer_actions.save_and_refresh:
        try:
            if not selected_torque_details.empty:
                raise ValueError(
                    "Clear selected rows before saving. Selection is reserved for "
                    "the confirmed deletion workflow."
                )
            prepared_torque_details = drop_untouched_new_rows(
                edited_torque_details,
                identifying_columns=[
                    "tool_type", "tool_orientation", "screw_bit_type",
                ],
            )
            if len(prepared_torque_details) > 1:
                raise ValueError(
                    "Each Torque requirement can have only one Torque tool detail record."
                )
            if prepared_torque_details.empty:
                raise ValueError("Enter the Torque tool details before saving.")
            prepared_torque_details = prepared_torque_details.copy()
            prepared_torque_details.loc[:, "screw_bit_type"] = str(
                screw_bit_type or ""
            ).strip()
            validation_errors = required_field_errors(
                prepared_torque_details,
                {
                    "tool_type": "Tool type",
                    "tool_orientation": "Tool orientation",
                    "screw_bit_type": "Screw bit type",
                },
            )
            if validation_errors:
                raise ValueError(" ".join(validation_errors))
            result = save_quality_requirement_torque_detail(
                project_id,
                selected_torque_requirement_id,
                prepared_torque_details.iloc[0].to_dict(),
            )
            changed_count = int(result["row_count"])
            if changed_count:
                record_audit_event(
                    project_id,
                    "Quality requirements",
                    "Save & Refresh Torque tool details",
                    changed_count,
                    st.session_state.get("current_editor", ""),
                    {
                        "quality_requirement_id": selected_torque_requirement_id,
                        "torque_detail_id": result["id"],
                        "store_timestamp": result["timestamp"],
                    },
                )
            st.session_state.pop(screw_bit_key, None)
            request_table_editor_reset(torque_editor_key)
            st.toast(
                (
                    "Saved the Torque tool details"
                    if changed_count else "Torque tool details are already up to date"
                ),
                icon=":material/check_circle:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

st.divider()
if active_scenario:
    section_heading_with_scope(
        "Link to Process at a Glance",
        scope="scenario",
        scenario_name=str(active_scenario["name"]),
    )
    st.caption(
        f"Attach a saved repository requirement within Rev "
        f"{active_scenario['revision_label']} · {active_scenario['name']}. The link "
        "continues to follow the same Process at a Glance step when its Pitch or Seq changes."
    )
else:
    st.subheader("Link to Process at a Glance")
    st.info(
        "Select an active planning scenario before attaching or unlinking Quality requirements."
    )

requirement_labels = {
    str(row["id"]): (
        f"{row['unique_identifier']} — {row['description']}"
    )
    for _, row in requirements.iterrows()
}
selected_requirement_id = st.selectbox(
    "Saved Quality requirement",
    options=list(requirement_labels),
    index=0 if requirement_labels else None,
    placeholder="Choose a saved Quality requirement",
    format_func=lambda requirement_id: requirement_labels.get(
        str(requirement_id), "Unavailable Quality requirement"
    ),
    disabled=not requirement_labels,
    key=f"quality_requirement_link_source_{project_id}",
    help=(
        "Choose a saved project requirement to attach in the active planning scenario. "
        "Unsaved table edits are not available here."
    ),
)

all_requirement_links = quality_requirement_links(project_id)
selected_requirement_links = pd.DataFrame(columns=all_requirement_links.columns)
if selected_requirement_id and not all_requirement_links.empty:
    selected_requirement_links = all_requirement_links.loc[
        all_requirement_links["quality_requirement_id"]
        .astype(str)
        .eq(str(selected_requirement_id))
    ].copy()

if active_scenario and selected_requirement_id:
    process_steps = quality_process_steps(project_id, scenario_id)
    step_labels = {
        str(row["id"]): (
            f"Pitch {str(row.get('pitch') or 'Unassigned')} · "
            f"{str(row.get('pitch_name') or 'No pitch name')} · "
            f"{str(row.get('work_element') or 'Unnamed work element')} · "
            f"{str(row.get('status') or 'No status')} · "
            f"Seq {int(row['sequence']) if pd.notna(row.get('sequence')) else '—'}"
        )
        for _, row in process_steps.iterrows()
    }
    selected_step_id = st.selectbox(
        "Process at a Glance step",
        options=list(step_labels),
        index=None,
        placeholder="Choose a Process at a Glance step",
        format_func=lambda work_element_id: step_labels.get(
            str(work_element_id), "Unavailable Process at a Glance step"
        ),
        disabled=process_steps.empty,
        key=f"quality_requirement_link_step_{project_id}_{scenario_id}",
        help=(
            "Options come only from the active project and planning scenario. "
            "The permanent internal identifier is never shown or entered."
        ),
    )
    active_links = selected_requirement_links.loc[
        selected_requirement_links.get(
            "scenario_id", pd.Series(dtype="string")
        ).astype(str).eq(scenario_id)
    ].copy()
    assigned_step_ids = set(
        active_links.get("work_element_id", pd.Series(dtype="string")).astype(str)
    )
    already_linked = bool(
        selected_step_id and str(selected_step_id) in assigned_step_ids
    )
    if process_steps.empty:
        st.info(
            "This scenario has no Process at a Glance steps available to receive a Quality requirement."
        )
    elif already_linked:
        st.info(
            "This Quality requirement is already linked to the selected Process at a Glance step."
        )
    if has_unsaved_edits:
        st.info(
            "Save or undo repository table edits before attaching or unlinking a requirement."
        )

    if st.button(
        "Attach to Process at a Glance step",
        type="primary",
        icon=":material/link:",
        disabled=(
            not selected_step_id or already_linked or has_unsaved_edits
        ),
        key=f"quality_requirement_attach_{project_id}_{scenario_id}",
    ):
        try:
            assignment_id = assign_quality_requirement(
                project_id,
                scenario_id,
                str(selected_step_id),
                str(selected_requirement_id),
            )
            record_audit_event(
                project_id,
                "Quality requirements",
                "Attach to Process step",
                1,
                st.session_state.get("current_editor", ""),
                {
                    "assignment_id": assignment_id,
                    "scenario_id": scenario_id,
                    "quality_requirement_id": str(selected_requirement_id),
                    "unique_identifier": requirement_labels[str(selected_requirement_id)].split(
                        " — ", 1
                    )[0],
                    "work_element_id": str(selected_step_id),
                    "process_step": step_labels[str(selected_step_id)],
                },
            )
            st.toast(
                "Quality requirement attached to the Process at a Glance step",
                icon=":material/check_circle:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    unlink_labels = {
        str(row["assignment_id"]): (
            f"Pitch {str(row.get('pitch') or 'Unassigned')} · "
            f"{str(row.get('pitch_name') or 'No pitch name')} · "
            f"{str(row.get('work_element') or 'Unnamed work element')} · "
            f"Seq {int(row['sequence']) if pd.notna(row.get('sequence')) else '—'}"
        )
        for _, row in active_links.iterrows()
    }
    selected_assignment_id = st.selectbox(
        "Linked Process at a Glance step to unlink",
        options=list(unlink_labels),
        index=None,
        placeholder="Choose an existing link",
        format_func=lambda assignment_id: unlink_labels.get(
            str(assignment_id), "Unavailable linked Process at a Glance step"
        ),
        disabled=not unlink_labels,
        key=f"quality_requirement_unlink_assignment_{project_id}_{scenario_id}",
        help=(
            "Unlinking removes only this scenario-specific connection. It preserves "
            "the repository requirement and the Process at a Glance step."
        ),
    )
    if st.button(
        "Unlink selected Process at a Glance step",
        icon=":material/link_off:",
        disabled=not selected_assignment_id or has_unsaved_edits,
        key=f"quality_requirement_request_unlink_{project_id}_{scenario_id}",
    ):
        try:
            selected_assignment_id = str(selected_assignment_id)
            if selected_assignment_id not in unlink_labels:
                raise ValueError(
                    "That Quality requirement assignment is not available in the active scenario."
                )
            selected_assignment = quality_requirement_assignment(
                project_id, selected_assignment_id
            )
            if str(selected_assignment["quality_requirement_id"]) != str(
                selected_requirement_id
            ):
                raise ValueError(
                    "That assignment does not belong to the selected Quality requirement."
                )
            st.session_state[pending_unlink_key] = {
                "assignment_id": selected_assignment_id,
                "scenario_id": str(selected_assignment["scenario_id"]),
                "quality_requirement_id": str(selected_requirement_id),
                "requirement": requirement_labels[str(selected_requirement_id)],
                "process_step": unlink_labels[selected_assignment_id],
                "pfmea_impact": quality_assignment_pfmea_impact(
                    project_id,
                    str(selected_assignment["scenario_id"]),
                    [selected_assignment_id],
                ),
            }
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Unlink Quality requirement?", dismissible=False)
def confirm_quality_requirement_unlink() -> None:
    pending = st.session_state.get(pending_unlink_key, {})
    st.warning(
        f"Unlink {pending.get('requirement', 'this Quality requirement')} from "
        f"{pending.get('process_step', 'the selected Process at a Glance step')}?"
    )
    st.write(
        "Only this scenario-specific link will be removed. The saved Quality requirement "
        "and Process at a Glance step will be preserved."
    )
    pfmea_impact = pending.get("pfmea_impact") or {}
    if int(pfmea_impact.get("selection_count", 0)):
        st.warning(
            f"This also removes {pfmea_impact['selection_count']} dependent structured "
            f"PFMEA control selection(s) from {pfmea_impact.get('cause_count', 0)} Cause(s). "
            "Those Causes will be marked Review required; Detection ratings are preserved."
        )
    scenario_changed = str(pending.get("scenario_id") or "") != scenario_id
    if scenario_changed:
        st.error(
            "The active planning scenario changed. Cancel and choose the link again."
        )
    actions = st.container(horizontal=True)
    if actions.button(
        "Cancel", key=f"cancel_quality_requirement_unlink_{project_id}"
    ):
        st.session_state.pop(pending_unlink_key, None)
        st.rerun()
    if actions.button(
        "Unlink",
        type="primary",
        icon=":material/link_off:",
        disabled=scenario_changed,
        key=(
            f"destructive_confirm_quality_requirement_unlink_{project_id}_"
            f"{pending.get('assignment_id', 'missing')}"
        ),
    ):
        try:
            deleted_count = delete_quality_requirement_assignments(
                project_id,
                str(pending["scenario_id"]),
                [str(pending["assignment_id"])],
            )
            record_audit_event(
                project_id,
                "Quality requirements",
                "Unlink from Process step",
                deleted_count,
                st.session_state.get("current_editor", ""),
                pending,
            )
            if int(pfmea_impact.get("selection_count", 0)):
                record_audit_event(
                    project_id,
                    "PFMEA",
                    "Quality assignment unlink cascade",
                    int(pfmea_impact["selection_count"]),
                    st.session_state.get("current_editor", ""),
                    {
                        "scenario_id": pending["scenario_id"],
                        "quality_requirement_assignment_id": pending["assignment_id"],
                        "cause_count": pfmea_impact.get("cause_count", 0),
                    },
                )
            st.session_state.pop(pending_unlink_key, None)
            st.toast(
                "Quality requirement unlinked from the Process at a Glance step",
                icon=":material/check_circle:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


if st.session_state.get(pending_unlink_key):
    confirm_quality_requirement_unlink()

with st.expander(
    "View Quality requirements linked to Process steps",
    icon=":material/account_tree:",
):
    st.caption(
        "Each row shows the published requirement values attached to one Process at a "
        "Glance step across every planning scenario in this project."
    )
    if all_requirement_links.empty:
        st.caption(
            "No Quality requirements are linked to Process at a Glance steps in this project."
        )
    else:
        linked_steps = all_requirement_links.copy()
        linked_steps["scenario"] = linked_steps.apply(
            lambda row: f"Rev {row['scenario_revision']} · {row['scenario_name']}",
            axis=1,
        )
        linked_steps = linked_steps.rename(
            columns={
                "pitch": "Pitch",
                "pitch_name": "Pitch Name",
                "work_element": "Work Element",
                "status": "Status",
                "sequence": "Seq",
                "scenario": "Scenario",
                "unique_identifier": "Quality requirement Unique identifier",
                "requirement_type": "Type",
                "description": "Description",
                "pass_fail": "Pass/fail",
                "target_value": "Target value",
                "tolerances": "Tolerances",
                "unit": "Unit",
                "repository_update_pending": "Repository update pending",
            }
        )
        linked_steps["Pass/fail"] = linked_steps["Pass/fail"].fillna(0).astype(bool)
        linked_steps["Repository update pending"] = (
            linked_steps["Repository update pending"].fillna(0).astype(bool)
        )
        linked_step_rows = linked_steps.reindex(
            columns=[
                "Scenario", "Pitch", "Pitch Name", "Work Element", "Status", "Seq",
                "Quality requirement Unique identifier", "Type", "Description", "Pass/fail",
                "Target value", "Tolerances", "Unit", "Repository update pending",
            ]
        )
        visible_linked_steps = filter_table(
            linked_step_rows,
            key=f"quality_requirement_linked_step_filters_{project_id}",
            dropdown_columns=[
                "Scenario", "Pitch", "Work Element",
                "Quality requirement Unique identifier", "Type",
                "Status", "Repository update pending",
            ],
            search_columns=[
                "Scenario", "Pitch", "Pitch Name", "Work Element", "Status",
                "Quality requirement Unique identifier", "Type", "Description",
                "Tolerances", "Unit",
            ],
            labels={
                "Quality requirement Unique identifier": "Quality requirement",
            },
        )
        selectable_dataframe(
            visible_linked_steps,
            key=f"quality_requirement_linked_steps_{project_id}",
            hide_index=True,
            column_config={
                "Scenario": st.column_config.TextColumn("Scenario", pinned=True),
                "Pitch": st.column_config.TextColumn("Pitch", pinned=True),
                "Pitch Name": st.column_config.TextColumn("Pitch Name"),
                "Work Element": st.column_config.TextColumn("Work Element", width="large"),
                "Status": st.column_config.TextColumn("Status"),
                "Seq": st.column_config.NumberColumn("Seq", format="%d"),
                "Quality requirement Unique identifier": st.column_config.TextColumn(
                    "Quality requirement Unique identifier",
                    pinned=True,
                    help="The published Unique identifier currently attached to this Process step.",
                ),
                "Type": st.column_config.TextColumn("Type"),
                "Description": st.column_config.TextColumn("Description", width="large"),
                "Pass/fail": st.column_config.CheckboxColumn("Pass/fail"),
                "Target value": st.column_config.NumberColumn("Target value"),
                "Tolerances": st.column_config.TextColumn("Tolerances"),
                "Unit": st.column_config.TextColumn("Unit"),
                "Repository update pending": st.column_config.CheckboxColumn(
                    "Repository update pending",
                    help=(
                        "Shows that the saved repository definition differs from the "
                        "published values currently attached to this Process step."
                    ),
                ),
            },
        )

pending_push = requirements.loc[
    requirements["pending_assignment_count"].fillna(0).astype(int) > 0
].copy()
st.subheader("Publish saved updates")
st.caption(
    "Publishing replaces linked Process requirement copies with the currently saved "
    "repository values. Unsaved table edits are never published."
)
push_updates = st.button(
    "Push saved updates to linked Process steps",
    type="primary",
    icon=":material/publish:",
    disabled=pending_push.empty or has_unsaved_edits,
    help=(
        "Review and publish every saved repository definition that has older values "
        "on linked Process at a Glance steps."
    ),
)
if has_unsaved_edits and not pending_push.empty:
    st.info("Save or undo the current table edits before publishing saved updates.")
elif pending_push.empty:
    st.caption("All linked Process requirements already match the saved repository.")

if push_updates:
    st.session_state[pending_push_key] = [
        {
            "id": str(row["id"]),
            "unique_identifier": str(row["unique_identifier"]),
            "pending_assignment_count": int(row["pending_assignment_count"]),
        }
        for _, row in pending_push.iterrows()
    ]


@st.dialog("Push saved Quality requirement updates?", dismissible=False)
def confirm_quality_requirement_push() -> None:
    pending = st.session_state.get(pending_push_key, [])
    affected_count = sum(int(item["pending_assignment_count"]) for item in pending)
    st.warning(
        f"Update {affected_count} linked Process requirement(s) with the "
        "saved repository values?"
    )
    for item in pending:
        st.write(
            f"- {item['unique_identifier']} — "
            f"{item['pending_assignment_count']} linked update(s)"
        )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_quality_requirement_push_{project_id}"):
        st.session_state.pop(pending_push_key, None)
        st.rerun()
    if actions.button(
        "Push updates", type="primary", icon=":material/publish:",
        key=f"confirm_quality_requirement_push_{project_id}",
    ):
        try:
            requirement_ids = [item["id"] for item in pending]
            updated_count = push_quality_requirements(project_id, requirement_ids)
            record_audit_event(
                project_id, "Quality requirements", "Push to linked Process steps",
                updated_count, st.session_state.get("current_editor", ""),
                {
                    "requirement_ids": requirement_ids,
                    "unique_identifiers": [item["unique_identifier"] for item in pending],
                },
            )
            st.session_state.pop(pending_push_key, None)
            request_table_editor_reset(editor_key)
            st.toast(
                f"Updated {updated_count} linked Process requirement(s)",
                icon=":material/check_circle:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


if st.session_state.get(pending_push_key):
    confirm_quality_requirement_push()

requirements_repository_tab.__exit__(None, None, None)
render_quality_history(project_id)
