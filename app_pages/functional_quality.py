import pandas as pd
import streamlit as st

from utils.assignment_ui import (
    ASSIGN_REQ_DIALOG_OPEN_KEY,
    render_assign_requirement_dialog,
)
from utils.control_plan_ui import render_control_plan_tab
from utils.equipment_ui import (
    EQUIPMENT_HISTORY_CATEGORIES,
    render_functional_equipment_tab,
)
from utils.pfmea_store import (
    bulk_review_pfmea_sources,
    reassign_pfmea_entry,
    upstream_modified_pfmea_entries,
)
from utils.pfmea_ui import render_pfmea_staged_draft_banner, render_pfmea_tab
from utils.quality_help import (
    CONTROL_PLAN_HELP,
    EQUIPMENT_HELP,
    PFMEA_HELP_SECTIONS,
    PFMEA_QUICK_START,
    REQUIREMENTS_REPOSITORY_HELP,
)
from utils.quality_store import (
    accept_quality_upstream_changes,
    bulk_delete_unlinked_records,
    bulk_relink_operation_records,
    quality_process_steps,
    reassign_quality_assignment,
    relink_quality_record,
    unlinked_quality_records,
    upstream_modified_quality_assignments,
)
from utils.requirements_ui import render_requirements_repository_tab
from utils.scope_ui import page_title_with_scope
from utils.store import audit_history, planning_scenarios
from utils.table_ui import selectable_dataframe
from utils.traceability_ui import render_traceability_matrix_tab


@st.dialog(
    "How to use the Quality page",
    width="large",
    icon=":material/help:",
)
def show_quality_page_help() -> None:
    """Show static, read-only instructions for the Quality workflows."""
    requirements_help_tab, pfmea_help_tab, control_plan_help_tab, equipment_help_tab = st.tabs(
        ["Requirements repository", "PFMEA", "Control Plan", "Equipment"],
        key="quality_page_help_tabs",
    )
    with requirements_help_tab:
        st.markdown(REQUIREMENTS_REPOSITORY_HELP)
    with pfmea_help_tab:
        st.markdown(PFMEA_QUICK_START)
        for section_title, section_content in PFMEA_HELP_SECTIONS:
            with st.expander(section_title):
                st.markdown(section_content)
    with control_plan_help_tab:
        st.markdown(CONTROL_PLAN_HELP)
    with equipment_help_tab:
        st.markdown(EQUIPMENT_HELP)

    actions = st.container(horizontal=True, horizontal_alignment="right")
    if actions.button(
        "Close",
        icon=":material/close:",
        key="close_quality_page_help",
    ):
        st.rerun()





def render_quality_history(project_id: str) -> None:
    """Render the page's one bottom History expander with workflow tabs."""
    with st.expander("History", icon=":material/history:"):
        requirements_history_tab, pfmea_history_tab, control_plan_history_tab, equipment_history_tab = st.tabs(
            ["Requirements", "PFMEA", "Control Plan", "Equipment"], key=f"quality_history_tabs_{project_id}"
        )
        with requirements_history_tab:
            history_groups: list[pd.DataFrame] = []
            for table_name, workflow in [
                ("Quality requirements", "Quality requirements"),
                ("Quality requirement types", "Quality requirement types"),
            ]:
                table_history = audit_history(project_id, table_name, limit=50)
                if not table_history.empty:
                    table_history = table_history.copy()
                    table_history.insert(0, "workflow", workflow)
                    history_groups.append(table_history)
            history = (
                pd.concat(history_groups, ignore_index=True)
                .sort_values("created_at", ascending=False, kind="stable")
                .head(50)
                if history_groups
                else pd.DataFrame()
            )
            if history.empty:
                st.caption("No Quality requirement changes have been recorded yet.")
            else:
                selectable_dataframe(
                    history.drop(columns=["details"], errors="ignore"),
                    key=f"quality_requirements_history_{project_id}",
                    hide_index=True,
                    column_config={
                        "workflow": "Workflow",
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
        with control_plan_history_tab:
            history = audit_history(project_id, "Control Plan", limit=50)
            if history.empty:
                st.caption("No Control Plan changes have been recorded yet.")
            else:
                selectable_dataframe(
                    history.drop(columns=["details"], errors="ignore"),
                    key=f"control_plan_history_{project_id}",
                    hide_index=True,
                    column_config={
                        "action": "Action", "row_count": "Rows",
                        "editor_name": "Editor",
                        "created_at": st.column_config.DatetimeColumn(
                            "When", format="MMM DD, YYYY HH:mm"
                        ),
                    },
                )
        with equipment_history_tab:
            groups: list[pd.DataFrame] = []
            for category in EQUIPMENT_HISTORY_CATEGORIES:
                category_history = audit_history(project_id, category, limit=50)
                if category_history.empty:
                    continue
                category_history = category_history.copy()
                category_history.insert(0, "workflow", category)
                groups.append(category_history)
            history = (
                pd.concat(groups, ignore_index=True)
                .sort_values("created_at", ascending=False, kind="stable")
                .head(50)
                if groups else pd.DataFrame()
            )
            if history.empty:
                st.caption("No Equipment changes have been recorded yet.")
            else:
                selectable_dataframe(
                    history.drop(columns=["details"], errors="ignore"),
                    key=f"quality_equipment_history_{project_id}",
                    hide_index=True,
                    column_config={
                        "workflow": "Workflow", "action": "Action", "row_count": "Rows",
                        "editor_name": "Editor",
                        "created_at": st.column_config.DatetimeColumn(
                            "When", format="MMM DD, YYYY HH:mm"
                        ),
                    },
                )


@st.dialog("Permanently delete unlinked records?", dismissible=False)
def confirm_unlinked_purge_dialog(project_id: str, scenario_id: str) -> None:
    pending_key = f"quality_unlinked_pending_purge_{project_id}"
    pending = st.session_state.get(pending_key, [])
    if not pending:
        st.session_state.pop(pending_key, None)
        st.rerun()
    st.warning(
        f"Permanently delete **{len(pending)}** unlinked record(s)? "
        "These records were disconnected when work elements were deleted in PAAG. "
        "Deleting them is permanent and cannot be undone."
    )
    for p_item in pending[:12]:
        st.write(
            f"- **{p_item.get('record_type', 'Record')}**: `{p_item.get('identifier', '')}` "
            f"— {p_item.get('detail') or p_item.get('name') or ''} "
            f"(Operation: *{p_item.get('removed_operation', 'Unknown')}*)"
        )
    if len(pending) > 12:
        st.caption(f"... and {len(pending) - 12} more record(s)")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_unlinked_purge_{project_id}"):
        st.session_state.pop(pending_key, None)
        st.rerun()
    if actions.button(
        "Permanently Delete",
        type="primary",
        icon=":material/delete_forever:",
        key=f"destructive_confirm_unlinked_purge_{project_id}",
    ):
        try:
            editor = st.session_state.get("current_editor", "")
            deleted_count = bulk_delete_unlinked_records(
                project_id, scenario_id, pending, editor=editor
            )
            st.session_state.pop(pending_key, None)
            st.toast(
                f"Permanently deleted {deleted_count} unlinked record(s)",
                icon=":material/delete:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def render_unlinked_review_tab(
    project_id: str,
    scenario_id: str,
    active_scenario: dict[str, object] | None,
    unlinked_data: dict[str, object],
) -> None:
    pending_purge_key = f"quality_unlinked_pending_purge_{project_id}"
    if st.session_state.get(pending_purge_key):
        confirm_unlinked_purge_dialog(project_id, scenario_id)

    st.markdown("### ⚠️ Unlinked Downstream Records Review")
    st.caption(
        "When process steps are removed in **Process at a Glance (PAAG)**, their associated "
        "Quality specifications, PFMEA failure modes, and Tooling/Equipment links are preserved "
        "here. Reconcile these items by relinking them to an active process step in this "
        "scenario, or permanently purge records that are no longer needed."
    )

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("Total Unlinked", unlinked_data["total_count"])
    col_m2.metric("Quality Requirements", unlinked_data["quality_count"])
    col_m3.metric("PFMEA Failure Modes", unlinked_data["pfmea_count"])
    col_m4.metric("Tooling / Equipment", unlinked_data["equipment_count"])

    steps_df = quality_process_steps(project_id, scenario_id)
    step_options: list[str] = [""]
    step_label_map: dict[str, str] = {"": "Select target process step..."}
    if not steps_df.empty:
        for _, srow in steps_df.iterrows():
            sid = str(srow["id"])
            op_lbl = str(srow.get("op_id") or "No Op ID")
            pitch_lbl = str(srow.get("pitch") or "")
            seq_lbl = str(srow.get("sequence") or "")
            we_lbl = str(srow.get("work_element") or "")
            step_options.append(sid)
            step_label_map[sid] = f"[{op_lbl}] {pitch_lbl} (Seq {seq_lbl}): {we_lbl}"
    else:
        st.warning(
            "There are currently no active process steps in this scenario. "
            "You can create new steps in PAAG or purge obsolete records here."
        )

    act_col1, act_col2 = st.columns([3, 1], vertical_alignment="center")
    with act_col2:
        if st.button(
            "🗑️ Purge All Unlinked Records",
            key=f"purge_all_unlinked_btn_{project_id}",
            help="Permanently delete all unlinked records in this scenario",
            use_container_width=True,
        ):
            st.session_state[pending_purge_key] = unlinked_data["items"]
            st.rerun()

    operations = unlinked_data.get("operations", [])
    editor = st.session_state.get("current_editor", "")

    for idx, op_group in enumerate(operations):
        op_name = op_group["operation"]
        op_desc = op_group["description"]
        op_pitch = op_group["pitch"]
        op_time = str(op_group.get("unlinked_at") or "")
        time_str = op_time[:19].replace("T", " ") if op_time else "Recently"
        items = op_group.get("items", [])

        with st.container(border=True):
            st.markdown(
                f"#### 📦 Removed Operation: `{op_name}`"
                + (f" — *{op_desc}*" if op_desc else "")
            )
            st.caption(
                f"Station/Pitch: **{op_pitch or 'N/A'}** | Disconnected: **{time_str}** | "
                f"Unlinked Items: **{len(items)}** "
                f"({op_group['quality_count']} Quality, {op_group['pfmea_count']} PFMEA, {op_group['equipment_count']} Equipment)"
            )

            # Bulk relink bar for this operation
            b_col1, b_col2, b_col3 = st.columns([4, 2, 1.5], vertical_alignment="bottom")
            bulk_target_key = f"bulk_target_step_{project_id}_{idx}"
            selected_bulk_step = b_col1.selectbox(
                "Bulk relink all items in this operation to:",
                options=step_options,
                format_func=lambda sid: step_label_map.get(sid, sid),
                key=bulk_target_key,
                disabled=steps_df.empty,
            )
            if b_col2.button(
                "Relink Entire Operation",
                key=f"bulk_relink_op_btn_{project_id}_{idx}",
                type="primary",
                icon=":material/swap_horiz:",
                disabled=steps_df.empty or not bool(selected_bulk_step),
            ):
                relinked_count = bulk_relink_operation_records(
                    project_id,
                    scenario_id,
                    op_name,
                    selected_bulk_step,
                    editor=editor,
                )
                st.toast(
                    f"Relinked {relinked_count} record(s) from operation '{op_name}'",
                    icon=":material/check_circle:",
                )
                st.rerun()

            if b_col3.button(
                "Purge Operation",
                key=f"purge_op_btn_{project_id}_{idx}",
                icon=":material/delete:",
                help=f"Permanently delete all {len(items)} unlinked records for this operation",
            ):
                st.session_state[pending_purge_key] = items
                st.rerun()

            st.markdown("<hr style='margin: 12px 0 16px 0; border: none; border-top: 1px solid #e5e7eb;' />", unsafe_allow_html=True)
            st.markdown("**Individual Records:**")

            for item_idx, item in enumerate(items):
                i_col_info, i_col_target, i_col_relink, i_col_del = st.columns(
                    [4, 4, 1.2, 1], vertical_alignment="center"
                )

                rtype = item["record_type"]
                if rtype == "Quality requirement":
                    badge_icon = "🏷️"
                    type_color = "#2563eb"
                elif rtype == "PFMEA failure mode":
                    badge_icon = "⚡"
                    type_color = "#d97706"
                else:
                    badge_icon = "🔧"
                    type_color = "#059669"

                with i_col_info:
                    st.markdown(
                        f"<div>"
                        f"<span style='background-color: {type_color}18; color: {type_color}; border: 1px solid {type_color}44; padding: 2px 6px; border-radius: 4px; font-size: 0.78rem; font-weight: 600;'>"
                        f"{badge_icon} {rtype}</span> "
                        f"<strong>{item['identifier']}</strong></div>"
                        f"<div style='font-size: 0.85rem; color: #4b5563; margin-top: 2px;'>{item['detail'] or item['name']}</div>",
                        unsafe_allow_html=True,
                    )

                item_step_key = f"item_step_{project_id}_{item['id']}"
                chosen_step = i_col_target.selectbox(
                    "Target Step",
                    options=step_options,
                    format_func=lambda sid: step_label_map.get(sid, sid),
                    key=item_step_key,
                    label_visibility="collapsed",
                    disabled=steps_df.empty,
                )

                if i_col_relink.button(
                    "Relink",
                    key=f"relink_item_{project_id}_{item['id']}",
                    icon=":material/link:",
                    disabled=steps_df.empty or not bool(chosen_step),
                ):
                    try:
                        relink_quality_record(
                            project_id,
                            scenario_id,
                            item["record_type"],
                            item["id"],
                            chosen_step,
                            editor=editor,
                        )
                        st.toast(
                            f"Relinked '{item['identifier']}'",
                            icon=":material/check_circle:",
                        )
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

                if i_col_del.button(
                    "Purge",
                    key=f"del_item_{project_id}_{item['id']}",
                    icon=":material/delete:",
                ):
                    st.session_state[pending_purge_key] = [item]
                    st.rerun()

def clear_upstream_dialog_request() -> None:
    for k in list(st.session_state.keys()):
        if k.startswith("show_upstream_dialog_"):
            st.session_state.pop(k, None)


@st.dialog(
    "Review Upstream Process Changes",
    width="large",
    on_dismiss=clear_upstream_dialog_request,
)
def render_upstream_changes_dialog(
    project_id: str,
    scenario_id: str,
    upstream_quality_mod: list[dict[str, object]],
    upstream_pfmea_mod: list[dict[str, object]],
) -> None:
    total_mod = len(upstream_quality_mod) + len(upstream_pfmea_mod)
    if total_mod == 0:
        st.success("All quality records are now in sync with current Process at a Glance steps.")
        if st.button("Close", key=f"btn_close_empty_upstream_{project_id}"):
            clear_upstream_dialog_request()
            st.rerun()
        return

    st.caption(
        "Industrial Engineers modified or moved process steps in **Process at a Glance (PAAG)**. "
        "Review differences below to synchronize your baseline snapshots or reassign records to another step."
    )

    top_act1, top_act2 = st.columns([3, 1], vertical_alignment="center")
    editor = st.session_state.get("current_editor", "")
    with top_act1:
        if st.button(
            f"Accept & Sync All Upstream Changes ({total_mod})",
            type="primary",
            icon=":material/done_all:",
            key=f"btn_sync_all_upstream_{project_id}",
            use_container_width=True,
        ):
            if upstream_quality_mod:
                q_ids = [str(item["assignment_id"]) for item in upstream_quality_mod]
                accept_quality_upstream_changes(project_id, scenario_id, q_ids, editor_name=editor)
            if upstream_pfmea_mod:
                p_ids = [str(item["entry_id"]) for item in upstream_pfmea_mod]
                bulk_review_pfmea_sources(project_id, scenario_id, p_ids, editor_name=editor)
            clear_upstream_dialog_request()
            st.toast(f"Synchronized {total_mod} record(s) with live PAAG steps", icon=":material/check_circle:")
            st.rerun()
    with top_act2:
        if st.button("Close", key=f"btn_close_upstream_dialog_{project_id}", use_container_width=True):
            clear_upstream_dialog_request()
            st.rerun()

    steps_df = quality_process_steps(project_id, scenario_id)
    step_options: list[str] = [""]
    step_label_map: dict[str, str] = {"": "Select target process step to reassign..."}
    if not steps_df.empty:
        for _, srow in steps_df.iterrows():
            sid = str(srow["id"])
            op_lbl = str(srow.get("op_id") or "No Op ID")
            pitch_lbl = str(srow.get("pitch") or "")
            seq_lbl = str(srow.get("sequence") or "")
            we_lbl = str(srow.get("work_element") or "")
            step_options.append(sid)
            step_label_map[sid] = f"[{op_lbl}] {pitch_lbl} (Seq {seq_lbl}): {we_lbl}"

    tab_qual, tab_pfmea = st.tabs([
        f"Quality Specifications ({len(upstream_quality_mod)})",
        f"PFMEA Failure Modes ({len(upstream_pfmea_mod)})",
    ])

    with tab_qual:
        if not upstream_quality_mod:
            st.info("No Quality specifications have upstream differences.")
        else:
            if len(upstream_quality_mod) > 1:
                if st.button(
                    f"Accept & Sync All Quality Specs ({len(upstream_quality_mod)})",
                    key=f"btn_sync_all_quality_specs_{project_id}",
                    icon=":material/done_all:",
                ):
                    q_ids = [str(item["assignment_id"]) for item in upstream_quality_mod]
                    accept_quality_upstream_changes(project_id, scenario_id, q_ids, editor_name=editor)
                    st.toast(f"Synchronized {len(q_ids)} Quality specifications", icon=":material/check_circle:")
                    st.rerun()

            for item in upstream_quality_mod:
                aid = str(item["assignment_id"])
                with st.container(border=True):
                    st.markdown(
                        f"**{item['unique_identifier']}** — `{item['requirement_type']}`: {item['description']}"
                    )
                    diff_parts = []
                    for chg in item.get("changes", []):
                        diff_parts.append(
                            f"• **{chg['label']}**: `{chg['snapshot']}` ➔ <span style='color: #b45309; font-weight: 700;'>`{chg['live']}`</span>"
                        )
                    if diff_parts:
                        st.markdown("<div style='margin-bottom: 8px; font-size: 0.9rem;'>" + "<br/>".join(diff_parts) + "</div>", unsafe_allow_html=True)

                    c_snap, c_live = st.columns(2)
                    with c_snap:
                        st.caption("📋 **Quality Baseline Snapshot**")
                        st.markdown(
                            f"- **Pitch:** {item['snapshot_pitch'] or '(None)'}\n"
                            f"- **Operation:** {item['snapshot_operation'] or '(None)'}\n"
                            f"- **Description:** {item['snapshot_description'] or '(None)'}"
                        )
                    with c_live:
                        st.caption("⚡ **Live PAAG Process Step**")
                        st.markdown(
                            f"- **Pitch:** {item['live_pitch'] or '(None)'}\n"
                            f"- **Operation:** {item['live_operation'] or '(None)'}\n"
                            f"- **Description:** {item['live_description'] or '(None)'}"
                        )

                    c_act_sync, c_act_reassign, c_act_btn = st.columns([1.5, 2.5, 1], vertical_alignment="bottom")
                    with c_act_sync:
                        if st.button(
                            "Accept & Sync",
                            key=f"sync_q_{aid}",
                            icon=":material/check:",
                            type="secondary",
                            help="Update baseline snapshot to match current PAAG step",
                        ):
                            accept_quality_upstream_changes(project_id, scenario_id, [aid], editor_name=editor)
                            st.toast(f"Synchronized {item['unique_identifier']}", icon=":material/check_circle:")
                            st.rerun()
                    with c_act_reassign:
                        chosen_step = st.selectbox(
                            "Reassign to step",
                            options=step_options,
                            format_func=lambda sid: step_label_map.get(sid, sid),
                            key=f"reassign_target_q_{aid}",
                            label_visibility="collapsed",
                        )
                    with c_act_btn:
                        if st.button(
                            "Reassign",
                            key=f"reassign_btn_q_{aid}",
                            icon=":material/swap_horiz:",
                            disabled=not chosen_step,
                        ):
                            try:
                                reassign_quality_assignment(
                                    project_id, scenario_id, aid, chosen_step, editor_name=editor
                                )
                                st.toast(f"Reassigned {item['unique_identifier']}", icon=":material/check_circle:")
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))

    with tab_pfmea:
        if not upstream_pfmea_mod:
            st.info("No PFMEA entries have upstream differences.")
        else:
            if len(upstream_pfmea_mod) > 1:
                if st.button(
                    f"Accept & Sync All PFMEA Entries ({len(upstream_pfmea_mod)})",
                    key=f"btn_sync_all_pfmea_entries_{project_id}",
                    icon=":material/done_all:",
                ):
                    p_ids = [str(item["entry_id"]) for item in upstream_pfmea_mod]
                    bulk_review_pfmea_sources(project_id, scenario_id, p_ids, editor_name=editor)
                    st.toast(f"Synchronized {len(p_ids)} PFMEA entries", icon=":material/check_circle:")
                    st.rerun()

            for item in upstream_pfmea_mod:
                eid = str(item["entry_id"])
                with st.container(border=True):
                    st.markdown(
                        f"**PFMEA Failure Mode**: {item['potential_failure_mode']} "
                        f"(Class: `{item['class_code'] or 'None'}`)"
                    )
                    diff_parts = []
                    for chg in item.get("changes", []):
                        diff_parts.append(
                            f"• **{chg['label']}**: `{chg['snapshot']}` ➔ <span style='color: #b45309; font-weight: 700;'>`{chg['live']}`</span>"
                        )
                    if diff_parts:
                        st.markdown("<div style='margin-bottom: 8px; font-size: 0.9rem;'>" + "<br/>".join(diff_parts) + "</div>", unsafe_allow_html=True)

                    c_snap, c_live = st.columns(2)
                    with c_snap:
                        st.caption("📋 **PFMEA Baseline Snapshot**")
                        st.markdown(
                            f"- **Pitch:** {item['snapshot_pitch'] or '(None)'}\n"
                            f"- **Operation:** {item['snapshot_operation'] or '(None)'}\n"
                            f"- **Location:** {item['snapshot_location'] or '(None)'}\n"
                            f"- **Description:** {item['snapshot_description'] or '(None)'}"
                        )
                    with c_live:
                        st.caption("⚡ **Live PAAG Process Step**")
                        st.markdown(
                            f"- **Pitch:** {item['live_pitch'] or '(None)'}\n"
                            f"- **Operation:** {item['live_operation'] or '(None)'}\n"
                            f"- **Location:** {item['live_location'] or '(None)'}\n"
                            f"- **Description:** {item['live_description'] or '(None)'}"
                        )

                    c_act_sync, c_act_reassign, c_act_btn = st.columns([1.5, 2.5, 1], vertical_alignment="bottom")
                    with c_act_sync:
                        if st.button(
                            "Accept & Sync",
                            key=f"sync_p_{eid}",
                            icon=":material/check:",
                            type="secondary",
                            help="Update baseline snapshot to match current PAAG step",
                        ):
                            bulk_review_pfmea_sources(project_id, scenario_id, [eid], editor_name=editor)
                            st.toast("Synchronized PFMEA failure mode baseline", icon=":material/check_circle:")
                            st.rerun()
                    with c_act_reassign:
                        chosen_step = st.selectbox(
                            "Reassign to step",
                            options=step_options,
                            format_func=lambda sid: step_label_map.get(sid, sid),
                            key=f"reassign_target_p_{eid}",
                            label_visibility="collapsed",
                        )
                    with c_act_btn:
                        if st.button(
                            "Reassign",
                            key=f"reassign_btn_p_{eid}",
                            icon=":material/swap_horiz:",
                            disabled=not chosen_step,
                        ):
                            try:
                                reassign_pfmea_entry(
                                    project_id, scenario_id, eid, chosen_step, editor_name=editor
                                )
                                st.toast("Reassigned PFMEA failure mode to new step", icon=":material/check_circle:")
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))


project_id = st.session_state.get("project_id")
page_title_with_scope(
    "Quality",
    scope="scenario-aware",
    help_text=(
        "The Quality requirements repository is shared across every scenario. "
        "PFMEA records belong only to the currently selected scenario."
    ),
)
if st.button(
    "How to use this page",
    icon=":material/help:",
    key="quality_page_help",
    help="Open instructions for Requirements repository, PFMEA, Control Plan, and Equipment.",
):
    show_quality_page_help()
st.caption(
    "Maintain reusable checks and specifications, then deliberately publish saved "
    "updates to linked Process at a Glance steps."
)
if not project_id:
    st.stop()

scenarios = planning_scenarios(project_id)
scenario_by_id = {str(scenario["id"]): scenario for scenario in scenarios}
scenario_id = str(st.session_state.get("scenario_id") or "")
active_scenario = scenario_by_id.get(scenario_id)

unlinked_data = (
    unlinked_quality_records(project_id, scenario_id)
    if active_scenario
    else {"total_count": 0, "quality_count": 0, "pfmea_count": 0, "equipment_count": 0, "items": [], "operations": []}
)
unlinked_count = unlinked_data["total_count"]

if unlinked_count > 0:
    st.markdown(
        f"""
        <div style="
            border: 2px solid #ef4444;
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.12) 0%, rgba(220, 38, 38, 0.05) 100%);
            border-left: 8px solid #dc2626;
            border-radius: 8px;
            padding: 16px 20px;
            margin-top: 10px;
            margin-bottom: 20px;
            box-shadow: 0 4px 12px rgba(220, 38, 38, 0.15);
        ">
            <div style="display: flex; align-items: flex-start; gap: 12px;">
                <div style="font-size: 1.8rem; line-height: 1;">⚠️</div>
                <div style="flex-grow: 1;">
                    <div style="font-size: 1.05rem; font-weight: 700; color: #dc2626; margin-bottom: 4px;">
                        Warning: {unlinked_count} Downstream Engineering Record{'s' if unlinked_count != 1 else ''} Disconnected by PAAG Deletions
                    </div>
                    <div style="font-size: 0.92rem; color: #374151; line-height: 1.45;">
                        Process steps deleted in <strong>Process at a Glance (PAAG)</strong> left 
                        <strong>{unlinked_data['quality_count']}</strong> Quality spec{'s' if unlinked_data['quality_count'] != 1 else ''}, 
                        <strong>{unlinked_data['pfmea_count']}</strong> PFMEA failure mode{'s' if unlinked_data['pfmea_count'] != 1 else ''}, and 
                        <strong>{unlinked_data['equipment_count']}</strong> Tooling/Equipment link{'s' if unlinked_data['equipment_count'] != 1 else ''} unlinked.
                        Please review the highlighted 
                        <strong style="color: #dc2626; text-decoration: underline;">⚠️ Unlinked Review ({unlinked_count})</strong> 
                        tab below to relink or permanently purge them.
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <style>
        div[data-baseweb="tab-list"] button[data-baseweb="tab"]:first-child {
            border: 2px solid #dc2626 !important;
            border-radius: 6px 6px 0 0 !important;
            background-color: rgba(220, 38, 38, 0.12) !important;
            color: #dc2626 !important;
            font-weight: 700 !important;
            box-shadow: 0 -2px 8px rgba(220, 38, 38, 0.2) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    upstream_quality_mod = (
        upstream_modified_quality_assignments(project_id, scenario_id)
        if active_scenario
        else []
    )
except Exception:
    upstream_quality_mod = []

try:
    upstream_pfmea_mod = (
        upstream_modified_pfmea_entries(project_id, scenario_id)
        if active_scenario
        else []
    )
except Exception:
    upstream_pfmea_mod = []

upstream_count = len(upstream_quality_mod) + len(upstream_pfmea_mod)

if upstream_count > 0:
    st.markdown(
        f"""
        <div style="
            border: 2px solid #f59e0b;
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.12) 0%, rgba(217, 119, 6, 0.05) 100%);
            border-left: 8px solid #d97706;
            border-radius: 8px;
            padding: 16px 20px;
            margin-top: 10px;
            margin-bottom: 16px;
            box-shadow: 0 4px 12px rgba(217, 119, 6, 0.15);
        ">
            <div style="display: flex; align-items: flex-start; gap: 12px;">
                <div style="font-size: 1.8rem; line-height: 1;">⚡</div>
                <div style="flex-grow: 1;">
                    <div style="font-size: 1.05rem; font-weight: 700; color: #b45309; margin-bottom: 4px;">
                        Notice: {upstream_count} Linked Downstream Record{'s' if upstream_count != 1 else ''} Affected by PAAG Process Changes
                    </div>
                    <div style="font-size: 0.92rem; color: #374151; line-height: 1.45;">
                        Process steps modified or moved in <strong>Process at a Glance (PAAG)</strong> differ from saved Quality documentation baselines
                        (<strong>{len(upstream_quality_mod)}</strong> Quality spec{'s' if len(upstream_quality_mod) != 1 else ''}, 
                        <strong>{len(upstream_pfmea_mod)}</strong> PFMEA failure mode{'s' if len(upstream_pfmea_mod) != 1 else ''}).
                        Review differences side-by-side to synchronize documentation baselines or reassign steps.
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button(
        f"⚡ Review Upstream Changes ({upstream_count})",
        key=f"btn_open_upstream_changes_{project_id}",
        help="Review side-by-side differences between PAAG and Quality documentation baselines",
    ):
        st.session_state[f"show_upstream_dialog_{project_id}"] = True
        st.rerun()

if st.session_state.get(f"show_upstream_dialog_{project_id}"):
    render_upstream_changes_dialog(
        project_id,
        scenario_id,
        upstream_quality_mod,
        upstream_pfmea_mod,
    )

if st.session_state.get(ASSIGN_REQ_DIALOG_OPEN_KEY):
    if active_scenario:
        render_assign_requirement_dialog(project_id, scenario_id)
    else:
        st.warning("Please select an active planning scenario before assigning Quality requirements.")

draft_banner_slot = st.empty()

if unlinked_count > 0:
    tab_list = [
        f"⚠️ Unlinked Review ({unlinked_count})",
        "📊 Traceability Matrix",
        "Requirements repository",
        "PFMEA",
        "Control Plan",
        "Equipment",
    ]
    tabs = st.tabs(
        tab_list,
        key=f"quality_page_tabs_{project_id}",
        on_change="rerun",
    )
    unlinked_review_tab = tabs[0]
    traceability_tab = tabs[1]
    requirements_repository_tab = tabs[2]
    pfmea_tab = tabs[3]
    control_plan_tab = tabs[4]
    equipment_tab = tabs[5]
else:
    tab_list = [
        "📊 Traceability Matrix",
        "Requirements repository",
        "PFMEA",
        "Control Plan",
        "Equipment",
    ]
    tabs = st.tabs(
        tab_list,
        key=f"quality_page_tabs_{project_id}",
        on_change="rerun",
    )
    unlinked_review_tab = None
    traceability_tab = tabs[0]
    requirements_repository_tab = tabs[1]
    pfmea_tab = tabs[2]
    control_plan_tab = tabs[3]
    equipment_tab = tabs[4]

if active_scenario and not pfmea_tab.open:
    with draft_banner_slot:
        render_pfmea_staged_draft_banner(project_id, scenario_id)

if unlinked_review_tab is not None and unlinked_review_tab.open:
    with unlinked_review_tab:
        render_unlinked_review_tab(
            project_id,
            scenario_id,
            active_scenario,
            unlinked_data,
        )
    render_quality_history(project_id)
    st.stop()
if traceability_tab.open:
    with traceability_tab:
        render_traceability_matrix_tab(
            project_id,
            scenario_id,
            active_scenario,
        )
    render_quality_history(project_id)
    st.stop()
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
        if not active_scenario:
            st.info("Select an active planning scenario before opening Control Plan.")
        else:
            render_control_plan_tab(project_id, scenario_id, str(active_scenario["name"]))
    render_quality_history(project_id)
    st.stop()
if equipment_tab.open:
    with equipment_tab:
        render_functional_equipment_tab(
            project_id,
            scenario_id if active_scenario else None,
            "Quality",
            render_history=False,
        )
    render_quality_history(project_id)
    st.stop()

with requirements_repository_tab:
    render_requirements_repository_tab(
        project_id=project_id,
        scenario_id=scenario_id,
        active_scenario=active_scenario,
    )

render_quality_history(project_id)
