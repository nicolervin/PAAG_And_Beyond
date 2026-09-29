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
                "technology_engineer": "Alex Engineer",
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
                    "part_code": "NP",
                    "Design Maturity": "Prototype",
                    "Comments": "Created from import",
                    "Factory Workstation Location": "Line 1",
                },
            }]

            summary = store.import_pits_id_snapshot(project_id, records, [])

            self.assertEqual(summary["new"], 1)
            catalog_rows = store.query(
                """SELECT part_number, description, source, revision, source_code,
                          technology_engineer,
                          pits_tracker_number
                   FROM parts WHERE project_id=?""",
                (project_id,),
            )
            match = next((row for row in catalog_rows if row["part_number"] == "P-1201"), None)
            self.assertIsNotNone(match)
            self.assertEqual(match["description"], "Imported support part")
            self.assertEqual(match["source"], "PITS snapshot")
            self.assertEqual(match["revision"], "Rev A : PreRelease")
            self.assertEqual(match["source_code"], "3")
            self.assertEqual(match["technology_engineer"], "Alex Engineer")
            self.assertEqual(match["pits_tracker_number"], "1201")
            catalog_match = store.project_table("parts", project_id, "part_number")
            catalog_match = catalog_match.loc[catalog_match["part_number"] == "P-1201"].iloc[0]
            self.assertEqual(catalog_match["subsystem"], "Power")
            self.assertEqual(catalog_match["part_code"], "NP")

            with store.connection() as conn:
                conn.execute(
                    """UPDATE parts SET pits_tracker_number=''
                       WHERE project_id=? AND part_number=?""",
                    (project_id, "P-1201"),
                )
            store.import_pits_id_snapshot(project_id, records, [])
            restored = store.query(
                """SELECT pits_tracker_number FROM parts
                   WHERE project_id=? AND part_number=?""",
                (project_id, "P-1201"),
            )[0]
            self.assertEqual(restored["pits_tracker_number"], "1201")
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

    def test_import_leaves_catalog_pits_id_blank_when_part_number_has_multiple_ids(self):
        database_path = store.DATA_DIR / f"test_pits_duplicate_part_{uuid4()}.db"
        database_patch = patch.object(store, "DB_PATH", database_path)
        database_patch.start()
        store.init_db()
        project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])

        try:
            records = []
            for source_row, pits_id in enumerate(("1204", "1205"), start=2):
                records.append({
                    "pits_id": pits_id,
                    "part_number": "P-REPEATED",
                    "description": "Repeated source part",
                    "used_bom": "Y",
                    "status": "Active",
                    "subsystem": "Power",
                    "design_maturity": "Prototype",
                    "comments": "",
                    "workstation": "Line 1",
                    "source_row": source_row,
                    "_bom_pits_ids": ["1204", "1205"],
                    "source_payload": {
                        "ID Number": pits_id,
                        "Part Number": "P-REPEATED",
                    },
                })

            summary = store.import_pits_id_snapshot(project_id, records, [])

            self.assertEqual(summary["pits_ids_linked"], 0)
            self.assertEqual(summary["pits_id_conflicts"], 1)
            self.assertEqual(summary["bom_pits_id_conflicts"], 1)
            catalog_row = store.query(
                """SELECT pits_tracker_number FROM parts
                   WHERE project_id=? AND part_number=?""",
                (project_id, "P-REPEATED"),
            )[0]
            self.assertEqual(catalog_row["pits_tracker_number"], "")
            self.assertEqual(
                len(store.query(
                    """SELECT pits_id FROM pits_records
                       WHERE project_id=? AND part_number=?""",
                    (project_id, "P-REPEATED"),
                )),
                2,
            )
        finally:
            database_patch.stop()
            for suffix in ("", "-wal", "-shm"):
                Path(f"{database_path}{suffix}").unlink(missing_ok=True)

    def test_import_uses_unique_bom_id_for_repeated_tracker_part_number(self):
        database_path = store.DATA_DIR / f"test_pits_bom_resolution_{uuid4()}.db"
        database_patch = patch.object(store, "DB_PATH", database_path)
        database_patch.start()
        store.init_db()
        project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])

        try:
            records = []
            for source_row, pits_id in enumerate(("1204", "1205"), start=2):
                records.append({
                    "pits_id": pits_id,
                    "part_number": "P-REPEATED",
                    "description": "Repeated source part",
                    "used_bom": "Y",
                    "status": "Active",
                    "subsystem": "Power",
                    "design_maturity": "Prototype",
                    "comments": "",
                    "workstation": "Line 1",
                    "source_row": source_row,
                    "_bom_pits_ids": ["1204"],
                    "source_payload": {
                        "ID Number": pits_id,
                        "Part Number": "P-REPEATED",
                    },
                })

            summary = store.import_pits_id_snapshot(project_id, records, [])

            self.assertEqual(summary["pits_ids_linked"], 1)
            self.assertEqual(summary["pits_ids_resolved_from_bom"], 1)
            self.assertEqual(summary["pits_id_conflicts"], 0)
            catalog_row = store.query(
                """SELECT pits_tracker_number FROM parts
                   WHERE project_id=? AND part_number=?""",
                (project_id, "P-REPEATED"),
            )[0]
            self.assertEqual(catalog_row["pits_tracker_number"], "1204")
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

    def test_import_preserves_manual_feature_applicability(self):
        database_path = store.DATA_DIR / f"test_pits_manual_applicability_{uuid4()}.db"
        database_patch = patch.object(store, "DB_PATH", database_path)
        database_patch.start()
        store.init_db()
        project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])

        try:
            feature_id = str(uuid4())
            store.execute(
                """INSERT INTO complexity_features
                   (id, project_id, category, name, allowed_values, description,
                    sequence, active, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    feature_id, project_id, "Control Panel", "Fascia",
                    '["W2", "G1"]', "", 10, 1, store.now_iso(),
                ),
            )
            model_id = str(uuid4())
            store.execute(
                """INSERT INTO project_models
                   (id, project_id, model_number, source_payload, updated_at,
                    display_name, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (model_id, project_id, "MODEL-1", "{}", store.now_iso(), "Model 1", 1),
            )
            store.execute(
                """INSERT INTO model_feature_values
                   (project_id, model_id, feature_id, value, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (project_id, model_id, feature_id, "W2", store.now_iso()),
            )
            record = {
                "pits_id": "1206",
                "part_number": "P-MANUAL-RULE",
                "description": "Manual applicability part",
                "revision": "Rev A",
                "source_code": "3",
                "used_bom": "Y",
                "status": "Active",
                "subsystem": "Power",
                "design_maturity": "Prototype",
                "comments": "",
                "workstation": "Line 1",
                "source_row": 2,
                "source_payload": {"ID Number": "1206", "Part Number": "P-MANUAL-RULE"},
            }
            store.import_pits_id_snapshot(project_id, [record], [])
            part_id = store.query(
                "SELECT id FROM parts WHERE project_id=? AND part_number=?",
                (project_id, "P-MANUAL-RULE"),
            )[0]["id"]
            store.update_part_feature_rules(
                project_id,
                {part_id: [f"{feature_id}::W2"]},
            )

            store.upsert_part(
                project_id,
                {
                    "part_number": "P-MANUAL-RULE",
                    "description": "Updated from PITS",
                    "model_applicability": "All",
                    "notes": "Keep this contributor note",
                    "source": "BOM import",
                },
            )

            rule = store.query(
                """SELECT feature_id, value FROM part_feature_rules
                   WHERE project_id=? AND part_id=?""",
                (project_id, part_id),
            )
            part = store.query(
                "SELECT model_applicability, notes FROM parts WHERE id=?",
                (part_id,),
            )[0]
            self.assertEqual([(row["feature_id"], row["value"]) for row in rule], [(feature_id, "W2")])
            self.assertEqual(part["model_applicability"], "MODEL-1")
            self.assertEqual(part["notes"], "Keep this contributor note")
        finally:
            database_patch.stop()
            for suffix in ("", "-wal", "-shm"):
                Path(f"{database_path}{suffix}").unlink(missing_ok=True)

    def test_import_preserves_manual_technology_engineer_unless_overwrite_confirmed(self):
        database_path = store.DATA_DIR / f"test_pits_manual_engineer_{uuid4()}.db"
        database_patch = patch.object(store, "DB_PATH", database_path)
        database_patch.start()
        store.init_db()
        project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])

        try:
            store.upsert_part(project_id, {
                "part_number": "P-ENGINEER",
                "description": "Engineer ownership part",
                "technology_engineer": "Manual Engineer",
                "source": "Manual",
            })
            record = {
                "pits_id": "1207",
                "part_number": "P-ENGINEER",
                "description": "Engineer ownership part",
                "technology_engineer": "PITS Engineer",
                "used_bom": "Y",
                "status": "Active",
                "subsystem": "Power",
                "design_maturity": "Prototype",
                "comments": "",
                "workstation": "Line 1",
                "source_row": 2,
                "source_payload": {"ID Number": "1207", "Part Number": "P-ENGINEER"},
            }

            store.import_pits_id_snapshot(project_id, [record], [])
            preserved = store.query(
                "SELECT technology_engineer FROM parts WHERE project_id=? AND part_number=?",
                (project_id, "P-ENGINEER"),
            )[0]
            self.assertEqual(preserved["technology_engineer"], "Manual Engineer")

            store.import_pits_id_snapshot(project_id, [record], [], overwrite_manual=True)
            overwritten = store.query(
                "SELECT technology_engineer FROM parts WHERE project_id=? AND part_number=?",
                (project_id, "P-ENGINEER"),
            )[0]
            self.assertEqual(overwritten["technology_engineer"], "PITS Engineer")
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
                ["PITS Data", "", "", "", "", "", "", "", ""],
                ["Used BOM", "ID Number", "Part No", "Description", "Base Info Status", "Subsystem", "Design Maturity", "Comments", "Factory Workstation Location"],
                ["Yes", "1001", "P-100", "Test part", "Active", "Power", "Prototype", "ok", "Line 1"],
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
        header[5] = "Subsystem"
        header[8] = "People Design Engineer"
        header[13] = "Parts Part Code"
        header[19] = "Source Code"
        header[63] = "Windchill Status"
        values[0] = "1002"
        values[1] = "P-200"
        values[2] = "Column mapped part"
        values[3] = "Y"
        values[5] = "Airflow"
        values[8] = "Taylor Engineer"
        values[13] = "NPNT"
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
        self.assertEqual(records[0]["technology_engineer"], "Taylor Engineer")
        self.assertEqual(records[0]["subsystem"], "Airflow")
        self.assertEqual(records[0]["part_code"], "NPNT")

    def test_reads_bom_column_a_pits_ids_by_part_number(self):
        tracker = pd.DataFrame([
            ["ID Number", "Part Number", "Description", "Used BOM"],
            ["1001", "P-300", "Repeated part", "Y"],
            ["1002", "P-300", "Repeated part", "Y"],
        ])
        models = pd.DataFrame([
            ["Model Number", "Item"],
            ["M-03", "C3"],
        ])
        bom = pd.DataFrame([
            ["", "", ""],
            ["In Tracker", "Part Number", "Description"],
            ["1002", "P-300", "Repeated part"],
        ])

        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            tracker.to_excel(writer, sheet_name="Tracker", index=False, header=False)
            models.to_excel(writer, sheet_name="Models", index=False, header=False)
            bom.to_excel(writer, sheet_name="BOM", index=False, header=False)
        buffer.seek(0)
        uploaded = type(
            "Uploaded",
            (),
            {"name": "bom_resolution.xlsm", "getvalue": lambda self: buffer.getvalue()},
        )()

        records, _ = parse_pits_id_workbook(uploaded)
        resolution = store.pits_catalog_id_resolution(records)

        self.assertEqual({tuple(record["_bom_pits_ids"]) for record in records}, {("1002",)})
        self.assertEqual(resolution["resolved_ids"]["P-300"], "1002")
        self.assertEqual(resolution["resolved_from_bom"], {"P-300"})


if __name__ == "__main__":
    unittest.main()
