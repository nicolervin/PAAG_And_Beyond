from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

import pandas as pd
import streamlit as st


_EDITOR_INSTANCE_MARKER = "__editor_instance_"
_ORIG_DATA_EDITOR = getattr(st, "_paag_orig_data_editor", st.data_editor)
setattr(st, "_paag_orig_data_editor", _ORIG_DATA_EDITOR)

_PRODUCT_STRUCTURE_FILTER_KEY_PREFIXES = (
    "pits_reconciliation_filters_",
    "pits_flagged_changes_filter_",
    "pits_registry_filters_",
    "pits_import_preview_filters",
    "pits_model_preview_filters",
    "pits_bom_preview_filters_",
    "legacy_pits_preview_filters",
    "mapped_bom_preview_filters",
    "model_definition_filters_",
    "feature_definition_filters_",
    "complexity_feature_filters_",
    "complexity_tree_filters_",
    "part_catalog_filters_",
    "fishbone_assignment_filters_",
    "assembly_framework_filters_",
)


def _is_product_structure_filter_key(key: str) -> bool:
    key_str = str(key or "").strip()
    return any(key_str.startswith(prefix) for prefix in _PRODUCT_STRUCTURE_FILTER_KEY_PREFIXES)


def clear_saved_table_filters(filter_key: str) -> None:
    """Clear both live and saved filter widget state for a filter_table key prefix."""
    key_str = str(filter_key or "").strip()
    if not key_str:
        return
    st.session_state.pop(f"{key_str}_keyword", None)
    st.session_state.pop(f"_saved_filter_kw_{key_str}", None)
    prefixes = (
        f"{key_str}_",
        f"_saved_filter_col_{key_str}_",
        f"_pending_filter_col_{key_str}_",
    )
    for existing_key in list(st.session_state.keys()):
        existing_str = str(existing_key)
        if existing_str != f"{key_str}_keyword" and any(
            existing_str.startswith(p) for p in prefixes
        ):
            st.session_state.pop(existing_key, None)


def preserve_filters_across_save(
    filter_key: str,
    before_df: pd.DataFrame,
    after_df: pd.DataFrame,
    dropdown_columns: Iterable[str] = (),
    *,
    id_column: str = "id",
    multi_value_columns: Iterable[str] = (),
) -> None:
    """Preserve active filter selections and remap edited filter values across Save & Refresh."""
    key_str = str(filter_key or "").strip()
    if not key_str or not _is_product_structure_filter_key(key_str):
        return
    kw_widget_key = f"{key_str}_keyword"
    saved_kw_key = f"_saved_filter_kw_{key_str}"
    if kw_widget_key in st.session_state:
        st.session_state[saved_kw_key] = str(st.session_state.get(kw_widget_key) or "")

    multi_cols = {str(col) for col in (multi_value_columns or ())}
    has_ids = (
        isinstance(before_df, pd.DataFrame)
        and isinstance(after_df, pd.DataFrame)
        and id_column in before_df.columns
        and id_column in after_df.columns
    )
    for col in dropdown_columns:
        widget_key = f"{key_str}_{col}"
        saved_col_key = f"_saved_filter_col_{widget_key}"
        pending_col_key = f"_pending_filter_col_{widget_key}"
        cur_sel = st.session_state.get(widget_key)
        if cur_sel is None:
            cur_sel = st.session_state.get(saved_col_key)
        if not isinstance(cur_sel, (list, tuple, set)) or not cur_sel:
            continue
        cur_sel_list = list(cur_sel)
        if (
            not has_ids
            or col not in before_df.columns
            or col not in after_df.columns
        ):
            st.session_state[saved_col_key] = cur_sel_list
            continue

        before_by_id = {
            str(rid).strip(): val
            for rid, val in zip(before_df[id_column], before_df[col])
            if rid is not None and not pd.isna(rid) and str(rid).strip()
        }
        after_by_id = {
            str(rid).strip(): val
            for rid, val in zip(after_df[id_column], after_df[col])
            if rid is not None and not pd.isna(rid) and str(rid).strip()
        }

        if col in multi_cols:
            remaining_tokens = {
                tok
                for cell in after_df[col]
                for tok in split_filter_values(cell)
            }
            remapped_tokens: dict[str, list[str]] = {}
            added_tokens: list[str] = []
            for rid, old_cell in before_by_id.items():
                if rid not in after_by_id:
                    continue
                old_toks = split_filter_values(old_cell)
                new_toks = split_filter_values(after_by_id[rid])
                if old_toks != new_toks:
                    for ot in old_toks:
                        if ot in cur_sel_list:
                            for nt in new_toks:
                                if nt:
                                    remapped_tokens.setdefault(ot, []).append(nt)
            for rid, new_cell in after_by_id.items():
                if rid not in before_by_id:
                    for nt in split_filter_values(new_cell):
                        if nt and nt not in cur_sel_list:
                            added_tokens.append(nt)
            next_sel: list[object] = []
            for sel_val in cur_sel_list:
                sel_str = str(sel_val)
                if sel_str in remaining_tokens or sel_str not in remapped_tokens:
                    next_sel.append(sel_val)
                if sel_str in remapped_tokens:
                    next_sel.extend(remapped_tokens[sel_str])
            next_sel.extend(added_tokens)
            next_sel = list(dict.fromkeys(next_sel))
        else:
            remaining_vals = {
                val
                for val in after_df[col].dropna().tolist()
                if val is not None and (isinstance(val, bool) or str(val).strip() != "")
            }
            remapped_vals: dict[object, list[object]] = {}
            added_vals: list[object] = []
            for rid, old_val in before_by_id.items():
                if rid not in after_by_id:
                    continue
                new_val = after_by_id[rid]
                if (
                    old_val in cur_sel_list
                    and new_val != old_val
                    and new_val is not None
                    and (isinstance(new_val, bool) or str(new_val).strip() != "")
                ):
                    remapped_vals.setdefault(old_val, []).append(new_val)
            for rid, new_val in after_by_id.items():
                if (
                    rid not in before_by_id
                    and new_val is not None
                    and (isinstance(new_val, bool) or str(new_val).strip() != "")
                    and new_val not in cur_sel_list
                ):
                    added_vals.append(new_val)
            next_sel = []
            for sel_val in cur_sel_list:
                if sel_val in remaining_vals or sel_val not in remapped_vals:
                    next_sel.append(sel_val)
                if sel_val in remapped_vals:
                    next_sel.extend(remapped_vals[sel_val])
            next_sel.extend(added_vals)
            next_sel = list(dict.fromkeys(next_sel))

        st.session_state[saved_col_key] = list(next_sel)
        if next_sel != cur_sel_list:
            st.session_state[pending_col_key] = list(next_sel)


def filter_table(
    dataframe: pd.DataFrame,
    *,
    key: str,
    dropdown_columns: Iterable[str] = (),
    always_visible_dropdown_columns: Iterable[str] = (),
    dropdown_options: dict[str, Iterable[object]] | None = None,
    search_columns: Iterable[str] | None = None,
    labels: dict[str, str] | None = None,
    reset_widget_keys: Iterable[str] = (),
    multi_value_columns: Iterable[str] = (),
    universal_values: dict[str, Iterable[str]] | None = None,
    keyword_container=None,
    caption_container=None,
) -> pd.DataFrame:
    """Render consistent keyword/dropdown controls and return the visible rows."""
    if dataframe.empty:
        return dataframe.reset_index(drop=True)
    labels = labels or {}
    dropdown_options = dropdown_options or {}
    preserve_for_product_structure = _is_product_structure_filter_key(key)
    always_visible_set = {str(col) for col in (always_visible_dropdown_columns or ())}
    multi_value_columns = set(multi_value_columns)
    universal_values = universal_values or {}
    valid_dropdowns = [column for column in dropdown_columns if column in dataframe.columns]
    controls = st.container(horizontal=True, vertical_alignment="bottom")
    keyword_host = keyword_container if keyword_container is not None else controls
    kw_widget_key = f"{key}_keyword"
    saved_kw_key = f"_saved_filter_kw_{key}"
    if (
        preserve_for_product_structure
        and kw_widget_key not in st.session_state
        and saved_kw_key in st.session_state
    ):
        st.session_state[kw_widget_key] = str(st.session_state.get(saved_kw_key) or "")
    keyword = keyword_host.text_input(
        "Filter by keyword",
        key=f"{key}_keyword",
        placeholder="Search this table",
        icon=":material/search:",
    )
    if preserve_for_product_structure:
        st.session_state[saved_kw_key] = str(keyword or "")
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
            values = sorted(values, key=lambda value: str(value).casefold())
        elif column in dropdown_options:
            explicit_vals = [
                v for v in (dropdown_options.get(column) or ())
                if v is not None and (isinstance(v, bool) or str(v).strip() != "")
            ]
            col_vals = [
                v for v in dataframe[column].dropna().unique().tolist()
                if v is not None and (isinstance(v, bool) or str(v).strip() != "")
            ]
            values = list(dict.fromkeys([*explicit_vals, *col_vals]))
        else:
            values = [
                v for v in dataframe[column].dropna().unique().tolist()
                if v is not None and (isinstance(v, bool) or str(v).strip() != "")
            ]
            values = sorted(values, key=lambda value: str(value).casefold())
        widget_key = f"{key}_{column}"
        saved_col_key = f"_saved_filter_col_{widget_key}"
        pending_col_key = f"_pending_filter_col_{widget_key}"
        if preserve_for_product_structure and pending_col_key in st.session_state:
            st.session_state[widget_key] = list(
                st.session_state.pop(pending_col_key) or []
            )
            st.session_state[saved_col_key] = list(st.session_state[widget_key])
        elif (
            preserve_for_product_structure
            and widget_key not in st.session_state
            and saved_col_key in st.session_state
        ):
            st.session_state[widget_key] = list(st.session_state.get(saved_col_key) or [])
        stored_selection = st.session_state.get(widget_key, [])
        current_selection = stored_selection
        if current_selection is None:
            current_selection = []
        elif not isinstance(current_selection, (list, tuple, set)):
            current_selection = [current_selection]
        if preserve_for_product_structure and column not in dropdown_options:
            for sel_val in current_selection:
                if (
                    sel_val is not None
                    and (isinstance(sel_val, bool) or str(sel_val).strip() != "")
                    and sel_val not in values
                ):
                    values.append(sel_val)
        normalized_selection = [
            value for value in current_selection if value in values
        ]
        if not isinstance(stored_selection, list) or stored_selection != normalized_selection:
            st.session_state[widget_key] = normalized_selection
        dropdown_host = keyword_host if str(column) in always_visible_set else controls
        selected[column] = dropdown_host.multiselect(
            labels.get(column, column.replace("_", " ").capitalize()),
            options=values,
            placeholder="All",
            key=widget_key,
        )

        if preserve_for_product_structure:
            st.session_state[saved_col_key] = list(selected[column] or [])
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
    prev_identity = st.session_state.get(signature_key)
    combined_filter_draft: dict[str, dict[str, Any]] = {}
    if "id" in dataframe.columns and isinstance(prev_identity, tuple) and prev_identity:
        for widget_key in reset_widget_keys:
            logical_widget_key = logical_table_editor_key(widget_key)
            if (
                st.session_state.get(f"_reset_table_editor_{logical_widget_key}")
                and not st.session_state.get(f"_pending_undo_last_edit_{logical_widget_key}")
                and not st.session_state.get(f"_preserve_filter_draft_{logical_widget_key}")
            ):
                st.session_state.pop(f"_table_filter_id_draft_{logical_widget_key}", None)
                continue
            id_draft: dict[str, dict[str, Any]] = deepcopy(
                st.session_state.get(f"_table_filter_id_draft_{logical_widget_key}") or {}
            )
            prior_widget_state = get_effective_table_editor_state(widget_key)
            inst_key = _resolve_editor_instance_key(widget_key)
            authoritative_visible = (
                inst_key in st.session_state
                or bool(st.session_state.get(f"_just_undid_last_edit_{logical_widget_key}"))
            )
            prior_edited = (
                (prior_widget_state.get("edited_rows") or {})
                if isinstance(prior_widget_state, dict)
                else {}
            )
            for old_pos, raw_rid in enumerate(prev_identity):
                rid = str(raw_rid).strip()
                if not rid:
                    continue
                raw_changes = (
                    prior_edited.get(old_pos)
                    if old_pos in prior_edited
                    else prior_edited.get(str(old_pos))
                )
                if isinstance(raw_changes, dict) and raw_changes:
                    id_draft[rid] = deepcopy(dict(raw_changes))
                elif authoritative_visible:
                    id_draft.pop(rid, None)
            if id_draft:
                st.session_state[f"_table_filter_id_draft_{logical_widget_key}"] = id_draft
                for rid_k, chg_v in id_draft.items():
                    if isinstance(chg_v, dict) and chg_v:
                        combined_filter_draft.setdefault(str(rid_k).strip(), {}).update(
                            deepcopy(chg_v)
                        )
            else:
                st.session_state.pop(f"_table_filter_id_draft_{logical_widget_key}", None)
    if prev_identity is None:
        st.session_state[signature_key] = row_identity
    elif prev_identity != row_identity:
        st.session_state[signature_key] = row_identity
        same_visible_id_set = (
            "id" in visible.columns
            and isinstance(prev_identity, tuple)
            and len(prev_identity) == len(row_identity)
            and set(prev_identity) == set(row_identity)
        )
        if not same_visible_id_set:
            new_pos_by_id = (
                {str(rid).strip(): idx for idx, rid in enumerate(row_identity) if str(rid).strip()}
                if "id" in visible.columns
                else {}
            )
            prev_id_set = (
                {str(rid).strip() for rid in prev_identity if str(rid).strip()}
                if isinstance(prev_identity, tuple)
                else set()
            )
            for widget_key in reset_widget_keys:
                logical_widget_key = logical_table_editor_key(widget_key)
                st.session_state.pop(f"_select_all_{logical_widget_key}", None)
                prior_widget_state = get_effective_table_editor_state(widget_key)
                st.session_state.pop(widget_key, None)
                id_draft = (
                    st.session_state.get(f"_table_filter_id_draft_{logical_widget_key}")
                    or {}
                )
                remapped_edited: dict[int, dict[str, Any]] = {}
                if "id" in visible.columns and new_pos_by_id:
                    if isinstance(id_draft, dict) and id_draft:
                        for rid, changes in id_draft.items():
                            new_pos = new_pos_by_id.get(str(rid).strip())
                            if new_pos is not None and isinstance(changes, dict) and changes:
                                remapped_edited[new_pos] = deepcopy(changes)
                    elif (
                        isinstance(prior_widget_state, dict)
                        and prior_widget_state.get("edited_rows")
                        and isinstance(prev_identity, tuple)
                        and prev_identity
                    ):
                        for raw_pos, changes in (prior_widget_state.get("edited_rows") or {}).items():
                            try:
                                old_pos = int(raw_pos)
                            except (TypeError, ValueError):
                                continue
                            if 0 <= old_pos < len(prev_identity) and isinstance(changes, dict) and changes:
                                rid = str(prev_identity[old_pos]).strip()
                                new_pos = new_pos_by_id.get(rid)
                                if new_pos is not None:
                                    remapped_edited[new_pos] = deepcopy(changes)
                remapped_deleted: list[int] = []
                if (
                    isinstance(prior_widget_state, dict)
                    and prior_widget_state.get("deleted_rows")
                    and "id" in visible.columns
                    and isinstance(prev_identity, tuple)
                    and prev_identity
                    and new_pos_by_id
                ):
                    for raw_pos in (prior_widget_state.get("deleted_rows") or []):
                        try:
                            old_pos = int(raw_pos)
                        except (TypeError, ValueError):
                            continue
                        if 0 <= old_pos < len(prev_identity):
                            rid = str(prev_identity[old_pos]).strip()
                            new_pos = new_pos_by_id.get(rid)
                            if new_pos is not None and new_pos not in remapped_deleted:
                                remapped_deleted.append(new_pos)
                remapped_added = (
                    deepcopy(prior_widget_state.get("added_rows") or [])
                    if isinstance(prior_widget_state, dict)
                    else []
                )
                hidden_visible_draft: dict[int, dict[str, Any]] = {}
                if isinstance(id_draft, dict) and id_draft and new_pos_by_id:
                    for rid, changes in id_draft.items():
                        rid_s = str(rid).strip()
                        if rid_s not in prev_id_set and rid_s in new_pos_by_id and isinstance(changes, dict) and changes:
                            hidden_visible_draft[new_pos_by_id[rid_s]] = deepcopy(changes)
                old_history = st.session_state.get(f"_table_undo_history_{logical_widget_key}")
                new_history: list[dict[str, Any]] = [_empty_editor_state()]
                if hidden_visible_draft:
                    new_history.append(
                        {
                            "edited_rows": deepcopy(hidden_visible_draft),
                            "added_rows": [],
                            "deleted_rows": [],
                        }
                    )
                if isinstance(old_history, list) and isinstance(prev_identity, tuple) and prev_identity:
                    for hist_item in old_history:
                        norm_hist = _normalize_editor_state(hist_item)
                        if not _editor_state_has_changes(norm_hist):
                            continue
                        mapped_ed = deepcopy(hidden_visible_draft)
                        for old_pos, ch in (norm_hist.get("edited_rows") or {}).items():
                            if 0 <= int(old_pos) < len(prev_identity) and isinstance(ch, dict) and ch:
                                rid_s = str(prev_identity[int(old_pos)]).strip()
                                np = new_pos_by_id.get(rid_s)
                                if np is not None:
                                    mapped_ed[np] = deepcopy(ch)
                        mapped_del: list[int] = []
                        for old_pos in norm_hist.get("deleted_rows") or []:
                            if 0 <= int(old_pos) < len(prev_identity):
                                rid_s = str(prev_identity[int(old_pos)]).strip()
                                np = new_pos_by_id.get(rid_s)
                                if np is not None and np not in mapped_del:
                                    mapped_del.append(np)
                        mapped_state = {
                            "edited_rows": mapped_ed,
                            "added_rows": deepcopy(norm_hist.get("added_rows") or []),
                            "deleted_rows": mapped_del,
                        }
                        if _editor_state_has_changes(mapped_state) and mapped_state != new_history[-1]:
                            new_history.append(mapped_state)
                if remapped_edited or remapped_deleted or remapped_added:
                    next_seed = {
                        "edited_rows": remapped_edited,
                        "added_rows": remapped_added,
                        "deleted_rows": remapped_deleted,
                    }
                    if new_history[-1] != next_seed:
                        new_history.append(deepcopy(next_seed))
                    st.session_state[f"_table_undo_history_{logical_widget_key}"] = new_history
                    st.session_state.pop(f"_table_redo_history_{logical_widget_key}", None)
                    st.session_state[f"_table_undo_seed_{logical_widget_key}"] = next_seed
                    st.session_state[f"_table_subtab_draft_{logical_widget_key}"] = deepcopy(next_seed)
                    st.session_state[f"_pending_undo_last_edit_{logical_widget_key}"] = True
                else:
                    st.session_state[f"_table_undo_history_{logical_widget_key}"] = [_empty_editor_state()]
                    st.session_state.pop(f"_table_redo_history_{logical_widget_key}", None)
                    st.session_state.pop(f"_table_undo_seed_{logical_widget_key}", None)
                    st.session_state.pop(f"_table_subtab_draft_{logical_widget_key}", None)
                    if id_draft:
                        st.session_state[f"_pending_undo_last_edit_{logical_widget_key}"] = True
                st.session_state[f"_preserve_filter_draft_{logical_widget_key}"] = True
                request_table_editor_reset(widget_key)
    caption_host = caption_container if caption_container is not None else st
    caption_host.caption(f"Showing {len(visible):,} of {len(dataframe):,} rows")
    visible_out = visible.copy().reset_index(drop=True)
    visible_out.attrs["_filter_editor_keys"] = [
        logical_table_editor_key(k) for k in reset_widget_keys
    ]
    if combined_filter_draft:
        visible_out.attrs["_filter_id_draft"] = deepcopy(combined_filter_draft)
    return visible_out


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
    if not hidden.empty:
        combined_draft: dict[str, dict[str, Any]] = {}
        attr_draft = filtered_dataframe.attrs.get("_filter_id_draft")
        if isinstance(attr_draft, dict):
            for rid, chg in attr_draft.items():
                if isinstance(chg, dict):
                    combined_draft.setdefault(str(rid).strip(), {}).update(deepcopy(chg))
        for lk in filtered_dataframe.attrs.get("_filter_editor_keys") or []:
            ss_draft = st.session_state.get(f"_table_filter_id_draft_{lk}")
            if isinstance(ss_draft, dict):
                for rid, chg in ss_draft.items():
                    if isinstance(chg, dict):
                        combined_draft.setdefault(str(rid).strip(), {}).update(deepcopy(chg))
        if combined_draft:
            for h_idx in hidden.index:
                raw_hid = hidden.at[h_idx, id_column]
                hid_str = "" if raw_hid is None or pd.isna(raw_hid) else str(raw_hid).strip()
                if not hid_str and "id" in hidden.columns:
                    raw_id_col = hidden.at[h_idx, "id"]
                    hid_str = "" if raw_id_col is None or pd.isna(raw_id_col) else str(raw_id_col).strip()
                row_patch = combined_draft.get(hid_str)
                if isinstance(row_patch, dict):
                    for col_name, col_val in row_patch.items():
                        if col_name in hidden.columns and col_name not in (id_column, "id", "selected"):
                            try:
                                hidden.at[h_idx, col_name] = col_val
                            except Exception:
                                pass
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
    live_cells_before_draft: dict[str, dict[str, Any]] = {}
    for stable_id, changes in draft_by_id.items():
        sid_str = str(stable_id).strip()
        row_index = row_by_id.get(sid_str)
        if row_index is None:
            continue
        for column, value in (changes or {}).items():
            if column in result.columns and column != id_column:
                live_cells_before_draft.setdefault(sid_str, {})[column] = dataframe.at[row_index, column]
                result.at[row_index, column] = value
    st.session_state["_pending_id_draft_patches"] = deepcopy(draft_by_id)
    st.session_state["_pending_id_draft_live_cells"] = live_cells_before_draft
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
        logical_part, inst_rest = key_str.split(_EDITOR_INSTANCE_MARKER, 1)
        suffix_part = ""
        if "_" in inst_rest:
            _, suf = inst_rest.split("_", 1)
            suffix_part = f"_{suf}"
        gen_key = f"_table_editor_generation_{logical_part}"
        if gen_key in st.session_state:
            gen = int(st.session_state.get(gen_key, 0) or 0)
            rotated = f"{logical_part}{_EDITOR_INSTANCE_MARKER}{gen}{suffix_part}"
            if rotated in st.session_state:
                return rotated
            for existing_key in list(st.session_state.keys()):
                if str(existing_key).startswith(f"{rotated}_"):
                    return str(existing_key)
            return rotated
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
    if (
        instance_key not in st.session_state
        and not _editor_state_has_changes(_normalize_editor_state(seed))
        and not st.session_state.get(f"_just_undid_last_edit_{logical_key}")
    ):
        subtab_draft = st.session_state.get(f"_table_subtab_draft_{logical_key}")
        if _editor_state_has_changes(_normalize_editor_state(subtab_draft)):
            seed = subtab_draft
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


def _sync_filter_id_draft_from_display_df(
    logical_key: str,
    display_df: pd.DataFrame | None,
    edited_rows: dict[Any, Any] | None,
) -> None:
    if not isinstance(display_df, pd.DataFrame) or "id" not in display_df.columns:
        return
    id_draft: dict[str, dict[str, Any]] = deepcopy(
        st.session_state.get(f"_table_filter_id_draft_{logical_key}") or {}
    )
    edited_map = edited_rows if isinstance(edited_rows, dict) else {}
    for pos_i in range(len(display_df)):
        rid_val = display_df.iloc[pos_i].get("id")
        rid_str = "" if rid_val is None or pd.isna(rid_val) else str(rid_val).strip()
        if not rid_str:
            continue
        raw_changes = (
            edited_map.get(pos_i)
            if pos_i in edited_map
            else edited_map.get(str(pos_i))
        )
        if isinstance(raw_changes, dict) and raw_changes:
            id_draft[rid_str] = deepcopy(dict(raw_changes))
        else:
            id_draft.pop(rid_str, None)
    if id_draft:
        st.session_state[f"_table_filter_id_draft_{logical_key}"] = id_draft
    else:
        st.session_state.pop(f"_table_filter_id_draft_{logical_key}", None)


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
    _sync_filter_id_draft_from_display_df(
        logical_key,
        st.session_state.get(f"_table_display_df_{logical_key}"),
        target_state.get("edited_rows"),
    )
    if _editor_state_has_changes(target_state):
        st.session_state[f"_table_undo_seed_{logical_key}"] = deepcopy(target_state)
        st.session_state[f"_table_subtab_draft_{logical_key}"] = deepcopy(target_state)
    else:
        st.session_state.pop(f"_table_undo_seed_{logical_key}", None)
        st.session_state.pop(f"_table_subtab_draft_{logical_key}", None)
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
    _sync_filter_id_draft_from_display_df(
        logical_key,
        st.session_state.get(f"_table_display_df_{logical_key}"),
        target_state.get("edited_rows"),
    )
    if _editor_state_has_changes(target_state):
        st.session_state[f"_table_undo_seed_{logical_key}"] = deepcopy(target_state)
        st.session_state[f"_table_subtab_draft_{logical_key}"] = deepcopy(target_state)
    else:
        st.session_state.pop(f"_table_undo_seed_{logical_key}", None)
        st.session_state.pop(f"_table_subtab_draft_{logical_key}", None)
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


def _editor_state_has_data_changes(state: dict[str, Any] | None) -> bool:
    if not isinstance(state, dict):
        return False
    if state.get("added_rows") or state.get("deleted_rows"):
        return True
    return any(
        any(col != "selected" for col in (changes or {}))
        for changes in (state.get("edited_rows") or {}).values()
    )


def _wrap_data_editor(data, *args, **kwargs):
    key = kwargs.get("key")
    if not key or not isinstance(data, pd.DataFrame):
        return _ORIG_DATA_EDITOR(data, *args, **kwargs)

    key_str = str(key)
    logical_key = logical_table_editor_key(key_str)
    if st.session_state.get(f"_reset_table_editor_{logical_key}"):
        suffix_part = ""
        if _EDITOR_INSTANCE_MARKER in key_str:
            _, inst_rest = key_str.split(_EDITOR_INSTANCE_MARKER, 1)
            if "_" in inst_rest:
                _, suf = inst_rest.split("_", 1)
                suffix_part = f"_{suf}"
        rotated_base = apply_pending_table_editor_reset(logical_key)
        key = f"{rotated_base}{suffix_part}"
        kwargs["key"] = key

    id_draft_patches = st.session_state.pop("_pending_id_draft_patches", None)
    id_draft_live_cells = st.session_state.pop("_pending_id_draft_live_cells", None)
    live_df = data.copy()
    if (
        isinstance(id_draft_live_cells, dict)
        and id_draft_live_cells
        and "id" in live_df.columns
    ):
        row_idx_by_id = {
            str(val).strip(): idx
            for idx, val in live_df["id"].items()
            if val is not None and not pd.isna(val) and str(val).strip()
        }
        for sid_str, col_map in id_draft_live_cells.items():
            r_idx = row_idx_by_id.get(str(sid_str).strip())
            if r_idx is None:
                continue
            for col_name, live_val in (col_map or {}).items():
                if col_name in live_df.columns:
                    try:
                        live_df.at[r_idx, col_name] = live_val
                    except Exception:
                        pass

    base_len = len(data)
    st.session_state[f"_table_undo_base_len_{logical_key}"] = base_len
    seed = _normalize_editor_state(
        st.session_state.get(f"_table_undo_seed_{logical_key}")
    )
    has_seed = _editor_state_has_changes(seed)
    if key not in st.session_state and not has_seed:
        subtab_draft = _normalize_editor_state(
            st.session_state.get(f"_table_subtab_draft_{logical_key}")
        )
        if _editor_state_has_changes(subtab_draft):
            seed = subtab_draft
            has_seed = True
            st.session_state[f"_table_undo_seed_{logical_key}"] = deepcopy(seed)

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
    has_data_edits = (
        _editor_state_has_data_changes(raw_before)
        or _editor_state_has_data_changes(seed)
        or bool(id_draft_patches)
    )
    clean_base_key = f"_table_clean_base_df_{logical_key}"
    if not has_data_edits or clean_base_key not in st.session_state:
        existing_base = st.session_state.get(clean_base_key)
        if (
            not has_data_edits
            and isinstance(existing_base, pd.DataFrame)
            and "id" in existing_base.columns
            and "id" in live_df.columns
            and not existing_base.empty
        ):
            live_ids = set(live_df["id"].dropna().astype(str).str.strip())
            kept_hidden = existing_base[
                ~existing_base["id"].fillna("").astype(str).str.strip().isin(live_ids)
            ].copy()
            st.session_state[clean_base_key] = pd.concat(
                [kept_hidden, live_df.copy()], ignore_index=True, sort=False
            )
        else:
            st.session_state[clean_base_key] = live_df.copy()
    elif (
        isinstance(st.session_state.get(clean_base_key), pd.DataFrame)
        and "id" in st.session_state[clean_base_key].columns
        and "id" in live_df.columns
        and not live_df.empty
    ):
        existing_base = st.session_state[clean_base_key]
        existing_ids = set(existing_base["id"].dropna().astype(str).str.strip())
        new_visible = live_df[
            ~live_df["id"].fillna("").astype(str).str.strip().isin(existing_ids)
        ].copy()
        if not new_visible.empty:
            st.session_state[clean_base_key] = pd.concat(
                [existing_base, new_visible], ignore_index=True, sort=False
            )
    st.session_state[f"_table_live_df_{logical_key}"] = live_df.copy()
    st.session_state[f"_table_id_draft_{logical_key}"] = deepcopy(id_draft_patches or {})

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
            if (
                "id" in frozen_df.columns
                and "id" in display_df.columns
                and frozen_df["id"].fillna("").astype(str).tolist()
                == display_df["id"].fillna("").astype(str).tolist()
            ):
                updated_frozen = display_df.copy()
                if "selected" in frozen_df.columns and "selected" in updated_frozen.columns:
                    updated_frozen["selected"] = frozen_df["selected"].values
                display_df = frozen_df.copy()
            else:
                display_df = frozen_df.copy()
        else:
            st.session_state[frozen_key] = display_df.copy()
    st.session_state[f"_table_display_df_{logical_key}"] = display_df.copy()
    _capture_editor_undo_meta(logical_key, display_df, kwargs.get("column_config"))
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

    if (
        has_data_edits
        and isinstance(result_df, pd.DataFrame)
        and "id" in result_df.columns
        and "id" in live_df.columns
    ):
        eff_state = get_effective_table_editor_state(str(key))
        edited_cols_by_id: dict[str, set[str]] = {}
        for rid_k, chg_map in (id_draft_patches or {}).items():
            if isinstance(chg_map, dict):
                edited_cols_by_id.setdefault(str(rid_k).strip(), set()).update(
                    str(c) for c in chg_map.keys()
                )
        for raw_pos, chg_map in (eff_state.get("edited_rows") or {}).items():
            try:
                pos_i = int(raw_pos)
            except (TypeError, ValueError):
                continue
            if 0 <= pos_i < len(display_df) and isinstance(chg_map, dict):
                rid_val = display_df.iloc[pos_i].get("id")
                rid_str = "" if rid_val is None or pd.isna(rid_val) else str(rid_val).strip()
                if rid_str:
                    edited_cols_by_id.setdefault(rid_str, set()).update(
                        str(c) for c in chg_map.keys()
                    )
        live_by_id: dict[str, pd.Series] = {}
        for _, l_row in live_df.iterrows():
            l_id = l_row.get("id")
            if l_id is not None and not pd.isna(l_id) and str(l_id).strip():
                live_by_id[str(l_id).strip()] = l_row
        for r_idx in result_df.index:
            r_id_val = result_df.at[r_idx, "id"]
            r_id_str = "" if r_id_val is None or pd.isna(r_id_val) else str(r_id_val).strip()
            if not r_id_str or r_id_str.startswith("__draft_new__") or r_id_str not in live_by_id:
                continue
            user_cols = edited_cols_by_id.get(r_id_str, set())
            l_row = live_by_id[r_id_str]
            for col_name in result_df.columns:
                if col_name in ("id", "selected") or col_name in user_cols or col_name not in l_row.index:
                    continue
                try:
                    result_df.at[r_idx, col_name] = l_row[col_name]
                except Exception:
                    pass

    _sync_table_undo_history(str(key))
    effective_after = get_effective_table_editor_state(str(key))
    if (
        has_raw_before
        and isinstance(result_df, pd.DataFrame)
        and "id" in data.columns
        and "id" in result_df.columns
        and not data.empty
        and not result_df.empty
    ):
        edited_by_pos = effective_after.get("edited_rows") or {}
        edited_cols_by_id: dict[str, set[str]] = {}
        base_for_pos = st.session_state.get(frozen_key)
        if isinstance(base_for_pos, pd.DataFrame) and "id" in base_for_pos.columns:
            for raw_pos, changes in edited_by_pos.items():
                try:
                    pos = int(raw_pos)
                except (TypeError, ValueError):
                    continue
                if 0 <= pos < len(base_for_pos) and isinstance(changes, dict):
                    rid = str(base_for_pos.iloc[pos].get("id") or "").strip()
                    if rid:
                        edited_cols_by_id.setdefault(rid, set()).update(
                            str(c) for c in changes.keys()
                        )
        fresh_by_id: dict[str, pd.Series] = {}
        for _, fresh_row in data.iterrows():
            rid = str(fresh_row.get("id") or "").strip()
            if rid and not rid.startswith("__draft_new__"):
                fresh_by_id[rid] = fresh_row
        if fresh_by_id:
            result_df = result_df.copy()
            for r_idx in result_df.index:
                rid = str(result_df.at[r_idx, "id"] or "").strip()
                if not rid or rid not in fresh_by_id:
                    continue
                fresh_row = fresh_by_id[rid]
                touched_cols = edited_cols_by_id.get(rid, set())
                for col in result_df.columns:
                    if col in ("id", "selected") or col in touched_cols or col not in fresh_row.index:
                        continue
                    try:
                        result_df.at[r_idx, col] = fresh_row[col]
                    except Exception:
                        pass
    if _editor_state_has_changes(effective_after):
        st.session_state[f"_table_subtab_draft_{logical_key}"] = deepcopy(effective_after)
    else:
        st.session_state.pop(f"_table_subtab_draft_{logical_key}", None)
    _sync_filter_id_draft_from_display_df(
        logical_key,
        display_df,
        effective_after.get("edited_rows"),
    )
    st.session_state.pop(f"_just_undid_last_edit_{logical_key}", None)
    return result_df


st.data_editor = _wrap_data_editor


def has_unsaved_table_changes(key: str) -> bool:
    """Return whether a data editor currently contains pending cell or row changes."""
    logical_key = logical_table_editor_key(key)
    if (
        st.session_state.get(f"_reset_table_editor_{logical_key}")
        and not st.session_state.get(f"_pending_undo_last_edit_{logical_key}")
        and not st.session_state.get(f"_preserve_filter_draft_{logical_key}")
    ):
        return False
    state = get_effective_table_editor_state(key)
    if state.get("edited_rows") or state.get("added_rows") or state.get("deleted_rows"):
        return True
    filter_draft = st.session_state.get(f"_table_filter_id_draft_{logical_key}")
    return bool(
        isinstance(filter_draft, dict)
        and any(isinstance(changes, dict) and bool(changes) for changes in filter_draft.values())
    )


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
    _sync_filter_id_draft_from_display_df(
        logical_key,
        st.session_state.get(f"_table_display_df_{logical_key}"),
        cleaned_edited,
    )
    has_other_edits = bool(cleaned_edited or cleaned_added)
    if has_other_edits:
        next_seed = {
            "edited_rows": cleaned_edited,
            "added_rows": cleaned_added,
            "deleted_rows": [],
        }
        st.session_state[f"_table_undo_seed_{logical_key}"] = next_seed
        st.session_state[f"_table_subtab_draft_{logical_key}"] = deepcopy(next_seed)
        st.session_state[f"_pending_undo_last_edit_{logical_key}"] = True
    else:
        st.session_state.pop(f"_table_undo_seed_{logical_key}", None)
        st.session_state.pop(f"_table_subtab_draft_{logical_key}", None)
        st.session_state.pop(f"_pending_undo_last_edit_{logical_key}", None)
    st.session_state[f"_preserve_select_all_{logical_key}"] = True
    st.session_state[f"_preserve_filter_draft_{logical_key}"] = True
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
        preserve_filter_draft = bool(
            st.session_state.pop(f"_preserve_filter_draft_{logical_key}", False)
        )
        is_undo_reset = bool(
            st.session_state.pop(f"_pending_undo_last_edit_{logical_key}", False)
        )
        if not preserve_select_all and not is_undo_reset:
            st.session_state.pop(f"_select_all_{logical_key}", None)
        previous_key = f"{logical_key}{_EDITOR_INSTANCE_MARKER}{generation}"
        st.session_state.pop(previous_key, None)
        st.session_state.pop(f"_saved_selectable_df_{previous_key}", None)
        st.session_state.pop(f"_saved_selectable_df_{logical_key}", None)
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
            st.session_state.pop(f"_saved_selectable_df_{suffixed_key}", None)
            st.session_state.pop(f"_table_undo_mutated_obj_id_{suffixed_key}", None)
            st.session_state.pop(f"_table_undo_last_raw_{suffixed_key}", None)
            st.session_state.pop(f"_table_editor_frozen_base_{suffixed_key}", None)
        if is_undo_reset:
            st.session_state[f"_just_undid_last_edit_{logical_key}"] = True
        else:
            st.session_state.pop(f"_table_undo_history_{logical_key}", None)
            st.session_state.pop(f"_table_redo_history_{logical_key}", None)
            st.session_state.pop(f"_table_undo_seed_{logical_key}", None)
            st.session_state.pop(f"_table_subtab_draft_{logical_key}", None)
            st.session_state.pop(f"_just_undid_last_edit_{logical_key}", None)
            st.session_state.pop(f"_table_clean_base_df_{logical_key}", None)
            st.session_state.pop(f"_table_live_df_{logical_key}", None)
            st.session_state.pop(f"_table_display_df_{logical_key}", None)
            st.session_state.pop(f"_table_id_draft_{logical_key}", None)
            if not preserve_filter_draft:
                st.session_state.pop(f"_table_filter_id_draft_{logical_key}", None)
            st.session_state.pop(f"_pending_save_conflict_{logical_key}", None)
            st.session_state.pop(f"_confirm_save_conflict_overwrite_{logical_key}", None)
            st.session_state.pop(f"_confirm_save_conflict_discard_{logical_key}", None)
        generation += 1
        st.session_state[generation_key] = generation
    return f"{logical_key}{_EDITOR_INSTANCE_MARKER}{generation}"


_TABLE_LAYOUT_PRESERVATION_HTML = """<div style="display:none" data-paag-table-layout-keeper="2"></div>
<script>
(function() {
  var SESSION_PREFIX = "paag_table_layout_v2_";
  window.__paagTableLayouts = window.__paagTableLayouts || {};

  function loadSavedLayout(logicalKey) {
    if (!logicalKey) return null;
    if (window.__paagTableLayouts[logicalKey]) {
      return window.__paagTableLayouts[logicalKey];
    }
    try {
      var raw = window.sessionStorage.getItem(SESSION_PREFIX + logicalKey);
      if (raw) {
        var parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object") {
          window.__paagTableLayouts[logicalKey] = parsed;
          return parsed;
        }
      }
    } catch (e) {}
    return null;
  }

  function saveLayout(logicalKey, layout) {
    if (!logicalKey || !layout) return;
    window.__paagTableLayouts[logicalKey] = layout;
    try {
      window.sessionStorage.setItem(SESSION_PREFIX + logicalKey, JSON.stringify(layout));
    } catch (e) {}
  }

  function getActiveFiber(fiber) {
    if (!fiber || !fiber.alternate) return fiber;
    var p = fiber;
    var steps = 0;
    while (p.return && steps < 200) {
      p = p.return;
      steps++;
    }
    if (p && p.stateNode && p.stateNode.current) {
      return p.stateNode.current === p ? fiber : fiber.alternate;
    }
    return fiber;
  }

  function getHookState(h) {
    if (!h) return undefined;
    if (h.queue && "lastRenderedState" in h.queue && h.queue.lastRenderedState !== undefined) {
      return h.queue.lastRenderedState;
    }
    return h.memoizedState;
  }

  function findDataFrameFiber(el) {
    if (!el) return null;
    var keys = Object.keys(el);
    var fKey = null;
    for (var i = 0; i < keys.length; i++) {
      if (keys[i].indexOf("__reactFiber$") === 0) {
        fKey = keys[i];
        break;
      }
    }
    if (!fKey) return null;
    var cur = getActiveFiber(el[fKey]);
    var steps = 0;
    while (cur && steps < 25) {
      var activeCur = getActiveFiber(cur);
      var mp = activeCur.memoizedProps;
      var ms = activeCur.memoizedState;
      if (
        mp &&
        mp.element &&
        typeof mp.element.id === "string" &&
        ms &&
        typeof ms === "object" &&
        "memoizedState" in ms &&
        "next" in ms
      ) {
        return activeCur;
      }
      cur = activeCur.return;
      steps++;
    }
    return null;
  }

  var ALLOWED_TABLE_PREFIXES = [
    "pits_flagged_changes_table_",
    "pits_flagged_downstream_impacts_",
    "pits_import_preview_table",
    "pits_model_preview_table",
    "pits_bom_preview_",
    "pits_bom_issue_preview_",
    "legacy_pits_preview_table",
    "mapped_bom_preview_table",
    "exchange_pits_history_",
    "exchange_pits_bom_history_",
    "exchange_mbom_history_",
    "exchange_parts_import_history_",
    "exchange_bom_history_",
    "exchange_export_history_",
    "model_definitions_editor_",
    "complexity_feature_editor_",
    "complexity_tree_editor_",
    "model_similarity_summary_",
    "model_similarity_pairs_",
    "models_history_",
    "complexity_history_",
    "bom_model_tree_table_",
    "bom_grid_editor_",
    "bom_tree_history_",
    "parts_catalog_editor_",
    "parts_mini_bom_pits_",
    "parts_mini_bom_legacy_",
    "parts_history_table_",
    "parts_fishbone_pool_",
    "fishbone_assignment_editor_",
    "assembly_framework_editor_",
    "fishbone_canvas_sections_table_",
    "fishbone_canvas_assignments_table_",
    "fishbone_framework_history_",
    "fishbone_uses_history_"
  ];

  function extractLogicalKey(rawId) {
    if (!rawId || typeof rawId !== "string") return "";
    var stripped = rawId.replace(/^\\$\\$ID-[^-]+-/, "");
    if (!stripped || stripped === "None") return "";
    return stripped.replace(/__editor_instance_\\d+/, "") || "";
  }

  function isProductStructureTableKey(logicalKey) {
    if (!logicalKey || typeof logicalKey !== "string") return false;
    for (var i = 0; i < ALLOWED_TABLE_PREFIXES.length; i++) {
      if (logicalKey.indexOf(ALLOWED_TABLE_PREFIXES[i]) === 0) {
        return true;
      }
    }
    return false;
  }

  function inspectDataFrameHooks(fiber) {
    var hooks = [];
    var h = fiber ? fiber.memoizedState : null;
    var guard = 0;
    while (h && guard < 150) {
      hooks.push(h);
      h = h.next;
      guard++;
    }

    var configIdx = -1;
    for (var i = 1; i < hooks.length; i++) {
      var cur = hooks[i];
      var prev = hooks[i - 1];
      var isState = Boolean(cur.queue && typeof cur.queue.dispatch === "function");
      var curVal = getHookState(cur);
      if (
        isState &&
        curVal instanceof Map &&
        prev &&
        !prev.queue &&
        Array.isArray(prev.memoizedState) &&
        prev.memoizedState[0] instanceof Map
      ) {
        configIdx = i;
        break;
      }
    }
    if (configIdx < 0) return null;

    var columnOrderHook = null;
    for (var j = configIdx - 1; j >= 0; j--) {
      var hj = hooks[j];
      var hjVal = getHookState(hj);
      if (hj.queue && typeof hj.queue.dispatch === "function" && Array.isArray(hjVal)) {
        columnOrderHook = hj;
        break;
      }
    }
    if (!columnOrderHook) return null;

    var configMapHook = hooks[configIdx];
    var baseConfigMap = hooks[configIdx - 1].memoizedState[0];
    var allColumns = null;
    var sortHook = null;
    var widthsHook = null;

    for (var k = configIdx + 1; k < hooks.length; k++) {
      var hk = hooks[k];
      var hkIsState = Boolean(hk.queue && typeof hk.queue.dispatch === "function");
      var hkVal = getHookState(hk);
      if (
        !allColumns &&
        !hkIsState &&
        Array.isArray(hk.memoizedState) &&
        Array.isArray(hk.memoizedState[0]) &&
        hk.memoizedState[0].length > 0 &&
        hk.memoizedState[0][0] &&
        typeof hk.memoizedState[0][0].id === "string" &&
        "name" in hk.memoizedState[0][0]
      ) {
        allColumns = hk.memoizedState[0];
      }
      if (
        !sortHook &&
        hkIsState &&
        k + 1 < hooks.length &&
        !hooks[k + 1].queue &&
        Array.isArray(hooks[k + 1].memoizedState) &&
        hooks[k + 1].memoizedState[0] instanceof Map &&
        hooks[k + 1].memoizedState[0].size > 0
      ) {
        var firstEntry = hooks[k + 1].memoizedState[0].entries().next().value;
        if (
          firstEntry &&
          typeof firstEntry[0] === "string" &&
          (firstEntry[0].indexOf("_column-") === 0 || firstEntry[0].indexOf("_index-") === 0)
        ) {
          sortHook = hk;
          if (!allColumns) {
            allColumns = Array.from(hooks[k + 1].memoizedState[0].values());
          }
        }
      }
      if (!widthsHook && hkIsState && hkVal instanceof Map) {
        widthsHook = hk;
      }
    }

    var idToName = new Map();
    var nameToId = new Map();
    var currentColumnNames = [];
    if (Array.isArray(allColumns)) {
      for (var cIdx = 0; cIdx < allColumns.length; cIdx++) {
        var colObj = allColumns[cIdx];
        if (colObj && typeof colObj.id === "string") {
          var cName = typeof colObj.name === "string" && colObj.name ? colObj.name : colObj.id;
          idToName.set(colObj.id, cName);
          if (!nameToId.has(cName)) {
            nameToId.set(cName, colObj.id);
          }
          if (cName !== "_index-0" && cName.indexOf("_index-") !== 0) {
            currentColumnNames.push(cName);
          }
        }
      }
    }

    return {
      columnOrderHook: columnOrderHook,
      baseConfigMap: baseConfigMap,
      configMapHook: configMapHook,
      sortHook: sortHook,
      widthsHook: widthsHook,
      idToName: idToName,
      nameToId: nameToId,
      currentColumnNames: currentColumnNames
    };
  }

  function applySavedLayoutToElement(el, saved) {
    if (!el || !saved) return;
    var fiber = findDataFrameFiber(el);
    if (!fiber) return;
    var info = inspectDataFrameHooks(fiber);
    if (!info) return;

    if (Array.isArray(saved.columnOrderNames) && info.columnOrderHook) {
      var nextOrder = [];
      var seenNames = new Set();
      for (var i = 0; i < saved.columnOrderNames.length; i++) {
        var cName = saved.columnOrderNames[i];
        if (cName && cName !== "_index-0" && cName.indexOf("_index-") !== 0 && info.nameToId.has(cName)) {
          nextOrder.push(info.nameToId.get(cName));
          seenNames.add(cName);
        }
      }
      var knownSet = Array.isArray(saved.knownColumnNames) ? new Set(saved.knownColumnNames) : null;
      var serverOrder = (fiber.memoizedProps && fiber.memoizedProps.element && fiber.memoizedProps.element.columnOrder) || [];
      if (knownSet && Array.isArray(serverOrder)) {
        var insertIdx = nextOrder.length;
        for (var k = 0; k < nextOrder.length; k++) {
          var mappedName = info.idToName.get(nextOrder[k]) || nextOrder[k];
          if (typeof mappedName === "string" && mappedName.indexOf("__complexity_tree_spacer_") === 0) {
            insertIdx = k;
            break;
          }
        }
        for (var j = 0; j < serverOrder.length; j++) {
          var sCol = serverOrder[j];
          var sName = info.idToName.get(sCol) || sCol;
          if (!knownSet.has(sName) && !seenNames.has(sName) && info.nameToId.has(sName)) {
            nextOrder.splice(insertIdx, 0, info.nameToId.get(sName));
            insertIdx++;
            seenNames.add(sName);
          }
        }
      }
      var curOrder = getHookState(info.columnOrderHook) || [];
      var curOrderNames = [];
      for (var co = 0; co < curOrder.length; co++) {
        var cm = info.idToName.get(curOrder[co]) || curOrder[co];
        if (cm && cm !== "_index-0" && cm.indexOf("_index-") !== 0) {
          curOrderNames.push(cm);
        }
      }
      var nextOrderNames = nextOrder.map(function(x) { return info.idToName.get(x) || x; });
      if (nextOrder.length > 0) {
        if (fiber.memoizedProps && fiber.memoizedProps.element) {
          try {
            fiber.memoizedProps.element.columnOrder = nextOrder.slice();
          } catch (e) {}
        }
        if (fiber.alternate && fiber.alternate.memoizedProps && fiber.alternate.memoizedProps.element) {
          try {
            fiber.alternate.memoizedProps.element.columnOrder = nextOrder.slice();
          } catch (e) {}
        }
        if (curOrderNames.join("|") !== nextOrderNames.join("|")) {
          info.columnOrderHook.queue.dispatch(nextOrder);
        }
      }
    }

    if (saved.configOverrides && typeof saved.configOverrides === "object" && info.configMapHook) {
      var curConfigMap = getHookState(info.configMapHook);
      var nextConfigMap = new Map(curConfigMap instanceof Map ? curConfigMap : []);
      var configChanged = false;
      var overrideKeys = Object.keys(saved.configOverrides);
      for (var ci = 0; ci < overrideKeys.length; ci++) {
        var colName = overrideKeys[ci];
        var ov = saved.configOverrides[colName];
        if (!ov || typeof ov !== "object") continue;
        var targetId = info.nameToId.get(colName);
        var candidateKeys = [];
        if (targetId) candidateKeys.push(targetId);
        if (nextConfigMap.has(colName) && colName !== targetId) candidateKeys.push(colName);
        for (var ck = 0; ck < candidateKeys.length; ck++) {
          var mapKey = candidateKeys[ck];
          var existing = nextConfigMap.get(mapKey) || {};
          var merged = Object.assign({}, existing, ov);
          if (
            existing.hidden !== merged.hidden ||
            existing.pinned !== merged.pinned ||
            JSON.stringify(existing.type_config || null) !== JSON.stringify(merged.type_config || null)
          ) {
            nextConfigMap.set(mapKey, merged);
            configChanged = true;
          }
        }
      }
      if (configChanged) {
        info.configMapHook.queue.dispatch(nextConfigMap);
      }
    }

    if (saved.columnWidths && typeof saved.columnWidths === "object" && info.widthsHook) {
      var curWidthsMap = getHookState(info.widthsHook);
      var nextWidthsMap = new Map(curWidthsMap instanceof Map ? curWidthsMap : []);
      var widthsChanged = false;
      var widthKeys = Object.keys(saved.columnWidths);
      for (var wi = 0; wi < widthKeys.length; wi++) {
        var wName = widthKeys[wi];
        var wVal = saved.columnWidths[wName];
        var wId = info.nameToId.get(wName);
        if (wId && typeof wVal === "number" && wVal > 0 && nextWidthsMap.get(wId) !== wVal) {
          nextWidthsMap.set(wId, wVal);
          widthsChanged = true;
        }
        if (nextWidthsMap.has(wName) && wName !== wId && typeof wVal === "number" && wVal > 0 && nextWidthsMap.get(wName) !== wVal) {
          nextWidthsMap.set(wName, wVal);
          widthsChanged = true;
        }
      }
      if (widthsChanged) {
        info.widthsHook.queue.dispatch(nextWidthsMap);
      }
    }

    if (info.sortHook && saved.sortState && typeof saved.sortState === "object") {
      var sortColName = saved.sortState.columnName;
      var sortDir = saved.sortState.direction || "asc";
      if (sortColName && info.nameToId.has(sortColName)) {
        var targetSortId = info.nameToId.get(sortColName);
        var curSort = getHookState(info.sortHook);
        if (!curSort || curSort.columnId !== targetSortId || curSort.direction !== sortDir) {
          info.sortHook.queue.dispatch({ columnId: targetSortId, direction: sortDir });
        }
      }
    }

    var scroller = el.querySelector(".dvn-scroller");
    if (scroller) {
      if (typeof saved.scrollLeft === "number" && saved.scrollLeft > 0) {
        scroller.scrollLeft = saved.scrollLeft;
      }
      if (typeof saved.scrollTop === "number" && saved.scrollTop > 0) {
        scroller.scrollTop = saved.scrollTop;
      }
    }
  }

  function captureLayoutFromElement(el, logicalKey, info) {
    var orderRaw = getHookState(info.columnOrderHook) || [];
    var orderNames = [];
    for (var oi = 0; oi < orderRaw.length; oi++) {
      var mapped = info.idToName.get(orderRaw[oi]) || orderRaw[oi];
      if (mapped && mapped !== "_index-0" && mapped.indexOf("_index-") !== 0) {
        orderNames.push(mapped);
      }
    }
    var configOverrides = {};
    var curConfigMap = getHookState(info.configMapHook);
    if (curConfigMap instanceof Map) {
      curConfigMap.forEach(function(v, k) {
        var cName = info.idToName.get(k) || (info.nameToId.has(k) ? k : null);
        if (v && typeof v === "object" && cName) {
          var ov = configOverrides[cName] ? Object.assign({}, configOverrides[cName]) : {};
          if (typeof v.hidden === "boolean") ov.hidden = v.hidden;
          if (typeof v.pinned === "boolean") ov.pinned = v.pinned;
          if (v.type_config !== undefined) ov.type_config = v.type_config;
          if (Object.keys(ov).length > 0) {
            configOverrides[cName] = ov;
          }
        }
      });
    }
    var columnWidths = {};
    var curWidthsMap = info.widthsHook ? getHookState(info.widthsHook) : null;
    if (curWidthsMap instanceof Map) {
      curWidthsMap.forEach(function(w, k) {
        if (typeof w === "number" && w > 0) {
          columnWidths[info.idToName.get(k) || k] = w;
        }
      });
    }
    var sortState = null;
    var curSort = info.sortHook ? getHookState(info.sortHook) : null;
    if (curSort && typeof curSort.columnId === "string") {
      sortState = {
        columnName: info.idToName.get(curSort.columnId) || curSort.columnId,
        direction: curSort.direction || "asc"
      };
    }
    var prev = loadSavedLayout(logicalKey) || {};
    var scroller = el.querySelector(".dvn-scroller");
    var scrollLeft = scroller ? scroller.scrollLeft : (prev.scrollLeft || 0);
    var scrollTop = scroller ? scroller.scrollTop : (prev.scrollTop || 0);

    saveLayout(logicalKey, {
      columnOrderNames: orderNames,
      knownColumnNames: info.currentColumnNames,
      configOverrides: configOverrides,
      columnWidths: columnWidths,
      sortState: sortState,
      scrollLeft: scrollLeft,
      scrollTop: scrollTop
    });
  }

  function syncAllDataFrames() {
    if (!document.querySelector('[data-paag-table-layout-keeper]')) return;
    var frames = document.querySelectorAll('div.stDataFrame[data-testid="stDataFrame"]');
    for (var i = 0; i < frames.length; i++) {
      var el = frames[i];
      var fiber = findDataFrameFiber(el);
      if (!fiber) continue;
      var rawId = fiber.memoizedProps && fiber.memoizedProps.element ? fiber.memoizedProps.element.id : "";
      var logicalKey = extractLogicalKey(rawId);
      if (!logicalKey || !isProductStructureTableKey(logicalKey)) continue;

      if (el.dataset.paagRestoredRawId !== rawId) {
        el.dataset.paagRestoredRawId = rawId;
        el.dataset.paagRestoreTs = String(Date.now());
        var saved = loadSavedLayout(logicalKey);
        if (saved) {
          applySavedLayoutToElement(el, saved);
          (function(targetEl, targetSaved) {
            requestAnimationFrame(function() {
              applySavedLayoutToElement(targetEl, targetSaved);
            });
            setTimeout(function() {
              applySavedLayoutToElement(targetEl, targetSaved);
            }, 50);
            setTimeout(function() {
              applySavedLayoutToElement(targetEl, targetSaved);
            }, 140);
          })(el, saved);
        }
      } else {
        var elapsed = Date.now() - Number(el.dataset.paagRestoreTs || 0);
        if (elapsed >= 180) {
          var info = inspectDataFrameHooks(fiber);
          if (info) {
            captureLayoutFromElement(el, logicalKey, info);
          }
        }
      }
    }
  }

  window.__paagSyncAllDataFrames = syncAllDataFrames;

  if (!window.__paagTableLayoutObserverInstalled) {
    window.__paagTableLayoutObserverInstalled = true;
    var observer = new MutationObserver(function() {
      if (window.__paagSyncAllDataFrames) {
        window.__paagSyncAllDataFrames();
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    document.addEventListener("pointerdown", function() {
      if (window.__paagSyncAllDataFrames) window.__paagSyncAllDataFrames();
    }, true);
    document.addEventListener("pointerup", function() {
      setTimeout(function() {
        if (window.__paagSyncAllDataFrames) window.__paagSyncAllDataFrames();
      }, 30);
    }, true);
    document.addEventListener("click", function() {
      setTimeout(function() {
        if (window.__paagSyncAllDataFrames) window.__paagSyncAllDataFrames();
      }, 30);
    }, true);
    setInterval(function() {
      if (window.__paagSyncAllDataFrames) window.__paagSyncAllDataFrames();
    }, 250);
  }

  syncAllDataFrames();
})();
</script>"""


def mount_table_layout_preservation_script() -> None:
    """Mount the client-side st.data_editor column layout and scroll preservation script."""
    html_fn = getattr(st, "html", None)
    if callable(html_fn):
        html_fn(_TABLE_LAYOUT_PRESERVATION_HTML, unsafe_allow_javascript=True)

