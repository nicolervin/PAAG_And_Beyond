from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from utils import quality_store, store, table_ui


PAGE_PATH = Path(__file__).resolve().parents[1] / "app_pages" / "functional_quality.py"


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
                "Scenario", "Pitch", "Pitch Name", "Work Element",
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

    def test_bulk_pass_fail_uses_separate_read_only_selection_surface(self) -> None:
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
                    "unit": "NÂ·m",
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
        self.assertIn("Apply to selected (0)", [button.label for button in app.button])
        bulk_tables = [
            table.value
            for table in app.dataframe
            if len(table.value) == 2
            and {
                "unique_identifier", "description", "requirement_type", "pass_fail",
            }.issubset(table.value.columns)
        ]
        self.assertGreaterEqual(len(bulk_tables), 1)
        source = PAGE_PATH.read_text(encoding="utf-8")
        self.assertIn('with st.expander("Bulk edit Pass/fail"):', source)
        self.assertIn("bulk_selection_event = selectable_dataframe(", source)
        self.assertIn("bulk_selected_requirements = selected_dataframe_rows(", source)
        self.assertIn(
            'f"Apply to selected ({len(bulk_selected_requirements)})"', source
        )
        self.assertIn(
            "selected_requirements_for_deletion = native_selected_rows(", source
        )
        self.assertIn(
            "reset_widget_keys=[editor_key, bulk_selector_key]", source
        )

    def test_bulk_pass_fail_updates_selected_ids_and_records_one_audit_event(self) -> None:
        requirements = pd.DataFrame(
            [
                {
                    "id": f"quality-{index}",
                    "project_id": "project-1",
                    "requirement_type": "Torque",
                    "description": f"Tighten screw {index}",
                    "unique_identifier": f"TQ-{index:03d}",
                    "pass_fail": 0,
                    "target_value": 32.0,
                    "tolerances": "+/- 3",
                    "unit": "NÂ·m",
                    "created_at": "2026-09-04T12:00:00+00:00",
                    "updated_at": "2026-09-04T12:00:00+00:00",
                    "assignment_count": 0,
                    "pending_assignment_count": 0,
                    "torque_detail_count": 0,
                }
                for index in [1, 2]
            ]
        )
        requirement_types = pd.DataFrame(
            [
                {
                    "id": "type-torque",
                    "project_id": "project-1",
                    "label": "Torque",
                    "active": 1,
                    "created_at": "2026-09-04T12:00:00+00:00",
                    "updated_at": "2026-09-04T12:00:00+00:00",
                    "requirement_count": 2,
                }
            ]
        )
        original_selectable_dataframe = table_ui.selectable_dataframe

        def selectable_with_bulk_rows(data, *, key: str, **kwargs):
            if "quality_requirements_bulk_selector" in key:
                selected_rows = [] if key.endswith("__editor_instance_1") else [0, 1]
                return SimpleNamespace(selection=SimpleNamespace(rows=selected_rows))
            return original_selectable_dataframe(data, key=key, **kwargs)

        bulk_result = {
            "row_count": 2,
            "updated_ids": ["quality-1", "quality-2"],
            "timestamp": "2026-09-04T13:00:00+00:00",
        }
        with (
            patch.object(quality_store, "quality_requirements", return_value=requirements),
            patch.object(
                quality_store, "quality_requirement_types", return_value=requirement_types
            ),
            patch.object(quality_store, "quality_process_steps", return_value=pd.DataFrame()),
            patch.object(quality_store, "quality_requirement_links", return_value=pd.DataFrame()),
            patch.object(
                quality_store,
                "quality_requirement_torque_details",
                return_value=pd.DataFrame(),
            ),
            patch.object(quality_store, "torque_screw_bit_types", return_value=[]),
            patch.object(
                quality_store,
                "bulk_update_quality_requirement_pass_fail",
                return_value=bulk_result,
            ) as bulk_update,
            patch.object(store, "planning_scenarios", return_value=[]),
            patch.object(store, "audit_history", return_value=pd.DataFrame()),
            patch.object(store, "record_audit_event") as record_audit,
            patch.object(
                table_ui,
                "selectable_dataframe",
                side_effect=selectable_with_bulk_rows,
            ),
        ):
            app = AppTest.from_file(str(PAGE_PATH))
            app.session_state["project_id"] = "project-1"
            app.session_state["current_editor"] = "Quality tester"
            app.session_state[
                "quality_requirements_bulk_pass_fail_project-1"
            ] = "Pass/fail check"
            app.run(timeout=10)
            apply_button = next(
                button for button in app.button
                if button.label == "Apply to selected (2)"
            )
            self.assertFalse(apply_button.disabled)
            apply_button.click().run(timeout=10)
            cleared_button = next(
                button for button in app.button
                if button.label == "Apply to selected (0)"
            )
            self.assertTrue(cleared_button.disabled)

        self.assertEqual(len(app.exception), 0)
        bulk_update.assert_called_once_with(
            "project-1", ["quality-1", "quality-2"], pass_fail=True
        )
        record_audit.assert_called_once()
        audit_args = record_audit.call_args.args
        self.assertEqual(audit_args[:5], (
            "project-1", "Quality requirements", "Bulk edit", 2, "Quality tester",
        ))
        self.assertEqual(
            audit_args[5],
            {
                "requirement_ids": ["quality-1", "quality-2"],
                "pass_fail": True,
                "store_timestamp": "2026-09-04T13:00:00+00:00",
            },
        )

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
        source = PAGE_PATH.read_text(encoding="utf-8")
        self.assertIn('st.expander("Manage Quality requirement types"', source)
        self.assertIn('"requirement_type": st.column_config.SelectboxColumn(', source)
        self.assertIn('"requirement_count": st.column_config.NumberColumn(', source)
        self.assertIn('"id": None', source)

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
