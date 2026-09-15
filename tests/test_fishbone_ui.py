from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import pandas as pd

from utils.fishbone_ui import (
    _set_sidebar_page_scope,
    fishbone_context_label,
    nearest_valid_section,
    ordered_section_ids,
    ordered_yamazumi_area_ids,
    remember_preferred_section,
    render_fishbone_sidebar_context,
    section_breadcrumb_labels,
)
from utils import fishbone_ui


class FishboneUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sections = pd.DataFrame(
            [
                {"id": "main-a", "name": "Main A", "parent_id": None, "active": 1},
                {"id": "child-a", "name": "Child A", "parent_id": "main-a", "active": 1},
                {"id": "grandchild", "name": "Grandchild", "parent_id": "child-a", "active": 0},
                {"id": "main-b", "name": "Main B", "parent_id": None, "active": 1},
                {"id": "orphan", "name": "Orphan", "parent_id": "missing", "active": 1},
            ]
        )
        self.all_ids = self.sections["id"].tolist()

    def test_breadcrumbs_follow_ancestry_and_preserve_orphan_label(self) -> None:
        labels = section_breadcrumb_labels(self.sections)

        self.assertEqual(labels["main-a"], "Main A")
        self.assertEqual(labels["child-a"], "Main A › Child A")
        self.assertEqual(
            labels["grandchild"], "Main A › Child A › Grandchild"
        )
        self.assertEqual(labels["orphan"], "Orphan")

    def test_active_options_retain_an_explicit_inactive_current_value(self) -> None:
        self.assertEqual(
            ordered_section_ids(self.sections, active_only=True),
            ["main-a", "child-a", "main-b", "orphan"],
        )
        self.assertEqual(
            ordered_section_ids(
                self.sections, active_only=True, retain_ids=["grandchild"]
            ),
            self.all_ids,
        )

    def test_nearest_valid_scans_forward_then_backward(self) -> None:
        state: dict[str, object] = {}
        remember_preferred_section(state, "project", "child-a", self.all_ids)
        self.assertEqual(
            nearest_valid_section(
                state, "project", self.all_ids, ["main-a", "main-b"]
            ),
            "main-b",
        )

        remember_preferred_section(state, "project", "orphan", self.all_ids)
        self.assertEqual(
            nearest_valid_section(
                state, "project", self.all_ids, ["main-a", "main-b"]
            ),
            "main-b",
        )

    def test_deleted_preference_uses_remembered_ordinal(self) -> None:
        state: dict[str, object] = {}
        remember_preferred_section(state, "project", "child-a", self.all_ids)
        remaining = ["main-a", "grandchild", "main-b", "orphan"]

        self.assertEqual(
            nearest_valid_section(state, "project", remaining, remaining),
            "grandchild",
        )

    def test_context_labels_cover_all_single_multiple_and_unlinked(self) -> None:
        labels = section_breadcrumb_labels(self.sections)
        active = ["main-a", "child-a", "main-b", "orphan"]

        self.assertEqual(
            fishbone_context_label([], active, labels, all_selected=True),
            "All active sections",
        )
        self.assertEqual(
            fishbone_context_label(["child-a"], active, labels),
            "Main A › Child A",
        )
        self.assertEqual(
            fishbone_context_label(["main-a", "main-b"], active, labels),
            "2 sections selected",
        )
        self.assertEqual(
            fishbone_context_label([], active, labels, unlinked=True),
            "Unlinked",
        )

    def test_yamazumi_areas_follow_sections_then_unlinked_names(self) -> None:
        areas = pd.DataFrame(
            [
                {"id": "unlinked-z", "name": "Zulu", "section_id": None},
                {"id": "area-b", "name": "Area B", "section_id": "main-b"},
                {"id": "unlinked-a", "name": "Alpha", "section_id": None},
                {"id": "area-a", "name": "Area A", "section_id": "main-a"},
            ]
        )

        self.assertEqual(
            ordered_yamazumi_area_ids(areas, self.all_ids),
            ["area-a", "area-b", "unlinked-a", "unlinked-z"],
        )

    def test_sidebar_command_changes_view_state_only(self) -> None:
        state: dict[str, object] = {"selector": "child-a"}
        with patch.object(fishbone_ui.st, "session_state", state):
            _set_sidebar_page_scope(
                "selector",
                "Process at a Glance",
                "project",
                "scenario",
                {},
                self.all_ids,
            )
        self.assertEqual(
            state["process_pairing_section_scenario"], "child-a"
        )
        self.assertEqual(state["fishbone_preferred_section_project"], "child-a")
        self.assertNotIn("project_id", state)
        self.assertNotIn("scenario_id", state)

    def test_sidebar_renders_process_context_in_breadcrumb_order(self) -> None:
        sections = self.sections.assign(
            section_type=[
                "Main spine", "Subassembly", "Subassembly", "Main spine", "Subassembly"
            ],
            sequence=[10, 10, 10, 20, 30],
            depth=[0, 1, 2, 0, 0],
        )
        state: dict[str, object] = {
            "process_pairing_section_scenario": "child-a"
        }
        parent = Mock()
        with (
            patch.object(fishbone_ui, "assembly_section_walk_order", return_value=sections),
            patch.object(fishbone_ui.st, "session_state", state),
        ):
            render_fishbone_sidebar_context(
                parent,
                page_title="Process at a Glance",
                project_id="project",
                scenario_id="scenario",
            )

        parent.markdown.assert_called_once_with("**Main A › Child A**")
        self.assertEqual(
            parent.selectbox.call_args.args[1],
            ["main-a", "child-a", "main-b", "orphan"],
        )

    def test_sidebar_preserves_selected_unlinked_yamazumi_area(self) -> None:
        sections = self.sections.assign(
            section_type=[
                "Main spine", "Subassembly", "Subassembly", "Main spine", "Subassembly"
            ],
            sequence=[10, 10, 10, 20, 30],
            depth=[0, 1, 2, 0, 0],
        )
        areas = pd.DataFrame(
            [
                {"id": "linked", "name": "Linked", "section_id": "main-a"},
                {"id": "unlinked", "name": "Imported", "section_id": None},
            ]
        )
        state: dict[str, object] = {"yamazumi_area_scenario": "unlinked"}
        parent = Mock()
        with (
            patch.object(fishbone_ui, "assembly_section_walk_order", return_value=sections),
            patch.object(fishbone_ui, "yamazumi_areas", return_value=areas),
            patch.object(fishbone_ui.st, "session_state", state),
        ):
            render_fishbone_sidebar_context(
                parent,
                page_title="Yamazumi",
                project_id="project",
                scenario_id="scenario",
            )

        parent.markdown.assert_called_once_with("**Unlinked**")
        self.assertEqual(state["yamazumi_area_scenario"], "unlinked")

    def test_sidebar_counts_mixed_pin_map_area_subset(self) -> None:
        sections = self.sections.assign(
            section_type=[
                "Main spine", "Subassembly", "Subassembly", "Main spine", "Subassembly"
            ],
            sequence=[10, 10, 10, 20, 30],
            depth=[0, 1, 2, 0, 0],
        )
        areas = pd.DataFrame(
            [
                {"id": "linked", "name": "Linked", "section_id": "main-a"},
                {"id": "unlinked", "name": "Imported", "section_id": None},
            ]
        )
        pin_map = pd.DataFrame(
            [{"area_id": "linked"}, {"area_id": "unlinked"}]
        )
        state: dict[str, object] = {
            "pin_map_areas_scenario": ["linked", "unlinked"]
        }
        parent = Mock()
        with (
            patch.object(fishbone_ui, "assembly_section_walk_order", return_value=sections),
            patch.object(fishbone_ui, "yamazumi_areas", return_value=areas),
            patch.object(fishbone_ui, "pin_map_for_scenario", return_value=pin_map),
            patch.object(fishbone_ui.st, "session_state", state),
        ):
            render_fishbone_sidebar_context(
                parent,
                page_title="Pin Map",
                project_id="project",
                scenario_id="scenario",
            )

        parent.markdown.assert_called_once_with("**2 sections selected**")


if __name__ == "__main__":
    unittest.main()
