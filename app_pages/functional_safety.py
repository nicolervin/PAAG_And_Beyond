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
    jsa_poster_save_bridge,
)
from utils.scope_ui import page_title_with_scope
from utils.store import (
    STANDARD_PPE_OPTIONS,
    acknowledge_safety_upstream_changes,
    delete_safety_requirements,
    derive_ppe_hazards_and_actions,
    ergonomics_work_elements,
    get_planning_scenario,
    get_ppe_catalog_item,
    pitch_jsa_poster_summary,
    pitch_ppe_poster_summary,
    safety_requirement_history,
    safety_requirements,
    save_pitch_jsa_poster_full,
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
poster_view_mode_key = f"safety_poster_view_mode_v2_{scenario_id}"

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

        # Compute scenario-wide pitch summaries
        poster_summaries = pitch_ppe_poster_summary(project_id, scenario_id)
        jsa_summaries = pitch_jsa_poster_summary(project_id, scenario_id)
        poster_by_pid = {str(item["pitch_id"]): item for item in poster_summaries}
        jsa_by_pid = {str(item["pitch_id"]): item for item in jsa_summaries}
        pid_by_pitch_num = {
            _text(item.get("pitch_number")): str(item["pitch_id"])
            for item in poster_summaries
            if _text(item.get("pitch_number"))
        }
        pid_by_pitch_num_cf = {
            _text(item.get("pitch_number")).casefold(): str(item["pitch_id"])
            for item in poster_summaries
            if _text(item.get("pitch_number"))
        }
        pid_by_sec_and_pitch = {
            (
                _text(item.get("section_name")).casefold(),
                _text(item.get("pitch_number")).casefold(),
            ): str(item["pitch_id"])
            for item in poster_summaries
            if _text(item.get("pitch_number"))
        }
        pid_by_we_id: dict[str, str] = {}
        for _jsa_item in jsa_summaries:
            _j_pid = _text(_jsa_item.get("pitch_id"))
            if not _j_pid:
                continue
            for _we_entry in _jsa_item.get("work_elements") or []:
                _we_id_val = _text(_we_entry.get("work_element_id"))
                if _we_id_val:
                    pid_by_we_id[_we_id_val] = _j_pid

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
        if "section_name" not in saved.columns:
            saved["section_name"] = ""
        saved["view_poster"] = "View JSA/PPE Poster"

        changed_safety = saved[saved["upstream_changed"].fillna(False).astype(bool)].copy()
        filter_changed_only = False
        if not changed_safety.empty:
            with st.container(border=True):
                q_head_col, q_toggle_col = st.columns([3, 1.3], vertical_alignment="center")
                with q_head_col:
                    st.markdown(f"**ΓÜá∩╕Å Upstream Process changes to review ({len(changed_safety)})**")
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
                        "section_name",
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
                        "section_name": st.column_config.TextColumn("Fishbone Section", width="medium"),
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
            dropdown_columns=["sync_status", "active", "section_name", "pitch"],
            search_columns=[
                "section_name",
                "work_element_label",
                "pitch",
                "requirement_description",
                "potential_hazards",
                "proposed_actions",
                "upstream_diff_summary",
            ],
            labels={
                "sync_status": "Sync status",
                "active": "Active",
                "section_name": "Fishbone Section",
                "pitch": "Pitch",
            },
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
            sort_columns=["section_name", "pitch", "work_element_label", "requirement_description", "active"],
            default_sort_column="pitch",
            labels={
                "section_name": "Fishbone Section",
                "pitch": "Pitch",
                "work_element_label": "Process Function",
                "ppe": "Assigned PPE",
                "potential_hazards": "Potential Errors / Hazards (JSA)",
                "proposed_actions": "Action / Mitigation (JSA)",
                "requirement_description": "Requirement description",
            },
        )

        view_poster_click_key = f"safety_requirements_view_poster_{scenario_id}"
        pitch_select_widget_key = f"safety_poster_pitch_select_{scenario_id}"

        def _resolve_row_pitch_id(clicked_row) -> str:
            row_pid = _text(clicked_row.get("pitch_id"))
            if row_pid and row_pid in poster_by_pid:
                return row_pid
            row_we_id = _text(clicked_row.get("work_element_id"))
            if row_we_id and row_we_id in pid_by_we_id:
                return pid_by_we_id[row_we_id]
            row_sec = _text(clicked_row.get("section_name")).casefold()
            row_pitch_num = _text(clicked_row.get("pitch"))
            if row_sec and row_pitch_num:
                sec_match = pid_by_sec_and_pitch.get((row_sec, row_pitch_num.casefold()), "")
                if sec_match:
                    return sec_match
            if row_pitch_num:
                return (
                    pid_by_pitch_num.get(row_pitch_num, "")
                    or pid_by_pitch_num_cf.get(row_pitch_num.casefold(), "")
                )
            return row_pid

        def _activate_safety_poster_for_click(click_state) -> None:
            if not click_state:
                return
            try:
                row_idx = int(click_state.get("row", -1))
            except (AttributeError, TypeError, ValueError):
                return
            if 0 <= row_idx < len(editor_rows):
                clicked_row = editor_rows.iloc[row_idx]
                row_pid = _resolve_row_pitch_id(clicked_row)
                if row_pid:
                    st.session_state[poster_pitch_state_key] = row_pid
                    st.session_state[pitch_select_widget_key] = row_pid
                    st.session_state[f"safety_poster_section_filter_{scenario_id}"] = "All Fishbone Sections"
                st.session_state["safety_scroll_nonce"] = (
                    int(st.session_state.get("safety_scroll_nonce", 0)) + 1
                )
                st.session_state["safety_scroll_to_posters"] = True

        def _open_pitch_poster_from_table() -> None:
            click = st.session_state.pop(view_poster_click_key, None)
            _activate_safety_poster_for_click(click)

        if view_poster_click_key in st.session_state:
            _activate_safety_poster_for_click(
                st.session_state.pop(view_poster_click_key, None)
            )

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
                "section_name",
                "pitch",
                "pitch_id",
                "created_at",
                "updated_at",
            ],
            column_order=[
                "sync_status",
                "view_poster",
                "section_name",
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
                    help="Shows whether the PAAG step has PPE assigned ('Synced'), needs PPE ('ΓÜá∩╕Å Needs PPE'), or changed upstream since last review ('ΓÜá∩╕Å Upstream change').",
                ),
                "view_poster": st.column_config.ButtonColumn(
                    "Poster",
                    help="Jump directly to this step's Pitch JSA & PPE Poster below.",
                    key=f"safety_requirements_view_poster_{scenario_id}",
                    on_click=_open_pitch_poster_from_table,
                    type="secondary",
                ),
                "section_name": st.column_config.TextColumn(
                    "Fishbone Section",
                    width="medium",
                    help="Fishbone assembly section where this pitch and work element belong.",
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
                    help="Pre-populated from Process at a Glance work elements (Operation ┬╖ Pitch).",
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
                    "section_name",
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
                        "section_name": "Fishbone Section",
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
                st.write(f"- {item['process_function']} ΓÇö {item['description']}")
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
            "Use **🛡️ Add PPE to Task** on the poster toolbar below to choose PPE icons and confirm which PAAG task(s) on this pitch require them."
        )
        if st.session_state.pop("safety_scroll_to_posters", False):
            _scroll_nonce = int(st.session_state.get("safety_scroll_nonce", 0))
            st.html(
                f"""<script data-nonce="{_scroll_nonce}">
                function scrollToSafetyPosters() {{
                    try {{
                        const parentDoc = window.parent ? window.parent.document : document;
                        const elem = (parentDoc && parentDoc.getElementById('safety-posters-section')) || document.getElementById('safety-posters-section');
                        if (elem) {{
                            elem.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                            return true;
                        }}
                    }} catch (e) {{
                        const elem = document.getElementById('safety-posters-section');
                        if (elem) {{
                            elem.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                            return true;
                        }}
                    }}
                    return false;
                }}
                scrollToSafetyPosters();
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
            all_poster_sections = [
                sec_lbl
                for sec_lbl in dict.fromkeys(
                    _text(item.get("section_name")) or "Unassigned"
                    for item in poster_summaries
                )
                if sec_lbl
            ]
            poster_sec_filter_key = f"safety_poster_section_filter_{scenario_id}"
            sec_filter_options = ["All Fishbone Sections", *all_poster_sections]
            if st.session_state.get(poster_sec_filter_key) not in sec_filter_options:
                st.session_state[poster_sec_filter_key] = "All Fishbone Sections"

            selected_poster_sec = _text(st.session_state.get(poster_sec_filter_key)) or "All Fishbone Sections"
            all_pids = list(poster_by_pid.keys())
            if selected_poster_sec != "All Fishbone Sections":
                pid_list = [
                    pid
                    for pid in all_pids
                    if (_text(poster_by_pid[pid].get("section_name")) or "Unassigned") == selected_poster_sec
                ] or all_pids
            else:
                pid_list = all_pids

            current_pid = _text(st.session_state.get(poster_pitch_state_key))
            if current_pid not in pid_list:
                current_pid = pid_list[0]
                st.session_state[poster_pitch_state_key] = current_pid
            curr_idx = pid_list.index(current_pid)
            st.session_state[pitch_select_widget_key] = current_pid

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

            st.session_state.pop(f"show_add_ppe_dialog_{scenario_id}", None)
            st.session_state.pop(f"show_add_ppe_dialog_v2_{scenario_id}", None)

            nav_sec_col, nav_c1, nav_c2, nav_c3 = st.columns([1.35, 2.1, 2.0, 1.15], vertical_alignment="center")
            with nav_sec_col:
                st.selectbox(
                    "Fishbone Section",
                    options=sec_filter_options,
                    key=poster_sec_filter_key,
                    help="Filter Pitch JSA & PPE Posters by Fishbone Section.",
                    label_visibility="collapsed",
                )
            def _on_poster_pitch_select_change() -> None:
                chosen = _text(st.session_state.get(pitch_select_widget_key))
                if chosen:
                    st.session_state[poster_pitch_state_key] = chosen

            with nav_c1:
                selected_pid = st.selectbox(
                    "Jump to Workstation Pitch",
                    options=pid_list,
                    format_func=_format_pitch_poster_opt,
                    key=pitch_select_widget_key,
                    on_change=_on_poster_pitch_select_change,
                    label_visibility="collapsed",
                )
                if selected_pid != current_pid:
                    st.session_state[poster_pitch_state_key] = selected_pid
                    st.rerun()

            active_poster = poster_by_pid[selected_pid]
            active_jsa = jsa_by_pid.get(selected_pid, {})
            effective_items = active_poster.get("effective_ppe") or []
            overrides_list = active_poster.get("overrides") or []
            pitch_we_steps = active_jsa.get("work_elements") or []

            with nav_c2:
                pitch_nav_bar = st.container(horizontal=True, vertical_alignment="center")
                if pitch_nav_bar.button(
                    "◀ Back",
                    disabled=(curr_idx == 0),
                    key=f"safety_pitch_prev_{scenario_id}",
                ):
                    prev_pid = pid_list[curr_idx - 1]
                    st.session_state[poster_pitch_state_key] = prev_pid
                    st.session_state[pitch_select_widget_key] = prev_pid
                    st.rerun()
                if pitch_nav_bar.button(
                    "Next ▶",
                    disabled=(curr_idx >= len(pid_list) - 1),
                    key=f"safety_pitch_next_{scenario_id}",
                ):
                    next_pid = pid_list[curr_idx + 1]
                    st.session_state[poster_pitch_state_key] = next_pid
                    st.session_state[pitch_select_widget_key] = next_pid
                    st.rerun()

                pitch_nav_bar.markdown(
                    f'<span style="font-weight:700; color:#0369a1; font-size:0.88rem; white-space:nowrap;">Pitch {curr_idx + 1} of {len(pid_list)}</span>',
                    unsafe_allow_html=True,
                )

            with nav_c3:
                if not effective_items:
                    st.warning("No PPE assigned yet", icon=":material/warning:")
                else:
                    st.info(f"{len(effective_items)} PPE item(s) on pitch", icon=":material/shield:")

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

            # -----------------------------------------------------------------
            # Build & Render Pitch JSA Poster and/or 11x17 PPE Poster Preview
            # -----------------------------------------------------------------
            jsa_bridge = jsa_poster_save_bridge(
                key=f"jsa_poster_save_bridge_{scenario_id}_{selected_pid}"
            )
            jsa_save_payload = (
                getattr(jsa_bridge, "save_payload", None)
                if jsa_bridge is not None
                else None
            )
            if isinstance(jsa_save_payload, dict) and jsa_save_payload:
                try:
                    target_pid = _text(jsa_save_payload.get("pitchId")) or selected_pid
                    save_res = save_pitch_jsa_poster_full(
                        project_id,
                        scenario_id,
                        target_pid,
                        jsa_save_payload,
                        editor_name=_text(st.session_state.get("current_editor")) or "Collaborator",
                    )
                    request_table_editor_reset(editor_key)
                    st.toast(
                        f"Saved JSA Poster ({save_res['row_count']} step row(s))",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

            jsa_html_doc = build_jsa_poster_html(
                pitch_id=selected_pid,
                section_name=_text(active_jsa.get("section_name")) or _text(active_poster.get("section_name")),
                job_title=_text(active_jsa.get("job_title")),
                plant_code=_text(active_jsa.get("plant_code")) or "AP1",
                important_notice=_text(active_jsa.get("important_notice")),
                effective_ppe_items=active_jsa.get("effective_ppe") or effective_items,
                jsa_rows=active_jsa.get("jsa_rows") or [],
                work_elements=active_jsa.get("work_elements") or pitch_we_steps,
                include_pitch_photos=False,
                overrides=overrides_list,
            )
            poster_html_doc = build_ppe_poster_html(
                pitch_id=selected_pid,
                job_name=_text(active_poster.get("job_name")),
                workstation=_text(active_poster.get("workstation")),
                section_name=_text(active_poster.get("section")),
                effective_ppe_items=active_jsa.get("effective_ppe") or effective_items,
                work_elements=active_jsa.get("work_elements") or pitch_we_steps,
                overrides=overrides_list,
                interactive_controls=True,
                default_job=_text(active_poster.get("default_job")),
                default_workstation=_text(active_poster.get("default_workstation")),
                default_section=_text(active_poster.get("default_section")),
            )

            safe_pitch_slug = (_text(active_poster.get("pitch_number")) or "Pitch").replace(" ", "_")
            if st.session_state.get(poster_view_mode_key) not in POSTER_VIEW_OPTIONS:
                st.session_state[poster_view_mode_key] = JSA_VIEW_LABEL

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

            with st.container(border=True):
                if active_view_mode == JSA_VIEW_LABEL:
                    components.html(jsa_html_doc, height=1190, scrolling=False)
                elif active_view_mode == PPE_VIEW_LABEL:
                    components.html(poster_html_doc, height=960, scrolling=False)
                else:
                    side_jsa_col, side_ppe_col = st.columns([1.05, 1.15])
                    with side_jsa_col:
                        st.markdown("**📋 Job Safety Analysis (`FRM-GEA-SAF-085`)**")
                        components.html(jsa_html_doc, height=960, scrolling=False)
                    with side_ppe_col:
                        st.markdown('**🛡️ 11"×' + '17" Minimum PPE Requirements Poster**')
                        components.html(poster_html_doc, height=960, scrolling=False)

st.divider()
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