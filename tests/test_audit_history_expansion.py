from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pandas as pd
import streamlit as st

from utils import ergonomics_store, safety_store, store
from utils.table_ui import count_table_create_and_edit_rows, render_audit_history_table


class AuditHistoryExpansionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_audit_history_expansion_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        scenarios = store.planning_scenarios(self.project_id)
        self.scenario_id = str(scenarios[0]["id"])

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_create_only_populates_create_new_and_leaves_edit_existing_empty(self) -> None:
        store.record_audit_event(
            self.project_id,
            "Parts",
            "Save & Refresh",
            3,
            "Alice",
            {"created_count": 3, "updated_count": 0},
        )
        hist = store.audit_history(self.project_id, "Parts", limit=10)
        self.assertEqual(len(hist), 1)
        row = hist.iloc[0]
        self.assertEqual(row["create_new_rows"], "3")
        self.assertEqual(row["create_new_user"], "Alice")
        self.assertTrue(bool(str(row["create_new_at"]).strip()))
        self.assertEqual(row["edit_existing_rows"], "")
        self.assertEqual(row["edit_existing_user"], "")
        self.assertEqual(row["edit_existing_at"], "")

    def test_edit_only_populates_edit_existing_and_leaves_create_new_empty(self) -> None:
        store.record_audit_event(
            self.project_id,
            "Parts",
            "Save & Refresh",
            2,
            "Bob",
            {"created_count": 0, "updated_count": 2},
        )
        hist = store.audit_history(self.project_id, "Parts", limit=10)
        self.assertEqual(len(hist), 1)
        row = hist.iloc[0]
        self.assertEqual(row["create_new_rows"], "")
        self.assertEqual(row["create_new_user"], "")
        self.assertEqual(row["create_new_at"], "")
        self.assertEqual(row["edit_existing_rows"], "2")
        self.assertEqual(row["edit_existing_user"], "Bob")
        self.assertTrue(bool(str(row["edit_existing_at"]).strip()))

    def test_mixed_save_splits_into_two_separate_history_rows(self) -> None:
        store.record_audit_event(
            self.project_id,
            "Concerns",
            "Save & Refresh",
            5,
            "Dana",
            {"created_count": 2, "updated_count": 3},
        )
        hist = store.audit_history(self.project_id, "Concerns", limit=10)
        self.assertEqual(len(hist), 2)

        create_rows = hist[hist["create_new_rows"] != ""]
        edit_rows = hist[hist["edit_existing_rows"] != ""]
        self.assertEqual(len(create_rows), 1)
        self.assertEqual(len(edit_rows), 1)

        c_row = create_rows.iloc[0]
        self.assertEqual(int(c_row["row_count"]), 2)
        self.assertEqual(c_row["create_new_rows"], "2")
        self.assertEqual(c_row["create_new_user"], "Dana")
        self.assertTrue(bool(str(c_row["create_new_at"]).strip()))
        self.assertEqual(c_row["edit_existing_rows"], "")
        self.assertEqual(c_row["edit_existing_user"], "")
        self.assertEqual(c_row["edit_existing_at"], "")

        e_row = edit_rows.iloc[0]
        self.assertEqual(int(e_row["row_count"]), 3)
        self.assertEqual(e_row["edit_existing_rows"], "3")
        self.assertEqual(e_row["edit_existing_user"], "Dana")
        self.assertTrue(bool(str(e_row["edit_existing_at"]).strip()))
        self.assertEqual(e_row["create_new_rows"], "")
        self.assertEqual(e_row["create_new_user"], "")
        self.assertEqual(e_row["create_new_at"], "")

    def test_delete_action_leaves_create_new_and_edit_existing_empty(self) -> None:
        store.record_audit_event(
            self.project_id,
            "Parts",
            "Bulk delete",
            4,
            "Charlie",
        )
        hist = store.audit_history(self.project_id, "Parts", limit=10)
        self.assertEqual(len(hist), 1)
        row = hist.iloc[0]
        self.assertEqual(row["action"], "Bulk delete")
        self.assertEqual(int(row["row_count"]), 4)
        self.assertEqual(row["editor_name"], "Charlie")
        self.assertEqual(row["create_new_rows"], "")
        self.assertEqual(row["create_new_user"], "")
        self.assertEqual(row["create_new_at"], "")
        self.assertEqual(row["edit_existing_rows"], "")
        self.assertEqual(row["edit_existing_user"], "")
        self.assertEqual(row["edit_existing_at"], "")

    def test_sections_remain_strictly_separate(self) -> None:
        store.record_audit_event(
            self.project_id,
            "Parts",
            "Save & Refresh",
            1,
            "Alice",
            {"created_count": 1, "updated_count": 0},
        )
        store.record_audit_event(
            self.project_id,
            "PFMEA",
            "Save & Refresh",
            2,
            "Bob",
            {"created_count": 0, "updated_count": 2},
        )
        parts_hist = store.audit_history(self.project_id, "Parts", limit=10)
        pfmea_hist = store.audit_history(self.project_id, "PFMEA", limit=10)
        self.assertEqual(len(parts_hist), 1)
        self.assertEqual(parts_hist.iloc[0]["editor_name"], "Alice")
        self.assertEqual(len(pfmea_hist), 1)
        self.assertEqual(pfmea_hist.iloc[0]["editor_name"], "Bob")

    def test_count_table_create_and_edit_rows_ignores_untouched_rows(self) -> None:
        before_df = pd.DataFrame(
            [
                {"id": "row-1", "name": "Pump", "qty": 1.0},
                {"id": "row-2", "name": "Valve", "qty": 2.0},
            ]
        )
        after_df = pd.DataFrame(
            [
                {"id": "row-1", "name": "Pump", "qty": 1.0},  # untouched
                {"id": "row-2", "name": "Valve XL", "qty": 2.0},  # modified
                {"id": "", "name": "Hose", "qty": 4.0},  # new row
            ]
        )
        created_count, updated_count = count_table_create_and_edit_rows(
            before_df,
            after_df,
            compare_columns=["name", "qty"],
        )
        self.assertEqual(created_count, 1)
        self.assertEqual(updated_count, 1)

    def test_render_audit_history_table_hides_and_expands_columns(self) -> None:
        store.record_audit_event(
            self.project_id,
            "Parts",
            "Save & Refresh",
            2,
            "Alice",
            {"created_count": 2, "updated_count": 0},
        )
        hist = store.audit_history(self.project_id, "Parts", limit=10).drop(
            columns=["details"], errors="ignore"
        )
        captured_frames: list[pd.DataFrame] = []

        def fake_dataframe(data, **kwargs):
            captured_frames.append(data.copy())
            return None

        fake_state: dict[str, object] = {}
        with patch.object(st, "session_state", fake_state), patch.object(
            st, "dataframe", side_effect=fake_dataframe
        ), patch.object(st, "button", return_value=False):
            render_audit_history_table(hist, key="test_hist_key")

        self.assertEqual(len(captured_frames), 1)
        collapsed_cols = list(captured_frames[0].columns)
        self.assertEqual(collapsed_cols, ["action", "row_count", "editor_name", "created_at"])

        captured_frames.clear()
        fake_state["_audit_history_expanded_test_hist_key"] = True
        with patch.object(st, "session_state", fake_state), patch.object(
            st, "dataframe", side_effect=fake_dataframe
        ), patch.object(st, "button", return_value=False):
            render_audit_history_table(hist, key="test_hist_key")

        self.assertEqual(len(captured_frames), 1)
        expanded_cols = list(captured_frames[0].columns)
        self.assertEqual(
            expanded_cols,
            [
                "action",
                "row_count",
                "editor_name",
                "created_at",
                "create_new_rows",
                "create_new_user",
                "create_new_at",
                "edit_existing_rows",
                "edit_existing_user",
                "edit_existing_at",
            ],
        )
        st.session_state.pop("test_hist_key_show_create_edit_details", None)

    def test_ergonomics_and_safety_history_include_expansion_columns(self) -> None:
        store.record_audit_event(
            self.project_id,
            "Ergonomics reviews",
            "Save & Refresh",
            3,
            "ErgoUser",
            {
                "scenario_id": self.scenario_id,
                "created_ids": ["e-1"],
                "updated_ids": ["e-2", "e-3"],
            },
        )
        ergo_hist = ergonomics_store.ergonomics_review_audit_history(
            self.project_id, self.scenario_id, limit=10
        )
        self.assertEqual(len(ergo_hist), 2)
        self.assertIn("create_new_rows", ergo_hist.columns)
        self.assertIn("edit_existing_rows", ergo_hist.columns)

        store.record_audit_event(
            self.project_id,
            "Safety requirements",
            "Save & Refresh",
            1,
            "SafetyUser",
            {
                "scenario_id": self.scenario_id,
                "created_ids": ["s-1"],
                "updated_ids": [],
            },
        )
        safety_hist = safety_store.safety_requirement_history(
            self.project_id, self.scenario_id, limit=10
        )
        self.assertEqual(len(safety_hist), 1)
        self.assertEqual(safety_hist.iloc[0]["create_new_rows"], "1")
        self.assertEqual(safety_hist.iloc[0]["create_new_user"], "SafetyUser")
        self.assertEqual(safety_hist.iloc[0]["edit_existing_rows"], "")


if __name__ == "__main__":
    unittest.main()
