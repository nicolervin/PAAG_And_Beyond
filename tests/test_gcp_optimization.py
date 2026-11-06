"""Unit tests for GCP Cloud Run optimizations (IAP/Okta auth, GCS sync, cross-platform paths)."""

from __future__ import annotations

import base64
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from utils.cache_store import (
    _env_int,
    get_active_collaborators,
    get_last_write_metadata,
    record_collaborator_heartbeat,
    record_write_attribution,
)
import utils.db_core as db_core
from utils.gcp_auth import (
    _extract_email_from_jwt_payload,
    clean_iap_okta_identity,
    detect_authenticated_user_email,
    detect_verified_sso_email,
)
import utils.gcp_storage as gcp_storage
import utils.project_store as project_store
import utils.split_workspace as split_workspace
import threading
import time


def _make_fake_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "ES256"}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.signature"


class FakeBlob:
    def __init__(self, name: str, store: dict[str, bytes]) -> None:
        self.name = name
        self._store = store

    def exists(self) -> bool:
        return self.name in self._store

    @property
    def size(self) -> int:
        return len(self._store.get(self.name, b""))

    def upload_from_filename(self, filename: str, **kwargs: object) -> None:
        self._store[self.name] = Path(filename).read_bytes()

    def download_to_filename(self, filename: str) -> None:
        if self.name not in self._store:
            raise FileNotFoundError(self.name)
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        Path(filename).write_bytes(self._store[self.name])


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(name, self.objects)

    def list_blobs(self, prefix: str = "") -> list[FakeBlob]:
        return [
            FakeBlob(name, self.objects)
            for name in sorted(self.objects)
            if name.startswith(prefix)
        ]


class TestGcpAuth(unittest.TestCase):
    def test_clean_iap_okta_identity_strips_prefixes(self) -> None:
        self.assertEqual(
            clean_iap_okta_identity("accounts.google.com:engineer@company.com"),
            "engineer@company.com",
        )
        self.assertEqual(
            clean_iap_okta_identity("securetoken.google.com/my-project/okta-saml:engineer@company.com"),
            "engineer@company.com",
        )
        self.assertEqual(
            clean_iap_okta_identity("  engineer@company.com  "),
            "engineer@company.com",
        )
        self.assertEqual(clean_iap_okta_identity(None), "")

    def test_extract_email_from_jwt_payload(self) -> None:
        jwt_token = _make_fake_jwt(
            {
                "iss": "https://cloud.google.com/iap",
                "sub": "accounts.google.com:123456",
                "email": "accounts.google.com:aqe.user@company.com",
            }
        )
        self.assertEqual(
            _extract_email_from_jwt_payload(jwt_token),
            "aqe.user@company.com",
        )
        okta_jwt = _make_fake_jwt({"upn": "okta.user@company.com"})
        self.assertEqual(
            _extract_email_from_jwt_payload(okta_jwt),
            "okta.user@company.com",
        )

    def test_detect_authenticated_user_email_priority(self) -> None:
        headers = {
            "X-Goog-Authenticated-User-Email": "accounts.google.com:iap.user@company.com",
            "X-Okta-User": "okta.fallback@company.com",
        }
        with patch("utils.gcp_auth._get_streamlit_request_headers", return_value=headers):
            self.assertEqual(detect_authenticated_user_email(), "iap.user@company.com")

        jwt_only_headers = {
            "X-Goog-IAP-JWT-Assertion": _make_fake_jwt({"email": "jwt.user@company.com"}),
        }
        with patch("utils.gcp_auth._get_streamlit_request_headers", return_value=jwt_only_headers):
            self.assertEqual(detect_authenticated_user_email(), "jwt.user@company.com")

        with patch("utils.gcp_auth._get_streamlit_request_headers", return_value={}):
            with patch.dict(os.environ, {"PAAG_DEFAULT_EDITOR": "env.editor@company.com"}):
                self.assertEqual(detect_authenticated_user_email(), "env.editor@company.com")


class TestGcpStorageAndPaths(unittest.TestCase):
    def test_cross_platform_upload_path_resolution_and_rebase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upload_dir = Path(tmp) / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            sample_file = upload_dir / "part_photo_abc.png"
            sample_file.write_bytes(b"PNGDATA")

            win_path = r"C:\Users\engineer\PAAG_And_Beyond\data\uploads\part_photo_abc.png"
            resolved = gcp_storage.resolve_upload_path(win_path, upload_dir)
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved.resolve(), sample_file.resolve())

            rebased_str = gcp_storage.rebase_upload_path_str(win_path, upload_dir)
            self.assertEqual(Path(rebased_str).resolve(), sample_file.resolve())

    def test_sqlite_snapshot_and_gcs_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            src_db = tmp_root / "source" / "paag.db"
            src_uploads = tmp_root / "source" / "uploads"
            src_uploads.mkdir(parents=True, exist_ok=True)
            src_db.parent.mkdir(parents=True, exist_ok=True)

            with closing(sqlite3.connect(src_db)) as conn:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("CREATE TABLE sample_items (id TEXT PRIMARY KEY, name TEXT)")
                conn.execute("INSERT INTO sample_items VALUES ('1', 'Cloud Run Ready')")
                conn.commit()
            (src_uploads / "diagram.png").write_bytes(b"1234567890")

            fake_bucket = FakeBucket()
            gcp_storage._UPLOADED_FILE_SIGNATURES.clear()
            gcp_storage._LAST_SYNCED_DB_SIGNATURE = None
            with patch.dict(
                os.environ,
                {"PAAG_GCS_BUCKET": "unit-test-bucket", "PAAG_GCS_PREFIX": "paag-test"},
            ):
                with patch("utils.gcp_storage._get_gcs_bucket", return_value=fake_bucket):
                    synced = gcp_storage.sync_state_to_gcs_now(src_db, src_uploads, force_db=True)
                    self.assertTrue(synced)
                    self.assertIn("paag-test/paag.db", fake_bucket.objects)
                    self.assertIn("paag-test/uploads/diagram.png", fake_bucket.objects)

                    # Restore into a fresh container directory
                    dst_db = tmp_root / "restored" / "paag.db"
                    dst_uploads = tmp_root / "restored" / "uploads"
                    gcp_storage._BOOTSTRAPPED_TARGETS.clear()
                    restored = gcp_storage.bootstrap_from_gcs_if_needed(dst_db, dst_uploads)
                    self.assertTrue(restored)
                    self.assertTrue(dst_db.is_file())
                    self.assertEqual((dst_uploads / "diagram.png").read_bytes(), b"1234567890")

                    with closing(sqlite3.connect(dst_db)) as check_conn:
                        row = check_conn.execute(
                            "SELECT name FROM sample_items WHERE id='1'"
                        ).fetchone()
                        self.assertEqual(row[0], "Cloud Run Ready")

    def test_rebase_cross_platform_upload_paths_in_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upload_dir = Path(tmp) / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            img_file = upload_dir / "hero_part.webp"
            img_file.write_bytes(b"WEBPDATA")

            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            conn.execute("CREATE TABLE parts (id TEXT PRIMARY KEY, photo_path TEXT)")
            conn.execute(
                "INSERT INTO parts VALUES ('p1', ?)",
                (r"C:\Windows\workspace\data\uploads\hero_part.webp",),
            )
            conn.execute(
                "CREATE TABLE future_module_items (id TEXT PRIMARY KEY, custom_diagram_path TEXT)"
            )
            conn.execute(
                "INSERT INTO future_module_items VALUES ('f1', ?)",
                (r"C:\Windows\workspace\data\uploads\hero_part.webp",),
            )
            with patch.object(db_core, "UPLOAD_DIR", upload_dir):
                updated = db_core._rebase_cross_platform_upload_paths(conn)
                self.assertEqual(updated, 2)
                row = conn.execute("SELECT photo_path FROM parts WHERE id='p1'").fetchone()
                self.assertEqual(Path(row["photo_path"]), img_file)
                future_row = conn.execute(
                    "SELECT custom_diagram_path FROM future_module_items WHERE id='f1'"
                ).fetchone()
                self.assertEqual(Path(future_row["custom_diagram_path"]), img_file)
            conn.close()

    def test_cache_env_int_bounds(self) -> None:
        with patch.dict(os.environ, {"PAAG_CACHE_MAX_MB": "512"}):
            self.assertEqual(_env_int("PAAG_CACHE_MAX_MB", 128, 16, 4096), 512)
        with patch.dict(os.environ, {"PAAG_CACHE_MAX_MB": "not-an-int"}):
            self.assertEqual(_env_int("PAAG_CACHE_MAX_MB", 128, 16, 4096), 128)
        with patch.dict(os.environ, {"PAAG_CACHE_MAX_MB": "4"}):
            self.assertEqual(_env_int("PAAG_CACHE_MAX_MB", 128, 16, 4096), 16)

    def test_upload_safety_blocks_disguised_executables_and_scripts(self) -> None:
        ok, _ = gcp_storage.validate_upload_bytes_safety("bracket.png", b"\x89PNG\r\n\x1a\n...")
        self.assertTrue(ok)
        ok_step, _ = gcp_storage.validate_upload_bytes_safety("assembly.step", b"ISO-10303-21;HEADER;")
        self.assertTrue(ok_step)

        bad_exe, reason_exe = gcp_storage.validate_upload_bytes_safety("malware.png", b"MZ\x90\x00\x03\x00")
        self.assertFalse(bad_exe)
        self.assertIn("PE/MZ", reason_exe)

        bad_elf, _ = gcp_storage.validate_upload_bytes_safety("linux_bin.jpg", b"\x7fELF\x02\x01")
        self.assertFalse(bad_elf)

        bad_script, _ = gcp_storage.validate_upload_bytes_safety("xss.png", b"<html><script>alert(1)</script></html>")
        self.assertFalse(bad_script)

        bad_ext, _ = gcp_storage.validate_upload_bytes_safety("installer.exe", b"SAFEBYTES")
        self.assertFalse(bad_ext)

    def test_async_upload_hydration_restores_db_immediately_and_uploads_in_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            src_db = tmp_root / "src" / "paag.db"
            src_uploads = tmp_root / "src" / "uploads"
            src_uploads.mkdir(parents=True, exist_ok=True)
            src_db.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(src_db)) as conn:
                conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY)")
                conn.execute("INSERT INTO t VALUES ('ok')")
                conn.commit()
            (src_uploads / "cad_model.step").write_bytes(b"ISO-10303-21-STEP-DATA")

            fake_bucket = FakeBucket()
            gcp_storage._UPLOADED_FILE_SIGNATURES.clear()
            gcp_storage._LAST_SYNCED_DB_SIGNATURE = None
            with patch.dict(os.environ, {"PAAG_GCS_BUCKET": "async-bucket"}):
                with patch("utils.gcp_storage._get_gcs_bucket", return_value=fake_bucket):
                    self.assertTrue(gcp_storage.sync_state_to_gcs_now(src_db, src_uploads, force_db=True))
                    dst_db = tmp_root / "dst" / "paag.db"
                    dst_uploads = tmp_root / "dst" / "uploads"
                    gcp_storage._BOOTSTRAPPED_TARGETS.clear()
                    restored = gcp_storage.bootstrap_from_gcs_if_needed(
                        dst_db, dst_uploads, async_uploads=True
                    )
                    self.assertTrue(restored)
                    self.assertTrue(dst_db.is_file())
                    for _ in range(40):
                        if (dst_uploads / "cad_model.step").is_file():
                            break
                        time.sleep(0.02)
                    self.assertTrue((dst_uploads / "cad_model.step").is_file())

    def test_per_editor_workspace_memory_isolates_collaborators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_file = Path(tmp) / "paag.db"
            with patch.object(project_store, "DB_PATH", db_file):
                project_store.set_last_active_workspace(
                    "proj-washer", "scen-w1", editor_name="alice@geappliances.com"
                )
                project_store.set_last_active_workspace(
                    "proj-dryer", "scen-d2", editor_name="bob@geappliances.com"
                )
                self.assertEqual(
                    project_store.get_last_active_workspace(editor_name="alice@geappliances.com"),
                    {"project_id": "proj-washer", "scenario_id": "scen-w1"},
                )
                self.assertEqual(
                    project_store.get_last_active_workspace(editor_name="bob@geappliances.com"),
                    {"project_id": "proj-dryer", "scenario_id": "scen-d2"},
                )

    def test_verified_sso_email_ignores_env_fallback(self) -> None:
        with patch("utils.gcp_auth._get_streamlit_request_headers", return_value={}):
            with patch.dict(os.environ, {"PAAG_DEFAULT_EDITOR": "local.fallback@company.com"}):
                self.assertEqual(detect_verified_sso_email(), "")
                self.assertEqual(detect_authenticated_user_email(), "local.fallback@company.com")

    def test_live_collaborator_presence_and_write_attribution(self) -> None:
        record_collaborator_heartbeat(
            "sess-1",
            editor_name="alice@geappliances.com",
            project_id="proj-1",
            scenario_id="scen-1",
            page_title="Yamazumi",
        )
        record_collaborator_heartbeat(
            "sess-2",
            editor_name="bob@geappliances.com",
            project_id="proj-1",
            scenario_id="scen-1",
            page_title="Process at a Glance",
        )
        peers_for_alice = get_active_collaborators(
            project_id="proj-1", exclude_session_id="sess-1"
        )
        self.assertEqual(len(peers_for_alice), 1)
        self.assertEqual(peers_for_alice[0]["editor_name"], "bob@geappliances.com")
        self.assertEqual(peers_for_alice[0]["page_title"], "Process at a Glance")

        record_write_attribution(
            project_id="proj-1",
            table_name="Yamazumi",
            action="Save & Refresh",
            editor_name="bob@geappliances.com",
            timestamp="2026-11-05T09:00:00-05:00",
        )
        meta = get_last_write_metadata()
        self.assertEqual(meta["editor_name"], "bob@geappliances.com")
        self.assertEqual(meta["table_name"], "Yamazumi")

    def test_concurrent_sqlite_writes_serialize_without_lock_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_db = Path(tmp) / "concurrent.db"
            with patch.object(db_core, "DB_PATH", test_db):
                with db_core.connection() as conn:
                    conn.execute("CREATE TABLE concurrent_items (id TEXT PRIMARY KEY, val INTEGER)")
                errors: list[Exception] = []

                def _writer(worker_idx: int) -> None:
                    try:
                        for i in range(10):
                            with db_core.connection() as c:
                                c.execute("SELECT COUNT(*) FROM concurrent_items").fetchone()
                                c.execute(
                                    "INSERT INTO concurrent_items VALUES (?, ?)",
                                    (f"w{worker_idx}_{i}", i),
                                )
                    except Exception as exc:
                        errors.append(exc)

                threads = [threading.Thread(target=_writer, args=(idx,)) for idx in range(5)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                self.assertEqual(errors, [])
                rows = db_core.query("SELECT COUNT(*) AS cnt FROM concurrent_items")
                self.assertEqual(rows[0]["cnt"], 50)

    def test_beforeunload_guard_present_in_split_navigation_js(self) -> None:
        self.assertIn("beforeunload", split_workspace._NAV_JS)
        self.assertIn('[data-paag-unsaved="true"]', split_workspace._NAV_JS)

    def test_yamazumi_pitch_move_conflict_detection_across_reordered_rows_and_board(self) -> None:
        import pandas as pd
        import streamlit as st
        from utils.table_ui import detect_table_cell_conflicts

        # 1. Table editor conflict when SQLite row order changes after collaborator moves element to another pitch
        editor_key = "yamazumi_element_editor_scen1_area1"
        base_df = pd.DataFrame(
            [
                {"id": "elem-1", "description": "Install drain pump", "pitch": "01-ML1-001", "sequence": 10},
                {"id": "elem-2", "description": "Secure wire harness", "pitch": "01-ML1-002", "sequence": 10},
            ]
        )
        # Collaborator 1 moved elem-1 to 01-ML1-003, which caused SQLite to return elem-2 first, then elem-1
        live_df = pd.DataFrame(
            [
                {"id": "elem-2", "description": "Secure wire harness", "pitch": "01-ML1-002", "sequence": 10},
                {"id": "elem-1", "description": "Install drain pump", "pitch": "01-ML1-003", "sequence": 10},
            ]
        )
        # Collaborator 2 had frozen display_df with elem-1 at row 0 and moved elem-1 to 01-ML1-004
        st.session_state[f"_table_clean_base_df_{editor_key}"] = base_df
        st.session_state[f"_table_live_df_{editor_key}"] = live_df
        st.session_state[f"_table_display_df_{editor_key}"] = base_df
        st.session_state[f"_table_undo_meta_{editor_key}"] = {
            "col_labels": {"pitch": "Pitch"},
            "row_labels": {0: "Install drain pump", 1: "Secure wire harness"},
        }
        st.session_state[editor_key] = {"edited_rows": {0: {"pitch": "01-ML1-004"}}, "added_rows": [], "deleted_rows": []}

        conflicts = detect_table_cell_conflicts(editor_key)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["row_label"], "Install drain pump")
        self.assertEqual(conflicts[0]["column_label"], "Pitch")
        self.assertEqual(conflicts[0]["base_value"], "01-ML1-001")
        self.assertEqual(conflicts[0]["saved_value"], "01-ML1-003")
        self.assertEqual(conflicts[0]["your_value"], "01-ML1-004")

        # 2. Visual Yamazumi Board conflict via _table_id_draft_
        board_key = "yamazumi_board_footer_proj1_scen1_area1"
        st.session_state[f"_table_clean_base_df_{board_key}"] = base_df
        st.session_state[f"_table_live_df_{board_key}"] = live_df
        st.session_state[f"_table_undo_meta_{board_key}"] = {
            "col_labels": {"pitch": "Pitch", "stack_order": "Stack Order"},
            "row_labels": {},
        }
        st.session_state[f"_table_id_draft_{board_key}"] = {
            "elem-1": {"pitch": "01-ML1-002"}
        }
        board_conflicts = detect_table_cell_conflicts(board_key)
        self.assertEqual(len(board_conflicts), 1)
        self.assertEqual(board_conflicts[0]["row_label"], "Install drain pump")
        self.assertEqual(board_conflicts[0]["column_label"], "Pitch")
        self.assertEqual(board_conflicts[0]["base_value"], "01-ML1-001")
        self.assertEqual(board_conflicts[0]["saved_value"], "01-ML1-003")
        self.assertEqual(board_conflicts[0]["your_value"], "01-ML1-002")

    def test_compare_record_field_conflicts_auto_merges_and_flags_true_conflicts(self) -> None:
        from utils.table_ui import (
            check_standalone_conflict_resolution,
            compare_record_field_conflicts,
            trigger_standalone_conflict_dialog,
        )

        baseline = {"tool": "M6 Driver", "cycle_time_s": 12.0, "status": "Draft"}
        # Collaborator updated cycle_time_s to 15.0 and status to Review
        live = {"tool": "M6 Driver", "cycle_time_s": 15.0, "status": "Review"}
        # Current user updated tool to M8 Driver and status to Validated, leaving cycle_time_s at 12.0
        user_values = {"tool": "M8 Driver", "cycle_time_s": 12.0, "status": "Validated"}

        merged, conflicts = compare_record_field_conflicts(
            row_label="OP-10",
            baseline=baseline,
            live=live,
            user_values=user_values,
            field_labels={"tool": "Tool", "cycle_time_s": "Time (s)", "status": "PAAG Status"},
        )
        # cycle_time_s was not edited by current user -> auto-merged from live (15.0)
        self.assertEqual(merged["cycle_time_s"], 15.0)
        # tool was only edited by current user -> kept as M8 Driver without conflict
        self.assertEqual(merged["tool"], "M8 Driver")
        # status was edited by both to different values -> flagged as conflict
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["Field"], "PAAG Status")
        self.assertEqual(conflicts[0]["Original Value"], "Draft")
        self.assertEqual(conflicts[0]["Saved by Collaborator"], "Review")
        self.assertEqual(conflicts[0]["Your Unsaved Edit"], "Validated")

        # Standalone conflict dialog trigger & resolution round-trip
        trigger_standalone_conflict_dialog("test_standalone_key", conflicts, payload={"val": 42})
        import streamlit as st
        self.assertIn("_pending_save_conflict_test_standalone_key", st.session_state)
        st.session_state["_conflict_confirmed_save_test_standalone_key"] = True
        res, payload = check_standalone_conflict_resolution("test_standalone_key")
        self.assertIs(res, True)
        self.assertEqual(payload, {"val": 42})

    def test_architecture_guardrail_all_record_edit_dialogs_and_canvases_protect_against_conflicts(self) -> None:
        import ast
        import glob
        import streamlit as st
        import utils.table_filters as tf

        repo_root = Path(__file__).resolve().parents[1]

        # 1. Verify st.data_editor is globally wrapped by _wrap_data_editor
        self.assertEqual(st.data_editor, tf._wrap_data_editor)

        # 2. Verify every @st.dialog in app_pages/*.py that calls an `update_*` store helper
        #    (excluding confirmation dialogs `confirm_*`) uses inline conflict protection.
        unprotected_dialogs: list[str] = []
        for path in sorted(glob.glob(str(repo_root / "app_pages" / "*.py"))):
            source = Path(path).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                if node.name.startswith("confirm_") or node.name.startswith("_confirm_"):
                    continue
                is_dialog = any("dialog" in ast.unparse(dec) for dec in node.decorator_list)
                if not is_dialog:
                    continue
                calls = {
                    ast.unparse(c.func)
                    for c in ast.walk(node)
                    if isinstance(c, ast.Call)
                }
                has_update_write = any(
                    c.startswith("update_") or ".update_" in c for c in calls
                )
                if has_update_write:
                    has_conflict_guard = any(
                        "conflict" in c for c in calls
                    )
                    if not has_conflict_guard:
                        unprotected_dialogs.append(f"{Path(path).name}:{node.lineno}:{node.name}")
        self.assertEqual(
            unprotected_dialogs,
            [],
            f"Found @st.dialog edit functions calling update_* without conflict protection: {unprotected_dialogs}",
        )

        # 3. Verify custom canvas & spreadsheet modules retain conflict detection hooks
        for rel_path in (
            "app_pages/fishbone.py",
            "app_pages/yamazumi.py",
            "app_pages/bom_tree.py",
            "utils/layout_ui.py",
        ):
            text = (repo_root / rel_path).read_text(encoding="utf-8")
            self.assertTrue(
                "trigger_standalone_conflict_dialog" in text or "_table_clean_base_df_" in text,
                f"{rel_path} must retain standalone or baseline conflict detection.",
            )


if __name__ == "__main__":
    unittest.main()
