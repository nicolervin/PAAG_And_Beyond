from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from utils import quality_store, store


PAGE_PATH = Path(__file__).resolve().parents[1] / "app_pages" / "functional_quality.py"


class QualityPageSmokeTests(unittest.TestCase):
    def run_page(
        self,
        requirements: pd.DataFrame,
        *,
        scenarios: list[dict] | None = None,
        process_steps: pd.DataFrame | None = None,
        links: pd.DataFrame | None = None,
        torque_details: pd.DataFrame | None = None,
        screw_bit_types: list[str] | None = None,
        selected_torque_requirement_id: str | None = None,
    ) -> AppTest:
        with (
            patch.object(quality_store, "quality_requirements", return_value=requirements),
            patch.object(
                quality_store,
                "quality_process_steps",
                return_value=process_steps if process_steps is not None else pd.DataFrame(),
            ),
            patch.object(
                quality_store,
                "quality_requirement_links",
                return_value=links if links is not None else pd.DataFrame(),
            ),
            patch.object(
                quality_store,
                "quality_requirement_torque_details",
                return_value=(
                    torque_details if torque_details is not None else pd.DataFrame()
                ),
            ),
            patch.object(
                quality_store,
                "torque_screw_bit_types",
                return_value=screw_bit_types or [],
            ),
            patch.object(store, "planning_scenarios", return_value=scenarios or []),
            patch.object(store, "audit_history", return_value=pd.DataFrame()),
        ):
            app = AppTest.from_file(str(PAGE_PATH))
            app.session_state["project_id"] = "project-1"
            app.session_state["current_editor"] = "Quality tester"
            if scenarios:
                app.session_state["scenario_id"] = str(scenarios[0]["id"])
            if selected_torque_requirement_id:
                app.session_state[
                    "quality_torque_detail_requirement_project-1"
                ] = selected_torque_requirement_id
            app.run(timeout=10)
        return app

    def test_empty_repository_renders_editor_footer_push_and_history(self) -> None:
        app = self.run_page(pd.DataFrame())

        self.assertEqual(len(app.exception), 0)
        self.assertIn("Quality requirements", [heading.value for heading in app.subheader])

    def test_active_scenario_renders_attach_unlink_and_linked_step_controls(self) -> None:
        requirements = pd.DataFrame(
            [
                {
                    "id": "quality-1",
                    "project_id": "project-1",
                    "requirement_type": "Torque",
                    "description": "Tighten the mounting screw",
                    "unique_identifier": "TQ-001",
                    "pass_fail": 1,
                    "target_value": 32.0,
                    "tolerances": "+/- 3",
                    "unit": "N·m",
                    "created_at": "2026-08-31T12:00:00+00:00",
                    "updated_at": "2026-08-31T12:00:00+00:00",
                    "assignment_count": 0,
                    "pending_assignment_count": 0,
                }
            ]
        )
        scenarios = [
            {
                "id": "scenario-1",
                "name": "Current plan",
                "revision_label": "A",
            }
        ]
        process_steps = pd.DataFrame(
            [
                {
                    "id": "step-1",
                    "sequence": 10,
                    "pitch": "Pitch 10",
                    "pitch_name": "Final assembly",
                    "work_element": "Install screw",
                    "status": "Draft",
                }
            ]
        )
        links = pd.DataFrame(
            [
                {
                    "assignment_id": "assignment-1",
                    "quality_requirement_id": "quality-1",
                    "scenario_id": "scenario-1",
                    "work_element_id": "step-1",
                    "scenario_revision": "A",
                    "scenario_name": "Current plan",
                    "sequence": 10,
                    "pitch": "Pitch 10",
                    "pitch_name": "Final assembly",
                    "work_element": "Install screw",
                    "status": "Draft",
                    "requirement_type": "Torque",
                    "description": "Published screw requirement",
                    "unique_identifier": "TQ-001",
                    "pass_fail": 1,
                    "target_value": 32.0,
                    "tolerances": "+/- 3",
                    "unit": "NÂ·m",
                    "repository_update_pending": 1,
                }
            ]
        )
        app = self.run_page(
            requirements,
            scenarios=scenarios,
            process_steps=process_steps,
            links=links,
        )

        self.assertEqual(len(app.exception), 0)
        self.assertIn(
            "Attach to Process at a Glance step",
            [button.label for button in app.button],
        )
        self.assertIn(
            "Unlink selected Process at a Glance step",
            [button.label for button in app.button],
        )
        self.assertIn(
            '"View Quality requirements linked to Process steps"',
            PAGE_PATH.read_text(encoding="utf-8"),
        )
        page_source = PAGE_PATH.read_text(encoding="utf-8")
        self.assertIn('"Quality requirement Unique identifier"', page_source)
        self.assertIn('"Repository update pending"', page_source)
        linked_tables = [
            table.value
            for table in app.dataframe
            if "Quality requirement Unique identifier" in table.value.columns
        ]
        self.assertEqual(len(linked_tables), 1)
        linked_table = linked_tables[0]
        self.assertEqual(len(linked_table), 1)
        self.assertEqual(linked_table.iloc[0]["Description"], "Published screw requirement")
        self.assertEqual(
            list(linked_table.columns),
            [
                "Scenario",
                "Pitch",
                "Pitch Name",
                "Work Element",
                "Status",
                "Seq",
                "Quality requirement Unique identifier",
                "Type",
                "Description",
                "Pass/fail",
                "Target value",
                "Tolerances",
                "Unit",
                "Repository update pending",
            ],
        )
        self.assertFalse(
            {
                "assignment_id",
                "quality_requirement_id",
                "work_element_id",
                "project_id",
                "scenario_id",
            }
            & set(linked_table.columns)
        )
        self.assertIn("Save & Refresh", [button.label for button in app.button])
        self.assertIn(
            "Push saved updates to linked Process steps",
            [button.label for button in app.button],
        )
        self.assertIn(
            "Saved Torque requirement",
            [selectbox.label for selectbox in app.selectbox],
        )
        page_source = PAGE_PATH.read_text(encoding="utf-8")
        self.assertIn('accept_new_options=True', page_source)
        self.assertIn('"Tool type"', page_source)
        self.assertIn('"Tool orientation"', page_source)
        self.assertNotIn('"Type",\n                options=TORQUE_TOOL_TYPES', page_source)

    def test_populated_repository_renders_without_exception(self) -> None:
        app = self.run_page(
            pd.DataFrame(
                [
                    {
                        "id": "quality-1",
                        "project_id": "project-1",
                        "requirement_type": "Torque",
                        "description": "Tighten the mounting screw",
                        "unique_identifier": "TQ-001",
                        "pass_fail": 1,
                        "target_value": 32.0,
                        "tolerances": "+/- 3",
                        "unit": "N·m",
                        "created_at": "2026-08-27T12:00:00+00:00",
                        "updated_at": "2026-08-27T12:00:00+00:00",
                        "assignment_count": 2,
                        "pending_assignment_count": 1,
                    }
                ]
            )
        )

        self.assertEqual(len(app.exception), 0)
        self.assertIn("Quality requirements", [heading.value for heading in app.subheader])

    def test_selected_torque_requirement_renders_tool_details_without_exception(self) -> None:
        requirements = pd.DataFrame(
            [
                {
                    "id": "quality-1",
                    "project_id": "project-1",
                    "requirement_type": "Torque",
                    "description": "Tighten the mounting screw",
                    "unique_identifier": "TQ-001",
                    "pass_fail": 0,
                    "target_value": 32.0,
                    "tolerances": "+/- 3",
                    "unit": "N·m",
                    "created_at": "2026-08-31T12:00:00+00:00",
                    "updated_at": "2026-08-31T12:00:00+00:00",
                    "assignment_count": 0,
                    "pending_assignment_count": 0,
                    "torque_detail_count": 1,
                }
            ]
        )
        torque_details = pd.DataFrame(
            [
                {
                    "id": "torque-detail-1",
                    "project_id": "project-1",
                    "quality_requirement_id": "quality-1",
                    "tool_type": "DC tool",
                    "tool_orientation": "Right angle",
                    "screw_bit_type": "Torx T30",
                    "created_at": "2026-08-31T12:00:00+00:00",
                    "updated_at": "2026-08-31T12:00:00+00:00",
                }
            ]
        )

        app = self.run_page(
            requirements,
            torque_details=torque_details,
            screw_bit_types=["Phillips #2", "Torx T30"],
            selected_torque_requirement_id="quality-1",
        )

        self.assertEqual(len(app.exception), 0)
        self.assertIn("Screw bit type", [selectbox.label for selectbox in app.selectbox])
        self.assertGreaterEqual(
            [button.label for button in app.button].count("Save & Refresh"), 2
        )

    def test_pending_unlink_uses_assignment_scenario_not_session_scenario(self) -> None:
        page_source = PAGE_PATH.read_text(encoding="utf-8")
        unlink_request = page_source.split(
            'if st.button(\n        "Unlink selected Process at a Glance step"', 1
        )[1].split('@st.dialog("Unlink Quality requirement?"', 1)[0]

        self.assertIn(
            '"scenario_id": str(selected_assignment["scenario_id"])',
            unlink_request,
        )
        self.assertNotIn('"scenario_id": scenario_id', unlink_request)
        self.assertIn(
            'quality_requirement_assignment(\n                project_id, selected_assignment_id',
            unlink_request,
        )
        self.assertIn(
            'scenario_changed = str(pending.get("scenario_id") or "") != scenario_id',
            page_source,
        )


if __name__ == "__main__":
    unittest.main()
