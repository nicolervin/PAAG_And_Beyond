"""Scenario-specific Manufacturing Control Plan working-draft persistence.

The active table is a live projection of classified PFMEA entries and the
published Quality assignments explicitly selected as PFMEA controls. Only
collaborator-authored MCP fields, exclusion, and source acknowledgement persist.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd


PLACEMENTS = ("", "Product / Part", "Process")
SOURCE_KINDS = ("quality", "pfmea_only")
PROCESS_NUMBERING_VERSION = 1


def _store():
    from utils import store

    return store


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def init_control_plan_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS control_plan_items (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            pfmea_entry_id TEXT NOT NULL REFERENCES pfmea_entries(id) ON DELETE CASCADE,
            source_kind TEXT NOT NULL CHECK (source_kind IN ('quality','pfmea_only')),
            quality_requirement_assignment_id TEXT
                REFERENCES quality_requirement_assignments(id) ON DELETE SET NULL,
            quality_requirement_id TEXT REFERENCES quality_requirements(id) ON DELETE SET NULL,
            source_quality_requirement_id_snapshot TEXT NOT NULL DEFAULT '',
            source_unique_identifier_snapshot TEXT NOT NULL DEFAULT '',
            source_description_snapshot TEXT NOT NULL DEFAULT '',
            characteristic_placement TEXT NOT NULL DEFAULT ''
                CHECK (characteristic_placement IN ('','Product / Part','Process')),
            machine_fixture TEXT NOT NULL DEFAULT '',
            sample_size TEXT NOT NULL DEFAULT '',
            sample_frequency TEXT NOT NULL DEFAULT '',
            who TEXT NOT NULL DEFAULT '',
            control_method TEXT NOT NULL DEFAULT '',
            decision_rule TEXT NOT NULL DEFAULT '',
            excluded INTEGER NOT NULL DEFAULT 0 CHECK (excluded IN (0,1)),
            source_fingerprint_snapshot TEXT NOT NULL DEFAULT '',
            source_review_required INTEGER NOT NULL DEFAULT 0
                CHECK (source_review_required IN (0,1)),
            sequence INTEGER NOT NULL DEFAULT 10,
            pr_number REAL,
            characteristic_suffix INTEGER
                CHECK (characteristic_suffix IS NULL OR
                       (typeof(characteristic_suffix)='integer' AND characteristic_suffix > 0)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_control_plan_items_scenario
            ON control_plan_items(project_id, scenario_id, pfmea_entry_id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_control_plan_quality_item
            ON control_plan_items(project_id, scenario_id, pfmea_entry_id,
                                  source_quality_requirement_id_snapshot)
            WHERE source_kind='quality';
        CREATE UNIQUE INDEX IF NOT EXISTS uq_control_plan_fallback_item
            ON control_plan_items(project_id, scenario_id, pfmea_entry_id)
            WHERE source_kind='pfmea_only';
        """
    )
    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(control_plan_items)").fetchall()
    }
    if "sequence" not in columns:
        conn.execute(
            "ALTER TABLE control_plan_items ADD COLUMN sequence INTEGER NOT NULL DEFAULT 10"
        )
    if "pr_number" not in columns:
        conn.execute("ALTER TABLE control_plan_items ADD COLUMN pr_number REAL")
    if "characteristic_suffix" not in columns:
        conn.execute(
            "ALTER TABLE control_plan_items ADD COLUMN characteristic_suffix INTEGER "
            "CHECK (characteristic_suffix IS NULL OR "
            "(typeof(characteristic_suffix)='integer' AND characteristic_suffix > 0))"
        )


def _pr_number(value) -> float | None:
    """Return a finite one-decimal Process number or ``None`` for a blank value."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and not value.strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Pr. Nº must be a finite decimal or blank.") from exc
    if not math.isfinite(number):
        raise ValueError("Pr. Nº must be a finite decimal or blank.")
    return round(number, 1)


def normalize_control_plan_pr_number(value) -> float | None:
    """Public validator used by the Control Plan editor and focused tests."""
    return _pr_number(value)


def _characteristic_suffix(value) -> int | None:
    """Return a positive whole-number suffix or ``None`` for a blank value."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, bool):
        raise ValueError("Characteristic suffix must be a positive whole number or blank.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Characteristic suffix must be a positive whole number or blank."
        ) from exc
    if not math.isfinite(number) or not number.is_integer() or number <= 0:
        raise ValueError("Characteristic suffix must be a positive whole number or blank.")
    return int(number)


def normalize_control_plan_characteristic_suffix(value) -> int | None:
    """Public validator used by the Control Plan editor and focused tests."""
    return _characteristic_suffix(value)


def _characteristic_number(pr_number, suffix: int | None) -> str:
    base = _pr_number(pr_number)
    if base is None or suffix is None:
        return ""
    base_text = f"{base:.1f}"
    if base_text.endswith(".0"):
        base_text = base_text[:-2]
    return f"{base_text}.{int(suffix)}"


def rebuild_control_plan_characteristic_numbers(rows: pd.DataFrame) -> pd.DataFrame:
    """Build display labels without changing stable characteristic order.

    Manual suffixes are reserved first. Blank suffixes receive the lowest available
    positive integer in the existing projection order. The effective suffix is a
    presentation value; only ``characteristic_suffix`` is persisted.
    """
    updated = rows.copy()
    if updated.empty:
        return updated
    order = (
        pd.to_numeric(updated.get("projection_order"), errors="coerce")
        if "projection_order" in updated
        else pd.Series(range(len(updated)), index=updated.index)
    )
    ordered_indexes = order.sort_values(kind="stable", na_position="last").index
    reserved: dict[str, set[int]] = {}
    for index in ordered_indexes:
        row = updated.loc[index]
        work_id = _text(row.get("work_element_id"))
        stored = _text(row.get("reserved_characteristic_suffixes"))
        for raw in stored.split(",") if stored else []:
            try:
                reserved.setdefault(work_id, set()).add(_characteristic_suffix(raw))
            except ValueError:
                continue
        suffix = _characteristic_suffix(row.get("characteristic_suffix"))
        if suffix is not None:
            reserved.setdefault(work_id, set()).add(suffix)
    assigned_auto: dict[str, set[int]] = {}
    for index in ordered_indexes:
        row = updated.loc[index]
        work_id = _text(row.get("work_element_id"))
        suffix = _characteristic_suffix(row.get("characteristic_suffix"))
        if suffix is None:
            suffix = 1
            unavailable = reserved.get(work_id, set()) | assigned_auto.get(work_id, set())
            while suffix in unavailable:
                suffix += 1
            assigned_auto.setdefault(work_id, set()).add(suffix)
        updated.at[index, "effective_characteristic_suffix"] = suffix
        prefix = _characteristic_number(row.get("operation_pr_number"), suffix)
        description = _text(row.get("source_description_snapshot"))
        display_value = f"{prefix} {description}".strip() if prefix else description
        placement = _text(row.get("characteristic_placement"))
        updated.at[index, "product_part_characteristic"] = (
            display_value if placement == "Product / Part" else ""
        )
        updated.at[index, "process_characteristic"] = (
            display_value if placement == "Process" else ""
        )
    return updated


def suggest_control_plan_pr_numbers(
    operation_ids: list[str],
    existing_by_operation: dict[str, object],
    occupied_numbers: list[object] | None = None,
) -> dict[str, float]:
    """Suggest missing Process numbers without changing persisted data."""
    all_ordered = list(dict.fromkeys(str(value) for value in operation_ids if str(value)))
    fixed_blank = {
        operation_id
        for operation_id in all_ordered
        if operation_id in existing_by_operation
        and _pr_number(existing_by_operation.get(operation_id)) is None
    }
    ordered = [operation_id for operation_id in all_ordered if operation_id not in fixed_blank]
    existing = {
        operation_id: _pr_number(existing_by_operation.get(operation_id))
        for operation_id in ordered
    }
    occupied = {
        number
        for number in (_pr_number(value) for value in (occupied_numbers or []))
        if number is not None
    }
    occupied.update(number for number in existing.values() if number is not None)
    suggestions: dict[str, float] = {}

    def append_after_max(run: list[str]) -> None:
        maximum = max([0.0, *occupied, *suggestions.values()])
        for offset, operation_id in enumerate(run, start=1):
            candidate = round(maximum + (10.0 * offset), 1)
            while candidate in occupied or candidate in suggestions.values():
                candidate = round(candidate + 10.0, 1)
            suggestions[operation_id] = candidate
            occupied.add(candidate)

    known_positions = [
        index for index, operation_id in enumerate(ordered)
        if existing[operation_id] is not None
    ]
    if not known_positions:
        if occupied:
            append_after_max(ordered)
        else:
            for index, operation_id in enumerate(ordered, start=1):
                suggestions[operation_id] = float(index * 10)
        return suggestions

    boundaries = [-1, *known_positions, len(ordered)]
    for boundary_index in range(len(boundaries) - 1):
        left_position = boundaries[boundary_index]
        right_position = boundaries[boundary_index + 1]
        run = ordered[left_position + 1:right_position]
        if not run:
            continue
        left = existing[ordered[left_position]] if left_position >= 0 else None
        right = existing[ordered[right_position]] if right_position < len(ordered) else None
        candidates: list[float] = []
        if left is None and right is not None and right > 0:
            interval = right / (len(run) + 1)
            candidates = [round(interval * index, 1) for index in range(1, len(run) + 1)]
        elif left is not None and right is not None and right > left:
            interval = (right - left) / (len(run) + 1)
            candidates = [
                round(left + (interval * index), 1)
                for index in range(1, len(run) + 1)
            ]
        elif left is not None and right is None:
            base = max([0.0, left, *occupied, *suggestions.values()])
            candidates = [round(base + (10.0 * index), 1) for index in range(1, len(run) + 1)]

        valid = (
            len(candidates) == len(run)
            and len(set(candidates)) == len(candidates)
            and all(candidate not in occupied for candidate in candidates)
            and (left is None or all(candidate > left for candidate in candidates))
            and (right is None or all(candidate < right for candidate in candidates))
        )
        if not valid:
            append_after_max(run)
            continue
        for operation_id, candidate in zip(run, candidates):
            suggestions[operation_id] = candidate
            occupied.add(candidate)
    return suggestions


def _numbering_version_recorded(conn: sqlite3.Connection, project_id: str) -> bool:
    rows = conn.execute(
        """SELECT details FROM audit_log
           WHERE project_id=? AND table_name='Control Plan'""",
        (project_id,),
    ).fetchall()
    for row in rows:
        try:
            details = json.loads(str(row["details"] or "{}"))
        except (TypeError, json.JSONDecodeError):
            continue
        if int(details.get("process_numbering_version") or 0) >= PROCESS_NUMBERING_VERSION:
            return True
    return False


def migrate_control_plan_pr_numbers(project_id: str, editor_name: str) -> dict:
    """Backfill legacy Process numbers once per project with atomic audit evidence."""
    timestamp = _store().now_iso()
    with _store().connection() as conn:
        if _numbering_version_recorded(conn, project_id):
            return {"row_count": 0, "affected_ids": [], "timestamp": timestamp}
        rows = [
            dict(row)
            for row in conn.execute(
                """SELECT item.id, item.scenario_id, item.pr_number,
                          entry.work_element_id, entry.process_sequence_snapshot,
                          entry.created_at AS entry_created_at
                   FROM control_plan_items item
                   JOIN pfmea_entries entry ON entry.id=item.pfmea_entry_id
                   WHERE item.project_id=?
                   ORDER BY item.scenario_id, entry.process_sequence_snapshot,
                            entry.created_at, entry.id, item.created_at, item.id""",
                (project_id,),
            ).fetchall()
        ]
        affected = [row for row in rows if row.get("pr_number") is None]
        if not affected:
            return {"row_count": 0, "affected_ids": [], "timestamp": timestamp}
        if not _text(editor_name):
            raise ValueError(
                "Enter Current editor before opening Control Plan so the Process-number "
                "migration can be recorded in History."
            )
        grouped: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            grouped.setdefault(
                (str(row["scenario_id"]), str(row["work_element_id"])), []
            ).append(row)
        affected_ids: list[str] = []
        affected_operations: set[tuple[str, str]] = set()
        for operation_key, operation_rows in grouped.items():
            if not any(row.get("pr_number") is None for row in operation_rows):
                continue
            existing = next(
                (
                    _pr_number(row.get("pr_number"))
                    for row in operation_rows
                    if row.get("pr_number") is not None
                ),
                None,
            )
            number = existing
            if number is None:
                number = _pr_number(operation_rows[0].get("process_sequence_snapshot"))
            ids = [str(row["id"]) for row in operation_rows]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"""UPDATE control_plan_items SET pr_number=?, updated_at=?
                    WHERE project_id=? AND id IN ({placeholders})""",
                (number, timestamp, project_id, *ids),
            )
            affected_ids.extend(ids)
            affected_operations.add(operation_key)
        _store().record_audit_event(
            project_id,
            "Control Plan",
            "Migrate Process numbers",
            len(affected_ids),
            editor_name,
            {
                "affected_ids": affected_ids,
                "operation_count": len(affected_operations),
                "scenario_count": len({key[0] for key in affected_operations}),
                "process_numbering_version": PROCESS_NUMBERING_VERSION,
                "store_timestamp": timestamp,
            },
            _conn=conn,
        )
    return {
        "row_count": len(affected_ids),
        "affected_ids": affected_ids,
        "operation_count": len(affected_operations),
        "scenario_count": len({key[0] for key in affected_operations}),
        "timestamp": timestamp,
    }


def _validate_context(conn: sqlite3.Connection, project_id: str, scenario_id: str) -> None:
    if not conn.execute(
        "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
        (scenario_id, project_id),
    ).fetchone():
        raise ValueError("The selected planning scenario no longer exists in this project.")


def _quality_sources(conn: sqlite3.Connection, project_id: str, scenario_id: str) -> list[dict]:
    unions: list[str] = []
    for table in ("pfmea_prevention_selections", "pfmea_detection_selections"):
        if _table_exists(conn, table):
            unions.append(
                f"SELECT pfmea_entry_id, quality_requirement_assignment_id FROM {table} "
                "WHERE project_id=? AND scenario_id=? AND source_type='quality_assignment'"
            )
    if not unions:
        return []
    params: list[str] = []
    for _ in unions:
        params.extend([project_id, scenario_id])
    rows = conn.execute(
        f"""SELECT DISTINCT selected.pfmea_entry_id, a.id AS assignment_id,
                   a.work_element_id, a.quality_requirement_id,
                   a.requirement_type, a.description, a.unique_identifier,
                   a.target_value, a.tolerances, a.unit, a.source_updated_at,
                   a.updated_at AS assignment_updated_at
            FROM ({' UNION ALL '.join(unions)}) selected
            JOIN quality_requirement_assignments a
              ON a.id=selected.quality_requirement_assignment_id
             AND a.project_id=? AND a.scenario_id=?
            ORDER BY selected.pfmea_entry_id, a.created_at, a.id""",
        (*params, project_id, scenario_id),
    ).fetchall()
    return [dict(row) for row in rows]


def _torque_text(conn: sqlite3.Connection, project_id: str, requirement_id: str) -> str:
    row = conn.execute(
        """SELECT tool_type, tool_orientation, screw_bit_type
           FROM quality_requirement_torque_details
           WHERE project_id=? AND quality_requirement_id=?""",
        (project_id, requirement_id),
    ).fetchone()
    if not row:
        return ""
    values = [_text(row[name]) for name in ("tool_type", "tool_orientation", "screw_bit_type")]
    return " — ".join(value for value in values if value)


def _specification(source: dict) -> str:
    target = source.get("target_value")
    if target is None or _text(target) == "":
        target_text = ""
    else:
        try:
            target_text = f"{float(target):g}"
        except (TypeError, ValueError):
            target_text = _text(target)
    values = [target_text, _text(source.get("tolerances")), _text(source.get("unit"))]
    return " ".join(value for value in values if value)


def _source_fingerprint(entry: dict, source: dict | None, torque: str) -> str:
    published = (
        {
            name: source.get(name)
            for name in (
                "requirement_type", "description", "unique_identifier",
                "target_value", "tolerances", "unit", "source_updated_at",
            )
        }
        if source else {}
    )
    return _hash(
        {
            "class_code": _text(entry.get("class_code")),
            "operation": _text(entry.get("process_operation_snapshot")),
            "pitch": _text(entry.get("process_pitch_snapshot")),
            "sequence": int(entry.get("process_sequence_snapshot") or 0),
            "failure_mode": _text(entry.get("potential_failure_mode")),
            "quality": published,
            "torque": torque,
        }
    )


def _live_projection_conn(
    conn: sqlite3.Connection, project_id: str, scenario_id: str
) -> list[dict]:
    entries = [
        dict(row)
        for row in conn.execute(
            """SELECT entry.*, work.station AS current_pitch
               FROM pfmea_entries entry
               JOIN work_elements work
                 ON work.id=entry.work_element_id
                AND work.project_id=entry.project_id
                AND work.scenario_id=entry.scenario_id
               WHERE entry.project_id=? AND entry.scenario_id=?
                 AND TRIM(entry.class_code)<>''
               ORDER BY entry.process_sequence_snapshot, entry.created_at, entry.id""",
            (project_id, scenario_id),
        ).fetchall()
    ]
    operation_ids_for_order = list(
        dict.fromkeys(str(entry["work_element_id"]) for entry in entries)
    )
    op_contexts = _store().work_element_op_contexts(
        project_id, scenario_id, operation_ids_for_order
    )
    entries.sort(
        key=lambda entry: (
            int(op_contexts[str(entry["work_element_id"])]["sort_order"]),
            _text(entry.get("created_at")),
            str(entry["id"]),
        )
    )
    sources_by_entry: dict[str, list[dict]] = {}
    for source in _quality_sources(conn, project_id, scenario_id):
        sources_by_entry.setdefault(str(source["pfmea_entry_id"]), []).append(source)
    saved = [
        dict(row)
        for row in conn.execute(
            """SELECT item.*, entry.work_element_id
               FROM control_plan_items item
               JOIN pfmea_entries entry ON entry.id=item.pfmea_entry_id
               WHERE item.project_id=? AND item.scenario_id=?
               ORDER BY item.created_at, item.id""",
            (project_id, scenario_id),
        ).fetchall()
    ]
    saved_by_key = {
        (
            str(row["pfmea_entry_id"]),
            str(row["source_kind"]),
            _text(row.get("source_quality_requirement_id_snapshot")),
        ): row
        for row in saved
    }
    entry_positions = {str(entry["id"]): position for position, entry in enumerate(entries)}
    operation_positions: dict[str, int] = {}
    for position, entry in enumerate(entries):
        operation_positions.setdefault(str(entry["work_element_id"]), position)
    entries.sort(
        key=lambda entry: (
            operation_positions[str(entry["work_element_id"])],
            entry_positions[str(entry["id"])],
        )
    )
    operation_ids = list(
        dict.fromkeys(str(entry["work_element_id"]) for entry in entries)
    )
    existing_by_operation: dict[str, float] = {}
    occupied_numbers: list[float] = []
    for item in saved:
        work_id = str(item["work_element_id"])
        number = _pr_number(item.get("pr_number"))
        existing_by_operation.setdefault(work_id, number)
        if number is not None:
            occupied_numbers.append(number)
    suggestions = suggest_control_plan_pr_numbers(
        operation_ids, existing_by_operation, occupied_numbers
    )
    operation_numbers = {
        operation_id: (
            existing_by_operation[operation_id]
            if operation_id in existing_by_operation
            else suggestions.get(operation_id)
        )
        for operation_id in operation_ids
    }
    reserved_suffixes_by_work: dict[str, set[int]] = {}
    for item in saved:
        suffix = _characteristic_suffix(item.get("characteristic_suffix"))
        if suffix is not None:
            reserved_suffixes_by_work.setdefault(str(item["work_element_id"]), set()).add(
                suffix
            )
    result: list[dict] = []
    first_by_work: set[str] = set()
    for entry in entries:
        entry_id = str(entry["id"])
        work_id = str(entry["work_element_id"])
        sources = sources_by_entry.get(entry_id) or [None]
        sources = sorted(
            enumerate(sources),
            key=lambda pair: (
                int(
                    saved_by_key.get(
                        (
                            entry_id,
                            "quality" if pair[1] else "pfmea_only",
                            _text(pair[1].get("quality_requirement_id")) if pair[1] else "",
                        ),
                        {},
                    ).get("sequence")
                    or ((pair[0] + 1) * 10)
                ),
                pair[0],
            ),
        )
        for source_position, source in sources:
            kind = "quality" if source else "pfmea_only"
            quality_id = _text(source.get("quality_requirement_id")) if source else ""
            key = (entry_id, kind, quality_id)
            item = saved_by_key.get(key, {})
            if (
                source
                and item
                and _text(item.get("quality_requirement_assignment_id"))
                != _text(source.get("assignment_id"))
            ):
                # A retained orphan must be explicitly relinked. Do not silently
                # reactivate it merely because a compatible assignment reappears.
                continue
            torque = ""
            if source and _text(source.get("requirement_type")).casefold() == "torque":
                torque = _torque_text(conn, project_id, quality_id)
            fingerprint = _source_fingerprint(entry, source, torque)
            operation_number = operation_numbers.get(work_id)
            placement = _text(item.get("characteristic_placement"))
            characteristic = (
                _text(source.get("description")) if source
                else _text(entry.get("potential_failure_mode"))
            )
            current_pitch = _text(entry.get("current_pitch"))
            pitch_changed = current_pitch != _text(entry.get("process_pitch_snapshot"))
            review_required = (
                bool(item.get("source_review_required"))
                or bool(item and _text(item.get("source_fingerprint_snapshot")) != fingerprint)
                or pitch_changed
            )
            row = {
                "id": _text(item.get("id")),
                "projection_key": "|".join(key),
                "pfmea_entry_id": entry_id,
                "work_element_id": work_id,
                "source_kind": kind,
                "quality_requirement_assignment_id": (
                    _text(source.get("assignment_id")) if source else ""
                ),
                "quality_requirement_id": quality_id,
                "source_quality_requirement_id_snapshot": quality_id,
                "source_unique_identifier_snapshot": (
                    _text(source.get("unique_identifier")) if source else ""
                ),
                "source_description_snapshot": characteristic,
                "source_fingerprint": fingerprint,
                "pr_number": operation_number if work_id not in first_by_work else None,
                "operation_pr_number": operation_number,
                "projection_order": len(result),
                "characteristic_suffix": _characteristic_suffix(
                    item.get("characteristic_suffix")
                ),
                "effective_characteristic_suffix": None,
                "reserved_characteristic_suffixes": ",".join(
                    str(value)
                    for value in sorted(reserved_suffixes_by_work.get(work_id, set()))
                ),
                "station_pitch": current_pitch or "Unassigned",
                "operation": _text(entry.get("process_operation_snapshot")),
                "classification": _text(entry.get("class_code")),
                "characteristic_placement": placement,
                "product_part_characteristic": "",
                "process_characteristic": "",
                "specification_requirement": _specification(source or {}),
                "measurement_evaluation": " — ".join(
                    value for value in [
                        _text(source.get("requirement_type")) if source else "",
                        torque,
                    ] if value
                ),
                "machine_fixture": _text(item.get("machine_fixture")),
                "sample_size": _text(item.get("sample_size")),
                "sample_frequency": _text(item.get("sample_frequency")),
                "who": _text(item.get("who")),
                "control_method": _text(item.get("control_method")),
                "decision_rule": _text(item.get("decision_rule")),
                "excluded": bool(item.get("excluded")),
                "source_review_required": review_required,
                "persisted": bool(item),
                "sequence": int(item.get("sequence") or ((source_position + 1) * 10)),
            }
            result.append(row)
            first_by_work.add(work_id)
    return rebuild_control_plan_characteristic_numbers(pd.DataFrame(result)).to_dict(
        "records"
    )


def control_plan_projection(project_id: str, scenario_id: str) -> pd.DataFrame:
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        rows = _live_projection_conn(conn, project_id, scenario_id)
    return pd.DataFrame(rows)


def control_plan_review_items(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Return excluded, orphaned, or currently source-ineligible persisted items."""
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        live = _live_projection_conn(conn, project_id, scenario_id)
        active_ids = {_text(row.get("id")) for row in live if _text(row.get("id"))}
        rows = [
            dict(row)
            for row in conn.execute(
                """SELECT item.*, e.class_code,
                          e.process_pitch_snapshot, e.process_operation_snapshot,
                          e.process_sequence_snapshot, e.work_element_id
                   FROM control_plan_items item
                   LEFT JOIN pfmea_entries e ON e.id=item.pfmea_entry_id
                   WHERE item.project_id=? AND item.scenario_id=?
                   ORDER BY item.updated_at DESC, item.id""",
                (project_id, scenario_id),
            ).fetchall()
        ]
    for row in rows:
        row["review_reason"] = (
            "Excluded by collaborator" if bool(row.get("excluded"))
            else "Quality assignment unlinked" if row.get("source_kind") == "quality"
            and not row.get("quality_requirement_assignment_id")
            else "Source no longer qualifies"
        )
    return pd.DataFrame(
        [row for row in rows if bool(row.get("excluded")) or _text(row.get("id")) not in active_ids]
    )


def save_control_plan_rows(
    project_id: str, scenario_id: str, edited: pd.DataFrame
) -> dict:
    """Atomically persist all visible MCP-owned values and acknowledge live sources."""
    timestamp = _store().now_iso()
    records = edited.to_dict("records")
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        live = {
            str(row["projection_key"]): row
            for row in _live_projection_conn(conn, project_id, scenario_id)
            if not bool(row.get("excluded"))
        }
        supplied = {str(row.get("projection_key") or "") for row in records}
        if not supplied.issubset(live):
            raise ValueError("One or more Control Plan sources changed. Refresh and review them.")
        operation_numbers: dict[str, float | None] = {}
        for record in records:
            source = live[str(record["projection_key"])]
            work_id = str(source["work_element_id"])
            number = _pr_number(
                record.get("operation_pr_number", record.get("pr_number"))
            )
            if work_id in operation_numbers and operation_numbers[work_id] != number:
                raise ValueError(
                    "One Process operation has conflicting Pr. Nº values. "
                    "Use one value for every characteristic line in that operation."
                )
            operation_numbers[work_id] = number
        changed_ids: list[str] = []
        for record in records:
            source = live[str(record["projection_key"])]
            pr_number = operation_numbers[str(source["work_element_id"])]
            placement = _text(record.get("characteristic_placement"))
            if placement not in PLACEMENTS:
                raise ValueError("Characteristic placement must be Product / Part, Process, or blank.")
            characteristic_suffix = _characteristic_suffix(
                record.get("characteristic_suffix")
            )
            values = {
                name: _text(record.get(name))
                for name in (
                    "machine_fixture", "sample_size", "sample_frequency", "who",
                    "control_method", "decision_rule",
                )
            }
            item_id = _text(source.get("id"))
            if item_id:
                conn.execute(
                    """UPDATE control_plan_items SET characteristic_placement=?,
                       machine_fixture=?, sample_size=?, sample_frequency=?, who=?,
                       control_method=?, decision_rule=?,
                       quality_requirement_assignment_id=?, quality_requirement_id=?,
                       source_unique_identifier_snapshot=?, source_description_snapshot=?,
                       source_fingerprint_snapshot=?, source_review_required=0, sequence=?,
                       pr_number=?, characteristic_suffix=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=?""",
                    (
                        placement, values["machine_fixture"], values["sample_size"],
                        values["sample_frequency"], values["who"], values["control_method"],
                        values["decision_rule"],
                        source.get("quality_requirement_assignment_id") or None,
                        source.get("quality_requirement_id") or None,
                        source.get("source_unique_identifier_snapshot") or "",
                        source.get("source_description_snapshot") or "",
                        source["source_fingerprint"], int(source.get("sequence") or 10),
                         pr_number, characteristic_suffix, timestamp,
                         item_id, project_id, scenario_id,
                    ),
                )
            else:
                item_id = str(uuid4())
                conn.execute(
                    """INSERT INTO control_plan_items
                       (id, project_id, scenario_id, pfmea_entry_id, source_kind,
                        quality_requirement_assignment_id, quality_requirement_id,
                        source_quality_requirement_id_snapshot,
                        source_unique_identifier_snapshot, source_description_snapshot,
                        characteristic_placement, machine_fixture, sample_size,
                        sample_frequency, who, control_method, decision_rule, excluded,
                        source_fingerprint_snapshot, source_review_required,
                         sequence, pr_number, characteristic_suffix, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0, ?, ?, ?, ?, ?)""",
                    (
                        item_id, project_id, scenario_id, source["pfmea_entry_id"],
                        source["source_kind"],
                        source.get("quality_requirement_assignment_id") or None,
                        source.get("quality_requirement_id") or None,
                        source.get("source_quality_requirement_id_snapshot") or "",
                        source.get("source_unique_identifier_snapshot") or "",
                        source.get("source_description_snapshot") or "", placement,
                        values["machine_fixture"], values["sample_size"],
                        values["sample_frequency"], values["who"], values["control_method"],
                        values["decision_rule"], source["source_fingerprint"],
                         int(source.get("sequence") or 10), pr_number,
                         characteristic_suffix, timestamp, timestamp,
                    ),
                )
            changed_ids.append(item_id)
        for work_id, number in operation_numbers.items():
            conn.execute(
                """UPDATE control_plan_items SET pr_number=?, updated_at=?
                   WHERE project_id=? AND scenario_id=? AND pfmea_entry_id IN (
                       SELECT id FROM pfmea_entries
                       WHERE project_id=? AND scenario_id=? AND work_element_id=?
                   )""",
                (
                    number, timestamp, project_id, scenario_id,
                    project_id, scenario_id, work_id,
                ),
            )
    return {"row_count": len(changed_ids), "affected_ids": changed_ids, "timestamp": timestamp}


def exclude_control_plan_items(
    project_id: str, scenario_id: str, item_ids: list[str]
) -> dict:
    ids = list(dict.fromkeys(_text(value) for value in item_ids if _text(value)))
    if not ids:
        return {"row_count": 0, "affected_ids": [], "timestamp": _store().now_iso()}
    placeholders = ",".join("?" for _ in ids)
    timestamp = _store().now_iso()
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        found = conn.execute(
            f"SELECT id FROM control_plan_items WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})",
            (project_id, scenario_id, *ids),
        ).fetchall()
        if {str(row["id"]) for row in found} != set(ids):
            raise ValueError("Save unsaved Control Plan lines before excluding them.")
        conn.execute(
            f"""UPDATE control_plan_items SET excluded=1, updated_at=?
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (timestamp, project_id, scenario_id, *ids),
        )
    return {"row_count": len(ids), "affected_ids": ids, "timestamp": timestamp}


def exclude_control_plan_projection_keys(
    project_id: str, scenario_id: str, projection_keys: list[str]
) -> dict:
    """Persist and exclude eligible projected rows, including previously unsaved lines."""
    keys = list(dict.fromkeys(_text(value) for value in projection_keys if _text(value)))
    timestamp = _store().now_iso()
    if not keys:
        return {"row_count": 0, "affected_ids": [], "timestamp": timestamp}
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        live = {str(row["projection_key"]): row for row in _live_projection_conn(conn, project_id, scenario_id)}
        if not set(keys).issubset(live):
            raise ValueError("One or more Control Plan sources changed. Refresh and try again.")
        item_ids: list[str] = []
        for key in keys:
            source = live[key]
            item_id = _text(source.get("id"))
            if item_id:
                conn.execute(
                    "UPDATE control_plan_items SET excluded=1, updated_at=? WHERE id=?",
                    (timestamp, item_id),
                )
            else:
                item_id = str(uuid4())
                conn.execute(
                    """INSERT INTO control_plan_items
                       (id, project_id, scenario_id, pfmea_entry_id, source_kind,
                        quality_requirement_assignment_id, quality_requirement_id,
                        source_quality_requirement_id_snapshot,
                        source_unique_identifier_snapshot, source_description_snapshot,
                        excluded, source_fingerprint_snapshot, source_review_required,
                        sequence, pr_number, characteristic_suffix, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 0, ?, ?, ?, ?, ?)""",
                    (
                        item_id, project_id, scenario_id, source["pfmea_entry_id"],
                        source["source_kind"],
                        source.get("quality_requirement_assignment_id") or None,
                        source.get("quality_requirement_id") or None,
                        source.get("source_quality_requirement_id_snapshot") or "",
                        source.get("source_unique_identifier_snapshot") or "",
                        source.get("source_description_snapshot") or "",
                        source["source_fingerprint"], int(source.get("sequence") or 10),
                        _pr_number(source.get("operation_pr_number")),
                        _characteristic_suffix(source.get("characteristic_suffix")),
                        timestamp, timestamp,
                    ),
                )
            item_ids.append(item_id)
    return {"row_count": len(item_ids), "affected_ids": item_ids, "timestamp": timestamp}


def control_plan_evidence(
    project_id: str, scenario_id: str, pfmea_entry_id: str
) -> dict[str, list[str]]:
    """Return friendly, read-only PFMEA control and action evidence for one entry."""
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        if not conn.execute(
            "SELECT 1 FROM pfmea_entries WHERE id=? AND project_id=? AND scenario_id=?",
            (pfmea_entry_id, project_id, scenario_id),
        ).fetchone():
            raise ValueError("That PFMEA entry no longer exists in this scenario.")
        result: dict[str, list[str]] = {"Prevention": [], "Detection": [], "Actions": []}
        for control_type, table, option_table, option_column in (
            ("Prevention", "pfmea_prevention_selections", "pfmea_prevention_options", "prevention_option_id"),
            ("Detection", "pfmea_detection_selections", "pfmea_detection_options", "detection_option_id"),
        ):
            rows = conn.execute(
                f"""SELECT s.source_type, a.description, a.requirement_type,
                           a.unique_identifier, o.label
                    FROM {table} s
                    LEFT JOIN quality_requirement_assignments a
                      ON a.id=s.quality_requirement_assignment_id
                    LEFT JOIN {option_table} o ON o.id=s.{option_column}
                    WHERE s.project_id=? AND s.scenario_id=? AND s.pfmea_entry_id=?
                    ORDER BY s.sequence, s.created_at, s.id""",
                (project_id, scenario_id, pfmea_entry_id),
            ).fetchall()
            for row in rows:
                if row["source_type"] == "quality_assignment":
                    result[control_type].append(
                        "Quality — " + " — ".join(
                            value for value in (
                                _text(row["description"]), _text(row["requirement_type"]),
                                _text(row["unique_identifier"]),
                            ) if value
                        )
                    )
                else:
                    result[control_type].append(f"Manual — {_text(row['label'])}")
        actions = conn.execute(
            """SELECT recommended_action, actions_taken FROM pfmea_actions
               WHERE project_id=? AND scenario_id=? AND pfmea_entry_id=?
               ORDER BY sequence, created_at, id""",
            (project_id, scenario_id, pfmea_entry_id),
        ).fetchall()
        for row in actions:
            recommended = _text(row["recommended_action"])
            taken = _text(row["actions_taken"])
            if recommended or taken:
                result["Actions"].append(
                    " | ".join(value for value in (
                        f"Recommended: {recommended}" if recommended else "",
                        f"Taken: {taken}" if taken else "",
                    ) if value)
                )
    return result


def control_plan_relink_candidates(
    project_id: str, scenario_id: str, item_id: str
) -> pd.DataFrame:
    with _store().connection() as conn:
        item = conn.execute(
            """SELECT item.source_quality_requirement_id_snapshot, entry.work_element_id
               FROM control_plan_items item JOIN pfmea_entries entry ON entry.id=item.pfmea_entry_id
               WHERE item.id=? AND item.project_id=? AND item.scenario_id=?""",
            (item_id, project_id, scenario_id),
        ).fetchone()
        if not item:
            return pd.DataFrame()
        rows = conn.execute(
            """SELECT id, unique_identifier, description FROM quality_requirement_assignments
               WHERE project_id=? AND scenario_id=? AND work_element_id=?
                 AND quality_requirement_id=? ORDER BY unique_identifier, id""",
            (
                project_id, scenario_id, item["work_element_id"],
                item["source_quality_requirement_id_snapshot"],
            ),
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def restore_control_plan_item(project_id: str, scenario_id: str, item_id: str) -> dict:
    timestamp = _store().now_iso()
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        row = conn.execute(
            "SELECT * FROM control_plan_items WHERE id=? AND project_id=? AND scenario_id=?",
            (item_id, project_id, scenario_id),
        ).fetchone()
        if not row:
            raise ValueError("That Control Plan item no longer exists.")
        conn.execute(
            "UPDATE control_plan_items SET excluded=0, source_review_required=1, updated_at=? WHERE id=?",
            (timestamp, item_id),
        )
        eligible_ids = {
            _text(item.get("id")) for item in _live_projection_conn(conn, project_id, scenario_id)
        }
        if item_id not in eligible_ids:
            raise ValueError("This item cannot be restored until its PFMEA source qualifies again.")
    return {"row_count": 1, "affected_ids": [item_id], "timestamp": timestamp}


def control_plan_assignment_impact(
    project_id: str, scenario_id: str, assignment_ids: list[str]
) -> dict:
    ids = list(dict.fromkeys(_text(value) for value in assignment_ids if _text(value)))
    if not ids:
        return {"item_count": 0, "item_ids": []}
    placeholders = ",".join("?" for _ in ids)
    with _store().connection() as conn:
        if not _table_exists(conn, "control_plan_items"):
            return {"item_count": 0, "item_ids": []}
        rows = conn.execute(
            f"""SELECT id FROM control_plan_items
                WHERE project_id=? AND scenario_id=?
                  AND quality_requirement_assignment_id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        ).fetchall()
    item_ids = [str(row["id"]) for row in rows]
    return {"item_count": len(item_ids), "item_ids": item_ids}


def orphan_control_plan_assignments_conn(
    conn: sqlite3.Connection, project_id: str, scenario_id: str,
    assignment_ids: list[str], timestamp: str,
) -> list[str]:
    if not _table_exists(conn, "control_plan_items"):
        return []
    ids = list(dict.fromkeys(_text(value) for value in assignment_ids if _text(value)))
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""SELECT id FROM control_plan_items
            WHERE project_id=? AND scenario_id=?
              AND quality_requirement_assignment_id IN ({placeholders})""",
        (project_id, scenario_id, *ids),
    ).fetchall()
    item_ids = [str(row["id"]) for row in rows]
    if item_ids:
        conn.execute(
            f"""UPDATE control_plan_items
                SET quality_requirement_assignment_id=NULL,
                    source_review_required=1, updated_at=?
                WHERE project_id=? AND scenario_id=?
                  AND quality_requirement_assignment_id IN ({placeholders})""",
            (timestamp, project_id, scenario_id, *ids),
        )
    return item_ids


def relink_control_plan_item(
    project_id: str, scenario_id: str, item_id: str, assignment_id: str
) -> dict:
    timestamp = _store().now_iso()
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        item = conn.execute(
            """SELECT item.*, entry.work_element_id FROM control_plan_items item
               JOIN pfmea_entries entry ON entry.id=item.pfmea_entry_id
               WHERE item.id=? AND item.project_id=? AND item.scenario_id=?""",
            (item_id, project_id, scenario_id),
        ).fetchone()
        assignment = conn.execute(
            """SELECT * FROM quality_requirement_assignments
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (assignment_id, project_id, scenario_id),
        ).fetchone()
        if not item or not assignment:
            raise ValueError("The Control Plan item or Quality assignment no longer exists.")
        if str(item["work_element_id"]) != str(assignment["work_element_id"]):
            raise ValueError("The replacement assignment must belong to the same Process step.")
        expected_quality_id = _text(item["source_quality_requirement_id_snapshot"])
        if expected_quality_id != str(assignment["quality_requirement_id"]):
            raise ValueError("The replacement assignment must use the same Quality definition.")
        selected_as_control = any(
            conn.execute(
                f"""SELECT 1 FROM {table}
                    WHERE project_id=? AND scenario_id=? AND pfmea_entry_id=?
                      AND quality_requirement_assignment_id=?""",
                (project_id, scenario_id, item["pfmea_entry_id"], assignment_id),
            ).fetchone()
            for table in ("pfmea_prevention_selections", "pfmea_detection_selections")
        )
        if not selected_as_control:
            raise ValueError(
                "Select this Quality assignment as a Prevention or Detection control in "
                "the PFMEA entry before relinking it to the Control Plan item."
            )
        conn.execute(
            """UPDATE control_plan_items SET quality_requirement_assignment_id=?,
               quality_requirement_id=?, source_unique_identifier_snapshot=?,
               source_description_snapshot=?, source_review_required=1, updated_at=?
               WHERE id=?""",
            (
                assignment_id, assignment["quality_requirement_id"],
                assignment["unique_identifier"], assignment["description"],
                timestamp, item_id,
            ),
        )
    return {"row_count": 1, "affected_ids": [item_id], "timestamp": timestamp}


def control_plan_pfmea_delete_impact(
    project_id: str, scenario_id: str, entry_ids: list[str]
) -> dict:
    ids = list(dict.fromkeys(_text(value) for value in entry_ids if _text(value)))
    if not ids:
        return {"item_count": 0}
    placeholders = ",".join("?" for _ in ids)
    with _store().connection() as conn:
        if not _table_exists(conn, "control_plan_items"):
            return {"item_count": 0}
        count = conn.execute(
            f"""SELECT COUNT(*) FROM control_plan_items
                WHERE project_id=? AND scenario_id=?
                  AND pfmea_entry_id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        ).fetchone()[0]
    return {"item_count": int(count)}


def clone_control_plan_scenario(
    conn: sqlite3.Connection, project_id: str, source_scenario_id: str,
    new_scenario_id: str, entry_id_map: dict[str, str],
    assignment_id_map: dict[str, str], timestamp: str,
) -> int:
    if not _table_exists(conn, "control_plan_items"):
        return 0
    cloned = 0
    for raw in conn.execute(
        "SELECT * FROM control_plan_items WHERE project_id=? AND scenario_id=?",
        (project_id, source_scenario_id),
    ).fetchall():
        row = dict(raw)
        new_entry_id = entry_id_map.get(str(row["pfmea_entry_id"]))
        if not new_entry_id:
            continue
        old_assignment = _text(row.get("quality_requirement_assignment_id"))
        row.update(
            id=str(uuid4()), scenario_id=new_scenario_id, pfmea_entry_id=new_entry_id,
            quality_requirement_assignment_id=(assignment_id_map.get(old_assignment) if old_assignment else None),
            created_at=timestamp, updated_at=timestamp,
        )
        if old_assignment and not row["quality_requirement_assignment_id"]:
            row["source_review_required"] = 1
        columns = list(row)
        conn.execute(
            f"INSERT INTO control_plan_items ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            tuple(row[column] for column in columns),
        )
        cloned += 1
    return cloned
