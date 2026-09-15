from __future__ import annotations

import json
import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from utils import store
from utils.yamazumi_stack import (
    UNASSIGNED_STACK_ID,
    apply_stack_draft_to_elements,
    apply_stack_drop,
    build_stack_draft,
)


class YamazumiStackOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        patcher = patch.object(store, "connection", self._test_connection)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()

        self.project_id = "stack-project"
        self.scenario_id = "stack-scenario"
        self.other_scenario_id = "stack-other-scenario"
        self.area_id = "stack-area"
        self.other_area_id = "stack-other-area"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, revision, status, takt_time_s, created_at, updated_at)
                   VALUES (?, 'Stack project', 'A', 'Draft', 60, ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            for scenario_id, sequence in (
                (self.scenario_id, 1), (self.other_scenario_id, 2)
            ):
                conn.execute(
                    """INSERT INTO planning_scenarios
                       (id, project_id, name, revision_label, revision_sequence,
                        status, takt_time_s, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'Working', 60, ?, ?)""",
                    (
                        scenario_id, self.project_id, scenario_id,
                        str(sequence), sequence, timestamp, timestamp,
                    ),
                )
            for area_id, scenario_id in (
                (self.area_id, self.scenario_id),
                (self.other_area_id, self.other_scenario_id),
            ):
                conn.execute(
                    """INSERT INTO yamazumi_areas
                       (id, project_id, scenario_id, name, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (area_id, self.project_id, scenario_id, area_id, timestamp),
                )

        self.north_id = self.add_pitch(self.area_id, "01-ML1-001", "North")
        self.south_id = self.add_pitch(self.area_id, "01-ML1-002", "South")
        self.other_pitch_id = self.add_pitch(
            self.other_area_id, "02-ML1-001", "Other scenario"
        )

    @contextmanager
    def _test_connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def add_pitch(self, area_id: str, number: str, name: str) -> str:
        return store.add_yamazumi_pitch(
            self.project_id, area_id, number, name, "Active", ["Base"]
        )

    def add_element(
        self, element_id: str, area_id: str, pitch_id: str | None, sequence: int
    ) -> None:
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, model_variant, model_variants,
                    work_type, description, time_s, work_region, sequence,
                    source, process_sync_status, updated_at)
                   VALUES (?, ?, ?, ?, 'Base', '["Base"]', 'Cycle', ?, 1,
                           'None', ?, 'Test', 'Synced', ?)""",
                (
                    element_id, self.project_id, area_id, pitch_id,
                    f"Description {element_id}", sequence, timestamp,
                ),
            )

    def rows(self, area_id: str | None = None) -> list[dict]:
        return [dict(row) for row in store.query(
            """SELECT id, pitch_id, description, sequence
               FROM yamazumi_elements WHERE project_id=? AND area_id=?
               ORDER BY pitch_id, sequence, id""",
            (self.project_id, area_id or self.area_id),
        )]

    def test_within_pitch_reorder_is_only_drafted_until_save(self) -> None:
        self.add_element("near", self.area_id, self.north_id, 10)
        self.add_element("far", self.area_id, self.north_id, 20)
        persisted = self.rows()
        draft = apply_stack_drop(
            build_stack_draft(persisted),
            element_id="far",
            pitch_id=self.north_id,
            before_element_id="near",
        )

        self.assertEqual([row["id"] for row in self.rows()], ["near", "far"])
        rendered = apply_stack_draft_to_elements(persisted, draft)
        self.assertEqual([row["id"] for row in rendered], ["far", "near"])

        store.save_yamazumi_stack_draft(
            self.project_id, self.scenario_id, self.area_id, draft
        )
        saved = self.rows()
        self.assertEqual([row["id"] for row in saved], ["far", "near"])
        self.assertEqual([row["sequence"] for row in saved], [10, 20])

    def test_cross_pitch_and_unassigned_moves_persist_requested_positions(self) -> None:
        self.add_element("north", self.area_id, self.north_id, 10)
        self.add_element("unassigned", self.area_id, None, 40)
        draft = build_stack_draft(self.rows())
        draft = apply_stack_drop(
            draft,
            element_id="north",
            pitch_id=None,
            before_element_id="unassigned",
        )
        store.save_yamazumi_stack_draft(
            self.project_id, self.scenario_id, self.area_id, draft
        )
        unassigned = [row for row in self.rows() if row["pitch_id"] is None]
        self.assertEqual(
            [(row["id"], row["sequence"]) for row in unassigned],
            [("north", 10), ("unassigned", 20)],
        )

        draft = apply_stack_drop(
            build_stack_draft(self.rows()),
            element_id="unassigned",
            pitch_id=self.south_id,
        )
        store.save_yamazumi_stack_draft(
            self.project_id, self.scenario_id, self.area_id, draft
        )
        moved = next(row for row in self.rows() if row["id"] == "unassigned")
        self.assertEqual(moved["pitch_id"], self.south_id)
        self.assertEqual(moved["sequence"], 10)

    def test_north_and_south_both_renumber_centerline_outward(self) -> None:
        for element_id, pitch_id, sequence in (
            ("n-near", self.north_id, 90),
            ("n-far", self.north_id, 100),
            ("s-near", self.south_id, 70),
            ("s-far", self.south_id, 80),
        ):
            self.add_element(element_id, self.area_id, pitch_id, sequence)
        draft = build_stack_draft(self.rows())
        draft[self.north_id] = ["n-far", "n-near"]
        draft[self.south_id] = ["s-far", "s-near"]
        store.save_yamazumi_stack_draft(
            self.project_id, self.scenario_id, self.area_id, draft
        )
        by_id = {row["id"]: row for row in self.rows()}
        self.assertEqual((by_id["n-far"]["sequence"], by_id["n-near"]["sequence"]), (10, 20))
        self.assertEqual((by_id["s-far"]["sequence"], by_id["s-near"]["sequence"]), (10, 20))

    def test_invalid_draft_rolls_back_every_change(self) -> None:
        self.add_element("one", self.area_id, self.north_id, 10)
        self.add_element("two", self.area_id, self.north_id, 20)
        before = self.rows()
        invalid = {
            self.south_id: ["one"],
            UNASSIGNED_STACK_ID: ["stale"],
        }
        with self.assertRaisesRegex(ValueError, "incomplete or out of date"):
            store.save_yamazumi_stack_draft(
                self.project_id, self.scenario_id, self.area_id, invalid
            )
        self.assertEqual(self.rows(), before)

    def test_duplicate_and_inactive_destinations_are_rejected_atomically(self) -> None:
        self.add_element("one", self.area_id, self.north_id, 10)
        self.add_element("two", self.area_id, self.north_id, 20)
        before = self.rows()
        with self.assertRaisesRegex(ValueError, "appears more than once"):
            store.save_yamazumi_stack_draft(
                self.project_id,
                self.scenario_id,
                self.area_id,
                {self.north_id: ["one"], self.south_id: ["one", "two"]},
            )
        with store.connection() as conn:
            conn.execute(
                "UPDATE yamazumi_pitches SET status='Open' WHERE id=?",
                (self.south_id,),
            )
        with self.assertRaisesRegex(ValueError, "Active pitch"):
            store.save_yamazumi_stack_draft(
                self.project_id,
                self.scenario_id,
                self.area_id,
                {self.south_id: ["one", "two"]},
            )
        self.assertEqual(self.rows(), before)

    def test_discarding_draft_restores_exact_saved_state(self) -> None:
        self.add_element("one", self.area_id, self.north_id, 10)
        self.add_element("two", self.area_id, self.north_id, 20)
        saved = self.rows()
        draft = apply_stack_drop(
            build_stack_draft(saved),
            element_id="two",
            pitch_id=None,
        )
        self.assertNotEqual(apply_stack_draft_to_elements(saved, draft), saved)
        self.assertEqual(self.rows(), saved)

    def test_result_supplies_complete_friendly_audit_details(self) -> None:
        self.add_element("one", self.area_id, self.north_id, 10)
        self.add_element("two", self.area_id, self.north_id, 20)
        draft = {self.north_id: ["two", "one"]}
        result = store.save_yamazumi_stack_draft(
            self.project_id, self.scenario_id, self.area_id, draft
        )
        stack = result["affected_stacks"][0]
        self.assertEqual(stack["pitch_id"], self.north_id)
        self.assertEqual(stack["pitch_address"], "01-ML1-001")
        self.assertEqual(stack["pitch_name"], "North")
        self.assertEqual(
            [(item["element_id"], item["description"], item["sequence"]) for item in stack["elements"]],
            [
                ("two", "Description two", 10),
                ("one", "Description one", 20),
            ],
        )
        store.record_audit_event(
            self.project_id, "Yamazumi", "Save stack order", 2, "Pat",
            {"centerline_outward_stacks": result["affected_stacks"]},
        )
        history = store.audit_history(self.project_id, "Yamazumi", limit=1)
        details = json.loads(history.iloc[0]["details"])
        self.assertEqual(details["centerline_outward_stacks"][0]["elements"][0]["element_id"], "two")
        self.assertEqual(history.iloc[0]["editor_name"], "Pat")

    def test_save_isolated_to_exact_scenario_area(self) -> None:
        self.add_element("current", self.area_id, self.north_id, 50)
        self.add_element("other", self.other_area_id, self.other_pitch_id, 77)
        draft = {self.north_id: ["current"]}
        store.save_yamazumi_stack_draft(
            self.project_id, self.scenario_id, self.area_id, draft
        )
        other = self.rows(self.other_area_id)[0]
        self.assertEqual(other["pitch_id"], self.other_pitch_id)
        self.assertEqual(other["sequence"], 77)
        with self.assertRaisesRegex(ValueError, "active planning scenario"):
            store.save_yamazumi_stack_draft(
                self.project_id, self.scenario_id, self.other_area_id,
                {self.other_pitch_id: ["other"]},
            )


if __name__ == "__main__":
    unittest.main()
