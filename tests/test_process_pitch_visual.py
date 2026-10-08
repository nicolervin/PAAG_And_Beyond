from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

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
        self.assertIn("details", next(
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
        self.assertIn("BRKT-001", html)
        self.assertIn("Functional Alerts", html)
        self.assertIn("Torque Critical", html)
        self.assertIn("Pinch Hazard", html)
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

        fmt_radio = next(r for r in app.radio if "Page Format" in r.label)
        self.assertTrue(any("11 × 17" in opt for opt in fmt_radio.options))

        fit_radio = next(r for r in app.radio if "Image Fit in Print" in r.label)
        self.assertTrue(any("Stretch to Fill Box" in opt for opt in fit_radio.options))

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


if __name__ == "__main__":
    unittest.main()


