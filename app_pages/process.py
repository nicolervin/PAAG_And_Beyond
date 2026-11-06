import base64
import hashlib
import importlib as _importlib
import json
from copy import deepcopy
from pathlib import Path
import re
import sys as _sys

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

if "utils.table_ui" in _sys.modules and getattr(_sys.modules["utils.table_ui"], "_TABLE_UI_REV_20261102", 0) < 4:
    if "utils.table_filters" in _sys.modules:
        _importlib.reload(_sys.modules["utils.table_filters"])
    _importlib.reload(_sys.modules["utils.table_ui"])
if "utils.process_store" in _sys.modules and getattr(_sys.modules["utils.process_store"], "_PROCESS_STORE_REV_20261102", 0) < 12:
    if "utils.assembly_store" in _sys.modules:
        _importlib.reload(_sys.modules["utils.assembly_store"])
    _importlib.reload(_sys.modules["utils.process_store"])
    if "utils.store" in _sys.modules and hasattr(_sys.modules["utils.store"], "_refresh_domain_modules"):
        _sys.modules["utils.store"]._refresh_domain_modules()
    if "utils.cache_store" in _sys.modules and hasattr(_sys.modules["utils.cache_store"], "get_data_cache"):
        _sys.modules["utils.cache_store"].get_data_cache().clear()
if "utils.process_pitch_visual" in _sys.modules and getattr(_sys.modules["utils.process_pitch_visual"], "_PROCESS_PITCH_VISUAL_REV_20261102", 0) < 8:
    _importlib.reload(_sys.modules["utils.process_pitch_visual"])
if "utils.image_annotator" in _sys.modules and getattr(_sys.modules["utils.image_annotator"], "_IMAGE_ANNOTATOR_REV_20261103", 0) < 4:
    _importlib.reload(_sys.modules["utils.image_annotator"])
if "utils.yamazumi_store" in _sys.modules and getattr(_sys.modules["utils.yamazumi_store"], "_YAMAZUMI_STORE_REV_20261103", 0) < 1:
    _importlib.reload(_sys.modules["utils.yamazumi_store"])
    if "utils.store" in _sys.modules and hasattr(_sys.modules["utils.store"], "_refresh_domain_modules"):
        _sys.modules["utils.store"]._refresh_domain_modules()
    if "utils.cache_store" in _sys.modules and hasattr(_sys.modules["utils.cache_store"], "get_data_cache"):
        _sys.modules["utils.cache_store"].get_data_cache().clear()

from utils.fishbone_ui import section_breadcrumb_labels
from utils.media_cache import cached_image_bytes, cached_image_data_url
from utils.store import (
    ROOT,
    assign_parts_to_section,
    assembly_section_walk_order,
    audit_history,
    create_part_and_assign_to_section,
    delete_process_part_groups,
    unlink_part_from_process_group,
    fishbone_part_assignments,
    get_planning_scenario,
    get_pitch_unclassified_part_options,
    move_fishbone_part_assignment,
    parse_yamazumi_model_variants,
    process_element_id_for_yamazumi,
    process_ergonomics_risk_work_element_ids,
    work_element_criticality,
    process_part_placement_options,
    process_part_groups,
    set_process_part_option_handling_type,
    process_pitch_visual_summary,
    process_readiness_metrics,
    scenario_pitch_visual_coverage,
    complexity_features,
    part_feature_rules,
    project_models,
    project_table,
    reconcile_yamazumi_to_process,
    record_audit_event,
    replace_work_elements,
    update_work_element_tool_and_resource,
    save_process_part_group,
    search_parts_and_fishbone,
    safety_requirement_delete_impact,
    validate_process_part_option_pairings,
    work_element_op_ids,
    work_element_downstream_impact,
    yamazumi_context_for_process,
    yamazumi_elements_for_section,
    yamazumi_pitches_for_scenario,
    catalog_part_photos_for_pitch,
    copy_part_photo_to_pitch_visual_media,
    copy_pitch_visual_media,
    delete_pitch_visual_media,
    get_pitch_visual_media,
    save_pitch_visual_media,
    save_pitch_visual_media_url,
    update_pitch_visual_media,
    update_pitch_visual_annotations,
)
from utils.process_flow_visual import render_process_flow_diagram
from utils.equipment_store import (
    equipment_assets,
    equipment_types,
    save_equipment_placement,
)
from utils.clipboard_image import as_uploaded_file, clipboard_image, decode_clipboard_image
from utils.image_annotator import decode_data_url, image_annotator
from utils.scope_ui import page_title_with_scope
from utils.split_workspace import build_page_url
from utils.process_pitch_visual import (
    clamp_media_page,
    clamp_page,
    media_page_count,
    page_count,
    page_elements,
    page_for_element,
    page_media,
    render_pitch_canvas,
    render_presentation_deck,
    render_printable_paag_deck,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
    split_filter_values,
)
from utils.table_ui import (
    dataframe_to_excel,
    editable_table_footer,
    editable_table_heading,
    format_clean_number,
    guarded_tabs,
    native_selected_rows,
    prepare_editor_selection_column,
    render_select_all_control,
    required_field_errors,
    resolve_editor_selected_rows,
    count_table_create_and_edit_rows,
    render_audit_history_table,
    selectable_dataframe,
    selected_rows_action_bar,
    stage_native_delete_confirmation,
    table_has_unsaved_changes,
)


def _pitch_address_sort_key(value: object) -> tuple:
    text = str(value or "").strip()
    if not text:
        return (1, (), "")
    tokens = tuple(
        (0, int(tok)) if tok.isdigit() else (1, tok.casefold())
        for tok in re.split(r"(\d+)", text)
        if tok
    )
    return (0, tokens, text.casefold())


def _sort_pitches_by_address_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "pitch_number" not in df.columns:
        return df
    sorted_idx = sorted(
        df.index,
        key=lambda idx: (
            _pitch_address_sort_key(df.at[idx, "pitch_number"]),
            str(df.at[idx, "id"]) if "id" in df.columns else "",
        ),
    )
    return df.loc[sorted_idx].reset_index(drop=True)


def _inject_disabled_consumed_placement_options_script() -> None:
    st.html(
        """
        <div style="display:none;" aria-hidden="true"></div>
        <script>
        (function() {
            const DISABLED_MARKERS = [
                "Unavailable for Consume — allowance fully used"
            ];
            const OPTION_SELECTOR = '[role="option"], [data-baseweb="menu"] li';
            const STYLE_ID = "paag-disabled-placement-options-style";
            const CSS_TEXT = [
                '[role="option"][data-paag-disabled-option="true"],',
                '[data-baseweb="menu"] li[data-paag-disabled-option="true"] {',
                '    opacity: 0.42 !important;',
                '    color: #8a8f98 !important;',
                '    cursor: not-allowed !important;',
                '    user-select: none !important;',
                '    background: transparent !important;',
                '    background-color: transparent !important;',
                '}',
                '[role="option"][data-paag-disabled-option="true"] [data-item-hl],',
                '[role="option"][data-paag-disabled-option="true"] *,',
                '[data-baseweb="menu"] li[data-paag-disabled-option="true"] * {',
                '    color: #8a8f98 !important;',
                '    cursor: not-allowed !important;',
                '    background: transparent !important;',
                '    background-color: transparent !important;',
                '}'
            ].join(" ");

            if (document.head) {
                let styleEl = document.getElementById(STYLE_ID);
                if (!styleEl) {
                    styleEl = document.createElement("style");
                    styleEl.id = STYLE_ID;
                    document.head.appendChild(styleEl);
                }
                if (styleEl.textContent !== CSS_TEXT) {
                    styleEl.textContent = CSS_TEXT;
                }
            }

            function isOptionTextDisabled(text) {
                if (!text) return false;
                for (let i = 0; i < DISABLED_MARKERS.length; i++) {
                    if (text.indexOf(DISABLED_MARKERS[i]) !== -1) {
                        return true;
                    }
                }
                return false;
            }

            function markOptionDisabled(opt, disabled) {
                if (disabled) {
                    if (opt.getAttribute("data-paag-disabled-option") !== "true") {
                        opt.setAttribute("data-paag-disabled-option", "true");
                    }
                    if (opt.getAttribute("aria-disabled") !== "true") {
                        opt.setAttribute("aria-disabled", "true");
                    }
                    opt.removeAttribute("data-hovered");
                    opt.removeAttribute("data-focused");
                } else if (opt.getAttribute("data-paag-disabled-option") === "true") {
                    opt.removeAttribute("data-paag-disabled-option");
                    opt.removeAttribute("aria-disabled");
                }
            }

            function syncDisabledPlacementOptions() {
                const options = document.querySelectorAll(OPTION_SELECTOR);
                options.forEach(function(opt) {
                    markOptionDisabled(opt, isOptionTextDisabled(opt.textContent || ""));
                });
            }

            window.__paagSyncDisabledPlacementOptions = syncDisabledPlacementOptions;

            if (!window.__paagDisabledPlacementObserverV2Installed) {
                window.__paagDisabledPlacementObserverV2Installed = true;

                const resolveDisabledOption = function(target) {
                    if (!target || !target.closest) return null;
                    const opt = target.closest(OPTION_SELECTOR);
                    if (!opt) return null;
                    const disabled =
                        opt.getAttribute("data-paag-disabled-option") === "true" ||
                        isOptionTextDisabled(opt.textContent || "");
                    markOptionDisabled(opt, disabled);
                    return disabled ? opt : null;
                };

                const blockPressOnDisabledOption = function(event) {
                    const opt = resolveDisabledOption(event.target);
                    if (opt) {
                        event.preventDefault();
                        event.stopPropagation();
                        if (event.stopImmediatePropagation) {
                            event.stopImmediatePropagation();
                        }
                    }
                };

                const blockHoverOnDisabledOption = function(event) {
                    const opt = resolveDisabledOption(event.target);
                    if (opt) {
                        event.stopPropagation();
                        if (event.stopImmediatePropagation) {
                            event.stopImmediatePropagation();
                        }
                    }
                };

                [
                    "pointerdown",
                    "mousedown",
                    "pointerup",
                    "mouseup",
                    "click",
                    "dblclick",
                    "touchstart",
                    "touchend"
                ].forEach(function(evtName) {
                    window.addEventListener(evtName, blockPressOnDisabledOption, true);
                });

                [
                    "pointerenter",
                    "pointerover",
                    "pointermove",
                    "mouseenter",
                    "mouseover",
                    "mousemove"
                ].forEach(function(evtName) {
                    window.addEventListener(evtName, blockHoverOnDisabledOption, true);
                });

                window.addEventListener("keydown", function(event) {
                    if (window.__paagSyncDisabledPlacementOptions) {
                        window.__paagSyncDisabledPlacementOptions();
                    }
                    if (event.key === "Enter" || event.key === "Tab") {
                        let activeOpt = document.querySelector(
                            '[role="option"][data-focused="true"][data-paag-disabled-option="true"], ' +
                            '[role="option"][data-hovered="true"][data-paag-disabled-option="true"], ' +
                            '[role="option"][aria-selected="true"][data-paag-disabled-option="true"]'
                        );
                        if (!activeOpt && document.activeElement) {
                            const activeId = document.activeElement.getAttribute("aria-activedescendant");
                            if (activeId) {
                                const descEl = document.getElementById(activeId);
                                if (descEl && isOptionTextDisabled(descEl.textContent || "")) {
                                    activeOpt = descEl;
                                }
                            }
                        }
                        if (activeOpt) {
                            event.preventDefault();
                            event.stopPropagation();
                            if (event.stopImmediatePropagation) {
                                event.stopImmediatePropagation();
                            }
                        }
                    }
                }, true);

                const observer = new MutationObserver(function() {
                    if (window.__paagSyncDisabledPlacementOptions) {
                        window.__paagSyncDisabledPlacementOptions();
                    }
                });
                if (document.body) {
                    observer.observe(document.body, {
                        childList: true,
                        subtree: true,
                        characterData: true
                    });
                }
            }

            syncDisabledPlacementOptions();
        })();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def _part_has_model_variants(
    part_id: str,
    placements_df: pd.DataFrame,
    *,
    fallback_model_applicability: object = None,
    feature_rule_part_ids: set[str] | None = None,
) -> bool:
    pid = str(part_id or "").strip()
    if not pid:
        return False
    if feature_rule_part_ids and pid in feature_rule_part_ids:
        return True
    if not placements_df.empty and "part_id" in placements_df.columns:
        part_rows = placements_df.loc[placements_df["part_id"].astype(str) == pid]
        for _, prow in part_rows.iterrows():
            vg = (
                ""
                if pd.isna(prow.get("variant_group"))
                else str(prow.get("variant_group") or "").strip()
            )
            if vg:
                return True
            m_app = (
                ""
                if pd.isna(prow.get("model_applicability"))
                else str(prow.get("model_applicability") or "").strip()
            )
            if m_app.casefold() not in {"", "all", "all models", "base"}:
                return True
            try:
                if int(prow.get("step_number") or 1) > 1:
                    return True
            except (TypeError, ValueError):
                pass
    if fallback_model_applicability is not None and not pd.isna(
        fallback_model_applicability
    ):
        fb_app = str(fallback_model_applicability or "").strip()
        if fb_app.casefold() not in {"", "all", "all models", "base"}:
            return True
    return False

project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
process_editor_key = f"process_editor_{scenario_id}"
missing_part_dialog_key = f"process_missing_part_dialog_{scenario_id}"
pairing_delete_key = f"process_pairings_pending_remove_{scenario_id}"
edit_line_dialog_key = f"process_edit_line_dialog_{scenario_id}"
if not project_id or not scenario_id:
    st.stop()

scenario = get_planning_scenario(project_id, scenario_id)
if not scenario:
    st.error("The active planning scenario no longer exists.")
    st.stop()
if st.session_state.get("selected_pitch_scenario_id") not in {None, scenario_id}:
    st.session_state.pop("selected_pitch_id", None)
    st.session_state.pop("pitch_page_num", None)
st.session_state["selected_pitch_scenario_id"] = scenario_id
page_title_with_scope(
    "Process at a Glance", scope="scenario", scenario_name=scenario["name"]
)
st.caption(
    "Create PAAG Elements for Yamazumi work elements section by section, classify each selected "
    "part as Consume or Handle, then complete the ordered Process at a Glance by pitch. A purchased "
    "assembly is handled as one catalog part."
)
st.caption(f"Rev {scenario['revision_label']} · {scenario['name']} · {scenario['status']}")

_paag_metrics = process_readiness_metrics(project_id, scenario_id)
_total_steps = int(_paag_metrics["total_steps"])
_total_yam = int(_paag_metrics["total_yamazumi_elements"])
_synced_yam = int(_paag_metrics["synced_yamazumi_elements"])
_unsynced_yam = int(_paag_metrics["unsynced_yamazumi_elements"])
_unlinked_steps = int(_paag_metrics["unlinked_process_steps"])

if _total_steps == 0 and _total_yam == 0:
    _steps_val = "🟢 0"
    _steps_delta = "No Yamazumi or Process steps yet"
    _steps_dcol = "off"
elif _total_yam > 0:
    _sync_pct = round(_synced_yam / _total_yam * 100)
    if _unsynced_yam == 0 and _unlinked_steps == 0:
        _steps_val = f"🟢 {_total_steps:,} (100%)"
        _steps_delta = f"All {_total_yam:,} Yamazumi elements in Process"
        _steps_dcol = "normal"
    else:
        _steps_icon = "🟡" if (_sync_pct >= 50 and _unlinked_steps == 0) else "🔴"
        _steps_val = f"{_steps_icon} {_total_steps:,} ({_sync_pct}%)"
        if _unsynced_yam > 0 and _unlinked_steps > 0:
            _steps_delta = f"{_unsynced_yam:,} Yamazumi not added · {_unlinked_steps:,} unlinked"
        elif _unsynced_yam > 0:
            _steps_delta = f"{_unsynced_yam:,} Yamazumi element{'s' if _unsynced_yam != 1 else ''} not yet added"
        else:
            _steps_delta = f"{_unlinked_steps:,} step{'s' if _unlinked_steps != 1 else ''} missing Yamazumi link"
        _steps_dcol = "inverse"
else:
    _steps_val = f"🔴 {_total_steps:,} (0%)"
    _steps_delta = f"{_unlinked_steps:,} step{'s' if _unlinked_steps != 1 else ''} missing Yamazumi link"
    _steps_dcol = "inverse"

_total_fb_parts = int(_paag_metrics["total_fishbone_parts"])
_consumed_parts = int(_paag_metrics["consumed_parts"])
_unclass_pairings = int(_paag_metrics["unclassified_pairings"])
if _total_fb_parts == 0:
    _parts_val = "🟢 0 / 0"
    _parts_delta = "No Fishbone parts placed yet"
    _parts_dcol = "off"
else:
    _part_cov_pct = round(_consumed_parts / _total_fb_parts * 100)
    _unconsumed_parts = max(_total_fb_parts - _consumed_parts, 0)
    if _unconsumed_parts == 0 and _unclass_pairings == 0:
        _parts_val = f"🟢 100% ({_consumed_parts:,}/{_total_fb_parts:,})"
        _parts_delta = "All Fishbone parts consumed"
        _parts_dcol = "normal"
    else:
        _parts_icon = "🟡" if (_part_cov_pct >= 50 and _unclass_pairings == 0) else ("🟡" if _part_cov_pct >= 80 else "🔴")
        _parts_val = f"{_parts_icon} {_part_cov_pct}% ({_consumed_parts:,}/{_total_fb_parts:,})"
        if _unconsumed_parts > 0 and _unclass_pairings > 0:
            _parts_delta = f"{_unconsumed_parts:,} unconsumed · {_unclass_pairings:,} unclassified"
        elif _unconsumed_parts > 0:
            _parts_delta = f"{_unconsumed_parts:,} Fishbone part{'s' if _unconsumed_parts != 1 else ''} not yet consumed"
        else:
            _parts_delta = f"{_unclass_pairings:,} part pairing{'s' if _unclass_pairings != 1 else ''} unclassified"
        _parts_dcol = "inverse"

_total_pitches = int(_paag_metrics["total_active_pitches"])
_pitches_media = int(_paag_metrics["pitches_with_media"])
_total_media = int(_paag_metrics["total_visual_media"])
_untagged_media = int(_paag_metrics["untagged_visual_media"])
if _total_pitches == 0:
    _media_val = "🟢 0 / 0"
    _media_delta = "No active pitches yet"
    _media_dcol = "off"
else:
    _media_cov_pct = round(_pitches_media / _total_pitches * 100)
    _pitches_missing_media = max(_total_pitches - _pitches_media, 0)
    if _pitches_missing_media == 0 and _untagged_media == 0:
        _media_val = f"🟢 100% ({_pitches_media:,}/{_total_pitches:,})"
        _media_delta = f"{_total_media:,} visual aid{'s' if _total_media != 1 else ''} attached"
        _media_dcol = "normal"
    else:
        _media_icon = "🟢" if _pitches_missing_media == 0 else ("🟡" if _media_cov_pct >= 50 else "🔴")
        _media_val = f"{_media_icon} {_media_cov_pct}% ({_pitches_media:,}/{_total_pitches:,})"
        if _pitches_missing_media > 0 and _untagged_media > 0:
            _media_delta = f"{_pitches_missing_media:,} pitch{'es' if _pitches_missing_media != 1 else ''} without visuals · {_untagged_media:,} untagged"
        elif _pitches_missing_media > 0:
            _media_delta = f"{_pitches_missing_media:,} pitch{'es' if _pitches_missing_media != 1 else ''} missing visual aids ({_total_media:,} total)"
        else:
            _media_delta = f"{_untagged_media:,} visual aid{'s' if _untagged_media != 1 else ''} not tagged to steps"
        _media_dcol = "inverse" if _pitches_missing_media > 0 else "off"

_q_alerts = int(_paag_metrics["quality_alerts"])
_m_alerts = int(_paag_metrics["materials_alerts"])
_e_alerts = int(_paag_metrics["ergo_alerts"])
_s_alerts = int(_paag_metrics["safety_alerts"])
_tot_alerts = int(_paag_metrics["total_alerts"])
_pfmea_alerts = int(_paag_metrics["pfmea_alert_count"])
_missing_ppe = int(_paag_metrics["steps_missing_ppe"])

_alerts_breakdown = f"{_q_alerts:,} Quality · {_m_alerts:,} Materials · {_e_alerts:,} Ergo · {_s_alerts:,} Safety"
if _total_steps == 0:
    _alerts_val = "🟢 0"
    _alerts_delta = _alerts_breakdown
    _alerts_dcol = "off"
elif _tot_alerts == 0:
    _alerts_val = "🟢 0"
    _alerts_delta = "All functional checks nominal"
    _alerts_dcol = "normal"
else:
    _has_red_alert = (_e_alerts > 0 or _m_alerts > 0 or _pfmea_alerts > 0)
    _alerts_icon = "🔴" if _has_red_alert else "🟡"
    _alerts_val = f"{_alerts_icon} {_tot_alerts:,}"
    _alerts_delta = _alerts_breakdown
    _alerts_dcol = "inverse" if (_has_red_alert or _missing_ppe > 0) else "off"

_pm1, _pm2, _pm3, _pm4 = st.columns(4)
_pm1.metric(
    "Process Steps",
    _steps_val,
    delta=_steps_delta,
    delta_color=_steps_dcol,
    help=(
        "Total Process at a Glance work elements in the active scenario and the percentage "
        "of scenario Yamazumi elements synced into Process."
    ),
)
_pm2.metric(
    "Part Consumption Coverage",
    _parts_val,
    delta=_parts_delta,
    delta_color=_parts_dcol,
    help=(
        "Share of active Fishbone-placed parts in this scenario that have been paired as "
        "'Consume' on at least one Process step, plus any unclassified part pairings."
    ),
)
_pm3.metric(
    "Pitch Visual Aids",
    _media_val,
    delta=_media_delta,
    delta_color=_media_dcol,
    help=(
        "Share of active Yamazumi pitches in this scenario that have at least one photo, "
        "video, 3D CAD model, or web link attached on PAAG slides."
    ),
)
_pm4.metric(
    "Functional Alerts",
    _alerts_val,
    delta=_alerts_delta,
    delta_color=_alerts_dcol,
    help=(
        "Scenario-wide alerts across Quality (Torque specs & high-risk PFMEA Sev ≥ 8 or RPN ≥ 100), "
        "Materials (unclassified part handling), Ergonomics (Open/Pending Red, Favorable Red, or Yellow reviews), "
        "and Safety (active safety requirements & steps without assigned PPE)."
    ),
)

sections = assembly_section_walk_order(project_id)
if not sections.empty:
    sections = sections.loc[sections["active"].fillna(1).astype(bool)].copy()
section_ids = sections["id"].astype(str).tolist() if not sections.empty else []
section_labels = dict(zip(sections["id"].astype(str), sections["name"].astype(str))) if not sections.empty else {}


models = project_models(project_id)
model_labels = {
    str(row["model_number"]): (str(row["display_name"]).strip() or "Common name not defined")
    for _, row in models.iterrows()
}
model_numbers_by_label = {label: number for number, label in model_labels.items()}
_active_features = complexity_features(project_id)
feature_variant_options: list[str] = []
feature_variant_aliases: dict[str, str] = {
    "all": "All models",
    "all models": "All models",
    "base": "All models",
}
if not _active_features.empty:
    for _, _frow in _active_features.iterrows():
        if not bool(_frow.get("active", 1)):
            continue
        _fname = str(_frow.get("name") or "").strip()
        if not _fname:
            continue
        _fcat = str(_frow.get("category") or "").strip()
        for _choice in json.loads(str(_frow.get("allowed_values") or "[]")):
            _choice_str = str(_choice or "").strip()
            if _choice_str:
                _short_feat = f"{_fname} = {_choice_str}"
                feature_variant_options.append(_short_feat)
                feature_variant_aliases[_short_feat.casefold()] = _short_feat
                if _fcat:
                    feature_variant_aliases[
                        f"{_fcat} · {_fname} = {_choice_str}".casefold()
                    ] = _short_feat
process_model_options = list(
    dict.fromkeys(["All models", *feature_variant_options])
)


def close_presentation_mode_dialog() -> None:
    st.session_state[f"paag_present_active_{scenario_id}"] = False


@st.dialog(
    "Process at a Glance Presentation",
    width="large",
    on_dismiss=close_presentation_mode_dialog,
)
def presentation_mode_dialog(
    project_id: str,
    scenario_id: str,
    scenario_name: str,
    project_name: str,
    pitch_options: list[tuple[str, str]],
    model_labels: dict[str, str],
) -> None:
    pitch_ids = [pid for pid, _ in pitch_options]
    pitch_dict = dict(pitch_options)
    if not pitch_ids:
        st.info("No pitches available to present.")
        return

    curr_pitch_id = str(st.session_state.get(f"pres_pitch_id_{scenario_id}") or "")
    if curr_pitch_id not in pitch_dict:
        curr_pitch_id = pitch_ids[0]
        st.session_state[f"pres_pitch_id_{scenario_id}"] = curr_pitch_id

    curr_pitch_idx = pitch_ids.index(curr_pitch_id)
    curr_page = int(st.session_state.get(f"pres_page_num_{scenario_id}", 1))

    try:
        curr_summary = process_pitch_visual_summary(project_id, scenario_id, curr_pitch_id)
    except Exception:
        curr_summary = {"pitch_number": "", "pitch_name": "", "elements": []}

    curr_elements = curr_summary.get("elements", [])
    total_pages = max(page_count(len(curr_elements)), curr_summary.get("slide_count", 1), 1)
    curr_page = min(max(1, curr_page), total_pages)
    st.session_state[f"pres_page_num_{scenario_id}"] = curr_page

    is_first_slide = (curr_pitch_idx == 0 and curr_page == 1)
    is_last_slide = (curr_pitch_idx >= len(pitch_ids) - 1 and curr_page >= total_pages)

    st.markdown(
        """
        <style>
        div[data-testid="stDialog"] div[role="dialog"] {
            width: 96vw !important;
            max-width: 96vw !important;
            max-height: 96vh !important;
        }
        div[data-testid="stDialog"] div[data-testid="stDialogHeader"] {
            padding-bottom: 2px !important;
        }
        div[data-testid="stDialog"] button[aria-label="Close"] {
            display: none !important;
        }
        .pres-nav-counter {
            text-align: center;
            font-weight: 700;
            font-size: 0.95rem;
            color: #0369a1;
            padding-top: 6px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Simplified, non-redundant controls:
    # ◀ Back | Jump to Pitch dropdown | Pitch & Slide counter | Next ▶ | ✕ Exit
    nav_col1, nav_col2, nav_col3, nav_col4, nav_col5 = st.columns(
        [1.1, 2.8, 2.5, 1.1, 0.9],
        vertical_alignment="center",
    )

    with nav_col1:
        if st.button("◀ Back", disabled=is_first_slide, key=f"pres_btn_back_{scenario_id}", help="Previous slide or pitch"):
            if curr_page > 1:
                st.session_state[f"pres_page_num_{scenario_id}"] = curr_page - 1
            else:
                prev_pid = pitch_ids[curr_pitch_idx - 1]
                st.session_state[f"pres_pitch_id_{scenario_id}"] = prev_pid
                try:
                    prev_sum = process_pitch_visual_summary(project_id, scenario_id, prev_pid)
                    prev_tot = max(page_count(len(prev_sum.get("elements", []))), prev_sum.get("slide_count", 1), 1)
                except Exception:
                    prev_tot = 1
                st.session_state[f"pres_page_num_{scenario_id}"] = prev_tot
            st.rerun()

    with nav_col2:
        new_choice = st.selectbox(
            "Jump to pitch",
            options=pitch_ids,
            index=curr_pitch_idx,
            format_func=lambda pid: f"Pitch {pitch_ids.index(pid) + 1}: {pitch_dict.get(pid, pid)}",
            key=f"pres_sel_p_{scenario_id}_{curr_pitch_id}",
            label_visibility="collapsed",
        )
        if new_choice != curr_pitch_id:
            st.session_state[f"pres_pitch_id_{scenario_id}"] = new_choice
            st.session_state[f"pres_page_num_{scenario_id}"] = 1
            st.rerun()

    with nav_col3:
        page_suffix = f" (Page {curr_page}/{total_pages})" if total_pages > 1 else ""
        st.html(
            f"<div class='pres-nav-counter' title='Pitch {curr_pitch_idx + 1} of {len(pitch_ids)}'>"
            f"Pitch {curr_pitch_idx + 1} of {len(pitch_ids)}{page_suffix} · {pitch_dict.get(curr_pitch_id, '')}"
            f"</div>"
        )

    with nav_col4:
        if st.button("Next ▶", type="primary", disabled=is_last_slide, key=f"pres_btn_next_{scenario_id}", help="Next slide or pitch"):
            if curr_page < total_pages:
                st.session_state[f"pres_page_num_{scenario_id}"] = curr_page + 1
            else:
                next_pid = pitch_ids[curr_pitch_idx + 1]
                st.session_state[f"pres_pitch_id_{scenario_id}"] = next_pid
                st.session_state[f"pres_page_num_{scenario_id}"] = 1
            st.rerun()

    with nav_col5:
        if st.button("✕ Exit", key=f"pres_btn_exit_{scenario_id}", help="Exit presentation mode"):
            st.session_state[f"paag_present_active_{scenario_id}"] = False
            st.session_state["selected_pitch_id"] = curr_pitch_id
            st.session_state["pitch_page_num"] = curr_page
            st.rerun()

    active_page_rows = page_elements(curr_elements, curr_page)
    for row in active_page_rows:
        row["models"] = [
            "All models" if model.casefold() in {"all", "all models"}
            else model_labels.get(model, model)
            for model in (split_filter_values(row.get("model_applicability")) or ["All"])
        ]

    slide_html = render_pitch_canvas(
        curr_summary,
        active_page_rows,
        scenario_name=scenario_name,
        project_name=project_name,
        page_num=curr_page,
        total_pages=total_pages,
        presentation_mode=True,
    )
    st.html(slide_html, unsafe_allow_javascript=True)


def close_print_slide_dialog() -> None:
    st.session_state[f"paag_print_active_{scenario_id}"] = False


@st.dialog(
    "Export & Print Process at a Glance",
    width="large",
    on_dismiss=close_print_slide_dialog,
)
def print_slide_dialog(
    pitch_summary: dict,
    active_page_rows: list[dict],
    current_page: int,
    total_pages: int,
    scenario_name: str,
    project_name: str,
    project_id: str = "",
    scenario_id: str = "",
    pitch_options: list[tuple[str, str]] | None = None,
    selected_pitch_id: str = "",
    model_labels: dict[str, str] | None = None,
    scenario_pitches_df: pd.DataFrame | None = None,
    sections: pd.DataFrame | None = None,
    section_labels: dict[str, str] | None = None,
    active_section_filter_id: str = "",
) -> None:
    # Hide the default gray X button to ensure dialog state stays in sync
    st.markdown(
        """
        <style>
        div[data-testid="stDialog"] button[aria-label="Close"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    labels_map = model_labels or {}
    pitch_opts = pitch_options or []
    all_pitch_ids = [pid for pid, _ in pitch_opts]
    all_pitch_dict = dict(pitch_opts)

    pitches_df = _sort_pitches_by_address_df(
        scenario_pitches_df
        if scenario_pitches_df is not None
        else yamazumi_pitches_for_scenario(project_id, scenario_id)
    )
    if not all_pitch_ids and not pitches_df.empty:
        all_pitch_ids = pitches_df["id"].astype(str).tolist()
        all_pitch_dict = {
            str(r["id"]): f"{r['pitch_number']} — {r['pitch_name'] or 'Pitch'}"
            for _, r in pitches_df.iterrows()
        }

    # Group pitches by section
    sec_pitch_map: dict[str, list[str]] = {}
    for _, r in pitches_df.iterrows():
        s_id = str(r.get("section_id") or "").strip()
        sec_pitch_map.setdefault(s_id, []).append(str(r["id"]))

    sec_df = (
        sections
        if sections is not None
        else assembly_section_walk_order(project_id)
    )
    labels_dict = (
        section_labels
        if section_labels is not None
        else (dict(zip(sec_df["id"].astype(str), sec_df["name"].astype(str))) if not sec_df.empty else {})
    )

    curr_pitch_name = all_pitch_dict.get(
        selected_pitch_id, pitch_summary.get("pitch_number", "Pitch")
    )
    curr_pitch_idx = (
        all_pitch_ids.index(selected_pitch_id)
        if selected_pitch_id in all_pitch_ids
        else 0
    )

    # Determine current pitch's Fishbone section and active filter section
    curr_pitch_sec_id = str(pitch_summary.get("section_id") or "").strip()
    if not curr_pitch_sec_id:
        p_match = pitches_df.loc[pitches_df["id"].astype(str) == selected_pitch_id]
        if not p_match.empty:
            curr_pitch_sec_id = str(p_match.iloc[0].get("section_id") or "").strip()

    curr_pitch_sec_name = str(pitch_summary.get("section_name") or "").strip()
    if not curr_pitch_sec_name and curr_pitch_sec_id:
        curr_pitch_sec_name = labels_dict.get(curr_pitch_sec_id, "Current Section")

    # If the user has filtered by section in the PAAG slides viewer, respect that as the target section
    active_filter_id = (
        active_section_filter_id
        if (active_section_filter_id and active_section_filter_id not in {"__ALL__", "__UNASSIGNED__"})
        else ""
    )
    target_sec_id = active_filter_id or curr_pitch_sec_id
    target_sec_name = (
        labels_dict.get(target_sec_id, curr_pitch_sec_name or "Current Section")
        if target_sec_id
        else ""
    )
    target_sec_pitch_count = len(sec_pitch_map.get(target_sec_id, [])) if target_sec_id else 0

    top_col1, top_col2 = st.columns([5, 1], vertical_alignment="center")
    with top_col1:
        st.markdown("### Export and Print Process at a Glance")
    with top_col2:
        if st.button("✕ Close", key=f"print_dialog_exit_top_{scenario_id}", help="Close print window"):
            st.session_state[f"paag_print_active_{scenario_id}"] = False
            st.rerun()

    st.markdown("#### Export and Print Settings")

    col_scope, col_fmt = st.columns([1.5, 1.2])

    with col_scope:
        if all_pitch_ids:
            scope_choices = [
                f"Current slide only (Pitch {curr_pitch_idx + 1}, Slide {current_page}/{total_pages})",
                f"Current pitch (All {total_pages} slide{'s' if total_pages > 1 else ''})",
            ]
            if target_sec_id and target_sec_pitch_count > 0:
                scope_choices.append(
                    f"Current section: {target_sec_name} ({target_sec_pitch_count} pitch{'es' if target_sec_pitch_count != 1 else ''})"
                )
            scope_choices.append("Select specific section(s)...")
            scope_choices.append(
                f"All pitches in scenario / entire project ({len(all_pitch_ids)} pitches)"
            )
            scope_choices.append("Select specific pitches...")
        else:
            scope_choices = [
                f"Current slide only (Slide {current_page}/{total_pages})",
                f"Current pitch (All {total_pages} slide{'s' if total_pages > 1 else ''})",
            ]

        chosen_scope = st.radio(
            "Print Selection",
            scope_choices,
            index=0,
            key=f"paag_print_scope_{scenario_id}",
            help="Choose to print just the active slide, all slides for this pitch, a Fishbone section, or multiple pitches across the scenario.",
        )

        selected_sec_ids = []
        if "specific section" in chosen_scope:
            available_sec_ids = [
                str(r["id"])
                for _, r in sec_df.iterrows()
                if str(r["id"]) in sec_pitch_map
            ]
            if "" in sec_pitch_map and "" not in available_sec_ids:
                available_sec_ids.append("")

            def _fmt_sec_opt(sid: str) -> str:
                if not sid:
                    return "Unassigned Pitches"
                return labels_dict.get(sid, sid)

            def_secs = (
                [curr_pitch_sec_id]
                if curr_pitch_sec_id in available_sec_ids
                else available_sec_ids[:1]
            )
            selected_sec_ids = st.multiselect(
                "Choose Fishbone Section(s) to Print",
                options=available_sec_ids,
                default=def_secs,
                format_func=_fmt_sec_opt,
                key=f"paag_print_sec_multiselect_{scenario_id}",
                help="Select one or more Fishbone sections to print all pitches and slides within them.",
            )

        selected_pids = []
        if "specific pitches" in chosen_scope and all_pitch_ids:
            selected_pids = st.multiselect(
                "Choose Pitches to Include",
                options=all_pitch_ids,
                default=[selected_pitch_id] if selected_pitch_id in all_pitch_ids else all_pitch_ids[:1],
                format_func=lambda pid: f"Pitch {all_pitch_ids.index(pid) + 1}: {all_pitch_dict.get(pid, pid)}",
                key=f"paag_print_multiselect_{scenario_id}",
                help="Select one or more pitches to include in this print job.",
            )

    with col_fmt:
        format_choice = st.radio(
            "Page Format",
            ["8.5 × 11 in (Letter Landscape)", "11 × 17 in (Tabloid Landscape)"],
            index=0,
            key=f"paag_print_fmt_{scenario_id}",
            help="8.5x11 Letter is standard printer paper. 11x17 Tabloid gives more space for high-resolution layout.",
        )
        paper_size = "letter" if "8.5 × 11" in format_choice else "tabloid"

        fit_choice = st.radio(
            "Image Fit in Print",
            ["Stretch to Fill Box", "Preserve Aspect Ratio"],
            index=0,
            key=f"paag_print_fit_{scenario_id}",
            help="Stretch to Fill Box expands step photos to fill the page aspect ratio with zero letterbox bars.",
        )
        image_fit = "fill" if "Stretch" in fit_choice else "contain"

    # Resolve target list of pitches and pages
    if "Current slide only" in chosen_scope:
        targets = [(selected_pitch_id, [current_page])]
    elif "Current pitch" in chosen_scope:
        targets = [(selected_pitch_id, None)]
    elif "Current section" in chosen_scope:
        sec_pids = sec_pitch_map.get(target_sec_id, [selected_pitch_id])
        targets = [(pid, None) for pid in sec_pids]
    elif "specific section" in chosen_scope:
        targets = []
        for sid in selected_sec_ids:
            for pid in sec_pitch_map.get(sid, []):
                if (pid, None) not in targets:
                    targets.append((pid, None))
        if not targets:
            targets = [(selected_pitch_id, None)]
    elif "All pitches" in chosen_scope:
        targets = [(pid, None) for pid in all_pitch_ids] if all_pitch_ids else [(selected_pitch_id, None)]
    else:  # specific pitches
        effective_pids = selected_pids if selected_pids else ([selected_pitch_id] if selected_pitch_id else all_pitch_ids[:1])
        targets = [(pid, None) for pid in effective_pids]

    slides_html: list[str] = []
    with st.spinner("Compiling print slides..."):
        for pid, page_filter in targets:
            if pid == selected_pitch_id and pitch_summary:
                p_sum = pitch_summary
            else:
                try:
                    p_sum = process_pitch_visual_summary(project_id, scenario_id, pid)
                except Exception:
                    continue

            p_elements = p_sum.get("elements", [])
            p_tot_pages = max(page_count(len(p_elements)), p_sum.get("slide_count", 1), 1)
            pages_to_render = page_filter if page_filter is not None else list(range(1, p_tot_pages + 1))

            for pg in pages_to_render:
                p_rows = page_elements(p_elements, pg)
                for row in p_rows:
                    row["models"] = [
                        "All models" if model.casefold() in {"all", "all models"}
                        else labels_map.get(model, model)
                        for model in (split_filter_values(row.get("model_applicability")) or ["All"])
                    ]
                s_html = render_pitch_canvas(
                    p_sum,
                    p_rows,
                    scenario_name=scenario_name,
                    project_name=project_name,
                    page_num=pg,
                    total_pages=p_tot_pages,
                    print_format=paper_size,
                    image_fit=image_fit,
                )
                slides_html.append(s_html)

    if not slides_html:
        st.warning("No slides were selected for printing.")
        return

    total_deck_slides = len(slides_html)
    deck_title = f"PAAG - {scenario_name} - {paper_size.title()} Landscape"
    full_deck_html = render_printable_paag_deck(
        slides_html,
        paper_size=paper_size,
        image_fit=image_fit,
        title=deck_title,
    )

    paper_label = "8.5 × 11 in (Letter Landscape)" if paper_size == "letter" else "11 × 17 in (Tabloid Landscape)"
    st.info(f"Ready to print **{total_deck_slides} slide{'s' if total_deck_slides > 1 else ''}** on **{paper_label}** · Image Fit: **{fit_choice}**")

    # Scope signature hash to ensure all buttons and download buffers update immediately on every setting change
    scope_sig = f"{chosen_scope}_{paper_size}_{image_fit}_{total_deck_slides}_{len(targets)}"
    scope_slug = hashlib.md5(scope_sig.encode()).hexdigest()[:8]

    # Action Toolbar
    act_col1, act_col2 = st.columns([1.6, 1.4], vertical_alignment="center")
    with act_col1:
        escaped_deck_html = json.dumps(full_deck_html).replace("</script>", "<\\/script>").replace("</Script>", "<\\/Script>")
        action_btn_html = f"""<!DOCTYPE html>
<html>
<head>
<style>
  body {{
    margin: 0;
    padding: 2px 0;
    background: transparent;
    display: flex;
    align-items: center;
    gap: 10px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  .btn-print {{
    background: #0284c7;
    color: #ffffff !important;
    text-decoration: none;
    font-size: 0.95rem;
    font-weight: 700;
    padding: 8px 18px;
    border-radius: 6px;
    border: none;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    box-shadow: 0 1px 3px rgba(0,0,0,0.12);
  }}
  .btn-print:hover {{
    background: #0369a1;
  }}
  .btn-open {{
    background: #f1f5f9;
    color: #0f172a !important;
    text-decoration: none;
    font-size: 0.95rem;
    font-weight: 600;
    padding: 8px 14px;
    border-radius: 6px;
    border: 1px solid #cbd5e1;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
  }}
  .btn-open:hover {{
    background: #e2e8f0;
  }}
</style>
</head>
<body>
  <button id="btnActionPrint" class="btn-print" title="Opens print preview immediately for 1-click printing or PDF export">
    <span>🖨️</span> Print to PDF / Printer
  </button>
  <button id="btnActionOpen" class="btn-open" title="Open full multi-slide deck in new browser tab to view and scroll">
    <span>↗️</span> Open in New Tab
  </button>

  <script>
    const deckContent = {escaped_deck_html};
    
    document.getElementById("btnActionPrint").onclick = function(e) {{
      e.preventDefault();
      const printHtml = deckContent.replace('</body>', '<script>window.addEventListener("load", function(){{ setTimeout(function(){{ window.print(); }}, 400); }});<\\/script></body>');
      const blob = new Blob([printHtml], {{ type: "text/html;charset=utf-8" }});
      const blobUrl = URL.createObjectURL(blob);
      const win = window.open(blobUrl, "_blank");
      if (win) win.focus();
    }};

    document.getElementById("btnActionOpen").onclick = function(e) {{
      e.preventDefault();
      const blob = new Blob([deckContent], {{ type: "text/html;charset=utf-8" }});
      const blobUrl = URL.createObjectURL(blob);
      const win = window.open(blobUrl, "_blank");
      if (win) win.focus();
    }};
  </script>
</body>
</html>"""
        components.html(action_btn_html, height=45)

    with act_col2:
        safe_fn = f"PAAG_{scenario_name}_{paper_size}_{total_deck_slides}_slides.html".replace(" ", "_")
        st.download_button(
            f"Download HTML Deck ({total_deck_slides} Slide{'s' if total_deck_slides != 1 else ''})",
            data=full_deck_html,
            file_name=safe_fn,
            mime="text/html",
            icon=":material/download:",
            type="secondary",
            key=f"dl_deck_btn_{scenario_id}_{scope_slug}",
        )

    # Preview slide
    st.divider()
    st.caption(f"Preview (Slide 1 of {total_deck_slides} on {paper_label}):")
    st.html(slides_html[0], unsafe_allow_javascript=True)

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    if st.button("✕ Close Print Window", key=f"print_dialog_exit_bottom_{scenario_id}"):
        st.session_state[f"paag_print_active_{scenario_id}"] = False
        st.rerun()


@st.dialog("Functional Alerts & Review Links", width="large")
def alerts_detail_dialog(
    alerts: dict[str, list[dict]],
    project_id: str = "",
    scenario_id: str = "",
    pitch_id: str = "",
) -> None:
    st.markdown("#### Functional Alerts & Constraints")
    st.caption("Inspect workstation alerts and navigate directly to functional reviews or resolve classifications.")

    category_configs = [
        {
            "key": "quality",
            "title": "Quality (Torque & PFMEA)",
            "page": "app_pages/functional_quality.py",
            "button_label": "Open Quality Review",
            "icon": ":material/verified:",
        },
        {
            "key": "ergo",
            "title": "Ergonomics (Risk Reviews)",
            "page": "app_pages/functional_ergonomics.py",
            "button_label": "Open Ergonomics Review",
            "icon": ":material/accessibility_new:",
        },
        {
            "key": "safety",
            "title": "Safety Constraints",
            "page": "app_pages/functional_safety.py",
            "button_label": "Open Safety Review",
            "icon": ":material/health_and_safety:",
        },
        {
            "key": "materials",
            "title": "Materials Planning",
            "page": "app_pages/functional_materials.py",
            "button_label": "Open Materials Review",
            "icon": ":material/inventory_2:",
        },
        {
            "key": "equipment",
            "title": "Equipment & Tools",
            "page": "app_pages/functional_equipment.py",
            "button_label": "Open Equipment Review",
            "icon": ":material/precision_manufacturing:",
        },
    ]

    for cfg in category_configs:
        cat_key = cfg["key"]
        cat_title = cfg["title"]
        items = alerts.get(cat_key, [])
        with st.expander(f"{cat_title} ({len(items)})", expanded=bool(items)):
            c_hdr1, c_hdr2 = st.columns([2.5, 1.5], vertical_alignment="center")
            with c_hdr1:
                st.caption(f"Direct link to review and resolve constraints in {cat_title}.")
            with c_hdr2:
                if st.button(
                    f"{cfg['button_label']} ↗",
                    icon=cfg["icon"],
                    key=f"btn_nav_review_{cat_key}_{pitch_id}",
                    help=f"Navigate directly to {cat_title} review page",
                    width="stretch",
                ):
                    st.switch_page(cfg["page"])

            if cat_key == "materials":
                unclassified_options = []
                if project_id and scenario_id and pitch_id:
                    try:
                        unclassified_options = get_pitch_unclassified_part_options(
                            project_id, scenario_id, pitch_id
                        )
                    except Exception:
                        unclassified_options = []

                if unclassified_options:
                    st.markdown("##### 📦 Unclassified Parts on this Pitch")
                    st.caption(
                        "Materials Planner / IE: Assign a handling classification (**Consume** or **Handle**) "
                        "below to resolve unclassified materials alerts directly from this slide."
                    )
                    for opt in unclassified_options:
                        opt_id = opt["option_id"]
                        p_num = opt["part_number"]
                        p_desc = opt.get("part_description") or ""
                        op_title = opt.get("operation") or "Operation"
                        sec_name = opt.get("section_name") or ""
                        placements = opt.get("placements") or []

                        with st.container(border=True):
                            st.markdown(
                                f"**Part {p_num}**"
                                + (f" — {p_desc}" if p_desc else "")
                                + f"  \n`Step: {op_title}`"
                                + (f" · Section: {sec_name}" if sec_name else "")
                            )

                            selected_placement_id = opt.get("fishbone_assignment_id")
                            if not selected_placement_id and placements:
                                if len(placements) == 1:
                                    selected_placement_id = placements[0]["fishbone_assignment_id"]
                                else:
                                    pl_options = {
                                        p["fishbone_assignment_id"]: (
                                            f"{p.get('use_description') or 'Placement'} (Qty {p.get('fishbone_quantity')})"
                                        )
                                        for p in placements
                                    }
                                    selected_placement_id = st.selectbox(
                                        "Fishbone placement / location",
                                        options=list(pl_options.keys()),
                                        format_func=lambda k: pl_options.get(k, k),
                                        key=f"mat_placement_{opt_id}",
                                    )

                            c_ht, c_save = st.columns([2.5, 1], vertical_alignment="bottom")
                            with c_ht:
                                chosen_ht = st.selectbox(
                                    "Handling classification",
                                    ["(Select classification...)", "Consume", "Handle"],
                                    index=0,
                                    key=f"mat_ht_select_{opt_id}",
                                    help="Consume = first time on line from container. Handle = subsequent manipulation.",
                                )
                            with c_save:
                                if st.button(
                                    "Save",
                                    type="primary",
                                    icon=":material/save:",
                                    key=f"mat_save_btn_{opt_id}",
                                    disabled=(chosen_ht == "(Select classification...)"),
                                    width="stretch",
                                ):
                                    try:
                                        editor = st.session_state.get("current_editor", "")
                                        set_process_part_option_handling_type(
                                            project_id=project_id,
                                            scenario_id=scenario_id,
                                            process_part_option_id=opt_id,
                                            handling_type=chosen_ht,
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
                                                "handling_type": chosen_ht,
                                                "source": "PAAG Alerts dialog",
                                            },
                                        )
                                        st.toast(f"Classified part {p_num} as {chosen_ht}", icon=":material/check_circle:")
                                        st.success(f"Part {p_num} classified as {chosen_ht}!")
                                        st.rerun()
                                    except Exception as exc:
                                        st.error(str(exc))

                non_unclass_items = [
                    it for it in items
                    if "Unclassified Handling" not in str(it.get("label", ""))
                ]
                if non_unclass_items:
                    for it in non_unclass_items:
                        lbl = it.get("label") or "Alert"
                        det = it.get("detail") or ""
                        st.warning(f"**{lbl}**: {det}" if det else f"**{lbl}**")

                if not unclassified_options and not non_unclass_items:
                    st.success("✓ All materials on this pitch are classified and nominal.")

            else:
                if items:
                    for it in items:
                        lbl = it.get("label") or "Alert"
                        det = it.get("detail") or ""
                        st.warning(f"**{lbl}**: {det}" if det else f"**{lbl}**")
                else:
                    st.success("✓ No active alerts.")


@st.dialog("Tie Tool to Work Element")
def tie_tool_slide_dialog(
    project_id: str,
    scenario_id: str,
    pitch_id: str,
    pitch_summary: dict,
) -> None:
    st.caption(
        "Select a work element from this pitch and a tool type to tie that tool to the work element on the PAAG slide and in the Process at a Glance by Pitch table."
    )
    pitch_step_records: list[dict] = []
    seen_we_ids: set[str] = set()
    seen_yam_ids: set[str] = set()

    for idx, el in enumerate(pitch_summary.get("elements", []) or []):
        raw_we_id = str(el.get("work_element_id") or el.get("id") or "").strip()
        yam_id = str(el.get("yamazumi_element_id") or "").strip()
        if raw_we_id.startswith("yam::"):
            if not yam_id:
                yam_id = raw_we_id[5:].strip()
            we_id = ""
        else:
            we_id = raw_we_id
        if we_id:
            seen_we_ids.add(we_id)
        if yam_id:
            seen_yam_ids.add(yam_id)
        for mid in el.get("yamazumi_member_ids") or []:
            if str(mid).strip():
                seen_yam_ids.add(str(mid).strip())
        op_id = str(el.get("op_id") or "").strip()
        desc = str(
            el.get("operation") or el.get("yamazumi_description") or "Work Step"
        ).strip()
        curr_tool = str(el.get("tool") or "").strip()
        res_type = str(el.get("resource_type") or "Human").strip()
        res_detail = str(el.get("resource_detail") or "").strip()
        op_prefix = (
            f"{op_id} — "
            if op_id and op_id != "Yamazumi link required"
            else ""
        )
        tool_suffix = f"  [Current tool: {curr_tool}]" if curr_tool else ""
        step_key = we_id or f"yam::{yam_id}" or f"idx::{idx}"
        pitch_step_records.append(
            {
                "key": step_key,
                "work_element_id": we_id,
                "yamazumi_element_id": yam_id,
                "description": desc,
                "tool": curr_tool,
                "resource_type": res_type,
                "resource_detail": res_detail,
                "label": f"Step {idx + 1} · {op_prefix}{desc}{tool_suffix}",
            }
        )

    all_we_df = project_table(
        "work_elements", project_id, "sequence", scenario_id=scenario_id
    )
    we_op_ids: dict[str, str] = (
        work_element_op_ids(
            project_id, scenario_id, all_we_df["id"].astype(str).tolist()
        )
        if not all_we_df.empty and "id" in all_we_df.columns
        else {}
    )
    we_by_id: dict[str, dict] = (
        {
            str(row.get("id") or "").strip(): row.to_dict()
            for _, row in all_we_df.iterrows()
            if str(row.get("id") or "").strip()
        }
        if not all_we_df.empty
        else {}
    )

    for yel in pitch_summary.get("yamazumi_elements", []) or []:
        yam_id = str(yel.get("id") or "").strip()
        if not yam_id or yam_id in seen_yam_ids:
            continue
        if str(yel.get("work_type") or "Cycle").strip().casefold() != "cycle":
            continue
        seen_yam_ids.add(yam_id)
        we_id = str(yel.get("process_element_id") or "").strip()
        if we_id:
            seen_we_ids.add(we_id)
        linked_we = we_by_id.get(we_id, {}) if we_id else {}
        desc = str(
            linked_we.get("operation") or yel.get("description") or "Work Step"
        ).strip()
        curr_tool = str(linked_we.get("tool") or "").strip()
        res_type = str(linked_we.get("resource_type") or "Human").strip()
        res_detail = str(linked_we.get("resource_detail") or "").strip()
        op_id = str(we_op_ids.get(we_id) or "").strip() if we_id else ""
        op_prefix = (
            f"{op_id} — "
            if op_id and op_id != "Yamazumi link required"
            else ""
        )
        tool_suffix = f"  [Current tool: {curr_tool}]" if curr_tool else ""
        step_idx = len(pitch_step_records) + 1
        pitch_step_records.append(
            {
                "key": we_id or f"yam::{yam_id}",
                "work_element_id": we_id,
                "yamazumi_element_id": yam_id,
                "description": desc,
                "tool": curr_tool,
                "resource_type": res_type,
                "resource_detail": res_detail,
                "label": f"Step {step_idx} · {op_prefix}{desc}{tool_suffix}",
            }
        )

    pitch_number_str = str(pitch_summary.get("pitch_number") or "").strip()
    if pitch_number_str and not all_we_df.empty and "station" in all_we_df.columns:
        for _, w_row in all_we_df.iterrows():
            we_id = str(w_row.get("id") or "").strip()
            if not we_id or we_id in seen_we_ids:
                continue
            if str(w_row.get("station") or "").strip() != pitch_number_str:
                continue
            seen_we_ids.add(we_id)
            op_id = str(
                we_op_ids.get(we_id) or w_row.get("op_id") or ""
            ).strip()
            desc = str(w_row.get("operation") or "Work Step").strip()
            curr_tool = str(w_row.get("tool") or "").strip()
            res_type = str(w_row.get("resource_type") or "Human").strip()
            res_detail = str(w_row.get("resource_detail") or "").strip()
            op_prefix = (
                f"{op_id} — "
                if op_id and op_id != "Yamazumi link required"
                else ""
            )
            tool_suffix = f"  [Current tool: {curr_tool}]" if curr_tool else ""
            step_idx = len(pitch_step_records) + 1
            pitch_step_records.append(
                {
                    "key": we_id,
                    "work_element_id": we_id,
                    "yamazumi_element_id": str(
                        w_row.get("yamazumi_element_id") or ""
                    ).strip(),
                    "description": desc,
                    "tool": curr_tool,
                    "resource_type": res_type,
                    "resource_detail": res_detail,
                    "label": f"Step {step_idx} · {op_prefix}{desc}{tool_suffix}",
                }
            )

    if not pitch_step_records:
        st.info(
            "No work elements are assigned to this pitch yet. Assign work elements in Yamazumi or Process plan first."
        )
        return

    step_map = {rec["key"]: rec for rec in pitch_step_records}
    selected_step_key = st.selectbox(
        "Work Element",
        options=list(step_map.keys()),
        format_func=lambda k: step_map[k]["label"],
        key=f"slide_tie_tool_step_{scenario_id}_{pitch_id}",
    )
    active_rec = step_map[selected_step_key]
    existing_tool = str(active_rec.get("tool") or "").strip()
    existing_res_type = str(active_rec.get("resource_type") or "Human").strip()
    existing_res_detail = str(active_rec.get("resource_detail") or "").strip()

    all_types_df = equipment_types(project_id)
    type_labels = [
        str(lbl).strip()
        for lbl in all_types_df["label"].dropna().unique()
        if str(lbl).strip()
    ]
    for std_tool in [
        "Handheld equipment",
        "Torque tool",
        "Scan/Compare equipment",
        "Poka-Yoke / Fixture equipment",
        "Test equipment",
        "Tape machine",
        "Platform",
        "Pit",
        "Operator Lift",
        "Ergo Hand Tools",
        "Ergo Lift Assists",
    ]:
        if std_tool not in type_labels:
            type_labels.append(std_tool)
    type_labels.sort()
    tool_categories = ["(No tool required)", *type_labels, "Other tool"]

    default_cat_idx = 0
    if existing_tool:
        matched_cat = False
        for idx, cat in enumerate(tool_categories):
            if cat.casefold() == existing_tool.casefold():
                default_cat_idx = idx
                matched_cat = True
                break
        if not matched_cat:
            default_cat_idx = tool_categories.index("Other tool")

    selected_tool_type = st.selectbox(
        "Tool Type",
        options=tool_categories,
        index=default_cat_idx,
        key=f"slide_tie_tool_type_{scenario_id}_{pitch_id}_{selected_step_key}",
    )
    final_tool = ""
    if selected_tool_type == "(No tool required)":
        final_tool = ""
    elif selected_tool_type == "Other tool":
        default_custom_tool = (
            existing_tool
            if existing_tool
            and existing_tool.casefold()
            not in {c.casefold() for c in tool_categories}
            else ""
        )
        final_tool = (
            st.text_input(
                "Specify other tool",
                value=default_custom_tool,
                placeholder="Enter tool name",
                key=f"slide_tie_tool_custom_{scenario_id}_{pitch_id}_{selected_step_key}",
            ).strip()
            or "Other tool"
        )
    else:
        final_tool = selected_tool_type

    if st.button(
        "Submit Tool",
        type="primary",
        icon=":material/check:",
        width="stretch",
        key=f"btn_submit_slide_tool_{scenario_id}_{pitch_id}_{selected_step_key}",
    ):
        try:
            target_we_id = str(active_rec.get("work_element_id") or "").strip()
            yam_id = str(active_rec.get("yamazumi_element_id") or "").strip()
            if not target_we_id and yam_id:
                reconcile_yamazumi_to_process(project_id, scenario_id, [yam_id])
                target_we_id = str(
                    process_element_id_for_yamazumi(project_id, scenario_id, yam_id)
                    or ""
                ).strip()
            if not target_we_id:
                raise ValueError(
                    "Could not resolve a Process work element for the selected step."
                )
            editor = st.session_state.get("current_editor", "")
            update_work_element_tool_and_resource(
                project_id,
                scenario_id,
                target_we_id,
                tool=final_tool,
                resource_type=existing_res_type or "Human",
                resource_detail=existing_res_detail,
                editor_name=editor,
            )
            request_table_editor_reset(f"process_editor_{scenario_id}")
            record_audit_event(
                project_id,
                "Process plan",
                "Tie tool from PAAG slide",
                1,
                editor,
                {
                    "scenario_id": scenario_id,
                    "pitch_id": pitch_id,
                    "work_element_id": target_we_id,
                    "work_element": active_rec.get("description", ""),
                    "tool": final_tool,
                },
            )
            st.toast(
                f"Tied tool '{final_tool or 'None'}' to '{active_rec.get('description', 'Work Element')}'",
                icon=":material/check_circle:",
            )
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


@st.dialog("Tools & Equipment Required", width="large")
def tools_detail_dialog(
    tools: list[dict],
    project_id: str = "",
    scenario_id: str = "",
    pitch_id: str = "",
    pitch_summary: dict | None = None,
) -> None:
    if not tools:
        st.info("No equipment or PPE assigned to this pitch.")
        return
    for tool in tools:
        t_name = tool.get("name") or "Tool"
        t_type = tool.get("type_name") or ""
        is_ppe = tool.get("is_ppe", False)
        prefix = "[PPE] " if is_ppe else ""
        with st.expander(f"{prefix}{t_name}" + (f" ({t_type})" if t_type else ""), expanded=True):
            if tool.get("description"):
                st.write(tool["description"])
            mfg = tool.get("manufacturer")
            mdl = tool.get("model")
            if mfg or mdl:
                st.caption(f"Manufacturer: {mfg or 'N/A'} | Model: {mdl or 'N/A'}")
            if tool.get("notes"):
                st.info(tool["notes"])


@st.dialog("Edit Visual Aid", width="medium")
def edit_visual_media_dialog(
    media_id: str,
    current_caption: str,
    current_sequence: int,
    current_tags: list[str],
    element_options: list[tuple[str, str]],
    project_id: str,
    scenario_id: str,
    current_url: str = "",
) -> None:
    st.markdown("#### Edit Visual Aid Details")
    is_link = bool(current_url and current_url.startswith(("http://", "https://")))
    with st.form(f"form_edit_media_{media_id}"):
        new_url_input = None
        if is_link:
            new_url_input = st.text_input("Web Link URL", value=current_url)
        new_caption = st.text_input("Caption / Yellow Callout Note", value=current_caption)
        new_sequence = st.number_input("Sequence Order", value=int(current_sequence), step=5)
        tag_dict = dict(element_options)
        current_tags_on_this_pitch = [t for t in current_tags if t in tag_dict]
        other_pitch_tags = [t for t in current_tags if t not in tag_dict]

        new_tags = st.multiselect(
            "Tag to PAAG Work Elements (This Pitch)",
            options=list(tag_dict.keys()),
            default=current_tags_on_this_pitch,
            format_func=lambda tid: tag_dict.get(tid, tid),
            help="Select which work elements on this pitch this visual aid illustrates. Unchecking removes it from that element.",
        )
        if other_pitch_tags:
            st.caption(f"ℹ️ Also attached to {len(other_pitch_tags)} element(s) on other workstation pitches (preserved).")

        col1, col2 = st.columns([1, 1])
        if col1.form_submit_button("Save changes", icon=":material/save:", type="primary"):
            final_tags = list(dict.fromkeys(new_tags + other_pitch_tags))
            update_kwargs = {
                "project_id": project_id,
                "scenario_id": scenario_id,
                "media_id": media_id,
                "caption": new_caption,
                "sequence": new_sequence,
                "tagged_work_element_ids": final_tags,
                "current_editor": st.session_state.get("current_editor", ""),
            }
            if is_link and new_url_input is not None:
                update_kwargs["url"] = new_url_input.strip()
            update_pitch_visual_media(**update_kwargs)
            st.toast("Visual aid updated", icon=":material/check_circle:")
            st.rerun()
        if col2.form_submit_button("Cancel"):
            st.rerun()


@st.dialog("Copy Visual Aid", width="medium")
def copy_visual_media_dialog(
    media_id: str,
    current_pitch_id: str,
    current_caption: str,
    current_sequence: int,
    current_tags: list[str],
    element_options: list[tuple[str, str]],
    pitch_options: list[tuple[str, str]],
    project_id: str,
    scenario_id: str,
) -> None:
    st.markdown("#### Copy Visual Aid")
    st.caption(
        "Duplicate this visual aid on the current pitch or copy it to another pitch in this scenario. "
        "Annotations, original photo layers, and media files are copied independently."
    )
    pitch_dict = dict(pitch_options)
    pitch_ids = list(pitch_dict.keys()) if pitch_dict else [current_pitch_id]
    default_pitch_idx = (
        pitch_ids.index(current_pitch_id) if current_pitch_id in pitch_ids else 0
    )

    dest_pitch_id = st.selectbox(
        "Destination Pitch",
        options=pitch_ids,
        index=default_pitch_idx,
        format_func=lambda pid: (
            f"{pitch_dict.get(pid, pid)} (Current pitch)"
            if pid == current_pitch_id
            else pitch_dict.get(pid, pid)
        ),
        key=f"copy_media_dest_pitch_{media_id}",
        help="Keep the current pitch selected to duplicate this visual aid in place, or choose another pitch to copy it there.",
    )

    if dest_pitch_id == current_pitch_id:
        dest_element_options = element_options
    else:
        try:
            dest_summary = process_pitch_visual_summary(
                project_id, scenario_id, dest_pitch_id
            )
            dest_rows = dest_summary.get("elements") or []
        except Exception:
            dest_rows = []
        dest_element_options = [
            (
                str(el.get("work_element_id") or el.get("id")),
                f"{idx + 1} · {el.get('op_id') + ' — ' if el.get('op_id') and el.get('op_id') != 'Yamazumi link required' else ''}{el.get('operation') or el.get('yamazumi_description') or 'Work Step'}",
            )
            for idx, el in enumerate(dest_rows)
            if el.get("work_element_id") or el.get("id")
        ]

    tag_dict = dict(dest_element_options)
    default_tags = [t for t in current_tags if t in tag_dict]

    with st.form(f"form_copy_media_{media_id}_{dest_pitch_id}"):
        new_caption = st.text_input(
            "Caption / Yellow Callout Note", value=current_caption
        )
        new_sequence = st.number_input(
            "Sequence Order", value=int(current_sequence), step=5
        )
        new_tags = st.multiselect(
            "Tag to PAAG Work Elements (Destination Pitch)",
            options=list(tag_dict.keys()),
            default=default_tags,
            format_func=lambda tid: tag_dict.get(tid, tid),
            help="Select which work elements on the destination pitch this copied visual aid illustrates. Leave empty to show across all elements on that pitch.",
        )

        col1, col2 = st.columns([1, 1])
        if col1.form_submit_button(
            "Copy Visual Aid", icon=":material/content_copy:", type="primary"
        ):
            try:
                copy_pitch_visual_media(
                    project_id=project_id,
                    scenario_id=scenario_id,
                    media_id=media_id,
                    target_pitch_id=dest_pitch_id,
                    caption=new_caption,
                    tagged_work_element_ids=new_tags,
                    sequence=int(new_sequence),
                    current_editor=st.session_state.get("current_editor", ""),
                )
                dest_label = pitch_dict.get(dest_pitch_id, dest_pitch_id)
                st.toast(
                    f"Visual aid copied to {dest_label}",
                    icon=":material/check_circle:",
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        if col2.form_submit_button("Cancel"):
            st.rerun()


@st.dialog("Delete Visual Aid?", dismissible=False)
def delete_visual_media_dialog(
    media_id: str,
    caption: str,
    project_id: str,
    scenario_id: str,
) -> None:
    st.write("Are you sure you want to permanently delete this visual aid?")
    if caption:
        st.info(f"Caption: **{caption}**")
    st.caption("This will permanently remove the media file and unpair all associated work element tags. To remove it from an element without deleting the file, edit the visual aid and uncheck that element tag instead.")
    col1, col2 = st.columns([1, 1])
    if col1.button("Confirm Delete", icon=":material/delete:", type="primary", key=f"destructive_conf_del_{media_id}"):
        delete_pitch_visual_media(
            project_id=project_id,
            scenario_id=scenario_id,
            media_id=media_id,
            current_editor=st.session_state.get("current_editor", ""),
        )
        st.toast("Visual aid deleted", icon=":material/check_circle:")
        st.rerun()
    if col2.button("Cancel", key=f"cancel_del_{media_id}"):
        st.rerun()


def _build_annotator_catalog_photos(
    project_id: str,
    scenario_id: str,
    pitch_id: str = "",
) -> list[dict]:
    """Build JSON-serializable Parts Catalog photo payloads for the in-canvas image annotator picker."""
    if not project_id or not scenario_id:
        return []
    try:
        catalog_items = catalog_part_photos_for_pitch(project_id, scenario_id, pitch_id)
    except Exception:
        return []
    entries: list[dict] = []
    for part in catalog_items:
        p_num = str(part.get("part_number") or "").strip()
        p_desc = str(
            part.get("description") or part.get("factory_nickname") or ""
        ).strip()
        on_pitch = bool(part.get("on_pitch"))
        for view in part.get("views") or []:
            img_path_str = str(view.get("image_path") or "").strip()
            if not img_path_str or img_path_str.startswith(("http://", "https://")):
                continue
            p_obj = Path(img_path_str)
            if not p_obj.exists() and not p_obj.is_absolute():
                p_obj = ROOT / img_path_str
            if not p_obj.exists() or not p_obj.is_file():
                continue
            d_url = cached_image_data_url(p_obj, max_dim=480, output_format="PNG")
            if not d_url:
                continue
            entries.append(
                {
                    "part_id": str(part.get("part_id") or ""),
                    "part_number": p_num,
                    "description": p_desc,
                    "view_id": str(view.get("view_id") or ""),
                    "view_label": str(view.get("view_label") or "Primary Image"),
                    "on_pitch": on_pitch,
                    "data_url": d_url,
                }
            )
    return entries


def _clear_paag_annotate_media_dialog() -> None:
    scen_id = str(st.session_state.get("scenario_id") or "")
    if scen_id:
        st.session_state.pop(f"paag_annotate_media_{scen_id}", None)
    for k in [k for k in st.session_state.keys() if str(k).startswith("paag_annotate_media_")]:
        st.session_state.pop(k, None)


def _clear_paag_annotate_staged_dialog() -> None:
    scen_id = str(st.session_state.get("scenario_id") or "")
    if scen_id:
        st.session_state.pop(f"paag_annotate_staged_{scen_id}", None)
    for k in [k for k in st.session_state.keys() if str(k).startswith("paag_annotate_staged_")]:
        st.session_state.pop(k, None)


@st.dialog("Annotate Visual Aid", width="large", on_dismiss=_clear_paag_annotate_media_dialog)
def annotate_visual_media_dialog(
    media_id: str,
    file_path: str,
    original_file_path: str,
    annotations_json: str,
    caption: str,
    project_id: str,
    scenario_id: str,
    pitch_id: str = "",
) -> None:
    st.markdown(f"#### Annotate Visual Aid: {caption or 'Visual Aid'}")
    st.caption(
        "Crop, rotate in 90° increments, insert overlay photos from the **Parts Catalog** (`📦 Part Photo`) or **Clipboard** (`📋 Paste Photo` / `Ctrl+V`), "
        "or add directional arrows, callout text boxes (adjust font size with **Text** / **A−** / **A+** or drag the callout corner), focus boxes/circles, "
        "step number badges (1, 2, 3), and freehand pen markup. Click **💾 Apply & Save Markup** when finished."
    )

    source_path = None
    if original_file_path:
        p = Path(original_file_path)
        if p.exists() and p.is_file():
            source_path = p
        else:
            rebased = resolve_upload_path(original_file_path, ROOT / "data" / "uploads")
            if rebased is not None and rebased.exists() and rebased.is_file():
                source_path = rebased
    if not source_path and file_path:
        p = Path(file_path)
        if p.exists() and p.is_file():
            source_path = p
        else:
            rebased = resolve_upload_path(file_path, ROOT / "data" / "uploads")
            if rebased is not None and rebased.exists() and rebased.is_file():
                source_path = rebased

    if not source_path:
        st.error("Image file could not be found on disk.")
        if st.button("Close"):
            _clear_paag_annotate_media_dialog()
            st.rerun()
        return

    data_url = cached_image_data_url(source_path, max_dim=None, output_format=None)
    if not data_url:
        raw_bytes = source_path.read_bytes()
        suffix = source_path.suffix.lower()
        mime = "image/png" if suffix == ".png" else "image/webp" if suffix == ".webp" else "image/jpeg"
        b64 = base64.b64encode(raw_bytes).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"

    annotator_res = image_annotator(
        image_data_url=data_url,
        annotations_json=annotations_json or "",
        key=f"annotator_existing_{media_id}",
        catalog_photos=_build_annotator_catalog_photos(project_id, scenario_id, pitch_id),
    )

    save_payload = getattr(annotator_res, "save", None)
    if save_payload:
        try:
            new_annotations = save_payload.get("annotations_json", "")
            new_data_url = save_payload.get("data_url", "")
            composite_bytes = decode_data_url(new_data_url) if new_data_url else None
            update_pitch_visual_annotations(
                project_id=project_id,
                scenario_id=scenario_id,
                media_id=media_id,
                annotations_json=new_annotations,
                composite_image_bytes=composite_bytes,
                current_editor=st.session_state.get("current_editor", ""),
            )
            _clear_paag_annotate_media_dialog()
            st.toast("Annotations saved!", icon=":material/check_circle:")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    st.caption("Tip: Select existing shapes or inserted photos (`👆 Select`) to move, resize via corner handles, adjust callout text font size (`Text:` / `A−` / `A+`), recolor borders, or delete them non-destructively.")
    if st.button("Close without saving", key=f"btn_close_annotator_{media_id}"):
        _clear_paag_annotate_media_dialog()
        st.rerun()


@st.dialog("Annotate Staged Visual Aid", width="large", on_dismiss=_clear_paag_annotate_staged_dialog)
def annotate_staged_media_dialog(
    pitch_id: str,
    project_id: str = "",
    scenario_id: str = "",
) -> None:
    staged = st.session_state.get(f"staged_media_{pitch_id}")
    if not staged or not staged.get("original_bytes"):
        st.info("No staged image found to annotate.")
        if st.button("Close"):
            _clear_paag_annotate_staged_dialog()
            st.rerun()
        return

    resolved_project_id = project_id or str(st.session_state.get("project_id") or "")
    resolved_scenario_id = scenario_id or str(st.session_state.get("scenario_id") or "")

    st.markdown("#### Annotate Staged Visual Aid")
    st.caption(
        "Crop, rotate in 90° increments, insert overlay photos from the **Parts Catalog** (`📦 Part Photo`) or **Clipboard** (`📋 Paste Photo` / `Ctrl+V`), "
        "or add arrows, callouts, shapes, and badges to this image before adding it to the PAAG slide. "
        "Click **💾 Apply & Save Markup** to apply your changes."
    )

    raw_bytes = staged["original_bytes"]
    mime = staged.get("mime_type", "image/png")
    b64 = base64.b64encode(raw_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    annotator_res = image_annotator(
        image_data_url=data_url,
        annotations_json=staged.get("annotations_json", ""),
        key=f"annotator_staged_{pitch_id}",
        catalog_photos=_build_annotator_catalog_photos(
            resolved_project_id, resolved_scenario_id, pitch_id
        ),
    )

    save_payload = getattr(annotator_res, "save", None)
    if save_payload:
        try:
            new_annotations = save_payload.get("annotations_json", "")
            new_data_url = save_payload.get("data_url", "")
            composite_bytes = decode_data_url(new_data_url) if new_data_url else raw_bytes
            staged["composite_bytes"] = composite_bytes
            staged["annotations_json"] = new_annotations
            st.session_state[f"staged_media_{pitch_id}"] = staged
            _clear_paag_annotate_staged_dialog()
            st.toast("Markup applied to staged image!", icon=":material/check_circle:")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    if st.button("Close without saving", key=f"btn_close_staged_{pitch_id}"):
        _clear_paag_annotate_staged_dialog()
        st.rerun()


@st.dialog("Delete Staged Visual Aid?", dismissible=False)
def discard_staged_media_dialog(pitch_id: str) -> None:
    st.warning("Delete this staged visual aid before saving?")
    st.caption(
        "Downstream effects: This discards the unsaved image upload or clipboard capture and any unsaved markup, crop, or rotation. "
        "Already-saved visual aids on this pitch and the PAAG slide remain unchanged."
    )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_discard_staged_{pitch_id}"):
        st.rerun()
    if actions.button(
        "Delete",
        type="primary",
        icon=":material/delete:",
        key=f"destructive_confirm_discard_staged_{pitch_id}",
        on_click=lambda: st.toast("Discarded staged visual aid", icon=":material/delete:"),
    ):
        cur_staged = st.session_state.get(f"staged_media_{pitch_id}")
        if isinstance(cur_staged, dict) and cur_staged.get("source") == "upload":
            st.session_state[f"_consumed_visual_up_hash_{pitch_id}"] = cur_staged.get("hash")
        st.session_state.pop(f"staged_media_{pitch_id}", None)
        _clear_paag_annotate_staged_dialog()
        st.rerun()


_paag_tab_options = ["Process Plan", "Process Flow Diagram", "PAAG Slides"]
_paag_tab_legacy_aliases = {
    "Process plan": "Process Plan",
    "PAAG slides": "PAAG Slides",
}
_qp_paag_tab = str(st.query_params.get("paag_tab", "") or "").strip()
_qp_paag_tab = _paag_tab_legacy_aliases.get(_qp_paag_tab, _qp_paag_tab)
if _qp_paag_tab in _paag_tab_options:
    st.session_state["paag_tab"] = _qp_paag_tab
    try:
        del st.query_params["paag_tab"]
    except Exception:
        pass
if st.session_state.get("paag_tab") in _paag_tab_legacy_aliases:
    st.session_state["paag_tab"] = _paag_tab_legacy_aliases[st.session_state["paag_tab"]]
if "paag_tab" not in st.session_state and st.query_params.get("active_pitch"):
    st.session_state["paag_tab"] = "PAAG Slides"

tab_plan, tab_flow, tab_slides = guarded_tabs(
    _paag_tab_options,
    key="paag_tab",
)

_PAAG_TAB_WIDGET_PREFIXES: dict[str, tuple[str, ...]] = {
    "Process Plan": (
        f"process_pairing_section_{scenario_id}",
        f"process_pairing_search_{scenario_id}_",
        f"process_yamazumi_pitch_{scenario_id}_",
        f"process_yamazumi_model_{scenario_id}_",
        f"process_parts_handled_{scenario_id}_",
        f"process_parts_model_{scenario_id}_",
        f"process_parts_search_{scenario_id}_",
        f"process_pairing_rule_{scenario_id}_",
        f"process_pairing_model_variant_{scenario_id}_",
        f"process_pairing_handling_{scenario_id}_",
        f"process_pairing_quantity_{scenario_id}_",
        f"process_pairing_location_{scenario_id}_",
        f"process_tool_cat_{scenario_id}_",
        f"process_tool_specific_{scenario_id}_",
        f"process_res_type_{scenario_id}_",
        f"process_res_detail_{scenario_id}_",
        f"process_pairing_requirement_{scenario_id}_",
        f"process_pairing_notes_{scenario_id}_",
    ),
    "Process Flow Diagram": (
        f"pfd_shape_mode_{scenario_id}",
    ),
    "PAAG Slides": (
        "input_caption_visual_",
        "select_tags_visual_",
        "input_seq_visual_",
        "input_url_visual_",
        "input_link_cap_visual_",
        "select_link_tags_",
        "input_link_seq_",
        "radio_part_photo_scope_",
        "select_catalog_part_visual_",
        "select_catalog_part_view_",
        "input_part_cap_visual_",
        "select_part_tags_visual_",
        "input_part_seq_visual_",
    ),
}
_paag_tab_snapshots_key = f"_paag_tab_snapshots_{scenario_id}"
_paag_last_open_tab_key = f"_paag_last_open_tab_{scenario_id}"


def _save_paag_tab_snapshot(tab_name: str) -> None:
    prefixes = _PAAG_TAB_WIDGET_PREFIXES.get(tab_name, ())
    if not prefixes:
        return
    snapshots = dict(st.session_state.get(_paag_tab_snapshots_key) or {})
    tab_snap = dict(snapshots.get(tab_name) or {})
    for k in list(st.session_state.keys()):
        k_str = str(k)
        if k_str.startswith(prefixes):
            try:
                tab_snap[k_str] = deepcopy(st.session_state[k])
            except Exception:
                tab_snap[k_str] = st.session_state[k]
    snapshots[tab_name] = tab_snap
    st.session_state[_paag_tab_snapshots_key] = snapshots


def _restore_paag_tab_snapshot(tab_name: str) -> None:
    snapshots = st.session_state.get(_paag_tab_snapshots_key)
    if not isinstance(snapshots, dict):
        return
    tab_snap = snapshots.get(tab_name)
    if not isinstance(tab_snap, dict):
        return
    for k_str, val in tab_snap.items():
        if k_str not in st.session_state:
            try:
                st.session_state[k_str] = deepcopy(val)
            except Exception:
                st.session_state[k_str] = val


def _pop_paag_tab_state(key: str, default: object = None) -> object:
    val = st.session_state.pop(key, default)
    snapshots = st.session_state.get(_paag_tab_snapshots_key)
    if isinstance(snapshots, dict):
        for tab_snap in snapshots.values():
            if isinstance(tab_snap, dict):
                tab_snap.pop(str(key), None)
    return val


_current_open_paag_tab = (
    "Process Plan"
    if tab_plan.open
    else ("Process Flow Diagram" if tab_flow.open else "PAAG Slides")
)
_prev_open_paag_tab = st.session_state.get(_paag_last_open_tab_key)
if (
    isinstance(_prev_open_paag_tab, str)
    and _prev_open_paag_tab in _PAAG_TAB_WIDGET_PREFIXES
    and _prev_open_paag_tab != _current_open_paag_tab
):
    _save_paag_tab_snapshot(_prev_open_paag_tab)
_restore_paag_tab_snapshot(_current_open_paag_tab)
st.session_state[_paag_last_open_tab_key] = _current_open_paag_tab

if tab_plan.open:
    with tab_plan:
        hdr_col_title, hdr_col_links = st.columns([3, 2], vertical_alignment="center")
        with hdr_col_title:
            st.subheader("Create PAAG Elements")
        with hdr_col_links:
            hdr_links_bar = st.container(horizontal=True, horizontal_alignment="right")
            hdr_links_bar.link_button(
                "Open Slides in New Window",
                url=build_page_url("process", query_params={"paag_tab": "PAAG Slides"}),
                icon=":material/open_in_new:",
                help="Open PAAG Slides in a separate browser window to view slides alongside your process plan",
            )
            hdr_links_bar.link_button(
                "Open Parts in New Window",
                url=build_page_url("parts"),
                icon=":material/open_in_new:",
                help="Open Parts Catalog in a separate browser window to cross-reference parts",
            )
        st.caption(
            "The selected fishbone section controls both lists. Use **Model choice** for alternatives such "
            "as black or silver versions of the same panel."
        )
        if not section_ids:
            st.info("Create and populate the Fishbone framework before adding PAAG Elements to process work.")
        else:
            process_section_key = f"process_pairing_section_{scenario_id}"
            if (
                process_section_key in st.session_state
                and st.session_state.get(process_section_key) not in section_ids
            ):
                _pop_paag_tab_state(process_section_key, None)
            section_id = st.selectbox(
                "Fishbone Section",
                section_ids,
                index=None if process_section_key in st.session_state else 0,
                format_func=lambda value: section_labels.get(value, value),
                key=process_section_key,
            )
            pairing_search = st.text_input(
                "Filter Work Elements or Parts",
                placeholder="Search descriptions, pitches, part numbers, or uses",
                key=f"process_pairing_search_{scenario_id}_{section_id}",
            ).strip().casefold()

            yamazumi_rows = yamazumi_elements_for_section(project_id, scenario_id, section_id)
            if not yamazumi_rows.empty:
                yamazumi_rows["work_type"] = (
                    yamazumi_rows["work_type"]
                    .fillna("Cycle")
                    .astype(str)
                    .str.strip()
                    .str.capitalize()
                    .replace({"": "Cycle"})
                )
                yamazumi_rows = yamazumi_rows.loc[
                    yamazumi_rows["work_type"].str.casefold() == "cycle"
                ].copy()
            section_has_yamazumi_work = not yamazumi_rows.empty
            if not yamazumi_rows.empty:
                yamazumi_rows["model_variants"] = [
                    parse_yamazumi_model_variants(mv, str(m_single or "Base"))
                    for mv, m_single in zip(
                        yamazumi_rows["model_variants"],
                        yamazumi_rows["model_variant"],
                    )
                ]
                reflected_in_process = yamazumi_rows["process_reflected"].fillna(0).astype(bool)
                all_section_yamazumi_rows = yamazumi_rows.copy()
                yamazumi_rows = yamazumi_rows.loc[~reflected_in_process].copy()
            else:
                all_section_yamazumi_rows = yamazumi_rows.copy()
            section_has_available_yamazumi_work = not yamazumi_rows.empty

            pitch_options: list[str] = ["All pitches"]
            pitch_label_map: dict[str, str] = {
                "All pitches": "All pitches",
                "Unassigned": "Unassigned",
            }
            if not all_section_yamazumi_rows.empty:
                discovered_pitches: list[str] = []
                for p_num_val, p_name_val in zip(
                    all_section_yamazumi_rows["pitch_number"],
                    all_section_yamazumi_rows["pitch_name"],
                ):
                    p_num = str(p_num_val or "").strip()
                    p_name = str(p_name_val or "").strip()
                    if p_num and p_num not in pitch_label_map:
                        discovered_pitches.append(p_num)
                        pitch_label_map[p_num] = f"{p_num} — {p_name}" if p_name else p_num
                pitch_options.extend(sorted(discovered_pitches, key=_pitch_address_sort_key))
                if (
                    all_section_yamazumi_rows["pitch_number"].isna()
                    | all_section_yamazumi_rows["pitch_number"].astype(str).str.strip().eq("")
                ).any():
                    if "Unassigned" not in pitch_options:
                        pitch_options.append("Unassigned")

            available_work_model_values: set[str] = set()
            if (
                not all_section_yamazumi_rows.empty
                and "model_variants" in all_section_yamazumi_rows.columns
            ):
                for val in all_section_yamazumi_rows["model_variants"].dropna():
                    for m in split_filter_values(val):
                        clean_m = m.strip()
                        if clean_m and clean_m.casefold() not in {"all", "all models"}:
                            available_work_model_values.add(
                                model_labels.get(clean_m, clean_m)
                            )
            all_project_models = [
                label
                for label in model_labels.values()
                if label != "Common name not defined"
            ]
            work_model_options = [
                "All models",
                *sorted(
                    set(all_project_models) | available_work_model_values,
                    key=str.casefold,
                ),
            ]

            all_placements = fishbone_part_assignments(project_id, scenario_id)
            if not all_placements.empty:
                section_placements = all_placements.loc[
                    all_placements["section_id"].astype(str) == section_id
                ].copy()
            else:
                section_placements = all_placements.copy()
            section_has_fishbone_parts = not section_placements.empty

            consumed_part_ids: set[str] = set()
            handled_part_ids: set[str] = set()
            for group in process_part_groups(project_id, scenario_id, active_only=True):
                for option in group.get("options", []):
                    opt_pid = str(option.get("part_id"))
                    htype = str(option.get("handling_type") or "").strip().capitalize()
                    if htype == "Consume":
                        consumed_part_ids.add(opt_pid)
                    elif htype == "Handle":
                        handled_part_ids.add(opt_pid)

            candidate_placements = (
                all_placements.loc[
                    (all_placements["section_id"].astype(str) == section_id)
                    | (all_placements["part_id"].astype(str).isin(consumed_part_ids))
                ].copy()
                if not all_placements.empty
                else all_placements.copy()
            )
            if candidate_placements.empty:
                available_parts = candidate_placements.copy()
            else:
                candidate_placements["_in_section_rank"] = (
                    candidate_placements["section_id"].astype(str) != str(section_id)
                ).astype(int)
                available_parts = (
                    candidate_placements.sort_values(
                        ["_in_section_rank", "part_number", "sequence", "id"]
                    )
                    .drop_duplicates(subset=["part_id"], keep="first")
                    .drop(columns=["_in_section_rank"])
                    .copy()
                )
                section_placement_counts = (
                    section_placements.groupby("part_id").size()
                    if not section_placements.empty
                    else pd.Series(dtype=int)
                )
                all_placement_counts = (
                    all_placements.groupby("part_id").size()
                    if not all_placements.empty
                    else pd.Series(dtype=int)
                )
                available_parts["fishbone_use_count"] = (
                    available_parts["part_id"]
                    .map(section_placement_counts)
                    .fillna(available_parts["part_id"].map(all_placement_counts))
                    .fillna(0)
                    .astype(int)
                )

            def _calc_part_handling(part_id_val: object) -> str:
                pid = str(part_id_val)
                is_c = pid in consumed_part_ids
                is_h = pid in handled_part_ids
                if is_c and is_h:
                    return "Consumed, Handled"
                if is_c:
                    return "Consumed"
                if is_h:
                    return "Handled"
                return "Unassigned"

            if not available_parts.empty:
                available_parts["handling"] = [
                    _calc_part_handling(pid) for pid in available_parts["part_id"]
                ]
                if "factory_nickname" not in available_parts.columns:
                    available_parts["factory_nickname"] = ""
            else:
                available_parts["handling"] = pd.Series(dtype="string")
                available_parts["factory_nickname"] = pd.Series(dtype="string")
            section_has_available_fishbone_parts = not available_parts.empty
            all_available_parts = available_parts.copy()

            if pairing_search and not yamazumi_rows.empty:
                yam_mask = pd.Series(False, index=yamazumi_rows.index)
                for column in ["description", "area_name", "pitch_number", "pitch_name", "model_variants", "work_type"]:
                    if column in yamazumi_rows.columns:
                        yam_mask |= yamazumi_rows[column].fillna("").astype(str).str.casefold().str.contains(
                            pairing_search, regex=False
                        )
                yamazumi_rows = yamazumi_rows.loc[yam_mask].copy()
            if pairing_search and not candidate_placements.empty:
                placement_mask = pd.Series(False, index=candidate_placements.index)
                search_cols = ["part_number", "description", "use_description", "model_applicability"]
                if "factory_nickname" in candidate_placements.columns:
                    search_cols.append("factory_nickname")
                if "section_name" in candidate_placements.columns:
                    search_cols.append("section_name")
                for column in search_cols:
                    placement_mask |= candidate_placements[column].fillna("").astype(str).str.casefold().str.contains(
                        pairing_search, regex=False
                    )
                matching_part_ids = set(
                    candidate_placements.loc[placement_mask, "part_id"].astype(str)
                )
                available_parts = available_parts.loc[
                    available_parts["part_id"].astype(str).isin(matching_part_ids)
                ].copy()

            work_column, part_column = st.columns(2, vertical_alignment="top")
            work_source_key = apply_pending_table_editor_reset(
                f"process_yamazumi_source_{scenario_id}_{section_id}"
            )
            not_consumed_part_source_key = apply_pending_table_editor_reset(
                f"process_part_source_{scenario_id}_{section_id}"
            )
            consumed_part_source_key = apply_pending_table_editor_reset(
                f"process_part_source_consumed_{scenario_id}_{section_id}"
            )
            work_selection_expired = False
            part_selection_expired = False
            with work_column.container(border=True, height="stretch"):
                st.markdown("#### Yamazumi Work Elements")
                st.caption("Select the work element that uses the parts.")

                work_filter_cols = st.columns([1, 1], vertical_alignment="bottom")
                _yam_pitch_filter_key = f"process_yamazumi_pitch_{scenario_id}_{section_id}"
                if (
                    _yam_pitch_filter_key in st.session_state
                    and st.session_state.get(_yam_pitch_filter_key) not in pitch_options
                ):
                    _pop_paag_tab_state(_yam_pitch_filter_key, None)
                _yam_model_filter_key = f"process_yamazumi_model_{scenario_id}_{section_id}"
                if (
                    _yam_model_filter_key in st.session_state
                    and st.session_state.get(_yam_model_filter_key) not in work_model_options
                ):
                    _pop_paag_tab_state(_yam_model_filter_key, None)
                pitch_filter = work_filter_cols[0].selectbox(
                    "Pitch",
                    options=pitch_options,
                    format_func=lambda val: pitch_label_map.get(val, val),
                    key=f"process_yamazumi_pitch_{scenario_id}_{section_id}",
                    help="Filter Yamazumi work elements by pitch.",
                )
                work_model_filter = work_filter_cols[1].selectbox(
                    "Model",
                    options=work_model_options,
                    key=f"process_yamazumi_model_{scenario_id}_{section_id}",
                    help="Filter work elements by vehicle model variant.",
                )

                has_active_work_filters = (
                    pitch_filter != "All pitches"
                    or work_model_filter != "All models"
                )
                filtered_yamazumi = yamazumi_rows.copy()
                if not filtered_yamazumi.empty:
                    if pitch_filter != "All pitches":
                        if pitch_filter == "Unassigned":
                            pitch_mask = (
                                filtered_yamazumi["pitch_number"].isna()
                                | filtered_yamazumi["pitch_number"].astype(str).str.strip().eq("")
                                | filtered_yamazumi["pitch_number"].astype(str).str.strip().casefold().eq("unassigned")
                            )
                        else:
                            pitch_mask = (
                                filtered_yamazumi["pitch_number"].fillna("").astype(str).str.strip()
                                == pitch_filter
                            )
                        filtered_yamazumi = filtered_yamazumi.loc[pitch_mask].copy()

                    if work_model_filter != "All models":
                        def _element_matches_model(variants_val: object) -> bool:
                            items = split_filter_values(variants_val)
                            if not items:
                                return True
                            target_num = model_numbers_by_label.get(work_model_filter, work_model_filter)
                            for item in items:
                                item_str = str(item).strip()
                                if item_str.casefold() in {"all", "all models"}:
                                    return True
                                mapped_label = model_labels.get(item_str, item_str)
                                if (
                                    work_model_filter.casefold() == mapped_label.casefold()
                                    or work_model_filter.casefold() == item_str.casefold()
                                    or target_num.casefold() == item_str.casefold()
                                ):
                                    return True
                            return False

                        filtered_yamazumi = filtered_yamazumi.loc[
                            filtered_yamazumi["model_variants"].apply(_element_matches_model)
                        ].copy()

                work_sig_key = f"process_yamazumi_visible_rows_{scenario_id}_{section_id}"
                current_work_ids = (
                    tuple(filtered_yamazumi["id"].astype(str))
                    if not filtered_yamazumi.empty
                    else ()
                )
                if (
                    work_sig_key in st.session_state
                    and st.session_state[work_sig_key] != current_work_ids
                ):
                    st.session_state.pop(work_source_key, None)
                    st.session_state.pop(f"_saved_selectable_df_{work_source_key}", None)
                st.session_state[work_sig_key] = current_work_ids

                if filtered_yamazumi.empty:
                    if (pairing_search or has_active_work_filters) and section_has_available_yamazumi_work:
                        st.info("No available Yamazumi work matches the selected filters.")
                    elif section_has_yamazumi_work:
                        st.info("All work in this section is already reflected below.")
                    else:
                        st.info("No work is linked to this fishbone section.")
                    selected_yamazumi = filtered_yamazumi
                else:
                    work_event = selectable_dataframe(
                        filtered_yamazumi,
                        key=work_source_key,
                        hide_index=True,
                        on_select="rerun",
                        selection_mode="multi-row",
                        column_order=[
                            "pitch_number",
                            "description",
                            "time_s",
                            "model_variants",
                            "material_group_count",
                        ],
                        column_config={
                            "pitch_number": st.column_config.TextColumn("Pitch", pinned=True),
                            "description": st.column_config.TextColumn("Work element", width="large"),
                            "time_s": st.column_config.NumberColumn("Time (s)", format="%.1f"),
                            "model_variants": st.column_config.ListColumn("Models"),
                            "material_group_count": st.column_config.NumberColumn("Part requirements"),
                            "process_sync_status": None,
                        },
                    )
                    work_selection_rows = list(work_event.selection.rows)
                    valid_work_selection_rows = [
                        row
                        for row in work_selection_rows
                        if isinstance(row, int) and 0 <= row < len(filtered_yamazumi)
                    ]
                    work_selection_expired = len(valid_work_selection_rows) != len(
                        work_selection_rows
                    )
                    selected_yamazumi = filtered_yamazumi.iloc[
                        [] if work_selection_expired else valid_work_selection_rows
                    ]

            with part_column.container(border=True, height="stretch"):
                st.markdown("#### Available Fishbone Parts")
                st.caption("Select one or more catalog parts from this section.")
                st.caption(
                    "Don't see your part? Check whether it is in another fishbone section, "
                    "or add it to the Parts Catalog and this section without leaving the page."
                )
                find_or_add_part = st.button(
                    "Find or add a missing part",
                    icon=":material/search:",
                    type="tertiary",
                    key=f"process_find_or_add_part_{scenario_id}_{section_id}",
                )
                if find_or_add_part:
                    if table_has_unsaved_changes(process_editor_key, native_row_selection=True):
                        st.warning("Save or undo Process at a Glance table edits first.")
                    else:
                        st.session_state[missing_part_dialog_key] = True
                filter_cols = st.columns([1, 1, 1], vertical_alignment="bottom")

                handled_filter = filter_cols[0].selectbox(
                    "Handled",
                    options=["All", "Handled", "Not handled"],
                    key=f"process_parts_handled_{scenario_id}_{section_id}",
                    help="Filter parts that have or have not been handled in this scenario.",
                )

                available_model_values: set[str] = set()
                if not available_parts.empty and "model_applicability" in available_parts.columns:
                    for val in available_parts["model_applicability"].dropna():
                        for m in split_filter_values(val):
                            clean_m = m.strip()
                            if clean_m and clean_m.casefold() not in {"all", "all models"}:
                                available_model_values.add(model_labels.get(clean_m, clean_m))
                all_project_models = [
                    label for label in model_labels.values() if label != "Common name not defined"
                ]
                model_options = [
                    "All models",
                    *sorted(set(all_project_models) | available_model_values, key=str.casefold),
                ]
                _parts_model_key = f"process_parts_model_{scenario_id}_{section_id}"
                if (
                    _parts_model_key in st.session_state
                    and st.session_state.get(_parts_model_key) not in model_options
                ):
                    _pop_paag_tab_state(_parts_model_key, None)
                model_filter = filter_cols[1].selectbox(
                    "Model",
                    options=model_options,
                    key=f"process_parts_model_{scenario_id}_{section_id}",
                    help="Filter parts by vehicle model applicability.",
                )

                nickname_key = f"process_show_factory_nickname_{scenario_id}"
                show_nickname = st.session_state.get(nickname_key, False)
                eye_icon = ":material/visibility:" if show_nickname else ":material/visibility_off:"
                eye_help = "Hide Factory Nickname on table" if show_nickname else "Show Factory Nickname on table"
                if filter_cols[2].button(
                    "Nickname",
                    icon=eye_icon,
                    help=eye_help,
                    type="primary" if show_nickname else "secondary",
                    key=f"process_toggle_fn_{scenario_id}_{section_id}",
                ):
                    st.session_state[nickname_key] = not show_nickname
                    st.rerun()

                parts_search = (
                    st.text_input(
                        "Search parts",
                        placeholder="Search part number, name, nickname, or model",
                        key=f"process_parts_search_{scenario_id}_{section_id}",
                        help="Search both Not consumed parts and Consumed parts by part number, part name, factory nickname, use description, or model. Selected parts remain selected while you search for additional parts.",
                    )
                    .strip()
                    .casefold()
                )

                if not available_parts.empty:
                    if parts_search:
                        parts_search_mask = pd.Series(
                            False, index=available_parts.index
                        )
                        part_search_cols = [
                            "part_number",
                            "description",
                            "factory_nickname",
                            "handling",
                            "model_applicability",
                            "use_description",
                            "section_name",
                        ]
                        for col in part_search_cols:
                            if col in available_parts.columns:
                                parts_search_mask |= (
                                    available_parts[col]
                                    .fillna("")
                                    .astype(str)
                                    .str.casefold()
                                    .str.contains(parts_search, regex=False)
                                )
                        if not candidate_placements.empty:
                            placement_search_mask = pd.Series(
                                False, index=candidate_placements.index
                            )
                            for col in part_search_cols:
                                if col in candidate_placements.columns:
                                    placement_search_mask |= (
                                        candidate_placements[col]
                                        .fillna("")
                                        .astype(str)
                                        .str.casefold()
                                        .str.contains(parts_search, regex=False)
                                    )
                            matching_placement_part_ids = set(
                                candidate_placements.loc[
                                    placement_search_mask, "part_id"
                                ].astype(str)
                            )
                            parts_search_mask |= (
                                available_parts["part_id"]
                                .astype(str)
                                .isin(matching_placement_part_ids)
                            )
                        available_parts = available_parts.loc[
                            parts_search_mask
                        ].copy()

                    if handled_filter == "Handled":
                        available_parts = available_parts.loc[
                            available_parts["part_id"].astype(str).isin(handled_part_ids)
                        ].copy()
                    elif handled_filter == "Not handled":
                        available_parts = available_parts.loc[
                            ~available_parts["part_id"].astype(str).isin(handled_part_ids)
                        ].copy()

                    if model_filter != "All models":
                        def _part_matches_model(app_val: object) -> bool:
                            app_str = str(app_val or "").strip()
                            if not app_str or app_str.casefold() in ("all", "all models"):
                                return True
                            part_models = [
                                model_labels.get(m.strip(), m.strip())
                                for m in split_filter_values(app_str)
                            ]
                            target_num = model_numbers_by_label.get(model_filter, model_filter)
                            return (
                                model_filter in part_models
                                or target_num in split_filter_values(app_str)
                            )

                        available_parts = available_parts.loc[
                            available_parts["model_applicability"].apply(_part_matches_model)
                        ].copy()

                if not available_parts.empty:
                    consumed_mask = available_parts["part_id"].astype(str).isin(consumed_part_ids)
                    not_consumed_parts = available_parts.loc[~consumed_mask].copy()
                    consumed_parts = available_parts.loc[consumed_mask].copy()
                else:
                    not_consumed_parts = available_parts.copy()
                    consumed_parts = available_parts.copy()

                selected_part_ids_key = (
                    f"process_selected_part_ids_{scenario_id}_{section_id}"
                )
                all_available_part_ids = (
                    set(all_available_parts["part_id"].astype(str).tolist())
                    if not all_available_parts.empty
                    and "part_id" in all_available_parts.columns
                    else set()
                )
                remembered_part_ids: list[str] = [
                    str(pid)
                    for pid in (st.session_state.get(selected_part_ids_key) or [])
                    if str(pid) in all_available_part_ids
                ]
                not_consumed_rows_changed = False
                consumed_rows_changed = False

                not_consumed_sig_key = (
                    f"process_not_consumed_parts_visible_rows_{scenario_id}_{section_id}"
                )
                current_not_consumed_ids = (
                    tuple(not_consumed_parts["part_id"].astype(str))
                    if not not_consumed_parts.empty
                    else ()
                )
                if (
                    not_consumed_sig_key in st.session_state
                    and st.session_state[not_consumed_sig_key] != current_not_consumed_ids
                ):
                    not_consumed_rows_changed = True
                    matching_not_consumed_rows = [
                        idx
                        for idx, pid in enumerate(current_not_consumed_ids)
                        if pid in remembered_part_ids
                    ]
                    _nc_sel_payload = {
                        "selection": {
                            "rows": matching_not_consumed_rows,
                            "columns": [],
                            "cells": [],
                        }
                    }
                    st.session_state[f"_saved_selectable_df_{not_consumed_part_source_key}"] = deepcopy(_nc_sel_payload)
                    st.session_state[not_consumed_part_source_key] = {
                        "selection": {
                            "rows": matching_not_consumed_rows,
                            "columns": [],
                            "cells": [],
                        }
                    }
                st.session_state[not_consumed_sig_key] = current_not_consumed_ids

                consumed_sig_key = (
                    f"process_consumed_parts_visible_rows_{scenario_id}_{section_id}"
                )
                current_consumed_ids = (
                    tuple(consumed_parts["part_id"].astype(str))
                    if not consumed_parts.empty
                    else ()
                )
                if (
                    consumed_sig_key in st.session_state
                    and st.session_state[consumed_sig_key] != current_consumed_ids
                ):
                    consumed_rows_changed = True
                    matching_consumed_rows = [
                        idx
                        for idx, pid in enumerate(current_consumed_ids)
                        if pid in remembered_part_ids
                    ]
                    _c_sel_payload = {
                        "selection": {
                            "rows": matching_consumed_rows,
                            "columns": [],
                            "cells": [],
                        }
                    }
                    st.session_state[f"_saved_selectable_df_{consumed_part_source_key}"] = deepcopy(_c_sel_payload)
                    st.session_state[consumed_part_source_key] = {
                        "selection": {
                            "rows": matching_consumed_rows,
                            "columns": [],
                            "cells": [],
                        }
                    }
                st.session_state[consumed_sig_key] = current_consumed_ids

                if show_nickname:
                    column_order = [
                        "part_number",
                        "factory_nickname",
                        "description",
                        "handling",
                        "fishbone_use_count",
                        "model_applicability",
                    ]
                else:
                    column_order = [
                        "part_number",
                        "description",
                        "handling",
                        "fishbone_use_count",
                        "model_applicability",
                    ]

                part_column_config = {
                    "part_number": st.column_config.TextColumn("Part number", pinned=True),
                    "factory_nickname": st.column_config.TextColumn(
                        "Factory Nickname",
                        help="Factory nickname / common shop floor name for the part",
                        width="medium",
                    ),
                    "description": st.column_config.TextColumn("Part Name", width="large"),
                    "handling": st.column_config.TextColumn(
                        "Handling",
                        help="Shows whether this part has been consumed, handled, or is unassigned in this scenario.",
                        width="small",
                    ),
                    "fishbone_use_count": st.column_config.NumberColumn(
                        "Fishbone uses", format="%d"
                    ),
                    "model_applicability": "Models",
                }

                has_active_part_filters = bool(
                    pairing_search
                    or parts_search
                    or handled_filter != "All"
                    or model_filter != "All models"
                )

                not_consumed_selection_expired = False
                consumed_selection_expired = False

                st.markdown("##### Not consumed parts")
                if not_consumed_parts.empty:
                    if not section_has_fishbone_parts:
                        st.info("No catalog parts are placed in this fishbone section.")
                    elif has_active_part_filters and section_has_available_fishbone_parts:
                        st.info("No not-consumed fishbone parts match these filters.")
                    else:
                        st.info("All fishbone parts in this section have been consumed.")
                    selected_not_consumed_parts = not_consumed_parts
                else:
                    not_consumed_event = selectable_dataframe(
                        not_consumed_parts,
                        key=not_consumed_part_source_key,
                        hide_index=True,
                        on_select="rerun",
                        selection_mode="multi-row",
                        column_order=column_order,
                        column_config=part_column_config,
                    )
                    not_consumed_rows = list(not_consumed_event.selection.rows)
                    valid_not_consumed_rows = [
                        row
                        for row in not_consumed_rows
                        if isinstance(row, int) and 0 <= row < len(not_consumed_parts)
                    ]
                    not_consumed_selection_expired = len(valid_not_consumed_rows) != len(
                        not_consumed_rows
                    )
                    selected_not_consumed_parts = not_consumed_parts.iloc[
                        [] if not_consumed_selection_expired else valid_not_consumed_rows
                    ]

                st.markdown("##### Consumed parts")
                if consumed_parts.empty:
                    if not section_has_fishbone_parts and not section_has_available_fishbone_parts:
                        st.info("No catalog parts are placed in this fishbone section.")
                    elif has_active_part_filters and section_has_available_fishbone_parts:
                        st.info("No consumed fishbone parts match these filters.")
                    else:
                        st.info("No fishbone parts in this section have been consumed yet.")
                    selected_consumed_parts = consumed_parts
                else:
                    consumed_event = selectable_dataframe(
                        consumed_parts,
                        key=consumed_part_source_key,
                        hide_index=True,
                        on_select="rerun",
                        selection_mode="multi-row",
                        column_order=column_order,
                        column_config=part_column_config,
                    )
                    consumed_rows = list(consumed_event.selection.rows)
                    if (
                        not consumed_rows
                        and not not_consumed_rows_changed
                        and not consumed_rows_changed
                        and not_consumed_parts.empty
                        and isinstance(
                            st.session_state.get(not_consumed_part_source_key), dict
                        )
                    ):
                        fallback_sel = st.session_state[
                            not_consumed_part_source_key
                        ].get("selection")
                        if isinstance(fallback_sel, dict):
                            consumed_rows = list(fallback_sel.get("rows") or [])
                    valid_consumed_rows = [
                        row
                        for row in consumed_rows
                        if isinstance(row, int) and 0 <= row < len(consumed_parts)
                    ]
                    consumed_selection_expired = len(valid_consumed_rows) != len(
                        consumed_rows
                    )
                    selected_consumed_parts = consumed_parts.iloc[
                        [] if consumed_selection_expired else valid_consumed_rows
                    ]

                part_selection_expired = (
                    not_consumed_selection_expired or consumed_selection_expired
                )
                if part_selection_expired:
                    remembered_part_ids = []
                    st.session_state.pop(selected_part_ids_key, None)
                    selected_parts = all_available_parts.iloc[[]]
                else:
                    selected_parts = pd.concat(
                        [selected_not_consumed_parts, selected_consumed_parts],
                        ignore_index=True,
                    )
                excluded_create_parts_key = (
                    f"process_create_excluded_parts_{scenario_id}_{section_id}"
                )
                if not part_selection_expired:
                    visible_part_ids_set = set(current_not_consumed_ids) | set(
                        current_consumed_ids
                    )
                    visible_selected_ids = (
                        selected_parts["part_id"].astype(str).tolist()
                        if not selected_parts.empty
                        and "part_id" in selected_parts.columns
                        else []
                    )
                    visible_selected_ids_set = set(visible_selected_ids)
                    updated_remembered_part_ids: list[str] = [
                        pid
                        for pid in remembered_part_ids
                        if pid not in visible_part_ids_set
                        or pid in visible_selected_ids_set
                    ]
                    for pid in visible_selected_ids:
                        if pid not in updated_remembered_part_ids:
                            updated_remembered_part_ids.append(pid)
                    remembered_part_ids = updated_remembered_part_ids
                    st.session_state[selected_part_ids_key] = remembered_part_ids
                    if remembered_part_ids and not all_available_parts.empty:
                        parts_by_id = {
                            str(row["part_id"]): row
                            for _, row in all_available_parts.iterrows()
                        }
                        ordered_rows = [
                            parts_by_id[pid]
                            for pid in remembered_part_ids
                            if pid in parts_by_id
                        ]
                        selected_parts = (
                            pd.DataFrame(
                                ordered_rows, columns=all_available_parts.columns
                            ).reset_index(drop=True)
                            if ordered_rows
                            else all_available_parts.iloc[[]]
                        )
                    else:
                        selected_parts = all_available_parts.iloc[[]]
                _unused_excluded_key = (None
                )
                raw_selected_part_ids = (
                    set(selected_parts["part_id"].astype(str).tolist())
                    if not selected_parts.empty and "part_id" in selected_parts.columns
                    else set()
                )
                excluded_create_part_ids = {
                    pid
                    for pid in st.session_state.get(excluded_create_parts_key, set())
                    if pid in raw_selected_part_ids
                }
                st.session_state[excluded_create_parts_key] = excluded_create_part_ids
                if excluded_create_part_ids and not selected_parts.empty:
                    selected_parts = selected_parts.loc[
                        ~selected_parts["part_id"].astype(str).isin(excluded_create_part_ids)
                    ].reset_index(drop=True)

            if work_selection_expired or part_selection_expired:
                request_table_editor_reset(work_source_key)
                request_table_editor_reset(not_consumed_part_source_key)
                request_table_editor_reset(consumed_part_source_key)
                if part_selection_expired:
                    st.warning(
                        "Your part selection changed and was cleared. Please reselect the parts for the PAAG Element."
                    )
                else:
                    st.warning(
                        "Your work-element selection changed and was cleared. Please reselect the work element."
                    )


            def close_missing_part_dialog() -> None:
                st.session_state.pop(missing_part_dialog_key, None)


            @st.dialog(
                "Find or add a fishbone part",
                width="large",
                dismissible=False,
                icon=":material/search:",
            )
            def missing_part_dialog(current_section_id: str) -> None:
                current_section_name = section_labels.get(current_section_id, current_section_id)
                st.caption(
                    f"Current fishbone section: {current_section_name}. Search the whole project before "
                    "creating a new catalog record."
                )
                find_tab, add_tab = st.tabs(["Find existing", "Add new part"])

                with find_tab:
                    search_text = st.text_input(
                        "Search by part number or name",
                        placeholder="Enter all or part of a part number or part name",
                        key=f"process_missing_part_search_{scenario_id}_{current_section_id}",
                    ).strip()
                    if len(search_text) < 2:
                        st.info("Enter at least two characters to search the Parts Catalog and all Fishbone sections.")
                    else:
                        matches = search_parts_and_fishbone(
                            project_id, search_text, scenario_id
                        )
                        if matches.empty:
                            st.warning("No similar catalog parts were found. Use Add new part if this is new.")
                        else:
                            summary_rows: list[dict] = []
                            for part_id, part_matches in matches.groupby("part_id", sort=False):
                                placed = part_matches.loc[part_matches["assignment_id"].notna()]
                                placements = []
                                for _, placement in placed.iterrows():
                                    use_text = str(placement.get("use_description") or "").strip()
                                    placement_text = (
                                        f"{placement.get('section_name') or 'Unknown section'} "
                                        f"(Fishbone quantity {format_clean_number(placement.get('quantity'))})"
                                    )
                                    if use_text:
                                        placement_text += f" — {use_text}"
                                    placements.append(placement_text)
                                first = part_matches.iloc[0]
                                summary_rows.append(
                                    {
                                        "part_id": str(part_id),
                                        "part_number": str(first.get("part_number") or ""),
                                        "description": str(first.get("description") or ""),
                                        "revision": str(first.get("revision") or ""),
                                        "fishbone_locations": " | ".join(placements) or "Not placed",
                                    }
                                )
                            result_summary = pd.DataFrame(summary_rows)
                            selectable_dataframe(
                                result_summary.drop(columns=["part_id"]),
                                key=f"process_existing_part_matches_{scenario_id}_{current_section_id}",
                                hide_index=True,
                                column_config={
                                    "part_number": st.column_config.TextColumn("Part number", pinned=True),
                                    "description": st.column_config.TextColumn("Part Name", width="large"),
                                    "revision": "Revision",
                                    "fishbone_locations": st.column_config.TextColumn(
                                        "Fishbone locations", width="large"
                                    ),
                                },
                            )
                            labels_by_part = {
                                row["part_id"]: f"{row['part_number']} — {row['description']}"
                                for row in summary_rows
                            }
                            selected_part_id = st.selectbox(
                                "Part to review or place",
                                list(labels_by_part),
                                format_func=lambda value: labels_by_part.get(value, value),
                                key=f"process_missing_part_match_{scenario_id}_{current_section_id}",
                            )
                            selected_matches = matches.loc[
                                matches["part_id"].astype(str) == str(selected_part_id)
                            ].copy()
                            placements = selected_matches.loc[selected_matches["assignment_id"].notna()].copy()
                            current_placements = placements.loc[
                                placements["section_id"].astype(str) == str(current_section_id)
                            ]
                            other_placements = placements.loc[
                                placements["section_id"].astype(str) != str(current_section_id)
                            ]
                            if not current_placements.empty:
                                st.success("This part is already available in the current fishbone section.")
                                action_options = ["Add another use"]
                            elif not other_placements.empty:
                                st.warning(
                                    "This part is placed in another fishbone section. Move that occurrence "
                                    "if it was misplaced, or add another use if both placements are intentional."
                                )
                                action_options = ["Move an existing use", "Add another use"]
                            else:
                                st.info("This catalog part has not been placed on the fishbone yet.")
                                action_options = ["Place in selected section"]

                            placement_action = st.segmented_control(
                                "Action",
                                action_options,
                                default=action_options[0],
                                key=f"process_missing_part_action_{scenario_id}_{current_section_id}",
                            )
                            target_section_id = st.selectbox(
                                "Use / installation location",
                                section_ids,
                                index=section_ids.index(current_section_id),
                                format_func=lambda value: section_labels.get(value, value),
                                key=f"process_missing_part_target_section_{scenario_id}_{current_section_id}",
                            )
                            selected_assignment_id = None
                            if placement_action == "Move an existing use":
                                section_position = {
                                    section_id: index
                                    for index, section_id in enumerate(section_ids)
                                }
                                other_placements = (
                                    other_placements.assign(
                                        _section_position=other_placements["section_id"]
                                        .astype(str)
                                        .map(section_position)
                                        .fillna(len(section_position))
                                    )
                                    .sort_values(
                                        ["_section_position", "assignment_id"],
                                        kind="stable",
                                    )
                                    .drop(columns=["_section_position"])
                                )
                                assignment_labels = {
                                    str(row["assignment_id"]): (
                                        f"{section_labels.get(str(row.get('section_id')), row.get('section_name') or 'Unknown section')} "
                                        "— "
                                        f"Fishbone quantity {format_clean_number(row.get('quantity'))} — "
                                        f"{row.get('use_description') or 'No use description'}"
                                    )
                                    for _, row in other_placements.iterrows()
                                }
                                selected_assignment_id = st.selectbox(
                                    "Fishbone use to move",
                                    list(assignment_labels),
                                    format_func=lambda value: assignment_labels.get(value, value),
                                    key=f"process_missing_part_assignment_{scenario_id}_{current_section_id}",
                                )
                            else:
                                placement_row = st.container(horizontal=True, vertical_alignment="bottom")
                                placement_quantity = placement_row.number_input(
                                    "Fishbone quantity",
                                    value=1.0,
                                    step=0.01,
                                    format="%g",
                                    key=f"process_missing_part_quantity_{scenario_id}_{current_section_id}",
                                )

                            if st.button(
                                placement_action,
                                type="primary",
                                icon=":material/account_tree:",
                                key=f"process_missing_part_apply_{scenario_id}_{current_section_id}",
                            ):
                                try:
                                    if placement_action == "Move an existing use":
                                        updated_at = move_fishbone_part_assignment(
                                            project_id, str(selected_assignment_id), target_section_id
                                        )
                                        audit_action = "Move part use"
                                    else:
                                        count = assign_parts_to_section(
                                            project_id,
                                            [str(selected_part_id)],
                                            target_section_id,
                                            "",
                                            allow_additional_use=not placements.empty,
                                            quantities_by_part={
                                                str(selected_part_id): float(placement_quantity)
                                            },
                                        )
                                        if count != 1:
                                            raise ValueError("The part could not be placed in this section.")
                                        updated_at = None
                                        audit_action = "Place part"
                                    record_audit_event(
                                        project_id,
                                        "Fishbone part assignments",
                                        audit_action,
                                        1,
                                        st.session_state.get("current_editor", ""),
                                        {
                                            "part_id": str(selected_part_id),
                                            "section_id": target_section_id,
                                            "updated_at": updated_at,
                                        },
                                    )
                                    close_missing_part_dialog()
                                    st.toast(
                                        f"{labels_by_part[str(selected_part_id)]} is now in "
                                        f"{section_labels.get(target_section_id, target_section_id)}",
                                        icon=":material/check_circle:",
                                    )
                                    st.rerun()
                                except ValueError as exc:
                                    st.error(str(exc))

                with add_tab:
                    st.caption(
                        "This creates a project Parts Catalog record and its first Fishbone use together. "
                        "Images and advanced applicability can be added later in the Parts Catalog."
                    )
                    new_part_number = st.text_input(
                        "Part number",
                        key=f"process_new_part_number_{scenario_id}_{current_section_id}",
                    )
                    new_description = st.text_input(
                        "Part Name",
                        key=f"process_new_part_description_{scenario_id}_{current_section_id}",
                    )
                    new_revision = st.text_input(
                        "Revision",
                        value="0",
                        key=f"process_new_part_revision_{scenario_id}_{current_section_id}",
                    )
                    new_placement = st.container(horizontal=True, vertical_alignment="bottom")
                    new_quantity = new_placement.number_input(
                        "Fishbone quantity",
                        value=1.0,
                        step=0.01,
                        format="%g",
                        key=f"process_new_part_quantity_{scenario_id}_{current_section_id}",
                    )
                    new_target_section_id = new_placement.selectbox(
                        "Use / installation location",
                        section_ids,
                        index=section_ids.index(current_section_id),
                        format_func=lambda value: section_labels.get(value, value),
                        key=f"process_new_part_target_section_{scenario_id}_{current_section_id}",
                    )
                    new_notes = st.text_area(
                        "Part notes",
                        key=f"process_new_part_notes_{scenario_id}_{current_section_id}",
                    )

                    suggestion_text = new_part_number.strip() or new_description.strip()
                    if len(suggestion_text) >= 2:
                        suggestions = search_parts_and_fishbone(project_id, suggestion_text)
                        if not suggestions.empty:
                            suggestion_summary = suggestions[
                                ["part_id", "part_number", "description", "revision", "section_name"]
                            ].drop_duplicates()
                            st.warning("Possible existing matches were found. Review them before creating a duplicate.")
                            selectable_dataframe(
                                suggestion_summary.drop(columns=["part_id"]),
                                key=f"process_new_part_matches_{scenario_id}_{current_section_id}",
                                hide_index=True,
                                column_config={
                                    "part_number": "Part number",
                                    "description": st.column_config.TextColumn("Part Name", width="large"),
                                    "revision": "Revision",
                                    "section_name": "Fishbone section",
                                },
                            )

                    if st.button(
                        "Add part and place it",
                        type="primary",
                        icon=":material/add_circle:",
                        key=f"process_create_missing_part_{scenario_id}_{current_section_id}",
                    ):
                        try:
                            part_id, assignment_id, updated_at = create_part_and_assign_to_section(
                                project_id,
                                new_target_section_id,
                                {
                                    "part_number": new_part_number,
                                    "description": new_description,
                                    "revision": new_revision,
                                    "model_applicability": "All",
                                    "notes": new_notes,
                                },
                                float(new_quantity),
                                "",
                            )
                            editor_name = st.session_state.get("current_editor", "")
                            record_audit_event(
                                project_id,
                                "Parts",
                                "Create from Process at a Glance",
                                1,
                                editor_name,
                                {"part_id": part_id, "updated_at": updated_at},
                            )
                            record_audit_event(
                                project_id,
                                "Fishbone part assignments",
                                "Place new part",
                                1,
                                editor_name,
                                {
                                    "part_id": part_id,
                                    "assignment_id": assignment_id,
                                    "section_id": new_target_section_id,
                                    "updated_at": updated_at,
                                },
                            )
                            close_missing_part_dialog()
                            st.toast(
                                f"Added {new_part_number.strip()} to Parts and "
                                f"{section_labels.get(new_target_section_id, new_target_section_id)}",
                                icon=":material/check_circle:",
                            )
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))

                if st.button(
                    "Cancel",
                    icon=":material/close:",
                    key=f"process_missing_part_cancel_{scenario_id}_{current_section_id}",
                ):
                    close_missing_part_dialog()
                    st.rerun()


            if st.session_state.get(missing_part_dialog_key):
                missing_part_dialog(section_id)

            selected_yamazumi_id = (
                str(selected_yamazumi.iloc[0]["id"]) if len(selected_yamazumi) == 1 else None
            )
            selected_pitch_id = (
                str(selected_yamazumi.iloc[0]["pitch_id"])
                if len(selected_yamazumi) == 1
                and "pitch_id" in selected_yamazumi.columns
                and pd.notna(selected_yamazumi.iloc[0]["pitch_id"])
                else None
            )
            selected_process_id = (
                process_element_id_for_yamazumi(project_id, scenario_id, selected_yamazumi_id)
                if selected_yamazumi_id else None
            )

            if selected_yamazumi_id:
                selected_description = str(selected_yamazumi.iloc[0]["description"])
                pair_controls = st.container(border=True)
                pair_controls.markdown(f"**Selected work:** {selected_description}")
                pairing_rule_key = (
                    f"process_pairing_rule_{scenario_id}_{section_id}_"
                    f"{selected_yamazumi_id}"
                )
                if st.session_state.get(pairing_rule_key) == "Choose one":
                    st.session_state[pairing_rule_key] = "Model choice"
                selection_rule = pair_controls.selectbox(
                    "Selection rule",
                    ["Use all", "Model choice", "Optional"],
                    key=pairing_rule_key,
                )
                handling_types_by_part: dict[str, str] = {}
                fishbone_assignment_ids_by_part: dict[str, str | None] = {}
                quantities_by_part: dict[str, float | None] = {}
                model_variants_by_part: dict[str, bool] = {}
                selected_pairing_details: list[dict] = []
                if not selected_parts.empty:
                    pair_controls.markdown("##### Classify selected parts")
                    pair_controls.caption(
                        "Each selected part needs a handling type (and a "
                        "Use / installation location when Consumed) before it can be paired."
                    )
                    _pfr_df = part_feature_rules(project_id)
                    feature_rule_pids = (
                        set(_pfr_df["part_id"].astype(str))
                        if not _pfr_df.empty and "part_id" in _pfr_df.columns
                        else set()
                    )
                    for _, selected_part in selected_parts.iterrows():
                        selected_part_id = str(selected_part["part_id"])
                        selected_part_number = str(selected_part["part_number"])
                        raw_part_name = selected_part.get("description")
                        selected_part_name = (
                            "" if pd.isna(raw_part_name) else str(raw_part_name or "")
                        )
                        placement_options = process_part_placement_options(
                            project_id,
                            scenario_id,
                            section_id,
                            selected_part_id,
                            work_element_id=selected_process_id,
                            yamazumi_element_id=selected_yamazumi_id,
                        )
                        in_current_section = (
                            not section_placements.empty
                            and selected_part_id
                            in set(section_placements["part_id"].astype(str))
                        )
                        has_consumable_placement = (
                            not placement_options.empty
                            and "can_consume" in placement_options.columns
                            and bool(placement_options["can_consume"].any())
                        )
                        default_handling_idx = (
                            0 if (in_current_section and has_consumable_placement) else 1
                        )
                        with pair_controls.container(border=True):
                            st.markdown(
                                f"**{selected_part_number}**"
                                + (f" — {selected_part_name}" if selected_part_name else "")
                            )
                            mv_key = (
                                f"process_pairing_model_variant_{scenario_id}_{section_id}_"
                                f"{selected_yamazumi_id}_{selected_part_id}"
                            )
                            if selection_rule == "Model choice":
                                default_is_mv = _part_has_model_variants(
                                    selected_part_id,
                                    all_placements,
                                    fallback_model_applicability=selected_part.get(
                                        "model_applicability"
                                    ),
                                    feature_rule_part_ids=feature_rule_pids,
                                )
                                is_model_variant = st.checkbox(
                                    "Model variant",
                                    value=default_is_mv,
                                    help=(
                                        "Check if this part is one of the model-choice alternatives "
                                        "the operator chooses between on this step."
                                    ),
                                    key=mv_key,
                                )
                                model_variants_by_part[selected_part_id] = bool(
                                    is_model_variant
                                )
                            else:
                                _pop_paag_tab_state(mv_key, None)
                                model_variants_by_part[selected_part_id] = False
                            ht_col, qty_col = st.columns([2, 1])
                            handling_type = ht_col.selectbox(
                                "Handling type",
                                ["Consume", "Handle"],
                                index=default_handling_idx,
                                help=(
                                    "Consume means one unit is removed from its container and placed "
                                    "on the line for the first time. Handle means that same Fishbone "
                                    "use is manipulated again after at least one unit has been consumed."
                                ),
                                key=(
                                    f"process_pairing_handling_{scenario_id}_{section_id}_"
                                    f"{selected_yamazumi_id}_{selected_part_id}"
                                ),
                            )
                            part_quantity = qty_col.number_input(
                                "Quantity",
                                min_value=0.01,
                                value=1.0,
                                step=1.0,
                                disabled=(handling_type != "Consume"),
                                help=(
                                    "Enter the quantity of parts consumed."
                                    if handling_type == "Consume"
                                    else "Quantity is only available when Handling type is Consume."
                                ),
                                key=(
                                    f"process_pairing_quantity_{scenario_id}_{section_id}_"
                                    f"{selected_yamazumi_id}_{selected_part_id}"
                                ),
                            )
                            handling_types_by_part[selected_part_id] = handling_type
                            quantities_by_part[selected_part_id] = (
                                float(part_quantity) if handling_type == "Consume" else None
                            )
                            placement_labels: dict[str, str] = {}
                            disabled_placement_ids: set[str] = set()
                            for _, placement in placement_options.iterrows():
                                assignment_id = str(placement["fishbone_assignment_id"])
                                raw_use_description = placement.get("use_description")
                                use_description = (
                                    "No location recorded"
                                    if pd.isna(raw_use_description)
                                    or not str(raw_use_description or "").strip()
                                    else str(raw_use_description).strip()
                                )
                                placement_sec_id = str(placement.get("section_id") or "")
                                placement_sec_name = str(
                                    placement.get("section_name") or ""
                                ).strip()
                                if (
                                    placement_sec_id
                                    and placement_sec_id != str(section_id)
                                    and placement_sec_name
                                ):
                                    use_description = (
                                        f"{placement_sec_name} ({use_description})"
                                    )
                                quantity_label = format_clean_number(
                                    placement["fishbone_quantity"]
                                )
                                remaining_label = format_clean_number(
                                    placement["remaining_consume_allowance"]
                                )
                                if handling_type == "Consume":
                                    can_consume_placement = bool(placement["can_consume"])
                                    availability = (
                                        f"Remaining Consume allowance {remaining_label}"
                                        if can_consume_placement
                                        else "Unavailable for Consume — allowance fully used"
                                    )
                                    if not can_consume_placement:
                                        disabled_placement_ids.add(assignment_id)
                                else:
                                    availability = (
                                        "Available for Handle"
                                        if bool(placement["can_handle"])
                                        else "Unavailable for Handle — Consume first"
                                    )
                                placement_labels[assignment_id] = (
                                    f"{use_description} · Fishbone quantity {quantity_label} · "
                                    f"{availability}"
                                )
                            placement_ids = list(placement_labels)
                            placement_key = (
                                f"process_pairing_location_{scenario_id}_{section_id}_"
                                f"{selected_yamazumi_id}_{selected_part_id}"
                            )
                            handle_auto_key = f"{placement_key}__handle_auto"
                            if handling_type != "Consume":
                                auto_handle_id = next(
                                    (
                                        str(r["fishbone_assignment_id"])
                                        for _, r in placement_options.iterrows()
                                        if bool(r.get("can_handle"))
                                    ),
                                    placement_ids[0] if placement_ids else None,
                                )
                                st.session_state[handle_auto_key] = True
                                if (
                                    auto_handle_id is not None
                                    and st.session_state.get(placement_key)
                                    != auto_handle_id
                                ):
                                    st.session_state[placement_key] = auto_handle_id
                                st.selectbox(
                                    "Use / installation location",
                                    placement_ids,
                                    format_func=lambda value, labels=placement_labels: labels.get(
                                        value, value
                                    ),
                                    disabled=True,
                                    help=(
                                        "Use / installation location is only needed when "
                                        "Handling type is Consume."
                                    ),
                                    key=placement_key,
                                )
                                selected_assignment_id = auto_handle_id
                            else:
                                if (
                                    st.session_state.pop(handle_auto_key, False)
                                    and len(placement_ids) > 1
                                ):
                                    st.session_state[placement_key] = None
                                if (
                                    placement_key in st.session_state
                                    and str(st.session_state.get(placement_key) or "")
                                    in disabled_placement_ids
                                ):
                                    st.session_state[placement_key] = None
                                if (
                                    len(placement_ids) == 1
                                    and placement_ids[0] not in disabled_placement_ids
                                ):
                                    if (
                                        st.session_state.get(placement_key)
                                        != placement_ids[0]
                                    ):
                                        st.session_state[placement_key] = (
                                            placement_ids[0]
                                        )
                                    selected_assignment_id = st.selectbox(
                                        "Use / installation location",
                                        placement_ids,
                                        format_func=lambda value, labels=placement_labels: labels.get(
                                            value, value
                                        ),
                                        disabled=True,
                                        help=(
                                            "This part has one Fishbone use in the selected section, so "
                                            "it is selected automatically."
                                        ),
                                        key=placement_key,
                                    )
                                else:
                                    selected_assignment_id = st.selectbox(
                                        "Use / installation location",
                                        placement_ids,
                                        index=None,
                                        placeholder="Choose a Use / installation location",
                                        format_func=lambda value, labels=placement_labels: labels.get(
                                            value, value
                                        ),
                                        help=(
                                            "Choose the exact Fishbone use represented by this Process "
                                            "part pairing."
                                        ),
                                        key=placement_key,
                                    )
                                if (
                                    selected_assignment_id
                                    and str(selected_assignment_id)
                                    in disabled_placement_ids
                                ):
                                    selected_assignment_id = None
                            _inject_disabled_consumed_placement_options_script()
                            fishbone_assignment_ids_by_part[selected_part_id] = (
                                str(selected_assignment_id) if selected_assignment_id else None
                            )
                            selected_pairing_details.append(
                                {
                                    "part_id": selected_part_id,
                                    "part_number": selected_part_number,
                                    "handling_type": handling_type,
                                    "quantity": quantities_by_part.get(selected_part_id),
                                    "is_model_variant": model_variants_by_part.get(
                                        selected_part_id, False
                                    ),
                                    "fishbone_assignment_id": (
                                        str(selected_assignment_id)
                                        if selected_assignment_id
                                        else None
                                    ),
                                }
                            )
                            if st.button(
                                "Unlink this part from the PAAG element",
                                icon=":material/link_off:",
                                key=(
                                    f"destructive_create_unlink_part_{scenario_id}_{section_id}_"
                                    f"{selected_yamazumi_id}_{selected_part_id}"
                                ),
                            ):
                                if len(selected_parts) <= 1:
                                    st.session_state.pop(excluded_create_parts_key, None)

                                    st.session_state.pop(selected_part_ids_key, [])
                                    request_table_editor_reset(not_consumed_part_source_key)
                                    request_table_editor_reset(consumed_part_source_key)
                                else:
                                    current_excluded = set(
                                        st.session_state.get(excluded_create_parts_key, set())
                                    )
                                    current_excluded.add(selected_part_id)
                                    remaining_part_ids = [
                                        pid
                                        for pid in (
                                            st.session_state.get(selected_part_ids_key)
                                            or []
                                        )
                                        if str(pid) != str(selected_part_id)
                                    ]
                                    st.session_state[selected_part_ids_key] = (
                                        remaining_part_ids
                                    )
                                    st.session_state[not_consumed_sig_key] = ("__force_sync__",)
                                    _unused_unlink_nc = {
                                        "selection": {
                                            "rows": [
                                                idx
                                                for idx, pid in enumerate(
                                                    current_not_consumed_ids
                                                )
                                                if pid in remaining_part_ids
                                            ],
                                            "columns": [],
                                            "cells": [],
                                        }
                                    }
                                    st.session_state[consumed_sig_key] = ("__force_sync__",)
                                    _unused_unlink_c = {
                                        "selection": {
                                            "rows": [
                                                idx
                                                for idx, pid in enumerate(
                                                    current_consumed_ids
                                                )
                                                if pid in remaining_part_ids
                                            ],
                                            "columns": [],
                                            "cells": [],
                                        }
                                    }
                                    st.session_state[excluded_create_parts_key] = current_excluded
                                st.rerun()
                pair_controls.markdown("##### PAAG Element Configuration")
                tool_res_container = pair_controls.container()
                tool_c1, tool_c2 = tool_res_container.columns(2)

                # Available equipment types for tool category dropdown
                all_types_df = equipment_types(project_id)
                type_labels = [
                    str(lbl).strip()
                    for lbl in all_types_df["label"].dropna().unique()
                    if str(lbl).strip()
                ]
                for std_tool in [
                    "Handheld equipment", "Torque tool", "Scan/Compare equipment",
                    "Poka-Yoke / Fixture equipment", "Test equipment", "Tape machine",
                    "Platform", "Pit", "Operator Lift", "Ergo Hand Tools", "Ergo Lift Assists",
                ]:
                    if std_tool not in type_labels:
                        type_labels.append(std_tool)
                type_labels.sort()
                tool_categories = ["(No tool required)", *type_labels, "Other tool"]

                # Query existing work element values if already linked
                existing_tool = ""
                existing_res_type = "Human"
                existing_res_detail = ""
                if selected_process_id:
                    try:
                        existing_we_df = project_table("work_elements", project_id, scenario_id=scenario_id)
                        existing_match = existing_we_df[existing_we_df["id"].astype(str) == str(selected_process_id)]
                        if not existing_match.empty:
                            existing_tool = str(existing_match.iloc[0].get("tool") or "").strip()
                            existing_res_type = str(existing_match.iloc[0].get("resource_type") or "Human").strip()
                            existing_res_detail = str(existing_match.iloc[0].get("resource_detail") or "").strip()
                    except Exception:
                        pass

                all_assets_df = equipment_assets(project_id, scenario_id)
                default_cat_idx = 0
                if existing_tool:
                    matched_cat = False
                    for idx, cat in enumerate(tool_categories):
                        if cat.casefold() == existing_tool.casefold():
                            default_cat_idx = idx
                            matched_cat = True
                            break
                    if not matched_cat and not all_assets_df.empty:
                        for _, a_row in all_assets_df.iterrows():
                            a_name = str(a_row.get("name") or "").strip()
                            a_model = str(a_row.get("model") or "").strip()
                            a_label = f"{a_name} ({a_model})" if a_model else a_name
                            if existing_tool.casefold() in {a_name.casefold(), a_label.casefold()}:
                                eq_cat = str(a_row.get("equipment_type") or "").strip()
                                for idx, cat in enumerate(tool_categories):
                                    if cat.casefold() == eq_cat.casefold():
                                        default_cat_idx = idx
                                        matched_cat = True
                                        break
                                if matched_cat:
                                    break
                    if not matched_cat:
                        tool_categories.append(existing_tool)
                        default_cat_idx = len(tool_categories) - 1

                selected_tool_category = tool_c1.selectbox(
                    "Tool category",
                    tool_categories,
                    index=default_cat_idx,
                    key=f"process_tool_cat_{scenario_id}_{section_id}_{selected_yamazumi_id}",
                    help="Select tool category from the handheld equipment catalog, or '(No tool required)'."
                )

                final_tool = ""
                selected_equipment_id = None
                if selected_tool_category != "(No tool required)":
                    cat_assets = pd.DataFrame()
                    if not all_assets_df.empty and "equipment_type" in all_assets_df.columns:
                        cat_assets = all_assets_df[
                            all_assets_df["equipment_type"].astype(str).str.casefold() == selected_tool_category.casefold()
                        ]
                
                    asset_choices = ["(Standard / Unspecified)"]
                    asset_id_map = {}
                    for _, a_row in cat_assets.iterrows():
                        a_name = str(a_row.get("name") or "").strip()
                        if a_name:
                            a_label = f"{a_name} ({str(a_row.get('model')).strip()})" if str(a_row.get("model") or "").strip() else a_name
                            asset_choices.append(a_label)
                            asset_id_map[a_label] = (str(a_row["id"]), a_name)
                
                    default_asset_idx = 0
                    if existing_tool and existing_tool.casefold() != selected_tool_category.casefold():
                        for idx, ch in enumerate(asset_choices):
                            if existing_tool.casefold() in ch.casefold():
                                default_asset_idx = idx
                                break

                    selected_asset_choice = tool_c2.selectbox(
                        "Specific handheld tool / equipment",
                        asset_choices,
                        index=default_asset_idx,
                        key=f"process_tool_specific_{scenario_id}_{section_id}_{selected_yamazumi_id}",
                        help="Choose a specific cataloged equipment asset or standard."
                    )
                    if selected_asset_choice != "(Standard / Unspecified)":
                        eq_info = asset_id_map.get(selected_asset_choice)
                        if eq_info:
                            selected_equipment_id = eq_info[0]
                            final_tool = eq_info[1]
                        else:
                            final_tool = selected_asset_choice
                    else:
                        final_tool = selected_tool_category
                else:
                    tool_c2.caption("No tool will be assigned to this PAAG element.")

                res_c1, res_c2 = tool_res_container.columns(2)
                default_res_type_idx = 1 if existing_res_type.casefold() == "autonomous equipment" else 0
                resource_type = res_c1.selectbox(
                    "Resource performing work",
                    ["Human", "Autonomous equipment"],
                    index=default_res_type_idx,
                    key=f"process_res_type_{scenario_id}_{section_id}_{selected_yamazumi_id}",
                    help="Select whether this operation is performed by a human operator or autonomous equipment."
                )
                resource_detail = ""
                if resource_type == "Autonomous equipment":
                    auto_options = ["Robot", "AMR", "Quality checker"]
                    default_detail_idx = 0
                    if existing_res_detail in auto_options:
                        default_detail_idx = auto_options.index(existing_res_detail)
                    resource_detail = res_c2.selectbox(
                        "Autonomous resource type",
                        auto_options,
                        index=default_detail_idx,
                        key=f"process_res_detail_{scenario_id}_{section_id}_{selected_yamazumi_id}",
                        help="Select the specific autonomous equipment performing the work."
                    )
                else:
                    res_c2.caption("Standard manual operator performing work.")

                if (
                    str(final_tool or "").strip() != str(existing_tool or "").strip()
                    or str(resource_type or "Human").strip() != str(existing_res_type or "Human").strip()
                    or str(resource_detail or "").strip() != str(existing_res_detail or "").strip()
                ):
                    if False and not selected_process_id and selected_yamazumi_id:
                        if selection_rule in {"Model choice", "Choose one"} and not any(
                            model_variants_by_part.get(pid, False)
                            for pid in selected_parts["part_id"].astype(str).tolist()
                        ):
                            raise ValueError(
                                "Check 'Model variant' on at least one part when Selection rule is Model choice."
                            )
                        reconcile_yamazumi_to_process(
                            project_id, scenario_id, [selected_yamazumi_id]
                        )
                        selected_process_id = process_element_id_for_yamazumi(
                            project_id, scenario_id, selected_yamazumi_id
                        )
                    if selected_process_id:
                        update_work_element_tool_and_resource(
                            project_id,
                            scenario_id,
                            selected_process_id,
                            tool=final_tool,
                            resource_type=resource_type,
                            resource_detail=resource_detail,
                        )
                        if selected_equipment_id and selected_pitch_id:
                            try:
                                save_equipment_placement(
                                    project_id=project_id,
                                    scenario_id=scenario_id,
                                    equipment_id=selected_equipment_id,
                                    pitch_id=str(selected_pitch_id),
                                    work_element_ids=[selected_process_id],
                                    editor_name=st.session_state.get("current_editor", ""),
                                )
                            except Exception:
                                pass

                is_handle_operation = any(
                    ht == "Handle" for ht in handling_types_by_part.values()
                )

                part_labels = []
                variant_part_labels = []
                non_variant_part_labels = []
                if not selected_parts.empty:
                    for _, r in selected_parts.iterrows():
                        r_pid = str(r.get("part_id") or "")
                        p_desc = (
                            ""
                            if pd.isna(r.get("description"))
                            else str(r.get("description") or "").strip()
                        )
                        p_num = (
                            ""
                            if pd.isna(r.get("part_number"))
                            else str(r.get("part_number") or "").strip()
                        )
                        lbl = p_desc or p_num
                        if lbl:
                            part_labels.append(lbl)
                            if model_variants_by_part.get(r_pid, False):
                                variant_part_labels.append(lbl)
                            else:
                                non_variant_part_labels.append(lbl)

                if selection_rule in {"Model choice", "Choose one"}:
                    if variant_part_labels and non_variant_part_labels:
                        auto_name = (
                            f"{' / '.join(variant_part_labels)}, "
                            f"{', '.join(non_variant_part_labels)}"
                        )
                    elif variant_part_labels:
                        auto_name = " / ".join(variant_part_labels)
                    else:
                        auto_name = (
                            " / ".join(part_labels)
                            if part_labels
                            else (selected_description or "Part option")
                        )
                elif selection_rule == "Optional":
                    auto_name = (
                        f"Optional: {', '.join(part_labels)}"
                        if part_labels
                        else (selected_description or "Optional part")
                    )
                else:
                    auto_name = (
                        ", ".join(part_labels)
                        if part_labels
                        else (selected_description or "Part requirement")
                    )

                if len(auto_name) > 80 and part_labels:
                    auto_name = f"{part_labels[0]} (+{len(part_labels)-1} parts)"

                with pair_controls.form(
                    f"pair_parts_{scenario_id}_{section_id}_{selected_yamazumi_id}", border=False
                ):
                    form_row = st.container(horizontal=True, vertical_alignment="bottom")
                    automatic_requirement_name = (
                        len(selected_parts) == 1
                        and selection_rule == "Use all"
                        and not is_handle_operation
                    )
                    if automatic_requirement_name:
                        group_name = auto_name
                        form_row.markdown(f"**Part requirement**  \n{group_name}")
                    else:
                        group_name = form_row.text_input(
                            "Part requirement"
                            if not is_handle_operation
                            else "Part requirement *",
                            value=auto_name if not is_handle_operation else "",
                            placeholder=(
                                "Example: Control panel color"
                                if not is_handle_operation
                                else "Describe the handling requirement"
                            ),
                            help=(
                                "Named automatically from selected parts. You can edit this requirement name if needed."
                                if not is_handle_operation
                                else "Name the requirement for this handle operation."
                            ),
                            key=(
                                f"process_pairing_requirement_{scenario_id}_{section_id}_"
                                f"{selected_yamazumi_id}"
                            ),
                        )
                    notes = st.text_input(
                        "Part requirement notes",
                        placeholder="Model choice, installation intent, or other IE guidance",
                        key=(
                            f"process_pairing_notes_{scenario_id}_{section_id}_"
                            f"{selected_yamazumi_id}"
                        ),
                    )
                    pair_parts = st.form_submit_button(
                        f"Create PAAG Elements ({len(selected_parts)} parts)"
                        if not selected_parts.empty
                        else "Create PAAG Elements",
                        type="primary",
                        icon=":material/link:",
                        disabled=selected_parts.empty,
                        key=(
                            f"process_pairing_submit_{scenario_id}_{section_id}_"
                            f"{selected_yamazumi_id}"
                        ),
                    )
                add_without_parts = st.button(
                    "Add selected work to Process at a Glance without parts",
                    icon=":material/playlist_add:",
                    key=f"add_work_only_{scenario_id}_{selected_yamazumi_id}",
                )
                if pair_parts:
                    try:
                        final_group_name = str(group_name or "").strip()
                        if not final_group_name:
                            if is_handle_operation:
                                raise ValueError(
                                    "Part requirement name is required for handle operations."
                                )
                            final_group_name = auto_name
                        if selected_parts.empty:
                            raise ValueError("Select at least one fishbone part.")
                        missing_locations = [
                            detail["part_number"]
                            for detail in selected_pairing_details
                            if detail.get("handling_type") == "Consume"
                            and not detail["fishbone_assignment_id"]
                        ]
                        if missing_locations:
                            raise ValueError(
                                "Choose a Use / installation location for: "
                                + ", ".join(missing_locations)
                                + "."
                            )
                        validate_process_part_option_pairings(
                            project_id,
                            scenario_id,
                            section_id,
                            selected_pairing_details,
                            work_element_id=selected_process_id,
                            yamazumi_element_id=selected_yamazumi_id,
                        )
                        if selection_rule in {"Model choice", "Choose one"} and not any(
                            model_variants_by_part.get(pid, False)
                            for pid in selected_parts["part_id"].astype(str).tolist()
                        ):
                            raise ValueError(
                                "Check 'Model variant' on at least one part when Selection rule is Model choice."
                            )
                        reconcile_yamazumi_to_process(
                            project_id, scenario_id, [selected_yamazumi_id]
                        )
                        selected_process_id = process_element_id_for_yamazumi(
                            project_id, scenario_id, selected_yamazumi_id
                        )
                        if not selected_process_id:
                            raise ValueError(
                                "The work element could not be added to Process at a Glance."
                            )
                        update_work_element_tool_and_resource(
                            project_id,
                            scenario_id,
                            selected_process_id,
                            tool=final_tool,
                            resource_type=resource_type,
                            resource_detail=resource_detail,
                        )
                        if selected_equipment_id and selected_pitch_id:
                            try:
                                save_equipment_placement(
                                    project_id=project_id,
                                    scenario_id=scenario_id,
                                    equipment_id=selected_equipment_id,
                                    pitch_id=str(selected_pitch_id),
                                    work_element_ids=[selected_process_id],
                                    editor_name=st.session_state.get("current_editor", ""),
                                )
                            except Exception:
                                pass

                        # Ensure unique requirement name on this work element
                        existing_groups = process_part_groups(
                            project_id, scenario_id, selected_process_id, active_only=True
                        )
                        existing_names = {
                            str(g.get("name") or "").strip().casefold()
                            for g in existing_groups
                        }
                        base_candidate = final_group_name
                        counter = 2
                        while final_group_name.casefold() in existing_names:
                            final_group_name = f"{base_candidate} ({counter})"
                            counter += 1

                        consumed_quantities = [
                            float(q)
                            for q in quantities_by_part.values()
                            if q is not None and float(q) > 0
                        ]
                        group_quantity = (
                            consumed_quantities[0] if consumed_quantities else 1.0
                        )
                        save_process_part_group(
                            project_id,
                            scenario_id,
                            selected_process_id,
                            section_id,
                            None,
                            final_group_name,
                            selection_rule,
                            group_quantity,
                            selected_parts["part_id"].astype(str).tolist(),
                            notes,
                            handling_types_by_part=handling_types_by_part,
                            fishbone_assignment_ids_by_part=(
                                fishbone_assignment_ids_by_part
                            ),
                            quantities_by_part=quantities_by_part,
                            model_variants_by_part=model_variants_by_part,
                        )
                        st.session_state.pop(excluded_create_parts_key, None)

                        for _paired_pid in selected_parts["part_id"].astype(str).tolist():
                            for _prefix in (
                                "process_pairing_handling",
                                "process_pairing_quantity",
                                "process_pairing_location",
                                "process_pairing_model_variant",
                            ):
                                st.session_state.pop(
                                    f"{_prefix}_{scenario_id}_{section_id}_{selected_yamazumi_id}_{_paired_pid}",
                                    None,
                                )
                        for _paired_pid in selected_parts["part_id"].astype(str).tolist():
                            for _prefix in (
                                "process_pairing_handling",
                                "process_pairing_quantity",
                                "process_pairing_location",
                                "process_pairing_model_variant",
                            ):
                                _pop_paag_tab_state(
                                    f"{_prefix}_{scenario_id}_{section_id}_{selected_yamazumi_id}_{_paired_pid}",
                                    None,
                                )
                        for _we_prefix in (
                            "process_pairing_rule",
                            "process_pairing_requirement",
                            "process_pairing_notes",
                            "process_tool_cat",
                            "process_tool_specific",
                            "process_res_type",
                            "process_res_detail",
                        ):
                            _pop_paag_tab_state(
                                f"{_we_prefix}_{scenario_id}_{section_id}_{selected_yamazumi_id}",
                                None,
                            )
                        _pop_paag_tab_state(selected_part_ids_key, None)
                        request_table_editor_reset(work_source_key)
                        request_table_editor_reset(not_consumed_part_source_key)
                        request_table_editor_reset(consumed_part_source_key)
                        record_audit_event(
                            project_id,
                            "Process part pairings",
                            "Pair parts",
                            len(selected_parts),
                            st.session_state.get("current_editor", ""),
                            {
                                "scenario_id": scenario_id,
                                "work_element": selected_description,
                                "requirement": final_group_name,
                                "section": section_labels.get(section_id, section_id),
                                "part_uses": selected_pairing_details,
                                "tool": final_tool,
                                "resource_type": resource_type,
                                "resource_detail": resource_detail,
                            },
                        )
                        st.toast(
                            f"Created PAAG requirement '{final_group_name}' ({len(selected_parts)} part(s)) on '{selected_description}'",
                            icon=":material/check_circle:",
                        )
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
                if add_without_parts:
                    reconcile_yamazumi_to_process(project_id, scenario_id, [selected_yamazumi_id])
                    new_proc_id = process_element_id_for_yamazumi(
                        project_id, scenario_id, selected_yamazumi_id
                    )
                    if new_proc_id:
                        update_work_element_tool_and_resource(
                            project_id,
                            scenario_id,
                            new_proc_id,
                            tool=final_tool,
                            resource_type=resource_type,
                            resource_detail=resource_detail,
                        )
                        if selected_equipment_id and selected_pitch_id:
                            try:
                                save_equipment_placement(
                                    project_id=project_id,
                                    scenario_id=scenario_id,
                                    equipment_id=selected_equipment_id,
                                    pitch_id=str(selected_pitch_id),
                                    work_element_ids=[new_proc_id],
                                    editor_name=st.session_state.get("current_editor", ""),
                                )
                            except Exception:
                                pass
                    record_audit_event(
                        project_id,
                        "Process plan",
                        "Add Yamazumi work",
                        1,
                        st.session_state.get("current_editor", ""),
                        {
                            "scenario_id": scenario_id,
                            "work_element": selected_description,
                            "tool": final_tool,
                            "resource_type": resource_type,
                            "resource_detail": resource_detail,
                        },
                    )
                    st.toast(
                        f"Added '{selected_description}' to Process at a Glance",
                        icon=":material/check_circle:",
                    )
                    st.rerun()

                if selected_process_id:
                    saved_groups = process_part_groups(
                        project_id, scenario_id, selected_process_id, active_only=True
                    )
                    if saved_groups:
                        st.markdown("##### Existing Part requirements")
                        pairing_editor_key = (
                            f"existing_process_pairings_{scenario_id}_{selected_process_id}"
                        )
                        pairing_editor_key = apply_pending_table_editor_reset(pairing_editor_key)
                        pairing_rows = pd.DataFrame(
                            [
                                {
                                    "id": str(group["id"]),
                                    "requirement": str(group["name"]),
                                    "selection_rule": str(group["selection_rule"]),
                                    "quantity": float(group["quantity"]),
                                    "parts": ", ".join(
                                        str(option["part_number"])
                                        for option in group["options"]
                                    ),
                                }
                                for group in saved_groups
                            ]
                        )
                        pairing_rows = prepare_editor_selection_column(
                            pairing_rows, editor_key=pairing_editor_key
                        )
                        pairing_action_slot = st.empty()
                        edited_pairings = st.data_editor(
                            pairing_rows,
                            key=pairing_editor_key,
                            hide_index=True,
                            num_rows="fixed",
                            disabled=[col for col in pairing_rows.columns if col != "selected"],
                            column_order=[
                                "selected", "requirement", "selection_rule", "quantity", "parts"
                            ],
                            column_config={
                                "id": None,
                                "selected": st.column_config.CheckboxColumn(
                                    "Select",
                                    default=False,
                                    pinned=True,
                                    width="small",
                                    help="Select one or more part requirements to remove from this step.",
                                ),
                                "requirement": st.column_config.TextColumn("Part requirement"),
                                "selection_rule": st.column_config.TextColumn("Selection rule"),
                                "quantity": st.column_config.NumberColumn(
                                    "Quantity", format="%.2f"
                                ),
                                "parts": st.column_config.TextColumn(
                                    "Parts Consumed or Handled", width="large"
                                ),
                            },
                        )
                        selected_pairings = resolve_editor_selected_rows(
                            pairing_rows, edited_pairings, editor_key=pairing_editor_key
                        )
                        pairing_bulk = selected_rows_action_bar(parent=pairing_action_slot)
                        render_select_all_control(
                            pairing_bulk,
                            editor_key=pairing_editor_key,
                            selectable_count=len(pairing_rows),
                            selected_count=len(selected_pairings),
                            key_prefix=f"pairing_select_{scenario_id}_{selected_process_id}",
                        )
                        remove_selected_pairings = pairing_bulk.button(
                            f"Remove selected ({len(selected_pairings)})",
                            icon=":material/delete:",
                            disabled=selected_pairings.empty,
                            key=f"destructive_remove_pairings_{scenario_id}_{selected_process_id}",
                            help="Remove the selected part requirements from this work element.",
                        )
                        native_selected_pairings = native_selected_rows(
                            pairing_rows, editor_key=pairing_editor_key
                        )
                        request_pairing_delete = bool(
                            remove_selected_pairings or not native_selected_pairings.empty
                        )
                        if request_pairing_delete:
                            selected_ids = set(selected_pairings["id"].astype(str))
                            selected_group_rows = [
                                group
                                for group in saved_groups
                                if str(group["id"]) in selected_ids
                            ]
                            st.session_state[pairing_delete_key] = {
                                "editor_key": pairing_editor_key,
                                "work_element_id": selected_process_id,
                                "work_element": selected_description,
                                "groups": [
                                    {
                                        "id": str(group["id"]),
                                        "requirement": str(group["name"]),
                                        "parts": [
                                            str(option["part_number"])
                                            for option in group["options"]
                                        ],
                                    }
                                    for group in selected_group_rows
                                ],
                            }
                            stage_native_delete_confirmation(pairing_editor_key)
            else:
                st.caption("Select one Yamazumi work element to pair parts or add it to the plan.")

        st.divider()

        process_editor_key = apply_pending_table_editor_reset(process_editor_key)
        elements = project_table("work_elements", project_id, "sequence", scenario_id=scenario_id)
        columns = [
            "id", "op_id", "sequence", "station", "pitch_name", "work_element", "operation", "description", "cycle_time_s",
            "assigned_parts", "handling", "resource", "resource_type", "resource_detail", "part_number", "output_assembly_number", "output_assembly_name",
            "tool", "torque", "quality_requirement", "ergo_requirement", "location", "unit_orientation",
            "conveyor_height_in", "platform_height_in", "pit_depth_in",
            "model_applicability", "ergonomics_risk", "criticality", "status",
        ]
        compact_columns = [
            "op_id",
            "station",
            "pitch_name",
            "work_element",
            "status",
            "resource",
            "tool",
            "assigned_parts",
            "handling",
            "ergonomics_risk",
            "criticality",
            "model_applicability",
            "cycle_time_s",
            "sequence",
        ]
        yamazumi_context = pd.DataFrame()
        if elements.empty:
            elements = pd.DataFrame(
                {
                    "id": pd.Series(dtype="string"),
                    "op_id": pd.Series(dtype="string"),
                    "sequence": pd.Series(dtype="int64"),
                    "station": pd.Series(dtype="string"),
                    "pitch_name": pd.Series(dtype="string"),
                    "work_element": pd.Series(dtype="string"),
                    "operation": pd.Series(dtype="string"),
                    "description": pd.Series(dtype="string"),
                    "cycle_time_s": pd.Series(dtype="float64"),
                    "assigned_parts": pd.Series(dtype="string"),
                    "handling": pd.Series(dtype="object"),
                    "resource": pd.Series(dtype="string"),
                    "resource_type": pd.Series(dtype="string"),
                    "resource_detail": pd.Series(dtype="string"),
                    "part_number": pd.Series(dtype="string"),
                    "output_assembly_number": pd.Series(dtype="string"),
                    "output_assembly_name": pd.Series(dtype="string"),
                    "tool": pd.Series(dtype="string"),
                    "torque": pd.Series(dtype="string"),
                    "quality_requirement": pd.Series(dtype="string"),
                    "ergo_requirement": pd.Series(dtype="string"),
                    "location": pd.Series(dtype="string"),
                    "unit_orientation": pd.Series(dtype="string"),
                    "conveyor_height_in": pd.Series(dtype="float64"),
                    "platform_height_in": pd.Series(dtype="float64"),
                    "pit_depth_in": pd.Series(dtype="float64"),
                    "model_applicability": pd.Series(dtype="object"),
                    "ergonomics_risk": pd.Series(dtype="object"),
                    "criticality": pd.Series(dtype="object"),
                    "status": pd.Series(dtype="string"),
                }
            )
        else:
            elements = elements.copy()
            op_ids = work_element_op_ids(
                project_id, scenario_id, elements["id"].astype(str).tolist()
            )
            elements["op_id"] = elements["id"].astype(str).map(op_ids).fillna(
                "Yamazumi link required"
            )
            pairing_summary: dict[str, list[str]] = {}
            handling_summary: dict[str, set[str]] = {}
            for group in process_part_groups(project_id, scenario_id, active_only=True):
                if group["selection_rule"] in {"Model choice", "Choose one"}:
                    variant_nums = [
                        str(option["part_number"])
                        for option in group["options"]
                        if option.get("is_model_variant", True)
                    ]
                    non_variant_nums = [
                        str(option["part_number"])
                        for option in group["options"]
                        if not option.get("is_model_variant", True)
                    ]
                    if variant_nums and non_variant_nums:
                        suffix = f"{' / '.join(variant_nums)}, {', '.join(non_variant_nums)}"
                    elif variant_nums:
                        suffix = " / ".join(variant_nums)
                    else:
                        suffix = " / ".join(
                            str(option["part_number"]) for option in group["options"]
                        )
                else:
                    option_numbers = [
                        str(option["part_number"]) for option in group["options"]
                    ]
                    suffix = ", ".join(option_numbers)
                work_element_id = str(group["work_element_id"])
                pairing_summary.setdefault(work_element_id, []).append(
                    f"{group['name']}: {suffix}"
                )
                handling_summary.setdefault(work_element_id, set()).update(
                    str(option.get("handling_type") or "Unclassified")
                    for option in group["options"]
                )
            elements["assigned_parts"] = elements["id"].astype(str).map(
                lambda element_id: " | ".join(pairing_summary.get(element_id, []))
            )
            handling_order = {"Consume": 0, "Handle": 1, "Unclassified": 2}
            elements["handling"] = elements["id"].astype(str).map(
                lambda element_id: sorted(
                    handling_summary.get(element_id, set()),
                    key=lambda value: (handling_order.get(value, 99), value),
                )
            )

            def _format_resource_vals(rtype_val, rdet_val) -> str:
                rtype = str(rtype_val or "Human").strip()
                rdet = str(rdet_val or "").strip()
                if rtype.casefold() == "autonomous equipment":
                    return f"Autonomous: {rdet}" if rdet else "Autonomous equipment"
                return rtype or "Human"

            elements["resource"] = [
                _format_resource_vals(rt, rd)
                for rt, rd in zip(
                    elements["resource_type"] if "resource_type" in elements.columns else [None] * len(elements),
                    elements["resource_detail"] if "resource_detail" in elements.columns else [None] * len(elements),
                )
            ]

            yamazumi_context = yamazumi_context_for_process(project_id, scenario_id)
            if yamazumi_context.empty:
                elements["pitch_name"] = ""
                elements["work_element"] = elements["operation"].fillna("").astype(str)
            else:
                yamazumi_context = yamazumi_context.drop_duplicates(
                    subset=["process_element_id"], keep="first"
                ).set_index("process_element_id")
                process_ids = elements["id"].astype(str)
                elements["pitch_name"] = process_ids.map(
                    yamazumi_context["pitch_name"].fillna("").astype(str)
                ).fillna("")
                if "pitch_number" in yamazumi_context.columns:
                    yamazumi_pitches = (
                        process_ids.map(
                            yamazumi_context["pitch_number"].fillna("").astype(str)
                        )
                        .fillna("")
                        .str.strip()
                    )
                    elements["station"] = yamazumi_pitches.where(
                        yamazumi_pitches.ne(""),
                        elements["station"].fillna("").astype(str),
                    )
                if "yamazumi_model_applicability" in yamazumi_context.columns:
                    linked_mask = process_ids.isin(yamazumi_context.index)
                    yamazumi_models = (
                        process_ids.map(
                            yamazumi_context["yamazumi_model_applicability"]
                            .fillna("")
                            .astype(str)
                        )
                        .fillna("")
                        .str.strip()
                    )
                    elements["model_applicability"] = yamazumi_models.where(
                        linked_mask
                        & yamazumi_models.ne("")
                        & yamazumi_models.str.casefold().ne("all"),
                        elements["model_applicability"].fillna("All").astype(str),
                    )
                if "yamazumi_time_s" in yamazumi_context.columns:
                    linked_time_mask = process_ids.isin(yamazumi_context.index)
                    yamazumi_times = pd.to_numeric(
                        process_ids.map(yamazumi_context["yamazumi_time_s"]),
                        errors="coerce",
                    )
                    elements["cycle_time_s"] = yamazumi_times.where(
                        linked_time_mask & yamazumi_times.notna(),
                        pd.to_numeric(elements["cycle_time_s"], errors="coerce").fillna(
                            0.0
                        ),
                    )
                yamazumi_descriptions = process_ids.map(
                    yamazumi_context["yamazumi_description"].fillna("").astype(str)
                ).fillna("")
                elements["work_element"] = yamazumi_descriptions.where(
                    yamazumi_descriptions.str.strip().ne(""),
                    elements["operation"].fillna("").astype(str),
                )
            ergonomics_risk_ids = process_ergonomics_risk_work_element_ids(
                project_id, scenario_id
            )
            elements["ergonomics_risk"] = pd.Series(
                [
                    ["Ergo Risk"] if work_element_id in ergonomics_risk_ids else []
                    for work_element_id in elements["id"].astype(str)
                ],
                index=elements.index,
                dtype="object",
            )
            criticality_by_work_element = work_element_criticality(project_id, scenario_id)
            elements["criticality"] = pd.Series(
                [
                    list(criticality_by_work_element.get(work_element_id, []))
                    for work_element_id in elements["id"].astype(str)
                ],
                index=elements.index,
                dtype="object",
            )

            def _normalize_element_features(raw_value: object) -> list[str]:
                normalized: list[str] = []
                for token in (split_filter_values(raw_value) or ["All models"]):
                    mapped = feature_variant_aliases.get(str(token).strip().casefold())
                    if mapped and mapped not in normalized:
                        normalized.append(mapped)
                return normalized or ["All models"]

            elements["model_applicability"] = pd.Series(
                [
                    _normalize_element_features(value)
                    for value in elements["model_applicability"]
                ],
                index=elements.index,
                dtype="object",
            )
            elements = elements.reindex(columns=columns)

        elements["selected"] = pd.Series(False, index=elements.index, dtype="bool")

        editable_table_heading("Process at a Glance by Pitch")
        st.caption("Complete and review ordered work elements by pitch and feature applicability.")
        visible_elements = filter_table(
            elements,
            key=f"process_filters_{scenario_id}",
            dropdown_columns=["station", "status", "resource", "handling", "model_applicability"],
            labels={"station": "Pitch", "model_applicability": "Feature"},
            search_columns=[
                "op_id", "work_element", "pitch_name", "status", "description", "station", "resource", "assigned_parts", "output_assembly_number",
                "output_assembly_name", "tool", "quality_requirement", "ergo_requirement", "location",
            ],
            reset_widget_keys=[process_editor_key],
            multi_value_columns=["handling", "model_applicability"],
            universal_values={"model_applicability": ["All", "All models", ""]},
        )
        visible_elements = prepare_editor_selection_column(
            visible_elements, editor_key=process_editor_key
        )
        process_action_slot = st.empty()



        prior_editor_state = dict(st.session_state.get(process_editor_key, {}) or {})

        edited = st.data_editor(
            visible_elements,
            key=process_editor_key,
            hide_index=True,
            num_rows="fixed",
            height=470,
            disabled=[
                "id",
                "op_id",
                "station",
                "pitch_name",
                "work_element",
                "resource",
                "assigned_parts",
                "handling",
                "ergonomics_risk",
                "criticality",
                "cycle_time_s",
                "model_applicability",
            ],
            column_order=["selected", *compact_columns],
            column_config={
                "id": None,
                "part_number": None,
                "selected": st.column_config.CheckboxColumn(
                    "Select",
                    default=False,
                    pinned=True,
                    width="small",
                    help=(
                        "Select one or more lines to edit with Edit line, move to a "
                        "destination pitch, or delete."
                    ),
                ),
                "op_id": st.column_config.TextColumn(
                    "Op ID",
                    pinned=True,
                    width="small",
                    help=(
                        "Identifies this Work Element's current Fishbone lineage, Pitch, and "
                        "centerline-outward stack position. It may change if the Fishbone "
                        "structure or Yamazumi assignments change."
                    ),
                ),
                "sequence": st.column_config.NumberColumn("Seq.", min_value=0, step=10),
                "station": st.column_config.TextColumn(
                    "Pitch", pinned=True, width=110
                ),
                "pitch_name": None,
                "work_element": st.column_config.TextColumn(
                    "Work Element", required=True, pinned=True, width=180
                ),
                "status": st.column_config.SelectboxColumn(
                    "Status",
                    options=["Draft", "Review", "Validated"],
                    required=True,
                    width="small",
                    help=(
                        "PAAG validation sign-off. Only steps that are technically complete "
                        "(valid Op ID and classified part handlings) and marked 'Validated' "
                        "are eligible for PFMEA selection and sync."
                    ),
                ),
                "resource": st.column_config.TextColumn(
                    "Resource",
                    help="Resource performing work (Human or Autonomous equipment)",
                    disabled=True,
                    width="medium",
                ),
                "tool": st.column_config.TextColumn(
                    "Tool",
                    help="Handheld equipment or tool used for this work element",
                    width="medium",
                ),
                "assigned_parts": st.column_config.TextColumn(
                    "Part requirements", width="large"
                ),
                "handling": st.column_config.ListColumn(
                    "Handling",
                    help=(
                        "Shows whether the parts paired to this Work Element are first consumed "
                        "or subsequently handled. Compatibility-null pairings appear as Unclassified."
                    ),
                    width="medium",
                ),
                "ergonomics_risk": st.column_config.MultiselectColumn(
                    "Ergonomics",
                    options=["Ergo Risk"],
                    color="red",
                    disabled=True,
                    width="medium",
                    help=(
                        "Shown when this step has an Open or Pending Ergonomics review "
                        "classified as Red or Favorable Red. Review details on the "
                        "Ergonomics page."
                    ),
                ),
                "criticality": st.column_config.MultiselectColumn(
                    "Criticality",
                    options=["CTQ", "Safety"],
                    color=["orange", "red"],
                    disabled=True,
                    width="medium",
                    help=(
                        "CTQ comes from a linked PFMEA Classification of E, P, P-, Q, or E-. "
                        "Safety comes from an active Safety requirement linked to this Process step."
                    ),
                ),
                "cycle_time_s": st.column_config.NumberColumn(
                    "Time (s)",
                    min_value=0.0,
                    step=0.1,
                    format="%.1f",
                    disabled=True,
                    help="Work element cycle time (managed in the Yamazumi tab).",
                ),
                "model_applicability": st.column_config.MultiselectColumn(
                    "Feature",
                    options=process_model_options,
                    disabled=True,
                    help="Model/feature applicability (managed in the Yamazumi tab).",
                ),
            },
        )
        footer_actions = editable_table_footer(
            editor_key=process_editor_key,
            key_prefix=f"process_plan_{scenario_id}",
            native_row_selection=True,
            additional_action_label="Edit line",
            additional_action_icon=":material/edit:",
            additional_action_key=f"process_edit_line_btn_{scenario_id}",
            additional_action_disabled=visible_elements.empty,
            additional_action_help=(
                "Select a line in the table and click Edit line to replace an assigned "
                "part, change handling classification, or edit line details."
            ),
        )


        export_actions = st.container(horizontal=True)
        _lazy_process_export = (
            getattr(dataframe_to_excel, "__module__", "") == "utils.table_ui"
        )
        export_actions.download_button(
            "Export filtered table view",
            data=(
                (
                    lambda _df=visible_elements, _cols=list(compact_columns): dataframe_to_excel(
                        _df.reindex(columns=_cols),
                        "Process plan",
                    )
                )
                if _lazy_process_export
                else dataframe_to_excel(
                    visible_elements.reindex(columns=compact_columns),
                    "Process plan",
                )
            ),
            file_name="process_plan_filtered_view.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
            key=f"process_compact_export_{scenario_id}",
        )
        export_actions.download_button(
            "Export filtered full data",
            data=(
                (
                    lambda _df=visible_elements: dataframe_to_excel(
                        _df.drop(columns=["id", "details", "selected"], errors="ignore"),
                        "Process plan",
                    )
                )
                if _lazy_process_export
                else dataframe_to_excel(
                    visible_elements.drop(
                        columns=["id", "details", "selected"], errors="ignore"
                    ),
                    "Process plan",
                )
            ),
            file_name="process_plan_filtered_full.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
            key=f"process_full_export_{scenario_id}",
        )

        native_selected = native_selected_rows(visible_elements, editor_key=process_editor_key)
        selected = resolve_editor_selected_rows(
            visible_elements,
            edited,
            editor_key=process_editor_key,
            prior_editor_state=prior_editor_state,
        )


        def current_process_editor_rows() -> pd.DataFrame:
            """Capture cell edits without treating native row selection as deletion."""
            state = st.session_state.get(process_editor_key, {}) or {}
            draft = visible_elements.copy()
            for raw_position, changes in (state.get("edited_rows") or {}).items():
                position = int(raw_position)
                if not 0 <= position < len(draft):
                    continue
                for column, value in (changes or {}).items():
                    if column == "selected":
                        continue
                    if column in draft.columns:
                        draft.at[draft.index[position], column] = value
            return draft


        def save_unsaved_process_table_edits(*, paired_removal: bool) -> int:
            """Persist unrelated compact-table edits before a confirmed pairing removal."""
            if not table_has_unsaved_changes(
                process_editor_key, native_row_selection=True
            ):
                return 0
            draft = current_process_editor_rows()
            errors = required_field_errors(draft, {"work_element": "Work Element"})
            if errors:
                raise ValueError(" ".join(errors))
            combined = merge_filtered_edits(elements, visible_elements, draft)
            combined["model_applicability"] = combined["model_applicability"].apply(
                lambda assigned: ", ".join(
                    "All" if label == "All models" else model_numbers_by_label.get(label, label)
                    for label in (assigned or ["All models"])
                )
            )
            replace_work_elements(project_id, scenario_id, combined)
            changed_count = sum(
                1
                for row_changes in (
                    (st.session_state.get(process_editor_key, {}) or {}).get("edited_rows") or {}
                ).values()
                if any(col != "selected" for col in (row_changes or {}).keys())
            )
            record_audit_event(
                project_id,
                "Process plan",
                "Save & Refresh",
                changed_count,
                st.session_state.get("current_editor", ""),
                {
                    "scenario_id": scenario_id,
                    "scenario_id": scenario_id,
                    "created_count": 0,
                    "updated_count": changed_count,
                    "saved_with_pairing_removal": paired_removal,
                },
            )
            return changed_count


        bulk = selected_rows_action_bar(
            parent=process_action_slot,
        )
        render_select_all_control(
            bulk,
            editor_key=process_editor_key,
            selectable_count=len(visible_elements),
            selected_count=len(selected),
            key_prefix=f"process_select_{scenario_id}",
        )
        move_selected = bulk.button(
            f"Move selected ({len(selected)})",
            type="primary",
            icon=":material/drive_file_move:",
            disabled=selected.empty,
            key=f"process_move_selected_{scenario_id}",
            help="Move the selected work element line(s) to a destination pitch address.",
        )
        delete_selected = bulk.button(
            f"Unlink selected ({len(selected)})",
            icon=":material/link_off:",
            disabled=selected.empty,
            key=f"destructive_process_delete_selected_{scenario_id}",
            help="Unlink the selected work element line(s) from this Process at a Glance plan without deleting the Yamazumi work element.",
        )
        request_bulk_delete = bool(delete_selected or not native_selected.empty)

        if move_selected:
            if table_has_unsaved_changes(process_editor_key, native_row_selection=True):
                st.warning("Save or undo other edits before moving selected steps.")
            else:
                st.session_state[f"process_pending_move_{scenario_id}"] = (
                    selected["id"].astype(str).tolist()
                )

        @st.dialog("Move selected Process steps")
        def confirm_process_move() -> None:
            pending_move_key = f"process_pending_move_{scenario_id}"
            pending_move_ids = st.session_state.get(pending_move_key, [])
            if not pending_move_ids:
                st.session_state.pop(pending_move_key, None)
                request_table_editor_reset(process_editor_key)
                st.rerun()

            scenario_pitches_df = yamazumi_pitches_for_scenario(project_id, scenario_id)
            move_pitch_options: list[str] = []
            move_pitch_labels: dict[str, str] = {}
            if not scenario_pitches_df.empty:
                for _, p_row in scenario_pitches_df.iterrows():
                    p_num = str(p_row.get("pitch_number") or "").strip()
                    if not p_num or p_num in move_pitch_labels:
                        continue
                    p_name = str(p_row.get("pitch_name") or "").strip()
                    move_pitch_options.append(p_num)
                    move_pitch_labels[p_num] = f"{p_num} — {p_name}" if p_name else p_num
            if not elements.empty and "station" in elements.columns:
                for raw_st in elements["station"].dropna().astype(str):
                    clean_st = raw_st.strip()
                    if clean_st and clean_st not in move_pitch_labels:
                        move_pitch_options.append(clean_st)
                        move_pitch_labels[clean_st] = clean_st

            st.markdown(
                f"**Select a destination pitch for {len(pending_move_ids)} selected Process step(s):**"
            )
            if not move_pitch_options:
                st.info("No pitches are defined in this scenario yet.")
                if st.button("Close", key=f"cancel_process_move_empty_{scenario_id}"):
                    st.session_state.pop(pending_move_key, None)
                    st.rerun()
                return

            dest_pitch = st.selectbox(
                "Destination pitch address",
                options=move_pitch_options,
                index=None,
                placeholder="Select or type a destination pitch address...",
                format_func=lambda val: move_pitch_labels.get(val, val),
                key=f"process_move_dest_pitch_{scenario_id}",
            )
            move_actions = st.container(horizontal=True)
            if move_actions.button("Cancel", key=f"cancel_process_move_{scenario_id}"):
                st.session_state.pop(pending_move_key, None)
                st.session_state.pop(f"process_move_dest_pitch_{scenario_id}", None)
                st.rerun()
            if move_actions.button(
                "Move steps",
                type="primary",
                icon=":material/drive_file_move:",
                disabled=not bool(str(dest_pitch or "").strip()),
                key=f"confirm_process_move_{scenario_id}",
            ):
                clean_dest = str(dest_pitch or "").strip()
                updated = elements.copy()
                selected_ids = set(str(i) for i in pending_move_ids)
                mask = updated["id"].astype(str).isin(selected_ids)
                updated.loc[mask, "station"] = clean_dest
                updated["model_applicability"] = updated["model_applicability"].apply(
                    lambda assigned: ", ".join(
                        "All" if label == "All models" else model_numbers_by_label.get(label, label)
                        for label in (assigned or ["All models"])
                    )
                )
                impact = work_element_downstream_impact(project_id, scenario_id, list(selected_ids))
                replace_work_elements(project_id, scenario_id, updated)
                record_audit_event(
                    project_id,
                    "Process plan",
                    "Move steps to pitch",
                    len(selected_ids),
                    st.session_state.get("current_editor", ""),
                    {"scenario_id": scenario_id, "pitch": clean_dest},
                )
                st.session_state.pop(pending_move_key, None)
                st.session_state.pop(f"process_move_dest_pitch_{scenario_id}", None)
                request_table_editor_reset(process_editor_key)
                if impact.get("quality_count", 0) > 0 or impact.get("pfmea_count", 0) > 0:
                    st.toast(
                        f"Moved {len(selected_ids)} step(s) to pitch {clean_dest} · {impact['quality_count']} Quality spec(s) & {impact['pfmea_count']} PFMEA item(s) flagged for review.",
                        icon=":material/info:",
                    )
                else:
                    st.toast(
                        f"Moved {len(selected_ids)} step(s) to pitch {clean_dest}",
                        icon=":material/check_circle:",
                    )
                st.rerun()

        if st.session_state.get(f"process_pending_move_{scenario_id}"):
            confirm_process_move()

        if request_bulk_delete:
            if table_has_unsaved_changes(process_editor_key, native_row_selection=True):
                st.warning("Save or undo other edits before unlinking selected steps.")
            else:
                delete_target = selected if not selected.empty else native_selected
                st.session_state[f"process_pending_delete_{scenario_id}"] = (
                    delete_target["id"].astype(str).tolist()
                )
                stage_native_delete_confirmation(process_editor_key)


        @st.dialog("Unlink selected Process steps?", dismissible=False)
        def confirm_process_delete() -> None:
            pending_key = f"process_pending_delete_{scenario_id}"
            pending_ids = st.session_state.get(pending_key, [])
            if not pending_ids:
                st.session_state.pop(pending_key, None)
                request_table_editor_reset(process_editor_key)
                st.rerun()

            impact = work_element_downstream_impact(project_id, scenario_id, pending_ids)
            has_impact = impact["has_impact"]
            count_steps = len(pending_ids)

            st.markdown(
                f"**Are you sure you want to unlink {count_steps} Process step(s) from Process at a Glance?**"
            )
            st.caption(
                "This only unlinks the step(s) from Process at a Glance; the underlying Yamazumi work element(s) will not be deleted."
            )

            if has_impact:
                st.error(
                    "⚠️ **Downstream Engineering Data Impact Detected**\n\n"
                    "Industrial Engineers cannot directly delete Quality or PFMEA records. "
                    "Unlinking these process steps will unlink downstream records and preserve their snapshots for "
                    "Quality Engineering review and reconciliation in the Quality workspace."
                )

                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Quality Requirements", impact["quality_count"])
                    st.metric("PFMEA Failure Modes", impact["pfmea_count"])
                with col2:
                    st.metric("Equipment Links", impact["equipment_count"])
                    st.metric("Safety Requirements (Deleted)", impact["safety_count"])

                if impact["operations_affected"]:
                    st.caption(f"Affected Operations: {', '.join(impact['operations_affected'])}")

                ack = st.checkbox(
                    "I acknowledge that unlinking these steps unlinks downstream Quality, PFMEA, and Equipment "
                    "records and notifies the Quality team for reconciliation.",
                    value=False,
                    key=f"ack_process_delete_{scenario_id}",
                )
                delete_label = "Unlink steps & Notify Quality"
                delete_disabled = not ack
            else:
                st.info("No downstream Quality requirements, PFMEA failure modes, or Equipment links are associated with these steps.")
                delete_label = "Unlink steps"
                delete_disabled = False

            actions = st.container(horizontal=True)
            if actions.button("Cancel", key=f"cancel_process_delete_{scenario_id}"):
                st.session_state.pop(pending_key, None)
                st.session_state.pop(f"ack_process_delete_{scenario_id}", None)
                request_table_editor_reset(process_editor_key)
                st.rerun()
            if actions.button(
                delete_label,
                type="primary",
                icon=":material/link_off:",
                disabled=delete_disabled,
                key=f"destructive_confirm_process_delete_{scenario_id}",
            ):
                retained = elements.loc[~elements["id"].astype(str).isin(set(pending_ids))].copy()
                retained["model_applicability"] = retained["model_applicability"].apply(
                    lambda assigned: ", ".join(
                        "All" if label == "All models" else model_numbers_by_label.get(label, label)
                        for label in (assigned or ["All models"])
                    )
                )
                replace_work_elements(project_id, scenario_id, retained)
                del_proc_impacts: list[str] = []
                if impact.get("quality_count"):
                    del_proc_impacts.append(f"{impact['quality_count']} Quality spec(s) unlinked")
                if impact.get("pfmea_count"):
                    del_proc_impacts.append(f"{impact['pfmea_count']} PFMEA item(s) unlinked")
                if impact.get("equipment_count"):
                    del_proc_impacts.append(f"{impact['equipment_count']} Equipment link(s) removed")
                if impact.get("safety_count"):
                    del_proc_impacts.append(f"{impact['safety_count']} Safety req(s) deleted")
                st.toast(
                    f"Deleted {len(pending_ids)} Process step(s)"
                    + (f" · {', '.join(del_proc_impacts)}" if del_proc_impacts else ""),
                    icon=":material/delete:",
                )
                record_audit_event(
                    project_id,
                    "Process plan",
                    "Delete steps",
                    len(pending_ids),
                    st.session_state.get("current_editor", ""),
                    {
                        "scenario_id": scenario_id,
                        "impact_quality_unlinked": impact["quality_count"],
                        "impact_pfmea_unlinked": impact["pfmea_count"],
                        "impact_equipment_unlinked": impact["equipment_count"],
                        "impact_safety_deleted": impact["safety_count"],
                        "affected_operations": impact["operations_affected"],
                    },
                )
                st.session_state.pop(pending_key, None)
                st.session_state.pop(f"ack_process_delete_{scenario_id}", None)
                request_table_editor_reset(process_editor_key)
                st.rerun()


        if st.session_state.get(f"process_pending_delete_{scenario_id}"):
            confirm_process_delete()

        if footer_actions.additional_action:
            explicit_selected_id = str(
                st.session_state.pop(f"process_selected_line_id_{scenario_id}", "") or ""
            ).strip()
            if table_has_unsaved_changes(process_editor_key, native_row_selection=True):
                st.warning("Save or undo Process at a Glance table edits first.")
            elif len(selected) > 1:
                st.warning("Select only one line at a time to edit.")
            elif len(selected) == 1:
                st.session_state[edit_line_dialog_key] = str(selected.iloc[0]["id"])
            elif explicit_selected_id and explicit_selected_id in set(
                visible_elements["id"].astype(str)
            ):
                st.session_state[edit_line_dialog_key] = explicit_selected_id
            elif len(visible_elements) == 1:
                st.session_state[edit_line_dialog_key] = str(visible_elements.iloc[0]["id"])
            else:
                st.warning("Select a line in the Select column of the table to edit.")

        if footer_actions.undo:
            st.toast("Discarded the unsaved Process at a Glance edits", icon=":material/undo:")
            request_table_editor_reset(process_editor_key)
            st.rerun()

        if footer_actions.save_and_refresh:
            try:
                if not native_selected.empty:
                    raise ValueError("Clear selected rows before saving table edits.")
                errors = required_field_errors(edited, {"work_element": "Work Element"})
                if errors:
                    raise ValueError(" ".join(errors))
                combined_elements = merge_filtered_edits(elements, visible_elements, edited)
                combined_elements["model_applicability"] = combined_elements["model_applicability"].apply(
                    lambda assigned: ", ".join(
                        "All" if label == "All models" else model_numbers_by_label.get(label, label)
                        for label in (assigned or ["All models"])
                    )
                )
                edited_raw = (st.session_state.get(process_editor_key, {}) or {}).get("edited_rows", {})
                edited_indices = [
                    idx
                    for idx, row_changes in edited_raw.items()
                    if any(col != "selected" for col in (row_changes or {}).keys())
                ]
                affected_ids = []
                if edited_indices and not visible_elements.empty:
                    for idx in edited_indices:
                        try:
                            pos = int(idx)
                            if 0 <= pos < len(visible_elements):
                                affected_ids.append(str(visible_elements.iloc[pos]["id"]))
                        except (ValueError, TypeError, IndexError):
                            pass
                impact = work_element_downstream_impact(project_id, scenario_id, affected_ids) if affected_ids else {"quality_count": 0, "pfmea_count": 0}

                _proc_created_cnt, _proc_updated_cnt = count_table_create_and_edit_rows(
                    elements,
                    combined_elements,
                    compare_columns=[
                        "station",
                        "operation",
                        "work_element",
                        "tool",
                        "resource_type",
                        "resource_detail",
                        "cycle_time_s",
                        "sequence",
                        "model_applicability",
                        "status",
                    ],
                )
                if _proc_created_cnt == 0 and _proc_updated_cnt == 0 and affected_ids:
                    _proc_updated_cnt = len(affected_ids)
                replace_work_elements(project_id, scenario_id, combined_elements)
                record_audit_event(
                    project_id,
                    "Process plan",
                    "Save & Refresh",
                    len(combined_elements),
                    st.session_state.get("current_editor", ""),
                    {
                        "scenario_id": scenario_id,
                        "created_count": _proc_created_cnt,
                        "updated_count": _proc_updated_cnt,
                    },
                )
                request_table_editor_reset(process_editor_key)
                if impact.get("quality_count", 0) > 0 or impact.get("pfmea_count", 0) > 0:
                    st.toast(
                        f"Saved {len(combined_elements)} Process step(s)"
                        + (f" ({len(affected_ids)} modified)" if affected_ids else "")
                        + f" · {impact['quality_count']} Quality spec(s) & {impact['pfmea_count']} PFMEA item(s) flagged for review.",
                        icon=":material/info:",
                    )
                else:
                    st.toast(
                        f"Saved {len(combined_elements)} Process step(s)"
                        + (f" ({len(affected_ids)} modified)" if affected_ids else ""),
                        icon=":material/check_circle:",
                    )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


        @st.dialog("Remove selected Part requirements?", dismissible=False)
        def confirm_pairing_bulk_removal() -> None:
            pending = st.session_state.get(pairing_delete_key, {})
            groups = pending.get("groups", [])
            st.warning(
                f"Remove {len(groups)} selected Part requirement(s)? The parts listed below will be "
                "removed from this work element."
            )
            for group in groups:
                parts = ", ".join(group.get("parts", [])) or "No active parts"
                st.write(f"- {group['requirement']}: {parts}")
            st.info(
                "The parts are not deleted. They will return to the available-parts table for "
                "their Fishbone section."
            )
            has_other_edits = table_has_unsaved_changes(
                process_editor_key, native_row_selection=True
            )
            if has_other_edits:
                st.info(
                    "Other unsaved Process at a Glance table edits will be saved at the same "
                    "time so they are not lost."
                )
            actions = st.container(horizontal=True)
            if actions.button("Cancel", key=f"cancel_pairing_bulk_remove_{scenario_id}"):
                st.session_state.pop(pairing_delete_key, None)
                pairing_editor_key = str(pending.get("editor_key") or "")
                if pairing_editor_key:
                    request_table_editor_reset(pairing_editor_key)
                st.rerun()
            if actions.button(
                "Unlink Part requirements",
                type="primary",
                icon=":material/link_off:",
                key=f"destructive_confirm_pairing_bulk_remove_{scenario_id}",
            ):
                try:
                    save_unsaved_process_table_edits(paired_removal=True)
                    group_ids = [str(group["id"]) for group in groups]
                    removed_count = delete_process_part_groups(
                        project_id, scenario_id, group_ids
                    )
                    record_audit_event(
                        project_id,
                        "Process part pairings",
                        "Remove pairing",
                        removed_count,
                        st.session_state.get("current_editor", ""),
                        {
                            "scenario_id": scenario_id,
                            "work_element_id": pending.get("work_element_id"),
                            "work_element": pending.get("work_element"),
                            "pairings": groups,
                        },
                    )
                    st.session_state.pop(pairing_delete_key, None)
                    request_table_editor_reset(process_editor_key)
                    pairing_editor_key = str(pending.get("editor_key") or "")
                    if pairing_editor_key:
                        request_table_editor_reset(pairing_editor_key)
                    st.toast(
                        f"Removed {removed_count} Part requirement(s); their parts are available again.",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


        if st.session_state.get(pairing_delete_key):
            confirm_pairing_bulk_removal()

        def close_edit_process_line_dialog() -> None:
            st.session_state.pop(edit_line_dialog_key, None)
            st.session_state.pop(f"process_selected_line_id_{scenario_id}", None)
            if not table_has_unsaved_changes(process_editor_key, native_row_selection=True):
                request_table_editor_reset(process_editor_key)

        @st.dialog(
            "Edit Process at a Glance line",
            width="large",
            on_dismiss=close_edit_process_line_dialog,
        )
        def edit_process_line_dialog() -> None:
            target_id = str(st.session_state.get(edit_line_dialog_key) or "").strip()
            match_rows = elements.loc[elements["id"].astype(str) == target_id]
            if not target_id or match_rows.empty:
                close_edit_process_line_dialog()
                st.rerun()
            line_row = match_rows.iloc[0]

            line_op_id = str(line_row.get("op_id") or "").strip()
            line_pitch_name = str(
                line_row.get("pitch_name") or line_row.get("station") or ""
            ).strip()
            line_work_element = str(
                line_row.get("work_element") or line_row.get("operation") or ""
            ).strip()
            header_parts = [p for p in [line_op_id, line_pitch_name] if p]
            header_prefix = " · ".join(header_parts)
            st.markdown(
                f"**{header_prefix}** — {line_work_element}"
                if header_prefix
                else f"**{line_work_element}**"
            )
            st.caption(
                "Replace an incorrectly assigned part, adjust handling classification or "
                "Fishbone location, or update this line's tool, resource, and sequence."
            )

            default_line_sec_id = ""
            line_pitch_id = ""
            if not yamazumi_context.empty and target_id in yamazumi_context.index:
                ctx_row = yamazumi_context.loc[target_id]
                if isinstance(ctx_row, pd.DataFrame):
                    ctx_row = ctx_row.iloc[0]
                default_line_sec_id = str(ctx_row.get("section_id") or "").strip()
                line_pitch_id = str(ctx_row.get("pitch_id") or "").strip()

            saved_line_groups = process_part_groups(
                project_id, scenario_id, target_id, active_only=True
            )
            groups_by_id = {str(g["id"]): g for g in saved_line_groups}

            st.markdown("##### Part requirements on this line")
            req_mode_options: list[str] = [str(g["id"]) for g in saved_line_groups]
            req_mode_labels: dict[str, str] = {}
            for g in saved_line_groups:
                gid = str(g["id"])
                g_parts = ", ".join(
                    str(opt.get("part_number") or "") for opt in g.get("options", [])
                )
                req_mode_labels[gid] = (
                    f"Edit: {g['name']} ({g_parts or 'No parts'})"
                )
            if section_ids:
                req_mode_options.append("__NEW__")
                req_mode_labels["__NEW__"] = "+ Add a new Part requirement"
            req_mode_options.append("__NONE__")
            req_mode_labels["__NONE__"] = "(Do not change Part requirements)"

            req_mode = st.selectbox(
                "Part requirement action",
                options=req_mode_options,
                index=0,
                format_func=lambda val, labels=req_mode_labels: labels.get(val, val),
                key=f"edit_line_req_mode_{scenario_id}_{target_id}",
            )

            active_group = groups_by_id.get(req_mode)
            editing_group_id = str(active_group["id"]) if active_group else None
            edit_sec_id = ""
            selected_edit_part_ids: list[str] = []
            edit_handling_types_by_part: dict[str, str] = {}
            edit_assignment_ids_by_part: dict[str, str | None] = {}
            edit_quantities_by_part: dict[str, float | None] = {}
            edit_model_variants_by_part: dict[str, bool] = {}
            edit_pairing_details: list[dict] = []
            edit_selection_rule = "Use all"
            edit_is_handle_op = False
            edit_auto_name = line_work_element or "Part requirement"
            edit_group_name = ""
            edit_quantity = 1.0
            edit_notes = ""

            if req_mode != "__NONE__":
                if not section_ids:
                    st.info("Create and populate the Fishbone framework before pairing parts.")
                else:
                    pref_sec_id = (
                        str(active_group.get("section_id") or "").strip()
                        if active_group
                        else (
                            default_line_sec_id
                            if default_line_sec_id in section_ids
                            else section_ids[0]
                        )
                    )
                    sec_idx = (
                        section_ids.index(pref_sec_id)
                        if pref_sec_id in section_ids
                        else 0
                    )
                    edit_sec_id = st.selectbox(
                        "Fishbone section",
                        options=section_ids,
                        index=sec_idx,
                        format_func=lambda val: section_labels.get(val, val),
                        key=f"edit_line_sec_{scenario_id}_{target_id}_{req_mode}",
                    )

                    all_fb_placements = fishbone_part_assignments(project_id, scenario_id)
                    sec_placements = (
                        all_fb_placements.loc[
                            all_fb_placements["section_id"].astype(str) == str(edit_sec_id)
                        ].copy()
                        if not all_fb_placements.empty
                        else pd.DataFrame()
                    )
                    in_edit_sec_part_ids = (
                        set(sec_placements["part_id"].astype(str))
                        if not sec_placements.empty
                        else set()
                    )
                    edit_consumed_part_ids: set[str] = set()
                    for g_row in process_part_groups(
                        project_id, scenario_id, active_only=True
                    ):
                        for opt_row in g_row.get("options", []):
                            if (
                                str(opt_row.get("handling_type") or "")
                                .strip()
                                .capitalize()
                                == "Consume"
                            ):
                                edit_consumed_part_ids.add(str(opt_row.get("part_id")))
                    edit_candidates = (
                        all_fb_placements.loc[
                            (all_fb_placements["section_id"].astype(str) == str(edit_sec_id))
                            | (
                                all_fb_placements["part_id"]
                                .astype(str)
                                .isin(edit_consumed_part_ids)
                            )
                        ].copy()
                        if not all_fb_placements.empty
                        else pd.DataFrame()
                    )
                    part_label_map: dict[str, str] = {}
                    part_number_map: dict[str, str] = {}
                    part_desc_map: dict[str, str] = {}
                    if not edit_candidates.empty:
                        edit_candidates["_in_sec_rank"] = (
                            edit_candidates["section_id"].astype(str) != str(edit_sec_id)
                        ).astype(int)
                        dedup_parts = (
                            edit_candidates.sort_values(
                                ["_in_sec_rank", "part_number", "sequence", "id"]
                            )
                            .drop_duplicates(subset=["part_id"], keep="first")
                        )
                        for _, p_row in dedup_parts.iterrows():
                            pid = str(p_row["part_id"])
                            pnum = str(p_row.get("part_number") or "").strip()
                            pdesc = (
                                ""
                                if pd.isna(p_row.get("description"))
                                else str(p_row.get("description") or "").strip()
                            )
                            part_number_map[pid] = pnum
                            part_desc_map[pid] = pdesc
                            part_label_map[pid] = f"{pnum} — {pdesc}" if pdesc else pnum

                    default_part_ids: list[str] = []
                    existing_options_by_part: dict[str, dict] = {}
                    if (
                        active_group
                        and str(active_group.get("section_id") or "") == str(edit_sec_id)
                    ):
                        for opt in active_group.get("options", []):
                            opid = str(opt.get("part_id") or "")
                            if not opid:
                                continue
                            existing_options_by_part[opid] = opt
                            if opid not in part_label_map:
                                opnum = str(opt.get("part_number") or opid).strip()
                                opdesc = str(opt.get("description") or "").strip()
                                part_number_map[opid] = opnum
                                part_desc_map[opid] = opdesc
                                part_label_map[opid] = (
                                    f"{opnum} — {opdesc}" if opdesc else opnum
                                )
                            default_part_ids.append(opid)

                    edit_ms_key = (
                        f"edit_line_parts_{scenario_id}_{target_id}_"
                        f"{req_mode}_{edit_sec_id}"
                    )
                    pending_remove_edit_part = st.session_state.pop(
                        f"_pending_remove_{edit_ms_key}", None
                    )
                    if pending_remove_edit_part and isinstance(
                        st.session_state.get(edit_ms_key), list
                    ):
                        st.session_state[edit_ms_key] = [
                            p
                            for p in st.session_state[edit_ms_key]
                            if str(p) != str(pending_remove_edit_part)
                        ]
                    if not part_label_map:
                        st.info("No active Fishbone parts are assigned to this section.")
                    else:
                        selected_edit_part_ids = st.multiselect(
                            "Parts Consumed or Handled",
                            options=list(part_label_map.keys()),
                            default=default_part_ids,
                            format_func=lambda pid, labels=part_label_map: labels.get(
                                pid, pid
                            ),
                            help=(
                                "Remove an incorrectly assigned part and select the replacement "
                                "part(s) from this Fishbone section."
                            ),
                            key=edit_ms_key,
                        )

                    rule_options = ["Use all", "Model choice", "Optional"]
                    raw_orig_rule = (
                        str(active_group.get("selection_rule") or "Use all")
                        if active_group
                        else "Use all"
                    )
                    orig_rule = (
                        "Model choice" if raw_orig_rule == "Choose one" else raw_orig_rule
                    )
                    default_rule_idx = (
                        rule_options.index(orig_rule)
                        if orig_rule in rule_options
                        else 0
                    )
                    edit_rule_key = f"edit_line_rule_{scenario_id}_{target_id}_{req_mode}"
                    if st.session_state.get(edit_rule_key) == "Choose one":
                        st.session_state[edit_rule_key] = "Model choice"
                    edit_selection_rule = st.selectbox(
                        "Selection rule",
                        options=rule_options,
                        index=default_rule_idx,
                        key=edit_rule_key,
                    )

                    preview_edit_models = st.session_state.get(
                        f"edit_line_models_{scenario_id}_{target_id}"
                    )
                    preview_target_variants = (
                        tuple(str(m) for m in preview_edit_models)
                        if isinstance(preview_edit_models, list) and preview_edit_models
                        else None
                    )
                    _edit_pfr_df = part_feature_rules(project_id)
                    edit_feature_rule_pids = (
                        set(_edit_pfr_df["part_id"].astype(str))
                        if not _edit_pfr_df.empty and "part_id" in _edit_pfr_df.columns
                        else set()
                    )
                    for pid in selected_edit_part_ids:
                        pnum = part_number_map.get(pid, pid)
                        pdesc = part_desc_map.get(pid, "")
                        existing_opt = existing_options_by_part.get(pid, {})
                        p_options = process_part_placement_options(
                            project_id,
                            scenario_id,
                            edit_sec_id,
                            pid,
                            exclude_group_id=editing_group_id,
                            work_element_id=target_id,
                            target_variants=preview_target_variants,
                        )
                        with st.container(border=True):
                            st.markdown(
                                f"**{pnum}**" + (f" — {pdesc}" if pdesc else "")
                            )
                            mv_key = (
                                f"edit_line_mv_{scenario_id}_{target_id}_"
                                f"{req_mode}_{edit_sec_id}_{pid}"
                            )
                            if edit_selection_rule == "Model choice":
                                if existing_opt and orig_rule == "Model choice":
                                    default_is_mv = bool(
                                        existing_opt.get("is_model_variant")
                                    )
                                else:
                                    default_is_mv = _part_has_model_variants(
                                        pid,
                                        all_fb_placements,
                                        fallback_model_applicability=existing_opt.get(
                                            "model_applicability"
                                        ),
                                        feature_rule_part_ids=edit_feature_rule_pids,
                                    )
                                is_mv_val = st.checkbox(
                                    "Model variant",
                                    value=default_is_mv,
                                    help=(
                                        "Check if this part is one of the model-choice alternatives "
                                        "the operator chooses between on this step."
                                    ),
                                    key=mv_key,
                                )
                                edit_model_variants_by_part[pid] = bool(is_mv_val)
                            else:
                                _pop_paag_tab_state(mv_key, None)
                                edit_model_variants_by_part[pid] = False
                            existing_ht = str(
                                existing_opt.get("handling_type")
                                or (
                                    "Consume"
                                    if (
                                        pid in in_edit_sec_part_ids
                                        and not p_options.empty
                                        and "can_consume" in p_options.columns
                                        and bool(p_options["can_consume"].any())
                                    )
                                    else "Handle"
                                )
                            ).strip()
                            default_ht_idx = 1 if existing_ht == "Handle" else 0
                            ht_col, qty_col = st.columns([2, 1])
                            ht_val = ht_col.selectbox(
                                "Handling type",
                                options=["Consume", "Handle"],
                                index=default_ht_idx,
                                key=(
                                    f"edit_line_ht_{scenario_id}_{target_id}_"
                                    f"{req_mode}_{edit_sec_id}_{pid}"
                                ),
                            )
                            existing_part_qty = (
                                existing_opt.get("quantity")
                                if existing_opt and existing_opt.get("quantity") is not None
                                else (active_group.get("quantity") if active_group else 1.0)
                            )
                            default_part_qty = max(float(existing_part_qty or 1.0), 0.01)
                            part_qty_val = qty_col.number_input(
                                "Quantity",
                                min_value=0.01,
                                value=default_part_qty,
                                step=1.0,
                                disabled=(ht_val != "Consume"),
                                help=(
                                    "Enter the quantity of parts consumed."
                                    if ht_val == "Consume"
                                    else "Quantity is only available when Handling type is Consume."
                                ),
                                key=(
                                    f"edit_line_qty_{scenario_id}_{target_id}_"
                                    f"{req_mode}_{edit_sec_id}_{pid}"
                                ),
                            )
                            edit_handling_types_by_part[pid] = ht_val
                            edit_quantities_by_part[pid] = (
                                float(part_qty_val) if ht_val == "Consume" else None
                            )

                            pl_labels: dict[str, str] = {}
                            disabled_pl_ids: set[str] = set()
                            for _, pl_row in p_options.iterrows():
                                aid = str(pl_row["fishbone_assignment_id"])
                                raw_use = pl_row.get("use_description")
                                use_desc = (
                                    "No location recorded"
                                    if pd.isna(raw_use) or not str(raw_use or "").strip()
                                    else str(raw_use).strip()
                                )
                                pl_sec_id = str(pl_row.get("section_id") or "")
                                pl_sec_name = str(pl_row.get("section_name") or "").strip()
                                if (
                                    pl_sec_id
                                    and pl_sec_id != str(edit_sec_id)
                                    and pl_sec_name
                                ):
                                    use_desc = f"{pl_sec_name} ({use_desc})"
                                qty_lbl = format_clean_number(pl_row["fishbone_quantity"])
                                rem_lbl = format_clean_number(
                                    pl_row["remaining_consume_allowance"]
                                )
                                if ht_val == "Consume":
                                    can_consume_pl = bool(pl_row["can_consume"])
                                    avail_lbl = (
                                        f"Remaining Consume allowance {rem_lbl}"
                                        if can_consume_pl
                                        else "Unavailable for Consume — allowance fully used"
                                    )
                                    if not can_consume_pl:
                                        disabled_pl_ids.add(aid)
                                else:
                                    avail_lbl = (
                                        "Available for Handle"
                                        if bool(pl_row["can_handle"])
                                        else "Unavailable for Handle — Consume first"
                                    )
                                pl_labels[aid] = (
                                    f"{use_desc} · Fishbone quantity {qty_lbl} · {avail_lbl}"
                                )
                            pl_ids = list(pl_labels.keys())
                            pl_key = (
                                f"edit_line_loc_{scenario_id}_{target_id}_"
                                f"{req_mode}_{edit_sec_id}_{pid}"
                            )
                            existing_aid = str(
                                existing_opt.get("fishbone_assignment_id") or ""
                            ).strip()
                            handle_auto_key = f"{pl_key}__handle_auto"
                            if ht_val != "Consume":
                                auto_handle_id = (
                                    existing_aid
                                    if existing_aid in pl_ids
                                    else next(
                                        (
                                            str(r["fishbone_assignment_id"])
                                            for _, r in p_options.iterrows()
                                            if bool(r.get("can_handle"))
                                        ),
                                        pl_ids[0] if pl_ids else None,
                                    )
                                )
                                st.session_state[handle_auto_key] = True
                                if (
                                    auto_handle_id is not None
                                    and st.session_state.get(pl_key) != auto_handle_id
                                ):
                                    st.session_state[pl_key] = auto_handle_id
                                st.selectbox(
                                    "Use / installation location",
                                    options=pl_ids,
                                    format_func=lambda v, labels=pl_labels: labels.get(
                                        v, v
                                    ),
                                    disabled=True,
                                    help=(
                                        "Use / installation location is only needed when "
                                        "Handling type is Consume."
                                    ),
                                    key=pl_key,
                                )
                                chosen_aid = auto_handle_id
                            else:
                                if (
                                    st.session_state.pop(handle_auto_key, False)
                                    and len(pl_ids) > 1
                                    and existing_aid not in pl_ids
                                ):
                                    st.session_state[pl_key] = None
                                if (
                                    pl_key in st.session_state
                                    and str(st.session_state.get(pl_key) or "")
                                    in disabled_pl_ids
                                ):
                                    st.session_state[pl_key] = None
                                if (
                                    len(pl_ids) == 1
                                    and pl_ids[0] not in disabled_pl_ids
                                ):
                                    if st.session_state.get(pl_key) != pl_ids[0]:
                                        st.session_state[pl_key] = pl_ids[0]
                                    chosen_aid = st.selectbox(
                                        "Use / installation location",
                                        options=pl_ids,
                                        format_func=lambda v, labels=pl_labels: labels.get(
                                            v, v
                                        ),
                                        disabled=True,
                                        key=pl_key,
                                    )
                                else:
                                    default_pl_idx = (
                                        pl_ids.index(existing_aid)
                                        if existing_aid in pl_ids
                                        and existing_aid not in disabled_pl_ids
                                        else None
                                    )
                                    chosen_aid = st.selectbox(
                                        "Use / installation location",
                                        options=pl_ids,
                                        index=default_pl_idx,
                                        placeholder="Choose a Use / installation location",
                                        format_func=lambda v, labels=pl_labels: labels.get(
                                            v, v
                                        ),
                                        key=pl_key,
                                    )
                                if chosen_aid and str(chosen_aid) in disabled_pl_ids:
                                    chosen_aid = None
                            _inject_disabled_consumed_placement_options_script()
                            edit_assignment_ids_by_part[pid] = (
                                str(chosen_aid) if chosen_aid else None
                            )
                            edit_pairing_details.append(
                                {
                                    "id": existing_opt.get("id"),
                                    "part_id": pid,
                                    "part_number": pnum,
                                    "handling_type": ht_val,
                                    "quantity": edit_quantities_by_part.get(pid),
                                    "is_model_variant": edit_model_variants_by_part.get(
                                        pid, False
                                    ),
                                    "fishbone_assignment_id": (
                                        str(chosen_aid) if chosen_aid else None
                                    ),
                                }
                            )
                            if st.button(
                                "Unlink this part from the PAAG element",
                                icon=":material/link_off:",
                                key=(
                                    f"destructive_edit_line_remove_part_{scenario_id}_{target_id}_"
                                    f"{req_mode}_{edit_sec_id}_{pid}"
                                ),
                            ):
                                if active_group and pid in existing_options_by_part:
                                    st.session_state[f"process_pending_unlink_line_req_{scenario_id}"] = {
                                        "group_id": str(editing_group_id),
                                        "part_id": str(pid),
                                        "part_number": str(pnum),
                                        "part_label": f"{pnum} — {pdesc}" if pdesc else str(pnum),
                                        "target_id": str(target_id),
                                        "work_element": str(line_work_element),
                                        "requirement": str(active_group.get("name") or ""),
                                        "edit_sec_id": str(edit_sec_id),
                                        "edit_ms_key": edit_ms_key,
                                    }
                                    st.rerun()
                                else:
                                    st.session_state[f"_pending_remove_{edit_ms_key}"] = str(pid)
                                    st.rerun()

                    consumed_edit_quantities = [
                        float(q)
                        for q in edit_quantities_by_part.values()
                        if q is not None and float(q) > 0
                    ]
                    edit_quantity = (
                        consumed_edit_quantities[0]
                        if consumed_edit_quantities
                        else (
                            float(active_group.get("quantity") or 1.0)
                            if active_group
                            else 1.0
                        )
                    )

                    edit_is_handle_op = any(
                        ht == "Handle" for ht in edit_handling_types_by_part.values()
                    )
                    edit_part_labels = []
                    edit_variant_labels = []
                    edit_non_variant_labels = []
                    for pid in selected_edit_part_ids:
                        lbl = part_desc_map.get(pid) or part_number_map.get(pid, "")
                        if lbl:
                            edit_part_labels.append(lbl)
                            if edit_model_variants_by_part.get(pid, False):
                                edit_variant_labels.append(lbl)
                            else:
                                edit_non_variant_labels.append(lbl)
                    if edit_selection_rule in {"Model choice", "Choose one"}:
                        if edit_variant_labels and edit_non_variant_labels:
                            edit_auto_name = (
                                f"{' / '.join(edit_variant_labels)}, "
                                f"{', '.join(edit_non_variant_labels)}"
                            )
                        elif edit_variant_labels:
                            edit_auto_name = " / ".join(edit_variant_labels)
                        else:
                            edit_auto_name = (
                                " / ".join(edit_part_labels)
                                if edit_part_labels
                                else (line_work_element or "Part option")
                            )
                    elif edit_selection_rule == "Optional":
                        edit_auto_name = (
                            f"Optional: {', '.join(edit_part_labels)}"
                            if edit_part_labels
                            else (line_work_element or "Optional part")
                        )
                    else:
                        edit_auto_name = (
                            ", ".join(edit_part_labels)
                            if edit_part_labels
                            else (line_work_element or "Part requirement")
                        )
                    if len(edit_auto_name) > 80 and edit_part_labels:
                        edit_auto_name = (
                            f"{edit_part_labels[0]} (+{len(edit_part_labels) - 1} parts)"
                        )

                    parts_unchanged = (
                        active_group is not None
                        and selected_edit_part_ids == default_part_ids
                        and edit_selection_rule == orig_rule
                    )
                    default_req_name = (
                        str(active_group.get("name") or "")
                        if parts_unchanged
                        else (edit_auto_name if not edit_is_handle_op else "")
                    )
                    parts_sig = hashlib.md5(
                        f"{','.join(selected_edit_part_ids)}_{edit_selection_rule}_{edit_is_handle_op}".encode()
                    ).hexdigest()[:8]
                    edit_group_name = st.text_input(
                        "Part requirement *" if edit_is_handle_op else "Part requirement",
                        value=default_req_name,
                        placeholder=(
                            "Describe the handling requirement"
                            if edit_is_handle_op
                            else "Named automatically from selected parts"
                        ),
                        key=(
                            f"edit_line_req_name_{scenario_id}_{target_id}_"
                            f"{req_mode}_{parts_sig}"
                        ),
                    )
                    edit_notes = st.text_input(
                        "Part requirement notes",
                        value=(
                            str(active_group.get("notes") or "")
                            if active_group
                            else ""
                        ),
                        placeholder="Model choice, installation intent, or other guidance",
                        key=f"edit_line_notes_{scenario_id}_{target_id}_{req_mode}",
                    )

            st.divider()
            st.markdown("##### Line details")

            all_types_df = equipment_types(project_id)
            type_labels = [
                str(lbl).strip()
                for lbl in all_types_df["label"].dropna().unique()
                if str(lbl).strip()
            ]
            for std_tool in [
                "Handheld equipment",
                "Torque tool",
                "Scan/Compare equipment",
                "Poka-Yoke / Fixture equipment",
                "Test equipment",
                "Tape machine",
                "Platform",
                "Pit",
                "Operator Lift",
                "Ergo Hand Tools",
                "Ergo Lift Assists",
            ]:
                if std_tool not in type_labels:
                    type_labels.append(std_tool)
            type_labels.sort()
            tool_categories = ["(No tool required)", *type_labels, "Other tool"]

            existing_tool = str(line_row.get("tool") or "").strip()
            existing_res_type = str(line_row.get("resource_type") or "Human").strip()
            existing_res_detail = str(line_row.get("resource_detail") or "").strip()

            all_assets_df = equipment_assets(project_id, scenario_id)
            default_cat_idx = 0
            if existing_tool:
                matched_cat = False
                for idx, cat in enumerate(tool_categories):
                    if cat.casefold() == existing_tool.casefold():
                        default_cat_idx = idx
                        matched_cat = True
                        break
                if (
                    not matched_cat
                    and not all_assets_df.empty
                    and "name" in all_assets_df.columns
                ):
                    for _, a_row in all_assets_df.iterrows():
                        a_name = str(a_row.get("name") or "").strip()
                        a_type = str(a_row.get("equipment_type") or "").strip()
                        if a_name and a_name.casefold() == existing_tool.casefold():
                            for idx, cat in enumerate(tool_categories):
                                if cat.casefold() == a_type.casefold():
                                    default_cat_idx = idx
                                    matched_cat = True
                                    break
                            if matched_cat:
                                break
                if not matched_cat:
                    default_cat_idx = tool_categories.index("Other tool")

            tool_c1, tool_c2 = st.columns(2)
            edit_tool_category = tool_c1.selectbox(
                "Tool category",
                options=tool_categories,
                index=default_cat_idx,
                key=f"edit_line_tool_cat_{scenario_id}_{target_id}",
            )
            edit_final_tool = ""
            edit_selected_equipment_id = None
            if edit_tool_category == "(No tool required)":
                tool_c2.caption("No tool assigned to this line.")
            elif edit_tool_category == "Other tool":
                default_custom_tool = (
                    existing_tool
                    if existing_tool
                    and existing_tool.casefold()
                    not in {c.casefold() for c in tool_categories}
                    else ""
                )
                edit_final_tool = tool_c2.text_input(
                    "Custom tool name",
                    value=default_custom_tool,
                    placeholder="Enter tool name",
                    key=f"edit_line_tool_custom_{scenario_id}_{target_id}",
                ).strip() or "Other tool"
            else:
                cat_assets = pd.DataFrame()
                if (
                    not all_assets_df.empty
                    and "equipment_type" in all_assets_df.columns
                ):
                    cat_assets = all_assets_df[
                        all_assets_df["equipment_type"].astype(str).str.casefold()
                        == edit_tool_category.casefold()
                    ]
                asset_choices = ["(Standard / Unspecified)"]
                asset_id_map: dict[str, tuple[str, str]] = {}
                for _, a_row in cat_assets.iterrows():
                    a_name = str(a_row.get("name") or "").strip()
                    if a_name:
                        a_model = str(a_row.get("model") or "").strip()
                        a_label = f"{a_name} ({a_model})" if a_model else a_name
                        asset_choices.append(a_label)
                        asset_id_map[a_label] = (str(a_row["id"]), a_name)
                default_asset_idx = 0
                if (
                    existing_tool
                    and existing_tool.casefold() != edit_tool_category.casefold()
                ):
                    for idx, ch in enumerate(asset_choices):
                        if existing_tool.casefold() in ch.casefold():
                            default_asset_idx = idx
                            break
                selected_asset_choice = tool_c2.selectbox(
                    "Specific handheld tool / equipment",
                    options=asset_choices,
                    index=default_asset_idx,
                    key=f"edit_line_tool_asset_{scenario_id}_{target_id}_{edit_tool_category}",
                )
                if selected_asset_choice != "(Standard / Unspecified)":
                    eq_info = asset_id_map.get(selected_asset_choice)
                    if eq_info:
                        edit_selected_equipment_id = eq_info[0]
                        edit_final_tool = eq_info[1]
                    else:
                        edit_final_tool = selected_asset_choice
                else:
                    edit_final_tool = edit_tool_category

            res_c1, res_c2 = st.columns(2)
            default_res_idx = (
                1 if existing_res_type.casefold() == "autonomous equipment" else 0
            )
            edit_resource_type = res_c1.selectbox(
                "Resource performing work",
                options=["Human", "Autonomous equipment"],
                index=default_res_idx,
                key=f"edit_line_res_type_{scenario_id}_{target_id}",
            )
            edit_resource_detail = ""
            if edit_resource_type == "Autonomous equipment":
                auto_options = ["Robot", "AMR", "Quality checker"]
                default_det_idx = (
                    auto_options.index(existing_res_detail)
                    if existing_res_detail in auto_options
                    else 0
                )
                edit_resource_detail = res_c2.selectbox(
                    "Autonomous resource type",
                    options=auto_options,
                    index=default_det_idx,
                    key=f"edit_line_res_detail_{scenario_id}_{target_id}",
                )
            else:
                res_c2.caption("Standard manual operator performing work.")

            model_options = list(process_model_options)
            raw_models = line_row.get("model_applicability")
            current_models = (
                [m for m in raw_models if m in model_options]
                if isinstance(raw_models, list)
                else ["All models"]
            )
            if not current_models:
                current_models = ["All models"]
            edit_models = st.multiselect(
                "Feature",
                options=model_options,
                default=current_models,
                disabled=True,
                help="Update feature/model applicability in the Yamazumi tab.",
                key=f"edit_line_models_{scenario_id}_{target_id}",
            )

            time_col, seq_col, status_col = st.columns(3)
            current_time = (
                0.0
                if pd.isna(line_row.get("cycle_time_s"))
                else float(line_row.get("cycle_time_s") or 0.0)
            )
            current_seq = (
                0
                if pd.isna(line_row.get("sequence"))
                else int(line_row.get("sequence") or 0)
            )
            status_options = ["Draft", "Review", "Validated"]
            current_status = str(line_row.get("status") or "Draft").strip()
            if current_status not in status_options:
                current_status = "Draft"
            edit_cycle_time = time_col.number_input(
                "Time (s)",
                min_value=0.0,
                value=max(current_time, 0.0),
                step=0.1,
                format="%.1f",
                disabled=True,
                help="Update work element time in the Yamazumi tab.",
                key=f"edit_line_time_{scenario_id}_{target_id}",
            )
            edit_sequence = seq_col.number_input(
                "Seq.",
                min_value=0,
                value=max(current_seq, 0),
                step=10,
                key=f"edit_line_seq_{scenario_id}_{target_id}",
            )
            edit_status = status_col.selectbox(
                "PAAG Status",
                options=status_options,
                index=status_options.index(current_status),
                help="Mark as Validated once the Op ID and part handlings are complete so PFMEA can reference this step.",
                key=f"edit_line_status_{scenario_id}_{target_id}",
            )

            dialog_actions = st.container(horizontal=True)
            if dialog_actions.button(
                "Cancel",
                key=f"edit_line_cancel_{scenario_id}_{target_id}",
            ):
                close_edit_process_line_dialog()
                st.rerun()
            if dialog_actions.button(
                "Save PAAG Element",
                type="primary",
                icon=":material/save:",
                key=f"edit_line_save_{scenario_id}_{target_id}",
            ):
                try:
                    final_group_name = ""
                    if req_mode != "__NONE__":
                        if not edit_sec_id:
                            raise ValueError("Choose a Fishbone section.")
                        if not selected_edit_part_ids:
                            raise ValueError(
                                "Select at least one Fishbone part for the requirement, "
                                "or remove the Part requirement from the line."
                            )
                        missing_locs = [
                            d["part_number"]
                            for d in edit_pairing_details
                            if d.get("handling_type") == "Consume"
                            and not d["fishbone_assignment_id"]
                        ]
                        if missing_locs:
                            raise ValueError(
                                "Choose a Use / installation location for: "
                                + ", ".join(missing_locs)
                                + "."
                            )
                        final_group_name = str(edit_group_name or "").strip()
                        if not final_group_name:
                            if edit_is_handle_op:
                                raise ValueError(
                                    "Part requirement name is required for handle operations."
                                )
                            final_group_name = edit_auto_name
                        other_names = {
                            str(g.get("name") or "").strip().casefold()
                            for g in saved_line_groups
                            if str(g.get("id")) != str(editing_group_id or "")
                        }
                        base_candidate = final_group_name
                        counter = 2
                        while final_group_name.casefold() in other_names:
                            final_group_name = f"{base_candidate} ({counter})"
                            counter += 1
                        validate_process_part_option_pairings(
                            project_id,
                            scenario_id,
                            edit_sec_id,
                            edit_pairing_details,
                            exclude_group_id=editing_group_id,
                            work_element_id=target_id,
                            target_variants=tuple(
                                str(m) for m in (edit_models or ["All models"])
                            ),
                        )

                    updated_elements = elements.copy()
                    row_mask = updated_elements["id"].astype(str) == target_id
                    updated_elements.loc[row_mask, "tool"] = edit_final_tool
                    updated_elements.loc[row_mask, "resource_type"] = edit_resource_type
                    updated_elements.loc[row_mask, "resource_detail"] = edit_resource_detail
                    updated_elements.loc[row_mask, "cycle_time_s"] = float(edit_cycle_time)
                    updated_elements.loc[row_mask, "sequence"] = int(edit_sequence)
                    updated_elements.loc[row_mask, "status"] = str(edit_status)
                    for idx in updated_elements.index[row_mask]:
                        updated_elements.at[idx, "model_applicability"] = (
                            edit_models or ["All models"]
                        )
                    updated_elements["model_applicability"] = updated_elements[
                        "model_applicability"
                    ].apply(
                        lambda assigned: ", ".join(
                            "All"
                            if label == "All models"
                            else model_numbers_by_label.get(label, label)
                            for label in (assigned or ["All models"])
                        )
                    )
                    replace_work_elements(project_id, scenario_id, updated_elements)
                    update_work_element_tool_and_resource(
                        project_id,
                        scenario_id,
                        target_id,
                        tool=edit_final_tool,
                        resource_type=edit_resource_type,
                        resource_detail=edit_resource_detail,
                    )
                    if edit_selected_equipment_id and line_pitch_id:
                        try:
                            save_equipment_placement(
                                project_id=project_id,
                                scenario_id=scenario_id,
                                equipment_id=edit_selected_equipment_id,
                                pitch_id=line_pitch_id,
                                work_element_ids=[target_id],
                                editor_name=st.session_state.get("current_editor", ""),
                            )
                        except Exception:
                            pass

                    if req_mode != "__NONE__":
                        save_process_part_group(
                            project_id,
                            scenario_id,
                            target_id,
                            edit_sec_id,
                            editing_group_id,
                            final_group_name,
                            edit_selection_rule,
                            edit_quantity,
                            selected_edit_part_ids,
                            edit_notes,
                            handling_types_by_part=edit_handling_types_by_part,
                            fishbone_assignment_ids_by_part=edit_assignment_ids_by_part,
                            quantities_by_part=edit_quantities_by_part,
                            model_variants_by_part=edit_model_variants_by_part,
                        )
                        record_audit_event(
                            project_id,
                            "Process part pairings",
                            "Update part pairing" if editing_group_id else "Pair parts",
                            len(selected_edit_part_ids),
                            st.session_state.get("current_editor", ""),
                            {
                                "scenario_id": scenario_id,
                                "work_element_id": target_id,
                                "work_element": line_work_element,
                                "requirement": final_group_name,
                                "section": section_labels.get(edit_sec_id, edit_sec_id),
                                "part_uses": edit_pairing_details,
                            },
                        )
                        request_table_editor_reset(
                            f"process_part_source_{scenario_id}_{edit_sec_id}"
                        )
                        request_table_editor_reset(
                            f"process_part_source_consumed_{scenario_id}_{edit_sec_id}"
                        )

                    record_audit_event(
                        project_id,
                        "Process plan",
                        "Edit line",
                        1,
                        st.session_state.get("current_editor", ""),
                        {
                            "scenario_id": scenario_id,
                            "work_element_id": target_id,
                            "work_element": line_work_element,
                            "tool": edit_final_tool,
                            "resource_type": edit_resource_type,
                            "resource_detail": edit_resource_detail,
                            "cycle_time_s": float(edit_cycle_time),
                            "sequence": int(edit_sequence),
                        },
                    )
                    request_table_editor_reset(process_editor_key)
                    close_edit_process_line_dialog()
                    st.toast(
                        f"Updated Process line '{line_work_element}'",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        pending_unlink_line_req_key = f"process_pending_unlink_line_req_{scenario_id}"

        @st.dialog("Unlink part from PAAG element?", dismissible=False)
        def confirm_unlink_line_req_dialog() -> None:
            info = st.session_state.get(pending_unlink_line_req_key) or {}
            part_id = str(info.get("part_id") or "").strip()
            part_label = str(
                info.get("part_label")
                or info.get("part_number")
                or info.get("requirement")
                or "this part"
            )
            req_name = str(info.get("requirement") or "this Part requirement")
            we_name = str(info.get("work_element") or "this PAAG element")
            st.warning(f"Unlink **{part_label}** from **{we_name}**?")
            st.caption(
                "Downstream effects: This removes the part pairing from this PAAG element in the active scenario. "
                "The PAAG element itself, Fishbone part placements, and Parts Catalog records remain intact, and the Fishbone part returns to Available Parts for pairing."
            )
            actions = st.container(horizontal=True)
            if actions.button("Cancel", key=f"cancel_unlink_line_req_{scenario_id}"):
                st.session_state.pop(pending_unlink_line_req_key, None)
                st.rerun()
            if actions.button(
                "Unlink",
                type="primary",
                icon=":material/link_off:",
                key=f"destructive_confirm_unlink_line_req_{scenario_id}",
            ):
                grp_id = str(info.get("group_id") or "")
                tgt_id = str(info.get("target_id") or "")
                sec_id = str(info.get("edit_sec_id") or "")
                ms_key = str(info.get("edit_ms_key") or "")
                if grp_id:
                    if part_id:
                        removed = unlink_part_from_process_group(
                            project_id, scenario_id, grp_id, part_id
                        )
                    else:
                        removed = delete_process_part_groups(
                            project_id, scenario_id, [grp_id]
                        )
                    if ms_key:
                        st.session_state.pop(ms_key, None)
                    record_audit_event(
                        project_id,
                        "Process part pairings",
                        "Remove pairing",
                        removed,
                        st.session_state.get("current_editor", ""),
                        {
                            "scenario_id": scenario_id,
                            "work_element_id": tgt_id,
                            "work_element": we_name,
                            "requirement": req_name,
                            "part": part_label,
                        },
                    )
                    request_table_editor_reset(process_editor_key)
                    request_table_editor_reset(
                        f"process_part_source_{scenario_id}_{sec_id}"
                    )
                    request_table_editor_reset(
                        f"process_part_source_consumed_{scenario_id}_{sec_id}"
                    )
                st.session_state.pop(pending_unlink_line_req_key, None)
                close_edit_process_line_dialog()
                st.toast(
                    "Part unlinked from PAAG element.",
                    icon=":material/check_circle:",
                )
                st.rerun()

        if st.session_state.get(pending_unlink_line_req_key):
            confirm_unlink_line_req_dialog()
        elif st.session_state.get(edit_line_dialog_key):
            edit_process_line_dialog()


elif tab_flow.open:
    with tab_flow:
        flow_col1, flow_col2 = st.columns([3, 1], vertical_alignment="bottom")
        with flow_col1:
            st.caption(
                "Visual left-to-right Process Flow Diagram mapped by Yamazumi pitch and sequence. "
                "Click any operation box to view its full details and paired parts."
            )
        with flow_col2:
            shape_choice = st.radio(
                "Block Shapes",
                options=["Functional Shapes", "Uniform Squares"],
                horizontal=True,
                key=f"pfd_shape_mode_{scenario_id}",
                help="Choose whether operations display functional symbology (Diamond for CTQ/Safety, Rounded for feeder handoff) or uniform square outlines.",
            )
        shape_mode = "uniform" if shape_choice == "Uniform Squares" else "functional"
        render_process_flow_diagram(
            project_id,
            scenario_id,
            key=f"process_flow_map_{scenario_id}",
            shape_mode=shape_mode,
        )


elif tab_slides.open:
    with tab_slides:
        all_scenario_pitches_df = _sort_pitches_by_address_df(
            yamazumi_pitches_for_scenario(project_id, scenario_id)
        )
        if not all_scenario_pitches_df.empty and "element_count" in all_scenario_pitches_df.columns:
            scenario_pitches_df = all_scenario_pitches_df.loc[
                pd.to_numeric(all_scenario_pitches_df["element_count"], errors="coerce").fillna(0) > 0
            ].copy()
        else:
            scenario_pitches_df = all_scenario_pitches_df
        pitch_options = [
            (str(row["id"]), f"{row['pitch_number']} — {row['pitch_name'] or 'Pitch'}")
            for _, row in scenario_pitches_df.iterrows()
        ]
        pitch_dict = dict(pitch_options)

        # Fishbone section hierarchy and pitch counts
        section_pitch_counts: dict[str, int] = {}
        for _, p_row in scenario_pitches_df.iterrows():
            s_id = str(p_row.get("section_id") or "").strip()
            section_pitch_counts[s_id] = section_pitch_counts.get(s_id, 0) + 1

        sec_filter_choices: list[tuple[str, str]] = [
            ("__ALL__", "All Fishbone Sections"),
        ]

        if not sections.empty:
            for _, s_row in sections.iterrows():
                s_id = str(s_row["id"])
                count = section_pitch_counts.get(s_id, 0)
                if count > 0:
                    sec_name = str(s_row.get("name") or "")
                    sec_filter_choices.append((s_id, sec_name))

        unassigned_count = section_pitch_counts.get("", 0)
        if unassigned_count > 0:
            sec_filter_choices.append(("__UNASSIGNED__", "Unassigned Pitches"))

        sec_filter_dict = dict(sec_filter_choices)
        sec_filter_key = f"paag_section_filter_{scenario_id}"
        current_sec_filter = str(st.session_state.get(sec_filter_key) or "__ALL__")
        if current_sec_filter not in sec_filter_dict:
            current_sec_filter = "__ALL__"
            st.session_state[sec_filter_key] = current_sec_filter

        # Filter pitches by section
        if current_sec_filter == "__ALL__":
            visible_pitches_df = scenario_pitches_df
        elif current_sec_filter == "__UNASSIGNED__":
            visible_pitches_df = scenario_pitches_df.loc[
                scenario_pitches_df["section_id"].isna() | (scenario_pitches_df["section_id"] == "")
            ]
        else:
            visible_pitches_df = scenario_pitches_df.loc[
                scenario_pitches_df["section_id"].astype(str) == current_sec_filter
            ]

        visible_pitch_options = [
            (str(row["id"]), f"{row['pitch_number']} — {row['pitch_name'] or 'Pitch'}")
            for _, row in visible_pitches_df.iterrows()
        ]
        visible_pitch_dict = dict(visible_pitch_options)

        selected_pitch_key = "selected_pitch_id"
        pitch_page_key = "pitch_page_num"

        qp_pitch = st.query_params.get("active_pitch")
        if qp_pitch and qp_pitch in pitch_dict:
            st.session_state[selected_pitch_key] = qp_pitch
            try:
                del st.query_params["active_pitch"]
            except Exception:
                pass

        selected_pitch_id = str(st.session_state.get(selected_pitch_key) or "").strip()

        if selected_pitch_id and selected_pitch_id in pitch_dict:
            if selected_pitch_id not in visible_pitch_dict:
                p_match = scenario_pitches_df.loc[scenario_pitches_df["id"].astype(str) == selected_pitch_id]
                if not p_match.empty:
                    pitch_sec = str(p_match.iloc[0].get("section_id") or "").strip()
                    if pitch_sec in sec_filter_dict:
                        current_sec_filter = pitch_sec
                    else:
                        current_sec_filter = "__ALL__"
                    st.session_state[sec_filter_key] = current_sec_filter

                    if current_sec_filter == "__ALL__":
                        visible_pitches_df = scenario_pitches_df
                    elif current_sec_filter == "__UNASSIGNED__":
                        visible_pitches_df = scenario_pitches_df.loc[
                            scenario_pitches_df["section_id"].isna() | (scenario_pitches_df["section_id"] == "")
                        ]
                    else:
                        visible_pitches_df = scenario_pitches_df.loc[
                            scenario_pitches_df["section_id"].astype(str) == current_sec_filter
                        ]
                    visible_pitch_options = [
                        (str(row["id"]), f"{row['pitch_number']} — {row['pitch_name'] or 'Pitch'}")
                        for _, row in visible_pitches_df.iterrows()
                    ]
                    visible_pitch_dict = dict(visible_pitch_options)


        # Auto-default selected pitch if none is selected
        if not selected_pitch_id or selected_pitch_id not in pitch_dict:
            if visible_pitch_options:
                selected_pitch_id = visible_pitch_options[0][0]
                st.session_state[selected_pitch_key] = selected_pitch_id
                st.session_state[pitch_page_key] = 1
            elif pitch_options:
                selected_pitch_id = pitch_options[0][0]
                st.session_state[selected_pitch_key] = selected_pitch_id
                st.session_state[pitch_page_key] = 1
            else:
                selected_pitch_id = ""
                st.session_state.pop(selected_pitch_key, None)

        if not pitch_options:
            st.info("No pitches defined for this planning scenario yet. Create pitches in the Yamazumi module to view PAAG slides.")
        elif not visible_pitch_options:
            st.info("No pitches match the selected Fishbone section.")

        if selected_pitch_id:
            try:
                pitch_summary = process_pitch_visual_summary(
                    project_id, scenario_id, selected_pitch_id
                )
            except ValueError as exc:
                st.session_state.pop(selected_pitch_key, None)
                st.session_state.pop(pitch_page_key, None)
                st.warning(str(exc))
            else:
                pitch_rows = pitch_summary["elements"]
                current_page = clamp_page(
                    st.session_state.get(pitch_page_key, 1), len(pitch_rows)
                )
                st.session_state[pitch_page_key] = current_page
                total_pages = max(page_count(len(pitch_rows)), pitch_summary.get("slide_count", 1))

                # Anchor for scroll
                st.html("""
                <div id="process-pitch-visual-summary"></div>
                <style>
                /* PAAG visualizer toolbar button styling: prevent text wrapping and vertical squishing */
                div[data-testid="stHorizontalBlock"] button[kind="secondary"],
                div[data-testid="stHorizontalBlock"] button {
                    white-space: nowrap !important;
                }
                div[data-testid="stHorizontalBlock"] button p {
                    white-space: nowrap !important;
                    overflow: hidden !important;
                    text-overflow: ellipsis !important;
                }
                /* Alerts button: orange background fill */
                div[class*="st-key-btn_alerts_"] button {
                    background-color: #ea580c !important;
                    border-color: #ea580c !important;
                    color: #ffffff !important;
                }
                div[class*="st-key-btn_alerts_"] button:hover {
                    background-color: #c2410c !important;
                    border-color: #c2410c !important;
                    color: #ffffff !important;
                }
                div[class*="st-key-btn_alerts_"] button p,
                div[class*="st-key-btn_alerts_"] button span {
                    color: #ffffff !important;
                }
                /* Delete buttons: red background fill */
                div[class*="st-key-destructive_"] button,
                div[class*="st-key-btn_del_"] button,
                div[class*="st-key-conf_del_"] button {
                    background-color: #c62828 !important;
                    border-color: #c62828 !important;
                    color: #ffffff !important;
                }
                div[class*="st-key-destructive_"] button:hover,
                div[class*="st-key-btn_del_"] button:hover,
                div[class*="st-key-conf_del_"] button:hover {
                    background-color: #a71919 !important;
                    border-color: #a71919 !important;
                    color: #ffffff !important;
                }
                div[class*="st-key-destructive_"] button p,
                div[class*="st-key-destructive_"] button span,
                div[class*="st-key-btn_del_"] button p,
                div[class*="st-key-btn_del_"] button span,
                div[class*="st-key-conf_del_"] button p,
                div[class*="st-key-conf_del_"] button span {
                    color: #ffffff !important;
                }
                </style>
                """)

                # Responsive toolbar: selectors + wrapping navigation & action buttons
                pitch_visual_coverage = scenario_pitch_visual_coverage(project_id, scenario_id)
                pitch_status_entries = [
                    {
                        "label": lbl,
                        "status": str((pitch_visual_coverage.get(pid) or {}).get("status") or "white"),
                    }
                    for pid, lbl in pitch_options
                ]
                selected_pitch_status = str(
                    (pitch_visual_coverage.get(selected_pitch_id) or {}).get("status") or "white"
                )
                if selected_pitch_status == "green":
                    sel_bg, sel_border, sel_fg = "#dcfce7", "#16a34a", "#14532d"
                elif selected_pitch_status == "yellow":
                    sel_bg, sel_border, sel_fg = "#fef9c3", "#eab308", "#713f12"
                else:
                    sel_bg, sel_border, sel_fg = "#ffffff", "#cbd5e1", "#1e293b"

                pitch_status_json = json.dumps(pitch_status_entries)
                st.html(
                    f"""
                    <div style="display:none;" aria-hidden="true"></div>
                    <style>
                    div[class*="st-key-pitch_active_select_"] div[data-baseweb="select"] > div {{
                        background-color: {sel_bg} !important;
                        border-color: {sel_border} !important;
                        color: {sel_fg} !important;
                    }}
                    div[class*="st-key-pitch_active_select_"] div[data-baseweb="select"] > div * {{
                        color: {sel_fg} !important;
                    }}
                    </style>
                    <script>
                    (function() {{
                        const ENTRIES = {pitch_status_json};
                        const OPTION_SELECTOR = '[role="option"], [data-baseweb="menu"] li';
                        const STYLE_ID = "paag-pitch-visual-status-options-style";
                        const CSS_TEXT = [
                            '[role="option"][data-paag-pitch-status="green"],',
                            '[data-baseweb="menu"] li[data-paag-pitch-status="green"] {{',
                            '    background: #dcfce7 !important;',
                            '    background-color: #dcfce7 !important;',
                            '    color: #14532d !important;',
                            '    border-left: 4px solid #16a34a !important;',
                            '}}',
                            '[role="option"][data-paag-pitch-status="green"]:hover,',
                            '[role="option"][data-paag-pitch-status="green"][aria-selected="true"],',
                            '[role="option"][data-paag-pitch-status="green"][data-highlighted="true"],',
                            '[data-baseweb="menu"] li[data-paag-pitch-status="green"]:hover,',
                            '[data-baseweb="menu"] li[data-paag-pitch-status="green"][aria-selected="true"] {{',
                            '    background: #bbf7d0 !important;',
                            '    background-color: #bbf7d0 !important;',
                            '    color: #14532d !important;',
                            '}}',
                            '[role="option"][data-paag-pitch-status="green"] [data-item-hl],',
                            '[role="option"][data-paag-pitch-status="green"] *,',
                            '[data-baseweb="menu"] li[data-paag-pitch-status="green"] * {{',
                            '    color: #14532d !important;',
                            '    background: transparent !important;',
                            '    background-color: transparent !important;',
                            '}}',
                            '[role="option"][data-paag-pitch-status="yellow"],',
                            '[data-baseweb="menu"] li[data-paag-pitch-status="yellow"] {{',
                            '    background: #fef9c3 !important;',
                            '    background-color: #fef9c3 !important;',
                            '    color: #713f12 !important;',
                            '    border-left: 4px solid #eab308 !important;',
                            '}}',
                            '[role="option"][data-paag-pitch-status="yellow"]:hover,',
                            '[role="option"][data-paag-pitch-status="yellow"][aria-selected="true"],',
                            '[role="option"][data-paag-pitch-status="yellow"][data-highlighted="true"],',
                            '[data-baseweb="menu"] li[data-paag-pitch-status="yellow"]:hover,',
                            '[data-baseweb="menu"] li[data-paag-pitch-status="yellow"][aria-selected="true"] {{',
                            '    background: #fef08a !important;',
                            '    background-color: #fef08a !important;',
                            '    color: #713f12 !important;',
                            '}}',
                            '[role="option"][data-paag-pitch-status="yellow"] [data-item-hl],',
                            '[role="option"][data-paag-pitch-status="yellow"] *,',
                            '[data-baseweb="menu"] li[data-paag-pitch-status="yellow"] * {{',
                            '    color: #713f12 !important;',
                            '    background: transparent !important;',
                            '    background-color: transparent !important;',
                            '}}',
                            '[role="option"][data-paag-pitch-status="white"],',
                            '[data-baseweb="menu"] li[data-paag-pitch-status="white"] {{',
                            '    background: #ffffff !important;',
                            '    background-color: #ffffff !important;',
                            '    color: #1e293b !important;',
                            '    border-left: 4px solid transparent !important;',
                            '}}',
                            '[role="option"][data-paag-pitch-status="white"]:hover,',
                            '[role="option"][data-paag-pitch-status="white"][aria-selected="true"],',
                            '[role="option"][data-paag-pitch-status="white"][data-highlighted="true"],',
                            '[data-baseweb="menu"] li[data-paag-pitch-status="white"]:hover,',
                            '[data-baseweb="menu"] li[data-paag-pitch-status="white"][aria-selected="true"] {{',
                            '    background: #f1f5f9 !important;',
                            '    background-color: #f1f5f9 !important;',
                            '    color: #0f172a !important;',
                            '}}',
                            '[role="option"][data-paag-pitch-status="white"] [data-item-hl],',
                            '[role="option"][data-paag-pitch-status="white"] *,',
                            '[data-baseweb="menu"] li[data-paag-pitch-status="white"] * {{',
                            '    color: #1e293b !important;',
                            '    background: transparent !important;',
                            '    background-color: transparent !important;',
                            '}}'
                        ].join(" ");

                        const rootDoc = (window.parent && window.parent.document) ? window.parent.document : document;
                        const rootWin = (window.parent && window.parent.document) ? window.parent : window;

                        if (rootDoc.head) {{
                            let styleEl = rootDoc.getElementById(STYLE_ID);
                            if (!styleEl) {{
                                styleEl = rootDoc.createElement("style");
                                styleEl.id = STYLE_ID;
                                rootDoc.head.appendChild(styleEl);
                            }}
                            if (styleEl.textContent !== CSS_TEXT) {{
                                styleEl.textContent = CSS_TEXT;
                            }}
                        }}

                        rootWin.__paagPitchVisualStatusEntries = ENTRIES;

                        function resolveOptionStatus(text) {{
                            const trimmed = (text || "").trim();
                            if (!trimmed) return "";
                            const entries = rootWin.__paagPitchVisualStatusEntries || [];
                            for (let i = 0; i < entries.length; i++) {{
                                const lbl = entries[i].label || "";
                                if (lbl && (trimmed === lbl || trimmed.indexOf(lbl + " · Slide ") === 0)) {{
                                    return entries[i].status || "white";
                                }}
                            }}
                            return "";
                        }}

                        function syncPitchVisualStatusOptions() {{
                            const options = rootDoc.querySelectorAll(OPTION_SELECTOR);
                            options.forEach(function(opt) {{
                                const status = resolveOptionStatus(opt.textContent || "");
                                if (status) {{
                                    if (opt.getAttribute("data-paag-pitch-status") !== status) {{
                                        opt.setAttribute("data-paag-pitch-status", status);
                                    }}
                                }} else if (opt.hasAttribute("data-paag-pitch-status")) {{
                                    opt.removeAttribute("data-paag-pitch-status");
                                }}
                            }});
                        }}

                        rootWin.__paagSyncPitchVisualStatusOptions = syncPitchVisualStatusOptions;
                        syncPitchVisualStatusOptions();

                        if (!rootWin.__paagPitchVisualStatusObserverInstalled) {{
                            rootWin.__paagPitchVisualStatusObserverInstalled = true;
                            const observer = new MutationObserver(function() {{
                                if (rootWin.__paagSyncPitchVisualStatusOptions) {{
                                    rootWin.__paagSyncPitchVisualStatusOptions();
                                }}
                            }});
                            if (rootDoc.body) {{
                                observer.observe(rootDoc.body, {{ childList: true, subtree: true }});
                            }}
                            ["click", "pointerdown", "pointermove", "keydown", "scroll"].forEach(function(evtName) {{
                                rootWin.addEventListener(evtName, function() {{
                                    if (rootWin.__paagSyncPitchVisualStatusOptions) {{
                                        rootWin.__paagSyncPitchVisualStatusOptions();
                                    }}
                                }}, true);
                            }});
                        }}
                    }})();
                    </script>
                    """,
                    unsafe_allow_javascript=True,
                )

                vis_pids = list(visible_pitch_dict.keys())
                curr_p_idx = vis_pids.index(selected_pitch_id) if selected_pitch_id in vis_pids else 0
                is_first_nav = (curr_p_idx <= 0 and current_page <= 1)
                is_last_nav = (curr_p_idx >= len(vis_pids) - 1 and current_page >= total_pages)

                nav_col_sec, nav_col_p = st.columns([1.5, 2.5], vertical_alignment="center")
                with nav_col_sec:
                    curr_sec_idx = list(sec_filter_dict.keys()).index(current_sec_filter) if current_sec_filter in sec_filter_dict else 0
                    new_sec = st.selectbox(
                        "Fishbone Section",
                        options=list(sec_filter_dict.keys()),
                        index=curr_sec_idx,
                        format_func=lambda sid: sec_filter_dict.get(sid, sid),
                        key=f"sec_active_select_{scenario_id}",
                        label_visibility="collapsed",
                        help="Filter pitches by Fishbone Section hierarchy",
                    )
                    if new_sec != current_sec_filter:
                        st.session_state[sec_filter_key] = new_sec
                        if new_sec == "__ALL__":
                            next_df = scenario_pitches_df
                        elif new_sec == "__UNASSIGNED__":
                            next_df = scenario_pitches_df.loc[
                                scenario_pitches_df["section_id"].isna() | (scenario_pitches_df["section_id"] == "")
                            ]
                        else:
                            next_df = scenario_pitches_df.loc[scenario_pitches_df["section_id"].astype(str) == new_sec]
                        if not next_df.empty:
                            st.session_state[selected_pitch_key] = str(next_df.iloc[0]["id"])
                            st.session_state[f"pitch_active_select_{scenario_id}"] = str(next_df.iloc[0]["id"])
                        st.session_state[pitch_page_key] = 1
                        st.rerun()

                with nav_col_p:
                    def _format_pitch_label(pid: str) -> str:
                        lbl = visible_pitch_dict.get(pid, pid)
                        if pid == selected_pitch_id and total_pages > 1:
                            return f"{lbl} · Slide {current_page}/{total_pages}"
                        return lbl

                    new_sel = st.selectbox(
                        "Pitch",
                        options=vis_pids,
                        index=curr_p_idx,
                        format_func=_format_pitch_label,
                        key=f"pitch_active_select_{scenario_id}",
                        label_visibility="collapsed",
                        help="Select pitch (Green = visual aid tied to every work element; Yellow = visual aid added, some work elements untagged; White = not started)",
                    )
                    if new_sel != selected_pitch_id:
                        st.session_state[selected_pitch_key] = new_sel
                        st.session_state[pitch_page_key] = 1
                        st.rerun()

                slide_action_bar = st.container(horizontal=True, vertical_alignment="center")
                if slide_action_bar.button(
                    "Back",
                    icon=":material/arrow_back:",
                    disabled=is_first_nav,
                    help=f"Previous slide / pitch (Slide {current_page}/{total_pages})" if total_pages > 1 else "Previous pitch",
                    key=f"pitch_visual_back_{scenario_id}_{selected_pitch_id}",
                ):
                    if current_page > 1:
                        st.session_state[pitch_page_key] = current_page - 1
                    else:
                        if curr_p_idx > 0:
                            prev_pid = vis_pids[curr_p_idx - 1]
                            st.session_state[selected_pitch_key] = prev_pid
                            st.session_state[f"pitch_active_select_{scenario_id}"] = prev_pid
                            try:
                                prev_sum = process_pitch_visual_summary(project_id, scenario_id, prev_pid)
                                prev_tot = max(page_count(len(prev_sum.get("elements", []))), prev_sum.get("slide_count", 1), 1)
                            except Exception:
                                prev_tot = 1
                            st.session_state[pitch_page_key] = prev_tot
                    st.rerun()

                if slide_action_bar.button(
                    "Next",
                    icon=":material/arrow_forward:",
                    disabled=is_last_nav,
                    help=f"Next slide / pitch (Slide {current_page}/{total_pages})" if total_pages > 1 else "Next pitch",
                    key=f"pitch_visual_next_{scenario_id}_{selected_pitch_id}",
                ):
                    if current_page < total_pages:
                        st.session_state[pitch_page_key] = current_page + 1
                    else:
                        if curr_p_idx < len(vis_pids) - 1:
                            next_pid = vis_pids[curr_p_idx + 1]
                            st.session_state[selected_pitch_key] = next_pid
                            st.session_state[f"pitch_active_select_{scenario_id}"] = next_pid
                            st.session_state[pitch_page_key] = 1
                    st.rerun()

                if slide_action_bar.button("Present", icon=":material/slideshow:", key=f"btn_present_{scenario_id}", help="Full-screen PowerPoint presentation mode"):
                    st.session_state[f"paag_present_active_{scenario_id}"] = True
                    st.session_state[f"pres_pitch_id_{scenario_id}"] = selected_pitch_id
                    st.session_state[f"pres_page_num_{scenario_id}"] = current_page
                    st.rerun()

                if slide_action_bar.button("Print", icon=":material/print:", key=f"btn_print_{scenario_id}", help="Print or export 8.5x11 or 11x17 landscape slide"):
                    st.session_state[f"paag_print_active_{scenario_id}"] = True
                    st.rerun()

                alerts_cnt = sum(len(v) for v in pitch_summary.get("alerts", {}).values())
                a_label = f"Alerts ({alerts_cnt})" if alerts_cnt > 0 else "Alerts"
                if slide_action_bar.button(a_label, icon=":material/notification_important:", key=f"btn_alerts_{scenario_id}", help="View functional alerts detail"):
                    alerts_detail_dialog(
                        pitch_summary.get("alerts", {}),
                        project_id=project_id,
                        scenario_id=scenario_id,
                        pitch_id=selected_pitch_id,
                    )

                tools_cnt = len(pitch_summary.get("tools", []))
                t_label = f"Tools ({tools_cnt})" if tools_cnt > 0 else "Tools"
                if slide_action_bar.button(t_label, icon=":material/construction:", key=f"btn_tools_{scenario_id}", help="View tools and equipment details"):
                    tools_detail_dialog(
                        pitch_summary.get("tools", []),
                        project_id=project_id,
                        scenario_id=scenario_id,
                        pitch_id=selected_pitch_id,
                        pitch_summary=pitch_summary,
                    )

                if slide_action_bar.button(
                    "+ Tie Tool",
                    icon=":material/build:",
                    key=f"btn_tie_tool_slide_{scenario_id}",
                    help="Tie a tool to a work element on this pitch",
                ):
                    tie_tool_slide_dialog(
                        project_id=project_id,
                        scenario_id=scenario_id,
                        pitch_id=selected_pitch_id,
                        pitch_summary=pitch_summary,
                    )


                slide_action_bar.link_button(
                    "Open Plan",
                    url=build_page_url("process", query_params={"paag_tab": "Process Plan"}),
                    icon=":material/open_in_new:",
                    help="Open Process Plan in a separate browser window or tab to edit elements alongside slides",
                )

                if st.session_state.get(f"paag_present_active_{scenario_id}"):
                    presentation_mode_dialog(
                        project_id=project_id,
                        scenario_id=scenario_id,
                        scenario_name=str(scenario["name"]),
                        project_name=str(pitch_summary.get("project_name", "")),
                        pitch_options=visible_pitch_options if visible_pitch_options else pitch_options,
                        model_labels=model_labels,
                    )

                if st.session_state.get(f"paag_print_active_{scenario_id}"):
                    print_slide_dialog(
                        pitch_summary=pitch_summary,
                        active_page_rows=pitch_rows,
                        current_page=current_page,
                        total_pages=total_pages,
                        scenario_name=str(scenario["name"]),
                        project_name=str(pitch_summary.get("project_name", "")),
                        project_id=project_id,
                        scenario_id=scenario_id,
                        pitch_options=pitch_options,
                        selected_pitch_id=selected_pitch_id,
                        model_labels=model_labels,
                        scenario_pitches_df=scenario_pitches_df,
                        sections=sections,
                        section_labels=section_labels,
                        active_section_filter_id=current_sec_filter,
                    )

                # Model applicability resolution for elements
                active_page_rows = page_elements(pitch_rows, current_page)
                for row in active_page_rows:
                    row["models"] = [
                        "All models" if model.casefold() in {"all", "all models"}
                        else model_labels.get(model, model)
                        for model in (split_filter_values(row.get("model_applicability")) or ["All"])
                    ]

                # Render 16:9 Landscape Canvas
                st.html(
                    render_pitch_canvas(
                        pitch_summary,
                        active_page_rows,
                        scenario_name=str(scenario["name"]),
                        project_name=str(pitch_summary.get("project_name", "")),
                        page_num=current_page,
                        total_pages=total_pages,
                    ),
                    unsafe_allow_javascript=True,
                )

                if st.session_state.pop(f"pitch_visual_scroll_{scenario_id}", False):
                    st.html(
                        """<script>
                        const target = window.parent.document.getElementById('process-pitch-visual-summary');
                        if (target) target.scrollIntoView({behavior: 'smooth', block: 'start'});
                        </script>"""
                    )

                # Visual Aids Management Section
                with st.expander("Process Visual Aids Management (Photos & Videos)", expanded=True):
                    st.markdown("Add photos or demonstration videos (`.mp4`, `.mov`, `.webm`) and tag them to work elements for this pitch.")

                    element_options = [
                        (
                            str(el.get("work_element_id") or el.get("id")),
                            f"{idx + 1} · {el.get('op_id') + ' — ' if el.get('op_id') and el.get('op_id') != 'Yamazumi link required' else ''}{el.get('operation') or el.get('yamazumi_description') or 'Work Step'}"
                        )
                        for idx, el in enumerate(pitch_rows)
                        if el.get("work_element_id") or el.get("id")
                    ]
                    tag_dict_elem = dict(element_options)
                    for _ms_key in (
                        f"select_tags_visual_{selected_pitch_id}",
                        f"select_link_tags_{selected_pitch_id}",
                    ):
                        if _ms_key in st.session_state and isinstance(st.session_state[_ms_key], list):
                            st.session_state[_ms_key] = [
                                v for v in st.session_state[_ms_key] if v in tag_dict_elem
                            ]

                    # Upload / Paste / Link Visual Aid Container
                    with st.container(border=True):
                        vis_tab_file, vis_tab_link, vis_tab_parts = st.tabs(["Upload / Clipboard", "Web Link / URL", "Parts Catalog"])
                        with vis_tab_file:
                            up_col1, up_col2 = st.columns([1.5, 1])
                            with up_col1:
                                uploaded_media = st.file_uploader(
                                    "Upload photo, video, or 3D CAD STEP",
                                    type=["png", "jpg", "jpeg", "webp", "mp4", "mov", "webm", "step", "stp"],
                                    key=f"file_upload_visual_{selected_pitch_id}",
                                    help="Photos: max 10 MB (PNG, JPG, WEBP) • Videos: max 25 MB (MP4, MOV, WEBM) • 3D CAD: max 50 MB (STEP, STP)",
                                )
                                st.caption("Photos: max **10 MB** • Videos: max **25 MB** • 3D CAD: max **50 MB** (STEP, STP)")

                                st.caption("Or take a photo with your camera / paste a screenshot (Win+Shift+S / Ctrl+V):")
                                pasted = clipboard_image(key=f"paste_media_{selected_pitch_id}")

                                aid_caption = st.text_input(
                                    "Caption / Yellow Callout Note",
                                    key=f"input_caption_visual_{selected_pitch_id}",
                                    placeholder="e.g. Ensure bracket is flush against locator pin before torquing",
                                )
                            with up_col2:
                                tagged_element_ids = st.multiselect(
                                    "Tag to Work Elements",
                                    options=list(tag_dict_elem.keys()),
                                    format_func=lambda tid: tag_dict_elem.get(tid, tid),
                                    key=f"select_tags_visual_{selected_pitch_id}",
                                    help="Tags link this visual aid to specific PAAG work elements on this pitch.",
                                )
                                aid_sequence = st.number_input(
                                    "Sequence Order",
                                    min_value=1,
                                    value=10,
                                    step=5,
                                    key=f"input_seq_visual_{selected_pitch_id}",
                                )

                            # Manage staged image if user uploads an image or pastes from clipboard
                            staged_key = f"staged_media_{selected_pitch_id}"
                            last_up_hash_key = f"_last_visual_up_hash_{selected_pitch_id}"
                            consumed_up_hash_key = f"_consumed_visual_up_hash_{selected_pitch_id}"
                            current_staged = st.session_state.get(staged_key)

                            # Check clipboard paste first
                            pasted_payload = getattr(pasted, "image", None)
                            if pasted_payload:
                                try:
                                    primary_image = decode_clipboard_image(pasted_payload, max_bytes=10 * 1024 * 1024)
                                    clip_bytes = primary_image["bytes"]
                                    clip_hash = hashlib.sha256(clip_bytes).hexdigest()
                                    if not current_staged or current_staged.get("hash") != clip_hash:
                                        st.session_state[staged_key] = {
                                            "source": "clipboard",
                                            "hash": clip_hash,
                                            "filename": primary_image["name"],
                                            "original_bytes": clip_bytes,
                                            "composite_bytes": clip_bytes,
                                            "mime_type": primary_image["mime_type"],
                                            "annotations_json": "",
                                        }
                                        current_staged = st.session_state[staged_key]
                                except Exception as exc:
                                    st.error(str(exc))

                            # Check file upload (if image)
                            if uploaded_media:
                                up_suffix = Path(uploaded_media.name).suffix.lower()
                                if up_suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                                    up_bytes = uploaded_media.getvalue()
                                    up_hash = hashlib.sha256(up_bytes).hexdigest()
                                    last_up_hash = st.session_state.get(last_up_hash_key)
                                    consumed_up_hash = st.session_state.get(consumed_up_hash_key)
                                    is_new_upload = up_hash != last_up_hash
                                    if is_new_upload:
                                        st.session_state.pop(consumed_up_hash_key, None)
                                        consumed_up_hash = None
                                    if up_hash != consumed_up_hash and (is_new_upload or not current_staged):
                                        up_mime = "image/png" if up_suffix == ".png" else "image/webp" if up_suffix == ".webp" else "image/jpeg"
                                        st.session_state[staged_key] = {
                                            "source": "upload",
                                            "hash": up_hash,
                                            "filename": uploaded_media.name,
                                            "original_bytes": up_bytes,
                                            "composite_bytes": up_bytes,
                                            "mime_type": up_mime,
                                            "annotations_json": "",
                                        }
                                        current_staged = st.session_state[staged_key]
                                    st.session_state[last_up_hash_key] = up_hash
                                elif up_suffix in {".step", ".stp"}:
                                    size_mb = len(uploaded_media.getvalue()) / (1024 * 1024)
                                    st.info(f":material/view_in_ar: **3D CAD Model Ready:** `{uploaded_media.name}` ({size_mb:.1f} MB)")
                            else:
                                st.session_state.pop(last_up_hash_key, None)
                                st.session_state.pop(consumed_up_hash_key, None)

                            # Show preview card if an image is staged
                            if current_staged and current_staged.get("composite_bytes"):
                                with st.container(border=True):
                                    st.markdown(f"**Image Ready:** `{current_staged.get('filename')}`")
                                    sp1, sp2 = st.columns([1, 2.5])
                                    with sp1:
                                        st.image(current_staged["composite_bytes"], width=150)
                                    with sp2:
                                        has_ann = bool(current_staged.get("annotations_json"))
                                        if has_ann:
                                            st.success("Markup / crop / rotation applied", icon=":material/draw:")
                                        else:
                                            st.caption("No annotations added yet. Click below to crop, rotate 90°, or add arrows, focus boxes, callouts, or step numbers.")
                                        staged_act_bar = st.container(horizontal=True)
                                        if staged_act_bar.button("Annotate / Add Shapes", icon=":material/draw:", key=f"btn_ann_staged_{selected_pitch_id}", type="secondary"):
                                            st.session_state[f"paag_annotate_staged_{scenario_id}"] = selected_pitch_id
                                            st.session_state.pop(f"paag_annotate_media_{scenario_id}", None)
                                        if staged_act_bar.button("Delete", icon=":material/delete:", key=f"destructive_discard_staged_{selected_pitch_id}"):
                                            discard_staged_media_dialog(selected_pitch_id)

                            submit_add = st.button("Add Visual Aid", icon=":material/add_photo_alternate:", type="primary", key=f"btn_add_visual_{selected_pitch_id}")
                            if submit_add:
                                if current_staged and current_staged.get("composite_bytes"):
                                    try:
                                        save_pitch_visual_media(
                                            project_id=project_id,
                                            scenario_id=scenario_id,
                                            pitch_id=selected_pitch_id,
                                            filename=current_staged["filename"],
                                            file_bytes=current_staged["composite_bytes"],
                                            original_file_bytes=current_staged["original_bytes"],
                                            annotations_json=current_staged.get("annotations_json", ""),
                                            caption=aid_caption or (current_staged["filename"] if "screenshot" not in current_staged["filename"].lower() else "Visual Aid"),
                                            tagged_work_element_ids=tagged_element_ids or [],
                                            sequence=aid_sequence or 10,
                                            current_editor=st.session_state.get("current_editor", ""),
                                        )
                                        record_audit_event(
                                            project_id,
                                            "Process",
                                            "Upload visual aid",
                                            1,
                                            st.session_state.get("current_editor", ""),
                                            {
                                                "pitch_id": selected_pitch_id,
                                                "filename": current_staged["filename"],
                                                "caption": aid_caption,
                                                "annotated": bool(current_staged.get("annotations_json")),
                                            },
                                        )
                                        if current_staged.get("source") == "upload" and current_staged.get("hash"):
                                            st.session_state[consumed_up_hash_key] = current_staged["hash"]
                                        st.session_state.pop(staged_key, None)
                                        st.toast("Visual aid saved!", icon=":material/check_circle:")
                                        st.rerun()
                                    except Exception as exc:
                                        st.error(str(exc))
                                elif uploaded_media:
                                    try:
                                        file_bytes = uploaded_media.getvalue()
                                        save_pitch_visual_media(
                                            project_id=project_id,
                                            scenario_id=scenario_id,
                                            pitch_id=selected_pitch_id,
                                            filename=uploaded_media.name,
                                            file_bytes=file_bytes,
                                            caption=aid_caption,
                                            tagged_work_element_ids=tagged_element_ids or [],
                                            sequence=aid_sequence or 10,
                                            current_editor=st.session_state.get("current_editor", ""),
                                        )
                                        record_audit_event(
                                            project_id,
                                            "Process",
                                            "Upload visual aid",
                                            1,
                                            st.session_state.get("current_editor", ""),
                                            {
                                                "pitch_id": selected_pitch_id,
                                                "filename": uploaded_media.name,
                                                "caption": aid_caption,
                                            },
                                        )
                                        st.toast("Visual aid saved!", icon=":material/check_circle:")
                                        st.rerun()
                                    except Exception as exc:
                                        st.error(str(exc))
                                else:
                                    st.error("Please choose an image or video file to upload, or paste a screenshot using the button above.")

                        with vis_tab_link:
                            link_col1, link_col2 = st.columns([1.5, 1])
                            with link_col1:
                                link_url_val = st.text_input(
                                    "Web Link URL",
                                    placeholder="https://sharepoint... or https://windchill... or web drawing/video URL",
                                    key=f"input_url_visual_{selected_pitch_id}",
                                    help="Attach a web link to a SharePoint document, CAD drawing, online SOP, or web media.",
                                )
                                link_caption_val = st.text_input(
                                    "Caption / Yellow Callout Note",
                                    key=f"input_link_cap_visual_{selected_pitch_id}",
                                    placeholder="e.g. Workstation Standard Operating Procedure",
                                )
                            with link_col2:
                                link_tagged_ids = st.multiselect(
                                    "Tag to Work Elements",
                                    options=list(tag_dict_elem.keys()),
                                    format_func=lambda tid: tag_dict_elem.get(tid, tid),
                                    key=f"select_link_tags_{selected_pitch_id}",
                                    help="Tags link this web visual aid to specific PAAG work elements on this pitch.",
                                )
                                link_seq_val = st.number_input(
                                    "Sequence Order",
                                    min_value=1,
                                    value=10,
                                    step=5,
                                    key=f"input_link_seq_{selected_pitch_id}",
                                )
                            if st.button("Add Web Link Visual Aid", icon=":material/link:", type="primary", key=f"btn_add_link_visual_{selected_pitch_id}"):
                                clean_link_url = str(link_url_val or "").strip()
                                if not clean_link_url.startswith(("http://", "https://")):
                                    st.error("Please enter a valid web URL starting with http:// or https://")
                                else:
                                    try:
                                        save_pitch_visual_media_url(
                                            project_id=project_id,
                                            scenario_id=scenario_id,
                                            pitch_id=selected_pitch_id,
                                            url=clean_link_url,
                                            caption=link_caption_val or "Web Document Link",
                                            tagged_work_element_ids=link_tagged_ids or [],
                                            sequence=link_seq_val or 10,
                                            current_editor=st.session_state.get("current_editor", ""),
                                        )
                                        record_audit_event(
                                            project_id,
                                            "Process",
                                            "Add visual aid link",
                                            1,
                                            st.session_state.get("current_editor", ""),
                                            {
                                                "pitch_id": selected_pitch_id,
                                                "url": clean_link_url,
                                                "caption": link_caption_val,
                                            },
                                        )
                                        st.toast("Web link visual aid saved!", icon=":material/check_circle:")
                                        st.rerun()
                                    except Exception as exc:
                                        st.error(str(exc))

                        with vis_tab_parts:
                            catalog_photo_parts = catalog_part_photos_for_pitch(
                                project_id, scenario_id, selected_pitch_id
                            )
                            if not catalog_photo_parts:
                                st.info(
                                    "No photos found in the Parts Catalog yet. Upload or paste part photos in the **Parts Catalog** module to pull them into PAAG slides."
                                )
                            else:
                                pitch_only_parts = [
                                    item for item in catalog_photo_parts if item.get("on_pitch")
                                ]
                                filtered_catalog_parts = catalog_photo_parts
                                if pitch_only_parts and len(pitch_only_parts) < len(catalog_photo_parts):
                                    scope_choice = st.radio(
                                        "Parts Catalog scope",
                                        ["All Parts Catalog with photos", "Parts on this pitch only"],
                                        horizontal=True,
                                        key=f"radio_part_photo_scope_{selected_pitch_id}",
                                    )
                                    if scope_choice == "Parts on this pitch only":
                                        filtered_catalog_parts = pitch_only_parts

                                part_by_id = {
                                    item["part_id"]: item for item in filtered_catalog_parts
                                }
                                part_option_ids = list(part_by_id.keys())

                                def _format_catalog_part_option(pid: str) -> str:
                                    p_item = part_by_id.get(pid, {})
                                    p_num = str(p_item.get("part_number") or "").strip()
                                    p_desc = str(
                                        p_item.get("description")
                                        or p_item.get("factory_nickname")
                                        or ""
                                    ).strip()
                                    prefix = "📌 [On this pitch] " if p_item.get("on_pitch") else ""
                                    view_cnt = len(p_item.get("views") or [])
                                    view_suffix = f" ({view_cnt} photos)" if view_cnt > 1 else ""
                                    return (
                                        f"{prefix}{p_num} — {p_desc}{view_suffix}"
                                        if p_desc
                                        else f"{prefix}{p_num}{view_suffix}"
                                    )

                                pc_col1, pc_col2 = st.columns([1.5, 1])
                                with pc_col1:
                                    selected_catalog_part_id = st.selectbox(
                                        "Select part from Parts Catalog",
                                        options=part_option_ids,
                                        format_func=_format_catalog_part_option,
                                        key=f"select_catalog_part_visual_{selected_pitch_id}",
                                        help="Choose any part in the Parts Catalog that has a primary or supplemental photo.",
                                    )
                                    active_part_item = part_by_id.get(selected_catalog_part_id, {})
                                    part_views = active_part_item.get("views") or []
                                    view_by_id = {v["view_id"]: v for v in part_views}
                                    if len(part_views) > 1:
                                        selected_view_id = st.selectbox(
                                            "Part photo view",
                                            options=list(view_by_id.keys()),
                                            format_func=lambda vid: view_by_id.get(vid, {}).get("view_label", vid),
                                            key=f"select_catalog_part_view_{selected_pitch_id}_{selected_catalog_part_id}",
                                            help="Choose between the Primary Image and any Additional views stored on this part.",
                                        )
                                    else:
                                        selected_view_id = part_views[0]["view_id"] if part_views else ""
                                        if part_views:
                                            st.caption(f"Photo source: **{part_views[0].get('view_label', 'Primary Image')}**")

                                    active_view = view_by_id.get(selected_view_id, part_views[0] if part_views else {})
                                    default_part_caption = str(active_view.get("caption") or "").strip()
                                    part_aid_caption = st.text_input(
                                        "Caption / Yellow Callout Note",
                                        value=default_part_caption,
                                        key=f"input_part_cap_visual_{selected_pitch_id}_{selected_catalog_part_id}_{selected_view_id}",
                                        placeholder="e.g. Verify part orientation and mating surface before fastening",
                                    )
                                    preview_path = str(active_view.get("image_path") or "").strip()
                                    if preview_path:
                                        if preview_path.startswith(("http://", "https://")):
                                            st.image(preview_path, width=180)
                                        else:
                                            st.image(
                                                cached_image_bytes(preview_path, max_dim=360) or preview_path,
                                                width=180,
                                            )

                                with pc_col2:
                                    default_linked_tags = [
                                        wid
                                        for wid in (active_part_item.get("linked_work_element_ids") or [])
                                        if wid in tag_dict_elem
                                    ]
                                    _part_ms_key = f"select_part_tags_visual_{selected_pitch_id}_{selected_catalog_part_id}"
                                    if _part_ms_key in st.session_state and isinstance(st.session_state[_part_ms_key], list):
                                        st.session_state[_part_ms_key] = [
                                            v for v in st.session_state[_part_ms_key] if v in tag_dict_elem
                                        ]
                                    part_tagged_ids = st.multiselect(
                                        "Tag to Work Elements",
                                        options=list(tag_dict_elem.keys()),
                                        default=default_linked_tags,
                                        format_func=lambda tid: tag_dict_elem.get(tid, tid),
                                        key=_part_ms_key,
                                        help="Tags link this Parts Catalog photo to specific PAAG work elements on this pitch.",
                                    )
                                    part_seq_val = st.number_input(
                                        "Sequence Order",
                                        min_value=1,
                                        value=10,
                                        step=5,
                                        key=f"input_part_seq_visual_{selected_pitch_id}",
                                    )

                                if st.button(
                                    "Add Part Photo as Visual Aid",
                                    icon=":material/add_photo_alternate:",
                                    type="primary",
                                    key=f"btn_add_part_visual_{selected_pitch_id}",
                                ):
                                    try:
                                        saved_media = copy_part_photo_to_pitch_visual_media(
                                            project_id=project_id,
                                            scenario_id=scenario_id,
                                            pitch_id=selected_pitch_id,
                                            part_id=selected_catalog_part_id,
                                            view_id=selected_view_id,
                                            caption=part_aid_caption,
                                            tagged_work_element_ids=part_tagged_ids or [],
                                            sequence=int(part_seq_val or 10),
                                            current_editor=st.session_state.get("current_editor", ""),
                                        )
                                        record_audit_event(
                                            project_id,
                                            "Process",
                                            "Pull part photo as visual aid",
                                            1,
                                            st.session_state.get("current_editor", ""),
                                            {
                                                "pitch_id": selected_pitch_id,
                                                "part_id": selected_catalog_part_id,
                                                "part_number": active_part_item.get("part_number", ""),
                                                "view_id": selected_view_id,
                                                "caption": saved_media.get("caption", ""),
                                            },
                                        )
                                        st.toast(
                                            f"Added photo for {active_part_item.get('part_number', 'part')} as visual aid!",
                                            icon=":material/check_circle:",
                                        )
                                        st.rerun()
                                    except Exception as exc:
                                        st.error(str(exc))

                    # Gallery of existing visual aids on this pitch
                    current_media_items = get_pitch_visual_media(project_id, scenario_id, selected_pitch_id)
                    if not current_media_items:
                        st.info("No visual aids uploaded for this pitch yet. Use the form above to add photos, videos, or web links.")
                    else:
                        st.markdown(f"**Current Visual Aids ({len(current_media_items)})**")
                        for m_idx, media_item in enumerate(current_media_items):
                            with st.container(border=True):
                                g_col1, g_col2, g_col3 = st.columns([1.5, 4, 1.5])
                                with g_col1:
                                    m_path = media_item.get("file_path", "")
                                    m_type = media_item.get("media_type")
                                    if m_type == "video":
                                        st.video(m_path)
                                    elif m_type == "link":
                                        lower_p = m_path.lower()
                                        if any(lower_p.endswith(ext) or (ext + "?") in lower_p for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"]):
                                            st.image(m_path, width=140)
                                        st.link_button("Open Web Link", m_path, icon=":material/open_in_new:")
                                    elif m_type == "cad":
                                        p = Path(m_path)
                                        size_str = ""
                                        if p.exists():
                                            size_mb = p.stat().st_size / (1024 * 1024)
                                            size_str = f" ({size_mb:.1f} MB)"
                                        st.markdown(f":material/view_in_ar: **3D CAD Model**{size_str}")
                                        if p.exists():
                                            st.download_button(
                                                "Download STEP",
                                                data=p.read_bytes,
                                                file_name=p.name,
                                                mime="application/step",
                                                icon=":material/download:",
                                                key=f"dl_cad_gallery_{media_item['id']}",
                                            )
                                    else:
                                        st.image(cached_image_bytes(m_path, max_dim=320) or m_path, width=140)
                                with g_col2:
                                    st.markdown(f"**Caption:** {media_item.get('caption') or '*(None)*'}")
                                    st.caption(f"Type: `{media_item.get('media_type')}` | Sequence: `{media_item.get('sequence', 10)}`")
                                    if media_item.get("annotations_json"):
                                        st.caption("Markup: :material/draw: **Annotated** (editable shapes)")
                                    tags = media_item.get("tagged_work_elements", [])
                                    pitch_step_map: dict[str, int] = {}
                                    for idx, el in enumerate(pitch_rows):
                                        s_num = idx + 1
                                        for k in (
                                            el.get("work_element_id"),
                                            el.get("id"),
                                            el.get("yamazumi_element_id"),
                                            *(el.get("yamazumi_member_ids") or []),
                                        ):
                                            k_str = str(k or "").strip()
                                            if k_str and k_str not in pitch_step_map:
                                                pitch_step_map[k_str] = s_num
                                    if tags:
                                        tagged_step_nums = sorted([pitch_step_map[str(t.get("work_element_id"))] for t in tags if str(t.get("work_element_id")) in pitch_step_map])
                                        if len(pitch_rows) > 0 and len(tagged_step_nums) >= len(pitch_rows):
                                            nums_display = ", ".join(str(n) for n in tagged_step_nums)
                                            st.caption(f"Tagged Steps: **All elements ({nums_display})**")
                                        else:
                                            tag_parts = []
                                            other_parts = []
                                            for t in tags:
                                                twid = str(t.get("work_element_id") or "")
                                                s_num = pitch_step_map.get(twid)
                                                op_text = t.get("operation") or f"Step {t.get('work_sequence', '')}"
                                                if s_num:
                                                    tag_parts.append(f"{s_num} · {op_text}")
                                                else:
                                                    other_pnum = t.get("element_pitch_number")
                                                    other_parts.append(f"{op_text} (on {other_pnum})" if other_pnum else op_text)
                                            tag_str = ", ".join(tag_parts) if tag_parts else ", ".join(other_parts)
                                            if tag_parts and other_parts:
                                                st.caption(f"Tagged Steps: **{tag_str}** *(also on {', '.join(other_parts)})*")
                                            else:
                                                st.caption(f"Tagged Steps: **{tag_str}**")
                                    else:
                                        all_nums_display = ", ".join(str(idx + 1) for idx in range(len(pitch_rows)))
                                        if all_nums_display:
                                            st.caption(f"Tagged Steps: **All elements ({all_nums_display})**")
                                        else:
                                            st.caption("Tagged Steps: *General pitch visual (all steps)*")
                                with g_col3:
                                    g_act_bar = st.container(horizontal=True)
                                    if media_item.get("media_type") == "image" and not str(media_item.get("file_path", "")).startswith(("http://", "https://")):
                                        if g_act_bar.button("Annotate", icon=":material/draw:", key=f"btn_annotate_media_{media_item['id']}", help="Crop, rotate 90°, insert Parts Catalog or clipboard photos, or add/edit arrows, text callouts, shapes, and badges"):
                                            st.session_state[f"paag_annotate_media_{scenario_id}"] = {
                                                "media_id": media_item["id"],
                                                "pitch_id": selected_pitch_id,
                                            }
                                            st.session_state.pop(f"paag_annotate_staged_{scenario_id}", None)
                                    if g_act_bar.button("Edit", icon=":material/edit:", key=f"btn_edit_media_{media_item['id']}"):
                                        edit_visual_media_dialog(
                                            media_id=media_item["id"],
                                            current_caption=media_item.get("caption", ""),
                                            current_sequence=media_item.get("sequence", 10),
                                            current_tags=[t["work_element_id"] for t in tags if "work_element_id" in t],
                                            element_options=element_options,
                                            project_id=project_id,
                                            scenario_id=scenario_id,
                                            current_url=media_item.get("file_path", "") if media_item.get("media_type") == "link" or str(media_item.get("file_path", "")).startswith(("http://", "https://")) else "",
                                        )
                                    if g_act_bar.button("Copy", icon=":material/content_copy:", key=f"btn_copy_media_{media_item['id']}", help="Duplicate this visual aid on this pitch or copy it to another pitch"):
                                        copy_visual_media_dialog(
                                            media_id=media_item["id"],
                                            current_pitch_id=selected_pitch_id,
                                            current_caption=media_item.get("caption", ""),
                                            current_sequence=media_item.get("sequence", 10),
                                            current_tags=[t["work_element_id"] for t in tags if "work_element_id" in t],
                                            element_options=element_options,
                                            pitch_options=pitch_options,
                                            project_id=project_id,
                                            scenario_id=scenario_id,
                                        )
                                    if g_act_bar.button("Delete", icon=":material/delete:", key=f"destructive_btn_del_media_{media_item['id']}"):
                                        delete_visual_media_dialog(
                                            media_id=media_item["id"],
                                            caption=media_item.get("caption", ""),
                                            project_id=project_id,
                                            scenario_id=scenario_id,
                                        )

                    active_staged_ann_pitch = st.session_state.get(f"paag_annotate_staged_{scenario_id}")
                    active_media_ann_info = st.session_state.get(f"paag_annotate_media_{scenario_id}")
                    if active_staged_ann_pitch:
                        if st.session_state.get(f"staged_media_{active_staged_ann_pitch}"):
                            annotate_staged_media_dialog(
                                str(active_staged_ann_pitch),
                                project_id=project_id,
                                scenario_id=scenario_id,
                            )
                        else:
                            st.session_state.pop(f"paag_annotate_staged_{scenario_id}", None)
                    elif isinstance(active_media_ann_info, dict) and active_media_ann_info.get("media_id"):
                        target_mid = str(active_media_ann_info["media_id"])
                        target_pid = str(active_media_ann_info.get("pitch_id") or selected_pitch_id)
                        target_item = next(
                            (m for m in current_media_items if str(m.get("id")) == target_mid),
                            None,
                        )
                        if target_item is None and target_pid != selected_pitch_id:
                            other_items = get_pitch_visual_media(project_id, scenario_id, target_pid)
                            target_item = next(
                                (m for m in other_items if str(m.get("id")) == target_mid),
                                None,
                            )
                        if target_item is not None:
                            annotate_visual_media_dialog(
                                media_id=target_item["id"],
                                file_path=target_item.get("file_path", ""),
                                original_file_path=target_item.get("original_file_path", ""),
                                annotations_json=target_item.get("annotations_json", ""),
                                caption=target_item.get("caption", ""),
                                project_id=project_id,
                                scenario_id=scenario_id,
                                pitch_id=target_pid,
                            )
                        else:
                            st.session_state.pop(f"paag_annotate_media_{scenario_id}", None)


_save_paag_tab_snapshot(_current_open_paag_tab)
with st.expander("Process at a Glance history", icon=":material/history:"):
    history = audit_history(project_id, "Process plan", limit=50)
    pairing_history = audit_history(project_id, "Process part pairings", limit=50)
    parts_history = audit_history(project_id, "Parts", limit=50)
    if not parts_history.empty:
        parts_history = parts_history.loc[
            parts_history["action"].eq("Create from Process at a Glance")
        ]
    fishbone_history = audit_history(
        project_id, "Fishbone part assignments", limit=50
    )
    if not fishbone_history.empty:
        fishbone_history = fishbone_history.loc[
            fishbone_history["action"].isin(
                {"Place part", "Place new part", "Move part use"}
            )
        ]
    combined_history = pd.concat(
        [history, pairing_history, parts_history, fishbone_history],
        ignore_index=True,
    )
    if combined_history.empty:
        st.caption("No standardized Process at a Glance changes have been recorded yet.")
    else:
        display_history = combined_history.sort_values(
            "created_at",
            ascending=False,
            key=lambda s: pd.to_datetime(s, errors="coerce", utc=True),
        ).drop(
            columns=["details"], errors="ignore"
        )
        if "table_name" in display_history.columns:
            display_history["table_name"] = display_history["table_name"].replace(
                {
                    "Process plan": "Process at a Glance",
                    "Process part pairings": "Part requirements",
                }
            )
        selectable_dataframe(
            display_history,
            key=f"process_history_table_{project_id}_{scenario_id}",
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

