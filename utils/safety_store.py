"""Domain persistence extracted from the historical utils.store module."""

from __future__ import annotations

import json
import sys as _sys
from utils import db_core as _db_core

globals().update({name: value for name, value in vars(_db_core).items() if not name.startswith('__')})

STANDARD_PPE_OPTIONS = [
    "Safety Glasses",
    "Cut-Resistant Gloves",
    "Hearing Protection",
    "Steel-Toe Shoes",
    "Bump Cap / Hard Hat",
    "Face Shield",
    "Heat-Resistant Gloves",
    "High-Vis Vest",
    "Respirator / Dust Mask",
    "ESD Grounding Strap",
    "Chemical Gloves",
    "Chemical Apron",
]

def parse_ppe(val: object) -> list[str]:
    """Parse stored PPE value into a list of strings."""
    if val is None:
        return []
    try:
        if bool(pd.isna(val)):
            return []
    except (TypeError, ValueError):
        pass
    if isinstance(val, (list, tuple, set)):
        return [str(item).strip() for item in val if str(item).strip()]
    s = str(val).strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass
    return [p.strip() for p in s.split(",") if p.strip()]

def serialize_ppe(val: object) -> str:
    """Serialize PPE list or string into stored JSON string."""
    items = parse_ppe(val)
    return json.dumps(items) if items else ""

def safety_requirements(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Load scenario-specific Safety requirements with current Process labels."""
    columns = [
        "id", "project_id", "scenario_id", "work_element_id",
        "requirement_description", "ppe", "active", "created_at", "updated_at",
        "work_element_label", "pitch",
    ]
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        rows = conn.execute(
            """SELECT requirement.*,
                      COALESCE(requirement.ppe, '') AS ppe,
                      COALESCE(
                          (SELECT NULLIF(TRIM(yamazumi.description), '')
                           FROM yamazumi_elements yamazumi
                           WHERE yamazumi.project_id=requirement.project_id
                             AND yamazumi.process_element_id=requirement.work_element_id
                           ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                          NULLIF(TRIM(work.operation), ''), '') AS work_element_label,
                      COALESCE(work.station, '') AS pitch
               FROM safety_requirements requirement
               JOIN work_elements work
                 ON work.id=requirement.work_element_id
                AND work.project_id=requirement.project_id
                AND work.scenario_id=requirement.scenario_id
               WHERE requirement.project_id=? AND requirement.scenario_id=?
               ORDER BY work.sequence, requirement.created_at, requirement.id""",
            (project_id, scenario_id),
        ).fetchall()
    if not rows:
        return pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "scenario_id": pd.Series(dtype="string"),
            "work_element_id": pd.Series(dtype="string"),
            "requirement_description": pd.Series(dtype="string"),
            "ppe": pd.Series(dtype="object"),
            "active": pd.Series(dtype="bool"),
            "created_at": pd.Series(dtype="string"),
            "updated_at": pd.Series(dtype="string"),
            "work_element_label": pd.Series(dtype="string"),
            "pitch": pd.Series(dtype="string"),
        })
    result_rows = []
    for row in rows:
        d = dict(row)
        d["ppe"] = parse_ppe(d.get("ppe"))
        result_rows.append(d)
    return pd.DataFrame(result_rows, columns=columns)

def save_safety_requirements(
    project_id: str,
    scenario_id: str,
    edited: pd.DataFrame,
    editor_name: str,
) -> dict:
    """Atomically validate and save Safety rows without deleting omitted rows."""
    editor = str(editor_name or "").strip()
    if not editor:
        raise ValueError("Enter the Current editor before saving Safety requirements.")
    timestamp = now_iso()
    prepared: list[dict] = []
    for _, row in edited.iterrows():
        work_element_id = str(row.get("work_element_id") or "").strip()
        description = str(row.get("requirement_description") or "").strip()
        raw_ppe = row.get("ppe")
        ppe_list = parse_ppe(raw_ppe)
        ppe_str = serialize_ppe(ppe_list)
        if not work_element_id and not description and not ppe_list:
            continue
        if not work_element_id:
            raise ValueError("Process Function is required for every Safety requirement.")
        if not description and ppe_list:
            description = f"PPE: {', '.join(ppe_list)}"
        elif not description:
            raise ValueError("Requirement description or PPE is required for every Safety requirement.")
        raw_id = row.get("id")
        requirement_id = (
            str(raw_id).strip()
            if raw_id is not None and not pd.isna(raw_id) and str(raw_id).strip()
            else str(uuid4())
        )
        raw_active = row.get("active", True)
        active = 1 if raw_active is None or pd.isna(raw_active) else int(bool(raw_active))
        prepared.append({
            "id": requirement_id,
            "work_element_id": work_element_id,
            "requirement_description": description,
            "ppe": ppe_str,
            "active": active,
        })
    if len({row["id"] for row in prepared}) != len(prepared):
        raise ValueError("Safety requirement identities must be unique.")
    changed_ids: list[str] = []
    created_ids: list[str] = []
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        valid_work_ids = {
            str(row["id"])
            for row in conn.execute(
                """SELECT id FROM work_elements
                   WHERE project_id=? AND scenario_id=?""",
                (project_id, scenario_id),
            ).fetchall()
        }
        if any(row["work_element_id"] not in valid_work_ids for row in prepared):
            raise ValueError(
                "Every Process Function must belong to the active project and scenario."
            )
        existing = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                """SELECT * FROM safety_requirements
                   WHERE project_id=? AND scenario_id=?""",
                (project_id, scenario_id),
            ).fetchall()
        }
        for row in prepared:
            previous = existing.get(row["id"])
            if previous:
                changed = any(
                    (previous.get(field) or "") != (row[field] or "") if field == "ppe"
                    else previous.get(field) != row[field]
                    for field in ("work_element_id", "requirement_description", "ppe", "active")
                )
                if not changed:
                    continue
                conn.execute(
                    """UPDATE safety_requirements
                       SET work_element_id=?, requirement_description=?, ppe=?, active=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=?""",
                    (
                        row["work_element_id"], row["requirement_description"],
                        row["ppe"], row["active"], timestamp, row["id"], project_id, scenario_id,
                    ),
                )
                changed_ids.append(row["id"])
            else:
                conn.execute(
                    """INSERT INTO safety_requirements
                       (id, project_id, scenario_id, work_element_id,
                        requirement_description, ppe, active, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["id"], project_id, scenario_id, row["work_element_id"],
                        row["requirement_description"], row["ppe"], row["active"], timestamp, timestamp,
                    ),
                )
                created_ids.append(row["id"])
        row_count = len(created_ids) + len(changed_ids)
        if row_count:
            record_audit_event(
                project_id,
                "Safety requirements",
                "Save & Refresh",
                row_count,
                editor,
                {
                    "scenario_id": scenario_id,
                    "created_ids": created_ids,
                    "updated_ids": changed_ids,
                    "updated_at": timestamp,
                },
                _conn=conn,
            )
    return {
        "row_count": len(created_ids) + len(changed_ids),
        "created_ids": created_ids,
        "updated_ids": changed_ids,
        "timestamp": timestamp,
    }

def delete_safety_requirements(
    project_id: str,
    scenario_id: str,
    requirement_ids: list[str],
    editor_name: str,
) -> dict:
    """Delete selected Safety rows with boundary validation and one audit event."""
    editor = str(editor_name or "").strip()
    if not editor:
        raise ValueError("Enter the Current editor before deleting Safety requirements.")
    ids = list(dict.fromkeys(str(value).strip() for value in requirement_ids if str(value).strip()))
    timestamp = now_iso()
    if not ids:
        return {"row_count": 0, "timestamp": timestamp}
    placeholders = ",".join("?" for _ in ids)
    with connection() as conn:
        found = conn.execute(
            f"""SELECT id FROM safety_requirements
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        ).fetchall()
        if len(found) != len(ids):
            raise ValueError(
                "One or more Safety requirements changed or no longer belong to the active scenario."
            )
        conn.execute(
            f"""DELETE FROM safety_requirements
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        )
        record_audit_event(
            project_id,
            "Safety requirements",
            "Delete" if len(ids) == 1 else "Bulk delete",
            len(ids),
            editor,
            {"scenario_id": scenario_id, "requirement_ids": ids, "updated_at": timestamp},
            _conn=conn,
        )
    return {"row_count": len(ids), "timestamp": timestamp}

def safety_requirement_delete_impact(
    project_id: str, scenario_id: str, work_element_ids: list[str]
) -> dict:
    """Describe Safety rows that would cascade with Process-step deletion."""
    ids = list(dict.fromkeys(str(value).strip() for value in work_element_ids if str(value).strip()))
    if not ids:
        return {"requirement_count": 0, "work_element_count": 0}
    placeholders = ",".join("?" for _ in ids)
    with connection() as conn:
        valid_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM work_elements
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        ).fetchone()[0])
        if valid_count != len(ids):
            raise ValueError(
                "One or more Process steps changed or no longer belong to the active scenario."
            )
        row = conn.execute(
            f"""SELECT COUNT(*) AS requirement_count,
                       COUNT(DISTINCT work_element_id) AS work_element_count
                FROM safety_requirements
                WHERE project_id=? AND scenario_id=?
                  AND work_element_id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        ).fetchone()
    return {
        "requirement_count": int(row["requirement_count"] or 0),
        "work_element_count": int(row["work_element_count"] or 0),
    }

def safety_requirement_history(
    project_id: str, scenario_id: str, limit: int = 50
) -> pd.DataFrame:
    rows = query(
        """SELECT action, row_count, editor_name, details, created_at
           FROM audit_log
           WHERE project_id=? AND table_name='Safety requirements'
             AND json_extract(details, '$.scenario_id')=?
           ORDER BY created_at DESC LIMIT ?""",
        (project_id, scenario_id, int(limit)),
    )
    return pd.DataFrame(rows)

__domain_exports__ = [
    'safety_requirements', 'save_safety_requirements', 'delete_safety_requirements',
    'safety_requirement_delete_impact', 'safety_requirement_history',
    'STANDARD_PPE_OPTIONS', 'parse_ppe', 'serialize_ppe',
]
for _export_name in __domain_exports__:
    if callable(globals()[_export_name]):
        globals()[_export_name] = _db_core.domain_entrypoint(globals()[_export_name])
_db_core.register_domain_module(_sys.modules[__name__], __domain_exports__)
