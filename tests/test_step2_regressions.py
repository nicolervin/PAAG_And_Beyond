from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from utils import (
    control_plan_store,
    db_core,
    equipment_store,
    fishbone_store,
    pfmea_pattern_store,
    pfmea_store,
    process_store,
    project_store,
    project_transfer,
    quality_store,
    recycle_bin_store,
    store,
)


class Step2RegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.db_path = self.temp_path / "test_step2.db"
        self.upload_dir = self.temp_path / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)

        self.orig_db_path = db_core.DB_PATH
        self.orig_upload_dir = db_core.UPLOAD_DIR

        db_core.DB_PATH = self.db_path
        store.DB_PATH = self.db_path
        db_core.UPLOAD_DIR = self.upload_dir
        store.UPLOAD_DIR = self.upload_dir
        db_core._SCHEMA_INITIALIZED = False
        store.init_db()

    def tearDown(self) -> None:
        db_core.DB_PATH = self.orig_db_path
        store.DB_PATH = self.orig_db_path
        db_core.UPLOAD_DIR = self.orig_upload_dir
        store.UPLOAD_DIR = self.orig_upload_dir
        db_core._SCHEMA_INITIALIZED = False
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_item5_scenario_cloning_completeness_and_media_isolation(self) -> None:
        proj_id = str(store.create_project("Clone Project", "P1", "L1", 60.0))
        scen_id = str(store.planning_scenarios(proj_id)[0]["id"])
        ts = store.now_iso()

        # 1. Create a linked work element, assign quality & PFMEA, then unlink by deleting work element
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements (id, project_id, scenario_id, sequence, station, operation, description, updated_at)
                   VALUES ('we-temp', ?, ?, 10, 'P-10', 'Install bolt', 'Desc', ?)""",
                (proj_id, scen_id, ts),
            )
        req_id = quality_store.save_quality_requirement(
            proj_id,
            {
                "requirement_type": "Torque",
                "description": "Bolt torque",
                "unique_identifier": "TQ-100",
                "pass_fail": False,
                "target_value": 25.0,
                "tolerances": "+/- 2",
                "unit": "Nm",
            },
        )
        q_assign_id = quality_store.assign_quality_requirement(proj_id, scen_id, "we-temp", req_id)
        pfmea_entry_id = pfmea_store.save_pfmea_entry_rows(
            proj_id,
            scen_id,
            "we-temp",
            pd.DataFrame([{"id": "", "potential_failure_mode": "Loose bolt", "class_code": "S"}]),
        )["created_ids"][0]

        store.replace_work_elements(proj_id, scen_id, pd.DataFrame())

        unlinked_q = store.query(
            "SELECT * FROM quality_requirement_assignments WHERE project_id=? AND scenario_id=? AND work_element_id IS NULL",
            (proj_id, scen_id),
        )
        self.assertEqual(len(unlinked_q), 1)
        unlinked_p = pfmea_store.pfmea_entries(proj_id, scen_id)
        self.assertEqual(len(unlinked_p), 1)
        self.assertTrue(bool(unlinked_p.iloc[0]["is_unlinked"]))

        # 2. Create scenario-scoped layout layer + shapes with group/connector references
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO layout_plans (id, project_id, name, created_at, updated_at)
                   VALUES ('plan-1', ?, 'Main Layout', ?, ?)""",
                (proj_id, ts, ts),
            )
            conn.execute(
                """INSERT INTO layout_revisions (id, layout_id, revision_number, image_path, width_value, height_value, unit, created_at)
                   VALUES ('rev-1', 'plan-1', 1, 'uploads/blank.png', 100.0, 100.0, 'ft', ?)""",
                (ts,),
            )
            conn.execute(
                """INSERT INTO layout_layers (id, revision_id, scenario_id, name, layer_type, visible, locked, opacity, z_index, color, created_at, updated_at)
                   VALUES ('layer-src', 'rev-1', ?, 'Scenario Layer', 'custom', 1, 0, 1.0, 10, '#2563EB', ?, ?)""",
                (scen_id, ts, ts),
            )
            conn.execute(
                """INSERT INTO layout_shapes (id, revision_id, layer_id, shape_type, label, x, y, width, height, group_id, created_at, updated_at)
                   VALUES ('shape-rect', 'rev-1', 'layer-src', 'rectangle', 'Box 1', 10, 10, 50, 50, 'grp-1', ?, ?)""",
                (ts, ts),
            )
            conn.execute(
                """INSERT INTO layout_shapes (id, revision_id, layer_id, shape_type, label, x, y, width, height, group_id, source_shape_id, created_at, updated_at)
                   VALUES ('shape-conn', 'rev-1', 'layer-src', 'Connector', 'Arrow', 20, 20, 30, 30, 'grp-1', 'shape-rect', ?, ?)""",
                (ts, ts),
            )
        layer_id = "layer-src"

        # 3. Test duplicate_scenario_upload_file media isolation
        src_media = self.upload_dir / "source_photo.png"
        src_media.write_bytes(b"fake-image-bytes")
        rel_media = str(src_media)
        dup_rel = db_core.duplicate_scenario_upload_file(rel_media, "test_clone")
        self.assertNotEqual(dup_rel, rel_media)
        dup_abs = db_core.resolve_upload_path(dup_rel, self.upload_dir)
        self.assertIsNotNone(dup_abs)
        self.assertTrue(dup_abs.exists())
        self.assertEqual(dup_abs.read_bytes(), b"fake-image-bytes")

        # 4. Clone the planning scenario
        cloned_scen_id = project_store.clone_planning_scenario(
            proj_id, scen_id, "Cloned Scenario", "B", 55.0
        )

        cloned_unlinked_q = store.query(
            "SELECT * FROM quality_requirement_assignments WHERE project_id=? AND scenario_id=? AND work_element_id IS NULL",
            (proj_id, cloned_scen_id),
        )
        self.assertEqual(len(cloned_unlinked_q), 1)
        self.assertNotEqual(str(cloned_unlinked_q[0]["id"]), str(q_assign_id))

        cloned_p = pfmea_store.pfmea_entries(proj_id, cloned_scen_id)
        self.assertEqual(len(cloned_p), 1)
        self.assertTrue(bool(cloned_p.iloc[0]["is_unlinked"]))
        self.assertEqual(str(cloned_p.iloc[0]["source_pfmea_entry_id"]), str(pfmea_entry_id))

        scen_layers = pd.DataFrame(
            store.query("SELECT * FROM layout_layers WHERE revision_id='rev-1' AND scenario_id=?", (cloned_scen_id,))
        )
        self.assertEqual(len(scen_layers), 1)
        cloned_layer_id = str(scen_layers.iloc[0]["id"])
        self.assertNotEqual(cloned_layer_id, str(layer_id))
        cloned_shapes = pd.DataFrame(
            store.query("SELECT * FROM layout_shapes WHERE layer_id=?", (cloned_layer_id,))
        )
        self.assertEqual(len(cloned_shapes), 2)
        rect_row = cloned_shapes[cloned_shapes["shape_type"] == "rectangle"].iloc[0]
        conn_row = cloned_shapes[cloned_shapes["shape_type"] == "Connector"].iloc[0]
        self.assertEqual(str(conn_row["source_shape_id"]), str(rect_row["id"]))
        self.assertEqual(str(conn_row["group_id"]), str(rect_row["group_id"]))
        self.assertNotEqual(str(conn_row["group_id"]), "grp-1")

    def test_item6_project_import_control_plan_links_and_fingerprints(self) -> None:
        proj_id = str(store.create_project("Transfer Project", "P2", "L2", 60.0))
        scen_id = str(store.planning_scenarios(proj_id)[0]["id"])
        ts = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas (id, project_id, scenario_id, name, updated_at)
                   VALUES ('area-t', ?, ?, 'Main', ?)""",
                (proj_id, scen_id, ts),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, status, sequence, updated_at)
                   VALUES ('pitch-t', ?, 'area-t', 'P-10', 'Pitch 10', 'Active', 10, ?)""",
                (proj_id, ts),
            )
            conn.execute(
                """INSERT INTO work_elements (id, project_id, scenario_id, sequence, station, operation, description, updated_at)
                   VALUES ('we-t', ?, ?, 10, 'P-10', 'Fasten', 'Fasten part', ?)""",
                (proj_id, scen_id, ts),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements (id, project_id, area_id, pitch_id, description, time_s, sequence, process_element_id, updated_at)
                   VALUES ('ye-t', ?, 'area-t', 'pitch-t', 'Fasten', 15.0, 10, 'we-t', ?)""",
                (proj_id, ts),
            )

        types_df = equipment_store.equipment_types(proj_id)
        type_id = str(types_df.loc[types_df["label"].eq("Torque tool"), "id"].iloc[0])
        equipment_store.save_function_equipment_rows(
            proj_id,
            "Quality",
            scen_id,
            [{"id": "", "name": "DC Nutrunner", "equipment_type_id": type_id, "pitch_id": "pitch-t", "notes": ""}],
            "Tester",
        )
        eq_id = str(equipment_store.equipment_assets(proj_id, scen_id, "Quality").iloc[0]["id"])
        equipment_store.save_equipment_placement(proj_id, scen_id, eq_id, "pitch-t", ["we-t"], "Tester")

        req_id = quality_store.save_quality_requirement(
            proj_id,
            {
                "requirement_type": "Torque",
                "description": "Fastener Torque",
                "unique_identifier": "TQ-200",
                "pass_fail": False,
                "target_value": 30.0,
                "tolerances": "+/- 3",
                "unit": "Nm",
            },
        )
        quality_store.assign_quality_requirement(proj_id, scen_id, "we-t", req_id)
        pfmea_store.save_pfmea_entry_rows(
            proj_id,
            scen_id,
            "we-t",
            pd.DataFrame([{"id": "", "potential_failure_mode": "Fastener loose", "class_code": "P"}]),
        )
        cp_proj_before = control_plan_store.control_plan_projection(proj_id, scen_id)
        self.assertEqual(len(cp_proj_before), 1)
        control_plan_store.save_control_plan_rows(proj_id, scen_id, cp_proj_before)
        cp_before = control_plan_store.control_plan_projection(proj_id, scen_id)
        self.assertEqual(len(cp_before), 1)
        self.assertFalse(bool(cp_before.iloc[0]["source_review_required"]))

        pkg = project_transfer.export_project_package(proj_id, "Tester")
        imported = project_transfer.import_project_package(pkg["data"], "Create new", "Tester")
        new_proj_id = str(imported["project_id"])
        new_scen_id = str(imported["scenario_id"])

        cp_after = control_plan_store.control_plan_projection(new_proj_id, new_scen_id)
        self.assertEqual(len(cp_after), 1)
        self.assertFalse(bool(cp_after.iloc[0]["source_review_required"]))
        with store.connection() as conn:
            new_req_id = str(
                conn.execute("SELECT id FROM quality_requirements WHERE project_id=?", (new_proj_id,)).fetchone()[0]
            )
            cp_snap_req_id = str(
                conn.execute(
                    "SELECT source_quality_requirement_id_snapshot FROM control_plan_items WHERE project_id=?",
                    (new_proj_id,),
                ).fetchone()[0]
            )
        self.assertEqual(cp_snap_req_id, new_req_id)

    def test_item7_recycle_bin_conflict_detection_and_4_option_resolution(self) -> None:
        proj_id = str(store.create_project("Recycle Conflict Project", "P3", "L3", 60.0))

        pfmea_store.add_pfmea_assignee(proj_id, "Alice")
        with store.connection() as conn:
            old_row = dict(
                conn.execute("SELECT * FROM pfmea_assignees WHERE project_id=? AND name='Alice'", (proj_id,)).fetchone()
            )
            with recycle_bin_store.capture_deletion_to_recycle_bin(
                conn,
                project_id=proj_id,
                scenario_id=None,
                entity_type="PFMEA Assignee",
                entity_table="pfmea_assignees",
                entity_id=str(old_row["id"]),
                entity_label="Alice",
                deleted_by="Tester",
            ):
                conn.execute("DELETE FROM pfmea_assignees WHERE id=?", (old_row["id"],))

        pfmea_store.add_pfmea_assignee(proj_id, "Alice")
        bin_df = recycle_bin_store.list_recycle_bin_items(proj_id)
        self.assertEqual(len(bin_df), 1)
        bin_item_id = str(bin_df.iloc[0]["id"])

        conflicts = recycle_bin_store.detect_recycle_bin_restore_conflicts([bin_item_id])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["rename_column"], "name")
        self.assertTrue(conflicts[0]["can_rename"])

        with self.assertRaisesRegex(ValueError, "conflict"):
            recycle_bin_store.restore_recycle_bin_items([bin_item_id])

        res1 = recycle_bin_store.restore_recycle_bin_items(
            [bin_item_id],
            conflict_resolutions={bin_item_id: {"action": "rename_older", "new_name": "Alice (Legacy)"}},
        )
        self.assertEqual(res1["restored_count"], 1)
        names = set(pfmea_store.pfmea_known_responsibilities(proj_id))
        self.assertIn("Alice", names)
        self.assertIn("Alice (Legacy)", names)

        with store.connection() as conn:
            legacy_row = dict(
                conn.execute(
                    "SELECT * FROM pfmea_assignees WHERE project_id=? AND name='Alice (Legacy)'", (proj_id,)
                ).fetchone()
            )
            with recycle_bin_store.capture_deletion_to_recycle_bin(
                conn,
                project_id=proj_id,
                scenario_id=None,
                entity_type="PFMEA Assignee",
                entity_table="pfmea_assignees",
                entity_id=str(legacy_row["id"]),
                entity_label="Alice (Legacy)",
                deleted_by="Tester",
            ):
                conn.execute("DELETE FROM pfmea_assignees WHERE id=?", (legacy_row["id"],))
        pfmea_store.add_pfmea_assignee(proj_id, "Alice (Legacy)")

        bin_df2 = recycle_bin_store.list_recycle_bin_items(proj_id)
        bin_item_id2 = str(bin_df2.iloc[0]["id"])
        res2 = recycle_bin_store.restore_recycle_bin_items(
            [bin_item_id2],
            conflict_resolutions={bin_item_id2: {"action": "rename_newer", "new_name": "Alice (Current)"}},
        )
        self.assertEqual(res2["restored_count"], 1)
        names2 = set(pfmea_store.pfmea_known_responsibilities(proj_id))
        self.assertIn("Alice (Legacy)", names2)
        self.assertIn("Alice (Current)", names2)

        with store.connection() as conn:
            cur_row = dict(
                conn.execute(
                    "SELECT * FROM pfmea_assignees WHERE project_id=? AND name='Alice (Current)'", (proj_id,)
                ).fetchone()
            )
            with recycle_bin_store.capture_deletion_to_recycle_bin(
                conn,
                project_id=proj_id,
                scenario_id=None,
                entity_type="PFMEA Assignee",
                entity_table="pfmea_assignees",
                entity_id=str(cur_row["id"]),
                entity_label="Alice (Current)",
                deleted_by="Tester",
            ):
                conn.execute("DELETE FROM pfmea_assignees WHERE id=?", (cur_row["id"],))
        pfmea_store.add_pfmea_assignee(proj_id, "Alice (Current)")

        bin_df3 = recycle_bin_store.list_recycle_bin_items(proj_id)
        bin_item_id3 = str(bin_df3.iloc[0]["id"])
        res3 = recycle_bin_store.restore_recycle_bin_items(
            [bin_item_id3],
            conflict_resolutions={bin_item_id3: {"action": "replace_newer"}},
        )
        self.assertEqual(res3["restored_count"], 1)
        bin_after_replace = recycle_bin_store.list_recycle_bin_items(proj_id)
        self.assertEqual(len(bin_after_replace), 1)

    def test_item8_paag_completeness_and_validation_gate_option_a(self) -> None:
        proj_id = str(store.create_project("PAAG Gate Project", "P4", "L4", 60.0))
        scen_id = str(store.planning_scenarios(proj_id)[0]["id"])
        ts = store.now_iso()

        sec_id = fishbone_store.add_assembly_section(proj_id, "Main Spine", "Main spine", None, "")
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES ('area-g', ?, ?, ?, 'Main Area', ?)""",
                (proj_id, scen_id, sec_id, ts),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, status, sequence, updated_at)
                   VALUES ('pitch-g', ?, 'area-g', 'ST-010', 'Station 10', 'Active', 10, ?)""",
                (proj_id, ts),
            )
            conn.execute(
                """INSERT INTO work_elements (id, project_id, scenario_id, sequence, station, operation, description, status, updated_at)
                   VALUES ('we-valid', ?, ?, 10, 'ST-010', 'Torque Bolt', 'Validated step', 'Validated', ?),
                          ('we-draft', ?, ?, 20, 'ST-010', 'Draft Op', 'Draft step', 'Draft', ?)""",
                (proj_id, scen_id, ts, proj_id, scen_id, ts),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements (id, project_id, area_id, pitch_id, description, time_s, sequence, process_element_id, updated_at)
                   VALUES ('ye-valid', ?, 'area-g', 'pitch-g', 'Torque Bolt', 12.0, 10, 'we-valid', ?)""",
                (proj_id, ts),
            )

        we_df = pd.DataFrame(
            store.query("SELECT * FROM work_elements WHERE project_id=? AND scenario_id=?", (proj_id, scen_id))
        )
        we_df_bad = we_df.copy()
        we_df_bad.loc[we_df_bad["id"] == "we-draft", "status"] = "Validated"
        with self.assertRaisesRegex(ValueError, "Cannot mark PAAG step"):
            process_store.replace_work_elements(proj_id, scen_id, we_df_bad)

        all_steps = pfmea_store.pfmea_process_steps(proj_id, scen_id)
        val_steps = pfmea_store.pfmea_process_steps(proj_id, scen_id, validated_only=True)
        self.assertEqual(len(all_steps), 2)
        self.assertEqual(len(val_steps), 1)
        self.assertEqual(str(val_steps.iloc[0]["id"]), "we-valid")

        entry_id = pfmea_store.save_pfmea_entry_rows(
            proj_id,
            scen_id,
            "we-valid",
            pd.DataFrame([{"id": "", "potential_failure_mode": "Cross-threaded bolt", "class_code": "S"}]),
        )["created_ids"][0]
        self.assertEqual(pfmea_store.upstream_modified_pfmea_entries(proj_id, scen_id), [])

        with store.connection() as conn:
            conn.execute("UPDATE work_elements SET status='In Progress' WHERE id='we-valid'")
        store.bump_runtime_revision()

        entries_df = pfmea_store.pfmea_entries(proj_id, scen_id)
        self.assertTrue(bool(entries_df.iloc[0]["upstream_changes"]))
        self.assertTrue(bool(entries_df.iloc[0]["paag_incomplete"]))

        mod_list = pfmea_store.upstream_modified_pfmea_entries(proj_id, scen_id)
        self.assertEqual(len(mod_list), 1)
        self.assertTrue(bool(mod_list[0]["paag_incomplete"]))
        self.assertTrue(any("Validated" in r for r in mod_list[0]["paag_missing_reasons"]))

        with self.assertRaisesRegex(ValueError, "Cannot synchronize PFMEA baseline"):
            pfmea_store.review_pfmea_sources(proj_id, scen_id, entry_id)
        with self.assertRaisesRegex(ValueError, "Cannot synchronize PFMEA baseline"):
            pfmea_store.bulk_review_pfmea_sources(proj_id, scen_id, [entry_id])

        with store.connection() as conn:
            conn.execute(
                "UPDATE work_elements SET status='Validated', description='Updated validated desc' WHERE id='we-valid'"
            )
        store.bump_runtime_revision()

        mod_list_valid = pfmea_store.upstream_modified_pfmea_entries(proj_id, scen_id)
        self.assertEqual(len(mod_list_valid), 1)
        self.assertFalse(bool(mod_list_valid[0]["paag_incomplete"]))
        sync_res = pfmea_store.bulk_review_pfmea_sources(proj_id, scen_id, [entry_id], editor_name="QE")
        self.assertEqual(sync_res["row_count"], 1)
        self.assertEqual(pfmea_store.upstream_modified_pfmea_entries(proj_id, scen_id), [])

        quality_store.save_quality_requirement(
            proj_id,
            {
                "requirement_type": "Dimensional",
                "description": "Check gap",
                "unique_identifier": "DIM-10",
                "pass_fail": True,
                "target_value": None,
                "tolerances": "",
                "unit": "",
            },
        )
        pfmea_store.add_pfmea_control_option(proj_id, "Prevention", "Fixture Poka-Yoke")
        cand_df = pfmea_pattern_store.pfmea_pattern_source_candidates(proj_id, "Prevention")
        self.assertTrue((cand_df["source_type"] == "manual_option").all())


if __name__ == "__main__":
    unittest.main()
