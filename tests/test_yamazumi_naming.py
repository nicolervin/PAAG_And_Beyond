from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from utils import store
from utils.yamazumi_naming import (
    format_yamazumi_pitch_address,
    normalize_yamazumi_line_code,
    normalize_yamazumi_section_code,
    parse_yamazumi_pitch_address,
    suggest_yamazumi_section_code,
)


class YamazumiNamingHelperTests(unittest.TestCase):
    def test_normalization_and_formatting(self) -> None:
        self.assertEqual(normalize_yamazumi_line_code(" a1 "), "A1")
        self.assertEqual(normalize_yamazumi_section_code("r&u"), "R&U")
        self.assertEqual(
            format_yamazumi_pitch_address("01", "ml2", 999), "01-ML2-999"
        )
        self.assertEqual(
            format_yamazumi_pitch_address("01", "ml2", 1000), "01-ML2-1000"
        )
        parsed = parse_yamazumi_pitch_address("01-wa1-001")
        self.assertEqual((parsed.line_code, parsed.section_code, parsed.number), ("01", "WA1", 1))

    def test_invalid_codes_are_rejected(self) -> None:
        for value in ("1", "ABC", "A-"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_yamazumi_line_code(value)
        for value in ("WA", "W-A", "WXYZ"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_yamazumi_section_code(value)

    def test_initials_ordinal_and_collision_suggestions(self) -> None:
        self.assertEqual(suggest_yamazumi_section_code("Main line 2"), "ML2")
        self.assertEqual(suggest_yamazumi_section_code("Wheel Assembly"), "WA1")
        self.assertEqual(
            suggest_yamazumi_section_code("Wheel Assembly", {"WA1"}), "WA2"
        )


class YamazumiNamingStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        connection_patcher = patch.object(store, "connection", self._connection)
        connection_patcher.start()
        self.addCleanup(connection_patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()
        self.project_id = "naming-project"
        self.other_project_id = "other-project"
        self.scenario_id = "naming-scenario"
        timestamp = store.now_iso()
        with store.connection() as conn:
            for project_id in (self.project_id, self.other_project_id):
                conn.execute(
                    "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (project_id, project_id, timestamp, timestamp),
                )
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, created_at, updated_at)
                   VALUES (?, ?, 'Primary', 'N-1', ?, ?)""",
                (self.scenario_id, self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO assembly_sections
                   (id, project_id, name, section_type, sequence, active, created_at, updated_at)
                   VALUES ('main-2', ?, 'Main line 2', 'Main spine', 10, 1, ?, ?),
                          ('wheel', ?, 'Wheel Assembly', 'Subassembly', 20, 1, ?, ?)""",
                (
                    self.project_id, timestamp, timestamp,
                    self.project_id, timestamp, timestamp,
                ),
            )
        self.main_area_id = store.upsert_yamazumi_area(
            self.project_id, self.scenario_id, "Main line 2", "main-2"
        )
        self.wheel_area_id = store.upsert_yamazumi_area(
            self.project_id, self.scenario_id, "Wheel Assembly", "wheel"
        )

    @contextmanager
    def _connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def test_project_line_code_update_is_scoped_and_database_checked(self) -> None:
        result = store.update_project_yamazumi_line_code(self.project_id, "a1")
        self.assertEqual(result["new_line_code"], "A1")
        self.assertEqual(
            self.conn.execute(
                "SELECT yamazumi_line_code FROM projects WHERE id=?", (self.other_project_id,)
            ).fetchone()[0],
            "",
        )
        with self.assertRaises(sqlite3.IntegrityError):
            with store.connection() as conn:
                conn.execute(
                    "UPDATE projects SET yamazumi_line_code='BAD' WHERE id=?",
                    (self.project_id,),
                )

    def test_legacy_projects_table_is_upgraded_with_blank_default(self) -> None:
        with store.connection() as conn:
            conn.execute("ALTER TABLE projects DROP COLUMN yamazumi_line_code")
        store.init_db()
        columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(projects)").fetchall()
        }
        self.assertIn("yamazumi_line_code", columns)
        self.assertEqual(
            self.conn.execute(
                "SELECT yamazumi_line_code FROM projects WHERE id=?", (self.project_id,)
            ).fetchone()[0],
            "",
        )

    def test_idempotent_backfill_uses_only_one_consistent_prefix(self) -> None:
        store.add_yamazumi_pitch(self.project_id, self.main_area_id, "01-ML2-001")
        store.add_yamazumi_pitch(self.project_id, self.main_area_id, "01-ML2-002A")
        store.init_db()
        store.init_db()
        self.assertEqual(
            self.conn.execute(
                "SELECT yamazumi_line_code FROM projects WHERE id=?", (self.project_id,)
            ).fetchone()[0],
            "01",
        )

    def test_ambiguous_prefix_is_not_backfilled(self) -> None:
        store.add_yamazumi_pitch(self.project_id, self.main_area_id, "01-ML2-001")
        store.add_yamazumi_pitch(self.project_id, self.wheel_area_id, "02-WA1-001")
        store.init_db()
        self.assertEqual(
            self.conn.execute(
                "SELECT yamazumi_line_code FROM projects WHERE id=?", (self.project_id,)
            ).fetchone()[0],
            "",
        )

    def test_suggestion_reuses_section_code_and_advances_in_scenario(self) -> None:
        store.update_project_yamazumi_line_code(self.project_id, "01")
        store.add_yamazumi_pitch(self.project_id, self.main_area_id, "01-ML2-001")
        store.add_yamazumi_pitch(self.project_id, self.main_area_id, "01-ML2-999")
        suggestion = store.yamazumi_pitch_address_suggestion(
            self.project_id, self.main_area_id
        )
        self.assertEqual(suggestion["section_code"], "ML2")
        self.assertEqual(suggestion["next_number"], 1000)
        self.assertEqual(suggestion["suggested_address"], "01-ML2-1000")

    def test_section_code_is_reused_across_scenarios(self) -> None:
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, created_at, updated_at)
                   VALUES ('second-scenario', ?, 'Second', 'N-2', ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
        store.update_project_yamazumi_line_code(self.project_id, "01")
        store.add_yamazumi_pitch(self.project_id, self.wheel_area_id, "01-WA7-001")
        second_area = store.upsert_yamazumi_area(
            self.project_id, "second-scenario", "Wheel Assembly", "wheel"
        )
        suggestion = store.yamazumi_pitch_address_suggestion(
            self.project_id, second_area
        )
        self.assertEqual(suggestion["section_code"], "WA7")
        self.assertEqual(suggestion["suggested_address"], "01-WA7-001")

    def test_empty_linked_and_unlinked_areas_receive_suggestions(self) -> None:
        store.update_project_yamazumi_line_code(self.project_id, "01")
        wheel = store.yamazumi_pitch_address_suggestion(
            self.project_id, self.wheel_area_id
        )
        self.assertEqual(wheel["section_code"], "WA1")
        unlinked_id = store.upsert_yamazumi_area(
            self.project_id, self.scenario_id, "Rainbows and unicorns"
        )
        unlinked = store.yamazumi_pitch_address_suggestion(
            self.project_id, unlinked_id
        )
        self.assertEqual(unlinked["section_code"], "RA1")

    def test_range_and_line_code_change_commit_or_roll_back_together(self) -> None:
        created, skipped = store.generate_yamazumi_pitch_range(
            self.project_id,
            self.main_area_id,
            "A1-ML2-001",
            "A1-ML2-003",
            project_line_code="A1",
        )
        self.assertEqual((created, skipped), (3, []))
        self.assertEqual(
            self.conn.execute(
                "SELECT yamazumi_line_code FROM projects WHERE id=?", (self.project_id,)
            ).fetchone()[0],
            "A1",
        )
        with self.assertRaises(ValueError):
            store.generate_yamazumi_pitch_range(
                self.project_id,
                self.main_area_id,
                "B2-ML2-005",
                "B2-ML2-004",
                project_line_code="B2",
            )
        self.assertEqual(
            self.conn.execute(
                "SELECT yamazumi_line_code FROM projects WHERE id=?", (self.project_id,)
            ).fetchone()[0],
            "A1",
        )

    def test_range_keeps_three_digits_until_naturally_expanding_to_four(self) -> None:
        created, skipped = store.generate_yamazumi_pitch_range(
            self.project_id,
            self.main_area_id,
            "01-ML2-999",
            "01-ML2-1000",
            project_line_code="01",
        )
        self.assertEqual((created, skipped), (2, []))
        self.assertEqual(
            set(store.yamazumi_pitches(self.project_id, self.main_area_id)["pitch_number"]),
            {"01-ML2-999", "01-ML2-1000"},
        )


if __name__ == "__main__":
    unittest.main()
