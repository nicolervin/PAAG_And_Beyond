"""Persistence for the Quality requirements module approved in `DATA_DICTIONARY.md`.

The project-wide repository is deliberately separate from scenario-specific Process
assignments. Assignments retain published snapshots and change only when a saved
repository requirement is explicitly pushed.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd


REQUIREMENT_COLUMNS = [
    "id", "project_id", "requirement_type", "description", "unique_identifier",
    "pass_fail", "target_value", "tolerances", "unit", "created_at", "updated_at",
]

ASSIGNMENT_COLUMNS = [
    "id", "project_id", "scenario_id", "work_element_id", "quality_requirement_id",
    "requirement_type", "description", "unique_identifier", "pass_fail", "target_value",
    "tolerances", "unit", "source_updated_at", "created_at", "updated_at",
]

TORQUE_DETAIL_COLUMNS = [
    "id", "project_id", "quality_requirement_id", "tool_type",
    "tool_orientation", "screw_bit_type", "created_at", "updated_at",
]

TORQUE_TOOL_TYPES = ["Air tool", "Electric clutch tool", "DC tool"]
TORQUE_TOOL_ORIENTATIONS = ["Fixtured", "Pistol", "In-line", "Right angle"]


def init_quality_schema(conn: sqlite3.Connection) -> None:
    """Create the approved Quality tables and their lookup indexes safely."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS quality_requirements (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            requirement_type TEXT NOT NULL,
            description TEXT NOT NULL,
            unique_identifier TEXT NOT NULL COLLATE NOCASE,
            pass_fail INTEGER NOT NULL DEFAULT 0 CHECK (pass_fail IN (0, 1)),
            target_value REAL,
            tolerances TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, unique_identifier)
        );
        CREATE TABLE IF NOT EXISTS quality_requirement_assignments (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            work_element_id TEXT NOT NULL REFERENCES work_elements(id) ON DELETE CASCADE,
            quality_requirement_id TEXT NOT NULL
                REFERENCES quality_requirements(id) ON DELETE RESTRICT,
            requirement_type TEXT NOT NULL,
            description TEXT NOT NULL,
            unique_identifier TEXT NOT NULL,
            pass_fail INTEGER NOT NULL DEFAULT 0 CHECK (pass_fail IN (0, 1)),
            target_value REAL,
            tolerances TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT '',
            source_updated_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(work_element_id, quality_requirement_id)
        );
        CREATE TABLE IF NOT EXISTS quality_requirement_torque_details (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            quality_requirement_id TEXT NOT NULL UNIQUE
                REFERENCES quality_requirements(id) ON DELETE RESTRICT,
            tool_type TEXT NOT NULL
                CHECK (tool_type IN ('Air tool', 'Electric clutch tool', 'DC tool')),
            tool_orientation TEXT NOT NULL
                CHECK (tool_orientation IN ('Fixtured', 'Pistol', 'In-line', 'Right angle')),
            screw_bit_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, quality_requirement_id)
        );
        CREATE INDEX IF NOT EXISTS idx_quality_requirements_project
            ON quality_requirements(project_id, unique_identifier);
        CREATE INDEX IF NOT EXISTS idx_quality_assignments_scenario
            ON quality_requirement_assignments(project_id, scenario_id, work_element_id);
        CREATE INDEX IF NOT EXISTS idx_quality_assignments_requirement
            ON quality_requirement_assignments(project_id, quality_requirement_id);
        CREATE INDEX IF NOT EXISTS idx_quality_torque_details_requirement
            ON quality_requirement_torque_details(project_id, quality_requirement_id);
        """
    )


def _store_module():
    # Import lazily so utils.store can initialize this module's schema without a
    # circular import during module loading.
    from utils import store

    return store


def _clean_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _optional_number(value, label: str) -> float | None:
    if value is None or _clean_text(value) == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number.")
    return number


def _pass_fail_value(value) -> int:
    if value is None:
        return 0
    try:
        if pd.isna(value):
            return 0
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and value in {0, 1}:
        return int(value)
    normalized = str(value).strip().casefold()
    if normalized in {"", "0", "false", "no", "n"}:
        return 0
    if normalized in {"1", "true", "yes", "y", "pass/fail"}:
        return 1
    raise ValueError("Pass/fail must be a yes/no value.")


def _validated_requirement(values: dict) -> dict:
    requirement_type = _clean_text(values.get("requirement_type"))
    description = _clean_text(values.get("description"))
    unique_identifier = _clean_text(values.get("unique_identifier"))
    if not requirement_type:
        raise ValueError("Quality requirement Type is required.")
    if not description:
        raise ValueError("Quality requirement Description is required.")
    if not unique_identifier:
        raise ValueError("Quality requirement Unique identifier is required.")
    unit = _clean_text(values.get("unit"))
    if "dimension" in requirement_type.casefold() and unit.casefold() not in {
        "", "in", "inch", "inches",
    }:
        raise ValueError("Linear dimensional Quality requirements must use inches.")
    return {
        "requirement_type": requirement_type,
        "description": description,
        "unique_identifier": unique_identifier,
        "pass_fail": _pass_fail_value(values.get("pass_fail")),
        "target_value": _optional_number(values.get("target_value"), "Target value"),
        "tolerances": _clean_text(values.get("tolerances")),
        "unit": unit,
    }


def _validated_torque_detail(values: dict) -> dict:
    tool_type = _clean_text(values.get("tool_type"))
    tool_orientation = _clean_text(values.get("tool_orientation"))
    screw_bit_type = _clean_text(values.get("screw_bit_type"))
    if tool_type not in TORQUE_TOOL_TYPES:
        raise ValueError("Tool type must use one of the approved choices.")
    if tool_orientation not in TORQUE_TOOL_ORIENTATIONS:
        raise ValueError("Tool orientation must use one of the approved choices.")
    if not screw_bit_type:
        raise ValueError("Screw bit type is required.")
    return {
        "tool_type": tool_type,
        "tool_orientation": tool_orientation,
        "screw_bit_type": screw_bit_type,
    }


def _validate_torque_detail_parent_type(
    conn: sqlite3.Connection,
    project_id: str,
    quality_requirement_id: str,
    requirement_type: str,
) -> None:
    if requirement_type.casefold() == "torque":
        return
    has_detail = conn.execute(
        """SELECT 1 FROM quality_requirement_torque_details
           WHERE project_id=? AND quality_requirement_id=?""",
        (project_id, quality_requirement_id),
    ).fetchone()
    if has_detail:
        raise ValueError(
            "Delete the linked Torque tool details before changing this requirement's Type."
        )


def _normalized_ids(record_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(
        str(record_id).strip() for record_id in record_ids if str(record_id).strip()
    ))


def quality_requirements(project_id: str) -> pd.DataFrame:
    """Return project-wide repository definitions with their assignment counts."""
    store = _store_module()
    rows = store.query(
        """SELECT requirement.*, COUNT(assignment.id) AS assignment_count,
                  SUM(CASE WHEN assignment.id IS NOT NULL AND NOT (
                                   assignment.requirement_type IS requirement.requirement_type
                               AND assignment.description IS requirement.description
                               AND assignment.unique_identifier IS requirement.unique_identifier
                               AND assignment.pass_fail IS requirement.pass_fail
                               AND assignment.target_value IS requirement.target_value
                               AND assignment.tolerances IS requirement.tolerances
                               AND assignment.unit IS requirement.unit
                           ) THEN 1 ELSE 0 END) AS pending_assignment_count,
                  (SELECT COUNT(*) FROM quality_requirement_torque_details detail
                   WHERE detail.project_id=requirement.project_id
                     AND detail.quality_requirement_id=requirement.id
                  ) AS torque_detail_count
           FROM quality_requirements requirement
           LEFT JOIN quality_requirement_assignments assignment
             ON assignment.quality_requirement_id=requirement.id
            AND assignment.project_id=requirement.project_id
           WHERE requirement.project_id=?
           GROUP BY requirement.id
           ORDER BY requirement.unique_identifier COLLATE NOCASE, requirement.id""",
        (project_id,),
    )
    return pd.DataFrame(
        rows,
        columns=[
            *REQUIREMENT_COLUMNS,
            "assignment_count",
            "pending_assignment_count",
            "torque_detail_count",
        ],
    )


def save_quality_requirement(
    project_id: str, values: dict, requirement_id: str | None = None
) -> str:
    """Create or update a repository definition without changing assignments."""
    store = _store_module()
    validated = _validated_requirement(values)
    supplied_id = _clean_text(requirement_id) or _clean_text(values.get("id"))
    requirement_id = supplied_id or str(uuid4())
    timestamp = store.now_iso()
    try:
        with store.connection() as conn:
            if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise ValueError("The active project no longer exists.")
            existing = conn.execute(
                "SELECT 1 FROM quality_requirements WHERE id=? AND project_id=?",
                (requirement_id, project_id),
            ).fetchone()
            if supplied_id and not existing:
                raise ValueError("That Quality requirement no longer exists.")
            if existing:
                _validate_torque_detail_parent_type(
                    conn,
                    project_id,
                    requirement_id,
                    validated["requirement_type"],
                )
                conn.execute(
                    """UPDATE quality_requirements
                       SET requirement_type=?, description=?, unique_identifier=?,
                           pass_fail=?, target_value=?, tolerances=?, unit=?, updated_at=?
                       WHERE id=? AND project_id=?""",
                    (*validated.values(), timestamp, requirement_id, project_id),
                )
            else:
                conn.execute(
                    """INSERT INTO quality_requirements
                       (id, project_id, requirement_type, description, unique_identifier,
                        pass_fail, target_value, tolerances, unit, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (requirement_id, project_id, *validated.values(), timestamp, timestamp),
                )
    except sqlite3.IntegrityError as exc:
        raise ValueError(
            "Quality requirement Unique identifiers must be unique within the project."
        ) from exc
    return requirement_id


def save_quality_requirement_rows(
    project_id: str, edited: pd.DataFrame
) -> dict[str, object]:
    """Atomically create and update a complete repository table submission."""
    required_columns = {
        "id",
        "requirement_type",
        "description",
        "unique_identifier",
        "pass_fail",
        "target_value",
        "tolerances",
        "unit",
    }
    if not required_columns.issubset(edited.columns):
        raise ValueError("The Quality requirements table is missing required columns.")

    prepared: list[dict] = []
    identifiers: set[str] = set()
    supplied_ids: set[str] = set()
    for record in edited.to_dict("records"):
        validated = _validated_requirement(record)
        identifier_key = validated["unique_identifier"].casefold()
        if identifier_key in identifiers:
            raise ValueError(
                "Quality requirement Unique identifiers must be unique within the project."
            )
        identifiers.add(identifier_key)
        requirement_id = _clean_text(record.get("id"))
        if requirement_id:
            if requirement_id in supplied_ids:
                raise ValueError("The Quality requirements table contains a duplicate record.")
            supplied_ids.add(requirement_id)
        prepared.append({"id": requirement_id, **validated})

    store = _store_module()
    timestamp = store.now_iso()
    created_ids: list[str] = []
    updated_ids: list[str] = []
    try:
        with store.connection() as conn:
            if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise ValueError("The active project no longer exists.")
            existing_rows = conn.execute(
                "SELECT * FROM quality_requirements WHERE project_id=?", (project_id,)
            ).fetchall()
            existing_by_id = {str(row["id"]): dict(row) for row in existing_rows}
            unknown_ids = supplied_ids - set(existing_by_id)
            if unknown_ids:
                raise ValueError(
                    "One or more Quality requirements no longer exist. Refresh and try again."
                )
            missing_ids = set(existing_by_id) - supplied_ids
            if missing_ids:
                raise ValueError(
                    "Use the confirmed deletion workflow to remove Quality requirements."
                )

            fields = [
                "requirement_type",
                "description",
                "unique_identifier",
                "pass_fail",
                "target_value",
                "tolerances",
                "unit",
            ]
            for row in prepared:
                requirement_id = row["id"]
                if not requirement_id:
                    requirement_id = str(uuid4())
                    conn.execute(
                        """INSERT INTO quality_requirements
                           (id, project_id, requirement_type, description, unique_identifier,
                            pass_fail, target_value, tolerances, unit, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            requirement_id,
                            project_id,
                            *(row[field] for field in fields),
                            timestamp,
                            timestamp,
                        ),
                    )
                    created_ids.append(requirement_id)
                    continue

                existing = existing_by_id[requirement_id]
                if all(existing[field] == row[field] for field in fields):
                    continue
                _validate_torque_detail_parent_type(
                    conn,
                    project_id,
                    requirement_id,
                    row["requirement_type"],
                )
                conn.execute(
                    """UPDATE quality_requirements
                       SET requirement_type=?, description=?, unique_identifier=?,
                           pass_fail=?, target_value=?, tolerances=?, unit=?, updated_at=?
                       WHERE id=? AND project_id=?""",
                    (
                        *(row[field] for field in fields),
                        timestamp,
                        requirement_id,
                        project_id,
                    ),
                )
                updated_ids.append(requirement_id)
    except sqlite3.IntegrityError as exc:
        raise ValueError(
            "Quality requirement Unique identifiers must be unique within the project."
        ) from exc
    return {
        "created_ids": created_ids,
        "updated_ids": updated_ids,
        "row_count": len(created_ids) + len(updated_ids),
        "timestamp": timestamp,
    }


def bulk_update_quality_requirement_pass_fail(
    project_id: str, requirement_ids: list[str], pass_fail: bool
) -> dict[str, object]:
    """Atomically apply one Pass/fail setting to validated repository definitions."""
    store = _store_module()
    normalized_ids = _normalized_ids(requirement_ids)
    if not normalized_ids:
        return {"row_count": 0, "updated_ids": [], "timestamp": store.now_iso()}
    placeholders = ", ".join("?" for _ in normalized_ids)
    pass_fail_value = int(bool(pass_fail))
    timestamp = store.now_iso()
    with store.connection() as conn:
        rows = conn.execute(
            f"""SELECT id, pass_fail FROM quality_requirements
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *normalized_ids),
        ).fetchall()
        if {str(row["id"]) for row in rows} != set(normalized_ids):
            raise ValueError(
                "One or more selected Quality requirements no longer exist. "
                "Refresh and try again."
            )
        updated_ids = [
            str(row["id"])
            for row in rows
            if int(row["pass_fail"]) != pass_fail_value
        ]
        if updated_ids:
            updated_placeholders = ", ".join("?" for _ in updated_ids)
            conn.execute(
                f"""UPDATE quality_requirements SET pass_fail=?, updated_at=?
                    WHERE project_id=? AND id IN ({updated_placeholders})""",
                (pass_fail_value, timestamp, project_id, *updated_ids),
            )
    return {
        "row_count": len(updated_ids),
        "updated_ids": updated_ids,
        "timestamp": timestamp,
    }


def delete_quality_requirements(project_id: str, requirement_ids: list[str]) -> int:
    """Delete unassigned repository definitions after validating the full request."""
    store = _store_module()
    normalized_ids = _normalized_ids(requirement_ids)
    if not normalized_ids:
        return 0
    placeholders = ", ".join("?" for _ in normalized_ids)
    with store.connection() as conn:
        rows = conn.execute(
            f"""SELECT requirement.id, COUNT(assignment.id) AS assignment_count,
                       (SELECT COUNT(*) FROM quality_requirement_torque_details detail
                        WHERE detail.project_id=requirement.project_id
                          AND detail.quality_requirement_id=requirement.id
                       ) AS torque_detail_count
                FROM quality_requirements requirement
                LEFT JOIN quality_requirement_assignments assignment
                  ON assignment.quality_requirement_id=requirement.id
                WHERE requirement.project_id=? AND requirement.id IN ({placeholders})
                GROUP BY requirement.id""",
            (project_id, *normalized_ids),
        ).fetchall()
        if {str(row["id"]) for row in rows} != set(normalized_ids):
            raise ValueError(
                "One or more selected Quality requirements no longer exist. Refresh and try again."
            )
        linked_count = sum(int(row["assignment_count"]) for row in rows)
        torque_detail_count = sum(int(row["torque_detail_count"]) for row in rows)
        if linked_count:
            raise ValueError(
                f"Remove {linked_count} linked Process requirement assignment(s) before deleting."
            )
        if torque_detail_count:
            raise ValueError(
                f"Delete {torque_detail_count} linked Torque tool detail record(s) before deleting."
            )
        cursor = conn.execute(
            f"DELETE FROM quality_requirements WHERE project_id=? AND id IN ({placeholders})",
            (project_id, *normalized_ids),
        )
        return int(cursor.rowcount)


def quality_requirement_torque_details(
    project_id: str, quality_requirement_id: str | None = None
) -> pd.DataFrame:
    """Return project-owned Torque tool details, optionally for one requirement."""
    store = _store_module()
    requirement_filter = " AND detail.quality_requirement_id=?" if quality_requirement_id else ""
    params = (
        (project_id, quality_requirement_id)
        if quality_requirement_id else (project_id,)
    )
    rows = store.query(
        f"""SELECT detail.*
            FROM quality_requirement_torque_details detail
            JOIN quality_requirements requirement
              ON requirement.id=detail.quality_requirement_id
             AND requirement.project_id=detail.project_id
            WHERE detail.project_id=?
              AND LOWER(TRIM(requirement.requirement_type))='torque'
              {requirement_filter}
            ORDER BY requirement.unique_identifier COLLATE NOCASE, detail.id""",
        params,
    )
    return pd.DataFrame(rows, columns=TORQUE_DETAIL_COLUMNS)


def torque_screw_bit_types(project_id: str) -> list[str]:
    """Return distinct saved Screw bit type values for project suggestions."""
    store = _store_module()
    rows = store.query(
        """SELECT MIN(screw_bit_type) AS screw_bit_type
           FROM quality_requirement_torque_details
           WHERE project_id=? AND TRIM(screw_bit_type)<>''
           GROUP BY LOWER(TRIM(screw_bit_type))
           ORDER BY screw_bit_type COLLATE NOCASE""",
        (project_id,),
    )
    return [str(row["screw_bit_type"]) for row in rows]


def save_quality_requirement_torque_detail(
    project_id: str,
    quality_requirement_id: str,
    values: dict,
) -> dict[str, object]:
    """Create or update the one project-wide tool-detail row for a Torque requirement."""
    store = _store_module()
    validated = _validated_torque_detail(values)
    supplied_id = _clean_text(values.get("id"))
    timestamp = store.now_iso()
    with store.connection() as conn:
        requirement = conn.execute(
            """SELECT requirement_type FROM quality_requirements
               WHERE id=? AND project_id=?""",
            (quality_requirement_id, project_id),
        ).fetchone()
        if not requirement:
            raise ValueError("That Quality requirement no longer exists in this project.")
        if str(requirement["requirement_type"]).strip().casefold() != "torque":
            raise ValueError("Torque tool details can only be saved for a Torque requirement.")
        existing = conn.execute(
            """SELECT * FROM quality_requirement_torque_details
               WHERE project_id=? AND quality_requirement_id=?""",
            (project_id, quality_requirement_id),
        ).fetchone()
        if supplied_id and (not existing or str(existing["id"]) != supplied_id):
            raise ValueError("That Torque tool detail record no longer exists.")
        if existing:
            changed = any(
                existing[field] != validated[field]
                for field in ["tool_type", "tool_orientation", "screw_bit_type"]
            )
            if changed:
                conn.execute(
                    """UPDATE quality_requirement_torque_details
                       SET tool_type=?, tool_orientation=?, screw_bit_type=?, updated_at=?
                       WHERE id=? AND project_id=? AND quality_requirement_id=?""",
                    (
                        *validated.values(), timestamp, existing["id"], project_id,
                        quality_requirement_id,
                    ),
                )
            detail_id = str(existing["id"])
            action = "updated" if changed else "unchanged"
        else:
            detail_id = str(uuid4())
            conn.execute(
                """INSERT INTO quality_requirement_torque_details
                   (id, project_id, quality_requirement_id, tool_type,
                    tool_orientation, screw_bit_type, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    detail_id, project_id, quality_requirement_id,
                    *validated.values(), timestamp, timestamp,
                ),
            )
            action = "created"
    return {
        "id": detail_id,
        "action": action,
        "row_count": int(action != "unchanged"),
        "timestamp": timestamp,
    }


def delete_quality_requirement_torque_details(
    project_id: str,
    quality_requirement_id: str,
    detail_ids: list[str],
) -> int:
    """Delete validated tool details while preserving their Torque requirement."""
    store = _store_module()
    normalized_ids = _normalized_ids(detail_ids)
    if not normalized_ids:
        return 0
    placeholders = ", ".join("?" for _ in normalized_ids)
    with store.connection() as conn:
        rows = conn.execute(
            f"""SELECT id FROM quality_requirement_torque_details
                WHERE project_id=? AND quality_requirement_id=?
                  AND id IN ({placeholders})""",
            (project_id, quality_requirement_id, *normalized_ids),
        ).fetchall()
        if {str(row["id"]) for row in rows} != set(normalized_ids):
            raise ValueError(
                "One or more selected Torque tool details no longer exist. Refresh and try again."
            )
        cursor = conn.execute(
            f"""DELETE FROM quality_requirement_torque_details
                WHERE project_id=? AND quality_requirement_id=?
                  AND id IN ({placeholders})""",
            (project_id, quality_requirement_id, *normalized_ids),
        )
        return int(cursor.rowcount)


def quality_requirement_assignments(
    project_id: str, scenario_id: str, work_element_id: str | None = None
) -> pd.DataFrame:
    """Return published assignment snapshots for one scenario or Process step."""
    store = _store_module()
    work_filter = " AND assignment.work_element_id=?" if work_element_id else ""
    params = (
        (project_id, scenario_id, work_element_id)
        if work_element_id else (project_id, scenario_id)
    )
    rows = store.query(
        f"""SELECT assignment.*, element.sequence AS process_sequence,
                   element.station AS pitch, element.operation AS work_element,
                   CASE WHEN assignment.requirement_type IS requirement.requirement_type
                              AND assignment.description IS requirement.description
                              AND assignment.unique_identifier IS requirement.unique_identifier
                              AND assignment.pass_fail IS requirement.pass_fail
                              AND assignment.target_value IS requirement.target_value
                              AND assignment.tolerances IS requirement.tolerances
                              AND assignment.unit IS requirement.unit
                        THEN 0 ELSE 1 END AS repository_update_pending
            FROM quality_requirement_assignments assignment
            JOIN work_elements element
              ON element.id=assignment.work_element_id
             AND element.project_id=assignment.project_id
             AND element.scenario_id=assignment.scenario_id
            JOIN quality_requirements requirement
              ON requirement.id=assignment.quality_requirement_id
             AND requirement.project_id=assignment.project_id
            WHERE assignment.project_id=? AND assignment.scenario_id=?{work_filter}
            ORDER BY element.sequence, assignment.unique_identifier COLLATE NOCASE,
                     assignment.id""",
        params,
    )
    return pd.DataFrame(rows, columns=[
        *ASSIGNMENT_COLUMNS, "process_sequence", "pitch", "work_element",
        "repository_update_pending",
    ])


def quality_process_steps(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Return active-scenario Process steps with the labels shown in Process at a Glance."""
    store = _store_module()
    rows = store.query(
        """SELECT element.id, element.sequence, element.station AS pitch,
                  COALESCE((
                      SELECT pitch.pitch_name
                      FROM yamazumi_elements yamazumi
                      JOIN yamazumi_areas area ON area.id=yamazumi.area_id
                      LEFT JOIN yamazumi_pitches pitch ON pitch.id=yamazumi.pitch_id
                      WHERE yamazumi.project_id=element.project_id
                        AND area.scenario_id=element.scenario_id
                        AND yamazumi.process_element_id=element.id
                      ORDER BY area.name, pitch.sequence, yamazumi.sequence
                      LIMIT 1
                  ), '') AS pitch_name,
                  COALESCE(NULLIF((
                      SELECT yamazumi.description
                      FROM yamazumi_elements yamazumi
                      JOIN yamazumi_areas area ON area.id=yamazumi.area_id
                      LEFT JOIN yamazumi_pitches pitch ON pitch.id=yamazumi.pitch_id
                      WHERE yamazumi.project_id=element.project_id
                        AND area.scenario_id=element.scenario_id
                        AND yamazumi.process_element_id=element.id
                      ORDER BY area.name, pitch.sequence, yamazumi.sequence
                      LIMIT 1
                  ), ''), element.operation) AS work_element,
                  element.status
           FROM work_elements element
           JOIN planning_scenarios scenario
             ON scenario.id=element.scenario_id
            AND scenario.project_id=element.project_id
           WHERE element.project_id=? AND element.scenario_id=?
           ORDER BY element.sequence, element.operation, element.id""",
        (project_id, scenario_id),
    )
    return pd.DataFrame(
        rows,
        columns=["id", "sequence", "pitch", "pitch_name", "work_element", "status"],
    )


def quality_requirement_links(
    project_id: str, quality_requirement_id: str | None = None
) -> pd.DataFrame:
    """Return published Quality assignments and their current Process-step labels.

    Omitting ``quality_requirement_id`` returns every assignment in the project.
    Supplying it retains the narrower result used by the separate unlink workflow.
    """
    store = _store_module()
    requirement_filter = (
        " AND assignment.quality_requirement_id=?" if quality_requirement_id else ""
    )
    params = (
        (project_id, quality_requirement_id)
        if quality_requirement_id else (project_id,)
    )
    rows = store.query(
        f"""SELECT assignment.id AS assignment_id,
                  assignment.quality_requirement_id, assignment.scenario_id,
                  assignment.work_element_id, scenario.revision_label AS scenario_revision,
                  scenario.name AS scenario_name, element.sequence,
                  element.station AS pitch,
                  COALESCE((
                      SELECT pitch.pitch_name
                      FROM yamazumi_elements yamazumi
                      JOIN yamazumi_areas area ON area.id=yamazumi.area_id
                      LEFT JOIN yamazumi_pitches pitch ON pitch.id=yamazumi.pitch_id
                      WHERE yamazumi.project_id=element.project_id
                        AND area.scenario_id=element.scenario_id
                        AND yamazumi.process_element_id=element.id
                      ORDER BY area.name, pitch.sequence, yamazumi.sequence
                      LIMIT 1
                  ), '') AS pitch_name,
                  COALESCE(NULLIF((
                      SELECT yamazumi.description
                      FROM yamazumi_elements yamazumi
                      JOIN yamazumi_areas area ON area.id=yamazumi.area_id
                      LEFT JOIN yamazumi_pitches pitch ON pitch.id=yamazumi.pitch_id
                      WHERE yamazumi.project_id=element.project_id
                        AND area.scenario_id=element.scenario_id
                        AND yamazumi.process_element_id=element.id
                      ORDER BY area.name, pitch.sequence, yamazumi.sequence
                      LIMIT 1
                  ), ''), element.operation) AS work_element,
                  element.status, assignment.requirement_type,
                  assignment.description, assignment.unique_identifier,
                  assignment.pass_fail, assignment.target_value,
                  assignment.tolerances, assignment.unit,
                  CASE WHEN assignment.requirement_type IS requirement.requirement_type
                             AND assignment.description IS requirement.description
                             AND assignment.unique_identifier IS requirement.unique_identifier
                             AND assignment.pass_fail IS requirement.pass_fail
                             AND assignment.target_value IS requirement.target_value
                             AND assignment.tolerances IS requirement.tolerances
                             AND assignment.unit IS requirement.unit
                       THEN 0 ELSE 1 END AS repository_update_pending
           FROM quality_requirement_assignments assignment
           JOIN quality_requirements requirement
             ON requirement.id=assignment.quality_requirement_id
            AND requirement.project_id=assignment.project_id
           JOIN work_elements element
             ON element.id=assignment.work_element_id
            AND element.project_id=assignment.project_id
            AND element.scenario_id=assignment.scenario_id
           JOIN planning_scenarios scenario
             ON scenario.id=assignment.scenario_id
            AND scenario.project_id=assignment.project_id
           WHERE assignment.project_id=?{requirement_filter}
           ORDER BY scenario.revision_sequence DESC, scenario.name,
                    element.sequence, assignment.unique_identifier COLLATE NOCASE,
                    assignment.id""",
        params,
    )
    return pd.DataFrame(
        rows,
        columns=[
            "assignment_id", "quality_requirement_id", "scenario_id",
            "work_element_id", "scenario_revision", "scenario_name", "sequence",
            "pitch", "pitch_name", "work_element", "status", "requirement_type",
            "description", "unique_identifier", "pass_fail", "target_value",
            "tolerances", "unit", "repository_update_pending",
        ],
    )


def assign_quality_requirement(
    project_id: str,
    scenario_id: str,
    work_element_id: str,
    quality_requirement_id: str,
) -> str:
    """Attach a saved repository definition to a Process step as a snapshot."""
    store = _store_module()
    assignment_id = str(uuid4())
    timestamp = store.now_iso()
    try:
        with store.connection() as conn:
            if not conn.execute(
                "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
                (scenario_id, project_id),
            ).fetchone():
                raise ValueError("The active planning scenario no longer exists.")
            if not conn.execute(
                """SELECT 1 FROM work_elements
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (work_element_id, project_id, scenario_id),
            ).fetchone():
                raise ValueError("That Process at a Glance step no longer exists in this scenario.")
            requirement = conn.execute(
                "SELECT * FROM quality_requirements WHERE id=? AND project_id=?",
                (quality_requirement_id, project_id),
            ).fetchone()
            if not requirement:
                raise ValueError("That Quality requirement no longer exists in this project.")
            conn.execute(
                """INSERT INTO quality_requirement_assignments
                   (id, project_id, scenario_id, work_element_id, quality_requirement_id,
                    requirement_type, description, unique_identifier, pass_fail,
                    target_value, tolerances, unit, source_updated_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    assignment_id, project_id, scenario_id, work_element_id,
                    quality_requirement_id, requirement["requirement_type"],
                    requirement["description"], requirement["unique_identifier"],
                    requirement["pass_fail"], requirement["target_value"],
                    requirement["tolerances"], requirement["unit"],
                    requirement["updated_at"], timestamp, timestamp,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(
            "That Quality requirement is already attached to this Process step."
        ) from exc
    return assignment_id


def quality_requirement_assignment(
    project_id: str, assignment_id: str
) -> dict[str, object]:
    """Return one assignment by its stable ID within the selected project."""
    store = _store_module()
    rows = store.query(
        """SELECT * FROM quality_requirement_assignments
           WHERE project_id=? AND id=?""",
        (project_id, assignment_id),
    )
    if not rows:
        raise ValueError(
            "That Quality requirement assignment no longer exists. Refresh and try again."
        )
    return dict(rows[0])


def delete_quality_requirement_assignments(
    project_id: str, scenario_id: str, assignment_ids: list[str]
) -> int:
    """Delete a validated set of scenario-owned Process requirement assignments."""
    store = _store_module()
    normalized_ids = _normalized_ids(assignment_ids)
    if not normalized_ids:
        return 0
    placeholders = ", ".join("?" for _ in normalized_ids)
    with store.connection() as conn:
        rows = conn.execute(
            f"""SELECT id FROM quality_requirement_assignments
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *normalized_ids),
        ).fetchall()
        if {str(row["id"]) for row in rows} != set(normalized_ids):
            raise ValueError(
                "One or more selected Quality requirement assignments no longer exist. "
                "Refresh and try again."
            )
        timestamp = store.now_iso()
        for table, detection in (
            ("pfmea_prevention_selections", False),
            ("pfmea_detection_selections", True),
        ):
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                continue
            affected = conn.execute(
                f"""SELECT DISTINCT pfmea_cause_id FROM {table}
                    WHERE project_id=? AND scenario_id=?
                      AND quality_requirement_assignment_id IN ({placeholders})""",
                (project_id, scenario_id, *normalized_ids),
            ).fetchall()
            for affected_row in affected:
                conn.execute(
                    """UPDATE pfmea_causes SET control_source_review_required=1,
                       detection_review_required=CASE WHEN ? THEN 1 ELSE detection_review_required END,
                       updated_at=? WHERE id=? AND project_id=? AND scenario_id=?""",
                    (1 if detection else 0, timestamp, affected_row["pfmea_cause_id"], project_id, scenario_id),
                )
        cursor = conn.execute(
            f"""DELETE FROM quality_requirement_assignments
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *normalized_ids),
        )
        return int(cursor.rowcount)


def quality_assignment_pfmea_impact(
    project_id: str, scenario_id: str, assignment_ids: list[str]
) -> dict:
    """Describe structured PFMEA selections removed by a confirmed Quality unlink."""
    normalized_ids = _normalized_ids(assignment_ids)
    if not normalized_ids:
        return {"selection_count": 0, "cause_count": 0}
    placeholders = ", ".join("?" for _ in normalized_ids)
    selections: list[tuple[str, str]] = []
    with _store_module().connection() as conn:
        for table, control_type in (
            ("pfmea_prevention_selections", "Prevention"),
            ("pfmea_detection_selections", "Detection"),
        ):
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                continue
            rows = conn.execute(
                f"""SELECT pfmea_cause_id FROM {table}
                    WHERE project_id=? AND scenario_id=?
                      AND quality_requirement_assignment_id IN ({placeholders})""",
                (project_id, scenario_id, *normalized_ids),
            ).fetchall()
            selections.extend((control_type, str(row["pfmea_cause_id"])) for row in rows)
    return {
        "selection_count": len(selections),
        "cause_count": len({cause_id for _, cause_id in selections}),
        "prevention_count": sum(control_type == "Prevention" for control_type, _ in selections),
        "detection_count": sum(control_type == "Detection" for control_type, _ in selections),
    }


def push_quality_requirements(project_id: str, requirement_ids: list[str]) -> int:
    """Atomically publish saved definitions to all of their linked snapshots."""
    store = _store_module()
    normalized_ids = _normalized_ids(requirement_ids)
    if not normalized_ids:
        return 0
    placeholders = ", ".join("?" for _ in normalized_ids)
    timestamp = datetime.now(timezone.utc).isoformat()
    with store.connection() as conn:
        requirements = conn.execute(
            f"""SELECT * FROM quality_requirements
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *normalized_ids),
        ).fetchall()
        if {str(row["id"]) for row in requirements} != set(normalized_ids):
            raise ValueError(
                "One or more selected Quality requirements no longer exist. Refresh and try again."
            )
        updated_count = 0
        for requirement in requirements:
            assignment_ids = [
                str(row["id"])
                for row in conn.execute(
                    "SELECT id FROM quality_requirement_assignments "
                    "WHERE project_id=? AND quality_requirement_id=?",
                    (project_id, requirement["id"]),
                ).fetchall()
            ]
            cursor = conn.execute(
                """UPDATE quality_requirement_assignments
                   SET requirement_type=?, description=?, unique_identifier=?, pass_fail=?,
                       target_value=?, tolerances=?, unit=?, source_updated_at=?, updated_at=?
                   WHERE project_id=? AND quality_requirement_id=?""",
                (
                    requirement["requirement_type"], requirement["description"],
                    requirement["unique_identifier"], requirement["pass_fail"],
                    requirement["target_value"], requirement["tolerances"],
                    requirement["unit"], requirement["updated_at"], timestamp,
                    project_id, requirement["id"],
                ),
            )
            updated_count += int(cursor.rowcount)
            if assignment_ids:
                assignment_placeholders = ",".join("?" for _ in assignment_ids)
                for selection_table, detection in (
                    ("pfmea_prevention_selections", False),
                    ("pfmea_detection_selections", True),
                ):
                    if not conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (selection_table,),
                    ).fetchone():
                        continue
                    affected = conn.execute(
                        f"SELECT DISTINCT pfmea_cause_id FROM {selection_table} "
                        f"WHERE quality_requirement_assignment_id IN ({assignment_placeholders})",
                        tuple(assignment_ids),
                    ).fetchall()
                    for affected_row in affected:
                        conn.execute(
                            """UPDATE pfmea_causes SET control_source_review_required=1,
                               detection_review_required=CASE WHEN ? THEN 1 ELSE detection_review_required END,
                               updated_at=? WHERE id=? AND project_id=?""",
                            (1 if detection else 0, timestamp, affected_row["pfmea_cause_id"], project_id),
                        )
        return updated_count


def clone_quality_requirement_assignments(
    conn: sqlite3.Connection,
    project_id: str,
    source_scenario_id: str,
    new_scenario_id: str,
    process_id_map: dict[str, str],
    timestamp: str,
    assignment_id_map: dict[str, str] | None = None,
) -> int:
    """Copy assignments to cloned Process steps while retaining repository links."""
    cloned_count = 0
    rows = conn.execute(
        """SELECT * FROM quality_requirement_assignments
           WHERE project_id=? AND scenario_id=? ORDER BY id""",
        (project_id, source_scenario_id),
    ).fetchall()
    for source_row in rows:
        row = dict(source_row)
        new_work_element_id = process_id_map.get(str(row["work_element_id"]))
        if not new_work_element_id:
            continue
        old_assignment_id = str(row["id"])
        new_assignment_id = str(uuid4())
        if assignment_id_map is not None:
            assignment_id_map[old_assignment_id] = new_assignment_id
        row.update(
            id=new_assignment_id, scenario_id=new_scenario_id,
            work_element_id=new_work_element_id, created_at=timestamp, updated_at=timestamp,
        )
        columns = list(row)
        conn.execute(
            f"""INSERT INTO quality_requirement_assignments ({', '.join(columns)})
                VALUES ({', '.join('?' for _ in columns)})""",
            tuple(row[column] for column in columns),
        )
        cloned_count += 1
    return cloned_count
