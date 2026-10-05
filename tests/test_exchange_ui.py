from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

from utils.exchange_ui import _save_pits_workbook_snapshot


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


if __name__ == "__main__":
    unittest.main()
