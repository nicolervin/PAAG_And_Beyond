from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

import pandas as pd
import streamlit as st


_EDITOR_INSTANCE_MARKER = "__editor_instance_"
_ORIG_DATA_EDITOR = getattr(st, "_paag_orig_data_editor", st.data_editor)
setattr(st, "_paag_orig_data_editor", _ORIG_DATA_EDITOR)


def filter_table(
    dataframe: pd.DataFrame,
    *,
    key: str,
    dropdown_columns: Iterable[str] = (),
    search_columns: Iterable[str] | None = None,
    labels: dict[str, str] | None = None,
    reset_widget_keys: Iterable[str] = (),
    multi_value_columns: Iterable[str] = (),
    universal_values: dict[str, Iterable[str]] | None = None,
    keyword_container=None,
) -> pd.DataFrame:
    """Render consistent keyword/dropdown controls and return the visible rows."""
    if dataframe.empty:
        return dataframe.reset_index(drop=True)
    labels = labels or {}
    multi_value_columns = set(multi_value_columns)
    universal_values = universal_values or {}
    valid_dropdowns = [column for column in dropdown_columns if column in dataframe.columns]
    controls = st.container(horizontal=True, vertical_alignment="bottom")
    keyword_host = keyword_container if keyword_container is not None else controls
    keyword = keyword_host.text_input(
        "Filter by keyword",
        key=f"{key}_keyword",
        placeholder="Search this table",
        icon=":material/search:",
    )
    selected: dict[str, list[object]] = {}
    for column in valid_dropdowns:
        if column in multi_value_columns:
            values = list(
                dict.fromkeys(
                    item
                    for value in dataframe[column]
                    for item in split_filter_values(value)
                    if item.casefold()
                    not in {str(marker).strip().casefold() for marker in universal_values.get(column, ())}
                )
            )
        else:
            values = dataframe[column].dropna().unique().tolist()
        values = sorted(values, key=lambda value: str(value).casefold())
        widget_key = f"{key}_{column}"
        stored_selection = st.session_state.get(widget_key, [])
        current_selection = stored_selection
        if current_selection is None:
            current_selection = []
        elif not isinstance(current_selection, (list, tuple, set)):
            current_selection = [current_selection]
        normalized_selection = [
            value for value in current_selection if value in values
        ]
        if not isinstance(stored_selection, list) or stored_selection != normalized_selection:
            st.session_state[widget_key] = normalized_selection
        selected[column] = controls.multiselect(
            labels.get(column, column.replace("_", " ").capitalize()),
            options=values,
            placeholder="All",
            key=widget_key,
        )

    visible = dataframe
    kw = keyword.strip()
    if kw and not visible.empty:
        columns = [column for column in (search_columns or visible.columns) if column in visible.columns]
        if columns:
            mask = pd.Series(False, index=visible.index, dtype=bool)
            for col in columns:
                mask = mask | visible[col].fillna("").astype(str).str.contains(
                    kw, case=False, regex=False, na=False
                )
            visible = visible.loc[mask]
    for column, values in selected.items():
        if values:
            if column in multi_value_columns:
                univ = universal_values.get(column, ())
                visible = visible.loc[
                    visible[column].apply(
                        lambda cell: any(
                            matches_filter_value(
                                cell,
                                value,
                                universal_values=univ,
                            )
                            for value in values
                        )
                    )
                ]
            else:
                visible = visible.loc[visible[column].isin(values)]
    row_identity = (
        tuple(visible["id"].fillna("").astype(str))
        if "id" in visible.columns
        else tuple(str(index) for index in visible.index)
    )
    signature_key = f"{key}_visible_rows"
    if st.session_state.get(signature_key) != row_identity:
        st.session_state[signature_key] = row_identity
        for widget_key in reset_widget_keys:
            logical_widget_key = logical_table_editor_key(widget_key)
            st.session_state.pop(f"_select_all_{logical_widget_key}", None)
            prior_widget_state = get_effective_table_editor_state(widget_key)
            st.session_state.pop(widget_key, None)
            if isinstance(prior_widget_state, dict) and (
                prior_widget_state.get("added_rows")
                or prior_widget_state.get("edited_rows")
                or prior_widget_state.get("deleted_rows")
            ):
                request_table_editor_reset(widget_key)
    st.caption(f"Showing {len(visible):,} of {len(dataframe):,} rows")
    return visible.copy().reset_index(drop=True)


def split_filter_values(value) -> list[str]:
    """Return normalized display values from a list or comma-separated table cell."""
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def matches_filter_value(
    cell_value,
    selected_value,
    *,
    universal_values: Iterable[str] = (),
) -> bool:
    """Match one selected value, while also retaining explicitly universal rows."""
    values = {value.casefold() for value in split_filter_values(cell_value)}
    universal = {str(value).strip().casefold() for value in universal_values}
    return str(selected_value).strip().casefold() in values or bool(values & universal) or (not values and "" in universal)


def merge_filtered_edits(
    full_dataframe: pd.DataFrame,
    filtered_dataframe: pd.DataFrame,
    edited_dataframe: pd.DataFrame,
    *,
    id_column: str = "id",
) -> pd.DataFrame:
    """Merge edited visible rows with untouched hidden rows, including visible deletions/additions."""
    if id_column not in full_dataframe.columns or id_column not in filtered_dataframe.columns:
        return edited_dataframe.copy()
    visible_ids = set(filtered_dataframe[id_column].dropna().astype(str))
    hidden = full_dataframe[~full_dataframe[id_column].fillna("").astype(str).isin(visible_ids)].copy()
    return pd.concat([hidden, edited_dataframe], ignore_index=True, sort=False)


def capture_id_keyed_editor_draft(
    previous_editor_rows: pd.DataFrame,
    editor_state: dict,
    draft_by_id: dict[str, dict] | None = None,
    captured_editor_state: dict[str, dict] | None = None,
    *,
    id_column: str = "id",
    ignored_columns: Iterable[str] = ("selected",),
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Capture new positional editor changes under stable persisted row IDs.

    Streamlit reports edited cells by visible row position. Persisting the
    resulting field patches by hidden ID prevents a filter or external sort
    from moving a row between the edit rerun and the later save rerun.
    """
    draft = deepcopy(draft_by_id or {})
    prior_state = captured_editor_state or {}
    current_state: dict[str, dict] = {}
    ignored = set(ignored_columns)
    for raw_position, raw_changes in (editor_state.get("edited_rows") or {}).items():
        try:
            position = int(raw_position)
        except (TypeError, ValueError):
            continue
        changes = {
            column: value
            for column, value in dict(raw_changes or {}).items()
            if column not in ignored
        }
        position_key = str(position)
        if changes:
            current_state[position_key] = deepcopy(changes)
        if not (0 <= position < len(previous_editor_rows)):
            continue
        stable_id = previous_editor_rows.iloc[position].get(id_column)
        if stable_id is None or pd.isna(stable_id) or not str(stable_id).strip():
            continue
        stable_id = str(stable_id).strip()
        prior_changes = prior_state.get(position_key, {}) or {}
        for column, value in changes.items():
            if column in prior_changes and prior_changes[column] == value:
                continue
            draft.setdefault(stable_id, {})[column] = deepcopy(value)
    for position_key, prior_changes in prior_state.items():
        if not prior_changes:
            continue
        try:
            position = int(position_key)
        except (TypeError, ValueError):
            continue
        if not (0 <= position < len(previous_editor_rows)):
            continue
        stable_id = previous_editor_rows.iloc[position].get(id_column)
        if stable_id is None or pd.isna(stable_id) or not str(stable_id).strip():
            continue
        stable_id = str(stable_id).strip()
        current_changes = current_state.get(position_key, {}) or {}
        row_draft = draft.get(stable_id)
        if not row_draft:
            continue
        for column in prior_changes:
            if column not in current_changes and column in row_draft:
                row_draft.pop(column, None)
        if not row_draft:
            draft.pop(stable_id, None)
    return draft, current_state


def apply_id_keyed_editor_draft(
    dataframe: pd.DataFrame,
    draft_by_id: dict[str, dict] | None,
    *,
    id_column: str = "id",
) -> pd.DataFrame:
    """Overlay stable-ID field patches without changing row order or visibility."""
    result = dataframe.copy()
    if result.empty or id_column not in result.columns or not draft_by_id:
        return result
    row_by_id = {
        str(value).strip(): index
        for index, value in result[id_column].items()
        if value is not None and not pd.isna(value) and str(value).strip()
    }
    for stable_id, changes in draft_by_id.items():
        row_index = row_by_id.get(str(stable_id).strip())
        if row_index is None:
            continue
        for column, value in (changes or {}).items():
            if column in result.columns and column != id_column:
                result.at[row_index, column] = value
    return result


def _empty_editor_state() -> dict[str, Any]:
    return {"edited_rows": {}, "added_rows": [], "deleted_rows": []}


def _normalize_editor_state(raw_state: object) -> dict[str, Any]:
    if not isinstance(raw_state, dict):
        return _empty_editor_state()
    edited_rows: dict[int, dict[str, Any]] = {}
    for raw_pos, raw_changes in (raw_state.get("edited_rows") or {}).items():
        if not isinstance(raw_changes, dict) or not raw_changes:
            continue
        try:
            pos = int(raw_pos)
        except (TypeError, ValueError):
            continue
        edited_rows[pos] = deepcopy(dict(raw_changes))
    added_rows = [
        deepcopy(dict(row))
        for row in (raw_state.get("added_rows") or [])
        if isinstance(row, dict) and row
    ]
    deleted_rows: list[int] = []
    for raw_pos in raw_state.get("deleted_rows") or []:
        try:
            deleted_rows.append(int(raw_pos))
        except (TypeError, ValueError):
            continue
    return {
        "edited_rows": edited_rows,
        "added_rows": added_rows,
        "deleted_rows": deleted_rows,
    }


def _editor_state_has_changes(state: dict[str, Any] | None) -> bool:
    if not isinstance(state, dict):
        return False
    return bool(
        state.get("edited_rows")
        or state.get("added_rows")
        or state.get("deleted_rows")
    )


def _resolve_editor_instance_key(key: str) -> str:
    """Resolve a logical or versioned editor key to its active session-state key."""
    key_str = str(key)
    if _EDITOR_INSTANCE_MARKER in key_str:
        if key_str in st.session_state:
            return key_str
        for existing_key in list(st.session_state.keys()):
            if str(existing_key).startswith(f"{key_str}_"):
                return str(existing_key)
        return key_str
    if key_str in st.session_state:
        return key_str
    generation_key = f"_table_editor_generation_{key_str}"
    generation = int(st.session_state.get(generation_key, 0) or 0)
    candidate = f"{key_str}{_EDITOR_INSTANCE_MARKER}{generation}"
    if candidate in st.session_state:
        return candidate
    for existing_key in list(st.session_state.keys()):
        if str(existing_key).startswith(f"{candidate}_"):
            return str(existing_key)
    if generation_key in st.session_state:
        return candidate
    return key_str


def _get_raw_editor_state(instance_key: str) -> dict[str, Any]:
    state_obj = st.session_state.get(instance_key)
    if not isinstance(state_obj, dict):
        return _empty_editor_state()
    mutated_id = st.session_state.get(f"_table_undo_mutated_obj_id_{instance_key}")
    if mutated_id is not None and id(state_obj) == mutated_id:
        last_raw = st.session_state.get(f"_table_undo_last_raw_{instance_key}")
        return _normalize_editor_state(last_raw)
    return _normalize_editor_state(state_obj)


def _combine_seed_and_raw_state(
    seed: dict[str, Any] | None,
    raw: dict[str, Any] | None,
    base_len: int | None = None,
) -> dict[str, Any]:
    norm_raw = _normalize_editor_state(raw)
    if not seed:
        return norm_raw
    norm_seed = _normalize_editor_state(seed)
    if not _editor_state_has_changes(norm_seed):
        return norm_raw

    combined_edited = deepcopy(norm_seed["edited_rows"])
    combined_added = deepcopy(norm_seed["added_rows"])
    combined_deleted = list(norm_seed["deleted_rows"])

    for pos, changes in norm_raw["edited_rows"].items():
        if base_len is not None and pos >= base_len:
            added_idx = pos - base_len
            if 0 <= added_idx < len(combined_added):
                combined_added[added_idx].update(deepcopy(changes))
            else:
                combined_edited.setdefault(pos, {}).update(deepcopy(changes))
        else:
            combined_edited.setdefault(pos, {}).update(deepcopy(changes))

    deleted_added_indices: set[int] = set()
    for pos in norm_raw["deleted_rows"]:
        if base_len is not None and pos >= base_len:
            added_idx = pos - base_len
            if 0 <= added_idx < len(combined_added):
                deleted_added_indices.add(added_idx)
        elif pos not in combined_deleted:
            combined_deleted.append(pos)
    if deleted_added_indices:
        combined_added = [
            row
            for idx, row in enumerate(combined_added)
            if idx not in deleted_added_indices
        ]

    combined_added.extend(deepcopy(norm_raw["added_rows"]))
    return {
        "edited_rows": combined_edited,
        "added_rows": combined_added,
        "deleted_rows": combined_deleted,
    }


def get_effective_table_editor_state(key: str) -> dict[str, Any]:
    """Return the active editor state, combining any undo seed with live edits."""
    logical_key = logical_table_editor_key(key)
    if st.session_state.get(f"_reset_table_editor_{logical_key}") and not st.session_state.get(
        f"_pending_undo_last_edit_{logical_key}"
    ):
        return _empty_editor_state()
    seed = st.session_state.get(f"_table_undo_seed_{logical_key}")
    if st.session_state.get(f"_pending_undo_last_edit_{logical_key}"):
        return _normalize_editor_state(seed)
    instance_key = _resolve_editor_instance_key(key)
    raw = _get_raw_editor_state(instance_key)
    base_len = st.session_state.get(f"_table_undo_base_len_{logical_key}")
    return _combine_seed_and_raw_state(
        seed,
        raw,
        int(base_len) if isinstance(base_len, int) else None,
    )


def _sync_table_undo_history(key: str) -> list[dict[str, Any]]:
    """Synchronize the per-table undo stack with the current effective editor state."""
    logical_key = logical_table_editor_key(key)
    history_key = f"_table_undo_history_{logical_key}"
    redo_key = f"_table_redo_history_{logical_key}"
    if st.session_state.get(f"_reset_table_editor_{logical_key}") and not st.session_state.get(
        f"_pending_undo_last_edit_{logical_key}"
    ):
        return [_empty_editor_state()]
    current = get_effective_table_editor_state(key)
    raw_history = st.session_state.get(history_key)
    if not isinstance(raw_history, list) or not raw_history:
        history: list[dict[str, Any]] = [_empty_editor_state()]
    else:
        history = [_normalize_editor_state(item) for item in raw_history]
        if _editor_state_has_changes(history[0]):
            history.insert(0, _empty_editor_state())

    if not _editor_state_has_changes(current):
        history = [_empty_editor_state()]
    elif current != history[-1]:
        history.append(deepcopy(current))
        st.session_state.pop(redo_key, None)
    st.session_state[history_key] = history
    return history


def can_undo_last_table_edit(
    key: str,
    *,
    ignored_columns: Iterable[str] = ("selected",),
    native_row_selection: bool = False,
) -> bool:
    """Return True when the table has at least one unsaved edit that can be stepped back."""
    logical_key = logical_table_editor_key(key)
    if st.session_state.get(f"_reset_table_editor_{logical_key}") and not st.session_state.get(
        f"_pending_undo_last_edit_{logical_key}"
    ):
        return False
    history = _sync_table_undo_history(key)
    if len(history) < 2:
        return False
    current = history[-1]
    if current.get("added_rows") or (
        current.get("deleted_rows") and not native_row_selection
    ):
        return True
    ignored = set(ignored_columns)
    return any(
        any(col not in ignored for col in changes)
        for changes in (current.get("edited_rows") or {}).values()
    )


_UNDO_ROW_ID_COLUMNS: tuple[str, ...] = (
    "part_number",
    "Part #",
    "model_number",
    "Model #",
    "unique_identifier",
    "code",
    "name",
    "feature_name",
    "option_name",
    "pitch_number",
    "station_number",
    "operation_number",
    "work_element",
    "step_description",
    "element_description",
    "requirement_type",
    "equipment_name",
    "type_name",
    "subject",
    "label",
    "description",
    "legacy_description",
)


def _format_toast_cell_val(val: Any) -> str:
    if val is None:
        return "blank"
    if isinstance(val, bool):
        return "Checked" if val else "Unchecked"
    if isinstance(val, (list, tuple)):
        cleaned = [str(x).strip() for x in val if str(x).strip()]
        if not cleaned:
            return "blank"
        joined = ", ".join(cleaned)
        return f"'{joined[:25]}...'" if len(joined) > 28 else f"'{joined}'"
    try:
        if pd.isna(val):
            return "blank"
    except Exception:
        pass
    s = str(val).strip()
    if not s:
        return "blank"
    if len(s) > 28:
        s = s[:25] + "..."
    return f"'{s}'"


def _capture_editor_undo_meta(
    logical_key: str,
    data: pd.DataFrame,
    column_config: dict[str, Any] | None,
) -> None:
    col_labels: dict[str, str] = {}
    cfg_map = column_config if isinstance(column_config, dict) else {}
    for raw_col in data.columns:
        col_str = str(raw_col)
        col_cfg = cfg_map.get(col_str) if col_str in cfg_map else cfg_map.get(raw_col)
        label: str | None = None
        if isinstance(col_cfg, dict):
            raw_lbl = col_cfg.get("label")
            if isinstance(raw_lbl, str) and raw_lbl.strip():
                label = raw_lbl.strip()
        elif isinstance(col_cfg, str) and col_cfg.strip():
            label = col_cfg.strip()
        elif col_cfg is not None:
            raw_lbl = getattr(col_cfg, "label", None)
            if isinstance(raw_lbl, str) and raw_lbl.strip():
                label = raw_lbl.strip()
        col_labels[col_str] = label or col_str.replace("_", " ").strip().title()

    id_cols = [col for col in _UNDO_ROW_ID_COLUMNS if col in data.columns]
    row_labels: dict[int, str] = {}
    base_rows: dict[int, dict[str, Any]] = {}
    capture_base = len(data) <= 2000
    for pos in range(len(data)):
        row = data.iloc[pos]
        if capture_base:
            base_rows[pos] = {str(col): row[col] for col in data.columns}
        row_ident = ""
        for id_col in id_cols:
            val = row[id_col]
            try:
                if val is None or pd.isna(val):
                    continue
            except Exception:
                if val is None:
                    continue
            val_str = str(val).strip()
            if val_str:
                row_ident = val_str[:32] + ("..." if len(val_str) > 32 else "")
                break
        row_labels[pos] = row_ident or f"Row {pos + 1}"

    st.session_state[f"_table_undo_meta_{logical_key}"] = {
        "col_labels": col_labels,
        "row_labels": row_labels,
        "base_rows": base_rows,
    }


def _describe_editor_state_transition(
    logical_key: str,
    from_state: dict[str, Any],
    to_state: dict[str, Any],
    *,
    action: str,
) -> str:
    meta = st.session_state.get(f"_table_undo_meta_{logical_key}")
    col_labels: dict[str, str] = (
        meta.get("col_labels", {}) if isinstance(meta, dict) else {}
    )
    row_labels: dict[int, str] = (
        meta.get("row_labels", {}) if isinstance(meta, dict) else {}
    )
    base_rows: dict[int, dict[str, Any]] = (
        meta.get("base_rows", {}) if isinstance(meta, dict) else {}
    )

    def _col_name(col: str) -> str:
        return col_labels.get(col) or str(col).replace("_", " ").strip().title()

    def _row_name(pos: int) -> str:
        return row_labels.get(pos) or f"Row {int(pos) + 1}"

    from_edited = (from_state or {}).get("edited_rows") or {}
    to_edited = (to_state or {}).get("edited_rows") or {}
    cell_diffs: list[tuple[int, str, Any, Any, bool, bool]] = []
    for pos in sorted(set(from_edited.keys()) | set(to_edited.keys())):
        f_row = from_edited.get(pos) or {}
        t_row = to_edited.get(pos) or {}
        base_row = base_rows.get(pos)
        has_base = isinstance(base_row, dict)
        for col in sorted(set(f_row.keys()) | set(t_row.keys())):
            if col == "selected":
                continue
            in_f = col in f_row
            in_t = col in t_row
            f_val = f_row[col] if in_f else (base_row.get(col) if has_base else None)
            t_val = t_row[col] if in_t else (base_row.get(col) if has_base else None)
            if in_f == in_t and f_val == t_val:
                continue
            cell_diffs.append(
                (int(pos), str(col), f_val, t_val, in_f or has_base, in_t or has_base)
            )

    if len(cell_diffs) == 1:
        pos, col, f_val, t_val, know_f, know_t = cell_diffs[0]
        c_lbl = _col_name(col)
        r_lbl = _row_name(pos)
        if know_f and know_t:
            return (
                f"{action} {c_lbl} on {r_lbl} "
                f"({_format_toast_cell_val(f_val)} → {_format_toast_cell_val(t_val)})"
            )
        if know_f:
            return f"{action} {c_lbl} edit on {r_lbl} ({_format_toast_cell_val(f_val)})"
        if know_t:
            return f"{action} {c_lbl} edit on {r_lbl} (→ {_format_toast_cell_val(t_val)})"
        return f"{action} {c_lbl} on {r_lbl}"
    if len(cell_diffs) > 1:
        pos, col, *_ = cell_diffs[0]
        return (
            f"{action} {len(cell_diffs)} cell edits "
            f"({_col_name(col)} on {_row_name(pos)}, ...)"
        )

    from_added = (from_state or {}).get("added_rows") or []
    to_added = (to_state or {}).get("added_rows") or []
    if len(from_added) != len(to_added):
        diff_count = abs(len(from_added) - len(to_added))
        if diff_count == 1:
            sample_row = (
                from_added[-1] if len(from_added) > len(to_added) else to_added[-1]
            )
            if isinstance(sample_row, dict):
                populated = [
                    f"{_col_name(str(k))}: {_format_toast_cell_val(v)}"
                    for k, v in sample_row.items()
                    if k != "selected" and _format_toast_cell_val(v) != "blank"
                ]
                if populated:
                    return f"{action} new row ({', '.join(populated[:2])})"
            return f"{action} new row"
        return f"{action} {diff_count} new rows"
    if from_added != to_added:
        for idx, (f_add, t_add) in enumerate(zip(from_added, to_added)):
            if f_add == t_add or not isinstance(f_add, dict) or not isinstance(t_add, dict):
                continue
            for col in sorted(set(f_add.keys()) | set(t_add.keys())):
                if col == "selected" or f_add.get(col) == t_add.get(col):
                    continue
                return (
                    f"{action} {_col_name(str(col))} on new row {idx + 1} "
                    f"({_format_toast_cell_val(f_add.get(col))} → {_format_toast_cell_val(t_add.get(col))})"
                )

    from_del = set((from_state or {}).get("deleted_rows") or [])
    to_del = set((to_state or {}).get("deleted_rows") or [])
    if from_del != to_del:
        diff_del = sorted(from_del ^ to_del)
        if len(diff_del) == 1:
            return f"{action} row deletion on {_row_name(diff_del[0])}"
        return f"{action} {len(diff_del)} row deletions"

    return (
        "Reverted the last cell edit."
        if action == "Reverted"
        else "Reapplied the last undone cell edit."
    )


def last_table_undo_redo_message(key: str, default: str = "") -> str:
    """Return the human-readable summary of the most recent Undo/Redo step for a table."""
    logical_key = logical_table_editor_key(key)
    msg = st.session_state.get(f"_table_last_undo_redo_msg_{logical_key}")
    if isinstance(msg, str) and msg.strip():
        return msg.strip()
    return default


def undo_last_table_edit(key: str) -> bool:
    """Step back one edit in the table's unsaved edit history and queue a remount."""
    logical_key = logical_table_editor_key(key)
    history = _sync_table_undo_history(key)
    if len(history) < 2:
        return False
    undone_state = history.pop()
    redo_key = f"_table_redo_history_{logical_key}"
    redo_stack = st.session_state.get(redo_key)
    if not isinstance(redo_stack, list):
        redo_stack = []
    else:
        redo_stack = [_normalize_editor_state(item) for item in redo_stack]
    redo_stack.append(deepcopy(undone_state))
    st.session_state[redo_key] = redo_stack
    target_state = deepcopy(history[-1])
    st.session_state[f"_table_last_undo_redo_msg_{logical_key}"] = (
        _describe_editor_state_transition(
            logical_key,
            undone_state,
            target_state,
            action="Reverted",
        )
    )
    st.session_state[f"_table_undo_history_{logical_key}"] = history
    if _editor_state_has_changes(target_state):
        st.session_state[f"_table_undo_seed_{logical_key}"] = deepcopy(target_state)
    else:
        st.session_state.pop(f"_table_undo_seed_{logical_key}", None)
    st.session_state[f"_pending_undo_last_edit_{logical_key}"] = True
    request_table_editor_reset(logical_key)
    return True


def can_redo_last_table_edit(
    key: str,
    *,
    ignored_columns: Iterable[str] = ("selected",),
    native_row_selection: bool = False,
) -> bool:
    """Return True when the table has at least one undone edit that can be reapplied."""
    logical_key = logical_table_editor_key(key)
    if st.session_state.get(f"_reset_table_editor_{logical_key}") and not st.session_state.get(
        f"_pending_undo_last_edit_{logical_key}"
    ):
        return False
    _sync_table_undo_history(key)
    redo_stack = st.session_state.get(f"_table_redo_history_{logical_key}")
    if not isinstance(redo_stack, list) or not redo_stack:
        return False
    candidate = _normalize_editor_state(redo_stack[-1])
    if candidate.get("added_rows") or (
        candidate.get("deleted_rows") and not native_row_selection
    ):
        return True
    ignored = set(ignored_columns)
    return any(
        any(col not in ignored for col in changes)
        for changes in (candidate.get("edited_rows") or {}).values()
    )


def redo_last_table_edit(key: str) -> bool:
    """Step forward one undone edit in the table's unsaved edit history and queue a remount."""
    logical_key = logical_table_editor_key(key)
    history = _sync_table_undo_history(key)
    redo_key = f"_table_redo_history_{logical_key}"
    redo_stack = st.session_state.get(redo_key)
    if not isinstance(redo_stack, list) or not redo_stack:
        return False
    redo_stack = [_normalize_editor_state(item) for item in redo_stack]
    prev_state = deepcopy(history[-1]) if history else _empty_editor_state()
    target_state = deepcopy(redo_stack.pop())
    if redo_stack:
        st.session_state[redo_key] = redo_stack
    else:
        st.session_state.pop(redo_key, None)
    st.session_state[f"_table_last_undo_redo_msg_{logical_key}"] = (
        _describe_editor_state_transition(
            logical_key,
            prev_state,
            target_state,
            action="Reapplied",
        )
    )
    history.append(deepcopy(target_state))
    st.session_state[f"_table_undo_history_{logical_key}"] = history
    if _editor_state_has_changes(target_state):
        st.session_state[f"_table_undo_seed_{logical_key}"] = deepcopy(target_state)
    else:
        st.session_state.pop(f"_table_undo_seed_{logical_key}", None)
    st.session_state[f"_pending_undo_last_edit_{logical_key}"] = True
    request_table_editor_reset(logical_key)
    return True


def was_table_editor_undo_reset(key: str) -> bool:
    """Return True during the rerun immediately following an undo_last_table_edit call."""
    logical_key = logical_table_editor_key(key)
    return bool(
        st.session_state.get(f"_just_undid_last_edit_{logical_key}")
        or st.session_state.get(f"_pending_undo_last_edit_{logical_key}")
    )


def _apply_seed_to_dataframe(
    dataframe: pd.DataFrame,
    seed: dict[str, Any],
) -> pd.DataFrame:
    display_df = dataframe.copy()
    edited_rows = seed.get("edited_rows") or {}
    added_rows = seed.get("added_rows") or []
    if not edited_rows and not added_rows:
        return display_df
    bool_cols = [
        col
        for col in display_df.columns
        if pd.api.types.is_bool_dtype(display_df[col].dtype)
    ]
    try:
        import pyarrow as pa
        from streamlit.elements.lib.column_types import determine_dataframe_schema
        from streamlit.elements.widgets.data_editor import (
            _apply_cell_edits,
            _apply_row_additions,
        )

        arrow_table = pa.Table.from_pandas(display_df)
        schema = determine_dataframe_schema(display_df, arrow_table.schema)
        if edited_rows:
            valid_edited = {
                int(pos): {
                    col: val
                    for col, val in changes.items()
                    if col in display_df.columns
                }
                for pos, changes in edited_rows.items()
                if 0 <= int(pos) < len(display_df) and isinstance(changes, dict)
            }
            if valid_edited:
                _apply_cell_edits(display_df, valid_edited, schema)
        if added_rows:
            valid_added = []
            for row in added_rows:
                if not isinstance(row, dict) or not row:
                    continue
                filtered_row = {
                    col: val
                    for col, val in row.items()
                    if col in display_df.columns
                }
                for bcol in bool_cols:
                    if filtered_row.get(bcol) is None:
                        filtered_row[bcol] = False
                valid_added.append(filtered_row)
            if valid_added:
                _apply_row_additions(display_df, valid_added, schema)
        return display_df
    except Exception:
        for raw_pos, changes in edited_rows.items():
            try:
                pos = int(raw_pos)
            except (TypeError, ValueError):
                continue
            if 0 <= pos < len(display_df) and isinstance(changes, dict):
                row_label = display_df.index[pos]
                for col, val in changes.items():
                    if col in display_df.columns:
                        display_df.at[row_label, col] = val
        for added_row in added_rows:
            if not isinstance(added_row, dict) or not added_row:
                continue
            next_idx = len(display_df)
            row_dict = {
                col: added_row.get(col, False if col in bool_cols else None)
                for col in display_df.columns
            }
            display_df.loc[next_idx] = row_dict
        return display_df


def _wrap_data_editor(data, *args, **kwargs):
    key = kwargs.get("key")
    if not key or not isinstance(data, pd.DataFrame):
        return _ORIG_DATA_EDITOR(data, *args, **kwargs)

    logical_key = logical_table_editor_key(str(key))
    base_len = len(data)
    st.session_state[f"_table_undo_base_len_{logical_key}"] = base_len
    _capture_editor_undo_meta(logical_key, data, kwargs.get("column_config"))
    seed = _normalize_editor_state(
        st.session_state.get(f"_table_undo_seed_{logical_key}")
    )
    has_seed = _editor_state_has_changes(seed)

    state_obj_before = st.session_state.get(key)
    if (
        isinstance(state_obj_before, dict)
        and st.session_state.get(f"_table_undo_mutated_obj_id_{key}") == id(state_obj_before)
    ):
        last_raw = _normalize_editor_state(
            st.session_state.get(f"_table_undo_last_raw_{key}")
        )
        dict.__setitem__(state_obj_before, "edited_rows", deepcopy(last_raw["edited_rows"]))
        dict.__setitem__(state_obj_before, "added_rows", deepcopy(last_raw["added_rows"]))
        dict.__setitem__(state_obj_before, "deleted_rows", deepcopy(last_raw["deleted_rows"]))

    display_df = _apply_seed_to_dataframe(data, seed) if has_seed else data
    raw_before = (
        _normalize_editor_state(state_obj_before)
        if isinstance(state_obj_before, dict)
        else _empty_editor_state()
    )
    has_raw_before = _editor_state_has_changes(raw_before)
    frozen_key = f"_table_editor_frozen_base_{key}"
    if not has_raw_before:
        st.session_state[frozen_key] = display_df.copy()
    else:
        frozen_df = st.session_state.get(frozen_key)
        if (
            isinstance(frozen_df, pd.DataFrame)
            and len(frozen_df) == len(display_df)
            and list(frozen_df.columns) == list(display_df.columns)
        ):
            display_df = frozen_df.copy()
        else:
            st.session_state[frozen_key] = display_df.copy()
    result_df = _ORIG_DATA_EDITOR(display_df, *args, **kwargs)

    state_obj = st.session_state.get(key)
    if isinstance(state_obj, dict):
        raw_snapshot = _normalize_editor_state(state_obj)
        st.session_state[f"_table_undo_last_raw_{key}"] = deepcopy(raw_snapshot)
        if has_seed:
            combined = _combine_seed_and_raw_state(seed, raw_snapshot, base_len)
            dict.__setitem__(state_obj, "edited_rows", deepcopy(combined["edited_rows"]))
            dict.__setitem__(state_obj, "added_rows", deepcopy(combined["added_rows"]))
            dict.__setitem__(state_obj, "deleted_rows", deepcopy(combined["deleted_rows"]))
            st.session_state[f"_table_undo_mutated_obj_id_{key}"] = id(state_obj)
        else:
            st.session_state.pop(f"_table_undo_mutated_obj_id_{key}", None)

    _sync_table_undo_history(str(key))
    st.session_state.pop(f"_just_undid_last_edit_{logical_key}", None)
    return result_df


st.data_editor = _wrap_data_editor


def has_unsaved_table_changes(key: str) -> bool:
    """Return whether a data editor currently contains pending cell or row changes."""
    logical_key = logical_table_editor_key(key)
    if st.session_state.get(f"_reset_table_editor_{logical_key}") and not st.session_state.get(
        f"_pending_undo_last_edit_{logical_key}"
    ):
        return False
    state = get_effective_table_editor_state(key)
    return bool(state.get("edited_rows") or state.get("added_rows") or state.get("deleted_rows"))


def logical_table_editor_key(key: str) -> str:
    """Return the stable logical key behind a versioned editor instance."""
    return str(key).split(_EDITOR_INSTANCE_MARKER, 1)[0]


def request_table_editor_reset(key: str) -> None:
    """Request a fresh keyed editor instance on the next Streamlit rerun."""
    logical_key = logical_table_editor_key(key)
    st.session_state[f"_reset_table_editor_{logical_key}"] = True


def reset_table_editor_selection(key: str, *, column: str = "selected") -> None:
    """Clear only selection-column edits on a data editor while preserving other unsaved cell edits."""
    logical_key = logical_table_editor_key(key)
    current = get_effective_table_editor_state(key)
    cleaned_edited: dict[str, dict] = {}
    for raw_pos, changes in (current.get("edited_rows") or {}).items():
        if not isinstance(changes, dict):
            continue
        filtered = {col: val for col, val in changes.items() if col != column}
        if filtered:
            cleaned_edited[str(raw_pos)] = deepcopy(filtered)
    cleaned_added: list[dict] = []
    for row in current.get("added_rows") or []:
        if not isinstance(row, dict):
            continue
        filtered_row = {col: val for col, val in row.items() if col != column}
        if filtered_row:
            cleaned_added.append(deepcopy(filtered_row))
    has_other_edits = bool(cleaned_edited or cleaned_added)
    if has_other_edits:
        st.session_state[f"_table_undo_seed_{logical_key}"] = {
            "edited_rows": cleaned_edited,
            "added_rows": cleaned_added,
            "deleted_rows": [],
        }
        st.session_state[f"_pending_undo_last_edit_{logical_key}"] = True
    else:
        st.session_state.pop(f"_table_undo_seed_{logical_key}", None)
        st.session_state.pop(f"_pending_undo_last_edit_{logical_key}", None)
    st.session_state[f"_preserve_select_all_{logical_key}"] = True
    request_table_editor_reset(logical_key)


def apply_pending_table_editor_reset(key: str) -> str:
    """Return the current editor-instance key, rotating it after a reset request.

    Removing Session State for a data editor does not reliably discard the
    browser's native ``deleted_rows`` state. A generation suffix changes widget
    identity and guarantees that Streamlit mounts the editor again from its
    supplied dataframe.
    """
    logical_key = logical_table_editor_key(key)
    generation_key = f"_table_editor_generation_{logical_key}"
    generation = int(st.session_state.get(generation_key, 0) or 0)
    if st.session_state.pop(f"_reset_table_editor_{logical_key}", False):
        preserve_select_all = bool(
            st.session_state.pop(f"_preserve_select_all_{logical_key}", False)
        )
        is_undo_reset = bool(
            st.session_state.pop(f"_pending_undo_last_edit_{logical_key}", False)
        )
        if not preserve_select_all and not is_undo_reset:
            st.session_state.pop(f"_select_all_{logical_key}", None)
        previous_key = f"{logical_key}{_EDITOR_INSTANCE_MARKER}{generation}"
        st.session_state.pop(previous_key, None)
        st.session_state.pop(f"_table_undo_mutated_obj_id_{previous_key}", None)
        st.session_state.pop(f"_table_undo_last_raw_{previous_key}", None)
        st.session_state.pop(f"_table_editor_frozen_base_{previous_key}", None)
        suffixed_keys = [
            existing_key
            for existing_key in list(st.session_state.keys())
            if str(existing_key).startswith(f"{previous_key}_")
        ]
        for suffixed_key in suffixed_keys:
            st.session_state.pop(suffixed_key, None)
            st.session_state.pop(f"_table_undo_mutated_obj_id_{suffixed_key}", None)
            st.session_state.pop(f"_table_undo_last_raw_{suffixed_key}", None)
            st.session_state.pop(f"_table_editor_frozen_base_{suffixed_key}", None)
        if is_undo_reset:
            st.session_state[f"_just_undid_last_edit_{logical_key}"] = True
        else:
            st.session_state.pop(f"_table_undo_history_{logical_key}", None)
            st.session_state.pop(f"_table_redo_history_{logical_key}", None)
            st.session_state.pop(f"_table_undo_seed_{logical_key}", None)
            st.session_state.pop(f"_just_undid_last_edit_{logical_key}", None)
        generation += 1
        st.session_state[generation_key] = generation
    return f"{logical_key}{_EDITOR_INSTANCE_MARKER}{generation}"
