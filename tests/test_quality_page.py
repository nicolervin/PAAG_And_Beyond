from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from utils import quality_store, store, table_ui


PAGE_PATH = Path(__file__).resolve().parents[1] / "app_pages" / "functional_quality.py"
REQUIREMENTS_UI_PATH = PAGE_PATH.parents[1] / "utils" / "requirements_ui.py"


class QualityPageSmokeTests(unittest.TestCase):
    def run_page(
        self,
        requirements: pd.DataFrame,
        *,
        requirement_types: pd.DataFrame | None = None,
        scenarios: list[dict] | None = None,
        process_steps: pd.DataFrame | None = None,
        links: pd.DataFrame | None = None,
        torque_details: pd.DataFrame | None = None,
        screw_bit_types: list[str] | None = None,
        selected_torque_requirement_id: str | None = None,
        focused_link_requirement_id: str | None = None,
        dialog_link_requirement_id: str | None = None,
    ) -> AppTest:
        if requirement_types is None:
            requirement_types = pd.DataFrame(
                [
                    {
                        "id": f"type-{index}",
                        "project_id": "project-1",
                        "label": label,
                        "active": 1,
                        "created_at": "2026-09-04T12:00:00+00:00",
                        "updated_at": "2026-09-04T12:00:00+00:00",
                        "requirement_count": int(
                            not requirements.empty
                            and requirements["requirement_type"]
                            .fillna("")
                            .astype(str)
                            .str.strip()
                            .str.casefold()
                            .eq(label.casefold())
                            .sum()
                        ),
                    }
                    for index, label in enumerate(
                        [
                            "Dimensional",
                            "Present and fully seated",
                            "Torque",
                            "Vision system",
                        ],
                        start=1,
                    )
                ]
            )
        with (
            patch.object(quality_store, "quality_requirements", return_value=requirements),
            patch.object(
                quality_store,
                "quality_requirement_types",
                return_value=requirement_types,
            ),
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
            patch("utils.scope_ui.planning_scenarios", return_value=scenarios or []),
            patch.object(store, "audit_history", return_value=pd.DataFrame()),
        ):
            app = AppTest.from_file(str(PAGE_PATH))
            app.session_state["project_id"] = "project-1"
            app.session_state["current_editor"] = "Quality tester"
            if "quality_page_tabs_project-1" not in app.session_state:
                app.session_state["quality_page_tabs_project-1"] = "Requirements repository"
            if scenarios:
                app.session_state["scenario_id"] = str(scenarios[0]["id"])
            if selected_torque_requirement_id:
                app.session_state[
                    "quality_torque_detail_requirement_project-1"
                ] = selected_torque_requirement_id
            if focused_link_requirement_id:
                app.session_state[
                    "quality_requirement_linked_steps_focus_project-1"
                ] = focused_link_requirement_id
            if dialog_link_requirement_id:
                app.session_state[
                    "quality_requirement_linked_steps_dialog_project-1"
                ] = dialog_link_requirement_id
            app.run(timeout=10)
        return app

    def test_empty_repository_renders_editor_footer_push_and_history(self) -> None:
        app = self.run_page(pd.DataFrame())

        self.assertEqual(len(app.exception), 0)
        self.assertIn("Quality requirements", [heading.value for heading in app.subheader])

    def test_linked_process_workflow_renders_before_publish_after_torque_move(self) -> None:
        active_scenario = [
            {
                "id": "scenario-1",
                "name": "Current plan",
                "revision_label": "A",
            }
        ]
        for scenarios in (None, active_scenario):
            with self.subTest(active_scenario=bool(scenarios)):
                app = self.run_page(pd.DataFrame(), scenarios=scenarios)
                headings = [heading.value for heading in app.subheader]

                self.assertEqual(len(app.exception), 0)
                self.assertLess(
                    headings.index("Link to Process at a Glance"),
                    headings.index("Publish saved updates"),
                )
                self.assertNotIn("Torque tool details", headings)

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
            "🔗 Assign Steps...",
            [button.label for button in app.button],
        )
        requirements_source = REQUIREMENTS_UI_PATH.read_text(encoding="utf-8")
        self.assertIn(
            '"View Quality requirements linked to Process steps"',
            requirements_source,
        )
        self.assertIn('"Quality requirement Unique identifier"', requirements_source)
        self.assertIn('"Repository update pending"', requirements_source)
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
        self.assertNotIn(
            "Saved Torque requirement",
            [selectbox.label for selectbox in app.selectbox],
        )
        self.assertIn("Equipment", [tab.label for tab in app.tabs])
        self.assertIn('accept_new_options=True', requirements_source)
        self.assertIn('"Tool type"', requirements_source)
        self.assertIn('"Tool orientation"', requirements_source)
        self.assertNotIn('"Type",\n                options=TORQUE_TOOL_TYPES', requirements_source)

    def test_link_count_click_resolves_saved_row_identity_and_ignores_blank_row(self) -> None:
        editor_rows = pd.DataFrame(
            [
                {"id": "quality-1", "description": "Similar requirement"},
                {"id": "quality-2", "description": "Similar requirement"},
                {"id": pd.NA, "description": ""},
            ]
        )
        self.assertEqual(
            table_ui.stable_id_from_button_click(
                editor_rows, {"row": 1, "label": "2"}
            ),
            "quality-2",
        )
        self.assertEqual(
            table_ui.stable_id_from_button_click(
                editor_rows, {"row": 2, "label": "0"}
            ),
            "",
        )
        self.assertEqual(
            table_ui.stable_id_from_button_click(
                editor_rows, {"row": 99, "label": "0"}
            ),
            "",
        )

    def test_linked_steps_focus_uses_hidden_id_and_keeps_published_values(self) -> None:
        requirements = pd.DataFrame(
            [
                {
                    "id": "quality-1", "project_id": "project-1",
                    "requirement_type": "Torque", "description": "Similar check",
                    "unique_identifier": "CURRENT-1", "pass_fail": 1,
                    "target_value": 10.0, "tolerances": "+/- 1", "unit": "N·m",
                    "created_at": "2026-09-01T12:00:00+00:00",
                    "updated_at": "2026-09-01T12:00:00+00:00",
                    "assignment_count": 0, "pending_assignment_count": 0,
                },
                {
                    "id": "quality-2", "project_id": "project-1",
                    "requirement_type": "Torque", "description": "Similar check",
                    "unique_identifier": "CURRENT-2", "pass_fail": 1,
                    "target_value": 20.0, "tolerances": "+/- 2", "unit": "N·m",
                    "created_at": "2026-09-01T12:00:00+00:00",
                    "updated_at": "2026-09-02T12:00:00+00:00",
                    "assignment_count": 1, "pending_assignment_count": 1,
                },
            ]
        )
        links = pd.DataFrame(
            [
                {
                    "assignment_id": "assignment-2",
                    "quality_requirement_id": "quality-2",
                    "scenario_id": "scenario-1", "work_element_id": "step-1",
                    "scenario_revision": "A", "scenario_name": "Current plan",
                    "sequence": 10, "pitch": "ST-010", "pitch_name": "Assembly",
                    "work_element": "Install bracket", "status": "Draft",
                    "requirement_type": "Torque",
                    "description": "Previously published description",
                    "unique_identifier": "PUBLISHED-OLD", "pass_fail": 1,
                    "target_value": 18.0, "tolerances": "+/- 2", "unit": "N·m",
                    "repository_update_pending": 1,
                }
            ]
        )
        app = self.run_page(
            requirements,
            links=links,
            focused_link_requirement_id="quality-2",
        )

        self.assertEqual(len(app.exception), 0)
        self.assertIn(
            "Show all linked Process steps", [button.label for button in app.button]
        )
        linked_tables = [
            table.value
            for table in app.dataframe
            if "Quality requirement Unique identifier" in table.value.columns
        ]
        self.assertEqual(len(linked_tables), 1)
        self.assertEqual(len(linked_tables[0]), 1)
        self.assertEqual(
            linked_tables[0].iloc[0]["Quality requirement Unique identifier"],
            "PUBLISHED-OLD",
        )
        self.assertEqual(
            linked_tables[0].iloc[0]["Description"],
            "Previously published description",
        )

    def test_link_count_dialog_shows_concise_published_process_context(self) -> None:
        requirements = pd.DataFrame(
            [
                {
                    "id": "quality-2", "project_id": "project-1",
                    "requirement_type": "Torque", "description": "Clamp check",
                    "unique_identifier": "CURRENT-2", "pass_fail": 1,
                    "target_value": 20.0, "tolerances": "+/- 2", "unit": "N·m",
                    "created_at": "2026-09-01T12:00:00+00:00",
                    "updated_at": "2026-09-02T12:00:00+00:00",
                    "assignment_count": 2, "pending_assignment_count": 1,
                }
            ]
        )
        links = pd.DataFrame(
            [
                {
                    "assignment_id": "assignment-1",
                    "quality_requirement_id": "quality-2",
                    "scenario_id": "scenario-1", "work_element_id": "step-1",
                    "scenario_revision": "A", "scenario_name": "Current plan",
                    "sequence": 10, "pitch": "ST-010", "pitch_name": "Assembly",
                    "work_element": "Load housing", "status": "Draft",
                    "requirement_type": "Torque", "description": "Published check",
                    "unique_identifier": "PUBLISHED-OLD", "pass_fail": 1,
                    "target_value": 18.0, "tolerances": "+/- 2", "unit": "N·m",
                    "repository_update_pending": 1,
                },
                {
                    "assignment_id": "assignment-2",
                    "quality_requirement_id": "quality-2",
                    "scenario_id": "scenario-2", "work_element_id": "step-2",
                    "scenario_revision": "B", "scenario_name": "Alternate",
                    "sequence": 20, "pitch": "ST-020", "pitch_name": "Finish",
                    "work_element": "Verify assembly", "status": "Released",
                    "requirement_type": "Torque", "description": "Published check",
                    "unique_identifier": "PUBLISHED-OLD", "pass_fail": 1,
                    "target_value": 18.0, "tolerances": "+/- 2", "unit": "N·m",
                    "repository_update_pending": 0,
                },
            ]
        )
        app = self.run_page(
            requirements,
            links=links,
            focused_link_requirement_id="quality-2",
            dialog_link_requirement_id="quality-2",
        )

        self.assertEqual(len(app.exception), 0)
        concise_tables = [
            table.value
            for table in app.dataframe
            if list(table.value.columns)
            == [
                "Scenario", "Op ID", "Pitch", "Pitch Name", "Work Element",
                "Status", "Seq", "Repository update pending",
            ]
        ]
        self.assertEqual(len(concise_tables), 1)
        self.assertEqual(len(concise_tables[0]), 2)
        self.assertEqual(
            concise_tables[0]["Work Element"].tolist(),
            ["Load housing", "Verify assembly"],
        )
        self.assertEqual(
            concise_tables[0]["Repository update pending"].tolist(),
            [True, False],
        )
        self.assertNotIn("quality_requirement_id", concise_tables[0].columns)
        self.assertIn("Close", [button.label for button in app.button])

    def test_zero_link_focus_reports_no_linked_process_steps(self) -> None:
        requirements = pd.DataFrame(
            [
                {
                    "id": "quality-1", "project_id": "project-1",
                    "requirement_type": "Torque", "description": "Unlinked check",
                    "unique_identifier": "TQ-EMPTY", "pass_fail": 1,
                    "target_value": 10.0, "tolerances": "+/- 1", "unit": "N·m",
                    "created_at": "2026-09-01T12:00:00+00:00",
                    "updated_at": "2026-09-01T12:00:00+00:00",
                    "assignment_count": 0, "pending_assignment_count": 0,
                }
            ]
        )
        app = self.run_page(
            requirements,
            links=pd.DataFrame(),
            focused_link_requirement_id="quality-1",
            dialog_link_requirement_id="quality-1",
        )

        self.assertEqual(len(app.exception), 0)
        self.assertIn(
            "No linked Process steps were found for this Quality requirement.",
            [caption.value for caption in app.caption],
        )
        self.assertIn("No linked Process steps", [info.value for info in app.info])

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

    def test_requirements_repository_renders_pass_fail_in_table_without_bulk_expander(self) -> None:
        requirements = pd.DataFrame(
            [
                {
                    "id": f"quality-{index}",
                    "project_id": "project-1",
                    "requirement_type": "Torque",
                    "description": f"Tighten screw {index}",
                    "unique_identifier": f"TQ-{index:03d}",
                    "pass_fail": index == 1,
                    "target_value": 32.0,
                    "tolerances": "+/- 3",
                    "unit": "N·m",
                    "created_at": "2026-09-04T12:00:00+00:00",
                    "updated_at": "2026-09-04T12:00:00+00:00",
                    "assignment_count": 0,
                    "pending_assignment_count": 0,
                    "torque_detail_count": 0,
                }
                for index in [1, 2]
            ]
        )

        app = self.run_page(requirements)

        self.assertEqual(len(app.exception), 0)
        self.assertFalse(any("Apply to selected" in button.label for button in app.button))
        source = REQUIREMENTS_UI_PATH.read_text(encoding="utf-8")
        self.assertNotIn('with st.expander("Bulk edit Pass/fail"):', source)
        self.assertNotIn("bulk_selector_key", source)
        self.assertIn('"pass_fail": st.column_config.CheckboxColumn(', source)


    def test_type_catalog_dropdown_management_and_inactive_warning_render(self) -> None:
        requirements = pd.DataFrame(
            [
                {
                    "id": "quality-legacy",
                    "project_id": "project-1",
                    "requirement_type": "Legacy visual",
                    "description": "Confirm label placement",
                    "unique_identifier": "VIS-LEGACY",
                    "pass_fail": 1,
                    "target_value": None,
                    "tolerances": "",
                    "unit": "",
                    "created_at": "2026-09-04T12:00:00+00:00",
                    "updated_at": "2026-09-04T12:00:00+00:00",
                    "assignment_count": 0,
                    "pending_assignment_count": 0,
                    "torque_detail_count": 0,
                }
            ]
        )
        catalog = pd.DataFrame(
            [
                {
                    "id": "type-torque",
                    "project_id": "project-1",
                    "label": "Torque",
                    "active": 1,
                    "created_at": "2026-09-04T12:00:00+00:00",
                    "updated_at": "2026-09-04T12:00:00+00:00",
                    "requirement_count": 0,
                },
                {
                    "id": "type-legacy",
                    "project_id": "project-1",
                    "label": "Legacy visual",
                    "active": 0,
                    "created_at": "2026-09-04T12:00:00+00:00",
                    "updated_at": "2026-09-04T12:00:00+00:00",
                    "requirement_count": 1,
                },
            ]
        )

        app = self.run_page(requirements, requirement_types=catalog)

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(
            any("cannot be newly assigned" in warning.value for warning in app.warning)
        )
        self.assertGreaterEqual(
            [button.label for button in app.button].count("Save & Refresh"), 2
        )
        source = REQUIREMENTS_UI_PATH.read_text(encoding="utf-8")
        self.assertIn('st.expander("Manage Quality requirement types"', source)
        self.assertIn('"requirement_type": st.column_config.SelectboxColumn(', source)
        self.assertIn('"requirement_count": st.column_config.NumberColumn(', source)
        self.assertIn('"id": None', source)

    def test_torque_requirement_details_are_not_rendered_in_repository(self) -> None:
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
        self.assertNotIn("Screw bit type", [selectbox.label for selectbox in app.selectbox])
        self.assertIn(
            "render_torque_requirement_specifications",
            (PAGE_PATH.parents[1] / "utils" / "equipment_ui.py").read_text(encoding="utf-8"),
        )

    def test_pending_unlink_uses_assignment_scenario_not_session_scenario(self) -> None:
        page_source = REQUIREMENTS_UI_PATH.read_text(encoding="utf-8")
        self.assertIn('sc_id = str(items[0]["scenario_id"])', page_source)
        self.assertIn(
            'scenario_changed = str(pending.get("scenario_id") or "") != scenario_id',
            page_source,
        )


if __name__ == "__main__":
    unittest.main()
