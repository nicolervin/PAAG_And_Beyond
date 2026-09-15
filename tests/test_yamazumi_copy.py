from __future__ import annotations

import json
import sqlite3
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from streamlit.testing.v1 import AppTest

from utils import store


class YamazumiCopyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        connection_patcher = patch.object(store, "connection", self._connection)
        connection_patcher.start()
        self.addCleanup(connection_patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()

        self.project_id = "copy-project"
        self.other_project_id = "other-copy-project"
        self.source_scenario_id = "copy-source-scenario"
        self.target_scenario_id = "copy-target-scenario"
        self.source_area_id = "copy-source-area"
        self.target_area_id = "copy-target-area"
        self.other_area_id = "copy-other-area"
        timestamp = store.now_iso()
        with store.connection() as conn:
            for project_id, name in (
                (self.project_id, "Copy project"),
                (self.other_project_id, "Other project"),
            ):
                conn.execute(
                    """INSERT INTO projects
                       (id, name, revision, status, takt_time_s, created_at, updated_at)
                       VALUES (?, ?, 'A', 'Draft', 60, ?, ?)""",
                    (project_id, name, timestamp, timestamp),
                )
            for scenario_id, project_id, name, revision in (
                (self.source_scenario_id, self.project_id, "Source", 1),
                (self.target_scenario_id, self.project_id, "Target", 2),
                ("other-project-scenario", self.other_project_id, "Other", 1),
            ):
                conn.execute(
                    """INSERT INTO planning_scenarios
                       (id, project_id, name, revision_label, revision_sequence,
                        status, takt_time_s, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'Working', 60, ?, ?)""",
                    (
                        scenario_id,
                        project_id,
                        name,
                        str(revision),
                        revision,
                        timestamp,
                        timestamp,
                    ),
                )
            for area_id, project_id, scenario_id, name in (
                (
                    self.source_area_id,
                    self.project_id,
                    self.source_scenario_id,
                    "Source area",
                ),
                (
                    self.target_area_id,
                    self.project_id,
                    self.target_scenario_id,
                    "Target area",
                ),
                (
                    self.other_area_id,
                    self.other_project_id,
                    "other-project-scenario",
                    "Other area",
                ),
            ):
                conn.execute(
                    """INSERT INTO yamazumi_areas
                       (id, project_id, scenario_id, name, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (area_id, project_id, scenario_id, name, timestamp),
                )

    @contextmanager
    def _connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def add_pitch(
        self,
        number: str,
        *,
        area_id: str | None = None,
        pitch_type: str = "Pitch",
        target_id: str | None = None,
        variants: list[str] | None = None,
    ) -> str:
        return store.add_yamazumi_pitch(
            self.project_id,
            area_id or self.source_area_id,
            number,
            f"Name {number}",
            "Active",
            variants or ["Base"],
            pitch_type,
            target_id,
        )

    def add_element(
        self,
        pitch_id: str | None,
        description: str,
        *,
        area_id: str | None = None,
        variants: list[str] | None = None,
        region: str = "None",
    ) -> str:
        return store.add_yamazumi_element(
            self.project_id,
            area_id or self.source_area_id,
            pitch_id,
            {
                "description": description,
                "time_s": 4.5,
                "model_variants": variants or ["Base"],
                "work_type": "Cycle",
                "work_region": region,
            },
        )

    def copy(self, pitch_ids: list[str], element_ids: list[str], **kwargs):
        return store.copy_yamazumi_records(
            self.project_id,
            self.source_scenario_id,
            self.source_area_id,
            self.target_scenario_id,
            self.target_area_id,
            pitch_ids,
            element_ids,
            editor_name="Copy tester",
            **kwargs,
        )

    def test_pitch_copy_preserves_source_and_creates_unlinked_clean_elements(self) -> None:
        pitch_id = self.add_pitch("P-10", variants=["Base", "Model A"])
        element_id = self.add_element(
            pitch_id, "Install bracket", variants=["Base", "Model A"], region="Left"
        )
        self.conn.execute(
            "UPDATE yamazumi_elements SET process_element_id='process-link' WHERE id=?",
            (element_id,),
        )
        source_pitch_before = dict(self.conn.execute(
            "SELECT * FROM yamazumi_pitches WHERE id=?", (pitch_id,)
        ).fetchone())
        source_element_before = dict(self.conn.execute(
            "SELECT * FROM yamazumi_elements WHERE id=?", (element_id,)
        ).fetchone())

        result = self.copy([pitch_id], [])

        self.assertEqual(result["pitches_created"], 1)
        self.assertEqual(result["elements_created"], 1)
        new_pitch_id = result["pitch_id_map"][pitch_id]
        new_element_id = result["element_id_map"][element_id]
        copied_pitch = dict(self.conn.execute(
            "SELECT * FROM yamazumi_pitches WHERE id=?", (new_pitch_id,)
        ).fetchone())
        copied_element = dict(self.conn.execute(
            "SELECT * FROM yamazumi_elements WHERE id=?", (new_element_id,)
        ).fetchone())
        self.assertNotEqual(new_pitch_id, pitch_id)
        self.assertNotEqual(new_element_id, element_id)
        self.assertEqual(copied_pitch["area_id"], self.target_area_id)
        self.assertEqual(copied_element["pitch_id"], new_pitch_id)
        self.assertEqual(copied_element["sequence"], 10)
        self.assertIsNone(copied_element["process_element_id"])
        self.assertEqual(copied_element["process_sync_status"], "Needs IE review")
        self.assertNotIn("flags", copied_element)
        self.assertEqual(copied_element["source"], "Yamazumi copy")
        self.assertEqual(copied_element["work_region"], "Left")
        self.assertEqual(
            dict(self.conn.execute("SELECT * FROM yamazumi_pitches WHERE id=?", (pitch_id,)).fetchone()),
            source_pitch_before,
        )
        self.assertEqual(
            dict(self.conn.execute("SELECT * FROM yamazumi_elements WHERE id=?", (element_id,)).fetchone()),
            source_element_before,
        )
        event = self.conn.execute(
            "SELECT action, row_count, editor_name FROM audit_log WHERE table_name='Yamazumi'"
        ).fetchone()
        self.assertEqual(event["action"], "Copy to another area")
        self.assertEqual(event["row_count"], 2)
        self.assertEqual(event["editor_name"], "Copy tester")

    def test_overlapping_pitch_and_element_selection_copies_element_once(self) -> None:
        pitch_id = self.add_pitch("P-20")
        element_id = self.add_element(pitch_id, "Shared selection")
        result = self.copy([pitch_id], [element_id])
        self.assertEqual(result["elements_created"], 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM yamazumi_elements WHERE area_id=?",
                (self.target_area_id,),
            ).fetchone()[0],
            1,
        )

    def test_standalone_copy_appends_and_enables_variants(self) -> None:
        source_pitch = self.add_pitch("P-30", variants=["Base", "Model X"])
        element_id = self.add_element(
            source_pitch, "Variant work", variants=["Model X"], region="Rare region"
        )
        target_pitch = self.add_pitch("T-10", area_id=self.target_area_id)
        existing = self.add_element(
            target_pitch, "Existing target work", area_id=self.target_area_id
        )

        preview = store.preview_yamazumi_copy(
            self.project_id,
            self.source_scenario_id,
            self.source_area_id,
            self.target_scenario_id,
            self.target_area_id,
            [],
            [element_id],
            standalone_target_pitch_id=target_pitch,
        )
        self.assertEqual(preview["variant_additions"], {target_pitch: ["Model X"]})
        self.assertEqual(preview["legacy_work_regions"], ["Rare region"])
        result = self.copy(
            [], [element_id], standalone_target_pitch_id=target_pitch
        )
        copied = self.conn.execute(
            "SELECT * FROM yamazumi_elements WHERE id=?",
            (result["element_id_map"][element_id],),
        ).fetchone()
        self.assertEqual(copied["pitch_id"], target_pitch)
        self.assertEqual(copied["sequence"], 20)
        target_variants = json.loads(self.conn.execute(
            "SELECT model_variants FROM yamazumi_pitches WHERE id=?", (target_pitch,)
        ).fetchone()[0])
        self.assertEqual(target_variants, ["Base", "Model X"])
        self.assertIsNotNone(self.conn.execute(
            "SELECT id FROM yamazumi_elements WHERE id=?", (existing,)
        ).fetchone())

    def test_multiple_pitches_and_unassigned_work_append_in_stable_order(self) -> None:
        first_pitch = self.add_pitch("P-31")
        second_pitch = self.add_pitch("P-32")
        first_element = self.add_element(first_pitch, "First pitch work")
        second_element = self.add_element(second_pitch, "Second pitch work")
        existing_unassigned = self.add_element(
            None, "Existing unassigned", area_id=self.target_area_id
        )
        standalone = self.add_element(None, "Copied unassigned")

        result = self.copy(
            [first_pitch, second_pitch], [first_element, standalone]
        )

        copied_pitches = self.conn.execute(
            """SELECT id, pitch_number, sequence FROM yamazumi_pitches
               WHERE area_id=? ORDER BY sequence""",
            (self.target_area_id,),
        ).fetchall()
        self.assertEqual(
            [(row["pitch_number"], row["sequence"]) for row in copied_pitches],
            [("P-31", 10), ("P-32", 20)],
        )
        self.assertEqual(result["elements_created"], 3)
        copied_standalone = self.conn.execute(
            "SELECT pitch_id, sequence FROM yamazumi_elements WHERE id=?",
            (result["element_id_map"][standalone],),
        ).fetchone()
        self.assertIsNone(copied_standalone["pitch_id"])
        self.assertEqual(copied_standalone["sequence"], 20)
        self.assertIsNotNone(self.conn.execute(
            "SELECT id FROM yamazumi_elements WHERE id=?", (existing_unassigned,)
        ).fetchone())
        self.assertEqual(
            self.conn.execute(
                "SELECT sequence FROM yamazumi_elements WHERE id=?",
                (result["element_id_map"][second_element],),
            ).fetchone()[0],
            10,
        )

    def test_case_insensitive_pitch_conflict_requires_override(self) -> None:
        source_pitch = self.add_pitch("P-40")
        self.add_pitch("p-40", area_id=self.target_area_id)
        preview = store.preview_yamazumi_copy(
            self.project_id,
            self.source_scenario_id,
            self.source_area_id,
            self.target_scenario_id,
            self.target_area_id,
            [source_pitch],
            [],
        )
        self.assertFalse(preview["ready"])
        self.assertEqual(len(preview["number_conflicts"]), 1)
        with self.assertRaisesRegex(ValueError, "pitch-address conflict"):
            self.copy([source_pitch], [])
        result = self.copy(
            [source_pitch], [], pitch_number_overrides={source_pitch: "P-41"}
        )
        copied_number = self.conn.execute(
            "SELECT pitch_number FROM yamazumi_pitches WHERE id=?",
            (result["pitch_id_map"][source_pitch],),
        ).fetchone()[0]
        self.assertEqual(copied_number, "P-41")

    def test_feeder_targets_remap_or_require_explicit_target(self) -> None:
        source_target = self.add_pitch("P-50")
        feeder = self.add_pitch(
            "SUB-50", pitch_type="Subassembly", target_id=source_target
        )
        result = self.copy([source_target, feeder], [])
        copied_feeder_target = self.conn.execute(
            "SELECT feeds_into_pitch_id FROM yamazumi_pitches WHERE id=?",
            (result["pitch_id_map"][feeder],),
        ).fetchone()[0]
        self.assertEqual(copied_feeder_target, result["pitch_id_map"][source_target])

        external_target = self.add_pitch("T-50", area_id=self.target_area_id)
        second_target = self.add_pitch("P-60")
        second_feeder = self.add_pitch(
            "SUB-60", pitch_type="Kitter", target_id=second_target
        )
        preview = store.preview_yamazumi_copy(
            self.project_id,
            self.source_scenario_id,
            self.source_area_id,
            self.target_scenario_id,
            self.target_area_id,
            [second_feeder],
            [],
        )
        self.assertFalse(preview["ready"])
        self.assertEqual(len(preview["feed_mapping_required"]), 1)
        mapped = self.copy(
            [second_feeder], [], feed_target_overrides={second_feeder: external_target}
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT feeds_into_pitch_id FROM yamazumi_pitches WHERE id=?",
                (mapped["pitch_id_map"][second_feeder],),
            ).fetchone()[0],
            external_target,
        )

    def test_invalid_boundary_and_failed_audit_leave_target_unchanged(self) -> None:
        pitch_id = self.add_pitch("P-70")
        with self.assertRaisesRegex(ValueError, "target Yamazumi area"):
            store.copy_yamazumi_records(
                self.project_id,
                self.source_scenario_id,
                self.source_area_id,
                "other-project-scenario",
                self.other_area_id,
                [pitch_id],
                [],
                editor_name="Copy tester",
            )
        with patch.object(
            store, "record_audit_event", side_effect=RuntimeError("audit failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "audit failed"):
                self.copy([pitch_id], [])
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM yamazumi_pitches WHERE area_id=?",
                (self.target_area_id,),
            ).fetchone()[0],
            0,
        )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0], 0)


class YamazumiCopyPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_yamazumi_copy_page_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])
        self.source_area_id = store.upsert_yamazumi_area(
            self.project_id, self.scenario_id, "Copy source"
        )
        self.target_area_id = store.upsert_yamazumi_area(
            self.project_id, self.scenario_id, "Copy target"
        )
        self.pitch_id = store.add_yamazumi_pitch(
            self.project_id, self.source_area_id, "CP-10", "Copy pitch"
        )
        store.add_yamazumi_element(
            self.project_id,
            self.source_area_id,
            self.pitch_id,
            {
                "description": "Copy page work",
                "time_s": 3.0,
                "model_variants": ["Base"],
                "work_type": "Cycle",
                "work_region": "None",
            },
        )

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def run_page(self, *, pending: bool = False) -> AppTest:
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/yamazumi.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Copy page tester"
        app.session_state[f"yamazumi_area_{self.scenario_id}"] = self.source_area_id
        if pending:
            app.session_state[
                f"yamazumi_copy_pending_{self.project_id}_{self.scenario_id}"
            ] = {
                "active_scenario_id": self.scenario_id,
                "source_scenario_id": self.scenario_id,
                "source_area_id": self.source_area_id,
                "target_scenario_id": self.scenario_id,
                "target_area_id": self.target_area_id,
                "pitch_ids": [self.pitch_id],
                "element_ids": [],
                "standalone_target_pitch_id": None,
                "pitch_number_overrides": {self.pitch_id: "P-COPY"},
                "feed_target_overrides": {},
            }
        with patch("utils.yamazumi_board.yamazumi_board", return_value=None):
            app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def test_populated_copy_expander_and_confirmed_dialog(self) -> None:
        self.run_page()

        app = self.run_page(pending=True)
        confirm = next(
            button for button in app.button if button.label == "Copy to another area"
        )
        with patch("utils.yamazumi_board.yamazumi_board", return_value=None):
            app = confirm.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(
            store.query(
                "SELECT COUNT(*) AS count FROM yamazumi_pitches WHERE area_id=?",
                (self.target_area_id,),
            )[0]["count"],
            1,
        )
        self.assertEqual(
            store.query(
                "SELECT COUNT(*) AS count FROM yamazumi_elements WHERE area_id=?",
                (self.target_area_id,),
            )[0]["count"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
