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
            {"level": 1, "part_number": "TOP-M1", "description": "M1 Root", "quantity": 1.0},
            {"level": 2, "part_number": "PART-ONLY-M1", "description": "M1 Specific", "quantity": 1.0},
        ]
        bom_m2 = [
            {"level": 1, "part_number": "TOP-M2", "description": "M2 Root", "quantity": 1.0},
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

    def test_level1_assembly_unique_validation(self):
        bom_m1 = [
            {"level": 1, "part_number": "TOP-SHARED", "description": "M1 Root", "quantity": 1.0},
            {"level": 2, "part_number": "PRT-1", "description": "Part 1", "quantity": 1.0},
        ]
        store.save_manual_model_bom(self.project_id, self.model_id, bom_m1, auto_add_parts=True)

        model2_id = store.add_project_model(self.project_id, "TEST-M2", "Model 2", "")
        bom_m2_duplicate = [
            {"level": 1, "part_number": "TOP-SHARED", "description": "Same Top Assembly", "quantity": 1.0},
            {"level": 2, "part_number": "PRT-2", "description": "Part 2", "quantity": 1.0},
        ]
        with self.assertRaises(ValueError) as ctx:
            store.save_manual_model_bom(self.project_id, model2_id, bom_m2_duplicate, auto_add_parts=True)
        self.assertIn("already assigned to model 'TEST-M1'", str(ctx.exception))

    def test_copy_model_bom_requires_level2_differences(self):
        bom_m1 = [
            {"level": 1, "part_number": "TOP-M1-SRC", "description": "Source Root", "quantity": 1.0},
            {"level": 2, "part_number": "SUB-DOOR", "description": "Door Sub", "quantity": 1.0},
            {"level": 3, "part_number": "PRT-HNDL", "description": "Handle", "quantity": 2.0},
        ]
        store.save_manual_model_bom(self.project_id, self.model_id, bom_m1, auto_add_parts=True)

        model2_id = store.add_project_model(self.project_id, "TEST-M2", "Model 2", "")
        # Exact clone of Level 2+ with changed Level 1
        copied_identical_l2 = [
            {"level": 1, "part_number": "TOP-M2-NEW", "description": "New Root", "quantity": 1.0},
            {"level": 2, "part_number": "SUB-DOOR", "description": "Door Sub", "quantity": 1.0},
            {"level": 3, "part_number": "PRT-HNDL", "description": "Handle", "quantity": 2.0},
        ]

        # Saving with source_model_id should fail because Level 2+ is 100% identical
        with self.assertRaises(ValueError) as ctx:
            store.save_manual_model_bom(
                self.project_id,
                model2_id,
                copied_identical_l2,
                auto_add_parts=True,
                source_model_id=self.model_id,
            )
        self.assertIn("100% identical", str(ctx.exception))

        # Modifying a quantity in Level 2+ allows save to succeed
        copied_varied = [
            {"level": 1, "part_number": "TOP-M2-NEW", "description": "New Root", "quantity": 1.0},
            {"level": 2, "part_number": "SUB-DOOR", "description": "Door Sub", "quantity": 1.0},
            {"level": 3, "part_number": "PRT-HNDL", "description": "Handle", "quantity": 4.0}, # changed qty!
        ]
        res = store.save_manual_model_bom(
            self.project_id,
            model2_id,
            copied_varied,
            auto_add_parts=True,
            source_model_id=self.model_id,
        )
        self.assertEqual(res["saved_count"], 3)

    def test_auto_detect_and_fill_catalog_description(self):
        # Pre-seed a part with description in catalog
        store.upsert_part(
            self.project_id,
            {
                "part_number": "PRT-CATALOG-XYZ",
                "description": "Catalog Premium Glass Shelf",
            },
        )

        bom_items = [
            {"level": 1, "part_number": "TOP-DESC-TEST", "description": "Top Root", "quantity": 1.0},
            {"level": 2, "part_number": "PRT-CATALOG-XYZ", "description": "", "quantity": 2.0}, # empty desc
        ]
        store.save_manual_model_bom(self.project_id, self.model_id, bom_items, auto_add_parts=True)

        retrieved = store.get_manual_model_bom(self.project_id, self.model_id)
        self.assertEqual(len(retrieved), 2)
        self.assertEqual(retrieved[1]["part_number"], "PRT-CATALOG-XYZ")
        self.assertEqual(retrieved[1]["description"], "Catalog Premium Glass Shelf")

    def test_get_known_subassembly_structure(self):
        bom_items = [
            {"level": 1, "part_number": "TOP-SUB-TEST", "description": "Root", "quantity": 1.0},
            {"level": 2, "part_number": "SUB-DOOR-X", "description": "Door Assembly", "quantity": 1.0},
            {"level": 3, "part_number": "PRT-BOLT-1", "description": "Hinge Bolt", "quantity": 4.0},
            {"level": 3, "part_number": "PRT-SEAL-1", "description": "Door Seal", "quantity": 1.0},
        ]
        store.save_manual_model_bom(self.project_id, self.model_id, bom_items, auto_add_parts=True)

        sub_children = store.get_known_subassembly_structure(self.project_id, "SUB-DOOR-X")
        self.assertEqual(len(sub_children), 2)
        pns = [c["part_number"] for c in sub_children]
        self.assertIn("PRT-BOLT-1", pns)
        self.assertIn("PRT-SEAL-1", pns)

    def test_get_model_level1_assemblies(self):
        bom_items = [
            {"level": 1, "part_number": "ASM-TOP-01", "description": "Top Root", "quantity": 1.0},
        ]
        store.save_manual_model_bom(self.project_id, self.model_id, bom_items, auto_add_parts=True)

        lvl1_map = store.get_model_level1_assemblies(self.project_id)
        self.assertEqual(lvl1_map.get("ASM-TOP-01"), "TEST-M1")

    def test_part_number_not_transferred_to_pits_id_column(self):
        items = [
            {"level": 1, "part_number": "PRT-NEW-99", "description": "Brand New Part", "quantity": 1.0},
        ]
        res = store.save_manual_model_bom(
            self.project_id, self.model_id, items, auto_add_parts=True
        )
        self.assertEqual(res["parts_created"], 1)

        row = store.query(
            "SELECT part_number, pits_tracker_number FROM parts WHERE project_id=? AND part_number='PRT-NEW-99'",
            (self.project_id,),
        )[0]
        self.assertEqual(row["part_number"], "PRT-NEW-99")
        self.assertEqual(row["pits_tracker_number"], "")

        # Test cleanup if an existing part erroneously had pits_tracker_number == part_number
        store.query(
            "UPDATE parts SET pits_tracker_number='PRT-NEW-99' WHERE project_id=? AND part_number='PRT-NEW-99'",
            (self.project_id,),
        )
        store.save_manual_model_bom(
            self.project_id, self.model_id, items, auto_add_parts=True
        )
        row_cleaned = store.query(
            "SELECT pits_tracker_number FROM parts WHERE project_id=? AND part_number='PRT-NEW-99'",
            (self.project_id,),
        )[0]
        self.assertEqual(row_cleaned["pits_tracker_number"], "")

    def test_quantity_five_decimal_places(self):
        items = [
            {"level": 1, "part_number": "TOP-DEC-5", "description": "Decimal Root", "quantity": 1.0},
            {"level": 2, "part_number": "PRT-ADHESIVE", "description": "Structural Glue (kg)", "quantity": 0.00025},
            {"level": 2, "part_number": "PRT-SEALANT", "description": "Silicone Sealant (L)", "quantity": 0.00001},
            {"level": 2, "part_number": "PRT-WIRE-GA", "description": "Wire Harness Lead (m)", "quantity": 1.12345},
        ]
        store.save_manual_model_bom(
            self.project_id, self.model_id, items, auto_add_parts=True
        )

        retrieved = store.get_manual_model_bom(self.project_id, self.model_id)
        self.assertEqual(len(retrieved), 4)
        self.assertEqual(retrieved[1]["quantity"], 0.00025)
        self.assertEqual(retrieved[2]["quantity"], 0.00001)
        self.assertEqual(retrieved[3]["quantity"], 1.12345)

        # Check model tree structure export
        tree_res = store.pits_bom_model_tree(self.project_id, model_id=self.model_id)
        qty_map = {n["part_number"]: n["quantity"] for n in tree_res["nodes"]}
        self.assertEqual(qty_map.get("PRT-ADHESIVE"), 0.00025)
        self.assertEqual(qty_map.get("PRT-SEALANT"), 0.00001)
        self.assertEqual(qty_map.get("PRT-WIRE-GA"), 1.12345)

    def test_save_over_existing_bom_syncs_catalog_description_and_quantities(self):
        # 1. Initial BOM save
        initial_items = [
            {"level": 1, "part_number": "ASM-SYNC-1", "description": "Original Root", "quantity": 1.0},
            {"level": 2, "part_number": "PRT-SYNC-A", "description": "Original Screw", "quantity": 2.0},
            {"level": 2, "part_number": "PRT-SYNC-B", "description": "Original Nut", "quantity": 4.0},
        ]
        store.save_manual_model_bom(
            self.project_id, self.model_id, initial_items, auto_add_parts=True
        )

        # Verify initial parts catalog descriptions
        p_a = store.query(
            "SELECT description FROM parts WHERE project_id=? AND part_number='PRT-SYNC-A'",
            (self.project_id,),
        )[0]
        self.assertEqual(p_a["description"], "Original Screw")

        # 2. Update BOM over top with new descriptions and new decimal quantities
        updated_items = [
            {"level": 1, "part_number": "ASM-SYNC-1", "description": "Updated Root Asm", "quantity": 1.0},
            {"level": 2, "part_number": "PRT-SYNC-A", "description": "Upgraded Hex Screw M5", "quantity": 2.50000},
            {"level": 2, "part_number": "PRT-SYNC-B", "description": "Locking Flange Nut M5", "quantity": 6.12345},
            {"level": 2, "part_number": "PRT-SYNC-C", "description": "New Washer M5", "quantity": 0.00050},
        ]
        store.save_manual_model_bom(
            self.project_id, self.model_id, updated_items, auto_add_parts=True
        )

        # 3. Verify Parts Catalog synced the new descriptions
        p_a_updated = store.query(
            "SELECT description FROM parts WHERE project_id=? AND part_number='PRT-SYNC-A'",
            (self.project_id,),
        )[0]
        self.assertEqual(p_a_updated["description"], "Upgraded Hex Screw M5")

        p_b_updated = store.query(
            "SELECT description FROM parts WHERE project_id=? AND part_number='PRT-SYNC-B'",
            (self.project_id,),
        )[0]
        self.assertEqual(p_b_updated["description"], "Locking Flange Nut M5")

        # 4. Verify get_manual_model_bom reflects updated descriptions and quantities
        retrieved = store.get_manual_model_bom(self.project_id, self.model_id)
        desc_map = {r["part_number"]: r["description"] for r in retrieved}
        qty_map = {r["part_number"]: r["quantity"] for r in retrieved}

        self.assertEqual(desc_map["PRT-SYNC-A"], "Upgraded Hex Screw M5")
        self.assertEqual(desc_map["PRT-SYNC-B"], "Locking Flange Nut M5")
        self.assertEqual(desc_map["PRT-SYNC-C"], "New Washer M5")
        self.assertEqual(qty_map["PRT-SYNC-A"], 2.50000)
        self.assertEqual(qty_map["PRT-SYNC-B"], 6.12345)
        self.assertEqual(qty_map["PRT-SYNC-C"], 0.00050)

        # 5. Verify pits_bom_model_tree nodes reflect updated descriptions and quantities
        tree_res = store.pits_bom_model_tree(self.project_id, model_id=self.model_id)
        tree_desc_map = {n["part_number"]: n["description"] for n in tree_res["nodes"]}
        tree_qty_map = {n["part_number"]: n["quantity"] for n in tree_res["nodes"]}

        self.assertEqual(tree_desc_map["PRT-SYNC-A"], "Upgraded Hex Screw M5")
        self.assertEqual(tree_desc_map["PRT-SYNC-B"], "Locking Flange Nut M5")
        self.assertEqual(tree_desc_map["PRT-SYNC-C"], "New Washer M5")
        self.assertEqual(tree_qty_map["PRT-SYNC-A"], 2.50000)
        self.assertEqual(tree_qty_map["PRT-SYNC-B"], 6.12345)
        self.assertEqual(tree_qty_map["PRT-SYNC-C"], 0.00050)

    def test_save_duplicate_part_under_same_parent(self):
        items = [
            {"level": 1, "part_number": "ASM-DUP-TOP", "description": "Duplicate Test Top", "quantity": 1.0},
            {"level": 2, "part_number": "PRT-CLIP", "description": "Snap Clip A", "quantity": 1.0},
            {"level": 2, "part_number": "PRT-CLIP", "description": "Snap Clip B", "quantity": 2.0},
        ]
        # Should save without UNIQUE constraint error
        store.save_manual_model_bom(
            self.project_id, self.model_id, items, auto_add_parts=True
        )
        retrieved = store.get_manual_model_bom(self.project_id, self.model_id)
        self.assertEqual(len(retrieved), 3)
        clips = [r for r in retrieved if r["part_number"] == "PRT-CLIP"]
        self.assertEqual(len(clips), 2)
        self.assertEqual(clips[0]["quantity"], 1.0)
        self.assertEqual(clips[1]["quantity"], 2.0)

    def test_bom_tree_page_smoke(self):
        page_path = Path(__file__).resolve().parent.parent / "app_pages" / "bom_tree.py"
        app = AppTest.from_file(str(page_path))
        app.session_state["project_id"] = self.project_id
        app.session_state["model_tree_selected_model"] = self.model_id
        app.run()
        self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main()
