from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import utils.db_core as db_core
from utils import store
from utils.help_hub import (
    PAGE_MANUALS,
    _build_critical_thread_flowchart_html,
    decode_operation_or_pitch_id,
    resolve_manual_key,
)
from utils.store import (
    add_assembly_section,
    create_app_feedback,
    create_project,
    critical_thread_status_counts,
    delete_app_feedback,
    global_project_search,
    init_db,
    list_app_feedback,
    list_recycle_bin_items,
    open_app_feedback_count,
    planning_scenarios,
    recycle_bin_item_count,
    restore_recycle_bin_items,
    save_bulk_app_feedback,
    update_app_feedback,
    upsert_part,
)


class HelpHubTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.db_path = self.tmp_path / "test_paag.db"
        self.upload_dir = self.tmp_path / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self._db_patch = patch.object(store, "DB_PATH", self.db_path)
        self._upload_patch = patch.object(store, "UPLOAD_DIR", self.upload_dir)
        self._db_patch.start()
        self._upload_patch.start()
        db_core._DB_INITIALIZED_KEY = None
        init_db()

    def tearDown(self) -> None:
        self._db_patch.stop()
        self._upload_patch.stop()
        self._tmpdir.cleanup()

    def test_app_feedback_crud_and_recycle_bin_restore(self) -> None:
        proj_id = create_project("Feedback Project", "FP-01", "Alice", 55.0)
        scen_rows = planning_scenarios(proj_id)
        scen_id = str(scen_rows[0]["id"])

        fb_id = create_app_feedback(
            project_id=proj_id,
            scenario_id=scen_id,
            page_context="Yamazumi",
            feedback_type="Bug report",
            severity="High",
            title="Board scroll jumps on drag",
            description="Dragging an element down a tall pitch column resets scroll.",
            steps_to_reproduce="1. Open Yamazumi\n2. Drag card",
            submitted_by="Alice",
        )
        self.assertTrue(fb_id)
        self.assertEqual(open_app_feedback_count(proj_id), 1)

        fb_df = list_app_feedback(proj_id)
        self.assertEqual(len(fb_df), 1)
        self.assertEqual(fb_df.iloc[0]["title"], "Board scroll jumps on drag")
        self.assertEqual(fb_df.iloc[0]["status"], "Open")

        # Update status via bulk save
        edited = fb_df.copy()
        edited.loc[0, "status"] = "Resolved"
        edited.loc[0, "resolution_notes"] = "Fixed scroll container anchor"
        changed = save_bulk_app_feedback(
            edited, active_project_id=proj_id, editor_name="Alice"
        )
        self.assertEqual(changed, 1)
        self.assertEqual(open_app_feedback_count(proj_id), 0)

        # Delete to Recycle Bin and restore
        deleted_count = delete_app_feedback(
            [fb_id], active_project_id=proj_id, editor_name="Alice"
        )
        self.assertEqual(deleted_count, 1)
        self.assertEqual(len(list_app_feedback(proj_id)), 0)
        self.assertEqual(recycle_bin_item_count(proj_id), 1)

        rb_items = list_recycle_bin_items(proj_id)
        self.assertEqual(rb_items.iloc[0]["entity_type"], "Bug report")
        bin_id = str(rb_items.iloc[0]["id"])

        restored = restore_recycle_bin_items([bin_id], "Alice")
        self.assertEqual(restored["restored_count"], 1)
        restored_df = list_app_feedback(proj_id)
        self.assertEqual(len(restored_df), 1)
        self.assertEqual(
            restored_df.iloc[0]["resolution_notes"],
            "Fixed scroll container anchor",
        )

    def test_global_project_search_and_critical_thread_counts(self) -> None:
        proj_id = create_project("Search Project", "SP-01", "Bob", 45.0)
        scen_rows = planning_scenarios(proj_id)
        scen_id = str(scen_rows[0]["id"])

        upsert_part(
            proj_id,
            {
                "part_number": "MTR-9988",
                "description": "Brushless drive motor assembly",
                "quantity": 1,
            },
        )
        add_assembly_section(
            proj_id, "Drive Housing Assembly", "Assembly", None, "Builds drive unit"
        )
        create_app_feedback(
            project_id=proj_id,
            scenario_id=scen_id,
            page_context="Parts Catalog",
            feedback_type="Feature suggestion",
            severity="Low",
            title="Highlight brushless motor parts",
            description="Add quick filter preset for motor components.",
            submitted_by="Bob",
        )

        results = global_project_search(proj_id, scen_id, "brushless")
        self.assertGreaterEqual(len(results), 2)
        categories = set(results["category"].tolist())
        self.assertIn("Parts Catalog", categories)
        self.assertIn("App Feedback", categories)

        fb_results = global_project_search(proj_id, scen_id, "Drive Housing")
        self.assertEqual(len(fb_results), 1)
        self.assertEqual(fb_results.iloc[0]["category"], "Fishbone")
        self.assertEqual(fb_results.iloc[0]["page_url_path"], "fishbone")

        steps = critical_thread_status_counts(proj_id, scen_id)
        self.assertEqual(len(steps), 8)
        step_by_num = {s["step_number"]: s for s in steps}
        self.assertTrue(step_by_num[4]["populated"])  # Parts Catalog
        self.assertTrue(step_by_num[5]["populated"])  # Fishbone

        flowchart_html = _build_critical_thread_flowchart_html(steps, "fishbone")
        self.assertIn("STEP 1", flowchart_html)
        self.assertIn("STEP 8", flowchart_html)
        self.assertIn("★ You are here", flowchart_html)
        self.assertIn("1 catalog parts", flowchart_html)

    def test_op_id_decoder_and_manual_resolution(self) -> None:
        self.assertEqual(resolve_manual_key("__default__"), "overview")
        self.assertEqual(resolve_manual_key("Equipment"), "functional_equipment")
        self.assertEqual(resolve_manual_key("yamazumi"), "yamazumi")
        self.assertGreaterEqual(len(PAGE_MANUALS), 17)

        decoded_op = decode_operation_or_pitch_id("M1S1b.01-ML1-004.4")
        self.assertTrue(decoded_op["valid"])
        self.assertTrue(decoded_op["is_guided_pitch"])
        self.assertTrue(decoded_op["is_full_op_id"])
        self.assertEqual(len(decoded_op["segments"]), 5)
        self.assertEqual(decoded_op["segments"][0]["segment"], "M1S1b")
        self.assertEqual(decoded_op["segments"][1]["segment"], "01")
        self.assertEqual(decoded_op["segments"][2]["segment"], "ML1")
        self.assertEqual(decoded_op["segments"][3]["segment"], "004")
        self.assertEqual(decoded_op["segments"][4]["segment"], ".4")

        decoded_pitch = decode_operation_or_pitch_id("01-SUB-012")
        self.assertTrue(decoded_pitch["valid"])
        self.assertTrue(decoded_pitch["is_guided_pitch"])
        self.assertFalse(decoded_pitch["is_full_op_id"])
        self.assertEqual(len(decoded_pitch["segments"]), 3)


if __name__ == "__main__":
    unittest.main()
