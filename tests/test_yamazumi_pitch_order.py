from __future__ import annotations

import unittest

import pandas as pd

from utils.yamazumi_order import order_yamazumi_pitches_for_board


class YamazumiPitchOrderTests(unittest.TestCase):
    @staticmethod
    def pitches(*rows: dict) -> pd.DataFrame:
        defaults = {
            "pitch_name": "",
            "pitch_type": "Pitch",
            "feeds_into_pitch_id": None,
            "sequence": 10,
        }
        return pd.DataFrame([{**defaults, **row} for row in rows])

    def ordered_ids(self, pitches: pd.DataFrame) -> list[str]:
        return list(order_yamazumi_pitches_for_board(pitches)["id"])

    def test_uses_natural_pitch_address_order_instead_of_append_sequence(self) -> None:
        pitches = self.pitches(
            {"id": "ten", "pitch_number": "OP-10", "sequence": 10},
            {"id": "two", "pitch_number": "OP-2", "sequence": 30},
            {"id": "one", "pitch_number": "OP-1", "sequence": 20},
        )

        self.assertEqual(self.ordered_ids(pitches), ["one", "two", "ten"])

    def test_feeder_is_immediately_before_its_receiving_pitch(self) -> None:
        pitches = self.pitches(
            {"id": "target", "pitch_number": "01-ML1-004"},
            {"id": "first", "pitch_number": "01-ML1-001"},
            {
                "id": "sub",
                "pitch_number": "99-SA1-001",
                "pitch_type": "Subassembly",
                "feeds_into_pitch_id": "target",
            },
        )

        self.assertEqual(self.ordered_ids(pitches), ["first", "sub", "target"])

    def test_nested_feeder_chain_and_siblings_are_deterministic(self) -> None:
        pitches = self.pitches(
            {"id": "target", "pitch_number": "01-ML1-004"},
            {
                "id": "sub-b",
                "pitch_number": "SA-20",
                "pitch_type": "Subassembly",
                "feeds_into_pitch_id": "target",
            },
            {
                "id": "sub-a",
                "pitch_number": "SA-3",
                "pitch_type": "Subassembly",
                "feeds_into_pitch_id": "target",
            },
            {
                "id": "kit",
                "pitch_number": "KIT-1",
                "pitch_type": "Kitter",
                "feeds_into_pitch_id": "sub-a",
            },
        )

        self.assertEqual(
            self.ordered_ids(pitches),
            ["kit", "sub-a", "sub-b", "target"],
        )

    def test_dangling_legacy_target_does_not_hide_or_move_pitch(self) -> None:
        pitches = self.pitches(
            {
                "id": "legacy",
                "pitch_number": "OP-2",
                "pitch_type": "Subassembly",
                "feeds_into_pitch_id": "missing",
            },
            {"id": "first", "pitch_number": "OP-1"},
        )

        self.assertEqual(self.ordered_ids(pitches), ["first", "legacy"])

    def test_empty_frame_retains_columns(self) -> None:
        pitches = pd.DataFrame({"id": pd.Series(dtype="string")})

        ordered = order_yamazumi_pitches_for_board(pitches)

        self.assertTrue(ordered.empty)
        self.assertEqual(list(ordered.columns), ["id"])


if __name__ == "__main__":
    unittest.main()
