from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from utils.pfmea_store import PFMEA_CLASSIFICATION_MEANINGS
from utils.quality_help import (
    CONTROL_PLAN_HELP,
    PFMEA_HELP,
    REQUIREMENTS_REPOSITORY_HELP,
)


PAGE_PATH = Path(__file__).resolve().parents[1] / "app_pages" / "functional_quality.py"


class QualityHelpContentTests(unittest.TestCase):
    def test_pfmea_help_contains_every_current_classification(self) -> None:
        for code, meaning in PFMEA_CLASSIFICATION_MEANINGS.items():
            if code:
                self.assertIn(f"| {code} | {meaning} |", PFMEA_HELP)

    def test_help_uses_current_quality_and_control_plan_labels(self) -> None:
        requirements_help = " ".join(REQUIREMENTS_REPOSITORY_HELP.split())
        control_plan_help = " ".join(CONTROL_PLAN_HELP.split())
        for label in (
            "Linked Process steps",
            "Pending linked updates",
            "Bulk edit Pass/fail",
            "Push saved updates to linked Process steps",
        ):
            self.assertIn(label, requirements_help)

        for label in (
            "Pr. Nº",
            "Station / Pitch",
            "Machine / fixture",
            "Characteristic suffix",
            "Characteristic type",
            "Source review required",
        ):
            self.assertIn(label, control_plan_help)

    def test_help_button_opens_and_closes_read_only_dialog(self) -> None:
        app = AppTest.from_file(str(PAGE_PATH), default_timeout=20)
        app.run()
        self.assertEqual(len(app.exception), 0)

        help_button = next(
            button for button in app.button if button.label == "How to use this page"
        )
        help_button.click().run()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(
            [tab.label for tab in app.tabs],
            ["Requirements repository", "PFMEA", "Control Plan"],
        )
        rendered_help = " ".join(
            "\n".join(str(block.value) for block in app.markdown).split()
        )
        self.assertIn("Save & Refresh", rendered_help)
        self.assertIn("Recalculate RPN", rendered_help)
        self.assertIn("Manufacturing Control Plan working draft", rendered_help)
        self.assertFalse(any(button.label == "Save & Refresh" for button in app.button))

        close_button = next(button for button in app.button if button.label == "Close")
        close_button.click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertFalse(any(button.label == "Close" for button in app.button))


if __name__ == "__main__":
    unittest.main()
