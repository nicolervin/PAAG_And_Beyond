"""Streamlit user interface for the Cross-Functional Traceability & Discrepancy Matrix.

Connects live PAAG Work Elements, Quality Requirement Assignments, PFMEA Entries & Controls,
Control Plan (MCP) Characteristics, and Equipment/Tooling Placements.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from utils.assignment_ui import open_assign_requirement_dialog
from utils.equipment_store import equipment_assets
from utils.table_ui import dataframe_to_excel
from utils.traceability_store import (
    align_control_plan_specification,
    cross_functional_traceability_matrix,
    quick_link_step_equipment,
)


def _navigate_to_tab(project_id: str, tab_name: str) -> None:
    """Switch active tab in the Functional Quality page and trigger rerun."""
    st.session_state[f"quality_page_tabs_{project_id}"] = tab_name
    st.rerun()


@st.dialog("Review & Align Specification")
def align_specification_dialog(project_id: str, scenario_id: str) -> None:
    """Individual review and alignment of drifted Control Plan specification."""
    pending_key = f"traceability_pending_align_spec_{project_id}"
    pending = st.session_state.get(pending_key)
    if not pending:
        return

    st.markdown(
        f"**Operation**: `[{pending.get('op_id', 'Op ID')}]` {pending.get('operation', '')}<br/>"
        f"**Quality Requirement**: `{pending.get('quality_uid', '')}`",
        unsafe_allow_html=True,
    )
    st.write("")

    c1, c2 = st.columns(2)
    with c1:
        st.caption("📋 **Published Quality Requirement Spec**")
        st.info(f"**{pending.get('published_spec') or '(None)'}**")
    with c2:
        st.caption("⚙️ **Current Control Plan Spec (Drifted)**")
        st.warning(f"**{pending.get('current_cp_spec') or '(None)'}**")

    st.caption(
        "Aligning this specification updates the Control Plan characteristic to match "
        "the published Quality Requirement and records a new baseline fingerprint."
    )

    editor_default = st.session_state.get("current_editor", "")
    editor_name = st.text_input(
        "Editor Name",
        value=editor_default,
        key=f"align_spec_editor_{project_id}",
        help="Name of the quality engineer approving this alignment",
    )

    act_col1, act_col2 = st.columns([1, 1])
    with act_col1:
        if act_col1.button("Cancel", key=f"cancel_align_spec_{project_id}", use_container_width=True):
            st.session_state.pop(pending_key, None)
            st.rerun()
    with act_col2:
        if act_col2.button(
            "Align Specification",
            type="primary",
            icon=":material/sync:",
            key=f"confirm_align_spec_{project_id}",
            use_container_width=True,
            disabled=not bool(editor_name.strip()),
        ):
            try:
                align_control_plan_specification(
                    project_id=project_id,
                    scenario_id=scenario_id,
                    control_plan_item_id=pending["control_plan_item_id"],
                    editor_name=editor_name.strip(),
                )
                st.session_state["current_editor"] = editor_name.strip()
                st.session_state.pop(pending_key, None)
                st.toast("Control Plan specification aligned successfully", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


@st.dialog("Quick-Link Tooling / Equipment")
def quick_link_equipment_dialog(project_id: str, scenario_id: str) -> None:
    """Quickly link a placed equipment asset to a work element with a tooling gap."""
    pending_key = f"traceability_pending_quick_link_{project_id}"
    pending = st.session_state.get(pending_key)
    if not pending:
        return

    st.markdown(
        f"**Operation**: `[{pending.get('op_id', 'Op ID')}]` {pending.get('operation', '')}<br/>"
        f"**Pitch**: `{pending.get('pitch', '')}`<br/>"
        f"**Requirement**: `{pending.get('quality_uid', '')}` — {pending.get('quality_description', '')}",
        unsafe_allow_html=True,
    )
    st.write("")

    eq_df = equipment_assets(project_id, scenario_id)
    if eq_df.empty:
        st.warning(
            "No equipment assets are registered in this project. "
            "Add equipment in the **Equipment** tab first."
        )
        if st.button("Close", key=f"close_empty_eq_{project_id}"):
            st.session_state.pop(pending_key, None)
            st.rerun()
        return

    is_torque = "torque" in str(pending.get("quality_type", "")).casefold()
    eq_list = eq_df.to_dict("records")
    if is_torque:
        eq_list = sorted(
            eq_list,
            key=lambda x: (
                0 if "torque" in str(x.get("equipment_type", "")).casefold() else 1,
                str(x.get("name", "")),
            ),
        )

    eq_options = [str(e["id"]) for e in eq_list]
    eq_labels = {
        str(e["id"]): (
            f"{e['name']} ({e.get('equipment_type') or 'Tool'})"
            + (f" · Pitch {e.get('pitch_number')}" if e.get("pitch_number") else "")
        )
        for e in eq_list
    }

    selected_eq_id = st.selectbox(
        "Select Equipment / Tool to link",
        options=eq_options,
        format_func=lambda eid: eq_labels.get(eid, eid),
        key=f"quick_link_eq_select_{project_id}",
    )

    editor_default = st.session_state.get("current_editor", "")
    editor_name = st.text_input(
        "Editor Name",
        value=editor_default,
        key=f"quick_link_editor_{project_id}",
    )

    act_col1, act_col2 = st.columns([1, 1])
    with act_col1:
        if act_col1.button("Cancel", key=f"cancel_quick_link_{project_id}", use_container_width=True):
            st.session_state.pop(pending_key, None)
            st.rerun()
    with act_col2:
        if act_col2.button(
            "Link Equipment to Step",
            type="primary",
            icon=":material/link:",
            key=f"confirm_quick_link_{project_id}",
            use_container_width=True,
            disabled=not bool(selected_eq_id) or not bool(editor_name.strip()),
        ):
            try:
                quick_link_step_equipment(
                    project_id=project_id,
                    scenario_id=scenario_id,
                    work_element_id=pending["work_element_id"],
                    equipment_id=selected_eq_id,
                    editor_name=editor_name.strip(),
                )
                st.session_state["current_editor"] = editor_name.strip()
                st.session_state.pop(pending_key, None)
                st.toast("Equipment linked to step successfully", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def render_traceability_matrix_tab(
    project_id: str,
    scenario_id: str,
    active_scenario: dict[str, Any] | None,
) -> None:
    """Render the Cross-Functional Traceability & Discrepancy Matrix tab."""
    if not active_scenario:
        st.info("Select an active planning scenario before opening the Traceability Matrix.")
        return

    # Check for open dialog requests
    align_pending_key = f"traceability_pending_align_spec_{project_id}"
    if st.session_state.get(align_pending_key):
        align_specification_dialog(project_id, scenario_id)

    quick_link_pending_key = f"traceability_pending_quick_link_{project_id}"
    if st.session_state.get(quick_link_pending_key):
        quick_link_equipment_dialog(project_id, scenario_id)

    # 1. Fetch matrix data
    matrix_data = cross_functional_traceability_matrix(project_id, scenario_id)
    rows = matrix_data["rows"]
    summary = matrix_data["summary"]
    pitches = matrix_data["pitches"]

    col_head, col_assign_btn = st.columns([3, 1])
    with col_head:
        st.markdown("### 📊 Cross-Functional Traceability & Discrepancy Matrix")
        st.caption(
            "Live cross-functional traceability linking **Process at a Glance (PAAG) Work Elements**, "
            "**Quality Requirement Assignments**, **PFMEA Failure Modes & Controls**, "
            "**Manufacturing Control Plan (MCP)**, and **Placed Equipment & Tooling**."
        )
    with col_assign_btn:
        st.write("")
        if st.button(
            "Assign Requirements",
            icon=":material/playlist_add_check:",
            key=f"traceability_assign_req_btn_{project_id}",
            help="Open assignment dialog to filter steps by Pitch and bulk attach Quality requirements.",
        ):
            open_assign_requirement_dialog()
            st.rerun()

    if summary["total_steps"] == 0:
        st.info(
            "No process steps found in the active planning scenario. "
            "Create or import work elements in Process at a Glance (PAAG) to populate the traceability matrix."
        )
        return

    # 2. KPI Scorecard
    col_kpi1, col_kpi2, col_kpi3, col_kpi4, col_kpi5 = st.columns(5)
    col_kpi1.metric(
        "Fully Protected",
        f"{summary['fully_protected_pct']}%",
        help="Percentage of quality-required process steps with complete PFMEA and Control Plan protection",
    )
    col_kpi2.metric(
        "Critical Gaps",
        f"🔴 {summary['critical_gap_steps']}",
        help="Process steps with quality specs or CTQs missing PFMEA controls or Control Plan coverage",
    )
    col_kpi3.metric(
        "Warnings & Drift",
        f"🟡 {summary['warning_steps']}",
        help="Process steps with tooling gaps, pitch mismatches, or specification drift",
    )
    col_kpi4.metric(
        "Protected Steps",
        f"🟢 {summary['protected_steps']}",
        help="Process steps with full active coverage in PFMEA and Control Plan",
    )
    col_kpi5.metric(
        "Total Steps",
        f"{summary['total_steps']}",
        delta=f"{summary['uncovered_steps']} standard steps",
        delta_color="off",
        help="Total work elements in this scenario (including steps without drawing quality requirements)",
    )

    # Status alerts
    if summary["critical_gap_steps"] > 0:
        st.error(
            f"⚠️ **{summary['critical_gap_steps']} process step(s) have Critical Coverage Gaps.** "
            f"Quality requirements or Critical-to-Quality (CTQ) failure modes lack active PFMEA controls "
            f"or active characteristics on the Control Plan.",
            icon=":material/error:",
        )
    elif summary["warning_steps"] > 0:
        st.warning(
            f"⚡ **{summary['warning_steps']} process step(s) have Warnings or Discrepancies.** "
            f"Tooling gaps or specification drift detected between Control Plan and published Quality specifications.",
            icon=":material/warning:",
        )
    else:
        st.success(
            "✅ **All Quality Requirements and CTQ failure modes have active PFMEA and Control Plan protection.**",
            icon=":material/verified:",
        )

    # 3. Direct Navigation / Quick Jump Bar
    with st.expander("⚡ Quick Navigation to Quality Disciplines", expanded=False):
        nav_col1, nav_col2, nav_col3, nav_col4 = st.columns(4)
        with nav_col1:
            if st.button("📋 Requirements Repository", use_container_width=True, key=f"nav_req_{project_id}"):
                _navigate_to_tab(project_id, "Requirements repository")
        with nav_col2:
            if st.button("⚡ PFMEA", use_container_width=True, key=f"nav_pfmea_{project_id}"):
                _navigate_to_tab(project_id, "PFMEA")
        with nav_col3:
            if st.button("🛡️ Control Plan", use_container_width=True, key=f"nav_cp_{project_id}"):
                _navigate_to_tab(project_id, "Control Plan")
        with nav_col4:
            if st.button("🔧 Equipment", use_container_width=True, key=f"nav_eq_{project_id}"):
                _navigate_to_tab(project_id, "Equipment")

    # 4. Filter Controls
    f_col1, f_col2, f_col3, f_col4 = st.columns([2, 1.8, 1.8, 2.5], vertical_alignment="bottom")

    status_options = [
        "All Statuses",
        "🔴 Critical Gaps",
        "🟡 Warnings & Drift",
        "🟢 Protected",
        "⚪ Uncovered",
    ]
    selected_status = f_col1.selectbox(
        "Filter by Status",
        options=status_options,
        key=f"traceability_status_filter_{project_id}",
    )

    pitch_options = ["All Pitches"] + pitches
    selected_pitch = f_col2.selectbox(
        "Filter by Pitch",
        options=pitch_options,
        key=f"traceability_pitch_filter_{project_id}",
    )

    discrepancies_only = f_col3.checkbox(
        "Discrepancies only",
        value=(summary["critical_gap_steps"] + summary["warning_steps"]) > 0,
        key=f"traceability_discrepancies_only_{project_id}",
        help="Show only rows with Critical Gaps or Warnings requiring engineering review",
    )

    search_query = f_col4.text_input(
        "Search matrix",
        placeholder="Search Op ID, spec, failure mode...",
        key=f"traceability_search_query_{project_id}",
    ).strip().casefold()

    # 5. Filter the rows
    filtered_rows = []
    for r in rows:
        # Status filter
        if selected_status == "🔴 Critical Gaps" and r["status"] != "CRITICAL_GAP":
            continue
        if selected_status == "🟡 Warnings & Drift" and r["status"] != "WARNING":
            continue
        if selected_status == "🟢 Protected" and r["status"] != "PROTECTED":
            continue
        if selected_status == "⚪ Uncovered" and r["status"] != "UNCOVERED":
            continue

        # Pitch filter
        if selected_pitch != "All Pitches" and r["pitch"] != selected_pitch:
            continue

        # Discrepancies only
        if discrepancies_only and r["status"] not in ("CRITICAL_GAP", "WARNING"):
            continue

        # Search query
        if search_query:
            haystack = " ".join([
                str(r.get("op_id", "")),
                str(r.get("pitch", "")),
                str(r.get("operation", "")),
                str(r.get("quality_uid", "")),
                str(r.get("quality_type", "")),
                str(r.get("quality_description", "")),
                str(r.get("published_spec", "")),
                str(r.get("pfmea_failure_mode", "")),
                str(r.get("pfmea_class_code", "")),
                str(r.get("control_plan_pr_number", "")),
                str(r.get("control_plan_spec", "")),
                str(r.get("equipment_display", "")),
                str(r.get("discrepancy_summary", "")),
            ]).casefold()
            if search_query not in haystack:
                continue

        filtered_rows.append(r)

    st.caption(f"Showing **{len(filtered_rows)}** of **{len(rows)}** matrix entries")

    # 6. Actionable Discrepancy Cards
    actionable_rows = [r for r in filtered_rows if r["status"] in ("CRITICAL_GAP", "WARNING")]

    if actionable_rows:
        with st.expander(f"⚠️ Items Requiring Engineering Attention ({len(actionable_rows)})", expanded=True):
            for row_idx, a_row in enumerate(actionable_rows):
                with st.container(border=True):
                    h_col, b_col = st.columns([4, 1.2], vertical_alignment="center")
                    with h_col:
                        op_lbl = a_row["op_id"] or "Op ID unavailable"
                        st.markdown(
                            f"**[{op_lbl}] {a_row['operation']}** · Pitch `{a_row['pitch']}` "
                            f"(Seq {a_row.get('sequence', 0)})"
                        )
                    with b_col:
                        st.markdown(f"**{a_row['status_label']}**")

                    # Discrepancies
                    for disc in a_row.get("discrepancies", []):
                        sev_color = "#dc2626" if disc.get("severity") == "CRITICAL" else "#d97706"
                        st.markdown(
                            f"<div style='font-size: 0.88rem; margin: 3px 0;'>"
                            f"<span style='color: {sev_color}; font-weight: 700;'>• {disc.get('title')}:</span> "
                            f"{disc.get('message')}</div>",
                            unsafe_allow_html=True,
                        )

                    # Action buttons
                    act1, act2, act3 = st.columns([1.5, 1.5, 3], vertical_alignment="center")

                    # Spec Drift -> Align
                    if a_row.get("spec_drift") and a_row.get("control_plan_item_id"):
                        with act1:
                            if st.button(
                                "Align Spec",
                                key=f"btn_align_{row_idx}_{a_row['work_element_id']}_{a_row['quality_assignment_id']}",
                                icon=":material/sync:",
                                help="Align Control Plan spec with published Quality spec",
                            ):
                                st.session_state[align_pending_key] = {
                                    "control_plan_item_id": a_row["control_plan_item_id"],
                                    "quality_uid": a_row["quality_uid"],
                                    "published_spec": a_row["published_spec"],
                                    "current_cp_spec": a_row["control_plan_spec"],
                                    "operation": a_row["operation"],
                                    "op_id": a_row["op_id"],
                                }
                                st.rerun()

                    # Missing Equipment -> Quick Link
                    has_tooling_gap = any(d.get("code") == "TOOLING_GAP" for d in a_row.get("discrepancies", []))
                    if has_tooling_gap:
                        with act2:
                            if st.button(
                                "Link Tooling",
                                key=f"btn_eq_{row_idx}_{a_row['work_element_id']}_{a_row['quality_assignment_id']}",
                                icon=":material/link:",
                                help="Link placed equipment to this step",
                            ):
                                st.session_state[quick_link_pending_key] = {
                                    "work_element_id": a_row["work_element_id"],
                                    "op_id": a_row["op_id"],
                                    "pitch": a_row["pitch"],
                                    "operation": a_row["operation"],
                                    "quality_uid": a_row["quality_uid"],
                                    "quality_type": a_row["quality_type"],
                                    "quality_description": a_row["quality_description"],
                                }
                                st.rerun()

                    # Navigation shortcuts
                    has_cp_gap = any(
                        d.get("code") in ("MISSING_CONTROL_PLAN", "EXCLUDED_FROM_CONTROL_PLAN", "UNMITIGATED_CTQ")
                        for d in a_row.get("discrepancies", [])
                    )
                    has_pfmea_gap = any(
                        d.get("code") in ("MISSING_PFMEA_CONTROL", "MISSING_PFMEA_ENTRY")
                        for d in a_row.get("discrepancies", [])
                    )

                    with act3:
                        if has_cp_gap:
                            if st.button(
                                "Open in Control Plan",
                                key=f"btn_cp_jump_{row_idx}_{a_row['work_element_id']}",
                                icon=":material/shield:",
                            ):
                                _navigate_to_tab(project_id, "Control Plan")
                        elif has_pfmea_gap:
                            if st.button(
                                "Open in PFMEA",
                                key=f"btn_pfmea_jump_{row_idx}_{a_row['work_element_id']}",
                                icon=":material/bolt:",
                            ):
                                _navigate_to_tab(project_id, "PFMEA")

    # 7. Comprehensive Traceability Table
    display_rows = []
    for r in filtered_rows:
        display_rows.append({
            "Status": r.get("status_label", ""),
            "Op ID": r.get("op_id", ""),
            "Pitch": r.get("pitch", ""),
            "Operation": r.get("operation", ""),
            "Quality UID": r.get("quality_uid", ""),
            "Published Spec": r.get("published_spec", ""),
            "PFMEA Class": r.get("pfmea_class_code", ""),
            "PFMEA Failure Mode": r.get("pfmea_failure_mode", ""),
            "Control Plan Pr. Nº": r.get("control_plan_pr_number", ""),
            "Control Plan Spec": r.get("control_plan_spec", ""),
            "Equipment": r.get("equipment_display", ""),
            "Discrepancies": r.get("discrepancy_summary", ""),
        })

    table_df = pd.DataFrame(display_rows)

    if table_df.empty:
        st.info("No records match the active filter criteria.")
    else:
        st.dataframe(
            table_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Op ID": st.column_config.TextColumn("Op ID", width="small"),
                "Pitch": st.column_config.TextColumn("Pitch", width="small"),
                "Operation": st.column_config.TextColumn("Operation", width="medium"),
                "Quality UID": st.column_config.TextColumn("Quality UID", width="small"),
                "Published Spec": st.column_config.TextColumn("Published Spec", width="medium"),
                "PFMEA Class": st.column_config.TextColumn("Class", width="small"),
                "PFMEA Failure Mode": st.column_config.TextColumn("Failure Mode", width="medium"),
                "Control Plan Pr. Nº": st.column_config.TextColumn("Pr. Nº", width="small"),
                "Control Plan Spec": st.column_config.TextColumn("CP Spec", width="medium"),
                "Equipment": st.column_config.TextColumn("Equipment / Tooling", width="medium"),
                "Discrepancies": st.column_config.TextColumn("Discrepancy Details", width="large"),
            },
        )

        # Excel export
        try:
            excel_bytes = dataframe_to_excel(table_df)
            st.download_button(
                "📥 Export Traceability Matrix (Excel)",
                data=excel_bytes,
                file_name=f"traceability_matrix_{project_id}_{scenario_id}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"export_matrix_excel_{project_id}",
            )
        except Exception:
            pass
