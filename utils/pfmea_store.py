"""Scenario-specific PFMEA persistence approved in `DATA_DICTIONARY.md`.

PFMEA records snapshot collaborator-reviewed Process at a Glance evidence. Its
Prevention and Detection controls are structured Cause-level references to
published Quality assignments or project-wide manual option catalogs.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd


PFMEA_CLASSIFICATIONS = ["", "Safety", "Critical Quality"]
PFMEA_RATINGS = list(range(1, 11))


CONTROL_TYPES = ("Prevention", "Detection")
CONTROL_SOURCE_TYPES = ("quality_assignment", "manual_option")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def init_pfmea_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pfmea_entries (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            work_element_id TEXT NOT NULL REFERENCES work_elements(id) ON DELETE RESTRICT,
            source_pfmea_entry_id TEXT REFERENCES pfmea_entries(id) ON DELETE SET NULL,
            potential_failure_mode TEXT NOT NULL,
            class_code TEXT NOT NULL DEFAULT '',
            process_operation_snapshot TEXT NOT NULL DEFAULT '',
            process_description_snapshot TEXT NOT NULL DEFAULT '',
            process_location_snapshot TEXT NOT NULL DEFAULT '',
            process_pitch_snapshot TEXT NOT NULL DEFAULT '',
            process_sequence_snapshot INTEGER NOT NULL DEFAULT 0,
            process_source_hash TEXT NOT NULL,
            quality_source_hash TEXT NOT NULL,
            source_reviewed_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pfmea_effects (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            pfmea_entry_id TEXT NOT NULL REFERENCES pfmea_entries(id) ON DELETE CASCADE,
            effect_description TEXT NOT NULL,
            severity REAL,
            sequence INTEGER NOT NULL DEFAULT 10,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pfmea_causes (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            pfmea_entry_id TEXT NOT NULL REFERENCES pfmea_entries(id) ON DELETE CASCADE,
            cause_description TEXT NOT NULL,
            occurrence REAL,
            detection REAL,
            detection_review_required INTEGER NOT NULL DEFAULT 0
                CHECK (detection_review_required IN (0, 1)),
            sequence INTEGER NOT NULL DEFAULT 10,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pfmea_risk_rows (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            pfmea_entry_id TEXT NOT NULL REFERENCES pfmea_entries(id) ON DELETE CASCADE,
            pfmea_effect_id TEXT NOT NULL REFERENCES pfmea_effects(id) ON DELETE CASCADE,
            pfmea_cause_id TEXT NOT NULL REFERENCES pfmea_causes(id) ON DELETE CASCADE,
            rpn REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(pfmea_effect_id, pfmea_cause_id)
        );
        CREATE TABLE IF NOT EXISTS pfmea_actions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            pfmea_entry_id TEXT NOT NULL REFERENCES pfmea_entries(id) ON DELETE CASCADE,
            pfmea_cause_id TEXT REFERENCES pfmea_causes(id) ON DELETE CASCADE,
            recommended_action TEXT NOT NULL,
            responsibility TEXT NOT NULL DEFAULT '',
            target_completion_date TEXT NOT NULL DEFAULT '',
            actions_taken TEXT NOT NULL DEFAULT '',
            resulting_severity REAL,
            resulting_occurrence REAL,
            resulting_detection REAL,
            resulting_rpn REAL,
            sequence INTEGER NOT NULL DEFAULT 10,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pfmea_prevention_options (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pfmea_detection_options (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pfmea_prevention_selections (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            pfmea_entry_id TEXT NOT NULL REFERENCES pfmea_entries(id) ON DELETE CASCADE,
            pfmea_cause_id TEXT NOT NULL REFERENCES pfmea_causes(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL
                CHECK (source_type IN ('quality_assignment', 'manual_option')),
            quality_requirement_assignment_id TEXT
                REFERENCES quality_requirement_assignments(id) ON DELETE CASCADE,
            prevention_option_id TEXT
                REFERENCES pfmea_prevention_options(id) ON DELETE CASCADE,
            source_updated_at_snapshot TEXT NOT NULL,
            sequence INTEGER NOT NULL DEFAULT 10,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (
                (source_type='quality_assignment'
                 AND quality_requirement_assignment_id IS NOT NULL
                 AND prevention_option_id IS NULL)
                OR
                (source_type='manual_option'
                 AND quality_requirement_assignment_id IS NULL
                 AND prevention_option_id IS NOT NULL)
            )
        );
        CREATE TABLE IF NOT EXISTS pfmea_detection_selections (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            pfmea_entry_id TEXT NOT NULL REFERENCES pfmea_entries(id) ON DELETE CASCADE,
            pfmea_cause_id TEXT NOT NULL REFERENCES pfmea_causes(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL
                CHECK (source_type IN ('quality_assignment', 'manual_option')),
            quality_requirement_assignment_id TEXT
                REFERENCES quality_requirement_assignments(id) ON DELETE CASCADE,
            detection_option_id TEXT
                REFERENCES pfmea_detection_options(id) ON DELETE CASCADE,
            source_updated_at_snapshot TEXT NOT NULL,
            sequence INTEGER NOT NULL DEFAULT 10,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (
                (source_type='quality_assignment'
                 AND quality_requirement_assignment_id IS NOT NULL
                 AND detection_option_id IS NULL)
                OR
                (source_type='manual_option'
                 AND quality_requirement_assignment_id IS NULL
                 AND detection_option_id IS NOT NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS idx_pfmea_entries_scenario
            ON pfmea_entries(project_id, scenario_id, work_element_id);
        CREATE INDEX IF NOT EXISTS idx_pfmea_effects_entry ON pfmea_effects(pfmea_entry_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_pfmea_causes_entry ON pfmea_causes(pfmea_entry_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_pfmea_actions_entry ON pfmea_actions(pfmea_entry_id, sequence);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pfmea_prevention_option_label
            ON pfmea_prevention_options(project_id, label COLLATE NOCASE);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pfmea_detection_option_label
            ON pfmea_detection_options(project_id, label COLLATE NOCASE);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pfmea_prevention_quality_selection
            ON pfmea_prevention_selections(pfmea_cause_id, quality_requirement_assignment_id)
            WHERE quality_requirement_assignment_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pfmea_prevention_manual_selection
            ON pfmea_prevention_selections(pfmea_cause_id, prevention_option_id)
            WHERE prevention_option_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pfmea_detection_quality_selection
            ON pfmea_detection_selections(pfmea_cause_id, quality_requirement_assignment_id)
            WHERE quality_requirement_assignment_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pfmea_detection_manual_selection
            ON pfmea_detection_selections(pfmea_cause_id, detection_option_id)
            WHERE detection_option_id IS NOT NULL;
        """
    )
    cause_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(pfmea_causes)").fetchall()
    }
    if "detection_review_required" not in cause_columns:
        conn.execute(
            """ALTER TABLE pfmea_causes
               ADD COLUMN detection_review_required INTEGER NOT NULL DEFAULT 0
               CHECK (detection_review_required IN (0, 1))"""
        )
    if "control_source_review_required" not in cause_columns:
        conn.execute(
            """ALTER TABLE pfmea_causes
               ADD COLUMN control_source_review_required INTEGER NOT NULL DEFAULT 0
               CHECK (control_source_review_required IN (0, 1))"""
        )


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


def _rating(value, label: str) -> int | None:
    if value is None or _text(value) == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(number) or not number.is_integer() or int(number) not in PFMEA_RATINGS:
        raise ValueError(f"{label} must be a whole number from 1 through 10.")
    return int(number)


def _classification(value) -> str:
    classification = _text(value)
    if classification not in PFMEA_CLASSIFICATIONS:
        raise ValueError("Classification must be Safety, Critical Quality, or blank.")
    return classification


def _sequence(value, default: int) -> int:
    if value is None or _text(value) == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("Seq must be a whole number.") from exc


def _hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_context(conn, project_id: str, scenario_id: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
        (scenario_id, project_id),
    ).fetchone()
    if not row:
        raise ValueError("The selected planning scenario no longer exists in this project.")


def _work_element(conn, project_id: str, scenario_id: str, work_element_id: str):
    row = conn.execute(
        "SELECT * FROM work_elements WHERE id=? AND project_id=? AND scenario_id=?",
        (work_element_id, project_id, scenario_id),
    ).fetchone()
    if not row:
        raise ValueError("The selected Process at a Glance step no longer exists in this scenario.")
    return dict(row)


def _control_tables(control_type: str) -> tuple[str, str, str]:
    if control_type == "Prevention":
        return (
            "pfmea_prevention_options",
            "pfmea_prevention_selections",
            "prevention_option_id",
        )
    if control_type == "Detection":
        return (
            "pfmea_detection_options",
            "pfmea_detection_selections",
            "detection_option_id",
        )
    raise ValueError("Control type must be Prevention or Detection.")


def _source_key(source_type: str, source_id: str) -> str:
    prefix = "quality" if source_type == "quality_assignment" else "manual"
    return f"{prefix}:{source_id}"


def _source_version_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_values(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                value = [text]
        else:
            value = [text]
    try:
        if bool(pd.isna(value)):
            return []
    except (TypeError, ValueError):
        pass
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    return [_text(item) for item in value if _text(item)]


def migrate_legacy_pfmea_controls(project_id: str, editor_name: str) -> dict:
    """Discard legacy free-text controls once and audit the destructive migration."""
    timestamp = _store().now_iso()
    with _store().connection() as conn:
        if not _table_exists(conn, "pfmea_controls"):
            return {"row_count": 0, "affected_cause_count": 0, "timestamp": timestamp}
        rows = conn.execute(
            "SELECT id, scenario_id, pfmea_cause_id, classification "
            "FROM pfmea_controls WHERE project_id=?",
            (project_id,),
        ).fetchall()
        if not rows:
            if not conn.execute("SELECT 1 FROM pfmea_controls LIMIT 1").fetchone():
                conn.execute("DROP INDEX IF EXISTS idx_pfmea_controls_cause")
                conn.execute("DROP TABLE pfmea_controls")
            return {"row_count": 0, "affected_cause_count": 0, "timestamp": timestamp}
        if not _text(editor_name):
            raise ValueError(
                "Enter Current editor before opening PFMEA so the legacy-control migration "
                "can be recorded in History."
            )
        cause_ids = sorted({str(row["pfmea_cause_id"]) for row in rows})
        detection_cause_ids = sorted(
            {
                str(row["pfmea_cause_id"])
                for row in rows
                if str(row["classification"]) == "Detection"
            }
        )
        placeholders = ",".join("?" for _ in cause_ids)
        conn.execute(
            f"""UPDATE pfmea_causes
                SET control_source_review_required=1, updated_at=?
                WHERE project_id=? AND id IN ({placeholders})""",
            (timestamp, project_id, *cause_ids),
        )
        if detection_cause_ids:
            detection_placeholders = ",".join("?" for _ in detection_cause_ids)
            conn.execute(
                f"""UPDATE pfmea_causes
                    SET detection_review_required=1, updated_at=?
                    WHERE project_id=? AND id IN ({detection_placeholders})""",
                (timestamp, project_id, *detection_cause_ids),
            )
        conn.execute("DELETE FROM pfmea_controls WHERE project_id=?", (project_id,))
        _store().record_audit_event(
            project_id,
            "PFMEA",
            "Migrate legacy controls",
            len(rows),
            editor_name,
            {
                "removed_control_count": len(rows),
                "affected_cause_count": len(cause_ids),
                "legacy_text_retained": False,
                "store_timestamp": timestamp,
            },
            _conn=conn,
        )
        if not conn.execute("SELECT 1 FROM pfmea_controls LIMIT 1").fetchone():
            conn.execute("DROP INDEX IF EXISTS idx_pfmea_controls_cause")
            conn.execute("DROP TABLE pfmea_controls")
        return {
            "row_count": len(rows),
            "affected_cause_count": len(cause_ids),
            "timestamp": timestamp,
        }


def pfmea_control_options(project_id: str, control_type: str) -> pd.DataFrame:
    option_table, _, _ = _control_tables(control_type)
    with _store().connection() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ValueError("The selected project no longer exists.")
        rows = conn.execute(
            f"""SELECT option.*,
                       (SELECT COUNT(*) FROM {
                           'pfmea_prevention_selections' if control_type == 'Prevention'
                           else 'pfmea_detection_selections'
                       } selection
                        WHERE selection.{
                            'prevention_option_id' if control_type == 'Prevention'
                            else 'detection_option_id'
                        }=option.id) AS selection_count
                FROM {option_table} option
                WHERE option.project_id=?
                ORDER BY option.active DESC, option.label COLLATE NOCASE, option.id""",
            (project_id,),
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def save_pfmea_control_option_rows(
    project_id: str, control_type: str, edited: pd.DataFrame
) -> dict:
    option_table, selection_table, option_column = _control_tables(control_type)
    timestamp = _source_version_timestamp()
    rows = edited.to_dict("records")
    labels = [_text(row.get("label")) for row in rows]
    if any(not label for label in labels):
        raise ValueError(f"Every {control_type} option requires a Label.")
    if len({label.casefold() for label in labels}) != len(labels):
        raise ValueError(f"{control_type} option labels must be unique within this project.")
    with _store().connection() as conn:
        existing = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                f"SELECT * FROM {option_table} WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        supplied = {_text(row.get("id")) for row in rows if _text(row.get("id"))}
        if set(existing) - supplied:
            raise ValueError(
                f"Remove {control_type} options through the confirmed deletion workflow."
            )
        created: list[str] = []
        updated: list[str] = []
        for row in rows:
            row_id = _text(row.get("id"))
            label = _text(row.get("label"))
            active = 1 if bool(row.get("active", True)) else 0
            try:
                if row_id:
                    if row_id not in existing:
                        raise ValueError(
                            f"A {control_type} option changed or no longer exists. Refresh and try again."
                        )
                    prior = existing[row_id]
                    changed = label != str(prior["label"]) or active != int(prior["active"])
                    conn.execute(
                        f"UPDATE {option_table} SET label=?, active=?, updated_at=? "
                        "WHERE id=? AND project_id=?",
                        (label, active, timestamp, row_id, project_id),
                    )
                    if changed:
                        causes = conn.execute(
                            f"SELECT DISTINCT pfmea_cause_id FROM {selection_table} "
                            f"WHERE {option_column}=?",
                            (row_id,),
                        ).fetchall()
                        for cause in causes:
                            conn.execute(
                                """UPDATE pfmea_causes
                                   SET control_source_review_required=1,
                                       detection_review_required=CASE WHEN ?='Detection'
                                           THEN 1 ELSE detection_review_required END,
                                       updated_at=? WHERE id=?""",
                                (control_type, timestamp, cause["pfmea_cause_id"]),
                            )
                    updated.append(row_id)
                else:
                    row_id = str(uuid4())
                    conn.execute(
                        f"""INSERT INTO {option_table}
                            (id, project_id, label, active, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?)""",
                        (row_id, project_id, label, active, timestamp, timestamp),
                    )
                    created.append(row_id)
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"{control_type} option labels must be unique within this project."
                ) from exc
        return {
            "row_count": len(created) + len(updated),
            "created_ids": created,
            "updated_ids": updated,
            "timestamp": timestamp,
        }


def pfmea_control_option_delete_impact(
    project_id: str, control_type: str, option_ids: list[str]
) -> dict:
    option_table, selection_table, option_column = _control_tables(control_type)
    ids = list(dict.fromkeys(_text(value) for value in option_ids if _text(value)))
    if not ids:
        return {"option_count": 0, "selection_count": 0, "cause_count": 0}
    placeholders = ",".join("?" for _ in ids)
    with _store().connection() as conn:
        options = conn.execute(
            f"SELECT id, label FROM {option_table} WHERE project_id=? AND id IN ({placeholders})",
            (project_id, *ids),
        ).fetchall()
        if len(options) != len(ids):
            raise ValueError(f"One or more {control_type} options changed. Refresh and try again.")
        selections = conn.execute(
            f"""SELECT selection.pfmea_cause_id, selection.scenario_id
                FROM {selection_table} selection
                WHERE selection.project_id=? AND selection.{option_column} IN ({placeholders})""",
            (project_id, *ids),
        ).fetchall()
    return {
        "option_count": len(ids),
        "selection_count": len(selections),
        "cause_count": len({str(row["pfmea_cause_id"]) for row in selections}),
        "scenario_count": len({str(row["scenario_id"]) for row in selections}),
        "labels": [str(row["label"]) for row in options],
    }


def delete_pfmea_control_options(
    project_id: str, control_type: str, option_ids: list[str]
) -> dict:
    option_table, selection_table, option_column = _control_tables(control_type)
    ids = list(dict.fromkeys(_text(value) for value in option_ids if _text(value)))
    impact = pfmea_control_option_delete_impact(project_id, control_type, ids)
    if not ids:
        return impact | {"row_count": 0, "timestamp": _store().now_iso()}
    placeholders = ",".join("?" for _ in ids)
    timestamp = _store().now_iso()
    with _store().connection() as conn:
        affected = conn.execute(
            f"SELECT DISTINCT pfmea_cause_id FROM {selection_table} "
            f"WHERE project_id=? AND {option_column} IN ({placeholders})",
            (project_id, *ids),
        ).fetchall()
        for row in affected:
            conn.execute(
                """UPDATE pfmea_causes
                   SET control_source_review_required=1,
                       detection_review_required=CASE WHEN ?='Detection'
                           THEN 1 ELSE detection_review_required END,
                       updated_at=? WHERE id=? AND project_id=?""",
                (control_type, timestamp, row["pfmea_cause_id"], project_id),
            )
        cursor = conn.execute(
            f"DELETE FROM {option_table} WHERE project_id=? AND id IN ({placeholders})",
            (project_id, *ids),
        )
        if int(cursor.rowcount) != len(ids):
            raise ValueError(f"One or more {control_type} options changed. Refresh and try again.")
    return impact | {"row_count": len(ids), "timestamp": timestamp}


def _quality_control_label(row: dict) -> str:
    return " — ".join(
        [
            "Quality",
            _text(row.get("description")) or "Unnamed requirement",
            _text(row.get("requirement_type")) or "Unspecified type",
            _text(row.get("unique_identifier")) or "No identifier",
        ]
    )


def pfmea_control_candidates(
    project_id: str,
    scenario_id: str,
    work_element_id: str,
    control_type: str,
    include_source_keys: list[str] | None = None,
) -> pd.DataFrame:
    option_table, _, _ = _control_tables(control_type)
    include = set(include_source_keys or [])
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        _work_element(conn, project_id, scenario_id, work_element_id)
        assignments = [
            dict(row)
            for row in conn.execute(
                """SELECT * FROM quality_requirement_assignments
                   WHERE project_id=? AND scenario_id=? AND work_element_id=?
                   ORDER BY description COLLATE NOCASE, unique_identifier COLLATE NOCASE, id""",
                (project_id, scenario_id, work_element_id),
            ).fetchall()
        ]
        options = [
            dict(row)
            for row in conn.execute(
                f"""SELECT * FROM {option_table}
                    WHERE project_id=? AND (active=1 OR ('manual:' || id) IN ({
                        ','.join('?' for _ in include) if include else "''"
                    }))
                    ORDER BY active DESC, label COLLATE NOCASE, id""",
                (project_id, *include) if include else (project_id,),
            ).fetchall()
        ]
    records = [
        {
            "source_key": _source_key("quality_assignment", str(row["id"])),
            "source_type": "quality_assignment",
            "source_id": str(row["id"]),
            "label": _quality_control_label(row),
            "active": True,
            "updated_at": str(row["updated_at"]),
        }
        for row in assignments
    ]
    records.extend(
        {
            "source_key": _source_key("manual_option", str(row["id"])),
            "source_type": "manual_option",
            "source_id": str(row["id"]),
            "label": f"Manual — {row['label']}",
            "active": bool(row["active"]),
            "updated_at": str(row["updated_at"]),
        }
        for row in options
    )
    return pd.DataFrame(records)


def _selection_rows_conn(
    conn: sqlite3.Connection, project_id: str, scenario_id: str, control_type: str
) -> list[dict]:
    option_table, selection_table, option_column = _control_tables(control_type)
    rows = conn.execute(
        f"""SELECT selection.*,
                   assignment.description AS quality_description,
                   assignment.requirement_type AS quality_type,
                   assignment.unique_identifier AS quality_identifier,
                   assignment.updated_at AS quality_updated_at,
                   option.label AS manual_label,
                   option.active AS manual_active,
                   option.updated_at AS manual_updated_at
            FROM {selection_table} selection
            LEFT JOIN quality_requirement_assignments assignment
              ON assignment.id=selection.quality_requirement_assignment_id
            LEFT JOIN {option_table} option ON option.id=selection.{option_column}
            WHERE selection.project_id=? AND selection.scenario_id=?
            ORDER BY selection.pfmea_cause_id, selection.sequence, selection.created_at,
                     selection.id""",
        (project_id, scenario_id),
    ).fetchall()
    result: list[dict] = []
    for raw in rows:
        row = dict(raw)
        if row["source_type"] == "quality_assignment":
            source_id = str(row["quality_requirement_assignment_id"])
            current_updated_at = _text(row.get("quality_updated_at"))
            label = _quality_control_label(
                {
                    "description": row.get("quality_description"),
                    "requirement_type": row.get("quality_type"),
                    "unique_identifier": row.get("quality_identifier"),
                }
            )
            active = True
        else:
            source_id = str(row[option_column])
            current_updated_at = _text(row.get("manual_updated_at"))
            label = f"Manual — {_text(row.get('manual_label')) or 'Removed option'}"
            active = bool(row.get("manual_active"))
        review_required = (
            not current_updated_at
            or current_updated_at != _text(row.get("source_updated_at_snapshot"))
        )
        row.update(
            control_type=control_type,
            source_id=source_id,
            source_key=_source_key(str(row["source_type"]), source_id),
            label=label,
            active=active,
            current_updated_at=current_updated_at,
            review_required=review_required,
        )
        result.append(row)
    return result


def pfmea_control_selections(project_id: str, scenario_id: str) -> pd.DataFrame:
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        rows = _selection_rows_conn(conn, project_id, scenario_id, "Prevention")
        rows.extend(_selection_rows_conn(conn, project_id, scenario_id, "Detection"))
    return pd.DataFrame(rows)


def _sync_control_selections(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    entry_id: str,
    cause_id: str,
    work_element_id: str,
    control_type: str,
    desired_keys: list[str],
    timestamp: str,
) -> bool:
    option_table, selection_table, option_column = _control_tables(control_type)
    existing_rows = [
        row
        for row in _selection_rows_conn(conn, project_id, scenario_id, control_type)
        if str(row["pfmea_cause_id"]) == cause_id
    ]
    existing_by_key = {str(row["source_key"]): row for row in existing_rows}
    desired = list(dict.fromkeys(desired_keys))
    if len(desired) != len(desired_keys):
        raise ValueError(f"Duplicate {control_type} controls are not allowed.")
    resolved: list[dict] = []
    for source_key in desired:
        if source_key.startswith("quality:"):
            source_id = source_key.removeprefix("quality:")
            source = conn.execute(
                """SELECT id, updated_at FROM quality_requirement_assignments
                   WHERE id=? AND project_id=? AND scenario_id=? AND work_element_id=?""",
                (source_id, project_id, scenario_id, work_element_id),
            ).fetchone()
            if not source:
                raise ValueError(
                    f"A selected {control_type} Quality requirement is not linked to this "
                    "Process Function in the active scenario."
                )
            resolved.append(
                {
                    "source_key": source_key,
                    "source_type": "quality_assignment",
                    "source_id": source_id,
                    "source_updated_at": str(source["updated_at"]),
                }
            )
        elif source_key.startswith("manual:"):
            source_id = source_key.removeprefix("manual:")
            source = conn.execute(
                f"SELECT id, active, updated_at FROM {option_table} WHERE id=? AND project_id=?",
                (source_id, project_id),
            ).fetchone()
            if not source:
                raise ValueError(f"A selected {control_type} manual option no longer exists.")
            if not bool(source["active"]) and source_key not in existing_by_key:
                raise ValueError(
                    f"Inactive {control_type} options cannot be added to a PFMEA Cause."
                )
            resolved.append(
                {
                    "source_key": source_key,
                    "source_type": "manual_option",
                    "source_id": source_id,
                    "source_updated_at": str(source["updated_at"]),
                }
            )
        else:
            raise ValueError(f"A selected {control_type} control has an invalid source.")

    changed = [str(row["source_key"]) for row in existing_rows] != desired
    for row in existing_rows:
        if str(row["source_key"]) not in desired:
            conn.execute(f"DELETE FROM {selection_table} WHERE id=?", (row["id"],))
    for position, source in enumerate(resolved, start=1):
        sequence = position * 10
        existing = existing_by_key.get(str(source["source_key"]))
        if existing:
            if (
                int(existing["sequence"]) != sequence
                or _text(existing["source_updated_at_snapshot"])
                != source["source_updated_at"]
            ):
                changed = True
            conn.execute(
                f"""UPDATE {selection_table}
                    SET sequence=?, source_updated_at_snapshot=?, updated_at=?
                    WHERE id=? AND project_id=? AND scenario_id=?""",
                (
                    sequence,
                    source["source_updated_at"],
                    timestamp,
                    existing["id"],
                    project_id,
                    scenario_id,
                ),
            )
            continue
        selection_id = str(uuid4())
        quality_id = (
            source["source_id"] if source["source_type"] == "quality_assignment" else None
        )
        option_id = source["source_id"] if source["source_type"] == "manual_option" else None
        conn.execute(
            f"""INSERT INTO {selection_table}
                (id, project_id, scenario_id, pfmea_entry_id, pfmea_cause_id,
                 source_type, quality_requirement_assignment_id, {option_column},
                 source_updated_at_snapshot, sequence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                selection_id,
                project_id,
                scenario_id,
                entry_id,
                cause_id,
                source["source_type"],
                quality_id,
                option_id,
                source["source_updated_at"],
                sequence,
                timestamp,
                timestamp,
            ),
        )
        changed = True
    conn.execute(
        """UPDATE pfmea_causes SET control_source_review_required=0,
           detection_review_required=CASE WHEN ?='Detection' AND ? THEN 1
               ELSE detection_review_required END,
           updated_at=? WHERE id=? AND project_id=? AND scenario_id=?""",
        (control_type, 1 if changed else 0, timestamp, cause_id, project_id, scenario_id),
    )
    return changed


def _process_hash(row: dict) -> str:
    return _hash({key: row.get(key) for key in row if key not in {"id", "project_id", "scenario_id"}})


def _quality_hash(rows: list[dict]) -> str:
    fields = [
        "quality_requirement_id", "requirement_type", "description", "unique_identifier",
        "pass_fail", "target_value", "tolerances", "unit", "source_updated_at", "updated_at",
    ]
    return _hash([{field: row.get(field) for field in fields} for row in rows])


def _entry(conn, project_id: str, scenario_id: str, entry_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM pfmea_entries WHERE id=? AND project_id=? AND scenario_id=?",
        (entry_id, project_id, scenario_id),
    ).fetchone()
    if not row:
        raise ValueError("The selected PFMEA entry no longer exists in this scenario.")
    return dict(row)


def _cause(conn, project_id: str, scenario_id: str, entry_id: str, cause_id: str) -> dict:
    row = conn.execute(
        """SELECT * FROM pfmea_causes
           WHERE id=? AND pfmea_entry_id=? AND project_id=? AND scenario_id=?""",
        (cause_id, entry_id, project_id, scenario_id),
    ).fetchone()
    if not row:
        raise ValueError("The selected PFMEA cause no longer exists in this scenario.")
    return dict(row)


def pfmea_process_steps(project_id: str, scenario_id: str) -> pd.DataFrame:
    work_element_labels = _process_work_element_labels(project_id, scenario_id)
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        rows = conn.execute(
            """SELECT id, sequence, station AS pitch, operation AS work_element,
                      description, location, status, updated_at
               FROM work_elements WHERE project_id=? AND scenario_id=?
               ORDER BY sequence, station, operation""",
            (project_id, scenario_id),
        ).fetchall()
    result = pd.DataFrame([dict(row) for row in rows])
    if not result.empty:
        result["work_element"] = result.apply(
            lambda row: work_element_labels.get(str(row["id"]))
            or _text(row.get("work_element")),
            axis=1,
        )
    return result


def pfmea_entries(project_id: str, scenario_id: str, work_element_id: str | None = None) -> pd.DataFrame:
    params: list[str] = [project_id, scenario_id]
    work_filter = ""
    if work_element_id:
        work_filter = " AND e.work_element_id=?"
        params.append(work_element_id)
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        rows = conn.execute(
            f"""SELECT e.*,
                       COUNT(DISTINCT ef.id) AS effect_count,
                       COUNT(DISTINCT c.id) AS cause_count,
                       MAX(rr.rpn) AS maximum_rpn
                FROM pfmea_entries e
                LEFT JOIN pfmea_effects ef ON ef.pfmea_entry_id=e.id
                LEFT JOIN pfmea_causes c ON c.pfmea_entry_id=e.id
                LEFT JOIN pfmea_risk_rows rr ON rr.pfmea_entry_id=e.id
                WHERE e.project_id=? AND e.scenario_id=?{work_filter}
                GROUP BY e.id ORDER BY e.process_sequence_snapshot, e.created_at""",
            tuple(params),
        ).fetchall()
        result = []
        for raw in rows:
            row = dict(raw)
            work = _work_element(conn, project_id, scenario_id, str(row["work_element_id"]))
            row["upstream_changes"] = _process_hash(work) != row["process_source_hash"]
            result.append(row)
    return pd.DataFrame(result)


def _process_work_element_labels(project_id: str, scenario_id: str) -> dict[str, str]:
    """Reuse the Process table's Yamazumi-description-first Work Element lookup."""
    context = _store().yamazumi_context_for_process(project_id, scenario_id)
    if context.empty:
        return {}
    first_links = context.drop_duplicates(subset=["process_element_id"], keep="first")
    return {
        str(row["process_element_id"]): _text(row.get("yamazumi_description"))
        for _, row in first_links.iterrows()
    }


def _item_label(pitch) -> str:
    return _text(pitch) or "Unassigned"


def _process_function(operation, description) -> str:
    return _text(operation)


def _responsibility_target(action: dict | None) -> str:
    if not action:
        return ""
    responsibility = _text(action.get("responsibility"))
    target = _text(action.get("target_completion_date"))
    if responsibility and target:
        return f"{responsibility} | {target}"
    if target:
        return f"| {target}"
    return responsibility


def _parse_responsibility_target(value) -> tuple[str, str]:
    text = _text(value)
    if not text:
        return "", ""
    if "|" not in text:
        return text, ""
    responsibility, target = (part.strip() for part in text.rsplit("|", 1))
    if target:
        try:
            target = pd.to_datetime(target).date().isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Responsibility & Target Completion Date must end with a valid date "
                "after |, using YYYY-MM-DD."
            ) from exc
    return responsibility, target


def _pfmea_flat_rows_conn(
    conn: sqlite3.Connection, project_id: str, scenario_id: str
) -> list[dict]:
    entries = [
        dict(row)
        for row in conn.execute(
            """SELECT * FROM pfmea_entries
               WHERE project_id=? AND scenario_id=?
               ORDER BY process_sequence_snapshot, created_at, id""",
            (project_id, scenario_id),
        ).fetchall()
    ]
    effects = [
        dict(row)
        for row in conn.execute(
            """SELECT * FROM pfmea_effects WHERE project_id=? AND scenario_id=?
               ORDER BY sequence, created_at, id""",
            (project_id, scenario_id),
        ).fetchall()
    ]
    causes = [
        dict(row)
        for row in conn.execute(
            """SELECT * FROM pfmea_causes WHERE project_id=? AND scenario_id=?
               ORDER BY sequence, created_at, id""",
            (project_id, scenario_id),
        ).fetchall()
    ]
    prevention_selections = _selection_rows_conn(
        conn, project_id, scenario_id, "Prevention"
    )
    detection_selections = _selection_rows_conn(
        conn, project_id, scenario_id, "Detection"
    )
    actions = [
        dict(row)
        for row in conn.execute(
            """SELECT * FROM pfmea_actions WHERE project_id=? AND scenario_id=?
               ORDER BY sequence, created_at, id""",
            (project_id, scenario_id),
        ).fetchall()
    ]
    risk_rows = {
        (str(row["pfmea_effect_id"]), str(row["pfmea_cause_id"])): dict(row)
        for row in conn.execute(
            "SELECT * FROM pfmea_risk_rows WHERE project_id=? AND scenario_id=?",
            (project_id, scenario_id),
        ).fetchall()
    }
    effects_by_entry: dict[str, list[dict]] = {}
    causes_by_entry: dict[str, list[dict]] = {}
    prevention_by_cause: dict[str, list[dict]] = {}
    detection_by_cause: dict[str, list[dict]] = {}
    actions_by_entry: dict[str, list[dict]] = {}
    for effect in effects:
        effects_by_entry.setdefault(str(effect["pfmea_entry_id"]), []).append(effect)
    for cause in causes:
        causes_by_entry.setdefault(str(cause["pfmea_entry_id"]), []).append(cause)
    for selection in prevention_selections:
        prevention_by_cause.setdefault(
            str(selection["pfmea_cause_id"]), []
        ).append(selection)
    for selection in detection_selections:
        detection_by_cause.setdefault(
            str(selection["pfmea_cause_id"]), []
        ).append(selection)
    for action in actions:
        actions_by_entry.setdefault(str(action["pfmea_entry_id"]), []).append(action)

    result: list[dict] = []
    for entry in entries:
        entry_id = str(entry["id"])
        work = _work_element(conn, project_id, scenario_id, str(entry["work_element_id"]))
        upstream_changes = _process_hash(work) != entry["process_source_hash"]
        entry_effects = effects_by_entry.get(entry_id) or [None]
        entry_causes = causes_by_entry.get(entry_id) or [None]
        for effect in entry_effects:
            effect_id = str(effect["id"]) if effect else ""
            for cause in entry_causes:
                cause_id = str(cause["id"]) if cause else ""
                risk = risk_rows.get((effect_id, cause_id)) if effect and cause else None
                prevention_rows = prevention_by_cause.get(cause_id, [])
                detection_rows = detection_by_cause.get(cause_id, [])
                prevention = [str(selection["source_key"]) for selection in prevention_rows]
                detection_controls = [
                    str(selection["source_key"]) for selection in detection_rows
                ]
                source_review_required = bool(
                    cause.get("control_source_review_required") if cause else False
                ) or any(
                    bool(selection["review_required"])
                    for selection in [*prevention_rows, *detection_rows]
                )
                applicable_actions = [
                    action
                    for action in actions_by_entry.get(entry_id, [])
                    if not action.get("pfmea_cause_id")
                    or str(action.get("pfmea_cause_id")) == cause_id
                ] or [None]
                for action in applicable_actions:
                    action_id = str(action["id"]) if action else ""
                    risk_id = str(risk["id"]) if risk else ""
                    line_key = "|".join(
                        [entry_id, effect_id or "-", cause_id or "-", risk_id or "-", action_id or "-"]
                    )
                    result.append(
                        {
                            "id": line_key,
                            "entry_id": entry_id,
                            "effect_id": effect_id,
                            "cause_id": cause_id,
                            "risk_row_id": risk_id,
                            "action_id": action_id,
                            "work_element_id": str(entry["work_element_id"]),
                            "item_number": _item_label(
                                entry.get("process_pitch_snapshot")
                            ),
                            "process_function": _process_function(
                                entry.get("process_operation_snapshot"),
                                entry.get("process_description_snapshot"),
                            ),
                            "potential_failure_mode": entry.get("potential_failure_mode"),
                            "potential_effects": effect.get("effect_description") if effect else "",
                            "severity": effect.get("severity") if effect else None,
                            "classification": entry.get("class_code"),
                            "potential_causes": cause.get("cause_description") if cause else "",
                            "occurrence": cause.get("occurrence") if cause else None,
                            "prevention_controls": prevention,
                            "detection_controls": detection_controls,
                            "detection": cause.get("detection") if cause else None,
                            "rpn": risk.get("rpn") if risk else None,
                            "recommended_action": action.get("recommended_action") if action else "",
                            "responsibility_target": _responsibility_target(action),
                            "actions_taken": action.get("actions_taken") if action else "",
                            "resulting_severity": action.get("resulting_severity") if action else None,
                            "resulting_occurrence": action.get("resulting_occurrence") if action else None,
                            "resulting_detection": action.get("resulting_detection") if action else None,
                            "resulting_rpn": action.get("resulting_rpn") if action else None,
                            "upstream_changes": upstream_changes,
                            "detection_review_required": bool(
                                cause.get("detection_review_required") if cause else False
                            ),
                            "control_source_review_required": source_review_required,
                        }
                    )
    return result


def pfmea_flat_rows(project_id: str, scenario_id: str) -> pd.DataFrame:
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        rows = _pfmea_flat_rows_conn(conn, project_id, scenario_id)
    return pd.DataFrame(rows)


def save_pfmea_entry_rows(
    project_id: str, scenario_id: str, work_element_id: str, edited: pd.DataFrame
) -> dict:
    timestamp = _store().now_iso()
    work_element_labels = _process_work_element_labels(project_id, scenario_id)
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        work = _work_element(conn, project_id, scenario_id, work_element_id)
        existing = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM pfmea_entries WHERE project_id=? AND scenario_id=? AND work_element_id=?",
                (project_id, scenario_id, work_element_id),
            ).fetchall()
        }
        supplied_ids = {_text(row.get("id")) for _, row in edited.iterrows() if _text(row.get("id"))}
        if set(existing) - supplied_ids:
            raise ValueError("Remove PFMEA entries through the confirmed deletion workflow.")
        created: list[str] = []
        updated: list[str] = []
        for _, row in edited.iterrows():
            failure_mode = _text(row.get("potential_failure_mode"))
            if not failure_mode:
                continue
            entry_id = _text(row.get("id"))
            if entry_id:
                if entry_id not in existing:
                    raise ValueError("A PFMEA entry changed or no longer exists. Refresh and try again.")
                conn.execute(
                    """UPDATE pfmea_entries SET potential_failure_mode=?, class_code=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=? AND work_element_id=?""",
                    (failure_mode, _classification(row.get("class_code")), timestamp, entry_id,
                     project_id, scenario_id, work_element_id),
                )
                updated.append(entry_id)
            else:
                entry_id = str(uuid4())
                conn.execute(
                    """INSERT INTO pfmea_entries
                       (id, project_id, scenario_id, work_element_id, potential_failure_mode,
                        class_code, process_operation_snapshot, process_description_snapshot,
                        process_location_snapshot, process_pitch_snapshot,
                        process_sequence_snapshot, process_source_hash, quality_source_hash,
                        source_reviewed_at, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (entry_id, project_id, scenario_id, work_element_id, failure_mode,
                     _classification(row.get("class_code")),
                     work_element_labels.get(work_element_id)
                     or _text(work.get("operation")),
                     _text(work.get("description")), _text(work.get("location")),
                     _text(work.get("station")), int(work.get("sequence") or 0),
                     _process_hash(work), _quality_hash([]), timestamp, timestamp, timestamp),
                )
                created.append(entry_id)
        return {"row_count": len(created) + len(updated), "created_ids": created,
                "updated_ids": updated, "timestamp": timestamp}


def _save_child_rows(
    *, table: str, project_id: str, scenario_id: str, entry_id: str,
    edited: pd.DataFrame, text_field: str, numeric_fields: list[str],
) -> dict:
    timestamp = _store().now_iso()
    with _store().connection() as conn:
        _entry(conn, project_id, scenario_id, entry_id)
        existing = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                f"SELECT * FROM {table} WHERE pfmea_entry_id=? AND project_id=? AND scenario_id=?",
                (entry_id, project_id, scenario_id),
            ).fetchall()
        }
        supplied = {_text(row.get("id")) for _, row in edited.iterrows() if _text(row.get("id"))}
        if set(existing) - supplied:
            raise ValueError("Remove selected rows through the confirmed deletion workflow.")
        created: list[str] = []
        updated: list[str] = []
        for position, (_, row) in enumerate(edited.iterrows(), start=1):
            description = _text(row.get(text_field))
            if not description:
                continue
            row_id = _text(row.get("id"))
            values = {field: _rating(row.get(field), field.replace("_", " ").capitalize()) for field in numeric_fields}
            seq = _sequence(row.get("sequence"), position * 10)
            if row_id:
                if row_id not in existing:
                    raise ValueError("A PFMEA detail changed or no longer exists. Refresh and try again.")
                assignments = [f"{text_field}=?", *[f"{field}=?" for field in numeric_fields], "sequence=?"]
                if table == "pfmea_causes":
                    assignments.append("detection_review_required=0")
                assignments.append("updated_at=?")
                conn.execute(
                    f"UPDATE {table} SET {', '.join(assignments)} WHERE id=? AND project_id=? AND scenario_id=? AND pfmea_entry_id=?",
                    (description, *[values[field] for field in numeric_fields], seq, timestamp,
                     row_id, project_id, scenario_id, entry_id),
                )
                updated.append(row_id)
            else:
                row_id = str(uuid4())
                columns = ["id", "project_id", "scenario_id", "pfmea_entry_id", text_field,
                           *numeric_fields, "sequence", "created_at", "updated_at"]
                conn.execute(
                    f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    (row_id, project_id, scenario_id, entry_id, description,
                     *[values[field] for field in numeric_fields], seq, timestamp, timestamp),
                )
                created.append(row_id)
        _rebuild_risk_rows(conn, project_id, scenario_id, entry_id, timestamp)
        return {"row_count": len(created) + len(updated), "created_ids": created,
                "updated_ids": updated, "timestamp": timestamp}


def pfmea_effects(project_id: str, scenario_id: str, entry_id: str) -> pd.DataFrame:
    with _store().connection() as conn:
        _entry(conn, project_id, scenario_id, entry_id)
        rows = conn.execute(
            "SELECT * FROM pfmea_effects WHERE pfmea_entry_id=? ORDER BY sequence, created_at",
            (entry_id,),
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def save_pfmea_effect_rows(project_id: str, scenario_id: str, entry_id: str, edited: pd.DataFrame) -> dict:
    return _save_child_rows(table="pfmea_effects", project_id=project_id,
                            scenario_id=scenario_id, entry_id=entry_id, edited=edited,
                            text_field="effect_description", numeric_fields=["severity"])


def pfmea_causes(project_id: str, scenario_id: str, entry_id: str) -> pd.DataFrame:
    with _store().connection() as conn:
        _entry(conn, project_id, scenario_id, entry_id)
        rows = conn.execute(
            "SELECT * FROM pfmea_causes WHERE pfmea_entry_id=? ORDER BY sequence, created_at",
            (entry_id,),
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def save_pfmea_cause_rows(project_id: str, scenario_id: str, entry_id: str, edited: pd.DataFrame) -> dict:
    return _save_child_rows(table="pfmea_causes", project_id=project_id,
                            scenario_id=scenario_id, entry_id=entry_id, edited=edited,
                            text_field="cause_description", numeric_fields=["occurrence", "detection"])


def _rebuild_risk_rows(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    entry_id: str,
    timestamp: str,
) -> None:
    """Refresh one stable risk row for every saved Effect-Cause combination."""
    effects = [
        dict(row)
        for row in conn.execute(
            """SELECT id, severity FROM pfmea_effects
               WHERE project_id=? AND scenario_id=? AND pfmea_entry_id=?""",
            (project_id, scenario_id, entry_id),
        ).fetchall()
    ]
    causes = [
        dict(row)
        for row in conn.execute(
            """SELECT id, occurrence, detection FROM pfmea_causes
               WHERE project_id=? AND scenario_id=? AND pfmea_entry_id=?""",
            (project_id, scenario_id, entry_id),
        ).fetchall()
    ]
    existing = {
        (str(row["pfmea_effect_id"]), str(row["pfmea_cause_id"])): dict(row)
        for row in conn.execute(
            """SELECT * FROM pfmea_risk_rows
               WHERE project_id=? AND scenario_id=? AND pfmea_entry_id=?""",
            (project_id, scenario_id, entry_id),
        ).fetchall()
    }
    desired_pairs = {
        (str(effect["id"]), str(cause["id"]))
        for effect in effects
        for cause in causes
    }
    for pair, risk_row in existing.items():
        if pair not in desired_pairs:
            conn.execute("DELETE FROM pfmea_risk_rows WHERE id=?", (risk_row["id"],))

    for effect in effects:
        for cause in causes:
            pair = (str(effect["id"]), str(cause["id"]))
            ratings = (effect.get("severity"), cause.get("occurrence"), cause.get("detection"))
            rpn = math.prod(ratings) if all(value is not None for value in ratings) else None
            risk_row = existing.get(pair)
            if risk_row:
                conn.execute(
                    """UPDATE pfmea_risk_rows SET rpn=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=?""",
                    (rpn, timestamp, risk_row["id"], project_id, scenario_id),
                )
            else:
                conn.execute(
                    """INSERT INTO pfmea_risk_rows
                       (id, project_id, scenario_id, pfmea_entry_id,
                        pfmea_effect_id, pfmea_cause_id, rpn, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid4()), project_id, scenario_id, entry_id,
                        pair[0], pair[1], rpn, timestamp, timestamp,
                    ),
                )


def pfmea_risk_rows(project_id: str, scenario_id: str, entry_id: str) -> pd.DataFrame:
    with _store().connection() as conn:
        _entry(conn, project_id, scenario_id, entry_id)
        rows = conn.execute(
            """SELECT rr.id, ef.effect_description, ef.severity,
                      c.cause_description, c.occurrence, c.detection, rr.rpn
               FROM pfmea_risk_rows rr
               JOIN pfmea_effects ef ON ef.id=rr.pfmea_effect_id
               JOIN pfmea_causes c ON c.id=rr.pfmea_cause_id
               WHERE rr.pfmea_entry_id=? AND rr.project_id=? AND rr.scenario_id=?
               ORDER BY ef.sequence, c.sequence""",
            (entry_id, project_id, scenario_id),
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def pfmea_actions(project_id: str, scenario_id: str, entry_id: str) -> pd.DataFrame:
    with _store().connection() as conn:
        _entry(conn, project_id, scenario_id, entry_id)
        rows = conn.execute(
            """SELECT a.*, c.cause_description
               FROM pfmea_actions a LEFT JOIN pfmea_causes c ON c.id=a.pfmea_cause_id
               WHERE a.pfmea_entry_id=? AND a.project_id=? AND a.scenario_id=?
               ORDER BY a.sequence, a.created_at""",
            (entry_id, project_id, scenario_id),
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def save_pfmea_action_rows(project_id: str, scenario_id: str, entry_id: str,
                           edited: pd.DataFrame) -> dict:
    timestamp = _store().now_iso()
    with _store().connection() as conn:
        _entry(conn, project_id, scenario_id, entry_id)
        valid_causes = {str(row[0]) for row in conn.execute(
            "SELECT id FROM pfmea_causes WHERE pfmea_entry_id=?", (entry_id,)
        ).fetchall()}
        existing = {str(row["id"]): dict(row) for row in conn.execute(
            "SELECT * FROM pfmea_actions WHERE pfmea_entry_id=?", (entry_id,)
        ).fetchall()}
        supplied = {_text(row.get("id")) for _, row in edited.iterrows() if _text(row.get("id"))}
        if set(existing) - supplied:
            raise ValueError("Remove PFMEA actions through the confirmed deletion workflow.")
        created: list[str] = []
        updated: list[str] = []
        for position, (_, row) in enumerate(edited.iterrows(), start=1):
            action = _text(row.get("recommended_action"))
            if not action:
                continue
            action_id = _text(row.get("id"))
            cause_id = _text(row.get("pfmea_cause_id")) or None
            if cause_id and cause_id not in valid_causes:
                raise ValueError("The selected PFMEA cause no longer belongs to this failure mode.")
            ratings = [
                _rating(row.get("resulting_severity"), "Resulting Severity"),
                _rating(row.get("resulting_occurrence"), "Resulting Occurrence"),
                _rating(row.get("resulting_detection"), "Resulting Detection"),
            ]
            resulting_rpn = math.prod(ratings) if all(value is not None for value in ratings) else None
            target_value = row.get("target_completion_date")
            target_date = ""
            if target_value is not None and _text(target_value):
                try:
                    target_date = pd.to_datetime(target_value).date().isoformat()
                except (TypeError, ValueError) as exc:
                    raise ValueError("Target Completion Date must be a valid date.") from exc
            values = (cause_id, action, _text(row.get("responsibility")),
                      target_date, _text(row.get("actions_taken")),
                      *ratings, resulting_rpn, _sequence(row.get("sequence"), position * 10))
            if action_id:
                if action_id not in existing:
                    raise ValueError("A PFMEA action changed or no longer exists. Refresh and try again.")
                conn.execute(
                    """UPDATE pfmea_actions SET pfmea_cause_id=?, recommended_action=?,
                       responsibility=?, target_completion_date=?, actions_taken=?,
                       resulting_severity=?, resulting_occurrence=?, resulting_detection=?,
                       resulting_rpn=?, sequence=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=? AND pfmea_entry_id=?""",
                    (*values, timestamp, action_id, project_id, scenario_id, entry_id),
                )
                updated.append(action_id)
            else:
                action_id = str(uuid4())
                conn.execute(
                    """INSERT INTO pfmea_actions
                       (id, project_id, scenario_id, pfmea_entry_id, pfmea_cause_id,
                        recommended_action, responsibility, target_completion_date,
                        actions_taken, resulting_severity, resulting_occurrence,
                        resulting_detection, resulting_rpn, sequence, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (action_id, project_id, scenario_id, entry_id, *values, timestamp, timestamp),
                )
                created.append(action_id)
        return {"row_count": len(created) + len(updated), "created_ids": created,
                "updated_ids": updated, "timestamp": timestamp}


def _repeated_edit_value(
    rows: list[dict], column: str, saved_value, label: str, normalize
):
    saved = normalize(saved_value)
    changes = {normalize(row.get(column)) for row in rows if normalize(row.get(column)) != saved}
    if len(changes) > 1:
        raise ValueError(
            f"{label} is repeated on more than one PFMEA line with conflicting edits. "
            "Keep the repeated values consistent and try again."
        )
    return next(iter(changes)) if changes else saved


def save_pfmea_flat_rows(
    project_id: str,
    scenario_id: str,
    edited: pd.DataFrame,
    *,
    force_new_draft_ids: set[str] | None = None,
) -> dict:
    """Save the template-aligned flat view back into the normalized PFMEA graph."""
    timestamp = _store().now_iso()
    work_element_labels = _process_work_element_labels(project_id, scenario_id)
    records = edited.to_dict("records")
    force_new = {_text(value) for value in (force_new_draft_ids or set()) if _text(value)}
    forced_records = [
        row for row in records if _text(row.get("draft_row_id")) in force_new
    ]
    if len(forced_records) != len(force_new) or any(
        _text(row.get("id")) for row in forced_records
    ):
        raise ValueError(
            "A PFMEA line selected for independent duplication changed. "
            "Undo the draft and duplicate it again."
        )
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        existing_flat = _pfmea_flat_rows_conn(conn, project_id, scenario_id)
        existing_line_ids = {str(row["id"]) for row in existing_flat}
        supplied_line_ids = {_text(row.get("id")) for row in records if _text(row.get("id"))}
        unknown_line_ids = supplied_line_ids - existing_line_ids
        if unknown_line_ids:
            raise ValueError("A PFMEA line changed or no longer exists. Refresh and try again.")
        if existing_line_ids - supplied_line_ids:
            raise ValueError(
                "Remove PFMEA lines only through the confirmed relationship-safe deletion workflow."
            )

        entries = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM pfmea_entries WHERE project_id=? AND scenario_id=?",
                (project_id, scenario_id),
            ).fetchall()
        }
        effects = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM pfmea_effects WHERE project_id=? AND scenario_id=?",
                (project_id, scenario_id),
            ).fetchall()
        }
        causes = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM pfmea_causes WHERE project_id=? AND scenario_id=?",
                (project_id, scenario_id),
            ).fetchall()
        }
        actions = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM pfmea_actions WHERE project_id=? AND scenario_id=?",
                (project_id, scenario_id),
            ).fetchall()
        }
        risk_rows = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM pfmea_risk_rows WHERE project_id=? AND scenario_id=?",
                (project_id, scenario_id),
            ).fetchall()
        }
        work_rows = [
            dict(row)
            for row in conn.execute(
                """SELECT * FROM work_elements WHERE project_id=? AND scenario_id=?
                   ORDER BY sequence, station, operation, id""",
                (project_id, scenario_id),
            ).fetchall()
        ]
        work_by_id = {str(row["id"]): row for row in work_rows}

        for row in records:
            entry_id = _text(row.get("entry_id"))
            effect_id = _text(row.get("effect_id"))
            cause_id = _text(row.get("cause_id"))
            risk_id = _text(row.get("risk_row_id"))
            action_id = _text(row.get("action_id"))
            if entry_id and entry_id not in entries:
                raise ValueError("A linked PFMEA failure mode no longer exists in this scenario.")
            if effect_id and (
                effect_id not in effects or str(effects[effect_id]["pfmea_entry_id"]) != entry_id
            ):
                raise ValueError("A linked PFMEA Effect no longer belongs to this failure mode.")
            if cause_id and (
                cause_id not in causes or str(causes[cause_id]["pfmea_entry_id"]) != entry_id
            ):
                raise ValueError("A linked PFMEA Cause no longer belongs to this failure mode.")
            if risk_id:
                risk = risk_rows.get(risk_id)
                if not risk or (
                    str(risk["pfmea_entry_id"]) != entry_id
                    or str(risk["pfmea_effect_id"]) != effect_id
                    or str(risk["pfmea_cause_id"]) != cause_id
                ):
                    raise ValueError("A linked PFMEA RPN line no longer matches its Effect and Cause.")
            if action_id:
                action = actions.get(action_id)
                if not action or str(action["pfmea_entry_id"]) != entry_id:
                    raise ValueError("A linked Recommended Action no longer belongs to this failure mode.")
                action_cause = _text(action.get("pfmea_cause_id"))
                if action_cause and action_cause != cause_id:
                    raise ValueError("A linked Recommended Action no longer belongs to this Cause.")

        affected_entries: set[str] = set()
        changed_rows = 0
        for entry_id, entry in entries.items():
            entry_rows = [row for row in records if _text(row.get("entry_id")) == entry_id]
            if not entry_rows:
                continue
            expected_item = _item_label(entry.get("process_pitch_snapshot"))
            expected_work_id = str(entry["work_element_id"])
            if any(
                _text(row.get("work_element_id")) != expected_work_id
                for row in entry_rows
            ):
                raise ValueError(
                    "Item # is linked to its saved Process at a Glance step and cannot be "
                    "reassigned by editing the PFMEA table."
                )
            if any(_text(row.get("item_number")) != expected_item for row in entry_rows):
                raise ValueError(
                    "Item # is linked to its saved Process at a Glance step and cannot be "
                    "reassigned by editing the PFMEA table."
                )
            failure_mode = _repeated_edit_value(
                entry_rows, "potential_failure_mode", entry["potential_failure_mode"],
                "Potential Failure Mode", _text,
            )
            saved_classification = _text(entry["class_code"])
            classification = _repeated_edit_value(
                entry_rows, "classification", saved_classification,
                "Classification", _text,
            )
            classification = _classification(classification)
            conn.execute(
                """UPDATE pfmea_entries SET potential_failure_mode=?, class_code=?, updated_at=?
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (failure_mode, classification, timestamp, entry_id, project_id, scenario_id),
            )
            affected_entries.add(entry_id)
            changed_rows += 1

        for effect_id, effect in effects.items():
            effect_rows = [row for row in records if _text(row.get("effect_id")) == effect_id]
            if not effect_rows:
                continue
            description = _repeated_edit_value(
                effect_rows, "potential_effects", effect["effect_description"],
                "Potential Effect(s) of Failure", _text,
            )
            severity = _repeated_edit_value(
                effect_rows, "severity", effect.get("severity"), "Severity",
                lambda value: _rating(value, "Severity"),
            )
            conn.execute(
                """UPDATE pfmea_effects SET effect_description=?, severity=?, updated_at=?
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (description, severity, timestamp, effect_id, project_id, scenario_id),
            )
            affected_entries.add(str(effect["pfmea_entry_id"]))
            changed_rows += 1

        for cause_id, cause in causes.items():
            cause_rows = [row for row in records if _text(row.get("cause_id")) == cause_id]
            if not cause_rows:
                continue
            description = _repeated_edit_value(
                cause_rows, "potential_causes", cause["cause_description"],
                "Potential Cause(s) of Failure", _text,
            )
            occurrence = _repeated_edit_value(
                cause_rows, "occurrence", cause.get("occurrence"), "Occurrence",
                lambda value: _rating(value, "Occurrence"),
            )
            detection = _repeated_edit_value(
                cause_rows, "detection", cause.get("detection"), "Detection",
                lambda value: _rating(value, "Detection"),
            )
            conn.execute(
                """UPDATE pfmea_causes SET cause_description=?, occurrence=?, detection=?,
                   detection_review_required=0, control_source_review_required=0, updated_at=?
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (description, occurrence, detection, timestamp, cause_id, project_id, scenario_id),
            )
            affected_entries.add(str(cause["pfmea_entry_id"]))
            changed_rows += 1

        for action_id, action in actions.items():
            action_rows = [row for row in records if _text(row.get("action_id")) == action_id]
            if not action_rows:
                continue
            recommended = _repeated_edit_value(
                action_rows, "recommended_action", action["recommended_action"],
                "Recommended Action", _text,
            )
            responsibility_target = _repeated_edit_value(
                action_rows, "responsibility_target", _responsibility_target(action),
                "Responsibility & Target Completion Date", _text,
            )
            responsibility, target_date = _parse_responsibility_target(responsibility_target)
            actions_taken = _repeated_edit_value(
                action_rows, "actions_taken", action.get("actions_taken"), "Actions Taken", _text,
            )
            resulting_severity = _repeated_edit_value(
                action_rows, "resulting_severity", action.get("resulting_severity"),
                "Resulting Severity", lambda value: _rating(value, "Resulting Severity"),
            )
            resulting_occurrence = _repeated_edit_value(
                action_rows, "resulting_occurrence", action.get("resulting_occurrence"),
                "Resulting Occurrence", lambda value: _rating(value, "Resulting Occurrence"),
            )
            resulting_detection = _repeated_edit_value(
                action_rows, "resulting_detection", action.get("resulting_detection"),
                "Resulting Detection", lambda value: _rating(value, "Resulting Detection"),
            )
            ratings = (resulting_severity, resulting_occurrence, resulting_detection)
            resulting_rpn = math.prod(ratings) if all(value is not None for value in ratings) else None
            conn.execute(
                """UPDATE pfmea_actions SET recommended_action=?, responsibility=?,
                   target_completion_date=?, actions_taken=?, resulting_severity=?,
                   resulting_occurrence=?, resulting_detection=?, resulting_rpn=?, updated_at=?
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (recommended, responsibility, target_date, actions_taken, resulting_severity,
                 resulting_occurrence, resulting_detection, resulting_rpn, timestamp,
                 action_id, project_id, scenario_id),
            )
            affected_entries.add(str(action["pfmea_entry_id"]))
            changed_rows += 1

        # A normalized entry may legitimately have no Effect, Cause, or Action yet.
        # Its flat placeholder line keeps the entry ID while the missing child IDs are blank.
        for row in records:
            entry_id = _text(row.get("entry_id"))
            if not entry_id:
                continue
            effect_id = _text(row.get("effect_id"))
            cause_id = _text(row.get("cause_id"))
            effect_description = _text(row.get("potential_effects"))
            cause_description = _text(row.get("potential_causes"))
            severity = _rating(row.get("severity"), "Severity")
            if not effect_id and (effect_description or severity is not None):
                matching_effects = [
                    item for item in effects.values()
                    if str(item["pfmea_entry_id"]) == entry_id
                    and _text(item["effect_description"]).casefold()
                    == effect_description.casefold()
                ]
                if matching_effects:
                    effect_id = str(matching_effects[0]["id"])
                else:
                    effect_id = str(uuid4())
                    next_sequence = 10 + max(
                        [
                            int(item.get("sequence") or 0)
                            for item in effects.values()
                            if str(item["pfmea_entry_id"]) == entry_id
                        ]
                        or [0]
                    )
                    conn.execute(
                        """INSERT INTO pfmea_effects
                           (id, project_id, scenario_id, pfmea_entry_id,
                            effect_description, severity, sequence, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (effect_id, project_id, scenario_id, entry_id, effect_description,
                         severity, next_sequence, timestamp, timestamp),
                    )
                    effects[effect_id] = {
                        "id": effect_id, "pfmea_entry_id": entry_id,
                        "effect_description": effect_description, "severity": severity,
                        "sequence": next_sequence,
                    }
                    changed_rows += 1
                row["effect_id"] = effect_id
            occurrence = _rating(row.get("occurrence"), "Occurrence")
            detection = _rating(row.get("detection"), "Detection")
            has_cause_values = bool(
                cause_description
                or _source_values(row.get("prevention_controls"))
                or _source_values(row.get("detection_controls"))
            ) or any(value is not None for value in (occurrence, detection))
            if not cause_id and has_cause_values:
                matching_causes = [
                    item for item in causes.values()
                    if str(item["pfmea_entry_id"]) == entry_id
                    and _text(item["cause_description"]).casefold()
                    == cause_description.casefold()
                ]
                if matching_causes:
                    cause_id = str(matching_causes[0]["id"])
                else:
                    cause_id = str(uuid4())
                    next_sequence = 10 + max(
                        [
                            int(item.get("sequence") or 0)
                            for item in causes.values()
                            if str(item["pfmea_entry_id"]) == entry_id
                        ]
                        or [0]
                    )
                    conn.execute(
                        """INSERT INTO pfmea_causes
                           (id, project_id, scenario_id, pfmea_entry_id, cause_description,
                            occurrence, detection, sequence, detection_review_required,
                            control_source_review_required, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (cause_id, project_id, scenario_id, entry_id, cause_description,
                         occurrence, detection, next_sequence,
                         1 if bool(row.get("detection_review_required")) else 0,
                         1 if bool(row.get("control_source_review_required")) else 0,
                         timestamp, timestamp),
                    )
                    causes[cause_id] = {
                        "id": cause_id, "pfmea_entry_id": entry_id,
                        "cause_description": cause_description, "occurrence": occurrence,
                        "detection": detection, "sequence": next_sequence,
                    }
                    changed_rows += 1
                row["cause_id"] = cause_id
            affected_entries.add(entry_id)

        created_action_keys: set[tuple[str, str, str]] = set()
        for row in records:
            if _text(row.get("action_id")):
                continue
            entry_id = _text(row.get("entry_id"))
            if not entry_id:
                continue
            cause_id = _text(row.get("cause_id"))
            recommended = _text(row.get("recommended_action"))
            responsibility, target_date = _parse_responsibility_target(
                row.get("responsibility_target")
            )
            actions_taken = _text(row.get("actions_taken"))
            ratings = (
                _rating(row.get("resulting_severity"), "Resulting Severity"),
                _rating(row.get("resulting_occurrence"), "Resulting Occurrence"),
                _rating(row.get("resulting_detection"), "Resulting Detection"),
            )
            if not (
                recommended or responsibility or target_date or actions_taken
                or any(value is not None for value in ratings)
            ):
                continue
            action_key = (entry_id, cause_id, recommended.casefold())
            if action_key in created_action_keys:
                continue
            resulting_rpn = math.prod(ratings) if all(value is not None for value in ratings) else None
            action_id = str(uuid4())
            conn.execute(
                """INSERT INTO pfmea_actions
                   (id, project_id, scenario_id, pfmea_entry_id, pfmea_cause_id,
                    recommended_action, responsibility, target_completion_date,
                    actions_taken, resulting_severity, resulting_occurrence,
                    resulting_detection, resulting_rpn, sequence, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (action_id, project_id, scenario_id, entry_id, cause_id or None,
                 recommended, responsibility, target_date, actions_taken,
                 *ratings, resulting_rpn, 10, timestamp, timestamp),
            )
            created_action_keys.add(action_key)
            affected_entries.add(entry_id)
            changed_rows += 1

        new_rows = [row for row in records if not _text(row.get("id"))]
        for row in new_rows:
            force_independent = _text(row.get("draft_row_id")) in force_new
            work_id = _text(row.get("work_element_id"))
            work = work_by_id.get(work_id)
            if not work:
                raise ValueError("Choose a valid Process Function from the active scenario.")
            failure_mode = _text(row.get("potential_failure_mode"))
            effect_description = _text(row.get("potential_effects"))
            cause_description = _text(row.get("potential_causes"))
            classification = _classification(row.get("classification"))
            entry_matches = (
                [
                    entry for entry in entries.values()
                    if str(entry["work_element_id"]) == work_id
                    and _text(entry["potential_failure_mode"]).casefold()
                    == failure_mode.casefold()
                ]
                if failure_mode and not force_independent
                else []
            )
            if len(entry_matches) > 1:
                raise ValueError(
                    "More than one saved failure mode matches this new line. Refresh and edit "
                    "the intended saved line instead."
                )
            if entry_matches:
                entry = entry_matches[0]
                entry_id = str(entry["id"])
                if classification and classification != _text(entry["class_code"]):
                    conn.execute(
                        "UPDATE pfmea_entries SET class_code=?, updated_at=? WHERE id=?",
                        (classification, timestamp, entry_id),
                    )
            else:
                entry_id = str(uuid4())
                conn.execute(
                    """INSERT INTO pfmea_entries
                       (id, project_id, scenario_id, work_element_id, potential_failure_mode,
                        class_code, process_operation_snapshot, process_description_snapshot,
                        process_location_snapshot, process_pitch_snapshot,
                        process_sequence_snapshot, process_source_hash, quality_source_hash,
                        source_reviewed_at, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (entry_id, project_id, scenario_id, work_id, failure_mode, classification,
                     work_element_labels.get(work_id) or _text(work.get("operation")),
                     _text(work.get("description")),
                     _text(work.get("location")), _text(work.get("station")),
                     int(work.get("sequence") or 0), _process_hash(work), _quality_hash([]),
                     timestamp, timestamp, timestamp),
                )
                entry = dict(id=entry_id, work_element_id=work_id,
                             potential_failure_mode=failure_mode, class_code=classification)
                entries[entry_id] = entry

            severity = _rating(row.get("severity"), "Severity")
            has_effect = bool(effect_description) or severity is not None
            effect_matches = (
                [
                    effect for effect in effects.values()
                    if str(effect["pfmea_entry_id"]) == entry_id
                    and _text(effect["effect_description"]).casefold()
                    == effect_description.casefold()
                ]
                if effect_description and not force_independent
                else []
            )
            if len(effect_matches) > 1:
                raise ValueError("More than one saved Effect matches this new line.")
            effect_id = ""
            if has_effect and effect_matches:
                effect = effect_matches[0]
                effect_id = str(effect["id"])
                if severity != effect.get("severity"):
                    conn.execute(
                        "UPDATE pfmea_effects SET severity=?, updated_at=? WHERE id=?",
                        (severity, timestamp, effect_id),
                    )
            elif has_effect:
                effect_id = str(uuid4())
                next_effect_sequence = 10 + max(
                    [
                        int(item.get("sequence") or 0)
                        for item in effects.values()
                        if str(item["pfmea_entry_id"]) == entry_id
                    ]
                    or [0]
                )
                conn.execute(
                    """INSERT INTO pfmea_effects
                       (id, project_id, scenario_id, pfmea_entry_id, effect_description,
                        severity, sequence, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (effect_id, project_id, scenario_id, entry_id, effect_description,
                     severity, next_effect_sequence, timestamp, timestamp),
                )
                effects[effect_id] = dict(
                    id=effect_id, pfmea_entry_id=entry_id,
                    effect_description=effect_description, severity=severity,
                    sequence=next_effect_sequence,
                )

            occurrence = _rating(row.get("occurrence"), "Occurrence")
            detection = _rating(row.get("detection"), "Detection")
            prevention_values = _source_values(row.get("prevention_controls"))
            detection_values = _source_values(row.get("detection_controls"))
            has_cause = bool(cause_description or prevention_values or detection_values) or any(
                value is not None for value in (occurrence, detection)
            )
            cause_matches = (
                [
                    cause for cause in causes.values()
                    if str(cause["pfmea_entry_id"]) == entry_id
                    and _text(cause["cause_description"]).casefold()
                    == cause_description.casefold()
                ]
                if cause_description and not force_independent
                else []
            )
            if len(cause_matches) > 1:
                raise ValueError("More than one saved Cause matches this new line.")
            cause_id = ""
            if has_cause and cause_matches:
                cause = cause_matches[0]
                cause_id = str(cause["id"])
                conn.execute(
                    """UPDATE pfmea_causes SET occurrence=?, detection=?,
                       updated_at=? WHERE id=?""",
                    (occurrence, detection, timestamp, cause_id),
                )
            elif has_cause:
                cause_id = str(uuid4())
                next_cause_sequence = 10 + max(
                    [
                        int(item.get("sequence") or 0)
                        for item in causes.values()
                        if str(item["pfmea_entry_id"]) == entry_id
                    ]
                    or [0]
                )
                conn.execute(
                    """INSERT INTO pfmea_causes
                       (id, project_id, scenario_id, pfmea_entry_id, cause_description,
                        occurrence, detection, sequence, detection_review_required,
                        control_source_review_required, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (cause_id, project_id, scenario_id, entry_id, cause_description,
                     occurrence, detection, next_cause_sequence,
                     1 if bool(row.get("detection_review_required")) else 0,
                     1 if bool(row.get("control_source_review_required")) else 0,
                     timestamp, timestamp),
                )
                causes[cause_id] = dict(
                    id=cause_id, pfmea_entry_id=entry_id,
                    cause_description=cause_description, occurrence=occurrence,
                    detection=detection, sequence=next_cause_sequence,
                )
            row["entry_id"] = entry_id
            row["effect_id"] = effect_id
            row["cause_id"] = cause_id

            recommended = _text(row.get("recommended_action"))
            responsibility, target_date = _parse_responsibility_target(
                row.get("responsibility_target")
            )
            actions_taken = _text(row.get("actions_taken"))
            resulting_ratings = (
                _rating(row.get("resulting_severity"), "Resulting Severity"),
                _rating(row.get("resulting_occurrence"), "Resulting Occurrence"),
                _rating(row.get("resulting_detection"), "Resulting Detection"),
            )
            has_action = bool(recommended or responsibility or target_date or actions_taken) or any(
                value is not None for value in resulting_ratings
            )
            if has_action:
                resulting_rpn = (
                    math.prod(resulting_ratings)
                    if all(value is not None for value in resulting_ratings)
                    else None
                )
                action_id = str(uuid4())
                conn.execute(
                    """INSERT INTO pfmea_actions
                       (id, project_id, scenario_id, pfmea_entry_id, pfmea_cause_id,
                        recommended_action, responsibility, target_completion_date,
                        actions_taken, resulting_severity, resulting_occurrence,
                        resulting_detection, resulting_rpn, sequence, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (action_id, project_id, scenario_id, entry_id, cause_id or None, recommended,
                     responsibility, target_date, actions_taken,
                     *resulting_ratings, resulting_rpn, 10, timestamp, timestamp),
                )
            elif effect_id and cause_id:
                already_exists = conn.execute(
                    """SELECT 1 FROM pfmea_risk_rows
                       WHERE pfmea_entry_id=? AND pfmea_effect_id=? AND pfmea_cause_id=?""",
                    (entry_id, effect_id, cause_id),
                ).fetchone()
                if already_exists:
                    raise ValueError(
                        "This Effect and Cause combination already exists. Add a Recommended "
                        "Action or edit the saved line instead."
                    )
            affected_entries.add(entry_id)
            changed_rows += 1

        for cause_id, cause in causes.items():
            cause_rows = [row for row in records if _text(row.get("cause_id")) == cause_id]
            if not cause_rows:
                continue
            entry_id = str(cause["pfmea_entry_id"])
            entry = entries.get(entry_id)
            if not entry:
                raise ValueError("A PFMEA Cause no longer belongs to a valid failure mode.")
            prevention = list(
                _repeated_edit_value(
                    cause_rows,
                    "prevention_controls",
                    tuple(
                        row["source_key"]
                        for row in _selection_rows_conn(
                            conn, project_id, scenario_id, "Prevention"
                        )
                        if str(row["pfmea_cause_id"]) == cause_id
                    ),
                    "Current Process Controls — Prevention",
                    lambda value: tuple(_source_values(value)),
                )
            )
            detection_values = list(
                _repeated_edit_value(
                    cause_rows,
                    "detection_controls",
                    tuple(
                        row["source_key"]
                        for row in _selection_rows_conn(
                            conn, project_id, scenario_id, "Detection"
                        )
                        if str(row["pfmea_cause_id"]) == cause_id
                    ),
                    "Current Process Controls — Detection",
                    lambda value: tuple(_source_values(value)),
                )
            )
            if _sync_control_selections(
                conn,
                project_id,
                scenario_id,
                entry_id,
                cause_id,
                str(entry["work_element_id"]),
                "Prevention",
                prevention,
                timestamp,
            ):
                changed_rows += 1
            if _sync_control_selections(
                conn,
                project_id,
                scenario_id,
                entry_id,
                cause_id,
                str(entry["work_element_id"]),
                "Detection",
                detection_values,
                timestamp,
            ):
                changed_rows += 1
            affected_entries.add(entry_id)

        for entry_id in affected_entries:
            _rebuild_risk_rows(conn, project_id, scenario_id, entry_id, timestamp)
        return {
            "row_count": changed_rows,
            "affected_entry_ids": sorted(affected_entries),
            "timestamp": timestamp,
        }


def review_pfmea_sources(project_id: str, scenario_id: str, entry_id: str) -> dict:
    timestamp = _store().now_iso()
    work_element_labels = _process_work_element_labels(project_id, scenario_id)
    with _store().connection() as conn:
        entry = _entry(conn, project_id, scenario_id, entry_id)
        work = _work_element(conn, project_id, scenario_id, str(entry["work_element_id"]))
        conn.execute(
            """UPDATE pfmea_entries SET process_operation_snapshot=?,
               process_description_snapshot=?, process_location_snapshot=?,
               process_pitch_snapshot=?, process_sequence_snapshot=?, process_source_hash=?,
               source_reviewed_at=?, updated_at=?
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (work_element_labels.get(str(entry["work_element_id"]))
             or _text(work.get("operation")), _text(work.get("description")),
             _text(work.get("location")), _text(work.get("station")),
             int(work.get("sequence") or 0), _process_hash(work), timestamp, timestamp,
             entry_id, project_id, scenario_id),
        )
        return {"row_count": 1, "timestamp": timestamp}


def delete_pfmea_records(project_id: str, scenario_id: str, table: str,
                         record_ids: list[str]) -> int:
    allowed = {
        "pfmea_entries": None,
        "pfmea_effects": "pfmea_entry_id",
        "pfmea_causes": "pfmea_entry_id",
        "pfmea_actions": "pfmea_entry_id",
    }
    if table not in allowed:
        raise ValueError("This PFMEA record type cannot be deleted here.")
    ids = list(dict.fromkeys(_text(value) for value in record_ids if _text(value)))
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with _store().connection() as conn:
        _validate_context(conn, project_id, scenario_id)
        found = conn.execute(
            f"SELECT id FROM {table} WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})",
            (project_id, scenario_id, *ids),
        ).fetchall()
        if len(found) != len(ids):
            raise ValueError("One or more selected PFMEA records changed or no longer exist.")
        entry_ids: set[str] = set()
        if table == "pfmea_entries":
            entry_ids = set(ids)
        elif table in {"pfmea_effects", "pfmea_causes"}:
            entry_ids = {str(row[0]) for row in conn.execute(
                f"SELECT DISTINCT pfmea_entry_id FROM {table} WHERE id IN ({placeholders})", tuple(ids)
            ).fetchall()}
        cursor = conn.execute(
            f"DELETE FROM {table} WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})",
            (project_id, scenario_id, *ids),
        )
        timestamp = _store().now_iso()
        for entry_id in entry_ids:
            if conn.execute("SELECT 1 FROM pfmea_entries WHERE id=?", (entry_id,)).fetchone():
                _rebuild_risk_rows(conn, project_id, scenario_id, entry_id, timestamp)
        return int(cursor.rowcount)


def clone_pfmea_scenario(conn: sqlite3.Connection, project_id: str,
                         source_scenario_id: str, new_scenario_id: str,
                         process_id_map: dict[str, str],
                         assignment_id_map: dict[str, str], timestamp: str) -> int:
    entry_map: dict[str, str] = {}
    effect_map: dict[str, str] = {}
    cause_map: dict[str, str] = {}
    cloned = 0
    entries = conn.execute(
        "SELECT * FROM pfmea_entries WHERE project_id=? AND scenario_id=? ORDER BY created_at",
        (project_id, source_scenario_id),
    ).fetchall()
    for raw in entries:
        row = dict(raw)
        old_id = str(row["id"])
        new_work_id = process_id_map.get(str(row["work_element_id"]))
        if not new_work_id:
            continue
        new_id = str(uuid4())
        entry_map[old_id] = new_id
        row.update(id=new_id, scenario_id=new_scenario_id, work_element_id=new_work_id,
                   source_pfmea_entry_id=old_id, created_at=timestamp, updated_at=timestamp)
        columns = list(row)
        conn.execute(f"INSERT INTO pfmea_entries ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                     tuple(row[column] for column in columns))
        cloned += 1
    for table, mapping in (("pfmea_effects", effect_map), ("pfmea_causes", cause_map)):
        for old_entry_id, new_entry_id in entry_map.items():
            for raw in conn.execute(f"SELECT * FROM {table} WHERE pfmea_entry_id=?", (old_entry_id,)).fetchall():
                row = dict(raw)
                old_id, new_id = str(row["id"]), str(uuid4())
                mapping[old_id] = new_id
                row.update(id=new_id, scenario_id=new_scenario_id,
                           pfmea_entry_id=new_entry_id, created_at=timestamp, updated_at=timestamp)
                columns = list(row)
                conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                             tuple(row[column] for column in columns))
    for control_type in CONTROL_TYPES:
        option_table, selection_table, option_column = _control_tables(control_type)
        for raw in conn.execute(
            f"SELECT * FROM {selection_table} WHERE project_id=? AND scenario_id=?",
            (project_id, source_scenario_id),
        ).fetchall():
            row = dict(raw)
            old_entry_id = str(row["pfmea_entry_id"])
            old_cause_id = str(row["pfmea_cause_id"])
            if old_entry_id not in entry_map or old_cause_id not in cause_map:
                continue
            if row["source_type"] == "quality_assignment":
                old_assignment_id = str(row["quality_requirement_assignment_id"])
                new_assignment_id = assignment_id_map.get(old_assignment_id)
                if not new_assignment_id:
                    continue
                row["quality_requirement_assignment_id"] = new_assignment_id
                source_row = conn.execute(
                    "SELECT updated_at FROM quality_requirement_assignments WHERE id=?",
                    (new_assignment_id,),
                ).fetchone()
            else:
                source_row = conn.execute(
                    f"SELECT updated_at FROM {option_table} WHERE id=?",
                    (row[option_column],),
                ).fetchone()
            row.update(
                id=str(uuid4()),
                scenario_id=new_scenario_id,
                pfmea_entry_id=entry_map[old_entry_id],
                pfmea_cause_id=cause_map[old_cause_id],
                source_updated_at_snapshot=(
                    source_row["updated_at"] if source_row else row["source_updated_at_snapshot"]
                ),
                created_at=timestamp,
                updated_at=timestamp,
            )
            columns = list(row)
            conn.execute(
                f"INSERT INTO {selection_table} ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                tuple(row[column] for column in columns),
            )
    for raw in conn.execute(
        "SELECT * FROM pfmea_actions WHERE project_id=? AND scenario_id=?", (project_id, source_scenario_id)
    ).fetchall():
        row = dict(raw)
        if str(row["pfmea_entry_id"]) not in entry_map:
            continue
        old_cause = str(row.get("pfmea_cause_id") or "")
        row.update(id=str(uuid4()), scenario_id=new_scenario_id,
                   pfmea_entry_id=entry_map[str(row["pfmea_entry_id"])],
                   pfmea_cause_id=cause_map.get(old_cause), created_at=timestamp, updated_at=timestamp)
        columns = list(row)
        conn.execute(f"INSERT INTO pfmea_actions ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                     tuple(row[column] for column in columns))
    for entry_id in entry_map.values():
        cloned_entry = _entry(conn, project_id, new_scenario_id, entry_id)
        cloned_work = _work_element(
            conn, project_id, new_scenario_id, str(cloned_entry["work_element_id"])
        )
        conn.execute(
            """UPDATE pfmea_entries SET process_source_hash=?, quality_source_hash=?,
               source_reviewed_at=?, updated_at=? WHERE id=?""",
            (_process_hash(cloned_work), _quality_hash([]), timestamp,
             timestamp, entry_id),
        )
        _rebuild_risk_rows(conn, project_id, new_scenario_id, entry_id, timestamp)
    return cloned
