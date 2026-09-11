from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from utils import store


class YamazumiPitchFeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        connection_patcher = patch.object(store, "connection", self._test_connection)
        connection_patcher.start()
        self.addCleanup(connection_patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()

        self.project_id = "feed-project"
        self.other_project_id = "feed-other-project"
        self.scenario_id = "feed-scenario"
        self.other_scenario_id = "feed-other-scenario"
        self.area_id = "feed-area"
        self.same_scenario_other_area_id = "feed-same-scenario-other-area"
        self.other_area_id = "feed-other-area"
        self.cross_project_area_id = "feed-cross-project-area"
        timestamp = store.now_iso()
        with store.connection() as conn:
            for project_id, name in (
                (self.project_id, "Feed project"),
                (self.other_project_id, "Other project"),
            ):
                conn.execute(
                    """INSERT INTO projects
                       (id, name, revision, status, takt_time_s, created_at, updated_at)
                       VALUES (?, ?, 'A', 'Draft', 60, ?, ?)""",
                    (project_id, name, timestamp, timestamp),
                )
            for scenario_id, project_id, name, sequence in (
                (self.scenario_id, self.project_id, "Current", 1),
                (self.other_scenario_id, self.project_id, "Other", 2),
                ("cross-project-scenario", self.other_project_id, "Cross project", 1),
            ):
                conn.execute(
                    """INSERT INTO planning_scenarios
                       (id, project_id, name, revision_label, revision_sequence,
                        status, takt_time_s, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'Working', 60, ?, ?)""",
                    (scenario_id, project_id, name, str(sequence), sequence, timestamp, timestamp),
                )
            for area_id, project_id, scenario_id, name in (
                (self.area_id, self.project_id, self.scenario_id, "Main"),
                (
                    self.same_scenario_other_area_id,
                    self.project_id,
                    self.scenario_id,
                    "Same scenario other area",
                ),
                (self.other_area_id, self.project_id, self.other_scenario_id, "Other"),
                (self.cross_project_area_id, self.other_project_id, "cross-project-scenario", "Cross"),
            ):
                conn.execute(
                    """INSERT INTO yamazumi_areas
                       (id, project_id, scenario_id, name, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (area_id, project_id, scenario_id, name, timestamp),
                )

    @contextmanager
    def _test_connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def add_pitch(
        self,
        number: str,
        *,
        pitch_type: str = "Pitch",
        target_id: str | None = None,
        project_id: str | None = None,
        area_id: str | None = None,
    ) -> str:
        return store.add_yamazumi_pitch(
            project_id or self.project_id,
            area_id or self.area_id,
            number,
            f"Name {number}",
            "Active",
            ["Base"],
            pitch_type,
            target_id,
        )

    def values(self, number: str, pitch_type: str, target_id: str | None) -> dict:
        return {
            "pitch_number": number,
            "pitch_name": f"Name {number}",
            "status": "Active",
            "model_variants": ["Base"],
            "pitch_type": pitch_type,
            "feeds_into_pitch_id": target_id,
        }

    def test_target_is_required_for_new_and_edited_feeder_pitches(self) -> None:
        with self.assertRaisesRegex(ValueError, "Feeds into pitch is required"):
            self.add_pitch("SUB-1", pitch_type="Subassembly")
        pitch_id = self.add_pitch("P-1")
        with self.assertRaisesRegex(ValueError, "Feeds into pitch is required"):
            store.update_yamazumi_pitch(
                self.project_id,
                self.area_id,
                pitch_id,
                self.values("P-1", "Kitter", None),
            )
        with self.assertRaisesRegex(ValueError, "Feeds into pitch is required"):
            store.generate_yamazumi_pitch_range(
                self.project_id,
                self.area_id,
                "SUB-10",
                "SUB-12",
                pitch_type="Subassembly",
            )

    def test_bulk_cycle_is_atomic(self) -> None:
        a_id = self.add_pitch("A")
        b_id = self.add_pitch("B")
        rows = store.yamazumi_pitches(self.project_id, self.area_id)
        rows.loc[rows["id"] == a_id, "pitch_type"] = "Subassembly"
        rows.loc[rows["id"] == a_id, "feeds_into_pitch_id"] = b_id
        rows.loc[rows["id"] == b_id, "pitch_type"] = "Kitter"
        rows.loc[rows["id"] == b_id, "feeds_into_pitch_id"] = a_id
        with self.assertRaisesRegex(ValueError, "cycle"):
            store.replace_yamazumi_pitches(
                self.project_id, self.area_id, pd.DataFrame(rows)
            )
        saved = store.yamazumi_pitches(self.project_id, self.area_id)
        self.assertEqual(set(saved["pitch_type"]), {"Pitch"})
        self.assertTrue(saved["feeds_into_pitch_id"].isna().all())

    def test_changing_away_from_feeder_type_clears_target(self) -> None:
        target_id = self.add_pitch("P-1")
        feeder_id = self.add_pitch(
            "SUB-1", pitch_type="Subassembly", target_id=target_id
        )
        store.update_yamazumi_pitch(
            self.project_id,
            self.area_id,
            feeder_id,
            self.values("SUB-1", "Waterspider", target_id),
        )
        row = store.query(
            "SELECT pitch_type, feeds_into_pitch_id FROM yamazumi_pitches WHERE id=?",
            (feeder_id,),
        )[0]
        self.assertEqual(row["pitch_type"], "Waterspider")
        self.assertIsNone(row["feeds_into_pitch_id"])

    def test_target_must_exist_in_same_area_and_cannot_be_self(self) -> None:
        source_id = self.add_pitch("P-1")
        valid_target_id = self.add_pitch("P-2")
        store.update_yamazumi_pitch(
            self.project_id,
            self.area_id,
            source_id,
            self.values("P-1", "Subassembly", valid_target_id),
        )
        same_scenario_other_area_target = self.add_pitch(
            "S-1",
            project_id=self.project_id,
            area_id=self.same_scenario_other_area_id,
        )
        other_scenario_target = self.add_pitch(
            "O-1", project_id=self.project_id, area_id=self.other_area_id
        )
        cross_project_target = self.add_pitch(
            "X-1", project_id=self.other_project_id, area_id=self.cross_project_area_id
        )
        for target_id in (
            same_scenario_other_area_target,
            other_scenario_target,
            cross_project_target,
        ):
            with self.assertRaisesRegex(ValueError, "same Yamazumi area"):
                store.update_yamazumi_pitch(
                    self.project_id,
                    self.area_id,
                    source_id,
                    self.values("P-1", "Subassembly", target_id),
                )
        with self.assertRaisesRegex(ValueError, "cannot feed into itself"):
            store.update_yamazumi_pitch(
                self.project_id,
                self.area_id,
                source_id,
                self.values("P-1", "Subassembly", source_id),
            )
        with self.assertRaisesRegex(ValueError, "no longer exists"):
            store.update_yamazumi_pitch(
                self.project_id,
                self.area_id,
                source_id,
                self.values("P-1", "Subassembly", "stale-pitch"),
            )

    def test_direct_cycle_is_rejected_and_names_each_pitch(self) -> None:
        a_id = self.add_pitch("A")
        b_id = self.add_pitch("B")
        store.update_yamazumi_pitch(
            self.project_id, self.area_id, a_id,
            self.values("A", "Subassembly", b_id),
        )
        with self.assertRaises(ValueError) as caught:
            store.update_yamazumi_pitch(
                self.project_id, self.area_id, b_id,
                self.values("B", "Kitter", a_id),
            )
        message = str(caught.exception)
        self.assertIn("cycle", message)
        self.assertIn("A — Name A", message)
        self.assertIn("B — Name B", message)

    def test_indirect_cycle_is_rejected_and_names_every_pitch(self) -> None:
        a_id = self.add_pitch("A")
        b_id = self.add_pitch("B")
        c_id = self.add_pitch("C")
        store.update_yamazumi_pitch(
            self.project_id, self.area_id, a_id,
            self.values("A", "Subassembly", b_id),
        )
        store.update_yamazumi_pitch(
            self.project_id, self.area_id, b_id,
            self.values("B", "Kitter", c_id),
        )
        with self.assertRaises(ValueError) as caught:
            store.update_yamazumi_pitch(
                self.project_id, self.area_id, c_id,
                self.values("C", "Subassembly", a_id),
            )
        message = str(caught.exception)
        for label in ("A — Name A", "B — Name B", "C — Name C"):
            self.assertIn(label, message)

    def test_clone_remaps_feed_target_to_cloned_pitch(self) -> None:
        target_id = self.add_pitch("P-1")
        feeder_id = self.add_pitch(
            "SUB-1", pitch_type="Subassembly", target_id=target_id
        )
        clone_id = store.clone_planning_scenario(
            self.project_id, self.scenario_id, "Clone", "C", 60
        )
        cloned = store.yamazumi_pitches_for_scenario(self.project_id, clone_id)
        cloned_target = cloned.loc[cloned["pitch_number"] == "P-1"].iloc[0]
        cloned_feeder = cloned.loc[cloned["pitch_number"] == "SUB-1"].iloc[0]
        self.assertNotEqual(str(cloned_target["id"]), target_id)
        self.assertNotEqual(str(cloned_feeder["id"]), feeder_id)
        self.assertEqual(
            str(cloned_feeder["feeds_into_pitch_id"]), str(cloned_target["id"])
        )

    def test_target_deletion_is_blocked_until_feeder_is_repointed(self) -> None:
        target_id = self.add_pitch("P-1")
        replacement_id = self.add_pitch("P-2")
        feeder_id = self.add_pitch(
            "SUB-1", pitch_type="Subassembly", target_id=target_id
        )
        with self.assertRaisesRegex(ValueError, "Re-point"):
            store.delete_yamazumi_pitch(self.project_id, self.area_id, target_id)
        store.update_yamazumi_pitch(
            self.project_id,
            self.area_id,
            feeder_id,
            self.values("SUB-1", "Subassembly", replacement_id),
        )
        self.assertEqual(
            store.delete_yamazumi_pitch(self.project_id, self.area_id, target_id), 0
        )

    def test_compatibility_null_status_appears_and_disappears(self) -> None:
        self.assertEqual(
            store.yamazumi_pitch_feed_target_status("Subassembly", None),
            "Feed target required",
        )
        self.assertEqual(
            store.yamazumi_pitch_feed_target_status("Kitter", "target"), ""
        )
        self.assertEqual(
            store.yamazumi_pitch_feed_target_status("Pitch", None), ""
        )

    def test_clear_area_removes_complete_feed_graph(self) -> None:
        target_id = self.add_pitch("P-1")
        self.add_pitch("SUB-1", pitch_type="Subassembly", target_id=target_id)
        counts = store.clear_yamazumi_data(
            self.project_id, self.scenario_id, self.area_id
        )
        self.assertEqual(counts["pitches"], 2)
        self.assertEqual(
            store.query("SELECT COUNT(*) AS count FROM yamazumi_pitches WHERE area_id=?", (self.area_id,))[0]["count"],
            0,
        )

    def test_import_blocks_compatibility_null_feeder_edit_atomically(self) -> None:
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status,
                    sequence, model_variants, pitch_type, feeds_into_pitch_id, updated_at)
                   VALUES ('legacy-feeder', ?, ?, 'SUB-LEGACY', 'Legacy', 'Active',
                           20, '["Base"]', 'Subassembly', NULL, ?)""",
                (self.project_id, self.area_id, timestamp),
            )
        rows = pd.DataFrame(
            [
                {
                    "Sub-Line": "Main",
                    "Pitch_number": "P-NEW",
                    "Pitch_status": "Active",
                    "Pitch_name": "New",
                    "Pitch_Takt_time": 60,
                    "Model_variant": "Base",
                    "Work_Type": "Cycle",
                    "Work_Description": "New work",
                    "Work_Time_to_complete": 1,
                    "Work_region": "None",
                },
                {
                    "Sub-Line": "Main",
                    "Pitch_number": "SUB-LEGACY",
                    "Pitch_status": "Active",
                    "Pitch_name": "Edited by import",
                    "Pitch_Takt_time": 60,
                    "Model_variant": "Base",
                    "Work_Type": "Cycle",
                    "Work_Description": "Legacy work",
                    "Work_Time_to_complete": 1,
                    "Work_region": "None",
                },
            ]
        )
        with self.assertRaisesRegex(ValueError, "Feeds into pitch is required"):
            store.import_yamazumi_rows(
                self.project_id, self.scenario_id, rows, {}
            )
        self.assertEqual(
            store.query(
                "SELECT COUNT(*) AS count FROM yamazumi_pitches WHERE pitch_number='P-NEW'"
            )[0]["count"],
            0,
        )
        self.assertEqual(
            store.query(
                "SELECT pitch_name FROM yamazumi_pitches WHERE id='legacy-feeder'"
            )[0]["pitch_name"],
            "Legacy",
        )


class YamazumiPitchFeedMigrationTests(unittest.TestCase):
    def test_migration_adds_nullable_column_without_backfilling_existing_rows(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF")

        @contextmanager
        def test_connection():
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        with patch.object(store, "connection", test_connection):
            store.init_db()
            conn.execute("DROP TABLE yamazumi_pitches")
            conn.execute(
                """CREATE TABLE yamazumi_pitches (
                       id TEXT PRIMARY KEY, project_id TEXT NOT NULL, area_id TEXT NOT NULL,
                       pitch_number TEXT NOT NULL, pitch_name TEXT DEFAULT '',
                       status TEXT NOT NULL DEFAULT 'Active', sequence INTEGER NOT NULL DEFAULT 10,
                       model_variants TEXT NOT NULL DEFAULT '["Base"]',
                       pitch_type TEXT NOT NULL DEFAULT 'Pitch', updated_at TEXT NOT NULL
                   )"""
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_type, updated_at)
                   VALUES ('legacy-sub', 'project', 'area', 'SUB-1', 'Subassembly', ?)""",
                (store.now_iso(),),
            )
            store.init_db()
            columns = {
                str(row["name"]): row
                for row in conn.execute("PRAGMA table_info(yamazumi_pitches)")
            }
            migrated = conn.execute(
                "SELECT feeds_into_pitch_id FROM yamazumi_pitches WHERE id='legacy-sub'"
            ).fetchone()
        conn.close()
        self.assertIn("feeds_into_pitch_id", columns)
        self.assertEqual(int(columns["feeds_into_pitch_id"]["notnull"]), 0)
        self.assertIsNone(migrated["feeds_into_pitch_id"])


if __name__ == "__main__":
    unittest.main()
