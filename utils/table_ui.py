from __future__ import annotations

import colorsys
import hashlib
import math
from dataclasses import dataclass
from io import BytesIO
from typing import Iterable, NoReturn

import pandas as pd
import streamlit as st

from utils.table_filters import logical_table_editor_key, request_table_editor_reset


DEFAULT_SELECTION_COLUMN = "selected"
DECIMAL_COMPARISON_PLACES = 9


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
        st.session_state[sort_key] = ""
    if not isinstance(st.session_state.get(direction_key), bool):
        st.session_state[direction_key] = False
    editor_state = st.session_state.get(editor_key, {}) or {}
    controls_locked = bool(
        editor_state.get("edited_rows")
        or editor_state.get("added_rows")
        or editor_state.get("deleted_rows")
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
        if pd.api.types.is_string_dtype(series.dtype) or pd.api.types.is_numeric_dtype(series.dtype):
            return (series.isna() | series.astype(str).str.strip().eq("")).astype(bool)
        if series.dtype == object:
            non_null = series.dropna()
            if non_null.empty:
                return pd.Series(True, index=series.index, dtype=bool)
            sample = non_null.iloc[:64]
            if not any(isinstance(v, (list, tuple, set, dict)) for v in sample):
                return (series.isna() | series.astype(str).str.strip().eq("")).astype(bool)
        return series.apply(is_blank).astype(bool)

    identifying_columns = [
        column for column in identifying_columns if column in dataframe.columns
    ]
    if not identifying_columns:
        return dataframe.reset_index(drop=True)
    if id_column in dataframe.columns:
        new_record = series_is_blank(dataframe[id_column])
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


def table_has_unsaved_changes(
    editor_key: str,
    *,
    ignored_columns: Iterable[str] = (DEFAULT_SELECTION_COLUMN,),
    native_row_selection: bool = False,
) -> bool:
    """Detect persisted data edits while ignoring action-only table columns."""
    state = st.session_state.get(editor_key, {}) or {}
    if state.get("added_rows") or (state.get("deleted_rows") and not native_row_selection):
        return True
    ignored = set(ignored_columns)
    return any(
        any(column not in ignored for column in changes)
        for changes in (state.get("edited_rows") or {}).values()
    )


def native_selected_rows(
    source_dataframe: pd.DataFrame,
    *,
    editor_key: str,
    id_column: str = "id",
) -> pd.DataFrame:
    """Return rows chosen with the data editor's native corner/row selectors."""
    if id_column not in source_dataframe:
        return source_dataframe.iloc[0:0].copy()
    state = st.session_state.get(editor_key, {}) or {}
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


def standard_details_column_config(*, on_click, key: str):
    """Return the standard row Details action."""
    return st.column_config.ButtonColumn(
        "Details", type="tertiary", on_click=on_click, key=key,
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


def editable_table_footer(
    *,
    editor_key: str,
    key_prefix: str,
    undo_available: bool = False,
    native_row_selection: bool = False,
    additional_unsaved_changes: bool = False,
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
    footer = st.container(
        horizontal=True,
        vertical_alignment="center",
        horizontal_alignment="right",
    )
    if unsaved:
        footer.markdown(":orange[:material/warning: **Unsaved changes**]")
    additional_action = False
    if additional_action_label:
        additional_action = footer.button(
            additional_action_label,
            icon=additional_action_icon,
            disabled=additional_action_disabled,
            help=additional_action_help,
            key=additional_action_key or f"{key_prefix}_additional_action",
        )
    undo = footer.button(
        "Undo",
        icon=":material/undo:",
        disabled=not (unsaved or undo_available),
        key=f"{key_prefix}_undo",
    )
    save_and_refresh = footer.button(
        "Save & Refresh",
        type="primary",
        icon=":material/save:",
        key=f"{key_prefix}_save_refresh",
    )
    return TableHeaderActions(
        save_and_refresh=save_and_refresh,
        undo=undo,
        additional_action=additional_action,
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
