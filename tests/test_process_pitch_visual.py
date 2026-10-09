from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pandas as pd
from streamlit.testing.v1 import AppTest

from utils import store
from utils.process_pitch_visual import (
    clamp_page,
    page_count,
    page_elements,
    page_for_element,
    render_pitch_canvas,
    render_presentation_deck,
    render_printable_paag_deck,
)


class ProcessPitchVisualTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_pitch_visual_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        self.scenario_id = str(store.planning_scenarios(self.project_id)[0]["id"])
        self.section_id = store.add_assembly_section(
            self.project_id, "Main", "Main spine", None, ""
        )
        self.area_id = str(uuid4())
        self.pitch_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES (?, ?, ?, ?, 'Visual area', ?)""",
                (self.area_id, self.project_id, self.scenario_id, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES (?, ?, ?, '01-SW1-051', 'Pitch visual', ?)""",
                (self.pitch_id, self.project_id, self.area_id, timestamp),
            )
        self.work_ids = [self._add_linked_element(index) for index in range(1, 7)]

    def _add_linked_element(self, index: int) -> str:
        work_id = f"work-{index}"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    model_applicability, updated_at)
                   VALUES (?, ?, ?, ?, '01-SW1-051', ?, 'All', ?)""",
                (
                    work_id,
                    self.project_id,
                    self.scenario_id,
                    index * 10,
                    f"Motion {index}",
                    timestamp,
                ),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id,
                    description, time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"yam-{index}",
                    self.project_id,
                    self.area_id,
                    self.pitch_id,
                    work_id,
                    f"Motion {index}",
                    float(index),
                    index * 10,
                    timestamp,
                ),
            )
        return work_id

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_summary_is_ordered_and_second_page_contains_clicked_element(self) -> None:
        summary = store.process_pitch_visual_summary(
            self.project_id, self.scenario_id, self.pitch_id
        )
        self.assertEqual(
            [row["work_element_id"] for row in summary["elements"]], self.work_ids
        )
        self.assertEqual(page_count(len(summary["elements"])), 2)
        self.assertEqual(page_for_element(summary["elements"], self.work_ids[5]), 2)
        self.assertEqual(
            page_elements(summary["elements"], 2)[0]["work_element_id"], self.work_ids[5]
        )

    def test_linked_work_is_reflected_even_when_yamazumi_needs_review(self) -> None:
        rows = store.yamazumi_elements_for_section(
            self.project_id, self.scenario_id, self.section_id
        )
        self.assertTrue(rows["process_sync_status"].eq("Needs IE review").all())
        self.assertTrue(rows["process_reflected"].astype(bool).all())

    def test_process_part_requirement_source_includes_only_cycle_work(self) -> None:
        cycle_id = store.add_yamazumi_element(
            self.project_id,
            self.area_id,
            self.pitch_id,
            {
                "description": "Cycle source",
                "time_s": 1,
                "model_variants": ["Base"],
                "work_type": "Cycle",
            },
        )
        periodic_id = store.add_yamazumi_element(
            self.project_id,
            self.area_id,
            self.pitch_id,
            {
                "description": "Periodic source",
                "time_s": 1,
                "model_variants": ["Base"],
                "work_type": "Periodic",
            },
        )
        fluctuation_id = store.add_yamazumi_element(
            self.project_id,
            self.area_id,
            self.pitch_id,
            {
                "description": "Fluctuation source",
                "time_s": 1,
                "model_variants": ["Base"],
                "work_type": "Fluctuation",
            },
        )

        rows = store.yamazumi_elements_for_section(
            self.project_id, self.scenario_id, self.section_id
        )
        element_ids = set(rows["id"].astype(str))

        self.assertIn(cycle_id, element_ids)
        self.assertNotIn(periodic_id, element_ids)
        self.assertNotIn(fluctuation_id, element_ids)
        self.assertTrue(rows["work_type"].fillna("Cycle").eq("Cycle").all())

    def test_summary_rejects_pitch_from_another_scenario(self) -> None:
        other_scenario = store.clone_planning_scenario(
            self.project_id,
            self.scenario_id,
            "Other",
            "B",
            60,
            created_by="Pitch visual test",
        )
        with self.assertRaisesRegex(ValueError, "active planning scenario"):
            store.process_pitch_visual_summary(
                self.project_id, str(other_scenario), self.pitch_id
            )

    def test_pagination_clamps_at_both_boundaries(self) -> None:
        self.assertEqual(clamp_page(0, 6), 1)
        self.assertEqual(clamp_page(99, 6), 2)
        with self.assertRaisesRegex(ValueError, "no longer assigned"):
            page_for_element([{"work_element_id": "one"}], "missing")

    def test_renderer_escapes_content_and_renders_required_fallbacks(self) -> None:
        html = render_pitch_canvas(
            {"pitch_number": "P<&", "pitch_name": "Visual"},
            [
                {
                    "work_element_id": "one",
                    "op_id": "M1.P1.1",
                    "yamazumi_description": "Fit <bracket>",
                    "time_s": 3.5,
                    "models": ["Model A"],
                    "parts": [],
                    "motion_classification": "Unclassified",
                    "motion_color": "gray",
                    "ergonomics_risk": True,
                    "torque_requirements": [
                        {
                            "unique_identifier": "TQ-1",
                            "target_value": 12,
                            "tolerances": "±1",
                            "unit": "N·m",
                        }
                    ],
                }
            ],
            scenario_name="Scenario <One>",
            generated_on=date(2026, 9, 11),
        )
        self.assertIn("No Parts Paired", html)
        self.assertIn("motion-bar gray", html)
        self.assertNotIn("motion-bar red", html)
        self.assertIn("Ergo Risk", html)
        self.assertIn("TQ-1: 12 ±1 N·m", html)
        self.assertIn("Fit &lt;bracket&gt;", html)
        self.assertIn("Generated on September 11, 2026 — Scenario: Scenario &lt;One&gt;", html)

    def test_renderer_embeds_an_available_part_image(self) -> None:
        html = render_pitch_canvas(
            {"pitch_number": "P1"},
            [{
                "op_id": "M1.P1.1",
                "yamazumi_description": "Install",
                "time_s": 1,
                "models": ["All models"],
                "parts": [{"part_number": "PART-1", "image_path": __file__}],
                "motion_classification": "Value-Added (VA)",
                "motion_color": "green",
                "torque_requirements": [],
            }],
            scenario_name="Base",
        )
        self.assertIn(";base64,", html)
        self.assertIn("motion-bar green", html)
        orange_html = render_pitch_canvas(
            {"pitch_number": "P1"},
            [{
                "op_id": "M1.P1.2", "yamazumi_description": "Move", "time_s": 2,
                "models": ["All models"], "parts": [],
                "motion_classification": "Non-Value-Added but Necessary (NVAN)",
                "motion_color": "orange", "torque_requirements": [],
            }],
            scenario_name="Base",
        )
        self.assertIn("motion-bar orange", orange_html)

    def test_process_page_renders_selected_pitch_and_navigates_to_page_two(self) -> None:
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/process.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Pitch visual test"
        app.session_state["selected_pitch_id"] = self.pitch_id
        app.session_state["pitch_page_num"] = 1
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertNotIn("details", next(
            editor.value for editor in app.dataframe
            if "ergonomics_risk" in editor.value.columns
        ).columns)
        next_button = next(button for button in app.button if button.label == "Next")
        app = next_button.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["pitch_page_num"], 2)
        self.assertFalse(next(button for button in app.button if button.label == "Back").disabled)


    def test_visual_media_crud_and_video_handling(self) -> None:
        img_res = store.save_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=self.pitch_id,
            filename="demo.png",
            file_bytes=b"\x89PNG\r\n\x1a\nfakeimagecontent",
            caption="Bracket mounting orientation",
            tagged_work_element_ids=[self.work_ids[0]],
            sequence=10,
            current_editor="Tester",
        )
        img_id = img_res["id"]
        vid_res = store.save_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=self.pitch_id,
            filename="action.mp4",
            file_bytes=b"\x00\x00\x00\x20ftypisomfakevideocontent",
            caption="Operator harness installation video",
            tagged_work_element_ids=[self.work_ids[1]],
            sequence=20,
            current_editor="Tester",
        )
        vid_id = vid_res["id"]
        items = store.get_pitch_visual_media(
            self.project_id, self.scenario_id, self.pitch_id
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["id"], img_id)
        self.assertEqual(items[0]["media_type"], "image")
        self.assertEqual(items[1]["id"], vid_id)
        self.assertEqual(items[1]["media_type"], "video")
        self.assertTrue(Path(items[0]["file_path"]).exists())
        self.assertTrue(Path(items[1]["file_path"]).exists())

        # Update visual media
        store.update_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            media_id=img_id,
            caption="Updated bracket caption",
            sequence=5,
            tagged_work_element_ids=[self.work_ids[0], self.work_ids[1]],
            current_editor="Tester",
        )
        updated_items = store.get_pitch_visual_media(
            self.project_id, self.scenario_id, self.pitch_id
        )
        self.assertEqual(updated_items[0]["id"], img_id)
        self.assertEqual(updated_items[0]["caption"], "Updated bracket caption")
        self.assertEqual(len(updated_items[0]["tagged_work_elements"]), 2)

        # Delete visual media
        file_to_check = Path(items[1]["file_path"])
        store.delete_pitch_visual_media(
            self.project_id, self.scenario_id, vid_id, current_editor="Tester"
        )
        self.assertFalse(file_to_check.exists())
        remaining = store.get_pitch_visual_media(
            self.project_id, self.scenario_id, self.pitch_id
        )
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["id"], img_id)

    def test_scenario_cloning_copies_visual_media_and_tags(self) -> None:
        store.save_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=self.pitch_id,
            filename="diagram.png",
            file_bytes=b"\x89PNG\r\n\x1a\nclonetest",
            caption="Base scenario visual",
            tagged_work_element_ids=[self.work_ids[0]],
            sequence=10,
            current_editor="Tester",
        )
        new_scenario_id = store.clone_planning_scenario(
            self.project_id,
            self.scenario_id,
            name="Cloned Scenario",
            revision_label="Rev B",
            takt_time_s=60.0,
            created_by="Tester",
        )
        # Find cloned pitch in new scenario
        cloned_pitches = store.yamazumi_pitches_for_scenario(
            self.project_id, new_scenario_id
        )
        self.assertFalse(cloned_pitches.empty)
        cloned_pitch_id = str(cloned_pitches.iloc[0]["id"])
        cloned_media = store.get_pitch_visual_media(
            self.project_id, new_scenario_id, cloned_pitch_id
        )
        self.assertEqual(len(cloned_media), 1)
        self.assertEqual(cloned_media[0]["caption"], "Base scenario visual")

    def test_visual_media_follows_yamazumi_elements_across_pitches(self) -> None:
        second_pitch_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES (?, ?, ?, '01-SW1-052', 'Second Station Pitch', ?)""",
                (second_pitch_id, self.project_id, self.area_id, store.now_iso()),
            )

        # Upload image on pitch 1 tied to element 1 and element 2
        img_res = store.save_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=self.pitch_id,
            filename="cross_pitch.png",
            file_bytes=b"\x89PNG\r\n\x1a\ncrosspitchcontent",
            caption="Multi element visual aid",
            tagged_work_element_ids=[self.work_ids[0], self.work_ids[1]],
            sequence=10,
            current_editor="Tester",
        )
        img_id = img_res["id"]

        # Before move: Image appears on pitch 1, but not pitch 2
        p1_media = store.get_pitch_visual_media(self.project_id, self.scenario_id, self.pitch_id)
        p2_media = store.get_pitch_visual_media(self.project_id, self.scenario_id, second_pitch_id)
        self.assertEqual(len(p1_media), 1)
        self.assertEqual(p1_media[0]["id"], img_id)
        self.assertEqual(len(p2_media), 0)

        # Move work_ids[1] (Element 2) to second_pitch_id
        with store.connection() as conn:
            conn.execute(
                "UPDATE yamazumi_elements SET pitch_id=? WHERE process_element_id=?",
                (second_pitch_id, self.work_ids[1]),
            )

        # After moving Element 2 to pitch 2:
        # Image is tied to Element 1 (on pitch 1) AND Element 2 (on pitch 2).
        # It must stick with Element 2 and appear on pitch 2, while remaining on pitch 1 for Element 1.
        p1_media = store.get_pitch_visual_media(self.project_id, self.scenario_id, self.pitch_id)
        p2_media = store.get_pitch_visual_media(self.project_id, self.scenario_id, second_pitch_id)
        self.assertEqual(len(p1_media), 1, "Image must remain on Pitch 1 because Element 1 is still on Pitch 1")
        self.assertEqual(p1_media[0]["id"], img_id)
        self.assertEqual(len(p2_media), 1, "Image must stick with Element 2 on Pitch 2")
        self.assertEqual(p2_media[0]["id"], img_id)

        # Verify PAAG slide render summaries for both pitches
        summary_1 = store.process_pitch_visual_summary(self.project_id, self.scenario_id, self.pitch_id)
        summary_2 = store.process_pitch_visual_summary(self.project_id, self.scenario_id, second_pitch_id)
        self.assertTrue(any(m["id"] == img_id for m in summary_1.get("visual_media", [])))
        self.assertTrue(any(m["id"] == img_id for m in summary_2.get("visual_media", [])))

        # Render canvases and verify each slide shows its own step operation & step badge
        html_1 = render_pitch_canvas(summary_1)
        html_2 = render_pitch_canvas(summary_2)
        # On Pitch 1: Element 1 is Motion 1 (Step 1)
        self.assertIn("Motion 1", html_1)
        # On Pitch 2: Element 2 is Motion 2 (Step 1 on Pitch 2)
        self.assertIn("Motion 2", html_2)

        # Now move Element 1 (work_ids[0]) to pitch 2 as well
        with store.connection() as conn:
            conn.execute(
                "UPDATE yamazumi_elements SET pitch_id=? WHERE process_element_id=?",
                (second_pitch_id, self.work_ids[0]),
            )

        # After both elements are moved to pitch 2:
        # None of the tagged elements are on Pitch 1, so the image should only appear on Pitch 2
        p1_media_after = store.get_pitch_visual_media(self.project_id, self.scenario_id, self.pitch_id)
        p2_media_after = store.get_pitch_visual_media(self.project_id, self.scenario_id, second_pitch_id)
        self.assertEqual(len(p1_media_after), 0, "No tagged elements on Pitch 1, visual aid should not appear on Pitch 1")
        self.assertEqual(len(p2_media_after), 1, "Both tagged elements on Pitch 2, visual aid appears on Pitch 2")

    def test_render_pitch_canvas_includes_video_tools_alerts_and_parts_nickname(self) -> None:
        summary = {
            "pitch_number": "01-SW1-051",
            "pitch_name": "Main Spindle",
            "project_name": "Project Alpha",
            "op_id_summary": "10 - 60",
            "tools": [
                {
                    "name": "DC Torque Tool 15Nm",
                    "type_name": "Torque Driver",
                    "description": "Atlas Copco inline driver",
                    "is_ppe": False,
                },
                {
                    "name": "Safety Glasses (ANSI Z87.1)",
                    "type_name": "PPE",
                    "description": "Clear impact shield",
                    "is_ppe": True,
                },
            ],
            "parts": [
                {
                    "part_number": "BRKT-001",
                    "part_name": "Support Bracket",
                    "factory_nickname": "Dog Bone",
                    "qty": 2,
                    "handling_type": "Consume",
                    "thumbnail_path": "",
                }
            ],
            "scenario_takt_s": 50.0,
            "yamazumi_stacks": {
                "Base": {
                    "total_time_s": 35.0,
                    "elements": [
                        {
                            "op_id": "10",
                            "yamazumi_description": "Mount Bracket",
                            "time_s": 15.0,
                            "work_type": "Cycle",
                            "motion_classification": "Value-Added (VA)",
                            "motion_color": "green",
                        },
                        {
                            "op_id": "11",
                            "yamazumi_description": "Periodic Maintenance",
                            "time_s": 10.0,
                            "work_type": "Periodic",
                            "motion_classification": "Non-Value-Added but Necessary (NVAN)",
                            "motion_color": "orange",
                        },
                        {
                            "op_id": "12",
                            "yamazumi_description": "Fluctuation Adjustment",
                            "time_s": 10.0,
                            "work_type": "Fluctuation",
                            "motion_classification": "Unclassified",
                            "motion_color": "gray",
                        },
                    ],
                },
                "Heavy": {
                    "total_time_s": 60.0,
                    "elements": [
                        {
                            "op_id": "13",
                            "yamazumi_description": "Heavy Weld",
                            "time_s": 60.0,
                            "work_type": "Cycle",
                            "motion_classification": "Value-Added (VA)",
                            "motion_color": "green",
                        }
                    ],
                },
            },
            "alerts": {
                "quality": [{"label": "Torque Critical", "detail": "12.5 Nm +/- 0.5"}],
                "safety": [{"label": "Pinch Hazard", "detail": "Keep hands clear during clamp"}],
            },
            "visual_media": [
                {
                    "id": "v1",
                    "media_type": "video",
                    "file_path": str(Path(__file__).resolve()),
                    "caption": "Verify alignment before cycling",
                }
            ],
            "slide_count": 1,
        }
        html = render_pitch_canvas(
            summary,
            [{"op_id": "10", "yamazumi_description": "Mount Bracket", "time_s": 15, "models": ["All"]}],
            scenario_name="Rev A Plan",
            project_name="Project Alpha",
            page_num=1,
            total_pages=1,
        )
        self.assertIn("Process at a Glance for Project Alpha", html)
        self.assertIn("01-SW1-051", html)
        self.assertIn("Main Spindle", html)
        self.assertIn("DC Torque Tool 15Nm", html)
        self.assertIn("badge-ppe", html)
        self.assertIn("PPE", html)
        self.assertIn("Safety Glasses", html)
        self.assertIn("Dog Bone", html)
        self.assertIn("part-nick-text", html)
        self.assertIn("Consume / Handle", html)
        self.assertIn("h-badge va", html)
        self.assertIn("part-thumb", html)
        self.assertIn("BRKT-001", html)
        self.assertIn("Functional Alerts", html)
        self.assertIn("Torque Critical", html)
        self.assertIn("Pinch Hazard", html)
        self.assertIn("alert-popover", html)
        self.assertIn("Open Quality Review", html)
        self.assertIn('href="./functional_quality"', html)
        self.assertIn("Open Safety Review", html)
        self.assertIn("part-popover", html)
        self.assertIn("part-popover-bridge", html)
        self.assertIn("part-info-cue", html)
        self.assertIn("Open in Parts Catalog", html)
        self.assertIn('href="./parts?part_number=BRKT-001#part-details-section"', html)
        self.assertIn("<video class=\"visual-player\" controls", html)
        self.assertIn("Verify alignment before cycling", html)
        self.assertIn("caption-callout", html)
        self.assertIn("type-cycle", html)
        self.assertIn("type-periodic", html)
        self.assertIn("type-fluctuation", html)
        self.assertIn("swatch-mini cycle", html)
        self.assertIn("swatch-mini periodic", html)
        self.assertIn("swatch-mini fluctuation", html)
        self.assertIn("Takt: 50s", html)
        self.assertIn("70% util", html)
        self.assertIn("under-takt", html)
        self.assertIn("120% util", html)
        self.assertIn("over-takt", html)

    def test_visual_media_file_size_limits(self) -> None:
        oversized_image = b"\x89PNG\r\n\x1a\n" + b"A" * (10 * 1024 * 1024 + 100)
        with self.assertRaises(ValueError) as cm_img:
            store.save_pitch_visual_media(
                project_id=self.project_id,
                scenario_id=self.scenario_id,
                pitch_id=self.pitch_id,
                filename="huge_photo.png",
                file_bytes=oversized_image,
            )
        self.assertIn("under 10 MB", str(cm_img.exception))

        oversized_video = b"\x00\x00\x00\x20ftypisom" + b"B" * (25 * 1024 * 1024 + 100)
        with self.assertRaises(ValueError) as cm_vid:
            store.save_pitch_visual_media(
                project_id=self.project_id,
                scenario_id=self.scenario_id,
                pitch_id=self.pitch_id,
                filename="huge_video.mp4",
                file_bytes=oversized_video,
            )
        self.assertIn("under 25 MB", str(cm_vid.exception))

    def test_render_presentation_deck_empty(self) -> None:
        deck_html = render_presentation_deck([])
        self.assertIn("No pitch slides available to present", deck_html)

    def test_render_presentation_deck_flow(self) -> None:
        slides_data = [
            {
                "pitch_id": "p1",
                "pitch_idx": 0,
                "pitch_label": "01-SW1-010 Base Frame",
                "page_num": 1,
                "total_pages": 1,
                "slide_html": "<section class='paag-slide'>Slide 1 Content</section>",
            },
            {
                "pitch_id": "p2",
                "pitch_idx": 1,
                "pitch_label": "01-SW1-020 Front Axle",
                "page_num": 1,
                "total_pages": 2,
                "slide_html": "<section class='paag-slide'>Slide 2 Part A</section>",
            },
            {
                "pitch_id": "p2",
                "pitch_idx": 1,
                "pitch_label": "01-SW1-020 Front Axle",
                "page_num": 2,
                "total_pages": 2,
                "slide_html": "<section class='paag-slide'>Slide 2 Part B</section>",
            },
        ]

        deck_html = render_presentation_deck(
            slides_data=slides_data,
            initial_pitch_id="p2",
            total_pitches=2,
        )

        # Toolbar controls
        self.assertIn("paag-presentation-player", deck_html)
        self.assertIn("pres-btn-prev-pitch", deck_html)
        self.assertIn("pres-btn-prev-slide", deck_html)
        self.assertIn("pres-btn-next-slide", deck_html)
        self.assertIn("pres-btn-next-pitch", deck_html)
        self.assertIn("pres-pitch-selector", deck_html)
        self.assertIn("pres-btn-fullscreen", deck_html)
        self.assertIn("pres-btn-close", deck_html)
        self.assertIn("pres-shortcuts", deck_html)

        # Initial counter for initial pitch p2
        self.assertIn("Pitch 2 of 2 (Page 1/2) · 01-SW1-020 Front Axle", deck_html)

        # Dropdown options
        self.assertIn('value="p1"', deck_html)
        self.assertIn('value="p2" selected', deck_html)

        # Slides and display state (slide 0 hidden, slide 1 active)
        self.assertIn('id="deck-slide-0"', deck_html)
        self.assertIn('data-pitch-id="p1"', deck_html)
        self.assertIn('style="display: none;"', deck_html)

        self.assertIn('id="deck-slide-1"', deck_html)
        self.assertIn('data-pitch-id="p2"', deck_html)
        self.assertIn('style="display: block;"', deck_html)

        # Keyboard event handler present
        self.assertIn("handleKeyDown", deck_html)
        self.assertIn("requestFullscreen", deck_html)

    def test_presentation_mode_dialog_navigation(self) -> None:
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/process.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Presentation test"
        app.session_state["selected_pitch_id"] = self.pitch_id
        app.session_state["pitch_page_num"] = 1
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])

        # Click Present button
        present_btn = next(b for b in app.button if b.label == "Present")
        app = present_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertTrue(app.session_state.get(f"paag_present_active_{self.scenario_id}"))

        # In presentation dialog, find Next ▶ button
        pres_next_btn = next(b for b in app.button if "Next" in b.label and "pres_btn_next" in str(b.key))
        app = pres_next_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state.get(f"pres_page_num_{self.scenario_id}"), 2)
        self.assertTrue(app.session_state.get(f"paag_present_active_{self.scenario_id}"))

        # In presentation dialog, find ◀ Back button
        pres_back_btn = next(b for b in app.button if "Back" in b.label and "pres_btn_back" in str(b.key))
        app = pres_back_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state.get(f"pres_page_num_{self.scenario_id}"), 1)

        # In presentation dialog, find ✕ Exit button
        pres_exit_btn = next(b for b in app.button if "Exit" in b.label and "pres_btn_exit" in str(b.key))
        app = pres_exit_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertFalse(app.session_state.get(f"paag_present_active_{self.scenario_id}"))

    def test_render_pitch_canvas_print_tabloid_and_fit(self) -> None:
        pitch = {
            "pitch_number": "01-SW1-010",
            "pitch_name": "Engine Drop",
            "project_name": "Project Apollo",
            "scenario_name": "Line 1 Ramp",
        }
        elements = [
            {
                "work_element_id": "we1",
                "element_name": "Position powertrain hoist",
                "description": "Align hoist pins with crossmember",
                "station_criticality": "Critical",
                "manual_s": 22.0,
                "walk_s": 3.0,
                "parts": [{"part_number": "P-100", "description": "Engine Mount", "quantity": 2.0}],
                "images": ["data/uploads/mount.png"],
            }
        ]
        html_tabloid = render_pitch_canvas(
            pitch,
            elements,
            page_num=1,
            total_pages=1,
            print_format="tabloid",
            image_fit="fill",
        )
        self.assertIn("print-tabloid", html_tabloid)
        self.assertIn("fit-fill", html_tabloid)
        self.assertIn("17 / 11", html_tabloid)
        self.assertIn("17in 11in landscape", html_tabloid)
        self.assertIn("object-fit: fill", html_tabloid)

        html_letter = render_pitch_canvas(
            pitch,
            elements,
            page_num=1,
            total_pages=1,
            print_format="letter",
            image_fit="contain",
        )
        self.assertIn("print-letter", html_letter)
        self.assertIn("fit-contain", html_letter)
        self.assertIn("11 / 8.5", html_letter)
        self.assertIn("11in 8.5in landscape", html_letter)

    def test_render_printable_paag_deck(self) -> None:
        slide_1 = "<section class='paag-slide print-tabloid fit-fill'>Slide 1 Content</section>"
        slide_2 = "<section class='paag-slide print-tabloid fit-fill'>Slide 2 Content</section>"
        deck = render_printable_paag_deck([slide_1, slide_2], paper_size="tabloid", title="Test PAAG Deck")
        self.assertIn("<!DOCTYPE html>", deck)
        self.assertIn("17in 11in landscape", deck)
        self.assertIn("Print Now (or press Ctrl+P)", deck)
        self.assertIn("window.print()", deck)
        self.assertIn("autoprint", deck)
        self.assertIn("Slide 1 of 2", deck)
        self.assertIn("Slide 2 of 2", deck)
        self.assertIn("Slide 1 Content", deck)
        self.assertIn("Slide 2 Content", deck)
        self.assertIn("2 Slides", deck)
        self.assertIn("page-break-after: always", deck)

    def test_print_dialog_export_workflow(self) -> None:
        app = AppTest.from_file(
            str(store.ROOT / "app_pages/process.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Print test"
        app.session_state["selected_pitch_id"] = self.pitch_id
        app.session_state["pitch_page_num"] = 1
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])

        # Click Print button
        print_btn = next(b for b in app.button if b.label == "Print")
        app = print_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertTrue(app.session_state.get(f"paag_print_active_{self.scenario_id}"))

        # Verify radio widgets for Print Selection, Page Format, and Image Fit exist
        scope_radio = next(r for r in app.radio if "Print Selection" in r.label)
        self.assertTrue(any("Current slide only" in opt for opt in scope_radio.options))
        self.assertTrue(any("All pitches in scenario" in opt for opt in scope_radio.options))

        # Default page format is 8.5x11 Letter Landscape
        fmt_radio = next(r for r in app.radio if "Page Format" in r.label)
        self.assertTrue(any("11 × 17" in opt for opt in fmt_radio.options))
        self.assertTrue(any("8.5 × 11" in opt for opt in fmt_radio.options))
        self.assertTrue("8.5 × 11" in fmt_radio.value)

        fit_radio = next(r for r in app.radio if "Image Fit in Print" in r.label)
        self.assertTrue(any("Stretch to Fill Box" in opt for opt in fit_radio.options))

        # Download HTML Deck button exists
        dl_btn = next(b for b in app.download_button if "Download HTML Deck" in b.label)
        self.assertIsNotNone(dl_btn)

        # Close dialog via button
        close_btn = next(b for b in app.button if "Close Print Window" in b.label)
        app = close_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertFalse(app.session_state.get(f"paag_print_active_{self.scenario_id}"))

    def test_fishbone_section_included_in_pitch_summary_and_canvas(self) -> None:
        # Verify yamazumi_pitches_for_scenario includes section_id and section_name
        pitches_df = store.yamazumi_pitches_for_scenario(self.project_id, self.scenario_id)
        self.assertFalse(pitches_df.empty)
        self.assertIn("section_id", pitches_df.columns)
        self.assertIn("section_name", pitches_df.columns)
        match_row = pitches_df.loc[pitches_df["id"] == self.pitch_id].iloc[0]
        self.assertEqual(str(match_row["section_id"]), self.section_id)
        self.assertEqual(str(match_row["section_name"]), "Main")

        # Verify process_pitch_visual_summary includes section_id and section_name
        summary = store.process_pitch_visual_summary(self.project_id, self.scenario_id, self.pitch_id)
        self.assertEqual(str(summary.get("section_id")), self.section_id)
        self.assertEqual(str(summary.get("section_name")), "Main")

        # Verify render_pitch_canvas outputs the section name in slide header
        html = render_pitch_canvas(summary, summary["elements"][:1], scenario_name="Test Scenario", project_name="Test Project")
        self.assertIn("Process at a Glance · Main", html)
        self.assertIn("<div><strong>Section:</strong> Main</div>", html)

    def test_fishbone_section_filtering_in_viewer_and_print_dialog(self) -> None:
        # Create a second section and pitch
        sec2_id = store.add_assembly_section(self.project_id, "Subassembly Front", "Subassembly", self.section_id, "")
        area2_id = str(uuid4())
        pitch2_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES (?, ?, ?, ?, 'Front Sub Area', ?)""",
                (area2_id, self.project_id, self.scenario_id, sec2_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES (?, ?, ?, '02-FR-001', 'Front subassembly pitch', ?)""",
                (pitch2_id, self.project_id, area2_id, timestamp),
            )

        app = AppTest.from_file(
            str(store.ROOT / "app_pages/process.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Section test"
        app.session_state["selected_pitch_id"] = self.pitch_id
        app.session_state["pitch_page_num"] = 1
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])

        # Verify Fishbone Section filter dropdown exists in visualizer navigation bar
        sec_selectbox = next(s for s in app.selectbox if s.label == "Fishbone Section" and "sec_active_select" in str(s.key))
        self.assertTrue(any("All Fishbone Sections" in opt for opt in sec_selectbox.options))
        self.assertTrue(any("Main" in opt for opt in sec_selectbox.options))
        self.assertTrue(any("Subassembly Front" in opt for opt in sec_selectbox.options))

        # Click Print to open export dialog
        print_btn = next(b for b in app.button if b.label == "Print")
        app = print_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertTrue(app.session_state.get(f"paag_print_active_{self.scenario_id}"))

        # Verify section printing options exist in Print Selection
        scope_radio = next(r for r in app.radio if "Print Selection" in r.label)
        self.assertTrue(any("Current section" in opt for opt in scope_radio.options))
        self.assertTrue(any("Select specific section(s)..." in opt for opt in scope_radio.options))
        self.assertTrue(any("All pitches in scenario" in opt for opt in scope_radio.options))

        # Close dialog
        close_btn = next(b for b in app.button if "Close Print Window" in b.label)
        app = close_btn.click().run(timeout=30)
        self.assertEqual(list(app.exception), [])

    def test_work_element_tool_and_resource_persistence(self) -> None:
        work_id = self.work_ids[0]
        store.update_work_element_tool_and_resource(
            self.project_id,
            self.scenario_id,
            work_id,
            tool="Cordless Screwdriver (Atlas Copco)",
            resource_type="Autonomous equipment",
            resource_detail="Robot",
            editor_name="Test IE",
        )

        with store.connection() as conn:
            row = conn.execute(
                "SELECT tool, resource_type, resource_detail FROM work_elements WHERE id=?",
                (work_id,),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["tool"], "Cordless Screwdriver (Atlas Copco)")
            self.assertEqual(row["resource_type"], "Autonomous equipment")
            self.assertEqual(row["resource_detail"], "Robot")

        # Verify pitch summary includes the tool from work_elements
        summary = store.process_pitch_visual_summary(
            self.project_id, self.scenario_id, self.pitch_id
        )
        self.assertIn(
            "Cordless Screwdriver (Atlas Copco)",
            [t["name"] for t in summary["tools"]],
        )

        # Verify Handheld equipment default type
        from utils.equipment_store import equipment_types
        eq_types = equipment_types(self.project_id)
        self.assertIn("Handheld equipment", eq_types["label"].tolist())

    def test_yamazumi_work_element_and_visual_aid_tagging_badges(self) -> None:
        work_id = self.work_ids[0]
        # Save a visual aid tagged to work element #1
        img_res = store.save_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=self.pitch_id,
            filename="bracket_guide.png",
            file_bytes=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82",
            caption="Align front bracket flush to chassis rail",
            tagged_work_element_ids=[work_id],
            sequence=10,
            current_editor="Test IE",
        )
        self.assertTrue(bool(img_res.get("id")))

        # Retrieve pitch summary and render slide
        summary = store.process_pitch_visual_summary(
            self.project_id, self.scenario_id, self.pitch_id
        )
        html = render_pitch_canvas(
            summary,
            summary["elements"],
            scenario_name="Rev A Plan",
            project_name="Test Project",
            page_num=1,
            total_pages=1,
        )

        # 1. Yamazumi block for element #1 has step badge (without #), camera indicator, and data attribute
        self.assertIn("stack-step-badge", html)
        self.assertIn('<span class="stack-step-badge">1</span>', html)
        self.assertNotIn('<span class="stack-step-badge">#1</span>', html)
        self.assertIn("has-visual", html)
        self.assertIn("stack-cam-icon", html)
        self.assertIn("📷", html)
        self.assertIn('data-step-num="1"', html)

        # 2. Visual card has matching step tag badge on banner, no overlay badge on image
        self.assertIn("visual-tag-badge", html)
        self.assertIn('<span class="visual-tag-badge">1</span>', html)
        self.assertNotIn("overlay-step-badge", html)
        self.assertIn('data-step-nums="1"', html)
        self.assertIn("Align front bracket flush to chassis rail", html)

        # 3. Interactive hover linking script is included
        self.assertIn("setupHoverLinking", html)
        self.assertIn(".stack-block[data-step-num]", html)
        self.assertIn(".visual-card[data-step-nums]", html)

        # 4. When all elements are tagged, banner displays "All elements (1, ...)"
        store.save_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=self.pitch_id,
            filename="overview.png",
            file_bytes=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82",
            caption="Station overview guide",
            tagged_work_element_ids=self.work_ids,
            sequence=20,
            current_editor="Test IE",
        )
        summary_all = store.process_pitch_visual_summary(
            self.project_id, self.scenario_id, self.pitch_id
        )
        html_all = render_pitch_canvas(
            summary_all,
            summary_all["elements"],
            scenario_name="Rev A Plan",
            project_name="Test Project",
            page_num=1,
            total_pages=1,
        )
        self.assertIn("All elements", html_all)

    def test_visual_media_annotations_and_vector_persistence(self) -> None:
        """Verify vector annotations, original source preservation, and non-destructive updates."""
        from pathlib import Path
        from utils.image_annotator import decode_data_url

        orig_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        comp_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        sample_annotations = json.dumps([
            {"id": "shape-1", "type": "arrow", "x1": 10, "y1": 10, "x2": 50, "y2": 50, "color": "#ff3b30", "lineWidth": 3},
            {"id": "shape-2", "type": "badge", "x": 60, "y": 60, "text": "1", "color": "#007aff", "radius": 14},
        ])

        created = store.save_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=self.pitch_id,
            filename="bracket_assembly.png",
            file_bytes=comp_png,
            original_file_bytes=orig_png,
            annotations_json=sample_annotations,
            caption="Check bracket alignment pin",
            tagged_work_element_ids=[self.work_ids[0]],
            sequence=10,
            current_editor="Test IE",
        )

        media_id = created["id"]
        self.assertEqual(created["annotations_json"], sample_annotations)
        self.assertTrue(created["original_file_path"])
        self.assertNotEqual(created["file_path"], created["original_file_path"])

        orig_file = Path(created["original_file_path"])
        comp_file = Path(created["file_path"])
        self.assertTrue(orig_file.exists())
        self.assertTrue(comp_file.exists())
        self.assertEqual(orig_file.read_bytes(), orig_png)
        self.assertEqual(comp_file.read_bytes(), comp_png)

        # Verify get_pitch_visual_media preserves vector JSON
        items = store.get_pitch_visual_media(self.project_id, self.scenario_id, self.pitch_id)
        matching = [i for i in items if i["id"] == media_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["annotations_json"], sample_annotations)
        self.assertEqual(matching[0]["original_file_path"], str(orig_file))

        # Test updating annotations non-destructively
        updated_annotations = json.dumps([
            {"id": "shape-1", "type": "arrow", "x1": 10, "y1": 10, "x2": 80, "y2": 80, "color": "#ffcc00", "lineWidth": 4},
            {"id": "shape-2", "type": "badge", "x": 60, "y": 60, "text": "1", "color": "#007aff", "radius": 14},
            {"id": "shape-3", "type": "rect", "x": 100, "y": 100, "w": 40, "h": 30, "color": "#34c759", "lineWidth": 2},
        ])
        new_comp_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x03\x00\x00\x00\x03\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"

        store.update_pitch_visual_annotations(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            media_id=media_id,
            annotations_json=updated_annotations,
            composite_image_bytes=new_comp_png,
            current_editor="Test IE",
        )

        # Check that original photo is still intact and composite image was refreshed
        self.assertEqual(orig_file.read_bytes(), orig_png)
        self.assertEqual(comp_file.read_bytes(), new_comp_png)

        updated_items = store.get_pitch_visual_media(self.project_id, self.scenario_id, self.pitch_id)
        matching_up = [i for i in updated_items if i["id"] == media_id]
        self.assertEqual(matching_up[0]["annotations_json"], updated_annotations)

        # Test decode_data_url
        data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        decoded = decode_data_url(data_url)
        self.assertTrue(decoded.startswith(b"\x89PNG"))

        # Test deletion cleans up both original and composite files
        store.delete_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            media_id=media_id,
            current_editor="Test IE",
        )
        self.assertFalse(orig_file.exists())
        self.assertFalse(comp_file.exists())

    def test_missing_ppe_alert_and_no_equipment_alert(self) -> None:
        # Initially, there are 6 work elements on the pitch and NO tools or PPE assigned.
        summary = store.process_pitch_visual_summary(
            self.project_id, self.scenario_id, self.pitch_id
        )

        # 1. Verify equipment alerts do NOT include "No tools or equipment placed on pitch"
        equip_alerts = summary["alerts"].get("equipment", [])
        self.assertFalse(
            any("No tools or equipment placed on pitch" in a["label"] for a in equip_alerts),
            "False equipment alert should be suppressed",
        )

        # 2. Verify safety alerts contain missing PPE alerts for each of the 6 steps
        safety_alerts = summary["alerts"].get("safety", [])
        missing_ppe_alerts = [a for a in safety_alerts if "No PPE Assigned" in a["label"]]
        self.assertEqual(len(missing_ppe_alerts), 6)
        self.assertTrue(any("Step 1" in a["label"] for a in missing_ppe_alerts))

        # 3. Assign PPE to Step 1 (self.work_ids[0])
        ppe_df = pd.DataFrame([{
            "work_element_id": self.work_ids[0],
            "ppe": ["Safety Glasses", "Cut-Resistant Gloves"],
            "requirement_description": "General assembly eye and hand protection",
            "active": True,
        }])
        store.save_safety_requirements(self.project_id, self.scenario_id, ppe_df, "Safety IE")

        # 4. Re-check summary
        summary2 = store.process_pitch_visual_summary(
            self.project_id, self.scenario_id, self.pitch_id
        )
        safety_alerts2 = summary2["alerts"].get("safety", [])
        missing_ppe_alerts2 = [a for a in safety_alerts2 if "No PPE Assigned" in a["label"]]
        # Step 1 should now be satisfied, remaining 5 steps still alert
        self.assertEqual(len(missing_ppe_alerts2), 5)
        self.assertFalse(any("Step 1" in a["label"] for a in missing_ppe_alerts2))

        # 5. Verify assigned PPE is listed under tools with is_ppe=True
        ppe_tools = [t for t in summary2["tools"] if t.get("is_ppe")]
        ppe_names = {t["name"] for t in ppe_tools}
        self.assertIn("Safety Glasses", ppe_names)
        self.assertIn("Cut-Resistant Gloves", ppe_names)

    def test_part_hover_popover_rich_metadata(self) -> None:
        part_data = {
            "part_number": "FRM-9900",
            "description": "Main Chassis Frame",
            "factory_nickname": "Big Bertha",
            "official_windchill_part_name": "FRAME_ASM_WINDCHILL_9900",
            "revision": "B",
            "make_buy": "Make",
            "subsystem": "Structure",
            "source_code": "3",
            "pits_tracker_number": "PITS-8841",
            "part_code": "P-CHASSIS",
            "weight_lb": 42.5,
            "model_applicability": "Heavy, Medium",
            "design_engineer": "Alice DE",
            "technology_engineer": "Bob TE",
            "buyer_gcl": "Carol Buyer",
            "pmqe_aqe": "Dave AQE",
            "notes": "Ensure torque on side bolts",
            "quantity": 2,
            "handling_types": ["Consume"],
            "linked_steps": ["Step 1 (Frame Align)", "Step 2 (Bolt Fix)"],
        }
        summary = {
            "pitch_number": "P-01",
            "pitch_name": "Chassis Assembly",
            "parts": [part_data],
        }
        html = render_pitch_canvas(summary, [])
        self.assertIn("FRM-9900", html)
        self.assertIn("Rev B", html)
        self.assertIn("Big Bertha", html)
        self.assertIn("FRAME_ASM_WINDCHILL_9900", html)
        self.assertIn("3 - Mfg Part", html)
        self.assertIn("PITS-8841", html)
        self.assertIn("P-CHASSIS", html)
        self.assertIn("42.5 lb", html)
        self.assertIn("Alice DE", html)
        self.assertIn("Carol Buyer", html)
        self.assertIn("Ensure torque on side bolts", html)
        self.assertIn("Step 1 (Frame Align)", html)
        self.assertIn("Step 2 (Bolt Fix)", html)
        self.assertIn("Open in Parts Catalog", html)
        self.assertIn("Assigned Engineers (Parts Catalog)", html)
        self.assertIn("Design Engineer", html)
        self.assertIn("Technology Engineer", html)
        self.assertIn("PMQE / AQE", html)
        self.assertIn("Buyer / GCL", html)

    def test_assembly_group_minibom_and_large_image(self) -> None:
        asm_part = {
            "part_number": "230D6738G001",
            "description": "Main Front Axle Assembly",
            "factory_nickname": "Front Axle Kit",
            "revision": "C",
            "make_buy": "Make",
            "is_assembly_group": True,
            "image_path": "data/uploads/sample_axle.png",
            "design_engineer": "Sarah Chen",
            "technology_engineer": "Marcus Bell",
            "ame_tooling_engineer": "Tom Bradley",
            "pmqe_aqe": "Elena Rostova",
            "buyer_gcl": "David Miller",
            "quantity": 1,
            "mini_bom": [
                {
                    "part_number": "123D4567P001",
                    "description": "Teal Axle Wheel",
                    "quantity": 4.0,
                    "design_engineer": "Sarah Chen",
                },
                {
                    "part_number": "789D1011P002",
                    "description": "Wheel Retaining Bolt",
                    "quantity": 8.0,
                    "design_engineer": "Tom Bradley",
                },
                {
                    "part_number": "184D8563G001",
                    "description": "Axle Hardware Pack",
                    "quantity": 1.0,
                    "design_engineer": "Marcus Bell",
                },
            ],
            "handling_types": ["Consume"],
            "linked_steps": ["Step 1 (Mount Axle)"],
        }
        summary = {
            "pitch_number": "P-02",
            "pitch_name": "Axle Subassembly",
            "parts": [asm_part],
        }
        html = render_pitch_canvas(summary, [])
        # Assembly group and badges
        self.assertIn("Assembly Group", html)
        self.assertIn("popover-badge asm-group", html)
        self.assertIn("Front Axle Kit", html)
        # Large image preview banner
        self.assertIn("popover-image-banner", html)
        self.assertIn("popover-large-img", html)
        # Engineers section
        self.assertIn("Assigned Engineers (Parts Catalog)", html)
        self.assertIn("Sarah Chen", html)
        self.assertIn("Marcus Bell", html)
        self.assertIn("Tom Bradley", html)
        self.assertIn("Elena Rostova", html)
        self.assertIn("David Miller", html)
        # Mini BOM section
        self.assertIn("Mini BOM Makeup", html)
        self.assertIn("3 components", html)
        self.assertIn("minibom-table", html)
        self.assertIn("123D4567P001", html)
        self.assertIn("Teal Axle Wheel", html)
        self.assertIn("×4", html)
        self.assertIn("789D1011P002", html)
        self.assertIn("Wheel Retaining Bolt", html)
        self.assertIn("×8", html)
        self.assertIn("184D8563G001", html)
        self.assertIn("Axle Hardware Pack", html)

    def test_pitch_unclassified_part_options_and_handling_classification(self) -> None:
        # 1. Create a part and place it in the fishbone section
        part_id = "test-part-classification"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO parts (id, project_id, part_number, description, updated_at)
                   VALUES (?, ?, 'PART-999', 'Turbo Flange', ?)""",
                (part_id, self.project_id, timestamp),
            )
            assignment_id = "fb-assign-999"
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                   VALUES (?, ?, ?, ?, 10, 2.0, 'Primary Mounting', ?)""",
                (assignment_id, self.project_id, self.section_id, part_id, timestamp),
            )

        # 2. Pair part to the first work element on self.pitch_id
        group_id = "test-group-999"
        store.save_process_part_group(
            self.project_id,
            self.scenario_id,
            self.work_ids[0],
            self.section_id,
            group_id,
            "Flange Group",
            "Use all",
            1,
            [part_id],
        )

        # 3. Query pitch unclassified options: should return our unclassified part
        unclassified = store.get_pitch_unclassified_part_options(
            self.project_id, self.scenario_id, self.pitch_id
        )
        self.assertEqual(len(unclassified), 1)
        opt = unclassified[0]
        self.assertEqual(opt["part_number"], "PART-999")
        self.assertEqual(opt["part_description"], "Turbo Flange")
        self.assertIsNone(opt["handling_type"])
        self.assertEqual(len(opt["placements"]), 1)
        self.assertEqual(opt["placements"][0]["fishbone_assignment_id"], assignment_id)

        # 4. Scenario part handling options before classification
        scenario_opts = store.get_scenario_part_handling_options(
            self.project_id, self.scenario_id, unclassified_only=True
        )
        self.assertEqual(len(scenario_opts), 1)
        self.assertEqual(scenario_opts[0]["part_number"], "PART-999")

        # 5. Classify the option as Consume (auto-resolving placement)
        store.set_process_part_option_handling_type(
            self.project_id,
            self.scenario_id,
            opt["option_id"],
            "Consume",
        )

        # 6. Query pitch unclassified options: should now be empty
        unclassified_after = store.get_pitch_unclassified_part_options(
            self.project_id, self.scenario_id, self.pitch_id
        )
        self.assertEqual(len(unclassified_after), 0)

        # 7. Scenario part handling options after classification
        scenario_unclassified_after = store.get_scenario_part_handling_options(
            self.project_id, self.scenario_id, unclassified_only=True
        )
        self.assertEqual(len(scenario_unclassified_after), 0)

        scenario_all_after = store.get_scenario_part_handling_options(
            self.project_id, self.scenario_id, unclassified_only=False
        )
        self.assertEqual(len(scenario_all_after), 1)
        self.assertEqual(scenario_all_after[0]["handling_type"], "Consume")

    def test_yamazumi_cycle_elements_on_pitch_are_green(self) -> None:
        # Pitches were already populated with 6 elements defaulting to work_type='Cycle'
        pitch_data = store.process_pitch_visual_summary(self.project_id, self.scenario_id, self.pitch_id)
        stacks = pitch_data.get("yamazumi_stacks", {})
        base_stack = stacks.get("Base", [])
        self.assertGreaterEqual(len(base_stack), 1)
        for elem in base_stack:
            self.assertEqual(elem["motion_color"], "green")
            self.assertEqual(elem["work_type"], "Cycle")

        # Render pitch canvas and verify the rendered block is type-cycle and green
        html = render_pitch_canvas(pitch_data, pitch_data.get("elements", []), scenario_name="Test")
        self.assertIn("stack-block type-cycle motion-bar green", html)
        self.assertNotIn("stack-block type-cycle motion-bar gray", html)
        self.assertNotIn("stack-block type-cycle motion-bar orange", html)

    def test_part_popover_open_in_parts_catalog_link(self) -> None:
        part_data = {
            "part_id": "test-uuid-1234",
            "part_number": "BRKT-9999",
            "part_name": "Test Bracket",
        }
        pitch_data = {
            "pitch_id": "p1",
            "parts": [part_data],
        }
        html = render_pitch_canvas(pitch_data, [], scenario_name="Test")
        self.assertIn("Open in Parts Catalog", html)
        self.assertIn('href="./parts?part_id=test-uuid-1234&part_number=BRKT-9999#part-details-section"', html)

    def test_yamazumi_stack_scaling_prevents_cutoff_and_title_compact(self) -> None:
        import re

        # Pitch with 8 elements under takt (40s / takt 60s)
        elements = [
            {"id": f"e{i}", "yamazumi_description": f"Step {i}", "time_s": 5.0, "work_type": "Cycle"}
            for i in range(1, 9)
        ]
        pitch_data = {
            "pitch_id": "p_scale",
            "scenario_takt_s": 60.0,
            "yamazumi_stacks": {
                "Base": {
                    "total_time_s": 40.0,
                    "elements": elements,
                }
            },
        }
        html = render_pitch_canvas(pitch_data, [], scenario_name="Test Plan")
        self.assertIn("Yamazumi Pitch Stack", html)
        self.assertIn("40s", html)
        self.assertIn("Takt 60s", html)
        self.assertIn("67% util", html)

        # Extract all block heights in the rendered stack
        block_heights = [int(m) for m in re.findall(r'class="stack-block[^"]*"[^>]*style="height:(\d+)px"', html)]
        self.assertEqual(len(block_heights), 8)
        # Verify the sum of all 8 blocks never exceeds the 175px track height
        self.assertLessEqual(sum(block_heights), 175)

        # Check no scrolling on parts panel and check bottom-left anchoring of stack-panel
        self.assertIn(".parts-panel", html)
        self.assertNotIn("parts-panel {\n        flex: 1 1 0;\n        overflow-y: auto;", html)
        self.assertIn("margin-top: auto", html)

        # Also test extreme element count (15 elements)
        many_elements = [
            {"id": f"m{i}", "yamazumi_description": f"Small step {i}", "time_s": 3.0, "work_type": "Cycle"}
            for i in range(1, 16)
        ]
        pitch_data_many = {
            "pitch_id": "p_many",
            "scenario_takt_s": 60.0,
            "yamazumi_stacks": {
                "Base": {
                    "total_time_s": 45.0,
                    "elements": many_elements,
                }
            },
        }
        html_many = render_pitch_canvas(pitch_data_many, [], scenario_name="Test Plan")
        many_heights = [int(m) for m in re.findall(r'class="stack-block[^"]*"[^>]*style="height:(\d+)px"', html_many)]
        self.assertEqual(len(many_heights), 15)
        self.assertLessEqual(sum(many_heights), 175)


if __name__ == "__main__":
    unittest.main()



