"""Compressed in-memory LRU cache forPAAG store queries and heavy computations."""

from __future__ import annotations

from collections import OrderedDict
import functools
import hashlib
import os
from pathlib import Path
import pickle
import sqlite3
import threading
from typing import Any, Callable, TypeVar
import zlib

try:
    import streamlit as st
except Exception:  # pragma: no cover
    st = None  # type: ignore[assignment]

F = TypeVar("F", bound=Callable[..., Any])

DEFAULT_MAX_CACHE_BYTES = 128 * 1024 * 1024  # 128 MB compressed cap
DEFAULT_MAX_CACHE_ENTRIES = 2048
ZLIB_COMPRESSION_LEVEL = 1  # Fast compression (~300+ MB/s) with 70-85% reduction on DataFrames


class CompressedLRUCache:
    """Thread-safe LRU cache that stores zlib-compressed pickled payloads under a strict byte cap."""

    def __init__(
        self,
        max_bytes: int = DEFAULT_MAX_CACHE_BYTES,
        max_entries: int = DEFAULT_MAX_CACHE_ENTRIES,
        compression_level: int = ZLIB_COMPRESSION_LEVEL,
    ) -> None:
        self.max_bytes = max(1024 * 1024, int(max_bytes))
        self.max_entries = max(32, int(max_entries))
        self.compression_level = int(compression_level)
        self._lock = threading.RLock()
        self._entries: OrderedDict[Any, tuple[bytes, int, int]] = OrderedDict()
        self._total_compressed_bytes = 0
        self._total_uncompressed_bytes = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(self, key: Any) -> tuple[bool, Any]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return False, None
            self._entries.move_to_end(key)
            compressed_blob, _, _ = entry
            self.hits += 1
        try:
            raw_bytes = zlib.decompress(compressed_blob)
            return True, pickle.loads(raw_bytes)
        except Exception:
            with self._lock:
                removed = self._entries.pop(key, None)
                if removed is not None:
                    self._total_compressed_bytes -= removed[1]
                    self._total_uncompressed_bytes -= removed[2]
            return False, None

    def set(self, key: Any, value: Any) -> bool:
        try:
            raw_bytes = pickle.dumps(value, protocol=5)
            compressed_blob = zlib.compress(raw_bytes, level=self.compression_level)
        except Exception:
            return False

        comp_size = len(compressed_blob)
        raw_size = len(raw_bytes)
        if comp_size > self.max_bytes // 2:
            # Avoid letting a single huge object evict the entire working set.
            return False

        with self._lock:
            existing = self._entries.pop(key, None)
            if existing is not None:
                self._total_compressed_bytes -= existing[1]
                self._total_uncompressed_bytes -= existing[2]

            while (
                self._entries
                and (
                    self._total_compressed_bytes + comp_size > self.max_bytes
                    or len(self._entries) >= self.max_entries
                )
            ):
                _, (_, old_comp, old_raw) = self._entries.popitem(last=False)
                self._total_compressed_bytes -= old_comp
                self._total_uncompressed_bytes -= old_raw
                self.evictions += 1

            self._entries[key] = (compressed_blob, comp_size, raw_size)
            self._total_compressed_bytes += comp_size
            self._total_uncompressed_bytes += raw_size
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._total_compressed_bytes = 0
            self._total_uncompressed_bytes = 0

    def stats(self) -> dict[str, int | float]:
        with self._lock:
            ratio = (
                round(self._total_uncompressed_bytes / self._total_compressed_bytes, 2)
                if self._total_compressed_bytes > 0
                else 1.0
            )
            return {
                "entries": len(self._entries),
                "compressed_bytes": self._total_compressed_bytes,
                "uncompressed_bytes": self._total_uncompressed_bytes,
                "compression_ratio": ratio,
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "max_bytes": self.max_bytes,
            }


_FALLBACK_DATA_CACHE = CompressedLRUCache()


def get_data_cache() -> CompressedLRUCache:
    """Return the active compressed LRU cache instance."""
    return _FALLBACK_DATA_CACHE


_EPOCH_LOCK = threading.RLock()
_DB_WRITE_EPOCH = 0
_SCOPE_WRITE_EPOCHS: dict[str, int] = {
    "catalog": 0,
    "scenario": 0,
}
_SCENARIO_MIGRATION_GUARD: set[tuple[Any, ...]] = set()

# Scenario-scoped and operational tables whose modifications do not alter
# project-wide Product Architecture, Parts Catalog, Models, or Fishbone structure.
SCENARIO_ONLY_TABLES: frozenset[str] = frozenset(
    {
        "planning_scenarios",
        "part_scenario_activity",
        "work_elements",
        "safety_requirements",
        "yamazumi_areas",
        "yamazumi_pitches",
        "yamazumi_elements",
        "yamazumi_work_regions",
        "assembly_scenario_policies",
        "work_element_material_groups",
        "work_element_material_options",
        "process_part_groups",
        "process_part_options",
        "ergonomics_reviews",
        "ergonomics_review_hazard_selections",
        "ergonomics_visual_media",
        "process_visual_media",
        "process_visual_media_tags",
        "quality_requirement_assignments",
        "pfmea_entries",
        "pfmea_effects",
        "pfmea_causes",
        "pfmea_controls",
        "pfmea_risk_rows",
        "pfmea_actions",
        "pfmea_failure_effects",
        "pfmea_failure_causes",
        "pfmea_prevention_controls",
        "pfmea_detection_controls",
        "pfmea_recommended_actions",
        "control_plan_items",
        "control_plan_entries",
        "control_plan_characteristics",
        "equipment_placements",
        "equipment_process_links",
        "conveyor_zones",
        "layout_plans",
        "layout_revisions",
        "layout_layers",
        "layout_shapes",
        "layout_section_pitch_standards",
        "layout_custom_stencils",
        "audit_log",
        "table_view_preferences",
    }
)


def bump_write_epoch(
    scope: str | None = None,
    *,
    modified_tables: set[str] | frozenset[str] | None = None,
) -> int:
    """Increment the global and domain-scoped write epochs whenever a SQLite transaction commits."""
    global _DB_WRITE_EPOCH
    with _EPOCH_LOCK:
        _DB_WRITE_EPOCH += 1
        normalized_tables = {str(t).strip().lower() for t in (modified_tables or ()) if str(t).strip()}
        if scope == "scenario" or (
            scope is None
            and normalized_tables
            and normalized_tables.issubset(SCENARIO_ONLY_TABLES)
        ):
            _SCOPE_WRITE_EPOCHS["scenario"] = _SCOPE_WRITE_EPOCHS.get("scenario", 0) + 1
        elif scope == "catalog":
            _SCOPE_WRITE_EPOCHS["catalog"] = _SCOPE_WRITE_EPOCHS.get("catalog", 0) + 1
            _SCOPE_WRITE_EPOCHS["scenario"] = _SCOPE_WRITE_EPOCHS.get("scenario", 0) + 1
        else:
            for key in tuple(_SCOPE_WRITE_EPOCHS):
                _SCOPE_WRITE_EPOCHS[key] += 1
            if scope and scope not in _SCOPE_WRITE_EPOCHS:
                _SCOPE_WRITE_EPOCHS[scope] = 1
        return _DB_WRITE_EPOCH


def get_write_epoch(scope: str = "all") -> int:
    with _EPOCH_LOCK:
        if scope == "all" or not scope:
            return _DB_WRITE_EPOCH
        return _SCOPE_WRITE_EPOCHS.get(scope, _DB_WRITE_EPOCH)


def clear_all_caches() -> None:
    """Clear all cached store data and migration guards."""
    bump_write_epoch()
    with _EPOCH_LOCK:
        _SCENARIO_MIGRATION_GUARD.clear()
    _FALLBACK_DATA_CACHE.clear()
    try:
        get_data_cache().clear()
    except Exception:
        pass


def _file_stat_signature(path: Path) -> tuple[int, int]:
    try:
        st_res = os.stat(path)
        return (int(st_res.st_mtime_ns), int(st_res.st_size))
    except OSError:
        return (0, 0)


def current_db_state_token(scope: str = "all") -> tuple[Any, ...] | None:
    """Return a fast state token for the active database, or None if mocked."""
    from utils import db_core

    if not db_core.is_cacheable_runtime():
        return None
    db_path = Path(db_core.DB_PATH)
    try:
        resolved = str(db_path.resolve())
    except OSError:
        resolved = str(db_path)
    epoch = get_write_epoch(scope)
    if scope and scope != "all":
        return (
            resolved,
            scope,
            epoch,
            db_core.get_runtime_revision(),
        )
    main_sig = _file_stat_signature(db_path)
    wal_sig = _file_stat_signature(Path(f"{db_path}-wal"))
    return (
        resolved,
        epoch,
        db_core.get_runtime_revision(),
        main_sig,
        wal_sig,
    )


def _normalize_cache_arg(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        if len(value) <= 256:
            return bytes(value)
        return ("__bytes__", len(value), hashlib.sha256(value).hexdigest())
    if isinstance(value, Path):
        return ("__path__", str(value))
    if isinstance(value, sqlite3.Connection):
        raise TypeError("sqlite3.Connection is not cacheable")
    if callable(getattr(value, "getvalue", None)):
        digest = uploaded_file_digest(value)
        if digest is not None:
            return ("__upload__", digest)
    if hasattr(value, "columns") and hasattr(value, "shape") and hasattr(value, "to_numpy"):
        try:
            raw_df = pickle.dumps(value, protocol=5)
            return ("__df__", value.shape, hashlib.sha256(raw_df).hexdigest())
        except Exception as exc:
            raise TypeError("DataFrame is not cacheable") from exc
    if isinstance(value, (tuple, list)):
        return tuple(_normalize_cache_arg(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return ("__set__", tuple(sorted((_normalize_cache_arg(item) for item in value), key=repr)))
    if isinstance(value, dict):
        return (
            "__dict__",
            tuple(
                sorted(
                    ((_normalize_cache_arg(k), _normalize_cache_arg(v)) for k, v in value.items()),
                    key=lambda item: repr(item[0]),
                )
            ),
        )
    raise TypeError(f"Unsupported cache key type: {type(value)!r}")


def cached_store_read(
    fn: F | None = None,
    *,
    scope: str = "all",
) -> Any:
    """Cache read-only store function results in the compressed LRU memory pool."""

    def _decorate(target_fn: F) -> F:
        qualname = f"{target_fn.__module__}.{target_fn.__qualname__}"

        @functools.wraps(target_fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("_conn") is not None:
                return target_fn(*args, **kwargs)
            state_token = current_db_state_token(scope)
            if state_token is None:
                return target_fn(*args, **kwargs)
            try:
                norm_args = _normalize_cache_arg(args)
                norm_kwargs = _normalize_cache_arg(kwargs) if kwargs else ()
            except TypeError:
                return target_fn(*args, **kwargs)

            cache_key = ("store_read", state_token, qualname, norm_args, norm_kwargs)
            cache = get_data_cache()
            hit, cached_val = cache.get(cache_key)
            if hit:
                return cached_val
            result = target_fn(*args, **kwargs)
            post_token = current_db_state_token(scope) or state_token
            if post_token != state_token:
                cache_key = ("store_read", post_token, qualname, norm_args, norm_kwargs)
            cache.set(cache_key, result)
            return result

        return wrapper  # type: ignore[return-value]

    if fn is not None:
        return _decorate(fn)
    return _decorate


def cached_computation(
    namespace: str = "default",
    *,
    scope: str | None = None,
) -> Callable[[F], F]:
    """Cache pure/expensive computations (such as workbook parsing) by normalized arguments."""
    ns = scope or namespace

    def decorator(fn: F) -> F:
        qualname = f"{fn.__module__}.{fn.__qualname__}"

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                norm_args = _normalize_cache_arg(args)
                norm_kwargs = _normalize_cache_arg(kwargs) if kwargs else ()
            except TypeError:
                return fn(*args, **kwargs)
            cache_key = ("computation", ns, qualname, norm_args, norm_kwargs)
            cache = get_data_cache()
            hit, cached_val = cache.get(cache_key)
            if hit:
                return cached_val
            result = fn(*args, **kwargs)
            cache.set(cache_key, result)
            return result

        return wrapper  # type: ignore[return-value]

    return decorator


def uploaded_file_digest(uploaded: Any) -> tuple[str, int, str] | None:
    """Compute a fast content identity (name, size, sha256) for a Streamlit UploadedFile or BytesIO."""
    if uploaded is None:
        return None
    try:
        if hasattr(uploaded, "getvalue"):
            raw_bytes = uploaded.getvalue()
        elif isinstance(uploaded, (bytes, bytearray)):
            raw_bytes = bytes(uploaded)
        else:
            return None
        name = str(getattr(uploaded, "name", "uploaded"))
        digest = hashlib.sha256(raw_bytes).hexdigest()
        return (name, len(raw_bytes), digest)
    except Exception:
        return None


def is_scenario_task_completed(task_name: str, *scope_keys: Any, extra_token: Any = None, **kwargs: Any) -> bool:
    """Return True if a one-time scenario migration/cleanup has already run for the current DB state."""
    state_token = current_db_state_token()
    if state_token is None:
        return False
    key = (
        task_name,
        state_token,
        *_normalize_cache_arg(scope_keys),
        _normalize_cache_arg(extra_token),
        _normalize_cache_arg(kwargs) if kwargs else None,
    )
    with _EPOCH_LOCK:
        return key in _SCENARIO_MIGRATION_GUARD


def mark_scenario_task_completed(task_name: str, *scope_keys: Any, extra_token: Any = None, **kwargs: Any) -> None:
    """Mark a one-time scenario migration/cleanup as completed for the active DB state."""
    state_token = current_db_state_token()
    if state_token is None:
        return
    key = (
        task_name,
        state_token,
        *_normalize_cache_arg(scope_keys),
        _normalize_cache_arg(extra_token),
        _normalize_cache_arg(kwargs) if kwargs else None,
    )
    with _EPOCH_LOCK:
        _SCENARIO_MIGRATION_GUARD.add(key)
