from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import pandas as pd
from streamlit.testing.v1 import AppTest

from utils import store
from utils.table_filters import filter_table, merge_filtered_edits


class ModelPageFiltersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_model_filters_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])

    def tearDown(self) -> None:
        self.database_patch.stop()
        if self.database_path.exists():
            self.database_path.unlink()

    def test_feature_definitions_filtering_and_merging(self) -> None:
        # Create initial features
        f1_id = str(uuid4())
        f2_id = str(uuid4())
        features_df = pd.DataFrame([
            {"id": f1_id, "active": True, "category": "Door", "name": "Dispenser", "allowed_choices": "Yes, No", "description": "Door dispenser"},
            {"id": f2_id, "active": False, "category": "Finish", "name": "Color", "allowed_choices": "Black, Stainless", "description": "Finish color"},
        ])
        store.update_complexity_features(self.project_id, features_df)

        fetched = store.complexity_features(self.project_id)
        feature_rows = fetched.reindex(columns=["id", "active", "category", "name", "allowed_choices", "description"])

        # Filter to category Door
        filtered = feature_rows[feature_rows["category"] == "Door"].copy()
        self.assertEqual(len(filtered), 1)

        # Edit visible row
        filtered.at[filtered.index[0], "description"] = "Updated Door dispenser"

        # Merging with original should preserve Finish row
        merged = merge_filtered_edits(feature_rows, filtered, filtered)
        self.assertEqual(len(merged), 2)
        store.update_complexity_features(self.project_id, merged)

        refetched = store.complexity_features(self.project_id)
        self.assertEqual(len(refetched), 2)
        door_feature = refetched[refetched["category"] == "Door"].iloc[0]
        self.assertEqual(door_feature["description"], "Updated Door dispenser")
        finish_feature = refetched[refetched["category"] == "Finish"].iloc[0]
        self.assertEqual(finish_feature["name"], "Color")

    def test_complexity_tree_filtering_and_merging(self) -> None:
        # Add models
        m1_id = str(uuid4())
        m2_id = str(uuid4())
        models_df = pd.DataFrame([
            {"id": m1_id, "model_number": "MOD-1", "display_name": "Model 1", "eau": 100, "description": "Desc 1", "active": True, "notes": ""},
            {"id": m2_id, "model_number": "MOD-2", "display_name": "Model 2", "eau": 200, "description": "Desc 2", "active": True, "notes": ""},
        ])
        store.update_project_model_rows(self.project_id, models_df)

        # Add feature
        f_id = str(uuid4())
        features_df = pd.DataFrame([
            {"id": f_id, "active": True, "category": "Door", "name": "Dispenser", "allowed_choices": "Dispenser, Standard", "description": ""},
        ])
        store.update_complexity_features(self.project_id, features_df)

        tree = store.complexity_tree(self.project_id)
        tree["id"] = tree["model_id"]
        self.assertEqual(len(tree), 2)

        # Filter tree to MOD-1
        visible_tree = tree[tree["official_model_number"] == "MOD-1"].copy()
        self.assertEqual(len(visible_tree), 1)

        # Edit visible tree
        visible_tree.at[visible_tree.index[0], f_id] = "Dispenser"

        # Merge filtered edits
        merged_tree = merge_filtered_edits(tree, visible_tree, visible_tree, id_column="model_id")
        self.assertEqual(len(merged_tree), 2)
        store.update_complexity_tree(self.project_id, merged_tree)

        # Refetch tree and verify MOD-1 has Dispenser and MOD-2 is preserved
        refetched_tree = store.complexity_tree(self.project_id).set_index("official_model_number")
        self.assertEqual(refetched_tree.at["MOD-1", f_id], "Dispenser")
        self.assertEqual(len(refetched_tree), 2)

    def test_models_page_smoke(self) -> None:
        script_path = str(Path(__file__).resolve().parent.parent / "app_pages" / "models.py")
        app = AppTest.from_file(script_path, default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["current_editor"] = "Tester"
        app.run()
        self.assertFalse(app.exception)

    def test_complexity_tree_visual_multiple_categories(self) -> None:
        m1_id = str(uuid4())
        m2_id = str(uuid4())
        models_df = pd.DataFrame([
            {"id": m1_id, "model_number": "MOD-1", "display_name": "Model 1", "eau": 100, "description": "", "active": True, "notes": ""},
            {"id": m2_id, "model_number": "MOD-2", "display_name": "Model 2", "eau": 200, "description": "", "active": True, "notes": ""},
        ])
        store.update_project_model_rows(self.project_id, models_df)

        f1_id = str(uuid4())
        f2_id = str(uuid4())
        features_df = pd.DataFrame([
            {"id": f1_id, "active": True, "category": "Door", "subsystem": "", "name": "Dispenser", "allowed_choices": "Yes, No", "description": ""},
            {"id": f2_id, "active": True, "category": "Finish", "subsystem": "", "name": "Color", "allowed_choices": "Black, Stainless", "description": ""},
        ])
        store.update_complexity_features(self.project_id, features_df)

        tree = store.complexity_tree(self.project_id)
        tree.loc[tree["model_id"] == m1_id, [f1_id, f2_id]] = ["Yes", "Black"]
        tree.loc[tree["model_id"] == m2_id, [f1_id, f2_id]] = ["No", "Stainless"]
        store.update_complexity_tree(self.project_id, tree)

        script_path = str(Path(__file__).resolve().parent.parent / "app_pages" / "models.py")
        app = AppTest.from_file(script_path, default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["current_editor"] = "Tester"
        app.session_state[f"complexity_tree_visual_category_{self.project_id}"] = ["Door", "Finish"]
        app.session_state[f"complexity_tree_visual_model_label_{self.project_id}"] = "Official model number"
        app.run()
        self.assertFalse(app.exception)
        markdown_texts = "\n".join(md.value for md in app.markdown)
        self.assertIn("Door · Dispenser", markdown_texts)
        self.assertIn("Finish · Color", markdown_texts)

    def test_complexity_tree_visual_part_number_display(self) -> None:
        m1_id = str(uuid4())
        m2_id = str(uuid4())
        models_df = pd.DataFrame([
            {"id": m1_id, "model_number": "MOD-1", "display_name": "Model 1", "eau": 100, "description": "", "active": True, "notes": ""},
            {"id": m2_id, "model_number": "MOD-2", "display_name": "Model 2", "eau": 200, "description": "", "active": True, "notes": ""},
        ])
        store.update_project_model_rows(self.project_id, models_df)

        f1_id = str(uuid4())
        features_df = pd.DataFrame([
            {"id": f1_id, "active": True, "category": "Door", "subsystem": "", "name": "Dispenser", "allowed_choices": "Yes, No", "description": ""},
        ])
        store.update_complexity_features(self.project_id, features_df)

        tree = store.complexity_tree(self.project_id)
        tree.loc[tree["model_id"] == m1_id, [f1_id]] = ["Yes"]
        tree.loc[tree["model_id"] == m2_id, [f1_id]] = ["No"]
        store.update_complexity_tree(self.project_id, tree)

        ts = store.now_iso()
        p1_id = str(uuid4())
        p2_id = str(uuid4())
        store.execute(
            """INSERT INTO parts (id, project_id, part_number, description, pits_tracker_number, model_applicability, updated_at)
               VALUES (?, ?, 'PN-DISP-01', 'Dispenser Asm A', '', '', ?),
                      (?, ?, 'PN-DISP-02', 'Dispenser Asm B', '', '', ?)""",
            (p1_id, self.project_id, ts, p2_id, self.project_id, ts),
        )
        store.execute(
            """INSERT INTO part_feature_rules (project_id, part_id, feature_id, value, updated_at)
               VALUES (?, ?, ?, 'Yes', ?),
                      (?, ?, ?, 'Yes', ?)""",
            (self.project_id, p1_id, f1_id, ts, self.project_id, p2_id, f1_id, ts),
        )

        script_path = str(Path(__file__).resolve().parent.parent / "app_pages" / "models.py")
        app = AppTest.from_file(script_path, default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["current_editor"] = "Tester"
        app.session_state[f"complexity_tree_visual_category_{self.project_id}"] = ["Door"]
        app.session_state[f"complexity_tree_visual_model_label_{self.project_id}"] = "Official model number"
        app.session_state[f"complexity_tree_visual_feature_display_{self.project_id}"] = "Part number"
        app.run()
        self.assertFalse(app.exception)
        markdown_texts = "\n".join(md.value for md in app.markdown)
        self.assertIn("PN-DISP-01<br>PN-DISP-02", markdown_texts)
        self.assertIn("No parts assigned", markdown_texts)

        # Also verify selecting multiple model labels and multiple feature displays together
        app.session_state[f"complexity_tree_visual_model_label_{self.project_id}"] = [
            "Model name",
            "Model number",
        ]
        app.session_state[f"complexity_tree_visual_feature_display_{self.project_id}"] = [
            "Feature",
            "Part number",
        ]
        app.run()
        self.assertFalse(app.exception)
        combined_markdown = "\n".join(md.value for md in app.markdown)
        self.assertIn("Model 1<br>MOD-1", combined_markdown)
        self.assertIn("Model 2<br>MOD-2", combined_markdown)
        self.assertIn("Yes<br><span style=\"font-weight:400;\">PN-DISP-01<br>PN-DISP-02</span>", combined_markdown)
        self.assertIn('id="complexity-tree-shell"', combined_markdown)
        self.assertIn('id="complexity-tree-body"', combined_markdown)
        self.assertIn('id="complexity-tree-sidebar"', combined_markdown)
        self.assertIn('id="complexity-tree-toggle-sidebar"', combined_markdown)
        self.assertIn('id="complexity-tree-reset-colors"', combined_markdown)
        self.assertIn("Definition colors", combined_markdown)
        self.assertIn('id="full-screen"', combined_markdown)
        self.assertIn('id="complexity-tree-reset-cols"', combined_markdown)
        self.assertIn('data-ct-action="toggle-sidebar"', combined_markdown)
        self.assertIn('data-ct-action="reset-colors"', combined_markdown)
        self.assertIn('data-ct-action="full-screen"', combined_markdown)
        self.assertIn('data-ct-action="reset-cols"', combined_markdown)
        self.assertIn('data-ct-action="fit-view"', combined_markdown)
        self.assertIn('data-ct-action="zoom-in"', combined_markdown)
        self.assertIn('data-ct-action="zoom-out"', combined_markdown)
        self.assertIn('data-ct-action="zoom-reset"', combined_markdown)
        self.assertIn('class="ct-model-col-header"', combined_markdown)
        self.assertIn('data-ct-move-col="-1"', combined_markdown)
        self.assertIn('data-ct-move-col="1"', combined_markdown)
        self.assertIn('class="ct-feature-box"', combined_markdown)
        self.assertIn('data-merge-key=', combined_markdown)
        self.assertIn(">Full Screen</button>", combined_markdown)
        html_blocks = [el.proto.body for el in app.get("html")]
        ct_scripts = [b for b in html_blocks if "toggleComplexityTreeFullScreen" in b]
        self.assertEqual(len(ct_scripts), 1)
        self.assertIn("renderColorSidebar", ct_scripts[0])
        self.assertIn("CURATED_COLOR_PALETTES", ct_scripts[0])
        self.assertIn("defaultShades", ct_scripts[0])
        self.assertIn("findActiveShadeIndex", ct_scripts[0])
        self.assertIn("buildFiveShadeRamp", ct_scripts[0])
        self.assertIn("saveUserCustomColor", ct_scripts[0])
        self.assertIn("applyFeaturePaletteFamily", ct_scripts[0])
        self.assertIn("buildPaletteDrawerHtml", ct_scripts[0])
        self.assertIn("resolveModelHeaderColor", ct_scripts[0])
        self.assertIn("resolveFeatureChoiceColor", ct_scripts[0])
        script_inner = ct_scripts[0].split("<script>", 1)[1].rsplit("</script>", 1)[0]
        self.assertIsNone(
            re.search(r"<[/\w!]", script_inner),
            "Script body must not contain raw '<tag' sequences that DOMPurify SAFE_FOR_XML strips",
        )

        # Verify Print button opens Print Complexity Tree Visual dialog cleanly
        print_btns = [
            b for b in app.button
            if b.key == f"btn_print_complexity_tree_visual_{self.project_id}"
        ]
        self.assertEqual(len(print_btns), 1)
        print_btns[0].click()
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(
            app.session_state[f"complexity_tree_print_active_{self.project_id}"]
        )
        print_html_blocks = [el.proto.body for el in app.get("html")]
        print_deck_blocks = [b for b in print_html_blocks if "print-complexity-grid-host" in b]
        self.assertEqual(len(print_deck_blocks), 1)
        self.assertIn("data-print-spec-b64=", print_deck_blocks[0])
        self.assertIn("applySavedOrderToPrintGrids", print_deck_blocks[0])
        self.assertIn("resolveSavedColorsForPrint", print_deck_blocks[0])
        self.assertIn("print-model-col-header", print_deck_blocks[0])
        self.assertIn("white-space:nowrap", print_deck_blocks[0])
        print_script_inner = print_deck_blocks[0].split("<script>", 1)[1].rsplit("</script>", 1)[0]
        self.assertIsNone(
            re.search(r"<[/\w!]", print_script_inner),
            "Print deck script body must not contain raw '<tag' sequences that DOMPurify SAFE_FOR_XML strips",
        )

    def test_image_annotator_zoom_composite_and_persistence(self) -> None:
        import json
        import tempfile
        from PIL import Image
        from utils.image_annotator import (
            _JS,
            _apply_zoom_to_composite_pil,
            patch_visual_media_composite_image_shapes,
        )

        # Verify JS includes zoom persistence in __transform__ and composite zoom application
        self.assertIn("hasZoomTransform()", _JS)
        self.assertIn("transformEntry.zoom", _JS)
        self.assertIn("syncViewportScrollToPan", _JS)

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_path = Path(tmpdir) / "orig.png"
            comp_zoom_in_path = Path(tmpdir) / "comp_in.png"
            comp_zoom_out_path = Path(tmpdir) / "comp_out.png"

            # Create a 200x100 image with a blue border and red center (x: 50..150, y: 25..75)
            base_img = Image.new("RGBA", (200, 100), (0, 0, 255, 255))
            center_patch = Image.new("RGBA", (100, 50), (255, 0, 0, 255))
            base_img.paste(center_patch, (50, 25))
            base_img.save(orig_path, format="PNG")

            # 1) Zoom in 2.0x centered at (0.5, 0.5) -> entire output should be the red center!
            ann_zoom_in = json.dumps(
                [{"id": "__transform__", "type": "__transform__", "ops": [], "zoom": 2.0, "panX": 0.5, "panY": 0.5}]
            )
            ok_in = patch_visual_media_composite_image_shapes(
                orig_path, comp_zoom_in_path, ann_zoom_in
            )
            self.assertTrue(ok_in)
            with Image.open(comp_zoom_in_path) as z_in:
                self.assertEqual(z_in.size, (200, 100))
                # Corner pixel of 2x zoomed-in image should now be red (from center patch) instead of blue!
                r, g, b, _ = z_in.convert("RGBA").getpixel((5, 5))
                self.assertGreater(r, 200)
                self.assertLess(b, 50)

            # 2) Zoom out 0.5x -> outer border should be white (#ffffff) padding and center should be red
            ann_zoom_out = json.dumps(
                [{"id": "__transform__", "type": "__transform__", "ops": [], "zoom": 0.5, "panX": 0.5, "panY": 0.5}]
            )
            ok_out = patch_visual_media_composite_image_shapes(
                orig_path, comp_zoom_out_path, ann_zoom_out
            )
            self.assertTrue(ok_out)
            with Image.open(comp_zoom_out_path) as z_out:
                self.assertEqual(z_out.size, (200, 100))
                rgba_out = z_out.convert("RGBA")
                self.assertEqual(rgba_out.getpixel((5, 5))[:3], (255, 255, 255))
                cr, cg, cb, _ = rgba_out.getpixel((100, 50))
                self.assertGreater(cr, 200)
                self.assertLess(cb, 50)

    def test_updating_allowed_choices_updates_complexity_tree_and_part_rules(self) -> None:
        m1_id = str(uuid4())
        m2_id = str(uuid4())
        models_df = pd.DataFrame([
            {"id": m1_id, "model_number": "GTD40EDSBWB", "display_name": "Model 40WB", "eau": 100, "description": "", "active": True, "notes": ""},
            {"id": m2_id, "model_number": "GTD50EDSBGR", "display_name": "Model 50GR", "eau": 200, "description": "", "active": True, "notes": ""},
        ])
        store.update_project_model_rows(self.project_id, models_df)

        f_hinge_id = str(uuid4())
        f_knob_qty_id = str(uuid4())
        features_df = pd.DataFrame([
            {"id": f_hinge_id, "active": True, "category": "Hinge", "subsystem": "", "name": "Type", "allowed_choices": "Sheet Metal, Cast", "description": ""},
            {"id": f_knob_qty_id, "active": True, "category": "UI", "subsystem": "", "name": "Option Knob QTY", "allowed_choices": "2, N/A", "description": ""},
        ])
        store.update_complexity_features(self.project_id, features_df)

        tree = store.complexity_tree(self.project_id)
        tree.loc[tree["model_id"] == m1_id, [f_hinge_id, f_knob_qty_id]] = ["Sheet Metal", "2"]
        tree.loc[tree["model_id"] == m2_id, [f_hinge_id, f_knob_qty_id]] = ["Cast", "N/A"]
        store.update_complexity_tree(self.project_id, tree)

        ts = store.now_iso()
        part_id = str(uuid4())
        store.execute(
            """INSERT INTO parts (id, project_id, part_number, description, pits_tracker_number, model_applicability, updated_at)
               VALUES (?, ?, 'PN-HINGE-02', 'Robust Hinge Asm', '', 'GTD50EDSBGR', ?)""",
            (part_id, self.project_id, ts),
        )
        store.execute(
            """INSERT INTO part_feature_rules (project_id, part_id, feature_id, value, updated_at)
               VALUES (?, ?, ?, 'Cast', ?)""",
            (self.project_id, part_id, f_hinge_id, ts),
        )

        # Update Allowed choices in Feature definitions: "Cast" -> "Robust", "N/A" -> "0"
        updated_features_df = pd.DataFrame([
            {"id": f_hinge_id, "active": True, "category": "Hinge", "subsystem": "", "name": "Type", "allowed_choices": "Sheet Metal, Robust", "description": ""},
            {"id": f_knob_qty_id, "active": True, "category": "UI", "subsystem": "", "name": "Option Knob QTY", "allowed_choices": "2, 0", "description": ""},
        ])
        store.update_complexity_features(self.project_id, updated_features_df)

        refetched_tree = store.complexity_tree(self.project_id).set_index("official_model_number")
        self.assertEqual(refetched_tree.at["GTD40EDSBWB", f_hinge_id], "Sheet Metal")
        self.assertEqual(refetched_tree.at["GTD50EDSBGR", f_hinge_id], "Robust")
        self.assertEqual(refetched_tree.at["GTD40EDSBWB", f_knob_qty_id], "2")
        self.assertEqual(refetched_tree.at["GTD50EDSBGR", f_knob_qty_id], "0")

        rules_df = store.part_feature_rules(self.project_id)
        part_rules = rules_df.loc[
            (rules_df["part_id"] == part_id) & (rules_df["feature_id"] == f_hinge_id),
            "value",
        ].tolist()
        self.assertEqual(part_rules, ["Robust"])
        part_row = store.query("SELECT model_applicability FROM parts WHERE id=?", (part_id,))[0]
        self.assertEqual(part_row["model_applicability"], "GTD50EDSBGR")

        # Verify AppTest renders Filter columns expander + Model number / Model name filters
        script_path = str(Path(__file__).resolve().parent.parent / "app_pages" / "models.py")
        app = AppTest.from_file(script_path, default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["current_editor"] = "Tester"
        app.run()
        self.assertFalse(app.exception)
        expander_labels = [exp.label for exp in app.expander]
        self.assertIn("Filter columns", expander_labels)
        ms_by_key = {ms.key: ms for ms in app.multiselect}
        self.assertIn(f"complexity_tree_filters_{self.project_id}_official_model_number", ms_by_key)
        self.assertIn(f"complexity_tree_filters_{self.project_id}_common_name", ms_by_key)
        self.assertEqual(
            ms_by_key[f"complexity_tree_filters_{self.project_id}_official_model_number"].label,
            "Model number",
        )
        self.assertEqual(
            ms_by_key[f"complexity_tree_filters_{self.project_id}_common_name"].label,
            "Model name",
        )
        self.assertEqual(
            ms_by_key[f"complexity_tree_filters_{self.project_id}_{f_hinge_id}"].options,
            ["Sheet Metal", "Robust"],
        )

    def test_complexity_tree_remembers_unsaved_edits_across_filter_changes_and_clear(self) -> None:
        from utils.table_filters import (
            _resolve_editor_instance_key,
            get_effective_table_editor_state,
            has_unsaved_table_changes,
        )

        m1_id = str(uuid4())
        m2_id = str(uuid4())
        m3_id = str(uuid4())
        models_df = pd.DataFrame([
            {"id": m1_id, "model_number": "MOD-10", "display_name": "Alpha 10", "eau": 100, "description": "", "active": True, "notes": ""},
            {"id": m2_id, "model_number": "MOD-20", "display_name": "Bravo 20", "eau": 200, "description": "", "active": True, "notes": ""},
            {"id": m3_id, "model_number": "MOD-30", "display_name": "Charlie 30", "eau": 300, "description": "", "active": True, "notes": ""},
        ])
        store.update_project_model_rows(self.project_id, models_df)

        f_console_id = str(uuid4())
        features_df = pd.DataFrame([
            {"id": f_console_id, "active": True, "category": "UI", "subsystem": "", "name": "Console", "allowed_choices": "40WB, 50GB, DS", "description": ""},
        ])
        store.update_complexity_features(self.project_id, features_df)

        tree = store.complexity_tree(self.project_id)
        tree.loc[tree["model_id"] == m1_id, [f_console_id]] = ["40WB"]
        tree.loc[tree["model_id"] == m2_id, [f_console_id]] = ["40WB"]
        tree.loc[tree["model_id"] == m3_id, [f_console_id]] = ["40WB"]
        store.update_complexity_tree(self.project_id, tree)

        script_path = str(Path(__file__).resolve().parent.parent / "app_pages" / "models.py")
        app = AppTest.from_file(script_path, default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["current_editor"] = "Tester"
        app.run()
        self.assertFalse(app.exception)

        logical_tree_key = f"complexity_tree_editor_{self.project_id}"
        filter_model_num_key = f"complexity_tree_filters_{self.project_id}_official_model_number"

        # 1) Filter to MOD-20 (which is row 1 in unfiltered table, now row 0 in filtered table)
        ms_model_num = next(ms for ms in app.multiselect if ms.key == filter_model_num_key)
        ms_model_num.select("MOD-20")
        app.run()
        self.assertFalse(app.exception)

        # 2) User edits MOD-20's feature in the filtered table (row 0 -> "50GB") without saving
        gen1 = int(app.session_state[f"_table_editor_generation_{logical_tree_key}"])
        active_tree_key = f"{logical_tree_key}__editor_instance_{gen1}"
        app.session_state[active_tree_key] = {
            "edited_rows": {0: {f_console_id: "50GB"}},
            "added_rows": [],
            "deleted_rows": [],
        }
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(
            app.session_state[f"_table_filter_id_draft_{logical_tree_key}"].get(m2_id, {}).get(f_console_id) == "50GB"
        )

        # 3) Switch filter to MOD-30 (hiding MOD-20) and edit MOD-30 (row 0 -> "DS") without saving
        ms_model_num = next(ms for ms in app.multiselect if ms.key == filter_model_num_key)
        ms_model_num.set_value(["MOD-30"])
        app.run()
        self.assertFalse(app.exception)

        gen2 = int(app.session_state[f"_table_editor_generation_{logical_tree_key}"])
        active_tree_key = f"{logical_tree_key}__editor_instance_{gen2}"
        app.session_state[active_tree_key] = {
            "edited_rows": {0: {f_console_id: "DS"}},
            "added_rows": [],
            "deleted_rows": [],
        }
        app.run()
        self.assertFalse(app.exception)

        # 4) Click "Clear filters" button -> all 3 rows should show with BOTH MOD-20="50GB" and MOD-30="DS" remembered!
        clear_btn = next(
            b for b in app.button if b.key == f"clear_complexity_tree_filters_{self.project_id}"
        )
        clear_btn.click()
        app.run()
        self.assertFalse(app.exception)

        display_df = app.session_state[f"_table_display_df_{logical_tree_key}"]
        self.assertEqual(len(display_df), 3)
        display_by_num = display_df.set_index("official_model_number")
        self.assertEqual(display_by_num.at["MOD-10", f_console_id], "40WB")
        self.assertEqual(display_by_num.at["MOD-20", f_console_id], "50GB")
        self.assertEqual(display_by_num.at["MOD-30", f_console_id], "DS")

        # 5) Click "Save & Refresh" on Complexity tree and confirm both edits are persisted to DB
        save_btn = next(b for b in app.button if b.key == "complexity_tree_save_refresh")
        self.assertFalse(save_btn.disabled)
        save_btn.click()
        app.run()
        self.assertFalse(app.exception)

        saved_tree = store.complexity_tree(self.project_id).set_index("official_model_number")
        self.assertEqual(saved_tree.at["MOD-10", f_console_id], "40WB")
        self.assertEqual(saved_tree.at["MOD-20", f_console_id], "50GB")
        self.assertEqual(saved_tree.at["MOD-30", f_console_id], "DS")


if __name__ == "__main__":
    unittest.main()

