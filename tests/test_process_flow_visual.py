from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

from utils import quality_store, store
from utils.process_flow_visual import process_flow_projection


class ProcessFlowVisualTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        patcher = patch.object(store, "connection", self._connection)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()

        self.project_id = f"proj-{uuid4()}"
        self.scenario_id = f"scen-{uuid4()}"
        timestamp = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, revision, status, takt_time_s, created_at, updated_at)
                   VALUES (?, 'PFD Project', 'A', 'Draft', 50.0, ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, status,
                    takt_time_s, created_at, updated_at)
                   VALUES (?, ?, 'Base Plan', 'A', 1, 'Working', 50.0, ?, ?)""",
                (self.scenario_id, self.project_id, timestamp, timestamp),
            )

    @contextmanager
    def _connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def test_empty_scenario_projection(self) -> None:
        proj = process_flow_projection(self.project_id, self.scenario_id)
        self.assertEqual(proj["metrics"]["total_operations"], 0)
        self.assertEqual(proj["sequence_edges"], [])
        self.assertEqual(proj["feed_edges"], [])

    def test_main_line_ordering_and_sequence_edges(self) -> None:
        area_id = f"area-{uuid4()}"
        pitch1_id = f"pitch-1-{uuid4()}"
        pitch2_id = f"pitch-2-{uuid4()}"
        timestamp = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES (?, ?, ?, 'Main Area', ?)""",
                (area_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, pitch_type, sequence, updated_at)
                   VALUES (?, ?, ?, 'P10', 'Station 10', 'Normal', 10, ?)""",
                (pitch1_id, self.project_id, area_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, pitch_type, sequence, updated_at)
                   VALUES (?, ?, ?, 'P20', 'Station 20', 'Normal', 20, ?)""",
                (pitch2_id, self.project_id, area_id, timestamp),
            )

            # Pitch 1 has Op 10 and Op 20
            for op_idx, p_id in [(1, pitch1_id), (2, pitch1_id), (3, pitch2_id)]:
                w_id = f"work-{op_idx}"
                conn.execute(
                    """INSERT INTO work_elements
                       (id, project_id, scenario_id, sequence, station, operation,
                        description, cycle_time_s, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 20.0, ?)""",
                    (w_id, self.project_id, self.scenario_id, op_idx * 10, f"ST-{op_idx}", f"Op-{op_idx}", f"Desc-{op_idx}", timestamp),
                )
                conn.execute(
                    """INSERT INTO yamazumi_elements
                       (id, project_id, area_id, pitch_id, process_element_id,
                        description, time_s, sequence, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 20.0, ?, ?)""",
                    (f"yam-{op_idx}", self.project_id, area_id, p_id, w_id, f"Op-{op_idx}", op_idx * 10, timestamp),
                )

        proj = process_flow_projection(self.project_id, self.scenario_id, shape_mode="uniform")
        self.assertEqual(proj["metrics"]["total_operations"], 3)
        self.assertEqual(proj["metrics"]["total_pitches"], 2)

        # Check sequence edges
        edges = proj["sequence_edges"]
        self.assertEqual(len(edges), 2)
        # First edge is intra-pitch between Op 1 and Op 2
        self.assertEqual(edges[0]["kind"], "intra_pitch")
        self.assertEqual(edges[0]["from"], "op:work-1")
        self.assertEqual(edges[0]["to"], "op:work-2")
        # Second edge is inter-pitch from Pitch 1 last op (Op 2) to Pitch 2 first op (Op 3)
        self.assertEqual(edges[1]["kind"], "inter_pitch")
        self.assertEqual(edges[1]["from"], "op:work-2")
        self.assertEqual(edges[1]["to"], "op:work-3")

    def test_feeder_pitch_injection(self) -> None:
        area_id = f"area-{uuid4()}"
        main_pitch_id = f"main-pitch-{uuid4()}"
        feeder_pitch_id = f"sub-pitch-{uuid4()}"
        timestamp = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES (?, ?, ?, 'Assembly Area', ?)""",
                (area_id, self.project_id, self.scenario_id, timestamp),
            )
            # Main pitch
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, pitch_type, sequence, updated_at)
                   VALUES (?, ?, ?, 'P100', 'Main Line Pitch', 'Normal', 10, ?)""",
                (main_pitch_id, self.project_id, area_id, timestamp),
            )
            # Feeder pitch feeding into main_pitch_id
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, pitch_type, sequence, feeds_into_pitch_id, updated_at)
                   VALUES (?, ?, ?, 'SUB-01', 'Subassembly Feed', 'Subassembly', 5, ?, ?)""",
                (feeder_pitch_id, self.project_id, area_id, main_pitch_id, timestamp),
            )

            # Feeder operation with output assembly
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    description, cycle_time_s, output_assembly_number, output_assembly_name, updated_at)
                   VALUES ('w-sub-1', ?, ?, 10, 'SUB-01', 'Assemble Valve', 'Valve', 15.0, 'ASM-777', 'Valve Module', ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id,
                    description, time_s, sequence, updated_at)
                   VALUES ('y-sub-1', ?, ?, ?, 'w-sub-1', 'Assemble Valve', 15.0, 10, ?)""",
                (self.project_id, area_id, feeder_pitch_id, timestamp),
            )

            # Main operation receiving injection
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    description, cycle_time_s, updated_at)
                   VALUES ('w-main-1', ?, ?, 20, 'P100', 'Install Valve', 'Mount Valve', 25.0, ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id,
                    description, time_s, sequence, updated_at)
                   VALUES ('y-main-1', ?, ?, ?, 'w-main-1', 'Install Valve', 25.0, 20, ?)""",
                (self.project_id, area_id, main_pitch_id, timestamp),
            )

        proj = process_flow_projection(self.project_id, self.scenario_id, shape_mode="functional")

        feeder_p = next(p for p in proj["pitches"] if p["id"] == feeder_pitch_id)
        self.assertTrue(feeder_p["is_feeder"])

        main_op = next(o for o in proj["operations"] if o["id"] == "w-main-1")
        sub_op = next(o for o in proj["operations"] if o["id"] == "w-sub-1")

        self.assertTrue(sub_op["is_feeder_output"])
        self.assertTrue(main_op["is_injection_target"])

        # Check feeder injection edge
        self.assertEqual(len(proj["feed_edges"]), 1)
        feed_edge = proj["feed_edges"][0]
        self.assertEqual(feed_edge["from"], "op:w-sub-1")
        self.assertEqual(feed_edge["to"], "op:w-main-1")
        self.assertIn("ASM-777", feed_edge["label"])
        self.assertIn("Valve Module", feed_edge["label"])

        # In functional mode, feeder output and injection target get rounded shape
        self.assertEqual(sub_op["shape"], "rounded")
        self.assertEqual(main_op["shape"], "rounded")

    def test_shape_modes_and_quality_diamond(self) -> None:
        area_id = f"area-{uuid4()}"
        pitch_id = f"pitch-{uuid4()}"
        timestamp = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES (?, ?, ?, 'Area', ?)""",
                (area_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, pitch_type, sequence, updated_at)
                   VALUES (?, ?, ?, 'P1', 'Pitch 1', 'Normal', 10, ?)""",
                (pitch_id, self.project_id, area_id, timestamp),
            )

            # Op 1: Normal operation
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, cycle_time_s, updated_at)
                   VALUES ('w-norm', ?, ?, 10, 'P1', 'Normal Op', 10.0, ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id, description, sequence, updated_at)
                   VALUES ('y-norm', ?, ?, ?, 'w-norm', 'Normal Op', 10, ?)""",
                (self.project_id, area_id, pitch_id, timestamp),
            )

            # Op 2: Quality critical operation (linked quality requirement)
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, quality_requirement, cycle_time_s, updated_at)
                   VALUES ('w-crit', ?, ?, 20, 'P1', 'Crit Op', 'Check gap', 15.0, ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id, description, sequence, updated_at)
                   VALUES ('y-crit', ?, ?, ?, 'w-crit', 'Crit Op', 20, ?)""",
                (self.project_id, area_id, pitch_id, timestamp),
            )

        # In functional shape mode
        proj_func = process_flow_projection(self.project_id, self.scenario_id, shape_mode="functional")
        norm_op = next(o for o in proj_func["operations"] if o["id"] == "w-norm")
        crit_op = next(o for o in proj_func["operations"] if o["id"] == "w-crit")
        self.assertEqual(norm_op["shape"], "square")
        self.assertEqual(crit_op["shape"], "diamond")

        # In uniform shape mode
        proj_uni = process_flow_projection(self.project_id, self.scenario_id, shape_mode="uniform")
        norm_op_uni = next(o for o in proj_uni["operations"] if o["id"] == "w-norm")
        crit_op_uni = next(o for o in proj_uni["operations"] if o["id"] == "w-crit")
        self.assertEqual(norm_op_uni["shape"], "square")
        self.assertEqual(crit_op_uni["shape"], "square")

    def test_takt_bottleneck_detection(self) -> None:
        area_id = f"area-{uuid4()}"
        pitch_id = f"pitch-{uuid4()}"
        timestamp = store.now_iso()

        # Takt time is 50.0s. Let's create an operation with cycle time 65.0s
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, name, updated_at)
                   VALUES (?, ?, ?, 'Area', ?)""",
                (area_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, pitch_type, sequence, updated_at)
                   VALUES (?, ?, ?, 'P-OVER', 'Heavy Pitch', 'Normal', 10, ?)""",
                (pitch_id, self.project_id, area_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, cycle_time_s, updated_at)
                   VALUES ('w-heavy', ?, ?, 10, 'P-OVER', 'Heavy Op', 65.0, ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id, description, time_s, sequence, updated_at)
                   VALUES ('y-heavy', ?, ?, ?, 'w-heavy', 'Heavy Op', 65.0, 10, ?)""",
                (self.project_id, area_id, pitch_id, timestamp),
            )

        proj = process_flow_projection(self.project_id, self.scenario_id)
        pitch = proj["pitches"][0]
        self.assertTrue(pitch["over_takt"])
        self.assertEqual(proj["metrics"]["bottlenecks"], 1)
        self.assertEqual(proj["metrics"]["total_work_time_s"], 65.0)

    def test_unassigned_work_element(self) -> None:
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, cycle_time_s, updated_at)
                   VALUES ('w-unassigned', ?, ?, 10, 'ST-NEW', 'Unlinked Task', 12.0, ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )

        proj = process_flow_projection(self.project_id, self.scenario_id)
        self.assertEqual(proj["metrics"]["total_operations"], 1)
        op = proj["operations"][0]
        self.assertEqual(op["pitch_id"], "__unassigned__")
        unassigned_pitch = next(p for p in proj["pitches"] if p["id"] == "__unassigned__")
        self.assertEqual(len(unassigned_pitch["operations"]), 1)
        self.assertEqual(unassigned_pitch["number"], "Unassigned")


if __name__ == "__main__":
    unittest.main()

