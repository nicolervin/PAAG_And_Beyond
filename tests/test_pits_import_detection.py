from __future__ import annotations

import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pandas as pd

from utils import store
from utils.excel_io import has_pits_id_sheets, parse_pits_id_workbook


class PitsImportDetectionTests(unittest.TestCase):
    def test_import_creates_catalog_parts_from_tracker_rows(self):
        database_path = store.DATA_DIR / f"test_pits_catalog_{uuid4()}.db"
        database_patch = patch.object(store, "DB_PATH", database_path)
        database_patch.start()
        store.init_db()
        project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])

        try:
            records = [{
                "pits_id": "1201",
                "part_number": "P-1201",
                "description": "Imported support part",
                "revision": "Rev A : PreRelease",
                "source_code": "3",
                "used_bom": "Yes",
                "status": "Active",
                "subsystem": "Power",
                "design_maturity": "Prototype",
                "comments": "Created from import",
                "workstation": "Line 1",
                "source_row": 2,
                "source_payload": {
                    "ID Number": "1201",
                    "Part Number": "P-1201",
                    "Description": "Imported support part",
                    "Used BOM": "Yes",
                    "Base Info Status": "Active",
                    "Subsystem": "Power",
                    "Design Maturity": "Prototype",
                    "Comments": "Created from import",
                    "Factory Workstation Location": "Line 1",
                },
            }]

            summary = store.import_pits_id_snapshot(project_id, records, [])

            self.assertEqual(summary["new"], 1)
            catalog_rows = store.query(
                "SELECT part_number, description, source, revision, source_code FROM parts WHERE project_id=?",
                (project_id,),
            )
            match = next((row for row in catalog_rows if row["part_number"] == "P-1201"), None)
            self.assertIsNotNone(match)
            self.assertEqual(match["description"], "Imported support part")
            self.assertEqual(match["source"], "PITS snapshot")
            self.assertEqual(match["revision"], "Rev A : PreRelease")
            self.assertEqual(match["source_code"], "3")
        finally:
            database_patch.stop()
            for suffix in ("", "-wal", "-shm"):
                Path(f"{database_path}{suffix}").unlink(missing_ok=True)

    def test_import_excludes_parts_not_used_in_bom(self):
        database_path = store.DATA_DIR / f"test_pits_bom_filter_{uuid4()}.db"
        database_patch = patch.object(store, "DB_PATH", database_path)
        database_patch.start()
        store.init_db()
        project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        scenario_id = str(store.planning_scenarios(project_id)[0]["id"])

        try:
            records = [
                {
                    "pits_id": "1202",
                    "part_number": "P-USED",
                    "description": "Used part",
                    "used_bom": "Y",
                    "status": "Active",
                    "subsystem": "Power",
                    "design_maturity": "Prototype",
                    "comments": "",
                    "workstation": "Line 1",
                    "source_row": 2,
                    "source_payload": {"ID Number": "1202", "Part Number": "P-USED", "Used BOM": "Y"},
                },
                {
                    "pits_id": "1203",
                    "part_number": "P-EXCLUDED",
                    "description": "Excluded part",
                    "used_bom": "N",
                    "status": "Inactive",
                    "subsystem": "Power",
                    "design_maturity": "Prototype",
                    "comments": "",
                    "workstation": "Line 1",
                    "source_row": 3,
                    "source_payload": {"ID Number": "1203", "Part Number": "P-EXCLUDED", "Used BOM": "N"},
                },
            ]

            store.import_pits_id_snapshot(project_id, records, [], scenario_id=scenario_id)

            catalog_rows = store.query(
                "SELECT part_number FROM parts WHERE project_id=? AND source='PITS snapshot'",
                (project_id,),
            )
            self.assertEqual(
                {row["part_number"] for row in catalog_rows},
                {"P-USED", "P-EXCLUDED"},
            )
            excluded_id = store.query(
                "SELECT id FROM parts WHERE project_id=? AND part_number=?",
                (project_id, "P-EXCLUDED"),
            )[0]["id"]
            self.assertEqual(
                store.query(
                    """SELECT active FROM part_scenario_activity
                       WHERE project_id=? AND scenario_id=? AND part_id=?""",
                    (project_id, scenario_id, excluded_id),
                )[0]["active"],
                0,
            )
            self.assertEqual(
                store.query(
                    "SELECT part_number FROM pits_records WHERE project_id=? AND pits_id=?",
                    (project_id, "1203"),
                )[0]["part_number"],
                "P-EXCLUDED",
            )
        finally:
            database_patch.stop()
            for suffix in ("", "-wal", "-shm"):
                Path(f"{database_path}{suffix}").unlink(missing_ok=True)

    def test_reimport_updates_catalog_revision_and_source_code(self):
        database_path = store.DATA_DIR / f"test_pits_live_updates_{uuid4()}.db"
        database_patch = patch.object(store, "DB_PATH", database_path)
        database_patch.start()
        store.init_db()
        project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])

        try:
            base_record = {
                "pits_id": "1204",
                "part_number": "P-LIVE",
                "description": "Live part",
                "used_bom": "Y",
                "status": "Active",
                "subsystem": "Power",
                "design_maturity": "Prototype",
                "comments": "",
                "workstation": "Line 1",
                "source_row": 2,
                "source_payload": {"ID Number": "1204"},
            }
            store.import_pits_id_snapshot(
                project_id,
                [{**base_record, "revision": "Rev A", "source_code": "1"}],
                [],
            )
            store.import_pits_id_snapshot(
                project_id,
                [{**base_record, "revision": "Rev B", "source_code": "8"}],
                [],
            )

            row = store.query(
                "SELECT revision, source_code FROM parts WHERE project_id=? AND part_number=?",
                (project_id, "P-LIVE"),
            )[0]
            self.assertEqual(row["revision"], "Rev B")
            self.assertEqual(row["source_code"], "8")
        finally:
            database_patch.stop()
            for suffix in ("", "-wal", "-shm"):
                Path(f"{database_path}{suffix}").unlink(missing_ok=True)

    def test_blank_pits_revision_stays_blank_in_catalog(self):
        database_path = store.DATA_DIR / f"test_pits_blank_revision_{uuid4()}.db"
        database_patch = patch.object(store, "DB_PATH", database_path)
        database_patch.start()
        store.init_db()
        project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])

        try:
            store.import_pits_id_snapshot(
                project_id,
                [{
                    "pits_id": "1205",
                    "part_number": "P-BLANK-REV",
                    "description": "Blank revision part",
                    "revision": "",
                    "source_code": "3",
                    "used_bom": "Y",
                    "status": "Active",
                    "subsystem": "Power",
                    "design_maturity": "Prototype",
                    "comments": "",
                    "workstation": "Line 1",
                    "source_row": 2,
                    "source_payload": {"ID Number": "1205", "Part Number": "P-BLANK-REV"},
                }],
                [],
            )

            revision = store.query(
                "SELECT revision FROM parts WHERE project_id=? AND part_number=?",
                (project_id, "P-BLANK-REV"),
            )[0]["revision"]
            self.assertEqual(revision, "")
        finally:
            database_patch.stop()
            for suffix in ("", "-wal", "-shm"):
                Path(f"{database_path}{suffix}").unlink(missing_ok=True)

    def test_existing_pits_zero_revision_is_repaired_from_source_payload(self):
        database_path = store.DATA_DIR / f"test_pits_revision_repair_{uuid4()}.db"
        database_patch = patch.object(store, "DB_PATH", database_path)
        database_patch.start()
        store.init_db()
        project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])

        try:
            store.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, revision, source, source_code, updated_at)
                   VALUES (?, ?, ?, ?, '0', 'PITS snapshot', '1', ?)""",
                (str(uuid4()), project_id, "P-OLD", "Old imported part", store.now_iso()),
            )
            store.execute(
                """INSERT INTO pits_records
                   (id, project_id, pits_id, part_number, description, source_payload,
                    source_hash, first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()), project_id, "1206", "P-OLD", "Old imported part",
                    "{\"part_number\": \"P-OLD\"}", "old-hash", store.now_iso(), store.now_iso(),
                ),
            )

            store.init_db()

            row = store.query(
                "SELECT revision, source_code FROM parts WHERE project_id=? AND part_number=?",
                (project_id, "P-OLD"),
            )[0]
            self.assertEqual(row["revision"], "")
            self.assertEqual(row["source_code"], "")
        finally:
            database_patch.stop()
            for suffix in ("", "-wal", "-shm"):
                Path(f"{database_path}{suffix}").unlink(missing_ok=True)

    def test_detects_nonstandard_tracker_and_model_sheet_names(self):
        tracker = pd.DataFrame(
            [
                ["PITS Data", "", "", "", "", "", "", ""],
                ["ID Number", "Part No", "Description", "Used BOM", "Base Info Status", "Subsystem", "Design Maturity", "Comments", "Factory Workstation Location"],
                ["1001", "P-100", "Test part", "Yes", "Active", "Power", "Prototype", "ok", "Line 1"],
            ]
        )
        models = pd.DataFrame(
            [
                ["", "", "", "", "", "", "", "", ""],
                ["Model Number", "Item", "Platform Size", "Package Type", "Appearance", "Base Model", "EAU", "Evaluate in Fishbone", "Yamazumi"],
                ["M-01", "C1", "Small", "Box", "Appearance", "Base", "100", "Yes", "Yes"],
            ]
        )

        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            tracker.to_excel(writer, sheet_name="PITS Tracker", index=False, header=False)
            models.to_excel(writer, sheet_name="Model Definitions", index=False, header=False)
        buffer.seek(0)

        uploaded = type("Uploaded", (), {"name": "sample.xlsm", "getvalue": lambda self: buffer.getvalue()})()

        self.assertTrue(has_pits_id_sheets(uploaded))

        records, model_rows = parse_pits_id_workbook(uploaded)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["pits_id"], "1001")
        self.assertEqual(records[0]["part_number"], "P-100")
        self.assertEqual(len(model_rows), 1)
        self.assertEqual(model_rows[0]["model_number"], "M-01")

    def test_reads_source_code_from_column_t_and_revision_from_column_bl(self):
        header = [""] * 64
        values = [""] * 64
        header[0] = "ID Number"
        header[1] = "Part Number"
        header[2] = "Description"
        header[3] = "Used BOM"
        header[19] = "Source Code"
        header[63] = "Windchill Status"
        values[0] = "1002"
        values[1] = "P-200"
        values[2] = "Column mapped part"
        values[3] = "Y"
        values[19] = "2.4"
        values[63] = "Rev B : Production Released"
        tracker = pd.DataFrame([["PITS Data", *([""] * 63)], header, values])
        models = pd.DataFrame([
            ["Model Number", "Item"],
            ["M-02", "C2"],
        ])

        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            tracker.to_excel(writer, sheet_name="PITS Tracker", index=False, header=False)
            models.to_excel(writer, sheet_name="Model Definitions", index=False, header=False)
        buffer.seek(0)
        uploaded = type("Uploaded", (), {"name": "columns.xlsm", "getvalue": lambda self: buffer.getvalue()})()

        records, _ = parse_pits_id_workbook(uploaded)

        self.assertEqual(records[0]["source_code"], "2.4")
        self.assertEqual(records[0]["revision"], "Rev B : Production Released")


if __name__ == "__main__":
    unittest.main()
