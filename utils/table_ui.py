from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Iterable

import pandas as pd
import streamlit as st


DEFAULT_SELECTION_COLUMN = "selected"


def sortable_editor_rows(
    dataframe: pd.DataFrame,
    *,
    defaults: dict[str, object] | None = None,
) -> pd.DataFrame:
    """Append one editable new-record row without disabling column sorting.

    Streamlit disables its native column sorting when ``num_rows`` is
    ``"dynamic"`` or ``"add"``. Standard editors therefore use
    ``num_rows="delete"`` and receive one explicit blank row from this helper.
    """
    defaults = defaults or {}
    blank: dict[str, object] = {}
    for column in dataframe.columns:
        if column in defaults:
            blank[column] = defaults[column]
            continue
        dtype = dataframe[column].dtype
        if pd.api.types.is_bool_dtype(dtype):
            blank[column] = False
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            blank[column] = pd.NaT
        elif pd.api.types.is_numeric_dtype(dtype):
            blank[column] = None
        elif isinstance(dtype, pd.StringDtype):
            blank[column] = ""
        else:
            blank[column] = None
    return pd.concat(
        [dataframe, pd.DataFrame([blank], columns=dataframe.columns)],
        ignore_index=True,
        sort=False,
    )


def drop_untouched_new_rows(
    dataframe: pd.DataFrame,
    *,
    identifying_columns: Iterable[str],
    id_column: str = "id",
) -> pd.DataFrame:
    """Remove the untouched blank row supplied by :func:`sortable_editor_rows`."""

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

    identifying_columns = [
        column for column in identifying_columns if column in dataframe.columns
    ]
    if not identifying_columns:
        return dataframe.copy()
    if id_column in dataframe.columns:
        new_record = dataframe[id_column].apply(is_blank)
    else:
        new_record = pd.Series(True, index=dataframe.index)
    untouched = new_record.copy()
    for column in identifying_columns:
        untouched &= dataframe[column].apply(is_blank)
    return dataframe.loc[~untouched].copy()


@dataclass(frozen=True)
class TableHeaderActions:
    """Actions returned by the standard editable-table section header."""

    save_and_refresh: bool
    undo: bool


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


def editable_table_header(
    title: str,
    *,
    editor_key: str,
    key_prefix: str,
    save_label: str = "Save & refresh",
    undo_available: bool = False,
    native_row_selection: bool = False,
) -> TableHeaderActions:
    """Render the standard title, dirty warning, undo, and primary save control."""
    unsaved = table_has_unsaved_changes(editor_key, native_row_selection=native_row_selection)
    title_col, warning_col, undo_col, action_col = st.columns(
        [4, 0.9, 0.7, 1.15], vertical_alignment="center"
    )
    title_col.subheader(title)
    if unsaved:
        warning_col.markdown(":orange[:material/warning: **Unsaved changes**]")
    undo = undo_col.button(
        "Undo",
        icon=":material/undo:",
        disabled=not (unsaved or undo_available),
        key=f"{key_prefix}_undo",
    )
    save_and_refresh = action_col.button(
        save_label,
        type="primary",
        icon=":material/save:",
        key=f"{key_prefix}_save_refresh",
    )
    return TableHeaderActions(save_and_refresh=save_and_refresh, undo=undo)
