from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pandas as pd
from streamlit.testing.v1 import AppTest

from utils import store


PAGE_PATH = store.ROOT / "app_pages" / "functional_ergonomics.py"


class ErgonomicsPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_ergonomics_page_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])
        self.work_element_id = "ergonomics-page-step"
        with store.connection() as conn:
            # Keep these page tests isolated from the sample Process steps and
            # their now-required automatically backfilled baseline reviews.
            conn.execute(
                "DELETE FROM ergonomics_reviews WHERE project_id=? AND scenario_id=?",
                (self.project_id, self.scenario_id),
            )
            conn.execute(
                "DELETE FROM work_elements WHERE project_id=? AND scenario_id=?",
                (self.project_id, self.scenario_id),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, updated_at)
                   VALUES (?, ?, ?, 900, 'P-900', 'Lift enclosure', ?)""",
                (
                    self.work_element_id,
                    self.project_id,
                    self.scenario_id,
                    store.now_iso(),
                ),
            )

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    @property
    def editor_key(self) -> str:
        return (
            f"ergonomics_reviews_editor_{self.project_id}_{self.scenario_id}"
            "__editor_instance_0"
        )

    def run_page(self, editor_state: dict | None = None) -> AppTest:
        app = AppTest.from_file(str(PAGE_PATH), default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "AppTest Ergonomist"
        if editor_state is not None:
            visible_ids = tuple(
                store.ergonomics_reviews(self.project_id, self.scenario_id)["id"]
                .fillna("")
                .astype(str)
            )
            app.session_state[
                f"ergonomics_reviews_filters_{self.project_id}_{self.scenario_id}"
                "_visible_rows"
            ] = visible_ids
            app.session_state[self.editor_key] = editor_state
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def save_button(self, app: AppTest):
        key = f"ergonomics_reviews_{self.project_id}_{self.scenario_id}_save_refresh"
        return next(button for button in app.button if button.key == key)

    def test_page_has_scenario_scope_unlinked_filter_and_direct_entry(self) -> None:
        store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {"notes": "Pre-PAAG concern"},
        )
        store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {"work_element_id": self.work_element_id},
        )
        app = self.run_page()
        self.assertTrue(any(title.value == "Ergonomics" for title in app.title))
        link_filter = next(
            widget for widget in app.multiselect if widget.label == "Link status"
        )
        self.assertEqual(set(link_filter.options), {"Linked", "Unlinked"})
        captions = " ".join(caption.value for caption in app.caption)
        self.assertIn("legacy item or pre-PAAG concern", captions)
        self.assertIn("Unlinked", captions)
        self.assertIn("non-production-intent part", captions)
        page_source = PAGE_PATH.read_text(encoding="utf-8")
        self.assertIn('st.column_config.SelectboxColumn(\n            "Risk classification"', page_source)
        self.assertIn("options=list(ERGONOMICS_RISK_CLASSIFICATIONS)", page_source)

    def test_page_displays_active_scenario_takt_time_with_frequency_help(self) -> None:
        with store.connection() as conn:
            conn.execute(
                "UPDATE planning_scenarios SET takt_time_s=? WHERE id=?",
                (47.5, self.scenario_id),
            )

        app = self.run_page()

        takt_metric = next(
            metric
            for metric in app.metric
            if metric.label == "Current scenario takt time"
        )
        self.assertEqual(takt_metric.value, "47.5 s")
        page_source = PAGE_PATH.read_text(encoding="utf-8")
        self.assertIn("frequency-driven ergonomic risk", page_source)

    def test_manual_unlinked_row_saves_with_current_editor_audit(self) -> None:
        app = self.run_page(
            {
                "edited_rows": {},
                "added_rows": [
                    {
                        "status": "Open",
                        "reviewer": "AppTest Ergonomist",
                        "notes": "Legacy lift concern",
                    }
                ],
                "deleted_rows": [],
            }
        )
        app = self.save_button(app).click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        saved = store.ergonomics_reviews(self.project_id, self.scenario_id)
        self.assertEqual(len(saved), 1)
        self.assertIsNone(saved.iloc[0]["work_element_id"])
        self.assertEqual(saved.iloc[0]["notes"], "Legacy lift concern")
        self.assertEqual(saved.iloc[0]["risk_classification"], "Not yet assessed")
        history = store.audit_history(
            self.project_id, "Ergonomics reviews", limit=10
        )
        self.assertEqual(history.iloc[0]["editor_name"], "AppTest Ergonomist")

    def test_risk_classification_edits_independently_from_status(self) -> None:
        review_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "work_element_id": self.work_element_id,
                "status": "Open",
            },
        )["id"]
        rows = store.ergonomics_reviews(self.project_id, self.scenario_id)
        position = int(rows.index[rows["id"].eq(review_id)][0])
        app = self.run_page(
            {
                "edited_rows": {
                    position: {"risk_classification": "Favorable Red"}
                },
                "added_rows": [],
                "deleted_rows": [],
            }
        )
        app = self.save_button(app).click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        saved = store.ergonomics_reviews(self.project_id, self.scenario_id).iloc[0]
        self.assertEqual(saved["status"], "Open")
        self.assertEqual(saved["risk_classification"], "Favorable Red")

    def test_ui_link_to_empty_placeholder_merges_without_dialog(self) -> None:
        placeholder_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {"work_element_id": self.work_element_id},
        )["id"]
        candidate_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {"status": "Open", "notes": "Keep this review"},
        )["id"]
        rows = store.ergonomics_reviews(self.project_id, self.scenario_id)
        candidate_position = int(rows.index[rows["id"].eq(candidate_id)][0])
        app = self.run_page(
            {
                "edited_rows": {
                    candidate_position: {"work_element_id": self.work_element_id}
                },
                "added_rows": [],
                "deleted_rows": [],
            }
        )
        app = self.save_button(app).click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        saved = store.ergonomics_reviews(self.project_id, self.scenario_id)
        self.assertEqual(list(saved["id"]), [candidate_id])
        self.assertNotIn(placeholder_id, set(saved["id"]))

    def test_ui_conflict_requires_survivor_and_applies_choice(self) -> None:
        target_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "work_element_id": self.work_element_id,
                "status": "Open",
                "notes": "Keep target content",
            },
        )["id"]
        candidate_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {"status": "Pending", "notes": "Candidate content"},
        )["id"]
        rows = store.ergonomics_reviews(self.project_id, self.scenario_id)
        candidate_position = int(rows.index[rows["id"].eq(candidate_id)][0])
        app = self.run_page(
            {
                "edited_rows": {
                    candidate_position: {"work_element_id": self.work_element_id}
                },
                "added_rows": [],
                "deleted_rows": [],
            }
        )
        app = self.save_button(app).click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        survivor = next(radio for radio in app.radio if radio.label == "Review to keep")
        self.assertIsNone(survivor.value)
        merge_button = next(
            button for button in app.button if button.label == "Merge and save"
        )
        self.assertTrue(merge_button.disabled)
        app = survivor.set_value(target_id).run(timeout=30)
        merge_button = next(
            button for button in app.button if button.label == "Merge and save"
        )
        app = merge_button.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        saved = store.ergonomics_reviews(self.project_id, self.scenario_id)
        self.assertEqual(list(saved["id"]), [target_id])
        self.assertEqual(saved.iloc[0]["notes"], "Keep target content")

    def test_ui_conflict_cancel_preserves_both_saved_reviews(self) -> None:
        target_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "work_element_id": self.work_element_id,
                "status": "Open",
                "notes": "Target content",
            },
        )["id"]
        candidate_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {"status": "Pending", "notes": "Candidate content"},
        )["id"]
        rows = store.ergonomics_reviews(self.project_id, self.scenario_id)
        candidate_position = int(rows.index[rows["id"].eq(candidate_id)][0])
        app = self.run_page(
            {
                "edited_rows": {
                    candidate_position: {"work_element_id": self.work_element_id}
                },
                "added_rows": [],
                "deleted_rows": [],
            }
        )
        app = self.save_button(app).click().run(timeout=30)
        cancel = next(
            button for button in app.button if button.label == "Cancel"
        )
        app = cancel.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        saved = store.ergonomics_reviews(self.project_id, self.scenario_id)
        self.assertEqual(set(saved["id"]), {target_id, candidate_id})
        candidate = saved.loc[saved["id"].eq(candidate_id)].iloc[0]
        self.assertTrue(pd.isna(candidate["work_element_id"]))

    def test_native_row_deletion_removes_review_after_confirmation(self) -> None:
        review_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {"notes": "Delete this concern"},
        )["id"]
        app = self.run_page(
            {"edited_rows": {}, "added_rows": [], "deleted_rows": [0]}
        )
        delete_button = next(
            button
            for button in app.button
            if button.key
            == f"destructive_confirm_ergonomics_delete_{self.scenario_id}"
        )
        app = delete_button.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertFalse(
            any(
                row["id"] == review_id
                for row in store.query(
                    "SELECT id FROM ergonomics_reviews WHERE project_id=? AND scenario_id=?",
                    (self.project_id, self.scenario_id),
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
