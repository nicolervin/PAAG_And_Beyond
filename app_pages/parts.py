from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from utils.clipboard_image import as_uploaded_file, clipboard_image, decode_clipboard_image
from utils.store import (
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
    part_delete_impact,
    get_planning_scenario,
    part_feature_rules,
    part_images,
    part_scenario_activity,
    project_models,
    project_table,
    record_audit_event,
    save_table_view_preference,
    set_part_image,
    set_part_image_url,
    table_view_preference,
    update_part_feature_rules,
    update_part_rows,
)
from utils.scope_ui import page_title_with_scope
from utils.table_filters import (
    apply_id_keyed_editor_draft,
    apply_pending_table_editor_reset,
    capture_id_keyed_editor_draft,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
)
from utils.table_ui import (
    dataframe_to_excel,
    drop_untouched_new_rows,
    editable_table_footer,
    editable_table_heading,
    native_selected_rows,
    required_field_errors,
    selectable_dataframe,
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
DEFAULT_PARTS_COLUMN_ORDER = [
    "view_details", "active", "photo_status", "part_number", "description",
    "weight_lb", "subsystem", "design_maturity", "factory_nickname", "design_engineer",
    "ppm", "buyer_gcl", "pmqe_aqe", "ame_tooling_engineer", "part_code",
    "pits_tracker_number", "source_code", "make_buy", "feature_applicability",
    "applicability_status", "notes", "source", "updated_display",
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
    "source": "Source", "updated_display": "Updated",
}


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
parts_base_editor_key = apply_pending_table_editor_reset(
    f"parts_catalog_editor_v7_{scenario_id}"
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
current_mount_token = f"{project_id}_{scenario_id}_{editor_view_scope}"
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
        f"parts_catalog_editor_v7_{scenario_id}"
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

parts = project_table("parts", project_id, "part_number")
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
        str(row["model_number"]): (
            str(row["display_name"]).strip() or "Common name not defined"
        )
        for _, row in models.iterrows()
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
for _, feature in active_features.iterrows():
    for choice in json.loads(feature["allowed_values"] or "[]"):
        token = f"{feature['id']}::{choice}"
        feature_option_labels[token] = f"{feature['category']} · {feature['name']} = {choice}"
feature_token_by_label = {label: token for token, label in feature_option_labels.items()}
feature_options = list(feature_token_by_label)
rules_by_part: dict[str, list[str]] = {}
if not rules.empty:
    for part_id, part_rules in rules.groupby("part_id", sort=False):
        rules_by_part[str(part_id)] = [
            feature_option_labels.get(
                f"{row['feature_id']}::{row['value']}",
                f"{row['category']} · {row['feature_name']} = {row['value']}",
            )
            for _, row in part_rules.iterrows()
        ]


def readable_feature_applicability(part_id: str, legacy_value) -> str:
    selected = rules_by_part.get(str(part_id), [])
    if selected:
        return "; ".join(selected)
    if str(legacy_value or "").strip().casefold() in {"all", "all models"}:
        return "All models"
    return "Needs feature tagging"


editable_table_heading("All parts")
st.caption(
    "Edit catalog fields directly, then save. Select View details on a row to open its "
    "photos, full information, and completed-subassembly mini-BOM below."
)

with st.expander(
    "Saved table view — hide and move columns here",
    icon=":material/view_column:",
    expanded=True,
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
        "Save & Refresh below. Undo restores the last saved layout and discards unsaved "
        "part edits."
    )
if not selected_parts_columns:
    st.warning("Show at least one column before saving the table view.")
parts_column_order = selected_parts_columns or ["part_number"]
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
    "updated_at", "assembly_id", "assembly_number",
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
    "updated_at", "assembly_id", "assembly_number",
):
    parts_for_editing[col] = parts_for_editing[col].fillna("").astype("string")
linked_assembly_by_part = {
    str(row["id"]): str(row.get("assembly_number") or "")
    for _, row in parts_for_editing.iterrows()
    if str(row.get("assembly_id") or "").strip()
}


def assembly_grid_applicability_status(part_id: str, value) -> str:
    return readable_feature_applicability(part_id, value)
parts_for_editing["active"] = parts_for_editing["id"].apply(
    lambda part_id: activity_by_part.get(str(part_id), True)
).astype(bool)
parts_for_editing["feature_applicability"] = pd.Series(dtype="object") if parts_for_editing.empty else parts_for_editing.apply(
    lambda row: (
        rules_by_part.get(str(row["id"]), [])
        or (["All models"] if str(row["model_applicability"] or "").strip().casefold() in {"all", "all models"} else [])
    ),
    axis=1,
)
parts_for_editing["applicability_status"] = pd.Series(dtype="string") if parts_for_editing.empty else parts_for_editing.apply(
    lambda row: assembly_grid_applicability_status(
        str(row["id"]), row["model_applicability"]
    ),
    axis=1,
)
parts_for_editing["source_code"] = parts_for_editing["source_code"].apply(
    lambda value: ""
    if value is None or pd.isna(value)
    else str(int(value))
    if isinstance(value, float) and value.is_integer()
    else str(value).strip()
).astype("string")
parts_for_editing["view_details"] = pd.Series(
    [":material/visibility: View details"] * len(parts_for_editing),
    index=parts_for_editing.index,
    dtype="string",
)
parts_for_editing["photo_status"] = parts_for_editing["image_path"].apply(
    lambda value: "✅ Added" if str(value or "").strip() else "❌ Missing"
)
updated_values = pd.to_datetime(parts_for_editing["updated_at"], errors="coerce", utc=True)
parts_for_editing["updated_display"] = updated_values.dt.strftime(
    "%b %d, %Y %H:%M"
).fillna("")


for col in ("applicability_status", "photo_status", "updated_display"):
    parts_for_editing[col] = parts_for_editing[col].fillna("").astype("string")


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
        "updated_at": "",
        "assembly_id": "",
        "assembly_number": "",
        "active": is_active,
        "feature_applicability": feature_list,
        "applicability_status": "; ".join(feature_list),
        "view_details": ":material/visibility: View details",
        "photo_status": "❌ Missing",
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
            existing_draft_rows.append(draft_row)
            harvested_any = True
    if harvested_any:
        st.session_state[parts_draft_added_key] = existing_draft_rows
    return harvested_any


def merge_parts_editor_draft(source: pd.DataFrame) -> pd.DataFrame:
    """Capture positional edits by part ID and overlay the complete pending draft."""
    last_editor_key = st.session_state.get(parts_draft_last_editor_key) or parts_editor_key
    state = st.session_state.get(last_editor_key, {}) or {}
    if last_editor_key != parts_editor_key:
        harvest_added_rows_into_draft(state.get("added_rows"))
        st.session_state.pop(last_editor_key, None)
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
    st.session_state[parts_draft_state_key] = captured_state
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
        st.session_state["part_catalog_filters_keyword"] = filter_kw
        # Clear conflicting dropdown filters so the part is guaranteed visible
        for filter_column in [
            "active", "photo_status", "part_number", "description", "subsystem", "design_maturity", "revision",
            "factory_nickname", "design_engineer", "ppm", "buyer_gcl",
            "pmqe_aqe", "ame_tooling_engineer", "part_code", "source_code",
            "make_buy", "pits_tracker_number", "feature_applicability", "notes", "source", "updated_at",
        ]:
            st.session_state.pop(f"part_catalog_filters_{filter_column}", None)
        st.session_state["parts_scroll_to_details"] = True

    try:
        if "part_id" in st.query_params:
            del st.query_params["part_id"]
        if "part_number" in st.query_params:
            del st.query_params["part_number"]
    except Exception:
        pass

with st.expander("Filter columns", icon=":material/filter_list:", expanded=True):
    pre_filter_added_rows = deepcopy(
        (st.session_state.get(parts_editor_key, {}) or {}).get("added_rows", [])
    )
    parts_for_editing = filter_table(
        parts_for_editing,
        key="part_catalog_filters",
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
    )
    if parts_editor_key not in st.session_state and pre_filter_added_rows:
        if harvest_added_rows_into_draft(pre_filter_added_rows):
            st.rerun()
    clear_filter_actions = st.container(horizontal=True, horizontal_alignment="right")
    if clear_filter_actions.button(
        "Clear filters",
        icon=":material/filter_alt_off:",
        key="clear_part_catalog_filters",
    ):
        if harvest_added_rows_into_draft(pre_filter_added_rows):
            st.session_state.pop(parts_editor_key, None)
        st.session_state.pop("part_catalog_filters_keyword", None)
        for filter_column in [
            "active", "photo_status", "part_number", "description", "subsystem", "design_maturity", "revision",
            "factory_nickname", "design_engineer", "ppm", "buyer_gcl",
            "pmqe_aqe", "ame_tooling_engineer", "part_code", "source_code",
            "make_buy", "pits_tracker_number", "feature_applicability", "notes", "source", "updated_at",
        ]:
            st.session_state.pop(f"part_catalog_filters_{filter_column}", None)
        st.rerun()


candidate_sort_columns = [
    "active", "photo_status", "part_number", "description", "weight_lb",
    "subsystem", "design_maturity",
    "factory_nickname", "design_engineer", "ppm", "buyer_gcl",
    "pmqe_aqe", "ame_tooling_engineer", "part_code", "pits_tracker_number",
    "source_code", "make_buy", "feature_applicability",
    "applicability_status", "notes", "source", "updated_at",
]
parts_editor_rows = direct_entry_editor_rows(
    parts_for_editing,
    editor_key=parts_editor_key,
    sort_columns=[
        col for col in candidate_sort_columns if col in parts_column_order
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
        "applicability_status": "Applicability status", "updated_at": "Updated",
    },
    additional_unsaved_changes=has_parts_draft,
)
# Let the mounted editor retain ordinary cell changes without replacing its
# data source on every edit rerun. Reapply the stable-ID draft only after
# another control has remounted the editor, such as a filter or view change.
current_editor_state = st.session_state.get(parts_editor_key, {}) or {}
if not (
    current_editor_state.get("edited_rows")
    or current_editor_state.get("added_rows")
    or current_editor_state.get("deleted_rows")
):
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
    *[col for col in parts_column_order if col != "id" and col in parts_editor_rows.columns],
]
parts_editor_display_rows = parts_editor_rows.reindex(columns=visible_editor_columns)


def open_part_details() -> None:
    click = st.session_state.get("parts_view_details")
    target_rows = globals().get("parts_editor_display_rows")
    if target_rows is None:
        target_rows = parts_for_editing
    if click and 0 <= click["row"] < len(target_rows):
        st.session_state[selected_part_key] = str(target_rows.iloc[click["row"]]["id"])
        st.session_state["parts_scroll_to_details"] = True


parts_action_slot = st.empty()
edited_parts = st.data_editor(
    parts_editor_display_rows,
    key=parts_editor_key,
    hide_index=True,
    num_rows="dynamic",
    height=430,
    disabled=[
        col for col in [
            "id", "subsystem", "part_code", "model_applicability", "photo_status",
            "applicability_status", "source", "image_path", "updated_at",
            "updated_display", "assembly_id", "assembly_number",
        ]
        if col in visible_editor_columns
    ],
    column_order=parts_column_order,
    column_config={
        "id": None,
        "official_windchill_part_name": None,
        "technology_engineer": None,
        "assembly_id": None,
        "assembly_number": None,
        "view_details": standard_details_column_config(on_click=open_part_details, key="parts_view_details"),
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
        "part_number": st.column_config.TextColumn("Part number", required=True),
        "description": st.column_config.TextColumn("Part Name", width="large"),
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
            help="Read-only subsystem identifier from column F of the imported PITS Tracker row matched by PITS ID.",
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
        "part_code": st.column_config.TextColumn(
            "Part Code",
            help=(
                "Part Code from PITS Tracker column N.\n\n"
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
st.caption(
    "Type or paste new parts directly into the blank entry row, then save. Use View details to manage its Primary CAD image "
    "and additional views."
)

export_columns = [
    "active", "part_number", "description", "subsystem", "design_maturity", "factory_nickname",
    "design_engineer", "ppm", "buyer_gcl", "pmqe_aqe",
    "ame_tooling_engineer", "part_code", "pits_tracker_number",
    "source_code", "make_buy", "feature_applicability",
    "photo_status", "notes", "source", "updated_at",
]
export_dataframe = parts_for_editing.reindex(columns=export_columns)
export_hash = _hash_filtered_export(export_dataframe)
st.download_button(
    "Export filtered rows",
    data=_cached_parts_dataframe_to_excel(export_hash, export_dataframe, "Parts"),
    file_name="parts_filtered.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    icon=":material/download:",
)

selected_saved_parts = native_selected_rows(parts_editor_display_rows, editor_key=parts_editor_key)
if not selected_saved_parts.empty:
    selected_saved_parts = selected_saved_parts.loc[
        ~selected_saved_parts["id"].astype(str).str.startswith("__draft_new__")
    ].copy()
bulk_controls = selected_rows_action_bar(
    parent=parts_action_slot,
)
bulk_applicability = bulk_controls.multiselect(
    "Feature applicability for selected parts",
    options=feature_options,
    placeholder="Choose All models or feature values",
    key="parts_bulk_feature_applicability",
)
apply_bulk_applicability = bulk_controls.button(
    f"Apply to selected ({len(selected_saved_parts)})",
    type="primary",
    icon=":material/checklist:",
    disabled=selected_saved_parts.empty,
)
request_delete_bulk_parts = not selected_saved_parts.empty

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
            request_table_editor_reset(parts_editor_key)
            st.toast(f"Updated feature applicability for {len(selected_saved_parts)} parts", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

if request_delete_bulk_parts:
    if has_parts_draft or table_has_unsaved_changes(
        parts_editor_key, native_row_selection=True
    ):
        st.warning("Save or undo other table edits before deleting selected parts.")
    else:
        st.session_state.parts_pending_bulk_delete = selected_saved_parts["id"].astype(str).tolist()
        stage_native_delete_confirmation(parts_editor_key)


@st.dialog("Delete selected parts?", dismissible=False)
def confirm_bulk_part_delete() -> None:
    pending_ids = st.session_state.get("parts_pending_bulk_delete", [])
    try:
        impact = part_delete_impact(project_id, pending_ids)
    except ValueError as exc:
        st.error(str(exc))
        return
    st.warning(
        f"This will permanently delete {len(pending_ids)} part(s), their photos, and their fishbone uses."
    )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_bulk_part_delete"):
        st.session_state.pop("parts_pending_bulk_delete", None)
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
        st.session_state.pop("parts_pending_bulk_delete", None)
        request_table_editor_reset(parts_editor_key)
        st.toast(f"Deleted {len(deleted_labels)} selected parts and their fishbone uses", icon=":material/delete:")
        st.rerun()


if st.session_state.get("parts_pending_bulk_delete"):
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
            columns=["view_details", "active", "photo_status", "feature_applicability", "applicability_status", "updated_display", "assembly_id", "assembly_number"]
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
            "scenario_id": scenario_id,
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
            f"Saved {count} parts and the table view",
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
            selectable_dataframe(
                history.drop(columns=["details"], errors="ignore"),
                key=f"parts_history_table_{project_id}",
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
image_col, details_col = st.columns([2, 3])
with image_col.container(border=True):
    st.subheader("Primary CAD image")
    raw_img = str(part.get("image_path") or "").strip()
    is_url = raw_img.startswith(("http://", "https://"))
    if is_url:
        lower_url = raw_img.lower()
        if any(lower_url.endswith(ext) or (ext + "?") in lower_url for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"]):
            st.image(raw_img, caption=part["part_number"])
        c_link1, c_link2 = st.columns([3, 1])
        with c_link1:
            st.link_button("Open CAD / Web Link", raw_img, icon=":material/open_in_new:")
        with c_link2:
            if st.button("Remove", icon=":material/delete:", key=f"del_prim_url_{part['id']}", help="Remove this CAD web link"):
                clear_part_image(part["id"])
                record_audit_event(
                    project_id,
                    "Parts",
                    "Remove CAD image link",
                    1,
                    st.session_state.get("current_editor", ""),
                    {"part_id": str(part["id"]), "part_number": str(part["part_number"])},
                )
                st.rerun()
    elif raw_img:
        image_path = Path(raw_img)
        if image_path.exists():
            st.image(str(image_path), caption=part["part_number"])
            if st.button("Remove image", icon=":material/delete:", key=f"del_prim_img_{part['id']}"):
                clear_part_image(part["id"])
                record_audit_event(
                    project_id,
                    "Parts",
                    "Remove CAD image",
                    1,
                    st.session_state.get("current_editor", ""),
                    {"part_id": str(part["id"]), "part_number": str(part["part_number"])},
                )
                st.rerun()
        else:
            st.caption("No image attached.")
    else:
        st.caption("No image or web link attached.")

    tab_upload, tab_url, tab_paste = st.tabs(["Upload File", "Web Link / URL", "Paste Screenshot"])

    with tab_upload:
        uploaded = st.file_uploader("Attach screenshot or rendered view", type=["png", "jpg", "jpeg", "webp"], key=f"image_{part['id']}")
        if uploaded and st.button("Save image", type="primary", icon=":material/upload:", key=f"btn_save_img_{part['id']}"):
            set_part_image(part["id"], uploaded)
            record_audit_event(
                project_id,
                "Parts",
                "Save image",
                1,
                st.session_state.get("current_editor", ""),
                {
                    "part_id": str(part["id"]),
                    "part_number": str(part["part_number"]),
                    "primary_cad_image_replaced_via": "upload",
                },
            )
            st.toast("Image attached", icon=":material/check_circle:")
            st.rerun()

    with tab_url:
        cad_url = st.text_input(
            "Attach CAD / PLM / Web Link",
            value=raw_img if is_url else "",
            placeholder="https://windchill... or https://sharepoint...",
            key=f"url_cad_{part['id']}",
            help="Enter a web URL for this part's 3D CAD model, Windchill drawing, or online specification.",
        )
        if st.button("Save CAD Link", type="primary", icon=":material/link:", key=f"btn_save_cad_url_{part['id']}"):
            if not cad_url or not cad_url.strip().startswith(("http://", "https://")):
                st.error("Please enter a valid URL starting with http:// or https://")
            else:
                set_part_image_url(part["id"], cad_url.strip())
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
                    },
                )
                st.toast("CAD web link attached", icon=":material/check_circle:")
                st.rerun()

    with tab_paste:
        st.caption(
            "Press Win+Shift+S, select a region, and paste it here. "
            "It saves immediately as the Primary CAD image."
        )
        primary_clipboard_key = f"clipboard_primary_{part['id']}"
        primary_pending_key = f"pending_primary_{part['id']}"
        st.session_state.pop(primary_pending_key, None)
        pasted = clipboard_image(key=primary_clipboard_key)
        pasted_payload = getattr(pasted, "image", None)
        if pasted_payload:
            try:
                primary_image = decode_clipboard_image(pasted_payload)
                set_part_image(part["id"], as_uploaded_file(primary_image))
                record_audit_event(
                    project_id,
                    "Parts",
                    "Paste Primary CAD image",
                    1,
                    st.session_state.get("current_editor", ""),
                    {"part_id": str(part["id"])},
                )
                st.toast(
                    "Screenshot saved as the Primary CAD image",
                    icon=":material/check_circle:",
                )
                st.rerun()
            except (OSError, ValueError) as exc:
                st.error(str(exc))

    st.subheader("Additional views")
    images = part_images(part["id"])
    for supplemental in images:
        supp_raw = str(supplemental.get("image_path") or "").strip()
        supp_caption = supplemental.get("caption") or supplemental.get("image_type") or "Additional View"
        supp_id = supplemental.get("id")
        with st.container(border=True):
            s_c1, s_c2 = st.columns([4, 1])
            with s_c1:
                if supp_raw.startswith(("http://", "https://")):
                    lower_supp = supp_raw.lower()
                    if any(lower_supp.endswith(ext) or (ext + "?") in lower_supp for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"]):
                        st.image(supp_raw, caption=supp_caption)
                    st.link_button(f":material/open_in_new: {supp_caption}", supp_raw)
                    st.caption(f"Type: `{supplemental.get('image_type')}` | URL: {supp_raw}")
                else:
                    supplemental_path = Path(supp_raw)
                    if supplemental_path.exists():
                        supp_suffix = supplemental_path.suffix.lower()
                        if supp_suffix in {".step", ".stp"}:
                            size_mb = supplemental_path.stat().st_size / (1024 * 1024)
                            st.markdown(f":material/view_in_ar: **3D CAD Model (STEP)** — `{supplemental_path.name}` ({size_mb:.1f} MB)")
                            if supp_caption and supp_caption != "3D CAD Model (STEP)":
                                st.caption(supp_caption)
                            st.download_button(
                                "Download STEP file",
                                data=supplemental_path.read_bytes(),
                                file_name=f"{part['part_number']}_{supplemental_path.name}",
                                mime="application/step",
                                icon=":material/download:",
                                key=f"dl_supp_{supp_id}",
                            )
                        else:
                            st.image(str(supplemental_path), caption=supp_caption)
                    st.caption(f"Type: `{supplemental.get('image_type')}`")
            with s_c2:
                if st.button("Delete", icon=":material/delete:", key=f"del_supp_{supp_id}"):
                    delete_part_image(supp_id)
                    record_audit_event(
                        project_id,
                        "Parts",
                        "Delete view",
                        1,
                        st.session_state.get("current_editor", ""),
                        {
                            "part_id": str(part["id"]),
                            "part_number": str(part["part_number"]),
                            "image_id": str(supp_id),
                        },
                    )
                    st.toast("View removed", icon=":material/check_circle:")
                    st.rerun()

    with st.expander("Add an exploded view, 3D CAD model, drawing, or web link", icon=":material/add_photo_alternate:"):
        source_mode = st.radio(
            "Source",
            ["Upload file (Image or 3D STEP)", "Web link / URL"],
            horizontal=True,
            key=f"supp_source_mode_{part['id']}",
        )
        view_types = [
            "3D CAD Model (STEP)",
            "Exploded assembly",
            "Alternate CAD view",
            "CAD / Drawing Link",
            "SharePoint Document",
            "Prototype photo",
            "Quality detail",
            "Other",
        ]
        image_type = st.selectbox("View type", view_types, key=f"supp_type_{part['id']}")
        caption = st.text_input("Caption / Notes", key=f"supp_caption_{part['id']}")

        if source_mode == "Upload file (Image or 3D STEP)":
            extra = st.file_uploader(
                "Upload image file or 3D CAD STEP file",
                type=["png", "jpg", "jpeg", "webp", "step", "stp"],
                key=f"supp_file_{part['id']}",
                help="Images: max 10 MB (PNG, JPG, WEBP) • 3D CAD: max 50 MB (STEP, STP)",
            )
            st.caption("Images: max **10 MB** (PNG, JPG, WEBP) • 3D CAD: max **50 MB** (STEP, STP)")
            if st.button("Add file view", icon=":material/upload:", type="primary", key=f"btn_add_supp_file_{part['id']}"):
                if not extra:
                    st.error("Choose a file first.")
                else:
                    try:
                        resolved_type = image_type
                        if extra.name.lower().endswith((".step", ".stp")) and image_type == "Exploded assembly":
                            resolved_type = "3D CAD Model (STEP)"
                        add_part_image(part["id"], extra, resolved_type, caption)
                        record_audit_event(
                            project_id,
                            "Parts",
                            "Add view",
                            1,
                            st.session_state.get("current_editor", ""),
                            {
                                "part_id": str(part["id"]),
                                "part_number": str(part["part_number"]),
                                "supplemental_view_type_added": resolved_type,
                                "filename": extra.name,
                            },
                        )
                        st.toast("Additional view added", icon=":material/check_circle:")
                        st.rerun()
                    except ValueError as ve:
                        st.error(str(ve))
        else:
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
