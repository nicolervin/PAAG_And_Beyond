from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from utils.equipment_ui import render_functional_equipment_tab
from utils.ppe_poster import (
    build_jsa_poster_html,
    build_ppe_poster_html,
    get_jsa_icon_data_uri,
    get_ppe_icon_data_uri,
)
from utils.scope_ui import page_title_with_scope
from utils.store import (
    STANDARD_BASELINE_PPE,
    STANDARD_PPE_OPTIONS,
    acknowledge_safety_upstream_changes,
    apply_standard_baseline_ppe,
    delete_safety_requirements,
    derive_ppe_hazards_and_actions,
    ergonomics_work_elements,
    get_planning_scenario,
    get_ppe_catalog_item,
    pitch_jsa_poster_summary,
    pitch_ppe_poster_summary,
    safety_requirement_history,
    safety_requirements,
    save_safety_requirements,
    tag_ppe_to_work_elements,
    update_ppe_item_element_tags_on_pitch,
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
    "Safety",
    scope="scenario-aware",
    scenario_name=_text((scenario or {}).get("name")) or None,
    help_text=(
        "Safety requirements, Job Safety Analysis (JSA) posters, and 11×17 PPE posters use the active "
        "planning scenario. Shared Equipment identity is project-wide while placement uses the active planning scenario."
    ),
)
st.caption(
    "Pair PAAG work elements with required PPE, document Potential Errors / Hazards and Actions, "
    "and generate pitch-by-pitch Job Safety Analysis (JSA) and 11\"×17\" Minimum PPE Requirements posters."
)
if not project_id or not scenario:
    st.info("Select an active planning scenario to manage Safety requirements.")
    st.stop()

safety_tab_key = f"safety_page_tabs_{project_id}"
poster_pitch_state_key = f"safety_poster_pitch_{scenario_id}"
poster_view_mode_key = f"safety_poster_view_mode_{scenario_id}"

JSA_VIEW_LABEL = "📋 JSA Poster (FRM-GEA-SAF-085)"
PPE_VIEW_LABEL = "🛡️ 11×17 PPE Poster"
BOTH_VIEW_LABEL = "📑 Both Posters Side-by-Side"
POSTER_VIEW_OPTIONS = [JSA_VIEW_LABEL, PPE_VIEW_LABEL, BOTH_VIEW_LABEL]

qp_pitch_id = _text(st.query_params.get("pitch_id"))
if qp_pitch_id:
    st.session_state[poster_pitch_state_key] = qp_pitch_id
    st.session_state["safety_scroll_to_posters"] = True
    try:
        del st.query_params["pitch_id"]
    except Exception:
        pass

qp_tab = _text(st.query_params.get("tab")).casefold()
if qp_tab in {"jsa", "jsa poster", "jsa_poster"}:
    st.session_state[safety_tab_key] = "Review"
    st.session_state[poster_view_mode_key] = JSA_VIEW_LABEL
    st.session_state["safety_scroll_to_posters"] = True
    try:
        del st.query_params["tab"]
    except Exception:
        pass
elif qp_tab in {"poster", "ppe poster", "ppe_poster"}:
    st.session_state[safety_tab_key] = "Review"
    st.session_state[poster_view_mode_key] = PPE_VIEW_LABEL
    st.session_state["safety_scroll_to_posters"] = True
    try:
        del st.query_params["tab"]
    except Exception:
        pass
elif qp_tab == "review":
    st.session_state[safety_tab_key] = "Review"
    try:
        del st.query_params["tab"]
    except Exception:
        pass
elif qp_tab == "equipment":
    st.session_state[safety_tab_key] = "Equipment"
    try:
        del st.query_params["tab"]
    except Exception:
        pass

# Normalize any legacy tab state ("JSA Poster" / "PPE Poster") into the unified Review tab + poster mode
cur_tab_state = _text(st.session_state.get(safety_tab_key))
if cur_tab_state == "JSA Poster":
    st.session_state[safety_tab_key] = "Review"
    st.session_state[poster_view_mode_key] = JSA_VIEW_LABEL
    st.session_state["safety_scroll_to_posters"] = True
elif cur_tab_state == "PPE Poster":
    st.session_state[safety_tab_key] = "Review"
    st.session_state[poster_view_mode_key] = PPE_VIEW_LABEL
    st.session_state["safety_scroll_to_posters"] = True

review_tab, equipment_tab = guarded_tabs(
    ["Review", "Equipment"],
    key=safety_tab_key,
)
if equipment_tab.open:
    with equipment_tab:
        render_functional_equipment_tab(project_id, scenario_id, "Safety")
elif review_tab.open:
    with review_tab:
        logical_editor_key = f"safety_requirements_editor_{project_id}_{scenario_id}"
        editor_key = apply_pending_table_editor_reset(logical_editor_key)
        pending_delete_key = f"safety_requirements_pending_delete_{project_id}_{scenario_id}"

        # Load pre-populated PAAG work elements + saved Safety requirements
        saved = safety_requirements(
            project_id, scenario_id, include_unassigned_steps=True
        ).copy()
        work_elements = ergonomics_work_elements(project_id, scenario_id)
        work_labels = {
            _text(row["id"]): " · ".join(
                value
                for value in [_text(row["work_element_label"]), _text(row["pitch"]) or "Unassigned"]
                if value
            )
            or _text(row["id"])
            for _, row in work_elements.iterrows()
        }

        ppe_options = list(
            dict.fromkeys(
                [
                    *STANDARD_PPE_OPTIONS,
                    *[
                        str(item).strip()
                        for ppe_list in saved.get("ppe", [])
                        if isinstance(ppe_list, (list, tuple, set))
                        for item in ppe_list
                        if str(item).strip()
                    ],
                ]
            )
        )

        # Compute scenario-wide unassigned PPE steps and pitch summaries
        active_we_with_ppe: set[str] = set()
        if not saved.empty:
            for _, s_row in saved.iterrows():
                if not bool(s_row.get("active", True)):
                    continue
                row_ppe = s_row.get("ppe")
                if isinstance(row_ppe, (list, tuple, set)) and len(row_ppe) > 0:
                    active_we_with_ppe.add(_text(s_row.get("work_element_id")))
        all_we_ids = [
            _text(row["id"])
            for _, row in work_elements.iterrows()
            if _text(row.get("id"))
        ]
        unassigned_we_ids = [wid for wid in all_we_ids if wid not in active_we_with_ppe]

        poster_summaries = pitch_ppe_poster_summary(project_id, scenario_id)
        jsa_summaries = pitch_jsa_poster_summary(project_id, scenario_id)
        poster_by_pid = {str(item["pitch_id"]): item for item in poster_summaries}
        jsa_by_pid = {str(item["pitch_id"]): item for item in jsa_summaries}
        pid_by_pitch_num = {
            _text(item.get("pitch_number")): str(item["pitch_id"])
            for item in poster_summaries
            if _text(item.get("pitch_number"))
        }

        with st.container(border=True):
            base_col1, base_col2 = st.columns([3.2, 1.4], vertical_alignment="center")
            with base_col1:
                st.markdown("**🛡️ Standard Baseline PPE & Pitch Hierarchy Rollup**")
                st.caption(
                    f"Standard floor baseline PPE is **{', '.join(STANDARD_BASELINE_PPE)}**. "
                    "When rolling up step PPE to a workstation pitch (for PAAG slides, the JSA Poster, and the 11×17 PPE Poster), "
                    "duplicate items are listed once and higher protection levels automatically override lower levels "
                    "(*Cut Level 6 > 5 > 4 > 3 > 2 > 1 Gloves*, *Hard Hat > Bump Cap*, *Safety Toe Shoes > Sturdy Closed Toe and Heel Shoes*, "
                    "*Foam Lined Safety Glasses > Safety Glasses*)."
                )
            with base_col2:
                if st.button(
                    f"Apply Standard Baseline PPE ({len(unassigned_we_ids)} unassigned)"
                    if unassigned_we_ids
                    else "All Steps Have PPE Assigned",
                    type="secondary" if not unassigned_we_ids else "primary",
                    icon=":material/verified_user:",
                    disabled=not unassigned_we_ids,
                    width="stretch",
                    key=f"btn_apply_baseline_all_{project_id}_{scenario_id}",
                    help=(
                        "Assign Cut Level 2 Gloves, Safety Glasses, and Sturdy Closed Toe and Heel Shoes "
                        "to all Process at a Glance work elements in this scenario that do not yet have active PPE."
                    ),
                ):
                    try:
                        res = apply_standard_baseline_ppe(
                            project_id,
                            scenario_id,
                            work_element_ids=unassigned_we_ids,
                            editor_name=_text(st.session_state.get("current_editor")) or "Collaborator",
                        )
                        request_table_editor_reset(editor_key)
                        st.toast(
                            f"Applied standard baseline PPE to {res['row_count']} unassigned Process step(s)",
                            icon=":material/check_circle:",
                        )
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

        editable_table_heading("Safety requirements")
        st.caption(
            "Pre-populated with all Process at a Glance work elements and their Pitch. "
            "Assign required PPE, Potential Errors / Hazards, and Actions in the table below (or in the interactive Pitch Poster section beneath), "
            "or click **View JSA/PPE Poster** on any row to jump directly to that pitch's JSA and PPE posters below."
        )
        if "sync_status" not in saved.columns:
            saved["sync_status"] = "Synced"
        if "upstream_changed" not in saved.columns:
            saved["upstream_changed"] = False
        if "upstream_diff_summary" not in saved.columns:
            saved["upstream_diff_summary"] = ""
        if "potential_hazards" not in saved.columns:
            saved["potential_hazards"] = ""
        if "proposed_actions" not in saved.columns:
            saved["proposed_actions"] = ""
        if "pitch_id" not in saved.columns:
            saved["pitch_id"] = ""
        saved["view_poster"] = "View JSA/PPE Poster"

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
                "potential_hazards",
                "proposed_actions",
                "upstream_diff_summary",
            ],
            labels={"sync_status": "Sync status", "active": "Active", "pitch": "Pitch"},
            reset_widget_keys=[editor_key],
        )
        if filter_changed_only:
            visible = visible[visible["upstream_changed"].fillna(False).astype(bool)].copy()

        pitch_sort_init_key = f"_safety_default_pitch_sort_init_{project_id}_{scenario_id}"
        if not st.session_state.get(pitch_sort_init_key):
            st.session_state[f"{logical_editor_key}_external_sort_column"] = "pitch"
            st.session_state[pitch_sort_init_key] = True

        editor_rows = direct_entry_editor_rows(
            visible,
            editor_key=editor_key,
            sort_columns=["pitch", "work_element_label", "requirement_description", "active"],
            default_sort_column="pitch",
            labels={
                "pitch": "Pitch",
                "work_element_label": "Process Function",
                "ppe": "Assigned PPE",
                "potential_hazards": "Potential Errors / Hazards (JSA)",
                "proposed_actions": "Action / Mitigation (JSA)",
                "requirement_description": "Requirement description",
            },
        )

        def _open_pitch_poster_from_table() -> None:
            click = st.session_state.get(f"safety_requirements_view_poster_{scenario_id}")
            if click and 0 <= click.get("row", -1) < len(editor_rows):
                clicked_row = editor_rows.iloc[click["row"]]
                row_pid = _text(clicked_row.get("pitch_id"))
                row_pitch_num = _text(clicked_row.get("pitch"))
                if not row_pid and row_pitch_num:
                    row_pid = pid_by_pitch_num.get(row_pitch_num, "")
                if row_pid:
                    st.session_state[poster_pitch_state_key] = row_pid
                st.session_state["safety_scroll_to_posters"] = True

        edited = st.data_editor(
            editor_rows,
            key=editor_key,
            hide_index=True,
            num_rows="dynamic",
            height=430,
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
                "pitch_id",
                "created_at",
                "updated_at",
            ],
            column_order=[
                "sync_status",
                "view_poster",
                "pitch",
                "work_element_id",
                "upstream_diff_summary",
                "ppe",
                "potential_hazards",
                "proposed_actions",
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
                "pitch_id": None,
                "work_element_label": None,
                "created_at": None,
                "updated_at": None,
                "sync_status": st.column_config.TextColumn(
                    "Sync status",
                    width="small",
                    help="Shows whether the PAAG step has PPE assigned ('Synced'), needs PPE ('⚠️ Needs PPE'), or changed upstream since last review ('⚠️ Upstream change').",
                ),
                "view_poster": st.column_config.ButtonColumn(
                    "Poster",
                    help="Jump directly to this step's Pitch JSA & PPE Poster below.",
                    key=f"safety_requirements_view_poster_{scenario_id}",
                    on_click=_open_pitch_poster_from_table,
                    type="secondary",
                ),
                "pitch": st.column_config.TextColumn(
                    "Pitch",
                    width="small",
                    help="Workstation pitch address where this Process at a Glance element is placed.",
                ),
                "work_element_id": st.column_config.SelectboxColumn(
                    "Process Function",
                    options=list(work_labels),
                    format_func=lambda value: work_labels.get(str(value), "Unavailable Process Function"),
                    required=True,
                    width="large",
                    help="Pre-populated from Process at a Glance work elements (Operation · Pitch).",
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
                "potential_hazards": st.column_config.TextColumn(
                    "Potential Errors / Hazards (JSA)",
                    required=False,
                    width="medium",
                    help="Potential errors or hazards displayed in the middle column of the Job Safety Analysis (JSA) poster.",
                ),
                "proposed_actions": st.column_config.TextColumn(
                    "Action / Mitigation (JSA)",
                    required=False,
                    width="medium",
                    help="Proposed action or mitigation displayed in the right column of the Job Safety Analysis (JSA) poster.",
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
            },
        )
        footer = editable_table_footer(
            editor_key=editor_key,
            key_prefix=f"safety_requirements_{project_id}_{scenario_id}",
            native_row_selection=True,
        )

        def _export_safety_bytes() -> bytes:
            export_df = visible[
                [
                    "pitch",
                    "work_element_label",
                    "sync_status",
                    "ppe",
                    "potential_hazards",
                    "proposed_actions",
                    "requirement_description",
                    "active",
                ]
            ].copy()
            export_df["ppe"] = [
                ", ".join(p) if isinstance(p, list) else str(p or "")
                for p in export_df["ppe"]
            ]
            return dataframe_to_excel(
                export_df.rename(
                    columns={
                        "pitch": "Pitch",
                        "work_element_label": "Process Function",
                        "sync_status": "Sync status",
                        "ppe": "Assigned PPE",
                        "potential_hazards": "Potential Errors / Hazards (JSA)",
                        "proposed_actions": "Action / Mitigation (JSA)",
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
            deletable_items = [
                {
                    "id": _text(row["id"]),
                    "process_function": work_labels.get(
                        _text(row["work_element_id"]), _text(row["work_element_label"])
                    ),
                    "description": _text(row["requirement_description"]) or "Saved PPE / Safety requirement",
                }
                for _, row in selected.iterrows()
                if _text(row.get("id")) and not _text(row.get("id")).startswith("__unassigned__::")
            ]
            if deletable_items:
                st.session_state[pending_delete_key] = deletable_items
                stage_native_delete_confirmation(editor_key)

        @st.dialog("Delete selected Safety requirements?", dismissible=False)
        def confirm_delete() -> None:
            pending = list(st.session_state.get(pending_delete_key) or [])
            st.warning(
                f"Delete {len(pending)} selected Safety requirement(s)? The PAAG step will remain in the table "
                "as an unreviewed element needing PPE."
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
                    identifying_columns=[
                        "work_element_id",
                        "requirement_description",
                        "potential_hazards",
                        "proposed_actions",
                        "ppe",
                    ],
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

        # =====================================================================
        # PITCH-BY-PITCH JSA & PPE POSTERS SECTION (BELOW THE TABLE, LIKE ERGO)
        # =====================================================================
        st.html('<div id="safety-posters-section"></div>')
        st.divider()
        st.subheader(
            "Pitch JSA & PPE Posters",
            anchor="safety-posters",
        )
        st.caption(
            "Navigate pitch by pitch (or click **View JSA/PPE Poster** on any PAAG element row in the table above). "
            "Click **Add PPE** in the header below to choose PPE icons and tag them to the appropriate PAAG elements on this pitch."
        )
        if st.session_state.pop("safety_scroll_to_posters", False):
            st.html(
                """<script>
                function scrollToSafetyPosters() {
                    try {
                        const parentDoc = window.parent ? window.parent.document : document;
                        const elem = (parentDoc && parentDoc.getElementById('safety-posters-section')) || document.getElementById('safety-posters-section');
                        if (elem) {
                            elem.scrollIntoView({ behavior: 'smooth', block: 'start' });
                            return true;
                        }
                    } catch (e) {
                        const elem = document.getElementById('safety-posters-section');
                        if (elem) {
                            elem.scrollIntoView({ behavior: 'smooth', block: 'start' });
                            return true;
                        }
                    }
                    return false;
                }
                setTimeout(scrollToSafetyPosters, 150);
                setTimeout(scrollToSafetyPosters, 450);
                </script>""",
                unsafe_allow_javascript=True,
            )

        if not poster_summaries or not jsa_summaries:
            st.info(
                "No pitches exist in this planning scenario yet. Create workstations/pitches in Yamazumi first to view and edit pitch-by-pitch JSA and PPE posters."
            )
        else:
            pid_list = list(poster_by_pid.keys())
            current_pid = _text(st.session_state.get(poster_pitch_state_key))
            if current_pid not in poster_by_pid:
                current_pid = pid_list[0]
                st.session_state[poster_pitch_state_key] = current_pid
            curr_idx = pid_list.index(current_pid)

            def _format_pitch_poster_opt(pid: str) -> str:
                info = poster_by_pid.get(pid, {})
                p_num = _text(info.get("pitch_number")) or "Pitch"
                p_name = _text(info.get("pitch_name"))
                sec = _text(info.get("section_name"))
                eff_cnt = len(info.get("effective_ppe") or [])
                unassigned_cnt = int(info.get("unassigned_element_count") or 0)
                tot_cnt = int(info.get("assigned_element_count") or 0) + unassigned_cnt
                status_tag = (
                    f" · ⚠️ {unassigned_cnt}/{tot_cnt} step(s) missing PPE"
                    if unassigned_cnt > 0
                    else f" · {tot_cnt} step(s) · {eff_cnt} PPE icon(s)"
                )
                base_lbl = f"{p_num} — {p_name}" if p_name else p_num
                if sec:
                    base_lbl += f" ({sec})"
                return f"{base_lbl}{status_tag}"

            add_ppe_dialog_state_key = f"show_add_ppe_dialog_{scenario_id}"

            nav_c1, nav_c2, nav_c3 = st.columns([2.3, 2.1, 1.3], vertical_alignment="center")
            with nav_c1:
                selected_pid = st.selectbox(
                    "Jump to Workstation Pitch",
                    options=pid_list,
                    index=curr_idx,
                    format_func=_format_pitch_poster_opt,
                    key=f"safety_poster_pitch_select_{scenario_id}",
                    label_visibility="collapsed",
                )
                if selected_pid != current_pid:
                    st.session_state[poster_pitch_state_key] = selected_pid
                    st.rerun()

            active_poster = poster_by_pid[selected_pid]
            active_jsa = jsa_by_pid.get(selected_pid, {})
            effective_items = active_poster.get("effective_ppe") or []
            overrides_list = active_poster.get("overrides") or []
            is_standard = bool(active_poster.get("is_standard_baseline"))
            pitch_we_steps = active_jsa.get("work_elements") or []

            with nav_c2:
                pitch_nav_bar = st.container(horizontal=True, vertical_alignment="center")
                if pitch_nav_bar.button(
                    "◀ Back",
                    disabled=(curr_idx == 0),
                    key=f"safety_pitch_prev_{scenario_id}",
                ):
                    st.session_state[poster_pitch_state_key] = pid_list[curr_idx - 1]
                    st.rerun()
                if pitch_nav_bar.button(
                    "Next ▶",
                    disabled=(curr_idx >= len(pid_list) - 1),
                    key=f"safety_pitch_next_{scenario_id}",
                ):
                    st.session_state[poster_pitch_state_key] = pid_list[curr_idx + 1]
                    st.rerun()
                if pitch_nav_bar.button(
                    "Add PPE",
                    type="primary",
                    icon=":material/add_moderator:",
                    key=f"btn_open_add_ppe_dialog_{scenario_id}_{selected_pid}",
                    help="Open a dialog to choose PPE images/items and tag them to the appropriate PAAG elements on this pitch.",
                ):
                    st.session_state[add_ppe_dialog_state_key] = True
                    st.rerun()
                pitch_nav_bar.markdown(
                    f'<span style="font-weight:700; color:#0369a1; font-size:0.88rem; white-space:nowrap;">Pitch {curr_idx + 1} of {len(pid_list)}</span>',
                    unsafe_allow_html=True,
                )

            with nav_c3:
                if not effective_items:
                    st.warning("No PPE assigned yet", icon=":material/warning:")
                elif is_standard:
                    st.success("Standard Baseline PPE (Green)", icon=":material/verified_user:")
                else:
                    st.info("Elevated / Special PPE (Purple)", icon=":material/shield:")

            if overrides_list:
                ov_bullets = " · ".join(
                    f"**{ov.get('summary', '')}**" for ov in overrides_list if ov.get("summary")
                )
                st.info(
                    f"**Automatic PPE Hierarchy Override on {active_poster.get('pitch_number')}:** {ov_bullets} "
                    "*(Only the highest protection tier in each category is shown on the PAAG slide, JSA Poster, and PPE Poster; "
                    "if the higher-tier step moves to another pitch, this pitch automatically reverts to the remaining lower tier.)*",
                    icon=":material/auto_awesome:",
                )

            @st.dialog("Add PPE to Pitch PAAG Elements", width="large")
            def _add_ppe_to_pitch_dialog() -> None:
                p_num_lbl = _text(active_poster.get("pitch_number")) or "Pitch"
                p_name_lbl = _text(active_poster.get("pitch_name"))
                pitch_title = f"{p_num_lbl} — {p_name_lbl}" if p_name_lbl else p_num_lbl
                st.markdown(f"#### 🛡️ {pitch_title}")
                st.caption(
                    "Choose one or more PPE items and select the PAAG work elements on this pitch that require them. "
                    "The JSA Poster and 11\"×17\" PPE Poster automatically deduplicate items and apply hierarchy rules "
                    "(e.g., Cut Level 4 overrides Cut Level 2 on the pitch)."
                )

                if not pitch_we_steps:
                    st.info("No PAAG Work Elements are currently assigned to this pitch in Yamazumi.")
                    if st.button("Close", key=f"close_empty_add_ppe_dlg_{scenario_id}_{selected_pid}"):
                        st.session_state.pop(add_ppe_dialog_state_key, None)
                        st.rerun()
                    return

                element_options = [
                    (
                        str(el["work_element_id"]),
                        f"Step {el['step_number']}: {el['operation']}",
                    )
                    for el in pitch_we_steps
                    if str(el.get("work_element_id") or "").strip()
                ]
                tag_dict_elem = dict(element_options)
                all_pitch_wids = list(tag_dict_elem.keys())

                ppe_pick_key = f"dlg_pitch_tag_ppe_pick_{scenario_id}_{selected_pid}"
                pending_ppe_pick_key = f"_pending_{ppe_pick_key}"
                if pending_ppe_pick_key in st.session_state:
                    st.session_state[ppe_pick_key] = list(
                        st.session_state.pop(pending_ppe_pick_key) or []
                    )

                def _toggle_gallery_ppe_pick(opt_name: str) -> None:
                    cur = list(st.session_state.get(ppe_pick_key) or [])
                    if opt_name in cur:
                        st.session_state[ppe_pick_key] = [x for x in cur if x != opt_name]
                    else:
                        cur.append(opt_name)
                        st.session_state[ppe_pick_key] = cur

                quick_bar = st.container(horizontal=True, vertical_alignment="center")
                if quick_bar.button(
                    "Select Standard Baseline PPE (Cut 2, Glasses, Shoes)",
                    icon=":material/verified_user:",
                    key=f"dlg_btn_quick_pick_baseline_{scenario_id}_{selected_pid}",
                ):
                    st.session_state[ppe_pick_key] = list(STANDARD_BASELINE_PPE)

                sel_ppe_to_tag = st.multiselect(
                    "1. Choose PPE",
                    options=ppe_options,
                    key=ppe_pick_key,
                    help="Select one or more PPE items to add to the selected PAAG elements.",
                )

                if sel_ppe_to_tag:
                    auto_h_preview, auto_a_preview = derive_ppe_hazards_and_actions(sel_ppe_to_tag)
                    icon_cards_html: list[str] = []
                    for p_name in sel_ppe_to_tag:
                        cat_item = get_ppe_catalog_item(p_name) or {}
                        uri = (
                            get_jsa_icon_data_uri(p_name)
                            or get_ppe_icon_data_uri(p_name)
                        )
                        rank_badge = (
                            f'<span style="font-size:0.68rem;background:#e0e7ff;color:#1e40af;padding:1px 5px;border-radius:4px;">Rank {cat_item.get("hierarchy_rank")}</span>'
                            if cat_item.get("category_group")
                            else ""
                        )
                        img_el = (
                            f'<img src="{uri}" style="width:52px;height:52px;object-fit:contain;border-radius:6px;background:#fff;border:1px solid #cbd5e1;" />'
                            if uri
                            else ""
                        )
                        icon_cards_html.append(
                            f'<div style="display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border:1px solid #cbd5e1;border-radius:8px;background:#f8fafc;margin:3px 6px 3px 0;">'
                            f'{img_el}<div><div style="font-size:0.82rem;font-weight:700;color:#0f172a;">{p_name}</div>{rank_badge}</div></div>'
                        )
                    st.markdown("".join(icon_cards_html), unsafe_allow_html=True)
                else:
                    auto_h_preview, auto_a_preview = "", ""

                with st.expander("Browse PPE Icon Gallery (Click to add/remove)", icon=":material/grid_view:", expanded=False):
                    gal_cols = st.columns(4)
                    current_picks = list(st.session_state.get(ppe_pick_key) or [])
                    for idx_p, p_opt in enumerate(ppe_options):
                        with gal_cols[idx_p % 4]:
                            uri = get_jsa_icon_data_uri(p_opt) or get_ppe_icon_data_uri(p_opt)
                            is_picked = p_opt in current_picks
                            if uri:
                                st.markdown(
                                    f'<div style="text-align:center;padding:4px;border:2px solid {"#0284c7" if is_picked else "#e2e8f0"};border-radius:8px;background:{"#f0f9ff" if is_picked else "#fff"};">'
                                    f'<img src="{uri}" style="height:48px;object-fit:contain;" />'
                                    f'<div style="font-size:0.74rem;font-weight:600;margin-top:2px;">{p_opt}</div></div>',
                                    unsafe_allow_html=True,
                                )
                            st.button(
                                "✓ Selected" if is_picked else "Add",
                                key=f"dlg_gal_btn_{scenario_id}_{selected_pid}_{idx_p}",
                                width="stretch",
                                type="primary" if is_picked else "secondary",
                                on_click=_toggle_gallery_ppe_pick,
                                args=(p_opt,),
                            )

                tagged_wids = st.multiselect(
                    "2. Choose Appropriate PAAG Elements on This Pitch",
                    options=all_pitch_wids,
                    default=all_pitch_wids,
                    format_func=lambda wid: tag_dict_elem.get(wid, wid),
                    key=f"dlg_pitch_tag_wids_{scenario_id}_{selected_pid}",
                    help="Select which PAAG work elements on this pitch require the chosen PPE (defaults to all elements on this pitch).",
                )

                tag_mode_choice = st.radio(
                    "Assignment Mode",
                    options=["add", "replace"],
                    format_func=lambda m: (
                        "Add to existing element PPE"
                        if m == "add"
                        else "Replace existing element PPE"
                    ),
                    horizontal=True,
                    key=f"dlg_pitch_tag_mode_{scenario_id}_{selected_pid}",
                )

                opt_h_col, opt_a_col = st.columns(2)
                with opt_h_col:
                    tag_haz_input = st.text_input(
                        "Optional JSA Potential Hazard (Free Text)",
                        value="",
                        placeholder=auto_h_preview or "e.g. Sharp metal edges / pinch point",
                        key=f"dlg_pitch_tag_haz_{scenario_id}_{selected_pid}",
                    )
                with opt_a_col:
                    tag_act_input = st.text_input(
                        "Optional JSA Action / Mitigation (Free Text)",
                        value="",
                        placeholder=auto_a_preview or "e.g. Wear required PPE and keep hands clear",
                        key=f"dlg_pitch_tag_act_{scenario_id}_{selected_pid}",
                    )

                dlg_actions = st.container(horizontal=True, vertical_alignment="center")
                if dlg_actions.button(
                    f"Add PPE to {len(tagged_wids)} PAAG Element(s)",
                    type="primary",
                    icon=":material/check:",
                    disabled=(not sel_ppe_to_tag or not tagged_wids),
                    key=f"dlg_btn_submit_tag_ppe_{scenario_id}_{selected_pid}",
                ):
                    try:
                        tag_ppe_to_work_elements(
                            project_id,
                            scenario_id,
                            work_element_ids=tagged_wids,
                            ppe_items=sel_ppe_to_tag,
                            potential_hazards=tag_haz_input,
                            proposed_actions=tag_act_input,
                            mode=tag_mode_choice,
                            editor_name=_text(st.session_state.get("current_editor")) or "Collaborator",
                        )
                        request_table_editor_reset(editor_key)
                        st.session_state.pop(add_ppe_dialog_state_key, None)
                        st.toast(
                            f"Added {', '.join(sel_ppe_to_tag)} to {len(tagged_wids)} PAAG element(s)",
                            icon=":material/check_circle:",
                        )
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

                if dlg_actions.button(
                    "Cancel",
                    key=f"dlg_btn_cancel_tag_ppe_{scenario_id}_{selected_pid}",
                ):
                    st.session_state.pop(add_ppe_dialog_state_key, None)
                    st.rerun()

                # Show existing PPE tagged on this pitch so user can also adjust or remove tags here
                ppe_to_wids: dict[str, list[str]] = {}
                for el in pitch_we_steps:
                    wid = str(el.get("work_element_id") or "").strip()
                    for p_item in (el.get("ppe") or []):
                        clean_p = _text(p_item)
                        if clean_p and wid:
                            ppe_to_wids.setdefault(clean_p, []).append(wid)

                if ppe_to_wids:
                    st.divider()
                    st.markdown(f"**Current PPE Tagged on This Pitch ({len(ppe_to_wids)})**")
                    eff_name_set = {
                        _text(it.get("name")).casefold() for it in effective_items
                    }
                    for p_idx, (ppe_name, linked_wids) in enumerate(ppe_to_wids.items()):
                        uri = get_jsa_icon_data_uri(ppe_name) or get_ppe_icon_data_uri(ppe_name)
                        is_eff = ppe_name.casefold() in eff_name_set
                        with st.container(border=True):
                            c_img, c_mid, c_act = st.columns([0.8, 3.4, 1.3], vertical_alignment="center")
                            with c_img:
                                if uri:
                                    st.markdown(
                                        f'<img src="{uri}" style="width:48px;height:48px;object-fit:contain;border-radius:6px;border:1px solid #cbd5e1;background:#fff;" />',
                                        unsafe_allow_html=True,
                                    )
                            with c_mid:
                                badge_txt = "✓ Displayed on Poster" if is_eff else "↳ Overridden by higher tier on pitch"
                                st.markdown(f"**{ppe_name}** · *{badge_txt}*")
                                updated_card_wids = st.multiselect(
                                    "Tagged PAAG Elements",
                                    options=all_pitch_wids,
                                    default=[w for w in linked_wids if w in tag_dict_elem],
                                    format_func=lambda wid: tag_dict_elem.get(wid, wid),
                                    key=f"dlg_card_ppe_tags_{scenario_id}_{selected_pid}_{p_idx}_{ppe_name}",
                                    label_visibility="collapsed",
                                )
                            with c_act:
                                c_btns = st.container(horizontal=True)
                                if c_btns.button(
                                    "Update",
                                    key=f"dlg_btn_save_card_ppe_{scenario_id}_{selected_pid}_{p_idx}",
                                ):
                                    update_ppe_item_element_tags_on_pitch(
                                        project_id,
                                        scenario_id,
                                        pitch_work_element_ids=all_pitch_wids,
                                        ppe_name=ppe_name,
                                        tagged_work_element_ids=updated_card_wids,
                                        editor_name=_text(st.session_state.get("current_editor")) or "Collaborator",
                                    )
                                    request_table_editor_reset(editor_key)
                                    st.toast(f"Updated elements for {ppe_name}", icon=":material/check_circle:")
                                    st.rerun()
                                if c_btns.button(
                                    "Remove",
                                    icon=":material/delete:",
                                    key=f"dlg_btn_rem_card_ppe_{scenario_id}_{selected_pid}_{p_idx}",
                                ):
                                    update_ppe_item_element_tags_on_pitch(
                                        project_id,
                                        scenario_id,
                                        pitch_work_element_ids=all_pitch_wids,
                                        ppe_name=ppe_name,
                                        tagged_work_element_ids=[],
                                        editor_name=_text(st.session_state.get("current_editor")) or "Collaborator",
                                    )
                                    request_table_editor_reset(editor_key)
                                    st.toast(f"Removed {ppe_name} from pitch", icon=":material/delete:")
                                    st.rerun()

            if st.session_state.get(add_ppe_dialog_state_key):
                _add_ppe_to_pitch_dialog()

            # -----------------------------------------------------------------
            # Build & Render Pitch JSA Poster and/or 11x17 PPE Poster Preview
            # -----------------------------------------------------------------
            jsa_html_doc = build_jsa_poster_html(
                job_title=_text(active_jsa.get("job_title")),
                plant_code=_text(active_jsa.get("plant_code")) or "AP1",
                important_notice=_text(active_jsa.get("important_notice")),
                effective_ppe_items=active_jsa.get("effective_ppe") or effective_items,
                jsa_rows=active_jsa.get("jsa_rows") or [],
                pitch_photos=active_jsa.get("pitch_photos") or [],
                include_pitch_photos=bool(active_jsa.get("include_pitch_photos", True)),
                overrides=overrides_list,
            )
            poster_html_doc = build_ppe_poster_html(
                job_name=_text(active_poster.get("job_name")),
                workstation=_text(active_poster.get("workstation")),
                section_name=_text(active_poster.get("section")),
                effective_ppe_items=effective_items,
                overrides=overrides_list,
                interactive_controls=True,
                default_job=_text(active_poster.get("default_job")),
                default_workstation=_text(active_poster.get("default_workstation")),
                default_section=_text(active_poster.get("default_section")),
            )

            safe_pitch_slug = (_text(active_poster.get("pitch_number")) or "Pitch").replace(" ", "_")
            if st.session_state.get(poster_view_mode_key) not in POSTER_VIEW_OPTIONS:
                st.session_state[poster_view_mode_key] = BOTH_VIEW_LABEL

            view_bar_c1, view_bar_c2, view_bar_c3 = st.columns([2.6, 1.2, 1.2], vertical_alignment="center")
            with view_bar_c1:
                active_view_mode = st.segmented_control(
                    "Poster View Mode",
                    options=POSTER_VIEW_OPTIONS,
                    key=poster_view_mode_key,
                    label_visibility="collapsed",
                )
            with view_bar_c2:
                st.download_button(
                    "Download JSA Poster (HTML)",
                    data=jsa_html_doc,
                    file_name=f"JSA_Poster_{safe_pitch_slug}.html",
                    mime="text/html",
                    icon=":material/download:",
                    width="stretch",
                    key=f"dl_jsa_poster_html_{scenario_id}_{selected_pid}",
                )
            with view_bar_c3:
                st.download_button(
                    "Download 11×17 PPE (HTML)",
                    data=poster_html_doc,
                    file_name=f"PPE_Poster_{safe_pitch_slug}.html",
                    mime="text/html",
                    icon=":material/download:",
                    width="stretch",
                    key=f"dl_ppe_poster_html_{scenario_id}_{selected_pid}",
                )

            if active_view_mode == JSA_VIEW_LABEL:
                components.html(jsa_html_doc, height=1140, scrolling=True)
            elif active_view_mode == PPE_VIEW_LABEL:
                components.html(poster_html_doc, height=840, scrolling=True)
            else:
                side_jsa_col, side_ppe_col = st.columns([1.05, 1.15])
                with side_jsa_col:
                    st.markdown("**📋 Job Safety Analysis (`FRM-GEA-SAF-085`)**")
                    components.html(jsa_html_doc, height=1060, scrolling=True)
                with side_ppe_col:
                    st.markdown("**🛡️ 11\"×17\" Minimum PPE Requirements Poster**")
                    components.html(poster_html_doc, height=1060, scrolling=True)

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
