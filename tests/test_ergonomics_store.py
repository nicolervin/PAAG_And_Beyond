from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from utils import store


class ErgonomicsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        connection_patcher = patch.object(store, "connection", self._test_connection)
        connection_patcher.start()
        self.addCleanup(connection_patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()

        self.project_id = "ergo-project"
        self.scenario_id = "ergo-scenario"
        self.other_scenario_id = "ergo-scenario-other"
        self.work_element_id = "ergo-step"
        self.other_work_element_id = "ergo-step-other"
        self.section_id = "ergo-section"
        self.part_id = "ergo-part"
        self.other_part_id = "ergo-part-other"
        self.group_id = "ergo-group"
        self.option_id = "ergo-option"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, revision, status, takt_time_s, created_at, updated_at)
                   VALUES (?, 'Ergonomics project', 'A', 'Draft', 60, ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            for scenario_id, name, revision, sequence in (
                (self.scenario_id, "Current plan", "A", 1),
                (self.other_scenario_id, "Other plan", "B", 2),
            ):
                conn.execute(
                    """INSERT INTO planning_scenarios
                       (id, project_id, name, revision_label, revision_sequence,
                        status, takt_time_s, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'Working', 60, ?, ?)""",
                    (
                        scenario_id,
                        self.project_id,
                        name,
                        revision,
                        sequence,
                        timestamp,
                        timestamp,
                    ),
                )
            for work_element_id, scenario_id, operation in (
                (self.work_element_id, self.scenario_id, "Lift bracket"),
                (self.other_work_element_id, self.other_scenario_id, "Place bracket"),
            ):
                conn.execute(
                    """INSERT INTO work_elements
                       (id, project_id, scenario_id, sequence, operation, updated_at)
                       VALUES (?, ?, ?, 10, ?, ?)""",
                    (work_element_id, self.project_id, scenario_id, operation, timestamp),
                )
            conn.execute(
                """INSERT INTO assembly_sections
                   (id, project_id, name, section_type, sequence, created_at, updated_at)
                   VALUES (?, ?, 'Cabinet', 'Main spine', 10, ?, ?)""",
                (self.section_id, self.project_id, timestamp, timestamp),
            )
            for part_id, number in (
                (self.part_id, "BRK-001"),
                (self.other_part_id, "BRK-002"),
            ):
                conn.execute(
                    """INSERT INTO parts
                       (id, project_id, part_number, description, quantity,
                        revision, source, updated_at)
                       VALUES (?, ?, ?, 'Bracket', 1, '0', 'Manual', ?)""",
                    (part_id, self.project_id, number, timestamp),
                )
                conn.execute(
                    """INSERT INTO fishbone_part_assignments
                       (id, project_id, part_id, section_id, sequence,
                        quantity, updated_at)
                       VALUES (?, ?, ?, ?, 10, 1, ?)""",
                    (
                        f"assignment-{part_id}",
                        self.project_id,
                        part_id,
                        self.section_id,
                        timestamp,
                    ),
                )
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id,
                    name, selection_rule, quantity, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'Bracket', 'Use all', 1, ?)""",
                (
                    self.group_id,
                    self.project_id,
                    self.scenario_id,
                    self.work_element_id,
                    self.section_id,
                    timestamp,
                ),
            )
            conn.execute(
                """INSERT INTO process_part_options
                   (id, group_id, part_id, updated_at) VALUES (?, ?, ?, ?)""",
                (self.option_id, self.group_id, self.part_id, timestamp),
            )

    @contextmanager
    def _test_connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _create_hazards(self) -> list[str]:
        result = store.save_ergonomic_hazard_option_rows(
            self.project_id,
            pd.DataFrame(
                [
                    {"id": "", "label": "Heavy lift", "active": True},
                    {"id": "", "label": "Awkward posture", "active": True},
                ]
            ),
        )
        return result["created_ids"]

    def _add_process_option(
        self,
        suffix: str,
        *,
        scenario_id: str | None = None,
        work_element_id: str | None = None,
        part_id: str | None = None,
    ) -> str:
        scenario_id = scenario_id or self.scenario_id
        work_element_id = work_element_id or self.work_element_id
        part_id = part_id or self.part_id
        group_id = f"group-{suffix}"
        option_id = f"option-{suffix}"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id,
                    name, selection_rule, quantity, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'Use all', 1, ?)""",
                (
                    group_id,
                    self.project_id,
                    scenario_id,
                    work_element_id,
                    self.section_id,
                    f"Requirement {suffix}",
                    timestamp,
                ),
            )
            conn.execute(
                """INSERT INTO process_part_options
                   (id, group_id, part_id, updated_at) VALUES (?, ?, ?, ?)""",
                (option_id, group_id, part_id, timestamp),
            )
        return option_id

    def test_init_creates_phase_one_schema_without_handling_default(self) -> None:
        with store.connection() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    """SELECT name FROM sqlite_master
                       WHERE type='table' AND name LIKE 'ergonomic%'"""
                ).fetchall()
            }
            option_columns = {
                row[1]: dict(row)
                for row in conn.execute("PRAGMA table_info(process_part_options)").fetchall()
            }
            part_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(parts)").fetchall()
            }
        self.assertEqual(
            tables,
            {
                "ergonomic_hazard_options",
                "ergonomics_reviews",
                "ergonomics_review_hazard_selections",
            },
        )
        self.assertIn("weight_lb", part_columns)
        self.assertIn("handling_type", option_columns)
        self.assertEqual(option_columns["handling_type"]["notnull"], 0)
        self.assertIsNone(option_columns["handling_type"]["dflt_value"])
        self.assertIn("fishbone_assignment_id", option_columns)
        self.assertEqual(option_columns["fishbone_assignment_id"]["notnull"], 0)
        self.assertIsNone(option_columns["fishbone_assignment_id"]["dflt_value"])
        with store.connection() as conn:
            option_foreign_keys = {
                row[3]: row[2]
                for row in conn.execute(
                    "PRAGMA foreign_key_list(process_part_options)"
                ).fetchall()
            }
        self.assertEqual(
            option_foreign_keys["fishbone_assignment_id"],
            "fishbone_part_assignments",
        )

    def test_upgrade_preserves_sixteen_legacy_options_with_both_fields_null(self) -> None:
        legacy_conn = sqlite3.connect(":memory:")
        legacy_conn.row_factory = sqlite3.Row
        legacy_conn.execute("PRAGMA foreign_keys = ON")
        legacy_conn.execute(
            """CREATE TABLE process_part_options (
                   id TEXT PRIMARY KEY,
                   group_id TEXT NOT NULL,
                   part_id TEXT NOT NULL,
                   updated_at TEXT NOT NULL,
                   UNIQUE(group_id, part_id)
               )"""
        )
        legacy_conn.executemany(
            """INSERT INTO process_part_options
               (id, group_id, part_id, updated_at) VALUES (?, ?, ?, ?)""",
            [
                (f"legacy-option-{index}", "legacy-group", f"legacy-part-{index}", "old")
                for index in range(16)
            ],
        )

        @contextmanager
        def legacy_connection():
            try:
                yield legacy_conn
                legacy_conn.commit()
            except Exception:
                legacy_conn.rollback()
                raise

        try:
            with patch.object(store, "connection", legacy_connection):
                store.init_db()
            rows = legacy_conn.execute(
                """SELECT handling_type, fishbone_assignment_id
                   FROM process_part_options ORDER BY id"""
            ).fetchall()
            columns = {
                row[1]: dict(row)
                for row in legacy_conn.execute(
                    "PRAGMA table_info(process_part_options)"
                ).fetchall()
            }
        finally:
            legacy_conn.close()

        self.assertEqual(len(rows), 16)
        self.assertTrue(all(row["handling_type"] is None for row in rows))
        self.assertTrue(all(row["fishbone_assignment_id"] is None for row in rows))
        self.assertIsNone(columns["handling_type"]["dflt_value"])
        self.assertIsNone(columns["fishbone_assignment_id"]["dflt_value"])

    def test_handling_type_uses_compatibility_null_and_controlled_values(self) -> None:
        with store.connection() as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT handling_type FROM process_part_options WHERE id=?",
                    (self.option_id,),
                ).fetchone()[0]
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE process_part_options SET handling_type='Move' WHERE id=?",
                    (self.option_id,),
                )

        store.set_process_part_option_handling_type(
            self.project_id,
            self.scenario_id,
            self.option_id,
            "Consume",
            f"assignment-{self.part_id}",
        )
        self.assertEqual(
            store.process_part_groups(
                self.project_id, self.scenario_id, self.work_element_id
            )[0]["options"][0]["handling_type"],
            "Consume",
        )
        with self.assertRaisesRegex(ValueError, "Handle or Consume"):
            store.set_process_part_option_handling_type(
                self.project_id, self.scenario_id, self.option_id, "Move"
            )

    def test_part_requirement_save_preserves_ids_and_nullable_classification(self) -> None:
        store.save_process_part_group(
            self.project_id,
            self.scenario_id,
            self.work_element_id,
            self.section_id,
            self.group_id,
            "Bracket",
            "Use all",
            1,
            [self.part_id, self.other_part_id],
        )
        with store.connection() as conn:
            rows = conn.execute(
                """SELECT id, part_id, handling_type FROM process_part_options
                   WHERE group_id=? ORDER BY part_id""",
                (self.group_id,),
            ).fetchall()
        by_part = {str(row["part_id"]): dict(row) for row in rows}
        self.assertEqual(by_part[self.part_id]["id"], self.option_id)
        self.assertIsNone(by_part[self.part_id]["handling_type"])
        self.assertIsNone(by_part[self.other_part_id]["handling_type"])

        store.save_process_part_group(
            self.project_id,
            self.scenario_id,
            self.work_element_id,
            self.section_id,
            self.group_id,
            "Bracket",
            "Use all",
            1,
            [self.part_id, self.other_part_id],
            handling_types_by_part={
                self.part_id: "Consume",
                self.other_part_id: None,
            },
            fishbone_assignment_ids_by_part={
                self.part_id: f"assignment-{self.part_id}",
                self.other_part_id: None,
            },
        )
        with store.connection() as conn:
            updated = {
                str(row["part_id"]): dict(row)
                for row in conn.execute(
                    """SELECT id, part_id, handling_type FROM process_part_options
                       WHERE group_id=?""",
                    (self.group_id,),
                ).fetchall()
            }
        self.assertEqual(updated[self.part_id]["id"], self.option_id)
        self.assertEqual(updated[self.part_id]["handling_type"], "Consume")
        self.assertIsNone(updated[self.other_part_id]["handling_type"])

    def test_consume_within_allowance_is_valid(self) -> None:
        assignment_id = f"assignment-{self.part_id}"
        store.set_process_part_option_handling_type(
            self.project_id,
            self.scenario_id,
            self.option_id,
            "Consume",
            assignment_id,
        )
        row = store.query(
            """SELECT handling_type, fishbone_assignment_id
               FROM process_part_options WHERE id=?""",
            (self.option_id,),
        )[0]
        self.assertEqual(row["handling_type"], "Consume")
        self.assertEqual(row["fishbone_assignment_id"], assignment_id)

    def test_consume_exceeding_allowance_is_blocked(self) -> None:
        assignment_id = f"assignment-{self.part_id}"
        with store.connection() as conn:
            conn.execute(
                "UPDATE fishbone_part_assignments SET quantity=2 WHERE id=?",
                (assignment_id,),
            )
        store.set_process_part_option_handling_type(
            self.project_id,
            self.scenario_id,
            self.option_id,
            "Consume",
            assignment_id,
        )
        second_option_id = self._add_process_option("consume-second-unit")
        store.set_process_part_option_handling_type(
            self.project_id,
            self.scenario_id,
            second_option_id,
            "Consume",
            assignment_id,
        )
        extra_option_id = self._add_process_option("consume-overflow")
        with self.assertRaisesRegex(
            ValueError,
            rf"{assignment_id}.*recorded quantity of 2.*fully consumed elsewhere in this scenario",
        ):
            store.set_process_part_option_handling_type(
                self.project_id,
                self.scenario_id,
                extra_option_id,
                "Consume",
                assignment_id,
            )

    def test_classified_pairing_requires_a_fishbone_placement(self) -> None:
        for handling_type in ("Consume", "Handle"):
            with self.subTest(handling_type=handling_type):
                with self.assertRaisesRegex(ValueError, "Fishbone placement is required"):
                    store.set_process_part_option_handling_type(
                        self.project_id,
                        self.scenario_id,
                        self.option_id,
                        handling_type,
                    )

    def test_handle_is_valid_after_existing_consume(self) -> None:
        assignment_id = f"assignment-{self.part_id}"
        store.set_process_part_option_handling_type(
            self.project_id,
            self.scenario_id,
            self.option_id,
            "Consume",
            assignment_id,
        )
        handle_option_id = self._add_process_option("handle-after-consume")
        store.set_process_part_option_handling_type(
            self.project_id,
            self.scenario_id,
            handle_option_id,
            "Handle",
            assignment_id,
        )
        self.assertEqual(
            store.query(
                "SELECT handling_type FROM process_part_options WHERE id=?",
                (handle_option_id,),
            )[0]["handling_type"],
            "Handle",
        )

    def test_handle_without_prior_consume_is_blocked(self) -> None:
        assignment_id = f"assignment-{self.part_id}"
        with self.assertRaisesRegex(
            ValueError,
            rf"{assignment_id}.*must be Consumed before it can be Handled",
        ):
            store.set_process_part_option_handling_type(
                self.project_id,
                self.scenario_id,
                self.option_id,
                "Handle",
                assignment_id,
            )

    def test_consume_counts_do_not_leak_across_scenarios(self) -> None:
        assignment_id = f"assignment-{self.part_id}"
        store.set_process_part_option_handling_type(
            self.project_id,
            self.scenario_id,
            self.option_id,
            "Consume",
            assignment_id,
        )
        other_scenario_option_id = self._add_process_option(
            "other-scenario-consume",
            scenario_id=self.other_scenario_id,
            work_element_id=self.other_work_element_id,
        )
        with self.assertRaisesRegex(
            ValueError, "must be Consumed before it can be Handled"
        ):
            store.set_process_part_option_handling_type(
                self.project_id,
                self.other_scenario_id,
                other_scenario_option_id,
                "Handle",
                assignment_id,
            )
        store.set_process_part_option_handling_type(
            self.project_id,
            self.other_scenario_id,
            other_scenario_option_id,
            "Consume",
            assignment_id,
        )
        consume_rows = store.query(
            """SELECT group_row.scenario_id
               FROM process_part_options option
               JOIN process_part_groups group_row ON group_row.id=option.group_id
               WHERE option.fishbone_assignment_id=?
                 AND option.handling_type='Consume'
               ORDER BY group_row.scenario_id""",
            (assignment_id,),
        )
        self.assertEqual(
            [row["scenario_id"] for row in consume_rows],
            sorted([self.scenario_id, self.other_scenario_id]),
        )

    def test_part_weight_is_project_bound_and_nonnegative(self) -> None:
        store.set_part_weight_lb(self.project_id, self.part_id, 33.5)
        self.assertEqual(
            store.query("SELECT weight_lb FROM parts WHERE id=?", (self.part_id,))[0][
                "weight_lb"
            ],
            33.5,
        )
        store.set_part_weight_lb(self.project_id, self.part_id, None)
        self.assertIsNone(
            store.query("SELECT weight_lb FROM parts WHERE id=?", (self.part_id,))[0][
                "weight_lb"
            ]
        )
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            store.set_part_weight_lb(self.project_id, self.part_id, -1)
        with self.assertRaisesRegex(ValueError, "no longer exists"):
            store.set_part_weight_lb("another-project", self.part_id, 10)

    def test_hazard_catalog_is_case_insensitively_unique(self) -> None:
        self._create_hazards()
        options = store.ergonomic_hazard_options(self.project_id)
        self.assertEqual(list(options["label"]), ["Awkward posture", "Heavy lift"])
        duplicate = pd.concat(
            [
                options[["id", "label", "active"]],
                pd.DataFrame([{"id": "", "label": "heavy LIFT", "active": True}]),
            ],
            ignore_index=True,
        )
        with self.assertRaisesRegex(ValueError, "unique"):
            store.save_ergonomic_hazard_option_rows(self.project_id, duplicate)

    def test_review_persists_multiple_hazards_and_enforces_boundaries(self) -> None:
        hazard_ids = self._create_hazards()
        result = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "work_element_id": self.work_element_id,
                "process_part_option_id": self.option_id,
                "reviewer": "Alex Ergonomist",
                "notes": "Assess lift path",
                "requested_due_date": "2026-09-30",
                "hazard_option_ids": hazard_ids,
            },
        )
        reviews = store.ergonomics_reviews(
            self.project_id, self.scenario_id, self.work_element_id
        )
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews.iloc[0]["id"], result["id"])
        self.assertEqual(reviews.iloc[0]["status"], "Started")
        self.assertEqual(reviews.iloc[0]["hazard_option_ids"], hazard_ids)

        store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "id": result["id"],
                "work_element_id": self.work_element_id,
                "process_part_option_id": self.option_id,
                "status": "Closed (engineering)",
                "reviewer": "Alex Ergonomist",
                "hazard_option_ids": hazard_ids[:1],
            },
        )
        updated = store.ergonomics_reviews(self.project_id, self.scenario_id)
        self.assertEqual(updated.iloc[0]["status"], "Closed (engineering)")
        self.assertEqual(updated.iloc[0]["hazard_option_ids"], hazard_ids[:1])

        with self.assertRaisesRegex(ValueError, "valid Ergonomics review status"):
            store.save_ergonomics_review(
                self.project_id,
                self.scenario_id,
                {
                    "work_element_id": self.work_element_id,
                    "status": "Approved",
                },
            )
        with self.assertRaisesRegex(ValueError, "does not belong"):
            store.save_ergonomics_review(
                self.project_id,
                self.other_scenario_id,
                {
                    "work_element_id": self.other_work_element_id,
                    "process_part_option_id": self.option_id,
                },
            )

    def test_part_use_removal_preserves_review_but_work_deletion_is_restricted(self) -> None:
        review_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "work_element_id": self.work_element_id,
                "process_part_option_id": self.option_id,
            },
        )["id"]
        with store.connection() as conn:
            conn.execute("DELETE FROM process_part_options WHERE id=?", (self.option_id,))
            review = conn.execute(
                "SELECT process_part_option_id FROM ergonomics_reviews WHERE id=?",
                (review_id,),
            ).fetchone()
            self.assertIsNone(review["process_part_option_id"])
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM work_elements WHERE id=?", (self.work_element_id,))


if __name__ == "__main__":
    unittest.main()
