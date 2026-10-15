from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from streamlit.testing.v1 import AppTest

from utils import store
from utils.fishbone_store import (
    fishbone_part_assignments,
    search_parts_and_fishbone,
)


class AvailableFishbonePartsFiltersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_avail_parts_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])
        self.section_id = store.add_assembly_section(
            self.project_id, "Main", "Main spine", None, ""
        )
        self.area_id = str(uuid4())
        self.pitch_id = str(uuid4())
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

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_fishbone_part_assignments_and_search_includes_factory_nickname(self) -> None:
        part_id_1 = str(uuid4())
        part_id_2 = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, factory_nickname,
                    model_applicability, updated_at)
                   VALUES (?, ?, 'PART-100', 'Bracket Assembly', 'Front clip', 'Model-A', ?)""",
                (part_id_1, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, factory_nickname,
                    model_applicability, updated_at)
                   VALUES (?, ?, 'PART-200', 'Screw Hex Head', '', 'All', ?)""",
                (part_id_2, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, part_id, section_id, sequence, quantity, updated_at)
                   VALUES (?, ?, ?, ?, 1, 2, ?)""",
                (str(uuid4()), self.project_id, part_id_1, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, part_id, section_id, sequence, quantity, updated_at)
                   VALUES (?, ?, ?, ?, 2, 4, ?)""",
                (str(uuid4()), self.project_id, part_id_2, self.section_id, timestamp),
            )

        assignments = fishbone_part_assignments(self.project_id, self.scenario_id)
        self.assertIn("factory_nickname", assignments.columns)
        p100 = assignments.loc[assignments["part_number"] == "PART-100"].iloc[0]
        self.assertEqual(p100["factory_nickname"], "Front clip")

        # Test search by factory_nickname
        results = search_parts_and_fishbone(self.project_id, "Front clip", self.scenario_id)
        self.assertEqual(len(results), 1)
        self.assertEqual(results.iloc[0]["part_number"], "PART-100")
        self.assertEqual(results.iloc[0]["factory_nickname"], "Front clip")

    def test_process_page_filters_and_nickname_toggle(self) -> None:
        part_id_1 = str(uuid4())
        part_id_2 = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, factory_nickname,
                    model_applicability, updated_at)
                   VALUES (?, ?, 'PART-100', 'Bracket Assembly', 'Front clip', 'Model-A', ?)""",
                (part_id_1, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, factory_nickname,
                    model_applicability, updated_at)
                   VALUES (?, ?, 'PART-200', 'Screw Hex Head', 'Tiny bolt', 'All', ?)""",
                (part_id_2, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, part_id, section_id, sequence, quantity, updated_at)
                   VALUES (?, ?, ?, ?, 1, 2, ?)""",
                (str(uuid4()), self.project_id, part_id_1, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, part_id, section_id, sequence, quantity, updated_at)
                   VALUES (?, ?, ?, ?, 2, 4, ?)""",
                (str(uuid4()), self.project_id, part_id_2, self.section_id, timestamp),
            )

        # Pair PART-100 as Consumed
        we_id = str(uuid4())
        group_id = str(uuid4())
        option_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, updated_at)
                   VALUES (?, ?, ?, 10, 'P01', 'Install Front Clip', ?)""",
                (we_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id, name,
                    selection_rule, quantity, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'PAAG Element 1', 'Use all', 1, ?)""",
                (group_id, self.project_id, self.scenario_id, we_id, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_options
                   (id, group_id, part_id, handling_type, updated_at)
                   VALUES (?, ?, ?, 'Consume', ?)""",
                (option_id, group_id, part_id_1, timestamp),
            )

        # Run AppTest on process.py
        app = AppTest.from_file(str(store.ROOT / "app_pages/process.py"), default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Filter Test Editor"
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])

        # Check that available fishbone parts are separated into Not consumed and Consumed charts
        consumed_sb = [sb for sb in app.selectbox if sb.label == "Consumed"]
        self.assertEqual(len(consumed_sb), 0)

        not_consumed_df = next(
            df
            for df in app.dataframe
            if str(df.key).startswith(
                f"process_part_source_{self.scenario_id}_{self.section_id}"
            )
        )
        consumed_df = next(
            df
            for df in app.dataframe
            if str(df.key).startswith(
                f"process_part_source_consumed_{self.scenario_id}_{self.section_id}"
            )
        )
        self.assertEqual(
            not_consumed_df.value["part_number"].tolist(),
            ["PART-200"],
        )
        self.assertEqual(
            consumed_df.value["part_number"].tolist(),
            ["PART-100"],
        )

        handled_sb = [sb for sb in app.selectbox if sb.label == "Handled"]
        self.assertEqual(len(handled_sb), 1)
        self.assertEqual(handled_sb[0].options, ["All", "Handled", "Not handled"])

        model_sb = [sb for sb in app.selectbox if sb.label == "Model"]
        self.assertEqual(len(model_sb), 1)
        self.assertIn("All models", model_sb[0].options)
        self.assertIn("Model-A", model_sb[0].options)

        # Check Nickname toggle button
        nick_btn = [btn for btn in app.button if btn.label == "Nickname"]
        self.assertEqual(len(nick_btn), 1)
        nick_btn[0].click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertTrue(
            app.session_state[f"process_show_factory_nickname_{self.scenario_id}"]
        )

        # Filter by Handled -> Handled (none should match)
        handled_sb = [sb for sb in app.selectbox if sb.label == "Handled"][0]
        handled_sb.select("Handled").run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertTrue(
            any(
                "No not-consumed fishbone parts match these filters" in info.value
                for info in app.info
            )
        )
        self.assertTrue(
            any(
                "No consumed fishbone parts match these filters" in info.value
                for info in app.info
            )
        )

    def test_edit_process_line_replaces_incorrect_part(self) -> None:
        part_id_1 = str(uuid4())
        part_id_2 = str(uuid4())
        assign_id_1 = str(uuid4())
        assign_id_2 = str(uuid4())
        we_id = str(uuid4())
        group_id = str(uuid4())
        option_id = str(uuid4())
        timestamp = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, factory_nickname, model_applicability, updated_at)
                   VALUES (?, ?, 'PART-100', 'Bracket', 'Left Bracket', 'All', ?)""",
                (part_id_1, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, factory_nickname, model_applicability, updated_at)
                   VALUES (?, ?, 'PART-200', 'Motor', 'Drive Motor', 'All', ?)""",
                (part_id_2, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                   VALUES (?, ?, ?, ?, 10, 1, 'Mount bracket', ?)""",
                (assign_id_1, self.project_id, self.section_id, part_id_1, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                   VALUES (?, ?, ?, ?, 20, 1, 'Mount motor', ?)""",
                (assign_id_2, self.project_id, self.section_id, part_id_2, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, description, cycle_time_s, model_applicability, status, updated_at)
                   VALUES (?, ?, ?, 10, 'P1', 'Install part', 'Install part', 12.0, 'All', 'Draft', ?)""",
                (we_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id, name, selection_rule, quantity, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'Bracket', 'Use all', 1, ?)""",
                (group_id, self.project_id, self.scenario_id, we_id, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_options
                   (id, group_id, part_id, handling_type, fishbone_assignment_id, updated_at)
                   VALUES (?, ?, ?, 'Consume', ?, ?)""",
                (option_id, group_id, part_id_1, assign_id_1, timestamp),
            )

        app = AppTest.from_file(str(store.ROOT / "app_pages/process.py"), default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Line Edit Tester"
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])

        # Select our work element row in the table and click the footer "Edit line" button
        all_elements = store.project_table(
            "work_elements", self.project_id, "sequence", scenario_id=self.scenario_id
        )
        we_pos = int(all_elements.index[all_elements["id"].astype(str) == we_id][0])
        app.session_state[f"process_editor_{self.scenario_id}"] = {
            "edited_rows": {we_pos: {"selected": True}},
            "added_rows": [],
            "deleted_rows": [],
        }
        app.session_state[f"process_selected_line_id_{self.scenario_id}"] = we_id
        edit_btn = app.button(key=f"process_edit_line_btn_{self.scenario_id}")
        edit_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])

        # Verify "Tape machine" is available in Tool category
        tool_cat_sb = app.selectbox(key=f"edit_line_tool_cat_{self.scenario_id}_{we_id}")
        self.assertIn("Tape machine", tool_cat_sb.options)

        # Replace PART-100 with PART-200 in the Parts in requirement multiselect
        parts_ms = app.multiselect(
            key=f"edit_line_parts_{self.scenario_id}_{we_id}_{group_id}_{self.section_id}"
        )
        self.assertEqual(parts_ms.value, [part_id_1])
        parts_ms.set_value([part_id_2]).run(timeout=30)
        self.assertEqual(list(app.exception), [])

        # Click "Save line changes"
        save_btn = app.button(key=f"edit_line_save_{self.scenario_id}_{we_id}")
        save_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])

        # Verify PART-200 is now paired to the line and PART-100 was returned to Not consumed parts
        updated_groups = store.process_part_groups(
            self.project_id, self.scenario_id, we_id, active_only=True
        )
        self.assertEqual(len(updated_groups), 1)
        self.assertEqual(
            [opt["part_number"] for opt in updated_groups[0]["options"]],
            ["PART-200"],
        )

        not_consumed_df = next(
            df
            for df in app.dataframe
            if str(df.key).startswith(
                f"process_part_source_{self.scenario_id}_{self.section_id}"
            )
        )
        consumed_df = next(
            df
            for df in app.dataframe
            if str(df.key).startswith(
                f"process_part_source_consumed_{self.scenario_id}_{self.section_id}"
            )
        )
        self.assertEqual(
            not_consumed_df.value["part_number"].tolist(),
            ["PART-100"],
        )
        self.assertEqual(
            consumed_df.value["part_number"].tolist(),
            ["PART-200"],
        )

