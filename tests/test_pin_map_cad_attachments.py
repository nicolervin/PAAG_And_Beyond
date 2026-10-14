"""Unit tests for native AutoCAD (.dwg / .dxf) drawing attachments, 100 MB limits, and CAD web links in Pin Map layouts."""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from PIL import Image

from utils import store
from utils.layout_store import (
    MAX_LAYOUT_CAD_FILE_SIZE_BYTES,
    SUPPORTED_LAYOUT_CAD_EXTENSIONS,
    attach_layout_revision_cad,
    create_layout,
    create_layout_revision,
    delete_layout_revision,
    get_layout_revision,
    get_pitch_layout_footprints,
    layout_deletion_impact,
    remove_layout_revision_cad,
    save_layout_shapes,
)


def _create_test_image(format: str = "PNG") -> io.BytesIO:
    buf = io.BytesIO()
    img = Image.new("RGB", (100, 50), color="blue")
    img.save(buf, format=format)
    buf.seek(0)
    buf.name = f"floorplan.{format.lower()}"
    return buf


def _create_mock_cad_file(filename: str = "plant_floorplan.dwg", size_bytes: int = 256) -> io.BytesIO:
    buf = io.BytesIO(b"MOCK_DWG_BINARY_HEADER" + b"\x00" * max(0, size_bytes - 22))
    buf.seek(0)
    buf.name = filename
    return buf


class PinMapCadAttachmentsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_pin_map_cad_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.editor = "CAD Test Engineer"
        self.created_uploads: list[Path] = []

    def tearDown(self) -> None:
        self.database_patch.stop()
        for p in self.created_uploads:
            if p.exists():
                p.unlink(missing_ok=True)
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def _track_upload(self, path_str: str) -> None:
        if path_str:
            p = Path(path_str)
            if p not in self.created_uploads:
                self.created_uploads.append(p)

    def test_create_revision_with_dwg_attachment(self) -> None:
        """Creating a layout revision with a .dwg AutoCAD file stores and exposes CAD metadata."""
        layout = create_layout(self.project_id, "Assembly Bay CAD", "Test Bay", self.editor)
        dwg_file = _create_mock_cad_file("Assembly_Bay_RevA.dwg", size_bytes=1024)

        rev = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout["id"],
            image_file=_create_test_image(),
            width_value=120.0,
            height_value=60.0,
            unit="feet",
            notes="Initial layout revision with native DWG",
            editor_name=self.editor,
            cad_file=dwg_file,
            cad_web_url="https://vault.autodesk.com/plant/dwg/123",
        )
        self._track_upload(rev["image_path"])
        self._track_upload(rev["cad_file_path"])

        self.assertTrue(rev["cad_file_path"])
        self.assertEqual(rev["cad_file_name"], "Assembly_Bay_RevA.dwg")
        self.assertEqual(rev["cad_file_size_bytes"], 1024)
        self.assertEqual(rev["cad_web_url"], "https://vault.autodesk.com/plant/dwg/123")

        # Verify disk persistence
        cad_path = Path(rev["cad_file_path"])
        self.assertTrue(cad_path.exists())
        self.assertTrue(cad_path.name.endswith(".dwg"))

        # Verify get_layout_revision returns identical CAD attributes
        fetched = get_layout_revision(rev["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["cad_file_name"], "Assembly_Bay_RevA.dwg")
        self.assertEqual(fetched["cad_file_size_bytes"], 1024)
        self.assertEqual(fetched["cad_web_url"], "https://vault.autodesk.com/plant/dwg/123")

        # Verify audit history
        audit = store.audit_history(self.project_id, table_name="Layouts", limit=5)
        self.assertFalse(audit.empty)
        latest_audit = audit.iloc[0]
        self.assertEqual(latest_audit["action"], "Create layout revision")

    def test_cad_size_limit_enforcement(self) -> None:
        """Uploading a CAD file exceeding the 100 MB limit raises a ValueError."""
        layout = create_layout(self.project_id, "Heavy Plant", "Oversized test", self.editor)
        oversized = _create_mock_cad_file("giant_facility.dwg", size_bytes=MAX_LAYOUT_CAD_FILE_SIZE_BYTES + 1024)

        with self.assertRaises(ValueError) as ctx:
            create_layout_revision(
                project_id=self.project_id,
                layout_id=layout["id"],
                image_file=_create_test_image(),
                width_value=200.0,
                height_value=100.0,
                unit="feet",
                notes=None,
                editor_name=self.editor,
                cad_file=oversized,
            )
        self.assertIn("100 MB", str(ctx.exception))
        self.assertIn("CAD Web Link", str(ctx.exception))

    def test_cad_file_format_validation(self) -> None:
        """Uploading unsupported file formats as CAD raises a ValueError."""
        layout = create_layout(self.project_id, "Format Test Layout", "Format test", self.editor)
        invalid_file = io.BytesIO(b"fake executable")
        invalid_file.name = "malicious.exe"

        with self.assertRaises(ValueError) as ctx:
            create_layout_revision(
                project_id=self.project_id,
                layout_id=layout["id"],
                image_file=_create_test_image(),
                width_value=100.0,
                height_value=50.0,
                unit="feet",
                notes=None,
                editor_name=self.editor,
                cad_file=invalid_file,
            )
        self.assertIn("Unsupported AutoCAD drawing format", str(ctx.exception))

    def test_dxf_primary_drawing_auto_preserves_cad(self) -> None:
        """When an architectural DXF is uploaded as the primary drawing, its bytes are auto-preserved as cad_file_path."""
        import ezdxf

        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        msp.add_line((0, 0), (100, 50))
        dxf_buf = io.StringIO()
        doc.write(stream=dxf_buf)
        dxf_bytes = io.BytesIO(dxf_buf.getvalue().encode("utf-8"))
        dxf_bytes.name = "plant_floorplan_v1.dxf"

        layout = create_layout(self.project_id, "DXF Auto Layout", "DXF auto preservation", self.editor)
        rev = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout["id"],
            image_file=dxf_bytes,
            width_value=150.0,
            height_value=75.0,
            unit="feet",
            notes="Uploaded native DXF directly",
            editor_name=self.editor,
        )
        self._track_upload(rev["image_path"])
        self._track_upload(rev["cad_file_path"])

        self.assertTrue(rev["cad_file_path"])
        self.assertEqual(rev["cad_file_name"], "plant_floorplan_v1.dxf")
        self.assertGreater(rev["cad_file_size_bytes"], 0)
        cad_path = Path(rev["cad_file_path"])
        self.assertTrue(cad_path.exists())
        self.assertTrue(cad_path.name.endswith(".dxf"))

    def test_attach_and_remove_cad_from_existing_revision(self) -> None:
        """Collaborators can attach a DWG or CAD link to an existing revision, or remove it."""
        layout = create_layout(self.project_id, "Retrofit Layout", "Retrofit test", self.editor)
        rev = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout["id"],
            image_file=_create_test_image(),
            width_value=80.0,
            height_value=40.0,
            unit="feet",
            notes="Revision without CAD originally",
            editor_name=self.editor,
        )
        self._track_upload(rev["image_path"])
        self.assertEqual(rev.get("cad_file_path"), "")

        # Attach DWG and Vault link
        dwg_file = _create_mock_cad_file("Retrofit_Line_4.dwg", size_bytes=512)
        updated = attach_layout_revision_cad(
            project_id=self.project_id,
            revision_id=rev["id"],
            cad_file=dwg_file,
            cad_web_url="https://company.sharepoint.com/:u:/r/cad/line4.dwg",
            editor_name=self.editor,
        )
        self._track_upload(updated["cad_file_path"])
        self.assertEqual(updated["cad_file_name"], "Retrofit_Line_4.dwg")
        self.assertEqual(updated["cad_file_size_bytes"], 512)
        self.assertEqual(updated["cad_web_url"], "https://company.sharepoint.com/:u:/r/cad/line4.dwg")
        cad_path = Path(updated["cad_file_path"])
        self.assertTrue(cad_path.exists())

        # Detach CAD
        detached = remove_layout_revision_cad(
            project_id=self.project_id,
            revision_id=rev["id"],
            editor_name=self.editor,
        )
        self.assertEqual(detached["cad_file_path"], "")
        self.assertEqual(detached["cad_file_name"], "")
        self.assertEqual(detached["cad_file_size_bytes"], 0)
        self.assertEqual(detached["cad_web_url"], "")
        self.assertFalse(cad_path.exists())

    def test_delete_revision_cleans_up_cad_file(self) -> None:
        """Deleting a revision unlinks both the rasterized floor plan image and the native CAD drawing."""
        layout = create_layout(self.project_id, "Temp Layout", "Temporary layout", self.editor)
        dwg_file = _create_mock_cad_file("Temp_Drawing.dwg", size_bytes=256)
        rev = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout["id"],
            image_file=_create_test_image(),
            width_value=50.0,
            height_value=25.0,
            unit="feet",
            notes=None,
            editor_name=self.editor,
            cad_file=dwg_file,
        )
        img_path = Path(rev["image_path"])
        cad_path = Path(rev["cad_file_path"])
        self.assertTrue(img_path.exists())
        self.assertTrue(cad_path.exists())

        # Check deletion impact includes CAD file
        impact = layout_deletion_impact(self.project_id, layout["id"])
        self.assertIn(str(cad_path), impact["image_paths"])

        delete_layout_revision(self.project_id, rev["id"], self.editor)
        self.assertFalse(img_path.exists())
        self.assertFalse(cad_path.exists())

    def test_footprints_include_cad_metadata_for_pin_map(self) -> None:
        """get_pitch_layout_footprints returns CAD columns for the Pin Map 2D Plant Spatial Map."""
        scenario_id = str(store.query("SELECT id FROM planning_scenarios WHERE project_id=? LIMIT 1", (self.project_id,))[0]["id"])
        area_id = str(uuid4())
        pitch_id = str(uuid4())
        ts = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES (?, ?, ?, 'Sub-Assembly Area', ?)""",
                (area_id, self.project_id, scenario_id, ts),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status, sequence, pitch_type, updated_at)
                   VALUES (?, ?, ?, 'P01', 'Sub-Assembly Pitch 1', 'Active', 10, 'Pitch', ?)""",
                (pitch_id, self.project_id, area_id, ts),
            )

        layout = create_layout(self.project_id, "Pin Map Spatial Layout", "Pin map test", self.editor)
        dwg_file = _create_mock_cad_file("Plant_Floor_Line_1.dwg", size_bytes=2048)
        rev = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout["id"],
            image_file=_create_test_image(),
            width_value=100.0,
            height_value=50.0,
            unit="feet",
            notes=None,
            editor_name=self.editor,
            cad_file=dwg_file,
            cad_web_url="https://autodesk360.com/plant/line1.dwg",
        )
        self._track_upload(rev["image_path"])
        self._track_upload(rev["cad_file_path"])

        # Place a pitch shape on the layout
        save_layout_shapes(
            self.project_id,
            rev["id"],
            [
                {
                    "shape_type": "workstation",
                    "pitch_id": pitch_id,
                    "x": 10.0,
                    "y": 10.0,
                    "width": 20.0,
                    "height": 10.0,
                    "rotation": 0.0,
                    "label": "Pitch 1",
                    "color": "#1976d2",
                }
            ],
            self.editor,
        )

        footprints = get_pitch_layout_footprints(self.project_id, scenario_id)
        self.assertEqual(len(footprints), 1)
        fp = footprints[0]
        self.assertEqual(fp["cad_file_name"], "Plant_Floor_Line_1.dwg")
        self.assertEqual(fp["cad_file_size_bytes"], 2048)
        self.assertEqual(fp["cad_web_url"], "https://autodesk360.com/plant/line1.dwg")
        self.assertTrue(Path(fp["cad_file_path"]).exists())


if __name__ == "__main__":
    unittest.main()
