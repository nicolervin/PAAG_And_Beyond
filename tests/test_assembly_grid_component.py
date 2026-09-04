from __future__ import annotations

import json
import unittest
from pathlib import Path

from utils.component_payload import is_empty_unsaved_grid_category, json_safe


class AssemblyGridComponentTests(unittest.TestCase):
    def test_component_payload_is_strict_json(self) -> None:
        payload = json_safe(
            {
                "missing": float("nan"),
                "positive_infinity": float("inf"),
                "nested": [1.5, float("-inf")],
            }
        )

        self.assertEqual(
            payload,
            {
                "missing": None,
                "positive_infinity": None,
                "nested": [1.5, None],
            },
        )
        encoded = json.dumps(payload, allow_nan=False)
        self.assertNotIn("NaN", encoded)

    def test_only_blank_unsaved_category_is_ignored_on_save(self) -> None:
        blank = {
            "id": "",
            "ebom_name": "",
            "display_name": "",
            "installed_section_id": "",
            "cells": {"model-1": {"assembly_number": ""}},
        }
        self.assertTrue(is_empty_unsaved_grid_category(blank))

        for field in ("id", "ebom_name", "display_name", "installed_section_id"):
            category = dict(blank)
            category[field] = "entered"
            self.assertFalse(is_empty_unsaved_grid_category(category))

        mapped = {**blank, "cells": {"model-1": {"assembly_number": "ASM-1"}}}
        self.assertFalse(is_empty_unsaved_grid_category(mapped))

    def test_component_additions_stay_in_the_frontend_draft(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "utils" / "assembly_grid.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("setTriggerValue('add_component'", source)
        self.assertIn("otherCell.components.push({", source)
        self.assertIn("emitDraft()\n          render()", source)
        self.assertIn("Add Subassembly", source)
        self.assertIn("Add part", source)
        self.assertIn("item.part_name", source)

    def test_grid_restores_click_and_tab_focus_after_draft_reruns(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "utils" / "assembly_grid.py"
        ).read_text(encoding="utf-8")

        self.assertIn("table.onpointerdown = event =>", source)
        self.assertIn("table.onkeydown = event =>", source)
        self.assertIn("event.key !== 'Tab'", source)
        self.assertIn("event.shiftKey ? -1 : 1", source)
        self.assertIn("queueFocusRestore(next.dataset.gridFocus)", source)
        self.assertIn("target.focus({preventScroll:true})", source)
        self.assertIn("modelCell.querySelector('.assembly-entry')", source)
        self.assertIn("const focusState = new WeakMap()", source)
        self.assertIn("if (!instanceFocus.key) queueFocusRestore", source)
        self.assertIn('"paag_assembly_grid_v6"', source)


if __name__ == "__main__":
    unittest.main()
