"""Unit tests for utils/traceability_store.py."""

from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

from utils import store
from utils.control_plan_store import init_control_plan_schema
from utils.equipment_store import init_equipment_schema
from utils.pfmea_store import init_pfmea_schema
from utils.quality_store import init_quality_schema
from utils.traceability_store import (
    align_control_plan_specification,
    cross_functional_traceability_matrix,
    quick_link_step_equipment,
)


class TraceabilityStoreTests(unittest.TestCase):
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
                (self.project_id, "Traceability Test Project", store.now_iso(), store.now_iso()),
            )
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, created_at, updated_at)
                   VALUES (?, ?, ?, 'Working', ?, ?)""",
                (self.scenario_id, self.project_id, "Production Line Plan", store.now_iso(), store.now_iso()),
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

    def test_empty_scenario_returns_zero_metrics(self) -> None:
        result = cross_functional_traceability_matrix(self.project_id, self.scenario_id)
        self.assertEqual(len(result["rows"]), 0)
        self.assertEqual(result["summary"]["total_steps"], 0)
        self.assertEqual(result["summary"]["steps_with_quality"], 0)
        self.assertEqual(result["summary"]["fully_protected_pct"], 100.0)

    def test_uncovered_standard_assembly_step(self) -> None:
        work_id = f"work-{uuid4().hex[:8]}"
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, station, operation, description, sequence, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (work_id, self.project_id, self.scenario_id, "Station 1", "Install Bracket", "Standard assembly", 10, store.now_iso()),
            )

        result = cross_functional_traceability_matrix(self.project_id, self.scenario_id)
        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        self.assertEqual(row["status"], "UNCOVERED")
        self.assertEqual(result["summary"]["total_steps"], 1)
        self.assertEqual(result["summary"]["steps_with_quality"], 0)
        self.assertEqual(result["summary"]["uncovered_steps"], 1)

    def test_critical_coverage_gap_when_pfmea_or_cp_missing(self) -> None:
        work_id = f"work-{uuid4().hex[:8]}"
        req_id = f"req-{uuid4().hex[:8]}"
        assign_id = f"assign-{uuid4().hex[:8]}"
        now = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, station, operation, sequence, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (work_id, self.project_id, self.scenario_id, "Station 2", "Weld Seam", 10, now),
            )
            conn.execute(
                """INSERT INTO quality_requirements
                   (id, project_id, requirement_type, description, unique_identifier, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (req_id, self.project_id, "Visual", "Weld Penetration", "WELD-001", now, now),
            )
            conn.execute(
                """INSERT INTO quality_requirement_assignments
                   (id, project_id, scenario_id, work_element_id, quality_requirement_id,
                    requirement_type, description, unique_identifier, target_value, tolerances, unit,
                    source_updated_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (assign_id, self.project_id, self.scenario_id, work_id, req_id,
                 "Visual", "Weld Penetration", "WELD-001", 5.0, "+-0.5", "mm",
                 now, now, now),
            )

        result = cross_functional_traceability_matrix(self.project_id, self.scenario_id)
        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        self.assertEqual(row["status"], "CRITICAL_GAP")
        self.assertIn("Coverage Gap", row["discrepancy_summary"])
        self.assertEqual(result["summary"]["critical_gap_steps"], 1)

    def test_tooling_gap_is_warning_severity(self) -> None:
        """User Directive #2: Missing equipment/tooling for a Torque requirement must be flagged as a Warning (Yellow)."""
        work_id = f"work-{uuid4().hex[:8]}"
        req_id = f"req-{uuid4().hex[:8]}"
        assign_id = f"assign-{uuid4().hex[:8]}"
        pfmea_id = f"pfmea-{uuid4().hex[:8]}"
        cause_id = f"cause-{uuid4().hex[:8]}"
        cp_id = f"cp-{uuid4().hex[:8]}"
        now = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, station, operation, sequence, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (work_id, self.project_id, self.scenario_id, "Station 3", "Torque Bolts", 10, now),
            )
            conn.execute(
                """INSERT INTO quality_requirements
                   (id, project_id, requirement_type, description, unique_identifier, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (req_id, self.project_id, "Torque", "Fastener Tightening", "TRQ-001", now, now),
            )
            conn.execute(
                """INSERT INTO quality_requirement_assignments
                   (id, project_id, scenario_id, work_element_id, quality_requirement_id,
                    requirement_type, description, unique_identifier, target_value, tolerances, unit,
                    source_updated_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (assign_id, self.project_id, self.scenario_id, work_id, req_id,
                 "Torque", "Fastener Tightening", "TRQ-001", 35.0, "+-2", "Nm",
                 now, now, now),
            )
            # Create PFMEA entry with class code
            conn.execute(
                """INSERT INTO pfmea_entries
                   (id, project_id, scenario_id, work_element_id, potential_failure_mode, class_code,
                    process_sequence_snapshot, process_source_hash, quality_source_hash, source_reviewed_at,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, ?)""",
                (pfmea_id, self.project_id, self.scenario_id, work_id, "Insufficient Torque", "P", 10, now, now, now),
            )
            # Create PFMEA cause with prevention control linked to assignment
            conn.execute(
                """INSERT INTO pfmea_causes (id, project_id, scenario_id, pfmea_entry_id, cause_description, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (cause_id, self.project_id, self.scenario_id, pfmea_id, "Tool calibration drift", now, now),
            )
            conn.execute(
                """INSERT INTO pfmea_prevention_selections
                   (id, project_id, scenario_id, pfmea_entry_id, pfmea_cause_id, source_type,
                    quality_requirement_assignment_id, source_updated_at_snapshot, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), self.project_id, self.scenario_id, pfmea_id, cause_id, "quality_assignment", assign_id, now, now, now),
            )
            # Create Control Plan item with matching spec
            conn.execute(
                """INSERT INTO control_plan_items
                   (id, project_id, scenario_id, pfmea_entry_id, source_kind,
                    quality_requirement_assignment_id, quality_requirement_id,
                    source_quality_requirement_id_snapshot,
                    specification_requirement, control_method, characteristic_placement,
                    excluded, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'quality', ?, ?, ?, '35 +-2 Nm', 'Torque Wrench', 'Process', 0, ?, ?)""",
                (cp_id, self.project_id, self.scenario_id, pfmea_id, assign_id, req_id, req_id, now, now),
            )

        # Run matrix without any equipment placed -> should be WARNING (Yellow), not CRITICAL
        result = cross_functional_traceability_matrix(self.project_id, self.scenario_id)
        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        self.assertEqual(row["status"], "WARNING", "Missing torque tooling must be WARNING per Directive #2")
        self.assertEqual(row["status_label"], "🟡 Warning")
        self.assertIn("Missing Torque Tooling", row["discrepancy_summary"])
        self.assertEqual(result["summary"]["warning_steps"], 1)
        self.assertEqual(result["summary"]["critical_gap_steps"], 0)

    def test_specification_drift_detection_and_individual_alignment(self) -> None:
        """User Directive #3: Each spec drift must be reviewed and aligned individually."""
        work_id = f"work-{uuid4().hex[:8]}"
        req_id = f"req-{uuid4().hex[:8]}"
        assign_id = f"assign-{uuid4().hex[:8]}"
        pfmea_id = f"pfmea-{uuid4().hex[:8]}"
        cause_id = f"cause-{uuid4().hex[:8]}"
        cp_id = f"cp-{uuid4().hex[:8]}"
        eq_id = f"eq-{uuid4().hex[:8]}"
        type_id = f"eqt-{uuid4().hex[:8]}"
        placement_id = f"plc-{uuid4().hex[:8]}"
        now = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, station, operation, sequence, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (work_id, self.project_id, self.scenario_id, "Station 4", "Assemble Hub", 10, now),
            )
            # Quality assignment published as 45 +-1 Nm
            conn.execute(
                """INSERT INTO quality_requirements
                   (id, project_id, requirement_type, description, unique_identifier, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (req_id, self.project_id, "Torque", "Hub Nut Torque", "HUB-001", now, now),
            )
            conn.execute(
                """INSERT INTO quality_requirement_assignments
                   (id, project_id, scenario_id, work_element_id, quality_requirement_id,
                    requirement_type, description, unique_identifier, target_value, tolerances, unit,
                    source_updated_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (assign_id, self.project_id, self.scenario_id, work_id, req_id,
                 "Torque", "Hub Nut Torque", "HUB-001", 45.0, "+-1", "Nm",
                 now, now, now),
            )
            conn.execute(
                """INSERT INTO pfmea_entries
                   (id, project_id, scenario_id, work_element_id, potential_failure_mode, class_code,
                    process_operation_snapshot, process_pitch_snapshot,
                    process_sequence_snapshot, process_source_hash, quality_source_hash, source_reviewed_at,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, ?)""",
                (pfmea_id, self.project_id, self.scenario_id, work_id, "Loose Hub", "S",
                 "Assemble Hub", "Station 4", 10, now, now, now),
            )
            conn.execute(
                """INSERT INTO pfmea_causes (id, project_id, scenario_id, pfmea_entry_id, cause_description, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (cause_id, self.project_id, self.scenario_id, pfmea_id, "Torque under-tightened", now, now),
            )
            conn.execute(
                """INSERT INTO pfmea_prevention_selections
                   (id, project_id, scenario_id, pfmea_entry_id, pfmea_cause_id, source_type,
                    quality_requirement_assignment_id, source_updated_at_snapshot, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), self.project_id, self.scenario_id, pfmea_id, cause_id, "quality_assignment", assign_id, now, now, now),
            )
            # Control plan item was saved with outdated/drifted spec: 40 +-2 Nm
            conn.execute(
                """INSERT INTO control_plan_items
                   (id, project_id, scenario_id, pfmea_entry_id, source_kind,
                    quality_requirement_assignment_id, quality_requirement_id,
                    source_quality_requirement_id_snapshot,
                    specification_requirement, control_method, characteristic_placement,
                    excluded, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'quality', ?, ?, ?, '40 +-2 Nm', 'DC Tool', 'Process', 0, ?, ?)""",
                (cp_id, self.project_id, self.scenario_id, pfmea_id, assign_id, req_id, req_id, now, now),
            )
            # Placed equipment: Torque Tool
            type_row = conn.execute(
                "SELECT id FROM equipment_types WHERE project_id=? AND label='Torque tool'",
                (self.project_id,),
            ).fetchone()
            type_id = type_row["id"]
            conn.execute(
                """INSERT INTO equipment_assets (id, project_id, equipment_type_id, name, created_at, updated_at)
                   VALUES (?, ?, ?, 'Atlas Copco Nutrunner', ?, ?)""",
                (eq_id, self.project_id, type_id, now, now),
            )
            conn.execute(
                """INSERT INTO equipment_placements (id, project_id, scenario_id, equipment_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (placement_id, self.project_id, self.scenario_id, eq_id, now, now),
            )
            conn.execute(
                """INSERT INTO equipment_process_links
                   (id, project_id, scenario_id, placement_id, work_element_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), self.project_id, self.scenario_id, placement_id, work_id, now, now),
            )

        # Check matrix: Spec Drift must be detected
        result_before = cross_functional_traceability_matrix(self.project_id, self.scenario_id)
        self.assertEqual(len(result_before["rows"]), 1)
        row_before = result_before["rows"][0]
        self.assertTrue(row_before["spec_drift"])
        self.assertEqual(row_before["status"], "WARNING")
        self.assertIn("Specification Drift", row_before["discrepancy_summary"])
        self.assertEqual(result_before["summary"]["spec_drift_count"], 1)

        # Execute individual alignment for this single control plan item
        align_result = align_control_plan_specification(
            self.project_id,
            self.scenario_id,
            cp_id,
            self.editor,
        )
        self.assertTrue(align_result["success"])
        self.assertEqual(align_result["previous_specification"], "40 +-2 Nm")
        self.assertEqual(align_result["aligned_specification"], "45 +-1 Nm")

        # Re-check matrix: Spec drift is resolved, and because all checks now pass, row is PROTECTED
        result_after = cross_functional_traceability_matrix(self.project_id, self.scenario_id)
        row_after = result_after["rows"][0]
        self.assertFalse(row_after["spec_drift"])
        self.assertEqual(row_after["status"], "PROTECTED")
        self.assertEqual(row_after["status_label"], "🟢 Protected")
        self.assertEqual(result_after["summary"]["spec_drift_count"], 0)
        self.assertEqual(result_after["summary"]["protected_steps"], 1)
        self.assertEqual(result_after["summary"]["fully_protected_pct"], 100.0)

        # Verify audit log was recorded
        with store.connection() as conn:
            audit = conn.execute(
                """SELECT action, editor_name, table_name FROM audit_log
                   WHERE project_id=? AND table_name='Control Plan' AND action='Align Specification'""",
                (self.project_id,),
            ).fetchone()
            self.assertIsNotNone(audit)
            self.assertEqual(audit["editor_name"], self.editor)
            self.assertEqual(audit["table_name"], "Control Plan")

    def test_quick_link_step_equipment(self) -> None:
        work_id = f"work-{uuid4().hex[:8]}"
        eq_id = f"eq-{uuid4().hex[:8]}"
        type_id = f"eqt-{uuid4().hex[:8]}"
        now = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, station, operation, sequence, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (work_id, self.project_id, self.scenario_id, "Station 5", "Vision Inspection", 10, now),
            )
            type_row = conn.execute(
                "SELECT id FROM equipment_types WHERE project_id=? AND label='Vision equipment'",
                (self.project_id,),
            ).fetchone()
            type_id = type_row["id"]
            conn.execute(
                """INSERT INTO equipment_assets (id, project_id, equipment_type_id, name, created_at, updated_at)
                   VALUES (?, ?, ?, 'Cognex Camera', ?, ?)""",
                (eq_id, self.project_id, type_id, now, now),
            )

        link_result = quick_link_step_equipment(
            self.project_id,
            self.scenario_id,
            work_id,
            eq_id,
            self.editor,
        )
        self.assertTrue(link_result["success"])

        with store.connection() as conn:
            link_count = conn.execute(
                """SELECT COUNT(*) FROM equipment_process_links
                   WHERE scenario_id=? AND work_element_id=?""",
                (self.scenario_id, work_id),
            ).fetchone()[0]
            self.assertEqual(link_count, 1)


if __name__ == "__main__":
    unittest.main()
