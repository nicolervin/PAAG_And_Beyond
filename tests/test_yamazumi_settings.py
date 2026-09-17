from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from utils import store


class YamazumiSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        connection_patcher = patch.object(store, "connection", self._connection)
        connection_patcher.start()
        self.addCleanup(connection_patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()

        self.project_id = "settings-project"
        self.scenario_id = "settings-scenario"
        self.area_id = "settings-area"
        self.other_area_id = "settings-other-area"
        self.section_id = "settings-section"
        self.other_section_id = "settings-other-section"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects (id, name, created_at, updated_at)
                   VALUES (?, 'Settings project', ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence,
                    takt_time_s, created_at, updated_at)
                   VALUES (?, ?, 'Current', 'A', 1, 60, ?, ?)""",
                (self.scenario_id, self.project_id, timestamp, timestamp),
            )
            for section_id, name, sequence in (
                (self.section_id, "Main", 10),
                (self.other_section_id, "Other", 20),
            ):
                conn.execute(
                    """INSERT INTO assembly_sections
                       (id, project_id, name, section_type, sequence,
                        created_at, updated_at)
                       VALUES (?, ?, ?, 'Main spine', ?, ?, ?)""",
                    (
                        section_id,
                        self.project_id,
                        name,
                        sequence,
                        timestamp,
                        timestamp,
                    ),
                )
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES (?, ?, ?, 'Imported', ?)""",
                (self.area_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES (?, ?, ?, ?, 'Other area', ?)""",
                (
                    self.other_area_id,
                    self.project_id,
                    self.scenario_id,
                    self.other_section_id,
                    timestamp,
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

    def test_combined_save_is_atomic_and_records_changed_fields(self) -> None:
        result = store.update_yamazumi_settings(
            self.project_id,
            self.scenario_id,
            self.area_id,
            "minutes",
            self.section_id,
            75,
            "Settings tester",
        )

        self.assertTrue(result["changed"])
        self.assertTrue(result["time_unit_changed"])
        self.assertEqual(
            set(result["changes"]),
            {"yamazumi_time_unit", "takt_override_s", "section_id"},
        )
        scenario = self.conn.execute(
            "SELECT yamazumi_time_unit FROM planning_scenarios WHERE id=?",
            (self.scenario_id,),
        ).fetchone()
        area = self.conn.execute(
            "SELECT section_id, takt_override_s FROM yamazumi_areas WHERE id=?",
            (self.area_id,),
        ).fetchone()
        self.assertEqual(scenario[0], "minutes")
        self.assertEqual(area["section_id"], self.section_id)
        self.assertEqual(area["takt_override_s"], 75)
        history = store.audit_history(self.project_id, "Yamazumi")
        self.assertEqual(len(history), 1)
        self.assertEqual(history.iloc[0]["action"], "Save & Refresh")
        self.assertEqual(history.iloc[0]["editor_name"], "Settings tester")

    def test_invalid_pairing_rolls_back_unit_and_takt_changes(self) -> None:
        with self.assertRaisesRegex(ValueError, "already linked"):
            store.update_yamazumi_settings(
                self.project_id,
                self.scenario_id,
                self.area_id,
                "hours",
                self.other_section_id,
                80,
                "Settings tester",
            )

        scenario = self.conn.execute(
            "SELECT yamazumi_time_unit FROM planning_scenarios WHERE id=?",
            (self.scenario_id,),
        ).fetchone()
        area = self.conn.execute(
            "SELECT section_id, takt_override_s FROM yamazumi_areas WHERE id=?",
            (self.area_id,),
        ).fetchone()
        self.assertEqual(scenario[0], "seconds")
        self.assertIsNone(area["section_id"])
        self.assertIsNone(area["takt_override_s"])
        self.assertTrue(store.audit_history(self.project_id, "Yamazumi").empty)

    def test_no_change_writes_no_audit_event(self) -> None:
        result = store.update_yamazumi_settings(
            self.project_id,
            self.scenario_id,
            self.area_id,
            "seconds",
            None,
            None,
            "Settings tester",
        )

        self.assertFalse(result["changed"])
        self.assertEqual(result["changes"], {})
        self.assertTrue(store.audit_history(self.project_id, "Yamazumi").empty)


if __name__ == "__main__":
    unittest.main()
