from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from utils import store
from utils.ergonomics_slide_visual import (
    render_ergonomics_presentation_deck,
    render_ergonomics_slide,
    render_printable_ergonomics_deck,
)


class ErgonomicsSlidesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        connection_patcher = patch.object(store, "connection", self._test_connection)
        connection_patcher.start()
        self.addCleanup(connection_patcher.stop)
        self.addCleanup(self.conn.close)

        # Temporary directory for uploaded files during tests
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        uploads_patcher = patch("utils.ergonomics_store.UPLOAD_DIR", Path(self.temp_dir.name))
        uploads_patcher.start()
        self.addCleanup(uploads_patcher.stop)

        store.init_db()

        self.project_id = "test-project-slides"
        self.scenario_id = "test-scenario-slides"
        self.work_element_id = "test-work-element-slides"
        self.pitch_id = "test-pitch-slides"
        self.section_id = "test-section-slides"
        self.area_id = "test-area-slides"
        self.part_id = "test-part-slides"

        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects (id, name, revision, status, takt_time_s, created_at, updated_at)
                   VALUES (?, 'Test Project', 'A', 'Draft', 60, ?, ?)""",
                (self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO planning_scenarios (id, project_id, name, revision_label, revision_sequence, status, takt_time_s, takt_time_unit, created_at, updated_at)
                   VALUES (?, ?, 'Base Scenario', 'A', 1, 'Working', 60, 'seconds', ?, ?)""",
                (self.scenario_id, self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO assembly_sections (id, project_id, name, sequence, created_at, updated_at)
                   VALUES (?, ?, 'Chassis Assembly', 10, ?, ?)""",
                (self.section_id, self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES (?, ?, ?, ?, 'Front Subassembly', ?)""",
                (self.area_id, self.project_id, self.scenario_id, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches (id, project_id, area_id, pitch_number, pitch_name, sequence, updated_at)
                   VALUES (?, ?, ?, 'P01', 'Front Axle Mount', 10, ?)""",
                (self.pitch_id, self.project_id, self.area_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements (id, project_id, scenario_id, sequence, operation, cycle_time_s, updated_at)
                   VALUES (?, ?, ?, 10, 'Position and torque front strut', 45.0, ?)""",
                (self.work_element_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements (id, project_id, area_id, pitch_id, description, process_element_id, time_s, sequence, updated_at)
                   VALUES ('yelem-slides-1', ?, ?, ?, 'Strut mount element', ?, 45.0, 10, ?)""",
                (self.project_id, self.area_id, self.pitch_id, self.work_element_id, timestamp),
            )
            conn.execute(
                """INSERT INTO parts (id, project_id, part_number, description, weight_lb, updated_at)
                   VALUES (?, ?, 'STRUT-001', 'Heavy Duty Strut', 38.5, ?)""",
                (self.part_id, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_groups (id, project_id, scenario_id, work_element_id, section_id, name, selection_rule, quantity, updated_at)
                   VALUES ('grp-slides-1', ?, ?, ?, ?, 'Strut Group', 'Use all', 2, ?)""",
                (self.project_id, self.scenario_id, self.work_element_id, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO process_part_options (id, group_id, part_id, handling_type, updated_at)
                   VALUES ('opt-slides-1', 'grp-slides-1', ?, 'Handle', ?)""",
                (self.part_id, timestamp),
            )

        hazard_res = store.save_ergonomic_hazard_option_rows(
            self.project_id,
            pd.DataFrame([{"id": "", "label": "Overhead Reach (>60°)", "active": True}]),
        )
        self.hazard_id = hazard_res["created_ids"][0]

        review = store.save_ergonomics_review(
            self.project_id,
            self.scenario_id,
            {
                "work_element_id": self.work_element_id,
                "status": "Open",
                "risk_classification": "Red",
                "reviewer": "Jane Ergo",
                "notes": "Requires sustained reach above shoulder height with heavy strut assembly.",
                "hazard_option_ids": [self.hazard_id],
            },
        )
        self.review_id = review["id"]

    @contextmanager
    def _test_connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def test_save_get_update_delete_visual_media(self) -> None:
        # 1. Save image media
        sample_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        media1 = store.save_ergonomics_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            review_id=self.review_id,
            filename="workstation_front.png",
            file_bytes=sample_png,
            caption="Operator overhead posture at station",
            sequence=10,
            current_editor="Ergo Engineer",
        )
        self.assertEqual(media1["caption"], "Operator overhead posture at station")
        self.assertEqual(media1["media_type"], "image")
        self.assertEqual(media1["sequence"], 10)

        # 2. Save video media
        sample_mp4 = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
        media2 = store.save_ergonomics_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            review_id=self.review_id,
            filename="lift_cycle.mp4",
            file_bytes=sample_mp4,
            caption="Cycle video of strut lift",
            sequence=20,
            current_editor="Ergo Engineer",
        )
        self.assertEqual(media2["media_type"], "video")

        # 3. Retrieve visual media list
        media_list = store.get_ergonomics_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            review_id=self.review_id,
        )
        self.assertEqual(len(media_list), 2)
        self.assertEqual(media_list[0]["id"], media1["id"])
        self.assertEqual(media_list[1]["id"], media2["id"])
        self.assertTrue(media_list[0]["data_url"].startswith("data:image/png;base64,"))
        self.assertEqual(media_list[1]["media_type"], "video")
        self.assertEqual(media_list[1]["data_url"], "")

        # 4. Update caption & sequence
        updated = store.update_ergonomics_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            media_id=media1["id"],
            caption="Updated posture note",
            sequence=30,
            current_editor="Ergo Lead",
        )
        self.assertEqual(updated["caption"], "Updated posture note")
        self.assertEqual(updated["sequence"], 30)

        # 5. Update annotations
        annotated = store.update_ergonomics_visual_annotations(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            media_id=media1["id"],
            annotations_json='[{"type":"arrow","color":"#ef4444"}]',
            composite_image_bytes=sample_png,
            current_editor="Ergo Lead",
        )
        self.assertEqual(annotated["annotations_json"], '[{"type":"arrow","color":"#ef4444"}]')

        # 6. Delete media
        store.delete_ergonomics_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            media_id=media1["id"],
            current_editor="Ergo Lead",
        )
        remaining = store.get_ergonomics_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            review_id=self.review_id,
        )
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["id"], media2["id"])

    def test_visual_media_size_limits_and_validation(self) -> None:
        # Test unsupported extension
        with self.assertRaises(ValueError) as ctx:
            store.save_ergonomics_visual_media(
                project_id=self.project_id,
                scenario_id=self.scenario_id,
                review_id=self.review_id,
                filename="document.pdf",
                file_bytes=b"dummy pdf",
                current_editor="User",
            )
        self.assertIn("Unsupported file format", str(ctx.exception))

        # Test image size limit (10 MB + 1 byte)
        large_image_bytes = b"0" * (10 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError) as ctx:
            store.save_ergonomics_visual_media(
                project_id=self.project_id,
                scenario_id=self.scenario_id,
                review_id=self.review_id,
                filename="huge.png",
                file_bytes=large_image_bytes,
                current_editor="User",
            )
        self.assertIn("under 10 MB", str(ctx.exception))

        # Test video size limit (25 MB + 1 byte)
        large_video_bytes = b"0" * (25 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError) as ctx:
            store.save_ergonomics_visual_media(
                project_id=self.project_id,
                scenario_id=self.scenario_id,
                review_id=self.review_id,
                filename="huge.mp4",
                file_bytes=large_video_bytes,
                current_editor="User",
            )
        self.assertIn("25 MB", str(ctx.exception))

    def test_ergonomics_slide_summary(self) -> None:
        summary = store.ergonomics_slide_summary(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            review_id=self.review_id,
        )
        self.assertEqual(summary["review"]["id"], self.review_id)
        self.assertEqual(summary["review"]["risk_classification"], "Red")
        self.assertEqual(summary["review"]["status"], "Open")
        self.assertEqual(summary["work_info"]["operation"], "Position and torque front strut")
        self.assertEqual(summary["work_info"]["pitch_number"], "P01")
        self.assertEqual(summary["takt_time_s"], 60.0)
        self.assertEqual(summary["work_info"]["cycle_time"], 45.0)
        self.assertIn("Overhead Reach (>60°)", summary["hazards"])
        self.assertTrue(summary["has_heavy_part"])  # Strut is 38.5 lbs >= 33 lbs
        self.assertEqual(len(summary["parts"]), 1)
        self.assertEqual(summary["parts"][0]["part_number"], "STRUT-001")
        self.assertEqual(summary["parts"][0]["weight_lb"], 38.5)

    def test_render_ergonomics_slide_html(self) -> None:
        summary = store.ergonomics_slide_summary(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            review_id=self.review_id,
        )
        html = render_ergonomics_slide(summary)
        self.assertIn("PROCESS AT A GLANCE", html)
        self.assertIn("Ergonomic Risk & Hazard Analysis", html)
        self.assertIn("Position and torque front strut", html)
        self.assertIn("Overhead Reach", html)
        self.assertIn("STRUT-001", html)
        self.assertIn("Manual Material Handling Warning", html)
        self.assertIn("Jane Ergo", html)
        self.assertIn("Requires sustained reach above shoulder height", html)

    def test_presentation_and_print_decks(self) -> None:
        summary = store.ergonomics_slide_summary(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            review_id=self.review_id,
        )
        slide_html = render_ergonomics_slide(summary, presentation_mode=True)
        slides_data = [{
            "review_id": self.review_id,
            "review_label": "P01 · Position and torque front strut (Red)",
            "slide_html": slide_html,
        }]

        # Test presentation deck
        pres_deck = render_ergonomics_presentation_deck(
            slides_data=slides_data,
            initial_review_id=self.review_id,
        )
        self.assertIn("ergo-deck-container", pres_deck)
        self.assertIn("deck-slide", pres_deck)
        self.assertIn("Shortcuts: ◀ / ▶ Arrow", pres_deck)

        # Test printable deck
        print_deck = render_printable_ergonomics_deck(
            slides_html=[slide_html],
            paper_size="tabloid",
            image_fit="contain",
            title="Ergo Print Test",
        )
        self.assertIn("@media print", print_deck)
        self.assertIn("size: 17in 11in landscape", print_deck)
        self.assertIn("window.print()", print_deck)

    def test_scenario_clone_replicates_visual_media(self) -> None:
        sample_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        media = store.save_ergonomics_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            review_id=self.review_id,
            filename="clone_source.png",
            file_bytes=sample_png,
            caption="Visual aid before clone",
            sequence=10,
            current_editor="Collaborator",
        )

        cloned_scenario_id = store.clone_planning_scenario(
            project_id=self.project_id,
            source_scenario_id=self.scenario_id,
            name="Cloned Scenario With Media",
            revision_label="B",
            takt_time_s=60.0,
            created_by="Cloner",
        )

        cloned_reviews = store.ergonomics_reviews(self.project_id, cloned_scenario_id)
        self.assertEqual(len(cloned_reviews), 1)
        cloned_review_id = cloned_reviews.iloc[0]["id"]

        cloned_media = store.get_ergonomics_visual_media(
            project_id=self.project_id,
            scenario_id=cloned_scenario_id,
            review_id=cloned_review_id,
        )
        self.assertEqual(len(cloned_media), 1)
        self.assertEqual(cloned_media[0]["caption"], "Visual aid before clone")
        self.assertNotEqual(cloned_media[0]["id"], media["id"])  # Brand new UUID
        self.assertEqual(cloned_media[0]["scenario_id"], cloned_scenario_id)
        self.assertEqual(cloned_media[0]["review_id"], cloned_review_id)


if __name__ == "__main__":
    unittest.main()
