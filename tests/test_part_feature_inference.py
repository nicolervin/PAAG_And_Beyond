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
        """Smoke test verifying pages compile and run without exceptions."""
        from streamlit.testing.v1 import AppTest

        scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])

        # 1. Models page smoke test & dialog verification
        at_models = AppTest.from_file(
            str(store.ROOT / "app_pages/models.py"), default_timeout=30
        )
        at_models.session_state["project_id"] = self.project_id
        at_models.session_state["scenario_id"] = scenario_id
        at_models.session_state["current_editor"] = "IE Tester"
        at_models.session_state["models_pending_auto_assign"] = True
        at_models.run()
        self.assertFalse(at_models.exception, f"Models page raised exception: {at_models.exception}")

        # 2. Parts page smoke test & dialog verification
        at_parts = AppTest.from_file(
            str(store.ROOT / "app_pages/parts.py"), default_timeout=30
        )
        at_parts.session_state["project_id"] = self.project_id
        at_parts.session_state["scenario_id"] = scenario_id
        at_parts.session_state["current_editor"] = "IE Tester"
        at_parts.session_state["parts_pending_auto_assign"] = True
        with patch("utils.clipboard_image.clipboard_image", return_value=None):
            at_parts.run()
        self.assertFalse(at_parts.exception, f"Parts page raised exception: {at_parts.exception}")

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


if __name__ == "__main__":
    unittest.main()

