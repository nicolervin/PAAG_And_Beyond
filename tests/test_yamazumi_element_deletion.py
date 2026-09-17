from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from utils import store


class YamazumiElementDeletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        patcher = patch.object(store, "connection", self._connection)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()

        self.project_id = "delete-project"
        self.scenario_id = "delete-scenario"
        self.other_scenario_id = "delete-other-scenario"
        self.area_id = "delete-area"
        self.other_area_id = "delete-other-area"
        self.pitch_id = "delete-pitch"
        self.element_id = "delete-element"
        self.other_element_id = "delete-other-element"
        self.process_id = "delete-process"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects (id, name, created_at, updated_at)
                   VALUES (?, 'Delete project', ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            for scenario_id, sequence, revision in (
                (self.scenario_id, 1, "A"),
                (self.other_scenario_id, 2, "B"),
            ):
                conn.execute(
                    """INSERT INTO planning_scenarios
                       (id, project_id, name, revision_label, revision_sequence,
                        takt_time_s, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 60, ?, ?)""",
                    (
                        scenario_id,
                        self.project_id,
                        scenario_id,
                        revision,
                        sequence,
                        timestamp,
                        timestamp,
                    ),
                )
            for area_id, scenario_id in (
                (self.area_id, self.scenario_id),
                (self.other_area_id, self.other_scenario_id),
            ):
                conn.execute(
                    """INSERT INTO yamazumi_areas
                       (id, project_id, scenario_id, name, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (area_id, self.project_id, scenario_id, area_id, timestamp),
                )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES (?, ?, ?, 'P-001', 'Delete pitch', ?)""",
                (self.pitch_id, self.project_id, self.area_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, updated_at)
                   VALUES (?, ?, ?, 10, 'P-001', 'Preserved process step', ?)""",
                (self.process_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, description, time_s,
                    process_element_id, process_sync_status, updated_at)
                   VALUES (?, ?, ?, ?, 'Delete this element', 12, ?, 'Synced', ?)""",
                (
                    self.element_id,
                    self.project_id,
                    self.area_id,
                    self.pitch_id,
                    self.process_id,
                    timestamp,
                ),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, description, time_s, updated_at)
                   VALUES (?, ?, ?, ?, 'Keep this element', 8, ?)""",
                (
                    self.other_element_id,
                    self.project_id,
                    self.area_id,
                    self.pitch_id,
                    timestamp,
                ),
            )
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, updated_at)
                   VALUES ('delete-part', ?, 'PART-DELETE', 'Legacy option', ?)""",
                (self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_element_material_groups
                   (id, project_id, scenario_id, yamazumi_element_id, name, updated_at)
                   VALUES ('delete-group', ?, ?, ?, 'Legacy group', ?)""",
                (self.project_id, self.scenario_id, self.element_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_element_material_options
                   (id, group_id, part_id, updated_at)
                   VALUES ('delete-option', 'delete-group', 'delete-part', ?)""",
                (timestamp,),
            )
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, name, updated_at)
                   VALUES ('process-group', ?, ?, ?, 'Preserved group', ?)""",
                (self.project_id, self.scenario_id, self.process_id, timestamp),
            )
            conn.execute(
                """INSERT INTO ergonomics_reviews
                   (id, project_id, scenario_id, work_element_id, created_at, updated_at)
                   VALUES ('process-review', ?, ?, ?, ?, ?)""",
                (
                    self.project_id,
                    self.scenario_id,
                    self.process_id,
                    timestamp,
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

    def count(self, table: str, record_id: str) -> int:
        return int(
            self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE id=?", (record_id,)
            ).fetchone()[0]
        )

    def test_impact_and_delete_preserve_process_data_and_remove_legacy_dependents(self) -> None:
        impact = store.yamazumi_element_delete_impact(
            self.project_id, self.scenario_id, self.area_id, self.element_id
        )

        self.assertEqual(impact["description"], "Delete this element")
        self.assertEqual(impact["pitch_number"], "P-001")
        self.assertTrue(impact["process_step_exists"])
        self.assertEqual(impact["process_element_id"], self.process_id)
        self.assertEqual(impact["legacy_material_group_count"], 1)
        self.assertEqual(impact["legacy_material_option_count"], 1)

        result = store.delete_yamazumi_element(
            self.project_id, self.scenario_id, self.area_id, self.element_id
        )

        self.assertEqual(result, impact)
        self.assertEqual(self.count("yamazumi_elements", self.element_id), 0)
        self.assertEqual(self.count("yamazumi_elements", self.other_element_id), 1)
        self.assertEqual(self.count("yamazumi_pitches", self.pitch_id), 1)
        self.assertEqual(self.count("work_element_material_groups", "delete-group"), 0)
        self.assertEqual(self.count("work_element_material_options", "delete-option"), 0)
        self.assertEqual(self.count("work_elements", self.process_id), 1)
        self.assertEqual(self.count("process_part_groups", "process-group"), 1)
        self.assertEqual(self.count("ergonomics_reviews", "process-review"), 1)

    def test_wrong_scenario_and_repeated_delete_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "planning scenario"):
            store.delete_yamazumi_element(
                self.project_id,
                self.other_scenario_id,
                self.area_id,
                self.element_id,
            )
        self.assertEqual(self.count("yamazumi_elements", self.element_id), 1)

        store.delete_yamazumi_element(
            self.project_id, self.scenario_id, self.area_id, self.element_id
        )
        with self.assertRaisesRegex(ValueError, "planning scenario"):
            store.delete_yamazumi_element(
                self.project_id, self.scenario_id, self.area_id, self.element_id
            )


if __name__ == "__main__":
    unittest.main()
