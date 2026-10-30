"""Regression tests for Step 4 architectural improvements (Items 13, 14, and 15)."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from utils import (
    cache_store,
    control_plan_store,
    db_core,
    equipment_store,
    feedback_store,
    layout_store,
    pfmea_pattern_store,
    pfmea_store,
    quality_store,
    recycle_bin_store,
    store,
)


class Step4RegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        cache_store.clear_all_caches()

    def tearDown(self) -> None:
        cache_store.clear_all_caches()

    def test_item13_schema_init_guard_skips_repeated_ddl_and_recovers_on_missing_table(self) -> None:
        """Item 13: init_*_schema functions run DDL once per DB and skip repeated executescript calls."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = Path(tmpdir) / "step4_schema.db"
            with patch.object(db_core, "DB_PATH", temp_db), patch.object(store, "DB_PATH", temp_db):
                store.init_db()
                with store.connection() as conn:
                    pfmea_store.init_pfmea_schema(conn)
                    control_plan_store.init_control_plan_schema(conn)
                    equipment_store.init_equipment_schema(conn)
                    quality_store.init_quality_schema(conn)
                    pfmea_pattern_store.init_pfmea_pattern_schema(conn)
                    recycle_bin_store.init_recycle_bin_schema(conn)
                    layout_store.init_layout_schema(conn)
                    feedback_store.init_feedback_schema(conn)

                    self.assertTrue(
                        cache_store.is_schema_initialized(conn, "pfmea_schema_v1", "pfmea_entries")
                    )
                    self.assertTrue(
                        cache_store.is_schema_initialized(
                            conn, "control_plan_schema_v1", "control_plan_items"
                        )
                    )
                    self.assertTrue(
                        cache_store.is_schema_initialized(
                            conn, "equipment_schema_v1", "equipment_process_links"
                        )
                    )
                    self.assertTrue(
                        cache_store.is_schema_initialized(
                            conn, "quality_schema_v1", "quality_requirement_assignments"
                        )
                    )
                    self.assertTrue(
                        cache_store.is_schema_initialized(
                            conn, "pfmea_pattern_schema_v1", "pfmea_patterns"
                        )
                    )
                    self.assertTrue(
                        cache_store.is_schema_initialized(
                            conn, "recycle_bin_schema_v1", "recycle_bin_items"
                        )
                    )
                    self.assertTrue(
                        cache_store.is_schema_initialized(
                            conn, "layout_schema_v1", "layout_custom_stencils"
                        )
                    )
                    self.assertTrue(
                        cache_store.is_schema_initialized(conn, "feedback_schema_v1", "app_feedback")
                    )

                    # Subsequent calls on an initialized DB must return early without executing DDL
                    statements: list[str] = []
                    conn.set_trace_callback(statements.append)
                    try:
                        pfmea_store.init_pfmea_schema(conn)
                        control_plan_store.init_control_plan_schema(conn)
                        pfmea_pattern_store.init_pfmea_pattern_schema(conn)
                        recycle_bin_store.init_recycle_bin_schema(conn)
                        layout_store.init_layout_schema(conn)
                        feedback_store.init_feedback_schema(conn)
                    finally:
                        conn.set_trace_callback(None)

                    ddl_statements = [
                        s for s in statements if "CREATE TABLE" in s.upper() or "PRAGMA TABLE_INFO" in s.upper()
                    ]
                    self.assertEqual(ddl_statements, [])

                    # Dropping the sentinel table automatically invalidates the guard and re-creates it
                    conn.execute("DROP TABLE app_feedback")
                    self.assertFalse(
                        cache_store.is_schema_initialized(conn, "feedback_schema_v1", "app_feedback")
                    )
                    feedback_store.init_feedback_schema(conn)
                    self.assertTrue(
                        cache_store.is_schema_initialized(conn, "feedback_schema_v1", "app_feedback")
                    )

    def test_item13_read_queries_do_not_execute_dml_on_initialized_db(self) -> None:
        """Item 13: Read queries do not issue DELETE/UPDATE DML once schema is initialized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = Path(tmpdir) / "step4_reads.db"
            with patch.object(db_core, "DB_PATH", temp_db), patch.object(store, "DB_PATH", temp_db):
                store.init_db()
                project_id = str(store.create_project("Step 4 Project", "", "Tester", 60.0))
                scenario_id = str(store.planning_scenarios(project_id)[0]["id"])

                # Warm schema initialization once
                pfmea_store.pfmea_entries(project_id, scenario_id)
                quality_store.quality_requirement_assignments(project_id, scenario_id)
                equipment_store.equipment_types(project_id)

                cache_store.get_data_cache().clear()

                dml_actions: list[tuple[int, str | None, str | None]] = []

                def deny_dml_authorizer(
                    action: int,
                    arg1: str | None,
                    arg2: str | None,
                    dbname: str | None,
                    source: str | None,
                ) -> int:
                    if action in (
                        sqlite3.SQLITE_DELETE,
                        sqlite3.SQLITE_UPDATE,
                        sqlite3.SQLITE_INSERT,
                    ):
                        dml_actions.append((action, arg1, arg2))
                    return sqlite3.SQLITE_OK

                with store.connection() as conn:
                    conn.set_authorizer(deny_dml_authorizer)
                    try:
                        pfmea_store.pfmea_entries(project_id, scenario_id)
                        quality_store.quality_requirement_assignments(project_id, scenario_id)
                        equipment_store.equipment_types(project_id)
                    finally:
                        conn.set_authorizer(None)

                self.assertEqual(dml_actions, [])

    def test_item14_scenario_only_tables_classification_and_epoch_scoping(self) -> None:
        """Item 14: SCENARIO_ONLY_TABLES includes real scenario tables and excludes project layout & phantom tables."""
        expected_present = {
            "pfmea_entries",
            "pfmea_effects",
            "pfmea_causes",
            "pfmea_prevention_selections",
            "pfmea_detection_selections",
            "pfmea_risk_rows",
            "pfmea_actions",
            "control_plan_items",
            "control_plan_characteristic_controls",
            "layout_layers",
            "layout_shapes",
            "layout_pitch_waypoints",
            "layout_aisles",
            "layout_auto_flow_links",
            "layout_shape_libraries",
        }
        self.assertTrue(expected_present.issubset(cache_store.SCENARIO_ONLY_TABLES))

        project_scoped_or_phantom = {
            "layout_plans",
            "layout_revisions",
            "layout_section_pitch_standards",
            "layout_custom_stencils",
            "pfmea_controls",
            "pfmea_failure_effects",
            "pfmea_failure_causes",
            "pfmea_prevention_controls",
            "pfmea_detection_controls",
            "pfmea_recommended_actions",
            "control_plan_entries",
            "control_plan_characteristics",
        }
        self.assertTrue(project_scoped_or_phantom.isdisjoint(cache_store.SCENARIO_ONLY_TABLES))

        # Verify epoch behavior: scenario selection writes preserve catalog epoch
        cat_before = cache_store.get_write_epoch("catalog")
        scen_before = cache_store.get_write_epoch("scenario")
        cache_store.bump_write_epoch(
            modified_tables={"pfmea_prevention_selections", "pfmea_detection_selections", "audit_log"}
        )
        self.assertEqual(cache_store.get_write_epoch("catalog"), cat_before)
        self.assertEqual(cache_store.get_write_epoch("scenario"), scen_before + 1)

        # Project-wide layout table writes bump both catalog and scenario epochs
        cache_store.bump_write_epoch(modified_tables={"layout_plans", "audit_log"})
        self.assertEqual(cache_store.get_write_epoch("catalog"), cat_before + 1)
        self.assertEqual(cache_store.get_write_epoch("scenario"), scen_before + 2)

    def test_item15_project_scoped_widget_and_filter_keys_in_pages(self) -> None:
        """Item 15: Project-level editor, filter, and pending-delete keys are scoped by project_id."""
        pages_dir = Path(__file__).resolve().parents[1] / "app_pages"

        concerns_src = (pages_dir / "concerns.py").read_text(encoding="utf-8")
        self.assertIn('editor_key = f"concerns_editor_{project_id}"', concerns_src)
        self.assertIn('key=f"concerns_filters_{project_id}"', concerns_src)

        models_src = (pages_dir / "models.py").read_text(encoding="utf-8")
        self.assertIn('f"model_definitions_editor_v2_{project_id}"', models_src)
        self.assertIn('f"complexity_feature_editor_{project_id}"', models_src)
        self.assertIn('f"complexity_tree_editor_{project_id}"', models_src)
        self.assertIn('key=f"model_definition_filters_{project_id}"', models_src)
        self.assertIn('key=f"feature_definition_filters_{project_id}"', models_src)
        self.assertIn('key=f"complexity_tree_filters_{project_id}"', models_src)

        parts_src = (pages_dir / "parts.py").read_text(encoding="utf-8")
        self.assertIn('key=f"part_catalog_filters_{project_id}"', parts_src)
        self.assertIn('f"parts_pending_bulk_delete_{project_id}"', parts_src)

        fishbone_src = (pages_dir / "fishbone.py").read_text(encoding="utf-8")
        self.assertIn('f"assembly_framework_editor_{project_id}"', fishbone_src)
        self.assertIn('key=f"assembly_framework_filters_{project_id}"', fishbone_src)
        self.assertIn('f"fishbone_assignment_editor_{project_id}_{scenario_id}"', fishbone_src)
        self.assertIn('key=f"fishbone_assignment_filters_{project_id}_{scenario_id}"', fishbone_src)


if __name__ == "__main__":
    unittest.main()
