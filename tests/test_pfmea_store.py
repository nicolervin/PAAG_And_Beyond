from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from utils import pfmea_store, quality_store, store


class PfmeaStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        patcher = patch.object(store, "connection", self._connection)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()
        self.project_id = "pfmea-project"
        self.scenario_id = "pfmea-scenario"
        self.work_element_id = "pfmea-step"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, revision, status, takt_time_s, created_at, updated_at)
                   VALUES (?, 'PFMEA project', 'A', 'Draft', 60, ?, ?)""",
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
                    description, location, updated_at)
                   VALUES (?, ?, ?, 10, 'ST-010', 'Install screw',
                           'Install the bracket screw', 'LH front', ?)""",
                (self.work_element_id, self.project_id, self.scenario_id, timestamp),
            )
        requirement_id = quality_store.save_quality_requirement(
            self.project_id,
            {
                "requirement_type": "Torque",
                "description": "Tighten the bracket screw",
                "unique_identifier": "TQ-001",
                "pass_fail": False,
                "target_value": 32,
                "tolerances": "+/- 3",
                "unit": "N·m",
            },
        )
        self.assignment_id = quality_store.assign_quality_requirement(
            self.project_id, self.scenario_id, self.work_element_id, requirement_id
        )

    @contextmanager
    def _connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def create_entry(self) -> str:
        result = pfmea_store.save_pfmea_entry_rows(
            self.project_id,
            self.scenario_id,
            self.work_element_id,
            pd.DataFrame([{"id": "", "potential_failure_mode": "Screw is loose", "class_code": ""}]),
        )
        return result["created_ids"][0]

    def test_init_creates_all_pfmea_tables(self) -> None:
        with store.connection() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'pfmea_%'"
                ).fetchall()
            }
        self.assertEqual(
            tables,
            {
                "pfmea_entries",
                "pfmea_effects",
                "pfmea_causes",
                "pfmea_prevention_options",
                "pfmea_detection_options",
                "pfmea_prevention_selections",
                "pfmea_detection_selections",
                "pfmea_risk_rows",
                "pfmea_actions",
            },
        )

    def test_effect_cause_detection_control_and_rpn_are_persisted(self) -> None:
        entry_id = self.create_entry()
        effect_id = pfmea_store.save_pfmea_effect_rows(
            self.project_id,
            self.scenario_id,
            entry_id,
            pd.DataFrame([{"id": "", "effect_description": "Bracket separates", "severity": 8, "sequence": 10}]),
        )["created_ids"][0]
        cause_id = pfmea_store.save_pfmea_cause_rows(
            self.project_id,
            self.scenario_id,
            entry_id,
            pd.DataFrame([{"id": "", "cause_description": "Tool shuts off early", "occurrence": 3,
                           "detection": None, "sequence": 10}]),
        )["created_ids"][0]
        option_id = pfmea_store.save_pfmea_control_option_rows(
            self.project_id, "Detection",
            pd.DataFrame([{"id": "", "label": "Verify torque rundown", "active": True}]),
        )["created_ids"][0]
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.at[0, "detection_controls"] = [f"manual:{option_id}"]
        flat.loc[:, "detection"] = 4
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        controls = pfmea_store.pfmea_control_selections(self.project_id, self.scenario_id)
        self.assertEqual(len(controls), 1)
        self.assertEqual(controls.iloc[0]["control_type"], "Detection")
        self.assertEqual(controls.iloc[0]["source_key"], f"manual:{option_id}")
        risk = pfmea_store.pfmea_risk_rows(self.project_id, self.scenario_id, entry_id)
        self.assertEqual(len(risk), 1)
        risk_id = risk.iloc[0]["id"]
        self.assertEqual(risk.iloc[0]["rpn"], 96)
        self.assertEqual(effect_id, self.conn.execute(
            "SELECT pfmea_effect_id FROM pfmea_risk_rows"
        ).fetchone()[0])

        effects = pfmea_store.pfmea_effects(self.project_id, self.scenario_id, entry_id)
        effects.loc[0, "severity"] = 9
        pfmea_store.save_pfmea_effect_rows(
            self.project_id, self.scenario_id, entry_id, effects
        )
        updated_risk = pfmea_store.pfmea_risk_rows(
            self.project_id, self.scenario_id, entry_id
        ).iloc[0]
        self.assertEqual(updated_risk["id"], risk_id)
        self.assertEqual(updated_risk["rpn"], 108)

    def test_flat_save_inserts_two_idless_rows_for_distinct_process_steps(self) -> None:
        timestamp = store.now_iso()
        second_work_element_id = "pfmea-step-2"
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    description, location, updated_at)
                   VALUES (?, ?, ?, 20, 'ST-010', 'Install bracket',
                           'Install bracket', 'LH front', ?)""",
                (second_work_element_id, self.project_id, self.scenario_id, timestamp),
            )
        rows = pd.DataFrame(
            [
                {
                    "id": "", "work_element_id": self.work_element_id,
                    "item_number": "ST-010", "potential_failure_mode": "Housing missing",
                    "potential_effects": "Assembly incomplete", "potential_causes": "Part absent",
                },
                {
                    "id": "", "work_element_id": second_work_element_id,
                    "item_number": "ST-010", "potential_failure_mode": "Bracket loose",
                    "potential_effects": "Bracket separates", "potential_causes": "Fastener loose",
                },
            ]
        )
        result = pfmea_store.save_pfmea_flat_rows(
            self.project_id, self.scenario_id, rows
        )
        self.assertEqual(result["row_count"], 2)
        saved = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        self.assertEqual(len(saved), 2)
        self.assertEqual(set(saved["item_number"]), {"ST-010"})
        self.assertEqual(
            set(saved["potential_failure_mode"]), {"Housing missing", "Bracket loose"}
        )

    def test_process_function_only_and_partial_rating_rows_persist_without_rpn(self) -> None:
        process_only = pd.DataFrame(
            [{"id": "", "work_element_id": self.work_element_id, "item_number": "ST-010"}]
        )
        pfmea_store.save_pfmea_flat_rows(
            self.project_id, self.scenario_id, process_only
        )
        first_reload = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        self.assertEqual(len(first_reload), 1)
        self.assertEqual(first_reload.iloc[0]["item_number"], "ST-010")
        self.assertEqual(first_reload.iloc[0]["process_function"], "Install screw")
        self.assertEqual(first_reload.iloc[0]["potential_failure_mode"], "")
        self.assertTrue(pd.isna(first_reload.iloc[0]["rpn"]))

        severity_only = pd.DataFrame(
            [{
                "id": "", "work_element_id": self.work_element_id,
                "item_number": "ST-010", "severity": 7,
            }]
        )
        pfmea_store.save_pfmea_flat_rows(
            self.project_id,
            self.scenario_id,
            pd.concat([first_reload, severity_only], ignore_index=True, sort=False),
        )
        second_reload = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        self.assertEqual(len(second_reload), 2)
        self.assertEqual(second_reload["item_number"].tolist(), ["ST-010", "ST-010"])
        self.assertEqual(second_reload["severity"].isna().value_counts().to_dict(), {True: 1, False: 1})
        self.assertEqual(second_reload["severity"].dropna().tolist(), [7])
        self.assertTrue(second_reload["rpn"].isna().all())

    def test_invalid_new_flat_row_rolls_back_the_whole_save(self) -> None:
        rows = pd.DataFrame(
            [
                {
                    "id": "", "work_element_id": self.work_element_id,
                    "item_number": "ST-010", "potential_failure_mode": "Housing missing",
                    "potential_effects": "Assembly incomplete", "potential_causes": "Part absent",
                },
                {
                    "id": "", "work_element_id": "not-in-this-scenario",
                    "item_number": "ST-010", "potential_failure_mode": "",
                    "potential_effects": "Second effect", "potential_causes": "Second cause",
                },
            ]
        )
        with self.assertRaisesRegex(ValueError, "valid Process Function"):
            pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, rows)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM pfmea_entries").fetchone()[0], 0
        )

    def test_saved_first_row_plus_new_second_and_third_rows_all_persist(self) -> None:
        timestamp = store.now_iso()
        with store.connection() as conn:
            for step_id, sequence, pitch, operation in [
                ("pfmea-step-2", 20, "ST-010", "Install bracket"),
                ("pfmea-step-3", 30, "ST-020", "Verify assembly"),
            ]:
                conn.execute(
                    """INSERT INTO work_elements
                       (id, project_id, scenario_id, sequence, station, operation,
                        description, location, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'LH front', ?)""",
                    (step_id, self.project_id, self.scenario_id, sequence, pitch,
                     operation, operation, timestamp),
                )
        first = pd.DataFrame(
            [{
                "id": "", "work_element_id": self.work_element_id,
                "item_number": "ST-010", "potential_failure_mode": "Saved first",
                "potential_effects": "First effect", "potential_causes": "First cause",
            }]
        )
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, first)
        saved_first = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        new_rows = pd.DataFrame(
            [
                {
                    "id": "", "work_element_id": "pfmea-step-2", "item_number": "ST-010",
                    "potential_failure_mode": "New second", "potential_effects": "Second effect",
                    "potential_causes": "Second cause",
                },
                {
                    "id": "", "work_element_id": "pfmea-step-3", "item_number": "ST-020",
                    "potential_failure_mode": "New third", "potential_effects": "Third effect",
                    "potential_causes": "Third cause",
                },
            ]
        )
        result = pfmea_store.save_pfmea_flat_rows(
            self.project_id,
            self.scenario_id,
            pd.concat([saved_first, new_rows], ignore_index=True, sort=False),
        )
        self.assertGreaterEqual(result["row_count"], 3)
        reloaded = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        self.assertEqual(len(reloaded), 3)
        self.assertEqual(
            reloaded["potential_failure_mode"].tolist(),
            ["Saved first", "New second", "New third"],
        )
        self.assertEqual(
            reloaded["work_element_id"].tolist(),
            [self.work_element_id, "pfmea-step-2", "pfmea-step-3"],
        )

    def test_detection_control_change_requires_rating_review_until_cause_save(self) -> None:
        entry_id = self.create_entry()
        cause_id = pfmea_store.save_pfmea_cause_rows(
            self.project_id,
            self.scenario_id,
            entry_id,
            pd.DataFrame([{"id": "", "cause_description": "Wrong setup",
                           "occurrence": 2, "detection": None, "sequence": 10}]),
        )["created_ids"][0]
        option_id = pfmea_store.save_pfmea_control_option_rows(
            self.project_id, "Detection",
            pd.DataFrame([{"id": "", "label": "Manual visual confirmation", "active": True}]),
        )["created_ids"][0]
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.at[0, "detection_controls"] = [f"manual:{option_id}"]
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        cause = pfmea_store.pfmea_causes(
            self.project_id, self.scenario_id, entry_id
        ).iloc[0]
        self.assertTrue(bool(cause["detection_review_required"]))

        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.loc[:, "detection"] = 4
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        reviewed = pfmea_store.pfmea_causes(
            self.project_id, self.scenario_id, entry_id
        ).iloc[0]
        self.assertFalse(bool(reviewed["detection_review_required"]))

    def test_detection_can_be_saved_without_detection_control_text(self) -> None:
        entry_id = self.create_entry()
        pfmea_store.save_pfmea_cause_rows(
            self.project_id, self.scenario_id, entry_id,
            pd.DataFrame([{"id": "", "cause_description": "Wrong setup",
                           "occurrence": 2, "detection": None, "sequence": 10}]),
        )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.loc[:, "detection"] = 5
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        reloaded = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        self.assertEqual(reloaded.iloc[0]["detection"], 5)
        self.assertEqual(reloaded.iloc[0]["detection_controls"], [])

    def test_upstream_changes_flag_without_replacing_snapshots(self) -> None:
        entry_id = self.create_entry()
        before = pfmea_store.pfmea_entries(
            self.project_id, self.scenario_id, self.work_element_id
        ).iloc[0]
        self.assertFalse(bool(before["upstream_changes"]))
        snapshot = before["process_pitch_snapshot"]
        with store.connection() as conn:
            conn.execute(
                "UPDATE work_elements SET station='ST-020', updated_at=? WHERE id=?",
                (store.now_iso() + "-changed", self.work_element_id),
            )
        changed = pfmea_store.pfmea_entries(
            self.project_id, self.scenario_id, self.work_element_id
        ).iloc[0]
        self.assertTrue(bool(changed["upstream_changes"]))
        self.assertEqual(changed["process_pitch_snapshot"], snapshot)
        pfmea_store.review_pfmea_sources(
            self.project_id, self.scenario_id, entry_id
        )
        reviewed = pfmea_store.pfmea_entries(
            self.project_id, self.scenario_id, self.work_element_id
        ).iloc[0]
        self.assertFalse(bool(reviewed["upstream_changes"]))
        self.assertEqual(reviewed["process_pitch_snapshot"], "ST-020")

    def test_quality_push_flags_structured_control_without_changing_selection(self) -> None:
        entry_id = self.create_entry()
        cause_id = pfmea_store.save_pfmea_cause_rows(
            self.project_id,
            self.scenario_id,
            entry_id,
            pd.DataFrame([{"id": "", "cause_description": "Wrong setup",
                           "occurrence": 2, "detection": None, "sequence": 10}]),
        )["created_ids"][0]
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.at[0, "prevention_controls"] = [f"quality:{self.assignment_id}"]
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM quality_requirement_assignments WHERE id=?",
                (self.assignment_id,),
            ).fetchone()[0],
            1,
        )
        requirement_id = self.conn.execute(
            "SELECT quality_requirement_id FROM quality_requirement_assignments WHERE id=?",
            (self.assignment_id,),
        ).fetchone()[0]
        quality_store.save_quality_requirement(
            self.project_id,
            {
                "requirement_type": "Torque",
                "description": "Updated repository requirement",
                "unique_identifier": "TQ-001",
                "pass_fail": False,
                "target_value": 35,
                "tolerances": "+/- 3",
                "unit": "N·m",
            },
            requirement_id,
        )
        quality_store.push_quality_requirements(self.project_id, [requirement_id])
        cause = pfmea_store.pfmea_causes(
            self.project_id, self.scenario_id, entry_id
        ).iloc[0]
        self.assertTrue(bool(cause["control_source_review_required"]))
        selections = pfmea_store.pfmea_control_selections(self.project_id, self.scenario_id)
        self.assertEqual(selections.iloc[0]["source_key"], f"quality:{self.assignment_id}")
        self.assertTrue(bool(selections.iloc[0]["review_required"]))

    def test_action_resulting_rpn_is_calculated_and_saved(self) -> None:
        entry_id = self.create_entry()
        result = pfmea_store.save_pfmea_action_rows(
            self.project_id,
            self.scenario_id,
            entry_id,
            pd.DataFrame(
                [
                    {
                        "id": "",
                        "pfmea_cause_id": None,
                        "recommended_action": "Add error proofing",
                        "responsibility": "AQE",
                        "target_completion_date": "2026-10-01",
                        "actions_taken": "Sensor installed",
                        "resulting_severity": 8,
                        "resulting_occurrence": 2,
                        "resulting_detection": 2,
                        "sequence": 10,
                    }
                ]
            ),
        )
        self.assertEqual(result["row_count"], 1)
        action = pfmea_store.pfmea_actions(
            self.project_id, self.scenario_id, entry_id
        ).iloc[0]
        self.assertEqual(action["resulting_rpn"], 32)
        action_id = action["id"]
        actions = pfmea_store.pfmea_actions(self.project_id, self.scenario_id, entry_id)
        actions.loc[0, "resulting_occurrence"] = 3
        pfmea_store.save_pfmea_action_rows(
            self.project_id, self.scenario_id, entry_id, actions
        )
        updated = pfmea_store.pfmea_actions(
            self.project_id, self.scenario_id, entry_id
        ).iloc[0]
        self.assertEqual(updated["id"], action_id)
        self.assertEqual(updated["resulting_rpn"], 48)

    def test_flat_template_rows_preserve_normalized_multiplicity(self) -> None:
        entry_id = self.create_entry()
        pfmea_store.save_pfmea_effect_rows(
            self.project_id, self.scenario_id, entry_id,
            pd.DataFrame([
                {"id": "", "effect_description": "Bracket separates", "severity": 8, "sequence": 10},
                {"id": "", "effect_description": "Noise", "severity": 4, "sequence": 20},
            ]),
        )
        pfmea_store.save_pfmea_cause_rows(
            self.project_id, self.scenario_id, entry_id,
            pd.DataFrame([
                {"id": "", "cause_description": "Tool shuts off", "occurrence": 3,
                 "detection": None, "sequence": 10},
                {"id": "", "cause_description": "Wrong screw", "occurrence": 2,
                 "detection": None, "sequence": 20},
            ]),
        )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        self.assertEqual(len(flat), 4)
        self.assertEqual(flat["entry_id"].nunique(), 1)
        self.assertEqual(flat["effect_id"].nunique(), 2)
        self.assertEqual(flat["cause_id"].nunique(), 2)
        self.assertTrue(flat["item_number"].eq("ST-010").all())
        self.assertTrue(flat["process_function"].eq("Install screw").all())

    def test_flat_save_cannot_reassign_a_saved_process_function(self) -> None:
        entry_id = self.create_entry()
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    description, location, updated_at)
                   VALUES ('other-step', ?, ?, 20, 'ST-010', 'Install bracket',
                           'Install the bracket', 'LH front', ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.loc[:, "work_element_id"] = "other-step"
        with self.assertRaisesRegex(ValueError, "cannot be reassigned"):
            pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        saved = pfmea_store.pfmea_entries(
            self.project_id, self.scenario_id, self.work_element_id
        )
        self.assertEqual(saved.iloc[0]["id"], entry_id)
        self.assertTrue(
            pfmea_store.pfmea_entries(
                self.project_id, self.scenario_id, "other-step"
            ).empty
        )

    def test_pfmea_save_does_not_write_upstream_process_or_product_tables(self) -> None:
        statements: list[str] = []
        self.conn.set_trace_callback(statements.append)
        try:
            pfmea_store.save_pfmea_flat_rows(
                self.project_id,
                self.scenario_id,
                pd.DataFrame(
                    [{
                        "id": "", "entry_id": "", "effect_id": "", "cause_id": "",
                        "risk_row_id": "", "action_id": "",
                        "work_element_id": self.work_element_id,
                        "item_number": "ST-010", "process_function": "Install screw",
                        "potential_failure_mode": "Screw is loose",
                        "potential_effects": "Bracket separates", "severity": None,
                        "classification": "", "potential_causes": "Low torque",
                        "occurrence": None, "prevention_controls": "",
                        "detection_controls": "", "detection": None,
                        "recommended_action": "", "responsibility_target": "",
                        "actions_taken": "", "resulting_severity": None,
                        "resulting_occurrence": None, "resulting_detection": None,
                    }]
                ),
            )
        finally:
            self.conn.set_trace_callback(None)
        writes = [
            statement.upper() for statement in statements
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        ]
        protected_tables = [
            "WORK_ELEMENTS", "YAMAZUMI_ELEMENTS", "YAMAZUMI_PITCHES",
            "YAMAZUMI_AREAS", "ASSEMBLY_SECTIONS", "FISHBONE_PART_ASSIGNMENTS",
            "FISHBONE_NODES",
        ]
        self.assertFalse(
            [
                statement for statement in writes
                if any(table in statement for table in protected_tables)
            ]
        )

    def test_pfmea_reuses_process_pitch_and_work_element_display_sources(self) -> None:
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    description, location, updated_at)
                   VALUES ('pfmea-step-2', ?, ?, 20, 'ST-020', 'Verify assembly',
                           'Confirm the completed assembly', 'Inspection', ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES ('area-1', ?, ?, 'Main line', ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status,
                    sequence, updated_at)
                   VALUES ('pitch-1', ?, 'area-1', 'ST-010', 'Housing load',
                           'Active', 10, ?)""",
                (self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, description, time_s,
                    sequence, process_element_id, updated_at)
                   VALUES ('yamazumi-1', ?, 'area-1', 'pitch-1',
                           'Load housing from Yamazumi', 12, 10, ?, ?)""",
                (self.project_id, self.work_element_id, timestamp),
            )

        steps = pfmea_store.pfmea_process_steps(self.project_id, self.scenario_id)
        self.assertEqual(steps.iloc[0]["pitch"], "ST-010")
        self.assertEqual(
            steps.iloc[0]["work_element"], "Load housing from Yamazumi"
        )
        self.assertEqual(steps.iloc[1]["pitch"], "ST-020")
        self.assertEqual(steps.iloc[1]["work_element"], "Verify assembly")

        self.create_entry()
        pfmea_store.save_pfmea_entry_rows(
            self.project_id,
            self.scenario_id,
            "pfmea-step-2",
            pd.DataFrame(
                [{"id": "", "potential_failure_mode": "Check is missed", "class_code": ""}]
            ),
        )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        self.assertEqual(flat.iloc[0]["item_number"], "ST-010")
        self.assertEqual(
            flat.iloc[0]["process_function"], "Load housing from Yamazumi"
        )
        self.assertEqual(flat.iloc[1]["item_number"], "ST-020")
        self.assertEqual(flat.iloc[1]["process_function"], "Verify assembly")

    def test_flat_save_recalculates_initial_and_resulting_rpn(self) -> None:
        entry_id = self.create_entry()
        pfmea_store.save_pfmea_effect_rows(
            self.project_id, self.scenario_id, entry_id,
            pd.DataFrame([{"id": "", "effect_description": "Bracket separates",
                           "severity": 8, "sequence": 10}]),
        )
        cause_id = pfmea_store.save_pfmea_cause_rows(
            self.project_id, self.scenario_id, entry_id,
            pd.DataFrame([{"id": "", "cause_description": "Tool shuts off",
                           "occurrence": 3, "detection": None, "sequence": 10}]),
        )["created_ids"][0]
        pfmea_store.save_pfmea_action_rows(
            self.project_id, self.scenario_id, entry_id,
            pd.DataFrame([{
                "id": "", "pfmea_cause_id": cause_id,
                "recommended_action": "Add rundown monitoring", "responsibility": "AQE",
                "target_completion_date": "2026-10-01", "actions_taken": "Installed",
                "resulting_severity": 7, "resulting_occurrence": 2,
                "resulting_detection": 2, "sequence": 10,
            }]),
        )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.loc[:, "classification"] = "Critical Quality"
        flat.loc[:, "severity"] = 9
        flat.loc[:, "occurrence"] = 4
        flat.loc[:, "detection"] = 5
        flat.loc[:, "resulting_severity"] = 8
        flat.loc[:, "resulting_occurrence"] = 3
        flat.loc[:, "resulting_detection"] = 2
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        saved = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id).iloc[0]
        self.assertEqual(saved["classification"], "Critical Quality")
        self.assertEqual(saved["rpn"], 180)
        self.assertEqual(saved["resulting_rpn"], 48)

    def test_flat_placeholder_creates_missing_children_and_action(self) -> None:
        entry_id = self.create_entry()
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        self.assertEqual(len(flat), 1)
        self.assertFalse(flat.iloc[0]["effect_id"])
        self.assertFalse(flat.iloc[0]["cause_id"])
        flat.loc[0, "potential_effects"] = "Bracket separates"
        flat.loc[0, "severity"] = 8
        flat.loc[0, "potential_causes"] = "Wrong setup"
        flat.loc[0, "occurrence"] = 3
        flat.loc[0, "recommended_action"] = "Add setup verification"
        flat.loc[0, "responsibility_target"] = "AQE | 2026-10-01"
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        saved = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved.iloc[0]["effect_id"])
        self.assertTrue(saved.iloc[0]["cause_id"])
        self.assertTrue(saved.iloc[0]["action_id"])
        self.assertEqual(saved.iloc[0]["recommended_action"], "Add setup verification")
        self.assertEqual(saved.iloc[0]["entry_id"], entry_id)

    def test_pfmea_ratings_and_classification_are_restricted(self) -> None:
        entry_id = self.create_entry()
        with self.assertRaisesRegex(ValueError, "whole number from 1 through 10"):
            pfmea_store.save_pfmea_effect_rows(
                self.project_id, self.scenario_id, entry_id,
                pd.DataFrame([{"id": "", "effect_description": "Effect",
                               "severity": 4.5, "sequence": 10}]),
            )
        entries = pfmea_store.pfmea_entries(
            self.project_id, self.scenario_id, self.work_element_id
        )[["id", "potential_failure_mode", "class_code"]]
        entries.loc[0, "class_code"] = "Legacy class"
        with self.assertRaisesRegex(ValueError, "Safety, Critical Quality, or blank"):
            pfmea_store.save_pfmea_entry_rows(
                self.project_id, self.scenario_id, self.work_element_id, entries
            )

    def test_process_step_deletion_is_restricted_until_pfmea_is_removed(self) -> None:
        entry_id = self.create_entry()
        steps = store.project_table(
            "work_elements", self.project_id, "sequence", scenario_id=self.scenario_id
        ).iloc[0:0]
        with self.assertRaisesRegex(ValueError, "linked PFMEA entries"):
            store.replace_work_elements(self.project_id, self.scenario_id, steps)
        pfmea_store.delete_pfmea_records(
            self.project_id, self.scenario_id, "pfmea_entries", [entry_id]
        )
        store.replace_work_elements(self.project_id, self.scenario_id, steps)
        self.assertEqual(len(store.project_table(
            "work_elements", self.project_id, "sequence", scenario_id=self.scenario_id
        )), 0)

    def test_confirmed_multi_entry_delete_cascades_pfmea_only(self) -> None:
        work_element_count = self.conn.execute(
            "SELECT COUNT(*) FROM work_elements"
        ).fetchone()[0]
        assignment_count = self.conn.execute(
            "SELECT COUNT(*) FROM quality_requirement_assignments"
        ).fetchone()[0]
        rows = pd.DataFrame(
            [
                {
                    "id": "", "work_element_id": self.work_element_id,
                    "item_number": "ST-010", "potential_failure_mode": "Loose screw",
                    "potential_effects": "Bracket separates", "potential_causes": "Low torque",
                },
                {
                    "id": "", "work_element_id": self.work_element_id,
                    "item_number": "ST-010", "potential_failure_mode": "Missing screw",
                    "potential_effects": "Bracket absent", "potential_causes": "Part omitted",
                },
            ]
        )
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, rows)
        entry_ids = [
            str(row[0])
            for row in self.conn.execute(
                "SELECT id FROM pfmea_entries ORDER BY potential_failure_mode"
            ).fetchall()
        ]
        deleted = pfmea_store.delete_pfmea_records(
            self.project_id, self.scenario_id, "pfmea_entries", entry_ids
        )
        self.assertEqual(deleted, 2)
        for table in [
            "pfmea_entries", "pfmea_effects", "pfmea_causes",
            "pfmea_prevention_selections", "pfmea_detection_selections",
            "pfmea_risk_rows", "pfmea_actions",
        ]:
            self.assertEqual(
                self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
            )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM work_elements").fetchone()[0],
            work_element_count,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM quality_requirement_assignments"
            ).fetchone()[0],
            assignment_count,
        )

    def test_scenario_clone_reuses_manual_option_with_new_selection_id(self) -> None:
        entry_id = self.create_entry()
        pfmea_store.save_pfmea_cause_rows(
            self.project_id,
            self.scenario_id,
            entry_id,
            pd.DataFrame([{"id": "", "cause_description": "Wrong setup",
                           "occurrence": 2, "detection": None, "sequence": 10}]),
        )
        option_id = pfmea_store.save_pfmea_control_option_rows(
            self.project_id, "Prevention",
            pd.DataFrame([{"id": "", "label": "Use a seated-part fixture", "active": True}]),
        )["created_ids"][0]
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.at[0, "prevention_controls"] = [f"manual:{option_id}"]
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        original_selection_id = str(
            pfmea_store.pfmea_control_selections(self.project_id, self.scenario_id).iloc[0]["id"]
        )
        new_scenario_id = store.clone_planning_scenario(
            self.project_id, self.scenario_id, "Alternate", "B", 55
        )
        cloned = pfmea_store.pfmea_entries(self.project_id, new_scenario_id)
        self.assertEqual(len(cloned), 1)
        self.assertNotEqual(cloned.iloc[0]["id"], entry_id)
        self.assertEqual(cloned.iloc[0]["source_pfmea_entry_id"], entry_id)
        self.assertNotEqual(cloned.iloc[0]["work_element_id"], self.work_element_id)
        self.assertFalse(bool(cloned.iloc[0]["upstream_changes"]))
        cloned_causes = pfmea_store.pfmea_causes(
            self.project_id, new_scenario_id, str(cloned.iloc[0]["id"])
        )
        self.assertEqual(len(cloned_causes), 1)
        cloned_controls = pfmea_store.pfmea_control_selections(self.project_id, new_scenario_id)
        self.assertEqual(len(cloned_controls), 1)
        self.assertNotEqual(str(cloned_controls.iloc[0]["id"]), original_selection_id)
        self.assertEqual(cloned_controls.iloc[0]["source_key"], f"manual:{option_id}")

    def test_legacy_controls_are_discarded_once_with_audit_evidence(self) -> None:
        entry_id = self.create_entry()
        cause_id = pfmea_store.save_pfmea_cause_rows(
            self.project_id,
            self.scenario_id,
            entry_id,
            pd.DataFrame([{"id": "", "cause_description": "Low torque",
                           "occurrence": 3, "detection": None, "sequence": 10}]),
        )["created_ids"][0]
        assignment = dict(self.conn.execute(
            "SELECT * FROM quality_requirement_assignments WHERE id=?",
            (self.assignment_id,),
        ).fetchone())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE pfmea_controls (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    scenario_id TEXT NOT NULL REFERENCES planning_scenarios(id) ON DELETE CASCADE,
                    pfmea_entry_id TEXT NOT NULL REFERENCES pfmea_entries(id) ON DELETE CASCADE,
                    pfmea_cause_id TEXT NOT NULL REFERENCES pfmea_causes(id) ON DELETE CASCADE,
                    quality_assignment_id TEXT REFERENCES quality_requirement_assignments(id)
                        ON DELETE SET NULL,
                    source_assignment_id TEXT NOT NULL,
                    classification TEXT NOT NULL DEFAULT 'Unclassified',
                    requirement_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    unique_identifier TEXT NOT NULL,
                    pass_fail INTEGER NOT NULL DEFAULT 0,
                    target_value REAL,
                    tolerances TEXT NOT NULL DEFAULT '',
                    unit TEXT NOT NULL DEFAULT '',
                    assignment_source_updated_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(pfmea_cause_id, source_assignment_id)
                );
                """
            )
            conn.execute(
                """INSERT INTO pfmea_controls
                   (id, project_id, scenario_id, pfmea_entry_id, pfmea_cause_id,
                    quality_assignment_id, source_assignment_id, classification,
                    requirement_type, description, unique_identifier, pass_fail,
                    target_value, tolerances, unit, assignment_source_updated_at,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'Prevention', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "legacy-control", self.project_id, self.scenario_id, entry_id,
                    cause_id, self.assignment_id, self.assignment_id,
                    assignment["requirement_type"], assignment["description"],
                    assignment["unique_identifier"], assignment["pass_fail"],
                    assignment["target_value"], assignment["tolerances"],
                    assignment["unit"], assignment["source_updated_at"],
                    timestamp, timestamp,
                ),
            )
        with self.assertRaisesRegex(ValueError, "Current editor"):
            pfmea_store.migrate_legacy_pfmea_controls(self.project_id, "")
        result = pfmea_store.migrate_legacy_pfmea_controls(self.project_id, "Nicole")
        self.assertEqual(result["row_count"], 1)
        self.assertFalse(self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pfmea_controls'"
        ).fetchone())
        audit = self.conn.execute(
            "SELECT details FROM audit_log WHERE project_id=? AND table_name='PFMEA'",
            (self.project_id,),
        ).fetchone()[0]
        self.assertIn('"removed_control_count": 1', audit)
        self.assertNotIn("Tighten the bracket screw", audit)
        pfmea_store.migrate_legacy_pfmea_controls(self.project_id, "Nicole")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE project_id=? AND table_name='PFMEA' "
            "AND action='Migrate legacy controls'", (self.project_id,)
        ).fetchone()[0], 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM quality_requirement_assignments WHERE id=?",
                (self.assignment_id,),
            ).fetchone()[0],
            1,
        )

    def test_catalog_uniqueness_deactivation_and_confirmed_cascade(self) -> None:
        entry_id = self.create_entry()
        pfmea_store.save_pfmea_cause_rows(
            self.project_id, self.scenario_id, entry_id,
            pd.DataFrame([{"id": "", "cause_description": "Wrong setup", "sequence": 10}]),
        )
        option_id = pfmea_store.save_pfmea_control_option_rows(
            self.project_id, "Prevention",
            pd.DataFrame([{"id": "", "label": "Fixture interlock", "active": True}]),
        )["created_ids"][0]
        with self.assertRaisesRegex(ValueError, "unique"):
            pfmea_store.save_pfmea_control_option_rows(
                self.project_id, "Prevention",
                pd.DataFrame([
                    {"id": option_id, "label": "Fixture interlock", "active": True},
                    {"id": "", "label": "FIXTURE INTERLOCK", "active": True},
                ]),
            )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.at[0, "prevention_controls"] = [f"manual:{option_id}"]
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        pfmea_store.save_pfmea_control_option_rows(
            self.project_id, "Prevention",
            pd.DataFrame([{"id": option_id, "label": "Fixture interlock", "active": False}]),
        )
        self.assertEqual(len(pfmea_store.pfmea_control_selections(
            self.project_id, self.scenario_id
        )), 1)
        impact = pfmea_store.pfmea_control_option_delete_impact(
            self.project_id, "Prevention", [option_id]
        )
        self.assertEqual(impact["selection_count"], 1)
        pfmea_store.delete_pfmea_control_options(
            self.project_id, "Prevention", [option_id]
        )
        self.assertTrue(pfmea_store.pfmea_control_selections(
            self.project_id, self.scenario_id
        ).empty)
        cause = pfmea_store.pfmea_causes(self.project_id, self.scenario_id, entry_id).iloc[0]
        self.assertTrue(bool(cause["control_source_review_required"]))

    def test_quality_source_can_be_in_both_lists_but_not_duplicated_within_one(self) -> None:
        entry_id = self.create_entry()
        pfmea_store.save_pfmea_cause_rows(
            self.project_id, self.scenario_id, entry_id,
            pd.DataFrame([{"id": "", "cause_description": "Low torque", "sequence": 10}]),
        )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        source = f"quality:{self.assignment_id}"
        flat.at[0, "prevention_controls"] = [source]
        flat.at[0, "detection_controls"] = [source]
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        selections = pfmea_store.pfmea_control_selections(self.project_id, self.scenario_id)
        self.assertEqual(set(selections["control_type"]), {"Prevention", "Detection"})
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.at[0, "prevention_controls"] = [source, source]
        with self.assertRaisesRegex(ValueError, "Duplicate Prevention"):
            pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        self.assertEqual(len(pfmea_store.pfmea_control_selections(
            self.project_id, self.scenario_id
        )), 2)

    def test_control_candidates_are_limited_to_the_pfmea_process_step(self) -> None:
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    description, location, updated_at)
                   VALUES ('other-step', ?, ?, 20, 'ST-020', 'Other work', '', '', ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
        requirement_id = quality_store.save_quality_requirement(
            self.project_id,
            {"requirement_type": "Vision validation", "description": "Other check",
             "unique_identifier": "VS-002", "pass_fail": True,
             "target_value": None, "tolerances": "", "unit": ""},
        )
        other_assignment = quality_store.assign_quality_requirement(
            self.project_id, self.scenario_id, "other-step", requirement_id
        )
        current = pfmea_store.pfmea_control_candidates(
            self.project_id, self.scenario_id, self.work_element_id, "Prevention"
        )
        other = pfmea_store.pfmea_control_candidates(
            self.project_id, self.scenario_id, "other-step", "Prevention"
        )
        self.assertIn(f"quality:{self.assignment_id}", set(current["source_key"]))
        self.assertNotIn(f"quality:{other_assignment}", set(current["source_key"]))
        self.assertIn(f"quality:{other_assignment}", set(other["source_key"]))

    def test_invalid_cross_step_control_selection_rolls_back_atomically(self) -> None:
        entry_id = self.create_entry()
        pfmea_store.save_pfmea_cause_rows(
            self.project_id, self.scenario_id, entry_id,
            pd.DataFrame([{"id": "", "cause_description": "Low torque", "occurrence": 2, "sequence": 10}]),
        )
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    description, location, updated_at)
                   VALUES ('wrong-step', ?, ?, 20, 'ST-020', 'Wrong work', '', '', ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
        requirement_id = quality_store.save_quality_requirement(
            self.project_id,
            {"requirement_type": "Dimension", "description": "Wrong-step check",
             "unique_identifier": "DIM-OTHER", "pass_fail": False,
             "target_value": 1, "tolerances": "+/- 0.1", "unit": "in"},
        )
        wrong_assignment = quality_store.assign_quality_requirement(
            self.project_id, self.scenario_id, "wrong-step", requirement_id
        )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.loc[0, "occurrence"] = 7
        flat.at[0, "prevention_controls"] = [f"quality:{wrong_assignment}"]
        with self.assertRaisesRegex(ValueError, "not linked to this Process Function"):
            pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        reloaded = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id).iloc[0]
        self.assertEqual(reloaded["occurrence"], 2)
        self.assertEqual(reloaded["prevention_controls"], [])

    def test_quality_unlink_cascades_only_dependent_selections_and_flags_cause(self) -> None:
        entry_id = self.create_entry()
        pfmea_store.save_pfmea_cause_rows(
            self.project_id, self.scenario_id, entry_id,
            pd.DataFrame([{"id": "", "cause_description": "Low torque", "detection": 4, "sequence": 10}]),
        )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.at[0, "detection_controls"] = [f"quality:{self.assignment_id}"]
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)
        impact = quality_store.quality_assignment_pfmea_impact(
            self.project_id, self.scenario_id, [self.assignment_id]
        )
        self.assertEqual(impact["detection_count"], 1)
        quality_store.delete_quality_requirement_assignments(
            self.project_id, self.scenario_id, [self.assignment_id]
        )
        self.assertTrue(pfmea_store.pfmea_control_selections(
            self.project_id, self.scenario_id
        ).empty)
        cause = pfmea_store.pfmea_causes(self.project_id, self.scenario_id, entry_id).iloc[0]
        self.assertEqual(cause["detection"], 4)
        self.assertTrue(bool(cause["control_source_review_required"]))
        self.assertTrue(bool(cause["detection_review_required"]))

    def test_draft_blank_cause_preserves_control_order_and_clone_remaps_quality(self) -> None:
        option_ids = pfmea_store.save_pfmea_control_option_rows(
            self.project_id, "Prevention",
            pd.DataFrame([
                {"id": "", "label": "First manual control", "active": True},
                {"id": "", "label": "Second manual control", "active": True},
            ]),
        )["created_ids"]
        ordered = [f"manual:{option_ids[1]}", f"quality:{self.assignment_id}", f"manual:{option_ids[0]}"]
        pfmea_store.save_pfmea_flat_rows(
            self.project_id, self.scenario_id,
            pd.DataFrame([{
                "id": "", "work_element_id": self.work_element_id,
                "potential_failure_mode": "", "potential_causes": "",
                "prevention_controls": ordered,
            }]),
        )
        saved = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id).iloc[0]
        self.assertTrue(saved["cause_id"])
        self.assertEqual(saved["potential_causes"], "")
        self.assertEqual(saved["prevention_controls"], ordered)
        old_selection_ids = set(pfmea_store.pfmea_control_selections(
            self.project_id, self.scenario_id
        )["id"].astype(str))
        cloned_scenario = store.clone_planning_scenario(
            self.project_id, self.scenario_id, "Structured clone", "B", 55
        )
        cloned = pfmea_store.pfmea_control_selections(self.project_id, cloned_scenario)
        self.assertEqual(len(cloned), 3)
        self.assertTrue(old_selection_ids.isdisjoint(set(cloned["id"].astype(str))))
        cloned_quality = cloned.loc[cloned["source_type"].eq("quality_assignment")].iloc[0]
        self.assertNotEqual(cloned_quality["source_key"], f"quality:{self.assignment_id}")
        self.assertEqual(cloned.sort_values("sequence")["source_type"].tolist(), [
            "manual_option", "quality_assignment", "manual_option"
        ])

    def test_multiline_pfmea_text_is_preserved(self) -> None:
        entry_id = pfmea_store.save_pfmea_entry_rows(
            self.project_id,
            self.scenario_id,
            self.work_element_id,
            pd.DataFrame(
                [{"id": "", "potential_failure_mode": "Loose screw\nMissing screw",
                  "class_code": ""}]
            ),
        )["created_ids"][0]
        pfmea_store.save_pfmea_effect_rows(
            self.project_id,
            self.scenario_id,
            entry_id,
            pd.DataFrame(
                [{"id": "", "effect_description": "Noise\nBracket separates",
                  "severity": 8, "sequence": 10}]
            ),
        )
        pfmea_store.save_pfmea_cause_rows(
            self.project_id,
            self.scenario_id,
            entry_id,
            pd.DataFrame(
                [{"id": "", "cause_description": "Tool fault\nWrong setup",
                  "occurrence": 3, "detection": None, "sequence": 10}]
            ),
        )
        flat = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        flat.loc[:, "detection"] = 4
        flat.loc[:, "recommended_action"] = "Add sensor\nAdd error proofing"
        flat.loc[:, "actions_taken"] = "Sensor added\nLogic validated"
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, flat)

        saved = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id).iloc[0]
        self.assertEqual(saved["potential_failure_mode"], "Loose screw\nMissing screw")
        self.assertEqual(saved["potential_effects"], "Noise\nBracket separates")
        self.assertEqual(saved["potential_causes"], "Tool fault\nWrong setup")
        self.assertEqual(saved["prevention_controls"], [])
        self.assertEqual(saved["detection_controls"], [])
        self.assertEqual(saved["recommended_action"], "Add sensor\nAdd error proofing")
        self.assertEqual(saved["actions_taken"], "Sensor added\nLogic validated")

    def test_forced_duplicate_creates_an_independent_graph_and_control_selections(self) -> None:
        manual_option_id = pfmea_store.save_pfmea_control_option_rows(
            self.project_id,
            "Prevention",
            pd.DataFrame([{"id": "", "label": "Fixture interlock", "active": True}]),
        )["created_ids"][0]
        original = pd.DataFrame(
            [{
                "id": "",
                "draft_row_id": "",
                "work_element_id": self.work_element_id,
                "item_number": "ST-010",
                "potential_failure_mode": "Screw is loose",
                "potential_effects": "Bracket separates",
                "severity": 8,
                "potential_causes": "Tool shuts off early",
                "occurrence": 3,
                "detection": 4,
                "prevention_controls": [
                    f"quality:{self.assignment_id}",
                    f"manual:{manual_option_id}",
                ],
                "detection_controls": [f"quality:{self.assignment_id}"],
                "recommended_action": "Add rundown monitor",
                "responsibility_target": "AQE | 2026-10-01",
            }]
        )
        pfmea_store.save_pfmea_flat_rows(self.project_id, self.scenario_id, original)
        saved = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        duplicate = saved.iloc[0].copy()
        duplicate["id"] = ""
        duplicate["draft_row_id"] = "independent-copy"
        for column in ("entry_id", "effect_id", "cause_id", "risk_row_id", "action_id"):
            duplicate[column] = ""
        combined = pd.concat([saved, pd.DataFrame([duplicate])], ignore_index=True, sort=False)

        pfmea_store.save_pfmea_flat_rows(
            self.project_id,
            self.scenario_id,
            combined,
            force_new_draft_ids={"independent-copy"},
        )

        reloaded = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        self.assertEqual(len(reloaded), 2)
        self.assertEqual(reloaded["potential_failure_mode"].tolist(), ["Screw is loose"] * 2)
        self.assertEqual(reloaded["rpn"].tolist(), [96, 96])
        for table in ("pfmea_entries", "pfmea_effects", "pfmea_causes", "pfmea_actions"):
            self.assertEqual(
                self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 2
            )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM pfmea_risk_rows").fetchone()[0], 2
        )
        selections = pfmea_store.pfmea_control_selections(
            self.project_id, self.scenario_id
        )
        self.assertEqual(len(selections), 6)
        self.assertEqual(len(set(selections["id"].astype(str))), 6)
        self.assertEqual(
            set(selections.loc[
                selections["source_type"].eq("quality_assignment"),
                "quality_requirement_assignment_id",
            ].astype(str)),
            {self.assignment_id},
        )
        source_links = self.conn.execute(
            "SELECT source_pfmea_entry_id FROM pfmea_entries ORDER BY created_at, id"
        ).fetchall()
        self.assertTrue(all(row[0] is None for row in source_links))

    def test_unknown_forced_duplicate_id_fails_without_writing(self) -> None:
        rows = pd.DataFrame(
            [{
                "id": "",
                "draft_row_id": "actual-draft",
                "work_element_id": self.work_element_id,
                "item_number": "ST-010",
            }]
        )
        with self.assertRaisesRegex(ValueError, "independent duplication changed"):
            pfmea_store.save_pfmea_flat_rows(
                self.project_id,
                self.scenario_id,
                rows,
                force_new_draft_ids={"missing-draft"},
            )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM pfmea_entries").fetchone()[0], 0
        )


if __name__ == "__main__":
    unittest.main()
