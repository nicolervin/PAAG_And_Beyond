from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.scope_ui import page_title_with_scope
from utils.store import (
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
    native_selected_rows,
    selectable_dataframe,
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

editable_table_heading("Safety requirements")
st.caption(
    "Active requirements create the read-only Safety indicator on linked Process at a Glance "
    "and Yamazumi work. Deactivating a requirement preserves its history while removing that indicator."
)
visible = filter_table(
    saved,
    key=f"safety_requirements_filters_{project_id}_{scenario_id}",
    dropdown_columns=["active", "pitch"],
    search_columns=["work_element_label", "pitch", "requirement_description"],
    labels={"active": "Active", "pitch": "Pitch"},
    reset_widget_keys=[editor_key],
)
editor_rows = direct_entry_editor_rows(
    visible,
    editor_key=editor_key,
    sort_columns=["pitch", "work_element_label", "requirement_description", "active"],
    labels={
        "work_element_label": "Process Function",
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
        "id", "project_id", "scenario_id", "work_element_label", "pitch",
        "created_at", "updated_at",
    ],
    column_order=["work_element_id", "requirement_description", "active"],
    column_config={
        "id": None,
        "project_id": None,
        "scenario_id": None,
        "work_element_id": st.column_config.SelectboxColumn(
            "Process Function",
            options=list(work_labels),
            format_func=lambda value: work_labels.get(str(value), "Unavailable Process Function"),
            required=True,
            width="large",
            help="Choose the Process step where this Safety requirement applies.",
        ),
        "requirement_description": st.column_config.TextColumn(
            "Requirement description",
            required=True,
            width="large",
            help="Describe the condition or requirement that makes this Process step safety-critical.",
        ),
        "active": st.column_config.CheckboxColumn(
            "Active",
            default=True,
            help="Only active requirements create the Safety indicator on linked Process work.",
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
st.download_button(
    "Export filtered",
    data=dataframe_to_excel(
        visible[["pitch", "work_element_label", "requirement_description", "active"]].rename(
            columns={
                "pitch": "Pitch",
                "work_element_label": "Process Function",
                "requirement_description": "Requirement description",
                "active": "Active",
            }
        ),
        "Safety requirements",
    ),
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
    request_table_editor_reset(editor_key)
    st.rerun()

if footer.save_and_refresh:
    try:
        if not selected.empty:
            raise ValueError("Clear selected rows before saving Safety requirement edits.")
        edited = drop_untouched_new_rows(
            edited,
            identifying_columns=["work_element_id", "requirement_description"],
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
                    "When", format="MMM DD, YYYY HH:mm"
                ),
            },
        )
