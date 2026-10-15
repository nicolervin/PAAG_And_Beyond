from __future__ import annotations

import os
import tempfile
import unittest
from uuid import uuid4

import pandas as pd

from pathlib import Path
from utils import store
from utils.store import (
    add_assembly_section,
    assembly_section_connections,
    assembly_sections,
    assign_parts_to_section,
    delete_assembly_section_connection,
    fishbone_part_assignments,
    fishbone_plan_snapshot,
    replace_fishbone_part_assignments,
    restore_fishbone_plan_snapshot,
    save_assembly_section_connection,
    save_fishbone_canvas_draft,
    save_fishbone_canvas_positions,
    work_element_op_contexts,
)


class FishboneCanvasConnectionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)
        self.orig_db_path = store.DB_PATH
        store.DB_PATH = self.tmp_path / "canvas_test.db"
        store.init_db()

        self.project_id = f"proj-{uuid4().hex[:8]}"
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (self.project_id, "Test Fishbone Project", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            )

    def tearDown(self) -> None:
        store.DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()

    def test_save_and_retrieve_connections(self) -> None:
        m1_id = add_assembly_section(self.project_id, "Main Line 1", "Main spine", None, "")
        m2_id = add_assembly_section(self.project_id, "Main Line 2", "Main spine", None, "")
        sub_id = add_assembly_section(self.project_id, "Door Subassembly", "Subassembly", m1_id, "")

        # Feed into M1 as subassembly
        save_assembly_section_connection(
            self.project_id, sub_id, m1_id, connection_type="subassembly", sequence=10, editor_name="Tester"
        )
        # Connect M1 to M2 in series
        save_assembly_section_connection(
            self.project_id, m1_id, m2_id, connection_type="series", sequence=20, editor_name="Tester"
        )

        conns = assembly_section_connections(self.project_id)
        self.assertEqual(len(conns), 2)

        types = dict(zip(conns["from_section_id"], conns["connection_type"]))
        self.assertEqual(types[sub_id], "subassembly")
        self.assertEqual(types[m1_id], "series")

    def test_multi_parent_connection_and_safe_delete(self) -> None:
        m1_id = add_assembly_section(self.project_id, "Main Line 1", "Main spine", None, "")
        m2_id = add_assembly_section(self.project_id, "Main Line 2", "Main spine", None, "")
        sub_id = add_assembly_section(self.project_id, "Wiring Subassembly", "Subassembly", m1_id, "")

        # Multi-parent flow: subassembly feeds BOTH M1 and M2
        save_assembly_section_connection(self.project_id, sub_id, m1_id, "subassembly", 10)
        c2_id = save_assembly_section_connection(self.project_id, sub_id, m2_id, "subassembly", 20)

        conns = assembly_section_connections(self.project_id)
        self.assertEqual(len(conns), 2)

        # Delete one connection; verify remaining parent survives in assembly_sections
        delete_assembly_section_connection(self.project_id, c2_id, editor_name="Tester")
        conns_after = assembly_section_connections(self.project_id)
        self.assertEqual(len(conns_after), 1)

        sec_rows = assembly_sections(self.project_id)
        sub_row = sec_rows.loc[sec_rows["id"] == sub_id].iloc[0]
        self.assertEqual(sub_row["parent_id"], m1_id)

    def test_save_fishbone_canvas_draft_atomic(self) -> None:
        m1_id = add_assembly_section(self.project_id, "Main Line 1", "Main spine", None, "")
        sub_id = add_assembly_section(self.project_id, "Subassembly", "Subassembly", m1_id, "")

        # Insert a part into catalog
        part_id = f"part-{uuid4().hex[:8]}"
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (part_id, self.project_id, "PN-100", "Bracket", 1.0, "2026-01-01T00:00:00"),
            )

        # Commit canvas draft with positions, connections, and part assignments
        result = save_fishbone_canvas_draft(
            self.project_id,
            positions={m1_id: (120, 240), sub_id: (360, 480)},
            connections=[{"from_section_id": sub_id, "to_section_id": m1_id, "connection_type": "subassembly", "sequence": 10}],
            new_assignments=[{"part_id": part_id, "section_id": sub_id, "quantity": 2.0, "use_description": "Draft drop"}],
            editor_name="CanvasUser",
        )

        self.assertEqual(result["positions_saved"], 2)
        self.assertEqual(result["connections_saved"], 1)
        self.assertEqual(result["assignments_saved"], 1)

        # Verify persisted positions
        sec_rows = assembly_sections(self.project_id)
        m1_row = sec_rows.loc[sec_rows["id"] == m1_id].iloc[0]
        self.assertEqual(m1_row["grid_x"], 120)
        self.assertEqual(m1_row["grid_y"], 240)

        # Verify persisted assignments
        assignments = fishbone_part_assignments(self.project_id)
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments.iloc[0]["part_id"], part_id)
        self.assertEqual(assignments.iloc[0]["section_id"], sub_id)
        self.assertEqual(float(assignments.iloc[0]["quantity"]), 2.0)

    def test_plan_snapshot_includes_connections(self) -> None:
        m1_id = add_assembly_section(self.project_id, "Main Line 1", "Main spine", None, "")
        m2_id = add_assembly_section(self.project_id, "Main Line 2", "Main spine", None, "")
        save_assembly_section_connection(self.project_id, m1_id, m2_id, "series", 10)

        snapshot = fishbone_plan_snapshot(self.project_id)
        self.assertIn("connections", snapshot)
        self.assertEqual(len(snapshot["connections"]), 1)

        # Delete connection
        conns = assembly_section_connections(self.project_id)
        delete_assembly_section_connection(self.project_id, conns.iloc[0]["id"])
        self.assertTrue(assembly_section_connections(self.project_id).empty)

        # Restore snapshot
        restore_fishbone_plan_snapshot(self.project_id, snapshot)
        conns_restored = assembly_section_connections(self.project_id)
        self.assertEqual(len(conns_restored), 1)
        self.assertEqual(conns_restored.iloc[0]["connection_type"], "series")

    def test_multi_parent_op_id_prefix(self) -> None:
        scenario_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO planning_scenarios (id, project_id, name, revision_label, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (scenario_id, self.project_id, "Base Scenario", "Rev A", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            )

        m1_id = add_assembly_section(self.project_id, "Main Line 1", "Main spine", None, "")
        m2_id = add_assembly_section(self.project_id, "Main Line 2", "Main spine", None, "")
        sub_id = add_assembly_section(self.project_id, "Shared Subassembly", "Subassembly", m1_id, "")

        save_assembly_section_connection(self.project_id, sub_id, m1_id, "subassembly", 10)
        save_assembly_section_connection(self.project_id, sub_id, m2_id, "subassembly", 20)

        work_id = str(uuid4())
        area_id = str(uuid4())
        pitch_id = str(uuid4())
        y_elem_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements (id, project_id, scenario_id, sequence, operation, description, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (work_id, self.project_id, scenario_id, 10, "Op 10", "Mount shared subassembly", "2026-01-01T00:00:00"),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (area_id, self.project_id, scenario_id, sub_id, "Sub Area", "2026-01-01T00:00:00"),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, sequence, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (pitch_id, self.project_id, area_id, "01", 1, "2026-01-01T00:00:00"),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements (id, project_id, area_id, pitch_id, process_element_id, sequence, description, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (y_elem_id, self.project_id, area_id, pitch_id, work_id, 10, "Mount shared subassembly", "2026-01-01T00:00:00"),
            )

        contexts = work_element_op_contexts(self.project_id, scenario_id)
        self.assertIn(work_id, contexts)
        self.assertTrue(contexts[work_id]["complete"])
        self.assertTrue(contexts[work_id]["op_id"].startswith("M1+M2.S1"))

    def test_assign_parts_with_step_number(self) -> None:
        m_id = add_assembly_section(self.project_id, "Main Line", "Main spine", None, "")
        sub_id = add_assembly_section(self.project_id, "FZ Liner Subassembly", "Subassembly", m_id, "")

        part1_id = f"part-{uuid4().hex[:8]}"
        part2_id = f"part-{uuid4().hex[:8]}"
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (part1_id, self.project_id, "FZ-001", "Liner Back", 1.0, "2026-01-01T00:00:00"),
            )
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (part2_id, self.project_id, "FZ-002", "Liner Front", 1.0, "2026-01-01T00:00:00"),
            )

        # Assign part1 to Step 1, part2 to Step 2
        assign_parts_to_section(self.project_id, [part1_id], sub_id, use_description="Op 1", step_number=1)
        assign_parts_to_section(self.project_id, [part2_id], sub_id, use_description="Op 2", step_number=2)

        assignments = fishbone_part_assignments(self.project_id)
        self.assertEqual(len(assignments), 2)
        self.assertIn("step_number", assignments.columns)

        p1_row = assignments.loc[assignments["part_id"] == part1_id].iloc[0]
        p2_row = assignments.loc[assignments["part_id"] == part2_id].iloc[0]
        self.assertEqual(int(p1_row["step_number"]), 1)
        self.assertEqual(int(p2_row["step_number"]), 2)

    def test_save_fishbone_canvas_draft_step_number_and_updates(self) -> None:
        m_id = add_assembly_section(self.project_id, "Main Line", "Main spine", None, "")
        sub_id = add_assembly_section(self.project_id, "FZ Liner Sub", "Subassembly", m_id, "")

        part_id = f"part-{uuid4().hex[:8]}"
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (part_id, self.project_id, "FZ-010", "Gasket", 1.0, "2026-01-01T00:00:00"),
            )

        # 1. New assignment staged with step_number=2
        result = save_fishbone_canvas_draft(
            self.project_id,
            new_assignments=[{
                "part_id": part_id,
                "section_id": sub_id,
                "step_number": 2,
                "quantity": 1.0,
                "use_description": "Op 2 prep",
            }],
            editor_name="StepTester",
        )
        self.assertEqual(result["assignments_saved"], 1)

        assignments = fishbone_part_assignments(self.project_id)
        self.assertEqual(len(assignments), 1)
        self.assertEqual(int(assignments.iloc[0]["step_number"]), 2)
        aid = str(assignments.iloc[0]["id"])

        # 2. Update assignment to step_number=3 via updated_assignments
        update_result = save_fishbone_canvas_draft(
            self.project_id,
            updated_assignments=[{
                "assignment_id": aid,
                "step_number": 3,
            }],
            editor_name="StepTester",
        )
        self.assertEqual(update_result["assignments_updated"], 1)

        assignments_after = fishbone_part_assignments(self.project_id)
        self.assertEqual(len(assignments_after), 1)
        self.assertEqual(int(assignments_after.iloc[0]["step_number"]), 3)

    def test_replace_fishbone_part_assignments_preserves_step_number(self) -> None:
        m_id = add_assembly_section(self.project_id, "Main Line", "Main spine", None, "")
        sub_id = add_assembly_section(self.project_id, "Door Sub", "Subassembly", m_id, "")

        part_id = f"part-{uuid4().hex[:8]}"
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (part_id, self.project_id, "DR-001", "Hinge", 2.0, "2026-01-01T00:00:00"),
            )

        assign_parts_to_section(self.project_id, [part_id], sub_id, step_number=1)
        assignments = fishbone_part_assignments(self.project_id)
        self.assertEqual(int(assignments.iloc[0]["step_number"]), 1)

        # Edit table row to step_number=4
        assignments["step_number"] = 4
        assignments["notes"] = "Updated in table"
        count = replace_fishbone_part_assignments(self.project_id, assignments)
        self.assertEqual(count, 1)

        assignments_after = fishbone_part_assignments(self.project_id)
        self.assertEqual(int(assignments_after.iloc[0]["step_number"]), 4)
        self.assertEqual(assignments_after.iloc[0]["notes"], "Updated in table")

    def test_add_assembly_section_with_grid_coordinates(self) -> None:
        # Create Main spine with grid_x and grid_y
        main_id = add_assembly_section(
            self.project_id,
            "Main Assembly Spine",
            "Main spine",
            parent_id=None,
            description="Main assembly spine",
            grid_x=320,
            grid_y=240,
        )
        # Create Subassembly with grid_x, grid_y and parent
        sub_id = add_assembly_section(
            self.project_id,
            "Door Subassembly Spine",
            "Subassembly",
            parent_id=main_id,
            description="Door branch",
            grid_x=160,
            grid_y=420,
        )
        save_assembly_section_connection(
            self.project_id,
            sub_id,
            main_id,
            connection_type="subassembly",
            sequence=10,
            editor_name="CanvasUser",
        )

        sections = assembly_sections(self.project_id)
        self.assertEqual(len(sections), 2)
        main_row = sections.loc[sections["id"] == main_id].iloc[0]
        sub_row = sections.loc[sections["id"] == sub_id].iloc[0]

        self.assertEqual(int(main_row["grid_x"]), 320)
        self.assertEqual(int(main_row["grid_y"]), 240)
        self.assertEqual(int(sub_row["grid_x"]), 160)
        self.assertEqual(int(sub_row["grid_y"]), 420)

        connections = assembly_section_connections(self.project_id)
        self.assertEqual(len(connections), 1)
        self.assertEqual(connections.iloc[0]["from_section_id"], sub_id)
        self.assertEqual(connections.iloc[0]["to_section_id"], main_id)

    def test_parallel_and_support_operations_connections(self) -> None:
        main_id = add_assembly_section(self.project_id, "Main Line", "Main spine", None, "")
        supp_id = add_assembly_section(self.project_id, "Stamping Support Ops", "Support Operations", None, "")
        feeder1_id = add_assembly_section(self.project_id, "FF Top Liner Prep", "Subassembly", main_id, "")
        feeder2_id = add_assembly_section(self.project_id, "FF RH Liner Prep", "Subassembly", main_id, "")

        # Support ops connected via buffer storage into Main Line
        c_supp = save_assembly_section_connection(
            self.project_id, supp_id, main_id, connection_type="parallel", sequence=10, editor_name="Tester"
        )
        # Parallel feeder branches feeding into main section
        c_f1 = save_assembly_section_connection(
            self.project_id, feeder1_id, main_id, connection_type="parallel", sequence=20, editor_name="Tester"
        )
        c_f2 = save_assembly_section_connection(
            self.project_id, feeder2_id, main_id, connection_type="parallel", sequence=30, editor_name="Tester"
        )

        conns = assembly_section_connections(self.project_id)
        self.assertEqual(len(conns), 3)

        type_map = dict(zip(conns["from_section_id"], conns["connection_type"]))
        self.assertEqual(type_map[supp_id], "parallel")
        self.assertEqual(type_map[feeder1_id], "parallel")
        self.assertEqual(type_map[feeder2_id], "parallel")

        # Verify walk order parent_id preserved for Subassembly
        sec_df = assembly_sections(self.project_id)
        f1_row = sec_df.loc[sec_df["id"] == feeder1_id].iloc[0]
        self.assertEqual(f1_row["parent_id"], main_id)

    def test_palette_and_table_part_consistency(self) -> None:
        sec_id = add_assembly_section(self.project_id, "Main Station", "Main spine", None, "")

        part1_id = f"part-{uuid4().hex[:8]}"
        part2_id = f"part-{uuid4().hex[:8]}"
        part3_id = f"part-{uuid4().hex[:8]}"

        with store.connection() as conn:
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (part1_id, self.project_id, "PN-101", "Bracket A", 1.0, "2026-01-01T00:00:00"),
            )
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (part2_id, self.project_id, "PN-102", "Bracket B", 2.0, "2026-01-01T00:00:00"),
            )
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (part3_id, self.project_id, "PN-103", "Screw C", 4.0, "2026-01-01T00:00:00"),
            )

        # Assign part1 to section; leave part2 and part3 unassigned
        assign_parts_to_section(self.project_id, [part1_id], sec_id)

        assignments = fishbone_part_assignments(self.project_id)
        placed_ids = set(assignments["part_id"].astype(str))

        self.assertIn(part1_id, placed_ids)
        self.assertNotIn(part2_id, placed_ids)
        self.assertNotIn(part3_id, placed_ids)

        # Simulate palette items construction
        parts_df = store.project_table("parts", self.project_id)
        self.assertEqual(len(parts_df), 3)

        palette_items = [
            {
                "part_id": str(r["id"]),
                "part_number": str(r["part_number"]),
                "placed": str(r["id"]) in placed_ids,
            }
            for _, r in parts_df.iterrows()
        ]

        unplaced_items = [it for it in palette_items if not it["placed"]]
        self.assertEqual(len(unplaced_items), 2)
        unplaced_pns = {it["part_number"] for it in unplaced_items}
        self.assertEqual(unplaced_pns, {"PN-102", "PN-103"})



