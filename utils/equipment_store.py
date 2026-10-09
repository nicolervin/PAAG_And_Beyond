"""Persistence and validation for the shared Functional Review Equipment catalog."""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path
from uuid import uuid4

import pandas as pd
from PIL import Image


EQUIPMENT_FUNCTION_AREAS = (
    "Quality",
    "Ergonomics",
    "Safety",
    "Materials",
    "Assembly",
)

DEFAULT_EQUIPMENT_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Torque tool", ("Quality",)),
    ("Handheld equipment", ("Assembly", "Quality")),
    ("ESD equipment", ("Quality",)),
    ("Vision equipment", ("Quality",)),
    ("Scan/Compare equipment", ("Quality",)),
    ("Test equipment", ("Quality",)),
    ("Dimensional measurement equipment", ("Quality",)),
    ("Poka-Yoke / Fixture equipment", ("Quality", "Assembly")),
    ("Conveyor", ("Assembly",)),
)

EQUIPMENT_TYPE_COLUMNS = [
    "id", "project_id", "label", "functional_areas", "created_at", "updated_at",
]
EQUIPMENT_COLUMNS = [
    "id", "project_id", "equipment_type_id", "equipment_type", "name",
    "description", "manufacturer", "model", "notes", "image_path",
    "functional_areas", "placement_id", "pitch_id", "pitch_number", "pitch_name",
    "process_link_count", "torque_requirement_count", "created_at", "updated_at",
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
        """
    )
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
    for label, functional_areas in DEFAULT_EQUIPMENT_TYPES:
        if label.strip().casefold() in existing_types:
            continue
        type_id = str(uuid4())
        conn.execute(
            """INSERT INTO equipment_types
               (id, project_id, label, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (type_id, project_id, label, timestamp, timestamp),
        )
        for functional_area in functional_areas:
            conn.execute(
                """INSERT INTO equipment_type_function_links
                   (id, project_id, equipment_type_id, functional_area, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), project_id, type_id, functional_area, timestamp, timestamp),
            )
        existing_types.add(label.strip().casefold())


def equipment_types(project_id: str, functional_area: str | None = None) -> pd.DataFrame:
    store = _store_module()
    with store.connection() as conn:
        _ensure_default_equipment_types(conn, project_id)
        area_filter = " AND EXISTS (SELECT 1 FROM equipment_type_function_links f WHERE f.equipment_type_id=t.id AND f.functional_area=?)" if functional_area else ""
        params = (project_id, functional_area) if functional_area else (project_id,)
        rows = conn.execute(
            f"""SELECT t.*,
                       COALESCE(GROUP_CONCAT(f.functional_area, ', '), '') AS functional_areas
                FROM equipment_types t
                LEFT JOIN equipment_type_function_links f ON f.equipment_type_id=t.id
                WHERE t.project_id=?{area_filter}
                GROUP BY t.id
                ORDER BY t.label COLLATE NOCASE, t.id""",
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
        functional_areas = _list(record.get("functional_areas"))
        invalid = [value for value in functional_areas if value not in EQUIPMENT_FUNCTION_AREAS]
        if invalid:
            raise ValueError("Choose only approved Functional Reviews for each Equipment Type.")
        if not functional_areas:
            raise ValueError("Choose at least one Functional Review for each Equipment Type.")
        cleaned.append({"id": _text(record.get("id")), "label": label, "functional_areas": functional_areas})

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
                changed = _text(old["label"]) != record["label"] or old_areas != set(record["functional_areas"])
                if changed:
                    conn.execute(
                        "UPDATE equipment_types SET label=?, updated_at=? WHERE id=? AND project_id=?",
                        (record["label"], timestamp, type_id, project_id),
                    )
                    changed_ids.append(type_id)
            else:
                conn.execute(
                    """INSERT INTO equipment_types
                       (id, project_id, label, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (type_id, project_id, record["label"], timestamp, timestamp),
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
            ORDER BY type.label COLLATE NOCASE, asset.name COLLATE NOCASE, asset.id""",
        tuple(params),
    )
    frame = pd.DataFrame(rows, columns=EQUIPMENT_COLUMNS)
    if not frame.empty:
        frame["functional_areas"] = frame["functional_areas"].map(_list)
        frame["process_link_count"] = pd.to_numeric(frame["process_link_count"], errors="coerce").fillna(0).astype(int)
        frame["torque_requirement_count"] = pd.to_numeric(frame["torque_requirement_count"], errors="coerce").fillna(0).astype(int)
    return frame


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


def equipment_needs_vs_placements_matrix(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Return a unified Equipment Needs vs Placements matrix DataFrame."""
    store = _store_module()
    with store.connection() as conn:
        init_equipment_schema(conn)

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

