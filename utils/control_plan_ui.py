"""Streamlit presentation for the scenario-specific MCP working draft."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.control_plan_store import (
    PROCESS_NUMBERING_VERSION,
    PLACEMENTS,
    control_plan_evidence,
    control_plan_flow_projection,
    control_plan_projection,
    control_plan_relink_candidates,
    control_plan_review_items,
    exclude_control_plan_projection_keys,
    migrate_control_plan_pr_numbers,
    normalize_control_plan_characteristic_suffix,
    normalize_control_plan_pr_number,
    rebuild_control_plan_characteristic_numbers,
    relink_control_plan_item,
    restore_control_plan_item,
    save_control_plan_rows,
)
from utils.control_plan_flow import control_plan_process_flow
from utils.pfmea_store import PFMEA_CLASSIFICATION_MEANINGS, migrate_pfmea_classifications
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
    editable_table_footer,
    editable_table_heading,
    native_selected_rows,
    selectable_dataframe,
    stage_native_delete_confirmation,
    table_has_unsaved_changes,
)


VISIBLE_COLUMNS = [
    "pr_number", "station_pitch", "op_id", "machine_fixture", "operation",
    "characteristic_suffix", "characteristic_placement",
    "product_part_characteristic", "process_characteristic", "classification",
    "specification_requirement", "measurement_evaluation", "sample_size",
    "sample_frequency", "who", "control_method", "decision_rule",
    "source_review_required",
]
EDITABLE_COLUMNS = {
    "pr_number", "machine_fixture", "characteristic_suffix", "characteristic_placement",
    "sample_size", "sample_frequency",
    "who", "control_method", "decision_rule",
}
PENDING_EXCLUSION_KEY = "control_plan_pending_exclusion"
PENDING_RELINK_KEY = "control_plan_pending_relink"
PENDING_DUPLICATE_NUMBER_KEY = "control_plan_pending_duplicate_number"


def _audit(project_id: str, action: str, result: dict, scenario_id: str) -> None:
    record_audit_event(
        project_id,
        "Control Plan",
        action,
        int(result.get("row_count", 0)),
        st.session_state.get("current_editor", ""),
        {
            "scenario_id": scenario_id,
            "affected_ids": result.get("affected_ids", []),
            "store_timestamp": result.get("timestamp", ""),
            "process_numbering_version": PROCESS_NUMBERING_VERSION,
        },
    )


def _classification_label(code) -> str:
    value = str(code or "").strip()
    meaning = PFMEA_CLASSIFICATION_MEANINGS.get(value, "Legacy or unavailable")
    return f"{value} — {meaning}" if value else "Unclassified"


def _characteristic_type_label(value) -> str:
    stored = "" if value is None or pd.isna(value) else str(value).strip()
    return "Product" if stored == "Product / Part" else stored or "Not assigned"


def _render_classification_legend() -> None:
    with st.expander("PFMEA Classification legend"):
        legend = pd.DataFrame(
            [
                {"Code": code, "Meaning": meaning}
                for code, meaning in PFMEA_CLASSIFICATION_MEANINGS.items()
                if code
            ]
        )
        st.dataframe(legend, hide_index=True)


def _column_config() -> dict:
    return {
        "id": None,
        "projection_key": None,
        "pfmea_entry_id": None,
        "work_element_id": None,
        "source_kind": None,
        "quality_requirement_assignment_id": None,
        "quality_requirement_id": None,
        "source_quality_requirement_id_snapshot": None,
        "source_unique_identifier_snapshot": None,
        "source_description_snapshot": None,
        "source_fingerprint": None,
        "operation_pr_number": None,
        "effective_characteristic_suffix": None,
        "reserved_characteristic_suffixes": None,
        "characteristic_type_filter": None,
        "projection_order": None,
        "persisted": None,
        "sequence": None,
        "excluded": None,
        "pr_number": st.column_config.NumberColumn(
            "Pr. Nº", format="%.1f", pinned=True,
            help=(
                "Enter the document number for this Process operation. It is shown only "
                "on the operation's first visible line and does not control Process order."
            ),
        ),
        "station_pitch": st.column_config.TextColumn(
            "Station / Pitch",
            disabled=True,
            pinned=True,
            help=(
                "The current Process at a Glance Pitch for this operation. "
                "It is read-only and does not control Pr. Nº or Process order."
            ),
        ),
        "op_id": st.column_config.TextColumn(
            "Op ID",
            disabled=True,
            pinned=True,
            width="medium",
            help=(
                "The current full Process operation identifier, including its position "
                "within the Pitch. It is derived live and controls the displayed Process order."
            ),
        ),
        "machine_fixture": st.column_config.TextColumn("Machine / fixture", width="medium"),
        "operation": st.column_config.TextColumn("Operation", disabled=True, width="large"),
        "characteristic_suffix": st.column_config.NumberColumn(
            "Characteristic suffix",
            min_value=1,
            step=1,
            format="%d",
            help=(
                "Optional positive whole-number override for the characteristic label. "
                "Leave blank to use the next available automatic suffix."
            ),
        ),
        "characteristic_placement": st.column_config.SelectboxColumn(
            "Characteristic type", options=list(PLACEMENTS),
            format_func=_characteristic_type_label,
            help="Choose Product or Process; Not assigned remains visibly incomplete.",
        ),
        "product_part_characteristic": st.column_config.TextColumn(
            "Product / Part characteristic", disabled=True, width="large"
        ),
        "process_characteristic": st.column_config.TextColumn(
            "Process characteristic", disabled=True, width="large"
        ),
        "classification": st.column_config.TextColumn(
            "CL", disabled=True,
            help="The current short Classification code from the linked PFMEA entry.",
        ),
        "specification_requirement": st.column_config.TextColumn(
            "Specification / Requirement", disabled=True, width="large"
        ),
        "measurement_evaluation": st.column_config.TextColumn(
            "Measurement / Evaluation", disabled=True, width="large"
        ),
        "sample_size": st.column_config.TextColumn("Sample size"),
        "sample_frequency": st.column_config.TextColumn("Sample frequency"),
        "who": st.column_config.TextColumn("Who"),
        "control_method": st.column_config.TextColumn(
            "Control method", width="large",
            help="Collaborator-authored MCP text; PFMEA control evidence is shown separately.",
        ),
        "decision_rule": st.column_config.TextColumn(
            "Decision rule / corrective action and reference documents", width="large",
            help="Collaborator-authored response and document references.",
        ),
        "source_review_required": st.column_config.CheckboxColumn(
            "Source review required", disabled=True
        ),
    }


def _grouped_control_plan_display(rows: pd.DataFrame) -> pd.DataFrame:
    """Apply operation-level blanks to a rendered copy without changing stored data."""
    display = rows.copy()
    if display.empty:
        return display
    if "operation" not in display:
        display["operation"] = ""
    if "machine_fixture" not in display:
        display["machine_fixture"] = ""
    display["pr_number"] = None
    for work_id, indexes in display.groupby(
        display["work_element_id"].astype(str), sort=False
    ).groups.items():
        group_indexes = list(indexes)
        if not work_id or not group_indexes:
            continue
        first = group_indexes[0]
        display.at[first, "pr_number"] = normalize_control_plan_pr_number(
            display.at[first, "operation_pr_number"]
        )
        for index in group_indexes[1:]:
            display.at[index, "operation"] = ""
        machine_values = {
            str(display.at[index, "machine_fixture"] or "").strip()
            for index in group_indexes
        }
        if len(machine_values) <= 1:
            for index in group_indexes[1:]:
                display.at[index, "machine_fixture"] = ""
    return display


def _display_first_pr_numbers(rows: pd.DataFrame) -> pd.DataFrame:
    """Backward-compatible alias for the operation-group display helper."""
    return _grouped_control_plan_display(rows)


def _rebuild_characteristic_numbers(rows: pd.DataFrame) -> pd.DataFrame:
    """Refresh derived characteristic prefixes from Process numbers and suffixes."""
    return rebuild_control_plan_characteristic_numbers(rows)


def _operations_in_projection_order(rows: pd.DataFrame) -> list[str]:
    """Return each active Process-step identity once in live projection order."""
    if rows.empty or "work_element_id" not in rows:
        return []
    ordered = rows.copy()
    if "projection_order" in ordered:
        ordered = ordered.sort_values(
            "projection_order", kind="stable", na_position="last"
        )
    return list(
        dict.fromkeys(
            str(value or "").strip()
            for value in ordered["work_element_id"].tolist()
            if str(value or "").strip()
        )
    )


def _op_id_number_mismatches(rows: pd.DataFrame) -> list[str]:
    """Identify active operations not numbered 1.0, 2.0, 3.0 in live order."""
    mismatches: list[str] = []
    for position, work_id in enumerate(_operations_in_projection_order(rows), start=1):
        operation_rows = rows.loc[rows["work_element_id"].astype(str).eq(work_id)]
        values = {
            normalize_control_plan_pr_number(value)
            for value in operation_rows["operation_pr_number"].tolist()
        }
        if values != {float(position)}:
            mismatches.append(work_id)
    return mismatches


def _renumber_operations_by_op_id(rows: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Stage sequential Process numbers across all active operations."""
    updated = rows.copy()
    operation_ids = _operations_in_projection_order(updated)
    for position, work_id in enumerate(operation_ids, start=1):
        mask = updated["work_element_id"].astype(str).eq(work_id)
        updated.loc[mask, "operation_pr_number"] = float(position)
        updated.loc[mask, "pr_number"] = float(position)
    return _rebuild_characteristic_numbers(updated), len(operation_ids)


def _apply_pr_number_editor_changes(
    rows: pd.DataFrame,
    editor_rows: pd.DataFrame,
    editor_state: dict,
) -> tuple[pd.DataFrame, list[str]]:
    """Propagate non-conflicting Pr. Nº edits by hidden Process-step identity."""
    requested: dict[str, list[float | None]] = {}
    for raw_position, changes in (editor_state.get("edited_rows") or {}).items():
        if "pr_number" not in (changes or {}):
            continue
        try:
            position = int(raw_position)
        except (TypeError, ValueError):
            continue
        if not 0 <= position < len(editor_rows):
            continue
        work_id = str(editor_rows.iloc[position].get("work_element_id") or "").strip()
        if work_id:
            requested.setdefault(work_id, []).append(
                normalize_control_plan_pr_number(changes.get("pr_number"))
            )
    conflicts: list[str] = []
    updated = rows.copy()
    for work_id, values in requested.items():
        distinct: list[float | None] = []
        for value in values:
            if value not in distinct:
                distinct.append(value)
        if len(distinct) > 1:
            conflicts.append(work_id)
            continue
        mask = updated["work_element_id"].astype(str).eq(work_id)
        updated.loc[mask, "operation_pr_number"] = distinct[0]
        updated.loc[mask, "pr_number"] = distinct[0]
    return _rebuild_characteristic_numbers(updated), conflicts


def _restore_grouped_display_values(
    visible_rows: pd.DataFrame,
    editor_rows: pd.DataFrame,
    edited_rows: pd.DataFrame,
    editor_state: dict,
) -> pd.DataFrame:
    """Restore values blanked only for grouped presentation before persistence."""
    restored = edited_rows.copy()
    changes_by_position = {
        int(position): changes or {}
        for position, changes in (editor_state.get("edited_rows") or {}).items()
        if str(position).lstrip("-").isdigit()
    }
    for position in range(min(len(visible_rows), len(restored))):
        changes = changes_by_position.get(position, {})
        for column in ("operation", "machine_fixture"):
            if column not in changes and column in restored and column in visible_rows:
                restored.iat[position, restored.columns.get_loc(column)] = (
                    visible_rows.iloc[position].get(column)
                )
    return restored


def _apply_characteristic_suffix_editor_changes(
    rows: pd.DataFrame,
    editor_rows: pd.DataFrame,
    editor_state: dict,
) -> pd.DataFrame:
    """Apply suffix edits by stable projection identity and rebuild derived labels."""
    updated = rows.copy()
    for raw_position, changes in (editor_state.get("edited_rows") or {}).items():
        if "characteristic_suffix" not in (changes or {}):
            continue
        try:
            position = int(raw_position)
        except (TypeError, ValueError):
            continue
        if not 0 <= position < len(editor_rows):
            continue
        projection_key = str(
            editor_rows.iloc[position].get("projection_key") or ""
        ).strip()
        if not projection_key:
            continue
        suffix = normalize_control_plan_characteristic_suffix(
            changes.get("characteristic_suffix")
        )
        updated.loc[
            updated["projection_key"].astype(str).eq(projection_key),
            "characteristic_suffix",
        ] = suffix
    return _rebuild_characteristic_numbers(updated)


def _duplicate_pr_numbers(rows: pd.DataFrame) -> list[dict]:
    """Return duplicate displayed Process numbers used by different operations."""
    operations: dict[str, dict] = {}
    for _, row in rows.iterrows():
        work_id = str(row.get("work_element_id") or "").strip()
        if not work_id or work_id in operations:
            continue
        number = normalize_control_plan_pr_number(row.get("operation_pr_number"))
        if number is None:
            continue
        operations[work_id] = {
            "work_element_id": work_id,
            "pr_number": number,
            "operation": str(row.get("operation") or "Unnamed operation"),
        }
    by_number: dict[float, list[dict]] = {}
    for operation in operations.values():
        by_number.setdefault(operation["pr_number"], []).append(operation)
    return [
        {"pr_number": number, "operations": values}
        for number, values in sorted(by_number.items())
        if len(values) > 1
    ]


def _duplicate_characteristic_suffixes(rows: pd.DataFrame) -> list[dict]:
    """Return duplicate manual suffixes used within one Process operation."""
    grouped: dict[tuple[str, int], list[dict]] = {}
    for _, row in rows.iterrows():
        work_id = str(row.get("work_element_id") or "").strip()
        suffix = normalize_control_plan_characteristic_suffix(
            row.get("characteristic_suffix")
        )
        if not work_id or suffix is None:
            continue
        grouped.setdefault((work_id, suffix), []).append(
            {
                "projection_key": str(row.get("projection_key") or ""),
                "operation": str(row.get("operation") or "Unnamed operation"),
                "description": str(
                    row.get("source_description_snapshot") or "Unnamed characteristic"
                ),
            }
        )
    return [
        {
            "work_element_id": work_id,
            "characteristic_suffix": suffix,
            "items": items,
        }
        for (work_id, suffix), items in grouped.items()
        if len(items) > 1
    ]


def _persist_control_plan_draft(pending: dict) -> None:
    project_id = str(pending["project_id"])
    scenario_id = str(pending["scenario_id"])
    result = save_control_plan_rows(
        project_id, scenario_id, pd.DataFrame(pending.get("rows", []))
    )
    renumbered_operation_count = int(pending.get("renumbered_operation_count") or 0)
    if renumbered_operation_count:
        record_audit_event(
            project_id,
            "Control Plan",
            "Save & Refresh",
            int(result.get("row_count", 0)),
            st.session_state.get("current_editor", ""),
            {
                "scenario_id": scenario_id,
                "affected_ids": result.get("affected_ids", []),
                "store_timestamp": result.get("timestamp", ""),
                "process_numbering_version": PROCESS_NUMBERING_VERSION,
                "renumbered_by_op_id": True,
                "renumbered_operation_count": renumbered_operation_count,
            },
        )
    else:
        _audit(project_id, "Save & Refresh", result, scenario_id)
    draft_key = str(pending.get("draft_key") or "")
    editor_key = str(pending.get("editor_key") or "")
    st.session_state.pop(PENDING_DUPLICATE_NUMBER_KEY, None)
    if draft_key:
        st.session_state.pop(draft_key, None)
        st.session_state.pop(f"{draft_key}_pr_conflicts", None)
        st.session_state.pop(f"{draft_key}_op_id_renumber_count", None)
    if editor_key:
        request_table_editor_reset(editor_key)
    st.toast("Saved Control Plan working draft", icon=":material/check_circle:")
    st.rerun()


@st.dialog("Save duplicate Pr. Nº values?", dismissible=False)
def _confirm_duplicate_pr_numbers() -> None:
    pending = st.session_state.get(PENDING_DUPLICATE_NUMBER_KEY) or {}
    scenario_changed = str(st.session_state.get("scenario_id") or "") != str(
        pending.get("scenario_id") or ""
    )
    st.warning(
        "Different Process operations use the same Pr. Nº. This is allowed, but "
        "review the duplicate document numbers before saving."
    )
    for duplicate in pending.get("duplicates", []):
        labels = "; ".join(
            str(operation.get("operation") or "Unnamed operation")
            for operation in duplicate.get("operations", [])
        )
        st.write(f"- {float(duplicate['pr_number']):.1f}: {labels}")
    for duplicate in pending.get("suffix_duplicates", []):
        items = duplicate.get("items", [])
        operation = str(
            (items[0] if items else {}).get("operation") or "Unnamed operation"
        )
        descriptions = "; ".join(
            str(item.get("description") or "Unnamed characteristic")
            for item in items
        )
        st.warning(
            "Duplicate manual Characteristic suffix "
            f"{int(duplicate['characteristic_suffix'])} in {operation}: {descriptions}. "
            "This is allowed only after review."
        )
    if scenario_changed:
        st.error("The active scenario changed. Cancel and review the current draft again.")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_control_plan_duplicate_numbers"):
        st.session_state.pop(PENDING_DUPLICATE_NUMBER_KEY, None)
        st.rerun()
    if actions.button(
        "Save anyway",
        type="primary",
        icon=":material/save:",
        disabled=scenario_changed,
        key="save_control_plan_duplicate_numbers_anyway",
    ):
        try:
            _persist_control_plan_draft(pending)
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Exclude selected Control Plan items?", dismissible=False)
def _confirm_exclusion() -> None:
    pending = st.session_state.get(PENDING_EXCLUSION_KEY) or {}
    scenario_changed = str(st.session_state.get("scenario_id") or "") != str(
        pending.get("scenario_id") or ""
    )
    st.warning(
        "Exclude the selected working-draft item(s)? Their MCP-owned content will be "
        "preserved and can be restored from the review area."
    )
    for label in pending.get("labels", []):
        st.write(f"- {label}")
    if scenario_changed:
        st.error("The active scenario changed. Cancel and select the items again.")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_control_plan_exclusion"):
        editor_key = str(pending.get("editor_key") or "")
        st.session_state.pop(PENDING_EXCLUSION_KEY, None)
        if editor_key:
            request_table_editor_reset(editor_key)
        st.rerun()
    if actions.button(
        "Exclude",
        type="primary",
        icon=":material/delete:",
        disabled=scenario_changed,
        key="destructive_confirm_control_plan_exclusion",
    ):
        try:
            result = exclude_control_plan_projection_keys(
                str(pending["project_id"]), str(pending["scenario_id"]),
                list(pending["projection_keys"]),
            )
            _audit(str(pending["project_id"]), "Exclude items", result, str(pending["scenario_id"]))
            editor_key = str(pending.get("editor_key") or "")
            st.session_state.pop(PENDING_EXCLUSION_KEY, None)
            if editor_key:
                request_table_editor_reset(editor_key)
            st.toast("Excluded Control Plan working-draft item(s)", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Relink Control Plan source?", dismissible=False)
def _confirm_relink() -> None:
    pending = st.session_state.get(PENDING_RELINK_KEY) or {}
    scenario_changed = str(st.session_state.get("scenario_id") or "") != str(
        pending.get("scenario_id") or ""
    )
    st.warning(
        "Relink this retained working-draft item to the selected compatible "
        "published Quality assignment?"
    )
    st.write(str(pending.get("item_label") or "Control Plan item"))
    st.write(str(pending.get("assignment_label") or "Compatible Quality assignment"))
    if scenario_changed:
        st.error("The active scenario changed. Cancel and select the item again.")
    actions = st.container(horizontal=True)
    if actions.button("Cancel", key="cancel_control_plan_relink"):
        st.session_state.pop(PENDING_RELINK_KEY, None)
        st.rerun()
    if actions.button(
        "Relink",
        type="primary",
        icon=":material/link:",
        disabled=scenario_changed,
        key="confirm_control_plan_relink",
    ):
        try:
            result = relink_control_plan_item(
                str(pending["project_id"]),
                str(pending["scenario_id"]),
                str(pending["item_id"]),
                str(pending["assignment_id"]),
            )
            _audit(
                str(pending["project_id"]),
                "Relink Quality source",
                result,
                str(pending["scenario_id"]),
            )
            st.session_state.pop(PENDING_RELINK_KEY, None)
            st.toast("Relinked Control Plan source", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def _render_evidence(project_id: str, scenario_id: str, rows: pd.DataFrame) -> None:
    with st.expander("View PFMEA control and action evidence"):
        if rows.empty:
            st.caption("No active Control Plan items are available.")
            return
        choices = rows.drop_duplicates(subset=["pfmea_entry_id"]).copy()
        by_id = {str(row["pfmea_entry_id"]): row for _, row in choices.iterrows()}
        selected = st.selectbox(
            "Control Plan operation",
            options=list(by_id),
            format_func=lambda entry_id: (
                f"{by_id[entry_id]['pr_number'] or 'Operation'} — "
                f"{by_id[entry_id]['operation']} — {_classification_label(by_id[entry_id]['classification'])}"
            ),
            key=f"control_plan_evidence_{project_id}_{scenario_id}",
            help="Choose an operation to review its PFMEA evidence. This panel is read-only.",
        )
        evidence = control_plan_evidence(project_id, scenario_id, str(selected))
        for heading in ("Prevention", "Detection", "Actions"):
            st.markdown(f"**{heading}**")
            values = evidence.get(heading) or []
            if values:
                for value in values:
                    st.write(f"- {value}")
            else:
                st.caption(f"No {heading.lower()} evidence recorded.")


def _render_review_area(project_id: str, scenario_id: str) -> None:
    with st.expander("Review excluded and source-ineligible items"):
        rows = control_plan_review_items(project_id, scenario_id)
        if rows.empty:
            st.caption("No excluded, orphaned, or source-ineligible Control Plan items.")
            return
        display = rows.copy()
        display["item_label"] = display.apply(
            lambda row: (
                f"{row.get('process_pitch_snapshot') or 'Unassigned'} — "
                f"{row.get('process_operation_snapshot') or 'Unnamed operation'} — "
                f"{row.get('source_description_snapshot') or 'No characteristic'}"
            ), axis=1,
        )
        event = selectable_dataframe(
            display[["id", "item_label", "review_reason", "source_review_required"]],
            key=f"control_plan_review_{project_id}_{scenario_id}",
            selection_mode="single-row",
            hide_index=True,
            column_config={
                "id": None, "item_label": "Control Plan item", "review_reason": "Reason",
                "source_review_required": "Review required",
            },
        )
        selected_positions = list(event.selection.rows)
        if not selected_positions:
            return
        selected = display.iloc[int(selected_positions[0])]
        item_id = str(selected["id"])
        actions = st.container(horizontal=True)
        if bool(selected.get("excluded")) and actions.button(
            "Restore selected", icon=":material/restore:",
            key=f"restore_control_plan_{item_id}",
        ):
            try:
                result = restore_control_plan_item(project_id, scenario_id, item_id)
                _audit(project_id, "Restore item", result, scenario_id)
                st.toast("Restored Control Plan item", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if (
            str(selected.get("source_kind")) == "quality"
            and not str(selected.get("quality_requirement_assignment_id") or "").strip()
        ):
            candidates = control_plan_relink_candidates(project_id, scenario_id, item_id)
            if candidates.empty:
                st.caption("No compatible published Quality assignment is available for relinking.")
            else:
                labels = {
                    str(row["id"]): f"{row['unique_identifier']} — {row['description']}"
                    for _, row in candidates.iterrows()
                }
                assignment_id = st.selectbox(
                    "Compatible Quality assignment", options=list(labels),
                    format_func=lambda value: labels[value],
                    key=f"control_plan_relink_choice_{item_id}",
                )
                if st.button(
                    "Relink selected item", icon=":material/link:",
                    key=f"control_plan_relink_{item_id}",
                ):
                    st.session_state[PENDING_RELINK_KEY] = {
                        "project_id": project_id,
                        "scenario_id": scenario_id,
                        "item_id": item_id,
                        "assignment_id": str(assignment_id),
                        "item_label": str(selected["item_label"]),
                        "assignment_label": labels[str(assignment_id)],
                    }
                    st.rerun()


def _render_control_plan_characteristics(project_id: str, scenario_id: str) -> None:
    """Render the editable Characteristics table peer view."""
    source = control_plan_projection(project_id, scenario_id)
    if source.empty:
        st.info(
            "Classify a PFMEA entry to create a Control Plan line. Published Quality controls "
            "selected in that PFMEA entry create separate characteristic lines."
        )
        _render_review_area(project_id, scenario_id)
        return
    persisted_active = source.loc[~source["excluded"].fillna(False)].copy()
    logical_key = f"control_plan_editor_{project_id}_{scenario_id}"
    editor_key = apply_pending_table_editor_reset(logical_key)
    draft_key = f"control_plan_draft_{project_id}_{scenario_id}"
    draft = st.session_state.get(draft_key)
    active = draft.copy() if isinstance(draft, pd.DataFrame) else persisted_active
    for column, default in (
        ("characteristic_suffix", None),
        ("effective_characteristic_suffix", None),
        ("reserved_characteristic_suffixes", ""),
    ):
        if column not in active:
            active[column] = default
    if "projection_order" in active:
        active = active.sort_values(
            "projection_order", kind="stable", na_position="last"
        ).reset_index(drop=True)
    active["characteristic_type_filter"] = active["characteristic_placement"].apply(
        _characteristic_type_label
    )
    editable_table_heading("Control Plan characteristics")
    visible = filter_table(
        active,
        key=f"control_plan_filters_{project_id}_{scenario_id}",
        dropdown_columns=["classification", "characteristic_type_filter", "source_review_required"],
        search_columns=[
            "op_id", "operation", "product_part_characteristic", "process_characteristic",
            "machine_fixture", "control_method", "decision_rule",
        ],
        labels={
            "classification": "CL", "characteristic_type_filter": "Characteristic type",
            "source_review_required": "Source review required",
        },
        reset_widget_keys=[editor_key],
    )
    editor_rows = _grouped_control_plan_display(visible)
    edited = st.data_editor(
        editor_rows,
        key=editor_key,
        num_rows="dynamic",
        hide_index=True,
        height=520,
        row_height=88,
        column_order=VISIBLE_COLUMNS,
        column_config=_column_config(),
        disabled=[column for column in VISIBLE_COLUMNS if column not in EDITABLE_COLUMNS],
    )
    editor_state = st.session_state.get(editor_key, {}) or {}
    edited_for_merge = _restore_grouped_display_values(
        visible, editor_rows, edited, editor_state
    )
    complete = merge_filtered_edits(
        active, editor_rows, edited_for_merge, id_column="projection_key"
    )
    pr_number_edited = any(
        "pr_number" in (changes or {})
        for changes in (editor_state.get("edited_rows") or {}).values()
    )
    suffix_edited = any(
        "characteristic_suffix" in (changes or {})
        for changes in (editor_state.get("edited_rows") or {}).values()
    )
    placement_edited = any(
        "characteristic_placement" in (changes or {})
        for changes in (editor_state.get("edited_rows") or {}).values()
    )
    pr_conflicts: list[str] = []
    if pr_number_edited or suffix_edited or placement_edited:
        try:
            if pr_number_edited:
                complete, pr_conflicts = _apply_pr_number_editor_changes(
                    complete, editor_rows, editor_state
                )
            if suffix_edited:
                complete = _apply_characteristic_suffix_editor_changes(
                    complete, editor_rows, editor_state
                )
            if placement_edited and not suffix_edited:
                complete = _rebuild_characteristic_numbers(complete)
        except ValueError as exc:
            pr_conflicts = [str(exc)]
        if pr_conflicts:
            st.session_state[f"{draft_key}_pr_conflicts"] = pr_conflicts
        else:
            st.session_state.pop(f"{draft_key}_pr_conflicts", None)
            st.session_state[draft_key] = complete
            request_table_editor_reset(editor_key)
            st.rerun()
    current_pr_conflicts = st.session_state.get(f"{draft_key}_pr_conflicts") or []
    if current_pr_conflicts:
        st.error(
            "Conflicting Pr. Nº values were entered for the same Process operation. "
            "Use one value for all of that operation's characteristic lines before saving."
        )
    selected_for_action = native_selected_rows(
        editor_rows, editor_key=editor_key, id_column="projection_key"
    )
    order_mismatches = _op_id_number_mismatches(complete)
    if order_mismatches:
        st.warning(
            f"Pr. Nº does not match the current Op ID order for "
            f"{len(order_mismatches)} operation(s). Renumber to stage 1.0, 2.0, 3.0… "
            "across the complete active Control Plan."
        )
    if st.button(
        "Renumber Pr. Nº by Op ID",
        icon=":material/format_list_numbered:",
        disabled=not order_mismatches or not selected_for_action.empty,
        help=(
            "Stages sequential Process numbers for every active operation in live Op ID "
            "order, including rows hidden by filters. Save & Refresh persists the result."
        ),
        key=f"control_plan_renumber_op_id_{project_id}_{scenario_id}",
    ):
        renumbered, operation_count = _renumber_operations_by_op_id(complete)
        st.session_state[draft_key] = renumbered
        st.session_state[f"{draft_key}_op_id_renumber_count"] = operation_count
        st.session_state.pop(f"{draft_key}_pr_conflicts", None)
        request_table_editor_reset(editor_key)
        st.toast(
            f"Staged Op ID renumbering for {operation_count} operation(s)",
            icon=":material/format_list_numbered:",
        )
        st.rerun()
    if not selected_for_action.empty:
        st.info("Clear selected Control Plan rows before renumbering by Op ID.")
    unassigned = complete.loc[
        complete["characteristic_placement"].fillna("").astype(str).str.strip().eq("")
    ]
    if not unassigned.empty:
        labels = [
            f"{row.get('station_pitch') or 'Unassigned'} — "
            f"{row.get('operation') or 'Unnamed operation'} — "
            f"{row.get('source_description_snapshot') or 'Unnamed characteristic'}"
            for _, row in unassigned.head(5).iterrows()
        ]
        remainder = len(unassigned) - len(labels)
        suffix = f"; and {remainder} more" if remainder else ""
        st.warning(
            "Characteristic type is Not assigned for: " + "; ".join(labels) + suffix
        )
    footer = editable_table_footer(
        editor_key=editor_key,
        key_prefix=f"control_plan_{project_id}_{scenario_id}",
        native_row_selection=True,
        additional_unsaved_changes=isinstance(draft, pd.DataFrame),
    )
    if footer.undo:
        st.session_state.pop(draft_key, None)
        st.session_state.pop(f"{draft_key}_pr_conflicts", None)
        st.session_state.pop(f"{draft_key}_op_id_renumber_count", None)
        st.session_state.pop(PENDING_DUPLICATE_NUMBER_KEY, None)
        request_table_editor_reset(editor_key)
        st.toast("Discarded unsaved Control Plan edits", icon=":material/undo:")
        st.rerun()
    if footer.save_and_refresh:
        selected = native_selected_rows(editor_rows, editor_key=editor_key, id_column="projection_key")
        if not selected.empty:
            st.warning("Clear selected Control Plan items before saving edits.")
        elif current_pr_conflicts:
            st.warning("Resolve the conflicting Pr. Nº values before saving.")
        else:
            try:
                complete = _rebuild_characteristic_numbers(complete)
                pending = {
                    "project_id": project_id,
                    "scenario_id": scenario_id,
                    "rows": complete.to_dict("records"),
                    "duplicates": _duplicate_pr_numbers(complete),
                    "suffix_duplicates": _duplicate_characteristic_suffixes(complete),
                    "renumbered_operation_count": int(
                        st.session_state.get(
                            f"{draft_key}_op_id_renumber_count", 0
                        )
                        or 0
                    ),
                    "draft_key": draft_key,
                    "editor_key": editor_key,
                }
                if pending["duplicates"] or pending["suffix_duplicates"]:
                    st.session_state[draft_key] = complete
                    st.session_state[PENDING_DUPLICATE_NUMBER_KEY] = pending
                else:
                    _persist_control_plan_draft(pending)
            except ValueError as exc:
                st.error(str(exc))
    export = editor_rows[VISIBLE_COLUMNS].rename(columns={
        "pr_number": "Pr. Nº", "station_pitch": "Station / Pitch",
        "op_id": "Op ID",
        "machine_fixture": "Machine / fixture",
        "operation": "Operation", "characteristic_suffix": "Characteristic suffix",
        "characteristic_placement": "Characteristic type",
        "product_part_characteristic": "Product / Part characteristic",
        "process_characteristic": "Process characteristic", "classification": "CL",
        "specification_requirement": "Specification / Requirement",
        "measurement_evaluation": "Measurement / Evaluation",
        "sample_size": "Sample size", "sample_frequency": "Sample frequency",
        "who": "Who", "control_method": "Control method",
        "decision_rule": "Decision rule / corrective action and reference documents",
        "source_review_required": "Source review required",
    })
    st.download_button(
        "Export filtered rows", data=dataframe_to_excel(export, "Control Plan"),
        file_name="control_plan_working_draft.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:", key=f"control_plan_export_{project_id}_{scenario_id}",
    )
    selected = native_selected_rows(editor_rows, editor_key=editor_key, id_column="projection_key")
    if not selected.empty and (
        table_has_unsaved_changes(editor_key, native_row_selection=True)
        or isinstance(draft, pd.DataFrame)
    ):
        st.warning("Save or undo other Control Plan edits before excluding selected items.")
    elif not selected.empty and not st.session_state.get(PENDING_EXCLUSION_KEY):
        st.session_state[PENDING_EXCLUSION_KEY] = {
            "project_id": project_id, "scenario_id": scenario_id,
            "projection_keys": selected["projection_key"].astype(str).tolist(),
            "labels": selected.apply(
                lambda row: f"{row['pr_number'] or 'Characteristic'} — {row['operation']}", axis=1
            ).tolist(),
            "editor_key": editor_key,
        }
        stage_native_delete_confirmation(editor_key)
    _render_evidence(project_id, scenario_id, active)
    _render_review_area(project_id, scenario_id)
    if st.session_state.get(PENDING_EXCLUSION_KEY):
        _confirm_exclusion()
    if st.session_state.get(PENDING_RELINK_KEY):
        _confirm_relink()
    if st.session_state.get(PENDING_DUPLICATE_NUMBER_KEY):
        _confirm_duplicate_pr_numbers()


def _filter_control_plan_flow(
    projection: dict,
    *,
    section: str = "All",
    pitch: str = "All",
    characteristic_type: str = "All",
    classification: str = "All",
    keyword: str = "",
) -> dict:
    """Apply presentation-only filters while retaining referentially valid edges."""
    lowered = keyword.strip().casefold()
    sections = projection.get("sections", [])
    pitches = projection.get("pitches", [])
    operations = projection.get("operations", [])
    characteristics = projection.get("characteristics", [])
    section_keys = {
        item["key"] for item in sections
        if section == "All" or item["name"] == section
    }
    pitch_keys = {
        item["key"] for item in pitches
        if (pitch == "All" or item["number"] == pitch)
        and (section == "All" or item.get("section_key") in section_keys)
    }
    candidate_operations = [
        item for item in operations
        if (section == "All" or item.get("section_key") in section_keys)
        and (pitch == "All" or item.get("pitch_key") in pitch_keys)
    ]
    candidate_keys = {item["key"] for item in candidate_operations}
    filtered_characteristics = [
        item for item in characteristics
        if item.get("operation_key") in candidate_keys
        and (characteristic_type == "All" or item.get("placement") == characteristic_type)
        and (classification == "All" or item.get("classification") == classification)
    ]
    if lowered:
        matching_characteristic_ops = {
            item["operation_key"] for item in filtered_characteristics
            if lowered in " ".join(
                str(item.get(name) or "") for name in (
                    "number", "description", "classification", "specification",
                    "evaluation", "control_method", "decision_rule",
                )
            ).casefold()
        }
        candidate_operations = [
            item for item in candidate_operations
            if item["key"] in matching_characteristic_ops
            or lowered in " ".join(
                str(item.get(name) or "") for name in (
                    "op_id", "operation", "station_pitch", "pitch", "pr_number",
                )
            ).casefold()
        ]
        candidate_keys = {item["key"] for item in candidate_operations}
        filtered_characteristics = [
            item for item in filtered_characteristics
            if item["operation_key"] in candidate_keys
        ]
    visible_section_keys = {item.get("section_key") for item in candidate_operations}
    visible_pitch_keys = {item.get("pitch_key") for item in candidate_operations}
    return {
        "sections": [item for item in sections if item["key"] in visible_section_keys],
        "section_edges": [
            edge for edge in projection.get("section_edges", [])
            if edge["from"] in visible_section_keys and edge["to"] in visible_section_keys
        ],
        "pitches": [item for item in pitches if item["key"] in visible_pitch_keys],
        "operations": candidate_operations,
        "characteristics": filtered_characteristics,
        "sequence_edges": [
            edge for edge in projection.get("sequence_edges", [])
            if edge["from"] in candidate_keys and edge["to"] in candidate_keys
        ],
        "feed_edges": [
            edge for edge in projection.get("feed_edges", [])
            if edge["from"] in candidate_keys and edge["to"] in candidate_keys
        ],
        "unresolved_feeds": [
            item for item in projection.get("unresolved_feeds", [])
            if item.get("pitch_key") in visible_pitch_keys
        ],
    }


@st.dialog("Control Plan characteristic", width="large")
def _control_plan_characteristic_dialog(item: dict) -> None:
    """Show one characteristic without exposing its internal relationship keys."""
    st.subheader(
        " ".join(value for value in (
            str(item.get("number") or "").strip(),
            str(item.get("description") or "Unnamed characteristic").strip(),
        ) if value)
    )
    st.caption(
        f"{str(item.get('placement') or 'unassigned').title()} characteristic · "
        f"CL {item.get('classification') or 'Unclassified'}"
    )
    details = pd.DataFrame([
        {"Field": "Specification / Requirement", "Value": item.get("specification") or "—"},
        {"Field": "Measurement / Evaluation", "Value": item.get("evaluation") or "—"},
        {"Field": "Sample size", "Value": item.get("sample_size") or "—"},
        {"Field": "Sample frequency", "Value": item.get("sample_frequency") or "—"},
        {"Field": "Who", "Value": item.get("who") or "—"},
        {"Field": "Control method", "Value": item.get("control_method") or "—"},
        {"Field": "Decision rule / corrective action", "Value": item.get("decision_rule") or "—"},
        {"Field": "Source review", "Value": "Required" if item.get("source_review_required") else "Current"},
    ])
    st.dataframe(details, hide_index=True)
    evidence = item.get("source_evidence") or {}
    st.markdown("**Source evidence**")
    for label in ("Prevention", "Detection", "Actions"):
        values = evidence.get(label) or []
        st.markdown(f"**{label}:** " + ("; ".join(values) if values else "None"))


def _render_control_plan_flow(project_id: str, scenario_id: str) -> None:
    """Render the read-only Process Flow Map peer view."""
    try:
        projection = control_plan_flow_projection(project_id, scenario_id)
    except ValueError as exc:
        st.warning(str(exc))
        return
    if not projection.get("operations"):
        st.info("Add Process at a Glance Work Elements to display the Process flow map.")
        return
    st.caption(
        "Read-only live view. Fishbone supplies structural grouping; Yamazumi feed routing "
        "supplies exact joins. Pr. Nº is shown for document context and never controls order."
    )
    sections = sorted({item["name"] for item in projection.get("sections", [])})
    pitches = sorted({item["number"] for item in projection.get("pitches", [])})
    classifications = sorted({
        item["classification"] for item in projection.get("characteristics", [])
        if item.get("classification")
    })
    filters = st.container(horizontal=True, vertical_alignment="bottom")
    keyword = filters.text_input(
        "Filter by keyword", key=f"control_plan_flow_keyword_{project_id}_{scenario_id}"
    )
    section = filters.selectbox(
        "Fishbone section", ["All", *sections],
        key=f"control_plan_flow_section_{project_id}_{scenario_id}",
    )
    pitch = filters.selectbox(
        "Pitch", ["All", *pitches], key=f"control_plan_flow_pitch_{project_id}_{scenario_id}"
    )
    characteristic_type = filters.selectbox(
        "Characteristic type", ["All", "product", "process", "unassigned"],
        format_func=lambda value: value.title() if value != "All" else value,
        key=f"control_plan_flow_type_{project_id}_{scenario_id}",
    )
    classification = filters.selectbox(
        "Classification", ["All", *classifications],
        key=f"control_plan_flow_classification_{project_id}_{scenario_id}",
    )
    filtered = _filter_control_plan_flow(
        projection,
        section=section,
        pitch=pitch,
        characteristic_type=characteristic_type,
        classification=classification,
        keyword=keyword,
    )
    st.caption(
        "White rectangle = Process operation · Blue oval = Product characteristic · "
        "Green oval = Process characteristic · Amber outline = type not assigned"
    )
    component_key = f"control_plan_flow_component_{project_id}_{scenario_id}"
    request_key = f"control_plan_flow_detail_request_{project_id}_{scenario_id}"

    def stage_detail() -> None:
        event = st.session_state.get(component_key, {}) or {}
        detail = event.get("detail") or {}
        selected_key = str(detail.get("key") or "")
        valid_keys = {item["key"] for item in projection.get("characteristics", [])}
        if selected_key in valid_keys:
            st.session_state[request_key] = selected_key

    control_plan_process_flow(
        filtered, key=component_key, on_detail_change=stage_detail
    )
    selected_key = st.session_state.pop(request_key, "")
    selected = next(
        (item for item in projection.get("characteristics", [])
         if item["key"] == selected_key),
        None,
    )
    if selected:
        _control_plan_characteristic_dialog(selected)


def render_control_plan_tab(project_id: str, scenario_id: str, scenario_name: str) -> None:
    """Render the editable MCP table and its read-only Process Flow Map peer view."""
    heading = st.container(horizontal=True, vertical_alignment="center")
    heading.subheader("Manufacturing Control Plan working draft")
    scope_badge(heading, scope="scenario", scenario_name=scenario_name)
    st.caption(
        "This is an editable working draft only. Document headers, revisions, approvals, "
        "issued status, and Word export remain deferred."
    )
    try:
        migration = migrate_pfmea_classifications(
            project_id, st.session_state.get("current_editor", "")
        )
        number_migration = migrate_control_plan_pr_numbers(
            project_id, st.session_state.get("current_editor", "")
        )
    except ValueError as exc:
        st.error(str(exc))
        st.info("Enter Current editor to complete the pending one-time migration.")
        return
    if migration.get("row_count"):
        st.toast(
            f"Updated {migration['row_count']} legacy PFMEA Classification record(s)",
            icon=":material/check_circle:",
        )
    if number_migration.get("row_count"):
        st.toast(
            f"Backfilled Pr. Nº for {number_migration['operation_count']} Process operation(s)",
            icon=":material/check_circle:",
        )
    _render_classification_legend()
    characteristics_tab, flow_tab = st.tabs(["Characteristics table", "Process flow map"])
    with characteristics_tab:
        _render_control_plan_characteristics(project_id, scenario_id)
    with flow_tab:
        _render_control_plan_flow(project_id, scenario_id)
