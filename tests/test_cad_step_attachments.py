from __future__ import annotations

import io
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from utils import store
from utils.process_pitch_visual import render_pitch_canvas
from utils.project_transfer import export_project_package, import_project_package


class MockUpload:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


class CadStepAttachmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_cad_step_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])
        self.section_id = store.add_assembly_section(
            self.project_id, "Main", "Main spine", None, ""
        )
        self.area_id = str(uuid4())
        self.pitch_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES (?, ?, ?, ?, 'CAD Test Area', ?)""",
                (self.area_id, self.project_id, self.scenario_id, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES (?, ?, ?, '01-CAD-01', 'CAD Workstation', ?)""",
                (self.pitch_id, self.project_id, self.area_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    model_applicability, updated_at)
                   VALUES ('work-cad-1', ?, ?, 10, '01-CAD-01', 'Mount bracket', 'All', ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, description, process_element_id, sequence, updated_at)
                   VALUES ('yam-cad-1', ?, ?, ?, 'Mount bracket', 'work-cad-1', 10, ?)""",
                (self.project_id, self.area_id, self.pitch_id, timestamp),
            )

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_part_cad_step_upload_and_delete(self) -> None:
        parts = store.project_table("parts", self.project_id, "part_number")
        part_id = str(parts.iloc[0]["id"])

        cad_bytes = b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('Sample STEP'),'2;1');\nENDSEC;\nEND-ISO-10303-21;\n"
        mock_file = MockUpload("bracket_assembly.step", cad_bytes)

        saved_path_str = store.add_part_image(
            part_id=part_id,
            uploaded_file=mock_file,
            image_type="3D CAD Model (STEP)",
            caption="Workstation mounting bracket 3D model",
        )
        saved_path = Path(saved_path_str)
        self.assertTrue(saved_path.exists())
        self.assertEqual(saved_path.suffix.lower(), ".step")
        self.assertEqual(saved_path.read_bytes(), cad_bytes)

        # Inspect retrieved records
        views = store.part_images(part_id)
        matching = [v for v in views if v["image_path"] == saved_path_str]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["image_type"], "3D CAD Model (STEP)")
        self.assertEqual(matching[0]["caption"], "Workstation mounting bracket 3D model")

        # Delete view
        img_id = matching[0]["id"]
        store.delete_part_image(img_id)
        self.assertFalse(saved_path.exists())
        views_after = store.part_images(part_id)
        self.assertFalse(any(v["id"] == img_id for v in views_after))

    def test_part_cad_step_size_limit_enforced(self) -> None:
        parts = store.project_table("parts", self.project_id, "part_number")
        part_id = str(parts.iloc[0]["id"])

        # 51 MB dummy bytes
        oversized_bytes = b"0" * (51 * 1024 * 1024)
        mock_file = MockUpload("large_assembly.step", oversized_bytes)

        with self.assertRaises(ValueError) as ctx:
            store.add_part_image(
                part_id=part_id,
                uploaded_file=mock_file,
                image_type="3D CAD Model (STEP)",
                caption="Large Machine Assembly",
            )
        self.assertIn("50 MB", str(ctx.exception))
        self.assertIn("PLM/CAD web link", str(ctx.exception))

    def test_process_visual_media_cad_step_round_trip(self) -> None:
        cad_content = b"ISO-10303-21;\nHEADER;\nFILE_NAME('fixture.stp');\nENDSEC;\nEND-ISO-10303-21;\n"
        saved = store.save_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=self.pitch_id,
            filename="fixture.stp",
            file_bytes=cad_content,
            caption="Fixture 3D CAD Reference",
            tagged_work_element_ids=["work-cad-1"],
            sequence=10,
            current_editor="Tooling Engineer",
        )

        media_id = saved["id"]
        self.assertEqual(saved["media_type"], "cad")
        file_path = Path(saved["file_path"])
        self.assertTrue(file_path.exists())
        self.assertEqual(file_path.read_bytes(), cad_content)

        # Retrieve media
        items = store.get_pitch_visual_media(self.project_id, self.scenario_id, self.pitch_id)
        matching = [m for m in items if m["id"] == media_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["media_type"], "cad")
        self.assertEqual(matching[0]["caption"], "Fixture 3D CAD Reference")

        # Verify slide canvas rendering
        pitch_dict = {"pitch_number": "01-CAD-01", "pitch_name": "CAD Workstation"}
        html = render_pitch_canvas(pitch=pitch_dict, visual_media=items)
        self.assertIn("media-cad-card", html)
        self.assertIn("3D CAD Model (STEP)", html)
        self.assertIn("Fixture 3D CAD Reference", html)

        # Delete visual aid
        store.delete_pitch_visual_media(self.project_id, self.scenario_id, media_id)
        self.assertFalse(file_path.exists())
        remaining = store.get_pitch_visual_media(self.project_id, self.scenario_id, self.pitch_id)
        self.assertFalse(any(m["id"] == media_id for m in remaining))

    def test_process_visual_media_cad_size_limit_enforced(self) -> None:
        oversized_bytes = b"0" * (52 * 1024 * 1024)
        with self.assertRaises(ValueError) as ctx:
            store.save_pitch_visual_media(
                project_id=self.project_id,
                scenario_id=self.scenario_id,
                pitch_id=self.pitch_id,
                filename="huge_cell.step",
                file_bytes=oversized_bytes,
                caption="Full Plant Cell",
            )
        self.assertIn("50 MB", str(ctx.exception))
        self.assertIn("PLM/CAD web link", str(ctx.exception))

    def test_export_import_bundles_and_restores_step_files(self) -> None:
        parts = store.project_table("parts", self.project_id, "part_number")
        part_id = str(parts.iloc[0]["id"])

        part_cad_bytes = b"ISO-10303-21; PART_CAD_SAMPLE; END-ISO-10303-21;"
        store.add_part_image(
            part_id=part_id,
            uploaded_file=MockUpload("part_sample.step", part_cad_bytes),
            image_type="3D CAD Model (STEP)",
            caption="Sample Part STEP",
        )

        pitch_cad_bytes = b"ISO-10303-21; PITCH_CAD_SAMPLE; END-ISO-10303-21;"
        store.save_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=self.pitch_id,
            filename="pitch_sample.stp",
            file_bytes=pitch_cad_bytes,
            caption="Sample Pitch CAD",
        )

        package = export_project_package(self.project_id, "CAD Tester")
        imported = import_project_package(package["data"], "Create new", "CAD Tester")
        imported_proj_id = imported["project_id"]
        imported_scen_id = imported["scenario_id"]

        # Check part STEP was imported and unpacked
        imp_parts = store.project_table("parts", imported_proj_id, "part_number")
        imp_part_id = str(imp_parts.iloc[0]["id"])
        imp_views = store.part_images(imp_part_id)
        self.assertEqual(len(imp_views), 1)
        imp_step_path = Path(imp_views[0]["image_path"])
        self.assertTrue(imp_step_path.exists())
        self.assertEqual(imp_step_path.read_bytes(), part_cad_bytes)

        # Check pitch visual aid was imported and unpacked
        imp_pitches = store.yamazumi_pitches_for_scenario(imported_proj_id, imported_scen_id)
        imp_pitch_id = str(imp_pitches.iloc[0]["id"])
        imp_media = store.get_pitch_visual_media(imported_proj_id, imported_scen_id, imp_pitch_id)
        self.assertEqual(len(imp_media), 1)
        self.assertEqual(imp_media[0]["media_type"], "cad")
        imp_media_file = Path(imp_media[0]["file_path"])
        self.assertTrue(imp_media_file.exists())
        self.assertEqual(imp_media_file.read_bytes(), pitch_cad_bytes)


if __name__ == "__main__":
    unittest.main()
