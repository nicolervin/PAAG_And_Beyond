from __future__ import annotations

import inspect
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest

from utils import pfmea_ui, quality_store, store


PAGE_PATH = Path(__file__).resolve().parents[1] / "app_pages" / "functional_quality.py"


class PfmeaPageSmokeTests(unittest.TestCase):
    @staticmethod
    def _process_steps() -> tuple[pd.DataFrame, dict[str, pd.Series]]:
        steps = pd.DataFrame(
            [
                {"id": "step-1", "work_element": "Load housing", "pitch": "ST-010",
                 "sequence": 10},
                {"id": "step-2", "work_element": "Install bracket", "pitch": "ST-010",
                 "sequence": 20},
                {"id": "step-3", "work_element": "Verify assembly", "pitch": "ST-020",
                 "sequence": 30},
            ]
        )
        return steps, {str(row["id"]): row for _, row in steps.iterrows()}

    def test_process_function_options_distinguish_steps_with_the_same_pitch(self) -> None:
        _, step_by_id = self._process_steps()
        self.assertEqual(
            pfmea_ui._process_step_option_label(step_by_id["step-1"]),
            "Load housing — ST-010 — Seq 10",
        )
        self.assertEqual(
            pfmea_ui._process_step_option_label(step_by_id["step-2"]),
            "Install bracket — ST-010 — Seq 20",
        )

        original = pd.DataFrame(
            [
                {"id": "", "work_element_id": "", "item_number": "",
                 "process_function": ""},
                {"id": "", "work_element_id": "", "item_number": "",
                 "process_function": ""},
            ]
        )
        editor_state = {
            "edited_rows": {},
            "added_rows": [
                {"process_function": "step-1"},
                {"process_function": "step-2"},
            ],
            "deleted_rows": [],
        }
        self.assertTrue(pfmea_ui._process_selection_changed_in_state(editor_state))
        edited = pfmea_ui._editor_rows_from_state(
            original.iloc[0:0],
            editor_state,
        )
        normalized, changed, locked = pfmea_ui._normalize_pfmea_process_selection(
            edited, original.iloc[0:0], step_by_id
        )
        self.assertTrue(changed)
        self.assertFalse(locked)
        self.assertEqual(normalized["work_element_id"].tolist(), ["step-1", "step-2"])
        self.assertEqual(normalized["item_number"].tolist(), ["ST-010", "ST-010"])
        self.assertEqual(
            normalized["process_function"].tolist(),
            ["Load housing", "Install bracket"],
        )

        template = original.iloc[0:0]
        session_state = {"editor": editor_state}
        with (
            patch.object(pfmea_ui.st, "session_state", session_state),
            patch.object(pfmea_ui, "request_table_editor_reset") as request_reset,
        ):
            pfmea_ui._stage_pfmea_process_selection(
                "editor", "draft", template, template, template, step_by_id
            )
        staged = session_state["draft"]
        self.assertEqual(staged["item_number"].tolist(), ["ST-010", "ST-010"])
        self.assertEqual(
            staged["process_function"].tolist(),
            ["Load housing", "Install bracket"],
        )
        request_reset.assert_called_once_with("editor")

    def test_pfmea_control_columns_are_native_editable_multiselects(self) -> None:
        source = inspect.getsource(pfmea_ui._render_flat_pfmea_table)
        prevention = source.split('"prevention_controls": st.column_config.MultiselectColumn(', 1)[1]
        prevention = prevention.split('"detection_controls": st.column_config.MultiselectColumn(', 1)[0]
        detection = source.split('"detection_controls": st.column_config.MultiselectColumn(', 1)[1]
        detection = detection.split('"rpn": st.column_config.NumberColumn', 1)[0]
        for configuration in (prevention, detection):
            self.assertIn("accept_new_options=False", configuration)
            self.assertNotIn("disabled=True", configuration)
        self.assertIn("options=list(prevention_labels)", prevention)
        self.assertIn("options=list(detection_labels)", detection)

    def test_pfmea_delete_staging_preserves_multi_row_labels_and_parent_ids(self) -> None:
        selected = pd.DataFrame(
            [
                {"id": "entry-1", "potential_failure_mode": "Loose bracket"},
                {"id": "entry-2", "potential_failure_mode": "Missing screw"},
            ]
        )
        session_state: dict = {}
        with (
            patch.object(pfmea_ui.st, "session_state", session_state),
            patch.object(pfmea_ui, "stage_native_delete_confirmation") as stage_confirmation,
        ):
            pfmea_ui._stage_delete(
                selected,
                editor_key="pfmea_flat_editor_project_scenario__instance__0",
                project_id="project",
                scenario_id="scenario",
                table="pfmea_entries",
                record_label="PFMEA line item",
                display_column="potential_failure_mode",
                selected_labels=[
                    "ST-010 — Load housing — Loose bracket",
                    "ST-020 — Install screw — Missing screw",
                ],
                impact_message="Related PFMEA child records are removed.",
            )
        pending = session_state[pfmea_ui.PENDING_DELETE_KEY]
        self.assertEqual(pending["record_ids"], ["entry-1", "entry-2"])
        self.assertEqual(
            pending["labels"],
            [
                "ST-010 — Load housing — Loose bracket",
                "ST-020 — Install screw — Missing screw",
            ],
        )
        self.assertEqual(pending["scenario_id"], "scenario")
        stage_confirmation.assert_called_once_with(
            "pfmea_flat_editor_project_scenario__instance__0"
        )

    def test_entrypoint_reveals_native_delete_only_for_pfmea_editor_key(self) -> None:
        source = (PAGE_PATH.parents[1] / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn(
            'div[class*="st-key-pfmea_flat_editor"] button[aria-label="Delete row(s)"]',
            source,
        )
        pfmea_source = (
            PAGE_PATH.parents[1] / "utils" / "pfmea_ui.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '@st.dialog("Delete selected PFMEA records?", dismissible=False)',
            pfmea_source,
        )

    def test_cancel_pfmea_delete_restores_editor_without_deleting(self) -> None:
        editor_key = "pfmea_flat_editor_project_scenario__instance__0"
        session_state = {
            "scenario_id": "scenario",
            pfmea_ui.PENDING_DELETE_KEY: {
                "project_id": "project",
                "scenario_id": "scenario",
                "table": "pfmea_entries",
                "record_label": "PFMEA line item",
                "record_ids": ["entry-1"],
                "labels": ["ST-010 — Load housing"],
                "impact_message": "Related PFMEA child records are removed.",
                "editor_key": editor_key,
            },
        }
        actions = MagicMock()
        actions.button.side_effect = [True]
        with (
            patch.object(pfmea_ui.st, "session_state", session_state),
            patch.object(pfmea_ui.st, "container", return_value=actions),
            patch.object(pfmea_ui.st, "warning"),
            patch.object(pfmea_ui.st, "write"),
            patch.object(pfmea_ui.st, "error"),
            patch.object(pfmea_ui.st, "rerun", side_effect=RuntimeError("rerun")),
            patch.object(pfmea_ui, "delete_pfmea_records") as delete,
            patch.object(pfmea_ui, "request_table_editor_reset") as reset,
            self.assertRaisesRegex(RuntimeError, "rerun"),
        ):
            pfmea_ui._confirm_pfmea_delete.__wrapped__()
        delete.assert_not_called()
        reset.assert_called_once_with(editor_key)
        self.assertNotIn(pfmea_ui.PENDING_DELETE_KEY, session_state)

    def test_confirmed_pfmea_delete_uses_destructive_flow_and_audits_editor(self) -> None:
        pending = {
            "project_id": "project",
            "scenario_id": "scenario",
            "table": "pfmea_entries",
            "record_label": "PFMEA line item",
            "record_ids": ["entry-1", "entry-2"],
            "labels": ["ST-010 — Load housing", "ST-020 — Install bracket"],
            "impact_message": "Related PFMEA child records are removed.",
            "editor_key": "pfmea_flat_editor_project_scenario__instance__0",
        }
        session_state = {
            "scenario_id": "scenario",
            "current_editor": "Nicole Ervin",
            pfmea_ui.PENDING_DELETE_KEY: pending,
        }
        actions = MagicMock()
        actions.button.side_effect = [False, True]
        with (
            patch.object(pfmea_ui.st, "session_state", session_state),
            patch.object(pfmea_ui.st, "container", return_value=actions),
            patch.object(pfmea_ui.st, "warning"),
            patch.object(pfmea_ui.st, "write"),
            patch.object(pfmea_ui.st, "error"),
            patch.object(pfmea_ui.st, "toast") as toast,
            patch.object(pfmea_ui.st, "rerun", side_effect=RuntimeError("rerun")),
            patch.object(pfmea_ui, "delete_pfmea_records", return_value=2) as delete,
            patch.object(pfmea_ui, "record_audit_event") as audit,
            patch.object(pfmea_ui, "request_table_editor_reset") as reset,
            self.assertRaisesRegex(RuntimeError, "rerun"),
        ):
            pfmea_ui._confirm_pfmea_delete.__wrapped__()
        delete.assert_called_once_with(
            "project", "scenario", "pfmea_entries", ["entry-1", "entry-2"]
        )
        self.assertEqual(audit.call_args.args[4], "Nicole Ervin")
        reset.assert_called_once_with(
            "pfmea_flat_editor_project_scenario__instance__0"
        )
        toast.assert_called_once()
        self.assertNotIn(pfmea_ui.PENDING_DELETE_KEY, session_state)
        destructive_call = actions.button.call_args_list[1]
        self.assertTrue(
            destructive_call.kwargs["key"].startswith("destructive_")
        )

    def test_item_number_is_derived_and_saved_process_function_is_locked(self) -> None:
        _, step_by_id = self._process_steps()
        saved = pd.DataFrame(
            [{"id": "line-1", "work_element_id": "step-1", "item_number": "old",
              "process_function": "old"}]
        )
        prepared = pfmea_ui._prepare_pfmea_process_columns(saved, step_by_id)
        self.assertEqual(prepared.loc[0, "item_number"], "ST-010")
        self.assertEqual(prepared.loc[0, "process_function"], "step-1")

        attempted = prepared.copy()
        attempted.loc[0, "process_function"] = "step-3"
        normalized, changed, locked = pfmea_ui._normalize_pfmea_process_selection(
            attempted, prepared, step_by_id
        )
        self.assertTrue(changed)
        self.assertTrue(locked)
        self.assertEqual(normalized.loc[0, "work_element_id"], "step-1")
        self.assertEqual(normalized.loc[0, "item_number"], "ST-010")
        self.assertEqual(normalized.loc[0, "process_function"], "Load housing")

    def test_high_risk_view_checks_both_rpn_columns_and_sorts_by_higher_value(self) -> None:
        rows = pd.DataFrame(
            [
                {"item_number": "Pitch A", "potential_failure_mode": "Initial risk",
                 "classification": "Safety", "severity": 10, "occurrence": 5,
                 "detection": 3, "rpn": 150, "resulting_rpn": 80},
                {"item_number": "Pitch B", "potential_failure_mode": "Resulting risk",
                 "classification": "Critical Quality", "severity": 8, "occurrence": 4,
                 "detection": 3, "rpn": 96, "resulting_rpn": 180},
                {"item_number": "Pitch C", "potential_failure_mode": "At threshold",
                 "classification": "", "severity": 10, "occurrence": 5,
                 "detection": 2, "rpn": 100, "resulting_rpn": None},
            ]
        )
        filtered = pfmea_ui._high_risk_pfmea_rows(rows, 100)
        self.assertEqual(
            filtered["potential_failure_mode"].tolist(),
            ["Resulting risk", "Initial risk"],
        )
        self.assertEqual(filtered["rpn"].tolist(), [96, 150])
        self.assertEqual(filtered["resulting_rpn"].tolist(), [180, 80])

    def test_live_rpn_previews_use_unsaved_rating_values(self) -> None:
        effects = pd.DataFrame(
            [{"effect_description": "Bracket separates", "severity": 9}]
        )
        causes = pd.DataFrame(
            [{"cause_description": "Tool shuts off early", "occurrence": 3,
              "detection": 4, "detection_review_required": True}]
        )
        initial = pfmea_ui._initial_rpn_preview(effects, causes)
        self.assertEqual(initial.iloc[0]["rpn"], 108)
        self.assertTrue(bool(initial.iloc[0]["detection_review_required"]))

        actions = pd.DataFrame(
            [{"recommended_action": "Add error proofing", "resulting_severity": 8,
              "resulting_occurrence": 3, "resulting_detection": 2,
              "resulting_rpn": 999}]
        )
        resulting = pfmea_ui._resulting_rpn_preview(actions)
        self.assertEqual(resulting.iloc[0]["resulting_rpn"], 48)

    def test_recalculate_preserves_saved_row_identity_order_and_count(self) -> None:
        base = pd.DataFrame(
            [
                {"id": "line-1", "severity": 8, "occurrence": 3, "detection": 4,
                 "resulting_severity": None, "resulting_occurrence": None,
                 "resulting_detection": None},
                {"id": "line-2", "severity": 5, "occurrence": 2, "detection": 3,
                 "resulting_severity": 4, "resulting_occurrence": 2,
                 "resulting_detection": 2},
            ]
        )
        edited = base.iloc[[1, 0]].copy()
        edited.loc[edited["id"] == "line-2", "detection"] = 4
        recalculated = pfmea_ui._stable_recalculated_draft(base, edited)
        self.assertEqual(recalculated["id"].tolist(), ["line-1", "line-2"])
        self.assertEqual(len(recalculated), 2)
        self.assertEqual(recalculated.loc[0, "rpn"], 96)
        self.assertEqual(recalculated.loc[1, "rpn"], 40)
        self.assertEqual(recalculated.loc[1, "resulting_rpn"], 16)

    def test_recalculate_replaces_single_unsaved_draft_instead_of_duplicating_it(self) -> None:
        base = pd.DataFrame(
            [{"id": "", "draft_row_id": "draft-1", "work_element_id": "step-1",
              "item_number": "ST-010", "potential_failure_mode": ""}]
        )
        edited = base.copy()
        edited.loc[0, "potential_failure_mode"] = "Housing is missing"
        recalculated = pfmea_ui._stable_recalculated_draft(base, edited)
        self.assertEqual(len(recalculated), 1)
        self.assertEqual(recalculated.loc[0, "draft_row_id"], "draft-1")
        self.assertEqual(recalculated.loc[0, "potential_failure_mode"], "Housing is missing")

    def test_recalculate_keeps_multiple_unsaved_rows_once_each(self) -> None:
        base = pd.DataFrame(
            [
                {"id": "", "draft_row_id": "draft-1", "work_element_id": "step-1",
                 "item_number": "ST-010", "potential_failure_mode": ""},
                {"id": "", "draft_row_id": "draft-2", "work_element_id": "step-2",
                 "item_number": "ST-010", "potential_failure_mode": ""},
            ]
        )
        edited = base.copy()
        edited["potential_failure_mode"] = ["Housing is missing", "Bracket is loose"]
        recalculated = pfmea_ui._stable_recalculated_draft(base, edited)
        self.assertEqual(len(recalculated), 2)
        self.assertEqual(recalculated["draft_row_id"].tolist(), ["draft-1", "draft-2"])
        self.assertEqual(
            recalculated["potential_failure_mode"].tolist(),
            ["Housing is missing", "Bracket is loose"],
        )

    def test_pfmea_merge_preserves_saved_first_row_and_each_new_row_once(self) -> None:
        rows = pd.DataFrame(
            [
                {"id": "line-1", "draft_row_id": "", "work_element_id": "step-1",
                 "item_number": "ST-010", "potential_failure_mode": "Saved first"},
                {"id": pd.NA, "draft_row_id": "draft-2", "work_element_id": "step-2",
                 "item_number": "ST-010", "potential_failure_mode": pd.NA},
                {"id": pd.NA, "draft_row_id": "draft-3", "work_element_id": "step-3",
                 "item_number": "ST-020", "potential_failure_mode": pd.NA},
            ]
        )
        edited = rows.copy()
        edited.loc[1, "potential_failure_mode"] = "New second"
        edited.loc[2, "potential_failure_mode"] = "New third"
        merged = pfmea_ui._merge_pfmea_filtered_edits(rows, rows, edited)
        before_store = pfmea_ui._stable_recalculated_draft(rows, merged)
        self.assertEqual(len(merged), 3)
        self.assertEqual(len(before_store), 3)
        self.assertEqual(
            before_store["potential_failure_mode"].tolist(),
            ["Saved first", "New second", "New third"],
        )
        self.assertEqual(
            before_store["work_element_id"].tolist(),
            ["step-1", "step-2", "step-3"],
        )

    def test_pfmea_merge_updates_an_existing_second_row_by_saved_identity(self) -> None:
        rows = pd.DataFrame(
            [
                {"id": "line-1", "draft_row_id": "", "potential_failure_mode": "First"},
                {"id": "line-2", "draft_row_id": "", "potential_failure_mode": "Second"},
            ]
        )
        edited = rows.copy()
        edited.loc[1, "potential_failure_mode"] = "Edited second"
        merged = pfmea_ui._merge_pfmea_filtered_edits(rows, rows, edited)
        before_store = pfmea_ui._stable_recalculated_draft(rows, merged)
        self.assertEqual(len(before_store), 2)
        self.assertEqual(before_store.loc[0, "potential_failure_mode"], "First")
        self.assertEqual(before_store.loc[1, "potential_failure_mode"], "Edited second")

    def test_process_selection_accepts_editor_label_and_assigns_stable_draft_id(self) -> None:
        _, step_by_id = self._process_steps()
        original = pd.DataFrame(
            columns=["id", "draft_row_id", "work_element_id", "item_number", "process_function"]
        )
        label = pfmea_ui._process_step_option_label(step_by_id["step-1"])
        edited = pd.DataFrame(
            [{"id": "", "draft_row_id": "", "work_element_id": "",
              "item_number": "", "process_function": label}]
        )
        normalized, changed, locked = pfmea_ui._normalize_pfmea_process_selection(
            edited, original, step_by_id
        )
        self.assertTrue(changed)
        self.assertFalse(locked)
        self.assertEqual(normalized.loc[0, "work_element_id"], "step-1")
        self.assertEqual(normalized.loc[0, "item_number"], "ST-010")
        self.assertEqual(normalized.loc[0, "process_function"], "Load housing")
        self.assertTrue(str(normalized.loc[0, "draft_row_id"]).strip())

    def test_pfmea_line_label_uses_friendly_text_and_correct_em_dashes(self) -> None:
        _, step_by_id = self._process_steps()
        row = pd.Series(
            {
                "work_element_id": "step-1",
                "item_number": "ST-010",
                "process_function": "Stored fallback",
                "potential_failure_mode": "Failure mode text",
                "potential_causes": "Cause text",
            }
        )

        label = pfmea_ui._pfmea_line_label(row, step_by_id)

        self.assertEqual(
            label,
            "ST-010 — Load housing — Failure mode text — Cause text",
        )
        self.assertEqual(label.count("\u2014"), 3)
        self.assertNotIn("\u00e2\u20ac\u201d", label)

        fallback_label = pfmea_ui._pfmea_line_label(pd.Series(dtype="object"), {})
        self.assertEqual(
            fallback_label,
            "Unassigned — Unnamed Process Function — Blank Failure Mode — Blank Cause",
        )

    def test_copy_and_duplicate_selectors_keep_hidden_keys_and_use_friendly_labels(self) -> None:
        _, step_by_id = self._process_steps()
        rows = pd.DataFrame(
            [
                {
                    "id": "line-target",
                    "cause_id": "cause-target",
                    "work_element_id": "step-1",
                    "item_number": "ST-010",
                    "process_function": "Load housing",
                    "potential_failure_mode": "Target failure",
                    "potential_causes": "Target cause",
                },
                {
                    "id": "line-source",
                    "cause_id": "cause-source",
                    "work_element_id": "step-2",
                    "item_number": "ST-010",
                    "process_function": "Install bracket",
                    "potential_failure_mode": "Source failure",
                    "potential_causes": "Source cause",
                },
            ]
        )
        targets = {
            pfmea_ui._cause_target_key(row): row for _, row in rows.iterrows()
        }
        captured: dict[str, dict[str, object]] = {}

        def selectbox(label, options, format_func=None, **_kwargs):
            option_values = list(options)
            selected = option_values[0]
            captured[label] = {
                "options": option_values,
                "display": format_func(selected) if format_func else selected,
            }
            return selected

        with (
            patch.object(pfmea_ui.st, "expander", return_value=MagicMock()),
            patch.object(pfmea_ui.st, "container", return_value=MagicMock()),
            patch.object(pfmea_ui.st, "subheader"),
            patch.object(pfmea_ui.st, "selectbox", side_effect=selectbox),
            patch.object(pfmea_ui.st, "multiselect", return_value=[]),
            patch.object(pfmea_ui.st, "button", return_value=False),
            patch.object(pfmea_ui, "_control_label_map", return_value={}),
        ):
            pfmea_ui._render_control_copy_workflow(
                "project",
                "scenario",
                targets,
                "cause:cause-target",
                rows,
                "draft",
                "editor",
                step_by_id,
            )
            pfmea_ui._render_pfmea_duplicate_workflow(
                "project", "scenario", rows, "draft", "editor", step_by_id
            )

        self.assertEqual(
            captured["Source PFMEA Cause"]["options"], ["cause:cause-source"]
        )
        self.assertEqual(
            captured["Source PFMEA Cause"]["display"],
            "ST-010 — Install bracket — Source failure — Source cause",
        )
        self.assertEqual(
            captured["PFMEA line to duplicate"]["options"],
            ["saved:line-target", "saved:line-source"],
        )
        self.assertEqual(
            captured["PFMEA line to duplicate"]["display"],
            "ST-010 — Load housing — Target failure — Target cause",
        )
        self.assertNotIn(
            "line-target", str(captured["PFMEA line to duplicate"]["display"])
        )

    def test_process_function_only_row_survives_editor_cleanup_and_save_preparation(self) -> None:
        _, step_by_id = self._process_steps()
        original = pd.DataFrame(
            columns=[
                "id", "draft_row_id", "work_element_id", "item_number",
                "process_function", "potential_failure_mode", "potential_effects",
                "potential_causes", "severity", "occurrence", "detection", "rpn",
                "resulting_severity", "resulting_occurrence", "resulting_detection",
                "resulting_rpn",
            ]
        )
        selected = pd.DataFrame(
            [{"id": "", "draft_row_id": "", "work_element_id": "",
              "item_number": "", "process_function": "step-1"}]
        ).reindex(columns=original.columns)
        normalized, _, _ = pfmea_ui._normalize_pfmea_process_selection(
            selected, original, step_by_id
        )
        cleaned = pfmea_ui._drop_untouched_rows(
            normalized,
            identifying_columns=[
                "item_number", "potential_failure_mode", "potential_effects", "potential_causes"
            ],
        )
        complete = pfmea_ui._merge_pfmea_filtered_edits(original, original, cleaned)
        before_store = pfmea_ui._stable_recalculated_draft(original, complete)
        self.assertEqual(len(before_store), 1)
        self.assertEqual(before_store.loc[0, "work_element_id"], "step-1")
        self.assertEqual(before_store.loc[0, "item_number"], "ST-010")
        self.assertTrue(pd.isna(before_store.loc[0, "rpn"]))

    def test_duplicate_line_clears_ids_completion_and_inactive_controls(self) -> None:
        source = pd.Series(
            {
                "id": "line-1",
                "entry_id": "entry-1",
                "effect_id": "effect-1",
                "cause_id": "cause-1",
                "risk_row_id": "risk-1",
                "action_id": "action-1",
                "draft_row_id": "",
                "work_element_id": "step-1",
                "item_number": "ST-010",
                "process_function": "Load housing",
                "potential_failure_mode": "Housing loose",
                "potential_effects": "Noise",
                "severity": 8,
                "classification": "Critical Quality",
                "potential_causes": "Fastener loose",
                "occurrence": 3,
                "prevention_controls": ["quality:q-1", "manual:m-active", "manual:m-old"],
                "detection_controls": ["quality:q-1"],
                "detection": 4,
                "rpn": 1,
                "recommended_action": "Improve fixture",
                "responsibility_target": "AQE | 2026-10-01",
                "actions_taken": "Fixture installed",
                "resulting_severity": 7,
                "resulting_occurrence": 2,
                "resulting_detection": 2,
                "resulting_rpn": 28,
                "upstream_changes": True,
                "detection_review_required": True,
                "control_source_review_required": True,
            }
        )

        def candidates(_project, _scenario, _work, control_type, _included):
            rows = [
                {"source_key": "quality:q-1", "label": "Quality control", "active": True},
            ]
            if control_type == "Prevention":
                rows.extend(
                    [
                        {"source_key": "manual:m-active", "label": "Active manual", "active": True},
                        {"source_key": "manual:m-old", "label": "Inactive manual", "active": False},
                    ]
                )
            return pd.DataFrame(rows)

        with patch.object(pfmea_ui, "pfmea_control_candidates", side_effect=candidates):
            duplicate, omitted = pfmea_ui._duplicate_pfmea_line(
                source, "project", "scenario"
            )
        self.assertTrue(duplicate["draft_row_id"])
        for column in ("id", "entry_id", "effect_id", "cause_id", "risk_row_id", "action_id"):
            self.assertEqual(duplicate[column], "")
        self.assertEqual(
            duplicate["prevention_controls"], ["quality:q-1", "manual:m-active"]
        )
        self.assertEqual(duplicate["detection_controls"], ["quality:q-1"])
        self.assertEqual(omitted, ["manual:m-old"])
        self.assertEqual(duplicate["actions_taken"], "")
        self.assertTrue(pd.isna(duplicate["resulting_rpn"]))
        self.assertEqual(duplicate["rpn"], 96)

    def test_recognized_pasted_row_copy_omits_controls_and_completion(self) -> None:
        base = pfmea_ui._frame(
            pd.DataFrame(
                [{
                    "id": "line-1",
                    "entry_id": "entry-1",
                    "effect_id": "effect-1",
                    "cause_id": "cause-1",
                    "risk_row_id": "risk-1",
                    "action_id": "action-1",
                    "work_element_id": "step-1",
                    "potential_failure_mode": "Housing loose",
                    "potential_effects": "Noise",
                    "severity": 8,
                    "classification": "",
                    "potential_causes": "Fastener loose",
                    "occurrence": 3,
                    "detection": 4,
                    "prevention_controls": ["quality:q-1"],
                    "detection_controls": ["manual:m-1"],
                    "recommended_action": "Improve fixture",
                    "responsibility_target": "AQE | 2026-10-01",
                    "actions_taken": "Fixture installed",
                    "resulting_severity": 7,
                    "resulting_occurrence": 2,
                    "resulting_detection": 2,
                    "resulting_rpn": 28,
                }]
            ),
            pfmea_ui.PFMEA_FLAT_COLUMNS,
        )
        pasted = base.iloc[0].copy()
        pasted["id"] = ""
        pasted["draft_row_id"] = "pasted-1"
        for column in ("entry_id", "effect_id", "cause_id", "risk_row_id", "action_id"):
            pasted[column] = ""
        combined = pd.concat([base, pd.DataFrame([pasted])], ignore_index=True, sort=False)
        normalized, copied_ids = pfmea_ui._recognize_pasted_line_copies(base, combined)
        copied = normalized.iloc[1]
        self.assertEqual(copied_ids, {"pasted-1"})
        self.assertEqual(copied["prevention_controls"], [])
        self.assertEqual(copied["detection_controls"], [])
        self.assertEqual(copied["actions_taken"], "")
        self.assertTrue(pd.isna(copied["resulting_rpn"]))
        self.assertEqual(copied["rpn"], 96)

    def test_shared_effect_edit_propagates_by_hidden_identity(self) -> None:
        editor_rows = pd.DataFrame(
            [
                {"effect_id": "effect-1", "potential_effects": "Old", "severity": 8},
                {"effect_id": "effect-1", "potential_effects": "Old", "severity": 8},
                {"effect_id": "effect-2", "potential_effects": "Other", "severity": 4},
            ]
        )
        state = {
            "edited_rows": {"0": {"potential_effects": "Updated effect"}},
            "added_rows": [],
            "deleted_rows": [],
        }
        updated, propagated, conflicts = pfmea_ui._propagate_shared_editor_changes(
            editor_rows.copy(), editor_rows, state
        )
        self.assertEqual(updated["potential_effects"].tolist(), [
            "Updated effect", "Updated effect", "Other"
        ])
        self.assertEqual(propagated, ["potential_effects"])
        self.assertEqual(conflicts, [])

    def test_compatible_control_paste_replaces_and_propagates_by_cause(self) -> None:
        _, step_by_id = self._process_steps()
        base = pfmea_ui._frame(
            pd.DataFrame(
                [
                    {"id": "line-1", "cause_id": "cause-1", "work_element_id": "step-1",
                     "item_number": "ST-010", "process_function": "Load housing",
                     "prevention_controls": ["manual:old"], "detection_controls": []},
                    {"id": "line-2", "cause_id": "cause-1", "work_element_id": "step-1",
                     "item_number": "ST-010", "process_function": "Load housing",
                     "prevention_controls": ["manual:old"], "detection_controls": []},
                    {"id": "line-3", "cause_id": "cause-2", "work_element_id": "step-2",
                     "item_number": "ST-010", "process_function": "Install bracket",
                     "prevention_controls": ["manual:other"], "detection_controls": []},
                ]
            ),
            pfmea_ui.PFMEA_FLAT_COLUMNS,
        )
        normalized = base.copy()
        normalized.at[0, "prevention_controls"] = [
            "quality:q-1", "manual:new", "quality:q-1"
        ]
        state = {
            "edited_rows": {
                0: {"prevention_controls": [
                    "quality:q-1", "manual:new", "quality:q-1"
                ]}
            },
            "added_rows": [],
            "deleted_rows": [],
        }
        with patch.object(
            pfmea_ui,
            "_valid_controls_for_step",
            return_value=(["quality:q-1", "manual:new"], []),
        ):
            updated, pending, warnings, instructions, conflicts = (
                pfmea_ui._apply_control_cell_edits(
                    base,
                    normalized,
                    normalized,
                    base,
                    state,
                    project_id="project",
                    scenario_id="scenario",
                    step_by_id=step_by_id,
                    control_labels={},
                )
            )
        self.assertEqual(
            updated.loc[updated["cause_id"].eq("cause-1"), "prevention_controls"].tolist(),
            [["quality:q-1", "manual:new"], ["quality:q-1", "manual:new"]],
        )
        self.assertEqual(updated.iloc[2]["prevention_controls"], ["manual:other"])
        self.assertEqual((pending, warnings, instructions, conflicts), ([], [], [], []))

    def test_quality_mismatch_waits_for_compatible_only_confirmation(self) -> None:
        _, step_by_id = self._process_steps()
        base = pfmea_ui._frame(
            pd.DataFrame([{
                "id": "line-1", "cause_id": "cause-1", "work_element_id": "step-1",
                "item_number": "ST-010", "process_function": "Load housing",
                "potential_causes": "Loose screw",
                "prevention_controls": ["manual:old"],
                "detection_controls": [],
            }]),
            pfmea_ui.PFMEA_FLAT_COLUMNS,
        )
        normalized = base.copy()
        normalized.at[0, "prevention_controls"] = ["quality:wrong-step", "manual:new"]
        state = {
            "edited_rows": {0: {"prevention_controls": [
                "quality:wrong-step", "manual:new"
            ]}},
            "added_rows": [],
            "deleted_rows": [],
        }
        with patch.object(
            pfmea_ui,
            "_valid_controls_for_step",
            return_value=(["manual:new"], ["quality:wrong-step"]),
        ):
            updated, pending, warnings, instructions, conflicts = (
                pfmea_ui._apply_control_cell_edits(
                    base,
                    normalized,
                    normalized,
                    base,
                    state,
                    project_id="project",
                    scenario_id="scenario",
                    step_by_id=step_by_id,
                    control_labels={"quality:wrong-step": "Quality — Wrong step"},
                )
            )
        self.assertEqual(updated.iloc[0]["prevention_controls"], ["manual:old"])
        self.assertEqual(pending[0]["replacement"], ["manual:new"])
        self.assertEqual(pending[0]["incompatible_labels"], ["Quality — Wrong step"])
        self.assertNotIn("quality:wrong-step", str(pending[0]["incompatible_labels"]))
        self.assertEqual((warnings, instructions, conflicts), ([], [], []))

    def test_inactive_manual_control_is_omitted_without_dialog(self) -> None:
        _, step_by_id = self._process_steps()
        base = pfmea_ui._frame(
            pd.DataFrame([{
                "id": "line-1", "cause_id": "cause-1", "work_element_id": "step-1",
                "item_number": "ST-010", "process_function": "Load housing",
                "prevention_controls": [], "detection_controls": ["manual:old"],
                "detection": 7,
            }]),
            pfmea_ui.PFMEA_FLAT_COLUMNS,
        )
        normalized = base.copy()
        normalized.at[0, "detection_controls"] = ["manual:active", "manual:inactive"]
        state = {
            "edited_rows": {0: {"detection_controls": [
                "manual:active", "manual:inactive"
            ]}},
            "added_rows": [],
            "deleted_rows": [],
        }
        with patch.object(
            pfmea_ui,
            "_valid_controls_for_step",
            return_value=(["manual:active"], ["manual:inactive"]),
        ):
            updated, pending, warnings, instructions, conflicts = (
                pfmea_ui._apply_control_cell_edits(
                    base,
                    normalized,
                    normalized,
                    base,
                    state,
                    project_id="project",
                    scenario_id="scenario",
                    step_by_id=step_by_id,
                    control_labels={"manual:inactive": "Manual — Retired check"},
                )
            )
        self.assertEqual(updated.iloc[0]["detection_controls"], ["manual:active"])
        self.assertEqual(updated.iloc[0]["detection"], 7)
        self.assertTrue(bool(updated.iloc[0]["detection_review_required"]))
        self.assertEqual(pending, [])
        self.assertIn("Manual — Retired check", warnings[0])
        self.assertEqual((instructions, conflicts), ([], []))

    def test_control_paste_without_process_function_leaves_target_unchanged(self) -> None:
        base = pfmea_ui._frame(
            pd.DataFrame([{
                "id": "", "draft_row_id": "draft-1", "work_element_id": "",
                "item_number": "", "process_function": "",
                "prevention_controls": [], "detection_controls": [],
            }]),
            pfmea_ui.PFMEA_FLAT_COLUMNS,
        )
        normalized = base.copy()
        normalized.at[0, "prevention_controls"] = ["manual:new"]
        state = {
            "edited_rows": {0: {"prevention_controls": ["manual:new"]}},
            "added_rows": [],
            "deleted_rows": [],
        }
        updated, pending, warnings, instructions, conflicts = (
            pfmea_ui._apply_control_cell_edits(
                base,
                normalized,
                normalized,
                base,
                state,
                project_id="project",
                scenario_id="scenario",
                step_by_id={},
                control_labels={},
            )
        )
        self.assertEqual(updated.iloc[0]["prevention_controls"], [])
        self.assertIn("Choose Process Function", instructions[0])
        self.assertEqual((pending, warnings, conflicts), ([], [], []))

    def test_confirmed_compatible_paste_preserves_detection_rating(self) -> None:
        draft = pfmea_ui._frame(
            pd.DataFrame([{
                "id": "line-1", "cause_id": "cause-1", "work_element_id": "step-1",
                "prevention_controls": [], "detection_controls": ["manual:old"],
                "detection": 6,
            }]),
            pfmea_ui.PFMEA_FLAT_COLUMNS,
        )
        state = {
            "project_id": "project",
            "scenario_id": "scenario",
            "draft": draft,
            pfmea_ui.PENDING_CONTROL_PASTE_KEY: {
                "project_id": "project",
                "scenario_id": "scenario",
                "draft_key": "draft",
                "editor_key": "editor",
                "changes": [{
                    "target_key": "cause:cause-1",
                    "column": "detection_controls",
                    "control_type": "Detection",
                    "line_label": "ST-010 — Load housing — Failure — Cause",
                    "original": ["manual:old"],
                    "replacement": ["manual:new"],
                    "incompatible_labels": ["Quality — Wrong step"],
                }],
            },
        }
        actions = MagicMock()
        actions.button.side_effect = [False, True]
        with (
            patch.object(pfmea_ui.st, "session_state", state),
            patch.object(pfmea_ui.st, "container", return_value=actions),
            patch.object(pfmea_ui.st, "warning"),
            patch.object(pfmea_ui.st, "markdown"),
            patch.object(pfmea_ui.st, "write"),
            patch.object(pfmea_ui.st, "caption"),
            patch.object(pfmea_ui.st, "error"),
            patch.object(pfmea_ui.st, "rerun", side_effect=RuntimeError("rerun")),
            patch.object(pfmea_ui, "request_table_editor_reset"),
            self.assertRaisesRegex(RuntimeError, "rerun"),
        ):
            pfmea_ui._confirm_pfmea_control_paste.__wrapped__()
        changed = state["draft"].iloc[0]
        self.assertEqual(changed["detection_controls"], ["manual:new"])
        self.assertEqual(changed["detection"], 6)
        self.assertTrue(bool(changed["detection_review_required"]))
        self.assertNotIn(pfmea_ui.PENDING_CONTROL_PASTE_KEY, state)

    def test_process_change_is_staged_until_quality_removal_is_confirmed(self) -> None:
        _, step_by_id = self._process_steps()
        row = pfmea_ui._frame(
            pd.DataFrame(
                [{
                    "id": "",
                    "draft_row_id": "draft-copy",
                    "work_element_id": "step-1",
                    "item_number": "ST-010",
                    "process_function": "step-1",
                    "prevention_controls": ["quality:q-1", "manual:m-1"],
                    "detection_controls": ["quality:q-2"],
                    "detection": 4,
                }]
            ),
            pfmea_ui.PFMEA_FLAT_COLUMNS,
        )
        state = {
            "editor": {
                "edited_rows": {0: {"process_function": "step-3"}},
                "added_rows": [],
                "deleted_rows": [],
            },
            "project_id": "project",
            "scenario_id": "scenario",
        }
        with (
            patch.object(pfmea_ui.st, "session_state", state),
            patch.object(pfmea_ui, "request_table_editor_reset"),
        ):
            pfmea_ui._stage_pfmea_process_selection(
                "editor",
                "draft",
                row,
                row,
                row,
                step_by_id,
                "project",
                "scenario",
                {"quality:q-1": "Quality one", "quality:q-2": "Quality two"},
            )
        self.assertEqual(state["draft"].loc[0, "work_element_id"], "step-1")
        self.assertIn(pfmea_ui.PENDING_PROCESS_CHANGE_KEY, state)

        actions = MagicMock()
        actions.button.side_effect = [False, True]
        steps, _ = self._process_steps()
        with (
            patch.object(pfmea_ui.st, "session_state", state),
            patch.object(pfmea_ui.st, "container", return_value=actions),
            patch.object(pfmea_ui.st, "warning"),
            patch.object(pfmea_ui.st, "write"),
            patch.object(pfmea_ui.st, "error"),
            patch.object(pfmea_ui.st, "toast"),
            patch.object(pfmea_ui.st, "rerun", side_effect=RuntimeError("rerun")),
            patch.object(pfmea_ui, "pfmea_process_steps", return_value=steps),
            patch.object(pfmea_ui, "request_table_editor_reset"),
            self.assertRaisesRegex(RuntimeError, "rerun"),
        ):
            pfmea_ui._confirm_pfmea_process_change.__wrapped__()
        changed = state["draft"].iloc[0]
        self.assertEqual(changed["work_element_id"], "step-3")
        self.assertEqual(changed["item_number"], "ST-020")
        self.assertEqual(changed["prevention_controls"], ["manual:m-1"])
        self.assertEqual(changed["detection_controls"], [])
        self.assertEqual(changed["detection"], 4)
        self.assertTrue(bool(changed["detection_review_required"]))

    def test_pfmea_export_preserves_line_breaks_and_wraps_cells(self) -> None:
        exported = pfmea_ui._pfmea_export_bytes(
            pd.DataFrame([{"Potential Failure Mode": "Loose screw\nMissing screw"}])
        )
        workbook = load_workbook(BytesIO(exported))
        cell = workbook.active["A2"]
        self.assertEqual(cell.value, "Loose screw\nMissing screw")
        self.assertTrue(cell.alignment.wrap_text)

    def test_populated_pfmea_tab_loads_without_streamlit_exceptions(self) -> None:
        scenarios = [
            {
                "id": "scenario-1",
                "project_id": "project-1",
                "name": "Current plan",
                "revision_label": "A",
                "takt_time_s": 60,
            }
        ]
        steps = pd.DataFrame(
            [
                {
                    "id": "step-1",
                    "sequence": 10,
                    "pitch": "ST-010",
                    "work_element": "Install bracket",
                    "description": "Install and secure the bracket",
                    "location": "LH front",
                    "status": "Draft",
                    "updated_at": "2026-08-31T12:00:00+00:00",
                }
            ]
        )
        entries = pd.DataFrame(
            [
                {
                    "id": "entry-1",
                    "potential_failure_mode": "Bracket is loose",
                    "class_code": "",
                    "effect_count": 1,
                    "cause_count": 1,
                    "maximum_rpn": 96,
                    "upstream_changes": False,
                    "updated_at": "2026-08-31T12:00:00+00:00",
                }
            ]
        )
        effects = pd.DataFrame(
            [{"id": "effect-1", "effect_description": "Bracket separates", "severity": 8,
              "sequence": 10}]
        )
        causes = pd.DataFrame(
            [{"id": "cause-1", "cause_description": "Tool shuts off early", "occurrence": 3,
              "detection": 4, "sequence": 10}]
        )
        flat_rows = pd.DataFrame(
            [{
                "id": "entry-1|effect-1|cause-1|risk-1|-", "entry_id": "entry-1",
                "effect_id": "effect-1", "cause_id": "cause-1", "risk_row_id": "risk-1",
                "action_id": "", "work_element_id": "step-1",
                "item_number": "ST-010",
                "process_function": "Install bracket",
                "potential_failure_mode": "Bracket is loose",
                "potential_effects": "Bracket separates", "severity": 8,
                "classification": "", "potential_causes": "Tool shuts off early",
                "occurrence": 3, "prevention_controls": [],
                "detection_controls": [], "detection": 4,
                "rpn": 96, "recommended_action": "", "responsibility_target": "",
                "actions_taken": "", "resulting_severity": None,
                "resulting_occurrence": None, "resulting_detection": None,
                "resulting_rpn": 120, "upstream_changes": False,
                "detection_review_required": False,
                "control_source_review_required": False,
            }]
        )
        with (
            patch.object(store, "planning_scenarios", return_value=scenarios),
            patch.object(store, "audit_history", return_value=pd.DataFrame()),
            patch.object(quality_store, "quality_requirements", return_value=pd.DataFrame()),
            patch.object(pfmea_ui, "pfmea_process_steps", return_value=steps),
            patch.object(pfmea_ui, "pfmea_entries", return_value=entries),
            patch.object(pfmea_ui, "pfmea_flat_rows", return_value=flat_rows),
            patch.object(pfmea_ui, "pfmea_effects", return_value=effects),
            patch.object(pfmea_ui, "pfmea_causes", return_value=causes),
            patch.object(pfmea_ui, "pfmea_actions", return_value=pd.DataFrame()),
            patch.object(pfmea_ui, "migrate_legacy_pfmea_controls", return_value={"row_count": 0}),
            patch.object(pfmea_ui, "pfmea_control_selections", return_value=pd.DataFrame()),
            patch.object(pfmea_ui, "pfmea_control_candidates", return_value=pd.DataFrame(
                columns=["source_key", "label", "active"]
            )),
            patch.object(pfmea_ui, "pfmea_control_options", return_value=pd.DataFrame()),
        ):
            app = AppTest.from_file(str(PAGE_PATH))
            app.session_state["project_id"] = "project-1"
            app.session_state["scenario_id"] = "scenario-1"
            app.session_state["current_editor"] = "PFMEA tester"
            app.session_state["quality_page_tabs_project-1"] = "PFMEA"
            app.run(timeout=15)
            self.assertEqual(app.number_input[0].value, 100)
            app.number_input[0].set_value(130).run(timeout=15)

        self.assertEqual(len(app.exception), 0)
        self.assertIn("Process FMEA", [heading.value for heading in app.subheader])
        self.assertIn("PFMEA line items", [heading.value for heading in app.subheader])
        self.assertIn("Saved RPN by PFMEA line", [heading.value for heading in app.subheader])
        self.assertIn("High-risk PFMEA lines", [heading.value for heading in app.subheader])
        self.assertIn("Select Current Process Controls", [heading.value for heading in app.subheader])
        self.assertTrue(
            {"Prevention controls", "Detection controls"}.issubset(
                {widget.label for widget in app.multiselect}
            )
        )
        self.assertIn("RPN review threshold", [widget.label for widget in app.number_input])
        self.assertTrue(
            any(
                "No PFMEA lines have RPN or Resulting RPN greater than 130."
                in caption.value
                for caption in app.caption
            )
        )
        self.assertIn("Recalculate RPN", [button.label for button in app.button])
        self.assertIn("Duplicate selected PFMEA line", [button.label for button in app.button])
        self.assertIn("Save & Refresh", [button.label for button in app.button])
        self.assertIn("Requirements", [tab.label for tab in app.tabs])
        self.assertIn("PFMEA", [tab.label for tab in app.tabs])


if __name__ == "__main__":
    unittest.main()
