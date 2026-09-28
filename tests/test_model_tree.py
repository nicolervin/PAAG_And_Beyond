from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from streamlit.testing.v1 import AppTest

from utils import store


class ModelTreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_model_tree_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])

    def tearDown(self) -> None:
        self.database_patch.stop()
        if self.database_path.exists():
            self.database_path.unlink()

    def test_pits_bom_model_tree_empty(self) -> None:
        tree = store.pits_bom_model_tree(self.project_id)
        self.assertEqual(tree["roots"], [])
        self.assertEqual(tree["nodes"], [])
        self.assertEqual(tree["metrics"]["total"], 0)
        self.assertEqual(tree["metrics"]["placed_fishbone"], 0)
        self.assertEqual(tree["metrics"]["missing_fishbone"], 0)
        self.assertEqual(tree["metrics"]["missing_catalog"], 0)

    def test_pits_bom_model_tree_reconciliation_and_hierarchy(self) -> None:
        # 1. Create section
        store.add_assembly_section(self.project_id, "Main Spine", "Main spine", None, "tester")
        section_id = str(store.assembly_sections(self.project_id).iloc[0]["id"])

        # 2. Add catalog part
        part1_id = str(uuid4())
        ts = store.now_iso()
        store.execute(
            """INSERT INTO parts (id, project_id, part_number, description, weight_lb, make_buy, model_applicability, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (part1_id, self.project_id, "PART-100", "Placed bracket", 1.5, "Make", "All", ts),
        )
        part2_id = str(uuid4())
        store.execute(
            """INSERT INTO parts (id, project_id, part_number, description, weight_lb, make_buy, model_applicability, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (part2_id, self.project_id, "PART-200", "Unplaced screw", 0.05, "Buy", "All", ts),
        )

        # 3. Place part1 into fishbone
        store.execute(
            """INSERT INTO fishbone_part_assignments (id, project_id, part_id, section_id, quantity, use_description, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), self.project_id, part1_id, section_id, 2.0, "Mounting bracket", store.now_iso()),
        )

        # 4. Insert PITS BOM occurrences:
        import_id = str(uuid4())
        ts = store.now_iso()
        store.execute(
            """INSERT INTO pits_bom_imports (
                id, project_id, import_sequence, workbook_name, workbook_sha256,
                bom_sheet_name, source_row_count, occurrence_count, issue_count,
                imported_by, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (import_id, self.project_id, 1, "test.xlsx", "sha", "BOM", 4, 4, 0, "tester", ts),
        )

        def add_occ(parent_trk: str, child_trk: str, child_pid: str | None, depth: int, qty: float, row_num: int):
            store.execute(
                """INSERT INTO pits_bom_occurrences (
                    id, project_id, parent_tracker_number, child_tracker_number, child_part_id,
                    proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                    source_fingerprint, first_seen_import_id, last_seen_import_id,
                    first_seen_at, last_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()), self.project_id, parent_trk, child_trk, child_pid,
                    depth, qty, str(qty), row_num,
                    f"fp_{child_trk}", import_id, import_id,
                    ts, ts, ts,
                ),
            )

        # L1: Root assembly (Tracker 10)
        add_occ("", "10", None, 1, 1.0, 1)
        # L2: Child 1: PART-100 (Tracker 20) -> In catalog, In fishbone
        add_occ("10", "20", part1_id, 2, 2.0, 2)
        # L2: Child 2: PART-200 (Tracker 30) -> In catalog, Missing from fishbone
        add_occ("10", "30", part2_id, 2, 4.0, 3)
        # L2: Child 3: Uncataloged (Tracker 40) -> Missing from catalog, Missing from fishbone
        add_occ("10", "40", None, 2, 1.0, 4)

        # 5. Query tree
        tree = store.pits_bom_model_tree(self.project_id)
        metrics = tree["metrics"]

        self.assertEqual(metrics["total"], 4)
        self.assertEqual(metrics["placed_fishbone"], 1)
        self.assertEqual(metrics["missing_fishbone"], 3)
        self.assertEqual(metrics["missing_catalog"], 2)  # Root (None) + Child 40 (None)

        self.assertEqual(len(tree["roots"]), 1)
        root = tree["roots"][0]
        self.assertEqual(root["child_tracker"], "10")
        self.assertEqual(len(root["children"]), 3)

        # Child 20 checks
        child_20 = next(c for c in root["children"] if c["child_tracker"] == "20")
        self.assertTrue(child_20["in_catalog"])
        self.assertTrue(child_20["in_fishbone"])
        self.assertEqual(child_20["fishbone_sections"], ["Main Spine"])

        # Child 30 checks
        child_30 = next(c for c in root["children"] if c["child_tracker"] == "30")
        self.assertTrue(child_30["in_catalog"])
        self.assertFalse(child_30["in_fishbone"])

        # Child 40 checks
        child_40 = next(c for c in root["children"] if c["child_tracker"] == "40")
        self.assertFalse(child_40["in_catalog"])
        self.assertFalse(child_40["in_fishbone"])

    def test_model_tree_page_smoke(self) -> None:
        file_path = str(Path(__file__).parent.parent / "app_pages" / "bom_tree.py")
        at = AppTest.from_file(file_path)
        at.session_state["project_id"] = self.project_id
        at.session_state["scenario_id"] = self.scenario_id
        at.run()
        self.assertEqual(at.exception, [])


if __name__ == "__main__":
    unittest.main()
