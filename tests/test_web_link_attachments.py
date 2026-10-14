from __future__ import annotations

from contextlib import closing
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from utils import store
from utils.fishbone_visual import part_thumbnail
from utils.process_pitch_visual import _media_data_url, render_pitch_canvas
from utils.project_transfer import export_project_package, import_project_package


class WebLinkAttachmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_web_links_{uuid4()}.db"
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
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, station, operation,
                    model_applicability, updated_at)
                   VALUES ('work-1', ?, ?, 10, '01-SW1-051', 'Attach bracket', 'All', ?)""",
                (self.project_id, self.scenario_id, timestamp),
            )

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_part_cad_image_url_round_trip(self) -> None:
        parts = store.project_table("parts", self.project_id, "part_number")
        part_id = str(parts.iloc[0]["id"])

        cad_url = "https://windchill.company.internal/models/3d/view?id=12345"
        store.set_part_image_url(part_id, cad_url)

        updated_parts = store.project_table("parts", self.project_id, "part_number")
        row = updated_parts.loc[updated_parts["id"] == part_id].iloc[0]
        self.assertEqual(row["image_path"], cad_url)

        # Thumbnail helper returns URL directly
        thumb = part_thumbnail(cad_url)
        self.assertEqual(thumb, cad_url)

        # Clear part image
        store.clear_part_image(part_id)
        cleared_parts = store.project_table("parts", self.project_id, "part_number")
        cleared_row = cleared_parts.loc[cleared_parts["id"] == part_id].iloc[0]
        self.assertEqual(cleared_row["image_path"], "")

    def test_part_cad_image_url_validation(self) -> None:
        parts = store.project_table("parts", self.project_id, "part_number")
        part_id = str(parts.iloc[0]["id"])

        with self.assertRaises(ValueError):
            store.set_part_image_url(part_id, "invalid-url-without-protocol")

    def test_part_supplemental_views_url_round_trip(self) -> None:
        parts = store.project_table("parts", self.project_id, "part_number")
        part_id = str(parts.iloc[0]["id"])

        sharepoint_url = "https://company.sharepoint.com/sites/eng/docs/spec.pdf"
        img_id = store.add_part_image_url(
            part_id,
            url=sharepoint_url,
            image_type="SharePoint Document",
            caption="Official Part Specification PDF",
        )
        self.assertTrue(bool(img_id))

        views = store.part_images(part_id)
        matching = [v for v in views if v["id"] == img_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["image_path"], sharepoint_url)
        self.assertEqual(matching[0]["image_type"], "SharePoint Document")
        self.assertEqual(matching[0]["caption"], "Official Part Specification PDF")

        # Delete view
        store.delete_part_image(img_id)
        views_after = store.part_images(part_id)
        self.assertFalse(any(v["id"] == img_id for v in views_after))

    def test_process_visual_media_url_lifecycle(self) -> None:
        sop_url = "https://sop.company.internal/assembly/workstation_procedure.html"
        saved = store.save_pitch_visual_media_url(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=self.pitch_id,
            url=sop_url,
            caption="Standard Operating Procedure Link",
            sequence=15,
            current_editor="Engineer",
        )
        media_id = saved["id"]
        self.assertEqual(saved["media_type"], "link")
        self.assertEqual(saved["file_path"], sop_url)

        # Retrieval
        media_items = store.get_pitch_visual_media(self.project_id, self.scenario_id, self.pitch_id)
        item = next(m for m in media_items if m["id"] == media_id)
        self.assertEqual(item["caption"], "Standard Operating Procedure Link")
        self.assertEqual(item["media_type"], "link")
        self.assertEqual(item["file_path"], sop_url)

        # Media URL helper returns external URL directly
        self.assertEqual(_media_data_url(sop_url), sop_url)

        # Update URL and caption
        new_url = "https://sop.company.internal/assembly/workstation_procedure_v2.html"
        store.update_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            media_id=media_id,
            caption="Updated SOP Link",
            sequence=20,
            url=new_url,
        )
        updated_items = store.get_pitch_visual_media(self.project_id, self.scenario_id, self.pitch_id)
        updated_item = next(m for m in updated_items if m["id"] == media_id)
        self.assertEqual(updated_item["caption"], "Updated SOP Link")
        self.assertEqual(updated_item["file_path"], new_url)

        # Render slide canvas includes link card
        pitch_dict = {"pitch_number": "01-SW1-051", "pitch_name": "Pitch visual"}
        html = render_pitch_canvas(
            pitch=pitch_dict,
            visual_media=updated_items,
        )
        self.assertIn("media-link-card", html)
        self.assertIn(new_url, html)

        # Safe deletion without filesystem unlinking errors
        store.delete_pitch_visual_media(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            media_id=media_id,
        )
        remaining = store.get_pitch_visual_media(self.project_id, self.scenario_id, self.pitch_id)
        self.assertFalse(any(m["id"] == media_id for m in remaining))

    def test_export_import_preserves_web_urls(self) -> None:
        parts = store.project_table("parts", self.project_id, "part_number")
        part_id = str(parts.iloc[0]["id"])
        cad_url = "https://windchill.company.internal/models/3d/view?id=999"
        store.set_part_image_url(part_id, cad_url)

        sop_url = "https://sharepoint.company.com/sop/deck_assembly.pdf"
        store.save_pitch_visual_media_url(
            project_id=self.project_id,
            scenario_id=self.scenario_id,
            pitch_id=self.pitch_id,
            url=sop_url,
            caption="Deck Assembly PDF",
        )

        package = export_project_package(self.project_id, "Test User")
        imported = import_project_package(package["data"], "Create new", "Test User")
        imported_proj_id = imported["project_id"]
        imported_scen_id = imported["scenario_id"]

        # Check parts
        imp_parts = store.project_table("parts", imported_proj_id, "part_number")
        self.assertTrue((imp_parts["image_path"] == cad_url).any())

        # Check visual media
        imp_pitches = store.yamazumi_pitches_for_scenario(imported_proj_id, imported_scen_id)
        found_media = False
        for _, p in imp_pitches.iterrows():
            items = store.get_pitch_visual_media(imported_proj_id, imported_scen_id, p["id"])
            for it in items:
                if it["file_path"] == sop_url:
                    found_media = True
                    self.assertEqual(it["media_type"], "link")
        self.assertTrue(found_media)


if __name__ == "__main__":
    unittest.main()
