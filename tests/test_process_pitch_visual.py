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
    render_paag_pptx_deck,
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

    def test_process_part_requirement_source_includes_cycle_work_only(self) -> None:
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
        self.assertIn("pitch_id", rows.columns)
        work_types = set(rows["work_type"].dropna())
        self.assertEqual(work_types, {"Cycle"})

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
        app.session_state["paag_tab"] = "PAAG Slides"
        app.run(timeout=30)
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
        store.empty_recycle_bin(self.project_id)
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
        self.assertIn("<span>Parts</span>", html)
        self.assertNotIn("Parts (Consume &amp; Handle)", html)
        self.assertIn("h-badge va", html)
        self.assertIn('<span class="h-badge va" title="Consume">C</span>', html)
        self.assertIn(".h-badge.nvan { background: #fef9c3; color: #854d0e;", html)
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
        self.assertIn("part-info-trigger", html)
        self.assertIn(".part-info-trigger:hover .part-popover", html)
        self.assertNotIn(".parts-table tr.part-row:hover .part-popover", html)
        self.assertNotIn(".part-pnum-container:hover .part-popover", html)
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
        app.session_state["paag_tab"] = "PAAG Slides"
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
        self.assertIn("grid-template-rows: minmax(0, 1fr)", html_letter)
        self.assertIn(".paag-slide.print-letter .visual-media-box", html_letter)
        self.assertIn("fitPrintSlideStacks", html_letter)

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
        app.session_state["paag_tab"] = "PAAG Slides"
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
        self.assertIn("Current slide only (Slide 1/2)", scope_radio.options)
        self.assertTrue(all("Pitch " not in opt for opt in scope_radio.options if "Current slide only" in opt))
        self.assertTrue(any("All pitches in scenario" in opt for opt in scope_radio.options))

        # Default page format is 8.5x11 Letter Landscape
        fmt_radio = next(r for r in app.radio if "Page Format" in r.label)
        self.assertTrue(any("11 × 17" in opt for opt in fmt_radio.options))
        self.assertTrue(any("8.5 × 11" in opt for opt in fmt_radio.options))
        self.assertTrue("8.5 × 11" in fmt_radio.value)

        fit_radio = next(r for r in app.radio if "Image Fit in Print" in r.label)
        self.assertTrue(any("Stretch to Fill Box" in opt for opt in fit_radio.options))
        self.assertEqual(fit_radio.value, "Preserve Aspect Ratio")

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

        # Verify render_pitch_canvas outputs the section name in slide header and page badge at top left
        html = render_pitch_canvas(summary, summary["elements"][:1], scenario_name="Test Scenario", project_name="Test Project")
        self.assertNotIn("Process at a Glance · Main", html)
        self.assertIn('<div class="header-page-row"><span class="page-badge">Page 1 of 1</span></div>', html)
        self.assertIn("<div><strong>Section:</strong> Main</div>", html)

    def test_fishbone_section_filtering_in_viewer_and_print_dialog(self) -> None:
        # Create a second section with one populated pitch and one empty pitch (no work elements)
        sec2_id = store.add_assembly_section(self.project_id, "Subassembly Front", "Subassembly", self.section_id, "")
        area2_id = str(uuid4())
        pitch2_id = str(uuid4())
        empty_pitch_id = str(uuid4())
        we2_id = str(uuid4())
        ye2_id = str(uuid4())
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
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES (?, ?, ?, '02-FR-002', 'Empty subassembly pitch', ?)""",
                (empty_pitch_id, self.project_id, area2_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, model_applicability, updated_at)
                   VALUES (?, ?, ?, 99, '02-FR-001', 'Install front bracket', 'All', ?)""",
                (we2_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id, sequence, description, time_s, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, 'Install front bracket', 12.0, ?)""",
                (ye2_id, self.project_id, area2_id, pitch2_id, we2_id, timestamp),
            )

        app = AppTest.from_file(
            str(store.ROOT / "app_pages/process.py"), default_timeout=30
        )
        app.session_state["project_id"] = self.project_id
        app.session_state["scenario_id"] = self.scenario_id
        app.session_state["current_editor"] = "Section test"
        app.session_state["paag_tab"] = "PAAG Slides"
        app.session_state["selected_pitch_id"] = self.pitch_id
        app.session_state["pitch_page_num"] = 1
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])

        # Verify Fishbone Section filter dropdown exists in visualizer navigation bar
        sec_selectbox = next(s for s in app.selectbox if s.label == "Fishbone Section" and "sec_active_select" in str(s.key))
        self.assertTrue(any("All Fishbone Sections" in opt for opt in sec_selectbox.options))
        self.assertTrue(any("Main" in opt for opt in sec_selectbox.options))
        self.assertTrue(any("Subassembly Front" in opt for opt in sec_selectbox.options))

        # Verify Pitch dropdown only populates pitches that contain work elements
        pitch_selectbox = next(s for s in app.selectbox if s.label == "Pitch" and "pitch_active_select" in str(s.key))
        self.assertTrue(any("01-SW1-051" in opt for opt in pitch_selectbox.options))
        self.assertTrue(any("02-FR-001" in opt for opt in pitch_selectbox.options))
        self.assertFalse(any("02-FR-002" in opt for opt in pitch_selectbox.options))

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
        store.empty_recycle_bin(self.project_id)
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

        # Verify rendered slide header collapses missing PPE into compact "No PPE assigned (0/6 tasks)"
        # while keeping individual step details inside the hover popover
        html1 = render_pitch_canvas(summary)
        self.assertIn('<span class="alert-summary">No PPE assigned (0/6 tasks)</span>', html1)
        self.assertIn('<div class="popover-item-title">No PPE Assigned: Step 1 (Motion 1)</div>', html1)

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

        html2 = render_pitch_canvas(summary2)
        self.assertIn('<span class="alert-summary">No PPE assigned (1/6 tasks)</span>', html2)
        self.assertNotIn('No PPE Assigned: Step 1', html2)
        self.assertIn('<div class="popover-item-title">No PPE Assigned: Step 2 (Motion 2)</div>', html2)

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
        self.assertNotIn("Technology Engineer", html)
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
        base_stack = stacks.get("All models", [])
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
        self.assertIn("<span>Yamazumi</span>", html)
        self.assertNotIn("Yamazumi Pitch Stack", html)
        self.assertIn("40s", html)
        self.assertIn("Takt 60s", html)
        self.assertIn("67% util", html)

        # Extract all block heights and track height in the rendered stack
        block_heights = [int(m) for m in re.findall(r'class="stack-block[^"]*"[^>]*style="height:(\d+)px"', html)]
        track_heights = [int(m) for m in re.findall(r'class="stack-track"\s+style="height:(\d+)px', html)]
        self.assertEqual(len(block_heights), 8)
        self.assertEqual(len(track_heights), 1)
        # Every block must be tall enough to read clearly (>= 26px) and fit inside the dynamically expanded track height
        self.assertGreaterEqual(min(block_heights), 26)
        self.assertLessEqual(sum(block_heights), track_heights[0])

        # Check no scrolling on parts panel and check bottom-left anchoring of stack-panel
        self.assertIn(".parts-panel", html)
        self.assertNotIn("parts-panel {\n        flex: 1 1 0;\n        overflow-y: auto;", html)
        self.assertIn("margin-top: auto", html)

        # Also test extreme element count (15 elements) with proportional cycle-time scaling
        many_elements = [
            {
                "id": f"m{i}",
                "yamazumi_description": f"Readable work element step {i}",
                "time_s": 3.0 if i <= 5 else (6.0 if i <= 10 else 9.0),
                "work_type": "Cycle",
            }
            for i in range(1, 16)
        ]
        pitch_data_many = {
            "pitch_id": "p_many",
            "scenario_takt_s": 60.0,
            "yamazumi_stacks": {
                "Base": {
                    "total_time_s": 90.0,
                    "elements": many_elements,
                }
            },
        }
        html_many = render_pitch_canvas(pitch_data_many, [], scenario_name="Test Plan")
        many_heights = [int(m) for m in re.findall(r'class="stack-block[^"]*"[^>]*style="height:(\d+)px"', html_many)]
        many_track_heights = [int(m) for m in re.findall(r'class="stack-track"\s+style="height:(\d+)px', html_many)]
        self.assertEqual(len(many_heights), 15)
        self.assertEqual(len(many_track_heights), 1)
        self.assertGreaterEqual(min(many_heights), 26)
        self.assertLessEqual(sum(many_heights), many_track_heights[0])
        # Verify proportional cycle-time scaling (9s > 6s > 3s)
        self.assertGreater(many_heights[6], many_heights[0])
        self.assertGreater(many_heights[12], many_heights[6])

    def test_small_screen_text_wrapping_in_parts_and_yamazumi_boxes(self) -> None:
        pitch_data = {
            "pitch_id": "p_wrap",
            "scenario_takt_s": 20.0,
            "parts": [
                {
                    "part_id": "p1",
                    "part_number": "3456",
                    "part_name": "graphics package rescue",
                    "quantity": 1,
                    "handling_type": "Consume",
                },
                {
                    "part_id": "p2",
                    "part_number": "6788",
                    "part_name": "graphics package adventure",
                    "quantity": 1,
                    "handling_type": "Consume",
                },
            ],
            "yamazumi_stacks": {
                "Base": {
                    "total_time_s": 11.0,
                    "elements": [
                        {"id": "e1", "yamazumi_description": "Add standard graphics", "time_s": 6.0, "work_type": "Cycle"},
                        {"id": "e2", "yamazumi_description": "get material", "time_s": 5.0, "work_type": "Cycle"},
                    ],
                },
                "graphics package = Rescue": {
                    "total_time_s": 19.0,
                    "elements": [
                        {"id": "e3", "yamazumi_description": "add rescue graphics", "time_s": 14.0, "work_type": "Cycle"},
                        {"id": "e2", "yamazumi_description": "get material", "time_s": 5.0, "work_type": "Cycle"},
                    ],
                },
            },
        }
        html = render_pitch_canvas(pitch_data, [], scenario_name="Test Plan")
        self.assertIn("table-layout: auto;", html)
        self.assertIn(".part-desc-text {\n        font-weight: 600;\n        color: #0f172a;\n        line-height: 1.2;\n        white-space: normal;", html)
        self.assertIn("stack-block type-cycle motion-bar green  multiline", html)
        self.assertIn(".stack-block.multiline .block-label {\n        display: -webkit-box;", html)
        self.assertIn("stack-step-trigger", html)
        self.assertIn("step-popover", html)
        self.assertIn(".stack-step-trigger:hover .step-popover", html)
        self.assertIn("step-popover-link", html)
        self.assertIn("Open in Yamazumi ↗", html)
        self.assertIn("./yamazumi?", html)
        self.assertNotIn('<span class="takt-label">', html)
        self.assertIn('title="Takt: 20s"', html)

    def test_image_annotator_part_photo_overlay_resolves_data_url(self) -> None:
        from utils.image_annotator import _JS

        self.assertIn("const cachedImg = getCachedShapeImage(s.dataUrl || s.data_url || s);", _JS)
        self.assertIn("? (shapeOrUrl.dataUrl || shapeOrUrl.data_url || \"\")", _JS)
        self.assertNotIn("const cachedImg = getCachedShapeImage(s);", _JS)

    def test_image_annotator_callout_font_size_controls_and_resolution_normalization(self) -> None:
        from utils.image_annotator import _HTML, _JS

        self.assertIn('id="font-size-select"', _HTML)
        self.assertIn('id="btn-font-dec"', _HTML)
        self.assertIn('id="btn-font-inc"', _HTML)
        self.assertIn("function getVisualNormFactor()", _JS)
        self.assertIn("const normFactor = getVisualNormFactor();", _JS)
        self.assertIn("const visScale = sc * normFactor;", _JS)
        self.assertIn("const baseFontPx = Number(s.fontSize) || 18;", _JS)
        self.assertIn("fontSize: currentFontSize,", _JS)
        self.assertIn("commitPendingTextOverlay(false);", _JS)
        self.assertIn("const MAX_EXPORT_DIM = 1920;", _JS)
        self.assertIn('offscreen.toDataURL("image/jpeg", 0.92)', _JS)

    def test_update_pitch_visual_annotations_persists_markup_and_handles_reassigned_pitch(self) -> None:
        orig_bytes = b"\x89PNG\r\n\x1a\noriginal_unmarked_image"
        comp_bytes = b"\x89PNG\r\n\x1a\nannotated_composite_image"
        saved = store.save_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=self.pitch_id,
            filename="photo.png",
            file_bytes=orig_bytes,
            caption="Test visual aid",
            tagged_work_element_ids=[self.work_ids[0]],
            sequence=10,
            current_editor="Tester",
        )
        media_id = saved["id"]
        created_files = [Path(saved["file_path"])]
        if saved.get("original_file_path"):
            created_files.append(Path(saved["original_file_path"]))
        try:
            # Simulate pitch_id reassignment where media record still points to another pitch_id
            other_pitch_id = str(uuid4())
            with store.connection() as conn:
                conn.execute(
                    """INSERT INTO yamazumi_pitches
                       (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                       VALUES (?, ?, ?, '01-SW1-052', 'Other pitch', ?)""",
                    (other_pitch_id, self.project_id, self.area_id, store.now_iso()),
                )
                conn.execute(
                    "UPDATE process_visual_media SET pitch_id = ?, original_file_path = '' WHERE id = ?",
                    (other_pitch_id, media_id),
                )
            ann_json = json.dumps(
                [
                    {
                        "id": "shape_1",
                        "type": "text",
                        "x": 100,
                        "y": 150,
                        "text": "Torque M8 bolt",
                        "color": "#ef4444",
                        "strokeWidth": 4,
                        "fontSize": 26,
                    }
                ]
            )
            store.update_pitch_visual_annotations(
                project_id=self.project_id,
                scenario_id=self.scenario_id,
                media_id=media_id,
                composite_image_bytes=comp_bytes,
                annotations_json=ann_json,
                current_editor="Tester",
            )
            items = store.get_pitch_visual_media(
                self.project_id, self.scenario_id, self.pitch_id
            )
            updated = next(m for m in items if m["id"] == media_id)
            self.assertEqual(updated["annotations_json"], ann_json)
            self.assertTrue(updated["original_file_path"])
            created_files.append(Path(updated["original_file_path"]))
            created_files.append(Path(updated["file_path"]))
            self.assertEqual(Path(updated["file_path"]).read_bytes(), comp_bytes)
            self.assertEqual(Path(updated["original_file_path"]).read_bytes(), orig_bytes)
        finally:
            for f in created_files:
                f.unlink(missing_ok=True)

    def test_tag_to_work_elements_populates_and_reconciles_unlinked_and_station_matched_elements(self) -> None:
        mixed_pitch_id = str(uuid4())
        linked_we_id = str(uuid4())
        station_matched_we_id = str(uuid4())
        station_only_we_id = str(uuid4())
        linked_yam_id = str(uuid4())
        station_matched_yam_id = str(uuid4())
        unlinked_yam_id = str(uuid4())
        timestamp = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES (?, ?, ?, '01-AY1-099', 'Mixed Tag Pitch', ?)""",
                (mixed_pitch_id, self.project_id, self.area_id, timestamp),
            )
            # 1. Linked work element + yamazumi element
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, model_applicability, updated_at)
                   VALUES (?, ?, ?, 10, '01-AY1-099', 'Step 1 Linked', 'All', ?)""",
                (linked_we_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id, description, time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'Step 1 Linked', 5.0, 10, ?)""",
                (linked_yam_id, self.project_id, self.area_id, mixed_pitch_id, linked_we_id, timestamp),
            )
            # 2. Unlinked yamazumi element with a matching station work_elements row
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, model_applicability, updated_at)
                   VALUES (?, ?, ?, 20, '01-AY1-099', 'Step 2 Station Match', 'All', ?)""",
                (station_matched_we_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id, description, time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, NULL, 'Step 2 Station Match', 6.0, 20, ?)""",
                (station_matched_yam_id, self.project_id, self.area_id, mixed_pitch_id, timestamp),
            )
            # 3. Unlinked yamazumi element with NO work_elements row yet
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id, description, time_s, sequence, updated_at)
                   VALUES (?, ?, ?, ?, NULL, 'Step 3 Unlinked Yamazumi', 7.0, 30, ?)""",
                (unlinked_yam_id, self.project_id, self.area_id, mixed_pitch_id, timestamp),
            )
            # 4. Station-only work_elements row with no yamazumi_elements row
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, model_applicability, updated_at)
                   VALUES (?, ?, ?, 40, '01-AY1-099', 'Step 4 Station Only', 'All', ?)""",
                (station_only_we_id, self.project_id, self.scenario_id, timestamp),
            )

        summary = store.process_pitch_visual_summary(
            self.project_id, self.scenario_id, mixed_pitch_id
        )
        elements = summary["elements"]
        self.assertEqual(len(elements), 3)
        self.assertEqual(elements[0]["work_element_id"], linked_we_id)
        self.assertEqual(elements[1]["work_element_id"], station_matched_we_id)
        self.assertEqual(elements[2]["work_element_id"], f"yam::{unlinked_yam_id}")
        self.assertNotIn(station_only_we_id, [el["work_element_id"] for el in elements])

        # Save visual aid tagged to Step 2 (station-matched) and Step 3 (unlinked yamazumi)
        saved = store.save_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=mixed_pitch_id,
            filename="tag_test.png",
            file_bytes=b"\x89PNG\r\n\x1a\ntag_test_bytes",
            caption="Visual Aid",
            tagged_work_element_ids=[
                elements[1]["work_element_id"],
                elements[2]["work_element_id"],
            ],
            sequence=10,
            current_editor="Tester",
        )
        try:
            self.assertEqual(len(saved["tagged_work_element_ids"]), 2)
            self.assertIn(station_matched_we_id, saved["tagged_work_element_ids"])
            reconciled_step3_we_id = next(
                wid for wid in saved["tagged_work_element_ids"] if wid != station_matched_we_id
            )

            # Both yamazumi elements should now have process_element_id linked in DB
            with store.connection() as conn:
                y2_proc = conn.execute(
                    "SELECT process_element_id FROM yamazumi_elements WHERE id=?",
                    (station_matched_yam_id,),
                ).fetchone()[0]
                y3_proc = conn.execute(
                    "SELECT process_element_id FROM yamazumi_elements WHERE id=?",
                    (unlinked_yam_id,),
                ).fetchone()[0]
            self.assertEqual(y2_proc, station_matched_we_id)
            self.assertEqual(y3_proc, reconciled_step3_we_id)

            # Re-fetching summary now shows real work_element_id for the 3 active Yamazumi steps
            summary_after = store.process_pitch_visual_summary(
                self.project_id, self.scenario_id, mixed_pitch_id
            )
            self.assertEqual(
                [el["work_element_id"] for el in summary_after["elements"]],
                [linked_we_id, station_matched_we_id, reconciled_step3_we_id],
            )
            media_after = summary_after["visual_media"]
            self.assertEqual(len(media_after), 1)
            self.assertEqual(
                set(media_after[0]["tagged_work_element_ids"]),
                {station_matched_we_id, reconciled_step3_we_id},
            )
            rendered_html = render_pitch_canvas(
                summary_after,
                summary_after["elements"],
                scenario_name="Rev A Plan",
                project_name="Test Project",
            )
            self.assertIn(
                '<div class="visual-step-line"><span class="visual-tag-badge">2</span><span class="visual-tag-title" title="Step 2 Station Match">Step 2 Station Match</span></div>',
                rendered_html,
            )
            self.assertIn(
                '<div class="visual-step-line"><span class="visual-tag-badge">3</span><span class="visual-tag-title" title="Step 3 Unlinked Yamazumi">Step 3 Unlinked Yamazumi</span></div>',
                rendered_html,
            )
            self.assertNotIn('<div class="caption-callout">', rendered_html)

            # Update wording on the Yamazumi element and verify the visual aid step title reflects the updated wording
            store.update_yamazumi_element(
                self.project_id,
                self.area_id,
                unlinked_yam_id,
                {
                    "description": "Install front control bracket, run wires through hole",
                    "pitch_id": mixed_pitch_id,
                    "time_s": 12.0,
                    "work_type": "Cycle",
                    "model_variants": ["All models"],
                },
            )
            summary_reworded = store.process_pitch_visual_summary(
                self.project_id, self.scenario_id, mixed_pitch_id
            )
            self.assertEqual(
                summary_reworded["elements"][2]["operation"],
                "Install front control bracket, run wires through hole",
            )
            media_reworded = summary_reworded["visual_media"]
            tag_ops = {t["work_element_id"]: t["operation"] for t in media_reworded[0]["tagged_work_elements"]}
            self.assertEqual(
                tag_ops.get(reconciled_step3_we_id),
                "Install front control bracket, run wires through hole",
            )
            rendered_reworded = render_pitch_canvas(
                summary_reworded,
                summary_reworded["elements"],
                scenario_name="Rev A Plan",
                project_name="Test Project",
            )
            self.assertIn(
                '<div class="visual-step-line"><span class="visual-tag-badge">3</span><span class="visual-tag-title" title="Install front control bracket, run wires through hole">Install front control bracket, run wires through hole</span></div>',
                rendered_reworded,
            )
            self.assertNotIn("Step 3 Unlinked Yamazumi", rendered_reworded)
        finally:
            Path(saved["file_path"]).unlink(missing_ok=True)
            if saved.get("original_file_path"):
                Path(saved["original_file_path"]).unlink(missing_ok=True)

    def test_updating_part_image_or_annotations_updates_visual_aid(self) -> None:
        import base64
        import io
        import json
        from PIL import Image

        def _make_png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (80, 60)) -> bytes:
            buf = io.BytesIO()
            Image.new("RGB", size, color).save(buf, format="PNG")
            return buf.getvalue()

        initial_part_bytes = _make_png_bytes((20, 40, 200))
        annotated_part_bytes = _make_png_bytes((220, 30, 30))
        base_visual_bytes = _make_png_bytes((240, 240, 240), size=(200, 150))

        created_files: list[str] = []
        try:
            parts_df = store.project_table("parts", self.project_id)
            self.assertFalse(parts_df.empty)
            self.assertFalse(store.project_table(self.project_id, "parts").empty)
            test_part_id = str(parts_df.iloc[0]["id"])
            test_part_number = str(parts_df.iloc[0]["part_number"])
            # 1. Set initial primary image on test_part_id
            from utils.clipboard_image import as_uploaded_file
            part_img_path = store.set_part_image(
                test_part_id,
                as_uploaded_file({"name": "pn1001_init.png", "bytes": initial_part_bytes}),
                original_file_bytes=initial_part_bytes,
                original_filename="pn1001_init.png",
            )
            created_files.append(part_img_path)

            # 2a. Copy part photo directly as a pitch visual aid
            direct_res = store.copy_part_photo_to_pitch_visual_media(
                project_id=self.project_id,
                scenario_id=self.scenario_id,
                pitch_id=self.pitch_id,
                part_id=test_part_id,
                tagged_work_element_ids=[self.work_ids[0]],
                sequence=10,
                current_editor="Tester",
            )
            created_files.append(direct_res["file_path"])
            if direct_res.get("original_file_path"):
                created_files.append(direct_res["original_file_path"])

            # 2b. Create a visual aid with an inset type="image" part photo shape in annotations_json
            initial_data_url = "data:image/png;base64," + base64.b64encode(initial_part_bytes).decode("ascii")
            inset_annotations = json.dumps(
                [
                    {
                        "type": "image",
                        "x": 20,
                        "y": 15,
                        "w": 100,
                        "h": 75,
                        "dataUrl": initial_data_url,
                        "label": test_part_number,
                    }
                ]
            )
            inset_res = store.save_pitch_visual_media(
                project_id=self.project_id,
                scenario_id=self.scenario_id,
                pitch_id=self.pitch_id,
                filename="station_overview.png",
                file_bytes=base_visual_bytes,
                original_file_bytes=base_visual_bytes,
                annotations_json=inset_annotations,
                caption="Station with inset part photo",
                tagged_work_element_ids=[self.work_ids[0]],
                sequence=20,
                current_editor="Tester",
            )
            created_files.append(inset_res["file_path"])
            if inset_res.get("original_file_path"):
                created_files.append(inset_res["original_file_path"])

            # 3. Update the part image annotations in the Parts Catalog
            new_part_img_path = store.update_part_primary_image_annotations(
                project_id=self.project_id,
                part_id=test_part_id,
                annotations_json=json.dumps([{"type": "callout", "text": "1/4 hex", "x": 0.2, "y": 0.2, "tx": 0.5, "ty": 0.5}]),
                composite_image_bytes=annotated_part_bytes,
                current_editor="Tester",
            )
            created_files.append(new_part_img_path)

            # 4. Verify both the direct part visual aid and the inset part photo visual aid were updated!
            media_items = {
                m["id"]: m
                for m in store.get_pitch_visual_media(self.project_id, self.scenario_id, self.pitch_id)
            }
            direct_item = media_items[direct_res["id"]]
            created_files.append(direct_item["file_path"])
            if direct_item.get("original_file_path"):
                created_files.append(direct_item["original_file_path"])
            self.assertEqual(Path(direct_item["file_path"]).read_bytes(), annotated_part_bytes)

            inset_item = media_items[inset_res["id"]]
            inset_shapes = json.loads(inset_item["annotations_json"])
            expected_data_url = "data:image/png;base64," + base64.b64encode(annotated_part_bytes).decode("ascii")
            self.assertEqual(inset_shapes[0]["dataUrl"], expected_data_url)
            self.assertEqual(inset_shapes[0].get("partId"), test_part_id)

            # Also verify the composite image on disk for inset_item was re-rendered with the red annotated part image
            with Image.open(inset_item["file_path"]) as comp_im:
                comp_rgb = comp_im.convert("RGB")
                # Center of inset box (0.1..0.6 x, 0.1..0.6 y -> pixel (70, 52) on 200x150 image)
                r_px, g_px, b_px = comp_rgb.getpixel((70, 52))
                self.assertGreater(r_px, 180)
                self.assertLess(b_px, 80)
        finally:
            for fp in set(created_files):
                if fp:
                    Path(fp).unlink(missing_ok=True)


    def test_render_paag_pptx_deck_produces_valid_pptx_with_media(self) -> None:
        import io
        import xml.etree.ElementTree as ET
        import zipfile
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (120, 90), (40, 120, 200)).save(buf, format="PNG")
        sample_png = buf.getvalue()

        saved_media = store.save_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=self.pitch_id,
            filename="pptx_step_photo.png",
            file_bytes=sample_png,
            caption="Use torque wrench at 45 Nm",
            tagged_work_element_ids=[self.work_ids[0]],
            sequence=10,
            current_editor="Tester",
        )
        try:
            summary = store.process_pitch_visual_summary(
                self.project_id, self.scenario_id, self.pitch_id
            )
            pptx_bytes = render_paag_pptx_deck(
                [
                    {
                        "pitch": summary,
                        "elements": summary.get("elements", []),
                        "page_num": 1,
                        "total_pages": 1,
                    }
                ],
                paper_size="letter",
                image_fit="contain",
                scenario_name="Rev A Plan",
                project_name="Nexus Dryer",
                title="PAAG Export Test",
            )
            self.assertTrue(pptx_bytes.startswith(b"PK"))
            with zipfile.ZipFile(io.BytesIO(pptx_bytes), "r") as zf:
                names = set(zf.namelist())
                self.assertIn("[Content_Types].xml", names)
                self.assertIn("_rels/.rels", names)
                self.assertIn("ppt/presentation.xml", names)
                self.assertIn("ppt/slides/slide1.xml", names)
                self.assertIn("ppt/slides/_rels/slide1.xml.rels", names)
                media_files = [n for n in names if n.startswith("ppt/media/")]
                self.assertGreaterEqual(len(media_files), 1)
                for name in names:
                    if name.endswith((".xml", ".rels")):
                        ET.fromstring(zf.read(name))
                slide1_text = zf.read("ppt/slides/slide1.xml").decode("utf-8")
                self.assertIn(summary["pitch_number"], slide1_text)
                self.assertIn("GE Appliances Logo", slide1_text)
                self.assertIn("Process at a Glance", slide1_text)
                self.assertIn('numCol="2"', slide1_text)
                self.assertIn("Project: ", slide1_text)
                self.assertIn("Building: ", slide1_text)
                self.assertIn("Section: ", slide1_text)
                self.assertIn("Date: ", slide1_text)
                self.assertIn("Scenario: ", slide1_text)
                self.assertIn("Use torque wrench at 45 Nm", slide1_text)
                self.assertIn("TOOLS &amp; PPE REQUIRED", slide1_text)
                self.assertIn("YAMAZUMI", slide1_text)
        finally:
            Path(saved_media["file_path"]).unlink(missing_ok=True)
            if saved_media.get("original_file_path"):
                Path(saved_media["original_file_path"]).unlink(missing_ok=True)


    def test_pitch_part_quantity_consume_and_handle_rules(self) -> None:
        timestamp = store.now_iso()
        part_ch_id = str(uuid4())
        part_h_id = str(uuid4())
        fb_ch_id = str(uuid4())
        fb_h_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO parts (id, project_id, part_number, description, updated_at)
                   VALUES (?, ?, '308D3061P001', 'Side Panel Alabaster', ?)""",
                (part_ch_id, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO parts (id, project_id, part_number, description, updated_at)
                   VALUES (?, ?, '999D0001P001', 'Handled Only Subframe', ?)""",
                (part_h_id, self.project_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                   VALUES (?, ?, ?, ?, 10, 1.0, 'North Side Panel Press', ?)""",
                (fb_ch_id, self.project_id, self.section_id, part_ch_id, timestamp),
            )
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, section_id, part_id, sequence, quantity, use_description, updated_at)
                   VALUES (?, ?, ?, ?, 20, 1.0, 'Upstream Frame', ?)""",
                (fb_h_id, self.project_id, self.section_id, part_h_id, timestamp),
            )

        upstream_we_id = str(uuid4())
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation, model_applicability, updated_at)
                   VALUES (?, ?, ?, 5, '01-SW1-050', 'Consume Subframe Upstream', 'All', ?)""",
                (upstream_we_id, self.project_id, self.scenario_id, timestamp),
            )
        store.save_process_part_group(
            self.project_id,
            self.scenario_id,
            upstream_we_id,
            self.section_id,
            str(uuid4()),
            "Upstream Frame Consume",
            "Use all",
            1,
            [part_h_id],
            handling_types_by_part={part_h_id: "Consume"},
            fishbone_assignment_ids_by_part={part_h_id: fb_h_id},
        )

        # Step 1: Consume 308D3061P001 (qty 1)
        store.save_process_part_group(
            self.project_id,
            self.scenario_id,
            self.work_ids[0],
            self.section_id,
            str(uuid4()),
            "Panel Consume",
            "Use all",
            1,
            [part_ch_id],
            handling_types_by_part={part_ch_id: "Consume"},
            fishbone_assignment_ids_by_part={part_ch_id: fb_ch_id},
        )
        # Step 2: Handle 308D3061P001 AND Handle 999D0001P001
        store.save_process_part_group(
            self.project_id,
            self.scenario_id,
            self.work_ids[1],
            self.section_id,
            str(uuid4()),
            "Panel & Frame Handle",
            "Use all",
            1,
            [part_ch_id, part_h_id],
            handling_types_by_part={part_ch_id: "Handle", part_h_id: "Handle"},
        )

        summary = store.process_pitch_visual_summary(
            self.project_id, self.scenario_id, self.pitch_id
        )
        parts_by_num = {p["part_number"]: p for p in summary["parts"]}
        # 1. Part with both Consume (qty 1) and Handle on pitch shows Consume quantity only (1.0)
        self.assertEqual(parts_by_num["308D3061P001"]["quantity"], 1.0)
        self.assertEqual(set(parts_by_num["308D3061P001"]["handling_types"]), {"Consume", "Handle"})
        # 2. Part with only Handle on pitch has None quantity
        self.assertIsNone(parts_by_num["999D0001P001"]["quantity"])
        self.assertEqual(set(parts_by_num["999D0001P001"]["handling_types"]), {"Handle"})

        rendered_html = render_pitch_canvas(
            summary,
            summary["elements"],
            scenario_name="Rev A Plan",
            project_name="Nexus Dryer",
        )
        self.assertIn('<td class="col-qty">1</td>', rendered_html)
        self.assertIn('<td class="col-qty"></td>', rendered_html)
        self.assertNotIn('<td class="col-qty">2</td>', rendered_html)

    def test_part_has_model_variants_ignores_same_prefix_all_model_hardware(self) -> None:
        placements_df = pd.DataFrame(
            [
                {
                    "part_id": "part_screw_341",
                    "part_number": "8911201P341",
                    "section_id": "sec_mbb",
                    "step_number": 1,
                    "variant_group": "8911201P227, 8911201P281, 8911201P679",
                    "model_applicability": "All",
                },
                {
                    "part_id": "part_brkt_nrml",
                    "part_number": "308D1405P001",
                    "section_id": "sec_mbb",
                    "step_number": 1,
                    "variant_group": "",
                    "model_applicability": "GFD36ESMB0WW, GFD56ESMB0WW",
                },
                {
                    "part_id": "part_brkt_long",
                    "part_number": "308D1406P001",
                    "section_id": "sec_mbb",
                    "step_number": 1,
                    "variant_group": "",
                    "model_applicability": "GFV36ESSB0WW",
                },
                {
                    "part_id": "part_stack_a",
                    "part_number": "308D9001P001",
                    "section_id": "sec_mbb",
                    "step_number": 2,
                    "variant_group": "",
                    "model_applicability": "All",
                },
                {
                    "part_id": "part_stack_b",
                    "part_number": "308D9002P001",
                    "section_id": "sec_mbb",
                    "step_number": 2,
                    "variant_group": "",
                    "model_applicability": "All",
                },
            ]
        )
        # 1. All-model hardware screw with auto-grouped drawing prefix peers is NOT a model variant
        self.assertFalse(
            store.part_has_model_variants(
                "part_screw_341",
                placements_df,
                section_id="sec_mbb",
                fallback_model_applicability="All",
            )
        )
        # 2. Model-specific brackets ARE model variant parts
        self.assertTrue(
            store.part_has_model_variants(
                "part_brkt_nrml",
                placements_df,
                section_id="sec_mbb",
                fallback_model_applicability="GFD36ESMB0WW, GFD56ESMB0WW",
            )
        )
        self.assertTrue(
            store.part_has_model_variants(
                "part_brkt_long",
                placements_df,
                section_id="sec_mbb",
                fallback_model_applicability="GFV36ESSB0WW",
            )
        )
        # 3. Explicitly canvas-stacked parts (step_number > 1 with >=2 peers in section) ARE model variants
        self.assertTrue(
            store.part_has_model_variants(
                "part_stack_a",
                placements_df,
                section_id="sec_mbb",
                fallback_model_applicability="All",
            )
        )

    def test_copy_visual_media_across_pitches_preserves_independent_annotations(self) -> None:
        dest_pitch_id = "pitch_dest_copy_test"
        dest_work_id = "we_dest_copy_test"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, updated_at)
                   VALUES (?, ?, ?, '01-SW1-052', 'Destination Pitch', ?)""",
                (dest_pitch_id, self.project_id, self.area_id, timestamp),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    model_applicability, updated_at)
                   VALUES (?, ?, ?, 10, '01-SW1-052', 'Install side panel on P2', 'All', ?)""",
                (dest_work_id, self.project_id, self.scenario_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, process_element_id,
                    description, time_s, sequence, updated_at)
                   VALUES ('yam-dest-1', ?, ?, ?, ?, 'Install side panel on P2', 12.0, 10, ?)""",
                (self.project_id, self.area_id, dest_pitch_id, dest_work_id, timestamp),
            )

        initial_annotations = '[{"type":"callout","text":"Step 1 on P1","x":0.2,"y":0.3}]'
        src_media = store.save_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=self.pitch_id,
            filename="panel_callout.png",
            file_bytes=b"\x89PNG\r\n\x1a\ncomposite_p1_bytes",
            original_file_bytes=b"\x89PNG\r\n\x1a\nclean_base_bytes",
            annotations_json=initial_annotations,
            caption="P1 Side Panel Callout",
            tagged_work_element_ids=[self.work_ids[0]],
            sequence=10,
            current_editor="Tester",
        )

        copied_media = store.copy_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            media_id=src_media["id"],
            target_pitch_id=dest_pitch_id,
            caption="P2 Side Panel Callout",
            sequence=15,
            tagged_work_element_ids=[dest_work_id],
            current_editor="Tester",
        )
        self.assertNotEqual(copied_media["id"], src_media["id"])
        self.assertEqual(copied_media["pitch_id"], dest_pitch_id)
        self.assertEqual(copied_media["annotations_json"], initial_annotations)
        self.assertNotEqual(copied_media["file_path"], src_media["file_path"])
        self.assertNotEqual(copied_media["original_file_path"], src_media["original_file_path"])
        self.assertTrue(Path(copied_media["file_path"]).exists())
        self.assertTrue(Path(copied_media["original_file_path"]).exists())

        # Editing annotations on the destination pitch must not alter the source pitch's visual aid
        updated_dest_annotations = '[{"type":"callout","text":"Edited for P2","x":0.5,"y":0.6}]'
        store.update_pitch_visual_annotations(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            media_id=copied_media["id"],
            annotations_json=updated_dest_annotations,
            composite_image_bytes=b"\x89PNG\r\n\x1a\ncomposite_p2_updated_bytes",
            current_editor="Tester",
        )

        p1_items = store.get_pitch_visual_media(self.project_id, self.scenario_id, self.pitch_id)
        p2_items = store.get_pitch_visual_media(self.project_id, self.scenario_id, dest_pitch_id)
        src_reloaded = next(m for m in p1_items if m["id"] == src_media["id"])
        dest_reloaded = next(m for m in p2_items if m["id"] == copied_media["id"])

        self.assertEqual(src_reloaded["annotations_json"], initial_annotations)
        self.assertEqual(Path(src_reloaded["file_path"]).read_bytes(), b"\x89PNG\r\n\x1a\ncomposite_p1_bytes")
        self.assertEqual(dest_reloaded["annotations_json"], updated_dest_annotations)
        self.assertEqual(Path(dest_reloaded["file_path"]).read_bytes(), b"\x89PNG\r\n\x1a\ncomposite_p2_updated_bytes")
        self.assertEqual(Path(dest_reloaded["original_file_path"]).read_bytes(), b"\x89PNG\r\n\x1a\nclean_base_bytes")

    def test_paag_slide_header_logo_and_detail_box_fields(self) -> None:
        with store.connection() as conn:
            conn.execute(
                "UPDATE projects SET name=?, building_location=? WHERE id=?",
                ("GFD36", "AP1", self.project_id),
            )
        summary = store.process_pitch_visual_summary(
            self.project_id, self.scenario_id, self.pitch_id
        )
        self.assertEqual(summary["project_name"], "GFD36")
        self.assertEqual(summary["building_location"], "AP1")
        self.assertEqual(summary["section_name"], "Main")

        html_out = render_pitch_canvas(
            summary,
            summary.get("elements", []),
            generated_on=date(2026, 4, 20),
        )
        self.assertIn("header-logo-img", html_out)
        self.assertIn('<div class="header-doc-title">Process at a Glance</div>', html_out)
        self.assertIn("<div><strong>Project:</strong> GFD36</div>", html_out)
        self.assertIn("<div><strong>Building:</strong> AP1</div>", html_out)
        self.assertIn("<div><strong>Section:</strong> Main</div>", html_out)
        self.assertIn("<div><strong>Date:</strong> April 20, 2026</div>", html_out)
        self.assertIn(f"<div><strong>Scenario:</strong> {summary['scenario_name']}</div>", html_out)

    def test_inset_part_photo_renders_entire_photo_above_label_footer(self) -> None:
        import base64
        import io
        from PIL import Image
        from utils.image_annotator import _draw_annotator_shape_pil

        # Create a 100x100 part photo whose bottom 20px is bright green (0, 220, 0)
        part_im = Image.new("RGBA", (100, 100), (220, 0, 0, 255))
        for py in range(80, 100):
            for px in range(100):
                part_im.putpixel((px, py), (0, 220, 0, 255))
        buf = io.BytesIO()
        part_im.save(buf, format="PNG")
        d_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

        canvas = Image.new("RGBA", (300, 300), (255, 255, 255, 255))
        shape = {
            "id": "sh_latch",
            "type": "image",
            "x": 20,
            "y": 20,
            "w": 120,
            "h": 140,
            "dataUrl": d_url,
            "label": "308D3028P001",
            "color": "#0284c7",
            "strokeWidth": 3,
        }
        _draw_annotator_shape_pil(canvas, shape, 1.0, 1.0)

        # Verify the bottom-most green strip of the part photo is visible above the dark footer banner
        green_pixels_found = 0
        for py in range(25, 155):
            r, g, b, _ = canvas.getpixel((80, py))
            if g > 180 and r < 50 and b < 50:
                green_pixels_found += 1
        self.assertGreater(
            green_pixels_found,
            8,
            "Bottom details of the part photo should remain visible above the part-number footer.",
        )

    def test_sync_model_variant_placement_selections_populates_tied_variants(self) -> None:
        import pandas as pd

        all_placements = pd.DataFrame(
            [
                {
                    "id": "fb-p1-a",
                    "part_id": "pid-1",
                    "part_number": "308D3012P001",
                    "section_id": "sec-cab",
                    "section_name": "Cabinet & Console",
                    "use_description": "Front Panel Left",
                },
                {
                    "id": "fb-p1-b",
                    "part_id": "pid-1",
                    "part_number": "308D3012P001",
                    "section_id": "sec-cab",
                    "section_name": "Cabinet & Console",
                    "use_description": "Front Panel Right",
                },
                {
                    "id": "fb-p2-a",
                    "part_id": "pid-2",
                    "part_number": "308D3012P002",
                    "section_id": "sec-cab",
                    "section_name": "Cabinet & Console",
                    "use_description": "Front Panel Left",
                },
                {
                    "id": "fb-p2-b",
                    "part_id": "pid-2",
                    "part_number": "308D3012P002",
                    "section_id": "sec-cab",
                    "section_name": "Cabinet & Console",
                    "use_description": "Front Panel Right",
                },
                {
                    "id": "fb-p3-a",
                    "part_id": "pid-3",
                    "part_number": "308D3012P003",
                    "section_id": "sec-cab",
                    "section_name": "Cabinet & Console",
                    "use_description": "Front Panel Left",
                },
                {
                    "id": "fb-p3-b",
                    "part_id": "pid-3",
                    "part_number": "308D3012P003",
                    "section_id": "sec-cab",
                    "section_name": "Cabinet & Console",
                    "use_description": "Front Panel Right",
                },
            ]
        )

        def _opts_for(part_idx: int) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "fishbone_assignment_id": f"fb-p{part_idx}-a",
                        "section_id": "sec-cab",
                        "section_name": "Cabinet & Console",
                        "use_description": "Front Panel Left",
                        "can_consume": True,
                        "can_handle": False,
                    },
                    {
                        "fishbone_assignment_id": f"fb-p{part_idx}-b",
                        "section_id": "sec-cab",
                        "section_name": "Cabinet & Console",
                        "use_description": "Front Panel Right",
                        "can_consume": True,
                        "can_handle": False,
                    },
                ]
            )

        entries = [
            {
                "part_id": "pid-1",
                "part_number": "308D3012P001",
                "is_model_variant": True,
                "handling_type": "Consume",
                "placement_key": "loc_pid_1",
                "placement_options": _opts_for(1),
            },
            {
                "part_id": "pid-2",
                "part_number": "308D3012P002",
                "is_model_variant": True,
                "handling_type": "Consume",
                "placement_key": "loc_pid_2",
                "placement_options": _opts_for(2),
            },
            {
                "part_id": "pid-3",
                "part_number": "308D3012P003",
                "is_model_variant": True,
                "handling_type": "Consume",
                "placement_key": "loc_pid_3",
                "placement_options": _opts_for(3),
            },
        ]

        # 1. Selecting location on 308D3012P001 populates 308D3012P002 and 308D3012P003
        session_state: dict = {
            "loc_pid_1": "fb-p1-a",
            "loc_pid_2": None,
            "loc_pid_3": None,
        }
        store.sync_model_variant_placement_selections(
            entries, all_placements, session_state
        )
        self.assertEqual(session_state["loc_pid_1"], "fb-p1-a")
        self.assertEqual(session_state["loc_pid_2"], "fb-p2-a")
        self.assertEqual(session_state["loc_pid_3"], "fb-p3-a")

        # 2. Changing location on 308D3012P003 updates 308D3012P001 and 308D3012P002
        session_state["loc_pid_3"] = "fb-p3-b"
        store.sync_model_variant_placement_selections(
            entries, all_placements, session_state
        )
        self.assertEqual(session_state["loc_pid_1"], "fb-p1-b")
        self.assertEqual(session_state["loc_pid_2"], "fb-p2-b")
        self.assertEqual(session_state["loc_pid_3"], "fb-p3-b")

    def test_duplicate_yamazumi_elements_copies_to_destination_pitch_in_active_scenario(
        self,
    ) -> None:
        area_id = self.area_id
        pitch_a_id = store.add_yamazumi_pitch(
            self.project_id,
            area_id,
            "01-ML1-001",
            "Station 1",
            "Active",
            ["All models", "Feature A"],
        )
        pitch_b_id = store.add_yamazumi_pitch(
            self.project_id,
            area_id,
            "01-ML1-002",
            "Station 2",
            "Active",
            ["All models"],
        )
        elem_id = store.add_yamazumi_element(
            self.project_id,
            area_id,
            pitch_a_id,
            {
                "description": "Install door latch",
                "time_s": 14.5,
                "model_variants": ["Feature A"],
                "work_type": "Cycle",
                "work_region": "None",
            },
        )

        # Copy work element from Pitch A to Pitch B in the active scenario
        result = store.duplicate_yamazumi_elements(
            self.project_id,
            self.scenario_id,
            [elem_id],
            target_pitch_id=pitch_b_id,
            editor_name="IE Collaborator",
        )
        self.assertEqual(result["copied_count"], 1)
        self.assertEqual(result["target_pitch_id"], pitch_b_id)
        self.assertEqual(result["target_pitch_number"], "01-ML1-002")
        self.assertIn("Feature A", result["enabled_variants"])

        elements_df = store.yamazumi_elements(self.project_id, area_id)
        pitch_b_elems = elements_df.loc[
            elements_df["pitch_id"].astype(str) == str(pitch_b_id)
        ]
        self.assertEqual(len(pitch_b_elems), 1)
        self.assertEqual(
            str(pitch_b_elems.iloc[0]["description"]), "Install door latch"
        )

        # Verify copying to a pitch in another scenario is rejected
        other_scenario_id = str(uuid4())
        other_area_id = str(uuid4())
        other_pitch_id = str(uuid4())
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, status, created_at, updated_at)
                   VALUES (?, ?, 'Other Scenario', 'B', 'Draft', ?, ?)""",
                (other_scenario_id, self.project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES (?, ?, ?, ?, 'Other area', ?)""",
                (other_area_id, self.project_id, other_scenario_id, self.section_id, timestamp),
            )
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status, updated_at)
                   VALUES (?, ?, ?, '01-ML1-099', 'Other Station', 'Active', ?)""",
                (other_pitch_id, self.project_id, other_area_id, timestamp),
            )
        with self.assertRaises(ValueError):
            store.duplicate_yamazumi_elements(
                self.project_id,
                self.scenario_id,
                [elem_id],
                target_pitch_id=other_pitch_id,
                editor_name="IE Collaborator",
            )


if __name__ == "__main__":
    unittest.main()



