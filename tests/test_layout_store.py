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
    create_layout,
    create_layout_revision,
    delete_layout,
    delete_layout_revision,
    format_dimension,
    from_canonical_inches,
    get_layout,
    get_layout_revision,
    layout_deletion_impact,
    list_layout_revisions,
    list_layout_shapes,
    list_layouts,
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

        # Verify Rev 2 has the copied shapes with new IDs
        rev2_shapes = list_layout_shapes(rev2["id"])
        self.assertEqual(len(rev2_shapes), 2)
        self.assertNotEqual(rev2_shapes[0]["id"], rev1_shapes[0]["id"])
        self.assertEqual(rev2_shapes[0]["label"], "Station 1 Pitch")
        self.assertEqual(rev2_shapes[0]["shape_type"], "rectangle")
        self.assertEqual(rev2_shapes[1]["label"], "Torque Arm")
        self.assertEqual(rev2_shapes[1]["shape_type"], "circle")

        # Verify Rev 1 shapes remain intact for viewing history
        rev1_shapes_after = list_layout_shapes(rev1["id"])
        self.assertEqual(len(rev1_shapes_after), 2)

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


if __name__ == "__main__":
    unittest.main()
