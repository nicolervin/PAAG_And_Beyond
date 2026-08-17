from __future__ import annotations

import sqlite3
import json
import hashlib
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "paag.db"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def connection():
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, program TEXT DEFAULT '',
                product_line TEXT DEFAULT '',
                owner TEXT DEFAULT '', revision TEXT DEFAULT 'A', status TEXT DEFAULT 'Draft',
                takt_time_s REAL DEFAULT 60, notes TEXT DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS planning_scenarios (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL, revision_label TEXT NOT NULL,
                revision_sequence INTEGER NOT NULL DEFAULT 1,
                parent_scenario_id TEXT REFERENCES planning_scenarios(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'Working', takt_time_s REAL NOT NULL DEFAULT 60,
                change_summary TEXT DEFAULT '', created_by TEXT DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(project_id, name), UNIQUE(project_id, revision_label)
            );
            CREATE TABLE IF NOT EXISTS parts (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                part_number TEXT NOT NULL, description TEXT DEFAULT '', quantity REAL DEFAULT 1,
                revision TEXT DEFAULT '', source TEXT DEFAULT 'Manual', image_path TEXT DEFAULT '',
                model_applicability TEXT DEFAULT 'All', notes TEXT DEFAULT '', updated_at TEXT NOT NULL,
                UNIQUE(project_id, part_number)
            );
            CREATE TABLE IF NOT EXISTS work_elements (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                scenario_id TEXT REFERENCES planning_scenarios(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL, station TEXT DEFAULT '', operation TEXT NOT NULL,
                description TEXT DEFAULT '', cycle_time_s REAL DEFAULT 0,
                part_number TEXT DEFAULT '', tool TEXT DEFAULT '', torque TEXT DEFAULT '',
                quality_requirement TEXT DEFAULT '', ergo_requirement TEXT DEFAULT '',
                location TEXT DEFAULT '', conveyor_height_mm REAL, platform_height_mm REAL,
                pit_depth_mm REAL, model_applicability TEXT DEFAULT 'All', status TEXT DEFAULT 'Draft',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS concerns (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                category TEXT DEFAULT 'Question', subject TEXT NOT NULL, detail TEXT DEFAULT '',
                owner TEXT DEFAULT '', priority TEXT DEFAULT 'Medium', status TEXT DEFAULT 'Open',
                related_part TEXT DEFAULT '', related_station TEXT DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fishbone_nodes (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                source_row INTEGER, sequence INTEGER NOT NULL, parent_id TEXT,
                depth INTEGER DEFAULT 1, part_number TEXT DEFAULT '', description TEXT DEFAULT '',
                quantity REAL DEFAULT 1, branch_name TEXT DEFAULT '', subsystem TEXT DEFAULT '',
                model_feature TEXT DEFAULT '', comments TEXT DEFAULT '', tracker_status TEXT DEFAULT '',
                planned_area TEXT DEFAULT '', source TEXT DEFAULT 'Manual', raw_levels TEXT DEFAULT '{}',
                review_status TEXT DEFAULT 'Confirmed',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS part_images (
                id TEXT PRIMARY KEY, part_id TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                image_path TEXT NOT NULL, image_type TEXT DEFAULT 'Supplemental', caption TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pits_records (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                pits_id TEXT NOT NULL, part_number TEXT DEFAULT '', description TEXT DEFAULT '',
                used_bom TEXT DEFAULT '', status TEXT DEFAULT '', subsystem TEXT DEFAULT '',
                design_maturity TEXT DEFAULT '', comments TEXT DEFAULT '', workstation TEXT DEFAULT '',
                source_payload TEXT NOT NULL, source_hash TEXT NOT NULL, revision_no INTEGER DEFAULT 1,
                first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                UNIQUE(project_id, pits_id)
            );
            CREATE TABLE IF NOT EXISTS pits_record_revisions (
                id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES pits_records(id) ON DELETE CASCADE,
                revision_no INTEGER NOT NULL, source_payload TEXT NOT NULL, imported_at TEXT NOT NULL,
                UNIQUE(record_id, revision_no)
            );
            CREATE TABLE IF NOT EXISTS project_models (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                model_number TEXT NOT NULL, item TEXT DEFAULT '', platform_size TEXT DEFAULT '',
                package_type TEXT DEFAULT '', appearance TEXT DEFAULT '', base_model TEXT DEFAULT '',
                eau REAL, dg_date TEXT, dc_date TEXT, pre_pilot_date TEXT, pilot_date TEXT,
                production_date TEXT, sku_upc TEXT DEFAULT '', evaluate_fishbone TEXT DEFAULT '',
                yamazumi TEXT DEFAULT '', bop_l1 TEXT DEFAULT '', source_payload TEXT NOT NULL,
                updated_at TEXT NOT NULL, display_name TEXT DEFAULT '', description TEXT DEFAULT '',
                active INTEGER DEFAULT 1, notes TEXT DEFAULT '', UNIQUE(project_id, model_number)
            );
            CREATE TABLE IF NOT EXISTS complexity_features (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                category TEXT NOT NULL DEFAULT '', name TEXT NOT NULL,
                allowed_values TEXT NOT NULL DEFAULT '[]', description TEXT DEFAULT '',
                sequence INTEGER NOT NULL DEFAULT 10, active INTEGER DEFAULT 1,
                updated_at TEXT NOT NULL, UNIQUE(project_id, name)
            );
            CREATE TABLE IF NOT EXISTS model_feature_values (
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                model_id TEXT NOT NULL REFERENCES project_models(id) ON DELETE CASCADE,
                feature_id TEXT NOT NULL REFERENCES complexity_features(id) ON DELETE CASCADE,
                value TEXT DEFAULT '', updated_at TEXT NOT NULL,
                PRIMARY KEY(model_id, feature_id)
            );
            CREATE TABLE IF NOT EXISTS part_feature_rules (
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                part_id TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                feature_id TEXT NOT NULL REFERENCES complexity_features(id) ON DELETE CASCADE,
                value TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(part_id, feature_id, value)
            );
            CREATE TABLE IF NOT EXISTS assembly_sections (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL, section_type TEXT NOT NULL DEFAULT 'Main spine', parent_id TEXT,
                sequence INTEGER NOT NULL DEFAULT 10, description TEXT DEFAULT '', active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(project_id, name), FOREIGN KEY(parent_id) REFERENCES assembly_sections(id)
            );
            CREATE TABLE IF NOT EXISTS fishbone_part_assignments (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                part_id TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                section_id TEXT NOT NULL REFERENCES assembly_sections(id), sequence INTEGER NOT NULL DEFAULT 10,
                quantity INTEGER NOT NULL DEFAULT 1, use_description TEXT DEFAULT '',
                notes TEXT DEFAULT '', updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                table_name TEXT NOT NULL, action TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0,
                editor_name TEXT DEFAULT '', details TEXT DEFAULT '{}', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS yamazumi_areas (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                scenario_id TEXT REFERENCES planning_scenarios(id) ON DELETE CASCADE,
                section_id TEXT REFERENCES assembly_sections(id) ON DELETE SET NULL,
                name TEXT NOT NULL, takt_override_s REAL, updated_at TEXT NOT NULL,
                UNIQUE(project_id, scenario_id, name)
            );
            CREATE TABLE IF NOT EXISTS yamazumi_pitches (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                area_id TEXT NOT NULL REFERENCES yamazumi_areas(id) ON DELETE CASCADE,
                pitch_number TEXT NOT NULL, pitch_name TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'Active',
                sequence INTEGER NOT NULL DEFAULT 10, model_variants TEXT NOT NULL DEFAULT '["Base"]',
                pitch_type TEXT NOT NULL DEFAULT 'Pitch',
                updated_at TEXT NOT NULL,
                UNIQUE(project_id, area_id, pitch_number)
            );
            CREATE TABLE IF NOT EXISTS yamazumi_elements (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                area_id TEXT NOT NULL REFERENCES yamazumi_areas(id) ON DELETE CASCADE,
                pitch_id TEXT REFERENCES yamazumi_pitches(id) ON DELETE SET NULL,
                model_variant TEXT NOT NULL DEFAULT 'Base', work_type TEXT DEFAULT 'Cycle',
                description TEXT NOT NULL, time_s REAL NOT NULL DEFAULT 0,
                work_region TEXT DEFAULT 'None', flags TEXT DEFAULT '[]', sequence INTEGER NOT NULL DEFAULT 10,
                source TEXT DEFAULT 'Manual', process_element_id TEXT,
                process_sync_status TEXT NOT NULL DEFAULT 'Needs IE review', updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS yamazumi_work_regions (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                area_id TEXT NOT NULL REFERENCES yamazumi_areas(id) ON DELETE CASCADE,
                name TEXT NOT NULL, description TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
                color TEXT NOT NULL DEFAULT '#3dcc4a',
                sequence INTEGER NOT NULL DEFAULT 10, updated_at TEXT NOT NULL,
                UNIQUE(project_id, area_id, name)
            );
            CREATE TABLE IF NOT EXISTS yamazumi_flag_definitions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL COLLATE NOCASE, description TEXT DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1, system_flag INTEGER NOT NULL DEFAULT 0,
                sequence INTEGER NOT NULL DEFAULT 10, updated_at TEXT NOT NULL,
                UNIQUE(project_id, name)
            );
            CREATE TABLE IF NOT EXISTS manufacturing_assemblies (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                assembly_number TEXT NOT NULL, name TEXT NOT NULL,
                pits_reference TEXT DEFAULT '', planning_reason TEXT NOT NULL DEFAULT 'Other',
                parent_id TEXT REFERENCES manufacturing_assemblies(id) ON DELETE SET NULL,
                active INTEGER NOT NULL DEFAULT 1, notes TEXT DEFAULT '', updated_at TEXT NOT NULL,
                UNIQUE(project_id, assembly_number)
            );
            CREATE TABLE IF NOT EXISTS assembly_scenario_policies (
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
                assembly_id TEXT NOT NULL REFERENCES manufacturing_assemblies(id) ON DELETE CASCADE,
                sourcing_decision TEXT NOT NULL DEFAULT 'Undecided', supplier TEXT DEFAULT '',
                build_area TEXT DEFAULT '', buffer_policy TEXT NOT NULL DEFAULT 'None',
                storage_location TEXT DEFAULT '', minimum_quantity REAL,
                target_quantity REAL, maximum_quantity REAL, updated_at TEXT NOT NULL,
                PRIMARY KEY(scenario_id, assembly_id)
            );
            CREATE TABLE IF NOT EXISTS work_element_material_groups (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
                yamazumi_element_id TEXT NOT NULL REFERENCES yamazumi_elements(id) ON DELETE CASCADE,
                target_assembly_id TEXT REFERENCES manufacturing_assemblies(id) ON DELETE SET NULL,
                name TEXT NOT NULL, selection_rule TEXT NOT NULL DEFAULT 'Choose one',
                quantity REAL NOT NULL DEFAULT 1, notes TEXT DEFAULT '', updated_at TEXT NOT NULL,
                UNIQUE(yamazumi_element_id, name)
            );
            CREATE TABLE IF NOT EXISTS work_element_material_options (
                id TEXT PRIMARY KEY,
                group_id TEXT NOT NULL REFERENCES work_element_material_groups(id) ON DELETE CASCADE,
                part_id TEXT REFERENCES parts(id) ON DELETE CASCADE,
                assembly_id TEXT REFERENCES manufacturing_assemblies(id) ON DELETE CASCADE,
                updated_at TEXT NOT NULL,
                CHECK ((part_id IS NOT NULL AND assembly_id IS NULL)
                    OR (part_id IS NULL AND assembly_id IS NOT NULL)),
                UNIQUE(group_id, part_id), UNIQUE(group_id, assembly_id)
            );
            CREATE TABLE IF NOT EXISTS process_part_groups (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
                work_element_id TEXT NOT NULL REFERENCES work_elements(id) ON DELETE CASCADE,
                section_id TEXT REFERENCES assembly_sections(id) ON DELETE SET NULL,
                name TEXT NOT NULL, selection_rule TEXT NOT NULL DEFAULT 'Use all',
                quantity REAL NOT NULL DEFAULT 1, notes TEXT DEFAULT '', updated_at TEXT NOT NULL,
                UNIQUE(work_element_id, name)
            );
            CREATE TABLE IF NOT EXISTS process_part_options (
                id TEXT PRIMARY KEY,
                group_id TEXT NOT NULL REFERENCES process_part_groups(id) ON DELETE CASCADE,
                part_id TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                updated_at TEXT NOT NULL,
                UNIQUE(group_id, part_id)
            );
            """
        )
        project_columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "product_line" not in project_columns:
            conn.execute("ALTER TABLE projects ADD COLUMN product_line TEXT DEFAULT ''")
        assignment_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(fishbone_part_assignments)").fetchall()
        }
        if "use_description" not in assignment_columns:
            # The original table allowed only one fishbone placement per catalog part.
            # Rebuild it so each row represents one use/installation occurrence.
            conn.executescript(
                """
                CREATE TABLE fishbone_part_assignments_new (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    part_id TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                    section_id TEXT NOT NULL REFERENCES assembly_sections(id),
                    sequence INTEGER NOT NULL DEFAULT 10,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    use_description TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                INSERT INTO fishbone_part_assignments_new
                    (id, project_id, part_id, section_id, sequence, quantity, use_description, notes, updated_at)
                SELECT id, project_id, part_id, section_id, sequence, quantity, '', notes, updated_at
                FROM fishbone_part_assignments;
                DROP TABLE fishbone_part_assignments;
                ALTER TABLE fishbone_part_assignments_new RENAME TO fishbone_part_assignments;
                """
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fishbone_assignment_part ON fishbone_part_assignments(project_id, part_id)"
        )
        fishbone_columns = {row[1] for row in conn.execute("PRAGMA table_info(fishbone_nodes)").fetchall()}
        if "review_status" not in fishbone_columns:
            conn.execute("ALTER TABLE fishbone_nodes ADD COLUMN review_status TEXT DEFAULT 'Confirmed'")
        for column, definition in {
            "pits_id": "TEXT DEFAULT ''",
            "applicable_models": "TEXT DEFAULT '[]'",
            "source_changed": "INTEGER DEFAULT 0",
        }.items():
            if column not in fishbone_columns:
                conn.execute(f"ALTER TABLE fishbone_nodes ADD COLUMN {column} {definition}")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_fishbone_project_pits_id ON fishbone_nodes(project_id, pits_id) WHERE pits_id IS NOT NULL AND pits_id <> ''"
        )
        model_columns = {row[1] for row in conn.execute("PRAGMA table_info(project_models)").fetchall()}
        for column, definition in {
            "display_name": "TEXT DEFAULT ''",
            "description": "TEXT DEFAULT ''",
            "active": "INTEGER DEFAULT 1",
            "notes": "TEXT DEFAULT ''",
        }.items():
            if column not in model_columns:
                conn.execute(f"ALTER TABLE project_models ADD COLUMN {column} {definition}")
        pitch_columns = {row[1] for row in conn.execute("PRAGMA table_info(yamazumi_pitches)").fetchall()}
        if "model_variants" not in pitch_columns:
            conn.execute("ALTER TABLE yamazumi_pitches ADD COLUMN model_variants TEXT NOT NULL DEFAULT '[\"Base\"]'")
            existing_pitches = conn.execute("SELECT id FROM yamazumi_pitches").fetchall()
            for pitch in existing_pitches:
                used = [
                    row[0] for row in conn.execute(
                        "SELECT DISTINCT model_variant FROM yamazumi_elements WHERE pitch_id=? ORDER BY model_variant",
                        (pitch["id"],),
                    ).fetchall() if str(row[0] or "").strip()
                ]
                conn.execute(
                    "UPDATE yamazumi_pitches SET model_variants=? WHERE id=?",
                    (json.dumps(used or ["Base"]), pitch["id"]),
                )
        if "pitch_type" not in pitch_columns:
            conn.execute("ALTER TABLE yamazumi_pitches ADD COLUMN pitch_type TEXT NOT NULL DEFAULT 'Pitch'")
        work_region_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(yamazumi_work_regions)").fetchall()
        }
        for column, definition in {
            "description": "TEXT DEFAULT ''",
            "active": "INTEGER NOT NULL DEFAULT 1",
        }.items():
            if column not in work_region_columns:
                conn.execute(f"ALTER TABLE yamazumi_work_regions ADD COLUMN {column} {definition}")
        if conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0:
            timestamp = now_iso()
            project_id = str(uuid4())
            conn.execute(
                """INSERT INTO projects
                   (id, name, program, product_line, owner, revision, status,
                    takt_time_s, notes, created_at, updated_at)
                   VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id, "Sample NPI launch", "Next-generation assembly",
                    "Industrial engineering", "A", "Draft", 60,
                    "Replace this sample or create a new project.", timestamp, timestamp,
                ),
            )
            sample_parts = [
                ("PN-100100", "Main housing", 1, "A"),
                ("PN-100220", "Support bracket", 1, "B"),
                ("HW-M8-025", "M8 fastener", 4, ""),
            ]
            for pn, desc, qty, rev in sample_parts:
                conn.execute(
                    "INSERT INTO parts VALUES (?, ?, ?, ?, ?, ?, 'Sample', '', 'All', '', ?)",
                    (str(uuid4()), project_id, pn, desc, qty, rev, timestamp),
                )
            sample_steps = [
                (10, "ST-010", "Load housing", "Place housing in locating fixture", 18.0, "PN-100100", "", "", "Confirm seated on all locators", "Two-hand lift review", "Main line / Zone 1", 950, 0, 0),
                (20, "ST-010", "Install bracket", "Locate bracket and hand-start four fasteners", 24.0, "PN-100220", "Nutrunner", "32 N·m ± 3", "Torque trace required", "Keep work below shoulder", "Main line / Zone 1", 950, 100, 0),
                (30, "ST-010", "Verify assembly", "Visual and torque-complete confirmation", 8.0, "HW-M8-025", "Scanner", "", "All four results pass", "", "Main line / Zone 1", 950, 100, 0),
            ]
            for row in sample_steps:
                conn.execute(
                    """INSERT INTO work_elements
                    (id, project_id, sequence, station, operation, description, cycle_time_s,
                     part_number, tool, torque, quality_requirement, ergo_requirement, location,
                     conveyor_height_mm, platform_height_mm, pit_depth_mm, model_applicability, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'All', 'Draft', ?)""",
                    (str(uuid4()), project_id, *row, timestamp),
                )

        # Every project gets one durable planning scenario. Existing databases are
        # migrated in place, preserving their current Yamazumi and Process Plan as
        # the initial scenario instead of treating the project's revision text as history.
        timestamp = now_iso()
        for project in conn.execute("SELECT * FROM projects").fetchall():
            if not conn.execute(
                "SELECT 1 FROM planning_scenarios WHERE project_id=? LIMIT 1", (project["id"],)
            ).fetchone():
                conn.execute(
                    """INSERT INTO planning_scenarios
                       (id, project_id, name, revision_label, revision_sequence, status,
                        takt_time_s, change_summary, created_by, created_at, updated_at)
                       VALUES (?, ?, 'Current plan', ?, 1, 'Working', ?,
                               'Migrated from the original project plan', ?, ?, ?)""",
                    (
                        str(uuid4()), project["id"], str(project["revision"] or "A"),
                        float(project["takt_time_s"] or 60), str(project["owner"] or ""),
                        timestamp, timestamp,
                    ),
                )

        work_columns = {row[1] for row in conn.execute("PRAGMA table_info(work_elements)").fetchall()}
        if "scenario_id" not in work_columns:
            conn.execute(
                "ALTER TABLE work_elements ADD COLUMN scenario_id TEXT REFERENCES planning_scenarios(id) ON DELETE CASCADE"
            )
        if "output_assembly_number" not in work_columns:
            conn.execute("ALTER TABLE work_elements ADD COLUMN output_assembly_number TEXT DEFAULT ''")
        if "output_assembly_name" not in work_columns:
            conn.execute("ALTER TABLE work_elements ADD COLUMN output_assembly_name TEXT DEFAULT ''")
        conn.execute(
            """UPDATE work_elements
               SET scenario_id=(SELECT id FROM planning_scenarios s
                                WHERE s.project_id=work_elements.project_id
                                ORDER BY revision_sequence, created_at LIMIT 1)
               WHERE scenario_id IS NULL OR scenario_id=''"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_elements_scenario ON work_elements(project_id, scenario_id, sequence)"
        )

        area_columns = {row[1] for row in conn.execute("PRAGMA table_info(yamazumi_areas)").fetchall()}
        if "scenario_id" not in area_columns:
            # The original UNIQUE(project_id, name) prevents two scenarios from
            # carrying the same balancing areas, so rebuild this one parent table.
            conn.commit()
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.executescript(
                """
                CREATE TABLE yamazumi_areas_new (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    scenario_id TEXT REFERENCES planning_scenarios(id) ON DELETE CASCADE,
                    section_id TEXT REFERENCES assembly_sections(id) ON DELETE SET NULL,
                    name TEXT NOT NULL, takt_override_s REAL, updated_at TEXT NOT NULL,
                    UNIQUE(project_id, scenario_id, name)
                );
                INSERT INTO yamazumi_areas_new
                    (id, project_id, scenario_id, section_id, name, takt_override_s, updated_at)
                SELECT a.id, a.project_id,
                       (SELECT s.id FROM planning_scenarios s
                        WHERE s.project_id=a.project_id
                        ORDER BY s.revision_sequence, s.created_at LIMIT 1),
                       a.section_id, a.name, a.takt_override_s, a.updated_at
                FROM yamazumi_areas a;
                DROP TABLE yamazumi_areas;
                ALTER TABLE yamazumi_areas_new RENAME TO yamazumi_areas;
                """
            )
            conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_yamazumi_areas_scenario ON yamazumi_areas(project_id, scenario_id, name)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_assembly_policy_scenario ON assembly_scenario_policies(project_id, scenario_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_material_groups_element ON work_element_material_groups(project_id, scenario_id, yamazumi_element_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_process_part_groups_element ON process_part_groups(project_id, scenario_id, work_element_id)"
        )
        material_group_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(work_element_material_groups)").fetchall()
        }
        if "target_assembly_id" not in material_group_columns:
            conn.execute(
                """ALTER TABLE work_element_material_groups
                   ADD COLUMN target_assembly_id TEXT REFERENCES manufacturing_assemblies(id) ON DELETE SET NULL"""
            )


def query(sql: str, params: tuple = ()) -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def execute(sql: str, params: tuple = ()) -> None:
    with connection() as conn:
        conn.execute(sql, params)


def projects() -> list[dict]:
    return query("SELECT * FROM projects ORDER BY updated_at DESC")


def get_project(project_id: str) -> dict | None:
    rows = query("SELECT * FROM projects WHERE id = ?", (project_id,))
    return rows[0] if rows else None


def planning_scenarios(project_id: str, include_archived: bool = False) -> list[dict]:
    archived_clause = "" if include_archived else "AND s.status <> 'Archived'"
    return query(
        f"""SELECT s.*, parent.name AS parent_name, parent.revision_label AS parent_revision_label
            FROM planning_scenarios s
            LEFT JOIN planning_scenarios parent ON parent.id=s.parent_scenario_id
            WHERE s.project_id=? {archived_clause}
            ORDER BY s.revision_sequence DESC, s.created_at DESC""",
        (project_id,),
    )


def get_planning_scenario(project_id: str, scenario_id: str) -> dict | None:
    rows = query(
        "SELECT * FROM planning_scenarios WHERE id=? AND project_id=?",
        (scenario_id, project_id),
    )
    return rows[0] if rows else None


def next_scenario_revision_label(project_id: str, current_label: str) -> str:
    """Suggest the next numeric or alphabetic label without using labels as identifiers."""
    label = str(current_label or "").strip()
    if label.isdigit():
        candidate = str(int(label) + 1)
    elif label.isalpha():
        number = 0
        for char in label.upper():
            number = number * 26 + (ord(char) - ord("A") + 1)
        number += 1
        letters: list[str] = []
        while number:
            number, remainder = divmod(number - 1, 26)
            letters.append(chr(ord("A") + remainder))
        candidate = "".join(reversed(letters))
    else:
        candidate = f"{label or 'Rev'}-2"
    used = {str(row["revision_label"]).casefold() for row in planning_scenarios(project_id, True)}
    base, suffix = candidate, 2
    while candidate.casefold() in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def update_planning_scenario(project_id: str, scenario_id: str, values: dict) -> None:
    name = str(values.get("name") or "").strip()
    revision_label = str(values.get("revision_label") or "").strip()
    status = str(values.get("status") or "Working").strip().title()
    if not name or not revision_label:
        raise ValueError("Scenario name and revision label are required.")
    if status not in {"Working", "Frozen", "Released", "Archived"}:
        raise ValueError("Choose a valid scenario status.")
    try:
        takt = float(values.get("takt_time_s"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Scenario takt time must be a number.") from exc
    if takt <= 0:
        raise ValueError("Scenario takt time must be greater than zero.")
    try:
        execute(
            """UPDATE planning_scenarios
               SET name=?, revision_label=?, status=?, takt_time_s=?, change_summary=?, updated_at=?
               WHERE id=? AND project_id=?""",
            (
                name, revision_label, status, takt,
                str(values.get("change_summary") or "").strip(), now_iso(), scenario_id, project_id,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Scenario names and revision labels must be unique within this project.") from exc


def clone_planning_scenario(
    project_id: str,
    source_scenario_id: str,
    name: str,
    revision_label: str,
    takt_time_s: float,
    change_summary: str = "",
    created_by: str = "",
) -> str:
    """Clone a complete balancing branch and preserve its internal lineage links."""
    name = str(name or "").strip()
    revision_label = str(revision_label or "").strip()
    if not name or not revision_label:
        raise ValueError("Scenario name and revision label are required.")
    try:
        takt = float(takt_time_s)
    except (TypeError, ValueError) as exc:
        raise ValueError("Scenario takt time must be a number.") from exc
    if takt <= 0:
        raise ValueError("Scenario takt time must be greater than zero.")

    new_scenario_id = str(uuid4())
    timestamp = now_iso()
    try:
        with connection() as conn:
            source = conn.execute(
                "SELECT * FROM planning_scenarios WHERE id=? AND project_id=?",
                (source_scenario_id, project_id),
            ).fetchone()
            if not source:
                raise ValueError("The source scenario no longer exists.")
            sequence = conn.execute(
                "SELECT COALESCE(MAX(revision_sequence), 0) + 1 FROM planning_scenarios WHERE project_id=?",
                (project_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, parent_scenario_id,
                    status, takt_time_s, change_summary, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'Working', ?, ?, ?, ?, ?)""",
                (
                    new_scenario_id, project_id, name, revision_label, sequence,
                    source_scenario_id, takt, str(change_summary or "").strip(),
                    str(created_by or "").strip(), timestamp, timestamp,
                ),
            )
            conn.execute(
                """INSERT INTO assembly_scenario_policies
                   (project_id, scenario_id, assembly_id, sourcing_decision, supplier,
                    build_area, buffer_policy, storage_location, minimum_quantity,
                    target_quantity, maximum_quantity, updated_at)
                   SELECT project_id, ?, assembly_id, sourcing_decision, supplier,
                          build_area, buffer_policy, storage_location, minimum_quantity,
                          target_quantity, maximum_quantity, ?
                   FROM assembly_scenario_policies
                   WHERE project_id=? AND scenario_id=?""",
                (new_scenario_id, timestamp, project_id, source_scenario_id),
            )

            process_id_map: dict[str, str] = {}
            for source_row in conn.execute(
                "SELECT * FROM work_elements WHERE project_id=? AND scenario_id=? ORDER BY sequence",
                (project_id, source_scenario_id),
            ).fetchall():
                row = dict(source_row)
                old_id, new_id = str(row["id"]), str(uuid4())
                process_id_map[old_id] = new_id
                row.update(id=new_id, scenario_id=new_scenario_id, updated_at=timestamp)
                columns = list(row)
                conn.execute(
                    f"INSERT INTO work_elements ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    tuple(row[column] for column in columns),
                )

            for source_group in conn.execute(
                """SELECT * FROM process_part_groups
                   WHERE project_id=? AND scenario_id=? ORDER BY name""",
                (project_id, source_scenario_id),
            ).fetchall():
                group = dict(source_group)
                old_group_id = str(group["id"])
                new_work_element_id = process_id_map.get(str(group["work_element_id"]))
                if not new_work_element_id:
                    continue
                new_group_id = str(uuid4())
                group.update(
                    id=new_group_id,
                    scenario_id=new_scenario_id,
                    work_element_id=new_work_element_id,
                    updated_at=timestamp,
                )
                columns = list(group)
                conn.execute(
                    f"INSERT INTO process_part_groups ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    tuple(group[column] for column in columns),
                )
                for source_option in conn.execute(
                    "SELECT * FROM process_part_options WHERE group_id=?", (old_group_id,)
                ).fetchall():
                    option = dict(source_option)
                    option.update(id=str(uuid4()), group_id=new_group_id, updated_at=timestamp)
                    option_columns = list(option)
                    conn.execute(
                        f"INSERT INTO process_part_options ({', '.join(option_columns)}) VALUES ({', '.join('?' for _ in option_columns)})",
                        tuple(option[column] for column in option_columns),
                    )

            area_id_map: dict[str, str] = {}
            for source_row in conn.execute(
                "SELECT * FROM yamazumi_areas WHERE project_id=? AND scenario_id=? ORDER BY name",
                (project_id, source_scenario_id),
            ).fetchall():
                row = dict(source_row)
                old_id, new_id = str(row["id"]), str(uuid4())
                area_id_map[old_id] = new_id
                row.update(id=new_id, scenario_id=new_scenario_id, updated_at=timestamp)
                columns = list(row)
                conn.execute(
                    f"INSERT INTO yamazumi_areas ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    tuple(row[column] for column in columns),
                )

            pitch_id_map: dict[str, str] = {}
            yamazumi_element_id_map: dict[str, str] = {}
            for old_area_id, new_area_id in area_id_map.items():
                for source_row in conn.execute(
                    "SELECT * FROM yamazumi_pitches WHERE project_id=? AND area_id=? ORDER BY sequence",
                    (project_id, old_area_id),
                ).fetchall():
                    row = dict(source_row)
                    old_id, new_id = str(row["id"]), str(uuid4())
                    pitch_id_map[old_id] = new_id
                    row.update(id=new_id, area_id=new_area_id, updated_at=timestamp)
                    columns = list(row)
                    conn.execute(
                        f"INSERT INTO yamazumi_pitches ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                        tuple(row[column] for column in columns),
                    )
                for source_row in conn.execute(
                    "SELECT * FROM yamazumi_work_regions WHERE project_id=? AND area_id=? ORDER BY sequence",
                    (project_id, old_area_id),
                ).fetchall():
                    row = dict(source_row)
                    row.update(id=str(uuid4()), area_id=new_area_id, updated_at=timestamp)
                    columns = list(row)
                    conn.execute(
                        f"INSERT INTO yamazumi_work_regions ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                        tuple(row[column] for column in columns),
                    )
                for source_row in conn.execute(
                    "SELECT * FROM yamazumi_elements WHERE project_id=? AND area_id=? ORDER BY sequence",
                    (project_id, old_area_id),
                ).fetchall():
                    row = dict(source_row)
                    old_element_id = str(row["id"])
                    new_element_id = str(uuid4())
                    yamazumi_element_id_map[old_element_id] = new_element_id
                    old_process_id = str(row.get("process_element_id") or "")
                    row.update(
                        id=new_element_id,
                        area_id=new_area_id,
                        pitch_id=pitch_id_map.get(str(row.get("pitch_id") or "")),
                        process_element_id=process_id_map.get(old_process_id),
                        updated_at=timestamp,
                    )
                    columns = list(row)
                    conn.execute(
                        f"INSERT INTO yamazumi_elements ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                        tuple(row[column] for column in columns),
                    )

            for source_group in conn.execute(
                """SELECT * FROM work_element_material_groups
                   WHERE project_id=? AND scenario_id=? ORDER BY name""",
                (project_id, source_scenario_id),
            ).fetchall():
                group = dict(source_group)
                old_group_id = str(group["id"])
                new_element_id = yamazumi_element_id_map.get(str(group["yamazumi_element_id"]))
                if not new_element_id:
                    continue
                new_group_id = str(uuid4())
                group.update(
                    id=new_group_id,
                    scenario_id=new_scenario_id,
                    yamazumi_element_id=new_element_id,
                    updated_at=timestamp,
                )
                columns = list(group)
                conn.execute(
                    f"INSERT INTO work_element_material_groups ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    tuple(group[column] for column in columns),
                )
                for source_option in conn.execute(
                    "SELECT * FROM work_element_material_options WHERE group_id=?",
                    (old_group_id,),
                ).fetchall():
                    option = dict(source_option)
                    option.update(id=str(uuid4()), group_id=new_group_id, updated_at=timestamp)
                    option_columns = list(option)
                    conn.execute(
                        f"INSERT INTO work_element_material_options ({', '.join(option_columns)}) VALUES ({', '.join('?' for _ in option_columns)})",
                        tuple(option[column] for column in option_columns),
                    )

            conn.execute(
                "UPDATE projects SET updated_at=? WHERE id=?", (timestamp, project_id)
            )
            conn.execute(
                """INSERT INTO audit_log
                   (id, project_id, table_name, action, row_count, editor_name, details, created_at)
                   VALUES (?, ?, 'Planning scenarios', 'Save as scenario', 1, ?, ?, ?)""",
                (
                    str(uuid4()), project_id, str(created_by or "").strip(),
                    json.dumps({"source_scenario_id": source_scenario_id, "new_scenario_id": new_scenario_id}),
                    timestamp,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Scenario names and revision labels must be unique within this project.") from exc
    return new_scenario_id


def record_audit_event(
    project_id: str,
    table_name: str,
    action: str,
    row_count: int,
    editor_name: str = "",
    details: dict | None = None,
) -> None:
    """Record a concise, project-scoped history entry for a persisted table action."""
    execute(
        """INSERT INTO audit_log
           (id, project_id, table_name, action, row_count, editor_name, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(uuid4()), project_id, table_name, action, int(row_count), editor_name.strip(),
            json.dumps(details or {}, ensure_ascii=False), now_iso(),
        ),
    )


def audit_history(project_id: str, table_name: str | None = None, limit: int = 100) -> pd.DataFrame:
    """Return the newest audit entries for a project or one logical table."""
    if table_name:
        rows = query(
            """SELECT action, row_count, editor_name, details, created_at
               FROM audit_log WHERE project_id=? AND table_name=?
               ORDER BY created_at DESC LIMIT ?""",
            (project_id, table_name, int(limit)),
        )
    else:
        rows = query(
            """SELECT table_name, action, row_count, editor_name, details, created_at
               FROM audit_log WHERE project_id=? ORDER BY created_at DESC LIMIT ?""",
            (project_id, int(limit)),
        )
    return pd.DataFrame(rows)


ASSEMBLY_PLANNING_REASONS = {
    "Purchased complete", "Separate build process", "Inventory buffer",
    "Independent test or traceability", "Other",
}
ASSEMBLY_SOURCING_DECISIONS = {"Undecided", "Make", "Buy"}
ASSEMBLY_BUFFER_POLICIES = {"None", "WIP buffer", "Safety stock"}
MATERIAL_SELECTION_RULES = {"Choose one", "Use all", "Optional"}


def manufacturing_assemblies(project_id: str, scenario_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT a.*, parent.assembly_number AS parent_assembly_number,
                  parent.name AS parent_name,
                  COALESCE(policy.sourcing_decision, 'Undecided') AS sourcing_decision,
                  COALESCE(policy.supplier, '') AS supplier,
                  COALESCE(policy.build_area, '') AS build_area,
                  COALESCE(policy.buffer_policy, 'None') AS buffer_policy,
                  COALESCE(policy.storage_location, '') AS storage_location,
                  policy.minimum_quantity, policy.target_quantity, policy.maximum_quantity
           FROM manufacturing_assemblies a
           LEFT JOIN manufacturing_assemblies parent ON parent.id=a.parent_id
           LEFT JOIN assembly_scenario_policies policy
             ON policy.assembly_id=a.id AND policy.scenario_id=?
           WHERE a.project_id=?
           ORDER BY a.assembly_number""",
        (scenario_id, project_id),
    ))


def _optional_nonnegative_number(value, label: str) -> float | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if number < 0:
        raise ValueError(f"{label} cannot be negative.")
    return number


def _assembly_text(value) -> str:
    """Normalize nullable values coming from pandas-backed table editors."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def replace_manufacturing_assemblies(
    project_id: str, scenario_id: str, edited: pd.DataFrame
) -> int:
    required = {
        "id", "assembly_number", "name", "pits_reference", "planning_reason",
        "parent_id", "active", "notes", "sourcing_decision", "supplier",
        "build_area", "buffer_policy", "storage_location", "minimum_quantity",
        "target_quantity", "maximum_quantity",
    }
    if not required.issubset(edited.columns):
        raise ValueError("The manufacturing-assembly table is missing required columns.")
    if not get_planning_scenario(project_id, scenario_id):
        raise ValueError("The active planning scenario no longer exists.")

    timestamp = now_iso()
    records: list[dict] = []
    seen_numbers: set[str] = set()
    for row in edited.to_dict("records"):
        assembly_number = _assembly_text(row.get("assembly_number"))
        name = _assembly_text(row.get("name"))
        if not assembly_number or not name:
            raise ValueError("Every manufacturing assembly needs an assembly number and name.")
        normalized_number = assembly_number.casefold()
        if normalized_number in seen_numbers:
            raise ValueError("Manufacturing assembly numbers must be unique within the project.")
        seen_numbers.add(normalized_number)
        planning_reason = _assembly_text(row.get("planning_reason")) or "Other"
        sourcing = (_assembly_text(row.get("sourcing_decision")) or "Undecided").title()
        buffer_policy = _assembly_text(row.get("buffer_policy")) or "None"
        if planning_reason not in ASSEMBLY_PLANNING_REASONS:
            raise ValueError(f"Choose a valid planning reason for {assembly_number}.")
        if sourcing not in ASSEMBLY_SOURCING_DECISIONS:
            raise ValueError(f"Choose Make, Buy, or Undecided for {assembly_number}.")
        if buffer_policy not in ASSEMBLY_BUFFER_POLICIES:
            raise ValueError(f"Choose a valid buffer policy for {assembly_number}.")
        minimum = _optional_nonnegative_number(row.get("minimum_quantity"), "Minimum quantity")
        target = _optional_nonnegative_number(row.get("target_quantity"), "Target quantity")
        maximum = _optional_nonnegative_number(row.get("maximum_quantity"), "Maximum quantity")
        ordered = [value for value in (minimum, target, maximum) if value is not None]
        if ordered != sorted(ordered):
            raise ValueError(
                f"Minimum, target, and maximum quantities must increase in that order for {assembly_number}."
            )
        records.append({
            "id": _assembly_text(row.get("id")) or str(uuid4()),
            "assembly_number": assembly_number,
            "name": name,
            "pits_reference": _assembly_text(row.get("pits_reference")),
            "planning_reason": planning_reason,
            "parent_id": _assembly_text(row.get("parent_id")) or None,
            "active": int(True if pd.isna(row.get("active")) else bool(row.get("active"))),
            "notes": _assembly_text(row.get("notes")),
            "sourcing_decision": sourcing,
            "supplier": _assembly_text(row.get("supplier")),
            "build_area": _assembly_text(row.get("build_area")),
            "buffer_policy": buffer_policy,
            "storage_location": _assembly_text(row.get("storage_location")),
            "minimum_quantity": minimum,
            "target_quantity": target,
            "maximum_quantity": maximum,
        })

    ids = {record["id"] for record in records}
    parent_by_id = {record["id"]: record["parent_id"] for record in records}
    for assembly_id, parent_id in parent_by_id.items():
        if parent_id and parent_id not in ids:
            raise ValueError("Every parent assembly must exist in the saved table.")
        if parent_id == assembly_id:
            raise ValueError("An assembly cannot be its own parent.")
        visited: set[str] = set()
        cursor = assembly_id
        while cursor:
            if cursor in visited:
                raise ValueError("Assembly parent relationships cannot contain a cycle.")
            visited.add(cursor)
            cursor = parent_by_id.get(cursor)

    try:
        with connection() as conn:
            existing = {
                str(row[0]) for row in conn.execute(
                    "SELECT id FROM manufacturing_assemblies WHERE project_id=?", (project_id,)
                ).fetchall()
            }
            kept = {record["id"] for record in records}
            for record in records:
                conn.execute(
                    """INSERT INTO manufacturing_assemblies
                       (id, project_id, assembly_number, name, pits_reference, planning_reason,
                        parent_id, active, notes, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET assembly_number=excluded.assembly_number,
                        name=excluded.name, pits_reference=excluded.pits_reference,
                        planning_reason=excluded.planning_reason, parent_id=NULL,
                        active=excluded.active, notes=excluded.notes, updated_at=excluded.updated_at""",
                    (
                        record["id"], project_id, record["assembly_number"], record["name"],
                        record["pits_reference"], record["planning_reason"], record["active"],
                        record["notes"], timestamp,
                    ),
                )
                conn.execute(
                    """INSERT INTO assembly_scenario_policies
                       (project_id, scenario_id, assembly_id, sourcing_decision, supplier,
                        build_area, buffer_policy, storage_location, minimum_quantity,
                        target_quantity, maximum_quantity, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(scenario_id, assembly_id) DO UPDATE SET
                        sourcing_decision=excluded.sourcing_decision, supplier=excluded.supplier,
                        build_area=excluded.build_area, buffer_policy=excluded.buffer_policy,
                        storage_location=excluded.storage_location,
                        minimum_quantity=excluded.minimum_quantity,
                        target_quantity=excluded.target_quantity,
                        maximum_quantity=excluded.maximum_quantity,
                        updated_at=excluded.updated_at""",
                    (
                        project_id, scenario_id, record["id"], record["sourcing_decision"],
                        record["supplier"], record["build_area"], record["buffer_policy"],
                        record["storage_location"], record["minimum_quantity"],
                        record["target_quantity"], record["maximum_quantity"], timestamp,
                    ),
                )
            for record in records:
                conn.execute(
                    "UPDATE manufacturing_assemblies SET parent_id=? WHERE id=? AND project_id=?",
                    (record["parent_id"], record["id"], project_id),
                )
            removed = existing - kept
            if removed:
                placeholders = ",".join("?" for _ in removed)
                conn.execute(
                    f"DELETE FROM manufacturing_assemblies WHERE project_id=? AND id IN ({placeholders})",
                    (project_id, *removed),
                )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Manufacturing assembly numbers must be unique within the project.") from exc
    return len(records)


def bulk_update_assembly_policy(
    project_id: str,
    scenario_id: str,
    assembly_ids: list[str],
    sourcing_decision: str | None = None,
    buffer_policy: str | None = None,
) -> int:
    if not assembly_ids:
        return 0
    if sourcing_decision and sourcing_decision not in ASSEMBLY_SOURCING_DECISIONS:
        raise ValueError("Choose Make, Buy, or Undecided.")
    if buffer_policy and buffer_policy not in ASSEMBLY_BUFFER_POLICIES:
        raise ValueError("Choose a valid buffer policy.")
    if not sourcing_decision and not buffer_policy:
        raise ValueError("Choose a sourcing decision or buffer policy to apply.")
    timestamp = now_iso()
    with connection() as conn:
        valid_ids = {
            str(row[0]) for row in conn.execute(
                f"""SELECT id FROM manufacturing_assemblies
                    WHERE project_id=? AND id IN ({','.join('?' for _ in assembly_ids)})""",
                (project_id, *assembly_ids),
            ).fetchall()
        }
        for assembly_id in valid_ids:
            conn.execute(
                """INSERT INTO assembly_scenario_policies
                   (project_id, scenario_id, assembly_id, sourcing_decision, buffer_policy, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(scenario_id, assembly_id) DO UPDATE SET
                    sourcing_decision=COALESCE(?, sourcing_decision),
                    buffer_policy=COALESCE(?, buffer_policy), updated_at=?""",
                (
                    project_id, scenario_id, assembly_id,
                    sourcing_decision or "Undecided", buffer_policy or "None", timestamp,
                    sourcing_decision, buffer_policy, timestamp,
                ),
            )
    return len(valid_ids)


def delete_manufacturing_assembly(project_id: str, assembly_id: str) -> str:
    with connection() as conn:
        row = conn.execute(
            "SELECT assembly_number, name FROM manufacturing_assemblies WHERE id=? AND project_id=?",
            (assembly_id, project_id),
        ).fetchone()
        if not row:
            raise ValueError("That manufacturing assembly no longer exists.")
        conn.execute(
            "DELETE FROM manufacturing_assemblies WHERE id=? AND project_id=?",
            (assembly_id, project_id),
        )
        return f"{row['assembly_number']} — {row['name']}"


def work_element_material_groups(
    project_id: str, scenario_id: str, yamazumi_element_id: str
) -> list[dict]:
    groups = query(
        """SELECT group_row.*, target.assembly_number AS target_assembly_number,
                  target.name AS target_assembly_name
           FROM work_element_material_groups group_row
           LEFT JOIN manufacturing_assemblies target ON target.id=group_row.target_assembly_id
           WHERE group_row.project_id=? AND group_row.scenario_id=?
             AND group_row.yamazumi_element_id=?
           ORDER BY group_row.name""",
        (project_id, scenario_id, yamazumi_element_id),
    )
    for group in groups:
        options = query(
            """SELECT option.id, option.part_id, option.assembly_id,
                      part.part_number, part.description AS part_description,
                      assembly.assembly_number, assembly.name AS assembly_name
               FROM work_element_material_options option
               LEFT JOIN parts part ON part.id=option.part_id
               LEFT JOIN manufacturing_assemblies assembly ON assembly.id=option.assembly_id
               WHERE option.group_id=? ORDER BY part.part_number, assembly.assembly_number""",
            (group["id"],),
        )
        group["options"] = options
        group["option_tokens"] = [
            f"part:{option['part_id']}" if option.get("part_id") else f"assembly:{option['assembly_id']}"
            for option in options
        ]
    return groups


def save_work_element_material_group(
    project_id: str,
    scenario_id: str,
    yamazumi_element_id: str,
    group_id: str | None,
    target_assembly_id: str | None,
    name: str,
    selection_rule: str,
    quantity: float,
    option_tokens: list[str],
    notes: str = "",
) -> str:
    name = str(name or "").strip()
    if not name:
        raise ValueError("Material requirement name is required.")
    if selection_rule not in MATERIAL_SELECTION_RULES:
        raise ValueError("Choose a valid material selection rule.")
    try:
        quantity = float(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("Material quantity must be a number.") from exc
    if quantity <= 0:
        raise ValueError("Material quantity must be greater than zero.")
    tokens = list(dict.fromkeys(str(token) for token in option_tokens if str(token)))
    if not tokens:
        raise ValueError("Choose at least one part or manufacturing assembly.")
    group_id = str(group_id or "").strip() or str(uuid4())
    timestamp = now_iso()
    try:
        with connection() as conn:
            valid_element = conn.execute(
                """SELECT 1 FROM yamazumi_elements element
                   JOIN yamazumi_areas area ON area.id=element.area_id
                   WHERE element.id=? AND element.project_id=? AND area.scenario_id=?""",
                (yamazumi_element_id, project_id, scenario_id),
            ).fetchone()
            if not valid_element:
                raise ValueError("That Yamazumi work element no longer exists in this scenario.")
            target_assembly_id = str(target_assembly_id or "").strip() or None
            if target_assembly_id and not conn.execute(
                """SELECT 1 FROM manufacturing_assemblies
                   WHERE id=? AND project_id=? AND active=1""",
                (target_assembly_id, project_id),
            ).fetchone():
                raise ValueError("The selected target assembly no longer exists or is inactive.")
            conn.execute(
                """INSERT INTO work_element_material_groups
                   (id, project_id, scenario_id, yamazumi_element_id, target_assembly_id, name,
                    selection_rule, quantity, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                    target_assembly_id=excluded.target_assembly_id,
                    selection_rule=excluded.selection_rule, quantity=excluded.quantity,
                    notes=excluded.notes, updated_at=excluded.updated_at""",
                (
                    group_id, project_id, scenario_id, yamazumi_element_id,
                    target_assembly_id, name,
                    selection_rule, quantity, str(notes or "").strip(), timestamp,
                ),
            )
            conn.execute("DELETE FROM work_element_material_options WHERE group_id=?", (group_id,))
            for token in tokens:
                kind, separator, item_id = token.partition(":")
                if not separator or kind not in {"part", "assembly"} or not item_id:
                    raise ValueError("A selected material option is invalid.")
                table = "parts" if kind == "part" else "manufacturing_assemblies"
                if not conn.execute(
                    f"SELECT 1 FROM {table} WHERE id=? AND project_id=?", (item_id, project_id)
                ).fetchone():
                    raise ValueError("A selected material option no longer exists in this project.")
                conn.execute(
                    """INSERT INTO work_element_material_options
                       (id, group_id, part_id, assembly_id, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        str(uuid4()), group_id, item_id if kind == "part" else None,
                        item_id if kind == "assembly" else None, timestamp,
                    ),
                )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Material requirement names must be unique within a work element.") from exc
    return group_id


def delete_work_element_material_group(
    project_id: str, scenario_id: str, group_id: str
) -> bool:
    with connection() as conn:
        cursor = conn.execute(
            """DELETE FROM work_element_material_groups
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (group_id, project_id, scenario_id),
        )
        return bool(cursor.rowcount)


def material_consumption_for_scenario(project_id: str, scenario_id: str) -> pd.DataFrame:
    rows = query(
        """SELECT group_row.id AS group_id, element.id AS process_element_id,
                  group_row.section_id, section.name AS section_name,
                  group_row.name AS requirement,
                  group_row.selection_rule, group_row.quantity,
                  part.part_number, part.description AS part_description,
                  group_row.notes
           FROM process_part_groups group_row
           JOIN work_elements element ON element.id=group_row.work_element_id
           LEFT JOIN assembly_sections section ON section.id=group_row.section_id
           LEFT JOIN process_part_options option ON option.group_id=group_row.id
           LEFT JOIN parts part ON part.id=option.part_id
           WHERE group_row.project_id=? AND group_row.scenario_id=?
           ORDER BY element.sequence, group_row.name, part.part_number""",
        (project_id, scenario_id),
    )
    return pd.DataFrame(rows)


def yamazumi_elements_for_section(
    project_id: str, scenario_id: str, section_id: str
) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT element.id, element.process_element_id, element.description,
                  element.time_s, element.model_variant, element.work_type,
                  element.process_sync_status, area.id AS area_id, area.name AS area_name,
                  pitch.pitch_number, pitch.pitch_name,
                  COUNT(DISTINCT group_row.id) AS material_group_count
           FROM yamazumi_elements element
           JOIN yamazumi_areas area ON area.id=element.area_id
           LEFT JOIN yamazumi_pitches pitch ON pitch.id=element.pitch_id
           LEFT JOIN process_part_groups group_row
             ON group_row.work_element_id=element.process_element_id
            AND group_row.scenario_id=area.scenario_id
           WHERE element.project_id=? AND area.scenario_id=? AND area.section_id=?
           GROUP BY element.id
           ORDER BY area.name, pitch.sequence, element.sequence""",
        (project_id, scenario_id, section_id),
    ))


def process_element_id_for_yamazumi(
    project_id: str, scenario_id: str, yamazumi_element_id: str
) -> str | None:
    rows = query(
        """SELECT element.process_element_id
           FROM yamazumi_elements element
           JOIN yamazumi_areas area ON area.id=element.area_id
           WHERE element.id=? AND element.project_id=? AND area.scenario_id=?""",
        (yamazumi_element_id, project_id, scenario_id),
    )
    if not rows:
        return None
    return str(rows[0].get("process_element_id") or "").strip() or None


def process_part_groups(
    project_id: str, scenario_id: str, work_element_id: str | None = None
) -> list[dict]:
    element_clause = " AND group_row.work_element_id=?" if work_element_id else ""
    params = (project_id, scenario_id, work_element_id) if work_element_id else (project_id, scenario_id)
    groups = query(
        f"""SELECT group_row.*, section.name AS section_name,
                   element.operation, element.station
            FROM process_part_groups group_row
            JOIN work_elements element ON element.id=group_row.work_element_id
            LEFT JOIN assembly_sections section ON section.id=group_row.section_id
            WHERE group_row.project_id=? AND group_row.scenario_id=?{element_clause}
            ORDER BY element.sequence, group_row.name""",
        params,
    )
    for group in groups:
        options = query(
            """SELECT option.id, option.part_id, part.part_number,
                      part.description AS part_description, part.model_applicability
               FROM process_part_options option
               JOIN parts part ON part.id=option.part_id
               WHERE option.group_id=? ORDER BY part.part_number""",
            (group["id"],),
        )
        group["options"] = options
        group["part_ids"] = [str(option["part_id"]) for option in options]
    return groups


def save_process_part_group(
    project_id: str,
    scenario_id: str,
    work_element_id: str,
    section_id: str,
    group_id: str | None,
    name: str,
    selection_rule: str,
    quantity: float,
    part_ids: list[str],
    notes: str = "",
) -> str:
    name = str(name or "").strip()
    if not name:
        raise ValueError("Part requirement name is required.")
    if selection_rule not in MATERIAL_SELECTION_RULES:
        raise ValueError("Choose a valid part-selection rule.")
    quantity = _optional_nonnegative_number(quantity, "Part quantity")
    if quantity is None or quantity <= 0:
        raise ValueError("Part quantity must be greater than zero.")
    selected_part_ids = list(dict.fromkeys(str(part_id) for part_id in part_ids if str(part_id)))
    if not selected_part_ids:
        raise ValueError("Select at least one fishbone part.")
    group_id = str(group_id or "").strip() or str(uuid4())
    timestamp = now_iso()
    try:
        with connection() as conn:
            if not conn.execute(
                """SELECT 1 FROM work_elements
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (work_element_id, project_id, scenario_id),
            ).fetchone():
                raise ValueError("That process-plan work element no longer exists.")
            if not conn.execute(
                "SELECT 1 FROM assembly_sections WHERE id=? AND project_id=? AND active=1",
                (section_id, project_id),
            ).fetchone():
                raise ValueError("Choose an active fishbone section.")
            placeholders = ",".join("?" for _ in selected_part_ids)
            available = {
                str(row[0]) for row in conn.execute(
                    f"""SELECT DISTINCT part_id FROM fishbone_part_assignments
                        WHERE project_id=? AND section_id=? AND part_id IN ({placeholders})""",
                    (project_id, section_id, *selected_part_ids),
                ).fetchall()
            }
            if available != set(selected_part_ids):
                raise ValueError("Every selected part must be available in the active fishbone section.")
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id, name,
                    selection_rule, quantity, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET section_id=excluded.section_id,
                    name=excluded.name, selection_rule=excluded.selection_rule,
                    quantity=excluded.quantity, notes=excluded.notes,
                    updated_at=excluded.updated_at""",
                (
                    group_id, project_id, scenario_id, work_element_id, section_id,
                    name, selection_rule, quantity, str(notes or "").strip(), timestamp,
                ),
            )
            conn.execute("DELETE FROM process_part_options WHERE group_id=?", (group_id,))
            for part_id in selected_part_ids:
                conn.execute(
                    """INSERT INTO process_part_options
                       (id, group_id, part_id, updated_at) VALUES (?, ?, ?, ?)""",
                    (str(uuid4()), group_id, part_id, timestamp),
                )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Part requirement names must be unique within a process step.") from exc
    return group_id


def delete_process_part_group(
    project_id: str, scenario_id: str, group_id: str
) -> bool:
    with connection() as conn:
        cursor = conn.execute(
            """DELETE FROM process_part_groups
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (group_id, project_id, scenario_id),
        )
        return bool(cursor.rowcount)


def yamazumi_areas(project_id: str, scenario_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT a.*, s.name AS section_name
           FROM yamazumi_areas a LEFT JOIN assembly_sections s ON s.id=a.section_id
           WHERE a.project_id=? AND a.scenario_id=? ORDER BY a.name""",
        (project_id, scenario_id),
    ))


def yamazumi_area_link_status(project_id: str, scenario_id: str) -> dict[str, int | bool]:
    """Report active Fishbone-section gaps and existing one-to-one link conflicts."""
    sections = query(
        """SELECT id, name, section_type FROM assembly_sections
           WHERE project_id=? AND active=1
           ORDER BY sequence, name""",
        (project_id,),
    )
    areas = query(
        """SELECT id, name, section_id FROM yamazumi_areas
           WHERE project_id=? AND scenario_id=? ORDER BY name, id""",
        (project_id, scenario_id),
    )
    link_counts: dict[str, int] = {}
    for area in areas:
        section_id = str(area.get("section_id") or "").strip()
        if section_id:
            link_counts[section_id] = link_counts.get(section_id, 0) + 1
    missing = sum(1 for section in sections if link_counts.get(str(section["id"]), 0) == 0)
    conflicting = sum(max(0, count - 1) for count in link_counts.values())
    section_by_name = {str(section["name"]).casefold(): str(section["id"]) for section in sections}
    mislinked = sum(
        1
        for area in areas
        if str(area["name"]).casefold() in section_by_name
        and str(area.get("section_id") or "") != section_by_name[str(area["name"]).casefold()]
    )
    return {
        "active_sections": len(sections),
        "missing": missing,
        "mislinked": mislinked,
        "conflicting": conflicting,
        "needs_sync": bool(missing or mislinked or conflicting),
    }


def yamazumi_pitches(project_id: str, area_id: str) -> pd.DataFrame:
    rows = pd.DataFrame(query(
        """SELECT * FROM yamazumi_pitches WHERE project_id=? AND area_id=?
           ORDER BY sequence, pitch_number""",
        (project_id, area_id),
    ))
    if rows.empty:
        return pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "pitch_number": pd.Series(dtype="string"),
            "pitch_name": pd.Series(dtype="string"),
            "status": pd.Series(dtype="string"),
            "sequence": pd.Series(dtype="Int64"),
            "model_variants": pd.Series(dtype="string"),
            "pitch_type": pd.Series(dtype="string"),
            "updated_at": pd.Series(dtype="string"),
        })
    return rows


def yamazumi_elements(project_id: str, area_id: str) -> pd.DataFrame:
    rows = pd.DataFrame(query(
        """SELECT e.*, p.pitch_number, p.pitch_name, p.status AS pitch_status
           FROM yamazumi_elements e LEFT JOIN yamazumi_pitches p ON p.id=e.pitch_id
           WHERE e.project_id=? AND e.area_id=?
           ORDER BY COALESCE(p.sequence, 999999), e.model_variant, e.sequence, e.description""",
        (project_id, area_id),
    ))
    if rows.empty:
        return pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "pitch_id": pd.Series(dtype="string"),
            "model_variant": pd.Series(dtype="string"),
            "work_type": pd.Series(dtype="string"),
            "description": pd.Series(dtype="string"),
            "time_s": pd.Series(dtype="Float64"),
            "work_region": pd.Series(dtype="string"),
            "flags": pd.Series(dtype="string"),
            "sequence": pd.Series(dtype="Int64"),
            "source": pd.Series(dtype="string"),
            "process_element_id": pd.Series(dtype="string"),
            "process_sync_status": pd.Series(dtype="string"),
            "updated_at": pd.Series(dtype="string"),
            "pitch_number": pd.Series(dtype="string"),
            "pitch_name": pd.Series(dtype="string"),
            "pitch_status": pd.Series(dtype="string"),
        })
    return rows


def yamazumi_pitches_for_scenario(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Load pitch addresses across every Yamazumi area in one scenario."""
    rows = pd.DataFrame(query(
        """SELECT p.*, a.name AS area_name
           FROM yamazumi_pitches p
           JOIN yamazumi_areas a ON a.id=p.area_id
           WHERE p.project_id=? AND a.scenario_id=?
           ORDER BY a.name, p.sequence, p.pitch_number""",
        (project_id, scenario_id),
    ))
    if rows.empty:
        return pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "pitch_number": pd.Series(dtype="string"),
            "pitch_name": pd.Series(dtype="string"),
            "status": pd.Series(dtype="string"),
            "sequence": pd.Series(dtype="Int64"),
            "model_variants": pd.Series(dtype="string"),
            "pitch_type": pd.Series(dtype="string"),
            "updated_at": pd.Series(dtype="string"),
            "area_name": pd.Series(dtype="string"),
        })
    return rows


def yamazumi_elements_for_scenario(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Load work elements across every Yamazumi area in one scenario."""
    rows = pd.DataFrame(query(
        """SELECT e.*, p.pitch_number, p.pitch_name, p.status AS pitch_status,
                  a.name AS area_name
           FROM yamazumi_elements e
           JOIN yamazumi_areas a ON a.id=e.area_id
           LEFT JOIN yamazumi_pitches p ON p.id=e.pitch_id
           WHERE e.project_id=? AND a.scenario_id=?
           ORDER BY a.name, COALESCE(p.sequence, 999999),
                    e.model_variant, e.sequence, e.description""",
        (project_id, scenario_id),
    ))
    if rows.empty:
        return pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "pitch_id": pd.Series(dtype="string"),
            "model_variant": pd.Series(dtype="string"),
            "work_type": pd.Series(dtype="string"),
            "description": pd.Series(dtype="string"),
            "time_s": pd.Series(dtype="Float64"),
            "work_region": pd.Series(dtype="string"),
            "flags": pd.Series(dtype="string"),
            "sequence": pd.Series(dtype="Int64"),
            "source": pd.Series(dtype="string"),
            "process_element_id": pd.Series(dtype="string"),
            "process_sync_status": pd.Series(dtype="string"),
            "updated_at": pd.Series(dtype="string"),
            "pitch_number": pd.Series(dtype="string"),
            "pitch_name": pd.Series(dtype="string"),
            "pitch_status": pd.Series(dtype="string"),
            "area_name": pd.Series(dtype="string"),
        })
    return rows


def yamazumi_work_regions(project_id: str, area_id: str) -> pd.DataFrame:
    rows = pd.DataFrame(query(
        """SELECT * FROM yamazumi_work_regions
           WHERE project_id=? AND area_id=? ORDER BY sequence, name""",
        (project_id, area_id),
    ))
    if rows.empty:
        return pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "name": pd.Series(dtype="string"),
            "description": pd.Series(dtype="string"),
            "active": pd.Series(dtype="bool"),
            "color": pd.Series(dtype="string"),
            "sequence": pd.Series(dtype="int64"),
            "updated_at": pd.Series(dtype="string"),
        })
    if "name" in rows.columns:
        rows["name"] = rows["name"].map(lambda value: "" if pd.isna(value) else str(value))
    if "description" in rows.columns:
        rows["description"] = rows["description"].map(lambda value: "" if pd.isna(value) else str(value))
    return rows


def replace_yamazumi_work_regions(project_id: str, area_id: str, records: list[dict]) -> int:
    """Replace area-specific work-region definitions."""
    import re

    cleaned: list[dict] = []
    seen: set[str] = set()
    for index, record in enumerate(records, start=1):
        name = str(record.get("name") or "").strip()
        if not name:
            continue
        if name.casefold() == "none":
            raise ValueError("None is reserved for elements without a work-region highlight.")
        if name.casefold() in seen:
            raise ValueError("Work-region names must be unique.")
        seen.add(name.casefold())
        raw_color = record.get("color")
        color = (
            "#35c84a"
            if raw_color is None or pd.isna(raw_color) or not str(raw_color).strip()
            else str(raw_color).strip().lower()
        )
        if not re.fullmatch(r"#[0-9a-f]{6}", color):
            raise ValueError(f"Choose a valid color for {name}.")
        cleaned.append({
            "id": str(record.get("id") or "").strip() or str(uuid4()),
            "name": name,
            "description": str(record.get("description") or "").strip(),
            "active": int(
                True
                if record.get("active") is None or pd.isna(record.get("active"))
                else bool(record.get("active"))
            ),
            "color": color,
            "sequence": (
                index * 10
                if record.get("sequence") is None or pd.isna(record.get("sequence"))
                else int(record.get("sequence"))
            ),
        })
    timestamp = now_iso()
    with connection() as conn:
        valid_area = conn.execute(
            "SELECT 1 FROM yamazumi_areas WHERE id=? AND project_id=?", (area_id, project_id)
        ).fetchone()
        if not valid_area:
            raise ValueError("That Yamazumi area no longer exists.")
        existing = {
            str(row["id"]): str(row["name"])
            for row in conn.execute(
                "SELECT id, name FROM yamazumi_work_regions WHERE project_id=? AND area_id=?",
                (project_id, area_id),
            ).fetchall()
        }
        kept = {record["id"] for record in cleaned}
        removed_names = [name for region_id, name in existing.items() if region_id not in kept]
        if removed_names:
            placeholders = ",".join("?" for _ in removed_names)
            conn.execute(
                f"""UPDATE yamazumi_elements
                    SET work_region='None', process_sync_status='Needs IE review', updated_at=?
                    WHERE project_id=? AND area_id=? AND work_region IN ({placeholders})""",
                (timestamp, project_id, area_id, *removed_names),
            )
        for record in cleaned:
            old_name = existing.get(record["id"])
            if old_name and old_name != record["name"]:
                conn.execute(
                    """UPDATE yamazumi_elements SET work_region=?, updated_at=?
                       WHERE project_id=? AND area_id=? AND work_region=?""",
                    (record["name"], timestamp, project_id, area_id, old_name),
                )
        for record in cleaned:
            conn.execute(
                """INSERT INTO yamazumi_work_regions
                   (id, project_id, area_id, name, description, active, color, sequence, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                   description=excluded.description, active=excluded.active,
                   color=excluded.color, sequence=excluded.sequence, updated_at=excluded.updated_at""",
                (
                    record["id"], project_id, area_id, record["name"], record["description"],
                    record["active"], record["color"], record["sequence"], timestamp,
                ),
            )
        removed_ids = set(existing) - kept
        if removed_ids:
            placeholders = ",".join("?" for _ in removed_ids)
            conn.execute(f"DELETE FROM yamazumi_work_regions WHERE id IN ({placeholders})", tuple(removed_ids))
    return len(cleaned)


SYSTEM_YAMAZUMI_FLAGS = {
    "CTQ": "Critical-to-quality work or verification.",
    "Safety": "Work with a safety-related requirement or risk.",
}


def _ensure_system_yamazumi_flags(conn: sqlite3.Connection, project_id: str) -> None:
    timestamp = now_iso()
    for sequence, (name, description) in enumerate(SYSTEM_YAMAZUMI_FLAGS.items(), start=1):
        conn.execute(
            """INSERT INTO yamazumi_flag_definitions
               (id, project_id, name, description, active, system_flag, sequence, updated_at)
               VALUES (?, ?, ?, ?, 1, 1, ?, ?)
               ON CONFLICT(project_id, name) DO UPDATE SET
                description=excluded.description, active=1, system_flag=1,
                sequence=excluded.sequence, updated_at=excluded.updated_at
               WHERE yamazumi_flag_definitions.description IS NOT excluded.description
                  OR yamazumi_flag_definitions.active <> 1
                  OR yamazumi_flag_definitions.system_flag <> 1
                  OR yamazumi_flag_definitions.sequence <> excluded.sequence""",
            (str(uuid4()), project_id, name, description, sequence * 10, timestamp),
        )


def yamazumi_flag_definitions(project_id: str) -> pd.DataFrame:
    with connection() as conn:
        _ensure_system_yamazumi_flags(conn, project_id)
        rows = conn.execute(
            """SELECT * FROM yamazumi_flag_definitions
               WHERE project_id=? ORDER BY sequence, name""",
            (project_id,),
        ).fetchall()
        definitions = pd.DataFrame([dict(row) for row in rows])
        if definitions.empty:
            return definitions
        if "name" in definitions.columns:
            definitions["name"] = definitions["name"].map(lambda value: "" if pd.isna(value) else str(value))
        if "description" in definitions.columns:
            definitions["description"] = definitions["description"].map(lambda value: "" if pd.isna(value) else str(value))
        return definitions


def active_yamazumi_flags(project_id: str) -> list[str]:
    definitions = yamazumi_flag_definitions(project_id)
    if definitions.empty:
        return list(SYSTEM_YAMAZUMI_FLAGS)
    return definitions.loc[
        definitions["active"].fillna(1).astype(bool), "name"
    ].astype(str).tolist()


def yamazumi_flag_names(project_id: str, include_inactive: bool = True) -> list[str]:
    definitions = yamazumi_flag_definitions(project_id)
    if definitions.empty:
        return list(SYSTEM_YAMAZUMI_FLAGS)
    if not include_inactive:
        definitions = definitions.loc[definitions["active"].fillna(1).astype(bool)]
    return definitions["name"].astype(str).tolist()


def _rewrite_yamazumi_element_flags(
    conn: sqlite3.Connection,
    project_id: str,
    renamed: dict[str, str] | None = None,
    removed: set[str] | None = None,
) -> None:
    renamed = renamed or {}
    removed = removed or set()
    if not renamed and not removed:
        return
    timestamp = now_iso()
    for row in conn.execute(
        "SELECT id, flags FROM yamazumi_elements WHERE project_id=?", (project_id,)
    ).fetchall():
        try:
            current = json.loads(row["flags"] or "[]")
        except (TypeError, json.JSONDecodeError):
            current = []
        normalized = list(dict.fromkeys(
            renamed.get(str(flag), str(flag))
            for flag in current
            if str(flag) not in removed
        ))
        if normalized != current:
            conn.execute(
                """UPDATE yamazumi_elements
                   SET flags=?, process_sync_status='Needs IE review', updated_at=? WHERE id=?""",
                (json.dumps(normalized), timestamp, row["id"]),
            )


def replace_yamazumi_flag_definitions(project_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "name", "description", "active", "system_flag", "sequence"}
    if not required.issubset(edited.columns):
        raise ValueError("The flag-definition table is missing required columns.")
    records: list[dict] = []
    seen_names: set[str] = set()
    for index, row in enumerate(edited.to_dict("records"), start=1):
        name = "" if row.get("name") is None or pd.isna(row.get("name")) else str(row["name"]).strip()
        if not name:
            raise ValueError("Every flag definition needs a name.")
        if name.casefold() in seen_names:
            raise ValueError("Flag names must be unique within the project.")
        seen_names.add(name.casefold())
        records.append({
            "id": (
                str(row.get("id")).strip()
                if row.get("id") is not None and not pd.isna(row.get("id")) and str(row.get("id")).strip()
                else str(uuid4())
            ),
            "name": name,
            "description": (
                "" if row.get("description") is None or pd.isna(row.get("description"))
                else str(row["description"]).strip()
            ),
            "active": int(True if pd.isna(row.get("active")) else bool(row.get("active"))),
            "system_flag": int(bool(row.get("system_flag", False))),
            "sequence": int(row.get("sequence") or index * 10),
        })

    timestamp = now_iso()
    try:
        with connection() as conn:
            _ensure_system_yamazumi_flags(conn, project_id)
            existing_rows = conn.execute(
                "SELECT * FROM yamazumi_flag_definitions WHERE project_id=?", (project_id,)
            ).fetchall()
            existing = {str(row["id"]): dict(row) for row in existing_rows}
            system_ids = {
                flag_id for flag_id, row in existing.items() if bool(row["system_flag"])
            }
            kept_ids = {record["id"] for record in records}
            if not system_ids.issubset(kept_ids):
                raise ValueError("CTQ and Safety are permanent system flags and cannot be deleted.")
            renamed: dict[str, str] = {}
            for record in records:
                previous = existing.get(record["id"])
                if previous and bool(previous["system_flag"]):
                    record["name"] = str(previous["name"])
                    record["description"] = str(previous["description"] or "")
                    record["active"] = 1
                    record["system_flag"] = 1
                else:
                    record["system_flag"] = 0
                if previous and str(previous["name"]) != record["name"]:
                    renamed[str(previous["name"])] = record["name"]
            removed_ids = set(existing) - kept_ids
            removed_names = {
                str(existing[flag_id]["name"])
                for flag_id in removed_ids
                if not bool(existing[flag_id]["system_flag"])
            }
            _rewrite_yamazumi_element_flags(conn, project_id, renamed, removed_names)
            for record in records:
                conn.execute(
                    """INSERT INTO yamazumi_flag_definitions
                       (id, project_id, name, description, active, system_flag, sequence, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                        description=excluded.description, active=excluded.active,
                        system_flag=excluded.system_flag, sequence=excluded.sequence,
                        updated_at=excluded.updated_at""",
                    (
                        record["id"], project_id, record["name"], record["description"],
                        record["active"], record["system_flag"], record["sequence"], timestamp,
                    ),
                )
            if removed_ids:
                placeholders = ",".join("?" for _ in removed_ids)
                conn.execute(
                    f"""DELETE FROM yamazumi_flag_definitions
                        WHERE project_id=? AND id IN ({placeholders}) AND system_flag=0""",
                    (project_id, *removed_ids),
                )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Flag names must be unique within the project.") from exc
    return len(records)


def delete_yamazumi_flag_definitions(project_id: str, flag_ids: list[str]) -> int:
    selected_ids = list(dict.fromkeys(str(flag_id) for flag_id in flag_ids if str(flag_id)))
    if not selected_ids:
        return 0
    with connection() as conn:
        _ensure_system_yamazumi_flags(conn, project_id)
        placeholders = ",".join("?" for _ in selected_ids)
        rows = conn.execute(
            f"""SELECT id, name, system_flag FROM yamazumi_flag_definitions
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *selected_ids),
        ).fetchall()
        if any(bool(row["system_flag"]) for row in rows):
            raise ValueError("CTQ and Safety are permanent system flags and cannot be deleted.")
        removed_names = {str(row["name"]) for row in rows}
        _rewrite_yamazumi_element_flags(conn, project_id, removed=removed_names)
        conn.execute(
            f"""DELETE FROM yamazumi_flag_definitions
                WHERE project_id=? AND id IN ({placeholders}) AND system_flag=0""",
            (project_id, *selected_ids),
        )
        return len(rows)


def rename_yamazumi_variants(project_id: str, scenario_id: str, label_mapping: dict[str, str]) -> int:
    """Normalize saved Yamazumi labels after a display-label convention changes."""
    mapping = {str(old): str(new) for old, new in label_mapping.items() if str(old) != str(new)}
    if not mapping:
        return 0
    changed = 0
    timestamp = now_iso()
    with connection() as conn:
        elements = conn.execute(
            """SELECT e.id, e.model_variant FROM yamazumi_elements e
               JOIN yamazumi_areas a ON a.id=e.area_id
               WHERE e.project_id=? AND a.scenario_id=?""", (project_id, scenario_id)
        ).fetchall()
        for element in elements:
            new_label = mapping.get(str(element["model_variant"]))
            if new_label:
                conn.execute(
                    "UPDATE yamazumi_elements SET model_variant=?, updated_at=? WHERE id=?",
                    (new_label, timestamp, element["id"]),
                )
                changed += 1
        pitches = conn.execute(
            """SELECT p.id, p.model_variants FROM yamazumi_pitches p
               JOIN yamazumi_areas a ON a.id=p.area_id
               WHERE p.project_id=? AND a.scenario_id=?""", (project_id, scenario_id)
        ).fetchall()
        for pitch in pitches:
            variants = json.loads(pitch["model_variants"] or "[]")
            normalized = list(dict.fromkeys(mapping.get(str(value), str(value)) for value in variants))
            if normalized != variants:
                conn.execute(
                    "UPDATE yamazumi_pitches SET model_variants=?, updated_at=? WHERE id=?",
                    (json.dumps(normalized), timestamp, pitch["id"]),
                )
                changed += 1
    return changed


def clear_yamazumi_data(project_id: str, scenario_id: str, area_id: str | None = None) -> dict[str, int]:
    """Delete Yamazumi-only areas, pitches, and work without changing Fishbone or Process Plan."""
    with connection() as conn:
        if area_id:
            area = conn.execute(
                "SELECT id FROM yamazumi_areas WHERE id=? AND project_id=? AND scenario_id=?",
                (area_id, project_id, scenario_id),
            ).fetchone()
            if not area:
                raise ValueError("That Yamazumi area no longer exists.")
            counts = {
                "areas": 1,
                "pitches": conn.execute(
                    "SELECT COUNT(*) FROM yamazumi_pitches WHERE project_id=? AND area_id=?",
                    (project_id, area_id),
                ).fetchone()[0],
                "elements": conn.execute(
                    "SELECT COUNT(*) FROM yamazumi_elements WHERE project_id=? AND area_id=?",
                    (project_id, area_id),
                ).fetchone()[0],
            }
            conn.execute("DELETE FROM yamazumi_areas WHERE id=? AND project_id=?", (area_id, project_id))
        else:
            counts = {
                "areas": conn.execute(
                    "SELECT COUNT(*) FROM yamazumi_areas WHERE project_id=? AND scenario_id=?", (project_id, scenario_id)
                ).fetchone()[0],
                "pitches": conn.execute(
                    """SELECT COUNT(*) FROM yamazumi_pitches p JOIN yamazumi_areas a ON a.id=p.area_id
                       WHERE p.project_id=? AND a.scenario_id=?""", (project_id, scenario_id)
                ).fetchone()[0],
                "elements": conn.execute(
                    """SELECT COUNT(*) FROM yamazumi_elements e JOIN yamazumi_areas a ON a.id=e.area_id
                       WHERE e.project_id=? AND a.scenario_id=?""", (project_id, scenario_id)
                ).fetchone()[0],
            }
            conn.execute(
                "DELETE FROM yamazumi_areas WHERE project_id=? AND scenario_id=?",
                (project_id, scenario_id),
            )
    return counts


def upsert_yamazumi_area(
    project_id: str, scenario_id: str, name: str,
    section_id: str | None = None, takt_override_s: float | None = None
) -> str:
    name = str(name or "").strip()
    if not name:
        raise ValueError("Yamazumi area name is required.")
    timestamp = now_iso()
    with connection() as conn:
        existing = conn.execute(
            "SELECT id, section_id FROM yamazumi_areas WHERE project_id=? AND scenario_id=? AND name=?",
            (project_id, scenario_id, name),
        ).fetchone()
        area_id = str(existing["id"]) if existing else str(uuid4())
        normalized_section_id = str(section_id or "").strip() or None
        existing_section_id = (
            str(existing["section_id"] or "").strip() or None if existing else None
        )
        if existing_section_id and normalized_section_id and normalized_section_id != existing_section_id:
            raise ValueError(
                "This Yamazumi area is already linked from the Fishbone and cannot be relinked automatically."
            )
        if normalized_section_id:
            _validate_yamazumi_area_link(
                conn, project_id, scenario_id, normalized_section_id, area_id
            )
        if existing:
            conn.execute(
                """UPDATE yamazumi_areas SET section_id=COALESCE(?, section_id),
                   takt_override_s=COALESCE(?, takt_override_s), updated_at=? WHERE id=?""",
                (normalized_section_id, takt_override_s, timestamp, area_id),
            )
        else:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, takt_override_s, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (area_id, project_id, scenario_id, normalized_section_id, name, takt_override_s, timestamp),
            )
    return area_id


def _validate_yamazumi_area_link(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    section_id: str,
    area_id: str,
) -> None:
    section = conn.execute(
        "SELECT name FROM assembly_sections WHERE id=? AND project_id=?",
        (section_id, project_id),
    ).fetchone()
    if not section:
        raise ValueError("Choose a Fishbone section from this project.")
    conflict = conn.execute(
        """SELECT name FROM yamazumi_areas
           WHERE project_id=? AND scenario_id=? AND section_id=? AND id<>?""",
        (project_id, scenario_id, section_id, area_id),
    ).fetchone()
    if conflict:
        raise ValueError(
            f"Fishbone section {section['name']} is already linked to Yamazumi area {conflict['name']}."
        )


def sync_yamazumi_areas_from_fishbone(project_id: str, scenario_id: str) -> dict[str, int]:
    """Create and repair one linked area per active Fishbone section."""
    timestamp = now_iso()
    summary = {"created": 0, "relinked": 0, "conflicts_cleared": 0}
    with connection() as conn:
        sections = conn.execute(
            """SELECT id, name FROM assembly_sections
               WHERE project_id=? AND active=1
               ORDER BY sequence, name""",
            (project_id,),
        ).fetchall()
        if not sections:
            return summary

        # Restart after every change. Re-reading the links prevents a repair
        # from hiding a newly missing section until the next button click.
        area_count = conn.execute(
            "SELECT COUNT(*) FROM yamazumi_areas WHERE project_id=? AND scenario_id=?",
            (project_id, scenario_id),
        ).fetchone()[0]
        max_changes = max(10, (len(sections) + int(area_count)) * 3)
        for _ in range(max_changes):
            changed = False

            duplicate = conn.execute(
                """SELECT section_id FROM yamazumi_areas
                   WHERE project_id=? AND scenario_id=? AND section_id IS NOT NULL
                   GROUP BY section_id HAVING COUNT(*) > 1 LIMIT 1""",
                (project_id, scenario_id),
            ).fetchone()
            if duplicate:
                section = conn.execute(
                    "SELECT name FROM assembly_sections WHERE id=? AND project_id=?",
                    (duplicate["section_id"], project_id),
                ).fetchone()
                linked = conn.execute(
                    """SELECT id, name FROM yamazumi_areas
                       WHERE project_id=? AND scenario_id=? AND section_id=?
                       ORDER BY name, id""",
                    (project_id, scenario_id, duplicate["section_id"]),
                ).fetchall()
                preferred = next(
                    (
                        row for row in linked
                        if section and str(row["name"]).casefold() == str(section["name"]).casefold()
                    ),
                    linked[0],
                )
                for row in linked:
                    if row["id"] == preferred["id"]:
                        continue
                    conn.execute(
                        "UPDATE yamazumi_areas SET section_id=NULL, updated_at=? WHERE id=?",
                        (timestamp, row["id"]),
                    )
                    summary["conflicts_cleared"] += 1
                changed = True

            if changed:
                continue

            for section in sections:
                matching_area = conn.execute(
                    """SELECT id, name, section_id FROM yamazumi_areas
                       WHERE project_id=? AND scenario_id=? AND name=? COLLATE NOCASE
                       ORDER BY id LIMIT 1""",
                    (project_id, scenario_id, section["name"]),
                ).fetchone()
                if matching_area and str(matching_area["section_id"] or "") != str(section["id"]):
                    current_target = conn.execute(
                        """SELECT id FROM yamazumi_areas
                           WHERE project_id=? AND scenario_id=? AND section_id=? AND id<>?""",
                        (project_id, scenario_id, section["id"], matching_area["id"]),
                    ).fetchone()
                    if current_target:
                        conn.execute(
                            "UPDATE yamazumi_areas SET section_id=NULL, updated_at=? WHERE id=?",
                            (timestamp, current_target["id"]),
                        )
                        summary["conflicts_cleared"] += 1
                    conn.execute(
                        "UPDATE yamazumi_areas SET section_id=?, updated_at=? WHERE id=?",
                        (section["id"], timestamp, matching_area["id"]),
                    )
                    summary["relinked"] += 1
                    changed = True
                    break

            if changed:
                continue

            for section in sections:
                linked = conn.execute(
                    """SELECT id FROM yamazumi_areas
                       WHERE project_id=? AND scenario_id=? AND section_id=?""",
                    (project_id, scenario_id, section["id"]),
                ).fetchone()
                if linked:
                    continue
                conn.execute(
                    """INSERT INTO yamazumi_areas
                       (id, project_id, scenario_id, section_id, name, takt_override_s, updated_at)
                       VALUES (?, ?, ?, ?, ?, NULL, ?)""",
                    (str(uuid4()), project_id, scenario_id, section["id"], section["name"], timestamp),
                )
                summary["created"] += 1
                changed = True
                break

            if not changed:
                return summary
        raise ValueError("Fishbone-to-Yamazumi links could not be repaired safely.")


def update_yamazumi_area(project_id: str, area_id: str, section_id: str | None, takt_override_s) -> None:
    takt = None if takt_override_s is None or pd.isna(takt_override_s) or str(takt_override_s).strip() == "" else float(takt_override_s)
    if takt is not None and takt <= 0:
        raise ValueError("Takt override must be greater than zero.")
    normalized_section_id = str(section_id or "").strip() or None
    with connection() as conn:
        area = conn.execute(
            """SELECT scenario_id, section_id FROM yamazumi_areas
               WHERE id=? AND project_id=?""",
            (area_id, project_id),
        ).fetchone()
        if not area:
            raise ValueError("That Yamazumi area no longer exists.")
        existing_section_id = str(area["section_id"] or "").strip() or None
        if existing_section_id and normalized_section_id != existing_section_id:
            raise ValueError(
                "This Yamazumi area is already linked from the Fishbone and cannot be relinked manually."
            )
        if normalized_section_id:
            _validate_yamazumi_area_link(
                conn, project_id, str(area["scenario_id"]), normalized_section_id, area_id
            )
        conn.execute(
            """UPDATE yamazumi_areas SET section_id=?, takt_override_s=?, updated_at=?
               WHERE id=? AND project_id=?""",
            (normalized_section_id, takt, now_iso(), area_id, project_id),
        )


def add_yamazumi_pitch(
    project_id: str,
    area_id: str,
    pitch_number: str,
    pitch_name: str = "",
    status: str = "Active",
    model_variants: list[str] | None = None,
    pitch_type: str = "Pitch",
) -> str:
    """Add one physical pitch address to a Yamazumi area."""
    pitch_number = str(pitch_number or "").strip()
    if not pitch_number:
        raise ValueError("Pitch address is required.")
    status = str(status or "Active").title()
    if status not in {"Active", "Blocked", "Open"}:
        raise ValueError("Pitch status must be Active, Blocked, or Open.")
    pitch_type = str(pitch_type or "Pitch").strip().title()
    if pitch_type not in {"Pitch", "Waterspider", "Subassembly", "Kitter", "Repacker"}:
        raise ValueError("Choose a valid pitch type.")
    timestamp = now_iso()
    variants = list(dict.fromkeys(str(value).strip() for value in (model_variants or ["Base"]) if str(value).strip()))
    if not variants:
        raise ValueError("Choose at least one model variant for the pitch.")
    pitch_id = str(uuid4())
    try:
        with connection() as conn:
            valid_area = conn.execute(
                "SELECT 1 FROM yamazumi_areas WHERE id=? AND project_id=?", (area_id, project_id)
            ).fetchone()
            if not valid_area:
                raise ValueError("That Yamazumi area no longer exists.")
            sequence = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 10 FROM yamazumi_pitches WHERE project_id=? AND area_id=?",
                (project_id, area_id),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO yamazumi_pitches
                (id, project_id, area_id, pitch_number, pitch_name, status, sequence, model_variants, pitch_type, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pitch_id, project_id, area_id, pitch_number, str(pitch_name or "").strip(), status, sequence, json.dumps(variants), pitch_type, timestamp),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"Pitch address {pitch_number} already exists in this Yamazumi area.") from exc
    return pitch_id


def add_yamazumi_element(
    project_id: str,
    area_id: str,
    pitch_id: str | None,
    values: dict,
) -> str:
    """Add one Yamazumi work element from the balancing board."""
    description = str(values.get("description") or "").strip()
    if not description:
        raise ValueError("Work description is required.")
    try:
        time_s = float(values.get("time_s") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Work-element time must be a number.") from exc
    if time_s < 0:
        raise ValueError("Work-element time cannot be negative.")
    pitch_id = str(pitch_id or "").strip() or None
    selected_variant = str(values.get("model_variant") or "Base").strip()
    work_type = str(values.get("work_type") or "Cycle").strip().title()
    if work_type not in {"Cycle", "Periodic", "Fluctuation"}:
        raise ValueError("Work type must be Cycle, Periodic, or Fluctuation.")
    allowed_flags = set(active_yamazumi_flags(project_id))
    flags = list(dict.fromkeys(
        str(flag) for flag in values.get("flags", []) if str(flag) in allowed_flags
    ))
    element_id = str(uuid4())
    timestamp = now_iso()
    with connection() as conn:
        if pitch_id:
            active_pitch = conn.execute(
                """SELECT id, model_variants FROM yamazumi_pitches
                   WHERE id=? AND project_id=? AND area_id=? AND status='Active'""",
                (pitch_id, project_id, area_id),
            ).fetchone()
            if not active_pitch:
                raise ValueError("Work can only be added to an Active pitch.")
            pitch_variants = list(dict.fromkeys(
                str(value).strip()
                for value in json.loads(active_pitch["model_variants"] or "[]")
                if str(value).strip()
            ))
            if selected_variant not in pitch_variants:
                pitch_variants.append(selected_variant)
                conn.execute(
                    """UPDATE yamazumi_pitches SET model_variants=?, updated_at=?
                       WHERE id=? AND project_id=? AND area_id=?""",
                    (json.dumps(pitch_variants), timestamp, pitch_id, project_id, area_id),
                )
        sequence = conn.execute(
            """SELECT COALESCE(MAX(sequence), 0) + 10 FROM yamazumi_elements
               WHERE project_id=? AND area_id=? AND pitch_id IS ?""",
            (project_id, area_id, pitch_id),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO yamazumi_elements
               (id, project_id, area_id, pitch_id, model_variant, work_type, description,
                time_s, work_region, flags, sequence, source, process_sync_status, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Interactive board', 'Needs IE review', ?)""",
            (
                element_id, project_id, area_id, pitch_id,
                selected_variant,
                work_type, description, time_s,
                str(values.get("work_region") or "None").strip(), json.dumps(flags), sequence, timestamp,
            ),
        )
    return element_id


def update_yamazumi_pitch(project_id: str, area_id: str, pitch_id: str, values: dict) -> None:
    """Update one pitch from the interactive board without replacing the area table."""
    pitch_number = str(values.get("pitch_number") or "").strip()
    if not pitch_number:
        raise ValueError("Pitch address is required.")
    status = str(values.get("status") or "Active").title()
    if status not in {"Active", "Blocked", "Open"}:
        raise ValueError("Pitch status must be Active, Blocked, or Open.")
    pitch_type = str(values.get("pitch_type") or "Pitch").strip().title()
    if pitch_type not in {"Pitch", "Waterspider", "Subassembly", "Kitter", "Repacker"}:
        raise ValueError("Choose a valid pitch type.")
    variants = list(
        dict.fromkeys(
            str(value).strip()
            for value in (values.get("model_variants") or [])
            if str(value).strip()
        )
    )
    if not variants:
        raise ValueError("Choose at least one model variant for the pitch.")
    with connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM yamazumi_pitches WHERE id=? AND project_id=? AND area_id=?",
            (pitch_id, project_id, area_id),
        ).fetchone()
        if not existing:
            raise ValueError("That pitch no longer exists.")
        assigned = conn.execute(
            "SELECT model_variant FROM yamazumi_elements WHERE pitch_id=?", (pitch_id,)
        ).fetchall()
        if status != "Active" and assigned:
            raise ValueError("Move work out of this pitch before changing it to Open or Blocked.")
        missing_used = {str(row[0]) for row in assigned} - set(variants)
        if missing_used:
            raise ValueError(
                "This pitch still contains work for: "
                + ", ".join(sorted(missing_used))
                + ". Move or retag that work first."
            )
        try:
            conn.execute(
                """UPDATE yamazumi_pitches
                   SET pitch_number=?, pitch_name=?, status=?, model_variants=?, pitch_type=?, updated_at=?
                   WHERE id=? AND project_id=? AND area_id=?""",
                (
                    pitch_number,
                    str(values.get("pitch_name") or "").strip(),
                    status,
                    json.dumps(variants),
                    pitch_type,
                    now_iso(),
                    pitch_id,
                    project_id,
                    area_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Pitch address {pitch_number} already exists in this Yamazumi area.") from exc


def update_yamazumi_element(project_id: str, area_id: str, element_id: str, values: dict) -> None:
    """Update one work element from an interactive pitch card."""
    description = str(values.get("description") or "").strip()
    if not description:
        raise ValueError("Work description is required.")
    try:
        time_s = float(values.get("time_s") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Work-element time must be a number.") from exc
    if time_s < 0:
        raise ValueError("Work-element time cannot be negative.")
    pitch_id = str(values.get("pitch_id") or "").strip() or None
    model_variant = str(values.get("model_variant") or "Base").strip()
    work_type = str(values.get("work_type") or "Cycle").strip().title()
    if work_type not in {"Cycle", "Periodic", "Fluctuation"}:
        raise ValueError("Work type must be Cycle, Periodic, or Fluctuation.")
    allowed_flags = set(yamazumi_flag_names(project_id))
    flags = list(dict.fromkeys(
        str(flag) for flag in values.get("flags", []) if str(flag) in allowed_flags
    ))
    with connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM yamazumi_elements WHERE id=? AND project_id=? AND area_id=?",
            (element_id, project_id, area_id),
        ).fetchone()
        if not existing:
            raise ValueError("That work element no longer exists.")
        if pitch_id:
            destination = conn.execute(
                """SELECT model_variants FROM yamazumi_pitches
                   WHERE id=? AND project_id=? AND area_id=? AND status='Active'""",
                (pitch_id, project_id, area_id),
            ).fetchone()
            if not destination:
                raise ValueError("Work can only be assigned to an Active pitch.")
            if model_variant not in json.loads(destination[0] or "[]"):
                raise ValueError("Choose a model variant enabled for the destination pitch.")
        conn.execute(
            """UPDATE yamazumi_elements
               SET pitch_id=?, model_variant=?, work_type=?, description=?, time_s=?,
                   work_region=?, flags=?, process_sync_status='Needs IE review', updated_at=?
               WHERE id=? AND project_id=? AND area_id=?""",
            (
                pitch_id,
                model_variant,
                work_type,
                description,
                time_s,
                str(values.get("work_region") or "None").strip(),
                json.dumps(flags),
                now_iso(),
                element_id,
                project_id,
                area_id,
            ),
        )


def delete_yamazumi_element(project_id: str, area_id: str, element_id: str) -> None:
    """Delete one Yamazumi work element from the selected area."""
    with connection() as conn:
        deleted = conn.execute(
            "DELETE FROM yamazumi_elements WHERE id=? AND project_id=? AND area_id=?",
            (element_id, project_id, area_id),
        ).rowcount
        if not deleted:
            raise ValueError("That work element no longer exists.")


def delete_yamazumi_pitch(project_id: str, area_id: str, pitch_id: str) -> int:
    """Delete one pitch and return its work elements to the unassigned pool."""
    timestamp = now_iso()
    with connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM yamazumi_pitches WHERE id=? AND project_id=? AND area_id=?",
            (pitch_id, project_id, area_id),
        ).fetchone()
        if not existing:
            raise ValueError("That pitch no longer exists.")
        moved = conn.execute(
            "SELECT COUNT(*) FROM yamazumi_elements WHERE pitch_id=?", (pitch_id,)
        ).fetchone()[0]
        conn.execute(
            """UPDATE yamazumi_elements
               SET pitch_id=NULL, process_sync_status='Needs IE review', updated_at=?
               WHERE pitch_id=?""",
            (timestamp, pitch_id),
        )
        conn.execute(
            "DELETE FROM yamazumi_pitches WHERE id=? AND project_id=? AND area_id=?",
            (pitch_id, project_id, area_id),
        )
    return int(moved)


def replace_yamazumi_pitches(project_id: str, area_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "pitch_number", "pitch_name", "status", "sequence", "model_variants", "pitch_type"}
    if not required.issubset(edited.columns):
        raise ValueError("The pitch table is missing required columns.")
    records = edited.to_dict("records")
    numbers = [str(row.get("pitch_number") or "").strip() for row in records]
    if any(not number for number in numbers):
        raise ValueError("Every pitch needs an address/number.")
    if len({number.casefold() for number in numbers}) != len(numbers):
        raise ValueError("Pitch addresses must be unique within a Yamazumi area.")
    allowed = {"Active", "Blocked", "Open"}
    timestamp = now_iso()
    with connection() as conn:
        existing = {row[0] for row in conn.execute(
            "SELECT id FROM yamazumi_pitches WHERE project_id=? AND area_id=?", (project_id, area_id)
        )}
        kept: set[str] = set()
        for index, row in enumerate(records, start=1):
            pitch_id = str(row.get("id") or "").strip() or str(uuid4())
            status = str(row.get("status") or "Active").title()
            if status not in allowed:
                raise ValueError("Pitch status must be Active, Blocked, or Open.")
            pitch_type = str(row.get("pitch_type") or "Pitch").strip().title()
            if pitch_type not in {"Pitch", "Waterspider", "Subassembly", "Kitter", "Repacker"}:
                raise ValueError("Choose a valid pitch type for every pitch.")
            if status != "Active":
                assigned_count = conn.execute(
                    "SELECT COUNT(*) FROM yamazumi_elements WHERE pitch_id=?", (pitch_id,)
                ).fetchone()[0]
                if assigned_count:
                    raise ValueError(
                        f"Move work out of pitch {numbers[index - 1]} before changing it to {status}."
                    )
            raw_variants = row.get("model_variants") or []
            variants = raw_variants if isinstance(raw_variants, list) else json.loads(str(raw_variants) or "[]")
            variants = list(dict.fromkeys(str(value).strip() for value in variants if str(value).strip()))
            if not variants:
                raise ValueError(f"Choose at least one model variant for pitch {numbers[index - 1]}.")
            used_variants = {
                str(used[0]) for used in conn.execute(
                    "SELECT DISTINCT model_variant FROM yamazumi_elements WHERE pitch_id=?", (pitch_id,)
                ).fetchall()
            }
            missing_used = used_variants - set(variants)
            if missing_used:
                raise ValueError(
                    f"Pitch {numbers[index - 1]} still contains work for: {', '.join(sorted(missing_used))}. Move or retag that work first."
                )
            kept.add(pitch_id)
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status, sequence, model_variants, pitch_type, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET pitch_number=excluded.pitch_number,
                   pitch_name=excluded.pitch_name, status=excluded.status,
                   sequence=excluded.sequence, model_variants=excluded.model_variants,
                   pitch_type=excluded.pitch_type,
                   updated_at=excluded.updated_at""",
                (pitch_id, project_id, area_id, numbers[index - 1], str(row.get("pitch_name") or "").strip(),
                 status, int(row.get("sequence") or index * 10), json.dumps(variants), pitch_type, timestamp),
            )
        removed = existing - kept
        if removed:
            placeholders = ",".join("?" for _ in removed)
            conn.execute(f"UPDATE yamazumi_elements SET pitch_id=NULL, process_sync_status='Needs IE review', updated_at=? WHERE pitch_id IN ({placeholders})", (timestamp, *removed))
            conn.execute(f"DELETE FROM yamazumi_pitches WHERE id IN ({placeholders})", tuple(removed))
    return len(records)


def generate_yamazumi_pitch_range(
    project_id: str,
    area_id: str,
    first_address: str,
    last_address: str,
    number_mode: str = "All numbers",
    status: str = "Active",
    model_variants: list[str] | None = None,
    pitch_type: str = "Pitch",
) -> int:
    """Generate physical pitch addresses between matching numeric-suffix endpoints."""
    import re

    first = str(first_address or "").strip()
    last = str(last_address or "").strip()
    first_match = re.match(r"^(.*?)(\d+)$", first)
    last_match = re.match(r"^(.*?)(\d+)$", last)
    if not first_match or not last_match:
        raise ValueError("First and last pitch addresses must end in a number.")
    if first_match.group(1) != last_match.group(1):
        raise ValueError("First and last pitch addresses must use the same prefix.")
    start, end = int(first_match.group(2)), int(last_match.group(2))
    if end < start:
        raise ValueError("The last pitch number must be greater than or equal to the first.")
    if number_mode not in {"All numbers", "Odd only", "Even only"}:
        raise ValueError("Choose All numbers, Odd only, or Even only.")
    status = str(status or "Active").title()
    if status not in {"Active", "Blocked", "Open"}:
        raise ValueError("Pitch status must be Active, Blocked, or Open.")
    pitch_type = str(pitch_type or "Pitch").strip().title()
    if pitch_type not in {"Pitch", "Waterspider", "Subassembly", "Kitter", "Repacker"}:
        raise ValueError("Choose a valid pitch type.")
    prefix = first_match.group(1)
    width = max(len(first_match.group(2)), len(last_match.group(2)))
    values = list(range(start, end + 1))
    if number_mode == "Odd only":
        values = [value for value in values if value % 2 == 1]
    elif number_mode == "Even only":
        values = [value for value in values if value % 2 == 0]
    if not values:
        raise ValueError("That range contains no pitch numbers for the selected numbering option.")
    timestamp = now_iso()
    variants = list(dict.fromkeys(str(value).strip() for value in (model_variants or ["Base"]) if str(value).strip()))
    if not variants:
        raise ValueError("Choose at least one model variant for the generated pitches.")
    with connection() as conn:
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM yamazumi_pitches WHERE project_id=? AND area_id=?",
            (project_id, area_id),
        ).fetchone()[0]
        created = 0
        for offset, value in enumerate(values, start=1):
            address = f"{prefix}{value:0{width}d}"
            exists = conn.execute(
                "SELECT 1 FROM yamazumi_pitches WHERE project_id=? AND area_id=? AND pitch_number=?",
                (project_id, area_id, address),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status, sequence, model_variants, pitch_type, updated_at)
                   VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?)""",
                (str(uuid4()), project_id, area_id, address, status, next_sequence + offset * 10, json.dumps(variants), pitch_type, timestamp),
            )
            created += 1
    return created


def replace_yamazumi_elements(project_id: str, area_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "pitch_id", "model_variant", "work_type", "description", "time_s", "work_region", "flags", "sequence"}
    if not required.issubset(edited.columns):
        raise ValueError("The Yamazumi work-element table is missing required columns.")
    records = edited.to_dict("records")
    timestamp = now_iso()
    allowed_flags = set(yamazumi_flag_names(project_id))
    valid_pitches = {
        str(row["id"]) for row in query(
            "SELECT id FROM yamazumi_pitches WHERE project_id=? AND area_id=? AND status='Active'",
            (project_id, area_id),
        )
    }
    with connection() as conn:
        existing = {row[0] for row in conn.execute("SELECT id FROM yamazumi_elements WHERE project_id=? AND area_id=?", (project_id, area_id))}
        kept: set[str] = set()
        for index, row in enumerate(records, start=1):
            description = str(row.get("description") or "").strip()
            if not description:
                raise ValueError("Every Yamazumi work element needs a description.")
            time_s = float(row.get("time_s") or 0)
            if time_s < 0:
                raise ValueError("Work-element time cannot be negative.")
            element_id = str(row.get("id") or "").strip() or str(uuid4())
            pitch_id = str(row.get("pitch_id") or "").strip() or None
            if pitch_id and pitch_id not in valid_pitches:
                raise ValueError("Choose an Active pitch from the selected Yamazumi area.")
            model_variant = str(row.get("model_variant") or "Base").strip()
            work_type = str(row.get("work_type") or "Cycle").strip().title()
            if work_type not in {"Cycle", "Periodic", "Fluctuation"}:
                raise ValueError("Work type must be Cycle, Periodic, or Fluctuation.")
            if pitch_id:
                pitch_variants_row = conn.execute(
                    "SELECT model_variants FROM yamazumi_pitches WHERE id=?", (pitch_id,)
                ).fetchone()
                pitch_variants = json.loads(pitch_variants_row[0] or "[]")
                if model_variant not in pitch_variants:
                    raise ValueError("Each work element's model variant must be enabled for its pitch.")
            raw_flags = row.get("flags") or []
            flags = raw_flags if isinstance(raw_flags, list) else [item.strip() for item in str(raw_flags).split(",") if item.strip()]
            invalid_flags = {str(flag) for flag in flags} - allowed_flags
            if invalid_flags:
                raise ValueError(
                    "Define or reactivate these Yamazumi flags before saving: "
                    + ", ".join(sorted(invalid_flags))
                )
            flags = list(dict.fromkeys(str(flag) for flag in flags))
            kept.add(element_id)
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, model_variant, work_type, description,
                    time_s, work_region, flags, sequence, source, process_element_id,
                    process_sync_status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET pitch_id=excluded.pitch_id,
                    model_variant=excluded.model_variant, work_type=excluded.work_type,
                    description=excluded.description, time_s=excluded.time_s,
                    work_region=excluded.work_region, flags=excluded.flags,
                    sequence=excluded.sequence, process_sync_status='Needs IE review',
                    updated_at=excluded.updated_at""",
                (element_id, project_id, area_id, pitch_id, model_variant,
                 work_type, description, time_s,
                 str(row.get("work_region") or "None").strip(), json.dumps(flags),
                 int(row.get("sequence") or index * 10), str(row.get("source") or "Manual"),
                 row.get("process_element_id"), str(row.get("process_sync_status") or "Needs IE review"), timestamp),
            )
        removed = existing - kept
        if removed:
            placeholders = ",".join("?" for _ in removed)
            conn.execute(f"DELETE FROM yamazumi_elements WHERE id IN ({placeholders})", tuple(removed))
    return len(records)


def move_yamazumi_element(project_id: str, element_id: str, pitch_id: str | None) -> None:
    if pitch_id:
        valid = query(
            "SELECT id, model_variants FROM yamazumi_pitches WHERE id=? AND project_id=? AND status='Active'",
            (pitch_id, project_id),
        )
        if not valid:
            raise ValueError("Work can only be moved into an Active pitch.")
        element = query("SELECT model_variant FROM yamazumi_elements WHERE id=? AND project_id=?", (element_id, project_id))
        if not element or element[0]["model_variant"] not in json.loads(valid[0]["model_variants"] or "[]"):
            raise ValueError("Enable this work element's model variant on the destination pitch before moving it.")
    execute(
        """UPDATE yamazumi_elements SET pitch_id=?, process_sync_status='Needs IE review', updated_at=?
           WHERE id=? AND project_id=?""",
        (pitch_id or None, now_iso(), element_id, project_id),
    )


def import_yamazumi_rows(
    project_id: str,
    scenario_id: str,
    rows: pd.DataFrame,
    section_ids_by_name: dict[str, str],
) -> tuple[int, int, int]:
    required = {"Sub-Line", "Pitch_number", "Pitch_status", "Pitch_name", "Pitch_Takt_time", "Model_variant", "Work_Type", "Work_Description", "Work_Time_to_complete", "Work_region"}
    missing = required - set(rows.columns)
    if missing:
        raise ValueError(f"The Yamazumi file is missing: {', '.join(sorted(missing))}.")
    timestamp = now_iso()
    area_ids: dict[str, str] = {}
    pitch_ids: dict[tuple[str, str], str] = {}
    elements_added = 0
    flag_names_by_casefold = {
        flag.casefold(): flag for flag in active_yamazumi_flags(project_id)
    }
    for index, row in rows.iterrows():
        area_name = str(row.get("Sub-Line") or "").strip()
        pitch_number = str(row.get("Pitch_number") or "").strip()
        description = str(row.get("Work_Description") or "").strip()
        if not area_name or not pitch_number or not description:
            continue
        takt_raw = row.get("Pitch_Takt_time")
        takt = None if pd.isna(takt_raw) or str(takt_raw).strip() == "" else float(takt_raw)
        area_id = area_ids.setdefault(
            area_name,
            upsert_yamazumi_area(
                project_id, scenario_id, area_name, section_ids_by_name.get(area_name), takt
            ),
        )
        pitch_key = (area_id, pitch_number)
        if pitch_key not in pitch_ids:
            existing_pitch = query("SELECT id FROM yamazumi_pitches WHERE project_id=? AND area_id=? AND pitch_number=?", (project_id, area_id, pitch_number))
            pitch_id = str(existing_pitch[0]["id"]) if existing_pitch else str(uuid4())
            pitch_ids[pitch_key] = pitch_id
            status = str(row.get("Pitch_status") or "Active").strip().title()
            if status not in {"Active", "Blocked", "Open"}:
                status = "Active"
            execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status, sequence, model_variants, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?)
                   ON CONFLICT(id) DO UPDATE SET pitch_name=excluded.pitch_name,
                   status=excluded.status, updated_at=excluded.updated_at""",
                (pitch_id, project_id, area_id, pitch_number, str(row.get("Pitch_name") or "").strip(), status, len(pitch_ids) * 10, timestamp),
            )
        flags_text = str(row.get("Pitch_Flags") or "")
        flags = [
            flag for normalized, flag in flag_names_by_casefold.items()
            if normalized in flags_text.casefold()
        ]
        import_pitch_id = pitch_ids[pitch_key]
        import_pitch = query("SELECT status FROM yamazumi_pitches WHERE id=?", (import_pitch_id,))
        assigned_pitch_id = import_pitch_id if import_pitch and import_pitch[0]["status"] == "Active" else None
        execute(
            """INSERT INTO yamazumi_elements
               (id, project_id, area_id, pitch_id, model_variant, work_type, description,
                time_s, work_region, flags, sequence, source, process_sync_status, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Excel import', 'Needs IE review', ?)""",
            (str(uuid4()), project_id, area_id, assigned_pitch_id, str(row.get("Model_variant") or "Base").strip().title(),
             str(row.get("Work_Type") or "Cycle").strip().title(), description,
             float(row.get("Work_Time_to_complete") or 0), str(row.get("Work_region") or "None").strip(),
             json.dumps(flags), (index + 1) * 10, timestamp),
        )
        imported_variant = str(row.get("Model_variant") or "Base").strip().title()
        current_pitch = query("SELECT model_variants FROM yamazumi_pitches WHERE id=?", (import_pitch_id,))[0]
        selected_variants = json.loads(current_pitch["model_variants"] or "[]")
        if imported_variant not in selected_variants:
            selected_variants.append(imported_variant)
            execute("UPDATE yamazumi_pitches SET model_variants=? WHERE id=?", (json.dumps(selected_variants), import_pitch_id))
        elements_added += 1
    return len(area_ids), len(pitch_ids), elements_added


def reconcile_yamazumi_to_process(project_id: str, scenario_id: str, element_ids: list[str]) -> int:
    """Accept Yamazumi station/time changes while retaining IE-authored process details."""
    if not element_ids:
        return 0
    placeholders = ",".join("?" for _ in element_ids)
    timestamp = now_iso()
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT e.*, p.pitch_number, a.name AS area_name
                FROM yamazumi_elements e
                LEFT JOIN yamazumi_pitches p ON p.id=e.pitch_id
                JOIN yamazumi_areas a ON a.id=e.area_id
                WHERE e.project_id=? AND a.scenario_id=? AND e.id IN ({placeholders})""",
            (project_id, scenario_id, *element_ids),
        ).fetchall()
        for row in rows:
            station = str(row["pitch_number"] or "Unassigned")
            process_id = str(row["process_element_id"] or "").strip()
            if process_id:
                exists = conn.execute(
                    "SELECT 1 FROM work_elements WHERE id=? AND project_id=? AND scenario_id=?",
                    (process_id, project_id, scenario_id),
                ).fetchone()
            else:
                exists = None
            if exists:
                conn.execute(
                    """UPDATE work_elements SET station=?, cycle_time_s=?, model_applicability=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=?""",
                    (
                        station, float(row["time_s"] or 0),
                        "All" if str(row["model_variant"]).casefold() == "base" else str(row["model_variant"]),
                        timestamp, process_id, project_id, scenario_id,
                    ),
                )
            else:
                process_id = str(uuid4())
                next_sequence = conn.execute(
                    """SELECT COALESCE(MAX(sequence), 0) + 10 FROM work_elements
                       WHERE project_id=? AND scenario_id=?""",
                    (project_id, scenario_id),
                ).fetchone()[0]
                conn.execute(
                    """INSERT INTO work_elements
                       (id, project_id, scenario_id, sequence, station, operation, description, cycle_time_s,
                        part_number, tool, torque, quality_requirement, ergo_requirement, location,
                        conveyor_height_mm, platform_height_mm, pit_depth_mm,
                        model_applicability, status, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '', '', ?, '', ?, NULL, NULL, NULL, ?, 'Draft', ?)""",
                    (
                        process_id, project_id, scenario_id, next_sequence, station,
                        str(row["description"]), f"Yamazumi area: {row['area_name']}",
                        float(row["time_s"] or 0),
                        "CTQ" if "CTQ" in json.loads(row["flags"] or "[]") else "",
                        station,
                        "All" if str(row["model_variant"]).casefold() == "base" else str(row["model_variant"]),
                        timestamp,
                    ),
                )
            conn.execute(
                """UPDATE yamazumi_elements SET process_element_id=?, process_sync_status='Synced', updated_at=?
                   WHERE id=? AND project_id=?""",
                (process_id, timestamp, row["id"], project_id),
            )
    return len(rows)


def project_table(
    table: str,
    project_id: str,
    order_by: str = "updated_at DESC",
    scenario_id: str | None = None,
) -> pd.DataFrame:
    allowed = {"parts", "work_elements", "concerns", "fishbone_nodes", "assembly_sections", "fishbone_part_assignments"}
    if table not in allowed:
        raise ValueError("Unsupported table")
    if table == "work_elements" and scenario_id:
        return pd.DataFrame(query(
            f"SELECT * FROM {table} WHERE project_id=? AND scenario_id=? ORDER BY {order_by}",
            (project_id, scenario_id),
        ))
    return pd.DataFrame(query(f"SELECT * FROM {table} WHERE project_id = ? ORDER BY {order_by}", (project_id,)))


def create_project(
    name: str,
    program: str,
    owner: str,
    takt_time_s: float,
    product_line: str = "",
) -> str:
    project_id, timestamp = str(uuid4()), now_iso()
    execute(
        """INSERT INTO projects
           (id, name, program, product_line, owner, revision, status,
            takt_time_s, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'A', 'Draft', ?, '', ?, ?)""",
        (
            project_id, name.strip(), program.strip(), product_line.strip(),
            owner.strip(), takt_time_s, timestamp, timestamp,
        ),
    )
    return project_id


def update_project(project_id: str, values: dict) -> None:
    fields = [
        "name", "program", "product_line", "owner", "revision", "status",
        "takt_time_s", "notes",
    ]
    execute(
        f"UPDATE projects SET {', '.join(f'{field} = ?' for field in fields)}, updated_at = ? WHERE id = ?",
        tuple(values.get(field, "") for field in fields) + (now_iso(), project_id),
    )


def normalize_model_applicability(value) -> str:
    if isinstance(value, (list, tuple, set)):
        selected = [str(item).strip() for item in value if str(item).strip()]
        if not selected or "All" in selected or "All models" in selected:
            return "All"
        return ", ".join(dict.fromkeys(selected))
    text = "" if value is None or pd.isna(value) else str(value).strip()
    return text or "All"


def upsert_part(project_id: str, values: dict, part_id: str | None = None) -> str:
    timestamp = now_iso()
    part_id = part_id or str(uuid4())
    quantity = values.get("quantity", 1)
    quantity = None if quantity is None or pd.isna(quantity) or str(quantity).strip() == "" else float(quantity)
    execute(
        """INSERT INTO parts (id, project_id, part_number, description, quantity, revision, source,
           image_path, model_applicability, notes, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(project_id, part_number) DO UPDATE SET description=excluded.description,
           quantity=excluded.quantity, revision=excluded.revision, source=excluded.source,
           model_applicability=excluded.model_applicability, notes=excluded.notes, updated_at=excluded.updated_at""",
        (part_id, project_id, values["part_number"].strip(), values.get("description", "").strip(),
         quantity, values.get("revision", "").strip(), values.get("source", "Manual"),
         values.get("image_path", ""), normalize_model_applicability(values.get("model_applicability", "All")),
         values.get("notes", "").strip(), timestamp),
    )
    rows = query("SELECT id FROM parts WHERE project_id = ? AND part_number = ?", (project_id, values["part_number"].strip()))
    return rows[0]["id"]


def update_part_rows(project_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "part_number", "description", "quantity", "revision", "model_applicability", "notes"}
    if not required.issubset(edited.columns):
        raise ValueError("The editable parts table is missing required columns.")
    part_numbers = edited["part_number"].fillna("").astype(str).str.strip()
    if part_numbers.eq("").any():
        raise ValueError("Every part must have a part number.")
    if part_numbers.duplicated().any():
        duplicates = ", ".join(sorted(part_numbers[part_numbers.duplicated(keep=False)].unique()))
        raise ValueError(f"Duplicate part numbers are not allowed: {duplicates}")
    def clean_text(value) -> str:
        return "" if value is None or pd.isna(value) else str(value).strip()

    timestamp = now_iso()
    with connection() as conn:
        existing_ids = {
            str(existing[0]) for existing in conn.execute(
                "SELECT id FROM parts WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        for _, row in edited.iterrows():
            part_id = (
                str(row["id"])
                if row.get("id") is not None and not pd.isna(row.get("id")) and str(row.get("id")).strip()
                else str(uuid4())
            )
            quantity = row.get("quantity")
            quantity = None if quantity is None or pd.isna(quantity) else float(quantity)
            values = (
                str(row["part_number"]).strip(), clean_text(row.get("description")), quantity,
                clean_text(row.get("revision")), normalize_model_applicability(row.get("model_applicability")),
                clean_text(row.get("notes")), timestamp,
            )
            if part_id in existing_ids:
                conn.execute(
                    """UPDATE parts SET part_number=?, description=?, quantity=?, revision=?,
                       model_applicability=?, notes=?, updated_at=? WHERE id=? AND project_id=?""",
                    (*values, part_id, project_id),
                )
            else:
                conn.execute(
                    """INSERT INTO parts
                       (id, project_id, part_number, description, quantity, revision, source,
                        image_path, model_applicability, notes, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)""",
                    (part_id, project_id, values[0], values[1], values[2], values[3],
                     clean_text(row.get("source")) or "Manual", values[4], values[5], values[6]),
                )
    return len(edited)


def delete_project_part(project_id: str, part_id: str) -> str:
    """Delete one catalog part and its cascading fishbone uses and image records."""
    with connection() as conn:
        part = conn.execute(
            "SELECT part_number, image_path FROM parts WHERE id=? AND project_id=?",
            (part_id, project_id),
        ).fetchone()
        if not part:
            raise ValueError("That part no longer exists.")
        supplemental_paths = [row[0] for row in conn.execute(
            "SELECT image_path FROM part_images WHERE part_id=?", (part_id,)
        ).fetchall()]
        conn.execute("DELETE FROM parts WHERE id=? AND project_id=?", (part_id, project_id))
    for raw_path in [part["image_path"], *supplemental_paths]:
        if raw_path:
            path = Path(raw_path)
            try:
                if path.exists() and path.is_file() and UPLOAD_DIR.resolve() in path.resolve().parents:
                    path.unlink()
            except OSError:
                pass
    return str(part["part_number"])


def set_part_image(part_id: str, uploaded_file) -> str:
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Use PNG, JPG, JPEG, or WEBP images.")
    target = UPLOAD_DIR / f"{part_id}{suffix}"
    target.write_bytes(uploaded_file.getvalue())
    execute("UPDATE parts SET image_path = ?, updated_at = ? WHERE id = ?", (str(target), now_iso(), part_id))
    return str(target)


def add_part_image(part_id: str, uploaded_file, image_type: str, caption: str) -> str:
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Use PNG, JPG, JPEG, or WEBP images.")
    image_id = str(uuid4())
    target = UPLOAD_DIR / f"{part_id}_{image_id}{suffix}"
    target.write_bytes(uploaded_file.getvalue())
    execute(
        "INSERT INTO part_images VALUES (?, ?, ?, ?, ?, ?)",
        (image_id, part_id, str(target), image_type, caption.strip(), now_iso()),
    )
    return str(target)


def part_images(part_id: str) -> list[dict]:
    return query("SELECT * FROM part_images WHERE part_id = ? ORDER BY created_at", (part_id,))


def assembly_sections(project_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        "SELECT * FROM assembly_sections WHERE project_id = ? ORDER BY sequence, name",
        (project_id,),
    ))


def add_assembly_section(
    project_id: str,
    name: str,
    section_type: str,
    parent_id: str | None,
    description: str,
) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Section or subassembly name is required.")
    if section_type not in {"Main spine", "Subassembly"}:
        raise ValueError("Choose Main spine or Subassembly.")
    parent_id = parent_id or None
    if section_type == "Subassembly" and not parent_id:
        raise ValueError("A subassembly must have a parent assembly.")
    if section_type == "Main spine":
        parent_id = None
    timestamp = now_iso()
    section_id = str(uuid4())
    try:
        with connection() as conn:
            next_sequence = conn.execute(
                """SELECT COALESCE(MAX(sequence), 0) + 10 FROM assembly_sections
                   WHERE project_id=? AND parent_id IS ?""",
                (project_id, parent_id),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO assembly_sections
                   (id, project_id, name, section_type, parent_id, sequence, description, active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (section_id, project_id, name, section_type, parent_id, next_sequence, description.strip(), timestamp, timestamp),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"A section named {name} already exists in this project.") from exc
    return section_id


def reorder_assembly_section(project_id: str, section_id: str, action: str) -> bool:
    allowed = {"Move earlier", "Move later", "Move to start", "Move to end"}
    if action not in allowed:
        raise ValueError("Unsupported framework reorder action.")
    with connection() as conn:
        target = conn.execute(
            "SELECT id, parent_id FROM assembly_sections WHERE id=? AND project_id=?",
            (section_id, project_id),
        ).fetchone()
        if not target:
            raise ValueError("The selected framework item no longer exists.")
        siblings = conn.execute(
            """SELECT id FROM assembly_sections WHERE project_id=? AND parent_id IS ?
               ORDER BY sequence, name""",
            (project_id, target["parent_id"]),
        ).fetchall()
        ordered_ids = [row["id"] for row in siblings]
        old_index = ordered_ids.index(section_id)
        new_index = old_index
        if action == "Move earlier":
            new_index = max(0, old_index - 1)
        elif action == "Move later":
            new_index = min(len(ordered_ids) - 1, old_index + 1)
        elif action == "Move to start":
            new_index = 0
        elif action == "Move to end":
            new_index = len(ordered_ids) - 1
        ordered_ids.insert(new_index, ordered_ids.pop(old_index))
        timestamp = now_iso()
        for index, sibling_id in enumerate(ordered_ids, start=1):
            conn.execute(
                "UPDATE assembly_sections SET sequence=?, updated_at=? WHERE id=?",
                (index * 10, timestamp, sibling_id),
            )
    return new_index != old_index


def update_assembly_section_rows(
    project_id: str,
    edited: pd.DataFrame,
    *,
    _connection: sqlite3.Connection | None = None,
) -> int:
    required = {"id", "name", "section_type", "parent_id", "sequence", "description", "active"}
    if not required.issubset(edited.columns):
        raise ValueError("The assembly framework table is missing required columns.")
    records = edited.to_dict("records")
    ids = {str(row["id"]) for row in records}
    names = [str(row.get("name") or "").strip() for row in records]
    if any(not name for name in names):
        raise ValueError("Every framework row needs a name.")
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("Framework names must be unique within the project.")

    parent_by_id: dict[str, str | None] = {}
    for row in records:
        section_id = str(row["id"])
        section_type = str(row.get("section_type") or "")
        parent_id = row.get("parent_id")
        parent_id = None if parent_id is None or pd.isna(parent_id) or not str(parent_id).strip() else str(parent_id)
        if section_type not in {"Main spine", "Subassembly"}:
            raise ValueError("Each framework row must be Main spine or Subassembly.")
        if section_type == "Main spine":
            parent_id = None
        elif not parent_id:
            raise ValueError(f"Subassembly {row['name']} needs a parent assembly.")
        if parent_id == section_id or (parent_id and parent_id not in ids):
            raise ValueError(f"Choose a valid parent for {row['name']}.")
        parent_by_id[section_id] = parent_id

    for section_id in ids:
        visited: set[str] = set()
        cursor = section_id
        while cursor:
            if cursor in visited:
                raise ValueError("The assembly framework cannot contain a circular parent relationship.")
            visited.add(cursor)
            cursor = parent_by_id.get(cursor)

    timestamp = now_iso()
    try:
        with (nullcontext(_connection) if _connection is not None else connection()) as conn:
            for row in records:
                section_id = str(row["id"])
                conn.execute(
                    """UPDATE assembly_sections SET name=?, section_type=?, parent_id=?, sequence=?,
                       description=?, active=?, updated_at=? WHERE id=? AND project_id=?""",
                    (
                        str(row["name"]).strip(), str(row["section_type"]), parent_by_id[section_id],
                        int(row.get("sequence") or 0), str(row.get("description") or "").strip(),
                        1 if bool(row.get("active")) else 0, timestamp, section_id, project_id,
                    ),
                )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Framework names must be unique within the project.") from exc
    return len(records)


def fishbone_part_assignments(project_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT a.id, a.project_id, a.part_id, a.section_id, a.sequence, a.quantity,
                  a.use_description, a.notes,
                  a.updated_at, p.part_number, p.description, p.revision, p.model_applicability,
                  s.name AS section_name
           FROM fishbone_part_assignments a
           JOIN parts p ON p.id = a.part_id
           JOIN assembly_sections s ON s.id = a.section_id
           WHERE a.project_id = ? ORDER BY s.sequence, a.sequence, p.part_number""",
        (project_id,),
    ))


def assign_parts_to_section(
    project_id: str,
    part_ids: list[str],
    section_id: str,
    use_description: str = "",
    *,
    allow_additional_use: bool = False,
    quantities_by_part: dict[str, int] | None = None,
) -> int:
    if not part_ids:
        return 0
    timestamp = now_iso()
    count = 0
    with connection() as conn:
        section = conn.execute(
            "SELECT id FROM assembly_sections WHERE id=? AND project_id=? AND active=1",
            (section_id, project_id),
        ).fetchone()
        if not section:
            raise ValueError("Choose an active assembly section.")
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM fishbone_part_assignments WHERE project_id=? AND section_id=?",
            (project_id, section_id),
        ).fetchone()[0]
        for part_id in dict.fromkeys(part_ids):
            part = conn.execute("SELECT quantity FROM parts WHERE id=? AND project_id=?", (part_id, project_id)).fetchone()
            if not part:
                continue
            already_placed = conn.execute(
                "SELECT 1 FROM fishbone_part_assignments WHERE project_id=? AND part_id=? LIMIT 1",
                (project_id, part_id),
            ).fetchone()
            if already_placed and not allow_additional_use:
                continue
            next_sequence += 10
            requested_quantity = (
                quantities_by_part.get(part_id)
                if quantities_by_part and part_id in quantities_by_part
                else part["quantity"]
            )
            numeric_quantity = float(requested_quantity if requested_quantity is not None else 1)
            if not numeric_quantity.is_integer() or numeric_quantity < 0:
                raise ValueError("Placement quantities must be non-negative whole numbers.")
            quantity = int(numeric_quantity)
            assignment_id = str(uuid4())
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, part_id, section_id, sequence, quantity, use_description, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, '', ?)""",
                (
                    assignment_id, project_id, part_id, section_id, next_sequence,
                    quantity, use_description.strip(), timestamp,
                ),
            )
            count += 1
    return count


def delete_fishbone_part_assignment(project_id: str, assignment_id: str) -> bool:
    """Delete one fishbone use while leaving its master Parts record untouched."""
    with connection() as conn:
        cursor = conn.execute(
            "DELETE FROM fishbone_part_assignments WHERE id=? AND project_id=?",
            (assignment_id, project_id),
        )
        return cursor.rowcount > 0


def replace_fishbone_part_assignments(
    project_id: str,
    edited: pd.DataFrame,
    *,
    _connection: sqlite3.Connection | None = None,
) -> int:
    required = {"id", "part_id", "section_id", "sequence", "quantity", "use_description", "notes"}
    if not required.issubset(edited.columns):
        raise ValueError("The part assignment table is missing required columns.")
    timestamp = now_iso()
    with (nullcontext(_connection) if _connection is not None else connection()) as conn:
        valid_parts = {row[0] for row in conn.execute("SELECT id FROM parts WHERE project_id=?", (project_id,))}
        valid_sections = {row[0] for row in conn.execute("SELECT id FROM assembly_sections WHERE project_id=?", (project_id,))}
        records = []
        for _, row in edited.iterrows():
            part_id, section_id = str(row["part_id"]), str(row["section_id"])
            if part_id not in valid_parts or section_id not in valid_sections:
                raise ValueError("Every assignment must reference a valid project part and assembly section.")
            quantity = float(row.get("quantity") or 0)
            if not quantity.is_integer():
                raise ValueError("Fishbone quantities must be whole numbers.")
            records.append((
                str(row.get("id") or uuid4()), project_id, part_id, section_id,
                int(row.get("sequence") or 0), int(quantity),
                str(row.get("use_description") or "").strip(),
                str(row.get("notes") or "").strip(), timestamp,
            ))
        conn.execute("DELETE FROM fishbone_part_assignments WHERE project_id=?", (project_id,))
        conn.executemany(
            """INSERT INTO fishbone_part_assignments
               (id, project_id, part_id, section_id, sequence, quantity, use_description, notes, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            records,
        )
    return len(records)


def save_fishbone_plan(
    project_id: str,
    framework: pd.DataFrame | None,
    assignments: pd.DataFrame | None,
) -> tuple[int, int]:
    """Validate and save framework and placement edits in one transaction."""
    with connection() as conn:
        framework_count = (
            update_assembly_section_rows(project_id, framework, _connection=conn)
            if framework is not None
            else 0
        )
        assignment_count = (
            replace_fishbone_part_assignments(project_id, assignments, _connection=conn)
            if assignments is not None
            else 0
        )
    return framework_count, assignment_count


def replace_fishbone_nodes(project_id: str, edited: pd.DataFrame) -> None:
    fields = ["source_row", "sequence", "parent_id", "depth", "part_number", "description", "quantity",
              "branch_name", "subsystem", "model_feature", "comments", "tracker_status", "planned_area", "source", "raw_levels", "review_status",
              "pits_id", "applicable_models", "source_changed"]
    with connection() as conn:
        conn.execute("DELETE FROM fishbone_nodes WHERE project_id = ?", (project_id,))
        for idx, row in edited.iterrows():
            part_number = "" if pd.isna(row.get("part_number", "")) else str(row.get("part_number", "")).strip()
            description = "" if pd.isna(row.get("description", "")) else str(row.get("description", "")).strip()
            if not part_number and not description:
                continue
            values = []
            for field in fields:
                value = row.get(field, "")
                if field == "applicable_models" and isinstance(value, (list, tuple, set)):
                    value = json.dumps(list(value))
                if pd.isna(value):
                    value = None if field in {"source_row", "parent_id", "quantity"} else (1 if field == "depth" else (0 if field == "source_changed" else ""))
                values.append(value)
            node_id = str(row.get("id")) if row.get("id") and not pd.isna(row.get("id")) else str(uuid4())
            conn.execute(
                f"INSERT INTO fishbone_nodes (id, project_id, {', '.join(fields)}, updated_at) VALUES ({', '.join(['?'] * (len(fields) + 3))})",
                (node_id, project_id, *values, now_iso()),
            )


def import_fishbone_nodes(project_id: str, nodes: pd.DataFrame, replace: bool = True) -> int:
    timestamp = now_iso()
    with connection() as conn:
        if replace:
            conn.execute("DELETE FROM fishbone_nodes WHERE project_id = ?", (project_id,))
        id_by_sequence: dict[int, str] = {}
        for _, row in nodes.iterrows():
            node_id = str(uuid4())
            parent_sequence = row.get("parent_sequence")
            parent_id = id_by_sequence.get(int(parent_sequence)) if pd.notna(parent_sequence) else None
            sequence = int(row["sequence"])
            id_by_sequence[sequence] = node_id
            conn.execute(
                """INSERT INTO fishbone_nodes
                (id, project_id, source_row, sequence, parent_id, depth, part_number, description,
                 quantity, branch_name, subsystem, model_feature, comments, tracker_status,
                 planned_area, source, raw_levels, review_status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PITS import', ?, 'Needs review', ?)""",
                (node_id, project_id, int(row["source_row"]), sequence, parent_id, int(row["depth"]),
                 row["part_number"], row["description"], None, row["branch_name"],
                 row["subsystem"], row["model_feature"], row["comments"], row["tracker_status"],
                 row["planned_area"], json.dumps(row["raw_levels"], ensure_ascii=False), timestamp),
            )
    return len(nodes)


def project_models(project_id: str) -> pd.DataFrame:
    return pd.DataFrame(query("SELECT * FROM project_models WHERE project_id = ? ORDER BY model_number", (project_id,)))


def complexity_features(project_id: str) -> pd.DataFrame:
    rows = query(
        "SELECT * FROM complexity_features WHERE project_id=? ORDER BY sequence, category, name",
        (project_id,),
    )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["allowed_choices"] = frame["allowed_values"].apply(
            lambda value: ", ".join(json.loads(value or "[]"))
        )
    return frame


def complexity_tree(project_id: str) -> pd.DataFrame:
    models = project_models(project_id)
    if models.empty:
        return pd.DataFrame(columns=["model_id", "common_name", "official_model_number"])
    result = models[["id", "display_name", "model_number"]].rename(columns={
        "id": "model_id", "display_name": "common_name", "model_number": "official_model_number",
    })
    values = query(
        "SELECT model_id, feature_id, value FROM model_feature_values WHERE project_id=?",
        (project_id,),
    )
    value_map = {(str(row["model_id"]), str(row["feature_id"])): row["value"] for row in values}
    for feature in complexity_features(project_id).to_dict("records"):
        feature_id = str(feature["id"])
        result[feature_id] = result["model_id"].astype(str).map(
            lambda model_id: value_map.get((model_id, feature_id)) or None
        )
    return result


def part_feature_rules(project_id: str) -> pd.DataFrame:
    """Return saved manufacturing-feature applicability rules for project parts."""
    return pd.DataFrame(query(
        """SELECT r.part_id, r.feature_id, r.value, f.category, f.name AS feature_name
           FROM part_feature_rules r
           JOIN complexity_features f ON f.id=r.feature_id
           WHERE r.project_id=? ORDER BY f.sequence, f.category, f.name, r.value""",
        (project_id,),
    ))


def update_part_feature_rules(project_id: str, selections_by_part: dict[str, list[str]]) -> int:
    """Save feature rules and resolve them to official model numbers for downstream use."""
    features = complexity_features(project_id)
    feature_by_id = {str(row["id"]): row for _, row in features.iterrows()}
    tree = complexity_tree(project_id)
    valid_parts = {str(row["id"]) for row in query("SELECT id FROM parts WHERE project_id=?", (project_id,))}
    timestamp = now_iso()
    updated = 0
    with connection() as conn:
        for part_id, raw_tokens in selections_by_part.items():
            if part_id not in valid_parts:
                continue
            tokens = [str(token).strip() for token in (raw_tokens or []) if str(token).strip()]
            if not tokens:
                continue  # Preserve legacy model-number applicability until the user tags it.
            if "All models" in tokens:
                conn.execute("DELETE FROM part_feature_rules WHERE project_id=? AND part_id=?", (project_id, part_id))
                conn.execute(
                    "UPDATE parts SET model_applicability='All', updated_at=? WHERE id=? AND project_id=?",
                    (timestamp, part_id, project_id),
                )
                updated += 1
                continue
            selected_by_feature: dict[str, set[str]] = {}
            for token in tokens:
                if "::" not in token:
                    raise ValueError("Choose All models or values defined in Feature definitions.")
                feature_id, value = token.split("::", 1)
                feature = feature_by_id.get(feature_id)
                allowed = json.loads(feature["allowed_values"] or "[]") if feature is not None else []
                if value not in allowed:
                    raise ValueError("A selected feature choice is no longer defined.")
                selected_by_feature.setdefault(feature_id, set()).add(value)

            matches = tree.copy()
            for feature_id, selected_values in selected_by_feature.items():
                matches = matches[matches[feature_id].isin(selected_values)]
            if matches.empty:
                raise ValueError("A feature rule matches no official models. Update the Complexity tree or the part rule.")
            model_numbers = matches["official_model_number"].dropna().astype(str).tolist()
            conn.execute("DELETE FROM part_feature_rules WHERE project_id=? AND part_id=?", (project_id, part_id))
            conn.executemany(
                """INSERT INTO part_feature_rules
                   (project_id, part_id, feature_id, value, updated_at) VALUES (?, ?, ?, ?, ?)""",
                [
                    (project_id, part_id, feature_id, value, timestamp)
                    for feature_id, values in selected_by_feature.items() for value in sorted(values)
                ],
            )
            conn.execute(
                "UPDATE parts SET model_applicability=?, updated_at=? WHERE id=? AND project_id=?",
                (normalize_model_applicability(model_numbers), timestamp, part_id, project_id),
            )
            updated += 1
    return updated


def complexity_planning_snapshot(project_id: str) -> dict:
    with connection() as conn:
        return {
            "features": [dict(row) for row in conn.execute(
                "SELECT * FROM complexity_features WHERE project_id=?", (project_id,)
            ).fetchall()],
            "values": [dict(row) for row in conn.execute(
                "SELECT * FROM model_feature_values WHERE project_id=?", (project_id,)
            ).fetchall()],
            "part_rules": [dict(row) for row in conn.execute(
                "SELECT * FROM part_feature_rules WHERE project_id=?", (project_id,)
            ).fetchall()],
            "part_applicability": [dict(row) for row in conn.execute(
                "SELECT id, model_applicability, updated_at FROM parts WHERE project_id=?", (project_id,)
            ).fetchall()],
        }


def restore_complexity_planning_snapshot(project_id: str, snapshot: dict) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM part_feature_rules WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM model_feature_values WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM complexity_features WHERE project_id=?", (project_id,))
        _insert_snapshot_rows(conn, "complexity_features", snapshot.get("features", []))
        _insert_snapshot_rows(conn, "model_feature_values", snapshot.get("values", []))
        _insert_snapshot_rows(conn, "part_feature_rules", snapshot.get("part_rules", []))
        for row in snapshot.get("part_applicability", []):
            conn.execute(
                "UPDATE parts SET model_applicability=?, updated_at=? WHERE id=? AND project_id=?",
                (row.get("model_applicability"), row.get("updated_at"), row.get("id"), project_id),
            )


def update_complexity_features(project_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "category", "name", "allowed_choices", "description", "active"}
    if not required.issubset(edited.columns):
        raise ValueError("The feature definitions table is missing required columns.")

    def clean(value) -> str:
        return "" if value is None or pd.isna(value) else str(value).strip()

    records = []
    names: list[str] = []
    for index, row in edited.reset_index(drop=True).iterrows():
        name = clean(row.get("name"))
        category = clean(row.get("category"))
        if not name and not category and not clean(row.get("allowed_choices")):
            continue
        if not category or not name:
            raise ValueError("Every feature needs both a category and a feature name.")
        choices = list(dict.fromkeys(
            choice.strip() for choice in clean(row.get("allowed_choices")).split(",") if choice.strip()
        ))
        if not choices:
            raise ValueError(f"Add at least one allowed choice for {name}.")
        names.append(name)
        records.append({
            "id": clean(row.get("id")) or str(uuid4()), "category": category, "name": name,
            "allowed_values": json.dumps(choices), "description": clean(row.get("description")),
            "active": 1 if bool(row.get("active")) else 0, "sequence": (index + 1) * 10,
        })
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("Feature names must be unique within this project.")

    timestamp = now_iso()
    with connection() as conn:
        existing_ids = {row[0] for row in conn.execute(
            "SELECT id FROM complexity_features WHERE project_id=?", (project_id,)
        )}
        retained_ids = {record["id"] for record in records}
        for feature_id in existing_ids - retained_ids:
            affected_part_ids = [row[0] for row in conn.execute(
                "SELECT DISTINCT part_id FROM part_feature_rules WHERE project_id=? AND feature_id=?",
                (project_id, feature_id),
            ).fetchall()]
            conn.execute("DELETE FROM complexity_features WHERE id=? AND project_id=?", (feature_id, project_id))
            for part_id in affected_part_ids:
                conn.execute(
                    "UPDATE parts SET model_applicability='', updated_at=? WHERE id=? AND project_id=?",
                    (timestamp, part_id, project_id),
                )
        for record in records:
            conn.execute(
                """INSERT INTO complexity_features
                   (id, project_id, category, name, allowed_values, description, sequence, active, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET category=excluded.category, name=excluded.name,
                   allowed_values=excluded.allowed_values, description=excluded.description,
                   sequence=excluded.sequence, active=excluded.active, updated_at=excluded.updated_at""",
                (record["id"], project_id, record["category"], record["name"], record["allowed_values"],
                 record["description"], record["sequence"], record["active"], timestamp),
            )
            choices = json.loads(record["allowed_values"])
            placeholders = ", ".join("?" for _ in choices)
            conn.execute(
                f"""DELETE FROM model_feature_values WHERE project_id=? AND feature_id=?
                    AND value NOT IN ({placeholders})""",
                (project_id, record["id"], *choices),
            )
            affected_part_ids = [row[0] for row in conn.execute(
                f"""SELECT DISTINCT part_id FROM part_feature_rules
                    WHERE project_id=? AND feature_id=? AND value NOT IN ({placeholders})""",
                (project_id, record["id"], *choices),
            ).fetchall()]
            conn.execute(
                f"""DELETE FROM part_feature_rules WHERE project_id=? AND feature_id=?
                    AND value NOT IN ({placeholders})""",
                (project_id, record["id"], *choices),
            )
            # Affected parts require an explicit review because their prior rule is no longer complete.
            for part_id in affected_part_ids:
                conn.execute(
                    "UPDATE parts SET model_applicability='', updated_at=? WHERE id=? AND project_id=?",
                    (timestamp, part_id, project_id),
                )
    return len(records)


def update_complexity_tree(project_id: str, edited: pd.DataFrame) -> int:
    if "model_id" not in edited.columns:
        raise ValueError("The complexity tree is missing model identifiers.")
    features = complexity_features(project_id)
    active_features = features.loc[features["active"].fillna(1).astype(bool)] if not features.empty else features
    allowed_by_id = {
        str(row["id"]): json.loads(row["allowed_values"] or "[]")
        for _, row in active_features.iterrows()
    }
    valid_models = set(project_models(project_id)["id"].astype(str))
    timestamp = now_iso()
    saved = 0
    with connection() as conn:
        for _, row in edited.iterrows():
            model_id = str(row["model_id"])
            if model_id not in valid_models:
                continue
            for feature_id, choices in allowed_by_id.items():
                value = "" if pd.isna(row.get(feature_id)) else str(row.get(feature_id) or "").strip()
                if value and value not in choices:
                    raise ValueError("Choose only values defined in Feature definitions.")
                if value:
                    conn.execute(
                        """INSERT INTO model_feature_values (project_id, model_id, feature_id, value, updated_at)
                           VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT(model_id, feature_id) DO UPDATE SET value=excluded.value,
                           updated_at=excluded.updated_at""",
                        (project_id, model_id, feature_id, value, timestamp),
                    )
                    saved += 1
                else:
                    conn.execute(
                        "DELETE FROM model_feature_values WHERE project_id=? AND model_id=? AND feature_id=?",
                        (project_id, model_id, feature_id),
                    )
        # Re-resolve every feature-tagged part when the model matrix changes.
        model_rows = conn.execute(
            "SELECT id, model_number FROM project_models WHERE project_id=?", (project_id,)
        ).fetchall()
        value_rows = conn.execute(
            "SELECT model_id, feature_id, value FROM model_feature_values WHERE project_id=?", (project_id,)
        ).fetchall()
        values_by_model = {
            str(model["id"]): {
                str(value["feature_id"]): str(value["value"])
                for value in value_rows if str(value["model_id"]) == str(model["id"])
            }
            for model in model_rows
        }
        rule_rows = conn.execute(
            "SELECT part_id, feature_id, value FROM part_feature_rules WHERE project_id=?",
            (project_id,),
        ).fetchall()
        rules_by_part: dict[str, dict[str, set[str]]] = {}
        for rule in rule_rows:
            rules_by_part.setdefault(str(rule["part_id"]), {}).setdefault(
                str(rule["feature_id"]), set()
            ).add(str(rule["value"]))
        for part_id, part_rules in rules_by_part.items():
            matching_numbers = [
                str(model["model_number"])
                for model in model_rows
                if all(values_by_model[str(model["id"])].get(feature_id) in choices
                       for feature_id, choices in part_rules.items())
            ]
            conn.execute(
                "UPDATE parts SET model_applicability=?, updated_at=? WHERE id=? AND project_id=?",
                (normalize_model_applicability(matching_numbers) if matching_numbers else "", timestamp, part_id, project_id),
            )
    return saved


def model_planning_snapshot(project_id: str) -> dict:
    """Capture model definitions and every project field affected by model renames."""
    with connection() as conn:
        return {
            "models": [dict(row) for row in conn.execute(
                "SELECT * FROM project_models WHERE project_id=?", (project_id,)
            ).fetchall()],
            "parts": [dict(row) for row in conn.execute(
                "SELECT id, model_applicability, updated_at FROM parts WHERE project_id=?", (project_id,)
            ).fetchall()],
            "work_elements": [dict(row) for row in conn.execute(
                "SELECT id, model_applicability, updated_at FROM work_elements WHERE project_id=?", (project_id,)
            ).fetchall()],
            "fishbone_nodes": [dict(row) for row in conn.execute(
                "SELECT id, applicable_models, updated_at FROM fishbone_nodes WHERE project_id=?", (project_id,)
            ).fetchall()],
        }


def _insert_snapshot_rows(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        [tuple(row.get(column) for column in columns) for row in rows],
    )


def restore_model_planning_snapshot(project_id: str, snapshot: dict) -> None:
    """Restore the last model edit along with propagated model applicability values."""
    with connection() as conn:
        conn.execute("DELETE FROM project_models WHERE project_id=?", (project_id,))
        _insert_snapshot_rows(conn, "project_models", snapshot.get("models", []))
        for table, value_column in (
            ("parts", "model_applicability"),
            ("work_elements", "model_applicability"),
            ("fishbone_nodes", "applicable_models"),
        ):
            for row in snapshot.get(table, []):
                conn.execute(
                    f"UPDATE {table} SET {value_column}=?, updated_at=? WHERE id=? AND project_id=?",
                    (row.get(value_column), row.get("updated_at"), row.get("id"), project_id),
                )


def fishbone_plan_snapshot(project_id: str) -> dict:
    """Capture the framework and its part uses as one referentially consistent unit."""
    with connection() as conn:
        return {
            "sections": [dict(row) for row in conn.execute(
                "SELECT * FROM assembly_sections WHERE project_id=?", (project_id,)
            ).fetchall()],
            "assignments": [dict(row) for row in conn.execute(
                "SELECT * FROM fishbone_part_assignments WHERE project_id=?", (project_id,)
            ).fetchall()],
        }


def fishbone_assignment_snapshot(project_id: str) -> list[dict]:
    """Capture assigned part uses without changing the assembly framework."""
    with connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM fishbone_part_assignments WHERE project_id=?", (project_id,)
        ).fetchall()]


def restore_fishbone_plan_snapshot(project_id: str, snapshot: dict) -> None:
    """Restore framework rows and assignments, including parent relationships."""
    sections = snapshot.get("sections", [])
    assignments = snapshot.get("assignments", [])
    with connection() as conn:
        conn.execute("DELETE FROM fishbone_part_assignments WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM assembly_sections WHERE project_id=?", (project_id,))
        # Insert parents and children with empty parent IDs first, then reconnect them.
        section_rows = [{**row, "parent_id": None} for row in sections]
        _insert_snapshot_rows(conn, "assembly_sections", section_rows)
        for row in sections:
            if row.get("parent_id"):
                conn.execute(
                    "UPDATE assembly_sections SET parent_id=? WHERE id=? AND project_id=?",
                    (row["parent_id"], row["id"], project_id),
                )
        _insert_snapshot_rows(conn, "fishbone_part_assignments", assignments)


def restore_fishbone_assignment_snapshot(project_id: str, snapshot: list[dict]) -> None:
    """Restore the last set of fishbone part uses."""
    with connection() as conn:
        conn.execute("DELETE FROM fishbone_part_assignments WHERE project_id=?", (project_id,))
        _insert_snapshot_rows(conn, "fishbone_part_assignments", snapshot)


def delete_project_model(project_id: str, model_id: str) -> str:
    """Delete an unreferenced model definition and return its common display label."""
    with connection() as conn:
        model = conn.execute(
            "SELECT model_number, display_name FROM project_models WHERE id=? AND project_id=?",
            (model_id, project_id),
        ).fetchone()
        if not model:
            raise ValueError("That model no longer exists.")
        model_number = str(model["model_number"])
        reference_count = 0
        for table in ("parts", "work_elements"):
            reference_count += conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE project_id=? AND instr(model_applicability, ?) > 0",
                (project_id, model_number),
            ).fetchone()[0]
        for row in conn.execute(
            "SELECT applicable_models FROM fishbone_nodes WHERE project_id=?",
            (project_id,),
        ).fetchall():
            try:
                assigned = json.loads(row["applicable_models"] or "[]")
            except (TypeError, json.JSONDecodeError):
                assigned = []
            reference_count += sum(str(value) == model_number for value in assigned)
        if reference_count:
            raise ValueError(
                "This model is still assigned elsewhere. Remove those assignments first, "
                "or turn off Use in planning instead of deleting it."
            )
        conn.execute("DELETE FROM project_models WHERE id=? AND project_id=?", (model_id, project_id))
        return str(model["display_name"] or model_number)


def add_project_model(project_id: str, model_number: str, display_name: str, description: str) -> str:
    model_number = model_number.strip()
    if not model_number:
        raise ValueError("Model number is required.")
    existing = query(
        "SELECT id FROM project_models WHERE project_id = ? AND model_number = ?",
        (project_id, model_number),
    )
    timestamp = now_iso()
    if existing:
        execute(
            "UPDATE project_models SET display_name=?, description=?, active=1, updated_at=? WHERE id=?",
            (display_name.strip(), description.strip(), timestamp, existing[0]["id"]),
        )
        return existing[0]["id"]
    model_id = str(uuid4())
    execute(
        """INSERT INTO project_models
           (id, project_id, model_number, source_payload, updated_at, display_name, description, active)
           VALUES (?, ?, ?, '{}', ?, ?, ?, 1)""",
        (model_id, project_id, model_number, timestamp, display_name.strip(), description.strip()),
    )
    return model_id


def update_project_model_rows(project_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "model_number", "display_name", "eau", "description", "active", "notes"}
    if not required.issubset(edited.columns):
        raise ValueError("The editable model table is missing required columns.")

    def clean_text(value) -> str:
        return "" if value is None or pd.isna(value) else str(value).strip()

    def clean_eau(value) -> int | None:
        if value is None or pd.isna(value) or str(value).strip() == "":
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("EAU must be a non-negative whole number.") from exc
        if numeric < 0 or not numeric.is_integer():
            raise ValueError("EAU must be a non-negative whole number.")
        return int(numeric)

    model_numbers = edited["model_number"].apply(clean_text)
    if model_numbers.eq("").any():
        raise ValueError("Every model needs an official model number.")
    if model_numbers.str.casefold().duplicated().any():
        raise ValueError("Official model numbers must be unique.")

    timestamp = now_iso()
    with connection() as conn:
        existing_rows = conn.execute(
            "SELECT id, model_number FROM project_models WHERE project_id=?",
            (project_id,),
        ).fetchall()
        existing_by_id = {str(row["id"]): str(row["model_number"]) for row in existing_rows}
        proposed_by_id = {
            str(row["id"]): clean_text(row.get("model_number"))
            for _, row in edited.iterrows()
            if row.get("id") is not None and not pd.isna(row.get("id")) and str(row.get("id")).strip()
        }
        final_numbers = [proposed_by_id.get(model_id, number) for model_id, number in existing_by_id.items()]
        if len({number.casefold() for number in final_numbers}) != len(final_numbers):
            raise ValueError("Official model numbers must be unique.")
        renamed = {
            existing_by_id[model_id]: new_number
            for model_id, new_number in proposed_by_id.items()
            if model_id in existing_by_id and existing_by_id[model_id] != new_number
        }
        try:
            # Temporary values allow two official model numbers to be swapped safely.
            for model_id in proposed_by_id:
                if model_id in existing_by_id and existing_by_id[model_id] != proposed_by_id[model_id]:
                    conn.execute(
                        "UPDATE project_models SET model_number=? WHERE id=? AND project_id=?",
                        (f"__renaming__{uuid4()}", model_id, project_id),
                    )
            for _, row in edited.iterrows():
                model_id = (
                    str(row["id"])
                    if row.get("id") is not None and not pd.isna(row.get("id")) and str(row.get("id")).strip()
                    else str(uuid4())
                )
                values = (
                    clean_text(row.get("model_number")),
                    clean_text(row.get("display_name")),
                    clean_eau(row.get("eau")),
                    clean_text(row.get("description")),
                    1 if bool(row.get("active")) else 0,
                    clean_text(row.get("notes")),
                    timestamp,
                )
                if model_id in existing_by_id:
                    conn.execute(
                        """UPDATE project_models
                           SET model_number=?, display_name=?, eau=?, description=?, active=?, notes=?, updated_at=?
                           WHERE id=? AND project_id=?""",
                        (*values, model_id, project_id),
                    )
                else:
                    conn.execute(
                        """INSERT INTO project_models
                           (id, project_id, model_number, source_payload, updated_at,
                            display_name, eau, description, active, notes)
                           VALUES (?, ?, ?, '{}', ?, ?, ?, ?, ?, ?)""",
                        (
                            model_id, project_id, values[0], values[6], values[1],
                            values[2], values[3], values[4], values[5],
                        ),
                    )
            if renamed:
                def rename_csv(value) -> str:
                    tokens = [token.strip() for token in str(value or "").split(",") if token.strip()]
                    return ", ".join(renamed.get(token, token) for token in tokens)

                for table in ("parts", "work_elements"):
                    reference_rows = conn.execute(
                        f"SELECT id, model_applicability FROM {table} WHERE project_id=?",
                        (project_id,),
                    ).fetchall()
                    for reference in reference_rows:
                        updated = rename_csv(reference["model_applicability"])
                        if updated != str(reference["model_applicability"] or ""):
                            conn.execute(
                                f"UPDATE {table} SET model_applicability=?, updated_at=? WHERE id=?",
                                (updated, timestamp, reference["id"]),
                            )
                node_rows = conn.execute(
                    "SELECT id, applicable_models FROM fishbone_nodes WHERE project_id=?",
                    (project_id,),
                ).fetchall()
                for node in node_rows:
                    try:
                        assigned = json.loads(node["applicable_models"] or "[]")
                    except (TypeError, json.JSONDecodeError):
                        assigned = []
                    updated = [renamed.get(str(model), str(model)) for model in assigned]
                    if updated != assigned:
                        conn.execute(
                            "UPDATE fishbone_nodes SET applicable_models=?, updated_at=? WHERE id=?",
                            (json.dumps(updated), timestamp, node["id"]),
                        )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Official model numbers must be unique.") from exc
    return len(edited)


def pits_records(project_id: str) -> pd.DataFrame:
    return pd.DataFrame(query("SELECT * FROM pits_records WHERE project_id = ? ORDER BY CAST(pits_id AS INTEGER), pits_id", (project_id,)))


def pits_revisions(project_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT p.pits_id, r.revision_no, r.imported_at, r.source_payload
           FROM pits_record_revisions r JOIN pits_records p ON p.id = r.record_id
           WHERE p.project_id = ? ORDER BY CAST(p.pits_id AS INTEGER), p.pits_id, r.revision_no""",
        (project_id,),
    ))


def import_pits_id_snapshot(project_id: str, records: list[dict], models: list[dict]) -> dict[str, int]:
    timestamp = now_iso()
    summary = {"new": 0, "changed": 0, "unchanged": 0, "models": 0}
    with connection() as conn:
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM fishbone_nodes WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
        for record in records:
            pits_id = str(record["pits_id"]).strip()
            payload = json.dumps(record["source_payload"], sort_keys=True, ensure_ascii=False, default=str)
            source_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            existing = conn.execute(
                "SELECT * FROM pits_records WHERE project_id = ? AND pits_id = ?", (project_id, pits_id)
            ).fetchone()
            if existing is None:
                record_id = str(uuid4())
                revision = 1
                conn.execute(
                    """INSERT INTO pits_records
                    (id, project_id, pits_id, part_number, description, used_bom, status, subsystem,
                     design_maturity, comments, workstation, source_payload, source_hash, revision_no,
                     first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (record_id, project_id, pits_id, record["part_number"], record["description"], record["used_bom"],
                     record["status"], record["subsystem"], record["design_maturity"], record["comments"],
                     record["workstation"], payload, source_hash, revision, timestamp, timestamp),
                )
                conn.execute(
                    "INSERT INTO pits_record_revisions VALUES (?, ?, ?, ?, ?)",
                    (str(uuid4()), record_id, revision, payload, timestamp),
                )
                next_sequence += 1
                conn.execute(
                    """INSERT INTO fishbone_nodes
                    (id, project_id, source_row, sequence, parent_id, depth, part_number, description, quantity,
                     branch_name, subsystem, model_feature, comments, tracker_status, planned_area, source,
                     raw_levels, review_status, updated_at, pits_id, applicable_models, source_changed)
                    VALUES (?, ?, ?, ?, NULL, 1, ?, ?, NULL, '', ?, '', ?, ?, ?, 'PITS tracker', ?, 'Needs review', ?, ?, '[]', 0)""",
                    (str(uuid4()), project_id, record["source_row"], next_sequence, record["part_number"],
                     record["description"], record["subsystem"], record["comments"], record["status"],
                     record["workstation"], payload, timestamp, pits_id),
                )
                summary["new"] += 1
            elif existing["source_hash"] != source_hash:
                revision = int(existing["revision_no"]) + 1
                conn.execute(
                    """UPDATE pits_records SET part_number=?, description=?, used_bom=?, status=?, subsystem=?,
                       design_maturity=?, comments=?, workstation=?, source_payload=?, source_hash=?, revision_no=?,
                       last_seen_at=? WHERE id=?""",
                    (record["part_number"], record["description"], record["used_bom"], record["status"],
                     record["subsystem"], record["design_maturity"], record["comments"], record["workstation"],
                     payload, source_hash, revision, timestamp, existing["id"]),
                )
                conn.execute(
                    "INSERT INTO pits_record_revisions VALUES (?, ?, ?, ?, ?)",
                    (str(uuid4()), existing["id"], revision, payload, timestamp),
                )
                conn.execute(
                    "UPDATE fishbone_nodes SET source_changed=1, updated_at=? WHERE project_id=? AND pits_id=?",
                    (timestamp, project_id, pits_id),
                )
                summary["changed"] += 1
            else:
                conn.execute("UPDATE pits_records SET last_seen_at=? WHERE id=?", (timestamp, existing["id"]))
                summary["unchanged"] += 1

        for model in models:
            payload = json.dumps(model["source_payload"], sort_keys=True, ensure_ascii=False, default=str)
            existing = conn.execute(
                "SELECT id FROM project_models WHERE project_id=? AND model_number=?",
                (project_id, model["model_number"]),
            ).fetchone()
            model_id = existing["id"] if existing else str(uuid4())
            conn.execute(
                """INSERT INTO project_models
                (id, project_id, model_number, item, platform_size, package_type, appearance, base_model,
                 eau, dg_date, dc_date, pre_pilot_date, pilot_date, production_date, sku_upc,
                 evaluate_fishbone, yamazumi, bop_l1, source_payload, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, model_number) DO UPDATE SET item=excluded.item,
                 platform_size=excluded.platform_size, package_type=excluded.package_type,
                 appearance=excluded.appearance, base_model=excluded.base_model, eau=excluded.eau,
                 dg_date=excluded.dg_date, dc_date=excluded.dc_date, pre_pilot_date=excluded.pre_pilot_date,
                 pilot_date=excluded.pilot_date, production_date=excluded.production_date,
                 sku_upc=excluded.sku_upc, evaluate_fishbone=excluded.evaluate_fishbone,
                 yamazumi=excluded.yamazumi, bop_l1=excluded.bop_l1,
                 source_payload=excluded.source_payload, updated_at=excluded.updated_at""",
                (model_id, project_id, model["model_number"], model["item"], model["platform_size"],
                 model["package_type"], model["appearance"], model["base_model"], model["eau"],
                 model["dg_date"], model["dc_date"], model["pre_pilot_date"], model["pilot_date"],
                 model["production_date"], model["sku_upc"], model["evaluate_fishbone"],
                 model["yamazumi"], model["bop_l1"], payload, timestamp),
            )
            summary["models"] += 1
    return summary


def apply_pits_updates(project_id: str, pits_ids: list[str]) -> int:
    if not pits_ids:
        return 0
    placeholders = ",".join("?" for _ in pits_ids)
    timestamp = now_iso()
    with connection() as conn:
        cursor = conn.execute(
            f"""UPDATE fishbone_nodes
                SET part_number=(SELECT part_number FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    description=(SELECT description FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    subsystem=(SELECT subsystem FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    comments=(SELECT comments FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    planned_area=(SELECT workstation FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    raw_levels=(SELECT source_payload FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    source_changed=0, review_status='Needs review', updated_at=?
                WHERE project_id=? AND pits_id IN ({placeholders})""",
            (timestamp, project_id, *pits_ids),
        )
        return cursor.rowcount


def set_mbom_review_status(project_id: str, node_ids: list[str], status: str) -> int:
    allowed = {"Needs review", "Confirmed", "Excluded"}
    if status not in allowed:
        raise ValueError("Unsupported MBOM review status")
    if not node_ids:
        return 0
    placeholders = ",".join("?" for _ in node_ids)
    with connection() as conn:
        cursor = conn.execute(
            f"UPDATE fishbone_nodes SET review_status=?, updated_at=? WHERE project_id=? AND id IN ({placeholders})",
            (status, now_iso(), project_id, *node_ids),
        )
        return cursor.rowcount


def sync_confirmed_mbom_parts(project_id: str) -> int:
    confirmed = query(
        """SELECT part_number, MAX(description) AS description, MAX(quantity) AS quantity,
                  MAX(applicable_models) AS applicable_models, MAX(comments) AS comments
           FROM fishbone_nodes
           WHERE project_id = ? AND review_status = 'Confirmed' AND TRIM(part_number) <> ''
           GROUP BY part_number""",
        (project_id,),
    )
    for row in confirmed:
        try:
            assigned_models = json.loads(row["applicable_models"] or "[]")
        except (TypeError, json.JSONDecodeError):
            assigned_models = []
        upsert_part(
            project_id,
            {
                "part_number": row["part_number"],
                "description": row["description"] or "",
                "quantity": row["quantity"],
                "source": "Confirmed MBOM",
                "model_applicability": ", ".join(assigned_models) if assigned_models else "All",
                "notes": row["comments"] or "",
            },
        )
    return len(confirmed)


def replace_work_elements(project_id: str, scenario_id: str, edited: pd.DataFrame) -> None:
    fields = ["sequence", "station", "operation", "description", "cycle_time_s", "part_number", "tool", "torque",
              "quality_requirement", "ergo_requirement", "location", "conveyor_height_mm", "platform_height_mm",
              "pit_depth_mm", "model_applicability", "status", "output_assembly_number",
              "output_assembly_name"]
    records: list[tuple[str, list]] = []
    assembly_numbers: set[str] = set()
    for _, row in edited.iterrows():
        if not str(row.get("operation", "")).strip():
            continue
        element_id = (
            str(row.get("id"))
            if row.get("id") is not None and not pd.isna(row.get("id")) and str(row.get("id")).strip()
            else str(uuid4())
        )
        values = []
        for field in fields:
            value = row.get(field, "")
            if value is None or pd.isna(value):
                value = None if field.endswith("_mm") else (0 if field in {"sequence", "cycle_time_s"} else "")
            values.append(value)
        output_number = str(values[fields.index("output_assembly_number")] or "").strip()
        if output_number:
            normalized = output_number.casefold()
            if normalized in assembly_numbers:
                raise ValueError("Each made-assembly output number can be completed only once in a scenario.")
            assembly_numbers.add(normalized)
        records.append((element_id, values))

    with connection() as conn:
        existing_ids = {
            str(row[0]) for row in conn.execute(
                "SELECT id FROM work_elements WHERE project_id=? AND scenario_id=?",
                (project_id, scenario_id),
            ).fetchall()
        }
        saved_ids = {element_id for element_id, _ in records}
        assignments = ", ".join(f"{field}=excluded.{field}" for field in fields)
        for element_id, values in records:
            conn.execute(
                f"""INSERT INTO work_elements
                    (id, project_id, scenario_id, {', '.join(fields)}, updated_at)
                    VALUES ({', '.join(['?'] * (len(fields) + 4))})
                    ON CONFLICT(id) DO UPDATE SET {assignments}, updated_at=excluded.updated_at""",
                (element_id, project_id, scenario_id, *values, now_iso()),
            )
        removed = existing_ids - saved_ids
        if removed:
            placeholders = ",".join("?" for _ in removed)
            conn.execute(
                f"""UPDATE yamazumi_elements
                    SET process_element_id=NULL, process_sync_status='Needs IE review', updated_at=?
                    WHERE project_id=? AND process_element_id IN ({placeholders})""",
                (now_iso(), project_id, *removed),
            )
            conn.execute(
                f"""DELETE FROM work_elements WHERE project_id=? AND scenario_id=?
                    AND id IN ({placeholders})""",
                (project_id, scenario_id, *removed),
            )


def replace_concerns(project_id: str, edited: pd.DataFrame) -> None:
    fields = ["category", "subject", "detail", "owner", "priority", "status", "related_part", "related_station"]
    with connection() as conn:
        conn.execute("DELETE FROM concerns WHERE project_id = ?", (project_id,))
        for _, row in edited.iterrows():
            if not str(row.get("subject", "")).strip():
                continue
            timestamp = now_iso()
            values = ["" if pd.isna(row.get(field, "")) else row.get(field, "") for field in fields]
            conn.execute(
                f"INSERT INTO concerns (id, project_id, {', '.join(fields)}, created_at, updated_at) VALUES ({', '.join(['?'] * (len(fields) + 4))})",
                (str(row.get("id")) if row.get("id") and not pd.isna(row.get("id")) else str(uuid4()), project_id, *values,
                 str(row.get("created_at")) if row.get("created_at") and not pd.isna(row.get("created_at")) else timestamp, timestamp),
            )
