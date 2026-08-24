from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import pandas as pd

from utils import table_ui


class DirectEntryEditorRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session_state: dict[str, object] = {}
        self.dataframe = pd.DataFrame({
            "id": pd.Series(["row-1", "row-2"], dtype="string"),
            "name": pd.Series(["Alpha", "Bravo"], dtype="string"),
            "active": pd.Series([True, False], dtype="bool"),
            "tags": pd.Series([["Zulu"], ["Alpha"]], dtype="object"),
        })

    def render_rows(
        self, *, sort_column: str = "", descending: bool = False
    ) -> tuple[pd.DataFrame, Mock]:
        controls = Mock()
        controls.selectbox.return_value = sort_column
        controls.toggle.return_value = descending
        with (
            patch.object(table_ui.st, "session_state", self.session_state),
            patch.object(table_ui.st, "container", return_value=controls),
        ):
            rows = table_ui.direct_entry_editor_rows(
                self.dataframe,
                editor_key="example_editor",
                sort_columns=["name", "active", "tags"],
            )
        return rows, controls

    def test_saved_order_is_unchanged_without_external_sort(self) -> None:
        rows, _ = self.render_rows()

        pd.testing.assert_frame_equal(rows, self.dataframe)

    def test_external_sort_can_reverse_saved_rows(self) -> None:
        rows, _ = self.render_rows(sort_column="name", descending=True)

        self.assertEqual(rows["name"].tolist(), ["Bravo", "Alpha"])

    def test_external_sort_supports_multi_value_columns(self) -> None:
        rows, _ = self.render_rows(sort_column="tags")

        self.assertEqual(rows["name"].tolist(), ["Bravo", "Alpha"])

    def test_sort_controls_lock_while_editor_has_draft_changes(self) -> None:
        self.session_state["example_editor"] = {
            "edited_rows": {0: {"name": "Changed"}}
        }

        _, controls = self.render_rows(sort_column="name")

        self.assertTrue(controls.selectbox.call_args.kwargs["disabled"])
        self.assertTrue(controls.toggle.call_args.kwargs["disabled"])


if __name__ == "__main__":
    unittest.main()
