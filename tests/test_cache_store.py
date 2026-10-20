from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from PIL import Image

from utils import cache_store, db_core, media_cache, store


class CompressedLRUCacheTests(unittest.TestCase):
    def test_compresses_dataframe_and_isolates_mutated_copies(self) -> None:
        cache = cache_store.CompressedLRUCache(max_bytes=4 * 1024 * 1024, max_entries=64)
        df = pd.DataFrame(
            {
                "part_number": pd.Series([f"PN-{i % 10:04d}" for i in range(500)], dtype="string"),
                "description": pd.Series(["Repeated assembly bracket description"] * 500, dtype="string"),
                "qty": pd.Series([1.0] * 500, dtype="float64"),
            }
        )
        self.assertTrue(cache.set("parts_df", df))
        stats = cache.stats()
        self.assertEqual(stats["entries"], 1)
        self.assertLess(stats["compressed_bytes"], stats["uncompressed_bytes"])

        hit, retrieved = cache.get("parts_df")
        self.assertTrue(hit)
        pd.testing.assert_frame_equal(retrieved, df)

        # Mutate retrieved copy and verify cached payload is untouched
        retrieved.loc[0, "part_number"] = "MUTATED-9999"
        hit2, retrieved2 = cache.get("parts_df")
        self.assertTrue(hit2)
        self.assertEqual(retrieved2.loc[0, "part_number"], "PN-0000")

    def test_lru_evicts_oldest_entries_when_entry_cap_exceeded(self) -> None:
        cache = cache_store.CompressedLRUCache(max_bytes=8 * 1024 * 1024, max_entries=32)
        for idx in range(32):
            self.assertTrue(cache.set(f"k-{idx}", {"index": idx, "payload": "x" * 100}))

        # Touch k-0 so k-1 becomes the least-recently-used entry
        hit, _ = cache.get("k-0")
        self.assertTrue(hit)

        self.assertTrue(cache.set("k-32", {"index": 32, "payload": "x" * 100}))
        self.assertTrue(cache.get("k-0")[0])
        self.assertFalse(cache.get("k-1")[0])
        self.assertTrue(cache.get("k-32")[0])
        self.assertGreaterEqual(cache.stats()["evictions"], 1)


class StoreReadCacheAndInvalidationTests(unittest.TestCase):
    def setUp(self) -> None:
        cache_store.clear_all_caches()

    def tearDown(self) -> None:
        cache_store.clear_all_caches()

    def test_cached_store_read_hits_and_invalidates_on_write_epoch_or_connection(self) -> None:
        call_count = 0

        @cache_store.cached_store_read
        def sample_query(project_id: str, *, _conn=None) -> dict[str, object]:
            nonlocal call_count
            call_count += 1
            return {"project_id": project_id, "calls": call_count}

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = Path(tmpdir) / "test_paag.db"
            temp_db.write_bytes(b"sqlite-placeholder")
            with patch.object(db_core, "DB_PATH", temp_db), patch.object(store, "DB_PATH", temp_db):
                first = sample_query("proj-1")
                second = sample_query("proj-1")
                self.assertEqual(call_count, 1)
                self.assertEqual(first, second)
                self.assertIsNot(first, second)

                # Passing _conn bypasses cache
                with_conn = sample_query("proj-1", _conn=object())
                self.assertEqual(call_count, 2)
                self.assertEqual(with_conn["calls"], 2)

                # Bumping write epoch invalidates cached store read
                cache_store.bump_write_epoch()
                third = sample_query("proj-1")
                self.assertEqual(call_count, 3)
                self.assertEqual(third["calls"], 3)

    def test_scenario_task_guard_resets_when_db_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = Path(tmpdir) / "test_paag.db"
            temp_db.write_bytes(b"sqlite-placeholder")
            with patch.object(db_core, "DB_PATH", temp_db), patch.object(store, "DB_PATH", temp_db):
                self.assertFalse(cache_store.is_scenario_task_completed("sync_task", "proj-1", "scen-1"))
                cache_store.mark_scenario_task_completed("sync_task", "proj-1", "scen-1")
                self.assertTrue(cache_store.is_scenario_task_completed("sync_task", "proj-1", "scen-1"))

                cache_store.bump_write_epoch()
                self.assertFalse(cache_store.is_scenario_task_completed("sync_task", "proj-1", "scen-1"))


class MediaCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        cache_store.clear_all_caches()

    def tearDown(self) -> None:
        cache_store.clear_all_caches()

    def test_cached_image_bytes_and_data_url_resize_and_invalidate_on_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            img_path = Path(tmpdir) / "sample.png"
            img = Image.new("RGBA", (1600, 1200), (20, 120, 220, 255))
            img.save(img_path, format="PNG")

            webp_bytes = media_cache.cached_image_bytes(
                img_path,
                max_dim=400,
                output_format="WEBP",
                quality=80,
            )
            self.assertIsNotNone(webp_bytes)
            assert webp_bytes is not None
            with Image.open(BytesIO(webp_bytes)) as decoded:
                self.assertEqual(decoded.format, "WEBP")
                self.assertLessEqual(max(decoded.size), 400)

            data_url = media_cache.cached_image_data_url(
                img_path,
                max_dim=400,
                output_format="WEBP",
                quality=80,
            )
            self.assertIsNotNone(data_url)
            assert data_url is not None
            self.assertTrue(data_url.startswith("data:image/webp;base64,"))

            # Modify image file and mtime; verify cache invalidates automatically
            img2 = Image.new("RGBA", (800, 800), (220, 40, 40, 255))
            img2.save(img_path, format="PNG")
            stat = img_path.stat()
            os.utime(img_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))

            data_url_2 = media_cache.cached_image_data_url(
                img_path,
                max_dim=400,
                output_format="WEBP",
                quality=80,
            )
            self.assertNotEqual(data_url, data_url_2)


if __name__ == "__main__":
    unittest.main()
