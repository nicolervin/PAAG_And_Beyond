from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from streamlit.testing.v1 import AppTest

from utils import store


REPO_ROOT = Path(__file__).resolve().parents[1]


class EquipmentPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_equipment_pages_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def _run(self, path: str, selected_tab_key: str | None = None) -> AppTest:
        app = AppTest.from_file(REPO_ROOT / path)
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Equipment page tester"
        if selected_tab_key:
            app.session_state[selected_tab_key] = "Equipment"
        app.run(timeout=30)
        self.assertEqual([], list(app.exception))
        return app

    def test_top_level_equipment_page_loads(self) -> None:
        app = self._run("app_pages/functional_equipment.py")
        tab_labels = [tab.label for tab in app.tabs]
        self.assertIn("Equipment", tab_labels)
        self.assertIn("Layouts", tab_labels)
        self.assertIn("Project equipment", [item.value for item in app.subheader])

    def test_layouts_tab_renders_with_layout(self) -> None:
        from utils.layout_store import create_layout, create_layout_revision
        from tests.test_layout_store import _create_test_image_file

        layout = create_layout(self.project_id, "Packaging Cell A", "Line A layout", "Layout Tester")
        img = _create_test_image_file(width=1000, height=400)
        create_layout_revision(
            project_id=self.project_id,
            layout_id=layout["id"],
            image_file=img,
            width_value=80.0,
            height_value=32.0,
            unit="feet",
            notes="Rev 1 CAD floor plan",
            copy_from_revision_id=None,
            editor_name="Layout Tester",
        )

        app = self._run("app_pages/functional_equipment.py")
        self.assertEqual([], list(app.exception))
        metric_labels = [m.label for m in app.metric]
        self.assertIn("Physical Dimensions", metric_labels)
        self.assertIn("Image Resolution", metric_labels)
        self.assertIn("Layout Scale", metric_labels)

    def test_new_revision_auto_populates_on_screen(self) -> None:
        from utils.layout_store import create_layout, create_layout_revision
        from tests.test_layout_store import _create_test_image_file

        layout = create_layout(self.project_id, "Assembly Line B", "Line B layout", "Layout Tester")
        img1 = _create_test_image_file(width=1000, height=400)
        rev1 = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout["id"],
            image_file=img1,
            width_value=80.0,
            height_value=32.0,
            unit="feet",
            notes="Rev 1 CAD",
            editor_name="Layout Tester",
        )

        app = AppTest.from_file(REPO_ROOT / "app_pages/functional_equipment.py")
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Equipment page tester"
        app.run(timeout=30)
        self.assertEqual([], list(app.exception))

        # Check that Rev 1 was initially selected
        self.assertEqual(app.session_state["active_revision_id"], rev1["id"])

        # Create Revision 2 (as happens in the revision dialog)
        img2 = _create_test_image_file(width=1200, height=500)
        rev2 = create_layout_revision(
            project_id=self.project_id,
            layout_id=layout["id"],
            image_file=img2,
            width_value=120.0,
            height_value=50.0,
            unit="feet",
            notes="Rev 2 Updated line",
            editor_name="Layout Tester",
        )

        # Simulate the dialog saving Rev 2 and updating active_revision_id
        app.session_state["active_revision_id"] = rev2["id"]
        app.run(timeout=30)
        self.assertEqual([], list(app.exception))

        # Confirm that the app automatically synchronized layout_revision_selector and rendered Rev 2
        self.assertEqual(app.session_state["active_revision_id"], rev2["id"])
        self.assertEqual(app.session_state["layout_revision_selector"], rev2["id"])
        # And verify the dimension metric displays Rev 2's dimensions
        metric_values = [m.value for m in app.metric]
        self.assertIn("120 × 50 feet", metric_values)

    def test_quality_equipment_tab_lists_seeded_type_charts(self) -> None:
        app = self._run(
            "app_pages/functional_quality.py",
            f"quality_page_tabs_{self.project_id}",
        )
        tab_labels = [tab.label for tab in app.tabs]
        self.assertIn("All equipment", tab_labels)
        self.assertIn("Torque tool", tab_labels)
        self.assertIn("ESD equipment", tab_labels)
        self.assertIn("Vision equipment", tab_labels)
        self.assertIn("Scan/Compare equipment", tab_labels)
        self.assertIn("Test equipment", tab_labels)
        self.assertNotIn("Conveyor", tab_labels)

    def test_other_functional_review_equipment_tabs_load(self) -> None:
        cases = [
            ("app_pages/functional_ergonomics.py", f"ergonomics_page_tabs_{self.project_id}"),
            ("app_pages/functional_safety.py", f"safety_page_tabs_{self.project_id}"),
            ("app_pages/functional_materials.py", f"materials_page_tabs_{self.project_id}"),
        ]
        for path, key in cases:
            with self.subTest(path=path):
                app = self._run(path, key)
                self.assertIn("All equipment", [tab.label for tab in app.tabs])


if __name__ == "__main__":
    unittest.main()
