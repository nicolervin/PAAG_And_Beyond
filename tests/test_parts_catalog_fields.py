from __future__ import annotations

from contextlib import closing
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from utils import store
from utils.project_transfer import export_project_package, import_project_package


class PartsCatalogFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_parts_catalog_fields_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def edited_parts(self):
        return store.project_table("parts", self.project_id, "part_number").copy()

    def test_new_row_display_only_columns_have_blank_defaults(self) -> None:
        page_source = (store.ROOT / "app_pages" / "parts.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"Photo status",\n            default="",', page_source)
        self.assertIn('st.column_config.TextColumn("Source", default="")', page_source)
        self.assertIn(
            'st.column_config.TextColumn("Updated", default="")', page_source
        )
        self.assertIn('parts_to_save.loc[new_row_mask, "source"] = "Manual"', page_source)

    def test_legacy_parts_table_migrates_without_rewriting_existing_data(self) -> None:
        legacy_path = store.DATA_DIR / f"test_parts_catalog_legacy_{uuid4()}.db"
        try:
            with closing(sqlite3.connect(legacy_path)) as conn:
                conn.execute(
                    """CREATE TABLE parts (
                       id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                       part_number TEXT NOT NULL, description TEXT DEFAULT '',
                       quantity REAL DEFAULT 1, revision TEXT DEFAULT '0',
                       source TEXT DEFAULT 'Manual', image_path TEXT DEFAULT '',
                       model_applicability TEXT DEFAULT 'All', notes TEXT DEFAULT '',
                       weight_lb REAL, updated_at TEXT NOT NULL,
                       UNIQUE(project_id, part_number))"""
                )
                conn.execute(
                    """INSERT INTO parts
                       (id, project_id, part_number, description, updated_at)
                       VALUES ('legacy-part', 'legacy-project', 'LEGACY-1',
                               'Preserve me', '2026-09-17T00:00:00+00:00')"""
                )
                conn.commit()
            with patch.object(store, "DB_PATH", legacy_path):
                store.init_db()
                store.init_db()
                migrated = store.query(
                    """SELECT description, technology_engineer, pits_tracker_number,
                              source_code, official_windchill_part_name, make_buy
                       FROM parts WHERE id='legacy-part'"""
                )[0]
            self.assertEqual(migrated["description"], "Preserve me")
            self.assertEqual(
                {
                    migrated["technology_engineer"], migrated["pits_tracker_number"],
                    migrated["source_code"], migrated["official_windchill_part_name"],
                    migrated["make_buy"],
                },
                {""},
            )
        finally:
            for suffix in ("", "-wal", "-shm"):
                Path(f"{legacy_path}{suffix}").unlink(missing_ok=True)

    def test_schema_upgrade_is_repeatable_and_fields_round_trip(self) -> None:
        store.init_db()
        columns = {
            row["name"] for row in store.query("PRAGMA table_info(parts)")
        }
        self.assertTrue(
            {
                "technology_engineer",
                "pits_tracker_number",
                "source_code",
                "official_windchill_part_name",
                "make_buy",
            }.issubset(columns)
        )

        edited = self.edited_parts()
        edited.loc[0, "technology_engineer"] = "  Alex Engineer  "
        edited.loc[0, "pits_tracker_number"] = "  00127  "
        edited.loc[0, "source_code"] = "4"
        edited.loc[0, "official_windchill_part_name"] = "  Official housing  "
        edited.loc[0, "make_buy"] = "Buy"
        part_id = str(edited.loc[0, "id"])
        store.update_part_rows(
            self.project_id,
            edited,
            scenario_id=self.scenario_id,
            activity_by_part={str(row["id"]): True for _, row in edited.iterrows()},
        )

        saved = store.query(
            """SELECT technology_engineer, pits_tracker_number, source_code,
                      official_windchill_part_name, make_buy
               FROM parts WHERE id=?""",
            (part_id,),
        )[0]
        self.assertEqual(saved["technology_engineer"], "Alex Engineer")
        self.assertEqual(saved["pits_tracker_number"], "00127")
        self.assertEqual(saved["source_code"], "4")
        self.assertEqual(saved["official_windchill_part_name"], "Official housing")
        self.assertEqual(saved["make_buy"], "Buy")

        edited = self.edited_parts()
        selected = edited["id"].astype(str) == part_id
        for field in (
            "technology_engineer", "pits_tracker_number", "source_code",
            "official_windchill_part_name", "make_buy",
        ):
            edited.loc[selected, field] = ""
        store.update_part_rows(self.project_id, edited)
        cleared = store.query(
            "SELECT technology_engineer, pits_tracker_number, source_code, official_windchill_part_name, make_buy FROM parts WHERE id=?",
            (part_id,),
        )[0]
        self.assertEqual(set(cleared.values()), {""})

    def test_validation_rejects_duplicate_tracker_and_invalid_controlled_values(self) -> None:
        edited = self.edited_parts()
        edited.loc[0, "pits_tracker_number"] = "PITS-7"
        edited.loc[1, "pits_tracker_number"] = " PITS-7 "
        with self.assertRaisesRegex(ValueError, "Duplicate PITS Tracker numbers.*PITS-7"):
            store.update_part_rows(self.project_id, edited)

        edited = self.edited_parts()
        edited.loc[0, "pits_tracker_number"] = "HIDDEN-1"
        store.update_part_rows(self.project_id, edited)
        filtered = self.edited_parts().iloc[[1]].copy()
        filtered.loc[filtered.index[0], "pits_tracker_number"] = " HIDDEN-1 "
        with self.assertRaisesRegex(ValueError, "Duplicate PITS Tracker numbers.*HIDDEN-1"):
            store.update_part_rows(self.project_id, filtered)

        edited = self.edited_parts()
        edited.loc[0, "source_code"] = "9"
        with self.assertRaisesRegex(ValueError, "Source Code"):
            store.update_part_rows(self.project_id, edited)

        edited = self.edited_parts()
        edited.loc[0, "make_buy"] = "Outsource"
        with self.assertRaisesRegex(ValueError, "Make vs Buy"):
            store.update_part_rows(self.project_id, edited)

    def test_upsert_without_new_fields_preserves_reviewed_values(self) -> None:
        part = self.edited_parts().iloc[0]
        store.upsert_part(
            self.project_id,
            {
                "part_number": str(part["part_number"]),
                "description": "Reviewed",
                "technology_engineer": "Taylor",
                "pits_tracker_number": "0008",
                "source_code": "8",
                "official_windchill_part_name": "Windchill name",
                "make_buy": "Make",
            },
        )
        store.upsert_part(
            self.project_id,
            {"part_number": str(part["part_number"]), "description": "MBOM refresh"},
        )
        legacy_contract = self.edited_parts()[
            [
                "id", "part_number", "description", "quantity", "revision",
                "model_applicability", "notes",
            ]
        ].copy()
        store.update_part_rows(self.project_id, legacy_contract)
        saved = store.query("SELECT * FROM parts WHERE id=?", (str(part["id"]),))[0]
        self.assertEqual(saved["technology_engineer"], "Taylor")
        self.assertEqual(saved["pits_tracker_number"], "0008")
        self.assertEqual(saved["source_code"], "8")
        self.assertEqual(saved["official_windchill_part_name"], "Windchill name")
        self.assertEqual(saved["make_buy"], "Make")

    def test_project_transfer_round_trips_new_fields(self) -> None:
        part = self.edited_parts().iloc[0]
        store.upsert_part(
            self.project_id,
            {
                "part_number": str(part["part_number"]),
                "description": str(part["description"]),
                "technology_engineer": "Morgan",
                "pits_tracker_number": "0042",
                "source_code": "2",
                "official_windchill_part_name": "Transferred name",
                "make_buy": "Buy",
            },
        )
        package = export_project_package(self.project_id, "Test editor")
        imported = import_project_package(package["data"], "Create new", "Test editor")
        copied = store.query(
            """SELECT technology_engineer, pits_tracker_number, source_code,
                      official_windchill_part_name, make_buy
               FROM parts WHERE project_id=? AND part_number=?""",
            (imported["project_id"], str(part["part_number"])),
        )[0]
        self.assertEqual(
            copied,
            {
                "technology_engineer": "Morgan",
                "pits_tracker_number": "0042",
                "source_code": "2",
                "official_windchill_part_name": "Transferred name",
                "make_buy": "Buy",
            },
        )


if __name__ == "__main__":
    unittest.main()
