from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from utils import quality_store, store


class QualityStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        connection_patcher = patch.object(store, "connection", self._test_connection)
        connection_patcher.start()
        self.addCleanup(connection_patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()

        self.project_id = "quality-project"
        self.scenario_id = "quality-scenario"
        self.work_element_id = "quality-step"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, program, product_line, owner, revision, status,
                    takt_time_s, notes, created_at, updated_at)
                   VALUES (?, 'Quality project', '', '', '', 'A', 'Draft', 60, '', ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, status,
                    takt_time_s, change_summary, created_by, created_at, updated_at)
                   VALUES (?, ?, 'Current plan', 'A', 1, 'Working', 60, '', '', ?, ?)""",
                (self.scenario_id, self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, operation, updated_at)
                   VALUES (?, ?, ?, 10, 'Install screw', ?)""",
                (self.work_element_id, self.project_id, self.scenario_id, timestamp),
            )

    @contextmanager
    def _test_connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def requirement_values(self, **overrides) -> dict:
        values = {
            "requirement_type": "Torque",
            "description": "Tighten the mounting screw",
            "unique_identifier": "TQ-001",
            "pass_fail": True,
            "target_value": 32,
            "tolerances": "+/- 3",
            "unit": "N·m",
        }
        values.update(overrides)
        return values

    def test_init_creates_quality_tables(self) -> None:
        store.init_db()
        with store.connection() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    """SELECT name FROM sqlite_master
                       WHERE type='table' AND name LIKE 'quality_%'"""
                ).fetchall()
            }
        self.assertEqual(
            tables,
            {
                "quality_requirements",
                "quality_requirement_assignments",
                "quality_requirement_torque_details",
            },
        )

    def test_torque_details_are_one_to_one_and_offer_saved_bit_values(self) -> None:
        requirement_id = quality_store.save_quality_requirement(
            self.project_id, self.requirement_values()
        )
        created = quality_store.save_quality_requirement_torque_detail(
            self.project_id,
            requirement_id,
            {
                "tool_type": "DC tool",
                "tool_orientation": "Right angle",
                "screw_bit_type": "Torx T30",
            },
        )
        updated = quality_store.save_quality_requirement_torque_detail(
            self.project_id,
            requirement_id,
            {
                "id": created["id"],
                "tool_type": "Electric clutch tool",
                "tool_orientation": "Pistol",
                "screw_bit_type": "Torx T30",
            },
        )

        details = quality_store.quality_requirement_torque_details(
            self.project_id, requirement_id
        )
        self.assertEqual(len(details), 1)
        self.assertEqual(details.iloc[0]["id"], created["id"])
        self.assertEqual(updated["id"], created["id"])
        self.assertEqual(details.iloc[0]["tool_type"], "Electric clutch tool")
        self.assertEqual(
            quality_store.torque_screw_bit_types(self.project_id),
            ["Torx T30"],
        )

    def test_torque_details_require_torque_parent_and_controlled_tool_values(self) -> None:
        non_torque_id = quality_store.save_quality_requirement(
            self.project_id,
            self.requirement_values(
                requirement_type="Vision", unique_identifier="VS-001"
            ),
        )
        with self.assertRaisesRegex(ValueError, "only be saved for a Torque"):
            quality_store.save_quality_requirement_torque_detail(
                self.project_id,
                non_torque_id,
                {
                    "tool_type": "DC tool",
                    "tool_orientation": "Pistol",
                    "screw_bit_type": "Phillips #2",
                },
            )

        torque_id = quality_store.save_quality_requirement(
            self.project_id,
            self.requirement_values(unique_identifier="TQ-002"),
        )
        with self.assertRaisesRegex(ValueError, "approved choices"):
            quality_store.save_quality_requirement_torque_detail(
                self.project_id,
                torque_id,
                {
                    "tool_type": "Manual wrench",
                    "tool_orientation": "Pistol",
                    "screw_bit_type": "Phillips #2",
                },
            )

    def test_torque_detail_must_be_removed_before_parent_type_or_parent_deletion(self) -> None:
        requirement_id = quality_store.save_quality_requirement(
            self.project_id, self.requirement_values()
        )
        detail = quality_store.save_quality_requirement_torque_detail(
            self.project_id,
            requirement_id,
            {
                "tool_type": "Air tool",
                "tool_orientation": "In-line",
                "screw_bit_type": "Hex 6 mm",
            },
        )

        with self.assertRaisesRegex(ValueError, "before changing this requirement's Type"):
            quality_store.save_quality_requirement(
                self.project_id,
                self.requirement_values(requirement_type="Vision"),
                requirement_id,
            )
        edited_repository = quality_store.quality_requirements(self.project_id)
        edited_repository.loc[
            edited_repository["id"].astype(str).eq(requirement_id),
            "requirement_type",
        ] = "Vision"
        with self.assertRaisesRegex(ValueError, "before changing this requirement's Type"):
            quality_store.save_quality_requirement_rows(
                self.project_id,
                edited_repository.reindex(
                    columns=[
                        "id",
                        "requirement_type",
                        "description",
                        "unique_identifier",
                        "pass_fail",
                        "target_value",
                        "tolerances",
                        "unit",
                    ]
                ),
            )
        with self.assertRaisesRegex(ValueError, "Torque tool detail"):
            quality_store.delete_quality_requirements(
                self.project_id, [requirement_id]
            )

        self.assertEqual(
            quality_store.delete_quality_requirement_torque_details(
                self.project_id, requirement_id, [str(detail["id"])]
            ),
            1,
        )
        self.assertEqual(
            quality_store.delete_quality_requirements(
                self.project_id, [requirement_id]
            ),
            1,
        )

    def test_repository_update_waits_for_explicit_push(self) -> None:
        requirement_id = quality_store.save_quality_requirement(
            self.project_id, self.requirement_values()
        )
        quality_store.assign_quality_requirement(
            self.project_id,
            self.scenario_id,
            self.work_element_id,
            requirement_id,
        )

        quality_store.save_quality_requirement(
            self.project_id,
            self.requirement_values(description="Tighten and record the mounting screw"),
            requirement_id,
        )
        before_push = quality_store.quality_requirement_assignments(
            self.project_id, self.scenario_id
        ).iloc[0]
        self.assertEqual(before_push["description"], "Tighten the mounting screw")
        self.assertEqual(before_push["repository_update_pending"], 1)

        self.assertEqual(
            quality_store.push_quality_requirements(self.project_id, [requirement_id]),
            1,
        )
        after_push = quality_store.quality_requirement_assignments(
            self.project_id, self.scenario_id
        ).iloc[0]
        self.assertEqual(
            after_push["description"], "Tighten and record the mounting screw"
        )
        self.assertEqual(after_push["repository_update_pending"], 0)

    def test_table_save_creates_updates_and_refuses_implicit_deletion(self) -> None:
        created = quality_store.save_quality_requirement_rows(
            self.project_id,
            pd.DataFrame([self.requirement_values() | {"id": ""}]),
        )
        self.assertEqual(created["row_count"], 1)
        requirement_id = created["created_ids"][0]

        saved = quality_store.quality_requirements(self.project_id)
        saved.loc[0, "description"] = "Tighten and verify the mounting screw"
        updated = quality_store.save_quality_requirement_rows(
            self.project_id,
            saved.reindex(
                columns=[
                    "id",
                    "requirement_type",
                    "description",
                    "unique_identifier",
                    "pass_fail",
                    "target_value",
                    "tolerances",
                    "unit",
                ]
            ),
        )
        self.assertEqual(updated["updated_ids"], [requirement_id])
        with self.assertRaisesRegex(ValueError, "confirmed deletion workflow"):
            quality_store.save_quality_requirement_rows(
                self.project_id,
                pd.DataFrame(columns=[
                    "id",
                    "requirement_type",
                    "description",
                    "unique_identifier",
                    "pass_fail",
                    "target_value",
                    "tolerances",
                    "unit",
                ]),
            )

    def test_bulk_pass_fail_update_validates_all_selected_requirements(self) -> None:
        first_id = quality_store.save_quality_requirement(
            self.project_id, self.requirement_values(pass_fail=False)
        )
        second_id = quality_store.save_quality_requirement(
            self.project_id,
            self.requirement_values(
                unique_identifier="TQ-002", description="Tighten the second screw",
                pass_fail=False,
            ),
        )
        result = quality_store.bulk_update_quality_requirement_pass_fail(
            self.project_id, [first_id, second_id], True
        )
        self.assertEqual(result["row_count"], 2)
        self.assertTrue(quality_store.quality_requirements(self.project_id)["pass_fail"].all())

        with self.assertRaisesRegex(ValueError, "no longer exist"):
            quality_store.bulk_update_quality_requirement_pass_fail(
                self.project_id, [first_id, "missing-requirement"], False
            )
        self.assertTrue(quality_store.quality_requirements(self.project_id)["pass_fail"].all())

    def test_validates_identifiers_units_and_scenario_boundaries(self) -> None:
        requirement_id = quality_store.save_quality_requirement(
            self.project_id, self.requirement_values()
        )
        with self.assertRaisesRegex(ValueError, "unique within the project"):
            quality_store.save_quality_requirement(
                self.project_id,
                self.requirement_values(unique_identifier="tq-001"),
            )
        with self.assertRaisesRegex(ValueError, "must use inches"):
            quality_store.save_quality_requirement(
                self.project_id,
                self.requirement_values(
                    requirement_type="Dimensional", unique_identifier="DIM-001", unit="mm"
                ),
            )
        with self.assertRaisesRegex(ValueError, "no longer exists"):
            quality_store.assign_quality_requirement(
                self.project_id, "wrong-scenario", self.work_element_id, requirement_id
            )

    def test_linked_repository_requirement_cannot_be_deleted(self) -> None:
        requirement_id = quality_store.save_quality_requirement(
            self.project_id, self.requirement_values()
        )
        assignment_id = quality_store.assign_quality_requirement(
            self.project_id,
            self.scenario_id,
            self.work_element_id,
            requirement_id,
        )
        with self.assertRaisesRegex(ValueError, "linked Process requirement"):
            quality_store.delete_quality_requirements(self.project_id, [requirement_id])
        self.assertEqual(
            quality_store.delete_quality_requirement_assignments(
                self.project_id, self.scenario_id, [assignment_id]
            ),
            1,
        )
        self.assertEqual(
            quality_store.delete_quality_requirements(self.project_id, [requirement_id]),
            1,
        )

    def test_assignment_picker_data_prevents_duplicates_and_survives_rebalance(self) -> None:
        requirement_id = quality_store.save_quality_requirement(
            self.project_id, self.requirement_values()
        )
        assignment_id = quality_store.assign_quality_requirement(
            self.project_id,
            self.scenario_id,
            self.work_element_id,
            requirement_id,
        )
        with self.assertRaisesRegex(ValueError, "already attached"):
            quality_store.assign_quality_requirement(
                self.project_id,
                self.scenario_id,
                self.work_element_id,
                requirement_id,
            )

        choices = quality_store.quality_process_steps(
            self.project_id, self.scenario_id
        )
        self.assertEqual(choices.iloc[0]["id"], self.work_element_id)
        self.assertEqual(choices.iloc[0]["work_element"], "Install screw")

        rebalanced_steps = store.project_table(
            "work_elements", self.project_id, "sequence", scenario_id=self.scenario_id
        )
        rebalanced_steps.loc[
            rebalanced_steps["id"].astype(str).eq(self.work_element_id),
            ["station", "sequence"],
        ] = ["Pitch 20", 40]
        store.replace_work_elements(
            self.project_id, self.scenario_id, rebalanced_steps
        )

        links = quality_store.quality_requirement_links(
            self.project_id, requirement_id
        )
        self.assertEqual(len(links), 1)
        self.assertEqual(links.iloc[0]["assignment_id"], assignment_id)
        self.assertEqual(links.iloc[0]["work_element_id"], self.work_element_id)
        self.assertEqual(links.iloc[0]["pitch"], "Pitch 20")
        self.assertEqual(links.iloc[0]["sequence"], 40)
        self.assertEqual(links.iloc[0]["scenario_name"], "Current plan")

    def test_project_link_view_returns_one_row_per_assignment(self) -> None:
        first_requirement_id = quality_store.save_quality_requirement(
            self.project_id, self.requirement_values()
        )
        second_requirement_id = quality_store.save_quality_requirement(
            self.project_id,
            self.requirement_values(
                requirement_type="Vision",
                description="Confirm the screw is fully seated",
                unique_identifier="VS-001",
                target_value=None,
                tolerances="",
                unit="",
            ),
        )
        second_work_element_id = "quality-step-2"
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, operation, updated_at)
                   VALUES (?, ?, ?, 20, 'Verify screw', ?)""",
                (
                    second_work_element_id,
                    self.project_id,
                    self.scenario_id,
                    store.now_iso(),
                ),
            )

        quality_store.assign_quality_requirement(
            self.project_id,
            self.scenario_id,
            self.work_element_id,
            first_requirement_id,
        )
        quality_store.assign_quality_requirement(
            self.project_id,
            self.scenario_id,
            self.work_element_id,
            second_requirement_id,
        )
        quality_store.assign_quality_requirement(
            self.project_id,
            self.scenario_id,
            second_work_element_id,
            first_requirement_id,
        )

        links = quality_store.quality_requirement_links(self.project_id)

        self.assertEqual(len(links), 3)
        self.assertEqual(
            set(
                links.loc[
                    links["work_element_id"].eq(self.work_element_id),
                    "unique_identifier",
                ]
            ),
            {"TQ-001", "VS-001"},
        )
        self.assertEqual(
            set(
                links.loc[
                    links["quality_requirement_id"].eq(first_requirement_id),
                    "work_element_id",
                ]
            ),
            {self.work_element_id, second_work_element_id},
        )

    def test_project_link_view_uses_published_values_until_push(self) -> None:
        requirement_id = quality_store.save_quality_requirement(
            self.project_id, self.requirement_values()
        )
        quality_store.assign_quality_requirement(
            self.project_id,
            self.scenario_id,
            self.work_element_id,
            requirement_id,
        )
        quality_store.save_quality_requirement(
            self.project_id,
            self.requirement_values(
                description="New repository description",
                target_value=35,
            ),
            requirement_id,
        )

        published = quality_store.quality_requirement_links(self.project_id).iloc[0]

        self.assertEqual(published["description"], "Tighten the mounting screw")
        self.assertEqual(published["target_value"], 32)
        self.assertEqual(published["repository_update_pending"], 1)

    def test_project_link_view_includes_every_scenario_in_the_project(self) -> None:
        requirement_id = quality_store.save_quality_requirement(
            self.project_id, self.requirement_values()
        )
        quality_store.assign_quality_requirement(
            self.project_id,
            self.scenario_id,
            self.work_element_id,
            requirement_id,
        )
        second_scenario_id = "quality-scenario-b"
        second_work_element_id = "quality-step-b"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, status,
                    takt_time_s, change_summary, created_by, created_at, updated_at)
                   VALUES (?, ?, 'Alternate plan', 'B', 2, 'Working', 60, '', '', ?, ?)""",
                (second_scenario_id, self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, operation, updated_at)
                   VALUES (?, ?, ?, 10, 'Install alternate screw', ?)""",
                (
                    second_work_element_id,
                    self.project_id,
                    second_scenario_id,
                    timestamp,
                ),
            )
        quality_store.assign_quality_requirement(
            self.project_id,
            second_scenario_id,
            second_work_element_id,
            requirement_id,
        )

        links = quality_store.quality_requirement_links(self.project_id)

        self.assertEqual(len(links), 2)
        self.assertEqual(
            set(links["scenario_id"]),
            {self.scenario_id, second_scenario_id},
        )

    def test_unlink_uses_assignment_scenario_and_preserves_other_scenarios(self) -> None:
        requirement_id = quality_store.save_quality_requirement(
            self.project_id, self.requirement_values()
        )
        first_assignment_id = quality_store.assign_quality_requirement(
            self.project_id,
            self.scenario_id,
            self.work_element_id,
            requirement_id,
        )
        second_scenario_id = "quality-scenario-b"
        second_work_element_id = "quality-step-b"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, status,
                    takt_time_s, change_summary, created_by, created_at, updated_at)
                   VALUES (?, ?, 'Alternate plan', 'B', 2, 'Working', 60, '', '', ?, ?)""",
                (second_scenario_id, self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, operation, updated_at)
                   VALUES (?, ?, ?, 10, 'Install alternate screw', ?)""",
                (
                    second_work_element_id,
                    self.project_id,
                    second_scenario_id,
                    timestamp,
                ),
            )
        second_assignment_id = quality_store.assign_quality_requirement(
            self.project_id,
            second_scenario_id,
            second_work_element_id,
            requirement_id,
        )

        selected_assignment = quality_store.quality_requirement_assignment(
            self.project_id, first_assignment_id
        )
        self.assertEqual(selected_assignment["scenario_id"], self.scenario_id)

        with self.assertRaisesRegex(ValueError, "no longer exist"):
            quality_store.delete_quality_requirement_assignments(
                self.project_id,
                second_scenario_id,
                [first_assignment_id],
            )
        self.assertEqual(
            set(
                quality_store.quality_requirement_links(self.project_id)[
                    "assignment_id"
                ]
            ),
            {first_assignment_id, second_assignment_id},
        )

        self.assertEqual(
            quality_store.delete_quality_requirement_assignments(
                self.project_id,
                str(selected_assignment["scenario_id"]),
                [first_assignment_id],
            ),
            1,
        )
        remaining = quality_store.quality_requirement_links(self.project_id)
        self.assertEqual(list(remaining["assignment_id"]), [second_assignment_id])
        self.assertEqual(remaining.iloc[0]["scenario_id"], second_scenario_id)

    def test_scenario_clone_copies_assignments_to_cloned_process_steps(self) -> None:
        requirement_id = quality_store.save_quality_requirement(
            self.project_id, self.requirement_values()
        )
        quality_store.assign_quality_requirement(
            self.project_id,
            self.scenario_id,
            self.work_element_id,
            requirement_id,
        )

        new_scenario_id = store.clone_planning_scenario(
            self.project_id,
            self.scenario_id,
            "Alternate plan",
            "B",
            55,
        )
        cloned = quality_store.quality_requirement_assignments(
            self.project_id, new_scenario_id
        )
        self.assertEqual(len(cloned), 1)
        self.assertEqual(cloned.iloc[0]["quality_requirement_id"], requirement_id)
        self.assertNotEqual(cloned.iloc[0]["work_element_id"], self.work_element_id)
        self.assertEqual(cloned.iloc[0]["scenario_id"], new_scenario_id)


if __name__ == "__main__":
    unittest.main()
