from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

import pandas as pd

from utils.exchange_ui import (
    _build_pits_flagged_changes_summary,
    _save_pits_workbook_snapshot,
    render_part_data_exchange,
)


class PitsExchangeUiTests(unittest.TestCase):
    def test_combined_import_passes_bom_snapshot_and_workbook_identity(self) -> None:
        workbook_data = b"combined PITS workbook"
        uploaded = type(
            "Uploaded",
            (),
            {
                "name": "nexus-pits.xlsm",
                "getvalue": lambda self: workbook_data,
            },
        )()
        records = [{"pits_id": "1"}]
        models = [{"model_number": "MODEL-1"}]
        bom_snapshot = {
            "sheet_name": "BOM",
            "occurrences": [{"child_tracker_number": "1"}],
        }

        with patch(
            "utils.exchange_ui.import_pits_id_snapshot",
            return_value={"bom": {"new": 1}},
        ) as import_snapshot:
            result = _save_pits_workbook_snapshot(
                "project-1",
                "scenario-1",
                records,
                models,
                bom_snapshot,
                uploaded,
                overwrite_manual=False,
                editor_name="Kayla Funk",
            )

        self.assertEqual(result, {"bom": {"new": 1}})
        import_snapshot.assert_called_once_with(
            "project-1",
            records,
            models,
            scenario_id="scenario-1",
            overwrite_manual=False,
            bom_snapshot=bom_snapshot,
            workbook_name="nexus-pits.xlsm",
            workbook_sha256=hashlib.sha256(workbook_data).hexdigest(),
            editor_name="Kayla Funk",
        )

    def test_render_part_data_exchange_shows_import_pits_file_only(self) -> None:
        subheaders: list[str] = []

        class DummyContainer:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with (
            patch(
                "utils.exchange_ui.project_models",
                return_value=pd.DataFrame(columns=["model_number", "display_name"]),
            ),
            patch("utils.exchange_ui.st.container", return_value=DummyContainer()),
            patch("utils.exchange_ui.st.subheader", side_effect=subheaders.append),
            patch("utils.exchange_ui.st.file_uploader", return_value=None),
            patch("utils.exchange_ui.st.session_state", {}),
        ):
            render_part_data_exchange("project-1", "scenario-1")

        self.assertEqual(subheaders, ["Import PITS File"])

    def test_build_pits_flagged_changes_summary_formats_changes_and_impacts(self) -> None:
        pending_reviews = [
            {
                "part_number": "PART-NEW-REPL",
                "change_type": "new_part",
                "replaces_part_number": "PART-OLD",
                "replaces_description": "Old Bracket",
                "incoming_description": "New Bracket",
                "pits_id": "10",
                "all_pits_ids": ["10"],
                "subsystem": "Chassis",
            },
            {
                "part_number": "PART-DESC-MOD",
                "change_type": "changed_description",
                "current_description": "Motor V1",
                "incoming_description": "Motor V2",
                "pits_id": "20",
                "all_pits_ids": ["20", "21"],
                "subsystem": "Drive",
            },
            {
                "part_number": "PART-DEL-OLD",
                "change_type": "deleted_part",
                "current_description": "Obsolete Harness",
                "incoming_description": "",
                "pits_id": "30",
                "all_pits_ids": ["30"],
                "subsystem": "Electrical",
            },
        ]
        fake_impacts = {
            "fishbone": {"count": 1, "replaces_count": 0, "assignments": [{"section_name": "Sec A", "quantity": 2, "use_description": "Mount"}], "replaces_assignments": []},
            "model_tree": {"occurrences": [], "replaces_count": 0, "replaces_occurrences": []},
            "yamazumi": {"count": 0, "replaces_count": 1, "elements": [], "replaces_elements": [{"station": "ST-1", "operation": "OP-1", "description": "Install"}]},
            "process": {"count": 0, "replaces_count": 0, "options": [], "replaces_options": []},
            "concerns": {"count": 0, "replaces_count": 0, "items": [], "replaces_items": []},
        }
        with patch("utils.exchange_ui.pits_part_downstream_impacts", return_value=fake_impacts):
            summary_df, impact_details = _build_pits_flagged_changes_summary(
                "project-1",
                "scenario-1",
                pending_reviews,
            )

        self.assertEqual(len(summary_df), 3)
        first = summary_df.iloc[0]
        self.assertEqual(first["change_type_label"], "Part replacement")
        self.assertEqual(first["part_number"], "PART-NEW-REPL")
        self.assertEqual(first["previous_value"], "PART-OLD (Old Bracket)")
        self.assertEqual(first["incoming_description"], "New Bracket")
        self.assertEqual(first["downstream_impacts"], "Fishbone (1), Yamazumi (1)")

        second = summary_df.iloc[1]
        self.assertEqual(second["change_type_label"], "Modified description")
        self.assertEqual(second["part_number"], "PART-DESC-MOD")
        self.assertEqual(second["pits_ids"], "20, 21")
        self.assertEqual(second["previous_value"], "Motor V1")
        self.assertEqual(second["incoming_description"], "Motor V2")

        third = summary_df.iloc[2]
        self.assertEqual(third["change_type_label"], "Deleted part")
        self.assertEqual(third["part_number"], "PART-DEL-OLD")
        self.assertEqual(third["pits_ids"], "30")
        self.assertEqual(third["previous_value"], "Obsolete Harness")
        self.assertEqual(third["incoming_description"], "—")
        self.assertEqual(len(impact_details), 3)


if __name__ == "__main__":
    unittest.main()

