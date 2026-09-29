from __future__ import annotations

import inspect
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from utils import (
    assembly_store,
    db_core,
    ergonomics_store,
    fishbone_store,
    model_part_store,
    process_store,
    project_store,
    safety_store,
    store,
    yamazumi_store,
)


class StoreFacadeCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_store_facade_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_facade_reexports_each_domain_with_original_signatures(self) -> None:
        expected = {
            project_store: "clone_planning_scenario",
            model_part_store: "upsert_part",
            assembly_store: "assembly_grid_categories",
            fishbone_store: "assembly_section_walk_order",
            yamazumi_store: "save_yamazumi_stack_draft",
            process_store: "replace_work_elements",
            ergonomics_store: "save_ergonomics_review_rows",
            safety_store: "save_safety_requirements",
        }
        for module, name in expected.items():
            with self.subTest(module=module.__name__, name=name):
                self.assertTrue(hasattr(store, name))
                self.assertEqual(
                    inspect.signature(getattr(module, name)),
                    inspect.signature(getattr(store, name)),
                )

    def test_facade_database_path_patch_propagates_to_db_core(self) -> None:
        self.assertEqual(self.database_path, db_core.DB_PATH)
        with store.connection() as conn:
            self.assertEqual(1, conn.execute("PRAGMA foreign_keys").fetchone()[0])
            self.assertEqual("wal", str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower())

    def test_connection_rolls_back_complete_transaction_on_failure(self) -> None:
        project_id = f"rollback-{uuid4()}"
        timestamp = store.now_iso()
        with self.assertRaisesRegex(RuntimeError, "force rollback"):
            with store.connection() as conn:
                conn.execute(
                    """INSERT INTO projects
                       (id, name, program, product_line, owner, revision, status,
                        takt_time_s, notes, created_at, updated_at)
                       VALUES (?, 'Rollback project', '', '', '', 'A', 'Draft',
                               60, '', ?, ?)""",
                    (project_id, timestamp, timestamp),
                )
                raise RuntimeError("force rollback")
        self.assertEqual([], store.query("SELECT id FROM projects WHERE id=?", (project_id,)))

    def test_work_element_foreign_key_is_enforced(self) -> None:
        project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        scenario_id = str(store.planning_scenarios(project_id)[0]["id"])
        timestamp = store.now_iso()
        with self.assertRaises(sqlite3.IntegrityError):
            with store.connection() as conn:
                conn.execute(
                    """INSERT INTO safety_requirements
                       (id, project_id, scenario_id, work_element_id,
                        requirement_description, active, created_at, updated_at)
                       VALUES (?, ?, ?, 'missing-work-element', 'Invalid', 1, ?, ?)""",
                    (str(uuid4()), project_id, scenario_id, timestamp, timestamp),
                )


if __name__ == "__main__":
    unittest.main()
