"""Project-wide reusable PFMEA pattern persistence and resolution."""

from __future__ import annotations

import sqlite3
from uuid import uuid4

import pandas as pd

from utils.pfmea_store import PFMEA_CLASSIFICATIONS


PATTERN_COLUMNS = [
    "id", "project_id", "label", "notes", "potential_failure_mode",
    "class_code", "active", "effect_count", "cause_count", "action_count",
    "control_source_count", "created_at", "updated_at",
]


def _store():
    from utils import store

    return store


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no"}
    return bool(value)


def _sequence(value, default: int) -> int:
    if not _text(value):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("Pattern sequence values must be whole numbers.") from exc


def init_pfmea_pattern_schema(conn: sqlite3.Connection) -> None:
    """Create the approved project-wide PFMEA pattern catalog."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pfmea_patterns (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            potential_failure_mode TEXT NOT NULL,
            class_code TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pfmea_pattern_effects (
            id TEXT PRIMARY KEY,
            pattern_id TEXT NOT NULL REFERENCES pfmea_patterns(id) ON DELETE CASCADE,
            effect_description TEXT NOT NULL,
            sequence INTEGER NOT NULL DEFAULT 10,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pfmea_pattern_causes (
            id TEXT PRIMARY KEY,
            pattern_id TEXT NOT NULL REFERENCES pfmea_patterns(id) ON DELETE CASCADE,
            cause_description TEXT NOT NULL,
            sequence INTEGER NOT NULL DEFAULT 10,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pfmea_pattern_actions (
            id TEXT PRIMARY KEY,
            pattern_id TEXT NOT NULL REFERENCES pfmea_patterns(id) ON DELETE CASCADE,
            pattern_cause_id TEXT REFERENCES pfmea_pattern_causes(id) ON DELETE CASCADE,
            recommended_action TEXT NOT NULL,
            sequence INTEGER NOT NULL DEFAULT 10,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pfmea_pattern_prevention_sources (
            id TEXT PRIMARY KEY,
            pattern_id TEXT NOT NULL REFERENCES pfmea_patterns(id) ON DELETE CASCADE,
            pattern_cause_id TEXT NOT NULL REFERENCES pfmea_pattern_causes(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL CHECK (source_type IN ('quality_requirement', 'manual_option')),
            quality_requirement_id TEXT REFERENCES quality_requirements(id) ON DELETE RESTRICT,
            prevention_option_id TEXT REFERENCES pfmea_prevention_options(id) ON DELETE RESTRICT,
            sequence INTEGER NOT NULL DEFAULT 10,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (
                (source_type='quality_requirement' AND quality_requirement_id IS NOT NULL
                 AND prevention_option_id IS NULL)
                OR
                (source_type='manual_option' AND quality_requirement_id IS NULL
                 AND prevention_option_id IS NOT NULL)
            )
        );
        CREATE TABLE IF NOT EXISTS pfmea_pattern_detection_sources (
            id TEXT PRIMARY KEY,
            pattern_id TEXT NOT NULL REFERENCES pfmea_patterns(id) ON DELETE CASCADE,
            pattern_cause_id TEXT NOT NULL REFERENCES pfmea_pattern_causes(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL CHECK (source_type IN ('quality_requirement', 'manual_option')),
            quality_requirement_id TEXT REFERENCES quality_requirements(id) ON DELETE RESTRICT,
            detection_option_id TEXT REFERENCES pfmea_detection_options(id) ON DELETE RESTRICT,
            sequence INTEGER NOT NULL DEFAULT 10,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (
                (source_type='quality_requirement' AND quality_requirement_id IS NOT NULL
                 AND detection_option_id IS NULL)
                OR
                (source_type='manual_option' AND quality_requirement_id IS NULL
                 AND detection_option_id IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pfmea_pattern_label
            ON pfmea_patterns(project_id, label COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_pfmea_pattern_effects
            ON pfmea_pattern_effects(pattern_id, sequence, id);
        CREATE INDEX IF NOT EXISTS idx_pfmea_pattern_causes
            ON pfmea_pattern_causes(pattern_id, sequence, id);
        CREATE INDEX IF NOT EXISTS idx_pfmea_pattern_actions
            ON pfmea_pattern_actions(pattern_id, pattern_cause_id, sequence, id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pfmea_pattern_prevention_quality
            ON pfmea_pattern_prevention_sources(pattern_cause_id, quality_requirement_id)
            WHERE quality_requirement_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pfmea_pattern_prevention_manual
            ON pfmea_pattern_prevention_sources(pattern_cause_id, prevention_option_id)
            WHERE prevention_option_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pfmea_pattern_detection_quality
            ON pfmea_pattern_detection_sources(pattern_cause_id, quality_requirement_id)
            WHERE quality_requirement_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pfmea_pattern_detection_manual
            ON pfmea_pattern_detection_sources(pattern_cause_id, detection_option_id)
            WHERE detection_option_id IS NOT NULL;
        """
    )


def _validate_project(conn: sqlite3.Connection, project_id: str) -> None:
    if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
        raise ValueError("The active project no longer exists.")


def _validate_scenario(conn: sqlite3.Connection, project_id: str, scenario_id: str) -> None:
    if not conn.execute(
        "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
        (scenario_id, project_id),
    ).fetchone():
        raise ValueError("The active planning scenario no longer exists in this project.")


def pfmea_patterns(project_id: str, *, active_only: bool = False) -> pd.DataFrame:
    active_filter = " AND pattern.active=1" if active_only else ""
    with _store().connection() as conn:
        _validate_project(conn, project_id)
        rows = conn.execute(
            f"""SELECT pattern.*,
                       (SELECT COUNT(*) FROM pfmea_pattern_effects effect
                        WHERE effect.pattern_id=pattern.id) AS effect_count,
                       (SELECT COUNT(*) FROM pfmea_pattern_causes cause
                        WHERE cause.pattern_id=pattern.id) AS cause_count,
                       (SELECT COUNT(*) FROM pfmea_pattern_actions action
                        WHERE action.pattern_id=pattern.id) AS action_count,
                       ((SELECT COUNT(*) FROM pfmea_pattern_prevention_sources prevention
                         WHERE prevention.pattern_id=pattern.id)
                        +
                        (SELECT COUNT(*) FROM pfmea_pattern_detection_sources detection
                         WHERE detection.pattern_id=pattern.id)) AS control_source_count
                FROM pfmea_patterns pattern
                WHERE pattern.project_id=?{active_filter}
                ORDER BY pattern.active DESC, pattern.label COLLATE NOCASE, pattern.id""",
            (project_id,),
        ).fetchall()
    result = pd.DataFrame([dict(row) for row in rows], columns=PATTERN_COLUMNS)
    if not result.empty:
        result["active"] = result["active"].astype(bool)
    return result


def _source_rows(
    conn: sqlite3.Connection, project_id: str, pattern_id: str, control_type: str
) -> list[dict]:
    if control_type == "Prevention":
        table = "pfmea_pattern_prevention_sources"
        option_table = "pfmea_prevention_options"
        option_column = "prevention_option_id"
    else:
        table = "pfmea_pattern_detection_sources"
        option_table = "pfmea_detection_options"
        option_column = "detection_option_id"
    rows = conn.execute(
        f"""SELECT source.*,
                   requirement.description AS quality_description,
                   requirement.requirement_type AS quality_type,
                   requirement.unique_identifier AS quality_identifier,
                   option.label AS manual_label,
                   option.active AS manual_active
            FROM {table} source
            JOIN pfmea_patterns pattern ON pattern.id=source.pattern_id
            LEFT JOIN quality_requirements requirement
              ON requirement.id=source.quality_requirement_id
            LEFT JOIN {option_table} option ON option.id=source.{option_column}
            WHERE source.pattern_id=? AND pattern.project_id=?
            ORDER BY source.pattern_cause_id, source.sequence, source.id""",
        (pattern_id, project_id),
    ).fetchall()
    result: list[dict] = []
    for raw in rows:
        row = dict(raw)
        if row["source_type"] == "quality_requirement":
            row["source_id"] = str(row["quality_requirement_id"])
            row["source_label"] = " — ".join(
                [
                    "Quality",
                    _text(row.get("quality_description")) or "Unnamed requirement",
                    _text(row.get("quality_type")) or "Unspecified type",
                    _text(row.get("quality_identifier")) or "No identifier",
                ]
            )
            row["source_active"] = True
        else:
            row["source_id"] = str(row[option_column])
            row["source_label"] = (
                f"Manual — {_text(row.get('manual_label')) or 'Unavailable option'}"
            )
            row["source_active"] = bool(row.get("manual_active"))
        row["control_type"] = control_type
        result.append(row)
    return result


def pfmea_pattern_graph(project_id: str, pattern_id: str) -> dict:
    with _store().connection() as conn:
        _validate_project(conn, project_id)
        header = conn.execute(
            "SELECT * FROM pfmea_patterns WHERE id=? AND project_id=?",
            (pattern_id, project_id),
        ).fetchone()
        if not header:
            raise ValueError("The selected PFMEA pattern no longer exists in this project.")
        effects = conn.execute(
            "SELECT * FROM pfmea_pattern_effects WHERE pattern_id=? ORDER BY sequence, id",
            (pattern_id,),
        ).fetchall()
        causes = conn.execute(
            "SELECT * FROM pfmea_pattern_causes WHERE pattern_id=? ORDER BY sequence, id",
            (pattern_id,),
        ).fetchall()
        actions = conn.execute(
            "SELECT * FROM pfmea_pattern_actions WHERE pattern_id=? ORDER BY sequence, id",
            (pattern_id,),
        ).fetchall()
        prevention = _source_rows(conn, project_id, pattern_id, "Prevention")
        detection = _source_rows(conn, project_id, pattern_id, "Detection")
    return {
        "pattern": dict(header),
        "effects": pd.DataFrame([dict(row) for row in effects]),
        "causes": pd.DataFrame([dict(row) for row in causes]),
        "actions": pd.DataFrame([dict(row) for row in actions]),
        "prevention_sources": pd.DataFrame(prevention),
        "detection_sources": pd.DataFrame(detection),
    }


def pfmea_pattern_source_candidates(project_id: str, control_type: str) -> pd.DataFrame:
    """Return friendly project-wide Quality definitions and manual choices with state."""
    if control_type == "Prevention":
        option_table = "pfmea_prevention_options"
    elif control_type == "Detection":
        option_table = "pfmea_detection_options"
    else:
        raise ValueError("Control type must be Prevention or Detection.")
    with _store().connection() as conn:
        _validate_project(conn, project_id)
        requirements = conn.execute(
            """SELECT id, description, requirement_type, unique_identifier
               FROM quality_requirements WHERE project_id=?
               ORDER BY description COLLATE NOCASE, unique_identifier COLLATE NOCASE, id""",
            (project_id,),
        ).fetchall()
        options = conn.execute(
            f"""SELECT id, label, active FROM {option_table}
                WHERE project_id=? ORDER BY active DESC, label COLLATE NOCASE, id""",
            (project_id,),
        ).fetchall()
    rows = [
        {
            "source_key": f"quality_requirement:{row['id']}",
            "source_type": "quality_requirement",
            "source_id": str(row["id"]),
            "label": " — ".join(
                [
                    "Quality",
                    _text(row["description"]) or "Unnamed requirement",
                    _text(row["requirement_type"]) or "Unspecified type",
                    _text(row["unique_identifier"]) or "No identifier",
                ]
            ),
            "active": True,
        }
        for row in requirements
    ]
    rows.extend(
        {
            "source_key": f"manual_option:{row['id']}",
            "source_type": "manual_option",
            "source_id": str(row["id"]),
            "label": f"Manual — {row['label']}",
            "active": bool(row["active"]),
        }
        for row in options
    )
    return pd.DataFrame(rows)


def _rows(value) -> list[dict]:
    if isinstance(value, pd.DataFrame):
        return value.to_dict("records")
    return [dict(row) for row in (value or [])]


def _save_child_rows(
    conn: sqlite3.Connection,
    *,
    table: str,
    pattern_id: str,
    rows: list[dict],
    text_column: str,
    timestamp: str,
) -> tuple[list[str], dict[str, str]]:
    existing = {
        str(row["id"]): dict(row)
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE pattern_id=?", (pattern_id,)
        ).fetchall()
    }
    kept: list[str] = []
    supplied_to_saved: dict[str, str] = {}
    for position, row in enumerate(rows, start=1):
        text = _text(row.get(text_column))
        if not text:
            continue
        supplied_id = _text(row.get("id"))
        draft_id = _text(row.get("draft_id"))
        if supplied_id and supplied_id not in existing:
            raise ValueError("A PFMEA pattern detail changed. Refresh and try again.")
        record_id = supplied_id or str(uuid4())
        sequence = _sequence(row.get("sequence"), position * 10)
        if supplied_id:
            conn.execute(
                f"UPDATE {table} SET {text_column}=?, sequence=?, updated_at=? WHERE id=?",
                (text, sequence, timestamp, record_id),
            )
        else:
            conn.execute(
                f"""INSERT INTO {table}
                    (id, pattern_id, {text_column}, sequence, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                (record_id, pattern_id, text, sequence, timestamp, timestamp),
            )
        kept.append(record_id)
        supplied_to_saved[supplied_id or draft_id or record_id] = record_id
    removed = set(existing) - set(kept)
    if removed:
        placeholders = ",".join("?" for _ in removed)
        conn.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", tuple(removed))
    return kept, supplied_to_saved


def _save_actions(
    conn: sqlite3.Connection,
    pattern_id: str,
    rows: list[dict],
    cause_ids: set[str],
    cause_map: dict[str, str],
    timestamp: str,
) -> list[str]:
    existing = {
        str(row["id"]): dict(row)
        for row in conn.execute(
            "SELECT * FROM pfmea_pattern_actions WHERE pattern_id=?", (pattern_id,)
        ).fetchall()
    }
    kept: list[str] = []
    for position, row in enumerate(rows, start=1):
        recommended = _text(row.get("recommended_action"))
        if not recommended:
            continue
        supplied_id = _text(row.get("id"))
        if supplied_id and supplied_id not in existing:
            raise ValueError("A PFMEA pattern action changed. Refresh and try again.")
        cause_id = _text(row.get("pattern_cause_id"))
        cause_id = cause_map.get(cause_id, cause_id)
        if cause_id and cause_id not in cause_ids:
            raise ValueError("A PFMEA pattern action references an unavailable Cause.")
        record_id = supplied_id or str(uuid4())
        sequence = _sequence(row.get("sequence"), position * 10)
        if supplied_id:
            conn.execute(
                """UPDATE pfmea_pattern_actions
                   SET pattern_cause_id=?, recommended_action=?, sequence=?, updated_at=?
                   WHERE id=?""",
                (cause_id or None, recommended, sequence, timestamp, record_id),
            )
        else:
            conn.execute(
                """INSERT INTO pfmea_pattern_actions
                   (id, pattern_id, pattern_cause_id, recommended_action, sequence,
                    created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    record_id, pattern_id, cause_id or None, recommended, sequence,
                    timestamp, timestamp,
                ),
            )
        kept.append(record_id)
    removed = set(existing) - set(kept)
    if removed:
        placeholders = ",".join("?" for _ in removed)
        conn.execute(
            f"DELETE FROM pfmea_pattern_actions WHERE id IN ({placeholders})", tuple(removed)
        )
    return kept


def _save_sources(
    conn: sqlite3.Connection,
    project_id: str,
    pattern_id: str,
    control_type: str,
    rows: list[dict],
    cause_ids: set[str],
    cause_map: dict[str, str],
    timestamp: str,
) -> list[str]:
    if control_type == "Prevention":
        table = "pfmea_pattern_prevention_sources"
        option_table = "pfmea_prevention_options"
        option_column = "prevention_option_id"
    else:
        table = "pfmea_pattern_detection_sources"
        option_table = "pfmea_detection_options"
        option_column = "detection_option_id"
    existing = {
        str(row["id"]): dict(row)
        for row in conn.execute(f"SELECT * FROM {table} WHERE pattern_id=?", (pattern_id,)).fetchall()
    }
    kept: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for position, row in enumerate(rows, start=1):
        supplied_id = _text(row.get("id"))
        if supplied_id and supplied_id not in existing:
            raise ValueError("A PFMEA pattern control source changed. Refresh and try again.")
        cause_id = _text(row.get("pattern_cause_id"))
        cause_id = cause_map.get(cause_id, cause_id)
        if cause_id not in cause_ids:
            raise ValueError("A PFMEA pattern control source must reference a saved Cause.")
        source_type = _text(row.get("source_type"))
        source_id = _text(row.get("source_id"))
        if not source_id:
            source_id = _text(
                row.get("quality_requirement_id")
                if source_type == "quality_requirement"
                else row.get(option_column)
            )
        if source_type not in {"quality_requirement", "manual_option"} or not source_id:
            raise ValueError("Choose a valid PFMEA pattern control source.")
        unique_key = (cause_id, source_type, source_id)
        if unique_key in seen:
            raise ValueError(f"Duplicate {control_type} pattern controls are not allowed.")
        seen.add(unique_key)
        if source_type == "quality_requirement":
            source = conn.execute(
                "SELECT 1 FROM quality_requirements WHERE id=? AND project_id=?",
                (source_id, project_id),
            ).fetchone()
            if not source:
                raise ValueError("A selected Quality requirement is unavailable in this project.")
            quality_id, option_id = source_id, None
        else:
            source = conn.execute(
                f"SELECT active FROM {option_table} WHERE id=? AND project_id=?",
                (source_id, project_id),
            ).fetchone()
            retained_inactive_source = bool(
                supplied_id
                and supplied_id in existing
                and existing[supplied_id].get("source_type") == "manual_option"
                and _text(existing[supplied_id].get(option_column)) == source_id
            )
            if not source or (not bool(source["active"]) and not retained_inactive_source):
                raise ValueError(f"Choose an active {control_type} manual option.")
            quality_id, option_id = None, source_id
        record_id = supplied_id or str(uuid4())
        sequence = _sequence(row.get("sequence"), position * 10)
        values = (
            pattern_id, cause_id, source_type, quality_id, option_id, sequence, timestamp,
            record_id,
        )
        if supplied_id:
            conn.execute(
                f"""UPDATE {table} SET pattern_id=?, pattern_cause_id=?, source_type=?,
                    quality_requirement_id=?, {option_column}=?, sequence=?, updated_at=?
                    WHERE id=?""",
                values,
            )
        else:
            conn.execute(
                f"""INSERT INTO {table}
                    (id, pattern_id, pattern_cause_id, source_type,
                     quality_requirement_id, {option_column}, sequence, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record_id, pattern_id, cause_id, source_type, quality_id, option_id,
                    sequence, timestamp, timestamp,
                ),
            )
        kept.append(record_id)
    removed = set(existing) - set(kept)
    if removed:
        placeholders = ",".join("?" for _ in removed)
        conn.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", tuple(removed))
    return kept


def _save_pattern_graph_conn(
    conn: sqlite3.Connection,
    project_id: str,
    header: dict,
    *,
    effects,
    causes,
    actions,
    prevention_sources,
    detection_sources,
    timestamp: str,
) -> dict:
    _validate_project(conn, project_id)
    pattern_id = _text(header.get("id")) or str(uuid4())
    label = _text(header.get("label"))
    failure_mode = _text(header.get("potential_failure_mode"))
    class_code = _text(header.get("class_code"))
    if not label:
        raise ValueError("PFMEA pattern Label is required.")
    if not failure_mode:
        raise ValueError("PFMEA pattern Potential Failure Mode is required.")
    if class_code not in PFMEA_CLASSIFICATIONS:
        raise ValueError("Choose an approved PFMEA Classification code or leave it blank.")
    existing = conn.execute(
        "SELECT * FROM pfmea_patterns WHERE id=? AND project_id=?", (pattern_id, project_id)
    ).fetchone()
    if _text(header.get("id")) and not existing:
        raise ValueError("The selected PFMEA pattern changed. Refresh and try again.")
    try:
        if existing:
            conn.execute(
                """UPDATE pfmea_patterns SET label=?, notes=?, potential_failure_mode=?,
                   class_code=?, active=?, updated_at=? WHERE id=? AND project_id=?""",
                (
                    label, _text(header.get("notes")), failure_mode, class_code,
                    int(_bool(header.get("active", True))), timestamp, pattern_id, project_id,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO pfmea_patterns
                   (id, project_id, label, notes, potential_failure_mode, class_code,
                    active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    pattern_id, project_id, label, _text(header.get("notes")), failure_mode,
                    class_code, int(_bool(header.get("active", True))), timestamp, timestamp,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("PFMEA pattern labels must be unique within the project.") from exc

    effect_ids, _ = _save_child_rows(
        conn, table="pfmea_pattern_effects", pattern_id=pattern_id,
        rows=_rows(effects), text_column="effect_description", timestamp=timestamp,
    )
    cause_ids, cause_map = _save_child_rows(
        conn, table="pfmea_pattern_causes", pattern_id=pattern_id,
        rows=_rows(causes), text_column="cause_description", timestamp=timestamp,
    )
    _save_actions(
        conn, pattern_id, _rows(actions), set(cause_ids), cause_map, timestamp
    )
    _save_sources(
        conn, project_id, pattern_id, "Prevention", _rows(prevention_sources),
        set(cause_ids), cause_map, timestamp,
    )
    _save_sources(
        conn, project_id, pattern_id, "Detection", _rows(detection_sources),
        set(cause_ids), cause_map, timestamp,
    )
    return {
        "row_count": 1 + len(effect_ids) + len(cause_ids) + len(_rows(actions))
        + len(_rows(prevention_sources)) + len(_rows(detection_sources)),
        "pattern_id": pattern_id,
        "created_ids": [pattern_id] if not existing else [],
        "updated_ids": [pattern_id] if existing else [],
        "timestamp": timestamp,
    }


def save_pfmea_pattern_graph(
    project_id: str,
    header: dict,
    *,
    effects=None,
    causes=None,
    actions=None,
    prevention_sources=None,
    detection_sources=None,
) -> dict:
    timestamp = _store().now_iso()
    with _store().connection() as conn:
        return _save_pattern_graph_conn(
            conn, project_id, header, effects=effects, causes=causes, actions=actions,
            prevention_sources=prevention_sources, detection_sources=detection_sources,
            timestamp=timestamp,
        )


def capture_pfmea_entry_as_pattern(
    project_id: str,
    scenario_id: str,
    entry_id: str,
    *,
    label: str,
    notes: str = "",
) -> dict:
    """Create a reusable pattern from one saved graph, intentionally excluding ratings."""
    timestamp = _store().now_iso()
    omitted: list[str] = []
    with _store().connection() as conn:
        _validate_scenario(conn, project_id, scenario_id)
        entry = conn.execute(
            """SELECT * FROM pfmea_entries
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (entry_id, project_id, scenario_id),
        ).fetchone()
        if not entry:
            raise ValueError("The selected saved PFMEA line no longer exists.")
        effects = [
            dict(row) for row in conn.execute(
                "SELECT * FROM pfmea_effects WHERE pfmea_entry_id=? ORDER BY sequence, id",
                (entry_id,),
            ).fetchall()
        ]
        causes = [
            dict(row) for row in conn.execute(
                "SELECT * FROM pfmea_causes WHERE pfmea_entry_id=? ORDER BY sequence, id",
                (entry_id,),
            ).fetchall()
        ]
        cause_keys = {str(row["id"]): str(uuid4()) for row in causes}
        pattern_causes = [
            {
                "draft_id": cause_keys[str(row["id"])],
                "cause_description": row["cause_description"],
                "sequence": row["sequence"],
            }
            for row in causes
        ]
        actions = [
            dict(row) for row in conn.execute(
                "SELECT * FROM pfmea_actions WHERE pfmea_entry_id=? ORDER BY sequence, id",
                (entry_id,),
            ).fetchall()
        ]
        pattern_actions = [
            {
                "recommended_action": row["recommended_action"],
                "pattern_cause_id": cause_keys.get(_text(row.get("pfmea_cause_id")), ""),
                "sequence": row["sequence"],
            }
            for row in actions
            if _text(row.get("recommended_action"))
        ]
        source_groups: dict[str, list[dict]] = {"Prevention": [], "Detection": []}
        for control_type, table, option_table, option_column in [
            (
                "Prevention", "pfmea_prevention_selections",
                "pfmea_prevention_options", "prevention_option_id",
            ),
            (
                "Detection", "pfmea_detection_selections",
                "pfmea_detection_options", "detection_option_id",
            ),
        ]:
            selections = conn.execute(
                f"SELECT * FROM {table} WHERE pfmea_entry_id=? ORDER BY sequence, id",
                (entry_id,),
            ).fetchall()
            for raw in selections:
                row = dict(raw)
                target_cause = cause_keys.get(str(row["pfmea_cause_id"]))
                if not target_cause:
                    continue
                if row["source_type"] == "quality_assignment":
                    assignment = conn.execute(
                        """SELECT quality_requirement_id FROM quality_requirement_assignments
                           WHERE id=? AND project_id=? AND scenario_id=?""",
                        (
                            row["quality_requirement_assignment_id"], project_id, scenario_id,
                        ),
                    ).fetchone()
                    if not assignment:
                        omitted.append(f"Unavailable {control_type} Quality assignment")
                        continue
                    source_groups[control_type].append(
                        {
                            "pattern_cause_id": target_cause,
                            "source_type": "quality_requirement",
                            "source_id": str(assignment["quality_requirement_id"]),
                            "sequence": row["sequence"],
                        }
                    )
                else:
                    option = conn.execute(
                        f"SELECT label, active FROM {option_table} WHERE id=? AND project_id=?",
                        (row[option_column], project_id),
                    ).fetchone()
                    if not option or not bool(option["active"]):
                        omitted.append(
                            f"{control_type}: {_text(option['label']) if option else 'Unavailable option'}"
                        )
                        continue
                    source_groups[control_type].append(
                        {
                            "pattern_cause_id": target_cause,
                            "source_type": "manual_option",
                            "source_id": str(row[option_column]),
                            "sequence": row["sequence"],
                        }
                    )
        result = _save_pattern_graph_conn(
            conn,
            project_id,
            {
                "label": label,
                "notes": notes,
                "potential_failure_mode": entry["potential_failure_mode"],
                "class_code": entry["class_code"],
                "active": True,
            },
            effects=[
                {
                    "effect_description": row["effect_description"],
                    "sequence": row["sequence"],
                }
                for row in effects
            ],
            causes=pattern_causes,
            actions=pattern_actions,
            prevention_sources=source_groups["Prevention"],
            detection_sources=source_groups["Detection"],
            timestamp=timestamp,
        )
    result["omitted_sources"] = omitted
    return result


def resolve_pfmea_pattern(
    project_id: str,
    scenario_id: str,
    work_element_id: str,
    pattern_id: str,
) -> dict:
    """Resolve project-wide source suggestions for one scenario-specific Process step."""
    with _store().connection() as conn:
        _validate_scenario(conn, project_id, scenario_id)
        if not conn.execute(
            """SELECT 1 FROM work_elements
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (work_element_id, project_id, scenario_id),
        ).fetchone():
            raise ValueError("The selected Process Function is unavailable in this scenario.")
        header = conn.execute(
            "SELECT * FROM pfmea_patterns WHERE id=? AND project_id=? AND active=1",
            (pattern_id, project_id),
        ).fetchone()
        if not header:
            raise ValueError("Choose an active PFMEA pattern from this project.")
        effects = [
            dict(row) for row in conn.execute(
                "SELECT * FROM pfmea_pattern_effects WHERE pattern_id=? ORDER BY sequence, id",
                (pattern_id,),
            ).fetchall()
        ]
        causes = [
            dict(row) for row in conn.execute(
                "SELECT * FROM pfmea_pattern_causes WHERE pattern_id=? ORDER BY sequence, id",
                (pattern_id,),
            ).fetchall()
        ]
        actions = [
            dict(row) for row in conn.execute(
                "SELECT * FROM pfmea_pattern_actions WHERE pattern_id=? ORDER BY sequence, id",
                (pattern_id,),
            ).fetchall()
        ]
        resolved: dict[str, dict[str, list]] = {
            str(cause["id"]): {"Prevention": [], "Detection": []} for cause in causes
        }
        omitted: list[str] = []
        for control_type in ("Prevention", "Detection"):
            for source in _source_rows(conn, project_id, pattern_id, control_type):
                cause_id = str(source["pattern_cause_id"])
                if source["source_type"] == "quality_requirement":
                    assignment = conn.execute(
                        """SELECT * FROM quality_requirement_assignments
                           WHERE project_id=? AND scenario_id=? AND work_element_id=?
                             AND quality_requirement_id=?""",
                        (
                            project_id, scenario_id, work_element_id,
                            source["quality_requirement_id"],
                        ),
                    ).fetchone()
                    if not assignment:
                        omitted.append(
                            f"{control_type}: {source['source_label']} — not published to this Process Function"
                        )
                        continue
                    resolved[cause_id][control_type].append(
                        f"quality:{assignment['id']}"
                    )
                elif not bool(source["source_active"]):
                    omitted.append(
                        f"{control_type}: {source['source_label']} — inactive"
                    )
                else:
                    resolved[cause_id][control_type].append(
                        f"manual:{source['source_id']}"
                    )
    return {
        "pattern": dict(header),
        "effects": effects,
        "causes": causes,
        "actions": actions,
        "controls_by_cause": resolved,
        "omitted_sources": omitted,
    }


def delete_pfmea_patterns(project_id: str, pattern_ids: list[str]) -> dict:
    ids = list(dict.fromkeys(_text(value) for value in pattern_ids if _text(value)))
    timestamp = _store().now_iso()
    if not ids:
        return {"row_count": 0, "deleted_ids": [], "timestamp": timestamp}
    placeholders = ",".join("?" for _ in ids)
    with _store().connection() as conn:
        _validate_project(conn, project_id)
        found = conn.execute(
            f"SELECT id FROM pfmea_patterns WHERE project_id=? AND id IN ({placeholders})",
            (project_id, *ids),
        ).fetchall()
        if {str(row["id"]) for row in found} != set(ids):
            raise ValueError("One or more selected PFMEA patterns changed. Refresh and try again.")
        cursor = conn.execute(
            f"DELETE FROM pfmea_patterns WHERE project_id=? AND id IN ({placeholders})",
            (project_id, *ids),
        )
    return {"row_count": int(cursor.rowcount), "deleted_ids": ids, "timestamp": timestamp}


def pattern_quality_reference_count(project_id: str, requirement_ids: list[str]) -> int:
    ids = list(dict.fromkeys(_text(value) for value in requirement_ids if _text(value)))
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with _store().connection() as conn:
        return int(
            conn.execute(
                f"""SELECT
                    (SELECT COUNT(*) FROM pfmea_pattern_prevention_sources source
                     JOIN pfmea_patterns pattern ON pattern.id=source.pattern_id
                     WHERE pattern.project_id=?
                       AND source.quality_requirement_id IN ({placeholders}))
                    +
                    (SELECT COUNT(*) FROM pfmea_pattern_detection_sources source
                     JOIN pfmea_patterns pattern ON pattern.id=source.pattern_id
                     WHERE pattern.project_id=?
                       AND source.quality_requirement_id IN ({placeholders})) AS count""",
                (project_id, *ids, project_id, *ids),
            ).fetchone()["count"]
        )


def pattern_manual_reference_count(
    project_id: str, control_type: str, option_ids: list[str]
) -> int:
    ids = list(dict.fromkeys(_text(value) for value in option_ids if _text(value)))
    if not ids:
        return 0
    if control_type == "Prevention":
        table, option_column = "pfmea_pattern_prevention_sources", "prevention_option_id"
    elif control_type == "Detection":
        table, option_column = "pfmea_pattern_detection_sources", "detection_option_id"
    else:
        raise ValueError("Control type must be Prevention or Detection.")
    placeholders = ",".join("?" for _ in ids)
    with _store().connection() as conn:
        return int(
            conn.execute(
                f"""SELECT COUNT(*) AS count FROM {table} source
                    JOIN pfmea_patterns pattern ON pattern.id=source.pattern_id
                    WHERE pattern.project_id=? AND source.{option_column} IN ({placeholders})""",
                (project_id, *ids),
            ).fetchone()["count"]
        )
