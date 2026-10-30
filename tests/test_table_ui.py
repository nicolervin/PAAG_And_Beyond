from __future__ import annotations

import unittest
from types import SimpleNamespace
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
        self,
        *,
        sort_column: str = "",
        descending: bool = False,
        additional_unsaved_changes: bool = False,
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
                additional_unsaved_changes=additional_unsaved_changes,
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

    def test_sort_controls_lock_for_id_keyed_draft_changes(self) -> None:
        _, controls = self.render_rows(
            sort_column="name", additional_unsaved_changes=True
        )

        self.assertTrue(controls.selectbox.call_args.kwargs["disabled"])
        self.assertTrue(controls.toggle.call_args.kwargs["disabled"])

    def test_default_sort_column_initializes_session_state_and_sorts_blank_strings_last(self) -> None:
        df = pd.DataFrame({
            "id": pd.Series(["row-1", "row-2", "row-draft"], dtype="string"),
            "name": pd.Series(["Zulu", "Alpha", "Draft"], dtype="string"),
            "created_at": pd.Series(
                ["2026-10-21T12:00:00+00:00", "2026-10-21T10:00:00+00:00", ""],
                dtype="string",
            ),
        })
        controls = Mock()
        controls.selectbox.side_effect = lambda *_args, **kwargs: self.session_state[kwargs["key"]]
        controls.toggle.side_effect = lambda *_args, **kwargs: self.session_state[kwargs["key"]]
        with (
            patch.object(table_ui.st, "session_state", self.session_state),
            patch.object(table_ui.st, "container", return_value=controls),
        ):
            rows = table_ui.direct_entry_editor_rows(
                df,
                editor_key="parts_editor",
                sort_columns=["name", "created_at"],
                default_sort_column="created_at",
            )

        self.assertEqual(
            self.session_state["parts_editor_external_sort_column"],
            "created_at",
        )
        self.assertEqual(rows["id"].tolist(), ["row-2", "row-1", "row-draft"])


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


class PartNumberColorTests(unittest.TestCase):
    def test_part_number_style_is_trimmed_deterministic_and_contrast_safe(self) -> None:
        style = table_ui.part_number_cell_style("PN-100")
        self.assertEqual(style, table_ui.part_number_cell_style("  PN-100  "))
        self.assertIn("background-color: #", style)
        self.assertIn("color: #17212B", style)
        self.assertNotEqual(style, table_ui.part_number_cell_style("PN-101"))
        self.assertEqual(table_ui.part_number_cell_style(""), "")


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


class SelectedDataframeRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataframe = pd.DataFrame({
            "id": pd.Series(["row-1", "row-2", ""], dtype="string"),
            "name": pd.Series(["Alpha", "Bravo", "New row"], dtype="string"),
        })

    def test_selection_event_resolves_one_or_multiple_saved_rows(self) -> None:
        event = SimpleNamespace(selection=SimpleNamespace(rows=[0, 1]))

        selected = table_ui.selected_dataframe_rows(self.dataframe, event)

        self.assertEqual(selected["id"].tolist(), ["row-1", "row-2"])

    def test_selection_event_supports_mapping_state_and_rejects_invalid_rows(self) -> None:
        selected = table_ui.selected_dataframe_rows(
            self.dataframe,
            {"selection": {"rows": [1, 1, 20, "invalid", 2]}},
        )

        self.assertEqual(selected["id"].tolist(), ["row-2"])

    def test_missing_selection_or_id_column_returns_empty_rows(self) -> None:
        self.assertTrue(
            table_ui.selected_dataframe_rows(self.dataframe, {}).empty
        )
        self.assertTrue(
            table_ui.selected_dataframe_rows(
                self.dataframe.drop(columns=["id"]),
                {"selection": {"rows": [0]}},
            ).empty
        )


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

    def test_undo_last_table_edit_steps_back_one_edit_and_preserves_prior_edits(self) -> None:
        session_state: dict[str, object] = {}
        base_df = pd.DataFrame(
            {
                "id": ["row-1", "row-2"],
                "name": ["Alpha", "Bravo"],
                "qty": [1.0, 2.0],
            }
        )
        with patch.object(table_filters.st, "session_state", session_state):
            key0 = table_filters.apply_pending_table_editor_reset("example_editor")
            self.assertFalse(table_filters.can_undo_last_table_edit(key0))

            # First edit: change row 0 name
            session_state[key0] = {"edited_rows": {0: {"name": "Alpha Edited"}}, "added_rows": [], "deleted_rows": []}
            self.assertTrue(table_filters.can_undo_last_table_edit(key0))

            # Second edit: fat-finger row 1 qty
            session_state[key0] = {
                "edited_rows": {0: {"name": "Alpha Edited"}, 1: {"qty": 999.0}},
                "added_rows": [],
                "deleted_rows": [],
            }
            self.assertTrue(table_filters.can_undo_last_table_edit(key0))

            # Click "Undo last edit": should step back to only row 0 edited
            self.assertTrue(table_filters.undo_last_table_edit(key0))
            self.assertIn("Qty", table_filters.last_table_undo_redo_message(key0))
            key1 = table_filters.apply_pending_table_editor_reset(key0)
            self.assertEqual(key1, "example_editor__editor_instance_1")
            self.assertTrue(table_filters.was_table_editor_undo_reset(key1))
            effective = table_filters.get_effective_table_editor_state(key1)
            self.assertEqual(effective["edited_rows"], {0: {"name": "Alpha Edited"}})
            self.assertTrue(table_filters.has_unsaved_table_changes(key1))

            # Verify wrapped st.data_editor receives seeded DataFrame and exposes combined state
            captured_input_dfs: list[pd.DataFrame] = []

            def fake_orig_editor(df: pd.DataFrame, *_args, **kwargs):
                captured_input_dfs.append(df.copy())
                k = kwargs.get("key")
                if k and k not in session_state:
                    session_state[k] = {"edited_rows": {}, "added_rows": [], "deleted_rows": []}
                return df.copy()

            with patch.object(table_filters, "_ORIG_DATA_EDITOR", side_effect=fake_orig_editor):
                returned_df = table_filters._wrap_data_editor(base_df, key=key1)

            self.assertEqual(captured_input_dfs[0]["name"].tolist(), ["Alpha Edited", "Bravo"])
            self.assertEqual(captured_input_dfs[0]["qty"].tolist(), [1.0, 2.0])
            self.assertEqual(returned_df["name"].tolist(), ["Alpha Edited", "Bravo"])
            self.assertEqual(session_state[key1]["edited_rows"], {0: {"name": "Alpha Edited"}})
            self.assertFalse(table_filters.was_table_editor_undo_reset(key1))
            self.assertTrue(table_filters.can_undo_last_table_edit(key1))

            # Click "Undo last edit" a second time: should step back to clean state
            self.assertTrue(table_filters.can_redo_last_table_edit(key1))
            self.assertTrue(table_filters.undo_last_table_edit(key1))
            key2 = table_filters.apply_pending_table_editor_reset(key1)
            self.assertEqual(key2, "example_editor__editor_instance_2")
            self.assertFalse(table_filters.has_unsaved_table_changes(key2))
            self.assertFalse(table_filters.can_undo_last_table_edit(key2))
            self.assertTrue(table_filters.can_redo_last_table_edit(key2))

            # Click "Redo last edit": should restore first edit (row 0 name)
            self.assertTrue(table_filters.redo_last_table_edit(key2))
            self.assertIn("Alpha Edited", table_filters.last_table_undo_redo_message(key2))
            key3 = table_filters.apply_pending_table_editor_reset(key2)
            self.assertEqual(key3, "example_editor__editor_instance_3")
            self.assertEqual(
                table_filters.get_effective_table_editor_state(key3)["edited_rows"],
                {0: {"name": "Alpha Edited"}},
            )
            self.assertTrue(table_filters.can_undo_last_table_edit(key3))
            self.assertTrue(table_filters.can_redo_last_table_edit(key3))

            # Click "Redo last edit" again: should restore second edit (row 0 name + row 1 qty)
            self.assertTrue(table_filters.redo_last_table_edit(key3))
            key4 = table_filters.apply_pending_table_editor_reset(key3)
            self.assertEqual(key4, "example_editor__editor_instance_4")
            self.assertEqual(
                table_filters.get_effective_table_editor_state(key4)["edited_rows"],
                {0: {"name": "Alpha Edited"}, 1: {"qty": 999.0}},
            )
            self.assertFalse(table_filters.can_redo_last_table_edit(key4))

            # Undo once, then make a brand-new edit: redo stack should clear
            self.assertTrue(table_filters.undo_last_table_edit(key4))
            key5 = table_filters.apply_pending_table_editor_reset(key4)
            self.assertTrue(table_filters.can_redo_last_table_edit(key5))
            session_state[key5] = {
                "edited_rows": {1: {"name": "Bravo Edited"}},
                "added_rows": [],
                "deleted_rows": [],
            }
            self.assertFalse(table_filters.can_redo_last_table_edit(key5))


class StableIdEditorDraftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = pd.DataFrame(
            {
                "id": ["part-1", "part-2"],
                "part_number": ["P-001", "P-002"],
                "active": [True, True],
                "description": ["First", "Second"],
            }
        )

    def test_active_edit_survives_when_changed_row_is_filtered_out(self) -> None:
        draft, captured = table_filters.capture_id_keyed_editor_draft(
            self.saved,
            {"edited_rows": {0: {"active": False}}},
        )
        filtered_next_run = self.saved.iloc[[1]].reset_index(drop=True)

        draft, captured = table_filters.capture_id_keyed_editor_draft(
            filtered_next_run,
            {"edited_rows": {0: {"active": False}}},
            draft,
            captured,
        )
        merged = table_filters.apply_id_keyed_editor_draft(self.saved, draft)

        self.assertFalse(bool(merged.loc[merged["id"].eq("part-1"), "active"].iloc[0]))
        self.assertTrue(bool(merged.loc[merged["id"].eq("part-2"), "active"].iloc[0]))

    def test_manual_edits_for_multiple_parts_are_retained_by_id(self) -> None:
        draft, captured = table_filters.capture_id_keyed_editor_draft(
            self.saved,
            {"edited_rows": {0: {"description": "Updated first"}}},
        )
        draft, captured = table_filters.capture_id_keyed_editor_draft(
            self.saved.iloc[[1]].reset_index(drop=True),
            {"edited_rows": {}},
            draft,
            captured,
        )
        draft, _ = table_filters.capture_id_keyed_editor_draft(
            self.saved.iloc[[1]].reset_index(drop=True),
            {"edited_rows": {0: {"active": False}}},
            draft,
            captured,
        )

        merged = table_filters.apply_id_keyed_editor_draft(self.saved, draft)

        self.assertEqual(
            merged.loc[merged["id"].eq("part-1"), "description"].iloc[0],
            "Updated first",
        )
        self.assertFalse(bool(merged.loc[merged["id"].eq("part-2"), "active"].iloc[0]))


class EditableTableFooterTests(unittest.TestCase):
    def test_footer_is_right_aligned_and_uses_standard_save_action(self) -> None:
        footer = Mock()
        footer.button.side_effect = [False, False, False, True]
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
        undo_last_call = footer.button.call_args_list[0]
        self.assertEqual(undo_last_call.args[0], "Undo last edit")
        self.assertFalse(undo_last_call.kwargs["disabled"])
        redo_last_call = footer.button.call_args_list[1]
        self.assertEqual(redo_last_call.args[0], "Redo last edit")
        self.assertTrue(redo_last_call.kwargs["disabled"])
        discard_call = footer.button.call_args_list[2]
        self.assertEqual(discard_call.args[0], "Discard all edits")
        save_call = footer.button.call_args_list[3]
        self.assertEqual(save_call.args[0], "Save & Refresh")
        self.assertEqual(save_call.kwargs["type"], "primary")
        self.assertEqual(save_call.kwargs["icon"], ":material/save:")
        self.assertTrue(actions.save_and_refresh)

    def test_footer_can_render_one_additional_action_before_undo(self) -> None:
        footer = Mock()
        footer.button.side_effect = [True, False, False, False, False]

        with (
            patch.object(table_ui.st, "session_state", {"example_editor": {}}),
            patch.object(table_ui.st, "container", return_value=footer),
        ):
            actions = table_ui.editable_table_footer(
                editor_key="example_editor",
                key_prefix="example",
                additional_action_label="Move pitches",
                additional_action_icon=":material/drive_file_move:",
                additional_action_key="move_pitches",
            )

        move_call = footer.button.call_args_list[0]
        self.assertEqual(move_call.args[0], "Move pitches")
        self.assertEqual(move_call.kwargs["key"], "move_pitches")
        self.assertTrue(actions.additional_action)

    def test_filter_table_returns_range_index_when_filtered(self) -> None:
        df = pd.DataFrame(
            {
                "id": ["id-1", "id-2", "id-3"],
                "part_number": ["P-100", "P-200", "P-300"],
                "description": ["Alpha", "Beta", "Gamma"],
            }
        )
        controls = Mock()
        controls.text_input.return_value = "Beta"
        session_state: dict[str, object] = {}
        with (
            patch.object(table_filters.st, "session_state", session_state),
            patch.object(table_filters.st, "container", return_value=controls),
            patch.object(table_filters.st, "caption"),
        ):
            filtered = table_filters.filter_table(
                df,
                key="test_filter",
                search_columns=["part_number", "description"],
            )
        self.assertEqual(len(filtered), 1)
        self.assertIsInstance(filtered.index, pd.RangeIndex)
        self.assertEqual(list(filtered.index), [0])

        controls.text_input.return_value = "NoSuchPart"
        with (
            patch.object(table_filters.st, "session_state", session_state),
            patch.object(table_filters.st, "container", return_value=controls),
            patch.object(table_filters.st, "caption"),
        ):
            empty_filtered = table_filters.filter_table(
                df,
                key="test_filter",
                search_columns=["part_number", "description"],
            )
        self.assertTrue(empty_filtered.empty)
        self.assertIsInstance(empty_filtered.index, pd.RangeIndex)

    def test_paginate_table_rows_and_merge_filtered_edits_preserve_other_pages(self) -> None:
        df = pd.DataFrame(
            {
                "id": [f"id-{i}" for i in range(120)],
                "part_number": [f"P-{i:03d}" for i in range(120)],
                "description": [f"Item {i}" for i in range(120)],
            }
        )
        session_state: dict[str, object] = {
            "large_table_page_size": 50,
            "large_table_page_number": 2,
        }
        with patch.object(table_ui.st, "session_state", session_state):
            page_df = table_ui.paginate_table_rows(
                df,
                key="large_table",
                default_page_size=50,
                page_size_options=(50, 100),
                render_controls=False,
            )
        self.assertEqual(len(page_df), 50)
        self.assertEqual(page_df.iloc[0]["id"], "id-50")
        self.assertEqual(page_df.iloc[-1]["id"], "id-99")

        edited_page = page_df.copy()
        edited_page.loc[0, "description"] = "Updated Item 50"
        merged = table_filters.merge_filtered_edits(df, page_df, edited_page)
        self.assertEqual(len(merged), 120)
        self.assertEqual(
            merged.loc[merged["id"].eq("id-50"), "description"].iloc[0],
            "Updated Item 50",
        )
        self.assertEqual(
            merged.loc[merged["id"].eq("id-0"), "description"].iloc[0],
            "Item 0",
        )

    def test_filter_table_renders_keyword_in_custom_container(self) -> None:
        df = pd.DataFrame(
            {
                "id": ["id-1", "id-2"],
                "part_number": ["P-100", "P-200"],
                "description": ["Alpha", "Beta"],
            }
        )
        controls = Mock()
        keyword_slot = Mock()
        keyword_slot.text_input.return_value = "P-200"
        session_state: dict[str, object] = {}
        with (
            patch.object(table_filters.st, "session_state", session_state),
            patch.object(table_filters.st, "container", return_value=controls),
            patch.object(table_filters.st, "caption"),
        ):
            filtered = table_filters.filter_table(
                df,
                key="test_filter_slot",
                search_columns=["part_number", "description"],
                keyword_container=keyword_slot,
            )
        controls.text_input.assert_not_called()
        keyword_slot.text_input.assert_called_once()
        self.assertEqual(filtered["part_number"].tolist(), ["P-200"])


class UnifiedEditorSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.df = pd.DataFrame(
            {
                "id": ["row-1", "row-2", "__draft_new__0"],
                "name": ["First", "Second", "Draft"],
            }
        )

    def test_prepare_and_resolve_editor_selection_with_select_all(self) -> None:
        session_state: dict[str, object] = {"_select_all_my_editor": True}
        with patch.object(table_ui.st, "session_state", session_state):
            prepared = table_ui.prepare_editor_selection_column(
                self.df, editor_key="my_editor__editor_instance_0"
            )
            self.assertEqual(prepared["selected"].tolist(), [True, True, False])

            selected = table_ui.resolve_editor_selected_rows(
                prepared,
                prepared,
                editor_key="my_editor__editor_instance_0",
            )
            self.assertEqual(selected["id"].tolist(), ["row-1", "row-2"])

    def test_reset_table_editor_selection_preserves_non_selection_cell_edits(self) -> None:
        session_state: dict[str, object] = {}
        with patch.object(table_filters.st, "session_state", session_state):
            key0 = table_filters.apply_pending_table_editor_reset("my_editor")
            session_state[key0] = {
                "edited_rows": {
                    0: {"selected": True, "name": "Updated First"},
                    1: {"selected": True},
                },
                "added_rows": [],
                "deleted_rows": [],
            }
            session_state["_select_all_my_editor"] = True
            table_filters.reset_table_editor_selection(key0)
            key1 = table_filters.apply_pending_table_editor_reset(key0)
            effective = table_filters.get_effective_table_editor_state(key1)

        self.assertEqual(effective["edited_rows"], {0: {"name": "Updated First"}})
        self.assertTrue(session_state.get("_select_all_my_editor"))

    def test_wrap_data_editor_freezes_base_dataframe_during_active_edits(self) -> None:
        session_state: dict[str, object] = {}
        initial_df = pd.DataFrame(
            {
                "id": ["row-1", "row-2"],
                "pitch_type": ["Pitch", "Pitch"],
            }
        )
        mutated_df = pd.DataFrame(
            {
                "id": ["row-1", "row-2"],
                "pitch_type": ["Waterspider", "Pitch"],
            }
        )
        captured_inputs: list[pd.DataFrame] = []

        def fake_orig_editor(df: pd.DataFrame, *_args, **kwargs):
            captured_inputs.append(df.copy())
            k = kwargs.get("key")
            if k and k not in session_state:
                session_state[k] = {"edited_rows": {}, "added_rows": [], "deleted_rows": []}
            return df.copy()

        with (
            patch.object(table_filters.st, "session_state", session_state),
            patch.object(table_filters, "_ORIG_DATA_EDITOR", side_effect=fake_orig_editor),
        ):
            key0 = table_filters.apply_pending_table_editor_reset("yamazumi_pitch_editor")
            # Initial render with no active edits stores frozen base
            table_filters._wrap_data_editor(initial_df, key=key0)
            self.assertEqual(captured_inputs[-1]["pitch_type"].tolist(), ["Pitch", "Pitch"])

            # Simulate user editing row 0 and page code mutating the input DataFrame on rerun
            session_state[key0] = {
                "edited_rows": {0: {"pitch_type": "Waterspider"}},
                "added_rows": [],
                "deleted_rows": [],
            }
            table_filters._wrap_data_editor(mutated_df, key=key0)
            # Base DataFrame passed to _ORIG_DATA_EDITOR must remain frozen to prevent (0, 0) focus reset
            self.assertEqual(captured_inputs[-1]["pitch_type"].tolist(), ["Pitch", "Pitch"])

            # After explicit reset, the new DataFrame becomes the fresh base
            table_filters.request_table_editor_reset(key0)
            key1 = table_filters.apply_pending_table_editor_reset(key0)
            table_filters._wrap_data_editor(mutated_df, key=key1)
            self.assertEqual(captured_inputs[-1]["pitch_type"].tolist(), ["Waterspider", "Pitch"])

    def test_direct_entry_editor_rows_keeps_caption_mounted_when_unlocked_and_locked(self) -> None:
        df = pd.DataFrame({"id": ["r1"], "name": ["Alpha"]})
        unlocked_controls = Mock()
        unlocked_controls.selectbox.return_value = ""
        unlocked_controls.toggle.return_value = False
        with (
            patch.object(table_ui.st, "session_state", {"test_editor": {}}),
            patch.object(table_ui.st, "container", return_value=unlocked_controls),
        ):
            table_ui.direct_entry_editor_rows(
                df,
                editor_key="test_editor",
                sort_columns=["name"],
            )
        unlocked_controls.caption.assert_called_once()

        locked_controls = Mock()
        locked_controls.selectbox.return_value = ""
        locked_controls.toggle.return_value = False
        with (
            patch.object(
                table_ui.st,
                "session_state",
                {"test_editor": {"edited_rows": {0: {"name": "Beta"}}}},
            ),
            patch.object(table_ui.st, "container", return_value=locked_controls),
        ):
            table_ui.direct_entry_editor_rows(
                df,
                editor_key="test_editor",
                sort_columns=["name"],
            )
        locked_controls.caption.assert_called_once()

    def test_request_unsaved_state_change_completes_when_clean(self) -> None:
        session_state: dict[str, object] = {
            "active_model": "model-1",
            "stale_key": "remove-me",
        }
        with (
            patch.object(table_ui.st, "session_state", session_state),
            patch.object(table_ui.st, "rerun"),
        ):
            table_ui.request_unsaved_state_change(
                {"active_model": "model-2"},
                label="Model 2",
                nav_kind="model",
                clear_keys=["stale_key"],
                clear_unsaved_tracking=True,
            )
            self.assertIn("_pending_unsaved_nav", session_state)
            table_ui.finalize_unsaved_tracking({})
        self.assertEqual(session_state.get("active_model"), "model-2")
        self.assertNotIn("stale_key", session_state)
        self.assertNotIn("_pending_unsaved_nav", session_state)


if __name__ == "__main__":
    unittest.main()
