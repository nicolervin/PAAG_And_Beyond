"""Tests for Cross-Functional Traceability & Discrepancy Matrix UI and workflows."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from utils import store, traceability_store, traceability_ui


PAGE_PATH = Path(__file__).resolve().parents[1] / "app_pages" / "functional_quality.py"


class TraceabilityUITests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_id = "proj-test"
        self.scenario_id = "scen-test"
        self.active_scenario = {
            "id": self.scenario_id,
            "project_id": self.project_id,
            "name": "Line 1 Revision A",
            "revision_label": "Rev A",
        }

    def test_no_active_scenario_shows_info_message(self) -> None:
        with patch.object(traceability_ui.st, "info") as mock_info:
            traceability_ui.render_traceability_matrix_tab(self.project_id, self.scenario_id, None)
            mock_info.assert_called_once()
            self.assertIn("Select an active planning scenario", mock_info.call_args[0][0])

    def test_empty_scenario_shows_empty_info(self) -> None:
        empty_matrix = {
            "rows": [],
            "summary": {
                "total_steps": 0,
                "steps_with_quality": 0,
                "protected_steps": 0,
                "critical_gap_steps": 0,
                "warning_steps": 0,
                "uncovered_steps": 0,
                "fully_protected_pct": 100.0,
                "spec_drift_count": 0,
                "tooling_gap_count": 0,
            },
            "pitches": [],
        }
        with (
            patch.object(
                traceability_ui,
                "cross_functional_traceability_matrix",
                return_value=empty_matrix,
            ),
            patch.object(traceability_ui.st, "info") as mock_info,
            patch.object(traceability_ui.st, "markdown"),
            patch.object(traceability_ui.st, "caption"),
        ):
            traceability_ui.render_traceability_matrix_tab(
                self.project_id, self.scenario_id, self.active_scenario
            )
            mock_info.assert_called_once()
            self.assertIn("No process steps found", mock_info.call_args[0][0])

    def test_populated_matrix_renders_kpis_and_cards(self) -> None:
        sample_rows = [
            {
                "work_element_id": "work-1",
                "op_id": "OP-10",
                "pitch": "Pitch 1",
                "sequence": 10,
                "operation": "Torque fastener",
                "quality_assignment_id": "qa-1",
                "quality_uid": "QR-TRQ-01",
                "quality_type": "Torque",
                "quality_description": "M6 bolt torque",
                "published_spec": "9.5 +/- 0.5 Nm",
                "pfmea_entry_id": "pf-1",
                "pfmea_class_code": "S",
                "pfmea_failure_mode": "Loose bolt",
                "has_pfmea_control": True,
                "control_plan_item_id": "cp-1",
                "control_plan_pr_number": "10.1",
                "control_plan_spec": "8.0 +/- 0.5 Nm",
                "equipment_names": ["Atlas Copco Tool"],
                "equipment_display": "Atlas Copco Tool [Torque tool]",
                "status": "WARNING",
                "status_label": "🟡 Warning",
                "spec_drift": True,
                "discrepancies": [
                    {
                        "code": "SPEC_DRIFT",
                        "severity": "WARNING",
                        "title": "Warning: Specification Drift",
                        "message": "Control Plan spec differs from published Quality spec.",
                    }
                ],
                "discrepancy_count": 1,
                "discrepancy_summary": "Warning: Specification Drift",
            },
            {
                "work_element_id": "work-2",
                "op_id": "OP-20",
                "pitch": "Pitch 2",
                "sequence": 20,
                "operation": "Install bracket",
                "quality_assignment_id": "",
                "quality_uid": "—",
                "quality_type": "—",
                "quality_description": "—",
                "published_spec": "—",
                "pfmea_entry_id": "",
                "pfmea_class_code": "",
                "pfmea_failure_mode": "—",
                "has_pfmea_control": False,
                "control_plan_item_id": "",
                "control_plan_pr_number": "",
                "control_plan_spec": "—",
                "equipment_names": [],
                "equipment_display": "—",
                "status": "UNCOVERED",
                "status_label": "⚪ Uncovered",
                "spec_drift": False,
                "discrepancies": [],
                "discrepancy_count": 0,
                "discrepancy_summary": "Standard assembly step",
            },
        ]
        sample_matrix = {
            "rows": sample_rows,
            "summary": {
                "total_steps": 2,
                "steps_with_quality": 1,
                "protected_steps": 0,
                "critical_gap_steps": 0,
                "warning_steps": 1,
                "uncovered_steps": 1,
                "fully_protected_pct": 0.0,
                "spec_drift_count": 1,
                "tooling_gap_count": 0,
            },
            "pitches": ["Pitch 1", "Pitch 2"],
        }

        mock_kpis = [MagicMock() for _ in range(5)]
        def fake_columns(spec, **kwargs):
            if spec == 5:
                return mock_kpis
            n = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
            cols = [MagicMock() for _ in range(n)]
            if n == 4:
                cols[0].selectbox.return_value = "All Statuses"
                cols[1].selectbox.return_value = "All Pitches"
                cols[2].checkbox.return_value = False
                cols[3].text_input.return_value = ""
            return cols

        with (
            patch.object(
                traceability_ui,
                "cross_functional_traceability_matrix",
                return_value=sample_matrix,
            ),
            patch.object(traceability_ui.st, "columns", side_effect=fake_columns),
            patch.object(traceability_ui.st, "markdown"),
            patch.object(traceability_ui.st, "caption"),
            patch.object(traceability_ui.st, "warning") as mock_warning,
            patch.object(traceability_ui.st, "expander"),
            patch.object(traceability_ui.st, "container"),
            patch.object(traceability_ui.st, "dataframe") as mock_df,
        ):
            traceability_ui.render_traceability_matrix_tab(
                self.project_id, self.scenario_id, self.active_scenario
            )
            mock_warning.assert_called_once()
            mock_kpis[0].metric.assert_called_with("Fully Protected", "0.0%", help=unittest.mock.ANY)
            mock_kpis[1].metric.assert_called_with("Critical Gaps", "🔴 0", help=unittest.mock.ANY)
            mock_kpis[2].metric.assert_called_with("Warnings & Drift", "🟡 1", help=unittest.mock.ANY)
            mock_df.assert_called_once()

    def test_align_specification_dialog_cancel_clears_state(self) -> None:
        pending_key = f"traceability_pending_align_spec_{self.project_id}"
        session_state = {
            pending_key: {
                "control_plan_item_id": "cp-1",
                "quality_uid": "QR-01",
                "published_spec": "10 Nm",
                "current_cp_spec": "8 Nm",
                "operation": "Torque Op",
                "op_id": "OP-10",
            },
            "current_editor": "Tester",
        }

        actions_c1 = MagicMock()
        actions_c1.button.return_value = True  # Cancel clicked
        actions_c2 = MagicMock()
        actions_c2.button.return_value = False

        with (
            patch.object(traceability_ui.st, "session_state", session_state),
            patch.object(traceability_ui.st, "markdown"),
            patch.object(traceability_ui.st, "write"),
            patch.object(traceability_ui.st, "columns", side_effect=[[MagicMock(), MagicMock()], [actions_c1, actions_c2]]),
            patch.object(traceability_ui.st, "caption"),
            patch.object(traceability_ui.st, "text_input", return_value="Tester"),
            patch.object(traceability_ui.st, "rerun", side_effect=RuntimeError("rerun")),
            self.assertRaisesRegex(RuntimeError, "rerun"),
        ):
            traceability_ui.align_specification_dialog.__wrapped__(
                self.project_id, self.scenario_id
            )

        self.assertNotIn(pending_key, session_state)

    def test_align_specification_dialog_confirm_executes_alignment(self) -> None:
        pending_key = f"traceability_pending_align_spec_{self.project_id}"
        session_state = {
            pending_key: {
                "control_plan_item_id": "cp-1",
                "quality_uid": "QR-01",
                "published_spec": "10 Nm",
                "current_cp_spec": "8 Nm",
                "operation": "Torque Op",
                "op_id": "OP-10",
            },
            "current_editor": "Tester",
        }

        actions_c1 = MagicMock()
        actions_c1.button.return_value = False
        actions_c2 = MagicMock()
        actions_c2.button.return_value = True  # Align clicked

        with (
            patch.object(traceability_ui.st, "session_state", session_state),
            patch.object(traceability_ui.st, "markdown"),
            patch.object(traceability_ui.st, "write"),
            patch.object(traceability_ui.st, "columns", side_effect=[[MagicMock(), MagicMock()], [actions_c1, actions_c2]]),
            patch.object(traceability_ui.st, "caption"),
            patch.object(traceability_ui.st, "text_input", return_value="Approver Engineer"),
            patch.object(traceability_ui, "align_control_plan_specification") as mock_align,
            patch.object(traceability_ui.st, "toast") as mock_toast,
            patch.object(traceability_ui.st, "rerun", side_effect=RuntimeError("rerun")),
            self.assertRaisesRegex(RuntimeError, "rerun"),
        ):
            traceability_ui.align_specification_dialog.__wrapped__(
                self.project_id, self.scenario_id
            )

        mock_align.assert_called_once_with(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            control_plan_item_id="cp-1",
            editor_name="Approver Engineer",
        )
        self.assertNotIn(pending_key, session_state)
        self.assertEqual(session_state["current_editor"], "Approver Engineer")
        mock_toast.assert_called_once()

    def test_quick_link_equipment_dialog_confirm_links_tool(self) -> None:
        pending_key = f"traceability_pending_quick_link_{self.project_id}"
        session_state = {
            pending_key: {
                "work_element_id": "work-10",
                "op_id": "OP-10",
                "pitch": "Pitch 1",
                "operation": "Torque Step",
                "quality_uid": "QR-01",
                "quality_type": "Torque",
                "quality_description": "M6 bolt torque",
            },
            "current_editor": "Tooling Tech",
        }

        eq_df = pd.DataFrame([
            {"id": "eq-1", "name": "Atlas Copco Nutrunner", "equipment_type": "Torque tool", "pitch_number": "1"}
        ])

        actions_c1 = MagicMock()
        actions_c1.button.return_value = False
        actions_c2 = MagicMock()
        actions_c2.button.return_value = True  # Link clicked

        with (
            patch.object(traceability_ui.st, "session_state", session_state),
            patch.object(traceability_ui.st, "markdown"),
            patch.object(traceability_ui.st, "write"),
            patch.object(traceability_ui, "equipment_assets", return_value=eq_df),
            patch.object(traceability_ui.st, "selectbox", return_value="eq-1"),
            patch.object(traceability_ui.st, "text_input", return_value="Tooling Tech"),
            patch.object(traceability_ui.st, "columns", return_value=[actions_c1, actions_c2]),
            patch.object(traceability_ui, "quick_link_step_equipment") as mock_link,
            patch.object(traceability_ui.st, "toast"),
            patch.object(traceability_ui.st, "rerun", side_effect=RuntimeError("rerun")),
            self.assertRaisesRegex(RuntimeError, "rerun"),
        ):
            traceability_ui.quick_link_equipment_dialog.__wrapped__(
                self.project_id, self.scenario_id
            )

        mock_link.assert_called_once_with(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            work_element_id="work-10",
            equipment_id="eq-1",
            editor_name="Tooling Tech",
        )
        self.assertNotIn(pending_key, session_state)

    def test_traceability_matrix_tab_renders_in_page_test(self) -> None:
        """Smoke test verifying page rendering when Traceability tab is selected."""
        scenarios = [
            {
                "id": "scenario-1",
                "name": "Active Line Scenario",
                "revision_label": "A",
            }
        ]
        sample_matrix = {
            "rows": [
                {
                    "work_element_id": "work-1",
                    "op_id": "OP-10",
                    "pitch": "Pitch 1",
                    "sequence": 10,
                    "operation": "Assemble Bracket",
                    "quality_assignment_id": "",
                    "quality_uid": "—",
                    "quality_type": "—",
                    "quality_description": "—",
                    "published_spec": "—",
                    "pfmea_entry_id": "",
                    "pfmea_class_code": "",
                    "pfmea_failure_mode": "—",
                    "has_pfmea_control": False,
                    "control_plan_item_id": "",
                    "control_plan_pr_number": "",
                    "control_plan_spec": "—",
                    "equipment_names": [],
                    "equipment_display": "—",
                    "status": "UNCOVERED",
                    "status_label": "⚪ Uncovered",
                    "spec_drift": False,
                    "discrepancies": [],
                    "discrepancy_count": 0,
                    "discrepancy_summary": "Standard assembly step",
                }
            ],
            "summary": {
                "total_steps": 1,
                "steps_with_quality": 0,
                "protected_steps": 0,
                "critical_gap_steps": 0,
                "warning_steps": 0,
                "uncovered_steps": 1,
                "fully_protected_pct": 100.0,
                "spec_drift_count": 0,
                "tooling_gap_count": 0,
            },
            "pitches": ["Pitch 1"],
        }

        with (
            patch.object(store, "planning_scenarios", return_value=scenarios),
            patch("utils.scope_ui.planning_scenarios", return_value=scenarios),
            patch.object(store, "audit_history", return_value=pd.DataFrame()),
            patch(
                "utils.traceability_ui.cross_functional_traceability_matrix",
                return_value=sample_matrix,
            ),
        ):
            app = AppTest.from_file(str(PAGE_PATH), default_timeout=20)
            app.session_state["project_id"] = "project-1"
            app.session_state["scenario_id"] = "scenario-1"
            app.session_state["current_editor"] = "Tester"
            app.session_state["quality_page_tabs_project-1"] = "📊 Traceability Matrix"
            app.run(timeout=20)

        self.assertEqual(list(app.exception), [])
        tab_labels = [tab.label for tab in app.tabs]
        self.assertIn("📊 Traceability Matrix", tab_labels)
        self.assertIn("Requirements repository", tab_labels)
        # Verify Traceability Matrix comes before Requirements repository
        self.assertLess(
            tab_labels.index("📊 Traceability Matrix"),
            tab_labels.index("Requirements repository"),
        )
        self.assertTrue(
            any("Traceability & Discrepancy Matrix" in m.value for m in app.markdown)
        )
