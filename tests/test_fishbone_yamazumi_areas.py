from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from utils import store


class FishboneYamazumiAreaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_fishbone_yamazumi_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.primary_scenario_id = str(
            store.planning_scenarios(self.project_id)[0]["id"]
        )
        self.archived_scenario_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence,
                    status, takt_time_s, created_at, updated_at)
                   VALUES (?, ?, 'Archived branch', 'ARCH', 99,
                           'Archived', 60, ?, ?)""",
                (
                    self.archived_scenario_id,
                    self.project_id,
                    timestamp,
                    timestamp,
                ),
            )

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_new_main_and_subassembly_create_areas_in_every_scenario(self) -> None:
        main_id = store.add_assembly_section(
            self.project_id, "Automatic main", "Main spine", None, ""
        )
        child_id = store.add_assembly_section(
            self.project_id, "Automatic child", "Subassembly", main_id, ""
        )

        for section_id, expected_name in (
            (main_id, "Automatic main"),
            (child_id, "Automatic child"),
        ):
            rows = store.query(
                """SELECT id, project_id, scenario_id, section_id, name,
                          takt_override_s
                   FROM yamazumi_areas
                   WHERE project_id=? AND section_id=? ORDER BY scenario_id""",
                (self.project_id, section_id),
            )
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                {str(row["scenario_id"]) for row in rows},
                {self.primary_scenario_id, self.archived_scenario_id},
            )
            self.assertEqual({str(row["name"]) for row in rows}, {expected_name})
            self.assertTrue(all(row["takt_override_s"] is None for row in rows))
            self.assertEqual(len({str(row["id"]) for row in rows}), 2)

    def test_creation_is_idempotent(self) -> None:
        section_id = store.add_assembly_section(
            self.project_id, "Idempotent area", "Main spine", None, ""
        )
        timestamp = store.now_iso()
        with store.connection() as conn:
            result = store._create_yamazumi_areas_for_section(
                conn,
                self.project_id,
                section_id,
                "Idempotent area",
                timestamp,
            )

        self.assertEqual(result, {"created": [], "conflicts": []})
        self.assertEqual(
            store.query(
                "SELECT COUNT(*) AS count FROM yamazumi_areas WHERE section_id=?",
                (section_id,),
            )[0]["count"],
            2,
        )

    def test_same_name_conflict_is_preserved_and_other_scenarios_continue(self) -> None:
        conflict_area_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name,
                    takt_override_s, updated_at)
                   VALUES (?, ?, ?, NULL, 'Preserved imported area', 75, ?)""",
                (
                    conflict_area_id,
                    self.project_id,
                    self.archived_scenario_id,
                    store.now_iso(),
                ),
            )

        section_id = store.add_assembly_section(
            self.project_id,
            "Preserved imported area",
            "Main spine",
            None,
            "",
        )
        summary = store.yamazumi_area_creation_summary(
            self.project_id, section_id
        )

        self.assertEqual(len(summary["created"]), 1)
        self.assertEqual(summary["created"][0]["scenario_id"], self.primary_scenario_id)
        self.assertEqual(len(summary["conflicts"]), 1)
        self.assertEqual(
            summary["conflicts"][0]["scenario_id"], self.archived_scenario_id
        )
        preserved = store.query(
            "SELECT section_id, takt_override_s FROM yamazumi_areas WHERE id=?",
            (conflict_area_id,),
        )[0]
        self.assertIsNone(preserved["section_id"])
        self.assertEqual(preserved["takt_override_s"], 75)


if __name__ == "__main__":
    unittest.main()
