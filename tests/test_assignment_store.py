"""Unit tests for Section 4 Assignment Store functions in utils/quality_store.py."""

from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

from utils import store
from utils.equipment_store import init_equipment_schema
from utils.quality_store import (
    bulk_assign_quality_requirement,
    project_equipment_assets,
    step_equipment_tooling_status,
)


class AssignmentStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        patcher = patch.object(store, "connection", self._test_connection)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()

        self.project_id = f"test-proj-{uuid4().hex[:8]}"
        self.scenario_id = f"test-scen-{uuid4().hex[:8]}"
        self.editor = "Quality Auditor"

        with store.connection() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (self.project_id, "Assignment Test Project", store.now_iso(), store.now_iso()),
            )
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, created_at, updated_at)
                   VALUES (?, ?, ?, 'Working', ?, ?)""",
                (self.scenario_id, self.project_id, "Assignment Line Plan", store.now_iso(), store.now_iso()),
            )
            init_equipment_schema(conn)

    @contextmanager
    def _test_connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def test_bulk_assign_quality_requirement_success(self) -> None:
        req_id = f"req-{uuid4().hex[:8]}"
        w1 = f"w1-{uuid4().hex[:8]}"
        w2 = f"w2-{uuid4().hex[:8]}"
        w3 = f"w3-{uuid4().hex[:8]}"
        now = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO quality_requirements
                   (id, project_id, requirement_type, description, unique_identifier,
                    pass_fail, target_value, tolerances, unit, created_at, updated_at)
                   VALUES (?, ?, 'Torque', 'Fasten M8 Bolt', 'QR-TRQ-001', 0, '25.0', '±2.0', 'Nm', ?, ?)""",
                (req_id, self.project_id, now, now),
            )
            for idx, wid in enumerate([w1, w2, w3], start=1):
                conn.execute(
                    """INSERT INTO work_elements
                       (id, project_id, scenario_id, station, operation, description, sequence, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        wid,
                        self.project_id,
                        self.scenario_id,
                        f"Pitch 0{idx}",
                        f"Op {idx}0",
                        f"Bolt Step {idx}",
                        idx * 10,
                        now,
                    ),
                )

        result = bulk_assign_quality_requirement(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            quality_requirement_id=req_id,
            work_element_ids=[w1, w2, w3],
            editor_name=self.editor,
        )

        self.assertEqual(result["created_count"], 3)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(len(result["assignment_ids"]), 3)

        with store.connection() as conn:
            rows = conn.execute(
                """SELECT work_element_id, requirement_type, unique_identifier,
                          process_operation_snapshot, station_pitch_snapshot
                   FROM quality_requirement_assignments
                   WHERE project_id=? AND scenario_id=? AND quality_requirement_id=?""",
                (self.project_id, self.scenario_id, req_id),
            ).fetchall()
            self.assertEqual(len(rows), 3)
            row_map = {r["work_element_id"]: dict(r) for r in rows}
            self.assertEqual(row_map[w1]["process_operation_snapshot"], "Op 10")
            self.assertEqual(row_map[w1]["station_pitch_snapshot"], "Pitch 01")
            self.assertEqual(row_map[w2]["process_operation_snapshot"], "Op 20")
            self.assertEqual(row_map[w3]["process_operation_snapshot"], "Op 30")

            audits = conn.execute(
                """SELECT action, row_count, editor_name FROM audit_log
                   WHERE project_id=? AND table_name='Quality requirements'
                     AND action='Bulk Attach to Process steps'""",
                (self.project_id,),
            ).fetchall()
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0]["row_count"], 3)
            self.assertEqual(audits[0]["editor_name"], self.editor)

    def test_bulk_assign_skips_already_assigned_steps(self) -> None:
        req_id = f"req-{uuid4().hex[:8]}"
        w1 = f"w1-{uuid4().hex[:8]}"
        w2 = f"w2-{uuid4().hex[:8]}"
        now = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO quality_requirements
                   (id, project_id, requirement_type, description, unique_identifier, created_at, updated_at)
                   VALUES (?, ?, 'Visual', 'Check Label', 'QR-VIS-001', ?, ?)""",
                (req_id, self.project_id, now, now),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, station, operation, sequence, updated_at)
                   VALUES (?, ?, ?, 'Station A', 'Apply Decal', 10, ?)""",
                (w1, self.project_id, self.scenario_id, now),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, station, operation, sequence, updated_at)
                   VALUES (?, ?, ?, 'Station B', 'Final Check', 20, ?)""",
                (w2, self.project_id, self.scenario_id, now),
            )
            # Already assign w1
            conn.execute(
                """INSERT INTO quality_requirement_assignments
                   (id, project_id, scenario_id, work_element_id, quality_requirement_id,
                    requirement_type, description, unique_identifier, source_updated_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'Visual', 'Check Label', 'QR-VIS-001', ?, ?, ?)""",
                (f"asg-{uuid4().hex[:8]}", self.project_id, self.scenario_id, w1, req_id, now, now, now),
            )

        # Bulk assign both w1 and w2
        result = bulk_assign_quality_requirement(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            quality_requirement_id=req_id,
            work_element_ids=[w1, w2],
            editor_name=self.editor,
        )

        self.assertEqual(result["created_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(len(result["assignment_ids"]), 1)

    def test_bulk_assign_validations(self) -> None:
        # Empty step list
        result = bulk_assign_quality_requirement(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            quality_requirement_id="req-123",
            work_element_ids=[],
        )
        self.assertEqual(result["created_count"], 0)

        # Invalid scenario
        with self.assertRaises(ValueError):
            bulk_assign_quality_requirement(
                project_id=self.project_id,
                scenario_id="non-existent-scenario",
                quality_requirement_id="req-123",
                work_element_ids=["w1"],
            )

        # Invalid requirement
        with self.assertRaises(ValueError):
            bulk_assign_quality_requirement(
                project_id=self.project_id,
                scenario_id=self.scenario_id,
                quality_requirement_id="non-existent-req",
                work_element_ids=["w1"],
            )

    def test_step_equipment_tooling_status_and_project_assets(self) -> None:
        w1 = f"w1-{uuid4().hex[:8]}"
        w2 = f"w2-{uuid4().hex[:8]}"
        now = store.now_iso()

        eq_torque_id = f"eq-trq-{uuid4().hex[:8]}"
        eq_manual_id = f"eq-man-{uuid4().hex[:8]}"
        place_id = f"pl-{uuid4().hex[:8]}"

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, station, operation, sequence, updated_at)
                   VALUES (?, ?, ?, 'Station 1', 'Fasten Nut', 10, ?)""",
                (w1, self.project_id, self.scenario_id, now),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, station, operation, sequence, updated_at)
                   VALUES (?, ?, ?, 'Station 2', 'Fasten Bracket', 20, ?)""",
                (w2, self.project_id, self.scenario_id, now),
            )

            trq_row = conn.execute(
                "SELECT id FROM equipment_types WHERE project_id=? AND label COLLATE NOCASE = 'Torque tool'",
                (self.project_id,),
            ).fetchone()
            type_trq_id = str(trq_row["id"])
            type_fix_id = f"type-fix-{uuid4().hex[:8]}"
            conn.execute(
                """INSERT INTO equipment_types (id, project_id, label, created_at, updated_at)
                   VALUES (?, ?, 'Custom Fixture', ?, ?)""",
                (type_fix_id, self.project_id, now, now),
            )

            # Equipment assets
            conn.execute(
                """INSERT INTO equipment_assets (id, project_id, equipment_type_id, name, model, created_at, updated_at)
                   VALUES (?, ?, ?, 'Atlas Copco Nutrunner', 'EQ-TRQ-01', ?, ?)""",
                (eq_torque_id, self.project_id, type_trq_id, now, now),
            )
            conn.execute(
                """INSERT INTO equipment_assets (id, project_id, equipment_type_id, name, model, created_at, updated_at)
                   VALUES (?, ?, ?, 'Workbench Vise', 'EQ-FIX-01', ?, ?)""",
                (eq_manual_id, self.project_id, type_fix_id, now, now),
            )

            # Place torque tool at Station 1 and link to w1
            conn.execute(
                """INSERT INTO equipment_placements (id, project_id, scenario_id, equipment_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (place_id, self.project_id, self.scenario_id, eq_torque_id, now, now),
            )
            conn.execute(
                """INSERT INTO equipment_process_links (id, project_id, scenario_id, placement_id, work_element_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (f"link-{uuid4().hex[:8]}", self.project_id, self.scenario_id, place_id, w1, now, now),
            )

        status = step_equipment_tooling_status(self.project_id, self.scenario_id, [w1, w2])
        self.assertIn(w1, status)
        self.assertIn(w2, status)
        self.assertEqual(len(status[w1]), 1)
        self.assertTrue(status[w1][0]["is_torque"])
        self.assertEqual(status[w1][0]["asset_name"], "Atlas Copco Nutrunner")
        self.assertEqual(len(status[w2]), 0)

        # Test project_equipment_assets
        all_assets = project_equipment_assets(self.project_id, torque_only=False)
        self.assertEqual(len(all_assets), 2)

        torque_assets = project_equipment_assets(self.project_id, torque_only=True)
        self.assertEqual(len(torque_assets), 1)
        self.assertEqual(torque_assets[0]["id"], eq_torque_id)


if __name__ == "__main__":
    unittest.main()
