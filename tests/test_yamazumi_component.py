from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from utils import yamazumi_board as board_module


class YamazumiComponentTests(unittest.TestCase):
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
