import json
import math
import re

import pandas as pd
import streamlit as st

from utils.cache_store import (
    cached_computation,
    clear_all_caches,
    is_scenario_task_completed,
    mark_scenario_task_completed,
)
from utils.fishbone_ui import (
    normalized_id,
    ordered_yamazumi_area_ids,
    section_breadcrumb_labels,
)
import importlib as _importlib
import inspect as _inspect
import utils.db_core as _db_core_mod
import utils.store as _store_mod
import utils.yamazumi_store as _yamazumi_store_mod

if (
    getattr(_yamazumi_store_mod, "_YAMAZUMI_STORE_HOT_RELOAD_REV", 0) < 6
    or not hasattr(_db_core_mod, "YAMAZUMI_CONVEYOR_TYPES")
    or "update_yamazumi_areas_table" not in _store_mod.__dict__
    or "split_variants" not in _inspect.signature(_yamazumi_store_mod.add_yamazumi_element).parameters
    or "source_variant" not in _inspect.signature(_yamazumi_store_mod.update_yamazumi_element).parameters
):
    _db_core_mod.YAMAZUMI_CONVEYOR_TYPES = ("1-sided", "2-sided")
    if "YAMAZUMI_CONVEYOR_TYPES" not in getattr(_db_core_mod, "__store_exports__", []):
        _db_core_mod.__store_exports__.append("YAMAZUMI_CONVEYOR_TYPES")
    _db_core_mod.init_db()
    for _export_name in getattr(_yamazumi_store_mod, "__domain_exports__", ()):
        _store_mod.__dict__.pop(_export_name, None)
        getattr(_store_mod, "_EXPORTED", {}).pop(_export_name, None)
    _importlib.reload(_yamazumi_store_mod)
    for _dom_mod in getattr(_store_mod, "_DOMAIN_MODULES", ()):
        _dom_exports = list(getattr(_dom_mod, "__domain_exports__", ()))
        if _dom_exports:
            _db_core_mod.register_domain_module(_dom_mod, _dom_exports)
            for _export_name in _dom_exports:
                _export_val = getattr(_dom_mod, _export_name)
                getattr(_store_mod, "_EXPORTED", {})[_export_name] = _export_val
                _store_mod.__dict__[_export_name] = _export_val
    for _export_name in getattr(_db_core_mod, "__store_exports__", ()):
        _export_val = getattr(_db_core_mod, _export_name)
        getattr(_store_mod, "_EXPORTED", {})[_export_name] = _export_val
        _store_mod.__dict__[_export_name] = _export_val
    _db_core_mod.sync_store_runtime(force=True)
    clear_all_caches()

from utils.store import (
    YAMAZUMI_CONVEYOR_TYPES,
    add_yamazumi_element,
    add_yamazumi_pitch,
    assembly_section_walk_order,
    audit_history,
    clear_yamazumi_data,
    complexity_features,
    copy_yamazumi_records,
    delete_yamazumi_element,
    delete_yamazumi_elements,
    delete_yamazumi_pitch,
    duplicate_yamazumi_elements,
    get_planning_scenario,
    generate_yamazumi_pitch_range,
    import_yamazumi_rows,
    move_yamazumi_pitches,
    parse_yamazumi_model_variants,
    planning_scenarios,
    preview_yamazumi_pitch_move,
    preview_yamazumi_copy,
    record_audit_event,
    rename_yamazumi_variants,
    replace_yamazumi_elements,
    replace_yamazumi_pitches,
    replace_yamazumi_work_regions,
    save_yamazumi_stack_draft,
    update_yamazumi_areas_table,
    update_yamazumi_element,
    update_yamazumi_pitch,
    update_yamazumi_settings,
    sync_yamazumi_areas_from_fishbone,
    yamazumi_area_link_status,
    yamazumi_areas,
    yamazumi_elements,
    yamazumi_element_delete_impact,
    yamazumi_elements_for_scenario,
    work_element_criticality,
    yamazumi_pitch_delete_blockers,
    yamazumi_pitch_address_conflicts,
    yamazumi_pitch_feed_target_status,
    yamazumi_pitch_address_suggestion,
    yamazumi_pitch_label,
    yamazumi_pitches,
    yamazumi_pitches_for_scenario,
    yamazumi_work_regions,
)
from utils.scope_ui import page_title_with_scope
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    get_effective_table_editor_state,
    logical_table_editor_key,
    merge_filtered_edits,
    request_table_editor_reset,
)
import utils.table_ui as _table_ui_mod

if "delete_action_label" not in _inspect.signature(_table_ui_mod.editable_table_footer).parameters:
    _importlib.reload(_table_ui_mod)

from utils.table_ui import (
    dataframe_to_excel,
    drop_untouched_new_rows,
    editable_table_footer,
    editable_table_heading,
    native_selected_rows,
    required_field_errors,
    selectable_dataframe,
    selected_rows_action_bar,
    selected_dataframe_rows,
    stage_native_delete_confirmation,
    direct_entry_editor_rows,
    table_has_unsaved_changes,
)
import utils.yamazumi_board as _yamazumi_board_mod

if getattr(_yamazumi_board_mod, "_YAMAZUMI_BOARD_HOT_RELOAD_REV", 0) < 2:
    _importlib.reload(_yamazumi_board_mod)

from utils.yamazumi_board import yamazumi_board
from utils.yamazumi_order import (
    _natural_key,
    filter_yamazumi_pitches_for_board,
    order_yamazumi_pitches_for_board,
)
from utils.time_units import (
    TIME_UNITS,
    display_to_seconds,
    format_seconds,
    normalize_time_unit,
    seconds_to_display,
    time_unit,
)
from utils.yamazumi_stack import (
    UNASSIGNED_STACK_ID,
    apply_stack_draft_to_elements,
    apply_stack_drop,
    build_stack_draft,
    draft_differs,
    reconcile_stack_draft,
    remove_element_from_stack_draft,
    stack_id,
)
from utils.yamazumi_pdf import parse_yamazumi_pdf



project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
WORK_TYPES = ["Cycle", "Periodic", "Fluctuation"]
PITCH_TYPES = ["Pitch", "Waterspider", "Subassembly", "Kitter", "Repacker"]
CONVEYOR_TYPES = list(YAMAZUMI_CONVEYOR_TYPES)
ELEMENT_VARIANT_HELP = (
    "Choose every model stack where this same work element applies. Missing stacks are added "
    "automatically to the destination pitch."
)
ADD_ELEMENT_VARIANT_HELP = (
    "Choose every model stack where this same work element applies. Missing stacks are added "
    "automatically to the destination pitch."
)
if not project_id or not scenario_id:
    st.stop()

scenario = get_planning_scenario(project_id, scenario_id)
if not scenario:
    st.error("The active planning scenario no longer exists.")
    st.stop()

yamazumi_time_unit = normalize_time_unit(
    scenario.get("yamazumi_time_unit", "seconds")
)
takt_time_unit = normalize_time_unit(scenario.get("takt_time_unit", "seconds"))
from utils.yamazumi_naming import (
    format_yamazumi_pitch_address,
    normalize_yamazumi_line_code,
    normalize_yamazumi_section_code,
)
time_config = time_unit(yamazumi_time_unit)
takt_config = time_unit(takt_time_unit)
time_column_label = f"Time ({time_config.label.title()})"
export_time_column_label = f"Time ({time_config.label.lower()})"


def element_times_to_seconds(rows: pd.DataFrame) -> pd.DataFrame:
    converted = rows.copy()
    numeric = pd.to_numeric(converted["time_s"], errors="coerce")
    if numeric.isna().any() or (numeric < 0).any() or not numeric.map(math.isfinite).all():
        raise ValueError(
            "Time to complete must be a finite number that is zero or greater."
        )
    converted["time_s"] = numeric * time_config.seconds_per_unit
    return converted

page_title_with_scope(
    "Yamazumi", scope="scenario", scenario_name=scenario["name"]
)
st.caption(
    "Draft work directly, balance one operator per physical pitch, and route every change to IE review before updating Process at a Glance."
)

pitch_address_conflicts = yamazumi_pitch_address_conflicts(
    project_id, scenario_id
)
if not pitch_address_conflicts.empty:
    st.error(
        "Duplicate pitch addresses must be corrected before additional pitch "
        "changes can be saved in this planning scenario."
    )
    st.caption(
        "Choose one affected Yamazumi area at a time and rename or delete the "
        "duplicate pitch. Existing records are never changed automatically."
    )
    selectable_dataframe(
        pitch_address_conflicts,
        key=f"yamazumi_pitch_address_conflicts_{scenario_id}",
        hide_index=True,
        column_order=["pitch_number", "pitch_name", "area_name"],
        column_config={
            "id": None,
            "area_id": None,
            "pitch_number": st.column_config.TextColumn("Pitch Address"),
            "pitch_name": st.column_config.TextColumn("Pitch Name"),
            "area_name": st.column_config.TextColumn("Yamazumi Area"),
        },
    )

initial_areas_df = yamazumi_areas(project_id, scenario_id)
has_yamazumi_areas = not initial_areas_df.empty


with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center"):
    st.caption(
        f"Rev {scenario['revision_label']} · {scenario['name']} · "
        f"{format_seconds(scenario['takt_time_s'], scenario['takt_time_unit'])} takt"
    )
    request_clear_area = st.button(
        "Clear This Yamazumi Section",
        type="primary",
        icon=":material/delete_sweep:",
        help="Remove the selected Yamazumi section's pitches, work elements, and settings only.",
        disabled=not has_yamazumi_areas,
        key="destructive_request_clear_yamazumi_section",
    )
    request_clear_all = st.button(
        "Clear All Yamazumi Data",
        type="primary",
        icon=":material/delete_forever:",
        help="Remove every Yamazumi area, pitch, work element, and Yamazumi setting in this scenario.",
        disabled=not has_yamazumi_areas,
        key="destructive_request_clear_all_yamazumi_data",
    )

top_controls_slot = st.container()
metrics_slot = st.container()

area_selector_key = f"yamazumi_area_{scenario_id}"
sections = assembly_section_walk_order(project_id)
features = complexity_features(project_id)
active_features = (
    features.loc[features["active"].fillna(1).astype(bool)].copy()
    if not features.empty else features
)
defined_variant_options = ["All models"]
stored_variant_labels: dict[str, str] = {"Base": "All models", "base": "All models"}
for _, feature in active_features.iterrows():
    for choice in json.loads(feature["allowed_values"] or "[]"):
        short_label = f"{feature['name']} = {choice}"
        long_label = f"{feature['category']} · {feature['name']} = {choice}"
        defined_variant_options.append(short_label)
        stored_variant_labels[long_label] = short_label
defined_variant_options = list(dict.fromkeys(defined_variant_options))
_variant_labels_token = tuple(sorted(stored_variant_labels.items()))
if not is_scenario_task_completed(
    "rename_yamazumi_variants",
    project_id,
    scenario_id,
    extra_token=_variant_labels_token,
):
    variant_rename_result = rename_yamazumi_variants(
        project_id, scenario_id, stored_variant_labels
    )
    mark_scenario_task_completed(
        "rename_yamazumi_variants",
        project_id,
        scenario_id,
        extra_token=_variant_labels_token,
    )
    non_base_changes = sum(
        1
        for change in (
            *variant_rename_result["element_changes"],
            *variant_rename_result["pitch_changes"],
        )
        if [
            "All models" if str(v).strip().casefold() == "base" else str(v).strip()
            for v in change.get("old_variants", [])
        ]
        != change.get("new_variants", [])
    )
    if non_base_changes:
        record_audit_event(
            project_id,
            "Yamazumi variants",
            "Automatic variant rename",
            int(non_base_changes),
            st.session_state.get("current_editor", ""),
            {
                "scenario_id": scenario_id,
                "element_changes": variant_rename_result["element_changes"],
                "pitch_changes": variant_rename_result["pitch_changes"],
            },
        )
active_sections = sections.loc[sections["active"].fillna(1).astype(bool)].copy() if not sections.empty else sections
fishbone_sections = active_sections
section_name_by_id = dict(zip(active_sections["id"].astype(str), active_sections["name"].astype(str))) if not active_sections.empty else {}
section_option_labels = dict(zip(sections["id"].astype(str), sections["name"].astype(str))) if not sections.empty else {}
section_id_by_name = {name: section_id for section_id, name in section_name_by_id.items()}


def order_areas_by_fishbone(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows
    section_ids = (
        sections["id"].astype(str).tolist()
        if "id" in sections.columns
        else []
    )
    area_ids = ordered_yamazumi_area_ids(
        rows, section_ids
    )
    return (
        rows.assign(_area_id=rows["id"].astype(str))
        .set_index("_area_id", drop=False)
        .loc[area_ids]
        .drop(columns=["_area_id"])
        .reset_index(drop=True)
    )

yamazumi_import_generation_key = (
    f"yamazumi_import_generation_{project_id}_{scenario_id}"
)
yamazumi_import_generation = int(
    st.session_state.get(yamazumi_import_generation_key, 0) or 0
)
yamazumi_import_widget_scope = (
    f"{project_id}_{scenario_id}_{yamazumi_import_generation}"
)
import_expander_key = f"yamazumi_import_expander_{yamazumi_import_widget_scope}"


def _handle_import_expander_change() -> None:
    if not bool(st.session_state.get(import_expander_key, False)):
        st.session_state[yamazumi_import_generation_key] = (
            int(st.session_state.get(yamazumi_import_generation_key, 0) or 0) + 1
        )


@cached_computation(scope="upload")
def _cached_parse_yamazumi_upload(uploaded_file, is_pdf_file: bool) -> dict:
    if hasattr(uploaded_file, "seek"):
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
    if is_pdf_file:
        pdf_res = parse_yamazumi_pdf(uploaded_file)
        return {
            "dataframe": pdf_res["dataframe"],
            "pitch_dataframe": pdf_res["pitch_dataframe"],
            "metadata": pdf_res["metadata"],
        }
    return {
        "dataframe": pd.read_excel(uploaded_file),
        "pitch_dataframe": None,
        "metadata": None,
    }


with st.expander(
    "Import Yamazumi File (Excel or PDF)",
    icon=":material/upload_file:",
    key=import_expander_key,
    on_change=_handle_import_expander_change,
):
    uploaded = st.file_uploader(
        "Yamazumi Excel or PDF File(s)",
        type=["xlsx", "pdf"],
        accept_multiple_files=True,
        key=f"yamazumi_import_file_{yamazumi_import_widget_scope}",
        help="Upload one or more Excel workbooks (.xlsx) or PDFs exported from yamazumi.sc.geappl.io for the selected Fishbone section.",
    )
    st.caption(
        f"Imports pitches, variants, work elements, and cycle times from one or more files. "
        f"Pitch_Takt_time is interpreted as {takt_config.label.lower()}, "
        f"and Work_Time_to_complete as {time_config.label.lower()}. "
        "Choose a default Fishbone section or assign specific pitches and pitch ranges to one or more Yamazumi areas in the preview below."
    )
    uploaded_files = (
        list(uploaded)
        if isinstance(uploaded, (list, tuple))
        else ([uploaded] if uploaded is not None else [])
    )
    if uploaded_files:
        parsed_dfs: list[pd.DataFrame] = []
        parsed_pitch_dfs: list[pd.DataFrame] = []
        pdf_metas: list[dict] = []
        parse_errors: list[str] = []
        has_pdf = False
        has_excel = False
        for uf in uploaded_files:
            uf_is_pdf = uf.name.lower().endswith(".pdf")
            if uf_is_pdf:
                has_pdf = True
            else:
                has_excel = True
            try:
                upload_res = _cached_parse_yamazumi_upload(uf, uf_is_pdf)
                file_df = upload_res["dataframe"]
                file_pitch_df = upload_res["pitch_dataframe"]
                file_meta = upload_res["metadata"]
                if file_df is not None:
                    file_df_copy = file_df.copy()
                    if len(uploaded_files) > 1:
                        file_df_copy["Source_file"] = uf.name
                    parsed_dfs.append(file_df_copy)
                if file_pitch_df is not None:
                    parsed_pitch_dfs.append(file_pitch_df.copy())
                if uf_is_pdf and file_meta:
                    pdf_metas.append(file_meta)
            except Exception as exc:
                parse_errors.append(
                    f"{uf.name}: {exc}" if len(uploaded_files) > 1 else str(exc)
                )

        parsed_df = (
            pd.concat(parsed_dfs, ignore_index=True)
            if parsed_dfs
            else None
        )
        parsed_pitch_df = (
            pd.concat(parsed_pitch_dfs, ignore_index=True)
            if parsed_pitch_dfs
            else None
        )

        if parse_errors:
            st.error("Could not parse file: " + "; ".join(parse_errors))
        elif parsed_df is not None and (
            not parsed_df.empty
            or (parsed_pitch_df is not None and not parsed_pitch_df.empty)
        ):
            upload_files_sig = tuple(
                (uf.name, getattr(uf, "size", 0)) for uf in uploaded_files
            )
            pitch_sig_key = f"yamazumi_import_pitch_sig_{yamazumi_import_widget_scope}"
            placed_pitches_key = f"yamazumi_import_placed_pitches_{yamazumi_import_widget_scope}"
            pitch_area_map_key = f"yamazumi_import_pitch_area_{yamazumi_import_widget_scope}"
            pitch_include_map_key = f"yamazumi_import_pitch_inc_{yamazumi_import_widget_scope}"
            pitch_type_map_key = f"yamazumi_import_pitch_type_{yamazumi_import_widget_scope}"
            import_pitch_editor_key = f"yamazumi_import_pitch_editor_{yamazumi_import_widget_scope}"
            pitch_base_df_key = f"yamazumi_import_pitch_base_df_{yamazumi_import_widget_scope}"
            from_pitch_key = f"yamazumi_import_bulk_from_{yamazumi_import_widget_scope}"
            to_pitch_key = f"yamazumi_import_bulk_to_{yamazumi_import_widget_scope}"

            if st.session_state.get(pitch_sig_key) != upload_files_sig:
                st.session_state[pitch_sig_key] = upload_files_sig
                st.session_state[placed_pitches_key] = set()
                st.session_state[pitch_area_map_key] = {}
                st.session_state[pitch_include_map_key] = {}
                st.session_state[pitch_type_map_key] = {}
                st.session_state.pop(import_pitch_editor_key, None)
                st.session_state.pop(pitch_base_df_key, None)
                st.session_state.pop(from_pitch_key, None)
                st.session_state.pop(to_pitch_key, None)

            placed_pitch_keys: set[str] = {
                str(k).strip().casefold()
                for k in (st.session_state.get(placed_pitches_key) or set())
                if str(k).strip()
            }
            if placed_pitch_keys:
                if "Pitch_number" in parsed_df.columns:
                    rem_mask = ~parsed_df["Pitch_number"].map(
                        lambda v: ("" if pd.isna(v) else str(v).strip().casefold())
                        in placed_pitch_keys
                    )
                    parsed_df = parsed_df.loc[rem_mask].copy()
                if (
                    parsed_pitch_df is not None
                    and "Pitch_number" in parsed_pitch_df.columns
                ):
                    rem_pitch_mask = ~parsed_pitch_df["Pitch_number"].map(
                        lambda v: ("" if pd.isna(v) else str(v).strip().casefold())
                        in placed_pitch_keys
                    )
                    parsed_pitch_df = parsed_pitch_df.loc[rem_pitch_mask].copy()

            pitch_numbers_set: set[str] = set()
            if parsed_pitch_df is not None and "Pitch_number" in parsed_pitch_df.columns:
                pitch_numbers_set.update(
                    str(v).strip()
                    for v in parsed_pitch_df["Pitch_number"].dropna().tolist()
                    if str(v).strip()
                )
            if "Pitch_number" in parsed_df.columns:
                pitch_numbers_set.update(
                    str(v).strip()
                    for v in parsed_df["Pitch_number"].dropna().tolist()
                    if str(v).strip()
                )
            parsed_pitch_count = len(pitch_numbers_set)
            if len(uploaded_files) > 1:
                st.caption(
                    f"**{len(uploaded_files)} files selected:** "
                    + ", ".join(uf.name for uf in uploaded_files)
                )
            if has_pdf and pdf_metas:
                detected_sublines = list(
                    dict.fromkeys(
                        str(m.get("subline")).strip()
                        for m in pdf_metas
                        if m.get("subline") and str(m.get("subline")).strip()
                    )
                )
                detected_takts = list(
                    dict.fromkeys(
                        f"{m.get('takt_time')} s"
                        for m in pdf_metas
                        if m.get("takt_time")
                    )
                )
                m_col1, m_col2, m_col3, m_col4 = st.columns(4)
                with m_col1:
                    st.metric(
                        "Detected Sub-Line",
                        ", ".join(detected_sublines) if detected_sublines else "—",
                    )
                with m_col2:
                    st.metric("Pitches", parsed_pitch_count)
                with m_col3:
                    st.metric("Work Elements", len(parsed_df))
                with m_col4:
                    st.metric(
                        "Detected Takt",
                        ", ".join(detected_takts) if detected_takts else "—",
                    )

            area_name_options = [
                section_name_by_id[str(sid)]
                for sid in active_sections["id"].astype(str).tolist()
                if str(sid) in section_name_by_id
            ] if not active_sections.empty else []
            fallback_initial_area = area_name_options[0] if area_name_options else ""
            section_name_by_casefold = {
                name.casefold(): name for name in area_name_options
            }

            detected_pitches: list[dict[str, object]] = []
            detected_pitch_idx_by_key: dict[str, int] = {}
            pitch_element_counts: dict[str, int] = {}
            if "Pitch_number" in parsed_df.columns:
                for _, r in parsed_df.iterrows():
                    p_num = str(r.get("Pitch_number") or "").strip()
                    desc = str(r.get("Work_Description") or "").strip()
                    if p_num and desc:
                        pk = p_num.casefold()
                        pitch_element_counts[pk] = pitch_element_counts.get(pk, 0) + 1

            for src_df in (
                [parsed_pitch_df, parsed_df]
                if parsed_pitch_df is not None and not parsed_pitch_df.empty
                else [parsed_df]
            ):
                if src_df is None or "Pitch_number" not in src_df.columns:
                    continue
                for _, r in src_df.iterrows():
                    p_num = str(r.get("Pitch_number") or "").strip()
                    if not p_num:
                        continue
                    pk = p_num.casefold()
                    p_name = (
                        ""
                        if pd.isna(r.get("Pitch_name"))
                        else str(r.get("Pitch_name") or "").strip()
                    )
                    p_subline = (
                        ""
                        if pd.isna(r.get("Sub-Line"))
                        else str(r.get("Sub-Line") or "").strip()
                    )
                    p_type_raw = (
                        ""
                        if pd.isna(r.get("Pitch_type"))
                        else str(r.get("Pitch_type") or "").strip().title()
                    )
                    p_type = p_type_raw if p_type_raw in PITCH_TYPES else "Pitch"
                    if pk not in detected_pitch_idx_by_key:
                        detected_pitch_idx_by_key[pk] = len(detected_pitches)
                        detected_pitches.append(
                            {
                                "pitch_key": pk,
                                "pitch_number": p_num,
                                "pitch_name": p_name,
                                "pitch_type": p_type,
                                "detected_subline": p_subline,
                                "element_count": pitch_element_counts.get(pk, 0),
                            }
                        )
                    else:
                        existing_p = detected_pitches[detected_pitch_idx_by_key[pk]]
                        if not existing_p["pitch_name"] and p_name:
                            existing_p["pitch_name"] = p_name
                        if existing_p.get("pitch_type", "Pitch") == "Pitch" and p_type != "Pitch":
                            existing_p["pitch_type"] = p_type
                        if not existing_p["detected_subline"] and p_subline:
                            existing_p["detected_subline"] = p_subline

            detected_pitches.sort(
                key=lambda p: (
                    _natural_key(p.get("pitch_number")),
                    _natural_key(p.get("pitch_name")),
                )
            )
            all_pitch_nums = [str(p["pitch_number"]) for p in detected_pitches]

            if active_sections.empty:
                st.error(
                    "Create an active Fishbone section before importing Yamazumi data."
                )

            pitch_area_map: dict[str, str] = dict(
                st.session_state.get(pitch_area_map_key) or {}
            )
            pitch_include_map: dict[str, bool] = dict(
                st.session_state.get(pitch_include_map_key) or {}
            )
            pitch_type_map: dict[str, str] = dict(
                st.session_state.get(pitch_type_map_key) or {}
            )

            for p in detected_pitches:
                pk = str(p["pitch_key"])
                det_sub_match = section_name_by_casefold.get(
                    str(p.get("detected_subline") or "").strip().casefold()
                )
                if pk not in pitch_area_map:
                    if det_sub_match:
                        pitch_area_map[pk] = det_sub_match
                        pitch_include_map[pk] = True
                    else:
                        pitch_area_map[pk] = fallback_initial_area
                        pitch_include_map[pk] = False
                if pk not in pitch_type_map or pitch_type_map[pk] not in PITCH_TYPES:
                    det_type = str(p.get("pitch_type") or "Pitch").strip().title()
                    pitch_type_map[pk] = det_type if det_type in PITCH_TYPES else "Pitch"

            st.session_state[pitch_area_map_key] = pitch_area_map
            st.session_state[pitch_include_map_key] = pitch_include_map
            st.session_state[pitch_type_map_key] = pitch_type_map

            with st.expander("Preview Parsed Data", expanded=True, icon=":material/visibility:"):
                detected_import_variants: list[str] = []
                detected_import_seen: set[str] = set()

                def _collect_detected_variant(raw_val: object) -> None:
                    for item in parse_yamazumi_model_variants(raw_val, fallback=None):
                        key = item.casefold()
                        if key not in detected_import_seen:
                            detected_import_seen.add(key)
                            detected_import_variants.append(item)

                for meta in pdf_metas:
                    for v_item in meta.get("variants") or []:
                        _collect_detected_variant(v_item)
                if parsed_pitch_df is not None:
                    for col in ("Model_variants", "Model_variant"):
                        if col in parsed_pitch_df.columns:
                            for val in parsed_pitch_df[col].dropna().tolist():
                                _collect_detected_variant(val)
                if "Model_variant" in parsed_df.columns:
                    for val in parsed_df["Model_variant"].dropna().tolist():
                        _collect_detected_variant(val)
                if "Model_variants" in parsed_df.columns:
                    for val in parsed_df["Model_variants"].dropna().tolist():
                        _collect_detected_variant(val)
                if not detected_import_variants:
                    detected_import_variants = ["All models"]

                variant_element_counts: dict[str, int] = {}
                if "Model_variant" in parsed_df.columns:
                    for val in parsed_df["Model_variant"].dropna().tolist():
                        for item in parse_yamazumi_model_variants(val, fallback="All models"):
                            k = item.casefold()
                            variant_element_counts[k] = variant_element_counts.get(k, 0) + 1
                variant_pitch_counts: dict[str, int] = {}
                pitch_count_source = (
                    parsed_pitch_df
                    if parsed_pitch_df is not None and not parsed_pitch_df.empty
                    else parsed_df
                )
                if pitch_count_source is not None and "Pitch_number" in pitch_count_source.columns:
                    pitches_by_var: dict[str, set[str]] = {}
                    for _, p_row in pitch_count_source.iterrows():
                        p_num = str(p_row.get("Pitch_number") or "").strip().casefold()
                        if not p_num:
                            continue
                        row_vars = parse_yamazumi_model_variants(
                            p_row.get("Model_variants", p_row.get("Model_variant")),
                            fallback="All models",
                        )
                        for item in row_vars:
                            pitches_by_var.setdefault(item.casefold(), set()).add(p_num)
                    variant_pitch_counts = {k: len(v) for k, v in pitches_by_var.items()}

                def _default_variant_assignment(det_var: str, options: list[str]) -> str:
                    det_key = det_var.strip().casefold()
                    for opt in options:
                        if opt.casefold() == det_key:
                            return opt
                    for opt in options:
                        if " = " in opt:
                            _, choice_val = opt.split(" = ", 1)
                            if choice_val.strip().casefold() == det_key:
                                return opt
                    det_tokens = [
                        tok
                        for tok in re.split(r"[^a-z0-9]+", det_key)
                        if tok and tok not in {"base", "variant", "variants", "model", "models", "all"}
                    ]
                    if not det_tokens:
                        return "All models"
                    for opt in options:
                        if " = " in opt:
                            feat_name, choice_val = opt.split(" = ", 1)
                            c_key = choice_val.strip().casefold()
                            f_key = feat_name.strip().casefold()
                            if not c_key:
                                continue
                            if c_key in det_tokens:
                                return opt
                            if c_key in det_key and (len(c_key) >= 3 or f_key in det_key):
                                return opt
                            if any(len(tok) >= 3 and c_key.startswith(tok) for tok in det_tokens):
                                return opt
                    return "All models"

                variant_mapping: dict[str, str] = {}
                variant_audit_mapping: dict[str, str] = {}
                with st.container(border=True):
                    st.markdown("**Assign Features to Detected Model Variants**")
                    if len(defined_variant_options) <= 1:
                        st.caption(
                            "Detected model variants in the uploaded file(s) are listed below. "
                            "Define active features in Complexity Trees to assign official project features here, or map variants to All models."
                        )
                    else:
                        st.caption(
                            "Map each model variant detected in the uploaded Yamazumi chart to All models or an official feature populated in the app before importing."
                        )
                    var_cols = st.columns(min(len(detected_import_variants), 3))
                    for idx, det_var in enumerate(detected_import_variants):
                        det_key = det_var.casefold()
                        var_options = list(defined_variant_options)
                        default_target = _default_variant_assignment(det_var, var_options)
                        default_idx = (
                            var_options.index(default_target)
                            if default_target in var_options
                            else 0
                        )
                        p_cnt = variant_pitch_counts.get(det_key, 0)
                        e_cnt = variant_element_counts.get(det_key, 0)
                        widget_key = f"yamazumi_import_feature_map_{yamazumi_import_widget_scope}_{det_key}"
                        if widget_key in st.session_state and st.session_state[widget_key] not in var_options:
                            st.session_state.pop(widget_key, None)
                        with var_cols[idx % len(var_cols)]:
                            selected_target = st.selectbox(
                                f"Detected Variant: {det_var}",
                                options=var_options,
                                index=default_idx,
                                help=f"Found on {p_cnt} pitch(es) and {e_cnt} work element(s) in the uploaded file(s).",
                                key=widget_key,
                            )
                            variant_mapping[det_var] = selected_target
                            variant_mapping[det_key] = selected_target
                            variant_audit_mapping[det_var] = selected_target

                if variant_mapping:
                    parsed_df = parsed_df.copy()
                    if "Model_variant" in parsed_df.columns:
                        parsed_df["Model_variant"] = [
                            variant_mapping.get(
                                str(v).strip(),
                                variant_mapping.get(
                                    str(v).strip().casefold(),
                                    str(v).strip() or "All models",
                                ),
                            )
                            if pd.notna(v) and str(v).strip()
                            else variant_mapping.get("All models", variant_mapping.get("Base", variant_mapping.get("base", "All models")))
                            for v in parsed_df["Model_variant"]
                        ]
                    if "Model_variants" in parsed_df.columns:
                        parsed_df["Model_variants"] = [
                            parse_yamazumi_model_variants(
                                [
                                    variant_mapping.get(
                                        item,
                                        variant_mapping.get(item.casefold(), item),
                                    )
                                    for item in parse_yamazumi_model_variants(v, fallback="All models")
                                ],
                                fallback="All models",
                            )
                            for v in parsed_df["Model_variants"]
                        ]
                    if parsed_pitch_df is not None and not parsed_pitch_df.empty:
                        parsed_pitch_df = parsed_pitch_df.copy()
                        if (
                            "Model_variants" in parsed_pitch_df.columns
                            or "Model_variant" in parsed_pitch_df.columns
                        ):
                            source_col = (
                                "Model_variants"
                                if "Model_variants" in parsed_pitch_df.columns
                                else "Model_variant"
                            )
                            parsed_pitch_df["Model_variants"] = [
                                parse_yamazumi_model_variants(
                                    [
                                        variant_mapping.get(
                                            item,
                                            variant_mapping.get(item.casefold(), item),
                                        )
                                        for item in parse_yamazumi_model_variants(
                                            v, fallback="All models"
                                        )
                                    ],
                                    fallback="All models",
                                )
                                for v in parsed_pitch_df[source_col]
                            ]

                if detected_pitches and area_name_options:
                    pitch_features_by_key: dict[str, list[str]] = {}
                    pitch_features_seen_by_key: dict[str, set[str]] = {}
                    for src_df in (
                        [parsed_pitch_df, parsed_df]
                        if parsed_pitch_df is not None and not parsed_pitch_df.empty
                        else [parsed_df]
                    ):
                        if src_df is None or "Pitch_number" not in src_df.columns:
                            continue
                        for _, r in src_df.iterrows():
                            p_num = str(r.get("Pitch_number") or "").strip()
                            if not p_num:
                                continue
                            pk = p_num.casefold()
                            raw_v = (
                                r.get("Model_variants")
                                if "Model_variants" in src_df.columns and r.get("Model_variants") is not None
                                else r.get("Model_variant")
                            )
                            for feat in parse_yamazumi_model_variants(raw_v, fallback="All models"):
                                feat_clean = str(feat).strip()
                                if not feat_clean:
                                    continue
                                seen_set = pitch_features_seen_by_key.setdefault(pk, set())
                                feat_cf = feat_clean.casefold()
                                if feat_cf not in seen_set:
                                    seen_set.add(feat_cf)
                                    pitch_features_by_key.setdefault(pk, []).append(feat_clean)
                    default_mapped_feature = variant_mapping.get(
                        "All models",
                        variant_mapping.get("Base", variant_mapping.get("base", "All models")),
                    )
                    for p in detected_pitches:
                        pk = str(p["pitch_key"])
                        p_feats = pitch_features_by_key.get(pk) or [default_mapped_feature]
                        p["features"] = ", ".join(p_feats)

                    with st.container(border=True):
                        st.markdown("**Assign Pitches to Yamazumi Areas**")
                        st.caption(
                            "Select a pitch range to assign to a Yamazumi area (Fishbone section), "
                            "or use the checkboxes and area dropdowns in the table below. Unchecked pitches will not be imported."
                        )
                        pitch_label_by_num = {
                            str(p["pitch_number"]): (
                                f"{p['pitch_number']} — {p['pitch_name']}"
                                if p.get("pitch_name")
                                else str(p["pitch_number"])
                            )
                            for p in detected_pitches
                        }
                        all_pitch_nums = [str(p["pitch_number"]) for p in detected_pitches]
                        bulk_target_options = list(area_name_options)
                        from_pitch_key = f"yamazumi_import_bulk_from_{yamazumi_import_widget_scope}"
                        to_pitch_key = f"yamazumi_import_bulk_to_{yamazumi_import_widget_scope}"
                        clear_sel_flag_key = f"yamazumi_import_clear_sel_{yamazumi_import_widget_scope}"
                        if st.session_state.pop(clear_sel_flag_key, False) and all_pitch_nums:
                            st.session_state[from_pitch_key] = all_pitch_nums[0]
                            st.session_state[to_pitch_key] = all_pitch_nums[-1]
                        if all_pitch_nums:
                            if st.session_state.get(from_pitch_key) not in all_pitch_nums:
                                st.session_state[from_pitch_key] = all_pitch_nums[0]
                            if st.session_state.get(to_pitch_key) not in all_pitch_nums:
                                st.session_state[to_pitch_key] = all_pitch_nums[-1]
                        b_col1, b_col2, b_col3 = st.columns([1.4, 1.4, 1.8])
                        with b_col1:
                            bulk_from_pitch = st.selectbox(
                                "From Pitch",
                                options=all_pitch_nums,
                                index=0 if all_pitch_nums else None,
                                format_func=lambda v: pitch_label_by_num.get(v, v),
                                key=from_pitch_key,
                            )
                        with b_col2:
                            bulk_to_pitch = st.selectbox(
                                "To Pitch",
                                options=all_pitch_nums,
                                index=(len(all_pitch_nums) - 1) if all_pitch_nums else None,
                                format_func=lambda v: pitch_label_by_num.get(v, v),
                                key=to_pitch_key,
                            )
                        with b_col3:
                            bulk_target_area = st.selectbox(
                                "Target Yamazumi Area",
                                options=bulk_target_options,
                                index=0,
                                key=f"yamazumi_import_bulk_area_{yamazumi_import_widget_scope}",
                            )

                        def _resolve_bulk_pitch_keys() -> set[str]:
                            keys: set[str] = set()
                            if bulk_from_pitch is not None or bulk_to_pitch is not None:
                                s_num = bulk_from_pitch if bulk_from_pitch is not None else bulk_to_pitch
                                e_num = bulk_to_pitch if bulk_to_pitch is not None else bulk_from_pitch
                                if s_num in all_pitch_nums and e_num in all_pitch_nums:
                                    i1 = all_pitch_nums.index(s_num)
                                    i2 = all_pitch_nums.index(e_num)
                                    lo, hi = min(i1, i2), max(i1, i2)
                                    for p_num in all_pitch_nums[lo : hi + 1]:
                                        keys.add(p_num.strip().casefold())
                            return keys

                        bulk_btn_row = st.container(horizontal=True)
                        if bulk_btn_row.button(
                            "Assign Pitch Range",
                            icon=":material/check:",
                            help="Assign pitches in the selected From/To range to the Target Yamazumi area.",
                            key=f"yamazumi_import_bulk_apply_{yamazumi_import_widget_scope}",
                        ):
                            target_keys = _resolve_bulk_pitch_keys()
                            if not target_keys:
                                st.warning("Select a From pitch or To pitch range first, or use the checkboxes in the table below.")
                            else:
                                for tk in target_keys:
                                    pitch_area_map[tk] = bulk_target_area
                                    pitch_include_map[tk] = True
                                st.session_state[pitch_area_map_key] = pitch_area_map
                                st.session_state[pitch_include_map_key] = pitch_include_map
                                st.session_state.pop(import_pitch_editor_key, None)
                                st.session_state.pop(pitch_base_df_key, None)

                        if bulk_btn_row.button(
                            "Clear Selection",
                            icon=":material/deselect:",
                            help="Uncheck all pitches and reset the pitch range selection.",
                            key=f"yamazumi_import_bulk_clear_{yamazumi_import_widget_scope}",
                        ):
                            fallback_clear_area = (
                                bulk_target_area
                                or fallback_initial_area
                            )
                            for p in detected_pitches:
                                pk = str(p["pitch_key"])
                                if pitch_area_map.get(pk) not in area_name_options and fallback_clear_area:
                                    pitch_area_map[pk] = fallback_clear_area
                                pitch_include_map[pk] = False
                            st.session_state[pitch_area_map_key] = pitch_area_map
                            st.session_state[pitch_include_map_key] = pitch_include_map
                            st.session_state.pop(import_pitch_editor_key, None)
                            st.session_state.pop(pitch_base_df_key, None)
                            st.session_state[clear_sel_flag_key] = True
                            st.rerun()

                        table_area_options = list(area_name_options)
                        expected_features_col = [
                            str(p.get("features") or "All models")
                            for p in detected_pitches
                        ]
                        if (
                            pitch_base_df_key in st.session_state
                            and (
                                "Feature" not in st.session_state[pitch_base_df_key].columns
                                or "Pitch_type" not in st.session_state[pitch_base_df_key].columns
                                or len(st.session_state[pitch_base_df_key]) != len(detected_pitches)
                                or st.session_state[pitch_base_df_key]["Feature"].astype(str).tolist()
                                != expected_features_col
                            )
                        ):
                            st.session_state.pop(pitch_base_df_key, None)
                            st.session_state.pop(import_pitch_editor_key, None)
                        if pitch_base_df_key not in st.session_state:
                            st.session_state[pitch_base_df_key] = pd.DataFrame(
                                [
                                    {
                                        "Import": bool(pitch_include_map.get(str(p["pitch_key"]), False)),
                                        "Pitch_number": str(p["pitch_number"]),
                                        "Pitch_name": str(p["pitch_name"]),
                                        "Pitch_type": (
                                            str(pitch_type_map.get(str(p["pitch_key"]), "Pitch"))
                                            if str(pitch_type_map.get(str(p["pitch_key"]), "Pitch")) in PITCH_TYPES
                                            else "Pitch"
                                        ),
                                        "Feature": str(p.get("features") or "All models"),
                                        "Work_elements": int(p["element_count"]),
                                        "Target_area": (
                                            str(pitch_area_map.get(str(p["pitch_key"]), fallback_initial_area))
                                            if str(pitch_area_map.get(str(p["pitch_key"]), fallback_initial_area))
                                            in table_area_options
                                            else fallback_initial_area
                                        ),
                                    }
                                    for p in detected_pitches
                                ]
                            )
                        pitch_assign_df = st.session_state[pitch_base_df_key]
                        edited_pitch_df = st.data_editor(
                            pitch_assign_df,
                            width="stretch",
                            hide_index=True,
                            key=import_pitch_editor_key,
                            column_config={
                                "Import": st.column_config.CheckboxColumn(
                                    "Import",
                                    help="Check to import this pitch and its work elements.",
                                    default=True,
                                ),
                                "Pitch_number": st.column_config.TextColumn(
                                    "Pitch Address", disabled=True
                                ),
                                "Pitch_name": st.column_config.TextColumn(
                                    "Pitch Name", disabled=True
                                ),
                                "Pitch_type": st.column_config.SelectboxColumn(
                                    "Pitch Type",
                                    options=PITCH_TYPES,
                                    required=True,
                                    default="Pitch",
                                ),
                                "Feature": st.column_config.TextColumn(
                                    "Feature", disabled=True
                                ),
                                "Work_elements": st.column_config.NumberColumn(
                                    "Work Elements", disabled=True
                                ),
                                "Target_area": st.column_config.SelectboxColumn(
                                    "Target Yamazumi Area",
                                    options=table_area_options,
                                    required=True,
                                ),
                            },
                        )

                        needs_editor_refresh = False
                        for _, erow in edited_pitch_df.iterrows():
                            pk = str(erow["Pitch_number"]).strip().casefold()
                            prev_area = str(pitch_area_map.get(pk, fallback_initial_area))
                            new_inc = bool(erow.get("Import", False))
                            new_area = str(erow.get("Target_area") or fallback_initial_area)
                            new_type = str(erow.get("Pitch_type") or "Pitch").strip().title()
                            if new_type not in PITCH_TYPES:
                                new_type = "Pitch"
                            if new_area != prev_area and not new_inc:
                                new_inc = True
                                needs_editor_refresh = True
                            pitch_include_map[pk] = new_inc
                            pitch_area_map[pk] = new_area
                            pitch_type_map[pk] = new_type

                        st.session_state[pitch_include_map_key] = pitch_include_map
                        st.session_state[pitch_area_map_key] = pitch_area_map
                        st.session_state[pitch_type_map_key] = pitch_type_map
                        if needs_editor_refresh:
                            st.session_state.pop(import_pitch_editor_key, None)
                            st.session_state.pop(pitch_base_df_key, None)
                            st.rerun()

                active_pitch_to_area: dict[str, str] = {}
                for p in detected_pitches:
                    pk = str(p["pitch_key"])
                    inc = bool(pitch_include_map.get(pk, False))
                    t_area = str(pitch_area_map.get(pk, fallback_initial_area))
                    if inc and t_area in section_id_by_name:
                        active_pitch_to_area[pk] = t_area

                if "Pitch_number" in parsed_df.columns:
                    p_keys = parsed_df["Pitch_number"].map(
                        lambda v: "" if pd.isna(v) else str(v).strip().casefold()
                    )
                    parsed_df = parsed_df.loc[p_keys.isin(active_pitch_to_area)].copy()
                    parsed_df["Sub-Line"] = [
                        active_pitch_to_area[str(v).strip().casefold()]
                        for v in parsed_df["Pitch_number"]
                    ]
                    parsed_df["Pitch_type"] = [
                        pitch_type_map.get(str(v).strip().casefold(), "Pitch")
                        for v in parsed_df["Pitch_number"]
                    ]
                if parsed_pitch_df is not None and "Pitch_number" in parsed_pitch_df.columns:
                    pp_keys = parsed_pitch_df["Pitch_number"].map(
                        lambda v: "" if pd.isna(v) else str(v).strip().casefold()
                    )
                    parsed_pitch_df = parsed_pitch_df.loc[pp_keys.isin(active_pitch_to_area)].copy()
                    parsed_pitch_df["Sub-Line"] = [
                        active_pitch_to_area[str(v).strip().casefold()]
                        for v in parsed_pitch_df["Pitch_number"]
                    ]
                    parsed_pitch_df["Pitch_type"] = [
                        pitch_type_map.get(str(v).strip().casefold(), "Pitch")
                        for v in parsed_pitch_df["Pitch_number"]
                    ]
                    if not parsed_pitch_df.empty:
                        parsed_pitch_df = (
                            parsed_pitch_df.assign(
                                _sort_key=parsed_pitch_df["Pitch_number"].map(_natural_key)
                            )
                            .sort_values("_sort_key", kind="mergesort")
                            .drop(columns=["_sort_key"])
                            .reset_index(drop=True)
                        )

                included_pitch_count = len(active_pitch_to_area)
                target_area_names = list(dict.fromkeys(active_pitch_to_area.values()))
                skipped_pitch_count = max(0, len(detected_pitches) - included_pitch_count)
                if included_pitch_count > 0:
                    area_summary_parts = [
                        f"**{a_name}** ({sum(1 for v in active_pitch_to_area.values() if v == a_name)} pitches)"
                        for a_name in target_area_names
                    ]
                    st.caption(
                        "Assigned for import: "
                        + ", ".join(area_summary_parts)
                        + (f" · {skipped_pitch_count} pitch(es) skipped" if skipped_pitch_count else "")
                    )
                else:
                    st.caption(
                        "Assign at least one pitch to a Target Yamazumi area to enable import."
                    )

                if parsed_pitch_df is not None:
                    st.caption(
                        "Pitch totals include detected pitch addresses with no work elements."
                    )
                display_cols = [
                    c for c in [
                        "Source_file", "Sub-Line", "Pitch_number", "Pitch_name", "Model_variant",
                        "Work_Type", "Work_Time_to_complete", "Work_Description",
                        "Work_region"
                    ] if c in parsed_df.columns
                ]
                st.dataframe(
                    parsed_df[display_cols],
                    width="stretch",
                    hide_index=True,
                )

            replace_elements = st.checkbox(
                "Replace Existing Pitch Addresses and Work Elements in Target Area",
                value=False,
                key=f"yamazumi_import_replace_{yamazumi_import_widget_scope}",
                help=(
                    "When checked, removes all existing pitch addresses, feed links, and work elements "
                    "from the target Yamazumi area before importing. The Yamazumi area and its Fishbone "
                    "pairing remain in place."
                ),
            )

            if has_pdf and has_excel:
                import_source_label = "Excel & PDF import"
            elif has_pdf:
                import_source_label = "PDF import"
            else:
                import_source_label = "Excel import"
            area_suffix = (
                f" into {len(target_area_names)} Areas"
                if len(target_area_names) > 1
                else (f" into {target_area_names[0]}" if len(target_area_names) == 1 else "")
            )
            action_btn_text = (
                f"Replace and Import {included_pitch_count} Pitches and "
                f"{len(parsed_df)} Elements{area_suffix}"
                if replace_elements
                else f"Import {included_pitch_count} Pitches and {len(parsed_df)} Elements{area_suffix}"
            )
            import_button_key = (
                f"destructive_yamazumi_import_replace_{yamazumi_import_widget_scope}"
                if replace_elements
                else f"yamazumi_import_apply_{yamazumi_import_widget_scope}"
            )
            pending_replace_import_key = (
                f"yamazumi_pending_replace_import_{yamazumi_import_widget_scope}"
            )

            def _execute_yamazumi_import() -> None:
                try:
                    area_count, pitch_count, element_count = import_yamazumi_rows(
                        project_id,
                        scenario_id,
                        parsed_df,
                        section_id_by_name,
                        replace_existing_elements=replace_elements,
                        source_label=import_source_label,
                        pitch_rows=parsed_pitch_df,
                    )
                    file_names = [uf.name for uf in uploaded_files]
                    record_audit_event(
                        project_id,
                        "Yamazumi",
                        import_source_label,
                        element_count,
                        st.session_state.get("current_editor", ""),
                        {
                            "areas": area_count,
                            "pitches": pitch_count,
                            "file": file_names[0] if len(file_names) == 1 else ", ".join(file_names),
                            "files": file_names,
                            "file_count": len(file_names),
                            "replace_existing_dataset": replace_elements,
                            "takt_time_unit": takt_time_unit,
                            "work_time_unit": yamazumi_time_unit,
                            "target_subline": ", ".join(target_area_names),
                            "target_sublines": target_area_names,
                            "variant_mapping": variant_audit_mapping,
                        },
                    )
                    toast_prefix = "Replaced and imported" if replace_elements else "Imported"
                    st.session_state.pop(pending_replace_import_key, None)
                    remaining_unplaced_keys = {
                        str(p["pitch_key"])
                        for p in detected_pitches
                        if str(p["pitch_key"]) not in active_pitch_to_area
                    }
                    if remaining_unplaced_keys:
                        st.session_state[placed_pitches_key] = set(placed_pitch_keys) | set(
                            active_pitch_to_area.keys()
                        )
                        for placed_k in active_pitch_to_area:
                            pitch_area_map.pop(placed_k, None)
                            pitch_include_map.pop(placed_k, None)
                            pitch_type_map.pop(placed_k, None)
                        st.session_state[pitch_area_map_key] = pitch_area_map
                        st.session_state[pitch_include_map_key] = pitch_include_map
                        st.session_state[pitch_type_map_key] = pitch_type_map
                        st.session_state.pop(import_pitch_editor_key, None)
                        st.session_state.pop(pitch_base_df_key, None)
                        st.session_state.pop(from_pitch_key, None)
                        st.session_state.pop(to_pitch_key, None)
                    else:
                        st.session_state.pop(placed_pitches_key, None)
                        st.session_state[yamazumi_import_generation_key] = (
                            yamazumi_import_generation + 1
                        )
                    for _area_row in yamazumi_areas(project_id, scenario_id).to_dict("records"):
                        request_table_editor_reset(
                            f"yamazumi_pitch_editor_{scenario_id}_{_area_row['id']}"
                        )
                    request_table_editor_reset(
                        f"yamazumi_pitch_editor_{scenario_id}_combined"
                    )
                    st.toast(
                        f"{toast_prefix} {element_count} work elements into {pitch_count} pitches",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except (ValueError, TypeError) as exc:
                    st.error(str(exc))

            if st.button(
                action_btn_text,
                type="primary",
                icon=":material/upload:",
                key=import_button_key,
                disabled=included_pitch_count == 0,
            ):
                if replace_elements:
                    st.session_state[pending_replace_import_key] = True
                else:
                    _execute_yamazumi_import()

            @st.dialog("Replace Existing Yamazumi Section Data?", dismissible=False)
            def _confirm_yamazumi_replace_import() -> None:
                target_subline_name = (
                    ", ".join(target_area_names)
                    if target_area_names
                    else "selected section(s)"
                )
                st.warning(
                    f"This will permanently delete the existing pitches and work elements in **{target_subline_name}** "
                    f"for this scenario and replace them with **{included_pitch_count}** pitch(es) and **{len(parsed_df)}** work element(s)."
                )
                st.caption(
                    "Downstream effects: Fishbone sections, other Yamazumi sections, and existing Process at a Glance steps "
                    "will not be deleted. Any Process steps previously linked to replaced work elements will be unlinked and flagged for reconciliation."
                )
                actions = st.container(horizontal=True)
                if actions.button("Cancel", key=f"cancel_yamazumi_import_replace_{yamazumi_import_widget_scope}"):
                    st.session_state.pop(pending_replace_import_key, None)
                    st.rerun()
                if actions.button(
                    "Delete & Replace",
                    type="primary",
                    icon=":material/delete:",
                    key=f"destructive_confirm_yamazumi_import_replace_{yamazumi_import_widget_scope}",
                ):
                    _execute_yamazumi_import()

            if replace_elements and st.session_state.get(pending_replace_import_key):
                _confirm_yamazumi_replace_import()
        elif parsed_df is not None and parsed_df.empty:
            st.warning("No work elements or pitches were found in the uploaded file.")

areas = order_areas_by_fishbone(initial_areas_df)
if fishbone_sections.empty and areas.empty:
    st.info(
        "Build an active Fishbone section before importing or planning Yamazumi data."
    )
    st.stop()

if not fishbone_sections.empty:
    link_status = yamazumi_area_link_status(project_id, scenario_id)
    if link_status["needs_sync"] and st.button(
        "Repair Fishbone Area Links",
        icon=":material/build:",
        help=(
            "Repairs legacy missing, mismatched, or duplicate Fishbone links in this scenario. "
            "New Fishbone sections create their Yamazumi areas automatically."
        ),
    ):
        try:
            summary = sync_yamazumi_areas_from_fishbone(project_id, scenario_id)
            st.toast(
                f"Fishbone areas synchronized: {summary['created']} created, "
                f"{summary['relinked']} relinked, and {summary['conflicts_cleared']} conflicts cleared",
                icon=":material/check_circle:",
            )
            record_audit_event(
                project_id,
                "Yamazumi",
                "Repair Fishbone area links",
                summary["created"] + summary["relinked"] + summary["conflicts_cleared"],
                st.session_state.get("current_editor", ""),
                summary,
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

if areas.empty:
    st.info("Create an area from the Fishbone or import a workbook to begin.")
    st.stop()

area_labels = {
    str(row["id"]): str(row["name"])
    for _, row in areas.iterrows()
}
area_widget_key = f"yamazumi_area_multiselect_{scenario_id}"
area_last_synced_key = f"yamazumi_area_last_synced_{scenario_id}"
pending_area_selector_key = f"yamazumi_pending_area_{scenario_id}"
pending_area_id = str(st.session_state.pop(pending_area_selector_key, "") or "")
if pending_area_id in area_labels:
    st.session_state[area_selector_key] = [pending_area_id]
    st.session_state[area_widget_key] = [pending_area_id]
elif area_selector_key in st.session_state:
    stored_areas = st.session_state.get(area_selector_key)
    if isinstance(stored_areas, str):
        normalized_areas = (
            [stored_areas] if stored_areas in area_labels else [next(iter(area_labels))]
        )
    elif isinstance(stored_areas, (list, tuple, set)):
        valid_stored = [str(v) for v in stored_areas if str(v) in area_labels]
        normalized_areas = (
            valid_stored if valid_stored else [next(iter(area_labels))]
        )
    else:
        normalized_areas = [next(iter(area_labels))]
    if (
        area_widget_key not in st.session_state
        or isinstance(stored_areas, str)
        or stored_areas != st.session_state.get(area_last_synced_key)
    ):
        st.session_state[area_widget_key] = list(normalized_areas)
    st.session_state[area_selector_key] = list(normalized_areas)
if area_widget_key in st.session_state:
    valid_widget_areas = [
        str(v)
        for v in (st.session_state.get(area_widget_key) or [])
        if str(v) in area_labels
    ]
    st.session_state[area_widget_key] = (
        valid_widget_areas if valid_widget_areas else [next(iter(area_labels))]
    )
with top_controls_slot:
    settings_controls = st.container(horizontal=True, vertical_alignment="bottom")
    selected_areas = settings_controls.multiselect(
        "Yamazumi Area",
        options=list(area_labels),
        default=None if area_widget_key in st.session_state else [next(iter(area_labels))],
        format_func=lambda value: area_labels[value],
        key=area_widget_key,
    )
    selected_area_ids = [
        str(value) for value in (selected_areas or []) if str(value) in area_labels
    ]
    if not selected_area_ids:
        selected_area_ids = list(area_labels)
    st.session_state[area_selector_key] = list(selected_area_ids)
    st.session_state[area_last_synced_key] = list(selected_area_ids)
    area_id = selected_area_ids[0]
    multi_area_selected = len(selected_area_ids) > 1
    selected_areas_df = areas.loc[
        areas["id"].astype(str).isin(selected_area_ids)
    ].copy()
    selected_area_names = [area_labels[aid] for aid in selected_area_ids]
    selected_areas_label = (
        selected_area_names[0]
        if len(selected_area_names) == 1
        else f"{len(selected_area_names)} Yamazumi areas ({', '.join(selected_area_names[:3])})"
    )
    area = areas.loc[areas["id"].astype(str) == str(area_id)].iloc[0].to_dict()
    pitch_editor_key = f"yamazumi_pitch_editor_{scenario_id}_{area_id}"
    element_editor_key = f"yamazumi_element_editor_{scenario_id}_{area_id}"
    combined_element_editor_key = f"yamazumi_combined_element_editor_{scenario_id}"
    pitch_delete_key = f"yamazumi_pitches_pending_delete_{scenario_id}_{area_id}"
    element_delete_key = f"yamazumi_elements_pending_delete_{scenario_id}_{area_id}"
    pitch_editor_key = apply_pending_table_editor_reset(pitch_editor_key)
    element_editor_key = apply_pending_table_editor_reset(element_editor_key)
    combined_element_editor_key = apply_pending_table_editor_reset(
        combined_element_editor_key
    )

    default_takt = float(scenario.get("takt_time_s") or 0)
    if not math.isfinite(default_takt):
        default_takt = 0.0
    area_takt_value = area.get("takt_override_s")
    area_takt = (
        default_takt
        if area_takt_value is None or pd.isna(area_takt_value)
        else float(area_takt_value)
    )
    if not math.isfinite(area_takt):
        area_takt = default_takt

    section_id_value = area.get("section_id")
    current_section_id = (
        None if section_id_value is None or pd.isna(section_id_value)
        else str(section_id_value).strip() or None
    )
    linked_elsewhere = {
        str(value) for value in areas["section_id"].dropna().astype(str).tolist()
        if str(value).strip()
    }
    available_sections = [
        section_id for section_id in section_name_by_id
        if section_id not in linked_elsewhere
    ]

    takt_widget_key = f"yamazumi_takt_{scenario_id}_{area_id}_{takt_time_unit}"
    takt_db_sync_key = f"yamazumi_takt_db_synced_{scenario_id}_{area_id}_{takt_time_unit}"
    expected_display_takt = float(seconds_to_display(area_takt, takt_time_unit))
    if (
        takt_widget_key not in st.session_state
        or st.session_state.get(takt_db_sync_key) != expected_display_takt
    ):
        st.session_state[takt_widget_key] = expected_display_takt
        st.session_state[takt_db_sync_key] = expected_display_takt

    takt_time = settings_controls.number_input(
        f"Yamazumi Takt Time ({takt_config.label.title()})",
        min_value=0.0,
        step=min(float(takt_config.step), 0.01),
        format=f"%.{takt_config.decimals}f",
        help="Enter an area-specific takt or use the active planning scenario's target takt.",
        key=takt_widget_key,
    )
    selected_time_unit = yamazumi_time_unit
    if current_section_id or multi_area_selected:
        linked_section = current_section_id
    else:
        linked_section = settings_controls.selectbox(
            "Pair with Fishbone Section",
            options=[None, *available_sections],
            format_func=lambda value: (
                "Unlinked" if value is None else section_option_labels.get(value, value)
            ),
            help="Manual matching is available only for imported areas that could not be matched by name.",
            key=f"linked_fishbone_for_import_{area_id}",
        )

    selected_time_unit = normalize_time_unit(selected_time_unit)
    entered_takt_s = (
        display_to_seconds(takt_time, takt_time_unit)
        if takt_time else default_takt
    )
    submitted_takt_override = entered_takt_s
    stored_takt_overrides = [
        default_takt
        if val is None or pd.isna(val)
        else float(val)
        for val in selected_areas_df["takt_override_s"].tolist()
    ]
    takt_changed = any(
        not math.isclose(submitted_takt_override, stored, rel_tol=1e-9, abs_tol=1e-9)
        for stored in stored_takt_overrides
    )
    settings_changed = (
        selected_time_unit != yamazumi_time_unit
        or takt_changed
        or linked_section != current_section_id
    )
    save_settings = settings_controls.button(
        "Save & Refresh",
        type="primary",
        icon=":material/save:",
        disabled=not settings_changed,
        key=f"save_yamazumi_settings_{scenario_id}_{area_id}",
    )
if save_settings:
    try:
        time_unit_changed = selected_time_unit != yamazumi_time_unit
        if time_unit_changed:
            has_pending_time_edits = (
                table_has_unsaved_changes(
                    element_editor_key, native_row_selection=True
                )
                or bool(st.session_state.get(pitch_delete_key))
                or bool(st.session_state.get(element_delete_key))
                or bool(st.session_state.get(
                    f"yamazumi_add_element_target_{project_id}_{area_id}"
                ))
                or bool(st.session_state.get(
                    f"yamazumi_edit_element_target_{project_id}_{area_id}"
                ))
            )
            if has_pending_time_edits:
                raise ValueError(
                    "Save or undo Yamazumi work-element edits before changing the time unit."
                )
        any_unit_changed = False
        for target_aid in selected_area_ids:
            target_row = areas.loc[areas["id"].astype(str) == str(target_aid)].iloc[0]
            target_sec = (
                linked_section
                if str(target_aid) == str(area_id)
                else (
                    None
                    if target_row.get("section_id") is None or pd.isna(target_row.get("section_id"))
                    else str(target_row.get("section_id")).strip() or None
                )
            )
            res = update_yamazumi_settings(
                project_id,
                scenario_id,
                str(target_aid),
                selected_time_unit,
                target_sec,
                submitted_takt_override,
                st.session_state.get("current_editor", ""),
            )
            any_unit_changed = any_unit_changed or bool(res.get("time_unit_changed"))
            st.session_state.pop(
                f"yamazumi_takt_db_synced_{scenario_id}_{target_aid}_{takt_time_unit}",
                None,
            )
            st.session_state.pop(
                f"yamazumi_takt_db_synced_{scenario_id}_{target_aid}_{selected_time_unit}",
                None,
            )
        request_table_editor_reset(f"yamazumi_area_table_editor_{scenario_id}")
        if any_unit_changed:
            request_table_editor_reset(element_editor_key)
        st.toast(
            f"Saved Yamazumi settings for {selected_areas_label}"
            + (f" (time unit: {TIME_UNITS[selected_time_unit].label})" if any_unit_changed else ""),
            icon=":material/check_circle:",
        )
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

takt = submitted_takt_override if submitted_takt_override is not None else default_takt

if request_clear_area:
    st.session_state["yamazumi_reset_scope"] = "area"
if request_clear_all:
    st.session_state["yamazumi_reset_scope"] = "all"


@st.dialog("Clear Yamazumi Data?", dismissible=False)
def confirm_yamazumi_reset() -> None:
    scope = st.session_state.get("yamazumi_reset_scope")
    if scope == "all":
        st.warning(
            "This will permanently remove every Yamazumi area, pitch, work element, takt time, and pending IE review item in this scenario."
        )
    else:
        st.warning(
            f"This will permanently remove the selected Yamazumi area(s) **{selected_areas_label}**, including all pitches, work elements, takt time, and pending IE review items."
        )
    st.caption(
        "Downstream effects: Fishbone sections, their linked Yamazumi areas, and existing Process at a Glance records will not be deleted or changed. "
        "Any Process steps in this scenario linked to cleared Yamazumi elements will be unlinked and flagged for reconciliation."
    )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_yamazumi_reset"):
        st.session_state.pop("yamazumi_reset_scope", None)
        st.rerun()
    if actions.button(
        "Delete",
        type="primary",
        icon=":material/delete:",
        key="destructive_confirm_yamazumi_reset",
    ):
        if scope == "area":
            counts = {"areas": 0, "pitches": 0, "elements": 0}
            for target_aid in selected_area_ids:
                part = clear_yamazumi_data(project_id, scenario_id, str(target_aid))
                for k in counts:
                    counts[k] += int(part.get(k, 0))
        else:
            counts = clear_yamazumi_data(project_id, scenario_id, None)
        record_audit_event(
            project_id,
            "Yamazumi",
            "Clear area" if scope == "area" else "Clear all",
            counts["elements"],
            st.session_state.get("current_editor", ""),
            counts,
        )
        for key in (
            "yamazumi_reset_scope", area_selector_key,
            pitch_editor_key, element_editor_key,
        ):
            st.session_state.pop(key, None)
        st.toast(
            f"Cleared {counts['areas']} area(s), {counts['pitches']} pitch(es), and {counts['elements']} work element(s)",
            icon=":material/delete_sweep:",
        )
        st.rerun()


if st.session_state.get("yamazumi_reset_scope") in {"area", "all"}:
    confirm_yamazumi_reset()

if multi_area_selected:
    pitches = yamazumi_pitches_for_scenario(project_id, scenario_id)
    pitches = pitches.loc[
        pitches["area_id"].astype(str).isin(selected_area_ids)
    ].copy()
else:
    pitches = yamazumi_pitches(project_id, area_id)
pitch_address_suggestion = yamazumi_pitch_address_suggestion(project_id, area_id)
if not pitches.empty:
    pitches["model_variants"] = [
        [stored_variant_labels.get(item, item) for item in json.loads(value or '["All models"]')]
        for value in pitches["model_variants"]
    ]
    for _pending_pitch_editor_key in dict.fromkeys(
        [
            pitch_editor_key,
            logical_table_editor_key(pitch_editor_key),
            f"yamazumi_pitch_editor_{scenario_id}_combined",
        ]
    ):
        _pending_pitch_editor_state = get_effective_table_editor_state(_pending_pitch_editor_key)
        if not (
            isinstance(_pending_pitch_editor_state, dict)
            and _pending_pitch_editor_state.get("edited_rows")
        ):
            _raw_editor_state = st.session_state.get(_pending_pitch_editor_key)
            if isinstance(_raw_editor_state, dict) and _raw_editor_state.get("edited_rows"):
                _pending_pitch_editor_state = _raw_editor_state
        _pending_pitch_edits = (
            _pending_pitch_editor_state.get("edited_rows")
            if isinstance(_pending_pitch_editor_state, dict)
            else None
        )
        if not (isinstance(_pending_pitch_edits, dict) and _pending_pitch_edits):
            continue
        _logical_pending_key = logical_table_editor_key(_pending_pitch_editor_key)
        _pending_row_ids = (
            st.session_state.get(f"{_pending_pitch_editor_key}__row_ids")
            or st.session_state.get(f"{_logical_pending_key}__row_ids")
        )
        if not isinstance(_pending_row_ids, list):
            if _logical_pending_key.endswith("_combined"):
                _scenario_pitch_df = yamazumi_pitches_for_scenario(project_id, scenario_id)
            else:
                _scenario_pitch_df = yamazumi_pitches(project_id, area_id)
            _pending_row_ids = (
                _scenario_pitch_df["id"].fillna("").astype(str).tolist()
                if not _scenario_pitch_df.empty
                else []
            )
        for _raw_pos, _row_changes in _pending_pitch_edits.items():
            if not isinstance(_row_changes, dict):
                continue
            try:
                _pos = int(_raw_pos)
            except (ValueError, TypeError):
                continue
            if not (0 <= _pos < len(_pending_row_ids)):
                continue
            _edited_pid = str(_pending_row_ids[_pos] or "").strip()
            if not _edited_pid:
                continue
            _pid_mask = pitches["id"].astype(str) == _edited_pid
            if not _pid_mask.any():
                continue
            if "pitch_type" in _row_changes:
                _new_ptype = str(_row_changes.get("pitch_type") or "").strip().title()
                if _new_ptype in PITCH_TYPES:
                    pitches.loc[_pid_mask, "pitch_type"] = _new_ptype
                    if _new_ptype not in {"Subassembly", "Kitter"}:
                        pitches.loc[_pid_mask, "feeds_into_pitch_id"] = None
            if "pitch_name" in _row_changes and _row_changes.get("pitch_name") is not None:
                pitches.loc[_pid_mask, "pitch_name"] = str(_row_changes.get("pitch_name") or "")
            if "pitch_number" in _row_changes and str(_row_changes.get("pitch_number") or "").strip():
                pitches.loc[_pid_mask, "pitch_number"] = str(_row_changes.get("pitch_number")).strip()
            if "status" in _row_changes:
                _new_status = str(_row_changes.get("status") or "").strip().title()
                if _new_status in {"Active", "Open", "Blocked"}:
                    pitches.loc[_pid_mask, "status"] = _new_status
if multi_area_selected:
    elements = yamazumi_elements_for_scenario(project_id, scenario_id)
    elements = elements.loc[
        elements["area_id"].astype(str).isin(selected_area_ids)
    ].copy()
else:
    elements = yamazumi_elements(project_id, area_id)
criticality_by_work_element = work_element_criticality(project_id, scenario_id)


def criticality_for_process_link(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return list(criticality_by_work_element.get(str(value), []))


if not elements.empty:
    parsed_variants_list = [
        [
            stored_variant_labels.get(item, item)
            for item in parse_yamazumi_model_variants(
                mv, str(m_single or "All models")
            )
        ]
        for mv, m_single in zip(elements["model_variants"], elements["model_variant"])
    ]
    elements["model_variants"] = parsed_variants_list
    elements["model_variant"] = [
        values[0] if values else "All models" for values in parsed_variants_list
    ]
    elements["criticality"] = [
        criticality_for_process_link(val) for val in elements["process_element_id"]
    ]

defined_work_regions: set[str] = set()
for target_aid in selected_area_ids:
    region_defs = yamazumi_work_regions(project_id, str(target_aid))
    if not region_defs.empty:
        defined_work_regions.update(
            region_defs.loc[
                region_defs["active"].fillna(1).astype(bool), "name"
            ].dropna().astype(str)
        )
region_definitions = yamazumi_work_regions(project_id, area_id)
legacy_work_regions = sorted(
    {
        str(value).strip()
        for value in elements.get("work_region", pd.Series(dtype=str)).dropna()
        if str(value).strip() and str(value).strip() != "None" and str(value).strip() not in defined_work_regions
    }
)
work_region_options = ["None", *sorted(defined_work_regions), *legacy_work_regions]
legacy_variant_options = [
    value
    for series in (
        pitches.get("model_variants", pd.Series(dtype=object)),
        elements.get("model_variants", pd.Series(dtype=object)),
    )
    for values in series
    for value in (values or [])
    if value not in defined_variant_options
]
variant_options = list(dict.fromkeys([*defined_variant_options, *legacy_variant_options]))
variants = variant_options
pitch_variants_by_id = {
    str(row["id"]): list(row["model_variants"] or ["All models"])
    for _, row in pitches.iterrows()
}
pitch_area_by_id = {
    str(row["id"]): str(row.get("area_id") or area_id)
    for _, row in pitches.iterrows()
}
element_area_by_id = {
    str(row["id"]): str(row.get("area_id") or area_id)
    for _, row in elements.iterrows()
}
feed_target_label_by_id = {
    str(row["id"]): yamazumi_pitch_label(row["pitch_number"], row["pitch_name"])
    for _, row in pitches.iterrows()
}


def feed_target_picker(
    label: str,
    *,
    source_pitch_id: str | None,
    current_target_id: str | None,
    key: str,
    target_area_id: str | None = None,
):
    target_ids = [
        pitch_id for pitch_id in feed_target_label_by_id
        if pitch_id != str(source_pitch_id or "")
        and (
            not target_area_id
            or pitch_area_by_id.get(pitch_id, str(area_id)) == str(target_area_id)
        )
    ]
    options = [None, *target_ids]
    current_value = (
        current_target_id if current_target_id in target_ids else None
    )
    return st.selectbox(
        label,
        options=options,
        index=options.index(current_value),
        format_func=lambda value: (
            "Select a Feed Target"
            if value is None
            else feed_target_label_by_id[value]
        ),
        help="Required for Subassembly and Kitter pitches. Targets are limited to this Yamazumi area.",
        key=key,
    )

def pitch_range_controls(surface: str) -> bool:
    """Render the shared guided pitch-range workflow."""
    st.caption(
        "Addresses use the suggested project and Fishbone codes. Suggestions are "
        "editable and do not restrict imported or existing addresses."
    )
    code_controls = st.container(horizontal=True, vertical_alignment="bottom")
    line_code = code_controls.text_input(
        "Project Line Code",
        value=pitch_address_suggestion["line_code"],
        max_chars=2,
        help="Saved project-wide for future Yamazumi address suggestions.",
        key=f"yamazumi_line_code_{surface}_{project_id}_{area_id}",
    )
    section_code = code_controls.text_input(
        "Fishbone Section Code",
        value=pitch_address_suggestion["section_code"],
        max_chars=3,
        help="Suggested from the linked Fishbone section and editable before generation.",
        key=f"yamazumi_section_code_{surface}_{project_id}_{area_id}",
    )
    sequence_controls = st.container(horizontal=True, vertical_alignment="bottom")
    start_number = sequence_controls.number_input(
        "Starting Sequence",
        min_value=1,
        max_value=9999,
        value=int(pitch_address_suggestion["next_number"]),
        step=1,
        key=f"yamazumi_range_start_{surface}_{project_id}_{area_id}",
    )
    stop_number = sequence_controls.number_input(
        "Ending Sequence",
        min_value=1,
        max_value=9999,
        value=int(pitch_address_suggestion["next_number"]),
        step=1,
        key=f"yamazumi_range_stop_{surface}_{project_id}_{area_id}",
    )
    number_mode = sequence_controls.selectbox(
        "Numbers to Create",
        ["All numbers", "Odd only", "Even only"],
        key=f"yamazumi_range_mode_{surface}_{project_id}_{area_id}",
    )
    detail_controls = st.container(horizontal=True, vertical_alignment="bottom")
    generated_status = detail_controls.selectbox(
        "Starting Status",
        ["Active", "Open", "Blocked"],
        help="Open and Blocked addresses cannot receive work until changed to Active.",
        key=f"yamazumi_range_status_{surface}_{project_id}_{area_id}",
    )
    available_pitch_types = (
        PITCH_TYPES
        if not pitches.empty
        else ["Pitch", "Waterspider", "Repacker"]
    )
    generated_pitch_type = detail_controls.selectbox(
        "Pitch Type",
        available_pitch_types,
        key=f"yamazumi_range_type_{surface}_{project_id}_{area_id}",
    )
    if pitches.empty:
        st.caption(
            "Create a receiving pitch first. Subassembly and Kitter become available "
            "after this area has a valid feed target."
        )
    generated_feed_target_id = None
    if generated_pitch_type in {"Subassembly", "Kitter"}:
        generated_feed_target_id = feed_target_picker(
            "Feeds Into Pitch",
            source_pitch_id=None,
            current_target_id=None,
            key=f"generated_feed_target_{surface}_{scenario_id}_{area_id}",
        )
    generated_variants = st.multiselect(
        "Model Variants Shown on Generated Pitches",
        options=variant_options,
        default=["All models"],
        help="Every generated pitch starts with these visible variant stacks.",
        key=f"yamazumi_range_variants_{surface}_{project_id}_{area_id}",
    )
    try:
        preview_first = format_yamazumi_pitch_address(
            line_code, section_code, start_number
        )
        preview_last = format_yamazumi_pitch_address(
            line_code, section_code, stop_number
        )
        st.caption(f"Preview: {preview_first} through {preview_last}")
    except ValueError:
        preview_first = preview_last = ""
    address_controls = st.container(horizontal=True, vertical_alignment="bottom")
    first_pitch = address_controls.text_input(
        "First Pitch Address",
        value=preview_first,
        help="Prefilled from the naming suggestion and editable before generation.",
        key=(
            f"yamazumi_first_address_{surface}_{project_id}_{area_id}_"
            f"{line_code}_{section_code}_{start_number}"
        ),
    )
    last_pitch = address_controls.text_input(
        "Last Pitch Address",
        value=preview_last,
        help="Uses the same editable prefix and an inclusive ending number.",
        key=(
            f"yamazumi_last_address_{surface}_{project_id}_{area_id}_"
            f"{line_code}_{section_code}_{stop_number}"
        ),
    )

    if not st.button(
        "Generate Pitches",
        type="primary",
        icon=":material/add:",
        key=f"generate_yamazumi_range_{surface}_{project_id}_{area_id}",
    ):
        return False
    try:
        normalized_line_code = normalize_yamazumi_line_code(line_code)
        normalize_yamazumi_section_code(section_code)
        before_generated_ids = set(pitches["id"].astype(str))
        created, skipped_addresses = generate_yamazumi_pitch_range(
            project_id,
            area_id,
            first_pitch,
            last_pitch,
            number_mode,
            generated_status,
            generated_variants,
            generated_pitch_type,
            generated_feed_target_id,
            project_line_code=normalized_line_code,
        )
        generated_rows = yamazumi_pitches(project_id, area_id)
        generated_rows = generated_rows.loc[
            ~generated_rows["id"].astype(str).isin(before_generated_ids)
        ]
        feed_relationship_changes = [
            {
                "source_pitch_id": str(row["id"]),
                "source_pitch_address": str(row["pitch_number"]),
                "old_feeds_into_pitch_id": None,
                "old_feed_target": None,
                "new_feeds_into_pitch_id": generated_feed_target_id,
                "new_feed_target": feed_target_label_by_id.get(
                    str(generated_feed_target_id), ""
                ),
            }
            for _, row in generated_rows.iterrows()
            if generated_feed_target_id
        ]
        old_line_code = pitch_address_suggestion["line_code"]
        record_audit_event(
            project_id,
            "Yamazumi pitches",
            "Generate range",
            created,
            st.session_state.get("current_editor", ""),
            {
                "area_id": area_id,
                "first": first_pitch,
                "last": last_pitch,
                "number_mode": number_mode,
                "status": generated_status,
                "pitch_type": generated_pitch_type,
                "variants": generated_variants,
                "old_project_line_code": old_line_code,
                "new_project_line_code": normalized_line_code,
                "skipped_addresses": skipped_addresses,
                "new_feeds_into_pitch_id": generated_feed_target_id,
                "new_feed_target": feed_target_label_by_id.get(
                    str(generated_feed_target_id), ""
                ),
                "feed_relationship_changes": feed_relationship_changes,
            },
        )
        result_message = f"Generated {created} new pitch addresses"
        if skipped_addresses:
            result_message += (
                f"; skipped {len(skipped_addresses)} existing address(es)"
            )
        st.toast(result_message, icon=":material/check_circle:")
        return True
    except ValueError as exc:
        st.error(str(exc))
        return False


setup_columns = st.columns(2)
with setup_columns[0].expander(
    "Generate Pitch Addresses",
    icon=":material/format_list_numbered:",
    expanded=False,
):
    if pitch_range_controls("expander"):
        request_table_editor_reset(pitch_editor_key)
        st.rerun()

with setup_columns[1].expander("Define Work Regions", icon=":material/category:"):
    st.caption(
        "Define the area-specific categories used to classify work. Inactive regions remain on "
        "existing elements but cannot be assigned to new ones."
    )
    region_editor_key = f"yamazumi_region_editor_{area_id}"
    region_editor_key = apply_pending_table_editor_reset(region_editor_key)
    region_rows = region_definitions.reindex(
        columns=["id", "name", "description", "active", "color", "sequence", "updated_at"]
    )
    # Empty columns created by reindex default to float64. Streamlit then rejects
    # TextColumn configuration before the first work region can be added.
    region_rows["name"] = region_rows["name"].astype("string").fillna("")
    region_rows["description"] = region_rows["description"].astype("string").fillna("")
    region_rows["active"] = region_rows["active"].fillna(1).astype(bool)

    editable_table_heading("Work Regions")
    visible_regions = filter_table(
        region_rows,
        key=f"yamazumi_region_filters_{area_id}",
        dropdown_columns=["active"],
        search_columns=["name", "description"],
        labels={"active": "Active"},
        reset_widget_keys=[region_editor_key],
    )
    region_editor_rows = direct_entry_editor_rows(
        visible_regions,
        editor_key=region_editor_key,
        sort_columns=["name", "description", "active"],
        labels={"name": "Work Region Name"},
    )
    region_action_slot = st.empty()
    edited_regions = st.data_editor(
        region_editor_rows,
        key=region_editor_key,
        hide_index=True,
        num_rows="dynamic",
        height=300,
        disabled=["id", "color", "sequence", "updated_at"],
        column_order=["name", "description", "active"],
        column_config={
            "id": None,
            "name": st.column_config.TextColumn(
                "Work Region Name", required=True, pinned=True
            ),
            "description": st.column_config.TextColumn("Description", width="large"),
            "active": st.column_config.CheckboxColumn("Active", default=True),
            "color": None,
            "sequence": None,
            "updated_at": None,
        },
    )
    region_actions = editable_table_footer(
        editor_key=region_editor_key,
        key_prefix=f"yamazumi_regions_{area_id}",
        native_row_selection=True,
    )

    selected_regions = native_selected_rows(
        region_editor_rows, editor_key=region_editor_key
    )
    region_bulk = selected_rows_action_bar(
        parent=region_action_slot,
    )
    bulk_region_active = region_bulk.selectbox(
        "Active for Selected Regions",
        [None, True, False],
        format_func=lambda value: (
            "No change" if value is None else ("Active" if value else "Inactive")
        ),
        key=f"yamazumi_region_bulk_active_{area_id}",
    )
    apply_region_bulk = region_bulk.button(
        f"Apply to Selected ({len(selected_regions)})",
        type="primary",
        icon=":material/checklist:",
        disabled=selected_regions.empty,
        key=f"apply_yamazumi_region_bulk_{area_id}",
    )
    request_region_delete = not selected_regions.empty
    region_bulk.download_button(
        "Export Filtered",
        data=lambda: dataframe_to_excel(
            visible_regions[["name", "description", "active"]],
            "Work regions",
        ),
        file_name="yamazumi_work_regions_filtered.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        key=f"export_yamazumi_regions_{area_id}",
    )

    def region_records_from(dataframe: pd.DataFrame) -> list[dict]:
        return dataframe.to_dict("records")

    if apply_region_bulk:
        if table_has_unsaved_changes(region_editor_key, native_row_selection=True):
            st.warning("Save or undo other work-region edits before applying a bulk change.")
        elif bulk_region_active is None:
            st.warning("Choose Active or Inactive to apply.")
        else:
            updated_regions = region_rows.copy()
            selected_ids = set(selected_regions["id"].astype(str))
            updated_regions.loc[
                updated_regions["id"].astype(str).isin(selected_ids), "active"
            ] = bulk_region_active
            count = replace_yamazumi_work_regions(
                project_id, area_id, region_records_from(updated_regions)
            )
            record_audit_event(
                project_id,
                "Yamazumi work regions",
                "Bulk edit",
                len(selected_ids),
                st.session_state.get("current_editor", ""),
                {"active": bulk_region_active},
            )
            request_table_editor_reset(region_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast(f"Updated {len(selected_ids)} work regions", icon=":material/check_circle:")
            st.rerun()

    if request_region_delete:
        if table_has_unsaved_changes(region_editor_key, native_row_selection=True):
            st.warning("Save or undo other work-region edits before deleting selected regions.")
        else:
            st.session_state[f"yamazumi_regions_pending_delete_{area_id}"] = (
                selected_regions["id"].astype(str).tolist()
            )
            stage_native_delete_confirmation(region_editor_key)

    @st.dialog("Delete Selected Work Regions?", dismissible=False)
    def confirm_region_delete() -> None:
        pending_key = f"yamazumi_regions_pending_delete_{area_id}"
        pending_ids = st.session_state.get(pending_key, [])
        st.warning(
            f"Delete {len(pending_ids)} work region(s)? Existing elements using them will be "
            "changed to None."
        )
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_yamazumi_region_delete_{area_id}"):
            st.session_state.pop(pending_key, None)
            request_table_editor_reset(region_editor_key)
            st.rerun()
        if actions.button(
            "Delete Regions",
            type="primary",
            icon=":material/delete:",
            key=f"destructive_confirm_yamazumi_region_delete_{area_id}",
        ):
            kept_regions = region_rows.loc[
                ~region_rows["id"].astype(str).isin(set(pending_ids))
            ]
            count = replace_yamazumi_work_regions(
                project_id, area_id, region_records_from(kept_regions)
            )
            record_audit_event(
                project_id,
                "Yamazumi work regions",
                "Bulk delete",
                len(pending_ids),
                st.session_state.get("current_editor", ""),
            )
            st.session_state.pop(pending_key, None)
            request_table_editor_reset(region_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast(f"Deleted {len(pending_ids)} work regions", icon=":material/delete:")
            st.rerun()

    if st.session_state.get(f"yamazumi_regions_pending_delete_{area_id}"):
        confirm_region_delete()

    if region_actions.undo:
        st.toast("Discarded the unsaved work-region edits", icon=":material/undo:")
        request_table_editor_reset(region_editor_key)
        st.rerun()

    if region_actions.save_and_refresh:
        try:
            if not selected_regions.empty:
                raise ValueError("Clear selected rows before saving work-region edits.")
            edited_regions = drop_untouched_new_rows(
                edited_regions, identifying_columns=["name"]
            )
            errors = required_field_errors(
                edited_regions, {"name": "Work region name"}
            )
            if errors:
                raise ValueError(" ".join(errors))
            combined_regions = merge_filtered_edits(
                region_rows, visible_regions, edited_regions
            )
            count = replace_yamazumi_work_regions(
                project_id, area_id, region_records_from(combined_regions)
            )
            record_audit_event(
                project_id, "Yamazumi work regions", "Save & Refresh", count,
                st.session_state.get("current_editor", ""),
            )
            request_table_editor_reset(region_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast(f"Saved {count} work-region definition(s)", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

times = pd.to_numeric(elements.get("time_s", pd.Series(dtype=float)), errors="coerce").fillna(0)
total_work = float(times.sum())
assigned_pitch_ids = {
    str(pid).strip()
    for pid in elements.get("pitch_id", pd.Series(dtype="string")).dropna().tolist()
    if str(pid).strip()
}
actual_operators = (
    int(pitches["id"].astype(str).str.strip().isin(assigned_pitch_ids).sum())
    if not pitches.empty and assigned_pitch_ids
    else 0
)
theoretical = total_work / takt if takt > 0 else 0
efficiency = total_work / (actual_operators * takt) * 100 if actual_operators and takt > 0 else 0
pitch_totals = elements.assign(time_s=times).groupby("pitch_number", dropna=True)["time_s"].sum() if not elements.empty else pd.Series(dtype=float)
bottleneck = str(pitch_totals.idxmax()) if not pitch_totals.empty else "—"

metrics = metrics_slot.container(horizontal=True)
metrics.metric(
    "Total Work Content",
    format_seconds(total_work, yamazumi_time_unit),
    border=True,
)
metrics.metric("Theoretical Operators", f"{theoretical:.2f}", border=True)
metrics.metric("Actual Operators", actual_operators, border=True)
metrics.metric("Line Balance Efficiency", f"{efficiency:.1f}%", border=True)
metrics.metric("Bottleneck Pitch", bottleneck, border=True)
metrics.metric("Takt", format_seconds(takt, takt_time_unit), border=True)

board_key = f"yamazumi_board_{project_id}_{area_id}"
board_draft_key = f"yamazumi_board_draft_{project_id}_{scenario_id}_{area_id}"
board_draft_error_key = f"yamazumi_board_draft_error_{project_id}_{scenario_id}_{area_id}"
add_pitch_dialog_key = f"yamazumi_show_add_pitch_{project_id}_{area_id}"
add_element_dialog_key = f"yamazumi_add_element_target_{project_id}_{area_id}"
edit_pitch_dialog_key = f"yamazumi_edit_pitch_target_{project_id}_{area_id}"
edit_element_dialog_key = f"yamazumi_edit_element_target_{project_id}_{area_id}"
gui_pitch_delete_key = f"yamazumi_gui_pitch_pending_delete_{project_id}_{scenario_id}_{area_id}"
gui_element_delete_key = f"yamazumi_gui_element_pending_delete_{project_id}_{scenario_id}_{area_id}"
pitch_edit_restore_key = f"yamazumi_gui_pitch_edit_restore_{project_id}_{scenario_id}_{area_id}"
element_edit_restore_key = f"yamazumi_gui_element_edit_restore_{project_id}_{scenario_id}_{area_id}"
delete_element_dialog_key = f"yamazumi_delete_element_target_{project_id}_{area_id}"
move_pitch_dialog_key = (
    f"yamazumi_move_pitches_{project_id}_{scenario_id}_{area_id}"
)
copy_pitch_dialog_key = (
    f"yamazumi_copy_pitches_{project_id}_{scenario_id}_{area_id}"
)


def close_other_yamazumi_dialogs(keep: str) -> None:
    """Guarantee that only one Streamlit dialog is eligible in a script run."""
    for dialog_key in (
        add_pitch_dialog_key,
        add_element_dialog_key,
        edit_pitch_dialog_key,
        edit_element_dialog_key,
        delete_element_dialog_key,
        move_pitch_dialog_key,
        copy_pitch_dialog_key,
    ):
        if dialog_key != keep:
            st.session_state.pop(dialog_key, None)


def handle_yamazumi_move() -> None:
    state = st.session_state.get(board_key)
    move = getattr(state, "move", None) if state is not None else None
    if not move and isinstance(state, dict):
        move = state.get("move")
    if not move:
        return
    if multi_area_selected:
        persisted_df = yamazumi_elements_for_scenario(project_id, scenario_id)
        persisted_elements = persisted_df.loc[
            persisted_df["area_id"].astype(str).isin(selected_area_ids)
        ].to_dict("records")
    else:
        persisted_elements = yamazumi_elements(project_id, area_id).to_dict("records")
    current_draft = st.session_state.get(board_draft_key)
    valid_p_ids = set(pitches["id"].dropna().astype(str)) if not pitches.empty else set()
    if not isinstance(current_draft, dict):
        current_draft = build_stack_draft(persisted_elements)
    else:
        current_draft = reconcile_stack_draft(
            current_draft, persisted_elements, valid_pitch_ids=valid_p_ids
        )
    try:
        updated_draft = apply_stack_drop(
            current_draft,
            element_id=str(move.get("element_id") or ""),
            pitch_id=move.get("pitch_id"),
            before_element_id=move.get("before_element_id"),
            after_element_id=move.get("after_element_id"),
            insert_index=move.get("insert_index"),
        )
        st.session_state.pop(board_draft_error_key, None)
        if draft_differs(persisted_elements, updated_draft):
            st.session_state[board_draft_key] = updated_draft
        else:
            st.session_state.pop(board_draft_key, None)
    except ValueError as exc:
        st.session_state[board_draft_error_key] = str(exc)


def handle_add_pitch_request() -> None:
    close_other_yamazumi_dialogs(add_pitch_dialog_key)
    st.session_state[add_pitch_dialog_key] = True


def handle_add_element_request() -> None:
    state = st.session_state.get(board_key)
    request = getattr(state, "add_element", None) if state is not None else None
    if not request and isinstance(state, dict):
        request = state.get("add_element")
    if request:
        close_other_yamazumi_dialogs(add_element_dialog_key)
        st.session_state[add_element_dialog_key] = dict(request)


def _board_trigger(name: str) -> dict:
    state = st.session_state.get(board_key)
    value = getattr(state, name, None) if state is not None else None
    if not value and isinstance(state, dict):
        value = state.get(name)
    return dict(value) if value else {}


def _clear_edit_pitch_widget_state(target_pitch_id: object, *, clear_sig: bool = True) -> None:
    pid = str(target_pitch_id or "").strip()
    if not pid:
        return
    for prefix in (
        "edit_pitch_number_",
        "edit_pitch_name_",
        "edit_pitch_status_",
        "edit_pitch_type_",
        "edit_pitch_feed_target_",
        "edit_pitch_variants_",
    ):
        st.session_state.pop(f"{prefix}{pid}", None)
    if clear_sig:
        st.session_state.pop(f"edit_pitch_source_sig_{pid}", None)


def close_edit_pitch_dialog() -> None:
    prev_pid = st.session_state.pop(edit_pitch_dialog_key, None)
    _clear_edit_pitch_widget_state(prev_pid)


def handle_edit_pitch_request() -> None:
    request = _board_trigger("edit_pitch")
    if request.get("pitch_id"):
        target_pid = str(request["pitch_id"])
        close_other_yamazumi_dialogs(edit_pitch_dialog_key)
        _clear_edit_pitch_widget_state(target_pid)
        st.session_state[edit_pitch_dialog_key] = target_pid


def handle_edit_element_request() -> None:
    request = _board_trigger("edit_element")
    if request.get("element_id"):
        close_other_yamazumi_dialogs(edit_element_dialog_key)
        model_variant = str(request.get("model_variant") or "").strip()
        if model_variant:
            st.session_state[edit_element_dialog_key] = {
                "element_id": str(request["element_id"]),
                "model_variant": model_variant,
            }
        else:
            st.session_state[edit_element_dialog_key] = str(request["element_id"])


@st.dialog("Add Pitch")
def add_pitch_dialog() -> None:
    st.caption("The new address will appear on the north/top or south/bottom side based on its ending number.")
    target_pitch_area_id = str(area_id)
    if multi_area_selected:
        target_pitch_area_id = st.selectbox(
            "Yamazumi Area",
            options=selected_area_ids,
            format_func=lambda value: area_labels.get(str(value), str(value)),
            key=f"add_pitch_area_{project_id}_{scenario_id}_{area_id}",
        )
    target_suggestion = (
        pitch_address_suggestion
        if str(target_pitch_area_id) == str(area_id)
        else yamazumi_pitch_address_suggestion(project_id, str(target_pitch_area_id))
    )
    pitch_number = st.text_input(
        "Pitch Address",
        value=target_suggestion["suggested_address"],
        placeholder="01-ML1-001",
        help="Must be unique across every Yamazumi area in this planning scenario. Capitalization and surrounding spaces do not create a different address.",
        key=f"add_pitch_number_{project_id}_{scenario_id}_{target_pitch_area_id}",
    )
    pitch_name = st.text_input("Pitch Name")
    status = st.selectbox("Status", ["Active", "Open", "Blocked"], index=0)
    pitch_type = st.selectbox("Pitch Type", PITCH_TYPES, index=0)
    feed_target_id = None
    if pitch_type in {"Subassembly", "Kitter"}:
        feed_target_id = feed_target_picker(
            "Feeds Into Pitch",
            source_pitch_id=None,
            current_target_id=None,
            key=f"add_pitch_feed_target_{project_id}_{target_pitch_area_id}",
            target_area_id=str(target_pitch_area_id),
        )
    selected_pitch_variants = st.multiselect(
        "Model Variants Shown on This Pitch",
        options=variant_options,
        default=["All models"],
        help="Only selected variants appear as stacks on this pitch.",
    )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_interactive_pitch"):
        st.session_state.pop(f"yamazumi_show_add_pitch_{project_id}_{area_id}", None)
        st.rerun()
    if actions.button("Add Pitch", type="primary", icon=":material/add:", key="save_interactive_pitch"):
        try:
            new_pitch_id = add_yamazumi_pitch(
                project_id, str(target_pitch_area_id), pitch_number, pitch_name, status,
                selected_pitch_variants, pitch_type, feed_target_id,
            )
            record_audit_event(
                project_id, "Yamazumi pitches", "Add from interactive board", 1,
                st.session_state.get("current_editor", ""),
                {
                    "area_id": str(target_pitch_area_id),
                    "source_pitch_id": new_pitch_id,
                    "source_pitch_address": pitch_number,
                    "pitch_type": pitch_type,
                    "old_feeds_into_pitch_id": None,
                    "old_feed_target": None,
                    "new_feeds_into_pitch_id": feed_target_id,
                    "new_feed_target": feed_target_label_by_id.get(
                        str(feed_target_id), ""
                    ),
                },
            )
            st.session_state.pop(f"yamazumi_show_add_pitch_{project_id}_{area_id}", None)
            request_table_editor_reset(pitch_editor_key)
            st.toast(f"Added pitch {pitch_number}", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Add Yamazumi Work Element")
def add_element_dialog() -> None:
    target = st.session_state.get(f"yamazumi_add_element_target_{project_id}_{area_id}", {})
    target_pitch_id = target.get("pitch_id")
    st.caption(f"Destination: {target.get('pitch_number') or 'Unassigned'}")
    target_element_area_id = (
        pitch_area_by_id.get(str(target_pitch_id), str(area_id))
        if target_pitch_id
        else str(area_id)
    )
    if multi_area_selected and not target_pitch_id:
        target_element_area_id = st.selectbox(
            "Yamazumi Area",
            options=selected_area_ids,
            format_func=lambda value: area_labels.get(str(value), str(value)),
            key=f"add_element_area_{project_id}_{scenario_id}_{area_id}",
        )
    description = st.text_area("Work Description", placeholder="Describe one measurable element of work")
    time_value = st.number_input(
        f"Time to Complete ({time_config.label.title()})",
        min_value=0.0,
        value=0.0,
        step=time_config.step,
        format=f"%.{time_config.decimals}f",
    )
    model_variants = st.multiselect(
        "Model Variants",
        options=variant_options,
        default=["All models"],
        help=ADD_ELEMENT_VARIANT_HELP,
    )
    work_type = st.selectbox("Work Type", WORK_TYPES, index=0)
    work_region = st.selectbox("Work Region", work_region_options, index=0)
    target_variants = pitch_variants_by_id.get(str(target_pitch_id), [])
    variants_added_to_pitch = [
        variant for variant in model_variants
        if target_pitch_id and variant not in target_variants
    ]
    if variants_added_to_pitch:
        st.caption(
            f"{', '.join(variants_added_to_pitch)} will also be added to pitch "
            f"{target.get('pitch_number') or ''} as a new Yamazumi stack."
        )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_interactive_element"):
        st.session_state.pop(f"yamazumi_add_element_target_{project_id}_{area_id}", None)
        st.rerun()
    if actions.button("Add Element", type="primary", icon=":material/add:", key="save_interactive_element"):
        try:
            new_element_id = add_yamazumi_element(
                project_id,
                str(target_element_area_id),
                target_pitch_id,
                {
                    "description": description,
                    "time_s": display_to_seconds(time_value, yamazumi_time_unit),
                    "model_variants": model_variants,
                    "work_type": work_type,
                    "work_region": work_region,
                    "split_variants": True,
                },
            )
            active_board_draft = st.session_state.get(board_draft_key)
            if isinstance(active_board_draft, dict):
                dest_stack = stack_id(target_pitch_id)
                active_board_draft.setdefault(dest_stack, []).append(new_element_id)
                st.session_state[board_draft_key] = active_board_draft
            record_audit_event(
                project_id, "Yamazumi elements", "Add from interactive board", 1,
                st.session_state.get("current_editor", ""),
                {
                    "area_id": str(target_element_area_id),
                    "pitch": target.get("pitch_number"),
                    "description": description,
                    "model_variants": model_variants,
                    "variants_added_to_pitch": variants_added_to_pitch,
                },
            )
            st.session_state.pop(f"yamazumi_add_element_target_{project_id}_{area_id}", None)
            if variants_added_to_pitch:
                request_table_editor_reset(pitch_editor_key)
            request_table_editor_reset(element_editor_key)
            message = "Added Yamazumi work element"
            if variants_added_to_pitch:
                message += f" and enabled {', '.join(variants_added_to_pitch)} on the pitch"
            st.toast(message, icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Edit Pitch", on_dismiss=close_edit_pitch_dialog)
def edit_pitch_dialog() -> None:
    state_key = f"yamazumi_edit_pitch_target_{project_id}_{area_id}"
    pitch_id = st.session_state.get(state_key)
    matches = pitches.loc[pitches["id"].astype(str) == str(pitch_id)]
    if matches.empty:
        st.warning("That pitch is no longer available.")
        if st.button("Close", key="close_missing_pitch"):
            st.session_state.pop(state_key, None)
            _clear_edit_pitch_widget_state(pitch_id)
            st.rerun()
        return
    current = matches.iloc[0]
    current_pitch_area_id = str(current.get("area_id") or area_id)
    restored = st.session_state.pop(pitch_edit_restore_key, None)
    restored_values = (
        dict(restored.get("values") or {})
        if isinstance(restored, dict) and str(restored.get("id")) == str(pitch_id)
        else {}
    )
    current_variants = list(
        restored_values.get("model_variants")
        or current.get("model_variants")
        or ["All models"]
    )
    source_sig_key = f"edit_pitch_source_sig_{pitch_id}"
    source_sig = (
        str(current.get("pitch_number") or ""),
        str(current.get("pitch_name") or ""),
        str(current.get("status") or "Active"),
        str(current.get("pitch_type") or "Pitch").title(),
        str(current.get("feeds_into_pitch_id") or "").strip(),
        tuple(str(v) for v in (current.get("model_variants") or ["All models"])),
    )
    if restored_values or st.session_state.get(source_sig_key) != source_sig:
        _clear_edit_pitch_widget_state(pitch_id, clear_sig=False)
        st.session_state[source_sig_key] = source_sig
    pitch_number = st.text_input(
        "Pitch Address",
        value=str(restored_values.get("pitch_number", current.get("pitch_number")) or ""),
        help="Must be unique across every Yamazumi area in this planning scenario. Capitalization and surrounding spaces do not create a different address.",
        key=f"edit_pitch_number_{pitch_id}",
    )
    pitch_name = st.text_input(
        "Pitch Name",
        value=str(restored_values.get("pitch_name", current.get("pitch_name")) or ""),
        key=f"edit_pitch_name_{pitch_id}",
    )
    statuses = ["Active", "Open", "Blocked"]
    current_status = str(restored_values.get("status", current.get("status")) or "Active")
    status = st.selectbox(
        "Status", statuses, index=statuses.index(current_status) if current_status in statuses else 0,
        key=f"edit_pitch_status_{pitch_id}",
    )
    current_pitch_type = str(
        restored_values.get("pitch_type", current.get("pitch_type")) or "Pitch"
    ).title()
    pitch_type = st.selectbox(
        "Pitch Type", PITCH_TYPES,
        index=PITCH_TYPES.index(current_pitch_type) if current_pitch_type in PITCH_TYPES else 0,
        key=f"edit_pitch_type_{pitch_id}",
    )
    current_feed_target_id = (
        str(
            restored_values.get(
                "feeds_into_pitch_id", current.get("feeds_into_pitch_id")
            )
            or ""
        ).strip()
        or None
    )
    feed_target_id = None
    if pitch_type in {"Subassembly", "Kitter"}:
        if not current_feed_target_id:
            st.warning("Feed target required", icon=":material/link_off:")
        feed_target_id = feed_target_picker(
            "Feeds Into Pitch",
            source_pitch_id=str(pitch_id),
            current_target_id=current_feed_target_id,
            key=f"edit_pitch_feed_target_{pitch_id}",
            target_area_id=current_pitch_area_id,
        )
    selected_variants = st.multiselect(
        "Model Variants Shown on This Pitch",
        options=list(dict.fromkeys([*variant_options, *current_variants])),
        default=current_variants,
        key=f"edit_pitch_variants_{pitch_id}",
        help="Existing work must be moved or retagged before its variant can be removed.",
    )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_edit_pitch_{pitch_id}"):
        st.session_state.pop(state_key, None)
        _clear_edit_pitch_widget_state(pitch_id)
        st.rerun()
    if actions.button("Save Pitch", type="primary", icon=":material/save:", key=f"save_edit_pitch_{pitch_id}"):
        try:
            update_yamazumi_pitch(
                project_id, current_pitch_area_id, str(pitch_id),
                {
                    "pitch_number": pitch_number,
                    "pitch_name": pitch_name,
                    "status": status,
                    "model_variants": selected_variants,
                    "pitch_type": pitch_type,
                    "feeds_into_pitch_id": feed_target_id,
                },
            )
            record_audit_event(
                project_id, "Yamazumi pitches", "Edit from interactive board", 1,
                st.session_state.get("current_editor", ""),
                {
                    "source_pitch_id": pitch_id,
                    "source_pitch_address": pitch_number,
                    "old_feeds_into_pitch_id": current_feed_target_id,
                    "old_feed_target": feed_target_label_by_id.get(
                        str(current_feed_target_id), ""
                    ),
                    "new_feeds_into_pitch_id": feed_target_id,
                    "new_feed_target": feed_target_label_by_id.get(
                        str(feed_target_id), ""
                    ),
                },
            )
            st.session_state.pop(state_key, None)
            _clear_edit_pitch_widget_state(pitch_id)
            request_table_editor_reset(pitch_editor_key)
            st.toast(f"Updated pitch {pitch_number}", icon=":material/check_circle:")
            st.rerun(scope="app")
        except ValueError as exc:
            st.error(str(exc))
    delete_pitch_request = actions.button(
        "Delete Pitch…",
        icon=":material/delete:",
        key=f"destructive_request_delete_pitch_from_board_{pitch_id}",
        disabled=has_board_draft,
        help=(
            "Save or undo the unsaved board arrangement before deleting this pitch."
            if has_board_draft
            else "Review the relationship impact before deleting this pitch."
        ),
    )
    if has_board_draft:
        st.info("Use the board's Save & Refresh or Undo before deleting a pitch.")
    if delete_pitch_request:
        st.session_state.pop(state_key, None)
        _clear_edit_pitch_widget_state(pitch_id)
        st.session_state.pop(gui_element_delete_key, None)
        st.session_state[gui_pitch_delete_key] = {
            "id": str(pitch_id),
            "values": {
                "pitch_number": pitch_number,
                "pitch_name": pitch_name,
                "status": status,
                "pitch_type": pitch_type,
                "feeds_into_pitch_id": feed_target_id,
                "model_variants": list(selected_variants),
            },
        }
        st.rerun(scope="app")


def close_edit_element_dialog() -> None:
    st.session_state.pop(edit_element_dialog_key, None)


def close_move_pitch_dialog() -> None:
    st.session_state.pop(move_pitch_dialog_key, None)


@st.dialog("Move Pitches to Another Yamazumi Area", on_dismiss=close_move_pitch_dialog)
def move_pitch_dialog() -> None:
    source_pitches = yamazumi_pitches_for_scenario(project_id, scenario_id)
    raw_selected = st.session_state.get(move_pitch_dialog_key)
    selected_ids = (
        [str(pid) for pid in raw_selected if str(pid).strip()]
        if isinstance(raw_selected, list)
        else []
    )
    selected_rows = (
        source_pitches.loc[source_pitches["id"].astype(str).isin(selected_ids)].copy()
        if not source_pitches.empty and selected_ids
        else pd.DataFrame()
    )
    if selected_rows.empty and not source_pitches.empty:
        area_pitches = source_pitches.loc[
            source_pitches["area_id"].astype(str) == str(area_id)
        ].copy()
        if len(area_pitches) == 1:
            selected_rows = area_pitches
    if selected_rows.empty:
        st.info("Select one or more pitches in the Pitch Addresses table before clicking Move Pitches.")
        if st.button("Close", key=f"close_empty_pitch_move_{scenario_id}"):
            close_move_pitch_dialog()
            st.rerun()
        return

    selected_ids = selected_rows["id"].astype(str).tolist()
    source_area_ids = set(selected_rows["area_id"].dropna().astype(str))
    destination_ids = (
        [aid for aid in area_labels if aid not in source_area_ids]
        if len(source_area_ids) == 1
        else list(area_labels.keys())
    )
    if len(area_labels) < 2 or not destination_ids:
        st.info("Create another Yamazumi area before moving pitches.")
        if st.button("Close", key=f"close_no_destination_pitch_move_{scenario_id}"):
            close_move_pitch_dialog()
            st.rerun()
        return

    target_area_id = st.selectbox(
        "Destination Yamazumi Area",
        options=destination_ids,
        index=0 if len(destination_ids) == 1 else None,
        placeholder="Select a destination area",
        format_func=lambda value: area_labels.get(value, value),
        key=f"yamazumi_move_pitch_target_{scenario_id}",
    )

    move_preview = None
    preview_error = ""
    if selected_ids and target_area_id:
        try:
            move_preview = preview_yamazumi_pitch_move(
                project_id,
                scenario_id,
                None,
                str(target_area_id),
                selected_ids,
            )
        except ValueError as exc:
            preview_error = str(exc)
            st.error(preview_error)
    if move_preview:
        st.info(
            f"Move {len(move_preview['pitch_ids'])} pitch(es) and "
            f"{move_preview['assigned_element_count']} assigned work element(s) to "
            f"{move_preview['target_area_name']}."
        )
        if move_preview["linked_process_count"]:
            st.caption(
                f"{move_preview['linked_process_count']} linked Process at a Glance step(s) "
                "will remain linked and return to Needs IE review because their Yamazumi "
                "area context changed."
            )
        if move_preview["feed_blockers"]:
            relationships = ", ".join(
                f"{row['source_pitch_label']} → {row['target_pitch_label']}"
                for row in move_preview["feed_blockers"]
            )
            st.error(
                "Move every pitch in each feed relationship together, or re-point it "
                f"first: {relationships}."
            )
        if move_preview["address_conflicts"]:
            st.error(
                "The destination already contains: "
                + ", ".join(
                    row["pitch_label"]
                    for row in move_preview["address_conflicts"]
                )
                + "."
            )

    editor_name = str(st.session_state.get("current_editor") or "").strip()
    actions = st.container(horizontal=True, horizontal_alignment="right")
    if actions.button("Cancel", key=f"cancel_move_pitches_{scenario_id}"):
        close_move_pitch_dialog()
        st.rerun()
    if actions.button(
        "Move Pitches",
        type="primary",
        icon=":material/drive_file_move:",
        key=f"confirm_move_pitches_{scenario_id}",
        disabled=(
            not selected_ids
            or not target_area_id
            or bool(preview_error)
            or not bool(move_preview and move_preview["ready"])
        ),
    ):
        try:
            result = move_yamazumi_pitches(
                project_id,
                scenario_id,
                None,
                str(target_area_id),
                selected_ids,
                editor_name=editor_name,
            )
            close_move_pitch_dialog()
            st.session_state[pending_area_selector_key] = str(target_area_id)
            request_table_editor_reset(pitch_editor_key)
            request_table_editor_reset(
                f"yamazumi_pitch_editor_{scenario_id}_{target_area_id}"
            )
            request_table_editor_reset(element_editor_key)
            request_table_editor_reset(
                f"yamazumi_element_editor_{scenario_id}_{target_area_id}"
            )
            request_table_editor_reset(combined_element_editor_key)
            st.toast(
                f"Moved {result['pitch_count']} pitch(es) and "
                f"{result['element_count']} work element(s) to "
                f"{result['target_area_name']}"
                + (
                    f" · flagged {result.get('flagged_process_count', 0)} PAAG step(s) for review"
                    if result.get("flagged_process_count")
                    else ""
                ),
                icon=":material/drive_file_move:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def close_copy_pitch_dialog() -> None:
    st.session_state.pop(copy_pitch_dialog_key, None)


@st.dialog("Copy Pitches to Another Planning Scenario", on_dismiss=close_copy_pitch_dialog)
def copy_pitch_dialog() -> None:
    st.warning(
        "You can only copy a pitch to another planning scenario to keep unique pitch names within each planning scenario."
    )
    source_pitches = yamazumi_pitches_for_scenario(project_id, scenario_id)
    raw_selected = st.session_state.get(copy_pitch_dialog_key)
    selected_ids = (
        [str(pid) for pid in raw_selected if str(pid).strip()]
        if isinstance(raw_selected, list)
        else []
    )
    selected_rows = (
        source_pitches.loc[source_pitches["id"].astype(str).isin(selected_ids)].copy()
        if not source_pitches.empty and selected_ids
        else pd.DataFrame()
    )
    if selected_rows.empty and not source_pitches.empty:
        area_pitches = source_pitches.loc[
            source_pitches["area_id"].astype(str) == str(area_id)
        ].copy()
        if len(area_pitches) == 1:
            selected_rows = area_pitches
    if selected_rows.empty:
        st.info("Select one or more pitches in the Pitch Addresses table before clicking Copy Pitches.")
        if st.button("Close", key=f"close_empty_pitch_copy_{scenario_id}"):
            close_copy_pitch_dialog()
            st.rerun()
        return

    selected_ids = selected_rows["id"].astype(str).tolist()
    all_scenarios = planning_scenarios(project_id)
    other_scenarios = [
        row for row in all_scenarios if str(row["id"]) != str(scenario_id)
    ]
    if not other_scenarios:
        st.info("Create another planning scenario before copying pitches.")
        if st.button("Close", key=f"close_no_scenario_pitch_copy_{scenario_id}"):
            close_copy_pitch_dialog()
            st.rerun()
        return

    scenario_labels = {
        str(row["id"]): f"Rev {row['revision_label']} · {row['name']}"
        for row in other_scenarios
    }
    scenario_options = list(scenario_labels.keys())
    target_scenario_id = st.selectbox(
        "Target Planning Scenario",
        options=scenario_options,
        index=0 if len(scenario_options) == 1 else None,
        placeholder="Select a target planning scenario",
        format_func=lambda value: scenario_labels.get(str(value), str(value)),
        key=f"yamazumi_copy_pitch_target_scenario_{scenario_id}",
    )

    target_areas_df = (
        yamazumi_areas(project_id, str(target_scenario_id))
        if target_scenario_id
        else pd.DataFrame()
    )
    target_area_labels = (
        dict(zip(target_areas_df["id"].astype(str), target_areas_df["name"].astype(str)))
        if not target_areas_df.empty
        else {}
    )
    target_area_options = list(target_area_labels.keys())
    if target_scenario_id and not target_area_options:
        st.info("No Yamazumi sections are available in the selected target planning scenario.")
    target_area_id = st.selectbox(
        "Target Yamazumi Section",
        options=target_area_options,
        index=0 if len(target_area_options) == 1 else None,
        placeholder="Select a target Yamazumi section",
        format_func=lambda value: target_area_labels.get(str(value), str(value)),
        key=f"yamazumi_copy_pitch_target_area_{scenario_id}_{target_scenario_id or 'none'}",
        disabled=not bool(target_scenario_id and target_area_options),
    )

    pitch_number_overrides: dict[str, str] = {}
    feed_target_overrides: dict[str, str] = {}
    copy_preview = None
    preview_error = ""
    if selected_ids and target_scenario_id and target_area_id:
        try:
            base_preview = preview_yamazumi_copy(
                project_id,
                scenario_id,
                None,
                str(target_scenario_id),
                str(target_area_id),
                selected_ids,
                [],
            )
        except ValueError as exc:
            base_preview = None
            preview_error = str(exc)
            st.error(preview_error)

        if base_preview:
            for conflict in base_preview["number_conflicts"]:
                src_pid = str(conflict["source_pitch_id"])
                pitch_number_overrides[src_pid] = st.text_input(
                    f"New Pitch Address for {conflict['source_pitch_number']}",
                    value="",
                    placeholder="Enter an unused target-scenario pitch address",
                    key=f"yamazumi_copy_pitch_dlg_num_{scenario_id}_{target_area_id}_{src_pid}",
                    help=conflict["reason"],
                )
            target_pitches_df = yamazumi_pitches(project_id, str(target_area_id))
            target_pitch_labels = (
                {
                    str(row["id"]): yamazumi_pitch_label(
                        row.get("pitch_number"), row.get("pitch_name")
                    )
                    for _, row in target_pitches_df.iterrows()
                }
                if not target_pitches_df.empty
                else {}
            )
            feed_target_options = (
                target_pitches_df["id"].astype(str).tolist()
                if not target_pitches_df.empty
                else []
            )
            for required_mapping in base_preview["feed_mapping_required"]:
                src_pid = str(required_mapping["source_pitch_id"])
                mapped_target = st.selectbox(
                    f"Feeds Into Pitch for {required_mapping['source_pitch_number']}",
                    options=[None, *feed_target_options],
                    format_func=lambda value: (
                        "Select a target-section pitch"
                        if value is None
                        else target_pitch_labels.get(str(value), "Unavailable pitch")
                    ),
                    key=f"yamazumi_copy_pitch_dlg_feed_{scenario_id}_{target_area_id}_{src_pid}",
                    help="Subassembly and Kitter pitches must feed into another pitch in the target Yamazumi section.",
                )
                if mapped_target:
                    feed_target_overrides[src_pid] = str(mapped_target)
            try:
                copy_preview = preview_yamazumi_copy(
                    project_id,
                    scenario_id,
                    None,
                    str(target_scenario_id),
                    str(target_area_id),
                    selected_ids,
                    [],
                    pitch_number_overrides=pitch_number_overrides,
                    feed_target_overrides=feed_target_overrides,
                )
            except ValueError as exc:
                preview_error = str(exc)
                st.error(preview_error)

    if copy_preview:
        st.info(
            f"Copy {len(copy_preview['selected_pitches'])} pitch(es) and "
            f"{len(copy_preview['elements_to_copy'])} assigned work element(s) to "
            f"{copy_preview['target']['name']} ({scenario_labels.get(str(target_scenario_id), '')})."
        )
        for conflict in copy_preview["number_conflicts"]:
            st.error(f"{conflict['source_pitch_number']}: {conflict['reason']}")
        for mapping in copy_preview["feed_mapping_required"]:
            st.error(
                f"Choose a target-section feed destination for {mapping['source_pitch_number']}."
            )

    editor_name = str(st.session_state.get("current_editor") or "").strip()
    actions = st.container(horizontal=True, horizontal_alignment="right")
    if actions.button("Cancel", key=f"cancel_copy_pitches_{scenario_id}"):
        close_copy_pitch_dialog()
        st.rerun()
    if actions.button(
        "Copy Pitches",
        type="primary",
        icon=":material/content_copy:",
        key=f"confirm_copy_pitches_{scenario_id}",
        disabled=(
            not selected_ids
            or not target_scenario_id
            or not target_area_id
            or bool(preview_error)
            or not bool(copy_preview and copy_preview.get("ready"))
        ),
    ):
        try:
            result = copy_yamazumi_records(
                project_id,
                scenario_id,
                None,
                str(target_scenario_id),
                str(target_area_id),
                selected_ids,
                [],
                pitch_number_overrides=pitch_number_overrides,
                feed_target_overrides=feed_target_overrides,
                editor_name=editor_name,
            )
            close_copy_pitch_dialog()
            request_table_editor_reset(pitch_editor_key)
            st.toast(
                f"Copied {result['pitch_count']} pitch(es) and "
                f"{result['element_count']} work element(s) to "
                f"{result['target_area_name']}",
                icon=":material/content_copy:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Edit Yamazumi Work Element", on_dismiss=close_edit_element_dialog)
def edit_element_dialog(
    element_id: str,
    restored_values: dict[str, object] | None = None,
    *,
    target_variant: str | None = None,
) -> None:
    state_key = f"yamazumi_edit_element_target_{project_id}_{area_id}"
    matches = elements.loc[elements["id"].astype(str) == str(element_id)]
    if matches.empty:
        st.warning("That work element is no longer available.")
        if st.button("Close", key="close_missing_element"):
            st.session_state.pop(state_key, None)
            st.rerun()
        return
    current = matches.iloc[0]
    restored = st.session_state.pop(element_edit_restore_key, None)
    if isinstance(restored, dict) and str(restored.get("id")) == str(element_id):
        restored_values = dict(restored.get("values") or {})
        if not target_variant and restored.get("model_variant"):
            target_variant = str(restored.get("model_variant")).strip() or None
    else:
        restored_values = dict(restored_values or {})
    active_pitches = pitches.loc[pitches["status"] == "Active"].copy()
    pitch_label_by_id = {
        str(row["id"]): f"{row['pitch_number']} — {row['pitch_name']}".rstrip(" —")
        for _, row in active_pitches.iterrows()
    }
    destinations = [None, *pitch_label_by_id]
    current_pitch_id = (
        str(restored_values.get("pitch_id", current.get("pitch_id")) or "") or None
    )
    with st.container():
        selected_pitch_id = st.selectbox(
            "Pitch",
            options=destinations,
            index=destinations.index(current_pitch_id) if current_pitch_id in destinations else 0,
            format_func=lambda value: "Unassigned" if value is None else pitch_label_by_id[value],
            key=f"edit_element_pitch_{element_id}",
        )
        description = st.text_area(
            "Work Description",
            value=str(restored_values.get("description", current.get("description")) or ""),
            key=f"edit_element_description_{element_id}",
        )
        time_value = st.number_input(
            f"Time to Complete ({time_config.label.title()})",
            min_value=0.0,
            value=seconds_to_display(
                restored_values.get("time_s", current.get("time_s")) or 0,
                yamazumi_time_unit,
            ),
            step=time_config.step,
            format=f"%.{time_config.decimals}f",
            key=f"edit_element_time_{element_id}",
        )
        element_variants = list(
            current.get("model_variants")
            or ["All models"]
        )
        if restored_values.get("model_variants"):
            current_variants = list(restored_values["model_variants"])
        elif target_variant:
            def _norm_variant(value: object) -> str:
                key = str(value or "").strip().casefold()
                return "all models" if key in {"base", "all", "all models"} else key

            target_key = _norm_variant(target_variant)
            matched_variant = next(
                (v for v in element_variants if _norm_variant(v) == target_key),
                target_variant,
            )
            current_variants = [matched_variant]
        else:
            current_variants = element_variants
        available_variants = list(
            dict.fromkeys([*variant_options, *element_variants, *current_variants])
        )
        variants_widget_key = (
            f"edit_element_variants_{element_id}_{target_variant}"
            if target_variant
            else f"edit_element_variants_{element_id}"
        )
        model_variants = st.multiselect(
            "Model Variants", available_variants, default=current_variants,
            help=ELEMENT_VARIANT_HELP,
            key=variants_widget_key,
        )
        current_work_type = str(
            restored_values.get("work_type", current.get("work_type")) or "Cycle"
        ).title()
        work_type = st.selectbox(
            "Work Type", WORK_TYPES,
            index=WORK_TYPES.index(current_work_type) if current_work_type in WORK_TYPES else 0,
            key=f"edit_element_work_type_{element_id}",
        )
        current_work_region = str(
            restored_values.get("work_region", current.get("work_region")) or "None"
        )
        edit_region_options = list(dict.fromkeys([*work_region_options, current_work_region]))
        work_region = st.selectbox(
            "Work Region", edit_region_options,
            index=edit_region_options.index(current_work_region),
            key=f"edit_element_work_region_{element_id}",
        )
        edit_target_variants = pitch_variants_by_id.get(str(selected_pitch_id), [])
        edit_variants_added_to_pitch = [
            variant
            for variant in model_variants
            if selected_pitch_id and variant not in edit_target_variants
        ]
        if edit_variants_added_to_pitch:
            selected_pitch_number = next(
                (
                    str(row["pitch_number"] or "")
                    for _, row in active_pitches.iterrows()
                    if str(row["id"]) == str(selected_pitch_id)
                ),
                "",
            )
            st.caption(
                f"{', '.join(edit_variants_added_to_pitch)} will also be added to pitch "
                f"{selected_pitch_number} as a new Yamazumi stack."
            )
        actions = st.container(horizontal=True)
        save_edit = actions.button(
            "Save Element", type="primary", icon=":material/save:",
            key=f"save_edit_element_{element_id}",
        )
        delete_edit = actions.button(
            "Delete Work Element…",
            icon=":material/delete:",
            key=f"destructive_request_edit_element_delete_{element_id}",
            disabled=has_board_draft and "__unassigned__" in (board_draft or {}),
            help=(
                "Save or undo the unsaved board arrangement before deleting this work element."
                if has_board_draft
                else "Review the relationship impact before deleting this work element."
            ),
        )
        if has_board_draft:
            st.info("Use the board's Save & Refresh or Undo before deleting a work element.")
    if save_edit:
        try:
            current_element_area_id = str(current.get("area_id") or area_id)
            updated_element_id = update_yamazumi_element(
                project_id, current_element_area_id, str(element_id),
                {
                    "pitch_id": selected_pitch_id, "model_variants": model_variants, "work_type": work_type,
                    "description": description,
                    "time_s": display_to_seconds(time_value, yamazumi_time_unit),
                    "work_region": work_region,
                    "source_variant": target_variant,
                },
            )
            active_board_draft = st.session_state.get(board_draft_key)
            if isinstance(active_board_draft, dict):
                eid_str = str(element_id)
                updated_id_str = str(updated_element_id or element_id)
                if updated_id_str != eid_str:
                    dest_stack = active_board_draft.setdefault(stack_id(selected_pitch_id), [])
                    if eid_str in dest_stack:
                        dest_stack.insert(dest_stack.index(eid_str) + 1, updated_id_str)
                    else:
                        dest_stack.append(updated_id_str)
                else:
                    for stack in active_board_draft.values():
                        if eid_str in stack:
                            stack.remove(eid_str)
                    active_board_draft.setdefault(stack_id(selected_pitch_id), []).append(eid_str)
                st.session_state[board_draft_key] = {k: v for k, v in active_board_draft.items() if v}
            record_audit_event(
                project_id, "Yamazumi elements", "Edit from interactive board", 1,
                st.session_state.get("current_editor", ""), {"element_id": updated_element_id or element_id, "description": description},
            )
            st.session_state.pop(state_key, None)
            request_table_editor_reset(pitch_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast("Updated Yamazumi work element", icon=":material/check_circle:")
            st.rerun(scope="app")
        except ValueError as exc:
            st.error(str(exc))
    if delete_edit:
        close_other_yamazumi_dialogs(delete_element_dialog_key)
        st.session_state[delete_element_dialog_key] = {
            "element_id": str(element_id),
            "model_variant": target_variant,
            "draft": {
                "pitch_id": selected_pitch_id,
                "description": description,
                "time_value": float(time_value),
                "model_variants": list(model_variants),
                "work_type": work_type,
                "work_region": work_region,
            },
        }
        st.rerun(scope="app")
    if delete_edit:
        st.session_state.pop(state_key, None)
        st.session_state.pop(gui_pitch_delete_key, None)
        st.session_state[gui_element_delete_key] = {
            "id": str(element_id),
            "model_variant": target_variant,
            "values": {
                "pitch_id": selected_pitch_id,
                "description": description,
                "time_s": display_to_seconds(time_value, yamazumi_time_unit),
                "model_variants": list(model_variants),
                "work_type": work_type,
                "work_region": work_region,
            },
        }
        st.rerun(scope="app")


@st.dialog("Delete Pitch?", dismissible=False)
def confirm_gui_pitch_delete() -> None:
    pending = st.session_state.get(gui_pitch_delete_key, {})
    pitch_id = str(pending.get("id") or "")
    matches = pitches.loc[pitches["id"].astype(str) == pitch_id]
    if matches.empty:
        st.error("That pitch is no longer available in the active scenario.")
        if st.button("Close", key=f"close_missing_gui_pitch_{scenario_id}_{area_id}"):
            st.session_state.pop(gui_pitch_delete_key, None)
            st.rerun()
        return
    current = matches.iloc[0]
    current_pitch_area_id = str(current.get("area_id") or area_id)
    pitch_label = str(current.get("pitch_number") or "Unnamed pitch")
    if current.get("pitch_name"):
        pitch_label += f" — {current['pitch_name']}"
    assigned_count = (
        int(elements["pitch_id"].fillna("").astype(str).eq(pitch_id).sum())
        if not elements.empty
        else 0
    )
    blockers = yamazumi_pitch_delete_blockers(project_id, current_pitch_area_id, [pitch_id])
    st.warning(
        f"Delete {pitch_label}? {assigned_count} assigned work element(s) will move "
        "to Unassigned; the work elements themselves will not be deleted."
    )
    if blockers:
        relationships = ", ".join(
            f"{yamazumi_pitch_label(row['source_pitch_number'], row['source_pitch_name'])} → "
            f"{yamazumi_pitch_label(row['target_pitch_number'], row['target_pitch_name'])}"
            for row in blockers
        )
        st.error(
            "Deletion is blocked while these feed relationships remain: "
            + relationships
            + ". Re-point the source pitches or change their type first."
        )
    if has_board_draft:
        st.error("Use the board's Save & Refresh or Undo before deleting this pitch.")
    editor_name = str(st.session_state.get("current_editor") or "").strip()
    if not editor_name:
        st.error("Enter the Current editor before deleting this pitch.")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_gui_pitch_delete_{pitch_id}"):
        st.session_state.pop(gui_pitch_delete_key, None)
        st.session_state[pitch_edit_restore_key] = pending
        close_other_yamazumi_dialogs(edit_pitch_dialog_key)
        st.session_state[edit_pitch_dialog_key] = pitch_id
        st.rerun()
    if actions.button(
        "Delete Pitch",
        type="primary",
        icon=":material/delete:",
        key=f"destructive_gui_pitch_delete_{pitch_id}",
        disabled=bool(blockers) or has_board_draft or not editor_name,
    ):
        try:
            moved_count = delete_yamazumi_pitch(
                project_id,
                current_pitch_area_id,
                pitch_id,
                scenario_id=scenario_id,
                audit_editor_name=editor_name,
                audit_details={"source": "interactive_board_gui"},
            )
            st.session_state.pop(gui_pitch_delete_key, None)
            st.session_state.pop(pitch_edit_restore_key, None)
            request_table_editor_reset(pitch_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast(
                f"Deleted pitch; {moved_count} work element(s) moved to Unassigned",
                icon=":material/delete:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Delete Yamazumi Work Element?", dismissible=False)
def confirm_gui_element_delete() -> None:
    pending = st.session_state.get(gui_element_delete_key, {})
    element_id = str(pending.get("id") or "")
    matches = elements.loc[elements["id"].astype(str) == element_id]
    if matches.empty:
        st.error("That work element is no longer available in the active scenario.")
        if st.button("Close", key=f"close_missing_gui_element_{scenario_id}_{area_id}"):
            st.session_state.pop(gui_element_delete_key, None)
            st.rerun()
        return
    current = matches.iloc[0]
    current_element_area_id = str(current.get("area_id") or area_id)
    description = str(current.get("description") or "Unnamed work element")
    pitch_id = str(current.get("pitch_id") or "")
    pitch_matches = pitches.loc[pitches["id"].astype(str) == pitch_id]
    pitch_label = (
        yamazumi_pitch_label(
            pitch_matches.iloc[0].get("pitch_number"),
            pitch_matches.iloc[0].get("pitch_name"),
        )
        if not pitch_matches.empty
        else "Unassigned"
    )
    process_element_value = current.get("process_element_id")
    has_process_link = (
        process_element_value is not None
        and not pd.isna(process_element_value)
        and bool(str(process_element_value).strip())
    )
    st.warning(
        f"Delete {description} ({pitch_label})? This removes the work element from "
        "the active planning scenario."
    )
    if has_process_link:
        st.info("Its linked Process at a Glance step will not be deleted automatically.")
    if has_board_draft:
        st.error("Use the board's Save & Refresh or Undo before deleting this work element.")
    editor_name = str(st.session_state.get("current_editor") or "").strip()
    if not editor_name:
        st.error("Enter the Current editor before deleting this work element.")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_gui_element_delete_{element_id}"):
        st.session_state.pop(gui_element_delete_key, None)
        st.session_state[element_edit_restore_key] = pending
        close_other_yamazumi_dialogs(edit_element_dialog_key)
        st.session_state[edit_element_dialog_key] = element_id
        st.rerun()
    if actions.button(
        "Delete Work Element",
        type="primary",
        icon=":material/delete:",
        key=f"destructive_gui_element_delete_{element_id}",
        disabled=has_board_draft or not editor_name,
    ):
        try:
            delete_yamazumi_element(
                project_id,
                current_element_area_id,
                element_id,
                scenario_id=scenario_id,
                audit_editor_name=editor_name,
                audit_details={
                    "source": "interactive_board_gui",
                    "linked_process_step_preserved": has_process_link,
                },
            )
            st.session_state.pop(gui_element_delete_key, None)
            st.session_state.pop(element_edit_restore_key, None)
            request_table_editor_reset(element_editor_key)
            request_table_editor_reset(pitch_editor_key)
            st.toast("Deleted Yamazumi work element", icon=":material/delete:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Delete Yamazumi Work Element?", dismissible=False)
def confirm_interactive_element_delete() -> None:
    pending = st.session_state.get(delete_element_dialog_key, {})
    element_id = str(pending.get("element_id") or "")
    target_element_area_id = element_area_by_id.get(element_id, str(area_id))
    try:
        impact = yamazumi_element_delete_impact(
            project_id, scenario_id, target_element_area_id, element_id
        )
    except ValueError as exc:
        st.warning(str(exc))
        if st.button(
            "Close",
            key=f"close_missing_interactive_element_{project_id}_{area_id}",
        ):
            st.session_state.pop(delete_element_dialog_key, None)
            st.rerun()
        return

    pitch_label = yamazumi_pitch_label(
        impact.get("pitch_number"), impact.get("pitch_name")
    ) if impact.get("pitch_id") else "Unassigned"
    st.warning(
        f"Delete **{impact['description']}** from **{pitch_label}** in this planning scenario?"
    )
    st.write(
        "This removes the element from the Yamazumi board, stack order, work totals, "
        "and line-balance calculations. Changes made in the edit form will not be saved."
    )
    if impact["process_step_exists"]:
        process_label = impact.get("process_operation") or "the linked Work Element"
        st.info(
            f"The Process at a Glance step **{process_label}** and its downstream part "
            "pairings, reviews, Quality, PFMEA, and Control Plan data will remain. It will "
            "lose its Yamazumi pitch, derived Op ID, and pitch-summary connection."
        )
    else:
        st.info("No current Process at a Glance step is linked to this Yamazumi element.")
    legacy_group_count = int(impact.get("legacy_material_group_count") or 0)
    legacy_option_count = int(impact.get("legacy_material_option_count") or 0)
    if legacy_group_count or legacy_option_count:
        st.write(
            f"This also removes {legacy_group_count} legacy Yamazumi-level material "
            f"requirement(s) and {legacy_option_count} option(s) attached directly to the element."
        )
    st.caption(
        "The pitch, Yamazumi area, Fishbone structure, work-region definition, and audit history remain."
    )
    actions = st.container(horizontal=True)
    if actions.button(
        "Cancel",
        key=f"cancel_interactive_element_delete_{project_id}_{area_id}_{element_id}",
    ):
        st.session_state.pop(delete_element_dialog_key, None)
        st.session_state[edit_element_dialog_key] = {
            "element_id": element_id,
            "model_variant": pending.get("model_variant"),
            "draft": dict(pending.get("draft") or {}),
        }
        st.rerun()
    if actions.button(
        "Delete Element",
        type="primary",
        icon=":material/delete:",
        key=f"destructive_confirm_interactive_element_delete_{element_id}",
    ):
        try:
            result = delete_yamazumi_element(
                project_id, scenario_id, target_element_area_id, element_id
            )
            record_audit_event(
                project_id,
                "Yamazumi elements",
                "Delete from interactive board",
                1,
                st.session_state.get("current_editor", ""),
                {
                    "scenario_id": scenario_id,
                    "area_id": target_element_area_id,
                    **result,
                },
            )
            current_draft = st.session_state.get(board_draft_key)
            if isinstance(current_draft, dict):
                updated_draft = remove_element_from_stack_draft(
                    current_draft, element_id
                )
                remaining_elements = [
                    row for row in elements.to_dict("records")
                    if str(row.get("id")) != element_id
                ]
                if draft_differs(remaining_elements, updated_draft):
                    st.session_state[board_draft_key] = updated_draft
                else:
                    st.session_state.pop(board_draft_key, None)
            st.session_state.pop(delete_element_dialog_key, None)
            st.session_state.pop(edit_element_dialog_key, None)
            request_table_editor_reset(element_editor_key)
            st.toast("Deleted Yamazumi work element", icon=":material/delete:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))



interactive_yamazumi_tab, yamazumi_tables_tab = st.tabs(
    ["Interactive Yamazumi", "Yamazumi Tables"]
)

with interactive_yamazumi_tab:
    board_heading, board_filter = st.columns([3, 2], vertical_alignment="bottom")
    with board_heading:
        st.subheader("Interactive Balancing Board")
    with board_filter:
        included_board_pitch_types = st.multiselect(
            "Pitch Types Shown",
            options=PITCH_TYPES,
            default=PITCH_TYPES,
            key=(
                f"yamazumi_board_pitch_types_{project_id}_{scenario_id}_{area_id}"
            ),
            help=(
                "Selected pitch types appear on this board. This display filter does "
                "not change saved pitches, assignments, feed relationships, or metrics."
            ),
        )
    if len(defined_variant_options) == 1:
        st.info(
            "Only All models is available. Add active feature definitions and allowed choices on Model Definitions to create additional Yamazumi variants."
        )
    st.caption(
        "Pitch stacks follow Op ID pitch-address order, with Subassembly and Kitter "
        "feeders immediately before the pitch they feed. Drag work within or between "
        "stacks; order is measured outward from the assembly-flow centerline and remains "
        "a draft until Save & Refresh.",
        help=(
            "CTQ comes from a linked PFMEA Classification of E, P, P-, Q, or E-. "
            "Safety comes from an active Safety requirement linked to the same Process step."
        ),
    )
    persisted_board_elements = elements.to_dict("records")
    raw_board_draft = st.session_state.get(board_draft_key)
    if isinstance(raw_board_draft, dict):
        valid_p_ids = set(pitches["id"].dropna().astype(str)) if not pitches.empty else set()
        board_draft = reconcile_stack_draft(
            raw_board_draft, persisted_board_elements, valid_pitch_ids=valid_p_ids
        )
        if board_draft != raw_board_draft:
            st.session_state[board_draft_key] = board_draft
    else:
        board_draft = None
    has_board_draft = (
        isinstance(board_draft, dict)
        and draft_differs(persisted_board_elements, board_draft)
    )
    board_elements = (
        apply_stack_draft_to_elements(persisted_board_elements, board_draft)
        if has_board_draft else persisted_board_elements
    )
    ordered_board_pitches = order_yamazumi_pitches_for_board(pitches)
    board_pitches = filter_yamazumi_pitches_for_board(
        ordered_board_pitches,
        included_board_pitch_types,
    )
    yamazumi_board(
        board_pitches.to_dict("records"),
        board_elements,
        variants,
        takt,
        time_unit=yamazumi_time_unit,
        takt_time_unit=takt_time_unit,
        key=board_key,
        on_move=handle_yamazumi_move,
        on_add_pitch=handle_add_pitch_request,
        on_add_element=handle_add_element_request,
        on_edit_pitch=handle_edit_pitch_request,
        on_edit_element=handle_edit_element_request,
    )
    if draft_error := st.session_state.pop(board_draft_error_key, None):
        st.error(str(draft_error))
    board_actions = editable_table_footer(
        editor_key=f"yamazumi_board_footer_{project_id}_{scenario_id}_{area_id}",
        key_prefix=f"yamazumi_board_{project_id}_{scenario_id}_{area_id}",
        additional_unsaved_changes=has_board_draft,
    )
    if board_actions.undo:
        st.session_state.pop(board_draft_key, None)
        st.session_state.pop(board_draft_error_key, None)
        st.toast("Restored the last-saved Yamazumi stack order", icon=":material/undo:")
        st.rerun()
    if board_actions.save_and_refresh:
        try:
            if not has_board_draft:
                raise ValueError("There are no unsaved Yamazumi stack changes to save.")
            if multi_area_selected:
                fresh_df = yamazumi_elements_for_scenario(project_id, scenario_id)
                fresh_elements = fresh_df.loc[
                    fresh_df["area_id"].astype(str).isin(selected_area_ids)
                ].to_dict("records")
            else:
                fresh_elements = yamazumi_elements(project_id, area_id).to_dict("records")
            valid_p_ids = set(pitches["id"].dropna().astype(str)) if not pitches.empty else set()
            reconciled_draft = reconcile_stack_draft(
                board_draft, fresh_elements, valid_pitch_ids=valid_p_ids
            )
            result = save_yamazumi_stack_draft(
                project_id,
                scenario_id,
                selected_area_ids if multi_area_selected else area_id,
                reconciled_draft,
            )
            record_audit_event(
                project_id,
                "Yamazumi",
                "Save stack order",
                len(result["changed_element_ids"]),
                st.session_state.get("current_editor", ""),
                {
                    "area_id": result["area_id"],
                    "area_name": result["area_name"],
                    "centerline_outward_stacks": result["affected_stacks"],
                },
            )
            st.session_state.pop(board_draft_key, None)
            if result["enabled_variants"]:
                request_table_editor_reset(pitch_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast(
                f"Saved {len(result['affected_stacks'])} Yamazumi stack(s)"
                + (
                    f" ({len(result['changed_element_ids'])} work element(s) updated)"
                    if result.get("changed_element_ids")
                    else ""
                )
                + (
                    f" · enabled {len(result['enabled_variants'])} variant(s)"
                    if result.get("enabled_variants")
                    else ""
                ),
                icon=":material/check_circle:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
gui_delete_dialog_open = bool(
    st.session_state.get(gui_pitch_delete_key)
    or st.session_state.get(gui_element_delete_key)
)
if st.session_state.get(gui_pitch_delete_key):
    confirm_gui_pitch_delete()
elif st.session_state.get(gui_element_delete_key):
    confirm_gui_element_delete()
elif st.session_state.get(add_pitch_dialog_key):
    add_pitch_dialog()
elif st.session_state.get(add_element_dialog_key):
    add_element_dialog()
elif st.session_state.get(edit_pitch_dialog_key):
    edit_pitch_dialog()
elif st.session_state.get(delete_element_dialog_key):
    confirm_interactive_element_delete()
elif st.session_state.get(move_pitch_dialog_key):
    move_pitch_dialog()
elif st.session_state.get(copy_pitch_dialog_key):
    copy_pitch_dialog()
elif edit_element_target := st.session_state.get(edit_element_dialog_key):
    if isinstance(edit_element_target, dict):
        edit_element_dialog(
            str(edit_element_target.get("element_id") or ""),
            dict(edit_element_target.get("draft") or {}),
            target_variant=str(edit_element_target.get("model_variant") or "").strip() or None,
        )
    else:
        edit_element_dialog(str(edit_element_target))

yamazumi_area_ids = list(area_labels)


def current_editor_draft(editor_rows: pd.DataFrame, editor_key: str) -> pd.DataFrame:
    """Capture cell/new-row edits while treating native row deletion as selection."""
    state = st.session_state.get(editor_key, {}) or {}
    draft = editor_rows.copy()
    for raw_position, changes in (state.get("edited_rows") or {}).items():
        position = int(raw_position)
        if not 0 <= position < len(draft):
            continue
        for column, value in (changes or {}).items():
            if column == "selected":
                continue
            if column in draft.columns:
                draft.at[draft.index[position], column] = value
    added_rows = state.get("added_rows") or []
    if added_rows:
        draft = pd.concat(
            [draft, pd.DataFrame(added_rows, columns=draft.columns)],
            ignore_index=True,
            sort=False,
        )
    return draft.reset_index(drop=True)


def editor_edit_count(editor_key: str) -> int:
    """Count edited/new rows without counting row selection."""
    state = st.session_state.get(editor_key, {}) or {}
    edited_rows = state.get("edited_rows") or {}
    edit_count = sum(
        1
        for changes in edited_rows.values()
        if isinstance(changes, dict) and any(k != "selected" for k in changes)
    )
    return edit_count + len(state.get("added_rows") or [])


area_id_by_name = {name: aid for aid, name in area_labels.items()}

with yamazumi_tables_tab:
    area_table_editor_key = apply_pending_table_editor_reset(
        f"yamazumi_area_table_editor_{scenario_id}"
    )
    editable_table_heading("Yamazumi Area")
    area_table_rows: list[dict[str, object]] = []
    for _, area_row in areas.iterrows():
        raw_area_takt = area_row.get("takt_override_s")
        try:
            row_takt_s = (
                float(raw_area_takt)
                if raw_area_takt is not None
                and not pd.isna(raw_area_takt)
                and math.isfinite(float(raw_area_takt))
                and float(raw_area_takt) > 0
                else (default_takt if default_takt > 0 else 60.0)
            )
        except (TypeError, ValueError):
            row_takt_s = default_takt if default_takt > 0 else 60.0
        raw_conveyor = str(area_row.get("conveyor_type") or "2-sided").strip()
        row_conveyor = raw_conveyor if raw_conveyor in CONVEYOR_TYPES else "2-sided"
        area_table_rows.append(
            {
                "id": str(area_row["id"]),
                "name": str(area_row["name"]),
                "area_takt_display": float(seconds_to_display(row_takt_s, takt_time_unit)),
                "conveyor_type": row_conveyor,
                "updated_at": str(area_row.get("updated_at") or ""),
            }
        )
    if area_table_rows:
        area_table_df = pd.DataFrame(area_table_rows)
    else:
        area_table_df = pd.DataFrame(
            {
                "id": pd.Series(dtype="string"),
                "name": pd.Series(dtype="string"),
                "area_takt_display": pd.Series(dtype="float64"),
                "conveyor_type": pd.Series(dtype="string"),
                "updated_at": pd.Series(dtype="string"),
            }
        )
    edited_area_table = st.data_editor(
        area_table_df,
        column_order=["name", "area_takt_display", "conveyor_type"],
        disabled=["id", "name", "updated_at"],
        hide_index=True,
        num_rows="fixed",
        width="stretch",
        key=area_table_editor_key,
        column_config={
            "id": None,
            "name": st.column_config.TextColumn(
                "Yamazumi Area",
                help="Balancing area in the active planning scenario.",
            ),
            "area_takt_display": st.column_config.NumberColumn(
                "Area Takt Time",
                min_value=0.0,
                step=min(float(takt_config.step), 0.01),
                format=f"%.{takt_config.decimals}f",
                required=True,
                help=(
                    f"Target takt time for this Yamazumi area in {takt_config.label}. "
                    "Initially set to the current scenario rev takt time."
                ),
            ),
            "conveyor_type": st.column_config.SelectboxColumn(
                "Conveyor Type",
                options=CONVEYOR_TYPES,
                required=True,
                help="Select whether this pitch area uses a 1-sided or 2-sided conveyor.",
            ),
            "updated_at": None,
        },
    )
    area_table_actions = editable_table_footer(
        editor_key=area_table_editor_key,
        key_prefix=f"yamazumi_area_table_{scenario_id}",
    )
    if area_table_actions.undo:
        st.toast("Discarded unsaved Yamazumi area edits", icon=":material/undo:")
        request_table_editor_reset(area_table_editor_key)
        st.rerun()
    if area_table_actions.save_and_refresh:
        try:
            area_draft_df = current_editor_draft(area_table_df, area_table_editor_key)
            if isinstance(edited_area_table, pd.DataFrame) and len(edited_area_table) == len(area_draft_df):
                for col in ("area_takt_display", "conveyor_type"):
                    if col in edited_area_table.columns:
                        area_draft_df[col] = edited_area_table[col].values
            area_req_errors = required_field_errors(
                area_draft_df,
                {
                    "area_takt_display": "Area Takt Time",
                    "conveyor_type": "Conveyor Type",
                },
            )
            if area_req_errors:
                raise ValueError(" ".join(area_req_errors))
            save_area_rows: list[dict[str, object]] = []
            for _, row in area_draft_df.iterrows():
                display_val = row.get("area_takt_display")
                try:
                    numeric_display = float(display_val)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Area Takt Time for '{row.get('name') or 'Yamazumi area'}' must be greater than zero."
                    ) from exc
                if not math.isfinite(numeric_display) or numeric_display <= 0:
                    raise ValueError(
                        f"Area Takt Time for '{row.get('name') or 'Yamazumi area'}' must be greater than zero."
                    )
                save_area_rows.append(
                    {
                        "id": str(row.get("id") or ""),
                        "takt_override_s": float(
                            display_to_seconds(numeric_display, takt_time_unit)
                        ),
                        "conveyor_type": str(row.get("conveyor_type") or "").strip(),
                    }
                )
            area_save_result = update_yamazumi_areas_table(
                project_id,
                scenario_id,
                pd.DataFrame(save_area_rows),
                st.session_state.get("current_editor", ""),
            )
            for saved_row in save_area_rows:
                st.session_state.pop(
                    f"yamazumi_takt_{scenario_id}_{saved_row['id']}_{takt_time_unit}",
                    None,
                )
                st.session_state.pop(
                    f"yamazumi_takt_db_synced_{scenario_id}_{saved_row['id']}_{takt_time_unit}",
                    None,
                )
            request_table_editor_reset(area_table_editor_key)
            updated_area_count = int(area_save_result.get("updated_count") or 0)
            st.toast(
                f"Saved Yamazumi Area settings ({updated_area_count} area(s) updated)"
                if updated_area_count
                else "Saved Yamazumi Area settings",
                icon=":material/check_circle:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    st.divider()

    effective_pitch_area_ids = list(yamazumi_area_ids)
    pitch_combined_view = True
    effective_element_area_ids = list(yamazumi_area_ids)
    element_combined_view = True
    pitch_save_scope = (
        effective_pitch_area_ids if len(effective_pitch_area_ids) > 1 else area_id
    )
    element_save_scope = (
        effective_element_area_ids if len(effective_element_area_ids) > 1 else area_id
    )

    pitch_table_source = yamazumi_pitches_for_scenario(project_id, scenario_id)
    pitch_table_source = pitch_table_source.loc[
        pitch_table_source["area_id"].astype(str).isin(effective_pitch_area_ids)
    ].copy()
    if not pitch_table_source.empty:
        pitch_table_source["model_variants"] = [
            [
                stored_variant_labels.get(item, item)
                for item in json.loads(value or '["All models"]')
            ]
            for value in pitch_table_source["model_variants"]
        ]

    element_table_source = yamazumi_elements_for_scenario(project_id, scenario_id)
    element_table_source = element_table_source.loc[
        element_table_source["area_id"].astype(str).isin(effective_element_area_ids)
    ].copy()
    if not element_table_source.empty:
        element_table_source["model_variants"] = [
            [
                stored_variant_labels.get(item, item)
                for item in parse_yamazumi_model_variants(
                    mv, str(m_single or "All models")
                )
            ]
            for mv, m_single in zip(
                element_table_source["model_variants"],
                element_table_source["model_variant"],
            )
        ]
        element_table_source["criticality"] = [
            criticality_for_process_link(val)
            for val in element_table_source["process_element_id"]
        ]
    element_table_pitches = pitch_table_source.copy()

    table_defined_work_regions: set[str] = set()
    for target_aid in yamazumi_area_ids:
        region_defs = yamazumi_work_regions(project_id, str(target_aid))
        if not region_defs.empty:
            table_defined_work_regions.update(
                region_defs.loc[
                    region_defs["active"].fillna(1).astype(bool), "name"
                ].dropna().astype(str)
            )
    table_legacy_work_regions = sorted(
        {
            str(value).strip()
            for value in element_table_source.get("work_region", pd.Series(dtype=str)).dropna()
            if str(value).strip()
            and str(value).strip() != "None"
            and str(value).strip() not in table_defined_work_regions
        }
    )
    table_work_region_options = [
        "None",
        *sorted(table_defined_work_regions),
        *table_legacy_work_regions,
    ]
    table_legacy_variant_options = [
        value
        for series in (
            pitch_table_source.get("model_variants", pd.Series(dtype=object)),
            element_table_source.get("model_variants", pd.Series(dtype=object)),
        )
        for values in series
        for value in (values or [])
        if value not in defined_variant_options
    ]
    table_variant_options = list(
        dict.fromkeys([*defined_variant_options, *table_legacy_variant_options])
    )
    table_pitch_label_by_id = (
        {
            str(pid): yamazumi_pitch_label(pnum, pname)
            for pid, pnum, pname in zip(
                pitch_table_source["id"],
                pitch_table_source["pitch_number"],
                pitch_table_source["pitch_name"],
            )
        }
        if not pitch_table_source.empty
        else {}
    )

    editable_table_heading("Pitch Addresses")
    pitch_columns = [
        "id", "area_id", "selected", "area_name", "pitch_number", "pitch_name", "pitch_type", "status",
        "feeds_into_pitch_id", "feed_target", "feed_target_status",
        "model_variants", "sequence", "updated_at",
    ]
    if pitch_table_source.empty:
        pitch_rows = pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "selected": pd.Series(dtype="bool"),
            "area_name": pd.Series(dtype="string"),
            "pitch_number": pd.Series(dtype="string"),
            "pitch_name": pd.Series(dtype="string"),
            "pitch_type": pd.Series(dtype="string"),
            "status": pd.Series(dtype="string"),
            "feeds_into_pitch_id": pd.Series(dtype="string"),
            "feed_target": pd.Series(dtype="string"),
            "feed_target_status": pd.Series(dtype="string"),
            # MultiselectColumn values are lists, so this column deliberately uses object dtype.
            "model_variants": pd.Series(dtype="object"),
            "sequence": pd.Series(dtype="Int64"),
            "updated_at": pd.Series(dtype="string"),
        })
    else:
        pitch_rows = pitch_table_source.reindex(columns=pitch_columns).copy()
        pitch_rows["selected"] = pd.Series(False, index=pitch_rows.index, dtype="bool")
        pitch_rows["feed_target"] = [
            table_pitch_label_by_id.get(str(value), "")
            if value is not None and not pd.isna(value) else ""
            for value in pitch_rows["feeds_into_pitch_id"]
        ]
        pitch_rows["feed_target_status"] = [
            yamazumi_pitch_feed_target_status(ptype, ftarget)
            for ptype, ftarget in zip(
                pitch_rows["pitch_type"], pitch_rows["feeds_into_pitch_id"]
            )
        ]
    pitch_filter_scope = "combined"
    visible_pitches = filter_table(
        pitch_rows,
        key=f"yamazumi_pitch_filters_{scenario_id}_{pitch_filter_scope}",
        dropdown_columns=["area_name", "pitch_type", "status", "model_variants"],
        search_columns=["area_name", "pitch_number", "pitch_name", "pitch_type", "status", "feed_target", "feed_target_status", "model_variants"],
        labels={
            "area_name": "Yamazumi Area",
            "pitch_type": "Pitch Type",
            "status": "Status",
            "model_variants": "Model Variant",
        },
        multi_value_columns=["model_variants"],
        reset_widget_keys=[pitch_editor_key],
    )
    pitch_column_order = [
        "selected", "area_name", "pitch_number", "pitch_name", "pitch_type", "status",
        "feed_target", "feed_target_status", "model_variants", "sequence",
    ]
    pitch_area_name_options = [area_labels[aid] for aid in effective_pitch_area_ids if aid in area_labels]
    table_feed_target_options = [""] + [
        lbl for lbl in dict.fromkeys(table_pitch_label_by_id.values()) if lbl
    ]
    pitch_column_config = {
        "id": None,
        "area_id": None,
        "selected": st.column_config.CheckboxColumn(
            "Select",
            default=False,
            pinned=True,
            width="small",
            help="Select one or more pitches to delete, copy to another planning scenario, or move to another Yamazumi area.",
        ),
        "area_name": st.column_config.SelectboxColumn(
            "Yamazumi Area",
            options=pitch_area_name_options,
            required=True,
            default=str(area["name"]),
        ),
        "pitch_number": st.column_config.TextColumn(
            "Pitch Address",
            required=True,
            help="Use the physical line address/nomenclature. It must be unique across every Yamazumi area in this planning scenario; capitalization and surrounding spaces are ignored when checking duplicates.",
        ),
        "pitch_name": st.column_config.TextColumn("Pitch Name"),
        "pitch_type": st.column_config.SelectboxColumn("Pitch Type", options=PITCH_TYPES, required=True, default="Pitch"),
        "status": st.column_config.SelectboxColumn("Status", options=["Active", "Blocked", "Open"], required=True, default="Active"),
        "feeds_into_pitch_id": None,
        "feed_target": st.column_config.SelectboxColumn(
            "Feeds Into Pitch",
            options=table_feed_target_options,
            help="Shown for Subassembly and Kitter pitches. Choose a same-area target here or in Edit Pitch on the Interactive Yamazumi board.",
        ),
        "feed_target_status": st.column_config.TextColumn(
            "Feed Target Status",
            help="Compatibility-null feeder pitches remain visibly unclassified until manually edited.",
        ),
        "model_variants": st.column_config.MultiselectColumn(
            "Model Variants",
            options=table_variant_options,
            required=True,
            default=["All models"],
            help="Only these variants appear as stacks on this pitch.",
        ),
        "sequence": st.column_config.NumberColumn("Order", min_value=1, step=1, format="%d"),
        "updated_at": None,
    }
    pitch_editor_rows = direct_entry_editor_rows(
        visible_pitches,
        editor_key=pitch_editor_key,
        sort_columns=[
            "area_name", "pitch_number", "pitch_name", "pitch_type", "status",
            "model_variants", "sequence"
        ],
        labels={
            "area_name": "Yamazumi Area", "pitch_number": "Pitch Address",
            "pitch_name": "Pitch Name", "pitch_type": "Pitch Type",
            "model_variants": "Model Variants", "sequence": "Order",
        },
    )
    _pitch_editor_row_ids = (
        pitch_editor_rows["id"].fillna("").astype(str).tolist()
        if "id" in pitch_editor_rows.columns
        else []
    )
    st.session_state[f"{pitch_editor_key}__row_ids"] = _pitch_editor_row_ids
    st.session_state[f"{logical_table_editor_key(pitch_editor_key)}__row_ids"] = _pitch_editor_row_ids
    pitch_disabled_cols = ["id", "area_id", "feeds_into_pitch_id", "feed_target_status", "updated_at"]
    edited_pitches = st.data_editor(
        pitch_editor_rows,
        key=pitch_editor_key,
        hide_index=True,
        num_rows="dynamic",
        height=280,
        disabled=pitch_disabled_cols,
        column_order=pitch_column_order,
        column_config=pitch_column_config,
    )
    selected_pitches = native_selected_rows(
        pitch_editor_rows, editor_key=pitch_editor_key
    )
    pitch_selected_mask = (
        edited_pitches["selected"].fillna(False).astype(bool).copy()
        if "selected" in edited_pitches.columns
        else pd.Series(False, index=edited_pitches.index, dtype="bool")
    )
    pitch_editor_state = st.session_state.get(pitch_editor_key, {}) or {}
    for raw_pos, row_changes in (pitch_editor_state.get("edited_rows") or {}).items():
        try:
            pos = int(raw_pos)
        except (ValueError, TypeError):
            continue
        if (
            0 <= pos < len(pitch_selected_mask)
            and isinstance(row_changes, dict)
            and "selected" in row_changes
        ):
            pitch_selected_mask.iat[pos] = bool(row_changes["selected"])
    move_selected_pitches = edited_pitches.loc[pitch_selected_mask].copy()
    if not move_selected_pitches.empty and "id" in move_selected_pitches.columns:
        move_selected_pitches = move_selected_pitches.loc[
            move_selected_pitches["id"].notna()
            & move_selected_pitches["id"].astype(str).str.strip().ne("")
        ].copy()
    move_selected_ids = (
        [
            str(pid)
            for pid in move_selected_pitches["id"].dropna().astype(str).tolist()
            if str(pid).strip()
        ]
        if not move_selected_pitches.empty and "id" in move_selected_pitches.columns
        else []
    )
    pitch_has_unsaved_edits = table_has_unsaved_changes(
        pitch_editor_key, native_row_selection=True
    )
    delete_pitch_disabled = has_board_draft
    copy_pitch_disabled = (
        pitch_has_unsaved_edits
        or not selected_pitches.empty
        or has_board_draft
    )
    move_pitch_disabled = (
        len(area_labels) < 2
        or pitch_has_unsaved_edits
        or not selected_pitches.empty
        or has_board_draft
    )
    pitch_actions = editable_table_footer(
        editor_key=pitch_editor_key,
        key_prefix="yamazumi_pitches",
        native_row_selection=True,
        delete_action_label="Delete Pitches",
        delete_action_icon=":material/delete:",
        delete_action_key=f"yamazumi_delete_pitches_request_{scenario_id}_{area_id}",
        delete_action_disabled=delete_pitch_disabled,
        delete_action_help=(
            "Save or undo current Yamazumi board changes first."
            if delete_pitch_disabled
            else "Select one or more pitches in the Select column and click Delete Pitches to remove them."
        ),
        secondary_action_label="Copy Pitches",
        secondary_action_icon=":material/content_copy:",
        secondary_action_key=f"yamazumi_copy_pitches_request_{scenario_id}_{area_id}",
        secondary_action_disabled=copy_pitch_disabled,
        secondary_action_help=(
            "Clear the delete row selection in the Pitch Addresses table first."
            if not selected_pitches.empty
            else (
                "Save or undo other Yamazumi changes first."
                if copy_pitch_disabled
                else "Select one or more pitches in the Select column and click Copy Pitches to copy them to another planning scenario."
            )
        ),
        additional_action_label="Move Pitches",
        additional_action_icon=":material/drive_file_move:",
        additional_action_key=f"yamazumi_move_pitches_request_{scenario_id}_{area_id}",
        additional_action_disabled=move_pitch_disabled,
        additional_action_help=(
            "At least two Yamazumi areas are required in this scenario before moving pitches."
            if len(area_labels) < 2
            else (
                "Clear the delete row selection in the Pitch Addresses table first."
                if not selected_pitches.empty
                else (
                    "Save or undo other Yamazumi changes first."
                    if move_pitch_disabled
                    else "Select one or more pitches in the Select column and click Move Pitches to move them to another Yamazumi area."
                )
            )
        ),
    )
    if pitch_actions.delete_action and move_selected_pitches.empty and selected_pitches.empty:
        st.warning(
            "Select one or more pitches in the Select column before clicking Delete Pitches."
        )
    if pitch_actions.secondary_action:
        close_other_yamazumi_dialogs(copy_pitch_dialog_key)
        st.session_state[copy_pitch_dialog_key] = move_selected_ids or True
        st.rerun()
    if pitch_actions.additional_action:
        close_other_yamazumi_dialogs(move_pitch_dialog_key)
        st.session_state[move_pitch_dialog_key] = move_selected_ids or True
        st.rerun()
    if pitch_actions.undo:
        st.toast("Discarded the unsaved pitch-address edits", icon=":material/undo:")
        request_table_editor_reset(pitch_editor_key)
        st.rerun()
    pitches_to_delete = (
        selected_pitches
        if not selected_pitches.empty
        else (
            move_selected_pitches
            if pitch_actions.delete_action and not move_selected_pitches.empty
            else pd.DataFrame()
        )
    )
    request_pitch_delete = not pitches_to_delete.empty
    if request_pitch_delete:
        selected_pitch_ids = set(pitches_to_delete["id"].astype(str))
        close_other_yamazumi_dialogs("")
        st.session_state.pop(element_delete_key, None)
        st.session_state[pitch_delete_key] = {
            "pitches": [
                {
                    "id": str(row["id"]),
                    "source_pitch_id": str(row["id"]),
                    "pitch_number": str(row.get("pitch_number") or ""),
                    "source_pitch_address": str(row.get("pitch_number") or ""),
                    "pitch_name": str(row.get("pitch_name") or ""),
                    "old_feeds_into_pitch_id": (
                        str(row.get("feeds_into_pitch_id"))
                        if row.get("feeds_into_pitch_id") is not None
                        and not pd.isna(row.get("feeds_into_pitch_id"))
                        else None
                    ),
                    "old_feed_target": table_pitch_label_by_id.get(
                        str(row.get("feeds_into_pitch_id")), ""
                    ),
                    "new_feeds_into_pitch_id": None,
                    "new_feed_target": None,
                    "assigned_element_count": int(
                        element_table_source["pitch_id"].fillna("").astype(str).eq(str(row["id"])).sum()
                    ) if not element_table_source.empty else 0,
                }
                for _, row in pitches_to_delete.iterrows()
                if str(row["id"]) in selected_pitch_ids
            ],
            "pitch_draft": current_editor_draft(
                pitch_editor_rows, pitch_editor_key
            ).to_dict("records"),
            "other_pitch_edits": table_has_unsaved_changes(
                pitch_editor_key, native_row_selection=True
            ),
            "pitch_edit_count": editor_edit_count(pitch_editor_key),
            "feed_reference_blockers": yamazumi_pitch_delete_blockers(
                project_id,
                pitch_save_scope,
                list(selected_pitch_ids),
            ),
        }
        stage_native_delete_confirmation(pitch_editor_key)
    _lazy_yamazumi_export = (
        getattr(dataframe_to_excel, "__module__", "") == "utils.table_ui"
    )
    st.download_button(
        "Export Filtered Pitches",
        data=(
            (
                lambda _df=visible_pitches: dataframe_to_excel(
                    _df.drop(columns=["id", "area_id", "selected", "updated_at"], errors="ignore"),
                    "Pitch addresses",
                )
            )
            if _lazy_yamazumi_export
            else dataframe_to_excel(
                visible_pitches.drop(columns=["id", "area_id", "selected", "updated_at"], errors="ignore"),
                "Pitch addresses",
            )
        ),
        file_name=(
            "yamazumi_pitch_addresses_multiple_areas_filtered.xlsx"
            if pitch_combined_view else "yamazumi_pitch_addresses_filtered.xlsx"
        ),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        key=f"export_yamazumi_pitches_{scenario_id}_{pitch_filter_scope}",
    )
    if pitch_actions.save_and_refresh:
        try:
            if not selected_pitches.empty:
                raise ValueError("Clear selected rows before saving pitch edits.")
            edited_pitches = drop_untouched_new_rows(
                edited_pitches, identifying_columns=["pitch_number"]
            )
            errors = required_field_errors(edited_pitches, {"pitch_number": "Pitch address", "status": "Status"})
            if errors:
                raise ValueError(" ".join(errors))
            to_save = merge_filtered_edits(pitch_rows, visible_pitches, edited_pitches)
            to_save = to_save.drop(columns=["selected"], errors="ignore")
            to_save["area_id"] = (
                to_save["area_name"].map(area_id_by_name)
                .fillna(to_save.get("area_id"))
                .fillna(str(area_id))
            )
            feed_target_id_by_label = {
                label: pitch_id for pitch_id, label in table_pitch_label_by_id.items()
            }
            to_save["feeds_into_pitch_id"] = to_save["feed_target"].map(
                feed_target_id_by_label
            )
            before_pitch_rows = (
                yamazumi_pitches_for_scenario(project_id, scenario_id).loc[
                    lambda df: df["area_id"].astype(str).isin(effective_pitch_area_ids)
                ].copy()
            )
            count = replace_yamazumi_pitches(project_id, pitch_save_scope, to_save)
            after_pitch_rows = (
                yamazumi_pitches_for_scenario(project_id, scenario_id).loc[
                    lambda df: df["area_id"].astype(str).isin(effective_pitch_area_ids)
                ].copy()
            )
            before_by_id = {
                str(row["id"]): row for _, row in before_pitch_rows.iterrows()
            }
            all_labels = {
                str(row["id"]): yamazumi_pitch_label(
                    row["pitch_number"], row["pitch_name"]
                )
                for frame in (before_pitch_rows, after_pitch_rows)
                for _, row in frame.iterrows()
            }
            feed_changes = []
            for _, row in after_pitch_rows.iterrows():
                source_id = str(row["id"])
                old_row = before_by_id.get(source_id)
                old_target_id = (
                    str(old_row.get("feeds_into_pitch_id") or "").strip() or None
                    if old_row is not None else None
                )
                new_target_id = str(row.get("feeds_into_pitch_id") or "").strip() or None
                if old_target_id != new_target_id:
                    feed_changes.append(
                        {
                            "source_pitch_id": source_id,
                            "source_pitch_address": str(row["pitch_number"]),
                            "old_feeds_into_pitch_id": old_target_id,
                            "old_feed_target": all_labels.get(str(old_target_id), ""),
                            "new_feeds_into_pitch_id": new_target_id,
                            "new_feed_target": all_labels.get(str(new_target_id), ""),
                        }
                    )
            record_audit_event(
                project_id,
                "Yamazumi pitches",
                "Save & Refresh",
                count,
                st.session_state.get("current_editor", ""),
                {"area_id": pitch_save_scope, "feed_relationship_changes": feed_changes},
            )
            for _, row in after_pitch_rows.iterrows():
                _clear_edit_pitch_widget_state(row.get("id"))
            st.toast(
                f"Saved {count} pitch address(es)"
                + (f" ({len(feed_changes)} feed link(s) updated)" if feed_changes else ""),
                icon=":material/check_circle:",
            )
            request_table_editor_reset(pitch_editor_key)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    st.divider()
    editable_table_heading("Yamazumi Work Elements")
    active_pitches = (
        element_table_pitches.loc[element_table_pitches["status"] == "Active"].copy()
        if not element_table_pitches.empty else element_table_pitches
    )
    pitch_label_by_id = dict(zip(active_pitches["id"].astype(str), active_pitches["pitch_number"].astype(str))) if not active_pitches.empty else {}
    element_pitch_variants_by_id = {
        str(row["id"]): list(row["model_variants"] or ["All models"])
        for _, row in active_pitches.iterrows()
    } if not active_pitches.empty else {}
    element_columns = [
        "id", "area_id", "selected", "area_name", "pitch_id", "model_variants", "work_type", "description", "time_s", "work_region",
        "criticality", "sequence", "source", "process_element_id", "process_sync_status", "updated_at",
    ]
    if element_table_source.empty:
        element_rows = pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "selected": pd.Series(dtype="bool"),
            "area_name": pd.Series(dtype="string"),
            "pitch_id": pd.Series(dtype="string"),
            # MultiselectColumn values are lists, so this column deliberately uses object dtype.
            "model_variants": pd.Series(dtype="object"),
            "work_type": pd.Series(dtype="string"),
            "description": pd.Series(dtype="string"),
            "time_s": pd.Series(dtype="Float64"),
            "work_region": pd.Series(dtype="string"),
            "criticality": pd.Series(dtype="object"),
            "sequence": pd.Series(dtype="Int64"),
            "source": pd.Series(dtype="string"),
            "process_element_id": pd.Series(dtype="string"),
            "process_sync_status": pd.Series(dtype="string"),
            "updated_at": pd.Series(dtype="string"),
        })
        element_rows["pitch"] = pd.Series(dtype="string")
    else:
        element_rows = element_table_source.reindex(columns=element_columns).copy()
        element_rows["selected"] = pd.Series(False, index=element_rows.index, dtype="bool")
        element_rows["pitch"] = [
            pitch_label_by_id.get(str(value), "Unassigned") if value is not None and not pd.isna(value) else "Unassigned"
            for value in element_rows["pitch_id"]
        ]
    element_rows["time_s"] = (
        pd.to_numeric(element_rows["time_s"], errors="coerce")
        / time_config.seconds_per_unit
    )
    element_filter_scope = "combined"
    visible_elements = filter_table(
        element_rows,
        key=f"yamazumi_element_filters_{scenario_id}_{element_filter_scope}",
        dropdown_columns=["area_name", "pitch", "model_variants", "work_type", "work_region", "criticality"],
        search_columns=["area_name", "description", "pitch", "model_variants", "work_region", "criticality"],
        labels={"area_name": "Yamazumi Area", "model_variants": "Model Variant", "criticality": "Criticality"},
        multi_value_columns=["model_variants", "criticality"],
        reset_widget_keys=[element_editor_key],
    )
    pitch_options = ["Unassigned", *pitch_label_by_id.values()]
    variant_options_by_pitch_label = {
        pitch_label_by_id[pitch_id]: element_pitch_variants_by_id.get(pitch_id, ["All models"])
        for pitch_id in pitch_label_by_id
    }
    element_column_order = [
        "selected", "area_name", "pitch", "model_variants", "work_type", "description", "time_s",
        "work_region", "criticality", "sequence",
    ]
    element_area_name_options = [area_labels[aid] for aid in effective_element_area_ids if aid in area_labels]
    element_column_config = {
        "id": None,
        "area_id": None,
        "selected": st.column_config.CheckboxColumn(
            "Select",
            default=False,
            pinned=True,
            width="small",
            help="Select one or more work elements to delete or copy immediately beneath each selected work element.",
        ),
        "area_name": st.column_config.SelectboxColumn(
            "Yamazumi Area",
            options=element_area_name_options,
            required=True,
            default=str(area["name"]),
        ),
        "pitch_id": None,
        "pitch": st.column_config.SelectboxColumn("Pitch", options=pitch_options, required=True, default="Unassigned"),
        "model_variants": st.column_config.MultiselectColumn(
            "Model Variants",
            options=table_variant_options,
            required=True,
            default=["All models"],
            help="Choose every model stack where this same work element applies.",
        ),
        "work_type": st.column_config.SelectboxColumn("Work Type", options=WORK_TYPES, required=True, default="Cycle"),
        "description": st.column_config.TextColumn("Work Description", required=True, width="large"),
        "time_s": st.column_config.NumberColumn(
            time_column_label,
            min_value=0.0,
            step=time_config.step,
            format=f"%.{time_config.decimals}f",
            required=True,
        ),
        "work_region": st.column_config.SelectboxColumn(
            "Work Region", options=table_work_region_options, required=True, default="None"
        ),
        "criticality": st.column_config.MultiselectColumn(
            "Criticality",
            options=["CTQ", "Safety"],
            color=["orange", "red"],
            disabled=True,
            help=(
                "CTQ comes from qualifying PFMEA Classification codes. Safety comes "
                "from active Safety requirements linked to the Process step."
            ),
        ),
        "sequence": st.column_config.NumberColumn("Order", min_value=1, step=1, format="%d"),
        "source": None,
        "process_element_id": None,
        "process_sync_status": None,
        "updated_at": None,
    }
    element_editor_rows = direct_entry_editor_rows(
        visible_elements,
        editor_key=element_editor_key,
        sort_columns=[
            "area_name", "pitch", "model_variants", "work_type", "description", "time_s",
            "work_region", "criticality", "sequence",
        ],
        labels={
            "area_name": "Yamazumi Area", "model_variants": "Model Variants",
            "work_type": "Work Type", "description": "Work Description",
            "time_s": time_column_label,
            "work_region": "Work Region", "sequence": "Order",
        },
    )
    element_disabled_cols = ["id", "area_id", "criticality", "source", "process_element_id", "process_sync_status", "updated_at"]
    edited_elements = st.data_editor(
        element_editor_rows,
        key=element_editor_key,
        hide_index=True,
        num_rows="dynamic",
        height=420,
        disabled=element_disabled_cols,
        column_order=element_column_order,
        column_config=element_column_config,
    )
    selected_elements = native_selected_rows(
        element_editor_rows, editor_key=element_editor_key
    )
    element_selected_mask = (
        edited_elements["selected"].fillna(False).astype(bool).copy()
        if "selected" in edited_elements.columns
        else pd.Series(False, index=edited_elements.index, dtype="bool")
    )
    element_editor_state = st.session_state.get(element_editor_key, {}) or {}
    for raw_pos, row_changes in (element_editor_state.get("edited_rows") or {}).items():
        try:
            pos = int(raw_pos)
        except (ValueError, TypeError):
            continue
        if (
            0 <= pos < len(element_selected_mask)
            and isinstance(row_changes, dict)
            and "selected" in row_changes
        ):
            element_selected_mask.iat[pos] = bool(row_changes["selected"])
    copy_selected_elements = edited_elements.loc[element_selected_mask].copy()
    if not copy_selected_elements.empty and "id" in copy_selected_elements.columns:
        copy_selected_elements = copy_selected_elements.loc[
            copy_selected_elements["id"].notna()
            & copy_selected_elements["id"].astype(str).str.strip().ne("")
        ].copy()
    copy_selected_element_ids = (
        [
            str(eid)
            for eid in copy_selected_elements["id"].dropna().astype(str).tolist()
            if str(eid).strip()
        ]
        if not copy_selected_elements.empty and "id" in copy_selected_elements.columns
        else []
    )
    element_has_unsaved_edits = table_has_unsaved_changes(
        element_editor_key, native_row_selection=True
    )
    delete_element_disabled = has_board_draft
    copy_element_disabled = (
        element_has_unsaved_edits
        or not selected_elements.empty
        or has_board_draft
    )
    element_actions = editable_table_footer(
        editor_key=element_editor_key,
        key_prefix="yamazumi_elements",
        native_row_selection=True,
        delete_action_label="Delete Work Element",
        delete_action_icon=":material/delete:",
        delete_action_key=f"yamazumi_delete_elements_request_{scenario_id}_{area_id}",
        delete_action_disabled=delete_element_disabled,
        delete_action_help=(
            "Save or undo current Yamazumi board changes first."
            if delete_element_disabled
            else "Select one or more work elements in the Select column and click Delete Work Element to remove them."
        ),
        additional_action_label="Copy Work Element",
        additional_action_icon=":material/content_copy:",
        additional_action_key=f"yamazumi_copy_elements_request_{scenario_id}_{area_id}",
        additional_action_disabled=copy_element_disabled,
        additional_action_help=(
            "Clear the delete row selection in the Yamazumi Work Elements table first."
            if not selected_elements.empty
            else (
                "Save or undo other Yamazumi changes first."
                if copy_element_disabled
                else "Select one or more work elements in the Select column and click Copy Work Element to duplicate each selected work element immediately beneath itself."
            )
        ),
    )
    if element_actions.delete_action and copy_selected_elements.empty and selected_elements.empty:
        st.warning(
            "Select one or more work elements in the Select column before clicking Delete Work Element."
        )
    if element_actions.additional_action:
        if not copy_selected_element_ids:
            st.warning(
                "Select one or more work elements in the Select column before clicking Copy Work Element."
            )
        else:
            try:
                copy_result = duplicate_yamazumi_elements(
                    project_id,
                    scenario_id,
                    copy_selected_element_ids,
                    editor_name=st.session_state.get("current_editor", ""),
                )
                st.session_state.pop(board_draft_key, None)
                request_table_editor_reset(element_editor_key)
                st.toast(
                    f"Copied {copy_result['copied_count']} Yamazumi work element(s)",
                    icon=":material/check_circle:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    if element_actions.undo:
        st.toast("Discarded the unsaved work-element edits", icon=":material/undo:")
        request_table_editor_reset(element_editor_key)
        st.rerun()
    elements_to_delete = (
        selected_elements
        if not selected_elements.empty
        else (
            copy_selected_elements
            if element_actions.delete_action and not copy_selected_elements.empty
            else pd.DataFrame()
        )
    )
    request_element_delete = not elements_to_delete.empty
    if request_element_delete:
        close_other_yamazumi_dialogs("")
        st.session_state.pop(pitch_delete_key, None)
        selected_element_impacts = [
            yamazumi_element_delete_impact(
                project_id,
                scenario_id,
                str(row.get("area_id") or area_id),
                str(row["id"]),
            )
            for _, row in elements_to_delete.iterrows()
        ]
        st.session_state[element_delete_key] = {
            "elements": [
                {
                    "id": str(row["id"]),
                    "area_id": str(row.get("area_id") or area_id),
                    "area_name": str(row.get("area_name") or ""),
                    "description": str(row.get("description") or ""),
                    "pitch": str(row.get("pitch") or "Unassigned"),
                    "process_element_id": str(
                        row.get("process_element_id") or ""
                    ),
                    "process_step_exists": bool(impact["process_step_exists"]),
                    "legacy_material_group_count": int(
                        impact["legacy_material_group_count"] or 0
                    ),
                    "legacy_material_option_count": int(
                        impact["legacy_material_option_count"] or 0
                    ),
                }
                for (_, row), impact in zip(
                    elements_to_delete.iterrows(), selected_element_impacts
                )
            ],
            "element_draft": current_editor_draft(
                element_editor_rows, element_editor_key
            ).to_dict("records"),
            "pitch_draft": current_editor_draft(
                pitch_editor_rows, pitch_editor_key
            ).to_dict("records"),
            "other_element_edits": table_has_unsaved_changes(
                element_editor_key, native_row_selection=True
            ),
            "element_edit_count": editor_edit_count(element_editor_key),
            "other_pitch_edits": table_has_unsaved_changes(
                pitch_editor_key, native_row_selection=True
            ),
            "pitch_edit_count": editor_edit_count(pitch_editor_key),
        }
        stage_native_delete_confirmation(element_editor_key)
    st.download_button(
        "Export Filtered Work Elements",
        data=(
            (
                lambda _df=visible_elements, _label=export_time_column_label: dataframe_to_excel(
                    _df.rename(
                        columns={"time_s": _label}
                    ).drop(
                        columns=["id", "area_id", "selected", "pitch_id", "process_element_id", "updated_at"],
                        errors="ignore",
                    ),
                    "Yamazumi work elements",
                )
            )
            if _lazy_yamazumi_export
            else dataframe_to_excel(
                visible_elements.rename(
                    columns={"time_s": export_time_column_label}
                ).drop(
                    columns=["id", "area_id", "selected", "pitch_id", "process_element_id", "updated_at"],
                    errors="ignore",
                ),
                "Yamazumi work elements",
            )
        ),
        file_name=(
            "yamazumi_work_elements_multiple_areas_filtered.xlsx"
            if element_combined_view else "yamazumi_work_elements_filtered.xlsx"
        ),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        key=f"export_yamazumi_elements_{scenario_id}_{element_filter_scope}",
    )
    if element_actions.save_and_refresh:
        try:
            if not selected_elements.empty:
                raise ValueError("Clear selected rows before saving work-element edits.")
            edited_elements = drop_untouched_new_rows(
                edited_elements, identifying_columns=["description"]
            )
            errors = required_field_errors(edited_elements, {"model_variants": "Model variants", "description": "Work description", "work_region": "Work region"})
            if errors:
                raise ValueError(" ".join(errors))
            pitch_id_by_label = {label: pitch_id for pitch_id, label in pitch_label_by_id.items()}
            to_save = merge_filtered_edits(element_rows, visible_elements, edited_elements)
            to_save["area_id"] = (
                to_save["area_name"].map(area_id_by_name)
                .fillna(to_save.get("area_id"))
                .fillna(str(area_id))
            )
            to_save["pitch_id"] = to_save["pitch"].map(pitch_id_by_label)
            to_save = to_save.drop(columns=["selected", "pitch"], errors="ignore")
            to_save = element_times_to_seconds(to_save)
            count = replace_yamazumi_elements(project_id, element_save_scope, to_save)
            record_audit_event(project_id, "Yamazumi elements", "Save & Refresh", count, st.session_state.get("current_editor", ""))
            st.toast(
                f"Saved {count} Yamazumi work element(s)",
                icon=":material/check_circle:",
            )
            active_board_draft = st.session_state.get(board_draft_key)
            if isinstance(active_board_draft, dict):
                valid_p_ids = set(pitches["id"].dropna().astype(str)) if not pitches.empty else set()
                st.session_state[board_draft_key] = reconcile_stack_draft(
                    active_board_draft, to_save.to_dict("records"), valid_pitch_ids=valid_p_ids
                )
            request_table_editor_reset(pitch_editor_key)
            request_table_editor_reset(element_editor_key)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def prepared_pitch_rows(
    draft_records: list[dict], excluded_ids: set[str]
) -> pd.DataFrame:
    draft = pd.DataFrame(draft_records, columns=pitch_editor_rows.columns)
    draft = draft.loc[
        ~draft["id"].fillna("").astype(str).isin(excluded_ids)
    ].copy()
    draft = drop_untouched_new_rows(draft, identifying_columns=["pitch_number"])
    errors = required_field_errors(
        draft, {"pitch_number": "Pitch address", "status": "Status"}
    )
    if errors:
        raise ValueError(" ".join(errors))
    to_save = merge_filtered_edits(pitch_rows, visible_pitches, draft)
    to_save = to_save.drop(columns=["selected"], errors="ignore")
    to_save["area_id"] = (
        to_save["area_name"].map(area_id_by_name)
        .fillna(to_save.get("area_id"))
        .fillna(str(area_id))
    )
    feed_target_id_by_label = {
        label: pitch_id for pitch_id, label in table_pitch_label_by_id.items()
    }
    to_save["feeds_into_pitch_id"] = to_save["feed_target"].map(
        feed_target_id_by_label
    )
    return to_save


def prepared_element_rows(
    draft_records: list[dict], excluded_ids: set[str]
) -> pd.DataFrame:
    draft = pd.DataFrame(draft_records, columns=element_editor_rows.columns)
    draft = draft.loc[
        ~draft["id"].fillna("").astype(str).isin(excluded_ids)
    ].copy()
    draft = drop_untouched_new_rows(draft, identifying_columns=["description"])
    errors = required_field_errors(
        draft,
        {
            "model_variants": "Model variants",
            "description": "Work description",
            "work_region": "Work region",
        },
    )
    if errors:
        raise ValueError(" ".join(errors))
    pitch_id_by_label = {
        label: pitch_id for pitch_id, label in pitch_label_by_id.items()
    }
    to_save = merge_filtered_edits(element_rows, visible_elements, draft)
    to_save["area_id"] = (
        to_save["area_name"].map(area_id_by_name)
        .fillna(to_save.get("area_id"))
        .fillna(str(area_id))
    )
    to_save["pitch_id"] = to_save["pitch"].map(pitch_id_by_label)
    to_save = to_save.drop(columns=["selected", "pitch"], errors="ignore")
    return element_times_to_seconds(to_save)


pending_pitch_delete = st.session_state.get(pitch_delete_key)
if pending_pitch_delete and "element_draft" not in pending_pitch_delete:
    pending_pitch_delete["element_draft"] = current_editor_draft(
        element_editor_rows, element_editor_key
    ).to_dict("records")
    pending_pitch_delete["other_element_edits"] = table_has_unsaved_changes(
        element_editor_key, native_row_selection=True
    )
    pending_pitch_delete["element_edit_count"] = editor_edit_count(element_editor_key)
    pitch_id_by_label = {
        label: pitch_id for pitch_id, label in pitch_label_by_id.items()
    }
    edited_pitch_ids = [
        pitch_id_by_label.get(str(row.get("pitch") or "Unassigned"))
        for row in pending_pitch_delete["element_draft"]
    ]
    for pitch in pending_pitch_delete.get("pitches", []):
        pitch["assigned_element_count"] = edited_pitch_ids.count(
            str(pitch["id"])
        )
    st.session_state[pitch_delete_key] = pending_pitch_delete


@st.dialog("Delete Selected Pitches?", dismissible=False)
def confirm_pitch_bulk_delete() -> None:
    pending = st.session_state.get(pitch_delete_key, {})
    selected_rows = pending.get("pitches", [])
    st.warning(
        f"Delete {len(selected_rows)} selected pitch(es)? Work elements assigned to "
        "these pitches will be moved to Unassigned; the work elements themselves will "
        "not be deleted."
    )
    for pitch in selected_rows:
        label = pitch.get("pitch_number") or "Unnamed pitch"
        if pitch.get("pitch_name"):
            label += f" — {pitch['pitch_name']}"
        st.write(
            f"- {label}: {pitch.get('assigned_element_count', 0)} assigned work "
            "element(s) will move to Unassigned"
        )
    blockers = pending.get("feed_reference_blockers", [])
    if blockers:
        relationships = ", ".join(
            f"{yamazumi_pitch_label(row['source_pitch_number'], row['source_pitch_name'])} → "
            f"{yamazumi_pitch_label(row['target_pitch_number'], row['target_pitch_name'])}"
            for row in blockers
        )
        st.error(
            "Deletion is blocked while these feed relationships remain: "
            + relationships
            + ". Re-point the source pitches or change their type before deleting the targets."
        )
    if pending.get("other_pitch_edits") or pending.get("other_element_edits"):
        st.info(
            "Other unsaved pitch or work-element edits will be saved at the same time "
            "so they are not lost."
        )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_pitch_bulk_delete_{scenario_id}_{area_id}"):
        st.session_state.pop(pitch_delete_key, None)
        request_table_editor_reset(pitch_editor_key)
        st.rerun()
    if actions.button(
        "Delete Pitches",
        type="primary",
        icon=":material/delete:",
        key=f"destructive_confirm_pitch_bulk_delete_{scenario_id}_{area_id}",
    ):
        try:
            editor_name = st.session_state.get("current_editor", "")
            if pending.get("other_element_edits"):
                element_save_rows = prepared_element_rows(
                    pending.get("element_draft", []), set()
                )
                replace_yamazumi_elements(project_id, element_save_scope, element_save_rows)
                record_audit_event(
                    project_id,
                    "Yamazumi elements",
                    "Save & Refresh",
                    int(pending.get("element_edit_count") or 0),
                    editor_name,
                    {"area_id": element_save_scope, "saved_with_pitch_delete": True},
                )
            selected_ids = {str(row["id"]) for row in selected_rows}
            pitch_save_rows = prepared_pitch_rows(
                pending.get("pitch_draft", []), selected_ids
            )
            replace_yamazumi_pitches(project_id, pitch_save_scope, pitch_save_rows)
            if pending.get("other_pitch_edits"):
                record_audit_event(
                    project_id,
                    "Yamazumi pitches",
                    "Save & Refresh",
                    int(pending.get("pitch_edit_count") or 0),
                    editor_name,
                    {"area_id": pitch_save_scope, "saved_with_bulk_delete": True},
                )
            moved_count = sum(
                int(row.get("assigned_element_count") or 0)
                for row in selected_rows
            )
            record_audit_event(
                project_id,
                "Yamazumi pitches",
                "Bulk delete",
                len(selected_ids),
                editor_name,
                {
                    "area_id": pitch_save_scope,
                    "pitches": selected_rows,
                    "elements_unassigned": moved_count,
                },
            )
            st.session_state.pop(pitch_delete_key, None)
            request_table_editor_reset(pitch_editor_key)
            request_table_editor_reset(element_editor_key)
            st.toast(
                f"Deleted {len(selected_ids)} pitch(es); {moved_count} work element(s) "
                "moved to Unassigned",
                icon=":material/delete:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Delete Selected Yamazumi Work Elements?", dismissible=False)
def confirm_element_bulk_delete() -> None:
    pending = st.session_state.get(element_delete_key, {})
    selected_rows = pending.get("elements", [])
    st.warning(
        f"Delete {len(selected_rows)} selected Yamazumi work element(s)? This removes "
        "the selected work from this planning scenario."
    )
    for element in selected_rows:
        linked_note = (
            " — its linked Process at a Glance step will not be deleted automatically"
            if element.get("process_step_exists")
            else ""
        )
        st.write(
            f"- {element.get('area_name') + ': ' if element.get('area_name') else ''}"
            f"{element.get('description') or 'Unnamed work element'} "
            f"({element.get('pitch') or 'Unassigned'}){linked_note}"
        )
        legacy_group_count = int(
            element.get("legacy_material_group_count") or 0
        )
        legacy_option_count = int(
            element.get("legacy_material_option_count") or 0
        )
        if legacy_group_count or legacy_option_count:
            st.caption(
                f"This element also removes {legacy_group_count} legacy material "
                f"group(s) and {legacy_option_count} legacy material option(s)."
            )
    if pending.get("other_pitch_edits") or pending.get("other_element_edits"):
        st.info(
            "Other unsaved pitch or work-element edits will be saved at the same time "
            "so they are not lost."
        )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_element_bulk_delete_{scenario_id}_{area_id}"):
        st.session_state.pop(element_delete_key, None)
        request_table_editor_reset(
            combined_element_editor_key
            if pending.get("combined_view")
            else element_editor_key
        )
        st.rerun()
    if actions.button(
        "Delete Work Elements",
        type="primary",
        icon=":material/delete:",
        key=f"destructive_confirm_element_bulk_delete_{scenario_id}_{area_id}",
    ):
        try:
            editor_name = st.session_state.get("current_editor", "")
            selected_ids = {str(row["id"]) for row in selected_rows}
            if pending.get("combined_view"):
                result = delete_yamazumi_elements(
                    project_id,
                    scenario_id,
                    list(selected_ids),
                    audit_editor_name=editor_name,
                )
                st.session_state.pop(element_delete_key, None)
                active_board_draft = st.session_state.get(board_draft_key)
                if isinstance(active_board_draft, dict):
                    st.session_state[board_draft_key] = reconcile_stack_draft(
                        active_board_draft, elements.to_dict("records")
                    )
                request_table_editor_reset(combined_element_editor_key)
                request_table_editor_reset(element_editor_key)
                st.toast(
                    f"Deleted {result['deleted_count']} Yamazumi work element(s)",
                    icon=":material/delete:",
                )
                st.rerun()
            element_save_rows = prepared_element_rows(
                pending.get("element_draft", []), selected_ids
            )
            replace_yamazumi_elements(project_id, element_save_scope, element_save_rows)
            if pending.get("other_element_edits"):
                record_audit_event(
                    project_id,
                    "Yamazumi elements",
                    "Save & Refresh",
                    int(pending.get("element_edit_count") or 0),
                    editor_name,
                    {"area_id": element_save_scope, "saved_with_bulk_delete": True},
                )
            if pending.get("other_pitch_edits"):
                pitch_save_rows = prepared_pitch_rows(
                    pending.get("pitch_draft", []), set()
                )
                replace_yamazumi_pitches(project_id, pitch_save_scope, pitch_save_rows)
                record_audit_event(
                    project_id,
                    "Yamazumi pitches",
                    "Save & Refresh",
                    int(pending.get("pitch_edit_count") or 0),
                    editor_name,
                    {"area_id": pitch_save_scope, "saved_with_element_delete": True},
                )
            record_audit_event(
                project_id,
                "Yamazumi elements",
                "Bulk delete",
                len(selected_ids),
                editor_name,
                {"area_id": element_save_scope, "elements": selected_rows},
            )
            st.session_state.pop(element_delete_key, None)
            active_board_draft = st.session_state.get(board_draft_key)
            if isinstance(active_board_draft, dict):
                st.session_state[board_draft_key] = reconcile_stack_draft(
                    active_board_draft,
                    element_save_rows.to_dict("records")
                    if hasattr(element_save_rows, "to_dict")
                    else elements.to_dict("records"),
                )
            request_table_editor_reset(element_editor_key)
            request_table_editor_reset(pitch_editor_key)
            st.toast(
                f"Deleted {len(selected_ids)} Yamazumi work element(s)",
                icon=":material/delete:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


if not gui_delete_dialog_open:
    if st.session_state.get(pitch_delete_key):
        confirm_pitch_bulk_delete()
    elif st.session_state.get(element_delete_key):
        confirm_element_bulk_delete()


with st.expander("Yamazumi History", icon=":material/history:"):
    (
        yamazumi_history_tab,
        pitch_history_tab,
        element_history_tab,
        variant_history_tab,
        region_history_tab,
    ) = st.tabs(
        [
            "Yamazumi Actions",
            "Pitches",
            "Work Elements",
            "Variants",
            "Work Regions",
        ]
    )
    with yamazumi_history_tab:
        yamazumi_history = audit_history(project_id, "Yamazumi", limit=50)
        if yamazumi_history.empty:
            st.caption("No Yamazumi action history has been recorded yet.")
        else:
            selectable_dataframe(
                yamazumi_history.drop(columns=["details"], errors="ignore"),
                key=f"yamazumi_action_history_{project_id}_{scenario_id}",
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
    with pitch_history_tab:
        pitch_history = audit_history(project_id, "Yamazumi pitches", limit=50)
        if pitch_history.empty:
            st.caption("No Yamazumi pitch history has been recorded yet.")
        else:
            selectable_dataframe(
                pitch_history.drop(columns=["details"], errors="ignore"),
                key=f"yamazumi_pitch_history_{project_id}_{scenario_id}",
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
    with element_history_tab:
        element_history = audit_history(project_id, "Yamazumi elements", limit=50)
        if element_history.empty:
            st.caption("No Yamazumi work-element history has been recorded yet.")
        else:
            selectable_dataframe(
                element_history.drop(columns=["details"], errors="ignore"),
                key=f"yamazumi_element_history_{project_id}_{scenario_id}",
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
    with variant_history_tab:
        variant_history = audit_history(project_id, "Yamazumi variants", limit=50)
        if variant_history.empty:
            st.caption("No Yamazumi variant history has been recorded yet.")
        else:
            selectable_dataframe(
                variant_history.drop(columns=["details"], errors="ignore"),
                key=f"yamazumi_variant_history_{project_id}_{scenario_id}",
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
    with region_history_tab:
        region_history = audit_history(
            project_id, "Yamazumi work regions", limit=50
        )
        if region_history.empty:
            st.caption("No standardized work-region changes have been recorded yet.")
        else:
            selectable_dataframe(
                region_history.drop(columns=["details"], errors="ignore"),
                key=f"yamazumi_region_history_{project_id}_{scenario_id}",
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
