"""Streamlit presentation helpers for the scenario-specific PFMEA Quality tab."""

from __future__ import annotations

import math
from io import BytesIO
from uuid import uuid4

import pandas as pd
import streamlit as st
from openpyxl.styles import Alignment

from utils.pfmea_store import (
    PFMEA_CLASSIFICATIONS,
    PFMEA_RATINGS,
    delete_pfmea_records,
    delete_pfmea_control_options,
    migrate_legacy_pfmea_controls,
    pfmea_actions,
    pfmea_causes,
    pfmea_effects,
    pfmea_entries,
    pfmea_flat_rows,
    pfmea_process_steps,
    pfmea_control_candidates,
    pfmea_control_option_delete_impact,
    pfmea_control_options,
    pfmea_control_selections,
    review_pfmea_sources,
    save_pfmea_action_rows,
    save_pfmea_cause_rows,
    save_pfmea_effect_rows,
    save_pfmea_entry_rows,
    save_pfmea_flat_rows,
    save_pfmea_control_option_rows,
)
from utils.scope_ui import scope_badge
from utils.store import record_audit_event
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
)
from utils.table_ui import (
    dataframe_to_excel,
    direct_entry_editor_rows,
    drop_untouched_new_rows,
    editable_table_footer,
    editable_table_heading,
    native_selected_rows,
    selectable_dataframe,
    stage_native_delete_confirmation,
    table_has_unsaved_changes,
)


PENDING_DELETE_KEY = "pfmea_pending_delete"
PENDING_REVIEW_KEY = "pfmea_pending_source_review"
PENDING_OPTION_DELETE_KEY = "pfmea_pending_option_delete"
PENDING_PROCESS_CHANGE_KEY = "pfmea_pending_process_change"
PENDING_CONTROL_PASTE_KEY = "pfmea_pending_control_paste"

PFMEA_CONTROL_COLUMNS = {
    "prevention_controls": "Prevention",
    "detection_controls": "Detection",
}

PFMEA_COPY_SIGNATURE_COLUMNS = [
    "work_element_id", "potential_failure_mode", "potential_effects", "severity",
    "classification", "potential_causes", "occurrence", "detection",
    "recommended_action", "responsibility_target",
]
PFMEA_COMPLETION_COLUMNS = [
    "actions_taken", "resulting_severity", "resulting_occurrence",
    "resulting_detection", "resulting_rpn",
]
PFMEA_SHARED_EDIT_COLUMNS = {
    "entry_id": ["potential_failure_mode", "classification"],
    "effect_id": ["potential_effects", "severity"],
    "cause_id": ["potential_causes", "occurrence", "detection"],
    "action_id": [
        "recommended_action", "responsibility_target", "actions_taken",
        "resulting_severity", "resulting_occurrence", "resulting_detection",
    ],
}

PFMEA_FLAT_COLUMNS = {
    "id": "string", "entry_id": "string", "effect_id": "string",
    "cause_id": "string", "risk_row_id": "string", "action_id": "string",
    "draft_row_id": "string",
    "work_element_id": "string", "item_number": "string",
    "process_function": "string", "potential_failure_mode": "string",
    "potential_effects": "string", "severity": "float64",
    "classification": "string", "potential_causes": "string",
    "occurrence": "float64", "prevention_controls": "list",
    "detection_controls": "list", "detection": "float64", "rpn": "float64",
    "recommended_action": "string", "responsibility_target": "string",
    "actions_taken": "string", "resulting_severity": "float64",
    "resulting_occurrence": "float64", "resulting_detection": "float64",
    "resulting_rpn": "float64", "upstream_changes": "bool",
    "detection_review_required": "bool",
    "control_source_review_required": "bool",
}

PFMEA_VISIBLE_COLUMNS = [
    "item_number", "process_function", "potential_failure_mode", "potential_effects",
    "severity", "classification", "potential_causes", "occurrence",
    "prevention_controls", "detection_controls", "detection", "rpn",
    "recommended_action", "responsibility_target", "actions_taken",
    "resulting_severity", "resulting_occurrence", "resulting_detection", "resulting_rpn",
]


def _frame(data: pd.DataFrame, columns: dict[str, str]) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame(
            {
                name: pd.Series(dtype="object" if dtype == "list" else dtype)
                for name, dtype in columns.items()
            }
        )
    result = data.copy()
    for name, dtype in columns.items():
        if name not in result:
            result[name] = pd.Series(index=result.index, dtype=dtype)
        if dtype.startswith("float"):
            result[name] = pd.to_numeric(result[name], errors="coerce").astype("float64")
        elif dtype.startswith("int"):
            result[name] = pd.to_numeric(result[name], errors="coerce").fillna(0).astype("int64")
        elif dtype == "bool":
            result[name] = result[name].fillna(False).astype(bool)
        elif dtype.startswith("datetime"):
            result[name] = pd.to_datetime(result[name], errors="coerce")
        elif dtype == "list":
            result[name] = result[name].map(_list_values).astype("object")
        else:
            result[name] = result[name].astype("string")
    return result.reindex(columns=list(columns))


def _list_values(value) -> list[str]:
    if value is None:
        return []
    try:
        if bool(pd.isna(value)):
            return []
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return list(dict.fromkeys(str(item) for item in value if str(item).strip()))
    return [str(value)]


def _rpn_value(severity, occurrence, detection) -> float | None:
    ratings: list[float] = []
    for value in (severity, occurrence, detection):
        try:
            rating = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(rating) or rating <= 0:
            return None
        ratings.append(rating)
    return math.prod(ratings)


def _plain_text(value) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _process_step_option_label(step: dict | pd.Series) -> str:
    """Return the friendly PFMEA selector label without exposing the Process ID."""
    work_element = _plain_text(step.get("work_element")) or "Unnamed Work Element"
    pitch = _plain_text(step.get("pitch")) or "Unassigned"
    sequence = step.get("sequence")
    try:
        sequence_label = str(int(float(sequence)))
    except (TypeError, ValueError):
        sequence_label = _plain_text(sequence) or "0"
    return f"{work_element} — {pitch} — Seq {sequence_label}"


def _resolve_process_step_id(
    value: object, step_by_id: dict[str, dict | pd.Series]
) -> str:
    """Resolve an editor selection to its hidden Process at a Glance row ID."""
    selected = _plain_text(value)
    if selected in step_by_id:
        return selected
    # SelectboxColumn normally returns its option value. Accept its formatted
    # label too so recovery is deterministic for every editor-state payload.
    label_to_id = {
        _process_step_option_label(step): work_element_id
        for work_element_id, step in step_by_id.items()
    }
    return label_to_id.get(selected, "")


def _prepare_pfmea_process_columns(
    rows: pd.DataFrame, step_by_id: dict[str, dict | pd.Series]
) -> pd.DataFrame:
    """Bind Process Function to the hidden Process ID and derive visible Item #."""
    prepared = rows.copy()
    selected_ids = prepared["work_element_id"].map(_plain_text)
    valid_ids = selected_ids.where(selected_ids.isin(step_by_id), "")
    prepared["process_function"] = valid_ids
    prepared["item_number"] = valid_ids.map(
        lambda work_element_id: _plain_text(
            step_by_id.get(work_element_id, {}).get("pitch")
        )
        if work_element_id
        else ""
    )
    return prepared


def _normalize_pfmea_process_selection(
    edited: pd.DataFrame,
    original_editor_rows: pd.DataFrame,
    step_by_id: dict[str, dict | pd.Series],
) -> tuple[pd.DataFrame, bool, bool]:
    """Resolve selector IDs, derive Pitch, and reject saved-row reassignment.

    Streamlit does not support disabling only the saved cells of one data-editor
    column. Saved selections are therefore restored immediately and remain
    protected again by the store-layer relationship validation on save.
    """
    normalized = edited.copy()
    selected_ids = normalized["process_function"].map(
        lambda value: _resolve_process_step_id(value, step_by_id)
    )
    original_ids = original_editor_rows["work_element_id"].map(_plain_text).reindex(
        normalized.index, fill_value=""
    )
    original_selector_ids = original_editor_rows["process_function"].map(
        _plain_text
    ).reindex(normalized.index, fill_value="")
    saved_rows = normalized["id"].map(_plain_text).ne("")
    reassignment_attempted = bool(
        (saved_rows & selected_ids.ne(original_ids)).any()
    )
    effective_ids = selected_ids.where(~saved_rows, original_ids)
    valid_ids = effective_ids.where(effective_ids.isin(step_by_id), "")
    selection_changed = bool(selected_ids.ne(original_selector_ids).any())

    normalized["work_element_id"] = valid_ids
    if "draft_row_id" not in normalized:
        normalized["draft_row_id"] = ""
    draft_ids = normalized["draft_row_id"].map(_plain_text)
    needs_draft_id = ~saved_rows & draft_ids.eq("")
    if needs_draft_id.any():
        normalized.loc[needs_draft_id, "draft_row_id"] = [
            str(uuid4()) for _ in range(int(needs_draft_id.sum()))
        ]
    normalized["item_number"] = valid_ids.map(
        lambda work_element_id: _plain_text(
            step_by_id.get(work_element_id, {}).get("pitch")
        )
        if work_element_id
        else ""
    )
    normalized["process_function"] = valid_ids.map(
        lambda work_element_id: _plain_text(
            step_by_id.get(work_element_id, {}).get("work_element")
        )
        if work_element_id
        else ""
    )
    return normalized, selection_changed, reassignment_attempted


def _editor_rows_from_state(
    source_rows: pd.DataFrame, editor_state: dict
) -> pd.DataFrame:
    """Materialize Streamlit's current editor state for pre-render derivation."""
    current = source_rows.reset_index(drop=True).copy()
    for raw_position, changes in (editor_state.get("edited_rows") or {}).items():
        try:
            position = int(raw_position)
        except (TypeError, ValueError):
            continue
        if not 0 <= position < len(current):
            continue
        for column, value in (changes or {}).items():
            if column in current.columns:
                current.at[position, column] = value
    deleted_positions = {
        int(position)
        for position in (editor_state.get("deleted_rows") or [])
        if str(position).lstrip("-").isdigit()
        and 0 <= int(position) < len(current)
    }
    if deleted_positions:
        current = current.drop(index=sorted(deleted_positions)).reset_index(drop=True)
    added_rows = editor_state.get("added_rows") or []
    if added_rows:
        additions = pd.DataFrame(added_rows).reindex(columns=current.columns)
        current = pd.concat([current, additions], ignore_index=True, sort=False)
    return current


def _process_selection_changed_in_state(editor_state: dict) -> bool:
    return any(
        "process_function" in (changes or {})
        for changes in (editor_state.get("edited_rows") or {}).values()
    ) or any(
        "process_function" in (row or {})
        for row in (editor_state.get("added_rows") or [])
    )


def _control_selection_changed_in_state(editor_state: dict) -> bool:
    return any(
        any(column in PFMEA_CONTROL_COLUMNS for column in (changes or {}))
        for changes in (editor_state.get("edited_rows") or {}).values()
    ) or any(
        any(column in PFMEA_CONTROL_COLUMNS for column in (row or {}))
        for row in (editor_state.get("added_rows") or [])
    )


def _stage_pfmea_process_selection(
    editor_key: str,
    draft_key: str,
    rows: pd.DataFrame,
    visible: pd.DataFrame,
    editor_rows: pd.DataFrame,
    step_by_id: dict[str, dict | pd.Series],
    project_id: str = "",
    scenario_id: str = "",
    control_labels: dict[str, str] | None = None,
) -> None:
    """Resolve Process Function and Item # before the editor's automatic rerun."""
    editor_state = st.session_state.get(editor_key, {}) or {}
    control_labels = control_labels or {}
    process_changed = _process_selection_changed_in_state(editor_state)
    controls_changed = _control_selection_changed_in_state(editor_state)
    if not process_changed and not controls_changed:
        return
    current = _editor_rows_from_state(editor_rows, editor_state)
    normalized, _, reassignment_attempted = _normalize_pfmea_process_selection(
        current, editor_rows, step_by_id
    )
    pending_changes: list[dict] = []
    for raw_position, changes in (editor_state.get("edited_rows") or {}).items():
        if "process_function" not in (changes or {}):
            continue
        try:
            position = int(raw_position)
        except (TypeError, ValueError):
            continue
        if not 0 <= position < min(len(editor_rows), len(normalized)):
            continue
        original = editor_rows.iloc[position]
        proposed = normalized.iloc[position]
        if _plain_text(original.get("id")):
            continue
        old_work_id = _plain_text(original.get("work_element_id"))
        target_work_id = _plain_text(proposed.get("work_element_id"))
        if not old_work_id or not target_work_id or old_work_id == target_work_id:
            continue
        quality_sources = list(
            dict.fromkeys(
                source_key
                for column in ("prevention_controls", "detection_controls")
                for source_key in _list_values(current.iloc[position].get(column))
                if source_key.startswith("quality:")
            )
        )
        if not quality_sources:
            continue
        draft_id = _plain_text(proposed.get("draft_row_id"))
        pending_changes.append(
            {
                "draft_row_id": draft_id,
                "old_work_element_id": old_work_id,
                "target_work_element_id": target_work_id,
                "quality_sources": quality_sources,
                "quality_labels": [
                    control_labels.get(source_key, "Linked Quality requirement")
                    for source_key in quality_sources
                ],
                "detection_quality_removed": any(
                    source_key.startswith("quality:")
                    for source_key in _list_values(
                        current.iloc[position].get("detection_controls")
                    )
                ),
            }
        )
        normalized.at[position, "work_element_id"] = old_work_id
        normalized.at[position, "item_number"] = _plain_text(
            step_by_id.get(old_work_id, {}).get("pitch")
        )
        normalized.at[position, "process_function"] = _plain_text(
            step_by_id.get(old_work_id, {}).get("work_element")
        )
    cleaned = _drop_untouched_rows(
        normalized,
        identifying_columns=[
            "item_number", "potential_failure_mode", "potential_effects", "potential_causes"
        ],
    )
    merged = _merge_pfmea_filtered_edits(rows, visible, cleaned)
    merged, pasted_copy_ids = _recognize_pasted_line_copies(rows, merged)
    if pasted_copy_ids:
        _set_forced_copy_ids(
            project_id,
            scenario_id,
            _forced_copy_ids(project_id, scenario_id) | pasted_copy_ids,
        )
        st.session_state[
            _pfmea_copy_state_key("copy_notice", project_id, scenario_id)
        ] = (
            "Pasted PFMEA line copies keep ordinary editable values but omit Current "
            "Process Controls, Actions Taken, and resulting ratings. Use Duplicate PFMEA "
            "line when structured controls should be carried forward."
        )
    if controls_changed:
        merged, control_pending, warnings, instructions, conflicts = (
            _apply_control_cell_edits(
                rows,
                merged,
                normalized,
                editor_rows,
                editor_state,
                project_id=project_id,
                scenario_id=scenario_id,
                step_by_id=step_by_id,
                control_labels=control_labels,
            )
        )
        if control_pending and pending_changes:
            control_pending = []
            instructions.append(
                "Finish or cancel the pending Process Function change, then paste the "
                "affected controls again."
            )
        warning_key = _pfmea_copy_state_key(
            "control_paste_warning", project_id, scenario_id
        )
        instruction_key = _pfmea_copy_state_key(
            "control_paste_instruction", project_id, scenario_id
        )
        error_key = _pfmea_copy_state_key(
            "control_paste_error", project_id, scenario_id
        )
        if warnings:
            st.session_state[warning_key] = warnings
        else:
            st.session_state.pop(warning_key, None)
        if instructions:
            st.session_state[instruction_key] = instructions
        else:
            st.session_state.pop(instruction_key, None)
        if conflicts:
            st.session_state[error_key] = conflicts
        else:
            st.session_state.pop(error_key, None)
        if control_pending and not st.session_state.get(PENDING_CONTROL_PASTE_KEY):
            if pasted_copy_ids:
                control_pending = [
                    change
                    for change in control_pending
                    if change.get("target_key")
                    not in {f"draft:{draft_id}" for draft_id in pasted_copy_ids}
                ]
        if pasted_copy_ids:
            pasted_mask = merged["draft_row_id"].map(_plain_text).isin(pasted_copy_ids)
            for column in PFMEA_CONTROL_COLUMNS:
                merged.loc[pasted_mask, column] = pd.Series(
                    [[] for _ in range(int(pasted_mask.sum()))],
                    index=merged.index[pasted_mask],
                    dtype="object",
                )
        if control_pending and not st.session_state.get(PENDING_CONTROL_PASTE_KEY):
            st.session_state[PENDING_CONTROL_PASTE_KEY] = {
                "project_id": project_id,
                "scenario_id": scenario_id,
                "draft_key": draft_key,
                "editor_key": editor_key,
                "changes": control_pending,
            }
    st.session_state[draft_key] = merged
    if pending_changes and not st.session_state.get(PENDING_PROCESS_CHANGE_KEY):
        st.session_state[PENDING_PROCESS_CHANGE_KEY] = {
            "project_id": project_id,
            "scenario_id": scenario_id,
            "draft_key": draft_key,
            "editor_key": editor_key,
            "changes": pending_changes,
        }
    if reassignment_attempted:
        st.session_state[f"{draft_key}_locked_notice"] = True
    request_table_editor_reset(editor_key)


def _drop_untouched_rows(data: pd.DataFrame, identifying_columns: list[str]) -> pd.DataFrame:
    """Keep the shared helper's boolean masks stable with Arrow string columns."""
    normalized = data.copy()
    for column in ["id", *identifying_columns]:
        if column in normalized:
            normalized[column] = normalized[column].astype(object)
    return drop_untouched_new_rows(normalized, identifying_columns=identifying_columns)


def _pfmea_row_identity(row: pd.Series) -> str:
    """Return a saved or session-only stable identity for one PFMEA editor row."""
    saved_id = _plain_text(row.get("id"))
    if saved_id:
        return f"saved:{saved_id}"
    draft_id = _plain_text(row.get("draft_row_id"))
    return f"draft:{draft_id}" if draft_id else ""


def _deduplicate_pfmea_draft_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """Recover stale duplicate draft copies created by the former ID-only merge."""
    if rows.empty or "draft_row_id" not in rows:
        return rows.copy()
    identities = rows.apply(_pfmea_row_identity, axis=1)
    duplicate_drafts = identities.str.startswith("draft:") & identities.duplicated(keep="last")
    return rows.loc[~duplicate_drafts].reset_index(drop=True)


def _merge_pfmea_filtered_edits(
    full_dataframe: pd.DataFrame,
    filtered_dataframe: pd.DataFrame,
    edited_dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Merge PFMEA edits using saved IDs or per-row draft IDs.

    The shared merge intentionally keys persisted tables by ``id``. PFMEA adds
    live-derived values to unsaved rows before persistence, so those rows need
    their session-only ``draft_row_id`` to avoid blank-ID collisions.
    """
    if full_dataframe.empty:
        return edited_dataframe.copy().reset_index(drop=True)
    visible_identities = {
        identity
        for identity in filtered_dataframe.apply(_pfmea_row_identity, axis=1)
        if identity
    }
    full_identities = full_dataframe.apply(_pfmea_row_identity, axis=1)
    hidden = full_dataframe.loc[~full_identities.isin(visible_identities)].copy()
    return _deduplicate_pfmea_draft_rows(
        pd.concat([hidden, edited_dataframe], ignore_index=True, sort=False)
    )


def _cell_value(value):
    if isinstance(value, (list, tuple, set)):
        return tuple(_list_values(value))
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _shared_editor_changes(
    editor_rows: pd.DataFrame, editor_state: dict
) -> tuple[dict[tuple[str, str, str], object], list[str]]:
    """Collect non-conflicting edits to normalized records shown on many flat lines."""
    requested: dict[tuple[str, str, str], list[object]] = {}
    column_to_identity = {
        column: identity_column
        for identity_column, columns in PFMEA_SHARED_EDIT_COLUMNS.items()
        for column in columns
    }
    for raw_position, changes in (editor_state.get("edited_rows") or {}).items():
        try:
            position = int(raw_position)
        except (TypeError, ValueError):
            continue
        if not 0 <= position < len(editor_rows):
            continue
        source = editor_rows.iloc[position]
        for column, value in (changes or {}).items():
            identity_column = column_to_identity.get(column)
            if not identity_column:
                continue
            record_id = _plain_text(source.get(identity_column))
            if not record_id:
                continue
            requested.setdefault((identity_column, record_id, column), []).append(value)

    resolved: dict[tuple[str, str, str], object] = {}
    conflicts: list[str] = []
    for key, values in requested.items():
        distinct: list[object] = []
        for value in values:
            if not any(_cell_value(value) == _cell_value(item) for item in distinct):
                distinct.append(value)
        if len(distinct) > 1:
            conflicts.append(key[2])
        else:
            resolved[key] = distinct[0]
    return resolved, sorted(set(conflicts))


def _propagate_shared_editor_changes(
    rows: pd.DataFrame,
    editor_rows: pd.DataFrame,
    editor_state: dict,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    updated = rows.copy()
    changes, conflicts = _shared_editor_changes(editor_rows, editor_state)
    propagated: list[str] = []
    if conflicts:
        return updated, propagated, conflicts
    for (identity_column, record_id, column), value in changes.items():
        mask = updated[identity_column].map(_plain_text).eq(record_id)
        if int(mask.sum()) <= 1:
            continue
        updated.loc[mask, column] = value
        propagated.append(column)
    return updated, sorted(set(propagated)), conflicts


def _copy_signature(row: pd.Series) -> tuple:
    numeric_columns = {"severity", "occurrence", "detection"}
    values: list[object] = []
    for column in PFMEA_COPY_SIGNATURE_COLUMNS:
        value = row.get(column)
        if column not in numeric_columns:
            values.append(_plain_text(value))
            continue
        try:
            numeric = float(value)
            values.append(
                int(numeric) if math.isfinite(numeric) and numeric.is_integer()
                else numeric if math.isfinite(numeric)
                else None
            )
        except (TypeError, ValueError):
            values.append(None)
    return tuple(values)


def _recognize_pasted_line_copies(
    base_rows: pd.DataFrame, edited_rows: pd.DataFrame
) -> tuple[pd.DataFrame, set[str]]:
    """Recognize exact in-grid row copies without persisting copy lineage."""
    updated = edited_rows.copy()
    known_drafts = {
        _plain_text(value)
        for value in base_rows.get("draft_row_id", pd.Series(dtype="string"))
        if _plain_text(value)
    }
    source_signatures = {
        _copy_signature(row)
        for _, row in base_rows.iterrows()
        if _plain_text(row.get("work_element_id"))
    }
    copied_ids: set[str] = set()
    for index, row in updated.iterrows():
        draft_id = _plain_text(row.get("draft_row_id"))
        if (
            _plain_text(row.get("id"))
            or not draft_id
            or draft_id in known_drafts
            or _copy_signature(row) not in source_signatures
        ):
            continue
        updated.at[index, "prevention_controls"] = []
        updated.at[index, "detection_controls"] = []
        for column in PFMEA_COMPLETION_COLUMNS:
            updated.at[index, column] = None if column != "actions_taken" else ""
        copied_ids.add(draft_id)
    return _recalculate_flat_rpn(updated), copied_ids


def _valid_controls_for_step(
    project_id: str,
    scenario_id: str,
    work_element_id: str,
    control_type: str,
    source_keys: list[str],
) -> tuple[list[str], list[str]]:
    requested = _list_values(source_keys)
    if not requested:
        return [], []
    candidates = pfmea_control_candidates(
        project_id,
        scenario_id,
        work_element_id,
        control_type,
        requested,
    )
    candidate_by_key = {
        str(row["source_key"]): row for _, row in candidates.iterrows()
    }
    kept: list[str] = []
    omitted: list[str] = []
    for source_key in requested:
        candidate = candidate_by_key.get(source_key)
        if candidate is None or not bool(candidate.get("active", False)):
            omitted.append(source_key)
        else:
            kept.append(source_key)
    return kept, omitted


def _control_editor_requests(
    normalized_rows: pd.DataFrame,
    editor_rows: pd.DataFrame,
    editor_state: dict,
) -> tuple[dict[tuple[str, str], dict], list[str]]:
    """Collect one non-conflicting control replacement per Cause or draft row."""
    raw_requests: dict[tuple[str, str], list[dict]] = {}

    def collect(position: int, changes: dict) -> None:
        if not 0 <= position < len(normalized_rows):
            return
        row = normalized_rows.iloc[position]
        target_key = _cause_target_key(row)
        if not target_key or target_key == "draft:":
            return
        for column, value in (changes or {}).items():
            if column not in PFMEA_CONTROL_COLUMNS:
                continue
            raw_requests.setdefault((target_key, column), []).append(
                {
                    "row": row,
                    "requested": _list_values(value),
                }
            )

    for raw_position, changes in (editor_state.get("edited_rows") or {}).items():
        try:
            position = int(raw_position)
        except (TypeError, ValueError):
            continue
        collect(position, changes or {})
    for offset, changes in enumerate(editor_state.get("added_rows") or []):
        collect(len(editor_rows) + offset, changes or {})

    resolved: dict[tuple[str, str], dict] = {}
    conflicts: list[str] = []
    for key, requests in raw_requests.items():
        distinct: list[list[str]] = []
        for request in requests:
            values = request["requested"]
            if values not in distinct:
                distinct.append(values)
        if len(distinct) > 1:
            conflicts.append(PFMEA_CONTROL_COLUMNS[key[1]])
            continue
        resolved[key] = requests[-1]
    return resolved, sorted(set(conflicts))


def _control_target_mask(rows: pd.DataFrame, target_key: str) -> pd.Series:
    return rows.apply(lambda row: _cause_target_key(row) == target_key, axis=1)


def _control_target_value(
    rows: pd.DataFrame, target_key: str, column: str
) -> list[str]:
    if rows.empty:
        return []
    mask = _control_target_mask(rows, target_key)
    if not bool(mask.any()):
        return []
    return _list_values(rows.loc[mask, column].iloc[0])


def _apply_control_cell_edits(
    base_rows: pd.DataFrame,
    merged_rows: pd.DataFrame,
    normalized_rows: pd.DataFrame,
    editor_rows: pd.DataFrame,
    editor_state: dict,
    *,
    project_id: str,
    scenario_id: str,
    step_by_id: dict[str, dict | pd.Series],
    control_labels: dict[str, str],
) -> tuple[pd.DataFrame, list[dict], list[str], list[str], list[str]]:
    """Validate and stage native control-cell replacements without writing data."""
    updated = merged_rows.copy()
    requests, conflicts = _control_editor_requests(
        normalized_rows, editor_rows, editor_state
    )
    if conflicts:
        return updated, [], [], [], conflicts

    pending: list[dict] = []
    warnings: list[str] = []
    instructions: list[str] = []
    for (target_key, column), request in requests.items():
        row = request["row"]
        requested = _list_values(request["requested"])
        original = _control_target_value(base_rows, target_key, column)
        target_mask = _control_target_mask(updated, target_key)
        if not bool(target_mask.any()):
            continue
        work_element_id = _plain_text(row.get("work_element_id"))
        line_label = _pfmea_line_label(row, step_by_id)
        if not work_element_id:
            updated.loc[target_mask, column] = pd.Series(
                [original] * int(target_mask.sum()),
                index=updated.index[target_mask],
                dtype="object",
            )
            instructions.append(
                f"Choose Process Function before pasting controls into {line_label}."
            )
            continue

        control_type = PFMEA_CONTROL_COLUMNS[column]
        try:
            compatible, omitted = _valid_controls_for_step(
                project_id,
                scenario_id,
                work_element_id,
                control_type,
                requested,
            )
        except ValueError:
            updated.loc[target_mask, column] = pd.Series(
                [original] * int(target_mask.sum()),
                index=updated.index[target_mask],
                dtype="object",
            )
            instructions.append(
                f"The Process Function or active scenario changed for {line_label}. "
                "Refresh and paste the controls again."
            )
            continue
        incompatible_quality = [
            source_key for source_key in omitted if source_key.startswith("quality:")
        ]
        unavailable_manual = [
            source_key for source_key in omitted if not source_key.startswith("quality:")
        ]
        if unavailable_manual:
            warnings.append(
                f"{line_label}: omitted unavailable or inactive {control_type} controls: "
                + "; ".join(
                    control_labels.get(source_key, "Unavailable control")
                    for source_key in unavailable_manual
                )
            )

        replacement = compatible
        if incompatible_quality:
            replacement = compatible if compatible else original
            updated.loc[target_mask, column] = pd.Series(
                [original] * int(target_mask.sum()),
                index=updated.index[target_mask],
                dtype="object",
            )
            pending.append(
                {
                    "target_key": target_key,
                    "column": column,
                    "control_type": control_type,
                    "line_label": line_label,
                    "original": original,
                    "replacement": replacement,
                    "incompatible_labels": [
                        control_labels.get(source_key, "Linked Quality requirement")
                        for source_key in incompatible_quality
                    ],
                }
            )
            continue

        updated.loc[target_mask, column] = pd.Series(
            [replacement] * int(target_mask.sum()),
            index=updated.index[target_mask],
            dtype="object",
        )
        if column == "detection_controls" and replacement != original:
            updated.loc[target_mask, "detection_review_required"] = True
    return updated, pending, warnings, instructions, []


def _duplicate_pfmea_line(
    source: pd.Series,
    project_id: str,
    scenario_id: str,
) -> tuple[pd.Series, list[str]]:
    duplicate = source.copy()
    duplicate["id"] = ""
    for column in ("entry_id", "effect_id", "cause_id", "risk_row_id", "action_id"):
        duplicate[column] = ""
    duplicate["draft_row_id"] = str(uuid4())
    omitted: list[str] = []
    for control_type, column in (
        ("Prevention", "prevention_controls"),
        ("Detection", "detection_controls"),
    ):
        kept, missing = _valid_controls_for_step(
            project_id,
            scenario_id,
            _plain_text(source.get("work_element_id")),
            control_type,
            _list_values(source.get(column)),
        )
        duplicate[column] = kept
        omitted.extend(missing)
    duplicate["actions_taken"] = ""
    for column in (
        "resulting_severity", "resulting_occurrence", "resulting_detection",
        "resulting_rpn",
    ):
        duplicate[column] = None
    duplicate["upstream_changes"] = False
    duplicate["detection_review_required"] = False
    duplicate["control_source_review_required"] = False
    duplicate["rpn"] = _rpn_value(
        duplicate.get("severity"), duplicate.get("occurrence"), duplicate.get("detection")
    )
    return duplicate, omitted


def _initial_rpn_preview(effects: pd.DataFrame, causes: pd.DataFrame) -> pd.DataFrame:
    columns = {
        "effect_description": "string",
        "severity": "float64",
        "cause_description": "string",
        "occurrence": "float64",
        "detection": "float64",
        "detection_review_required": "bool",
        "rpn": "float64",
    }
    preview: list[dict] = []
    for _, effect in effects.iterrows():
        if not _plain_text(effect.get("effect_description")):
            continue
        for _, cause in causes.iterrows():
            if not _plain_text(cause.get("cause_description")):
                continue
            preview.append(
                {
                    "effect_description": effect.get("effect_description"),
                    "severity": effect.get("severity"),
                    "cause_description": cause.get("cause_description"),
                    "occurrence": cause.get("occurrence"),
                    "detection": cause.get("detection"),
                    "detection_review_required": bool(
                        cause.get("detection_review_required", False)
                    ),
                    "rpn": _rpn_value(
                        effect.get("severity"),
                        cause.get("occurrence"),
                        cause.get("detection"),
                    ),
                }
            )
    return _frame(pd.DataFrame(preview), columns)


def _resulting_rpn_preview(actions: pd.DataFrame) -> pd.DataFrame:
    columns = {
        "recommended_action": "string",
        "resulting_severity": "float64",
        "resulting_occurrence": "float64",
        "resulting_detection": "float64",
        "resulting_rpn": "float64",
    }
    preview: list[dict] = []
    for _, action in actions.iterrows():
        description = _plain_text(action.get("recommended_action"))
        if not description:
            continue
        preview.append(
            {
                "recommended_action": description,
                "resulting_severity": action.get("resulting_severity"),
                "resulting_occurrence": action.get("resulting_occurrence"),
                "resulting_detection": action.get("resulting_detection"),
                "resulting_rpn": _rpn_value(
                    action.get("resulting_severity"),
                    action.get("resulting_occurrence"),
                    action.get("resulting_detection"),
                ),
            }
        )
    return _frame(pd.DataFrame(preview), columns)


def _audit(project_id: str, action: str, result: dict, details: dict) -> None:
    record_audit_event(
        project_id,
        "PFMEA",
        action,
        int(result.get("row_count", 0)),
        st.session_state.get("current_editor", ""),
        details | {"store_timestamp": result.get("timestamp", "")},
    )


def _undo(editor_key: str, message: str) -> None:
    request_table_editor_reset(editor_key)
    st.toast(message, icon=":material/undo:")
    st.rerun()


def _clear_control_picker_state(project_id: str, scenario_id: str) -> None:
    prefixes = (
        f"pfmea_prevention_picker_{project_id}_{scenario_id}_",
        f"pfmea_detection_picker_{project_id}_{scenario_id}_",
    )
    for key in list(st.session_state):
        if any(str(key).startswith(prefix) for prefix in prefixes):
            st.session_state.pop(key, None)


def _pfmea_copy_state_key(kind: str, project_id: str, scenario_id: str) -> str:
    return f"pfmea_{kind}_{project_id}_{scenario_id}"


def _forced_copy_ids(project_id: str, scenario_id: str) -> set[str]:
    key = _pfmea_copy_state_key("force_new_drafts", project_id, scenario_id)
    return {
        _plain_text(value)
        for value in st.session_state.get(key, set())
        if _plain_text(value)
    }


def _set_forced_copy_ids(
    project_id: str, scenario_id: str, draft_ids: set[str]
) -> None:
    key = _pfmea_copy_state_key("force_new_drafts", project_id, scenario_id)
    if draft_ids:
        st.session_state[key] = set(draft_ids)
    else:
        st.session_state.pop(key, None)


def _clear_pfmea_copy_state(project_id: str, scenario_id: str) -> None:
    for kind in (
        "force_new_drafts", "copy_notice", "shared_edit_notice", "shared_edit_error",
        "control_paste_warning", "control_paste_instruction", "control_paste_error",
    ):
        st.session_state.pop(_pfmea_copy_state_key(kind, project_id, scenario_id), None)
    pending = st.session_state.get(PENDING_PROCESS_CHANGE_KEY) or {}
    if (
        str(pending.get("project_id") or "") == project_id
        and str(pending.get("scenario_id") or "") == scenario_id
    ):
        st.session_state.pop(PENDING_PROCESS_CHANGE_KEY, None)
    pending_paste = st.session_state.get(PENDING_CONTROL_PASTE_KEY) or {}
    if (
        str(pending_paste.get("project_id") or "") == project_id
        and str(pending_paste.get("scenario_id") or "") == scenario_id
    ):
        st.session_state.pop(PENDING_CONTROL_PASTE_KEY, None)


def _stage_delete(
    selected: pd.DataFrame,
    *,
    editor_key: str,
    project_id: str,
    scenario_id: str,
    table: str,
    record_label: str,
    display_column: str,
    selected_labels: list[str] | None = None,
    impact_message: str = "",
) -> None:
    if selected.empty or st.session_state.get(PENDING_DELETE_KEY):
        return
    st.session_state[PENDING_DELETE_KEY] = {
        "project_id": project_id,
        "scenario_id": scenario_id,
        "table": table,
        "record_label": record_label,
        "record_ids": selected["id"].astype(str).tolist(),
        "labels": (
            list(selected_labels)
            if selected_labels is not None
            else selected[display_column].fillna("").astype(str).tolist()
        ),
        "impact_message": impact_message,
        "editor_key": editor_key,
    }
    stage_native_delete_confirmation(editor_key)


@st.dialog("Delete selected PFMEA records?", dismissible=False)
def _confirm_pfmea_delete() -> None:
    pending = st.session_state.get(PENDING_DELETE_KEY) or {}
    scenario_changed = str(st.session_state.get("scenario_id") or "") != str(
        pending.get("scenario_id") or ""
    )
    labels = list(pending.get("labels") or [])
    record_label = str(pending.get("record_label") or "PFMEA record")
    impact_message = str(pending.get("impact_message") or "").strip()
    st.warning(
        f"Delete {len(labels)} selected {record_label}(s)? "
        + (
            impact_message
            if impact_message
            else (
                "Related PFMEA child records will be removed with their parent. "
                "Process at a Glance and Quality records remain unchanged."
            )
        )
    )
    for label in labels:
        st.write(f"- {label}")
    if scenario_changed:
        st.error("The active scenario changed. Cancel and select the PFMEA records again.")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_pfmea_delete"):
        editor_key = str(pending.get("editor_key") or "")
        st.session_state.pop(PENDING_DELETE_KEY, None)
        if editor_key:
            request_table_editor_reset(editor_key)
        st.rerun()
    if actions.button(
        "Delete",
        type="primary",
        icon=":material/delete:",
        disabled=scenario_changed,
        key="destructive_confirm_pfmea_delete",
    ):
        try:
            count = delete_pfmea_records(
                str(pending["project_id"]),
                str(pending["scenario_id"]),
                str(pending["table"]),
                list(pending["record_ids"]),
            )
            record_audit_event(
                str(pending["project_id"]),
                "PFMEA",
                "Bulk delete",
                count,
                st.session_state.get("current_editor", ""),
                {
                    "scenario_id": pending["scenario_id"],
                    "record_type": pending["table"],
                    "record_ids": pending["record_ids"],
                },
            )
            editor_key = str(pending.get("editor_key") or "")
            st.session_state.pop(PENDING_DELETE_KEY, None)
            if editor_key:
                request_table_editor_reset(editor_key)
            st.toast(f"Deleted {count} PFMEA record(s)", icon=":material/delete:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Review current Process and Quality sources?", dismissible=False)
def _confirm_source_review() -> None:
    pending = st.session_state.get(PENDING_REVIEW_KEY) or {}
    scenario_changed = str(st.session_state.get("scenario_id") or "") != str(
        pending.get("scenario_id") or ""
    )
    st.warning(
        "Accept the current Process at a Glance fields as the reviewed PFMEA source? "
        "Existing PFMEA failure modes, effects, causes, controls, ratings, classifications, "
        "and actions are preserved."
    )
    if scenario_changed:
        st.error("The active scenario changed. Cancel and select the PFMEA entry again.")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_pfmea_source_review"):
        st.session_state.pop(PENDING_REVIEW_KEY, None)
        st.rerun()
    if actions.button(
        "Accept current sources",
        type="primary",
        icon=":material/fact_check:",
        disabled=scenario_changed,
        key="confirm_pfmea_source_review",
    ):
        try:
            result = review_pfmea_sources(
                str(pending["project_id"]),
                str(pending["scenario_id"]),
                str(pending["entry_id"]),
            )
            _audit(
                str(pending["project_id"]),
                "Review upstream sources",
                result,
                {"scenario_id": pending["scenario_id"], "pfmea_entry_id": pending["entry_id"]},
            )
            st.session_state.pop(PENDING_REVIEW_KEY, None)
            st.toast("Accepted the current PFMEA source evidence", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Change Process Function?", dismissible=False)
def _confirm_pfmea_process_change() -> None:
    pending = st.session_state.get(PENDING_PROCESS_CHANGE_KEY) or {}
    project_id = str(pending.get("project_id") or "")
    scenario_id = str(pending.get("scenario_id") or "")
    scenario_changed = (
        str(st.session_state.get("project_id") or "") != project_id
        or str(st.session_state.get("scenario_id") or "") != scenario_id
    )
    changes = list(pending.get("changes") or [])
    st.warning(
        "Changing Process Function removes the listed Quality-sourced Current Process "
        "Controls because those requirements belong to the previous Process step. "
        "Active manual controls and the Detection rating are preserved."
    )
    for change in changes:
        for label in change.get("quality_labels") or []:
            st.write(f"- {label}")
    if scenario_changed:
        st.error("The active project or scenario changed. Cancel and make the selection again.")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_pfmea_process_change"):
        st.session_state.pop(PENDING_PROCESS_CHANGE_KEY, None)
        editor_key = str(pending.get("editor_key") or "")
        if editor_key:
            request_table_editor_reset(editor_key)
        st.rerun()
    if actions.button(
        "Change Process Function",
        type="primary",
        icon=":material/swap_horiz:",
        disabled=scenario_changed,
        key="destructive_confirm_pfmea_process_change",
    ):
        draft_key = str(pending.get("draft_key") or "")
        draft = st.session_state.get(draft_key)
        if not isinstance(draft, pd.DataFrame):
            st.error("The PFMEA draft changed. Cancel and select the Process Function again.")
            return
        steps = pfmea_process_steps(project_id, scenario_id)
        step_by_id = {str(row["id"]): row for _, row in steps.iterrows()}
        updated = draft.copy()
        for change in changes:
            draft_id = str(change.get("draft_row_id") or "")
            target_work_id = str(change.get("target_work_element_id") or "")
            target = step_by_id.get(target_work_id)
            mask = updated["draft_row_id"].map(_plain_text).eq(draft_id)
            if target is None or int(mask.sum()) != 1:
                st.error(
                    "The PFMEA draft or target Process Function changed. "
                    "Cancel and make the selection again."
                )
                return
            updated.loc[mask, "work_element_id"] = target_work_id
            updated.loc[mask, "item_number"] = _plain_text(target.get("pitch"))
            updated.loc[mask, "process_function"] = _plain_text(target.get("work_element"))
            for column in ("prevention_controls", "detection_controls"):
                current = _list_values(updated.loc[mask, column].iloc[0])
                retained = [value for value in current if not value.startswith("quality:")]
                updated.loc[mask, column] = pd.Series(
                    [retained], index=updated.index[mask], dtype="object"
                )
            updated.loc[mask, "control_source_review_required"] = True
            if bool(change.get("detection_quality_removed")):
                updated.loc[mask, "detection_review_required"] = True
        st.session_state[draft_key] = _recalculate_flat_rpn(updated)
        st.session_state.pop(PENDING_PROCESS_CHANGE_KEY, None)
        editor_key = str(pending.get("editor_key") or "")
        if editor_key:
            request_table_editor_reset(editor_key)
        st.toast(
            "Changed Process Function and removed incompatible Quality controls",
            icon=":material/check_circle:",
        )
        st.rerun()


@st.dialog("Paste compatible controls?", dismissible=False)
def _confirm_pfmea_control_paste() -> None:
    pending = st.session_state.get(PENDING_CONTROL_PASTE_KEY) or {}
    project_id = str(pending.get("project_id") or "")
    scenario_id = str(pending.get("scenario_id") or "")
    scenario_changed = (
        str(st.session_state.get("project_id") or "") != project_id
        or str(st.session_state.get("scenario_id") or "") != scenario_id
    )
    changes = list(pending.get("changes") or [])
    st.warning(
        "Some pasted Quality controls belong to a different Process Function. "
        "They cannot be copied to the affected PFMEA Cause."
    )
    for change in changes:
        st.markdown(
            f"**{change.get('line_label') or 'PFMEA Cause'} — "
            f"{change.get('control_type') or 'Current Process Controls'}**"
        )
        for label in change.get("incompatible_labels") or []:
            st.write(f"- {label}")
        replacement = _list_values(change.get("replacement"))
        original = _list_values(change.get("original"))
        if replacement == original:
            st.caption(
                "No compatible pasted controls remain, so this cell will stay unchanged."
            )
    if scenario_changed:
        st.error(
            "The active project or scenario changed. Cancel and paste the controls again."
        )
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_pfmea_control_paste"):
        st.session_state.pop(PENDING_CONTROL_PASTE_KEY, None)
        editor_key = str(pending.get("editor_key") or "")
        if editor_key:
            request_table_editor_reset(editor_key)
        st.rerun()
    if actions.button(
        "Paste compatible controls",
        type="primary",
        icon=":material/content_paste:",
        disabled=scenario_changed,
        key="confirm_pfmea_control_paste",
    ):
        draft_key = str(pending.get("draft_key") or "")
        draft = st.session_state.get(draft_key)
        if not isinstance(draft, pd.DataFrame):
            st.error("The PFMEA draft changed. Cancel and paste the controls again.")
            return
        updated = draft.copy()
        for change in changes:
            target_key = str(change.get("target_key") or "")
            column = str(change.get("column") or "")
            if column not in PFMEA_CONTROL_COLUMNS:
                st.error("The pending PFMEA control paste is no longer valid.")
                return
            target_mask = _control_target_mask(updated, target_key)
            if not bool(target_mask.any()):
                st.error(
                    "An affected PFMEA Cause changed. Cancel and paste the controls again."
                )
                return
            replacement = _list_values(change.get("replacement"))
            original = _list_values(change.get("original"))
            if replacement == original:
                continue
            updated.loc[target_mask, column] = pd.Series(
                [replacement] * int(target_mask.sum()),
                index=updated.index[target_mask],
                dtype="object",
            )
            if column == "detection_controls":
                updated.loc[target_mask, "detection_review_required"] = True
        st.session_state[draft_key] = updated
        st.session_state.pop(PENDING_CONTROL_PASTE_KEY, None)
        editor_key = str(pending.get("editor_key") or "")
        if editor_key:
            request_table_editor_reset(editor_key)
        st.rerun()


@st.dialog("Delete selected PFMEA control options?", dismissible=False)
def _confirm_control_option_delete() -> None:
    pending = st.session_state.get(PENDING_OPTION_DELETE_KEY) or {}
    control_type = str(pending.get("control_type") or "Control")
    impact = pending.get("impact") or {}
    st.warning(
        f"Delete {impact.get('option_count', 0)} selected {control_type} option(s)? "
        f"This removes {impact.get('selection_count', 0)} PFMEA selection(s) across "
        f"{impact.get('scenario_count', 0)} scenario(s) and marks "
        f"{impact.get('cause_count', 0)} affected Cause(s) for review."
    )
    for label in impact.get("labels", []):
        st.write(f"- {label}")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_pfmea_control_option_delete"):
        editor_key = str(pending.get("editor_key") or "")
        st.session_state.pop(PENDING_OPTION_DELETE_KEY, None)
        if editor_key:
            request_table_editor_reset(editor_key)
        st.rerun()
    if actions.button(
        "Delete",
        type="primary",
        icon=":material/delete:",
        key="destructive_confirm_pfmea_control_option_delete",
    ):
        try:
            result = delete_pfmea_control_options(
                str(pending["project_id"]), control_type, list(pending["option_ids"])
            )
            _audit(
                str(pending["project_id"]),
                f"Delete {control_type} control options",
                result,
                {"record_ids": pending["option_ids"], "cascade_impact": impact},
            )
            editor_key = str(pending.get("editor_key") or "")
            st.session_state.pop(PENDING_OPTION_DELETE_KEY, None)
            if editor_key:
                request_table_editor_reset(editor_key)
            st.toast(f"Deleted {result['row_count']} {control_type} option(s)", icon=":material/delete:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def _render_control_catalog(project_id: str, control_type: str) -> None:
    raw = pfmea_control_options(project_id, control_type)
    columns = {
        "id": "string", "label": "string", "active": "bool",
        "selection_count": "int64", "created_at": "string", "updated_at": "string",
    }
    stored = _frame(raw, columns)
    logical_key = f"pfmea_{control_type.casefold()}_options_editor_{project_id}"
    editor_key = apply_pending_table_editor_reset(logical_key)
    visible = filter_table(
        stored,
        key=f"pfmea_{control_type.casefold()}_options_filters_{project_id}",
        dropdown_columns=["active"],
        search_columns=["label"],
        labels={"label": "Label", "active": "Active"},
        reset_widget_keys=[editor_key],
    )
    editor_rows = direct_entry_editor_rows(
        visible,
        editor_key=editor_key,
        sort_columns=["label"],
        labels={"label": "Label"},
    )
    new_option_rows = editor_rows["id"].fillna("").astype(str).str.strip().eq("")
    editor_rows.loc[new_option_rows, "active"] = True
    edited = st.data_editor(
        editor_rows,
        key=editor_key,
        num_rows="dynamic",
        hide_index=True,
        column_order=["label", "active", "selection_count"],
        disabled=["selection_count"],
        column_config={
            "id": None, "created_at": None, "updated_at": None,
            "label": st.column_config.TextColumn("Label", required=True),
            "active": st.column_config.CheckboxColumn(
                "Active", help="Inactive options stay on saved PFMEA Causes but cannot be newly selected."
            ),
            "selection_count": st.column_config.NumberColumn("PFMEA selections", disabled=True),
        },
    )
    cleaned = _drop_untouched_rows(edited, identifying_columns=["label"])
    complete = merge_filtered_edits(stored, visible, cleaned)
    footer = editable_table_footer(
        editor_key=editor_key,
        key_prefix=f"pfmea_{control_type.casefold()}_options_{project_id}",
        native_row_selection=True,
    )
    if footer.undo:
        _undo(editor_key, f"Discarded unsaved {control_type} option edits")
    if footer.save_and_refresh:
        try:
            result = save_pfmea_control_option_rows(
                project_id, control_type, complete[["id", "label", "active"]]
            )
            _audit(project_id, f"Save {control_type} control options", result, {"scope": "project-wide"})
            request_table_editor_reset(editor_key)
            st.toast(f"Saved {control_type} options", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    st.download_button(
        "Export filtered rows",
        data=dataframe_to_excel(visible[["label", "active", "selection_count"]]),
        file_name=f"pfmea_{control_type.casefold()}_options.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"pfmea_{control_type.casefold()}_options_export_{project_id}",
        icon=":material/download:",
    )
    selected = native_selected_rows(editor_rows, editor_key=editor_key)
    if not selected.empty and not table_has_unsaved_changes(editor_key, native_row_selection=True):
        ids = selected.get("id", pd.Series(dtype="string")).dropna().astype(str).tolist()
        if ids and not st.session_state.get(PENDING_OPTION_DELETE_KEY):
            impact = pfmea_control_option_delete_impact(project_id, control_type, ids)
            st.session_state[PENDING_OPTION_DELETE_KEY] = {
                "project_id": project_id,
                "control_type": control_type,
                "option_ids": ids,
                "impact": impact,
                "editor_key": editor_key,
            }
            stage_native_delete_confirmation(editor_key)


def _render_control_catalogs(project_id: str) -> None:
    with st.expander("Manage PFMEA control options", icon=":material/settings:"):
        badge_row = st.container(horizontal=True, vertical_alignment="center")
        badge_row.caption("Reusable manual choices for structured PFMEA controls.")
        scope_badge(badge_row, scope="project")
        prevention_tab, detection_tab = st.tabs(["Prevention", "Detection"])
        with prevention_tab:
            _render_control_catalog(project_id, "Prevention")
        with detection_tab:
            _render_control_catalog(project_id, "Detection")


def _render_entries(project_id: str, scenario_id: str, work_element_id: str) -> pd.DataFrame:
    entries = _frame(
        pfmea_entries(project_id, scenario_id, work_element_id),
        {
            "id": "string",
            "potential_failure_mode": "string",
            "class_code": "string",
            "effect_count": "int64",
            "cause_count": "int64",
            "maximum_rpn": "float64",
            "upstream_changes": "bool",
            "updated_at": "string",
        },
    )
    logical_key = f"pfmea_entries_editor_{project_id}_{scenario_id}_{work_element_id}"
    editor_key = apply_pending_table_editor_reset(logical_key)
    editable_table_heading("Potential Failure Modes")
    visible = filter_table(
        entries,
        key=f"pfmea_entries_filters_{project_id}_{scenario_id}_{work_element_id}",
        dropdown_columns=["class_code", "upstream_changes"],
        search_columns=["potential_failure_mode", "class_code"],
        labels={"class_code": "Class", "upstream_changes": "Upstream changes need review"},
        reset_widget_keys=[editor_key],
    )
    editor_rows = direct_entry_editor_rows(
        visible,
        editor_key=editor_key,
        sort_columns=["potential_failure_mode", "class_code", "maximum_rpn", "updated_at"],
        labels={"potential_failure_mode": "Potential Failure Mode", "class_code": "Class",
                "maximum_rpn": "Maximum RPN", "updated_at": "Updated"},
    )
    edited = st.data_editor(
        editor_rows,
        key=editor_key,
        num_rows="dynamic",
        hide_index=True,
        height=300,
        disabled=["id", "effect_count", "cause_count", "maximum_rpn", "upstream_changes", "updated_at"],
        column_order=["potential_failure_mode", "class_code", "effect_count", "cause_count",
                      "maximum_rpn", "upstream_changes", "updated_at"],
        column_config={
            "id": None,
            "potential_failure_mode": st.column_config.TextColumn(
                "Potential Failure Mode", required=True, pinned=True,
                help="Describe how this Process at a Glance step could fail to meet its requirements.",
            ),
            "class_code": st.column_config.TextColumn(
                "Class", help="Enter the reviewed PFMEA classification. No value is inferred from Yamazumi flags."
            ),
            "effect_count": st.column_config.NumberColumn("Potential Effects"),
            "cause_count": st.column_config.NumberColumn("Potential Causes"),
            "maximum_rpn": st.column_config.NumberColumn("Maximum RPN", format="%.2f"),
            "upstream_changes": st.column_config.CheckboxColumn(
                "Upstream changes need review",
                help="The current Process step or published Quality assignments differ from the reviewed PFMEA source.",
            ),
            "updated_at": st.column_config.DatetimeColumn("Updated", format="MMM DD, YYYY HH:mm"),
        },
    )
    footer = editable_table_footer(
        editor_key=editor_key,
        key_prefix=f"pfmea_entries_{project_id}_{scenario_id}_{work_element_id}",
        native_row_selection=True,
    )
    if footer.undo:
        _undo(editor_key, "Discarded the unsaved PFMEA entry edits")
    if footer.save_and_refresh:
        selected = native_selected_rows(editor_rows, editor_key=editor_key)
        if not selected.empty:
            st.warning("Clear selected PFMEA entries before saving table edits.")
        else:
            try:
                cleaned = _drop_untouched_rows(
                    edited, identifying_columns=["potential_failure_mode"]
                )
                complete = merge_filtered_edits(entries, visible, cleaned)
                result = save_pfmea_entry_rows(project_id, scenario_id, work_element_id, complete)
                _audit(project_id, "Save & Refresh", result,
                       {"scenario_id": scenario_id, "work_element_id": work_element_id,
                        "record_type": "PFMEA entries"})
                request_table_editor_reset(editor_key)
                st.toast("Saved PFMEA entries", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    st.download_button(
        "Export filtered rows",
        data=dataframe_to_excel(
            visible.drop(columns=["id"], errors="ignore"), "PFMEA failure modes"
        ),
        file_name="pfmea_failure_modes_filtered.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        key=f"pfmea_entries_export_{project_id}_{scenario_id}_{work_element_id}",
    )
    selected = native_selected_rows(editor_rows, editor_key=editor_key)
    if not selected.empty and table_has_unsaved_changes(editor_key, native_row_selection=True):
        st.warning("Save or undo other PFMEA edits before deleting selected entries.")
    elif not selected.empty:
        _stage_delete(
            selected,
            editor_key=editor_key,
            project_id=project_id,
            scenario_id=scenario_id,
            table="pfmea_entries",
            record_label="Potential Failure Mode",
            display_column="potential_failure_mode",
        )
    return entries


def _render_simple_child_table(
    *, project_id: str, scenario_id: str, entry_id: str, table_name: str,
    title: str, data: pd.DataFrame, text_field: str, text_label: str,
    numeric_fields: list[tuple[str, str]], save_function,
) -> pd.DataFrame:
    columns = {"id": "string", text_field: "string"}
    columns.update({field: "float64" for field, _ in numeric_fields})
    if table_name == "pfmea_causes":
        columns["detection_review_required"] = "bool"
    columns["sequence"] = "int64"
    rows = _frame(data, columns)
    logical_key = f"{table_name}_editor_{project_id}_{scenario_id}_{entry_id}"
    editor_key = apply_pending_table_editor_reset(logical_key)
    editable_table_heading(title)
    visible = filter_table(
        rows,
        key=f"{table_name}_filters_{project_id}_{scenario_id}_{entry_id}",
        search_columns=[text_field],
        labels={text_field: text_label},
        reset_widget_keys=[editor_key],
    )
    editor_rows = direct_entry_editor_rows(
        visible, editor_key=editor_key, sort_columns=["sequence", text_field],
        labels={"sequence": "Seq", text_field: text_label},
    )
    config = {
        "id": None,
        text_field: st.column_config.TextColumn(text_label, required=True, width="large"),
        "sequence": st.column_config.NumberColumn("Seq", step=1),
    }
    for field, label in numeric_fields:
        config[field] = st.column_config.NumberColumn(
            label,
            min_value=0.000001,
            help="Enter the numeric rating. This module does not define or enforce a company scoring scale.",
        )
    column_order = [text_field, *[field for field, _ in numeric_fields]]
    disabled: list[str] = []
    if table_name == "pfmea_causes":
        column_order.append("detection_review_required")
        disabled.append("detection_review_required")
        config["detection_review_required"] = st.column_config.CheckboxColumn(
            "Detection rating needs review",
            help=(
                "A Detection control was added, removed, or reclassified. Review the numeric "
                "Detection rating, then use Save & Refresh to acknowledge it."
            ),
        )
    column_order.append("sequence")
    edited = st.data_editor(
        editor_rows,
        key=editor_key,
        num_rows="dynamic",
        hide_index=True,
        height=250,
        disabled=disabled,
        column_order=column_order,
        column_config=config,
    )
    cleaned = _drop_untouched_rows(edited, identifying_columns=[text_field])
    complete = merge_filtered_edits(rows, visible, cleaned)
    if table_name == "pfmea_causes" and bool(
        complete.get("detection_review_required", pd.Series(dtype=bool)).fillna(False).any()
    ):
        st.warning(
            "Detection control classification changed. Review the Detection rating and use "
            "Save & Refresh in Potential Causes to acknowledge it. RPN continues to use the "
            "current numeric Severity, Occurrence, and Detection values."
        )
    footer = editable_table_footer(
        editor_key=editor_key,
        key_prefix=f"{table_name}_{project_id}_{scenario_id}_{entry_id}",
        native_row_selection=True,
    )
    if footer.undo:
        _undo(editor_key, f"Discarded the unsaved {title} edits")
    if footer.save_and_refresh:
        if not native_selected_rows(editor_rows, editor_key=editor_key).empty:
            st.warning(f"Clear selected {title} rows before saving table edits.")
        else:
            try:
                result = save_function(project_id, scenario_id, entry_id, complete)
                _audit(project_id, "Save & Refresh", result,
                       {"scenario_id": scenario_id, "pfmea_entry_id": entry_id,
                        "record_type": table_name})
                request_table_editor_reset(editor_key)
                st.toast(f"Saved {title}", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    selected = native_selected_rows(editor_rows, editor_key=editor_key)
    if not selected.empty and not table_has_unsaved_changes(editor_key, native_row_selection=True):
        _stage_delete(
            selected,
            editor_key=editor_key,
            project_id=project_id,
            scenario_id=scenario_id,
            table=table_name,
            record_label=text_label,
            display_column=text_field,
        )
    return complete


def _render_actions(project_id: str, scenario_id: str, entry_id: str, causes: pd.DataFrame) -> None:
    rows = _frame(
        pfmea_actions(project_id, scenario_id, entry_id),
        {
            "id": "string", "pfmea_cause_id": "string", "recommended_action": "string",
            "responsibility": "string", "target_completion_date": "datetime64[ns]", "actions_taken": "string",
            "resulting_severity": "float64", "resulting_occurrence": "float64",
            "resulting_detection": "float64", "resulting_rpn": "float64", "sequence": "int64",
        },
    )
    rows["target_completion_date"] = pd.to_datetime(
        rows["target_completion_date"], errors="coerce"
    )
    cause_by_id = {str(row["id"]): str(row["cause_description"]) for _, row in causes.iterrows()}
    label_to_id = {"Failure mode": ""}
    for cause_id, description in cause_by_id.items():
        label_to_id[f"Cause: {description}"] = cause_id
    rows["action_scope"] = rows["pfmea_cause_id"].fillna("").astype(str).map(
        lambda value: "Failure mode" if not value else f"Cause: {cause_by_id.get(value, 'Unavailable cause')}"
    )
    logical_key = f"pfmea_actions_editor_{project_id}_{scenario_id}_{entry_id}"
    editor_key = apply_pending_table_editor_reset(logical_key)
    editable_table_heading("Recommended Actions")
    visible = filter_table(
        rows,
        key=f"pfmea_actions_filters_{project_id}_{scenario_id}_{entry_id}",
        dropdown_columns=["action_scope", "responsibility"],
        search_columns=["recommended_action", "responsibility", "actions_taken"],
        labels={"action_scope": "Applies to", "responsibility": "Responsibility"},
        reset_widget_keys=[editor_key],
    )
    editor_rows = direct_entry_editor_rows(
        visible, editor_key=editor_key, sort_columns=["sequence", "target_completion_date", "responsibility"],
        labels={"sequence": "Seq", "target_completion_date": "Target Completion Date"},
    )
    edited = st.data_editor(
        editor_rows,
        key=editor_key,
        num_rows="dynamic",
        hide_index=True,
        height=310,
        disabled=["id", "pfmea_cause_id"],
        column_order=["action_scope", "recommended_action", "responsibility", "target_completion_date",
                      "actions_taken", "resulting_severity", "resulting_occurrence",
                      "resulting_detection", "sequence"],
        column_config={
            "id": None,
            "pfmea_cause_id": None,
            "action_scope": st.column_config.SelectboxColumn(
                "Applies to", options=list(label_to_id), default="Failure mode", required=True
            ),
            "recommended_action": st.column_config.TextColumn("Recommended Action", required=True, width="large"),
            "responsibility": "Responsibility",
            "target_completion_date": st.column_config.DateColumn("Target Completion Date"),
            "actions_taken": st.column_config.TextColumn("Actions Taken", width="large"),
            "resulting_severity": st.column_config.NumberColumn("Resulting Severity", min_value=0.000001),
            "resulting_occurrence": st.column_config.NumberColumn("Resulting Occurrence", min_value=0.000001),
            "resulting_detection": st.column_config.NumberColumn("Resulting Detection", min_value=0.000001),
            "sequence": st.column_config.NumberColumn("Seq", step=1),
        },
    )
    cleaned = _drop_untouched_rows(edited, identifying_columns=["recommended_action"])
    complete = merge_filtered_edits(rows, visible, cleaned)
    resulting_preview = _resulting_rpn_preview(complete)
    st.markdown("**Resulting RPN preview**")
    st.caption(
        "Updates as Resulting Severity, Resulting Occurrence, or Resulting Detection is edited. "
        "Save & Refresh persists the displayed Resulting RPN."
    )
    if resulting_preview.empty:
        st.caption("Enter all three resulting ratings to calculate Resulting RPN.")
    else:
        selectable_dataframe(
            resulting_preview.rename(
                columns={
                    "recommended_action": "Recommended Action",
                    "resulting_severity": "Resulting Severity",
                    "resulting_occurrence": "Resulting Occurrence",
                    "resulting_detection": "Resulting Detection",
                    "resulting_rpn": "Resulting RPN",
                }
            ),
            key=f"pfmea_resulting_rpn_preview_{project_id}_{scenario_id}_{entry_id}",
            hide_index=True,
        )
    footer = editable_table_footer(
        editor_key=editor_key,
        key_prefix=f"pfmea_actions_{project_id}_{scenario_id}_{entry_id}",
        native_row_selection=True,
    )
    if footer.undo:
        _undo(editor_key, "Discarded the unsaved Recommended Action edits")
    if footer.save_and_refresh:
        if not native_selected_rows(editor_rows, editor_key=editor_key).empty:
            st.warning("Clear selected Recommended Actions before saving table edits.")
        else:
            try:
                complete["pfmea_cause_id"] = complete["action_scope"].map(label_to_id).replace("", None)
                result = save_pfmea_action_rows(project_id, scenario_id, entry_id, complete)
                _audit(project_id, "Save & Refresh", result,
                       {"scenario_id": scenario_id, "pfmea_entry_id": entry_id,
                        "record_type": "PFMEA actions"})
                request_table_editor_reset(editor_key)
                st.toast("Saved Recommended Actions", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    selected = native_selected_rows(editor_rows, editor_key=editor_key)
    if not selected.empty and not table_has_unsaved_changes(editor_key, native_row_selection=True):
        _stage_delete(
            selected,
            editor_key=editor_key,
            project_id=project_id,
            scenario_id=scenario_id,
            table="pfmea_actions",
            record_label="Recommended Action",
            display_column="recommended_action",
        )


def _recalculate_flat_rpn(rows: pd.DataFrame) -> pd.DataFrame:
    recalculated = rows.copy()
    recalculated["rpn"] = recalculated.apply(
        lambda row: _rpn_value(row.get("severity"), row.get("occurrence"), row.get("detection")),
        axis=1,
    )
    recalculated["resulting_rpn"] = recalculated.apply(
        lambda row: _rpn_value(
            row.get("resulting_severity"),
            row.get("resulting_occurrence"),
            row.get("resulting_detection"),
        ),
        axis=1,
    )
    return recalculated


def _stable_recalculated_draft(base_rows: pd.DataFrame, edited_rows: pd.DataFrame) -> pd.DataFrame:
    """Apply edits by stable line ID without duplicating or reordering saved rows."""
    base = base_rows.copy().reset_index(drop=True)
    if base.empty:
        return _recalculate_flat_rpn(edited_rows.copy().reset_index(drop=True))
    # ``edited_rows`` is authoritative for unsaved rows. Keeping an older
    # blank-ID draft in ``base`` would append the same logical row a second time
    # below, causing validation to inspect the incomplete copy first.
    base = base.loc[base["id"].map(_plain_text).ne("")].reset_index(drop=True)
    positions = {
        _plain_text(value): position
        for position, value in enumerate(base.get("id", pd.Series(dtype="string")))
        if _plain_text(value)
    }
    new_rows: list[dict] = []
    for record in edited_rows.to_dict("records"):
        line_id = _plain_text(record.get("id"))
        if not line_id:
            new_rows.append(record)
            continue
        position = positions.get(line_id)
        if position is None:
            raise ValueError("A PFMEA line changed or no longer exists. Refresh and try again.")
        for column, value in record.items():
            if column in base.columns:
                base.at[position, column] = value
    if new_rows:
        base = pd.concat([base, pd.DataFrame(new_rows)], ignore_index=True, sort=False)
    return _recalculate_flat_rpn(base)


def _pfmea_export_bytes(dataframe: pd.DataFrame) -> bytes:
    """Export PFMEA text with saved line breaks visible in Excel."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name="PFMEA", index=False)
        worksheet = writer.book["PFMEA"]
        for row in worksheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and "\n" in cell.value:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
    return output.getvalue()


def _high_risk_pfmea_rows(rows: pd.DataFrame, threshold: int) -> pd.DataFrame:
    """Return current flat PFMEA lines whose initial or resulting RPN exceeds the filter."""
    display_columns = [
        "item_number", "potential_failure_mode", "classification", "severity",
        "occurrence", "detection", "rpn", "resulting_rpn",
    ]
    if rows.empty:
        return pd.DataFrame({column: pd.Series(dtype="object") for column in display_columns})
    filtered = rows.copy()
    filtered["rpn"] = pd.to_numeric(filtered.get("rpn"), errors="coerce")
    filtered["resulting_rpn"] = pd.to_numeric(
        filtered.get("resulting_rpn"), errors="coerce"
    )
    filtered["highest_rpn"] = filtered[["rpn", "resulting_rpn"]].max(axis=1)
    filtered = filtered.loc[
        filtered["rpn"].gt(threshold) | filtered["resulting_rpn"].gt(threshold)
    ].sort_values(
        ["highest_rpn", "rpn", "resulting_rpn", "item_number"],
        ascending=[False, False, False, True],
        na_position="last",
        kind="stable",
    )
    return filtered.reindex(columns=display_columns).reset_index(drop=True)


def _render_high_risk_pfmea_view(
    project_id: str, scenario_id: str, flat_rows: pd.DataFrame
) -> None:
    with st.container(border=True):
        st.subheader("High-risk PFMEA lines")
        threshold = int(
            st.number_input(
                "RPN review threshold",
                min_value=1,
                value=100,
                step=1,
                format="%d",
                key=f"pfmea_rpn_threshold_{project_id}_{scenario_id}",
                help=(
                    "Shows current PFMEA lines when either RPN or Resulting RPN is greater "
                    "than this value. This review filter does not change PFMEA records or "
                    "define an approval limit."
                ),
            )
        )
        high_risk = _high_risk_pfmea_rows(flat_rows, threshold)
        if high_risk.empty:
            st.caption(
                f"No PFMEA lines have RPN or Resulting RPN greater than {threshold}."
            )
            return
        selectable_dataframe(
            high_risk.rename(
                columns={
                    "item_number": "Item #",
                    "potential_failure_mode": "Potential Failure Mode",
                    "classification": "Classification",
                    "severity": "Severity",
                    "occurrence": "Occurrence",
                    "detection": "Detection",
                    "rpn": "RPN",
                    "resulting_rpn": "Resulting RPN",
                }
            ),
            key=f"pfmea_high_risk_{project_id}_{scenario_id}",
            hide_index=True,
            row_height=96,
            column_config={
                "Item #": st.column_config.TextColumn("Item #", pinned=True),
                "RPN": st.column_config.NumberColumn("RPN", format="%d"),
                "Resulting RPN": st.column_config.NumberColumn(
                    "Resulting RPN", format="%d"
                ),
            },
        )


def _control_label_map(
    project_id: str,
    scenario_id: str,
    rows: pd.DataFrame,
    control_type: str | None = None,
) -> dict[str, str]:
    labels: dict[str, str] = {}
    selections = pfmea_control_selections(project_id, scenario_id)
    if not selections.empty:
        for _, selection in selections.iterrows():
            if control_type and _plain_text(selection.get("control_type")) != control_type:
                continue
            label = _plain_text(selection.get("label"))
            if bool(selection.get("review_required")):
                label = f"{label} — Review required"
            labels[str(selection["source_key"])] = label
    work_ids = rows.get("work_element_id", pd.Series(dtype="string")).dropna().astype(str).unique()
    for work_element_id in work_ids:
        if not work_element_id:
            continue
        matching = rows.loc[rows["work_element_id"].astype(str).eq(work_element_id)]
        candidate_types = (
            [
                (
                    control_type,
                    "prevention_controls"
                    if control_type == "Prevention"
                    else "detection_controls",
                )
            ]
            if control_type
            else [
                ("Prevention", "prevention_controls"),
                ("Detection", "detection_controls"),
            ]
        )
        for candidate_type, column in candidate_types:
            included = [item for value in matching.get(column, []) for item in _list_values(value)]
            candidates = pfmea_control_candidates(
                project_id, scenario_id, work_element_id, candidate_type, included
            )
            for _, candidate in candidates.iterrows():
                labels.setdefault(str(candidate["source_key"]), str(candidate["label"]))
    return labels


def _cause_target_key(row: pd.Series) -> str:
    cause_id = _plain_text(row.get("cause_id"))
    return f"cause:{cause_id}" if cause_id else f"draft:{_plain_text(row.get('draft_row_id'))}"


def _pfmea_line_label(
    row: pd.Series, step_by_id: dict[str, dict | pd.Series]
) -> str:
    step = step_by_id.get(_plain_text(row.get("work_element_id")), {})
    return " — ".join(
        [
            _plain_text(row.get("item_number")) or "Unassigned",
            _plain_text(step.get("work_element"))
            or _plain_text(row.get("process_function"))
            or "Unnamed Process Function",
            _plain_text(row.get("potential_failure_mode")) or "Blank Failure Mode",
            _plain_text(row.get("potential_causes")) or "Blank Cause",
        ]
    )


def _render_control_copy_workflow(
    project_id: str,
    scenario_id: str,
    targets: dict[str, pd.Series],
    target_key: str,
    rows: pd.DataFrame,
    draft_key: str,
    editor_key: str,
    step_by_id: dict[str, dict | pd.Series],
) -> None:
    sources = {key: row for key, row in targets.items() if key != target_key}
    if not sources:
        return
    with st.expander("Copy controls from another PFMEA Cause"):
        source_key = st.selectbox(
            "Source PFMEA Cause",
            options=list(sources),
            format_func=lambda key: _pfmea_line_label(sources[key], step_by_id),
            key=f"pfmea_control_copy_source_{project_id}_{scenario_id}_{target_key}",
            help="Choose the PFMEA Cause whose Prevention or Detection selections you want to reuse.",
        )
        lists_to_copy = st.multiselect(
            "Control lists to replace",
            options=["Prevention", "Detection"],
            default=["Prevention", "Detection"],
            key=f"pfmea_control_copy_lists_{project_id}_{scenario_id}_{target_key}",
            help="Only the chosen target lists are replaced. Other target controls remain unchanged.",
        )
        source = sources[source_key]
        target = targets[target_key]
        preview: dict[str, tuple[list[str], list[str]]] = {}
        all_labels = _control_label_map(project_id, scenario_id, rows)
        for control_type, column in (
            ("Prevention", "prevention_controls"),
            ("Detection", "detection_controls"),
        ):
            if control_type not in lists_to_copy:
                continue
            preview[control_type] = _valid_controls_for_step(
                project_id,
                scenario_id,
                _plain_text(target.get("work_element_id")),
                control_type,
                _list_values(source.get(column)),
            )
        for control_type, (kept, omitted) in preview.items():
            st.markdown(f"**{control_type} replacement**")
            if kept:
                for source_id in kept:
                    st.write(f"- {all_labels.get(source_id, 'Unavailable control')}")
            else:
                st.caption("No valid controls will be copied to this list.")
            if omitted:
                st.warning(
                    "These controls will be omitted because they are step-specific or inactive: "
                    + "; ".join(
                        all_labels.get(value, "Unavailable control") for value in omitted
                    )
                )
        if st.button(
            "Replace selected control lists",
            icon=":material/content_copy:",
            disabled=not bool(lists_to_copy),
            key=f"pfmea_apply_control_copy_{project_id}_{scenario_id}_{target_key}",
        ):
            updated = rows.copy()
            target_mask = updated.apply(
                lambda row: _cause_target_key(row) == target_key, axis=1
            )
            for control_type, column in (
                ("Prevention", "prevention_controls"),
                ("Detection", "detection_controls"),
            ):
                if control_type not in preview:
                    continue
                replacement = list(preview[control_type][0])
                updated.loc[target_mask, column] = pd.Series(
                    [replacement] * int(target_mask.sum()),
                    index=updated.index[target_mask],
                    dtype="object",
                )
            st.session_state[draft_key] = updated
            request_table_editor_reset(editor_key)
            st.toast("Staged copied PFMEA controls", icon=":material/content_copy:")
            st.rerun()


def _render_control_selection_panel(
    project_id: str, scenario_id: str, rows: pd.DataFrame, draft_key: str, editor_key: str,
    step_by_id: dict[str, dict | pd.Series],
) -> pd.DataFrame:
    targets: dict[str, pd.Series] = {}
    for _, row in rows.iterrows():
        if _plain_text(row.get("work_element_id")):
            targets.setdefault(_cause_target_key(row), row)
    if not targets:
        st.caption("Select a Process Function in a PFMEA line before choosing controls.")
        return rows
    st.subheader("Select Current Process Controls")
    target_key = st.selectbox(
        "PFMEA Cause",
        options=list(targets),
        format_func=lambda key: " — ".join(
            [
                _plain_text(targets[key].get("item_number")) or "Unassigned",
                _plain_text(
                    step_by_id.get(_plain_text(targets[key].get("work_element_id")), {}).get("work_element")
                ) or "Unnamed Process Function",
                _plain_text(targets[key].get("potential_failure_mode")) or "Blank Failure Mode",
                _plain_text(targets[key].get("potential_causes")) or "Blank Cause",
            ]
        ),
        key=f"pfmea_control_cause_{project_id}_{scenario_id}",
        help="Choose the saved or draft PFMEA Cause whose structured controls you want to edit.",
    )
    target = targets[target_key]
    target_mask = rows.apply(lambda row: _cause_target_key(row) == target_key, axis=1)
    updated = rows.copy()
    changed = False
    for control_type, column in (("Prevention", "prevention_controls"), ("Detection", "detection_controls")):
        current = _list_values(target.get(column))
        candidates = pfmea_control_candidates(
            project_id, scenario_id, _plain_text(target.get("work_element_id")), control_type, current
        )
        labels = {str(row["source_key"]): str(row["label"]) for _, row in candidates.iterrows()}
        selected = st.multiselect(
            f"{control_type} controls",
            options=list(labels),
            default=[value for value in current if value in labels],
            format_func=lambda value, choices=labels: choices.get(value, value),
            key=f"pfmea_{control_type.casefold()}_picker_{project_id}_{scenario_id}_{target_key}",
            help=f"Choose linked published Quality requirements or project-wide manual {control_type} options.",
        )
        if selected != current:
            updated.loc[target_mask, column] = pd.Series(
                [list(selected)] * int(target_mask.sum()), index=updated.index[target_mask], dtype="object"
            )
            changed = True
    if changed:
        st.session_state[draft_key] = updated
        st.session_state.pop(
            _pfmea_copy_state_key("control_paste_error", project_id, scenario_id),
            None,
        )
        request_table_editor_reset(editor_key)
        st.rerun()
    _render_control_copy_workflow(
        project_id,
        scenario_id,
        targets,
        target_key,
        updated,
        draft_key,
        editor_key,
        step_by_id,
    )
    return updated


def _render_pfmea_duplicate_workflow(
    project_id: str,
    scenario_id: str,
    rows: pd.DataFrame,
    draft_key: str,
    editor_key: str,
    step_by_id: dict[str, dict | pd.Series],
) -> None:
    sources: dict[str, pd.Series] = {}
    for _, row in rows.iterrows():
        identity = _pfmea_row_identity(row)
        if identity and _plain_text(row.get("work_element_id")):
            sources.setdefault(identity, row)
    if not sources:
        return
    with st.container(border=True):
        st.subheader("Duplicate PFMEA line")
        source_key = st.selectbox(
            "PFMEA line to duplicate",
            options=list(sources),
            format_func=lambda key: _pfmea_line_label(sources[key], step_by_id),
            key=f"pfmea_duplicate_source_{project_id}_{scenario_id}",
            help=(
                "Creates one independent unsaved line. Actions Taken and resulting ratings "
                "are cleared; use Save & Refresh when the draft is ready."
            ),
        )
        if st.button(
            "Duplicate selected PFMEA line",
            icon=":material/content_copy:",
            key=f"pfmea_duplicate_line_{project_id}_{scenario_id}",
        ):
            duplicate, omitted = _duplicate_pfmea_line(
                sources[source_key], project_id, scenario_id
            )
            updated = pd.concat(
                [rows, pd.DataFrame([duplicate]).reindex(columns=rows.columns)],
                ignore_index=True,
                sort=False,
            )
            st.session_state[draft_key] = _recalculate_flat_rpn(updated)
            forced = _forced_copy_ids(project_id, scenario_id)
            forced.add(_plain_text(duplicate.get("draft_row_id")))
            _set_forced_copy_ids(project_id, scenario_id, forced)
            if omitted:
                labels = _control_label_map(project_id, scenario_id, rows)
                st.session_state[
                    _pfmea_copy_state_key("copy_notice", project_id, scenario_id)
                ] = (
                    "The duplicate omitted inactive or no-longer-applicable controls: "
                    + "; ".join(
                        labels.get(value, "Unavailable control") for value in omitted
                    )
                )
            request_table_editor_reset(editor_key)
            st.toast("Created an unsaved PFMEA line duplicate", icon=":material/content_copy:")
            st.rerun()


def _render_flat_pfmea_table(
    project_id: str, scenario_id: str, steps: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    stored = _frame(pfmea_flat_rows(project_id, scenario_id), PFMEA_FLAT_COLUMNS)
    draft_key = f"pfmea_flat_draft_{project_id}_{scenario_id}"
    draft = st.session_state.get(draft_key)
    rows = (
        _deduplicate_pfmea_draft_rows(_frame(draft, PFMEA_FLAT_COLUMNS))
        if isinstance(draft, pd.DataFrame)
        else stored
    )

    invalid_classes = sorted(
        set(rows["classification"].dropna().astype(str)) - set(PFMEA_CLASSIFICATIONS)
    )
    if invalid_classes:
        st.warning(
            "Saved legacy Class values are outside the approved Classification choices. "
            "Choose blank, Safety, or Critical Quality before Save & Refresh."
        )
        rows.loc[rows["classification"].isin(invalid_classes), "classification"] = ""

    logical_key = f"pfmea_flat_editor_{project_id}_{scenario_id}"
    editor_key = apply_pending_table_editor_reset(logical_key)
    editable_table_heading("PFMEA line items")
    visible = filter_table(
        rows,
        key=f"pfmea_flat_filters_{project_id}_{scenario_id}",
        dropdown_columns=["item_number", "classification"],
        search_columns=[
            "potential_failure_mode", "potential_effects", "potential_causes",
            "recommended_action",
        ],
        labels={"item_number": "Item #", "classification": "Classification"},
        reset_widget_keys=[editor_key],
    )
    editor_rows = direct_entry_editor_rows(
        visible,
        editor_key=editor_key,
        sort_columns=["item_number", "potential_failure_mode", "potential_effects", "potential_causes"],
        labels={"item_number": "Item #", "potential_failure_mode": "Potential Failure Mode"},
    )
    step_by_id = {str(row["id"]): row for _, row in steps.iterrows()}
    process_options = list(step_by_id)
    editor_rows = _prepare_pfmea_process_columns(editor_rows, step_by_id)
    rating_help = (
        "Choose a whole-number rating from 1 through 10. This module does not define "
        "or embed company scoring guidance."
    )
    prevention_labels = _control_label_map(
        project_id, scenario_id, rows, "Prevention"
    )
    detection_labels = _control_label_map(
        project_id, scenario_id, rows, "Detection"
    )
    control_labels = prevention_labels | detection_labels
    column_config = {
        column: None for column in PFMEA_FLAT_COLUMNS if column not in PFMEA_VISIBLE_COLUMNS
    }
    column_config.update(
        {
            "item_number": st.column_config.TextColumn(
                "Item #", disabled=True, pinned=True,
                help="Displays the selected Process Function's Process at a Glance Pitch.",
            ),
            "process_function": st.column_config.SelectboxColumn(
                "Process Function", options=process_options, required=True,
                format_func=lambda work_element_id: _process_step_option_label(
                    step_by_id.get(str(work_element_id), {})
                ),
                help=(
                    "Choose a Process at a Glance Work Element for a new PFMEA line. "
                    "The selection is locked after its first Save & Refresh."
                ),
                width="large",
            ),
            "potential_failure_mode": st.column_config.TextColumn(
                "Potential Failure Mode", width="large",
                help="Free text preserves pasted or saved line breaks.",
            ),
            "potential_effects": st.column_config.TextColumn(
                "Potential Effect(s) of Failure", width="large",
                help="Free text preserves pasted or saved line breaks.",
            ),
            "classification": st.column_config.SelectboxColumn(
                "Classification", options=PFMEA_CLASSIFICATIONS,
                help="Choose blank, Safety, or Critical Quality. This replaces the former free-text Class field.",
            ),
            "potential_causes": st.column_config.TextColumn(
                "Potential Causes(s) of Failure", width="large",
                help="Free text preserves pasted or saved line breaks.",
            ),
            "prevention_controls": st.column_config.MultiselectColumn(
                "Current Process Controls — Prevention",
                options=list(prevention_labels),
                format_func=lambda value: prevention_labels.get(value, value),
                accept_new_options=False,
                width="large",
                help=(
                    "Choose controls directly or use Ctrl+C and Ctrl+V to replace another "
                    "Prevention cell. Changes remain unsaved until Save & Refresh."
                ),
            ),
            "detection_controls": st.column_config.MultiselectColumn(
                "Current Process Controls — Detection",
                options=list(detection_labels),
                format_func=lambda value: detection_labels.get(value, value),
                accept_new_options=False,
                width="large",
                help=(
                    "Choose controls directly or use Ctrl+C and Ctrl+V to replace another "
                    "Detection cell. Changes remain unsaved until Save & Refresh."
                ),
            ),
            "rpn": st.column_config.NumberColumn("RPN", disabled=True, format="%d"),
            "recommended_action": st.column_config.TextColumn(
                "Recommended Action", width="large",
                help="Free text preserves pasted or saved line breaks.",
            ),
            "responsibility_target": st.column_config.TextColumn(
                "Responsibility & Target Completion Date",
                help="Enter Responsibility, optionally followed by | and the date in YYYY-MM-DD format.",
            ),
            "actions_taken": st.column_config.TextColumn(
                "Actions Taken", width="large",
                help="Free text preserves pasted or saved line breaks.",
            ),
            "resulting_rpn": st.column_config.NumberColumn(
                "Resulting RPN", disabled=True, format="%d"
            ),
        }
    )
    for column, label in [
        ("severity", "Severity"), ("occurrence", "Occurrence"), ("detection", "Detection"),
        ("resulting_severity", "Resulting Severity"),
        ("resulting_occurrence", "Resulting Occurrence"),
        ("resulting_detection", "Resulting Detection"),
    ]:
        column_config[column] = st.column_config.SelectboxColumn(
            label, options=PFMEA_RATINGS, help=rating_help
        )

    edited = st.data_editor(
        editor_rows,
        key=editor_key,
        on_change=_stage_pfmea_process_selection,
        args=(
            editor_key,
            draft_key,
            rows,
            visible,
            editor_rows,
            step_by_id,
            project_id,
            scenario_id,
            control_labels,
        ),
        num_rows="dynamic",
        hide_index=True,
        height=470,
        row_height=96,
        disabled=["item_number", "rpn", "resulting_rpn"],
        column_order=PFMEA_VISIBLE_COLUMNS,
        column_config=column_config,
    )
    edited, process_selection_changed, reassignment_attempted = (
        _normalize_pfmea_process_selection(edited, editor_rows, step_by_id)
    )

    cleaned = _drop_untouched_rows(
        edited,
        identifying_columns=[
            "item_number", "potential_failure_mode", "potential_effects", "potential_causes"
        ],
    )
    complete = _merge_pfmea_filtered_edits(rows, visible, cleaned)
    complete, propagated_columns, shared_conflicts = _propagate_shared_editor_changes(
        complete,
        editor_rows,
        st.session_state.get(editor_key, {}) or {},
    )
    if shared_conflicts:
        st.session_state[draft_key] = complete
        st.session_state[
            _pfmea_copy_state_key("shared_edit_error", project_id, scenario_id)
        ] = shared_conflicts
        request_table_editor_reset(editor_key)
        st.rerun()
    if propagated_columns:
        st.session_state[draft_key] = complete
        st.session_state.pop(
            _pfmea_copy_state_key("shared_edit_error", project_id, scenario_id), None
        )
        st.session_state[
            _pfmea_copy_state_key("shared_edit_notice", project_id, scenario_id)
        ] = propagated_columns
        request_table_editor_reset(editor_key)
        st.rerun()
    if process_selection_changed:
        st.session_state[draft_key] = complete
        if reassignment_attempted:
            st.session_state[f"{draft_key}_locked_notice"] = True
        request_table_editor_reset(editor_key)
        st.rerun()
    if st.session_state.pop(f"{draft_key}_locked_notice", False):
        st.warning(
            "A saved Process Function is locked. Create a new PFMEA line for another "
            "Process step; reassignment requires a separately approved confirmed action."
        )
    shared_error = st.session_state.get(
        _pfmea_copy_state_key("shared_edit_error", project_id, scenario_id)
    )
    if shared_error:
        st.error(
            "Conflicting pasted values target the same underlying PFMEA record: "
            + ", ".join(str(value) for value in shared_error)
            + ". Make those repeated values consistent before Save & Refresh."
        )
    shared_notice = st.session_state.pop(
        _pfmea_copy_state_key("shared_edit_notice", project_id, scenario_id), None
    )
    if shared_notice:
        st.info(
            "Updated every displayed line that shares: "
            + ", ".join(str(value).replace("_", " ").title() for value in shared_notice)
            + "."
        )
    copy_notice = st.session_state.pop(
        _pfmea_copy_state_key("copy_notice", project_id, scenario_id), None
    )
    if copy_notice:
        st.warning(str(copy_notice))
    control_paste_error = st.session_state.get(
        _pfmea_copy_state_key("control_paste_error", project_id, scenario_id)
    )
    if control_paste_error:
        st.error(
            "Conflicting pasted values target the same PFMEA Cause: "
            + ", ".join(str(value) for value in control_paste_error)
            + ". Make the repeated control cells consistent before Save & Refresh."
        )
    control_paste_instructions = st.session_state.pop(
        _pfmea_copy_state_key("control_paste_instruction", project_id, scenario_id),
        None,
    )
    for instruction in control_paste_instructions or []:
        st.info(str(instruction))
    control_paste_warnings = st.session_state.pop(
        _pfmea_copy_state_key("control_paste_warning", project_id, scenario_id),
        None,
    )
    for warning in control_paste_warnings or []:
        st.warning(str(warning))
    present_draft_ids = {
        _plain_text(value)
        for value in complete.get("draft_row_id", pd.Series(dtype="string"))
        if _plain_text(value)
    }
    _set_forced_copy_ids(
        project_id,
        scenario_id,
        _forced_copy_ids(project_id, scenario_id) & present_draft_ids,
    )
    complete = _render_control_selection_panel(
        project_id, scenario_id, complete, draft_key, editor_key, step_by_id
    )
    _render_pfmea_duplicate_workflow(
        project_id, scenario_id, complete, draft_key, editor_key, step_by_id
    )
    footer = editable_table_footer(
        editor_key=editor_key,
        key_prefix=f"pfmea_flat_{project_id}_{scenario_id}",
        native_row_selection=True,
        additional_unsaved_changes=isinstance(st.session_state.get(draft_key), pd.DataFrame),
    )
    if footer.undo:
        st.session_state.pop(draft_key, None)
        _clear_control_picker_state(project_id, scenario_id)
        _clear_pfmea_copy_state(project_id, scenario_id)
        _undo(editor_key, "Discarded the unsaved PFMEA line-item and control edits")
    if st.button(
        "Recalculate RPN",
        icon=":material/calculate:",
        key=f"pfmea_recalculate_{project_id}_{scenario_id}",
        help="Refreshes Initial and Resulting RPN from the six current unsaved rating selections without saving.",
    ):
        try:
            st.session_state[draft_key] = _stable_recalculated_draft(rows, complete)
            request_table_editor_reset(editor_key)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    if bool(complete.get("detection_review_required", pd.Series(dtype=bool)).fillna(False).any()):
        st.warning(
            "Detection-control selections changed. Review the Detection rating. RPN uses "
            "the currently entered Severity, Occurrence, and Detection values and is recalculated on save."
        )
    review_rows = complete.loc[
        complete.get("control_source_review_required", pd.Series(dtype=bool)).fillna(False)
    ]
    if not review_rows.empty:
        affected = []
        for _, row in review_rows.drop_duplicates(subset=["cause_id", "draft_row_id"]).iterrows():
            affected.append(
                " — ".join(
                    [
                        _plain_text(row.get("item_number")) or "Unassigned",
                        _plain_text(row.get("process_function")) or "Unnamed Process Function",
                        _plain_text(row.get("potential_causes")) or "Blank Cause",
                    ]
                )
            )
        st.warning(
            "Control sources changed and require review:\n\n"
            + "\n".join(f"- {value}" for value in affected)
        )

    if footer.save_and_refresh:
        selected = native_selected_rows(editor_rows, editor_key=editor_key)
        if not selected.empty:
            st.warning("Clear selected PFMEA lines before saving table edits.")
        else:
            try:
                save_rows = _stable_recalculated_draft(rows, complete)
                result = save_pfmea_flat_rows(
                    project_id,
                    scenario_id,
                    save_rows,
                    force_new_draft_ids=_forced_copy_ids(project_id, scenario_id),
                )
                _audit(
                    project_id, "Save & Refresh", result,
                    {"scenario_id": scenario_id, "record_type": "PFMEA line items"},
                )
                st.session_state.pop(draft_key, None)
                _clear_control_picker_state(project_id, scenario_id)
                _clear_pfmea_copy_state(project_id, scenario_id)
                request_table_editor_reset(editor_key)
                st.toast("Saved PFMEA line items", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                # Retain the complete current editor output across later reruns.
                # Validation errors must not discard a new or edited PFMEA row.
                st.session_state[draft_key] = complete.copy()
                st.error(str(exc))

    export_rows = visible[PFMEA_VISIBLE_COLUMNS].copy()
    for control_column in ("prevention_controls", "detection_controls"):
        export_rows[control_column] = export_rows[control_column].map(
            lambda value: "\n".join(
                control_labels.get(source_key, "Unavailable control")
                for source_key in _list_values(value)
            )
        )
    st.download_button(
        "Export filtered rows",
        data=_pfmea_export_bytes(
            export_rows.rename(columns={
                "item_number": "Item #", "process_function": "Process Function",
                "potential_failure_mode": "Potential Failure Mode",
                "potential_effects": "Potential Effect(s) of Failure", "severity": "Severity",
                "classification": "Classification", "potential_causes": "Potential Causes(s) of Failure",
                "occurrence": "Occurrence", "prevention_controls": "Current Process Controls — Prevention",
                "detection_controls": "Current Process Controls — Detection", "detection": "Detection",
                "rpn": "RPN", "recommended_action": "Recommended Action",
                "responsibility_target": "Responsibility & Target Completion Date",
                "actions_taken": "Actions Taken", "resulting_severity": "Resulting Severity",
                "resulting_occurrence": "Resulting Occurrence",
                "resulting_detection": "Resulting Detection", "resulting_rpn": "Resulting RPN",
            }),
        ),
        file_name="pfmea_filtered.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        key=f"pfmea_flat_export_{project_id}_{scenario_id}",
    )
    selected = native_selected_rows(editor_rows, editor_key=editor_key)
    if not selected.empty and table_has_unsaved_changes(editor_key, native_row_selection=True):
        st.warning("Save or undo other PFMEA edits before deleting selected lines.")
    elif not selected.empty:
        selected_entries = selected.drop_duplicates(subset=["entry_id"])
        selected_labels = selected_entries.apply(
            lambda row: (
                f"{_plain_text(row.get('item_number')) or 'Unassigned'} — "
                f"{_plain_text(row.get('process_function')) or 'Unnamed Process Function'}"
                + (
                    f" — {_plain_text(row.get('potential_failure_mode'))}"
                    if _plain_text(row.get("potential_failure_mode"))
                    else ""
                )
            ),
            axis=1,
        ).tolist()
        delete_rows = (
            selected_entries[["entry_id", "potential_failure_mode"]]
            .rename(columns={"entry_id": "id"})
        )
        _stage_delete(
            delete_rows,
            editor_key=editor_key,
            project_id=project_id,
            scenario_id=scenario_id,
            table="pfmea_entries",
            record_label="PFMEA line item",
            display_column="potential_failure_mode",
            selected_labels=selected_labels,
            impact_message=(
                f"This removes {len(delete_rows)} parent PFMEA failure mode record(s), "
                "including their Effects, Causes, Controls, RPN records, and Recommended "
                "Actions. Process at a Glance and Quality records remain unchanged."
            ),
        )
    return stored, complete


def render_pfmea_tab(project_id: str, scenario_id: str, scenario_name: str) -> None:
    pending_paste = st.session_state.get(PENDING_CONTROL_PASTE_KEY) or {}
    if pending_paste and (
        str(pending_paste.get("project_id") or "") != project_id
        or str(pending_paste.get("scenario_id") or "") != scenario_id
    ):
        st.session_state.pop(PENDING_CONTROL_PASTE_KEY, None)
    st.subheader("Process FMEA")
    st.caption(
        f"Scenario-specific to {scenario_name}. Ratings are whole-number selections from "
        "1 through 10; this module does not define company Severity, Occurrence, or Detection scales."
    )
    try:
        migration = migrate_legacy_pfmea_controls(
            project_id, st.session_state.get("current_editor", "")
        )
    except ValueError as exc:
        st.error(str(exc))
        st.info("Enter Current editor to complete the one-time PFMEA controls migration.")
        return
    if migration.get("row_count"):
        st.toast(
            f"Completed PFMEA control migration for {migration['row_count']} legacy record(s)",
            icon=":material/check_circle:",
        )
    steps = pfmea_process_steps(project_id, scenario_id)
    if steps.empty:
        st.info("Add a Process at a Glance step in this scenario before creating PFMEA entries.")
        return
    with st.container(border=True):
        st.caption(
            "Item # shows the Process at a Glance Pitch while the stable Process relationship "
            "remains hidden. Process Function shows the Process at a Glance Work Element."
        )
        stored_flat_rows, current_flat_rows = _render_flat_pfmea_table(
            project_id, scenario_id, steps
        )

    _render_control_catalogs(project_id)

    chart_rows = stored_flat_rows.loc[
        stored_flat_rows.get("rpn", pd.Series(dtype=float)).notna()
        & stored_flat_rows.get("risk_row_id", pd.Series(dtype="string")).fillna("").ne("")
    ].copy()
    if not chart_rows.empty:
        chart_rows = chart_rows.drop_duplicates(subset=["risk_row_id"])
        chart_rows["PFMEA line"] = (
            chart_rows["item_number"].astype(str)
            + " | " + chart_rows["potential_failure_mode"].astype(str)
            + " | " + chart_rows["potential_causes"].astype(str)
        )
        chart_rows["RPN"] = pd.to_numeric(chart_rows["rpn"], errors="coerce")
        with st.container(border=True):
            st.subheader("Saved RPN by PFMEA line")
            st.caption(
                "Each bar represents one saved Effect and Cause line. This chart applies no "
                "thresholds, rating guidance, or risk colors."
            )
            st.bar_chart(chart_rows, x="PFMEA line", y="RPN", horizontal=True)

    _render_high_risk_pfmea_view(project_id, scenario_id, current_flat_rows)

    entries = pfmea_entries(project_id, scenario_id)
    review_entries = entries.loc[
        entries.get("upstream_changes", pd.Series(dtype=bool)).fillna(False)
    ].copy()
    if not review_entries.empty:
        st.subheader("Process source review")
        entry_by_id = {str(row["id"]): row for _, row in review_entries.iterrows()}
        entry_id = st.selectbox(
            "PFMEA failure mode with Process changes",
            options=list(entry_by_id),
            format_func=lambda value: (
                f"{entry_by_id[value].get('process_pitch_snapshot') or 'Unassigned'} — "
                f"{entry_by_id[value].get('process_operation_snapshot') or 'Unnamed Work Element'} — "
                f"{entry_by_id[value]['potential_failure_mode']}"
            ),
            key=f"pfmea_entry_details_{project_id}_{scenario_id}",
            help="Choose a saved failure mode whose linked Process at a Glance source changed.",
        )
        selected_entry = entry_by_id[entry_id]
        if bool(selected_entry.get("upstream_changes")):
            st.warning(
                "Process changes need review. Current Process at a Glance data differs from "
                "the reviewed PFMEA evidence; saved PFMEA values were not replaced."
            )
            if st.button(
                "Review current sources",
                icon=":material/fact_check:",
                key=f"pfmea_review_sources_{project_id}_{scenario_id}_{entry_id}",
            ):
                st.session_state[PENDING_REVIEW_KEY] = {
                    "project_id": project_id, "scenario_id": scenario_id, "entry_id": entry_id
                }

    if st.session_state.get(PENDING_DELETE_KEY):
        _confirm_pfmea_delete()
    if st.session_state.get(PENDING_REVIEW_KEY):
        _confirm_source_review()
    if st.session_state.get(PENDING_OPTION_DELETE_KEY):
        _confirm_control_option_delete()
    if st.session_state.get(PENDING_PROCESS_CHANGE_KEY):
        _confirm_pfmea_process_change()
    elif st.session_state.get(PENDING_CONTROL_PASTE_KEY):
        _confirm_pfmea_control_paste()
