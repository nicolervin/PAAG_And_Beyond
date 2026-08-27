from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
import streamlit as st


_EDITOR_INSTANCE_MARKER = "__editor_instance_"


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
) -> pd.DataFrame:
    """Render consistent keyword/dropdown controls and return the visible rows."""
    if dataframe.empty:
        return dataframe.copy()
    labels = labels or {}
    multi_value_columns = set(multi_value_columns)
    universal_values = universal_values or {}
    valid_dropdowns = [column for column in dropdown_columns if column in dataframe.columns]
    controls = st.container(horizontal=True, vertical_alignment="bottom")
    keyword = controls.text_input(
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

    visible = dataframe.copy()
    if keyword.strip():
        columns = [column for column in (search_columns or visible.columns) if column in visible.columns]
        searchable = visible[columns].fillna("").astype(str).agg(" ".join, axis=1)
        visible = visible[searchable.str.contains(keyword.strip(), case=False, regex=False)]
    for column, values in selected.items():
        if values:
            if column in multi_value_columns:
                visible = visible[
                    visible[column].apply(
                        lambda cell: any(
                            matches_filter_value(
                                cell,
                                value,
                                universal_values=universal_values.get(column, ()),
                            )
                            for value in values
                        )
                    )
                ]
            else:
                visible = visible[visible[column].isin(values)]
    row_identity = (
        tuple(visible["id"].fillna("").astype(str))
        if "id" in visible.columns
        else tuple(str(index) for index in visible.index)
    )
    signature_key = f"{key}_visible_rows"
    if st.session_state.get(signature_key) != row_identity:
        st.session_state[signature_key] = row_identity
        for widget_key in reset_widget_keys:
            st.session_state.pop(widget_key, None)
    st.caption(f"Showing {len(visible):,} of {len(dataframe):,} rows")
    return visible.copy()


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


def has_unsaved_table_changes(key: str) -> bool:
    """Return whether a data editor currently contains pending cell or row changes."""
    state = st.session_state.get(key, {}) or {}
    return bool(state.get("edited_rows") or state.get("added_rows") or state.get("deleted_rows"))


def logical_table_editor_key(key: str) -> str:
    """Return the stable logical key behind a versioned editor instance."""
    return str(key).split(_EDITOR_INSTANCE_MARKER, 1)[0]


def request_table_editor_reset(key: str) -> None:
    """Request a fresh keyed editor instance on the next Streamlit rerun."""
    logical_key = logical_table_editor_key(key)
    st.session_state[f"_reset_table_editor_{logical_key}"] = True


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
        previous_key = f"{logical_key}{_EDITOR_INSTANCE_MARKER}{generation}"
        st.session_state.pop(previous_key, None)
        generation += 1
        st.session_state[generation_key] = generation
    return f"{logical_key}{_EDITOR_INSTANCE_MARKER}{generation}"
