from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from streamlit.testing.v1 import AppTest

from utils import store


class ModelAndAssemblyPageSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_page_smoke_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])
        if store.assembly_sections(self.project_id).empty:
            store.add_assembly_section(
                self.project_id, "Smoke assembly", "Main spine", None, ""
            )
        section_id = str(store.assembly_sections(self.project_id).iloc[0]["id"])
        self.section_id = section_id
        # Page fixtures add their own Yamazumi areas where needed. Keep the
        # shared baseline empty; automatic creation has dedicated coverage.
        store.execute(
            "DELETE FROM yamazumi_areas WHERE project_id=? AND section_id=?",
            (self.project_id, self.section_id),
        )
        assembly_id = str(uuid4())
        store.save_assembly_catalog_rows(
            self.project_id,
            [
                {
                    "id": assembly_id,
                    "assembly_number": "ASM-SMOKE",
                    "name": "Smoke assembly",
                    "make_buy": "Make",
                    "parent_id": None,
                    "built_section_id": section_id,
                    "installed_section_id": section_id,
                    "active": True,
                    "notes": "",
                }
            ],
        )
        model_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO project_models
                   (id, project_id, model_number, source_payload, active, updated_at)
                   VALUES (?, ?, 'SMOKE-MODEL', '{}', 1, ?)""",
                (model_id, self.project_id, store.now_iso()),
            )
        category_id = str(uuid4())
        store.save_assembly_grid_categories(
            self.project_id,
            section_id,
            [{
                "id": category_id,
                "ebom_name": "Smoke EBOM category",
                "display_name": "Smoke category",
                "installed_section_id": section_id,
                "sequence": 10,
            }],
        )
        store.save_assembly_grid_model_mappings(
            self.project_id,
            [{
                "category_id": category_id,
                "model_id": model_id,
                "assembly_id": assembly_id,
            }],
        )
        store.record_audit_event(
            self.project_id,
            "Assemblies catalog",
            "Save & Refresh",
            1,
            "AppTest smoke",
            {
                "make_buy_changes": [
                    {
                        "assembly_id": assembly_id,
                        "assembly_number": "ASM-SMOKE",
                        "old_value": "",
                        "new_value": "Make",
                    }
                ]
            },
        )
        self.component_part_id, self.assignment_id, _ = store.create_part_and_assign_to_section(
            self.project_id,
            section_id,
            {
                "part_number": "COMP-SMOKE",
                "description": "Smoke component",
                "revision": "0",
            },
            1,
        )
        store.save_assembly_bom_components(
            self.project_id,
            assembly_id,
            [{
                "id": str(uuid4()),
                "fishbone_assignment_id": self.assignment_id,
                "quantity": 1,
            }],
        )

    def add_process_pairing_source(self) -> str:
        area_id = str(uuid4())
        pitch_id = str(uuid4())
        yamazumi_element_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES (?, ?, ?, ?, 'Pairing area', ?)""",
                (
                    area_id,
                    self.project_id,
                    self.scenario_id,
                    self.section_id,
                    timestamp,
                ),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES (?, ?, ?, 'P-PAIR', 'Pairing pitch', ?)""",
                (pitch_id, self.project_id, area_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, description, time_s, updated_at)
                   VALUES (?, ?, ?, ?, 'Pair smoke component', 5, ?)""",
                (
                    yamazumi_element_id,
                    self.project_id,
                    area_id,
                    pitch_id,
                    timestamp,
                ),
            )
        return yamazumi_element_id

    def run_process_pairing_page(self, *, select_part: bool = True) -> AppTest:
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/process.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "AppTest smoke"
        app.session_state[
            f"process_yamazumi_source_{self.scenario_id}_{self.section_id}"
            "__editor_instance_0"
        ] = {"selection": {"rows": [0], "columns": [], "cells": []}}
        if select_part:
            app.session_state[
                f"process_part_source_{self.scenario_id}_{self.section_id}"
                "__editor_instance_0"
            ] = {"selection": {"rows": [0], "columns": [], "cells": []}}
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def add_saved_consume(self) -> str:
        work_element_id = str(uuid4())
        group_id = str(uuid4())
        option_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, operation, updated_at)
                   VALUES (?, ?, ?, 5, 'Existing consume', ?)""",
                (work_element_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id,
                    name, selection_rule, quantity, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'Existing consume', 'Use all', 1, ?)""",
                (
                    group_id,
                    self.project_id,
                    self.scenario_id,
                    work_element_id,
                    self.section_id,
                    timestamp,
                ),
            )
            conn.execute(
                """INSERT INTO process_part_options
                   (id, group_id, part_id, updated_at) VALUES (?, ?, ?, ?)""",
                (
                    option_id,
                    group_id,
                    self.component_part_id,
                    timestamp,
                ),
            )
        store.set_process_part_option_handling_type(
            self.project_id,
            self.scenario_id,
            option_id,
            "Consume",
            self.assignment_id,
        )
        return option_id

    def pairing_selectbox(self, app: AppTest, field: str):
        prefix = f"process_pairing_{field}_{self.scenario_id}_{self.section_id}_"
        return next(
            selectbox
            for selectbox in app.selectbox
            if str(selectbox.key).startswith(prefix)
        )

    def submit_part_pairing(self, app: AppTest, requirement: str) -> AppTest:
        requirement_inputs = [
            text_input
            for text_input in app.text_input
            if str(text_input.key).startswith(
                f"process_pairing_requirement_{self.scenario_id}_{self.section_id}_"
            )
        ]
        if requirement_inputs:
            requirement_inputs[0].set_value(requirement)
        submit = next(
            button
            for button in app.button
            if str(button.key).startswith(
                f"process_pairing_submit_{self.scenario_id}_{self.section_id}_"
            )
        )
        return submit.click().run(timeout=30)

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def run_page(self, relative_path: str) -> AppTest:
        app = AppTest.from_file(str(store.ROOT / relative_path), default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "AppTest smoke"
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def test_model_definitions_smoke(self) -> None:
        app = self.run_page("app_pages/models.py")
        self.assertTrue(any(title.value == "Model definitions" for title in app.title))

    def test_overview_takt_unit_controls_smoke(self) -> None:
        app = self.run_page("app_pages/overview.py")
        self.assertTrue(
            any(widget.label == "Default takt unit" for widget in app.selectbox)
        )
        self.assertNotIn("Status", {widget.label for widget in app.selectbox})
        self.assertNotIn(
            "Lead industrial engineer", {widget.label for widget in app.text_input}
        )
        scenario_tables = [
            table.value for table in app.dataframe
            if {"takt", "takt_time_unit"}.issubset(table.value.columns)
        ]
        self.assertTrue(scenario_tables)

    def test_parts_catalog_smoke_with_linked_assembly_part(self) -> None:
        with patch("utils.clipboard_image.clipboard_image", return_value=None):
            app = self.run_page("app_pages/parts.py")
        self.assertTrue(any(title.value == "Parts Catalog" for title in app.title))
        linked_part = store.query(
            """SELECT part.id, part.part_number
               FROM manufacturing_assemblies assembly
               JOIN parts part ON part.id=assembly.catalog_part_id
               WHERE assembly.project_id=? AND assembly.assembly_number='ASM-SMOKE'""",
            (self.project_id,),
        )
        self.assertEqual(linked_part[0]["part_number"], "ASM-SMOKE")
        app.session_state[f"parts_selected_id_{self.project_id}"] = linked_part[0]["id"]
        with patch("utils.clipboard_image.clipboard_image", return_value=None):
            app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertTrue(any(header.value == "Mini-BOM" for header in app.subheader))
        mini_bom_tables = [
            table.value
            for table in app.dataframe
            if "Part number" in table.value.columns
            and "Part name" in table.value.columns
            and "Quantity" in table.value.columns
        ]
        self.assertTrue(mini_bom_tables)
        self.assertFalse(mini_bom_tables[0].empty)

    def test_assemblies_smoke(self) -> None:
        app = self.run_page("app_pages/assemblies.py")
        self.assertTrue(any(title.value == "Assembly grid" for title in app.title))
        section_filter = next(
            widget for widget in app.multiselect if widget.label == "Fishbone sections"
        )
        self.assertIn("__all_active_sections__", section_filter.value)
        subheaders = [subheader.value for subheader in app.subheader]
        details_index = next(
            index
            for index, value in enumerate(subheaders)
            if value.startswith("Assembly details · ")
        )
        catalog_index = subheaders.index("Full assembly catalog and deletion")
        self.assertLess(details_index, catalog_index)
        saved_category = store.assembly_grid_categories(
            self.project_id, self.section_id
        ).iloc[0]
        app.session_state[
            f"assembly_grid_component_v8_{self.project_id}_{self.section_id}"
        ] = {
            "draft": [
                {
                    "id": "",
                    "section_id": self.section_id,
                    "ebom_name": "Top-level packaged unit",
                    "display_name": "Top-level packaged unit",
                    "is_top_level": True,
                    "installed_section_id": "",
                    "sequence": 0,
                    "cells": {},
                },
                {
                    "id": str(saved_category["id"]),
                    "section_id": self.section_id,
                    "ebom_name": str(saved_category["ebom_name"]),
                    "display_name": str(saved_category["display_name"]),
                    "is_top_level": False,
                    "installed_section_id": str(saved_category["installed_section_id"]),
                    "sequence": 10,
                    "cells": {},
                },
                {
                    "id": "",
                    "section_id": self.section_id,
                    "ebom_name": "",
                    "display_name": "",
                    "is_top_level": False,
                    "installed_section_id": "",
                    "sequence": 20,
                    "cells": {},
                },
            ]
        }
        app.run(timeout=30)
        save = next(
            button
            for button in app.button
            if button.key
            == f"assembly_grid_{self.project_id}_{self.section_id}_save_refresh"
        )
        save.click().run(timeout=30)

        self.assertEqual(list(app.exception), [])
        self.assertFalse(
            any(
                "Every assembly-grid category requires" in warning.value
                for warning in app.warning
            )
        )

    def test_sidebar_fishbone_selector_changes_view_without_audit(self) -> None:
        app = AppTest.from_file(
            str(store.ROOT / "streamlit_app.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "AppTest smoke"
        app.run(timeout=30)
        with (
            patch("utils.assembly_grid.assembly_grid", return_value=None),
            patch("utils.clipboard_image._CLIPBOARD_IMAGE", return_value=None),
        ):
            app.switch_page("app_pages/assemblies.py").run(timeout=30)
            self.assertEqual(list(app.exception), [])
            before_count = len(store.audit_history(self.project_id))

            sidebar_selector = next(
                widget
                for widget in app.selectbox
                if widget.label == "Change Fishbone view"
            )
            sidebar_selector.set_value(self.section_id).run(timeout=30)
            self.assertEqual(list(app.exception), [])
            section_filter = next(
                widget for widget in app.multiselect
                if widget.label == "Fishbone sections"
            )
            self.assertEqual(section_filter.value, [self.section_id])
            self.assertEqual(len(store.audit_history(self.project_id)), before_count)

        app.switch_page("app_pages/process.py").run(timeout=30)
        process_section = next(
            widget for widget in app.selectbox
            if widget.label == "Fishbone section"
        )
        self.assertEqual(process_section.value, self.section_id)

    def test_parts_to_fishbone_smoke(self) -> None:
        with patch("utils.fishbone_visual.interactive_fishbone", return_value=None):
            app = self.run_page("app_pages/fishbone.py")
        self.assertTrue(any(title.value == "Parts to fishbone" for title in app.title))

    def test_new_fishbone_section_audits_automatic_yamazumi_area(self) -> None:
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/fishbone.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Automatic area tester"
        with patch("utils.fishbone_visual.interactive_fishbone", return_value=None):
            app.run(timeout=30)
            next(widget for widget in app.text_input if widget.label == "Name").set_value(
                "Automatically linked section"
            )
            next(
                button
                for button in app.button
                if button.label == "Add to Fishbone framework"
            ).click().run(timeout=30)

        self.assertEqual(list(app.exception), [])
        section_id = str(
            store.query(
                "SELECT id FROM assembly_sections WHERE project_id=? AND name=?",
                (self.project_id, "Automatically linked section"),
            )[0]["id"]
        )
        areas = store.query(
            "SELECT id FROM yamazumi_areas WHERE project_id=? AND section_id=?",
            (self.project_id, section_id),
        )
        self.assertEqual(len(areas), len(store.planning_scenarios(self.project_id, True)))
        fishbone_history = store.audit_history(self.project_id, "Fishbone framework")
        yamazumi_history = store.audit_history(self.project_id, "Yamazumi")
        self.assertTrue(
            any(
                "automatic_yamazumi_areas" in str(details)
                and "Automatically linked section" in str(details)
                for details in fishbone_history["details"]
            )
        )
        self.assertTrue(
            any(
                action == "Create areas from Fishbone"
                and editor == "Automatic area tester"
                and "Automatically linked section" in str(details)
                for action, editor, details in zip(
                    yamazumi_history["action"],
                    yamazumi_history["editor_name"],
                    yamazumi_history["details"],
                )
            )
        )

    def test_fishbone_selectors_and_areas_follow_depth_first_order(self) -> None:
        child_id = store.add_assembly_section(
            self.project_id, "Smoke child", "Subassembly", self.section_id, ""
        )
        grandchild_id = store.add_assembly_section(
            self.project_id, "Smoke grandchild", "Subassembly", child_id, ""
        )
        second_main_id = store.add_assembly_section(
            self.project_id, "Smoke second main", "Main spine", None, ""
        )
        expected = [
            "Smoke assembly",
            "Smoke assembly › Smoke child",
            "Smoke assembly › Smoke child › Smoke grandchild",
            "Smoke second main",
        ]

        areas = store.yamazumi_areas(self.project_id, self.scenario_id)
        area_by_section = (
            {
                str(row["section_id"]): str(row["id"])
                for _, row in areas.dropna(subset=["section_id"]).iterrows()
            }
            if "section_id" in areas.columns else {}
        )
        for index, section_id in enumerate(
            [self.section_id, child_id, grandchild_id, second_main_id], start=1
        ):
            area_id = area_by_section.get(section_id)
            if not area_id:
                area_id = store.upsert_yamazumi_area(
                    self.project_id,
                    self.scenario_id,
                    f"Ordered area {index}",
                    section_id,
                )
            if store.yamazumi_pitches(self.project_id, area_id).empty:
                store.add_yamazumi_pitch(
                    self.project_id, area_id, f"P-ORDER-{index}", "Order check"
                )

        with (
            patch("utils.assembly_grid.assembly_grid", return_value=None),
            patch("utils.clipboard_image._CLIPBOARD_IMAGE", return_value=None),
        ):
            assembly_app = self.run_page("app_pages/assemblies.py")
        assembly_sections = next(
            widget
            for widget in assembly_app.multiselect
            if widget.label == "Fishbone sections"
        )
        self.assertEqual(assembly_sections.options, ["All active sections", *expected])

        process_app = self.run_page("app_pages/process.py")
        process_sections = next(
            widget
            for widget in process_app.selectbox
            if widget.label == "Fishbone section"
        )
        self.assertEqual(process_sections.options, expected)

        with patch("utils.fishbone_visual.interactive_fishbone", return_value=None):
            fishbone_app = self.run_page("app_pages/fishbone.py")
        parent_sections = next(
            widget
            for widget in fishbone_app.selectbox
            if widget.label == "Parent assembly"
        )
        self.assertEqual(
            parent_sections.options, ["Product / main assembly", *expected]
        )

        with patch("utils.yamazumi_board._YAMAZUMI_BOARD", return_value=None):
            yamazumi_app = self.run_page("app_pages/yamazumi.py")
        yamazumi_areas = next(
            widget
            for widget in yamazumi_app.selectbox
            if widget.label == "Yamazumi area"
        )
        linked_labels = [
            option.split("Fishbone: ", 1)[1]
            for option in yamazumi_areas.options
            if "Fishbone: " in option
        ]
        self.assertEqual(linked_labels[:4], expected)

        pin_map_app = self.run_page("app_pages/pin_map.py")
        pin_map_areas = next(
            widget
            for widget in pin_map_app.multiselect
            if widget.label == "Yamazumi areas"
        )
        linked_labels = [
            option.split("Fishbone: ", 1)[1]
            for option in pin_map_areas.options
            if "Fishbone: " in option
        ]
        self.assertEqual(linked_labels[:4], expected)

    def test_fishbone_framework_walk_order_and_indentation_are_unchanged(self) -> None:
        child_id = store.add_assembly_section(
            self.project_id,
            "Smoke child",
            "Subassembly",
            self.section_id,
            "",
        )
        store.add_assembly_section(
            self.project_id,
            "Smoke grandchild",
            "Subassembly",
            child_id,
            "",
        )
        store.add_assembly_section(
            self.project_id,
            "Smoke second main",
            "Main spine",
            None,
            "",
        )

        with patch("utils.fishbone_visual.interactive_fishbone", return_value=None):
            app = self.run_page("app_pages/fishbone.py")
        framework = next(
            table.value
            for table in app.dataframe
            if "hierarchy" in table.value.columns
        )
        self.assertEqual(
            list(framework.columns),
            [
                "id", "project_id", "name", "section_type", "parent_id",
                "sequence", "description", "active", "created_at", "updated_at",
                "hierarchy", "parent_assembly", "order_actions", "assemblies_action",
            ],
        )
        visible_bytes = framework[["name", "hierarchy"]].to_csv(
            index=False, lineterminator="\n"
        ).encode("utf-8")
        self.assertEqual(
            visible_bytes,
            (
                "name,hierarchy\n"
                "Smoke assembly,🟦  Smoke assembly\n"
                "Smoke child, └─ 🟧  Smoke child\n"
                "Smoke grandchild,  └─ 🟧  Smoke grandchild\n"
                "Smoke second main,🟦  Smoke second main\n"
            ).encode("utf-8"),
        )

    def test_yamazumi_smoke(self) -> None:
        app = self.run_page("app_pages/yamazumi.py")
        self.assertTrue(any(title.value == "Yamazumi" for title in app.title))

    def test_yamazumi_fishbone_pairing_control_only_appears_when_unlinked(self) -> None:
        linked_section_id = store.add_assembly_section(
            self.project_id, "Automatically paired", "Main spine", None, ""
        )
        linked_area_id = str(
            store.query(
                """SELECT id FROM yamazumi_areas
                   WHERE project_id=? AND scenario_id=? AND section_id=?""",
                (self.project_id, self.scenario_id, linked_section_id),
            )[0]["id"]
        )
        store.add_yamazumi_pitch(
            self.project_id, linked_area_id, "PAIR-001", "Linked pitch"
        )
        unlinked_area_id = store.upsert_yamazumi_area(
            self.project_id, self.scenario_id, "Imported unlinked area"
        )
        store.add_yamazumi_pitch(
            self.project_id, unlinked_area_id, "PAIR-002", "Imported pitch"
        )

        app = AppTest.from_file(
            str(store.ROOT / "app_pages/yamazumi.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Pairing tester"
        area_key = f"yamazumi_area_{self.scenario_id}"
        app.session_state[area_key] = linked_area_id
        with patch("utils.yamazumi_board.yamazumi_board", return_value=None):
            app.run(timeout=30)
            self.assertEqual(list(app.exception), [])
            self.assertNotIn(
                "Linked Fishbone section",
                {widget.label for widget in [*app.text_input, *app.selectbox]},
            )
            self.assertNotIn(
                "Pair with Fishbone section",
                {widget.label for widget in app.selectbox},
            )

            app.session_state[area_key] = unlinked_area_id
            app.run(timeout=30)
            pairing = next(
                widget
                for widget in app.selectbox
                if widget.label == "Pair with Fishbone section"
            )
            pairing.set_value(self.section_id)
            next(
                button
                for button in app.button
                if button.label == "Save area settings"
            ).click().run(timeout=30)

        self.assertEqual(list(app.exception), [])
        self.assertEqual(
            store.query(
                "SELECT section_id FROM yamazumi_areas WHERE id=?",
                (unlinked_area_id,),
            )[0]["section_id"],
            self.section_id,
        )
        self.assertNotIn(
            "Pair with Fishbone section",
            {widget.label for widget in app.selectbox},
        )

    def test_empty_yamazumi_area_prompts_once_per_area_visit(self) -> None:
        first_area_id = store.upsert_yamazumi_area(
            self.project_id, self.scenario_id, "Empty prompt one"
        )
        second_area_id = store.upsert_yamazumi_area(
            self.project_id, self.scenario_id, "Empty prompt two"
        )
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/yamazumi.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "AppTest smoke"
        area_key = f"yamazumi_area_{self.scenario_id}"
        app.session_state[area_key] = first_area_id

        with patch("utils.yamazumi_board.yamazumi_board", return_value=None):
            app.run(timeout=30)
            cancel_key = (
                f"cancel_empty_pitch_setup_{self.project_id}_{self.scenario_id}_"
                f"{first_area_id}"
            )
            self.assertTrue(any(button.key == cancel_key for button in app.button))
            next(button for button in app.button if button.key == cancel_key).click()
            app.run(timeout=30)
            self.assertFalse(any(button.key == cancel_key for button in app.button))

            app.session_state[area_key] = second_area_id
            app.run(timeout=30)
            second_cancel_key = (
                f"cancel_empty_pitch_setup_{self.project_id}_{self.scenario_id}_"
                f"{second_area_id}"
            )
            self.assertTrue(
                any(button.key == second_cancel_key for button in app.button)
            )

            app.session_state[area_key] = first_area_id
            app.run(timeout=30)
            self.assertTrue(any(button.key == cancel_key for button in app.button))

        self.assertEqual(list(app.exception), [])

    def test_empty_yamazumi_prompt_generates_guided_range_and_audit(self) -> None:
        area_id = store.upsert_yamazumi_area(
            self.project_id, self.scenario_id, "Guided range area"
        )
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/yamazumi.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "AppTest smoke"
        app.session_state[f"yamazumi_area_{self.scenario_id}"] = area_id
        surface = "empty_dialog"

        with patch("utils.yamazumi_board.yamazumi_board", return_value=None):
            app.run(timeout=30)
            next(
                item for item in app.text_input
                if item.key == f"yamazumi_line_code_{surface}_{self.project_id}_{area_id}"
            ).set_value("A1")
            next(
                item for item in app.number_input
                if item.key == f"yamazumi_range_stop_{surface}_{self.project_id}_{area_id}"
            ).set_value(3)
            next(
                button for button in app.button
                if button.key == f"generate_yamazumi_range_{surface}_{self.project_id}_{area_id}"
            ).click()
            app.run(timeout=30)

        self.assertEqual(list(app.exception), [])
        saved = store.yamazumi_pitches(self.project_id, area_id)
        self.assertEqual(len(saved), 3)
        self.assertTrue(all(str(value).startswith("A1-") for value in saved["pitch_number"]))
        project = next(
            row for row in store.projects() if str(row["id"]) == self.project_id
        )
        self.assertEqual(project["yamazumi_line_code"], "A1")
        history = store.audit_history(self.project_id, "Yamazumi pitches", limit=1)
        self.assertEqual(history.iloc[0]["action"], "Generate range")
        self.assertIn('"new_project_line_code": "A1"', history.iloc[0]["details"])

    def test_yamazumi_board_receives_op_id_and_feed_ordered_pitches(self) -> None:
        area_id = store.upsert_yamazumi_area(
            self.project_id,
            self.scenario_id,
            "Board order area",
            self.section_id,
        )
        target_id = store.add_yamazumi_pitch(
            self.project_id, area_id, "OP-4", "Receiving pitch"
        )
        store.add_yamazumi_pitch(
            self.project_id, area_id, "OP-1", "First pitch"
        )
        store.add_yamazumi_pitch(
            self.project_id,
            area_id,
            "SA-100",
            "Subassembly feeder",
            pitch_type="Subassembly",
            feeds_into_pitch_id=target_id,
        )
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/yamazumi.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "AppTest smoke"
        app.session_state[f"yamazumi_area_{self.scenario_id}"] = area_id
        before_audit_count = len(store.audit_history(self.project_id))

        with patch(
            "utils.yamazumi_board.yamazumi_board", return_value=None
        ) as board:
            app.run(timeout=30)

        self.assertEqual(list(app.exception), [])
        self.assertEqual(
            [row["pitch_number"] for row in board.call_args.args[0]],
            ["OP-1", "SA-100", "OP-4"],
        )
        self.assertEqual(len(store.audit_history(self.project_id)), before_audit_count)

    def test_yamazumi_time_unit_save_converts_display_without_rewriting_times(self) -> None:
        area_id = store.upsert_yamazumi_area(
            self.project_id,
            self.scenario_id,
            "Minute display area",
            self.section_id,
            90,
        )
        pitch_id = store.add_yamazumi_pitch(
            self.project_id, area_id, "TIME-001", "Minute pitch"
        )
        element_id = store.add_yamazumi_element(
            self.project_id,
            area_id,
            pitch_id,
            {"description": "Thirty second task", "time_s": 30},
        )
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/yamazumi.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "AppTest smoke"
        app.session_state[f"yamazumi_area_{self.scenario_id}"] = area_id
        exported_frames = []

        def capture_export(dataframe, sheet_name="Filtered rows"):
            exported_frames.append((sheet_name, dataframe.copy()))
            return b"test workbook"

        with (
            patch(
                "utils.yamazumi_board.yamazumi_board", return_value=None
            ) as board,
            patch(
                "utils.table_ui.dataframe_to_excel",
                side_effect=capture_export,
            ),
        ):
            app.run(timeout=30)
            selector = next(
                widget
                for widget in app.segmented_control
                if widget.label == "Yamazumi time unit"
            )
            selector.set_value("minutes").run(timeout=30)
            save = next(
                button
                for button in app.button
                if button.key == f"save_yamazumi_time_unit_{self.scenario_id}"
            )
            save.click().run(timeout=30)

        self.assertEqual(list(app.exception), [])
        self.assertEqual(
            store.get_planning_scenario(
                self.project_id, self.scenario_id
            )["yamazumi_time_unit"],
            "minutes",
        )
        self.assertEqual(
            store.query(
                "SELECT takt_override_s FROM yamazumi_areas WHERE id=?",
                (area_id,),
            )[0]["takt_override_s"],
            90,
        )
        self.assertEqual(
            store.query(
                "SELECT time_s FROM yamazumi_elements WHERE id=?", (element_id,)
            )[0]["time_s"],
            30,
        )
        takt_input = next(
            widget
            for widget in app.number_input
            if widget.label == "Yamazumi takt time (seconds)"
        )
        self.assertEqual(takt_input.value, 90.0)
        element_table = next(
            table.value
            for table in app.dataframe
            if "time_s" in table.value.columns
            and "Thirty second task" in set(table.value.get("description", []))
        )
        self.assertEqual(float(element_table.iloc[0]["time_s"]), 0.5)
        self.assertEqual(board.call_args.kwargs["time_unit"], "minutes")
        self.assertEqual(board.call_args.kwargs["takt_time_unit"], "seconds")
        work_exports = [
            frame
            for sheet_name, frame in exported_frames
            if sheet_name == "Yamazumi work elements"
            and "Time (minutes)" in frame.columns
        ]
        self.assertTrue(work_exports)
        self.assertEqual(
            float(work_exports[-1].iloc[0]["Time (minutes)"]), 0.5
        )
        history = store.audit_history(self.project_id, "Yamazumi")
        self.assertTrue(
            any(
                '"old_unit": "seconds"' in str(details)
                and '"new_unit": "minutes"' in str(details)
                for details in history["details"]
            )
        )

    def test_yamazumi_unit_change_waits_for_unsaved_element_edits(self) -> None:
        area_id = store.upsert_yamazumi_area(
            self.project_id,
            self.scenario_id,
            "Unit draft area",
            self.section_id,
            60,
        )
        pitch_id = store.add_yamazumi_pitch(
            self.project_id, area_id, "TIME-002", "Draft pitch"
        )
        store.add_yamazumi_element(
            self.project_id,
            area_id,
            pitch_id,
            {"description": "Editable minute task", "time_s": 30},
        )
        store.update_yamazumi_time_unit(
            self.project_id, self.scenario_id, "minutes"
        )
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/yamazumi.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "AppTest smoke"
        app.session_state[f"yamazumi_area_{self.scenario_id}"] = area_id

        with (
            patch("utils.yamazumi_board.yamazumi_board", return_value=None),
            patch("utils.table_ui.table_has_unsaved_changes", return_value=True),
        ):
            app.run(timeout=30)
            selector = next(
                widget
                for widget in app.segmented_control
                if widget.label == "Yamazumi time unit"
            )
            selector.set_value("hours").run(timeout=30)
            unit_save = next(
                button
                for button in app.button
                if button.key == f"save_yamazumi_time_unit_{self.scenario_id}"
            )
            unit_save.click().run(timeout=30)

            self.assertEqual(
                store.get_planning_scenario(
                    self.project_id, self.scenario_id
                )["yamazumi_time_unit"],
                "minutes",
            )
            self.assertTrue(
                any(
                    "Save or undo Yamazumi work-element edits" in error.value
                    for error in app.error
                )
            )
        self.assertEqual(list(app.exception), [])

    def test_yamazumi_reports_legacy_pitch_address_conflicts_until_corrected(self) -> None:
        first_area_id = store.upsert_yamazumi_area(
            self.project_id,
            self.scenario_id,
            "Pitch conflict first area",
            None,
        )
        second_area_id = store.upsert_yamazumi_area(
            self.project_id,
            self.scenario_id,
            "Pitch conflict second area",
            None,
        )
        store.add_yamazumi_pitch(
            self.project_id, first_area_id, "P-CONFLICT", "First pitch"
        )
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                "DROP TRIGGER IF EXISTS trg_yamazumi_pitch_address_scenario_insert"
            )
            conn.execute(
                "DROP TRIGGER IF EXISTS trg_yamazumi_pitch_address_scenario_update"
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES ('page-legacy-conflict', ?, ?, 'p-conflict',
                           'Second pitch', ?)""",
                (self.project_id, second_area_id, timestamp),
            )
        store.init_db()
        before_audit_count = len(store.audit_history(self.project_id))

        app = AppTest.from_file(
            str(store.ROOT / "app_pages/yamazumi.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "AppTest smoke"
        app.session_state[f"yamazumi_area_{self.scenario_id}"] = first_area_id
        with patch("utils.yamazumi_board._YAMAZUMI_BOARD", return_value=None):
            app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertTrue(
            any(
                "Duplicate pitch addresses must be corrected" in error.value
                for error in app.error
            )
        )
        conflict_table = next(
            table.value
            for table in app.dataframe
            if {"pitch_number", "pitch_name", "area_name"}.issubset(
                table.value.columns
            )
            and len(table.value) == 2
        )
        self.assertEqual(
            set(conflict_table["area_name"]),
            {"Pitch conflict first area", "Pitch conflict second area"},
        )
        self.assertEqual(len(store.audit_history(self.project_id)), before_audit_count)

        store.update_yamazumi_pitch(
            self.project_id,
            second_area_id,
            "page-legacy-conflict",
            {
                "pitch_number": "P-CORRECTED",
                "pitch_name": "Second pitch",
                "status": "Active",
                "model_variants": ["Base"],
                "pitch_type": "Pitch",
                "feeds_into_pitch_id": None,
            },
        )
        with patch("utils.yamazumi_board._YAMAZUMI_BOARD", return_value=None):
            app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertFalse(
            any(
                "Duplicate pitch addresses must be corrected" in error.value
                for error in app.error
            )
        )

    def test_yamazumi_feed_target_required_indicator_tracks_classification(self) -> None:
        area_id = store.upsert_yamazumi_area(
            self.project_id,
            self.scenario_id,
            "Feed indicator area",
            self.section_id,
        )
        target_id = store.add_yamazumi_pitch(
            self.project_id, area_id, "P-1", "Receiving pitch"
        )
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status,
                    sequence, model_variants, pitch_type, feeds_into_pitch_id, updated_at)
                   VALUES ('compat-sub', ?, ?, 'SUB-1', 'Legacy feeder', 'Active',
                           20, '["Base"]', 'Subassembly', NULL, ?)""",
                (self.project_id, area_id, timestamp),
            )
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/yamazumi.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "AppTest smoke"
        app.session_state[f"yamazumi_area_{self.scenario_id}"] = area_id
        with patch("utils.yamazumi_board.yamazumi_board", return_value=None):
            app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        pitch_table = next(
            table.value
            for table in app.dataframe
            if "feed_target_status" in table.value.columns
        )
        status = pitch_table.loc[
            pitch_table["pitch_number"] == "SUB-1", "feed_target_status"
        ].iloc[0]
        self.assertEqual(status, "Feed target required")

        store.update_yamazumi_pitch(
            self.project_id,
            area_id,
            "compat-sub",
            {
                "pitch_number": "SUB-1",
                "pitch_name": "Legacy feeder",
                "status": "Active",
                "model_variants": ["Base"],
                "pitch_type": "Subassembly",
                "feeds_into_pitch_id": target_id,
            },
        )
        with patch("utils.yamazumi_board.yamazumi_board", return_value=None):
            app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        pitch_table = next(
            table.value
            for table in app.dataframe
            if "feed_target_status" in table.value.columns
        )
        status = pitch_table.loc[
            pitch_table["pitch_number"] == "SUB-1", "feed_target_status"
        ].iloc[0]
        self.assertEqual(status, "")

    def test_process_at_a_glance_smoke(self) -> None:
        app = self.run_page("app_pages/process.py")
        self.assertTrue(any(title.value == "Process at a Glance" for title in app.title))
        process_table = next(
            editor.value
            for editor in app.dataframe
            if "ergonomics_risk" in editor.value.columns
        )
        self.assertIn("details", process_table.columns)
        self.assertNotIn(
            "Status for selected",
            {widget.label for widget in app.selectbox},
        )
        self.assertNotIn("Status", {widget.label for widget in app.multiselect})
        self.assertTrue(
            {
                "op_id",
                "description",
                "output_assembly_number",
                "tool",
                "location",
                "unit_orientation",
                "conveyor_height_in",
            }.issubset(process_table.columns)
        )
        self.assertFalse(
            {
                "Total work content",
                "Target takt",
                "Pitches represented",
            }
            & {metric.label for metric in app.metric}
        )
        self.assertFalse(
            any(
                subheader.value == "Draft Yamazumi by pitch"
                for subheader in app.subheader
            )
        )

    def test_process_at_a_glance_displays_live_ergonomics_risk_tag(self) -> None:
        work_element_id = "process-ergo-risk-step"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, updated_at)
                   VALUES (?, ?, ?, 950, 'P-950', 'Lift risk item', ?)""",
                (work_element_id, self.project_id, self.scenario_id, timestamp),
            )
        review_id = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "work_element_id": work_element_id,
                "status": "Open",
                "risk_classification": "Red",
            },
        )["id"]

        app = self.run_page("app_pages/process.py")
        process_table = next(
            editor.value
            for editor in app.dataframe
            if "ergonomics_risk" in editor.value.columns
        )
        risk_row = process_table.loc[process_table["id"].eq(work_element_id)].iloc[0]
        self.assertEqual(
            list(risk_row["ergonomics_risk"]), ["Ergo Risk"]
        )

        store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "id": review_id,
                "work_element_id": work_element_id,
                "status": "Validation",
                "risk_classification": "Red",
            },
        )
        app = self.run_page("app_pages/process.py")
        process_table = next(
            editor.value
            for editor in app.dataframe
            if "ergonomics_risk" in editor.value.columns
        )
        risk_row = process_table.loc[process_table["id"].eq(work_element_id)].iloc[0]
        self.assertEqual(list(risk_row["ergonomics_risk"]), [])

    def test_process_pairing_single_use_defaults_consume_and_auto_selects(self) -> None:
        self.add_process_pairing_source()
        app = self.run_process_pairing_page()
        handling_key = (
            f"process_pairing_handling_{self.scenario_id}_{self.section_id}_"
        )
        handling = next(
            selectbox
            for selectbox in app.selectbox
            if str(selectbox.key).startswith(handling_key)
        )
        location = next(
            selectbox
            for selectbox in app.selectbox
            if str(selectbox.key).startswith(
                f"process_pairing_location_{self.scenario_id}_{self.section_id}_"
            )
        )
        self.assertEqual(handling.value, "Consume")
        self.assertEqual(location.value, self.assignment_id)
        self.assertTrue(location.disabled)
        self.assertFalse(any(
            str(text_input.key).startswith(
                f"process_pairing_requirement_{self.scenario_id}_{self.section_id}_"
            )
            for text_input in app.text_input
        ))
        app = self.pairing_selectbox(app, "rule").select("Optional").run(timeout=30)
        self.assertTrue(any(
            str(text_input.key).startswith(
                f"process_pairing_requirement_{self.scenario_id}_{self.section_id}_"
            )
            for text_input in app.text_input
        ))

    def test_process_pairing_without_parts_remains_unclassified(self) -> None:
        self.add_process_pairing_source()
        app = self.run_process_pairing_page(select_part=False)
        add_without_parts = next(
            button
            for button in app.button
            if str(button.key).startswith(
                f"add_work_only_{self.scenario_id}_"
            )
        )
        app = add_without_parts.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        process_step = store.query(
            """SELECT id FROM work_elements
               WHERE project_id=? AND scenario_id=? AND operation='Pair smoke component'""",
            (self.project_id, self.scenario_id),
        )
        self.assertEqual(len(process_step), 1)
        option_count = store.query(
            """SELECT COUNT(*) AS count
               FROM process_part_options option
               JOIN process_part_groups group_row ON group_row.id=option.group_id
               WHERE group_row.project_id=? AND group_row.scenario_id=?
                 AND group_row.work_element_id=?""",
            (self.project_id, self.scenario_id, process_step[0]["id"]),
        )[0]["count"]
        self.assertEqual(option_count, 0)

    def test_process_pairing_multiple_uses_requires_explicit_location(self) -> None:
        self.add_process_pairing_source()
        store.assign_parts_to_section(
            self.project_id,
            [self.component_part_id],
            self.section_id,
            "Second installation",
            allow_additional_use=True,
            quantities_by_part={self.component_part_id: 2},
        )
        app = self.run_process_pairing_page()
        location = self.pairing_selectbox(app, "location")
        self.assertIsNone(location.value)
        self.assertFalse(location.disabled)
        self.assertEqual(len(location.options), 2)

        app = self.submit_part_pairing(app, "Explicit use required")
        self.assertTrue(
            any(
                "Choose a Use / installation location" in error.value
                for error in app.error
            )
        )

    def test_process_pairing_saves_explicit_location_and_audits_editor(self) -> None:
        self.add_process_pairing_source()
        store.assign_parts_to_section(
            self.project_id,
            [self.component_part_id],
            self.section_id,
            "Second installation",
            allow_additional_use=True,
            quantities_by_part={self.component_part_id: 2},
        )
        second_assignment_id = str(
            store.query(
                """SELECT id FROM fishbone_part_assignments
                   WHERE project_id=? AND part_id=? AND section_id=?
                     AND use_description='Second installation'""",
                (self.project_id, self.component_part_id, self.section_id),
            )[0]["id"]
        )
        app = self.run_process_pairing_page()
        app = self.pairing_selectbox(app, "location").select_index(1).run(timeout=30)
        self.assertEqual(
            self.pairing_selectbox(app, "location").value,
            second_assignment_id,
        )
        app = self.submit_part_pairing(app, "Explicit placement")
        self.assertEqual(list(app.exception), [])
        saved = store.query(
            """SELECT option.handling_type, option.fishbone_assignment_id
               FROM process_part_options option
               JOIN process_part_groups group_row ON group_row.id=option.group_id
               WHERE group_row.project_id=? AND group_row.scenario_id=?
                  AND group_row.name='Smoke component'""",
            (self.project_id, self.scenario_id),
        )
        self.assertEqual(saved[0]["handling_type"], "Consume")
        self.assertEqual(saved[0]["fishbone_assignment_id"], second_assignment_id)
        process_table = next(
            editor.value
            for editor in app.dataframe
            if "ergonomics_risk" in editor.value.columns
        )
        handling = process_table.loc[
            process_table["work_element"].eq("Pair smoke component"), "handling"
        ].iloc[0]
        self.assertEqual(list(handling), ["Consume"])
        audit = store.query(
            """SELECT editor_name, details FROM audit_log
               WHERE project_id=? AND table_name='Process part pairings'
               ORDER BY created_at DESC LIMIT 1""",
            (self.project_id,),
        )[0]
        self.assertEqual(audit["editor_name"], "AppTest smoke")
        self.assertIn(second_assignment_id, audit["details"])

    def test_process_pairing_can_switch_to_handle(self) -> None:
        self.add_saved_consume()
        self.add_process_pairing_source()
        app = self.run_process_pairing_page()
        handling = self.pairing_selectbox(app, "handling")
        app = handling.select("Handle").run(timeout=30)
        self.assertEqual(self.pairing_selectbox(app, "handling").value, "Handle")
        location = self.pairing_selectbox(app, "location")
        self.assertTrue(any("Available for Handle" in option for option in location.options))

    def test_process_pairing_surfaces_consume_allowance_error(self) -> None:
        self.add_saved_consume()
        self.add_process_pairing_source()
        app = self.run_process_pairing_page()
        self.assertTrue(
            any(
                "Unavailable for Consume" in option
                for option in self.pairing_selectbox(app, "location").options
            )
        )
        app = self.submit_part_pairing(app, "Consume blocked")
        self.assertTrue(
            any(
                self.assignment_id in error.value
                and "fully consumed elsewhere in this scenario" in error.value
                for error in app.error
            )
        )
        source = store.query(
            """SELECT process_element_id, process_sync_status
               FROM yamazumi_elements WHERE description='Pair smoke component'"""
        )[0]
        self.assertIsNone(source["process_element_id"])
        self.assertNotEqual(source["process_sync_status"], "Synced")

    def test_process_pairing_surfaces_handle_prerequisite_error(self) -> None:
        self.add_process_pairing_source()
        app = self.run_process_pairing_page()
        app = self.pairing_selectbox(app, "handling").select("Handle").run(timeout=30)
        app = self.submit_part_pairing(app, "Handle blocked")
        self.assertTrue(
            any(
                self.assignment_id in error.value
                and "must be Consumed before it can be Handled" in error.value
                for error in app.error
            )
        )
        source = store.query(
            """SELECT process_element_id, process_sync_status
               FROM yamazumi_elements WHERE description='Pair smoke component'"""
        )[0]
        self.assertIsNone(source["process_element_id"])
        self.assertNotEqual(source["process_sync_status"], "Synced")


if __name__ == "__main__":
    unittest.main()
