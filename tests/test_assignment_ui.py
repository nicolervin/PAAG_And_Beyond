"""Unit tests for utils/assignment_ui.py (Section 4 Assignment Dialog)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd
import streamlit as st

from utils import assignment_ui


class AssignmentUITests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_id = "test-proj-ui"
        self.scenario_id = "test-scen-ui"
        # Reset session state for testing
        for k in list(st.session_state.keys()):
            del st.session_state[k]

    def _render(self, *args, **kwargs):
        fn = getattr(
            assignment_ui.render_assign_requirement_dialog,
            "__wrapped__",
            assignment_ui.render_assign_requirement_dialog,
        )
        return fn(*args, **kwargs)

    def test_open_and_close_assign_dialog_session_state(self) -> None:
        self.assertFalse(st.session_state.get(assignment_ui.ASSIGN_REQ_DIALOG_OPEN_KEY, False))
        self.assertIsNone(st.session_state.get(assignment_ui.ASSIGN_REQ_SELECTED_ID_KEY))

        # Open without requirement id
        assignment_ui.open_assign_requirement_dialog()
        self.assertTrue(st.session_state[assignment_ui.ASSIGN_REQ_DIALOG_OPEN_KEY])
        self.assertIsNone(st.session_state.get(assignment_ui.ASSIGN_REQ_SELECTED_ID_KEY))

        # Open with requirement id
        assignment_ui.open_assign_requirement_dialog("req-999")
        self.assertTrue(st.session_state[assignment_ui.ASSIGN_REQ_DIALOG_OPEN_KEY])
        self.assertEqual(st.session_state[assignment_ui.ASSIGN_REQ_SELECTED_ID_KEY], "req-999")

        # Close
        assignment_ui.close_assign_requirement_dialog()
        self.assertFalse(st.session_state.get(assignment_ui.ASSIGN_REQ_DIALOG_OPEN_KEY, False))
        self.assertIsNone(st.session_state.get(assignment_ui.ASSIGN_REQ_SELECTED_ID_KEY))

    def test_empty_requirements_shows_warning(self) -> None:
        with (
            patch.object(assignment_ui, "quality_requirements", return_value=pd.DataFrame()),
            patch.object(assignment_ui.st, "warning") as mock_warning,
            patch.object(assignment_ui.st, "button", return_value=False),
        ):
            self._render(self.project_id, self.scenario_id)
            mock_warning.assert_called_once()
            self.assertIn("no saved Quality requirements", mock_warning.call_args[0][0])

    def test_empty_steps_shows_info(self) -> None:
        req_df = pd.DataFrame([{
            "id": "req-1",
            "unique_identifier": "QR-01",
            "description": "Visual check",
            "requirement_type": "Visual",
            "pass_fail": 1,
            "target_value": None,
            "tolerances": None,
            "unit": None,
        }])
        with (
            patch.object(assignment_ui, "quality_requirements", return_value=req_df),
            patch.object(assignment_ui, "quality_process_steps", return_value=pd.DataFrame()),
            patch.object(assignment_ui.st, "info") as mock_info,
            patch.object(assignment_ui.st, "selectbox", return_value="req-1"),
            patch.object(assignment_ui.st, "container"),
            patch.object(
                assignment_ui.st,
                "columns",
                side_effect=lambda spec, **kw: [MagicMock() for _ in range(len(spec) if isinstance(spec, (list, tuple)) else int(spec))],
            ),
            patch.object(assignment_ui.st, "button", return_value=False),
        ):
            self._render(self.project_id, self.scenario_id)
            mock_info.assert_called_once()
            self.assertIn("no Process at a Glance steps available", mock_info.call_args[0][0])

    def test_torque_requirement_triggers_tooling_gap_advisory(self) -> None:
        req_df = pd.DataFrame([{
            "id": "req-trq",
            "unique_identifier": "QR-TRQ-01",
            "description": "Tighten fastener",
            "requirement_type": "Torque",
            "pass_fail": 0,
            "target_value": "15.0",
            "tolerances": "+/- 1.0",
            "unit": "Nm",
        }])
        steps_df = pd.DataFrame([
            {
                "id": "step-1",
                "pitch_name": "Pitch 01",
                "op_id": "OP-10",
                "work_element": "Install Bolt",
            },
            {
                "id": "step-2",
                "pitch_name": "Pitch 01",
                "op_id": "OP-20",
                "work_element": "Torque Bolt",
            },
        ])

        with (
            patch.object(assignment_ui, "quality_requirements", return_value=req_df),
            patch.object(assignment_ui, "quality_process_steps", return_value=steps_df),
            patch.object(assignment_ui, "quality_requirement_links", return_value=pd.DataFrame()),
            patch.object(assignment_ui, "step_equipment_tooling_status", return_value={"step-1": [], "step-2": []}),
            patch.object(assignment_ui, "project_equipment_assets", return_value=[{"id": "eq-1", "name": "Torque Gun", "equipment_type": "Torque Tool"}]),
            patch.object(assignment_ui.st, "selectbox", side_effect=["req-trq", "All Stations / Pitches", "eq-1"]),
            patch.object(assignment_ui.st, "text_input", side_effect=["", "Quality Engineer"]),
            patch.object(assignment_ui.st, "multiselect", return_value=["step-1", "step-2"]),
            patch.object(assignment_ui.st, "warning") as mock_warning,
            patch.object(assignment_ui.st, "checkbox", return_value=True),
            patch.object(assignment_ui.st, "container"),
            patch.object(
                assignment_ui.st,
                "columns",
                side_effect=lambda spec, **kw: [MagicMock() for _ in range(len(spec) if isinstance(spec, (list, tuple)) else int(spec))],
            ),
            patch.object(assignment_ui.st, "button", return_value=False),
        ):
            self._render(self.project_id, self.scenario_id)
            mock_warning.assert_called()
            # Verify the warning contains Tooling Gap Advisory
            warning_texts = [call[0][0] for call in mock_warning.call_args_list if call[0]]
            self.assertTrue(any("Tooling Gap Advisory" in str(txt) for txt in warning_texts))

    def test_attach_requirement_keeps_dialog_open_and_clears_selection(self) -> None:
        req_df = pd.DataFrame([{
            "id": "req-1",
            "unique_identifier": "QR-01",
            "description": "Visual check",
            "requirement_type": "Visual",
            "pass_fail": 1,
            "target_value": None,
            "tolerances": None,
            "unit": None,
        }])
        steps_df = pd.DataFrame([{
            "id": "step-1",
            "pitch_name": "Pitch 01",
            "op_id": "OP-10",
            "work_element": "Inspect part",
        }])

        st.session_state[assignment_ui.ASSIGN_REQ_DIALOG_OPEN_KEY] = True

        def button_mock(label, **kwargs):
            if "Attach Requirement" in label:
                return True
            return False

        with (
            patch.object(assignment_ui, "quality_requirements", return_value=req_df),
            patch.object(assignment_ui, "quality_process_steps", return_value=steps_df),
            patch.object(assignment_ui, "quality_requirement_links", return_value=pd.DataFrame()),
            patch.object(assignment_ui, "bulk_assign_quality_requirement", return_value={"created_count": 1}) as mock_assign,
            patch.object(assignment_ui, "request_table_editor_reset") as mock_reset,
            patch.object(assignment_ui.st, "selectbox", side_effect=["req-1", "All Stations / Pitches"]),
            patch.object(assignment_ui.st, "text_input", side_effect=["", "Quality Auditor"]),
            patch.object(assignment_ui.st, "multiselect", return_value=["step-1"]),
            patch.object(assignment_ui.st, "button", side_effect=button_mock),
            patch.object(assignment_ui.st, "rerun") as mock_rerun,
            patch.object(assignment_ui.st, "toast"),
            patch.object(assignment_ui.st, "container"),
            patch.object(
                assignment_ui.st,
                "columns",
                side_effect=lambda spec, **kw: [MagicMock() for _ in range(len(spec) if isinstance(spec, (list, tuple)) else int(spec))],
            ),
        ):
            self._render(self.project_id, self.scenario_id)

            mock_assign.assert_called_once_with(
                project_id=self.project_id,
                scenario_id=self.scenario_id,
                quality_requirement_id="req-1",
                work_element_ids=["step-1"],
                editor_name="Quality Auditor",
            )
            mock_reset.assert_called_once_with(f"quality_requirements_editor_{self.project_id}")
            # Dialog remains open for further attachments
            self.assertTrue(st.session_state.get(assignment_ui.ASSIGN_REQ_DIALOG_OPEN_KEY))
            # Success message was set
            self.assertIn("Successfully attached requirement", st.session_state.get(f"assign_success_msg_{self.project_id}", ""))
            # Sequence key was incremented to reset widget keys cleanly on rerun
            seq_key = f"assign_steps_seq_{self.project_id}"
            self.assertEqual(st.session_state.get(seq_key), 1)
            mock_rerun.assert_called_once()

    def test_close_button_closes_dialog(self) -> None:
        req_df = pd.DataFrame([{
            "id": "req-1",
            "unique_identifier": "QR-01",
            "description": "Visual check",
            "requirement_type": "Visual",
            "pass_fail": 1,
            "target_value": None,
            "tolerances": None,
            "unit": None,
        }])
        steps_df = pd.DataFrame([{
            "id": "step-1",
            "pitch_name": "Pitch 01",
            "op_id": "OP-10",
            "work_element": "Inspect part",
        }])

        st.session_state[assignment_ui.ASSIGN_REQ_DIALOG_OPEN_KEY] = True
        st.session_state[f"assign_steps_seq_{self.project_id}"] = 1
        st.session_state[f"assign_success_msg_{self.project_id}"] = "Some message"

        def button_mock(label, **kwargs):
            if label == "Close":
                return True
            return False

        with (
            patch.object(assignment_ui, "quality_requirements", return_value=req_df),
            patch.object(assignment_ui, "quality_process_steps", return_value=steps_df),
            patch.object(assignment_ui, "quality_requirement_links", return_value=pd.DataFrame()),
            patch.object(assignment_ui.st, "selectbox", side_effect=["req-1", "All Stations / Pitches"]),
            patch.object(assignment_ui.st, "text_input", side_effect=["", "Quality Auditor"]),
            patch.object(assignment_ui.st, "multiselect", return_value=[]),
            patch.object(assignment_ui.st, "button", side_effect=button_mock),
            patch.object(assignment_ui.st, "rerun") as mock_rerun,
            patch.object(assignment_ui.st, "container"),
            patch.object(
                assignment_ui.st,
                "columns",
                side_effect=lambda spec, **kw: [MagicMock() for _ in range(len(spec) if isinstance(spec, (list, tuple)) else int(spec))],
            ),
        ):
            self._render(self.project_id, self.scenario_id)

            # Dialog is closed and cleanup occurred
            self.assertFalse(st.session_state.get(assignment_ui.ASSIGN_REQ_DIALOG_OPEN_KEY, False))
            self.assertNotIn(f"assign_steps_seq_{self.project_id}", st.session_state)
            self.assertNotIn(f"assign_success_msg_{self.project_id}", st.session_state)
            mock_rerun.assert_called_once()


if __name__ == "__main__":
    unittest.main()
