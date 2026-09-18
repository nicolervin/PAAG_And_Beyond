from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from utils import store


class YamazumiFlagRetirementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        connection_patcher = patch.object(store, "connection", self._connection)
        connection_patcher.start()
        self.addCleanup(connection_patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()

        self.project_id = "flag-retirement-project"
        self.scenario_id = "flag-retirement-scenario"
        self.area_id = "flag-retirement-area"
        self.pitch_id = "flag-retirement-pitch"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects (id, name, created_at, updated_at)
                   VALUES (?, 'Flag retirement', ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence,
                    takt_time_s, created_at, updated_at)
                   VALUES (?, ?, 'Current', 'A', 1, 60, ?, ?)""",
                (self.scenario_id, self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES (?, ?, ?, 'Main', ?)""",
                (self.area_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES (?, ?, ?, 'P-001', 'Pitch one', ?)""",
                (self.pitch_id, self.project_id, self.area_id, timestamp),
            )

    @contextmanager
    def _connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def test_schema_migration_drops_flags_and_preserves_element_dependencies(self) -> None:
        element_id = "legacy-flagged-element"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute("ALTER TABLE yamazumi_elements ADD COLUMN flags TEXT DEFAULT '[]'")
            conn.execute(
                """CREATE TABLE yamazumi_flag_definitions (
                       id TEXT PRIMARY KEY,
                       project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                       name TEXT NOT NULL,
                       updated_at TEXT NOT NULL
                   )"""
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, description, time_s,
                    flags, updated_at)
                   VALUES (?, ?, ?, ?, 'Install part', 12, '["CTQ"]', ?)""",
                (element_id, self.project_id, self.area_id, self.pitch_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_flag_definitions
                   (id, project_id, name, updated_at)
                   VALUES ('legacy-ctq', ?, 'CTQ', ?)""",
                (self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_element_material_groups
                   (id, project_id, scenario_id, yamazumi_element_id, name, updated_at)
                   VALUES ('material-group', ?, ?, ?, 'Fasteners', ?)""",
                (self.project_id, self.scenario_id, element_id, timestamp),
            )
            store.record_audit_event(
                self.project_id,
                "Yamazumi flag definitions",
                "Legacy save",
                1,
                "Test editor",
                _conn=conn,
            )

        store.init_db()
        store.init_db()

        columns = {
            row[1]
            for row in self.conn.execute(
                "PRAGMA table_info(yamazumi_elements)"
            ).fetchall()
        }
        self.assertNotIn("flags", columns)
        self.assertIsNone(
            self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='yamazumi_flag_definitions'"
            ).fetchone()
        )
        element = self.conn.execute(
            "SELECT description, pitch_id, time_s FROM yamazumi_elements WHERE id=?",
            (element_id,),
        ).fetchone()
        self.assertEqual(dict(element), {
            "description": "Install part",
            "pitch_id": self.pitch_id,
            "time_s": 12.0,
        })
        dependency = self.conn.execute(
            "SELECT yamazumi_element_id FROM work_element_material_groups WHERE id='material-group'"
        ).fetchone()
        self.assertEqual(dependency[0], element_id)
        audit = self.conn.execute(
            """SELECT action FROM audit_log
               WHERE project_id=? AND table_name='Yamazumi flag definitions'""",
            (self.project_id,),
        ).fetchone()
        self.assertEqual(audit[0], "Legacy save")

    def test_element_writes_ignore_legacy_flag_input(self) -> None:
        element_id = store.add_yamazumi_element(
            self.project_id,
            self.area_id,
            self.pitch_id,
            {
                "description": "Flag-free work",
                "time_s": 4,
                "model_variants": ["Base"],
                "work_type": "Cycle",
                "work_region": "None",
                "flags": ["CTQ"],
            },
        )
        saved = store.yamazumi_elements(self.project_id, self.area_id)
        self.assertIn(element_id, set(saved["id"]))
        self.assertNotIn("flags", saved.columns)

        edited = saved.copy()
        edited.loc[edited["id"] == element_id, "description"] = "Updated work"
        store.replace_yamazumi_elements(self.project_id, self.area_id, edited)
        updated = self.conn.execute(
            "SELECT description FROM yamazumi_elements WHERE id=?",
            (element_id,),
        ).fetchone()[0]
        self.assertEqual(updated, "Updated work")

    def test_legacy_import_flag_column_is_ignored(self) -> None:
        rows = pd.DataFrame([{
            "Sub-Line": "Imported",
            "Pitch_number": "P-IMPORT",
            "Pitch_status": "Active",
            "Pitch_name": "Imported pitch",
            "Pitch_Takt_time": 60,
            "Model_variant": "Base",
            "Work_Type": "Cycle",
            "Work_Description": "Imported work",
            "Work_Time_to_complete": 6,
            "Work_region": "None",
            "Pitch_Flags": "CTQ Safety",
        }])

        store.import_yamazumi_rows(
            self.project_id, self.scenario_id, rows, {}
        )

        imported = self.conn.execute(
            "SELECT description FROM yamazumi_elements WHERE description='Imported work'"
        ).fetchone()
        self.assertIsNotNone(imported)
        self.assertNotIn(
            "flags",
            {row[1] for row in self.conn.execute("PRAGMA table_info(yamazumi_elements)")},
        )

    def test_reconciliation_stops_deriving_ctq_and_preserves_existing_text(self) -> None:
        element_id = store.add_yamazumi_element(
            self.project_id,
            self.area_id,
            self.pitch_id,
            {
                "description": "Reconciled work",
                "time_s": 5,
                "model_variants": ["Base"],
                "work_type": "Cycle",
                "work_region": "None",
            },
        )

        store.reconcile_yamazumi_to_process(
            self.project_id, self.scenario_id, [element_id]
        )
        process_id = self.conn.execute(
            "SELECT process_element_id FROM yamazumi_elements WHERE id=?",
            (element_id,),
        ).fetchone()[0]
        quality_text = self.conn.execute(
            "SELECT quality_requirement FROM work_elements WHERE id=?",
            (process_id,),
        ).fetchone()[0]
        self.assertEqual(quality_text, "")

        self.conn.execute(
            "UPDATE work_elements SET quality_requirement='CTQ' WHERE id=?",
            (process_id,),
        )
        self.conn.commit()
        store.reconcile_yamazumi_to_process(
            self.project_id, self.scenario_id, [element_id]
        )
        preserved = self.conn.execute(
            "SELECT quality_requirement FROM work_elements WHERE id=?",
            (process_id,),
        ).fetchone()[0]
        self.assertEqual(preserved, "CTQ")


if __name__ == "__main__":
    unittest.main()
