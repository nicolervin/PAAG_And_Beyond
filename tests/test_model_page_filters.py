from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()

