"""Shared SQLite infrastructure and schema initialization for PAAG stores."""

from __future__ import annotations

import sqlite3

import json

import hashlib

import math

import re

from contextlib import closing, contextmanager, nullcontext

from datetime import datetime, timezone

from pathlib import Path

from uuid import uuid4

import pandas as pd

from utils.quality_store import (
    clone_quality_requirement_assignments,
    init_quality_schema,
)

from utils.pfmea_store import (
    PFMEA_CTQ_CLASSIFICATIONS,
    clone_pfmea_scenario,
    init_pfmea_schema,
)

from utils.pfmea_pattern_store import init_pfmea_pattern_schema

from utils.yamazumi_stack import UNASSIGNED_STACK_ID, build_stack_draft

from utils.time_units import display_to_seconds, normalize_time_unit

from utils.control_plan_store import clone_control_plan_scenario, init_control_plan_schema

from utils.equipment_store import clone_equipment_scenario, init_equipment_schema
from utils.layout_store import init_layout_schema

from utils.yamazumi_naming import (
    format_yamazumi_pitch_address,
    normalize_yamazumi_line_code,
    parse_yamazumi_pitch_address as parse_guided_yamazumi_pitch_address,
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


def init_process_visual_media_schema(conn: sqlite3.Connection) -> None:
    """Initialize database tables for scenario-owned pitch visual aids and element tags."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS process_visual_media (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            pitch_id TEXT NOT NULL REFERENCES yamazumi_pitches(id) ON DELETE CASCADE,
            media_type TEXT NOT NULL CHECK(media_type IN ('image', 'video')),
            file_path TEXT NOT NULL,
            original_file_path TEXT NOT NULL DEFAULT '',
            annotations_json TEXT NOT NULL DEFAULT '',
            caption TEXT NOT NULL DEFAULT '',
            sequence INTEGER NOT NULL DEFAULT 10,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS process_visual_media_tags (
            id TEXT PRIMARY KEY,
            media_id TEXT NOT NULL REFERENCES process_visual_media(id) ON DELETE CASCADE,
            work_element_id TEXT NOT NULL REFERENCES work_elements(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            UNIQUE(media_id, work_element_id)
        );
        CREATE INDEX IF NOT EXISTS idx_process_visual_media_pitch
            ON process_visual_media(project_id, scenario_id, pitch_id);
        CREATE INDEX IF NOT EXISTS idx_process_visual_media_tags_media
            ON process_visual_media_tags(media_id);
        CREATE INDEX IF NOT EXISTS idx_process_visual_media_tags_element
            ON process_visual_media_tags(work_element_id);
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(process_visual_media)").fetchall()}
    if "annotations_json" not in cols:
        conn.execute("ALTER TABLE process_visual_media ADD COLUMN annotations_json TEXT NOT NULL DEFAULT ''")
    if "original_file_path" not in cols:
        conn.execute("ALTER TABLE process_visual_media ADD COLUMN original_file_path TEXT NOT NULL DEFAULT ''")


def clone_process_visual_media_scenario(
    conn: sqlite3.Connection,
    project_id: str,
    source_scenario_id: str,
    new_scenario_id: str,
    pitch_id_map: dict[str, str],
    process_id_map: dict[str, str],
    timestamp: str,
) -> None:
    """Clone scenario visual aids and re-link element tags to cloned pitch and work elements."""
    media_id_map: dict[str, str] = {}
    source_media_rows = conn.execute(
        """SELECT * FROM process_visual_media
           WHERE project_id=? AND scenario_id=?
           ORDER BY sequence, created_at, id""",
        (project_id, source_scenario_id),
    ).fetchall()
    for row in source_media_rows:
        item = dict(row)
        old_id = str(item["id"])
        old_pitch_id = str(item["pitch_id"])
        new_pitch_id = pitch_id_map.get(old_pitch_id)
        if not new_pitch_id:
            tag_elem = conn.execute(
                """SELECT y.pitch_id FROM process_visual_media_tags t
                   JOIN yamazumi_elements y ON (
                       y.process_element_id = t.work_element_id
                       OR (y.process_element_id IS NULL AND y.id = t.work_element_id)
                   )
                   WHERE t.media_id=? AND y.pitch_id IS NOT NULL LIMIT 1""",
                (old_id,),
            ).fetchone()
            if tag_elem and str(tag_elem[0]) in pitch_id_map:
                new_pitch_id = pitch_id_map[str(tag_elem[0])]
            else:
                continue
        new_media_id = str(uuid4())
        media_id_map[old_id] = new_media_id
        item.update(
            id=new_media_id,
            scenario_id=new_scenario_id,
            pitch_id=new_pitch_id,
            updated_at=timestamp,
        )
        columns = list(item)
        conn.execute(
            f"INSERT INTO process_visual_media ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            tuple(item[col] for col in columns),
        )

    source_tag_rows = conn.execute(
        """SELECT * FROM process_visual_media_tags
           WHERE project_id=? AND scenario_id=?""",
        (project_id, source_scenario_id),
    ).fetchall()
    for row in source_tag_rows:
        tag = dict(row)
        old_media_id = str(tag["media_id"])
        old_work_id = str(tag["work_element_id"])
        new_media_id = media_id_map.get(old_media_id)
        new_work_id = process_id_map.get(old_work_id)
        if not new_media_id or not new_work_id:
            continue
        tag.update(
            id=str(uuid4()),
            media_id=new_media_id,
            work_element_id=new_work_id,
            scenario_id=new_scenario_id,
            created_at=timestamp,
        )
        columns = list(tag)
        conn.execute(
            f"INSERT INTO process_visual_media_tags ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            tuple(tag[col] for col in columns),
        )


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
    conn = get_db_connection()
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
                revision TEXT DEFAULT '0',
                design_maturity TEXT NOT NULL DEFAULT '',
                subsystem TEXT NOT NULL DEFAULT '',
                source TEXT DEFAULT 'Manual', image_path TEXT DEFAULT '',
                model_applicability TEXT DEFAULT 'All', notes TEXT DEFAULT '', weight_lb REAL,
                technology_engineer TEXT NOT NULL DEFAULT '',
                design_engineer TEXT NOT NULL DEFAULT '',
                pits_tracker_number TEXT NOT NULL DEFAULT '',
                source_code TEXT NOT NULL DEFAULT ''
                    CHECK (source_code IN ('', '1', '+1', '2', '2.4', '3', '4', '5', '6', '7', '8')),
                official_windchill_part_name TEXT NOT NULL DEFAULT '',
                factory_nickname TEXT NOT NULL DEFAULT '',
                make_buy TEXT NOT NULL DEFAULT ''
                    CHECK (make_buy IN ('', 'Make', 'Buy')),
                ppm TEXT NOT NULL DEFAULT '',
                buyer_gcl TEXT NOT NULL DEFAULT '',
                pmqe_aqe TEXT NOT NULL DEFAULT '',
                ame_tooling_engineer TEXT NOT NULL DEFAULT '',
                part_code TEXT NOT NULL DEFAULT '',
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
            CREATE TABLE IF NOT EXISTS table_view_preferences (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                editor_name TEXT NOT NULL DEFAULT '',
                view_key TEXT NOT NULL,
                visible_columns_json TEXT NOT NULL DEFAULT '[]',
                column_order_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project_id, editor_name, view_key)
            );
            CREATE INDEX IF NOT EXISTS idx_table_view_preferences_project
                ON table_view_preferences(project_id, view_key, editor_name);
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
                resource_type TEXT NOT NULL DEFAULT 'Human',
                resource_detail TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS safety_requirements (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
                work_element_id TEXT NOT NULL REFERENCES work_elements(id) ON DELETE CASCADE,
                requirement_description TEXT NOT NULL,
                ppe TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_safety_requirements_scenario
                ON safety_requirements(project_id, scenario_id, work_element_id, active);
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
            CREATE INDEX IF NOT EXISTS idx_part_images_part
                ON part_images(part_id);
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
            CREATE INDEX IF NOT EXISTS idx_model_feature_values_project
                ON model_feature_values(project_id);
            CREATE TABLE IF NOT EXISTS part_feature_rules (
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                part_id TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
                feature_id TEXT NOT NULL REFERENCES complexity_features(id) ON DELETE CASCADE,
                value TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(part_id, feature_id, value)
            );
            CREATE INDEX IF NOT EXISTS idx_part_feature_rules_project
                ON part_feature_rules(project_id);
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
                notes TEXT DEFAULT '',
                pits_sync_status TEXT NOT NULL DEFAULT 'Not linked'
                    CHECK(pits_sync_status IN ('Not linked', 'In sync', 'Quantity differs', 'No longer found')),
                pits_quantity_updated_at TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pits_bom_imports (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                import_sequence INTEGER NOT NULL CHECK(import_sequence > 0),
                workbook_name TEXT NOT NULL DEFAULT '',
                workbook_sha256 TEXT NOT NULL,
                bom_sheet_name TEXT NOT NULL DEFAULT 'BOM',
                source_row_count INTEGER NOT NULL DEFAULT 0 CHECK(source_row_count >= 0),
                occurrence_count INTEGER NOT NULL DEFAULT 0 CHECK(occurrence_count >= 0),
                issue_count INTEGER NOT NULL DEFAULT 0 CHECK(issue_count >= 0),
                imported_by TEXT NOT NULL DEFAULT '',
                imported_at TEXT NOT NULL,
                UNIQUE(project_id, import_sequence)
            );
            CREATE TABLE IF NOT EXISTS pits_bom_occurrences (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                parent_tracker_number TEXT NOT NULL,
                child_tracker_number TEXT NOT NULL CHECK(TRIM(child_tracker_number) <> ''),
                parent_part_id TEXT REFERENCES parts(id) ON DELETE SET NULL,
                child_part_id TEXT REFERENCES parts(id) ON DELETE SET NULL,
                proposed_depth INTEGER NOT NULL CHECK(proposed_depth BETWEEN 1 AND 11),
                raw_quantity_text TEXT NOT NULL DEFAULT '',
                proposed_quantity REAL,
                source_row INTEGER NOT NULL CHECK(source_row > 0),
                raw_levels_json TEXT NOT NULL DEFAULT '{}',
                source_fingerprint TEXT NOT NULL,
                reviewed_source_fingerprint TEXT,
                review_status TEXT NOT NULL DEFAULT 'Needs review'
                    CHECK(review_status IN ('Needs review', 'Approved', 'Rejected')),
                source_state TEXT NOT NULL DEFAULT 'New'
                    CHECK(source_state IN ('New', 'Current', 'Changed', 'Missing')),
                validation_issues_json TEXT NOT NULL DEFAULT '[]',
                confirmed_section_id TEXT REFERENCES assembly_sections(id) ON DELETE RESTRICT,
                approved_assignment_id TEXT UNIQUE
                    REFERENCES fishbone_part_assignments(id) ON DELETE RESTRICT,
                first_seen_import_id TEXT NOT NULL REFERENCES pits_bom_imports(id) ON DELETE RESTRICT,
                last_seen_import_id TEXT NOT NULL REFERENCES pits_bom_imports(id) ON DELETE RESTRICT,
                last_reviewed_import_id TEXT REFERENCES pits_bom_imports(id) ON DELETE RESTRICT,
                reviewed_by TEXT NOT NULL DEFAULT '',
                reviewed_at TEXT,
                rejection_reason TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project_id, parent_tracker_number, child_tracker_number)
            );
            CREATE TABLE IF NOT EXISTS pits_bom_occurrence_revisions (
                id TEXT PRIMARY KEY,
                occurrence_id TEXT NOT NULL REFERENCES pits_bom_occurrences(id) ON DELETE CASCADE,
                import_id TEXT NOT NULL REFERENCES pits_bom_imports(id) ON DELETE RESTRICT,
                revision_no INTEGER NOT NULL CHECK(revision_no > 0),
                source_row INTEGER NOT NULL CHECK(source_row > 0),
                proposed_depth INTEGER NOT NULL CHECK(proposed_depth BETWEEN 1 AND 11),
                raw_quantity_text TEXT NOT NULL DEFAULT '',
                proposed_quantity REAL,
                raw_levels_json TEXT NOT NULL DEFAULT '{}',
                source_fingerprint TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                UNIQUE(occurrence_id, revision_no),
                UNIQUE(occurrence_id, source_fingerprint)
            );
            CREATE TABLE IF NOT EXISTS pits_bom_occurrence_concerns (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                occurrence_id TEXT NOT NULL REFERENCES pits_bom_occurrences(id) ON DELETE CASCADE,
                concern_id TEXT NOT NULL REFERENCES concerns(id) ON DELETE CASCADE,
                escalated_source_state TEXT NOT NULL
                    CHECK(escalated_source_state IN ('New', 'Changed', 'Missing')),
                escalated_source_fingerprint TEXT NOT NULL,
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(occurrence_id, concern_id)
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                table_name TEXT NOT NULL, action TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0,
                editor_name TEXT DEFAULT '', details TEXT DEFAULT '{}', created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_log_project_table_created
                ON audit_log(project_id, table_name, created_at);
            CREATE TABLE IF NOT EXISTS project_transfer_events (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                operation TEXT NOT NULL CHECK(operation IN ('Export', 'Import')),
                package_version INTEGER NOT NULL,
                manifest_json TEXT NOT NULL,
                source_project_id TEXT NOT NULL,
                source_project_name TEXT NOT NULL DEFAULT '',
                target_project_id TEXT,
                target_project_name TEXT NOT NULL DEFAULT '',
                record_counts_json TEXT NOT NULL DEFAULT '{}',
                conflicts_json TEXT NOT NULL DEFAULT '[]',
                editor_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
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
        init_pfmea_pattern_schema(conn)
        init_control_plan_schema(conn)
        init_equipment_schema(conn)
        init_layout_schema(conn)
        init_process_visual_media_schema(conn)
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
        if "source_code" not in part_columns:
            conn.execute("ALTER TABLE parts ADD COLUMN source_code TEXT DEFAULT ''")
            part_columns.add("source_code")
        for part in conn.execute(
            """SELECT record.project_id, record.part_number, record.source_payload
               FROM pits_records record
               JOIN parts catalog
                 ON catalog.project_id=record.project_id
                AND catalog.part_number=record.part_number
                AND catalog.source='PITS snapshot'
               WHERE TRIM(record.part_number) <> ''
                 AND (catalog.source_code IS NULL OR catalog.source_code = '')"""
        ).fetchall():
            try:
                payload = json.loads(part["source_payload"] or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            source_code = str(
                payload.get("source_code")
                or payload.get("sourcecode")
                or payload.get("source_code_t")
                or ""
            ).strip()
            revision = str(payload.get("revision") or "").strip()
            conn.execute(
                """UPDATE parts SET revision=?, source_code=?
                   WHERE project_id=? AND part_number=? AND source='PITS snapshot'""",
                (revision, source_code, part["project_id"], part["part_number"]),
            )
        if "weight_lb" not in part_columns:
            conn.execute("ALTER TABLE parts ADD COLUMN weight_lb REAL")
        for column in (
            "technology_engineer",
            "design_engineer",
            "pits_tracker_number",
            "source_code",
            "official_windchill_part_name",
            "factory_nickname",
            "make_buy",
            "ppm",
            "buyer_gcl",
            "pmqe_aqe",
            "ame_tooling_engineer",
            "part_code",
            "subsystem",
            "design_maturity",
        ):
            if column not in part_columns:
                conn.execute(
                    f"ALTER TABLE parts ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                )
                part_columns.add(column)
        conn.execute(
            """UPDATE parts SET design_engineer = technology_engineer
               WHERE (design_engineer IS NULL OR design_engineer = '')
                 AND (technology_engineer IS NOT NULL AND technology_engineer <> '')"""
        )
        conn.execute(
            """UPDATE parts SET technology_engineer = design_engineer
               WHERE (technology_engineer IS NULL OR technology_engineer = '')
                 AND (design_engineer IS NOT NULL AND design_engineer <> '')"""
        )
        conn.execute(
            """UPDATE parts SET factory_nickname = official_windchill_part_name
               WHERE (factory_nickname IS NULL OR factory_nickname = '')
                 AND (official_windchill_part_name IS NOT NULL AND official_windchill_part_name <> '')"""
        )
        conn.execute(
            """UPDATE parts SET official_windchill_part_name = factory_nickname
               WHERE (official_windchill_part_name IS NULL OR official_windchill_part_name = '')
                 AND (factory_nickname IS NOT NULL AND factory_nickname <> '')"""
        )
        conn.execute(
            """UPDATE parts SET design_maturity = revision
               WHERE (design_maturity IS NULL OR design_maturity = '')
                 AND (revision IS NOT NULL AND revision <> '')"""
        )
        conn.execute(
            """UPDATE parts SET revision = design_maturity
               WHERE (revision IS NULL OR revision = '' OR revision = '0')
                 AND (design_maturity IS NOT NULL AND design_maturity <> '')"""
        )
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_parts_project_pits_tracker_number
               ON parts(project_id, pits_tracker_number)
               WHERE pits_tracker_number <> ''"""
        )
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
        assignment_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(fishbone_part_assignments)"
            ).fetchall()
        }
        if "pits_sync_status" not in assignment_columns:
            conn.execute(
                "ALTER TABLE fishbone_part_assignments ADD COLUMN pits_sync_status "
                "TEXT NOT NULL DEFAULT 'Not linked' "
                "CHECK(pits_sync_status IN "
                "('Not linked', 'In sync', 'Quantity differs', 'No longer found'))"
            )
        if "pits_quantity_updated_at" not in assignment_columns:
            conn.execute(
                "ALTER TABLE fishbone_part_assignments ADD COLUMN pits_quantity_updated_at TEXT"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fishbone_assignment_part ON fishbone_part_assignments(project_id, part_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pits_bom_occurrence_state "
            "ON pits_bom_occurrences(project_id, source_state, review_status)"
        )
        conn.execute(
            """CREATE TRIGGER IF NOT EXISTS trg_fishbone_assignment_pits_quantity_sync
               AFTER UPDATE OF quantity ON fishbone_part_assignments
               BEGIN
                   UPDATE fishbone_part_assignments
                   SET pits_sync_status=COALESCE((
                       SELECT CASE
                           WHEN occurrence.source_state='Missing' THEN 'No longer found'
                           WHEN occurrence.proposed_quantity IS NOT NULL
                            AND ROUND(occurrence.proposed_quantity, 9)=ROUND(NEW.quantity, 9)
                               THEN 'In sync'
                           ELSE 'Quantity differs'
                       END
                       FROM pits_bom_occurrences occurrence
                       WHERE occurrence.project_id=NEW.project_id
                         AND occurrence.approved_assignment_id=NEW.id
                   ), 'Not linked')
                   WHERE id=NEW.id;
               END"""
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
        if "resource_type" not in work_columns:
            conn.execute("ALTER TABLE work_elements ADD COLUMN resource_type TEXT NOT NULL DEFAULT 'Human'")
        if "resource_detail" not in work_columns:
            conn.execute("ALTER TABLE work_elements ADD COLUMN resource_detail TEXT NOT NULL DEFAULT ''")
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

        safety_req_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(safety_requirements)").fetchall()
        }
        if "ppe" not in safety_req_columns:
            conn.execute("ALTER TABLE safety_requirements ADD COLUMN ppe TEXT NOT NULL DEFAULT ''")

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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_project_table_created "
            "ON audit_log(project_id, table_name, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_part_feature_rules_project "
            "ON part_feature_rules(project_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_part_images_part "
            "ON part_images(part_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_model_feature_values_project "
            "ON model_feature_values(project_id)"
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

def get_db_connection() -> sqlite3.Connection:
    """Return a configured SQLite connection owned by the caller."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


import functools as _functools
import importlib as _importlib
import sys as _sys
import types as _types

_DOMAIN_MODULES: list[_types.ModuleType] = []
_DOMAIN_EXPORTS: dict[str, list[str]] = {}


def register_domain_module(module: _types.ModuleType, exports: list[str]) -> None:
    """Register one extracted store and share symbols across store domains."""
    if module not in _DOMAIN_MODULES:
        _DOMAIN_MODULES.append(module)
    _DOMAIN_EXPORTS[module.__name__] = list(exports)
    sync_store_runtime()


def store_runtime_symbols() -> dict[str, object]:
    symbols = {
        name: value
        for name, value in globals().items()
        if not name.startswith("__")
        and name not in {
            "_DOMAIN_MODULES", "_DOMAIN_EXPORTS", "_functools", "_importlib",
            "_sys", "_types",
        }
    }
    for module in _DOMAIN_MODULES:
        for name in _DOMAIN_EXPORTS.get(module.__name__, []):
            symbols[name] = getattr(module, name)
    facade = _sys.modules.get("utils.store")
    if facade is not None:
        for name in tuple(symbols):
            if name in facade.__dict__:
                symbols[name] = facade.__dict__[name]
    return symbols


def sync_store_runtime() -> None:
    symbols = store_runtime_symbols()
    globals().update(symbols)
    for module in _DOMAIN_MODULES:
        module.__dict__.update(symbols)


def domain_entrypoint(function):
    """Ensure every domain can also be imported and called directly."""
    @_functools.wraps(function)
    def wrapped(*args, **kwargs):
        _importlib.import_module("utils.store")
        sync_store_runtime()
        return function(*args, **kwargs)
    return wrapped

__store_exports__ = ['ROOT', 'DATA_DIR', 'UPLOAD_DIR', 'DB_PATH', 'HANDLING_TYPES', 'YAMAZUMI_PITCH_TYPES', 'YAMAZUMI_FEEDER_PITCH_TYPES', 'ERGONOMICS_REVIEW_STATUSES', 'ERGONOMICS_RISK_CLASSIFICATIONS', 'now_iso', '_drop_yamazumi_flags_schema', '_upgrade_ergonomics_reviews_work_element_link', '_upgrade_ergonomics_reviews_risk_classification', '_create_started_ergonomics_review', '_create_work_element_with_started_ergonomics_review', '_backfill_missing_ergonomics_reviews', '_clone_ergonomics_reviews', 'clone_process_visual_media_scenario', 'init_process_visual_media_schema', 'parse_yamazumi_model_variants', 'connection', 'init_db', 'query', 'execute', 'record_audit_event', 'audit_history', 'backup_database', 'get_db_connection']
