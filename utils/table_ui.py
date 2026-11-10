from __future__ import annotations

import colorsys
import hashlib
import math
from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
from typing import Iterable, NoReturn, Sequence

import pandas as pd
import streamlit as st

from utils.cache_store import get_last_write_metadata, get_write_epoch
from utils.table_filters import (
    can_redo_last_table_edit,
    can_undo_last_table_edit,
    get_effective_table_editor_state,
    last_table_undo_redo_message,
    logical_table_editor_key,
    redo_last_table_edit,
    request_table_editor_reset,
    reset_table_editor_selection,
    undo_last_table_edit,
)


DEFAULT_SELECTION_COLUMN = "selected"
_TABLE_UI_REV_20261102 = 4
DECIMAL_COMPARISON_PLACES = 9

_UNSAVED_SOURCES_KEY = "_active_unsaved_sources"
_PENDING_UNSAVED_NAV_KEY = "_pending_unsaved_nav"
_UNSAVED_NAV_ACTION_KEY = "_unsaved_nav_action"
_UNSAVED_NAV_EXECUTING_KEY = "_executing_unsaved_nav_action"
_UNSAVED_NAV_AFTER_ACTION_KEY = "_unsaved_nav_after_action"
_UNSAVED_NAV_TRIGGERED_KEY = "_unsaved_nav_triggered_sources"


def _rounded_decimal(value, *, decimal_places: int = DECIMAL_COMPARISON_PLACES) -> float | None:
    """Normalize a scalar number for clean display and tolerant comparisons."""
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return round(number, decimal_places) if math.isfinite(number) else number


def format_clean_number(value, *, decimal_places: int = DECIMAL_COMPARISON_PLACES) -> str:
    """Display whole and decimal quantities without trailing zeroes or scientific notation."""
    number = _rounded_decimal(value, decimal_places=decimal_places)
    if number is None:
        return ""
    if math.isfinite(number):
        formatted = f"{number:.{decimal_places}f}".rstrip("0").rstrip(".")
        return formatted if formatted and formatted != "-0" else "0"
    return f"{number:g}"


def part_number_cell_style(value) -> str:
    """Return a stable, contrast-safe cell style for one real part number."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    part_number = str(value).strip()
    if not part_number:
        return ""
    digest = hashlib.sha256(part_number.encode("utf-8")).digest()
    hue = int.from_bytes(digest[:2], "big") / 65535
    red, green, blue = colorsys.hls_to_rgb(hue, 0.84, 0.55)
    background = "#{:02X}{:02X}{:02X}".format(
        round(red * 255), round(green * 255), round(blue * 255)
    )
    return f"background-color: {background}; color: #17212B; font-weight: 600"


def decimal_values_equal(
    left, right, *, decimal_places: int = DECIMAL_COMPARISON_PLACES
) -> bool:
    """Compare editor-backed numbers after suppressing insignificant float noise."""
    return _rounded_decimal(left, decimal_places=decimal_places) == _rounded_decimal(
        right, decimal_places=decimal_places
    )


def _is_audit_history_dataframe(data: object, key: str) -> bool:
    """Return True when a DataFrame represents an audit history table."""
    if not isinstance(data, pd.DataFrame):
        return False
    cols = set(data.columns)
    if "create_new_rows" in cols or "edit_existing_rows" in cols:
        return True
    if (
        "action" in cols
        and ("editor_name" in cols or "actor" in cols)
        and ("created_at" in cols or "timestamp" in cols)
    ):
        return True
    return "history" in str(key or "").lower() and "action" in cols


def selectable_dataframe(data, *, key: str, **kwargs):
    """Render a read-only table with native multi-row selection and select-all."""
    skip_history_wrapper = bool(kwargs.pop("_from_audit_history_table", False))
    if not skip_history_wrapper and _is_audit_history_dataframe(data, key):
        return render_audit_history_table(data, key=key, **kwargs)
    active_sel_keys = list(st.session_state.get("_active_selectable_df_keys") or [])
    if key and key not in active_sel_keys:
        active_sel_keys.append(str(key))
        st.session_state["_active_selectable_df_keys"] = active_sel_keys
    saved_sel_key = f"_saved_selectable_df_{key}" if key else ""
    if key and key not in st.session_state and saved_sel_key in st.session_state:
        saved_sel = st.session_state.get(saved_sel_key)
        if isinstance(saved_sel, dict) and isinstance(saved_sel.get("selection"), dict):
            st.session_state[key] = deepcopy(saved_sel)
    kwargs.setdefault("on_select", "rerun")
    kwargs.setdefault("selection_mode", "multi-row")
    event = st.dataframe(data, key=key, **kwargs)
    if key:
        try:
            sel_obj = getattr(event, "selection", None) or (
                event.get("selection") if isinstance(event, dict) else None
            )
            if sel_obj is not None:
                raw_rows = getattr(sel_obj, "rows", None)
                if raw_rows is None and isinstance(sel_obj, dict):
                    raw_rows = sel_obj.get("rows")
                raw_cols = getattr(sel_obj, "columns", None)
                if raw_cols is None and isinstance(sel_obj, dict):
                    raw_cols = sel_obj.get("columns")
                raw_cells = getattr(sel_obj, "cells", None)
                if raw_cells is None and isinstance(sel_obj, dict):
                    raw_cells = sel_obj.get("cells")
                st.session_state[saved_sel_key] = {
                    "selection": {
                        "rows": list(raw_rows or []),
                        "columns": list(raw_cols or []),
                        "cells": list(raw_cells or []),
                    }
                }
        except Exception:
            pass
    if key and st.config.get_option("global.appTest"):
        try:
            from streamlit.runtime.scriptrunner_utils.script_run_context import (
                get_script_run_ctx,
            )

            ctx = get_script_run_ctx(suppress_warning=True)
            if ctx is not None:
                ctx.session_state._state._old_state[str(key)] = dict(event)
        except Exception:
            pass
    return event


def _audit_cell_values_equal(left: object, right: object) -> bool:
    """Compare two cell values for audit change detection across editor types."""
    left_empty = left is None or (isinstance(left, float) and math.isnan(left)) or (not isinstance(left, (list, dict, tuple, set)) and pd.isna(left))
    right_empty = right is None or (isinstance(right, float) and math.isnan(right)) or (not isinstance(right, (list, dict, tuple, set)) and pd.isna(right))
    if left_empty and right_empty:
        return True
    if isinstance(left, str) and left.strip() == "" and right_empty:
        return True
    if isinstance(right, str) and right.strip() == "" and left_empty:
        return True
    if left_empty or right_empty:
        return False
    if isinstance(left, bool) or isinstance(right, bool):
        return bool(left) == bool(right)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return decimal_values_equal(left, right)
    return str(left).strip() == str(right).strip()


def _normalize_audit_row_id(raw_id: object) -> str | None:
    """Normalize a table row ID (UUID string or positive int) for audit diffing."""
    if raw_id is None or (not isinstance(raw_id, (list, dict, tuple, set)) and pd.isna(raw_id)):
        return None
    text = str(raw_id).strip()
    if not text or text.lower() in {"none", "nan", "<na>", "null"}:
        return None
    try:
        numeric = float(text)
        if numeric <= 0:
            return None
        if numeric.is_integer():
            return str(int(numeric))
    except (TypeError, ValueError):
        pass
    return text


def count_table_create_and_edit_rows(
    original_df: pd.DataFrame | None,
    edited_df: pd.DataFrame | Sequence[dict[str, object]] | None,
    *,
    id_column: str = "id",
    compare_columns: Iterable[str] | None = None,
    ignore_columns: Iterable[str] = ("selected", "updated_at", "created_at"),
    non_empty_columns: Iterable[str] | None = None,
) -> tuple[int, int]:
    """Count (created_count, updated_count) between an original DataFrame and edited rows."""
    if edited_df is None:
        return 0, 0
    edited = edited_df if isinstance(edited_df, pd.DataFrame) else pd.DataFrame(list(edited_df))
    if edited.empty:
        return 0, 0
    ignored = {str(col) for col in ignore_columns} | {id_column}
    orig_by_id: dict[str, pd.Series] = {}
    if original_df is not None and not original_df.empty and id_column in original_df.columns:
        for _, orig_row in original_df.iterrows():
            rid = _normalize_audit_row_id(orig_row.get(id_column))
            if rid is not None:
                orig_by_id[rid] = orig_row

    if compare_columns is not None:
        compare_cols = [str(col) for col in compare_columns if str(col) in edited.columns and str(col) not in ignored]
    else:
        compare_cols = [col for col in edited.columns if col not in ignored]
    check_non_empty = list(non_empty_columns) if non_empty_columns is not None else compare_cols

    created_count = 0
    updated_count = 0
    for _, row in edited.iterrows():
        has_content = False
        for col in check_non_empty:
            if col not in row.index:
                continue
            val = row.get(col)
            if val is None or (not isinstance(val, (list, dict, tuple, set)) and pd.isna(val)):
                continue
            if isinstance(val, bool):
                if val:
                    has_content = True
                    break
                continue
            if isinstance(val, (list, tuple, set, dict)):
                if len(val) > 0:
                    has_content = True
                    break
                continue
            if str(val).strip() != "":
                has_content = True
                break
        if not has_content and non_empty_columns is not None:
            continue

        raw_id = row.get(id_column) if id_column in row.index else None
        row_id = _normalize_audit_row_id(raw_id)

        if row_id is None or row_id not in orig_by_id:
            if has_content or non_empty_columns is None:
                created_count += 1
        else:
            orig_row = orig_by_id[row_id]
            changed = any(
                col in orig_row.index and not _audit_cell_values_equal(row.get(col), orig_row.get(col))
                for col in compare_cols
            )
            if changed:
                updated_count += 1
    return created_count, updated_count


def render_audit_history_table(
    history_df: pd.DataFrame | None,
    *,
    key: str,
    leading_columns: Sequence[tuple[str, str]] = (),
    action_column: str = "action",
    action_label: str = "Action",
    count_column: str = "row_count",
    count_label: str = "Rows",
    actor_column: str = "editor_name",
    actor_label: str = "Editor",
    time_column: str = "created_at",
    time_label: str = "When",
    empty_caption: str | None = None,
    height: int | None = None,
    hide_index: bool = True,
    column_config: dict[str, object] | None = None,
    **kwargs,
):
    """Render a section's audit history table with an expandable Create New / Edit Existing toggle."""
    if history_df is None or history_df.empty:
        if empty_caption:
            st.caption(empty_caption)
        return None

    from utils.db_core import AUDIT_HISTORY_EXPANSION_COLUMNS, enrich_audit_history_dataframe

    working_df = history_df.copy()
    if not all(col in working_df.columns for col in AUDIT_HISTORY_EXPANSION_COLUMNS):
        working_df = enrich_audit_history_dataframe(working_df)

    caller_cfg = dict(column_config) if isinstance(column_config, dict) else {}

    resolved_leading: list[tuple[str, str]] = list(leading_columns)
    if not resolved_leading:
        for cand_col, default_lbl in (
            ("workflow", "Workflow"),
            ("table_name", "Workflow"),
            ("Section", "Section"),
        ):
            if cand_col in working_df.columns:
                lbl = caller_cfg.get(cand_col)
                resolved_leading.append(
                    (cand_col, lbl if isinstance(lbl, str) and lbl else default_lbl)
                )
                break

    if actor_column not in working_df.columns:
        for fallback_actor in ("editor_name", "actor", "Editor"):
            if fallback_actor in working_df.columns:
                actor_column = fallback_actor
                break

    if isinstance(caller_cfg.get(action_column), str):
        action_label = str(caller_cfg[action_column])
    if isinstance(caller_cfg.get(count_column), str):
        count_label = str(caller_cfg[count_column])
    if isinstance(caller_cfg.get(actor_column), str):
        actor_label = str(caller_cfg[actor_column])

    expanded_state_key = f"_audit_history_expanded_{key}"
    is_expanded = bool(st.session_state.get(expanded_state_key, False))

    _, toggle_col = st.columns([5.8, 2.2])
    with toggle_col:
        toggle_label = (
            ":material/unfold_less: Hide Create / Edit Details"
            if is_expanded
            else ":material/unfold_more: Create New / Edit Existing"
        )
        if st.button(
            toggle_label,
            key=f"{key}_toggle_expand",
            width="stretch",
            help="Show or hide the Create New and Edit Existing user and timestamp columns.",
        ):
            is_expanded = not is_expanded
            st.session_state[expanded_state_key] = is_expanded

    selected_columns: list[str] = []
    resolved_column_config: dict[str, object] = {}

    for src_col, label in resolved_leading:
        if src_col in working_df.columns:
            selected_columns.append(src_col)
            resolved_column_config[src_col] = caller_cfg.get(src_col) or label

    time_col_cfg = caller_cfg.get(time_column) or st.column_config.DatetimeColumn(
        time_label, format="MMM DD, YYYY HH:mm", timezone="America/New_York"
    )
    base_columns = [
        (action_column, caller_cfg.get(action_column) or action_label),
        (count_column, caller_cfg.get(count_column) or count_label),
        (actor_column, caller_cfg.get(actor_column) or actor_label),
        (time_column, time_col_cfg),
    ]
    for src_col, col_cfg in base_columns:
        if src_col in working_df.columns:
            selected_columns.append(src_col)
            resolved_column_config[src_col] = col_cfg

    if is_expanded:
        expansion_specs = [
            ("create_new_rows", "Create New (Rows)"),
            ("create_new_user", "Create New (User)"),
            ("create_new_at", "Create New (When)"),
            ("edit_existing_rows", "Edit Existing (Rows)"),
            ("edit_existing_user", "Edit Existing (User)"),
            ("edit_existing_at", "Edit Existing (When)"),
        ]
        for src_col, label in expansion_specs:
            if src_col not in working_df.columns:
                working_df[src_col] = ""
            selected_columns.append(src_col)
            resolved_column_config[src_col] = st.column_config.TextColumn(label)

    dataframe_kwargs: dict[str, object] = dict(kwargs)
    dataframe_kwargs["hide_index"] = hide_index
    dataframe_kwargs["column_config"] = resolved_column_config
    if height is not None:
        dataframe_kwargs["height"] = height

    return selectable_dataframe(
        working_df[selected_columns],
        key=key,
        _from_audit_history_table=True,
        **dataframe_kwargs,
    )


def selected_dataframe_rows(
    source_dataframe: pd.DataFrame,
    selection_event: object,
    *,
    id_column: str = "id",
) -> pd.DataFrame:
    """Resolve a read-only dataframe selection event to persisted source rows."""
    if id_column not in source_dataframe:
        return source_dataframe.iloc[0:0].copy()
    selection = getattr(selection_event, "selection", None)
    if selection is None and isinstance(selection_event, dict):
        selection = selection_event.get("selection")
    positions = getattr(selection, "rows", None)
    if positions is None and isinstance(selection, dict):
        positions = selection.get("rows")

    normalized_positions: list[int] = []
    for raw_position in positions or []:
        try:
            position = int(raw_position)
        except (TypeError, ValueError):
            continue
        if 0 <= position < len(source_dataframe) and position not in normalized_positions:
            normalized_positions.append(position)
    if not normalized_positions:
        return source_dataframe.iloc[0:0].copy()

    selected = source_dataframe.iloc[normalized_positions].copy()
    return selected.loc[
        selected[id_column].notna() & selected[id_column].astype(str).str.strip().ne("")
    ].copy()


def direct_entry_editor_rows(
    dataframe: pd.DataFrame,
    *,
    editor_key: str,
    sort_columns: Iterable[str] | None = None,
    labels: dict[str, str] | None = None,
    additional_unsaved_changes: bool = False,
    default_sort_column: str = "",
    default_sort_descending: bool = False,
) -> pd.DataFrame:
    """Sort saved rows before a direct-entry, multi-row-paste editor renders.

    Streamlit disables native header sorting when an editor permits row
    creation. These external controls preserve sorting without inserting an
    extra Add row step. Controls lock while the editor has draft changes or
    native row selections so row positions cannot shift underneath the draft.
    """
    labels = labels or {}
    requested_columns = list(sort_columns or dataframe.columns)
    candidates: list[str] = []
    for column in requested_columns:
        if column not in dataframe.columns:
            continue
        candidates.append(column)
    if not candidates:
        return dataframe.reset_index(drop=True)

    sort_scope = logical_table_editor_key(editor_key)
    sort_key = f"{sort_scope}_external_sort_column"
    sort_key = f"{sort_scope}_external_sort_column"
    direction_key = f"{sort_scope}_external_sort_direction"
    saved_sort_key = f"_saved_sort_col_{sort_scope}"
    saved_dir_key = f"_saved_sort_dir_{sort_scope}"
    if sort_key not in st.session_state and saved_sort_key in st.session_state:
        st.session_state[sort_key] = st.session_state.get(saved_sort_key)
    if direction_key not in st.session_state and saved_dir_key in st.session_state:
        st.session_state[direction_key] = bool(st.session_state.get(saved_dir_key))
    valid_options = ["", *candidates]
    if st.session_state.get(sort_key) not in valid_options:
        st.session_state[sort_key] = (
            default_sort_column if default_sort_column in valid_options else ""
        )
    if not isinstance(st.session_state.get(direction_key), bool):
        st.session_state[direction_key] = bool(default_sort_descending)
    editor_state = get_effective_table_editor_state(editor_key)
    controls_locked = bool(
        editor_state.get("edited_rows")
        or editor_state.get("added_rows")
        or editor_state.get("deleted_rows")
        or bool(st.session_state.get(f"_select_all_{sort_scope}", False))
        or additional_unsaved_changes
    )
    controls = st.container(horizontal=True, vertical_alignment="bottom")
    sort_column = controls.selectbox(
        "Sort rows by",
        options=valid_options,
        format_func=lambda column: (
            "Saved order"
            if not column
            else labels.get(column, column.replace("_", " ").capitalize())
        ),
        key=sort_key,
        disabled=controls_locked,
        help="Choose the saved-row order before editing or pasting new rows.",
        width=240,
    )
    descending = controls.toggle(
        "Descending",
        key=direction_key,
        disabled=controls_locked or not sort_column,
        help="Turn on to reverse the selected sort order.",
    )
    st.session_state[saved_sort_key] = sort_column
    st.session_state[saved_dir_key] = bool(descending)
    if True:
        controls.caption(
            "Save, undo, or clear selected rows before changing the sort."
            if controls_locked
            else "Choose the saved-row order before editing or pasting new rows."
        )
    if not sort_column:
        return dataframe.reset_index(drop=True)
    sort_values = dataframe[sort_column]
    if any(
        isinstance(value, (list, tuple, set, dict))
        for value in sort_values.dropna().tolist()
    ):
        comparable = sort_values.map(
            lambda value: " | ".join(str(item) for item in value)
            if isinstance(value, (list, tuple, set))
            else ("" if value is None else str(value))
        )
        comparable = comparable.mask(comparable.astype(str).str.strip().eq(""), pd.NA)
        positions = comparable.sort_values(
            ascending=not bool(descending), na_position="last", kind="stable"
        ).index
        return dataframe.loc[positions].reset_index(drop=True)
    if pd.api.types.is_string_dtype(sort_values.dtype) or sort_values.dtype == object:
        comparable = sort_values.map(
            lambda value: pd.NA
            if value is None or (isinstance(value, str) and not value.strip()) or pd.isna(value)
            else str(value)
        )
        positions = comparable.sort_values(
            ascending=not bool(descending), na_position="last", kind="stable"
        ).index
        return dataframe.loc[positions].reset_index(drop=True)
    return dataframe.sort_values(
        by=sort_column,
        ascending=not bool(descending),
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)


def drop_untouched_new_rows(
    dataframe: pd.DataFrame,
    *,
    identifying_columns: Iterable[str],
    id_column: str = "id",
) -> pd.DataFrame:
    """Remove any untouched new-record rows returned by a dynamic editor."""

    def is_blank(value: object) -> bool:
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

    def series_is_blank(series: pd.Series) -> pd.Series:
        if series.empty:
            return pd.Series(dtype=bool, index=series.index)
        if series.dtype == object:
            non_null = series.dropna()
            if non_null.empty:
                return pd.Series(True, index=series.index, dtype=bool)
            if not any(isinstance(v, (list, tuple, set, dict)) for v in non_null.tolist()):
                return (series.isna() | series.astype(str).str.strip().eq("")).astype(bool)
            return pd.Series([is_blank(v) for v in series.tolist()], index=series.index, dtype=bool)
        if pd.api.types.is_string_dtype(series.dtype) or pd.api.types.is_numeric_dtype(series.dtype):
            return (series.isna() | series.astype(str).str.strip().eq("")).astype(bool)
        return pd.Series([is_blank(v) for v in series.tolist()], index=series.index, dtype=bool)

    identifying_columns = [
        column for column in identifying_columns if column in dataframe.columns
    ]
    if not identifying_columns:
        return dataframe.reset_index(drop=True)
    if id_column in dataframe.columns:
        new_record = (
            series_is_blank(dataframe[id_column])
            | dataframe[id_column].astype(str).str.strip().str.startswith("__draft_new__")
        ).astype(bool)
    else:
        new_record = pd.Series(True, index=dataframe.index, dtype=bool)
    untouched = new_record.copy()
    for column in identifying_columns:
        if not untouched.any():
            break
        untouched = untouched & series_is_blank(dataframe[column])
    return dataframe.loc[~untouched].copy()


@dataclass(frozen=True)
class TableHeaderActions:
    """Actions returned by the standard editable-table footer."""

    save_and_refresh: bool
    undo: bool
    additional_action: bool = False
    secondary_action: bool = False
    delete_action: bool = False


def table_has_unsaved_changes(
    editor_key: str,
    *,
    ignored_columns: Iterable[str] = (DEFAULT_SELECTION_COLUMN,),
    native_row_selection: bool = False,
) -> bool:
    """Detect persisted data edits while ignoring action-only table columns."""
    logical_key = logical_table_editor_key(editor_key)
    if (
        st.session_state.get(f"_reset_table_editor_{logical_key}")
        and not st.session_state.get(f"_pending_undo_last_edit_{logical_key}")
        and not st.session_state.get(f"_preserve_filter_draft_{logical_key}")
    ):
        return False
    state = get_effective_table_editor_state(editor_key)
    if state.get("added_rows") or (state.get("deleted_rows") and not native_row_selection):
        return True
    ignored = set(ignored_columns)
    if any(
        any(column not in ignored for column in changes)
        for changes in (state.get("edited_rows") or {}).values()
    ):
        return True
    filter_draft = st.session_state.get(f"_table_filter_id_draft_{logical_key}")
    return bool(
        isinstance(filter_draft, dict)
        and any(
            isinstance(changes, dict) and any(column not in ignored for column in changes)
            for changes in filter_draft.values()
        )
    )


def prepare_editor_selection_column(
    dataframe: pd.DataFrame,
    *,
    editor_key: str,
    column: str = DEFAULT_SELECTION_COLUMN,
    id_column: str = "id",
) -> pd.DataFrame:
    """Populate a boolean row-selection column, respecting active Select All state."""
    prepared = dataframe.copy()
    logical_key = logical_table_editor_key(editor_key)
    select_all = bool(st.session_state.get(f"_select_all_{logical_key}", False))
    if select_all and not prepared.empty:
        if id_column in prepared.columns:
            ids = prepared[id_column].fillna("").astype(str).str.strip()
            selectable = ids.ne("") & ~ids.str.startswith("__draft_new__")
            prepared[column] = selectable.astype(bool)
        else:
            prepared[column] = pd.Series(True, index=prepared.index, dtype="bool")
    elif column not in prepared.columns:
        prepared[column] = pd.Series(False, index=prepared.index, dtype="bool")
    else:
        prepared[column] = prepared[column].fillna(False).astype(bool)
    return prepared


def resolve_editor_selected_rows(
    source_dataframe: pd.DataFrame,
    edited_dataframe: pd.DataFrame | None = None,
    *,
    editor_key: str,
    column: str = DEFAULT_SELECTION_COLUMN,
    id_column: str = "id",
    prior_editor_state: dict | None = None,
    include_draft_new: bool = False,
) -> pd.DataFrame:
    """Resolve rows selected via the Select checkbox column or native row selection."""
    if source_dataframe.empty:
        return source_dataframe.iloc[0:0].copy()

    logical_key = logical_table_editor_key(editor_key)
    select_all_default = bool(st.session_state.get(f"_select_all_{logical_key}", False))

    state = get_effective_table_editor_state(editor_key)
    edited_rows = state.get("edited_rows", {}) or {}
    prior_edited_rows = (
        (prior_editor_state.get("edited_rows", {}) or {})
        if isinstance(prior_editor_state, dict)
        else {}
    )
    deleted_positions = {
        int(pos)
        for pos in (state.get("deleted_rows") or [])
        if str(pos).lstrip("-").isdigit() and 0 <= int(pos) < len(source_dataframe)
    }

    selected_positions: list[int] = []
    for pos in range(len(source_dataframe)):
        if id_column in source_dataframe.columns:
            raw_id = source_dataframe.iloc[pos].get(id_column)
            stable_id = (
                ""
                if raw_id is None or pd.isna(raw_id)
                else str(raw_id).strip()
            )
            if not stable_id:
                continue
            if not include_draft_new and stable_id.startswith("__draft_new__"):
                continue

        is_selected: bool | None = None
        if (
            edited_dataframe is not None
            and column in edited_dataframe.columns
            and pos < len(edited_dataframe)
        ):
            val = edited_dataframe.iloc[pos].get(column)
            if val is not None and not pd.isna(val):
                is_selected = bool(val)

        changes = edited_rows.get(pos, edited_rows.get(str(pos), {})) or {}
        if column in changes:
            is_selected = bool(changes[column])
        elif is_selected is None:
            prior_changes = (
                prior_edited_rows.get(pos, prior_edited_rows.get(str(pos), {})) or {}
            )
            if column in prior_changes:
                is_selected = bool(prior_changes[column])

        if is_selected is None:
            if select_all_default:
                if id_column in source_dataframe.columns:
                    raw_id = source_dataframe.iloc[pos].get(id_column)
                    sid = (
                        ""
                        if raw_id is None or pd.isna(raw_id)
                        else str(raw_id).strip()
                    )
                    is_selected = bool(sid and not sid.startswith("__draft_new__"))
                else:
                    is_selected = True
            elif column in source_dataframe.columns:
                val = source_dataframe.iloc[pos].get(column)
                is_selected = (
                    bool(val) if val is not None and not pd.isna(val) else False
                )
            else:
                is_selected = False

        if pos in deleted_positions:
            is_selected = True

        if is_selected:
            selected_positions.append(pos)

    if not selected_positions:
        return source_dataframe.iloc[0:0].copy()

    base_df = (
        edited_dataframe
        if (
            edited_dataframe is not None
            and len(edited_dataframe) == len(source_dataframe)
        )
        else source_dataframe
    )
    selected = base_df.iloc[selected_positions].copy()
    for pos in selected_positions:
        row_index = base_df.index[pos]
        prior_changes = (
            prior_edited_rows.get(pos, prior_edited_rows.get(str(pos), {})) or {}
        )
        for col, val in prior_changes.items():
            if col in selected.columns:
                selected.loc[row_index, col] = val
        changes = edited_rows.get(pos, edited_rows.get(str(pos), {})) or {}
        for col, val in changes.items():
            if col in selected.columns:
                selected.loc[row_index, col] = val
    return selected


def render_select_all_control(
    host,
    *,
    editor_key: str,
    selectable_count: int,
    selected_count: int,
    key_prefix: str,
    column: str = DEFAULT_SELECTION_COLUMN,
    always_show_both: bool = False,
) -> None:
    """Render Select all / Clear selection buttons inside a bulk action bar."""
    logical_key = logical_table_editor_key(editor_key)
    select_all_active = bool(st.session_state.get(f"_select_all_{logical_key}", False))
    all_selected = selectable_count > 0 and selected_count >= selectable_count
    if always_show_both or not all_selected:
        if host.button(
            "Select all",
            icon=":material/select_all:",
            disabled=selectable_count <= 0 or all_selected,
            key=f"{key_prefix}_select_all",
            help="Select all visible saved rows in this table.",
        ):
            st.session_state[f"_select_all_{logical_key}"] = True
            reset_table_editor_selection(editor_key, column=column)
            st.rerun()
    if always_show_both or selected_count > 0:
        if host.button(
            "Clear selection",
            icon=":material/deselect:",
            disabled=selected_count <= 0 and not select_all_active,
            key=f"{key_prefix}_clear_selection",
            help="Uncheck all selected rows in this table.",
        ):
            st.session_state.pop(f"_select_all_{logical_key}", None)
            reset_table_editor_selection(editor_key, column=column)
            st.rerun()


def native_selected_rows(
    source_dataframe: pd.DataFrame,
    *,
    editor_key: str,
    id_column: str = "id",
) -> pd.DataFrame:
    """Return rows chosen with the data editor's native corner/row selectors."""
    if id_column not in source_dataframe:
        return source_dataframe.iloc[0:0].copy()
    state = get_effective_table_editor_state(editor_key)
    positions = [
        int(position) for position in state.get("deleted_rows", [])
        if 0 <= int(position) < len(source_dataframe)
    ]
    if not positions:
        return source_dataframe.iloc[0:0].copy()
    selected = source_dataframe.iloc[positions].copy()
    edited_rows = state.get("edited_rows", {}) or {}
    for position in positions:
        changes = edited_rows.get(position, edited_rows.get(str(position), {})) or {}
        for column, value in changes.items():
            if column in selected.columns:
                selected.loc[source_dataframe.index[position], column] = value
    return selected.loc[
        selected[id_column].notna() & selected[id_column].astype(str).str.strip().ne("")
    ].copy()


def stage_native_delete_confirmation(editor_key: str) -> NoReturn:
    """Restore native-deleted rows before showing their confirmation dialog.

    Streamlit applies its native Delete row(s) action to the editor before
    Python receives the resulting ``deleted_rows`` state. Call this only after
    the page has copied those rows into durable pending-confirmation state.
    The immediate full rerun rebuilds the editor from saved data, so no row
    disappears from the table until the confirmed storage write succeeds.
    """
    request_table_editor_reset(editor_key)
    st.rerun()


def dataframe_to_excel(dataframe: pd.DataFrame, sheet_name: str = "Filtered rows") -> bytes:
    """Create an in-memory Excel export for the currently visible table rows."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    return output.getvalue()


def required_field_errors(dataframe: pd.DataFrame, required_fields: dict[str, str]) -> list[str]:
    """Return consistent validation messages for blank required cells."""
    errors: list[str] = []
    for column, label in required_fields.items():
        if column not in dataframe:
            errors.append(f"{label} is missing from the table.")
            continue
        blank = dataframe[column].isna() | dataframe[column].astype(str).str.strip().eq("")
        if blank.any():
            errors.append(f"{label} is required in {int(blank.sum())} row(s).")
    return errors


def standard_details_column_config(
    *,
    on_click,
    key: str,
    pinned: bool = False,
    width: str | int | None = "small",
):
    """Return the standard row Details action."""
    return st.column_config.ButtonColumn(
        "Details",
        type="tertiary",
        on_click=on_click,
        key=key,
        pinned=pinned,
        width=width,
        help="Open this row's full information and editing controls.",
    )


def selected_rows_action_bar(
    *,
    parent=None,
    gap: str | None = "small",
):
    """Return an uncluttered, right-aligned row for selected-table actions."""
    host = parent if parent is not None else st
    return host.container(
        horizontal=True,
        vertical_alignment="center",
        horizontal_alignment="right",
        gap=gap,
    )


def stable_id_from_button_click(
    source_dataframe: pd.DataFrame,
    click_state,
    *,
    id_column: str = "id",
) -> str:
    """Resolve a ButtonColumn click through its rendered row to a hidden stable ID."""
    if not click_state:
        return ""
    try:
        row_index = int(click_state.get("row", -1))
    except (AttributeError, TypeError, ValueError):
        return ""
    if (
        row_index < 0
        or row_index >= len(source_dataframe)
        or id_column not in source_dataframe
    ):
        return ""
    stable_id = source_dataframe.iloc[row_index].get(id_column)
    if stable_id is None or pd.isna(stable_id):
        return ""
    return str(stable_id).strip()


def editable_table_heading(title: str) -> None:
    """Render the section heading above an editable table and its filters."""
    st.subheader(title)


def _source_item_has_unsaved(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("additional_unsaved"):
        return True
    editor_key = str(item.get("editor_key") or "")
    if editor_key and table_has_unsaved_changes(
        editor_key,
        native_row_selection=bool(item.get("native_row_selection", False)),
    ):
        return True
    return False


def has_active_unsaved_changes() -> bool:
    """Return True if any active editor or draft on the current view has unsaved changes."""
    sources = st.session_state.get(_UNSAVED_SOURCES_KEY) or []
    if any(_source_item_has_unsaved(item) for item in sources):
        return True
    for s_key in list(st.session_state.keys()):
        key_str = str(s_key)
        if key_str.startswith("yamazumi_board_draft_"):
            val = st.session_state.get(s_key)
            if isinstance(val, dict) and bool(val):
                return True
        elif key_str.startswith("fishbone_canvas_draft_"):
            val = st.session_state.get(s_key)
            if isinstance(val, dict) and any(
                bool(val.get(k))
                for k in (
                    "positions",
                    "connections",
                    "deleted_connections",
                    "connection_nodes",
                    "new_assignments",
                    "updated_assignments",
                    "deleted_assignments",
                    "variant_links",
                )
            ):
                return True
        elif (
            key_str.startswith("yamazumi_edit_element_target_")
            or key_str.startswith("yamazumi_edit_pitch_target_")
            or key_str.startswith("process_edit_line_dialog_")
            or key_str.startswith("_draft_modified_")
            or key_str.startswith("layout_shapes_has_unsaved_")
            or key_str.startswith("_pending_save_conflict_")
            or key_str.startswith("_inline_conflict_")
            or key_str.startswith("edit_element_conflict_")
            or key_str.startswith("ergo_annotate_active_")
            or key_str.startswith("_annotator_open_")
        ):
            if st.session_state.get(s_key):
                return True
    return False


def has_active_table_selections_or_edits() -> bool:
    """Return True if the user has unsaved edits or active row selections in any table on the page."""
    if has_active_unsaved_changes():
        return True
    sources = st.session_state.get(_UNSAVED_SOURCES_KEY) or []
    for item in sources:
        if not isinstance(item, dict):
            continue
        editor_key = str(item.get("editor_key") or "")
        if not editor_key:
            continue
        logical_key = logical_table_editor_key(editor_key)
        if st.session_state.get(f"_select_all_{logical_key}", False):
            return True
        state = get_effective_table_editor_state(editor_key)
        if state.get("edited_rows") or state.get("added_rows") or state.get("deleted_rows"):
            return True
    for sel_key in list(st.session_state.get("_active_selectable_df_keys") or []):
        sel_state = st.session_state.get(sel_key)
        selection = getattr(sel_state, "selection", None)
        if selection is None and isinstance(sel_state, dict):
            selection = sel_state.get("selection")
        rows = getattr(selection, "rows", None)
        if rows is None and isinstance(selection, dict):
            rows = selection.get("rows")
        if rows:
            return True
    return False


def _has_untried_unsaved_sources() -> bool:
    triggered = set(st.session_state.get(_UNSAVED_NAV_TRIGGERED_KEY) or [])
    sources = st.session_state.get(_UNSAVED_SOURCES_KEY) or []
    for item in sources:
        if not isinstance(item, dict):
            continue
        if str(item.get("source_id") or "") in triggered:
            continue
        if _source_item_has_unsaved(item):
            return True
    return False


def clear_unsaved_tracking_state() -> None:
    """Clear transient unsaved-change tracking state when switching contexts."""
    st.session_state.pop(_UNSAVED_SOURCES_KEY, None)
    st.session_state.pop(_PENDING_UNSAVED_NAV_KEY, None)
    st.session_state.pop(_UNSAVED_NAV_ACTION_KEY, None)
    st.session_state.pop(_UNSAVED_NAV_EXECUTING_KEY, None)
    st.session_state.pop(_UNSAVED_NAV_AFTER_ACTION_KEY, None)
    st.session_state.pop(_UNSAVED_NAV_TRIGGERED_KEY, None)
    for k in list(st.session_state.keys()):
        if str(k).startswith("_table_subtab_draft_") or str(k).startswith("_table_filter_id_draft_"):
            st.session_state.pop(k, None)


def request_unsaved_page_navigation(target_url_path: str, *, label: str = "") -> None:
    """Intercept a main-tab page switch and queue the Unsaved Changes dialog."""
    st.session_state[_PENDING_UNSAVED_NAV_KEY] = {
        "kind": "page",
        "target": str(target_url_path),
        "label": str(label or target_url_path),
    }


def register_unsaved_source(
    source_id: str,
    *,
    editor_key: str | None = None,
    native_row_selection: bool = False,
    additional_unsaved: bool = False,
) -> tuple[bool, bool]:
    """Register an editable view source and return (trigger_save, trigger_discard)."""
    unsaved = (
        (
            bool(editor_key)
            and table_has_unsaved_changes(
                editor_key, native_row_selection=native_row_selection
            )
        )
        or bool(additional_unsaved)
    )
    sources = list(st.session_state.get(_UNSAVED_SOURCES_KEY) or [])
    sources = [
        item
        for item in sources
        if isinstance(item, dict) and item.get("source_id") != source_id
    ]
    sources.append(
        {
            "source_id": str(source_id),
            "editor_key": str(editor_key or ""),
            "native_row_selection": bool(native_row_selection),
            "additional_unsaved": bool(additional_unsaved),
        }
    )
    st.session_state[_UNSAVED_SOURCES_KEY] = sources
    executing_action = st.session_state.get(_UNSAVED_NAV_EXECUTING_KEY)
    triggered = list(st.session_state.get(_UNSAVED_NAV_TRIGGERED_KEY) or [])
    trigger_save = False
    trigger_discard = False
    if unsaved and executing_action in ("save", "discard") and source_id not in triggered:
        triggered.append(str(source_id))
        st.session_state[_UNSAVED_NAV_TRIGGERED_KEY] = triggered
        trigger_save = executing_action == "save"
        trigger_discard = executing_action == "discard"
    return trigger_save, trigger_discard


_CONFLICT_IGNORED_COLUMNS: frozenset[str] = frozenset(
    {
        "id",
        DEFAULT_SELECTION_COLUMN,
        "view_details",
        "created_at",
        "updated_at",
        "created_display",
        "updated_display",
        "photo_status",
        "applicability_status",
    }
)

_CONFLICT_ROW_LABEL_COLUMNS: tuple[str, ...] = (
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
    "detail",
    "label",
    "description",
)


def _conflict_cell_values_equal(left: object, right: object) -> bool:
    if isinstance(left, (list, tuple, set)) and isinstance(right, (list, tuple, set)):
        left_norm = [str(x).strip() for x in left if str(x).strip()]
        right_norm = [str(x).strip() for x in right if str(x).strip()]
        return left_norm == right_norm
    return _audit_cell_values_equal(left, right)


def _format_conflict_cell_value(val: object) -> str:
    if val is None:
        return "(blank)"
    if isinstance(val, bool):
        return "Checked" if val else "Unchecked"
    if isinstance(val, (list, tuple, set)):
        cleaned = [str(x).strip() for x in val if str(x).strip()]
        return ", ".join(cleaned) if cleaned else "(blank)"
    try:
        if pd.isna(val):
            return "(blank)"
    except Exception:
        pass
    if isinstance(val, (int, float)):
        formatted = format_clean_number(val)
        return formatted if formatted else "(blank)"
    text = str(val).strip()
    return text if text else "(blank)"


def _extract_conflict_row_label(
    row: pd.Series,
    pos: int | None,
    row_labels: dict[int, str] | None,
) -> str:
    if isinstance(row_labels, dict) and pos is not None and pos in row_labels:
        lbl = str(row_labels[pos] or "").strip()
        if lbl and not lbl.startswith("Row "):
            return lbl
    for col in _CONFLICT_ROW_LABEL_COLUMNS:
        if col not in row.index:
            continue
        val = row.get(col)
        try:
            if val is None or pd.isna(val):
                continue
        except Exception:
            if val is None:
                continue
        text = str(val).strip()
        if text:
            return text[:48] + ("..." if len(text) > 48 else "")
    if pos is not None:
        return f"Row {pos + 1}"
    return "Edited row"


def detect_table_cell_conflicts(editor_key: str) -> list[dict[str, str]]:
    """Detect cells edited by the current user that were also modified and saved in the DB since editing began."""
    logical_key = logical_table_editor_key(editor_key)
    base_df = st.session_state.get(f"_table_clean_base_df_{logical_key}")
    live_df = st.session_state.get(f"_table_live_df_{logical_key}")
    if (
        not isinstance(base_df, pd.DataFrame)
        or not isinstance(live_df, pd.DataFrame)
        or base_df.empty
    ):
        return []

    display_df = st.session_state.get(f"_table_display_df_{logical_key}")
    id_draft = st.session_state.get(f"_table_id_draft_{logical_key}") or {}
    state = get_effective_table_editor_state(editor_key)
    meta = st.session_state.get(f"_table_undo_meta_{logical_key}")
    col_labels: dict[str, str] = (
        meta.get("col_labels", {}) if isinstance(meta, dict) else {}
    )
    row_labels: dict[int, str] = (
        meta.get("row_labels", {}) if isinstance(meta, dict) else {}
    )

    has_id_col = "id" in base_df.columns and "id" in live_df.columns
    base_by_id: dict[str, pd.Series] = {}
    live_by_id: dict[str, pd.Series] = {}
    if has_id_col:
        for _, b_row in base_df.iterrows():
            bid = b_row.get("id")
            if bid is not None and not pd.isna(bid) and str(bid).strip():
                base_by_id[str(bid).strip()] = b_row
        for _, l_row in live_df.iterrows():
            lid = l_row.get("id")
            if lid is not None and not pd.isna(lid) and str(lid).strip():
                live_by_id[str(lid).strip()] = l_row

    edits_by_row_key: dict[tuple[str, int | None], dict[str, object]] = {}
    pos_for_row_key: dict[tuple[str, int | None], int] = {}

    if isinstance(id_draft, dict):
        for raw_rid, chg_map in id_draft.items():
            rid_str = str(raw_rid or "").strip()
            if not rid_str or rid_str.startswith("__draft_new__") or not isinstance(chg_map, dict):
                continue
            r_key = (rid_str, None)
            for col_name, col_val in chg_map.items():
                if str(col_name) not in _CONFLICT_IGNORED_COLUMNS:
                    edits_by_row_key.setdefault(r_key, {})[str(col_name)] = col_val

    for raw_pos, chg_map in (state.get("edited_rows") or {}).items():
        if not isinstance(chg_map, dict):
            continue
        try:
            pos = int(raw_pos)
        except (TypeError, ValueError):
            continue
        rid_str = ""
        if (
            has_id_col
            and isinstance(display_df, pd.DataFrame)
            and "id" in display_df.columns
            and 0 <= pos < len(display_df)
        ):
            raw_id = display_df.iloc[pos].get("id")
            if raw_id is not None and not pd.isna(raw_id):
                rid_str = str(raw_id).strip()
        elif has_id_col and 0 <= pos < len(base_df):
            raw_id = base_df.iloc[pos].get("id")
            if raw_id is not None and not pd.isna(raw_id):
                rid_str = str(raw_id).strip()
        if rid_str.startswith("__draft_new__"):
            continue
        r_key = (rid_str, None) if rid_str else ("", pos)
        pos_for_row_key[r_key] = pos
        for col_name, col_val in chg_map.items():
            if str(col_name) not in _CONFLICT_IGNORED_COLUMNS:
                edits_by_row_key.setdefault(r_key, {})[str(col_name)] = col_val

    conflicts: list[dict[str, str]] = []
    for r_key, col_changes in edits_by_row_key.items():
        rid_str, pos_fallback = r_key
        pos_hint = pos_for_row_key.get(r_key, pos_fallback)
        base_row: pd.Series | None = None
        live_row: pd.Series | None = None
        if rid_str and has_id_col:
            base_row = base_by_id.get(rid_str)
            live_row = live_by_id.get(rid_str)
        elif pos_fallback is not None:
            if 0 <= pos_fallback < len(base_df):
                base_row = base_df.iloc[pos_fallback]
            if 0 <= pos_fallback < len(live_df):
                live_row = live_df.iloc[pos_fallback]

        if base_row is None:
            continue

        row_label = _extract_conflict_row_label(base_row, pos_hint, row_labels)
        for col_name, user_val in col_changes.items():
            if col_name not in base_row.index:
                continue
            base_val = base_row[col_name]
            if _conflict_cell_values_equal(user_val, base_val):
                continue
            col_label = (
                col_labels.get(col_name)
                or col_name.replace("_", " ").strip().title()
            )
            if live_row is None:
                conflicts.append(
                    {
                        "row_label": row_label,
                        "column": col_name,
                        "column_label": col_label,
                        "base_value": _format_conflict_cell_value(base_val),
                        "saved_value": "(Row deleted)",
                        "your_value": _format_conflict_cell_value(user_val),
                    }
                )
            elif col_name in live_row.index:
                live_val = live_row[col_name]
                if not _conflict_cell_values_equal(live_val, base_val):
                    conflicts.append(
                        {
                            "row_label": row_label,
                            "column": col_name,
                            "column_label": col_label,
                            "base_value": _format_conflict_cell_value(base_val),
                            "saved_value": _format_conflict_cell_value(live_val),
                            "your_value": _format_conflict_cell_value(user_val),
                        }
                    )
    return conflicts


@st.dialog("Save Conflict Detected", width="large", dismissible=False)
def _save_conflict_dialog(logical_key: str, conflict_payload: dict[str, object]) -> None:
    conflicts = list(conflict_payload.get("conflicts") or [])
    who = str(conflict_payload.get("editor_name") or "another collaborator").strip()
    cell_count = len(conflicts)
    st.warning(
        f"**{who}** already saved changes to **{cell_count} cell(s)** that you also edited. "
        "Choose whether to overwrite their saved values with your changes, discard your changes, or return to the table to review.",
        icon=":material/sync_problem:",
    )
    if conflicts:
        conflict_df = pd.DataFrame(
            [
                {
                    "Row": str(item.get("row_label") or item.get("Row") or ""),
                    "Column": str(
                        item.get("column_label")
                        or item.get("field")
                        or item.get("Field")
                        or ""
                    ),
                    "Original value": str(
                        item.get("base_value") or item.get("Original Value") or ""
                    ),
                    f"Saved by {who}": str(
                        item.get("saved_value")
                        or item.get("Saved by Collaborator")
                        or ""
                    ),
                    "Your unsaved edit": str(
                        item.get("your_value") or item.get("Your Unsaved Edit") or ""
                    ),
                }
                for item in conflicts
            ]
        )
        st.dataframe(conflict_df, hide_index=True, width="stretch")

    action_bar = st.container(
        horizontal=True,
        vertical_alignment="center",
        horizontal_alignment="right",
    )
    if action_bar.button(
        "Overwrite with my changes",
        type="primary",
        icon=":material/save:",
        key=f"conflict_overwrite_{logical_key}",
    ):
        st.session_state.pop(f"_pending_save_conflict_{logical_key}", None)
        st.session_state[f"_confirm_save_conflict_overwrite_{logical_key}"] = True
        st.rerun()
    if action_bar.button(
        "Discard my changes",
        icon=":material/delete:",
        key=f"destructive_conflict_discard_{logical_key}",
    ):
        st.session_state.pop(f"_pending_save_conflict_{logical_key}", None)
        st.session_state.pop(f"_conflict_saved_payload_{logical_key}", None)
        st.session_state[f"_confirm_save_conflict_discard_{logical_key}"] = True
        st.rerun()
    if action_bar.button(
        "Return to review",
        icon=":material/arrow_back:",
        key=f"conflict_return_{logical_key}",
    ):
        st.session_state.pop(f"_pending_save_conflict_{logical_key}", None)
        st.session_state.pop(f"_conflict_saved_payload_{logical_key}", None)
        st.rerun()


def compare_record_field_conflicts(
    baseline: dict[str, object],
    live: dict[str, object],
    user_values: dict[str, object],
    field_labels: dict[str, str],
    *,
    row_label: str = "",
    formatters: dict[str, object] | None = None,
) -> tuple[dict[str, object], list[dict[str, str]]]:
    """Compare baseline, live DB, and user-submitted fields, returning (merged_values, conflicts).

    Fields that the user did not change relative to ``baseline`` automatically adopt the
    current ``live`` value so non-overlapping concurrent edits are preserved.
    """
    conflicts: list[dict[str, str]] = []
    merged: dict[str, object] = dict(user_values)
    fmt_map = formatters or {}
    for col_name, col_label in field_labels.items():
        base_val = baseline.get(col_name)
        live_val = live.get(col_name)
        user_val = user_values.get(col_name)
        if _conflict_cell_values_equal(user_val, base_val):
            if col_name in live:
                merged[col_name] = live_val
            continue
        if not _conflict_cell_values_equal(live_val, base_val) and not _conflict_cell_values_equal(
            user_val, live_val
        ):
            fmt_fn = fmt_map.get(col_name)
            if callable(fmt_fn):
                b_str = str(fmt_fn(base_val))
                l_str = str(fmt_fn(live_val))
                u_str = str(fmt_fn(user_val))
            else:
                b_str = _format_conflict_cell_value(base_val)
                l_str = _format_conflict_cell_value(live_val)
                u_str = _format_conflict_cell_value(user_val)
            r_lbl = row_label or "Current record"
            conflicts.append(
                {
                    "row_label": r_lbl,
                    "field": col_label,
                    "column": col_name,
                    "column_label": col_label,
                    "base_value": b_str,
                    "saved_value": l_str,
                    "your_value": u_str,
                    "Row": r_lbl,
                    "Field": col_label,
                    "Original Value": b_str,
                    "Saved by Collaborator": l_str,
                    "Your Unsaved Edit": u_str,
                }
            )
    return merged, conflicts


def render_inline_conflict_resolution(
    conflict_key: str,
) -> str | None:
    """Render an inline conflict resolution banner and table inside an already-open modal dialog.

    Returns ``"overwrite"``, ``"discard"``, or ``None``.
    """
    state_key = f"_inline_conflict_{conflict_key}"
    raw = st.session_state.get(state_key)
    if raw is None and conflict_key in st.session_state:
        state_key = conflict_key
        raw = st.session_state.get(conflict_key)
    if isinstance(raw, dict):
        conflicts = list(raw.get("conflicts") or [])
        who = str(
            raw.get("editor_name")
            or get_last_write_metadata().get("editor_name")
            or "another collaborator"
        ).strip()
    elif isinstance(raw, list):
        conflicts = list(raw)
        who = str(
            get_last_write_metadata().get("editor_name") or "another collaborator"
        ).strip()
    else:
        return None
    if not conflicts:
        return None
    st.warning(
        f"**{who}** already saved changes to **{len(conflicts)} field(s)** that you also edited. "
        "Choose whether to overwrite their saved values with your changes or discard your edits.",
        icon=":material/sync_problem:",
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Field": str(
                        item.get("column_label")
                        or item.get("field")
                        or item.get("Field")
                        or ""
                    ),
                    "Original value": str(
                        item.get("base_value") or item.get("Original Value") or ""
                    ),
                    f"Saved by {who}": str(
                        item.get("saved_value")
                        or item.get("Saved by Collaborator")
                        or ""
                    ),
                    "Your unsaved edit": str(
                        item.get("your_value") or item.get("Your Unsaved Edit") or ""
                    ),
                }
                for item in conflicts
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    c_bar = st.container(horizontal=True, horizontal_alignment="right")
    overwrite_clicked = c_bar.button(
        "Overwrite with my changes",
        type="primary",
        icon=":material/save:",
        key=f"inline_conflict_overwrite_{conflict_key}",
    )
    discard_clicked = c_bar.button(
        "Discard my changes",
        icon=":material/delete:",
        key=f"destructive_inline_conflict_discard_{conflict_key}",
    )
    if overwrite_clicked:
        st.session_state.pop(state_key, None)
        return "overwrite"
    if discard_clicked:
        st.session_state.pop(state_key, None)
        return "discard"
    return None


def trigger_standalone_conflict_dialog(
    logical_key: str,
    conflicts: list[dict[str, str]],
    *,
    payload: object = None,
) -> None:
    """Queue a Save Conflict Detected modal for a non-editable_table_footer save action."""
    meta = get_last_write_metadata()
    who = str(meta.get("editor_name") or "another collaborator").strip()
    st.session_state[f"_pending_save_conflict_{logical_key}"] = {
        "conflicts": conflicts,
        "editor_name": who,
        "key_prefix": logical_key,
    }
    if payload is not None:
        st.session_state[f"_conflict_saved_payload_{logical_key}"] = payload


def check_standalone_conflict_resolution(
    logical_key: str,
) -> tuple[bool | str | None, object]:
    """Return (resolution, saved_payload) where resolution is True (overwrite), 'discard', or None."""
    confirmed_overwrite = bool(
        st.session_state.pop(f"_confirm_save_conflict_overwrite_{logical_key}", False)
        or st.session_state.pop(f"_conflict_confirmed_save_{logical_key}", False)
    )
    confirmed_discard = bool(
        st.session_state.pop(f"_confirm_save_conflict_discard_{logical_key}", False)
    )
    saved_payload = None
    if confirmed_overwrite or confirmed_discard:
        saved_payload = st.session_state.pop(
            f"_conflict_saved_payload_{logical_key}", None
        )
    if confirmed_overwrite:
        return True, saved_payload
    if confirmed_discard:
        return "discard", saved_payload
    return None, None


def render_standalone_conflict_dialog(logical_key: str) -> None:
    """Render the Save Conflict Detected modal if one is pending for ``logical_key``."""
    pending_conflict = st.session_state.get(f"_pending_save_conflict_{logical_key}")
    if isinstance(pending_conflict, dict) and pending_conflict.get("conflicts"):
        _save_conflict_dialog(logical_key, pending_conflict)


def editable_table_footer(
    *,
    editor_key: str,
    key_prefix: str,
    undo_available: bool = False,
    native_row_selection: bool = False,
    additional_unsaved_changes: bool = False,
    show_select_all_controls: bool = False,
    selectable_row_count: int = 0,
    selected_row_count: int = 0,
    selection_column: str = DEFAULT_SELECTION_COLUMN,
    delete_action_label: str | None = None,
    delete_action_icon: str | None = None,
    delete_action_key: str | None = None,
    delete_action_disabled: bool = False,
    delete_action_help: str | None = None,
    secondary_action_label: str | None = None,
    secondary_action_icon: str | None = None,
    secondary_action_key: str | None = None,
    secondary_action_disabled: bool = False,
    secondary_action_help: str | None = None,
    additional_action_label: str | None = None,
    additional_action_icon: str | None = None,
    additional_action_key: str | None = None,
    additional_action_disabled: bool = False,
    additional_action_help: str | None = None,
) -> TableHeaderActions:
    """Render the standard warning and actions below an editable table."""
    logical_key = logical_table_editor_key(editor_key)
    confirmed_overwrite = bool(
        st.session_state.pop(f"_confirm_save_conflict_overwrite_{logical_key}", False)
    )
    confirmed_discard = bool(
        st.session_state.pop(f"_confirm_save_conflict_discard_{logical_key}", False)
    )
    unsaved = (
        table_has_unsaved_changes(
            editor_key, native_row_selection=native_row_selection
        )
        or additional_unsaved_changes
    )
    trigger_save, trigger_discard = register_unsaved_source(
        key_prefix,
        editor_key=editor_key,
        native_row_selection=native_row_selection,
        additional_unsaved=additional_unsaved_changes,
    )
    footer = st.container(
        horizontal=True,
        vertical_alignment="center",
        horizontal_alignment="right",
    )
    base_epoch_key = f"_table_base_epoch_{logical_key}"
    current_epoch = get_write_epoch()
    if not unsaved:
        st.session_state[base_epoch_key] = current_epoch
        st.session_state.pop(f"_pending_save_conflict_{logical_key}", None)
    else:
        base_epoch = int(st.session_state.get(base_epoch_key, current_epoch) or current_epoch)
        st.html('<span data-paag-unsaved="true" style="display:none;"></span>')
        if current_epoch > base_epoch:
            meta = get_last_write_metadata()
            active_pid = str(st.session_state.get("project_id") or "").strip()
            meta_pid = str(meta.get("project_id") or "").strip()
            if not active_pid or not meta_pid or active_pid == meta_pid:
                who = str(meta.get("editor_name") or "another collaborator").strip()
                footer.markdown(
                    f":red[:material/sync_problem: **New changes saved by {who}**]"
                )
        footer.markdown(":orange[:material/warning: **Unsaved changes**]")
    if show_select_all_controls:
        render_select_all_control(
            footer,
            editor_key=editor_key,
            selectable_count=selectable_row_count,
            selected_count=selected_row_count,
            key_prefix=key_prefix,
            column=selection_column,
            always_show_both=True,
        )
    delete_action = False
    if delete_action_label:
        delete_action = footer.button(
            delete_action_label,
            icon=delete_action_icon,
            disabled=delete_action_disabled,
            help=delete_action_help,
            key=(
                delete_action_key
                if delete_action_key and str(delete_action_key).startswith("destructive_")
                else f"destructive_{delete_action_key or f'{key_prefix}_delete_action'}"
            ),
        )
    secondary_action = False
    if secondary_action_label:
        secondary_action = footer.button(
            secondary_action_label,
            icon=secondary_action_icon,
            disabled=secondary_action_disabled,
            help=secondary_action_help,
            key=secondary_action_key or f"{key_prefix}_secondary_action",
        )
    additional_action = False
    if additional_action_label:
        additional_action = footer.button(
            additional_action_label,
            icon=additional_action_icon,
            disabled=additional_action_disabled,
            help=additional_action_help,
            key=additional_action_key or f"{key_prefix}_additional_action",
        )
    can_undo_last = can_undo_last_table_edit(
        editor_key,
        native_row_selection=native_row_selection,
    )
    undo_last = footer.button(
        "Undo last edit",
        icon=":material/undo:",
        disabled=not can_undo_last,
        help="Revert the most recent cell edit while keeping earlier unsaved changes.",
        key=f"{key_prefix}_undo_last_edit",
    )
    if undo_last:
        if undo_last_table_edit(editor_key):
            st.toast(
                last_table_undo_redo_message(
                    editor_key,
                    default="Reverted the last cell edit.",
                ),
                icon=":material/undo:",
            )
            st.rerun()
    can_redo_last = can_redo_last_table_edit(
        editor_key,
        native_row_selection=native_row_selection,
    )
    redo_last = footer.button(
        "Redo last edit",
        icon=":material/redo:",
        disabled=not can_redo_last,
        help="Reapply the most recently undone cell edit.",
        key=f"{key_prefix}_redo_last_edit",
    )
    if redo_last:
        if redo_last_table_edit(editor_key):
            st.toast(
                last_table_undo_redo_message(
                    editor_key,
                    default="Reapplied the last undone cell edit.",
                ),
                icon=":material/redo:",
            )
            st.rerun()
    undo = footer.button(
        "Discard all edits",
        icon=":material/restart_alt:",
        disabled=not (unsaved or undo_available),
        help="Discard all unsaved changes in this table and restore the last saved values.",
        key=f"{key_prefix}_undo",
    )
    save_and_refresh = footer.button(
        "Save & Refresh",
        type="primary",
        icon=":material/save:",
        key=f"{key_prefix}_save_refresh",
    )
    wants_save = bool(save_and_refresh or trigger_save or confirmed_overwrite)
    wants_discard = bool(undo or trigger_discard or confirmed_discard)
    if wants_discard:
        st.session_state.pop(f"_pending_save_conflict_{logical_key}", None)
    elif wants_save and not confirmed_overwrite:
        conflicts = detect_table_cell_conflicts(editor_key)
        if conflicts:
            meta = get_last_write_metadata()
            who = str(meta.get("editor_name") or "another collaborator").strip()
            st.session_state[f"_pending_save_conflict_{logical_key}"] = {
                "conflicts": conflicts,
                "editor_name": who,
                "key_prefix": key_prefix,
            }
            wants_save = False
            if trigger_save:
                st.session_state.pop(_PENDING_UNSAVED_NAV_KEY, None)
                st.session_state.pop(_UNSAVED_NAV_EXECUTING_KEY, None)
                st.session_state.pop(_UNSAVED_NAV_AFTER_ACTION_KEY, None)
                st.session_state.pop(_UNSAVED_NAV_TRIGGERED_KEY, None)

    pending_conflict = st.session_state.get(f"_pending_save_conflict_{logical_key}")
    if isinstance(pending_conflict, dict) and pending_conflict.get("conflicts"):
        _save_conflict_dialog(logical_key, pending_conflict)

    return TableHeaderActions(
        save_and_refresh=wants_save,
        undo=wants_discard,
        additional_action=additional_action,
        secondary_action=secondary_action,
        delete_action=delete_action,
    )


def paginate_table_rows(
    dataframe: pd.DataFrame,
    *,
    key: str,
    default_page_size: int = 100,
    page_size_options: tuple[int, ...] = (50, 100, 250, 500),
    render_controls: bool = True,
) -> pd.DataFrame:
    """Slice a large table into a single page while remaining compatible with merge_filtered_edits()."""
    total_rows = len(dataframe)
    options = tuple(sorted({int(opt) for opt in (*page_size_options, default_page_size) if int(opt) > 0}))
    size_key = f"{key}_page_size"
    size_key = f"{key}_page_size"
    page_key = f"{key}_page_number"
    saved_size_key = f"_saved_page_size_{key}"
    saved_page_key = f"_saved_page_num_{key}"
    if size_key not in st.session_state and saved_size_key in st.session_state:
        st.session_state[size_key] = st.session_state.get(saved_size_key)
    if page_key not in st.session_state and saved_page_key in st.session_state:
        st.session_state[page_key] = st.session_state.get(saved_page_key)
    current_size = int(st.session_state.get(size_key, default_page_size) or default_page_size)
    if current_size not in options:
        current_size = int(default_page_size)
        st.session_state[size_key] = current_size

    if total_rows <= min(options):
        return dataframe.reset_index(drop=True)

    total_pages = max(1, (total_rows + current_size - 1) // current_size)
    current_page = int(st.session_state.get(page_key, 1) or 1)
    if current_page < 1 or current_page > total_pages:
        current_page = max(1, min(current_page, total_pages))
        st.session_state[page_key] = current_page

    if render_controls:
        bar = st.container(horizontal=True, vertical_alignment="bottom")
        selected_size = int(
            bar.selectbox(
                "Rows per page",
                options=list(options),
                key=size_key,
                width=140,
            )
        )
        total_pages = max(1, (total_rows + selected_size - 1) // selected_size)
        if current_page > total_pages:
            current_page = total_pages
            st.session_state[page_key] = current_page
        selected_page = int(
            bar.number_input(
                f"Page (1–{total_pages})",
                min_value=1,
                max_value=total_pages,
                step=1,
                key=page_key,
                width=140,
            )
        )
        current_size = selected_size
        current_page = selected_page

    st.session_state[saved_size_key] = int(current_size)
    st.session_state[saved_page_key] = int(current_page)
    start = (current_page - 1) * current_size
    end = min(total_rows, start + current_size)
    if render_controls:
        st.caption(f"Showing rows {start + 1:,}–{end:,} of {total_rows:,} (page {current_page} of {total_pages})")
    return dataframe.iloc[start:end].reset_index(drop=True)


def _has_non_table_unsaved_changes() -> bool:
    """Return True if any non-table source on the current view has unsaved changes."""
    return any(
        isinstance(item, dict)
        and bool(item.get("additional_unsaved"))
        and not str(item.get("editor_key") or "").strip()
        for item in (st.session_state.get(_UNSAVED_SOURCES_KEY) or [])
    )


def _on_guarded_tab_change(tab_key: str) -> None:
    committed_key = f"_committed_tab_{tab_key}"
    gen_key = f"_guarded_tab_gen_{tab_key}"
    gen = int(st.session_state.get(gen_key, 0) or 0)
    widget_key = f"{tab_key}__tab_gen_{gen}"
    new_val = str(st.session_state.get(widget_key) or "")
    prev_tab = str(st.session_state.get(committed_key) or "")
    if not new_val or new_val == prev_tab:
        return
    if _has_non_table_unsaved_changes():
        st.session_state[committed_key] = prev_tab
        st.session_state[tab_key] = prev_tab
        st.session_state[gen_key] = gen + 1
        st.session_state[_PENDING_UNSAVED_NAV_KEY] = {
            "kind": "subtab",
            "tab_key": tab_key,
            "target": new_val,
            "label": new_val,
        }
    else:
        st.session_state[committed_key] = new_val
        st.session_state[tab_key] = new_val


def guarded_tabs(
    tabs: Sequence[str],
    *,
    key: str,
    default: str | None = None,
):
    """Render st.tabs that intercept tab switches when unsaved changes exist."""
    tab_list = [str(tab) for tab in tabs]
    committed_key = f"_committed_tab_{key}"
    gen_key = f"_guarded_tab_gen_{key}"
    gen = int(st.session_state.get(gen_key, 0) or 0)
    fallback_tab = (
        default
        if (default and default in tab_list)
        else (tab_list[0] if tab_list else "")
    )

    external_val = st.session_state.get(key)
    committed_tab = st.session_state.get(committed_key)
    if (
        isinstance(external_val, str)
        and external_val in tab_list
        and external_val != committed_tab
    ):
        committed_tab = external_val
        st.session_state[committed_key] = committed_tab
        gen += 1
        st.session_state[gen_key] = gen
    elif not isinstance(committed_tab, str) or committed_tab not in tab_list:
        committed_tab = fallback_tab
        st.session_state[committed_key] = committed_tab
        st.session_state[key] = committed_tab
    else:
        st.session_state[key] = committed_tab

    widget_key = f"{key}__tab_gen_{gen}"
    return st.tabs(
        tab_list,
        key=widget_key,
        default=committed_tab if committed_tab in tab_list else None,
        on_change=_on_guarded_tab_change,
        args=(key,),
    )


def _has_blocking_save_dialog_state() -> bool:
    for state_key, state_val in st.session_state.items():
        s_key = str(state_key)
        if (
            s_key.startswith("_pending_group_conflict_")
            or s_key.startswith("_pending_save_conflict_")
        ) and state_val:
            return True
    return False


def request_unsaved_state_change(
    state_updates: dict[str, object],
    *,
    label: str,
    nav_kind: str = "selection",
    clear_keys: Sequence[str] | None = None,
    clear_unsaved_tracking: bool = False,
) -> None:
    """Intercept a context/selector switch and queue the Unsaved Changes dialog."""
    st.session_state[_PENDING_UNSAVED_NAV_KEY] = {
        "kind": "state_change",
        "state_updates": dict(state_updates),
        "clear_keys": [str(k) for k in (clear_keys or [])],
        "clear_unsaved_tracking": bool(clear_unsaved_tracking),
        "label": str(label),
        "nav_kind": str(nav_kind or "selection"),
    }


def _complete_pending_unsaved_nav(
    page_by_url_path: dict[str, object],
    *,
    split_secondary_key: str | None = None,
) -> None:
    pending = st.session_state.pop(_PENDING_UNSAVED_NAV_KEY, None)
    st.session_state.pop(_UNSAVED_NAV_ACTION_KEY, None)
    st.session_state.pop(_UNSAVED_NAV_EXECUTING_KEY, None)
    st.session_state.pop(_UNSAVED_NAV_AFTER_ACTION_KEY, None)
    st.session_state.pop(_UNSAVED_NAV_TRIGGERED_KEY, None)
    for k in list(st.session_state.keys()):
        if str(k).startswith("_table_subtab_draft_") or str(k).startswith("_table_filter_id_draft_"):
            st.session_state.pop(k, None)
    if not isinstance(pending, dict):
        return
    kind = str(pending.get("kind") or "")
    target = str(pending.get("target") or "")
    if kind == "page" and target in page_by_url_path:
        if split_secondary_key and target == str(
            st.session_state.get(split_secondary_key) or ""
        ):
            st.session_state.pop(split_secondary_key, None)
        clear_unsaved_tracking_state()
        st.switch_page(page_by_url_path[target])
    elif kind == "subtab":
        tab_key = str(pending.get("tab_key") or "")
        if tab_key and target:
            st.session_state[f"_committed_tab_{tab_key}"] = target
            st.session_state[tab_key] = target
            gen_key = f"_guarded_tab_gen_{tab_key}"
            st.session_state[gen_key] = int(st.session_state.get(gen_key, 0) or 0) + 1
            st.session_state[gen_key] = int(st.session_state.get(gen_key, 0) or 0) + 1
            st.session_state.pop(_UNSAVED_SOURCES_KEY, None)
    elif kind == "state_change":
        state_updates = pending.get("state_updates")
        if isinstance(state_updates, dict):
            for k, v in state_updates.items():
                st.session_state[str(k)] = v
        clear_keys = pending.get("clear_keys")
        if isinstance(clear_keys, list):
            for k in clear_keys:
                st.session_state.pop(str(k), None)
        if pending.get("clear_unsaved_tracking"):
            clear_unsaved_tracking_state()
        else:
            st.session_state.pop(_UNSAVED_SOURCES_KEY, None)


def begin_unsaved_tracking(
    page_by_url_path: dict[str, object],
    *,
    split_secondary_key: str | None = None,
) -> None:
    """Prepare unsaved-change tracking before rendering the active workspace page."""
    action = st.session_state.pop(_UNSAVED_NAV_ACTION_KEY, None)
    if action in ("save", "discard"):
        st.session_state[_UNSAVED_NAV_EXECUTING_KEY] = action
        st.session_state[_UNSAVED_NAV_AFTER_ACTION_KEY] = action
    else:
        after_action = st.session_state.pop(_UNSAVED_NAV_AFTER_ACTION_KEY, None)
        if after_action in ("save", "discard"):
            if _has_blocking_save_dialog_state():
                st.session_state.pop(_PENDING_UNSAVED_NAV_KEY, None)
                st.session_state.pop(_UNSAVED_NAV_EXECUTING_KEY, None)
                st.session_state.pop(_UNSAVED_NAV_TRIGGERED_KEY, None)
            elif _has_untried_unsaved_sources():
                st.session_state[_UNSAVED_NAV_EXECUTING_KEY] = after_action
                st.session_state[_UNSAVED_NAV_AFTER_ACTION_KEY] = after_action
            else:
                _complete_pending_unsaved_nav(
                    page_by_url_path,
                    split_secondary_key=split_secondary_key,
                )
    st.session_state[_UNSAVED_SOURCES_KEY] = []
    st.session_state["_active_selectable_df_keys"] = []


@st.dialog("Unsaved Changes", dismissible=False)
def _unsaved_changes_navigation_dialog(pending: dict[str, object]) -> None:
    target_label = str(
        pending.get("label") or pending.get("target") or "the selected view"
    )
    default_nav_kind = "sub-tab" if pending.get("kind") == "subtab" else "tab"
    nav_kind = str(pending.get("nav_kind") or default_nav_kind)
    st.warning(
        f"You have unsaved changes on this page. What would you like to do before leaving for the **{target_label}** {nav_kind}?",
        icon=":material/warning:",
    )
    nav_bar = st.container(
        horizontal=True,
        vertical_alignment="center",
        horizontal_alignment="right",
    )
    if nav_bar.button(
        "Save & Refresh",
        type="primary",
        icon=":material/save:",
        key="unsaved_nav_save_refresh",
    ):
        st.session_state[_UNSAVED_NAV_ACTION_KEY] = "save"
        st.session_state[_UNSAVED_NAV_TRIGGERED_KEY] = []
        st.rerun()
    if nav_bar.button(
        "Discard changes",
        icon=":material/delete:",
        key="destructive_unsaved_nav_discard",
    ):
        st.session_state[_UNSAVED_NAV_ACTION_KEY] = "discard"
        st.session_state[_UNSAVED_NAV_TRIGGERED_KEY] = []
        st.rerun()
    if nav_bar.button(
        "Return to page",
        icon=":material/arrow_back:",
        key="unsaved_nav_return",
    ):
        st.session_state.pop(_PENDING_UNSAVED_NAV_KEY, None)
        st.session_state.pop(_UNSAVED_NAV_ACTION_KEY, None)
        st.session_state.pop(_UNSAVED_NAV_EXECUTING_KEY, None)
        st.session_state.pop(_UNSAVED_NAV_AFTER_ACTION_KEY, None)
        st.session_state.pop(_UNSAVED_NAV_TRIGGERED_KEY, None)
        st.rerun()


def finalize_unsaved_tracking(
    page_by_url_path: dict[str, object],
    *,
    split_secondary_key: str | None = None,
) -> None:
    """Complete or prompt for any pending navigation after the page finishes rendering."""
    if has_active_unsaved_changes():
        st.html('<span data-paag-unsaved="true" style="display:none;"></span>')
    else:
        st.session_state["_rendered_write_epoch"] = get_write_epoch()
    executing_action = st.session_state.pop(_UNSAVED_NAV_EXECUTING_KEY, None)
    pending = st.session_state.get(_PENDING_UNSAVED_NAV_KEY)
    if not isinstance(pending, dict):
        st.session_state.pop(_UNSAVED_NAV_AFTER_ACTION_KEY, None)
        st.session_state.pop(_UNSAVED_NAV_TRIGGERED_KEY, None)
        return
    if executing_action:
        st.session_state.pop(_UNSAVED_NAV_AFTER_ACTION_KEY, None)
        st.session_state.pop(_UNSAVED_NAV_TRIGGERED_KEY, None)
        if not has_active_unsaved_changes() and not _has_blocking_save_dialog_state():
            _complete_pending_unsaved_nav(
                page_by_url_path,
                split_secondary_key=split_secondary_key,
            )
            st.rerun()
        else:
            st.session_state.pop(_PENDING_UNSAVED_NAV_KEY, None)
        return
    if _has_non_table_unsaved_changes():
        _unsaved_changes_navigation_dialog(pending)
    elif pending.get("kind") != "subtab" and has_active_unsaved_changes():
        _unsaved_changes_navigation_dialog(pending)
    else:
        _complete_pending_unsaved_nav(
            page_by_url_path,
            split_secondary_key=split_secondary_key,
        )
        st.rerun()
