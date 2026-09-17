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

from utils.quality_store import (
    clone_quality_requirement_assignments,
    init_quality_schema,
)
from utils.pfmea_store import clone_pfmea_scenario, init_pfmea_schema
from utils.yamazumi_stack import UNASSIGNED_STACK_ID, build_stack_draft
from utils.time_units import display_to_seconds, normalize_time_unit
from utils.control_plan_store import clone_control_plan_scenario, init_control_plan_schema
from utils.yamazumi_naming import (
    format_yamazumi_pitch_address,
    normalize_yamazumi_line_code,
    parse_yamazumi_pitch_address,
    suggest_yamazumi_section_code,
    yamazumi_line_prefix,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "paag.db"

HANDLING_TYPES = ("Handle", "Consume")
YAMAZUMI_PITCH_TYPES = ("Pitch", "Waterspider", "Subassembly", "Kitter", "Repacker")
YAMAZUMI_FEEDER_PITCH_TYPES = ("Subassembly", "Kitter")
ERGONOMICS_REVIEW_STATUSES = (
    "Started",
    "Open",
    "Pending",
    "Validation",
    "Closed (admin)",
    "Closed (engineering)",
)
ERGONOMICS_RISK_CLASSIFICATIONS = (
    "Not yet assessed",
    "Favorable Red",
    "Favorable Green",
    "Red",
    "Green",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _drop_yamazumi_flags_schema(conn: sqlite3.Connection) -> None:
    """Retire legacy Yamazumi flags without disturbing work-element identities."""
    element_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(yamazumi_elements)").fetchall()
    }
    if "flags" in element_columns:
        conn.execute("ALTER TABLE yamazumi_elements DROP COLUMN flags")
    conn.execute("DROP TABLE IF EXISTS yamazumi_flag_definitions")


def _upgrade_ergonomics_reviews_work_element_link(
    conn: sqlite3.Connection,
) -> None:
    """Make the Process-step link nullable with content-preserving deletion."""
    columns = {
        str(row[1]): row
        for row in conn.execute("PRAGMA table_info(ergonomics_reviews)").fetchall()
    }
    foreign_keys = {
        str(row[3]): row
        for row in conn.execute(
            "PRAGMA foreign_key_list(ergonomics_reviews)"
        ).fetchall()
    }
    work_column = columns.get("work_element_id")
    work_foreign_key = foreign_keys.get("work_element_id")
    if (
        work_column is not None
        and int(work_column[3]) == 0
        and work_foreign_key is not None
        and str(work_foreign_key[6]).upper() == "SET NULL"
    ):
        return

    risk_select = (
        "risk_classification"
        if "risk_classification" in columns
        else "'Not yet assessed'"
    )
    conn.executescript(
        f"""
        ALTER TABLE ergonomics_review_hazard_selections
            RENAME TO ergonomics_review_hazard_selections_legacy;
        ALTER TABLE ergonomics_reviews RENAME TO ergonomics_reviews_legacy;

        CREATE TABLE ergonomics_reviews (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            work_element_id TEXT REFERENCES work_elements(id) ON DELETE SET NULL,
            process_part_option_id TEXT
                REFERENCES process_part_options(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'Started'
                CHECK (status IN ('Started', 'Open', 'Pending', 'Validation',
                                  'Closed (admin)', 'Closed (engineering)')),
            risk_classification TEXT NOT NULL DEFAULT 'Not yet assessed'
                CHECK (risk_classification IN ('Not yet assessed',
                                               'Favorable Red', 'Favorable Green',
                                               'Red', 'Green')),
            reviewer TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            requested_due_date TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO ergonomics_reviews
            (id, project_id, scenario_id, work_element_id,
             process_part_option_id, status, reviewer, notes,
             requested_due_date, created_at, updated_at, risk_classification)
        SELECT id, project_id, scenario_id, work_element_id,
               process_part_option_id, status, reviewer, notes,
               requested_due_date, created_at, updated_at, {risk_select}
        FROM ergonomics_reviews_legacy;

        CREATE TABLE ergonomics_review_hazard_selections (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            ergonomics_review_id TEXT NOT NULL
                REFERENCES ergonomics_reviews(id) ON DELETE CASCADE,
            hazard_option_id TEXT NOT NULL
                REFERENCES ergonomic_hazard_options(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL DEFAULT 10,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(ergonomics_review_id, hazard_option_id)
        );
        INSERT INTO ergonomics_review_hazard_selections
            (id, project_id, scenario_id, ergonomics_review_id,
             hazard_option_id, sequence, created_at, updated_at)
        SELECT id, project_id, scenario_id, ergonomics_review_id,
               hazard_option_id, sequence, created_at, updated_at
        FROM ergonomics_review_hazard_selections_legacy;

        DROP TABLE ergonomics_review_hazard_selections_legacy;
        DROP TABLE ergonomics_reviews_legacy;
        CREATE INDEX idx_ergonomics_reviews_scenario
            ON ergonomics_reviews(project_id, scenario_id, work_element_id);
        CREATE INDEX idx_ergonomics_review_hazards
            ON ergonomics_review_hazard_selections(
                project_id, scenario_id, ergonomics_review_id, sequence
            );
        """
    )


def _upgrade_ergonomics_reviews_risk_classification(
    conn: sqlite3.Connection,
) -> None:
    """Add the controlled risk outcome and factually initialize legacy reviews."""
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(ergonomics_reviews)").fetchall()
    }
    if "risk_classification" in columns:
        return
    conn.execute(
        """ALTER TABLE ergonomics_reviews
           ADD COLUMN risk_classification TEXT NOT NULL DEFAULT 'Not yet assessed'
           CHECK (risk_classification IN ('Not yet assessed',
                                          'Favorable Red', 'Favorable Green',
                                          'Red', 'Green'))"""
    )
    conn.execute(
        """UPDATE ergonomics_reviews
           SET risk_classification='Not yet assessed'"""
    )


def _create_started_ergonomics_review(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    work_element_id: str,
    timestamp: str,
) -> str:
    """Create the required untouched Ergonomics placeholder for new Process work."""
    existing = conn.execute(
        """SELECT id FROM ergonomics_reviews
           WHERE project_id=? AND scenario_id=? AND work_element_id=?
           ORDER BY created_at, id LIMIT 1""",
        (project_id, scenario_id, work_element_id),
    ).fetchone()
    if existing:
        return str(existing["id"])
    review_id = str(uuid4())
    conn.execute(
        """INSERT INTO ergonomics_reviews
           (id, project_id, scenario_id, work_element_id, status,
            reviewer, notes, requested_due_date, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'Started', '', '', NULL, ?, ?)""",
        (
            review_id,
            project_id,
            scenario_id,
            work_element_id,
            timestamp,
            timestamp,
        ),
    )
    return review_id


def _create_work_element_with_started_ergonomics_review(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    values: dict,
    timestamp: str,
    *,
    work_element_id: str | None = None,
) -> str:
    """Atomically create one Process step and its baseline Ergonomics review."""
    if not scenario_id:
        raise ValueError("A planning scenario is required to create a Process step.")
    if not conn.execute(
        "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
        (scenario_id, project_id),
    ).fetchone():
        raise ValueError("The active planning scenario no longer exists.")
    protected_columns = {"id", "project_id", "scenario_id", "updated_at"}
    available_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(work_elements)").fetchall()
    }
    invalid_columns = set(values) - available_columns - protected_columns
    if invalid_columns:
        raise ValueError("The Process step contains unsupported stored fields.")
    payload = {
        key: value
        for key, value in values.items()
        if key in available_columns and key not in protected_columns
    }
    element_id = str(work_element_id or uuid4())
    columns = ["id", "project_id", "scenario_id", *payload, "updated_at"]
    conn.execute(
        f"INSERT INTO work_elements ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})",
        (
            element_id,
            project_id,
            scenario_id,
            *payload.values(),
            timestamp,
        ),
    )
    _create_started_ergonomics_review(
        conn,
        project_id,
        scenario_id,
        element_id,
        timestamp,
    )
    return element_id


def _backfill_missing_ergonomics_reviews(conn: sqlite3.Connection) -> int:
    """Create baseline reviews for historical Process steps that lack one."""
    timestamp = now_iso()
    missing = conn.execute(
        """SELECT work.id, work.project_id, work.scenario_id
           FROM work_elements work
           WHERE work.scenario_id IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1
                 FROM ergonomics_reviews review
                 WHERE review.project_id=work.project_id
                   AND review.scenario_id=work.scenario_id
                   AND review.work_element_id=work.id
             )
           ORDER BY work.project_id, work.scenario_id, work.sequence, work.id"""
    ).fetchall()
    for row in missing:
        _create_started_ergonomics_review(
            conn,
            str(row["project_id"]),
            str(row["scenario_id"]),
            str(row["id"]),
            timestamp,
        )
    return len(missing)


def _clone_ergonomics_reviews(
    conn: sqlite3.Connection,
    project_id: str,
    source_scenario_id: str,
    new_scenario_id: str,
    work_element_id_map: dict[str, str],
    process_part_option_id_map: dict[str, str],
    timestamp: str,
) -> int:
    """Clone every scenario review and replace generated Work Element placeholders."""
    source_reviews = conn.execute(
        """SELECT * FROM ergonomics_reviews
           WHERE project_id=? AND scenario_id=?
           ORDER BY created_at, id""",
        (project_id, source_scenario_id),
    ).fetchall()
    cloned_work_element_ids = {
        work_element_id_map[str(review["work_element_id"])]
        for review in source_reviews
        if review["work_element_id"] is not None
        and str(review["work_element_id"]) in work_element_id_map
    }
    for work_element_id in cloned_work_element_ids:
        # The new scenario cannot contain contributor-authored reviews yet. These
        # are the baseline rows created atomically with the cloned Process steps.
        conn.execute(
            """DELETE FROM ergonomics_reviews
               WHERE project_id=? AND scenario_id=? AND work_element_id=?""",
            (project_id, new_scenario_id, work_element_id),
        )

    for source_review in source_reviews:
        source_review_id = str(source_review["id"])
        source_work_element_id = source_review["work_element_id"]
        source_process_part_option_id = source_review["process_part_option_id"]
        cloned_review_id = str(uuid4())
        cloned_work_element_id = (
            work_element_id_map.get(str(source_work_element_id))
            if source_work_element_id is not None
            else None
        )
        cloned_process_part_option_id = (
            process_part_option_id_map.get(str(source_process_part_option_id))
            if source_process_part_option_id is not None
            else None
        )
        conn.execute(
            """INSERT INTO ergonomics_reviews
               (id, project_id, scenario_id, work_element_id,
                process_part_option_id, status, risk_classification, reviewer,
                notes, requested_due_date, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cloned_review_id,
                project_id,
                new_scenario_id,
                cloned_work_element_id,
                cloned_process_part_option_id,
                source_review["status"],
                source_review["risk_classification"],
                source_review["reviewer"],
                source_review["notes"],
                source_review["requested_due_date"],
                timestamp,
                timestamp,
            ),
        )
        for selection in conn.execute(
            """SELECT hazard_option_id, sequence
               FROM ergonomics_review_hazard_selections
               WHERE project_id=? AND scenario_id=? AND ergonomics_review_id=?
               ORDER BY sequence, id""",
            (project_id, source_scenario_id, source_review_id),
        ).fetchall():
            conn.execute(
                """INSERT INTO ergonomics_review_hazard_selections
                   (id, project_id, scenario_id, ergonomics_review_id,
                    hazard_option_id, sequence, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()),
                    project_id,
                    new_scenario_id,
                    cloned_review_id,
                    selection["hazard_option_id"],
                    selection["sequence"],
                    timestamp,
                    timestamp,
                ),
            )
    return len(source_reviews)


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
                yamazumi_line_code TEXT NOT NULL DEFAULT ''
                    CHECK(
                        yamazumi_line_code = '' OR (
                            length(yamazumi_line_code) = 2
                            AND yamazumi_line_code = upper(trim(yamazumi_line_code))
                            AND yamazumi_line_code NOT GLOB '*[^A-Z0-9]*'
                        )
                    ),
                owner TEXT DEFAULT '', revision TEXT DEFAULT 'A', status TEXT DEFAULT 'Draft',
                takt_time_s REAL DEFAULT 60,
                takt_time_unit TEXT NOT NULL DEFAULT 'seconds'
                    CHECK(takt_time_unit IN ('seconds', 'minutes', 'hours')),
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS planning_scenarios (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL, revision_label TEXT NOT NULL,
                revision_sequence INTEGER NOT NULL DEFAULT 1,
                parent_scenario_id TEXT REFERENCES planning_scenarios(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'Working', takt_time_s REAL NOT NULL DEFAULT 60,
                takt_time_unit TEXT NOT NULL DEFAULT 'seconds'
                    CHECK(takt_time_unit IN ('seconds', 'minutes', 'hours')),
                yamazumi_time_unit TEXT NOT NULL DEFAULT 'seconds'
                    CHECK(yamazumi_time_unit IN ('seconds', 'minutes', 'hours')),
                change_summary TEXT DEFAULT '', created_by TEXT DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(project_id, name), UNIQUE(project_id, revision_label)
            );
            CREATE TABLE IF NOT EXISTS parts (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                part_number TEXT NOT NULL, description TEXT DEFAULT '', quantity REAL DEFAULT 1,
                revision TEXT DEFAULT '0', source TEXT DEFAULT 'Manual', image_path TEXT DEFAULT '',
                model_applicability TEXT DEFAULT 'All', notes TEXT DEFAULT '', weight_lb REAL,
                updated_at TEXT NOT NULL,
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
                feeds_into_pitch_id TEXT REFERENCES yamazumi_pitches(id) ON DELETE RESTRICT,
                updated_at TEXT NOT NULL,
                UNIQUE(project_id, area_id, pitch_number)
            );
            CREATE TRIGGER IF NOT EXISTS trg_yamazumi_pitch_address_scenario_insert
            BEFORE INSERT ON yamazumi_pitches
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1
                FROM yamazumi_pitches existing
                JOIN yamazumi_areas existing_area ON existing_area.id=existing.area_id
                JOIN yamazumi_areas new_area ON new_area.id=NEW.area_id
                WHERE existing.id<>NEW.id
                  AND existing.project_id=NEW.project_id
                  AND existing_area.scenario_id IS new_area.scenario_id
                  AND TRIM(existing.pitch_number)=TRIM(NEW.pitch_number) COLLATE NOCASE
            )
            BEGIN
                SELECT RAISE(ABORT, 'Pitch address already exists in this planning scenario.');
            END;
            CREATE TRIGGER IF NOT EXISTS trg_yamazumi_pitch_address_scenario_update
            BEFORE UPDATE OF project_id, area_id, pitch_number ON yamazumi_pitches
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1
                FROM yamazumi_pitches existing
                JOIN yamazumi_areas existing_area ON existing_area.id=existing.area_id
                JOIN yamazumi_areas new_area ON new_area.id=NEW.area_id
                WHERE existing.id<>OLD.id
                  AND existing.project_id=NEW.project_id
                  AND existing_area.scenario_id IS new_area.scenario_id
                  AND TRIM(existing.pitch_number)=TRIM(NEW.pitch_number) COLLATE NOCASE
            )
            BEGIN
                SELECT RAISE(ABORT, 'Pitch address already exists in this planning scenario.');
            END;
            CREATE TABLE IF NOT EXISTS yamazumi_elements (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                area_id TEXT NOT NULL REFERENCES yamazumi_areas(id) ON DELETE CASCADE,
                pitch_id TEXT REFERENCES yamazumi_pitches(id) ON DELETE SET NULL,
                model_variant TEXT NOT NULL DEFAULT 'Base',
                model_variants TEXT NOT NULL DEFAULT '["Base"]', work_type TEXT DEFAULT 'Cycle',
                description TEXT NOT NULL, time_s REAL NOT NULL DEFAULT 0,
                work_region TEXT DEFAULT 'None', sequence INTEGER NOT NULL DEFAULT 10,
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
                catalog_part_id TEXT REFERENCES parts(id) ON DELETE RESTRICT,
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
                is_top_level INTEGER NOT NULL DEFAULT 0 CHECK(is_top_level IN (0, 1)),
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
                handling_type TEXT
                    CHECK (handling_type IS NULL OR handling_type IN ('Handle', 'Consume')),
                fishbone_assignment_id TEXT
                    REFERENCES fishbone_part_assignments(id),
                updated_at TEXT NOT NULL,
                UNIQUE(group_id, part_id)
            );
            CREATE TABLE IF NOT EXISTS ergonomic_hazard_options (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                label TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ergonomics_reviews (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
                work_element_id TEXT REFERENCES work_elements(id) ON DELETE SET NULL,
                process_part_option_id TEXT
                    REFERENCES process_part_options(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'Started'
                    CHECK (status IN ('Started', 'Open', 'Pending', 'Validation',
                                      'Closed (admin)', 'Closed (engineering)')),
                risk_classification TEXT NOT NULL DEFAULT 'Not yet assessed'
                    CHECK (risk_classification IN ('Not yet assessed',
                                                   'Favorable Red', 'Favorable Green',
                                                   'Red', 'Green')),
                reviewer TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                requested_due_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ergonomics_review_hazard_selections (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
                ergonomics_review_id TEXT NOT NULL
                    REFERENCES ergonomics_reviews(id) ON DELETE CASCADE,
                hazard_option_id TEXT NOT NULL
                    REFERENCES ergonomic_hazard_options(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL DEFAULT 10,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(ergonomics_review_id, hazard_option_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_ergonomic_hazard_option_label
                ON ergonomic_hazard_options(project_id, label COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_ergonomics_reviews_scenario
                ON ergonomics_reviews(project_id, scenario_id, work_element_id);
            CREATE INDEX IF NOT EXISTS idx_ergonomics_review_hazards
                ON ergonomics_review_hazard_selections(
                    project_id, scenario_id, ergonomics_review_id, sequence
                );
            """
        )
        _drop_yamazumi_flags_schema(conn)
        _upgrade_ergonomics_reviews_work_element_link(conn)
        _upgrade_ergonomics_reviews_risk_classification(conn)
        init_quality_schema(conn)
        init_pfmea_schema(conn)
        init_control_plan_schema(conn)
        project_columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "product_line" not in project_columns:
            conn.execute("ALTER TABLE projects ADD COLUMN product_line TEXT DEFAULT ''")
        if "yamazumi_line_code" not in project_columns:
            conn.execute(
                """ALTER TABLE projects ADD COLUMN yamazumi_line_code TEXT NOT NULL DEFAULT ''
                   CHECK(
                       yamazumi_line_code = '' OR (
                           length(yamazumi_line_code) = 2
                           AND yamazumi_line_code = upper(trim(yamazumi_line_code))
                           AND yamazumi_line_code NOT GLOB '*[^A-Z0-9]*'
                       )
                )"""
            )
        if "takt_time_unit" not in project_columns:
            conn.execute(
                "ALTER TABLE projects ADD COLUMN takt_time_unit "
                "TEXT NOT NULL DEFAULT 'seconds' "
                "CHECK(takt_time_unit IN ('seconds', 'minutes', 'hours'))"
            )
        for project_row in conn.execute(
            "SELECT id FROM projects WHERE yamazumi_line_code=''"
        ).fetchall():
            addresses = [
                str(row[0] or "").strip()
                for row in conn.execute(
                    "SELECT pitch_number FROM yamazumi_pitches WHERE project_id=?",
                    (project_row["id"],),
                ).fetchall()
                if str(row[0] or "").strip()
            ]
            prefixes = [yamazumi_line_prefix(address) for address in addresses]
            if addresses and all(prefixes) and len(set(prefixes)) == 1:
                conn.execute(
                    "UPDATE projects SET yamazumi_line_code=? WHERE id=?",
                    (prefixes[0], project_row["id"]),
                )
        part_columns = {row[1] for row in conn.execute("PRAGMA table_info(parts)").fetchall()}
        if "weight_lb" not in part_columns:
            conn.execute("ALTER TABLE parts ADD COLUMN weight_lb REAL")
        process_option_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(process_part_options)").fetchall()
        }
        if "handling_type" not in process_option_columns:
            conn.execute(
                """ALTER TABLE process_part_options ADD COLUMN handling_type TEXT
                   CHECK (handling_type IS NULL OR handling_type IN ('Handle', 'Consume'))"""
            )
        if "fishbone_assignment_id" not in process_option_columns:
            conn.execute(
                """ALTER TABLE process_part_options
                   ADD COLUMN fishbone_assignment_id TEXT
                   REFERENCES fishbone_part_assignments(id)"""
            )
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
            "catalog_part_id": "TEXT REFERENCES parts(id) ON DELETE RESTRICT",
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
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_assembly_catalog_part
               ON manufacturing_assemblies(project_id, catalog_part_id)
               WHERE catalog_part_id IS NOT NULL"""
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
        assembly_grid_category_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(assembly_grid_categories)"
            ).fetchall()
        }
        if "is_top_level" not in assembly_grid_category_columns:
            conn.execute(
                """ALTER TABLE assembly_grid_categories
                   ADD COLUMN is_top_level INTEGER NOT NULL DEFAULT 0
                   CHECK(is_top_level IN (0, 1))"""
            )
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_assembly_grid_one_top_level
               ON assembly_grid_categories(project_id)
               WHERE is_top_level=1"""
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
        scenario_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(planning_scenarios)").fetchall()
        }
        if "yamazumi_time_unit" not in scenario_columns:
            conn.execute(
                "ALTER TABLE planning_scenarios ADD COLUMN yamazumi_time_unit "
                "TEXT NOT NULL DEFAULT 'seconds' "
                "CHECK(yamazumi_time_unit IN ('seconds', 'minutes', 'hours'))"
            )
        if "takt_time_unit" not in scenario_columns:
            conn.execute(
                "ALTER TABLE planning_scenarios ADD COLUMN takt_time_unit "
                "TEXT NOT NULL DEFAULT 'seconds' "
                "CHECK(takt_time_unit IN ('seconds', 'minutes', 'hours'))"
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
        if "feeds_into_pitch_id" not in pitch_columns:
            conn.execute(
                "ALTER TABLE yamazumi_pitches ADD COLUMN feeds_into_pitch_id "
                "TEXT REFERENCES yamazumi_pitches(id) ON DELETE RESTRICT"
            )
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
                    """INSERT INTO parts
                       (id, project_id, part_number, description, quantity, revision,
                        source, image_path, model_applicability, notes, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'Sample', '', 'All', '', ?)""",
                    (str(uuid4()), project_id, pn, desc, qty, rev, timestamp),
                )
            sample_scenario_id = str(uuid4())
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, status,
                    takt_time_s, change_summary, created_by, created_at, updated_at)
                   VALUES (?, ?, 'Current plan', 'A', 1, 'Working', 60,
                           'Migrated from the original project plan',
                           'Industrial engineering', ?, ?)""",
                (sample_scenario_id, project_id, timestamp, timestamp),
            )
            sample_steps = [
                (10, "ST-010", "Load housing", "Place housing in locating fixture", 18.0, "PN-100100", "", "", "Confirm seated on all locators", "Two-hand lift review", "Main line / Zone 1", 37.4, 0, 0),
                (20, "ST-010", "Install bracket", "Locate bracket and hand-start four fasteners", 24.0, "PN-100220", "Nutrunner", "32 N·m ± 3", "Torque trace required", "Keep work below shoulder", "Main line / Zone 1", 37.4, 3.94, 0),
                (30, "ST-010", "Verify assembly", "Visual and torque-complete confirmation", 8.0, "HW-M8-025", "Scanner", "", "All four results pass", "", "Main line / Zone 1", 37.4, 3.94, 0),
            ]
            for row in sample_steps:
                _create_work_element_with_started_ergonomics_review(
                    conn,
                    project_id,
                    sample_scenario_id,
                    {
                        "sequence": row[0],
                        "station": row[1],
                        "operation": row[2],
                        "description": row[3],
                        "cycle_time_s": row[4],
                        "part_number": row[5],
                        "tool": row[6],
                        "torque": row[7],
                        "quality_requirement": row[8],
                        "ergo_requirement": row[9],
                        "location": row[10],
                        "conveyor_height_in": row[11],
                        "platform_height_in": row[12],
                        "pit_depth_in": row[13],
                        "model_applicability": "All",
                        "status": "Draft",
                    },
                    timestamp,
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
                        takt_time_s, takt_time_unit, change_summary, created_by,
                        created_at, updated_at)
                       VALUES (?, ?, 'Current plan', ?, 1, 'Working', ?, ?,
                               'Migrated from the original project plan', ?, ?, ?)""",
                    (
                        str(uuid4()), project["id"], str(project["revision"] or "A"),
                        float(project["takt_time_s"] or 60),
                        normalize_time_unit(project["takt_time_unit"]),
                        str(project["owner"] or ""),
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
        _backfill_missing_ergonomics_reviews(conn)

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

        # A completed manufacturing assembly is handled material again downstream.
        # Backfill one stable Parts Catalog identity for legacy assembly rows. Matching
        # part numbers are reused without overwriting collaborator-authored fields.
        backfilled_by_project: dict[str, list[dict]] = {}
        timestamp = now_iso()
        for assembly in conn.execute(
            """SELECT id, project_id, assembly_number, name
               FROM manufacturing_assemblies
               WHERE catalog_part_id IS NULL
               ORDER BY project_id, assembly_number"""
        ).fetchall():
            matches = conn.execute(
                """SELECT id FROM parts
                   WHERE project_id=? AND LOWER(TRIM(part_number))=LOWER(TRIM(?))
                   ORDER BY CASE WHEN part_number=? THEN 0 ELSE 1 END, id""",
                (
                    assembly["project_id"], assembly["assembly_number"],
                    assembly["assembly_number"],
                ),
            ).fetchall()
            if len(matches) > 1:
                raise ValueError(
                    f"Assembly {assembly['assembly_number']} matches multiple Parts Catalog "
                    "rows after case-insensitive comparison. Resolve the duplicate part numbers "
                    "before the assembly-part schema upgrade can run."
                )
            created = not matches
            part_id = str(matches[0]["id"]) if matches else str(uuid4())
            if created:
                conn.execute(
                    """INSERT INTO parts
                       (id, project_id, part_number, description, quantity, revision, source,
                        image_path, model_applicability, notes, updated_at)
                       VALUES (?, ?, ?, ?, 1, '0', 'Assembly grid', '', '', '', ?)""",
                    (
                        part_id, assembly["project_id"], assembly["assembly_number"],
                        assembly["name"], timestamp,
                    ),
                )
            conn.execute(
                """UPDATE manufacturing_assemblies
                   SET catalog_part_id=?, updated_at=? WHERE id=? AND project_id=?""",
                (part_id, timestamp, assembly["id"], assembly["project_id"]),
            )
            model_numbers = [
                str(row[0])
                for row in conn.execute(
                    """SELECT DISTINCT model.model_number
                       FROM assembly_grid_model_mappings mapping
                       JOIN project_models model ON model.id=mapping.model_id
                       WHERE mapping.project_id=? AND mapping.assembly_id=? AND model.active=1
                       ORDER BY model.model_number""",
                    (assembly["project_id"], assembly["id"]),
                ).fetchall()
            ]
            conn.execute(
                "UPDATE parts SET model_applicability=?, updated_at=? WHERE id=?",
                (", ".join(model_numbers), timestamp, part_id),
            )
            backfilled_by_project.setdefault(str(assembly["project_id"]), []).append(
                {
                    "assembly_id": str(assembly["id"]),
                    "assembly_number": str(assembly["assembly_number"]),
                    "part_id": part_id,
                    "action": "created" if created else "reused",
                }
            )
        for project_id, changes in backfilled_by_project.items():
            conn.execute(
                """INSERT INTO audit_log
                   (id, project_id, table_name, action, row_count, editor_name, details, created_at)
                   VALUES (?, ?, 'Parts', 'Assembly catalog backfill', ?,
                           'Schema upgrade', ?, ?)""",
                (
                    str(uuid4()), project_id, len(changes),
                    json.dumps({"assembly_parts": changes}, ensure_ascii=False), timestamp,
                ),
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
    takt_unit = normalize_time_unit(values.get("takt_time_unit", "seconds"))
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
                   SET name=?, revision_label=?, status=?, takt_time_s=?, takt_time_unit=?,
                       change_summary=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (
                    name, revision_label, status, takt, takt_unit,
                    str(values.get("change_summary") or "").strip(), now_iso(),
                    scenario_id, project_id,
                ),
            )
            if not cursor.rowcount:
                raise ValueError("The planning scenario no longer exists.")
    except sqlite3.IntegrityError as exc:
        raise ValueError("Scenario names and revision labels must be unique within this project.") from exc


def update_yamazumi_time_unit(
    project_id: str, scenario_id: str, value: object
) -> dict[str, str]:
    """Save one scenario's Yamazumi presentation unit without rewriting times."""
    unit = normalize_time_unit(value)
    timestamp = now_iso()
    with connection() as conn:
        current = conn.execute(
            "SELECT yamazumi_time_unit FROM planning_scenarios "
            "WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone()
        if not current:
            raise ValueError("The active planning scenario no longer exists in this project.")
        previous = normalize_time_unit(current["yamazumi_time_unit"])
        conn.execute(
            "UPDATE planning_scenarios SET yamazumi_time_unit=?, updated_at=? "
            "WHERE id=? AND project_id=?",
            (unit, timestamp, scenario_id, project_id),
        )
    return {"old_unit": previous, "new_unit": unit, "updated_at": timestamp}


def clone_planning_scenario(
    project_id: str,
    source_scenario_id: str,
    name: str,
    revision_label: str,
    takt_time_s: float,
    change_summary: str = "",
    created_by: str = "",
    *,
    takt_time_unit: str | None = None,
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
            _validate_yamazumi_scenario_pitch_addresses(
                conn, project_id, source_scenario_id
            )
            sequence = conn.execute(
                "SELECT COALESCE(MAX(revision_sequence), 0) + 1 FROM planning_scenarios WHERE project_id=?",
                (project_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, parent_scenario_id,
                    status, takt_time_s, takt_time_unit, yamazumi_time_unit,
                    change_summary, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'Working', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_scenario_id, project_id, name, revision_label, sequence,
                    source_scenario_id, takt,
                    normalize_time_unit(takt_time_unit or source["takt_time_unit"]),
                    normalize_time_unit(source["yamazumi_time_unit"]),
                    str(change_summary or "").strip(),
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
                _create_work_element_with_started_ergonomics_review(
                    conn,
                    project_id,
                    new_scenario_id,
                    {
                        column: value
                        for column, value in row.items()
                        if column not in {"id", "project_id", "scenario_id", "updated_at"}
                    },
                    timestamp,
                    work_element_id=new_id,
                )

            process_part_option_id_map: dict[str, str] = {}
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
                    old_option_id = str(option["id"])
                    new_option_id = str(uuid4())
                    process_part_option_id_map[old_option_id] = new_option_id
                    option.update(id=new_option_id, group_id=new_group_id, updated_at=timestamp)
                    option_columns = list(option)
                    conn.execute(
                        f"INSERT INTO process_part_options ({', '.join(option_columns)}) VALUES ({', '.join('?' for _ in option_columns)})",
                        tuple(option[column] for column in option_columns),
                    )

            _clone_ergonomics_reviews(
                conn,
                project_id,
                source_scenario_id,
                new_scenario_id,
                process_id_map,
                process_part_option_id_map,
                timestamp,
            )

            quality_assignment_id_map: dict[str, str] = {}
            clone_quality_requirement_assignments(
                conn,
                project_id,
                source_scenario_id,
                new_scenario_id,
                process_id_map,
                timestamp,
                quality_assignment_id_map,
            )
            pfmea_entry_id_map: dict[str, str] = {}
            clone_pfmea_scenario(
                conn,
                project_id,
                source_scenario_id,
                new_scenario_id,
                process_id_map,
                quality_assignment_id_map,
                timestamp,
                pfmea_entry_id_map,
            )
            clone_control_plan_scenario(
                conn,
                project_id,
                source_scenario_id,
                new_scenario_id,
                pfmea_entry_id_map,
                quality_assignment_id_map,
                timestamp,
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
            pending_pitch_feeds: list[tuple[str, str, str | None]] = []
            yamazumi_element_id_map: dict[str, str] = {}
            for old_area_id, new_area_id in area_id_map.items():
                for source_row in conn.execute(
                    "SELECT * FROM yamazumi_pitches WHERE project_id=? AND area_id=? ORDER BY sequence",
                    (project_id, old_area_id),
                ).fetchall():
                    row = dict(source_row)
                    old_id, new_id = str(row["id"]), str(uuid4())
                    pitch_id_map[old_id] = new_id
                    old_feed_target_id = str(row.get("feeds_into_pitch_id") or "").strip() or None
                    row.update(
                        id=new_id,
                        area_id=new_area_id,
                        feeds_into_pitch_id=None,
                        updated_at=timestamp,
                    )
                    pending_pitch_feeds.append(
                        (new_id, new_area_id, old_feed_target_id)
                    )
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

            for new_pitch_id, new_area_id, old_feed_target_id in pending_pitch_feeds:
                new_feed_target_id = (
                    pitch_id_map.get(old_feed_target_id) if old_feed_target_id else None
                )
                if old_feed_target_id and not new_feed_target_id:
                    raise ValueError(
                        "A Yamazumi pitch feed target could not be remapped while cloning the scenario."
                    )
                conn.execute(
                    "UPDATE yamazumi_pitches SET feeds_into_pitch_id=? WHERE id=?",
                    (new_feed_target_id, new_pitch_id),
                )
            for new_area_id in area_id_map.values():
                _validate_yamazumi_pitch_feeds(conn, project_id, new_area_id)

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
        takt_unit = normalize_time_unit(record.get("takt_time_unit", "seconds"))
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
                "takt_time_unit": takt_unit,
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
                takt_time_unit=str(record["takt_time_unit"]),
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
    *,
    _conn: sqlite3.Connection | None = None,
) -> None:
    """Record a concise, project-scoped history entry for a persisted table action."""
    sql = (
        """INSERT INTO audit_log
           (id, project_id, table_name, action, row_count, editor_name, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
    )
    params = (
        str(uuid4()), project_id, table_name, action, int(row_count), editor_name.strip(),
        json.dumps(details or {}, ensure_ascii=False), now_iso(),
    )
    if _conn is not None:
        _conn.execute(sql, params)
    else:
        execute(sql, params)


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


def _catalog_part_by_number(
    conn: sqlite3.Connection,
    project_id: str,
    part_number: str,
) -> sqlite3.Row | None:
    matches = conn.execute(
        """SELECT * FROM parts
           WHERE project_id=? AND LOWER(TRIM(part_number))=LOWER(TRIM(?))
           ORDER BY CASE WHEN part_number=? THEN 0 ELSE 1 END, id""",
        (project_id, part_number, part_number),
    ).fetchall()
    if len(matches) > 1:
        raise ValueError(
            f"Part number {part_number} matches multiple Parts Catalog rows. "
            "Resolve the duplicate catalog numbers before saving assemblies."
        )
    return matches[0] if matches else None


def _assembly_part_relationship_counts(
    conn: sqlite3.Connection, part_id: str
) -> dict[str, int]:
    def count(table: str, column: str = "part_id") -> int:
        return int(conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column}=?", (part_id,)
        ).fetchone()[0])

    return {
        "fishbone_use_count": count("fishbone_part_assignments"),
        "process_option_count": count("process_part_options"),
        "feature_rule_count": count("part_feature_rules"),
        "scenario_activity_count": count("part_scenario_activity"),
        "supplemental_image_count": count("part_images"),
    }


def _release_or_remove_generated_assembly_part(
    conn: sqlite3.Connection,
    project_id: str,
    part_id: str | None,
) -> str:
    """Remove only an untouched generated orphan; preserve every used/authored part."""
    if not part_id:
        return "none"
    part = conn.execute(
        "SELECT * FROM parts WHERE id=? AND project_id=?", (part_id, project_id)
    ).fetchone()
    if not part:
        return "none"
    linked = conn.execute(
        "SELECT 1 FROM manufacturing_assemblies WHERE catalog_part_id=? LIMIT 1",
        (part_id,),
    ).fetchone()
    relationships = _assembly_part_relationship_counts(conn, part_id)
    generated = str(part["source"] or "") == "Assembly grid"
    untouched = (
        float(part["quantity"] or 0) == 1
        and str(part["revision"] or "") == "0"
        and not str(part["image_path"] or "").strip()
        and not str(part["notes"] or "").strip()
    )
    if not linked and generated and untouched and not any(relationships.values()):
        conn.execute("DELETE FROM parts WHERE id=? AND project_id=?", (part_id, project_id))
        return "deleted generated orphan"
    return "preserved independent part"


def _ensure_assembly_catalog_part(
    conn: sqlite3.Connection,
    project_id: str,
    assembly_id: str,
    assembly_number: str,
    assembly_name: str,
    timestamp: str,
    *,
    allow_existing_relink: bool = False,
) -> dict:
    assembly = conn.execute(
        "SELECT catalog_part_id FROM manufacturing_assemblies WHERE id=? AND project_id=?",
        (assembly_id, project_id),
    ).fetchone()
    if not assembly:
        raise ValueError("The selected assembly no longer exists in this project.")
    old_part_id = _catalog_text(assembly["catalog_part_id"]) or None
    old_part = (
        conn.execute(
            "SELECT * FROM parts WHERE id=? AND project_id=?", (old_part_id, project_id)
        ).fetchone()
        if old_part_id else None
    )
    matching_part = _catalog_part_by_number(conn, project_id, assembly_number)
    if matching_part and str(matching_part["id"]) != old_part_id:
        owner = conn.execute(
            """SELECT assembly_number FROM manufacturing_assemblies
               WHERE project_id=? AND catalog_part_id=? AND id<>?""",
            (project_id, matching_part["id"], assembly_id),
        ).fetchone()
        if owner:
            raise ValueError(
                f"Part number {assembly_number} is already linked to assembly "
                f"{owner['assembly_number']}."
            )
        if old_part and not allow_existing_relink:
            raise ValueError(
                f"Part number {assembly_number} already exists in the Parts Catalog. "
                "Review and confirm the catalog-part relink before saving."
            )
        part_id = str(matching_part["id"])
        action = "reused existing part"
    elif matching_part:
        part_id = str(matching_part["id"])
        action = "kept linked part"
    elif old_part:
        conn.execute(
            "UPDATE parts SET part_number=?, updated_at=? WHERE id=? AND project_id=?",
            (assembly_number, timestamp, old_part_id, project_id),
        )
        part_id = old_part_id
        action = "renamed linked part"
    else:
        part_id = str(uuid4())
        conn.execute(
            """INSERT INTO parts
               (id, project_id, part_number, description, quantity, revision, source,
                image_path, model_applicability, notes, updated_at)
               VALUES (?, ?, ?, ?, 1, '0', 'Assembly grid', '', '', '', ?)""",
            (part_id, project_id, assembly_number, assembly_name, timestamp),
        )
        action = "created part"
    conn.execute(
        """UPDATE manufacturing_assemblies SET catalog_part_id=?, updated_at=?
           WHERE id=? AND project_id=?""",
        (part_id, timestamp, assembly_id, project_id),
    )
    old_part_action = (
        _release_or_remove_generated_assembly_part(conn, project_id, old_part_id)
        if old_part_id and old_part_id != part_id else "none"
    )
    return {
        "assembly_id": assembly_id,
        "assembly_number": assembly_number,
        "part_id": part_id,
        "action": action,
        "old_part_id": old_part_id,
        "old_part_action": old_part_action,
    }


def _sync_assembly_catalog_part_applicability(
    conn: sqlite3.Connection,
    project_id: str,
    timestamp: str,
) -> list[dict]:
    changes: list[dict] = []
    assemblies = conn.execute(
        """SELECT id, assembly_number, catalog_part_id
           FROM manufacturing_assemblies
           WHERE project_id=? AND catalog_part_id IS NOT NULL""",
        (project_id,),
    ).fetchall()
    for assembly in assemblies:
        model_numbers = [
            str(row[0])
            for row in conn.execute(
                """SELECT DISTINCT model.model_number
                   FROM assembly_grid_model_mappings mapping
                   JOIN project_models model ON model.id=mapping.model_id
                   WHERE mapping.project_id=? AND mapping.assembly_id=? AND model.active=1
                   ORDER BY model.model_number""",
                (project_id, assembly["id"]),
            ).fetchall()
        ]
        applicability = normalize_model_applicability(model_numbers) if model_numbers else ""
        part = conn.execute(
            "SELECT model_applicability FROM parts WHERE id=? AND project_id=?",
            (assembly["catalog_part_id"], project_id),
        ).fetchone()
        if part and str(part["model_applicability"] or "") != applicability:
            conn.execute(
                """UPDATE parts SET model_applicability=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (applicability, timestamp, assembly["catalog_part_id"], project_id),
            )
            changes.append(
                {
                    "assembly_id": str(assembly["id"]),
                    "assembly_number": str(assembly["assembly_number"]),
                    "part_id": str(assembly["catalog_part_id"]),
                    "model_applicability": applicability,
                }
            )
    return changes


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
                   category.root_number, category.is_top_level,
                   category.installed_section_id,
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
            is_top_level = int(
                raw.get("is_top_level") in (True, 1, "1", "true", "True")
            )
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
                if not bool(previous.get("is_top_level")):
                    raise ValueError(
                        "A category can be moved to another Fishbone section only through the "
                        "approved section-continuity workflow."
                    )
            if previous and bool(previous.get("is_top_level")) != bool(is_top_level):
                raise ValueError(
                    "The protected Top-level packaged unit row cannot be converted to or "
                    "from a Fishbone-section category."
                )
            if is_top_level and (
                ebom_name != "Top-level packaged unit"
                or display_name != "Top-level packaged unit"
            ):
                raise ValueError(
                    "The protected row must keep the name Top-level packaged unit."
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
                    "is_top_level": is_top_level,
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
        top_level_ids = [
            category_id
            for category_id, row in merged.items()
            if bool(row.get("is_top_level"))
        ]
        if len(top_level_ids) > 1:
            raise ValueError(
                "Only one Top-level packaged unit row is allowed in a project."
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
        built_sync_changes: list[dict] = []
        for row in normalized:
            previous = current.get(row["id"])
            created_at = _catalog_text(previous.get("created_at")) if previous else timestamp
            conn.execute(
                """INSERT INTO assembly_grid_categories
                   (id, project_id, section_id, ebom_name, display_name, root_number,
                    is_top_level, installed_section_id, sequence, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       section_id=excluded.section_id,
                       ebom_name=excluded.ebom_name,
                       display_name=excluded.display_name,
                       root_number=excluded.root_number,
                       is_top_level=excluded.is_top_level,
                       installed_section_id=excluded.installed_section_id,
                       sequence=excluded.sequence,
                       updated_at=excluded.updated_at""",
                (
                    row["id"], project_id, section_id, row["ebom_name"],
                    row["display_name"], row["root_number"],
                    row["is_top_level"], row["installed_section_id"], row["sequence"],
                    created_at, timestamp,
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
                previous_built_section_id = (
                    _catalog_text((previous or {}).get("section_id")) or None
                )
                if (
                    row["is_top_level"]
                    and previous_built_section_id
                    and previous_built_section_id != section_id
                ):
                    conn.execute(
                        """UPDATE fishbone_part_assignments SET section_id=?, updated_at=?
                           WHERE project_id=? AND id IN (
                               SELECT fishbone_assignment_id
                               FROM manufacturing_assembly_components
                               WHERE project_id=? AND assembly_id=?
                           )""",
                        (
                            section_id,
                            timestamp,
                            project_id,
                            project_id,
                            assembly["id"],
                        ),
                    )
                    conn.execute(
                        """UPDATE manufacturing_assemblies
                           SET built_section_id=?, updated_at=?
                           WHERE id=? AND project_id=?""",
                        (section_id, timestamp, assembly["id"], project_id),
                    )
                    built_sync_changes.append(
                        {
                            "assembly_id": str(assembly["id"]),
                            "assembly_number": str(assembly["assembly_number"]),
                            "old_built_section_id": previous_built_section_id,
                            "new_built_section_id": section_id,
                        }
                    )
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
        "built_section_sync_changes": built_sync_changes,
        "installed_section_sync_changes": sync_changes,
        "updated_at": timestamp,
    }


def assembly_grid_part_relink_impact(
    project_id: str, rows, *, _conn: sqlite3.Connection | None = None
) -> list[dict]:
    """Describe mapped-assembly renames that would relink to an existing catalog part."""
    records = _catalog_records(rows)
    with (connection() if _conn is None else nullcontext(_conn)) as conn:
        assemblies = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM manufacturing_assemblies WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        assembly_by_number = {
            _catalog_text(row["assembly_number"]).casefold(): assembly_id
            for assembly_id, row in assemblies.items()
        }
        candidates: dict[str, dict[str, str]] = {}
        for raw in records:
            assembly_id = _catalog_text(raw.get("assembly_id"))
            requested_number = _catalog_text(raw.get("assembly_number"))
            if (
                assembly_id in assemblies
                and requested_number
                and requested_number.casefold()
                != _catalog_text(assemblies[assembly_id]["assembly_number"]).casefold()
            ):
                candidates.setdefault(assembly_id, {})[
                    requested_number.casefold()
                ] = requested_number

        impacts: list[dict] = []
        for assembly_id, requested in candidates.items():
            if len(requested) != 1:
                continue
            target_number = next(iter(requested.values()))
            if assembly_by_number.get(target_number.casefold()) not in {None, assembly_id}:
                continue
            assembly = assemblies[assembly_id]
            source_part_id = _catalog_text(assembly.get("catalog_part_id"))
            target_part = _catalog_part_by_number(conn, project_id, target_number)
            if not source_part_id or not target_part or str(target_part["id"]) == source_part_id:
                continue
            owner = conn.execute(
                """SELECT assembly_number FROM manufacturing_assemblies
                   WHERE project_id=? AND catalog_part_id=? AND id<>?""",
                (project_id, target_part["id"], assembly_id),
            ).fetchone()
            if owner:
                raise ValueError(
                    f"Part number {target_number} is already linked to assembly "
                    f"{owner['assembly_number']}."
                )
            source_part = conn.execute(
                "SELECT * FROM parts WHERE id=? AND project_id=?",
                (source_part_id, project_id),
            ).fetchone()
            relationships = _assembly_part_relationship_counts(conn, source_part_id)
            generated_orphan = bool(
                source_part
                and str(source_part["source"] or "") == "Assembly grid"
                and float(source_part["quantity"] or 0) == 1
                and str(source_part["revision"] or "") == "0"
                and not str(source_part["image_path"] or "").strip()
                and not str(source_part["notes"] or "").strip()
                and not any(relationships.values())
            )
            impacts.append(
                {
                    "assembly_id": assembly_id,
                    "source_assembly_number": _catalog_text(assembly["assembly_number"]),
                    "target_assembly_number": target_number,
                    "source_part_id": source_part_id,
                    "target_part_id": str(target_part["id"]),
                    "source_part_number": str(source_part["part_number"]) if source_part else "",
                    "target_part_number": str(target_part["part_number"]),
                    "source_part_action": (
                        "deleted generated orphan" if generated_orphan
                        else "preserved independent part"
                    ),
                    **relationships,
                }
            )
        return impacts


def save_assembly_grid_model_mappings(
    project_id: str,
    rows,
    *,
    catalog_part_relinks: list[dict] | None = None,
    _validate_containment: bool = True,
    _conn: sqlite3.Connection | None = None,
) -> dict:
    """Replace the complete project mapping state after validating every relationship."""
    records = _catalog_records(rows)
    timestamp = now_iso()
    with (connection() if _conn is None else nullcontext(_conn)) as conn:
        actual_part_relinks = assembly_grid_part_relink_impact(
            project_id, records, _conn=conn
        )
        actual_relink_pairs = {
            (row["assembly_id"], row["target_part_id"])
            for row in actual_part_relinks
        }
        confirmed_relink_pairs = {
            (
                _catalog_text(row.get("assembly_id")),
                _catalog_text(row.get("target_part_id")),
            )
            for row in (catalog_part_relinks or [])
        }
        if actual_relink_pairs != confirmed_relink_pairs:
            if actual_relink_pairs:
                raise ValueError(
                    "Review and confirm the existing Parts Catalog relink before saving."
                )
            raise ValueError(
                "The pending Parts Catalog relink is no longer present. Review the grid again."
            )
        confirmed_relink_assemblies = {row[0] for row in actual_relink_pairs}
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
        catalog_part_changes: list[dict] = []
        for assembly in created_assemblies:
            catalog_part_changes.append(
                _ensure_assembly_catalog_part(
                    conn, project_id, assembly["id"], assembly["assembly_number"],
                    assembly["name"], timestamp,
                )
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
            catalog_part_changes.append(
                _ensure_assembly_catalog_part(
                    conn, project_id, assembly["assembly_id"],
                    assembly["assembly_number"],
                    _catalog_text(assemblies[assembly["assembly_id"]].get("name")),
                    timestamp,
                    allow_existing_relink=(
                        assembly["assembly_id"] in confirmed_relink_assemblies
                    ),
                )
            )
        for assembly_id, assembly in assemblies.items():
            if assembly_id in {row["id"] for row in created_assemblies}:
                continue
            if assembly_id in {row["assembly_id"] for row in renamed_assemblies}:
                continue
            if not _catalog_text(assembly.get("catalog_part_id")):
                catalog_part_changes.append(
                    _ensure_assembly_catalog_part(
                        conn, project_id, assembly_id,
                        _catalog_text(assembly.get("assembly_number")),
                        _catalog_text(assembly.get("name")), timestamp,
                    )
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
        applicability_changes = _sync_assembly_catalog_part_applicability(
            conn, project_id, timestamp
        )
        if _validate_containment:
            _validate_assembly_containment(conn, project_id)
    return {
        "count": len(normalized),
        "mapping_ids": [row["id"] for row in normalized],
        "created_assemblies": [
            {"assembly_id": row["id"], "assembly_number": row["assembly_number"]}
            for row in created_assemblies
        ],
        "renamed_assemblies": renamed_assemblies,
        "catalog_part_changes": catalog_part_changes,
        "catalog_part_relinks": actual_part_relinks,
        "catalog_part_applicability_changes": applicability_changes,
        "updated_at": timestamp,
    }


def assembly_grid_number_merge_impact(
    project_id: str, rows, *, _conn: sqlite3.Connection | None = None
) -> list[dict]:
    """Describe saved assemblies that a grid draft would replace with existing numbers."""
    records = _catalog_records(rows)
    with (connection() if _conn is None else nullcontext(_conn)) as conn:
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
        requested_targets: dict[str, str] = {}
        categories_by_assembly: dict[str, set[str]] = {}
        for raw in records:
            assembly_id = _catalog_text(raw.get("assembly_id"))
            category_id = _catalog_text(raw.get("category_id"))
            requested_number = _catalog_text(raw.get("assembly_number"))
            if assembly_id:
                categories_by_assembly.setdefault(assembly_id, set()).add(category_id)
            target_id = assembly_by_number.get(requested_number.casefold())
            if not assembly_id or assembly_id not in assemblies or not target_id:
                continue
            if target_id == assembly_id:
                continue
            previous_target = requested_targets.get(assembly_id)
            if previous_target and previous_target != target_id:
                raise ValueError(
                    f"Assembly {assemblies[assembly_id]['assembly_number']} has conflicting "
                    "Part number edits. Use one Part number for every model mapped to it."
                )
            requested_targets[assembly_id] = target_id

        impacts: list[dict] = []
        for source_id, target_id in requested_targets.items():
            if target_id in requested_targets:
                raise ValueError(
                    "Assembly-number merges cannot be chained in one save. Complete one merge "
                    "and refresh the grid before starting another."
                )
            source_categories = categories_by_assembly.get(source_id, set()) - {""}
            target_categories = categories_by_assembly.get(target_id, set()) - {""}
            combined_categories = source_categories | target_categories
            if len(combined_categories) > 1:
                category_rows = conn.execute(
                    f"""SELECT id, display_name FROM assembly_grid_categories
                        WHERE project_id=? AND id IN ({','.join('?' for _ in combined_categories)})""",
                    (project_id, *combined_categories),
                ).fetchall()
                category_names = ", ".join(str(row["display_name"]) for row in category_rows)
                raise ValueError(
                    f"Assembly {assemblies[target_id]['assembly_number']} is mapped under a "
                    f"different category ({category_names}). Move or clear those mappings "
                    "before merging assembly numbers."
                )

            def direct_count(table: str, column: str = "assembly_id") -> int:
                return int(conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column}=?",
                    (source_id,),
                ).fetchone()[0])

            source_image_paths = [
                str(row[0])
                for row in conn.execute(
                    """SELECT image_path FROM manufacturing_assemblies
                       WHERE project_id=? AND id=?
                         AND TRIM(COALESCE(image_path, ''))<>''
                       UNION ALL
                       SELECT image_path FROM manufacturing_assembly_images
                       WHERE project_id=? AND assembly_id=?""",
                    (project_id, source_id, project_id, source_id),
                ).fetchall()
            ]
            source_part_id = _catalog_text(
                assemblies[source_id].get("catalog_part_id")
            )
            target_part_id = _catalog_text(
                assemblies[target_id].get("catalog_part_id")
            )
            source_part_relationships = (
                _assembly_part_relationship_counts(conn, source_part_id)
                if source_part_id else {
                    "fishbone_use_count": 0,
                    "process_option_count": 0,
                    "feature_rule_count": 0,
                    "scenario_activity_count": 0,
                    "supplemental_image_count": 0,
                }
            )
            source_part = conn.execute(
                "SELECT * FROM parts WHERE id=? AND project_id=?",
                (source_part_id, project_id),
            ).fetchone() if source_part_id else None
            source_part_action = "none"
            if source_part:
                removable_generated_part = bool(
                    str(source_part["source"] or "") == "Assembly grid"
                    and float(source_part["quantity"] or 0) == 1
                    and str(source_part["revision"] or "") == "0"
                    and not str(source_part["image_path"] or "").strip()
                    and not str(source_part["notes"] or "").strip()
                    and not any(source_part_relationships.values())
                )
                source_part_action = (
                    "deleted generated orphan" if removable_generated_part
                    else "preserved independent part"
                )
            impacts.append(
                {
                    "source_assembly_id": source_id,
                    "source_assembly_number": str(assemblies[source_id]["assembly_number"]),
                    "target_assembly_id": target_id,
                    "target_assembly_number": str(assemblies[target_id]["assembly_number"]),
                    "source_component_count": direct_count(
                        "manufacturing_assembly_components"
                    ),
                    "target_component_count": int(conn.execute(
                        """SELECT COUNT(*) FROM manufacturing_assembly_components
                           WHERE project_id=? AND assembly_id=?""",
                        (project_id, target_id),
                    ).fetchone()[0]),
                    "source_rule_count": direct_count(
                        "manufacturing_assembly_feature_rules"
                    ),
                    "source_supplemental_image_count": direct_count(
                        "manufacturing_assembly_images"
                    ),
                    "source_primary_image_count": int(bool(
                        _catalog_text(assemblies[source_id].get("image_path"))
                    )),
                    "source_child_count": int(conn.execute(
                        """SELECT COUNT(*) FROM manufacturing_assemblies
                           WHERE project_id=? AND parent_id=?""",
                        (project_id, source_id),
                    ).fetchone()[0]),
                    "source_policy_count": direct_count("assembly_scenario_policies"),
                    "source_material_option_count": direct_count(
                        "work_element_material_options"
                    ),
                    "source_target_link_count": direct_count(
                        "work_element_material_groups", "target_assembly_id"
                    ),
                    "source_mapping_count": direct_count("assembly_grid_model_mappings"),
                    "reassigned_mapping_count": sum(
                        1
                        for raw in records
                        if _catalog_text(raw.get("assembly_id")) == source_id
                    ),
                    "source_part_id": source_part_id,
                    "target_part_id": target_part_id,
                    "source_part_number": (
                        str(source_part["part_number"]) if source_part else ""
                    ),
                    "source_part_action": source_part_action,
                    **source_part_relationships,
                    "source_image_paths": source_image_paths,
                }
            )
        return impacts


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
    assembly_merges: list[dict] | None = None,
    catalog_part_relinks: list[dict] | None = None,
) -> dict:
    """Validate and save one complete grid draft in a single transaction."""
    deleted_image_paths: list[str] = []
    with connection() as conn:
        merge_impact = assembly_grid_number_merge_impact(
            project_id, complete_mapping_rows, _conn=conn
        )
        part_relink_impact = assembly_grid_part_relink_impact(
            project_id, complete_mapping_rows, _conn=conn
        )
        actual_part_relinks = {
            (row["assembly_id"], row["target_part_id"])
            for row in part_relink_impact
        }
        confirmed_part_relinks = {
            (
                _catalog_text(row.get("assembly_id")),
                _catalog_text(row.get("target_part_id")),
            )
            for row in (catalog_part_relinks or [])
        }
        if actual_part_relinks != confirmed_part_relinks:
            if actual_part_relinks:
                raise ValueError(
                    "Review and confirm the existing Parts Catalog relink before saving."
                )
            raise ValueError(
                "The pending Parts Catalog relink is no longer present. Review the grid again."
            )
        actual_merges = {
            (row["source_assembly_id"], row["target_assembly_id"])
            for row in merge_impact
        }
        confirmed_merges = {
            (
                _catalog_text(row.get("source_assembly_id")),
                _catalog_text(row.get("target_assembly_id")),
            )
            for row in (assembly_merges or [])
        }
        if actual_merges != confirmed_merges:
            if actual_merges:
                raise ValueError(
                    "Review and confirm the assembly-number merge before saving."
                )
            raise ValueError(
                "The pending assembly-number merge is no longer present. Review the grid again."
            )
        target_by_source = dict(actual_merges)
        resolved_mapping_rows = []
        for raw in _catalog_records(complete_mapping_rows):
            source_id = _catalog_text(raw.get("assembly_id"))
            target_id = target_by_source.get(source_id)
            if target_id:
                target_number = next(
                    row["target_assembly_number"]
                    for row in merge_impact
                    if row["source_assembly_id"] == source_id
                )
                resolved_mapping_rows.append(
                    {**raw, "assembly_id": target_id, "assembly_number": target_number}
                )
            else:
                resolved_mapping_rows.append(raw)
        categories_result = save_assembly_grid_categories(
            project_id, section_id, category_rows, _conn=conn
        )
        mappings_result = save_assembly_grid_model_mappings(
            project_id,
            resolved_mapping_rows,
            catalog_part_relinks=part_relink_impact,
            _validate_containment=False,
            _conn=conn,
        )
        visibility_result = save_assembly_grid_feature_visibility(
            project_id, section_id, feature_visibility_rows, _conn=conn
        )
        component_results: dict[str, dict] = {}
        for assembly_id, rows in (component_rows_by_assembly or {}).items():
            if str(assembly_id) in target_by_source:
                continue
            component_results[str(assembly_id)] = save_assembly_bom_components(
                project_id,
                str(assembly_id),
                rows,
                _validate_containment=False,
                _conn=conn,
            )
        for impact in merge_impact:
            deleted_image_paths.extend(impact["source_image_paths"])
            conn.execute(
                "DELETE FROM manufacturing_assemblies WHERE project_id=? AND id=?",
                (project_id, impact["source_assembly_id"]),
            )
            impact["source_part_action"] = _release_or_remove_generated_assembly_part(
                conn, project_id, impact.get("source_part_id")
            )
        _validate_assembly_containment(conn, project_id)
    for image_path in deleted_image_paths:
        _remove_owned_upload(image_path)
    return {
        "categories": categories_result,
        "mappings": mappings_result,
        "feature_visibility": visibility_result,
        "components": component_results,
        "assembly_merges": merge_impact,
        "catalog_part_relinks": part_relink_impact,
        "updated_at": now_iso(),
    }


def save_assembly_grid_sections(
    project_id: str,
    section_payloads: list[dict],
    complete_mapping_rows,
    component_rows_by_assembly: dict[str, list[dict]] | None = None,
    assembly_merges: list[dict] | None = None,
    catalog_part_relinks: list[dict] | None = None,
) -> dict:
    """Validate and atomically save every displayed Assembly grid section."""
    payloads = [dict(payload) for payload in section_payloads]
    section_ids = [_catalog_text(payload.get("section_id")) for payload in payloads]
    if not section_ids or any(not section_id for section_id in section_ids):
        raise ValueError("Select at least one Fishbone section to save.")
    if len(section_ids) != len(set(section_ids)):
        raise ValueError("Each selected Fishbone section may appear only once in a grid save.")

    deleted_image_paths: list[str] = []
    with connection() as conn:
        merge_impact = assembly_grid_number_merge_impact(
            project_id, complete_mapping_rows, _conn=conn
        )
        part_relink_impact = assembly_grid_part_relink_impact(
            project_id, complete_mapping_rows, _conn=conn
        )
        actual_part_relinks = {
            (row["assembly_id"], row["target_part_id"])
            for row in part_relink_impact
        }
        confirmed_part_relinks = {
            (
                _catalog_text(row.get("assembly_id")),
                _catalog_text(row.get("target_part_id")),
            )
            for row in (catalog_part_relinks or [])
        }
        if actual_part_relinks != confirmed_part_relinks:
            if actual_part_relinks:
                raise ValueError(
                    "Review and confirm the existing Parts Catalog relink before saving."
                )
            raise ValueError(
                "The pending Parts Catalog relink is no longer present. Review the grid again."
            )
        actual_merges = {
            (row["source_assembly_id"], row["target_assembly_id"])
            for row in merge_impact
        }
        confirmed_merges = {
            (
                _catalog_text(row.get("source_assembly_id")),
                _catalog_text(row.get("target_assembly_id")),
            )
            for row in (assembly_merges or [])
        }
        if actual_merges != confirmed_merges:
            if actual_merges:
                raise ValueError("Review and confirm the assembly-number merge before saving.")
            raise ValueError(
                "The pending assembly-number merge is no longer present. Review the grid again."
            )

        target_by_source = dict(actual_merges)
        target_number_by_source = {
            row["source_assembly_id"]: row["target_assembly_number"]
            for row in merge_impact
        }
        resolved_mapping_rows = []
        for raw in _catalog_records(complete_mapping_rows):
            source_id = _catalog_text(raw.get("assembly_id"))
            target_id = target_by_source.get(source_id)
            resolved_mapping_rows.append(
                {
                    **raw,
                    **(
                        {
                            "assembly_id": target_id,
                            "assembly_number": target_number_by_source[source_id],
                        }
                        if target_id else {}
                    ),
                }
            )

        section_results: dict[str, dict] = {}
        for section_id, payload in zip(section_ids, payloads):
            section_results[section_id] = {
                "categories": save_assembly_grid_categories(
                    project_id,
                    section_id,
                    payload.get("categories", []),
                    _conn=conn,
                )
            }
        mappings_result = save_assembly_grid_model_mappings(
            project_id,
            resolved_mapping_rows,
            catalog_part_relinks=part_relink_impact,
            _validate_containment=False,
            _conn=conn,
        )
        for section_id, payload in zip(section_ids, payloads):
            section_results[section_id]["feature_visibility"] = (
                save_assembly_grid_feature_visibility(
                    project_id,
                    section_id,
                    payload["feature_visibility"],
                    _conn=conn,
                )
                if "feature_visibility" in payload
                else {
                    "count": 0,
                    "hidden_feature_ids": [],
                    "updated_at": now_iso(),
                }
            )

        component_results: dict[str, dict] = {}
        for assembly_id, rows in (component_rows_by_assembly or {}).items():
            if str(assembly_id) in target_by_source:
                continue
            component_results[str(assembly_id)] = save_assembly_bom_components(
                project_id,
                str(assembly_id),
                rows,
                _validate_containment=False,
                _conn=conn,
            )
        for impact in merge_impact:
            deleted_image_paths.extend(impact["source_image_paths"])
            conn.execute(
                "DELETE FROM manufacturing_assemblies WHERE project_id=? AND id=?",
                (project_id, impact["source_assembly_id"]),
            )
            impact["source_part_action"] = _release_or_remove_generated_assembly_part(
                conn, project_id, impact.get("source_part_id")
            )
        _validate_assembly_containment(conn, project_id)

    for image_path in deleted_image_paths:
        _remove_owned_upload(image_path)
    return {
        "sections": section_results,
        "mappings": mappings_result,
        "components": component_results,
        "assembly_merges": merge_impact,
        "catalog_part_relinks": part_relink_impact,
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
            f"""SELECT id, display_name, is_top_level FROM assembly_grid_categories
                WHERE project_id=? AND section_id=? AND id IN ({placeholders})""",
            (project_id, section_id, *normalized),
        ).fetchall()
        if len(categories) != len(normalized):
            raise ValueError("One or more selected assembly-grid categories no longer exist.")
        if any(bool(row["is_top_level"]) for row in categories):
            raise ValueError(
                "The Top-level packaged unit row cannot be deleted. Clear its model "
                "mappings instead."
            )
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
        applicability_changes = _sync_assembly_catalog_part_applicability(
            conn, project_id, now_iso()
        )
    return {
        "deleted_count": len(normalized),
        "mapping_count": mapping_count,
        "category_ids": normalized,
        "category_names": [str(row["display_name"]) for row in categories],
        "catalog_part_applicability_changes": applicability_changes,
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
        catalog_part_changes: list[dict] = []
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
            catalog_part_changes.append(
                _ensure_assembly_catalog_part(
                    conn,
                    project_id,
                    row["id"],
                    row["assembly_number"],
                    row["name"],
                    timestamp,
                )
            )
        applicability_changes = _sync_assembly_catalog_part_applicability(
            conn, project_id, timestamp
        )
    return {
        "count": len(normalized),
        "updated_at": timestamp,
        "mismatch_warnings": mismatch_warnings,
        "make_buy_changes": make_buy_changes,
        "catalog_part_changes": catalog_part_changes,
        "catalog_part_applicability_changes": applicability_changes,
        "assembly_ids": [row["id"] for row in normalized],
    }


def assembly_bom_components(project_id: str, assembly_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT component.*, assignment.part_id, assignment.section_id,
                  assignment.quantity AS fishbone_quantity,
                  assignment.use_description, assignment.notes AS fishbone_notes,
                  part.part_number, part.description AS part_name,
                  child.id AS nested_assembly_id,
                  child.assembly_number AS nested_assembly_number,
                  section.name AS current_section_name,
                  assembly.built_section_id,
                  CASE WHEN assignment.section_id=assembly.built_section_id THEN 0 ELSE 1 END
                       AS section_mismatch
           FROM manufacturing_assembly_components component
           JOIN manufacturing_assemblies assembly ON assembly.id=component.assembly_id
           JOIN fishbone_part_assignments assignment
             ON assignment.id=component.fishbone_assignment_id
           JOIN parts part ON part.id=assignment.part_id
           LEFT JOIN manufacturing_assemblies child
             ON child.catalog_part_id=part.id AND child.project_id=component.project_id
           JOIN assembly_sections section ON section.id=assignment.section_id
           WHERE component.project_id=? AND component.assembly_id=?
           ORDER BY part.part_number, assignment.sequence""",
        (project_id, assembly_id),
    ))


def _assembly_containment_edges(
    conn: sqlite3.Connection, project_id: str
) -> list[dict]:
    """Return operational parent/child assembly links derived from mini-BOM parts."""
    return [
        dict(row)
        for row in conn.execute(
            """SELECT DISTINCT component.assembly_id AS parent_assembly_id,
                              child.id AS child_assembly_id,
                              parent.assembly_number AS parent_assembly_number,
                              child.assembly_number AS child_assembly_number
               FROM manufacturing_assembly_components component
               JOIN manufacturing_assemblies parent
                 ON parent.id=component.assembly_id AND parent.project_id=component.project_id
               JOIN fishbone_part_assignments assignment
                 ON assignment.id=component.fishbone_assignment_id
                AND assignment.project_id=component.project_id
               JOIN manufacturing_assemblies child
                 ON child.catalog_part_id=assignment.part_id
                AND child.project_id=component.project_id
               WHERE component.project_id=?""",
            (project_id,),
        ).fetchall()
    ]


def _validate_assembly_containment(
    conn: sqlite3.Connection, project_id: str
) -> None:
    """Reject mini-BOM assembly cycles and incomplete child model coverage."""
    edges = _assembly_containment_edges(conn, project_id)
    children_by_parent: dict[str, set[str]] = {}
    number_by_id: dict[str, str] = {}
    for edge in edges:
        parent_id = str(edge["parent_assembly_id"])
        child_id = str(edge["child_assembly_id"])
        number_by_id[parent_id] = str(edge["parent_assembly_number"])
        number_by_id[child_id] = str(edge["child_assembly_number"])
        if parent_id == child_id:
            raise ValueError(
                f"Assembly {number_by_id[parent_id]} cannot contain itself in its mini-BOM."
            )
        children_by_parent.setdefault(parent_id, set()).add(child_id)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(assembly_id: str, path: list[str]) -> None:
        if assembly_id in visiting:
            cycle_start = path.index(assembly_id)
            cycle = path[cycle_start:] + [assembly_id]
            labels = " → ".join(number_by_id.get(value, value) for value in cycle)
            raise ValueError(f"Assembly mini-BOM nesting cannot contain a cycle: {labels}.")
        if assembly_id in visited:
            return
        visiting.add(assembly_id)
        for child_id in children_by_parent.get(assembly_id, set()):
            visit(child_id, [*path, child_id])
        visiting.remove(assembly_id)
        visited.add(assembly_id)

    for parent_id in children_by_parent:
        visit(parent_id, [parent_id])

    mapped_models: dict[str, set[str]] = {}
    model_number_by_id: dict[str, str] = {}
    for row in conn.execute(
        """SELECT mapping.assembly_id, mapping.model_id, model.model_number
           FROM assembly_grid_model_mappings mapping
           JOIN project_models model
             ON model.id=mapping.model_id AND model.project_id=mapping.project_id
           WHERE mapping.project_id=?""",
        (project_id,),
    ).fetchall():
        mapped_models.setdefault(str(row["assembly_id"]), set()).add(str(row["model_id"]))
        model_number_by_id[str(row["model_id"])] = str(row["model_number"])
    for edge in edges:
        parent_id = str(edge["parent_assembly_id"])
        child_id = str(edge["child_assembly_id"])
        missing = mapped_models.get(parent_id, set()) - mapped_models.get(child_id, set())
        if missing:
            labels = ", ".join(
                sorted(model_number_by_id.get(model_id, model_id) for model_id in missing)
            )
            raise ValueError(
                f"Child assembly {edge['child_assembly_number']} does not cover every model "
                f"mapped to parent assembly {edge['parent_assembly_number']}. Missing: {labels}."
            )


def save_assembly_bom_components(
    project_id: str,
    assembly_id: str,
    rows,
    *,
    _validate_containment: bool = True,
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
        created_fishbone_uses: list[dict] = []
        assignment_ids: set[str] = set()
        row_ids: set[str] = set()
        for raw in records:
            row_id = _catalog_text(raw.get("id")) or str(uuid4())
            assignment_id = _catalog_text(raw.get("fishbone_assignment_id"))
            nested_assembly_id = _catalog_text(raw.get("nested_assembly_id"))
            if nested_assembly_id and not assignment_id:
                child = conn.execute(
                    """SELECT id, assembly_number, catalog_part_id
                       FROM manufacturing_assemblies
                       WHERE id=? AND project_id=?""",
                    (nested_assembly_id, project_id),
                ).fetchone()
                if not child or not _catalog_text(child["catalog_part_id"]):
                    raise ValueError(
                        "Every nested subassembly must be a current project assembly with a "
                        "linked Parts Catalog row."
                    )
                existing_use = conn.execute(
                    """SELECT id FROM fishbone_part_assignments
                       WHERE project_id=? AND section_id=? AND part_id=?
                       ORDER BY sequence, id LIMIT 1""",
                    (project_id, built_section_id, child["catalog_part_id"]),
                ).fetchone()
                if existing_use:
                    assignment_id = str(existing_use["id"])
                else:
                    assignment_id = str(uuid4())
                    next_sequence = conn.execute(
                        """SELECT COALESCE(MAX(sequence), 0) + 10
                           FROM fishbone_part_assignments
                           WHERE project_id=? AND section_id=?""",
                        (project_id, built_section_id),
                    ).fetchone()[0]
                    raw_quantity = raw.get("quantity")
                    try:
                        placement_quantity = float(raw_quantity or 1)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            "Nested subassembly quantities must be numbers greater than zero."
                        ) from exc
                    if not math.isfinite(placement_quantity) or placement_quantity <= 0:
                        raise ValueError(
                            "Nested subassembly quantities must be numbers greater than zero."
                        )
                    conn.execute(
                        """INSERT INTO fishbone_part_assignments
                           (id, project_id, part_id, section_id, sequence, quantity,
                            use_description, notes, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, '', ?)""",
                        (
                            assignment_id,
                            project_id,
                            child["catalog_part_id"],
                            built_section_id,
                            next_sequence,
                            placement_quantity,
                            f"Nested assembly {child['assembly_number']}",
                            timestamp,
                        ),
                    )
                    created_fishbone_uses.append(
                        {
                            "assignment_id": assignment_id,
                            "parent_assembly_id": assembly_id,
                            "parent_assembly_number": str(assembly["assembly_number"]),
                            "child_assembly_id": nested_assembly_id,
                            "child_assembly_number": str(child["assembly_number"]),
                            "section_id": built_section_id,
                        }
                    )
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
        if _validate_containment:
            _validate_assembly_containment(conn, project_id)
        nested_relationships = [
            edge
            for edge in _assembly_containment_edges(conn, project_id)
            if str(edge["parent_assembly_id"]) == str(assembly_id)
        ]
    return {
        "count": len(normalized),
        "created_fishbone_uses": created_fishbone_uses,
        "nested_relationships": nested_relationships,
        "updated_at": timestamp,
    }


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
        preserved_catalog_parts = [
            dict(row)
            for row in conn.execute(
                f"""SELECT assembly.id AS assembly_id, assembly.assembly_number,
                            part.id AS part_id, part.part_number
                     FROM manufacturing_assemblies assembly
                     JOIN parts part ON part.id=assembly.catalog_part_id
                     WHERE assembly.id IN ({affected_placeholders})
                     ORDER BY assembly.assembly_number""",
                tuple(affected_ids),
            ).fetchall()
        ]
        nested_parent_links = [
            dict(row)
            for row in conn.execute(
                f"""SELECT DISTINCT child.id AS child_assembly_id,
                                   child.assembly_number AS child_assembly_number,
                                   parent.id AS parent_assembly_id,
                                   parent.assembly_number AS parent_assembly_number
                    FROM manufacturing_assemblies child
                    JOIN fishbone_part_assignments assignment
                      ON assignment.part_id=child.catalog_part_id
                     AND assignment.project_id=child.project_id
                    JOIN manufacturing_assembly_components component
                      ON component.fishbone_assignment_id=assignment.id
                     AND component.project_id=child.project_id
                    JOIN manufacturing_assemblies parent
                      ON parent.id=component.assembly_id
                    WHERE child.project_id=?
                      AND child.id IN ({affected_placeholders})
                    ORDER BY child.assembly_number, parent.assembly_number""",
                (project_id, *affected_ids),
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
            "preserved_catalog_parts": preserved_catalog_parts,
            "preserved_catalog_part_count": len(preserved_catalog_parts),
            "nested_parent_links": nested_parent_links,
            "nested_parent_link_count": len(nested_parent_links),
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


def _normalize_handling_type(value) -> str | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    handling_type = str(value).strip()
    if handling_type not in HANDLING_TYPES:
        raise ValueError("Handling type must be Handle or Consume.")
    return handling_type


def _normalize_fishbone_assignment_id(value) -> str | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    return str(value).strip()


def _process_part_assignment_consume_count(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    fishbone_assignment_id: str,
    *,
    exclude_process_part_option_id: str | None = None,
) -> int:
    exclude_clause = " AND option.id<>?" if exclude_process_part_option_id else ""
    params: tuple = (project_id, scenario_id, fishbone_assignment_id)
    if exclude_process_part_option_id:
        params += (exclude_process_part_option_id,)
    return int(
        conn.execute(
            f"""SELECT COUNT(*)
                FROM process_part_options option
                JOIN process_part_groups group_row ON group_row.id=option.group_id
                WHERE group_row.project_id=? AND group_row.scenario_id=?
                  AND option.fishbone_assignment_id=?
                  AND option.handling_type='Consume'{exclude_clause}""",
            params,
        ).fetchone()[0]
    )


def _validate_process_part_option_handling(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    scenario_id: str,
    section_id: str,
    process_part_option_id: str,
    part_id: str,
    handling_type: str | None,
    fishbone_assignment_id: str | None,
) -> None:
    if handling_type is None and fishbone_assignment_id is None:
        return
    if handling_type is not None and fishbone_assignment_id is None:
        raise ValueError(
            f"A Fishbone placement is required before this part can be {handling_type.lower()}d."
        )
    if fishbone_assignment_id is None:
        return

    assignment = conn.execute(
        """SELECT assignment.id, assignment.quantity, assignment.use_description,
                  part.part_number, section.name AS section_name
           FROM fishbone_part_assignments assignment
           JOIN parts part ON part.id=assignment.part_id
           JOIN assembly_sections section ON section.id=assignment.section_id
           WHERE assignment.id=? AND assignment.project_id=?
             AND assignment.part_id=? AND assignment.section_id=?""",
        (fishbone_assignment_id, project_id, part_id, section_id),
    ).fetchone()
    if not assignment:
        raise ValueError(
            "Choose a Fishbone placement for the same part in this part requirement's "
            "Fishbone section."
        )
    if handling_type is None:
        return

    other_consume_count = _process_part_assignment_consume_count(
        conn,
        project_id,
        scenario_id,
        fishbone_assignment_id,
        exclude_process_part_option_id=process_part_option_id,
    )
    placement_label = str(assignment["part_number"])
    use_description = str(assignment["use_description"] or "").strip()
    if use_description:
        placement_label = f"{placement_label} — {use_description}"
    placement_label = f"{placement_label} [{assignment['id']}]"

    if handling_type == "Consume":
        recorded_quantity = float(assignment["quantity"])
        if other_consume_count + 1 > recorded_quantity:
            raise ValueError(
                f"Fishbone placement {placement_label} has a recorded quantity of "
                f"{recorded_quantity:g}, which has already been fully consumed elsewhere "
                "in this scenario."
            )
        return

    if other_consume_count < 1:
        raise ValueError(
            f"Fishbone placement {placement_label} must be Consumed before it can be Handled "
            "in this scenario."
        )


def process_part_placement_options(
    project_id: str,
    scenario_id: str,
    section_id: str,
    part_id: str,
) -> pd.DataFrame:
    """Return exact Fishbone uses with scenario-specific Consume availability."""
    columns = [
        "fishbone_assignment_id",
        "part_id",
        "part_number",
        "section_id",
        "section_name",
        "use_description",
        "fishbone_quantity",
        "consumed_count",
        "remaining_consume_allowance",
        "can_consume",
        "can_handle",
    ]
    with connection() as conn:
        if not conn.execute(
            """SELECT 1 FROM planning_scenarios
               WHERE id=? AND project_id=?""",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        assignments = conn.execute(
            """SELECT assignment.id AS fishbone_assignment_id,
                      assignment.part_id, part.part_number,
                      assignment.section_id, section.name AS section_name,
                      assignment.use_description,
                      assignment.quantity AS fishbone_quantity
               FROM fishbone_part_assignments assignment
               JOIN parts part ON part.id=assignment.part_id
               JOIN assembly_sections section ON section.id=assignment.section_id
               LEFT JOIN part_scenario_activity activity
                 ON activity.project_id=assignment.project_id
                AND activity.scenario_id=? AND activity.part_id=assignment.part_id
               WHERE assignment.project_id=? AND assignment.section_id=?
                 AND assignment.part_id=? AND COALESCE(activity.active, 1)=1
               ORDER BY assignment.sequence, assignment.id""",
            (scenario_id, project_id, section_id, part_id),
        ).fetchall()
        rows: list[dict] = []
        for assignment in assignments:
            assignment_id = str(assignment["fishbone_assignment_id"])
            consumed_count = _process_part_assignment_consume_count(
                conn, project_id, scenario_id, assignment_id
            )
            fishbone_quantity = float(assignment["fishbone_quantity"])
            remaining = max(fishbone_quantity - consumed_count, 0.0)
            row = dict(assignment)
            row.update(
                consumed_count=consumed_count,
                remaining_consume_allowance=remaining,
                can_consume=(consumed_count + 1 <= fishbone_quantity),
                can_handle=(consumed_count >= 1),
            )
            rows.append(row)
    if not rows:
        return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})
    return pd.DataFrame(rows, columns=columns)


def validate_process_part_option_pairings(
    project_id: str,
    scenario_id: str,
    section_id: str,
    pairings: list[dict],
) -> None:
    """Validate new Process part pairings before any surrounding workflow writes."""
    with connection() as conn:
        if not conn.execute(
            """SELECT 1 FROM planning_scenarios
               WHERE id=? AND project_id=?""",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        for pairing in pairings:
            _validate_process_part_option_handling(
                conn,
                project_id=project_id,
                scenario_id=scenario_id,
                section_id=section_id,
                process_part_option_id=str(pairing.get("id") or uuid4()),
                part_id=str(pairing.get("part_id") or ""),
                handling_type=_normalize_handling_type(
                    pairing.get("handling_type")
                ),
                fishbone_assignment_id=_normalize_fishbone_assignment_id(
                    pairing.get("fishbone_assignment_id")
                ),
            )


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
                  option.handling_type, option.fishbone_assignment_id, part.weight_lb,
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
                   CASE WHEN process.id IS NULL THEN 0 ELSE 1 END AS process_reflected,
                   COUNT(DISTINCT group_row.id) AS material_group_count
           FROM yamazumi_elements element
            JOIN yamazumi_areas area ON area.id=element.area_id
            LEFT JOIN yamazumi_pitches pitch ON pitch.id=element.pitch_id
            LEFT JOIN work_elements process
              ON process.id=element.process_element_id
             AND process.project_id=element.project_id
             AND process.scenario_id=area.scenario_id
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
                   pitch.id AS pitch_id, pitch.pitch_number, pitch.pitch_name
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
            f"""SELECT option.id, option.part_id, option.handling_type,
                      option.fishbone_assignment_id,
                      part.part_number, part.description AS part_description,
                      part.model_applicability, part.weight_lb
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
    handling_types_by_part: dict[str, str | None] | None = None,
    fishbone_assignment_ids_by_part: dict[str, str | None] | None = None,
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
    normalized_handling_types: dict[str, str | None] = {}
    if handling_types_by_part is not None:
        unknown_part_ids = set(handling_types_by_part) - set(selected_part_ids)
        if unknown_part_ids:
            raise ValueError("Handling types may only be supplied for selected parts.")
        for part_id, value in handling_types_by_part.items():
            normalized_handling_types[str(part_id)] = _normalize_handling_type(value)
    normalized_assignment_ids: dict[str, str | None] = {}
    if fishbone_assignment_ids_by_part is not None:
        unknown_part_ids = set(fishbone_assignment_ids_by_part) - set(selected_part_ids)
        if unknown_part_ids:
            raise ValueError("Fishbone placements may only be supplied for selected parts.")
        for part_id, value in fishbone_assignment_ids_by_part.items():
            normalized_assignment_ids[str(part_id)] = _normalize_fishbone_assignment_id(value)
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
            existing_group = conn.execute(
                """SELECT project_id, scenario_id, work_element_id
                   FROM process_part_groups WHERE id=?""",
                (group_id,),
            ).fetchone()
            if existing_group and (
                str(existing_group["project_id"]) != project_id
                or str(existing_group["scenario_id"]) != scenario_id
                or str(existing_group["work_element_id"]) != work_element_id
            ):
                raise ValueError("That part requirement no longer belongs to this process step.")
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
            existing_options = {
                str(row["part_id"]): dict(row)
                for row in conn.execute(
                    """SELECT id, part_id, handling_type, fishbone_assignment_id
                       FROM process_part_options WHERE group_id=?""",
                    (group_id,),
                ).fetchall()
            }
            conn.execute(
                f"""DELETE FROM process_part_options
                    WHERE group_id=? AND part_id NOT IN ({placeholders})""",
                (group_id, *selected_part_ids),
            )
            for part_id in selected_part_ids:
                existing_option = existing_options.get(part_id)
                handling_type = normalized_handling_types.get(
                    part_id,
                    existing_option.get("handling_type") if existing_option else None,
                )
                fishbone_assignment_id = normalized_assignment_ids.get(
                    part_id,
                    existing_option.get("fishbone_assignment_id") if existing_option else None,
                )
                option_id = (
                    str(existing_option["id"]) if existing_option else str(uuid4())
                )
                _validate_process_part_option_handling(
                    conn,
                    project_id=project_id,
                    scenario_id=scenario_id,
                    section_id=section_id,
                    process_part_option_id=option_id,
                    part_id=part_id,
                    handling_type=handling_type,
                    fishbone_assignment_id=fishbone_assignment_id,
                )
                if existing_option:
                    conn.execute(
                        """UPDATE process_part_options
                           SET handling_type=?, fishbone_assignment_id=?, updated_at=?
                           WHERE id=? AND group_id=?""",
                        (
                            handling_type,
                            fishbone_assignment_id,
                            timestamp,
                            option_id,
                            group_id,
                        ),
                    )
                else:
                    conn.execute(
                        """INSERT INTO process_part_options
                           (id, group_id, part_id, handling_type,
                            fishbone_assignment_id, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            option_id,
                            group_id,
                            part_id,
                            handling_type,
                            fishbone_assignment_id,
                            timestamp,
                        ),
                    )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Part requirement names must be unique within a process step.") from exc
    return group_id


def set_part_weight_lb(project_id: str, part_id: str, weight_lb) -> str:
    """Set or clear a project-wide Parts Catalog weight in pounds."""
    weight = _optional_nonnegative_number(weight_lb, "Part weight")
    if weight is not None and not math.isfinite(weight):
        raise ValueError("Part weight must be a finite number.")
    timestamp = now_iso()
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM parts WHERE id=? AND project_id=?",
            (part_id, project_id),
        ).fetchone():
            raise ValueError("That part no longer exists in this project.")
        conn.execute(
            "UPDATE parts SET weight_lb=?, updated_at=? WHERE id=? AND project_id=?",
            (weight, timestamp, part_id, project_id),
        )
    return timestamp


def set_process_part_option_handling_type(
    project_id: str,
    scenario_id: str,
    process_part_option_id: str,
    handling_type: str | None,
    fishbone_assignment_id: str | None = None,
) -> str:
    """Classify one scenario-specific Process part-use, or restore compatibility NULL."""
    normalized = _normalize_handling_type(handling_type)
    timestamp = now_iso()
    with connection() as conn:
        option = conn.execute(
            """SELECT option.id, option.part_id, group_row.section_id
               FROM process_part_options option
               JOIN process_part_groups group_row ON group_row.id=option.group_id
               WHERE option.id=? AND group_row.project_id=? AND group_row.scenario_id=?""",
            (process_part_option_id, project_id, scenario_id),
        ).fetchone()
        if not option:
            raise ValueError("That Process part-use no longer exists in this scenario.")
        normalized_assignment_id = _normalize_fishbone_assignment_id(
            fishbone_assignment_id
        )
        _validate_process_part_option_handling(
            conn,
            project_id=project_id,
            scenario_id=scenario_id,
            section_id=str(option["section_id"] or ""),
            process_part_option_id=process_part_option_id,
            part_id=str(option["part_id"]),
            handling_type=normalized,
            fishbone_assignment_id=normalized_assignment_id,
        )
        conn.execute(
            """UPDATE process_part_options
               SET handling_type=?, fishbone_assignment_id=?, updated_at=?
               WHERE id=?""",
            (
                normalized,
                normalized_assignment_id,
                timestamp,
                process_part_option_id,
            ),
        )
    return timestamp


def ergonomic_hazard_options(project_id: str) -> pd.DataFrame:
    columns = [
        "id",
        "project_id",
        "label",
        "active",
        "created_at",
        "updated_at",
        "selection_count",
    ]
    with connection() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ValueError("The selected project no longer exists.")
        rows = conn.execute(
            """SELECT option.*,
                      COUNT(selection.id) AS selection_count
               FROM ergonomic_hazard_options option
               LEFT JOIN ergonomics_review_hazard_selections selection
                 ON selection.hazard_option_id=option.id
               WHERE option.project_id=?
               GROUP BY option.id
               ORDER BY option.active DESC, option.label COLLATE NOCASE, option.id""",
            (project_id,),
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows], columns=columns)


def save_ergonomic_hazard_option_rows(project_id: str, edited: pd.DataFrame) -> dict:
    rows = edited.to_dict("records")
    labels = [str(row.get("label") or "").strip() for row in rows]
    if any(not label for label in labels):
        raise ValueError("Every Ergonomics hazard option requires a Label.")
    if len({label.casefold() for label in labels}) != len(labels):
        raise ValueError("Ergonomics hazard option labels must be unique within this project.")
    timestamp = now_iso()
    with connection() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ValueError("The selected project no longer exists.")
        existing = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM ergonomic_hazard_options WHERE project_id=?",
                (project_id,),
            ).fetchall()
        }
        supplied_ids = {
            str(row.get("id") or "").strip()
            for row in rows
            if str(row.get("id") or "").strip()
        }
        if set(existing) - supplied_ids:
            raise ValueError(
                "Remove Ergonomics hazard options through the confirmed deletion workflow."
            )
        created_ids: list[str] = []
        updated_ids: list[str] = []
        try:
            for row, label in zip(rows, labels):
                option_id = str(row.get("id") or "").strip()
                active = 1 if bool(row.get("active", True)) else 0
                if option_id:
                    if option_id not in existing:
                        raise ValueError(
                            "An Ergonomics hazard option changed or no longer exists. "
                            "Refresh and try again."
                        )
                    conn.execute(
                        """UPDATE ergonomic_hazard_options
                           SET label=?, active=?, updated_at=?
                           WHERE id=? AND project_id=?""",
                        (label, active, timestamp, option_id, project_id),
                    )
                    updated_ids.append(option_id)
                else:
                    option_id = str(uuid4())
                    conn.execute(
                        """INSERT INTO ergonomic_hazard_options
                           (id, project_id, label, active, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (option_id, project_id, label, active, timestamp, timestamp),
                    )
                    created_ids.append(option_id)
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "Ergonomics hazard option labels must be unique within this project."
            ) from exc
    return {
        "row_count": len(created_ids) + len(updated_ids),
        "created_ids": created_ids,
        "updated_ids": updated_ids,
        "timestamp": timestamp,
    }


def ergonomic_hazard_option_delete_impact(
    project_id: str, option_ids: list[str]
) -> dict:
    ids = list(dict.fromkeys(str(value).strip() for value in option_ids if str(value).strip()))
    if not ids:
        return {"option_count": 0, "selection_count": 0, "review_count": 0, "labels": []}
    placeholders = ",".join("?" for _ in ids)
    with connection() as conn:
        options = conn.execute(
            f"""SELECT id, label FROM ergonomic_hazard_options
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *ids),
        ).fetchall()
        if len(options) != len(ids):
            raise ValueError(
                "One or more Ergonomics hazard options changed. Refresh and try again."
            )
        selections = conn.execute(
            f"""SELECT ergonomics_review_id
                FROM ergonomics_review_hazard_selections
                WHERE project_id=? AND hazard_option_id IN ({placeholders})""",
            (project_id, *ids),
        ).fetchall()
    return {
        "option_count": len(ids),
        "selection_count": len(selections),
        "review_count": len({str(row["ergonomics_review_id"]) for row in selections}),
        "labels": [str(row["label"]) for row in options],
    }


def delete_ergonomic_hazard_options(project_id: str, option_ids: list[str]) -> dict:
    ids = list(dict.fromkeys(str(value).strip() for value in option_ids if str(value).strip()))
    impact = ergonomic_hazard_option_delete_impact(project_id, ids)
    timestamp = now_iso()
    if not ids:
        return impact | {"row_count": 0, "timestamp": timestamp}
    placeholders = ",".join("?" for _ in ids)
    with connection() as conn:
        cursor = conn.execute(
            f"""DELETE FROM ergonomic_hazard_options
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *ids),
        )
        if int(cursor.rowcount) != len(ids):
            raise ValueError(
                "One or more Ergonomics hazard options changed. Refresh and try again."
            )
    return impact | {"row_count": len(ids), "timestamp": timestamp}


def ergonomics_reviews(
    project_id: str,
    scenario_id: str,
    work_element_id: str | None = None,
) -> pd.DataFrame:
    columns = [
        "id",
        "project_id",
        "scenario_id",
        "work_element_id",
        "process_part_option_id",
        "status",
        "risk_classification",
        "reviewer",
        "notes",
        "requested_due_date",
        "created_at",
        "updated_at",
        "hazard_option_ids",
        "hazard_labels",
        "work_element_label",
        "pitch",
    ]
    params: tuple = (project_id, scenario_id)
    work_clause = ""
    if work_element_id:
        work_clause = " AND review.work_element_id=?"
        params = (*params, work_element_id)
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        review_rows = [
            dict(row)
            for row in conn.execute(
                f"""SELECT review.*,
                           COALESCE(
                               (SELECT NULLIF(TRIM(yamazumi.description), '')
                                FROM yamazumi_elements yamazumi
                                WHERE yamazumi.project_id=review.project_id
                                  AND yamazumi.process_element_id=review.work_element_id
                                ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                               NULLIF(TRIM(work.operation), ''),
                               ''
                           ) AS work_element_label,
                           COALESCE(work.station, '') AS pitch
                    FROM ergonomics_reviews review
                    LEFT JOIN work_elements work
                      ON work.id=review.work_element_id
                     AND work.project_id=review.project_id
                     AND work.scenario_id=review.scenario_id
                    WHERE review.project_id=? AND review.scenario_id=?{work_clause}
                    ORDER BY review.requested_due_date, review.created_at, review.id""",
                params,
            ).fetchall()
        ]
        review_ids = [str(row["id"]) for row in review_rows]
        selections_by_review: dict[str, list[dict]] = {review_id: [] for review_id in review_ids}
        if review_ids:
            placeholders = ",".join("?" for _ in review_ids)
            for selection in conn.execute(
                f"""SELECT selection.ergonomics_review_id, selection.hazard_option_id,
                            option.label
                     FROM ergonomics_review_hazard_selections selection
                     JOIN ergonomic_hazard_options option
                       ON option.id=selection.hazard_option_id
                     WHERE selection.ergonomics_review_id IN ({placeholders})
                     ORDER BY selection.sequence, option.label COLLATE NOCASE, selection.id""",
                tuple(review_ids),
            ).fetchall():
                selections_by_review[str(selection["ergonomics_review_id"])].append(
                    dict(selection)
                )
    for row in review_rows:
        selections = selections_by_review[str(row["id"])]
        row["hazard_option_ids"] = [str(item["hazard_option_id"]) for item in selections]
        row["hazard_labels"] = [str(item["label"]) for item in selections]
    return pd.DataFrame(review_rows, columns=columns)


def ergonomics_work_elements(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Return scenario Process steps with Yamazumi-description-first labels."""
    columns = ["id", "work_element_label", "pitch", "sequence"]
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        rows = conn.execute(
            """SELECT work.id,
                      COALESCE(
                          (SELECT NULLIF(TRIM(yamazumi.description), '')
                           FROM yamazumi_elements yamazumi
                           WHERE yamazumi.project_id=work.project_id
                             AND yamazumi.process_element_id=work.id
                           ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                          NULLIF(TRIM(work.operation), ''),
                          ''
                      ) AS work_element_label,
                      COALESCE(work.station, '') AS pitch,
                      work.sequence
               FROM work_elements work
               WHERE work.project_id=? AND work.scenario_id=?
               ORDER BY work.sequence, work.id""",
            (project_id, scenario_id),
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows], columns=columns)


def process_ergonomics_risk_work_element_ids(
    project_id: str, scenario_id: str
) -> set[str]:
    """Return Process steps with a qualifying live Ergonomics risk review."""
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        rows = conn.execute(
            """SELECT DISTINCT review.work_element_id
               FROM ergonomics_reviews review
               JOIN work_elements work
                 ON work.id=review.work_element_id
                AND work.project_id=review.project_id
                AND work.scenario_id=review.scenario_id
               WHERE review.project_id=? AND review.scenario_id=?
                 AND review.status IN ('Open', 'Pending')
                 AND review.risk_classification IN ('Red', 'Favorable Red')""",
            (project_id, scenario_id),
        ).fetchall()
    return {str(row["work_element_id"]) for row in rows}


def ergonomics_review_audit_history(
    project_id: str, scenario_id: str, limit: int = 50
) -> pd.DataFrame:
    """Return only audit entries belonging to the active Ergonomics scenario."""
    rows = query(
        """SELECT action, row_count, editor_name, details, created_at
           FROM audit_log
           WHERE project_id=? AND table_name='Ergonomics reviews'
             AND json_extract(details, '$.scenario_id')=?
           ORDER BY created_at DESC LIMIT ?""",
        (project_id, scenario_id, int(limit)),
    )
    return pd.DataFrame(rows)


def _ergonomics_review_has_real_content(values: dict) -> bool:
    """Return whether a review contains content beyond an untouched placeholder."""
    return bool(
        str(values.get("status") or "Started").strip() != "Started"
        or str(values.get("risk_classification") or "Not yet assessed").strip()
        != "Not yet assessed"
        or str(values.get("reviewer") or "").strip()
        or str(values.get("notes") or "").strip()
        or str(values.get("requested_due_date") or "").strip()
        or [value for value in values.get("hazard_option_ids", []) if str(value).strip()]
    )


def _ergonomics_review_merge_plan(
    rows: list[dict], link_candidate_ids: set[str]
) -> dict:
    rows_by_id = {str(row.get("id") or "").strip(): row for row in rows}
    if "" in rows_by_id:
        raise ValueError("Every Ergonomics review requires a stable identifier before saving.")
    silent_merges: list[dict] = []
    conflicts: list[dict] = []
    seen_targets: dict[str, str] = {}
    for candidate_id in link_candidate_ids:
        candidate = rows_by_id.get(candidate_id)
        if candidate is None:
            raise ValueError("An Ergonomics review changed. Refresh and try again.")
        work_element_id = str(candidate.get("work_element_id") or "").strip()
        if not work_element_id:
            continue
        previous_candidate = seen_targets.get(work_element_id)
        if previous_candidate and previous_candidate != candidate_id:
            raise ValueError(
                "Link one Ergonomics review at a time to the same Work Element."
            )
        seen_targets[work_element_id] = candidate_id
        others = [
            row
            for row in rows
            if str(row.get("id") or "").strip() != candidate_id
            and str(row.get("work_element_id") or "").strip() == work_element_id
        ]
        if not others:
            continue
        if len(others) > 1:
            raise ValueError(
                "This Work Element has more than one existing Ergonomics review. "
                "Resolve those reviews before linking another one."
            )
        existing = others[0]
        merge = {
            "work_element_id": work_element_id,
            "candidate_id": candidate_id,
            "existing_id": str(existing["id"]),
            "candidate": dict(candidate),
            "existing": dict(existing),
        }
        if _ergonomics_review_has_real_content(existing):
            conflicts.append(merge)
        else:
            silent_merges.append(merge)
    return {"silent_merges": silent_merges, "conflicts": conflicts}


def ergonomics_review_save_plan(
    project_id: str,
    scenario_id: str,
    rows: list[dict],
    link_candidate_ids: list[str],
) -> dict:
    """Describe automatic and confirmation-required review merges without writing."""
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
    return _ergonomics_review_merge_plan(
        [dict(row) for row in rows],
        {str(value).strip() for value in link_candidate_ids if str(value).strip()},
    )


def save_ergonomics_review_rows(
    project_id: str,
    scenario_id: str,
    rows: list[dict],
    *,
    link_candidate_ids: list[str] | None = None,
    merge_survivors: dict[str, str] | None = None,
    editor_name: str = "",
) -> dict:
    """Save the complete review table and apply approved link merges atomically."""
    normalized_rows: list[dict] = []
    for values in rows:
        review_id = str(values.get("id") or "").strip()
        if not review_id:
            raise ValueError("Every Ergonomics review requires a stable identifier before saving.")
        status = str(values.get("status") or "Started").strip()
        if status not in ERGONOMICS_REVIEW_STATUSES:
            raise ValueError("Choose a valid Ergonomics review status.")
        risk_classification = str(
            values.get("risk_classification") or "Not yet assessed"
        ).strip()
        if risk_classification not in ERGONOMICS_RISK_CLASSIFICATIONS:
            raise ValueError("Choose a valid Ergonomics risk classification.")
        normalized_rows.append(
            {
                "id": review_id,
                "work_element_id": (
                    str(values.get("work_element_id") or "").strip() or None
                ),
                "process_part_option_id": (
                    str(values.get("process_part_option_id") or "").strip() or None
                ),
                "status": status,
                "risk_classification": risk_classification,
                "reviewer": str(values.get("reviewer") or "").strip(),
                "notes": str(values.get("notes") or "").strip(),
                "requested_due_date": (
                    str(values.get("requested_due_date") or "").strip() or None
                ),
                "hazard_option_ids": list(
                    dict.fromkeys(
                        str(value).strip()
                        for value in values.get("hazard_option_ids", [])
                        if str(value).strip()
                    )
                ),
            }
        )
    ids = [row["id"] for row in normalized_rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Every Ergonomics review must have a unique stable identifier.")

    candidate_ids = {
        str(value).strip()
        for value in (link_candidate_ids or [])
        if str(value).strip()
    }
    decisions = {
        str(candidate_id).strip(): str(survivor_id).strip()
        for candidate_id, survivor_id in (merge_survivors or {}).items()
    }
    timestamp = now_iso()
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        existing_rows = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                """SELECT * FROM ergonomics_reviews
                   WHERE project_id=? AND scenario_id=?""",
                (project_id, scenario_id),
            ).fetchall()
        }
        if set(existing_rows) - set(ids):
            raise ValueError(
                "Remove Ergonomics reviews through the confirmed deletion workflow."
            )

        plan = _ergonomics_review_merge_plan(normalized_rows, candidate_ids)
        discard_ids = {
            str(merge["existing_id"]) for merge in plan["silent_merges"]
        }
        merge_audit: list[dict] = [
            {
                "work_element_id": merge["work_element_id"],
                "surviving_review_id": merge["candidate_id"],
                "discarded_review_id": merge["existing_id"],
                "confirmation_required": False,
            }
            for merge in plan["silent_merges"]
        ]
        for conflict in plan["conflicts"]:
            candidate_id = str(conflict["candidate_id"])
            existing_id = str(conflict["existing_id"])
            survivor_id = decisions.get(candidate_id)
            if survivor_id not in {candidate_id, existing_id}:
                raise ValueError(
                    "Confirm which Ergonomics review should survive the link before saving."
                )
            discarded_id = existing_id if survivor_id == candidate_id else candidate_id
            discard_ids.add(discarded_id)
            merge_audit.append(
                {
                    "work_element_id": conflict["work_element_id"],
                    "surviving_review_id": survivor_id,
                    "discarded_review_id": discarded_id,
                    "confirmation_required": True,
                }
            )

        rows_to_save = [
            row for row in normalized_rows if row["id"] not in discard_ids
        ]
        existing_hazards_by_review = {
            review_id: {
                str(selection["hazard_option_id"]): str(selection["id"])
                for selection in conn.execute(
                    """SELECT id, hazard_option_id
                       FROM ergonomics_review_hazard_selections
                       WHERE ergonomics_review_id=?""",
                    (review_id,),
                ).fetchall()
            }
            for review_id in ids
        }
        for row in rows_to_save:
            work_element_id = row["work_element_id"]
            if work_element_id and not conn.execute(
                """SELECT 1 FROM work_elements
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (work_element_id, project_id, scenario_id),
            ).fetchone():
                raise ValueError(
                    "That Process at a Glance Work Element no longer exists."
                )
            process_part_option_id = row["process_part_option_id"]
            if process_part_option_id and not work_element_id:
                raise ValueError(
                    "A review linked to a Process part-use must also be linked to its Work Element."
                )
            if process_part_option_id and not conn.execute(
                """SELECT 1
                   FROM process_part_options option
                   JOIN process_part_groups group_row ON group_row.id=option.group_id
                   WHERE option.id=? AND group_row.project_id=?
                     AND group_row.scenario_id=? AND group_row.work_element_id=?""",
                (
                    process_part_option_id,
                    project_id,
                    scenario_id,
                    work_element_id,
                ),
            ).fetchone():
                raise ValueError(
                    "The selected Process part-use does not belong to this Work Element and scenario."
                )

            hazard_ids = row["hazard_option_ids"]
            if hazard_ids:
                placeholders = ",".join("?" for _ in hazard_ids)
                available = {
                    str(option["id"]): int(option["active"])
                    for option in conn.execute(
                        f"""SELECT id, active FROM ergonomic_hazard_options
                            WHERE project_id=? AND id IN ({placeholders})""",
                        (project_id, *hazard_ids),
                    ).fetchall()
                }
                if set(available) != set(hazard_ids):
                    raise ValueError(
                        "One or more selected Ergonomics hazards no longer exist."
                    )
                existing_hazard_ids = set(
                    existing_hazards_by_review.get(row["id"], {})
                )
                if any(
                    not active and option_id not in existing_hazard_ids
                    for option_id, active in available.items()
                ):
                    raise ValueError(
                        "Inactive Ergonomics hazards cannot be newly selected."
                    )

        if discard_ids:
            placeholders = ",".join("?" for _ in discard_ids)
            conn.execute(
                f"""DELETE FROM ergonomics_reviews
                    WHERE project_id=? AND scenario_id=?
                      AND id IN ({placeholders})""",
                (project_id, scenario_id, *sorted(discard_ids)),
            )

        created_ids: list[str] = []
        updated_ids: list[str] = []
        for row in rows_to_save:
            review_id = row["id"]
            existing = existing_rows.get(review_id)
            if existing:
                conn.execute(
                    """UPDATE ergonomics_reviews
                       SET work_element_id=?, process_part_option_id=?, status=?,
                           risk_classification=?, reviewer=?, notes=?,
                           requested_due_date=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=?""",
                    (
                        row["work_element_id"],
                        row["process_part_option_id"],
                        row["status"],
                        row["risk_classification"],
                        row["reviewer"],
                        row["notes"],
                        row["requested_due_date"],
                        timestamp,
                        review_id,
                        project_id,
                        scenario_id,
                    ),
                )
                updated_ids.append(review_id)
            else:
                conn.execute(
                    """INSERT INTO ergonomics_reviews
                       (id, project_id, scenario_id, work_element_id,
                        process_part_option_id, status, reviewer, notes,
                        requested_due_date, created_at, updated_at,
                        risk_classification)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        review_id,
                        project_id,
                        scenario_id,
                        row["work_element_id"],
                        row["process_part_option_id"],
                        row["status"],
                        row["reviewer"],
                        row["notes"],
                        row["requested_due_date"],
                        timestamp,
                        timestamp,
                        row["risk_classification"],
                    ),
                )
                created_ids.append(review_id)
            existing_selections = existing_hazards_by_review.get(review_id, {})
            conn.execute(
                """DELETE FROM ergonomics_review_hazard_selections
                   WHERE ergonomics_review_id=?""",
                (review_id,),
            )
            for index, hazard_option_id in enumerate(
                row["hazard_option_ids"], start=1
            ):
                conn.execute(
                    """INSERT INTO ergonomics_review_hazard_selections
                       (id, project_id, scenario_id, ergonomics_review_id,
                        hazard_option_id, sequence, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        existing_selections.get(hazard_option_id, str(uuid4())),
                        project_id,
                        scenario_id,
                        review_id,
                        hazard_option_id,
                        index * 10,
                        timestamp,
                        timestamp,
                    ),
                )

        if merge_audit:
            record_audit_event(
                project_id,
                "Ergonomics reviews",
                "Merge reviews",
                len(merge_audit),
                editor_name,
                {"scenario_id": scenario_id, "merges": merge_audit},
                _conn=conn,
            )
    return {
        "row_count": len(rows_to_save),
        "created_ids": created_ids,
        "updated_ids": updated_ids,
        "discarded_ids": sorted(discard_ids),
        "merges": merge_audit,
        "timestamp": timestamp,
    }


def save_ergonomics_review(
    project_id: str,
    scenario_id: str,
    values: dict,
) -> dict:
    review_id = str(values.get("id") or "").strip() or str(uuid4())
    work_element_id = str(values.get("work_element_id") or "").strip() or None
    process_part_option_id = str(values.get("process_part_option_id") or "").strip() or None
    status = str(values.get("status") or "Started").strip()
    if status not in ERGONOMICS_REVIEW_STATUSES:
        raise ValueError("Choose a valid Ergonomics review status.")
    risk_classification = str(
        values.get("risk_classification") or "Not yet assessed"
    ).strip()
    if risk_classification not in ERGONOMICS_RISK_CLASSIFICATIONS:
        raise ValueError("Choose a valid Ergonomics risk classification.")
    reviewer = str(values.get("reviewer") or "").strip()
    notes = str(values.get("notes") or "").strip()
    requested_due_date = str(values.get("requested_due_date") or "").strip() or None
    hazard_option_ids = list(
        dict.fromkeys(
            str(value).strip()
            for value in values.get("hazard_option_ids", [])
            if str(value).strip()
        )
    )
    timestamp = now_iso()
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        if work_element_id and not conn.execute(
            """SELECT 1 FROM work_elements
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (work_element_id, project_id, scenario_id),
        ).fetchone():
            raise ValueError("That Process at a Glance Work Element no longer exists.")
        if process_part_option_id and not work_element_id:
            raise ValueError(
                "A review linked to a Process part-use must also be linked to its Work Element."
            )
        if process_part_option_id and not conn.execute(
            """SELECT 1
               FROM process_part_options option
               JOIN process_part_groups group_row ON group_row.id=option.group_id
               WHERE option.id=? AND group_row.project_id=?
                 AND group_row.scenario_id=? AND group_row.work_element_id=?""",
            (process_part_option_id, project_id, scenario_id, work_element_id),
        ).fetchone():
            raise ValueError(
                "The selected Process part-use does not belong to this Work Element and scenario."
            )
        existing_review = conn.execute(
            """SELECT * FROM ergonomics_reviews
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (review_id, project_id, scenario_id),
        ).fetchone()
        existing_hazard_ids = {
            str(row["hazard_option_id"])
            for row in conn.execute(
                """SELECT hazard_option_id
                   FROM ergonomics_review_hazard_selections
                   WHERE ergonomics_review_id=?""",
                (review_id,),
            ).fetchall()
        }
        if hazard_option_ids:
            placeholders = ",".join("?" for _ in hazard_option_ids)
            options = {
                str(row["id"]): int(row["active"])
                for row in conn.execute(
                    f"""SELECT id, active FROM ergonomic_hazard_options
                        WHERE project_id=? AND id IN ({placeholders})""",
                    (project_id, *hazard_option_ids),
                ).fetchall()
            }
            if set(options) != set(hazard_option_ids):
                raise ValueError("One or more selected Ergonomics hazards no longer exist.")
            inactive_new = {
                option_id
                for option_id, active in options.items()
                if not active and option_id not in existing_hazard_ids
            }
            if inactive_new:
                raise ValueError("Inactive Ergonomics hazards cannot be newly selected.")
        if existing_review:
            conn.execute(
                """UPDATE ergonomics_reviews
                   SET work_element_id=?, process_part_option_id=?, status=?,
                       risk_classification=?, reviewer=?, notes=?,
                       requested_due_date=?, updated_at=?
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (
                    work_element_id,
                    process_part_option_id,
                    status,
                    risk_classification,
                    reviewer,
                    notes,
                    requested_due_date,
                    timestamp,
                    review_id,
                    project_id,
                    scenario_id,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO ergonomics_reviews
                   (id, project_id, scenario_id, work_element_id,
                    process_part_option_id, status, reviewer, notes,
                    requested_due_date, created_at, updated_at,
                    risk_classification)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    review_id,
                    project_id,
                    scenario_id,
                    work_element_id,
                    process_part_option_id,
                    status,
                    reviewer,
                    notes,
                    requested_due_date,
                    timestamp,
                    timestamp,
                    risk_classification,
                ),
            )
        existing_selections = {
            str(row["hazard_option_id"]): str(row["id"])
            for row in conn.execute(
                """SELECT id, hazard_option_id
                   FROM ergonomics_review_hazard_selections
                   WHERE ergonomics_review_id=?""",
                (review_id,),
            ).fetchall()
        }
        if hazard_option_ids:
            placeholders = ",".join("?" for _ in hazard_option_ids)
            conn.execute(
                f"""DELETE FROM ergonomics_review_hazard_selections
                    WHERE ergonomics_review_id=?
                      AND hazard_option_id NOT IN ({placeholders})""",
                (review_id, *hazard_option_ids),
            )
        else:
            conn.execute(
                "DELETE FROM ergonomics_review_hazard_selections WHERE ergonomics_review_id=?",
                (review_id,),
            )
        for index, hazard_option_id in enumerate(hazard_option_ids, start=1):
            selection_id = existing_selections.get(hazard_option_id, str(uuid4()))
            conn.execute(
                """INSERT INTO ergonomics_review_hazard_selections
                   (id, project_id, scenario_id, ergonomics_review_id,
                    hazard_option_id, sequence, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ergonomics_review_id, hazard_option_id) DO UPDATE SET
                     sequence=excluded.sequence, updated_at=excluded.updated_at""",
                (
                    selection_id,
                    project_id,
                    scenario_id,
                    review_id,
                    hazard_option_id,
                    index * 10,
                    timestamp,
                    timestamp,
                ),
            )
    return {"id": review_id, "row_count": 1, "timestamp": timestamp}


def delete_ergonomics_reviews(
    project_id: str, scenario_id: str, review_ids: list[str]
) -> dict:
    ids = list(dict.fromkeys(str(value).strip() for value in review_ids if str(value).strip()))
    timestamp = now_iso()
    if not ids:
        return {"row_count": 0, "hazard_selection_count": 0, "timestamp": timestamp}
    placeholders = ",".join("?" for _ in ids)
    with connection() as conn:
        reviews = conn.execute(
            f"""SELECT id FROM ergonomics_reviews
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        ).fetchall()
        if len(reviews) != len(ids):
            raise ValueError("One or more Ergonomics reviews changed. Refresh and try again.")
        selection_count = int(
            conn.execute(
                f"""SELECT COUNT(*) FROM ergonomics_review_hazard_selections
                    WHERE project_id=? AND scenario_id=?
                      AND ergonomics_review_id IN ({placeholders})""",
                (project_id, scenario_id, *ids),
            ).fetchone()[0]
        )
        cursor = conn.execute(
            f"""DELETE FROM ergonomics_reviews
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        )
        if int(cursor.rowcount) != len(ids):
            raise ValueError("One or more Ergonomics reviews changed. Refresh and try again.")
    return {
        "row_count": len(ids),
        "hazard_selection_count": selection_count,
        "timestamp": timestamp,
    }


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
            "feeds_into_pitch_id": pd.Series(dtype="string"),
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
            "feeds_into_pitch_id": pd.Series(dtype="string"),
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
                  a.section_id,
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
            "section_id": pd.Series(dtype="string"),
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
            """SELECT p.id, p.area_id, p.pitch_number, p.pitch_name, p.pitch_type,
                      p.feeds_into_pitch_id, p.model_variants
               FROM yamazumi_pitches p
               JOIN yamazumi_areas a ON a.id=p.area_id
               WHERE p.project_id=? AND a.scenario_id=?""", (project_id, scenario_id)
        ).fetchall()
        for pitch in pitches:
            variants = json.loads(pitch["model_variants"] or "[]")
            normalized = list(dict.fromkeys(mapping.get(str(value), str(value)) for value in variants))
            if normalized != variants:
                _require_yamazumi_feed_target_for_pitch_write(
                    conn, project_id, pitch
                )
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
            conn.execute(
                """UPDATE yamazumi_pitches SET feeds_into_pitch_id=NULL
                   WHERE project_id=? AND area_id=?""",
                (project_id, area_id),
            )
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
                """UPDATE yamazumi_pitches SET feeds_into_pitch_id=NULL
                   WHERE project_id=? AND area_id IN (
                       SELECT id FROM yamazumi_areas
                       WHERE project_id=? AND scenario_id=?
                   )""",
                (project_id, project_id, scenario_id),
            )
            conn.execute(
                "DELETE FROM yamazumi_areas WHERE project_id=? AND scenario_id=?",
                (project_id, scenario_id),
            )
    return counts


def upsert_yamazumi_area(
    project_id: str, scenario_id: str, name: str,
    section_id: str | None = None, takt_override_s: float | None = None,
    *, _conn: sqlite3.Connection | None = None,
) -> str:
    name = str(name or "").strip()
    if not name:
        raise ValueError("Yamazumi area name is required.")
    timestamp = now_iso()
    context = nullcontext(_conn) if _conn is not None else connection()
    with context as conn:
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


def yamazumi_pitch_label(pitch_number: object, pitch_name: object = "") -> str:
    """Return the human-readable pitch identity used in validation and UI."""
    number = str(pitch_number or "").strip() or "Unnamed pitch"
    name = str(pitch_name or "").strip()
    return f"{number} — {name}" if name else number


def _yamazumi_pitch_address_conflict_rows(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        """WITH duplicate_addresses AS (
               SELECT TRIM(pitch.pitch_number) AS normalized_address
               FROM yamazumi_pitches pitch
               JOIN yamazumi_areas area ON area.id=pitch.area_id
               WHERE pitch.project_id=? AND area.scenario_id=?
               GROUP BY TRIM(pitch.pitch_number) COLLATE NOCASE
               HAVING COUNT(*)>1
           )
           SELECT pitch.id, pitch.area_id, TRIM(pitch.pitch_number) AS pitch_number,
                  pitch.pitch_name, area.name AS area_name
           FROM yamazumi_pitches pitch
           JOIN yamazumi_areas area ON area.id=pitch.area_id
           JOIN duplicate_addresses duplicate
             ON TRIM(pitch.pitch_number)=duplicate.normalized_address COLLATE NOCASE
           WHERE pitch.project_id=? AND area.scenario_id=?
           ORDER BY TRIM(pitch.pitch_number) COLLATE NOCASE,
                    area.name COLLATE NOCASE, pitch.sequence, pitch.id""",
        (project_id, scenario_id, project_id, scenario_id),
    ).fetchall()


def yamazumi_pitch_address_conflicts(
    project_id: str, scenario_id: str
) -> pd.DataFrame:
    """Return every pitch participating in a scenario-wide address conflict."""
    with connection() as conn:
        rows = _yamazumi_pitch_address_conflict_rows(
            conn, project_id, scenario_id
        )
    columns = ["id", "area_id", "pitch_number", "pitch_name", "area_name"]
    if not rows:
        return pd.DataFrame(
            {
                column: pd.Series(dtype="string")
                for column in columns
            }
        )
    return pd.DataFrame([dict(row) for row in rows], columns=columns).astype(
        "string"
    )


def _yamazumi_pitch_address_owner(
    conn: sqlite3.Connection,
    project_id: str,
    area_id: str,
    pitch_number: str,
    *,
    exclude_pitch_id: str | None = None,
) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT existing.id, existing_area.name AS area_name
           FROM yamazumi_pitches existing
           JOIN yamazumi_areas existing_area ON existing_area.id=existing.area_id
           JOIN yamazumi_areas requested_area ON requested_area.id=?
           WHERE existing.project_id=?
             AND existing_area.scenario_id IS requested_area.scenario_id
             AND TRIM(existing.pitch_number)=TRIM(?) COLLATE NOCASE
             AND (? IS NULL OR existing.id<>?)
           ORDER BY existing_area.name COLLATE NOCASE, existing.sequence
           LIMIT 1""",
        (
            area_id,
            project_id,
            pitch_number,
            exclude_pitch_id,
            exclude_pitch_id,
        ),
    ).fetchone()


def _validate_yamazumi_pitch_address_available(
    conn: sqlite3.Connection,
    project_id: str,
    area_id: str,
    pitch_number: str,
    *,
    exclude_pitch_id: str | None = None,
) -> None:
    owner = _yamazumi_pitch_address_owner(
        conn,
        project_id,
        area_id,
        pitch_number,
        exclude_pitch_id=exclude_pitch_id,
    )
    if owner:
        raise ValueError(
            f"Pitch address {pitch_number} already exists in Yamazumi area "
            f"{owner['area_name']} in this planning scenario. Pitch addresses "
            "must be unique across the scenario."
        )


def _validate_yamazumi_scenario_pitch_addresses(
    conn: sqlite3.Connection, project_id: str, scenario_id: str
) -> None:
    conflicts = _yamazumi_pitch_address_conflict_rows(
        conn, project_id, scenario_id
    )
    if not conflicts:
        return
    addresses = list(
        dict.fromkeys(str(row["pitch_number"]) for row in conflicts)
    )
    raise ValueError(
        "Resolve duplicate pitch addresses in this planning scenario before "
        f"saving: {', '.join(addresses)}."
    )


def _validate_yamazumi_pitch_conflict_progress(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    before_conflicts: list[sqlite3.Row],
) -> None:
    """Allow a legacy-conflict correction while rejecting unchanged/new conflicts."""
    after_conflicts = _yamazumi_pitch_address_conflict_rows(
        conn, project_id, scenario_id
    )
    if not after_conflicts:
        return
    before_ids = {str(row["id"]) for row in before_conflicts}
    after_ids = {str(row["id"]) for row in after_conflicts}
    if before_ids and after_ids < before_ids:
        return
    addresses = list(
        dict.fromkeys(str(row["pitch_number"]) for row in after_conflicts)
    )
    raise ValueError(
        "Resolve duplicate pitch addresses in this planning scenario before "
        f"saving: {', '.join(addresses)}."
    )


def yamazumi_pitch_feed_target_status(
    pitch_type: object, feeds_into_pitch_id: object
) -> str:
    """Return the visible compatibility-null indicator for feeder pitches."""
    normalized_type = str(pitch_type or "Pitch").strip().title()
    target_id = (
        ""
        if feeds_into_pitch_id is None or pd.isna(feeds_into_pitch_id)
        else str(feeds_into_pitch_id).strip()
    )
    if normalized_type in YAMAZUMI_FEEDER_PITCH_TYPES and not target_id:
        return "Feed target required"
    return ""


def _normalize_yamazumi_feed_target(
    pitch_type: str,
    feeds_into_pitch_id: object,
    *,
    require_target: bool,
    pitch_label: str,
) -> str | None:
    target_id = (
        None
        if feeds_into_pitch_id is None or pd.isna(feeds_into_pitch_id)
        else str(feeds_into_pitch_id).strip() or None
    )
    if pitch_type not in YAMAZUMI_FEEDER_PITCH_TYPES:
        return None
    if require_target and target_id is None:
        raise ValueError(
            f"Feeds into pitch is required for {pitch_type} pitch {pitch_label}."
        )
    return target_id


def _validate_yamazumi_pitch_feeds(
    conn: sqlite3.Connection, project_id: str, area_id: str
) -> None:
    """Validate the complete directed feeds-into graph for one Yamazumi area."""
    rows = conn.execute(
        """SELECT id, project_id, area_id, pitch_number, pitch_name, pitch_type,
                  feeds_into_pitch_id
           FROM yamazumi_pitches
           WHERE project_id=? AND area_id=?""",
        (project_id, area_id),
    ).fetchall()
    pitch_by_id = {str(row["id"]): row for row in rows}
    target_by_source: dict[str, str] = {}
    label_by_id = {
        pitch_id: yamazumi_pitch_label(row["pitch_number"], row["pitch_name"])
        for pitch_id, row in pitch_by_id.items()
    }
    for source_id, source in pitch_by_id.items():
        pitch_type = str(source["pitch_type"] or "Pitch").strip().title()
        target_id = str(source["feeds_into_pitch_id"] or "").strip()
        if not target_id:
            continue
        if pitch_type not in YAMAZUMI_FEEDER_PITCH_TYPES:
            raise ValueError(
                f"Pitch {label_by_id[source_id]} cannot have a feed target when its type is {pitch_type}."
            )
        if source_id == target_id:
            raise ValueError(f"Pitch {label_by_id[source_id]} cannot feed into itself.")
        target = conn.execute(
            """SELECT p.id, p.project_id, p.area_id, a.scenario_id
               FROM yamazumi_pitches p
               JOIN yamazumi_areas a ON a.id=p.area_id
               WHERE p.id=?""",
            (target_id,),
        ).fetchone()
        if not target:
            raise ValueError(
                f"The feed target selected for pitch {label_by_id[source_id]} no longer exists."
            )
        if str(target["project_id"]) != project_id or str(target["area_id"]) != area_id:
            raise ValueError(
                f"Pitch {label_by_id[source_id]} must feed into another pitch in the same Yamazumi area."
            )
        target_by_source[source_id] = target_id

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(pitch_id: str, path: list[str]) -> None:
        if pitch_id in visiting:
            cycle_start = path.index(pitch_id)
            cycle = path[cycle_start:]
            labels = " → ".join(label_by_id.get(value, value) for value in cycle)
            raise ValueError(f"Yamazumi pitch feeds-into relationships cannot contain a cycle: {labels}.")
        if pitch_id in visited:
            return
        visiting.add(pitch_id)
        target_id = target_by_source.get(pitch_id)
        if target_id:
            visit(target_id, [*path, target_id])
        visiting.remove(pitch_id)
        visited.add(pitch_id)

    for source_id in target_by_source:
        visit(source_id, [source_id])


def _validate_yamazumi_feed_target_context(
    conn: sqlite3.Connection,
    project_id: str,
    area_id: str,
    source_id: str,
    source_label: str,
    target_id: str | None,
) -> None:
    if not target_id:
        return
    if source_id == target_id:
        raise ValueError(f"Pitch {source_label} cannot feed into itself.")
    target = conn.execute(
        "SELECT project_id, area_id FROM yamazumi_pitches WHERE id=?",
        (target_id,),
    ).fetchone()
    if not target:
        raise ValueError(
            f"The feed target selected for pitch {source_label} no longer exists."
        )
    if str(target["project_id"]) != project_id or str(target["area_id"]) != area_id:
        raise ValueError(
            f"Pitch {source_label} must feed into another pitch in the same Yamazumi area."
        )


def _require_yamazumi_feed_target_for_pitch_write(
    conn: sqlite3.Connection, project_id: str, pitch: sqlite3.Row
) -> None:
    pitch_type = str(pitch["pitch_type"] or "Pitch").strip().title()
    label = yamazumi_pitch_label(pitch["pitch_number"], pitch["pitch_name"])
    target_id = _normalize_yamazumi_feed_target(
        pitch_type,
        pitch["feeds_into_pitch_id"],
        require_target=True,
        pitch_label=label,
    )
    _validate_yamazumi_feed_target_context(
        conn,
        project_id,
        str(pitch["area_id"]),
        str(pitch["id"]),
        label,
        target_id,
    )


def _yamazumi_pitch_reference_blockers(
    conn: sqlite3.Connection,
    project_id: str,
    area_id: str,
    pitch_ids: set[str],
) -> list[dict]:
    if not pitch_ids:
        return []
    placeholders = ",".join("?" for _ in pitch_ids)
    return [
        dict(row)
        for row in conn.execute(
            f"""SELECT source.id AS source_pitch_id,
                       source.pitch_number AS source_pitch_number,
                       source.pitch_name AS source_pitch_name,
                       target.id AS target_pitch_id,
                       target.pitch_number AS target_pitch_number,
                       target.pitch_name AS target_pitch_name
                FROM yamazumi_pitches source
                JOIN yamazumi_pitches target ON target.id=source.feeds_into_pitch_id
                WHERE target.project_id=? AND target.area_id=?
                  AND target.id IN ({placeholders})
                  AND source.id NOT IN ({placeholders})
                ORDER BY target.sequence, source.sequence""",
            (project_id, area_id, *pitch_ids, *pitch_ids),
        ).fetchall()
    ]


def yamazumi_pitch_delete_blockers(
    project_id: str, area_id: str, pitch_ids: list[str]
) -> list[dict]:
    """Return feeder pitches that must be re-pointed before target deletion."""
    normalized_ids = {str(value).strip() for value in pitch_ids if str(value).strip()}
    with connection() as conn:
        return _yamazumi_pitch_reference_blockers(
            conn, project_id, area_id, normalized_ids
        )


def _raise_yamazumi_pitch_reference_blockers(blockers: list[dict]) -> None:
    if not blockers:
        return
    relationships = ", ".join(
        f"{yamazumi_pitch_label(row['source_pitch_number'], row['source_pitch_name'])} → "
        f"{yamazumi_pitch_label(row['target_pitch_number'], row['target_pitch_name'])}"
        for row in blockers
    )
    raise ValueError(
        "Re-point these feeder pitches or change their pitch type before deleting the target: "
        + relationships
        + "."
    )


def add_yamazumi_pitch(
    project_id: str,
    area_id: str,
    pitch_number: str,
    pitch_name: str = "",
    status: str = "Active",
    model_variants: list[str] | None = None,
    pitch_type: str = "Pitch",
    feeds_into_pitch_id: str | None = None,
) -> str:
    """Add one physical pitch address to a Yamazumi area."""
    pitch_number = str(pitch_number or "").strip()
    if not pitch_number:
        raise ValueError("Pitch address is required.")
    status = str(status or "Active").title()
    if status not in {"Active", "Blocked", "Open"}:
        raise ValueError("Pitch status must be Active, Blocked, or Open.")
    pitch_type = str(pitch_type or "Pitch").strip().title()
    if pitch_type not in YAMAZUMI_PITCH_TYPES:
        raise ValueError("Choose a valid pitch type.")
    feed_target_id = _normalize_yamazumi_feed_target(
        pitch_type,
        feeds_into_pitch_id,
        require_target=True,
        pitch_label=pitch_number,
    )
    timestamp = now_iso()
    variants = list(dict.fromkeys(str(value).strip() for value in (model_variants or ["Base"]) if str(value).strip()))
    if not variants:
        raise ValueError("Choose at least one model variant for the pitch.")
    pitch_id = str(uuid4())
    try:
        with connection() as conn:
            valid_area = conn.execute(
                "SELECT scenario_id FROM yamazumi_areas WHERE id=? AND project_id=?",
                (area_id, project_id),
            ).fetchone()
            if not valid_area:
                raise ValueError("That Yamazumi area no longer exists.")
            before_conflicts = _yamazumi_pitch_address_conflict_rows(
                conn, project_id, str(valid_area["scenario_id"])
            )
            _validate_yamazumi_pitch_address_available(
                conn, project_id, area_id, pitch_number
            )
            _validate_yamazumi_feed_target_context(
                conn, project_id, area_id, pitch_id, pitch_number, feed_target_id
            )
            sequence = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 10 FROM yamazumi_pitches WHERE project_id=? AND area_id=?",
                (project_id, area_id),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO yamazumi_pitches
                (id, project_id, area_id, pitch_number, pitch_name, status, sequence,
                 model_variants, pitch_type, feeds_into_pitch_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pitch_id, project_id, area_id, pitch_number, str(pitch_name or "").strip(),
                 status, sequence, json.dumps(variants), pitch_type, feed_target_id, timestamp),
            )
            _validate_yamazumi_pitch_feeds(conn, project_id, area_id)
            _validate_yamazumi_pitch_conflict_progress(
                conn,
                project_id,
                str(valid_area["scenario_id"]),
                before_conflicts,
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(
            f"Pitch address {pitch_number} already exists in this planning scenario."
        ) from exc
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
    element_id = str(uuid4())
    timestamp = now_iso()
    with connection() as conn:
        if pitch_id:
            active_pitch = conn.execute(
                """SELECT id, area_id, pitch_number, pitch_name, pitch_type,
                          feeds_into_pitch_id, model_variants
                   FROM yamazumi_pitches
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
                _require_yamazumi_feed_target_for_pitch_write(
                    conn, project_id, active_pitch
                )
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
                time_s, work_region, sequence, source, process_sync_status, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Interactive board', 'Needs IE review', ?)""",
            (
                element_id, project_id, area_id, pitch_id,
                primary_variant, json.dumps(selected_variants),
                work_type, description, time_s,
                str(values.get("work_region") or "None").strip(), sequence, timestamp,
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
    if pitch_type not in YAMAZUMI_PITCH_TYPES:
        raise ValueError("Choose a valid pitch type.")
    feed_target_id = _normalize_yamazumi_feed_target(
        pitch_type,
        values.get("feeds_into_pitch_id"),
        require_target=True,
        pitch_label=pitch_number,
    )
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
            """SELECT area.scenario_id
               FROM yamazumi_pitches pitch
               JOIN yamazumi_areas area ON area.id=pitch.area_id
               WHERE pitch.id=? AND pitch.project_id=? AND pitch.area_id=?""",
            (pitch_id, project_id, area_id),
        ).fetchone()
        if not existing:
            raise ValueError("That pitch no longer exists.")
        before_conflicts = _yamazumi_pitch_address_conflict_rows(
            conn, project_id, str(existing["scenario_id"])
        )
        _validate_yamazumi_pitch_address_available(
            conn,
            project_id,
            area_id,
            pitch_number,
            exclude_pitch_id=pitch_id,
        )
        _validate_yamazumi_feed_target_context(
            conn, project_id, area_id, pitch_id, pitch_number, feed_target_id
        )
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
                   SET pitch_number=?, pitch_name=?, status=?, model_variants=?, pitch_type=?,
                       feeds_into_pitch_id=?, updated_at=?
                   WHERE id=? AND project_id=? AND area_id=?""",
                (
                    pitch_number,
                    str(values.get("pitch_name") or "").strip(),
                    status,
                    json.dumps(variants),
                    pitch_type,
                    feed_target_id,
                    now_iso(),
                    pitch_id,
                    project_id,
                    area_id,
                ),
            )
            _validate_yamazumi_pitch_feeds(conn, project_id, area_id)
            _validate_yamazumi_pitch_conflict_progress(
                conn,
                project_id,
                str(existing["scenario_id"]),
                before_conflicts,
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"Pitch address {pitch_number} already exists in this planning scenario."
            ) from exc


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
                   work_region=?, process_sync_status='Needs IE review', updated_at=?
               WHERE id=? AND project_id=? AND area_id=?""",
            (
                pitch_id,
                primary_variant,
                json.dumps(model_variants),
                work_type,
                description,
                time_s,
                str(values.get("work_region") or "None").strip(),
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
        _raise_yamazumi_pitch_reference_blockers(
            _yamazumi_pitch_reference_blockers(
                conn, project_id, area_id, {str(pitch_id)}
            )
        )
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
        raise ValueError("Pitch addresses must be unique across the planning scenario.")
    allowed = {"Active", "Blocked", "Open"}
    timestamp = now_iso()
    with connection() as conn:
        area = conn.execute(
            "SELECT scenario_id FROM yamazumi_areas WHERE id=? AND project_id=?",
            (area_id, project_id),
        ).fetchone()
        if not area:
            raise ValueError("That Yamazumi area no longer exists.")
        before_conflicts = _yamazumi_pitch_address_conflict_rows(
            conn, project_id, str(area["scenario_id"])
        )
        existing_rows = conn.execute(
            """SELECT id, feeds_into_pitch_id FROM yamazumi_pitches
               WHERE project_id=? AND area_id=?""",
            (project_id, area_id),
        ).fetchall()
        existing = {str(row["id"]) for row in existing_rows}
        existing_targets = {
            str(row["id"]): str(row["feeds_into_pitch_id"] or "").strip() or None
            for row in existing_rows
        }
        incoming_ids = {
            str(row.get("id") or "").strip()
            for row in records
            if str(row.get("id") or "").strip()
        }
        removed = existing - incoming_ids
        if removed:
            _raise_yamazumi_pitch_reference_blockers(
                _yamazumi_pitch_reference_blockers(
                    conn, project_id, area_id, removed
                )
            )
            placeholders = ",".join("?" for _ in removed)
            conn.execute(
                f"UPDATE yamazumi_pitches SET feeds_into_pitch_id=NULL WHERE id IN ({placeholders})",
                tuple(removed),
            )
            conn.execute(
                f"""UPDATE yamazumi_elements
                    SET pitch_id=NULL, process_sync_status='Needs IE review', updated_at=?
                    WHERE pitch_id IN ({placeholders})""",
                (timestamp, *removed),
            )
            conn.execute(
                f"DELETE FROM yamazumi_pitches WHERE id IN ({placeholders})",
                tuple(removed),
            )
        staged_targets: dict[str, str | None] = {}
        for index, row in enumerate(records, start=1):
            pitch_id = str(row.get("id") or "").strip() or str(uuid4())
            elsewhere = conn.execute(
                """SELECT 1 FROM yamazumi_pitches
                   WHERE id=? AND (project_id<>? OR area_id<>?)""",
                (pitch_id, project_id, area_id),
            ).fetchone()
            if elsewhere:
                raise ValueError("A pitch row does not belong to this Yamazumi area.")
            _validate_yamazumi_pitch_address_available(
                conn,
                project_id,
                area_id,
                numbers[index - 1],
                exclude_pitch_id=pitch_id,
            )
            status = str(row.get("status") or "Active").title()
            if status not in allowed:
                raise ValueError("Pitch status must be Active, Blocked, or Open.")
            pitch_type = str(row.get("pitch_type") or "Pitch").strip().title()
            if pitch_type not in YAMAZUMI_PITCH_TYPES:
                raise ValueError("Choose a valid pitch type for every pitch.")
            raw_target = (
                row.get("feeds_into_pitch_id")
                if "feeds_into_pitch_id" in edited.columns
                else existing_targets.get(pitch_id)
            )
            feed_target_id = _normalize_yamazumi_feed_target(
                pitch_type,
                raw_target,
                require_target=True,
                pitch_label=numbers[index - 1],
            )
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
            staged_targets[pitch_id] = feed_target_id
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status, sequence,
                    model_variants, pitch_type, feeds_into_pitch_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                   ON CONFLICT(id) DO UPDATE SET pitch_number=excluded.pitch_number,
                   pitch_name=excluded.pitch_name, status=excluded.status,
                   sequence=excluded.sequence, model_variants=excluded.model_variants,
                   pitch_type=excluded.pitch_type,
                   feeds_into_pitch_id=NULL,
                   updated_at=excluded.updated_at""",
                (pitch_id, project_id, area_id, numbers[index - 1], str(row.get("pitch_name") or "").strip(),
                 status, int(row.get("sequence") or index * 10), json.dumps(variants), pitch_type, timestamp),
            )
        for pitch_id, feed_target_id in staged_targets.items():
            source = conn.execute(
                "SELECT pitch_number, pitch_name FROM yamazumi_pitches WHERE id=?",
                (pitch_id,),
            ).fetchone()
            _validate_yamazumi_feed_target_context(
                conn,
                project_id,
                area_id,
                pitch_id,
                yamazumi_pitch_label(source["pitch_number"], source["pitch_name"]),
                feed_target_id,
            )
            conn.execute(
                "UPDATE yamazumi_pitches SET feeds_into_pitch_id=? WHERE id=?",
                (feed_target_id, pitch_id),
            )
        _validate_yamazumi_pitch_feeds(conn, project_id, area_id)
        _validate_yamazumi_pitch_conflict_progress(
            conn,
            project_id,
            str(area["scenario_id"]),
            before_conflicts,
        )
    return len(records)


def yamazumi_pitch_address_suggestion(project_id: str, area_id: str) -> dict:
    """Return project and Fishbone-aware defaults for creating pitch addresses."""
    section_walk = assembly_section_walk_order(project_id)
    with connection() as conn:
        area = conn.execute(
            """SELECT area.id, area.name, area.scenario_id, area.section_id,
                      project.yamazumi_line_code
               FROM yamazumi_areas area
               JOIN projects project ON project.id=area.project_id
               WHERE area.id=? AND area.project_id=?""",
            (area_id, project_id),
        ).fetchone()
        if not area:
            raise ValueError("That Yamazumi area no longer exists.")
        pitch_rows = conn.execute(
            """SELECT pitch.pitch_number, linked_area.section_id, linked_area.name,
                      linked_area.scenario_id
               FROM yamazumi_pitches pitch
               JOIN yamazumi_areas linked_area ON linked_area.id=pitch.area_id
               WHERE pitch.project_id=?""",
            (project_id,),
        ).fetchall()

    parsed_rows = [
        (row, parse_yamazumi_pitch_address(row["pitch_number"]))
        for row in pitch_rows
    ]
    parsed_rows = [(row, parsed) for row, parsed in parsed_rows if parsed]
    section_id = str(area["section_id"] or "").strip() or None

    known_by_section: dict[str, set[str]] = {}
    for row, parsed in parsed_rows:
        linked_section_id = str(row["section_id"] or "").strip()
        if linked_section_id:
            known_by_section.setdefault(linked_section_id, set()).add(
                parsed.section_code
            )

    assigned_codes: set[str] = {
        next(iter(codes))
        for codes in known_by_section.values()
        if len(codes) == 1
    }
    section_code = ""
    if section_id and len(known_by_section.get(section_id, set())) == 1:
        section_code = next(iter(known_by_section[section_id]))
    elif section_id and not section_walk.empty:
        for _, section in section_walk.iterrows():
            walk_section_id = str(section["id"])
            known_codes = known_by_section.get(walk_section_id, set())
            if len(known_codes) == 1:
                candidate = next(iter(known_codes))
            else:
                candidate = suggest_yamazumi_section_code(
                    section.get("name"), assigned_codes
                )
            assigned_codes.add(candidate)
            if walk_section_id == section_id:
                section_code = candidate
                break
    if not section_code:
        matching_unlinked_codes = {
            parsed.section_code
            for row, parsed in parsed_rows
            if not str(row["section_id"] or "").strip()
            and str(row["name"] or "").strip().casefold()
            == str(area["name"] or "").strip().casefold()
        }
        section_code = (
            next(iter(matching_unlinked_codes))
            if len(matching_unlinked_codes) == 1
            else suggest_yamazumi_section_code(area["name"], assigned_codes)
        )

    line_code = normalize_yamazumi_line_code(
        area["yamazumi_line_code"], allow_blank=True
    )
    matching_numbers = [
        parsed.number
        for row, parsed in parsed_rows
        if str(row["scenario_id"]) == str(area["scenario_id"])
        and parsed.line_code == line_code
        and parsed.section_code == section_code
    ]
    next_number = max(matching_numbers, default=0) + 1
    suggested_address = (
        format_yamazumi_pitch_address(line_code, section_code, next_number)
        if line_code
        else ""
    )
    return {
        "line_code": line_code,
        "section_code": section_code,
        "next_number": next_number,
        "suggested_address": suggested_address,
    }


def generate_yamazumi_pitch_range(
    project_id: str,
    area_id: str,
    first_address: str,
    last_address: str,
    number_mode: str = "All numbers",
    status: str = "Active",
    model_variants: list[str] | None = None,
    pitch_type: str = "Pitch",
    feeds_into_pitch_id: str | None = None,
    project_line_code: str | None = None,
) -> tuple[int, list[str]]:
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
    if pitch_type not in YAMAZUMI_PITCH_TYPES:
        raise ValueError("Choose a valid pitch type.")
    feed_target_id = _normalize_yamazumi_feed_target(
        pitch_type,
        feeds_into_pitch_id,
        require_target=True,
        pitch_label=f"range {first}–{last}",
    )
    normalized_project_line_code = (
        normalize_yamazumi_line_code(project_line_code)
        if project_line_code is not None
        else None
    )
    prefix = first_match.group(1)
    width = max(3, len(first_match.group(2)))
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
        area = conn.execute(
            "SELECT scenario_id FROM yamazumi_areas WHERE id=? AND project_id=?",
            (area_id, project_id),
        ).fetchone()
        if not area:
            raise ValueError("That Yamazumi area no longer exists.")
        scenario_id = str(area["scenario_id"])
        if normalized_project_line_code is not None:
            conn.execute(
                "UPDATE projects SET yamazumi_line_code=?, updated_at=? WHERE id=?",
                (normalized_project_line_code, timestamp, project_id),
            )
        _validate_yamazumi_scenario_pitch_addresses(
            conn, project_id, scenario_id
        )
        _validate_yamazumi_feed_target_context(
            conn,
            project_id,
            area_id,
            "",
            f"range {first}–{last}",
            feed_target_id,
        )
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM yamazumi_pitches WHERE project_id=? AND area_id=?",
            (project_id, area_id),
        ).fetchone()[0]
        existing_addresses = {
            str(row["pitch_number"]).strip().casefold()
            for row in conn.execute(
                """SELECT pitch.pitch_number
                   FROM yamazumi_pitches pitch
                   JOIN yamazumi_areas area ON area.id=pitch.area_id
                   WHERE pitch.project_id=? AND area.scenario_id=?""",
                (project_id, scenario_id),
            ).fetchall()
        }
        created = 0
        skipped: list[str] = []
        for offset, value in enumerate(values, start=1):
            address = f"{prefix}{value:0{width}d}"
            if address.casefold() in existing_addresses:
                skipped.append(address)
                continue
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status, sequence,
                    model_variants, pitch_type, feeds_into_pitch_id, updated_at)
                   VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), project_id, area_id, address, status,
                 next_sequence + offset * 10, json.dumps(variants), pitch_type,
                 feed_target_id, timestamp),
            )
            created += 1
            existing_addresses.add(address.casefold())
        _validate_yamazumi_pitch_feeds(conn, project_id, area_id)
    return created, skipped


def replace_yamazumi_elements(project_id: str, area_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "pitch_id", "model_variants", "work_type", "description", "time_s", "work_region", "sequence"}
    if not required.issubset(edited.columns):
        raise ValueError("The Yamazumi work-element table is missing required columns.")
    records = edited.to_dict("records")
    timestamp = now_iso()
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
            kept.add(element_id)
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, model_variant, model_variants,
                    work_type, description,
                    time_s, work_region, sequence, source, process_element_id,
                    process_sync_status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET pitch_id=excluded.pitch_id,
                    model_variant=excluded.model_variant, model_variants=excluded.model_variants,
                    work_type=excluded.work_type,
                    description=excluded.description, time_s=excluded.time_s,
                    work_region=excluded.work_region,
                    sequence=excluded.sequence, process_sync_status='Needs IE review',
                    updated_at=excluded.updated_at""",
                (element_id, project_id, area_id, pitch_id, primary_variant,
                 json.dumps(model_variants),
                 work_type, description, time_s,
                 str(row.get("work_region") or "None").strip(),
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
                """SELECT id, area_id, pitch_number, pitch_name, pitch_type,
                          feeds_into_pitch_id, model_variants
                   FROM yamazumi_pitches
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
                _require_yamazumi_feed_target_for_pitch_write(
                    conn, project_id, destination
                )
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


def save_yamazumi_stack_draft(
    project_id: str,
    scenario_id: str,
    area_id: str,
    stacks: dict[str, list[str]],
) -> dict:
    """Validate and atomically persist complete centerline-outward stack order."""
    if not isinstance(stacks, dict):
        raise ValueError("The Yamazumi board draft is invalid. Undo it and try again.")
    normalized: dict[str, list[str]] = {}
    for raw_stack_id, raw_element_ids in stacks.items():
        stack_key = str(raw_stack_id or "").strip()
        if not stack_key or not isinstance(raw_element_ids, list):
            raise ValueError("Every Yamazumi draft stack needs a stable destination and order.")
        normalized[stack_key] = [str(value or "").strip() for value in raw_element_ids]
        if any(not value for value in normalized[stack_key]):
            raise ValueError("Every Yamazumi draft element needs a stable ID.")

    timestamp = now_iso()
    with connection() as conn:
        area = conn.execute(
            """SELECT id, name FROM yamazumi_areas
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (area_id, project_id, scenario_id),
        ).fetchone()
        if not area:
            raise ValueError("That Yamazumi area is not in the active planning scenario.")

        pitch_rows = conn.execute(
            """SELECT id, pitch_number, pitch_name, status, pitch_type,
                      feeds_into_pitch_id, model_variants
               FROM yamazumi_pitches
               WHERE project_id=? AND area_id=?""",
            (project_id, area_id),
        ).fetchall()
        pitches = {str(row["id"]): row for row in pitch_rows}
        element_rows = conn.execute(
            """SELECT id, pitch_id, model_variant, model_variants, description,
                      sequence, process_sync_status
               FROM yamazumi_elements
               WHERE project_id=? AND area_id=?
               ORDER BY sequence, description COLLATE NOCASE, id""",
            (project_id, area_id),
        ).fetchall()
        elements = {str(row["id"]): row for row in element_rows}

        submitted_ids = [element_id for values in normalized.values() for element_id in values]
        if len(submitted_ids) != len(set(submitted_ids)):
            raise ValueError("A Yamazumi work element appears more than once in the board draft.")
        submitted_set = set(submitted_ids)
        existing_set = set(elements)
        missing = existing_set - submitted_set
        stale = submitted_set - existing_set
        if missing or stale:
            parts = []
            if missing:
                parts.append(f"missing {len(missing)} current element(s)")
            if stale:
                parts.append(f"containing {len(stale)} stale or foreign element(s)")
            raise ValueError(
                "The Yamazumi board draft is incomplete or out of date ("
                + " and ".join(parts)
                + "). Undo it and try again."
            )

        for stack_key, element_ids in normalized.items():
            if stack_key == UNASSIGNED_STACK_ID:
                continue
            pitch = pitches.get(stack_key)
            if not pitch:
                raise ValueError(
                    "A Yamazumi draft destination is missing or belongs to another area or scenario."
                )
            if element_ids and str(pitch["status"]) != "Active":
                label = yamazumi_pitch_label(pitch["pitch_number"], pitch["pitch_name"])
                raise ValueError(f"Work can only be saved into an Active pitch; {label} is not Active.")

        current = build_stack_draft(dict(row) for row in element_rows)
        affected_stack_ids = sorted(
            stack_key
            for stack_key in set(current) | set(normalized)
            if current.get(stack_key, []) != normalized.get(stack_key, [])
        )
        desired: dict[str, tuple[str | None, int]] = {}
        for stack_key in affected_stack_ids:
            pitch_id = None if stack_key == UNASSIGNED_STACK_ID else stack_key
            for position, element_id in enumerate(normalized.get(stack_key, []), start=1):
                desired[element_id] = (pitch_id, position * 10)

        enabled_variants: dict[str, list[str]] = {}
        for stack_key in affected_stack_ids:
            if stack_key == UNASSIGNED_STACK_ID or stack_key not in pitches:
                continue
            destination = pitches[stack_key]
            destination_variants = parse_yamazumi_model_variants(
                destination["model_variants"], fallback=None
            )
            required_variants = list(dict.fromkeys(
                variant
                for element_id in normalized.get(stack_key, [])
                for variant in parse_yamazumi_model_variants(
                    elements[element_id]["model_variants"],
                    elements[element_id]["model_variant"],
                )
            ))
            missing_variants = [
                variant for variant in required_variants
                if variant not in destination_variants
            ]
            if missing_variants:
                _require_yamazumi_feed_target_for_pitch_write(
                    conn, project_id, destination
                )
                conn.execute(
                    """UPDATE yamazumi_pitches SET model_variants=?, updated_at=?
                       WHERE id=? AND project_id=? AND area_id=?""",
                    (
                        json.dumps([*destination_variants, *missing_variants]),
                        timestamp,
                        stack_key,
                        project_id,
                        area_id,
                    ),
                )
                enabled_variants[stack_key] = missing_variants

        changed_element_ids: list[str] = []
        for element_id, (pitch_id, sequence) in desired.items():
            existing = elements[element_id]
            old_pitch_id = str(existing["pitch_id"] or "").strip() or None
            if old_pitch_id == pitch_id and int(existing["sequence"]) == sequence:
                continue
            sync_status = (
                "Needs IE review"
                if old_pitch_id != pitch_id
                else str(existing["process_sync_status"] or "Needs IE review")
            )
            cursor = conn.execute(
                """UPDATE yamazumi_elements
                   SET pitch_id=?, sequence=?, process_sync_status=?, updated_at=?
                   WHERE id=? AND project_id=? AND area_id=?""",
                (
                    pitch_id, sequence, sync_status, timestamp,
                    element_id, project_id, area_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "A Yamazumi work element changed while the draft was being saved. No changes were applied."
                )
            changed_element_ids.append(element_id)

        affected_stacks = []
        for stack_key in affected_stack_ids:
            pitch = pitches.get(stack_key)
            affected_stacks.append({
                "pitch_id": stack_key,
                "pitch_address": (
                    str(pitch["pitch_number"] or "") if pitch else "Unassigned"
                ),
                "pitch_name": str(pitch["pitch_name"] or "") if pitch else "Unassigned",
                "elements": [
                    {
                        "element_id": element_id,
                        "description": str(elements[element_id]["description"] or ""),
                        "sequence": position * 10,
                    }
                    for position, element_id in enumerate(
                        normalized.get(stack_key, []), start=1
                    )
                ],
            })

    return {
        "area_id": area_id,
        "area_name": str(area["name"] or ""),
        "affected_stacks": affected_stacks,
        "enabled_variants": enabled_variants,
        "changed_element_ids": changed_element_ids,
    }


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
    with connection() as conn:
        scenario = conn.execute(
            "SELECT takt_time_unit, yamazumi_time_unit FROM planning_scenarios "
            "WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone()
        if not scenario:
            raise ValueError("The active planning scenario no longer exists in this project.")
        import_takt_unit = normalize_time_unit(scenario["takt_time_unit"])
        import_work_unit = normalize_time_unit(scenario["yamazumi_time_unit"])
        _validate_yamazumi_scenario_pitch_addresses(
            conn, project_id, scenario_id
        )
        for index, row in rows.iterrows():
            area_name = str(row.get("Sub-Line") or "").strip()
            pitch_number = str(row.get("Pitch_number") or "").strip()
            description = str(row.get("Work_Description") or "").strip()
            if not area_name or not pitch_number or not description:
                continue
            takt_raw = row.get("Pitch_Takt_time")
            takt = (
                None
                if pd.isna(takt_raw) or str(takt_raw).strip() == ""
                else display_to_seconds(takt_raw, import_takt_unit)
            )
            if area_name not in area_ids:
                area_ids[area_name] = upsert_yamazumi_area(
                    project_id,
                    scenario_id,
                    area_name,
                    section_ids_by_name.get(area_name),
                    takt,
                    _conn=conn,
                )
            area_id = area_ids[area_name]
            pitch_key = (area_id, pitch_number.casefold())
            if pitch_key not in pitch_ids:
                existing_pitch = conn.execute(
                    """SELECT id, pitch_number, pitch_type, feeds_into_pitch_id
                       FROM yamazumi_pitches
                       WHERE project_id=? AND area_id=?
                         AND TRIM(pitch_number)=TRIM(?) COLLATE NOCASE""",
                    (project_id, area_id, pitch_number),
                ).fetchone()
                if existing_pitch:
                    existing_target_id = _normalize_yamazumi_feed_target(
                        str(existing_pitch["pitch_type"] or "Pitch").title(),
                        existing_pitch["feeds_into_pitch_id"],
                        require_target=True,
                        pitch_label=pitch_number,
                    )
                    _validate_yamazumi_feed_target_context(
                        conn,
                        project_id,
                        area_id,
                        str(existing_pitch["id"]),
                        pitch_number,
                        existing_target_id,
                    )
                else:
                    _validate_yamazumi_pitch_address_available(
                        conn, project_id, area_id, pitch_number
                    )
                pitch_id = str(existing_pitch["id"]) if existing_pitch else str(uuid4())
                pitch_ids[pitch_key] = pitch_id
                status = str(row.get("Pitch_status") or "Active").strip().title()
                if status not in {"Active", "Blocked", "Open"}:
                    status = "Active"
                conn.execute(
                    """INSERT INTO yamazumi_pitches
                       (id, project_id, area_id, pitch_number, pitch_name, status,
                        sequence, model_variants, pitch_type, feeds_into_pitch_id, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, '[]', 'Pitch', NULL, ?)
                       ON CONFLICT(id) DO UPDATE SET pitch_name=excluded.pitch_name,
                       status=excluded.status, updated_at=excluded.updated_at""",
                    (pitch_id, project_id, area_id, pitch_number,
                     str(row.get("Pitch_name") or "").strip(), status,
                     len(pitch_ids) * 10, timestamp),
                )
            import_pitch_id = pitch_ids[pitch_key]
            import_pitch = conn.execute(
                "SELECT status FROM yamazumi_pitches WHERE id=?", (import_pitch_id,)
            ).fetchone()
            assigned_pitch_id = (
                import_pitch_id if import_pitch and import_pitch["status"] == "Active" else None
            )
            imported_variant = str(row.get("Model_variant") or "Base").strip().title()
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, model_variant, model_variants,
                    work_type, description, time_s, work_region, sequence,
                    source, process_sync_status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           'Excel import', 'Needs IE review', ?)""",
                (str(uuid4()), project_id, area_id, assigned_pitch_id, imported_variant,
                 json.dumps([imported_variant]),
                 str(row.get("Work_Type") or "Cycle").strip().title(), description,
                 display_to_seconds(
                     row.get("Work_Time_to_complete") or 0, import_work_unit
                 ),
                 str(row.get("Work_region") or "None").strip(),
                 (index + 1) * 10, timestamp),
            )
            current_pitch = conn.execute(
                "SELECT model_variants FROM yamazumi_pitches WHERE id=?",
                (import_pitch_id,),
            ).fetchone()
            selected_variants = json.loads(current_pitch["model_variants"] or "[]")
            if imported_variant not in selected_variants:
                selected_variants.append(imported_variant)
                conn.execute(
                    "UPDATE yamazumi_pitches SET model_variants=? WHERE id=?",
                    (json.dumps(selected_variants), import_pitch_id),
                )
            elements_added += 1
        for area_id in set(area_ids.values()):
            _validate_yamazumi_pitch_feeds(conn, project_id, area_id)
        _validate_yamazumi_scenario_pitch_addresses(
            conn, project_id, scenario_id
        )
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
                next_sequence = conn.execute(
                    """SELECT COALESCE(MAX(sequence), 0) + 10 FROM work_elements
                       WHERE project_id=? AND scenario_id=?""",
                    (project_id, scenario_id),
                ).fetchone()[0]
                process_id = _create_work_element_with_started_ergonomics_review(
                    conn,
                    project_id,
                    scenario_id,
                    {
                        "sequence": next_sequence,
                        "station": station,
                        "operation": str(row["description"]),
                        "description": f"Yamazumi area: {row['area_name']}",
                        "cycle_time_s": float(row["time_s"] or 0),
                        "part_number": "",
                        "tool": "",
                        "torque": "",
                        "quality_requirement": "",
                        "ergo_requirement": "",
                        "location": station,
                        "conveyor_height_in": None,
                        "platform_height_in": None,
                        "pit_depth_in": None,
                        "model_applicability": model_applicability,
                        "status": "Draft",
                    },
                    timestamp,
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
    frame = pd.DataFrame(
        query(f"SELECT * FROM {table} WHERE project_id = ? ORDER BY {order_by}", (project_id,))
    )
    if table == "parts" and not frame.empty:
        links = assembly_catalog_part_applicability(project_id)
        frame["assembly_id"] = ""
        frame["assembly_number"] = ""
        if not links.empty:
            links_by_part = links.set_index(links["part_id"].astype(str))
            part_ids = frame["id"].astype(str)
            linked = part_ids.isin(links_by_part.index)
            frame.loc[linked, "assembly_id"] = part_ids[linked].map(
                links_by_part["assembly_id"]
            )
            frame.loc[linked, "assembly_number"] = part_ids[linked].map(
                links_by_part["assembly_number"]
            )
            frame.loc[linked, "model_applicability"] = part_ids[linked].map(
                links_by_part["model_applicability"]
            ).fillna("")
    return frame


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
    takt_time_unit: str = "seconds",
) -> str:
    project_id, timestamp = str(uuid4()), now_iso()
    takt_unit = normalize_time_unit(takt_time_unit)
    execute(
        """INSERT INTO projects
           (id, name, program, product_line, owner, revision, status,
            takt_time_s, takt_time_unit, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'A', 'Draft', ?, ?, '', ?, ?)""",
        (
            project_id, name.strip(), program.strip(), product_line.strip(),
            owner.strip(), takt_time_s, takt_unit, timestamp, timestamp,
        ),
    )
    return project_id


def update_project_yamazumi_line_code(project_id: str, value: object) -> dict:
    """Save the project-wide line code used only for Yamazumi address suggestions."""
    code = normalize_yamazumi_line_code(value, allow_blank=True)
    timestamp = now_iso()
    with connection() as conn:
        current = conn.execute(
            "SELECT yamazumi_line_code FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if not current:
            raise ValueError("The active project no longer exists.")
        old_code = str(current["yamazumi_line_code"] or "")
        conn.execute(
            "UPDATE projects SET yamazumi_line_code=?, updated_at=? WHERE id=?",
            (code, timestamp, project_id),
        )
    return {
        "old_line_code": old_code,
        "new_line_code": code,
        "updated_at": timestamp,
    }


def update_project(project_id: str, values: dict) -> None:
    takt_unit = normalize_time_unit(values.get("takt_time_unit", "seconds"))
    values = {**values, "takt_time_unit": takt_unit}
    fields = [
        "name", "program", "product_line", "owner", "revision", "status",
        "takt_time_s", "takt_time_unit", "notes",
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
        existing_parts = {
            str(existing["id"]): dict(existing)
            for existing in conn.execute(
                "SELECT * FROM parts WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        existing_ids = set(existing_parts)
        linked_assemblies = {
            str(row["catalog_part_id"]): str(row["assembly_number"])
            for row in conn.execute(
                """SELECT catalog_part_id, assembly_number
                   FROM manufacturing_assemblies
                   WHERE project_id=? AND catalog_part_id IS NOT NULL""",
                (project_id,),
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
            previous = existing_parts.get(part_id)
            part_number = str(row["part_number"]).strip()
            if (
                part_id in linked_assemblies
                and previous
                and part_number != str(previous["part_number"])
            ):
                raise ValueError(
                    f"Part number {previous['part_number']} represents assembly "
                    f"{linked_assemblies[part_id]}. Rename it through the Assembly grid."
                )
            applicability = (
                str(previous["model_applicability"] or "")
                if part_id in linked_assemblies and previous
                else normalize_model_applicability(row.get("model_applicability"))
            )
            values = (
                part_number, clean_text(row.get("description")), quantity,
                revision, applicability,
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


def part_delete_impact(project_id: str, part_ids: list[str]) -> dict:
    normalized = list(dict.fromkeys(
        str(part_id).strip() for part_id in part_ids if str(part_id).strip()
    ))
    if not normalized:
        raise ValueError("Select at least one part to delete.")
    placeholders = ",".join("?" for _ in normalized)
    with connection() as conn:
        parts = conn.execute(
            f"""SELECT id, part_number FROM parts
                WHERE project_id=? AND id IN ({placeholders})
                ORDER BY part_number""",
            (project_id, *normalized),
        ).fetchall()
        if len(parts) != len(normalized):
            raise ValueError("One or more selected parts no longer exist.")
        linked = conn.execute(
            f"""SELECT catalog_part_id AS part_id, assembly_number, name AS assembly_name
                FROM manufacturing_assemblies
                WHERE project_id=? AND catalog_part_id IN ({placeholders})
                ORDER BY assembly_number""",
            (project_id, *normalized),
        ).fetchall()
        return {
            "part_ids": normalized,
            "part_numbers": [str(row["part_number"]) for row in parts],
            "linked_assemblies": [dict(row) for row in linked],
        }


def delete_project_part(project_id: str, part_id: str) -> str:
    """Delete one catalog part and its cascading fishbone uses and image records."""
    with connection() as conn:
        part = conn.execute(
            "SELECT part_number, image_path FROM parts WHERE id=? AND project_id=?",
            (part_id, project_id),
        ).fetchone()
        if not part:
            raise ValueError("That part no longer exists.")
        linked = conn.execute(
            """SELECT assembly_number FROM manufacturing_assemblies
               WHERE project_id=? AND catalog_part_id=?""",
            (project_id, part_id),
        ).fetchone()
        if linked:
            raise ValueError(
                f"Part number {part['part_number']} represents assembly "
                f"{linked['assembly_number']}. Delete or merge that assembly first."
            )
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


def assembly_section_walk_order(project_id: str) -> pd.DataFrame:
    """Return Fishbone sections in deterministic depth-first framework order."""
    sections = assembly_sections(project_id)
    if sections.empty:
        result = sections.copy()
        result["depth"] = pd.Series(dtype="Int64")
        return result

    def normalized_parent_id(value) -> str:
        if value is None or pd.isna(value):
            return ""
        return str(value).strip()

    records = {
        str(row["id"]): row.to_dict() for _, row in sections.iterrows()
    }
    children: dict[str, list[str]] = {}
    for section_id, row in records.items():
        parent_id = normalized_parent_id(row.get("parent_id"))
        children.setdefault(parent_id, []).append(section_id)
    for child_ids in children.values():
        child_ids.sort(
            key=lambda child_id: (
                int(records[child_id]["sequence"]),
                records[child_id]["name"],
            )
        )

    order: list[str] = []
    depth_by_id: dict[str, int] = {}

    def add_branch(section_id: str, depth: int) -> None:
        if section_id in depth_by_id:
            return
        depth_by_id[section_id] = depth
        order.append(section_id)
        for child_id in children.get(section_id, []):
            add_branch(child_id, depth + 1)

    root_ids = [
        section_id
        for section_id, row in records.items()
        if not normalized_parent_id(row.get("parent_id"))
        or row["section_type"] == "Main spine"
    ]
    root_ids.sort(
        key=lambda section_id: (
            int(records[section_id]["sequence"]),
            records[section_id]["name"],
        )
    )
    for root_id in root_ids:
        add_branch(root_id, 0)
    for section_id in records:
        add_branch(section_id, 0)

    result = (
        sections.set_index(sections["id"].astype(str), drop=False)
        .loc[order]
        .reset_index(drop=True)
    )
    result["depth"] = result["id"].astype(str).map(depth_by_id).astype("Int64")
    return result


def _op_id_depth_letter(depth: int) -> str:
    """Return a lowercase spreadsheet-style letter for a zero-based depth."""
    value = depth + 1
    letters = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(ord("a") + remainder) + letters
    return letters


def work_element_op_ids(
    project_id: str,
    scenario_id: str,
    work_element_ids: list[str] | None = None,
) -> dict[str, str]:
    """Compute scenario-scoped, human-readable Op IDs without persisting them."""
    requested_ids = None
    if work_element_ids is not None:
        requested_ids = list(dict.fromkeys(
            str(value or "").strip() for value in work_element_ids
            if str(value or "").strip()
        ))
        if not requested_ids:
            return {}

    with connection() as conn:
        scenario = conn.execute(
            "SELECT id FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone()
        if not scenario:
            raise ValueError("The active planning scenario no longer exists in this project.")

        parameters: list[object] = [project_id, scenario_id]
        work_filter = ""
        if requested_ids is not None:
            placeholders = ",".join("?" for _ in requested_ids)
            work_filter = f" AND id IN ({placeholders})"
            parameters.extend(requested_ids)
        work_rows = conn.execute(
            f"""SELECT id FROM work_elements
                WHERE project_id=? AND scenario_id=?{work_filter}
                ORDER BY sequence, id""",
            tuple(parameters),
        ).fetchall()
        work_ids = [str(row["id"]) for row in work_rows]
        if requested_ids is not None and set(work_ids) != set(requested_ids):
            raise ValueError(
                "One or more Process at a Glance Work Elements are missing or belong to "
                "another planning scenario."
            )
        if not work_ids:
            return {}

        yamazumi_rows = conn.execute(
            """SELECT element.id AS yamazumi_element_id,
                      element.process_element_id, element.pitch_id,
                      element.sequence, element.description,
                      area.id AS area_id, area.section_id,
                      pitch.id AS resolved_pitch_id, pitch.pitch_number
               FROM yamazumi_elements element
               JOIN yamazumi_areas area
                 ON area.id=element.area_id
                AND area.project_id=element.project_id
                AND area.scenario_id=?
               LEFT JOIN yamazumi_pitches pitch
                 ON pitch.id=element.pitch_id
                AND pitch.project_id=element.project_id
                AND pitch.area_id=area.id
               WHERE element.project_id=?
               ORDER BY element.sequence,
                        element.description COLLATE NOCASE,
                        element.id""",
            (scenario_id, project_id),
        ).fetchall()

    links_by_work: dict[str, list[sqlite3.Row]] = {}
    stack_rows: dict[str, list[sqlite3.Row]] = {}
    for row in yamazumi_rows:
        process_id = str(row["process_element_id"] or "").strip()
        if process_id:
            links_by_work.setdefault(process_id, []).append(row)
        pitch_id = str(row["resolved_pitch_id"] or "").strip()
        if pitch_id:
            stack_rows.setdefault(pitch_id, []).append(row)
    stack_positions = {
        str(row["yamazumi_element_id"]): position
        for rows in stack_rows.values()
        for position, row in enumerate(rows, start=1)
    }

    walk = assembly_section_walk_order(project_id)
    section_by_id = {
        str(row["id"]): row.to_dict() for _, row in walk.iterrows()
    } if not walk.empty else {}
    mainline_numbers = {
        str(row["id"]): position
        for position, (_, row) in enumerate(
            walk.loc[walk["section_type"].eq("Main spine")].iterrows(), start=1
        )
    } if not walk.empty else {}
    subassembly_children: dict[str, list[str]] = {}
    for section_id, section in section_by_id.items():
        if str(section.get("section_type") or "") != "Subassembly":
            continue
        parent_id = str(section.get("parent_id") or "").strip()
        subassembly_children.setdefault(parent_id, []).append(section_id)
    for child_ids in subassembly_children.values():
        child_ids.sort(
            key=lambda child_id: (
                int(section_by_id[child_id]["sequence"]),
                str(section_by_id[child_id]["name"]),
            )
        )

    def fishbone_prefix(section_id: str) -> str | None:
        section = section_by_id.get(section_id)
        if not section:
            return None
        if str(section.get("section_type") or "") == "Main spine":
            number = mainline_numbers.get(section_id)
            return f"M{number}" if number else None

        reverse_path: list[str] = []
        visited: set[str] = set()
        current_id = section_id
        mainline_id = ""
        while current_id and current_id not in visited:
            visited.add(current_id)
            current = section_by_id.get(current_id)
            if not current:
                return None
            section_type = str(current.get("section_type") or "")
            if section_type == "Main spine":
                mainline_id = current_id
                break
            if section_type != "Subassembly":
                return None
            reverse_path.append(current_id)
            current_id = str(current.get("parent_id") or "").strip()
        if not mainline_id or mainline_id not in mainline_numbers:
            return None

        path = list(reversed(reverse_path))
        lineages = subassembly_children.get(mainline_id, [])
        if not path or path[0] not in lineages:
            return None
        lineage_number = lineages.index(path[0]) + 1
        branch_path: list[str] = []
        for depth, path_section_id in enumerate(path):
            if depth:
                parent_id = path[depth - 1]
                siblings = subassembly_children.get(parent_id, [])
                if path_section_id not in siblings:
                    return None
                if len(siblings) > 1:
                    branch_path.append(str(siblings.index(path_section_id) + 1))
            depth_designator = _op_id_depth_letter(depth) + "".join(branch_path)
        return f"M{mainline_numbers[mainline_id]}S{lineage_number}{depth_designator}"

    result: dict[str, str] = {}
    for work_id in work_ids:
        links = links_by_work.get(work_id, [])
        if not links:
            result[work_id] = "Yamazumi link required"
            continue
        if len(links) != 1:
            result[work_id] = "Unique Yamazumi link required"
            continue
        link = links[0]
        pitch_id = str(link["resolved_pitch_id"] or "").strip()
        if not pitch_id:
            result[work_id] = "Yamazumi pitch required"
            continue
        section_id = str(link["section_id"] or "").strip()
        if not section_id:
            result[work_id] = "Fishbone link required"
            continue
        prefix = fishbone_prefix(section_id)
        if not prefix:
            result[work_id] = "Fishbone hierarchy required"
            continue
        position = stack_positions.get(str(link["yamazumi_element_id"]))
        if position is None:
            result[work_id] = "Yamazumi link required"
            continue
        result[work_id] = f"{prefix}.{link['pitch_number']}.{position}"
    return result


def work_element_op_id(project_id: str, scenario_id: str, work_element_id: str) -> str:
    """Compute one Op ID through the shared batch implementation."""
    normalized_id = str(work_element_id or "").strip()
    if not normalized_id:
        raise ValueError("Choose a Process at a Glance Work Element.")
    return work_element_op_ids(project_id, scenario_id, [normalized_id])[normalized_id]


def process_pitch_visual_summary(
    project_id: str, scenario_id: str, pitch_id: str
) -> dict:
    """Return one scenario-owned pitch and its Process-linked visual-summary rows."""
    normalized_pitch_id = str(pitch_id or "").strip()
    if not normalized_pitch_id:
        raise ValueError("Choose a Yamazumi pitch.")

    with connection() as conn:
        scenario = conn.execute(
            "SELECT id FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone()
        if not scenario:
            raise ValueError("The active planning scenario no longer exists in this project.")
        pitch = conn.execute(
            """SELECT pitch.id, pitch.pitch_number, pitch.pitch_name, pitch.sequence,
                      area.id AS area_id, area.section_id, area.name AS area_name
               FROM yamazumi_pitches pitch
               JOIN yamazumi_areas area
                 ON area.id=pitch.area_id AND area.project_id=pitch.project_id
               WHERE pitch.id=? AND pitch.project_id=? AND area.scenario_id=?""",
            (normalized_pitch_id, project_id, scenario_id),
        ).fetchone()
        if not pitch:
            raise ValueError("The selected pitch no longer exists in the active planning scenario.")

        rows = conn.execute(
            """SELECT work.id AS work_element_id, work.operation,
                      work.model_applicability, work.sequence AS process_sequence,
                      yamazumi.id AS yamazumi_element_id,
                      yamazumi.description AS yamazumi_description,
                      yamazumi.time_s, yamazumi.sequence AS stack_sequence
               FROM yamazumi_elements yamazumi
               JOIN yamazumi_areas area
                 ON area.id=yamazumi.area_id
                AND area.project_id=yamazumi.project_id
                AND area.scenario_id=?
               JOIN work_elements work
                 ON work.id=yamazumi.process_element_id
                AND work.project_id=yamazumi.project_id
                AND work.scenario_id=area.scenario_id
               WHERE yamazumi.project_id=? AND yamazumi.pitch_id=?
               ORDER BY yamazumi.sequence,
                        yamazumi.description COLLATE NOCASE,
                        yamazumi.id""",
            (scenario_id, project_id, normalized_pitch_id),
        ).fetchall()
        work_ids = [str(row["work_element_id"]) for row in rows]
        cards = [dict(row) for row in rows]

        parts_by_work: dict[str, list[dict]] = {work_id: [] for work_id in work_ids}
        handling_by_work: dict[str, list[str | None]] = {
            work_id: [] for work_id in work_ids
        }
        torque_by_work: dict[str, list[dict]] = {work_id: [] for work_id in work_ids}
        if work_ids:
            placeholders = ",".join("?" for _ in work_ids)
            part_rows = conn.execute(
                f"""SELECT group_row.work_element_id, option.handling_type,
                           part.id AS part_id, part.part_number,
                           part.description AS part_description,
                           COALESCE(NULLIF(TRIM(part.image_path), ''), (
                               SELECT image.image_path FROM part_images image
                               WHERE image.part_id=part.id
                               ORDER BY image.created_at, image.id LIMIT 1
                           ), '') AS image_path
                    FROM process_part_groups group_row
                    JOIN process_part_options option ON option.group_id=group_row.id
                    JOIN parts part
                      ON part.id=option.part_id AND part.project_id=group_row.project_id
                    LEFT JOIN part_scenario_activity activity
                      ON activity.project_id=group_row.project_id
                     AND activity.scenario_id=group_row.scenario_id
                     AND activity.part_id=part.id
                    WHERE group_row.project_id=? AND group_row.scenario_id=?
                      AND group_row.work_element_id IN ({placeholders})
                      AND COALESCE(activity.active, 1)=1
                    ORDER BY group_row.work_element_id, group_row.name,
                             part.part_number""",
                (project_id, scenario_id, *work_ids),
            ).fetchall()
            for row in part_rows:
                work_id = str(row["work_element_id"])
                part = dict(row)
                handling_by_work[work_id].append(part.pop("handling_type"))
                part.pop("work_element_id", None)
                parts_by_work[work_id].append(part)

            torque_rows = conn.execute(
                f"""SELECT assignment.work_element_id, assignment.unique_identifier,
                           assignment.target_value, assignment.tolerances,
                           assignment.unit
                    FROM quality_requirement_assignments assignment
                    JOIN quality_requirement_torque_details detail
                      ON detail.quality_requirement_id=assignment.quality_requirement_id
                     AND detail.project_id=assignment.project_id
                    WHERE assignment.project_id=? AND assignment.scenario_id=?
                      AND assignment.requirement_type='Torque'
                      AND assignment.work_element_id IN ({placeholders})
                    ORDER BY assignment.work_element_id,
                             assignment.unique_identifier COLLATE NOCASE,
                             assignment.id""",
                (project_id, scenario_id, *work_ids),
            ).fetchall()
            for row in torque_rows:
                torque = dict(row)
                work_id = str(torque.pop("work_element_id"))
                torque_by_work[work_id].append(torque)

    op_ids = work_element_op_ids(project_id, scenario_id, work_ids) if work_ids else {}
    risk_ids = process_ergonomics_risk_work_element_ids(project_id, scenario_id)
    for card in cards:
        work_id = str(card["work_element_id"])
        handling_values = handling_by_work.get(work_id, [])
        normalized_handling = {
            str(value).strip() for value in handling_values if str(value or "").strip()
        }
        has_null = any(not str(value or "").strip() for value in handling_values)
        if normalized_handling == {"Consume"} and not has_null:
            classification = "Value-Added (VA)"
            color = "green"
        elif normalized_handling == {"Handle"} and not has_null:
            classification = "Non-Value-Added but Necessary (NVAN)"
            color = "orange"
        else:
            classification = "Unclassified"
            color = "gray"
        card.update(
            op_id=op_ids.get(work_id, "Yamazumi link required"),
            parts=parts_by_work.get(work_id, []),
            motion_classification=classification,
            motion_color=color,
            ergonomics_risk=work_id in risk_ids,
            torque_requirements=torque_by_work.get(work_id, []),
        )

    return {**dict(pitch), "elements": cards}




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
    # Yamazumi areas may now converge on the selected target; deletion merges
    # their contents per scenario instead of treating convergence as a conflict.
    conflicts: list[dict] = []
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


def _merge_yamazumi_areas_for_section_delete(
    conn: sqlite3.Connection,
    project_id: str,
    affected_ids: list[str],
    target_section_id: str,
    timestamp: str,
) -> tuple[int, int]:
    """Move affected area contents into one target-linked area per scenario."""
    placeholders = ", ".join("?" for _ in affected_ids)
    rows = conn.execute(
        f"""SELECT id, scenario_id, section_id
            FROM yamazumi_areas
            WHERE project_id=?
              AND (section_id=? OR section_id IN ({placeholders}))
            ORDER BY CASE WHEN section_id=? THEN 0 ELSE 1 END, rowid""",
        (project_id, target_section_id, *affected_ids, target_section_id),
    ).fetchall()
    by_scenario: dict[str | None, list[sqlite3.Row]] = {}
    for row in rows:
        by_scenario.setdefault(row["scenario_id"], []).append(row)

    moved_area_count = 0
    merged_area_count = 0
    for scenario_rows in by_scenario.values():
        incoming = [
            row for row in scenario_rows if str(row["section_id"]) in affected_ids
        ]
        if not incoming:
            continue
        survivor = scenario_rows[0]
        survivor_id = str(survivor["id"])
        if str(survivor["section_id"]) in affected_ids:
            conn.execute(
                "UPDATE yamazumi_areas SET section_id=?, updated_at=? WHERE id=?",
                (target_section_id, timestamp, survivor_id),
            )
            moved_area_count += 1

        for donor in scenario_rows[1:]:
            donor_id = str(donor["id"])
            if str(donor["section_id"]) not in affected_ids:
                continue
            conn.execute(
                """DELETE FROM yamazumi_work_regions
                   WHERE area_id=? AND EXISTS (
                       SELECT 1 FROM yamazumi_work_regions target_region
                       WHERE target_region.area_id=?
                         AND target_region.name=yamazumi_work_regions.name
                   )""",
                (donor_id, survivor_id),
            )
            conn.execute(
                "UPDATE yamazumi_work_regions SET area_id=?, updated_at=? WHERE area_id=?",
                (survivor_id, timestamp, donor_id),
            )
            conn.execute(
                "UPDATE yamazumi_elements SET area_id=?, updated_at=? WHERE area_id=?",
                (survivor_id, timestamp, donor_id),
            )
            conn.execute(
                "UPDATE yamazumi_pitches SET area_id=?, updated_at=? WHERE area_id=?",
                (survivor_id, timestamp, donor_id),
            )
            conn.execute("DELETE FROM yamazumi_areas WHERE id=?", (donor_id,))
            moved_area_count += 1
            merged_area_count += 1
    return moved_area_count, merged_area_count


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
    yamazumi_merged = 0
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
            yamazumi_repointed, yamazumi_merged = (
                _merge_yamazumi_areas_for_section_delete(
                    conn, project_id, affected_ids, str(target_id), timestamp
                )
            )
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
        "yamazumi_merged_count": int(yamazumi_merged),
        "process_repointed_count": int(process_repointed),
        "assembly_replacement_count": len(assembly_replacements),
        "category_built_repointed_count": int(category_built_repointed),
        "category_installed_repointed_count": int(category_installed_repointed),
        "feature_visibility_deleted_count": int(feature_visibility_deleted),
    }




def _create_yamazumi_areas_for_section(
    conn: sqlite3.Connection,
    project_id: str,
    section_id: str,
    section_name: str,
    timestamp: str,
) -> dict[str, object]:
    """Create one linked area per existing scenario without altering conflicts."""
    created: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    scenarios = conn.execute(
        """SELECT id, name, revision_label, status
           FROM planning_scenarios WHERE project_id=?
           ORDER BY revision_sequence, created_at, id""",
        (project_id,),
    ).fetchall()
    for scenario in scenarios:
        scenario_id = str(scenario["id"])
        linked = conn.execute(
            """SELECT id FROM yamazumi_areas
               WHERE project_id=? AND scenario_id=? AND section_id=? LIMIT 1""",
            (project_id, scenario_id, section_id),
        ).fetchone()
        if linked:
            continue
        same_name = conn.execute(
            """SELECT id, section_id FROM yamazumi_areas
               WHERE project_id=? AND scenario_id=? AND name=? COLLATE NOCASE
               ORDER BY id LIMIT 1""",
            (project_id, scenario_id, section_name),
        ).fetchone()
        if same_name:
            conflicts.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_name": str(scenario["name"]),
                    "revision_label": str(scenario["revision_label"]),
                    "status": str(scenario["status"]),
                    "area_id": str(same_name["id"]),
                    "reason": "same_name_area",
                }
            )
            continue
        area_id = str(uuid4())
        conn.execute(
            """INSERT INTO yamazumi_areas
               (id, project_id, scenario_id, section_id, name, takt_override_s, updated_at)
               VALUES (?, ?, ?, ?, ?, NULL, ?)""",
            (area_id, project_id, scenario_id, section_id, section_name, timestamp),
        )
        created.append(
            {
                "area_id": area_id,
                "scenario_id": scenario_id,
                "scenario_name": str(scenario["name"]),
                "revision_label": str(scenario["revision_label"]),
                "status": str(scenario["status"]),
            }
        )
    return {"created": created, "conflicts": conflicts}


def yamazumi_area_creation_summary(
    project_id: str, section_id: str
) -> dict[str, object]:
    """Describe linked areas and preserved name conflicts for one section."""
    section_rows = query(
        "SELECT name FROM assembly_sections WHERE id=? AND project_id=?",
        (section_id, project_id),
    )
    if not section_rows:
        raise ValueError("The Fishbone section no longer exists.")
    section_name = str(section_rows[0]["name"])
    linked = query(
        """SELECT area.id AS area_id, scenario.id AS scenario_id,
                  scenario.name AS scenario_name,
                  scenario.revision_label, scenario.status
           FROM planning_scenarios scenario
           JOIN yamazumi_areas area
             ON area.scenario_id=scenario.id AND area.project_id=scenario.project_id
           WHERE scenario.project_id=? AND area.section_id=?
           ORDER BY scenario.revision_sequence, scenario.created_at, scenario.id""",
        (project_id, section_id),
    )
    conflicts = query(
        """SELECT area.id AS area_id, scenario.id AS scenario_id,
                  scenario.name AS scenario_name,
                  scenario.revision_label, scenario.status
           FROM planning_scenarios scenario
           JOIN yamazumi_areas area
             ON area.scenario_id=scenario.id AND area.project_id=scenario.project_id
           WHERE scenario.project_id=? AND area.name=? COLLATE NOCASE
             AND (area.section_id IS NULL OR area.section_id<>?)
           ORDER BY scenario.revision_sequence, scenario.created_at, scenario.id""",
        (project_id, section_name, section_id),
    )
    for row in conflicts:
        row["reason"] = "same_name_area"
    return {
        "section_id": section_id,
        "section_name": section_name,
        "created": linked,
        "conflicts": conflicts,
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
            _create_yamazumi_areas_for_section(
                conn, project_id, section_id, name, timestamp
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


def assembly_catalog_part_applicability(project_id: str) -> pd.DataFrame:
    """Return linked assembly parts and their directly mapped active official models."""
    rows = query(
        """SELECT assembly.catalog_part_id AS part_id, assembly.id AS assembly_id,
                  assembly.assembly_number, model.model_number
           FROM manufacturing_assemblies assembly
           LEFT JOIN assembly_grid_model_mappings mapping
             ON mapping.project_id=assembly.project_id AND mapping.assembly_id=assembly.id
           LEFT JOIN project_models model
             ON model.id=mapping.model_id AND model.project_id=assembly.project_id
            AND model.active=1
           WHERE assembly.project_id=? AND assembly.catalog_part_id IS NOT NULL
           ORDER BY assembly.assembly_number, model.model_number""",
        (project_id,),
    )
    grouped: dict[str, dict] = {}
    for row in rows:
        part_id = str(row["part_id"])
        grouped.setdefault(
            part_id,
            {
                "part_id": part_id,
                "assembly_id": str(row["assembly_id"]),
                "assembly_number": str(row["assembly_number"]),
                "model_numbers": [],
            },
        )
        if row.get("model_number") is not None:
            grouped[part_id]["model_numbers"].append(str(row["model_number"]))
    result = []
    for row in grouped.values():
        model_numbers = list(dict.fromkeys(row.pop("model_numbers")))
        result.append({**row, "model_applicability": ", ".join(model_numbers)})
    return pd.DataFrame(
        result,
        columns=["part_id", "assembly_id", "assembly_number", "model_applicability"],
    )


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
    """Return saved part rules plus mapping-derived rows for linked assembly parts."""
    return pd.DataFrame(query(
        """SELECT r.part_id, r.feature_id, r.value, f.category, f.name AS feature_name
           FROM part_feature_rules r
           JOIN complexity_features f ON f.id=r.feature_id
           WHERE r.project_id=?
             AND NOT EXISTS (
                 SELECT 1 FROM manufacturing_assemblies assembly
                 WHERE assembly.project_id=r.project_id
                   AND assembly.catalog_part_id=r.part_id
             )
           UNION
           SELECT assembly.catalog_part_id AS part_id, value.feature_id, value.value,
                  f.category, f.name AS feature_name
           FROM manufacturing_assemblies assembly
           JOIN assembly_grid_model_mappings mapping
             ON mapping.project_id=assembly.project_id AND mapping.assembly_id=assembly.id
           JOIN project_models model
             ON model.id=mapping.model_id AND model.active=1
           JOIN model_feature_values value
             ON value.project_id=assembly.project_id AND value.model_id=model.id
           JOIN complexity_features f
             ON f.id=value.feature_id AND f.active=1
           WHERE assembly.project_id=? AND assembly.catalog_part_id IS NOT NULL
           ORDER BY category, feature_name, value""",
        (project_id, project_id),
    ))


def update_part_feature_rules(project_id: str, selections_by_part: dict[str, list[str]]) -> int:
    """Save feature rules and resolve them to official model numbers for downstream use."""
    features = complexity_features(project_id)
    feature_by_id = {str(row["id"]): row for _, row in features.iterrows()}
    tree = complexity_tree(project_id)
    valid_parts = {str(row["id"]) for row in query("SELECT id FROM parts WHERE project_id=?", (project_id,))}
    linked_parts = {
        str(row["part_id"]): str(row["assembly_number"])
        for row in query(
            """SELECT catalog_part_id AS part_id, assembly_number
               FROM manufacturing_assemblies
               WHERE project_id=? AND catalog_part_id IS NOT NULL""",
            (project_id,),
        )
    }
    derived_tokens: dict[str, set[str]] = {part_id: set() for part_id in linked_parts}
    for row in query(
        """SELECT assembly.catalog_part_id AS part_id, value.feature_id, value.value
           FROM manufacturing_assemblies assembly
           JOIN assembly_grid_model_mappings mapping
             ON mapping.project_id=assembly.project_id AND mapping.assembly_id=assembly.id
           JOIN project_models model ON model.id=mapping.model_id AND model.active=1
           JOIN model_feature_values value
             ON value.project_id=assembly.project_id AND value.model_id=model.id
           JOIN complexity_features feature
             ON feature.id=value.feature_id AND feature.active=1
           WHERE assembly.project_id=? AND assembly.catalog_part_id IS NOT NULL""",
        (project_id,),
    ):
        derived_tokens.setdefault(str(row["part_id"]), set()).add(
            f"{row['feature_id']}::{row['value']}"
        )
    timestamp = now_iso()
    updated = 0
    with connection() as conn:
        for part_id, raw_tokens in selections_by_part.items():
            if part_id not in valid_parts:
                continue
            tokens = [str(token).strip() for token in (raw_tokens or []) if str(token).strip()]
            if part_id in linked_parts:
                if set(tokens) != derived_tokens.get(part_id, set()):
                    raise ValueError(
                        f"Part number for assembly {linked_parts[part_id]} gets its model "
                        "applicability from the Assembly grid and cannot use Parts feature rules."
                    )
                continue
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
            reference_count += conn.execute(
                """SELECT COUNT(*) FROM parts part
                   WHERE part.project_id=? AND instr(part.model_applicability, ?) > 0
                     AND NOT EXISTS (
                         SELECT 1 FROM manufacturing_assemblies assembly
                         WHERE assembly.project_id=part.project_id
                           AND assembly.catalog_part_id=part.id
                     )""",
                (project_id, model_number),
            ).fetchone()[0]
            reference_count += conn.execute(
                """SELECT COUNT(*) FROM work_elements
                   WHERE project_id=? AND instr(model_applicability, ?) > 0""",
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
        _sync_assembly_catalog_part_applicability(conn, project_id, now_iso())
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
            _sync_assembly_catalog_part_applicability(conn, project_id, timestamp)
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
        assignments = ", ".join(f"{field}=?" for field in fields)
        for element_id, values in records:
            timestamp = now_iso()
            if element_id in existing_ids:
                conn.execute(
                    f"""UPDATE work_elements
                        SET {assignments}, updated_at=?
                        WHERE id=? AND project_id=? AND scenario_id=?""",
                    (*values, timestamp, element_id, project_id, scenario_id),
                )
            else:
                _create_work_element_with_started_ergonomics_review(
                    conn,
                    project_id,
                    scenario_id,
                    dict(zip(fields, values)),
                    timestamp,
                    work_element_id=element_id,
                )
        removed = existing_ids - saved_ids
        if removed:
            placeholders = ",".join("?" for _ in removed)
            protected_count = conn.execute(
                f"""SELECT COUNT(*) FROM pfmea_entries
                    WHERE project_id=? AND scenario_id=? AND work_element_id IN ({placeholders})""",
                (project_id, scenario_id, *removed),
            ).fetchone()[0]
            if protected_count:
                raise ValueError(
                    "Remove the linked PFMEA entries before deleting this Process at a Glance step."
                )
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
