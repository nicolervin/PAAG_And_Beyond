from __future__ import annotations

import unittest
from contextlib import nullcontext
from unittest.mock import patch

from utils import store


class PlanningScenarioTableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.existing = [
            {
                "id": "scenario-1",
                "name": "Current plan",
                "revision_label": "1",
            }
        ]

    def test_new_row_clones_current_scenario_and_existing_row_updates(self) -> None:
        records = [
            {
                "id": "scenario-1",
                "name": "Current plan",
                "revision_label": "1",
                "status": "Frozen",
                "takt_time_s": 60,
                "change_summary": "Saved baseline",
            },
            {
                "id": "",
                "name": "Higher demand",
                "revision_label": "2",
                "status": "Working",
                "takt_time_s": 54,
                "change_summary": "Faster takt",
            },
        ]

        transaction = object()
        with (
            patch.object(store, "planning_scenarios", return_value=self.existing),
            patch.object(store, "connection", return_value=nullcontext(transaction)),
            patch.object(store, "update_planning_scenario") as update,
            patch.object(store, "clone_planning_scenario", return_value="scenario-2") as clone,
        ):
            result = store.save_planning_scenario_rows(
                "project-1", "scenario-1", records, "Nicole"
            )

        update.assert_called_once_with(
            "project-1", "scenario-1",
            records[0] | {"takt_time_s": 60.0, "takt_time_unit": "seconds"},
            _conn=transaction,
        )
        clone.assert_called_once_with(
            "project-1", "scenario-1", "Higher demand", "2", 54.0,
            "Faster takt", "Nicole", takt_time_unit="seconds", _conn=transaction,
        )
        self.assertEqual(result["created_ids"], ["scenario-2"])
        self.assertEqual(result["updated_count"], 1)

    def test_duplicate_names_fail_before_any_write(self) -> None:
        records = [
            {
                "id": "scenario-1",
                "name": "Current plan",
                "revision_label": "1",
                "status": "Working",
                "takt_time_s": 60,
            },
            {
                "id": "",
                "name": "current PLAN",
                "revision_label": "2",
                "status": "Working",
                "takt_time_s": 55,
            },
        ]

        with (
            patch.object(store, "planning_scenarios", return_value=self.existing),
            patch.object(store, "update_planning_scenario") as update,
            patch.object(store, "clone_planning_scenario") as clone,
        ):
            with self.assertRaisesRegex(ValueError, "names must be unique"):
                store.save_planning_scenario_rows(
                    "project-1", "scenario-1", records, "Nicole"
                )

        update.assert_not_called()
        clone.assert_not_called()


class WorkspacePersistenceTests(unittest.TestCase):
    def test_set_and_get_last_active_workspace_persists_across_reads(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            orig_db_path = store.DB_PATH
            try:
                store.DB_PATH = Path(tmp_dir) / "workspace_test.db"
                self.assertEqual(
                    store.get_last_active_workspace(),
                    {"project_id": None, "scenario_id": None},
                )
                store.set_last_active_workspace("proj-2", "scen-2")
                self.assertEqual(
                    store.get_last_active_workspace(),
                    {"project_id": "proj-2", "scenario_id": "scen-2"},
                )
                store.set_last_active_workspace(None, "scen-2")
                self.assertEqual(
                    store.get_last_active_workspace(),
                    {"project_id": None, "scenario_id": None},
                )
            finally:
                store.DB_PATH = orig_db_path

    def test_app_reload_restores_last_active_project_instead_of_first_project(self) -> None:
        import tempfile
        from pathlib import Path
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmp_dir:
            orig_db_path = store.DB_PATH
            try:
                store.DB_PATH = Path(tmp_dir) / "reload_test.db"
                store.init_db()
                older_id = store.create_project(
                    "Older Project",
                    "Prog B",
                    "Owner",
                    60.0,
                    product_line="Line 2",
                    building_location="Plant 2",
                )
                top_id = store.create_project(
                    "Top Project",
                    "Prog A",
                    "Owner",
                    60.0,
                    product_line="Line 1",
                    building_location="Plant 1",
                )
                # Ensure "Top Project" is first in projects() order
                with store.connection() as conn:
                    conn.execute(
                        "UPDATE projects SET updated_at='2099-01-02T00:00:00Z' WHERE id=?",
                        (top_id,),
                    )
                    conn.execute(
                        "UPDATE projects SET updated_at='2099-01-01T00:00:00Z' WHERE id=?",
                        (older_id,),
                    )
                self.assertEqual(store.projects()[0]["id"], top_id)

                app_script = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")

                # User selects Older Project in first session
                at1 = AppTest.from_file(app_script)
                at1.run(timeout=30)
                self.assertFalse(at1.exception)
                at1.sidebar.selectbox(key="global_project").select("Older Project").run(timeout=30)
                self.assertFalse(at1.exception)
                self.assertEqual(at1.session_state["project_id"], older_id)

                # Simulate browser refresh (brand new AppTest session with empty session_state)
                at2 = AppTest.from_file(app_script)
                at2.run(timeout=30)
                self.assertFalse(at2.exception)
                self.assertEqual(at2.session_state["project_id"], older_id)
                self.assertEqual(at2.sidebar.selectbox(key="global_project").value, "Older Project")
            finally:
                store.DB_PATH = orig_db_path


class NavigationTableViewTests(unittest.TestCase):
    def test_parts_catalog_loads_saved_table_view_after_switching_from_model_tree(self) -> None:
        import hashlib
        import tempfile
        from pathlib import Path
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmp_dir:
            orig_db_path = store.DB_PATH
            try:
                store.DB_PATH = Path(tmp_dir) / "parts_view_nav_test.db"
                store.init_db()
                project_id = store.create_project(
                    "Dryer NPI",
                    "Prog Dryer",
                    "Kayla Funk",
                    60.0,
                    product_line="Dryers",
                    building_location="AP3",
                )
                saved_cols = ["part_number", "subsystem", "feature_applicability"]
                store.set_last_active_workspace(project_id, None)
                store.save_table_view_preference(
                    project_id,
                    "Kayla Funk",
                    "parts_catalog",
                    saved_cols,
                    saved_cols,
                )

                app_script = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")
                at = AppTest.from_file(app_script, default_timeout=30)
                at.run(timeout=30)
                self.assertFalse(at.exception)
                self.assertEqual(at.session_state["current_editor"], "Kayla Funk")

                # Navigate into Model Tree first, then leave and navigate to Parts Catalog
                at.switch_page("app_pages/bom_tree.py").run(timeout=30)
                self.assertFalse(at.exception)
                self.assertEqual(at.session_state["current_editor"], "Kayla Funk")

                at.switch_page("app_pages/parts.py").run(timeout=30)
                self.assertFalse(at.exception)
                self.assertEqual(at.session_state["current_editor"], "Kayla Funk")

                editor_scope = hashlib.sha256("Kayla Funk".encode("utf-8")).hexdigest()[:12]
                view_key = f"parts_catalog_view_columns_{project_id}_{editor_scope}"
                self.assertEqual(at.multiselect(key=view_key).value, saved_cols)

                # Change draft columns without saving, leave to Model Tree, and return to Parts Catalog
                at.multiselect(key=view_key).set_value(["part_number", "description"]).run(timeout=30)
                self.assertEqual(at.multiselect(key=view_key).value, ["part_number", "description"])

                at.switch_page("app_pages/bom_tree.py").run(timeout=30)
                self.assertFalse(at.exception)

                at.switch_page("app_pages/parts.py").run(timeout=30)
                self.assertFalse(at.exception)
                self.assertEqual(at.session_state["current_editor"], "Kayla Funk")
                self.assertEqual(at.multiselect(key=view_key).value, saved_cols)
            finally:
                store.DB_PATH = orig_db_path


if __name__ == "__main__":
    unittest.main()
