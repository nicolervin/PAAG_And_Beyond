from __future__ import annotations

import json
import inspect
import unittest
from unittest.mock import patch

from utils import yamazumi_board as board_module


class YamazumiComponentTests(unittest.TestCase):
    def test_unassigned_card_is_only_rendered_for_unassigned_work(self) -> None:
        self.assertIn('id="unassigned"', board_module._HTML)
        self.assertIn(
            "data.show_unassigned && Object.keys(grouped.__unassigned__ || {}).length",
            board_module._JS,
        )
        self.assertIn("unassigned.appendChild(makePitch({", board_module._JS)
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
        self.assertIn("paag_yamazumi_drag_board_v20", inspect.getsource(board_module))

    def test_selected_time_unit_scales_labels_and_preserves_height_ratio(self) -> None:
        self.assertIn("const displayTime = value =>", board_module._JS)
        self.assertIn("${formatTime(total)} / ${formatTakt(data.takt)}", board_module._JS)
        self.assertIn(
            "displayTime(item.time_s) / displayTakt * taktPixels", board_module._JS
        )

    def test_assigned_lanes_use_an_accurate_takt_line_and_proportional_scale(self) -> None:
        self.assertIn("const taktPixels = 155", board_module._JS)
        self.assertIn(
            "Number.isFinite(Number(data.takt)) && Number(data.takt) > 0",
            board_module._JS,
        )
        self.assertIn("if (pitch.id && hasTakt) stack.classList.add('takt-scale')", board_module._JS)
        self.assertIn("drawTaktLine(north, 'north')", board_module._JS)
        self.assertIn("drawTaktLine(south, 'south')", board_module._JS)
        self.assertIn("lane.scrollWidth - 4", board_module._JS)
        self.assertIn("Math.max(0, displayTime(item.time_s)", board_module._JS)
        self.assertNotIn("Math.max(34, displayTime(item.time_s)", board_module._JS)

    def test_unassigned_and_invalid_takt_do_not_receive_a_takt_line(self) -> None:
        self.assertIn("if (!hasTakt) return", board_module._JS)
        self.assertIn("if (pitch.id && hasTakt)", board_module._JS)
        self.assertNotIn("drawTaktLine(unassigned", board_module._JS)
        self.assertIn(": 34", board_module._JS)

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
                time_unit="minutes",
                takt_time_unit="hours",
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
        self.assertEqual(payload["time_unit"], "minutes")
        self.assertEqual(payload["seconds_per_unit"], 60.0)
        self.assertEqual(payload["time_decimals"], 3)
        self.assertEqual(payload["time_suffix"], "min")
        self.assertEqual(payload["takt_time_unit"], "hours")
        self.assertEqual(payload["takt_seconds_per_unit"], 3600.0)
        self.assertEqual(payload["takt_decimals"], 4)
        self.assertEqual(payload["takt_suffix"], "hr")
        self.assertTrue(payload["show_unassigned"])
        encoded = json.dumps(payload, allow_nan=False)
        self.assertNotIn("NaN", encoded)

    def test_payload_hides_and_shows_unassigned_from_current_elements(self) -> None:
        callbacks = {
            "on_move": lambda: None,
            "on_add_pitch": lambda: None,
            "on_add_element": lambda: None,
            "on_edit_pitch": lambda: None,
            "on_edit_element": lambda: None,
        }
        with patch.object(board_module, "_YAMAZUMI_BOARD", return_value=object()) as mount:
            board_module.yamazumi_board(
                [], [{"id": "assigned", "pitch_id": "pitch-1"}], ["Base"], 60,
                time_unit="seconds", takt_time_unit="seconds",
                key="assigned-only", **callbacks,
            )
            self.assertFalse(mount.call_args.kwargs["data"]["show_unassigned"])
            board_module.yamazumi_board(
                [],
                [
                    {"id": "assigned", "pitch_id": "pitch-1"},
                    {"id": "unassigned-one", "pitch_id": None},
                    {"id": "unassigned-two", "pitch_id": None},
                ],
                ["Base"],
                60,
                time_unit="seconds",
                takt_time_unit="seconds",
                key="with-unassigned",
                **callbacks,
            )
            self.assertTrue(mount.call_args.kwargs["data"]["show_unassigned"])


if __name__ == "__main__":
    unittest.main()
