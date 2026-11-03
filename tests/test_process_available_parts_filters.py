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

        model_sb = [
            sb
            for sb in app.selectbox
            if sb.label == "Model"
            and sb.key == f"process_parts_model_{self.scenario_id}_{self.section_id}"
        ]
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

        # Replace PART-100 with PART-200 in the Parts Consumed or Handled multiselect
        parts_ms = app.multiselect(
            key=f"edit_line_parts_{self.scenario_id}_{we_id}_{group_id}_{self.section_id}"
        )
        self.assertEqual(parts_ms.label, "Parts Consumed or Handled")
        self.assertEqual(parts_ms.value, [part_id_1])

        # Verify per-part "Unlink this part from the PAAG element" button is present for PART-100
        unlink_part_btn = app.button(
            key=f"destructive_edit_line_remove_part_{self.scenario_id}_{we_id}_{group_id}_{self.section_id}_{part_id_1}"
        )
        self.assertEqual(unlink_part_btn.label, "Unlink this part from the PAAG element")

        parts_ms.set_value([part_id_2]).run(timeout=30)
        self.assertEqual(list(app.exception), [])

        # Click "Save PAAG Element"
        save_btn = app.button(key=f"edit_line_save_{self.scenario_id}_{we_id}")
        self.assertEqual(save_btn.label, "Save PAAG Element")
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

    def test_consumed_parts_table_populates_other_area_parts_for_handle(self) -> None:
        other_section_id = store.add_assembly_section(
            self.project_id, "Subassembly", "Assembly", self.section_id, ""
        )
        part_local = str(uuid4())
        part_other_consumed = str(uuid4())
        part_other_unconsumed = str(uuid4())
        other_assign_id = str(uuid4())
        yam_el_id = str(uuid4())
        we_other_id = str(uuid4())
        grp_other_id = str(uuid4())
        opt_other_id = str(uuid4())
        timestamp = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, model_applicability, updated_at)
                   VALUES (?, ?, 'PART-LOCAL', 'Local Main Frame', 'All', ?)""",
                (part_local, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, model_applicability, updated_at)
                   VALUES (?, ?, 'PART-OTHER-C', 'Subassembly Harness', 'All', ?)""",
                (part_other_consumed, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, model_applicability, updated_at)
                   VALUES (?, ?, 'PART-OTHER-U', 'Unconsumed Sub Part', 'All', ?)""",
                (part_other_unconsumed, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                   VALUES (?, ?, ?, ?, 1, 1, 'Main frame mount', ?)""",
                (str(uuid4()), self.project_id, self.section_id, part_local, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                   VALUES (?, ?, ?, ?, 1, 1, 'Pre-build harness', ?)""",
                (other_assign_id, self.project_id, other_section_id, part_other_consumed, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                   VALUES (?, ?, ?, ?, 2, 1, 'Unused sub location', ?)""",
                (str(uuid4()), self.project_id, other_section_id, part_other_unconsumed, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, description, time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, 'Route Harness in Main', 14.0, 10, ?)""",
                (yam_el_id, self.project_id, self.area_id, self.pitch_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, updated_at)
                   VALUES (?, ?, ?, 5, 'S01', 'Build Harness', ?)""",
                (we_other_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id, name, selection_rule, quantity, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'Subassembly Harness', 'Use all', 1, ?)""",
                (grp_other_id, self.project_id, self.scenario_id, we_other_id, other_section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_options
                   (id, group_id, part_id, handling_type, fishbone_assignment_id, updated_at)
                   VALUES (?, ?, ?, 'Consume', ?, ?)""",
                (opt_other_id, grp_other_id, part_other_consumed, other_assign_id, timestamp),
            )

        app = AppTest.from_file(str(store.ROOT / "app_pages/process.py"), default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Cross Area Tester"
        app.session_state[
            f"process_yamazumi_source_{self.scenario_id}_{self.section_id}__editor_instance_0"
        ] = {"selection": {"rows": [0], "columns": [], "cells": []}}
        app.session_state[
            f"process_part_source_consumed_{self.scenario_id}_{self.section_id}__editor_instance_0"
        ] = {"selection": {"rows": [0], "columns": [], "cells": []}}
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])

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
            ["PART-LOCAL"],
        )
        self.assertEqual(
            consumed_df.value["part_number"].tolist(),
            ["PART-OTHER-C"],
        )

        # Verify Handling type defaults to "Handle" for a part from another section
        handling_sb = app.selectbox(
            key=f"process_pairing_handling_{self.scenario_id}_{self.section_id}_{yam_el_id}_{part_other_consumed}"
        )
        self.assertEqual(handling_sb.value, "Handle")

        # Supply a requirement name and submit the Handle pairing in Main
        req_input = app.text_input(
            key=f"process_pairing_requirement_{self.scenario_id}_{self.section_id}_{yam_el_id}"
        )
        req_input.set_value("Route pre-consumed harness")
        submit_btn = app.button(
            key=f"process_pairing_submit_{self.scenario_id}_{self.section_id}_{yam_el_id}"
        )
        submit_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(list(app.error), [])

        groups = store.process_part_groups(self.project_id, self.scenario_id, active_only=True)
        handle_groups = [g for g in groups if g["name"] == "Route pre-consumed harness"]
        self.assertEqual(len(handle_groups), 1)
        self.assertEqual(str(handle_groups[0]["section_id"]), self.section_id)
        self.assertEqual(len(handle_groups[0]["options"]), 1)
        self.assertEqual(handle_groups[0]["options"][0]["part_id"], part_other_consumed)
        self.assertEqual(handle_groups[0]["options"][0]["handling_type"], "Handle")
        self.assertEqual(
            handle_groups[0]["options"][0]["fishbone_assignment_id"],
            other_assign_id,
        )

    def test_linked_yamazumi_feature_variant_syncs_to_process_table_and_edit_dialog(
        self,
    ) -> None:
        pitch_13_id = str(uuid4())
        we_id = str(uuid4())
        yam_id = str(uuid4())
        feature_id = str(uuid4())
        timestamp = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO complexity_features
                   (id, project_id, name, allowed_values, active, updated_at)
                   VALUES (?, ?, 'Pedestal / Riser', '["Pedestal", "Riser"]', 1, ?)""",
                (feature_id, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, model_variants, updated_at)
                   VALUES (?, ?, ?, '01-PED-013', 'Front Screws', '["Pedestal / Riser = Pedestal", "Pedestal / Riser = Riser"]', ?)""",
                (pitch_13_id, self.project_id, self.area_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, description, cycle_time_s, model_applicability, status, updated_at)
                   VALUES (?, ?, ?, 10, 'P01', 'Install 1 drawer slide rail', 'Yamazumi area', 7.0, 'All', 'Draft', ?)""",
                (we_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, model_variant, model_variants, work_type, description, time_s, sequence, process_element_id, process_sync_status, updated_at)
                   VALUES (?, ?, ?, ?, 'Base', '["Base"]', 'Cycle', 'Install 1 drawer slide rail', 7.0, 10, ?, 'Synchronized', ?)""",
                (yam_id, self.project_id, self.area_id, self.pitch_id, we_id, timestamp),
            )

        # Retag the Yamazumi element to "Pedestal / Riser = Pedestal" and move it to pitch 13
        store.update_yamazumi_element(
            self.project_id,
            self.area_id,
            yam_id,
            {
                "area_id": self.area_id,
                "pitch_id": self.pitch_id,
                "model_variants": ["Pedestal / Riser = Pedestal"],
                "work_type": "Cycle",
                "description": "Install 1 drawer slide rail",
                "time_s": 7.0,
            },
        )
        store.move_yamazumi_element(self.project_id, yam_id, pitch_13_id)

        we_row = store.query(
            "SELECT station, model_applicability FROM work_elements WHERE id=?",
            (we_id,),
        )[0]
        self.assertEqual(we_row["station"], "01-PED-013")
        self.assertEqual(
            we_row["model_applicability"], "Pedestal / Riser = Pedestal"
        )

        # Render Process at a Glance and verify the table and Edit line dialog show the feature variant
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/process.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Feature Sync Tester"
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])

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

        models_ms = app.multiselect(
            key=f"edit_line_models_{self.scenario_id}_{we_id}"
        )
        self.assertIn("Pedestal / Riser = Pedestal", models_ms.options)
        self.assertIn("Pedestal / Riser = Riser", models_ms.options)
        self.assertEqual(
            models_ms.value,
            ["Pedestal / Riser = Pedestal"],
        )


    def test_variant_specific_consume_allowance_across_mutually_exclusive_features(
        self,
    ) -> None:
        feature_id = str(uuid4())
        part_id = str(uuid4())
        assign_id = str(uuid4())
        yam_ped_id = str(uuid4())
        yam_riser_id = str(uuid4())
        yam_ped_extra_id = str(uuid4())
        yam_all_id = str(uuid4())
        timestamp = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO complexity_features
                   (id, project_id, name, allowed_values, active, updated_at)
                   VALUES (?, ?, 'Pedestal / Riser', '["Pedestal", "Riser"]', 1, ?)""",
                (feature_id, self.project_id, timestamp),
            )
            conn.execute(
                """UPDATE yamazumi_pitches
                   SET model_variants='["Base", "Pedestal / Riser = Pedestal", "Pedestal / Riser = Riser"]'
                   WHERE id=?""",
                (self.pitch_id,),
            )
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, model_applicability, updated_at)
                   VALUES (?, ?, '8911201P341', 'Drawer Slide Rail', 'All', ?)""",
                (part_id, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                   VALUES (?, ?, ?, ?, 1, 1, 'Common slide rail placement', ?)""",
                (assign_id, self.project_id, self.section_id, part_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, model_variant, model_variants,
                    work_type, description, time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, 'Pedestal / Riser = Pedestal',
                           '["Pedestal / Riser = Pedestal"]', 'Cycle',
                           'Install slide rail (Pedestal)', 10.0, 10, ?)""",
                (yam_ped_id, self.project_id, self.area_id, self.pitch_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, model_variant, model_variants,
                    work_type, description, time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, 'Pedestal / Riser = Riser',
                           '["Pedestal / Riser = Riser"]', 'Cycle',
                           'Install slide rail (Riser)', 10.0, 20, ?)""",
                (yam_riser_id, self.project_id, self.area_id, self.pitch_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, model_variant, model_variants,
                    work_type, description, time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, 'Pedestal / Riser = Pedestal',
                           '["Pedestal / Riser = Pedestal"]', 'Cycle',
                           'Second Pedestal step', 10.0, 30, ?)""",
                (yam_ped_extra_id, self.project_id, self.area_id, self.pitch_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, model_variant, model_variants,
                    work_type, description, time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, 'Base', '["Base"]', 'Cycle',
                           'All models step', 10.0, 40, ?)""",
                (yam_all_id, self.project_id, self.area_id, self.pitch_id, timestamp),
            )

        # 1. Pair 8911201P341 as Consume onto the Pedestal Yamazumi element
        store.reconcile_yamazumi_to_process(
            self.project_id, self.scenario_id, [yam_ped_id]
        )
        we_ped_id = str(
            store.query(
                "SELECT process_element_id FROM yamazumi_elements WHERE id=?",
                (yam_ped_id,),
            )[0]["process_element_id"]
        )
        store.save_process_part_group(
            self.project_id,
            self.scenario_id,
            we_ped_id,
            self.section_id,
            None,
            "Install slide rail (Pedestal)",
            "Use all",
            1,
            [part_id],
            handling_types_by_part={part_id: "Consume"},
            fishbone_assignment_ids_by_part={part_id: assign_id},
        )

        # 2. Verify placement options for Riser still have 1 remaining Consume allowance
        riser_opts = store.process_part_placement_options(
            self.project_id,
            self.scenario_id,
            self.section_id,
            part_id,
            yamazumi_element_id=yam_riser_id,
        ).to_dict("records")
        self.assertEqual(len(riser_opts), 1)
        self.assertEqual(riser_opts[0]["consumed_count"], 0)
        self.assertEqual(riser_opts[0]["remaining_consume_allowance"], 1)
        self.assertTrue(riser_opts[0]["can_consume"])
        self.assertTrue(riser_opts[0]["can_handle"])

        # 3. Verify another Pedestal step and an All models step have 0 remaining Consume allowance
        ped_extra_opts = store.process_part_placement_options(
            self.project_id,
            self.scenario_id,
            self.section_id,
            part_id,
            yamazumi_element_id=yam_ped_extra_id,
        ).to_dict("records")
        self.assertEqual(ped_extra_opts[0]["consumed_count"], 1)
        self.assertEqual(ped_extra_opts[0]["remaining_consume_allowance"], 0)
        self.assertFalse(ped_extra_opts[0]["can_consume"])
        self.assertTrue(ped_extra_opts[0]["can_handle"])

        with self.assertRaises(ValueError):
            store.validate_process_part_option_pairings(
                self.project_id,
                self.scenario_id,
                self.section_id,
                [
                    {
                        "part_id": part_id,
                        "handling_type": "Consume",
                        "fishbone_assignment_id": assign_id,
                    }
                ],
                yamazumi_element_id=yam_ped_extra_id,
            )

        with self.assertRaises(ValueError):
            store.validate_process_part_option_pairings(
                self.project_id,
                self.scenario_id,
                self.section_id,
                [
                    {
                        "part_id": part_id,
                        "handling_type": "Consume",
                        "fishbone_assignment_id": assign_id,
                    }
                ],
                yamazumi_element_id=yam_all_id,
            )

        # 4. In Process at a Glance UI, select Riser step + 8911201P341 from Consumed parts table
        # and verify it defaults to "Consume" and submits cleanly
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/process.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Variant Consume Tester"
        app.session_state[
            f"process_yamazumi_source_{self.scenario_id}_{self.section_id}__editor_instance_0"
        ] = {"selection": {"rows": [0], "columns": [], "cells": []}}
        app.session_state[
            f"process_part_source_consumed_{self.scenario_id}_{self.section_id}__editor_instance_0"
        ] = {"selection": {"rows": [0], "columns": [], "cells": []}}
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])

        handling_sb = app.selectbox(
            key=f"process_pairing_handling_{self.scenario_id}_{self.section_id}_{yam_riser_id}_{part_id}"
        )
        self.assertEqual(handling_sb.value, "Consume")

        submit_btn = app.button(
            key=f"process_pairing_submit_{self.scenario_id}_{self.section_id}_{yam_riser_id}"
        )
        submit_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(list(app.error), [])

        we_riser_id = str(
            store.query(
                "SELECT process_element_id FROM yamazumi_elements WHERE id=?",
                (yam_riser_id,),
            )[0]["process_element_id"]
        )
        riser_groups = store.process_part_groups(
            self.project_id, self.scenario_id, we_riser_id, active_only=True
        )
        self.assertEqual(len(riser_groups), 1)
        self.assertEqual(riser_groups[0]["options"][0]["handling_type"], "Consume")
        self.assertEqual(
            riser_groups[0]["options"][0]["fishbone_assignment_id"], assign_id
        )
        self.assertEqual(riser_groups[0]["options"][0]["quantity"], 1.0)

    def test_per_part_quantity_enabled_for_consume_and_disabled_for_handle(self):
        part_id = str(uuid4())
        assign_id = str(uuid4())
        yam_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, model_applicability, updated_at)
                   VALUES (?, ?, '8911201P341', 'Drawer Slide Rail', 'All', ?)""",
                (part_id, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                   VALUES (?, ?, ?, ?, 1, 4, 'Slide rail placement', ?)""",
                (assign_id, self.project_id, self.section_id, part_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, model_variant, model_variants,
                    work_type, description, time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, 'Base', '["Base"]', 'Cycle',
                           'Install slide rails', 10.0, 10, ?)""",
                (yam_id, self.project_id, self.area_id, self.pitch_id, timestamp),
            )

        app = AppTest.from_file(
            str(store.ROOT / "app_pages/process.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Quantity Tester"
        app.session_state[
            f"process_yamazumi_source_{self.scenario_id}_{self.section_id}__editor_instance_0"
        ] = {"selection": {"rows": [0], "columns": [], "cells": []}}
        app.session_state[
            f"process_part_source_{self.scenario_id}_{self.section_id}__editor_instance_0"
        ] = {"selection": {"rows": [0], "columns": [], "cells": []}}
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])

        handling_sb = app.selectbox(
            key=f"process_pairing_handling_{self.scenario_id}_{self.section_id}_{yam_id}_{part_id}"
        )
        qty_input = app.number_input(
            key=f"process_pairing_quantity_{self.scenario_id}_{self.section_id}_{yam_id}_{part_id}"
        )
        self.assertEqual(handling_sb.value, "Consume")
        self.assertFalse(qty_input.disabled)

        # Switching to Handle disables the Quantity box
        handling_sb.select("Handle").run(timeout=30)
        self.assertEqual(list(app.exception), [])
        qty_input_handle = app.number_input(
            key=f"process_pairing_quantity_{self.scenario_id}_{self.section_id}_{yam_id}_{part_id}"
        )
        self.assertTrue(qty_input_handle.disabled)

        # Switching back to Consume re-enables Quantity and saves the entered quantity
        handling_sb = app.selectbox(
            key=f"process_pairing_handling_{self.scenario_id}_{self.section_id}_{yam_id}_{part_id}"
        )
        handling_sb.select("Consume").run(timeout=30)
        qty_input_consume = app.number_input(
            key=f"process_pairing_quantity_{self.scenario_id}_{self.section_id}_{yam_id}_{part_id}"
        )
        self.assertFalse(qty_input_consume.disabled)
        qty_input_consume.set_value(3.0).run(timeout=30)

        submit_btn = app.button(
            key=f"process_pairing_submit_{self.scenario_id}_{self.section_id}_{yam_id}"
        )
        submit_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(list(app.error), [])

        we_id = str(
            store.query(
                "SELECT process_element_id FROM yamazumi_elements WHERE id=?",
                (yam_id,),
            )[0]["process_element_id"]
        )
        saved_groups = store.process_part_groups(
            self.project_id, self.scenario_id, we_id, active_only=True
        )
        self.assertEqual(len(saved_groups), 1)
        self.assertEqual(saved_groups[0]["quantity"], 3.0)
        self.assertEqual(saved_groups[0]["options"][0]["quantity"], 3.0)

        placements = store.process_part_placement_options(
            self.project_id,
            self.scenario_id,
            self.section_id,
            part_id,
        )
        self.assertEqual(len(placements), 1)
        self.assertEqual(float(placements.iloc[0]["consumed_count"]), 3.0)
        self.assertEqual(float(placements.iloc[0]["remaining_consume_allowance"]), 1.0)
        self.assertTrue(bool(placements.iloc[0]["can_consume"]))

    def test_consuming_multi_quantity_depletes_full_consume_allowance(self) -> None:
        part_id = str(uuid4())
        assign_id = str(uuid4())
        we1_id = str(uuid4())
        we2_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, model_applicability, updated_at)
                   VALUES (?, ?, '8911201P341', 'Pedestal Screw', 'All', ?)""",
                (part_id, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                   VALUES (?, ?, ?, ?, 1, 7, 'Shoot 7 screws on right', ?)""",
                (assign_id, self.project_id, self.section_id, part_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, description,
                    cycle_time_s, model_applicability, status, updated_at)
                   VALUES (?, ?, ?, 10, '01-PED-012', 'Shoot 7 screws', '', 22.0, 'All', 'Confirmed', ?),
                          (?, ?, ?, 20, '01-PED-012', 'Extra screw step', '', 5.0, 'All', 'Confirmed', ?)""",
                (
                    we1_id, self.project_id, self.scenario_id, timestamp,
                    we2_id, self.project_id, self.scenario_id, timestamp,
                ),
            )

        store.save_process_part_group(
            self.project_id,
            self.scenario_id,
            we1_id,
            self.section_id,
            None,
            "Pedestal Screw",
            "Use all",
            7.0,
            [part_id],
            "",
            handling_types_by_part={part_id: "Consume"},
            fishbone_assignment_ids_by_part={part_id: assign_id},
            quantities_by_part={part_id: 7.0},
        )

        placements = store.process_part_placement_options(
            self.project_id,
            self.scenario_id,
            self.section_id,
            part_id,
            work_element_id=we2_id,
        )
        self.assertEqual(len(placements), 1)
        self.assertEqual(float(placements.iloc[0]["fishbone_quantity"]), 7.0)
        self.assertEqual(float(placements.iloc[0]["consumed_count"]), 7.0)
        self.assertEqual(float(placements.iloc[0]["remaining_consume_allowance"]), 0.0)
        self.assertFalse(bool(placements.iloc[0]["can_consume"]))
        self.assertTrue(bool(placements.iloc[0]["can_handle"]))

        with self.assertRaises(ValueError) as ctx:
            store.validate_process_part_option_pairings(
                self.project_id,
                self.scenario_id,
                self.section_id,
                [
                    {
                        "part_id": part_id,
                        "handling_type": "Consume",
                        "quantity": 1.0,
                        "fishbone_assignment_id": assign_id,
                    }
                ],
                work_element_id=we2_id,
            )
        self.assertIn("already been fully consumed", str(ctx.exception))

    def test_hot_reload_process_store_preserves_updated_entrypoint_signature(self) -> None:
        import sys

        part_id = str(uuid4())
        yam_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, model_applicability, updated_at)
                   VALUES (?, ?, 'PART-RELOAD', 'Hot Reload Part', 'All', ?)""",
                (part_id, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                   VALUES (?, ?, ?, ?, 1, 2, 'Reload test mount', ?)""",
                (str(uuid4()), self.project_id, self.section_id, part_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, description, time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, 'Install Hot Reload Part', 10.0, 10, ?)""",
                (yam_id, self.project_id, self.area_id, self.pitch_id, timestamp),
            )

        # Simulate a stale function placed in utils.store.__dict__ before a hot-reload of utils.process_store
        def _stale_placement_options(project_id, scenario_id, section_id, part_id, *, exclude_group_id=None, _conn=None):
            raise TypeError("stale placement_options should have been replaced on reload")

        store.__dict__["process_part_placement_options"] = _stale_placement_options
        store._EXPORTED["process_part_placement_options"] = _stale_placement_options
        store._FACADE_BASELINE["process_part_placement_options"] = _stale_placement_options

        # Evict utils.process_store from sys.modules just like Streamlit's LocalSourcesWatcher does
        sys.modules.pop("utils.process_store", None)

        from utils.store import process_part_placement_options

        placements = process_part_placement_options(
            self.project_id,
            self.scenario_id,
            self.section_id,
            part_id,
            work_element_id=None,
            yamazumi_element_id=yam_id,
        )
        self.assertEqual(len(placements), 1)

    def test_fully_consumed_placement_remains_visible_but_cannot_be_selected(self) -> None:
        part_id = str(uuid4())
        assign_consumed_id = str(uuid4())
        assign_available_id = str(uuid4())
        we1_id = str(uuid4())
        we2_id = str(uuid4())
        group1_id = str(uuid4())
        group2_id = str(uuid4())
        timestamp = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, model_applicability, updated_at)
                   VALUES (?, ?, '8911201P341', 'Screw', 'All', ?)""",
                (part_id, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                   VALUES (?, ?, ?, ?, 10, 7, 'Attach Rear Cover to Rear Cover Subs', ?)""",
                (assign_consumed_id, self.project_id, self.section_id, part_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                   VALUES (?, ?, ?, ?, 20, 6, 'Attach Upper Cover', ?)""",
                (assign_available_id, self.project_id, self.section_id, part_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, description, cycle_time_s, model_applicability, status, updated_at)
                   VALUES (?, ?, ?, 10, 'P12', '7 Screws', '7 Screws', 14.0, 'All', 'Draft', ?)""",
                (we1_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, description, cycle_time_s, model_applicability, status, updated_at)
                   VALUES (?, ?, ?, 20, 'P12', '6 Screws', '6 Screws', 12.0, 'All', 'Draft', ?)""",
                (we2_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id, name, selection_rule, quantity, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'Screw', 'Use all', 7, ?)""",
                (group1_id, self.project_id, self.scenario_id, we1_id, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_options
                   (id, group_id, part_id, handling_type, quantity, fishbone_assignment_id, updated_at)
                   VALUES (?, ?, ?, 'Consume', 7, ?, ?)""",
                (str(uuid4()), group1_id, part_id, assign_consumed_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id, name, selection_rule, quantity, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'Screw', 'Use all', 1, ?)""",
                (group2_id, self.project_id, self.scenario_id, we2_id, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_options
                   (id, group_id, part_id, handling_type, quantity, fishbone_assignment_id, updated_at)
                   VALUES (?, ?, ?, 'Consume', 1, ?, ?)""",
                (str(uuid4()), group2_id, part_id, assign_available_id, timestamp),
            )

        app = AppTest.from_file(str(store.ROOT / "app_pages/process.py"), default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Dropdown Tester"
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])

        all_elements = store.project_table(
            "work_elements", self.project_id, "sequence", scenario_id=self.scenario_id
        )
        we2_pos = int(all_elements.index[all_elements["id"].astype(str) == we2_id][0])
        app.session_state[f"process_editor_{self.scenario_id}"] = {
            "edited_rows": {we2_pos: {"selected": True}},
            "added_rows": [],
            "deleted_rows": [],
        }
        app.session_state[f"process_selected_line_id_{self.scenario_id}"] = we2_id
        edit_btn = app.button(key=f"process_edit_line_btn_{self.scenario_id}")
        edit_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])

        loc_key = (
            f"edit_line_loc_{self.scenario_id}_{we2_id}_"
            f"{group2_id}_{self.section_id}_{part_id}"
        )
        loc_sb = app.selectbox(key=loc_key)
        # Both uses are shown in the dropdown options
        self.assertEqual(len(loc_sb.options), 2)
        self.assertIn("Unavailable for Consume — allowance fully used", loc_sb.options[0])
        self.assertIn("Remaining Consume allowance 6", loc_sb.options[1])
        self.assertEqual(loc_sb.value, assign_available_id)

        # Attempting to select the already-fully-consumed use resets selection to None
        loc_sb.select(loc_sb.options[0]).run(timeout=30)
        self.assertEqual(list(app.exception), [])
        loc_sb_after = app.selectbox(key=loc_key)
        self.assertIsNone(loc_sb_after.value)

        # Selecting the available use works as expected
        loc_sb_after.select(loc_sb_after.options[1]).run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.selectbox(key=loc_key).value, assign_available_id)

    def test_model_choice_selection_rule_and_per_part_model_variant_checkbox(self) -> None:
        part_a_id = str(uuid4())
        part_b_id = str(uuid4())
        part_c_id = str(uuid4())
        assign_a_id = str(uuid4())
        assign_b_id = str(uuid4())
        assign_c_id = str(uuid4())
        we_id = str(uuid4())
        timestamp = store.now_iso()

        with store.connection() as conn:
            for pid, pnum, pdesc, aid, seq, m_app, v_json in [
                (part_a_id, "PN-BLK", "Black Panel", assign_a_id, 10, "Model A", '["PN-SLV"]'),
                (part_b_id, "PN-SLV", "Silver Panel", assign_b_id, 20, "Model B", '["PN-BLK"]'),
                (part_c_id, "PN-SCR", "Mounting Screw", assign_c_id, 30, "All", "[]"),
            ]:
                conn.execute(
                    """INSERT INTO parts
                       (id, project_id, part_number, description, factory_nickname, model_applicability, variant_part_numbers_json, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (pid, self.project_id, pnum, pdesc, pdesc, m_app, v_json, timestamp),
                )
                conn.execute(
                    """INSERT INTO fishbone_part_assignments
                       (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                       VALUES (?, ?, ?, ?, ?, 2, 'Install on unit', ?)""",
                    (aid, self.project_id, self.section_id, pid, seq, timestamp),
                )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, description, cycle_time_s, model_applicability, status, updated_at)
                   VALUES (?, ?, ?, 10, 'P1', 'Install panel', 'Install panel', 15.0, 'All', 'Draft', ?)""",
                (we_id, self.project_id, self.scenario_id, timestamp),
            )

        # Validation requires at least one part to have Model variant checked when Selection rule is Model choice
        with self.assertRaisesRegex(
            ValueError,
            "Check 'Model variant' on at least one part when Selection rule is Model choice",
        ):
            store.save_process_part_group(
                self.project_id,
                self.scenario_id,
                we_id,
                self.section_id,
                None,
                "Panel assembly",
                "Model choice",
                1.0,
                [part_a_id, part_b_id, part_c_id],
                handling_types_by_part={
                    part_a_id: "Consume",
                    part_b_id: "Consume",
                    part_c_id: "Consume",
                },
                fishbone_assignment_ids_by_part={
                    part_a_id: assign_a_id,
                    part_b_id: assign_b_id,
                    part_c_id: assign_c_id,
                },
                quantities_by_part={
                    part_a_id: 1.0,
                    part_b_id: 1.0,
                    part_c_id: 2.0,
                },
                model_variants_by_part={
                    part_a_id: False,
                    part_b_id: False,
                    part_c_id: False,
                },
            )

        group_id = store.save_process_part_group(
            self.project_id,
            self.scenario_id,
            we_id,
            self.section_id,
            None,
            "Panel assembly",
            "Model choice",
            1.0,
            [part_a_id, part_b_id, part_c_id],
            handling_types_by_part={
                part_a_id: "Consume",
                part_b_id: "Consume",
                part_c_id: "Consume",
            },
            fishbone_assignment_ids_by_part={
                part_a_id: assign_a_id,
                part_b_id: assign_b_id,
                part_c_id: assign_c_id,
            },
            quantities_by_part={
                part_a_id: 1.0,
                part_b_id: 1.0,
                part_c_id: 2.0,
            },
            model_variants_by_part={
                part_a_id: True,
                part_b_id: True,
                part_c_id: False,
            },
        )
        groups = store.process_part_groups(
            self.project_id, self.scenario_id, we_id, active_only=True
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["selection_rule"], "Model choice")
        mv_by_pid = {
            str(opt["part_id"]): bool(opt.get("is_model_variant"))
            for opt in groups[0]["options"]
        }
        self.assertEqual(
            mv_by_pid,
            {part_a_id: True, part_b_id: True, part_c_id: False},
        )

        # Verify Edit line dialog displays Selection rule = Model choice and per-part Model variant checkboxes
        app = AppTest.from_file(str(store.ROOT / "app_pages/process.py"), default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Model Choice Tester"
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])

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

        rule_sb = app.selectbox(key=f"edit_line_rule_{self.scenario_id}_{we_id}_{group_id}")
        self.assertEqual(rule_sb.options, ["Use all", "Model choice", "Optional"])
        self.assertEqual(rule_sb.value, "Model choice")

        cb_a = app.checkbox(
            key=f"edit_line_mv_{self.scenario_id}_{we_id}_{group_id}_{self.section_id}_{part_a_id}"
        )
        cb_b = app.checkbox(
            key=f"edit_line_mv_{self.scenario_id}_{we_id}_{group_id}_{self.section_id}_{part_b_id}"
        )
        cb_c = app.checkbox(
            key=f"edit_line_mv_{self.scenario_id}_{we_id}_{group_id}_{self.section_id}_{part_c_id}"
        )
        self.assertEqual(cb_a.label, "Model variant")
        self.assertTrue(cb_a.value)
        self.assertTrue(cb_b.value)
        self.assertFalse(cb_c.value)

        # Verify switching Selection rule from "Use all" to "Model choice" pre-selects parts with model variants
        rule_sb.select("Use all").run(timeout=30)
        self.assertEqual(list(app.exception), [])
        rule_sb = app.selectbox(key=f"edit_line_rule_{self.scenario_id}_{we_id}_{group_id}")
        rule_sb.select("Model choice").run(timeout=30)
        self.assertEqual(list(app.exception), [])

        cb_a = app.checkbox(
            key=f"edit_line_mv_{self.scenario_id}_{we_id}_{group_id}_{self.section_id}_{part_a_id}"
        )
        cb_b = app.checkbox(
            key=f"edit_line_mv_{self.scenario_id}_{we_id}_{group_id}_{self.section_id}_{part_b_id}"
        )
        cb_c = app.checkbox(
            key=f"edit_line_mv_{self.scenario_id}_{we_id}_{group_id}_{self.section_id}_{part_c_id}"
        )
        self.assertTrue(cb_a.value)
        self.assertTrue(cb_b.value)
        self.assertFalse(cb_c.value)

        # Verify PAAG slide summary and canvas outline Model Choice variant parts in purple per step
        yam_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id, description, time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'Install panel', 15.0, 10, ?)""",
                (yam_id, self.project_id, self.area_id, self.pitch_id, we_id, timestamp),
            )
        summary = store.process_pitch_visual_summary(
            self.project_id, self.scenario_id, self.pitch_id
        )
        parts_by_num = {p["part_number"]: p for p in summary["parts"]}
        self.assertTrue(parts_by_num["PN-BLK"]["is_model_variant"])
        self.assertTrue(parts_by_num["PN-SLV"]["is_model_variant"])
        self.assertFalse(parts_by_num["PN-SCR"]["is_model_variant"])
        self.assertEqual(
            parts_by_num["PN-BLK"]["model_choice_group_id"],
            f"{we_id}::{group_id}",
        )
        self.assertEqual(
            parts_by_num["PN-SLV"]["model_choice_group_id"],
            f"{we_id}::{group_id}",
        )
        self.assertEqual(parts_by_num["PN-SCR"]["model_choice_group_id"], "")

        from utils.process_pitch_visual import render_pitch_canvas

        slide_html = render_pitch_canvas(summary)
        self.assertIn('<span class="model-choice-outline-label">Model Choice</span>', slide_html)
        self.assertIn(
            f'<tr class="model-choice-label-row" data-model-choice-group="{we_id}::{group_id}">',
            slide_html,
        )
        self.assertIn(
            f'<tr class="part-row model-choice-row model-choice-first" data-part-num="PN-BLK" data-model-choice-group="{we_id}::{group_id}">',
            slide_html,
        )
        self.assertIn(
            f'<tr class="part-row model-choice-row model-choice-last" data-part-num="PN-SLV" data-model-choice-group="{we_id}::{group_id}">',
            slide_html,
        )
        self.assertIn('<tr class="part-row" data-part-num="PN-SCR">', slide_html)

        # Verify each Yamazumi stack column restarts step numbering at 1
        multi_stack_summary = {
            **summary,
            "yamazumi_stacks": {
                "Pedestal / Riser = Pedestal": [
                    {"id": "y1", "work_element_id": "w1", "description": "Ped step 1", "time_s": 5.0, "work_type": "Cycle"},
                    {"id": "y2", "work_element_id": "w2", "description": "Ped step 2", "time_s": 5.0, "work_type": "Cycle"},
                    {"id": "y3", "work_element_id": "w3", "description": "Ped step 3", "time_s": 5.0, "work_type": "Cycle"},
                    {"id": "y4", "work_element_id": "w4", "description": "Ped step 4", "time_s": 5.0, "work_type": "Cycle"},
                ],
                "Pedestal / Riser = Riser": [
                    {"id": "y5", "work_element_id": "w5", "description": "Riser step 1", "time_s": 8.0, "work_type": "Cycle"},
                    {"id": "y6", "work_element_id": "w6", "description": "Riser step 2", "time_s": 8.0, "work_type": "Cycle"},
                ],
            },
        }
        multi_slide_html = render_pitch_canvas(multi_stack_summary)
        self.assertNotIn('<span class="stack-step-badge">5</span>', multi_slide_html)
        self.assertNotIn('<span class="stack-step-badge">6</span>', multi_slide_html)
        self.assertEqual(multi_slide_html.count('<span class="stack-step-badge">1</span>'), 2)
        self.assertEqual(multi_slide_html.count('<span class="stack-step-badge">2</span>'), 2)
        self.assertEqual(multi_slide_html.count('<span class="stack-step-badge">3</span>'), 1)
        self.assertEqual(multi_slide_html.count('<span class="stack-step-badge">4</span>'), 1)

    def test_paag_slide_tools_and_ppe_section_sizing_and_pitch_address_tools(self) -> None:
        from utils.process_pitch_visual import render_pitch_canvas

        we1_id = str(uuid4())
        we2_id = str(uuid4())
        yam1_id = str(uuid4())
        timestamp = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, description,
                    cycle_time_s, model_applicability, tool, status, updated_at)
                   VALUES (?, ?, ?, 10, 'P01', 'Torque base', 'Torque base', 10.0, 'All',
                           'Torque tool', 'Confirmed', ?),
                          (?, ?, ?, 20, 'P01 — First pitch', 'Install clip', 'Install clip', 8.0, 'All',
                           'Hand tool', 'Confirmed', ?)""",
                (
                    we1_id,
                    self.project_id,
                    self.scenario_id,
                    timestamp,
                    we2_id,
                    self.project_id,
                    self.scenario_id,
                    timestamp,
                ),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id, description, time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'Torque base', 10.0, 10, ?)""",
                (yam1_id, self.project_id, self.area_id, self.pitch_id, we1_id, timestamp),
            )

        summary = store.process_pitch_visual_summary(
            self.project_id, self.scenario_id, self.pitch_id
        )
        tool_names = [t.get("name") for t in summary["tools"]]
        self.assertIn("Torque tool", tool_names)
        self.assertIn("Hand tool", tool_names)

        slide_html = render_pitch_canvas(summary)
        self.assertIn('<div class="panel-section tools-panel">', slide_html)
        self.assertIn(".tools-panel {\n        flex: 0 0 auto;", slide_html)
        self.assertIn("Torque tool", slide_html)
        self.assertIn("Hand tool", slide_html)

    def test_parts_catalog_photo_copy_to_pitch_visual_media(self) -> None:
        part_id = str(uuid4())
        supp_photo_id = str(uuid4())
        assign_id = str(uuid4())
        we_id = str(uuid4())
        yam_id = str(uuid4())
        group_id = str(uuid4())
        timestamp = store.now_iso()

        uploads_dir = store.UPLOAD_DIR
        uploads_dir.mkdir(parents=True, exist_ok=True)
        primary_path = uploads_dir / f"test_catalog_primary_{uuid4().hex}.png"
        supp_path = uploads_dir / f"test_catalog_supp_{uuid4().hex}.png"
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
            b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        primary_path.write_bytes(png_bytes)
        supp_path.write_bytes(png_bytes)
        primary_rel = f"data/uploads/{primary_path.name}"
        supp_rel = f"data/uploads/{supp_path.name}"

        try:
            with store.connection() as conn:
                conn.execute(
                    """INSERT INTO parts
                       (id, project_id, part_number, description, factory_nickname,
                        model_applicability, image_path, updated_at)
                       VALUES (?, ?, 'PN-CAT-100', 'Catalog Bracket', 'Bracket',
                               'All', ?, ?)""",
                    (part_id, self.project_id, primary_rel, timestamp),
                )
                conn.execute(
                    """INSERT INTO part_images
                       (id, part_id, image_path, image_type, caption, created_at)
                       VALUES (?, ?, ?, 'Side View', '', ?)""",
                    (supp_photo_id, part_id, supp_rel, timestamp),
                )
                conn.execute(
                    """INSERT INTO fishbone_part_assignments
                       (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                       VALUES (?, ?, ?, ?, 10, 1, 'Mount bracket', ?)""",
                    (assign_id, self.project_id, self.section_id, part_id, timestamp),
                )
                conn.execute(
                    """INSERT INTO work_elements
                       (id, project_id, scenario_id, sequence, station, operation, description,
                        cycle_time_s, model_applicability, status, updated_at)
                       VALUES (?, ?, ?, 10, 'P01', 'Mount bracket', 'Mount bracket',
                               12.0, 'All', 'Confirmed', ?)""",
                    (we_id, self.project_id, self.scenario_id, timestamp),
                )
                conn.execute(
                    """INSERT INTO yamazumi_elements
                       (id, project_id, area_id, pitch_id, process_element_id, description,
                        time_s, sequence, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'Mount bracket', 12.0, 10, ?)""",
                    (yam_id, self.project_id, self.area_id, self.pitch_id, we_id, timestamp),
                )
                conn.execute(
                    """INSERT INTO process_part_groups
                       (id, project_id, scenario_id, work_element_id, section_id, name,
                        selection_rule, quantity, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'Catalog Bracket', 'Use all', 1, ?)""",
                    (group_id, self.project_id, self.scenario_id, we_id, self.section_id, timestamp),
                )
                conn.execute(
                    """INSERT INTO process_part_options
                       (id, group_id, part_id, handling_type, quantity, fishbone_assignment_id, updated_at)
                       VALUES (?, ?, ?, 'Consume', 1, ?, ?)""",
                    (str(uuid4()), group_id, part_id, assign_id, timestamp),
                )

            catalog_photos = store.catalog_part_photos_for_pitch(
                self.project_id, self.scenario_id, self.pitch_id
            )
            self.assertEqual(len(catalog_photos), 1)
            self.assertTrue(catalog_photos[0]["on_pitch"])
            views = {v["view_label"] for v in catalog_photos[0]["views"]}
            self.assertEqual(views, {"Primary Image", "Side View"})

            copied_media = store.copy_part_photo_to_pitch_visual_media(
                self.project_id,
                self.scenario_id,
                self.pitch_id,
                part_id,
                view_id=f"supp::{supp_photo_id}",
                tagged_work_element_ids=[we_id],
                sequence=10,
                current_editor="Photo Tester",
            )
            media_items = store.get_pitch_visual_media(
                self.project_id, self.scenario_id, self.pitch_id
            )
            self.assertEqual(len(media_items), 1)
            row = media_items[0]
            self.assertEqual(str(row["id"]), copied_media["id"])
            self.assertIn("PN-CAT-100", str(row["caption"]))
            self.assertIn("Side View", str(row["caption"]))
            copied_path = Path(str(row["file_path"]))
            self.assertNotEqual(copied_path.resolve(), supp_path.resolve())
            self.assertTrue(copied_path.exists())

            # Deleting the pitch visual aid moves it to the Recycle Bin, and emptying the Recycle Bin
            # deletes the copied file while leaving the Parts Catalog files intact.
            store.delete_pitch_visual_media(
                self.project_id,
                self.scenario_id,
                copied_media["id"],
                current_editor="Photo Tester",
            )
            self.assertEqual(
                store.get_pitch_visual_media(self.project_id, self.scenario_id, self.pitch_id),
                [],
            )
            store.empty_recycle_bin(project_id=self.project_id, editor_name="Photo Tester")
            self.assertFalse(copied_path.exists())
            self.assertTrue(supp_path.exists())
            self.assertTrue(primary_path.exists())
        finally:
            primary_path.unlink(missing_ok=True)
            supp_path.unlink(missing_ok=True)
            if "copied_path" in locals():
                copied_path.unlink(missing_ok=True)
