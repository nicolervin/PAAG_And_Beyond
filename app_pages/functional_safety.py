from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.equipment_ui import render_functional_equipment_tab
from utils.scope_ui import page_title_with_scope
from utils.store import (
    STANDARD_PPE_OPTIONS,
    acknowledge_safety_upstream_changes,
    delete_safety_requirements,
    ergonomics_work_elements,
    get_planning_scenario,
    safety_requirement_history,
    safety_requirements,
    save_safety_requirements,
)
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
    guarded_tabs,
    native_selected_rows,
    selectable_dataframe,
    selected_dataframe_rows,
    stage_native_delete_confirmation,
)


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


project_id = _text(st.session_state.get("project_id"))
scenario_id = _text(st.session_state.get("scenario_id"))
scenario = get_planning_scenario(project_id, scenario_id) if project_id and scenario_id else None

page_title_with_scope(
    "Safety", scope="scenario", scenario_name=_text((scenario or {}).get("name"))
)
st.caption(
    "Record active Safety requirements against Process at a Glance steps in the current planning scenario."
)
if not project_id or not scenario:
    st.info("Select an active planning scenario to manage Safety requirements.")
    st.stop()

review_tab, equipment_tab = guarded_tabs(
    ["Review", "Equipment"],
    key=f"safety_page_tabs_{project_id}",
)
if equipment_tab.open:
    with equipment_tab:
        render_functional_equipment_tab(project_id, scenario_id, "Safety")
    st.stop()
review_tab.__enter__()

logical_editor_key = f"safety_requirements_editor_{project_id}_{scenario_id}"
editor_key = apply_pending_table_editor_reset(logical_editor_key)
pending_delete_key = f"safety_requirements_pending_delete_{project_id}_{scenario_id}"

saved = safety_requirements(project_id, scenario_id).copy()
work_elements = ergonomics_work_elements(project_id, scenario_id)
work_labels = {
    _text(row["id"]): " — ".join(
        value
        for value in [_text(row["pitch"]) or "Unassigned", _text(row["work_element_label"])]
        if value
    )
    for _, row in work_elements.iterrows()
}

# Aggregate all standard PPE options plus any previously recorded custom PPE
ppe_options = list(dict.fromkeys([
    *STANDARD_PPE_OPTIONS,
    *[
        str(item).strip()
        for ppe_list in saved.get("ppe", [])
        if isinstance(ppe_list, (list, tuple, set))
        for item in ppe_list
        if str(item).strip()
    ]
]))

editable_table_heading("Safety requirements")
st.caption(
    "Assign required PPE and document safety requirements per Process step. "
    "Work elements without assigned PPE trigger a Safety Alert on the Process at a Glance slide."
)
if "sync_status" not in saved.columns:
    saved["sync_status"] = "Synced"
if "upstream_changed" not in saved.columns:
    saved["upstream_changed"] = False
if "upstream_diff_summary" not in saved.columns:
    saved["upstream_diff_summary"] = ""

changed_safety = saved[saved["upstream_changed"].fillna(False).astype(bool)].copy()
filter_changed_only = False
if not changed_safety.empty:
    with st.container(border=True):
        q_head_col, q_toggle_col = st.columns([3, 1.3], vertical_alignment="center")
        with q_head_col:
            st.markdown(f"**⚠️ Upstream Process changes to review ({len(changed_safety)})**")
            st.caption(
                "These Process at a Glance steps were edited upstream after their Safety "
                "requirement was saved. Select rows below to **Acknowledge** that your existing "
                "PPE/requirement still stands, or **Edit** the rows in the main table and click "
                "**Save & Refresh** to update and clear the flag automatically."
            )
        with q_toggle_col:
            filter_changed_only = st.toggle(
                "Filter main table to changed rows",
                key=f"safety_filter_upstream_changed_{scenario_id}",
            )
        ack_queue_df = changed_safety[
            [
                "id",
                "pitch",
                "work_element_label",
                "upstream_diff_summary",
                "ppe",
                "requirement_description",
                "active",
            ]
        ].copy()
        ack_queue_df["ppe"] = [
            ", ".join(p) if isinstance(p, list) else str(p or "")
            for p in ack_queue_df["ppe"]
        ]
        ack_event = selectable_dataframe(
            ack_queue_df,
            key=f"safety_upstream_ack_queue_{project_id}_{scenario_id}",
            hide_index=True,
            width="stretch",
            column_config={
                "id": None,
                "pitch": st.column_config.TextColumn("Pitch", width="small"),
                "work_element_label": st.column_config.TextColumn(
                    "Process Function", width="medium"
                ),
                "upstream_diff_summary": st.column_config.TextColumn(
                    "Upstream Process changes (since last review)", width="large"
                ),
                "ppe": st.column_config.TextColumn("Assigned PPE", width="medium"),
                "requirement_description": st.column_config.TextColumn(
                    "Requirement description", width="medium"
                ),
                "active": st.column_config.CheckboxColumn("Active", width="small"),
            },
        )
        selected_ack_rows = selected_dataframe_rows(
            ack_queue_df, ack_event, id_column="id"
        )
        ack_bar = st.container(horizontal=True, vertical_alignment="center")
        if ack_bar.button(
            f"Acknowledge selected ({len(selected_ack_rows)})",
            type="primary",
            icon=":material/task_alt:",
            disabled=selected_ack_rows.empty,
            key=f"safety_ack_upstream_btn_{project_id}_{scenario_id}",
        ):
            try:
                ack_res = acknowledge_safety_upstream_changes(
                    project_id,
                    scenario_id,
                    selected_ack_rows["id"].astype(str).tolist(),
                    editor_name=_text(st.session_state.get("current_editor")) or "Collaborator",
                )
                request_table_editor_reset(editor_key)
                st.toast(
                    f"Acknowledged upstream Process changes for {ack_res['row_count']} Safety requirement(s)",
                    icon=":material/task_alt:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

visible = filter_table(
    saved,
    key=f"safety_requirements_filters_{project_id}_{scenario_id}",
    dropdown_columns=["sync_status", "active", "pitch"],
    search_columns=[
        "work_element_label",
        "pitch",
        "requirement_description",
        "upstream_diff_summary",
    ],
    labels={"sync_status": "Sync status", "active": "Active", "pitch": "Pitch"},
    reset_widget_keys=[editor_key],
)
if filter_changed_only:
    visible = visible[visible["upstream_changed"].fillna(False).astype(bool)].copy()
editor_rows = direct_entry_editor_rows(
    visible,
    editor_key=editor_key,
    sort_columns=["pitch", "work_element_label", "requirement_description", "active"],
    labels={
        "work_element_label": "Process Function",
        "ppe": "Assigned PPE",
        "requirement_description": "Requirement description",
    },
)
edited = st.data_editor(
    editor_rows,
    key=editor_key,
    hide_index=True,
    num_rows="dynamic",
    height=420,
    disabled=[
        "id",
        "project_id",
        "scenario_id",
        "sync_status",
        "upstream_changed",
        "upstream_diff_summary",
        "source_snapshot_json",
        "source_acknowledged_at",
        "work_element_label",
        "pitch",
        "created_at",
        "updated_at",
    ],
    column_order=[
        "sync_status",
        "work_element_id",
        "upstream_diff_summary",
        "ppe",
        "requirement_description",
        "active",
    ],
    column_config={
        "id": None,
        "project_id": None,
        "scenario_id": None,
        "upstream_changed": None,
        "source_snapshot_json": None,
        "source_acknowledged_at": None,
        "sync_status": st.column_config.TextColumn(
            "Sync status",
            width="small",
            help="Shows whether the linked Process at a Glance step changed upstream since this requirement was last saved or acknowledged.",
        ),
        "work_element_id": st.column_config.SelectboxColumn(
            "Process Function",
            options=list(work_labels),
            format_func=lambda value: work_labels.get(str(value), "Unavailable Process Function"),
            required=True,
            width="large",
            help="Choose the Process step where this Safety requirement or PPE applies.",
        ),
        "upstream_diff_summary": st.column_config.TextColumn(
            "Upstream changes",
            width="large",
            help="Summary of upstream Process at a Glance step changes since this requirement was last saved or acknowledged.",
        ),
        "ppe": st.column_config.MultiselectColumn(
            "Assigned PPE",
            options=ppe_options,
            width="large",
            help="Select Personal Protective Equipment required for this Process step.",
        ),
        "requirement_description": st.column_config.TextColumn(
            "Requirement description",
            required=False,
            width="large",
            help="Describe specific hazards or safety requirements (auto-filled if only PPE is selected).",
        ),
        "active": st.column_config.CheckboxColumn(
            "Active",
            default=True,
            help="Only active requirements and PPE satisfy safety compliance and appear on Process work.",
        ),
        "work_element_label": None,
        "pitch": None,
        "created_at": None,
        "updated_at": None,
    },
)
footer = editable_table_footer(
    editor_key=editor_key,
    key_prefix=f"safety_requirements_{project_id}_{scenario_id}",
    native_row_selection=True,
)
def _export_safety_bytes() -> bytes:
    export_df = visible[["pitch", "work_element_label", "ppe", "requirement_description", "active"]].copy()
    export_df["ppe"] = [
        ", ".join(p) if isinstance(p, list) else str(p or "")
        for p in export_df["ppe"]
    ]
    return dataframe_to_excel(
        export_df.rename(
            columns={
                "pitch": "Pitch",
                "work_element_label": "Process Function",
                "ppe": "Assigned PPE",
                "requirement_description": "Requirement description",
                "active": "Active",
            }
        ),
        "Safety requirements",
    )


st.download_button(
    "Export filtered",
    data=_export_safety_bytes,
    file_name="safety_requirements_filtered.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    icon=":material/download:",
)

selected = native_selected_rows(editor_rows, editor_key=editor_key)
if not selected.empty:
    st.session_state[pending_delete_key] = [
        {
            "id": _text(row["id"]),
            "process_function": work_labels.get(
                _text(row["work_element_id"]), _text(row["work_element_label"])
            ),
            "description": _text(row["requirement_description"]),
        }
        for _, row in selected.iterrows()
        if _text(row.get("id"))
    ]
    stage_native_delete_confirmation(editor_key)


@st.dialog("Delete selected Safety requirements?", dismissible=False)
def confirm_delete() -> None:
    pending = list(st.session_state.get(pending_delete_key) or [])
    st.warning(
        f"Delete {len(pending)} selected Safety requirement(s)? The Safety indicator "
        "will disappear when no other active requirement remains for the Process step."
    )
    for item in pending:
        st.write(f"- {item['process_function']} — {item['description']}")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_safety_delete_{scenario_id}"):
        st.session_state.pop(pending_delete_key, None)
        request_table_editor_reset(editor_key)
        st.rerun()
    if actions.button(
        "Delete requirements",
        type="primary",
        icon=":material/delete:",
        key=f"destructive_confirm_safety_delete_{scenario_id}",
    ):
        try:
            result = delete_safety_requirements(
                project_id,
                scenario_id,
                [item["id"] for item in pending],
                _text(st.session_state.get("current_editor")),
            )
            st.session_state.pop(pending_delete_key, None)
            request_table_editor_reset(editor_key)
            st.toast(
                f"Deleted {result['row_count']} Safety requirement(s)",
                icon=":material/delete:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


if st.session_state.get(pending_delete_key):
    confirm_delete()

if footer.undo:
    st.toast("Discarded the unsaved Safety requirement edits", icon=":material/undo:")
    request_table_editor_reset(editor_key)
    st.rerun()

if footer.save_and_refresh:
    try:
        if not selected.empty:
            raise ValueError("Clear selected rows before saving Safety requirement edits.")
        edited = drop_untouched_new_rows(
            edited,
            identifying_columns=["work_element_id", "requirement_description", "ppe"],
        )
        combined = merge_filtered_edits(saved, visible, edited)
        result = save_safety_requirements(
            project_id,
            scenario_id,
            combined,
            _text(st.session_state.get("current_editor")),
        )
        request_table_editor_reset(editor_key)
        st.toast(
            f"Saved {result['row_count']} Safety requirement change(s)",
            icon=":material/check_circle:",
        )
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

with st.expander("History", icon=":material/history:"):
    history = safety_requirement_history(project_id, scenario_id)
    if history.empty:
        st.caption("No Safety requirement history has been recorded yet.")
    else:
        selectable_dataframe(
            history.drop(columns=["details"], errors="ignore"),
            key=f"safety_requirement_history_{project_id}_{scenario_id}",
            hide_index=True,
            column_config={
                "action": "Action",
                "row_count": "Rows",
                "editor_name": "Editor",
                "created_at": st.column_config.DatetimeColumn(
                    "When", format="MMM DD, YYYY HH:mm", timezone="America/New_York"
                ),
            },
        )
