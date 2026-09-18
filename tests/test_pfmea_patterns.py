from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from utils import pfmea_pattern_store, pfmea_store, quality_store, store


class PfmeaPatternStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        patcher = patch.object(store, "connection", self._connection)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()
        self.project_id = "pattern-project"
        self.scenario_id = "pattern-scenario"
        self.work_element_id = "pattern-step"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, revision, status, takt_time_s, created_at, updated_at)
                   VALUES (?, 'Pattern project', 'A', 'Draft', 60, ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, status,
                    takt_time_s, created_at, updated_at)
                   VALUES (?, ?, 'Current', 'A', 1, 'Working', 60, ?, ?)""",
                (self.scenario_id, self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    description, location, updated_at)
                   VALUES (?, ?, ?, 10, '01-WA1-001', 'Load housing', '', '', ?)""",
                (self.work_element_id, self.project_id, self.scenario_id, timestamp),
            )
        self.requirement_id = quality_store.save_quality_requirement(
            self.project_id,
            {
                "requirement_type": "Torque",
                "description": "Fastener torque",
                "unique_identifier": "TQ-001",
                "pass_fail": False,
                "target_value": 20,
                "tolerances": "+/- 2",
                "unit": "N-m",
            },
        )
        self.assignment_id = quality_store.assign_quality_requirement(
            self.project_id, self.scenario_id, self.work_element_id, self.requirement_id
        )
        self.manual_id = pfmea_store.save_pfmea_control_option_rows(
            self.project_id,
            "Prevention",
            pd.DataFrame([{"id": "", "label": "Poka-yoke", "active": True}]),
        )["created_ids"][0]

    @contextmanager
    def _connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def create_pattern(self) -> str:
        cause_key = "draft-cause"
        result = pfmea_pattern_store.save_pfmea_pattern_graph(
            self.project_id,
            {
                "label": "Loose fastener",
                "notes": "Reviewed starting point",
                "potential_failure_mode": "Fastener is loose",
                "class_code": "P",
                "active": True,
            },
            effects=[{"effect_description": "Assembly separates", "sequence": 10}],
            causes=[
                {
                    "draft_id": cause_key,
                    "cause_description": "Torque not achieved",
                    "sequence": 10,
                }
            ],
            actions=[
                {
                    "pattern_cause_id": cause_key,
                    "recommended_action": "Validate rundown",
                    "sequence": 10,
                }
            ],
            prevention_sources=[
                {
                    "pattern_cause_id": cause_key,
                    "source_type": "quality_requirement",
                    "source_id": self.requirement_id,
                    "sequence": 10,
                },
                {
                    "pattern_cause_id": cause_key,
                    "source_type": "manual_option",
                    "source_id": self.manual_id,
                    "sequence": 20,
                },
            ],
            detection_sources=[],
        )
        return str(result["pattern_id"])

    def test_pattern_graph_resolves_published_and_manual_sources(self) -> None:
        pattern_id = self.create_pattern()
        resolved = pfmea_pattern_store.resolve_pfmea_pattern(
            self.project_id, self.scenario_id, self.work_element_id, pattern_id
        )
        cause_id = str(resolved["causes"][0]["id"])
        self.assertEqual(resolved["pattern"]["class_code"], "P")
        self.assertEqual(resolved["effects"][0]["effect_description"], "Assembly separates")
        self.assertEqual(
            resolved["controls_by_cause"][cause_id]["Prevention"],
            [f"quality:{self.assignment_id}", f"manual:{self.manual_id}"],
        )
        self.assertEqual(resolved["omitted_sources"], [])

    def test_labels_are_case_insensitively_unique(self) -> None:
        self.create_pattern()
        with self.assertRaisesRegex(ValueError, "unique"):
            pfmea_pattern_store.save_pfmea_pattern_graph(
                self.project_id,
                {
                    "label": "loose FASTENER",
                    "potential_failure_mode": "Another mode",
                    "class_code": "",
                    "active": True,
                },
            )

    def test_pattern_sources_block_parent_deletion(self) -> None:
        self.create_pattern()
        quality_store.delete_quality_requirement_assignments(
            self.project_id, self.scenario_id, [self.assignment_id], "Tester"
        )
        with self.assertRaisesRegex(ValueError, "PFMEA pattern control reference"):
            quality_store.delete_quality_requirements(
                self.project_id, [self.requirement_id]
            )
        with self.assertRaisesRegex(ValueError, "PFMEA pattern reference"):
            pfmea_store.delete_pfmea_control_options(
                self.project_id, "Prevention", [self.manual_id]
            )

    def test_existing_inactive_manual_source_is_retained_but_cannot_be_newly_selected(self) -> None:
        pattern_id = self.create_pattern()
        pfmea_store.save_pfmea_control_option_rows(
            self.project_id,
            "Prevention",
            pd.DataFrame(
                [{"id": self.manual_id, "label": "Poka-yoke", "active": False}]
            ),
        )
        graph = pfmea_pattern_store.pfmea_pattern_graph(self.project_id, pattern_id)
        pfmea_pattern_store.save_pfmea_pattern_graph(
            self.project_id,
            graph["pattern"],
            effects=graph["effects"],
            causes=graph["causes"],
            actions=graph["actions"],
            prevention_sources=graph["prevention_sources"],
            detection_sources=graph["detection_sources"],
        )
        retained = pfmea_pattern_store.pfmea_pattern_graph(self.project_id, pattern_id)
        self.assertEqual(len(retained["prevention_sources"]), 2)
        self.assertFalse(bool(
            retained["prevention_sources"].loc[
                retained["prevention_sources"]["source_type"].eq("manual_option"),
                "source_active",
            ].iloc[0]
        ))

        with self.assertRaisesRegex(ValueError, "active Prevention manual option"):
            pfmea_pattern_store.save_pfmea_pattern_graph(
                self.project_id,
                {
                    "label": "New inactive source",
                    "potential_failure_mode": "Example",
                    "class_code": "",
                    "active": True,
                },
                causes=[{"draft_id": "cause", "cause_description": "Cause"}],
                prevention_sources=[
                    {
                        "pattern_cause_id": "cause",
                        "source_type": "manual_option",
                        "source_id": self.manual_id,
                    }
                ],
            )

    def test_capture_excludes_ratings_and_completion_evidence(self) -> None:
        entry_id = pfmea_store.save_pfmea_entry_rows(
            self.project_id,
            self.scenario_id,
            self.work_element_id,
            pd.DataFrame(
                [{"id": "", "potential_failure_mode": "Bolt loose", "class_code": "Q"}]
            ),
        )["created_ids"][0]
        pfmea_store.save_pfmea_effect_rows(
            self.project_id,
            self.scenario_id,
            entry_id,
            pd.DataFrame(
                [{"id": "", "effect_description": "Noise", "severity": 8, "sequence": 10}]
            ),
        )
        cause_id = pfmea_store.save_pfmea_cause_rows(
            self.project_id,
            self.scenario_id,
            entry_id,
            pd.DataFrame(
                [{
                    "id": "", "cause_description": "Low torque", "occurrence": 3,
                    "detection": 4, "sequence": 10,
                }]
            ),
        )["created_ids"][0]
        pfmea_store.save_pfmea_action_rows(
            self.project_id,
            self.scenario_id,
            entry_id,
            pd.DataFrame(
                [{
                    "id": "", "pfmea_cause_id": cause_id,
                    "recommended_action": "Review program", "responsibility": "IE",
                    "target_completion_date": "2026-10-01", "actions_taken": "Done",
                    "resulting_severity": 2, "resulting_occurrence": 2,
                    "resulting_detection": 2, "sequence": 10,
                }]
            ),
        )
        result = pfmea_pattern_store.capture_pfmea_entry_as_pattern(
            self.project_id,
            self.scenario_id,
            entry_id,
            label="Captured line",
        )
        graph = pfmea_pattern_store.pfmea_pattern_graph(
            self.project_id, str(result["pattern_id"])
        )
        self.assertEqual(graph["pattern"]["class_code"], "Q")
        self.assertNotIn("severity", graph["effects"].columns)
        self.assertNotIn("occurrence", graph["causes"].columns)
        self.assertEqual(graph["actions"].iloc[0]["recommended_action"], "Review program")
        self.assertNotIn("actions_taken", graph["actions"].columns)

    def test_full_graph_draft_saves_as_one_independent_entry(self) -> None:
        graph_key = "draft-graph"
        rows = pd.DataFrame(
            [
                {
                    "id": "", "draft_row_id": "row-1", "draft_entry_key": graph_key,
                    "draft_effect_key": "effect-1", "draft_cause_key": "cause-1",
                    "draft_action_key": "action-1", "work_element_id": self.work_element_id,
                    "item_number": "01-WA1-001", "potential_failure_mode": "Loose",
                    "potential_effects": "Noise", "potential_causes": "Low torque",
                    "recommended_action": "Review", "classification": "P",
                    "prevention_controls": [], "detection_controls": [],
                },
                {
                    "id": "", "draft_row_id": "row-2", "draft_entry_key": graph_key,
                    "draft_effect_key": "effect-2", "draft_cause_key": "cause-1",
                    "draft_action_key": "action-1", "work_element_id": self.work_element_id,
                    "item_number": "01-WA1-001", "potential_failure_mode": "Loose",
                    "potential_effects": "Leak", "potential_causes": "Low torque",
                    "recommended_action": "Review", "classification": "P",
                    "prevention_controls": [], "detection_controls": [],
                },
            ]
        )
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, rows)
        entries = pfmea_store.pfmea_entries(self.project_id, self.scenario_id)
        self.assertEqual(len(entries), 1)
        entry_id = str(entries.iloc[0]["id"])
        self.assertEqual(len(pfmea_store.pfmea_effects(
            self.project_id, self.scenario_id, entry_id
        )), 2)
        self.assertEqual(len(pfmea_store.pfmea_causes(
            self.project_id, self.scenario_id, entry_id
        )), 1)
        self.assertEqual(len(pfmea_store.pfmea_actions(
            self.project_id, self.scenario_id, entry_id
        )), 1)


if __name__ == "__main__":
    unittest.main()
