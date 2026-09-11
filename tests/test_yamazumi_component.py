from __future__ import annotations

import json
import inspect
import unittest
from unittest.mock import patch

from utils import yamazumi_board as board_module


class YamazumiComponentTests(unittest.TestCase):
    def test_unassigned_card_is_always_rendered_and_accepts_drops(self) -> None:
        self.assertIn('id="unassigned"', board_module._HTML)
        self.assertIn(
            "unassigned.appendChild(makePitch({",
            board_module._JS,
        )
        self.assertIn("pitch_number: 'Unassigned'", board_module._JS)
        self.assertIn(
            "const acceptsWork = !pitch.id || pitch.status === 'Active'",
            board_module._JS,
        )
        self.assertIn("card.ondrop = event =>", board_module._JS)
        self.assertIn("pitch_id: pitch.id || null", board_module._JS)

    def test_drop_slots_emit_position_anchors_without_changing_orientation(self) -> None:
        self.assertIn("const displayItems = side === 'north' ? [...items].reverse() : items", board_module._JS)
        self.assertIn("appendDropSlot(logicalIndex + 1)", board_module._JS)
        self.assertIn("before_element_id: items[logicalIndex]?.id || null", board_module._JS)
        self.assertIn("after_element_id: logicalIndex > 0", board_module._JS)
        self.assertIn("paag_yamazumi_drag_board_v17", inspect.getsource(board_module))

    def test_nullable_link_fields_are_strict_json_at_component_boundary(self) -> None:
        with patch.object(
            board_module, "_YAMAZUMI_BOARD", return_value=object()
        ) as mounted_component:
            board_module.yamazumi_board(
                [{"id": "pitch-1", "assignment_id": float("nan")}],
                [
                    {
                        "id": "element-1",
                        "assignment_id": float("nan"),
                        "process_element_id": float("nan"),
                    }
                ],
                ["Base"],
                float("nan"),
                key="yamazumi-test",
                on_move=lambda: None,
                on_add_pitch=lambda: None,
                on_add_element=lambda: None,
                on_edit_pitch=lambda: None,
                on_edit_element=lambda: None,
            )

        payload = mounted_component.call_args.kwargs["data"]
        self.assertIsNone(payload["pitches"][0]["assignment_id"])
        self.assertIsNone(payload["elements"][0]["assignment_id"])
        self.assertIsNone(payload["elements"][0]["process_element_id"])
        self.assertEqual(payload["takt"], 0.0)
        encoded = json.dumps(payload, allow_nan=False)
        self.assertNotIn("NaN", encoded)


if __name__ == "__main__":
    unittest.main()
