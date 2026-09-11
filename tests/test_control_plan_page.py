from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from utils import control_plan_ui, quality_store, store


PAGE_PATH = Path(__file__).resolve().parents[1] / "app_pages" / "functional_quality.py"


class ControlPlanPageTests(unittest.TestCase):
    def test_characteristic_type_labels_preserve_storage_values(self) -> None:
        self.assertEqual(control_plan_ui._characteristic_type_label(""), "Not assigned")
        self.assertEqual(
            control_plan_ui._characteristic_type_label("Product / Part"), "Product"
        )
        self.assertEqual(control_plan_ui._characteristic_type_label("Process"), "Process")
        self.assertEqual(list(control_plan_ui.PLACEMENTS), ["", "Product / Part", "Process"])

    def test_orphan_relink_requires_confirmed_scenario_safe_dialog(self) -> None:
        pending = {
            "project_id": "project-1",
            "scenario_id": "scenario-1",
            "item_id": "item-1",
            "assignment_id": "assignment-1",
            "item_label": "ST-010 — Install bolt — Bolt torque",
            "assignment_label": "TQ-001 — Bolt torque",
        }
        session_state = {
            "scenario_id": "scenario-1",
            "current_editor": "MCP tester",
            control_plan_ui.PENDING_RELINK_KEY: pending,
        }
        actions = MagicMock()
        actions.button.side_effect = [False, True]
        with (
            patch.object(control_plan_ui.st, "session_state", session_state),
            patch.object(control_plan_ui.st, "container", return_value=actions),
            patch.object(control_plan_ui.st, "warning"),
            patch.object(control_plan_ui.st, "write"),
            patch.object(control_plan_ui.st, "error"),
            patch.object(control_plan_ui.st, "toast"),
            patch.object(control_plan_ui.st, "rerun", side_effect=RuntimeError("rerun")),
            patch.object(
                control_plan_ui,
                "relink_control_plan_item",
                return_value={"row_count": 1, "affected_ids": ["item-1"]},
            ) as relink,
            patch.object(control_plan_ui, "_audit") as audit,
            self.assertRaisesRegex(RuntimeError, "rerun"),
        ):
            control_plan_ui._confirm_relink.__wrapped__()
        relink.assert_called_once_with(
            "project-1", "scenario-1", "item-1", "assignment-1"
        )
        audit.assert_called_once()
        self.assertNotIn(control_plan_ui.PENDING_RELINK_KEY, session_state)

    def test_populated_working_draft_loads_without_streamlit_exception(self) -> None:
        scenarios = [{
            "id": "scenario-1", "project_id": "project-1", "name": "Current plan",
            "revision_label": "A", "revision_sequence": 1, "status": "Working",
            "takt_time_s": 60,
        }]
        projection = pd.DataFrame([{
            "id": "cp-1", "projection_key": "entry-1|quality|requirement-1",
            "pfmea_entry_id": "entry-1", "work_element_id": "work-1",
            "source_kind": "quality", "quality_requirement_assignment_id": "assignment-1",
            "quality_requirement_id": "requirement-1",
            "source_quality_requirement_id_snapshot": "requirement-1",
            "source_unique_identifier_snapshot": "TQ-001",
            "source_description_snapshot": "Bolt torque",
            "source_fingerprint": "fingerprint", "pr_number": 10.0,
            "operation_pr_number": 10.0, "projection_order": 0,
            "characteristic_suffix": None,
            "station_pitch": "ST-010",
            "operation": "Install bolt", "classification": "P",
            "characteristic_placement": "Process",
            "product_part_characteristic": "",
            "process_characteristic": "10.1 Bolt torque",
            "specification_requirement": "30 +/- 2 N-m",
            "measurement_evaluation": "Torque — DC tool — Right angle — Torx T30",
            "machine_fixture": "Torque spindle", "sample_size": "1",
            "sample_frequency": "Every unit", "who": "Operator",
            "control_method": "Controller OK result", "decision_rule": "Stop and contain",
            "excluded": False, "source_review_required": False, "persisted": True,
        }])
        with (
            patch.object(store, "planning_scenarios", return_value=scenarios),
            patch("utils.scope_ui.planning_scenarios", return_value=scenarios),
            patch.object(store, "audit_history", return_value=pd.DataFrame()),
            patch.object(quality_store, "quality_requirements", return_value=pd.DataFrame()),
            patch.object(
                control_plan_ui, "migrate_pfmea_classifications",
                return_value={"row_count": 0},
            ),
            patch.object(
                control_plan_ui, "migrate_control_plan_pr_numbers",
                return_value={"row_count": 0},
            ),
            patch.object(control_plan_ui, "control_plan_projection", return_value=projection),
            patch.object(control_plan_ui, "control_plan_review_items", return_value=pd.DataFrame()),
            patch.object(
                control_plan_ui, "control_plan_evidence",
                return_value={"Prevention": ["Quality — Bolt torque"], "Detection": [], "Actions": []},
            ),
        ):
            app = AppTest.from_file(str(PAGE_PATH), default_timeout=20)
            app.session_state["project_id"] = "project-1"
            app.session_state["scenario_id"] = "scenario-1"
            app.session_state["current_editor"] = "MCP tester"
            app.session_state["quality_page_tabs_project-1"] = "Control Plan"
            app.run(timeout=20)

        self.assertEqual(list(app.exception), [])
        self.assertIn(
            "Manufacturing Control Plan working draft",
            [heading.value for heading in app.subheader],
        )
        self.assertIn("Control Plan characteristics", [heading.value for heading in app.subheader])
        self.assertIn("Save & Refresh", [button.label for button in app.button])
        self.assertIn("Control Plan", [tab.label for tab in app.tabs])
        self.assertEqual(control_plan_ui.VISIBLE_COLUMNS[:3], [
            "pr_number", "station_pitch", "machine_fixture",
        ])
        self.assertNotIn("station_pitch", control_plan_ui.EDITABLE_COLUMNS)
        self.assertIn("characteristic_suffix", control_plan_ui.EDITABLE_COLUMNS)
        source = Path(
            Path(__file__).resolve().parents[1] / "utils" / "control_plan_ui.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"pfmea_entry_id": None', source)

    def test_process_number_displays_once_and_propagates_by_hidden_work_id(self) -> None:
        rows = pd.DataFrame(
            [
                {
                    "projection_key": "a-1", "work_element_id": "work-a",
                    "operation_pr_number": 10.0, "pr_number": 10.0,
                    "projection_order": 0, "operation": "Load housing",
                    "source_description_snapshot": "Check one",
                    "characteristic_placement": "Process",
                },
                {
                    "projection_key": "a-2", "work_element_id": "work-a",
                    "operation_pr_number": 10.0, "pr_number": None,
                    "projection_order": 1, "operation": "Load housing",
                    "source_description_snapshot": "Check two",
                    "characteristic_placement": "Process",
                },
                {
                    "projection_key": "b-1", "work_element_id": "work-b",
                    "operation_pr_number": 20.0, "pr_number": 20.0,
                    "projection_order": 2, "operation": "Install bracket",
                    "source_description_snapshot": "Check three",
                    "characteristic_placement": "Product / Part",
                },
            ]
        )
        display = control_plan_ui._display_first_pr_numbers(rows)
        self.assertEqual(display["pr_number"].tolist()[0], 10.0)
        self.assertTrue(pd.isna(display["pr_number"].tolist()[1]))
        self.assertEqual(display["pr_number"].tolist()[2], 20.0)

        updated, conflicts = control_plan_ui._apply_pr_number_editor_changes(
            rows,
            display,
            {"edited_rows": {"0": {"pr_number": 97.0}}},
        )
        self.assertEqual(conflicts, [])
        self.assertEqual(
            updated.loc[updated["work_element_id"].eq("work-a"), "operation_pr_number"].tolist(),
            [97.0, 97.0],
        )
        self.assertEqual(
            updated.loc[updated["work_element_id"].eq("work-b"), "operation_pr_number"].tolist(),
            [20.0],
        )
        self.assertEqual(updated.iloc[0]["process_characteristic"], "97.1 Check one")
        self.assertEqual(updated.iloc[1]["process_characteristic"], "97.2 Check two")

    def test_grouped_display_blanks_only_repeated_operation_level_values(self) -> None:
        rows = pd.DataFrame(
            [
                {
                    "projection_key": "a-1", "work_element_id": "work-a",
                    "operation_pr_number": 10.0, "pr_number": 10.0,
                    "operation": "Load", "machine_fixture": "Fixture A",
                },
                {
                    "projection_key": "a-2", "work_element_id": "work-a",
                    "operation_pr_number": 10.0, "pr_number": None,
                    "operation": "Load", "machine_fixture": "Fixture A",
                },
                {
                    "projection_key": "b-1", "work_element_id": "work-b",
                    "operation_pr_number": 20.0, "pr_number": 20.0,
                    "operation": "Inspect", "machine_fixture": "Gauge A",
                },
                {
                    "projection_key": "b-2", "work_element_id": "work-b",
                    "operation_pr_number": 20.0, "pr_number": None,
                    "operation": "Inspect", "machine_fixture": "Gauge B",
                },
            ]
        )
        display = control_plan_ui._grouped_control_plan_display(rows)
        self.assertEqual(display["operation"].tolist(), ["Load", "", "Inspect", ""])
        self.assertEqual(
            display["machine_fixture"].tolist(),
            ["Fixture A", "", "Gauge A", "Gauge B"],
        )
        self.assertEqual(rows.iloc[1]["machine_fixture"], "Fixture A")

        restored = control_plan_ui._restore_grouped_display_values(
            rows, display, display.copy(), {"edited_rows": {}}
        )
        self.assertEqual(restored["machine_fixture"].tolist(), rows["machine_fixture"].tolist())
        self.assertEqual(restored["operation"].tolist(), rows["operation"].tolist())

    def test_suffix_edit_is_per_line_and_duplicates_are_reported(self) -> None:
        rows = pd.DataFrame(
            [
                {
                    "projection_key": "a-1", "work_element_id": "work-a",
                    "operation_pr_number": 97.5, "projection_order": 0,
                    "operation": "Load", "source_description_snapshot": "First",
                    "characteristic_suffix": None,
                    "characteristic_placement": "Process",
                },
                {
                    "projection_key": "a-2", "work_element_id": "work-a",
                    "operation_pr_number": 97.5, "projection_order": 1,
                    "operation": "Load", "source_description_snapshot": "Second",
                    "characteristic_suffix": None,
                    "characteristic_placement": "Product / Part",
                },
            ]
        )
        updated = control_plan_ui._apply_characteristic_suffix_editor_changes(
            rows, rows, {"edited_rows": {0: {"characteristic_suffix": 10}}}
        )
        self.assertEqual(updated.iloc[0]["process_characteristic"], "97.5.10 First")
        self.assertEqual(updated.iloc[1]["product_part_characteristic"], "97.5.1 Second")
        self.assertEqual(updated["projection_key"].tolist(), rows["projection_key"].tolist())

        updated.loc[:, "characteristic_suffix"] = 3
        duplicates = control_plan_ui._duplicate_characteristic_suffixes(updated)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["characteristic_suffix"], 3)
        self.assertEqual(len(duplicates[0]["items"]), 2)

    def test_conflicting_same_operation_edits_and_cross_operation_duplicates_are_distinct(self) -> None:
        rows = pd.DataFrame(
            [
                {
                    "projection_key": "a-1", "work_element_id": "work-a",
                    "operation_pr_number": 10.0, "pr_number": 10.0,
                    "projection_order": 0, "operation": "Load housing",
                    "source_description_snapshot": "First",
                    "characteristic_placement": "Process",
                },
                {
                    "projection_key": "a-2", "work_element_id": "work-a",
                    "operation_pr_number": 10.0, "pr_number": None,
                    "projection_order": 1, "operation": "Load housing",
                    "source_description_snapshot": "Second",
                    "characteristic_placement": "Process",
                },
                {
                    "projection_key": "b-1", "work_element_id": "work-b",
                    "operation_pr_number": 10.0, "pr_number": 10.0,
                    "projection_order": 2, "operation": "Install bracket",
                    "source_description_snapshot": "Third",
                    "characteristic_placement": "Process",
                },
            ]
        )
        _, conflicts = control_plan_ui._apply_pr_number_editor_changes(
            rows,
            rows,
            {"edited_rows": {0: {"pr_number": 30.0}, 1: {"pr_number": 40.0}}},
        )
        self.assertEqual(conflicts, ["work-a"])
        duplicates = control_plan_ui._duplicate_pr_numbers(rows)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["pr_number"], 10.0)
        self.assertEqual(len(duplicates[0]["operations"]), 2)

    def test_duplicate_number_dialog_cancel_keeps_control_plan_draft(self) -> None:
        pending = {
            "project_id": "project-1", "scenario_id": "scenario-1",
            "rows": [], "duplicates": [],
            "suffix_duplicates": [{
                "work_element_id": "work-1", "characteristic_suffix": 2,
                "items": [
                    {"operation": "Load", "description": "First"},
                    {"operation": "Load", "description": "Second"},
                ],
            }],
            "draft_key": "draft-key", "editor_key": "editor-key",
        }
        draft = pd.DataFrame([{"projection_key": "line-1"}])
        session_state = {
            "scenario_id": "scenario-1", "draft-key": draft,
            control_plan_ui.PENDING_DUPLICATE_NUMBER_KEY: pending,
        }
        actions = MagicMock()
        actions.button.side_effect = [True, False]
        with (
            patch.object(control_plan_ui.st, "session_state", session_state),
            patch.object(control_plan_ui.st, "container", return_value=actions),
            patch.object(control_plan_ui.st, "warning"),
            patch.object(control_plan_ui.st, "write"),
            patch.object(control_plan_ui.st, "error"),
            patch.object(control_plan_ui.st, "rerun", side_effect=RuntimeError("rerun")),
            self.assertRaisesRegex(RuntimeError, "rerun"),
        ):
            control_plan_ui._confirm_duplicate_pr_numbers.__wrapped__()
        self.assertNotIn(control_plan_ui.PENDING_DUPLICATE_NUMBER_KEY, session_state)
        self.assertIs(session_state["draft-key"], draft)

    def test_duplicate_number_dialog_save_anyway_writes_once_and_clears_draft(self) -> None:
        pending = {
            "project_id": "project-1", "scenario_id": "scenario-1",
            "rows": [{"projection_key": "line-1"}],
            "duplicates": [],
            "suffix_duplicates": [{
                "work_element_id": "work-1", "characteristic_suffix": 2,
                "items": [
                    {"operation": "Load", "description": "First"},
                    {"operation": "Load", "description": "Second"},
                ],
            }],
            "draft_key": "draft-key", "editor_key": "editor-key",
        }
        session_state = {
            "scenario_id": "scenario-1",
            "draft-key": pd.DataFrame(pending["rows"]),
            control_plan_ui.PENDING_DUPLICATE_NUMBER_KEY: pending,
        }
        actions = MagicMock()
        actions.button.side_effect = [False, True]
        result = {"row_count": 1, "affected_ids": ["cp-1"], "timestamp": "now"}
        with (
            patch.object(control_plan_ui.st, "session_state", session_state),
            patch.object(control_plan_ui.st, "container", return_value=actions),
            patch.object(control_plan_ui.st, "warning"),
            patch.object(control_plan_ui.st, "write"),
            patch.object(control_plan_ui.st, "error"),
            patch.object(control_plan_ui.st, "toast"),
            patch.object(control_plan_ui.st, "rerun", side_effect=RuntimeError("rerun")),
            patch.object(
                control_plan_ui, "save_control_plan_rows", return_value=result
            ) as save,
            patch.object(control_plan_ui, "_audit") as audit,
            self.assertRaisesRegex(RuntimeError, "rerun"),
        ):
            control_plan_ui._confirm_duplicate_pr_numbers.__wrapped__()
        save.assert_called_once()
        audit.assert_called_once_with("project-1", "Save & Refresh", result, "scenario-1")
        self.assertNotIn(control_plan_ui.PENDING_DUPLICATE_NUMBER_KEY, session_state)
        self.assertNotIn("draft-key", session_state)


if __name__ == "__main__":
    unittest.main()
