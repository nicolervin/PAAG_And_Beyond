from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from utils import pfmea_store, store


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
        pitch_number: str | None = None,
        pitch_sequence: int = 10,
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
                   VALUES (?, ?, ?, ?, '', 'Active', ?, '["Base"]', 'Pitch', ?)""",
                (
                    pitch_id,
                    self.project_id,
                    area_id,
                    pitch_number or f"01-{key.upper()}",
                    pitch_sequence,
                    timestamp,
                ),
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

    def test_context_sort_uses_physical_hierarchy_and_numeric_stack_order(self) -> None:
        area_id, pitch_id = self.add_area_pitch("stack", "main")
        stack_work_ids = []
        for position in range(1, 11):
            work_id = f"work-stack-{position}"
            stack_work_ids.append(work_id)
            self.add_work(work_id)
            self.add_yamazumi_element(
                f"element-stack-{position}",
                area_id,
                pitch_id,
                position * 10,
                work_id,
            )
        self.linked_work("work-subassembly", "subassembly", "single")
        self.add_work("work-incomplete")

        requested = ["work-incomplete", "work-subassembly", *reversed(stack_work_ids)]
        contexts = store.work_element_op_contexts(
            self.project_id, self.scenario_id, requested
        )
        ordered = sorted(requested, key=lambda work_id: contexts[work_id]["sort_order"])

        self.assertEqual(ordered[:10], stack_work_ids)
        self.assertEqual(ordered[10], "work-subassembly")
        self.assertEqual(ordered[-1], "work-incomplete")
        self.assertTrue(contexts["work-stack-2"]["complete"])
        self.assertLess(
            contexts["work-stack-2"]["sort_order"],
            contexts["work-stack-10"]["sort_order"],
        )
        self.assertTrue(contexts["work-stack-2"]["op_id"].endswith(".2"))
        self.assertTrue(contexts["work-stack-10"]["op_id"].endswith(".10"))
        self.assertFalse(contexts["work-incomplete"]["complete"])

        picker_steps = pfmea_store.pfmea_process_steps(
            self.project_id, self.scenario_id
        )
        self.assertEqual(
            picker_steps["id"].astype(str).tolist(),
            [*stack_work_ids, "work-subassembly", "work-incomplete"],
        )
        self.assertEqual(
            picker_steps.loc[
                picker_steps["id"].eq("work-stack-10"), "op_id"
            ].iloc[0],
            contexts["work-stack-10"]["op_id"],
        )

    def test_pitch_address_components_use_natural_numeric_order(self) -> None:
        expected = [
            ("work-wa1-001", "01-WA1-001"),
            ("work-wa1-010", "01-WA1-010"),
            ("work-wa2-001", "01-WA2-001"),
            ("work-wa10-001", "01-WA10-001"),
        ]
        for position, (work_id, address) in enumerate(reversed(expected), start=1):
            self.add_work(work_id)
            area_id, pitch_id = self.add_area_pitch(
                f"address-{position}",
                "main",
                pitch_number=address,
                pitch_sequence=position * 10,
            )
            self.add_yamazumi_element(
                f"element-{work_id}", area_id, pitch_id, 10, work_id
            )

        requested = [work_id for work_id, _ in reversed(expected)]
        contexts = store.work_element_op_contexts(
            self.project_id, self.scenario_id, requested
        )
        ordered = sorted(requested, key=lambda work_id: contexts[work_id]["sort_order"])

        self.assertEqual(ordered, [work_id for work_id, _ in expected])
        self.assertEqual(
            store.parse_yamazumi_pitch_address("01-WA10-001"),
            {
                "address": "01-WA10-001",
                "parsed": True,
                "subline_number": 1,
                "work_area_letters": "wa",
                "work_area_number": 10,
                "position_number": 1,
            },
        )

    def test_fishbone_traversal_remains_primary_over_parsed_address(self) -> None:
        rows = [
            ("work-main-before", "main-before", "01-WA10-001"),
            ("work-main", "main", "01-WA1-001"),
        ]
        for work_id, section_id, address in rows:
            self.add_work(work_id)
            area_id, pitch_id = self.add_area_pitch(
                work_id, section_id, pitch_number=address
            )
            self.add_yamazumi_element(
                f"element-{work_id}", area_id, pitch_id, 10, work_id
            )

        contexts = store.work_element_op_contexts(
            self.project_id,
            self.scenario_id,
            ["work-main", "work-main-before"],
        )

        self.assertLess(
            contexts["work-main-before"]["sort_order"],
            contexts["work-main"]["sort_order"],
        )

    def test_unparseable_pitch_addresses_follow_parsed_addresses_deterministically(self) -> None:
        records = [
            ("work-legacy-later", "Legacy pitch B", 20),
            ("work-parsed", "01-WA1-001", 999),
            ("work-legacy-first", "Legacy pitch A", 10),
        ]
        for work_id, address, pitch_sequence in records:
            self.add_work(work_id)
            area_id, pitch_id = self.add_area_pitch(
                work_id,
                "main",
                pitch_number=address,
                pitch_sequence=pitch_sequence,
            )
            self.add_yamazumi_element(
                f"element-{work_id}", area_id, pitch_id, 10, work_id
            )

        requested = [work_id for work_id, _, _ in records]
        contexts = store.work_element_op_contexts(
            self.project_id, self.scenario_id, requested
        )
        ordered = sorted(requested, key=lambda work_id: contexts[work_id]["sort_order"])

        self.assertEqual(
            ordered,
            ["work-parsed", "work-legacy-first", "work-legacy-later"],
        )
        self.assertTrue(all(contexts[work_id]["complete"] for work_id in requested))
        self.assertFalse(store.parse_yamazumi_pitch_address("Legacy pitch A")["parsed"])

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
