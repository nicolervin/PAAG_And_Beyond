from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

import utils.db_core as db_core
from utils import store
from utils.store import (
    add_assembly_section,
    connection,
    create_project,
    delete_assembly_sections,
    delete_project,
    delete_project_part,
    get_project,
    init_db,
    list_recycle_bin_items,
    permanently_delete_recycle_bin_items,
    planning_scenarios,
    project_table,
    purge_expired_recycle_bin_items,
    recycle_bin_item_count,
    replace_concerns,
    restore_recycle_bin_items,
    save_assembly_section_connection,
    upsert_part,
)


class RecycleBinTests(unittest.TestCase):
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

    def test_delete_and_restore_part(self) -> None:
        proj_id = create_project("Test Project", "P-100", "Tester", 60.0)
        part_id = upsert_part(
            proj_id,
            {
                "part_number": "PN-001",
                "description": "Test bracket",
                "quantity": 1,
            },
        )
        self.assertEqual(len(project_table("parts", proj_id)), 1)
        self.assertEqual(recycle_bin_item_count(proj_id), 0)

        delete_project_part(proj_id, part_id)
        self.assertEqual(len(project_table("parts", proj_id)), 0)
        self.assertEqual(recycle_bin_item_count(proj_id), 1)

        items = list_recycle_bin_items(proj_id)
        self.assertEqual(len(items), 1)
        self.assertEqual(items.iloc[0]["entity_type"], "Part")
        self.assertEqual(items.iloc[0]["project_name"], "Test Project")
        self.assertEqual(items.iloc[0]["scenario_name"], "All scenarios")
        bin_id = str(items.iloc[0]["id"])

        restored = restore_recycle_bin_items([bin_id], "Tester")
        self.assertEqual(restored["restored_count"], 1)
        self.assertEqual(recycle_bin_item_count(proj_id), 0)
        parts_df = project_table("parts", proj_id)
        self.assertEqual(len(parts_df), 1)
        self.assertEqual(parts_df.iloc[0]["part_number"], "PN-001")

    def test_delete_and_restore_fishbone_section_reverses_healed_connection(self) -> None:
        proj_id = create_project("Fishbone Project", "P-200", "Tester", 60.0)
        sec_a = add_assembly_section(proj_id, "Sec A", "Assembly", None, "")
        sec_b = add_assembly_section(proj_id, "Sec B", "Assembly", None, "")
        sec_c = add_assembly_section(proj_id, "Sec C", "Assembly", None, "")
        save_assembly_section_connection(proj_id, sec_a, sec_b, "series", 10, "Tester")
        save_assembly_section_connection(proj_id, sec_b, sec_c, "series", 20, "Tester")

        # Deleting Sec B deletes (A->B) and (B->C) and inserts healed connection (A->C)
        delete_assembly_sections(proj_id, [sec_b], target_section_id=sec_c)
        self.assertEqual(recycle_bin_item_count(proj_id), 1)

        items = list_recycle_bin_items(proj_id)
        bin_id = str(items.iloc[0]["id"])
        restore_recycle_bin_items([bin_id], "Tester")

        with connection() as conn:
            conns = conn.execute(
                "SELECT from_section_id, to_section_id FROM assembly_section_connections WHERE project_id = ?",
                (proj_id,),
            ).fetchall()
            pairs = {(r["from_section_id"], r["to_section_id"]) for r in conns}
        self.assertEqual(pairs, {(sec_a, sec_b), (sec_b, sec_c)})

    def test_delete_and_restore_entire_project(self) -> None:
        proj_id = create_project("Full Project", "P-300", "Tester", 60.0)
        upsert_part(proj_id, {"part_number": "PN-99", "description": "Motor", "quantity": 1})
        replace_concerns(
            proj_id,
            pd.DataFrame(
                [
                    {
                        "id": "",
                        "title": "Clearance check",
                        "category": "Assembly",
                        "priority": "High",
                        "owner": "Tester",
                        "status": "Open",
                        "target_date": "",
                        "resolution_notes": "",
                    }
                ]
            ),
        )
        delete_project(proj_id, "Tester")
        self.assertIsNone(get_project(proj_id))
        self.assertEqual(recycle_bin_item_count(None), 1)

        items = list_recycle_bin_items(None)
        bin_id = str(items.iloc[0]["id"])
        restore_recycle_bin_items([bin_id], "Tester")

        self.assertIsNotNone(get_project(proj_id))
        self.assertEqual(len(project_table("parts", proj_id)), 1)

    def test_expiry_and_permanent_delete(self) -> None:
        proj_id = create_project("Purge Project", "P-400", "Tester", 60.0)
        p1 = upsert_part(proj_id, {"part_number": "PN-1", "description": "Part 1", "quantity": 1})
        p2 = upsert_part(proj_id, {"part_number": "PN-2", "description": "Part 2", "quantity": 1})
        delete_project_part(proj_id, p1)
        delete_project_part(proj_id, p2)
        self.assertEqual(recycle_bin_item_count(proj_id), 2)

        items = list_recycle_bin_items(proj_id)
        first_bin_id = str(items.iloc[0]["id"])
        permanently_delete_recycle_bin_items([first_bin_id], "Tester")
        self.assertEqual(recycle_bin_item_count(proj_id), 1)

        # Backdate remaining item's expires_at into the past and verify auto-purge
        past_iso = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        with connection() as conn:
            conn.execute("UPDATE recycle_bin_items SET expires_at = ?", (past_iso,))
            purged = purge_expired_recycle_bin_items(conn)
        self.assertEqual(purged, 1)
        self.assertEqual(recycle_bin_item_count(proj_id), 0)

    def test_recycle_bin_page_apptest_smoke(self) -> None:
        proj_id = create_project("UI Project", "P-500", "Tester", 60.0)
        scens = planning_scenarios(proj_id)
        scen_id = str(scens[0]["id"]) if scens else None
        p1 = upsert_part(proj_id, {"part_number": "PN-UI", "description": "UI Part", "quantity": 1})
        delete_project_part(proj_id, p1)

        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app_pages" / "recycle_bin.py"))
        at.session_state["project_id"] = proj_id
        if scen_id:
            at.session_state["scenario_id"] = scen_id
        at.session_state["current_editor"] = "Tester"
        at.run(timeout=15)
        self.assertEqual(len(at.exception), 0, f"AppTest exception: {at.exception}")
        button_labels = [btn.label for btn in at.button]
        self.assertIn("Restore selected", button_labels)
        self.assertIn("Delete permanently", button_labels)
        self.assertNotIn("Empty recycle bin", button_labels)

    def test_eastern_time_timestamps(self) -> None:
        from utils.store import (
            audit_history,
            format_eastern_timestamp,
            now_iso,
            record_audit_event,
            to_eastern_iso,
        )

        iso_now = now_iso()
        self.assertTrue(
            iso_now.endswith("-04:00") or iso_now.endswith("-05:00"),
            f"Expected Eastern Time offset in now_iso(), got {iso_now}",
        )
        self.assertEqual(
            to_eastern_iso("2026-07-15T16:30:00+00:00"),
            "2026-07-15T12:30:00-04:00",
        )
        self.assertEqual(
            format_eastern_timestamp("2026-01-15T16:30:00+00:00"),
            "Jan 15, 2026 11:30",
        )
        proj_id = create_project("ET Project", "P-600", "Tester", 60.0)
        record_audit_event(proj_id, "Projects", "Create project", 1, "Tester", {})
        hist = audit_history(proj_id, "Projects", limit=5)
        self.assertFalse(hist.empty)
        created_val = str(hist.iloc[0]["created_at"])
        self.assertTrue(
            created_val.endswith("-04:00") or created_val.endswith("-05:00"),
            f"Expected Eastern Time offset in audit_history, got {created_val}",
        )

    def test_concerns_fields_and_resolved_validation(self) -> None:
        proj_id = create_project("Concerns Project", "P-700", "Tester", 60.0)
        scens = planning_scenarios(proj_id)
        scen_id = str(scens[0]["id"]) if scens else None

        # 1. Resolved without resolution_comments must raise ValueError
        with self.assertRaisesRegex(ValueError, "Resolution comments are required"):
            replace_concerns(
                proj_id,
                pd.DataFrame(
                    [
                        {
                            "id": "",
                            "category": "Quality",
                            "detail": "Check torque tolerance",
                            "owner": "AQE",
                            "priority": "High",
                            "status": "Resolved",
                            "comments": "Needs verification",
                            "resolution_comments": "",
                            "submitted_by": "",
                        }
                    ]
                ),
                editor_name="Alice",
            )

        # 2. Save Open concern and verify submitted_by defaults to editor_name
        replace_concerns(
            proj_id,
            pd.DataFrame(
                [
                    {
                        "id": "",
                        "category": "Quality",
                        "detail": "Check torque tolerance",
                        "owner": "AQE",
                        "priority": "High",
                        "status": "Open",
                        "comments": "Needs verification",
                        "resolution_comments": "",
                        "submitted_by": "",
                    }
                ]
            ),
            editor_name="Alice",
        )
        saved = project_table("concerns", proj_id)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved.iloc[0]["detail"], "Check torque tolerance")
        self.assertEqual(saved.iloc[0]["category"], "Quality")
        self.assertEqual(saved.iloc[0]["comments"], "Needs verification")
        self.assertEqual(saved.iloc[0]["submitted_by"], "Alice")
        self.assertTrue(bool(str(saved.iloc[0]["updated_at"]).strip()))

        # 3. Resolve with resolution_comments succeeds
        saved_df = saved.copy()
        saved_df.loc[0, "status"] = "Resolved"
        saved_df.loc[0, "resolution_comments"] = "Verified torque spec 12 Nm"
        replace_concerns(proj_id, saved_df, editor_name="Bob")
        resolved_df = project_table("concerns", proj_id)
        self.assertEqual(resolved_df.iloc[0]["status"], "Resolved")
        self.assertEqual(resolved_df.iloc[0]["resolution_comments"], "Verified torque spec 12 Nm")
        self.assertEqual(resolved_df.iloc[0]["submitted_by"], "Alice")

        # 4. AppTest smoke check for app_pages/concerns.py
        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app_pages" / "concerns.py"))
        at.session_state["project_id"] = proj_id
        if scen_id:
            at.session_state["scenario_id"] = scen_id
        at.session_state["current_editor"] = "Alice"
        at.run(timeout=15)
        self.assertEqual(len(at.exception), 0, f"AppTest exception on concerns.py: {at.exception}")


if __name__ == "__main__":
    unittest.main()
