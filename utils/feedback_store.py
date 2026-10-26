"""Persistence for the Universal Help & Search Hub and App Feedback Tracker."""

from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4

import pandas as pd

from utils import db_core as _db_core
from utils.cache_store import cached_store_read
from utils.recycle_bin_store import (
    capture_deletion_to_recycle_bin,
    safe_unlink_upload_path,
)

FEEDBACK_TYPES: tuple[str, ...] = (
    "Bug report",
    "Feature suggestion",
    "UX improvement",
    "Question",
)

FEEDBACK_SEVERITIES: tuple[str, ...] = (
    "Low",
    "Medium",
    "High",
    "Critical",
)

FEEDBACK_STATUSES: tuple[str, ...] = (
    "Open",
    "Under review",
    "Planned",
    "Resolved",
    "Closed",
)

FEEDBACK_COLUMNS: list[str] = [
    "id",
    "project_id",
    "project_name",
    "scenario_id",
    "scenario_name",
    "page_context",
    "feedback_type",
    "severity",
    "title",
    "description",
    "steps_to_reproduce",
    "screenshot_path",
    "status",
    "submitted_by",
    "resolution_notes",
    "created_at",
    "updated_at",
]

GLOBAL_SEARCH_COLUMNS: list[str] = [
    "category",
    "item_label",
    "detail",
    "scope",
    "page_title",
    "page_url_path",
    "record_id",
]


def init_feedback_schema(conn: sqlite3.Connection) -> None:
    """Create the app-wide app_feedback table and indexes if absent."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS app_feedback (
            id TEXT PRIMARY KEY,
            project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
            project_name TEXT NOT NULL DEFAULT '',
            scenario_id TEXT REFERENCES planning_scenarios(id) ON DELETE SET NULL,
            scenario_name TEXT NOT NULL DEFAULT '',
            page_context TEXT NOT NULL DEFAULT '',
            feedback_type TEXT NOT NULL DEFAULT 'Bug report'
                CHECK (feedback_type IN ('Bug report', 'Feature suggestion', 'UX improvement', 'Question')),
            severity TEXT NOT NULL DEFAULT 'Medium'
                CHECK (severity IN ('Low', 'Medium', 'High', 'Critical')),
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            steps_to_reproduce TEXT NOT NULL DEFAULT '',
            screenshot_path TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Open'
                CHECK (status IN ('Open', 'Under review', 'Planned', 'Resolved', 'Closed')),
            submitted_by TEXT NOT NULL DEFAULT '',
            resolution_notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_app_feedback_status_created
            ON app_feedback(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_app_feedback_project_created
            ON app_feedback(project_id, created_at DESC);
        """
    )


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _resolve_project_and_scenario_names(
    conn: sqlite3.Connection,
    project_id: str | None,
    scenario_id: str | None,
) -> tuple[str | None, str, str | None, str]:
    pid = _clean_text(project_id) or None
    sid = _clean_text(scenario_id) or None
    project_name = ""
    scenario_name = ""
    if pid:
        prow = conn.execute(
            "SELECT id, name FROM projects WHERE id=?", (pid,)
        ).fetchone()
        if prow:
            project_name = _clean_text(prow["name"])
        else:
            pid = None
            sid = None
    if pid and sid:
        srow = conn.execute(
            "SELECT id, name, revision_label FROM planning_scenarios WHERE id=? AND project_id=?",
            (sid, pid),
        ).fetchone()
        if srow:
            sname = _clean_text(srow["name"])
            srev = _clean_text(srow["revision_label"])
            scenario_name = f"{sname} (Rev {srev})" if srev else sname
        else:
            sid = None
    return pid, project_name, sid, scenario_name


def create_app_feedback(
    *,
    title: str,
    feedback_type: str = "Bug report",
    severity: str = "Medium",
    description: str = "",
    steps_to_reproduce: str = "",
    page_context: str = "",
    project_id: str | None = None,
    scenario_id: str | None = None,
    screenshot_path: str = "",
    submitted_by: str = "",
    status: str = "Open",
    resolution_notes: str = "",
) -> str:
    """Validate and persist a new bug report or feature suggestion."""
    clean_title = _clean_text(title)
    if not clean_title:
        raise ValueError("Enter a concise title for the feedback item.")
    clean_type = _clean_text(feedback_type) or "Bug report"
    if clean_type not in FEEDBACK_TYPES:
        raise ValueError(
            f"Feedback type must be one of: {', '.join(FEEDBACK_TYPES)}."
        )
    clean_severity = _clean_text(severity) or "Medium"
    if clean_severity not in FEEDBACK_SEVERITIES:
        raise ValueError(
            f"Severity must be one of: {', '.join(FEEDBACK_SEVERITIES)}."
        )
    clean_status = _clean_text(status) or "Open"
    if clean_status not in FEEDBACK_STATUSES:
        raise ValueError(
            f"Status must be one of: {', '.join(FEEDBACK_STATUSES)}."
        )

    feedback_id = str(uuid4())
    now = _db_core.now_iso()
    clean_editor = _clean_text(submitted_by)

    with _db_core.connection() as conn:
        init_feedback_schema(conn)
        pid, project_name, sid, scenario_name = _resolve_project_and_scenario_names(
            conn, project_id, scenario_id
        )
        conn.execute(
            """INSERT INTO app_feedback (
                   id, project_id, project_name, scenario_id, scenario_name,
                   page_context, feedback_type, severity, title, description,
                   steps_to_reproduce, screenshot_path, status, submitted_by,
                   resolution_notes, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                feedback_id,
                pid,
                project_name,
                sid,
                scenario_name,
                _clean_text(page_context),
                clean_type,
                clean_severity,
                clean_title,
                _clean_text(description),
                _clean_text(steps_to_reproduce),
                _clean_text(screenshot_path),
                clean_status,
                clean_editor,
                _clean_text(resolution_notes),
                now,
                now,
            ),
        )
        if pid:
            _db_core.record_audit_event(
                pid,
                "App feedback",
                f"Submit {clean_type.lower()}",
                1,
                editor_name=clean_editor,
                details={
                    "feedback_id": feedback_id,
                    "feedback_type": clean_type,
                    "severity": clean_severity,
                    "title": clean_title,
                    "page_context": _clean_text(page_context),
                },
                _conn=conn,
            )
    return feedback_id


@cached_store_read
def list_app_feedback(
    project_id: str | None = None,
    *,
    include_all_projects: bool = True,
    status_filter: str | None = None,
    feedback_type_filter: str | None = None,
) -> pd.DataFrame:
    """Return app_feedback rows ordered newest first."""
    with _db_core.connection() as conn:
        init_feedback_schema(conn)
        sql = """
            SELECT id, project_id, project_name, scenario_id, scenario_name,
                   page_context, feedback_type, severity, title, description,
                   steps_to_reproduce, screenshot_path, status, submitted_by,
                   resolution_notes, created_at, updated_at
            FROM app_feedback
            WHERE 1=1
        """
        params: list[Any] = []
        if not include_all_projects and _clean_text(project_id):
            sql += " AND (project_id = ? OR project_id IS NULL OR project_id = '')"
            params.append(_clean_text(project_id))
        if _clean_text(status_filter) and _clean_text(status_filter) != "All":
            sql += " AND status = ?"
            params.append(_clean_text(status_filter))
        if _clean_text(feedback_type_filter) and _clean_text(feedback_type_filter) != "All":
            sql += " AND feedback_type = ?"
            params.append(_clean_text(feedback_type_filter))
        sql += " ORDER BY datetime(created_at) DESC, created_at DESC, rowid DESC"
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
        df = pd.DataFrame(columns=FEEDBACK_COLUMNS)
        for col in FEEDBACK_COLUMNS:
            df[col] = df[col].astype("string")
        return df

    records: list[dict[str, Any]] = []
    for row in rows:
        pid = _clean_text(row["project_id"])
        sid = _clean_text(row["scenario_id"])
        resolved_project_name = (
            live_projects.get(pid)
            or _clean_text(row["project_name"])
            or ("All projects" if not pid else pid)
        )
        resolved_scenario_name = (
            live_scenarios.get(sid)
            or _clean_text(row["scenario_name"])
            or ("All scenarios" if not sid else sid)
        )
        records.append(
            {
                "id": str(row["id"]),
                "project_id": pid,
                "project_name": resolved_project_name,
                "scenario_id": sid,
                "scenario_name": resolved_scenario_name,
                "page_context": _clean_text(row["page_context"]),
                "feedback_type": _clean_text(row["feedback_type"]),
                "severity": _clean_text(row["severity"]),
                "title": _clean_text(row["title"]),
                "description": _clean_text(row["description"]),
                "steps_to_reproduce": _clean_text(row["steps_to_reproduce"]),
                "screenshot_path": _clean_text(row["screenshot_path"]),
                "status": _clean_text(row["status"]),
                "submitted_by": _clean_text(row["submitted_by"]),
                "resolution_notes": _clean_text(row["resolution_notes"]),
                "created_at": _db_core.to_eastern_iso(row["created_at"]),
                "updated_at": _db_core.to_eastern_iso(row["updated_at"]),
            }
        )
    return pd.DataFrame(records, columns=FEEDBACK_COLUMNS)


@cached_store_read
def open_app_feedback_count(project_id: str | None = None) -> int:
    """Return the count of Open / Under review / Planned feedback items."""
    with _db_core.connection() as conn:
        init_feedback_schema(conn)
        if _clean_text(project_id):
            row = conn.execute(
                """SELECT COUNT(*) FROM app_feedback
                   WHERE status IN ('Open', 'Under review', 'Planned')
                     AND (project_id = ? OR project_id IS NULL OR project_id = '')""",
                (_clean_text(project_id),),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT COUNT(*) FROM app_feedback
                   WHERE status IN ('Open', 'Under review', 'Planned')"""
            ).fetchone()
        return int(row[0] or 0) if row else 0


def update_app_feedback(
    feedback_id: str,
    *,
    title: str | None = None,
    feedback_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    description: str | None = None,
    steps_to_reproduce: str | None = None,
    resolution_notes: str | None = None,
    screenshot_path: str | None = None,
    editor_name: str = "",
) -> None:
    """Update an existing app_feedback item and record an audit event."""
    clean_id = _clean_text(feedback_id)
    if not clean_id:
        raise ValueError("Feedback ID is required.")

    with _db_core.connection() as conn:
        init_feedback_schema(conn)
        existing = conn.execute(
            "SELECT * FROM app_feedback WHERE id=?", (clean_id,)
        ).fetchone()
        if not existing:
            raise ValueError("The selected feedback item no longer exists.")

        new_title = (
            _clean_text(title)
            if title is not None
            else _clean_text(existing["title"])
        )
        if not new_title:
            raise ValueError("Feedback title cannot be empty.")

        new_type = (
            _clean_text(feedback_type)
            if feedback_type is not None
            else _clean_text(existing["feedback_type"])
        )
        if new_type not in FEEDBACK_TYPES:
            raise ValueError(
                f"Feedback type must be one of: {', '.join(FEEDBACK_TYPES)}."
            )

        new_severity = (
            _clean_text(severity)
            if severity is not None
            else _clean_text(existing["severity"])
        )
        if new_severity not in FEEDBACK_SEVERITIES:
            raise ValueError(
                f"Severity must be one of: {', '.join(FEEDBACK_SEVERITIES)}."
            )

        new_status = (
            _clean_text(status)
            if status is not None
            else _clean_text(existing["status"])
        )
        if new_status not in FEEDBACK_STATUSES:
            raise ValueError(
                f"Status must be one of: {', '.join(FEEDBACK_STATUSES)}."
            )

        new_desc = (
            _clean_text(description)
            if description is not None
            else _clean_text(existing["description"])
        )
        new_steps = (
            _clean_text(steps_to_reproduce)
            if steps_to_reproduce is not None
            else _clean_text(existing["steps_to_reproduce"])
        )
        new_notes = (
            _clean_text(resolution_notes)
            if resolution_notes is not None
            else _clean_text(existing["resolution_notes"])
        )
        old_screenshot = _clean_text(existing["screenshot_path"])
        new_screenshot = (
            _clean_text(screenshot_path)
            if screenshot_path is not None
            else old_screenshot
        )

        now = _db_core.now_iso()
        conn.execute(
            """UPDATE app_feedback
               SET title=?, feedback_type=?, severity=?, status=?,
                   description=?, steps_to_reproduce=?, resolution_notes=?,
                   screenshot_path=?, updated_at=?
               WHERE id=?""",
            (
                new_title,
                new_type,
                new_severity,
                new_status,
                new_desc,
                new_steps,
                new_notes,
                new_screenshot,
                now,
                clean_id,
            ),
        )
        if old_screenshot and old_screenshot != new_screenshot:
            safe_unlink_upload_path(old_screenshot, conn=conn)

        pid = _clean_text(existing["project_id"])
        if pid and conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone():
            _db_core.record_audit_event(
                pid,
                "App feedback",
                "Update feedback",
                1,
                editor_name=_clean_text(editor_name),
                details={
                    "feedback_id": clean_id,
                    "title": new_title,
                    "status": new_status,
                    "severity": new_severity,
                },
                _conn=conn,
            )


def save_bulk_app_feedback(
    df: pd.DataFrame,
    *,
    active_project_id: str | None = None,
    editor_name: str = "",
) -> int:
    """Validate and save inline edits from the feedback tracker table."""
    if df is None or df.empty:
        return 0

    validated_updates: list[tuple[str, str, str, str, str, str, str, str]] = []
    for idx, row in df.iterrows():
        fid = _clean_text(row.get("id"))
        if not fid:
            continue
        title = _clean_text(row.get("title"))
        if not title:
            raise ValueError(f"Row {idx + 1}: Title is required.")
        ftype = _clean_text(row.get("feedback_type")) or "Bug report"
        if ftype not in FEEDBACK_TYPES:
            raise ValueError(
                f"Row {idx + 1}: Feedback type must be one of {', '.join(FEEDBACK_TYPES)}."
            )
        sev = _clean_text(row.get("severity")) or "Medium"
        if sev not in FEEDBACK_SEVERITIES:
            raise ValueError(
                f"Row {idx + 1}: Severity must be one of {', '.join(FEEDBACK_SEVERITIES)}."
            )
        status = _clean_text(row.get("status")) or "Open"
        if status not in FEEDBACK_STATUSES:
            raise ValueError(
                f"Row {idx + 1}: Status must be one of {', '.join(FEEDBACK_STATUSES)}."
            )
        desc = _clean_text(row.get("description"))
        steps = _clean_text(row.get("steps_to_reproduce"))
        notes = _clean_text(row.get("resolution_notes"))
        validated_updates.append(
            (fid, title, ftype, sev, status, desc, steps, notes)
        )

    if not validated_updates:
        return 0

    now = _db_core.now_iso()
    changed_count = 0
    touched_projects: dict[str, int] = {}

    with _db_core.connection() as conn:
        init_feedback_schema(conn)
        existing_map = {
            str(r["id"]): dict(r)
            for r in conn.execute("SELECT * FROM app_feedback").fetchall()
        }
        for fid, title, ftype, sev, status, desc, steps, notes in validated_updates:
            curr = existing_map.get(fid)
            if not curr:
                continue
            if (
                _clean_text(curr.get("title")) == title
                and _clean_text(curr.get("feedback_type")) == ftype
                and _clean_text(curr.get("severity")) == sev
                and _clean_text(curr.get("status")) == status
                and _clean_text(curr.get("description")) == desc
                and _clean_text(curr.get("steps_to_reproduce")) == steps
                and _clean_text(curr.get("resolution_notes")) == notes
            ):
                continue
            conn.execute(
                """UPDATE app_feedback
                   SET title=?, feedback_type=?, severity=?, status=?,
                       description=?, steps_to_reproduce=?, resolution_notes=?,
                       updated_at=?
                   WHERE id=?""",
                (title, ftype, sev, status, desc, steps, notes, now, fid),
            )
            changed_count += 1
            pid = _clean_text(curr.get("project_id")) or _clean_text(active_project_id)
            if pid:
                touched_projects[pid] = touched_projects.get(pid, 0) + 1

        for pid, count in touched_projects.items():
            if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone():
                _db_core.record_audit_event(
                    pid,
                    "App feedback",
                    "Update feedback tracker",
                    count,
                    editor_name=_clean_text(editor_name),
                    details={"updated_rows": count},
                    _conn=conn,
                )
    return changed_count


def delete_app_feedback(
    feedback_ids: list[str] | tuple[str, ...] | str,
    *,
    active_project_id: str | None = None,
    editor_name: str = "",
) -> int:
    """Delete one or more feedback items, archiving each into the 30-day Recycle Bin."""
    if isinstance(feedback_ids, str):
        raw_ids = [feedback_ids]
    else:
        raw_ids = list(feedback_ids)
    normalized_ids = [_clean_text(fid) for fid in raw_ids if _clean_text(fid)]
    if not normalized_ids:
        raise ValueError("Select at least one feedback item to delete.")

    deleted_count = 0
    clean_editor = _clean_text(editor_name)

    with _db_core.connection() as conn:
        init_feedback_schema(conn)
        placeholders = ",".join("?" for _ in normalized_ids)
        rows = conn.execute(
            f"SELECT * FROM app_feedback WHERE id IN ({placeholders})",
            tuple(normalized_ids),
        ).fetchall()
        if not rows:
            raise ValueError("The selected feedback item(s) no longer exist.")

        for row in rows:
            fid = str(row["id"])
            pid = _clean_text(row["project_id"]) or _clean_text(active_project_id)
            sid = _clean_text(row["scenario_id"]) or None
            ftype = _clean_text(row["feedback_type"]) or "Feedback"
            title = _clean_text(row["title"]) or fid
            screenshot = _clean_text(row["screenshot_path"])
            extra_paths = [screenshot] if screenshot else []

            with capture_deletion_to_recycle_bin(
                conn,
                project_id=pid,
                scenario_id=sid,
                entity_type=ftype,
                entity_table="app_feedback",
                entity_id=fid,
                entity_label=title,
                deleted_by=clean_editor,
                extra_file_paths=extra_paths,
            ):
                conn.execute("DELETE FROM app_feedback WHERE id=?", (fid,))
                deleted_count += 1

            if screenshot:
                safe_unlink_upload_path(screenshot, conn=conn)

            if pid and conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone():
                _db_core.record_audit_event(
                    pid,
                    "App feedback",
                    f"Delete {ftype.lower()}",
                    1,
                    editor_name=clean_editor,
                    details={
                        "feedback_id": fid,
                        "title": title,
                        "feedback_type": ftype,
                    },
                    _conn=conn,
                )

    return deleted_count


def _matches_all_tokens(tokens: list[str], *fields: object) -> bool:
    if not tokens:
        return False
    combined = " ".join(_clean_text(f) for f in fields if f is not None).lower()
    return all(tok in combined for tok in tokens)


@cached_store_read
def global_project_search(
    project_id: str | None,
    scenario_id: str | None = None,
    query: str = "",
    *,
    include_all_scenarios: bool = False,
    limit_per_category: int = 25,
) -> pd.DataFrame:
    """Keyword-search across project-wide and scenario-specific tables."""
    clean_query = _clean_text(query)
    tokens = [tok.lower() for tok in clean_query.split() if tok.strip()]
    if not tokens:
        df = pd.DataFrame(columns=GLOBAL_SEARCH_COLUMNS)
        for col in GLOBAL_SEARCH_COLUMNS:
            df[col] = df[col].astype("string")
        return df

    pid = _clean_text(project_id)
    sid = _clean_text(scenario_id)
    results: list[dict[str, str]] = []

    with _db_core.connection() as conn:
        init_feedback_schema(conn)
        scenario_names = {
            str(r["id"]): str(r["name"] or "")
            for r in conn.execute(
                "SELECT id, name FROM planning_scenarios WHERE project_id=?",
                (pid,),
            ).fetchall()
        } if pid else {}

        def _scen_badge(row_sid: object) -> str:
            rsid = _clean_text(row_sid)
            if not rsid:
                return "All scenarios"
            sname = scenario_names.get(rsid, rsid[:8])
            return f"Scenario: {sname}"

        if pid:
            # 1. Parts Catalog
            part_rows = conn.execute(
                """SELECT id, part_number, description, subsystem, factory_nickname,
                          official_windchill_part_name, pits_tracker_number, notes
                   FROM parts WHERE project_id=?
                   ORDER BY part_number""",
                (pid,),
            ).fetchall()
            cat_count = 0
            for r in part_rows:
                if _matches_all_tokens(
                    tokens,
                    r["part_number"],
                    r["description"],
                    r["subsystem"],
                    r["factory_nickname"],
                    r["official_windchill_part_name"],
                    r["pits_tracker_number"],
                    r["notes"],
                ):
                    detail_parts = [
                        _clean_text(r["description"]),
                        f"Subsystem: {_clean_text(r['subsystem'])}"
                        if _clean_text(r["subsystem"])
                        else "",
                        f"Nickname: {_clean_text(r['factory_nickname'])}"
                        if _clean_text(r["factory_nickname"])
                        else "",
                        f"Tracker: {_clean_text(r['pits_tracker_number'])}"
                        if _clean_text(r["pits_tracker_number"])
                        else "",
                    ]
                    results.append(
                        {
                            "category": "Parts Catalog",
                            "item_label": _clean_text(r["part_number"]),
                            "detail": " · ".join(p for p in detail_parts if p),
                            "scope": "All scenarios",
                            "page_title": "Parts Catalog",
                            "page_url_path": "parts",
                            "record_id": str(r["id"]),
                        }
                    )
                    cat_count += 1
                    if cat_count >= limit_per_category:
                        break

            # 2. Fishbone Sections & Placements
            sec_rows = conn.execute(
                """SELECT id, name, section_type, description
                   FROM assembly_sections WHERE project_id=?
                   ORDER BY sequence, name""",
                (pid,),
            ).fetchall()
            cat_count = 0
            for r in sec_rows:
                if _matches_all_tokens(
                    tokens, r["name"], r["section_type"], r["description"]
                ):
                    results.append(
                        {
                            "category": "Fishbone",
                            "item_label": f"Section: {_clean_text(r['name'])}",
                            "detail": f"{_clean_text(r['section_type'])} · {_clean_text(r['description'])}".strip(
                                " ·"
                            ),
                            "scope": "All scenarios",
                            "page_title": "Fishbone",
                            "page_url_path": "fishbone",
                            "record_id": str(r["id"]),
                        }
                    )
                    cat_count += 1
                    if cat_count >= limit_per_category:
                        break

            if cat_count < limit_per_category:
                assign_rows = conn.execute(
                    """SELECT fpa.id, p.part_number, p.description AS part_desc,
                              s.name AS section_name, fpa.use_description, fpa.notes
                       FROM fishbone_part_assignments fpa
                       JOIN parts p ON p.id = fpa.part_id
                       JOIN assembly_sections s ON s.id = fpa.section_id
                       WHERE fpa.project_id=?
                       ORDER BY s.sequence, fpa.step_number, fpa.sequence""",
                    (pid,),
                ).fetchall()
                for r in assign_rows:
                    if _matches_all_tokens(
                        tokens,
                        r["part_number"],
                        r["part_desc"],
                        r["section_name"],
                        r["use_description"],
                        r["notes"],
                    ):
                        results.append(
                            {
                                "category": "Fishbone",
                                "item_label": f"{_clean_text(r['part_number'])} in {_clean_text(r['section_name'])}",
                                "detail": _clean_text(r["use_description"])
                                or _clean_text(r["part_desc"])
                                or _clean_text(r["notes"]),
                                "scope": "All scenarios",
                                "page_title": "Fishbone",
                                "page_url_path": "fishbone",
                                "record_id": str(r["id"]),
                            }
                        )
                        cat_count += 1
                        if cat_count >= limit_per_category:
                            break

            # 3. Complexity Trees (Models & Features)
            model_rows = conn.execute(
                """SELECT id, model_number, display_name, description, platform_size,
                          package_type, base_model, notes
                   FROM project_models WHERE project_id=?
                   ORDER BY model_number""",
                (pid,),
            ).fetchall()
            cat_count = 0
            for r in model_rows:
                if _matches_all_tokens(
                    tokens,
                    r["model_number"],
                    r["display_name"],
                    r["description"],
                    r["platform_size"],
                    r["package_type"],
                    r["base_model"],
                    r["notes"],
                ):
                    results.append(
                        {
                            "category": "Complexity Trees",
                            "item_label": f"Model: {_clean_text(r['model_number'])}",
                            "detail": _clean_text(r["display_name"])
                            or _clean_text(r["description"])
                            or _clean_text(r["base_model"]),
                            "scope": "All scenarios",
                            "page_title": "Complexity Trees",
                            "page_url_path": "models",
                            "record_id": str(r["id"]),
                        }
                    )
                    cat_count += 1
                    if cat_count >= limit_per_category:
                        break

            if cat_count < limit_per_category:
                feat_rows = conn.execute(
                    """SELECT id, name, category, subsystem, allowed_values, description
                       FROM complexity_features WHERE project_id=?
                       ORDER BY sequence, name""",
                    (pid,),
                ).fetchall()
                for r in feat_rows:
                    if _matches_all_tokens(
                        tokens,
                        r["name"],
                        r["category"],
                        r["subsystem"],
                        r["allowed_values"],
                        r["description"],
                    ):
                        results.append(
                            {
                                "category": "Complexity Trees",
                                "item_label": f"Feature: {_clean_text(r['name'])}",
                                "detail": f"{_clean_text(r['category'])} · {_clean_text(r['description'])}".strip(
                                    " ·"
                                ),
                                "scope": "All scenarios",
                                "page_title": "Complexity Trees",
                                "page_url_path": "models",
                                "record_id": str(r["id"]),
                            }
                        )
                        cat_count += 1
                        if cat_count >= limit_per_category:
                            break

            # 4. BOM Occurrences
            bom_rows = conn.execute(
                """SELECT id, parent_tracker_number, child_tracker_number,
                          review_status, source_state, rejection_reason
                   FROM pits_bom_occurrences WHERE project_id=?
                   ORDER BY source_row""",
                (pid,),
            ).fetchall()
            cat_count = 0
            for r in bom_rows:
                if _matches_all_tokens(
                    tokens,
                    r["parent_tracker_number"],
                    r["child_tracker_number"],
                    r["review_status"],
                    r["source_state"],
                    r["rejection_reason"],
                ):
                    results.append(
                        {
                            "category": "BOM",
                            "item_label": f"{_clean_text(r['parent_tracker_number'])} -> {_clean_text(r['child_tracker_number'])}",
                            "detail": f"{_clean_text(r['review_status'])} ({_clean_text(r['source_state'])})",
                            "scope": "All scenarios",
                            "page_title": "BOM",
                            "page_url_path": "bom_tree",
                            "record_id": str(r["id"]),
                        }
                    )
                    cat_count += 1
                    if cat_count >= limit_per_category:
                        break

            # 5. Yamazumi (Scenario-scoped)
            yam_sql = """
                SELECT ye.id, ye.description, ye.work_type, ye.work_region,
                       ya.name AS area_name, ya.scenario_id,
                       COALESCE(yp.pitch_number, 'Unassigned') AS pitch_number,
                       COALESCE(yp.pitch_name, '') AS pitch_name
                FROM yamazumi_elements ye
                JOIN yamazumi_areas ya ON ya.id = ye.area_id
                LEFT JOIN yamazumi_pitches yp ON yp.id = ye.pitch_id
                WHERE ye.project_id=?
            """
            yam_params: list[Any] = [pid]
            if sid and not include_all_scenarios:
                yam_sql += " AND ya.scenario_id=?"
                yam_params.append(sid)
            yam_sql += " ORDER BY ya.name, ye.sequence"
            yam_rows = conn.execute(yam_sql, tuple(yam_params)).fetchall()
            cat_count = 0
            for r in yam_rows:
                if _matches_all_tokens(
                    tokens,
                    r["description"],
                    r["work_type"],
                    r["work_region"],
                    r["area_name"],
                    r["pitch_number"],
                    r["pitch_name"],
                ):
                    results.append(
                        {
                            "category": "Yamazumi",
                            "item_label": f"{_clean_text(r['pitch_number'])}: {_clean_text(r['description'])}",
                            "detail": f"Area: {_clean_text(r['area_name'])} · {_clean_text(r['work_type'])}",
                            "scope": _scen_badge(r["scenario_id"]),
                            "page_title": "Yamazumi",
                            "page_url_path": "yamazumi",
                            "record_id": str(r["id"]),
                        }
                    )
                    cat_count += 1
                    if cat_count >= limit_per_category:
                        break

            # 6. Process at a Glance (Scenario-scoped)
            proc_sql = """
                SELECT id, scenario_id, sequence, station, operation, description,
                       part_number, tool, torque, quality_requirement, ergo_requirement,
                       location, resource_type, resource_detail
                FROM work_elements
                WHERE project_id=?
            """
            proc_params: list[Any] = [pid]
            if sid and not include_all_scenarios:
                proc_sql += " AND scenario_id=?"
                proc_params.append(sid)
            proc_sql += " ORDER BY sequence"
            proc_rows = conn.execute(proc_sql, tuple(proc_params)).fetchall()
            cat_count = 0
            for r in proc_rows:
                if _matches_all_tokens(
                    tokens,
                    r["station"],
                    r["operation"],
                    r["description"],
                    r["part_number"],
                    r["tool"],
                    r["torque"],
                    r["quality_requirement"],
                    r["ergo_requirement"],
                    r["location"],
                    r["resource_type"],
                    r["resource_detail"],
                ):
                    results.append(
                        {
                            "category": "Process at a Glance",
                            "item_label": f"{_clean_text(r['operation'])} ({_clean_text(r['station']) or 'Unassigned'})",
                            "detail": _clean_text(r["description"]),
                            "scope": _scen_badge(r["scenario_id"]),
                            "page_title": "Process at a Glance",
                            "page_url_path": "process",
                            "record_id": str(r["id"]),
                        }
                    )
                    cat_count += 1
                    if cat_count >= limit_per_category:
                        break

            # 7. Equipment
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='equipment_assets'"
            ).fetchone():
                eq_rows = conn.execute(
                    """SELECT ea.id, ea.name, ea.description, ea.manufacturer, ea.model, ea.notes,
                              COALESCE(et.label, '') AS type_label, COALESCE(et.tier, '') AS tier
                       FROM equipment_assets ea
                       LEFT JOIN equipment_types et ON et.id = ea.equipment_type_id
                       WHERE ea.project_id=?
                       ORDER BY ea.name""",
                    (pid,),
                ).fetchall()
                cat_count = 0
                for r in eq_rows:
                    if _matches_all_tokens(
                        tokens,
                        r["name"],
                        r["description"],
                        r["manufacturer"],
                        r["model"],
                        r["notes"],
                        r["type_label"],
                        r["tier"],
                    ):
                        results.append(
                            {
                                "category": "Equipment",
                                "item_label": _clean_text(r["name"]),
                                "detail": f"{_clean_text(r['type_label'])} · {_clean_text(r['description'])}".strip(
                                    " ·"
                                ),
                                "scope": "All scenarios",
                                "page_title": "Equipment",
                                "page_url_path": "functional_equipment",
                                "record_id": str(r["id"]),
                            }
                        )
                        cat_count += 1
                        if cat_count >= limit_per_category:
                            break

            # 8. Quality & PFMEA
            cat_count = 0
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='quality_requirements'"
            ).fetchone():
                q_rows = conn.execute(
                    """SELECT id, unique_identifier, requirement_type, description, tolerances, unit
                       FROM quality_requirements WHERE project_id=?
                       ORDER BY unique_identifier""",
                    (pid,),
                ).fetchall()
                for r in q_rows:
                    if _matches_all_tokens(
                        tokens,
                        r["unique_identifier"],
                        r["requirement_type"],
                        r["description"],
                        r["tolerances"],
                        r["unit"],
                    ):
                        results.append(
                            {
                                "category": "Quality",
                                "item_label": f"{_clean_text(r['unique_identifier'])} ({_clean_text(r['requirement_type'])})",
                                "detail": _clean_text(r["description"]),
                                "scope": "All scenarios",
                                "page_title": "Quality",
                                "page_url_path": "functional_quality",
                                "record_id": str(r["id"]),
                            }
                        )
                        cat_count += 1
                        if cat_count >= limit_per_category:
                            break

            if cat_count < limit_per_category and conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pfmea_entries'"
            ).fetchone():
                pf_sql = """
                    SELECT id, scenario_id, potential_failure_mode, class_code,
                           process_operation_snapshot, process_description_snapshot,
                           process_pitch_snapshot
                    FROM pfmea_entries WHERE project_id=?
                """
                pf_params: list[Any] = [pid]
                if sid and not include_all_scenarios:
                    pf_sql += " AND scenario_id=?"
                    pf_params.append(sid)
                pf_rows = conn.execute(pf_sql, tuple(pf_params)).fetchall()
                for r in pf_rows:
                    if _matches_all_tokens(
                        tokens,
                        r["potential_failure_mode"],
                        r["class_code"],
                        r["process_operation_snapshot"],
                        r["process_description_snapshot"],
                        r["process_pitch_snapshot"],
                    ):
                        results.append(
                            {
                                "category": "Quality (PFMEA)",
                                "item_label": f"PFMEA: {_clean_text(r['potential_failure_mode'])}",
                                "detail": f"Op: {_clean_text(r['process_operation_snapshot'])} · {_clean_text(r['process_description_snapshot'])}".strip(
                                    " ·"
                                ),
                                "scope": _scen_badge(r["scenario_id"]),
                                "page_title": "Quality",
                                "page_url_path": "functional_quality",
                                "record_id": str(r["id"]),
                            }
                        )
                        cat_count += 1
                        if cat_count >= limit_per_category:
                            break

            # 9. Ergonomics
            ergo_sql = """
                SELECT er.id, er.scenario_id, er.status, er.risk_classification,
                       er.reviewer, er.notes, er.legacy_description,
                       COALESCE(we.operation, '') AS operation
                FROM ergonomics_reviews er
                LEFT JOIN work_elements we ON we.id = er.work_element_id
                WHERE er.project_id=?
            """
            ergo_params: list[Any] = [pid]
            if sid and not include_all_scenarios:
                ergo_sql += " AND er.scenario_id=?"
                ergo_params.append(sid)
            ergo_rows = conn.execute(ergo_sql, tuple(ergo_params)).fetchall()
            cat_count = 0
            for r in ergo_rows:
                if _matches_all_tokens(
                    tokens,
                    r["status"],
                    r["risk_classification"],
                    r["reviewer"],
                    r["notes"],
                    r["legacy_description"],
                    r["operation"],
                ):
                    results.append(
                        {
                            "category": "Ergonomics",
                            "item_label": f"Ergo Review ({_clean_text(r['operation']) or 'Unlinked'})",
                            "detail": f"{_clean_text(r['risk_classification'])} · {_clean_text(r['notes']) or _clean_text(r['legacy_description'])}".strip(
                                " ·"
                            ),
                            "scope": _scen_badge(r["scenario_id"]),
                            "page_title": "Ergonomics",
                            "page_url_path": "functional_ergonomics",
                            "record_id": str(r["id"]),
                        }
                    )
                    cat_count += 1
                    if cat_count >= limit_per_category:
                        break

            # 10. Safety
            saf_sql = """
                SELECT sr.id, sr.scenario_id, sr.requirement_description, sr.ppe,
                       COALESCE(we.operation, '') AS operation
                FROM safety_requirements sr
                LEFT JOIN work_elements we ON we.id = sr.work_element_id
                WHERE sr.project_id=?
            """
            saf_params: list[Any] = [pid]
            if sid and not include_all_scenarios:
                saf_sql += " AND sr.scenario_id=?"
                saf_params.append(sid)
            saf_rows = conn.execute(saf_sql, tuple(saf_params)).fetchall()
            cat_count = 0
            for r in saf_rows:
                if _matches_all_tokens(
                    tokens,
                    r["requirement_description"],
                    r["ppe"],
                    r["operation"],
                ):
                    results.append(
                        {
                            "category": "Safety",
                            "item_label": f"Safety ({_clean_text(r['operation']) or 'Step'}): {_clean_text(r['requirement_description'])}",
                            "detail": f"PPE: {_clean_text(r['ppe'])}"
                            if _clean_text(r["ppe"])
                            else "",
                            "scope": _scen_badge(r["scenario_id"]),
                            "page_title": "Safety",
                            "page_url_path": "functional_safety",
                            "record_id": str(r["id"]),
                        }
                    )
                    cat_count += 1
                    if cat_count >= limit_per_category:
                        break

            # 11. Questions & Concerns
            con_rows = conn.execute(
                """SELECT id, category, subject, detail, owner, priority, status,
                          related_part, related_station
                   FROM concerns WHERE project_id=?
                   ORDER BY created_at DESC""",
                (pid,),
            ).fetchall()
            cat_count = 0
            for r in con_rows:
                if _matches_all_tokens(
                    tokens,
                    r["category"],
                    r["subject"],
                    r["detail"],
                    r["owner"],
                    r["priority"],
                    r["status"],
                    r["related_part"],
                    r["related_station"],
                ):
                    results.append(
                        {
                            "category": "Questions & Concerns",
                            "item_label": f"{_clean_text(r['category'])}: {_clean_text(r['subject'])}",
                            "detail": f"{_clean_text(r['status'])} ({_clean_text(r['priority'])}) · {_clean_text(r['detail'])}".strip(
                                " ·"
                            ),
                            "scope": "All scenarios",
                            "page_title": "Questions and concerns",
                            "page_url_path": "concerns",
                            "record_id": str(r["id"]),
                        }
                    )
                    cat_count += 1
                    if cat_count >= limit_per_category:
                        break

        # 12. App Feedback (Bugs & Feature Suggestions)
        fb_rows = conn.execute(
            """SELECT id, feedback_type, severity, status, title, description,
                      steps_to_reproduce, resolution_notes, page_context
               FROM app_feedback
               ORDER BY created_at DESC"""
        ).fetchall()
        cat_count = 0
        for r in fb_rows:
            if _matches_all_tokens(
                tokens,
                r["feedback_type"],
                r["severity"],
                r["status"],
                r["title"],
                r["description"],
                r["steps_to_reproduce"],
                r["resolution_notes"],
                r["page_context"],
            ):
                results.append(
                    {
                        "category": "App Feedback",
                        "item_label": f"{_clean_text(r['feedback_type'])}: {_clean_text(r['title'])}",
                        "detail": f"{_clean_text(r['status'])} ({_clean_text(r['severity'])}) · {_clean_text(r['description'])}",
                        "scope": "App-wide",
                        "page_title": "Bug Reports & Feature Ideas",
                        "page_url_path": "__feedback_tab__",
                        "record_id": str(r["id"]),
                    }
                )
                cat_count += 1
                if cat_count >= limit_per_category:
                    break

    if not results:
        df = pd.DataFrame(columns=GLOBAL_SEARCH_COLUMNS)
        for col in GLOBAL_SEARCH_COLUMNS:
            df[col] = df[col].astype("string")
        return df

    return pd.DataFrame(results, columns=GLOBAL_SEARCH_COLUMNS)


@cached_store_read
def critical_thread_status_counts(
    project_id: str | None,
    scenario_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return live progress metrics for each step in the PAAG Critical Thread."""
    pid = _clean_text(project_id)
    sid = _clean_text(scenario_id)

    if not pid:
        return []

    with _db_core.connection() as conn:
        pits_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM pits_records WHERE project_id=?", (pid,)
            ).fetchone()[0]
            or 0
        )
        bom_import_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM pits_bom_imports WHERE project_id=?", (pid,)
            ).fetchone()[0]
            or 0
        )
        models_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM project_models WHERE project_id=?", (pid,)
            ).fetchone()[0]
            or 0
        )
        features_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM complexity_features WHERE project_id=?", (pid,)
            ).fetchone()[0]
            or 0
        )
        bom_total = int(
            conn.execute(
                "SELECT COUNT(*) FROM pits_bom_occurrences WHERE project_id=?", (pid,)
            ).fetchone()[0]
            or 0
        )
        bom_approved = int(
            conn.execute(
                "SELECT COUNT(*) FROM pits_bom_occurrences WHERE project_id=? AND review_status='Approved'",
                (pid,),
            ).fetchone()[0]
            or 0
        )
        parts_total = int(
            conn.execute(
                "SELECT COUNT(*) FROM parts WHERE project_id=?", (pid,)
            ).fetchone()[0]
            or 0
        )
        sections_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM assembly_sections WHERE project_id=?", (pid,)
            ).fetchone()[0]
            or 0
        )
        placements_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM fishbone_part_assignments WHERE project_id=?",
                (pid,),
            ).fetchone()[0]
            or 0
        )

        if sid:
            areas_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM yamazumi_areas WHERE project_id=? AND scenario_id=?",
                    (pid, sid),
                ).fetchone()[0]
                or 0
            )
            pitches_count = int(
                conn.execute(
                    """SELECT COUNT(*) FROM yamazumi_pitches yp
                       JOIN yamazumi_areas ya ON ya.id = yp.area_id
                       WHERE yp.project_id=? AND ya.scenario_id=?""",
                    (pid, sid),
                ).fetchone()[0]
                or 0
            )
            yam_elements_count = int(
                conn.execute(
                    """SELECT COUNT(*) FROM yamazumi_elements ye
                       JOIN yamazumi_areas ya ON ya.id = ye.area_id
                       WHERE ye.project_id=? AND ya.scenario_id=?""",
                    (pid, sid),
                ).fetchone()[0]
                or 0
            )
            process_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM work_elements WHERE project_id=? AND scenario_id=?",
                    (pid, sid),
                ).fetchone()[0]
                or 0
            )
            ergo_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM ergonomics_reviews WHERE project_id=? AND scenario_id=?",
                    (pid, sid),
                ).fetchone()[0]
                or 0
            )
            safety_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM safety_requirements WHERE project_id=? AND scenario_id=?",
                    (pid, sid),
                ).fetchone()[0]
                or 0
            )
        else:
            areas_count = 0
            pitches_count = 0
            yam_elements_count = 0
            process_count = 0
            ergo_count = 0
            safety_count = 0

        quality_count = (
            int(
                conn.execute(
                    "SELECT COUNT(*) FROM quality_requirements WHERE project_id=?",
                    (pid,),
                ).fetchone()[0]
                or 0
            )
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='quality_requirements'"
            ).fetchone()
            else 0
        )
        equipment_count = (
            int(
                conn.execute(
                    "SELECT COUNT(*) FROM equipment_assets WHERE project_id=?",
                    (pid,),
                ).fetchone()[0]
                or 0
            )
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='equipment_assets'"
            ).fetchone()
            else 0
        )

    return [
        {
            "step_number": 1,
            "title": "Import PITs (Source Evidence)",
            "scope": "All scenarios",
            "page_url_path": "pits_exchange",
            "page_title": "Import PITs",
            "metric_summary": f"{pits_count} PITS records · {bom_import_count} BOM workbook imports",
            "populated": (pits_count + bom_import_count) > 0,
            "description": (
                "Import Product Architecture / PITS tracker workbooks as source evidence. "
                "Changed records enter reconciliation without silently overwriting reviewed planning decisions."
            ),
        },
        {
            "step_number": 2,
            "title": "Complexity Trees (Models & Features)",
            "scope": "All scenarios",
            "page_url_path": "models",
            "page_title": "Complexity Trees",
            "metric_summary": f"{models_count} models · {features_count} complexity features",
            "populated": (models_count + features_count) > 0,
            "description": (
                "Define product models, platform sizes, and differentiating complexity features "
                "so parts and assemblies can be mapped to model applicability rules."
            ),
        },
        {
            "step_number": 3,
            "title": "BOM Reconciliation (EBOM -> MBOM)",
            "scope": "All scenarios",
            "page_url_path": "bom_tree",
            "page_title": "BOM",
            "metric_summary": f"{bom_approved} approved / {bom_total} total BOM occurrences",
            "populated": bom_total > 0,
            "description": (
                "Review PITS BOM parent-child occurrences, resolve validation issues, "
                "and approve placements into Fishbone assembly sections."
            ),
        },
        {
            "step_number": 4,
            "title": "Parts Catalog",
            "scope": "All scenarios + scenario active flags",
            "page_url_path": "parts",
            "page_title": "Parts Catalog",
            "metric_summary": f"{parts_total} catalog parts",
            "populated": parts_total > 0,
            "description": (
                "Maintain the project-wide part master, reference images, annotated callouts, "
                "feature applicability rules, and scenario-specific Active status."
            ),
        },
        {
            "step_number": 5,
            "title": "Fishbone Assembly Structure",
            "scope": "All scenarios",
            "page_url_path": "fishbone",
            "page_title": "Fishbone",
            "metric_summary": f"{sections_count} sections · {placements_count} part placements",
            "populated": sections_count > 0,
            "description": (
                "Structure main-line, subassembly, and feeder sections, sequence part placements, "
                "and define manufacturing assemblies across the assembly grid."
            ),
        },
        {
            "step_number": 6,
            "title": "Yamazumi Line Balancing",
            "scope": "Active scenario",
            "page_url_path": "yamazumi",
            "page_title": "Yamazumi",
            "metric_summary": f"{areas_count} areas · {pitches_count} pitches · {yam_elements_count} work elements",
            "populated": yam_elements_count > 0 or pitches_count > 0,
            "description": (
                "Balance operator work elements against scenario takt time across pitches, "
                "assign material groups from Fishbone placements, and push reviewed stacks to Process at a Glance."
            ),
        },
        {
            "step_number": 7,
            "title": "Process at a Glance",
            "scope": "Active scenario",
            "page_url_path": "process",
            "page_title": "Process at a Glance",
            "metric_summary": f"{process_count} Process steps",
            "populated": process_count > 0,
            "description": (
                "Maintain the authoritative scenario Process plan with deterministic Op IDs, "
                "part handling/consumption groups, visual aids, and functional review links."
            ),
        },
        {
            "step_number": 8,
            "title": "Pin Map & Functional Reviews",
            "scope": "Active scenario + shared repositories",
            "page_url_path": "pin_map",
            "page_title": "Pin Map",
            "metric_summary": (
                f"{quality_count} Quality reqs · {equipment_count} Equipment · "
                f"{ergo_count} Ergo · {safety_count} Safety"
            ),
            "populated": (quality_count + equipment_count + ergo_count + safety_count) > 0,
            "description": (
                "Review the derived Pin Map and complete functional reviews across Equipment, "
                "Ergonomics, Quality (Requirements, Torque, PFMEA, Control Plan), Materials, and Safety."
            ),
        },
    ]


def save_feedback_screenshot(
    raw_bytes: bytes,
    filename: str = "feedback.png",
) -> str:
    """Validate and save an uploaded or pasted feedback screenshot under data/uploads/."""
    from io import BytesIO
    from pathlib import Path
    from PIL import Image

    if not raw_bytes:
        raise ValueError("Screenshot file is empty.")
    max_bytes = 10 * 1024 * 1024
    if len(raw_bytes) > max_bytes:
        raise ValueError("Screenshot must be 10 MB or smaller.")

    try:
        with Image.open(BytesIO(raw_bytes)) as img:
            img.verify()
            fmt = str(img.format or "").upper()
    except Exception as exc:
        raise ValueError("Upload a valid PNG, JPG, or WEBP screenshot image.") from exc

    ext_by_fmt = {
        "PNG": ".png",
        "JPEG": ".jpg",
        "JPG": ".jpg",
        "WEBP": ".webp",
    }
    ext = ext_by_fmt.get(fmt) or Path(filename or "feedback.png").suffix.lower() or ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        ext = ".png"

    _db_core.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = _db_core.UPLOAD_DIR / f"feedback_{uuid4().hex[:12]}{ext}"
    target.write_bytes(raw_bytes)
    try:
        return target.relative_to(_db_core.ROOT).as_posix()
    except ValueError:
        return target.as_posix()


__domain_exports__ = [
    "FEEDBACK_TYPES",
    "FEEDBACK_SEVERITIES",
    "FEEDBACK_STATUSES",
    "FEEDBACK_COLUMNS",
    "GLOBAL_SEARCH_COLUMNS",
    "init_feedback_schema",
    "create_app_feedback",
    "list_app_feedback",
    "open_app_feedback_count",
    "update_app_feedback",
    "save_bulk_app_feedback",
    "delete_app_feedback",
    "global_project_search",
    "critical_thread_status_counts",
    "save_feedback_screenshot",
]
