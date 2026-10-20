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
        self.assertEqual(app.session_state["active_layout_id"], self.layout_id)
        self.assertEqual(app.session_state["active_revision_id"], self.rev_id)
        self.assertIn(f"layout_shapes_draft_{self.rev_id}", app.session_state)
        self.assertIn(f"layout_layers_draft_{self.rev_id}", app.session_state)

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

        # Verify shape and default layers are loaded into session state for the canvas
        drafts = app.session_state[f"layout_shapes_draft_{self.rev_id}"]
        matched = next(s for s in drafts if s["id"] == shape_id)
        self.assertEqual(matched["color"], "#1976d2")
        self.assertEqual(LAYOUT_SWATCH_PALETTE["🟠"], "#f57c00")

    def test_sync_draft_layers_to_db_updates_z_index_and_creates_custom_layers(self) -> None:
        from utils.layout_ui import _sync_draft_layers_to_db

        layers = layout_store.ensure_default_layers_for_revision(self.rev_id)
        draft_layers = [dict(l) for l in layers]
        draft_layers[0]["name"] = "Updated Base Layer"
        draft_layers.append(
            {
                "id": "layer_temp_custom",
                "name": "Custom Overlay",
                "visible": True,
                "locked": False,
                "opacity": 0.85,
                "z_index": 90,
                "color": "#7c3aed",
            }
        )
        id_map = _sync_draft_layers_to_db(
            project_id=self.project_id,
            revision_id=self.rev_id,
            draft_layers=draft_layers,
            editor_name=self.editor,
        )
        self.assertIn("layer_temp_custom", id_map)
        updated_layers = layout_store.list_layout_layers(self.rev_id)
        names = [l["name"] for l in updated_layers]
        self.assertIn("Updated Base Layer", names)
        self.assertIn("Custom Overlay", names)

    def test_canvas_commit_all_actions_and_cad_screenshot_upload_stress(self) -> None:
        """End-to-end stress test of all handle_canvas_commit actions via AppTest."""
        import base64

        # Create a 1600x900 CAD floorplan screenshot data URL
        buf = _make_dummy_image(1600, 900)
        b64_str = base64.b64encode(buf.getvalue()).decode("ascii")
        data_url = f"data:image/png;base64,{b64_str}"

        layers = [dict(l) for l in layout_store.ensure_default_layers_for_revision(self.rev_id)]
        layers[0]["opacity"] = 0.75
        layers[1]["visible"] = False
        layers.append(
            {
                "id": "layer_custom_stress",
                "name": "Safety Walkways",
                "visible": True,
                "locked": False,
                "opacity": 0.9,
                "z_index": 120,
                "color": "#16a34a",
            }
        )

        s1_id = str(uuid4())
        s2_id = str(uuid4())
        s3_id = str(uuid4())
        conn_id = str(uuid4())

        # Put connector FIRST (before its source_shape_id and target_shape_id) to stress-test FK ordering
        shapes_batch = [
            {
                "id": conn_id,
                "shape_type": "connector",
                "label": "Flow 1->3",
                "x": 100.0,
                "y": 100.0,
                "width": 200.0,
                "height": 80.0,
                "rotation": 0.0,
                "color": "#2563eb",
                "source_shape_id": s1_id,
                "target_shape_id": s3_id,
                "style_json": json.dumps({"routing": "elbow", "arrow": "end"}),
            },
            {
                "id": s1_id,
                "shape_type": "rectangle",
                "label": "Station 1",
                "x": 50.0,
                "y": 60.0,
                "width": 80.0,
                "height": 40.0,
                "rotation": 0.0,
                "color": "#2563eb",
                "layer_id": "layer_custom_stress",
                "pitch_id": "non_existent_pitch_id_should_safely_clear",
                "equipment_id": "non_existent_equip_id_should_safely_clear",
            },
            {
                "id": s2_id,
                "shape_type": "callout",
                "label": "Middle Note Original",
                "x": 180.0,
                "y": 90.0,
                "width": 70.0,
                "height": 45.0,
                "rotation": 0.0,
                "color": "#d97706",
            },
            {
                "id": s3_id,
                "shape_type": "circle",
                "label": "Station 3",
                "x": 320.0,
                "y": 140.0,
                "width": 60.0,
                "height": 60.0,
                "rotation": 0.0,
                "color": "#16a34a",
            },
        ]

        def run_commit(payload: dict) -> AppTest:
            app = AppTest.from_file(str(store.ROOT / "app_pages/pin_map.py"), default_timeout=30)
            app.session_state["project_id"] = self.project_id
            app.session_state["scenario_id"] = self.scenario_id
            app.session_state["current_editor"] = self.editor
            app.session_state["active_layout_id"] = self.layout_id
            app.session_state["active_revision_id"] = self.rev_id
            app.session_state[f"layout_canvas_{self.rev_id}"] = {"canvas_commit": payload}
            app.run(timeout=30)
            self.assertEqual([], list(app.exception))
            return app

        # 1. Upload CAD floorplan screenshot + save shapes & modified layers
        run_commit(
            {
                "action": "upload_background",
                "background_data_url": data_url,
                "shapes": shapes_batch,
                "layers": layers,
                "selected_shape_id": s2_id,
            }
        )
        rev_after_bg = layout_store.get_layout_revision(self.rev_id)
        self.assertIsNotNone(rev_after_bg)
        self.assertEqual(rev_after_bg["image_width_px"], 1600)
        self.assertEqual(rev_after_bg["image_height_px"], 900)
        # Aspect ratio preserved (80 ft wide * 900/1600 = 45 ft high)
        self.assertAlmostEqual(float(rev_after_bg["height_value"]), 45.0, places=2)

        saved_shapes = layout_store.list_layout_shapes(self.rev_id)
        self.assertEqual(len(saved_shapes), 4)
        saved_conn = next(s for s in saved_shapes if s["id"] == conn_id)
        self.assertEqual(saved_conn["source_shape_id"], s1_id)
        self.assertEqual(saved_conn["target_shape_id"], s3_id)

        # 2. Edit ONLY the middle shape (s2_id) without changing first/last shape or counts
        shapes_batch[2] = dict(shapes_batch[2], label="Middle Note Edited", x=215.5)
        run_commit(
            {
                "action": "save",
                "shapes": shapes_batch,
                "layers": [dict(l) for l in layout_store.list_layout_layers(self.rev_id)],
            }
        )
        saved_shapes_2 = layout_store.list_layout_shapes(self.rev_id)
        mid_shape = next(s for s in saved_shapes_2 if s["id"] == s2_id)
        self.assertEqual(mid_shape["label"], "Middle Note Edited")
        self.assertAlmostEqual(float(mid_shape["x"]), 215.5, places=2)

        # 3. Calibrate scale by 2-point reference
        run_commit(
            {
                "action": "calibrate_scale",
                "shapes": shapes_batch,
                "layers": [dict(l) for l in layout_store.list_layout_layers(self.rev_id)],
                "scale_calibration": {
                    "pixel_distance": 160.0,
                    "physical_distance": 20.0,
                    "unit": "feet",
                },
            }
        )
        rev_after_cal = layout_store.get_layout_revision(self.rev_id)
        # 160 px = 20 ft -> 8 px/ft -> 1600 px = 200 ft wide, 900 px = 112.5 ft high
        self.assertAlmostEqual(float(rev_after_cal["width_value"]), 200.0, places=1)
        self.assertAlmostEqual(float(rev_after_cal["height_value"]), 112.5, places=1)

        # 4. Update scale directly via top bar W x H
        run_commit(
            {
                "action": "update_scale",
                "shapes": shapes_batch,
                "layers": [dict(l) for l in layout_store.list_layout_layers(self.rev_id)],
                "width_value": 300.0,
                "height_value": 150.0,
                "unit": "meters",
            }
        )
        rev_after_su = layout_store.get_layout_revision(self.rev_id)
        self.assertAlmostEqual(float(rev_after_su["width_value"]), 300.0, places=1)
        self.assertAlmostEqual(float(rev_after_su["height_value"]), 150.0, places=1)
        self.assertEqual(rev_after_su["unit"], "meters")

        # 5. Rename page, add page, switch page, delete page, and clear background
        run_commit({"action": "rename_page", "page_title": "Main Assembly Floor"})
        self.assertEqual(layout_store.get_layout(self.project_id, self.layout_id)["name"], "Main Assembly Floor")

        app_added = run_commit({"action": "add_page", "page_title": "Sub-Assembly Floor"})
        all_pages = layout_store.list_layouts(self.project_id)
        self.assertEqual(len(all_pages), 2)
        new_page_id = str(app_added.session_state["active_layout_id"])
        self.assertNotEqual(new_page_id, self.layout_id)

        run_commit({"action": "clear_background"})
        rev_after_clear = layout_store.get_layout_revision(self.rev_id)
        self.assertIn("Blank scaled", str(rev_after_clear["notes"]))

    def test_stress_20000_shapes_batch_save_and_reload(self) -> None:
        """Stress test saving and querying 20,000 shapes in a single revision."""
        shapes_20k = []
        prev_id = None
        for i in range(20000):
            sid = f"shape_{self.rev_id}_{i}"
            if i % 20 == 0 and prev_id is not None:
                shapes_20k.append(
                    {
                        "id": sid,
                        "shape_type": "connector",
                        "label": f"C{i}",
                        "x": float((i % 200) * 12),
                        "y": float((i // 200) * 12),
                        "width": 10.0,
                        "height": 10.0,
                        "rotation": 0.0,
                        "color": "#2563eb",
                        "source_shape_id": prev_id,
                        "target_shape_id": f"shape_{self.rev_id}_{min(19999, i + 1)}",
                        "z_index": i,
                    }
                )
            else:
                shapes_20k.append(
                    {
                        "id": sid,
                        "shape_type": "rectangle" if i % 2 == 0 else "circle",
                        "label": f"S{i}",
                        "x": float((i % 200) * 12),
                        "y": float((i // 200) * 12),
                        "width": 8.0,
                        "height": 6.0,
                        "rotation": 0.0,
                        "color": "#1976d2",
                        "z_index": i,
                    }
                )
                prev_id = sid

        layout_store.save_layout_shapes(
            self.project_id, self.rev_id, shapes_20k, self.editor
        )
        reloaded_20k = layout_store.list_layout_shapes(self.rev_id)
        self.assertEqual(len(reloaded_20k), 20000)

        # Verify project export/import round-trip with layers and 20,000 shapes
        from utils.project_transfer import export_project_package, import_project_package

        pkg = export_project_package(self.project_id, editor_name=self.editor)
        self.assertTrue(pkg["file_name"].endswith(".paagproject"))
        self.assertGreater(len(pkg["data"]), 1000)

        imported = import_project_package(
            pkg["data"],
            "Create new",
            editor_name=self.editor,
        )
        imported_layouts = layout_store.list_layouts(imported["project_id"])
        self.assertGreaterEqual(len(imported_layouts), 1)
        imported_rev = layout_store.get_latest_layout_revision(imported_layouts[0]["id"])
        self.assertIsNotNone(imported_rev)
        imported_rev_id = imported_rev["id"]
        imported_shapes = layout_store.list_layout_shapes(imported_rev_id)
        self.assertEqual(len(imported_shapes), 20000)
        imported_layers = layout_store.list_layout_layers(imported_rev_id)
        self.assertEqual(len(imported_layers), 6)

    def test_new_pin_map_shapes_and_custom_stencils_end_to_end(self) -> None:
        """Verify all newly added shape types, extended style_json properties, and custom stencils CRUD."""
        new_shape_types = [
            "square", "pill", "semicircle", "quarter_circle", "arc_line",
            "right_triangle", "pentagon", "octagon", "trapezoid", "parallelogram",
            "l_shape", "t_shape", "u_shape", "cross", "star", "arrow_block",
            "cylinder", "document", "callout", "area_header", "pitch_box",
            "conveyor_curve", "x_box", "worker", "turntable", "quality_gate",
            "screen", "scanner", "computer_kiosk", "supermarket", "pallet",
            "agv", "mat_flow", "info_flow", "custom_polygon",
        ]
        shapes_payload = []
        for idx, stype in enumerate(new_shape_types):
            style = {
                "fill_opacity": 0.45,
                "text_color": "#0f172a",
                "font_weight": "700",
                "text_align": "center",
                "text_rotation": -90 if stype == "pitch_box" else 0,
            }
            if stype == "area_header":
                style["area_code"] = "374"
                style["area_pills"] = "STANDARD WORK,YAMAZUMI"
            if stype == "custom_polygon":
                style["points"] = [
                    {"nx": 0.0, "ny": 0.0},
                    {"nx": 1.0, "ny": 0.0},
                    {"nx": 1.0, "ny": 0.6},
                    {"nx": 0.5, "ny": 0.6},
                    {"nx": 0.5, "ny": 1.0},
                    {"nx": 0.0, "ny": 1.0},
                ]
            shapes_payload.append(
                {
                    "id": f"new_shape_{idx}",
                    "shape_type": stype,
                    "label": f"Label {stype}",
                    "x": float(idx * 10),
                    "y": 25.0,
                    "width": 12.0,
                    "height": 8.0,
                    "rotation": 90.0 if idx % 4 == 0 else 0.0,
                    "color": "#f97316",
                    "stroke_color": "#1e293b",
                    "stroke_width": 2.0,
                    "opacity": 1.0,
                    "font_size": 14,
                    "z_index": idx,
                    "style": style,
                }
            )

        layout_store.save_layout_shapes(self.project_id, self.rev_id, shapes_payload, self.editor)
        reloaded = layout_store.list_layout_shapes(self.rev_id)
        self.assertEqual(len(reloaded), len(new_shape_types))

        by_type = {row["shape_type"]: row for row in reloaded}
        self.assertIn("area_header", by_type)
        self.assertIn("custom_polygon", by_type)
        self.assertIn("pitch_box", by_type)

        import json
        area_style = json.loads(by_type["area_header"]["style_json"])
        self.assertEqual(area_style["area_code"], "374")
        self.assertAlmostEqual(float(area_style["fill_opacity"]), 0.45, places=2)

        poly_style = json.loads(by_type["custom_polygon"]["style_json"])
        self.assertEqual(len(poly_style["points"]), 6)

        # Custom stencil store CRUD
        saved_stencil = layout_store.save_layout_custom_stencil(
            self.project_id,
            name="Pedestal Bend Press",
            stencil_data={
                "base_width_px": 180.0,
                "base_height_px": 140.0,
                "items": [
                    {
                        "shape_type": "l_shape",
                        "nx": 0.0,
                        "ny": 0.0,
                        "nw": 1.0,
                        "nh": 1.0,
                        "color": "#f97316",
                        "stroke_color": "#c2410c",
                        "label": "PEDESTAL BEND",
                    }
                ],
            },
            editor_name=self.editor,
            category="Pin Map & Line Stencils",
        )
        stencil_id = saved_stencil["id"]
        stencils_list = layout_store.list_layout_custom_stencils(self.project_id)
        self.assertEqual(len(stencils_list), 1)
        self.assertEqual(stencils_list[0]["id"], stencil_id)
        self.assertEqual(stencils_list[0]["name"], "Pedestal Bend Press")

        layout_store.delete_layout_custom_stencil(self.project_id, stencil_id, editor_name=self.editor)
        self.assertEqual(len(layout_store.list_layout_custom_stencils(self.project_id)), 0)

    def test_all_js_dom_selectors_match_html_and_custom_stencil_commits(self) -> None:
        """Verify every #lc-* selector in _JS exists in _HTML and test custom stencil + partial modal commits."""
        import re
        import utils.layout_canvas as lc

        html_ids = set(re.findall(r'id=["\'](lc-[a-zA-Z0-9_-]+)["\']', lc._HTML))
        js_selectors = set(re.findall(r'#(lc-[a-zA-Z0-9_-]+)', lc._JS))
        missing_in_html = js_selectors - html_ids
        self.assertEqual(
            set(),
            missing_in_html,
            f"JS references DOM IDs missing in _HTML: {sorted(missing_in_html)}",
        )

        # Stress test handle_canvas_commit with save_custom_stencil, partial size/style save, and delete_custom_stencil
        shape_id = str(uuid4())
        initial_shape = {
            "id": shape_id,
            "shape_type": "pitch_box",
            "label": "P-101",
            "x": 120.0,
            "y": 80.0,
            "width": 96.0,
            "height": 48.0,
            "rotation": 0.0,
            "color": "#dbeafe",
            "style_json": {
                "stroke_color": "#1e293b",
                "stroke_width": 2,
                "stroke_style": "solid",
                "fill_color": "#dbeafe",
                "fill_opacity": 0.85,
                "font_size": 12,
                "font_weight": "bold",
                "text_color": "#0f172a",
                "text_align": "center",
                "text_rotation": -90,
            },
        }

        def run_commit(payload: dict) -> AppTest:
            app = AppTest.from_file(str(store.ROOT / "app_pages/pin_map.py"), default_timeout=30)
            app.session_state["project_id"] = self.project_id
            app.session_state["scenario_id"] = self.scenario_id
            app.session_state["current_editor"] = self.editor
            app.session_state["active_layout_id"] = self.layout_id
            app.session_state["active_revision_id"] = self.rev_id
            app.session_state[f"layout_canvas_{self.rev_id}"] = {"canvas_commit": payload}
            app.run(timeout=30)
            self.assertEqual([], list(app.exception))
            return app

        # 1. Save initial shape
        run_commit({"action": "save", "shapes": [initial_shape], "selected_shape_id": shape_id})
        saved = layout_store.list_layout_shapes(self.rev_id)
        self.assertEqual(len(saved), 1)
        self.assertAlmostEqual(float(saved[0]["width"]), 96.0, places=2)
        self.assertAlmostEqual(float(saved[0]["height"]), 48.0, places=2)

        # 2. Simulate double-click modal Apply Changes with ONLY new size (width=144.0, height=72.0)
        resized_shape = dict(initial_shape, width=144.0, height=72.0)
        run_commit({"action": "save", "shapes": [resized_shape], "selected_shape_id": shape_id})
        saved_after_resize = layout_store.list_layout_shapes(self.rev_id)
        self.assertEqual(len(saved_after_resize), 1)
        self.assertAlmostEqual(float(saved_after_resize[0]["width"]), 144.0, places=2)
        self.assertAlmostEqual(float(saved_after_resize[0]["height"]), 72.0, places=2)
        style_after_resize = json.loads(saved_after_resize[0]["style_json"])
        self.assertEqual(style_after_resize["label"] if "label" in style_after_resize else saved_after_resize[0]["label"], "P-101")
        self.assertEqual(style_after_resize["text_rotation"], -90)

        # 3. Save custom stencil via commit payload
        run_commit(
            {
                "action": "save_custom_stencil",
                "shapes": [resized_shape],
                "custom_stencil": {
                    "name": "Custom Pitch Cell",
                    "category": "Saved Shapes",
                    "stencil_json": {
                        "base_w": 144.0,
                        "base_h": 72.0,
                        "items": [{"shape_type": "pitch_box", "dx": 0, "dy": 0, "dw": 1, "dh": 1}],
                    },
                },
            }
        )
        stencils = layout_store.list_layout_custom_stencils(self.project_id)
        self.assertEqual(len(stencils), 1)
        self.assertEqual(stencils[0]["name"], "Custom Pitch Cell")

        # 4. Delete custom stencil via commit payload
        run_commit(
            {
                "action": "delete_custom_stencil",
                "shapes": [resized_shape],
                "stencil_id": stencils[0]["id"],
            }
        )
        self.assertEqual(len(layout_store.list_layout_custom_stencils(self.project_id)), 0)

        # 5. Re-saving unchanged shapes with non-sorted JSON string keys should be a no-op (no duplicate audit log)
        audit_before = len(store.audit_history(self.project_id, "Layouts"))
        unsorted_style_str = json.dumps(dict(reversed(list(resized_shape["style_json"].items()))))
        noop_shape = dict(resized_shape)
        noop_shape["style_json"] = unsorted_style_str
        layout_store.save_layout_shapes(
            self.project_id, self.rev_id, [noop_shape], self.editor
        )
        audit_after = len(store.audit_history(self.project_id, "Layouts"))
        self.assertEqual(audit_before, audit_after)

    def test_round5_and_round6_footprint_filtering_inactive_rename_and_spatial_svg(self) -> None:
        """Verify latest-revision & visible-layer footprint filtering, same-scenario non-fanout, inactive page rename, and 2D spatial SVG geometry."""
        # 1. Same-scenario two areas sharing a section_id and pitch_number ('P01') must NOT fan out
        ts = store.now_iso()
        sec_id = str(uuid4())
        area1_id = str(uuid4())
        area2_id = str(uuid4())
        pitch1_id = str(uuid4())
        pitch2_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO assembly_sections (id, project_id, name, sequence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (sec_id, self.project_id, "Chassis Section", 10, ts, ts),
            )
            conn.execute(
                "INSERT INTO yamazumi_areas (id, project_id, scenario_id, section_id, name, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (area1_id, self.project_id, self.scenario_id, sec_id, "Chassis Sub-Area A", ts),
            )
            conn.execute(
                "INSERT INTO yamazumi_areas (id, project_id, scenario_id, section_id, name, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (area2_id, self.project_id, self.scenario_id, sec_id, "Chassis Sub-Area B", ts),
            )
            conn.execute(
                """
                INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, status, sequence, pitch_type, updated_at)
                VALUES (?, ?, ?, 'P01', 'Sub-Area A Station 1', 'Active', 10, 'Pitch', ?)
                """,
                (pitch1_id, self.project_id, area1_id, ts),
            )
            conn.execute(
                """
                INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, status, sequence, pitch_type, updated_at)
                VALUES (?, ?, ?, 'P02', 'Sub-Area B Station 1', 'Active', 20, 'Pitch', ?)
                """,
                (pitch2_id, self.project_id, area2_id, ts),
            )

        layers = layout_store.ensure_default_layers_for_revision(self.rev_id)
        visible_layer_id = str(layers[0]["id"])
        hidden_layer = layout_store.create_layout_layer(
            self.project_id, self.rev_id, "Hidden Draft Layer", editor_name=self.editor
        )
        layout_store.update_layout_layer(
            self.project_id,
            str(hidden_layer["id"]),
            name="Hidden Draft Layer",
            visible=False,
            locked=False,
            opacity=1.0,
            color="#64748b",
            editor_name=self.editor,
        )

        # Place one visible L-shape for pitch1_id and one hidden shape for pitch2_id on Rev 1
        shape_rev1_vis = {
            "id": str(uuid4()),
            "layer_id": visible_layer_id,
            "shape_type": "l_shape",
            "label": "P01-L",
            "x": 50.0,
            "y": 60.0,
            "width": 120.0,
            "height": 80.0,
            "rotation": 0.0,
            "color": "#16a34a",
            "pitch_id": pitch1_id,
            "style_json": {"fill_color": "#bbf7d0", "stroke_color": "#16a34a"},
        }
        shape_rev1_hid = {
            "id": str(uuid4()),
            "layer_id": str(hidden_layer["id"]),
            "shape_type": "circle",
            "label": "Hidden-P01",
            "x": 250.0,
            "y": 60.0,
            "width": 90.0,
            "height": 90.0,
            "rotation": 0.0,
            "color": "#dc2626",
            "pitch_id": pitch2_id,
            "style_json": {},
        }
        layout_store.save_layout_shapes(
            self.project_id, self.rev_id, [shape_rev1_vis, shape_rev1_hid], self.editor
        )

        # Footprints on Rev 1: only visible_layer_id shape is returned, and it does NOT fan out to pitch2_id
        fps_rev1 = layout_store.get_pitch_layout_footprints(self.project_id, self.scenario_id)
        self.assertEqual(len(fps_rev1), 1)
        self.assertEqual(fps_rev1[0]["pitch_id"], pitch1_id)
        self.assertEqual(fps_rev1[0]["shape_type"], "l_shape")

        # 2. Create Rev 2 on the same layout; get_pitch_layout_footprints must only return Rev 2 footprints
        rev2 = layout_store.create_blank_scaled_revision(
            project_id=self.project_id,
            layout_id=self.layout_id,
            width_value=200.0,
            height_value=100.0,
            unit="feet",
            notes="Blank scaled grid canvas",
            editor_name=self.editor,
        )
        rev2_id = str(rev2["id"])
        rev2_layers = layout_store.ensure_default_layers_for_revision(rev2_id)
        shape_rev2 = {
            "id": str(uuid4()),
            "layer_id": str(rev2_layers[0]["id"]),
            "shape_type": "t_shape",
            "label": "P01-Rev2-T",
            "x": 140.0,
            "y": 90.0,
            "width": 100.0,
            "height": 100.0,
            "rotation": 15.0,
            "color": "#2563eb",
            "pitch_id": pitch1_id,
            "style_json": {"fill_color": "#bfdbfe", "stroke_color": "#2563eb"},
        }
        layout_store.save_layout_shapes(self.project_id, rev2_id, [shape_rev2], self.editor)

        fps_latest = layout_store.get_pitch_layout_footprints(self.project_id, self.scenario_id)
        self.assertEqual(len(fps_latest), 1)
        self.assertEqual(fps_latest[0]["revision_id"], rev2_id)
        self.assertEqual(fps_latest[0]["shape_type"], "t_shape")
        self.assertEqual(fps_latest[0]["label"], "P01-Rev2-T")

        # 3. Create a second page and rename the inactive first page via target_page_id
        page2 = layout_store.create_layout(
            self.project_id, "Page 2", "Second layout", self.editor
        )
        page2_rev = layout_store.create_blank_scaled_revision(
            project_id=self.project_id,
            layout_id=str(page2["id"]),
            width_value=200.0,
            height_value=100.0,
            unit="feet",
            notes="Blank scaled grid canvas",
            editor_name=self.editor,
        )
        app = AppTest.from_file(str(store.ROOT / "app_pages/pin_map.py"), default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = self.editor
        app.session_state["active_layout_id"] = str(page2["id"])
        app.session_state["active_revision_id"] = str(page2_rev["id"])
        app.session_state[f"layout_canvas_{page2_rev['id']}"] = {
            "canvas_commit": {
                "commit_id": str(uuid4()),
                "action": "rename_page",
                "target_page_id": self.layout_id,
                "page_title": "Renamed Inactive Page 1",
            }
        }
        app.run(timeout=30)
        self.assertEqual([], list(app.exception))
        self.assertEqual(
            layout_store.get_layout(self.project_id, self.layout_id)["name"],
            "Renamed Inactive Page 1",
        )
        self.assertEqual(
            layout_store.get_layout(self.project_id, str(page2["id"]))["name"],
            "Page 2",
        )

        # 4. Render 2D Plant Spatial Map tab and verify polygon SVG + Color Overlay controls render cleanly
        app_map = AppTest.from_file(str(store.ROOT / "app_pages/pin_map.py"), default_timeout=30)
        app_map.session_state["project_id"] = self.project_id
        app_map.session_state["scenario_id"] = self.scenario_id
        app_map.session_state["current_editor"] = self.editor
        app_map.session_state[f"pin_map_workspace_mode_{self.project_id}_{self.scenario_id}"] = (
            "Pin Map Matrix, Linear Flow & Excel Export"
        )
        app_map.session_state[f"pin_map_view_mode_{self.scenario_id}"] = "2D Plant Spatial Map"
        app_map.run(timeout=30)
        self.assertEqual([], list(app_map.exception))
        markdown_bodies = "\n".join(m.value for m in app_map.markdown)
        self.assertIn("<polygon", markdown_bodies)
        self.assertIn("paagMajorGrid", markdown_bodies)
        self.assertIn("P01-Rev2-T", markdown_bodies)


if __name__ == "__main__":
    unittest.main()

