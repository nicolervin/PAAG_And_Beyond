import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import pandas as pd
from streamlit.testing.v1 import AppTest

from utils import store


class ModelTreeScratchBomTests(unittest.TestCase):
    def setUp(self):
        self.database_path = store.DATA_DIR / f"test_bom_scratch_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.model_id = store.add_project_model(
            self.project_id, "TEST-M1", "Test Model 1", "For BOM from scratch testing"
        )

    def tearDown(self):
        self.database_patch.stop()
        if self.database_path.exists():
            self.database_path.unlink()

    def test_validation_empty_items(self):
        with self.assertRaises(ValueError) as ctx:
            store.save_manual_model_bom(self.project_id, self.model_id, [])
        self.assertIn("at least one item", str(ctx.exception).lower())

    def test_validation_level_skips(self):
        invalid_items = [
            {"level": 1, "part_number": "ASM-001", "quantity": 1.0},
            {"level": 3, "part_number": "PRT-001", "quantity": 1.0}, # skipped L2!
        ]
        with self.assertRaises(ValueError) as ctx:
            store.save_manual_model_bom(self.project_id, self.model_id, invalid_items)
        self.assertIn("cannot skip levels", str(ctx.exception).lower())

    def test_validation_quantity(self):
        invalid_items = [
            {"level": 1, "part_number": "ASM-001", "quantity": 0.0},
        ]
        with self.assertRaises(ValueError) as ctx:
            store.save_manual_model_bom(self.project_id, self.model_id, invalid_items)
        self.assertIn("greater than 0", str(ctx.exception).lower())

    def test_save_and_retrieve_manual_bom(self):
        items = [
            {"level": 1, "part_number": "ASM-TOP", "description": "Top Assembly", "quantity": 1.0},
            {"level": 2, "part_number": "SUB-DOOR", "description": "Door Assembly", "quantity": 1.0},
            {"level": 3, "part_number": "PRT-HNDL", "description": "Door Handle", "quantity": 2.0},
            {"level": 3, "part_number": "PRT-GSKT", "description": "Door Gasket", "quantity": 1.0},
            {"level": 2, "part_number": "SUB-CAB", "description": "Cabinet Assembly", "quantity": 1.0},
            {"level": 3, "part_number": "PRT-SHLF", "description": "Glass Shelf", "quantity": 3.0},
        ]

        res = store.save_manual_model_bom(
            self.project_id,
            self.model_id,
            items,
            auto_add_parts=True,
            editor="IE Tester",
        )
        self.assertEqual(res["saved_count"], 6)
        self.assertEqual(res["parts_created"], 6)
        self.assertEqual(res["model_number"], "TEST-M1")

        # Check retrieval via get_manual_model_bom
        retrieved = store.get_manual_model_bom(self.project_id, self.model_id)
        self.assertEqual(len(retrieved), 6)
        self.assertEqual(retrieved[0]["part_number"], "ASM-TOP")
        self.assertEqual(retrieved[0]["level"], 1)
        self.assertEqual(retrieved[2]["part_number"], "PRT-HNDL")
        self.assertEqual(retrieved[2]["level"], 3)
        self.assertEqual(retrieved[2]["quantity"], 2.0)

        # Check CAD model tree integration
        tree_res = store.pits_bom_model_tree(self.project_id, self.model_id)
        self.assertEqual(len(tree_res["roots"]), 1)
        root = tree_res["roots"][0]
        self.assertEqual(root["part_number"], "ASM-TOP")
        self.assertEqual(len(root["children"]), 2) # SUB-DOOR and SUB-CAB
        self.assertEqual(root["children"][0]["part_number"], "SUB-DOOR")
        self.assertEqual(len(root["children"][0]["children"]), 2) # PRT-HNDL and PRT-GSKT

        self.assertEqual(tree_res["metrics"]["total"], 6)
        self.assertEqual(tree_res["metrics"]["missing_catalog"], 0) # all auto-onboarded!

    def test_multi_model_isolation(self):
        model2_id = store.add_project_model(self.project_id, "TEST-M2", "Model 2", "")

        bom_m1 = [
            {"level": 1, "part_number": "TOP-1", "description": "Common Root", "quantity": 1.0},
            {"level": 2, "part_number": "PART-ONLY-M1", "description": "M1 Specific", "quantity": 1.0},
        ]
        bom_m2 = [
            {"level": 1, "part_number": "TOP-1", "description": "Common Root", "quantity": 1.0},
            {"level": 2, "part_number": "PART-ONLY-M2", "description": "M2 Specific", "quantity": 5.0},
        ]

        store.save_manual_model_bom(self.project_id, self.model_id, bom_m1, auto_add_parts=True)
        store.save_manual_model_bom(self.project_id, model2_id, bom_m2, auto_add_parts=True)

        tree_m1 = store.pits_bom_model_tree(self.project_id, self.model_id)
        m1_parts = [n["part_number"] for n in tree_m1["nodes"]]
        self.assertIn("PART-ONLY-M1", m1_parts)
        self.assertNotIn("PART-ONLY-M2", m1_parts)

        tree_m2 = store.pits_bom_model_tree(self.project_id, model2_id)
        m2_parts = [n["part_number"] for n in tree_m2["nodes"]]
        self.assertIn("PART-ONLY-M2", m2_parts)
        self.assertNotIn("PART-ONLY-M1", m2_parts)

    def test_bom_tree_page_smoke(self):
        page_path = Path(__file__).resolve().parent.parent / "app_pages" / "bom_tree.py"
        app = AppTest.from_file(str(page_path))
        app.session_state["project_id"] = self.project_id
        app.session_state["model_tree_selected_model"] = self.model_id
        app.run()
        self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main()
