import pandas as pd
import streamlit as st

from utils.store import project_table, record_audit_event, replace_concerns
from utils.scope_ui import page_title_with_scope
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
)
from utils.table_ui import (
    drop_untouched_new_rows,
    editable_table_footer,
    editable_table_heading,
    native_selected_rows,
    direct_entry_editor_rows,
)


project_id = st.session_state.get("project_id")
editor_key = "concerns_editor"
pending_delete_key = f"concerns_pending_delete_{project_id}"
page_title_with_scope("Questions and concerns", scope="project")
st.caption("Keep unresolved assumptions and cross-functional decisions visible as the process changes.")
if not project_id:
    st.stop()
apply_pending_table_editor_reset(editor_key)

concerns = project_table("concerns", project_id, "created_at DESC")
columns = ["id", "category", "subject", "detail", "owner", "priority", "status", "related_part", "related_station", "created_at"]
if concerns.empty:
    concerns = pd.DataFrame(
        {
            "id": pd.Series(dtype="string"),
            "category": pd.Series(dtype="string"),
            "subject": pd.Series(dtype="string"),
            "detail": pd.Series(dtype="string"),
            "owner": pd.Series(dtype="string"),
            "priority": pd.Series(dtype="string"),
            "status": pd.Series(dtype="string"),
            "related_part": pd.Series(dtype="string"),
            "related_station": pd.Series(dtype="string"),
            "created_at": pd.Series(dtype="string"),
        }
    )
else:
    concerns = concerns.reindex(columns=columns)

editable_table_heading("Questions and concerns")

visible_concerns = filter_table(
    concerns,
    key="concerns_filters",
    dropdown_columns=["category", "priority", "status", "owner"],
    search_columns=["subject", "detail", "owner", "related_part", "related_station"],
    reset_widget_keys=[editor_key],
)
concerns_for_editing = direct_entry_editor_rows(
    visible_concerns,
    editor_key=editor_key,
    sort_columns=[
        "category", "subject", "priority", "status", "owner",
        "related_part", "related_station", "created_at",
    ],
)
edited = st.data_editor(
    concerns_for_editing, key=editor_key, num_rows="dynamic", hide_index=True, height=430,
    disabled=["id", "created_at"], column_order=[column for column in columns if column != "id"],
    column_config={
        "id": None,
        "category": st.column_config.SelectboxColumn(
            options=["Question", "Concern", "Decision", "Assumption"],
            default="Question",
        ),
        "subject": st.column_config.TextColumn(required=True, pinned=True),
        "detail": st.column_config.TextColumn(width="large"),
        "priority": st.column_config.SelectboxColumn(
            options=["Low", "Medium", "High", "Critical"], default="Medium"
        ),
        "status": st.column_config.SelectboxColumn(
            options=["Open", "Investigating", "Waiting", "Resolved", "Closed"],
            default="Open",
        ),
        "created_at": st.column_config.DatetimeColumn("Created", format="MMM DD, YYYY HH:mm"),
    },
)
footer_actions = editable_table_footer(
    editor_key=editor_key,
    key_prefix="concerns",
    native_row_selection=True,
)
if footer_actions.undo:
    request_table_editor_reset(editor_key)
    st.rerun()


def clean_text(value: object) -> str:
    """Normalize nullable table values for user-facing summaries."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def concern_summary(row: pd.Series | dict) -> str:
    """Return a short, stable description for confirmations and audit details."""
    concern_id = clean_text(row.get("id"))
    category = clean_text(row.get("category")) or "Concern"
    subject = clean_text(row.get("subject"))
    detail = clean_text(row.get("detail"))
    label = subject or detail[:80] or "Untitled concern"
    return f"{category}: {label} (ID: {concern_id})"


def pending_edit_summaries(excluded_ids: set[str] | None = None) -> list[str]:
    """Describe unsaved row edits without treating native row selection as an edit."""
    excluded_ids = excluded_ids or set()
    state = st.session_state.get(editor_key, {}) or {}
    summaries: list[str] = []
    for raw_position, changes in (state.get("edited_rows") or {}).items():
        position = int(raw_position)
        if not 0 <= position < len(concerns_for_editing):
            continue
        row = concerns_for_editing.iloc[position].to_dict()
        row.update(changes or {})
        concern_id = clean_text(row.get("id"))
        if concern_id and concern_id in excluded_ids:
            continue
        summaries.append(concern_summary(row))
    for row in state.get("added_rows") or []:
        summaries.append(concern_summary(row))
    return list(dict.fromkeys(summaries))


def current_editor_rows() -> pd.DataFrame:
    """Rebuild the current editor draft, including edits and native selections."""
    state = st.session_state.get(editor_key, {}) or {}
    draft = concerns_for_editing.copy()
    for raw_position, changes in (state.get("edited_rows") or {}).items():
        position = int(raw_position)
        if not 0 <= position < len(draft):
            continue
        for column, value in (changes or {}).items():
            if column in draft.columns:
                draft.at[draft.index[position], column] = value
    selected_positions = {
        int(position)
        for position in state.get("deleted_rows") or []
        if 0 <= int(position) < len(draft)
    }
    if selected_positions:
        draft = draft.iloc[
            [position for position in range(len(draft)) if position not in selected_positions]
        ].copy()
    added_rows = state.get("added_rows") or []
    if added_rows:
        draft = pd.concat(
            [draft, pd.DataFrame(added_rows, columns=draft.columns)],
            ignore_index=True,
            sort=False,
        )
    return draft.reset_index(drop=True)


selected_concerns = native_selected_rows(
    concerns_for_editing,
    editor_key=editor_key,
)
request_delete = not selected_concerns.empty
if request_delete:
    pending_concerns = [
        {
            "id": str(row["id"]),
            "summary": concern_summary(row),
        }
        for _, row in selected_concerns.iterrows()
    ]
    pending_ids = {item["id"] for item in pending_concerns}
    st.session_state[pending_delete_key] = {
        "concerns": pending_concerns,
        "draft_rows": current_editor_rows().to_dict("records"),
        "other_edits": pending_edit_summaries(pending_ids),
    }


@st.dialog("Delete selected concerns?")
def confirm_concern_delete() -> None:
    pending_state = st.session_state.get(pending_delete_key, {})
    pending = pending_state.get("concerns", [])
    pending_ids = {str(item["id"]) for item in pending}
    st.warning(
        f"Delete {len(pending)} selected concern(s)? Only the concerns listed below will be deleted."
    )
    for item in pending:
        st.write(f"- {item['summary']}")
    other_edits = pending_state.get("other_edits", [])
    if other_edits:
        st.info(
            "Other unsaved table edits will be saved at the same time so they are not lost."
        )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_concerns_bulk_delete"):
        st.session_state.pop(pending_delete_key, None)
        request_table_editor_reset(editor_key)
        st.rerun()
    if actions.button(
        "Delete",
        type="primary",
        icon=":material/delete:",
        key="destructive_confirm_concerns_bulk_delete",
    ):
        draft_rows = pd.DataFrame(
            pending_state.get("draft_rows", []),
            columns=concerns_for_editing.columns,
        )
        remaining_edits = drop_untouched_new_rows(
            draft_rows,
            identifying_columns=["subject"],
        )
        combined_concerns = merge_filtered_edits(
            concerns,
            visible_concerns,
            remaining_edits,
        )
        combined_concerns = combined_concerns.loc[
            ~combined_concerns["id"].fillna("").astype(str).isin(pending_ids)
        ].copy()
        replace_concerns(project_id, combined_concerns)
        editor_name = st.session_state.get("current_editor", "")
        record_audit_event(
            project_id,
            "Questions and concerns",
            "Bulk delete",
            len(pending),
            editor_name,
            {
                "concern_ids": sorted(pending_ids),
                "concerns": [item["summary"] for item in pending],
            },
        )
        if other_edits:
            record_audit_event(
                project_id,
                "Questions and concerns",
                "Save & Refresh",
                len(other_edits),
                editor_name,
                {"concerns": other_edits, "saved_with_bulk_delete": True},
            )
        st.session_state.pop(pending_delete_key, None)
        request_table_editor_reset(editor_key)
        st.toast(f"Deleted {len(pending)} concern(s)", icon=":material/delete:")
        st.rerun()


if st.session_state.get(pending_delete_key):
    confirm_concern_delete()

if footer_actions.save_and_refresh:
    if not selected_concerns.empty:
        st.warning("Clear selected rows before saving concern edits.")
    else:
        edited = drop_untouched_new_rows(edited, identifying_columns=["subject"])
        combined_concerns = merge_filtered_edits(concerns, visible_concerns, edited)
        changed_concerns = pending_edit_summaries()
        replace_concerns(project_id, combined_concerns)
        record_audit_event(
            project_id,
            "Questions and concerns",
            "Save & Refresh",
            len(changed_concerns),
            st.session_state.get("current_editor", ""),
            {"concerns": changed_concerns},
        )
        request_table_editor_reset(editor_key)
        st.toast("Questions and concerns saved", icon=":material/check_circle:")
        st.rerun()
