"""App-wide 30-day Recycle Bin persistence, snapshot diffing, and restoration."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys as _sys
import threading
from typing import Any
from uuid import uuid4

import pandas as pd

import importlib as _importlib
from utils.cache_store import (
    cached_store_read,
    is_schema_initialized,
    mark_schema_initialized,
)


class _DbCoreProxy:
    def __getattr__(self, name: str):
        mod = _sys.modules.get("utils.db_core") or _importlib.import_module("utils.db_core")
        return getattr(mod, name)


_db_core = _DbCoreProxy()

RECYCLE_BIN_RETENTION_DAYS = 30

_CAPTURE_LOCK = threading.Lock()
_ACTIVE_CAPTURE_CONN_IDS: set[int] = set()

# Exclude audit and transient UI preference tables from normal entity snapshots
# so restoring an item does not roll back audit history or user table filters.
_EXCLUDED_ENTITY_SNAPSHOT_TABLES = frozenset(
    {
        "audit_log",
        "project_transfer_events",
        "table_view_preferences",
        "recycle_bin_items",
    }
)

_TABLE_HUMAN_LABELS: dict[str, str] = {
    "projects": "project",
    "planning_scenarios": "planning scenario",
    "parts": "part",
    "part_scenario_activity": "part scenario status",
    "work_elements": "Process step",
    "concerns": "concern",
    "fishbone_nodes": "Fishbone node",
    "pits_bom_imports": "PITS BOM import",
    "part_images": "part image",
    "pits_records": "PITS record",
    "pits_record_revisions": "PITS revision",
    "project_models": "model",
    "complexity_features": "complexity feature",
    "model_feature_values": "model feature value",
    "part_feature_rules": "part feature rule",
    "assembly_sections": "Fishbone section",
    "assembly_section_connections": "section connection",
    "fishbone_part_assignments": "Fishbone part placement",
    "pits_bom_occurrences": "PITS BOM occurrence",
    "pits_bom_occurrence_revisions": "PITS BOM occurrence revision",
    "pits_bom_occurrence_concerns": "PITS BOM concern link",
    "conveyor_zones": "conveyor zone",
    "yamazumi_areas": "Yamazumi area",
    "yamazumi_pitches": "Yamazumi pitch",
    "yamazumi_elements": "Yamazumi element",
    "yamazumi_work_regions": "work region",
    "manufacturing_assemblies": "manufacturing assembly",
    "manufacturing_assembly_components": "assembly component",
    "manufacturing_assembly_feature_rules": "assembly feature rule",
    "manufacturing_assembly_images": "assembly image",
    "assembly_grid_categories": "Assembly Grid category",
    "assembly_grid_model_mappings": "Assembly Grid model mapping",
    "assembly_grid_feature_visibility": "Assembly Grid feature visibility",
    "assembly_scenario_policies": "assembly scenario policy",
    "work_element_material_groups": "material group",
    "work_element_material_options": "material option",
    "process_part_groups": "Process part group",
    "process_part_options": "Process part option",
    "process_visual_media": "Process visual aid",
    "process_visual_media_tags": "Process visual aid tag",
    "safety_requirements": "safety requirement",
    "ergonomic_hazard_options": "ergonomic hazard option",
    "ergonomics_reviews": "ergonomics review",
    "ergonomics_review_hazard_selections": "ergonomics hazard selection",
    "ergonomics_visual_media": "ergonomics visual media",
    "quality_requirements": "quality requirement",
    "quality_requirement_assignments": "quality requirement assignment",
    "quality_requirement_torque_details": "torque specification",
    "quality_requirement_types": "quality requirement type",
    "equipment_types": "equipment type",
    "equipment_type_function_links": "equipment type function link",
    "equipment_assets": "equipment asset",
    "equipment_function_links": "equipment function link",
    "equipment_placements": "equipment placement",
    "equipment_process_links": "equipment Process link",
    "equipment_torque_requirement_links": "equipment torque link",
    "layout_plans": "layout plan",
    "layout_revisions": "layout revision",
    "layout_layers": "layout layer",
    "layout_section_pitch_standards": "layout pitch standard",
    "layout_shapes": "layout shape",
    "layout_custom_stencils": "layout custom stencil",
    "pfmea_assignees": "PFMEA assignee",
    "pfmea_entries": "PFMEA row",
    "pfmea_effects": "PFMEA effect",
    "pfmea_causes": "PFMEA cause",
    "pfmea_risk_rows": "PFMEA risk row",
    "pfmea_actions": "PFMEA action",
    "pfmea_prevention_options": "PFMEA prevention option",
    "pfmea_detection_options": "PFMEA detection option",
    "pfmea_prevention_selections": "PFMEA prevention selection",
    "pfmea_detection_selections": "PFMEA detection selection",
    "pfmea_patterns": "PFMEA pattern",
    "pfmea_pattern_effects": "PFMEA pattern effect",
    "pfmea_pattern_causes": "PFMEA pattern cause",
    "pfmea_pattern_actions": "PFMEA pattern action",
    "pfmea_pattern_prevention_sources": "PFMEA pattern prevention source",
    "pfmea_pattern_detection_sources": "PFMEA pattern detection source",
    "control_plan_items": "Control Plan row",
    "control_method_catalog": "Control Plan method",
    "app_feedback": "feedback item",
}


def init_recycle_bin_schema(conn: sqlite3.Connection) -> None:
    """Create the app-wide recycle_bin_items table and indexes if absent."""
    if is_schema_initialized(conn, "recycle_bin_schema_v1", "recycle_bin_items"):
        return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS recycle_bin_items (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            project_name TEXT NOT NULL DEFAULT '',
            scenario_id TEXT,
            scenario_name TEXT NOT NULL DEFAULT '',
            entity_type TEXT NOT NULL,
            entity_table TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            entity_label TEXT NOT NULL DEFAULT '',
            summary_text TEXT NOT NULL DEFAULT '',
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            file_paths_json TEXT NOT NULL DEFAULT '[]',
            deleted_by TEXT NOT NULL DEFAULT '',
            deleted_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_recycle_bin_project_deleted
            ON recycle_bin_items(project_id, deleted_at DESC);
        CREATE INDEX IF NOT EXISTS idx_recycle_bin_expires
            ON recycle_bin_items(expires_at);
        """
    )
    mark_schema_initialized(conn, "recycle_bin_schema_v1")


def _expires_at_iso(deleted_at_iso: str, days: int = RECYCLE_BIN_RETENTION_DAYS) -> str:
    try:
        dt = datetime.fromisoformat(str(deleted_at_iso or "").replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.now(_db_core.EASTERN_TIMEZONE).replace(microsecond=0)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(_db_core.EASTERN_TIMEZONE)
    return (dt + timedelta(days=int(days))).replace(microsecond=0).isoformat()


def _table_pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    pk_rows = sorted(
        [(int(row[5]), str(row[1])) for row in info if int(row[5] or 0) > 0],
        key=lambda item: item[0],
    )
    if pk_rows:
        return [name for _, name in pk_rows]
    return [str(row[1]) for row in info]


def _row_pk_tuple(row: dict[str, Any], pk_cols: list[str]) -> tuple[Any, ...]:
    return tuple(row.get(col) for col in pk_cols)


def _snapshot_project_tables(
    conn: sqlite3.Connection,
    project_id: str,
    *,
    include_project_wide_logs: bool = False,
) -> tuple[dict[str, dict[tuple[Any, ...], dict[str, Any]]], dict[str, list[str]]]:
    """Return a keyed snapshot of all tables belonging to project_id."""
    from utils.project_transfer import PROJECT_TRANSFER_TABLES

    existing = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    excluded = (
        {"recycle_bin_items"}
        if include_project_wide_logs
        else _EXCLUDED_ENTITY_SNAPSHOT_TABLES
    )
    raw_tables: dict[str, list[dict[str, Any]]] = {}
    keyed_tables: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = {}
    pk_map: dict[str, list[str]] = {}

    for item in PROJECT_TRANSFER_TABLES:
        table_name = item.name
        if table_name not in existing or table_name in excluded:
            continue
        info = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        columns = [str(row[1]) for row in info]
        pk_cols = _table_pk_columns(conn, table_name)
        pk_map[table_name] = pk_cols

        if table_name == "projects":
            rows = conn.execute(
                "SELECT * FROM projects WHERE id=?", (project_id,)
            ).fetchall()
        elif "project_id" in columns:
            rows = conn.execute(
                f'SELECT * FROM "{table_name}" WHERE project_id=?', (project_id,)
            ).fetchall()
        else:
            parent_rows = raw_tables.get(str(item.parent_table), [])
            parent_values = [
                r.get(item.parent_key)
                for r in parent_rows
                if r.get(item.parent_key) is not None
            ]
            if not parent_values:
                rows = []
            else:
                rows = []
                for idx in range(0, len(parent_values), 900):
                    chunk = parent_values[idx : idx + 900]
                    placeholders = ",".join("?" for _ in chunk)
                    rows.extend(
                        conn.execute(
                            f'SELECT * FROM "{table_name}" WHERE "{item.foreign_key}" IN ({placeholders})',
                            tuple(chunk),
                        ).fetchall()
                    )
        dict_rows = [dict(r) for r in rows]
        raw_tables[table_name] = dict_rows
        keyed_tables[table_name] = {
            _row_pk_tuple(r, pk_cols): r for r in dict_rows
        }
    if "app_feedback" in existing and "app_feedback" not in excluded:
        fb_pk_cols = _table_pk_columns(conn, "app_feedback")
        pk_map["app_feedback"] = fb_pk_cols
        fb_rows = [
            dict(r)
            for r in conn.execute("SELECT * FROM app_feedback").fetchall()
        ]
        raw_tables["app_feedback"] = fb_rows
        keyed_tables["app_feedback"] = {
            _row_pk_tuple(r, fb_pk_cols): r for r in fb_rows
        }
    return keyed_tables, pk_map


def _extract_file_paths_from_diff(
    deleted_rows: dict[str, list[dict[str, Any]]],
    updated_rows: dict[str, list[dict[str, Any]]],
    extra_file_paths: list[str | Path] | None = None,
) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()

    def _add(val: object) -> None:
        raw = str(val or "").strip()
        if raw and raw not in seen:
            seen.add(raw)
            paths.append(raw)

    for rows in deleted_rows.values():
        for row in rows:
            for col, val in row.items():
                if col.endswith("_path") and val:
                    _add(val)
    for updates in updated_rows.values():
        for item in updates:
            changed_before = item.get("changed_before") or {}
            for col, val in changed_before.items():
                if col.endswith("_path") and val:
                    _add(val)
    for extra in extra_file_paths or []:
        _add(extra)
    return paths


def _format_table_count(table: str, count: int) -> str:
    label = _TABLE_HUMAN_LABELS.get(table, table.replace("_", " "))
    if count == 1:
        return f"1 {label}"
    if label.endswith("y") and not label.endswith(("ay", "ey", "oy", "uy")):
        return f"{count} {label[:-1]}ies"
    if label.endswith(("s", "x", "z", "ch", "sh")):
        return f"{count} {label}es"
    return f"{count} {label}s"


def _build_snapshot_summary(
    entity_table: str,
    deleted_rows: dict[str, list[dict[str, Any]]],
    updated_rows: dict[str, list[dict[str, Any]]],
    file_paths: list[str],
    custom_summary: str = "",
) -> str:
    if custom_summary.strip():
        return custom_summary.strip()
    parts: list[str] = []
    primary_count = len(deleted_rows.get(entity_table, []))
    if primary_count > 0:
        parts.append(_format_table_count(entity_table, primary_count))
    child_parts: list[str] = []
    for tbl, rows in deleted_rows.items():
        if tbl == entity_table or not rows:
            continue
        child_parts.append(_format_table_count(tbl, len(rows)))
    if child_parts:
        if len(child_parts) <= 4:
            parts.append("cascaded: " + ", ".join(child_parts))
        else:
            shown = ", ".join(child_parts[:4])
            parts.append(f"cascaded: {shown}, +{len(child_parts) - 4} more tables")
    updated_count = sum(len(rows) for rows in updated_rows.values())
    if updated_count > 0:
        parts.append(
            f"{updated_count} linked reference{'s' if updated_count != 1 else ''} updated"
        )
    if file_paths:
        parts.append(
            f"{len(file_paths)} media file{'s' if len(file_paths) != 1 else ''} preserved"
        )
    return "; ".join(parts) if parts else "Record snapshot captured"


def _resolve_deleted_by(deleted_by: str = "") -> str:
    """Return the explicit editor name, or fall back to the active Streamlit session's current_editor."""
    explicit = str(deleted_by or "").strip()
    if explicit:
        return explicit
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        if get_script_run_ctx(suppress_warning=True) is not None:
            import streamlit as st

            editor = str(st.session_state.get("current_editor") or "").strip()
            if editor:
                return editor
    except Exception:
        pass
    return ""


@contextmanager
def capture_deletion_to_recycle_bin(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    entity_type: str,
    entity_table: str,
    entity_id: str,
    entity_label: str,
    scenario_id: str | None = None,
    deleted_by: str = "",
    extra_file_paths: list[str | Path] | None = None,
    custom_summary: str = "",
):
    """Capture a before/after project snapshot around a delete block and store it in recycle_bin_items."""
    init_recycle_bin_schema(conn)
    conn_id = id(conn)
    with _CAPTURE_LOCK:
        if conn_id in _ACTIVE_CAPTURE_CONN_IDS:
            nested = True
        else:
            nested = False
            _ACTIVE_CAPTURE_CONN_IDS.add(conn_id)
    if nested:
        yield
        return

    try:
        is_project_delete = entity_table == "projects"
        proj_row = conn.execute(
            "SELECT name FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        project_name = str(proj_row["name"] or "") if proj_row else ""

        scenario_name = ""
        if scenario_id:
            scen_row = conn.execute(
                "SELECT name, revision_label FROM planning_scenarios WHERE id=? AND project_id=?",
                (scenario_id, project_id),
            ).fetchone()
            if scen_row:
                s_name = str(scen_row["name"] or "").strip()
                s_rev = str(scen_row["revision_label"] or "").strip()
                scenario_name = f"{s_name} (Rev {s_rev})" if s_rev else s_name

        before_snap, pk_map = _snapshot_project_tables(
            conn, project_id, include_project_wide_logs=is_project_delete
        )

        yield

        deleted_rows: dict[str, list[dict[str, Any]]] = {}
        updated_rows: dict[str, list[dict[str, Any]]] = {}
        inserted_rows: dict[str, list[dict[str, Any]]] = {}

        if is_project_delete:
            for tbl, keyed in before_snap.items():
                if keyed:
                    deleted_rows[tbl] = list(keyed.values())
        else:
            after_snap, _ = _snapshot_project_tables(
                conn, project_id, include_project_wide_logs=False
            )
            for tbl, before_keyed in before_snap.items():
                after_keyed = after_snap.get(tbl, {})
                pk_cols = pk_map.get(tbl, ["id"])

                tbl_deleted: list[dict[str, Any]] = []
                tbl_updated: list[dict[str, Any]] = []
                for pk_tuple, before_row in before_keyed.items():
                    after_row = after_keyed.get(pk_tuple)
                    if after_row is None:
                        tbl_deleted.append(before_row)
                    elif before_row != after_row:
                        changed_cols = [
                            col
                            for col in before_row
                            if before_row.get(col) != after_row.get(col)
                        ]
                        if changed_cols:
                            tbl_updated.append(
                                {
                                    "pk": {col: before_row.get(col) for col in pk_cols},
                                    "changed_before": {
                                        col: before_row.get(col) for col in changed_cols
                                    },
                                    "changed_after": {
                                        col: after_row.get(col) for col in changed_cols
                                    },
                                }
                            )
                if tbl_deleted:
                    deleted_rows[tbl] = tbl_deleted
                if tbl_updated:
                    updated_rows[tbl] = tbl_updated

                tbl_inserted = [
                    {col: after_row.get(col) for col in pk_cols}
                    for pk_tuple, after_row in after_keyed.items()
                    if pk_tuple not in before_keyed
                ]
                if tbl_inserted:
                    inserted_rows[tbl] = tbl_inserted

        file_paths = _extract_file_paths_from_diff(
            deleted_rows, updated_rows, extra_file_paths
        )
        if not deleted_rows and not updated_rows and not inserted_rows and not file_paths:
            return

        deleted_at = _db_core.now_iso()
        expires_at = _expires_at_iso(deleted_at, RECYCLE_BIN_RETENTION_DAYS)
        summary_text = _build_snapshot_summary(
            entity_table, deleted_rows, updated_rows, file_paths, custom_summary
        )
        snapshot_payload = {
            "version": 1,
            "deleted_rows": deleted_rows,
            "updated_rows": updated_rows,
            "inserted_rows": inserted_rows,
        }
        conn.execute(
            """INSERT INTO recycle_bin_items (
                   id, project_id, project_name, scenario_id, scenario_name,
                   entity_type, entity_table, entity_id, entity_label,
                   summary_text, snapshot_json, file_paths_json,
                   deleted_by, deleted_at, expires_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                str(project_id or ""),
                project_name,
                str(scenario_id) if scenario_id else None,
                scenario_name,
                str(entity_type or "").strip() or "Record",
                str(entity_table or "").strip(),
                str(entity_id or "").strip(),
                str(entity_label or "").strip() or str(entity_id or ""),
                summary_text,
                json.dumps(snapshot_payload, ensure_ascii=False),
                json.dumps(file_paths, ensure_ascii=False),
                _resolve_deleted_by(deleted_by),
                deleted_at,
                expires_at,
            ),
        )
    finally:
        with _CAPTURE_LOCK:
            _ACTIVE_CAPTURE_CONN_IDS.discard(conn_id)


def _normalize_upload_key(raw_path: str | Path | None) -> str:
    raw = str(raw_path or "").strip()
    if not raw:
        return ""
    resolved = _db_core.resolve_upload_path(raw, _db_core.UPLOAD_DIR)
    if resolved is not None:
        try:
            return resolved.resolve().as_posix().lower()
        except OSError:
            return resolved.as_posix().lower()
    return raw.replace("\\", "/").lower()


def is_upload_path_in_recycle_bin(
    raw_path: str | Path | None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Return True when raw_path is referenced by at least one Recycle Bin item."""
    target_key = _normalize_upload_key(raw_path)
    if not target_key:
        return False

    def _check(c: sqlite3.Connection) -> bool:
        init_recycle_bin_schema(c)
        rows = c.execute(
            "SELECT file_paths_json FROM recycle_bin_items WHERE file_paths_json <> '[]'"
        ).fetchall()
        for row in rows:
            try:
                paths = json.loads(row[0] or "[]")
            except (TypeError, json.JSONDecodeError):
                continue
            for p in paths:
                if _normalize_upload_key(p) == target_key:
                    return True
        return False

    if conn is not None:
        return _check(conn)
    with _db_core.connection() as c:
        return _check(c)


def _is_upload_path_referenced_in_live_tables(
    conn: sqlite3.Connection, target_key: str
) -> bool:
    from utils.project_transfer import PROJECT_TRANSFER_TABLES

    existing = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    table_names = [item.name for item in PROJECT_TRANSFER_TABLES]
    if "app_feedback" in existing and "app_feedback" not in table_names:
        table_names.append("app_feedback")
    for table_name in table_names:
        if table_name not in existing:
            continue
        cols = [
            str(r[1])
            for r in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            if str(r[1]).endswith("_path")
        ]
        for col in cols:
            rows = conn.execute(
                f'SELECT "{col}" FROM "{table_name}" WHERE "{col}" IS NOT NULL AND TRIM("{col}") <> \'\''
            ).fetchall()
            for r in rows:
                if _normalize_upload_key(r[0]) == target_key:
                    return True
    return False


def safe_unlink_upload_path(
    raw_path: str | Path | None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Unlink an owned upload file only if it is not preserved in the Recycle Bin or live tables."""
    raw = str(raw_path or "").strip()
    if not raw:
        return False
    target = _db_core.resolve_upload_path(raw, _db_core.UPLOAD_DIR)
    if target is None or not target.is_file():
        return False
    target_key = _normalize_upload_key(target)

    def _still_referenced(c: sqlite3.Connection) -> bool:
        return is_upload_path_in_recycle_bin(target, c) or _is_upload_path_referenced_in_live_tables(
            c, target_key
        )

    referenced = (
        _still_referenced(conn)
        if conn is not None
        else _still_referenced_with_new_conn(target, target_key)
    )
    if referenced:
        return False
    try:
        target.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _still_referenced_with_new_conn(target: Path, target_key: str) -> bool:
    with _db_core.connection() as c:
        return is_upload_path_in_recycle_bin(target, c) or _is_upload_path_referenced_in_live_tables(
            c, target_key
        )


def _cleanup_unreferenced_upload_paths(
    conn: sqlite3.Connection, candidate_paths: list[str]
) -> int:
    removed = 0
    seen: set[str] = set()
    for raw in candidate_paths:
        key = _normalize_upload_key(raw)
        if not key or key in seen:
            continue
        seen.add(key)
        if safe_unlink_upload_path(raw, conn=conn):
            removed += 1
    return removed


def purge_expired_recycle_bin_items(
    conn: sqlite3.Connection | None = None,
) -> int:
    """Permanently purge Recycle Bin items whose expires_at is at or before now."""
    now_str = _db_core.now_iso()

    def _purge(c: sqlite3.Connection) -> int:
        init_recycle_bin_schema(c)
        expired_rows = c.execute(
            "SELECT id, file_paths_json FROM recycle_bin_items WHERE datetime(expires_at) <= datetime(?)",
            (now_str,),
        ).fetchall()
        if not expired_rows:
            return 0
        candidate_files: list[str] = []
        expired_ids = [str(r["id"]) for r in expired_rows]
        for r in expired_rows:
            try:
                candidate_files.extend(json.loads(r["file_paths_json"] or "[]"))
            except (TypeError, json.JSONDecodeError):
                pass
        placeholders = ",".join("?" for _ in expired_ids)
        c.execute(
            f"DELETE FROM recycle_bin_items WHERE id IN ({placeholders})",
            tuple(expired_ids),
        )
        _cleanup_unreferenced_upload_paths(c, candidate_files)
        return len(expired_ids)

    if conn is not None:
        return _purge(conn)
    with _db_core.connection() as c:
        return _purge(c)


@cached_store_read
def recycle_bin_item_count(
    project_id: str | None = None,
    include_all_projects: bool = True,
) -> int:
    """Return the count of non-expired items currently in the Recycle Bin."""
    now_str = _db_core.now_iso()
    with _db_core.connection() as conn:
        init_recycle_bin_schema(conn)
        if include_all_projects or not project_id:
            row = conn.execute(
                "SELECT COUNT(*) FROM recycle_bin_items WHERE datetime(expires_at) > datetime(?)",
                (now_str,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM recycle_bin_items WHERE project_id = ? AND datetime(expires_at) > datetime(?)",
                (str(project_id), now_str),
            ).fetchone()
        return int(row[0] or 0) if row else 0


@cached_store_read
def list_recycle_bin_items(
    project_id: str | None = None,
    scenario_id: str | None = None,
    include_all_projects: bool = False,
) -> pd.DataFrame:
    """Return non-expired Recycle Bin items ordered newest first."""
    columns = [
        "id",
        "project_id",
        "project_name",
        "scenario_id",
        "scenario_name",
        "entity_type",
        "entity_table",
        "entity_id",
        "entity_label",
        "summary_text",
        "file_count",
        "deleted_by",
        "deleted_at",
        "expires_at",
        "days_remaining",
    ]
    now_dt = datetime.now(_db_core.EASTERN_TIMEZONE)
    now_str = now_dt.replace(microsecond=0).isoformat()
    with _db_core.connection() as conn:
        init_recycle_bin_schema(conn)
        purge_expired_recycle_bin_items(conn)
        sql = """
            SELECT id, project_id, project_name, scenario_id, scenario_name,
                   entity_type, entity_table, entity_id, entity_label,
                   summary_text, file_paths_json, deleted_by, deleted_at, expires_at
            FROM recycle_bin_items
            WHERE datetime(expires_at) > datetime(?)
        """
        params: list[Any] = [now_str]
        if not include_all_projects and project_id:
            sql += " AND project_id = ?"
            params.append(str(project_id))
        if scenario_id:
            sql += " AND (scenario_id = ? OR scenario_id IS NULL OR scenario_id = '')"
            params.append(str(scenario_id))
        sql += " ORDER BY datetime(deleted_at) DESC, deleted_at DESC, rowid DESC"
        rows = conn.execute(sql, tuple(params)).fetchall()
        live_projects = {
            str(r["id"]): str(r["name"] or "")
            for r in conn.execute("SELECT id, name FROM projects").fetchall()
        }
        live_scenarios = {
            str(r["id"]): str(r["name"] or "")
            for r in conn.execute("SELECT id, name FROM planning_scenarios").fetchall()
        }

    if not rows:
        df = pd.DataFrame(columns=columns)
        for col in columns:
            if col in {"file_count", "days_remaining"}:
                df[col] = df[col].astype("int64")
            else:
                df[col] = df[col].astype("string")
        return df

    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            files = json.loads(row["file_paths_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            files = []
        try:
            exp_dt = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            exp_dt = exp_dt.astimezone(_db_core.EASTERN_TIMEZONE)
            delta_days = max(0, int((exp_dt - now_dt).total_seconds() // 86400))
        except ValueError:
            delta_days = RECYCLE_BIN_RETENTION_DAYS
        pid = str(row["project_id"] or "")
        sid = str(row["scenario_id"] or "")
        resolved_project_name = (
            live_projects.get(pid)
            or str(row["project_name"] or "").strip()
            or pid
            or "All projects"
        )
        if not sid or str(row["entity_table"] or "") == "projects":
            resolved_scenario_name = "All scenarios"
        else:
            resolved_scenario_name = (
                live_scenarios.get(sid)
                or str(row["scenario_name"] or "").strip()
                or sid
            )
        records.append(
            {
                "id": str(row["id"]),
                "project_id": pid,
                "project_name": resolved_project_name,
                "scenario_id": sid,
                "scenario_name": resolved_scenario_name,
                "entity_type": str(row["entity_type"] or ""),
                "entity_table": str(row["entity_table"] or ""),
                "entity_id": str(row["entity_id"] or ""),
                "entity_label": str(row["entity_label"] or ""),
                "summary_text": str(row["summary_text"] or ""),
                "file_count": len(files),
                "deleted_by": str(row["deleted_by"] or ""),
                "deleted_at": _db_core.to_eastern_iso(row["deleted_at"]),
                "expires_at": _db_core.to_eastern_iso(row["expires_at"]),
                "days_remaining": delta_days,
            }
        )
    return pd.DataFrame(records, columns=columns)


_RENAMEABLE_CANDIDATE_COLUMNS: tuple[str, ...] = (
    "name",
    "part_number",
    "code",
    "unique_identifier",
    "assembly_number",
    "issue_key",
    "asset_tag",
    "title",
    "label",
    "option_text",
)


def _table_unique_constraints(
    conn: sqlite3.Connection, table: str
) -> tuple[list[str], list[list[str]]]:
    """Return (pk_cols, unique_index_col_groups) for table."""
    pk_cols = _table_pk_columns(conn, table)
    unique_groups: list[list[str]] = []
    for idx_row in conn.execute(f'PRAGMA index_list("{table}")').fetchall():
        is_unique = int(idx_row[2] or 0) == 1
        if not is_unique:
            continue
        idx_name = str(idx_row[1])
        idx_cols = [
            str(info_row[2])
            for info_row in sorted(
                conn.execute(f'PRAGMA index_info("{idx_name}")').fetchall(),
                key=lambda r: int(r[0] or 0),
            )
            if info_row[2] is not None
        ]
        if idx_cols and idx_cols not in unique_groups and idx_cols != pk_cols:
            unique_groups.append(idx_cols)
    return pk_cols, unique_groups


def _choose_rename_column(
    conn: sqlite3.Connection, table: str, constraint_cols: list[str]
) -> str:
    """Return the human-editable column in constraint_cols, or '' if none is suitable."""
    for candidate in _RENAMEABLE_CANDIDATE_COLUMNS:
        if candidate in constraint_cols:
            return candidate
    col_types = {
        str(r[1]): str(r[2] or "").upper()
        for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    }
    for col in constraint_cols:
        if col == "id" or col.endswith("_id"):
            continue
        if "TEXT" in col_types.get(col, "TEXT") or col_types.get(col, "") == "":
            return col
    return ""


def _row_display_summary(row: dict[str, Any], rename_col: str = "") -> str:
    """Format a concise summary of a row for side-by-side conflict comparison."""
    parts: list[str] = []
    primary = str(
        (row.get(rename_col) if rename_col else None)
        or row.get("name")
        or row.get("part_number")
        or row.get("unique_identifier")
        or row.get("code")
        or row.get("assembly_number")
        or row.get("issue_key")
        or row.get("operation")
        or row.get("description")
        or row.get("id")
        or ""
    ).strip()
    if primary:
        parts.append(primary)
    for extra_col in ("name", "description", "operation", "station", "category", "status"):
        if extra_col == rename_col:
            continue
        val = str(row.get(extra_col) or "").strip()
        if val and val != primary:
            parts.append(f"{extra_col}: {val}")
            if len(parts) >= 3:
                break
    return " · ".join(parts) if parts else str(row.get("id") or "Record")


def _suggest_non_colliding_value(
    conn: sqlite3.Connection,
    table: str,
    rename_col: str,
    base_value: str,
    suffix: str,
) -> str:
    """Return a non-colliding candidate value for rename_col in table."""
    clean_base = str(base_value or "").strip() or "Item"
    candidate = f"{clean_base} ({suffix})"
    counter = 2
    while conn.execute(
        f'SELECT 1 FROM "{table}" WHERE "{rename_col}" = ? COLLATE NOCASE LIMIT 1',
        (candidate,),
    ).fetchone():
        candidate = f"{clean_base} ({suffix} {counter})"
        counter += 1
    return candidate


def _detect_conflicts_for_item_conn(
    conn: sqlite3.Connection,
    item: sqlite3.Row | dict[str, Any],
    topo_tables: list[str],
) -> list[dict[str, Any]]:
    """Detect primary-key or unique-constraint collisions between one Recycle Bin item and live DB rows."""
    item_id = str(item["id"])
    entity_table = str(item["entity_table"] or "")
    entity_type = str(item["entity_type"] or "Record")
    entity_label = str(item["entity_label"] or item["entity_id"] or "")
    deleted_at = _db_core.to_eastern_iso(item["deleted_at"])
    deleted_by = str(item["deleted_by"] or "")

    try:
        snapshot = json.loads(item["snapshot_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        return []

    deleted_rows: dict[str, list[dict[str, Any]]] = snapshot.get("deleted_rows") or {}
    inserted_rows: dict[str, list[dict[str, Any]]] = snapshot.get("inserted_rows") or {}

    # Prioritize checking the root entity_table first, then other tables in topological order
    ordered_tables: list[str] = []
    if entity_table and entity_table in topo_tables:
        ordered_tables.append(entity_table)
    for tbl in topo_tables:
        if tbl not in ordered_tables:
            ordered_tables.append(tbl)

    conflicts: list[dict[str, Any]] = []
    seen_live_rows: set[tuple[str, tuple[Any, ...]]] = set()

    for tbl in ordered_tables:
        rows_to_insert = deleted_rows.get(tbl) or []
        if not rows_to_insert:
            continue
        # If root entity_table already has a conflict, skip secondary child-table noise
        # so the user resolves the root entity conflict cleanly.
        if conflicts and tbl != entity_table:
            continue

        avail_cols = {
            str(r[1]) for r in conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
        }
        pk_cols, unique_groups = _table_unique_constraints(conn, tbl)
        side_effect_pks = {
            tuple(pk_dict.get(c) for c in pk_cols)
            for pk_dict in (inserted_rows.get(tbl) or [])
            if pk_dict
        }

        for row_idx, row_dict in enumerate(rows_to_insert):
            filtered = {k: v for k, v in row_dict.items() if k in avail_cols}
            if not filtered:
                continue

            matched_live: dict[str, Any] | None = None
            matched_type = ""
            matched_cols: list[str] = []
            rename_col = ""

            # 1. Check unique constraints first (human-meaningful keys like part_number, name, code)
            for u_cols in unique_groups:
                if any(filtered.get(c) is None for c in u_cols):
                    continue
                where_sql = " AND ".join(
                    f'"{c}" = ? COLLATE NOCASE' if isinstance(filtered.get(c), str) else f'"{c}" = ?'
                    for c in u_cols
                )
                live_row = conn.execute(
                    f'SELECT * FROM "{tbl}" WHERE {where_sql} LIMIT 1',
                    tuple(filtered[c] for c in u_cols),
                ).fetchone()
                if live_row is not None:
                    live_dict = dict(live_row)
                    live_pk = tuple(live_dict.get(c) for c in pk_cols)
                    if live_pk in side_effect_pks:
                        continue
                    matched_live = live_dict
                    matched_type = "unique_key"
                    matched_cols = u_cols
                    rename_col = _choose_rename_column(conn, tbl, u_cols)
                    break

            # 2. Check primary key collision if no unique index collided
            if matched_live is None and pk_cols and all(filtered.get(c) is not None for c in pk_cols):
                where_sql = " AND ".join(f'"{c}" = ?' for c in pk_cols)
                live_row = conn.execute(
                    f'SELECT * FROM "{tbl}" WHERE {where_sql} LIMIT 1',
                    tuple(filtered[c] for c in pk_cols),
                ).fetchone()
                if live_row is not None:
                    live_dict = dict(live_row)
                    live_pk = tuple(live_dict.get(c) for c in pk_cols)
                    if live_pk not in side_effect_pks:
                        matched_live = live_dict
                        matched_type = "primary_key"
                        matched_cols = pk_cols
                        # If the table also has unique groups with a rename column, allow renaming if values match
                        for u_cols in unique_groups:
                            candidate_col = _choose_rename_column(conn, tbl, u_cols)
                            if candidate_col and str(filtered.get(candidate_col) or "").strip().lower() == str(live_dict.get(candidate_col) or "").strip().lower():
                                rename_col = candidate_col
                                break

            if matched_live is None:
                continue

            live_pk_tuple = tuple(matched_live.get(c) for c in pk_cols)
            if (tbl, live_pk_tuple) in seen_live_rows:
                continue
            seen_live_rows.add((tbl, live_pk_tuple))

            older_val = str(
                (filtered.get(rename_col) if rename_col else None)
                or filtered.get("name")
                or filtered.get("part_number")
                or filtered.get("unique_identifier")
                or filtered.get("code")
                or filtered.get("id")
                or entity_label
            ).strip()
            newer_val = str(
                (matched_live.get(rename_col) if rename_col else None)
                or matched_live.get("name")
                or matched_live.get("part_number")
                or matched_live.get("unique_identifier")
                or matched_live.get("code")
                or matched_live.get("id")
                or ""
            ).strip()

            conflict_id = f"{item_id}:{tbl}:{row_idx}"
            conflicts.append(
                {
                    "conflict_id": conflict_id,
                    "item_id": item_id,
                    "entity_type": entity_type,
                    "entity_table": entity_table,
                    "entity_label": entity_label,
                    "conflict_table": tbl,
                    "conflict_table_label": _TABLE_HUMAN_LABELS.get(tbl, tbl),
                    "conflict_type": matched_type,
                    "conflict_columns": matched_cols,
                    "pk_columns": pk_cols,
                    "rename_column": rename_col,
                    "can_rename": bool(rename_col),
                    "row_index": row_idx,
                    "older_value": older_val,
                    "newer_value": newer_val,
                    "older_summary": _row_display_summary(filtered, rename_col),
                    "newer_summary": _row_display_summary(matched_live, rename_col),
                    "older_deleted_at": deleted_at,
                    "older_deleted_by": deleted_by,
                    "older_updated_at": _db_core.to_eastern_iso(filtered.get("updated_at") or item["deleted_at"]),
                    "newer_updated_at": _db_core.to_eastern_iso(matched_live.get("updated_at") or matched_live.get("created_at") or ""),
                    "older_row": filtered,
                    "newer_row": matched_live,
                    "suggested_older_name": (
                        _suggest_non_colliding_value(conn, tbl, rename_col, older_val, "Restored")
                        if rename_col
                        else ""
                    ),
                    "suggested_newer_name": (
                        _suggest_non_colliding_value(conn, tbl, rename_col, newer_val, "Active")
                        if rename_col
                        else ""
                    ),
                }
            )

    return conflicts


def detect_recycle_bin_restore_conflicts(
    item_ids: list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    """Return any conflicts between the selected Recycle Bin items and currently active records."""
    from utils.project_transfer import PROJECT_TRANSFER_TABLES

    normalized_ids = [
        str(item_id or "").strip()
        for item_id in item_ids
        if str(item_id or "").strip()
    ]
    if not normalized_ids:
        return []

    with _db_core.connection() as conn:
        init_recycle_bin_schema(conn)
        placeholders = ",".join("?" for _ in normalized_ids)
        items = conn.execute(
            f"""SELECT * FROM recycle_bin_items
                WHERE id IN ({placeholders})
                ORDER BY datetime(deleted_at) DESC, deleted_at DESC, rowid DESC""",
            tuple(normalized_ids),
        ).fetchall()
        if not items:
            return []
        existing_tables = {
            str(r[0])
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        topo_tables = [
            t.name for t in PROJECT_TRANSFER_TABLES if t.name in existing_tables
        ]
        if "app_feedback" in existing_tables and "app_feedback" not in topo_tables:
            topo_tables.append("app_feedback")

        all_conflicts: list[dict[str, Any]] = []
        for item in items:
            all_conflicts.extend(_detect_conflicts_for_item_conn(conn, item, topo_tables))
        return all_conflicts


def _remap_snapshot_entity_id(
    deleted_rows: dict[str, list[dict[str, Any]]],
    updated_rows: dict[str, list[dict[str, Any]]],
    old_id: str,
    new_id: str,
) -> None:
    """Replace occurrences of old_id with new_id across deleted_rows and updated_rows when keeping both items."""
    if not old_id or not new_id or old_id == new_id:
        return
    for tbl, rows in deleted_rows.items():
        for row_dict in rows:
            for k, v in list(row_dict.items()):
                if v == old_id and (k == "id" or k.endswith("_id")):
                    row_dict[k] = new_id
    for tbl, updates in updated_rows.items():
        for upd in updates:
            changed_before = upd.get("changed_before") or {}
            for k, v in list(changed_before.items()):
                if v == old_id and (k == "id" or k.endswith("_id")):
                    changed_before[k] = new_id


def restore_recycle_bin_items(
    item_ids: list[str] | tuple[str, ...],
    editor_name: str = "",
    conflict_resolutions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Atomically restore one or more Recycle Bin items and their cascaded child records."""
    from utils.project_transfer import PROJECT_TRANSFER_TABLES

    normalized_ids = [
        str(item_id or "").strip()
        for item_id in item_ids
        if str(item_id or "").strip()
    ]
    if not normalized_ids:
        raise ValueError("Select at least one Recycle Bin item to restore.")

    resolutions = conflict_resolutions or {}

    with _db_core.connection() as conn:
        init_recycle_bin_schema(conn)
        placeholders = ",".join("?" for _ in normalized_ids)
        # Order newest deletion first so if a user deleted a child at T1 and its parent
        # at T2 and restores both together, the parent (T2) is restored before the child (T1).
        items = conn.execute(
            f"""SELECT * FROM recycle_bin_items
                WHERE id IN ({placeholders})
                ORDER BY datetime(deleted_at) DESC, deleted_at DESC, rowid DESC""",
            tuple(normalized_ids),
        ).fetchall()
        if not items:
            raise ValueError("The selected Recycle Bin items no longer exist.")

        conn.execute("PRAGMA defer_foreign_keys = ON")
        existing_tables = {
            str(r[0])
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        topo_tables = [
            t.name for t in PROJECT_TRANSFER_TABLES if t.name in existing_tables
        ]
        if "app_feedback" in existing_tables and "app_feedback" not in topo_tables:
            topo_tables.append("app_feedback")

        restored_labels: list[str] = []
        restored_projects: list[str] = []
        skipped_labels: list[str] = []
        replaced_labels: list[str] = []

        for item in items:
            item_id = str(item["id"])
            project_id = str(item["project_id"] or "")
            scenario_id = str(item["scenario_id"] or "").strip() or None
            entity_type = str(item["entity_type"] or "Record")
            entity_table = str(item["entity_table"] or "")
            entity_label = str(item["entity_label"] or item["entity_id"] or "")

            if entity_table not in {"projects", "app_feedback"}:
                proj_exists = conn.execute(
                    "SELECT 1 FROM projects WHERE id=?", (project_id,)
                ).fetchone()
                if not proj_exists:
                    raise ValueError(
                        f"Cannot restore '{entity_label}' because its parent project "
                        f"('{item['project_name'] or project_id}') is currently deleted. "
                        "Restore the project first (or select both to restore together)."
                    )
            if scenario_id and entity_table not in {"planning_scenarios", "app_feedback"}:
                scen_exists = conn.execute(
                    "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
                    (scenario_id, project_id),
                ).fetchone()
                if not scen_exists:
                    raise ValueError(
                        f"Cannot restore '{entity_label}' because its planning scenario "
                        f"('{item['scenario_name'] or scenario_id}') no longer exists."
                    )

            try:
                snapshot = json.loads(item["snapshot_json"] or "{}")
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"Cannot restore '{entity_label}' because its snapshot payload is unreadable."
                ) from exc

            deleted_rows: dict[str, list[dict[str, Any]]] = snapshot.get("deleted_rows") or {}
            updated_rows: dict[str, list[dict[str, Any]]] = snapshot.get("updated_rows") or {}
            inserted_rows: dict[str, list[dict[str, Any]]] = snapshot.get("inserted_rows") or {}

            item_conflicts = _detect_conflicts_for_item_conn(conn, item, topo_tables)
            skip_this_item = False

            for conflict in item_conflicts:
                cid = str(conflict["conflict_id"])
                res = resolutions.get(cid) or resolutions.get(item_id)
                if not res or not str(res.get("action") or "").strip():
                    col_desc = conflict["rename_column"] or ", ".join(conflict["conflict_columns"])
                    err = ValueError(
                        f"Restore conflict detected for '{entity_label}': an active {conflict['conflict_table_label']} "
                        f"('{conflict['newer_value']}') already uses the same {col_desc}. "
                        "Confirm whether to rename the older item, rename the newer item, replace the newer item, or skip."
                    )
                    setattr(err, "conflicts", item_conflicts)
                    raise err

                action = str(res.get("action") or "").strip()
                c_table = str(conflict["conflict_table"])
                c_row_idx = int(conflict["row_index"])
                rename_col = str(conflict["rename_column"] or "")
                pk_cols = list(conflict["pk_columns"])
                newer_row = dict(conflict["newer_row"])
                older_row_ref = (deleted_rows.get(c_table) or [])[c_row_idx]

                if action == "skip":
                    skip_this_item = True
                    break
                elif action == "rename_older":
                    if not rename_col:
                        raise ValueError(
                            f"Cannot rename '{entity_label}' because '{conflict['conflict_table_label']}' has no editable name/identifier column."
                        )
                    new_name = str(res.get("new_name") or "").strip()
                    if not new_name:
                        raise ValueError(f"Enter a new {rename_col} for the restored item '{entity_label}'.")
                    older_row_ref[rename_col] = new_name
                    entity_label = new_name
                    # Check if any other unique column on the same row also collides with newer_row
                    _, u_groups = _table_unique_constraints(conn, c_table)
                    for u_cols in u_groups:
                        sec_col = _choose_rename_column(conn, c_table, u_cols)
                        if sec_col and sec_col != rename_col:
                            if str(older_row_ref.get(sec_col) or "").strip().lower() == str(newer_row.get(sec_col) or "").strip().lower():
                                older_row_ref[sec_col] = _suggest_non_colliding_value(
                                    conn, c_table, sec_col, str(older_row_ref.get(sec_col) or ""), "Restored"
                                )
                    # If the primary key (e.g. UUID) ALSO collides with the live row, mint a new UUID for the restored row
                    if pk_cols == ["id"] and str(older_row_ref.get("id") or "") == str(newer_row.get("id") or ""):
                        _remap_snapshot_entity_id(
                            deleted_rows, updated_rows, str(older_row_ref["id"]), str(uuid4())
                        )
                elif action == "rename_newer":
                    if not rename_col:
                        raise ValueError(
                            f"Cannot rename the active '{conflict['conflict_table_label']}' because it has no editable name/identifier column."
                        )
                    new_name = str(res.get("new_name") or "").strip()
                    if not new_name:
                        raise ValueError(f"Enter a new {rename_col} for the active item '{conflict['newer_value']}'.")
                    where_pk = " AND ".join(f'"{c}" = ?' for c in pk_cols)
                    pk_vals = tuple(newer_row[c] for c in pk_cols)
                    try:
                        conn.execute(
                            f'UPDATE "{c_table}" SET "{rename_col}" = ? WHERE {where_pk}',
                            (new_name,) + pk_vals,
                        )
                    except sqlite3.IntegrityError as exc:
                        raise ValueError(
                            f"Cannot rename active {conflict['conflict_table_label']} to '{new_name}' because that identifier is already in use."
                        ) from exc
                    # Check if any other unique column on the same row also collides with older_row_ref
                    _, u_groups = _table_unique_constraints(conn, c_table)
                    for u_cols in u_groups:
                        sec_col = _choose_rename_column(conn, c_table, u_cols)
                        if sec_col and sec_col != rename_col:
                            if str(older_row_ref.get(sec_col) or "").strip().lower() == str(newer_row.get(sec_col) or "").strip().lower():
                                sec_new = _suggest_non_colliding_value(
                                    conn, c_table, sec_col, str(newer_row.get(sec_col) or ""), "Active"
                                )
                                conn.execute(
                                    f'UPDATE "{c_table}" SET "{sec_col}" = ? WHERE {where_pk}',
                                    (sec_new,) + pk_vals,
                                )
                    if pk_cols == ["id"] and str(older_row_ref.get("id") or "") == str(newer_row.get("id") or ""):
                        _remap_snapshot_entity_id(
                            deleted_rows, updated_rows, str(older_row_ref["id"]), str(uuid4())
                        )
                elif action == "replace_newer":
                    where_pk = " AND ".join(f'"{c}" = ?' for c in pk_cols)
                    pk_vals = tuple(newer_row[c] for c in pk_cols)
                    newer_id = str(newer_row.get("id") or pk_vals[0] or "")
                    newer_label = str(conflict["newer_value"] or newer_id)
                    with capture_deletion_to_recycle_bin(
                        conn,
                        project_id=project_id,
                        scenario_id=scenario_id,
                        entity_type=entity_type if c_table == entity_table else _TABLE_HUMAN_LABELS.get(c_table, c_table).capitalize(),
                        entity_table=c_table,
                        entity_id=newer_id,
                        entity_label=f"{newer_label} (Replaced by restored item)",
                        deleted_by=editor_name or "Collaborator",
                    ):
                        conn.execute(f'DELETE FROM "{c_table}" WHERE {where_pk}', pk_vals)
                    replaced_labels.append(newer_label)
                else:
                    raise ValueError(f"Unsupported conflict resolution action: '{action}'.")

            if skip_this_item:
                skipped_labels.append(f"{entity_type}: {entity_label}")
                continue

            # 1. Remove side-effect rows inserted during deletion (e.g. healed section connections)
            for tbl in reversed(topo_tables):
                side_effects = inserted_rows.get(tbl) or []
                for pk_dict in side_effects:
                    if not pk_dict:
                        continue
                    where_clause = " AND ".join(f'"{k}" = ?' for k in pk_dict)
                    conn.execute(
                        f'DELETE FROM "{tbl}" WHERE {where_clause}',
                        tuple(pk_dict.values()),
                    )

            # 2. Re-insert deleted rows in topological parent-before-child order
            for tbl in topo_tables:
                rows_to_insert = deleted_rows.get(tbl) or []
                if not rows_to_insert:
                    continue
                avail_cols = {
                    str(r[1])
                    for r in conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
                }
                for row_dict in rows_to_insert:
                    filtered = {
                        k: v for k, v in row_dict.items() if k in avail_cols
                    }
                    if not filtered:
                        continue
                    if tbl == "app_feedback":
                        fb_pid = str(filtered.get("project_id") or "").strip()
                        if fb_pid and not conn.execute(
                            "SELECT 1 FROM projects WHERE id=?", (fb_pid,)
                        ).fetchone():
                            filtered["project_id"] = None
                            filtered["scenario_id"] = None
                        fb_sid = str(filtered.get("scenario_id") or "").strip()
                        if fb_sid and not conn.execute(
                            "SELECT 1 FROM planning_scenarios WHERE id=?", (fb_sid,)
                        ).fetchone():
                            filtered["scenario_id"] = None
                    col_list = ", ".join(f'"{k}"' for k in filtered)
                    val_placeholders = ", ".join("?" for _ in filtered)
                    try:
                        conn.execute(
                            f'INSERT INTO "{tbl}" ({col_list}) VALUES ({val_placeholders})',
                            tuple(filtered.values()),
                        )
                    except sqlite3.IntegrityError as exc:
                        if tbl != entity_table:
                            # Secondary child row (e.g. default part_scenario_activity created when active item existed)
                            continue
                        raise ValueError(
                            f"Cannot restore '{entity_label}' due to a uniqueness or constraint conflict "
                            f"in '{_TABLE_HUMAN_LABELS.get(tbl, tbl)}' ({exc})."
                        ) from exc

            # 3. Revert updated columns on surviving rows (e.g. unlinked work_element_id or cleared image_path)
            for tbl in topo_tables:
                updates = updated_rows.get(tbl) or []
                if not updates:
                    continue
                avail_cols = {
                    str(r[1])
                    for r in conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
                }
                for upd in updates:
                    pk_dict = upd.get("pk") or {}
                    changed_before = {
                        k: v
                        for k, v in (upd.get("changed_before") or {}).items()
                        if k in avail_cols
                    }
                    if not pk_dict or not changed_before:
                        continue
                    set_clause = ", ".join(f'"{k}" = ?' for k in changed_before)
                    where_clause = " AND ".join(f'"{k}" = ?' for k in pk_dict)
                    try:
                        conn.execute(
                            f'UPDATE "{tbl}" SET {set_clause} WHERE {where_clause}',
                            tuple(changed_before.values()) + tuple(pk_dict.values()),
                        )
                    except sqlite3.IntegrityError:
                        # If a surviving row was modified in a conflicting way, skip its optional link revert
                        pass

            conn.execute("DELETE FROM recycle_bin_items WHERE id=?", (item_id,))
            restored_labels.append(f"{entity_type}: {entity_label}")
            if entity_table == "projects":
                restored_projects.append(project_id)

            if conn.execute(
                "SELECT 1 FROM projects WHERE id=?", (project_id,)
            ).fetchone():
                _db_core.record_audit_event(
                    project_id,
                    "Recycle Bin",
                    f"Restore {entity_type}",
                    1,
                    editor_name=editor_name,
                    details={
                        "recycle_bin_item_id": item_id,
                        "entity_type": entity_type,
                        "entity_table": entity_table,
                        "entity_id": str(item["entity_id"] or ""),
                        "entity_label": entity_label,
                        "scenario_id": scenario_id or "",
                    },
                    _conn=conn,
                )

        # Verify foreign key integrity across the restored state before committing
        fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_violations:
            violating_tables = sorted({str(v[0]) for v in fk_violations})
            human_tables = [
                _TABLE_HUMAN_LABELS.get(t, t) for t in violating_tables
            ]
            raise ValueError(
                "Cannot restore the selected item(s) because a parent or linked record they depend on "
                f"is still deleted ({', '.join(human_tables)}). Restore the parent record first or "
                "select both to restore together."
            )

    return {
        "restored_count": len(restored_labels),
        "restored_labels": restored_labels,
        "restored_projects": restored_projects,
        "skipped_count": len(skipped_labels),
        "skipped_labels": skipped_labels,
        "replaced_count": len(replaced_labels),
        "replaced_labels": replaced_labels,
    }


def permanently_delete_recycle_bin_items(
    item_ids: list[str] | tuple[str, ...],
    editor_name: str = "",
) -> int:
    """Permanently purge selected Recycle Bin items and unlink unreferenced media files."""
    normalized_ids = [
        str(item_id or "").strip()
        for item_id in item_ids
        if str(item_id or "").strip()
    ]
    if not normalized_ids:
        raise ValueError("Select at least one Recycle Bin item to permanently delete.")

    with _db_core.connection() as conn:
        init_recycle_bin_schema(conn)
        placeholders = ",".join("?" for _ in normalized_ids)
        rows = conn.execute(
            f"""SELECT id, project_id, entity_type, entity_label, file_paths_json
                FROM recycle_bin_items
                WHERE id IN ({placeholders})""",
            tuple(normalized_ids),
        ).fetchall()
        if not rows:
            return 0
        candidate_files: list[str] = []
        by_project: dict[str, list[str]] = {}
        for r in rows:
            try:
                candidate_files.extend(json.loads(r["file_paths_json"] or "[]"))
            except (TypeError, json.JSONDecodeError):
                pass
            pid = str(r["project_id"] or "")
            by_project.setdefault(pid, []).append(
                f"{r['entity_type']}: {r['entity_label']}"
            )

        conn.execute(
            f"DELETE FROM recycle_bin_items WHERE id IN ({placeholders})",
            tuple(normalized_ids),
        )
        _cleanup_unreferenced_upload_paths(conn, candidate_files)

        for pid, labels in by_project.items():
            if pid and conn.execute(
                "SELECT 1 FROM projects WHERE id=?", (pid,)
            ).fetchone():
                _db_core.record_audit_event(
                    pid,
                    "Recycle Bin",
                    "Permanent delete",
                    len(labels),
                    editor_name=editor_name,
                    details={"purged_items": labels[:25]},
                    _conn=conn,
                )
        return len(rows)


def empty_recycle_bin(
    project_id: str | None = None,
    include_all_projects: bool = False,
    editor_name: str = "",
) -> int:
    """Permanently purge all items in the Recycle Bin for the current project or all projects."""
    with _db_core.connection() as conn:
        init_recycle_bin_schema(conn)
        if include_all_projects or not project_id:
            rows = conn.execute("SELECT id FROM recycle_bin_items").fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM recycle_bin_items WHERE project_id=?",
                (str(project_id),),
            ).fetchall()
        ids = [str(r["id"]) for r in rows]
    if not ids:
        return 0
    return permanently_delete_recycle_bin_items(ids, editor_name=editor_name)


__domain_exports__ = [
    "RECYCLE_BIN_RETENTION_DAYS",
    "init_recycle_bin_schema",
    "purge_expired_recycle_bin_items",
    "capture_deletion_to_recycle_bin",
    "is_upload_path_in_recycle_bin",
    "safe_unlink_upload_path",
    "recycle_bin_item_count",
    "list_recycle_bin_items",
    "detect_recycle_bin_restore_conflicts",
    "restore_recycle_bin_items",
    "permanently_delete_recycle_bin_items",
    "empty_recycle_bin",
]
