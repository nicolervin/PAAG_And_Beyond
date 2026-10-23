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

    def test_pits_bom_model_tree_with_model_usages_and_outline_hierarchy(self) -> None:
        import json

        # 1. Create two models
        store.add_project_model(self.project_id, "MODEL-A-01", "Model A", "tester")
        store.add_project_model(self.project_id, "MODEL-B-02", "Model B", "tester")
        models_df = store.project_models(self.project_id)
        model_a = models_df[models_df["model_number"] == "MODEL-A-01"].iloc[0]
        model_b = models_df[models_df["model_number"] == "MODEL-B-02"].iloc[0]

        import_id = str(uuid4())
        ts = store.now_iso()
        store.execute(
            """INSERT INTO pits_bom_imports (
                id, project_id, import_sequence, workbook_name, workbook_sha256,
                bom_sheet_name, source_row_count, occurrence_count, issue_count,
                imported_by, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (import_id, self.project_id, 2, "test_models.xlsx", "sha_m", "BOM", 5, 5, 0, "tester", ts),
        )

        def add_usage_occ(parent_trk: str, child_trk: str, depth: int, row_num: int, usages: dict[str, float]):
            raw_json = json.dumps({"Level": depth, "model_usages": usages})
            first_qty = next(iter(usages.values()))
            store.execute(
                """INSERT INTO pits_bom_occurrences (
                    id, project_id, parent_tracker_number, child_tracker_number, child_part_id,
                    proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                    raw_levels_json, source_fingerprint, first_seen_import_id, last_seen_import_id,
                    first_seen_at, last_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()), self.project_id, parent_trk, child_trk, None,
                    depth, first_qty, str(first_qty), row_num,
                    raw_json, f"fp_{child_trk}", import_id, import_id,
                    ts, ts, ts,
                ),
            )

        # Row 10: Root assembly for Model A (Level 1)
        add_usage_occ("", "101", 1, 10, {"MODEL-A-01": 1.0})
        # Row 11: Root assembly for Model B (Level 1)
        add_usage_occ("", "102", 1, 11, {"MODEL-B-02": 1.0})
        # Row 20: Shared Level 2 Subassembly
        add_usage_occ("102", "201", 2, 20, {"MODEL-A-01": 1.0, "MODEL-B-02": 1.0})
        # Row 25: Level 3 component unique to Model A (Qty 2.0)
        add_usage_occ("201", "301", 3, 25, {"MODEL-A-01": 2.0})
        # Row 26: Level 3 component unique to Model B (Qty 5.0)
        add_usage_occ("201", "302", 3, 26, {"MODEL-B-02": 5.0})

        # Test Tree for Model A
        tree_a = store.pits_bom_model_tree(self.project_id, model_id=str(model_a["id"]))
        self.assertEqual(tree_a["metrics"]["total"], 3)
        self.assertEqual(len(tree_a["roots"]), 1)
        root_a = tree_a["roots"][0]
        self.assertEqual(root_a["child_tracker"], "101")
        self.assertEqual(len(root_a["children"]), 1)
        l2_a = root_a["children"][0]
        self.assertEqual(l2_a["child_tracker"], "201")
        self.assertEqual(len(l2_a["children"]), 1)
        l3_a = l2_a["children"][0]
        self.assertEqual(l3_a["child_tracker"], "301")
        self.assertEqual(l3_a["quantity"], 2.0)

        # Test Tree for Model B
        tree_b = store.pits_bom_model_tree(self.project_id, model_id=str(model_b["id"]))
        self.assertEqual(tree_b["metrics"]["total"], 3)
        self.assertEqual(len(tree_b["roots"]), 1)
        root_b = tree_b["roots"][0]
        self.assertEqual(root_b["child_tracker"], "102")
        self.assertEqual(len(root_b["children"]), 1)
        l2_b = root_b["children"][0]
        self.assertEqual(l2_b["child_tracker"], "201")
        self.assertEqual(len(l2_b["children"]), 1)
        l3_b = l2_b["children"][0]
        self.assertEqual(l3_b["child_tracker"], "302")
        # Test resolving model tree by model number string directly
        tree_a_str = store.pits_bom_model_tree(self.project_id, model_id="MODEL-A-01")
        self.assertEqual(tree_a_str["metrics"]["total"], 3)
        self.assertEqual(tree_a_str["roots"][0]["child_tracker"], "101")

    def test_model_tree_page_smoke(self) -> None:
        file_path = str(Path(__file__).parent.parent / "app_pages" / "bom_tree.py")
        at = AppTest.from_file(file_path)
        at.session_state["project_id"] = self.project_id
        at.session_state["scenario_id"] = self.scenario_id
        at.run()
        self.assertEqual(at.exception, [])

    def test_model_tree_page_with_search_queries(self) -> None:
        store.add_project_model(self.project_id, "MODEL-A-01", "Model A", "tester")
        file_path = str(Path(__file__).parent.parent / "app_pages" / "bom_tree.py")
        at = AppTest.from_file(file_path)
        at.session_state["project_id"] = self.project_id
        at.session_state["scenario_id"] = self.scenario_id
        at.run()
        self.assertEqual(at.exception, [])
        self.assertEqual(at.session_state["model_tree_selected_model"], "all")

        # Now search for MODEL-A
        at.session_state["model_tree_model_search"] = "MODEL-A"
        at.session_state["model_tree_search"] = "PART"
        at.run()
        self.assertEqual(at.exception, [])
        # The official model dropdown must reflect the search, not 'all'
        self.assertNotEqual(at.session_state["model_tree_selected_model"], "all")
        sel = at.selectbox(key="model_tree_selected_model")
        self.assertNotEqual(sel.value, "all")

    def test_model_tree_part_photo_thumbnail(self) -> None:
        # Create a mock image file on disk
        from PIL import Image
        img_file = store.DATA_DIR / f"test_img_{uuid4()}.png"
        img = Image.new("RGB", (32, 32), color=(73, 109, 137))
        img.save(img_file, format="PNG")
        self.addCleanup(lambda: img_file.unlink(missing_ok=True))

        store.add_project_model(self.project_id, "MODEL-PHOTO", "Model Photo", "tester")
        part_id = str(uuid4())
        ts = store.now_iso()
        store.execute(
            """INSERT INTO parts (id, project_id, part_number, description, weight_lb, make_buy, model_applicability, image_path, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (part_id, self.project_id, "PART-PHOTO", "Photo part", 1.0, "Make", "All", str(img_file), ts),
        )
        import_id = str(uuid4())
        store.execute(
            """INSERT INTO pits_bom_imports (
                id, project_id, import_sequence, workbook_name, workbook_sha256,
                bom_sheet_name, source_row_count, occurrence_count, issue_count,
                imported_by, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (import_id, self.project_id, 99, "test.xlsx", "sha_photo", "BOM", 1, 1, 0, "tester", ts),
        )

        occ_id = str(uuid4())
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                id, project_id, parent_tracker_number, child_tracker_number, child_part_id,
                proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                source_fingerprint, first_seen_import_id, last_seen_import_id,
                first_seen_at, last_seen_at, updated_at, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                occ_id, self.project_id, "", "TRK-PHOTO", part_id,
                1, 1.0, "1", 1,
                "fp_photo", import_id, import_id,
                ts, ts, ts, "Needs review",
            ),
        )

        tree = store.pits_bom_model_tree(self.project_id)
        photo_node = next((n for n in tree["nodes"] if n["id"] == occ_id), None)
        self.assertIsNotNone(photo_node)
        self.assertEqual(photo_node["image_path"], str(img_file))

        # Test AppTest renders image
        file_path = str(Path(__file__).parent.parent / "app_pages" / "bom_tree.py")
        at = AppTest.from_file(file_path)
        at.session_state["project_id"] = self.project_id
        at.session_state["scenario_id"] = self.scenario_id
        at.session_state["selected_model_tree_node_id"] = occ_id
        at.run()
        self.assertEqual(at.exception, [])
        self.assertEqual(len(at.image), 1)

    def test_quick_add_model_does_not_mutate_instantiated_widget(self) -> None:
        file_path = str(Path(__file__).parent.parent / "app_pages" / "bom_tree.py")
        at = AppTest.from_file(file_path)
        at.session_state["project_id"] = self.project_id
        at.session_state["scenario_id"] = self.scenario_id
        at.run()
        self.assertEqual(at.exception, [])

        # Stage a new model creation as done by the quick add popover
        new_mid = store.add_project_model(self.project_id, "MODEL-QUICK-99", "Quick Model", "tester")
        at.session_state["_pending_model_tree_model"] = new_mid
        at.run()
        self.assertEqual(at.exception, [])
        self.assertEqual(at.session_state.get("model_tree_selected_model"), new_mid)
        sel = at.selectbox(key="model_tree_selected_model")
        self.assertEqual(sel.value, new_mid)

    def test_model_tree_with_duplicate_parts_across_subassemblies(self) -> None:
        import_id = str(uuid4())
        ts = store.now_iso()
        store.execute(
            """INSERT INTO pits_bom_imports (
                id, project_id, import_sequence, workbook_name, workbook_sha256,
                bom_sheet_name, source_row_count, occurrence_count, issue_count,
                imported_by, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (import_id, self.project_id, 100, "car.xlsx", "sha_car", "BOM", 5, 5, 0, "tester", ts),
        )

        # L1: Root car
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                id, project_id, parent_tracker_number, child_tracker_number,
                proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                source_fingerprint, first_seen_import_id, last_seen_import_id,
                first_seen_at, last_seen_at, updated_at, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), self.project_id, "", "ROOT-CAR", 1, 1.0, "1", 1, "fp1", import_id, import_id, ts, ts, ts, "Needs review"),
        )
        # L2: Front assembly
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                id, project_id, parent_tracker_number, child_tracker_number,
                proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                source_fingerprint, first_seen_import_id, last_seen_import_id,
                first_seen_at, last_seen_at, updated_at, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), self.project_id, "ROOT-CAR", "FRONT-ASM", 2, 1.0, "1", 2, "fp2", import_id, import_id, ts, ts, ts, "Needs review"),
        )
        # L2: Rear assembly
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                id, project_id, parent_tracker_number, child_tracker_number,
                proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                source_fingerprint, first_seen_import_id, last_seen_import_id,
                first_seen_at, last_seen_at, updated_at, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), self.project_id, "ROOT-CAR", "REAR-ASM", 2, 1.0, "1", 3, "fp3", import_id, import_id, ts, ts, ts, "Needs review"),
        )
        # Shared part under both FRONT-ASM and REAR-ASM (using subassembly definition lookup in pits_bom_model_tree Case B)
        # Subassembly under FRONT-ASM:
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                id, project_id, parent_tracker_number, child_tracker_number,
                proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                source_fingerprint, first_seen_import_id, last_seen_import_id,
                first_seen_at, last_seen_at, updated_at, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), self.project_id, "FRONT-ASM", "WHEEL-ASM", 3, 2.0, "2", 4, "fp4", import_id, import_id, ts, ts, ts, "Needs review"),
        )
        # Same subassembly reference under REAR-ASM:
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                id, project_id, parent_tracker_number, child_tracker_number,
                proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                source_fingerprint, first_seen_import_id, last_seen_import_id,
                first_seen_at, last_seen_at, updated_at, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), self.project_id, "REAR-ASM", "WHEEL-ASM", 3, 2.0, "2", 5, "fp5", import_id, import_id, ts, ts, ts, "Needs review"),
        )
        # Leaf child under WHEEL-ASM (which attaches to both occurrences of WHEEL-ASM)
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                id, project_id, parent_tracker_number, child_tracker_number,
                proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                source_fingerprint, first_seen_import_id, last_seen_import_id,
                first_seen_at, last_seen_at, updated_at, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), self.project_id, "WHEEL-ASM", "TIRE-PART", 4, 1.0, "1", 6, "fp6", import_id, import_id, ts, ts, ts, "Needs review"),
        )

        file_path = str(Path(__file__).parent.parent / "app_pages" / "bom_tree.py")
        at = AppTest.from_file(file_path)
        at.session_state["project_id"] = self.project_id
        at.session_state["scenario_id"] = self.scenario_id
        at.run()
        self.assertEqual(at.exception, [])

    def test_unused_bom_parts_excluded_from_bom_catalog_active_and_fishbone(self) -> None:
        import json

        model_id = store.add_project_model(self.project_id, "HPC0305DW-1", "Valid Model", "tester")
        ts = store.now_iso()

        used_part_id = str(uuid4())
        unused_part_id = str(uuid4())
        store.execute(
            """INSERT INTO parts (id, project_id, part_number, description, pits_tracker_number, weight_lb, make_buy, model_applicability, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (used_part_id, self.project_id, "USED-PART-001", "Used part", "63", 1.0, "Buy", "HPC0305DW-1", ts),
        )
        store.execute(
            """INSERT INTO parts (id, project_id, part_number, description, pits_tracker_number, weight_lb, make_buy, model_applicability, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (unused_part_id, self.project_id, "308D1387P001", "Unused screw", "64", 0.1, "Buy", "", ts),
        )
        store.execute(
            """INSERT INTO part_scenario_activity (project_id, scenario_id, part_id, active, updated_at)
               VALUES (?, ?, ?, 1, ?), (?, ?, ?, 1, ?)""",
            (self.project_id, self.scenario_id, used_part_id, ts, self.project_id, self.scenario_id, unused_part_id, ts),
        )

        import_id = str(uuid4())
        store.execute(
            """INSERT INTO pits_bom_imports (
                id, project_id, import_sequence, workbook_name, workbook_sha256,
                bom_sheet_name, source_row_count, occurrence_count, issue_count,
                imported_by, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (import_id, self.project_id, 101, "nexus.xlsx", "sha_nexus", "BOM", 3, 3, 0, "tester", ts),
        )

        # L1 root for active model
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                id, project_id, parent_tracker_number, child_tracker_number,
                proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                raw_levels_json, source_fingerprint, first_seen_import_id, last_seen_import_id,
                first_seen_at, last_seen_at, updated_at, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()), self.project_id, "", "1", 1, 1.0, "1", 1,
                json.dumps({"Level 1": 1, "model_usages": {"HPC0305DW-1": 1.0}}),
                "fp_root", import_id, import_id, ts, ts, ts, "Needs review",
            ),
        )
        # L2 used part
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                id, project_id, parent_tracker_number, child_tracker_number, child_part_id,
                proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                raw_levels_json, source_fingerprint, first_seen_import_id, last_seen_import_id,
                first_seen_at, last_seen_at, updated_at, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()), self.project_id, "1", "63", used_part_id, 2, 1.0, "1", 2,
                json.dumps({"Level 2": 1, "model_usages": {"HPC0305DW-1": 1.0}}),
                "fp_used", import_id, import_id, ts, ts, ts, "Needs review",
            ),
        )
        # L3 unused part (no model_usages key in raw_levels_json, mimicking PITS BOM row with 0/blank across all valid models)
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                id, project_id, parent_tracker_number, child_tracker_number, child_part_id,
                proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                raw_levels_json, source_fingerprint, first_seen_import_id, last_seen_import_id,
                first_seen_at, last_seen_at, updated_at, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()), self.project_id, "63", "64", unused_part_id, 3, 4.0, "4", 3,
                json.dumps({"Level 3": 4}),
                "fp_unused", import_id, import_id, ts, ts, ts, "Needs review",
            ),
        )

        with store.connection() as conn:
            store._sync_bom_part_scenario_activity(conn, self.project_id, ts)

        # 1. Verify Master BOM and Model BOM exclude 308D1387P001
        master_tree = store.pits_bom_model_tree(self.project_id, "all")
        master_pns = {n["part_number"] for n in master_tree["nodes"]}
        self.assertIn("USED-PART-001", master_pns)
        self.assertNotIn("308D1387P001", master_pns)

        model_tree = store.pits_bom_model_tree(self.project_id, model_id)
        model_pns = {n["part_number"] for n in model_tree["nodes"]}
        self.assertIn("USED-PART-001", model_pns)
        self.assertNotIn("308D1387P001", model_pns)

        manual_bom = store.get_manual_model_bom(self.project_id, model_id)
        manual_pns = {r["part_number"] for r in manual_bom}
        self.assertIn("USED-PART-001", manual_pns)
        self.assertNotIn("308D1387P001", manual_pns)

        # 2. Verify Parts Catalog active column is unchecked and active_part_ids excludes 308D1387P001
        active_ids = store.active_part_ids(self.project_id, self.scenario_id)
        self.assertIn(used_part_id, active_ids)
        self.assertNotIn(unused_part_id, active_ids)

        activity_map = store.part_scenario_activity(self.project_id, self.scenario_id)
        self.assertTrue(activity_map.get(used_part_id, False))
        self.assertFalse(activity_map.get(unused_part_id, True))

    def test_source_code_8_parts_active_in_catalog_and_bom_but_excluded_from_fishbone_placement(self) -> None:
        import json

        model_id = store.add_project_model(self.project_id, "HPC0305DW-1", "Valid Model", "tester")
        store.add_assembly_section(self.project_id, "Main Section", "Assembly", None, "")
        ts = store.now_iso()

        received_part_id = str(uuid4())
        sc8_part_id = str(uuid4())
        store.execute(
            """INSERT INTO parts (id, project_id, part_number, description, pits_tracker_number, source_code, weight_lb, make_buy, model_applicability, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (received_part_id, self.project_id, "RECV-ASM-001", "Supplied Assembly", "63", "3", 2.5, "Buy", "HPC0305DW-1", ts),
        )
        store.execute(
            """INSERT INTO parts (id, project_id, part_number, description, pits_tracker_number, source_code, weight_lb, make_buy, model_applicability, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sc8_part_id, self.project_id, "SC8-SUB-008", "Component of Purchased Asm", "64", "8", 0.2, "Buy", "HPC0305DW-1", ts),
        )
        store.execute(
            """INSERT INTO part_scenario_activity (project_id, scenario_id, part_id, active, updated_at)
               VALUES (?, ?, ?, 1, ?), (?, ?, ?, 1, ?)""",
            (self.project_id, self.scenario_id, received_part_id, ts, self.project_id, self.scenario_id, sc8_part_id, ts),
        )

        import_id = str(uuid4())
        store.execute(
            """INSERT INTO pits_bom_imports (
                id, project_id, import_sequence, workbook_name, workbook_sha256,
                bom_sheet_name, source_row_count, occurrence_count, issue_count,
                imported_by, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (import_id, self.project_id, 102, "sc8.xlsx", "sha_sc8", "BOM", 3, 3, 0, "tester", ts),
        )

        # L1 root for active model
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                id, project_id, parent_tracker_number, child_tracker_number,
                proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                raw_levels_json, source_fingerprint, first_seen_import_id, last_seen_import_id,
                first_seen_at, last_seen_at, updated_at, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()), self.project_id, "", "1", 1, 1.0, "1", 1,
                json.dumps({"Level 1": 1, "model_usages": {"HPC0305DW-1": 1.0}}),
                "fp_sc8_root", import_id, import_id, ts, ts, ts, "Needs review",
            ),
        )
        # L2 supplied assembly (source_code = 3)
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                id, project_id, parent_tracker_number, child_tracker_number, child_part_id,
                proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                raw_levels_json, source_fingerprint, first_seen_import_id, last_seen_import_id,
                first_seen_at, last_seen_at, updated_at, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()), self.project_id, "1", "63", received_part_id, 2, 1.0, "1", 2,
                json.dumps({"Level 2": 1, "model_usages": {"HPC0305DW-1": 1.0}}),
                "fp_sc8_asm", import_id, import_id, ts, ts, ts, "Needs review",
            ),
        )
        # L3 component of purchased assembly (source_code = 8), used in valid model
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                id, project_id, parent_tracker_number, child_tracker_number, child_part_id,
                proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                raw_levels_json, source_fingerprint, first_seen_import_id, last_seen_import_id,
                first_seen_at, last_seen_at, updated_at, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()), self.project_id, "63", "64", sc8_part_id, 3, 2.0, "2", 3,
                json.dumps({"Level 3": 2, "model_usages": {"HPC0305DW-1": 2.0}}),
                "fp_sc8_sub", import_id, import_id, ts, ts, ts, "Needs review",
            ),
        )

        with store.connection() as conn:
            store._sync_bom_part_scenario_activity(conn, self.project_id, ts)

        # 1. Source code 8 part remains Active in Parts Catalog when used in a valid model
        active_ids = store.active_part_ids(self.project_id, self.scenario_id)
        self.assertIn(received_part_id, active_ids)
        self.assertIn(sc8_part_id, active_ids)

        activity_map = store.part_scenario_activity(self.project_id, self.scenario_id)
        self.assertTrue(activity_map.get(received_part_id, False))
        self.assertTrue(activity_map.get(sc8_part_id, False))

        # 2. Source code 8 part remains visible in Master BOM and Model BOM when used in a valid model
        master_tree = store.pits_bom_model_tree(self.project_id, "all")
        master_pns = {n["part_number"] for n in master_tree["nodes"]}
        self.assertIn("RECV-ASM-001", master_pns)
        self.assertIn("SC8-SUB-008", master_pns)

        model_tree = store.pits_bom_model_tree(self.project_id, model_id)
        model_pns = {n["part_number"] for n in model_tree["nodes"]}
        self.assertIn("RECV-ASM-001", model_pns)
        self.assertIn("SC8-SUB-008", model_pns)

        # 3. Source code 8 part is excluded from Fishbone parts-to-place table, palette_items, and assembly child_parts
        fishbone_path = str(Path(__file__).parent.parent / "app_pages" / "fishbone.py")
        with patch("utils.fishbone_visual.interactive_fishbone", return_value=None) as mock_canvas:
            at = AppTest.from_file(fishbone_path, default_timeout=30)
            at.session_state["project_id"] = self.project_id
            at.session_state["scenario_id"] = self.scenario_id
            at.run(timeout=30)
        self.assertEqual(list(at.exception), [])

        pool_tables = [
            df.value for df in at.dataframe
            if "fishbone_section" in df.value.columns and "part_number" in df.value.columns
        ]
        self.assertTrue(pool_tables, "Expected Place Parts into Fishbone dataframe on fishbone page")
        pool_pns = set(pool_tables[0]["part_number"].astype(str))
        self.assertIn("RECV-ASM-001", pool_pns)
        self.assertNotIn("SC8-SUB-008", pool_pns)

        self.assertTrue(mock_canvas.called)
        palette_items = mock_canvas.call_args.kwargs.get("palette_items", [])
        palette_pns = {item["part_number"] for item in palette_items}
        self.assertIn("RECV-ASM-001", palette_pns)
        self.assertNotIn("SC8-SUB-008", palette_pns)
        recv_asm_item = next(item for item in palette_items if item["part_number"] == "RECV-ASM-001")
        child_pns = {c["part_number"] for c in recv_asm_item.get("child_parts", [])}
        self.assertNotIn("SC8-SUB-008", child_pns)


if __name__ == "__main__":
    unittest.main()
