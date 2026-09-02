from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pandas as pd

from utils import store


class AssemblyCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_assembly_catalog_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])
        self.built_section_id = store.add_assembly_section(
            self.project_id, "Assembly build", "Main spine", None, ""
        )
        self.installed_section_id = store.add_assembly_section(
            self.project_id, "Final install", "Main spine", None, ""
        )
        self.other_section_id = store.add_assembly_section(
            self.project_id, "Alternate build", "Main spine", None, ""
        )
        self.part_id = str(
            store.project_table("parts", self.project_id, "part_number").iloc[0]["id"]
        )

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def save_assembly(
        self,
        assembly_id: str,
        number: str,
        *,
        parent_id: str | None = None,
        built_section_id: str | None = None,
        installed_section_id: str | None = None,
        make_buy: str = "Make",
    ) -> None:
        store.save_assembly_catalog_rows(
            self.project_id,
            [
                {
                    "id": assembly_id,
                    "assembly_number": number,
                    "name": f"{number} name",
                    "make_buy": make_buy,
                    "parent_id": parent_id,
                    "built_section_id": built_section_id or self.built_section_id,
                    "installed_section_id": installed_section_id or self.installed_section_id,
                    "active": True,
                    "notes": "Catalog note",
                }
            ],
        )

    def add_fishbone_use(self, quantity: float = 1.5) -> str:
        store.assign_parts_to_section(
            self.project_id,
            [self.part_id],
            self.built_section_id,
            allow_additional_use=True,
            quantities_by_part={self.part_id: quantity},
        )
        return str(store.fishbone_part_assignments(self.project_id).iloc[-1]["id"])

    def test_catalog_writer_is_isolated_from_parked_fields_and_scenario_policy(self) -> None:
        assembly_id = str(uuid4())
        self.save_assembly(assembly_id, "ASM-100")
        with store.connection() as conn:
            conn.execute(
                """UPDATE manufacturing_assemblies
                   SET pits_reference='PITS-keep', planning_reason='Purchased complete'
                   WHERE id=?""",
                (assembly_id,),
            )
            conn.execute(
                """INSERT INTO assembly_scenario_policies
                   (project_id, scenario_id, assembly_id, sourcing_decision, supplier,
                    build_area, buffer_policy, storage_location, updated_at)
                   VALUES (?, ?, ?, 'Buy', 'Supplier', '', 'None', '', ?)""",
                (self.project_id, self.scenario_id, assembly_id, store.now_iso()),
            )

        self.save_assembly(assembly_id, "ASM-100")

        row = store.query(
            """SELECT make_buy, pits_reference, planning_reason
               FROM manufacturing_assemblies WHERE id=?""",
            (assembly_id,),
        )[0]
        self.assertEqual(row["make_buy"], "Make")
        self.assertEqual(row["pits_reference"], "PITS-keep")
        self.assertEqual(row["planning_reason"], "Purchased complete")
        self.assertEqual(
            store.query(
                "SELECT COUNT(*) AS count FROM assembly_scenario_policies WHERE assembly_id=?",
                (assembly_id,),
            )[0]["count"],
            1,
        )

    def test_make_buy_preserves_legacy_blank_and_reports_deliberate_change(self) -> None:
        legacy_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO manufacturing_assemblies
                   (id, project_id, assembly_number, name, built_section_id,
                    installed_section_id, created_at, updated_at)
                   VALUES (?, ?, 'ASM-LEGACY', 'Legacy assembly', ?, ?, ?, ?)""",
                (
                    legacy_id,
                    self.project_id,
                    self.built_section_id,
                    self.installed_section_id,
                    store.now_iso(),
                    store.now_iso(),
                ),
            )

        legacy_row = {
            "id": legacy_id,
            "assembly_number": "ASM-LEGACY",
            "name": "Legacy assembly",
            "parent_id": None,
            "built_section_id": self.built_section_id,
            "installed_section_id": self.installed_section_id,
            "active": True,
            "notes": "",
        }
        unchanged = store.save_assembly_catalog_rows(self.project_id, [legacy_row])
        self.assertEqual(unchanged["make_buy_changes"], [])
        self.assertEqual(
            store.query(
                "SELECT make_buy FROM manufacturing_assemblies WHERE id=?", (legacy_id,)
            )[0]["make_buy"],
            "",
        )

        classified = store.save_assembly_catalog_rows(
            self.project_id, [{**legacy_row, "make_buy": "Buy"}]
        )
        self.assertEqual(
            classified["make_buy_changes"],
            [
                {
                    "assembly_id": legacy_id,
                    "assembly_number": "ASM-LEGACY",
                    "old_value": "",
                    "new_value": "Buy",
                }
            ],
        )
        with self.assertRaisesRegex(ValueError, "cannot be cleared"):
            store.save_assembly_catalog_rows(self.project_id, [legacy_row])
        with self.assertRaises(sqlite3.IntegrityError):
            store.execute(
                "UPDATE manufacturing_assemblies SET make_buy='Invalid' WHERE id=?",
                (legacy_id,),
            )

    def test_new_assembly_requires_make_buy(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a Make / buy"):
            store.save_assembly_catalog_rows(
                self.project_id,
                [
                    {
                        "id": str(uuid4()),
                        "assembly_number": "ASM-NO-SOURCE",
                        "name": "Missing classification",
                        "built_section_id": self.built_section_id,
                        "installed_section_id": self.installed_section_id,
                        "active": True,
                        "notes": "",
                    }
                ],
            )

    def test_component_defaults_to_fishbone_quantity_and_built_change_relocates_use(self) -> None:
        first_id, second_id = str(uuid4()), str(uuid4())
        self.save_assembly(first_id, "ASM-200")
        self.save_assembly(second_id, "ASM-201")
        assignment_id = self.add_fishbone_use(1.5)
        store.save_assembly_bom_components(
            self.project_id,
            first_id,
            [{"id": str(uuid4()), "fishbone_assignment_id": assignment_id, "quantity": None}],
        )
        store.save_assembly_bom_components(
            self.project_id,
            second_id,
            [{"id": str(uuid4()), "fishbone_assignment_id": assignment_id, "quantity": 0.02}],
        )
        self.assertEqual(
            store.assembly_bom_components(self.project_id, first_id)["quantity"].tolist(),
            [1.5],
        )

        self.save_assembly(
            first_id,
            "ASM-200",
            built_section_id=self.other_section_id,
        )

        assignment = store.fishbone_part_assignments(self.project_id).loc[
            lambda rows: rows["id"].astype(str).eq(assignment_id)
        ].iloc[0]
        self.assertEqual(str(assignment["section_id"]), self.other_section_id)
        second = store.assembly_bom_components(self.project_id, second_id).iloc[0]
        self.assertTrue(bool(second["section_mismatch"]))
        self.assertEqual(float(second["quantity"]), 0.02)

    def test_stale_rule_is_retained_and_fails_closed(self) -> None:
        assembly_id = str(uuid4())
        feature_id, model_id = str(uuid4()), str(uuid4())
        self.save_assembly(assembly_id, "ASM-300")
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO complexity_features
                   (id, project_id, category, name, allowed_values, active, updated_at)
                   VALUES (?, ?, 'Product', 'Brand', ?, 1, ?)""",
                (feature_id, self.project_id, json.dumps(["Acme", "Other"]), store.now_iso()),
            )
            conn.execute(
                """INSERT INTO project_models
                   (id, project_id, model_number, source_payload, active, updated_at)
                   VALUES (?, ?, 'MODEL-1', '{}', 1, ?)""",
                (model_id, self.project_id, store.now_iso()),
            )
            conn.execute(
                """INSERT INTO model_feature_values
                   (project_id, model_id, feature_id, value, updated_at)
                   VALUES (?, ?, ?, 'Acme', ?)""",
                (self.project_id, model_id, feature_id, store.now_iso()),
            )
        rule_id = str(uuid4())
        store.save_assembly_feature_rules(
            self.project_id,
            assembly_id,
            [{"id": rule_id, "feature_id": feature_id, "value": "Acme"}],
        )
        self.assertEqual(
            store.assembly_model_applicability(self.project_id, assembly_id)["models"][
                "model_number"
            ].tolist(),
            ["MODEL-1"],
        )

        store.execute(
            "UPDATE complexity_features SET active=0 WHERE id=? AND project_id=?",
            (feature_id, self.project_id),
        )

        rules = store.assembly_feature_rules(self.project_id, assembly_id)
        self.assertTrue(bool(rules.iloc[0]["stale"]))
        applicability = store.assembly_model_applicability(self.project_id, assembly_id)
        self.assertTrue(applicability["stale"])
        self.assertTrue(applicability["models"].empty)
        with self.assertRaisesRegex(ValueError, "active feature"):
            store.save_assembly_feature_rules(
                self.project_id,
                assembly_id,
                [{"id": rule_id, "feature_id": feature_id, "value": "Other"}],
            )

    def test_feature_rules_reject_a_second_choice_for_the_same_feature(self) -> None:
        assembly_id, feature_id = str(uuid4()), str(uuid4())
        self.save_assembly(assembly_id, "ASM-301")
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO complexity_features
                   (id, project_id, category, name, allowed_values, active, updated_at)
                   VALUES (?, ?, 'Product', 'Brand', ?, 1, ?)""",
                (feature_id, self.project_id, json.dumps(["Acme", "Other"]), store.now_iso()),
            )
        with self.assertRaisesRegex(ValueError, "at most one choice"):
            store.save_assembly_feature_rules(
                self.project_id,
                assembly_id,
                [
                    {"id": str(uuid4()), "feature_id": feature_id, "value": "Acme"},
                    {"id": str(uuid4()), "feature_id": feature_id, "value": "Other"},
                ],
            )
        store.save_assembly_feature_rules(
            self.project_id,
            assembly_id,
            [{"id": str(uuid4()), "feature_id": feature_id, "value": "Acme"}],
        )
        with self.assertRaises(sqlite3.IntegrityError):
            with store.connection() as conn:
                conn.execute(
                    """INSERT INTO manufacturing_assembly_feature_rules
                       (id, project_id, assembly_id, feature_id, value, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'Other', ?, ?)""",
                    (
                        str(uuid4()), self.project_id, assembly_id, feature_id,
                        store.now_iso(), store.now_iso(),
                    ),
                )

    def test_section_list_reports_built_and_installed_relationships_separately(self) -> None:
        assembly_id = str(uuid4())
        self.save_assembly(
            assembly_id,
            "ASM-302",
            built_section_id=self.built_section_id,
            installed_section_id=self.built_section_id,
        )

        relationships = store.assemblies_for_section(
            self.project_id, self.built_section_id
        )

        self.assertEqual(relationships["assembly_number"].tolist(), ["ASM-302", "ASM-302"])
        self.assertEqual(
            set(relationships["relationship"].tolist()),
            {"Built here", "Installed here"},
        )

    def test_section_repoint_and_fishbone_delete_disclose_and_preserve_relationship_rules(self) -> None:
        assembly_id = str(uuid4())
        self.save_assembly(
            assembly_id,
            "ASM-400",
            built_section_id=self.built_section_id,
            installed_section_id=self.built_section_id,
        )
        assignment_id = self.add_fishbone_use(1.25)
        store.save_assembly_bom_components(
            self.project_id,
            assembly_id,
            [{"id": str(uuid4()), "fishbone_assignment_id": assignment_id, "quantity": 1.25}],
        )
        impact = store.assembly_section_delete_impact(
            self.project_id, [self.built_section_id]
        )
        self.assertEqual(impact["assembly_reference_count"], 2)
        self.assertEqual(impact["assembly_component_count"], 1)
        store.delete_assembly_sections(
            self.project_id,
            [self.built_section_id],
            self.other_section_id,
            self.scenario_id,
        )
        catalog_row = store.assembly_catalog_rows(self.project_id).iloc[0]
        self.assertEqual(str(catalog_row["built_section_id"]), self.other_section_id)
        self.assertEqual(str(catalog_row["installed_section_id"]), self.other_section_id)
        self.assertEqual(
            str(store.fishbone_part_assignments(self.project_id).iloc[0]["section_id"]),
            self.other_section_id,
        )

        assignment_impact = store.fishbone_assignment_assembly_impact(
            self.project_id, [assignment_id]
        )
        self.assertEqual(assignment_impact["assembly_number"].tolist(), ["ASM-400"])
        store.delete_fishbone_part_assignments(self.project_id, [assignment_id])
        self.assertTrue(store.assembly_bom_components(self.project_id, assembly_id).empty)

    def test_multilevel_deletion_applies_one_action_per_level(self) -> None:
        parent_id, child_id, grandchild_id = str(uuid4()), str(uuid4()), str(uuid4())
        self.save_assembly(parent_id, "ASM-500")
        self.save_assembly(child_id, "ASM-501", parent_id=parent_id)
        self.save_assembly(grandchild_id, "ASM-502", parent_id=child_id)
        impact = store.assembly_catalog_delete_impact(self.project_id, [parent_id])
        self.assertEqual(sorted(impact["levels"]), [0, 1, 2])

        result = store.delete_assembly_catalog_rows(
            self.project_id,
            [parent_id],
            {1: "Move to grandparent", 2: "Become unassigned"},
        )

        self.assertEqual(result["deleted_count"], 1)
        remaining = store.assembly_catalog_rows(self.project_id).set_index("id")
        self.assertIsNone(remaining.loc[child_id, "parent_id"])
        self.assertIsNone(remaining.loc[grandchild_id, "parent_id"])
        self.assertTrue(pd.isna(remaining.loc[grandchild_id, "built_section_id"]))
        self.assertTrue(pd.isna(remaining.loc[grandchild_id, "installed_section_id"]))


if __name__ == "__main__":
    unittest.main()
