from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from utils import store


class SectionDeletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_section_deletion_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])
        self.part_ids = store.project_table("parts", self.project_id, "part_number")["id"].astype(str).tolist()

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def add_section(self, name: str, parent_id: str | None = None) -> str:
        return store.add_assembly_section(
            self.project_id,
            name,
            "Subassembly" if parent_id else "Main spine",
            parent_id,
            "",
        )

    def add_use(self, section_id: str, part_id: str | None = None) -> str:
        selected_part = part_id or self.part_ids[0]
        store.assign_parts_to_section(
            self.project_id,
            [selected_part],
            section_id,
            allow_additional_use=True,
            quantities_by_part={selected_part: 1.5},
        )
        rows = store.fishbone_part_assignments(self.project_id)
        return str(rows.iloc[-1]["id"])

    def add_yamazumi_area(
        self, section_id: str, scenario_id: str, name: str
    ) -> str:
        area_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, takt_override_s, updated_at)
                   VALUES (?, ?, ?, ?, ?, NULL, ?)""",
                (area_id, self.project_id, scenario_id, section_id, name, store.now_iso()),
            )
        return area_id

    def add_process_group(self, section_id: str, scenario_id: str, name: str) -> str:
        work_id, group_id = str(uuid4()), str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, updated_at)
                   VALUES (?, ?, ?, 10, '10', ?, ?)""",
                (work_id, self.project_id, scenario_id, f"{name} work", timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id, name,
                    selection_rule, quantity, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'Use all', 1, '', ?)""",
                (
                    group_id, self.project_id, scenario_id, work_id, section_id,
                    name, timestamp,
                ),
            )
        return group_id

    def add_scenario(self, name: str, revision: str) -> str:
        scenario_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, status,
                    takt_time_s, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 2, 'Working', 60, ?, ?)""",
                (scenario_id, self.project_id, name, revision, timestamp, timestamp),
            )
        return scenario_id

    def add_assembly(self, built_id: str, installed_id: str) -> str:
        assembly_id = str(uuid4())
        store.save_assembly_catalog_rows(
            self.project_id,
            [
                {
                    "id": assembly_id,
                    "assembly_number": f"ASM-{assembly_id[:8]}",
                    "name": "Deletion test assembly",
                    "make_buy": "Make",
                    "parent_id": None,
                    "built_section_id": built_id,
                    "installed_section_id": installed_id,
                    "active": True,
                    "notes": "",
                }
            ],
        )
        return assembly_id

    def add_grid_category(
        self,
        section_id: str,
        installed_section_id: str | None,
        *,
        ebom_name: str = "Fascia SubAsm",
        display_name: str = "Fascia",
    ) -> str:
        category_id = str(uuid4())
        store.save_assembly_grid_categories(
            self.project_id,
            section_id,
            [{
                "id": category_id,
                "ebom_name": ebom_name,
                "display_name": display_name,
                "root_number": "290D5251",
                "installed_section_id": installed_section_id,
                "sequence": 10,
            }],
        )
        return category_id

    def test_no_reference_deletion_requires_no_target(self) -> None:
        source_id = self.add_section("No references")
        impact = store.assembly_section_delete_impact(self.project_id, [source_id])
        self.assertFalse(impact["requires_repointing"])

        result = store.delete_assembly_sections(
            self.project_id, [source_id], active_scenario_id=self.scenario_id
        )

        self.assertEqual(result["affected_section_count"], 1)
        self.assertTrue(store.assembly_sections(self.project_id).empty)

    def test_combined_repoint_moves_yamazumi_process_and_assembly_references(self) -> None:
        source_id = self.add_section("Combined source")
        target_id = self.add_section("Combined target")
        area_id = self.add_yamazumi_area(source_id, self.scenario_id, "Source area")
        group_id = self.add_process_group(source_id, self.scenario_id, "Source requirement")
        assembly_id = self.add_assembly(source_id, source_id)

        impact = store.assembly_section_delete_impact(self.project_id, [source_id])
        self.assertEqual(impact["yamazumi_area_count"], 1)
        self.assertEqual(impact["process_link_count"], 1)
        self.assertEqual(impact["assembly_reference_count"], 2)
        self.assertTrue(impact["requires_repointing"])

        result = store.delete_assembly_sections(
            self.project_id, [source_id], target_id, self.scenario_id
        )

        self.assertEqual(result["yamazumi_repointed_count"], 1)
        self.assertEqual(result["process_repointed_count"], 1)
        self.assertEqual(result["assembly_replacement_count"], 2)
        self.assertEqual(
            store.query("SELECT section_id FROM yamazumi_areas WHERE id=?", (area_id,))[0]["section_id"],
            target_id,
        )
        self.assertEqual(
            store.query("SELECT section_id FROM process_part_groups WHERE id=?", (group_id,))[0]["section_id"],
            target_id,
        )
        assembly = store.assembly_catalog_rows(self.project_id).set_index("id").loc[assembly_id]
        self.assertEqual(str(assembly["built_section_id"]), target_id)
        self.assertEqual(str(assembly["installed_section_id"]), target_id)

    def test_grid_category_references_require_and_use_the_shared_target(self) -> None:
        source_id = self.add_section("Grid category source")
        target_id = self.add_section("Grid category target")
        category_id = self.add_grid_category(source_id, source_id)

        impact = store.assembly_section_delete_impact(self.project_id, [source_id])

        self.assertEqual(impact["category_built_reference_count"], 1)
        self.assertEqual(impact["category_installed_reference_count"], 1)
        self.assertEqual(impact["category_reference_count"], 2)
        self.assertTrue(impact["requires_repointing"])
        with self.assertRaisesRegex(ValueError, "Choose an existing Fishbone section"):
            store.delete_assembly_sections(
                self.project_id, [source_id], active_scenario_id=self.scenario_id
            )

        result = store.delete_assembly_sections(
            self.project_id, [source_id], target_id, self.scenario_id
        )

        category = store.query(
            "SELECT section_id, installed_section_id FROM assembly_grid_categories WHERE id=?",
            (category_id,),
        )[0]
        self.assertEqual(category["section_id"], target_id)
        self.assertEqual(category["installed_section_id"], target_id)
        self.assertEqual(result["category_built_repointed_count"], 1)
        self.assertEqual(result["category_installed_repointed_count"], 1)

    def test_grid_category_name_collision_identifies_category_field_and_value(self) -> None:
        source_id = self.add_section("Collision source")
        target_id = self.add_section("Collision target")
        self.add_grid_category(
            source_id,
            None,
            ebom_name="Fascia SubAsm",
            display_name="Incoming fascia",
        )
        self.add_grid_category(
            target_id,
            None,
            ebom_name="fascia subasm",
            display_name="Existing fascia",
        )

        validation = store.assembly_section_delete_target_validation(
            self.project_id, [source_id], target_id, self.scenario_id
        )

        self.assertFalse(validation["valid"])
        self.assertEqual(validation["category_conflicts"][0]["field"], "ebom_name")
        self.assertIn("Incoming fascia", validation["message"])
        self.assertIn("Official EBOM category name", validation["message"])
        self.assertIn('"Fascia SubAsm"', validation["message"])
        self.assertIn("Existing fascia", validation["message"])
        self.assertIn("Choose a different target Fishbone section", validation["message"])

    def test_grid_feature_visibility_is_disclosed_and_removed_not_repointed(self) -> None:
        source_id = self.add_section("Visibility source")
        feature_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO complexity_features
                   (id, project_id, category, name, allowed_values, active, updated_at)
                   VALUES (?, ?, 'Product', 'Brand', '[\"Acme\"]', 1, ?)""",
                (feature_id, self.project_id, store.now_iso()),
            )
        store.save_assembly_grid_feature_visibility(
            self.project_id,
            source_id,
            [{"feature_id": feature_id, "is_visible": False}],
        )

        impact = store.assembly_section_delete_impact(self.project_id, [source_id])
        self.assertEqual(impact["feature_visibility_preference_count"], 1)
        self.assertFalse(impact["requires_repointing"])

        result = store.delete_assembly_sections(
            self.project_id, [source_id], active_scenario_id=self.scenario_id
        )
        self.assertEqual(result["feature_visibility_deleted_count"], 1)
        self.assertEqual(
            store.query(
                "SELECT COUNT(*) AS count FROM assembly_grid_feature_visibility WHERE project_id=?",
                (self.project_id,),
            )[0]["count"],
            0,
        )

    def test_descendant_references_are_included_and_repointed(self) -> None:
        parent_id = self.add_section("Delete parent")
        child_id = self.add_section("Delete child", parent_id)
        target_id = self.add_section("Descendant target")
        area_id = self.add_yamazumi_area(child_id, self.scenario_id, "Child area")

        impact = store.assembly_section_delete_impact(self.project_id, [parent_id])
        self.assertEqual(impact["descendant_section_count"], 1)
        self.assertEqual(impact["yamazumi_area_count"], 1)

        store.delete_assembly_sections(
            self.project_id, [parent_id], target_id, self.scenario_id
        )

        self.assertEqual(
            store.query("SELECT section_id FROM yamazumi_areas WHERE id=?", (area_id,))[0]["section_id"],
            target_id,
        )
        remaining_ids = set(store.assembly_sections(self.project_id)["id"].astype(str))
        self.assertNotIn(parent_id, remaining_ids)
        self.assertNotIn(child_id, remaining_ids)

    def test_target_validation_rejects_missing_deleted_and_other_project_sections(self) -> None:
        source_id = self.add_section("Validation source")
        self.add_process_group(source_id, self.scenario_id, "Validation requirement")
        with self.assertRaisesRegex(ValueError, "Choose an existing Fishbone section"):
            store.delete_assembly_sections(
                self.project_id, [source_id], None, self.scenario_id
            )
        with self.assertRaisesRegex(ValueError, "outside the deletion set"):
            store.assembly_section_delete_target_validation(
                self.project_id, [source_id], source_id, self.scenario_id
            )
        other_project_id = str(uuid4())
        other_section_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, created_at, updated_at) VALUES (?, 'Other project', ?, ?)""",
                (other_project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO assembly_sections
                   (id, project_id, name, section_type, sequence, created_at, updated_at)
                   VALUES (?, ?, 'Other section', 'Main spine', 10, ?, ?)""",
                (other_section_id, other_project_id, timestamp, timestamp),
            )
        with self.assertRaisesRegex(ValueError, "from this project"):
            store.assembly_section_delete_target_validation(
                self.project_id, [source_id], other_section_id, self.scenario_id
            )

    def test_cross_scenario_yamazumi_conflict_is_rejected(self) -> None:
        source_id = self.add_section("Cross-scenario source")
        target_id = self.add_section("Cross-scenario target")
        other_scenario_id = self.add_scenario("Other scenario", "B")
        self.add_yamazumi_area(source_id, other_scenario_id, "Other source area")
        self.add_yamazumi_area(target_id, other_scenario_id, "Other target area")

        validation = store.assembly_section_delete_target_validation(
            self.project_id, [source_id], target_id, self.scenario_id
        )

        self.assertFalse(validation["valid"])
        self.assertEqual(validation["conflicts"][0]["scenario_id"], other_scenario_id)
        self.assertIn("already has its own Yamazumi area", validation["message"])
        self.assertIn("Other scenario", validation["message"])
        with self.assertRaisesRegex(ValueError, "already has its own Yamazumi area"):
            store.delete_assembly_sections(
                self.project_id, [source_id], target_id, self.scenario_id
            )
        self.assertTrue(
            store.assembly_sections(self.project_id)["id"].astype(str).eq(source_id).any()
        )

    def test_multiple_source_yamazumi_areas_cannot_share_one_target(self) -> None:
        parent_id = self.add_section("Multiple-area parent")
        child_id = self.add_section("Multiple-area child", parent_id)
        target_id = self.add_section("Multiple-area target")
        self.add_yamazumi_area(parent_id, self.scenario_id, "Parent area")
        self.add_yamazumi_area(child_id, self.scenario_id, "Child area")

        validation = store.assembly_section_delete_target_validation(
            self.project_id, [parent_id], target_id, self.scenario_id
        )

        self.assertFalse(validation["valid"])
        self.assertIn("More than one Yamazumi area would be re-pointed", validation["message"])

    def test_non_component_part_use_returns_to_not_placed(self) -> None:
        source_id = self.add_section("Unassigned source")
        assignment_id = self.add_use(source_id)
        part_id = str(
            store.fishbone_part_assignments(self.project_id)
            .loc[lambda rows: rows["id"].astype(str).eq(assignment_id)]
            .iloc[0]["part_id"]
        )

        store.delete_assembly_sections(
            self.project_id, [source_id], active_scenario_id=self.scenario_id
        )

        assignments = store.fishbone_part_assignments(self.project_id)
        self.assertTrue(assignments.empty)
        self.assertTrue(
            store.project_table("parts", self.project_id, "part_number")["id"]
            .astype(str)
            .eq(part_id)
            .any()
        )

    def test_built_repoint_relocates_minibom_use_before_section_deletion(self) -> None:
        source_id = self.add_section("Mini-BOM source")
        target_id = self.add_section("Mini-BOM target")
        assembly_id = self.add_assembly(source_id, target_id)
        assignment_id = self.add_use(source_id)
        store.save_assembly_bom_components(
            self.project_id,
            assembly_id,
            [{"id": str(uuid4()), "fishbone_assignment_id": assignment_id, "quantity": 1.5}],
        )

        result = store.delete_assembly_sections(
            self.project_id, [source_id], target_id, self.scenario_id
        )

        assignment = store.fishbone_part_assignments(self.project_id).loc[
            lambda rows: rows["id"].astype(str).eq(assignment_id)
        ].iloc[0]
        self.assertEqual(str(assignment["section_id"]), target_id)
        self.assertEqual(result["assembly_replacement_count"], 1)
        component = store.assembly_bom_components(self.project_id, assembly_id).iloc[0]
        self.assertFalse(bool(component["section_mismatch"]))

    def test_saved_state_undo_restores_repointed_references_and_minibom(self) -> None:
        source_id = self.add_section("Undo source")
        target_id = self.add_section("Undo target")
        area_id = self.add_yamazumi_area(source_id, self.scenario_id, "Undo area")
        group_id = self.add_process_group(source_id, self.scenario_id, "Undo requirement")
        assembly_id = self.add_assembly(source_id, source_id)
        assignment_id = self.add_use(source_id)
        component_id = str(uuid4())
        store.save_assembly_bom_components(
            self.project_id,
            assembly_id,
            [{
                "id": component_id,
                "fishbone_assignment_id": assignment_id,
                "quantity": 1.5,
            }],
        )
        category_id = self.add_grid_category(source_id, source_id)
        model_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO project_models
                   (id, project_id, model_number, source_payload, active, updated_at)
                   VALUES (?, ?, 'UNDO-MODEL', '{}', 1, ?)""",
                (model_id, self.project_id, store.now_iso()),
            )
        mapping_id = str(uuid4())
        store.save_assembly_grid_model_mappings(
            self.project_id,
            [{
                "id": mapping_id,
                "category_id": category_id,
                "model_id": model_id,
                "assembly_id": assembly_id,
            }],
        )
        feature_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO complexity_features
                   (id, project_id, category, name, allowed_values, active, updated_at)
                   VALUES (?, ?, 'Product', 'Undo feature', '[\"Yes\"]', 1, ?)""",
                (feature_id, self.project_id, store.now_iso()),
            )
        store.save_assembly_grid_feature_visibility(
            self.project_id,
            source_id,
            [{"feature_id": feature_id, "is_visible": False}],
        )
        snapshot = store.fishbone_plan_snapshot(self.project_id)

        store.delete_assembly_sections(
            self.project_id, [source_id], target_id, self.scenario_id
        )
        store.restore_fishbone_plan_snapshot(self.project_id, snapshot)

        self.assertEqual(
            store.query("SELECT section_id FROM yamazumi_areas WHERE id=?", (area_id,))[0]["section_id"],
            source_id,
        )
        self.assertEqual(
            store.query("SELECT section_id FROM process_part_groups WHERE id=?", (group_id,))[0]["section_id"],
            source_id,
        )
        assembly = store.assembly_catalog_rows(self.project_id).set_index("id").loc[assembly_id]
        self.assertEqual(str(assembly["built_section_id"]), source_id)
        self.assertEqual(str(assembly["installed_section_id"]), source_id)
        assignment = store.fishbone_part_assignments(self.project_id).set_index("id").loc[assignment_id]
        self.assertEqual(str(assignment["section_id"]), source_id)
        component = store.assembly_bom_components(self.project_id, assembly_id).set_index("id").loc[component_id]
        self.assertEqual(float(component["quantity"]), 1.5)
        self.assertFalse(bool(component["section_mismatch"]))
        category = store.query(
            "SELECT section_id, installed_section_id FROM assembly_grid_categories WHERE id=?",
            (category_id,),
        )[0]
        self.assertEqual(category["section_id"], source_id)
        self.assertEqual(category["installed_section_id"], source_id)
        self.assertEqual(
            store.query(
                "SELECT category_id, model_id, assembly_id FROM assembly_grid_model_mappings WHERE id=?",
                (mapping_id,),
            )[0],
            {
                "category_id": category_id,
                "model_id": model_id,
                "assembly_id": assembly_id,
            },
        )
        self.assertEqual(
            store.query(
                "SELECT is_visible FROM assembly_grid_feature_visibility WHERE feature_id=?",
                (feature_id,),
            )[0]["is_visible"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
