from __future__ import annotations

import unittest
from unittest.mock import patch

from utils import store


class PinMapDataTests(unittest.TestCase):
    def test_uses_explicit_process_link_and_keeps_one_row_for_empty_pitches(self) -> None:
        query_rows = [
            {
                "pitch_id": "pitch-1",
                "area_id": "area-1",
                "area_name": "Main line",
                "pitch_number": "101",
                "pitch_name": "Install",
                "pitch_type": "Pitch",
                "pitch_status": "Active",
                "pitch_sequence": 10,
                "process_element_id": "process-1",
                "process_sequence": 10,
                "work_element": "Install part",
            },
            {
                "pitch_id": "pitch-1",
                "area_id": "area-1",
                "area_name": "Main line",
                "pitch_number": "101",
                "pitch_name": "Install",
                "pitch_type": "Pitch",
                "pitch_status": "Active",
                "pitch_sequence": 10,
                "process_element_id": None,
                "process_sequence": None,
                "work_element": None,
            },
            {
                "pitch_id": "pitch-2",
                "area_id": "area-1",
                "area_name": "Main line",
                "pitch_number": "102",
                "pitch_name": "Inspect",
                "pitch_type": "Pitch",
                "pitch_status": "Open",
                "pitch_sequence": 20,
                "process_element_id": None,
                "process_sequence": None,
                "work_element": None,
            },
        ]

        with patch.object(store, "query", return_value=query_rows) as query:
            result = store.pin_map_for_scenario("project-1", "scenario-1")

        self.assertEqual(query.call_args.args[1], ("project-1", "scenario-1"))
        self.assertEqual(len(result), 2)
        self.assertEqual(
            result.loc[result["pitch_id"] == "pitch-1", "process_element_id"].tolist(),
            ["process-1"],
        )
        self.assertTrue(
            result.loc[result["pitch_id"] == "pitch-2", "process_element_id"].isna().all()
        )


if __name__ == "__main__":
    unittest.main()
