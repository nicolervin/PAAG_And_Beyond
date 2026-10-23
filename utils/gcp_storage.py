"""Google Cloud Storage (GCS) persistence and cross-platform upload path management for PAAG.

When `PAAG_GCS_BUCKET` is configured (e.g. on Google Cloud Run), this module:
1. Hydrates `paag.db` and `data/uploads/` from GCS once on container startup.
2. Creates transactionally consistent SQLite snapshots via `sqlite3.Connection.backup()`
   and syncs `paag.db` plus `data/uploads/` to GCS in the background after writes.
3. Flushes any pending sync synchronously on `atexit` or Cloud Run `SIGTERM`.
4. Rebases Windows/Linux upload file paths across environments so CAD/process images
   work seamlessly whether authored locally on Windows or in a Linux container.
"""

from __future__ import annotations

import atexit
from contextlib import closing
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import tempfile
import threading
from typing import Any

logger = logging.getLogger(__name__)

_SYNC_LOCK = threading.RLock()
_BOOTSTRAPPED_TARGETS: set[tuple[str, str, str]] = set()
_UPLOADED_FILE_SIGNATURES: dict[str, tuple[int, int]] = {}
_LAST_SYNCED_DB_SIGNATURE: tuple[int, int, int, int] | None = None
_PENDING_SYNC_TIMER: threading.Timer | None = None
_PENDING_SYNC_ARGS: tuple[Path, Path] | None = None
_SHUTDOWN_HOOKS_REGISTERED = False
_GCS_CLIENT_CACHE: dict[str, Any] = {}

_UPLOAD_PATH_MARKER_RE = re.compile(r"(?:^|[\\/])uploads[\\/]([^\\/]+)$", re.IGNORECASE)


def gcs_bucket_name() -> str:
    """Return the configured GCS bucket name, or empty string if GCS sync is disabled."""
    return str(os.environ.get("PAAG_GCS_BUCKET") or "").strip()


def gcs_object_prefix() -> str:
    """Return the normalized object prefix inside the GCS bucket (default: 'paag')."""
    raw = str(os.environ.get("PAAG_GCS_PREFIX", "paag") or "").strip().strip("/")
    return raw


def gcs_sync_debounce_seconds() -> float:
    """Return the debounce interval in seconds for background GCS syncs."""
    try:
        val = float(os.environ.get("PAAG_GCS_SYNC_DEBOUNCE_S", "1.5"))
        return max(0.0, val)
    except (TypeError, ValueError):
        return 1.5


def is_gcs_sync_enabled() -> bool:
    """Return True when a GCS bucket is configured for state persistence."""
    return bool(gcs_bucket_name())


def _blob_name(relative_path: str) -> str:
    prefix = gcs_object_prefix()
    clean_rel = relative_path.lstrip("/")
    return f"{prefix}/{clean_rel}" if prefix else clean_rel


def _get_gcs_bucket():
    """Return the `google.cloud.storage.Bucket` handle, or None if unavailable."""
    bucket_name = gcs_bucket_name()
    if not bucket_name:
        return None
    with _SYNC_LOCK:
        cached = _GCS_CLIENT_CACHE.get(bucket_name)
        if cached is not None:
            return cached
        try:
            from google.cloud import storage  # type: ignore[import-untyped]

            client = storage.Client()
            bucket = client.bucket(bucket_name)
            _GCS_CLIENT_CACHE[bucket_name] = bucket
            return bucket
        except Exception as exc:
            logger.warning("GCS client initialization failed for bucket %r: %s", bucket_name, exc)
            return None


def _file_sig(path: Path) -> tuple[int, int]:
    try:
        st_res = path.stat()
        return (int(st_res.st_mtime_ns), int(st_res.st_size))
    except OSError:
        return (0, 0)


def _db_composite_sig(db_path: Path) -> tuple[int, int, int, int]:
    main_mtime, main_size = _file_sig(db_path)
    wal_mtime, wal_size = _file_sig(Path(f"{db_path}-wal"))
    return (main_mtime, main_size, wal_mtime, wal_size)


def create_consistent_sqlite_snapshot(source_db_path: Path, target_snapshot_path: Path) -> bool:
    """Create a WAL-consistent single-file SQLite backup using SQLite's online backup API."""
    if not source_db_path.exists() or not source_db_path.is_file():
        return False
    target_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(f"file:{source_db_path.as_posix()}?mode=ro", uri=True, timeout=30)) as src_conn:
            with closing(sqlite3.connect(target_snapshot_path, timeout=30)) as dst_conn:
                src_conn.backup(dst_conn)
                dst_conn.execute("PRAGMA journal_mode = DELETE")
                check = dst_conn.execute("PRAGMA quick_check").fetchone()
                if not check or str(check[0]).lower() != "ok":
                    raise RuntimeError("SQLite snapshot failed PRAGMA quick_check")
        return target_snapshot_path.exists() and target_snapshot_path.stat().st_size > 0
    except Exception as exc:
        logger.warning("Failed to create consistent SQLite snapshot from %s: %s", source_db_path, exc)
        target_snapshot_path.unlink(missing_ok=True)
        return False


def bootstrap_from_gcs_if_needed(db_path: Path, upload_dir: Path) -> bool:
    """Hydrate `paag.db` and `uploads/` from GCS once per process startup when configured."""
    bucket_name = gcs_bucket_name()
    if not bucket_name:
        return False

    skip_restore = str(os.environ.get("PAAG_GCS_SKIP_RESTORE") or "").strip().lower() in {"1", "true", "yes"}
    if skip_restore:
        return False

    target_key = (bucket_name, str(db_path), str(upload_dir))
    with _SYNC_LOCK:
        if target_key in _BOOTSTRAPPED_TARGETS:
            return False
        _BOOTSTRAPPED_TARGETS.add(target_key)
        _register_shutdown_hooks_locked()

    bucket = _get_gcs_bucket()
    if bucket is None:
        return False

    restored_any = False
    db_path.parent.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 1. Restore SQLite database from GCS if remote snapshot exists
    db_blob_key = _blob_name("paag.db")
    try:
        db_blob = bucket.blob(db_blob_key)
        if db_blob.exists():
            fd, tmp_name = tempfile.mkstemp(prefix=".paag_gcs_restore_", suffix=".db", dir=str(db_path.parent))
            os.close(fd)
            tmp_path = Path(tmp_name)
            try:
                db_blob.download_to_filename(str(tmp_path))
                if tmp_path.exists() and tmp_path.stat().st_size > 0:
                    # Remove stale WAL/SHM sidecars before replacing main database file
                    for suffix in ("-wal", "-shm"):
                        Path(f"{db_path}{suffix}").unlink(missing_ok=True)
                    shutil.move(str(tmp_path), str(db_path))
                    restored_any = True
            finally:
                tmp_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Failed to restore paag.db from gs://%s/%s: %s", bucket_name, db_blob_key, exc)

    # 2. Hydrate uploaded files from GCS
    uploads_prefix = _blob_name("uploads/")
    try:
        for blob in bucket.list_blobs(prefix=uploads_prefix):
            rel_name = str(blob.name)[len(uploads_prefix) :].strip("/")
            if not rel_name or "/" in rel_name or "\\" in rel_name:
                continue
            local_file = upload_dir / rel_name
            remote_size = int(getattr(blob, "size", 0) or 0)
            if local_file.exists() and local_file.is_file():
                try:
                    if remote_size > 0 and local_file.stat().st_size == remote_size:
                        with _SYNC_LOCK:
                            _UPLOADED_FILE_SIGNATURES[rel_name] = _file_sig(local_file)
                        continue
                except OSError:
                    pass
            fd, tmp_upload = tempfile.mkstemp(prefix=".upload_restore_", dir=str(upload_dir))
            os.close(fd)
            tmp_upload_path = Path(tmp_upload)
            try:
                blob.download_to_filename(str(tmp_upload_path))
                shutil.move(str(tmp_upload_path), str(local_file))
                with _SYNC_LOCK:
                    _UPLOADED_FILE_SIGNATURES[rel_name] = _file_sig(local_file)
                restored_any = True
            finally:
                tmp_upload_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Failed to restore uploads from gs://%s/%s: %s", bucket_name, uploads_prefix, exc)

    with _SYNC_LOCK:
        global _LAST_SYNCED_DB_SIGNATURE
        if db_path.exists():
            _LAST_SYNCED_DB_SIGNATURE = _db_composite_sig(db_path)

    return restored_any


def ensure_upload_file_local(candidate_path: Path, upload_dir: Path | None = None) -> bool:
    """Ensure an upload file exists locally, pulling it on demand from GCS if needed."""
    if candidate_path.exists() and candidate_path.is_file():
        return True
    bucket = _get_gcs_bucket()
    if bucket is None:
        return False
    try:
        effective_upload_dir = (upload_dir or candidate_path.parent).resolve()
        if candidate_path.resolve().parent != effective_upload_dir:
            return False
        filename = candidate_path.name
        blob = bucket.blob(_blob_name(f"uploads/{filename}"))
        if not blob.exists():
            return False
        effective_upload_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_upload = tempfile.mkstemp(prefix=".upload_lazy_", dir=str(effective_upload_dir))
        os.close(fd)
        tmp_path = Path(tmp_upload)
        try:
            blob.download_to_filename(str(tmp_path))
            shutil.move(str(tmp_path), str(candidate_path))
            with _SYNC_LOCK:
                _UPLOADED_FILE_SIGNATURES[filename] = _file_sig(candidate_path)
            return True
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.debug("On-demand GCS fetch for %s did not succeed: %s", candidate_path, exc)
        return False


def sync_state_to_gcs_now(db_path: Path, upload_dir: Path, *, force_db: bool = False) -> bool:
    """Synchronously push any changed SQLite state and upload files to GCS."""
    bucket = _get_gcs_bucket()
    if bucket is None:
        return False

    global _LAST_SYNCED_DB_SIGNATURE
    synced_anything = False

    with _SYNC_LOCK:
        # 1. Sync SQLite database via safe online backup snapshot
        if db_path.exists() and db_path.is_file():
            current_sig = _db_composite_sig(db_path)
            if force_db or current_sig != _LAST_SYNCED_DB_SIGNATURE:
                fd, tmp_name = tempfile.mkstemp(
                    prefix=".paag_gcs_snap_", suffix=".db", dir=str(db_path.parent)
                )
                os.close(fd)
                tmp_snapshot = Path(tmp_name)
                try:
                    if create_consistent_sqlite_snapshot(db_path, tmp_snapshot):
                        blob = bucket.blob(_blob_name("paag.db"))
                        blob.upload_from_filename(
                            str(tmp_snapshot), content_type="application/vnd.sqlite3"
                        )
                        _LAST_SYNCED_DB_SIGNATURE = _db_composite_sig(db_path)
                        synced_anything = True
                except Exception as exc:
                    logger.warning("Failed to upload paag.db snapshot to GCS: %s", exc)
                finally:
                    tmp_snapshot.unlink(missing_ok=True)

        # 2. Sync new/modified/deleted files in UPLOAD_DIR
        if upload_dir.exists() and upload_dir.is_dir():
            current_files: dict[str, Path] = {}
            for entry in upload_dir.iterdir():
                if entry.is_file() and not entry.name.startswith("."):
                    current_files[entry.name] = entry

            for fname, fpath in current_files.items():
                sig = _file_sig(fpath)
                if _UPLOADED_FILE_SIGNATURES.get(fname) == sig:
                    continue
                try:
                    blob = bucket.blob(_blob_name(f"uploads/{fname}"))
                    blob.upload_from_filename(str(fpath))
                    _UPLOADED_FILE_SIGNATURES[fname] = sig
                    synced_anything = True
                except Exception as exc:
                    logger.warning("Failed to upload %s to GCS: %s", fname, exc)

            sync_deletes = str(os.environ.get("PAAG_GCS_SYNC_DELETES", "1") or "1").strip().lower() not in {
                "0",
                "false",
                "no",
            }
            if sync_deletes:
                removed_names = set(_UPLOADED_FILE_SIGNATURES) - set(current_files)
                for fname in removed_names:
                    _UPLOADED_FILE_SIGNATURES.pop(fname, None)
                    try:
                        blob = bucket.blob(_blob_name(f"uploads/{fname}"))
                        if blob.exists():
                            blob.delete()
                            synced_anything = True
                    except Exception as exc:
                        logger.debug("Failed to delete removed upload %s from GCS: %s", fname, exc)

    return synced_anything


def _run_scheduled_sync() -> None:
    global _PENDING_SYNC_TIMER, _PENDING_SYNC_ARGS
    with _SYNC_LOCK:
        args = _PENDING_SYNC_ARGS
        _PENDING_SYNC_TIMER = None
        _PENDING_SYNC_ARGS = None
    if args is not None:
        sync_state_to_gcs_now(args[0], args[1])


def schedule_gcs_sync(db_path: Path, upload_dir: Path) -> None:
    """Schedule a debounced non-blocking background sync of `paag.db` and `uploads/` to GCS."""
    if not is_gcs_sync_enabled():
        return
    debounce = gcs_sync_debounce_seconds()
    if debounce <= 0:
        sync_state_to_gcs_now(db_path, upload_dir)
        return

    global _PENDING_SYNC_TIMER, _PENDING_SYNC_ARGS
    with _SYNC_LOCK:
        _register_shutdown_hooks_locked()
        _PENDING_SYNC_ARGS = (Path(db_path), Path(upload_dir))
        if _PENDING_SYNC_TIMER is not None:
            _PENDING_SYNC_TIMER.cancel()
        timer = threading.Timer(debounce, _run_scheduled_sync)
        timer.daemon = True
        _PENDING_SYNC_TIMER = timer
        timer.start()


def flush_pending_gcs_sync() -> bool:
    """Immediately execute any pending debounced GCS sync (used on shutdown/SIGTERM or tests)."""
    global _PENDING_SYNC_TIMER, _PENDING_SYNC_ARGS
    with _SYNC_LOCK:
        if _PENDING_SYNC_TIMER is not None:
            _PENDING_SYNC_TIMER.cancel()
            _PENDING_SYNC_TIMER = None
        args = _PENDING_SYNC_ARGS
        _PENDING_SYNC_ARGS = None
    if args is not None:
        return sync_state_to_gcs_now(args[0], args[1], force_db=True)
    return False


def _register_shutdown_hooks_locked() -> None:
    global _SHUTDOWN_HOOKS_REGISTERED
    if _SHUTDOWN_HOOKS_REGISTERED:
        return
    _SHUTDOWN_HOOKS_REGISTERED = True
    atexit.register(flush_pending_gcs_sync)
    if threading.current_thread() is threading.main_thread():
        for sig_name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                prev_handler = signal.getsignal(sig)

                def _handle_signal(signum, frame, _prev=prev_handler):
                    try:
                        flush_pending_gcs_sync()
                    finally:
                        if callable(_prev):
                            _prev(signum, frame)
                        elif _prev == signal.SIG_DFL:
                            signal.signal(signum, signal.SIG_DFL)
                            os.kill(os.getpid(), signum)

                signal.signal(sig, _handle_signal)
            except Exception:
                pass


def rebase_upload_path_str(raw_path: str | None, upload_dir: Path) -> str:
    """Normalize a stored Windows or Linux upload file path to the active runtime `upload_dir`.

    Preserves empty strings and HTTP/HTTPS URLs unchanged. If `raw_path` already exists
    on disk as written, returns it unchanged; otherwise, if it points into an `uploads/`
    directory from another OS/container path, rebases it onto `upload_dir / <filename>`.
    """
    cleaned = str(raw_path or "").strip()
    if not cleaned or cleaned.startswith(("http://", "https://", "data:")):
        return cleaned

    try:
        direct = Path(cleaned)
        if direct.exists() and direct.is_file():
            return cleaned
    except OSError:
        pass

    match = _UPLOAD_PATH_MARKER_RE.search(cleaned)
    filename = match.group(1) if match else ""
    if not filename and ("/" not in cleaned and "\\" not in cleaned):
        filename = cleaned
    if not filename:
        return cleaned

    rebased = upload_dir / filename
    return str(rebased)


def resolve_upload_path(raw_path: str | Path | None, upload_dir: Path) -> Path | None:
    """Resolve an upload path across Windows/Linux environments and lazy-fetch from GCS if needed."""
    if not raw_path:
        return None
    raw_str = str(raw_path).strip()
    if not raw_str or raw_str.startswith(("http://", "https://", "data:")):
        return None

    try:
        candidate = Path(raw_str)
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    except OSError:
        pass

    rebased_str = rebase_upload_path_str(raw_str, upload_dir)
    try:
        rebased = Path(rebased_str)
        if rebased.exists() and rebased.is_file():
            return rebased.resolve()
        if ensure_upload_file_local(rebased, upload_dir) and rebased.exists() and rebased.is_file():
            return rebased.resolve()
    except OSError:
        pass
    return None
