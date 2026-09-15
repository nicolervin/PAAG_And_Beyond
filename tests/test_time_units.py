from __future__ import annotations

import unittest

from utils.time_units import (
    display_to_seconds,
    format_seconds,
    normalize_time_unit,
    seconds_to_display,
    time_unit,
)


class TimeUnitTests(unittest.TestCase):
    def test_converts_all_supported_units_both_directions(self) -> None:
        self.assertEqual(seconds_to_display(90, "seconds"), 90)
        self.assertEqual(seconds_to_display(90, "minutes"), 1.5)
        self.assertEqual(seconds_to_display(7200, "hours"), 2)
        self.assertEqual(display_to_seconds(1.5, "minutes"), 90)
        self.assertEqual(display_to_seconds(2, "hours"), 7200)

    def test_normalizes_case_and_rejects_unknown_units(self) -> None:
        self.assertEqual(normalize_time_unit(" Minutes "), "minutes")
        with self.assertRaisesRegex(ValueError, "Seconds, Minutes, or Hours"):
            normalize_time_unit("days")

    def test_configuration_and_formatting_use_approved_precision(self) -> None:
        self.assertEqual((time_unit("seconds").step, time_unit("seconds").decimals), (0.1, 1))
        self.assertEqual((time_unit("minutes").step, time_unit("minutes").decimals), (0.001, 3))
        self.assertEqual((time_unit("hours").step, time_unit("hours").decimals), (0.0001, 4))
        self.assertEqual(format_seconds(90, "seconds"), "90.0 s")
        self.assertEqual(format_seconds(90, "minutes"), "1.500 min")
        self.assertEqual(format_seconds(7200, "hours"), "2.0000 hr")

    def test_nonfinite_values_are_rejected(self) -> None:
        for value in (float("nan"), float("inf"), "not a number"):
            with self.assertRaisesRegex(ValueError, "must be"):
                display_to_seconds(value, "seconds")
        with self.assertRaisesRegex(ValueError, "zero or greater"):
            display_to_seconds(-0.1, "minutes")


if __name__ == "__main__":
    unittest.main()
