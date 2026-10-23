from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from utils import store


class PartFeatureInferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_inference_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])

        # Create active models
        # LCD models
        self.lcd_models = ["PFD95ESPB0DS", "PFD95ESPB0RS", "PFD95GSPB0DS", "PFD95GSPB0RS"]
        # Rotary models
        self.rotary_models = ["PFD95ESPB0WS", "PFD95GSPB0WS"]
        self.all_models = self.lcd_models + self.rotary_models

        self.model_ids = {}
        for m in self.all_models:
            mid = str(uuid4())
            self.model_ids[m] = mid
            store.execute(
                """INSERT INTO project_models (id, project_id, model_number, display_name, active, source_payload, updated_at)
                   VALUES (?, ?, ?, ?, 1, '{}', ?)""",
                (mid, self.project_id, m, f"Model {m}", store.now_iso()),
            )

        # Create complexity features
        # 1. Fascia (Control Panel) -> LCD, Rotary
        self.fascia_fid = str(uuid4())
        store.execute(
            """INSERT INTO complexity_features (id, project_id, category, name, allowed_values, active, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?)""",
            (self.fascia_fid, self.project_id, "Control Panel", "Fascia", json.dumps(["Rotary", "LCD"]), store.now_iso()),
        )

        # 2. Fuel Type (Fuel) -> Electric, Gas
        self.fuel_fid = str(uuid4())
        store.execute(
            """INSERT INTO complexity_features (id, project_id, category, name, allowed_values, active, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?)""",
            (self.fuel_fid, self.project_id, "Fuel", "Fuel Type", json.dumps(["Electric", "Gas"]), store.now_iso()),
        )

        # Assign values in model_feature_values
        for m in self.lcd_models:
            mid = self.model_ids[m]
            store.execute(
                """INSERT INTO model_feature_values (project_id, model_id, feature_id, value, updated_at)
                   VALUES (?, ?, ?, 'LCD', ?)""",
                (self.project_id, mid, self.fascia_fid, store.now_iso()),
            )
        for m in self.rotary_models:
            mid = self.model_ids[m]
            store.execute(
                """INSERT INTO model_feature_values (project_id, model_id, feature_id, value, updated_at)
                   VALUES (?, ?, ?, 'Rotary', ?)""",
                (self.project_id, mid, self.fascia_fid, store.now_iso()),
            )

        for m in self.all_models:
            mid = self.model_ids[m]
            fuel_val = "Electric" if "ESP" in m else "Gas"
            store.execute(
                """INSERT INTO model_feature_values (project_id, model_id, feature_id, value, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (self.project_id, mid, self.fuel_fid, fuel_val, store.now_iso()),
            )

        # Create import record for PITS BOM occurrences
        self.import_id = str(uuid4())
        store.execute(
            """INSERT INTO pits_bom_imports (
                id, project_id, import_sequence, workbook_name, workbook_sha256,
                bom_sheet_name, source_row_count, occurrence_count, issue_count,
                imported_by, imported_at
            ) VALUES (?, ?, 1, 'test.xlsx', 'sha', 'BOM', 10, 10, 0, 'tester', ?)""",
            (self.import_id, self.project_id, store.now_iso()),
        )

    def tearDown(self) -> None:
        self.database_patch.stop()
        if self.database_path.exists():
            self.database_path.unlink()

    def _create_part_with_bom(
        self,
        part_number: str,
        description: str,
        models: list[str],
        tracker: str = "",
    ) -> str:
        part_id = str(uuid4())
        ts = store.now_iso()
        store.execute(
            """INSERT INTO parts (id, project_id, part_number, description, pits_tracker_number, model_applicability, updated_at)
               VALUES (?, ?, ?, ?, ?, '', ?)""",
            (part_id, self.project_id, part_number, description, tracker, ts),
        )
        if models:
            usages = {m: 1 for m in models}
            levels_json = json.dumps({"model_usages": usages})
            store.execute(
                """INSERT INTO pits_bom_occurrences (
                    id, project_id, parent_tracker_number, child_tracker_number, child_part_id,
                    proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                    source_fingerprint, raw_levels_json, first_seen_import_id, last_seen_import_id,
                    first_seen_at, last_seen_at, updated_at
                ) VALUES (?, ?, '', ?, ?, 1, 1.0, '1', 1, ?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), self.project_id, tracker or f"trk_{part_id}", part_id, f"fp_{part_id}", levels_json, self.import_id, self.import_id, ts, ts, ts),
            )
        return part_id

    def test_infer_nexus_dryer_user_example(self) -> None:
        """User's specific example: Part 308D3313G001 only found in LCD models."""
        part_id = self._create_part_with_bom(
            part_number="308D3313G001",
            description="Fascia Elec Asm",
            models=self.lcd_models,
            tracker="TRK-LCD-FASCIA",
        )

        inferred = store.infer_part_feature_rules(self.project_id, [part_id])
        self.assertIn(part_id, inferred)
        expected_token = f"{self.fascia_fid}::LCD"
        self.assertEqual(inferred[part_id], [expected_token])

    def test_infer_rotary_and_fuel(self) -> None:
        # Rotary fascia part
        rotary_pid = self._create_part_with_bom(
            part_number="308D3313G002",
            description="Fascia Rotary Asm",
            models=self.rotary_models,
            tracker="TRK-ROTARY-FASCIA",
        )
        # Gas valve part
        gas_models = [m for m in self.all_models if "GSP" in m]
        gas_pid = self._create_part_with_bom(
            part_number="308D8888G001",
            description="Gas Valve Assembly",
            models=gas_models,
            tracker="TRK-GAS-VALVE",
        )
        # Universal part
        all_pid = self._create_part_with_bom(
            part_number="308D9999G001",
            description="Universal Base Channel",
            models=self.all_models,
            tracker="TRK-UNIVERSAL",
        )

        inferred = store.infer_part_feature_rules(
            self.project_id, [rotary_pid, gas_pid, all_pid]
        )

        self.assertEqual(inferred[rotary_pid], [f"{self.fascia_fid}::Rotary"])
        self.assertEqual(inferred[gas_pid], [f"{self.fuel_fid}::Gas"])
        self.assertEqual(inferred[all_pid], ["All models"])

    def test_apply_inferred_rules_preserves_existing(self) -> None:
        part_id = self._create_part_with_bom(
            part_number="308D3313G001",
            description="Fascia Elec Asm",
            models=self.lcd_models,
            tracker="TRK-LCD-FASCIA",
        )

        # Manually assign an existing rule first
        existing_token = f"{self.fuel_fid}::Electric"
        store.update_part_feature_rules(
            self.project_id,
            {part_id: [existing_token]},
        )

        # Run apply with overwrite_existing=False (default)
        updated = store.apply_inferred_part_feature_rules(
            self.project_id,
            overwrite_existing=False,
            part_ids=[part_id],
            editor_name="Test Collaborator",
        )
        self.assertEqual(updated, 0)

        rules_df = store.part_feature_rules(self.project_id)
        assigned = rules_df.loc[rules_df["part_id"] == part_id, "value"].tolist()
        self.assertEqual(assigned, ["Electric"])

        # Run apply with overwrite_existing=True
        updated_overwrite = store.apply_inferred_part_feature_rules(
            self.project_id,
            overwrite_existing=True,
            part_ids=[part_id],
            editor_name="Test Collaborator",
        )
        self.assertEqual(updated_overwrite, 1)

        rules_df = store.part_feature_rules(self.project_id)
        assigned_new = rules_df.loc[rules_df["part_id"] == part_id, "value"].tolist()
        self.assertEqual(assigned_new, ["LCD"])

        # Verify audit log was recorded
        audit_df = store.audit_history(self.project_id)
        auto_assign_events = audit_df[
            audit_df["action"] == "Auto-assign from Complexity tree"
        ]
        self.assertTrue(len(auto_assign_events) >= 1)
        self.assertEqual(auto_assign_events.iloc[0]["editor_name"], "Test Collaborator")

    def test_apply_inferred_includes_all_catalog_parts(self) -> None:
        part_id = self._create_part_with_bom(
            part_number="ASM-TOP-001",
            description="Top Shell Subassembly",
            models=self.lcd_models,
            tracker="TRK-ASM-001",
        )
        updated = store.apply_inferred_part_feature_rules(
            self.project_id,
            overwrite_existing=True,
            part_ids=[part_id],
        )
        self.assertEqual(updated, 1)

    def test_app_test_smoke_parts_and_models(self) -> None:
        """Smoke test verifying pages run without manual auto-assign buttons and Complexity Tree save auto-assigns."""
        from streamlit.testing.v1 import AppTest

        scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])
        part_id = self._create_part_with_bom(
            part_number="308D3313G001",
            description="Fascia Elec Asm",
            models=self.lcd_models,
            tracker="TRK-LCD-FASCIA-AUTO",
        )
        # Seed a stale rule on the part first to confirm Complexity Tree Save & Refresh overwrites it
        store.update_part_feature_rules(
            self.project_id,
            {part_id: [f"{self.fuel_fid}::Electric"]},
        )

        # 1. Models page smoke test & Complexity Tree Save & Refresh auto-assign verification
        at_models = AppTest.from_file(
            str(store.ROOT / "app_pages/models.py"), default_timeout=30
        )
        at_models.session_state["project_id"] = self.project_id
        at_models.session_state["scenario_id"] = scenario_id
        at_models.session_state["current_editor"] = "IE Tester"
        at_models.run()
        self.assertFalse(at_models.exception, f"Models page raised exception: {at_models.exception}")
        model_button_labels = [btn.label for btn in at_models.button]
        self.assertNotIn("Auto-assign to Parts Catalog", model_button_labels)

        # Click Save & Refresh on the Complexity tree footer
        at_models.button(key="complexity_tree_save_refresh").click()
        at_models.run()
        self.assertFalse(at_models.exception, f"Models page Save & Refresh raised exception: {at_models.exception}")
        at_models.button(key=f"save_duplicate_models_anyway_{self.project_id}").click()
        at_models.run()
        self.assertFalse(at_models.exception, f"Models page Save anyway raised exception: {at_models.exception}")

        rules_df = store.part_feature_rules(self.project_id)
        assigned = rules_df.loc[rules_df["part_id"] == part_id, "value"].tolist()
        self.assertEqual(assigned, ["LCD"])

        # 2. Parts page smoke test & button removal verification
        at_parts = AppTest.from_file(
            str(store.ROOT / "app_pages/parts.py"), default_timeout=30
        )
        at_parts.session_state["project_id"] = self.project_id
        at_parts.session_state["scenario_id"] = scenario_id
        at_parts.session_state["current_editor"] = "IE Tester"
        with patch("utils.clipboard_image.clipboard_image", return_value=None):
            at_parts.run()
        self.assertFalse(at_parts.exception, f"Parts page raised exception: {at_parts.exception}")
        parts_button_labels = [btn.label for btn in at_parts.button]
        self.assertNotIn("Auto-assign from Complexity Tree", parts_button_labels)
        self.assertNotIn("Auto-assign selected", parts_button_labels)

    def test_preview_inferred_part_feature_rules_separates_direct_and_review(self) -> None:
        """Verify preview separates single-feature and multi-feature parts."""
        # Single-feature part: LCD models only
        direct_pid = self._create_part_with_bom(
            part_number="PN-DIRECT-001",
            description="LCD Harness",
            models=self.lcd_models,
            tracker="TRK-DIR-001",
        )
        # Multi-feature part: Electric LCD models only (matches both Fascia=LCD and Fuel=Electric)
        multi_models = ["PFD95ESPB0DS", "PFD95ESPB0RS"]
        review_pid = self._create_part_with_bom(
            part_number="PN-REVIEW-001",
            description="Electric LCD Control Board",
            models=multi_models,
            tracker="TRK-REV-001",
        )

        preview = store.preview_inferred_part_feature_rules(
            self.project_id,
            part_ids=[direct_pid, review_pid],
        )

        # Direct assertions
        self.assertIn(direct_pid, preview["direct"])
        self.assertEqual(preview["direct"][direct_pid], [f"{self.fascia_fid}::LCD"])

        # Review assertions
        review_items = [r for r in preview["review"] if r["part_id"] == review_pid]
        self.assertEqual(len(review_items), 1)
        item = review_items[0]
        self.assertEqual(item["part_number"], "PN-REVIEW-001")
        self.assertEqual(item["description"], "Electric LCD Control Board")
        self.assertEqual(item["models"], "PFD95ESPB0DS, PFD95ESPB0RS")
        self.assertEqual(len(item["inferred_tokens"]), 2)
        self.assertIn(f"{self.fascia_fid}::LCD", item["inferred_tokens"])
        self.assertIn(f"{self.fuel_fid}::Electric", item["inferred_tokens"])
        self.assertIn("Control Panel · Fascia = LCD", item["feature_applicability"])
        self.assertIn("Fuel · Fuel Type = Electric", item["feature_applicability"])

        # Options assertions
        self.assertIn("All models", preview["feature_options"])
        self.assertIn("Control Panel · Fascia = LCD", preview["feature_options"])
        self.assertIn("Fuel · Fuel Type = Electric", preview["feature_options"])

    def test_apply_inferred_part_feature_rules_skip_multi_feature(self) -> None:
        """Verify skip_multi_feature=True applies only direct parts without multi-feature parts."""
        direct_pid = self._create_part_with_bom(
            part_number="PN-SKIP-DIR-001",
            description="LCD Bezel",
            models=self.lcd_models,
        )
        multi_models = ["PFD95ESPB0DS", "PFD95ESPB0RS"]
        review_pid = self._create_part_with_bom(
            part_number="PN-SKIP-REV-001",
            description="Electric LCD Display Asm",
            models=multi_models,
        )

        # Apply with skip_multi_feature=True
        updated = store.apply_inferred_part_feature_rules(
            self.project_id,
            overwrite_existing=True,
            part_ids=[direct_pid, review_pid],
            skip_multi_feature=True,
        )
        self.assertEqual(updated, 1)

        # Direct part has rules
        rules_df = store.part_feature_rules(self.project_id)
        direct_rules = rules_df.loc[rules_df["part_id"] == direct_pid, "value"].tolist()
        self.assertEqual(direct_rules, ["LCD"])

        # Review part has no rules
        review_rules = rules_df.loc[rules_df["part_id"] == review_pid, "value"].tolist()
        self.assertEqual(review_rules, [])

    def test_app_test_smoke_review_dialog(self) -> None:
        """Smoke test verifying review dialog renders without exceptions in both models and parts pages."""
        from streamlit.testing.v1 import AppTest

        scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])
        multi_models = ["PFD95ESPB0DS", "PFD95ESPB0RS"]
        review_pid = self._create_part_with_bom(
            part_number="PN-DLG-REV-001",
            description="Electric LCD Display Board",
            models=multi_models,
        )
        preview = store.preview_inferred_part_feature_rules(
            self.project_id,
            part_ids=[review_pid],
        )

        review_state = {
            "preview": preview,
            "source_page": "models",
        }

        # 1. Models page with review dialog active
        at_models = AppTest.from_file(
            str(store.ROOT / "app_pages/models.py"), default_timeout=30
        )
        at_models.session_state["project_id"] = self.project_id
        at_models.session_state["scenario_id"] = scenario_id
        at_models.session_state["current_editor"] = "IE Tester"
        at_models.session_state[f"pending_multi_feature_review_{self.project_id}"] = review_state
        at_models.run()
        self.assertFalse(at_models.exception, f"Models page with review dialog raised exception: {at_models.exception}")

        # 2. Parts page with review dialog active
        at_parts = AppTest.from_file(
            str(store.ROOT / "app_pages/parts.py"), default_timeout=30
        )
        at_parts.session_state["project_id"] = self.project_id
        at_parts.session_state["scenario_id"] = scenario_id
        at_parts.session_state["current_editor"] = "IE Tester"
        at_parts.session_state[f"pending_multi_feature_review_{self.project_id}"] = review_state
        with patch("utils.clipboard_image.clipboard_image", return_value=None):
            at_parts.run()
        self.assertFalse(at_parts.exception, f"Parts page with review dialog raised exception: {at_parts.exception}")

    def test_single_model_bom_defaults_no_keyword_to_all_models(self) -> None:
        """When only 1 model has a BOM, parts with no keyword overlap default to 'All models'."""
        single_model = [self.lcd_models[0]]
        bolt_pid = self._create_part_with_bom(
            part_number="999D1001P001",
            description="M6 Hex Flange Bolt",
            models=single_model,
        )
        inferred = store.infer_part_feature_rules(self.project_id, [bolt_pid])
        self.assertEqual(inferred[bolt_pid], ["All models"])

    def test_single_model_bom_infers_keyword_matching_features(self) -> None:
        """When only 1 model has a BOM, parts with keyword overlap still infer their matching feature."""
        single_model = [self.lcd_models[0]]
        fascia_pid = self._create_part_with_bom(
            part_number="999D2001P001",
            description="Fascia Display Housing",
            models=single_model,
        )
        inferred = store.infer_part_feature_rules(self.project_id, [fascia_pid])
        self.assertEqual(inferred[fascia_pid], [f"{self.fascia_fid}::LCD"])

    def test_multiple_models_bom_tags_distinguishing_features_when_no_keyword(self) -> None:
        """When multiple model BOMs exist and a part is unique to 1 model without keywords, tag distinguishing features."""
        # Create occurrence in rotary model so len(models_with_bom) >= 2
        self._create_part_with_bom(
            part_number="ROTARY-BASE",
            description="Rotary Base Plate",
            models=[self.rotary_models[0]],
        )
        # Create a unique part in LCD model without keyword overlap
        special_bracket = self._create_part_with_bom(
            part_number="999D3001P001",
            description="Special Internal Stiffener",
            models=self.lcd_models,
        )
        inferred = store.infer_part_feature_rules(self.project_id, [special_bracket])
        # Should tag distinguishing features of LCD models (Fascia = LCD)
        self.assertIn(special_bracket, inferred)
        self.assertEqual(inferred[special_bracket], [f"{self.fascia_fid}::LCD"])

    def test_save_manual_model_bom_auto_infers_feature_rules(self) -> None:
        """Saving a manual BOM from scratch automatically infers and updates part feature rules."""
        target_model_num = self.lcd_models[0]
        target_model_id = self.model_ids[target_model_num]

        rows = [
            {
                "level": 1,
                "part_number": "TOP-ASM-001",
                "description": "Top Level Assembly",
                "quantity": 1.0,
            },
            {
                "level": 2,
                "part_number": "FASCIA-LCD-001",
                "description": "Fascia Assembly Front",
                "quantity": 1.0,
            },
        ]
        res = store.save_manual_model_bom(
            self.project_id,
            target_model_id,
            rows,
            auto_add_parts=True,
            editor="Test Collaborator",
        )
        self.assertEqual(res["saved_count"], 2)
        self.assertIn("features_inferred", res)

        # Check part record created for FASCIA-LCD-001
        p_row = store.query(
            "SELECT id, model_applicability FROM parts WHERE project_id=? AND part_number=?",
            (self.project_id, "FASCIA-LCD-001"),
        )[0]
        # Verified feature rule was auto-assigned
        rules_df = store.part_feature_rules(self.project_id)
        part_rules = rules_df.loc[rules_df["part_id"] == p_row["id"], "value"].tolist()
        self.assertEqual(part_rules, ["LCD"])

    def test_infer_excludes_superset_features_found_on_more_models(self) -> None:
        """Broader features found on more models than tighter matching features must not be applied."""
        # Suppose GFD56GR is a 2-model subset of LCD models: ["PFD95ESPB0DS", "PFD95GSPB0DS"]
        gr_models = ["PFD95ESPB0DS", "PFD95GSPB0DS"]
        other_lcd_models = ["PFD95ESPB0RS", "PFD95GSPB0RS"]

        # Specific feature 1: Color · Panels = GR (only on gr_models)
        color_panels_fid = str(uuid4())
        store.execute(
            """INSERT INTO complexity_features (id, project_id, category, name, allowed_values, active, updated_at)
               VALUES (?, ?, 'Color', 'Panels', ?, 1, ?)""",
            (color_panels_fid, self.project_id, json.dumps(["GR", "WW"]), store.now_iso()),
        )
        # Specific feature 2: Control Panel · Control Panel Housing = LG (only on gr_models)
        cp_housing_fid = str(uuid4())
        store.execute(
            """INSERT INTO complexity_features (id, project_id, category, name, allowed_values, active, updated_at)
               VALUES (?, ?, 'Control Panel', 'Control Panel Housing', ?, 1, ?)""",
            (cp_housing_fid, self.project_id, json.dumps(["LG", "WW"]), store.now_iso()),
        )
        # Broader feature: Control Panel · UI Board = A-2 (on all 4 lcd_models: gr_models + other_lcd_models)
        ui_board_fid = str(uuid4())
        store.execute(
            """INSERT INTO complexity_features (id, project_id, category, name, allowed_values, active, updated_at)
               VALUES (?, ?, 'Control Panel', 'UI Board', ?, 1, ?)""",
            (ui_board_fid, self.project_id, json.dumps(["A-2", "B-1"]), store.now_iso()),
        )
        # Broader feature: Control Panel · Knob = Pointer Knob (on all 4 lcd_models)
        knob_fid = str(uuid4())
        store.execute(
            """INSERT INTO complexity_features (id, project_id, category, name, allowed_values, active, updated_at)
               VALUES (?, ?, 'Control Panel', 'Knob', ?, 1, ?)""",
            (knob_fid, self.project_id, json.dumps(["Pointer Knob", "Lens Knob"]), store.now_iso()),
        )

        for m in self.all_models:
            mid = self.model_ids[m]
            is_gr = m in gr_models
            is_lcd = m in self.lcd_models
            store.execute(
                """INSERT INTO model_feature_values (project_id, model_id, feature_id, value, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (self.project_id, mid, color_panels_fid, "GR" if is_gr else "WW", store.now_iso()),
            )
            store.execute(
                """INSERT INTO model_feature_values (project_id, model_id, feature_id, value, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (self.project_id, mid, cp_housing_fid, "LG" if is_gr else "WW", store.now_iso()),
            )
            store.execute(
                """INSERT INTO model_feature_values (project_id, model_id, feature_id, value, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (self.project_id, mid, ui_board_fid, "A-2" if is_lcd else "B-1", store.now_iso()),
            )
            store.execute(
                """INSERT INTO model_feature_values (project_id, model_id, feature_id, value, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (self.project_id, mid, knob_fid, "Pointer Knob" if is_lcd else "Lens Knob", store.now_iso()),
            )

        panel_rh_pid = self._create_part_with_bom(
            part_number="308D3060P005",
            description="PANEL SIDE RH",
            models=gr_models,
            tracker="TRK-PANEL-RH",
        )

        inferred = store.infer_part_feature_rules(self.project_id, [panel_rh_pid])
        self.assertIn(panel_rh_pid, inferred)
        tokens = set(inferred[panel_rh_pid])
        # Specific features matching only gr_models are retained
        self.assertIn(f"{color_panels_fid}::GR", tokens)
        self.assertIn(f"{cp_housing_fid}::LG", tokens)
        # Broader features found on more models (UI Board=A-2, Knob=Pointer Knob, Fascia=LCD) are excluded
        self.assertNotIn(f"{ui_board_fid}::A-2", tokens)
        self.assertNotIn(f"{knob_fid}::Pointer Knob", tokens)
        self.assertNotIn(f"{self.fascia_fid}::LCD", tokens)

    def test_feature_subsystem_persistence_and_auto_assign_filtering(self) -> None:
        """Feature definitions can specify an optional subsystem to limit auto-assigned features."""
        import pandas as pd

        gr_models = ["PFD95ESPB0DS", "PFD95GSPB0DS"]

        # Create a part in subsystem 'Structure' and a PITS record in subsystem 'Control Panel'
        panel_rh_pid = self._create_part_with_bom(
            part_number="308D3060P005",
            description="PANEL SIDE RH",
            models=gr_models,
            tracker="TRK-PANEL-RH-SUB",
        )
        store.execute(
            "UPDATE parts SET subsystem='Structure' WHERE id=? AND project_id=?",
            (panel_rh_pid, self.project_id),
        )

        cp_housing_pid = self._create_part_with_bom(
            part_number="308D4000P001",
            description="HOUSING CONTROL PANEL",
            models=gr_models,
            tracker="TRK-CP-HOUSING-SUB",
        )
        ts = store.now_iso()
        store.execute(
            """INSERT INTO pits_records (
                   id, project_id, pits_id, part_number, description, subsystem,
                   source_payload, source_hash, first_seen_at, last_seen_at
               ) VALUES (?, ?, 'TRK-CP-HOUSING-SUB', '308D4000P001', 'HOUSING CONTROL PANEL', 'Control Panel', '{}', 'hash', ?, ?)""",
            (str(uuid4()), self.project_id, ts, ts),
        )

        # Verify project_part_subsystems discovers both 'Control Panel' and 'Structure'
        subsystems = store.project_part_subsystems(self.project_id)
        self.assertIn("Control Panel", subsystems)
        self.assertIn("Structure", subsystems)

        # Save two features via update_complexity_features:
        # 1. Color · Panels (subsystem='Structure')
        # 2. Control Panel · Control Panel Housing (subsystem='Control Panel')
        existing_features = store.complexity_features(self.project_id)
        color_panels_fid = str(uuid4())
        cp_housing_fid = str(uuid4())
        new_rows = pd.DataFrame([
            {
                "id": color_panels_fid,
                "active": True,
                "category": "Color",
                "subsystem": "Structure",
                "name": "Panels",
                "allowed_choices": "GR, WW",
                "description": "Side and top panel color",
            },
            {
                "id": cp_housing_fid,
                "active": True,
                "category": "Control Panel",
                "subsystem": "Control Panel",
                "name": "Control Panel Housing",
                "allowed_choices": "LG, WW",
                "description": "Control panel housing color",
            },
        ])
        combined = pd.concat(
            [
                existing_features[
                    ["id", "active", "category", "subsystem", "name", "allowed_choices", "description"]
                ],
                new_rows,
            ],
            ignore_index=True,
        )
        store.update_complexity_features(self.project_id, combined)

        saved_features = store.complexity_features(self.project_id).set_index("id")
        self.assertEqual(saved_features.loc[color_panels_fid, "subsystem"], "Structure")
        self.assertEqual(saved_features.loc[cp_housing_fid, "subsystem"], "Control Panel")

        # Assign both features to the exact same gr_models
        for m in self.all_models:
            mid = self.model_ids[m]
            is_gr = m in gr_models
            store.execute(
                """INSERT INTO model_feature_values (project_id, model_id, feature_id, value, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (self.project_id, mid, color_panels_fid, "GR" if is_gr else "WW", store.now_iso()),
            )
            store.execute(
                """INSERT INTO model_feature_values (project_id, model_id, feature_id, value, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (self.project_id, mid, cp_housing_fid, "LG" if is_gr else "WW", store.now_iso()),
            )

        # Case 1: Both features have explicit subsystems -> each part only gets its subsystem's feature
        inferred = store.infer_part_feature_rules(
            self.project_id, [panel_rh_pid, cp_housing_pid]
        )
        self.assertEqual(inferred[panel_rh_pid], [f"{color_panels_fid}::GR"])
        self.assertEqual(inferred[cp_housing_pid], [f"{cp_housing_fid}::LG"])

        # Case 2: Even if Control Panel Housing has a blank subsystem (''), Structure part still
        # only gets Color · Panels = GR because parts with a subsystem only accept matching subsystem features
        store.execute(
            "UPDATE complexity_features SET subsystem='' WHERE id=? AND project_id=?",
            (cp_housing_fid, self.project_id),
        )
        inferred_blank_other = store.infer_part_feature_rules(
            self.project_id, [panel_rh_pid]
        )
        self.assertEqual(inferred_blank_other[panel_rh_pid], [f"{color_panels_fid}::GR"])

        # Case 3: A part in the "Drum" subsystem (Rear Drum Support) can ONLY be assigned features
        # associated with subsystem='Drum' once "Drum" is assigned to a feature, and cannot be
        # assigned a "Main Line" feature (subsystem='') or a feature from another subsystem.
        rds_pid = self._create_part_with_bom(
            part_number="308D3170G002",
            description="REAR DRUM SUPPORT ASM",
            models=gr_models,
            tracker="TRK-RDS-DRUM",
        )
        store.execute(
            "UPDATE parts SET subsystem='Drum' WHERE id=? AND project_id=?",
            (rds_pid, self.project_id),
        )
        # Before "Drum" is assigned to any feature, "Drum" is an unassigned subsystem, so the part
        # can be assigned matching features.
        inferred_rds_before_drum_feat = store.infer_part_feature_rules(
            self.project_id, [rds_pid]
        )
        self.assertTrue(len(inferred_rds_before_drum_feat.get(rds_pid, [])) > 0)

        # Now add an RDS feature associated with subsystem='Drum' alongside the blank-subsystem feature.
        # Because "Drum" is now assigned to a feature, Drum parts can ONLY receive Drum features.
        rds_fid = str(uuid4())
        store.execute(
            """INSERT INTO complexity_features (
                   id, project_id, category, subsystem, name, allowed_values, active, updated_at
               ) VALUES (?, ?, 'RDS', 'Drum', 'RDS Assembly', '["Gas Coated", "Electric Coated"]', 1, ?)""",
            (rds_fid, self.project_id, store.now_iso()),
        )
        for m in self.all_models:
            mid = self.model_ids[m]
            is_gr = m in gr_models
            store.execute(
                """INSERT INTO model_feature_values (project_id, model_id, feature_id, value, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (self.project_id, mid, rds_fid, "Gas Coated" if is_gr else "Electric Coated", store.now_iso()),
            )

        inferred_rds_after_drum_feat = store.infer_part_feature_rules(
            self.project_id, [rds_pid]
        )
        self.assertEqual(inferred_rds_after_drum_feat[rds_pid], [f"{rds_fid}::Gas Coated"])

        # When the Drum feature has no matching model values for a Drum part (e.g. a Drum part
        # driven by a Main Line feature), it falls back to Main Line (blank subsystem) features
        # while still blocking features from other subsystems like Structure.
        unmatched_drum_pid = self._create_part_with_bom(
            part_number="308D3150G002",
            description="FRONT DRUM SUPPORT ASM",
            models=self.lcd_models[:3],
            tracker="TRK-FDS-DRUM",
        )
        store.execute(
            "UPDATE parts SET subsystem='Drum' WHERE id=? AND project_id=?",
            (unmatched_drum_pid, self.project_id),
        )
        inferred_unmatched_drum = store.infer_part_feature_rules(
            self.project_id, [unmatched_drum_pid]
        )
        self.assertEqual(inferred_unmatched_drum[unmatched_drum_pid], [f"{self.fascia_fid}::LCD"])

        # Case 4: A part in a subsystem that is NOT assigned to any feature (e.g. 'Controls')
        # can still be assigned any matching feature (such as Main Line or fuel/panel features).
        controls_pid = self._create_part_with_bom(
            part_number="308D3525G001",
            description="ELECTRIC HARNESS ASM",
            models=[m for m in self.all_models if "ESP" in m],
            tracker="TRK-CTRL-HARNESS",
        )
        store.execute(
            "UPDATE parts SET subsystem='Controls' WHERE id=? AND project_id=?",
            (controls_pid, self.project_id),
        )
        inferred_controls = store.infer_part_feature_rules(
            self.project_id, [controls_pid]
        )
        self.assertEqual(inferred_controls[controls_pid], [f"{self.fuel_fid}::Electric"])

    def test_multi_item_level1_bom_not_excluded_as_top_level_assemblies(self):
        """Verify Level 1 parts and subassemblies in a multi-item Level 1 BOM are not falsely excluded."""
        gas_models = [m for m in self.all_models if "GSP" in m]
        # Create two Level-1 parts on the same models (so each model has >1 Level-1 row) plus a Level-2 child
        sub_pid = self._create_part_with_bom(
            part_number="308D3270G001",
            description="SUB BASE ASM GAS",
            models=gas_models,
            tracker="TRK-L1-SUB-GAS",
        )
        other_l1_pid = self._create_part_with_bom(
            part_number="308D3180G001",
            description="DRUM ASM ALZ",
            models=self.all_models,
            tracker="TRK-L1-DRUM",
        )
        # Add a Level-2 child under TRK-L1-SUB-GAS so l2_plus_pns is non-empty
        child_pid = str(uuid4())
        ts = store.now_iso()
        store.execute(
            """INSERT INTO parts (
                   id, project_id, part_number, description, pits_tracker_number,
                   model_applicability, updated_at
               ) VALUES (?, ?, '312D1390P001', 'VALVE GAS', 'TRK-L2-VALVE', ?, ?)""",
            (child_pid, self.project_id, ", ".join(gas_models), ts),
        )
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                   id, project_id, parent_tracker_number, child_tracker_number, child_part_id,
                   proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                   source_fingerprint, raw_levels_json, first_seen_import_id, last_seen_import_id,
                   first_seen_at, last_seen_at, updated_at
               ) VALUES (?, ?, 'TRK-L1-SUB-GAS', 'TRK-L2-VALVE', ?, 2, 1.0, '1', 2, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                self.project_id,
                child_pid,
                f"fp_{child_pid}",
                json.dumps({"model_usages": {m: 1 for m in gas_models}}),
                self.import_id,
                self.import_id,
                ts,
                ts,
                ts,
            ),
        )

        inferred = store.infer_part_feature_rules(
            self.project_id, [sub_pid, other_l1_pid, child_pid]
        )
        self.assertEqual(inferred[sub_pid], [f"{self.fuel_fid}::Gas"])
        self.assertEqual(inferred[other_l1_pid], ["All models"])
        self.assertEqual(inferred[child_pid], [f"{self.fuel_fid}::Gas"])

    def test_empty_bom_usages_falls_back_to_part_model_applicability(self):
        """Verify a part with empty BOM model_usages falls back to parts.model_applicability."""
        gas_models = [m for m in self.all_models if "GSP" in m]
        part_id = str(uuid4())
        ts = store.now_iso()
        store.execute(
            """INSERT INTO parts (
                   id, project_id, part_number, description, pits_tracker_number,
                   model_applicability, updated_at
               ) VALUES (?, ?, 'STK3D30SPRS', 'LP CONVERSION KIT', 'TRK-EMPTY-BOM', ?, ?)""",
            (part_id, self.project_id, ", ".join(gas_models), ts),
        )
        store.execute(
            """INSERT INTO pits_bom_occurrences (
                   id, project_id, parent_tracker_number, child_tracker_number, child_part_id,
                   proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                   source_fingerprint, raw_levels_json, first_seen_import_id, last_seen_import_id,
                   first_seen_at, last_seen_at, updated_at
               ) VALUES (?, ?, '', 'TRK-EMPTY-BOM', ?, 1, 1.0, '1', 1, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                self.project_id,
                part_id,
                f"fp_{part_id}",
                json.dumps({"model_usages": {}}),
                self.import_id,
                self.import_id,
                ts,
                ts,
                ts,
            ),
        )
        inferred = store.infer_part_feature_rules(self.project_id, [part_id])
        self.assertEqual(inferred[part_id], [f"{self.fuel_fid}::Gas"])

    def test_multi_value_feature_matching_within_single_feature(self):
        """Verify parts spanning multiple choices of a 3+ choice feature receive all matching choices."""
        series_fid = str(uuid4())
        store.execute(
            """INSERT INTO complexity_features (
                   id, project_id, category, subsystem, name, allowed_values, active, updated_at
               ) VALUES (?, ?, 'UI', 'UI', 'LH Fascia', '["55 Series", "66 Series", "86 Series", "96 Series"]', 1, ?)""",
            (series_fid, self.project_id, store.now_iso()),
        )
        series_by_idx = [
            "55 Series",
            "66 Series",
            "66 Series",
            "86 Series",
            "86 Series",
            "96 Series",
        ]
        for idx, m in enumerate(self.all_models):
            mid = self.model_ids[m]
            val = series_by_idx[idx]
            store.execute(
                """INSERT INTO model_feature_values (project_id, model_id, feature_id, value, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (self.project_id, mid, series_fid, val, store.now_iso()),
            )

        # Part used across 66 Series and 86 Series
        shared_models = self.all_models[1:5]
        fascia_pid = self._create_part_with_bom(
            part_number="308D3363P001",
            description="Left Fascia Asm",
            models=shared_models,
            tracker="TRK-LH-FASCIA-SHARED",
        )
        store.execute(
            "UPDATE parts SET subsystem='UI' WHERE id=? AND project_id=?",
            (fascia_pid, self.project_id),
        )
        inferred = store.infer_part_feature_rules(self.project_id, [fascia_pid])
        self.assertEqual(
            inferred[fascia_pid],
            [f"{series_fid}::66 Series", f"{series_fid}::86 Series"],
        )


    def test_cross_feature_subject_nouns_and_category_exclusion_and_final_asm(self) -> None:
        """Verify category exclusion, subject-noun false-positive prevention, sibling-value conflict, and final asm exclusion."""
        proj_id = store.create_project("Model Car Inference Test", "Model Car", "Tester", 60.0)
        pid = str(proj_id)
        models = ["MC100", "MC110", "MC200"]
        m_ids = {}
        for idx, m in enumerate(models, start=1):
            mid = str(uuid4())
            m_ids[m] = mid
            store.execute(
                """INSERT INTO project_models (id, project_id, model_number, display_name, active, source_payload, updated_at)
                   VALUES (?, ?, ?, ?, 1, '{}', ?)""",
                (mid, pid, m, f"Car {m}", store.now_iso()),
            )

        roof_opt_fid = str(uuid4())
        roof_col_fid = str(uuid4())
        wheel_col_fid = str(uuid4())
        wheel_fin_fid = str(uuid4())
        features = [
            (roof_opt_fid, "Body", "Roof option", ["Coupe", "Convertible"]),
            (roof_col_fid, "Body", "Roof Color", ["Teal", "Smoke", "N/A"]),
            (wheel_col_fid, "Wheels", "Wheel Color", ["Teal", "Black"]),
            (wheel_fin_fid, "Wheels", "Wheel Finish", ["Chrome", "Black"]),
        ]
        for fid, cat, name, allowed in features:
            store.execute(
                """INSERT INTO complexity_features (id, project_id, category, name, allowed_values, active, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (fid, pid, cat, name, json.dumps(allowed), store.now_iso()),
            )

        tree_vals = {
            "MC100": {
                roof_opt_fid: "Coupe",
                roof_col_fid: "Teal",
                wheel_col_fid: "Teal",
                wheel_fin_fid: "Chrome",
            },
            "MC110": {
                roof_opt_fid: "Coupe",
                roof_col_fid: "Smoke",
                wheel_col_fid: "Black",
                wheel_fin_fid: "Black",
            },
            "MC200": {
                roof_opt_fid: "Convertible",
                roof_col_fid: "N/A",
                wheel_col_fid: "Black",
                wheel_fin_fid: "Chrome",
            },
        }
        for m, fvals in tree_vals.items():
            for fid, val in fvals.items():
                store.execute(
                    """INSERT INTO model_feature_values (project_id, model_id, feature_id, value, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (pid, m_ids[m], fid, val, store.now_iso()),
                )

        def add_part(pn: str, desc: str, usages: list[str]) -> str:
            part_id = str(uuid4())
            ts = store.now_iso()
            store.execute(
                """INSERT INTO parts (id, project_id, part_number, description, model_applicability, pits_tracker_number, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (part_id, pid, pn, desc, ", ".join(usages), pn, ts),
            )
            store.execute(
                """INSERT INTO pits_bom_occurrences (
                    id, project_id, parent_tracker_number, child_tracker_number, child_part_id,
                    proposed_depth, proposed_quantity, raw_quantity_text, source_row,
                    source_fingerprint, raw_levels_json, first_seen_import_id, last_seen_import_id,
                    first_seen_at, last_seen_at, updated_at
                ) VALUES (?, ?, '', ?, ?, 1, 1.0, '1', 1, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()),
                    pid,
                    pn,
                    part_id,
                    f"fp_{part_id}",
                    json.dumps({"model_usages": {u: 1.0 for u in usages}}),
                    self.import_id,
                    self.import_id,
                    ts,
                    ts,
                    ts,
                ),
            )
            return part_id

        # 1. "Black ABS Roof" on MC110 must match Roof option=Coupe / Roof Color=Smoke, NOT Wheel Color=Black / Wheel Finish=Black
        black_roof_id = add_part("999D8503P002", "Black ABS Roof", ["MC110"])
        # 2. "teal tire" on MC100 must match Wheel Color=Teal, NOT Roof Color=Teal
        teal_tire_id = add_part("999D8505P001", "teal tire", ["MC100"])
        # 3. "Wheel asm (black and chrome)" on MC200 must match Wheel Color=Black & Wheel Finish=Chrome, NOT Wheel Finish=Black
        wheel_bc_id = add_part("999D8505G002", "Wheel asm (black and chrome)", ["MC200"])
        # 4. "Urban Black Coupe final asm" on MC110 must auto-assign all active feature values of MC110
        #    and apply directly without entering the multi-feature review dialog
        final_asm_id = add_part("999D8842G002", "Urban Black Coupe final asm", ["MC110"])

        inferred = store.infer_part_feature_rules(
            pid, [black_roof_id, teal_tire_id, wheel_bc_id, final_asm_id]
        )
        self.assertEqual(
            inferred[black_roof_id],
            [f"{roof_col_fid}::Smoke"],
        )
        self.assertEqual(inferred[teal_tire_id], [f"{wheel_col_fid}::Teal"])
        self.assertEqual(
            set(inferred[wheel_bc_id]),
            {f"{wheel_col_fid}::Black", f"{wheel_fin_fid}::Chrome"},
        )
        self.assertEqual(
            set(inferred[final_asm_id]),
            {
                f"{roof_opt_fid}::Coupe",
                f"{roof_col_fid}::Smoke",
                f"{wheel_col_fid}::Black",
                f"{wheel_fin_fid}::Black",
            },
        )
        preview = store.preview_inferred_part_feature_rules(pid, part_ids=[final_asm_id])
        self.assertIn(final_asm_id, preview["direct"])
        self.assertEqual(preview["review"], [])

        # 5. Complexity tree visual deduplication: when parent assemblies (G groups) and child piece parts (P parts)
        #    are both linked to the same feature choice, each box only displays the specific part/group number once.
        wheel_tc_id = add_part("999D8505G001", "Wheel asm (teal and chrome)", ["MC100"])
        front_tc_id = add_part("999D8402G001", "Front of car body asm (teal and chrome)", ["MC100"])
        back_tc_id = add_part("999D8802G001", "back of car asm (teal and chrome)", ["MC100"])
        store.execute("UPDATE complexity_features SET subsystem='Wheels' WHERE id=?", (wheel_col_fid,))
        store.execute("UPDATE parts SET subsystem='Wheels' WHERE id IN (?, ?)", (teal_tire_id, wheel_tc_id))
        store.execute("UPDATE parts SET subsystem='Chassis' WHERE id IN (?, ?)", (front_tc_id, back_tc_id))
        store.update_part_feature_rules(
            pid,
            {
                teal_tire_id: [f"{wheel_col_fid}::Teal"],
                wheel_tc_id: [f"{wheel_col_fid}::Teal", f"{wheel_fin_fid}::Chrome"],
                front_tc_id: [f"{wheel_col_fid}::Teal", f"{wheel_fin_fid}::Chrome"],
                back_tc_id: [f"{wheel_col_fid}::Teal", f"{wheel_fin_fid}::Chrome"],
            },
        )
        rules_by_fv, bom_desc = store.complexity_visual_part_rules(pid)
        teal_candidates = [
            pn for pn, _ in rules_by_fv.get((wheel_col_fid, "Teal"), [])
        ]
        # Chassis assemblies are excluded from Wheels feature bucket
        self.assertNotIn("999D8402G001", teal_candidates)
        self.assertNotIn("999D8802G001", teal_candidates)
        # Group assembly 999D8505G001 and piece part 999D8505P001 deduplicate to only 999D8505P001
        self.assertEqual(
            store.deduplicate_visual_box_parts(teal_candidates, bom_desc),
            ["999D8505P001"],
        )

    def test_complexity_tree_visual_feature_dropdown_includes_part_name(self) -> None:
        from pathlib import Path
        from streamlit.testing.v1 import AppTest

        part_id = self._create_part_with_bom(
            "PN-LCD-001",
            "7 Inch LCD Display Module",
            self.lcd_models,
        )
        store.update_part_feature_rules(
            self.project_id,
            {part_id: [f"{self.fascia_fid}::LCD"]},
        )

        scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])
        feature_display_key = f"complexity_tree_visual_feature_display_{self.project_id}"
        category_key = f"complexity_tree_visual_category_{self.project_id}"
        model_label_key = f"complexity_tree_visual_model_label_{self.project_id}"

        models_page = str(Path(__file__).resolve().parents[1] / "app_pages" / "models.py")
        app = AppTest.from_file(models_page)
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = scenario_id
        app.session_state[category_key] = ["Control Panel"]
        app.session_state[model_label_key] = ["Model number"]
        app.session_state[feature_display_key] = ["Feature", "Part number", "Part name"]
        app.run(timeout=15)

        self.assertEqual(len(app.exception), 0, f"Models page raised exception: {app.exception}")
        feature_multiselect = next(
            ms for ms in app.multiselect if ms.key == feature_display_key
        )
        self.assertEqual(
            list(feature_multiselect.options),
            ["Feature", "Part number", "Part name"],
        )
        rendered_markdown = "\n".join(md.value for md in app.markdown)
        self.assertIn("PN-LCD-001", rendered_markdown)
        self.assertIn("7 Inch LCD Display Module", rendered_markdown)


if __name__ == "__main__":
    unittest.main()

