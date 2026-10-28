from __future__ import annotations

import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from utils import store
from utils.project_transfer import (
    PACKAGE_VERSION,
    PROJECT_TRANSFER_TABLES,
    export_project_package,
    import_project_package,
    preview_project_package,
)


class ProjectTransferRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.orig_db_path = store.DB_PATH
        self.orig_upload_dir = store.UPLOAD_DIR

        store.DB_PATH = self.tmp_path / "transfer_test.db"
        store.UPLOAD_DIR = self.tmp_path / "uploads"
        store.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        store.init_db()

        self.project_id = str(uuid4())
        self.scenario_id = str(uuid4())
        self.now = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects (id, name, program, product_line, created_at, updated_at)
                   VALUES (?, 'Transfer Test Project', 'Prog', 'Line', ?, ?)""",
                (self.project_id, self.now, self.now),
            )
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, created_at, updated_at)
                   VALUES (?, ?, 'Base Scenario', 'Rev 1', 1, ?, ?)""",
                (self.scenario_id, self.project_id, self.now, self.now),
            )

    def tearDown(self) -> None:
        store.DB_PATH = self.orig_db_path
        store.UPLOAD_DIR = self.orig_upload_dir
        self.tmp_dir.cleanup()

    def test_all_database_tables_are_registered(self) -> None:
        with store.connection() as conn:
            existing = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
        registered = {item.name for item in PROJECT_TRANSFER_TABLES}
        unregistered = existing - registered - {"recycle_bin_items", "app_feedback"}
        self.assertEqual(
            unregistered,
            set(),
            f"All active tables must be in PROJECT_TRANSFER_TABLES. Missing: {sorted(unregistered)}",
        )

    def test_export_and_import_round_trip_for_newly_registered_tables(self) -> None:
        # Create supporting records: section, pitch, work element, equipment asset, quality req, prevention option
        section_id = str(uuid4())
        area_id = str(uuid4())
        pitch_id = str(uuid4())
        element_id = str(uuid4())
        equipment_id = str(uuid4())
        quality_id = str(uuid4())
        prevention_opt_id = str(uuid4())
        detection_opt_id = str(uuid4())

        # Create a mock upload file
        mock_image = store.UPLOAD_DIR / f"test_layout_{uuid4()}.png"
        mock_image.write_bytes(b"\x89PNG\r\n\x1a\nfake image data")

        mock_media = store.UPLOAD_DIR / f"test_media_{uuid4()}.png"
        mock_media.write_bytes(b"\x89PNG\r\n\x1a\nfake media data")

        layout_plan_id = str(uuid4())
        layout_rev_id = str(uuid4())
        standard_id = str(uuid4())
        shape_id = str(uuid4())
        media_id = str(uuid4())
        media_tag_id = str(uuid4())
        safety_id = str(uuid4())
        assignee_id = str(uuid4())
        pattern_id = str(uuid4())
        pattern_effect_id = str(uuid4())
        pattern_cause_id = str(uuid4())
        pattern_action_id = str(uuid4())
        pattern_prev_id = str(uuid4())
        pattern_det_id = str(uuid4())

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO assembly_sections (id, project_id, name, sequence, created_at, updated_at)
                   VALUES (?, ?, 'Main Section', 1, ?, ?)""",
                (section_id, self.project_id, self.now, self.now),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas (id, project_id, scenario_id, name, updated_at)
                   VALUES (?, ?, ?, 'Area 1', ?)""",
                (area_id, self.project_id, self.scenario_id, self.now),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, sequence, updated_at)
                   VALUES (?, ?, ?, 'P-01', 'Pitch 1', 1, ?)""",
                (pitch_id, self.project_id, area_id, self.now),
            )
            conn.execute(
                """INSERT INTO work_elements (id, project_id, scenario_id, sequence, operation, updated_at, resource_type, resource_detail)
                   VALUES (?, ?, ?, 1, 'Op 1', ?, 'Manual', '')""",
                (element_id, self.project_id, self.scenario_id, self.now),
            )
            eq_type_id = str(uuid4())
            conn.execute(
                """INSERT INTO equipment_types (id, project_id, label, created_at, updated_at)
                   VALUES (?, ?, 'Robot Type', ?, ?)""",
                (eq_type_id, self.project_id, self.now, self.now),
            )
            conn.execute(
                """INSERT INTO equipment_assets (id, project_id, equipment_type_id, name, description, manufacturer, model, notes, image_path, created_at, updated_at)
                   VALUES (?, ?, ?, 'EQ-01', 'Desc', 'Mfr', 'Mdl', 'Notes', '', ?, ?)""",
                (equipment_id, self.project_id, eq_type_id, self.now, self.now),
            )
            conn.execute(
                """INSERT INTO quality_requirements (id, project_id, requirement_type, description, unique_identifier, pass_fail, tolerances, unit, created_at, updated_at)
                   VALUES (?, ?, 'Torque', 'Torque spec', 'Q-01', 0, '10', 'Nm', ?, ?)""",
                (quality_id, self.project_id, self.now, self.now),
            )
            conn.execute(
                """INSERT INTO pfmea_prevention_options (id, project_id, label, active, created_at, updated_at)
                   VALUES (?, ?, 'Poka-yoke', 1, ?, ?)""",
                (prevention_opt_id, self.project_id, self.now, self.now),
            )
            conn.execute(
                """INSERT INTO pfmea_detection_options (id, project_id, label, active, created_at, updated_at)
                   VALUES (?, ?, 'Visual check', 1, ?, ?)""",
                (detection_opt_id, self.project_id, self.now, self.now),
            )

            # Insert into the newly registered tables:
            # 1. layout_plans
            conn.execute(
                """INSERT INTO layout_plans (id, project_id, name, description, created_at, updated_at)
                   VALUES (?, ?, 'Plant Layout', 'Floor 1', ?, ?)""",
                (layout_plan_id, self.project_id, self.now, self.now),
            )
            # 2. layout_revisions
            conn.execute(
                """INSERT INTO layout_revisions (id, layout_id, revision_number, image_path, created_at)
                   VALUES (?, ?, 1, ?, ?)""",
                (layout_rev_id, layout_plan_id, str(mock_image), self.now),
            )
            # 3. layout_section_pitch_standards
            conn.execute(
                """INSERT INTO layout_section_pitch_standards (id, layout_id, section_id, pitch_width, pitch_height, unit, created_at, updated_at)
                   VALUES (?, ?, ?, 4.0, 2.0, 'feet', ?, ?)""",
                (standard_id, layout_plan_id, section_id, self.now, self.now),
            )
            # 4. layout_shapes
            conn.execute(
                """INSERT INTO layout_shapes (id, revision_id, shape_type, label, x, y, width, height, pitch_id, equipment_id, created_at, updated_at)
                   VALUES (?, ?, 'rectangle', 'Shape 1', 10.0, 20.0, 50.0, 50.0, ?, ?, ?, ?)""",
                (shape_id, layout_rev_id, pitch_id, equipment_id, self.now, self.now),
            )
            # 5. process_visual_media
            conn.execute(
                """INSERT INTO process_visual_media (id, project_id, scenario_id, pitch_id, media_type, file_path, original_file_path, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'image', ?, '', ?, ?)""",
                (media_id, self.project_id, self.scenario_id, pitch_id, str(mock_media), self.now, self.now),
            )
            # 6. process_visual_media_tags
            conn.execute(
                """INSERT INTO process_visual_media_tags (id, media_id, work_element_id, project_id, scenario_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (media_tag_id, media_id, element_id, self.project_id, self.scenario_id, self.now),
            )
            # 7. safety_requirements
            conn.execute(
                """INSERT INTO safety_requirements (id, project_id, scenario_id, work_element_id, requirement_description, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'Wear safety glasses', ?, ?)""",
                (safety_id, self.project_id, self.scenario_id, element_id, self.now, self.now),
            )
            # 8. pfmea_assignees
            conn.execute(
                "INSERT INTO pfmea_assignees (id, project_id, name, created_at, updated_at) VALUES (?, ?, 'John Doe', ?, ?)",
                (assignee_id, self.project_id, self.now, self.now),
            )
            # 9. pfmea_patterns
            conn.execute(
                """INSERT INTO pfmea_patterns (id, project_id, label, potential_failure_mode, class_code, created_at, updated_at)
                   VALUES (?, ?, 'Pattern 1', 'Part missing', 'CC', ?, ?)""",
                (pattern_id, self.project_id, self.now, self.now),
            )
            # 10. pfmea_pattern_effects
            conn.execute(
                """INSERT INTO pfmea_pattern_effects (id, pattern_id, effect_description, sequence, created_at, updated_at)
                   VALUES (?, ?, 'Assembly stops', 1, ?, ?)""",
                (pattern_effect_id, pattern_id, self.now, self.now),
            )
            # 11. pfmea_pattern_causes
            conn.execute(
                """INSERT INTO pfmea_pattern_causes (id, pattern_id, cause_description, sequence, created_at, updated_at)
                   VALUES (?, ?, 'Operator error', 1, ?, ?)""",
                (pattern_cause_id, pattern_id, self.now, self.now),
            )
            # 12. pfmea_pattern_actions
            conn.execute(
                """INSERT INTO pfmea_pattern_actions (id, pattern_id, pattern_cause_id, recommended_action, sequence, created_at, updated_at)
                   VALUES (?, ?, ?, 'Add sensor', 1, ?, ?)""",
                (pattern_action_id, pattern_id, pattern_cause_id, self.now, self.now),
            )
            # 13. pfmea_pattern_prevention_sources
            conn.execute(
                """INSERT INTO pfmea_pattern_prevention_sources (id, pattern_id, pattern_cause_id, source_type, prevention_option_id, sequence, created_at, updated_at)
                   VALUES (?, ?, ?, 'manual_option', ?, 1, ?, ?)""",
                (pattern_prev_id, pattern_id, pattern_cause_id, prevention_opt_id, self.now, self.now),
            )
            # 14. pfmea_pattern_detection_sources
            conn.execute(
                """INSERT INTO pfmea_pattern_detection_sources (id, pattern_id, pattern_cause_id, source_type, detection_option_id, sequence, created_at, updated_at)
                   VALUES (?, ?, ?, 'manual_option', ?, 1, ?, ?)""",
                (pattern_det_id, pattern_id, pattern_cause_id, detection_opt_id, self.now, self.now),
            )

        # Export package
        package = export_project_package(self.project_id, "Test User")
        self.assertTrue(package["file_name"].endswith(".paagproject"))

        # Preview package
        preview = preview_project_package(package["data"])
        self.assertEqual(preview["manifest"]["package_version"], PACKAGE_VERSION)
        counts = preview["record_counts"]
        self.assertEqual(counts["layout_plans"], 1)
        self.assertEqual(counts["layout_revisions"], 1)
        self.assertEqual(counts["layout_section_pitch_standards"], 1)
        self.assertEqual(counts["layout_shapes"], 1)
        self.assertEqual(counts["process_visual_media"], 1)
        self.assertEqual(counts["process_visual_media_tags"], 1)
        self.assertEqual(counts["safety_requirements"], 1)
        self.assertEqual(counts["pfmea_assignees"], 1)
        self.assertEqual(counts["pfmea_patterns"], 1)
        self.assertEqual(counts["pfmea_pattern_effects"], 1)
        self.assertEqual(counts["pfmea_pattern_causes"], 1)
        self.assertEqual(counts["pfmea_pattern_actions"], 1)
        self.assertEqual(counts["pfmea_pattern_prevention_sources"], 1)
        self.assertEqual(counts["pfmea_pattern_detection_sources"], 1)

        # Import package as Create new
        res = import_project_package(package["data"], "Create new", "Test User")
        new_project_id = res["project_id"]
        self.assertNotEqual(new_project_id, self.project_id)

        # Verify database integrity and remapping
        with store.connection() as conn:
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(violations, [], f"Foreign key check failed: {violations}")

            # Check new section ID and that layout_section_pitch_standards.section_id remapped to it
            new_section = conn.execute(
                "SELECT id FROM assembly_sections WHERE project_id=?", (new_project_id,)
            ).fetchone()
            self.assertIsNotNone(new_section)
            new_standard = conn.execute(
                """SELECT s.section_id FROM layout_section_pitch_standards s
                   JOIN layout_plans p ON s.layout_id=p.id WHERE p.project_id=?""",
                (new_project_id,),
            ).fetchone()
            self.assertIsNotNone(new_standard)
            self.assertEqual(new_standard["section_id"], new_section["id"])

            # Check layout shapes remapped revision_id, pitch_id, equipment_id
            new_pitch = conn.execute(
                "SELECT id FROM yamazumi_pitches WHERE project_id=?", (new_project_id,)
            ).fetchone()
            new_equip = conn.execute(
                "SELECT id FROM equipment_assets WHERE project_id=?", (new_project_id,)
            ).fetchone()
            new_shape = conn.execute(
                """SELECT s.* FROM layout_shapes s
                   JOIN layout_revisions r ON s.revision_id=r.id
                   JOIN layout_plans p ON r.layout_id=p.id WHERE p.project_id=?""",
                (new_project_id,),
            ).fetchone()
            self.assertIsNotNone(new_shape)
            self.assertEqual(new_shape["pitch_id"], new_pitch["id"])
            self.assertEqual(new_shape["equipment_id"], new_equip["id"])

            # Check media files were remapped and unpacked
            new_revision = conn.execute(
                """SELECT r.image_path FROM layout_revisions r
                   JOIN layout_plans p ON r.layout_id=p.id WHERE p.project_id=?""",
                (new_project_id,),
            ).fetchone()
            self.assertTrue(Path(new_revision["image_path"]).is_file())
            self.assertNotEqual(new_revision["image_path"], str(mock_image))

            new_media_row = conn.execute(
                "SELECT file_path FROM process_visual_media WHERE project_id=?", (new_project_id,)
            ).fetchone()
            self.assertTrue(Path(new_media_row["file_path"]).is_file())
            self.assertNotEqual(new_media_row["file_path"], str(mock_media))

    def test_preview_and_import_backwards_compatibility(self) -> None:
        # Create an archive matching older format where newly registered tables were absent
        package = export_project_package(self.project_id, "Test User")
        with ZipFile(BytesIO(package["data"])) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            records = json.loads(archive.read("records.json"))

        # Strip out the 14 new tables from records and manifest
        new_tables = {
            "layout_plans", "layout_revisions", "layout_section_pitch_standards", "layout_shapes",
            "process_visual_media", "process_visual_media_tags", "safety_requirements",
            "pfmea_assignees", "pfmea_patterns", "pfmea_pattern_effects", "pfmea_pattern_causes",
            "pfmea_pattern_actions", "pfmea_pattern_prevention_sources", "pfmea_pattern_detection_sources",
        }
        for table in new_tables:
            records.pop(table, None)
            manifest["record_counts"].pop(table, None)

        legacy_buffer = BytesIO()
        with ZipFile(legacy_buffer, "w") as legacy_zip:
            legacy_zip.writestr("manifest.json", json.dumps(manifest))
            legacy_zip.writestr("records.json", json.dumps(records))

        legacy_data = legacy_buffer.getvalue()

        # Preview should succeed with defaulted empty lists rather than raising registry error
        preview = preview_project_package(legacy_data)
        self.assertEqual(preview["manifest"]["package_version"], PACKAGE_VERSION)

        # Import should succeed and create a valid project
        res = import_project_package(legacy_data, "Create new", "Test User")
        self.assertTrue(res["project_id"])
        with store.connection() as conn:
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(violations, [])

    def test_preview_and_import_with_extra_and_defaulted_columns(self) -> None:
        # Create records with table_view_preferences having extra columns and equipment_types missing a defaulted column
        pref_id = str(uuid4())
        eq_type_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO table_view_preferences
                   (id, project_id, editor_name, view_key, visible_columns_json, column_order_json, created_at, updated_at)
                   VALUES (?, ?, 'Nicole Ervin', 'parts_catalog', '["part_number"]', '["part_number"]', ?, ?)""",
                (pref_id, self.project_id, self.now, self.now),
            )
            conn.execute(
                """INSERT INTO equipment_types
                   (id, project_id, label, tier, created_at, updated_at)
                   VALUES (?, ?, 'Drill', 'Handheld Tools', ?, ?)""",
                (eq_type_id, self.project_id, self.now, self.now),
            )

        package = export_project_package(self.project_id, "Test User")
        with ZipFile(BytesIO(package["data"])) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            records = json.loads(archive.read("records.json"))

        # Add extra unrecognized columns to table_view_preferences
        for row in records.get("table_view_preferences", []):
            row["view_name"] = "Default"
            row["is_default"] = 0

        # Remove defaulted column 'tier' from equipment_types
        for row in records.get("equipment_types", []):
            row.pop("tier", None)

        modified_buffer = BytesIO()
        with ZipFile(modified_buffer, "w") as mod_zip:
            mod_zip.writestr("manifest.json", json.dumps(manifest))
            mod_zip.writestr("records.json", json.dumps(records))

        modified_data = modified_buffer.getvalue()

        # Preview should succeed despite extra and omitted-default columns
        preview = preview_project_package(modified_data)
        self.assertEqual(preview["record_counts"]["table_view_preferences"], 1)

        # Import should succeed and prune extra columns
        res = import_project_package(modified_data, "Create new", "Test User")
        new_project_id = res["project_id"]
        self.assertTrue(new_project_id)
        with store.connection() as conn:
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(violations, [])

            # Verify table_view_preferences record exists
            imported_prefs = conn.execute(
                "SELECT * FROM table_view_preferences WHERE project_id=?", (new_project_id,)
            ).fetchall()
            self.assertEqual(len(imported_prefs), 1)
            self.assertEqual(imported_prefs[0]["view_key"], "parts_catalog")

            # Verify equipment_types has default tier applied
            imported_eq = conn.execute(
                "SELECT tier FROM equipment_types WHERE project_id=?", (new_project_id,)
            ).fetchone()
            self.assertEqual(imported_eq["tier"], "Handheld Tools")

    def test_preview_rejects_missing_required_columns(self) -> None:
        part_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO parts (id, project_id, part_number, description, updated_at)
                   VALUES (?, ?, 'PN-100', 'Part 100', ?)""",
                (part_id, self.project_id, self.now),
            )

        package = export_project_package(self.project_id, "Test User")
        with ZipFile(BytesIO(package["data"])) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            records = json.loads(archive.read("records.json"))

        # Remove required column 'part_number' from parts
        for row in records.get("parts", []):
            row.pop("part_number", None)

        bad_buffer = BytesIO()
        with ZipFile(bad_buffer, "w") as bad_zip:
            bad_zip.writestr("manifest.json", json.dumps(manifest))
            bad_zip.writestr("records.json", json.dumps(records))

        with self.assertRaises(ValueError) as ctx:
            preview_project_package(bad_buffer.getvalue())
        self.assertIn("missing required column(s) part_number", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
