import pandas as pd
import streamlit as st

from utils.scope_ui import page_title_with_scope
from utils.store import (
    RECYCLE_BIN_RETENTION_DAYS,
    audit_history,
    list_recycle_bin_items,
    permanently_delete_recycle_bin_items,
    projects,
    restore_recycle_bin_items,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
)
from utils.table_ui import (
    prepare_editor_selection_column,
    render_select_all_control,
    resolve_editor_selected_rows,
    selectable_dataframe,
)


project_id = st.session_state.get("project_id")
current_editor = str(st.session_state.get("current_editor") or "").strip()

page_title_with_scope("Recycle bin", scope="project")
st.caption(
    f"Deleted items, their cascaded child records, and uploaded media are held in the Recycle Bin for "
    f"{RECYCLE_BIN_RETENTION_DAYS} days before being permanently purged."
)

scope_options = (
    ["Current project", "All projects (including deleted projects)"]
    if project_id
    else ["All projects (including deleted projects)"]
)
col_scope, col_info = st.columns([2, 3], vertical_alignment="bottom")
with col_scope:
    selected_scope = st.segmented_control(
        "View scope",
        options=scope_options,
        default=scope_options[0],
        key="recycle_bin_scope_toggle",
    ) or scope_options[0]

include_all_projects = selected_scope != "Current project" or not project_id
editor_key = f"recycle_bin_table_editor_{'all' if include_all_projects else project_id}"
pending_perm_delete_key = f"recycle_bin_pending_perm_delete_{'all' if include_all_projects else project_id}"

editor_key = apply_pending_table_editor_reset(editor_key)

items_df = list_recycle_bin_items(
    project_id=project_id if not include_all_projects else None,
    include_all_projects=include_all_projects,
)

with col_info:
    if items_df.empty:
        st.caption("Recycle bin is currently empty for this view.")
    else:
        st.caption(
            f"Showing **{len(items_df)}** recoverable item(s). Select rows below to restore them or purge them early."
        )

if items_df.empty:
    with st.container(border=True):
        st.info(
            "No deleted items are in the Recycle Bin for this view. Items deleted across the app will appear here automatically for 30 days.",
            icon=":material/delete_outline:",
        )
else:
    table_df = items_df.copy()
    table_df.insert(0, "Select", False)
    table_df["Select"] = table_df["Select"].astype(bool)

    dropdown_cols = (
        ["project_name", "scenario_name", "entity_type", "deleted_by"]
        if include_all_projects
        else ["scenario_name", "entity_type", "deleted_by"]
    )
    visible_df = filter_table(
        table_df,
        key=f"recycle_bin_filters_{'all' if include_all_projects else project_id}",
        dropdown_columns=dropdown_cols,
        search_columns=[
            "entity_label",
            "entity_type",
            "project_name",
            "scenario_name",
            "summary_text",
            "deleted_by",
        ],
        reset_widget_keys=[editor_key],
    )

    display_columns = [
        "Select",
        "entity_label",
        "entity_type",
        "project_name",
        "scenario_name",
        "summary_text",
        "deleted_by",
        "deleted_at",
        "days_remaining",
    ]
    visible_df = prepare_editor_selection_column(
        visible_df, editor_key=editor_key, column="Select"
    )
    disabled_columns = [col for col in visible_df.columns if col != "Select"]

    edited_visible = st.data_editor(
        visible_df,
        key=editor_key,
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        height=min(520, max(240, 62 + 38 * len(visible_df))),
        column_order=display_columns,
        disabled=disabled_columns,
        column_config={
            "id": None,
            "project_id": None,
            "scenario_id": None,
            "entity_table": None,
            "entity_id": None,
            "expires_at": None,
            "file_count": None,
            "Select": st.column_config.CheckboxColumn(
                "Select",
                help="Select items to restore or permanently delete.",
                default=False,
                pinned=True,
            ),
            "entity_label": st.column_config.TextColumn(
                "Deleted item",
                width="medium",
                pinned=True,
            ),
            "entity_type": st.column_config.TextColumn(
                "Type",
                width="small",
            ),
            "project_name": st.column_config.TextColumn(
                "Project",
                width="medium",
            ),
            "scenario_name": st.column_config.TextColumn(
                "Scenario",
                width="medium",
                help="Shows the specific scenario this item belonged to, or 'All scenarios' when project-wide.",
            ),
            "summary_text": st.column_config.TextColumn(
                "Included records & media",
                width="large",
            ),
            "deleted_by": st.column_config.TextColumn(
                "Deleted by",
                width="small",
            ),
            "deleted_at": st.column_config.DatetimeColumn(
                "Deleted at (ET)",
                format="MMM DD, YYYY HH:mm",
                timezone="America/New_York",
            ),
            "days_remaining": st.column_config.NumberColumn(
                "Expires in",
                format="%d days",
                help="Items are automatically and permanently deleted after 30 days.",
            ),
        },
    )

    selected_rows = resolve_editor_selected_rows(
        visible_df, edited_visible, editor_key=editor_key, column="Select"
    )
    selected_ids = [str(rid) for rid in selected_rows["id"].tolist() if str(rid).strip()]

    btn_bar = st.container(horizontal=True, vertical_alignment="center")
    render_select_all_control(
        btn_bar,
        editor_key=editor_key,
        selectable_count=len(visible_df),
        selected_count=len(selected_ids),
        key_prefix=f"recycle_bin_select_{'all' if include_all_projects else project_id}",
        column="Select",
    )
    restore_clicked = btn_bar.button(
        f"Restore selected ({len(selected_ids)})" if selected_ids else "Restore selected",
        icon=":material/restore_from_trash:",
        type="primary",
        disabled=not selected_ids,
        key="recycle_bin_restore_btn",
    )
    perm_delete_clicked = btn_bar.button(
        f"Delete permanently ({len(selected_ids)})" if selected_ids else "Delete permanently",
        icon=":material/delete_forever:",
        type="secondary",
        disabled=not selected_ids,
        key="destructive_recycle_bin_perm_delete_btn",
    )

    if restore_clicked and selected_ids:
        try:
            result = restore_recycle_bin_items(
                selected_ids,
                editor_name=current_editor or "Collaborator",
            )
            # If a project was restored and no active project is selected, select the restored project.
            live_projects = projects()
            if live_projects and not st.session_state.get("project_id"):
                st.session_state["project_id"] = str(live_projects[0]["id"])
            request_table_editor_reset(editor_key)
            st.toast(
                f"Restored {result['restored_count']} item(s).",
                icon=":material/restore_from_trash:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    if perm_delete_clicked and selected_ids:
        st.session_state[pending_perm_delete_key] = selected_rows[
            ["id", "entity_type", "entity_label", "project_name", "scenario_name", "summary_text"]
        ].to_dict("records")


@st.dialog("Confirm permanent deletion")
def confirm_permanent_delete_dialog() -> None:
    pending = st.session_state.get(pending_perm_delete_key) or []
    if not pending:
        st.session_state.pop(pending_perm_delete_key, None)
        st.rerun()
        return
    st.warning(
        f"Permanently delete **{len(pending)}** selected item(s) from the Recycle Bin? "
        "This action cannot be undone and any unreferenced media files will be removed from disk.",
        icon=":material/warning:",
    )
    for row in pending[:8]:
        st.markdown(
            f"- **{row.get('entity_type')}**: {row.get('entity_label')} "
            f"*({row.get('project_name')} · {row.get('scenario_name')})* — {row.get('summary_text')}"
        )
    if len(pending) > 8:
        st.caption(f"...and {len(pending) - 8} more item(s).")

    c1, c2 = st.columns(2)
    with c1:
        if st.button(
            "Delete permanently",
            type="primary",
            icon=":material/delete_forever:",
            width="stretch",
            key="destructive_confirm_perm_delete_yes",
        ):
            ids_to_purge = [str(r["id"]) for r in pending]
            purged = permanently_delete_recycle_bin_items(
                ids_to_purge,
                editor_name=current_editor or "Collaborator",
            )
            st.session_state.pop(pending_perm_delete_key, None)
            request_table_editor_reset(editor_key)
            st.toast(
                f"Permanently deleted {purged} item(s) from the Recycle Bin.",
                icon=":material/delete_forever:",
            )
            st.rerun()
    with c2:
        if st.button("Cancel", width="stretch", key="confirm_perm_delete_no"):
            st.session_state.pop(pending_perm_delete_key, None)
            st.rerun()


if st.session_state.get(pending_perm_delete_key):
    confirm_permanent_delete_dialog()

if project_id:
    with st.expander("History", icon=":material/history:"):
        history = audit_history(project_id, "Recycle Bin", limit=50)
        if history.empty:
            st.caption("No Recycle Bin restore or permanent-purge history has been recorded for this project yet.")
        else:
            selectable_dataframe(
                history.drop(columns=["details"], errors="ignore"),
                key=f"recycle_bin_history_table_{project_id}",
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
