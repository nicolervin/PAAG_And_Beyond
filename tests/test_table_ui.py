from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import pandas as pd

from utils import table_filters, table_ui


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


class DecimalNumberHelpersTests(unittest.TestCase):
    def test_clean_number_hides_unnecessary_trailing_zeroes(self) -> None:
        self.assertEqual(table_ui.format_clean_number(1.0), "1")
        self.assertEqual(table_ui.format_clean_number(1.5), "1.5")
        self.assertEqual(table_ui.format_clean_number(0.02), "0.02")

    def test_decimal_comparison_ignores_insignificant_float_noise(self) -> None:
        self.assertTrue(
            table_ui.decimal_values_equal(1.5, 1.5000000004)
        )
        self.assertFalse(table_ui.decimal_values_equal(1.5, 1.5001))


class DropUntouchedRowsTests(unittest.TestCase):
    def test_empty_string_typed_frame_keeps_boolean_blank_mask(self) -> None:
        dataframe = pd.DataFrame(
            {
                "id": pd.Series(dtype="string"),
                "name": pd.Series(dtype="string"),
            }
        )

        result = table_ui.drop_untouched_new_rows(
            dataframe, identifying_columns=["name"]
        )

        self.assertTrue(result.empty)


class NativeSelectedRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataframe = pd.DataFrame({
            "id": pd.Series(["row-1", "row-2", ""], dtype="string"),
            "name": pd.Series(["Alpha", "Bravo", "New row"], dtype="string"),
        })

    def selected_rows(self, editor_state: dict[str, object]) -> pd.DataFrame:
        with patch.object(
            table_ui.st,
            "session_state",
            {"example_editor": editor_state},
        ):
            return table_ui.native_selected_rows(
                self.dataframe,
                editor_key="example_editor",
            )

    def test_native_deleted_rows_identify_persisted_records_for_confirmation(self) -> None:
        selected = self.selected_rows({"deleted_rows": [0, 1]})

        self.assertEqual(selected["id"].tolist(), ["row-1", "row-2"])

    def test_new_blank_id_rows_are_not_treated_as_deletion_targets(self) -> None:
        selected = self.selected_rows({"deleted_rows": [2]})

        self.assertTrue(selected.empty)


class NativeDeleteConfirmationTests(unittest.TestCase):
    def test_staging_restores_editor_before_confirmation_rerun(self) -> None:
        with (
            patch.object(table_ui, "request_table_editor_reset") as request_reset,
            patch.object(table_ui.st, "rerun", side_effect=RuntimeError("rerun")) as rerun,
        ):
            with self.assertRaisesRegex(RuntimeError, "rerun"):
                table_ui.stage_native_delete_confirmation("example_editor")

        request_reset.assert_called_once_with("example_editor")
        rerun.assert_called_once_with()


class TableEditorResetTests(unittest.TestCase):
    def test_reset_rotates_widget_identity_and_discards_old_editor_state(self) -> None:
        session_state: dict[str, object] = {}
        with patch.object(table_filters.st, "session_state", session_state):
            first_key = table_filters.apply_pending_table_editor_reset("example_editor")
            session_state[first_key] = {"deleted_rows": [0]}

            table_filters.request_table_editor_reset(first_key)
            second_key = table_filters.apply_pending_table_editor_reset(first_key)

        self.assertEqual(first_key, "example_editor__editor_instance_0")
        self.assertEqual(second_key, "example_editor__editor_instance_1")
        self.assertNotIn(first_key, session_state)

    def test_editor_identity_stays_stable_without_a_reset(self) -> None:
        session_state: dict[str, object] = {}
        with patch.object(table_filters.st, "session_state", session_state):
            first_key = table_filters.apply_pending_table_editor_reset("example_editor")
            second_key = table_filters.apply_pending_table_editor_reset(first_key)

        self.assertEqual(first_key, second_key)


class EditableTableFooterTests(unittest.TestCase):
    def test_footer_is_right_aligned_and_uses_standard_save_action(self) -> None:
        footer = Mock()
        footer.button.side_effect = [False, True]
        editor_state = {"edited_rows": {0: {"name": "Changed"}}}

        with (
            patch.object(table_ui.st, "session_state", {"example_editor": editor_state}),
            patch.object(table_ui.st, "container", return_value=footer) as container,
        ):
            actions = table_ui.editable_table_footer(
                editor_key="example_editor",
                key_prefix="example",
                native_row_selection=True,
            )

        container.assert_called_once_with(
            horizontal=True,
            vertical_alignment="center",
            horizontal_alignment="right",
        )
        footer.markdown.assert_called_once_with(
            ":orange[:material/warning: **Unsaved changes**]"
        )
        save_call = footer.button.call_args_list[1]
        self.assertEqual(save_call.args[0], "Save & Refresh")
        self.assertEqual(save_call.kwargs["type"], "primary")
        self.assertEqual(save_call.kwargs["icon"], ":material/save:")
        self.assertTrue(actions.save_and_refresh)


if __name__ == "__main__":
    unittest.main()
