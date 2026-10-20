"""Persistence and validation for the shared Functional Review Equipment catalog."""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path
from uuid import uuid4

import pandas as pd
from PIL import Image

from utils.cache_store import (
    cached_store_read,
    is_scenario_task_completed,
    mark_scenario_task_completed,
)


EQUIPMENT_FUNCTION_AREAS = (
    "Quality",
    "Ergonomics",
    "Safety",
    "Materials",
    "Assembly",
)

EQUIPMENT_TIERS: tuple[str, ...] = (
    "Handheld Tools",
    "Station/Pitch Equipment",
    "Capital Equipment",
)

UNIT_ORIENTATION_OPTIONS: tuple[str, ...] = (
    "Front Facing",
    "Top Up / Standing",
    "Lying on Back",
    "Inverted / Bottom Up",
    "Left Side Leading",
    "Right Side Leading",
    "Rear Facing",
)

DEFAULT_EQUIPMENT_TYPES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Torque tool", "Handheld Tools", ("Quality", "Ergonomics")),
    ("Handheld equipment", "Handheld Tools", ("Assembly", "Quality")),
    ("ESD equipment", "Handheld Tools", ("Quality",)),
    ("Ergo Hand Tools", "Handheld Tools", ("Ergonomics",)),
    ("Vision equipment", "Station/Pitch Equipment", ("Quality",)),
    ("Scan/Compare equipment", "Station/Pitch Equipment", ("Quality",)),
    ("Test equipment", "Station/Pitch Equipment", ("Quality",)),
    ("Dimensional measurement equipment", "Station/Pitch Equipment", ("Quality",)),
    ("Poka-Yoke / Fixture equipment", "Station/Pitch Equipment", ("Quality", "Assembly")),
    ("Tape machine", "Station/Pitch Equipment", ("Assembly",)),
    ("Platform", "Station/Pitch Equipment", ("Ergonomics",)),
    ("Pit", "Station/Pitch Equipment", ("Ergonomics",)),
    ("Operator Lift", "Station/Pitch Equipment", ("Ergonomics",)),
    ("Ergo Lift Assists", "Station/Pitch Equipment", ("Ergonomics",)),
    ("Conveyor", "Capital Equipment", ("Assembly",)),
    ("Automation cell", "Capital Equipment", ("Assembly",)),
    ("Robot", "Capital Equipment", ("Assembly",)),
)

EQUIPMENT_TYPE_COLUMNS = [
    "id", "project_id", "label", "tier", "functional_areas", "created_at", "updated_at",
]
EQUIPMENT_COLUMNS = [
    "id", "project_id", "equipment_type_id", "equipment_type", "equipment_tier", "name",
    "description", "manufacturer", "model", "notes", "image_path",
    "functional_areas", "placement_id", "pitch_id", "pitch_number", "pitch_name",
    "process_link_count", "torque_requirement_count", "created_at", "updated_at",
]

CONVEYOR_ZONE_COLUMNS = [
    "id", "project_id", "scenario_id", "name", "sequence",
    "start_pitch_id", "end_pitch_id", "start_pitch_number", "end_pitch_number",
    "assigned_pitch_numbers",
    "conveyor_height_in", "conveyor_width_in", "unit_orientation", "orientation_image_path",
    "standard_pitch_length_in", "helper_pitch_count", "growth_pitch_count", "monument_length_in",
    "active_pitch_count", "total_pitch_count", "calculated_total_length_in", "calculated_total_length_ft",
    "notes", "created_at", "updated_at",
]



def _store_module():
    return importlib.import_module("utils.db_core")


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _list(value: object) -> list[str]:
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        values = [_text(item) for item in value]
    else:
        values = []
    return list(dict.fromkeys(item for item in values if item))


def _require_editor(editor_name: str) -> str:
    editor = _text(editor_name)
    if not editor:
        raise ValueError("Enter Current editor before saving Equipment changes.")
    return editor


def init_equipment_schema(conn: sqlite3.Connection) -> None:
    """Create the approved Equipment tables and seed each project once."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS equipment_types (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            label TEXT NOT NULL COLLATE NOCASE,
            tier TEXT NOT NULL DEFAULT 'Handheld Tools',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, label)
        );
        CREATE TABLE IF NOT EXISTS equipment_type_function_links (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            equipment_type_id TEXT NOT NULL REFERENCES equipment_types(id) ON DELETE CASCADE,
            functional_area TEXT NOT NULL
                CHECK(functional_area IN ('Quality', 'Ergonomics', 'Safety', 'Materials', 'Assembly')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(equipment_type_id, functional_area)
        );
        CREATE TABLE IF NOT EXISTS equipment_assets (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            equipment_type_id TEXT NOT NULL REFERENCES equipment_types(id) ON DELETE RESTRICT,
            name TEXT NOT NULL COLLATE NOCASE,
            description TEXT NOT NULL DEFAULT '',
            manufacturer TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, name)
        );
        CREATE TABLE IF NOT EXISTS equipment_function_links (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            equipment_id TEXT NOT NULL REFERENCES equipment_assets(id) ON DELETE CASCADE,
            functional_area TEXT NOT NULL
                CHECK(functional_area IN ('Quality', 'Ergonomics', 'Safety', 'Materials', 'Assembly')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(equipment_id, functional_area)
        );
        CREATE TABLE IF NOT EXISTS equipment_placements (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            equipment_id TEXT NOT NULL REFERENCES equipment_assets(id) ON DELETE CASCADE,
            pitch_id TEXT REFERENCES yamazumi_pitches(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(scenario_id, equipment_id)
        );
        CREATE TABLE IF NOT EXISTS equipment_process_links (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            placement_id TEXT NOT NULL REFERENCES equipment_placements(id) ON DELETE CASCADE,
            work_element_id TEXT REFERENCES work_elements(id) ON DELETE SET NULL,
            process_operation_snapshot TEXT NOT NULL DEFAULT '',
            process_description_snapshot TEXT NOT NULL DEFAULT '',
            station_pitch_snapshot TEXT NOT NULL DEFAULT '',
            unlinked_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(placement_id, work_element_id)
        );
        CREATE TABLE IF NOT EXISTS equipment_torque_requirement_links (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            equipment_id TEXT NOT NULL REFERENCES equipment_assets(id) ON DELETE CASCADE,
            quality_requirement_id TEXT NOT NULL
                REFERENCES quality_requirements(id) ON DELETE RESTRICT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(equipment_id, quality_requirement_id)
        );
        CREATE TABLE IF NOT EXISTS conveyor_zones (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            sequence INTEGER NOT NULL DEFAULT 10,
            start_pitch_id TEXT REFERENCES yamazumi_pitches(id) ON DELETE SET NULL,
            end_pitch_id TEXT REFERENCES yamazumi_pitches(id) ON DELETE SET NULL,
            conveyor_height_in REAL,
            conveyor_width_in REAL,
            unit_orientation TEXT NOT NULL DEFAULT '',
            orientation_image_path TEXT NOT NULL DEFAULT '',
            standard_pitch_length_in REAL DEFAULT 120.0,
            helper_pitch_count INTEGER DEFAULT 0,
            growth_pitch_count INTEGER DEFAULT 0,
            monument_length_in REAL DEFAULT 0.0,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_equipment_types_project
            ON equipment_types(project_id, label);
        CREATE INDEX IF NOT EXISTS idx_equipment_assets_project
            ON equipment_assets(project_id, name);
        CREATE INDEX IF NOT EXISTS idx_equipment_function_area
            ON equipment_function_links(project_id, functional_area, equipment_id);
        CREATE INDEX IF NOT EXISTS idx_equipment_placements_scenario
            ON equipment_placements(project_id, scenario_id, equipment_id);
        CREATE INDEX IF NOT EXISTS idx_equipment_process_links_work
            ON equipment_process_links(project_id, scenario_id, work_element_id);
        CREATE INDEX IF NOT EXISTS idx_equipment_torque_links_requirement
            ON equipment_torque_requirement_links(project_id, quality_requirement_id);
        CREATE INDEX IF NOT EXISTS idx_conveyor_zones_scenario
            ON conveyor_zones(project_id, scenario_id, sequence);
        """
    )
    # Check and upgrade equipment_types if tier column is missing
    cursor = conn.execute("PRAGMA table_info(equipment_types)")
    type_cols = [row[1] for row in cursor.fetchall()]
    if "tier" not in type_cols:
        conn.execute("ALTER TABLE equipment_types ADD COLUMN tier TEXT NOT NULL DEFAULT 'Handheld Tools'")
        conn.execute(
            """UPDATE equipment_types
               SET tier = 'Capital Equipment'
               WHERE label IN ('Conveyor', 'Automation cell', 'Robot')"""
        )
        conn.execute(
            """UPDATE equipment_types
               SET tier = 'Station/Pitch Equipment'
               WHERE label IN ('Vision equipment', 'Test equipment', 'Poka-Yoke / Fixture equipment',
                               'Dimensional measurement equipment', 'Scan/Compare equipment',
                               'Platform', 'Pit', 'Operator Lift', 'Ergo Lift Assists')"""
        )

    # Check and upgrade yamazumi_pitches for platform and pit ergonomics
    cursor = conn.execute("PRAGMA table_info(yamazumi_pitches)")
    pitch_cols = [row[1] for row in cursor.fetchall()]
    if "platform_height_in" not in pitch_cols:
        conn.execute("ALTER TABLE yamazumi_pitches ADD COLUMN platform_height_in REAL DEFAULT 0.0")
    if "pit_depth_in" not in pitch_cols:
        conn.execute("ALTER TABLE yamazumi_pitches ADD COLUMN pit_depth_in REAL DEFAULT 0.0")
    if "conveyor_zone_id" not in pitch_cols:
        conn.execute("ALTER TABLE yamazumi_pitches ADD COLUMN conveyor_zone_id TEXT REFERENCES conveyor_zones(id) ON DELETE SET NULL")

    for project in conn.execute("SELECT id FROM projects").fetchall():
        _ensure_default_equipment_types(conn, str(project["id"]))


def _ensure_default_equipment_types(conn: sqlite3.Connection, project_id: str) -> None:
    timestamp = _store_module().now_iso()
    existing_types = {
        str(row["label"]).strip().casefold()
        for row in conn.execute(
            "SELECT label FROM equipment_types WHERE project_id=?", (project_id,)
        ).fetchall()
    }
    for label, tier, functional_areas in DEFAULT_EQUIPMENT_TYPES:
        if label.strip().casefold() in existing_types:
            type_row = conn.execute(
                "SELECT id FROM equipment_types WHERE project_id=? AND LOWER(TRIM(label))=?",
                (project_id, label.strip().casefold()),
            ).fetchone()
            if type_row:
                existing_type_id = str(type_row["id"])
                for functional_area in functional_areas:
                    conn.execute(
                        """INSERT OR IGNORE INTO equipment_type_function_links
                           (id, project_id, equipment_type_id, functional_area, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (str(uuid4()), project_id, existing_type_id, functional_area, timestamp, timestamp),
                    )
            continue
        type_id = str(uuid4())
        conn.execute(
            """INSERT INTO equipment_types
               (id, project_id, label, tier, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (type_id, project_id, label, tier, timestamp, timestamp),
        )
        for functional_area in functional_areas:
            conn.execute(
                """INSERT INTO equipment_type_function_links
                   (id, project_id, equipment_type_id, functional_area, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), project_id, type_id, functional_area, timestamp, timestamp),
            )
        existing_types.add(label.strip().casefold())


@cached_store_read
def equipment_types(project_id: str, functional_area: str | None = None) -> pd.DataFrame:
    store = _store_module()
    with store.connection() as conn:
        if not is_scenario_task_completed("ensure_default_equipment_types", project_id, ""):
            _ensure_default_equipment_types(conn, project_id)
            mark_scenario_task_completed("ensure_default_equipment_types", project_id, "")
        area_filter = " AND EXISTS (SELECT 1 FROM equipment_type_function_links f WHERE f.equipment_type_id=t.id AND f.functional_area=?)" if functional_area else ""
        params = (project_id, functional_area) if functional_area else (project_id,)
        rows = conn.execute(
            f"""SELECT t.*,
                       COALESCE(GROUP_CONCAT(f.functional_area, ', '), '') AS functional_areas
                FROM equipment_types t
                LEFT JOIN equipment_type_function_links f ON f.equipment_type_id=t.id
                WHERE t.project_id=?{area_filter}
                GROUP BY t.id
                ORDER BY t.tier COLLATE NOCASE, t.label COLLATE NOCASE, t.id""",
            params,
        ).fetchall()
    frame = pd.DataFrame([dict(row) for row in rows], columns=EQUIPMENT_TYPE_COLUMNS)
    if not frame.empty:
        frame["functional_areas"] = frame["functional_areas"].map(_list)
    return frame


def save_equipment_type_rows(
    project_id: str, records: list[dict], editor_name: str
) -> dict[str, object]:
    store = _store_module()
    editor = _require_editor(editor_name)
    timestamp = store.now_iso()
    cleaned: list[dict] = []
    labels: set[str] = set()
    for record in records:
        label = _text(record.get("label"))
        if not label:
            raise ValueError("Equipment Type is required in every row.")
        key = label.casefold()
        if key in labels:
            raise ValueError("Equipment Type labels must be unique within the project.")
        labels.add(key)
        tier = _text(record.get("tier")) or "Handheld Tools"
        if tier not in EQUIPMENT_TIERS:
            tier = "Handheld Tools"
        functional_areas = _list(record.get("functional_areas"))
        invalid = [value for value in functional_areas if value not in EQUIPMENT_FUNCTION_AREAS]
        if invalid:
            raise ValueError("Choose only approved Functional Reviews for each Equipment Type.")
        if not functional_areas:
            raise ValueError("Choose at least one Functional Review for each Equipment Type.")
        cleaned.append({
            "id": _text(record.get("id")),
            "label": label,
            "tier": tier,
            "functional_areas": functional_areas,
        })

    changed_ids: list[str] = []
    created_ids: list[str] = []
    with store.connection() as conn:
        _ensure_default_equipment_types(conn, project_id)
        existing_rows = conn.execute(
            "SELECT * FROM equipment_types WHERE project_id=?", (project_id,)
        ).fetchall()
        existing = {str(row["id"]): row for row in existing_rows}
        submitted_ids = {row["id"] for row in cleaned if row["id"]}
        if not submitted_ids.issubset(existing):
            raise ValueError("One or more Equipment Types no longer exist. Refresh and try again.")
        for record in cleaned:
            type_id = record["id"] or str(uuid4())
            if type_id in existing:
                old = existing[type_id]
                old_areas = {
                    str(row["functional_area"])
                    for row in conn.execute(
                        "SELECT functional_area FROM equipment_type_function_links WHERE equipment_type_id=?",
                        (type_id,),
                    ).fetchall()
                }
                removed_areas = old_areas - set(record["functional_areas"])
                for area in removed_areas:
                    count = conn.execute(
                        """SELECT COUNT(*) FROM equipment_assets asset
                           JOIN equipment_function_links link ON link.equipment_id=asset.id
                           WHERE asset.project_id=? AND asset.equipment_type_id=?
                             AND link.functional_area=?""",
                        (project_id, type_id, area),
                    ).fetchone()[0]
                    if count:
                        raise ValueError(
                            f"{record['label']} is still used by {count} {area} equipment record(s). "
                            "Move or detach those records before removing the Functional Review."
                        )
                changed = (
                    _text(old["label"]) != record["label"]
                    or (_text(old["tier"]) if "tier" in old.keys() else "") != record["tier"]
                    or old_areas != set(record["functional_areas"])
                )
                if changed:
                    conn.execute(
                        "UPDATE equipment_types SET label=?, tier=?, updated_at=? WHERE id=? AND project_id=?",
                        (record["label"], record["tier"], timestamp, type_id, project_id),
                    )
                    changed_ids.append(type_id)
            else:
                conn.execute(
                    """INSERT INTO equipment_types
                       (id, project_id, label, tier, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (type_id, project_id, record["label"], record["tier"], timestamp, timestamp),
                )
                created_ids.append(type_id)
                old_areas = set()
            desired = set(record["functional_areas"])
            if not record["id"] or old_areas != desired:
                conn.execute(
                    "DELETE FROM equipment_type_function_links WHERE equipment_type_id=?",
                    (type_id,),
                )
                for area in EQUIPMENT_FUNCTION_AREAS:
                    if area in desired:
                        conn.execute(
                            """INSERT INTO equipment_type_function_links
                               (id, project_id, equipment_type_id, functional_area, created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (str(uuid4()), project_id, type_id, area, timestamp, timestamp),
                        )
        changed_count = len(set(changed_ids)) + len(created_ids)
        if changed_count:
            store.record_audit_event(
                project_id, "Equipment types", "Save & Refresh", changed_count,
                editor,
                {"created_ids": created_ids, "updated_ids": list(dict.fromkeys(changed_ids)), "store_timestamp": timestamp},
                _conn=conn,
            )
    return {"row_count": changed_count, "created_ids": created_ids, "updated_ids": list(dict.fromkeys(changed_ids)), "timestamp": timestamp}


def delete_equipment_types(
    project_id: str, type_ids: list[str], editor_name: str
) -> dict[str, object]:
    store = _store_module()
    editor = _require_editor(editor_name)
    normalized = list(dict.fromkeys(_text(value) for value in type_ids if _text(value)))
    if not normalized:
        return {"row_count": 0, "timestamp": store.now_iso()}
    placeholders = ",".join("?" for _ in normalized)
    timestamp = store.now_iso()
    with store.connection() as conn:
        rows = conn.execute(
            f"SELECT id, label FROM equipment_types WHERE project_id=? AND id IN ({placeholders})",
            (project_id, *normalized),
        ).fetchall()
        if len(rows) != len(normalized):
            raise ValueError("One or more Equipment Types no longer exist.")
        usage = conn.execute(
            f"""SELECT type.label, COUNT(asset.id) AS count
                FROM equipment_types type
                LEFT JOIN equipment_assets asset ON asset.equipment_type_id=type.id
                WHERE type.project_id=? AND type.id IN ({placeholders})
                GROUP BY type.id HAVING COUNT(asset.id)>0""",
            (project_id, *normalized),
        ).fetchall()
        if usage:
            summary = ", ".join(f"{row['label']} ({row['count']})" for row in usage)
            raise ValueError(f"Equipment Types in use cannot be deleted: {summary}.")
        conn.execute(
            f"DELETE FROM equipment_types WHERE project_id=? AND id IN ({placeholders})",
            (project_id, *normalized),
        )
        store.record_audit_event(
            project_id, "Equipment types", "Delete", len(normalized), editor,
            {"equipment_type_ids": normalized, "labels": [str(row["label"]) for row in rows], "store_timestamp": timestamp},
            _conn=conn,
        )
    return {"row_count": len(normalized), "timestamp": timestamp}


@cached_store_read
def equipment_assets(
    project_id: str,
    scenario_id: str | None = None,
    functional_area: str | None = None,
    equipment_type_id: str | None = None,
) -> pd.DataFrame:
    store = _store_module()
    params: list[object] = [scenario_id or "", project_id]
    where = ["asset.project_id=?"]
    if functional_area:
        where.append("EXISTS (SELECT 1 FROM equipment_function_links x WHERE x.equipment_id=asset.id AND x.functional_area=?)")
        params.append(functional_area)
    if equipment_type_id:
        where.append("asset.equipment_type_id=?")
        params.append(equipment_type_id)
    rows = store.query(
        f"""SELECT asset.*, type.label AS equipment_type,
                   COALESCE(type.tier, 'Handheld Tools') AS equipment_tier,
                   COALESCE((SELECT GROUP_CONCAT(link.functional_area, ', ')
                             FROM equipment_function_links link
                             WHERE link.equipment_id=asset.id), '') AS functional_areas,
                   placement.id AS placement_id, placement.pitch_id,
                   COALESCE(pitch.pitch_number, '') AS pitch_number,
                   COALESCE(pitch.pitch_name, '') AS pitch_name,
                   (SELECT COUNT(*) FROM equipment_process_links process_link
                    WHERE process_link.placement_id=placement.id) AS process_link_count,
                   (SELECT COUNT(*) FROM equipment_torque_requirement_links torque_link
                    WHERE torque_link.equipment_id=asset.id) AS torque_requirement_count
            FROM equipment_assets asset
            JOIN equipment_types type ON type.id=asset.equipment_type_id
            LEFT JOIN equipment_placements placement
              ON placement.equipment_id=asset.id AND placement.scenario_id=?
            LEFT JOIN yamazumi_pitches pitch ON pitch.id=placement.pitch_id
            WHERE {' AND '.join(where)}
            ORDER BY type.tier COLLATE NOCASE, type.label COLLATE NOCASE, asset.name COLLATE NOCASE, asset.id""",
        tuple(params),
    )
    frame = pd.DataFrame(rows, columns=EQUIPMENT_COLUMNS)
    if not frame.empty:
        frame["functional_areas"] = frame["functional_areas"].map(_list)
        frame["process_link_count"] = pd.to_numeric(frame["process_link_count"], errors="coerce").fillna(0).astype(int)
        frame["torque_requirement_count"] = pd.to_numeric(frame["torque_requirement_count"], errors="coerce").fillna(0).astype(int)
    return frame


@cached_store_read
def equipment_pitch_options(project_id: str, scenario_id: str) -> pd.DataFrame:
    store = _store_module()
    rows = store.query(
        """SELECT pitch.id, pitch.pitch_number, pitch.pitch_name, pitch.status,
                  area.name AS area_name, pitch.sequence
           FROM yamazumi_pitches pitch
           JOIN yamazumi_areas area ON area.id=pitch.area_id AND area.project_id=pitch.project_id
           WHERE pitch.project_id=? AND area.scenario_id=?
           ORDER BY area.name COLLATE NOCASE, pitch.sequence, pitch.pitch_number COLLATE NOCASE""",
        (project_id, scenario_id),
    )
    return pd.DataFrame(rows, columns=["id", "pitch_number", "pitch_name", "status", "area_name", "sequence"])


def _require_type_for_area(
    conn: sqlite3.Connection, project_id: str, type_id: str, functional_area: str
) -> sqlite3.Row:
    row = conn.execute(
        """SELECT type.* FROM equipment_types type
           JOIN equipment_type_function_links link ON link.equipment_type_id=type.id
           WHERE type.id=? AND type.project_id=? AND link.project_id=type.project_id
             AND link.functional_area=?""",
        (type_id, project_id, functional_area),
    ).fetchone()
    if not row:
        raise ValueError("Choose an Equipment Type assigned to this Functional Review.")
    return row


def _require_pitch(
    conn: sqlite3.Connection, project_id: str, scenario_id: str, pitch_id: str
) -> sqlite3.Row:
    row = conn.execute(
        """SELECT pitch.* FROM yamazumi_pitches pitch
           JOIN yamazumi_areas area ON area.id=pitch.area_id AND area.project_id=pitch.project_id
           WHERE pitch.id=? AND pitch.project_id=? AND area.scenario_id=?""",
        (pitch_id, project_id, scenario_id),
    ).fetchone()
    if not row:
        raise ValueError("The selected Station / Pitch is not in the active scenario.")
    return row


def save_function_equipment_rows(
    project_id: str,
    functional_area: str,
    scenario_id: str | None,
    records: list[dict],
    editor_name: str,
) -> dict[str, object]:
    store = _store_module()
    editor = _require_editor(editor_name)
    if functional_area not in EQUIPMENT_FUNCTION_AREAS:
        raise ValueError("Choose a valid Functional Review.")
    timestamp = store.now_iso()
    cleaned: list[dict] = []
    names: set[str] = set()
    for record in records:
        name = _text(record.get("name"))
        type_id = _text(record.get("equipment_type_id"))
        if not name or not type_id:
            raise ValueError("Equipment name and Equipment Type are required in every row.")
        key = name.casefold()
        if key in names:
            raise ValueError("Equipment names must be unique within the project.")
        names.add(key)
        cleaned.append({
            "id": _text(record.get("id")),
            "equipment_type_id": type_id,
            "name": name,
            "description": _text(record.get("description")),
            "manufacturer": _text(record.get("manufacturer")),
            "model": _text(record.get("model")),
            "notes": _text(record.get("notes")),
            "pitch_id": _text(record.get("pitch_id")),
        })
    changed_ids: list[str] = []
    created_ids: list[str] = []
    with store.connection() as conn:
        if scenario_id and not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        project_names = {
            str(row["name"]).strip().casefold(): str(row["id"])
            for row in conn.execute(
                "SELECT id, name FROM equipment_assets WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        for record in cleaned:
            type_row = _require_type_for_area(
                conn, project_id, record["equipment_type_id"], functional_area
            )
            asset_id = record["id"] or str(uuid4())
            existing = conn.execute(
                "SELECT * FROM equipment_assets WHERE id=? AND project_id=?",
                (asset_id, project_id),
            ).fetchone()
            owner = project_names.get(record["name"].casefold())
            if owner and owner != asset_id:
                raise ValueError(
                    f"Equipment name {record['name']} already exists. Use Add existing equipment instead."
                )
            if existing:
                if not conn.execute(
                    "SELECT 1 FROM equipment_function_links WHERE equipment_id=? AND functional_area=?",
                    (asset_id, functional_area),
                ).fetchone():
                    raise ValueError("One selected equipment record is no longer linked to this Functional Review.")
                if _text(type_row["label"]).casefold() != "torque tool":
                    torque_count = conn.execute(
                        "SELECT COUNT(*) FROM equipment_torque_requirement_links WHERE equipment_id=?",
                        (asset_id,),
                    ).fetchone()[0]
                    if torque_count:
                        raise ValueError("Remove linked Torque requirements before changing this equipment from Torque tool.")
                fields = ["equipment_type_id", "name", "description", "manufacturer", "model", "notes"]
                changed = any(_text(existing[field]) != record[field] for field in fields)
                if changed:
                    conn.execute(
                        """UPDATE equipment_assets
                           SET equipment_type_id=?, name=?, description=?, manufacturer=?, model=?, notes=?, updated_at=?
                           WHERE id=? AND project_id=?""",
                        tuple(record[field] for field in fields) + (timestamp, asset_id, project_id),
                    )
                    changed_ids.append(asset_id)
            else:
                conn.execute(
                    """INSERT INTO equipment_assets
                       (id, project_id, equipment_type_id, name, description, manufacturer,
                        model, notes, image_path, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)""",
                    (
                        asset_id, project_id, record["equipment_type_id"], record["name"],
                        record["description"], record["manufacturer"], record["model"],
                        record["notes"], timestamp, timestamp,
                    ),
                )
                conn.execute(
                    """INSERT INTO equipment_function_links
                       (id, project_id, equipment_id, functional_area, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (str(uuid4()), project_id, asset_id, functional_area, timestamp, timestamp),
                )
                created_ids.append(asset_id)
                project_names[record["name"].casefold()] = asset_id
            if scenario_id:
                pitch_id = record["pitch_id"] or None
                if pitch_id:
                    _require_pitch(conn, project_id, scenario_id, pitch_id)
                placement = conn.execute(
                    "SELECT * FROM equipment_placements WHERE equipment_id=? AND scenario_id=?",
                    (asset_id, scenario_id),
                ).fetchone()
                if placement and _text(placement["pitch_id"]) != (pitch_id or ""):
                    linked_work = conn.execute(
                        """SELECT process_link.work_element_id, element.pitch_id AS current_pitch_id
                           FROM equipment_process_links process_link
                           LEFT JOIN yamazumi_elements element
                             ON element.process_element_id=process_link.work_element_id
                            AND element.project_id=process_link.project_id
                           LEFT JOIN yamazumi_areas area ON area.id=element.area_id
                            AND area.scenario_id=process_link.scenario_id
                           WHERE process_link.placement_id=?""",
                        (placement["id"],),
                    ).fetchall()
                    if linked_work and any(
                        _text(link["current_pitch_id"]) != (pitch_id or "")
                        for link in linked_work
                    ):
                        raise ValueError(
                            "Station / Pitch cannot be changed in the chart while linked "
                            "Process Functions belong elsewhere. Reconcile the selected "
                            "equipment's placement and Process links first."
                        )
                    conn.execute(
                        "UPDATE equipment_placements SET pitch_id=?, updated_at=? WHERE id=?",
                        (pitch_id, timestamp, placement["id"]),
                    )
                    changed_ids.append(asset_id)
                elif not placement and pitch_id:
                    conn.execute(
                        """INSERT INTO equipment_placements
                           (id, project_id, scenario_id, equipment_id, pitch_id, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (str(uuid4()), project_id, scenario_id, asset_id, pitch_id, timestamp, timestamp),
                    )
                    changed_ids.append(asset_id)
        changed_count = len(set(created_ids + changed_ids))
        if changed_count:
            store.record_audit_event(
                project_id, "Equipment assets", "Save & Refresh", changed_count, editor,
                {
                    "functional_area": functional_area,
                    "scenario_id": scenario_id or "",
                    "created_ids": created_ids,
                    "updated_ids": list(dict.fromkeys(changed_ids)),
                    "store_timestamp": timestamp,
                },
                _conn=conn,
            )
    return {"row_count": changed_count, "created_ids": created_ids, "updated_ids": list(dict.fromkeys(changed_ids)), "timestamp": timestamp}


def attach_equipment_to_function(
    project_id: str, equipment_ids: list[str], functional_area: str, editor_name: str
) -> dict[str, object]:
    store = _store_module()
    editor = _require_editor(editor_name)
    normalized = list(dict.fromkeys(_text(value) for value in equipment_ids if _text(value)))
    timestamp = store.now_iso()
    created: list[str] = []
    with store.connection() as conn:
        for equipment_id in normalized:
            asset = conn.execute(
                "SELECT * FROM equipment_assets WHERE id=? AND project_id=?", (equipment_id, project_id)
            ).fetchone()
            if not asset:
                raise ValueError("One selected equipment record no longer exists.")
            _require_type_for_area(conn, project_id, str(asset["equipment_type_id"]), functional_area)
        for equipment_id in normalized:
            if conn.execute(
                "SELECT 1 FROM equipment_function_links WHERE equipment_id=? AND functional_area=?",
                (equipment_id, functional_area),
            ).fetchone():
                continue
            conn.execute(
                """INSERT INTO equipment_function_links
                   (id, project_id, equipment_id, functional_area, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), project_id, equipment_id, functional_area, timestamp, timestamp),
            )
            created.append(equipment_id)
        if created:
            store.record_audit_event(
                project_id, "Equipment assets", "Add existing equipment", len(created), editor,
                {"functional_area": functional_area, "equipment_ids": created, "store_timestamp": timestamp},
                _conn=conn,
            )
    return {"row_count": len(created), "equipment_ids": created, "timestamp": timestamp}


def detach_equipment_from_function(
    project_id: str, equipment_ids: list[str], functional_area: str, editor_name: str
) -> dict[str, object]:
    store = _store_module()
    editor = _require_editor(editor_name)
    normalized = list(dict.fromkeys(_text(value) for value in equipment_ids if _text(value)))
    if not normalized:
        return {"row_count": 0, "timestamp": store.now_iso()}
    placeholders = ",".join("?" for _ in normalized)
    timestamp = store.now_iso()
    with store.connection() as conn:
        rows = conn.execute(
            f"""SELECT link.equipment_id FROM equipment_function_links link
                JOIN equipment_assets asset ON asset.id=link.equipment_id
                WHERE link.project_id=? AND asset.project_id=? AND link.functional_area=?
                  AND link.equipment_id IN ({placeholders})""",
            (project_id, project_id, functional_area, *normalized),
        ).fetchall()
        if {str(row["equipment_id"]) for row in rows} != set(normalized):
            raise ValueError("One or more selected equipment records are no longer linked here.")
        conn.execute(
            f"""DELETE FROM equipment_function_links
                WHERE project_id=? AND functional_area=? AND equipment_id IN ({placeholders})""",
            (project_id, functional_area, *normalized),
        )
        store.record_audit_event(
            project_id, "Equipment assets", "Remove Functional Review link", len(normalized), editor,
            {"functional_area": functional_area, "equipment_ids": normalized, "store_timestamp": timestamp},
            _conn=conn,
        )
    return {"row_count": len(normalized), "timestamp": timestamp}


def equipment_deletion_impact(project_id: str, equipment_ids: list[str]) -> dict[str, object]:
    store = _store_module()
    normalized = list(dict.fromkeys(_text(value) for value in equipment_ids if _text(value)))
    if not normalized:
        return {"equipment": [], "function_links": 0, "placements": 0, "process_links": 0, "torque_links": 0, "image_files": 0}
    placeholders = ",".join("?" for _ in normalized)
    with store.connection() as conn:
        assets = conn.execute(
            f"SELECT id, name, image_path FROM equipment_assets WHERE project_id=? AND id IN ({placeholders})",
            (project_id, *normalized),
        ).fetchall()
        if len(assets) != len(normalized):
            raise ValueError("One or more selected equipment records no longer exist.")
        counts = {}
        for key, table, column in [
            ("function_links", "equipment_function_links", "equipment_id"),
            ("placements", "equipment_placements", "equipment_id"),
            ("torque_links", "equipment_torque_requirement_links", "equipment_id"),
        ]:
            counts[key] = int(conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE project_id=? AND {column} IN ({placeholders})",
                (project_id, *normalized),
            ).fetchone()[0])
        counts["process_links"] = int(conn.execute(
            f"""SELECT COUNT(*) FROM equipment_process_links link
                JOIN equipment_placements placement ON placement.id=link.placement_id
                WHERE link.project_id=? AND placement.equipment_id IN ({placeholders})""",
            (project_id, *normalized),
        ).fetchone()[0])
    return {
        "equipment": [{"id": str(row["id"]), "name": str(row["name"]), "image_path": str(row["image_path"] or "")} for row in assets],
        **counts,
        "image_files": sum(bool(_text(row["image_path"])) for row in assets),
    }


def delete_equipment_assets(
    project_id: str, equipment_ids: list[str], editor_name: str
) -> dict[str, object]:
    store = _store_module()
    editor = _require_editor(editor_name)
    impact = equipment_deletion_impact(project_id, equipment_ids)
    normalized = [item["id"] for item in impact["equipment"]]
    if not normalized:
        return {"row_count": 0, "timestamp": store.now_iso()}
    placeholders = ",".join("?" for _ in normalized)
    timestamp = store.now_iso()
    with store.connection() as conn:
        conn.execute(
            f"DELETE FROM equipment_assets WHERE project_id=? AND id IN ({placeholders})",
            (project_id, *normalized),
        )
        store.record_audit_event(
            project_id, "Equipment assets", "Delete", len(normalized), editor,
            {**{key: value for key, value in impact.items() if key != "equipment"}, "equipment_ids": normalized, "names": [item["name"] for item in impact["equipment"]], "store_timestamp": timestamp},
            _conn=conn,
        )
    for item in impact["equipment"]:
        store._remove_owned_upload(item["image_path"])
    return {"row_count": len(normalized), "timestamp": timestamp, "impact": impact}


@cached_store_read
def equipment_process_options(project_id: str, scenario_id: str, pitch_id: str) -> pd.DataFrame:
    store = _store_module()
    _ = equipment_pitch_options(project_id, scenario_id)
    rows = store.query(
        """SELECT work.id, work.sequence, work.operation,
                  COALESCE(NULLIF(TRIM(yamazumi.description), ''), work.operation) AS work_element,
                  pitch.id AS pitch_id, pitch.pitch_number
           FROM yamazumi_elements yamazumi
           JOIN yamazumi_areas area ON area.id=yamazumi.area_id
             AND area.project_id=yamazumi.project_id AND area.scenario_id=?
           JOIN yamazumi_pitches pitch ON pitch.id=yamazumi.pitch_id
             AND pitch.project_id=yamazumi.project_id
           JOIN work_elements work ON work.id=yamazumi.process_element_id
             AND work.project_id=yamazumi.project_id AND work.scenario_id=area.scenario_id
           WHERE yamazumi.project_id=? AND pitch.id=?
           ORDER BY yamazumi.sequence, work.sequence, work.id""",
        (scenario_id, project_id, pitch_id),
    )
    frame = pd.DataFrame(rows, columns=["id", "sequence", "operation", "work_element", "pitch_id", "pitch_number"])
    if not frame.empty:
        contexts = store.work_element_op_contexts(project_id, scenario_id, frame["id"].astype(str).tolist())
        frame["op_id"] = frame["id"].astype(str).map(lambda value: str(contexts.get(value, {}).get("op_id") or "Op ID unavailable"))
        frame["sort_order"] = frame["id"].astype(str).map(lambda value: int(contexts.get(value, {}).get("sort_order", 10**9)))
        frame = frame.sort_values(["sort_order", "sequence", "id"], kind="stable").reset_index(drop=True)
    else:
        frame["op_id"] = pd.Series(dtype="string")
        frame["sort_order"] = pd.Series(dtype="int64")
    return frame


@cached_store_read
def equipment_placement_detail(project_id: str, scenario_id: str, equipment_id: str) -> dict[str, object]:
    store = _store_module()
    rows = store.query(
        """SELECT placement.id, placement.pitch_id
           FROM equipment_assets asset
           LEFT JOIN equipment_placements placement
             ON placement.equipment_id=asset.id AND placement.scenario_id=?
           WHERE asset.id=? AND asset.project_id=?""",
        (scenario_id, equipment_id, project_id),
    )
    if not rows:
        raise ValueError("That equipment record no longer exists.")
    placement_id = _text(rows[0].get("id"))
    work_ids = []
    if placement_id:
        work_ids = [
            str(row["work_element_id"])
            for row in store.query(
                """SELECT work_element_id FROM equipment_process_links
                   WHERE project_id=? AND scenario_id=? AND placement_id=?
                   ORDER BY created_at, id""",
                (project_id, scenario_id, placement_id),
            )
        ]
    return {"placement_id": placement_id, "pitch_id": _text(rows[0].get("pitch_id")), "work_element_ids": work_ids}


def save_equipment_placement(
    project_id: str,
    scenario_id: str,
    equipment_id: str,
    pitch_id: str | None,
    work_element_ids: list[str],
    editor_name: str,
    mark_pitch_blocked: bool = False,
) -> dict[str, object]:
    store = _store_module()
    editor = _require_editor(editor_name)
    normalized_pitch = _text(pitch_id) or None
    normalized_work = list(dict.fromkeys(_text(value) for value in work_element_ids if _text(value)))
    if normalized_work and not normalized_pitch:
        raise ValueError("Choose Station / Pitch before linking Process Functions.")
    timestamp = store.now_iso()
    with store.connection() as conn:
        asset = conn.execute(
            "SELECT id FROM equipment_assets WHERE id=? AND project_id=?", (equipment_id, project_id)
        ).fetchone()
        if not asset:
            raise ValueError("That equipment record no longer exists.")
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?", (scenario_id, project_id)
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        if normalized_pitch:
            _require_pitch(conn, project_id, scenario_id, normalized_pitch)
        for work_id in normalized_work:
            work = conn.execute(
                "SELECT id FROM work_elements WHERE id=? AND project_id=? AND scenario_id=?",
                (work_id, project_id, scenario_id),
            ).fetchone()
            if not work:
                raise ValueError("One selected Process Function is outside the active scenario.")
            link_pitch = conn.execute(
                """SELECT pitch.id FROM yamazumi_elements element
                   JOIN yamazumi_areas area ON area.id=element.area_id
                     AND area.project_id=element.project_id AND area.scenario_id=?
                   JOIN yamazumi_pitches pitch ON pitch.id=element.pitch_id
                   WHERE element.project_id=? AND element.process_element_id=?
                   ORDER BY element.sequence, element.id LIMIT 1""",
                (scenario_id, project_id, work_id),
            ).fetchone()
            if not link_pitch or str(link_pitch["id"]) != normalized_pitch:
                raise ValueError("Every linked Process Function must currently belong to the selected Station / Pitch.")
        placement = conn.execute(
            "SELECT * FROM equipment_placements WHERE equipment_id=? AND scenario_id=?",
            (equipment_id, scenario_id),
        ).fetchone()
        before_pitch = _text(placement["pitch_id"]) if placement else ""
        before_work = {
            str(row["work_element_id"])
            for row in conn.execute(
                "SELECT work_element_id FROM equipment_process_links WHERE placement_id=?",
                (placement["id"],),
            ).fetchall()
        } if placement else set()
        if not placement:
            placement_id = str(uuid4())
            conn.execute(
                """INSERT INTO equipment_placements
                   (id, project_id, scenario_id, equipment_id, pitch_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (placement_id, project_id, scenario_id, equipment_id, normalized_pitch, timestamp, timestamp),
            )
        else:
            placement_id = str(placement["id"])
            conn.execute(
                "UPDATE equipment_placements SET pitch_id=?, updated_at=? WHERE id=?",
                (normalized_pitch, timestamp, placement_id),
            )
            conn.execute("DELETE FROM equipment_process_links WHERE placement_id=?", (placement_id,))
        for work_id in normalized_work:
            conn.execute(
                """INSERT INTO equipment_process_links
                   (id, project_id, scenario_id, placement_id, work_element_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), project_id, scenario_id, placement_id, work_id, timestamp, timestamp),
            )
        if mark_pitch_blocked and normalized_pitch:
            conn.execute(
                "UPDATE yamazumi_pitches SET status='Blocked', updated_at=? WHERE id=? AND project_id=?",
                (timestamp, normalized_pitch, project_id),
            )
        changed = before_pitch != (normalized_pitch or "") or before_work != set(normalized_work)
        if changed:
            store.record_audit_event(
                project_id, "Equipment placements", "Save & Refresh", 1, editor,
                {
                    "scenario_id": scenario_id,
                    "equipment_id": equipment_id,
                    "old_pitch_id": before_pitch,
                    "new_pitch_id": normalized_pitch or "",
                    "work_element_ids": normalized_work,
                    "store_timestamp": timestamp,
                },
                _conn=conn,
            )
    return {"row_count": int(changed), "placement_id": placement_id, "timestamp": timestamp}


@cached_store_read
def equipment_placement_mismatches(project_id: str, scenario_id: str) -> pd.DataFrame:
    store = _store_module()
    rows = store.query(
        """SELECT asset.id AS equipment_id, asset.name,
                  placement.id AS placement_id, placement.pitch_id AS saved_pitch_id,
                  COALESCE(saved_pitch.pitch_number, 'Unassigned') AS saved_pitch,
                  process_link.work_element_id,
                  current_pitch.id AS current_pitch_id,
                  COALESCE(current_pitch.pitch_number, 'Unassigned') AS current_pitch,
                  COALESCE(NULLIF(TRIM(element.description), ''), work.operation) AS process_function
           FROM equipment_placements placement
           JOIN equipment_assets asset ON asset.id=placement.equipment_id
           LEFT JOIN yamazumi_pitches saved_pitch ON saved_pitch.id=placement.pitch_id
           JOIN equipment_process_links process_link ON process_link.placement_id=placement.id
           JOIN work_elements work ON work.id=process_link.work_element_id
             AND work.project_id=placement.project_id AND work.scenario_id=placement.scenario_id
           LEFT JOIN yamazumi_elements element ON element.process_element_id=work.id
             AND element.project_id=work.project_id
           LEFT JOIN yamazumi_areas area ON area.id=element.area_id AND area.scenario_id=work.scenario_id
           LEFT JOIN yamazumi_pitches current_pitch ON current_pitch.id=element.pitch_id
           WHERE placement.project_id=? AND placement.scenario_id=?
             AND COALESCE(current_pitch.id, '')<>COALESCE(placement.pitch_id, '')
           ORDER BY asset.name COLLATE NOCASE, work.sequence, work.id""",
        (project_id, scenario_id),
    )
    return pd.DataFrame(rows, columns=[
        "equipment_id", "name", "placement_id", "saved_pitch_id", "saved_pitch",
        "work_element_id", "current_pitch_id", "current_pitch", "process_function",
    ])


def move_equipment_to_linked_pitch(
    project_id: str, scenario_id: str, equipment_id: str, editor_name: str
) -> dict[str, object]:
    store = _store_module()
    editor = _require_editor(editor_name)
    mismatches = equipment_placement_mismatches(project_id, scenario_id)
    rows = mismatches.loc[mismatches["equipment_id"].astype(str).eq(equipment_id)]
    if rows.empty:
        raise ValueError("This equipment no longer has a Pitch mismatch.")
    current_ids = {_text(value) for value in rows["current_pitch_id"]}
    if "" in current_ids or len(current_ids) != 1:
        raise ValueError("Linked Process Functions are split across Pitches. Reconcile them manually.")
    target_pitch_id = next(iter(current_ids))
    timestamp = store.now_iso()
    with store.connection() as conn:
        _require_pitch(conn, project_id, scenario_id, target_pitch_id)
        placement = conn.execute(
            "SELECT id, pitch_id FROM equipment_placements WHERE project_id=? AND scenario_id=? AND equipment_id=?",
            (project_id, scenario_id, equipment_id),
        ).fetchone()
        if not placement:
            raise ValueError("The equipment placement no longer exists.")
        conn.execute(
            "UPDATE equipment_placements SET pitch_id=?, updated_at=? WHERE id=?",
            (target_pitch_id, timestamp, placement["id"]),
        )
        store.record_audit_event(
            project_id, "Equipment placements", "Move equipment to current Pitch", 1, editor,
            {"scenario_id": scenario_id, "equipment_id": equipment_id, "old_pitch_id": _text(placement["pitch_id"]), "new_pitch_id": target_pitch_id, "store_timestamp": timestamp},
            _conn=conn,
        )
    return {"row_count": 1, "pitch_id": target_pitch_id, "timestamp": timestamp}


def unlink_moved_equipment_links(
    project_id: str,
    scenario_id: str,
    equipment_id: str | None,
    editor_name: str,
) -> dict[str, object]:
    """Unlink moved process functions from station equipment, keeping equipment anchored to its pitch.
    The moved operation will now show as an unfulfilled equipment need at its new pitch."""
    store = _store_module()
    editor = _require_editor(editor_name)
    timestamp = store.now_iso()
    with store.connection() as conn:
        mismatches = equipment_placement_mismatches(project_id, scenario_id)
        if equipment_id:
            mismatches = mismatches.loc[mismatches["equipment_id"].astype(str).eq(equipment_id)]
        if mismatches.empty:
            raise ValueError("No mismatched equipment links to unlink.")
        count = 0
        for _, row in mismatches.iterrows():
            placement_id = str(row["placement_id"])
            work_id = str(row["work_element_id"])
            conn.execute(
                "DELETE FROM equipment_process_links WHERE placement_id=? AND work_element_id=?",
                (placement_id, work_id),
            )
            count += 1
        store.record_audit_event(
            project_id,
            "Equipment placements",
            "Unlink Moved Steps",
            count,
            editor,
            {
                "scenario_id": scenario_id,
                "equipment_id": equipment_id or "all_mismatched",
                "unlinked_count": count,
                "store_timestamp": timestamp,
            },
            _conn=conn,
        )
    return {"row_count": count, "timestamp": timestamp}


@cached_store_read
def torque_requirements(project_id: str) -> pd.DataFrame:
    store = _store_module()
    rows = store.query(
        """SELECT requirement.id, requirement.unique_identifier, requirement.description,
                  requirement.target_value, requirement.tolerances, requirement.unit,
                  COALESCE(detail.tool_type, '') AS tool_type,
                  COALESCE(detail.tool_orientation, '') AS tool_orientation,
                  COALESCE(detail.screw_bit_type, '') AS screw_bit_type
           FROM quality_requirements requirement
           LEFT JOIN quality_requirement_torque_details detail
             ON detail.quality_requirement_id=requirement.id AND detail.project_id=requirement.project_id
           WHERE requirement.project_id=? AND LOWER(TRIM(requirement.requirement_type))='torque'
           ORDER BY requirement.unique_identifier COLLATE NOCASE, requirement.id""",
        (project_id,),
    )
    return pd.DataFrame(rows, columns=[
        "id", "unique_identifier", "description", "target_value", "tolerances", "unit",
        "tool_type", "tool_orientation", "screw_bit_type",
    ])


@cached_store_read
def equipment_torque_requirement_ids(project_id: str, equipment_id: str) -> list[str]:
    store = _store_module()
    return [
        str(row["quality_requirement_id"])
        for row in store.query(
            """SELECT link.quality_requirement_id
               FROM equipment_torque_requirement_links link
               JOIN equipment_assets asset ON asset.id=link.equipment_id
               WHERE link.project_id=? AND link.equipment_id=? AND asset.project_id=link.project_id
               ORDER BY link.created_at, link.id""",
            (project_id, equipment_id),
        )
    ]


@cached_store_read
def equipment_torque_published_specifications(
    project_id: str,
    scenario_id: str,
    equipment_id: str,
    requirement_ids: list[str],
) -> pd.DataFrame:
    """Return exact-step published snapshots for selected Torque definitions."""
    store = _store_module()
    normalized = list(
        dict.fromkeys(_text(value) for value in requirement_ids if _text(value))
    )
    columns = [
        "quality_requirement_id", "work_element_id", "op_id", "process_function",
        "unique_identifier", "description", "target_value", "tolerances", "unit",
        "tool_type", "tool_orientation", "screw_bit_type",
    ]
    if not normalized:
        return pd.DataFrame({column: pd.Series(dtype="string") for column in columns})
    placeholders = ",".join("?" for _ in normalized)
    rows = store.query(
        f"""SELECT assignment.quality_requirement_id, assignment.work_element_id,
                   COALESCE(NULLIF(TRIM(element.description), ''), work.operation)
                       AS process_function,
                   assignment.unique_identifier, assignment.description,
                   assignment.target_value, assignment.tolerances, assignment.unit,
                   COALESCE(detail.tool_type, '') AS tool_type,
                   COALESCE(detail.tool_orientation, '') AS tool_orientation,
                   COALESCE(detail.screw_bit_type, '') AS screw_bit_type
            FROM equipment_assets asset
            JOIN equipment_placements placement
              ON placement.equipment_id=asset.id AND placement.scenario_id=?
            JOIN equipment_process_links process_link
              ON process_link.placement_id=placement.id
             AND process_link.scenario_id=placement.scenario_id
            JOIN quality_requirement_assignments assignment
              ON assignment.project_id=asset.project_id
             AND assignment.scenario_id=placement.scenario_id
             AND assignment.work_element_id=process_link.work_element_id
            JOIN work_elements work
              ON work.id=process_link.work_element_id
             AND work.project_id=asset.project_id
             AND work.scenario_id=placement.scenario_id
            LEFT JOIN yamazumi_elements element
              ON element.project_id=asset.project_id
             AND element.process_element_id=work.id
            LEFT JOIN quality_requirement_torque_details detail
              ON detail.project_id=asset.project_id
             AND detail.quality_requirement_id=assignment.quality_requirement_id
            WHERE asset.project_id=? AND asset.id=?
              AND assignment.quality_requirement_id IN ({placeholders})
            ORDER BY process_link.created_at, process_link.id,
                     assignment.unique_identifier COLLATE NOCASE,
                     assignment.quality_requirement_id""",
        (scenario_id, project_id, equipment_id, *normalized),
    )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame({column: pd.Series(dtype="string") for column in columns})
    context_by_id = store.work_element_op_contexts(project_id, scenario_id)
    frame["op_id"] = frame["work_element_id"].map(
        lambda value: _text(context_by_id.get(_text(value), {}).get("op_id"))
    )
    return frame.reindex(columns=columns)


def save_equipment_torque_requirements(
    project_id: str, equipment_id: str, requirement_ids: list[str], editor_name: str
) -> dict[str, object]:
    store = _store_module()
    editor = _require_editor(editor_name)
    normalized = list(dict.fromkeys(_text(value) for value in requirement_ids if _text(value)))
    timestamp = store.now_iso()
    with store.connection() as conn:
        asset = conn.execute(
            """SELECT asset.id, type.label FROM equipment_assets asset
               JOIN equipment_types type ON type.id=asset.equipment_type_id
               WHERE asset.id=? AND asset.project_id=?""",
            (equipment_id, project_id),
        ).fetchone()
        if not asset:
            raise ValueError("That equipment record no longer exists.")
        if _text(asset["label"]).casefold() != "torque tool":
            raise ValueError("Torque requirements can only be linked to Torque tool equipment.")
        if normalized:
            placeholders = ",".join("?" for _ in normalized)
            rows = conn.execute(
                f"""SELECT id FROM quality_requirements
                    WHERE project_id=? AND LOWER(TRIM(requirement_type))='torque'
                      AND id IN ({placeholders})""",
                (project_id, *normalized),
            ).fetchall()
            if {str(row["id"]) for row in rows} != set(normalized):
                raise ValueError("One selected Torque requirement is unavailable.")
        before = {
            str(row["quality_requirement_id"])
            for row in conn.execute(
                "SELECT quality_requirement_id FROM equipment_torque_requirement_links WHERE equipment_id=?",
                (equipment_id,),
            ).fetchall()
        }
        conn.execute("DELETE FROM equipment_torque_requirement_links WHERE equipment_id=?", (equipment_id,))
        for requirement_id in normalized:
            conn.execute(
                """INSERT INTO equipment_torque_requirement_links
                   (id, project_id, equipment_id, quality_requirement_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), project_id, equipment_id, requirement_id, timestamp, timestamp),
            )
        changed = before != set(normalized)
        if changed:
            store.record_audit_event(
                project_id, "Equipment Torque links", "Save & Refresh", 1, editor,
                {"equipment_id": equipment_id, "quality_requirement_ids": normalized, "store_timestamp": timestamp},
                _conn=conn,
            )
    return {"row_count": int(changed), "timestamp": timestamp}


@cached_store_read
def equipment_torque_compatibility_warnings(
    project_id: str, scenario_id: str, equipment_id: str
) -> list[str]:
    store = _store_module()
    rows = store.query(
        """SELECT work.id AS work_element_id,
                  COALESCE(NULLIF(TRIM(element.description), ''), work.operation) AS process_function,
                  requirement.id AS requirement_id, requirement.unique_identifier
           FROM equipment_assets asset
           JOIN equipment_placements placement ON placement.equipment_id=asset.id AND placement.scenario_id=?
           JOIN equipment_process_links process_link ON process_link.placement_id=placement.id
           JOIN work_elements work ON work.id=process_link.work_element_id
           JOIN equipment_torque_requirement_links torque_link ON torque_link.equipment_id=asset.id
           JOIN quality_requirements requirement ON requirement.id=torque_link.quality_requirement_id
           LEFT JOIN yamazumi_elements element ON element.process_element_id=work.id AND element.project_id=work.project_id
           LEFT JOIN quality_requirement_assignments assignment
             ON assignment.project_id=asset.project_id AND assignment.scenario_id=placement.scenario_id
            AND assignment.work_element_id=work.id
            AND assignment.quality_requirement_id=requirement.id
           WHERE asset.project_id=? AND asset.id=? AND assignment.id IS NULL
           ORDER BY work.sequence, requirement.unique_identifier COLLATE NOCASE""",
        (scenario_id, project_id, equipment_id),
    )
    return [
        f"{row['process_function']} does not have {row['unique_identifier']} published to that exact Process step."
        for row in rows
    ]


def set_equipment_image(
    project_id: str, equipment_id: str, uploaded_file, editor_name: str
) -> str:
    store = _store_module()
    editor = _require_editor(editor_name)
    suffix = Path(str(uploaded_file.name)).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Use PNG, JPG, JPEG, or WEBP images.")
    content = uploaded_file.getvalue()
    if not content:
        raise ValueError("Choose a non-empty image.")
    try:
        from io import BytesIO
        with Image.open(BytesIO(content)) as image:
            image.verify()
    except Exception as exc:
        raise ValueError("The selected file is not a readable image.") from exc
    target = store.UPLOAD_DIR / f"equipment_{equipment_id}_{uuid4()}{suffix}"
    target.write_bytes(content)
    previous = ""
    timestamp = store.now_iso()
    try:
        with store.connection() as conn:
            asset = conn.execute(
                "SELECT image_path FROM equipment_assets WHERE id=? AND project_id=?",
                (equipment_id, project_id),
            ).fetchone()
            if not asset:
                raise ValueError("That equipment record no longer exists.")
            previous = _text(asset["image_path"])
            conn.execute(
                "UPDATE equipment_assets SET image_path=?, updated_at=? WHERE id=? AND project_id=?",
                (str(target), timestamp, equipment_id, project_id),
            )
            store.record_audit_event(
                project_id, "Equipment images", "Save primary image", 1, editor,
                {"equipment_id": equipment_id, "store_timestamp": timestamp},
                _conn=conn,
            )
    except Exception:
        store._remove_owned_upload(target)
        raise
    if previous != str(target):
        store._remove_owned_upload(previous)
    return str(target)


def delete_equipment_image(project_id: str, equipment_id: str, editor_name: str) -> int:
    store = _store_module()
    editor = _require_editor(editor_name)
    timestamp = store.now_iso()
    with store.connection() as conn:
        asset = conn.execute(
            "SELECT image_path FROM equipment_assets WHERE id=? AND project_id=?",
            (equipment_id, project_id),
        ).fetchone()
        if not asset:
            raise ValueError("That equipment record no longer exists.")
        path = _text(asset["image_path"])
        if not path:
            return 0
        conn.execute(
            "UPDATE equipment_assets SET image_path='', updated_at=? WHERE id=? AND project_id=?",
            (timestamp, equipment_id, project_id),
        )
        store.record_audit_event(
            project_id, "Equipment images", "Delete primary image", 1, editor,
            {"equipment_id": equipment_id, "store_timestamp": timestamp},
            _conn=conn,
        )
    store._remove_owned_upload(path)
    return 1


def clone_equipment_scenario(
    conn: sqlite3.Connection,
    project_id: str,
    source_scenario_id: str,
    target_scenario_id: str,
    pitch_id_map: dict[str, str],
    process_id_map: dict[str, str],
    timestamp: str,
) -> None:
    """Clone scenario placements while reusing project-wide equipment assets."""
    for source in conn.execute(
        """SELECT * FROM equipment_placements
           WHERE project_id=? AND scenario_id=? ORDER BY created_at, id""",
        (project_id, source_scenario_id),
    ).fetchall():
        old_placement_id = str(source["id"])
        new_placement_id = str(uuid4())
        old_pitch_id = _text(source["pitch_id"])
        new_pitch_id = pitch_id_map.get(old_pitch_id) if old_pitch_id else None
        if old_pitch_id and not new_pitch_id:
            raise ValueError("An Equipment Station / Pitch could not be remapped while cloning the scenario.")
        conn.execute(
            """INSERT INTO equipment_placements
               (id, project_id, scenario_id, equipment_id, pitch_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (new_placement_id, project_id, target_scenario_id, source["equipment_id"], new_pitch_id, timestamp, timestamp),
        )
        for link in conn.execute(
            "SELECT * FROM equipment_process_links WHERE placement_id=? ORDER BY created_at, id",
            (old_placement_id,),
        ).fetchall():
            new_work_id = process_id_map.get(str(link["work_element_id"]))
            if not new_work_id:
                raise ValueError("An Equipment Process Function could not be remapped while cloning the scenario.")
            conn.execute(
                """INSERT INTO equipment_process_links
                   (id, project_id, scenario_id, placement_id, work_element_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), project_id, target_scenario_id, new_placement_id, new_work_id, timestamp, timestamp),
            )

    # Clone conveyor zones
    zone_id_map: dict[str, str] = {}
    for zone in conn.execute(
        """SELECT * FROM conveyor_zones WHERE project_id=? AND scenario_id=? ORDER BY sequence, id""",
        (project_id, source_scenario_id),
    ).fetchall():
        old_zid = str(zone["id"])
        new_zid = str(uuid4())
        zone_id_map[old_zid] = new_zid
        old_start = _text(zone["start_pitch_id"])
        old_end = _text(zone["end_pitch_id"])
        new_start = pitch_id_map.get(old_start) if old_start else None
        new_end = pitch_id_map.get(old_end) if old_end else None

        conn.execute(
            """INSERT INTO conveyor_zones
               (id, project_id, scenario_id, name, sequence, start_pitch_id, end_pitch_id,
                conveyor_height_in, conveyor_width_in, unit_orientation, orientation_image_path,
                standard_pitch_length_in, helper_pitch_count, growth_pitch_count, monument_length_in,
                notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_zid, project_id, target_scenario_id, zone["name"], zone["sequence"],
                new_start, new_end, zone["conveyor_height_in"], zone["conveyor_width_in"],
                zone["unit_orientation"], zone["orientation_image_path"],
                zone["standard_pitch_length_in"], zone["helper_pitch_count"],
                zone["growth_pitch_count"], zone["monument_length_in"], zone["notes"],
                timestamp, timestamp,
            ),
        )

    # Remap conveyor_zone_id and copy platform/pit dimensions on cloned pitches
    for old_pid, new_pid in pitch_id_map.items():
        old_pitch = conn.execute(
            "SELECT conveyor_zone_id, platform_height_in, pit_depth_in FROM yamazumi_pitches WHERE id=?",
            (old_pid,),
        ).fetchone()
        if old_pitch:
            old_zid = _text(old_pitch["conveyor_zone_id"])
            new_zid = zone_id_map.get(old_zid) if old_zid else None
            conn.execute(
                """UPDATE yamazumi_pitches
                   SET conveyor_zone_id=?, platform_height_in=?, pit_depth_in=?
                   WHERE id=?""",
                (new_zid, old_pitch["platform_height_in"] or 0.0, old_pitch["pit_depth_in"] or 0.0, new_pid),
            )


@cached_store_read
def equipment_needs_vs_placements_matrix(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Return a unified Equipment Needs vs Placements matrix DataFrame."""
    store = _store_module()
    with store.connection() as conn:
        if not is_scenario_task_completed("init_equipment_schema_for_matrix", project_id, ""):
            init_equipment_schema(conn)
            mark_scenario_task_completed("init_equipment_schema_for_matrix", project_id, "")

        work_rows = conn.execute(
            """SELECT id, station, operation, sequence
               FROM work_elements
               WHERE project_id=? AND scenario_id=?
               ORDER BY sequence, id""",
            (project_id, scenario_id),
        ).fetchall()
        if not work_rows:
            return pd.DataFrame(columns=[
                "work_element_id", "op_id", "pitch_station", "operation",
                "source_stage", "requirement_control_desc", "expected_equipment_type",
                "linked_asset_names", "coverage_status", "is_satisfied",
            ])

        work_ids = [str(r["id"]) for r in work_rows]
        op_contexts = store.work_element_op_contexts(project_id, scenario_id, work_ids)

        placed_rows = conn.execute(
            """SELECT link.work_element_id, asset.id AS equipment_id, asset.name AS asset_name,
                      eqtype.label AS equipment_type
               FROM equipment_process_links link
               JOIN equipment_placements placement
                 ON placement.id = link.placement_id
                AND placement.project_id = link.project_id
                AND placement.scenario_id = link.scenario_id
               JOIN equipment_assets asset
                 ON asset.id = placement.equipment_id
                AND asset.project_id = link.project_id
               JOIN equipment_types eqtype
                 ON eqtype.id = asset.equipment_type_id
                AND eqtype.project_id = link.project_id
               WHERE link.project_id=? AND link.scenario_id=?""",
            (project_id, scenario_id),
        ).fetchall()

        placed_by_work: dict[str, list[dict]] = {}
        for r in placed_rows:
            placed_by_work.setdefault(str(r["work_element_id"]), []).append(dict(r))

        torque_linked_req_ids = {
            str(r[0])
            for r in conn.execute(
                """SELECT quality_requirement_id FROM equipment_torque_requirement_links
                   WHERE project_id=?""",
                (project_id,),
            ).fetchall()
        }

        assignments = conn.execute(
            """SELECT a.id AS assignment_id, a.work_element_id, a.quality_requirement_id,
                      a.requirement_type, a.description, a.unique_identifier,
                      a.target_value, a.tolerances, a.unit
               FROM quality_requirement_assignments a
               WHERE a.project_id=? AND a.scenario_id=?""",
            (project_id, scenario_id),
        ).fetchall()

        matrix_records: list[dict] = []
        drawing_matched_keys: set[tuple[str, str]] = set()

        for a in assignments:
            work_id = str(a["work_element_id"])
            req_type = _text(a["requirement_type"])
            desc = _text(a["description"])
            uid = _text(a["unique_identifier"])
            target = _text(a["target_value"])
            tol = _text(a["tolerances"])
            unit = _text(a["unit"])
            req_id = str(a["quality_requirement_id"])

            expected_type = ""
            if req_type.casefold() == "torque" or "torque" in desc.casefold():
                expected_type = "Torque tool"
            elif "vision" in req_type.casefold() or "vision" in desc.casefold():
                expected_type = "Vision equipment"
            elif "esd" in req_type.casefold() or "esd" in desc.casefold():
                expected_type = "ESD equipment"
            elif "scan" in req_type.casefold() or "scan" in desc.casefold():
                expected_type = "Scan/Compare equipment"
            elif "test" in req_type.casefold() or "test" in desc.casefold():
                expected_type = "Test equipment"

            if not expected_type:
                continue

            op_ctx = op_contexts.get(work_id, {})
            op_id = _text(op_ctx.get("op_id")) or "Op ID unavailable"
            pitch_st = _text(op_ctx.get("pitch_number")) or _text(op_ctx.get("station")) or "Unassigned"
            op_text = _text(op_ctx.get("operation"))

            spec_parts = [p for p in [uid, desc, target, tol, unit] if p]
            spec_str = " — ".join(spec_parts) if spec_parts else f"{req_type} Requirement"

            placed_assets = placed_by_work.get(work_id, [])
            matching_assets = [
                eq["asset_name"] for eq in placed_assets
                if _text(eq.get("equipment_type")).casefold() == expected_type.casefold()
                or (expected_type == "Torque tool" and "torque" in _text(eq.get("equipment_type")).casefold())
            ]
            if req_id in torque_linked_req_ids and expected_type == "Torque tool":
                t_rows = conn.execute(
                    """SELECT asset.name FROM equipment_torque_requirement_links link
                       JOIN equipment_assets asset ON asset.id=link.equipment_id
                       WHERE link.project_id=? AND link.quality_requirement_id=?""",
                    (project_id, req_id),
                ).fetchall()
                for tr in t_rows:
                    aname = _text(tr[0])
                    if aname and aname not in matching_assets:
                        matching_assets.append(aname)

            is_satisfied = len(matching_assets) > 0
            matrix_records.append({
                "work_element_id": work_id,
                "op_id": op_id,
                "pitch_station": pitch_st,
                "operation": op_text,
                "source_stage": "Drawing Requirement",
                "requirement_control_desc": spec_str,
                "expected_equipment_type": expected_type,
                "linked_asset_names": ", ".join(matching_assets) if is_satisfied else "⚠️ [No Asset Attached]",
                "coverage_status": "Satisfied" if is_satisfied else "Missing Equipment",
                "is_satisfied": is_satisfied,
            })
            drawing_matched_keys.add((work_id, expected_type.casefold()))

        pfmea_items = conn.execute(
            """SELECT item.*, entry.work_element_id, entry.process_operation_snapshot
               FROM control_plan_items item
               JOIN pfmea_entries entry ON entry.id=item.pfmea_entry_id
               WHERE item.project_id=? AND item.scenario_id=? AND item.excluded=0""",
            (project_id, scenario_id),
        ).fetchall()

        for item in pfmea_items:
            item_dict = dict(item)
            work_id = str(item_dict.get("work_element_id") or "")
            method = _text(item_dict.get("control_method"))
            if not method:
                continue

            m_lower = method.lower()
            expected_type = ""
            if "vision" in m_lower:
                expected_type = "Vision equipment"
            elif "scan" in m_lower or "genealogy" in m_lower or "plc" in m_lower:
                expected_type = "Scan/Compare equipment"
            elif "poka" in m_lower or "fixture" in m_lower:
                expected_type = "Poka-Yoke / Fixture equipment"
            elif "esd" in m_lower or "frm-ap1-qys-029" in m_lower:
                expected_type = "ESD equipment"
            elif "torque" in m_lower:
                expected_type = "Torque tool"
            elif "test" in m_lower:
                expected_type = "Test equipment"

            if not expected_type:
                continue

            if (work_id, expected_type.casefold()) in drawing_matched_keys:
                continue

            op_ctx = op_contexts.get(work_id, {})
            op_id = _text(op_ctx.get("op_id")) or "Op ID unavailable"
            pitch_st = _text(op_ctx.get("pitch_number")) or _text(op_ctx.get("station")) or "Unassigned"
            op_text = _text(op_ctx.get("operation")) or _text(item_dict.get("process_operation_snapshot"))

            placed_assets = placed_by_work.get(work_id, [])
            matching_assets = [
                eq["asset_name"] for eq in placed_assets
                if _text(eq.get("equipment_type")).casefold() == expected_type.casefold()
            ]
            is_satisfied = len(matching_assets) > 0

            matrix_records.append({
                "work_element_id": work_id,
                "op_id": op_id,
                "pitch_station": pitch_st,
                "operation": op_text,
                "source_stage": "PFMEA Control",
                "requirement_control_desc": method,
                "expected_equipment_type": expected_type,
                "linked_asset_names": ", ".join(matching_assets) if is_satisfied else "⚠️ [No Asset Attached]",
                "coverage_status": "Satisfied" if is_satisfied else "Missing Equipment",
                "is_satisfied": is_satisfied,
            })

    df = pd.DataFrame(matrix_records)
    if df.empty:
        return pd.DataFrame(columns=[
            "work_element_id", "op_id", "pitch_station", "operation",
            "source_stage", "requirement_control_desc", "expected_equipment_type",
            "linked_asset_names", "coverage_status", "is_satisfied",
        ])
    return df.sort_values(by=["op_id", "source_stage"], kind="stable").reset_index(drop=True)


@cached_store_read
def conveyor_zones(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Return scenario conveyor zones with dynamic pitch count and length calculations."""
    store = _store_module()
    rows = store.query(
        """SELECT z.*,
                  p_start.pitch_number AS start_pitch_number,
                  p_end.pitch_number AS end_pitch_number
           FROM conveyor_zones z
           LEFT JOIN yamazumi_pitches p_start ON p_start.id=z.start_pitch_id
           LEFT JOIN yamazumi_pitches p_end ON p_end.id=z.end_pitch_id
           WHERE z.project_id=? AND z.scenario_id=?
           ORDER BY z.sequence, z.name COLLATE NOCASE, z.id""",
        (project_id, scenario_id),
    )
    all_pitches = store.query(
        """SELECT p.id, p.pitch_number, p.sequence, p.conveyor_zone_id
           FROM yamazumi_pitches p
           JOIN yamazumi_areas area ON area.id=p.area_id
           LEFT JOIN assembly_sections sec ON sec.id=area.section_id
           WHERE p.project_id=? AND area.scenario_id=? AND p.status='Active'
           ORDER BY COALESCE(sec.sequence, 0), area.name COLLATE NOCASE, p.sequence, p.pitch_number COLLATE NOCASE""",
        (project_id, scenario_id),
    )
    pitch_ids = [str(r["id"]) for r in all_pitches]

    records = []
    for r in rows:
        d = dict(r)
        zone_id = str(d.get("id"))
        start_id = _text(d.get("start_pitch_id"))
        end_id = _text(d.get("end_pitch_id"))

        # Explicitly assigned pitches via yamazumi_pitches.conveyor_zone_id
        directly_assigned = [p for p in all_pitches if _text(p.get("conveyor_zone_id")) == zone_id]
        if directly_assigned:
            active_count = len(directly_assigned)
            d["assigned_pitch_numbers"] = ", ".join(str(p["pitch_number"]) for p in directly_assigned)
            d["assigned_pitch_ids"] = [str(p["id"]) for p in directly_assigned]
            if not d.get("start_pitch_number"):
                d["start_pitch_id"] = str(directly_assigned[0]["id"])
                d["start_pitch_number"] = str(directly_assigned[0]["pitch_number"])
            if not d.get("end_pitch_number"):
                d["end_pitch_id"] = str(directly_assigned[-1]["id"])
                d["end_pitch_number"] = str(directly_assigned[-1]["pitch_number"])
        elif start_id in pitch_ids and end_id in pitch_ids:
            idx1 = pitch_ids.index(start_id)
            idx2 = pitch_ids.index(end_id)
            if idx1 <= idx2:
                sp_ids = pitch_ids[idx1 : idx2 + 1]
            else:
                sp_ids = pitch_ids[idx2 : idx1 + 1]
            active_count = len(sp_ids)
            matched = [p for p in all_pitches if str(p["id"]) in sp_ids]
            d["assigned_pitch_numbers"] = ", ".join(str(p["pitch_number"]) for p in matched)
            d["assigned_pitch_ids"] = sp_ids
        elif start_id in pitch_ids:
            idx1 = pitch_ids.index(start_id)
            sp_ids = pitch_ids[idx1:]
            active_count = len(sp_ids)
            matched = [p for p in all_pitches if str(p["id"]) in sp_ids]
            d["assigned_pitch_numbers"] = ", ".join(str(p["pitch_number"]) for p in matched)
            d["assigned_pitch_ids"] = sp_ids
        elif end_id in pitch_ids:
            idx2 = pitch_ids.index(end_id)
            sp_ids = pitch_ids[: idx2 + 1]
            active_count = len(sp_ids)
            matched = [p for p in all_pitches if str(p["id"]) in sp_ids]
            d["assigned_pitch_numbers"] = ", ".join(str(p["pitch_number"]) for p in matched)
            d["assigned_pitch_ids"] = sp_ids
        else:
            active_count = len(pitch_ids) if len(rows) == 1 else 0
            if active_count > 0:
                d["assigned_pitch_numbers"] = ", ".join(str(p["pitch_number"]) for p in all_pitches)
                d["assigned_pitch_ids"] = pitch_ids
            else:
                d["assigned_pitch_numbers"] = ""
                d["assigned_pitch_ids"] = []

        helper_count = int(d.get("helper_pitch_count") or 0)
        growth_count = int(d.get("growth_pitch_count") or 0)
        pitch_len_in = float(d.get("standard_pitch_length_in") or 120.0)
        monument_in = float(d.get("monument_length_in") or 0.0)

        total_pitches = active_count + helper_count + growth_count
        total_len_in = (total_pitches * pitch_len_in) + monument_in
        total_len_ft = round(total_len_in / 12.0, 1)

        d["active_pitch_count"] = active_count
        d["total_pitch_count"] = total_pitches
        d["calculated_total_length_in"] = round(total_len_in, 1)
        d["calculated_total_length_ft"] = total_len_ft
        records.append(d)

    frame = pd.DataFrame(records, columns=CONVEYOR_ZONE_COLUMNS)
    if frame.empty:
        return pd.DataFrame(columns=CONVEYOR_ZONE_COLUMNS)
    return frame


def save_conveyor_zone(
    project_id: str,
    scenario_id: str,
    record: dict,
    editor_name: str,
) -> dict[str, object]:
    """Save or update a Conveyor Zone with ergonomic dimensions and pitch bounds."""
    store = _store_module()
    editor = _require_editor(editor_name)
    name = _text(record.get("name"))
    if not name:
        raise ValueError("Conveyor Zone name is required.")

    zone_id = _text(record.get("id")) or str(uuid4())
    sequence = int(record.get("sequence") or 10)

    raw_pitch_ids = record.get("pitch_ids") if "pitch_ids" in record else record.get("assigned_pitch_ids")
    if raw_pitch_ids is not None:
        pitch_ids = [_text(pid) for pid in raw_pitch_ids if _text(pid)]
        start_pitch_id = pitch_ids[0] if pitch_ids else None
        end_pitch_id = pitch_ids[-1] if pitch_ids else None
    else:
        pitch_ids = None
        start_pitch_id = _text(record.get("start_pitch_id")) or None
        end_pitch_id = _text(record.get("end_pitch_id")) or None

    height_in = record.get("conveyor_height_in")
    conveyor_height_in = float(height_in) if height_in not in (None, "", "None") else None
    if conveyor_height_in is not None and conveyor_height_in <= 0:
        raise ValueError("Conveyor height must be a positive number in inches.")

    width_in = record.get("conveyor_width_in")
    conveyor_width_in = float(width_in) if width_in not in (None, "", "None") else None
    if conveyor_width_in is not None and conveyor_width_in <= 0:
        raise ValueError("Conveyor width must be a positive number in inches.")

    unit_orientation = _text(record.get("unit_orientation"))
    orientation_image_path = _text(record.get("orientation_image_path"))

    standard_pitch_length_in = float(record.get("standard_pitch_length_in") or 120.0)
    if standard_pitch_length_in <= 0:
        raise ValueError("Standard pitch length must be greater than 0 inches.")

    helper_pitch_count = max(0, int(record.get("helper_pitch_count") or 0))
    growth_pitch_count = max(0, int(record.get("growth_pitch_count") or 0))
    monument_length_in = max(0.0, float(record.get("monument_length_in") or 0.0))
    notes = _text(record.get("notes"))
    timestamp = store.now_iso()

    with store.connection() as conn:
        existing = conn.execute(
            "SELECT id FROM conveyor_zones WHERE id=? AND project_id=? AND scenario_id=?",
            (zone_id, project_id, scenario_id),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE conveyor_zones
                   SET name=?, sequence=?, start_pitch_id=?, end_pitch_id=?,
                       conveyor_height_in=?, conveyor_width_in=?, unit_orientation=?,
                       orientation_image_path=?, standard_pitch_length_in=?,
                       helper_pitch_count=?, growth_pitch_count=?, monument_length_in=?,
                       notes=?, updated_at=?
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (
                    name, sequence, start_pitch_id, end_pitch_id,
                    conveyor_height_in, conveyor_width_in, unit_orientation,
                    orientation_image_path, standard_pitch_length_in,
                    helper_pitch_count, growth_pitch_count, monument_length_in,
                    notes, timestamp, zone_id, project_id, scenario_id,
                ),
            )
            action = "Update conveyor zone"
        else:
            conn.execute(
                """INSERT INTO conveyor_zones
                   (id, project_id, scenario_id, name, sequence, start_pitch_id, end_pitch_id,
                    conveyor_height_in, conveyor_width_in, unit_orientation, orientation_image_path,
                    standard_pitch_length_in, helper_pitch_count, growth_pitch_count,
                    monument_length_in, notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    zone_id, project_id, scenario_id, name, sequence, start_pitch_id, end_pitch_id,
                    conveyor_height_in, conveyor_width_in, unit_orientation, orientation_image_path,
                    standard_pitch_length_in, helper_pitch_count, growth_pitch_count,
                    monument_length_in, notes, timestamp, timestamp,
                ),
            )
            action = "Create conveyor zone"

        if pitch_ids is not None:
            if pitch_ids:
                placeholders = ",".join("?" * len(pitch_ids))
                conn.execute(
                    f"""UPDATE yamazumi_pitches
                       SET conveyor_zone_id=?, updated_at=?
                       WHERE project_id=? AND id IN ({placeholders})""",
                    (zone_id, timestamp, project_id, *pitch_ids),
                )
                conn.execute(
                    f"""UPDATE yamazumi_pitches
                       SET conveyor_zone_id=NULL, updated_at=?
                       WHERE project_id=? AND conveyor_zone_id=? AND id NOT IN ({placeholders})""",
                    (timestamp, project_id, zone_id, *pitch_ids),
                )
            else:
                conn.execute(
                    """UPDATE yamazumi_pitches
                       SET conveyor_zone_id=NULL, updated_at=?
                       WHERE project_id=? AND conveyor_zone_id=?""",
                    (timestamp, project_id, zone_id),
                )

        store.record_audit_event(
            project_id,
            "Conveyor zones",
            action,
            1,
            editor,
            {
                "zone_id": zone_id,
                "name": name,
                "scenario_id": scenario_id,
                "conveyor_height_in": conveyor_height_in,
                "conveyor_width_in": conveyor_width_in,
                "unit_orientation": unit_orientation,
                "store_timestamp": timestamp,
            },
            _conn=conn,
        )

    return {"zone_id": zone_id, "id": zone_id, "timestamp": timestamp}


def batch_assign_pitches_to_conveyor_zone(
    project_id: str,
    scenario_id: str,
    pitch_ids: list[str],
    conveyor_zone_id: str | None,
    editor_name: str,
) -> dict[str, object]:
    """Assign or unassign a batch of pitches to a conveyor zone."""
    store = _store_module()
    editor = _require_editor(editor_name)
    timestamp = store.now_iso()
    clean_pids = [_text(p) for p in pitch_ids if _text(p)]
    if not clean_pids:
        return {"updated_count": 0, "timestamp": timestamp}
    clean_zone_id = _text(conveyor_zone_id) or None
    with store.connection() as conn:
        placeholders = ",".join("?" * len(clean_pids))
        conn.execute(
            f"""UPDATE yamazumi_pitches
               SET conveyor_zone_id=?, updated_at=?
               WHERE project_id=? AND id IN ({placeholders})""",
            (clean_zone_id, timestamp, project_id, *clean_pids),
        )
        store.record_audit_event(
            project_id,
            "Pitch ergonomics",
            "Batch assign conveyor zone",
            len(clean_pids),
            editor,
            {
                "scenario_id": scenario_id,
                "conveyor_zone_id": clean_zone_id,
                "pitch_count": len(clean_pids),
                "store_timestamp": timestamp,
            },
            _conn=conn,
        )
    return {"updated_count": len(clean_pids), "timestamp": timestamp}


def delete_conveyor_zones(
    project_id: str,
    scenario_id: str,
    zone_ids: list[str],
    editor_name: str,
) -> dict[str, object]:
    """Delete conveyor zones and clean up associated image uploads."""
    store = _store_module()
    editor = _require_editor(editor_name)
    normalized = list(dict.fromkeys(_text(z) for z in zone_ids if _text(z)))
    if not normalized:
        return {"row_count": 0, "timestamp": store.now_iso()}
    placeholders = ",".join("?" for _ in normalized)
    timestamp = store.now_iso()
    with store.connection() as conn:
        rows = conn.execute(
            f"SELECT id, name, orientation_image_path FROM conveyor_zones WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})",
            (project_id, scenario_id, *normalized),
        ).fetchall()
        for r in rows:
            img = _text(r["orientation_image_path"])
            if img:
                store._remove_owned_upload(img)
        conn.execute(
            f"UPDATE yamazumi_pitches SET conveyor_zone_id=NULL WHERE conveyor_zone_id IN ({placeholders})",
            tuple(normalized),
        )
        conn.execute(
            f"DELETE FROM conveyor_zones WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})",
            (project_id, scenario_id, *normalized),
        )
        store.record_audit_event(
            project_id,
            "Conveyor zones",
            "Delete conveyor zone(s)",
            len(normalized),
            editor,
            {
                "zone_ids": normalized,
                "names": [str(r["name"]) for r in rows],
                "store_timestamp": timestamp,
            },
            _conn=conn,
        )
    return {"row_count": len(normalized), "timestamp": timestamp}


def set_conveyor_zone_image(
    project_id: str,
    scenario_id: str,
    zone_id: str,
    uploaded_file,
    editor_name: str,
) -> str:
    """Save an illustrative unit orientation image for a conveyor zone."""
    store = _store_module()
    editor = _require_editor(editor_name)
    suffix = Path(str(getattr(uploaded_file, "name", "image.png"))).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Use PNG, JPG, JPEG, or WEBP images.")
    content = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
    if not content:
        raise ValueError("Choose a non-empty image.")
    try:
        from io import BytesIO
        with Image.open(BytesIO(content)) as image:
            image.verify()
    except Exception as exc:
        raise ValueError("The selected file is not a readable image.") from exc

    target = store.UPLOAD_DIR / f"zone_orientation_{zone_id}_{uuid4()}{suffix}"
    target.write_bytes(content)
    timestamp = store.now_iso()
    previous = ""
    try:
        with store.connection() as conn:
            row = conn.execute(
                "SELECT orientation_image_path FROM conveyor_zones WHERE id=? AND project_id=? AND scenario_id=?",
                (zone_id, project_id, scenario_id),
            ).fetchone()
            if not row:
                raise ValueError("That conveyor zone no longer exists.")
            previous = _text(row["orientation_image_path"])
            conn.execute(
                "UPDATE conveyor_zones SET orientation_image_path=?, updated_at=? WHERE id=? AND project_id=? AND scenario_id=?",
                (str(target), timestamp, zone_id, project_id, scenario_id),
            )
            store.record_audit_event(
                project_id,
                "Conveyor zones",
                "Save orientation visual",
                1,
                editor,
                {"zone_id": zone_id, "store_timestamp": timestamp},
                _conn=conn,
            )
    except Exception:
        store._remove_owned_upload(target)
        raise
    if previous and previous != str(target):
        store._remove_owned_upload(previous)
    return str(target)


def delete_conveyor_zone_image(
    project_id: str,
    scenario_id: str,
    zone_id: str,
    editor_name: str,
) -> None:
    """Delete an orientation image for a conveyor zone."""
    store = _store_module()
    editor = _require_editor(editor_name)
    timestamp = store.now_iso()
    previous = ""
    with store.connection() as conn:
        row = conn.execute(
            "SELECT orientation_image_path FROM conveyor_zones WHERE id=? AND project_id=? AND scenario_id=?",
            (zone_id, project_id, scenario_id),
        ).fetchone()
        if not row:
            raise ValueError("That conveyor zone no longer exists.")
        previous = _text(row["orientation_image_path"])
        conn.execute(
            "UPDATE conveyor_zones SET orientation_image_path='', updated_at=? WHERE id=? AND project_id=? AND scenario_id=?",
            (timestamp, zone_id, project_id, scenario_id),
        )
        store.record_audit_event(
            project_id,
            "Conveyor zones",
            "Delete orientation visual",
            1,
            editor,
            {"zone_id": zone_id, "store_timestamp": timestamp},
            _conn=conn,
        )
    if previous:
        store._remove_owned_upload(previous)


@cached_store_read
def scenario_pitches_ergonomics_geometry(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Return workstation pitches with their platform elevation, pit depth, and assigned zone."""
    store = _store_module()
    rows = store.query(
        """SELECT p.id, p.pitch_number, p.pitch_name, p.status, p.sequence,
                  p.platform_height_in, p.pit_depth_in, p.conveyor_zone_id,
                  z.name AS zone_name, z.conveyor_height_in, z.conveyor_width_in, z.unit_orientation,
                  area.name AS area_name
           FROM yamazumi_pitches p
           JOIN yamazumi_areas area ON area.id=p.area_id
           LEFT JOIN assembly_sections sec ON sec.id=area.section_id
           LEFT JOIN conveyor_zones z ON z.id=p.conveyor_zone_id
           WHERE p.project_id=? AND area.scenario_id=?
           ORDER BY COALESCE(sec.sequence, 0), area.name COLLATE NOCASE, p.sequence, p.pitch_number COLLATE NOCASE""",
        (project_id, scenario_id),
    )
    cols = [
        "id", "pitch_number", "pitch_name", "status", "sequence", "area_name",
        "platform_height_in", "pit_depth_in", "conveyor_zone_id", "zone_name",
        "conveyor_height_in", "conveyor_width_in", "unit_orientation",
    ]
    frame = pd.DataFrame(rows, columns=cols)
    if not frame.empty:
        frame["platform_height_in"] = pd.to_numeric(frame["platform_height_in"], errors="coerce").fillna(0.0)
        frame["pit_depth_in"] = pd.to_numeric(frame["pit_depth_in"], errors="coerce").fillna(0.0)
    return frame


def save_pitch_ergonomics_geometry(
    project_id: str,
    scenario_id: str,
    records: list[dict],
    editor_name: str,
) -> dict[str, object]:
    """Save platform height, pit depth, and conveyor zone assignments for pitches."""
    store = _store_module()
    editor = _require_editor(editor_name)
    timestamp = store.now_iso()
    count = 0
    with store.connection() as conn:
        for r in records:
            p_id = _text(r.get("id") or r.get("pitch_id"))
            if not p_id:
                continue
            plat = float(r.get("platform_height_in") or 0.0)
            pit = float(r.get("pit_depth_in") or 0.0)
            zone_id = _text(r.get("conveyor_zone_id")) or None

            conn.execute(
                """UPDATE yamazumi_pitches
                   SET platform_height_in=?, pit_depth_in=?, conveyor_zone_id=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (plat, pit, zone_id, timestamp, p_id, project_id),
            )
            count += 1

        if count:
            store.record_audit_event(
                project_id,
                "Pitch ergonomics",
                "Save Platforms & Pits",
                count,
                editor,
                {"scenario_id": scenario_id, "updated_count": count, "store_timestamp": timestamp},
                _conn=conn,
            )
    return {"row_count": count, "timestamp": timestamp}


@cached_store_read
def scenario_conveyor_line_sizing(project_id: str, scenario_id: str) -> dict[str, object]:
    """Calculate aggregate conveyor line sizing across zones and active pitches."""
    store = _store_module()
    zones_df = conveyor_zones(project_id, scenario_id)
    all_active_pitches_rows = store.query(
        """SELECT COUNT(*) AS total FROM yamazumi_pitches p
           JOIN yamazumi_areas area ON area.id=p.area_id
           WHERE p.project_id=? AND area.scenario_id=? AND p.status='Active'""",
        (project_id, scenario_id),
    )
    all_active_pitches = all_active_pitches_rows[0]["total"] if all_active_pitches_rows else 0

    if zones_df.empty:
        active_pitches = int(all_active_pitches)
        std_len_in = 120.0
        total_len_in = active_pitches * std_len_in
        return {
            "zone_count": 0,
            "active_pitches": active_pitches,
            "helper_pitches": 0,
            "growth_pitches": 0,
            "total_pitches": active_pitches,
            "standard_pitch_length_in": std_len_in,
            "monument_length_in": 0.0,
            "total_length_in": round(total_len_in, 1),
            "total_length_ft": round(total_len_in / 12.0, 1),
        }

    active_p = int(zones_df["active_pitch_count"].sum())
    helper_p = int(zones_df["helper_pitch_count"].sum())
    growth_p = int(zones_df["growth_pitch_count"].sum())
    monument_in = float(zones_df["monument_length_in"].sum())
    total_len_in = float(zones_df["calculated_total_length_in"].sum())
    total_pitches = active_p + helper_p + growth_p

    return {
        "zone_count": len(zones_df),
        "active_pitches": active_p,
        "helper_pitches": helper_p,
        "growth_pitches": growth_p,
        "total_pitches": total_pitches,
        "standard_pitch_length_in": float(zones_df["standard_pitch_length_in"].iloc[0]),
        "monument_length_in": monument_in,
        "total_length_in": round(total_len_in, 1),
        "total_length_ft": round(total_len_in / 12.0, 1),
    }


