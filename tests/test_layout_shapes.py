"""Unit and AppTest tests for 2D layout shape annotations, geometry math, and styling."""

from __future__ import annotations

import io
import json
import math
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from PIL import Image
from streamlit.testing.v1 import AppTest

import utils.layout_store as layout_store
import utils.store as store
from utils.layout_ui import (
    FOOTPRINT_PRESETS,
    LAYOUT_SWATCH_PALETTE,
    LINE_STYLE_OPTIONS,
    LINE_THICKNESS_OPTIONS,
    SHAPE_TYPES,
    _calculate_shape_area,
    _format_shape_dim,
    _normalize_hex_color,
    _px_to_units,
    _render_color_selector,
    _units_to_px,
)


def _make_dummy_image(width: int = 1000, height: int = 600) -> io.BytesIO:
    img = Image.new("RGB", (width, height), color=(240, 240, 240))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    setattr(buffer, "name", "test_plan.png")
    return buffer


class LayoutShapesMathTests(unittest.TestCase):
    """Test geometric conversion, scale math, and area calculations."""

    def test_units_and_pixel_conversions(self) -> None:
        # Scale: 100 ft represented by 1000 px -> 10 px / ft -> 1200 in = 1000 px -> px_per_in = 1000 / 1200 = 0.8333...
        px_per_in = 1000.0 / 1200.0
        unit = "feet"

        # 10 feet to px
        px = _units_to_px(10.0, px_per_in, unit)
        self.assertAlmostEqual(px, 100.0, places=2)

        # 100 px back to feet
        ft = _px_to_units(100.0, px_per_in, unit)
        self.assertAlmostEqual(ft, 10.0, places=2)

        # Formatted label
        formatted = _format_shape_dim(100.0, px_per_in, unit)
        self.assertEqual(formatted, "10.0 feet")

    def test_area_calculations_for_all_shapes(self) -> None:
        w = 10.0
        h = 8.0

        # Rectangle
        rect_area = _calculate_shape_area("rectangle", w, h)
        self.assertAlmostEqual(rect_area, 80.0, places=3)

        # Triangle
        tri_area = _calculate_shape_area("triangle", w, h)
        self.assertAlmostEqual(tri_area, 40.0, places=3)

        # Oval / Ellipse: pi * (w/2) * (h/2) = pi * 5 * 4 = 20 * pi ~ 62.8318
        oval_area = _calculate_shape_area("oval", w, h)
        self.assertAlmostEqual(oval_area, math.pi * 5.0 * 4.0, places=3)

        # Circle: pi * r^2 where r = min(w, h)/2 = 8 / 2 = 4 -> pi * 16 ~ 50.265
        circle_area = _calculate_shape_area("circle", w, h)
        self.assertAlmostEqual(circle_area, math.pi * 16.0, places=3)

        # Hexagon: (3 * sqrt(3) / 2) * r^2 where r = min(w, h)/2 = 4
        hex_area = _calculate_shape_area("hexagon", w, h)
        expected_hex = (3.0 * math.sqrt(3.0) / 2.0) * 16.0
        self.assertAlmostEqual(hex_area, expected_hex, places=3)

        # Text box
        text_area = _calculate_shape_area("text", w, h)
        self.assertAlmostEqual(text_area, 80.0, places=3)

    def test_presets_coverage(self) -> None:
        for name, preset in FOOTPRINT_PRESETS.items():
            self.assertIn(preset["shape_type"], SHAPE_TYPES)
            self.assertIn(preset["stroke_width"], LINE_THICKNESS_OPTIONS)
            self.assertIn(preset["stroke_style"], LINE_STYLE_OPTIONS)
            self.assertGreaterEqual(preset["fill_opacity"], 0.0)
            self.assertLessEqual(preset["fill_opacity"], 1.0)

    def test_dual_axis_scaling_and_subpixel_precision(self) -> None:
        # User scenario: 800x133 px layout representing 680x80 ft
        w_in = 680.0 * 12.0  # 8160 in
        h_in = 80.0 * 12.0   # 960 in
        px_per_in_x = 800.0 / w_in
        px_per_in_y = 133.0 / h_in

        # 4 ft by 2 ft pitch standards
        pitch_w_ft = 4.0
        pitch_h_ft = 2.0
        w_px = _units_to_px(pitch_w_ft, px_per_in_x, "feet")
        h_px = _units_to_px(pitch_h_ft, px_per_in_y, "feet")

        # Must not be clamped to 24px or distorted to 20.4 ft
        self.assertAlmostEqual(w_px, 4.71, places=2)
        self.assertAlmostEqual(h_px, 3.33, places=2)

        read_w_ft = _px_to_units(w_px, px_per_in_x, "feet")
        read_h_ft = _px_to_units(h_px, px_per_in_y, "feet")
        self.assertAlmostEqual(read_w_ft, 4.0, places=2)
        self.assertAlmostEqual(read_h_ft, 2.0, places=2)

        # Custom shape: 10 ft by 5 ft
        custom_w_px = _units_to_px(10.0, px_per_in_x, "feet")
        custom_h_px = _units_to_px(5.0, px_per_in_y, "feet")
        self.assertAlmostEqual(_px_to_units(custom_w_px, px_per_in_x, "feet"), 10.0, places=2)
        self.assertAlmostEqual(_px_to_units(custom_h_px, px_per_in_y, "feet"), 5.0, places=2)


class LayoutShapesStoreTests(unittest.TestCase):
    """Test shape persistence, style JSON serialization, and revision copy-forward."""

    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_layout_shapes_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.editor = "Nicole Ervin"

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_save_and_retrieve_shapes_with_styling(self) -> None:
        layout = layout_store.create_layout(
            self.project_id, "Packaging Floor", "Testing shapes", self.editor
        )
        rev = layout_store.create_layout_revision(
            project_id=self.project_id,
            layout_id=layout["id"],
            image_file=_make_dummy_image(1200, 800),
            width_value=120.0,
            height_value=80.0,
            unit="feet",
            notes="Initial layout",
            editor_name=self.editor,
        )

        style_meta = {
            "stroke_color": "#1976D2",
            "stroke_width": 3,
            "stroke_style": "dashed",
            "fill_color": "#42A5F5",
            "fill_opacity": 0.35,
            "font_size": 16,
            "font_color": "#000000",
            "font_weight": "bold",
            "bg_pill": True,
        }

        shapes_to_save = [
            {
                "id": str(uuid4()),
                "shape_type": "rectangle",
                "label": "Workstation 101",
                "x": 150.0,
                "y": 200.0,
                "width": 120.0,
                "height": 80.0,
                "rotation": 15.0,
                "color": "#1976D2",
                "style_json": json.dumps(style_meta),
            },
            {
                "id": str(uuid4()),
                "shape_type": "circle",
                "label": "Rotary Buffer",
                "x": 400.0,
                "y": 300.0,
                "width": 60.0,
                "height": 60.0,
                "rotation": 0.0,
                "color": "#F57C00",
                "style_json": json.dumps({"fill_opacity": 0.4}),
            },
        ]

        layout_store.save_layout_shapes(
            self.project_id, rev["id"], shapes_to_save, self.editor
        )

        retrieved = layout_store.list_layout_shapes(rev["id"])
        self.assertEqual(len(retrieved), 2)

        s1 = next(s for s in retrieved if s["label"] == "Workstation 101")
        self.assertEqual(s1["shape_type"], "rectangle")
        self.assertAlmostEqual(s1["x"], 150.0)
        self.assertAlmostEqual(s1["y"], 200.0)
        self.assertAlmostEqual(s1["width"], 120.0)
        self.assertAlmostEqual(s1["height"], 80.0)
        self.assertAlmostEqual(s1["rotation"], 15.0)

        s1_style = json.loads(s1["style_json"])
        self.assertEqual(s1_style["stroke_color"], "#1976D2")
        self.assertEqual(s1_style["stroke_width"], 3)
        self.assertEqual(s1_style["stroke_style"], "dashed")
        self.assertAlmostEqual(s1_style["fill_opacity"], 0.35)
        self.assertEqual(s1_style["font_size"], 16)
        self.assertTrue(s1_style["bg_pill"])

    def test_copy_forward_shapes_into_new_revision(self) -> None:
        layout = layout_store.create_layout(
            self.project_id, "Assembly Line A", "Copy forward test", self.editor
        )
        rev1 = layout_store.create_layout_revision(
            project_id=self.project_id,
            layout_id=layout["id"],
            image_file=_make_dummy_image(),
            width_value=100.0,
            height_value=50.0,
            unit="feet",
            editor_name=self.editor,
        )

        shapes = [
            {
                "id": str(uuid4()),
                "shape_type": "rectangle",
                "label": "Pitch 01",
                "x": 50.0,
                "y": 50.0,
                "width": 100.0,
                "height": 50.0,
                "rotation": 0.0,
                "color": "#1976D2",
                "style_json": json.dumps({"stroke_width": 2, "fill_opacity": 0.3}),
            }
        ]
        layout_store.save_layout_shapes(
            self.project_id, rev1["id"], shapes, self.editor
        )

        # Create Revision 2 copying from Rev 1
        rev2 = layout_store.create_layout_revision(
            project_id=self.project_id,
            layout_id=layout["id"],
            image_file=_make_dummy_image(),
            width_value=100.0,
            height_value=50.0,
            unit="feet",
            notes="Updated CAD with copied shapes",
            editor_name=self.editor,
            copy_from_revision_id=rev1["id"],
        )

        rev2_shapes = layout_store.list_layout_shapes(rev2["id"])
        self.assertEqual(len(rev2_shapes), 1)
        self.assertEqual(rev2_shapes[0]["label"], "Pitch 01")
        # Ensure new unique ID was generated
        self.assertNotEqual(rev2_shapes[0]["id"], shapes[0]["id"])
        rev2_style = json.loads(rev2_shapes[0]["style_json"])
        self.assertEqual(rev2_style["stroke_width"], 2)

    def test_section_pitch_standards_crud(self) -> None:
        layout = layout_store.create_layout(
            self.project_id, "Standards Test", "Testing pitch dimensions", self.editor
        )
        sec_id = "test-sec-1"
        res = layout_store.set_section_pitch_standard(
            project_id=self.project_id,
            layout_id=layout["id"],
            section_id=sec_id,
            pitch_width=16.0,
            pitch_height=10.0,
            unit="feet",
            editor_name=self.editor,
        )
        self.assertEqual(res["pitch_width"], 16.0)
        self.assertEqual(res["pitch_height"], 10.0)

        standards = layout_store.get_section_pitch_standards(layout["id"])
        self.assertIn(sec_id, standards)
        self.assertEqual(standards[sec_id]["pitch_width"], 16.0)
        self.assertEqual(standards[sec_id]["pitch_height"], 10.0)

    def test_cross_scenario_pitches_and_pin_map_footprints(self) -> None:
        scenario_id = str(uuid4())
        area_id = str(uuid4())
        pitch_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, status, takt_time_s, created_at, updated_at)
                   VALUES (?, ?, 'Base Plan', 'Rev A', 1, 'Working', 60.0, ?, ?)""",
                (scenario_id, self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES (?, ?, ?, 'Sub-Assembly Area', ?)""",
                (area_id, self.project_id, scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status, sequence, pitch_type, updated_at)
                   VALUES (?, ?, ?, 'P01', 'Sub-Assembly Pitch 1', 'Active', 10, 'Pitch', ?)""",
                (pitch_id, self.project_id, area_id, timestamp),
            )

        project_pitches = layout_store.list_project_yamazumi_pitches(self.project_id)
        self.assertTrue(any(p["pitch_id"] == pitch_id for p in project_pitches))
        matched = next(p for p in project_pitches if p["pitch_id"] == pitch_id)
        self.assertEqual(matched["scenario_name"], "Base Plan")
        self.assertEqual(matched["pitch_number"], "P01")

        layout = layout_store.create_layout(self.project_id, "Plant 1", "Main Layout", self.editor)
        rev = layout_store.create_layout_revision(
            project_id=self.project_id,
            layout_id=layout["id"],
            image_file=_make_dummy_image(1000, 500),
            width_value=100.0,
            height_value=50.0,
            unit="feet",
            editor_name=self.editor,
        )
        shape = {
            "id": str(uuid4()),
            "shape_type": "rectangle",
            "label": "P01 - Sub-Assembly Pitch 1",
            "x": 120.0,
            "y": 80.0,
            "width": 80.0,
            "height": 40.0,
            "rotation": 0.0,
            "color": "#1976D2",
            "pitch_id": pitch_id,
            "style_json": json.dumps({"fill_color": "#e3f2fd"}),
        }
        layout_store.save_layout_shapes(self.project_id, rev["id"], [shape], self.editor)

        footprints = layout_store.get_pitch_layout_footprints(self.project_id, scenario_id)
        self.assertEqual(len(footprints), 1)
        fp = footprints[0]
        self.assertEqual(fp["pitch_id"], pitch_id)
        self.assertEqual(fp["shape_id"], shape["id"])
        self.assertEqual(fp["x"], 120.0)
        self.assertEqual(fp["y"], 80.0)
        self.assertEqual(fp["pitch_number"], "P01")
        self.assertEqual(fp["layout_name"], "Plant 1")


class LayoutShapesAppSmokeTests(unittest.TestCase):
    """Test Streamlit page smoke rendering of Layouts workspace with shapes."""

    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_layout_smoke_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        scenarios = store.query("SELECT id FROM planning_scenarios WHERE project_id = ? LIMIT 1", (self.project_id,))
        self.scenario_id = str(scenarios[0]["id"]) if scenarios else ""
        self.editor = "Nicole Ervin"

        layout = layout_store.create_layout(
            self.project_id, "Smoke Floor Plan", "Testing UI", self.editor
        )
        self.layout_id = layout["id"]
        rev = layout_store.create_layout_revision(
            project_id=self.project_id,
            layout_id=self.layout_id,
            image_file=_make_dummy_image(800, 600),
            width_value=80.0,
            height_value=60.0,
            unit="feet",
            editor_name=self.editor,
        )
        self.rev_id = rev["id"]

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def _run_app(self) -> AppTest:
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/pin_map.py"),
            default_timeout=30,
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = self.editor
        app.session_state["active_layout_id"] = self.layout_id
        app.session_state["active_revision_id"] = self.rev_id
        app.run(timeout=30)
        return app

    def test_layouts_tab_renders_canvas_and_controls_without_exceptions(self) -> None:
        app = self._run_app()
        self.assertEqual([], list(app.exception))

        # Check button to add shape exists
        add_shape_btns = [
            b for b in app.button if "+ Add Shape" in str(getattr(b, "label", ""))
        ]
        self.assertTrue(len(add_shape_btns) > 0)

    def test_pin_map_renders_dual_views_without_exceptions(self) -> None:
        scenario_id = str(uuid4())
        area_id = str(uuid4())
        pitch_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, status, takt_time_s, created_at, updated_at)
                   VALUES (?, ?, 'Pin Map Plan', 'Rev B', 1, 'Working', 60.0, ?, ?)""",
                (scenario_id, self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES (?, ?, ?, 'Main Pin Area', ?)""",
                (area_id, self.project_id, scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status, sequence, pitch_type, updated_at)
                   VALUES (?, ?, ?, 'P02', 'Assembly Station', 'Active', 10, 'Pitch', ?)""",
                (pitch_id, self.project_id, area_id, timestamp),
            )

        shape = {
            "id": str(uuid4()),
            "shape_type": "rectangle",
            "label": "P02",
            "x": 50.0,
            "y": 50.0,
            "width": 60.0,
            "height": 30.0,
            "rotation": 0.0,
            "color": "#1976D2",
            "pitch_id": pitch_id,
        }
        layout_store.save_layout_shapes(self.project_id, self.rev_id, [shape], self.editor)

        # 1. Test Linear Flow Cards
        app1 = AppTest.from_file(str(store.ROOT / "app_pages/pin_map.py"), default_timeout=30)
        app1.session_state["project_id"] = self.project_id
        app1.session_state["scenario_id"] = scenario_id
        app1.session_state["current_editor"] = self.editor
        app1.run(timeout=30)
        self.assertEqual([], list(app1.exception))

        # 2. Test 2D Plant Spatial Map
        app2 = AppTest.from_file(str(store.ROOT / "app_pages/pin_map.py"), default_timeout=30)
        app2.session_state["project_id"] = self.project_id
        app2.session_state["scenario_id"] = scenario_id
        app2.session_state["current_editor"] = self.editor
        app2.session_state[f"pin_map_view_mode_{scenario_id}"] = "2D Plant Spatial Map"
        app2.run(timeout=30)
        self.assertEqual([], list(app2.exception))

    def test_drag_resize_shape_persistence_and_inspector_sync(self) -> None:
        """Verify that dragging handles to resize and repositioning shapes persists through save."""
        from utils.layout_ui import _px_to_units, _units_to_px

        px_per_in_x = 0.8  # e.g. 800 px / (100 ft * 12) = 0.667 px/in
        px_per_in_y = 1.0  # e.g. 500 px / (50 ft * 12)
        unit = "feet"

        init_w_px = _units_to_px(10.0, px_per_in_x, unit)
        init_h_px = _units_to_px(10.0, px_per_in_y, unit)

        shape_id = str(uuid4())
        shape = {
            "id": shape_id,
            "shape_type": "rectangle",
            "label": "Machine Cell A",
            "x": 100.0,
            "y": 100.0,
            "width": init_w_px,
            "height": init_h_px,
            "rotation": 0.0,
            "color": "#1976D2",
        }
        draft_shapes = [shape]

        # 1. User drags corners out to 25.0 ft width and 15.0 ft height, and moves to (220, 180)
        dragged_w_px = _units_to_px(25.0, px_per_in_x, unit)
        dragged_h_px = _units_to_px(15.0, px_per_in_y, unit)
        dragged_x = 220.0
        dragged_y = 180.0

        # Simulate shape_moved callback updating draft and inspector state
        shape["x"] = dragged_x
        shape["y"] = dragged_y
        shape["width"] = dragged_w_px
        shape["height"] = dragged_h_px

        # Synchronize inspector keys as handle_shape_moved does
        insp_w_val = float(round(_px_to_units(shape["width"], px_per_in_x, unit), 2))
        insp_h_val = float(round(_px_to_units(shape["height"], px_per_in_y, unit), 2))
        self.assertAlmostEqual(insp_w_val, 25.0, places=1)
        self.assertAlmostEqual(insp_h_val, 15.0, places=1)

        # Inspector re-renders:
        sw_units = _px_to_units(float(shape["width"]), px_per_in_x, unit)
        sh_units = _px_to_units(float(shape["height"]), px_per_in_y, unit)
        cur_w_units = float(round(sw_units, 2))
        cur_h_units = float(round(sh_units, 2))

        # Because inspector inputs match insp_w_val, user did not edit inspector inputs
        new_w_units = insp_w_val
        new_h_units = insp_h_val
        w_changed_in_inspector = abs(float(new_w_units) - cur_w_units) > 0.001
        h_changed_in_inspector = abs(float(new_h_units) - cur_h_units) > 0.001

        self.assertFalse(w_changed_in_inspector)
        self.assertFalse(h_changed_in_inspector)

        # Target px retains the dragged dimensions
        target_w_px = round(_units_to_px(new_w_units, px_per_in_x, unit), 2) if w_changed_in_inspector else float(shape["width"])
        target_h_px = round(_units_to_px(new_h_units, px_per_in_y, unit), 2) if h_changed_in_inspector else float(shape["height"])
        self.assertEqual(target_w_px, dragged_w_px)
        self.assertEqual(target_h_px, dragged_h_px)

        # 2. Save & Refresh persists the dragged shape to SQLite
        layout_store.save_layout_shapes(
            self.project_id, self.rev_id, draft_shapes, self.editor
        )

        # 3. Reload from database and verify persistence
        saved = layout_store.list_layout_shapes(self.rev_id)
        self.assertEqual(len(saved), 1)
        saved_shape = saved[0]
        self.assertEqual(saved_shape["id"], shape_id)
        self.assertAlmostEqual(saved_shape["x"], 220.0)
        self.assertAlmostEqual(saved_shape["y"], 180.0)
        self.assertAlmostEqual(saved_shape["width"], dragged_w_px, places=1)
        self.assertAlmostEqual(saved_shape["height"], dragged_h_px, places=1)

        # Dimension calculation in units confirms the saved shape is 25 x 15 ft
        reloaded_w_units = _px_to_units(saved_shape["width"], px_per_in_x, unit)
        reloaded_h_units = _px_to_units(saved_shape["height"], px_per_in_y, unit)
        self.assertAlmostEqual(reloaded_w_units, 25.0, places=1)
        self.assertAlmostEqual(reloaded_h_units, 15.0, places=1)

    def test_hex_normalization(self) -> None:
        self.assertEqual(_normalize_hex_color("#1976D2"), "#1976d2")
        self.assertEqual(_normalize_hex_color("1976d2"), "#1976d2")
        self.assertEqual(_normalize_hex_color("#fff"), "#ffffff")
        self.assertEqual(_normalize_hex_color("fff"), "#ffffff")
        self.assertEqual(_normalize_hex_color("#123"), "#112233")
        self.assertEqual(_normalize_hex_color(None, default="#d32f2f"), "#d32f2f")
        self.assertEqual(_normalize_hex_color("invalid", default="#1976d2"), "#1976d2")
        self.assertEqual(_normalize_hex_color(12345, default="#1976d2"), "#1976d2")

    def test_palette_validity(self) -> None:
        self.assertGreaterEqual(len(LAYOUT_SWATCH_PALETTE), 9)
        for emoji, hex_code in LAYOUT_SWATCH_PALETTE.items():
            self.assertTrue(hex_code.startswith("#"), f"{hex_code} must start with #")
            self.assertEqual(len(hex_code), 7, f"{hex_code} must be 7 chars")
            int(hex_code[1:], 16)  # must parse as valid hex

    def test_inspector_color_selector_interaction(self) -> None:
        shape_id = str(uuid4())
        shape = {
            "id": shape_id,
            "shape_type": "rectangle",
            "label": "Test Workstation",
            "x": 100.0,
            "y": 100.0,
            "width": 120.0,
            "height": 80.0,
            "rotation": 0.0,
            "color": "#1976d2",
            "pitch_id": None,
            "style_json": json.dumps({
                "stroke_color": "#1976d2",
                "fill_color": "#ffffff",
                "stroke_width": 2,
                "stroke_style": "solid",
                "fill_opacity": 0.25,
                "font_size": 14,
                "font_color": "#1a1a1a",
                "font_weight": "bold",
                "bg_pill": True,
            }),
        }
        layout_store.save_layout_shapes(self.project_id, self.rev_id, [shape], self.editor)

        app = AppTest.from_file(
            str(store.ROOT / "app_pages/pin_map.py"),
            default_timeout=30,
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = self.editor
        app.session_state["active_layout_id"] = self.layout_id
        app.session_state["active_revision_id"] = self.rev_id
        app.session_state[f"layout_selected_shape_{self.rev_id}"] = shape_id
        app.run(timeout=30)
        self.assertEqual([], list(app.exception))

        # Check color pickers and pills exist for this shape
        color_pickers = [cp for cp in app.color_picker]
        self.assertGreaterEqual(len(color_pickers), 3)

        # Trigger quick palette selection on border color (e.g. Conveyor Orange 🟠)
        pill_key = f"insp_stroke_{shape_id}_pill"
        self.assertIn(pill_key, app.session_state)
        app.session_state[pill_key] = "🟠"
        app.run(timeout=30)
        self.assertEqual([], list(app.exception))

        # Verify that the color updated to orange
        drafts = app.session_state[f"layout_shapes_draft_{self.rev_id}"]
        matched = next(s for s in drafts if s["id"] == shape_id)
        self.assertEqual(matched["color"], "#f57c00")


if __name__ == "__main__":
    unittest.main()

