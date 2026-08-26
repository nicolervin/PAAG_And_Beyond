from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Iterable, NoReturn

import pandas as pd
import streamlit as st

from utils.table_filters import logical_table_editor_key, request_table_editor_reset


DEFAULT_SELECTION_COLUMN = "selected"


def selectable_dataframe(data, *, key: str, **kwargs):
    """Render a read-only table with native multi-row selection and select-all."""
    kwargs.setdefault("on_select", "rerun")
    kwargs.setdefault("selection_mode", "multi-row")
    return st.dataframe(data, key=key, **kwargs)


def direct_entry_editor_rows(
    dataframe: pd.DataFrame,
    *,
    editor_key: str,
    sort_columns: Iterable[str] | None = None,
    labels: dict[str, str] | None = None,
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
        return dataframe.copy()

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
        return dataframe.copy()
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
    """Actions returned by the standard editable-table footer."""

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
    return TableHeaderActions(save_and_refresh=save_and_refresh, undo=undo)
