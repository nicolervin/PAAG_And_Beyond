from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from utils import store


class AssemblyGridStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_assembly_grid_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        self.extra_paths: list[Path] = []
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.built_section_id = store.add_assembly_section(
            self.project_id, "Grid build", "Main spine", None, ""
        )
        self.installed_section_id = store.add_assembly_section(
            self.project_id, "Grid install", "Main spine", None, ""
        )
        self.other_section_id = store.add_assembly_section(
            self.project_id, "Grid alternate", "Main spine", None, ""
        )
        self.model_ids = self._ensure_models(2)

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)
        for path in self.extra_paths:
            path.unlink(missing_ok=True)

    def _ensure_models(self, count: int) -> list[str]:
        saved_models = store.project_models(self.project_id)
        model_ids = (
            [str(value) for value in saved_models["id"]]
            if "id" in saved_models.columns
            else []
        )
        with store.connection() as conn:
            while len(model_ids) < count:
                model_id = str(uuid4())
                model_number = f"GRID-MODEL-{len(model_ids) + 1}"
                conn.execute(
                    """INSERT INTO project_models
                       (id, project_id, model_number, source_payload, updated_at,
                        display_name, active)
                       VALUES (?, ?, ?, '{}', ?, ?, 1)""",
                    (
                        model_id,
                        self.project_id,
                        model_number,
                        store.now_iso(),
                        f"Grid model {len(model_ids) + 1}",
                    ),
                )
                model_ids.append(model_id)
        return model_ids[:count]

    def _save_categories(self) -> tuple[str, str]:
        first_id = str(uuid4())
        second_id = str(uuid4())
        store.save_assembly_grid_categories(
            self.project_id,
            self.built_section_id,
            [
                {
                    "id": first_id,
                    "ebom_name": "FASCIA_EBOM",
                    "display_name": "Fascia SubAsm",
                    "root_number": "290D5251",
                    "installed_section_id": self.installed_section_id,
                    "sequence": 10,
                },
                {
                    "id": second_id,
                    "ebom_name": "BACKSPLASH_EBOM",
                    "display_name": "BackSplash ASM",
                    "root_number": "290D6000",
                    "installed_section_id": self.installed_section_id,
                    "sequence": 20,
                },
            ],
        )
        return first_id, second_id

    def test_schema_and_minimal_assembly_creation(self) -> None:
        table_names = {
            str(row["name"])
            for row in store.query(
                """SELECT name FROM sqlite_master
                   WHERE type='table' AND name LIKE 'assembly_grid_%'"""
            )
        }
        self.assertEqual(
            table_names,
            {
                "assembly_grid_categories",
                "assembly_grid_model_mappings",
                "assembly_grid_feature_visibility",
            },
        )
        category_id, _ = self._save_categories()
        result = store.save_assembly_grid_model_mappings(
            self.project_id,
            [
                {
                    "id": str(uuid4()),
                    "category_id": category_id,
                    "model_id": self.model_ids[0],
                    "assembly_number": "290D5251G020",
                }
            ],
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["created_assemblies"][0]["assembly_number"], "290D5251G020")
        assembly = store.assembly_catalog_rows(self.project_id).iloc[0]
        self.assertEqual(str(assembly["name"]), "Fascia SubAsm")
        self.assertEqual(str(assembly["built_section_id"]), self.built_section_id)
        self.assertEqual(str(assembly["installed_section_id"]), self.installed_section_id)
        self.assertEqual(str(assembly["make_buy"]), "")

    def test_one_assembly_may_serve_many_models_only_inside_one_category(self) -> None:
        first_id, second_id = self._save_categories()
        first_save = store.save_assembly_grid_model_mappings(
            self.project_id,
            [
                {
                    "id": str(uuid4()),
                    "category_id": first_id,
                    "model_id": self.model_ids[0],
                    "assembly_number": "ASM-SHARED",
                },
                {
                    "id": str(uuid4()),
                    "category_id": first_id,
                    "model_id": self.model_ids[1],
                    "assembly_number": "ASM-SHARED",
                },
            ],
        )
        self.assertEqual(first_save["count"], 2)
        mappings = store.assembly_grid_model_mappings(self.project_id)
        assembly_id = str(mappings.iloc[0]["assembly_id"])

        with self.assertRaisesRegex(ValueError, "already mapped under category"):
            store.save_assembly_grid_model_mappings(
                self.project_id,
                [
                    {
                        "id": str(mappings.iloc[0]["id"]),
                        "category_id": first_id,
                        "model_id": self.model_ids[0],
                        "assembly_id": assembly_id,
                    },
                    {
                        "id": str(uuid4()),
                        "category_id": second_id,
                        "model_id": self.model_ids[1],
                        "assembly_id": assembly_id,
                    },
                ],
            )

    def test_category_installed_section_continuously_syncs_mapped_assemblies(self) -> None:
        category_id, _ = self._save_categories()
        store.save_assembly_grid_model_mappings(
            self.project_id,
            [
                {
                    "id": str(uuid4()),
                    "category_id": category_id,
                    "model_id": self.model_ids[0],
                    "assembly_number": "ASM-SYNC",
                }
            ],
        )
        mapping = store.assembly_grid_model_mappings(self.project_id).iloc[0]
        assembly_id = str(mapping["assembly_id"])
        result = store.save_assembly_grid_categories(
            self.project_id,
            self.built_section_id,
            [
                {
                    "id": category_id,
                    "ebom_name": "FASCIA_EBOM",
                    "display_name": "Fascia SubAsm",
                    "root_number": "290D5251",
                    "installed_section_id": self.other_section_id,
                    "sequence": 10,
                }
            ],
        )
        self.assertEqual(len(result["installed_section_sync_changes"]), 1)
        assembly = store.assembly_catalog_rows(self.project_id).iloc[0]
        self.assertEqual(str(assembly["installed_section_id"]), self.other_section_id)

        with self.assertRaisesRegex(ValueError, "Change its Built or Installed section"):
            store.save_assembly_catalog_rows(
                self.project_id,
                [
                    {
                        "id": assembly_id,
                        "assembly_number": "ASM-SYNC",
                        "name": "Fascia SubAsm",
                        "make_buy": "Make",
                        "parent_id": None,
                        "built_section_id": self.built_section_id,
                        "installed_section_id": self.installed_section_id,
                        "active": True,
                        "notes": "",
                    }
                ],
            )

    def test_mapping_removal_preserves_assembly(self) -> None:
        category_id, _ = self._save_categories()
        store.save_assembly_grid_model_mappings(
            self.project_id,
            [
                {
                    "category_id": category_id,
                    "model_id": self.model_ids[0],
                    "assembly_number": "ASM-PRESERVE",
                }
            ],
        )
        assembly_id = str(store.assembly_grid_model_mappings(self.project_id).iloc[0]["assembly_id"])
        store.save_assembly_grid_model_mappings(self.project_id, [])
        self.assertTrue(store.assembly_grid_model_mappings(self.project_id).empty)
        self.assertEqual(
            store.query(
                "SELECT COUNT(*) AS count FROM manufacturing_assemblies WHERE id=?",
                (assembly_id,),
            )[0]["count"],
            1,
        )

    def test_editing_mapped_part_number_renames_assembly_and_preserves_mini_bom(self) -> None:
        category_id, _ = self._save_categories()
        store.save_assembly_grid_model_mappings(
            self.project_id,
            [
                {
                    "category_id": category_id,
                    "model_id": self.model_ids[0],
                    "assembly_number": "ASM-BEFORE",
                },
                {
                    "category_id": category_id,
                    "model_id": self.model_ids[1],
                    "assembly_number": "ASM-BEFORE",
                },
            ],
        )
        mappings = store.assembly_grid_model_mappings(self.project_id).set_index("model_id")
        first_mapping = mappings.loc[self.model_ids[0]]
        second_mapping = mappings.loc[self.model_ids[1]]
        assembly_id = str(first_mapping["assembly_id"])
        part_id = str(
            store.project_table("parts", self.project_id, "part_number").iloc[0]["id"]
        )
        store.assign_parts_to_section(
            self.project_id,
            [part_id],
            self.built_section_id,
            allow_additional_use=True,
            quantities_by_part={part_id: 2.5},
        )
        assignment = store.fishbone_part_assignments(self.project_id).loc[
            lambda rows: rows["section_id"].astype(str).eq(self.built_section_id)
            & rows["part_id"].astype(str).eq(part_id)
        ].iloc[-1]
        component_id = str(uuid4())
        store.save_assembly_bom_components(
            self.project_id,
            assembly_id,
            [{
                "id": component_id,
                "fishbone_assignment_id": str(assignment["id"]),
                "quantity": 1.75,
            }],
        )

        result = store.save_assembly_grid_model_mappings(
            self.project_id,
            [
                {
                    "id": str(first_mapping["id"]),
                    "category_id": category_id,
                    "model_id": self.model_ids[0],
                    "assembly_id": assembly_id,
                    "assembly_number": "ASM-AFTER",
                },
                {
                    "id": str(second_mapping["id"]),
                    "category_id": category_id,
                    "model_id": self.model_ids[1],
                    "assembly_id": assembly_id,
                    # This is the unchanged value from the other rendered cell.
                    "assembly_number": "ASM-BEFORE",
                },
            ],
        )

        self.assertEqual(result["created_assemblies"], [])
        self.assertEqual(
            result["renamed_assemblies"],
            [{
                "assembly_id": assembly_id,
                "old_assembly_number": "ASM-BEFORE",
                "assembly_number": "ASM-AFTER",
            }],
        )
        assemblies = store.assembly_catalog_rows(self.project_id)
        self.assertEqual(len(assemblies), 1)
        self.assertEqual(str(assemblies.iloc[0]["id"]), assembly_id)
        self.assertEqual(str(assemblies.iloc[0]["assembly_number"]), "ASM-AFTER")
        saved_mappings = store.assembly_grid_model_mappings(self.project_id)
        self.assertEqual(len(saved_mappings), 2)
        self.assertEqual(set(saved_mappings["assembly_id"].astype(str)), {assembly_id})
        self.assertEqual(set(saved_mappings["assembly_number"]), {"ASM-AFTER"})
        components = store.assembly_bom_components(self.project_id, assembly_id)
        self.assertEqual(str(components.iloc[0]["id"]), component_id)
        self.assertEqual(float(components.iloc[0]["quantity"]), 1.75)

    def test_mapped_part_number_rename_rejects_another_assembly_number(self) -> None:
        category_id, _ = self._save_categories()
        store.save_assembly_grid_model_mappings(
            self.project_id,
            [
                {
                    "category_id": category_id,
                    "model_id": self.model_ids[0],
                    "assembly_number": "ASM-FIRST",
                },
                {
                    "category_id": category_id,
                    "model_id": self.model_ids[1],
                    "assembly_number": "ASM-SECOND",
                },
            ],
        )
        mappings = store.assembly_grid_model_mappings(self.project_id).set_index("model_id")
        first = mappings.loc[self.model_ids[0]]
        second = mappings.loc[self.model_ids[1]]

        with self.assertRaisesRegex(ValueError, "already belongs to another assembly"):
            store.save_assembly_grid_model_mappings(
                self.project_id,
                [
                    {
                        "id": str(first["id"]),
                        "category_id": category_id,
                        "model_id": self.model_ids[0],
                        "assembly_id": str(first["assembly_id"]),
                        "assembly_number": "ASM-SECOND",
                    },
                    {
                        "id": str(second["id"]),
                        "category_id": category_id,
                        "model_id": self.model_ids[1],
                        "assembly_id": str(second["assembly_id"]),
                        "assembly_number": "ASM-SECOND",
                    },
                ],
            )

        self.assertEqual(
            set(store.assembly_catalog_rows(self.project_id)["assembly_number"]),
            {"ASM-FIRST", "ASM-SECOND"},
        )

    def test_confirmed_existing_number_merge_uses_target_mini_bom_and_deletes_source(self) -> None:
        category_id, _ = self._save_categories()
        store.save_assembly_grid_model_mappings(
            self.project_id,
            [
                {
                    "category_id": category_id,
                    "model_id": self.model_ids[0],
                    "assembly_number": "ASM-OLD",
                },
                {
                    "category_id": category_id,
                    "model_id": self.model_ids[1],
                    "assembly_number": "ASM-EXISTING",
                },
            ],
        )
        mappings = store.assembly_grid_model_mappings(self.project_id).set_index("model_id")
        source = mappings.loc[self.model_ids[0]]
        target = mappings.loc[self.model_ids[1]]
        source_id = str(source["assembly_id"])
        target_id = str(target["assembly_id"])
        part_id = str(
            store.project_table("parts", self.project_id, "part_number").iloc[0]["id"]
        )
        store.assign_parts_to_section(
            self.project_id,
            [part_id],
            self.built_section_id,
            allow_additional_use=True,
            quantities_by_part={part_id: 2.5},
        )
        assignment_id = str(
            store.fishbone_part_assignments(self.project_id).loc[
                lambda rows: rows["section_id"].astype(str).eq(self.built_section_id)
                & rows["part_id"].astype(str).eq(part_id)
            ].iloc[-1]["id"]
        )
        source_component_id = str(uuid4())
        target_component_id = str(uuid4())
        store.save_assembly_bom_components(
            self.project_id,
            source_id,
            [{
                "id": source_component_id,
                "fishbone_assignment_id": assignment_id,
                "quantity": 1.0,
            }],
        )
        store.save_assembly_bom_components(
            self.project_id,
            target_id,
            [{
                "id": target_component_id,
                "fishbone_assignment_id": assignment_id,
                "quantity": 3.0,
            }],
        )
        category = store.assembly_grid_categories(
            self.project_id, self.built_section_id
        ).loc[lambda rows: rows["id"].astype(str).eq(category_id)].iloc[0]
        mapping_rows = [
            {
                "id": str(source["id"]),
                "category_id": category_id,
                "model_id": self.model_ids[0],
                "assembly_id": source_id,
                "assembly_number": "ASM-EXISTING",
            },
            {
                "id": str(target["id"]),
                "category_id": category_id,
                "model_id": self.model_ids[1],
                "assembly_id": target_id,
                "assembly_number": "ASM-EXISTING",
            },
        ]
        impacts = store.assembly_grid_number_merge_impact(
            self.project_id, mapping_rows
        )
        self.assertEqual(len(impacts), 1)
        self.assertEqual(impacts[0]["source_assembly_id"], source_id)
        self.assertEqual(impacts[0]["target_assembly_id"], target_id)
        self.assertEqual(impacts[0]["source_component_count"], 1)
        self.assertEqual(impacts[0]["target_component_count"], 1)

        with self.assertRaisesRegex(ValueError, "Review and confirm"):
            store.save_assembly_grid_section(
                self.project_id,
                self.built_section_id,
                [dict(category)],
                mapping_rows,
                [],
                {},
            )

        result = store.save_assembly_grid_section(
            self.project_id,
            self.built_section_id,
            [dict(category)],
            mapping_rows,
            [],
            {
                source_id: [{
                    "id": source_component_id,
                    "fishbone_assignment_id": assignment_id,
                    "quantity": 1.0,
                }],
                target_id: [{
                    "id": target_component_id,
                    "fishbone_assignment_id": assignment_id,
                    "quantity": 3.0,
                }],
            },
            assembly_merges=impacts,
        )

        self.assertEqual(len(result["assembly_merges"]), 1)
        assemblies = store.assembly_catalog_rows(self.project_id)
        self.assertNotIn("ASM-OLD", set(assemblies["assembly_number"]))
        saved_mappings = store.assembly_grid_model_mappings(self.project_id)
        self.assertEqual(set(saved_mappings["assembly_id"].astype(str)), {target_id})
        components = store.assembly_bom_components(self.project_id, target_id)
        self.assertEqual(components["id"].astype(str).tolist(), [target_component_id])
        self.assertEqual(components["quantity"].tolist(), [3.0])
        self.assertEqual(
            store.query(
                "SELECT COUNT(*) AS count FROM manufacturing_assemblies WHERE id=?",
                (source_id,),
            )[0]["count"],
            0,
        )

    def test_feature_visibility_stores_only_hidden_preferences(self) -> None:
        features = store.complexity_features(self.project_id)
        if features.empty:
            feature_id = str(uuid4())
            with store.connection() as conn:
                conn.execute(
                    """INSERT INTO complexity_features
                       (id, project_id, category, name, allowed_values,
                        description, sequence, active, updated_at)
                       VALUES (?, ?, 'Appearance', 'Color', ?, '', 10, 1, ?)""",
                    (feature_id, self.project_id, '["Red", "Blue"]', store.now_iso()),
                )
            features = store.complexity_features(self.project_id)
        feature_ids = features["id"].astype(str).tolist()
        store.save_assembly_grid_feature_visibility(
            self.project_id,
            self.built_section_id,
            [
                {"feature_id": feature_ids[0], "is_visible": False},
                *(
                    [{"feature_id": feature_ids[1], "is_visible": True}]
                    if len(feature_ids) > 1
                    else []
                ),
            ],
        )
        preferences = store.query(
            """SELECT feature_id, is_visible FROM assembly_grid_feature_visibility
               WHERE project_id=? AND section_id=?""",
            (self.project_id, self.built_section_id),
        )
        self.assertEqual(len(preferences), 1)
        self.assertEqual(str(preferences[0]["feature_id"]), feature_ids[0])
        visible = store.assembly_grid_feature_visibility(
            self.project_id, self.built_section_id
        ).set_index("feature_id")
        self.assertEqual(int(visible.loc[feature_ids[0], "is_visible"]), 0)

    def test_verified_backup_precedes_audited_one_time_assembly_reset(self) -> None:
        category_id, _ = self._save_categories()
        store.save_assembly_grid_model_mappings(
            self.project_id,
            [{
                "category_id": category_id,
                "model_id": self.model_ids[0],
                "assembly_number": "ASM-RESET",
            }],
        )
        backup_path = store.DATA_DIR / f"test_backup_{uuid4()}.db"
        self.extra_paths.append(backup_path)
        verified = store.backup_database(backup_path)

        summary = store.reset_manufacturing_assembly_catalog(verified, "Nicole Ervin")

        self.assertTrue(verified.exists())
        self.assertEqual(summary["assembly_count"], 1)
        self.assertEqual(summary["grid_mapping_count"], 1)
        self.assertEqual(
            store.query("SELECT COUNT(*) AS count FROM manufacturing_assemblies")[0]["count"],
            0,
        )
        event = store.query(
            """SELECT action, row_count, editor_name FROM audit_log
               WHERE project_id=? AND table_name='Assemblies catalog'
               ORDER BY created_at DESC LIMIT 1""",
            (self.project_id,),
        )[0]
        self.assertEqual(event["action"], "Prototype data reset")
        self.assertEqual(event["row_count"], 1)
        self.assertEqual(event["editor_name"], "Nicole Ervin")

    def test_complete_section_save_rolls_back_every_table_on_validation_failure(self) -> None:
        category_id, _ = self._save_categories()
        with self.assertRaisesRegex(ValueError, "current official model"):
            store.save_assembly_grid_section(
                self.project_id,
                self.built_section_id,
                [{
                    "id": category_id,
                    "ebom_name": "FASCIA_EBOM",
                    "display_name": "Should roll back",
                    "root_number": "290D5251",
                    "installed_section_id": self.installed_section_id,
                    "sequence": 10,
                }],
                [{
                    "category_id": category_id,
                    "model_id": "missing-model",
                    "assembly_number": "ASM-INVALID",
                }],
                [],
            )
        category = store.query(
            "SELECT display_name FROM assembly_grid_categories WHERE id=?", (category_id,)
        )[0]
        self.assertEqual(category["display_name"], "Fascia SubAsm")
        self.assertEqual(
            store.query("SELECT COUNT(*) AS count FROM manufacturing_assemblies")[0]["count"],
            0,
        )

    def test_model_saved_state_undo_restores_direct_grid_mappings(self) -> None:
        category_id, _ = self._save_categories()
        store.save_assembly_grid_model_mappings(
            self.project_id,
            [{
                "category_id": category_id,
                "model_id": self.model_ids[0],
                "assembly_number": "ASM-MODEL-UNDO",
            }],
        )
        mapping_id = str(store.assembly_grid_model_mappings(self.project_id).iloc[0]["id"])
        snapshot = store.model_planning_snapshot(self.project_id)

        store.delete_project_models(self.project_id, [self.model_ids[0]])
        self.assertTrue(store.assembly_grid_model_mappings(self.project_id).empty)
        store.restore_model_planning_snapshot(self.project_id, snapshot)

        self.assertEqual(
            store.query(
                "SELECT COUNT(*) AS count FROM assembly_grid_model_mappings WHERE id=?",
                (mapping_id,),
            )[0]["count"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
