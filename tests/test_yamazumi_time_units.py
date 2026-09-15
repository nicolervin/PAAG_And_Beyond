from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from utils import store


class YamazumiTimeUnitStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        connection_patcher = patch.object(store, "connection", self._connection)
        connection_patcher.start()
        self.addCleanup(connection_patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()

        self.project_id = "time-unit-project"
        self.scenario_id = "time-unit-scenario"
        self.other_scenario_id = "time-unit-other"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, created_at, updated_at)
                   VALUES (?, 'Time unit project', ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            for scenario_id, name, revision in (
                (self.scenario_id, "Primary", "TU-1"),
                (self.other_scenario_id, "Other", "TU-2"),
            ):
                conn.execute(
                    """INSERT INTO planning_scenarios
                       (id, project_id, name, revision_label, revision_sequence,
                        takt_time_s, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 1, 90, ?, ?)""",
                    (
                        scenario_id, self.project_id, name, revision,
                        timestamp, timestamp,
                    ),
                )

    @contextmanager
    def _connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def test_migration_is_idempotent_and_defaults_to_seconds(self) -> None:
        store.init_db()
        store.init_db()

        scenario = store.get_planning_scenario(self.project_id, self.scenario_id)

        self.assertEqual(scenario["yamazumi_time_unit"], "seconds")
        columns = {
            row[1] for row in self.conn.execute(
                "PRAGMA table_info(planning_scenarios)"
            ).fetchall()
        }
        self.assertIn("yamazumi_time_unit", columns)

    def test_legacy_scenario_table_is_upgraded_in_place(self) -> None:
        legacy_conn = sqlite3.connect(":memory:")
        legacy_conn.row_factory = sqlite3.Row
        legacy_conn.execute("PRAGMA foreign_keys = ON")
        legacy_conn.execute(
            """CREATE TABLE planning_scenarios (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                name TEXT NOT NULL,
                revision_label TEXT NOT NULL,
                revision_sequence INTEGER NOT NULL DEFAULT 1,
                parent_scenario_id TEXT,
                status TEXT NOT NULL DEFAULT 'Working',
                takt_time_s REAL NOT NULL DEFAULT 60,
                change_summary TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project_id, name),
                UNIQUE(project_id, revision_label)
            )"""
        )

        @contextmanager
        def legacy_connection():
            try:
                yield legacy_conn
                legacy_conn.commit()
            except Exception:
                legacy_conn.rollback()
                raise

        try:
            with patch.object(store, "connection", legacy_connection):
                store.init_db()
            columns = {
                row[1]
                for row in legacy_conn.execute(
                    "PRAGMA table_info(planning_scenarios)"
                ).fetchall()
            }
            units = {
                row[0]
                for row in legacy_conn.execute(
                    "SELECT yamazumi_time_unit FROM planning_scenarios"
                ).fetchall()
            }
            self.assertIn("yamazumi_time_unit", columns)
            self.assertEqual(units, {"seconds"})
        finally:
            legacy_conn.close()

    def test_update_is_scenario_scoped_and_does_not_rewrite_times(self) -> None:
        area_id = store.upsert_yamazumi_area(
            self.project_id, self.scenario_id, "Timed area", None, 75
        )
        pitch_id = store.add_yamazumi_pitch(
            self.project_id, area_id, "TU-001", "Timed pitch"
        )
        element_id = store.add_yamazumi_element(
            self.project_id,
            area_id,
            pitch_id,
            {"description": "Timed work", "time_s": 12.5},
        )

        result = store.update_yamazumi_time_unit(
            self.project_id, self.scenario_id, "Minutes"
        )

        self.assertEqual(result["old_unit"], "seconds")
        self.assertEqual(result["new_unit"], "minutes")
        self.assertEqual(
            store.get_planning_scenario(
                self.project_id, self.other_scenario_id
            )["yamazumi_time_unit"],
            "seconds",
        )
        self.assertEqual(
            store.query(
                "SELECT takt_override_s FROM yamazumi_areas WHERE id=?",
                (area_id,),
            )[0]["takt_override_s"],
            75,
        )
        self.assertEqual(
            store.query(
                "SELECT time_s FROM yamazumi_elements WHERE id=?", (element_id,)
            )[0]["time_s"],
            12.5,
        )

    def test_invalid_units_are_rejected_by_store_and_database(self) -> None:
        with self.assertRaisesRegex(ValueError, "Seconds, Minutes, or Hours"):
            store.update_yamazumi_time_unit(
                self.project_id, self.scenario_id, "days"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            with store.connection() as conn:
                conn.execute(
                    "UPDATE planning_scenarios SET yamazumi_time_unit='days' "
                    "WHERE id=?",
                    (self.scenario_id,),
                )

    def test_scenario_clone_preserves_source_yamazumi_unit(self) -> None:
        store.update_yamazumi_time_unit(
            self.project_id, self.scenario_id, "hours"
        )

        clone_id = store.clone_planning_scenario(
            self.project_id,
            self.scenario_id,
            "Hours clone",
            "TU-3",
            100,
        )

        self.assertEqual(
            store.get_planning_scenario(
                self.project_id, clone_id
            )["yamazumi_time_unit"],
            "hours",
        )

    def test_import_interprets_takt_and_work_in_saved_unit(self) -> None:
        store.update_yamazumi_time_unit(
            self.project_id, self.scenario_id, "minutes"
        )
        rows = pd.DataFrame([
            {
                "Sub-Line": "Imported minutes",
                "Pitch_number": "TU-010",
                "Pitch_status": "Active",
                "Pitch_name": "Import pitch",
                "Pitch_Takt_time": 1.5,
                "Model_variant": "Base",
                "Work_Type": "Cycle",
                "Work_Description": "Half minute",
                "Work_Time_to_complete": 0.5,
                "Work_region": "None",
            }
        ])

        store.import_yamazumi_rows(
            self.project_id, self.scenario_id, rows, {}
        )

        area = store.query(
            "SELECT id, takt_override_s FROM yamazumi_areas "
            "WHERE scenario_id=? AND name='Imported minutes'",
            (self.scenario_id,),
        )[0]
        element = store.query(
            "SELECT time_s FROM yamazumi_elements WHERE area_id=?",
            (area["id"],),
        )[0]
        self.assertEqual(area["takt_override_s"], 90)
        self.assertEqual(element["time_s"], 30)

    def test_invalid_import_time_rolls_back_complete_import(self) -> None:
        store.update_yamazumi_time_unit(
            self.project_id, self.scenario_id, "hours"
        )
        rows = pd.DataFrame([
            {
                "Sub-Line": "Invalid import",
                "Pitch_number": "TU-020",
                "Pitch_status": "Active",
                "Pitch_name": "Invalid",
                "Pitch_Takt_time": 1,
                "Model_variant": "Base",
                "Work_Type": "Cycle",
                "Work_Description": "Invalid time",
                "Work_Time_to_complete": float("inf"),
                "Work_region": "None",
            }
        ])

        with self.assertRaisesRegex(ValueError, "finite"):
            store.import_yamazumi_rows(
                self.project_id, self.scenario_id, rows, {}
            )

        self.assertEqual(
            store.query(
                "SELECT COUNT(*) AS count FROM yamazumi_areas "
                "WHERE scenario_id=? AND name='Invalid import'",
                (self.scenario_id,),
            )[0]["count"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
