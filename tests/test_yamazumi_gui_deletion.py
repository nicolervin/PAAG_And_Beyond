from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from streamlit.testing.v1 import AppTest

from utils import store
from utils.yamazumi_stack import UNASSIGNED_STACK_ID


class YamazumiGuiDeletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_yamazumi_gui_delete_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])
        self.area_id = store.upsert_yamazumi_area(
            self.project_id, self.scenario_id, "GUI deletion area"
        )
        self.pitch_id = store.add_yamazumi_pitch(
            self.project_id, self.area_id, "P-GUI", "GUI pitch"
        )
        self.element_id = store.add_yamazumi_element(
            self.project_id,
            self.area_id,
            self.pitch_id,
            {
                "description": "GUI work element",
                "time_s": 5.0,
                "model_variants": ["Base"],
                "work_type": "Cycle",
                "work_region": "None",
            },
        )

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def run_page(self, *, pitch: bool = False, element: bool = False) -> AppTest:
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/yamazumi.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "GUI test editor"
        app.session_state[f"yamazumi_area_{self.scenario_id}"] = self.area_id
        if pitch:
            app.session_state[
                f"yamazumi_edit_pitch_target_{self.project_id}_{self.area_id}"
            ] = self.pitch_id
        if element:
            app.session_state[
                f"yamazumi_edit_element_target_{self.project_id}_{self.area_id}"
            ] = self.element_id
        with patch("utils.yamazumi_board.yamazumi_board", return_value=None):
            app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def rerun(self, element) -> AppTest:
        with patch("utils.yamazumi_board.yamazumi_board", return_value=None):
            app = element.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    @staticmethod
    def button(app: AppTest, label: str):
        for button in app.button:
            if button.label == label and str(button.key).startswith("destructive_gui_"):
                return button
        return next(button for button in app.button if button.label == label)

    def test_pitch_gui_cancel_restores_draft_and_confirm_unassigns(self) -> None:
        app = self.run_page(pitch=True)
        pitch_name = next(field for field in app.text_input if field.label == "Pitch Name")
        pitch_name.set_value("Unsaved pitch name")
        app = self.rerun(app)
        app = self.rerun(self.button(app, "Delete Pitch…").click())
        self.assertIsNotNone(self.button(app, "Delete Pitch"))

        app = self.rerun(self.button(app, "Cancel").click())
        restored_name = next(
            field for field in app.text_input if field.label == "Pitch Name"
        )
        self.assertEqual(restored_name.value, "Unsaved pitch name")

        app = self.rerun(self.button(app, "Delete Pitch…").click())
        self.rerun(self.button(app, "Delete Pitch").click())
        self.assertEqual(
            store.query("SELECT COUNT(*) AS count FROM yamazumi_pitches WHERE id=?", (self.pitch_id,))[0]["count"],
            0,
        )
        element = store.query(
            "SELECT pitch_id, process_sync_status FROM yamazumi_elements WHERE id=?",
            (self.element_id,),
        )[0]
        self.assertIsNone(element["pitch_id"])
        self.assertEqual(element["process_sync_status"], "Needs IE review")

    def test_element_gui_cancel_restores_draft_and_confirm_preserves_process(self) -> None:
        process_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, operation, updated_at)
                   VALUES (?, ?, ?, 10, 'Preserved process step', ?)""",
                (process_id, self.project_id, self.scenario_id, store.now_iso()),
            )
            conn.execute(
                "UPDATE yamazumi_elements SET process_element_id=? WHERE id=?",
                (process_id, self.element_id),
            )
        app = self.run_page(element=True)
        description = next(
            field for field in app.text_area if field.label == "Work Description"
        )
        description.set_value("Unsaved element description")
        self.assertIsNotNone(self.button(app, "Delete Work Element…"))
        pending_key = (
            f"yamazumi_gui_element_pending_delete_{self.project_id}_"
            f"{self.scenario_id}_{self.area_id}"
        )
        pending = {
            "id": self.element_id,
            "values": {
                "pitch_id": self.pitch_id,
                "description": "Unsaved element description",
                "time_s": 5.0,
                "model_variants": ["Base"],
                "work_type": "Cycle",
                "work_region": "None",
            },
        }
        app.session_state[pending_key] = pending
        app = self.rerun(app)
        self.assertTrue(
            any("will not be deleted" in info.value for info in app.info),
            [info.value for info in app.info],
        )

        app = self.rerun(self.button(app, "Cancel").click())
        restored_description = next(
            field for field in app.text_area if field.label == "Work Description"
        )
        self.assertEqual(restored_description.value, "Unsaved element description")

        app.session_state[pending_key] = pending
        app = self.rerun(app)
        self.rerun(self.button(app, "Delete Work Element").click())
        self.assertEqual(
            store.query("SELECT COUNT(*) AS count FROM yamazumi_elements WHERE id=?", (self.element_id,))[0]["count"],
            0,
        )
        self.assertEqual(
            store.query("SELECT COUNT(*) AS count FROM work_elements WHERE id=?", (process_id,))[0]["count"],
            1,
        )

    def test_gui_delete_requests_are_disabled_for_unsaved_board_moves(self) -> None:
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/yamazumi.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "GUI test editor"
        app.session_state[f"yamazumi_area_{self.scenario_id}"] = self.area_id
        app.session_state[
            f"yamazumi_board_draft_{self.project_id}_{self.scenario_id}_{self.area_id}"
        ] = {UNASSIGNED_STACK_ID: [self.element_id]}
        app.session_state[
            f"yamazumi_edit_element_target_{self.project_id}_{self.area_id}"
        ] = self.element_id
        with patch("utils.yamazumi_board.yamazumi_board", return_value=None):
            app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertTrue(self.button(app, "Delete Work Element…").disabled)
        self.assertTrue(
            any("Save & Refresh or Undo" in info.value for info in app.info)
        )

    def test_pitch_type_links_between_pitch_addresses_table_and_edit_pitch_dialog(self) -> None:
        app = self.run_page(pitch=True)
        pitch_type_select = next(
            sb for sb in app.selectbox if sb.key == f"edit_pitch_type_{self.pitch_id}"
        )
        self.assertEqual(pitch_type_select.value, "Pitch")

        # Close Edit Pitch dialog, then update Pitch Type in the Pitch Addresses table
        app = self.rerun(self.button(app, "Cancel").click())
        pitch_editor_key = f"yamazumi_pitch_editor_{self.scenario_id}_{self.area_id}"
        app.session_state[pitch_editor_key] = {
            "edited_rows": {0: {"pitch_type": "Waterspider"}},
            "added_rows": [],
            "deleted_rows": [],
        }
        # Re-open Edit Pitch from the interactive board and confirm it reflects the table's Pitch Type
        edit_pitch_key = f"yamazumi_edit_pitch_target_{self.project_id}_{self.area_id}"
        app.session_state[edit_pitch_key] = self.pitch_id
        app = self.rerun(app)
        pitch_type_select = next(
            sb for sb in app.selectbox if sb.key == f"edit_pitch_type_{self.pitch_id}"
        )
        self.assertEqual(pitch_type_select.value, "Waterspider")

        # Change Pitch Type in Edit Pitch dialog and save; confirm DB and table update
        pitch_type_select.select("Repacker")
        app = self.rerun(app)
        app = self.rerun(self.button(app, "Save Pitch").click())
        saved_pitch = store.query(
            "SELECT pitch_type FROM yamazumi_pitches WHERE id=?",
            (self.pitch_id,),
        )[0]
        self.assertEqual(saved_pitch["pitch_type"], "Repacker")


if __name__ == "__main__":
    unittest.main()
