from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pandas as pd

from utils import quality_store, store
from utils.equipment_store import (
    DEFAULT_EQUIPMENT_TYPES,
    attach_equipment_to_function,
    delete_equipment_types,
    detach_equipment_from_function,
    equipment_assets,
    equipment_needs_vs_placements_matrix,
    equipment_placement_detail,
    equipment_torque_published_specifications,
    equipment_types,
    save_equipment_placement,
    save_equipment_torque_requirements,
    save_equipment_type_rows,
    save_function_equipment_rows,
)


class EquipmentStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_equipment_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_schema_seeds_types_without_active_or_serial_fields(self) -> None:
        types = equipment_types(self.project_id)
        self.assertEqual(
            {label for label, _ in DEFAULT_EQUIPMENT_TYPES},
            set(types["label"].astype(str)),
        )
        self.assertEqual(
            ["Quality"],
            types.loc[types["label"].eq("Torque tool"), "functional_areas"].iloc[0],
        )
        type_columns = {
            str(row["name"])
            for row in store.query("PRAGMA table_info(equipment_types)")
        }
        asset_columns = {
            str(row["name"])
            for row in store.query("PRAGMA table_info(equipment_assets)")
        }
        self.assertNotIn("active", type_columns)
        self.assertNotIn("active", asset_columns)
        self.assertNotIn("serial_number", asset_columns)
        self.assertNotIn("asset_identifier", asset_columns)

    def test_shared_asset_is_not_duplicated_between_reviews(self) -> None:
        types = equipment_types(self.project_id)
        torque = types.loc[types["label"].eq("Torque tool")].iloc[0].to_dict()
        torque["functional_areas"] = ["Quality", "Ergonomics"]
        result = save_equipment_type_rows(
            self.project_id, types.assign(
                functional_areas=types.apply(
                    lambda row: torque["functional_areas"]
                    if str(row["id"]) == str(torque["id"])
                    else row["functional_areas"],
                    axis=1,
                )
            ).to_dict("records"), "Equipment tester"
        )
        self.assertEqual(1, result["row_count"])

        created = save_function_equipment_rows(
            self.project_id,
            "Quality",
            self.scenario_id,
            [{
                "id": "",
                "equipment_type_id": str(torque["id"]),
                "name": "DC Tool 01",
                "description": "Line torque tool",
                "manufacturer": "Example",
                "model": "T-100",
                "notes": "",
                "pitch_id": "",
            }],
            "Equipment tester",
        )
        equipment_id = str(created["created_ids"][0])
        attach_equipment_to_function(
            self.project_id, [equipment_id], "Ergonomics", "Equipment tester"
        )

        quality = equipment_assets(
            self.project_id, self.scenario_id, "Quality"
        )
        ergonomics = equipment_assets(
            self.project_id, self.scenario_id, "Ergonomics"
        )
        self.assertEqual([equipment_id], quality["id"].astype(str).tolist())
        self.assertEqual([equipment_id], ergonomics["id"].astype(str).tolist())

        detach_equipment_from_function(
            self.project_id, [equipment_id], "Ergonomics", "Equipment tester"
        )
        self.assertTrue(
            equipment_assets(self.project_id, self.scenario_id, "Ergonomics").empty
        )
        self.assertEqual(
            [equipment_id],
            equipment_assets(self.project_id, self.scenario_id, "Quality")["id"]
            .astype(str)
            .tolist(),
        )

    def test_names_and_type_labels_are_case_insensitively_unique(self) -> None:
        types = equipment_types(self.project_id)
        torque_id = str(types.loc[types["label"].eq("Torque tool"), "id"].iloc[0])
        base = {
            "id": "",
            "equipment_type_id": torque_id,
            "description": "",
            "manufacturer": "",
            "model": "",
            "notes": "",
            "pitch_id": "",
        }
        with self.assertRaisesRegex(ValueError, "unique"):
            save_function_equipment_rows(
                self.project_id,
                "Quality",
                self.scenario_id,
                [{**base, "name": "Tool A"}, {**base, "name": "tool a"}],
                "Equipment tester",
            )

        duplicate = types.to_dict("records") + [{
            "id": "", "label": "torque TOOL", "functional_areas": ["Quality"]
        }]
        with self.assertRaisesRegex(ValueError, "unique"):
            save_equipment_type_rows(
                self.project_id, duplicate, "Equipment tester"
            )

    def test_type_deletion_is_blocked_while_equipment_uses_it(self) -> None:
        types = equipment_types(self.project_id)
        type_id = str(types.loc[types["label"].eq("Torque tool"), "id"].iloc[0])
        save_function_equipment_rows(
            self.project_id,
            "Quality",
            self.scenario_id,
            [{
                "id": "", "equipment_type_id": type_id, "name": "Used tool",
                "description": "", "manufacturer": "", "model": "",
                "notes": "", "pitch_id": "",
            }],
            "Equipment tester",
        )
        with self.assertRaisesRegex(ValueError, "in use"):
            delete_equipment_types(
                self.project_id, [type_id], "Equipment tester"
            )

    def test_torque_requirement_deletion_is_blocked_while_installed_tool_uses_it(self) -> None:
        types = equipment_types(self.project_id)
        torque_type_id = str(
            types.loc[types["label"].eq("Torque tool"), "id"].iloc[0]
        )
        equipment_result = save_function_equipment_rows(
            self.project_id,
            "Quality",
            self.scenario_id,
            [{
                "id": "", "equipment_type_id": torque_type_id,
                "name": "Installed torque tool", "description": "",
                "manufacturer": "", "model": "", "notes": "", "pitch_id": "",
            }],
            "Equipment tester",
        )
        equipment_id = str(equipment_result["created_ids"][0])
        requirement_id = quality_store.save_quality_requirement(
            self.project_id,
            {
                "requirement_type": "Torque",
                "description": "Tighten fastener",
                "unique_identifier": "TQ-EQUIPMENT-001",
                "pass_fail": True,
                "target_value": 32,
                "tolerances": "+/- 3",
                "unit": "N·m",
            },
        )
        save_equipment_torque_requirements(
            self.project_id,
            equipment_id,
            [requirement_id],
            "Equipment tester",
        )

        with self.assertRaisesRegex(ValueError, "installed Torque equipment link"):
            quality_store.delete_quality_requirements(
                self.project_id, [requirement_id]
            )

        save_equipment_torque_requirements(
            self.project_id, equipment_id, [], "Equipment tester"
        )
        self.assertEqual(
            1,
            quality_store.delete_quality_requirements(
                self.project_id, [requirement_id]
            ),
        )

    def test_scenario_clone_reuses_asset_and_remaps_placement_relationships(self) -> None:
        timestamp = store.now_iso()
        area_id = f"equipment-area-{uuid4()}"
        pitch_id = f"equipment-pitch-{uuid4()}"
        work_id = f"equipment-work-{uuid4()}"
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES (?, ?, ?, 'Equipment area', ?)""",
                (area_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status,
                    sequence, model_variants, pitch_type, updated_at)
                   VALUES (?, ?, ?, '01-EQ1-001', 'Equipment pitch', 'Active',
                           10, '["Base"]', 'Pitch', ?)""",
                (pitch_id, self.project_id, area_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    description, updated_at)
                   VALUES (?, ?, ?, 10, '01-EQ1-001', 'Use equipment',
                           'Use equipment', ?)""",
                (work_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, description, time_s,
                    sequence, process_element_id, updated_at)
                   VALUES (?, ?, ?, ?, 'Use equipment', 1, 10, ?, ?)""",
                (
                    f"equipment-element-{uuid4()}", self.project_id, area_id,
                    pitch_id, work_id, timestamp,
                ),
            )

        types = equipment_types(self.project_id)
        torque_type_id = str(
            types.loc[types["label"].eq("Torque tool"), "id"].iloc[0]
        )
        created = save_function_equipment_rows(
            self.project_id,
            "Quality",
            self.scenario_id,
            [{
                "id": "", "equipment_type_id": torque_type_id,
                "name": "Clone-safe tool", "description": "",
                "manufacturer": "", "model": "", "notes": "",
                "pitch_id": "",
            }],
            "Equipment tester",
        )
        equipment_id = str(created["created_ids"][0])
        save_equipment_placement(
            self.project_id,
            self.scenario_id,
            equipment_id,
            pitch_id,
            [work_id],
            "Equipment tester",
        )

        cloned_scenario_id = store.clone_planning_scenario(
            self.project_id,
            self.scenario_id,
            "Equipment clone",
            "EQ-CLONE",
            60,
            created_by="Equipment tester",
        )
        cloned_pitch_id = str(
            store.query(
                """SELECT pitch.id FROM yamazumi_pitches pitch
                   JOIN yamazumi_areas area ON area.id=pitch.area_id
                   WHERE area.scenario_id=? AND pitch.pitch_number='01-EQ1-001'""",
                (cloned_scenario_id,),
            )[0]["id"]
        )
        cloned_work_id = str(
            store.query(
                """SELECT id FROM work_elements
                   WHERE scenario_id=? AND operation='Use equipment'""",
                (cloned_scenario_id,),
            )[0]["id"]
        )
        source = equipment_placement_detail(
            self.project_id, self.scenario_id, equipment_id
        )
        cloned = equipment_placement_detail(
            self.project_id, cloned_scenario_id, equipment_id
        )

        self.assertNotEqual(source["placement_id"], cloned["placement_id"])
        self.assertEqual(cloned_pitch_id, cloned["pitch_id"])
        self.assertEqual([cloned_work_id], cloned["work_element_ids"])

    def test_torque_specification_uses_published_assignment_snapshot(self) -> None:
        timestamp = store.now_iso()
        area_id = f"published-area-{uuid4()}"
        pitch_id = f"published-pitch-{uuid4()}"
        work_id = f"published-work-{uuid4()}"
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES (?, ?, ?, 'Published equipment area', ?)""",
                (area_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status,
                    sequence, model_variants, pitch_type, updated_at)
                   VALUES (?, ?, ?, '01-EQ2-001', '', 'Active', 10,
                           '["Base"]', 'Pitch', ?)""",
                (pitch_id, self.project_id, area_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    description, updated_at)
                   VALUES (?, ?, ?, 10, '01-EQ2-001', 'Published operation',
                           'Published operation', ?)""",
                (work_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, description, time_s,
                    sequence, process_element_id, updated_at)
                   VALUES (?, ?, ?, ?, 'Published operation', 1, 10, ?, ?)""",
                (
                    f"published-element-{uuid4()}", self.project_id, area_id,
                    pitch_id, work_id, timestamp,
                ),
            )
        torque_type_id = str(
            equipment_types(self.project_id)
            .loc[lambda frame: frame["label"].eq("Torque tool"), "id"]
            .iloc[0]
        )
        equipment_id = str(
            save_function_equipment_rows(
                self.project_id,
                "Quality",
                self.scenario_id,
                [{
                    "id": "", "equipment_type_id": torque_type_id,
                    "name": "Published-spec tool", "description": "",
                    "manufacturer": "", "model": "", "notes": "",
                    "pitch_id": "",
                }],
                "Equipment tester",
            )["created_ids"][0]
        )
        save_equipment_placement(
            self.project_id, self.scenario_id, equipment_id, pitch_id,
            [work_id], "Equipment tester",
        )
        requirement = {
            "requirement_type": "Torque",
            "description": "Published torque",
            "unique_identifier": "TQ-PUBLISHED-001",
            "pass_fail": True,
            "target_value": 32,
            "tolerances": "+/- 3",
            "unit": "N·m",
        }
        requirement_id = quality_store.save_quality_requirement(
            self.project_id, requirement
        )
        quality_store.assign_quality_requirement(
            self.project_id, self.scenario_id, work_id, requirement_id
        )
        quality_store.save_quality_requirement(
            self.project_id,
            {**requirement, "target_value": 45, "tolerances": "+/- 2"},
            requirement_id,
        )

        specification = equipment_torque_published_specifications(
            self.project_id,
            self.scenario_id,
            equipment_id,
            [requirement_id],
        )

        self.assertEqual(1, len(specification))
        self.assertEqual(32, specification.iloc[0]["target_value"])
        self.assertEqual("+/- 3", specification.iloc[0]["tolerances"])
        self.assertEqual("Published operation", specification.iloc[0]["process_function"])

    def test_equipment_needs_vs_placements_matrix(self) -> None:
        work_id = str(uuid4())
        area_id = str(uuid4())
        pitch_id = str(uuid4())
        now = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO yamazumi_areas (id, project_id, scenario_id, name, updated_at) VALUES (?, ?, ?, ?, ?)",
                (area_id, self.project_id, self.scenario_id, "Main Line", now),
            )
            conn.execute(
                "INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (pitch_id, self.project_id, area_id, "1-A1-1", "Station 1", now),
            )
            conn.execute(
                "INSERT INTO yamazumi_elements (id, project_id, area_id, pitch_id, process_element_id, description, sequence, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (str(uuid4()), self.project_id, area_id, pitch_id, work_id, "Torque Bolt", now),
            )

        store.replace_work_elements(
            self.project_id,
            self.scenario_id,
            pd.DataFrame([{"id": work_id, "station": "01", "operation": "Torque Bolt", "sequence": 1, "pitch_id": pitch_id}]),
        )

        req_id = quality_store.save_quality_requirement(
            self.project_id,
            {
                "requirement_type": "Torque",
                "description": "Engine bolt torque",
                "unique_identifier": "TQ-001",
                "pass_fail": True,
                "target_value": 25,
                "tolerances": "+/- 2",
                "unit": "N·m",
            },
        )
        quality_store.assign_quality_requirement(
            self.project_id, self.scenario_id, work_id, req_id
        )

        matrix = equipment_needs_vs_placements_matrix(self.project_id, self.scenario_id)
        self.assertEqual(len(matrix), 1)
        self.assertEqual(matrix.iloc[0]["source_stage"], "Drawing Requirement")
        self.assertEqual(matrix.iloc[0]["expected_equipment_type"], "Torque tool")
        self.assertEqual(matrix.iloc[0]["coverage_status"], "Missing Equipment")
        self.assertFalse(bool(matrix.iloc[0]["is_satisfied"]))

        types = equipment_types(self.project_id)
        torque_type_id = str(types.loc[types["label"].eq("Torque tool"), "id"].iloc[0])
        created = save_function_equipment_rows(
            self.project_id,
            "Quality",
            self.scenario_id,
            [{
                "id": "",
                "equipment_type_id": torque_type_id,
                "name": "DC Tool 01",
                "description": "Torque tool",
                "manufacturer": "",
                "model": "",
                "notes": "",
                "pitch_id": "",
            }],
            "Tester",
        )
        eq_id = str(created["created_ids"][0])
        save_equipment_placement(self.project_id, self.scenario_id, eq_id, pitch_id, [work_id], "Tester")

        matrix_satisfied = equipment_needs_vs_placements_matrix(self.project_id, self.scenario_id)
        self.assertEqual(len(matrix_satisfied), 1)
        self.assertEqual(matrix_satisfied.iloc[0]["coverage_status"], "Satisfied")
        self.assertTrue(bool(matrix_satisfied.iloc[0]["is_satisfied"]))
        self.assertEqual(matrix_satisfied.iloc[0]["linked_asset_names"], "DC Tool 01")


if __name__ == "__main__":
    unittest.main()

