from __future__ import annotations

import sqlite3
import unittest
import json
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from utils import pfmea_store, store


class SafetyStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        patcher = patch.object(store, "connection", self._connection)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()
        self.project_id = "safety-project"
        self.scenario_id = "safety-scenario"
        self.other_scenario_id = "other-safety-scenario"
        self.work_ids = ["ctq-work", "safety-work", "both-work", "plain-work"]
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, revision, status, takt_time_s, created_at, updated_at)
                   VALUES (?, 'Safety project', 'A', 'Draft', 60, ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            for scenario_id, name, sequence in (
                (self.scenario_id, "Current", 1),
                (self.other_scenario_id, "Other", 2),
            ):
                conn.execute(
                    """INSERT INTO planning_scenarios
                       (id, project_id, name, revision_label, revision_sequence,
                        status, takt_time_s, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'Working', 60, ?, ?)""",
                    (
                        scenario_id, self.project_id, name, str(sequence), sequence,
                        timestamp, timestamp,
                    ),
                )
            for sequence, work_id in enumerate(self.work_ids, start=1):
                conn.execute(
                    """INSERT INTO work_elements
                       (id, project_id, scenario_id, sequence, station, operation, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        work_id, self.project_id, self.scenario_id, sequence * 10,
                        f"ST-{sequence:03d}", f"Operation {sequence}", timestamp,
                    ),
                )

    @contextmanager
    def _connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def add_pfmea(self, work_id: str, classification: str) -> None:
        pfmea_store.save_pfmea_entry_rows(
            self.project_id,
            self.scenario_id,
            work_id,
            pd.DataFrame([
                {
                    "id": "",
                    "potential_failure_mode": "Failure",
                    "class_code": classification,
                }
            ]),
        )

    def save_safety(self, work_id: str, *, active: bool = True) -> str:
        result = store.save_safety_requirements(
            self.project_id,
            self.scenario_id,
            pd.DataFrame([
                {
                    "id": "",
                    "work_element_id": work_id,
                    "requirement_description": "Guard the pinch point",
                    "active": active,
                }
            ]),
            "Safety tester",
        )
        return str(result["created_ids"][0])

    def test_live_criticality_returns_ctq_safety_both_and_neither(self) -> None:
        self.add_pfmea("ctq-work", "E")
        self.add_pfmea("both-work", "P-")
        self.save_safety("safety-work")
        both_requirement_id = self.save_safety("both-work")

        audit_count_before = int(self.conn.execute(
            "SELECT COUNT(*) FROM audit_log"
        ).fetchone()[0])
        tags = store.work_element_criticality(self.project_id, self.scenario_id)
        self.assertEqual(
            int(self.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]),
            audit_count_before,
        )
        self.assertEqual(tags["ctq-work"], ["CTQ"])
        self.assertEqual(tags["safety-work"], ["Safety"])
        self.assertEqual(tags["both-work"], ["CTQ", "Safety"])
        self.assertEqual(tags["plain-work"], [])

        rows = store.safety_requirements(self.project_id, self.scenario_id)
        rows.loc[rows["id"].astype(str) == both_requirement_id, "active"] = 0
        store.save_safety_requirements(
            self.project_id, self.scenario_id, rows, "Safety tester"
        )
        tags = store.work_element_criticality(self.project_id, self.scenario_id)
        self.assertEqual(tags["both-work"], ["CTQ"])
        with store.connection() as conn:
            conn.execute(
                """UPDATE pfmea_entries SET class_code='S'
                   WHERE project_id=? AND scenario_id=? AND work_element_id='ctq-work'""",
                (self.project_id, self.scenario_id),
            )
        tags = store.work_element_criticality(self.project_id, self.scenario_id)
        self.assertEqual(tags["ctq-work"], [])

    def test_only_confirmed_ctq_equivalent_codes_create_ctq_tag(self) -> None:
        for work_id, classification in zip(
            self.work_ids, ["S", "R", "M", "Q"], strict=True
        ):
            self.add_pfmea(work_id, classification)
        tags = store.work_element_criticality(self.project_id, self.scenario_id)
        self.assertEqual(tags["ctq-work"], [])
        self.assertEqual(tags["safety-work"], [])
        self.assertEqual(tags["both-work"], [])
        self.assertEqual(tags["plain-work"], ["CTQ"])

    def test_safety_save_validates_scenario_and_delete_is_audited(self) -> None:
        requirement_id = self.save_safety("safety-work")
        with self.assertRaisesRegex(ValueError, "active project and scenario"):
            store.save_safety_requirements(
                self.project_id,
                self.other_scenario_id,
                pd.DataFrame([
                    {
                        "id": "",
                        "work_element_id": "safety-work",
                        "requirement_description": "Wrong scenario",
                        "active": True,
                    }
                ]),
                "Safety tester",
            )
        result = store.delete_safety_requirements(
            self.project_id, self.scenario_id, [requirement_id], "Safety tester"
        )
        self.assertEqual(result["row_count"], 1)
        events = self.conn.execute(
            """SELECT action, editor_name FROM audit_log
               WHERE table_name='Safety requirements' ORDER BY created_at"""
        ).fetchall()
        self.assertEqual(events[-1]["action"], "Delete")
        self.assertEqual(events[-1]["editor_name"], "Safety tester")

    def test_scenario_clone_remaps_safety_work_element(self) -> None:
        self.save_safety("safety-work")
        cloned_id = store.clone_planning_scenario(
            self.project_id,
            self.scenario_id,
            "Clone",
            "C",
            60,
            created_by="Safety tester",
        )
        cloned = store.safety_requirements(self.project_id, cloned_id)
        self.assertEqual(len(cloned), 1)
        self.assertNotEqual(str(cloned.iloc[0]["work_element_id"]), "safety-work")
        cloned_work = self.conn.execute(
            "SELECT scenario_id FROM work_elements WHERE id=?",
            (str(cloned.iloc[0]["work_element_id"]),),
        ).fetchone()
        self.assertEqual(cloned_work["scenario_id"], cloned_id)

    def test_process_delete_impact_and_cascade_are_scenario_safe(self) -> None:
        requirement_id = self.save_safety("safety-work")
        impact = store.safety_requirement_delete_impact(
            self.project_id, self.scenario_id, ["safety-work"]
        )
        self.assertEqual(impact, {"requirement_count": 1, "work_element_count": 1})
        with self.assertRaisesRegex(ValueError, "active scenario"):
            store.safety_requirement_delete_impact(
                self.project_id, self.other_scenario_id, ["safety-work"]
            )

        rows = store.project_table(
            "work_elements", self.project_id, "sequence", scenario_id=self.scenario_id
        )
        store.replace_work_elements(
            self.project_id,
            self.scenario_id,
            rows.loc[rows["id"].astype(str) != "safety-work"].copy(),
        )
        self.assertFalse(self.conn.execute(
            "SELECT 1 FROM safety_requirements WHERE id=?", (requirement_id,)
        ).fetchone())
        self.assertTrue(self.conn.execute(
            "SELECT 1 FROM work_elements WHERE id='ctq-work'"
        ).fetchone())

    def test_legacy_flag_migration_is_audited_once_and_drops_storage(self) -> None:
        with store.connection() as conn:
            conn.execute("ALTER TABLE yamazumi_elements ADD COLUMN flags TEXT DEFAULT '[]'")
            conn.execute(
                """CREATE TABLE yamazumi_flag_definitions (
                       id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                       name TEXT NOT NULL, description TEXT DEFAULT '', active INTEGER,
                       system_flag INTEGER, sequence INTEGER, updated_at TEXT NOT NULL)"""
            )
            conn.execute(
                """INSERT INTO yamazumi_flag_definitions
                   (id, project_id, name, active, system_flag, sequence, updated_at)
                   VALUES ('legacy-flag', ?, 'CTQ', 1, 1, 10, ?)""",
                (self.project_id, store.now_iso()),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES ('legacy-area', ?, ?, 'Legacy area', ?)""",
                (self.project_id, self.scenario_id, store.now_iso()),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, description, flags, updated_at)
                   VALUES ('legacy-element', ?, 'legacy-area', 'Legacy work',
                           '["CTQ"]', ?)""",
                (self.project_id, store.now_iso()),
            )
        with self.assertRaisesRegex(ValueError, "Current editor"):
            store.migrate_legacy_yamazumi_flags(self.project_id, "")
        first = store.migrate_legacy_yamazumi_flags(self.project_id, "Safety tester")
        second = store.migrate_legacy_yamazumi_flags(self.project_id, "Safety tester")
        self.assertEqual(first["definition_count"], 1)
        self.assertEqual(first["affected_element_count"], 1)
        self.assertEqual(second["definition_count"], 0)
        self.assertNotIn(
            "flags", [row["name"] for row in self.conn.execute("PRAGMA table_info(yamazumi_elements)")]
        )
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='yamazumi_flag_definitions'"
        ).fetchone())
        events = self.conn.execute(
            "SELECT * FROM audit_log WHERE action='Retire legacy flags'"
        ).fetchall()
        self.assertEqual(len(events), 1)
        details = json.loads(events[0]["details"])
        self.assertEqual(details["definition_count"], 1)
        self.assertEqual(details["affected_element_count"], 1)
        self.assertNotIn("CTQ", events[0]["details"])

    def test_ppe_parsing_and_persistence(self) -> None:
        self.assertEqual(store.parse_ppe(""), [])
        self.assertEqual(store.parse_ppe(None), [])
        self.assertEqual(
            store.parse_ppe(["Safety Glasses", "Cut-Resistant Gloves"]),
            ["Safety Glasses", "Cut-Resistant Gloves"],
        )
        self.assertEqual(
            store.parse_ppe('["Safety Glasses", "Hearing Protection"]'),
            ["Safety Glasses", "Hearing Protection"],
        )
        self.assertEqual(
            store.parse_ppe("Safety Glasses, Cut-Resistant Gloves"),
            ["Safety Glasses", "Cut-Resistant Gloves"],
        )

        # Save with PPE list
        df = pd.DataFrame([{
            "work_element_id": "safety-work",
            "ppe": ["Safety Glasses", "Cut-Resistant Gloves"],
            "requirement_description": "Wear eye and hand protection",
            "active": True,
        }])
        store.save_safety_requirements(self.project_id, self.scenario_id, df, "Safety tester")
        loaded = store.safety_requirements(self.project_id, self.scenario_id)
        saved_row = loaded.loc[loaded["work_element_id"] == "safety-work"].iloc[0]
        self.assertEqual(saved_row["ppe"], ["Safety Glasses", "Cut-Resistant Gloves"])
        self.assertEqual(saved_row["requirement_description"], "Wear eye and hand protection")

        # Save with PPE but blank description -> auto fills description
        df2 = pd.DataFrame([{
            "work_element_id": "both-work",
            "ppe": ["Hearing Protection"],
            "requirement_description": "",
            "active": True,
        }])
        store.save_safety_requirements(self.project_id, self.scenario_id, df2, "Safety tester")
        loaded2 = store.safety_requirements(self.project_id, self.scenario_id)
        both_row = loaded2.loc[loaded2["work_element_id"] == "both-work"].iloc[0]
        self.assertEqual(both_row["ppe"], ["Hearing Protection"])
        self.assertEqual(both_row["requirement_description"], "PPE: Hearing Protection")

    def test_ppe_hierarchy_rollup_and_deduplication(self) -> None:
        # 1. Exact 3-item baseline PPE -> is_standard_baseline = True
        rollup_std = store.resolve_pitch_ppe_rollup([
            ["Cut Level 2 Gloves", "Safety Glasses", "Sturdy Closed Toe and Heel Shoes"],
            ["Cut Level 2 Gloves", "Safety Glasses"],
        ])
        eff_std_names = [it["name"] for it in rollup_std["effective_ppe"]]
        self.assertEqual(
            eff_std_names,
            ["Cut Level 2 Gloves", "Safety Glasses", "Sturdy Closed Toe and Heel Shoes"],
        )
        self.assertTrue(rollup_std["is_standard_baseline"])
        self.assertEqual(rollup_std["overrides"], [])

        # 2. Cut Level 4 overrides Cut Level 2; Safety Toe overrides Sturdy Closed Toe;
        #    Foam Lined Safety Glasses overrides Safety Glasses; specialty items stay alongside.
        rollup_ov = store.resolve_pitch_ppe_rollup([
            ["Cut Level 2 Gloves", "Safety Glasses", "Sturdy Closed Toe and Heel Shoes"],
            ["Cut Level 4 Gloves", "Safety Toe Shoes", "Foam Lined Safety Glasses", "Hearing Protection"],
            ["Chemical Resistant Gloves", "Chemiclal Resistant Galoshes"],
        ])
        eff_ov_names = [it["name"] for it in rollup_ov["effective_ppe"]]
        self.assertIn("Cut Level 4 Gloves", eff_ov_names)
        self.assertNotIn("Cut Level 2 Gloves", eff_ov_names)
        self.assertIn("Safety Toe Shoes", eff_ov_names)
        self.assertNotIn("Sturdy Closed Toe and Heel Shoes", eff_ov_names)
        self.assertIn("Foam Lined Safety Glasses", eff_ov_names)
        self.assertNotIn("Safety Glasses", eff_ov_names)
        self.assertIn("Hearing Protection", eff_ov_names)
        self.assertIn("Chemical Resistant Gloves", eff_ov_names)
        self.assertIn("Chemical Resistant Galoshes", eff_ov_names)
        self.assertFalse(rollup_ov["is_standard_baseline"])
        self.assertEqual(len(rollup_ov["overrides"]), 3)

        # 3. Cut Level 6 overrides Cut Level 1..5, and Hard Hat overrides Bump Cap
        rollup_c6 = store.resolve_pitch_ppe_rollup([
            ["Cut Level 1 Gloves", "Bump Cap"],
            ["Cut Level 2 Gloves"],
            ["Cut Level 3 Gloves", "Hard Hat"],
            ["Cut Level 4 Gloves"],
            ["Cut Level 5 Gloves"],
            ["Cut Level 6 Gloves"],
        ])
        self.assertEqual(
            [it["name"] for it in rollup_c6["effective_ppe"]],
            ["Cut Level 6 Gloves", "Hard Hat"],
        )
        self.assertEqual(
            rollup_c6["overrides"][0]["overridden_items"],
            [
                "Cut Level 1 Gloves",
                "Cut Level 2 Gloves",
                "Cut Level 3 Gloves",
                "Cut Level 4 Gloves",
                "Cut Level 5 Gloves",
            ],
        )
        self.assertEqual(
            rollup_c6["overrides"][1]["overridden_items"],
            ["Bump Cap"],
        )

    def test_jsa_poster_summary_steps_settings_and_rebalancing(self) -> None:
        from utils.ppe_poster import build_jsa_poster_html

        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO assembly_sections
                   (id, project_id, name, section_type, sequence, created_at, updated_at)
                   VALUES ('sec-jsa', ?, 'Main Line 1', 'mainline', 10, ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES ('area-jsa', ?, ?, 'sec-jsa', 'Main Line 1 Area', ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES
                   ('pitch-jsa-1', ?, 'area-jsa', '01-ML1-001', 'Basket Drop', ?),
                   ('pitch-jsa-2', ?, 'area-jsa', '01-ML1-002', 'Marriage Deck', ?)""",
                (self.project_id, timestamp, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id, sequence, description, time_s, updated_at)
                   VALUES
                   ('ye-jsa-1', ?, 'area-jsa', 'pitch-jsa-1', 'ctq-work', 10, 'Enter Work Pitch', 20, ?),
                   ('ye-jsa-2', ?, 'area-jsa', 'pitch-jsa-1', 'safety-work', 20, 'Operate Manipulator', 25, ?)""",
                (self.project_id, timestamp, self.project_id, timestamp),
            )

        # Save JSA steps via save_pitch_jsa_steps
        steps_df = pd.DataFrame([
            {
                "work_element_id": "ctq-work",
                "ppe": ["Cut Level 2 Gloves", "Safety Glasses", "Safety Toe Shoes"],
                "potential_hazards": "Slip, trip and fall hazards",
                "proposed_actions": "Ensure area is free of debris, damaged ergo matting, cords, dropped parts and trash.",
            },
            {
                "work_element_id": "safety-work",
                "ppe": ["Cut Level 5 Gloves", "Hard Hat", "Safety Glasses"],
                "potential_hazards": "Overhead pinch & sharp edge hazard",
                "proposed_actions": "Keep hands on manipulator handles and wear Cut Level 5 gloves + Hard Hat.",
            },
        ])
        step_res = store.save_pitch_jsa_steps(
            self.project_id,
            self.scenario_id,
            steps_df,
            editor_name="EHS JSA Tester",
        )
        self.assertEqual(step_res["row_count"], 2)

        # Save JSA header settings
        store.save_pitch_jsa_poster_settings(
            self.project_id,
            self.scenario_id,
            "pitch-jsa-1",
            job_title_override="01-ML1-001 — Basket Drop / Marriage Deck",
            plant_code="AP1",
            important_notice="Custom JSA Important Notice for Basket Drop.",
            include_pitch_photos=True,
            editor_name="EHS JSA Tester",
        )

        jsa_list = store.pitch_jsa_poster_summary(
            self.project_id, self.scenario_id, "pitch-jsa-1"
        )
        self.assertEqual(len(jsa_list), 1)
        p1_jsa = jsa_list[0]
        self.assertEqual(p1_jsa["job_title"], "01-ML1-001 — Basket Drop / Marriage Deck")
        self.assertEqual(p1_jsa["plant_code"], "AP1")
        self.assertEqual(p1_jsa["important_notice"], "Custom JSA Important Notice for Basket Drop.")
        # Effective PPE should have Cut Level 5 overriding Cut Level 2
        eff_names = [it["name"] for it in p1_jsa["effective_ppe"]]
        self.assertEqual(
            eff_names,
            ["Cut Level 5 Gloves", "Safety Glasses", "Safety Toe Shoes", "Hard Hat"],
        )
        # JSA rows: lead-in "Put on PPE" + 2 work element steps = 3 rows
        self.assertEqual(len(p1_jsa["jsa_rows"]), 3)
        self.assertEqual(p1_jsa["jsa_rows"][0]["job_step"], "Put on PPE")
        self.assertIn("Cut Level 5 Gloves", p1_jsa["jsa_rows"][0]["proposed_actions"])
        self.assertEqual(p1_jsa["jsa_rows"][1]["job_step"], "Enter Work Pitch")
        self.assertEqual(p1_jsa["jsa_rows"][1]["step_number"], 1)
        self.assertEqual(p1_jsa["jsa_rows"][1]["potential_hazards"], "Slip, trip and fall hazards")
        self.assertEqual(p1_jsa["jsa_rows"][2]["job_step"], "Operate Manipulator")
        self.assertEqual(p1_jsa["jsa_rows"][2]["step_number"], 2)

        jsa_html = build_jsa_poster_html(
            job_title=p1_jsa["job_title"],
            plant_code=p1_jsa["plant_code"],
            important_notice=p1_jsa["important_notice"],
            effective_ppe_items=p1_jsa["effective_ppe"],
            jsa_rows=p1_jsa["jsa_rows"],
            pitch_photos=p1_jsa["pitch_photos"],
            include_pitch_photos=p1_jsa["include_pitch_photos"],
            overrides=p1_jsa["overrides"],
        )
        self.assertIn("JOB SAFETY ANALYSIS", jsa_html)
        self.assertIn("FRM-GEA-SAF-085", jsa_html)
        self.assertIn("01-ML1-001 — Basket Drop / Marriage Deck", jsa_html)
        self.assertIn("Slip, trip and fall hazards", jsa_html)
        self.assertIn("Put on PPE", jsa_html)

        # Now rebalance/move 'safety-work' ('ye-jsa-2') to 'pitch-jsa-2'
        with store.connection() as conn:
            conn.execute(
                "UPDATE yamazumi_elements SET pitch_id = 'pitch-jsa-2' WHERE id = 'ye-jsa-2'"
            )
            conn.execute(
                "UPDATE work_elements SET station = '01-ML1-002' WHERE id = 'safety-work'"
            )

        p1_after = store.pitch_jsa_poster_summary(
            self.project_id, self.scenario_id, "pitch-jsa-1"
        )[0]
        p2_after = store.pitch_jsa_poster_summary(
            self.project_id, self.scenario_id, "pitch-jsa-2"
        )[0]
        # Pitch 1 reverts to Cut Level 2 Gloves and only 1 work element step (+ Put on PPE row)
        self.assertEqual(
            [it["name"] for it in p1_after["effective_ppe"]],
            ["Cut Level 2 Gloves", "Safety Glasses", "Safety Toe Shoes"],
        )
        self.assertEqual(len(p1_after["jsa_rows"]), 2)
        # Pitch 2 now has Cut Level 5 Gloves + Hard Hat and the moved work element step
        self.assertEqual(
            [it["name"] for it in p2_after["effective_ppe"]],
            ["Cut Level 5 Gloves", "Safety Glasses", "Hard Hat"],
        )
        self.assertEqual(len(p2_after["jsa_rows"]), 2)
        self.assertEqual(p2_after["jsa_rows"][1]["job_step"], "Operate Manipulator")
        self.assertEqual(p2_after["jsa_rows"][1]["step_number"], 1)
        self.assertEqual(
            p2_after["jsa_rows"][1]["potential_hazards"],
            "Overhead pinch & sharp edge hazard",
        )

    def test_dynamic_pitch_ppe_rebalancing_and_poster_summary(self) -> None:
        from utils.ppe_poster import build_ppe_poster_html

        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO assembly_sections
                   (id, project_id, name, section_type, sequence, created_at, updated_at)
                   VALUES ('sec-1', ?, 'Main Line 1', 'mainline', 10, ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES ('area-1', ?, ?, 'sec-1', 'Main Line 1 Area', ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES
                   ('pitch-1', ?, 'area-1', '01-ML1-001', 'Frame Prep', ?),
                   ('pitch-2', ?, 'area-1', '01-ML1-002', 'Heavy Bracket', ?)""",
                (self.project_id, timestamp, self.project_id, timestamp),
            )
            # Assign ctq-work (Step A) and safety-work (Step B) to pitch-1
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id, sequence, description, time_s, updated_at)
                   VALUES
                   ('ye-1', ?, 'area-1', 'pitch-1', 'ctq-work', 10, 'Operation 1', 20, ?),
                   ('ye-2', ?, 'area-1', 'pitch-1', 'safety-work', 20, 'Operation 2', 25, ?)""",
                (self.project_id, timestamp, self.project_id, timestamp),
            )

        # Step A ('ctq-work') requires Cut Level 2 Gloves + Safety Glasses
        # Step B ('safety-work') requires Cut Level 4 Gloves + Safety Glasses
        ppe_df = pd.DataFrame([
            {
                "work_element_id": "ctq-work",
                "ppe": ["Cut Level 2 Gloves", "Safety Glasses"],
                "requirement_description": "Step A PPE",
                "active": True,
            },
            {
                "work_element_id": "safety-work",
                "ppe": ["Cut Level 4 Gloves", "Safety Glasses"],
                "requirement_description": "Step B PPE",
                "active": True,
            },
        ])
        store.save_safety_requirements(self.project_id, self.scenario_id, ppe_df, "EHS Reviewer")

        # Check Pitch 1 PAAG visual summary: only Cut Level 4 Gloves + Safety Glasses should appear
        p1_sum = store.process_pitch_visual_summary(self.project_id, self.scenario_id, "pitch-1")
        p1_ppe_names = [t["name"] for t in p1_sum["tools"] if t.get("is_ppe")]
        self.assertEqual(p1_ppe_names, ["Cut Level 4 Gloves", "Safety Glasses"])

        # Now move Step B ('safety-work' / 'ye-2') to pitch-2
        with store.connection() as conn:
            conn.execute(
                "UPDATE yamazumi_elements SET pitch_id = 'pitch-2' WHERE id = 'ye-2'"
            )
            conn.execute(
                "UPDATE work_elements SET station = '01-ML1-002' WHERE id = 'safety-work'"
            )

        # Pitch 1 should now automatically revert to Cut Level 2 Gloves + Safety Glasses!
        p1_sum_after = store.process_pitch_visual_summary(self.project_id, self.scenario_id, "pitch-1")
        p1_ppe_after = [t["name"] for t in p1_sum_after["tools"] if t.get("is_ppe")]
        self.assertEqual(p1_ppe_after, ["Cut Level 2 Gloves", "Safety Glasses"])

        # And Pitch 2 now shows Cut Level 4 Gloves + Safety Glasses!
        p2_sum_after = store.process_pitch_visual_summary(self.project_id, self.scenario_id, "pitch-2")
        p2_ppe_after = [t["name"] for t in p2_sum_after["tools"] if t.get("is_ppe")]
        self.assertEqual(p2_ppe_after, ["Cut Level 4 Gloves", "Safety Glasses"])

        # Verify poster header overrides and HTML generation
        store.save_pitch_ppe_poster_overrides(
            self.project_id,
            self.scenario_id,
            "pitch-1",
            job_override="Custom Frame Job",
            workstation_override="WS-101",
            section_override="SEC-A",
            editor_name="EHS Reviewer",
        )
        poster_list = store.pitch_ppe_poster_summary(self.project_id, self.scenario_id, "pitch-1")
        self.assertEqual(len(poster_list), 1)
        p1_poster = poster_list[0]
        self.assertEqual(p1_poster["job_name"], "Custom Frame Job")
        self.assertEqual(p1_poster["workstation"], "WS-101")
        self.assertEqual(p1_poster["section"], "SEC-A")

        poster_html = build_ppe_poster_html(
            job_name=p1_poster["job_name"],
            workstation=p1_poster["workstation"],
            section_name=p1_poster["section"],
            effective_ppe_items=p1_poster["effective_ppe"],
            overrides=p1_poster["overrides"],
        )
        self.assertIn("MINIMUM PPE REQUIREMENTS", poster_html)
        self.assertIn("Custom Frame Job", poster_html)
        self.assertIn("Cut Level 2 Gloves", poster_html)
        self.assertIn("mode-special", poster_html)

    def test_apply_standard_baseline_ppe(self) -> None:
        res = store.apply_standard_baseline_ppe(
            self.project_id,
            self.scenario_id,
            editor_name="EHS Reviewer",
        )
        self.assertEqual(res["row_count"], 4)
        loaded = store.safety_requirements(self.project_id, self.scenario_id)
        self.assertEqual(len(loaded), 4)
        for _, row in loaded.iterrows():
            self.assertEqual(row["ppe"], list(store.STANDARD_BASELINE_PPE))
        # Calling again when all steps already have active PPE is a no-op
        res_again = store.apply_standard_baseline_ppe(
            self.project_id,
            self.scenario_id,
            editor_name="EHS Reviewer",
        )
        self.assertEqual(res_again["row_count"], 0)

    def test_prepopulated_steps_and_visual_aid_style_ppe_tagging(self) -> None:
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO assembly_sections
                   (id, project_id, name, section_type, sequence, created_at, updated_at)
                   VALUES ('sec-tag', ?, 'Main Line 1', 'mainline', 10, ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES ('area-tag', ?, ?, 'sec-tag', 'Main Line 1 Area', ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES ('pitch-tag', ?, 'area-tag', '01-ML1-001', 'Frame Prep', ?)""",
                (self.project_id, timestamp),
            )
            for idx, we_id in enumerate(["ctq-work", "safety-work"], start=1):
                conn.execute(
                    """INSERT INTO yamazumi_elements
                       (id, project_id, area_id, pitch_id, process_element_id, sequence, description, time_s, updated_at)
                       VALUES (?, ?, 'area-tag', 'pitch-tag', ?, ?, ?, 20, ?)""",
                    (f"ye-tag-{idx}", self.project_id, we_id, idx * 10, f"Op {idx}", timestamp),
                )

        # 1. Pre-populated safety_requirements returns all 4 PAAG work elements
        prepop = store.safety_requirements(
            self.project_id,
            self.scenario_id,
            include_unassigned_steps=True,
        )
        self.assertEqual(len(prepop), 4)
        self.assertTrue(all(str(rid).startswith("__unassigned__::") for rid in prepop["id"]))
        self.assertTrue(all(status == "⚠️ Needs PPE" for status in prepop["sync_status"]))
        pitch_map = dict(zip(prepop["work_element_id"], prepop["pitch_id"]))
        self.assertEqual(pitch_map["ctq-work"], "pitch-tag")
        self.assertEqual(pitch_map["safety-work"], "pitch-tag")

        # 2. Editing one pre-populated row saves only that row and ignores untouched placeholders
        edited_df = prepop.copy()
        ctq_idx = edited_df.index[edited_df["work_element_id"] == "ctq-work"][0]
        edited_df.at[ctq_idx, "ppe"] = ["Safety Glasses", "Cut Level 2 Gloves"]
        save_res = store.save_safety_requirements(
            self.project_id,
            self.scenario_id,
            edited_df,
            editor_name="EHS Reviewer",
        )
        self.assertEqual(save_res["row_count"], 1)
        persisted_only = store.safety_requirements(self.project_id, self.scenario_id)
        self.assertEqual(len(persisted_only), 1)
        self.assertEqual(persisted_only.iloc[0]["work_element_id"], "ctq-work")
        self.assertEqual(
            persisted_only.iloc[0]["ppe"],
            ["Safety Glasses", "Cut Level 2 Gloves"],
        )

        # 3. Visual-Aid-style tagging across multiple PAAG elements
        tag_res = store.tag_ppe_to_work_elements(
            self.project_id,
            self.scenario_id,
            ppe_items=["Cut Level 4 Gloves", "Hearing Protection"],
            work_element_ids=["ctq-work", "safety-work"],
            potential_hazards="Sharp sheet metal edges",
            proposed_actions="Wear Cut Level 4 gloves",
            editor_name="EHS Reviewer",
        )
        self.assertEqual(tag_res["row_count"], 2)
        after_tag = store.safety_requirements(self.project_id, self.scenario_id)
        self.assertEqual(len(after_tag), 2)
        by_we = {row["work_element_id"]: row for _, row in after_tag.iterrows()}
        self.assertIn("Cut Level 4 Gloves", by_we["ctq-work"]["ppe"])
        self.assertIn("Hearing Protection", by_we["ctq-work"]["ppe"])
        self.assertIn("Cut Level 4 Gloves", by_we["safety-work"]["ppe"])

        # 4. Update which elements on the pitch have Hearing Protection tagged (keep only safety-work)
        upd_res = store.update_ppe_item_element_tags_on_pitch(
            self.project_id,
            self.scenario_id,
            pitch_work_element_ids=["ctq-work", "safety-work"],
            ppe_name="Hearing Protection",
            tagged_work_element_ids=["safety-work"],
            editor_name="EHS Reviewer",
        )
        self.assertGreaterEqual(upd_res["row_count"], 1)
        after_upd = store.safety_requirements(self.project_id, self.scenario_id)
        by_we_upd = {row["work_element_id"]: row for _, row in after_upd.iterrows()}
        self.assertNotIn("Hearing Protection", by_we_upd["ctq-work"]["ppe"])
        self.assertIn("Hearing Protection", by_we_upd["safety-work"]["ppe"])

    def test_safety_page_apptest_review_and_poster_tabs(self) -> None:
        from streamlit.testing.v1 import AppTest
        from utils import db_core, safety_store

        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO assembly_sections
                   (id, project_id, name, section_type, sequence, created_at, updated_at)
                   VALUES ('sec-app', ?, 'Main Line 1', 'mainline', 10, ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES ('area-app', ?, ?, 'sec-app', 'Main Line 1 Area', ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES ('pitch-app', ?, 'area-app', '01-ML1-001', 'Frame Prep', ?)""",
                (self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id, sequence, description, time_s, updated_at)
                   VALUES ('ye-app', ?, 'area-app', 'pitch-app', 'ctq-work', 10, 'Operation 1', 20, ?)""",
                (self.project_id, timestamp),
            )

        with patch.object(db_core, "connection", self._connection), patch.object(
            safety_store, "connection", self._connection
        ):
            app = AppTest.from_file(
                str(store.ROOT / "app_pages/functional_safety.py"), default_timeout=30
            )
            app.session_state["project_id"] = self.project_id
            app.session_state["scenario_id"] = self.scenario_id
            app.session_state["current_editor"] = "EHS Tester"
            app.run(timeout=30)
            self.assertEqual(list(app.exception), [])

            # Switch to JSA Poster tab and verify it renders without exception
            app.session_state[f"safety_page_tabs_{self.project_id}"] = "JSA Poster"
            app.run(timeout=30)
            self.assertEqual(list(app.exception), [])

            # Switch to PPE Poster tab and verify it renders without exception
            app.session_state[f"safety_page_tabs_{self.project_id}"] = "PPE Poster"
            app.run(timeout=30)
            self.assertEqual(list(app.exception), [])

            # Open Add PPE dialog from the header above the JSA and verify it renders without exception
            app.session_state[f"show_add_ppe_dialog_{self.scenario_id}"] = True
            app.run(timeout=30)
            self.assertEqual(list(app.exception), [])


if __name__ == "__main__":
    unittest.main()
