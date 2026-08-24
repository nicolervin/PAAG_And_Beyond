from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from utils import scope_ui
from utils.scope_ui import (
    _activate_scenario,
    _scope_details,
    page_title_with_scope,
    scenario_view_selector,
)


class ScopeDetailsTests(unittest.TestCase):
    def test_project_scope_uses_locked_wording(self) -> None:
        label, icon, help_text = _scope_details("project")

        self.assertEqual(label, "Project-wide")
        self.assertEqual(icon, ":material/public:")
        self.assertEqual(
            help_text,
            "Changes on this page affect every planning scenario in this project.",
        )

    def test_scenario_scope_includes_active_scenario_name(self) -> None:
        label, icon, help_text = _scope_details(
            "scenario", scenario_name="Current plan"
        )

        self.assertEqual(label, "Scenario-specific")
        self.assertEqual(icon, ":material/account_tree:")
        self.assertEqual(
            help_text,
            "Changes on this page only affect the Current plan scenario. Other scenarios are not affected.",
        )

    def test_scenario_aware_scope_requires_page_specific_help(self) -> None:
        with self.assertRaisesRegex(ValueError, "page-specific tooltip"):
            _scope_details("scenario-aware")

    def test_scenario_aware_scope_uses_concise_label(self) -> None:
        label, icon, help_text = _scope_details(
            "scenario-aware", help_text="Shared data with scenario-specific visibility."
        )

        self.assertEqual(label, "Scenario-aware")
        self.assertEqual(icon, ":material/hub:")
        self.assertEqual(
            help_text, "Shared data with scenario-specific visibility."
        )

    def test_page_selector_defaults_to_latest_and_persists_for_the_session(self) -> None:
        session_state: dict[str, object] = {"scenario_id": None}
        scenarios = [
            {"id": "latest", "revision_label": "3", "name": "Latest plan"},
            {"id": "older", "revision_label": "2", "name": "Older plan"},
        ]
        parent = Mock()
        parent.selectbox.return_value = "latest"

        with (
            patch.object(scope_ui, "planning_scenarios", return_value=scenarios),
            patch.object(scope_ui.st, "session_state", session_state),
        ):
            selected = scenario_view_selector(
                parent,
                project_id="project-1",
                key="page_scenario_view_test",
                label_visibility="collapsed",
            )

        self.assertEqual(selected["id"], "latest")
        self.assertEqual(session_state["scenario_id"], "latest")
        self.assertEqual(session_state["page_scenario_view_test"], "latest")
        self.assertEqual(parent.selectbox.call_args.kwargs["persist_state"], "session")

    def test_page_selector_change_updates_cross_page_scenario(self) -> None:
        session_state = {"page_scenario_view_test": "scenario-2"}

        with patch.object(scope_ui.st, "session_state", session_state):
            _activate_scenario("page_scenario_view_test")

        self.assertEqual(session_state["scenario_id"], "scenario-2")

    def test_sidebar_selector_synchronizes_from_cross_page_scenario(self) -> None:
        session_state = {
            "scenario_id": "scenario-2",
            "global_scenario": "scenario-1",
        }
        scenarios = [
            {"id": "scenario-2", "revision_label": "2", "name": "Second"},
            {"id": "scenario-1", "revision_label": "1", "name": "First"},
        ]
        parent = Mock()
        parent.selectbox.return_value = "scenario-2"

        with (
            patch.object(scope_ui, "planning_scenarios", return_value=scenarios),
            patch.object(scope_ui.st, "session_state", session_state),
        ):
            scenario_view_selector(
                parent,
                project_id="project-1",
                key="global_scenario",
            )

        self.assertEqual(session_state["global_scenario"], "scenario-2")

    def test_scenario_page_places_save_as_action_beside_selector(self) -> None:
        row = Mock()
        row.button.return_value = True
        selected = {
            "id": "scenario-1",
            "name": "Current plan",
            "revision_label": "1",
            "takt_time_s": 60,
        }
        session_state = {"project_id": "project-1"}

        with (
            patch.object(scope_ui.st, "session_state", session_state),
            patch.object(scope_ui.st, "container", return_value=row),
            patch.object(scope_ui, "scenario_view_selector", return_value=selected),
            patch.object(scope_ui, "save_as_scenario_dialog") as dialog,
        ):
            page_title_with_scope(
                "Yamazumi", scope="scenario", scenario_name="Current plan"
            )

        row.button.assert_called_once()
        self.assertEqual(row.button.call_args.args[0], "Save as scenario")
        dialog.assert_called_once_with(
            project_id="project-1",
            source_scenario=selected,
            key_prefix="yamazumi",
        )

    def test_scenario_aware_page_does_not_offer_save_as_action(self) -> None:
        row = Mock()
        session_state = {"project_id": "project-1"}

        with (
            patch.object(scope_ui.st, "session_state", session_state),
            patch.object(scope_ui.st, "container", return_value=row),
            patch.object(scope_ui, "scenario_view_selector", return_value={"id": "scenario-1"}),
        ):
            page_title_with_scope(
                "Parts Catalog",
                scope="scenario-aware",
                help_text="The catalog is shared; activity follows the selected scenario.",
            )

        row.button.assert_not_called()


if __name__ == "__main__":
    unittest.main()
