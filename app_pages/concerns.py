import pandas as pd
import streamlit as st

from utils.store import (
    CONCERN_CATEGORIES,
    CONCERN_STATUSES,
    audit_history,
    get_project,
    project_table,
    record_audit_event,
    replace_concerns,
)
from utils.scope_ui import page_title_with_scope
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
)
from utils.table_ui import (
    direct_entry_editor_rows,
    drop_untouched_new_rows,
    editable_table_footer,
    editable_table_heading,
    native_selected_rows,
    render_audit_history_table, selectable_dataframe,
    stage_native_delete_confirmation,
)


project_id = st.session_state.get("project_id")
current_editor = (
    str(st.session_state.get("current_editor", "") or "").strip()
    or str(st.session_state.get(f"editor_value_{project_id}", "") or "").strip()
)
if not current_editor and project_id:
    project_row = get_project(project_id) or {}
    current_editor = str(project_row.get("owner", "") or "").strip()
editor_key = f"concerns_editor_{project_id}"
pending_delete_key = f"concerns_pending_delete_{project_id}"
page_title_with_scope("Questions and concerns", scope="project")
st.caption("Keep unresolved questions, concerns, and cross-functional resolutions visible as the process changes.")
if not project_id:
    st.stop()
editor_key = apply_pending_table_editor_reset(editor_key)

raw_concerns = project_table("concerns", project_id, "created_at DESC")
columns = [
    "id",
    "category",
    "detail",
    "owner",
    "priority",
    "status",
    "comments",
    "resolution_comments",
    "submitted_by",
    "created_at",
    "updated_at",
]
column_labels = {
    "category": "Category",
    "detail": "Description",
    "owner": "Owner",
    "priority": "Priority",
    "status": "Status",
    "comments": "Comments",
    "resolution_comments": "Resolution comments",
    "submitted_by": "Submitted by",
    "created_at": "Created",
    "updated_at": "Updated",
}
if raw_concerns.empty:
    concerns = pd.DataFrame(
        {col: pd.Series(dtype="string") for col in columns}
    )
else:
    concerns = raw_concerns.copy()
    if "detail" in concerns.columns and "subject" in concerns.columns:
        detail_series = concerns["detail"].fillna("").astype(str).str.strip()
        subject_series = concerns["subject"].fillna("").astype(str).str.strip()
        concerns["detail"] = detail_series.where(detail_series != "", subject_series)
    concerns = concerns.reindex(columns=columns)
    for col in columns:
        concerns[col] = concerns[col].fillna("").astype("string")
    valid_categories = set(CONCERN_CATEGORIES)
    concerns["category"] = concerns["category"].map(
        lambda val: val if str(val).strip() in valid_categories else "Other"
    ).astype("string")
    concerns["status"] = concerns["status"].map(
        lambda val: "Resolved"
        if str(val).strip() == "Closed"
        else (str(val).strip() if str(val).strip() in CONCERN_STATUSES else "Open")
    ).astype("string")
    if current_editor:
        concerns["submitted_by"] = concerns["submitted_by"].map(
            lambda val: str(val).strip() if str(val).strip() else current_editor
        ).astype("string")

editor_state = st.session_state.get(editor_key)
if isinstance(editor_state, dict) and current_editor:
    for added_row in editor_state.get("added_rows") or []:
        if isinstance(added_row, dict) and not str(added_row.get("submitted_by") or "").strip():
            added_row["submitted_by"] = current_editor

total_concerns = int(len(concerns))
open_df = concerns[concerns["status"].str.strip() != "Resolved"] if not concerns.empty else concerns
open_count = int(len(open_df))
resolved_count = int(total_concerns - open_count)
resolved_pct = (resolved_count / total_concerns * 100.0) if total_concerns > 0 else 0.0

critical_open_count = (
    int((open_df["priority"].str.strip() == "Critical").sum())
    if not open_df.empty
    else 0
)
high_open_count = (
    int((open_df["priority"].str.strip() == "High").sum())
    if not open_df.empty
    else 0
)
crit_high_open = critical_open_count + high_open_count

unassigned_open_count = (
    int((open_df["owner"].fillna("").astype(str).str.strip() == "").sum())
    if not open_df.empty
    else 0
)

waiting_count = (
    int((open_df["status"].str.strip() == "Waiting").sum())
    if not open_df.empty
    else 0
)
investigating_count = (
    int((open_df["status"].str.strip() == "Investigating").sum())
    if not open_df.empty
    else 0
)
not_started_count = (
    int((open_df["status"].str.strip() == "Open").sum())
    if not open_df.empty
    else 0
)

open_icon = "🟢" if open_count == 0 else ("🔴" if critical_open_count > 0 else "🟡")
if total_concerns == 0:
    open_delta = "No items logged yet"
    open_delta_color = "off"
elif open_count == 0:
    open_delta = f"All {resolved_count} resolved (100%)"
    open_delta_color = "normal"
else:
    open_delta = f"{resolved_count} of {total_concerns} resolved ({resolved_pct:.0f}%)"
    open_delta_color = "off"

crit_high_icon = (
    "🟢" if crit_high_open == 0 else ("🔴" if critical_open_count > 0 else "🟡")
)
if crit_high_open == 0:
    crit_high_delta = "No high-urgency blockers"
    crit_high_delta_color = "normal"
else:
    crit_high_delta = f"{critical_open_count} critical · {high_open_count} high"
    crit_high_delta_color = "inverse" if critical_open_count > 0 else "off"

unassigned_icon = "🟢" if unassigned_open_count == 0 else "🟡"
if open_count == 0:
    unassigned_delta = "No open items"
    unassigned_delta_color = "off"
elif unassigned_open_count == 0:
    unassigned_delta = "All open items owned"
    unassigned_delta_color = "normal"
else:
    unassigned_delta = "Needs owner assigned"
    unassigned_delta_color = "inverse"

waiting_icon = "🟢" if waiting_count == 0 else "🟡"
waiting_delta = f"{investigating_count} investigating · {not_started_count} open"

if current_editor:
    my_open_df = (
        open_df[
            open_df["owner"].fillna("").astype(str).str.strip().str.lower()
            == current_editor.lower()
        ]
        if not open_df.empty
        else open_df
    )
    my_open_count = int(len(my_open_df))
    my_crit_count = (
        int((my_open_df["priority"].str.strip() == "Critical").sum())
        if not my_open_df.empty
        else 0
    )
    my_high_count = (
        int((my_open_df["priority"].str.strip() == "High").sum())
        if not my_open_df.empty
        else 0
    )
    my_icon = "🟢" if my_open_count == 0 else ("🔴" if my_crit_count > 0 else "🟡")
    my_value_str = f"{my_icon} {my_open_count}"
    if my_open_count == 0:
        my_delta = f"0 open for {current_editor}"
        my_delta_color = "normal"
    else:
        my_delta = f"{my_crit_count} critical, {my_high_count} high · {current_editor}"
        my_delta_color = "inverse" if my_crit_count > 0 else "off"
else:
    my_value_str = "—"
    my_delta = "Set Current editor in sidebar"
    my_delta_color = "off"

banner_cols = st.columns(5)
banner_cols[0].metric(
    "Open concerns",
    f"{open_icon} {open_count}",
    delta=open_delta,
    delta_color=open_delta_color,
    help=(
        "Total unresolved questions and concerns (status of Open, Investigating, or Waiting). "
        "Target is 0 open items before launch readiness. "
        "🟢 = 0 open, 🟡 = open items (none Critical), 🔴 = 1 or more Critical open items."
    ),
)
banner_cols[1].metric(
    "Critical & high open",
    f"{crit_high_icon} {crit_high_open}",
    delta=crit_high_delta,
    delta_color=crit_high_delta_color,
    help=(
        "Unresolved items marked Critical (blocks build, safety, or launch) or High "
        "(major process, quality, or layout impact). "
        "🟢 = 0 critical/high open, 🟡 = High open (no Critical), 🔴 = Critical open."
    ),
)
banner_cols[2].metric(
    "Unassigned open",
    f"{unassigned_icon} {unassigned_open_count}",
    delta=unassigned_delta,
    delta_color=unassigned_delta_color,
    help=(
        "Open items with a blank Owner field. Every open question or concern should have "
        "an owner assigned to drive resolution."
    ),
)
banner_cols[3].metric(
    "Waiting / blocked",
    f"{waiting_icon} {waiting_count}",
    delta=waiting_delta,
    delta_color="off",
    help=(
        "Open items in Waiting status (blocked on external engineering, supplier, or "
        "cross-functional input), with a breakdown of items actively Investigating versus "
        "still in initial Open status."
    ),
)
banner_cols[4].metric(
    "Assigned to me",
    my_value_str,
    delta=my_delta,
    delta_color=my_delta_color,
    help=(
        "Open questions and concerns where Owner matches the Current editor in the left sidebar "
        "(case-insensitive). Shows how many unresolved action items are currently assigned to you."
    ),
)

editable_table_heading("Questions and concerns")

visible_concerns = filter_table(
    concerns,
    key=f"concerns_filters_{project_id}",
    dropdown_columns=["category", "priority", "status", "owner", "submitted_by"],
    search_columns=["detail", "owner", "comments", "resolution_comments", "submitted_by"],
    labels=column_labels,
    reset_widget_keys=[editor_key],
)
concerns_for_editing = direct_entry_editor_rows(
    visible_concerns,
    editor_key=editor_key,
    sort_columns=[
        "category",
        "detail",
        "priority",
        "status",
        "owner",
        "comments",
        "resolution_comments",
        "submitted_by",
        "created_at",
        "updated_at",
    ],
    labels=column_labels,
)
edited = st.data_editor(
    concerns_for_editing,
    key=editor_key,
    num_rows="dynamic",
    hide_index=True,
    height=430,
    disabled=["id", "submitted_by", "created_at", "updated_at"],
    column_order=[column for column in columns if column != "id"],
    column_config={
        "id": None,
        "category": st.column_config.SelectboxColumn(
            "Category",
            options=list(CONCERN_CATEGORIES),
            default="Other",
            required=True,
        ),
        "detail": st.column_config.TextColumn(
            "Description",
            required=True,
            pinned=True,
            width="large",
        ),
        "owner": st.column_config.TextColumn("Owner"),
        "priority": st.column_config.SelectboxColumn(
            "Priority",
            options=["Low", "Medium", "High", "Critical"],
            default="Medium",
            help=(
                "How urgently this item needs attention: "
                "Critical blocks build, safety, or launch; "
                "High has a major process, quality, or layout impact; "
                "Medium is a standard open item to resolve before process freeze; "
                "Low is a minor question or improvement with a known workaround."
            ),
        ),
        "status": st.column_config.SelectboxColumn(
            "Status",
            options=list(CONCERN_STATUSES),
            default="Open",
        ),
        "comments": st.column_config.TextColumn("Comments", width="medium"),
        "resolution_comments": st.column_config.TextColumn(
            "Resolution comments",
            width="medium",
            help="Required once Status is set to 'Resolved'.",
        ),
        "submitted_by": st.column_config.TextColumn(
            "Submitted by",
            default=current_editor,
            help="Automatically filled with the Current editor when an item is added.",
        ),
        "created_at": st.column_config.DatetimeColumn(
            "Created", format="MMM DD, YYYY HH:mm", timezone="America/New_York"
        ),
        "updated_at": st.column_config.DatetimeColumn(
            "Updated", format="MMM DD, YYYY HH:mm", timezone="America/New_York"
        ),
    },
)
footer_actions = editable_table_footer(
    editor_key=editor_key,
    key_prefix="concerns",
    native_row_selection=True,
)
if footer_actions.undo:
    request_table_editor_reset(editor_key)
    st.toast("Discarded the unsaved Questions and concerns edits", icon=":material/undo:")
    st.rerun()


def clean_text(value: object) -> str:
    """Normalize nullable table values for user-facing summaries."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def concern_summary(row: pd.Series | dict) -> str:
    """Return a short, stable description for confirmations and audit details."""
    concern_id = clean_text(row.get("id"))
    category = clean_text(row.get("category")) or "Other"
    detail = clean_text(row.get("detail")) or clean_text(row.get("subject"))
    label = detail[:80] or "Untitled concern"
    if concern_id:
        return f"{category}: {label} (ID: {concern_id})"
    return f"{category}: {label}"


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
    stage_native_delete_confirmation(editor_key)


IDENTIFYING_CONCERN_COLUMNS = ["detail", "comments", "resolution_comments", "owner"]


@st.dialog("Delete selected concerns?", dismissible=False)
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
            identifying_columns=IDENTIFYING_CONCERN_COLUMNS,
        )
        combined_concerns = merge_filtered_edits(
            concerns,
            visible_concerns,
            remaining_edits,
        )
        combined_concerns = combined_concerns.loc[
            ~combined_concerns["id"].fillna("").astype(str).isin(pending_ids)
        ].copy()
        editor_name = current_editor
        try:
            concern_save_res = replace_concerns(project_id, combined_concerns, editor_name=editor_name)
        except ValueError as exc:
            st.error(str(exc))
            return
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
                {"concerns": other_edits, "saved_with_bulk_delete": True, "created_count": concern_save_res["created_count"], "updated_count": concern_save_res["updated_count"]},
            )
        st.session_state.pop(pending_delete_key, None)
        request_table_editor_reset(editor_key)
        del_concern_msg = f"Deleted {len(pending)} concern(s)"
        if other_edits:
            del_concern_msg += f" · saved {len(other_edits)} other edit(s)"
        st.toast(del_concern_msg, icon=":material/delete:")
        st.rerun()


if st.session_state.get(pending_delete_key):
    confirm_concern_delete()

if footer_actions.save_and_refresh:
    if not selected_concerns.empty:
        st.warning("Clear selected rows before saving concern edits.")
    else:
        edited = drop_untouched_new_rows(
            edited,
            identifying_columns=IDENTIFYING_CONCERN_COLUMNS,
        )
        combined_concerns = merge_filtered_edits(concerns, visible_concerns, edited)
        changed_concerns = pending_edit_summaries()
        editor_name = current_editor
        try:
            concern_save_res = replace_concerns(project_id, combined_concerns, editor_name=editor_name)
        except ValueError as exc:
            st.error(str(exc))
        else:
            record_audit_event(
                project_id,
                "Questions and concerns",
                "Save & Refresh",
                len(changed_concerns),
                editor_name,
                {"concerns": changed_concerns, "created_count": concern_save_res["created_count"], "updated_count": concern_save_res["updated_count"]},
            )
            request_table_editor_reset(editor_key)
            st.toast(
                f"Saved {len(combined_concerns)} item(s) in Questions and concerns"
                + (f" ({len(changed_concerns)} modified)" if changed_concerns else ""),
                icon=":material/check_circle:",
            )
            st.rerun()


with st.expander("History", icon=":material/history:"):
    history = audit_history(project_id, "Questions and concerns", limit=50)
    if history.empty:
        st.caption("No Questions and concerns history has been recorded yet.")
    else:
        render_audit_history_table(
            history.drop(columns=["details"], errors="ignore"),
            key=f"concerns_history_table_{project_id}",
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
