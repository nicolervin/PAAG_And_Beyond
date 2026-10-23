from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4
import zlib

import openpyxl
import pandas as pd
from PIL import Image, ImageDraw

from utils import (
    cache_store,
    control_plan_store,
    db_core,
    equipment_store,
    excel_io,
    layout_store,
    media_cache,
    pfmea_store,
    project_transfer,
    quality_store,
    store,
    traceability_store,
    yamazumi_pdf,
)


class _UploadedWorkbookStub:
    """In-memory file-like object matching Streamlit UploadedFile for Excel parsers."""

    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data
        self.size = len(data)

    def getvalue(self) -> bytes:
        return self._data


def _build_massive_pits_workbook_bytes(
    *,
    num_piece_parts: int = 1150,
    num_assemblies: int = 50,
    num_models: int = 24,
    num_subsystems: int = 12,
) -> bytes:
    """Create a realistic, large multi-sheet PITS workbook (Part Tracker, Models, BOM)."""
    subsystems = [f"Subsystem_{i:02d}" for i in range(1, num_subsystems + 1)]
    model_numbers = [f"MOD-{100 + m:03d}" for m in range(1, num_models + 1)]

    # 1. Part Tracker sheet (65 columns wide so column F, G, I..N, T, BL are exercised)
    tracker_headers = [f"Col_{idx}" for idx in range(65)]
    tracker_headers[0] = "ID Number"
    tracker_headers[1] = "Part Number"
    tracker_headers[2] = "Description"
    tracker_headers[3] = "Used BOM"
    tracker_headers[4] = "Base Info Status"
    tracker_headers[5] = "Subsystem"          # Col F
    tracker_headers[6] = "Design Maturity"    # Col G
    tracker_headers[8] = "Design Engineer"    # Col I
    tracker_headers[9] = "PPM"                # Col J
    tracker_headers[10] = "Buyer / GCL"       # Col K
    tracker_headers[11] = "PMQE / AQE"        # Col L
    tracker_headers[12] = "AME Tooling Engineer"  # Col M
    tracker_headers[13] = "Part Code"         # Col N
    tracker_headers[19] = "Source Code"       # Col T
    tracker_headers[20] = "Comments"
    tracker_headers[21] = "Factory Workstation Location"
    tracker_headers[63] = "Revision"          # Col BL

    tracker_rows: list[list[object]] = [tracker_headers]
    bom_rows: list[list[object]] = []

    # BOM sheet has 2 metadata rows above the header row so model columns (col 14+) are detected
    num_bom_cols = 14 + num_models
    bom_meta_row_0 = ["" for _ in range(num_bom_cols)]
    bom_meta_row_1 = ["" for _ in range(num_bom_cols)]
    for m_idx, m_num in enumerate(model_numbers):
        bom_meta_row_1[14 + m_idx] = m_num

    bom_header_row = ["" for _ in range(num_bom_cols)]
    bom_header_row[0] = "In Tracker"
    bom_header_row[1] = "Part Number"
    bom_header_row[2] = "Description"
    bom_header_row[3] = "Level 1"
    bom_header_row[4] = "Level 2"
    bom_header_row[5] = "Level 3"
    bom_header_row[6] = "Level 4"
    for m_idx, m_num in enumerate(model_numbers):
        bom_header_row[14 + m_idx] = f"Usage_{m_num}"

    bom_rows.append(bom_meta_row_0)
    bom_rows.append(bom_meta_row_1)
    bom_rows.append(bom_header_row)

    # Add 50 Level-1 and Level-2 G-assemblies first
    for asm_idx in range(1, num_assemblies + 1):
        pits_id = str(asm_idx)
        part_number = f"200G{asm_idx:04d}G001"
        desc = f"Major Subassembly Group {asm_idx:03d}"
        sub = subsystems[(asm_idx - 1) % num_subsystems]
        t_row: list[object] = ["" for _ in range(65)]
        t_row[0] = pits_id
        t_row[1] = part_number
        t_row[2] = desc
        t_row[3] = "Y"
        t_row[4] = "Active"
        t_row[5] = sub
        t_row[6] = "P2"
        t_row[8] = f"Eng_{(asm_idx % 8) + 1}"
        t_row[9] = f"PPM_{(asm_idx % 4) + 1}"
        t_row[10] = f"Buyer_{(asm_idx % 5) + 1}"
        t_row[11] = f"AQE_{(asm_idx % 4) + 1}"
        t_row[12] = f"AME_{(asm_idx % 4) + 1}"
        t_row[13] = f"PC-{asm_idx % 20:02d}"
        t_row[19] = "2 Make"
        t_row[20] = f"Assembly tracker note {asm_idx}"
        t_row[21] = f"Area_{(asm_idx % 10) + 1}"
        t_row[63] = "A"
        tracker_rows.append(t_row)

        # Place assembly in BOM at Level 1 (or Level 2 under previous Level 1)
        b_row: list[object] = ["" for _ in range(num_bom_cols)]
        b_row[0] = pits_id
        b_row[1] = part_number
        b_row[2] = desc
        if asm_idx % 2 == 1:
            b_row[3] = "1"  # Level 1 root
        else:
            b_row[4] = "1"  # Level 2 child under preceding Level 1 root
        for m_idx in range(num_models):
            b_row[14 + m_idx] = 1
        bom_rows.append(b_row)

        # Add piece parts under this assembly
        pieces_per_asm = num_piece_parts // num_assemblies
        start_piece = (asm_idx - 1) * pieces_per_asm + 1
        end_piece = (
            num_piece_parts
            if asm_idx == num_assemblies
            else asm_idx * pieces_per_asm
        )
        for p_idx in range(start_piece, end_piece + 1):
            p_pits_id = str(num_assemblies + p_idx)
            p_number = f"100D{1000 + p_idx:04d}P001"
            p_sub_idx = (p_idx - 1) % num_subsystems
            p_sub = subsystems[p_sub_idx]
            p_desc = f"Precision Component {p_idx:04d} ({p_sub})"

            pt_row: list[object] = ["" for _ in range(65)]
            pt_row[0] = p_pits_id
            pt_row[1] = p_number
            pt_row[2] = p_desc
            pt_row[3] = "Y"
            pt_row[4] = "Released"
            pt_row[5] = p_sub
            pt_row[6] = "P3"
            pt_row[8] = f"Eng_{(p_idx % 12) + 1}"
            pt_row[9] = f"PPM_{(p_idx % 6) + 1}"
            pt_row[10] = f"Buyer_{(p_idx % 6) + 1}"
            pt_row[11] = f"AQE_{(p_idx % 6) + 1}"
            pt_row[12] = f"AME_{(p_idx % 6) + 1}"
            pt_row[13] = f"PC-{p_idx % 30:02d}"
            pt_row[19] = "1 Buy"
            pt_row[20] = f"Piece part note {p_idx}"
            pt_row[21] = f"Station_{(p_idx % 20) + 1}"
            pt_row[63] = "B"
            tracker_rows.append(pt_row)

            # BOM row at Level 3 (under Level 2 or Level 1)
            pb_row: list[object] = ["" for _ in range(num_bom_cols)]
            pb_row[0] = p_pits_id
            pb_row[1] = p_number
            pb_row[2] = p_desc
            depth_col = 5 if (asm_idx % 2 == 0) else 4  # Level 3 if parent is Level 2, else Level 2
            pb_row[depth_col] = "2"

            # Assign deterministic model usage by subsystem choice so feature inference is exercised:
            # Models are partitioned into 3 choices (Choice_A, Choice_B, Choice_C) per subsystem,
            # or all models for common parts.
            choice_bucket = p_idx % 4  # 0 -> Choice_A, 1 -> Choice_B, 2 -> Choice_C, 3 -> All models
            for m_idx in range(num_models):
                model_choice_for_sub = (m_idx + p_sub_idx) % 3
                if choice_bucket == 3 or model_choice_for_sub == choice_bucket:
                    pb_row[14 + m_idx] = 2.0
            bom_rows.append(pb_row)

    # 2. Models sheet
    model_headers = [
        "Model Number",
        "Item",
        "Platform Size",
        "Package Type",
        "Appearance",
        "Base Model",
        "EAU",
        "DG Date",
        "DC Date",
        "Pre-Pilot Date",
        "Pilot Date",
        "Production Date",
        "SKU / UPC",
        "Evaluate in Fishbone",
        "Yamazumi",
        "BOP L1",
    ]
    model_rows: list[list[object]] = [model_headers]
    for m_idx, m_num in enumerate(model_numbers):
        model_rows.append([
            m_num,
            f"Item-{m_idx + 1:02d}",
            "Large" if m_idx % 2 == 0 else "Medium",
            "Premium" if m_idx % 3 == 0 else "Standard",
            "Stainless" if m_idx % 2 == 0 else "Slate",
            model_numbers[0],
            15000 + m_idx * 1000,
            "2026-01-15",
            "2026-03-01",
            "2026-05-01",
            "2026-07-01",
            "2026-09-01",
            f"UPC-{100000 + m_idx}",
            "Yes",
            "Yes",
            f"BOP-{m_idx + 1:02d}",
        ])

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(tracker_rows).to_excel(
            writer, sheet_name="Part Tracker", index=False, header=False
        )
        pd.DataFrame(model_rows).to_excel(
            writer, sheet_name="Models", index=False, header=False
        )
        pd.DataFrame(bom_rows).to_excel(
            writer, sheet_name="BOM", index=False, header=False
        )
    return buf.getvalue()


class MassiveProjectStressTests(unittest.TestCase):
    """End-to-end stress and performance tests with a large multi-sheet Excel workbook and rich assets."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp_dir.name)
        self.db_path = self.tmp_path / "stress_paag.db"
        self.upload_dir = self.tmp_path / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)

        self._orig_store_db = store.DB_PATH
        self._orig_core_db = db_core.DB_PATH
        self._orig_store_upload = store.UPLOAD_DIR
        self._orig_core_upload = db_core.UPLOAD_DIR

        store.DB_PATH = self.db_path
        db_core.DB_PATH = self.db_path
        store.UPLOAD_DIR = self.upload_dir
        db_core.UPLOAD_DIR = self.upload_dir

        cache_store.clear_all_caches()
        store.init_db()

        self.project_id = store.create_project(
            "Massive Stress Test Program",
            "Dish Program",
            "Perf Stress Lead",
            48.0,
            product_line="Dishwashers",
            building_location="AP3",
        )
        scenarios = store.planning_scenarios(self.project_id)
        self.scenario_id = str(scenarios[0]["id"])

    def tearDown(self) -> None:
        cache_store.clear_all_caches()
        store.DB_PATH = self._orig_store_db
        db_core.DB_PATH = self._orig_core_db
        store.UPLOAD_DIR = self._orig_store_upload
        db_core.UPLOAD_DIR = self._orig_core_upload
        self._tmp_dir.cleanup()

    def test_massive_pits_excel_workbook_import_and_feature_inference(self) -> None:
        """Stress-test parsing a 1,200-part / 24-model / 1,200-BOM-row Excel file and inferring feature rules."""
        num_piece_parts = 1150
        num_assemblies = 50
        total_parts = num_piece_parts + num_assemblies
        num_models = 24
        num_subsystems = 12

        wb_bytes = _build_massive_pits_workbook_bytes(
            num_piece_parts=num_piece_parts,
            num_assemblies=num_assemblies,
            num_models=num_models,
            num_subsystems=num_subsystems,
        )
        self.assertGreater(len(wb_bytes), 100_000)
        uploaded = _UploadedWorkbookStub("Massive_PITS_Master.xlsx", wb_bytes)

        # 1. Cold vs. Warm parse_pits_combined_workbook
        t0 = time.perf_counter()
        records, models, bom_snapshot = excel_io.parse_pits_combined_workbook(uploaded)
        cold_parse_s = time.perf_counter() - t0

        self.assertEqual(len(records), total_parts)
        self.assertEqual(len(models), num_models)
        self.assertEqual(len(bom_snapshot["occurrences"]), total_parts)

        t1 = time.perf_counter()
        records_warm, models_warm, bom_warm = excel_io.parse_pits_combined_workbook(uploaded)
        warm_parse_s = time.perf_counter() - t1

        self.assertEqual(len(records_warm), total_parts)
        self.assertEqual(len(models_warm), num_models)
        self.assertEqual(len(bom_warm["occurrences"]), total_parts)
        self.assertLess(warm_parse_s, 0.050, "Upload-scoped cached parse should be < 50ms")
        self.assertLess(warm_parse_s, cold_parse_s * 0.10)

        # 2. Import the massive snapshot into SQLite
        wb_sha = hashlib.sha256(wb_bytes).hexdigest()
        t_imp0 = time.perf_counter()
        summary = store.import_pits_id_snapshot(
            self.project_id,
            records,
            models,
            scenario_id=self.scenario_id,
            overwrite_manual=True,
            bom_snapshot=bom_snapshot,
            workbook_name=uploaded.name,
            workbook_sha256=wb_sha,
            editor_name="Stress Tester",
        )
        import_s = time.perf_counter() - t_imp0
        self.assertEqual(summary["new"], total_parts)
        self.assertEqual(summary["models"], num_models)
        self.assertLess(import_s, 15.0, "Importing 1,200 parts + 1,200 BOM rows should finish quickly")

        # 3. Verify project_part_subsystems cache & results
        subsystems = store.project_part_subsystems(self.project_id)
        self.assertEqual(len(subsystems), num_subsystems)
        self.assertEqual(subsystems[0], "Subsystem_01")

        # 4. Configure 12 Complexity Features (each scoped to one Subsystem_01..12)
        feature_rows = []
        for s_idx in range(num_subsystems):
            sub_name = f"Subsystem_{s_idx + 1:02d}"
            feature_rows.append({
                "id": "",
                "category": "Subsystem Architecture",
                "subsystem": sub_name,
                "name": f"Feature_{sub_name}",
                "allowed_choices": "Choice_A, Choice_B, Choice_C",
                "description": f"Variant selector for {sub_name}",
                "active": True,
            })
        saved_features = store.update_complexity_features(
            self.project_id, pd.DataFrame(feature_rows)
        )
        self.assertEqual(saved_features, num_subsystems)

        features_df = store.complexity_features(self.project_id)
        feature_id_by_sub = {
            str(r["subsystem"]): str(r["id"])
            for r in features_df.to_dict(orient="records")
        }

        # Populate the 24-model x 12-feature Complexity Tree matching the BOM usage pattern
        models_df = store.project_models(self.project_id)
        model_id_by_num = {
            str(r["model_number"]): str(r["id"])
            for r in models_df.to_dict(orient="records")
        }
        tree_rows = []
        choice_labels = ["Choice_A", "Choice_B", "Choice_C"]
        for m_idx in range(num_models):
            m_num = f"MOD-{100 + m_idx + 1:03d}"
            m_id = model_id_by_num[m_num]
            row_dict: dict[str, object] = {"model_id": m_id}
            for s_idx in range(num_subsystems):
                sub_name = f"Subsystem_{s_idx + 1:02d}"
                f_id = feature_id_by_sub[sub_name]
                row_dict[f_id] = choice_labels[(m_idx + s_idx) % 3]
            tree_rows.append(row_dict)

        store.update_complexity_tree(self.project_id, pd.DataFrame(tree_rows))

        # 5. Benchmark infer_part_feature_rules & apply_inferred_part_feature_rules across 1,200 parts
        t_inf0 = time.perf_counter()
        preview = store.preview_inferred_part_feature_rules(
            self.project_id, overwrite_existing=True
        )
        infer_preview_s = time.perf_counter() - t_inf0

        self.assertLess(
            infer_preview_s,
            2.5,
            f"Feature rule inference across {total_parts} parts took {infer_preview_s:.2f}s (expected < 2.5s)",
        )
        # All 25 Level-1 top-level G-assemblies are skipped automatically by infer_part_feature_rules,
        # while the 25 Level-2 subassemblies ('All models') + 1,150 piece parts = 1,175 parts are inferred
        expected_inferred = num_piece_parts + (num_assemblies // 2)
        self.assertEqual(total_parts - preview["total_inferred"], num_assemblies // 2)
        self.assertEqual(preview["total_inferred"], expected_inferred)
        # Because each feature is scoped to its subsystem, every inferred part maps unambiguously to 1 rule!
        self.assertEqual(len(preview["direct"]), expected_inferred)
        self.assertEqual(len(preview["review"]), 0)

        t_app0 = time.perf_counter()
        applied_count = store.apply_inferred_part_feature_rules(
            self.project_id, overwrite_existing=True, editor_name="Stress Tester"
        )
        apply_s = time.perf_counter() - t_app0
        self.assertEqual(applied_count, expected_inferred)
        self.assertLess(apply_s, 3.0)

        # 6. Benchmark pits_bom_model_tree cold vs. warm cache
        t_tree0 = time.perf_counter()
        full_tree = store.pits_bom_model_tree(self.project_id, "all")
        cold_tree_s = time.perf_counter() - t_tree0
        self.assertEqual(full_tree["metrics"]["total"], total_parts)

        t_tree1 = time.perf_counter()
        full_tree_warm = store.pits_bom_model_tree(self.project_id, "all")
        warm_tree_s = time.perf_counter() - t_tree1
        self.assertEqual(full_tree_warm["metrics"]["total"], total_parts)
        self.assertLess(warm_tree_s, 0.025)
        self.assertLess(warm_tree_s, cold_tree_s * 0.25)

    def test_massive_planning_assets_media_cache_and_workbook_export(self) -> None:
        """Stress-test 20 Fishbone sections, 1,000 assignments, 1,200 Yamazumi elements, 400 Process steps, 40 HD images, and full Excel export."""
        # 1. Generate 40 high-resolution synthetic PNG images (1600x1200) on disk
        image_rel_paths: list[str] = []
        raw_image_bytes_total = 0
        for img_idx in range(40):
            img = Image.new(
                "RGB",
                (1600, 1200),
                color=((img_idx * 37) % 255, (img_idx * 73) % 255, (img_idx * 113) % 255),
            )
            draw = ImageDraw.Draw(img)
            for step in range(0, 1600, 80):
                draw.line([(step, 0), (1600 - step, 1200)], fill=(255, 255, 255), width=3)
            draw.rectangle([100, 100, 1500, 1100], outline=(240, 220, 80), width=6)
            fname = f"stress_asset_{img_idx:03d}.png"
            fpath = self.upload_dir / fname
            img.save(fpath, format="PNG")
            raw_image_bytes_total += fpath.stat().st_size
            image_rel_paths.append(str(fpath))

        self.assertGreater(raw_image_bytes_total, 1_500_000)

        # 2. Bulk-populate 1,000 parts, 20 Fishbone sections, 1,000 Fishbone assignments,
        #    10 Yamazumi areas, 100 pitches, 1,200 Yamazumi elements, 400 Process work elements,
        #    and 100 Quality requirements / assignments / PFMEA rows in one atomic transaction.
        now = store.now_iso()
        part_ids: list[str] = []
        section_ids: list[str] = []
        area_ids: list[str] = []
        pitch_ids: list[str] = []
        work_element_ids: list[str] = []

        with store.connection() as conn:
            # 1,000 Parts
            part_tuples = []
            activity_tuples = []
            for idx in range(1, 1001):
                pid = str(uuid4())
                part_ids.append(pid)
                pnum = f"300D{idx:04d}P001"
                img_path = image_rel_paths[idx % len(image_rel_paths)] if idx <= 200 else ""
                part_tuples.append((
                    pid,
                    self.project_id,
                    pnum,
                    f"Stress Catalog Part {idx:04d}",
                    float((idx % 4) + 1),
                    "A",
                    "P3",
                    f"Subsystem_{(idx % 10) + 1:02d}",
                    "Manual",
                    img_path,
                    "All",
                    f"Note for part {idx}",
                    "Lead Eng",
                    "Lead Eng",
                    str(idx),
                    "1",
                    f"Windchill_{idx:04d}",
                    f"Nickname_{idx:04d}",
                    "Buy" if idx % 3 else "Make",
                    "PPM_1",
                    "Buyer_1",
                    "AQE_1",
                    "AME_1",
                    f"PC-{idx % 15:02d}",
                    now,
                ))
                activity_tuples.append((self.project_id, self.scenario_id, pid, 1, now))

            conn.executemany(
                """INSERT INTO parts (
                       id, project_id, part_number, description, quantity, revision,
                       design_maturity, subsystem, source, image_path, model_applicability, notes,
                       technology_engineer, design_engineer, pits_tracker_number, source_code,
                       official_windchill_part_name, factory_nickname, make_buy, ppm, buyer_gcl,
                       pmqe_aqe, ame_tooling_engineer, part_code, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                part_tuples,
            )
            conn.executemany(
                """INSERT INTO part_scenario_activity (project_id, scenario_id, part_id, active, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                activity_tuples,
            )

            # 20 Fishbone Assembly Sections
            sec_tuples = []
            for s_idx in range(1, 21):
                sid = str(uuid4())
                section_ids.append(sid)
                sec_type = "Assembly"
                parent_id = None if s_idx <= 10 else section_ids[s_idx - 11]
                sec_tuples.append((
                    sid,
                    self.project_id,
                    f"Section {s_idx:02d} -Zone",
                    sec_type,
                    parent_id,
                    s_idx * 10,
                    f"Assembly zone {s_idx}",
                    1,
                    s_idx,
                    0 if s_idx <= 10 else 1,
                    now,
                    now,
                ))
            conn.executemany(
                """INSERT INTO assembly_sections (
                       id, project_id, name, section_type, parent_id, sequence,
                       description, active, grid_x, grid_y, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                sec_tuples,
            )

            # 1,000 Fishbone Part Assignments
            fpa_tuples = []
            for idx, pid in enumerate(part_ids, start=1):
                sid = section_ids[(idx - 1) % len(section_ids)]
                fpa_tuples.append((
                    str(uuid4()),
                    self.project_id,
                    pid,
                    sid,
                    1,
                    idx * 10,
                    float((idx % 3) + 1),
                    f"Install component {idx} into section",
                    "",
                    "In sync",
                    now,
                ))
            conn.executemany(
                """INSERT INTO fishbone_part_assignments (
                       id, project_id, part_id, section_id, step_number, sequence,
                       quantity, use_description, notes, pits_sync_status, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                fpa_tuples,
            )

            # 10 Yamazumi Areas & 100 Yamazumi Pitches
            area_tuples = []
            pitch_tuples = []
            for a_idx in range(10):
                aid = str(uuid4())
                area_ids.append(aid)
                sid = section_ids[a_idx]
                area_tuples.append((
                    aid,
                    self.project_id,
                    self.scenario_id,
                    sid,
                    f"Area {a_idx + 1:02d}",
                    None,
                    now,
                ))
                for p_idx in range(1, 11):
                    pitch_id = str(uuid4())
                    pitch_ids.append(pitch_id)
                    pitch_num = f"P{a_idx * 10 + p_idx:03d}"
                    pitch_tuples.append((
                        pitch_id,
                        self.project_id,
                        aid,
                        pitch_num,
                        f"Pitch {pitch_num}",
                        "Active",
                        p_idx * 10,
                        '["Base"]',
                        "Pitch",
                        None,
                        now,
                    ))
            conn.executemany(
                """INSERT INTO yamazumi_areas (
                       id, project_id, scenario_id, section_id, name, takt_override_s, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                area_tuples,
            )
            conn.executemany(
                """INSERT INTO yamazumi_pitches (
                       id, project_id, area_id, pitch_number, pitch_name, status,
                       sequence, model_variants, pitch_type, feeds_into_pitch_id, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                pitch_tuples,
            )

            # 400 Process at a Glance Work Elements
            we_tuples = []
            for w_idx in range(1, 401):
                we_id = str(uuid4())
                work_element_ids.append(we_id)
                pitch_idx = (w_idx - 1) % len(pitch_ids)
                station_num = f"P{pitch_idx + 1:03d}"
                pnum = f"300D{w_idx:04d}P001"
                we_tuples.append((
                    we_id,
                    self.project_id,
                    self.scenario_id,
                    w_idx * 10,
                    station_num,
                    f"OP-{w_idx:03d}",
                    f"Secure assembly step {w_idx:03d}",
                    11.5 + (w_idx % 7),
                    pnum,
                    "DC Nutrunner" if w_idx % 2 == 0 else "Fixture Check",
                    "4.5 Nm +/- 0.5" if w_idx % 2 == 0 else "",
                    "Verify flush seating" if w_idx % 3 == 0 else "",
                    "Neutral posture" if w_idx % 4 == 0 else "",
                    "Front",
                    "0 deg",
                    34.0,
                    0.0,
                    0.0,
                    "All",
                    "Reviewed",
                    "Human",
                    "",
                    "",
                    "",
                    now,
                ))
            conn.executemany(
                """INSERT INTO work_elements (
                       id, project_id, scenario_id, sequence, station, operation, description,
                       cycle_time_s, part_number, tool, torque, quality_requirement, ergo_requirement,
                       location, unit_orientation, conveyor_height_in, platform_height_in, pit_depth_in,
                       model_applicability, status, resource_type, resource_detail,
                       output_assembly_number, output_assembly_name, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                we_tuples,
            )

            # 1,200 Yamazumi Work Elements
            ye_tuples = []
            for y_idx in range(1, 1201):
                pitch_idx = (y_idx - 1) % len(pitch_ids)
                aid = area_ids[pitch_idx // 10]
                pitch_id = pitch_ids[pitch_idx]
                linked_we_id = work_element_ids[y_idx - 1] if y_idx <= 400 else ""
                ye_tuples.append((
                    str(uuid4()),
                    self.project_id,
                    aid,
                    pitch_id,
                    "Base",
                    '["Base"]',
                    "Cycle" if y_idx % 3 != 0 else "Walk",
                    f"Yamazumi work element {y_idx:04d}",
                    8.5 + (y_idx % 5),
                    "None",
                    y_idx * 10,
                    "Manual",
                    linked_we_id,
                    "In sync" if linked_we_id else "Needs IE review",
                    now,
                ))
            conn.executemany(
                """INSERT INTO yamazumi_elements (
                       id, project_id, area_id, pitch_id, model_variant, model_variants,
                       work_type, description, time_s, work_region, sequence, source,
                       process_element_id, process_sync_status, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ye_tuples,
            )

        # 3. Benchmark cold vs. warm @cached_store_read across heavy store queries
        cold_queries_start = time.perf_counter()
        parts_cold = store.project_table("parts", self.project_id, "part_number")
        fpa_cold = store.fishbone_part_assignments(self.project_id, self.scenario_id)
        ye_cold = store.yamazumi_elements_for_scenario(self.project_id, self.scenario_id)
        we_cold = store.project_table("work_elements", self.project_id, "sequence", scenario_id=self.scenario_id)
        pin_cold = store.pin_map_for_scenario(self.project_id, self.scenario_id)
        cold_queries_s = time.perf_counter() - cold_queries_start

        self.assertEqual(len(parts_cold), 1000)
        self.assertEqual(len(fpa_cold), 1000)
        self.assertEqual(len(ye_cold), 1200)
        self.assertEqual(len(we_cold), 400)
        self.assertEqual(len(pin_cold), 400)

        warm_queries_start = time.perf_counter()
        parts_warm = store.project_table("parts", self.project_id, "part_number")
        fpa_warm = store.fishbone_part_assignments(self.project_id, self.scenario_id)
        ye_warm = store.yamazumi_elements_for_scenario(self.project_id, self.scenario_id)
        we_warm = store.project_table("work_elements", self.project_id, "sequence", scenario_id=self.scenario_id)
        pin_warm = store.pin_map_for_scenario(self.project_id, self.scenario_id)
        warm_queries_s = time.perf_counter() - warm_queries_start

        self.assertEqual(len(parts_warm), 1000)
        self.assertEqual(len(fpa_warm), 1000)
        self.assertEqual(len(ye_warm), 1200)
        self.assertEqual(len(we_warm), 400)
        self.assertEqual(len(pin_warm), 400)
        self.assertLess(
            warm_queries_s,
            cold_queries_s * 0.35,
            f"Warm cached reads ({warm_queries_s:.4f}s) should be much faster than cold DB queries ({cold_queries_s:.4f}s)",
        )

        # Mutating a returned DataFrame must never corrupt the cache
        parts_warm.iloc[0, parts_warm.columns.get_loc("description")] = "MUTATED_IN_MEMORY"
        parts_recheck = store.project_table("parts", self.project_id, "part_number")
        self.assertNotEqual(parts_recheck.iloc[0]["description"], "MUTATED_IN_MEMORY")

        # 4. Stress-test media_cache.cached_image_bytes across all 40 high-resolution PNGs
        t_img_cold0 = time.perf_counter()
        thumb_bytes_total = 0
        for rel_path in image_rel_paths:
            data = media_cache.cached_image_bytes(rel_path, max_dim=320, output_format="WEBP", quality=80)
            self.assertIsNotNone(data)
            thumb_bytes_total += len(data)
        cold_img_s = time.perf_counter() - t_img_cold0

        # Thumbnail optimization should reduce total payload size by > 65%
        self.assertLess(thumb_bytes_total, raw_image_bytes_total * 0.35)

        t_img_warm0 = time.perf_counter()
        for rel_path in image_rel_paths:
            data = media_cache.cached_image_bytes(rel_path, max_dim=320, output_format="WEBP", quality=80)
            self.assertIsNotNone(data)
        warm_img_s = time.perf_counter() - t_img_warm0

        self.assertLess(warm_img_s, 0.050, "40 warm thumbnail lookups should take < 50ms total")
        self.assertLess(warm_img_s, cold_img_s * 0.10)

        # 5. Stress-test full multi-sheet Excel export on the massive project
        t_exp0 = time.perf_counter()
        exported_bytes = excel_io.export_workbook(self.project_id, self.scenario_id)
        export_s = time.perf_counter() - t_exp0

        self.assertGreater(len(exported_bytes), 50_000)
        self.assertLess(export_s, 10.0, f"Full workbook export took {export_s:.2f}s (expected < 10s)")

        wb = openpyxl.load_workbook(BytesIO(exported_bytes), read_only=True)
        try:
            expected_sheets = {
                "Project",
                "Planning Scenario",
                "Parts",
                "Work Elements",
                "Fishbone Sections",
                "Fishbone Parts",
                "Lucid Data Link",
            }
            self.assertTrue(expected_sheets.issubset(set(wb.sheetnames)))
            self.assertEqual(wb["Parts"].max_row, 1001)          # header + 1,000 parts
            self.assertEqual(wb["Work Elements"].max_row, 401)   # header + 400 elements
            self.assertEqual(wb["Fishbone Sections"].max_row, 21)
            self.assertEqual(wb["Fishbone Parts"].max_row, 1001)
        finally:
            wb.close()

    def test_massive_functional_reviews_scenario_cloning_and_project_transfer(self) -> None:
        """Stress-test Yamazumi PDF parsing, all Functional Reviews (Safety, Ergo, Equipment, Quality/Torque, PFMEA, Control Plan, Traceability, 2D Layouts), Scenario Cloning, and .paagproject Transfer."""
        # 1. Stress-test Yamazumi PDF vector stream parser across a 10-page / 40-pitch / 200-element PDF
        pdf_streams: list[bytes] = []
        p1_commands = [
            "BT /F1 12 Tf 40.0 750.0 Td (Plant Name: AP3) Tj ET",
            "BT /F1 12 Tf 40.0 730.0 Td (Line: Dish Final Assembly) Tj ET",
            "BT /F1 12 Tf 40.0 710.0 Td (Sub Line: Main Line) Tj ET",
            "BT /F1 12 Tf 40.0 690.0 Td (Takt Time: 48.0) Tj ET",
            "0.20 0.60 0.80 rg 40.0 200.0 20.0 15.0 re f",
            "BT /F1 10 Tf 70.0 202.0 Td (Front Zone) Tj ET",
        ]
        pdf_streams.append(zlib.compress("\n".join(p1_commands).encode("latin1")))

        for page_idx in range(1, 11):
            page_cmds: list[str] = []
            for p_col in range(4):
                pitch_seq = (page_idx - 1) * 4 + p_col + 1
                base_x = 60.0 + p_col * 300.0
                p_code = f"01-AY1-{pitch_seq:03d}"
                p_name = f"Station {pitch_seq:03d}"
                page_cmds.append(f"BT /F1 11 Tf {base_x:.1f} 60.0 Td ({p_code}) Tj ET")
                page_cmds.append(f"BT /F1 10 Tf {base_x:.1f} 35.0 Td ({p_name}) Tj ET")
                page_cmds.append(f"BT /F1 10 Tf {base_x:.1f} 80.84 Td (Base) Tj ET")

                for el_idx in range(5):
                    el_y = 140.0 + el_idx * 45.0
                    el_num = (pitch_seq - 1) * 5 + el_idx + 1
                    # Cycle (green), Periodic (yellow), or Fluctuation (red)
                    if el_num % 7 == 0:
                        page_cmds.append("1.0 0.0 0.0 rg")
                    elif el_num % 5 == 0:
                        page_cmds.append("1.0 1.0 0.0 rg")
                    else:
                        page_cmds.append("0.2 0.7 0.3 rg")
                    desc_x = base_x + 10.0
                    time_x = base_x + 120.0
                    dur_s = 7.5 + (el_num % 4)
                    page_cmds.append(
                        f"BT /F1 9 Tf {desc_x:.1f} {el_y:.1f} Td (Assemble subcomponent {el_num:03d}) Tj ET"
                    )
                    page_cmds.append(
                        f"BT /F1 9 Tf {time_x:.1f} {el_y:.1f} Td ({dur_s:.1f} s) Tj ET"
                    )
            pdf_streams.append(zlib.compress("\n".join(page_cmds).encode("latin1")))

        pdf_chunks = [b"%PDF-1.4\n"]
        for s_idx, raw_comp in enumerate(pdf_streams, start=1):
            pdf_chunks.append(
                f"{s_idx} 0 obj\n<< /Length {len(raw_comp)} >>\nstream\n".encode("latin1")
                + raw_comp
                + b"\nendstream\nendobj\n"
            )
        pdf_chunks.append(b"%%EOF\n")
        pdf_bytes = b"".join(pdf_chunks)

        t_pdf0 = time.perf_counter()
        parsed_pdf = yamazumi_pdf.parse_yamazumi_pdf(pdf_bytes)
        pdf_parse_s = time.perf_counter() - t_pdf0

        self.assertEqual(parsed_pdf["metadata"]["plant"], "AP3")
        self.assertEqual(parsed_pdf["metadata"]["takt_time"], 48.0)
        self.assertEqual(len(parsed_pdf["pitches"]), 40)
        self.assertEqual(len(parsed_pdf["dataframe"]), 200)
        self.assertLess(pdf_parse_s, 1.5, f"Parsing 10-page Yamazumi PDF took {pdf_parse_s:.2f}s")

        # 2. Populate upstream Parts, Fishbone, Yamazumi, Process Work Elements, Part Groups,
        #    and all Functional Review tables (Safety, Ergonomics, Equipment, Quality/Torque, PFMEA, Layouts)
        now = store.now_iso()
        part_ids: list[str] = []
        section_ids: list[str] = []
        area_ids: list[str] = []
        pitch_ids: list[str] = []
        work_element_ids: list[str] = []
        hazard_option_ids: list[str] = []
        ergo_review_ids: list[str] = []

        # Create 4 synthetic images for Layout & Ergonomics visual media
        sample_img_paths: list[str] = []
        for idx in range(4):
            img = Image.new("RGB", (800, 600), color=(40 + idx * 30, 80 + idx * 20, 140))
            p = self.upload_dir / f"functional_asset_{idx}.png"
            img.save(p, format="PNG")
            sample_img_paths.append(str(p))

        with store.connection() as conn:
            equipment_store.init_equipment_schema(conn)
            layout_store.init_layout_schema(conn)

            # 200 Parts
            part_tuples = []
            act_tuples = []
            for idx in range(1, 201):
                pid = str(uuid4())
                part_ids.append(pid)
                part_tuples.append((
                    pid,
                    self.project_id,
                    f"400D{idx:04d}P001",
                    f"Functional Review Component {idx:03d}",
                    2.0,
                    "A",
                    "P3",
                    f"Subsystem_{(idx % 5) + 1:02d}",
                    "Manual",
                    sample_img_paths[idx % len(sample_img_paths)] if idx <= 20 else "",
                    "All",
                    "",
                    "Eng_A",
                    "Eng_A",
                    str(idx),
                    "1",
                    f"WC_{idx:03d}",
                    f"Nick_{idx:03d}",
                    "Buy",
                    "PPM_1",
                    "Buyer_1",
                    "AQE_1",
                    "AME_1",
                    "PC-01",
                    12.5 + (idx % 25),
                    now,
                ))
                act_tuples.append((self.project_id, self.scenario_id, pid, 1, now))
            conn.executemany(
                """INSERT INTO parts (
                       id, project_id, part_number, description, quantity, revision,
                       design_maturity, subsystem, source, image_path, model_applicability, notes,
                       technology_engineer, design_engineer, pits_tracker_number, source_code,
                       official_windchill_part_name, factory_nickname, make_buy, ppm, buyer_gcl,
                       pmqe_aqe, ame_tooling_engineer, part_code, weight_lb, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                part_tuples,
            )
            conn.executemany(
                """INSERT INTO part_scenario_activity (project_id, scenario_id, part_id, active, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                act_tuples,
            )

            # 10 Fishbone Sections & 200 Assignments
            sec_tuples = []
            for s_idx in range(1, 11):
                sid = str(uuid4())
                section_ids.append(sid)
                sec_tuples.append((
                    sid, self.project_id, f"Zone {s_idx:02d}", "Assembly", None,
                    s_idx * 10, f"Zone {s_idx}", 1, s_idx, 0, now, now,
                ))
            conn.executemany(
                """INSERT INTO assembly_sections (
                       id, project_id, name, section_type, parent_id, sequence,
                       description, active, grid_x, grid_y, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                sec_tuples,
            )

            fpa_tuples = [
                (
                    str(uuid4()), self.project_id, pid, section_ids[(idx - 1) % len(section_ids)],
                    1, idx * 10, 1.0, f"Mount part {idx}", "", "In sync", now,
                )
                for idx, pid in enumerate(part_ids, start=1)
            ]
            conn.executemany(
                """INSERT INTO fishbone_part_assignments (
                       id, project_id, part_id, section_id, step_number, sequence,
                       quantity, use_description, notes, pits_sync_status, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                fpa_tuples,
            )

            # 5 Yamazumi Areas & 50 Pitches
            area_tuples = []
            pitch_tuples = []
            for a_idx in range(5):
                aid = str(uuid4())
                area_ids.append(aid)
                area_tuples.append((
                    aid, self.project_id, self.scenario_id, section_ids[a_idx],
                    f"Area {a_idx + 1:02d}", None, now,
                ))
                for p_idx in range(1, 11):
                    pitch_id = str(uuid4())
                    pitch_ids.append(pitch_id)
                    p_num = f"P{a_idx * 10 + p_idx:03d}"
                    pitch_tuples.append((
                        pitch_id, self.project_id, aid, p_num, f"Pitch {p_num}",
                        "Active", p_idx * 10, '["Base"]', "Pitch", None, 4.0, 0.0, now,
                    ))
            conn.executemany(
                """INSERT INTO yamazumi_areas (
                       id, project_id, scenario_id, section_id, name, takt_override_s, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                area_tuples,
            )
            conn.executemany(
                """INSERT INTO yamazumi_pitches (
                       id, project_id, area_id, pitch_number, pitch_name, status,
                       sequence, model_variants, pitch_type, feeds_into_pitch_id,
                       platform_height_in, pit_depth_in, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                pitch_tuples,
            )

            # 200 Work Elements & 200 Linked Yamazumi Elements
            we_tuples = []
            ye_tuples = []
            ppg_tuples = []
            ppo_tuples = []
            wemg_tuples = []
            wemo_tuples = []

            for w_idx in range(1, 201):
                we_id = str(uuid4())
                work_element_ids.append(we_id)
                p_idx = (w_idx - 1) % len(pitch_ids)
                pitch_id = pitch_ids[p_idx]
                aid = area_ids[p_idx // 10]
                st_num = f"P{p_idx + 1:03d}"
                p_num = f"400D{w_idx:04d}P001"
                part_id = part_ids[w_idx - 1]

                we_tuples.append((
                    we_id, self.project_id, self.scenario_id, w_idx * 10, st_num,
                    f"OP-{w_idx:03d}", f"Fasten and verify subassembly {w_idx:03d}",
                    10.5, p_num, "DC Torque Tool", "5.0 Nm", "Check torque", "Neutral wrist",
                    "Front", "0 deg", 34.0, 4.0, 0.0, "All", "Reviewed", "Human", "", now,
                ))
                ye_id = str(uuid4())
                ye_tuples.append((
                    ye_id, self.project_id, aid, pitch_id, "Base", '["Base"]',
                    "Cycle", f"Yamazumi step {w_idx:03d}", 10.5, "Front Zone",
                    w_idx * 10, "Manual", we_id, "In sync", now,
                ))

                if w_idx <= 100:
                    ppg_id = str(uuid4())
                    ppg_tuples.append((
                        ppg_id, self.project_id, self.scenario_id, we_id, section_ids[p_idx // 10],
                        f"Group {w_idx}", "Model match", 1.0, "", now,
                    ))
                    ppo_tuples.append((
                        str(uuid4()), ppg_id, part_id, "Consume", None, now,
                    ))
                    wemg_id = str(uuid4())
                    wemg_tuples.append((
                        wemg_id, self.project_id, self.scenario_id, ye_id, None,
                        f"MatGroup {w_idx}", "Model match", 1.0, "", now,
                    ))
                    wemo_tuples.append((
                        str(uuid4()), wemg_id, part_id, None, now,
                    ))

            conn.executemany(
                """INSERT INTO work_elements (
                       id, project_id, scenario_id, sequence, station, operation, description,
                       cycle_time_s, part_number, tool, torque, quality_requirement, ergo_requirement,
                       location, unit_orientation, conveyor_height_in, platform_height_in, pit_depth_in,
                       model_applicability, status, resource_type, resource_detail, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                we_tuples,
            )
            conn.executemany(
                """INSERT INTO yamazumi_elements (
                       id, project_id, area_id, pitch_id, model_variant, model_variants,
                       work_type, description, time_s, work_region, sequence, source,
                       process_element_id, process_sync_status, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ye_tuples,
            )
            conn.executemany(
                """INSERT INTO process_part_groups (
                       id, project_id, scenario_id, work_element_id, section_id,
                       name, selection_rule, quantity, notes, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ppg_tuples,
            )
            conn.executemany(
                """INSERT INTO process_part_options (
                       id, group_id, part_id, handling_type, fishbone_assignment_id, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                ppo_tuples,
            )
            conn.executemany(
                """INSERT INTO work_element_material_groups (
                       id, project_id, scenario_id, yamazumi_element_id, target_assembly_id,
                       name, selection_rule, quantity, notes, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                wemg_tuples,
            )
            conn.executemany(
                """INSERT INTO work_element_material_options (
                       id, group_id, part_id, assembly_id, updated_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                wemo_tuples,
            )

            # 10 Ergonomic Hazard Options, 100 Ergonomics Reviews, 200 Hazard Selections
            haz_tuples = []
            for h_idx in range(1, 11):
                hid = str(uuid4())
                hazard_option_ids.append(hid)
                haz_tuples.append((hid, self.project_id, f"Hazard Factor {h_idx:02d}", 1, now, now))
            conn.executemany(
                """INSERT INTO ergonomic_hazard_options (
                       id, project_id, label, active, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                haz_tuples,
            )

            ergo_tuples = []
            ergo_sel_tuples = []
            for e_idx in range(1, 101):
                rid = str(uuid4())
                ergo_review_ids.append(rid)
                we_id = work_element_ids[e_idx - 1]
                risk_cls = "Red" if e_idx % 5 == 0 else ("Favorable Red" if e_idx % 2 == 0 else "Green")
                ergo_tuples.append((
                    rid, self.project_id, self.scenario_id, we_id, None,
                    "Open", risk_cls, "Ergo Lead", f"Ergo assessment note {e_idx}",
                    "2026-08-01", "", now, now,
                ))
                h1 = hazard_option_ids[(e_idx - 1) % len(hazard_option_ids)]
                h2 = hazard_option_ids[e_idx % len(hazard_option_ids)]
                ergo_sel_tuples.append((
                    str(uuid4()), self.project_id, self.scenario_id, rid, h1, 10, now, now,
                ))
                ergo_sel_tuples.append((
                    str(uuid4()), self.project_id, self.scenario_id, rid, h2, 20, now, now,
                ))
            conn.executemany(
                """INSERT INTO ergonomics_reviews (
                       id, project_id, scenario_id, work_element_id, process_part_option_id,
                       status, risk_classification, reviewer, notes, requested_due_date,
                       legacy_description, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ergo_tuples,
            )
            conn.executemany(
                """INSERT INTO ergonomics_review_hazard_selections (
                       id, project_id, scenario_id, ergonomics_review_id, hazard_option_id,
                       sequence, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ergo_sel_tuples,
            )

        # 3. Save 100 Safety Requirements via store.save_safety_requirements
        safety_rows = [
            {
                "id": "",
                "work_element_id": work_element_ids[idx],
                "requirement_description": f"Mandatory pinch-point and PPE check {idx + 1:03d}",
                "ppe": ["Safety Glasses", "Cut-Resistant Gloves"],
                "active": True,
            }
            for idx in range(100)
        ]
        safety_res = store.save_safety_requirements(
            self.project_id,
            self.scenario_id,
            pd.DataFrame(safety_rows),
            editor_name="Safety Lead",
        )
        self.assertEqual(safety_res["row_count"], 100)

        # 4. Populate Equipment Types, 50 Equipment Assets, 50 Placements, 150 Process Links, and 5 Conveyor Zones
        eq_types_df = equipment_store.equipment_types(self.project_id)
        torque_type_rows = eq_types_df[
            eq_types_df["label"].astype(str).str.casefold() == "torque tool"
        ]
        if torque_type_rows.empty:
            equipment_store.save_equipment_types(
                self.project_id,
                pd.DataFrame([{"id": "", "label": "Torque tool", "active": True}]),
                {"": ["Quality", "Assembly"]},
                editor_name="AME Lead",
            )
            eq_types_df = equipment_store.equipment_types(self.project_id)
            torque_type_rows = eq_types_df[
                eq_types_df["label"].astype(str).str.casefold() == "torque tool"
            ]
        torque_type_id = str(torque_type_rows.iloc[0]["id"])

        equipment_asset_ids: list[str] = []
        with store.connection() as conn:
            asset_tuples = []
            func_link_tuples = []
            placement_tuples = []
            proc_link_tuples = []
            for eq_idx in range(1, 51):
                eq_id = str(uuid4())
                equipment_asset_ids.append(eq_id)
                pitch_id = pitch_ids[eq_idx - 1]
                pl_id = str(uuid4())
                asset_tuples.append((
                    eq_id, self.project_id, torque_type_id, f"DC-Nutrunner-{eq_idx:03d}",
                    "High-precision transducerized tool", "Atlas Copco",
                    f"Tensor-STR-{eq_idx:02d}", f"SN-{10000 + eq_idx}", "", now, now,
                ))
                func_link_tuples.append((
                    str(uuid4()), self.project_id, eq_id, "Quality", now, now,
                ))
                placement_tuples.append((
                    pl_id, self.project_id, self.scenario_id, eq_id, pitch_id, now, now,
                ))
                # Link each placement to the 3 work elements stationed at this pitch
                for offset in range(3):
                    we_idx = (eq_idx - 1) + offset * 50
                    if we_idx < len(work_element_ids):
                        proc_link_tuples.append((
                            str(uuid4()), self.project_id, self.scenario_id,
                            pl_id, work_element_ids[we_idx], f"OP-{we_idx + 1:03d}",
                            f"Fasten and verify subassembly {we_idx + 1:03d}",
                            f"P{eq_idx:03d}", "", now, now,
                        ))
            conn.executemany(
                """INSERT INTO equipment_assets (
                       id, project_id, equipment_type_id, name, description,
                       manufacturer, model, notes, image_path, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                asset_tuples,
            )
            conn.executemany(
                """INSERT INTO equipment_function_links (
                       id, project_id, equipment_id, functional_area, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                func_link_tuples,
            )
            conn.executemany(
                """INSERT INTO equipment_placements (
                       id, project_id, scenario_id, equipment_id, pitch_id, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                placement_tuples,
            )
            conn.executemany(
                """INSERT INTO equipment_process_links (
                       id, project_id, scenario_id, placement_id, work_element_id,
                       process_operation_snapshot, process_description_snapshot,
                       station_pitch_snapshot, unlinked_at, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                proc_link_tuples,
            )

        for z_idx in range(5):
            zone_pitches = pitch_ids[z_idx * 10 : (z_idx + 1) * 10]
            equipment_store.save_conveyor_zone(
                self.project_id,
                self.scenario_id,
                {
                    "name": f"Conveyor Zone {z_idx + 1}",
                    "sequence": (z_idx + 1) * 10,
                    "pitch_ids": zone_pitches,
                    "conveyor_height_in": 34.0,
                    "conveyor_width_in": 36.0,
                    "unit_orientation": "Front",
                    "standard_pitch_length_in": 120.0,
                    "helper_pitch_count": 1,
                    "growth_pitch_count": 1,
                    "monument_length_in": 24.0,
                },
                editor_name="IE Lead",
            )

        # 5. Populate 40 Quality Requirements (20 Torque + 20 Visual/Inspection) & bulk-assign 200 assignments
        quality_req_ids: list[str] = []
        torque_req_ids: list[str] = []
        with store.connection() as conn:
            q_tuples = []
            td_tuples = []
            for q_idx in range(1, 41):
                qid = str(uuid4())
                quality_req_ids.append(qid)
                is_torque = q_idx <= 20
                if is_torque:
                    torque_req_ids.append(qid)
                q_tuples.append((
                    qid,
                    self.project_id,
                    "Torque" if is_torque else "Inspection",
                    f"Critical Fastener Torque Spec {q_idx:02d}" if is_torque else f"Visual Flushness Spec {q_idx:02d}",
                    f"TQ-{q_idx:03d}" if is_torque else f"VS-{q_idx:03d}",
                    0 if is_torque else 1,
                    5.0 if is_torque else 0.5,
                    "+/- 0.5" if is_torque else "+/- 0.1",
                    "Nm" if is_torque else "mm",
                    now,
                    now,
                ))
                if is_torque:
                    td_tuples.append((
                        str(uuid4()), self.project_id, qid, "DC tool",
                        "Pistol", "T25 Torx", now, now,
                    ))
            conn.executemany(
                """INSERT INTO quality_requirements (
                       id, project_id, requirement_type, description, unique_identifier,
                       pass_fail, target_value, tolerances, unit, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                q_tuples,
            )
            conn.executemany(
                """INSERT INTO quality_requirement_torque_details (
                       id, project_id, quality_requirement_id, tool_type,
                       tool_orientation, screw_bit_type, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                td_tuples,
            )

        # Exercise optimized bulk_assign_quality_requirement across 200 step assignments
        t_bulk_q0 = time.perf_counter()
        total_assigned = 0
        for q_idx, qid in enumerate(quality_req_ids[:10]):
            batch_we_ids = work_element_ids[q_idx * 20 : (q_idx + 1) * 20]
            res = quality_store.bulk_assign_quality_requirement(
                self.project_id,
                self.scenario_id,
                qid,
                batch_we_ids,
                editor_name="AQE Lead",
            )
            total_assigned += int(res["created_count"])
        bulk_q_s = time.perf_counter() - t_bulk_q0
        self.assertEqual(total_assigned, 200)
        self.assertLess(bulk_q_s, 3.0, f"Bulk assigning 200 quality requirements took {bulk_q_s:.2f}s")

        # Link first 10 torque requirements to first 10 equipment assets
        for eq_idx in range(10):
            equipment_store.save_equipment_torque_requirements(
                self.project_id,
                equipment_asset_ids[eq_idx],
                [torque_req_ids[eq_idx]],
                editor_name="AME Lead",
            )

        # 6. Populate 120 PFMEA Entries, 120 Effects, 120 Causes, 120 Risk Rows, and 120 Actions
        with store.connection() as conn:
            pf_entries = []
            pf_effects = []
            pf_causes = []
            pf_risks = []
            pf_actions = []
            for pf_idx in range(1, 121):
                entry_id = str(uuid4())
                eff_id = str(uuid4())
                cause_id = str(uuid4())
                we_id = work_element_ids[pf_idx - 1]
                st_num = f"P{((pf_idx - 1) % len(pitch_ids)) + 1:03d}"
                pf_entries.append((
                    entry_id, self.project_id, self.scenario_id, we_id,
                    f"Insufficient fastener seating on step {pf_idx:03d}",
                    "Q" if pf_idx % 3 == 0 else "S",
                    f"OP-{pf_idx:03d}", f"Fasten and verify subassembly {pf_idx:03d}",
                    "Front", st_num, pf_idx * 10, "hash_p", "hash_q", now, now, now,
                ))
                pf_effects.append((
                    eff_id, self.project_id, self.scenario_id, entry_id,
                    f"Water leak or vibration noise {pf_idx:03d}", 7, 10, now, now,
                ))
                pf_causes.append((
                    cause_id, self.project_id, self.scenario_id, entry_id,
                    f"Cross-threaded fastener {pf_idx:03d}", 4, 3, 0, 10, now, now,
                ))
                pf_risks.append((
                    str(uuid4()), self.project_id, self.scenario_id, entry_id,
                    eff_id, cause_id, 7 * 4 * 3, now, now,
                ))
                pf_actions.append((
                    str(uuid4()), self.project_id, self.scenario_id, entry_id,
                    cause_id, "Add angle-monitoring window on DC tool",
                    "AQE Lead", "2026-09-15", "Programmed P-set 12", 7, 2, 2, 28, 10, now, now,
                ))
            conn.executemany(
                """INSERT INTO pfmea_entries (
                       id, project_id, scenario_id, work_element_id, potential_failure_mode,
                       class_code, process_operation_snapshot, process_description_snapshot,
                       process_location_snapshot, process_pitch_snapshot,
                       process_sequence_snapshot, process_source_hash, quality_source_hash,
                       source_reviewed_at, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                pf_entries,
            )
            conn.executemany(
                """INSERT INTO pfmea_effects (
                       id, project_id, scenario_id, pfmea_entry_id, effect_description,
                       severity, sequence, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                pf_effects,
            )
            conn.executemany(
                """INSERT INTO pfmea_causes (
                       id, project_id, scenario_id, pfmea_entry_id, cause_description,
                       occurrence, detection, detection_review_required,
                       sequence, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                pf_causes,
            )
            conn.executemany(
                """INSERT INTO pfmea_risk_rows (
                       id, project_id, scenario_id, pfmea_entry_id, pfmea_effect_id,
                       pfmea_cause_id, rpn, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                pf_risks,
            )
            conn.executemany(
                """INSERT INTO pfmea_actions (
                       id, project_id, scenario_id, pfmea_entry_id,
                       pfmea_cause_id, recommended_action, responsibility,
                       target_completion_date, actions_taken, resulting_severity,
                       resulting_occurrence, resulting_detection, resulting_rpn,
                       sequence, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                pf_actions,
            )

        # 7. Create a 2D Plant Layout with a scaled revision and 120 shapes (pitches, equipment, connectors)
        layout_info = layout_store.create_layout(
            self.project_id,
            "Main Assembly Floor Layout",
            "Full factory line footprint",
            editor_name="Layout Engineer",
        )
        rev_info = layout_store.create_blank_scaled_revision(
            self.project_id,
            layout_info["id"],
            width_value=300.0,
            height_value=120.0,
            unit="feet",
            editor_name="Layout Engineer",
            canvas_width_px=1600,
            canvas_height_px=900,
        )
        revision_id = str(rev_info["id"])
        shapes_payload: list[dict[str, object]] = []
        for idx in range(50):
            s_id = str(uuid4())
            shapes_payload.append({
                "id": s_id,
                "shape_type": "pitch_footprint",
                "label": f"Pitch P{idx + 1:03d}",
                "x": float(40 + (idx % 10) * 140),
                "y": float(60 + (idx // 10) * 140),
                "width": 110.0,
                "height": 80.0,
                "rotation": 0.0,
                "color": "#2563EB",
                "pitch_id": pitch_ids[idx],
                "z_index": idx + 1,
            })
        for idx in range(50):
            shapes_payload.append({
                "id": str(uuid4()),
                "shape_type": "equipment_marker",
                "label": f"Tool {idx + 1:03d}",
                "x": float(60 + (idx % 10) * 140),
                "y": float(80 + (idx // 10) * 140),
                "width": 36.0,
                "height": 36.0,
                "rotation": 0.0,
                "color": "#059669",
                "equipment_id": equipment_asset_ids[idx],
                "z_index": 60 + idx,
            })
        for idx in range(20):
            shapes_payload.append({
                "id": str(uuid4()),
                "shape_type": "connector",
                "label": f"Flow {idx + 1}",
                "x": 100.0,
                "y": 100.0,
                "width": 50.0,
                "height": 10.0,
                "source_shape_id": str(shapes_payload[idx]["id"]),
                "target_shape_id": str(shapes_payload[idx + 1]["id"]),
                "z_index": 120 + idx,
            })
        layout_store.save_layout_shapes(
            self.project_id,
            revision_id,
            shapes_payload,
            editor_name="Layout Engineer",
        )

        # 8. Benchmark Cold vs. Warm reads across all Functional Review modules
        cache_store.clear_all_caches()
        t_fr_cold0 = time.perf_counter()
        safety_df_cold = store.safety_requirements(self.project_id, self.scenario_id)
        ergo_df_cold = store.ergonomics_reviews(self.project_id, self.scenario_id)
        ergo_slide_cold = store.ergonomics_slide_summary(
            self.project_id, self.scenario_id, ergo_review_ids[0]
        )
        q_links_cold = quality_store.quality_requirement_links(self.project_id)
        pfmea_entries_cold = pfmea_store.pfmea_entries(self.project_id, self.scenario_id)
        pfmea_flat_cold = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        cp_proj_cold = control_plan_store.control_plan_projection(self.project_id, self.scenario_id)
        eq_matrix_cold = equipment_store.equipment_needs_vs_placements_matrix(
            self.project_id, self.scenario_id
        )
        line_sizing_cold = equipment_store.scenario_conveyor_line_sizing(
            self.project_id, self.scenario_id
        )
        trace_cold = traceability_store.cross_functional_traceability_matrix(
            self.project_id, self.scenario_id
        )
        shapes_cold = layout_store.list_layout_shapes(revision_id)
        cold_fr_s = time.perf_counter() - t_fr_cold0

        self.assertEqual(len(safety_df_cold), 100)
        self.assertEqual(len(ergo_df_cold), 100)
        self.assertEqual(len(ergo_slide_cold["hazards"]), 2)
        self.assertEqual(len(q_links_cold), 200)
        self.assertEqual(len(pfmea_entries_cold), 120)
        self.assertEqual(len(pfmea_flat_cold), 120)
        self.assertGreaterEqual(len(cp_proj_cold), 120)
        self.assertGreaterEqual(len(eq_matrix_cold), 100)
        self.assertEqual(line_sizing_cold["zone_count"], 5)
        self.assertEqual(line_sizing_cold["active_pitches"], 50)
        self.assertEqual(trace_cold["summary"]["total_steps"], 200)
        self.assertEqual(len(shapes_cold), 120)

        t_fr_warm0 = time.perf_counter()
        safety_df_warm = store.safety_requirements(self.project_id, self.scenario_id)
        ergo_df_warm = store.ergonomics_reviews(self.project_id, self.scenario_id)
        ergo_slide_warm = store.ergonomics_slide_summary(
            self.project_id, self.scenario_id, ergo_review_ids[0]
        )
        q_links_warm = quality_store.quality_requirement_links(self.project_id)
        pfmea_entries_warm = pfmea_store.pfmea_entries(self.project_id, self.scenario_id)
        pfmea_flat_warm = pfmea_store.pfmea_flat_rows(self.project_id, self.scenario_id)
        cp_proj_warm = control_plan_store.control_plan_projection(self.project_id, self.scenario_id)
        eq_matrix_warm = equipment_store.equipment_needs_vs_placements_matrix(
            self.project_id, self.scenario_id
        )
        line_sizing_warm = equipment_store.scenario_conveyor_line_sizing(
            self.project_id, self.scenario_id
        )
        trace_warm = traceability_store.cross_functional_traceability_matrix(
            self.project_id, self.scenario_id
        )
        shapes_warm = layout_store.list_layout_shapes(revision_id)
        warm_fr_s = time.perf_counter() - t_fr_warm0

        self.assertEqual(len(safety_df_warm), 100)
        self.assertEqual(len(ergo_df_warm), 100)
        self.assertEqual(len(ergo_slide_warm["hazards"]), 2)
        self.assertEqual(len(q_links_warm), 200)
        self.assertEqual(len(pfmea_entries_warm), 120)
        self.assertEqual(len(pfmea_flat_warm), 120)
        self.assertEqual(len(cp_proj_warm), len(cp_proj_cold))
        self.assertEqual(len(eq_matrix_warm), len(eq_matrix_cold))
        self.assertEqual(line_sizing_warm["active_pitches"], 50)
        self.assertEqual(trace_warm["summary"]["total_steps"], 200)
        self.assertEqual(len(shapes_warm), 120)
        self.assertLess(
            warm_fr_s,
            cold_fr_s * 0.25,
            f"Warm Functional Review queries ({warm_fr_s:.4f}s) should be <25% of cold ({cold_fr_s:.4f}s)",
        )

        # 9. Stress-test Scenario Cloning across the entire populated scenario
        t_clone0 = time.perf_counter()
        cloned_scenario_id = store.clone_planning_scenario(
            self.project_id,
            self.scenario_id,
            "Cloned High-Volume Scenario",
            "Rev B",
            60.0,
            change_summary="Full deep clone of all planning and functional review records",
            created_by="Stress Tester",
        )
        clone_s = time.perf_counter() - t_clone0
        self.assertLess(
            clone_s,
            5.0,
            f"Cloning a full scenario with 1,500+ cross-functional records took {clone_s:.2f}s (expected < 5s)",
        )

        # Verify cloned scenario integrity across all modules
        self.assertEqual(len(store.safety_requirements(self.project_id, cloned_scenario_id)), 100)
        cloned_ergo_df = store.ergonomics_reviews(self.project_id, cloned_scenario_id)
        self.assertEqual(len(cloned_ergo_df), 200)
        self.assertEqual(int((cloned_ergo_df["reviewer"] == "Ergo Lead").sum()), 100)
        self.assertEqual(
            len(quality_store.quality_requirement_assignments(self.project_id, cloned_scenario_id)),
            200,
        )
        self.assertEqual(len(pfmea_store.pfmea_flat_rows(self.project_id, cloned_scenario_id)), 120)
        self.assertEqual(
            equipment_store.scenario_conveyor_line_sizing(self.project_id, cloned_scenario_id)["zone_count"],
            5,
        )
        self.assertEqual(
            traceability_store.cross_functional_traceability_matrix(
                self.project_id, cloned_scenario_id
            )["summary"]["total_steps"],
            200,
        )

        # 10. Stress-test .paagproject Archive Export, Preview Validation, and Full Project Import
        t_pkg_exp0 = time.perf_counter()
        pkg_export = project_transfer.export_project_package(
            self.project_id, editor_name="Stress Tester"
        )
        pkg_exp_s = time.perf_counter() - t_pkg_exp0
        pkg_bytes = pkg_export["data"]
        self.assertGreater(len(pkg_bytes), 20_000)
        self.assertLess(pkg_exp_s, 5.0, f"Exporting .paagproject took {pkg_exp_s:.2f}s")

        t_pkg_prev0 = time.perf_counter()
        pkg_preview = project_transfer.preview_project_package(pkg_bytes)
        pkg_prev_s = time.perf_counter() - t_pkg_prev0
        self.assertEqual(pkg_preview["record_counts"]["planning_scenarios"], 2)
        self.assertEqual(pkg_preview["record_counts"]["parts"], 200)
        self.assertEqual(pkg_preview["record_counts"]["work_elements"], 400)  # 200 x 2 scenarios
        self.assertEqual(pkg_preview["record_counts"]["pfmea_entries"], 240)  # 120 x 2 scenarios
        self.assertEqual(pkg_preview["record_counts"]["layout_shapes"], 120)
        self.assertLess(pkg_prev_s, 3.0)

        t_pkg_imp0 = time.perf_counter()
        imported_proj = project_transfer.import_project_package(
            pkg_bytes,
            "Create new",
            editor_name="Stress Tester",
        )
        pkg_imp_s = time.perf_counter() - t_pkg_imp0
        self.assertLess(
            pkg_imp_s,
            6.0,
            f"Importing full .paagproject graph with 2 scenarios took {pkg_imp_s:.2f}s (expected < 6s)",
        )

        new_proj_id = str(imported_proj["project_id"])
        new_scen_id = str(imported_proj["scenario_id"])
        self.assertNotEqual(new_proj_id, self.project_id)
        self.assertEqual(len(store.planning_scenarios(new_proj_id)), 2)
        self.assertEqual(len(store.project_table("parts", new_proj_id, "part_number")), 200)
        self.assertEqual(len(store.safety_requirements(new_proj_id, new_scen_id)), 100)
        self.assertEqual(len(pfmea_store.pfmea_flat_rows(new_proj_id, new_scen_id)), 120)

        # 11. Verify composite SQLite indexes, scoped catalog cache preservation across
        #     scenario writes, and pre-warmed image upload cache hits.
        with store.connection() as conn:
            existing_indexes = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
        for expected_idx in (
            "idx_fishbone_part_assignments_proj_sec_part",
            "idx_yamazumi_elements_proj_area_pitch_proc",
            "idx_work_elements_proj_scen_seq",
            "idx_quality_req_assignments_proj_scen_we",
            "idx_ergonomics_reviews_proj_scen_we",
            "idx_safety_requirements_proj_scen_we",
            "idx_parts_proj_pn",
        ):
            self.assertIn(expected_idx, existing_indexes)

        # Warm catalog-scoped caches for new_proj_id
        _ = store.project_table("parts", new_proj_id, "part_number")
        _ = store.complexity_features(new_proj_id)
        _ = store.complexity_tree(new_proj_id)

        epoch_cat_before = cache_store.get_write_epoch("catalog")
        epoch_scen_before = cache_store.get_write_epoch("scenario")

        # Execute a scenario-scoped write (Safety review update)
        safety_df = store.safety_requirements(new_proj_id, new_scen_id)
        safety_df.loc[0, "requirement_description"] = "Updated mandatory PPE check"
        store.save_safety_requirements(
            new_proj_id,
            new_scen_id,
            safety_df,
            editor_name="Safety Lead",
        )

        # Catalog epoch must remain unchanged while scenario epoch increments
        self.assertEqual(cache_store.get_write_epoch("catalog"), epoch_cat_before)
        self.assertGreater(cache_store.get_write_epoch("scenario"), epoch_scen_before)

        cache = cache_store.get_data_cache()
        misses_before_cat = cache.misses
        hits_before_cat = cache.hits
        _ = store.project_table("parts", new_proj_id, "part_number")
        _ = store.complexity_features(new_proj_id)
        _ = store.complexity_tree(new_proj_id)
        self.assertEqual(cache.misses, misses_before_cat)
        self.assertEqual(cache.hits, hits_before_cat + 3)

        # Verify image upload pre-warms WebP thumbnail and data-URL cache tiers immediately
        first_part_id = str(store.project_table("parts", new_proj_id, "part_number").iloc[0]["id"])
        img_buf = BytesIO()
        Image.new("RGB", (1280, 960), color=(30, 140, 210)).save(img_buf, format="PNG")
        img_buf.name = "part_upload.png"
        saved_img_path = store.set_part_image(first_part_id, img_buf)

        misses_before_img = cache.misses
        hits_before_img = cache.hits
        self.assertIsNotNone(media_cache.cached_image_bytes(saved_img_path, max_dim=160))
        self.assertIsNotNone(media_cache.cached_image_bytes(saved_img_path, max_dim=360))
        self.assertIsNotNone(media_cache.cached_image_data_url(saved_img_path, max_dim=360))
        self.assertIsNotNone(media_cache.cached_image_data_url(saved_img_path, max_dim=1600))
        self.assertEqual(cache.misses, misses_before_img)
        self.assertEqual(cache.hits, hits_before_img + 4)


if __name__ == "__main__":
    unittest.main()
