import streamlit as st

from utils.equipment_ui import render_functional_equipment_tab
from utils.functional_review_ui import render_functional_review_shell
from utils.scope_ui import page_title_with_scope
from utils.store import (
    audit_history,
    get_planning_scenario,
    get_scenario_part_handling_options,
    record_audit_event,
    set_process_part_option_handling_type,
)

project_id = str(st.session_state.get("project_id") or "")
scenario_id = str(st.session_state.get("scenario_id") or "")
scenario = (
    get_planning_scenario(project_id, scenario_id)
    if project_id and scenario_id
    else None
)

page_title_with_scope(
    "Materials",
    scope="scenario-aware",
    scenario_name=str((scenario or {}).get("name") or "") or None,
    help_text=(
        "Materials Review content uses its established scope. Shared Equipment identity "
        "is project-wide while placement uses the active planning scenario."
    ),
)
if not project_id:
    st.stop()

review_tab, equipment_tab = st.tabs(
    ["Review", "Equipment"],
    key=f"materials_page_tabs_{project_id}",
    on_change="rerun",
)
if equipment_tab.open:
    with equipment_tab:
        render_functional_equipment_tab(
            project_id, scenario_id if scenario else None, "Materials"
        )
    st.stop()

review_tab.__enter__()

render_functional_review_shell(
    title="Materials",
    description="Prepare materials observations and review items for future planning.",
    key_prefix="materials",
    show_title=False,
)

if scenario_id:
    st.divider()
    st.subheader("Process Part Handling Classifications", anchor=False)
    st.caption(
        "Materials Planner / IE: Review parts assigned to Process steps in this scenario. "
        "Classify each part-use as **Consume** (first arrival on line from container) or **Handle** "
        "(subsequent positioning or manipulation). Unclassified parts generate alerts on Process slides."
    )

    part_options = get_scenario_part_handling_options(project_id, scenario_id)
    total_uses = len(part_options)
    consumed_cnt = sum(1 for o in part_options if o.get("handling_type") == "Consume")
    handled_cnt = sum(1 for o in part_options if o.get("handling_type") == "Handle")
    unclassified_cnt = sum(1 for o in part_options if not o.get("handling_type"))

    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    m_col1.metric("Total Part Uses", total_uses)
    m_col2.metric("Consumed", consumed_cnt)
    m_col3.metric("Handled", handled_cnt)
    m_col4.metric(
        "Unclassified",
        unclassified_cnt,
        delta=f"{unclassified_cnt} alerts" if unclassified_cnt > 0 else None,
        delta_color="inverse",
    )

    f_col1, f_col2 = st.columns([2, 2], vertical_alignment="center")
    with f_col1:
        status_filter = st.radio(
            "Filter status",
            options=["All", "Unclassified Only", "Classified Only"],
            horizontal=True,
            key=f"mat_status_filter_{scenario_id}",
        )
    with f_col2:
        stations = sorted({str(o.get("station") or "") for o in part_options if o.get("station")})
        station_filter = st.selectbox(
            "Station filter",
            options=["All Stations"] + stations,
            key=f"mat_station_filter_{scenario_id}",
        )

    filtered = part_options
    if status_filter == "Unclassified Only":
        filtered = [o for o in filtered if not o.get("handling_type")]
    elif status_filter == "Classified Only":
        filtered = [o for o in filtered if o.get("handling_type")]
    if station_filter != "All Stations":
        filtered = [o for o in filtered if str(o.get("station") or "") == station_filter]

    if not filtered:
        st.info("No part uses match the selected filters.")
    else:
        for opt in filtered:
            opt_id = opt["option_id"]
            p_num = opt["part_number"]
            p_desc = opt.get("part_description") or ""
            op_title = opt.get("operation") or "Operation"
            stn = opt.get("station") or ""
            sec_name = opt.get("section_name") or ""
            current_ht = opt.get("handling_type")
            placements = opt.get("placements") or []

            with st.container(border=True):
                c_top1, c_top2 = st.columns([3, 1], vertical_alignment="center")
                with c_top1:
                    st.markdown(
                        f"**Part {p_num}** — {p_desc}  \n"
                        f"`Station: {stn}` · `Step: {op_title}`"
                        + (f" · Section: {sec_name}" if sec_name else "")
                    )
                with c_top2:
                    if not current_ht:
                        st.error("⚠️ Unclassified", icon=":material/warning:")
                    elif current_ht == "Consume":
                        st.success("📦 Consume", icon=":material/check_circle:")
                    else:
                        st.info("🖐️ Handle", icon=":material/pan_tool:")

                c_pl, c_sel, c_save = st.columns([2, 1.5, 1], vertical_alignment="bottom")
                selected_placement_id = opt.get("fishbone_assignment_id")
                with c_pl:
                    if not selected_placement_id and placements:
                        if len(placements) == 1:
                            selected_placement_id = placements[0]["fishbone_assignment_id"]
                            st.caption(f"Placement: {placements[0].get('use_description') or 'Default placement'} (Qty {placements[0].get('fishbone_quantity')})")
                        else:
                            pl_options = {
                                p["fishbone_assignment_id"]: (
                                    f"{p.get('use_description') or 'Placement'} (Qty {p.get('fishbone_quantity')})"
                                )
                                for p in placements
                            }
                            selected_placement_id = st.selectbox(
                                "Fishbone placement",
                                options=list(pl_options.keys()),
                                format_func=lambda k: pl_options.get(k, k),
                                key=f"mat_page_pl_{opt_id}",
                            )
                    elif selected_placement_id:
                        desc = opt.get("fishbone_use_description") or "Default placement"
                        st.caption(f"Placement: {desc}")
                    else:
                        st.caption("No placement linked (must be on Fishbone).")

                with c_sel:
                    options = ["(Unclassified)", "Consume", "Handle"]
                    cur_idx = 1 if current_ht == "Consume" else (2 if current_ht == "Handle" else 0)
                    new_ht = st.selectbox(
                        "Handling",
                        options=options,
                        index=cur_idx,
                        key=f"mat_page_ht_{opt_id}",
                    )
                with c_save:
                    save_val = None if new_ht == "(Unclassified)" else new_ht
                    is_changed = save_val != current_ht
                    if st.button(
                        "Update",
                        type="primary" if is_changed else "secondary",
                        icon=":material/save:",
                        key=f"mat_page_save_{opt_id}",
                        disabled=not is_changed or (save_val is not None and not selected_placement_id and not placements),
                        width="stretch",
                    ):
                        try:
                            editor = st.session_state.get("current_editor", "")
                            set_process_part_option_handling_type(
                                project_id=project_id,
                                scenario_id=scenario_id,
                                process_part_option_id=opt_id,
                                handling_type=save_val,
                                fishbone_assignment_id=selected_placement_id,
                            )
                            record_audit_event(
                                project_id=project_id,
                                table_name="Process part pairings",
                                action="Classify handling",
                                row_count=1,
                                editor_name=editor,
                                details={
                                    "scenario_id": scenario_id,
                                    "option_id": opt_id,
                                    "part_number": p_num,
                                    "handling_type": save_val,
                                    "source": "Materials Review page",
                                },
                            )
                            st.toast(f"Part {p_num} updated to {new_ht}!", icon=":material/check_circle:")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
    with st.expander("Materials Handling Audit History", expanded=False):
        history_df = audit_history(project_id, "Process part pairings", limit=50)
        if not history_df.empty:
            st.dataframe(history_df, hide_index=True, width="stretch")
        else:
            st.info("No materials handling audit records yet.")

