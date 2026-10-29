from __future__ import annotations

import colorsys
import hashlib
import math
from dataclasses import dataclass
from io import BytesIO
from typing import Iterable, NoReturn, Sequence

import pandas as pd
import streamlit as st

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


def selectable_dataframe(data, *, key: str, **kwargs):
    """Render a read-only table with native multi-row selection and select-all."""
    kwargs.setdefault("on_select", "rerun")
    kwargs.setdefault("selection_mode", "multi-row")
    return st.dataframe(data, key=key, **kwargs)


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
    direction_key = f"{sort_scope}_external_sort_direction"
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
    if controls_locked:
        controls.caption("Save, undo, or clear selected rows before changing the sort.")
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
    if st.session_state.get(f"_reset_table_editor_{logical_key}") and not st.session_state.get(
        f"_pending_undo_last_edit_{logical_key}"
    ):
        return False
    state = get_effective_table_editor_state(editor_key)
    if state.get("added_rows") or (state.get("deleted_rows") and not native_row_selection):
        return True
    ignored = set(ignored_columns)
    return any(
        any(column not in ignored for column in changes)
        for changes in (state.get("edited_rows") or {}).values()
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
) -> None:
    """Render Select all / Clear selection buttons inside a bulk action bar."""
    logical_key = logical_table_editor_key(editor_key)
    all_selected = selectable_count > 0 and selected_count >= selectable_count
    if not all_selected:
        if host.button(
            "Select all",
            icon=":material/select_all:",
            disabled=selectable_count <= 0,
            key=f"{key_prefix}_select_all",
            help="Select all visible saved rows in this table.",
        ):
            st.session_state[f"_select_all_{logical_key}"] = True
            reset_table_editor_selection(editor_key, column=column)
            st.rerun()
    if selected_count > 0:
        if host.button(
            "Clear selection",
            icon=":material/deselect:",
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
):
    """Return an uncluttered, right-aligned row for selected-table actions."""
    host = parent if parent is not None else st
    return host.container(
        horizontal=True,
        vertical_alignment="center",
        horizontal_alignment="right",
        gap=None,
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
    return any(_source_item_has_unsaved(item) for item in sources)


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


def editable_table_footer(
    *,
    editor_key: str,
    key_prefix: str,
    undo_available: bool = False,
    native_row_selection: bool = False,
    additional_unsaved_changes: bool = False,
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
    if unsaved:
        footer.markdown(":orange[:material/warning: **Unsaved changes**]")
    delete_action = False
    if delete_action_label:
        delete_action = footer.button(
            delete_action_label,
            icon=delete_action_icon,
            disabled=delete_action_disabled,
            help=delete_action_help,
            key=delete_action_key or f"{key_prefix}_delete_action",
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
    return TableHeaderActions(
        save_and_refresh=bool(save_and_refresh or trigger_save),
        undo=bool(undo or trigger_discard),
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
    page_key = f"{key}_page_number"
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

    start = (current_page - 1) * current_size
    end = min(total_rows, start + current_size)
    if render_controls:
        st.caption(f"Showing rows {start + 1:,}–{end:,} of {total_rows:,} (page {current_page} of {total_pages})")
    return dataframe.iloc[start:end].reset_index(drop=True)


def _on_guarded_tab_change(tab_key: str) -> None:
    committed_key = f"_committed_tab_{tab_key}"
    gen_key = f"_guarded_tab_gen_{tab_key}"
    gen = int(st.session_state.get(gen_key, 0) or 0)
    widget_key = f"{tab_key}__tab_gen_{gen}"
    new_val = str(st.session_state.get(widget_key) or "")
    prev_tab = str(st.session_state.get(committed_key) or "")
    if not new_val or new_val == prev_tab:
        return
    if has_active_unsaved_changes():
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
        if str(state_key).startswith("_pending_group_conflict_") and state_val:
            return True
    return False


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


@st.dialog("Unsaved Changes", dismissible=False)
def _unsaved_changes_navigation_dialog(pending: dict[str, object]) -> None:
    target_label = str(
        pending.get("label") or pending.get("target") or "the selected view"
    )
    nav_kind = "sub-tab" if pending.get("kind") == "subtab" else "tab"
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
    if has_active_unsaved_changes():
        _unsaved_changes_navigation_dialog(pending)
    else:
        _complete_pending_unsaved_nav(
            page_by_url_path,
            split_secondary_key=split_secondary_key,
        )
        st.rerun()
