from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4

import openpyxl
import pandas as pd
from PIL import Image, ImageDraw

from utils import cache_store, db_core, excel_io, media_cache, store


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
        self.assertLess(warm_parse_s, 0.020, "Upload-scoped cached parse should be < 20ms")
        self.assertLess(warm_parse_s, cold_parse_s * 0.05)

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
        self.assertLess(warm_tree_s, 0.015)
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

        self.assertLess(warm_img_s, 0.020, "40 warm thumbnail lookups should take < 20ms total")
        self.assertLess(warm_img_s, cold_img_s * 0.05)

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


if __name__ == "__main__":
    unittest.main()
