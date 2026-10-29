from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import pandas as pd

from streamlit.testing.v1 import AppTest

from utils import store


class ProcessPartRequirementNamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_req_naming_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])
        self.section_id = store.add_assembly_section(
            self.project_id, "Main Spine", "Main spine", None, ""
        )
        self.area_id = str(uuid4())
        self.pitch_id = str(uuid4())
        self.yamazumi_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES (?, ?, ?, ?, 'Assembly Area', ?)""",
                (self.area_id, self.project_id, self.scenario_id, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES (?, ?, ?, 'P01', 'First pitch', ?)""",
                (self.pitch_id, self.project_id, self.area_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, description,
                    time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, 'Fasten Bracket and Screws', 15.0, 10, ?)""",
                (self.yamazumi_id, self.project_id, self.area_id, self.pitch_id, timestamp),
            )

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_auto_name_generation_multi_part_consume(self) -> None:
        part_1 = str(uuid4())
        part_2 = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, updated_at)
                   VALUES (?, ?, 'BRK-01', 'Mounting Bracket', ?)""",
                (part_1, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, updated_at)
                   VALUES (?, ?, 'SCR-02', 'M4 Hex Screw', ?)""",
                (part_2, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, part_id, section_id, sequence, quantity, updated_at)
                   VALUES (?, ?, ?, ?, 1, 1, ?)""",
                (str(uuid4()), self.project_id, part_1, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, part_id, section_id, sequence, quantity, updated_at)
                   VALUES (?, ?, ?, ?, 2, 2, ?)""",
                (str(uuid4()), self.project_id, part_2, self.section_id, timestamp),
            )

        app = AppTest.from_file(str(store.ROOT / "app_pages/process.py"), default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Test IE"
        app.session_state[
            f"process_yamazumi_source_{self.scenario_id}_{self.section_id}__editor_instance_0"
        ] = {"selection": {"rows": [0], "columns": [], "cells": []}}
        app.session_state[
            f"process_part_source_{self.scenario_id}_{self.section_id}__editor_instance_0"
        ] = {"selection": {"rows": [0, 1], "columns": [], "cells": []}}
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])

        # For multi-part consume, a text_input is rendered and pre-filled with auto_name
        req_inputs = [
            t for t in app.text_input
            if str(t.key).startswith(f"process_pairing_requirement_{self.scenario_id}_{self.section_id}_")
        ]
        self.assertEqual(len(req_inputs), 1)
        self.assertEqual(req_inputs[0].value, "Mounting Bracket, M4 Hex Screw")

        # Each selected part has an "Unlink this part from the PAAG element" button in Create PAAG Elements
        for pid in (part_1, part_2):
            unlink_btn = app.button(
                key=f"destructive_create_unlink_part_{self.scenario_id}_{self.section_id}_{self.yamazumi_id}_{pid}"
            )
            self.assertEqual(unlink_btn.label, "Unlink this part from the PAAG element")

        # Submit pairing without changing the name
        submit_btn = next(
            b for b in app.button
            if str(b.key).startswith(f"process_pairing_submit_{self.scenario_id}_{self.section_id}_")
        )
        app = submit_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])

        # Check group was saved with the auto name
        groups = store.query(
            """SELECT id, name, selection_rule FROM process_part_groups
               WHERE project_id=? AND scenario_id=?""",
            (self.project_id, self.scenario_id),
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["name"], "Mounting Bracket, M4 Hex Screw")
        self.assertEqual(groups[0]["selection_rule"], "Use all")

        # Unlink one part from the multi-part group; the other part remains
        group_id = str(groups[0]["id"])
        store.unlink_part_from_process_group(self.project_id, self.scenario_id, group_id, part_1)
        remaining_opts = store.query(
            "SELECT part_id FROM process_part_options WHERE group_id = ?",
            (group_id,),
        )
        self.assertEqual([str(r["part_id"]) for r in remaining_opts], [part_2])

        # Unlink the last remaining part; the group itself is cleaned up
        store.unlink_part_from_process_group(self.project_id, self.scenario_id, group_id, part_2)
        remaining_groups = store.query(
            "SELECT id FROM process_part_groups WHERE id = ?",
            (group_id,),
        )
        self.assertEqual(len(remaining_groups), 0)

    def test_handle_operation_requires_name(self) -> None:
        part_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, updated_at)
                   VALUES (?, ?, 'PN-100', 'Cover Panel', ?)""",
                (part_id, self.project_id, timestamp),
            )
            assignment_id = str(uuid4())
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, part_id, section_id, sequence, quantity, updated_at)
                   VALUES (?, ?, ?, ?, 1, 1, ?)""",
                (assignment_id, self.project_id, part_id, self.section_id, timestamp),
            )
            # Create a prior consume so Handle is available
            work_el_id = str(uuid4())
            group_id = str(uuid4())
            opt_id = str(uuid4())
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, operation, updated_at)
                   VALUES (?, ?, ?, 1, 'Initial consume', ?)""",
                (work_el_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id, name, selection_rule, quantity, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'Consume Cover', 'Use all', 1, ?)""",
                (group_id, self.project_id, self.scenario_id, work_el_id, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_options (id, group_id, part_id, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (opt_id, group_id, part_id, timestamp),
            )
        store.set_process_part_option_handling_type(
            self.project_id, self.scenario_id, opt_id, "Consume", assignment_id
        )

        app = AppTest.from_file(str(store.ROOT / "app_pages/process.py"), default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Test IE"
        app.session_state[
            f"process_yamazumi_source_{self.scenario_id}_{self.section_id}__editor_instance_0"
        ] = {"selection": {"rows": [0], "columns": [], "cells": []}}
        app.session_state[
            f"process_part_source_{self.scenario_id}_{self.section_id}__editor_instance_0"
        ] = {"selection": {"rows": [0], "columns": [], "cells": []}}
        app.run(timeout=30)

        # Switch handling type to Handle
        handling_sb = next(
            s for s in app.selectbox
            if str(s.key).startswith(f"process_pairing_handling_{self.scenario_id}_{self.section_id}_")
        )
        app = handling_sb.select("Handle").run(timeout=30)

        # In Handle mode, requirement input is empty and marked with *
        req_input = next(
            t for t in app.text_input
            if str(t.key).startswith(f"process_pairing_requirement_{self.scenario_id}_{self.section_id}_")
        )
        self.assertEqual(req_input.label, "Part requirement *")
        self.assertEqual(req_input.value, "")

        # Submitting without a name shows an error
        submit_btn = next(
            b for b in app.button
            if str(b.key).startswith(f"process_pairing_submit_{self.scenario_id}_{self.section_id}_")
        )
        app = submit_btn.click().run(timeout=30)
        self.assertTrue(any("Part requirement name is required for handle operations" in err.value for err in app.error))

        # Supplying a name succeeds
        req_input = next(
            t for t in app.text_input
            if str(t.key).startswith(f"process_pairing_requirement_{self.scenario_id}_{self.section_id}_")
        )
        req_input.set_value("Inspect and position cover")
        submit_btn = next(
            b for b in app.button
            if str(b.key).startswith(f"process_pairing_submit_{self.scenario_id}_{self.section_id}_")
        )
        app = submit_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        handle_groups = store.query(
            """SELECT name FROM process_part_groups
               WHERE project_id=? AND scenario_id=? AND name='Inspect and position cover'""",
            (self.project_id, self.scenario_id),
        )
        self.assertEqual(len(handle_groups), 1)
