import json
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from utils import store


def tracker_record(pits_id: str, part_number: str) -> dict:
    return {
        "pits_id": pits_id,
        "part_number": part_number,
        "description": f"Part {part_number}",
        "revision": "A",
        "source_code": "3",
        "used_bom": "Y",
        "status": "Active",
        "subsystem": "",
        "design_maturity": "",
        "comments": "",
        "workstation": "",
        "source_row": 2,
        "source_payload": {"ID Number": pits_id, "Part Number": part_number},
    }


def occurrence(parent: str, child: str, quantity: float, row: int = 9, depth: int = 1) -> dict:
    return {
        "parent_tracker_number": parent,
        "child_tracker_number": child,
        "part_number": f"P-{child}",
        "description": f"Part {child}",
        "proposed_depth": depth,
        "raw_quantity_text": str(quantity),
        "proposed_quantity": quantity,
        "source_row": row,
        "raw_levels": {f"Level {depth}": quantity},
    }


def snapshot(rows: list[dict], *, duplicates: list[dict] | None = None) -> dict:
    return {
        "sheet_name": "BOM",
        "source_row_count": len(rows),
        "occurrences": rows,
        "issues": [],
        "duplicates": duplicates or [],
    }


class PitsBomStructureImportTests(unittest.TestCase):
    def setUp(self):
        self.database_path = store.DATA_DIR / f"test_pits_bom_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])

    def tearDown(self):
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def import_rows(self, tracker_rows: list[dict], bom_rows: list[dict], name: str = "pits.xlsm"):
        return store.import_pits_id_snapshot(
            self.project_id,
            tracker_rows,
            [],
            bom_snapshot=snapshot(bom_rows),
            workbook_name=name,
            workbook_sha256=f"hash-{name}",
            editor_name="Tester",
        )

    def test_snapshot_upsert_change_missing_return_and_revision_history(self):
        records = [tracker_record("001", "P-001"), tracker_record("002", "P-002")]
        first = self.import_rows(records, [occurrence("", "001", 1), occurrence("001", "002", 2, 10, 2)])
        self.assertEqual(first["bom"]["new"], 2)

        second = self.import_rows(records, [occurrence("", "001", 1), occurrence("001", "002", 2, 99, 2)], "same.xlsm")
        self.assertEqual(second["bom"]["unchanged"], 2)
        self.assertEqual(
            store.query("SELECT COUNT(*) AS count FROM pits_bom_occurrence_revisions")[0]["count"],
            2,
        )

        changed = self.import_rows(records, [occurrence("", "001", 1), occurrence("001", "002", 3, 10, 2)], "changed.xlsm")
        self.assertEqual(changed["bom"]["changed"], 1)
        child = store.query(
            """SELECT source_state, proposed_quantity FROM pits_bom_occurrences
               WHERE project_id=? AND parent_tracker_number='001' AND child_tracker_number='002'""",
            (self.project_id,),
        )[0]
        self.assertEqual(child["source_state"], "New")
        self.assertEqual(child["proposed_quantity"], 3)

        missing = self.import_rows(records, [occurrence("", "001", 1)], "missing.xlsm")
        self.assertEqual(missing["bom"]["missing"], 1)
        returned = self.import_rows(records, [occurrence("", "001", 1), occurrence("001", "002", 3, 10, 2)], "return.xlsm")
        self.assertEqual(returned["bom"]["unchanged"], 2)
        state = store.query(
            "SELECT source_state FROM pits_bom_occurrences WHERE parent_tracker_number='001' AND child_tracker_number='002'"
        )[0]["source_state"]
        self.assertEqual(state, "New")

    def test_approval_quantity_sync_and_escalation_preserve_difference(self):
        result = self.import_rows([tracker_record("001", "P-001")], [occurrence("", "001", 2)])
        occurrence_row = store.query("SELECT * FROM pits_bom_occurrences")[0]
        section_id = str(uuid4())
        store.execute(
            """INSERT INTO assembly_sections
               (id, project_id, name, section_type, sequence, description, active, created_at, updated_at)
               VALUES (?, ?, 'Main', 'Main spine', 10, '', 1, ?, ?)""",
            (section_id, self.project_id, store.now_iso(), store.now_iso()),
        )
        review = store.review_pits_bom_occurrences(
            self.project_id, [occurrence_row["id"]], "Approve", "Tester", section_id=section_id
        )
        self.assertEqual(review["created_assignments"], 1)
        assignment = store.query("SELECT * FROM fishbone_part_assignments")[0]
        self.assertEqual(assignment["quantity"], 2)
        self.assertEqual(assignment["pits_sync_status"], "In sync")

        store.execute(
            "UPDATE fishbone_part_assignments SET quantity=4, updated_at=? WHERE id=?",
            (store.now_iso(), assignment["id"]),
        )
        self.assertEqual(
            store.query("SELECT pits_sync_status FROM fishbone_part_assignments")[0]["pits_sync_status"],
            "Quantity differs",
        )
        concern_id = store.escalate_pits_bom_occurrence(
            self.project_id, occurrence_row["id"], "Tester"
        )
        self.assertTrue(store.query("SELECT id FROM concerns WHERE id=?", (concern_id,)))
        self.assertEqual(
            store.query("SELECT pits_sync_status FROM fishbone_part_assignments")[0]["pits_sync_status"],
            "Quantity differs",
        )

        self.import_rows([tracker_record("001", "P-001")], [], "removed.xlsm")
        self.assertEqual(
            store.query("SELECT pits_sync_status FROM fishbone_part_assignments")[0]["pits_sync_status"],
            "No longer found",
        )

    def test_duplicate_key_imports_once_and_is_flagged_with_source_rows(self):
        duplicate = {
            "parent_tracker_number": "",
            "child_tracker_number": "001",
            "first_source_row": 9,
            "duplicate_source_row": 10,
        }
        result = store.import_pits_id_snapshot(
            self.project_id,
            [tracker_record("001", "P-001")],
            [],
            bom_snapshot=snapshot([occurrence("", "001", 1)], duplicates=[duplicate]),
            workbook_name="duplicate.xlsm",
            workbook_sha256="duplicate",
        )
        self.assertEqual(result["bom"]["duplicate_pairs"], 1)
        self.assertEqual(result["bom"]["issues"], 1)
        self.assertTrue(store.query("SELECT id FROM pits_records"))
        self.assertTrue(store.query("SELECT id FROM pits_bom_imports"))
        rows = store.query("SELECT * FROM pits_bom_occurrences")
        self.assertEqual(len(rows), 1)
        issues = json.loads(rows[0]["validation_issues_json"])
        self.assertEqual(len(issues), 1)
        self.assertIn("BOM rows 9, 10", issues[0])

        clean = self.import_rows(
            [tracker_record("001", "P-001")], [occurrence("", "001", 1)], "clean.xlsm"
        )
        self.assertEqual(clean["bom"]["duplicate_pairs"], 0)
        cleaned = store.query("SELECT validation_issues_json FROM pits_bom_occurrences")[0]
        self.assertEqual(json.loads(cleaned["validation_issues_json"]), [])

    def test_repeated_occurrence_rows_are_collapsed_and_flagged(self):
        result = store.import_pits_id_snapshot(
            self.project_id,
            [tracker_record("001", "P-001")],
            [],
            bom_snapshot=snapshot([
                occurrence("", "001", 1, row=9),
                occurrence("", "001", 1, row=10),
            ]),
            workbook_name="direct-duplicate.xlsm",
            workbook_sha256="direct-duplicate",
        )
        self.assertEqual(result["bom"]["duplicate_pairs"], 1)
        rows = store.query("SELECT validation_issues_json FROM pits_bom_occurrences")
        self.assertEqual(len(rows), 1)
        self.assertIn("BOM rows 9, 10", json.loads(rows[0]["validation_issues_json"])[0])

    def test_unresolved_parent_is_staged_but_cannot_be_approved(self):
        result = self.import_rows(
            [tracker_record("002", "P-002")],
            [occurrence("999", "002", 1, depth=2)],
        )
        self.assertEqual(result["bom"]["issues"], 1)
        row = store.query("SELECT * FROM pits_bom_occurrences")[0]
        self.assertIsNone(row["parent_part_id"])
        self.assertIn("Parent tracker", json.loads(row["validation_issues_json"])[0])
        section_id = str(uuid4())
        store.execute(
            """INSERT INTO assembly_sections
               (id, project_id, name, section_type, sequence, description, active, created_at, updated_at)
               VALUES (?, ?, 'Main', 'Main spine', 10, '', 1, ?, ?)""",
            (section_id, self.project_id, store.now_iso(), store.now_iso()),
        )
        with self.assertRaisesRegex(ValueError, "validation issues"):
            store.review_pits_bom_occurrences(
                self.project_id, [row["id"]], "Approve", section_id=section_id
            )


if __name__ == "__main__":
    unittest.main()
