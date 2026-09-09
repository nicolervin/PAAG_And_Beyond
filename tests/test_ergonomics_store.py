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
        with store.connection() as conn:
            review_columns = {
                row[1]: dict(row)
                for row in conn.execute("PRAGMA table_info(ergonomics_reviews)").fetchall()
            }
            review_foreign_keys = {
                row[3]: dict(row)
                for row in conn.execute(
                    "PRAGMA foreign_key_list(ergonomics_reviews)"
                ).fetchall()
            }
        self.assertEqual(review_columns["work_element_id"]["notnull"], 0)
        self.assertEqual(review_columns["risk_classification"]["notnull"], 1)
        self.assertEqual(
            review_columns["risk_classification"]["dflt_value"],
            "'Not yet assessed'",
        )
        self.assertEqual(
            review_foreign_keys["work_element_id"]["on_delete"].upper(),
            "SET NULL",
        )

    def test_upgrade_preserves_reviews_and_hazards_while_making_work_link_nullable(self) -> None:
        legacy_conn = sqlite3.connect(":memory:")
        legacy_conn.row_factory = sqlite3.Row
        legacy_conn.execute("PRAGMA foreign_keys = ON")
        legacy_conn.executescript(
            """
            CREATE TABLE projects (id TEXT PRIMARY KEY);
            CREATE TABLE planning_scenarios (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE TABLE work_elements (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE
            );
            CREATE TABLE process_part_options (id TEXT PRIMARY KEY);
            CREATE TABLE ergonomic_hazard_options (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE TABLE ergonomics_reviews (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
                work_element_id TEXT NOT NULL
                    REFERENCES work_elements(id) ON DELETE RESTRICT,
                process_part_option_id TEXT
                    REFERENCES process_part_options(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'Started',
                reviewer TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                requested_due_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE ergonomics_review_hazard_selections (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
                ergonomics_review_id TEXT NOT NULL
                    REFERENCES ergonomics_reviews(id) ON DELETE CASCADE,
                hazard_option_id TEXT NOT NULL
                    REFERENCES ergonomic_hazard_options(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL DEFAULT 10,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(ergonomics_review_id, hazard_option_id)
            );
            INSERT INTO projects VALUES ('project');
            INSERT INTO planning_scenarios VALUES ('scenario', 'project');
            INSERT INTO work_elements VALUES ('step', 'project', 'scenario');
            INSERT INTO ergonomic_hazard_options VALUES ('hazard', 'project');
            INSERT INTO ergonomics_reviews VALUES (
                'review', 'project', 'scenario', 'step', NULL, 'Open',
                'Ergonomist', 'Preserve this', '2026-10-01', 'old', 'old'
            );
            INSERT INTO ergonomics_review_hazard_selections VALUES (
                'selection', 'project', 'scenario', 'review', 'hazard', 10,
                'old', 'old'
            );
            """
        )
        try:
            store._upgrade_ergonomics_reviews_work_element_link(legacy_conn)
            review = legacy_conn.execute(
                "SELECT * FROM ergonomics_reviews WHERE id='review'"
            ).fetchone()
            selection = legacy_conn.execute(
                "SELECT * FROM ergonomics_review_hazard_selections WHERE id='selection'"
            ).fetchone()
            columns = {
                row[1]: dict(row)
                for row in legacy_conn.execute(
                    "PRAGMA table_info(ergonomics_reviews)"
                ).fetchall()
            }
            foreign_keys = {
                row[3]: dict(row)
                for row in legacy_conn.execute(
                    "PRAGMA foreign_key_list(ergonomics_reviews)"
                ).fetchall()
            }
        finally:
            legacy_conn.close()

        self.assertEqual(review["notes"], "Preserve this")
        self.assertEqual(selection["hazard_option_id"], "hazard")
        self.assertEqual(columns["work_element_id"]["notnull"], 0)
        self.assertEqual(foreign_keys["work_element_id"]["on_delete"], "SET NULL")
        self.assertEqual(review["risk_classification"], "Not yet assessed")

    def test_risk_classification_upgrade_backfills_every_existing_review(self) -> None:
        legacy_conn = sqlite3.connect(":memory:")
        legacy_conn.row_factory = sqlite3.Row
        legacy_conn.executescript(
            """
            CREATE TABLE ergonomics_reviews (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'Started',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO ergonomics_reviews VALUES
                ('review-one', 'Started', 'old', 'old'),
                ('review-two', 'Pending', 'old', 'old');
            """
        )
        try:
            store._upgrade_ergonomics_reviews_risk_classification(legacy_conn)
            rows = legacy_conn.execute(
                """SELECT risk_classification FROM ergonomics_reviews
                   ORDER BY id"""
            ).fetchall()
            columns = {
                row[1]: dict(row)
                for row in legacy_conn.execute(
                    "PRAGMA table_info(ergonomics_reviews)"
                ).fetchall()
            }
            with self.assertRaises(sqlite3.IntegrityError):
                legacy_conn.execute(
                    """UPDATE ergonomics_reviews
                       SET risk_classification='Amber' WHERE id='review-one'"""
                )
        finally:
            legacy_conn.close()

        self.assertEqual(
            [row["risk_classification"] for row in rows],
            ["Not yet assessed", "Not yet assessed"],
        )
        self.assertEqual(columns["risk_classification"]["notnull"], 1)
        self.assertEqual(
            columns["risk_classification"]["dflt_value"], "'Not yet assessed'"
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
        self.assertEqual(reviews.iloc[0]["risk_classification"], "Not yet assessed")
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
        with self.assertRaisesRegex(ValueError, "valid Ergonomics risk classification"):
            store.save_ergonomics_review(
                self.project_id,
                self.scenario_id,
                {
                    "work_element_id": self.work_element_id,
                    "risk_classification": "Amber",
                },
            )

    def test_manual_unlinked_review_is_supported(self) -> None:
        review_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "status": "Open",
                "reviewer": "Alex Ergonomist",
                "notes": "Legacy production concern",
            },
        )["id"]
        review = store.ergonomics_reviews(self.project_id, self.scenario_id).loc[
            lambda frame: frame["id"].eq(review_id)
        ].iloc[0]
        self.assertIsNone(review["work_element_id"])
        self.assertEqual(review["notes"], "Legacy production concern")

    def test_ergonomics_history_is_scenario_scoped(self) -> None:
        store.record_audit_event(
            self.project_id,
            "Ergonomics reviews",
            "Save & Refresh",
            1,
            "First Ergonomist",
            {"scenario_id": self.scenario_id},
        )
        store.record_audit_event(
            self.project_id,
            "Ergonomics reviews",
            "Save & Refresh",
            1,
            "Other Ergonomist",
            {"scenario_id": self.other_scenario_id},
        )
        history = store.ergonomics_review_audit_history(
            self.project_id, self.scenario_id
        )
        self.assertEqual(list(history["editor_name"]), ["First Ergonomist"])

    def test_new_work_element_automatically_receives_started_review(self) -> None:
        new_work_id = "new-ergo-step"
        store.replace_work_elements(
            self.project_id,
            self.scenario_id,
            pd.DataFrame(
                [
                    {"id": self.work_element_id, "operation": "Lift bracket"},
                    {"id": new_work_id, "operation": "Install bracket"},
                ]
            ),
        )
        rows = store.ergonomics_reviews(
            self.project_id, self.scenario_id, new_work_id
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.iloc[0]["status"], "Started")
        self.assertEqual(rows.iloc[0]["risk_classification"], "Not yet assessed")
        self.assertEqual(rows.iloc[0]["reviewer"], "")
        self.assertEqual(rows.iloc[0]["hazard_option_ids"], [])

    def test_bulk_work_element_creation_gives_each_step_exactly_one_review(self) -> None:
        new_work_ids = ["bulk-ergo-step-1", "bulk-ergo-step-2"]
        store.replace_work_elements(
            self.project_id,
            self.scenario_id,
            pd.DataFrame(
                [
                    {"id": self.work_element_id, "operation": "Lift bracket"},
                    {"id": new_work_ids[0], "operation": "Install bracket"},
                    {"id": new_work_ids[1], "operation": "Inspect bracket"},
                ]
            ),
        )
        with store.connection() as conn:
            counts = {
                str(row[0]): int(row[1])
                for row in conn.execute(
                    """SELECT work_element_id, COUNT(*)
                       FROM ergonomics_reviews
                       WHERE project_id=? AND scenario_id=?
                         AND work_element_id IN (?, ?)
                       GROUP BY work_element_id""",
                    (self.project_id, self.scenario_id, *new_work_ids),
                ).fetchall()
            }
        self.assertEqual(counts, {work_id: 1 for work_id in new_work_ids})

    def test_yamazumi_reconciliation_creates_exactly_one_review(self) -> None:
        area_id = "ergo-yamazumi-area"
        yamazumi_id = "ergo-yamazumi-element"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES (?, ?, ?, 'Main line', ?)""",
                (area_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, description, time_s, updated_at)
                   VALUES (?, ?, ?, 'Install clip', 12, ?)""",
                (yamazumi_id, self.project_id, area_id, timestamp),
            )

        self.assertEqual(
            store.reconcile_yamazumi_to_process(
                self.project_id, self.scenario_id, [yamazumi_id]
            ),
            1,
        )
        with store.connection() as conn:
            process_id = str(
                conn.execute(
                    "SELECT process_element_id FROM yamazumi_elements WHERE id=?",
                    (yamazumi_id,),
                ).fetchone()[0]
            )
            review_count = conn.execute(
                """SELECT COUNT(*) FROM ergonomics_reviews
                   WHERE project_id=? AND scenario_id=? AND work_element_id=?""",
                (self.project_id, self.scenario_id, process_id),
            ).fetchone()[0]
        self.assertEqual(review_count, 1)

    def test_scenario_clone_creates_exactly_one_baseline_review_per_step(self) -> None:
        cloned_scenario_id = store.clone_planning_scenario(
            self.project_id,
            self.scenario_id,
            "Ergonomics clone",
            "C",
            60,
        )
        with store.connection() as conn:
            rows = conn.execute(
                """SELECT work.id, COUNT(review.id) AS review_count,
                          MIN(review.status) AS status,
                          MIN(review.risk_classification) AS risk_classification
                   FROM work_elements work
                   LEFT JOIN ergonomics_reviews review
                     ON review.project_id=work.project_id
                    AND review.scenario_id=work.scenario_id
                    AND review.work_element_id=work.id
                   WHERE work.project_id=? AND work.scenario_id=?
                   GROUP BY work.id""",
                (self.project_id, cloned_scenario_id),
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0]["review_count"]), 1)
        self.assertEqual(rows[0]["status"], "Started")
        self.assertEqual(rows[0]["risk_classification"], "Not yet assessed")

    def test_scenario_clone_copies_linked_unlinked_and_hazard_review_content(self) -> None:
        hazard_id = self._create_hazards()[0]
        linked_review_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "work_element_id": self.work_element_id,
                "process_part_option_id": self.option_id,
                "status": "Pending",
                "risk_classification": "Favorable Red",
                "reviewer": "Alex Ergonomist",
                "notes": "Carry forward lift assessment",
                "requested_due_date": "2026-10-01",
                "hazard_option_ids": [hazard_id],
            },
        )["id"]
        unlinked_review_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {"status": "Open", "notes": "Legacy production concern"},
        )["id"]
        source_selection_id = store.query(
            """SELECT id FROM ergonomics_review_hazard_selections
               WHERE ergonomics_review_id=?""",
            (linked_review_id,),
        )[0]["id"]

        cloned_scenario_id = store.clone_planning_scenario(
            self.project_id, self.scenario_id, "Review clone", "C", 48
        )
        cloned_work = store.query(
            """SELECT id FROM work_elements
               WHERE project_id=? AND scenario_id=? AND operation='Lift bracket'""",
            (self.project_id, cloned_scenario_id),
        )[0]
        cloned_option = store.query(
            """SELECT option.id
               FROM process_part_options option
               JOIN process_part_groups group_row ON group_row.id=option.group_id
               WHERE group_row.project_id=? AND group_row.scenario_id=?
                 AND group_row.work_element_id=?""",
            (self.project_id, cloned_scenario_id, cloned_work["id"]),
        )[0]
        cloned_reviews = store.ergonomics_reviews(
            self.project_id, cloned_scenario_id
        )

        self.assertEqual(len(cloned_reviews), 2)
        linked = cloned_reviews.loc[
            cloned_reviews["notes"].eq("Carry forward lift assessment")
        ].iloc[0]
        unlinked = cloned_reviews.loc[
            cloned_reviews["notes"].eq("Legacy production concern")
        ].iloc[0]
        self.assertNotIn(linked["id"], {linked_review_id, unlinked_review_id})
        self.assertNotIn(unlinked["id"], {linked_review_id, unlinked_review_id})
        self.assertEqual(linked["work_element_id"], cloned_work["id"])
        self.assertEqual(linked["process_part_option_id"], cloned_option["id"])
        self.assertEqual(linked["status"], "Pending")
        self.assertEqual(linked["risk_classification"], "Favorable Red")
        self.assertEqual(linked["reviewer"], "Alex Ergonomist")
        self.assertEqual(linked["requested_due_date"], "2026-10-01")
        self.assertEqual(linked["hazard_option_ids"], [hazard_id])
        self.assertTrue(pd.isna(unlinked["work_element_id"]))
        cloned_selection = store.query(
            """SELECT id, hazard_option_id
               FROM ergonomics_review_hazard_selections
               WHERE ergonomics_review_id=?""",
            (linked["id"],),
        )[0]
        self.assertNotEqual(cloned_selection["id"], source_selection_id)
        self.assertEqual(cloned_selection["hazard_option_id"], hazard_id)

    def test_scenario_clone_nulls_unmapped_process_part_option(self) -> None:
        skipped_group_id = "unmapped-source-group"
        skipped_option_id = "unmapped-source-option"
        source_review_id = "unmapped-option-review"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id,
                    name, selection_rule, quantity, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'Unmapped requirement', 'Use all', 1, ?)""",
                (
                    skipped_group_id,
                    self.project_id,
                    self.scenario_id,
                    self.other_work_element_id,
                    self.section_id,
                    timestamp,
                ),
            )
            conn.execute(
                """INSERT INTO process_part_options
                   (id, group_id, part_id, updated_at) VALUES (?, ?, ?, ?)""",
                (skipped_option_id, skipped_group_id, self.part_id, timestamp),
            )
            conn.execute(
                """INSERT INTO ergonomics_reviews
                   (id, project_id, scenario_id, work_element_id,
                    process_part_option_id, status, risk_classification,
                    reviewer, notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'Open', 'Red', '',
                           'Option cannot be cloned', ?, ?)""",
                (
                    source_review_id,
                    self.project_id,
                    self.scenario_id,
                    self.work_element_id,
                    skipped_option_id,
                    timestamp,
                    timestamp,
                ),
            )

        cloned_scenario_id = store.clone_planning_scenario(
            self.project_id, self.scenario_id, "Unmapped option clone", "C", 60
        )
        cloned = store.ergonomics_reviews(
            self.project_id, cloned_scenario_id
        ).loc[lambda frame: frame["notes"].eq("Option cannot be cloned")].iloc[0]
        self.assertNotEqual(cloned["id"], source_review_id)
        self.assertFalse(pd.isna(cloned["work_element_id"]))
        self.assertTrue(pd.isna(cloned["process_part_option_id"]))

    def test_scenario_clone_copies_multiple_reviews_and_removes_only_placeholder(self) -> None:
        edited_review_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "work_element_id": self.work_element_id,
                "status": "Open",
                "notes": "Edited source review",
            },
        )["id"]
        blank_review_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {"work_element_id": self.work_element_id},
        )["id"]

        cloned_scenario_id = store.clone_planning_scenario(
            self.project_id, self.scenario_id, "Multiple review clone", "C", 60
        )
        cloned_work_id = store.query(
            """SELECT id FROM work_elements
               WHERE project_id=? AND scenario_id=? AND operation='Lift bracket'""",
            (self.project_id, cloned_scenario_id),
        )[0]["id"]
        cloned_reviews = store.ergonomics_reviews(
            self.project_id, cloned_scenario_id, cloned_work_id
        )

        self.assertEqual(len(cloned_reviews), 2)
        self.assertTrue(
            {edited_review_id, blank_review_id}.isdisjoint(set(cloned_reviews["id"]))
        )
        self.assertEqual(
            len(cloned_reviews.loc[cloned_reviews["notes"].eq("Edited source review")]),
            1,
        )
        blank_rows = cloned_reviews.loc[
            cloned_reviews["status"].eq("Started")
            & cloned_reviews["risk_classification"].eq("Not yet assessed")
            & cloned_reviews["reviewer"].eq("")
            & cloned_reviews["notes"].eq("")
        ]
        self.assertEqual(len(blank_rows), 1)

    def test_ergonomics_schema_has_no_clone_rereview_or_takt_comparison_fields(self) -> None:
        with store.connection() as conn:
            columns = {
                str(row["name"])
                for row in conn.execute(
                    "PRAGMA table_info(ergonomics_reviews)"
                ).fetchall()
            }
        self.assertFalse(
            any(
                fragment in column.casefold()
                for column in columns
                for fragment in (
                    "re_review",
                    "rereview",
                    "source_takt",
                    "takt_difference",
                    "takt_comparison",
                )
            )
        )

    def test_new_database_sample_steps_each_receive_exactly_one_review(self) -> None:
        with store.connection() as conn:
            rows = conn.execute(
                """SELECT work.id, COUNT(review.id) AS review_count
                   FROM work_elements work
                   JOIN projects project ON project.id=work.project_id
                   LEFT JOIN ergonomics_reviews review
                     ON review.project_id=work.project_id
                    AND review.scenario_id=work.scenario_id
                    AND review.work_element_id=work.id
                   WHERE project.name='Sample NPI launch'
                   GROUP BY work.id"""
            ).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(int(row["review_count"]) == 1 for row in rows))

    def test_historical_review_backfill_is_complete_and_idempotent(self) -> None:
        missing_ids = ["historical-ergo-step-1", "historical-ergo-step-2"]
        existing_id = "historical-ergo-step-with-review"
        timestamp = store.now_iso()
        with store.connection() as conn:
            store._backfill_missing_ergonomics_reviews(conn)
            for sequence, work_id in enumerate([*missing_ids, existing_id], start=20):
                conn.execute(
                    """INSERT INTO work_elements
                       (id, project_id, scenario_id, sequence, operation, updated_at)
                       VALUES (?, ?, ?, ?, 'Historical step', ?)""",
                    (work_id, self.project_id, self.scenario_id, sequence, timestamp),
                )
            store._create_started_ergonomics_review(
                conn,
                self.project_id,
                self.scenario_id,
                existing_id,
                timestamp,
            )
            affected = store._backfill_missing_ergonomics_reviews(conn)
            affected_second_run = store._backfill_missing_ergonomics_reviews(conn)
            rows = conn.execute(
                """SELECT work_element_id, COUNT(*) AS review_count,
                          MIN(status) AS status,
                          MIN(risk_classification) AS risk_classification,
                          MIN(reviewer) AS reviewer,
                          MIN(notes) AS notes,
                          MIN(requested_due_date) AS requested_due_date
                   FROM ergonomics_reviews
                   WHERE project_id=? AND scenario_id=?
                     AND work_element_id IN (?, ?, ?)
                   GROUP BY work_element_id""",
                (
                    self.project_id,
                    self.scenario_id,
                    *missing_ids,
                    existing_id,
                ),
            ).fetchall()

        self.assertEqual(affected, 2)
        self.assertEqual(affected_second_run, 0)
        self.assertEqual({str(row["work_element_id"]) for row in rows}, {*missing_ids, existing_id})
        self.assertTrue(all(int(row["review_count"]) == 1 for row in rows))
        self.assertTrue(all(row["status"] == "Started" for row in rows))
        self.assertTrue(
            all(row["risk_classification"] == "Not yet assessed" for row in rows)
        )
        self.assertTrue(all(row["reviewer"] == "" for row in rows))
        self.assertTrue(all(row["notes"] == "" for row in rows))
        self.assertTrue(all(row["requested_due_date"] is None for row in rows))

    def test_process_ergonomics_risk_requires_status_and_classification_together(self) -> None:
        review_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "work_element_id": self.work_element_id,
                "status": "Open",
                "risk_classification": "Green",
            },
        )["id"]
        self.assertEqual(
            store.process_ergonomics_risk_work_element_ids(
                self.project_id, self.scenario_id
            ),
            set(),
        )

        store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "id": review_id,
                "work_element_id": self.work_element_id,
                "status": "Validation",
                "risk_classification": "Red",
            },
        )
        self.assertEqual(
            store.process_ergonomics_risk_work_element_ids(
                self.project_id, self.scenario_id
            ),
            set(),
        )

        store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "id": review_id,
                "work_element_id": self.work_element_id,
                "status": "Pending",
                "risk_classification": "Favorable Red",
            },
        )
        self.assertEqual(
            store.process_ergonomics_risk_work_element_ids(
                self.project_id, self.scenario_id
            ),
            {self.work_element_id},
        )

        store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "id": review_id,
                "work_element_id": self.work_element_id,
                "status": "Closed (engineering)",
                "risk_classification": "Favorable Red",
            },
        )
        self.assertEqual(
            store.process_ergonomics_risk_work_element_ids(
                self.project_id, self.scenario_id
            ),
            set(),
        )

    def test_process_ergonomics_risk_uses_any_linked_review_and_stays_scenario_scoped(self) -> None:
        store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "work_element_id": self.work_element_id,
                "status": "Started",
                "risk_classification": "Not yet assessed",
            },
        )
        store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "work_element_id": self.work_element_id,
                "status": "Open",
                "risk_classification": "Red",
            },
        )
        store.save_ergonomics_review(
            self.project_id,
            self.other_scenario_id,
            {
                "work_element_id": self.other_work_element_id,
                "status": "Pending",
                "risk_classification": "Red",
            },
        )

        self.assertEqual(
            store.process_ergonomics_risk_work_element_ids(
                self.project_id, self.scenario_id
            ),
            {self.work_element_id},
        )

    def test_link_to_empty_placeholder_silently_keeps_edited_review(self) -> None:
        hazard_id = self._create_hazards()[0]
        placeholder_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {"work_element_id": self.work_element_id},
        )["id"]
        candidate_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "notes": "Legacy lift concern",
                "hazard_option_ids": [hazard_id],
            },
        )["id"]
        rows = store.ergonomics_reviews(self.project_id, self.scenario_id).to_dict(
            "records"
        )
        for row in rows:
            if row["id"] == candidate_id:
                row["work_element_id"] = self.work_element_id

        plan = store.ergonomics_review_save_plan(
            self.project_id, self.scenario_id, rows, [candidate_id]
        )
        self.assertEqual(plan["conflicts"], [])
        self.assertEqual(plan["silent_merges"][0]["existing_id"], placeholder_id)
        result = store.save_ergonomics_review_rows(
            self.project_id,
            self.scenario_id,
            rows,
            link_candidate_ids=[candidate_id],
            editor_name="Alex Ergonomist",
        )

        self.assertEqual(result["discarded_ids"], [placeholder_id])
        saved = store.ergonomics_reviews(self.project_id, self.scenario_id)
        self.assertEqual(list(saved["id"]), [candidate_id])
        self.assertEqual(saved.iloc[0]["hazard_option_ids"], [hazard_id])
        audit = store.audit_history(
            self.project_id, "Ergonomics reviews", limit=10
        )
        self.assertIn("Merge reviews", set(audit["action"]))
        merge_row = audit.loc[audit["action"].eq("Merge reviews")].iloc[0]
        self.assertEqual(merge_row["editor_name"], "Alex Ergonomist")

    def test_link_with_two_edited_reviews_requires_and_respects_survivor(self) -> None:
        target_hazard, candidate_hazard = self._create_hazards()
        target_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "work_element_id": self.work_element_id,
                "status": "Open",
                "notes": "Target review content",
                "hazard_option_ids": [target_hazard],
            },
        )["id"]
        candidate_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "status": "Pending",
                "notes": "Candidate review content",
                "hazard_option_ids": [candidate_hazard],
            },
        )["id"]
        rows = store.ergonomics_reviews(self.project_id, self.scenario_id).to_dict(
            "records"
        )
        for row in rows:
            if row["id"] == candidate_id:
                row["work_element_id"] = self.work_element_id

        plan = store.ergonomics_review_save_plan(
            self.project_id, self.scenario_id, rows, [candidate_id]
        )
        self.assertEqual(len(plan["conflicts"]), 1)
        with self.assertRaisesRegex(ValueError, "Confirm which"):
            store.save_ergonomics_review_rows(
                self.project_id,
                self.scenario_id,
                rows,
                link_candidate_ids=[candidate_id],
            )

        result = store.save_ergonomics_review_rows(
            self.project_id,
            self.scenario_id,
            rows,
            link_candidate_ids=[candidate_id],
            merge_survivors={candidate_id: target_id},
            editor_name="Alex Ergonomist",
        )
        self.assertEqual(result["discarded_ids"], [candidate_id])
        saved = store.ergonomics_reviews(self.project_id, self.scenario_id)
        self.assertEqual(list(saved["id"]), [target_id])
        self.assertEqual(saved.iloc[0]["notes"], "Target review content")
        selection_rows = store.query(
            """SELECT ergonomics_review_id, hazard_option_id
               FROM ergonomics_review_hazard_selections"""
        )
        self.assertEqual(
            [(row["ergonomics_review_id"], row["hazard_option_id"]) for row in selection_rows],
            [(target_id, target_hazard)],
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

    def test_part_use_and_work_deletion_preserve_review_by_nulling_links(self) -> None:
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
                """SELECT process_part_option_id, work_element_id, reviewer, notes
                   FROM ergonomics_reviews WHERE id=?""",
                (review_id,),
            ).fetchone()
            self.assertIsNone(review["process_part_option_id"])
            conn.execute("DELETE FROM work_elements WHERE id=?", (self.work_element_id,))
            review = conn.execute(
                """SELECT process_part_option_id, work_element_id, reviewer, notes
                   FROM ergonomics_reviews WHERE id=?""",
                (review_id,),
            ).fetchone()
            self.assertIsNone(review["work_element_id"])
            self.assertIsNone(review["process_part_option_id"])
            self.assertEqual(review["reviewer"], "")
            self.assertEqual(review["notes"], "")


if __name__ == "__main__":
    unittest.main()
