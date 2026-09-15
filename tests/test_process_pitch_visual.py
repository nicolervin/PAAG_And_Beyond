from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from streamlit.testing.v1 import AppTest

from utils import store
from utils.process_pitch_visual import (
    clamp_page,
    page_count,
    page_elements,
    page_for_element,
    render_pitch_canvas,
)


class ProcessPitchVisualTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_pitch_visual_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])
        self.section_id = store.add_assembly_section(
            self.project_id, "Main", "Main spine", None, ""
        )
        self.area_id = str(uuid4())
        self.pitch_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES (?, ?, ?, ?, 'Visual area', ?)""",
                (self.area_id, self.project_id, self.scenario_id, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES (?, ?, ?, '01-SW1-051', 'Pitch visual', ?)""",
                (self.pitch_id, self.project_id, self.area_id, timestamp),
            )
        self.work_ids = [self._add_linked_element(index) for index in range(1, 7)]

    def _add_linked_element(self, index: int) -> str:
        work_id = f"work-{index}"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    model_applicability, updated_at)
                   VALUES (?, ?, ?, ?, '01-SW1-051', ?, 'All', ?)""",
                (
                    work_id,
                    self.project_id,
                    self.scenario_id,
                    index * 10,
                    f"Motion {index}",
                    timestamp,
                ),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id,
                    description, time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"yam-{index}",
                    self.project_id,
                    self.area_id,
                    self.pitch_id,
                    work_id,
                    f"Motion {index}",
                    float(index),
                    index * 10,
                    timestamp,
                ),
            )
        return work_id

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_summary_is_ordered_and_second_page_contains_clicked_element(self) -> None:
        summary = store.process_pitch_visual_summary(
            self.project_id, self.scenario_id, self.pitch_id
        )
        self.assertEqual(
            [row["work_element_id"] for row in summary["elements"]], self.work_ids
        )
        self.assertEqual(page_count(len(summary["elements"])), 2)
        self.assertEqual(page_for_element(summary["elements"], self.work_ids[5]), 2)
        self.assertEqual(
            page_elements(summary["elements"], 2)[0]["work_element_id"], self.work_ids[5]
        )

    def test_linked_work_is_reflected_even_when_yamazumi_needs_review(self) -> None:
        rows = store.yamazumi_elements_for_section(
            self.project_id, self.scenario_id, self.section_id
        )
        self.assertTrue(rows["process_sync_status"].eq("Needs IE review").all())
        self.assertTrue(rows["process_reflected"].astype(bool).all())

    def test_summary_rejects_pitch_from_another_scenario(self) -> None:
        other_scenario = store.clone_planning_scenario(
            self.project_id,
            self.scenario_id,
            "Other",
            "B",
            60,
            created_by="Pitch visual test",
        )
        with self.assertRaisesRegex(ValueError, "active planning scenario"):
            store.process_pitch_visual_summary(
                self.project_id, str(other_scenario), self.pitch_id
            )

    def test_pagination_clamps_at_both_boundaries(self) -> None:
        self.assertEqual(clamp_page(0, 6), 1)
        self.assertEqual(clamp_page(99, 6), 2)
        with self.assertRaisesRegex(ValueError, "no longer assigned"):
            page_for_element([{"work_element_id": "one"}], "missing")

    def test_renderer_escapes_content_and_renders_required_fallbacks(self) -> None:
        html = render_pitch_canvas(
            {"pitch_number": "P<&", "pitch_name": "Visual"},
            [
                {
                    "work_element_id": "one",
                    "op_id": "M1.P1.1",
                    "yamazumi_description": "Fit <bracket>",
                    "time_s": 3.5,
                    "models": ["Model A"],
                    "parts": [],
                    "motion_classification": "Unclassified",
                    "motion_color": "gray",
                    "ergonomics_risk": True,
                    "torque_requirements": [
                        {
                            "unique_identifier": "TQ-1",
                            "target_value": 12,
                            "tolerances": "±1",
                            "unit": "N·m",
                        }
                    ],
                }
            ],
            scenario_name="Scenario <One>",
            generated_on=date(2026, 9, 11),
        )
        self.assertIn("No Parts Paired", html)
        self.assertIn("motion-bar gray", html)
        self.assertNotIn("motion-bar red", html)
        self.assertIn("Ergo Risk", html)
        self.assertIn("TQ-1: 12 ±1 N·m", html)
        self.assertIn("Fit &lt;bracket&gt;", html)
        self.assertIn("Generated on September 11, 2026 — Scenario: Scenario &lt;One&gt;", html)

    def test_renderer_embeds_an_available_part_image(self) -> None:
        html = render_pitch_canvas(
            {"pitch_number": "P1"},
            [{
                "op_id": "M1.P1.1",
                "yamazumi_description": "Install",
                "time_s": 1,
                "models": ["All models"],
                "parts": [{"part_number": "PART-1", "image_path": __file__}],
                "motion_classification": "Value-Added (VA)",
                "motion_color": "green",
                "torque_requirements": [],
            }],
            scenario_name="Base",
        )
        self.assertIn(";base64,", html)
        self.assertIn("motion-bar green", html)
        orange_html = render_pitch_canvas(
            {"pitch_number": "P1"},
            [{
                "op_id": "M1.P1.2", "yamazumi_description": "Move", "time_s": 2,
                "models": ["All models"], "parts": [],
                "motion_classification": "Non-Value-Added but Necessary (NVAN)",
                "motion_color": "orange", "torque_requirements": [],
            }],
            scenario_name="Base",
        )
        self.assertIn("motion-bar orange", orange_html)

    def test_process_page_renders_selected_pitch_and_navigates_to_page_two(self) -> None:
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/process.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Pitch visual test"
        app.session_state["selected_pitch_id"] = self.pitch_id
        app.session_state["pitch_page_num"] = 1
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertIn("details", next(
            editor.value for editor in app.dataframe
            if "ergonomics_risk" in editor.value.columns
        ).columns)
        next_button = next(button for button in app.button if button.label == "Next")
        app = next_button.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["pitch_page_num"], 2)
        self.assertFalse(next(button for button in app.button if button.label == "Back").disabled)


if __name__ == "__main__":
    unittest.main()
