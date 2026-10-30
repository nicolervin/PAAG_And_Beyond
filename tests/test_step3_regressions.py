from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from utils.table_filters import (
    _resolve_editor_instance_key,
    apply_pending_table_editor_reset,
    has_unsaved_table_changes,
)
from utils.table_ui import table_has_unsaved_changes


class Step3RegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        st.session_state.clear()

    def tearDown(self) -> None:
        st.session_state.clear()

    # ------------------------------------------------------------------
    # Item 9: Standardize guarded_tabs consumption across pages
    # ------------------------------------------------------------------
    def test_functional_pages_do_not_use_manual_tab_enter_or_stop(self) -> None:
        for rel_path in (
            "app_pages/functional_materials.py",
            "app_pages/functional_safety.py",
            "app_pages/functional_ergonomics.py",
        ):
            source = (ROOT / rel_path).read_text(encoding="utf-8")
            self.assertNotIn("review_tab.__enter__()", source, msg=rel_path)
            self.assertIn("if equipment_tab.open:", source, msg=rel_path)
            self.assertIn("elif review_tab.open:", source, msg=rel_path)
            self.assertIn("with review_tab:", source, msg=rel_path)

    def test_all_guarded_tabs_blocks_check_open_property(self) -> None:
        expectations = {
            "utils/control_plan_ui.py": [
                "if characteristics_tab.open:",
                "elif flow_tab.open:",
            ],
            "utils/equipment_ui.py": [
                "if tab1.open:",
                "elif tab2.open:",
                "elif tab3.open:",
                "elif tab4.open:",
            ],
            "app_pages/bom_tree.py": [
                "if tab_view.open:",
                "elif tab_author.open:",
            ],
            "app_pages/fishbone.py": [
                "if assign_parts_tab.open:",
                "if fishbone_tab.open:",
            ],
            "app_pages/process.py": [
                "if tab_plan.open:",
                "elif tab_flow.open:",
                "elif tab_slides.open:",
            ],
        }
        for rel_path, snippets in expectations.items():
            source = (ROOT / rel_path).read_text(encoding="utf-8")
            ast.parse(source)
            for snippet in snippets:
                self.assertIn(snippet, source, msg=f"{rel_path} missing {snippet}")

    # ------------------------------------------------------------------
    # Item 10: Broken table reset keys & unsaved-changes tracking bugs
    # ------------------------------------------------------------------
    def test_resolve_editor_instance_key_handles_layout_suffixed_keys(self) -> None:
        base_versioned_key = apply_pending_table_editor_reset("parts_editor")
        self.assertEqual(base_versioned_key, "parts_editor__editor_instance_0")

        suffixed_widget_key = f"{base_versioned_key}_layout_token_123"
        st.session_state[suffixed_widget_key] = {
            "edited_rows": {0: {"part_number": "P-100"}},
            "added_rows": [],
            "deleted_rows": [],
        }

        self.assertEqual(
            _resolve_editor_instance_key(base_versioned_key),
            suffixed_widget_key,
        )
        self.assertTrue(
            table_has_unsaved_changes(base_versioned_key, native_row_selection=True)
        )
        self.assertTrue(
            has_unsaved_table_changes(base_versioned_key)
        )

    def test_fishbone_framework_editor_and_pool_save_fixes(self) -> None:
        source = (ROOT / "app_pages/fishbone.py").read_text(encoding="utf-8")
        maint_body = source.split("def _render_framework_maintenance():", 1)[1]
        self.assertNotIn(
            '"assembly_framework_editor"',
            maint_body,
            "Hardcoded 'assembly_framework_editor' must not appear inside _render_framework_maintenance",
        )
        self.assertIn("elif trigger_pool_save:", source)
        self.assertIn("request_table_editor_reset(pool_editor_key)", source)

    def test_bom_tree_and_help_hub_editor_reset_keys(self) -> None:
        bom_source = (ROOT / "app_pages/bom_tree.py").read_text(encoding="utf-8")
        self.assertNotIn("bom_author_grid_", bom_source)
        self.assertIn('request_table_editor_reset(f"bom_grid_editor_{t_mid}")', bom_source)

        help_source = (ROOT / "utils/help_hub.py").read_text(encoding="utf-8")
        self.assertIn(
            'editor_key = apply_pending_table_editor_reset("help_hub_feedback_table_editor")',
            help_source,
        )

    def test_ergonomics_hazard_dialog_and_pfmea_pattern_manager_register_unsaved_source(self) -> None:
        ergo_source = (ROOT / "app_pages/functional_ergonomics.py").read_text(encoding="utf-8")
        self.assertIn("register_unsaved_source(", ergo_source)
        self.assertIn("trigger_tags_save, trigger_tags_discard = register_unsaved_source(", ergo_source)

        pfmea_source = (ROOT / "utils/pfmea_ui.py").read_text(encoding="utf-8")
        self.assertIn("trigger_pattern_save, trigger_pattern_discard = register_unsaved_source(", pfmea_source)

    # ------------------------------------------------------------------
    # Item 11: Structural consistency across functional review pages
    # ------------------------------------------------------------------
    def test_functional_pages_use_scenario_aware_scope_and_module_level_history(self) -> None:
        for rel_path in (
            "app_pages/functional_quality.py",
            "app_pages/functional_materials.py",
            "app_pages/functional_safety.py",
            "app_pages/functional_ergonomics.py",
            "app_pages/functional_equipment.py",
        ):
            source = (ROOT / rel_path).read_text(encoding="utf-8")
            self.assertIn('scope="scenario-aware"', source, msg=rel_path)
            self.assertNotIn('scope="scenario"', source, msg=rel_path)

        for rel_path in (
            "app_pages/functional_materials.py",
            "app_pages/functional_safety.py",
            "app_pages/functional_ergonomics.py",
        ):
            source = (ROOT / rel_path).read_text(encoding="utf-8")
            lines = source.splitlines()
            top_level_expanders = [
                line for line in lines if line.startswith("with st.expander(") and "History" in line
            ]
            self.assertTrue(
                len(top_level_expanders) >= 1,
                msg=f"{rel_path} should have a module-level History expander outside tab blocks",
            )

    # ------------------------------------------------------------------
    # Item 12: Split-workspace DuplicateWidgetID collisions & alias pages
    # ------------------------------------------------------------------
    def test_streamlit_app_canonicalizes_alias_url_paths_and_sets_icons(self) -> None:
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("_ALIAS_TO_CANONICAL_URL_PATH", source)
        self.assertIn("def _canonical_workspace_page_key(", source)
        for alias, canonical in (
            ("Equipment", "functional_equipment"),
            ("Ergonomics", "functional_ergonomics"),
            ("Quality", "functional_quality"),
            ("Materials", "functional_materials"),
            ("Safety", "functional_safety"),
        ):
            self.assertIn(f'"{alias}": "{canonical}"', source)

    def test_equipment_ui_scopes_matrix_and_type_manager_keys(self) -> None:
        source = (ROOT / "utils/equipment_ui.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn(
            'def render_equipment_type_manager(\n    project_id: str,\n    *,\n    wrap_in_expander: bool = True,\n    key_prefix: str = "equipment_types",',
            source,
        )
        self.assertIn(
            'def render_equipment_needs_vs_placements_matrix(\n    project_id: str,\n    scenario_id: str | None,\n    *,\n    wrap_in_expander: bool = True,\n    key_prefix: str = "equipment_matrix",',
            source,
        )
        self.assertIn('key_prefix=f"{functional_area.lower()}_equipment_matrix"', source)
        self.assertIn('key_prefix="equipment_overview_matrix"', source)
        self.assertIn('key_prefix="equipment_overview_types"', source)


if __name__ == "__main__":
    unittest.main()
