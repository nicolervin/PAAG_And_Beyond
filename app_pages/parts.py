import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from utils.clipboard_image import as_uploaded_file, clipboard_image, decode_clipboard_image
from utils.image_annotator import decode_data_url, image_annotator
from utils.media_cache import cached_image_bytes
from utils.store import (
    PART_CODE_VALUES,
    PART_MAKE_BUY_VALUES,
    PART_SOURCE_CODES,
    add_part_image,
    add_part_image_url,
    assembly_bom_components,
    pits_assembly_mini_bom,
    audit_history,
    clear_part_image,
    complexity_features,
    connection,
    delete_part_image,
    delete_project_part,
    fishbone_part_assignments,
    part_delete_impact,
    get_planning_scenario,
    infer_part_feature_rules,
    part_feature_rules,
    part_images,
    part_scenario_activity,
    project_models,
    project_table,
    promote_part_image_to_primary,
    record_audit_event,
    save_table_view_preference,
    set_part_image,
    set_part_image_url,
    table_view_preference,
    update_part_feature_rules,
    update_part_primary_image_annotations,
    update_part_rows,
    update_part_supplemental_image_annotations,
)
from utils.scope_ui import page_title_with_scope
from utils.table_filters import (
    apply_id_keyed_editor_draft,
    apply_pending_table_editor_reset,
    capture_id_keyed_editor_draft,
    filter_table,
    get_effective_table_editor_state,
    merge_filtered_edits,
    request_table_editor_reset,
    was_table_editor_undo_reset,
)
from utils.table_ui import (
    dataframe_to_excel,
    drop_untouched_new_rows,
    editable_table_footer,
    editable_table_heading,
    native_selected_rows,
    prepare_editor_selection_column,
    render_select_all_control,
    required_field_errors,
    resolve_editor_selected_rows,
    count_table_create_and_edit_rows, render_audit_history_table, selectable_dataframe,
    selected_rows_action_bar,
    stage_native_delete_confirmation,
    standard_details_column_config,
    direct_entry_editor_rows,
    table_has_unsaved_changes,
)


@st.cache_data(show_spinner=False)
def _cached_parts_dataframe_to_excel(
    data_hash: str,
    _dataframe: pd.DataFrame,
    sheet_name: str = "Parts",
) -> bytes:
    del data_hash
    return dataframe_to_excel(_dataframe, sheet_name)


def _hash_filtered_export(dataframe: pd.DataFrame) -> str:
    serialized = dataframe.to_json(orient="split", date_format="iso").encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


PARTS_VIEW_KEY = "parts_catalog"
PINNED_PARTS_COLUMNS = ("view_details", "part_number", "description")
LEGACY_PARTS_COLUMN_ORDER_PREFIX = [
    "view_details", "active", "photo_status", "part_number", "description",
]
PREVIOUS_DEFAULT_PARTS_COLUMN_ORDER = [
    "view_details", "part_number", "description", "active", "photo_status",
    "weight_lb", "subsystem", "design_maturity", "factory_nickname", "design_engineer",
    "ppm", "buyer_gcl", "pmqe_aqe", "ame_tooling_engineer", "part_code",
    "pits_tracker_number", "source_code", "make_buy", "feature_applicability",
    "applicability_status", "notes", "source", "updated_display",
]
DEFAULT_PARTS_COLUMN_ORDER = [
    "view_details", "part_number", "description", "active", "photo_status",
    "weight_lb", "subsystem", "design_maturity", "factory_nickname", "design_engineer",
    "ppm", "buyer_gcl", "pmqe_aqe", "ame_tooling_engineer", "part_code",
    "pits_tracker_number", "source_code", "make_buy", "feature_applicability",
    "applicability_status", "notes", "source", "created_display", "updated_display",
]
PARTS_COLUMN_LABELS = {
    "view_details": "Details", "active": "Active", "photo_status": "Photo status",
    "part_number": "Part number", "description": "Part name", "weight_lb": "Weight (lb)",
    "subsystem": "Subsystem", "design_maturity": "Design Maturity",
    "factory_nickname": "Factory Nickname", "design_engineer": "Design Engineer",
    "ppm": "PPM", "buyer_gcl": "Buyer / GCL", "pmqe_aqe": "PMQE / AQE",
    "ame_tooling_engineer": "AME / Tooling Engineer", "part_code": "Part Code",
    "pits_tracker_number": "PITS ID", "source_code": "Source Code",
    "make_buy": "Make vs Buy", "feature_applicability": "Feature",
    "applicability_status": "Applicability status", "notes": "Notes",
    "source": "Source", "created_display": "Created", "updated_display": "Updated",
}


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
parts_base_editor_key = apply_pending_table_editor_reset(
    f"parts_catalog_editor_v9_{scenario_id}"
)
parts_editor_key = parts_base_editor_key
parts_draft_key = f"parts_catalog_draft_{project_id}_{scenario_id}"
parts_draft_values_key = f"{parts_draft_key}_values"
parts_draft_state_key = f"{parts_draft_key}_captured_state"
parts_draft_visible_key = f"{parts_draft_key}_visible"
parts_draft_added_key = f"{parts_draft_key}_added_rows"
parts_draft_last_editor_key = f"{parts_draft_key}_last_editor_key"
parts_editor_baseline_draft_key = f"{parts_draft_key}_baseline_draft"
page_title_with_scope(
    "Parts Catalog",
    scope="scenario-aware",
    help_text=(
        "The Parts Catalog itself is shared across every scenario. Whether a part is marked "
        "Active applies only to the currently selected scenario."
    ),
)
st.caption(
    "Connect official part numbers to CAD screenshots, revisions, model applicability, and the "
    "parts active in this planning scenario."
)
if not project_id or not scenario_id:
    st.stop()
scenario = get_planning_scenario(project_id, scenario_id)
if not scenario:
    st.error("The active planning scenario no longer exists.")
    st.stop()
st.caption(f"Active scenario: Rev {scenario['revision_label']} · {scenario['name']}")
parts_banner_container = st.container()
current_editor = str(st.session_state.get("current_editor", "") or "").strip()
editor_view_scope = hashlib.sha256(current_editor.encode("utf-8")).hexdigest()[:12]
parts_view_draft_key = f"parts_catalog_view_columns_{project_id}_{editor_view_scope}"
parts_view_pending_key = f"{parts_view_draft_key}_pending_reset"
parts_view_move_key = f"{parts_view_draft_key}_move"
saved_parts_view = table_view_preference(project_id, current_editor, PARTS_VIEW_KEY)
saved_parts_column_order = [
    column
    for column in (
        (saved_parts_view or {}).get("column_order")
        or (saved_parts_view or {}).get("visible_columns")
        or DEFAULT_PARTS_COLUMN_ORDER
    )
    if column in DEFAULT_PARTS_COLUMN_ORDER
]
if not saved_parts_column_order:
    saved_parts_column_order = DEFAULT_PARTS_COLUMN_ORDER.copy()
elif saved_parts_column_order[:5] == LEGACY_PARTS_COLUMN_ORDER_PREFIX:
    saved_parts_column_order = [
        "view_details", "part_number", "description", "active", "photo_status",
        *saved_parts_column_order[5:],
    ]
saved_parts_column_order = [
    *(col for col in PINNED_PARTS_COLUMNS if col in saved_parts_column_order),
    *(col for col in saved_parts_column_order if col not in PINNED_PARTS_COLUMNS),
]
if saved_parts_column_order == PREVIOUS_DEFAULT_PARTS_COLUMN_ORDER:
    saved_parts_column_order = DEFAULT_PARTS_COLUMN_ORDER.copy()
current_mount_token = f"{project_id}_{scenario_id}_{editor_view_scope}_v5"
if st.session_state.get("_parts_page_mounted_token") != current_mount_token:
    st.session_state["_parts_page_mounted_token"] = current_mount_token
    st.session_state[parts_view_draft_key] = saved_parts_column_order.copy()
    st.session_state[parts_view_pending_key] = saved_parts_column_order.copy()
    st.session_state.pop(parts_view_move_key, None)
    st.session_state.pop(parts_draft_values_key, None)
    st.session_state.pop(parts_draft_state_key, None)
    st.session_state.pop(parts_draft_visible_key, None)
    st.session_state.pop(parts_draft_added_key, None)
    st.session_state.pop(parts_draft_last_editor_key, None)
    st.session_state.pop(parts_editor_baseline_draft_key, None)
    request_table_editor_reset(parts_base_editor_key)
    parts_base_editor_key = apply_pending_table_editor_reset(
        f"parts_catalog_editor_v9_{scenario_id}"
    )
    parts_editor_key = parts_base_editor_key
pending_view_reset = st.session_state.pop(parts_view_pending_key, None)
if pending_view_reset is not None:
    st.session_state[parts_view_draft_key] = list(pending_view_reset)
current_view_draft = st.session_state.get(parts_view_draft_key)
if not isinstance(current_view_draft, list) or not current_view_draft:
    st.session_state[parts_view_draft_key] = saved_parts_column_order.copy()
else:
    normalized_view_draft = [
        column
        for column in dict.fromkeys(current_view_draft)
        if column in DEFAULT_PARTS_COLUMN_ORDER
    ]
    if not normalized_view_draft:
        st.session_state[parts_view_draft_key] = saved_parts_column_order.copy()
    elif normalized_view_draft != current_view_draft:
        st.session_state[parts_view_draft_key] = normalized_view_draft

parts = project_table("parts", project_id, "created_at ASC, rowid ASC")
models = project_models(project_id)
features = complexity_features(project_id)
active_features = features.loc[features["active"].fillna(1).astype(bool)].copy() if not features.empty else features
rules = part_feature_rules(project_id)
activity_by_part = part_scenario_activity(project_id, scenario_id)
if models.empty:
    active_model_numbers = []
    model_labels = {}
else:
    active_models = models.loc[models["active"].fillna(1).astype(bool)].copy()
    active_model_numbers = active_models["model_number"].fillna("").astype(str).tolist()
    model_labels = {
        str(mnum): (
            str(dname).strip() or "Common name not defined"
        )
        for mnum, dname in zip(models["model_number"], models["display_name"])
    }


def split_model_applicability(value) -> list[str]:
    text = "" if value is None else str(value).strip()
    if not text or text.lower() == "all":
        return ["All models"]
    if text in model_labels:
        return [text]

    # Official model identifiers can contain commas. Parse against the complete
    # set of defined identifiers before falling back to legacy comma splitting.
    candidates = sorted(model_labels, key=len, reverse=True)

    def parse_remaining(remaining: str) -> list[str] | None:
        for model_number in candidates:
            if remaining == model_number:
                return [model_number]
            prefix = f"{model_number}, "
            if remaining.startswith(prefix):
                parsed_tail = parse_remaining(remaining[len(prefix):])
                if parsed_tail is not None:
                    return [model_number, *parsed_tail]
        return None

    parsed = parse_remaining(text)
    return parsed if parsed is not None else [text]


feature_option_labels: dict[str, str] = {"All models": "All models"}
if not active_features.empty:
    for fid, fcat, fname, fallowed in zip(
        active_features["id"],
        active_features["category"],
        active_features["name"],
        active_features["allowed_values"],
    ):
        for choice in json.loads(fallowed or "[]"):
            token = f"{fid}::{choice}"
            feature_option_labels[token] = f"{fcat} · {fname} = {choice}"
feature_token_by_label = {label: token for token, label in feature_option_labels.items()}
feature_options = list(feature_token_by_label)
rules_by_part: dict[str, list[str]] = {}
if not rules.empty:
    for part_id, fid, val, cat, fname in zip(
        rules["part_id"],
        rules["feature_id"],
        rules["value"],
        rules["category"],
        rules["feature_name"],
    ):
        rules_by_part.setdefault(str(part_id), []).append(
            feature_option_labels.get(
                f"{fid}::{val}",
                f"{cat} · {fname} = {val}",
            )
        )
if not parts.empty and not active_features.empty:
    missing_rule_part_ids = [
        str(pid)
        for pid, app_val, asm_id in zip(
            parts["id"],
            parts["model_applicability"],
            parts["assembly_id"],
        )
        if str(pid) not in rules_by_part
        and str(app_val or "").strip().casefold() not in {"all", "all models"}
        and not str(asm_id or "").strip()
    ]
    if missing_rule_part_ids:
        inferred_missing = infer_part_feature_rules(project_id, part_ids=missing_rule_part_ids)
        if inferred_missing:
            update_part_feature_rules(project_id, inferred_missing)
            for pid, tokens in inferred_missing.items():
                if tokens == ["All models"]:
                    rules_by_part[str(pid)] = ["All models"]
                else:
                    labels = [
                        feature_option_labels[tok]
                        for tok in tokens
                        if tok in feature_option_labels
                    ]
                    if labels:
                        rules_by_part[str(pid)] = labels


def readable_feature_applicability(part_id: str, legacy_value) -> str:
    selected = rules_by_part.get(str(part_id), [])
    if selected:
        return "; ".join(selected)
    if str(legacy_value or "").strip().casefold() in {"all", "all models"}:
        return "All models"
    return "Needs feature tagging"


editable_table_heading("All parts")
st.caption(
    "Edit catalog fields directly, then save. Select View on a row to open its "
    "photos, full information, and completed-subassembly mini-BOM below."
)

with st.expander(
    "Saved table view — hide and move columns here",
    icon=":material/view_column:",
    expanded=False,
):
    st.info(
        "Use these controls for any layout you want to keep. Hiding or dragging a "
        "column from its menu inside the table is temporary and cannot be captured "
        "by Save & Refresh."
    )
    selected_parts_columns = st.multiselect(
        "Columns shown in saved view",
        options=DEFAULT_PARTS_COLUMN_ORDER,
        format_func=lambda column: PARTS_COLUMN_LABELS[column],
        key=parts_view_draft_key,
        help=(
            "Choose the columns to display. Their order here is the left-to-right table "
            "order and is saved for the Current editor in this project."
        ),
    )

    def move_parts_view_column(offset: int) -> None:
        columns = list(st.session_state.get(parts_view_draft_key, []))
        selected = st.session_state.get(parts_view_move_key)
        if selected not in columns:
            return
        current_index = columns.index(selected)
        target_index = current_index + offset
        if not 0 <= target_index < len(columns):
            return
        columns[current_index], columns[target_index] = (
            columns[target_index], columns[current_index]
        )
        st.session_state[parts_view_draft_key] = columns

    def reset_parts_view_columns() -> None:
        st.session_state[parts_view_draft_key] = DEFAULT_PARTS_COLUMN_ORDER.copy()

    if st.session_state.get(parts_view_move_key) not in selected_parts_columns:
        st.session_state[parts_view_move_key] = (
            selected_parts_columns[0] if selected_parts_columns else None
        )
    view_actions = st.container(horizontal=True, vertical_alignment="bottom")
    view_actions.selectbox(
        "Column to move",
        options=selected_parts_columns,
        format_func=lambda column: PARTS_COLUMN_LABELS[column],
        key=parts_view_move_key,
        disabled=not selected_parts_columns,
        width=260,
    )
    selected_move_index = (
        selected_parts_columns.index(st.session_state.get(parts_view_move_key))
        if st.session_state.get(parts_view_move_key) in selected_parts_columns
        else -1
    )
    view_actions.button(
        "Move earlier",
        icon=":material/arrow_back:",
        key=f"{parts_view_draft_key}_move_earlier",
        disabled=selected_move_index <= 0,
        on_click=move_parts_view_column,
        args=(-1,),
    )
    view_actions.button(
        "Move later",
        icon=":material/arrow_forward:",
        key=f"{parts_view_draft_key}_move_later",
        disabled=(
            selected_move_index < 0
            or selected_move_index >= len(selected_parts_columns) - 1
        ),
        on_click=move_parts_view_column,
        args=(1,),
    )
    view_actions.button(
        "Reset to default",
        icon=":material/restart_alt:",
        key=f"{parts_view_draft_key}_default",
        on_click=reset_parts_view_columns,
    )
    st.caption(
        "Changes appear in the table immediately but remain a draft until you select "
        "Save & Refresh below. Discard all edits restores the last saved layout and discards unsaved "
        "part edits."
    )
if not selected_parts_columns:
    st.warning("Show at least one column before saving the table view.")
raw_parts_column_order = selected_parts_columns or [
    "view_details",
    "part_number",
    "description",
]
parts_column_order = [
    *(col for col in PINNED_PARTS_COLUMNS if col in raw_parts_column_order),
    *(col for col in raw_parts_column_order if col not in PINNED_PARTS_COLUMNS),
]
parts_view_layout_token = hashlib.sha256(
    ",".join(parts_column_order).encode("utf-8")
).hexdigest()[:8]
parts_editor_key = f"{parts_base_editor_key}_{parts_view_layout_token}"
parts_view_has_unsaved_changes = selected_parts_columns != saved_parts_column_order
editable_columns = [
    "id", "part_number", "description", "weight_lb", "subsystem", "design_maturity",
    "factory_nickname", "official_windchill_part_name",
    "design_engineer", "technology_engineer", "ppm", "buyer_gcl", "pmqe_aqe",
    "ame_tooling_engineer", "part_code", "pits_tracker_number", "source_code", "make_buy",
    "quantity", "revision", "model_applicability", "notes", "source", "image_path",
    "created_at", "updated_at", "assembly_id", "assembly_number",
]
parts_for_editing = parts.reindex(columns=editable_columns).copy()
parts_for_editing["subsystem"] = parts_for_editing["subsystem"].fillna("").astype("string")
parts_for_editing["design_maturity"] = parts_for_editing["design_maturity"].fillna(
    parts_for_editing["revision"]
).fillna("").astype("string")
parts_for_editing["factory_nickname"] = parts_for_editing["factory_nickname"].fillna(
    parts_for_editing["official_windchill_part_name"]
).fillna("").astype("string")
parts_for_editing["design_engineer"] = parts_for_editing["design_engineer"].fillna(
    parts_for_editing["technology_engineer"]
).fillna("").astype("string")
for col in (
    "id", "part_number", "description", "ppm", "buyer_gcl", "pmqe_aqe",
    "ame_tooling_engineer", "part_code", "pits_tracker_number", "make_buy",
    "revision", "model_applicability", "notes", "source", "image_path",
    "created_at", "updated_at", "assembly_id", "assembly_number",
):
    parts_for_editing[col] = parts_for_editing[col].fillna("").astype("string")


_part_id_strs = [str(pid) for pid in parts_for_editing["id"]]
_model_app_vals = parts_for_editing["model_applicability"].tolist()
linked_assembly_by_part = {
    pid: str(asm_num or "")
    for pid, asm_id, asm_num in zip(
        _part_id_strs,
        parts_for_editing["assembly_id"],
        parts_for_editing["assembly_number"],
    )
    if str(asm_id or "").strip()
}


def assembly_grid_applicability_status(part_id: str, value) -> str:
    return readable_feature_applicability(part_id, value)


parts_for_editing["active"] = pd.Series(
    [bool(activity_by_part.get(pid, True)) for pid in _part_id_strs],
    index=parts_for_editing.index,
    dtype=bool,
)
parts_for_editing["feature_applicability"] = (
    pd.Series(dtype="object")
    if parts_for_editing.empty
    else [
        rules_by_part.get(pid, [])
        or (["All models"] if str(m_app or "").strip().casefold() in {"all", "all models"} else [])
        for pid, m_app in zip(_part_id_strs, _model_app_vals)
    ]
)
parts_for_editing["applicability_status"] = (
    pd.Series(dtype="string")
    if parts_for_editing.empty
    else [
        assembly_grid_applicability_status(pid, m_app)
        for pid, m_app in zip(_part_id_strs, _model_app_vals)
    ]
)
parts_for_editing["source_code"] = pd.Series(
    [
        ""
        if value is None or pd.isna(value)
        else str(int(value))
        if isinstance(value, float) and value.is_integer()
        else str(value).strip()
        for value in parts_for_editing["source_code"]
    ],
    index=parts_for_editing.index,
    dtype="string",
)
parts_for_editing["view_details"] = pd.Series(
    [":material/visibility: View"] * len(parts_for_editing),
    index=parts_for_editing.index,
    dtype="string",
)
parts_for_editing["photo_status"] = [
    "✅ Added" if str(value or "").strip() else "❌ Missing"
    for value in parts_for_editing["image_path"]
]
created_values = pd.to_datetime(
    parts_for_editing["created_at"], errors="coerce", utc=True
).dt.tz_convert("America/New_York")
parts_for_editing["created_display"] = created_values.dt.strftime(
    "%b %d, %Y %H:%M"
).fillna("")
updated_values = pd.to_datetime(
    parts_for_editing["updated_at"], errors="coerce", utc=True
).dt.tz_convert("America/New_York")
parts_for_editing["updated_display"] = updated_values.dt.strftime(
    "%b %d, %Y %H:%M"
).fillna("")


for col in ("applicability_status", "photo_status", "created_display", "updated_display"):
    parts_for_editing[col] = parts_for_editing[col].fillna("").astype("string")




total_catalog_parts = int(len(parts_for_editing))
active_parts_df = (
    parts_for_editing.loc[parts_for_editing["active"].astype(bool)]
    if not parts_for_editing.empty
    else parts_for_editing
)
active_parts_count = int(len(active_parts_df))
inactive_parts_count = max(0, total_catalog_parts - active_parts_count)
active_parts_icon = "🟢" if active_parts_count > 0 else "🟡"
if total_catalog_parts == 0:
    active_parts_delta = "No parts in catalog"
    active_parts_delta_color = "off"
elif inactive_parts_count == 0:
    active_parts_delta = f"All {total_catalog_parts} catalog part(s) active"
    active_parts_delta_color = "normal"
else:
    active_parts_delta = f"{total_catalog_parts} total · {inactive_parts_count} inactive"
    active_parts_delta_color = "off"

with_photo_count = (
    int((active_parts_df["photo_status"] == "✅ Added").sum())
    if active_parts_count > 0
    else 0
)
missing_photo_count = max(0, active_parts_count - with_photo_count)
photo_pct = (
    round((with_photo_count / active_parts_count) * 100)
    if active_parts_count > 0
    else 0
)
photo_icon = (
    "🟢"
    if (active_parts_count > 0 and missing_photo_count == 0)
    else ("🟡" if with_photo_count > 0 else "🔴")
)
if active_parts_count == 0:
    photo_delta = "No active parts"
    photo_delta_color = "off"
elif missing_photo_count == 0:
    photo_delta = "All active parts have photos"
    photo_delta_color = "normal"
else:
    photo_delta = f"{missing_photo_count} missing photo"
    photo_delta_color = "inverse"

needs_tagging_count = (
    int((active_parts_df["applicability_status"] == "Needs feature tagging").sum())
    if active_parts_count > 0
    else 0
)
tagged_count = max(0, active_parts_count - needs_tagging_count)
tagged_pct = (
    round((tagged_count / active_parts_count) * 100)
    if active_parts_count > 0
    else 0
)
tagged_icon = (
    "🟢"
    if (active_parts_count > 0 and needs_tagging_count == 0)
    else ("🟡" if tagged_count > 0 else "🔴")
)
if active_parts_count == 0:
    tagged_delta = "No active parts"
    tagged_delta_color = "off"
elif needs_tagging_count == 0:
    tagged_delta = "All active parts tagged"
    tagged_delta_color = "normal"
else:
    tagged_delta = f"{needs_tagging_count} need feature tagging"
    tagged_delta_color = "inverse"

fb_assignments = fishbone_part_assignments(project_id)
placed_part_ids = (
    set(fb_assignments["part_id"].astype(str))
    if not fb_assignments.empty
    else set()
)
placeable_active_df = (
    active_parts_df.loc[
        active_parts_df["source_code"].fillna("").astype(str).str.strip() != "8"
    ]
    if active_parts_count > 0
    else active_parts_df
)
placeable_active_count = int(len(placeable_active_df))
placed_active_count = (
    int(placeable_active_df["id"].astype(str).isin(placed_part_ids).sum())
    if placeable_active_count > 0
    else 0
)
unplaced_active_count = max(0, placeable_active_count - placed_active_count)
fb_pct = (
    round((placed_active_count / placeable_active_count) * 100)
    if placeable_active_count > 0
    else 0
)
fb_icon = (
    "🟢"
    if (placeable_active_count > 0 and unplaced_active_count == 0)
    else ("🟡" if placed_active_count > 0 else "🔴")
)
if placeable_active_count == 0:
    fb_delta = "No placeable active parts"
    fb_delta_color = "off"
elif unplaced_active_count == 0:
    fb_delta = "All active parts placed"
    fb_delta_color = "normal"
else:
    fb_delta = f"{unplaced_active_count} not in Fishbone"
    fb_delta_color = "inverse"

if active_parts_count > 0:
    _make_buy_clean = active_parts_df["make_buy"].fillna("").astype(str).str.strip()
    _part_code_clean = active_parts_df["part_code"].fillna("").astype(str).str.strip()
    classified_count = int(((_make_buy_clean != "") & (_part_code_clean != "")).sum())
    make_count = int((_make_buy_clean.str.casefold() == "make").sum())
    buy_count = int((_make_buy_clean.str.casefold() == "buy").sum())
    subasm_code_count = int((_part_code_clean == "Completed Subassembly").sum())
else:
    classified_count = 0
    make_count = 0
    buy_count = 0
    subasm_code_count = 0
missing_sourcing_count = max(0, active_parts_count - classified_count)
sourcing_pct = (
    round((classified_count / active_parts_count) * 100)
    if active_parts_count > 0
    else 0
)
sourcing_icon = (
    "🟢"
    if (active_parts_count > 0 and missing_sourcing_count == 0)
    else ("🟡" if classified_count > 0 else "🔴")
)
if active_parts_count == 0:
    sourcing_delta = "No active parts"
    sourcing_delta_color = "off"
elif missing_sourcing_count == 0:
    sourcing_delta = f"Make: {make_count} · Buy: {buy_count}"
    sourcing_delta_color = "normal"
else:
    sourcing_delta = f"{missing_sourcing_count} missing Make/Buy or Code"
    sourcing_delta_color = "inverse"

with parts_banner_container:
    pm1, pm2, pm3, pm4, pm5 = st.columns(5)
    pm1.metric(
        "Active parts",
        f"{active_parts_icon} {active_parts_count}",
        delta=active_parts_delta,
        delta_color=active_parts_delta_color,
        help=(
            "Number of Parts Catalog items marked Active in the current planning scenario. "
            "Catalog records are shared across the project, while the Active toggle scopes "
            "scenario visibility."
        ),
    )
    pm2.metric(
        "Photo coverage",
        f"{photo_icon} {photo_pct}%" if active_parts_count > 0 else "⚪ —",
        delta=photo_delta,
        delta_color=photo_delta_color,
        help=(
            "Percentage of active parts with a Primary Image or CAD web link attached. "
            "Part thumbnails flow into Fishbone, Yamazumi, Process at a Glance, and Pin Map."
        ),
    )
    pm3.metric(
        "Feature tagging",
        f"{tagged_icon} {tagged_pct}%" if active_parts_count > 0 else "⚪ —",
        delta=tagged_delta,
        delta_color=tagged_delta_color,
        help=(
            "Percentage of active parts assigned to 'All models' or specific Complexity Tree "
            "feature rules."
        ),
    )
    pm4.metric(
        "Fishbone placement",
        f"{fb_icon} {fb_pct}%" if placeable_active_count > 0 else "⚪ —",
        delta=fb_delta,
        delta_color=fb_delta_color,
        help=(
            "Percentage of placeable active catalog parts (excluding Source Code 8 phantom "
            "assemblies) assigned to at least one Fishbone section."
        ),
    )
    pm5.metric(
        "Sourcing & Part Code",
        f"{sourcing_icon} {sourcing_pct}%" if active_parts_count > 0 else "⚪ —",
        delta=sourcing_delta,
        delta_color=sourcing_delta_color,
        help=(
            "Percentage of active parts with both Make vs Buy and Part Code populated "
            f"(Make: {make_count}, Buy: {buy_count}, Completed Subassemblies: {subasm_code_count})."
        ),
    )


def _is_blank_cell(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    try:
        if bool(pd.isna(value)):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() == ""


def _build_draft_added_part_row(raw_row: dict[str, object]) -> dict[str, object] | None:
    if _is_blank_cell(raw_row.get("part_number")) and _is_blank_cell(raw_row.get("description")):
        return None
    raw_features = raw_row.get("feature_applicability")
    if isinstance(raw_features, (list, tuple, set)):
        feature_list = [str(item) for item in raw_features if not _is_blank_cell(item)]
    else:
        feature_list = []
    if not feature_list:
        feature_list = ["All models"]
    raw_active = raw_row.get("active")
    is_active = True if _is_blank_cell(raw_active) else bool(raw_active)
    raw_weight = raw_row.get("weight_lb")
    try:
        weight_val = None if _is_blank_cell(raw_weight) else float(raw_weight)
    except (TypeError, ValueError):
        weight_val = None
    draft_id = str(raw_row.get("id") or "").strip()
    if not draft_id or not draft_id.startswith("__draft_new__"):
        draft_id = f"__draft_new__{uuid4()}"
    return {
        "id": draft_id,
        "part_number": "" if _is_blank_cell(raw_row.get("part_number")) else str(raw_row.get("part_number")).strip(),
        "description": "" if _is_blank_cell(raw_row.get("description")) else str(raw_row.get("description")).strip(),
        "weight_lb": weight_val,
        "subsystem": "" if _is_blank_cell(raw_row.get("subsystem")) else str(raw_row.get("subsystem")).strip(),
        "design_maturity": "" if _is_blank_cell(raw_row.get("design_maturity")) else str(raw_row.get("design_maturity")).strip(),
        "factory_nickname": "" if _is_blank_cell(raw_row.get("factory_nickname")) else str(raw_row.get("factory_nickname")).strip(),
        "official_windchill_part_name": "" if _is_blank_cell(raw_row.get("factory_nickname")) else str(raw_row.get("factory_nickname")).strip(),
        "design_engineer": "" if _is_blank_cell(raw_row.get("design_engineer")) else str(raw_row.get("design_engineer")).strip(),
        "technology_engineer": "" if _is_blank_cell(raw_row.get("design_engineer")) else str(raw_row.get("design_engineer")).strip(),
        "ppm": "" if _is_blank_cell(raw_row.get("ppm")) else str(raw_row.get("ppm")).strip(),
        "buyer_gcl": "" if _is_blank_cell(raw_row.get("buyer_gcl")) else str(raw_row.get("buyer_gcl")).strip(),
        "pmqe_aqe": "" if _is_blank_cell(raw_row.get("pmqe_aqe")) else str(raw_row.get("pmqe_aqe")).strip(),
        "ame_tooling_engineer": "" if _is_blank_cell(raw_row.get("ame_tooling_engineer")) else str(raw_row.get("ame_tooling_engineer")).strip(),
        "part_code": "" if _is_blank_cell(raw_row.get("part_code")) else str(raw_row.get("part_code")).strip(),
        "pits_tracker_number": "" if _is_blank_cell(raw_row.get("pits_tracker_number")) else str(raw_row.get("pits_tracker_number")).strip(),
        "source_code": "" if _is_blank_cell(raw_row.get("source_code")) else str(raw_row.get("source_code")).strip(),
        "make_buy": "" if _is_blank_cell(raw_row.get("make_buy")) else str(raw_row.get("make_buy")).strip(),
        "quantity": 1,
        "revision": "" if _is_blank_cell(raw_row.get("design_maturity")) else str(raw_row.get("design_maturity")).strip(),
        "model_applicability": "All",
        "notes": "" if _is_blank_cell(raw_row.get("notes")) else str(raw_row.get("notes")).strip(),
        "source": "Manual",
        "image_path": "",
        "created_at": "",
        "updated_at": "",
        "assembly_id": "",
        "assembly_number": "",
        "active": is_active,
        "feature_applicability": feature_list,
        "applicability_status": "; ".join(feature_list),
        "view_details": ":material/visibility: View",
        "photo_status": "❌ Missing",
        "created_display": "",
        "updated_display": "",
    }


def harvest_added_rows_into_draft(added_rows: list[dict[str, object]] | None) -> bool:
    if not added_rows:
        return False
    existing_draft_rows = list(st.session_state.get(parts_draft_added_key, []))
    harvested_any = False
    for raw_row in added_rows:
        if not isinstance(raw_row, dict):
            continue
        draft_row = _build_draft_added_part_row(raw_row)
        if draft_row is not None:
            candidate_pnum = str(draft_row.get("part_number") or "").strip().casefold()
            if candidate_pnum:
                saved_pnums = (
                    set(parts["part_number"].fillna("").astype(str).str.strip().str.casefold())
                    if not parts.empty and "part_number" in parts.columns
                    else set()
                )
                draft_pnums = {
                    str(item.get("part_number") or "").strip().casefold()
                    for item in existing_draft_rows
                    if isinstance(item, dict)
                }
                if candidate_pnum in saved_pnums or candidate_pnum in draft_pnums:
                    draft_row = None
        if draft_row is not None:
            existing_draft_rows.append(draft_row)
            harvested_any = True
    if harvested_any:
        st.session_state[parts_draft_added_key] = existing_draft_rows
    return harvested_any


def merge_parts_editor_draft(source: pd.DataFrame) -> pd.DataFrame:
    """Capture positional edits by part ID and overlay the complete pending draft."""
    last_editor_key = st.session_state.get(parts_draft_last_editor_key) or parts_editor_key
    is_undo_reset = was_table_editor_undo_reset(parts_editor_key)
    if last_editor_key != parts_editor_key and not is_undo_reset:
        old_state = get_effective_table_editor_state(last_editor_key)
        harvest_added_rows_into_draft(old_state.get("added_rows"))
        st.session_state.pop(last_editor_key, None)
        state = get_effective_table_editor_state(parts_editor_key)
    else:
        state = get_effective_table_editor_state(
            parts_editor_key if is_undo_reset else last_editor_key
        )
    st.session_state[parts_draft_last_editor_key] = parts_editor_key
    previous_visible = pd.DataFrame(
        st.session_state.get(parts_draft_visible_key, [])
    )
    draft_by_id, captured_state = capture_id_keyed_editor_draft(
        previous_visible,
        state,
        st.session_state.get(parts_draft_values_key, {}),
        st.session_state.get(parts_draft_state_key, {}),
    )
    st.session_state[parts_draft_values_key] = draft_by_id
    st.session_state[parts_draft_state_key] = (
        {} if (last_editor_key != parts_editor_key and not is_undo_reset) else captured_state
    )
    return apply_id_keyed_editor_draft(source, draft_by_id)


def clear_parts_editor_draft() -> None:
    for key in (
        parts_draft_values_key,
        parts_draft_state_key,
        parts_draft_visible_key,
        parts_draft_added_key,
        parts_draft_last_editor_key,
        parts_editor_baseline_draft_key,
    ):
        st.session_state.pop(key, None)


draft_added_records = list(st.session_state.get(parts_draft_added_key, []))
if draft_added_records:
    draft_added_df = pd.DataFrame(draft_added_records).reindex(
        columns=parts_for_editing.columns
    )
    parts_for_editing = pd.concat(
        [parts_for_editing, draft_added_df], ignore_index=True, sort=False
    )
parts_saved_for_editing = parts_for_editing.copy()
parts_full_for_editing = merge_parts_editor_draft(parts_saved_for_editing)
if draft_added_records and not parts_full_for_editing.empty:
    saved_pnums_lower = (
        set(parts["part_number"].fillna("").astype(str).str.strip().str.casefold())
        if not parts.empty and "part_number" in parts.columns
        else set()
    )
    stale_draft_ids: set[str] = set()
    for _, draft_check_row in parts_full_for_editing.loc[
        parts_full_for_editing["id"].astype(str).str.startswith("__draft_new__")
    ].iterrows():
        did = str(draft_check_row["id"])
        dpnum = str(draft_check_row.get("part_number") or "").strip().casefold()
        ddesc = str(draft_check_row.get("description") or "").strip()
        if (not dpnum and not ddesc) or (dpnum and dpnum in saved_pnums_lower):
            stale_draft_ids.add(did)
    if stale_draft_ids:
        st.session_state[parts_draft_added_key] = [
            item
            for item in draft_added_records
            if str(item.get("id") or "") not in stale_draft_ids
        ]
        current_draft_vals = dict(st.session_state.get(parts_draft_values_key, {}) or {})
        for did in stale_draft_ids:
            current_draft_vals.pop(did, None)
        st.session_state[parts_draft_values_key] = current_draft_vals
        parts_saved_for_editing = parts_saved_for_editing.loc[
            ~parts_saved_for_editing["id"].astype(str).isin(stale_draft_ids)
        ].reset_index(drop=True)
        parts_full_for_editing = parts_full_for_editing.loc[
            ~parts_full_for_editing["id"].astype(str).isin(stale_draft_ids)
        ].reset_index(drop=True)
        request_table_editor_reset(parts_editor_key)
        parts_base_editor_key = apply_pending_table_editor_reset(
            f"parts_catalog_editor_v9_{scenario_id}"
        )
        parts_editor_key = f"{parts_base_editor_key}_{parts_view_layout_token}"
        st.session_state[parts_draft_last_editor_key] = parts_editor_key
has_parts_draft = bool(st.session_state.get(parts_draft_values_key, {})) or bool(
    st.session_state.get(parts_draft_added_key, [])
)
parts_for_editing = parts_saved_for_editing
selected_part_key = f"parts_selected_id_{project_id}"

# Resolve query parameters if navigating from PAAG slide or external link
qp_part_id = str(st.query_params.get("part_id") or "").strip()
qp_part_number = str(st.query_params.get("part_number") or "").strip()
if qp_part_id or qp_part_number:
    matched_id = None
    matched_pnum = None
    if not parts.empty:
        if qp_part_id:
            m = parts.loc[parts["id"].astype(str) == qp_part_id]
            if not m.empty:
                matched_id = str(m.iloc[0]["id"])
                matched_pnum = str(m.iloc[0]["part_number"] or "").strip()
        if not matched_id and qp_part_number:
            m = parts.loc[
                parts["part_number"].astype(str).str.strip().str.casefold()
                == qp_part_number.casefold()
            ]
            if not m.empty:
                matched_id = str(m.iloc[0]["id"])
                matched_pnum = str(m.iloc[0]["part_number"] or "").strip()

    if matched_id:
        st.session_state[selected_part_key] = matched_id
        # Pre-fill keyword filter so the table displays this queried part
        filter_kw = matched_pnum or qp_part_number
        st.session_state[f"part_catalog_filters_{project_id}_keyword"] = filter_kw
        st.session_state["part_catalog_filters_keyword"] = filter_kw
        # Clear conflicting dropdown filters so the part is guaranteed visible
        for filter_column in [
            "active", "photo_status", "part_number", "description", "subsystem", "design_maturity", "revision",
            "factory_nickname", "design_engineer", "ppm", "buyer_gcl",
            "pmqe_aqe", "ame_tooling_engineer", "part_code", "source_code",
            "make_buy", "pits_tracker_number", "feature_applicability", "notes", "source", "created_at", "updated_at",
        ]:
            st.session_state.pop(f"part_catalog_filters_{project_id}_{filter_column}", None)
            st.session_state.pop(f"part_catalog_filters_{filter_column}", None)
        st.session_state["parts_scroll_to_details"] = True

    try:
        if "part_id" in st.query_params:
            del st.query_params["part_id"]
        if "part_number" in st.query_params:
            del st.query_params["part_number"]
    except Exception:
        pass

filter_expander = st.expander("Filter columns", icon=":material/filter_list:", expanded=False)
sort_controls_slot = st.container()
keyword_and_selection_row = st.container(horizontal=True, vertical_alignment="bottom")
keyword_filter_slot = keyword_and_selection_row.container()
parts_action_slot = keyword_and_selection_row.empty()

with filter_expander:
    pre_filter_editor_state = deepcopy(st.session_state.get(parts_editor_key, {}) or {})
    pre_filter_had_dirty_state = bool(
        pre_filter_editor_state.get("added_rows")
        or pre_filter_editor_state.get("edited_rows")
        or pre_filter_editor_state.get("deleted_rows")
    )
    pre_filter_added_rows = deepcopy(
        (st.session_state.get(parts_editor_key, {}) or {}).get("added_rows", [])
    )
    parts_for_editing = filter_table(
        parts_for_editing,
        key=f"part_catalog_filters_{project_id}",
        dropdown_columns=[
            "active", "source", "design_maturity", "subsystem", "source_code", "make_buy",
            "factory_nickname", "design_engineer", "ppm", "buyer_gcl",
            "pmqe_aqe", "ame_tooling_engineer", "part_code", "photo_status", "applicability_status",
        ],
        search_columns=[
            "part_number", "description", "subsystem", "design_maturity", "factory_nickname",
            "design_engineer", "ppm", "buyer_gcl", "pmqe_aqe",
            "ame_tooling_engineer", "part_code", "pits_tracker_number",
            "source_code", "make_buy", "photo_status", "applicability_status",
            "notes", "source",
        ],
        labels={
            "active": "Active in scenario",
            "photo_status": "Photo status",
            "part_number": "Part number",
            "description": "Part Name",
            "subsystem": "Subsystem",
            "design_maturity": "Design Maturity",
            "factory_nickname": "Factory Nickname",
            "design_engineer": "Design Engineer",
            "ppm": "PPM",
            "buyer_gcl": "Buyer / GCL",
            "pmqe_aqe": "PMQE / AQE",
            "ame_tooling_engineer": "AME / Tooling Engineer",
            "part_code": "Part Code",
            "source_code": "Source Code",
            "make_buy": "Make vs Buy",
            "technology_engineer": "Technology Engineer",
            "pits_tracker_number": "PITS ID",
            "applicability_status": "Feature",
        },
        reset_widget_keys=[parts_editor_key],
        multi_value_columns=["feature_applicability"],
        keyword_container=keyword_filter_slot,
    )
    if parts_editor_key not in st.session_state and not was_table_editor_undo_reset(parts_editor_key):
        st.session_state.pop(parts_draft_state_key, None)
        harvested_pre_filter_rows = (
            harvest_added_rows_into_draft(pre_filter_added_rows)
            if pre_filter_added_rows
            else False
        )
        if harvested_pre_filter_rows:
            request_table_editor_reset(parts_editor_key)
            st.rerun()
        elif pre_filter_had_dirty_state:
            request_table_editor_reset(parts_editor_key)
            parts_base_editor_key = apply_pending_table_editor_reset(
                f"parts_catalog_editor_v9_{scenario_id}"
            )
            parts_editor_key = f"{parts_base_editor_key}_{parts_view_layout_token}"
            st.session_state[parts_draft_last_editor_key] = parts_editor_key
    if False:
        if harvest_added_rows_into_draft(pre_filter_added_rows) or True:
            st.rerun()
    clear_filter_actions = st.container(horizontal=True, horizontal_alignment="right")
    if clear_filter_actions.button(
        "Clear filters",
        icon=":material/filter_alt_off:",
        key="clear_part_catalog_filters",
    ):
        if harvest_added_rows_into_draft(pre_filter_added_rows) or True:
            st.session_state.pop(parts_editor_key, None)
            request_table_editor_reset(parts_editor_key)
        st.session_state.pop(f"part_catalog_filters_{project_id}_keyword", None)
        st.session_state.pop("part_catalog_filters_keyword", None)
        for filter_column in [
            "active", "photo_status", "part_number", "description", "subsystem", "design_maturity", "revision",
            "factory_nickname", "design_engineer", "ppm", "buyer_gcl",
            "pmqe_aqe", "ame_tooling_engineer", "part_code", "source_code",
            "make_buy", "pits_tracker_number", "feature_applicability", "notes", "source", "created_at", "updated_at",
        ]:
            st.session_state.pop(f"part_catalog_filters_{project_id}_{filter_column}", None)
            st.session_state.pop(f"part_catalog_filters_{filter_column}", None)
        st.rerun()


    parts_bulk_feature_slot = st.empty()


candidate_sort_columns = [
    "active", "photo_status", "part_number", "description", "weight_lb",
    "subsystem", "design_maturity",
    "factory_nickname", "design_engineer", "ppm", "buyer_gcl",
    "pmqe_aqe", "ame_tooling_engineer", "part_code", "pits_tracker_number",
    "source_code", "make_buy", "feature_applicability",
    "applicability_status", "notes", "source", "created_at", "updated_at",
]
sort_column_display_map = {
    "created_at": "created_display",
    "updated_at": "updated_display",
}
with sort_controls_slot:
    parts_editor_rows = direct_entry_editor_rows(
        parts_for_editing,
        editor_key=parts_editor_key,
        sort_columns=[
            col
            for col in candidate_sort_columns
            if sort_column_display_map.get(col, col) in parts_column_order
            or col == "created_at"
        ],
        labels={
            "photo_status": "Photo status", "part_number": "Part number",
            "description": "Part name", "weight_lb": "Weight (lb)",
            "subsystem": "Subsystem", "design_maturity": "Design Maturity",
            "factory_nickname": "Factory Nickname",
            "design_engineer": "Design Engineer", "ppm": "PPM",
            "buyer_gcl": "Buyer / GCL", "pmqe_aqe": "PMQE / AQE",
            "ame_tooling_engineer": "AME / Tooling Engineer", "part_code": "Part Code",
            "feature_applicability": "Feature",
            "applicability_status": "Applicability status",
            "created_at": "Created", "updated_at": "Updated",
        },
        additional_unsaved_changes=has_parts_draft,
        default_sort_column="created_at",
    )
# Let the mounted editor retain ordinary cell changes without replacing its
# data source on every edit rerun. Reapply the stable-ID draft only after
# another control has remounted the editor, such as a filter or view change.
current_editor_state = get_effective_table_editor_state(parts_editor_key)
if not (
    current_editor_state.get("edited_rows")
    or current_editor_state.get("added_rows")
    or current_editor_state.get("deleted_rows")
):
    st.session_state[parts_draft_state_key] = {}
    st.session_state[parts_editor_baseline_draft_key] = deepcopy(
        st.session_state.get(parts_draft_values_key, {})
    )
parts_editor_rows = apply_id_keyed_editor_draft(
    parts_editor_rows,
    st.session_state.get(parts_editor_baseline_draft_key, {}),
)

parts_for_editing = parts_editor_rows.copy()
visible_editor_columns = [
    "id",
    "selected",
    *[col for col in parts_column_order if col != "id" and col in parts_editor_rows.columns],
]
parts_editor_display_rows = prepare_editor_selection_column(
    parts_editor_rows.reindex(columns=visible_editor_columns),
    editor_key=parts_editor_key,
)


def open_part_details() -> None:
    click = st.session_state.get("parts_view_details")
    target_rows = globals().get("parts_editor_display_rows")
    if target_rows is None:
        target_rows = parts_for_editing
    if click and 0 <= click["row"] < len(target_rows):
        st.session_state[selected_part_key] = str(target_rows.iloc[click["row"]]["id"])
        st.session_state["parts_scroll_to_details"] = True


part_code_options = ["", *PART_CODE_VALUES]
if "part_code" in parts_editor_display_rows.columns:
    for val in parts_editor_display_rows["part_code"].dropna().astype(str):
        cleaned_code = val.strip()
        if cleaned_code and cleaned_code not in part_code_options:
            part_code_options.append(cleaned_code)



edited_parts = st.data_editor(
    parts_editor_display_rows,
    key=parts_editor_key,
    hide_index=True,
    num_rows="add",
    height=430,
    disabled=[
        col for col in [
            "id", "model_applicability", "photo_status",
            "applicability_status", "source", "image_path", "created_at",
            "created_display", "updated_at",
            "updated_display", "assembly_id", "assembly_number",
        ]
        if col in visible_editor_columns
    ],
    column_order=["selected", *parts_column_order],
    column_config={
        "id": None,
        "selected": st.column_config.CheckboxColumn(
            "Select",
            default=False,
            pinned=True,
            width="small",
            help="Select parts for bulk feature updates or deletion.",
        ),
        "official_windchill_part_name": None,
        "technology_engineer": None,
        "assembly_id": None,
        "assembly_number": None,
        "view_details": standard_details_column_config(
            on_click=open_part_details, key="parts_view_details", pinned=True, width="small"
        ),
        "active": st.column_config.CheckboxColumn(
            "Active",
            default=True,
            help=(
                "Turn off to keep this catalog record but hide it from downstream views in "
                "the active planning scenario."
            ),
        ),
        "photo_status": st.column_config.TextColumn(
            "Photo status",
            default="",
            help="A green check means a primary CAD image is attached; a red X means it is missing.",
        ),
        "part_number": st.column_config.TextColumn("Part number", required=True, pinned=True),
        "description": st.column_config.TextColumn("Part Name", width="large", pinned=True),
        "weight_lb": st.column_config.NumberColumn(
            "Weight (lb)",
            min_value=0.0,
            step=0.1,
            format="%.2f lb",
            help="Catalog part weight in pounds. Single parts >= 33 lb trigger Ergonomics heavy part warnings.",
        ),
        "subsystem": st.column_config.TextColumn(
            "Subsystem",
            width="medium",
            default="",
            help="Subsystem identifier (manual entry or imported from column F of the PITS Tracker).",
        ),
        "design_maturity": st.column_config.TextColumn(
            "Design Maturity",
            default="",
            help="Design maturity / revision from PITS Tracker column G.",
        ),
        "factory_nickname": st.column_config.TextColumn(
            "Factory Nickname",
            width="large",
            help="The factory nickname or official Windchill name recorded from PITS.",
        ),
        "design_engineer": st.column_config.TextColumn(
            "Design Engineer",
            help="Design Engineer / Technology Engineer from PITS Tracker column I.",
        ),
        "ppm": st.column_config.TextColumn(
            "PPM",
            help="Part Project Manager from PITS Tracker column J.",
        ),
        "buyer_gcl": st.column_config.TextColumn(
            "Buyer / GCL",
            help="Buyer / Global Commodity Leader from PITS Tracker column K.",
        ),
        "pmqe_aqe": st.column_config.TextColumn(
            "PMQE / AQE",
            help="Plant Manufacturing Quality Engineer / Advanced Quality Engineer from PITS Tracker column L.",
        ),
        "ame_tooling_engineer": st.column_config.TextColumn(
            "AME / Tooling Engineer",
            help="Advanced Manufacturing Engineer / Tooling Engineer from PITS Tracker column M.",
        ),
        "part_code": st.column_config.SelectboxColumn(
            "Part Code",
            options=part_code_options,
            default="",
            help=(
                "Part Code (manual selection or from PITS Tracker column N).\n\n"
                "- NP = New Part, New Tool\n"
                "- NPNT = New Part, No Tooling\n"
                "- ASM = Assembly\n"
                "- CP = Current Production\n"
                "- CP Other = CP different site"
            ),
        ),
        "pits_tracker_number": st.column_config.TextColumn(
            "PITS ID",
            help="ID Number imported from column B of the PITS Tracker. It must be unique within the current project, and leading zeros are preserved.",
        ),
        "source_code": st.column_config.SelectboxColumn(
            "Source Code",
            options=["", *PART_SOURCE_CODES],
            default="",
            help=(
                "PITS source code from tracker column T.\n\n"
                "- 1 - Purchased Part\n"
                "- +1 - Purchased Asm\n"
                "- 2.4 - From AP3\n"
                "- 3 - Mfg Part\n"
                "- 5 - Asm (Disassembly no)\n"
                "- 6 - Asm (Disassembly yes)\n"
                "- 8 - Component of Purchased Asm"
            ),
        ),
        "make_buy": st.column_config.SelectboxColumn(
            "Make vs Buy", options=["", *PART_MAKE_BUY_VALUES], default=""
        ),
        "quantity": None,
        "revision": None,
        "model_applicability": None,
        "image_path": None,
        "feature_applicability": st.column_config.MultiselectColumn(
            "Feature",
            options=feature_options,
            help="Choose All models alone, or feature choices. Within-feature choices are OR; across-feature choices are AND.",
            width="large",
            default=["All models"],
        ),
        "applicability_status": None,
        "notes": st.column_config.TextColumn("Notes", width="large"),
        "source": st.column_config.TextColumn("Source", default=""),
        "created_at": None,
        "created_display": st.column_config.TextColumn(
            "Created",
            default="",
            help="Timestamp when this part record was first created in the catalog.",
        ),
        "updated_at": None,
        "updated_display": st.column_config.TextColumn("Updated", default=""),
    },
)
st.session_state[parts_draft_visible_key] = parts_editor_display_rows.to_dict("records")
parts_actions = editable_table_footer(
    editor_key=parts_editor_key,
    key_prefix="parts_catalog",
    native_row_selection=True,
    additional_unsaved_changes=(
        has_parts_draft or parts_view_has_unsaved_changes
    ),
)
save_part_table = parts_actions.save_and_refresh
if parts_actions.undo:
    clear_parts_editor_draft()
    st.session_state[parts_view_pending_key] = saved_parts_column_order.copy()
    request_table_editor_reset(parts_editor_key)
    st.toast(
        "Discarded the unsaved Parts Catalog edits and table view",
        icon=":material/undo:",
    )
    st.rerun()

export_columns = [
    "active", "part_number", "description", "subsystem", "design_maturity", "factory_nickname",
    "design_engineer", "ppm", "buyer_gcl", "pmqe_aqe",
    "ame_tooling_engineer", "part_code", "pits_tracker_number",
    "source_code", "make_buy", "feature_applicability",
    "photo_status", "notes", "source", "created_at", "updated_at",
]
def _build_filtered_parts_export() -> bytes:
    export_df = parts_for_editing.reindex(columns=export_columns)
    export_hash = _hash_filtered_export(export_df)
    return _cached_parts_dataframe_to_excel(export_hash, export_df, "Parts")


st.download_button(
    "Export filtered rows",
    data=_build_filtered_parts_export,
    file_name="parts_filtered.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    icon=":material/download:",
)

native_selected_parts = native_selected_rows(
    parts_editor_display_rows, editor_key=parts_editor_key
)
selected_all_parts = resolve_editor_selected_rows(
    parts_editor_display_rows,
    edited_parts,
    editor_key=parts_editor_key,
    include_draft_new=True,
)
selected_saved_parts = selected_all_parts.loc[
    ~selected_all_parts["id"].astype(str).str.startswith("__draft_new__")
].copy()
selectable_saved_parts_count = int(
    (
        parts_editor_display_rows["id"].fillna("").astype(str).str.strip().ne("")
        & ~parts_editor_display_rows["id"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.startswith("__draft_new__")
    ).sum()
)
bulk_controls = selected_rows_action_bar(
    parent=parts_action_slot,
)
render_select_all_control(
    bulk_controls,
    editor_key=parts_editor_key,
    selectable_count=selectable_saved_parts_count,
    selected_count=len(selected_saved_parts),
    key_prefix=f"parts_select_{scenario_id}",
)
feature_bulk_controls = selected_rows_action_bar(
    parent=parts_bulk_feature_slot,
)
bulk_applicability = feature_bulk_controls.multiselect(
    "Feature applicability for selected parts",
    options=feature_options,
    placeholder="Choose All models or feature values",
    key="parts_bulk_feature_applicability",
)
apply_bulk_applicability = feature_bulk_controls.button(
    f"Apply to selected ({len(selected_saved_parts)})",
    type="primary",
    icon=":material/checklist:",
    disabled=selected_saved_parts.empty,
)
delete_selected_parts = bulk_controls.button(
    f"Delete selected ({len(selected_all_parts)})",
    icon=":material/delete:",
    disabled=selected_all_parts.empty,
    key="destructive_parts_delete_selected",
    help="Delete the selected part(s) from the project catalog.",
)
if delete_selected_parts or not native_selected_parts.empty:
    selected_draft_ids = set(
        selected_all_parts.loc[
            selected_all_parts["id"].astype(str).str.startswith("__draft_new__"),
            "id",
        ].astype(str)
    )
    if selected_draft_ids:
        st.session_state[parts_draft_added_key] = [
            item
            for item in list(st.session_state.get(parts_draft_added_key, []))
            if str(item.get("id") or "") not in selected_draft_ids
        ]
        current_draft_vals = dict(st.session_state.get(parts_draft_values_key, {}) or {})
        for did in selected_draft_ids:
            current_draft_vals.pop(did, None)
        st.session_state[parts_draft_values_key] = current_draft_vals
        request_table_editor_reset(parts_editor_key)
        if selected_saved_parts.empty:
            st.rerun()
request_delete_bulk_parts = bool(
    (delete_selected_parts or not native_selected_parts.empty)
    and not selected_saved_parts.empty
)

if apply_bulk_applicability:
    if has_parts_draft or table_has_unsaved_changes(
        parts_editor_key, native_row_selection=True
    ):
        st.warning("Save or undo other table edits before applying a bulk feature change.")
    elif not bulk_applicability:
        st.warning("Choose All models or at least one feature value.")
    elif "All models" in bulk_applicability and len(bulk_applicability) > 1:
        st.warning("Choose All models by itself, or choose feature values.")
    else:
        try:
            update_part_feature_rules(
                project_id,
                {
                    str(part_id): [feature_token_by_label[label] for label in bulk_applicability]
                    for part_id in selected_saved_parts["id"]
                },
            )
            record_audit_event(
                project_id, "Parts", "Bulk feature edit", len(selected_saved_parts),
                st.session_state.get("current_editor", ""),
                {"feature_applicability": bulk_applicability},
            )
            clear_parts_editor_draft()
            request_table_editor_reset(parts_editor_key)
            st.toast(
                f"Updated feature applicability for {len(selected_saved_parts)} part(s) to {', '.join(bulk_applicability[:3])}"
                + ("..." if len(bulk_applicability) > 3 else ""),
                icon=":material/check_circle:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

if request_delete_bulk_parts:
    if has_parts_draft or table_has_unsaved_changes(
        parts_editor_key, native_row_selection=True
    ):
        st.warning("Save or undo other table edits before deleting selected parts.")
    else:
        st.session_state[f"parts_pending_bulk_delete_{project_id}"] = selected_saved_parts["id"].astype(str).tolist()
        stage_native_delete_confirmation(parts_editor_key)


@st.dialog("Delete selected parts?", dismissible=False)
def confirm_bulk_part_delete() -> None:
    pending_ids = st.session_state.get(f"parts_pending_bulk_delete_{project_id}", [])
    try:
        impact = part_delete_impact(project_id, pending_ids)
    except ValueError as exc:
        st.error(str(exc))
        return
    st.warning(
        f"This will permanently delete {len(pending_ids)} part(s), their photos, and their Fishbone uses."
    )
    st.caption(
        f"Downstream effects: Removes {impact.get('fishbone_uses', 0)} Fishbone placement(s) and unlinks these parts from "
        f"{impact.get('process_uses', 0)} Process at a Glance part requirement(s). "
        "Yamazumi pitches and Process at a Glance steps themselves will not be deleted."
    )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_bulk_part_delete"):
        st.session_state.pop(f"parts_pending_bulk_delete_{project_id}", None)
        request_table_editor_reset(parts_editor_key)
        st.rerun()
    if actions.button(
        "Delete parts",
        type="primary",
        icon=":material/delete:",
        key="destructive_confirm_bulk_part_delete",
    ):
        deleted_labels = [
            delete_project_part(project_id, str(part_id))
            for part_id in pending_ids
        ]
        deleted_ids = set(pending_ids)
        if st.session_state.get(selected_part_key) in deleted_ids:
            st.session_state.pop(selected_part_key, None)
        record_audit_event(
            project_id, "Parts", "Bulk delete", len(deleted_labels),
            st.session_state.get("current_editor", ""), {"part_numbers": deleted_labels},
        )
        st.session_state.pop(f"parts_pending_bulk_delete_{project_id}", None)
        request_table_editor_reset(parts_editor_key)
        del_part_details: list[str] = []
        if impact.get("fishbone_uses", 0):
            del_part_details.append(f"removed {impact['fishbone_uses']} Fishbone placement(s)")
        if impact.get("process_uses", 0):
            del_part_details.append(f"unlinked {impact['process_uses']} PAAG requirement(s)")
        st.toast(
            f"Deleted {len(deleted_labels)} part(s)"
            + (f" · {', '.join(del_part_details)}" if del_part_details else ""),
            icon=":material/delete:",
        )
        clear_parts_editor_draft()
        st.rerun()


if st.session_state.get(f"parts_pending_bulk_delete_{project_id}"):
    confirm_bulk_part_delete()

if save_part_table:
    try:
        if not selected_parts_columns:
            raise ValueError("Show at least one column before saving the table view.")
        if not selected_saved_parts.empty:
            raise ValueError("Clear the selected rows before saving table edits. Selection is reserved for bulk actions.")
        edited_parts = drop_untouched_new_rows(
            edited_parts, identifying_columns=["part_number"]
        )
        missing_columns = [
            col for col in parts_full_for_editing.columns if col not in edited_parts.columns
        ]
        if missing_columns:
            full_lookup = parts_full_for_editing.drop_duplicates(subset=["id"]).set_index("id")
            for col in missing_columns:
                edited_parts[col] = edited_parts["id"].map(full_lookup[col])
            if "feature_applicability" in missing_columns:
                edited_parts["feature_applicability"] = edited_parts.apply(
                    lambda row: (
                        []
                        if str(row.get("id") or "").strip() in linked_assembly_by_part
                        else (
                            row["feature_applicability"]
                            if isinstance(row["feature_applicability"], list) and row["feature_applicability"]
                            else ["All models"]
                        )
                    ),
                    axis=1,
                )
        edited_parts = merge_filtered_edits(
            parts_full_for_editing,
            parts_for_editing,
            edited_parts,
        )
        def _normalize_row_feature_applicability(row: pd.Series) -> list[str]:
            raw_val = row.get("feature_applicability")
            if isinstance(raw_val, (list, tuple, set)):
                cleaned = [str(item) for item in raw_val if not _is_blank_cell(item)]
            else:
                cleaned = []
            row_id = "" if _is_blank_cell(row.get("id")) else str(row.get("id")).strip()
            is_new = not row_id or row_id.startswith("__draft_new__")
            if is_new and not cleaned:
                return ["All models"]
            return cleaned

        edited_parts["feature_applicability"] = edited_parts.apply(
            _normalize_row_feature_applicability, axis=1
        )
        validation_errors = required_field_errors(edited_parts, {"part_number": "Part number"})
        if validation_errors:
            raise ValueError(" ".join(validation_errors))
        invalid_all = edited_parts["feature_applicability"].apply(
            lambda selected: "All models" in (selected or []) and len(selected or []) > 1
        )
        if invalid_all.any():
            raise ValueError("Choose All models by itself, or choose feature values.")
        missing_rule = edited_parts.apply(
            lambda row: (
                str(row.get("id") or "") not in linked_assembly_by_part
                and not (row.get("feature_applicability") or [])
            ),
            axis=1,
        )
        if missing_rule.any():
            raise ValueError("Every part needs All models or at least one feature choice.")
        parts_to_save = edited_parts.drop(
            columns=[
                "view_details", "active", "photo_status", "feature_applicability",
                "applicability_status", "created_display", "updated_display",
                "assembly_id", "assembly_number",
            ],
            errors="ignore",
        ).copy()
        new_row_mask = (
            parts_to_save["id"].isna()
            | parts_to_save["id"].astype(str).str.strip().eq("")
            | parts_to_save["id"].astype(str).str.startswith("__draft_new__")
        )
        parts_to_save.loc[new_row_mask, "id"] = [str(uuid4()) for _ in range(int(new_row_mask.sum()))]
        edited_parts = edited_parts.copy()
        edited_parts.loc[new_row_mask, "id"] = parts_to_save.loc[new_row_mask, "id"]
        parts_to_save.loc[new_row_mask, "quantity"] = 1
        parts_to_save.loc[new_row_mask, "model_applicability"] = "All"
        parts_to_save.loc[new_row_mask, "source"] = "Manual"
        parts_to_save["revision"] = parts_to_save["design_maturity"]
        parts_to_save["technology_engineer"] = parts_to_save["design_engineer"]
        parts_to_save["official_windchill_part_name"] = parts_to_save["factory_nickname"]
        tracked_fields = {
            "subsystem": "Subsystem",
            "design_maturity": "Design Maturity",
            "factory_nickname": "Factory Nickname",
            "design_engineer": "Design Engineer",
            "ppm": "PPM",
            "buyer_gcl": "Buyer / GCL",
            "pmqe_aqe": "PMQE / AQE",
            "ame_tooling_engineer": "AME / Tooling Engineer",
            "part_code": "Part Code",
            "pits_tracker_number": "PITS ID",
            "source_code": "Source Code",
            "make_buy": "Make vs Buy",
        }
        saved_parts_by_id = (
            parts.set_index(parts["id"].astype(str)).to_dict("index")
            if not parts.empty else {}
        )
        field_changes = []
        for _, row in parts_to_save.iterrows():
            part_id = str(row["id"])
            previous = saved_parts_by_id.get(part_id)
            changed_fields = {}
            for field, label in tracked_fields.items():
                new_value = "" if pd.isna(row.get(field)) else str(row.get(field)).strip()
                old_value = "" if previous is None else str(previous.get(field) or "").strip()
                if previous is None or new_value != old_value:
                    changed_fields[label] = {
                        "old_value": None if previous is None else old_value,
                        "new_value": new_value,
                    }
            if changed_fields:
                field_changes.append(
                    {
                        "part_id": part_id,
                        "part_number": str(row["part_number"]).strip(),
                        "fields": changed_fields,
                    }
                )
        audit_details = {
            "scenario_id": scenario_id, "created_count": int(new_row_mask.sum()), "updated_count": int(count_table_create_and_edit_rows(parts_full_for_editing, edited_parts)[1]),
            "catalog_field_changes": field_changes,
        }
        if parts_view_has_unsaved_changes:
            audit_details["table_view_change"] = {
                "old_column_order": saved_parts_column_order,
                "new_column_order": selected_parts_columns,
            }
        with connection() as conn:
            count = update_part_rows(
                project_id,
                parts_to_save,
                scenario_id=scenario_id,
                activity_by_part={
                    str(row["id"]): (
                        True
                        if row.get("active") is None or pd.isna(row.get("active"))
                        else bool(row.get("active"))
                    )
                    for _, row in edited_parts.iterrows()
                },
                _conn=conn,
            )
            update_part_feature_rules(
                project_id,
                {
                    str(row["id"]): [
                        feature_token_by_label[label]
                        for label in (row["feature_applicability"] or [])
                        if label in feature_token_by_label
                    ]
                    for _, row in edited_parts.iterrows()
                },
                _conn=conn,
            )
            save_table_view_preference(
                project_id,
                current_editor,
                PARTS_VIEW_KEY,
                selected_parts_columns,
                selected_parts_columns,
                _conn=conn,
            )
            record_audit_event(
                project_id,
                "Parts",
                "Save & Refresh",
                count,
                current_editor,
                audit_details,
                _conn=conn,
            )
        clear_parts_editor_draft()
        st.session_state[parts_view_pending_key] = selected_parts_columns.copy()
        request_table_editor_reset(parts_editor_key)
        st.toast(
            f"Saved {count} part(s) in Parts Catalog"
            + (f" ({len(field_changes)} row(s) modified)" if field_changes else "")
            + (" · updated table view" if parts_view_has_unsaved_changes else ""),
            icon=":material/check_circle:",
        )
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

def render_parts_history() -> None:
    """Render Parts history at the bottom of the current page state."""
    with st.expander("Parts history", icon=":material/history:"):
        history = audit_history(project_id, "Parts", limit=50)
        if history.empty:
            st.caption("No standardized Parts Catalog changes have been recorded yet.")
        else:
            render_audit_history_table(
                history.drop(columns=["details"], errors="ignore"),
                key=f"parts_history_table_{project_id}",
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

if parts.empty:
    st.info("Type or paste the first part into the blank entry row, then select Save & Refresh.")
    render_parts_history()
    st.stop()

valid_part_ids = set(parts["id"].astype(str))
if st.session_state.get(selected_part_key) not in valid_part_ids:
    st.session_state[selected_part_key] = str(parts.iloc[0]["id"])
part = parts.loc[parts["id"].astype(str) == st.session_state[selected_part_key]].iloc[0].to_dict()
part_name = str(part.get("description") or "").strip()
part_details_title = f"Part Details · {part['part_number']}"
if part_name:
    part_details_title += f" {part_name}"
st.html('<div id="part-details-section"></div>')
st.subheader(part_details_title)
if st.session_state.pop("parts_scroll_to_details", False):
    st.html(
        """<script>
        function scrollToDetails() {
            try {
                const parentDoc = window.parent ? window.parent.document : document;
                const elem = (parentDoc && parentDoc.getElementById('part-details-section')) || document.getElementById('part-details-section');
                if (elem) {
                    elem.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    return true;
                }
            } catch (e) {
                const elem = document.getElementById('part-details-section');
                if (elem) {
                    elem.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    return true;
                }
            }
            return false;
        }
        setTimeout(scrollToDetails, 150);
        setTimeout(scrollToDetails, 450);
        </script>""",
        unsafe_allow_javascript=True,
    )


def _mime_for_part_image_suffix(suffix: str) -> str:
    ext = str(suffix or "").lower().lstrip(".")
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, "image/png")


def _has_part_image_annotations(annotations_json: object) -> bool:
    raw = str(annotations_json or "").strip()
    return bool(raw and raw != "[]")


def _composite_upload_filename(filename: str, has_annotations: bool) -> str:
    base_name = Path(str(filename or "part_image.png")).name
    if not has_annotations:
        return base_name
    stem = Path(base_name).stem or "part_image"
    return f"{stem}.png"


@st.dialog("Annotate Primary Part Image", width="large")
def annotate_part_primary_image_dialog(part_row: dict, active_project_id: str) -> None:
    orig_path_str = (
        str(part_row.get("original_image_path") or "").strip()
        or str(part_row.get("image_path") or "").strip()
    )
    img_path = Path(orig_path_str) if orig_path_str else None
    if not img_path or not img_path.exists():
        fallback_str = str(part_row.get("image_path") or "").strip()
        img_path = Path(fallback_str) if fallback_str else None
    if not img_path or not img_path.exists():
        st.error("Image file not found on disk.")
        return

    raw_bytes = img_path.read_bytes()
    mime = _mime_for_part_image_suffix(img_path.suffix)
    b64_str = base64.b64encode(raw_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64_str}"

    st.caption(
        f"**Part:** `{part_row.get('part_number', '')}` — Crop, rotate in 90° increments, or draw arrows, callouts, shapes, and text. "
        "Click **💾 Apply & Save Markup** in the toolbar when finished."
    )
    annotator_res = image_annotator(
        image_data_url=data_url,
        annotations_json=str(part_row.get("annotations_json") or ""),
        key=f"annotator_part_prim_{part_row['id']}",
    )
    if annotator_res is not None:
        save_payload = getattr(annotator_res, "save", None)
        cancel_payload = getattr(annotator_res, "cancel", None)
        if isinstance(save_payload, dict):
            new_annotations = str(save_payload.get("annotations_json") or "")
            new_data_url = str(
                save_payload.get("data_url")
                or save_payload.get("composite_data_url")
                or ""
            )
            composite_bytes = decode_data_url(new_data_url) if new_data_url else None
            try:
                update_part_primary_image_annotations(
                    project_id=active_project_id,
                    part_id=str(part_row["id"]),
                    annotations_json=new_annotations,
                    composite_image_bytes=composite_bytes,
                    current_editor=st.session_state.get("current_editor", "Collaborator"),
                )
                st.toast("Annotations saved!", icon=":material/check_circle:")
                st.rerun()
            except ValueError as err:
                st.error(str(err))
        elif cancel_payload:
            st.rerun()


@st.dialog("Annotate Additional Part View", width="large")
def annotate_part_supplemental_image_dialog(supplemental: dict, active_project_id: str) -> None:
    orig_path_str = (
        str(supplemental.get("original_image_path") or "").strip()
        or str(supplemental.get("image_path") or "").strip()
    )
    img_path = Path(orig_path_str) if orig_path_str else None
    if not img_path or not img_path.exists():
        fallback_str = str(supplemental.get("image_path") or "").strip()
        img_path = Path(fallback_str) if fallback_str else None
    if not img_path or not img_path.exists():
        st.error("Image file not found on disk.")
        return

    raw_bytes = img_path.read_bytes()
    mime = _mime_for_part_image_suffix(img_path.suffix)
    b64_str = base64.b64encode(raw_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64_str}"

    view_label = supplemental.get("caption") or supplemental.get("image_type") or "Additional View"
    st.caption(
        f"**View:** {view_label} — Crop, rotate in 90° increments, or draw arrows, callouts, shapes, and text. "
        "Click **💾 Apply & Save Markup** in the toolbar when finished."
    )
    annotator_res = image_annotator(
        image_data_url=data_url,
        annotations_json=str(supplemental.get("annotations_json") or ""),
        key=f"annotator_part_supp_{supplemental['id']}",
    )
    if annotator_res is not None:
        save_payload = getattr(annotator_res, "save", None)
        cancel_payload = getattr(annotator_res, "cancel", None)
        if isinstance(save_payload, dict):
            new_annotations = str(save_payload.get("annotations_json") or "")
            new_data_url = str(
                save_payload.get("data_url")
                or save_payload.get("composite_data_url")
                or ""
            )
            composite_bytes = decode_data_url(new_data_url) if new_data_url else None
            try:
                update_part_supplemental_image_annotations(
                    project_id=active_project_id,
                    image_id=str(supplemental["id"]),
                    annotations_json=new_annotations,
                    composite_image_bytes=composite_bytes,
                    current_editor=st.session_state.get("current_editor", "Collaborator"),
                )
                st.toast("Annotations saved!", icon=":material/check_circle:")
                st.rerun()
            except ValueError as err:
                st.error(str(err))
        elif cancel_payload:
            st.rerun()


@st.dialog("Annotate Staged Part Image", width="large")
def annotate_staged_part_image_dialog(staged_state_key: str) -> None:
    staged = st.session_state.get(staged_state_key)
    if not isinstance(staged, dict) or not staged.get("original_bytes"):
        st.error("No staged image found.")
        return

    raw_bytes = staged["original_bytes"]
    mime = staged.get("mime_type", "image/png")
    b64_str = base64.b64encode(raw_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64_str}"

    st.caption(
        "Crop, rotate in 90° increments, or draw arrows, callouts, shapes, and text on the staged part image. "
        "Click **💾 Apply & Save Markup** in the toolbar when finished."
    )
    annotator_res = image_annotator(
        image_data_url=data_url,
        annotations_json=str(staged.get("annotations_json") or ""),
        key=f"annotator_{staged_state_key}",
    )
    if annotator_res is not None:
        save_payload = getattr(annotator_res, "save", None)
        cancel_payload = getattr(annotator_res, "cancel", None)
        if isinstance(save_payload, dict):
            new_annotations = str(save_payload.get("annotations_json") or "")
            new_data_url = str(
                save_payload.get("data_url")
                or save_payload.get("composite_data_url")
                or ""
            )
            composite_bytes = decode_data_url(new_data_url) if new_data_url else raw_bytes
            staged["composite_bytes"] = composite_bytes or raw_bytes
            staged["annotations_json"] = new_annotations
            st.session_state[staged_state_key] = staged
            st.toast("Markup applied to staged image!", icon=":material/check_circle:")
            st.rerun()
        elif cancel_payload:
            st.rerun()


image_col, details_col = st.columns([2, 3])
with image_col.container(border=True):
    st.subheader("Primary Image")
    raw_img = str(part.get("image_path") or "").strip()
    prim_caption = str(part.get("image_caption") or "").strip()
    prim_display_caption = f"{part['part_number']} — {prim_caption}" if prim_caption else str(part["part_number"])
    is_url = raw_img.startswith(("http://", "https://"))
    if is_url:
        lower_url = raw_img.lower()
        if any(lower_url.endswith(ext) or (ext + "?") in lower_url for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"]):
            st.image(raw_img, caption=prim_display_caption)
        if prim_caption:
            st.caption(f"**Caption / Notes:** {prim_caption}")
        c_link1, c_link2 = st.columns([3, 1])
        with c_link1:
            st.link_button("Open CAD / Web Link", raw_img, icon=":material/open_in_new:")
        with c_link2:
            if st.button("Delete", icon=":material/delete:", key=f"destructive_del_prim_url_{part['id']}", help="Delete this CAD web link"):
                st.session_state[f"parts_pending_del_prim_url_{part['id']}"] = True
                st.rerun()
    elif raw_img:
        image_path = Path(raw_img)
        if image_path.exists():
            st.image(
                cached_image_bytes(image_path, max_dim=1200) or str(image_path),
                caption=prim_display_caption,
            )
            if prim_caption:
                st.caption(f"**Caption / Notes:** {prim_caption}")
            if _has_part_image_annotations(part.get("annotations_json")):
                st.caption(":material/draw: **Annotated** (editable vector shapes)")
            prim_act_bar = st.container(horizontal=True)
            if prim_act_bar.button(
                "Annotate",
                icon=":material/draw:",
                key=f"btn_ann_prim_img_{part['id']}",
                help="Crop, rotate 90°, or draw arrows, callouts, shapes, and text on this part image",
            ):
                annotate_part_primary_image_dialog(dict(part), project_id)
            if prim_act_bar.button(
                "Remove Image",
                icon=":material/delete:",
                key=f"destructive_del_prim_img_{part['id']}",
            ):
                st.session_state[f"parts_pending_del_prim_img_{part['id']}"] = True
                st.rerun()
        else:
            st.caption("No image attached.")
    else:
        st.caption("No image or web link attached.")

    if st.session_state.pop(f"_clear_prim_caption_{part['id']}", False):
        st.session_state.pop(f"prim_upload_caption_{part['id']}", None)

    tab_upload_clip, tab_url = st.tabs(["Upload / Clipboard", "Web Link / URL"])

    with tab_upload_clip:
        staged_prim_key = f"staged_prim_upload_{part['id']}"
        last_prim_paste_hash_key = f"last_prim_paste_hash_{part['id']}"
        last_prim_upload_hash_key = f"last_prim_upload_hash_{part['id']}"
        discarded_prim_up_key = f"_discarded_prim_up_{part['id']}"

        uploaded = st.file_uploader(
            "Upload photo or rendered view",
            type=["png", "jpg", "jpeg", "webp"],
            key=f"image_{part['id']}",
            help="Photos: max 10 MB (PNG, JPG, WEBP)",
        )
        st.caption("Photos: max **10 MB** (PNG, JPG, WEBP)")

        st.caption("Or take a photo with your camera / paste a screenshot (Win+Shift+S / Ctrl+V):")
        primary_clipboard_key = f"clipboard_primary_{part['id']}"
        pasted = clipboard_image(key=primary_clipboard_key)

        prim_upload_caption = st.text_input(
            "Caption / Notes (optional)",
            placeholder="Optional photo notes, revision, or callout summary...",
            key=f"prim_upload_caption_{part['id']}",
        )

        pasted_payload = getattr(pasted, "image", None)
        if pasted_payload:
            try:
                primary_image = decode_clipboard_image(pasted_payload)
                raw_paste_bytes = primary_image["bytes"]
                paste_hash = hashlib.sha256(raw_paste_bytes).hexdigest()[:16]
                if st.session_state.get(last_prim_paste_hash_key) != paste_hash:
                    st.session_state[last_prim_paste_hash_key] = paste_hash
                    paste_name = primary_image.get("name") or "clipboard.png"
                    st.session_state[staged_prim_key] = {
                        "source": "clipboard",
                        "source_hash": paste_hash,
                        "original_bytes": raw_paste_bytes,
                        "composite_bytes": raw_paste_bytes,
                        "mime_type": _mime_for_part_image_suffix(Path(paste_name).suffix),
                        "filename": paste_name,
                        "annotations_json": "",
                    }
            except (OSError, ValueError) as exc:
                st.error(str(exc))

        if uploaded is not None:
            raw_up_bytes = uploaded.getvalue()
            up_hash = hashlib.sha256(raw_up_bytes).hexdigest()[:16]
            existing_staged_prim = st.session_state.get(staged_prim_key)
            if st.session_state.get(last_prim_upload_hash_key) != up_hash or (
                not isinstance(existing_staged_prim, dict)
                and st.session_state.get(discarded_prim_up_key) != up_hash
            ):
                st.session_state[last_prim_upload_hash_key] = up_hash
                st.session_state.pop(discarded_prim_up_key, None)
                st.session_state[staged_prim_key] = {
                    "source": "upload",
                    "source_hash": up_hash,
                    "original_bytes": raw_up_bytes,
                    "composite_bytes": raw_up_bytes,
                    "mime_type": _mime_for_part_image_suffix(Path(uploaded.name or "image.png").suffix),
                    "filename": uploaded.name or "part_image.png",
                    "annotations_json": "",
                }
        else:
            st.session_state.pop(last_prim_upload_hash_key, None)
            st.session_state.pop(discarded_prim_up_key, None)
            existing_staged_prim = st.session_state.get(staged_prim_key)
            if isinstance(existing_staged_prim, dict) and existing_staged_prim.get("source") == "upload":
                st.session_state.pop(staged_prim_key, None)

        staged_prim = st.session_state.get(staged_prim_key)
        if isinstance(staged_prim, dict) and staged_prim.get("composite_bytes"):
            with st.container(border=True):
                st_c1, st_c2 = st.columns([2, 3])
                with st_c1:
                    st.image(staged_prim["composite_bytes"], width="stretch")
                with st_c2:
                    has_staged_markup = _has_part_image_annotations(staged_prim.get("annotations_json"))
                    if has_staged_markup:
                        st.caption(":material/check_circle: **Markup applied** (editable vector shapes)")
                    else:
                        st.caption("Ready to save — click **Annotate / Add Shapes** to add callouts before saving.")
                    staged_prim_btns = st.container(horizontal=True)
                    if staged_prim_btns.button(
                        "Annotate / Add Shapes",
                        icon=":material/draw:",
                        key=f"btn_ann_staged_prim_up_{part['id']}",
                    ):
                        annotate_staged_part_image_dialog(staged_prim_key)
                    if staged_prim_btns.button(
                        "Delete",
                        icon=":material/delete:",
                        key=f"destructive_discard_staged_prim_{part['id']}",
                    ):
                        st.session_state[f"parts_pending_discard_staged_prim_{part['id']}"] = True
                        st.rerun()

        if st.button("Save Primary Image", type="primary", icon=":material/add_photo_alternate:", key=f"btn_save_img_{part['id']}"):
            if not isinstance(staged_prim, dict) or not staged_prim.get("composite_bytes"):
                st.error("Please upload an image file or paste a screenshot from your clipboard first.")
            else:
                had_previous = bool(raw_img)
                is_clipboard = staged_prim.get("source") == "clipboard"
                has_staged_markup = _has_part_image_annotations(staged_prim.get("annotations_json"))
                comp_filename = _composite_upload_filename(staged_prim["filename"], has_staged_markup)
                comp_file = as_uploaded_file({"name": comp_filename, "bytes": staged_prim["composite_bytes"]})
                set_part_image(
                    part["id"],
                    comp_file,
                    original_file_bytes=staged_prim["original_bytes"],
                    original_filename=staged_prim["filename"],
                    annotations_json=str(staged_prim.get("annotations_json") or ""),
                    caption=prim_upload_caption,
                )
                if staged_prim.get("source") == "upload":
                    st.session_state[discarded_prim_up_key] = staged_prim.get("source_hash")
                st.session_state.pop(staged_prim_key, None)
                st.session_state[f"_clear_prim_caption_{part['id']}"] = True
                record_audit_event(
                    project_id,
                    "Parts",
                    "Paste Primary CAD image" if is_clipboard else "Save image",
                    1,
                    st.session_state.get("current_editor", ""),
                    {
                        "part_id": str(part["id"]),
                        "part_number": str(part["part_number"]),
                        "primary_cad_image_replaced_via": "clipboard" if is_clipboard else "upload",
                        "annotated": bool(has_staged_markup),
                        "caption": str(prim_upload_caption or "").strip(),
                        "archived_previous_primary": had_previous,
                    },
                )
                st.toast(
                    "Primary Image saved (previous Primary Image moved to Additional views)"
                    if had_previous
                    else "Primary Image saved",
                    icon=":material/check_circle:",
                )
                st.rerun()

    with tab_url:
        cad_url = st.text_input(
            "Attach CAD / PLM / Web Link",
            value=raw_img if is_url else "",
            placeholder="https://windchill... or https://sharepoint...",
            key=f"url_cad_{part['id']}",
            help="Enter a web URL for this part's 3D CAD model, Windchill drawing, or online specification.",
        )
        prim_url_caption = st.text_input(
            "Caption / Notes (optional)",
            value=prim_caption if is_url else "",
            placeholder="Optional photo notes, revision, or callout summary...",
            key=f"prim_url_caption_{part['id']}",
        )
        if st.button("Save CAD Link", type="primary", icon=":material/link:", key=f"btn_save_cad_url_{part['id']}"):
            if not cad_url or not cad_url.strip().startswith(("http://", "https://")):
                st.error("Please enter a valid URL starting with http:// or https://")
            else:
                had_previous = bool(raw_img and raw_img != cad_url.strip())
                set_part_image_url(part["id"], cad_url.strip(), caption=prim_url_caption)
                record_audit_event(
                    project_id,
                    "Parts",
                    "Save CAD web link",
                    1,
                    st.session_state.get("current_editor", ""),
                    {
                        "part_id": str(part["id"]),
                        "part_number": str(part["part_number"]),
                        "url": cad_url.strip(),
                        "caption": str(prim_url_caption or "").strip(),
                        "archived_previous_primary": had_previous,
                    },
                )
                st.toast(
                    "CAD web link attached (previous Primary Image moved to Additional views)"
                    if had_previous
                    else "CAD web link attached",
                    icon=":material/check_circle:",
                )
                st.rerun()

    @st.dialog("Delete Primary CAD / Web Link?", dismissible=False)
    def _confirm_del_prim_url_dialog() -> None:
        st.warning(f"Delete the primary CAD / web link from part **{part['part_number']}**?")
        st.caption(
            "Downstream effects: This removes the primary web link from this part across the Parts Catalog, Fishbone, and Process at a Glance. "
            "The part record, its BOM and Fishbone uses, Process pairings, and any Additional views remain intact."
        )
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_del_prim_url_{part['id']}"):
            st.session_state.pop(f"parts_pending_del_prim_url_{part['id']}", None)
            st.rerun()
        if actions.button(
            "Delete",
            type="primary",
            icon=":material/delete:",
            key=f"destructive_confirm_del_prim_url_{part['id']}",
        ):
            clear_part_image(part["id"])
            st.toast(f"Removed external image link for {part['part_number']}", icon=":material/delete:")
            record_audit_event(
                project_id,
                "Parts",
                "Remove CAD image link",
                1,
                st.session_state.get("current_editor", ""),
                {"part_id": str(part["id"]), "part_number": str(part["part_number"])},
            )
            st.session_state.pop(f"parts_pending_del_prim_url_{part['id']}", None)
            st.rerun()

    @st.dialog("Remove Primary Part Image?", dismissible=False)
    def _confirm_del_prim_img_dialog() -> None:
        st.markdown(f"Choose how to remove the primary image from part **{part['part_number']}**:")
        remove_mode = st.radio(
            "Removal action",
            options=["move", "delete"],
            format_func=lambda opt: (
                "Remove as the primary image and move to Additional views"
                if opt == "move"
                else "Permanently delete the image"
            ),
            key=f"prim_img_remove_mode_{part['id']}",
            label_visibility="collapsed",
        )
        if remove_mode == "move":
            st.info(
                f"Move the current primary image for **{part['part_number']}** to **Additional views** and clear the Primary Image slot?"
            )
            st.caption(
                "Downstream effects: This removes the image as the primary thumbnail across the Parts Catalog, Fishbone, and Process at a Glance, "
                "while preserving the image file, its editable annotations, and its caption in this part's Additional views."
            )
        else:
            st.warning(f"Permanently delete the primary image from part **{part['part_number']}**?")
            st.caption(
                "Downstream effects: This permanently deletes the primary image file and its annotations from this part across the Parts Catalog, Fishbone, and Process at a Glance. "
                "The part record, its BOM and Fishbone uses, Process pairings, and any Additional views remain intact."
            )
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_del_prim_img_{part['id']}"):
            st.session_state.pop(f"parts_pending_del_prim_img_{part['id']}", None)
            st.session_state.pop(f"prim_img_remove_mode_{part['id']}", None)
            st.rerun()
        confirm_label = "Remove & Move to Additional Views" if remove_mode == "move" else "Permanently Delete Image"
        confirm_icon = ":material/collections:" if remove_mode == "move" else ":material/delete:"
        if actions.button(
            confirm_label,
            type="primary",
            icon=confirm_icon,
            key=f"destructive_confirm_del_prim_img_{part['id']}",
        ):
            move_to_additional = remove_mode == "move"
            archived = clear_part_image(part["id"], move_to_additional_views=move_to_additional)
            record_audit_event(
                project_id,
                "Parts",
                "Move primary image to additional views" if move_to_additional else "Remove CAD image",
                1,
                st.session_state.get("current_editor", ""),
                {
                    "part_id": str(part["id"]),
                    "part_number": str(part["part_number"]),
                    "moved_to_additional_views": bool(archived),
                },
            )
            st.session_state.pop(f"parts_pending_del_prim_img_{part['id']}", None)
            st.session_state.pop(f"prim_img_remove_mode_{part['id']}", None)
            st.toast(
                "Primary Image removed and moved to Additional views"
                if archived
                else "Primary Image permanently deleted",
                icon=":material/check_circle:",
            )
            st.rerun()
    @st.dialog("Delete Staged Primary Image?", dismissible=False)
    def _confirm_discard_staged_prim_dialog() -> None:
        st.warning(f"Delete the unsaved staged image for part **{part['part_number']}**?")
        st.caption(
            "Downstream effects: This removes the unsaved upload or clipboard capture and any unsaved markup/crop/rotation before saving. "
            "The part's currently saved Primary Image and Additional views will not be changed."
        )
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_discard_staged_prim_{part['id']}"):
            st.session_state.pop(f"parts_pending_discard_staged_prim_{part['id']}", None)
            st.rerun()
        if actions.button(
            "Delete",
            type="primary",
            icon=":material/delete:",
            key=f"destructive_confirm_discard_staged_prim_{part['id']}",
        ):
            cur_staged = st.session_state.get(staged_prim_key)
            st.toast(f"Discarded staged primary image for {part['part_number']}", icon=":material/delete:")
            if isinstance(cur_staged, dict) and cur_staged.get("source") == "upload":
                st.session_state[discarded_prim_up_key] = cur_staged.get("source_hash")
            st.session_state.pop(staged_prim_key, None)
            st.session_state.pop(f"parts_pending_discard_staged_prim_{part['id']}", None)
            st.rerun()

    @st.dialog("Delete Additional View?", dismissible=False)
    def _confirm_del_supp_dialog() -> None:
        pending_supp = st.session_state.get(f"parts_pending_del_supp_{part['id']}") or {}
        target_supp_id = str(pending_supp.get("id") or "")
        target_supp_caption = str(pending_supp.get("caption") or "Additional View")
        st.warning(
            f"Permanently delete the additional view **{target_supp_caption}** from part **{part['part_number']}**?"
        )
        st.caption(
            "Downstream effects: This permanently deletes this additional view file/link and any annotations on it. "
            "The part record, its Primary Image, and its BOM, Fishbone, and Process at a Glance uses remain intact."
        )
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_del_supp_{target_supp_id}"):
            st.session_state.pop(f"parts_pending_del_supp_{part['id']}", None)
            st.rerun()
        if actions.button(
            "Delete",
            type="primary",
            icon=":material/delete:",
            key=f"destructive_confirm_del_supp_{target_supp_id}",
        ):
            if target_supp_id:
                delete_part_image(target_supp_id)
                record_audit_event(
                    project_id,
                    "Parts",
                    "Delete view",
                    1,
                    st.session_state.get("current_editor", ""),
                    {
                        "part_id": str(part["id"]),
                        "part_number": str(part["part_number"]),
                        "image_id": target_supp_id,
                    },
                )
                st.toast("View deleted", icon=":material/check_circle:")
            st.session_state.pop(f"parts_pending_del_supp_{part['id']}", None)
            st.rerun()

    @st.dialog("Delete Staged Additional View?", dismissible=False)
    def _confirm_discard_staged_supp_dialog() -> None:
        st.warning(f"Delete the unsaved staged additional view for part **{part['part_number']}**?")
        st.caption(
            "Downstream effects: This removes the unsaved upload or clipboard capture and any unsaved markup/crop/rotation before adding the view. "
            "The part's saved Primary Image and existing Additional views will not be changed."
        )
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_discard_staged_supp_{part['id']}"):
            st.session_state.pop(f"parts_pending_discard_staged_supp_{part['id']}", None)
            st.rerun()
        if actions.button(
            "Delete",
            type="primary",
            icon=":material/delete:",
            key=f"destructive_confirm_discard_staged_supp_{part['id']}",
        ):
            s_key = f"staged_supp_upload_{part['id']}"
            d_key = f"_discarded_supp_up_{part['id']}"
            cur_staged = st.session_state.get(s_key)
            if isinstance(cur_staged, dict) and cur_staged.get("source") == "upload":
                st.session_state[d_key] = cur_staged.get("source_hash")
            st.session_state.pop(s_key, None)
            st.toast(f"Discarded staged additional view for {part['part_number']}", icon=":material/delete:")
            st.session_state.pop(f"parts_pending_discard_staged_supp_{part['id']}", None)
            st.rerun()

    if st.session_state.get(f"parts_pending_del_prim_url_{part['id']}"):
        _confirm_del_prim_url_dialog()
    elif st.session_state.get(f"parts_pending_del_prim_img_{part['id']}"):
        _confirm_del_prim_img_dialog()
    elif st.session_state.get(f"parts_pending_discard_staged_prim_{part['id']}"):
        _confirm_discard_staged_prim_dialog()
    elif st.session_state.get(f"parts_pending_del_supp_{part['id']}"):
        _confirm_del_supp_dialog()
    elif st.session_state.get(f"parts_pending_discard_staged_supp_{part['id']}"):
        _confirm_discard_staged_supp_dialog()

    st.subheader("Additional views")
    images = part_images(part["id"])
    for supplemental in images:
        supp_raw = str(supplemental.get("image_path") or "").strip()
        supp_caption = supplemental.get("caption") or supplemental.get("image_type") or "Additional View"
        supp_id = supplemental.get("id")
        is_supp_url = supp_raw.startswith(("http://", "https://"))
        supp_path_obj = Path(supp_raw) if (supp_raw and not is_supp_url) else None
        is_supp_raster = bool(
            supp_path_obj
            and supp_path_obj.exists()
            and supp_path_obj.suffix.lower() not in {".step", ".stp"}
        )
        with st.container(border=True):
            if is_supp_url:
                lower_supp = supp_raw.lower()
                if any(lower_supp.endswith(ext) or (ext + "?") in lower_supp for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"]):
                    st.image(supp_raw, caption=supp_caption)
                st.link_button(f":material/open_in_new: {supp_caption}", supp_raw)
                st.caption(f"Type: `{supplemental.get('image_type')}` | URL: {supp_raw}")
            else:
                if supp_path_obj and supp_path_obj.exists():
                    supp_suffix = supp_path_obj.suffix.lower()
                    if supp_suffix in {".step", ".stp"}:
                        size_mb = supp_path_obj.stat().st_size / (1024 * 1024)
                        st.markdown(f":material/view_in_ar: **3D CAD Model (STEP)** — `{supp_path_obj.name}` ({size_mb:.1f} MB)")
                        if supp_caption and supp_caption != "3D CAD Model (STEP)":
                            st.caption(supp_caption)
                        st.download_button(
                            "Download STEP file",
                            data=lambda p=supp_path_obj: p.read_bytes(),
                            file_name=f"{part['part_number']}_{supp_path_obj.name}",
                            mime="application/step",
                            icon=":material/download:",
                            key=f"dl_supp_{supp_id}",
                        )
                    else:
                        st.image(
                            cached_image_bytes(supp_path_obj, max_dim=1200) or str(supp_path_obj),
                            caption=supp_caption,
                        )
                if _has_part_image_annotations(supplemental.get("annotations_json")):
                    st.caption(f"Type: `{supplemental.get('image_type')}` | :material/draw: **Annotated**")
                else:
                    st.caption(f"Type: `{supplemental.get('image_type')}`")
            supp_act_bar = st.container(horizontal=True)
            if is_supp_raster or is_supp_url:
                if supp_act_bar.button(
                    "Make primary",
                    icon=":material/star:",
                    key=f"make_prim_supp_{supp_id}",
                    help="Set this view as the Primary Image (any current Primary Image moves to Additional views)",
                ):
                    try:
                        res = promote_part_image_to_primary(part["id"], str(supp_id))
                        record_audit_event(
                            project_id,
                            "Parts",
                            "Promote view to primary image",
                            1,
                            st.session_state.get("current_editor", ""),
                            {
                                "part_id": str(part["id"]),
                                "part_number": str(part["part_number"]),
                                "promoted_image_id": str(supp_id),
                                "archived_previous_primary": bool(res.get("had_previous_primary")),
                            },
                        )
                        st.toast(
                            "Switched to Primary Image (previous Primary Image moved to Additional views)"
                            if res.get("had_previous_primary")
                            else "Set as Primary Image",
                            icon=":material/check_circle:",
                        )
                        st.rerun()
                    except ValueError as ve:
                        st.error(str(ve))
            if is_supp_raster:
                if supp_act_bar.button(
                    "Annotate",
                    icon=":material/draw:",
                    key=f"ann_supp_{supp_id}",
                    help="Crop, rotate 90°, or draw arrows, callouts, shapes, and text on this view",
                ):
                    annotate_part_supplemental_image_dialog(dict(supplemental), project_id)
            if supp_act_bar.button(
                "Delete",
                icon=":material/delete:",
                key=f"destructive_del_supp_{supp_id}",
            ):
                st.session_state[f"parts_pending_del_supp_{part['id']}"] = {
                    "id": str(supp_id),
                    "caption": str(supp_caption),
                }
                st.rerun()

    with st.expander("Add an exploded view, 3D CAD model, drawing, or web link", icon=":material/add_photo_alternate:"):
        if st.session_state.pop(f"_clear_supp_caption_{part['id']}", False):
            st.session_state.pop(f"supp_caption_{part['id']}", None)

        view_types = [
            "3D CAD Model (STEP)",
            "Exploded assembly",
            "Alternate CAD view",
            "Previous primary image",
            "CAD / Drawing Link",
            "SharePoint Document",
            "Prototype photo",
            "Quality detail",
            "Other",
        ]
        image_type = st.selectbox("View type", view_types, key=f"supp_type_{part['id']}")
        caption = st.text_input("Caption / Notes (optional)", key=f"supp_caption_{part['id']}")

        supp_tab_upload_clip, supp_tab_url = st.tabs(["Upload / Clipboard", "Web Link / URL"])

        with supp_tab_upload_clip:
            staged_supp_upload_key = f"staged_supp_upload_{part['id']}"
            last_supp_paste_hash_key = f"last_supp_paste_hash_{part['id']}"
            last_supp_upload_hash_key = f"last_supp_upload_hash_{part['id']}"
            discarded_supp_up_key = f"_discarded_supp_up_{part['id']}"

            extra = st.file_uploader(
                "Upload image file or 3D CAD STEP file",
                type=["png", "jpg", "jpeg", "webp", "step", "stp"],
                key=f"supp_file_{part['id']}",
                help="Images: max 10 MB (PNG, JPG, WEBP) • 3D CAD: max 50 MB (STEP, STP)",
            )
            st.caption("Images: max **10 MB** (PNG, JPG, WEBP) • 3D CAD: max **50 MB** (STEP, STP)")

            st.caption("Or take a photo with your camera / paste a screenshot (Win+Shift+S / Ctrl+V):")
            supp_clipboard_key = f"clipboard_supp_{part['id']}"
            supp_pasted = clipboard_image(key=supp_clipboard_key)
            supp_pasted_payload = getattr(supp_pasted, "image", None)
            if supp_pasted_payload:
                try:
                    supp_clip_img = decode_clipboard_image(supp_pasted_payload)
                    raw_sp_bytes = supp_clip_img["bytes"]
                    sp_hash = hashlib.sha256(raw_sp_bytes).hexdigest()[:16]
                    if st.session_state.get(last_supp_paste_hash_key) != sp_hash:
                        st.session_state[last_supp_paste_hash_key] = sp_hash
                        sp_name = supp_clip_img.get("name") or "clipboard_view.png"
                        st.session_state[staged_supp_upload_key] = {
                            "source": "clipboard",
                            "source_hash": sp_hash,
                            "original_bytes": raw_sp_bytes,
                            "composite_bytes": raw_sp_bytes,
                            "mime_type": _mime_for_part_image_suffix(Path(sp_name).suffix),
                            "filename": sp_name,
                            "annotations_json": "",
                        }
                except (OSError, ValueError) as exc:
                    st.error(str(exc))

            is_extra_step = bool(extra is not None and (extra.name or "").lower().endswith((".step", ".stp")))
            if extra is not None and not is_extra_step:
                raw_supp_bytes = extra.getvalue()
                supp_hash = hashlib.sha256(raw_supp_bytes).hexdigest()[:16]
                existing_staged_supp = st.session_state.get(staged_supp_upload_key)
                if st.session_state.get(last_supp_upload_hash_key) != supp_hash or (
                    not isinstance(existing_staged_supp, dict)
                    and st.session_state.get(discarded_supp_up_key) != supp_hash
                ):
                    st.session_state[last_supp_upload_hash_key] = supp_hash
                    st.session_state.pop(discarded_supp_up_key, None)
                    st.session_state[staged_supp_upload_key] = {
                        "source": "upload",
                        "source_hash": supp_hash,
                        "original_bytes": raw_supp_bytes,
                        "composite_bytes": raw_supp_bytes,
                        "mime_type": _mime_for_part_image_suffix(Path(extra.name or "image.png").suffix),
                        "filename": extra.name or "view.png",
                        "annotations_json": "",
                    }
            else:
                st.session_state.pop(last_supp_upload_hash_key, None)
                st.session_state.pop(discarded_supp_up_key, None)
                existing_staged_supp = st.session_state.get(staged_supp_upload_key)
                if isinstance(existing_staged_supp, dict) and existing_staged_supp.get("source") == "upload":
                    st.session_state.pop(staged_supp_upload_key, None)

            staged_supp_up = st.session_state.get(staged_supp_upload_key)
            if isinstance(staged_supp_up, dict) and staged_supp_up.get("composite_bytes"):
                with st.container(border=True):
                    su_c1, su_c2 = st.columns([2, 3])
                    with su_c1:
                        st.image(staged_supp_up["composite_bytes"], width="stretch")
                    with su_c2:
                        has_supp_markup = _has_part_image_annotations(staged_supp_up.get("annotations_json"))
                        if has_supp_markup:
                            st.caption(":material/check_circle: **Markup applied** (editable vector shapes)")
                        else:
                            st.caption("Ready to add — click **Annotate / Add Shapes** to add callouts before saving.")
                        staged_supp_btns = st.container(horizontal=True)
                        if staged_supp_btns.button(
                            "Annotate / Add Shapes",
                            icon=":material/draw:",
                            key=f"btn_ann_staged_supp_up_{part['id']}",
                        ):
                            annotate_staged_part_image_dialog(staged_supp_upload_key)
                        if staged_supp_btns.button(
                            "Delete",
                            icon=":material/delete:",
                            key=f"destructive_discard_staged_supp_up_{part['id']}",
                        ):
                            st.session_state[f"parts_pending_discard_staged_supp_{part['id']}"] = True
                            st.rerun()

            if st.button("Add view", icon=":material/add_photo_alternate:", type="primary", key=f"btn_add_supp_file_{part['id']}"):
                has_staged_supp = isinstance(staged_supp_up, dict) and bool(staged_supp_up.get("composite_bytes"))
                if not has_staged_supp and not (extra is not None and is_extra_step):
                    st.error("Please upload a file or paste a screenshot from your clipboard first.")
                else:
                    try:
                        resolved_type = image_type
                        if has_staged_supp:
                            is_supp_clip = staged_supp_up.get("source") == "clipboard"
                            if is_supp_clip and image_type == "3D CAD Model (STEP)":
                                resolved_type = "Alternate CAD view"
                            has_supp_markup = _has_part_image_annotations(staged_supp_up.get("annotations_json"))
                            comp_filename = _composite_upload_filename(staged_supp_up["filename"], has_supp_markup)
                            comp_file = as_uploaded_file({"name": comp_filename, "bytes": staged_supp_up["composite_bytes"]})
                            add_part_image(
                                part["id"],
                                comp_file,
                                resolved_type,
                                caption,
                                original_file_bytes=staged_supp_up["original_bytes"],
                                original_filename=staged_supp_up["filename"],
                                annotations_json=str(staged_supp_up.get("annotations_json") or ""),
                            )
                            if staged_supp_up.get("source") == "upload":
                                st.session_state[discarded_supp_up_key] = staged_supp_up.get("source_hash")
                            st.session_state.pop(staged_supp_upload_key, None)
                            audit_meta = {
                                "part_id": str(part["id"]),
                                "part_number": str(part["part_number"]),
                                "supplemental_view_type_added": resolved_type,
                                "source": "clipboard" if is_supp_clip else "upload",
                                "filename": staged_supp_up["filename"],
                                "annotated": bool(has_supp_markup),
                            }
                        else:
                            if is_extra_step and image_type == "Exploded assembly":
                                resolved_type = "3D CAD Model (STEP)"
                            add_part_image(part["id"], extra, resolved_type, caption)
                            audit_meta = {
                                "part_id": str(part["id"]),
                                "part_number": str(part["part_number"]),
                                "supplemental_view_type_added": resolved_type,
                                "source": "upload",
                                "filename": extra.name,
                            }
                        st.session_state[f"_clear_supp_caption_{part['id']}"] = True
                        record_audit_event(
                            project_id,
                            "Parts",
                            "Add view",
                            1,
                            st.session_state.get("current_editor", ""),
                            audit_meta,
                        )
                        st.toast("Additional view added", icon=":material/check_circle:")
                        st.rerun()
                    except ValueError as ve:
                        st.error(str(ve))

        with supp_tab_url:
            extra_url = st.text_input(
                "Web link URL (SharePoint, Windchill drawing, CAD viewer link)",
                placeholder="https://...",
                key=f"supp_url_val_{part['id']}",
            )
            if st.button("Add web link", icon=":material/link:", type="primary", key=f"btn_add_supp_url_{part['id']}"):
                if not extra_url or not extra_url.strip().startswith(("http://", "https://")):
                    st.error("Please enter a valid URL starting with http:// or https://")
                else:
                    add_part_image_url(part["id"], extra_url.strip(), image_type, caption)
                    st.session_state[f"_clear_supp_caption_{part['id']}"] = True
                    record_audit_event(
                        project_id,
                        "Parts",
                        "Add view link",
                        1,
                        st.session_state.get("current_editor", ""),
                        {
                            "part_id": str(part["id"]),
                            "part_number": str(part["part_number"]),
                            "supplemental_view_type_added": image_type,
                            "url": extra_url.strip(),
                        },
                    )
                    st.toast("Additional view link added", icon=":material/check_circle:")
                    st.rerun()

with details_col.container(border=True):
    st.subheader(part["part_number"])
    st.write(part["description"] or "No part name")
    detail_cols = st.columns(2)
    detail_cols[0].metric("Design Maturity", part.get("design_maturity") or part.get("revision") or "—")
    detail_cols[1].metric("Source", part["source"])
    st.markdown(
        f"**Feature applicability:** "
        f"{assembly_grid_applicability_status(str(part['id']), part['model_applicability'])}"
    )
    col_meta1, col_meta2 = st.columns(2)
    with col_meta1:
        st.write("**Subsystem:**", part.get("subsystem") or "—")
        st.write("**Factory Nickname:**", part.get("factory_nickname") or part.get("official_windchill_part_name") or "—")
        st.write("**Design Engineer:**", part.get("design_engineer") or part.get("technology_engineer") or "—")
        st.write("**Part Code:**", part.get("part_code") or "—")
        st.write("**PPM:**", part.get("ppm") or "—")
    with col_meta2:
        raw_w = part.get("weight_lb")
        w_str = f"{float(raw_w):.2f} lb" if raw_w is not None and not pd.isna(raw_w) and str(raw_w).strip() != "" else "—"
        st.write("**Weight (lb):**", w_str)
        st.write("**Buyer / GCL:**", part.get("buyer_gcl") or "—")
        st.write("**PMQE / AQE:**", part.get("pmqe_aqe") or "—")
        st.write("**AME / Tooling:**", part.get("ame_tooling_engineer") or "—")
        st.write("**Source Code:**", part.get("source_code") or "—")
    if part["notes"]:
        st.write(part["notes"])

    raw_assembly_id = part.get("assembly_id")
    assembly_id = (
        ""
        if raw_assembly_id is None or pd.isna(raw_assembly_id)
        else str(raw_assembly_id).strip()
    )
    st.subheader("Mini-BOM")
    mini_bom = pits_assembly_mini_bom(
        project_id,
        part_id=str(part.get("id") or ""),
        part_number=str(part.get("part_number") or ""),
        pits_tracker_number=str(part.get("pits_tracker_number") or ""),
    )
    if not mini_bom.empty:
        st.caption(
            f"Indented PITS BOM tree ({len(mini_bom)} component{'s' if len(mini_bom) != 1 else ''}) "
            "contained within this assembly."
        )
        mini_bom_display = mini_bom[
            ["tree_part_number", "part_name", "quantity", "level", "tracker_number", "make_buy"]
        ].rename(
            columns={
                "tree_part_number": "Part number",
                "part_name": "Part name",
                "quantity": "Quantity",
                "level": "Level",
                "tracker_number": "PITS Tracker",
                "make_buy": "Make / Buy",
            }
        )
        st.dataframe(
            mini_bom_display,
            hide_index=True,
            width="stretch",
            column_config={
                "Part number": st.column_config.TextColumn(
                    "Part number", pinned=True
                ),
                "Part name": st.column_config.TextColumn("Part name"),
                "Quantity": st.column_config.NumberColumn(
                    "Quantity", format="%g"
                ),
                "Level": st.column_config.TextColumn("Level", width="small"),
                "PITS Tracker": st.column_config.TextColumn("PITS Tracker", width="small"),
                "Make / Buy": st.column_config.TextColumn("Make / Buy", width="small"),
            },
        )
    elif assembly_id:
        st.caption(
            "Read-only completed-subassembly structure."
        )
        legacy_bom = assembly_bom_components(project_id, assembly_id)
        if legacy_bom.empty:
            st.caption("No sub-components found for this assembly in PITS BOM.")
        else:
            mini_bom_view = legacy_bom[
                ["part_number", "part_name", "quantity", "use_description"]
            ].rename(
                columns={
                    "part_number": "Part number",
                    "part_name": "Part name",
                    "quantity": "Quantity",
                    "use_description": "Fishbone use",
                }
            )
            st.dataframe(
                mini_bom_view,
                hide_index=True,
                width="stretch",
                column_config={
                    "Part number": st.column_config.TextColumn(
                        "Part number", pinned=True
                    ),
                    "Part name": st.column_config.TextColumn("Part name"),
                    "Quantity": st.column_config.NumberColumn(
                        "Quantity", format="%g"
                    ),
                    "Fishbone use": st.column_config.TextColumn("Fishbone use"),
                },
            )
    else:
        st.caption("No sub-components found for this part in PITS BOM.")

render_parts_history()
