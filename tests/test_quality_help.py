from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from utils.pfmea_store import PFMEA_CLASSIFICATION_MEANINGS
from utils.quality_help import (
    CONTROL_PLAN_HELP,
    PFMEA_HELP_SECTIONS,
    PFMEA_QUICK_START,
    REQUIREMENTS_REPOSITORY_HELP,
)


PAGE_PATH = Path(__file__).resolve().parents[1] / "app_pages" / "functional_quality.py"


class QualityHelpContentTests(unittest.TestCase):
    def test_pfmea_help_contains_every_current_classification(self) -> None:
        rendered_pfmea_help = PFMEA_QUICK_START + "\n" + "\n".join(
            content for _, content in PFMEA_HELP_SECTIONS
        )
        for code, meaning in PFMEA_CLASSIFICATION_MEANINGS.items():
            if code:
                self.assertIn(f"| {code} | {meaning} |", rendered_pfmea_help)

    def test_pfmea_help_uses_quick_start_and_focused_sections(self) -> None:
        self.assertIn("PAAG Validation Gate", PFMEA_QUICK_START)
        self.assertEqual(
            [title for title, _ in PFMEA_HELP_SECTIONS],
            [
                "PAAG Validation Gate & Staging New PFMEA Lines (Pattern Quick-Apply vs. Blank Lines)",
                "PFMEA Worksheet Columns, Shared-Record Sync & Inline Editing",
                "Ratings, RPN Calculation, and Classification (CL) Codes",
                "Current Process Controls (Prevention & Detection) & Control Plan Coverage Flag",
                "Recommended Actions, Assignees (👥 Manage Assignees) & Target Dates",
                "Manual Control Catalog Overview & Editor (📊 Control Catalog)",
                "Creating, Capturing & Managing Reusable PFMEA Patterns",
                "Duplicating Lines, Completion Assistant, RPN Charts & Exports",
            ],
        )
        combined_sections = " ".join(
            " ".join(content.split()) for _, content in PFMEA_HELP_SECTIONS
        )
        for label in (
            "Stage Blank Line(s)",
            "PFMEA completion assistant",
            "Duplicate selected PFMEA line",
            "Manage PFMEA patterns",
            "Manual Prevention & Detection Control Catalog Overview",
            "High-risk PFMEA lines",
            "Process source review",
        ):
            self.assertIn(label, combined_sections)

    def test_pfmea_pattern_help_documents_complete_workflow(self) -> None:
        pattern_sections = {
            title: " ".join(content.split())
            for title, content in PFMEA_HELP_SECTIONS
            if "pattern" in title.lower()
        }
        self.assertEqual(
            set(pattern_sections),
            {
                "PAAG Validation Gate & Staging New PFMEA Lines (Pattern Quick-Apply vs. Blank Lines)",
                "Creating, Capturing & Managing Reusable PFMEA Patterns",
            },
        )
        combined = " ".join(pattern_sections.values()).replace("**", "")
        for expected in (
            "project-wide template",
            "Label",
            "Potential Failure Mode",
            "Effects",
            "Causes",
            "Recommended Actions",
            "Save selected PFMEA line as pattern",
            "Pattern Quick-Apply",
            "independent copy",
            "Prevention suggestions",
            "Detection suggestions",
        ):
            self.assertIn(expected, combined)

    def test_help_uses_current_quality_and_control_plan_labels(self) -> None:
        requirements_help = " ".join(REQUIREMENTS_REPOSITORY_HELP.split())
        control_plan_help = " ".join(CONTROL_PLAN_HELP.split())
        for label in (
            "Linked Process steps",
            "Pending linked updates",
            "Assign Steps...",
            "Push saved updates to linked Process steps",
        ):
            self.assertIn(label, requirements_help)

        for label in (
            "Pr. Nº",
            "Station / Pitch",
            "Machine / fixture",
            "Characteristic type",
            "Control method",
            "Process flow map",
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
            [
                "📊 Traceability & PAAG Sync",
                "Requirements repository",
                "PFMEA",
                "Control Plan",
                "Equipment",
            ],
        )
        expander_labels = {expander.label for expander in app.expander}
        self.assertTrue(
            {title for title, _ in PFMEA_HELP_SECTIONS}.issubset(expander_labels)
        )
        rendered_help = " ".join(
            "\n".join(str(block.value) for block in app.markdown).split()
        )
        self.assertIn("Save & Refresh", rendered_help)
        self.assertIn("Recalculate RPN", rendered_help)
        self.assertIn("Manufacturing Control Plan (MCP) working draft", rendered_help)
        self.assertFalse(any(button.label == "Save & Refresh" for button in app.button))

        close_button = next(button for button in app.button if button.label == "Close")
        close_button.click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertFalse(any(button.label == "Close" for button in app.button))


if __name__ == "__main__":
    unittest.main()
