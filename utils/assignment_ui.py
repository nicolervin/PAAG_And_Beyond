"""Option A: Structured Assignment Dialog for Quality Requirements and Process Steps.

Provides a robust, native Streamlit modal for assigning Quality Requirements to multiple
Process at a Glance work elements filtered by Pitch / Station, with proactive Torque tooling
gap detection and inline equipment linking.
"""

from __future__ import annotations

from typing import Any
import pandas as pd
import streamlit as st

from utils.quality_store import (
    bulk_assign_quality_requirement,
    project_equipment_assets,
    quality_process_steps,
    quality_requirement_links,
    quality_requirements,
    step_equipment_tooling_status,
)
from utils.table_filters import request_table_editor_reset
from utils.traceability_store import quick_link_step_equipment

ASSIGN_REQ_DIALOG_OPEN_KEY = "show_assign_requirement_dialog"
ASSIGN_REQ_SELECTED_ID_KEY = "pending_assign_requirement_id"


def open_assign_requirement_dialog(requirement_id: str | None = None) -> None:
    """Set session state flags to display the assignment dialog on next rerun."""
    st.session_state[ASSIGN_REQ_DIALOG_OPEN_KEY] = True
    if requirement_id:
        st.session_state[ASSIGN_REQ_SELECTED_ID_KEY] = str(requirement_id)


def close_assign_requirement_dialog(project_id: str | None = None) -> None:
    """Clear session state flags for the assignment dialog."""
    st.session_state.pop(ASSIGN_REQ_DIALOG_OPEN_KEY, None)
    st.session_state.pop(ASSIGN_REQ_SELECTED_ID_KEY, None)
    if project_id:
        st.session_state.pop(f"assign_success_msg_{project_id}", None)
        st.session_state.pop(f"assign_steps_seq_{project_id}", None)


@st.dialog(
    "Assign Quality Requirement to Process Steps",
    width="large",
    on_dismiss=close_assign_requirement_dialog,
)
def render_assign_requirement_dialog(
    project_id: str,
    scenario_id: str,
    default_requirement_id: str | None = None,
) -> None:
    """Native Streamlit modal for bulk linking a quality requirement to process steps."""
    success_msg_key = f"assign_success_msg_{project_id}"
    if success_msg_key in st.session_state:
        st.success(st.session_state.pop(success_msg_key), icon=":material/check_circle:")

    seq_key = f"assign_steps_seq_{project_id}"
    seq = st.session_state.get(seq_key, 0)

    requirements = quality_requirements(project_id)
    if requirements.empty:
        st.warning("There are no saved Quality requirements in this project.")
        if st.button("Close", key=f"assign_close_empty_{project_id}"):
            close_assign_requirement_dialog(project_id)
            st.rerun()
        return

    # 1. Determine Selected Requirement
    req_labels: dict[str, str] = {}
    req_lookup: dict[str, dict[str, Any]] = {}
    for _, row in requirements.iterrows():
        rid = str(row["id"])
        uid = str(row.get("unique_identifier") or "No ID")
        desc = str(row.get("description") or "No description")
        rtype = str(row.get("requirement_type") or "General")
        req_labels[rid] = f"{uid} — {desc} ({rtype})"
        req_lookup[rid] = dict(row)

    req_id_to_select = (
        st.session_state.get(ASSIGN_REQ_SELECTED_ID_KEY)
        or default_requirement_id
        or (list(req_labels)[0] if req_labels else None)
    )
    if req_id_to_select not in req_labels:
        req_id_to_select = list(req_labels)[0]

    selected_req_id = st.selectbox(
        "Choose Quality Requirement to Assign",
        options=list(req_labels.keys()),
        index=list(req_labels.keys()).index(req_id_to_select),
        format_func=lambda rid: req_labels.get(rid, rid),
        key=f"assign_req_picker_{project_id}",
    )
    st.session_state[ASSIGN_REQ_SELECTED_ID_KEY] = selected_req_id

    req_data = req_lookup.get(selected_req_id, {})
    req_type = str(req_data.get("requirement_type") or "")
    req_desc = str(req_data.get("description") or "")
    is_torque = req_type.casefold() == "torque" or "torque" in req_desc.casefold()

    # Requirement Specification Card
    with st.container(border=True):
        c1, c2, c3 = st.columns([2, 1.5, 1.5])
        with c1:
            st.markdown(f"**Parameter:** {req_desc}")
            st.caption(f"Unique Identifier: `{req_data.get('unique_identifier') or '—'}`")
        with c2:
            st.markdown(f"**Type:** `{req_type or 'General'}`")
            if bool(req_data.get("pass_fail")):
                st.caption("Evaluation: Pass / Fail")
            else:
                target = req_data.get("target_value")
                tol = req_data.get("tolerances") or "±0"
                unit = req_data.get("unit") or ""
                st.caption(f"Target: {target} ({tol}) {unit}")
        with c3:
            if is_torque:
                st.info("🔧 Torque Requirement", icon=":material/handyman:")
            else:
                st.markdown(f"**Unit:** {req_data.get('unit') or '—'}")

    # 2. Process Steps Retrieval & Pitch Filtering (Option A)
    process_steps = quality_process_steps(project_id, scenario_id)
    if process_steps.empty:
        st.info("This planning scenario has no Process at a Glance steps available to receive a requirement.")
        if st.button("Close", key=f"assign_close_nosteps_{project_id}"):
            close_assign_requirement_dialog(project_id)
            st.rerun()
        return

    pitches = sorted([p for p in process_steps["pitch_name"].dropna().unique() if str(p).strip()])
    pitch_options = ["All Stations / Pitches", *pitches]

    f_col1, f_col2 = st.columns([2, 1])
    with f_col1:
        selected_pitch = st.selectbox(
            "Filter Process Steps by Station / Pitch",
            options=pitch_options,
            key=f"assign_pitch_filter_{project_id}_{selected_req_id}",
        )
    with f_col2:
        search_term = st.text_input(
            "Quick Search Steps",
            placeholder="Search Op ID or element...",
            key=f"assign_step_search_{project_id}_{selected_req_id}",
        ).strip().casefold()

    # Filter steps
    if selected_pitch != "All Stations / Pitches":
        scoped_steps = process_steps[process_steps["pitch_name"] == selected_pitch].copy()
    else:
        scoped_steps = process_steps.copy()

    if search_term:
        scoped_steps = scoped_steps[
            scoped_steps["op_id"].astype(str).str.casefold().str.contains(search_term)
            | scoped_steps["work_element"].astype(str).str.casefold().str.contains(search_term)
        ]

    # Check existing links for this requirement
    existing_links = quality_requirement_links(project_id, selected_req_id)
    already_linked_wids = set()
    if not existing_links.empty:
        scenario_links = existing_links.loc[
            existing_links["scenario_id"].astype(str).eq(scenario_id)
        ]
        already_linked_wids = set(scenario_links["work_element_id"].dropna().astype(str))

    available_steps = scoped_steps[~scoped_steps["id"].astype(str).isin(already_linked_wids)].copy()
    linked_steps_here = scoped_steps[scoped_steps["id"].astype(str).isin(already_linked_wids)].copy()

    step_labels: dict[str, str] = {}
    for _, row in available_steps.iterrows():
        wid = str(row["id"])
        op = str(row.get("op_id") or "No Op ID")
        we = str(row.get("work_element") or "Unnamed Work Element")
        pn = str(row.get("pitch_name") or "Unassigned Pitch")
        step_labels[wid] = f"{op} — {we} ({pn})"

    ms_key = f"assign_steps_multiselect_{project_id}_{selected_req_id}_{selected_pitch}_{seq}"

    # Selection Quick Actions
    act_col1, act_col2, _ = st.columns([1.5, 1.2, 2])
    with act_col1:
        if st.button(
            "Select All Available Steps",
            icon=":material/select_all:",
            key=f"assign_select_all_{project_id}_{selected_pitch}_{seq}",
            disabled=not step_labels,
        ):
            st.session_state[ms_key] = list(step_labels.keys())
            st.rerun()
    with act_col2:
        if st.button(
            "Clear Selection",
            icon=":material/clear_all:",
            key=f"assign_clear_{project_id}_{selected_pitch}_{seq}",
            disabled=not step_labels,
        ):
            st.session_state[ms_key] = []
            st.rerun()

    selected_step_ids = st.multiselect(
        f"Select Process Steps to Attach ({len(step_labels)} available on {selected_pitch})",
        options=list(step_labels.keys()),
        default=st.session_state.get(ms_key, []),
        format_func=lambda wid: step_labels.get(str(wid), str(wid)),
        key=ms_key,
        help="Check one or more process steps to receive this Quality requirement.",
    )

    if not linked_steps_here.empty:
        st.caption(
            f"ℹ️ {len(linked_steps_here)} step(s) on this station already have this requirement linked and are excluded."
        )

    # 3. Torque Tooling Advisory & Inline Quick-Link (Feature 2)
    link_torque_tool = False
    selected_tool_id: str | None = None
    unequipped_step_ids: list[str] = []

    if is_torque and selected_step_ids:
        tooling_status = step_equipment_tooling_status(project_id, scenario_id, selected_step_ids)
        unequipped_step_ids = [
            wid for wid in selected_step_ids
            if not any(eq.get("is_torque") for eq in tooling_status.get(wid, []))
        ]

        if unequipped_step_ids:
            with st.container(border=True):
                st.warning(
                    f"⚠️ **Tooling Gap Advisory**: {len(unequipped_step_ids)} of the selected step(s) "
                    "do not have torque equipment linked in the Equipment module.",
                    icon=":material/warning:",
                )
                disp_unequipped = [step_labels.get(wid, wid) for wid in unequipped_step_ids[:4]]
                for s_name in disp_unequipped:
                    st.caption(f"• {s_name}")
                if len(unequipped_step_ids) > 4:
                    st.caption(f"• ...and {len(unequipped_step_ids) - 4} more step(s)")

                link_torque_tool = st.checkbox(
                    "Also link a torque tool to these unequipped step(s)",
                    value=False,
                    key=f"assign_link_torque_chk_{project_id}_{selected_req_id}_{seq}",
                    help="Automatically creates equipment process links for the unequipped steps.",
                )
                if link_torque_tool:
                    torque_assets = project_equipment_assets(project_id, torque_only=True)
                    if not torque_assets:
                        torque_assets = project_equipment_assets(project_id, torque_only=False)
                    if torque_assets:
                        eq_opts = {
                            a["id"]: f"{a['name']} [{a.get('equipment_type') or 'Tool'}]"
                            for a in torque_assets
                        }
                        selected_tool_id = st.selectbox(
                            "Select Torque Equipment Asset to Link",
                            options=list(eq_opts.keys()),
                            format_func=lambda eid: eq_opts.get(eid, eid),
                            key=f"assign_torque_asset_sel_{project_id}_{selected_req_id}_{seq}",
                        )
                    else:
                        st.info("No equipment assets registered in this project yet.")
        else:
            st.success(
                "✅ All selected process steps already have torque equipment assigned in the Equipment module.",
                icon=":material/check_circle:",
            )

    # 4. Confirmation & Execution
    st.divider()
    e_col1, e_col2 = st.columns([1.5, 2])
    with e_col1:
        current_editor = st.session_state.get("current_editor", "")
        editor_name = st.text_input(
            "Current Editor",
            value=current_editor,
            placeholder="Enter your name...",
            key=f"assign_editor_input_{project_id}",
        ).strip()
        if not editor_name:
            st.caption("⚠️ Editor name is required to log the audit event.")

    with e_col2:
        st.write("")  # spacing
        st.write("")
        btn_close, btn_submit = st.columns([1, 1.8])
        with btn_close:
            if st.button("Close", key=f"assign_close_{project_id}", icon=":material/close:"):
                close_assign_requirement_dialog(project_id)
                st.rerun()

        with btn_submit:
            submit_disabled = not selected_step_ids or not editor_name
            count_label = f" ({len(selected_step_ids)})" if selected_step_ids else ""
            if st.button(
                f"Attach Requirement{count_label}",
                type="primary",
                icon=":material/link:",
                disabled=submit_disabled,
                key=f"assign_confirm_submit_{project_id}",
            ):
                try:
                    result = bulk_assign_quality_requirement(
                        project_id=project_id,
                        scenario_id=scenario_id,
                        quality_requirement_id=selected_req_id,
                        work_element_ids=selected_step_ids,
                        editor_name=editor_name,
                    )

                    # Update current editor in session state
                    st.session_state["current_editor"] = editor_name

                    # If torque tool linking requested, link to unequipped steps
                    linked_tools_count = 0
                    if link_torque_tool and selected_tool_id and unequipped_step_ids:
                        for wid in unequipped_step_ids:
                            try:
                                quick_link_step_equipment(
                                    project_id=project_id,
                                    scenario_id=scenario_id,
                                    work_element_id=wid,
                                    equipment_id=selected_tool_id,
                                    editor_name=editor_name,
                                )
                                linked_tools_count += 1
                            except Exception:
                                pass

                    created = result.get("created_count", 0)
                    tool_msg = f" and linked torque equipment to {linked_tools_count} step(s)" if linked_tools_count else ""
                    st.toast(
                        f"Successfully attached requirement to {created} process step(s){tool_msg}!",
                        icon=":material/check_circle:",
                    )
                    request_table_editor_reset(f"quality_requirements_editor_{project_id}")
                    st.session_state[f"assign_success_msg_{project_id}"] = (
                        f"Successfully attached requirement to {created} process step(s){tool_msg}!"
                    )
                    st.session_state[seq_key] = seq + 1
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
