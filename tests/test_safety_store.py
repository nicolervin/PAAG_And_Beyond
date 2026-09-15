from __future__ import annotations

import sqlite3
import unittest
import json
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from utils import pfmea_store, store


class SafetyStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        patcher = patch.object(store, "connection", self._connection)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()
        self.project_id = "safety-project"
        self.scenario_id = "safety-scenario"
        self.other_scenario_id = "other-safety-scenario"
        self.work_ids = ["ctq-work", "safety-work", "both-work", "plain-work"]
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, revision, status, takt_time_s, created_at, updated_at)
                   VALUES (?, 'Safety project', 'A', 'Draft', 60, ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            for scenario_id, name, sequence in (
                (self.scenario_id, "Current", 1),
                (self.other_scenario_id, "Other", 2),
            ):
                conn.execute(
                    """INSERT INTO planning_scenarios
                       (id, project_id, name, revision_label, revision_sequence,
                        status, takt_time_s, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'Working', 60, ?, ?)""",
                    (
                        scenario_id, self.project_id, name, str(sequence), sequence,
                        timestamp, timestamp,
                    ),
                )
            for sequence, work_id in enumerate(self.work_ids, start=1):
                conn.execute(
                    """INSERT INTO work_elements
                       (id, project_id, scenario_id, sequence, station, operation, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        work_id, self.project_id, self.scenario_id, sequence * 10,
                        f"ST-{sequence:03d}", f"Operation {sequence}", timestamp,
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

    def add_pfmea(self, work_id: str, classification: str) -> None:
        pfmea_store.save_pfmea_entry_rows(
            self.project_id,
            self.scenario_id,
            work_id,
            pd.DataFrame([
                {
                    "id": "",
                    "potential_failure_mode": "Failure",
                    "class_code": classification,
                }
            ]),
        )

    def save_safety(self, work_id: str, *, active: bool = True) -> str:
        result = store.save_safety_requirements(
            self.project_id,
            self.scenario_id,
            pd.DataFrame([
                {
                    "id": "",
                    "work_element_id": work_id,
                    "requirement_description": "Guard the pinch point",
                    "active": active,
                }
            ]),
            "Safety tester",
        )
        return str(result["created_ids"][0])

    def test_live_criticality_returns_ctq_safety_both_and_neither(self) -> None:
        self.add_pfmea("ctq-work", "E")
        self.add_pfmea("both-work", "P-")
        self.save_safety("safety-work")
        both_requirement_id = self.save_safety("both-work")

        audit_count_before = int(self.conn.execute(
            "SELECT COUNT(*) FROM audit_log"
        ).fetchone()[0])
        tags = store.work_element_criticality(self.project_id, self.scenario_id)
        self.assertEqual(
            int(self.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]),
            audit_count_before,
        )
        self.assertEqual(tags["ctq-work"], ["CTQ"])
        self.assertEqual(tags["safety-work"], ["Safety"])
        self.assertEqual(tags["both-work"], ["CTQ", "Safety"])
        self.assertEqual(tags["plain-work"], [])

        rows = store.safety_requirements(self.project_id, self.scenario_id)
        rows.loc[rows["id"].astype(str) == both_requirement_id, "active"] = 0
        store.save_safety_requirements(
            self.project_id, self.scenario_id, rows, "Safety tester"
        )
        tags = store.work_element_criticality(self.project_id, self.scenario_id)
        self.assertEqual(tags["both-work"], ["CTQ"])
        with store.connection() as conn:
            conn.execute(
                """UPDATE pfmea_entries SET class_code='S'
                   WHERE project_id=? AND scenario_id=? AND work_element_id='ctq-work'""",
                (self.project_id, self.scenario_id),
            )
        tags = store.work_element_criticality(self.project_id, self.scenario_id)
        self.assertEqual(tags["ctq-work"], [])

    def test_only_confirmed_ctq_equivalent_codes_create_ctq_tag(self) -> None:
        for work_id, classification in zip(
            self.work_ids, ["S", "R", "M", "Q"], strict=True
        ):
            self.add_pfmea(work_id, classification)
        tags = store.work_element_criticality(self.project_id, self.scenario_id)
        self.assertEqual(tags["ctq-work"], [])
        self.assertEqual(tags["safety-work"], [])
        self.assertEqual(tags["both-work"], [])
        self.assertEqual(tags["plain-work"], ["CTQ"])

    def test_safety_save_validates_scenario_and_delete_is_audited(self) -> None:
        requirement_id = self.save_safety("safety-work")
        with self.assertRaisesRegex(ValueError, "active project and scenario"):
            store.save_safety_requirements(
                self.project_id,
                self.other_scenario_id,
                pd.DataFrame([
                    {
                        "id": "",
                        "work_element_id": "safety-work",
                        "requirement_description": "Wrong scenario",
                        "active": True,
                    }
                ]),
                "Safety tester",
            )
        result = store.delete_safety_requirements(
            self.project_id, self.scenario_id, [requirement_id], "Safety tester"
        )
        self.assertEqual(result["row_count"], 1)
        events = self.conn.execute(
            """SELECT action, editor_name FROM audit_log
               WHERE table_name='Safety requirements' ORDER BY created_at"""
        ).fetchall()
        self.assertEqual(events[-1]["action"], "Delete")
        self.assertEqual(events[-1]["editor_name"], "Safety tester")

    def test_scenario_clone_remaps_safety_work_element(self) -> None:
        self.save_safety("safety-work")
        cloned_id = store.clone_planning_scenario(
            self.project_id,
            self.scenario_id,
            "Clone",
            "C",
            60,
            created_by="Safety tester",
        )
        cloned = store.safety_requirements(self.project_id, cloned_id)
        self.assertEqual(len(cloned), 1)
        self.assertNotEqual(str(cloned.iloc[0]["work_element_id"]), "safety-work")
        cloned_work = self.conn.execute(
            "SELECT scenario_id FROM work_elements WHERE id=?",
            (str(cloned.iloc[0]["work_element_id"]),),
        ).fetchone()
        self.assertEqual(cloned_work["scenario_id"], cloned_id)

    def test_process_delete_impact_and_cascade_are_scenario_safe(self) -> None:
        requirement_id = self.save_safety("safety-work")
        impact = store.safety_requirement_delete_impact(
            self.project_id, self.scenario_id, ["safety-work"]
        )
        self.assertEqual(impact, {"requirement_count": 1, "work_element_count": 1})
        with self.assertRaisesRegex(ValueError, "active scenario"):
            store.safety_requirement_delete_impact(
                self.project_id, self.other_scenario_id, ["safety-work"]
            )

        rows = store.project_table(
            "work_elements", self.project_id, "sequence", scenario_id=self.scenario_id
        )
        store.replace_work_elements(
            self.project_id,
            self.scenario_id,
            rows.loc[rows["id"].astype(str) != "safety-work"].copy(),
        )
        self.assertFalse(self.conn.execute(
            "SELECT 1 FROM safety_requirements WHERE id=?", (requirement_id,)
        ).fetchone())
        self.assertTrue(self.conn.execute(
            "SELECT 1 FROM work_elements WHERE id='ctq-work'"
        ).fetchone())

    def test_legacy_flag_migration_is_audited_once_and_drops_storage(self) -> None:
        with store.connection() as conn:
            conn.execute("ALTER TABLE yamazumi_elements ADD COLUMN flags TEXT DEFAULT '[]'")
            conn.execute(
                """CREATE TABLE yamazumi_flag_definitions (
                       id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                       name TEXT NOT NULL, description TEXT DEFAULT '', active INTEGER,
                       system_flag INTEGER, sequence INTEGER, updated_at TEXT NOT NULL)"""
            )
            conn.execute(
                """INSERT INTO yamazumi_flag_definitions
                   (id, project_id, name, active, system_flag, sequence, updated_at)
                   VALUES ('legacy-flag', ?, 'CTQ', 1, 1, 10, ?)""",
                (self.project_id, store.now_iso()),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES ('legacy-area', ?, ?, 'Legacy area', ?)""",
                (self.project_id, self.scenario_id, store.now_iso()),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, description, flags, updated_at)
                   VALUES ('legacy-element', ?, 'legacy-area', 'Legacy work',
                           '["CTQ"]', ?)""",
                (self.project_id, store.now_iso()),
            )
        with self.assertRaisesRegex(ValueError, "Current editor"):
            store.migrate_legacy_yamazumi_flags(self.project_id, "")
        first = store.migrate_legacy_yamazumi_flags(self.project_id, "Safety tester")
        second = store.migrate_legacy_yamazumi_flags(self.project_id, "Safety tester")
        self.assertEqual(first["definition_count"], 1)
        self.assertEqual(first["affected_element_count"], 1)
        self.assertEqual(second["definition_count"], 0)
        self.assertNotIn(
            "flags", [row["name"] for row in self.conn.execute("PRAGMA table_info(yamazumi_elements)")]
        )
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='yamazumi_flag_definitions'"
        ).fetchone())
        events = self.conn.execute(
            "SELECT * FROM audit_log WHERE action='Retire legacy flags'"
        ).fetchall()
        self.assertEqual(len(events), 1)
        details = json.loads(events[0]["details"])
        self.assertEqual(details["definition_count"], 1)
        self.assertEqual(details["affected_element_count"], 1)
        self.assertNotIn("CTQ", events[0]["details"])


if __name__ == "__main__":
    unittest.main()
