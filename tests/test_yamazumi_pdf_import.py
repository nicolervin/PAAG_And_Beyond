import os
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pandas as pd

from utils.yamazumi_pdf import (
    _decompress_pdf_stream,
    _last_rgb_fill_before,
    _work_item_anchor_x,
    _work_type_from_fill_color,
    parse_yamazumi_pdf,
)
from utils.yamazumi_store import import_yamazumi_rows, yamazumi_elements_for_scenario
from utils import store


class TestYamazumiPdfStreamDecompression(unittest.TestCase):
    def test_recovers_a_stripped_terminal_newline_byte(self):
        payload = b"Yamazumi PDF page \x00\xe5"
        compressed = zlib.compress(payload)
        self.assertTrue(compressed.endswith(b"\n"))
        self.assertEqual(_decompress_pdf_stream(compressed[:-1]), payload)


class TestYamazumiPdfWorkTypeColors(unittest.TestCase):
    def test_maps_approved_red_to_fluctuation(self):
        self.assertEqual(
            _work_type_from_fill_color((1.0, 0.0, 0.0)),
            "Fluctuation",
        )

    def test_maps_approved_yellow_to_periodic(self):
        self.assertEqual(
            _work_type_from_fill_color((1.0, 1.0, 0.0)),
            "Periodic",
        )

    def test_uses_small_tolerance_for_export_color_variation(self):
        self.assertEqual(
            _work_type_from_fill_color((1.0, 0.12, 0.12)),
            "Fluctuation",
        )
        self.assertEqual(
            _work_type_from_fill_color((1.0, 1.0, 0.08)),
            "Periodic",
        )

    def test_other_or_missing_colors_default_to_cycle(self):
        self.assertEqual(
            _work_type_from_fill_color((0.6078, 1.0, 0.6078)),
            "Cycle",
        )
        self.assertEqual(_work_type_from_fill_color(None), "Cycle")

    def test_color_lookup_uses_the_requested_stream_position(self):
        content = (
            "1 0 0 rg BT (2.5s) Tj ET "
            "1 1 0 rg BT (2.5s) Tj ET"
        )
        second_time_index = content.rindex("BT (2.5s)")

        self.assertEqual(
            _last_rgb_fill_before(content, second_time_index),
            (1.0, 1.0, 0.0),
        )


class TestYamazumiPdfWorkRowOwnership(unittest.TestCase):
    def test_duration_uses_description_anchor_instead_of_header_midpoint(self):
        time_item = {"x": 163.73, "y": 169.01, "text": "3.5s"}
        texts = [
            {"x": 17.01, "y": 169.01, "text": "Look at screen pick the"},
            time_item,
            {"x": 215.44, "y": 180.0, "text": "Neighboring pitch text"},
        ]

        self.assertEqual(_work_item_anchor_x(time_item, texts), 17.01)


class TestYamazumiPdfImport(unittest.TestCase):
    SAMPLE_PDF_PATH = r"C:\Users\240036666\Downloads\yamazumi_AP1_434_Nexus 2027 (2).pdf"
    COLOR_SAMPLE_PDF_PATH = (
        r"C:\Users\240036666\Downloads\yamazumi_AP1_58_Initial (2).pdf"
    )

    def setUp(self):
        self.database_path = store.DATA_DIR / f"test_yamazumi_pdf_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()

    def tearDown(self):
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    @staticmethod
    def _minimal_pdf(*page_contents: str) -> bytes:
        document = bytearray(b"%PDF-1.4\n")
        for content in page_contents:
            compressed = zlib.compress(content.encode("latin1"))
            document.extend(
                f"<< /Length {len(compressed)} >>\nstream\n".encode("ascii")
            )
            document.extend(compressed)
            document.extend(b"\nendstream\n")
        return bytes(document)

    def test_does_not_create_work_element_from_standalone_time_label(self):
        pdf = self._minimal_pdf(
            "BT 0 0 Td (Plant Name: AP1) Tj "
            "BT 0 0 Td (Line: Asm 1) Tj "
            "BT 0 0 Td (Sub Line: Asm 1 North 1) Tj "
            "BT 0 0 Td (Takt Time: 17.5) Tj",
            "BT 100 40 Td (01-AY1-012) Tj "
            "BT 100 80.84 Td (Base_Variant Electric) Tj "
            "BT 100 120 Td (3.5 s) Tj",
        )

        result = parse_yamazumi_pdf(pdf)

        self.assertEqual(
            [pitch["pitch_number"] for pitch in result["pitches"]],
            ["01-AY1-012"],
        )
        self.assertEqual(
            result["pitch_dataframe"]["Pitch_number"].tolist(),
            ["01-AY1-012"],
        )
        self.assertEqual(
            result["pitch_dataframe"].iloc[0]["Model_variants"],
            ["Base_Variant Electric"],
        )
        self.assertTrue(result["dataframe"].empty)

    def test_creates_work_element_when_time_has_description_text(self):
        pdf = self._minimal_pdf(
            "BT 0 0 Td (Plant Name: AP1) Tj "
            "BT 0 0 Td (Line: Asm 1) Tj "
            "BT 0 0 Td (Sub Line: Asm 1 North 1) Tj "
            "BT 0 0 Td (Takt Time: 17.5) Tj",
            "BT 100 40 Td (01-AY1-010) Tj "
            "BT 100 80.84 Td (Base_Variant Electric) Tj "
            "BT 160 120 Td (2.65 s) Tj "
            "BT 100 120 Td (Tape manifest to bottom pack) Tj",
        )

        result = parse_yamazumi_pdf(pdf)

        self.assertEqual(len(result["dataframe"]), 1)
        row = result["dataframe"].iloc[0]
        self.assertEqual(row["Pitch_number"], "01-AY1-010")
        self.assertEqual(row["Work_Description"], "Tape manifest to bottom pack")
        self.assertEqual(row["Work_Time_to_complete"], 2.65)

    def test_assigns_right_aligned_time_to_its_description_pitch(self):
        pdf = self._minimal_pdf(
            "BT 0 0 Td (Plant Name: AP1) Tj "
            "BT 0 0 Td (Line: Asm 1) Tj "
            "BT 0 0 Td (Sub Line: Asm 1 North 1) Tj "
            "BT 0 0 Td (Takt Time: 17.5) Tj",
            "BT 60.94 52.12 Td (01-AY1-010) Tj "
            "BT 55.44 30.86 Td (Bottom Pack) Tj "
            "BT 30.46 80.84 Td (Base_Variant Electric) Tj "
            "BT 17.01 169.01 Td (Look at screen pick the) Tj "
            "BT 163.73 169.01 Td (3.5s) Tj "
            "BT 17.01 152.00 Td (correct manifest) Tj "
            "BT 259.37 52.12 Td (01-AY1-012) Tj "
            "BT 274.62 30.86 Td (Sensor) Tj "
            "BT 228.88 80.84 Td (Base_Variant Electric) Tj",
        )

        result = parse_yamazumi_pdf(pdf)

        self.assertEqual(len(result["dataframe"]), 1)
        row = result["dataframe"].iloc[0]
        self.assertEqual(row["Pitch_number"], "01-AY1-010")
        self.assertEqual(
            row["Work_Description"], "Look at screen pick the correct manifest"
        )
        self.assertNotIn("01-AY1-012", result["dataframe"]["Pitch_number"].tolist())

    def test_import_preserves_detected_pitch_without_fabricating_work(self):
        pdf = self._minimal_pdf(
            "BT 0 0 Td (Plant Name: AP1) Tj "
            "BT 0 0 Td (Line: Asm 1) Tj "
            "BT 0 0 Td (Sub Line: Asm 1 North 1) Tj "
            "BT 0 0 Td (Takt Time: 17.5) Tj",
            "BT 100 40 Td (01-AY1-012) Tj "
            "BT 100 80.84 Td (Base_Variant Electric) Tj "
            "BT 100 120 Td (3.5 s) Tj",
        )
        result = parse_yamazumi_pdf(pdf)
        project_id = f"empty-pitch-project-{uuid4()}"
        scenario_id = f"empty-pitch-scenario-{uuid4()}"
        section_id = f"empty-pitch-section-{uuid4()}"
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, revision, status, takt_time_s, created_at, updated_at)
                   VALUES (?, 'Empty pitch project', 'A', 'Draft', 17.5, ?, ?)""",
                (project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence,
                    status, takt_time_s, created_at, updated_at)
                   VALUES (?, ?, 'Baseline', '1', 1, 'Working', 17.5, ?, ?)""",
                (scenario_id, project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO assembly_sections
                   (id, project_id, name, sequence, active, created_at, updated_at)
                   VALUES (?, ?, 'Asm 1 North 1', 10, 1, ?, ?)""",
                (section_id, project_id, timestamp, timestamp),
            )

        counts = import_yamazumi_rows(
            project_id,
            scenario_id,
            result["dataframe"],
            {"Asm 1 North 1": section_id},
            source_label="PDF import",
            pitch_rows=result["pitch_dataframe"],
        )

        self.assertEqual(counts, (1, 1, 0))
        pitches = store.query(
            """SELECT pitch_number, model_variants
               FROM yamazumi_pitches WHERE project_id=?""",
            (project_id,),
        )
        self.assertEqual(pitches[0]["pitch_number"], "01-AY1-012")
        self.assertEqual(pitches[0]["model_variants"], '["Base_Variant Electric"]')
        self.assertEqual(
            store.query(
                "SELECT COUNT(*) AS count FROM yamazumi_elements WHERE project_id=?",
                (project_id,),
            )[0]["count"],
            0,
        )

    def test_parse_invalid_pdf(self):
        with self.assertRaises(ValueError):
            parse_yamazumi_pdf(b"not a valid pdf content")

    def test_parse_real_yamazumi_pdf(self):
        if not os.path.exists(self.SAMPLE_PDF_PATH):
            self.skipTest(f"Sample PDF not found at {self.SAMPLE_PDF_PATH}")

        result = parse_yamazumi_pdf(self.SAMPLE_PDF_PATH)
        self.assertIn("metadata", result)
        self.assertIn("dataframe", result)
        self.assertIn("pitches", result)

        meta = result["metadata"]
        self.assertEqual(meta["plant"], "AP1")
        self.assertEqual(meta["line"], "Pedestal and Riser")
        self.assertEqual(meta["subline"], "Pedestal")
        self.assertEqual(meta["takt_time"], 39.3)

        df = result["dataframe"]
        self.assertFalse(df.empty)
        self.assertEqual(len(df), 63)

        # Check required columns
        expected_cols = {
            "Sub-Line", "Pitch_number", "Pitch_status", "Pitch_name",
            "Pitch_Takt_time", "Model_variant", "Work_Type",
            "Work_Description", "Work_Time_to_complete", "Work_region",
        }
        self.assertTrue(expected_cols.issubset(set(df.columns)))

        # Check pitches
        unique_pitches = df["Pitch_number"].unique().tolist()
        self.assertIn("01-PED-003", unique_pitches)
        self.assertIn("01-PED-007", unique_pitches)
        self.assertIn("01-PED-011", unique_pitches)
        self.assertIn("01-PED-036", unique_pitches)
        self.assertEqual(len(unique_pitches), 11)

        # Check pitch friendly name for 01-PED-036
        ped36 = df[df["Pitch_number"] == "01-PED-036"]
        self.assertEqual(ped36["Pitch_name"].iloc[0], "Manual Box Erector")

        # Check regions
        regions = set(df["Work_region"].unique())
        self.assertIn("New Part", regions)
        self.assertIn("North/West", regions)
        self.assertIn("None", regions)

    def test_parse_real_yamazumi_pdf_detects_work_types_from_fill_colors(self):
        if not os.path.exists(self.COLOR_SAMPLE_PDF_PATH):
            self.skipTest(
                f"Color sample PDF not found at {self.COLOR_SAMPLE_PDF_PATH}"
            )

        result = parse_yamazumi_pdf(self.COLOR_SAMPLE_PDF_PATH)

        self.assertEqual(
            result["dataframe"]["Work_Type"].value_counts().to_dict(),
            {"Cycle": 46, "Fluctuation": 10, "Periodic": 9},
        )

    def test_import_yamazumi_rows_pdf_and_replace(self):
        if not os.path.exists(self.SAMPLE_PDF_PATH):
            self.skipTest(f"Sample PDF not found at {self.SAMPLE_PDF_PATH}")

        result = parse_yamazumi_pdf(self.SAMPLE_PDF_PATH)
        df = result["dataframe"]

        project_id = f"test-pdf-proj-{uuid4().hex[:6]}"
        scenario_id = f"test-pdf-scen-{uuid4().hex[:6]}"
        section_id = f"test-pdf-sec-{uuid4().hex[:6]}"
        timestamp = store.now_iso()

        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, revision, status, takt_time_s, created_at, updated_at)
                   VALUES (?, 'Test PDF Project', 'A', 'Draft', 39.3, ?, ?)""",
                (project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence,
                    status, takt_time_s, created_at, updated_at)
                   VALUES (?, ?, 'Baseline', '1', 1, 'Working', 39.3, ?, ?)""",
                (scenario_id, project_id, timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO assembly_sections
                   (id, project_id, name, sequence, active, created_at, updated_at)
                   VALUES (?, ?, 'Pedestal', 10, 1, ?, ?)""",
                (section_id, project_id, timestamp, timestamp),
            )

        section_map = {"Pedestal": section_id}

        # 1. First import without replacement
        area_count, pitch_count, element_count = import_yamazumi_rows(
            project_id,
            scenario_id,
            df,
            section_map,
            replace_existing_elements=False,
            source_label="PDF import",
        )
        self.assertEqual(area_count, 1)
        self.assertEqual(pitch_count, 11)
        self.assertEqual(element_count, 63)

        elems = yamazumi_elements_for_scenario(project_id, scenario_id)
        self.assertEqual(len(elems), 63)
        self.assertTrue((elems["source"] == "PDF import").all())

        # 2. Second import WITH replace_existing_elements=True
        # Should clear the previous 63 elements and re-import 63 (not 126!)
        area_count2, pitch_count2, element_count2 = import_yamazumi_rows(
            project_id,
            scenario_id,
            df,
            section_map,
            replace_existing_elements=True,
            source_label="PDF import",
        )
        self.assertEqual(element_count2, 63)

        elems2 = yamazumi_elements_for_scenario(project_id, scenario_id)
        self.assertEqual(len(elems2), 63)
        self.assertTrue((elems2["source"] == "PDF import").all())


if __name__ == "__main__":
    unittest.main()
