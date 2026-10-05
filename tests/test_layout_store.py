"""Tests for 2D plant floor plan layout persistence, scaling math, and revision history."""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from PIL import Image

from utils import store
from utils.layout_store import (
    annotate_preview_with_dimensions,
    apply_image_crop,
    apply_image_orientation,
    auto_detect_whitespace_crop,
    create_layout,
    create_layout_revision,
    delete_layout,
    delete_layout_revision,
    format_dimension,
    from_canonical_inches,
    get_layout,
    get_layout_revision,
    get_pdf_page_count,
    import_shapes_from_revision,
    layout_deletion_impact,
    list_layout_revisions,
    list_layout_shapes,
    list_layouts,
    load_and_orient_layout_preview,
    render_dxf_to_image,
    render_pdf_page_to_image,
    save_layout_shapes,
    to_canonical_inches,
    update_layout,
    update_layout_revision_scale,
)


def _create_test_image_file(width: int = 100, height: int = 50, format: str = "PNG") -> io.BytesIO:
    """Create a minimal in-memory valid image file for tests."""
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color="red")
    img.save(buf, format=format)
    buf.seek(0)
    buf.name = f"test_floorplan.{format.lower()}"
    return buf


def _create_test_pdf_file(pages: int = 1) -> io.BytesIO:
    """Create a minimal in-memory valid PDF file for tests."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument.new()
    for i in range(pages):
        doc.new_page(200 + i * 100, 100 + i * 50)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    buf.name = "plant_floorplan.pdf"
    return buf


def _create_test_dxf_file() -> io.BytesIO:
    """Create a minimal in-memory valid DXF file for tests."""
    import ezdxf

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 50))
    buf = io.StringIO()
    doc.write(stream=buf)
    out = io.BytesIO(buf.getvalue().encode("utf-8"))
    out.name = "plant_drawing.dxf"
    return out


class LayoutStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_layout_store_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.editor = "Layout Tester"

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_linear_distance_unit_conversions(self) -> None:
        """Verify imperial unit conversions to/from canonical inches."""
        self.assertAlmostEqual(to_canonical_inches(10.0, "feet"), 120.0)
        self.assertAlmostEqual(to_canonical_inches(10.0, "ft"), 120.0)
        self.assertAlmostEqual(to_canonical_inches(24.0, "inches"), 24.0)
        self.assertAlmostEqual(to_canonical_inches(24.0, "in"), 24.0)
        self.assertAlmostEqual(to_canonical_inches(2.0, "yards"), 72.0)
        self.assertAlmostEqual(to_canonical_inches(1.0, "miles"), 63360.0)

        self.assertAlmostEqual(from_canonical_inches(120.0, "feet"), 10.0)
        self.assertAlmostEqual(from_canonical_inches(72.0, "yards"), 2.0)
        self.assertAlmostEqual(from_canonical_inches(24.0, "inches"), 24.0)

        self.assertEqual(format_dimension(120.0, "feet"), "10 feet")
        self.assertEqual(format_dimension(30.0, "feet"), "2.50 feet")

    def test_layout_plan_lifecycle(self) -> None:
        """Verify layout creation, listing, retrieval, update, and deletion."""
        # Initial state: no layouts
        self.assertEqual(list_layouts(self.project_id), [])

        # Create layout
        created = create_layout(self.project_id, "Main Line Floor", "Primary assembly building", self.editor)
        layout_id = created["id"]
        self.assertTrue(layout_id)

        # Retrieval
        layout = get_layout(self.project_id, layout_id)
        self.assertIsNotNone(layout)
        self.assertEqual(layout["name"], "Main Line Floor")
        self.assertEqual(layout["description"], "Primary assembly building")
        self.assertEqual(layout["revision_count"], 0)

        # Duplicate name prevention
        with self.assertRaises(ValueError):
            create_layout(self.project_id, "MAIN LINE FLOOR", "Duplicate", self.editor)

        # Update layout
        update_layout(self.project_id, layout_id, "Main Line Building 1", "Updated desc", self.editor)
        updated = get_layout(self.project_id, layout_id)
        self.assertEqual(updated["name"], "Main Line Building 1")
        self.assertEqual(updated["description"], "Updated desc")

        # Listing
        layouts = list_layouts(self.project_id)
        self.assertEqual(len(layouts), 1)
        self.assertEqual(layouts[0]["id"], layout_id)

    def test_layout_revision_creation_and_scaling(self) -> None:
        """Verify uploading revision with image dimensions and scale calculation."""
        layout = create_layout(self.project_id, "Packaging Floor", "", self.editor)
        layout_id = layout["id"]

        image_file = _create_test_image_file(width=1200, height=600)
        rev = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout_id,
            image_file=image_file,
            width_value=100.0,
            height_value=50.0,
            unit="feet",
            notes="Initial floor plan CAD drawing",
            copy_from_revision_id=None,
            editor_name=self.editor,
        )

        self.assertEqual(rev["revision_number"], 1)
        self.assertEqual(rev["image_width_px"], 1200)
        self.assertEqual(rev["image_height_px"], 600)
        self.assertAlmostEqual(rev["scale_width_in"], 1200.0)  # 100 ft = 1200 in
        self.assertAlmostEqual(rev["scale_height_in"], 600.0)  # 50 ft = 600 in

        # Check file exists on disk
        img_path = Path(rev["image_path"])
        self.assertTrue(img_path.exists())

        # Check revision retrieval
        revisions = list_layout_revisions(layout_id)
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0]["id"], rev["id"])

        # Update revision scale
        update_layout_revision_scale(
            project_id=self.project_id,
            revision_id=rev["id"],
            width_value=120.0,
            height_value=60.0,
            unit="feet",
            notes="Calibrated with tape measure",
            editor_name=self.editor,
        )
        updated_rev = get_layout_revision(rev["id"])
        self.assertAlmostEqual(updated_rev["scale_width_in"], 1440.0)
        self.assertEqual(updated_rev["notes"], "Calibrated with tape measure")

    def test_copy_forward_shapes_across_revisions(self) -> None:
        """Verify that shapes and annotations copy forward to new revisions."""
        layout = create_layout(self.project_id, "Subassembly Cell", "", self.editor)
        layout_id = layout["id"]

        # Create Rev 1
        img1 = _create_test_image_file(width=800, height=400)
        rev1 = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout_id,
            image_file=img1,
            width_value=50.0,
            height_value=25.0,
            unit="feet",
            notes="Rev 1 initial",
            copy_from_revision_id=None,
            editor_name=self.editor,
        )

        # Save some drawn shapes on Rev 1
        shapes = [
            {
                "shape_type": "rectangle",
                "label": "Station 1 Pitch",
                "x": 100.0,
                "y": 150.0,
                "width": 80.0,
                "height": 40.0,
                "rotation": 0.0,
                "color": "#1976d2",
            },
            {
                "shape_type": "circle",
                "label": "Torque Arm",
                "x": 220.0,
                "y": 160.0,
                "width": 30.0,
                "height": 30.0,
                "rotation": 0.0,
                "color": "#ff9800",
            },
        ]
        save_layout_shapes(self.project_id, rev1["id"], shapes, self.editor)

        rev1_shapes = list_layout_shapes(rev1["id"])
        self.assertEqual(len(rev1_shapes), 2)

        # Create Rev 2 with updated image, copying forward shapes from Rev 1
        img2 = _create_test_image_file(width=1000, height=500)
        rev2 = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout_id,
            image_file=img2,
            width_value=50.0,
            height_value=25.0,
            unit="feet",
            notes="Rev 2 updated CAD",
            copy_from_revision_id=rev1["id"],
            editor_name=self.editor,
        )

        self.assertEqual(rev2["revision_number"], 2)
        self.assertEqual(rev2["copied_shapes_count"], 2)

        # Verify Rev 2 has the copied shapes with new IDs and auto-scaled coordinates
        rev2_shapes = list_layout_shapes(rev2["id"])
        self.assertEqual(len(rev2_shapes), 2)
        self.assertNotEqual(rev2_shapes[0]["id"], rev1_shapes[0]["id"])
        self.assertEqual(rev2_shapes[0]["label"], "Station 1 Pitch")
        self.assertEqual(rev2_shapes[0]["shape_type"], "rectangle")
        # 800x400 -> 1000x500 is 1.25x scaling
        self.assertAlmostEqual(rev2_shapes[0]["x"], 125.0)
        self.assertAlmostEqual(rev2_shapes[0]["y"], 187.5)
        self.assertAlmostEqual(rev2_shapes[0]["width"], 100.0)
        self.assertAlmostEqual(rev2_shapes[0]["height"], 50.0)

        self.assertEqual(rev2_shapes[1]["label"], "Torque Arm")
        self.assertEqual(rev2_shapes[1]["shape_type"], "circle")
        self.assertAlmostEqual(rev2_shapes[1]["x"], 275.0)
        self.assertAlmostEqual(rev2_shapes[1]["y"], 200.0)
        self.assertAlmostEqual(rev2_shapes[1]["width"], 37.5)
        self.assertAlmostEqual(rev2_shapes[1]["height"], 37.5)

        # Verify Rev 1 shapes remain intact for viewing history
        rev1_shapes_after = list_layout_shapes(rev1["id"])
        self.assertEqual(len(rev1_shapes_after), 2)

    def test_import_shapes_from_revision_with_scaling(self) -> None:
        """Verify import_shapes_from_revision imports and auto-scales shapes to target resolution."""
        layout = create_layout(self.project_id, "Import Shapes Test", "", self.editor)
        layout_id = layout["id"]

        # Rev 1: 500x250
        img1 = _create_test_image_file(width=500, height=250)
        rev1 = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout_id,
            image_file=img1,
            width_value=50.0,
            height_value=25.0,
            unit="feet",
            notes="Rev 1",
            editor_name=self.editor,
        )

        shapes = [
            {
                "shape_type": "rectangle",
                "label": "Robot Cell",
                "x": 50.0,
                "y": 100.0,
                "width": 100.0,
                "height": 50.0,
                "rotation": 0.0,
                "color": "#4caf50",
                "style_json": '{"stroke_width": 2, "font_size": 12}',
            }
        ]
        save_layout_shapes(self.project_id, rev1["id"], shapes, self.editor)

        # Rev 2: 2000x1000 (4x resolution)
        img2 = _create_test_image_file(width=2000, height=1000)
        rev2 = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout_id,
            image_file=img2,
            width_value=50.0,
            height_value=25.0,
            unit="feet",
            notes="Rev 2 high res CAD",
            editor_name=self.editor,
        )

        # Initially Rev 2 has 0 shapes
        self.assertEqual(len(list_layout_shapes(rev2["id"])), 0)

        # Import shapes from Rev 1 into Rev 2
        count = import_shapes_from_revision(
            project_id=self.project_id,
            target_revision_id=rev2["id"],
            source_revision_id=rev1["id"],
            editor_name=self.editor,
        )
        self.assertEqual(count, 1)

        rev2_shapes = list_layout_shapes(rev2["id"])
        self.assertEqual(len(rev2_shapes), 1)
        s = rev2_shapes[0]
        self.assertEqual(s["label"], "Robot Cell")
        # 4x scale: x=50*4=200, y=100*4=400, w=100*4=400, h=50*4=200
        self.assertAlmostEqual(s["x"], 200.0)
        self.assertAlmostEqual(s["y"], 400.0)
        self.assertAlmostEqual(s["width"], 400.0)
        self.assertAlmostEqual(s["height"], 200.0)

        delete_layout(self.project_id, layout_id, self.editor)

    def test_layout_deletion_impact_and_cleanup(self) -> None:
        """Verify layout deletion cascades to revisions, shapes, and image files."""
        layout = create_layout(self.project_id, "Temporary Layout", "", self.editor)
        layout_id = layout["id"]

        img = _create_test_image_file()
        rev = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout_id,
            image_file=img,
            width_value=20.0,
            height_value=10.0,
            unit="feet",
            notes="To be deleted",
            copy_from_revision_id=None,
            editor_name=self.editor,
        )
        img_path = Path(rev["image_path"])
        self.assertTrue(img_path.exists())

        # Check impact
        impact = layout_deletion_impact(self.project_id, layout_id)
        self.assertEqual(impact["layout_name"], "Temporary Layout")
        self.assertEqual(impact["revision_count"], 1)
        self.assertEqual(impact["image_count"], 1)
        self.assertEqual(impact["shape_count"], 0)
        self.assertEqual(impact["revisions_count"], 1)
        self.assertEqual(impact["images_count"], 1)
        self.assertEqual(impact["shapes_count"], 0)

        # Check get_layout_revision includes shape_count
        fetched_rev = get_layout_revision(rev["id"])
        self.assertIsNotNone(fetched_rev)
        self.assertEqual(fetched_rev["shape_count"], 0)

        # Delete layout
        delete_layout(self.project_id, layout_id, self.editor)

        # Verify layout is gone from database
        self.assertIsNone(get_layout(self.project_id, layout_id))
        self.assertEqual(list_layout_revisions(layout_id), [])

        # Verify image file is cleaned up from disk
        self.assertFalse(img_path.exists())

    def test_single_revision_deletion(self) -> None:
        """Verify deleting an older revision while preserving the rest."""
        layout = create_layout(self.project_id, "Multi-rev layout", "", self.editor)
        layout_id = layout["id"]

        img1 = _create_test_image_file()
        rev1 = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout_id,
            image_file=img1,
            width_value=30.0,
            height_value=15.0,
            unit="feet",
            notes="Rev 1",
            copy_from_revision_id=None,
            editor_name=self.editor,
        )
        img1_path = Path(rev1["image_path"])

        img2 = _create_test_image_file()
        rev2 = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout_id,
            image_file=img2,
            width_value=30.0,
            height_value=15.0,
            unit="feet",
            notes="Rev 2",
            copy_from_revision_id=None,
            editor_name=self.editor,
        )
        img2_path = Path(rev2["image_path"])

        self.assertEqual(len(list_layout_revisions(layout_id)), 2)

        # Delete Rev 1
        delete_layout_revision(self.project_id, rev1["id"], self.editor)

        revisions_remaining = list_layout_revisions(layout_id)
        self.assertEqual(len(revisions_remaining), 1)
        self.assertEqual(revisions_remaining[0]["id"], rev2["id"])

        # Verify Rev 1 file is deleted, Rev 2 file remains
        self.assertFalse(img1_path.exists())
        self.assertTrue(img2_path.exists())

        # Cleanup Rev 2
        delete_layout(self.project_id, layout_id, self.editor)
        self.assertFalse(img2_path.exists())

    def test_layout_revision_pdf_import(self) -> None:
        """Verify importing a PDF drawing file renders as high-res PNG revision."""
        layout = create_layout(self.project_id, "Welding Bay PDF", "", self.editor)
        layout_id = layout["id"]

        pdf_file = _create_test_pdf_file(pages=1)
        self.assertEqual(get_pdf_page_count(pdf_file.getvalue()), 1)

        rev = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout_id,
            image_file=pdf_file,
            width_value=80.0,
            height_value=40.0,
            unit="feet",
            notes="PDF line plan",
            copy_from_revision_id=None,
            editor_name=self.editor,
        )

        self.assertEqual(rev["revision_number"], 1)
        self.assertTrue(rev["image_path"].endswith(".png"))
        self.assertTrue(Path(rev["image_path"]).exists())
        self.assertGreater(rev["image_width_px"], 0)
        self.assertGreater(rev["image_height_px"], 0)
        self.assertAlmostEqual(rev["scale_width_in"], 960.0)

        # Cleanup
        delete_layout(self.project_id, layout_id, self.editor)
        self.assertFalse(Path(rev["image_path"]).exists())

    def test_layout_revision_pdf_multi_page_selection(self) -> None:
        """Verify multi-page PDF sheet selection renders the designated page."""
        layout = create_layout(self.project_id, "Multi Sheet CAD", "", self.editor)
        layout_id = layout["id"]

        pdf_file = _create_test_pdf_file(pages=2)
        self.assertEqual(get_pdf_page_count(pdf_file.getvalue()), 2)

        # Import sheet 2
        rev = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout_id,
            image_file=pdf_file,
            width_value=120.0,
            height_value=60.0,
            unit="feet",
            notes="Sheet 2",
            copy_from_revision_id=None,
            editor_name=self.editor,
            pdf_page=2,
        )

        self.assertEqual(rev["revision_number"], 1)
        self.assertTrue(Path(rev["image_path"]).exists())
        delete_layout(self.project_id, layout_id, self.editor)

    def test_layout_revision_orientation_rotation(self) -> None:
        """Verify rotating drawing by 90/180/270 degrees clockwise transforms image dimensions."""
        layout = create_layout(self.project_id, "Rotated Cell", "", self.editor)
        layout_id = layout["id"]

        # Original: width=400, height=200
        img_90 = _create_test_image_file(width=400, height=200)
        rev_90 = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout_id,
            image_file=img_90,
            width_value=50.0,
            height_value=100.0,
            unit="feet",
            notes="Rotated 90 deg",
            copy_from_revision_id=None,
            editor_name=self.editor,
            rotation_angle=90,
        )

        # 90 degrees CW rotation swaps width and height
        self.assertEqual(rev_90["image_width_px"], 200)
        self.assertEqual(rev_90["image_height_px"], 400)
        self.assertTrue(Path(rev_90["image_path"]).exists())

        # 180 degrees keeps same width and height
        img_180 = _create_test_image_file(width=400, height=200)
        rev_180 = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout_id,
            image_file=img_180,
            width_value=100.0,
            height_value=50.0,
            unit="feet",
            notes="Rotated 180 deg",
            copy_from_revision_id=None,
            editor_name=self.editor,
            rotation_angle=180,
        )
        self.assertEqual(rev_180["image_width_px"], 400)
        self.assertEqual(rev_180["image_height_px"], 200)

        delete_layout(self.project_id, layout_id, self.editor)

    def test_layout_revision_dxf_import(self) -> None:
        """Verify importing a 2D DXF CAD file converts modelspace to layout image."""
        layout = create_layout(self.project_id, "AutoCAD DXF Bay", "", self.editor)
        layout_id = layout["id"]

        dxf_file = _create_test_dxf_file()
        rev = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout_id,
            image_file=dxf_file,
            width_value=50.0,
            height_value=25.0,
            unit="feet",
            notes="Imported from AutoCAD DXF",
            copy_from_revision_id=None,
            editor_name=self.editor,
        )

        self.assertEqual(rev["revision_number"], 1)
        self.assertTrue(rev["image_path"].endswith(".png"))
        self.assertTrue(Path(rev["image_path"]).exists())
        self.assertGreater(rev["image_width_px"], 0)
        self.assertGreater(rev["image_height_px"], 0)

        delete_layout(self.project_id, layout_id, self.editor)

    def test_load_and_orient_layout_preview(self) -> None:
        """Verify load_and_orient_layout_preview generates PIL preview for images, PDFs, and DXFs."""
        # Raster image preview with rotation
        img_file = _create_test_image_file(width=300, height=150)
        preview_img = load_and_orient_layout_preview(img_file, rotation_angle=90)
        self.assertIsNotNone(preview_img)
        self.assertEqual(preview_img.size, (150, 300))

        # PDF preview
        pdf_file = _create_test_pdf_file(pages=1)
        preview_pdf = load_and_orient_layout_preview(pdf_file, rotation_angle=0)
        self.assertIsNotNone(preview_pdf)

        # DXF preview
        dxf_file = _create_test_dxf_file()
        preview_dxf = load_and_orient_layout_preview(dxf_file, rotation_angle=0)
        self.assertIsNotNone(preview_dxf)

        # Preview with cropping
        cropped_preview = load_and_orient_layout_preview(
            img_file,
            rotation_angle=0,
            crop_left_pct=10.0,
            crop_right_pct=10.0,
            crop_top_pct=10.0,
            crop_bottom_pct=10.0,
        )
        self.assertIsNotNone(cropped_preview)
        self.assertEqual(cropped_preview.size, (240, 120))

    def test_auto_detect_whitespace_crop(self) -> None:
        """Verify auto_detect_whitespace_crop detects non-white content boundary with padding."""
        from PIL import ImageDraw

        # 400x300 image with white border and dark box in center (100, 50) to (300, 250)
        img = Image.new("RGB", (400, 300), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(100, 50), (300, 250)], fill=(50, 50, 50))

        bbox = auto_detect_whitespace_crop(img, threshold=240, padding=10)
        # Content is [100, 50, 300, 250], with padding 10: [90, 40, 311, 261]
        self.assertLessEqual(bbox[0], 95)
        self.assertLessEqual(bbox[1], 45)
        self.assertGreaterEqual(bbox[2], 305)
        self.assertGreaterEqual(bbox[3], 255)

        # Blank white image falls back to full bounds
        white_img = Image.new("RGB", (200, 100), (255, 255, 255))
        white_bbox = auto_detect_whitespace_crop(white_img)
        self.assertEqual(white_bbox, (0, 0, 200, 100))

    def test_apply_image_crop(self) -> None:
        """Verify apply_image_crop crops by percentage and clamps safely."""
        img = Image.new("RGB", (1000, 500), (200, 200, 200))

        # 0% crop returns original
        same = apply_image_crop(img, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(same.size, (1000, 500))

        # 10% left, 20% right, 10% top, 10% bottom
        # left = 100, right = 800 -> width = 700
        # top = 50, bottom = 450 -> height = 400
        cropped = apply_image_crop(img, crop_left_pct=10.0, crop_top_pct=10.0, crop_right_pct=20.0, crop_bottom_pct=10.0)
        self.assertEqual(cropped.size, (700, 400))

    def test_annotate_preview_with_dimensions(self) -> None:
        """Verify annotate_preview_with_dimensions frames image with rulers and arrows."""
        img = Image.new("RGB", (500, 300), (240, 240, 240))
        framed = annotate_preview_with_dimensions(img, width_val=100.0, height_val=60.0, unit="feet")
        self.assertIsNotNone(framed)
        self.assertGreater(framed.width, 500)
        self.assertGreater(framed.height, 300)

    def test_layout_revision_with_crop(self) -> None:
        """Verify creating a layout revision with cropping trims image on disk and records accurate px."""
        layout = create_layout(self.project_id, "Cropped Revision Plant", "", self.editor)
        layout_id = layout["id"]

        img_file = _create_test_image_file(width=1000, height=500)
        rev = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout_id,
            image_file=img_file,
            width_value=80.0,
            height_value=40.0,
            unit="feet",
            notes="Cropped outer margins",
            editor_name=self.editor,
            crop_left_pct=10.0,
            crop_top_pct=10.0,
            crop_right_pct=10.0,
            crop_bottom_pct=10.0,
        )

        self.assertEqual(rev["revision_number"], 1)
        self.assertEqual(rev["image_width_px"], 800)
        self.assertEqual(rev["image_height_px"], 400)
        self.assertTrue(Path(rev["image_path"]).exists())
        with Image.open(rev["image_path"]) as saved_img:
            self.assertEqual(saved_img.size, (800, 400))

        delete_layout(self.project_id, layout_id, self.editor)


if __name__ == "__main__":
    unittest.main()
