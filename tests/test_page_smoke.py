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
        if store.assembly_sections(self.project_id).empty:
            store.add_assembly_section(
                self.project_id, "Smoke assembly", "Main spine", None, ""
            )
        section_id = str(store.assembly_sections(self.project_id).iloc[0]["id"])
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
        parts = store.project_table("parts", self.project_id, "part_number")
        if not parts.empty:
            part_id = str(parts.iloc[0]["id"])
            store.assign_parts_to_section(
                self.project_id, [part_id], section_id, allow_additional_use=True
            )
            assignment = store.fishbone_part_assignments(self.project_id).loc[
                lambda rows: rows["part_id"].astype(str).eq(part_id)
                & rows["section_id"].astype(str).eq(section_id)
            ].iloc[-1]
            store.save_assembly_bom_components(
                self.project_id,
                assembly_id,
                [
                    {
                        "id": str(uuid4()),
                        "fishbone_assignment_id": str(assignment["id"]),
                        "quantity": 1,
                    }
                ],
            )

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def run_page(self, relative_path: str) -> AppTest:
        app = AppTest.from_file(str(store.ROOT / relative_path), default_timeout=30)
        app.session_state["project_id"] = self.project_id
        app.session_state["current_editor"] = "AppTest smoke"
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def test_model_definitions_smoke(self) -> None:
        app = self.run_page("app_pages/models.py")
        self.assertTrue(any(title.value == "Model definitions" for title in app.title))

    def test_assemblies_smoke(self) -> None:
        app = self.run_page("app_pages/assemblies.py")
        self.assertTrue(any(title.value == "Assemblies" for title in app.title))


if __name__ == "__main__":
    unittest.main()
