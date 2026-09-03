from __future__ import annotations

import sqlite3
import json
import hashlib
import math
from contextlib import closing, contextmanager, nullcontext
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


def parse_yamazumi_model_variants(value, fallback: str | None = "Base") -> list[str]:
    """Return a clean model-variant list from stored JSON, a list, or legacy text."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                raw_values = json.loads(text)
            except json.JSONDecodeError:
                raw_values = [text]
        else:
            raw_values = [text] if text else []
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    elif value is None or pd.isna(value):
        raw_values = []
    else:
        raw_values = [value]
    variants = list(
        dict.fromkeys(str(item).strip() for item in raw_values if str(item).strip())
    )
    if not variants and fallback:
        return [fallback]
    return variants


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
                revision TEXT DEFAULT '0', source TEXT DEFAULT 'Manual', image_path TEXT DEFAULT '',
                model_applicability TEXT DEFAULT 'All', notes TEXT DEFAULT '', updated_at TEXT NOT NULL,
                UNIQUE(project_id, part_number)
            );
            CREATE TABLE IF NOT EXISTS part_scenario_activity (
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
                part_id TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                active INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(scenario_id, part_id)
            );
            CREATE TABLE IF NOT EXISTS work_elements (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                scenario_id TEXT REFERENCES planning_scenarios(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL, station TEXT DEFAULT '', operation TEXT NOT NULL,
                description TEXT DEFAULT '', cycle_time_s REAL DEFAULT 0,
                part_number TEXT DEFAULT '', tool TEXT DEFAULT '', torque TEXT DEFAULT '',
                quality_requirement TEXT DEFAULT '', ergo_requirement TEXT DEFAULT '',
                location TEXT DEFAULT '', unit_orientation TEXT DEFAULT '',
                conveyor_height_in REAL, platform_height_in REAL,
                pit_depth_in REAL, model_applicability TEXT DEFAULT 'All', status TEXT DEFAULT 'Draft',
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
                quantity REAL NOT NULL DEFAULT 1 CHECK(quantity > 0), use_description TEXT DEFAULT '',
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
                model_variant TEXT NOT NULL DEFAULT 'Base',
                model_variants TEXT NOT NULL DEFAULT '["Base"]', work_type TEXT DEFAULT 'Cycle',
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
                make_buy TEXT NOT NULL DEFAULT ''
                    CHECK (make_buy IN ('', 'Make', 'Buy')),
                pits_reference TEXT DEFAULT '', planning_reason TEXT NOT NULL DEFAULT 'Other',
                parent_id TEXT REFERENCES manufacturing_assemblies(id) ON DELETE SET NULL,
                built_section_id TEXT REFERENCES assembly_sections(id) ON DELETE RESTRICT,
                installed_section_id TEXT REFERENCES assembly_sections(id) ON DELETE RESTRICT,
                image_path TEXT DEFAULT '', created_at TEXT,
                active INTEGER NOT NULL DEFAULT 1, notes TEXT DEFAULT '', updated_at TEXT NOT NULL,
                UNIQUE(project_id, assembly_number)
            );
            CREATE TABLE IF NOT EXISTS manufacturing_assembly_components (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                assembly_id TEXT NOT NULL REFERENCES manufacturing_assemblies(id) ON DELETE CASCADE,
                fishbone_assignment_id TEXT NOT NULL REFERENCES fishbone_part_assignments(id) ON DELETE CASCADE,
                quantity REAL NOT NULL CHECK(quantity > 0),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(assembly_id, fishbone_assignment_id)
            );
            CREATE TABLE IF NOT EXISTS manufacturing_assembly_feature_rules (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                assembly_id TEXT NOT NULL REFERENCES manufacturing_assemblies(id) ON DELETE CASCADE,
                feature_id TEXT NOT NULL REFERENCES complexity_features(id) ON DELETE RESTRICT,
                value TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(assembly_id, feature_id)
            );
            CREATE TABLE IF NOT EXISTS manufacturing_assembly_images (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                assembly_id TEXT NOT NULL REFERENCES manufacturing_assemblies(id) ON DELETE CASCADE,
                image_path TEXT NOT NULL, caption TEXT DEFAULT '', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assembly_grid_categories (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                section_id TEXT NOT NULL REFERENCES assembly_sections(id) ON DELETE RESTRICT,
                ebom_name TEXT NOT NULL COLLATE NOCASE,
                display_name TEXT NOT NULL COLLATE NOCASE,
                root_number TEXT NOT NULL,
                installed_section_id TEXT REFERENCES assembly_sections(id) ON DELETE RESTRICT,
                sequence INTEGER NOT NULL DEFAULT 10,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(project_id, section_id, ebom_name),
                UNIQUE(project_id, section_id, display_name)
            );
            CREATE TABLE IF NOT EXISTS assembly_grid_model_mappings (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                category_id TEXT NOT NULL REFERENCES assembly_grid_categories(id) ON DELETE CASCADE,
                model_id TEXT NOT NULL REFERENCES project_models(id) ON DELETE CASCADE,
                assembly_id TEXT NOT NULL REFERENCES manufacturing_assemblies(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(category_id, model_id)
            );
            CREATE TABLE IF NOT EXISTS assembly_grid_feature_visibility (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                section_id TEXT NOT NULL REFERENCES assembly_sections(id) ON DELETE CASCADE,
                feature_id TEXT NOT NULL REFERENCES complexity_features(id) ON DELETE CASCADE,
                is_visible INTEGER NOT NULL DEFAULT 1 CHECK(is_visible IN (0, 1)),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(section_id, feature_id)
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
        manufacturing_assembly_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(manufacturing_assemblies)").fetchall()
        }
        for column, definition in {
            "make_buy": (
                "TEXT NOT NULL DEFAULT '' CHECK (make_buy IN ('', 'Make', 'Buy'))"
            ),
            "built_section_id": (
                "TEXT REFERENCES assembly_sections(id) ON DELETE RESTRICT"
            ),
            "installed_section_id": (
                "TEXT REFERENCES assembly_sections(id) ON DELETE RESTRICT"
            ),
            "image_path": "TEXT DEFAULT ''",
            "created_at": "TEXT",
        }.items():
            if column not in manufacturing_assembly_columns:
                conn.execute(
                    f"ALTER TABLE manufacturing_assemblies ADD COLUMN {column} {definition}"
                )
        conn.execute(
            """UPDATE manufacturing_assemblies SET created_at=updated_at
               WHERE created_at IS NULL OR TRIM(created_at)=''"""
        )
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
                    quantity REAL NOT NULL DEFAULT 1 CHECK(quantity > 0),
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
        assignment_quantity_type = next(
            (
                str(row[2]).upper()
                for row in conn.execute("PRAGMA table_info(fishbone_part_assignments)").fetchall()
                if row[1] == "quantity"
            ),
            "",
        )
        if assignment_quantity_type != "REAL":
            invalid_quantity_count = conn.execute(
                """SELECT COUNT(*) FROM fishbone_part_assignments
                   WHERE quantity IS NULL OR typeof(quantity) NOT IN ('integer', 'real')
                      OR CAST(quantity AS REAL) <= 0"""
            ).fetchone()[0]
            if invalid_quantity_count:
                raise ValueError(
                    "Fishbone quantities must all be positive numbers before the decimal-quantity "
                    "schema upgrade can run."
                )
            conn.executescript(
                """
                CREATE TABLE fishbone_part_assignments_quantity_new (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    part_id TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                    section_id TEXT NOT NULL REFERENCES assembly_sections(id),
                    sequence INTEGER NOT NULL DEFAULT 10,
                    quantity REAL NOT NULL DEFAULT 1 CHECK(quantity > 0),
                    use_description TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                INSERT INTO fishbone_part_assignments_quantity_new
                    (id, project_id, part_id, section_id, sequence, quantity,
                     use_description, notes, updated_at)
                SELECT id, project_id, part_id, section_id, sequence, CAST(quantity AS REAL),
                       use_description, notes, updated_at
                FROM fishbone_part_assignments;
                DROP TABLE fishbone_part_assignments;
                ALTER TABLE fishbone_part_assignments_quantity_new
                    RENAME TO fishbone_part_assignments;
                """
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fishbone_assignment_part ON fishbone_part_assignments(project_id, part_id)"
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_assembly_catalog_sections
               ON manufacturing_assemblies(project_id, built_section_id, installed_section_id)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_assembly_component_assignment
               ON manufacturing_assembly_components(project_id, fishbone_assignment_id)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_assembly_rules_owner
               ON manufacturing_assembly_feature_rules(project_id, assembly_id)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_assembly_images_owner
               ON manufacturing_assembly_images(project_id, assembly_id)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_assembly_grid_categories_section
               ON assembly_grid_categories(project_id, section_id, sequence)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_assembly_grid_mapping_assembly
               ON assembly_grid_model_mappings(project_id, assembly_id, category_id)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_assembly_grid_mapping_model
               ON assembly_grid_model_mappings(project_id, model_id)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_assembly_grid_visibility_section
               ON assembly_grid_feature_visibility(project_id, section_id, feature_id)"""
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
        element_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(yamazumi_elements)").fetchall()
        }
        if "model_variants" not in element_columns:
            conn.execute(
                "ALTER TABLE yamazumi_elements ADD COLUMN model_variants TEXT NOT NULL DEFAULT '[\"Base\"]'"
            )
            for element in conn.execute(
                "SELECT id, model_variant FROM yamazumi_elements"
            ).fetchall():
                variants = parse_yamazumi_model_variants(element["model_variant"])
                conn.execute(
                    "UPDATE yamazumi_elements SET model_variants=? WHERE id=?",
                    (json.dumps(variants), element["id"]),
                )
        work_region_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(yamazumi_work_regions)").fetchall()
        }
        for column, definition in {
            "description": "TEXT DEFAULT ''",
            "active": "INTEGER NOT NULL DEFAULT 1",
        }.items():
            if column not in work_region_columns:
                conn.execute(f"ALTER TABLE yamazumi_work_regions ADD COLUMN {column} {definition}")
        work_dimension_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(work_elements)").fetchall()
        }
        for old_column, new_column in {
            "conveyor_height_mm": "conveyor_height_in",
            "platform_height_mm": "platform_height_in",
            "pit_depth_mm": "pit_depth_in",
        }.items():
            if old_column in work_dimension_columns and new_column not in work_dimension_columns:
                conn.execute(
                    f"ALTER TABLE work_elements RENAME COLUMN {old_column} TO {new_column}"
                )
                conn.execute(
                    f"UPDATE work_elements SET {new_column}={new_column} / 25.4 "
                    f"WHERE {new_column} IS NOT NULL"
                )
                work_dimension_columns.remove(old_column)
                work_dimension_columns.add(new_column)
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
                ("HW-M8-025", "M8 fastener", 4, "0"),
            ]
            for pn, desc, qty, rev in sample_parts:
                conn.execute(
                    "INSERT INTO parts VALUES (?, ?, ?, ?, ?, ?, 'Sample', '', 'All', '', ?)",
                    (str(uuid4()), project_id, pn, desc, qty, rev, timestamp),
                )
            sample_steps = [
                (10, "ST-010", "Load housing", "Place housing in locating fixture", 18.0, "PN-100100", "", "", "Confirm seated on all locators", "Two-hand lift review", "Main line / Zone 1", 37.4, 0, 0),
                (20, "ST-010", "Install bracket", "Locate bracket and hand-start four fasteners", 24.0, "PN-100220", "Nutrunner", "32 N·m ± 3", "Torque trace required", "Keep work below shoulder", "Main line / Zone 1", 37.4, 3.94, 0),
                (30, "ST-010", "Verify assembly", "Visual and torque-complete confirmation", 8.0, "HW-M8-025", "Scanner", "", "All four results pass", "", "Main line / Zone 1", 37.4, 3.94, 0),
            ]
            for row in sample_steps:
                conn.execute(
                    """INSERT INTO work_elements
                    (id, project_id, sequence, station, operation, description, cycle_time_s,
                     part_number, tool, torque, quality_requirement, ergo_requirement, location,
                     conveyor_height_in, platform_height_in, pit_depth_in, model_applicability, status, updated_at)
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
        if "unit_orientation" not in work_columns:
            conn.execute("ALTER TABLE work_elements ADD COLUMN unit_orientation TEXT DEFAULT ''")
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


def update_planning_scenario(
    project_id: str,
    scenario_id: str,
    values: dict,
    *,
    _conn: sqlite3.Connection | None = None,
) -> None:
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
        context = nullcontext(_conn) if _conn is not None else connection()
        with context as conn:
            cursor = conn.execute(
                """UPDATE planning_scenarios
                   SET name=?, revision_label=?, status=?, takt_time_s=?, change_summary=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (
                    name, revision_label, status, takt,
                    str(values.get("change_summary") or "").strip(), now_iso(),
                    scenario_id, project_id,
                ),
            )
            if not cursor.rowcount:
                raise ValueError("The planning scenario no longer exists.")
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
    *,
    _conn: sqlite3.Connection | None = None,
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
        context = nullcontext(_conn) if _conn is not None else connection()
        with context as conn:
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
                """INSERT INTO part_scenario_activity
                   (project_id, scenario_id, part_id, active, updated_at)
                   SELECT project_id, ?, part_id, active, ?
                   FROM part_scenario_activity
                   WHERE project_id=? AND scenario_id=?""",
                (new_scenario_id, timestamp, project_id, source_scenario_id),
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


def save_planning_scenario_rows(
    project_id: str,
    source_scenario_id: str,
    records: list[dict],
    created_by: str = "",
) -> dict[str, object]:
    """Save the Overview scenario table and branch new rows from one source.

    Every row is validated before the first write. Existing scenario IDs update
    metadata in place; rows without an ID use the complete scenario-cloning
    workflow so their scenario-owned planning data is preserved.
    """
    existing = planning_scenarios(project_id, include_archived=True)
    existing_ids = {str(row["id"]) for row in existing}
    if source_scenario_id not in existing_ids:
        raise ValueError("The source scenario no longer exists.")

    cleaned: list[dict] = []
    names: set[str] = set()
    revisions: set[str] = set()
    valid_statuses = {"Working", "Frozen", "Released", "Archived"}
    for record in records:
        scenario_id = str(record.get("id") or "").strip()
        if scenario_id and scenario_id not in existing_ids:
            raise ValueError("One of the planning scenarios no longer exists. Refresh and try again.")
        name = str(record.get("name") or "").strip()
        revision_label = str(record.get("revision_label") or "").strip()
        status = str(record.get("status") or "Working").strip().title()
        if not name or not revision_label:
            raise ValueError("Scenario name and revision label are required in every row.")
        if status not in valid_statuses:
            raise ValueError("Choose a valid scenario status in every row.")
        try:
            takt = float(record.get("takt_time_s"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Scenario takt time must be a number in every row.") from exc
        if takt <= 0:
            raise ValueError("Scenario takt time must be greater than zero in every row.")
        if name.casefold() in names:
            raise ValueError("Scenario names must be unique within this project.")
        if revision_label.casefold() in revisions:
            raise ValueError("Scenario revision labels must be unique within this project.")
        names.add(name.casefold())
        revisions.add(revision_label.casefold())
        cleaned.append(
            {
                "id": scenario_id,
                "name": name,
                "revision_label": revision_label,
                "status": status,
                "takt_time_s": takt,
                "change_summary": str(record.get("change_summary") or "").strip(),
            }
        )

    updated_count = 0
    created_ids: list[str] = []
    with connection() as conn:
        for record in cleaned:
            if record["id"]:
                update_planning_scenario(
                    project_id, str(record["id"]), record, _conn=conn
                )
                updated_count += 1
                continue
            new_id = clone_planning_scenario(
                project_id,
                source_scenario_id,
                str(record["name"]),
                str(record["revision_label"]),
                float(record["takt_time_s"]),
                str(record["change_summary"]),
                created_by,
                _conn=conn,
            )
            if record["status"] != "Working":
                update_planning_scenario(project_id, new_id, record, _conn=conn)
            created_ids.append(new_id)

    return {
        "updated_count": updated_count,
        "created_ids": created_ids,
        "saved_count": len(cleaned),
    }


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


def backup_database(target_path: str | Path) -> Path:
    """Create and validate a consistent SQLite backup without modifying the source DB."""
    source = DB_PATH.resolve()
    target = Path(target_path).resolve()
    data_root = DATA_DIR.resolve()
    if not source.exists() or not source.is_file():
        raise ValueError("The local PAAG database does not exist, so it cannot be backed up.")
    if target == source:
        raise ValueError("Choose a backup path different from the live PAAG database.")
    if data_root != target.parent and data_root not in target.parents:
        raise ValueError("Store the PAAG database backup beneath the data directory.")
    if target.exists():
        raise ValueError("The requested PAAG database backup already exists.")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(
            f"file:{source.as_posix()}?mode=ro", uri=True
        )) as source_conn:
            with closing(sqlite3.connect(target)) as target_conn:
                source_conn.backup(target_conn)
                result = target_conn.execute("PRAGMA quick_check").fetchone()
                if not result or str(result[0]).lower() != "ok":
                    raise ValueError("The PAAG database backup failed SQLite validation.")
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if not target.exists() or target.stat().st_size <= 0:
        target.unlink(missing_ok=True)
        raise ValueError("The PAAG database backup was not created successfully.")
    return target


def _catalog_records(rows) -> list[dict]:
    if isinstance(rows, pd.DataFrame):
        return rows.to_dict("records")
    return [dict(row) for row in rows]


def _catalog_text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _require_catalog_assembly(
    conn: sqlite3.Connection, project_id: str, assembly_id: str
) -> sqlite3.Row:
    assembly = conn.execute(
        "SELECT * FROM manufacturing_assemblies WHERE id=? AND project_id=?",
        (assembly_id, project_id),
    ).fetchone()
    if not assembly:
        raise ValueError("The selected assembly no longer exists in this project.")
    return assembly


def assembly_grid_categories(
    project_id: str, section_id: str | None = None
) -> pd.DataFrame:
    params: list[str] = [project_id]
    section_clause = ""
    if _catalog_text(section_id):
        section_clause = " AND category.section_id=?"
        params.append(_catalog_text(section_id))
    return pd.DataFrame(query(
        f"""SELECT category.*, built.name AS section_name,
                   installed.name AS installed_section_name,
                   COUNT(DISTINCT mapping.id) AS mapping_count,
                   COUNT(DISTINCT mapping.assembly_id) AS assembly_count
            FROM assembly_grid_categories category
            JOIN assembly_sections built ON built.id=category.section_id
            LEFT JOIN assembly_sections installed
              ON installed.id=category.installed_section_id
            LEFT JOIN assembly_grid_model_mappings mapping
              ON mapping.category_id=category.id
            WHERE category.project_id=?{section_clause}
            GROUP BY category.id
            ORDER BY built.sequence, category.sequence, category.display_name""",
        tuple(params),
    ))


def assembly_grid_model_mappings(
    project_id: str, section_id: str | None = None
) -> pd.DataFrame:
    params: list[str] = [project_id]
    section_clause = ""
    if _catalog_text(section_id):
        section_clause = " AND category.section_id=?"
        params.append(_catalog_text(section_id))
    return pd.DataFrame(query(
        f"""SELECT mapping.*, category.section_id, category.ebom_name,
                   category.display_name AS category_display_name,
                   category.root_number, category.installed_section_id,
                   model.model_number, model.display_name AS model_display_name,
                   model.active AS model_active,
                   assembly.assembly_number, assembly.name AS assembly_name,
                   assembly.built_section_id AS assembly_built_section_id,
                   assembly.installed_section_id AS assembly_installed_section_id
            FROM assembly_grid_model_mappings mapping
            JOIN assembly_grid_categories category ON category.id=mapping.category_id
            JOIN project_models model ON model.id=mapping.model_id
            JOIN manufacturing_assemblies assembly ON assembly.id=mapping.assembly_id
            WHERE mapping.project_id=?{section_clause}
            ORDER BY category.sequence, category.display_name, model.model_number""",
        tuple(params),
    ))


def assembly_grid_feature_visibility(
    project_id: str, section_id: str
) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT feature.id AS feature_id, feature.category, feature.name,
                  feature.sequence, feature.active,
                  COALESCE(preference.is_visible, 1) AS is_visible,
                  preference.id, preference.created_at, preference.updated_at
           FROM complexity_features feature
           LEFT JOIN assembly_grid_feature_visibility preference
             ON preference.feature_id=feature.id AND preference.section_id=?
           WHERE feature.project_id=?
           ORDER BY feature.sequence, feature.category, feature.name""",
        (section_id, project_id),
    ))


def save_assembly_grid_categories(
    project_id: str, section_id: str, rows, *, _conn: sqlite3.Connection | None = None
) -> dict:
    """Upsert category rows and continuously sync their mapped assemblies."""
    records = _catalog_records(rows)
    section_id = _catalog_text(section_id)
    timestamp = now_iso()
    with (connection() if _conn is None else nullcontext(_conn)) as conn:
        section = conn.execute(
            "SELECT id FROM assembly_sections WHERE id=? AND project_id=?",
            (section_id, project_id),
        ).fetchone()
        if not section:
            raise ValueError("Choose an existing Fishbone section from this project.")
        valid_installed = {
            str(row[0]) for row in conn.execute(
                "SELECT id FROM assembly_sections WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        current = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM assembly_grid_categories WHERE project_id=?",
                (project_id,),
            ).fetchall()
        }
        normalized: list[dict] = []
        seen_ids: set[str] = set()
        for raw in records:
            category_id = _catalog_text(raw.get("id")) or str(uuid4())
            ebom_name = _catalog_text(raw.get("ebom_name"))
            display_name = _catalog_text(raw.get("display_name"))
            installed_section_id = _catalog_text(raw.get("installed_section_id")) or None
            if category_id in seen_ids:
                raise ValueError("The assembly grid contains a duplicate category identifier.")
            if not ebom_name or not display_name:
                raise ValueError(
                    "Every assembly-grid category requires an Official EBOM category name "
                    "and Display name."
                )
            if installed_section_id and installed_section_id not in valid_installed:
                raise ValueError("Choose an existing Installed section from this project.")
            previous = current.get(category_id)
            root_number = (
                _catalog_text(raw.get("root_number"))
                if "root_number" in raw
                else _catalog_text((previous or {}).get("root_number"))
            )
            if previous and _catalog_text(previous.get("section_id")) != section_id:
                raise ValueError(
                    "A category can be moved to another Fishbone section only through the "
                    "approved section-continuity workflow."
                )
            try:
                sequence = int(raw.get("sequence", 10))
            except (TypeError, ValueError) as exc:
                raise ValueError("Assembly-grid category sequence values must be whole numbers.") from exc
            seen_ids.add(category_id)
            normalized.append(
                {
                    "id": category_id,
                    "ebom_name": ebom_name,
                    "display_name": display_name,
                    "root_number": root_number,
                    "installed_section_id": installed_section_id,
                    "sequence": sequence,
                }
            )

        merged = {category_id: dict(value) for category_id, value in current.items()}
        merged.update(
            {
                row["id"]: {
                    **row,
                    "project_id": project_id,
                    "section_id": section_id,
                }
                for row in normalized
            }
        )
        for field, label in (("ebom_name", "Official EBOM category name"), ("display_name", "Display name")):
            seen: dict[tuple[str, str], str] = {}
            for category_id, row in merged.items():
                key = (
                    _catalog_text(row.get("section_id")),
                    _catalog_text(row.get(field)).casefold(),
                )
                if key in seen and seen[key] != category_id:
                    raise ValueError(f"{label} values must be unique within a Fishbone section.")
                seen[key] = category_id

        sync_changes: list[dict] = []
        for row in normalized:
            previous = current.get(row["id"])
            created_at = _catalog_text(previous.get("created_at")) if previous else timestamp
            conn.execute(
                """INSERT INTO assembly_grid_categories
                   (id, project_id, section_id, ebom_name, display_name, root_number,
                    installed_section_id, sequence, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       ebom_name=excluded.ebom_name,
                       display_name=excluded.display_name,
                       root_number=excluded.root_number,
                       installed_section_id=excluded.installed_section_id,
                       sequence=excluded.sequence,
                       updated_at=excluded.updated_at""",
                (
                    row["id"], project_id, section_id, row["ebom_name"],
                    row["display_name"], row["root_number"],
                    row["installed_section_id"], row["sequence"], created_at, timestamp,
                ),
            )
            mapped = conn.execute(
                """SELECT DISTINCT assembly.id, assembly.assembly_number,
                          assembly.installed_section_id
                   FROM assembly_grid_model_mappings mapping
                   JOIN manufacturing_assemblies assembly ON assembly.id=mapping.assembly_id
                   WHERE mapping.project_id=? AND mapping.category_id=?""",
                (project_id, row["id"]),
            ).fetchall()
            for assembly in mapped:
                old_value = _catalog_text(assembly["installed_section_id"]) or None
                if old_value == row["installed_section_id"]:
                    continue
                conn.execute(
                    """UPDATE manufacturing_assemblies
                       SET installed_section_id=?, updated_at=?
                       WHERE id=? AND project_id=?""",
                    (row["installed_section_id"], timestamp, assembly["id"], project_id),
                )
                sync_changes.append(
                    {
                        "assembly_id": str(assembly["id"]),
                        "assembly_number": str(assembly["assembly_number"]),
                        "old_installed_section_id": old_value,
                        "new_installed_section_id": row["installed_section_id"],
                    }
                )
    return {
        "count": len(normalized),
        "category_ids": [row["id"] for row in normalized],
        "installed_section_sync_changes": sync_changes,
        "updated_at": timestamp,
    }


def save_assembly_grid_model_mappings(
    project_id: str, rows, *, _conn: sqlite3.Connection | None = None
) -> dict:
    """Replace the complete project mapping state after validating every relationship."""
    records = _catalog_records(rows)
    timestamp = now_iso()
    with (connection() if _conn is None else nullcontext(_conn)) as conn:
        categories = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM assembly_grid_categories WHERE project_id=?",
                (project_id,),
            ).fetchall()
        }
        models = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT id, model_number FROM project_models WHERE project_id=?",
                (project_id,),
            ).fetchall()
        }
        assemblies = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM manufacturing_assemblies WHERE project_id=?",
                (project_id,),
            ).fetchall()
        }
        assembly_by_number = {
            _catalog_text(row["assembly_number"]).casefold(): assembly_id
            for assembly_id, row in assemblies.items()
        }
        existing_mappings = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM assembly_grid_model_mappings WHERE project_id=?",
                (project_id,),
            ).fetchall()
        }
        original_numbers = {
            assembly_id: _catalog_text(row["assembly_number"])
            for assembly_id, row in assemblies.items()
        }
        rename_candidates: dict[str, dict[str, str]] = {}
        for raw in records:
            assembly_id = _catalog_text(raw.get("assembly_id"))
            requested_number = _catalog_text(raw.get("assembly_number"))
            current_number = original_numbers.get(assembly_id, "")
            if (
                assembly_id in assemblies
                and requested_number
                and requested_number != current_number
            ):
                rename_candidates.setdefault(assembly_id, {})[
                    requested_number.casefold()
                ] = requested_number

        planned_renames: dict[str, str] = {}
        for assembly_id, candidates in rename_candidates.items():
            changed_numbers = {
                key: value
                for key, value in candidates.items()
                if key != original_numbers[assembly_id].casefold()
            }
            if len(changed_numbers) > 1:
                raise ValueError(
                    f"Assembly {original_numbers[assembly_id]} has conflicting Part number "
                    "edits. Use one Part number for every model mapped to that assembly."
                )
            if changed_numbers:
                planned_renames[assembly_id] = next(iter(changed_numbers.values()))
            elif candidates:
                # Preserve deliberate capitalization-only corrections.
                planned_renames[assembly_id] = next(iter(candidates.values()))

        final_number_owners: dict[str, str] = {}
        renamed_assemblies: list[dict] = []
        for assembly_id, assembly in assemblies.items():
            old_number = original_numbers[assembly_id]
            final_number = planned_renames.get(assembly_id, old_number)
            owner = final_number_owners.get(final_number.casefold())
            if owner and owner != assembly_id:
                raise ValueError(
                    f"Part number {final_number} already belongs to another assembly. "
                    "Choose a unique Part number."
                )
            final_number_owners[final_number.casefold()] = assembly_id
            if final_number != old_number:
                assembly["assembly_number"] = final_number
                renamed_assemblies.append(
                    {
                        "assembly_id": assembly_id,
                        "old_assembly_number": old_number,
                        "assembly_number": final_number,
                    }
                )
        assembly_by_number = dict(final_number_owners)
        normalized: list[dict] = []
        seen_ids: set[str] = set()
        seen_cells: set[tuple[str, str]] = set()
        category_by_assembly: dict[str, str] = {}
        created_assemblies: list[dict] = []
        for raw in records:
            mapping_id = _catalog_text(raw.get("id")) or str(uuid4())
            category_id = _catalog_text(raw.get("category_id"))
            model_id = _catalog_text(raw.get("model_id"))
            category = categories.get(category_id)
            model = models.get(model_id)
            if not category:
                raise ValueError("Every mapping must use a current project assembly-grid category.")
            if not model:
                raise ValueError("Every mapping must use a current official model.")
            assembly_id = _catalog_text(raw.get("assembly_id"))
            assembly_number = _catalog_text(raw.get("assembly_number"))
            assembly = assemblies.get(assembly_id) if assembly_id else None
            if assembly is None:
                if not assembly_number:
                    raise ValueError("Every mapping requires an assembly number.")
                existing_id = assembly_by_number.get(assembly_number.casefold())
                if existing_id:
                    assembly_id = existing_id
                    assembly = assemblies[assembly_id]
                else:
                    assembly_id = str(uuid4())
                    assembly = {
                        "id": assembly_id,
                        "project_id": project_id,
                        "assembly_number": assembly_number,
                        "name": _catalog_text(category.get("display_name")),
                        "make_buy": "",
                        "built_section_id": category["section_id"],
                        "installed_section_id": category["installed_section_id"],
                    }
                    assemblies[assembly_id] = assembly
                    assembly_by_number[assembly_number.casefold()] = assembly_id
                    created_assemblies.append(assembly)
            if mapping_id in seen_ids:
                raise ValueError("The assembly grid contains a duplicate mapping identifier.")
            cell = (category_id, model_id)
            if cell in seen_cells:
                raise ValueError("Each category may map an official model only once.")
            if _catalog_text(assembly.get("built_section_id")) != _catalog_text(category.get("section_id")):
                raise ValueError(
                    f"Assembly {assembly['assembly_number']} is built in a different Fishbone "
                    "section and cannot be mapped here."
                )
            assembly_installed = _catalog_text(assembly.get("installed_section_id")) or None
            category_installed = _catalog_text(category.get("installed_section_id")) or None
            if assembly_installed != category_installed:
                raise ValueError(
                    f"Assembly {assembly['assembly_number']} has an Installed section that "
                    "does not match this category. Reconcile it before mapping."
                )
            prior_category = category_by_assembly.get(assembly_id)
            if prior_category and prior_category != category_id:
                prior = categories[prior_category]
                raise ValueError(
                    f"Assembly {assembly['assembly_number']} is already mapped under category "
                    f"{prior['display_name']} and cannot also be mapped under "
                    f"{category['display_name']} for model {model['model_number']}."
                )
            category_by_assembly[assembly_id] = category_id
            seen_ids.add(mapping_id)
            seen_cells.add(cell)
            normalized.append(
                {
                    "id": mapping_id,
                    "category_id": category_id,
                    "model_id": model_id,
                    "assembly_id": assembly_id,
                }
            )

        for assembly in created_assemblies:
            conn.execute(
                """INSERT INTO manufacturing_assemblies
                   (id, project_id, assembly_number, name, make_buy, pits_reference,
                    planning_reason, parent_id, built_section_id, installed_section_id,
                    image_path, created_at, active, notes, updated_at)
                   VALUES (?, ?, ?, ?, '', '', 'Other', NULL, ?, ?, '', ?, 1, '', ?)""",
                (
                    assembly["id"], project_id, assembly["assembly_number"], assembly["name"],
                    assembly["built_section_id"], assembly["installed_section_id"],
                    timestamp, timestamp,
                ),
            )
        for assembly in renamed_assemblies:
            conn.execute(
                """UPDATE manufacturing_assemblies
                   SET assembly_number=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (
                    assembly["assembly_number"], timestamp,
                    assembly["assembly_id"], project_id,
                ),
            )
        conn.execute(
            "DELETE FROM assembly_grid_model_mappings WHERE project_id=?", (project_id,)
        )
        conn.executemany(
            """INSERT INTO assembly_grid_model_mappings
               (id, project_id, category_id, model_id, assembly_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    row["id"], project_id, row["category_id"], row["model_id"],
                    row["assembly_id"],
                    _catalog_text(existing_mappings.get(row["id"], {}).get("created_at"))
                    or timestamp,
                    timestamp,
                )
                for row in normalized
            ],
        )
    return {
        "count": len(normalized),
        "mapping_ids": [row["id"] for row in normalized],
        "created_assemblies": [
            {"assembly_id": row["id"], "assembly_number": row["assembly_number"]}
            for row in created_assemblies
        ],
        "renamed_assemblies": renamed_assemblies,
        "updated_at": timestamp,
    }


def save_assembly_grid_feature_visibility(
    project_id: str, section_id: str, rows, *, _conn: sqlite3.Connection | None = None
) -> dict:
    """Persist only non-default hidden-feature preferences for one section."""
    records = _catalog_records(rows)
    timestamp = now_iso()
    with (connection() if _conn is None else nullcontext(_conn)) as conn:
        if not conn.execute(
            "SELECT 1 FROM assembly_sections WHERE id=? AND project_id=?",
            (section_id, project_id),
        ).fetchone():
            raise ValueError("Choose an existing Fishbone section from this project.")
        valid_features = {
            str(row[0]) for row in conn.execute(
                "SELECT id FROM complexity_features WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        existing = {
            str(row["feature_id"]): dict(row)
            for row in conn.execute(
                """SELECT * FROM assembly_grid_feature_visibility
                   WHERE project_id=? AND section_id=?""",
                (project_id, section_id),
            ).fetchall()
        }
        hidden_features: list[str] = []
        seen: set[str] = set()
        for raw in records:
            feature_id = _catalog_text(raw.get("feature_id"))
            if feature_id not in valid_features:
                raise ValueError("Every feature preference must use a current project feature.")
            if feature_id in seen:
                raise ValueError("A feature may have only one visibility preference per section.")
            seen.add(feature_id)
            if not bool(raw.get("is_visible", True)):
                hidden_features.append(feature_id)
        conn.execute(
            """DELETE FROM assembly_grid_feature_visibility
               WHERE project_id=? AND section_id=?""",
            (project_id, section_id),
        )
        conn.executemany(
            """INSERT INTO assembly_grid_feature_visibility
               (id, project_id, section_id, feature_id, is_visible, created_at, updated_at)
               VALUES (?, ?, ?, ?, 0, ?, ?)""",
            [
                (
                    _catalog_text(existing.get(feature_id, {}).get("id")) or str(uuid4()),
                    project_id, section_id, feature_id,
                    _catalog_text(existing.get(feature_id, {}).get("created_at")) or timestamp,
                    timestamp,
                )
                for feature_id in hidden_features
            ],
        )
    return {
        "count": len(hidden_features),
        "hidden_feature_ids": hidden_features,
        "updated_at": timestamp,
    }


def save_assembly_grid_section(
    project_id: str,
    section_id: str,
    category_rows,
    complete_mapping_rows,
    feature_visibility_rows,
    component_rows_by_assembly: dict[str, list[dict]] | None = None,
) -> dict:
    """Validate and save one complete grid draft in a single transaction."""
    with connection() as conn:
        categories_result = save_assembly_grid_categories(
            project_id, section_id, category_rows, _conn=conn
        )
        mappings_result = save_assembly_grid_model_mappings(
            project_id, complete_mapping_rows, _conn=conn
        )
        visibility_result = save_assembly_grid_feature_visibility(
            project_id, section_id, feature_visibility_rows, _conn=conn
        )
        component_results: dict[str, dict] = {}
        for assembly_id, rows in (component_rows_by_assembly or {}).items():
            component_results[str(assembly_id)] = save_assembly_bom_components(
                project_id, str(assembly_id), rows, _conn=conn
            )
    return {
        "categories": categories_result,
        "mappings": mappings_result,
        "feature_visibility": visibility_result,
        "components": component_results,
        "updated_at": now_iso(),
    }


def delete_assembly_grid_categories(
    project_id: str, section_id: str, category_ids: list[str]
) -> dict:
    """Delete selected grid categories and mappings while preserving assemblies."""
    normalized = list(dict.fromkeys(
        _catalog_text(category_id) for category_id in category_ids
        if _catalog_text(category_id)
    ))
    if not normalized:
        raise ValueError("Select at least one assembly-grid category to delete.")
    placeholders = ", ".join("?" for _ in normalized)
    with connection() as conn:
        categories = conn.execute(
            f"""SELECT id, display_name FROM assembly_grid_categories
                WHERE project_id=? AND section_id=? AND id IN ({placeholders})""",
            (project_id, section_id, *normalized),
        ).fetchall()
        if len(categories) != len(normalized):
            raise ValueError("One or more selected assembly-grid categories no longer exist.")
        mapping_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM assembly_grid_model_mappings
                WHERE project_id=? AND category_id IN ({placeholders})""",
            (project_id, *normalized),
        ).fetchone()[0])
        conn.execute(
            f"""DELETE FROM assembly_grid_categories
                WHERE project_id=? AND section_id=? AND id IN ({placeholders})""",
            (project_id, section_id, *normalized),
        )
    return {
        "deleted_count": len(normalized),
        "mapping_count": mapping_count,
        "category_ids": normalized,
        "category_names": [str(row["display_name"]) for row in categories],
    }


def assembly_catalog_rows(project_id: str) -> pd.DataFrame:
    """Return project-wide assembly catalog rows without scenario-policy joins."""
    rows = query(
        """SELECT assembly.*, parent.assembly_number AS parent_assembly_number,
                  parent.name AS parent_name,
                  built.name AS built_section_name,
                  installed.name AS installed_section_name,
                  (SELECT COUNT(*) FROM manufacturing_assembly_components component
                   WHERE component.assembly_id=assembly.id) AS component_count,
                  (SELECT COUNT(*) FROM manufacturing_assembly_feature_rules rule
                   WHERE rule.assembly_id=assembly.id) AS rule_count,
                  (SELECT COUNT(*) FROM manufacturing_assembly_images image
                   WHERE image.assembly_id=assembly.id) AS supplemental_image_count,
                  (SELECT COUNT(*) FROM manufacturing_assembly_components component
                   JOIN fishbone_part_assignments assignment
                     ON assignment.id=component.fishbone_assignment_id
                   WHERE component.assembly_id=assembly.id
                     AND (assembly.built_section_id IS NULL
                          OR assignment.section_id<>assembly.built_section_id)) AS component_mismatch_count
           FROM manufacturing_assemblies assembly
           LEFT JOIN manufacturing_assemblies parent ON parent.id=assembly.parent_id
           LEFT JOIN assembly_sections built ON built.id=assembly.built_section_id
           LEFT JOIN assembly_sections installed ON installed.id=assembly.installed_section_id
           WHERE assembly.project_id=?
           ORDER BY assembly.assembly_number""",
        (project_id,),
    )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    stale_counts: dict[str, int] = {}
    for row in query(
        """SELECT rule.assembly_id, rule.value, feature.allowed_values, feature.active
           FROM manufacturing_assembly_feature_rules rule
           LEFT JOIN complexity_features feature ON feature.id=rule.feature_id
           WHERE rule.project_id=?""",
        (project_id,),
    ):
        try:
            allowed_values = json.loads(row.get("allowed_values") or "[]")
        except json.JSONDecodeError:
            allowed_values = []
        if not bool(row.get("active")) or str(row.get("value")) not in {
            str(value) for value in allowed_values
        }:
            assembly_id = str(row["assembly_id"])
            stale_counts[assembly_id] = stale_counts.get(assembly_id, 0) + 1
    result["stale_rule_count"] = (
        result["id"].astype(str).map(stale_counts).fillna(0).astype(int)
    )
    return result


def save_assembly_catalog_rows(project_id: str, rows) -> dict:
    """Save catalog-owned assembly fields without touching scenario-policy data."""
    records = _catalog_records(rows)
    timestamp = now_iso()
    with connection() as conn:
        current = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM manufacturing_assemblies WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        valid_sections = {
            str(row[0]) for row in conn.execute(
                "SELECT id FROM assembly_sections WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        normalized: list[dict] = []
        seen_ids: set[str] = set()
        for raw in records:
            assembly_id = _catalog_text(raw.get("id")) or str(uuid4())
            assembly_number = _catalog_text(raw.get("assembly_number"))
            name = _catalog_text(raw.get("name"))
            make_buy = _catalog_text(raw.get("make_buy"))
            built_section_id = _catalog_text(raw.get("built_section_id"))
            installed_section_id = _catalog_text(raw.get("installed_section_id"))
            parent_id = _catalog_text(raw.get("parent_id")) or None
            if assembly_id in seen_ids:
                raise ValueError("The assembly table contains a duplicate internal identifier.")
            if not assembly_number or not name:
                raise ValueError("Every assembly requires an Assembly number and Assembly name.")
            if make_buy not in {"", "Make", "Buy"}:
                raise ValueError("Make / buy must be Make or Buy.")
            previous = current.get(assembly_id)
            if previous is None and not make_buy:
                raise ValueError("Every new assembly requires a Make / buy selection.")
            if previous and _catalog_text(previous.get("make_buy")) and not make_buy:
                raise ValueError("Make / buy cannot be cleared. Choose Make or Buy.")
            managed_category = conn.execute(
                """SELECT DISTINCT category.id, category.display_name, category.section_id,
                          category.installed_section_id
                   FROM assembly_grid_model_mappings mapping
                   JOIN assembly_grid_categories category ON category.id=mapping.category_id
                   WHERE mapping.project_id=? AND mapping.assembly_id=?""",
                (project_id, assembly_id),
            ).fetchone()
            if (
                built_section_id not in valid_sections
                or (installed_section_id and installed_section_id not in valid_sections)
                or (not installed_section_id and not managed_category)
            ):
                raise ValueError(
                    "Every assembly requires valid Built section and Installed section values. "
                    "A grid-managed assembly may remain without an Installed section while its "
                    "category is unassigned."
                )
            if managed_category and (
                built_section_id != _catalog_text(managed_category["section_id"])
                or (installed_section_id or None)
                != (_catalog_text(managed_category["installed_section_id"]) or None)
            ):
                raise ValueError(
                    f"Assembly {assembly_number} is mapped under category "
                    f"{managed_category['display_name']}. Change its Built or Installed section "
                    "through the assembly grid category."
                )
            if parent_id == assembly_id:
                raise ValueError(f"Assembly {assembly_number} cannot be its own parent.")
            raw_active = raw.get("active", True)
            active = 1 if raw_active is None or pd.isna(raw_active) else int(bool(raw_active))
            seen_ids.add(assembly_id)
            normalized.append(
                {
                    "id": assembly_id,
                    "assembly_number": assembly_number,
                    "name": name,
                    "make_buy": make_buy,
                    "parent_id": parent_id,
                    "built_section_id": built_section_id,
                    "installed_section_id": installed_section_id,
                    "active": active,
                    "notes": _catalog_text(raw.get("notes")),
                }
            )

        merged = {assembly_id: dict(value) for assembly_id, value in current.items()}
        merged.update({row["id"]: row for row in normalized})
        numbers: dict[str, str] = {}
        for assembly_id, row in merged.items():
            number_key = _catalog_text(row.get("assembly_number")).casefold()
            if number_key in numbers and numbers[number_key] != assembly_id:
                raise ValueError("Assembly numbers must be unique within the project.")
            numbers[number_key] = assembly_id
        for row in normalized:
            parent_id = row["parent_id"]
            if parent_id and parent_id not in merged:
                raise ValueError(f"Assembly {row['assembly_number']} has an invalid parent assembly.")

        parent_by_id = {
            assembly_id: _catalog_text(row.get("parent_id")) or None
            for assembly_id, row in merged.items()
        }
        for assembly_id in parent_by_id:
            visited: set[str] = set()
            cursor = assembly_id
            while cursor:
                if cursor in visited:
                    raise ValueError("Assembly nesting cannot contain a cycle.")
                visited.add(cursor)
                cursor = parent_by_id.get(cursor)

        mismatch_warnings: list[dict] = []
        for row in normalized:
            parent_id = row["parent_id"]
            parent = merged.get(parent_id) if parent_id else None
            if parent and _catalog_text(row["installed_section_id"]) != _catalog_text(
                parent.get("built_section_id")
            ):
                mismatch_warnings.append(
                    {
                        "assembly_id": row["id"],
                        "assembly_number": row["assembly_number"],
                        "parent_assembly_number": _catalog_text(parent.get("assembly_number")),
                    }
                )

        make_buy_changes: list[dict] = []
        for row in normalized:
            previous = current.get(row["id"])
            previous_make_buy = _catalog_text(previous.get("make_buy")) if previous else ""
            if previous_make_buy != row["make_buy"]:
                make_buy_changes.append(
                    {
                        "assembly_id": row["id"],
                        "assembly_number": row["assembly_number"],
                        "old_value": previous_make_buy,
                        "new_value": row["make_buy"],
                    }
                )
            if previous:
                if _catalog_text(previous.get("built_section_id")) != row["built_section_id"]:
                    conn.execute(
                        """UPDATE fishbone_part_assignments SET section_id=?, updated_at=?
                           WHERE project_id=? AND id IN (
                               SELECT fishbone_assignment_id
                               FROM manufacturing_assembly_components
                               WHERE project_id=? AND assembly_id=?
                           )""",
                        (row["built_section_id"], timestamp, project_id, project_id, row["id"]),
                    )
                conn.execute(
                    """UPDATE manufacturing_assemblies
                       SET assembly_number=?, name=?, make_buy=?, parent_id=?, built_section_id=?,
                           installed_section_id=?, active=?, notes=?, updated_at=?
                       WHERE id=? AND project_id=?""",
                    (
                        row["assembly_number"], row["name"], row["make_buy"], row["parent_id"],
                        row["built_section_id"], row["installed_section_id"],
                        row["active"], row["notes"], timestamp, row["id"], project_id,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO manufacturing_assemblies
                       (id, project_id, assembly_number, name, make_buy, pits_reference,
                        planning_reason, parent_id, built_section_id, installed_section_id,
                        image_path, created_at, active, notes, updated_at)
                       VALUES (?, ?, ?, ?, ?, '', 'Other', ?, ?, ?, '', ?, ?, ?, ?)""",
                    (
                        row["id"], project_id, row["assembly_number"], row["name"],
                        row["make_buy"], row["parent_id"], row["built_section_id"],
                        row["installed_section_id"], timestamp, row["active"],
                        row["notes"], timestamp,
                    ),
                )
    return {
        "count": len(normalized),
        "updated_at": timestamp,
        "mismatch_warnings": mismatch_warnings,
        "make_buy_changes": make_buy_changes,
        "assembly_ids": [row["id"] for row in normalized],
    }


def assembly_bom_components(project_id: str, assembly_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT component.*, assignment.part_id, assignment.section_id,
                  assignment.quantity AS fishbone_quantity,
                  assignment.use_description, assignment.notes AS fishbone_notes,
                  part.part_number, part.description AS part_name,
                  section.name AS current_section_name,
                  assembly.built_section_id,
                  CASE WHEN assignment.section_id=assembly.built_section_id THEN 0 ELSE 1 END
                       AS section_mismatch
           FROM manufacturing_assembly_components component
           JOIN manufacturing_assemblies assembly ON assembly.id=component.assembly_id
           JOIN fishbone_part_assignments assignment
             ON assignment.id=component.fishbone_assignment_id
           JOIN parts part ON part.id=assignment.part_id
           JOIN assembly_sections section ON section.id=assignment.section_id
           WHERE component.project_id=? AND component.assembly_id=?
           ORDER BY part.part_number, assignment.sequence""",
        (project_id, assembly_id),
    ))


def save_assembly_bom_components(
    project_id: str,
    assembly_id: str,
    rows,
    *,
    _conn: sqlite3.Connection | None = None,
) -> dict:
    records = _catalog_records(rows)
    timestamp = now_iso()
    with (connection() if _conn is None else nullcontext(_conn)) as conn:
        assembly = _require_catalog_assembly(conn, project_id, assembly_id)
        built_section_id = _catalog_text(assembly["built_section_id"])
        if not built_section_id:
            raise ValueError("Choose the assembly's Built section before editing its mini-BOM.")
        existing = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                """SELECT * FROM manufacturing_assembly_components
                   WHERE project_id=? AND assembly_id=?""",
                (project_id, assembly_id),
            ).fetchall()
        }
        normalized: list[dict] = []
        assignment_ids: set[str] = set()
        row_ids: set[str] = set()
        for raw in records:
            row_id = _catalog_text(raw.get("id")) or str(uuid4())
            assignment_id = _catalog_text(raw.get("fishbone_assignment_id"))
            if row_id in row_ids or assignment_id in assignment_ids:
                raise ValueError("Each Fishbone use may appear only once in one assembly mini-BOM.")
            assignment = conn.execute(
                """SELECT id, section_id, quantity FROM fishbone_part_assignments
                   WHERE id=? AND project_id=?""",
                (assignment_id, project_id),
            ).fetchone()
            if not assignment:
                raise ValueError("Every mini-BOM row must reference a current project Fishbone use.")
            previous = existing.get(row_id)
            raw_quantity = raw.get("quantity")
            if (
                not previous
                and (
                    raw_quantity is None
                    or pd.isna(raw_quantity)
                    or _catalog_text(raw_quantity) == ""
                )
            ):
                raw_quantity = assignment["quantity"]
            try:
                quantity = float(raw_quantity)
            except (TypeError, ValueError) as exc:
                raise ValueError("Mini-BOM quantities must be numbers greater than zero.") from exc
            if not math.isfinite(quantity) or quantity <= 0:
                raise ValueError("Mini-BOM quantities must be numbers greater than zero.")
            unchanged_stale = bool(
                previous
                and str(previous["fishbone_assignment_id"]) == assignment_id
                and round(float(previous["quantity"]), 9) == round(quantity, 9)
            )
            if str(assignment["section_id"]) != built_section_id and not unchanged_stale:
                raise ValueError(
                    "New or changed mini-BOM rows must use parts currently placed in the assembly's Built section."
                )
            row_ids.add(row_id)
            assignment_ids.add(assignment_id)
            normalized.append(
                {"id": row_id, "fishbone_assignment_id": assignment_id, "quantity": quantity}
            )
        conn.execute(
            "DELETE FROM manufacturing_assembly_components WHERE project_id=? AND assembly_id=?",
            (project_id, assembly_id),
        )
        conn.executemany(
            """INSERT INTO manufacturing_assembly_components
               (id, project_id, assembly_id, fishbone_assignment_id, quantity,
                created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    row["id"], project_id, assembly_id, row["fishbone_assignment_id"],
                    row["quantity"], existing.get(row["id"], {}).get("created_at", timestamp),
                    timestamp,
                )
                for row in normalized
            ],
        )
    return {"count": len(normalized), "updated_at": timestamp}


def assembly_feature_rules(project_id: str, assembly_id: str) -> pd.DataFrame:
    rows = query(
        """SELECT rule.*, feature.name AS feature_name, feature.category,
                  feature.allowed_values, feature.active AS feature_active
           FROM manufacturing_assembly_feature_rules rule
           LEFT JOIN complexity_features feature ON feature.id=rule.feature_id
           WHERE rule.project_id=? AND rule.assembly_id=?
           ORDER BY feature.category, feature.name, rule.created_at""",
        (project_id, assembly_id),
    )
    result = pd.DataFrame(rows)
    if result.empty:
        return result

    def stale(row) -> bool:
        try:
            choices = json.loads(row.get("allowed_values") or "[]")
        except json.JSONDecodeError:
            choices = []
        return not bool(row.get("feature_active")) or str(row.get("value")) not in {
            str(choice) for choice in choices
        }

    result["stale"] = result.apply(stale, axis=1)
    result["warning"] = result["stale"].map(
        lambda value: "Warning: references a removed choice — review and update" if value else ""
    )
    return result


def save_assembly_feature_rules(project_id: str, assembly_id: str, rows) -> dict:
    records = _catalog_records(rows)
    timestamp = now_iso()
    with connection() as conn:
        _require_catalog_assembly(conn, project_id, assembly_id)
        existing = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                """SELECT * FROM manufacturing_assembly_feature_rules
                   WHERE project_id=? AND assembly_id=?""",
                (project_id, assembly_id),
            ).fetchall()
        }
        features = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM complexity_features WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        normalized: list[dict] = []
        feature_ids: set[str] = set()
        row_ids: set[str] = set()
        for raw in records:
            row_id = _catalog_text(raw.get("id")) or str(uuid4())
            feature_id = _catalog_text(raw.get("feature_id"))
            value = _catalog_text(raw.get("value"))
            if row_id in row_ids or feature_id in feature_ids:
                raise ValueError("An assembly may have at most one choice for each feature.")
            feature = features.get(feature_id)
            previous = existing.get(row_id)
            unchanged_stale = bool(
                previous
                and str(previous["feature_id"]) == feature_id
                and str(previous["value"]) == value
            )
            try:
                allowed = {
                    str(choice) for choice in json.loads((feature or {}).get("allowed_values") or "[]")
                }
            except json.JSONDecodeError:
                allowed = set()
            if (
                not feature
                or not bool(feature.get("active"))
                or value not in allowed
            ) and not unchanged_stale:
                raise ValueError(
                    "New or changed assembly rules must use an active feature and one of its current choices."
                )
            row_ids.add(row_id)
            feature_ids.add(feature_id)
            normalized.append({"id": row_id, "feature_id": feature_id, "value": value})
        conn.execute(
            """DELETE FROM manufacturing_assembly_feature_rules
               WHERE project_id=? AND assembly_id=?""",
            (project_id, assembly_id),
        )
        conn.executemany(
            """INSERT INTO manufacturing_assembly_feature_rules
               (id, project_id, assembly_id, feature_id, value, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    row["id"], project_id, assembly_id, row["feature_id"], row["value"],
                    existing.get(row["id"], {}).get("created_at", timestamp), timestamp,
                )
                for row in normalized
            ],
        )
    return {"count": len(normalized), "updated_at": timestamp}


def assembly_model_applicability(project_id: str, assembly_id: str) -> dict:
    """Return active official models explicitly paired to an assembly in the grid."""
    models = project_models(project_id)
    if not models.empty:
        models = models.loc[models["active"].fillna(1).astype(bool)].copy()
    mapped_ids = {
        str(row["model_id"])
        for row in query(
            """SELECT DISTINCT model_id FROM assembly_grid_model_mappings
               WHERE project_id=? AND assembly_id=?""",
            (project_id, assembly_id),
        )
    }
    matching = models.loc[models["id"].astype(str).isin(mapped_ids)].copy()
    return {
        "stale": False,
        "summary": "Mapped in Assembly grid" if mapped_ids else "No mapped models",
        "models": matching,
    }


def assembly_images(project_id: str, assembly_id: str) -> list[dict]:
    return query(
        """SELECT * FROM manufacturing_assembly_images
           WHERE project_id=? AND assembly_id=? ORDER BY created_at""",
        (project_id, assembly_id),
    )


def _assembly_image_target(assembly_id: str, uploaded_file) -> Path:
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Use PNG, JPG, JPEG, or WEBP images.")
    return UPLOAD_DIR / f"assembly_{assembly_id}_{uuid4()}{suffix}"


def _remove_owned_upload(path_value) -> None:
    if not path_value:
        return
    path = Path(str(path_value))
    try:
        if path.exists() and path.is_file() and UPLOAD_DIR.resolve() in path.resolve().parents:
            path.unlink()
    except OSError:
        pass


def set_assembly_image(project_id: str, assembly_id: str, uploaded_file) -> str:
    target = _assembly_image_target(assembly_id, uploaded_file)
    content = uploaded_file.getvalue()
    if not content:
        raise ValueError("Choose a non-empty image.")
    target.write_bytes(content)
    previous_path = ""
    try:
        with connection() as conn:
            assembly = _require_catalog_assembly(conn, project_id, assembly_id)
            previous_path = _catalog_text(assembly["image_path"])
            conn.execute(
                """UPDATE manufacturing_assemblies SET image_path=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (str(target), now_iso(), assembly_id, project_id),
            )
    except Exception:
        _remove_owned_upload(target)
        raise
    if previous_path != str(target):
        _remove_owned_upload(previous_path)
    return str(target)


def add_assembly_image(
    project_id: str, assembly_id: str, uploaded_file, caption: str = ""
) -> str:
    target = _assembly_image_target(assembly_id, uploaded_file)
    content = uploaded_file.getvalue()
    if not content:
        raise ValueError("Choose a non-empty image.")
    target.write_bytes(content)
    image_id = str(uuid4())
    try:
        with connection() as conn:
            _require_catalog_assembly(conn, project_id, assembly_id)
            conn.execute(
                """INSERT INTO manufacturing_assembly_images
                   (id, project_id, assembly_id, image_path, caption, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (image_id, project_id, assembly_id, str(target), _catalog_text(caption), now_iso()),
            )
    except Exception:
        _remove_owned_upload(target)
        raise
    return image_id


def delete_assembly_images(
    project_id: str, assembly_id: str, image_ids: list[str]
) -> int:
    normalized = list(
        dict.fromkeys(_catalog_text(value) for value in image_ids if _catalog_text(value))
    )
    if not normalized:
        return 0
    placeholders = ",".join("?" for _ in normalized)
    with connection() as conn:
        _require_catalog_assembly(conn, project_id, assembly_id)
        rows = conn.execute(
            f"""SELECT id, image_path FROM manufacturing_assembly_images
                WHERE project_id=? AND assembly_id=? AND id IN ({placeholders})""",
            (project_id, assembly_id, *normalized),
        ).fetchall()
        if len(rows) != len(normalized):
            raise ValueError("One or more selected assembly images no longer exist.")
        conn.execute(
            f"""DELETE FROM manufacturing_assembly_images
                WHERE project_id=? AND assembly_id=? AND id IN ({placeholders})""",
            (project_id, assembly_id, *normalized),
        )
    for row in rows:
        _remove_owned_upload(row["image_path"])
    return len(rows)


def assemblies_for_section(project_id: str, section_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT assembly.id, assembly.assembly_number, assembly.name,
                  'Built here' AS relationship
           FROM manufacturing_assemblies assembly
           WHERE assembly.project_id=? AND assembly.built_section_id=?
           UNION ALL
           SELECT assembly.id, assembly.assembly_number, assembly.name,
                  'Installed here' AS relationship
           FROM manufacturing_assemblies assembly
           WHERE assembly.project_id=? AND assembly.installed_section_id=?
           ORDER BY assembly_number, relationship""",
        (project_id, section_id, project_id, section_id),
    ))


def fishbone_assignment_assembly_impact(
    project_id: str, assignment_ids: list[str]
) -> pd.DataFrame:
    normalized = list(
        dict.fromkeys(_catalog_text(value) for value in assignment_ids if _catalog_text(value))
    )
    if not normalized:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in normalized)
    return pd.DataFrame(query(
        f"""SELECT component.id AS component_id, component.fishbone_assignment_id,
                   assembly.id AS assembly_id, assembly.assembly_number, assembly.name
            FROM manufacturing_assembly_components component
            JOIN manufacturing_assemblies assembly ON assembly.id=component.assembly_id
            WHERE component.project_id=?
              AND component.fishbone_assignment_id IN ({placeholders})
            ORDER BY assembly.assembly_number""",
        (project_id, *normalized),
    ))


def assembly_section_reference_impact(
    project_id: str,
    section_ids: list[str],
    connection: sqlite3.Connection | None = None,
) -> pd.DataFrame:
    normalized = list(
        dict.fromkeys(_catalog_text(value) for value in section_ids if _catalog_text(value))
    )
    if not normalized:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in normalized)
    sql = f"""SELECT assembly.id AS assembly_id, assembly.assembly_number, assembly.name,
                     assembly.built_section_id, built.name AS built_section_name,
                     assembly.installed_section_id, installed.name AS installed_section_name
              FROM manufacturing_assemblies assembly
              LEFT JOIN assembly_sections built ON built.id=assembly.built_section_id
              LEFT JOIN assembly_sections installed ON installed.id=assembly.installed_section_id
              WHERE assembly.project_id=? AND (
                  assembly.built_section_id IN ({placeholders})
                  OR assembly.installed_section_id IN ({placeholders})
              ) ORDER BY assembly.assembly_number"""
    params = (project_id, *normalized, *normalized)
    if connection is not None:
        return pd.DataFrame([dict(row) for row in connection.execute(sql, params).fetchall()])
    return pd.DataFrame(query(sql, params))


def repoint_assembly_section_references(
    project_id: str, replacements, connection: sqlite3.Connection | None = None
) -> int:
    records = _catalog_records(replacements)
    timestamp = now_iso()
    context = nullcontext(connection) if connection is not None else globals()["connection"]()
    with context as conn:
        valid_sections = {
            str(row[0]) for row in conn.execute(
                "SELECT id FROM assembly_sections WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        normalized: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for row in records:
            assembly_id = _catalog_text(row.get("assembly_id"))
            field = _catalog_text(row.get("field"))
            section_id = _catalog_text(row.get("section_id"))
            if field not in {"built_section_id", "installed_section_id"}:
                raise ValueError("Choose whether each replacement applies to Built or Installed section.")
            if section_id not in valid_sections:
                raise ValueError("Every assembly section replacement must be a current project section.")
            _require_catalog_assembly(conn, project_id, assembly_id)
            if (assembly_id, field) in seen:
                raise ValueError("Each assembly section relationship needs exactly one replacement.")
            seen.add((assembly_id, field))
            normalized.append((assembly_id, field, section_id))
        for assembly_id, field, section_id in normalized:
            if field == "built_section_id":
                conn.execute(
                    """UPDATE fishbone_part_assignments SET section_id=?, updated_at=?
                       WHERE project_id=? AND id IN (
                           SELECT fishbone_assignment_id
                           FROM manufacturing_assembly_components
                           WHERE project_id=? AND assembly_id=?
                       )""",
                    (section_id, timestamp, project_id, project_id, assembly_id),
                )
            conn.execute(
                f"""UPDATE manufacturing_assemblies SET {field}=?, updated_at=?
                    WHERE id=? AND project_id=?""",
                (section_id, timestamp, assembly_id, project_id),
            )
    return len(normalized)


def assembly_catalog_delete_impact(project_id: str, assembly_ids: list[str]) -> dict:
    normalized = list(
        dict.fromkeys(_catalog_text(value) for value in assembly_ids if _catalog_text(value))
    )
    if not normalized:
        raise ValueError("Select at least one assembly to delete.")
    placeholders = ",".join("?" for _ in normalized)
    with connection() as conn:
        selected_count = conn.execute(
            f"""SELECT COUNT(*) FROM manufacturing_assemblies
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *normalized),
        ).fetchone()[0]
        if int(selected_count) != len(normalized):
            raise ValueError("One or more selected assemblies no longer exist.")
        rows = conn.execute(
            f"""WITH RECURSIVE tree(id, assembly_number, name, parent_id, depth) AS (
                    SELECT id, assembly_number, name, parent_id, 0
                    FROM manufacturing_assemblies
                    WHERE project_id=? AND id IN ({placeholders})
                    UNION
                    SELECT child.id, child.assembly_number, child.name, child.parent_id,
                           tree.depth + 1
                    FROM manufacturing_assemblies child JOIN tree ON child.parent_id=tree.id
                    WHERE child.project_id=?
                )
                SELECT id, assembly_number, name, parent_id, MIN(depth) AS depth
                FROM tree GROUP BY id, assembly_number, name, parent_id
                ORDER BY depth, assembly_number""",
            (project_id, *normalized, project_id),
        ).fetchall()
        affected_ids = [str(row["id"]) for row in rows]
        affected_placeholders = ",".join("?" for _ in affected_ids)

        def count(table: str, column: str = "assembly_id") -> int:
            return int(conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IN ({affected_placeholders})",
                tuple(affected_ids),
            ).fetchone()[0])

        levels: dict[int, list[dict]] = {}
        for row in rows:
            levels.setdefault(int(row["depth"]), []).append(dict(row))
        image_paths = [
            str(row[0]) for row in conn.execute(
                f"""SELECT image_path FROM manufacturing_assemblies
                    WHERE id IN ({affected_placeholders}) AND TRIM(COALESCE(image_path, ''))<>''
                    UNION ALL
                    SELECT image_path FROM manufacturing_assembly_images
                    WHERE assembly_id IN ({affected_placeholders})""",
                (*affected_ids, *affected_ids),
            ).fetchall()
        ]
        return {
            "selected_ids": normalized,
            "affected_ids": affected_ids,
            "selected_count": len(normalized),
            "descendant_count": len(affected_ids) - len(normalized),
            "levels": levels,
            "component_count": count("manufacturing_assembly_components"),
            "rule_count": count("manufacturing_assembly_feature_rules"),
            "supplemental_image_count": count("manufacturing_assembly_images"),
            "grid_mapping_count": count("assembly_grid_model_mappings"),
            "primary_image_count": int(conn.execute(
                f"""SELECT COUNT(*) FROM manufacturing_assemblies
                    WHERE id IN ({affected_placeholders})
                      AND TRIM(COALESCE(image_path, ''))<>''""",
                tuple(affected_ids),
            ).fetchone()[0]),
            "image_paths": image_paths,
            "image_file_count": len(image_paths),
            "policy_count": count("assembly_scenario_policies"),
            "material_option_count": count("work_element_material_options"),
            "target_assembly_link_count": count(
                "work_element_material_groups", "target_assembly_id"
            ),
        }


def delete_assembly_catalog_rows(
    project_id: str, assembly_ids: list[str], level_actions: dict
) -> dict:
    impact = assembly_catalog_delete_impact(project_id, assembly_ids)
    actions = {int(depth): str(action) for depth, action in dict(level_actions or {}).items()}
    allowed = {"Move to grandparent", "Delete entirely", "Become unassigned"}
    for depth in impact["levels"]:
        if depth > 0 and actions.get(depth) not in allowed:
            raise ValueError(f"Choose what happens to child assemblies at level {depth}.")
    selected_ids = set(impact["selected_ids"])
    deleted_ids = set(selected_ids)
    for depth, rows in impact["levels"].items():
        if depth > 0 and actions.get(depth) == "Delete entirely":
            deleted_ids.update(str(row["id"]) for row in rows)
    all_rows = {
        str(row["id"]): dict(row)
        for depth_rows in impact["levels"].values() for row in depth_rows
    }
    image_paths: list[str] = []
    timestamp = now_iso()
    with connection() as conn:
        if deleted_ids:
            placeholders = ",".join("?" for _ in deleted_ids)
            image_paths.extend(
                str(row[0]) for row in conn.execute(
                    f"""SELECT image_path FROM manufacturing_assemblies
                        WHERE project_id=? AND id IN ({placeholders})
                          AND TRIM(COALESCE(image_path, ''))<>''""",
                    (project_id, *deleted_ids),
                ).fetchall()
            )
            image_paths.extend(
                str(row[0]) for row in conn.execute(
                    f"""SELECT image_path FROM manufacturing_assembly_images
                        WHERE project_id=? AND assembly_id IN ({placeholders})""",
                    (project_id, *deleted_ids),
                ).fetchall()
            )
        for depth, rows in impact["levels"].items():
            if depth == 0 or actions.get(depth) == "Delete entirely":
                continue
            action = actions[depth]
            for row in rows:
                assembly_id = str(row["id"])
                if assembly_id in deleted_ids:
                    continue
                if action == "Become unassigned":
                    conn.execute(
                        """UPDATE manufacturing_assemblies
                           SET parent_id=NULL, built_section_id=NULL, installed_section_id=NULL,
                               updated_at=? WHERE id=? AND project_id=?""",
                        (timestamp, assembly_id, project_id),
                    )
                else:
                    parent_id = _catalog_text(row.get("parent_id")) or None
                    while parent_id in deleted_ids:
                        parent_id = (
                            _catalog_text(all_rows.get(parent_id, {}).get("parent_id")) or None
                        )
                    conn.execute(
                        """UPDATE manufacturing_assemblies SET parent_id=?, updated_at=?
                           WHERE id=? AND project_id=?""",
                        (parent_id, timestamp, assembly_id, project_id),
                    )
        if deleted_ids:
            placeholders = ",".join("?" for _ in deleted_ids)
            conn.execute(
                f"""DELETE FROM manufacturing_assemblies
                    WHERE project_id=? AND id IN ({placeholders})""",
                (project_id, *deleted_ids),
            )
    for path in image_paths:
        _remove_owned_upload(path)
    return {**impact, "deleted_count": len(deleted_ids), "level_actions": actions}


def reset_manufacturing_assembly_catalog(
    verified_backup_path: str | Path,
    editor_name: str,
) -> dict:
    """Perform the approved one-time catalog reset after validating its DB backup."""
    backup_path = Path(verified_backup_path).resolve()
    if not backup_path.exists() or not backup_path.is_file() or backup_path.stat().st_size <= 0:
        raise ValueError("Confirm a valid PAAG database backup before resetting assemblies.")
    if backup_path == DB_PATH.resolve():
        raise ValueError("The verified backup must be separate from the live PAAG database.")
    with closing(sqlite3.connect(
        f"file:{backup_path.as_posix()}?mode=ro", uri=True
    )) as backup_conn:
        result = backup_conn.execute("PRAGMA quick_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            raise ValueError("The verified PAAG database backup did not pass SQLite validation.")

    timestamp = now_iso()
    image_paths: list[str] = []
    summary: dict = {}
    with connection() as conn:
        project_counts = [dict(row) for row in conn.execute(
            """SELECT project_id, COUNT(*) AS assembly_count
               FROM manufacturing_assemblies GROUP BY project_id"""
        ).fetchall()]

        def table_count(table: str) -> int:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

        image_paths = [
            str(row[0])
            for row in conn.execute(
                """SELECT image_path FROM manufacturing_assemblies
                   WHERE TRIM(COALESCE(image_path, ''))<>''
                   UNION ALL
                   SELECT image_path FROM manufacturing_assembly_images"""
            ).fetchall()
        ]
        summary = {
            "assembly_count": table_count("manufacturing_assemblies"),
            "component_count": table_count("manufacturing_assembly_components"),
            "feature_rule_count": table_count("manufacturing_assembly_feature_rules"),
            "supplemental_image_count": table_count("manufacturing_assembly_images"),
            "owned_image_file_count": len(image_paths),
            "grid_mapping_count": table_count("assembly_grid_model_mappings"),
            "scenario_policy_count": table_count("assembly_scenario_policies"),
            "material_option_count": int(conn.execute(
                "SELECT COUNT(*) FROM work_element_material_options WHERE assembly_id IS NOT NULL"
            ).fetchone()[0]),
            "material_target_count": int(conn.execute(
                "SELECT COUNT(*) FROM work_element_material_groups WHERE target_assembly_id IS NOT NULL"
            ).fetchone()[0]),
            "backup_path": str(backup_path),
        }
        conn.execute("DELETE FROM manufacturing_assemblies")
        for project in project_counts:
            details = {
                **summary,
                "project_assembly_count": int(project["assembly_count"]),
                "scope": "Approved Task 09 one-time assembly-catalog reset",
            }
            conn.execute(
                """INSERT INTO audit_log
                   (id, project_id, table_name, action, row_count, editor_name, details, created_at)
                   VALUES (?, ?, 'Assemblies catalog', 'Prototype data reset', ?, ?, ?, ?)""",
                (
                    str(uuid4()),
                    str(project["project_id"]),
                    int(project["assembly_count"]),
                    editor_name.strip(),
                    json.dumps(details, ensure_ascii=False),
                    timestamp,
                ),
            )
    for image_path in image_paths:
        _remove_owned_upload(image_path)
    return summary


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
           LEFT JOIN part_scenario_activity activity
             ON activity.project_id=group_row.project_id
            AND activity.scenario_id=group_row.scenario_id
            AND activity.part_id=option.part_id
           WHERE group_row.project_id=? AND group_row.scenario_id=?
             AND (option.part_id IS NULL OR COALESCE(activity.active, 1)=1)
           ORDER BY element.sequence, group_row.name, part.part_number""",
        (project_id, scenario_id),
    )
    return pd.DataFrame(rows)


def yamazumi_elements_for_section(
    project_id: str, scenario_id: str, section_id: str
) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT element.id, element.process_element_id, element.description,
                  element.time_s, element.model_variant, element.model_variants, element.work_type,
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


def yamazumi_context_for_process(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Return Yamazumi source labels linked to Process at a Glance rows."""
    rows = query(
        """SELECT element.process_element_id, element.id AS yamazumi_element_id,
                  element.description AS yamazumi_description,
                  element.time_s AS yamazumi_time_s,
                  pitch.pitch_number, pitch.pitch_name
           FROM yamazumi_elements element
           JOIN yamazumi_areas area ON area.id=element.area_id
           LEFT JOIN yamazumi_pitches pitch ON pitch.id=element.pitch_id
           WHERE element.project_id=? AND area.scenario_id=?
             AND element.process_element_id IS NOT NULL
             AND TRIM(element.process_element_id) <> ''
           ORDER BY area.name, pitch.sequence, element.sequence""",
        (project_id, scenario_id),
    )
    return pd.DataFrame(rows)


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
    project_id: str,
    scenario_id: str,
    work_element_id: str | None = None,
    *,
    active_only: bool = False,
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
        activity_join = """
            LEFT JOIN part_scenario_activity activity
              ON activity.project_id=? AND activity.scenario_id=?
             AND activity.part_id=option.part_id
        """ if active_only else ""
        activity_clause = " AND COALESCE(activity.active, 1)=1" if active_only else ""
        option_params = (
            (project_id, scenario_id, group["id"])
            if active_only else (group["id"],)
        )
        options = query(
            f"""SELECT option.id, option.part_id, part.part_number,
                      part.description AS part_description, part.model_applicability
               FROM process_part_options option
               JOIN parts part ON part.id=option.part_id
               {activity_join}
               WHERE option.group_id=?{activity_clause} ORDER BY part.part_number""",
            option_params,
        )
        group["options"] = options
        group["part_ids"] = [str(option["part_id"]) for option in options]
    return [group for group in groups if group["options"]] if active_only else groups


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


def delete_process_part_groups(
    project_id: str, scenario_id: str, group_ids: list[str]
) -> int:
    """Delete validated process-part groups together and reopen their source parts."""
    normalized_ids = list(
        dict.fromkeys(
            str(group_id).strip()
            for group_id in group_ids
            if str(group_id).strip()
        )
    )
    if not normalized_ids:
        return 0
    placeholders = ", ".join("?" for _ in normalized_ids)
    with connection() as conn:
        group_rows = conn.execute(
            f"""SELECT id, work_element_id FROM process_part_groups
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *normalized_ids),
        ).fetchall()
        found_ids = {str(row["id"]) for row in group_rows}
        missing_ids = [group_id for group_id in normalized_ids if group_id not in found_ids]
        if missing_ids:
            raise ValueError(
                "One or more selected part pairings no longer exist. Refresh and try again."
            )
        affected_work_element_ids = {
            str(row["work_element_id"]) for row in group_rows
        }
        cursor = conn.execute(
            f"""DELETE FROM process_part_groups
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *normalized_ids),
        )
        timestamp = now_iso()
        for work_element_id in affected_work_element_ids:
            remaining = conn.execute(
                """SELECT 1 FROM process_part_groups
                   WHERE project_id=? AND scenario_id=? AND work_element_id=? LIMIT 1""",
                (project_id, scenario_id, work_element_id),
            ).fetchone()
            if not remaining:
                conn.execute(
                    """UPDATE yamazumi_elements
                       SET process_sync_status='Needs IE review', updated_at=?
                       WHERE project_id=? AND process_element_id=?""",
                    (timestamp, project_id, work_element_id),
                )
        return int(cursor.rowcount)


def delete_process_part_group(
    project_id: str, scenario_id: str, group_id: str
) -> bool:
    return bool(delete_process_part_groups(project_id, scenario_id, [group_id]))


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
            "model_variants": pd.Series(dtype="string"),
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
            "model_variants": pd.Series(dtype="string"),
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


def pin_map_for_scenario(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Load pitches and their explicitly linked Process work for one scenario."""
    rows = pd.DataFrame(query(
        """SELECT p.id AS pitch_id, p.area_id, a.name AS area_name,
                  p.pitch_number, p.pitch_name, p.pitch_type,
                  p.status AS pitch_status, p.sequence AS pitch_sequence,
                  work.id AS process_element_id,
                  work.sequence AS process_sequence,
                  work.operation AS work_element,
                  work.description AS process_description,
                  work.cycle_time_s, work.tool, work.torque,
                  work.quality_requirement, work.ergo_requirement,
                  work.location, work.unit_orientation,
                  work.model_applicability,
                  work.status AS process_status
           FROM yamazumi_pitches p
           JOIN yamazumi_areas a ON a.id=p.area_id
           LEFT JOIN yamazumi_elements yamazumi
             ON yamazumi.pitch_id=p.id AND yamazumi.project_id=p.project_id
           LEFT JOIN work_elements work
             ON work.id=yamazumi.process_element_id
            AND work.project_id=p.project_id
            AND work.scenario_id=a.scenario_id
           WHERE p.project_id=? AND a.scenario_id=?
           ORDER BY a.name, p.sequence, p.pitch_number,
                    work.sequence, work.operation""",
        (project_id, scenario_id),
    ))
    if rows.empty:
        return pd.DataFrame({
            "pitch_id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "area_name": pd.Series(dtype="string"),
            "pitch_number": pd.Series(dtype="string"),
            "pitch_name": pd.Series(dtype="string"),
            "pitch_type": pd.Series(dtype="string"),
            "pitch_status": pd.Series(dtype="string"),
            "pitch_sequence": pd.Series(dtype="Int64"),
            "process_element_id": pd.Series(dtype="string"),
            "process_sequence": pd.Series(dtype="Int64"),
            "work_element": pd.Series(dtype="string"),
            "process_description": pd.Series(dtype="string"),
            "cycle_time_s": pd.Series(dtype="Float64"),
            "tool": pd.Series(dtype="string"),
            "torque": pd.Series(dtype="string"),
            "quality_requirement": pd.Series(dtype="string"),
            "ergo_requirement": pd.Series(dtype="string"),
            "location": pd.Series(dtype="string"),
            "unit_orientation": pd.Series(dtype="string"),
            "model_applicability": pd.Series(dtype="string"),
            "process_status": pd.Series(dtype="string"),
        })
    rows = rows.drop_duplicates(
        subset=["pitch_id", "process_element_id"], keep="first"
    )
    linked_pitch_ids = set(
        rows.loc[rows["process_element_id"].notna(), "pitch_id"].astype(str)
    )
    rows = rows.loc[
        ~(
            rows["pitch_id"].astype(str).isin(linked_pitch_ids)
            & rows["process_element_id"].isna()
        )
    ]
    return rows.reset_index(drop=True)


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


def rename_yamazumi_variants(
    project_id: str, scenario_id: str, label_mapping: dict[str, str]
) -> dict[str, object]:
    """Normalize saved Yamazumi labels and describe every persisted change."""
    mapping = {str(old): str(new) for old, new in label_mapping.items() if str(old) != str(new)}
    if not mapping:
        return {"changed_count": 0, "element_changes": [], "pitch_changes": []}
    element_changes: list[dict[str, object]] = []
    pitch_changes: list[dict[str, object]] = []
    timestamp = now_iso()
    with connection() as conn:
        elements = conn.execute(
            """SELECT e.id, e.model_variant, e.model_variants FROM yamazumi_elements e
               JOIN yamazumi_areas a ON a.id=e.area_id
               WHERE e.project_id=? AND a.scenario_id=?""", (project_id, scenario_id)
        ).fetchall()
        for element in elements:
            variants = parse_yamazumi_model_variants(
                element["model_variants"], str(element["model_variant"] or "Base")
            )
            normalized = list(dict.fromkeys(mapping.get(value, value) for value in variants))
            primary_variant = normalized[0]
            if normalized != variants or primary_variant != str(element["model_variant"]):
                conn.execute(
                    """UPDATE yamazumi_elements
                       SET model_variant=?, model_variants=?, updated_at=? WHERE id=?""",
                    (primary_variant, json.dumps(normalized), timestamp, element["id"]),
                )
                element_changes.append(
                    {
                        "element_id": str(element["id"]),
                        "old_primary_variant": str(element["model_variant"] or "Base"),
                        "new_primary_variant": primary_variant,
                        "old_variants": variants,
                        "new_variants": normalized,
                    }
                )
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
                pitch_changes.append(
                    {
                        "pitch_id": str(pitch["id"]),
                        "old_variants": variants,
                        "new_variants": normalized,
                    }
                )
    return {
        "changed_count": len(element_changes) + len(pitch_changes),
        "element_changes": element_changes,
        "pitch_changes": pitch_changes,
    }


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
    raw_variants = (
        values.get("model_variants")
        if "model_variants" in values
        else values.get("model_variant") or "Base"
    )
    selected_variants = parse_yamazumi_model_variants(raw_variants, fallback=None)
    if not selected_variants:
        raise ValueError("Choose at least one model variant for the work element.")
    primary_variant = selected_variants[0]
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
            missing_variants = [
                variant for variant in selected_variants if variant not in pitch_variants
            ]
            if missing_variants:
                pitch_variants.extend(missing_variants)
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
               (id, project_id, area_id, pitch_id, model_variant, model_variants,
                work_type, description,
                time_s, work_region, flags, sequence, source, process_sync_status, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Interactive board', 'Needs IE review', ?)""",
            (
                element_id, project_id, area_id, pitch_id,
                primary_variant, json.dumps(selected_variants),
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
            "SELECT model_variant, model_variants FROM yamazumi_elements WHERE pitch_id=?",
            (pitch_id,),
        ).fetchall()
        if status != "Active" and assigned:
            raise ValueError("Move work out of this pitch before changing it to Open or Blocked.")
        used_variants = {
            variant
            for row in assigned
            for variant in parse_yamazumi_model_variants(row["model_variants"], row["model_variant"])
        }
        missing_used = used_variants - set(variants)
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
    raw_variants = (
        values.get("model_variants")
        if "model_variants" in values
        else values.get("model_variant") or "Base"
    )
    model_variants = parse_yamazumi_model_variants(raw_variants, fallback=None)
    if not model_variants:
        raise ValueError("Choose at least one model variant for the work element.")
    primary_variant = model_variants[0]
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
            destination_variants = set(parse_yamazumi_model_variants(destination[0], fallback=None))
            missing_variants = set(model_variants) - destination_variants
            if missing_variants:
                raise ValueError(
                    "Enable these model variants on the destination pitch first: "
                    + ", ".join(sorted(missing_variants))
                    + "."
                )
        conn.execute(
            """UPDATE yamazumi_elements
               SET pitch_id=?, model_variant=?, model_variants=?, work_type=?, description=?, time_s=?,
                   work_region=?, flags=?, process_sync_status='Needs IE review', updated_at=?
               WHERE id=? AND project_id=? AND area_id=?""",
            (
                pitch_id,
                primary_variant,
                json.dumps(model_variants),
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
                variant
                for used in conn.execute(
                    "SELECT model_variant, model_variants FROM yamazumi_elements WHERE pitch_id=?",
                    (pitch_id,),
                ).fetchall()
                for variant in parse_yamazumi_model_variants(
                    used["model_variants"], used["model_variant"]
                )
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
    required = {"id", "pitch_id", "model_variants", "work_type", "description", "time_s", "work_region", "flags", "sequence"}
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
            model_variants = parse_yamazumi_model_variants(
                row.get("model_variants"), fallback=None
            )
            if not model_variants:
                raise ValueError("Choose at least one model variant for every work element.")
            primary_variant = model_variants[0]
            work_type = str(row.get("work_type") or "Cycle").strip().title()
            if work_type not in {"Cycle", "Periodic", "Fluctuation"}:
                raise ValueError("Work type must be Cycle, Periodic, or Fluctuation.")
            if pitch_id:
                pitch_variants_row = conn.execute(
                    "SELECT model_variants FROM yamazumi_pitches WHERE id=?", (pitch_id,)
                ).fetchone()
                pitch_variants = set(
                    parse_yamazumi_model_variants(pitch_variants_row[0], fallback=None)
                )
                missing_variants = set(model_variants) - pitch_variants
                if missing_variants:
                    raise ValueError(
                        "Enable these model variants on the selected pitch first: "
                        + ", ".join(sorted(missing_variants))
                        + "."
                    )
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
                   (id, project_id, area_id, pitch_id, model_variant, model_variants,
                    work_type, description,
                    time_s, work_region, flags, sequence, source, process_element_id,
                    process_sync_status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET pitch_id=excluded.pitch_id,
                    model_variant=excluded.model_variant, model_variants=excluded.model_variants,
                    work_type=excluded.work_type,
                    description=excluded.description, time_s=excluded.time_s,
                    work_region=excluded.work_region, flags=excluded.flags,
                    sequence=excluded.sequence, process_sync_status='Needs IE review',
                    updated_at=excluded.updated_at""",
                (element_id, project_id, area_id, pitch_id, primary_variant,
                 json.dumps(model_variants),
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


def move_yamazumi_element(
    project_id: str, element_id: str, pitch_id: str | None
) -> list[str]:
    """Move one linked work record and return variants added to the destination pitch."""
    timestamp = now_iso()
    enabled_variants: list[str] = []
    with connection() as conn:
        element = conn.execute(
            """SELECT model_variant, model_variants FROM yamazumi_elements
               WHERE id=? AND project_id=?""",
            (element_id, project_id),
        ).fetchone()
        if not element:
            raise ValueError("That work element no longer exists.")
        element_variants = parse_yamazumi_model_variants(
            element["model_variants"], element["model_variant"]
        )
        if pitch_id:
            destination = conn.execute(
                """SELECT id, model_variants FROM yamazumi_pitches
                   WHERE id=? AND project_id=? AND status='Active'""",
                (pitch_id, project_id),
            ).fetchone()
            if not destination:
                raise ValueError("Work can only be moved into an Active pitch.")
            destination_variants = parse_yamazumi_model_variants(
                destination["model_variants"], fallback=None
            )
            enabled_variants = [
                variant for variant in element_variants
                if variant not in destination_variants
            ]
            if enabled_variants:
                conn.execute(
                    """UPDATE yamazumi_pitches SET model_variants=?, updated_at=?
                       WHERE id=? AND project_id=?""",
                    (
                        json.dumps([*destination_variants, *enabled_variants]),
                        timestamp,
                        pitch_id,
                        project_id,
                    ),
                )
        conn.execute(
            """UPDATE yamazumi_elements
               SET pitch_id=?, process_sync_status='Needs IE review', updated_at=?
               WHERE id=? AND project_id=?""",
            (pitch_id or None, timestamp, element_id, project_id),
        )
    return enabled_variants


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
        imported_variant = str(row.get("Model_variant") or "Base").strip().title()
        execute(
            """INSERT INTO yamazumi_elements
               (id, project_id, area_id, pitch_id, model_variant, model_variants,
                work_type, description,
                time_s, work_region, flags, sequence, source, process_sync_status, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Excel import', 'Needs IE review', ?)""",
            (str(uuid4()), project_id, area_id, assigned_pitch_id, imported_variant,
             json.dumps([imported_variant]),
             str(row.get("Work_Type") or "Cycle").strip().title(), description,
             float(row.get("Work_Time_to_complete") or 0), str(row.get("Work_region") or "None").strip(),
             json.dumps(flags), (index + 1) * 10, timestamp),
        )
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
            model_variants = parse_yamazumi_model_variants(
                row["model_variants"], row["model_variant"]
            )
            model_applicability = (
                "All"
                if any(value.casefold() == "base" for value in model_variants)
                else ", ".join(model_variants)
            )
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
                        model_applicability,
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
                        conveyor_height_in, platform_height_in, pit_depth_in,
                        model_applicability, status, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '', '', ?, '', ?, NULL, NULL, NULL, ?, 'Draft', ?)""",
                    (
                        process_id, project_id, scenario_id, next_sequence, station,
                        str(row["description"]), f"Yamazumi area: {row['area_name']}",
                        float(row["time_s"] or 0),
                        "CTQ" if "CTQ" in json.loads(row["flags"] or "[]") else "",
                        station,
                        model_applicability,
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


def part_scenario_activity(project_id: str, scenario_id: str) -> dict[str, bool]:
    """Return explicit per-scenario part activity; missing rows default to active."""
    rows = query(
        """SELECT activity.part_id, activity.active
           FROM part_scenario_activity activity
           JOIN planning_scenarios scenario ON scenario.id=activity.scenario_id
           JOIN parts part ON part.id=activity.part_id
           WHERE activity.project_id=? AND activity.scenario_id=?
             AND scenario.project_id=? AND part.project_id=?""",
        (project_id, scenario_id, project_id, project_id),
    )
    return {str(row["part_id"]): bool(row["active"]) for row in rows}


def active_part_ids(project_id: str, scenario_id: str) -> set[str]:
    """Return project part IDs active in a scenario, defaulting new/unmapped parts to active."""
    rows = query(
        """SELECT part.id
           FROM parts part
           JOIN planning_scenarios scenario
             ON scenario.id=? AND scenario.project_id=part.project_id
           LEFT JOIN part_scenario_activity activity
             ON activity.project_id=part.project_id
            AND activity.scenario_id=scenario.id AND activity.part_id=part.id
           WHERE part.project_id=? AND COALESCE(activity.active, 1)=1""",
        (scenario_id, project_id),
    )
    return {str(row["id"]) for row in rows}


def update_part_scenario_activity(
    project_id: str, scenario_id: str, activity_by_part: dict[str, bool]
) -> str:
    """Persist scenario-specific Active flags for project parts atomically."""
    normalized_activity = {
        str(part_id): bool(active) for part_id, active in activity_by_part.items()
    }
    selected_ids = list(normalized_activity)
    timestamp = now_iso()
    with connection() as conn:
        scenario = conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone()
        if not scenario:
            raise ValueError("The active planning scenario no longer exists.")
        if selected_ids:
            placeholders = ",".join("?" for _ in selected_ids)
            valid_ids = {
                str(row[0]) for row in conn.execute(
                    f"SELECT id FROM parts WHERE project_id=? AND id IN ({placeholders})",
                    (project_id, *selected_ids),
                ).fetchall()
            }
            if valid_ids != set(selected_ids):
                raise ValueError("One or more parts no longer belong to this project.")
        for part_id in selected_ids:
            conn.execute(
                """INSERT INTO part_scenario_activity
                   (project_id, scenario_id, part_id, active, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(scenario_id, part_id) DO UPDATE SET
                     active=excluded.active, updated_at=excluded.updated_at""",
                (
                    project_id,
                    scenario_id,
                    part_id,
                    1 if normalized_activity[part_id] else 0,
                    timestamp,
                ),
            )
    return timestamp


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
         quantity, str(values.get("revision") or "0").strip() or "0", values.get("source", "Manual"),
         values.get("image_path", ""), normalize_model_applicability(values.get("model_applicability", "All")),
         values.get("notes", "").strip(), timestamp),
    )
    rows = query("SELECT id FROM parts WHERE project_id = ? AND part_number = ?", (project_id, values["part_number"].strip()))
    return rows[0]["id"]


def update_part_rows(
    project_id: str,
    edited: pd.DataFrame,
    *,
    scenario_id: str | None = None,
    activity_by_part: dict[str, bool] | None = None,
) -> int:
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
        if scenario_id and not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
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
            revision = clean_text(row.get("revision"))
            if part_id not in existing_ids and not revision:
                revision = "0"
            values = (
                str(row["part_number"]).strip(), clean_text(row.get("description")), quantity,
                revision, normalize_model_applicability(row.get("model_applicability")),
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
        if scenario_id and activity_by_part is not None:
            normalized_activity = {
                str(part_id): bool(active)
                for part_id, active in activity_by_part.items()
            }
            saved_ids = set(edited["id"].fillna("").astype(str))
            if set(normalized_activity) != saved_ids:
                raise ValueError("Part activity must be supplied for every saved row.")
            for part_id, active in normalized_activity.items():
                conn.execute(
                    """INSERT INTO part_scenario_activity
                       (project_id, scenario_id, part_id, active, updated_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(scenario_id, part_id) DO UPDATE SET
                         active=excluded.active, updated_at=excluded.updated_at""",
                    (project_id, scenario_id, part_id, 1 if active else 0, timestamp),
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




def _assembly_section_delete_rows(
    conn: sqlite3.Connection, project_id: str, section_ids: list[str]
) -> list[sqlite3.Row]:
    normalized_ids = list(dict.fromkeys(
        str(section_id).strip() for section_id in section_ids if str(section_id).strip()
    ))
    if not normalized_ids:
        raise ValueError("Select at least one Fishbone section to delete.")
    placeholders = ", ".join("?" for _ in normalized_ids)
    selected_count = conn.execute(
        f"""SELECT COUNT(*) FROM assembly_sections
            WHERE project_id=? AND id IN ({placeholders})""",
        (project_id, *normalized_ids),
    ).fetchone()[0]
    if int(selected_count) != len(normalized_ids):
        raise ValueError("One or more selected Fishbone sections no longer exist.")
    return conn.execute(
        f"""WITH RECURSIVE affected(id, name, parent_id, depth) AS (
                SELECT id, name, parent_id, 0 FROM assembly_sections
                WHERE project_id=? AND id IN ({placeholders})
                UNION
                SELECT child.id, child.name, child.parent_id, affected.depth + 1
                FROM assembly_sections child
                JOIN affected ON child.parent_id=affected.id
                WHERE child.project_id=?
            )
            SELECT id, name, MAX(depth) AS depth FROM affected
            GROUP BY id, name ORDER BY depth, name""",
        (project_id, *normalized_ids, project_id),
    ).fetchall()


def _assembly_section_target_validation(
    conn: sqlite3.Connection,
    project_id: str,
    affected_ids: list[str],
    target_section_id: str,
    active_scenario_id: str | None = None,
) -> dict:
    target_id = _catalog_text(target_section_id)
    if not target_id:
        raise ValueError("Choose an existing Fishbone section to continue this work under.")
    if target_id in affected_ids:
        raise ValueError("The target Fishbone section must be outside the deletion set.")
    target = conn.execute(
        "SELECT id, name FROM assembly_sections WHERE id=? AND project_id=?",
        (target_id, project_id),
    ).fetchone()
    if not target:
        raise ValueError("Choose an existing Fishbone section from this project.")
    active_scenario = _catalog_text(active_scenario_id) or None
    if active_scenario and not conn.execute(
        "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
        (active_scenario, project_id),
    ).fetchone():
        raise ValueError("The active planning scenario no longer exists in this project.")

    placeholders = ", ".join("?" for _ in affected_ids)
    source_counts = {
        str(row["scenario_id"]): int(row["area_count"])
        for row in conn.execute(
            f"""SELECT scenario_id, COUNT(*) AS area_count
                FROM yamazumi_areas
                WHERE project_id=? AND section_id IN ({placeholders})
                GROUP BY scenario_id""",
            (project_id, *affected_ids),
        ).fetchall()
    }
    target_counts = {
        str(row["scenario_id"]): int(row["area_count"])
        for row in conn.execute(
            """SELECT scenario_id, COUNT(*) AS area_count
               FROM yamazumi_areas
               WHERE project_id=? AND section_id=?
               GROUP BY scenario_id""",
            (project_id, target_id),
        ).fetchall()
    }
    conflicts: list[dict] = []
    for scenario_id, source_count in source_counts.items():
        target_count = target_counts.get(scenario_id, 0)
        if source_count + target_count <= 1:
            continue
        scenario = conn.execute(
            """SELECT name, revision_label FROM planning_scenarios
               WHERE id=? AND project_id=?""",
            (scenario_id, project_id),
        ).fetchone()
        conflicts.append(
            {
                "scenario_id": scenario_id,
                "scenario_name": str(scenario["name"]) if scenario else "Unknown scenario",
                "revision_label": str(scenario["revision_label"]) if scenario else "",
                "source_area_count": source_count,
                "target_area_count": target_count,
            }
        )
    conflicts.sort(
        key=lambda row: (
            str(row["scenario_id"]) != str(active_scenario or ""),
            str(row["revision_label"]),
            str(row["scenario_name"]),
        )
    )
    category_conflicts: list[dict] = []
    incoming_categories = [
        dict(row)
        for row in conn.execute(
            f"""SELECT id, ebom_name, display_name
                FROM assembly_grid_categories
                WHERE project_id=? AND section_id IN ({placeholders})
                ORDER BY sequence, display_name""",
            (project_id, *affected_ids),
        ).fetchall()
    ]
    target_categories = [
        dict(row)
        for row in conn.execute(
            """SELECT id, ebom_name, display_name
               FROM assembly_grid_categories
               WHERE project_id=? AND section_id=?
               ORDER BY sequence, display_name""",
            (project_id, target_id),
        ).fetchall()
    ]
    for field, label in (
        ("ebom_name", "Official EBOM category name"),
        ("display_name", "Display name"),
    ):
        combined: list[tuple[dict, bool]] = [
            *((row, False) for row in target_categories),
            *((row, True) for row in incoming_categories),
        ]
        seen_values: dict[str, tuple[dict, bool]] = {}
        for category, is_incoming in combined:
            value = _catalog_text(category.get(field))
            key = value.casefold()
            previous = seen_values.get(key)
            if previous and (is_incoming or previous[1]):
                incoming = category if is_incoming else previous[0]
                conflicting = previous[0] if is_incoming else category
                category_conflicts.append(
                    {
                        "type": "category",
                        "field": field,
                        "field_label": label,
                        "value": value,
                        "incoming_category_id": str(incoming["id"]),
                        "incoming_category_name": str(incoming["display_name"]),
                        "conflicting_category_id": str(conflicting["id"]),
                        "conflicting_category_name": str(conflicting["display_name"]),
                    }
                )
                continue
            seen_values[key] = (category, is_incoming)
    message = ""
    if conflicts:
        first = conflicts[0]
        if int(first["target_area_count"]) > 0:
            message = (
                "The selected target section already has its own Yamazumi area. "
                "Choose a different target, or reconcile the duplicate manually in "
                "Yamazumi before deleting."
            )
        else:
            message = (
                "More than one Yamazumi area would be re-pointed to the selected target "
                "section. Choose a different target, or reconcile the duplicate manually "
                "in Yamazumi before deleting."
            )
        if str(first["scenario_id"]) != str(active_scenario or ""):
            message += (
                f" Conflict found in Rev {first['revision_label']} · "
                f"{first['scenario_name']}."
            )
    elif category_conflicts:
        first = category_conflicts[0]
        message = (
            f"Cannot continue under Fishbone section {target['name']}: incoming category "
            f"{first['incoming_category_name']} has {first['field_label']} "
            f"\"{first['value']}\" that conflicts with category "
            f"{first['conflicting_category_name']}. Choose a different target Fishbone section."
        )
    return {
        "valid": not conflicts and not category_conflicts,
        "message": message,
        "target_section_id": target_id,
        "target_section_name": str(target["name"]),
        "conflicts": [*conflicts, *category_conflicts],
        "category_conflicts": category_conflicts,
    }


def assembly_section_delete_target_validation(
    project_id: str,
    section_ids: list[str],
    target_section_id: str,
    active_scenario_id: str | None = None,
) -> dict:
    """Validate one shared continuity target without changing persisted records."""
    with connection() as conn:
        section_rows = _assembly_section_delete_rows(conn, project_id, section_ids)
        affected_ids = [str(row["id"]) for row in section_rows]
        return _assembly_section_target_validation(
            conn, project_id, affected_ids, target_section_id, active_scenario_id
        )


def assembly_section_delete_impact(
    project_id: str, section_ids: list[str]
) -> dict:
    """Describe the complete, approved effect of deleting Fishbone sections."""
    normalized_ids = list(dict.fromkeys(
        str(section_id).strip() for section_id in section_ids if str(section_id).strip()
    ))
    with connection() as conn:
        section_rows = _assembly_section_delete_rows(conn, project_id, normalized_ids)
        affected_ids = [str(row["id"]) for row in section_rows]
        affected_placeholders = ", ".join("?" for _ in affected_ids)

        def count_rows(table: str) -> int:
            return int(conn.execute(
                f"""SELECT COUNT(*) FROM {table}
                    WHERE project_id=? AND section_id IN ({affected_placeholders})""",
                (project_id, *affected_ids),
            ).fetchone()[0])

        assembly_impact = assembly_section_reference_impact(
            project_id, affected_ids, connection=conn
        )
        assembly_references = assembly_impact.to_dict("records")
        assembly_component_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM manufacturing_assembly_components component
                JOIN fishbone_part_assignments assignment
                  ON assignment.id=component.fishbone_assignment_id
                WHERE component.project_id=?
                  AND assignment.section_id IN ({affected_placeholders})""",
            (project_id, *affected_ids),
        ).fetchone()[0])

        yamazumi_area_count = count_rows("yamazumi_areas")
        process_link_count = count_rows("process_part_groups")
        category_references = [
            dict(row)
            for row in conn.execute(
                f"""SELECT id AS category_id, ebom_name, display_name,
                           section_id, installed_section_id
                    FROM assembly_grid_categories
                    WHERE project_id=? AND (
                        section_id IN ({affected_placeholders}) OR
                        installed_section_id IN ({affected_placeholders})
                    )
                    ORDER BY sequence, display_name""",
                (project_id, *affected_ids, *affected_ids),
            ).fetchall()
        ]
        category_built_reference_count = sum(
            int(str(row.get("section_id")) in affected_ids)
            for row in category_references
        )
        category_installed_reference_count = sum(
            int(str(row.get("installed_section_id")) in affected_ids)
            for row in category_references
        )
        feature_visibility_preference_count = count_rows(
            "assembly_grid_feature_visibility"
        )
        assembly_reference_count = sum(
            int(str(row.get("built_section_id")) in affected_ids)
            + int(str(row.get("installed_section_id")) in affected_ids)
            for row in assembly_references
        )
        return {
            "selected_section_count": len(normalized_ids),
            "affected_section_count": len(affected_ids),
            "descendant_section_count": len(affected_ids) - len(normalized_ids),
            "section_ids": affected_ids,
            "section_names": [str(row["name"]) for row in section_rows],
            "fishbone_use_count": count_rows("fishbone_part_assignments"),
            "yamazumi_area_count": yamazumi_area_count,
            "process_link_count": process_link_count,
            "assembly_reference_count": assembly_reference_count,
            "assembly_references": assembly_references,
            "category_built_reference_count": category_built_reference_count,
            "category_installed_reference_count": category_installed_reference_count,
            "category_reference_count": (
                category_built_reference_count + category_installed_reference_count
            ),
            "category_references": category_references,
            "feature_visibility_preference_count": feature_visibility_preference_count,
            "assembly_component_count": assembly_component_count,
            "requires_repointing": bool(
                yamazumi_area_count
                or process_link_count
                or assembly_reference_count
                or category_built_reference_count
                or category_installed_reference_count
            ),
        }


def delete_assembly_sections(
    project_id: str,
    section_ids: list[str],
    target_section_id: str | None = None,
    active_scenario_id: str | None = None,
) -> dict:
    """Atomically re-point continuity references and delete Fishbone sections."""
    impact = assembly_section_delete_impact(project_id, section_ids)
    timestamp = now_iso()
    target_id = _catalog_text(target_section_id) or None
    target_validation = None
    yamazumi_repointed = 0
    process_repointed = 0
    category_built_repointed = 0
    category_installed_repointed = 0
    feature_visibility_deleted = 0
    assembly_replacements: list[dict] = []
    with connection() as conn:
        section_rows = _assembly_section_delete_rows(conn, project_id, section_ids)
        affected_ids = [str(row["id"]) for row in section_rows]
        placeholders = ", ".join("?" for _ in affected_ids)
        yamazumi_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM yamazumi_areas
                WHERE project_id=? AND section_id IN ({placeholders})""",
            (project_id, *affected_ids),
        ).fetchone()[0])
        process_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM process_part_groups
                WHERE project_id=? AND section_id IN ({placeholders})""",
            (project_id, *affected_ids),
        ).fetchone()[0])
        assembly_impact = assembly_section_reference_impact(
            project_id, affected_ids, connection=conn
        )
        assembly_rows = assembly_impact.to_dict("records")
        assembly_reference_count = sum(
            int(_catalog_text(row.get("built_section_id")) in affected_ids)
            + int(_catalog_text(row.get("installed_section_id")) in affected_ids)
            for row in assembly_rows
        )
        category_built_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM assembly_grid_categories
                WHERE project_id=? AND section_id IN ({placeholders})""",
            (project_id, *affected_ids),
        ).fetchone()[0])
        category_installed_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM assembly_grid_categories
                WHERE project_id=? AND installed_section_id IN ({placeholders})""",
            (project_id, *affected_ids),
        ).fetchone()[0])
        feature_visibility_deleted = int(conn.execute(
            f"""SELECT COUNT(*) FROM assembly_grid_feature_visibility
                WHERE project_id=? AND section_id IN ({placeholders})""",
            (project_id, *affected_ids),
        ).fetchone()[0])
        requires_repointing = bool(
            yamazumi_count
            or process_count
            or assembly_reference_count
            or category_built_count
            or category_installed_count
        )
        if requires_repointing:
            target_validation = _assembly_section_target_validation(
                conn, project_id, affected_ids, target_id or "", active_scenario_id
            )
            if not target_validation["valid"]:
                raise ValueError(str(target_validation["message"]))
            yamazumi_repointed = conn.execute(
                f"""UPDATE yamazumi_areas SET section_id=?, updated_at=?
                    WHERE project_id=? AND section_id IN ({placeholders})""",
                (target_id, timestamp, project_id, *affected_ids),
            ).rowcount
            process_repointed = conn.execute(
                f"""UPDATE process_part_groups SET section_id=?, updated_at=?
                    WHERE project_id=? AND section_id IN ({placeholders})""",
                (target_id, timestamp, project_id, *affected_ids),
            ).rowcount
            category_built_repointed = conn.execute(
                f"""UPDATE assembly_grid_categories
                    SET section_id=?, updated_at=?
                    WHERE project_id=? AND section_id IN ({placeholders})""",
                (target_id, timestamp, project_id, *affected_ids),
            ).rowcount
            category_installed_repointed = conn.execute(
                f"""UPDATE assembly_grid_categories
                    SET installed_section_id=?, updated_at=?
                    WHERE project_id=? AND installed_section_id IN ({placeholders})""",
                (target_id, timestamp, project_id, *affected_ids),
            ).rowcount
            for row in assembly_rows:
                if _catalog_text(row.get("built_section_id")) in affected_ids:
                    assembly_replacements.append(
                        {
                            "assembly_id": str(row["assembly_id"]),
                            "field": "built_section_id",
                            "section_id": target_id,
                        }
                    )
                if _catalog_text(row.get("installed_section_id")) in affected_ids:
                    assembly_replacements.append(
                        {
                            "assembly_id": str(row["assembly_id"]),
                            "field": "installed_section_id",
                            "section_id": target_id,
                        }
                    )
        elif target_id:
            _assembly_section_target_validation(
                conn, project_id, affected_ids, target_id, active_scenario_id
            )
        if assembly_replacements:
            repoint_assembly_section_references(
                project_id, assembly_replacements, connection=conn
            )
        conn.execute(
            f"DELETE FROM fishbone_part_assignments WHERE project_id=? AND section_id IN ({placeholders})",
            (project_id, *affected_ids),
        )
        conn.execute(
            f"DELETE FROM assembly_sections WHERE project_id=? AND id IN ({placeholders})",
            (project_id, *affected_ids),
        )
    return {
        **impact,
        "target_section_id": target_id,
        "target_section_name": (
            str(target_validation["target_section_name"]) if target_validation else ""
        ),
        "yamazumi_repointed_count": int(yamazumi_repointed),
        "process_repointed_count": int(process_repointed),
        "assembly_replacement_count": len(assembly_replacements),
        "category_built_repointed_count": int(category_built_repointed),
        "category_installed_repointed_count": int(category_installed_repointed),
        "feature_visibility_deleted_count": int(feature_visibility_deleted),
    }




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


def fishbone_part_assignments(
    project_id: str, scenario_id: str | None = None
) -> pd.DataFrame:
    activity_join = """
        LEFT JOIN part_scenario_activity activity
          ON activity.project_id=a.project_id AND activity.part_id=a.part_id
         AND activity.scenario_id=?
    """ if scenario_id else ""
    activity_clause = " AND COALESCE(activity.active, 1)=1" if scenario_id else ""
    params = (scenario_id, project_id) if scenario_id else (project_id,)
    return pd.DataFrame(query(
        f"""SELECT a.id, a.project_id, a.part_id, a.section_id, a.sequence, a.quantity,
                  a.use_description, a.notes,
                  a.updated_at, p.part_number, p.description, p.revision, p.model_applicability,
                  s.name AS section_name
           FROM fishbone_part_assignments a
           JOIN parts p ON p.id = a.part_id
           JOIN assembly_sections s ON s.id = a.section_id
           {activity_join}
           WHERE a.project_id = ?{activity_clause}
           ORDER BY s.sequence, a.sequence, p.part_number""",
        params,
    ))


def search_parts_and_fishbone(
    project_id: str, search_text: str, scenario_id: str | None = None
) -> pd.DataFrame:
    """Find catalog parts by number, description, or fishbone-use text across all sections."""
    columns = [
        "part_id",
        "part_number",
        "description",
        "revision",
        "model_applicability",
        "assignment_id",
        "section_id",
        "section_name",
        "quantity",
        "use_description",
        "assignment_notes",
    ]
    tokens = list(dict.fromkeys(str(search_text or "").casefold().split()))
    if not tokens:
        return pd.DataFrame({column: pd.Series(dtype="string") for column in columns})

    token_clauses: list[str] = []
    params: list = [scenario_id, project_id] if scenario_id else [project_id]
    for token in tokens:
        pattern = f"%{token}%"
        token_clauses.append(
            """(LOWER(p.part_number) LIKE ? OR LOWER(p.description) LIKE ?
                 OR LOWER(COALESCE(a.use_description, '')) LIKE ?
                 OR LOWER(COALESCE(s.name, '')) LIKE ?)"""
        )
        params.extend([pattern, pattern, pattern, pattern])
    params.append(100)
    activity_join = """
            LEFT JOIN part_scenario_activity activity
              ON activity.project_id=p.project_id AND activity.part_id=p.id
             AND activity.scenario_id=?
    """ if scenario_id else ""
    activity_clause = " AND COALESCE(activity.active, 1)=1" if scenario_id else ""
    rows = query(
        f"""SELECT p.id AS part_id, p.part_number, p.description, p.revision,
                   p.model_applicability, a.id AS assignment_id, a.section_id,
                   s.name AS section_name, a.quantity, a.use_description,
                   a.notes AS assignment_notes
            FROM parts p
            LEFT JOIN fishbone_part_assignments a
              ON a.part_id=p.id AND a.project_id=p.project_id
            LEFT JOIN assembly_sections s ON s.id=a.section_id
            {activity_join}
            WHERE p.project_id=? AND ({' OR '.join(token_clauses)}){activity_clause}
            ORDER BY p.part_number, s.sequence, a.sequence
            LIMIT ?""",
        tuple(params),
    )
    return pd.DataFrame(rows, columns=columns)


def create_part_and_assign_to_section(
    project_id: str,
    section_id: str,
    values: dict,
    placement_quantity: float,
    use_description: str = "",
    placement_notes: str = "",
) -> tuple[str, str, str]:
    """Create one catalog part and its first fishbone use in one transaction."""
    part_number = str(values.get("part_number") or "").strip()
    description = str(values.get("description") or "").strip()
    revision = str(values.get("revision") or "0").strip() or "0"
    catalog_notes = str(values.get("notes") or "").strip()
    if not part_number:
        raise ValueError("Part number is required.")
    if not description:
        raise ValueError("Part Name is required.")
    try:
        numeric_quantity = float(placement_quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("Fishbone quantity must be a number greater than zero.") from exc
    if not math.isfinite(numeric_quantity) or numeric_quantity <= 0:
        raise ValueError("Fishbone quantity must be a number greater than zero.")
    quantity = numeric_quantity

    part_id = str(uuid4())
    assignment_id = str(uuid4())
    timestamp = now_iso()
    try:
        with connection() as conn:
            section = conn.execute(
                "SELECT id FROM assembly_sections WHERE id=? AND project_id=? AND active=1",
                (section_id, project_id),
            ).fetchone()
            if not section:
                raise ValueError("Choose an active fishbone section.")
            duplicate = conn.execute(
                """SELECT part_number FROM parts
                   WHERE project_id=? AND LOWER(TRIM(part_number))=LOWER(?)""",
                (project_id, part_number),
            ).fetchone()
            if duplicate:
                raise ValueError(
                    f"Part {duplicate['part_number']} already exists. Use Find existing instead."
                )
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, quantity, revision, source,
                    image_path, model_applicability, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'Manual', '', ?, ?, ?)""",
                (
                    part_id,
                    project_id,
                    part_number,
                    description,
                    quantity,
                    revision,
                    normalize_model_applicability(values.get("model_applicability", "All")),
                    catalog_notes,
                    timestamp,
                ),
            )
            next_sequence = conn.execute(
                """SELECT COALESCE(MAX(sequence), 0) + 10
                   FROM fishbone_part_assignments WHERE project_id=? AND section_id=?""",
                (project_id, section_id),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, part_id, section_id, sequence, quantity,
                    use_description, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    assignment_id,
                    project_id,
                    part_id,
                    section_id,
                    next_sequence,
                    quantity,
                    str(use_description or "").strip(),
                    str(placement_notes or "").strip(),
                    timestamp,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("That part number already exists in this project.") from exc
    return part_id, assignment_id, timestamp


def move_fishbone_part_assignment(
    project_id: str, assignment_id: str, section_id: str
) -> str:
    """Move one existing fishbone occurrence to the end of another active section."""
    timestamp = now_iso()
    with connection() as conn:
        assignment = conn.execute(
            """SELECT section_id, part_id FROM fishbone_part_assignments
               WHERE id=? AND project_id=?""",
            (assignment_id, project_id),
        ).fetchone()
        if not assignment:
            raise ValueError("The selected fishbone use no longer exists.")
        section = conn.execute(
            "SELECT id FROM assembly_sections WHERE id=? AND project_id=? AND active=1",
            (section_id, project_id),
        ).fetchone()
        if not section:
            raise ValueError("Choose an active fishbone section.")
        if str(assignment["section_id"]) == str(section_id):
            raise ValueError("That fishbone use is already in the selected section.")
        another_source_use = conn.execute(
            """SELECT 1 FROM fishbone_part_assignments
               WHERE project_id=? AND section_id=? AND part_id=? AND id<>? LIMIT 1""",
            (
                project_id,
                assignment["section_id"],
                assignment["part_id"],
                assignment_id,
            ),
        ).fetchone()
        paired_in_source = conn.execute(
            """SELECT 1 FROM process_part_groups group_row
               JOIN process_part_options option_row ON option_row.group_id=group_row.id
               WHERE group_row.project_id=? AND group_row.section_id=?
                 AND option_row.part_id=? LIMIT 1""",
            (project_id, assignment["section_id"], assignment["part_id"]),
        ).fetchone()
        if paired_in_source and not another_source_use:
            raise ValueError(
                "This fishbone use is already paired to Process at a Glance work in its current "
                "section. Remove or update that pairing before moving it."
            )
        next_sequence = conn.execute(
            """SELECT COALESCE(MAX(sequence), 0) + 10
               FROM fishbone_part_assignments WHERE project_id=? AND section_id=?""",
            (project_id, section_id),
        ).fetchone()[0]
        conn.execute(
            """UPDATE fishbone_part_assignments
               SET section_id=?, sequence=?, updated_at=?
               WHERE id=? AND project_id=?""",
            (section_id, next_sequence, timestamp, assignment_id, project_id),
        )
    return timestamp


def assign_parts_to_section(
    project_id: str,
    part_ids: list[str],
    section_id: str,
    use_description: str = "",
    *,
    allow_additional_use: bool = False,
    quantities_by_part: dict[str, float] | None = None,
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
            try:
                numeric_quantity = float(
                    requested_quantity if requested_quantity is not None else 1
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Fishbone quantities must be numbers greater than zero."
                ) from exc
            if not math.isfinite(numeric_quantity) or numeric_quantity <= 0:
                raise ValueError("Fishbone quantities must be numbers greater than zero.")
            quantity = numeric_quantity
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


def delete_fishbone_part_assignments(project_id: str, assignment_ids: list[str]) -> int:
    """Delete selected fishbone uses atomically, leaving master Parts records untouched."""
    selected_ids = list(
        dict.fromkeys(str(assignment_id) for assignment_id in assignment_ids if str(assignment_id))
    )
    if not selected_ids:
        return 0
    placeholders = ",".join("?" for _ in selected_ids)
    with connection() as conn:
        found = conn.execute(
            f"""SELECT COUNT(*) FROM fishbone_part_assignments
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *selected_ids),
        ).fetchone()[0]
        if found != len(selected_ids):
            raise ValueError("One or more selected fishbone uses no longer exist.")
        cursor = conn.execute(
            f"""DELETE FROM fishbone_part_assignments
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *selected_ids),
        )
        return int(cursor.rowcount)


def delete_fishbone_part_assignment(project_id: str, assignment_id: str) -> bool:
    """Delete one fishbone use while leaving its master Parts record untouched."""
    return delete_fishbone_part_assignments(project_id, [assignment_id]) == 1


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
            try:
                quantity = float(row.get("quantity"))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Fishbone quantities must be numbers greater than zero."
                ) from exc
            if not math.isfinite(quantity) or quantity <= 0:
                raise ValueError("Fishbone quantities must be numbers greater than zero.")
            records.append((
                str(row.get("id") or uuid4()), project_id, part_id, section_id,
                int(row.get("sequence") or 0), quantity,
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


def complexity_feature_delete_impacts(
    project_id: str, feature_ids: list[str]
) -> pd.DataFrame:
    """Return dependency counts used to explain a proposed feature deletion."""
    normalized_ids = list(
        dict.fromkeys(
            str(feature_id).strip()
            for feature_id in feature_ids
            if str(feature_id).strip()
        )
    )
    columns = [
        "id", "category", "name", "model_value_count", "part_rule_count",
        "affected_part_count",
    ]
    if not normalized_ids:
        return pd.DataFrame(
            {
                "id": pd.Series(dtype="string"),
                "category": pd.Series(dtype="string"),
                "name": pd.Series(dtype="string"),
                "model_value_count": pd.Series(dtype="int64"),
                "part_rule_count": pd.Series(dtype="int64"),
                "affected_part_count": pd.Series(dtype="int64"),
            }
        )
    placeholders = ", ".join("?" for _ in normalized_ids)
    return pd.DataFrame(
        query(
            f"""SELECT f.id, f.category, f.name,
                       (SELECT COUNT(*) FROM model_feature_values value
                        WHERE value.project_id=f.project_id AND value.feature_id=f.id)
                           AS model_value_count,
                       (SELECT COUNT(*) FROM part_feature_rules rule
                        WHERE rule.project_id=f.project_id AND rule.feature_id=f.id)
                           AS part_rule_count,
                       (SELECT COUNT(DISTINCT rule.part_id) FROM part_feature_rules rule
                        WHERE rule.project_id=f.project_id AND rule.feature_id=f.id)
                           AS affected_part_count
                FROM complexity_features f
                WHERE f.project_id=? AND f.id IN ({placeholders})
                ORDER BY f.sequence, f.category, f.name""",
            (project_id, *normalized_ids),
        ),
        columns=columns,
    )


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


def potential_duplicate_models(project_id: str, edited: pd.DataFrame) -> list[dict]:
    """Return active-model pairs whose mutually assigned feature values all match."""
    if "model_id" not in edited.columns:
        raise ValueError("The complexity tree is missing model identifiers.")

    features = complexity_features(project_id)
    active_features = (
        features.loc[features["active"].fillna(1).astype(bool)]
        if not features.empty
        else features
    )
    allowed_by_id = {
        str(row["id"]): {str(value) for value in json.loads(row["allowed_values"] or "[]")}
        for _, row in active_features.iterrows()
    }
    models = project_models(project_id)
    if models.empty:
        return []
    model_by_id = {str(row["id"]): row for _, row in models.iterrows()}
    active_model_ids = {
        str(row["id"])
        for _, row in models.loc[models["active"].fillna(1).astype(bool)].iterrows()
    }

    candidates: list[dict] = []
    seen_model_ids: set[str] = set()
    for _, row in edited.iterrows():
        model_id = _catalog_text(row.get("model_id"))
        if model_id not in model_by_id or model_id in seen_model_ids:
            continue
        seen_model_ids.add(model_id)
        values: dict[str, str] = {}
        for feature_id, choices in allowed_by_id.items():
            value = _catalog_text(row.get(feature_id))
            if value and value not in choices:
                raise ValueError("Choose only values defined in Feature definitions.")
            if value:
                values[feature_id] = value
        if model_id not in active_model_ids:
            continue
        model = model_by_id[model_id]
        candidates.append(
            {
                "model_id": model_id,
                "common_name": _catalog_text(model.get("display_name")),
                "official_model_number": _catalog_text(model.get("model_number")),
                "values": values,
            }
        )

    conflicts: list[dict] = []
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index + 1 :]:
            mutual_feature_ids = set(left["values"]) & set(right["values"])
            if not mutual_feature_ids:
                continue
            if all(
                left["values"][feature_id] == right["values"][feature_id]
                for feature_id in mutual_feature_ids
            ):
                conflicts.append(
                    {
                        "left_model_id": left["model_id"],
                        "left_common_name": left["common_name"],
                        "left_official_model_number": left["official_model_number"],
                        "right_model_id": right["model_id"],
                        "right_common_name": right["common_name"],
                        "right_official_model_number": right["official_model_number"],
                        "mutual_feature_count": len(mutual_feature_ids),
                    }
                )
    return conflicts


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
            "assembly_grid_model_mappings": [dict(row) for row in conn.execute(
                "SELECT * FROM assembly_grid_model_mappings WHERE project_id=?", (project_id,)
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
        conn.execute(
            "DELETE FROM assembly_grid_model_mappings WHERE project_id=?", (project_id,)
        )
        conn.execute("DELETE FROM project_models WHERE project_id=?", (project_id,))
        _insert_snapshot_rows(conn, "project_models", snapshot.get("models", []))
        _insert_snapshot_rows(
            conn,
            "assembly_grid_model_mappings",
            snapshot.get("assembly_grid_model_mappings", []),
        )
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
    """Capture the framework and every section-linked record needed for saved-state Undo."""
    with connection() as conn:
        return {
            "sections": [dict(row) for row in conn.execute(
                "SELECT * FROM assembly_sections WHERE project_id=?", (project_id,)
            ).fetchall()],
            "assignments": [dict(row) for row in conn.execute(
                "SELECT * FROM fishbone_part_assignments WHERE project_id=?", (project_id,)
            ).fetchall()],
            "assembly_components": [dict(row) for row in conn.execute(
                "SELECT * FROM manufacturing_assembly_components WHERE project_id=?",
                (project_id,),
            ).fetchall()],
            "yamazumi_section_references": [dict(row) for row in conn.execute(
                "SELECT id, section_id FROM yamazumi_areas WHERE project_id=?",
                (project_id,),
            ).fetchall()],
            "process_section_references": [dict(row) for row in conn.execute(
                "SELECT id, section_id FROM process_part_groups WHERE project_id=?",
                (project_id,),
            ).fetchall()],
            "assembly_section_references": [dict(row) for row in conn.execute(
                """SELECT id, built_section_id, installed_section_id, updated_at
                   FROM manufacturing_assemblies WHERE project_id=?""",
                (project_id,),
            ).fetchall()],
            "assembly_grid_categories": [dict(row) for row in conn.execute(
                "SELECT * FROM assembly_grid_categories WHERE project_id=?",
                (project_id,),
            ).fetchall()],
            "assembly_grid_model_mappings": [dict(row) for row in conn.execute(
                "SELECT * FROM assembly_grid_model_mappings WHERE project_id=?",
                (project_id,),
            ).fetchall()],
            "assembly_grid_feature_visibility": [dict(row) for row in conn.execute(
                "SELECT * FROM assembly_grid_feature_visibility WHERE project_id=?",
                (project_id,),
            ).fetchall()],
        }


def fishbone_assignment_snapshot(project_id: str) -> list[dict]:
    """Capture assigned part uses without changing the assembly framework."""
    with connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM fishbone_part_assignments WHERE project_id=?", (project_id,)
        ).fetchall()]


def restore_fishbone_plan_snapshot(project_id: str, snapshot: dict) -> None:
    """Restore a framework snapshot and its section-linked records atomically."""
    sections = snapshot.get("sections", [])
    assignments = snapshot.get("assignments", [])
    assembly_components = snapshot.get("assembly_components", [])
    grid_categories = snapshot.get("assembly_grid_categories", [])
    grid_mappings = snapshot.get("assembly_grid_model_mappings", [])
    grid_feature_visibility = snapshot.get(
        "assembly_grid_feature_visibility", []
    )
    with connection() as conn:
        # The framework is rebuilt as one unit. Temporarily release every section
        # reference so RESTRICT relationships cannot leave a partial restore.
        conn.execute(
            "UPDATE yamazumi_areas SET section_id=NULL WHERE project_id=?", (project_id,)
        )
        conn.execute(
            "UPDATE process_part_groups SET section_id=NULL WHERE project_id=?", (project_id,)
        )
        conn.execute(
            """UPDATE manufacturing_assemblies
               SET built_section_id=NULL, installed_section_id=NULL
               WHERE project_id=?""",
            (project_id,),
        )
        # Category section references are RESTRICT relationships. Remove the
        # project-owned grid state before rebuilding the framework, then restore
        # the same stable category, mapping, and preference IDs afterward.
        conn.execute(
            "DELETE FROM assembly_grid_model_mappings WHERE project_id=?", (project_id,)
        )
        conn.execute(
            "DELETE FROM assembly_grid_categories WHERE project_id=?", (project_id,)
        )
        conn.execute(
            "DELETE FROM assembly_grid_feature_visibility WHERE project_id=?",
            (project_id,),
        )
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
        _insert_snapshot_rows(conn, "manufacturing_assembly_components", assembly_components)
        _insert_snapshot_rows(conn, "assembly_grid_categories", grid_categories)
        _insert_snapshot_rows(conn, "assembly_grid_model_mappings", grid_mappings)
        _insert_snapshot_rows(
            conn, "assembly_grid_feature_visibility", grid_feature_visibility
        )
        for row in snapshot.get("yamazumi_section_references", []):
            conn.execute(
                "UPDATE yamazumi_areas SET section_id=? WHERE id=? AND project_id=?",
                (row.get("section_id"), row.get("id"), project_id),
            )
        for row in snapshot.get("process_section_references", []):
            conn.execute(
                "UPDATE process_part_groups SET section_id=? WHERE id=? AND project_id=?",
                (row.get("section_id"), row.get("id"), project_id),
            )
        for row in snapshot.get("assembly_section_references", []):
            conn.execute(
                """UPDATE manufacturing_assemblies
                   SET built_section_id=?, installed_section_id=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (
                    row.get("built_section_id"),
                    row.get("installed_section_id"),
                    row.get("updated_at"),
                    row.get("id"),
                    project_id,
                ),
            )


def restore_fishbone_assignment_snapshot(project_id: str, snapshot: list[dict]) -> None:
    """Restore the last set of fishbone part uses."""
    with connection() as conn:
        conn.execute("DELETE FROM fishbone_part_assignments WHERE project_id=?", (project_id,))
        _insert_snapshot_rows(conn, "fishbone_part_assignments", snapshot)


def delete_project_models(project_id: str, model_ids: list[str]) -> list[str]:
    """Delete selected unreferenced models only after validating the complete selection."""
    selected_ids = list(dict.fromkeys(str(model_id) for model_id in model_ids if str(model_id)))
    if not selected_ids:
        return []
    placeholders = ",".join("?" for _ in selected_ids)
    with connection() as conn:
        models = conn.execute(
            f"""SELECT id, model_number, display_name FROM project_models
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *selected_ids),
        ).fetchall()
        if len(models) != len(selected_ids):
            raise ValueError("One or more selected models no longer exist.")
        blocked: list[str] = []
        labels: list[str] = []
        for model in models:
            model_number = str(model["model_number"])
            label = str(model["display_name"] or model_number)
            labels.append(label)
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
                blocked.append(label)
        if blocked:
            raise ValueError(
                f"These models are still assigned elsewhere: {', '.join(sorted(blocked))}. "
                "Remove those assignments first, or turn off Use in planning instead."
            )
        conn.execute(
            f"DELETE FROM project_models WHERE project_id=? AND id IN ({placeholders})",
            (project_id, *selected_ids),
        )
        return labels


def delete_project_model(project_id: str, model_id: str) -> str:
    """Delete one unreferenced model definition."""
    return delete_project_models(project_id, [model_id])[0]


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


def process_section_for_step(
    project_id: str, scenario_id: str, element_id: str
) -> dict | None:
    """Return the one Fishbone section linked to a Process step, if unambiguous."""
    rows = query(
        """SELECT DISTINCT section.id, section.name
           FROM assembly_sections section
           JOIN (
               SELECT area.section_id
               FROM yamazumi_elements yamazumi
               JOIN yamazumi_areas area ON area.id=yamazumi.area_id
               WHERE yamazumi.project_id=? AND area.scenario_id=?
                 AND yamazumi.process_element_id=? AND area.section_id IS NOT NULL
               UNION
               SELECT group_row.section_id
               FROM process_part_groups group_row
               WHERE group_row.project_id=? AND group_row.scenario_id=?
                 AND group_row.work_element_id=? AND group_row.section_id IS NOT NULL
           ) linked ON linked.section_id=section.id
           WHERE section.project_id=?""",
        (
            project_id,
            scenario_id,
            element_id,
            project_id,
            scenario_id,
            element_id,
            project_id,
        ),
    )
    return rows[0] if len(rows) == 1 else None


def update_process_step_details(
    project_id: str,
    scenario_id: str,
    element_id: str,
    values: dict,
    apply_geometry_to_section: bool = False,
) -> tuple[str, int, str | None]:
    """Update one Process step and optionally copy its geometry across its section."""
    text_fields = [
        "description",
        "output_assembly_number",
        "output_assembly_name",
        "tool",
        "location",
        "unit_orientation",
    ]
    numeric_fields = {
        "conveyor_height_in": "Conveyor height",
    }
    cleaned = {
        field: "" if values.get(field) is None or pd.isna(values.get(field))
        else str(values.get(field)).strip()
        for field in text_fields
    }
    cleaned.update(
        {
            field: _optional_nonnegative_number(values.get(field), label)
            for field, label in numeric_fields.items()
        }
    )
    timestamp = now_iso()
    with connection() as conn:
        existing = conn.execute(
            """SELECT id FROM work_elements
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (element_id, project_id, scenario_id),
        ).fetchone()
        if not existing:
            raise ValueError("The selected process step no longer exists in this scenario.")

        section_id = None
        affected_ids = [element_id]
        if apply_geometry_to_section:
            linked_sections = conn.execute(
                """SELECT DISTINCT section_id FROM (
                       SELECT area.section_id
                       FROM yamazumi_elements yamazumi
                       JOIN yamazumi_areas area ON area.id=yamazumi.area_id
                       WHERE yamazumi.project_id=? AND area.scenario_id=?
                         AND yamazumi.process_element_id=? AND area.section_id IS NOT NULL
                       UNION
                       SELECT group_row.section_id
                       FROM process_part_groups group_row
                       WHERE group_row.project_id=? AND group_row.scenario_id=?
                         AND group_row.work_element_id=? AND group_row.section_id IS NOT NULL
                   )""",
                (
                    project_id,
                    scenario_id,
                    element_id,
                    project_id,
                    scenario_id,
                    element_id,
                ),
            ).fetchall()
            if len(linked_sections) != 1:
                raise ValueError(
                    "This process step is not tied to exactly one Fishbone section, so its "
                    "orientation and conveyor height cannot be applied section-wide."
                )
            section_id = str(linked_sections[0]["section_id"])
            affected_ids = [
                str(row["element_id"])
                for row in conn.execute(
                    """SELECT DISTINCT element_id FROM (
                           SELECT yamazumi.process_element_id AS element_id
                           FROM yamazumi_elements yamazumi
                           JOIN yamazumi_areas area ON area.id=yamazumi.area_id
                           JOIN work_elements work ON work.id=yamazumi.process_element_id
                           WHERE yamazumi.project_id=? AND area.scenario_id=?
                             AND area.section_id=? AND work.scenario_id=?
                           UNION
                           SELECT group_row.work_element_id AS element_id
                           FROM process_part_groups group_row
                           JOIN work_elements work ON work.id=group_row.work_element_id
                           WHERE group_row.project_id=? AND group_row.scenario_id=?
                             AND group_row.section_id=? AND work.scenario_id=?
                       ) WHERE element_id IS NOT NULL""",
                    (
                        project_id,
                        scenario_id,
                        section_id,
                        scenario_id,
                        project_id,
                        scenario_id,
                        section_id,
                        scenario_id,
                    ),
                ).fetchall()
            ]
            if element_id not in affected_ids:
                affected_ids.append(element_id)

        output_number = cleaned["output_assembly_number"]
        if output_number:
            duplicate = conn.execute(
                """SELECT id FROM work_elements
                   WHERE project_id=? AND scenario_id=? AND id<>?
                     AND LOWER(TRIM(output_assembly_number))=LOWER(?)""",
                (project_id, scenario_id, element_id, output_number),
            ).fetchone()
            if duplicate:
                raise ValueError(
                    "Each made-assembly output number can be completed only once in a scenario."
                )

        assignments = ", ".join(f"{field}=?" for field in cleaned)
        conn.execute(
            f"""UPDATE work_elements SET {assignments}, updated_at=?
                WHERE id=? AND project_id=? AND scenario_id=?""",
            (*cleaned.values(), timestamp, element_id, project_id, scenario_id),
        )
        if apply_geometry_to_section:
            placeholders = ",".join("?" for _ in affected_ids)
            conn.execute(
                f"""UPDATE work_elements
                    SET unit_orientation=?, conveyor_height_in=?, updated_at=?
                    WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
                (
                    cleaned["unit_orientation"],
                    cleaned["conveyor_height_in"],
                    timestamp,
                    project_id,
                    scenario_id,
                    *affected_ids,
                ),
            )
    return timestamp, len(affected_ids), section_id


def replace_work_elements(project_id: str, scenario_id: str, edited: pd.DataFrame) -> None:
    fields = ["sequence", "station", "operation", "description", "cycle_time_s", "part_number", "tool", "torque",
              "quality_requirement", "ergo_requirement", "location", "unit_orientation", "conveyor_height_in", "platform_height_in",
              "pit_depth_in", "model_applicability", "status", "output_assembly_number",
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
                value = None if field.endswith("_in") else (0 if field in {"sequence", "cycle_time_s"} else "")
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
