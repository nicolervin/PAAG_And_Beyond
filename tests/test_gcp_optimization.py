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

from utils.cache_store import _env_int
import utils.db_core as db_core
from utils.gcp_auth import (
    _extract_email_from_jwt_payload,
    clean_iap_okta_identity,
    detect_authenticated_user_email,
)
import utils.gcp_storage as gcp_storage


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
            with patch.object(db_core, "UPLOAD_DIR", upload_dir):
                updated = db_core._rebase_cross_platform_upload_paths(conn)
                self.assertEqual(updated, 1)
                row = conn.execute("SELECT photo_path FROM parts WHERE id='p1'").fetchone()
                self.assertEqual(Path(row["photo_path"]), img_file)
            conn.close()

    def test_cache_env_int_bounds(self) -> None:
        with patch.dict(os.environ, {"PAAG_CACHE_MAX_MB": "512"}):
            self.assertEqual(_env_int("PAAG_CACHE_MAX_MB", 128, 16, 4096), 512)
        with patch.dict(os.environ, {"PAAG_CACHE_MAX_MB": "not-an-int"}):
            self.assertEqual(_env_int("PAAG_CACHE_MAX_MB", 128, 16, 4096), 128)
        with patch.dict(os.environ, {"PAAG_CACHE_MAX_MB": "4"}):
            self.assertEqual(_env_int("PAAG_CACHE_MAX_MB", 128, 16, 4096), 16)


if __name__ == "__main__":
    unittest.main()
