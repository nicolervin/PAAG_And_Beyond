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
        _, assignment_id, _ = store.create_part_and_assign_to_section(
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
                "fishbone_assignment_id": assignment_id,
                "quantity": 1,
            }],
        )

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

    def test_parts_to_fishbone_smoke(self) -> None:
        app = self.run_page("app_pages/fishbone.py")
        self.assertTrue(any(title.value == "Parts to fishbone" for title in app.title))

    def test_yamazumi_smoke(self) -> None:
        app = self.run_page("app_pages/yamazumi.py")
        self.assertTrue(any(title.value == "Yamazumi" for title in app.title))

    def test_process_at_a_glance_smoke(self) -> None:
        app = self.run_page("app_pages/process.py")
        self.assertTrue(any(title.value == "Process at a Glance" for title in app.title))


if __name__ == "__main__":
    unittest.main()
