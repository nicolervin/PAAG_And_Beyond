from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from utils import store


class WorkElementOpIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        connection_patcher = patch.object(store, "connection", self._connection)
        connection_patcher.start()
        self.addCleanup(connection_patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()

        self.project_id = "op-id-project"
        self.scenario_id = "op-id-scenario"
        self.other_scenario_id = "op-id-other-scenario"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, revision, status, takt_time_s, created_at, updated_at)
                   VALUES (?, 'Op ID project', 'A', 'Draft', 60, ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            for scenario_id, name, revision in (
                (self.scenario_id, "Primary", "A"),
                (self.other_scenario_id, "Other", "B"),
            ):
                conn.execute(
                    """INSERT INTO planning_scenarios
                       (id, project_id, name, revision_label, revision_sequence,
                        status, takt_time_s, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 1, 'Working', 60, ?, ?)""",
                    (
                        scenario_id, self.project_id, name, revision,
                        timestamp, timestamp,
                    ),
                )

        self.add_section("main-before", "Main before", "Main spine", None, 5)
        self.add_section("main", "Main", "Main spine", None, 500)
        self.add_section("single", "Single", "Subassembly", "main", 10)
        self.add_section("nested-top", "Nested top", "Subassembly", "main", 20)
        self.add_section("nested-mid", "Nested mid", "Subassembly", "nested-top", 10)
        self.add_section("nested-deep", "Nested deep", "Subassembly", "nested-mid", 10)
        self.add_section("branch-top", "Branch top", "Subassembly", "main", 30)
        self.add_section("branch-one", "Branch one", "Subassembly", "branch-top", 10)
        self.add_section("branch-two", "Branch two", "Subassembly", "branch-top", 20)
        self.add_section("branch-one-a", "Branch one A", "Subassembly", "branch-one", 10)
        self.add_section("branch-one-b", "Branch one B", "Subassembly", "branch-one", 20)

    @contextmanager
    def _connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def add_section(
        self,
        section_id: str,
        name: str,
        section_type: str,
        parent_id: str | None,
        sequence: int,
    ) -> None:
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO assembly_sections
                   (id, project_id, name, section_type, parent_id, sequence,
                    description, active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, '', 1, ?, ?)""",
                (
                    section_id, self.project_id, name, section_type, parent_id,
                    sequence, timestamp, timestamp,
                ),
            )

    def add_area_pitch(
        self,
        key: str,
        section_id: str | None,
        *,
        scenario_id: str | None = None,
    ) -> tuple[str, str]:
        scenario_id = scenario_id or self.scenario_id
        area_id = f"area-{scenario_id}-{key}"
        pitch_id = f"pitch-{scenario_id}-{key}"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (area_id, self.project_id, scenario_id, section_id, key, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status,
                    sequence, model_variants, pitch_type, updated_at)
                   VALUES (?, ?, ?, ?, '', 'Active', 10, '["Base"]', 'Pitch', ?)""",
                (pitch_id, self.project_id, area_id, f"01-{key.upper()}", timestamp),
            )
        return area_id, pitch_id

    def add_work(self, work_id: str, *, scenario_id: str | None = None) -> None:
        scenario_id = scenario_id or self.scenario_id
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, updated_at)
                   VALUES (?, ?, ?, 10, 'stale-address', ?, ?)""",
                (work_id, self.project_id, scenario_id, work_id, timestamp),
            )

    def add_yamazumi_element(
        self,
        element_id: str,
        area_id: str,
        pitch_id: str | None,
        sequence: int,
        process_element_id: str | None,
    ) -> None:
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, description, time_s,
                    sequence, process_element_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (
                    element_id, self.project_id, area_id, pitch_id, element_id,
                    sequence, process_element_id, timestamp,
                ),
            )

    def linked_work(
        self,
        work_id: str,
        key: str,
        section_id: str | None,
        *,
        sequence: int = 10,
    ) -> tuple[str, str, str]:
        self.add_work(work_id)
        area_id, pitch_id = self.add_area_pitch(key, section_id)
        element_id = f"element-{work_id}"
        self.add_yamazumi_element(
            element_id, area_id, pitch_id, sequence, work_id
        )
        return area_id, pitch_id, element_id

    def test_mainline_single_and_nonbranching_nested_op_ids(self) -> None:
        main_area, main_pitch, _ = self.linked_work(
            "work-main", "main", "main", sequence=30
        )
        self.add_yamazumi_element("main-nearest", main_area, main_pitch, 10, None)
        self.linked_work("work-single", "single", "single")
        self.linked_work("work-nested", "nested", "nested-deep")

        values = store.work_element_op_ids(
            self.project_id,
            self.scenario_id,
            ["work-main", "work-single", "work-nested"],
        )

        self.assertEqual(values["work-main"], "M2.01-MAIN.2")
        self.assertEqual(values["work-single"], "M2S1a.01-SINGLE.1")
        self.assertEqual(values["work-nested"], "M2S2c.01-NESTED.1")

    def test_branch_point_uses_compound_designators_recursively(self) -> None:
        self.linked_work("work-b1", "b1", "branch-one")
        self.linked_work("work-b2", "b2", "branch-two")
        self.linked_work("work-c11", "c11", "branch-one-a")
        self.linked_work("work-c12", "c12", "branch-one-b")

        values = store.work_element_op_ids(
            self.project_id,
            self.scenario_id,
            ["work-b1", "work-b2", "work-c11", "work-c12"],
        )

        self.assertEqual(values["work-b1"], "M2S3b1.01-B1.1")
        self.assertEqual(values["work-b2"], "M2S3b2.01-B2.1")
        self.assertEqual(values["work-c11"], "M2S3c11.01-C11.1")
        self.assertEqual(values["work-c12"], "M2S3c12.01-C12.1")

    def test_incomplete_source_states_return_clear_placeholders(self) -> None:
        self.linked_work("work-no-fishbone", "unlinked", None)
        self.add_work("work-no-yamazumi")
        self.add_work("work-no-pitch")
        area_id, _ = self.add_area_pitch("no-pitch", "main")
        self.add_yamazumi_element(
            "element-no-pitch", area_id, None, 10, "work-no-pitch"
        )

        values = store.work_element_op_ids(
            self.project_id,
            self.scenario_id,
            ["work-no-fishbone", "work-no-yamazumi", "work-no-pitch"],
        )

        self.assertEqual(values["work-no-fishbone"], "Fishbone link required")
        self.assertEqual(values["work-no-yamazumi"], "Yamazumi link required")
        self.assertEqual(values["work-no-pitch"], "Yamazumi pitch required")

    def test_scenario_isolation_prevents_cross_scenario_resolution(self) -> None:
        self.add_work("work-primary")
        other_area, other_pitch = self.add_area_pitch(
            "other", "main", scenario_id=self.other_scenario_id
        )
        self.add_yamazumi_element(
            "element-other", other_area, other_pitch, 10, "work-primary"
        )
        self.add_work("work-other", scenario_id=self.other_scenario_id)

        values = store.work_element_op_ids(
            self.project_id, self.scenario_id, ["work-primary"]
        )
        self.assertEqual(values["work-primary"], "Yamazumi link required")
        with self.assertRaisesRegex(ValueError, "another planning scenario"):
            store.work_element_op_ids(
                self.project_id, self.scenario_id, ["work-other"]
            )


if __name__ == "__main__":
    unittest.main()
