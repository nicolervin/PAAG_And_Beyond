from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pandas as pd

from utils import quality_store, store
from utils.equipment_store import (
    DEFAULT_EQUIPMENT_TYPES,
    EQUIPMENT_TIERS,
    UNIT_ORIENTATION_OPTIONS,
    attach_equipment_to_function,
    batch_assign_pitches_to_conveyor_zone,
    clone_equipment_scenario,
    conveyor_zones,
    delete_conveyor_zones,
    delete_conveyor_zone_image,
    delete_equipment_types,
    detach_equipment_from_function,
    equipment_assets,
    equipment_needs_vs_placements_matrix,
    equipment_placement_detail,
    equipment_torque_published_specifications,
    equipment_types,
    save_conveyor_zone,
    save_equipment_placement,
    save_equipment_torque_requirements,
    save_equipment_type_rows,
    save_function_equipment_rows,
    save_pitch_ergonomics_geometry,
    scenario_conveyor_line_sizing,
    scenario_pitches_ergonomics_geometry,
    set_conveyor_zone_image,
    unlink_moved_equipment_links,
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
            {entry[0] for entry in DEFAULT_EQUIPMENT_TYPES},
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

    def test_equipment_tiers_and_type_tier_persistence(self) -> None:
        types = equipment_types(self.project_id)
        self.assertIn("tier", types.columns)
        torque = types.loc[types["label"].eq("Torque tool")].iloc[0]
        self.assertEqual("Handheld Tools", torque["tier"])

        updated_types = types.to_dict("records")
        for t in updated_types:
            if t["label"] == "Torque tool":
                t["tier"] = "Capital Equipment"
        save_equipment_type_rows(self.project_id, updated_types, "Tester")

        reloaded = equipment_types(self.project_id)
        self.assertEqual(
            "Capital Equipment",
            reloaded.loc[reloaded["label"].eq("Torque tool"), "tier"].iloc[0],
        )

        torque_id = str(reloaded.loc[reloaded["label"].eq("Torque tool"), "id"].iloc[0])
        created = save_function_equipment_rows(
            self.project_id,
            "Quality",
            self.scenario_id,
            [{
                "id": "",
                "equipment_type_id": torque_id,
                "name": "Robotic Spindle 01",
                "description": "",
                "manufacturer": "",
                "model": "",
                "notes": "",
                "pitch_id": "",
            }],
            "Tester",
        )
        eq_id = str(created["created_ids"][0])
        assets = equipment_assets(self.project_id, self.scenario_id)
        asset_row = assets.loc[assets["id"].astype(str).eq(eq_id)].iloc[0]
        self.assertEqual("Capital Equipment", asset_row["equipment_tier"])

    def test_equipment_placement_blocked_pitch_and_unlink_moved_links(self) -> None:
        area_id = str(uuid4())
        pitch_id = str(uuid4())
        pitch_id_2 = str(uuid4())
        work_id = str(uuid4())
        now = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO yamazumi_areas (id, project_id, scenario_id, name, updated_at) VALUES (?, ?, ?, ?, ?)",
                (area_id, self.project_id, self.scenario_id, "Main Line", now),
            )
            conn.execute(
                "INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, status, sequence, updated_at) VALUES (?, ?, ?, ?, ?, 'Active', 1, ?)",
                (pitch_id, self.project_id, area_id, "1-A1-1", "Station 1", now),
            )
            conn.execute(
                "INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, status, sequence, updated_at) VALUES (?, ?, ?, ?, ?, 'Active', 2, ?)",
                (pitch_id_2, self.project_id, area_id, "1-A1-2", "Station 2", now),
            )
            conn.execute(
                "INSERT INTO yamazumi_elements (id, project_id, area_id, pitch_id, process_element_id, description, sequence, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (str(uuid4()), self.project_id, area_id, pitch_id, work_id, "Screw Fastening", now),
            )

        store.replace_work_elements(
            self.project_id,
            self.scenario_id,
            pd.DataFrame([{"id": work_id, "station": "01", "operation": "Screw Fastening", "sequence": 1, "pitch_id": pitch_id}]),
        )

        types = equipment_types(self.project_id)
        quality_types = types[types["functional_areas"].apply(lambda fa: "Quality" in (fa or []))]
        type_id = str(quality_types.iloc[0]["id"])
        created = save_function_equipment_rows(
            self.project_id,
            "Quality",
            self.scenario_id,
            [{
                "id": "",
                "equipment_type_id": type_id,
                "name": "Station Screwdriver",
                "description": "",
                "manufacturer": "",
                "model": "",
                "notes": "",
                "pitch_id": "",
            }],
            "Tester",
        )
        eq_id = str(created["created_ids"][0])

        save_equipment_placement(
            self.project_id,
            self.scenario_id,
            eq_id,
            pitch_id,
            [work_id],
            "Tester",
            mark_pitch_blocked=True,
        )

        with store.connection() as conn:
            pitch_status = conn.execute(
                "SELECT status FROM yamazumi_pitches WHERE id = ?", (pitch_id,)
            ).fetchone()[0]
        self.assertEqual("Blocked", pitch_status)

        with store.connection() as conn:
            conn.execute(
                "UPDATE yamazumi_elements SET pitch_id = ? WHERE process_element_id = ?",
                (pitch_id_2, work_id),
            )
        store.replace_work_elements(
            self.project_id,
            self.scenario_id,
            pd.DataFrame([{"id": work_id, "station": "02", "operation": "Screw Fastening", "sequence": 1, "pitch_id": pitch_id_2}]),
        )

        res = unlink_moved_equipment_links(self.project_id, self.scenario_id, eq_id, "Tester")
        self.assertEqual(1, res["row_count"])

        placement = equipment_placement_detail(self.project_id, self.scenario_id, eq_id)
        self.assertEqual(pitch_id, placement["pitch_id"])
        self.assertEqual([], placement["work_element_ids"])

    def test_conveyor_zones_crud_and_sizing(self) -> None:
        area_id = str(uuid4())
        p1 = str(uuid4())
        p2 = str(uuid4())
        now = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO yamazumi_areas (id, project_id, scenario_id, name, updated_at) VALUES (?, ?, ?, ?, ?)",
                (area_id, self.project_id, self.scenario_id, "Main Line", now),
            )
            conn.execute(
                "INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, status, sequence, updated_at) VALUES (?, ?, ?, ?, ?, 'Active', 1, ?)",
                (p1, self.project_id, area_id, "P1", "Pitch 1", now),
            )
            conn.execute(
                "INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, status, sequence, updated_at) VALUES (?, ?, ?, ?, ?, 'Active', 2, ?)",
                (p2, self.project_id, area_id, "P2", "Pitch 2", now),
            )

        zone_data = {
            "name": "Zone A",
            "sequence": 1,
            "start_pitch_id": p1,
            "end_pitch_id": p2,
            "conveyor_height_in": 38.0,
            "conveyor_width_in": 30.0,
            "unit_orientation": "Front Facing",
            "standard_pitch_length_in": 120.0,
            "helper_pitch_count": 1,
            "growth_pitch_count": 1,
            "monument_length_in": 40.0,
            "notes": "Ergonomics reviewed",
        }
        saved = save_conveyor_zone(self.project_id, self.scenario_id, zone_data, "Ergonomist")
        zone_id = saved["id"]

        zones_df = conveyor_zones(self.project_id, self.scenario_id)
        self.assertEqual(1, len(zones_df))
        self.assertEqual("Zone A", zones_df.iloc[0]["name"])
        self.assertEqual(38.0, zones_df.iloc[0]["conveyor_height_in"])
        self.assertEqual(2, zones_df.iloc[0]["active_pitch_count"])
        self.assertEqual(4, zones_df.iloc[0]["total_pitch_count"])
        self.assertEqual(520.0, zones_df.iloc[0]["calculated_total_length_in"])

        sizing = scenario_conveyor_line_sizing(self.project_id, self.scenario_id)
        self.assertEqual(520.0, sizing["total_length_in"])
        self.assertEqual(43.3, sizing["total_length_ft"])
        self.assertEqual(2, sizing["active_pitches"])
        self.assertEqual(1, sizing["helper_pitches"])
        self.assertEqual(1, sizing["growth_pitches"])

        del_res = delete_conveyor_zones(self.project_id, self.scenario_id, [zone_id], "Tester")
        self.assertEqual(1, del_res["row_count"])
        self.assertTrue(conveyor_zones(self.project_id, self.scenario_id).empty)

    def test_conveyor_zones_pitch_multiselect_and_batch_assignment(self) -> None:
        area_id = str(uuid4())
        p1, p2, p3 = str(uuid4()), str(uuid4()), str(uuid4())
        now = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO yamazumi_areas (id, project_id, scenario_id, name, updated_at) VALUES (?, ?, ?, 'Sub-Assembly', ?)",
                (area_id, self.project_id, self.scenario_id, now),
            )
            for idx, (pid, pnum) in enumerate([(p1, "01"), (p2, "02"), (p3, "03")], start=1):
                conn.execute(
                    "INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, status, sequence, updated_at) VALUES (?, ?, ?, ?, ?, 'Active', ?, ?)",
                    (pid, self.project_id, area_id, pnum, f"Pitch {pnum}", idx, now),
                )

        # 1. Save conveyor zone with multiselect pitch_ids [p1, p2]
        zone_data = {
            "name": "Front Conveyor",
            "sequence": 1,
            "pitch_ids": [p1, p2],
            "conveyor_height_in": 36.0,
            "conveyor_width_in": 28.0,
            "unit_orientation": "Front Facing",
            "standard_pitch_length_in": 100.0,
        }
        res = save_conveyor_zone(self.project_id, self.scenario_id, zone_data, "IE Collaborator")
        zone_id = str(res["id"])

        zones_df = conveyor_zones(self.project_id, self.scenario_id)
        self.assertEqual(1, len(zones_df))
        self.assertEqual(2, zones_df.iloc[0]["active_pitch_count"])
        self.assertEqual("01, 02", zones_df.iloc[0]["assigned_pitch_numbers"])

        # Check yamazumi_pitches conveyor_zone_id directly
        pitches_df = scenario_pitches_ergonomics_geometry(self.project_id, self.scenario_id)
        p1_row = pitches_df[pitches_df["id"] == p1].iloc[0]
        p2_row = pitches_df[pitches_df["id"] == p2].iloc[0]
        p3_row = pitches_df[pitches_df["id"] == p3].iloc[0]
        self.assertEqual(zone_id, p1_row["conveyor_zone_id"])
        self.assertEqual(zone_id, p2_row["conveyor_zone_id"])
        self.assertTrue(pd.isna(p3_row["conveyor_zone_id"]) or not p3_row["conveyor_zone_id"])

        # 2. Batch assign p3 to this zone
        batch_res = batch_assign_pitches_to_conveyor_zone(
            self.project_id, self.scenario_id, [p3], zone_id, "IE Collaborator"
        )
        self.assertEqual(1, batch_res["updated_count"])

        zones_df2 = conveyor_zones(self.project_id, self.scenario_id)
        self.assertEqual(3, zones_df2.iloc[0]["active_pitch_count"])
        self.assertEqual("01, 02, 03", zones_df2.iloc[0]["assigned_pitch_numbers"])

        # 3. Batch unassign p1 from zone
        unassign_res = batch_assign_pitches_to_conveyor_zone(
            self.project_id, self.scenario_id, [p1], None, "IE Collaborator"
        )
        self.assertEqual(1, unassign_res["updated_count"])
        zones_df3 = conveyor_zones(self.project_id, self.scenario_id)
        self.assertEqual(2, zones_df3.iloc[0]["active_pitch_count"])
        self.assertEqual("02, 03", zones_df3.iloc[0]["assigned_pitch_numbers"])

    def test_pitch_ergonomics_geometry(self) -> None:
        area_id = str(uuid4())
        p1 = str(uuid4())
        now = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO yamazumi_areas (id, project_id, scenario_id, name, updated_at) VALUES (?, ?, ?, ?, ?)",
                (area_id, self.project_id, self.scenario_id, "Main Line", now),
            )
            conn.execute(
                "INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, status, sequence, updated_at) VALUES (?, ?, ?, ?, ?, 'Active', 1, ?)",
                (p1, self.project_id, area_id, "P1", "Pitch 1", now),
            )

        ergo_df = scenario_pitches_ergonomics_geometry(self.project_id, self.scenario_id)
        self.assertEqual(1, len(ergo_df))
        self.assertEqual(0.0, ergo_df.iloc[0]["platform_height_in"])
        self.assertEqual(0.0, ergo_df.iloc[0]["pit_depth_in"])

        save_pitch_ergonomics_geometry(
            self.project_id,
            self.scenario_id,
            [{"pitch_id": p1, "platform_height_in": 6.5, "pit_depth_in": 0.0, "conveyor_zone_id": ""}],
            "Ergonomist",
        )
        reloaded = scenario_pitches_ergonomics_geometry(self.project_id, self.scenario_id)
        self.assertEqual(6.5, reloaded.iloc[0]["platform_height_in"])

    def test_clone_equipment_scenario_includes_conveyor_zones_and_pitch_ergo(self) -> None:
        area_id = str(uuid4())
        p1 = str(uuid4())
        now = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO yamazumi_areas (id, project_id, scenario_id, name, updated_at) VALUES (?, ?, ?, ?, ?)",
                (area_id, self.project_id, self.scenario_id, "Main Line", now),
            )
            conn.execute(
                "INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, status, sequence, updated_at) VALUES (?, ?, ?, ?, ?, 'Active', 1, ?)",
                (p1, self.project_id, area_id, "P1", "Pitch 1", now),
            )

        save_conveyor_zone(
            self.project_id,
            self.scenario_id,
            {
                "name": "Zone Alpha",
                "sequence": 1,
                "start_pitch_id": p1,
                "end_pitch_id": p1,
                "conveyor_height_in": 36.0,
                "conveyor_width_in": 24.0,
                "unit_orientation": "Front Facing",
                "standard_pitch_length_in": 100.0,
                "helper_pitch_count": 0,
                "growth_pitch_count": 0,
                "monument_length_in": 0.0,
                "notes": "",
            },
            "Tester",
        )
        save_pitch_ergonomics_geometry(
            self.project_id,
            self.scenario_id,
            [{"pitch_id": p1, "platform_height_in": 4.0, "pit_depth_in": 0.0, "conveyor_zone_id": ""}],
            "Tester",
        )

        target_scenario_id = str(uuid4())
        cloned_pitch_id = str(uuid4())
        cloned_area_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO planning_scenarios (id, project_id, name, revision_label, takt_time_s, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (target_scenario_id, self.project_id, "Cloned Scenario", "B", 60.0, now, now),
            )
            conn.execute(
                "INSERT INTO yamazumi_areas (id, project_id, scenario_id, name, updated_at) VALUES (?, ?, ?, ?, ?)",
                (cloned_area_id, self.project_id, target_scenario_id, "Main Line", now),
            )
            conn.execute(
                "INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, status, sequence, updated_at) VALUES (?, ?, ?, 'P1', 'Pitch 1', 'Active', 1, ?)",
                (cloned_pitch_id, self.project_id, cloned_area_id, now),
            )

        pitch_map = {p1: cloned_pitch_id}
        with store.connection() as conn:
            clone_equipment_scenario(
                conn,
                self.project_id,
                self.scenario_id,
                target_scenario_id,
                pitch_id_map=pitch_map,
                process_id_map={},
                timestamp=now,
            )

        cloned_zones = conveyor_zones(self.project_id, target_scenario_id)
        self.assertEqual(1, len(cloned_zones))
        self.assertEqual("Zone Alpha", cloned_zones.iloc[0]["name"])
        if pitch_map:
            self.assertEqual(pitch_map[p1], cloned_zones.iloc[0]["start_pitch_id"])


if __name__ == "__main__":
    unittest.main()

