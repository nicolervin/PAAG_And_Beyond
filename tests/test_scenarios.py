from __future__ import annotations

import unittest
from contextlib import nullcontext
from unittest.mock import patch

from utils import store


class PlanningScenarioTableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.existing = [
            {
                "id": "scenario-1",
                "name": "Current plan",
                "revision_label": "1",
            }
        ]

    def test_new_row_clones_current_scenario_and_existing_row_updates(self) -> None:
        records = [
            {
                "id": "scenario-1",
                "name": "Current plan",
                "revision_label": "1",
                "status": "Frozen",
                "takt_time_s": 60,
                "change_summary": "Saved baseline",
            },
            {
                "id": "",
                "name": "Higher demand",
                "revision_label": "2",
                "status": "Working",
                "takt_time_s": 54,
                "change_summary": "Faster takt",
            },
        ]

        transaction = object()
        with (
            patch.object(store, "planning_scenarios", return_value=self.existing),
            patch.object(store, "connection", return_value=nullcontext(transaction)),
            patch.object(store, "update_planning_scenario") as update,
            patch.object(store, "clone_planning_scenario", return_value="scenario-2") as clone,
        ):
            result = store.save_planning_scenario_rows(
                "project-1", "scenario-1", records, "Nicole"
            )

        update.assert_called_once_with(
            "project-1", "scenario-1", records[0] | {"takt_time_s": 60.0},
            _conn=transaction,
        )
        clone.assert_called_once_with(
            "project-1", "scenario-1", "Higher demand", "2", 54.0,
            "Faster takt", "Nicole", _conn=transaction,
        )
        self.assertEqual(result["created_ids"], ["scenario-2"])
        self.assertEqual(result["updated_count"], 1)

    def test_duplicate_names_fail_before_any_write(self) -> None:
        records = [
            {
                "id": "scenario-1",
                "name": "Current plan",
                "revision_label": "1",
                "status": "Working",
                "takt_time_s": 60,
            },
            {
                "id": "",
                "name": "current PLAN",
                "revision_label": "2",
                "status": "Working",
                "takt_time_s": 55,
            },
        ]

        with (
            patch.object(store, "planning_scenarios", return_value=self.existing),
            patch.object(store, "update_planning_scenario") as update,
            patch.object(store, "clone_planning_scenario") as clone,
        ):
            with self.assertRaisesRegex(ValueError, "names must be unique"):
                store.save_planning_scenario_rows(
                    "project-1", "scenario-1", records, "Nicole"
                )

        update.assert_not_called()
        clone.assert_not_called()


if __name__ == "__main__":
    unittest.main()
