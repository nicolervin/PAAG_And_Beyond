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
    assembly_section_delete_impact,
    assembly_sections,
    assign_parts_to_section,
    delete_assembly_section_connection,
    delete_assembly_sections,
    fishbone_part_assignments,
    fishbone_plan_snapshot,
    move_assembly_section_connection,
    move_fishbone_part_assignment,
    reorder_fishbone_part_assignments,
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

    def test_support_operations_feeds_into_connection(self) -> None:
        main_sec = add_assembly_section(self.project_id, "Main Spine Line", "Main spine", None, "")
        supp_sec = add_assembly_section(
            self.project_id, "Stamping Cell", "Support Operations", main_sec, "Fabrication area"
        )
        sections = assembly_sections(self.project_id)
        supp_row = sections[sections["id"] == supp_sec].iloc[0]
        self.assertEqual(supp_row["parent_id"], main_sec)
        self.assertEqual(supp_row["section_type"], "Support Operations")

        # Save connection from Support Operations to Main Spine
        save_assembly_section_connection(
            self.project_id, supp_sec, main_sec, connection_type="subassembly", sequence=10, editor_name="Tester"
        )
        conns = assembly_section_connections(self.project_id)
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns.iloc[0]["from_section_id"], supp_sec)
        self.assertEqual(conns.iloc[0]["to_section_id"], main_sec)

    def test_move_fishbone_part_assignment_between_sections(self) -> None:
        sec1 = add_assembly_section(self.project_id, "Section 1", "Main spine", None, "")
        sec2 = add_assembly_section(self.project_id, "Section 2", "Main spine", None, "")

        part_id = f"part-{uuid4().hex[:8]}"
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (part_id, self.project_id, "999D8503P001", "Door Foam Outer", 1.0, "2026-01-01T00:00:00"),
            )
        assign_parts_to_section(self.project_id, [part_id], sec1)

        assignments = fishbone_part_assignments(self.project_id)
        self.assertEqual(len(assignments), 1)
        assignment_id = str(assignments.iloc[0]["id"])
        self.assertEqual(str(assignments.iloc[0]["section_id"]), sec1)

        # Move assignment from sec1 to sec2
        move_fishbone_part_assignment(self.project_id, assignment_id, sec2)

        updated_assignments = fishbone_part_assignments(self.project_id)
        self.assertEqual(len(updated_assignments), 1)
        self.assertEqual(str(updated_assignments.iloc[0]["section_id"]), sec2)

    def test_interactive_section_deletion_impact_includes_connections(self) -> None:
        sec2 = add_assembly_section(self.project_id, "Target Section", "Main spine", None, "")
        sec1 = add_assembly_section(self.project_id, "Source Section", "Subassembly", sec2, "")
        sec3 = add_assembly_section(self.project_id, "Upstream Section", "Subassembly", sec1, "")

        # Connect upstream -> sec1, and sec1 -> sec2
        save_assembly_section_connection(self.project_id, sec3, sec1, "subassembly", 10)
        save_assembly_section_connection(self.project_id, sec1, sec2, "series", 20)

        # Assign part to sec1
        part_id = f"part-{uuid4().hex[:8]}"
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (part_id, self.project_id, "999D8503P001", "Door Trim", 1.0, "2026-01-01T00:00:00"),
            )
        assign_parts_to_section(self.project_id, [part_id], sec1)

        impact = assembly_section_delete_impact(self.project_id, [sec1])
        # sec1 has child sec3, so 2 affected sections total
        self.assertEqual(impact["affected_section_count"], 2)
        self.assertEqual(impact["fishbone_use_count"], 1)
        self.assertEqual(impact["connection_count"], 2)

    def test_interactive_section_deletion_with_rehome(self) -> None:
        sec2 = add_assembly_section(self.project_id, "Destination Section", "Main spine", None, "")
        sec1 = add_assembly_section(self.project_id, "Feed Section", "Subassembly", sec2, "")
        sec3 = add_assembly_section(self.project_id, "Upstream Section", "Subassembly", sec2, "")

        # Connect upstream -> sec1, and sec1 -> sec2
        save_assembly_section_connection(self.project_id, sec3, sec1, "series", 10)
        save_assembly_section_connection(self.project_id, sec1, sec2, "series", 20)

        # Assign part to sec1
        part_id = f"part-{uuid4().hex[:8]}"
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (part_id, self.project_id, "999D8503P002", "Door Panel", 1.0, "2026-01-01T00:00:00"),
            )
        assign_parts_to_section(self.project_id, [part_id], sec1)

        # Delete sec1 with rehome_parts=True pointing to sec2
        res = delete_assembly_sections(
            project_id=self.project_id,
            section_ids=[sec1],
            target_section_id=sec2,
            rehome_parts=True,
            cascade_delete_content=False,
        )
        self.assertEqual(res["affected_section_count"], 1)

        # Part assignment should now belong to sec2
        assignments = fishbone_part_assignments(self.project_id)
        self.assertEqual(len(assignments), 1)
        self.assertEqual(str(assignments.iloc[0]["section_id"]), sec2)

        # Connection sec3 -> sec1 should now be re-routed to sec3 -> sec2
        # Connection sec1 -> sec2 would have become sec2 -> sec2 (self-loop) and thus removed
        conns = assembly_section_connections(self.project_id)
        self.assertEqual(len(conns), 1)
        self.assertEqual(str(conns.iloc[0]["from_section_id"]), sec3)
        self.assertEqual(str(conns.iloc[0]["to_section_id"]), sec2)

    def test_interactive_section_deletion_cascade_delete_all(self) -> None:
        sec2 = add_assembly_section(self.project_id, "Main Section", "Main spine", None, "")
        sec1 = add_assembly_section(self.project_id, "Standalone Section", "Subassembly", sec2, "")

        save_assembly_section_connection(self.project_id, sec1, sec2, "subassembly", 10)

        # Assign part to sec1
        part_id = f"part-{uuid4().hex[:8]}"
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (part_id, self.project_id, "999D8503P003", "Bracket", 1.0, "2026-01-01T00:00:00"),
            )
        assign_parts_to_section(self.project_id, [part_id], sec1)

        # Delete sec1 with cascade_delete_content=True
        res = delete_assembly_sections(
            project_id=self.project_id,
            section_ids=[sec1],
            target_section_id=None,
            rehome_parts=False,
            cascade_delete_content=True,
        )
        self.assertEqual(res["affected_section_count"], 1)

        # Part assignment should be unassigned (removed from fishbone_part_assignments)
        assignments = fishbone_part_assignments(self.project_id)
        self.assertEqual(len(assignments), 0)

        # Flow connection should be gone
        conns = assembly_section_connections(self.project_id)
        self.assertEqual(len(conns), 0)

        # Section should no longer exist
        secs = assembly_sections(self.project_id)
        self.assertNotIn(sec1, secs["id"].tolist())

    def test_assembly_drop_and_child_parts_enrichment(self) -> None:
        main_sec = add_assembly_section(self.project_id, "Main Spine", "Main spine", None, "")
        sec = add_assembly_section(self.project_id, "Assembly Line", "Subassembly", main_sec, "")
        asm_id = f"part-{uuid4().hex[:8]}"
        ch1_id = f"part-{uuid4().hex[:8]}"
        ch2_id = f"part-{uuid4().hex[:8]}"

        with store.connection() as conn:
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (asm_id, self.project_id, "999D8402G002", "Body Assembly", 1.0, "2026-01-01T00:00:00"),
            )
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (ch1_id, self.project_id, "999D8501P001", "Front bumper", 1.0, "2026-01-01T00:00:00"),
            )
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (ch2_id, self.project_id, "999D8502P001", "Rear bumper", 1.0, "2026-01-01T00:00:00"),
            )

        # Test group part only placement
        res_group = save_fishbone_canvas_draft(
            self.project_id,
            new_assignments=[{
                "part_id": asm_id,
                "section_id": sec,
                "quantity": 1.0,
            }],
            editor_name="AsmTester",
        )
        self.assertEqual(res_group["assignments_saved"], 1)
        assignments = fishbone_part_assignments(self.project_id)
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments.iloc[0]["part_id"], asm_id)

        # Test placing children
        res_children = save_fishbone_canvas_draft(
            self.project_id,
            new_assignments=[
                {"part_id": ch1_id, "section_id": sec, "quantity": 1.0},
                {"part_id": ch2_id, "section_id": sec, "quantity": 1.0},
            ],
            editor_name="AsmTester",
        )
        self.assertEqual(res_children["assignments_saved"], 2)
        assignments_all = fishbone_part_assignments(self.project_id)
        self.assertEqual(len(assignments_all), 3)

    def test_move_assembly_section_connection(self) -> None:
        target_a = add_assembly_section(self.project_id, "Main Spine A", "Main spine", None, "")
        target_b = add_assembly_section(self.project_id, "Main Spine B", "Main spine", None, "")
        sec1 = add_assembly_section(self.project_id, "Sub Line 1", "Subassembly", target_a, "")
        sec2 = add_assembly_section(self.project_id, "Sub Line 2", "Subassembly", target_a, "")

        # Connect Sub Line 1 -> Main Spine A
        conn_id = save_assembly_section_connection(
            self.project_id, sec1, target_a, connection_type="subassembly", editor_name="Tester"
        )
        conns = assembly_section_connections(self.project_id)
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns.iloc[0]["to_section_id"], target_a)

        # Move Sub Line 1 connection from Main Spine A -> Main Spine B
        move_assembly_section_connection(
            self.project_id, conn_id, target_b, editor_name="Tester"
        )
        conns_after = assembly_section_connections(self.project_id)
        self.assertEqual(len(conns_after), 1)
        self.assertEqual(conns_after.iloc[0]["to_section_id"], target_b)

        # Verify parent_id was updated on Sub Line 1
        sec_df = assembly_sections(self.project_id)
        sub1 = sec_df[sec_df["id"] == sec1].iloc[0]
        self.assertEqual(sub1["parent_id"], target_b)

        # Connecting to self must fail
        with self.assertRaises(ValueError):
            move_assembly_section_connection(self.project_id, conn_id, sec1)

    def test_save_fishbone_canvas_draft_move_connection(self) -> None:
        target_a = add_assembly_section(self.project_id, "Assembly Line 1", "Main spine", None, "")
        target_b = add_assembly_section(self.project_id, "Assembly Line 2", "Main spine", None, "")
        sec1 = add_assembly_section(self.project_id, "Feeder", "Support Operations", target_a, "")

        # Initial connection Feeder -> Assembly Line 1
        init_cid = save_assembly_section_connection(
            self.project_id, sec1, target_a, connection_type="parallel", editor_name="Tester"
        )
        self.assertEqual(len(assembly_section_connections(self.project_id)), 1)

        # Re-route connection Feeder -> Assembly Line 2 via canvas draft
        res = save_fishbone_canvas_draft(
            self.project_id,
            deleted_connection_ids=[init_cid],
            connections=[{
                "from_section_id": sec1,
                "to_section_id": target_b,
                "connection_type": "parallel",
                "sequence": 10,
            }],
            editor_name="Tester",
        )
        self.assertEqual(res["connections_deleted"], 1)
        self.assertEqual(res["connections_saved"], 1)

        conns = assembly_section_connections(self.project_id)
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns.iloc[0]["from_section_id"], sec1)
        self.assertEqual(conns.iloc[0]["to_section_id"], target_b)

    def _create_part(self, description: str, part_number: str) -> str:
        part_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO parts (id, project_id, part_number, description, quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (part_id, self.project_id, part_number, description, 1.0, "2026-01-01T00:00:00"),
            )
        return part_id

    def test_reorder_fishbone_part_assignments_within_section(self) -> None:
        sec_id = add_assembly_section(self.project_id, "Assembly Line", "Main spine", None, "")
        part_a = self._create_part("Part Alpha", "PN-ALPHA")
        part_b = self._create_part("Part Beta", "PN-BETA")
        part_c = self._create_part("Part Gamma", "PN-GAMMA")

        # Assign all 3 to sec_id
        assign_parts_to_section(self.project_id, [part_a, part_b, part_c], sec_id)
        df_initial = fishbone_part_assignments(self.project_id)
        self.assertEqual(len(df_initial), 3)

        # Get their IDs
        aid_a = df_initial.loc[df_initial["part_id"] == part_a, "id"].iloc[0]
        aid_b = df_initial.loc[df_initial["part_id"] == part_b, "id"].iloc[0]
        aid_c = df_initial.loc[df_initial["part_id"] == part_c, "id"].iloc[0]

        # Reorder to C, A, B
        reordered_count = reorder_fishbone_part_assignments(
            self.project_id, sec_id, [aid_c, aid_a, aid_b], editor_name="Tester"
        )
        self.assertEqual(reordered_count, 3)

        df_after = fishbone_part_assignments(self.project_id)
        self.assertEqual(list(df_after["id"]), [aid_c, aid_a, aid_b])
        self.assertEqual(list(df_after["sequence"]), [10, 20, 30])

    def test_move_and_reorder_part_assignments_cross_section(self) -> None:
        sec1 = add_assembly_section(self.project_id, "Source Line", "Main spine", None, "")
        sec2 = add_assembly_section(self.project_id, "Target Line", "Main spine", None, "")

        part1 = self._create_part("Part 1", "PN-1")
        part2 = self._create_part("Part 2", "PN-2")
        part3 = self._create_part("Part 3", "PN-3")

        assign_parts_to_section(self.project_id, [part1], sec1)
        assign_parts_to_section(self.project_id, [part2, part3], sec2)

        df_sec1 = fishbone_part_assignments(self.project_id)
        aid1 = df_sec1.loc[df_sec1["part_id"] == part1, "id"].iloc[0]
        aid2 = df_sec1.loc[df_sec1["part_id"] == part2, "id"].iloc[0]
        aid3 = df_sec1.loc[df_sec1["part_id"] == part3, "id"].iloc[0]

        # Move part1 to sec2
        move_fishbone_part_assignment(self.project_id, aid1, sec2)

        # Reorder sec2 to [part2, part1, part3] (inserting part1 between part2 and part3)
        reorder_fishbone_part_assignments(
            self.project_id, sec2, [aid2, aid1, aid3], editor_name="Tester"
        )

        df_after = fishbone_part_assignments(self.project_id)
        sec2_assignments = df_after[df_after["section_id"] == sec2]
        self.assertEqual(list(sec2_assignments["id"]), [aid2, aid1, aid3])
        self.assertEqual(list(sec2_assignments["sequence"]), [10, 20, 30])

    def test_save_fishbone_canvas_draft_with_updated_assignment_sequence(self) -> None:
        sec = add_assembly_section(self.project_id, "Main Line", "Main spine", None, "")
        p1 = self._create_part("P1", "PN-01")
        p2 = self._create_part("P2", "PN-02")
        assign_parts_to_section(self.project_id, [p1, p2], sec)

        df = fishbone_part_assignments(self.project_id)
        aid1 = df.loc[df["part_id"] == p1, "id"].iloc[0]
        aid2 = df.loc[df["part_id"] == p2, "id"].iloc[0]

        # Use save_fishbone_canvas_draft to update sequence
        res = save_fishbone_canvas_draft(
            self.project_id,
            updated_assignments=[
                {"id": aid1, "sequence": 50},
                {"id": aid2, "sequence": 25},
            ],
            editor_name="Tester",
        )
        self.assertEqual(res["assignments_updated"], 2)

        df_after = fishbone_part_assignments(self.project_id)
        # Sequence 25 (aid2) comes before Sequence 50 (aid1)
        self.assertEqual(list(df_after["id"]), [aid2, aid1])
        self.assertEqual(list(df_after["sequence"]), [25, 50])






