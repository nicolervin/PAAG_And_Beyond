from __future__ import annotations

import sqlite3
import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from utils import control_plan_store, pfmea_store, quality_store, store


class ControlPlanStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        patcher = patch.object(store, "connection", self._connection)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()
        self.project_id = "cp-project"
        self.scenario_id = "cp-scenario"
        self.work_id = "cp-work"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, revision, status, takt_time_s, created_at, updated_at)
                   VALUES (?, 'MCP project', 'A', 'Draft', 60, ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, status,
                    takt_time_s, created_at, updated_at)
                   VALUES (?, ?, 'Current plan', 'A', 1, 'Working', 60, ?, ?)""",
                (self.scenario_id, self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    description, updated_at)
                   VALUES (?, ?, ?, 20, 'ST-020', 'Install pump', 'Install pump', ?)""",
                (self.work_id, self.project_id, self.scenario_id, timestamp),
            )
        requirement_id = quality_store.save_quality_requirement(
            self.project_id,
            {
                "requirement_type": "Torque", "description": "Pump bolt torque",
                "unique_identifier": "TQ-020", "pass_fail": False,
                "target_value": 30, "tolerances": "+/- 2", "unit": "N-m",
            },
        )
        self.requirement_id = requirement_id
        self.assignment_id = quality_store.assign_quality_requirement(
            self.project_id, self.scenario_id, self.work_id, requirement_id
        )
        quality_store.save_quality_requirement_torque_detail(
            self.project_id,
            requirement_id,
            {
                "tool_type": "DC tool", "tool_orientation": "Right angle",
                "screw_bit_type": "Torx T30",
            },
        )
        self.entry_id = pfmea_store.save_pfmea_entry_rows(
            self.project_id, self.scenario_id, self.work_id,
            pd.DataFrame([{
                "id": "", "potential_failure_mode": "Pump loose", "class_code": "P",
            }]),
        )["created_ids"][0]
        pfmea_store.save_pfmea_effect_rows(
            self.project_id, self.scenario_id, self.entry_id,
            pd.DataFrame([{"id": "", "effect_description": "Leak", "severity": 7}]),
        )
        pfmea_store.save_pfmea_cause_rows(
            self.project_id, self.scenario_id, self.entry_id,
            pd.DataFrame([{"id": "", "cause_description": "Bolt loose", "occurrence": 3}]),
        )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.at[0, "prevention_controls"] = [f"quality:{self.assignment_id}"]
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)

    @contextmanager
    def _connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def test_schema_projection_and_persistence(self) -> None:
        with store.connection() as conn:
            control_plan_store.init_control_plan_schema(conn)
        columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(control_plan_items)")
        }
        self.assertIn("source_fingerprint_snapshot", columns)
        self.assertIn("sequence", columns)
        self.assertIn("pr_number", columns)
        self.assertIn("characteristic_suffix", columns)
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        self.assertEqual(len(projection), 1)
        row = projection.iloc[0]
        self.assertEqual(row["pr_number"], 10.0)
        self.assertEqual(row["station_pitch"], "ST-020")
        self.assertEqual(row["classification"], "P")
        self.assertEqual(row["specification_requirement"], "30 +/- 2 N-m")
        self.assertIn("DC tool", row["measurement_evaluation"])
        self.assertFalse(row["persisted"])

        projection.loc[:, "characteristic_placement"] = "Process"
        projection.loc[:, "machine_fixture"] = "Torque spindle"
        result = control_plan_store.save_control_plan_rows(
            self.project_id, self.scenario_id, projection
        )
        self.assertEqual(result["row_count"], 1)
        reloaded = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        ).iloc[0]
        self.assertTrue(reloaded["persisted"])
        self.assertEqual(reloaded["machine_fixture"], "Torque spindle")
        self.assertTrue(str(reloaded["process_characteristic"]).startswith("10.1 "))

    def test_characteristic_suffix_validation_and_segment_numbering(self) -> None:
        self.assertIsNone(
            control_plan_store.normalize_control_plan_characteristic_suffix("")
        )
        self.assertEqual(
            control_plan_store.normalize_control_plan_characteristic_suffix("10"), 10
        )
        for value in (0, -1, 1.5, float("inf")):
            with self.assertRaisesRegex(ValueError, "positive whole number"):
                control_plan_store.normalize_control_plan_characteristic_suffix(value)

        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        control_plan_store.save_control_plan_rows(
            self.project_id, self.scenario_id, projection
        )
        item_id = self.conn.execute("SELECT id FROM control_plan_items").fetchone()[0]
        for invalid in (0, -1, 1.5):
            with self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute(
                    "UPDATE control_plan_items SET characteristic_suffix=? WHERE id=?",
                    (invalid, item_id),
                )
            self.conn.rollback()

        rows = pd.DataFrame(
            [
                {
                    "projection_order": index,
                    "projection_key": f"line-{index}",
                    "work_element_id": "work-a",
                    "operation_pr_number": 10.0,
                    "characteristic_suffix": None,
                    "source_description_snapshot": f"Characteristic {index + 1}",
                    "characteristic_placement": "Process",
                }
                for index in range(11)
            ]
        )
        numbered = control_plan_store.rebuild_control_plan_characteristic_numbers(rows)
        prefixes = [value.split()[0] for value in numbered["process_characteristic"]]
        self.assertEqual(prefixes[8:], ["10.9", "10.10", "10.11"])
        rows.loc[:, "operation_pr_number"] = 97.5
        rows.at[0, "characteristic_suffix"] = 1
        numbered = control_plan_store.rebuild_control_plan_characteristic_numbers(rows)
        self.assertTrue(numbered.iloc[0]["process_characteristic"].startswith("97.5.1 "))

    def test_manual_suffixes_reserve_numbers_without_reordering_and_persist(self) -> None:
        second_requirement = quality_store.save_quality_requirement(
            self.project_id,
            {
                "requirement_type": "Dimensional", "description": "Pump position",
                "unique_identifier": "DIM-SUFFIX", "pass_fail": False,
                "target_value": 1, "tolerances": "+/- 0.1", "unit": "in",
            },
        )
        second_assignment = quality_store.assign_quality_requirement(
            self.project_id, self.scenario_id, self.work_id, second_requirement
        )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.at[0, "detection_controls"] = [f"quality:{second_assignment}"]
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        original_keys = projection["projection_key"].tolist()
        projection.loc[:, "characteristic_placement"] = "Process"
        projection.at[projection.index[0], "characteristic_suffix"] = 2
        control_plan_store.save_control_plan_rows(
            self.project_id, self.scenario_id, projection
        )
        reloaded = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        self.assertEqual(reloaded["projection_key"].tolist(), original_keys)
        self.assertEqual(reloaded["characteristic_suffix"].tolist()[0], 2)
        self.assertEqual(
            [value.split()[0] for value in reloaded["process_characteristic"]],
            ["10.2", "10.1"],
        )
        reloaded.loc[:, "operation_pr_number"] = 30.0
        renumbered = control_plan_store.rebuild_control_plan_characteristic_numbers(
            reloaded
        )
        self.assertEqual(renumbered["characteristic_suffix"].tolist()[0], 2)
        self.assertEqual(
            [value.split()[0] for value in renumbered["process_characteristic"]],
            ["30.2", "30.1"],
        )

        clone_id = store.clone_planning_scenario(
            self.project_id, self.scenario_id, "Suffix clone", "C", 55
        )
        cloned = control_plan_store.control_plan_projection(self.project_id, clone_id)
        self.assertEqual(cloned["characteristic_suffix"].tolist()[0], 2)

    def test_unpushed_repository_edit_is_hidden_and_push_flags_review(self) -> None:
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        control_plan_store.save_control_plan_rows(self.project_id, self.scenario_id, projection)
        quality_store.save_quality_requirement(
            self.project_id,
            {
                "id": self.requirement_id, "requirement_type": "Torque",
                "description": "Updated repository-only description",
                "unique_identifier": "TQ-020", "pass_fail": False,
                "target_value": 45, "tolerances": "+/- 1", "unit": "N-m",
            },
        )
        before_push = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        ).iloc[0]
        self.assertEqual(before_push["source_description_snapshot"], "Pump bolt torque")
        self.assertEqual(before_push["specification_requirement"], "30 +/- 2 N-m")
        quality_store.push_quality_requirements(self.project_id, [self.requirement_id])
        after_push = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        ).iloc[0]
        self.assertEqual(
            after_push["source_description_snapshot"], "Updated repository-only description"
        )
        self.assertEqual(after_push["specification_requirement"], "45 +/- 1 N-m")
        self.assertTrue(after_push["source_review_required"])

    def test_multiple_characteristics_use_template_numbering(self) -> None:
        second_requirement = quality_store.save_quality_requirement(
            self.project_id,
            {
                "requirement_type": "Dimensional", "description": "Pump location",
                "unique_identifier": "DIM-020", "pass_fail": False,
                "target_value": 1.5, "tolerances": "+/- 0.1", "unit": "in",
            },
        )
        second_assignment = quality_store.assign_quality_requirement(
            self.project_id, self.scenario_id, self.work_id, second_requirement
        )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.at[0, "detection_controls"] = [f"quality:{second_assignment}"]
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        self.assertEqual(len(projection), 2)
        self.assertEqual(projection.iloc[0]["pr_number"], 10.0)
        self.assertTrue(pd.isna(projection.iloc[1]["pr_number"]))
        projection.loc[:, "characteristic_placement"] = "Product / Part"
        control_plan_store.save_control_plan_rows(self.project_id, self.scenario_id, projection)
        reloaded = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        prefixes = [value.split()[0] for value in reloaded["product_part_characteristic"]]
        self.assertEqual(prefixes, ["10.1", "10.2"])
        self.assertEqual(reloaded["station_pitch"].tolist(), ["ST-020", "ST-020"])

    def test_multiple_pfmea_failure_modes_share_one_operation_group(self) -> None:
        second_entry = "cp-entry-second"
        timestamp = store.now_iso()
        self.conn.execute(
            """INSERT INTO pfmea_entries
               (id, project_id, scenario_id, work_element_id,
                potential_failure_mode, class_code, process_operation_snapshot,
                process_description_snapshot, process_location_snapshot,
                process_pitch_snapshot, process_sequence_snapshot,
                process_source_hash, quality_source_hash, source_reviewed_at,
                created_at, updated_at)
               SELECT ?, project_id, scenario_id, work_element_id,
                      'Pump misaligned', 'Q', process_operation_snapshot,
                      process_description_snapshot, process_location_snapshot,
                      process_pitch_snapshot, process_sequence_snapshot,
                      process_source_hash, quality_source_hash, source_reviewed_at,
                      ?, ?
               FROM pfmea_entries WHERE id=?""",
            (second_entry, timestamp, timestamp, self.entry_id),
        )
        self.conn.commit()
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        self.assertEqual(len(projection), 2)
        self.assertEqual(projection["work_element_id"].tolist(), [self.work_id, self.work_id])
        self.assertEqual(
            set(projection["source_description_snapshot"]),
            {"Pump bolt torque", "Pump misaligned"},
        )
        projection.at[projection.index[0], "characteristic_placement"] = "Product / Part"
        projection.at[projection.index[1], "characteristic_placement"] = "Process"
        control_plan_store.save_control_plan_rows(
            self.project_id, self.scenario_id, projection
        )
        reloaded = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        displayed = (
            reloaded["product_part_characteristic"].fillna("")
            + reloaded["process_characteristic"].fillna("")
        ).tolist()
        self.assertTrue(displayed[0].startswith("10.1 "))
        self.assertTrue(displayed[1].startswith("10.2 "))

    def test_current_pitch_is_live_and_flags_pfmea_snapshot_difference(self) -> None:
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        projection.loc[:, "operation_pr_number"] = 97.0
        projection.loc[:, "pr_number"] = 97.0
        control_plan_store.save_control_plan_rows(
            self.project_id, self.scenario_id, projection
        )
        item_before = dict(
            self.conn.execute("SELECT * FROM control_plan_items").fetchone()
        )
        pfmea_before = dict(
            self.conn.execute(
                "SELECT * FROM pfmea_entries WHERE id=?", (self.entry_id,)
            ).fetchone()
        )

        self.conn.execute(
            """UPDATE work_elements SET station='ST-099'
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (self.work_id, self.project_id, self.scenario_id),
        )
        self.conn.commit()

        current = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        ).iloc[0]
        self.assertEqual(current["station_pitch"], "ST-099")
        self.assertEqual(current["operation_pr_number"], 97.0)
        self.assertTrue(current["source_review_required"])
        self.assertEqual(
            dict(self.conn.execute("SELECT * FROM control_plan_items").fetchone()),
            item_before,
        )
        self.assertEqual(
            dict(
                self.conn.execute(
                    "SELECT * FROM pfmea_entries WHERE id=?", (self.entry_id,)
                ).fetchone()
            ),
            pfmea_before,
        )

    def test_blank_current_pitch_displays_unassigned(self) -> None:
        self.conn.execute(
            """UPDATE work_elements SET station=''
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (self.work_id, self.project_id, self.scenario_id),
        )
        self.conn.commit()
        row = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        ).iloc[0]
        self.assertEqual(row["station_pitch"], "Unassigned")
        self.assertTrue(row["source_review_required"])

    def test_live_pitch_join_rejects_cross_scenario_process_relationship(self) -> None:
        other_scenario_id = "cp-other-scenario"
        timestamp = store.now_iso()
        self.conn.execute(
            """INSERT INTO planning_scenarios
               (id, project_id, name, revision_label, revision_sequence, status,
                takt_time_s, created_at, updated_at)
               VALUES (?, ?, 'Other plan', 'B', 2, 'Working', 60, ?, ?)""",
            (other_scenario_id, self.project_id, timestamp, timestamp),
        )
        self.conn.execute(
            "UPDATE pfmea_entries SET scenario_id=? WHERE id=?",
            (other_scenario_id, self.entry_id),
        )
        self.conn.commit()

        projection = control_plan_store.control_plan_projection(
            self.project_id, other_scenario_id
        )
        self.assertTrue(projection.empty)

    def test_same_quality_in_both_control_lists_deduplicates(self) -> None:
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.at[0, "detection_controls"] = [f"quality:{self.assignment_id}"]
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        self.assertEqual(len(projection), 1)

    def test_classified_entry_without_quality_control_gets_fallback(self) -> None:
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.at[0, "prevention_controls"] = []
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        self.assertEqual(len(projection), 1)
        self.assertEqual(projection.iloc[0]["source_kind"], "pfmea_only")
        self.assertEqual(projection.iloc[0]["source_description_snapshot"], "Pump loose")
        self.assertEqual(projection.iloc[0]["characteristic_placement"], "")
        self.assertEqual(projection.iloc[0]["product_part_characteristic"], "")
        self.assertEqual(projection.iloc[0]["process_characteristic"], "")

    def test_quality_unlink_orphans_persisted_item_without_losing_quality_data(self) -> None:
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        control_plan_store.save_control_plan_rows(self.project_id, self.scenario_id, projection)
        quality_store.delete_quality_requirement_assignments(
            self.project_id, self.scenario_id, [self.assignment_id], "Nicole"
        )
        saved = self.conn.execute("SELECT * FROM control_plan_items").fetchone()
        self.assertIsNone(saved["quality_requirement_assignment_id"])
        self.assertEqual(saved["source_quality_requirement_id_snapshot"], self.requirement_id)
        self.assertEqual(saved["source_description_snapshot"], "Pump bolt torque")
        self.assertEqual(saved["source_review_required"], 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM quality_requirements").fetchone()[0], 1
        )
        audit = self.conn.execute(
            "SELECT * FROM audit_log WHERE table_name='Control Plan'"
        ).fetchall()
        self.assertEqual(len(audit), 1)

    def test_orphan_never_reconnects_without_explicit_compatible_relink(self) -> None:
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        control_plan_store.save_control_plan_rows(self.project_id, self.scenario_id, projection)
        item_id = str(
            self.conn.execute("SELECT id FROM control_plan_items").fetchone()["id"]
        )
        quality_store.delete_quality_requirement_assignments(
            self.project_id, self.scenario_id, [self.assignment_id], "Nicole"
        )
        replacement = quality_store.assign_quality_requirement(
            self.project_id, self.scenario_id, self.work_id, self.requirement_id
        )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.at[0, "prevention_controls"] = [f"quality:{replacement}"]
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        self.assertTrue(
            control_plan_store.control_plan_projection(
                self.project_id, self.scenario_id
            ).empty
        )
        candidates = control_plan_store.control_plan_relink_candidates(
            self.project_id, self.scenario_id, item_id
        )
        self.assertEqual(candidates["id"].tolist(), [replacement])
        control_plan_store.relink_control_plan_item(
            self.project_id, self.scenario_id, item_id, replacement
        )
        reconnected = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        self.assertEqual(reconnected["id"].tolist(), [item_id])

    def test_exclusion_preserves_manual_content(self) -> None:
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        projection.loc[:, "control_method"] = "Verify controller result"
        control_plan_store.save_control_plan_rows(self.project_id, self.scenario_id, projection)
        persisted = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        ).iloc[0]
        control_plan_store.exclude_control_plan_projection_keys(
            self.project_id, self.scenario_id, [persisted["projection_key"]]
        )
        review = control_plan_store.control_plan_review_items(
            self.project_id, self.scenario_id
        )
        self.assertEqual(len(review), 1)
        self.assertEqual(review.iloc[0]["control_method"], "Verify controller result")

    def test_scenario_clone_remaps_pfmea_and_quality_links(self) -> None:
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        projection.loc[:, "who"] = "Operator"
        projection.loc[:, "operation_pr_number"] = 97.0
        projection.loc[:, "pr_number"] = 97.0
        control_plan_store.save_control_plan_rows(self.project_id, self.scenario_id, projection)
        new_scenario_id = store.clone_planning_scenario(
            self.project_id, self.scenario_id, "Alternate", "B", 55
        )
        cloned = control_plan_store.control_plan_projection(
            self.project_id, new_scenario_id
        )
        self.assertEqual(len(cloned), 1)
        self.assertEqual(cloned.iloc[0]["who"], "Operator")
        self.assertEqual(cloned.iloc[0]["operation_pr_number"], 97.0)
        self.assertNotEqual(cloned.iloc[0]["id"], projection.iloc[0]["id"])
        self.assertNotEqual(cloned.iloc[0]["pfmea_entry_id"], self.entry_id)
        self.assertNotEqual(
            cloned.iloc[0]["quality_requirement_assignment_id"], self.assignment_id
        )
        self.assertFalse(cloned.iloc[0]["source_review_required"])

    def test_pfmea_delete_cascades_only_dependent_working_draft(self) -> None:
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        control_plan_store.save_control_plan_rows(self.project_id, self.scenario_id, projection)
        impact = control_plan_store.control_plan_pfmea_delete_impact(
            self.project_id, self.scenario_id, [self.entry_id]
        )
        self.assertEqual(impact["item_count"], 1)
        pfmea_store.delete_pfmea_records(
            self.project_id, self.scenario_id, "pfmea_entries", [self.entry_id], "Nicole"
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM control_plan_items").fetchone()[0], 0
        )

    def test_process_number_suggestions_cover_ordering_edge_cases(self) -> None:
        suggest = control_plan_store.suggest_control_plan_pr_numbers
        self.assertEqual(suggest(["a", "b", "c"], {}), {"a": 10.0, "b": 20.0, "c": 30.0})
        self.assertEqual(
            suggest(["a", "b", "c", "d"], {"a": 10.0, "d": 40.0}),
            {"b": 20.0, "c": 30.0},
        )
        self.assertEqual(
            suggest(["a", "b", "c"], {"c": 30.0}),
            {"a": 10.0, "b": 20.0},
        )
        self.assertEqual(suggest(["a", "b"], {"a": 10.0}), {"b": 20.0})
        self.assertEqual(
            suggest(["a", "b", "c"], {"a": 10.0, "c": 10.1}),
            {"b": 20.1},
        )
        self.assertEqual(
            suggest(["a", "b"], {"a": 10.0}, occupied_numbers=[20.0]),
            {"b": 30.0},
        )
        self.assertEqual(
            suggest(["a", "b"], {"a": None}),
            {"b": 10.0},
        )

    def test_projection_suggestions_do_not_write_until_save(self) -> None:
        before = self.conn.execute("SELECT COUNT(*) FROM control_plan_items").fetchone()[0]
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        self.assertEqual(projection.iloc[0]["operation_pr_number"], 10.0)
        after = self.conn.execute("SELECT COUNT(*) FROM control_plan_items").fetchone()[0]
        self.assertEqual(before, after)

    def test_process_number_accepts_blank_and_negative_but_rejects_nonfinite(self) -> None:
        self.assertIsNone(control_plan_store.normalize_control_plan_pr_number(""))
        self.assertIsNone(control_plan_store.normalize_control_plan_pr_number(float("nan")))
        self.assertEqual(control_plan_store.normalize_control_plan_pr_number(-4.26), -4.3)
        for value in (float("inf"), float("-inf")):
            with self.assertRaisesRegex(ValueError, "finite decimal"):
                control_plan_store.normalize_control_plan_pr_number(value)

    def test_curated_process_number_drives_prefix_and_blank_is_preserved(self) -> None:
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        projection.loc[:, "operation_pr_number"] = 97.0
        projection.loc[:, "pr_number"] = 97.0
        projection.loc[:, "characteristic_placement"] = "Process"
        control_plan_store.save_control_plan_rows(self.project_id, self.scenario_id, projection)
        reloaded = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        self.assertEqual(reloaded.iloc[0]["operation_pr_number"], 97.0)
        self.assertTrue(reloaded.iloc[0]["process_characteristic"].startswith("97.1 "))

        reloaded.loc[:, "operation_pr_number"] = float("nan")
        reloaded.loc[:, "pr_number"] = float("nan")
        control_plan_store.save_control_plan_rows(self.project_id, self.scenario_id, reloaded)
        blank = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        ).iloc[0]
        self.assertTrue(pd.isna(blank["operation_pr_number"]))
        self.assertEqual(blank["process_characteristic"], "Pump bolt torque")

    def test_conflicting_numbers_for_one_operation_fail_atomically(self) -> None:
        second_requirement = quality_store.save_quality_requirement(
            self.project_id,
            {
                "requirement_type": "Dimensional", "description": "Pump position",
                "unique_identifier": "DIM-CP", "pass_fail": False,
                "target_value": 1, "tolerances": "+/- 0.1", "unit": "in",
            },
        )
        second_assignment = quality_store.assign_quality_requirement(
            self.project_id, self.scenario_id, self.work_id, second_requirement
        )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.at[0, "detection_controls"] = [f"quality:{second_assignment}"]
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        projection.at[projection.index[0], "operation_pr_number"] = 10.0
        projection.at[projection.index[1], "operation_pr_number"] = 20.0
        with self.assertRaisesRegex(ValueError, "conflicting Pr"):
            control_plan_store.save_control_plan_rows(
                self.project_id, self.scenario_id, projection
            )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM control_plan_items").fetchone()[0], 0
        )

    def test_legacy_process_number_backfill_is_atomic_audited_and_idempotent(self) -> None:
        projection = control_plan_store.control_plan_projection(
            self.project_id, self.scenario_id
        )
        control_plan_store.save_control_plan_rows(self.project_id, self.scenario_id, projection)
        saved = self.conn.execute(
            "SELECT id, pfmea_entry_id, quality_requirement_assignment_id FROM control_plan_items"
        ).fetchone()
        self.conn.execute("UPDATE control_plan_items SET pr_number=NULL")
        self.conn.commit()

        with self.assertRaisesRegex(ValueError, "Current editor"):
            control_plan_store.migrate_control_plan_pr_numbers(self.project_id, "")
        self.assertIsNone(
            self.conn.execute("SELECT pr_number FROM control_plan_items").fetchone()[0]
        )
        result = control_plan_store.migrate_control_plan_pr_numbers(
            self.project_id, "Nicole Ervin"
        )
        self.assertEqual(result["row_count"], 1)
        migrated = self.conn.execute("SELECT * FROM control_plan_items").fetchone()
        self.assertEqual(migrated["id"], saved["id"])
        self.assertEqual(migrated["pfmea_entry_id"], saved["pfmea_entry_id"])
        self.assertEqual(
            migrated["quality_requirement_assignment_id"],
            saved["quality_requirement_assignment_id"],
        )
        self.assertEqual(migrated["pr_number"], 20.0)
        audits = self.conn.execute(
            "SELECT * FROM audit_log WHERE table_name='Control Plan' "
            "AND action='Migrate Process numbers'"
        ).fetchall()
        self.assertEqual(len(audits), 1)
        details = json.loads(audits[0]["details"])
        self.assertEqual(details["operation_count"], 1)
        self.assertEqual(details["scenario_count"], 1)
        self.assertEqual(details["process_numbering_version"], 1)
        again = control_plan_store.migrate_control_plan_pr_numbers(
            self.project_id, "Nicole Ervin"
        )
        self.assertEqual(again["row_count"], 0)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE table_name='Control Plan' "
                "AND action='Migrate Process numbers'"
            ).fetchone()[0],
            1,
        )


if __name__ == "__main__":
    unittest.main()
