from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from utils import store


class ProjectManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.db_path = self.tmp_path / f"test_proj_{uuid4()}.db"
        self.upload_dir = self.tmp_path / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)

        self.db_patch = patch.object(store, "DB_PATH", self.db_path)
        self.upload_patch = patch.object(store, "UPLOAD_DIR", self.upload_dir)
        self.db_patch.start()
        self.upload_patch.start()
        store.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.upload_patch.stop()
        self.tmp_dir.cleanup()

    def test_create_and_update_project_with_building_location(self) -> None:
        proj_id = store.create_project(
            name="Alpha Project",
            program="Appliance",
            owner="IE Lead",
            takt_time_s=45.0,
            product_line="Line 1",
            building_location="Building 2, AP1",
        )
        proj = store.get_project(proj_id)
        self.assertIsNotNone(proj)
        self.assertEqual(proj["name"], "Alpha Project")
        self.assertEqual(proj["building_location"], "Building 2, AP1")
        self.assertEqual(proj["product_line"], "Line 1")

        # Update building location
        store.update_project(
            proj_id,
            {
                "name": "Alpha Project Updated",
                "program": "Appliance",
                "product_line": "Line 2",
                "building_location": "Plant 4",
                "owner": "IE Lead",
                "revision": "B",
                "status": "Working",
                "takt_time_s": 50.0,
                "takt_time_unit": "seconds",
                "notes": "Relocated to Plant 4",
            },
        )
        updated_proj = store.get_project(proj_id)
        self.assertEqual(updated_proj["name"], "Alpha Project Updated")
        self.assertEqual(updated_proj["building_location"], "Plant 4")
        self.assertEqual(updated_proj["product_line"], "Line 2")
        self.assertEqual(updated_proj["revision"], "B")

    def test_get_project_deletion_impact_counts_accurately(self) -> None:
        proj_id = store.create_project(
            name="Beta Project",
            program="Appliance",
            owner="IE",
            takt_time_s=60.0,
            building_location="Bldg 5",
        )
        scenario_id = str(uuid4())
        now = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO planning_scenarios (id, project_id, name, revision_label, revision_sequence, created_at, updated_at)
                   VALUES (?, ?, 'Base', 'A', 1, ?, ?)""",
                (scenario_id, proj_id, now, now),
            )
            conn.execute(
                """INSERT INTO parts (id, project_id, part_number, description, quantity, revision, source, updated_at)
                   VALUES (?, ?, 'PN-100', 'Bracket', 2, 'A', 'Manual', ?)""",
                (str(uuid4()), proj_id, now),
            )
            conn.execute(
                """INSERT INTO assembly_sections (id, project_id, name, section_type, sequence, created_at, updated_at)
                   VALUES (?, ?, 'Main Line', 'Main spine', 10, ?, ?)""",
                (str(uuid4()), proj_id, now, now),
            )
            area_id = str(uuid4())
            conn.execute(
                """INSERT INTO yamazumi_areas (id, project_id, scenario_id, name, updated_at)
                   VALUES (?, ?, ?, 'Area 1', ?)""",
                (area_id, proj_id, scenario_id, now),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, updated_at)
                   VALUES (?, ?, ?, '01-01', ?)""",
                (str(uuid4()), proj_id, area_id, now),
            )
            conn.execute(
                """INSERT INTO work_elements (id, project_id, scenario_id, sequence, operation, cycle_time_s, updated_at)
                   VALUES (?, ?, ?, 1, 'Fasten screw', 12.0, ?)""",
                (str(uuid4()), proj_id, scenario_id, now),
            )

        impact = store.get_project_deletion_impact(proj_id)
        self.assertEqual(impact.get("scenarios"), 1)
        self.assertEqual(impact.get("parts"), 1)
        self.assertEqual(impact.get("sections"), 1)
        self.assertEqual(impact.get("pitches"), 1)
        self.assertEqual(impact.get("work_elements"), 1)

    def test_delete_project_cascades_database_and_unlinks_uploads(self) -> None:
        proj_id = store.create_project(
            name="Gamma Project",
            program="Appliance",
            owner="IE",
            takt_time_s=60.0,
            building_location="Bldg 9",
        )
        scenario_id = str(uuid4())
        part_id = str(uuid4())
        now = store.now_iso()

        # Create a mock upload file
        mock_upload_file = self.upload_dir / f"test_img_{uuid4()}.png"
        mock_upload_file.write_bytes(b"dummy image data")
        self.assertTrue(mock_upload_file.exists())

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO planning_scenarios (id, project_id, name, revision_label, revision_sequence, created_at, updated_at)
                   VALUES (?, ?, 'Base', 'A', 1, ?, ?)""",
                (scenario_id, proj_id, now, now),
            )
            conn.execute(
                """INSERT INTO parts (id, project_id, part_number, description, quantity, revision, source, image_path, updated_at)
                   VALUES (?, ?, 'PN-999', 'Housing', 1, 'A', 'Manual', ?, ?)""",
                (part_id, proj_id, str(mock_upload_file), now),
            )
            conn.execute(
                """INSERT INTO part_images (id, part_id, image_path, image_type, caption, created_at)
                   VALUES (?, ?, ?, 'Supplemental', '', ?)""",
                (str(uuid4()), part_id, str(mock_upload_file), now),
            )
            conn.execute(
                """INSERT INTO work_elements (id, project_id, scenario_id, sequence, operation, cycle_time_s, updated_at)
                   VALUES (?, ?, ?, 1, 'Assemble part', 15.0, ?)""",
                (str(uuid4()), proj_id, scenario_id, now),
            )

        # Deletion
        result = store.delete_project(proj_id, editor_name="Test Editor")
        self.assertEqual(result["project_id"], proj_id)
        self.assertEqual(result["project_name"], "Gamma Project")
        self.assertGreater(result["deleted_files_count"], 0)

        # Check project is deleted
        self.assertIsNone(store.get_project(proj_id))

        # Check cascaded tables have no records for proj_id
        with store.connection() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM planning_scenarios WHERE project_id=?", (proj_id,)).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM parts WHERE project_id=?", (proj_id,)).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM work_elements WHERE project_id=?", (proj_id,)).fetchone()[0],
                0,
            )

        # Check upload file on disk was unlinked
        self.assertFalse(mock_upload_file.exists())

    def test_delete_nonexistent_project_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as cm:
            store.delete_project("non-existent-uuid")
        self.assertIn("no longer exists", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
