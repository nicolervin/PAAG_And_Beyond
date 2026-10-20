from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from utils import store
from utils.exchange_ui import (
    _UploadedFileWrapper,
    _execute_pits_import,
)


def make_tracker_record(
    pits_id: str,
    part_number: str,
    description: str = "",
    subsystem: str = "Chassis",
    design_maturity: str = "Production",
    design_engineer: str = "Engineer A",
    ppm: str = "10",
    buyer_gcl: str = "Buyer B",
    comments: str = "Test comment",
) -> dict:
    return {
        "pits_id": pits_id,
        "part_number": part_number,
        "description": description or f"Description for {part_number}",
        "revision": "A",
        "subsystem": subsystem,
        "design_maturity": design_maturity,
        "design_engineer": design_engineer,
        "ppm": ppm,
        "buyer_gcl": buyer_gcl,
        "source_code": "3",
        "used_bom": "Y",
        "status": "Active",
        "comments": comments,
        "workstation": "ST-10",
        "source_row": 2,
        "source_payload": {"ID Number": pits_id, "Part Number": part_number},
    }


class PitsVerificationTests(unittest.TestCase):
    def setUp(self):
        self.database_path = store.DATA_DIR / f"test_pits_verify_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        scenarios = store.planning_scenarios(self.project_id)
        self.scenario_id = str(scenarios[0]["id"]) if scenarios else None

    def tearDown(self):
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_uploaded_file_wrapper(self):
        sample_bytes = b"sample excel content"
        mock_uploaded = type(
            "MockUploaded",
            (),
            {
                "name": "sample.xlsx",
                "getvalue": lambda self: sample_bytes,
            },
        )()
        wrapper1 = _UploadedFileWrapper(mock_uploaded)
        self.assertEqual(wrapper1.name, "sample.xlsx")
        self.assertEqual(wrapper1.getvalue(), sample_bytes)
        self.assertEqual(wrapper1.size, len(sample_bytes))

        wrapper2 = _UploadedFileWrapper("custom.xlsx", sample_bytes)
        self.assertEqual(wrapper2.name, "custom.xlsx")
        self.assertEqual(wrapper2.getvalue(), sample_bytes)
        self.assertEqual(wrapper2.size, len(sample_bytes))

    def test_first_pits_upload_skips_part_verification(self):
        new_project_id = store.create_project("New PITS Project", "Fresh project", "Owner", 60.0)
        records = [
            make_tracker_record("ID-1", "PART-BRAND-NEW", "Brand New Part Description"),
            make_tracker_record("ID-2", "PART-SECOND", "Second Part Description"),
        ]
        # First PITS upload on a new project should not require part verification
        self.assertEqual(store.detect_pits_new_and_changed_parts(new_project_id, records), [])
        # Even if manual/sample parts exist, if no prior PITS upload occurred, skip verification
        self.assertEqual(store.detect_pits_new_and_changed_parts(self.project_id, records), [])

    def test_detect_new_and_changed_parts(self):
        # Seed a prior PITS upload so subsequent upload verification is active
        store.import_pits_id_snapshot(
            self.project_id,
            [
                make_tracker_record("ID-1", "PART-EXISTING-SAME", "Catalog Same Description"),
                make_tracker_record("ID-2", "PART-EXISTING-CHANGED", "Catalog Old Description"),
                make_tracker_record("ID-5", "PART-REMOVED", "Catalog Removed Description"),
            ],
            [],
        )

        records = [
            # Part unchanged -> should NOT be flagged
            make_tracker_record("ID-1", "PART-EXISTING-SAME", "Catalog Same Description"),
            # Part with modified description -> should be flagged as changed_description
            make_tracker_record("ID-2", "PART-EXISTING-CHANGED", "Incoming New Description"),
            # New part 1 -> flagged as new_part
            make_tracker_record("ID-3", "PART-BRAND-NEW", "Brand New Part Description"),
            # New part 2 repeated with two different PITS IDs -> deduplicated to 1 item
            make_tracker_record("ID-4A", "PART-REPEATED-NEW", "Repeated New Desc"),
            make_tracker_record("ID-4B", "PART-REPEATED-NEW", "Repeated New Desc"),
        ]

        detected = store.detect_pits_new_and_changed_parts(self.project_id, records)
        detected_by_part = {d["part_number"]: d for d in detected}

        self.assertNotIn("PART-EXISTING-SAME", detected_by_part)

        self.assertIn("PART-EXISTING-CHANGED", detected_by_part)
        changed_item = detected_by_part["PART-EXISTING-CHANGED"]
        self.assertEqual(changed_item["change_type"], "changed_description")
        self.assertEqual(changed_item["current_description"], "Catalog Old Description")
        self.assertEqual(changed_item["incoming_description"], "Incoming New Description")

        self.assertIn("PART-BRAND-NEW", detected_by_part)
        new_item = detected_by_part["PART-BRAND-NEW"]
        self.assertEqual(new_item["change_type"], "new_part")
        self.assertEqual(new_item["incoming_description"], "Brand New Part Description")

        self.assertIn("PART-REPEATED-NEW", detected_by_part)
        repeated_item = detected_by_part["PART-REPEATED-NEW"]
        self.assertEqual(repeated_item["change_type"], "new_part")
        self.assertEqual(sorted(repeated_item["all_pits_ids"]), ["ID-4A", "ID-4B"])

        self.assertIn("PART-REMOVED", detected_by_part)
        deleted_item = detected_by_part["PART-REMOVED"]
        self.assertEqual(deleted_item["change_type"], "deleted_part")
        self.assertEqual(deleted_item["current_description"], "Catalog Removed Description")
        self.assertEqual(deleted_item["all_pits_ids"], ["ID-5"])
        self.assertEqual(len(detected), 4)

    def test_reupload_same_pits_snapshot_does_not_flag_unchanged_parts(self):
        records = [
            make_tracker_record("ID-10", "308D3170G003", "CONSOLE ASM - FIRST DESC"),
            make_tracker_record("ID-11", "308D3170G003", "CONSOLE ASM - SECOND DESC"),
            make_tracker_record("732", "308d3342P001", "BRACKET LOWER"),
        ]
        bom_snapshot = {
            "occurrences": [
                {
                    "parent_tracker_number": "ROOT",
                    "child_tracker_number": "732",
                    "part_number": "308D3342P001",
                    "description": "BRACKET LOWER",
                    "proposed_depth": 2,
                    "proposed_quantity": 1,
                },
                {
                    "parent_tracker_number": "ROOT",
                    "child_tracker_number": "N",
                    "part_number": "STK3D1051AL",
                    "description": "SCREW NOT IN TRACKER",
                    "proposed_depth": 2,
                    "proposed_quantity": 4,
                },
            ]
        }
        store.import_pits_id_snapshot(self.project_id, records, [], bom_snapshot=bom_snapshot)

        # Re-uploading the exact same snapshot must flag 0 changes
        detected_same = store.detect_pits_new_and_changed_parts(
            self.project_id,
            records,
            bom_snapshot=bom_snapshot,
        )
        self.assertEqual(detected_same, [])

        # If one of the repeated tracker rows actually changes its description, it should be flagged
        modified_records = [
            make_tracker_record("ID-10", "308D3170G003", "CONSOLE ASM - UPDATED DESC"),
            make_tracker_record("ID-11", "308D3170G003", "CONSOLE ASM - SECOND DESC"),
            make_tracker_record("732", "308d3342P001", "BRACKET LOWER"),
        ]
        detected_mod = store.detect_pits_new_and_changed_parts(
            self.project_id,
            modified_records,
            bom_snapshot=bom_snapshot,
        )
        self.assertEqual(len(detected_mod), 1)
        self.assertEqual(detected_mod[0]["part_number"], "308D3170G003")
        self.assertEqual(detected_mod[0]["change_type"], "changed_description")
        self.assertEqual(detected_mod[0]["incoming_description"], "CONSOLE ASM - UPDATED DESC")

        # If a part is removed in a new upload, it is flagged as deleted_part
        records_without_732 = [
            make_tracker_record("ID-10", "308D3170G003", "CONSOLE ASM - FIRST DESC"),
            make_tracker_record("ID-11", "308D3170G003", "CONSOLE ASM - SECOND DESC"),
        ]
        detected_del = store.detect_pits_new_and_changed_parts(
            self.project_id,
            records_without_732,
        )
        self.assertEqual(len(detected_del), 1)
        self.assertEqual(detected_del[0]["part_number"], "308d3342P001")
        self.assertEqual(detected_del[0]["change_type"], "deleted_part")
        self.assertEqual(detected_del[0]["current_description"], "BRACKET LOWER")

    def test_downstream_impacts_queries(self):
        # 1. Setup a part in Fishbone
        part_id = store.upsert_part(
            self.project_id,
            {"part_number": "PART-IMPACT-TEST", "description": "Impact Test Part"},
        )

        section_id = str(uuid4())
        now_ts = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO assembly_sections (id, project_id, name, sequence, created_at, updated_at)
                   VALUES (?, ?, 'Chassis Assembly', 1, ?, ?)""",
                (section_id, self.project_id, now_ts, now_ts),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments (id, project_id, section_id, part_id, quantity, use_description, pits_sync_status, updated_at)
                   VALUES (?, ?, ?, ?, 2.0, 'Primary bracket', 'In sync', ?)""",
                (str(uuid4()), self.project_id, section_id, part_id, now_ts),
            )

        # 2. Setup Yamazumi work element
        we_id = str(uuid4())
        if self.scenario_id:
            with store.connection() as conn:
                conn.execute(
                    """INSERT INTO work_elements (id, project_id, scenario_id, sequence, station, operation, part_number, description, cycle_time_s, updated_at)
                       VALUES (?, ?, ?, 10, 'ST-10', 'OP-1', 'PART-IMPACT-TEST', 'Install bracket', 25.5, ?)""",
                    (we_id, self.project_id, self.scenario_id, now_ts),
                )

        # 3. Setup Process at a Glance option
        if self.scenario_id:
            with store.connection() as conn:
                group_id = str(uuid4())
                conn.execute(
                    """INSERT INTO process_part_groups (id, project_id, scenario_id, work_element_id, section_id, name, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'Mounting Group', ?)""",
                    (group_id, self.project_id, self.scenario_id, we_id, section_id, now_ts),
                )
                conn.execute(
                    """INSERT INTO process_part_options (id, group_id, part_id, handling_type, updated_at)
                       VALUES (?, ?, ?, 'Consume', ?)""",
                    (str(uuid4()), group_id, part_id, now_ts),
                )

        # 4. Setup Concern
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO concerns (id, project_id, related_part, category, subject, priority, status, created_at, updated_at)
                   VALUES (?, ?, 'PART-IMPACT-TEST', 'Quality', 'PART-IMPACT-TEST torque check', 'High', 'Open', ?, ?)""",
                (str(uuid4()), self.project_id, now_ts, now_ts),
            )

        # Incoming BOM occurrence
        bom_snapshot = {
            "occurrences": [
                {
                    "parent_tracker_number": "ROOT",
                    "child_tracker_number": "ID-100",
                    "part_number": "PART-IMPACT-TEST",
                    "proposed_depth": 2,
                    "proposed_quantity": 2,
                }
            ]
        }

        impacts = store.pits_part_downstream_impacts(
            self.project_id,
            "PART-IMPACT-TEST",
            scenario_id=self.scenario_id,
            bom_snapshot=bom_snapshot,
        )

        # Assert Fishbone impact
        self.assertTrue(impacts["fishbone"]["is_placed"])
        self.assertEqual(impacts["fishbone"]["count"], 1)
        self.assertEqual(impacts["fishbone"]["assignments"][0]["section_name"], "Chassis Assembly")

        # Assert Model Tree impact
        self.assertEqual(len(impacts["model_tree"]["occurrences"]), 1)
        self.assertEqual(impacts["model_tree"]["occurrences"][0]["parent_tracker_number"], "ROOT")

        # Assert Yamazumi impact
        if self.scenario_id:
            self.assertEqual(impacts["yamazumi"]["count"], 1)
            self.assertEqual(impacts["yamazumi"]["elements"][0]["station"], "ST-10")

        # Assert Process at a Glance impact
        if self.scenario_id:
            self.assertEqual(impacts["process"]["count"], 1)
            self.assertEqual(impacts["process"]["options"][0]["group_name"], "Mounting Group")

        # Assert Concerns impact
        self.assertEqual(impacts["concerns"]["count"], 1)
        self.assertIn("torque check", impacts["concerns"]["items"][0]["subject"])

    def test_execute_pits_import_records_acknowledged_parts_in_audit(self):
        records = [
            make_tracker_record("ID-101", "PART-ACK-1", "Ack Part 1"),
            make_tracker_record("ID-102", "PART-ACK-2", "Ack Part 2"),
        ]
        models = []
        bom_snapshot = {"occurrences": []}
        mock_file = _UploadedFileWrapper("test.xlsx", b"test workbook data")

        acknowledged = ["PART-ACK-1", "PART-ACK-2"]
        result = _execute_pits_import(
            self.project_id,
            self.scenario_id,
            records,
            models,
            bom_snapshot,
            mock_file,
            overwrite_manual=False,
            editor_name="Auditor Kayla",
            acknowledged_parts=acknowledged,
        )

        self.assertIn("success_message", result)
        self.assertEqual(result["acknowledged_parts"], acknowledged)

        # Verify audit event payload contains acknowledged_parts
        history = store.audit_history(self.project_id, "PITS snapshot", limit=10)
        self.assertFalse(history.empty)
        last_event = history.iloc[0]
        details = json.loads(last_event["details"]) if isinstance(last_event["details"], str) else last_event["details"]

        self.assertEqual(details.get("acknowledged_parts"), acknowledged)
        self.assertEqual(last_event["editor_name"], "Auditor Kayla")


if __name__ == "__main__":
    unittest.main()
