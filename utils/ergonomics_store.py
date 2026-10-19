"""Domain persistence extracted from the historical utils.store module."""

from __future__ import annotations

import base64
from pathlib import Path
import sys as _sys
from typing import Any
from uuid import uuid4
from utils import db_core as _db_core

globals().update({name: value for name, value in vars(_db_core).items() if not name.startswith('__')})

DEFAULT_ERGONOMIC_HAZARD_OPTIONS: tuple[str, ...] = (
    "Heavy lift (≥ 33 lb)",
    "Awkward posture (bending / twisting / reaching)",
    "Repetitive motion",
    "Pinch point",
    "High grip / push / pull force",
    "Contact stress",
    "Vibration",
    "Static load / sustained hold",
)

def ensure_default_ergonomic_hazard_options(project_id: str) -> int:
    """Seed standard ergonomics hazard options if the project has none defined."""
    timestamp = now_iso()
    with connection() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            return 0
        count = conn.execute(
            "SELECT COUNT(*) FROM ergonomic_hazard_options WHERE project_id=?",
            (project_id,),
        ).fetchone()[0]
        if count > 0:
            return 0
        for label in DEFAULT_ERGONOMIC_HAZARD_OPTIONS:
            conn.execute(
                """INSERT INTO ergonomic_hazard_options
                   (id, project_id, label, active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), project_id, label, 1, timestamp, timestamp),
            )
        return len(DEFAULT_ERGONOMIC_HAZARD_OPTIONS)

def create_or_get_ergonomic_hazard_option(project_id: str, label: str) -> str:
    """Create a new ergonomic hazard option if it does not already exist, and return its ID."""
    clean_label = str(label or "").strip()
    if not clean_label:
        raise ValueError("Hazard label cannot be empty.")
    timestamp = now_iso()
    with connection() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ValueError("The selected project no longer exists.")
        existing = conn.execute(
            "SELECT id FROM ergonomic_hazard_options WHERE project_id=? AND LOWER(label)=LOWER(?)",
            (project_id, clean_label),
        ).fetchone()
        if existing:
            return str(existing["id"])
        new_id = str(uuid4())
        conn.execute(
            """INSERT INTO ergonomic_hazard_options
               (id, project_id, label, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (new_id, project_id, clean_label, 1, timestamp, timestamp),
        )
        return new_id

def ergonomic_hazard_options(project_id: str) -> pd.DataFrame:
    columns = [
        "id",
        "project_id",
        "label",
        "active",
        "created_at",
        "updated_at",
        "selection_count",
    ]
    with connection() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ValueError("The selected project no longer exists.")
        rows = conn.execute(
            """SELECT option.*,
                      COUNT(selection.id) AS selection_count
               FROM ergonomic_hazard_options option
               LEFT JOIN ergonomics_review_hazard_selections selection
                 ON selection.hazard_option_id=option.id
               WHERE option.project_id=?
               GROUP BY option.id
               ORDER BY option.active DESC, option.label COLLATE NOCASE, option.id""",
            (project_id,),
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows], columns=columns)

def save_ergonomic_hazard_option_rows(project_id: str, edited: pd.DataFrame) -> dict:
    rows = edited.to_dict("records")
    labels = [str(row.get("label") or "").strip() for row in rows]
    if any(not label for label in labels):
        raise ValueError("Every Ergonomics hazard option requires a Label.")
    if len({label.casefold() for label in labels}) != len(labels):
        raise ValueError("Ergonomics hazard option labels must be unique within this project.")
    timestamp = now_iso()
    with connection() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ValueError("The selected project no longer exists.")
        existing = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM ergonomic_hazard_options WHERE project_id=?",
                (project_id,),
            ).fetchall()
        }
        supplied_ids = {
            str(row.get("id") or "").strip()
            for row in rows
            if str(row.get("id") or "").strip()
        }
        if set(existing) - supplied_ids:
            raise ValueError(
                "Remove Ergonomics hazard options through the confirmed deletion workflow."
            )
        created_ids: list[str] = []
        updated_ids: list[str] = []
        try:
            for row, label in zip(rows, labels):
                option_id = str(row.get("id") or "").strip()
                active = 1 if bool(row.get("active", True)) else 0
                if option_id:
                    if option_id not in existing:
                        raise ValueError(
                            "An Ergonomics hazard option changed or no longer exists. "
                            "Refresh and try again."
                        )
                    conn.execute(
                        """UPDATE ergonomic_hazard_options
                           SET label=?, active=?, updated_at=?
                           WHERE id=? AND project_id=?""",
                        (label, active, timestamp, option_id, project_id),
                    )
                    updated_ids.append(option_id)
                else:
                    option_id = str(uuid4())
                    conn.execute(
                        """INSERT INTO ergonomic_hazard_options
                           (id, project_id, label, active, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (option_id, project_id, label, active, timestamp, timestamp),
                    )
                    created_ids.append(option_id)
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "Ergonomics hazard option labels must be unique within this project."
            ) from exc
    return {
        "row_count": len(created_ids) + len(updated_ids),
        "created_ids": created_ids,
        "updated_ids": updated_ids,
        "timestamp": timestamp,
    }

def ergonomic_hazard_option_delete_impact(
    project_id: str, option_ids: list[str]
) -> dict:
    ids = list(dict.fromkeys(str(value).strip() for value in option_ids if str(value).strip()))
    if not ids:
        return {"option_count": 0, "selection_count": 0, "review_count": 0, "labels": []}
    placeholders = ",".join("?" for _ in ids)
    with connection() as conn:
        options = conn.execute(
            f"""SELECT id, label FROM ergonomic_hazard_options
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *ids),
        ).fetchall()
        if len(options) != len(ids):
            raise ValueError(
                "One or more Ergonomics hazard options changed. Refresh and try again."
            )
        selections = conn.execute(
            f"""SELECT ergonomics_review_id
                FROM ergonomics_review_hazard_selections
                WHERE project_id=? AND hazard_option_id IN ({placeholders})""",
            (project_id, *ids),
        ).fetchall()
    return {
        "option_count": len(ids),
        "selection_count": len(selections),
        "review_count": len({str(row["ergonomics_review_id"]) for row in selections}),
        "labels": [str(row["label"]) for row in options],
    }

def delete_ergonomic_hazard_options(project_id: str, option_ids: list[str]) -> dict:
    ids = list(dict.fromkeys(str(value).strip() for value in option_ids if str(value).strip()))
    impact = ergonomic_hazard_option_delete_impact(project_id, ids)
    timestamp = now_iso()
    if not ids:
        return impact | {"row_count": 0, "timestamp": timestamp}
    placeholders = ",".join("?" for _ in ids)
    with connection() as conn:
        cursor = conn.execute(
            f"""DELETE FROM ergonomic_hazard_options
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *ids),
        )
        if int(cursor.rowcount) != len(ids):
            raise ValueError(
                "One or more Ergonomics hazard options changed. Refresh and try again."
            )
    return impact | {"row_count": len(ids), "timestamp": timestamp}

def ergonomics_reviews(
    project_id: str,
    scenario_id: str,
    work_element_id: str | None = None,
) -> pd.DataFrame:
    columns = [
        "id",
        "project_id",
        "scenario_id",
        "work_element_id",
        "process_part_option_id",
        "status",
        "risk_classification",
        "reviewer",
        "notes",
        "requested_due_date",
        "legacy_description",
        "created_at",
        "updated_at",
        "hazard_option_ids",
        "hazard_labels",
        "work_element_label",
        "pitch",
    ]
    params: tuple = (project_id, scenario_id)
    work_clause = ""
    if work_element_id:
        work_clause = " AND review.work_element_id=?"
        params = (*params, work_element_id)
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        review_rows = [
            dict(row)
            for row in conn.execute(
                f"""SELECT review.*,
                           COALESCE(
                               (SELECT NULLIF(TRIM(yamazumi.description), '')
                                FROM yamazumi_elements yamazumi
                                WHERE yamazumi.project_id=review.project_id
                                  AND yamazumi.process_element_id=review.work_element_id
                                ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                               NULLIF(TRIM(work.operation), ''),
                               ''
                            ) AS work_element_label,
                           COALESCE(
                               NULLIF(TRIM(work.station), ''),
                               (SELECT NULLIF(TRIM(pitch.pitch_number), '')
                                FROM yamazumi_elements yamazumi
                                JOIN yamazumi_pitches pitch ON pitch.id=yamazumi.pitch_id
                                WHERE yamazumi.project_id=review.project_id
                                  AND (yamazumi.process_element_id=review.work_element_id
                                       OR (yamazumi.process_element_id IS NULL AND yamazumi.id=review.work_element_id))
                                ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                               ''
                           ) AS pitch
                    FROM ergonomics_reviews review
                    LEFT JOIN work_elements work
                      ON work.id=review.work_element_id
                     AND work.project_id=review.project_id
                     AND work.scenario_id=review.scenario_id
                    WHERE review.project_id=? AND review.scenario_id=?{work_clause}
                    ORDER BY review.requested_due_date, review.created_at, review.id""",
                params,
            ).fetchall()
        ]
        review_ids = [str(row["id"]) for row in review_rows]
        selections_by_review: dict[str, list[dict]] = {review_id: [] for review_id in review_ids}
        if review_ids:
            placeholders = ",".join("?" for _ in review_ids)
            for selection in conn.execute(
                f"""SELECT selection.ergonomics_review_id, selection.hazard_option_id,
                            option.label
                     FROM ergonomics_review_hazard_selections selection
                     JOIN ergonomic_hazard_options option
                       ON option.id=selection.hazard_option_id
                     WHERE selection.ergonomics_review_id IN ({placeholders})
                     ORDER BY selection.sequence, option.label COLLATE NOCASE, selection.id""",
                tuple(review_ids),
            ).fetchall():
                selections_by_review[str(selection["ergonomics_review_id"])].append(
                    dict(selection)
                )
    for row in review_rows:
        selections = selections_by_review[str(row["id"])]
        row["hazard_option_ids"] = [str(item["hazard_option_id"]) for item in selections]
        row["hazard_labels"] = [str(item["label"]) for item in selections]
        row["legacy_description"] = str(row.get("legacy_description") or "")
    return pd.DataFrame(review_rows, columns=columns)

def ergonomics_work_elements(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Return scenario Process steps with Yamazumi-description-first labels."""
    columns = ["id", "work_element_label", "pitch", "sequence"]
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        rows = conn.execute(
            """SELECT work.id,
                      COALESCE(
                          (SELECT NULLIF(TRIM(yamazumi.description), '')
                           FROM yamazumi_elements yamazumi
                           WHERE yamazumi.project_id=work.project_id
                             AND yamazumi.process_element_id=work.id
                           ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                          NULLIF(TRIM(work.operation), ''),
                          ''
                      ) AS work_element_label,
                      COALESCE(
                          NULLIF(TRIM(work.station), ''),
                          (SELECT NULLIF(TRIM(pitch.pitch_number), '')
                           FROM yamazumi_elements yamazumi
                           JOIN yamazumi_pitches pitch ON pitch.id=yamazumi.pitch_id
                           WHERE yamazumi.project_id=work.project_id
                             AND (yamazumi.process_element_id=work.id
                                  OR (yamazumi.process_element_id IS NULL AND yamazumi.id=work.id))
                           ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                          ''
                      ) AS pitch,
                      work.sequence
               FROM work_elements work
               WHERE work.project_id=? AND work.scenario_id=?
               ORDER BY work.sequence, work.id""",
            (project_id, scenario_id),
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows], columns=columns)

def process_ergonomics_risk_work_element_ids(
    project_id: str, scenario_id: str
) -> set[str]:
    """Return Process steps with a qualifying live Ergonomics risk review."""
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        rows = conn.execute(
            """SELECT DISTINCT review.work_element_id
               FROM ergonomics_reviews review
               JOIN work_elements work
                 ON work.id=review.work_element_id
                AND work.project_id=review.project_id
                AND work.scenario_id=review.scenario_id
               WHERE review.project_id=? AND review.scenario_id=?
                 AND review.status IN ('Open', 'Pending')
                 AND review.risk_classification IN ('Red', 'Favorable Red')""",
            (project_id, scenario_id),
        ).fetchall()
    return {str(row["work_element_id"]) for row in rows}

def ergonomics_review_audit_history(
    project_id: str, scenario_id: str, limit: int = 50
) -> pd.DataFrame:
    """Return only audit entries belonging to the active Ergonomics scenario."""
    rows = query(
        """SELECT action, row_count, editor_name, details, created_at
           FROM audit_log
           WHERE project_id=? AND table_name='Ergonomics reviews'
             AND json_extract(details, '$.scenario_id')=?
           ORDER BY created_at DESC LIMIT ?""",
        (project_id, scenario_id, int(limit)),
    )
    return pd.DataFrame(rows)

def _ergonomics_review_has_real_content(values: dict) -> bool:
    """Return whether a review contains content beyond an untouched placeholder."""
    return bool(
        str(values.get("status") or "Started").strip() != "Started"
        or str(values.get("risk_classification") or "Not yet assessed").strip()
        != "Not yet assessed"
        or str(values.get("reviewer") or "").strip()
        or str(values.get("notes") or "").strip()
        or str(values.get("requested_due_date") or "").strip()
        or str(values.get("legacy_description") or "").strip()
        or [value for value in values.get("hazard_option_ids", []) if str(value).strip()]
    )

def _ergonomics_review_merge_plan(
    rows: list[dict], link_candidate_ids: set[str]
) -> dict:
    rows_by_id = {str(row.get("id") or "").strip(): row for row in rows}
    if "" in rows_by_id:
        raise ValueError("Every Ergonomics review requires a stable identifier before saving.")
    silent_merges: list[dict] = []
    conflicts: list[dict] = []
    seen_targets: dict[str, str] = {}
    for candidate_id in link_candidate_ids:
        candidate = rows_by_id.get(candidate_id)
        if candidate is None:
            raise ValueError("An Ergonomics review changed. Refresh and try again.")
        work_element_id = str(candidate.get("work_element_id") or "").strip()
        if not work_element_id:
            continue
        previous_candidate = seen_targets.get(work_element_id)
        if previous_candidate and previous_candidate != candidate_id:
            raise ValueError(
                "Link one Ergonomics review at a time to the same Work Element."
            )
        seen_targets[work_element_id] = candidate_id
        others = [
            row
            for row in rows
            if str(row.get("id") or "").strip() != candidate_id
            and str(row.get("work_element_id") or "").strip() == work_element_id
        ]
        if not others:
            continue
        if len(others) > 1:
            raise ValueError(
                "This Work Element has more than one existing Ergonomics review. "
                "Resolve those reviews before linking another one."
            )
        existing = others[0]
        merge = {
            "work_element_id": work_element_id,
            "candidate_id": candidate_id,
            "existing_id": str(existing["id"]),
            "candidate": dict(candidate),
            "existing": dict(existing),
        }
        if _ergonomics_review_has_real_content(existing):
            conflicts.append(merge)
        else:
            silent_merges.append(merge)
    return {"silent_merges": silent_merges, "conflicts": conflicts}

def ergonomics_review_save_plan(
    project_id: str,
    scenario_id: str,
    rows: list[dict],
    link_candidate_ids: list[str],
) -> dict:
    """Describe automatic and confirmation-required review merges without writing."""
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
    return _ergonomics_review_merge_plan(
        [dict(row) for row in rows],
        {str(value).strip() for value in link_candidate_ids if str(value).strip()},
    )

def save_ergonomics_review_rows(
    project_id: str,
    scenario_id: str,
    rows: list[dict],
    *,
    link_candidate_ids: list[str] | None = None,
    merge_survivors: dict[str, str] | None = None,
    editor_name: str = "",
) -> dict:
    """Save the complete review table and apply approved link merges atomically."""
    normalized_rows: list[dict] = []
    for values in rows:
        review_id = str(values.get("id") or "").strip()
        if not review_id:
            raise ValueError("Every Ergonomics review requires a stable identifier before saving.")
        status = str(values.get("status") or "Started").strip()
        if status not in ERGONOMICS_REVIEW_STATUSES:
            raise ValueError("Choose a valid Ergonomics review status.")
        risk_classification = str(
            values.get("risk_classification") or "Not yet assessed"
        ).strip()
        if risk_classification not in ERGONOMICS_RISK_CLASSIFICATIONS:
            raise ValueError("Choose a valid Ergonomics risk classification.")
        normalized_rows.append(
            {
                "id": review_id,
                "work_element_id": (
                    str(values.get("work_element_id") or "").strip() or None
                ),
                "process_part_option_id": (
                    str(values.get("process_part_option_id") or "").strip() or None
                ),
                "status": status,
                "risk_classification": risk_classification,
                "reviewer": str(values.get("reviewer") or "").strip(),
                "notes": str(values.get("notes") or "").strip(),
                "requested_due_date": (
                    str(values.get("requested_due_date") or "").strip() or None
                ),
                "legacy_description": str(values.get("legacy_description") or "").strip(),
                "hazard_option_ids": list(
                    dict.fromkeys(
                        str(value).strip()
                        for value in values.get("hazard_option_ids", [])
                        if str(value).strip()
                    )
                ),
            }
        )
    ids = [row["id"] for row in normalized_rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Every Ergonomics review must have a unique stable identifier.")

    candidate_ids = {
        str(value).strip()
        for value in (link_candidate_ids or [])
        if str(value).strip()
    }
    decisions = {
        str(candidate_id).strip(): str(survivor_id).strip()
        for candidate_id, survivor_id in (merge_survivors or {}).items()
    }
    timestamp = now_iso()
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        existing_rows = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                """SELECT * FROM ergonomics_reviews
                   WHERE project_id=? AND scenario_id=?""",
                (project_id, scenario_id),
            ).fetchall()
        }
        if set(existing_rows) - set(ids):
            raise ValueError(
                "Remove Ergonomics reviews through the confirmed deletion workflow."
            )

        plan = _ergonomics_review_merge_plan(normalized_rows, candidate_ids)
        discard_ids = {
            str(merge["existing_id"]) for merge in plan["silent_merges"]
        }
        merge_audit: list[dict] = [
            {
                "work_element_id": merge["work_element_id"],
                "surviving_review_id": merge["candidate_id"],
                "discarded_review_id": merge["existing_id"],
                "confirmation_required": False,
            }
            for merge in plan["silent_merges"]
        ]
        for conflict in plan["conflicts"]:
            candidate_id = str(conflict["candidate_id"])
            existing_id = str(conflict["existing_id"])
            survivor_id = decisions.get(candidate_id)
            if survivor_id not in {candidate_id, existing_id}:
                raise ValueError(
                    "Confirm which Ergonomics review should survive the link before saving."
                )
            discarded_id = existing_id if survivor_id == candidate_id else candidate_id
            discard_ids.add(discarded_id)
            merge_audit.append(
                {
                    "work_element_id": conflict["work_element_id"],
                    "surviving_review_id": survivor_id,
                    "discarded_review_id": discarded_id,
                    "confirmation_required": True,
                }
            )

        rows_to_save = [
            row for row in normalized_rows if row["id"] not in discard_ids
        ]
        existing_hazards_by_review = {
            review_id: {
                str(selection["hazard_option_id"]): str(selection["id"])
                for selection in conn.execute(
                    """SELECT id, hazard_option_id
                       FROM ergonomics_review_hazard_selections
                       WHERE ergonomics_review_id=?""",
                    (review_id,),
                ).fetchall()
            }
            for review_id in ids
        }
        for row in rows_to_save:
            work_element_id = row["work_element_id"]
            if work_element_id and not conn.execute(
                """SELECT 1 FROM work_elements
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (work_element_id, project_id, scenario_id),
            ).fetchone():
                raise ValueError(
                    "That Process at a Glance Work Element no longer exists."
                )
            process_part_option_id = row["process_part_option_id"]
            if process_part_option_id and not work_element_id:
                raise ValueError(
                    "A review linked to a Process part-use must also be linked to its Work Element."
                )
            if process_part_option_id and not conn.execute(
                """SELECT 1
                   FROM process_part_options option
                   JOIN process_part_groups group_row ON group_row.id=option.group_id
                   WHERE option.id=? AND group_row.project_id=?
                     AND group_row.scenario_id=? AND group_row.work_element_id=?""",
                (
                    process_part_option_id,
                    project_id,
                    scenario_id,
                    work_element_id,
                ),
            ).fetchone():
                raise ValueError(
                    "The selected Process part-use does not belong to this Work Element and scenario."
                )

            hazard_ids = row["hazard_option_ids"]
            if hazard_ids:
                placeholders = ",".join("?" for _ in hazard_ids)
                available = {
                    str(option["id"]): int(option["active"])
                    for option in conn.execute(
                        f"""SELECT id, active FROM ergonomic_hazard_options
                            WHERE project_id=? AND id IN ({placeholders})""",
                        (project_id, *hazard_ids),
                    ).fetchall()
                }
                if set(available) != set(hazard_ids):
                    raise ValueError(
                        "One or more selected Ergonomics hazards no longer exist."
                    )
                existing_hazard_ids = set(
                    existing_hazards_by_review.get(row["id"], {})
                )
                if any(
                    not active and option_id not in existing_hazard_ids
                    for option_id, active in available.items()
                ):
                    raise ValueError(
                        "Inactive Ergonomics hazards cannot be newly selected."
                    )

        if discard_ids:
            placeholders = ",".join("?" for _ in discard_ids)
            conn.execute(
                f"""DELETE FROM ergonomics_reviews
                    WHERE project_id=? AND scenario_id=?
                      AND id IN ({placeholders})""",
                (project_id, scenario_id, *sorted(discard_ids)),
            )

        created_ids: list[str] = []
        updated_ids: list[str] = []
        for row in rows_to_save:
            review_id = row["id"]
            existing = existing_rows.get(review_id)
            if existing:
                conn.execute(
                    """UPDATE ergonomics_reviews
                       SET work_element_id=?, process_part_option_id=?, status=?,
                           risk_classification=?, reviewer=?, notes=?,
                           requested_due_date=?, legacy_description=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=?""",
                    (
                        row["work_element_id"],
                        row["process_part_option_id"],
                        row["status"],
                        row["risk_classification"],
                        row["reviewer"],
                        row["notes"],
                        row["requested_due_date"],
                        row["legacy_description"],
                        timestamp,
                        review_id,
                        project_id,
                        scenario_id,
                    ),
                )
                updated_ids.append(review_id)
            else:
                conn.execute(
                    """INSERT INTO ergonomics_reviews
                       (id, project_id, scenario_id, work_element_id,
                        process_part_option_id, status, reviewer, notes,
                        requested_due_date, legacy_description, created_at, updated_at,
                        risk_classification)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        review_id,
                        project_id,
                        scenario_id,
                        row["work_element_id"],
                        row["process_part_option_id"],
                        row["status"],
                        row["reviewer"],
                        row["notes"],
                        row["requested_due_date"],
                        row["legacy_description"],
                        timestamp,
                        timestamp,
                        row["risk_classification"],
                    ),
                )
                created_ids.append(review_id)
            existing_selections = existing_hazards_by_review.get(review_id, {})
            conn.execute(
                """DELETE FROM ergonomics_review_hazard_selections
                   WHERE ergonomics_review_id=?""",
                (review_id,),
            )
            for index, hazard_option_id in enumerate(
                row["hazard_option_ids"], start=1
            ):
                conn.execute(
                    """INSERT INTO ergonomics_review_hazard_selections
                       (id, project_id, scenario_id, ergonomics_review_id,
                        hazard_option_id, sequence, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        existing_selections.get(hazard_option_id, str(uuid4())),
                        project_id,
                        scenario_id,
                        review_id,
                        hazard_option_id,
                        index * 10,
                        timestamp,
                        timestamp,
                    ),
                )

        if merge_audit:
            record_audit_event(
                project_id,
                "Ergonomics reviews",
                "Merge reviews",
                len(merge_audit),
                editor_name,
                {"scenario_id": scenario_id, "merges": merge_audit},
                _conn=conn,
            )
    return {
        "row_count": len(rows_to_save),
        "created_ids": created_ids,
        "updated_ids": updated_ids,
        "discarded_ids": sorted(discard_ids),
        "merges": merge_audit,
        "timestamp": timestamp,
    }

def save_ergonomics_review(
    project_id: str,
    scenario_id: str,
    values: dict,
) -> dict:
    review_id = str(values.get("id") or "").strip() or str(uuid4())
    work_element_id = str(values.get("work_element_id") or "").strip() or None
    process_part_option_id = str(values.get("process_part_option_id") or "").strip() or None
    status = str(values.get("status") or "Started").strip()
    if status not in ERGONOMICS_REVIEW_STATUSES:
        raise ValueError("Choose a valid Ergonomics review status.")
    risk_classification = str(
        values.get("risk_classification") or "Not yet assessed"
    ).strip()
    if risk_classification not in ERGONOMICS_RISK_CLASSIFICATIONS:
        raise ValueError("Choose a valid Ergonomics risk classification.")
    reviewer = str(values.get("reviewer") or "").strip()
    notes = str(values.get("notes") or "").strip()
    requested_due_date = str(values.get("requested_due_date") or "").strip() or None
    legacy_description = str(values.get("legacy_description") or "").strip()
    hazard_option_ids = list(
        dict.fromkeys(
            str(value).strip()
            for value in values.get("hazard_option_ids", [])
            if str(value).strip()
        )
    )
    timestamp = now_iso()
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        if work_element_id and not conn.execute(
            """SELECT 1 FROM work_elements
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (work_element_id, project_id, scenario_id),
        ).fetchone():
            raise ValueError("That Process at a Glance Work Element no longer exists.")
        if process_part_option_id and not work_element_id:
            raise ValueError(
                "A review linked to a Process part-use must also be linked to its Work Element."
            )
        if process_part_option_id and not conn.execute(
            """SELECT 1
               FROM process_part_options option
               JOIN process_part_groups group_row ON group_row.id=option.group_id
               WHERE option.id=? AND group_row.project_id=?
                 AND group_row.scenario_id=? AND group_row.work_element_id=?""",
            (process_part_option_id, project_id, scenario_id, work_element_id),
        ).fetchone():
            raise ValueError(
                "The selected Process part-use does not belong to this Work Element and scenario."
            )
        existing_review = conn.execute(
            """SELECT * FROM ergonomics_reviews
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (review_id, project_id, scenario_id),
        ).fetchone()
        existing_hazard_ids = {
            str(row["hazard_option_id"])
            for row in conn.execute(
                """SELECT hazard_option_id
                   FROM ergonomics_review_hazard_selections
                   WHERE ergonomics_review_id=?""",
                (review_id,),
            ).fetchall()
        }
        if hazard_option_ids:
            placeholders = ",".join("?" for _ in hazard_option_ids)
            options = {
                str(row["id"]): int(row["active"])
                for row in conn.execute(
                    f"""SELECT id, active FROM ergonomic_hazard_options
                        WHERE project_id=? AND id IN ({placeholders})""",
                    (project_id, *hazard_option_ids),
                ).fetchall()
            }
            if set(options) != set(hazard_option_ids):
                raise ValueError("One or more selected Ergonomics hazards no longer exist.")
            inactive_new = {
                option_id
                for option_id, active in options.items()
                if not active and option_id not in existing_hazard_ids
            }
            if inactive_new:
                raise ValueError("Inactive Ergonomics hazards cannot be newly selected.")
        if existing_review:
            conn.execute(
                """UPDATE ergonomics_reviews
                   SET work_element_id=?, process_part_option_id=?, status=?,
                       risk_classification=?, reviewer=?, notes=?,
                       requested_due_date=?, legacy_description=?, updated_at=?
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (
                    work_element_id,
                    process_part_option_id,
                    status,
                    risk_classification,
                    reviewer,
                    notes,
                    requested_due_date,
                    legacy_description,
                    timestamp,
                    review_id,
                    project_id,
                    scenario_id,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO ergonomics_reviews
                   (id, project_id, scenario_id, work_element_id,
                    process_part_option_id, status, reviewer, notes,
                    requested_due_date, legacy_description, created_at, updated_at,
                    risk_classification)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    review_id,
                    project_id,
                    scenario_id,
                    work_element_id,
                    process_part_option_id,
                    status,
                    reviewer,
                    notes,
                    requested_due_date,
                    legacy_description,
                    timestamp,
                    timestamp,
                    risk_classification,
                ),
            )
        existing_selections = {
            str(row["hazard_option_id"]): str(row["id"])
            for row in conn.execute(
                """SELECT id, hazard_option_id
                   FROM ergonomics_review_hazard_selections
                   WHERE ergonomics_review_id=?""",
                (review_id,),
            ).fetchall()
        }
        if hazard_option_ids:
            placeholders = ",".join("?" for _ in hazard_option_ids)
            conn.execute(
                f"""DELETE FROM ergonomics_review_hazard_selections
                    WHERE ergonomics_review_id=?
                      AND hazard_option_id NOT IN ({placeholders})""",
                (review_id, *hazard_option_ids),
            )
        else:
            conn.execute(
                "DELETE FROM ergonomics_review_hazard_selections WHERE ergonomics_review_id=?",
                (review_id,),
            )
        for index, hazard_option_id in enumerate(hazard_option_ids, start=1):
            selection_id = existing_selections.get(hazard_option_id, str(uuid4()))
            conn.execute(
                """INSERT INTO ergonomics_review_hazard_selections
                   (id, project_id, scenario_id, ergonomics_review_id,
                    hazard_option_id, sequence, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ergonomics_review_id, hazard_option_id) DO UPDATE SET
                     sequence=excluded.sequence, updated_at=excluded.updated_at""",
                (
                    selection_id,
                    project_id,
                    scenario_id,
                    review_id,
                    hazard_option_id,
                    index * 10,
                    timestamp,
                    timestamp,
                ),
            )
    return {"id": review_id, "row_count": 1, "timestamp": timestamp}

def delete_ergonomics_reviews(
    project_id: str, scenario_id: str, review_ids: list[str]
) -> dict:
    ids = list(dict.fromkeys(str(value).strip() for value in review_ids if str(value).strip()))
    timestamp = now_iso()
    if not ids:
        return {"row_count": 0, "hazard_selection_count": 0, "timestamp": timestamp}
    placeholders = ",".join("?" for _ in ids)
    with connection() as conn:
        reviews = conn.execute(
            f"""SELECT id FROM ergonomics_reviews
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        ).fetchall()
        if len(reviews) != len(ids):
            raise ValueError("One or more Ergonomics reviews changed. Refresh and try again.")
        selection_count = int(
            conn.execute(
                f"""SELECT COUNT(*) FROM ergonomics_review_hazard_selections
                    WHERE project_id=? AND scenario_id=?
                      AND ergonomics_review_id IN ({placeholders})""",
                (project_id, scenario_id, *ids),
            ).fetchone()[0]
        )
        cursor = conn.execute(
            f"""DELETE FROM ergonomics_reviews
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        )
        if int(cursor.rowcount) != len(ids):
            raise ValueError("One or more Ergonomics reviews changed. Refresh and try again.")
    return {
        "row_count": len(ids),
        "hazard_selection_count": selection_count,
        "timestamp": timestamp,
    }


def create_legacy_ergonomics_review(
    project_id: str,
    scenario_id: str,
    legacy_description: str,
    *,
    risk_classification: str = "Not yet assessed",
    status: str = "Started",
    reviewer: str = "",
    hazard_option_ids: list[str] | None = None,
    notes: str = "",
    requested_due_date: str | None = None,
    editor_name: str = "",
) -> dict:
    """Create a new unlinked legacy ergonomics review."""
    title = str(legacy_description or "").strip()
    if not title:
        raise ValueError("Please provide a legacy concern title or description.")
    review_values = {
        "id": str(uuid4()),
        "work_element_id": None,
        "process_part_option_id": None,
        "legacy_description": title,
        "status": status,
        "risk_classification": risk_classification,
        "reviewer": reviewer,
        "hazard_option_ids": hazard_option_ids or [],
        "notes": notes,
        "requested_due_date": requested_due_date,
    }
    result = save_ergonomics_review(project_id, scenario_id, review_values)
    record_audit_event(
        project_id,
        "Ergonomics reviews",
        "Create legacy review",
        1,
        editor_name,
        {
            "scenario_id": scenario_id,
            "review_id": result["id"],
            "legacy_description": title,
        },
    )
    return {**result, "legacy_description": title, "work_element_id": None}


def delete_unlinked_ergonomics_reviews(
    project_id: str,
    scenario_id: str,
    review_ids: list[str] | None = None,
    editor_name: str = "",
) -> dict:
    """Purge unlinked reviews from the active scenario, with optional id filtering."""
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        if review_ids is not None:
            clean_ids = list(dict.fromkeys(str(v).strip() for v in review_ids if str(v).strip()))
            if not clean_ids:
                return {"row_count": 0, "timestamp": now_iso()}
            placeholders = ",".join("?" for _ in clean_ids)
            unlinked = conn.execute(
                f"""SELECT id FROM ergonomics_reviews
                    WHERE project_id=? AND scenario_id=? AND work_element_id IS NULL AND id IN ({placeholders})""",
                (project_id, scenario_id, *clean_ids),
            ).fetchall()
        else:
            unlinked = conn.execute(
                """SELECT id FROM ergonomics_reviews
                    WHERE project_id=? AND scenario_id=? AND work_element_id IS NULL""",
                (project_id, scenario_id),
            ).fetchall()
        target_ids = [str(r["id"]) for r in unlinked]
        if not target_ids:
            return {"row_count": 0, "timestamp": now_iso()}
    result = delete_ergonomics_reviews(project_id, scenario_id, target_ids)
    if result.get("row_count"):
        record_audit_event(
            project_id,
            "Ergonomics reviews",
            "Delete unlinked reviews",
            result["row_count"],
            editor_name,
            {"scenario_id": scenario_id, "deleted_review_ids": target_ids},
        )
    return result


def link_legacy_concern_to_work_element(
    project_id: str,
    scenario_id: str,
    legacy_review_id: str,
    target_work_element_id: str,
    editor_name: str = "",
) -> dict:
    """Merge an unlinked legacy Ergonomics concern into a target Process step's review."""
    timestamp = now_iso()
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        work_elem = conn.execute(
            "SELECT id, operation FROM work_elements WHERE id=? AND project_id=? AND scenario_id=?",
            (target_work_element_id, project_id, scenario_id),
        ).fetchone()
        if not work_elem:
            raise ValueError("The target Process step no longer exists.")

        legacy_row = conn.execute(
            """SELECT * FROM ergonomics_reviews
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (legacy_review_id, project_id, scenario_id),
        ).fetchone()
        if not legacy_row:
            raise ValueError("The selected legacy concern no longer exists.")

        legacy_review = dict(legacy_row)
        legacy_hazards = [
            str(r["hazard_option_id"])
            for r in conn.execute(
                """SELECT hazard_option_id FROM ergonomics_review_hazard_selections
                   WHERE ergonomics_review_id=?""",
                (legacy_review_id,),
            ).fetchall()
        ]

        existing_rows = conn.execute(
            """SELECT * FROM ergonomics_reviews
               WHERE project_id=? AND scenario_id=? AND work_element_id=? AND id != ?""",
            (project_id, scenario_id, target_work_element_id, legacy_review_id),
        ).fetchall()

        legacy_title = (
            str(legacy_review.get("legacy_description") or "").strip()
            or str(legacy_review.get("notes") or "").strip()
            or "Legacy concern"
        )

        risk_ranks = {
            "Red": 5,
            "Favorable Red": 4,
            "Favorable Green": 3,
            "Green": 2,
            "Not yet assessed": 1,
        }

        if existing_rows:
            target_review = dict(existing_rows[0])
            surviving_id = target_review["id"]
            target_hazards = [
                str(r["hazard_option_id"])
                for r in conn.execute(
                    """SELECT hazard_option_id FROM ergonomics_review_hazard_selections
                       WHERE ergonomics_review_id=?""",
                    (surviving_id,),
                ).fetchall()
            ]

            # Merge notes
            l_notes = str(legacy_review.get("notes") or "").strip()
            t_notes = str(target_review.get("notes") or "").strip()
            if l_notes and t_notes:
                if l_notes == t_notes:
                    merged_notes = l_notes
                else:
                    merged_notes = f"[Legacy Concern]: {l_notes}\n\n[Process Step Review]: {t_notes}"
            else:
                merged_notes = l_notes or t_notes

            # Merge hazard tags
            merged_hazards = list(dict.fromkeys([*target_hazards, *legacy_hazards]))

            # Merge risk classification
            l_risk = str(legacy_review.get("risk_classification") or "Not yet assessed")
            t_risk = str(target_review.get("risk_classification") or "Not yet assessed")
            merged_risk = l_risk if risk_ranks.get(l_risk, 0) >= risk_ranks.get(t_risk, 0) else t_risk

            # Merge status
            l_status = str(legacy_review.get("status") or "Started")
            t_status = str(target_review.get("status") or "Started")
            merged_status = l_status if t_status == "Started" else t_status

            # Reviewer
            merged_reviewer = (
                str(legacy_review.get("reviewer") or "").strip()
                or str(target_review.get("reviewer") or "").strip()
            )

            # Due date
            merged_due_date = (
                str(target_review.get("requested_due_date") or "").strip()
                or str(legacy_review.get("requested_due_date") or "").strip()
                or None
            )

            conn.execute(
                """UPDATE ergonomics_reviews
                   SET legacy_description=?, notes=?, risk_classification=?,
                       status=?, reviewer=?, requested_due_date=?, updated_at=?
                   WHERE id=?""",
                (
                    legacy_title,
                    merged_notes,
                    merged_risk,
                    merged_status,
                    merged_reviewer,
                    merged_due_date,
                    timestamp,
                    surviving_id,
                ),
            )

            # Hazard selections on surviving review
            conn.execute(
                "DELETE FROM ergonomics_review_hazard_selections WHERE ergonomics_review_id=?",
                (surviving_id,),
            )
            for idx, h_id in enumerate(merged_hazards):
                conn.execute(
                    """INSERT INTO ergonomics_review_hazard_selections
                       (id, project_id, scenario_id, ergonomics_review_id, hazard_option_id, sequence, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid4()), project_id, scenario_id, surviving_id, h_id, idx * 10, timestamp, timestamp),
                )

            # Re-point visual media from legacy review to surviving review
            conn.execute(
                "UPDATE ergonomics_visual_media SET review_id=?, updated_at=? WHERE review_id=?",
                (surviving_id, timestamp, legacy_review_id),
            )

            # Delete legacy review and its hazard selections
            conn.execute(
                "DELETE FROM ergonomics_review_hazard_selections WHERE ergonomics_review_id=?",
                (legacy_review_id,),
            )
            conn.execute(
                "DELETE FROM ergonomics_reviews WHERE id=?",
                (legacy_review_id,),
            )
            discarded_id = legacy_review_id
        else:
            surviving_id = legacy_review_id
            conn.execute(
                """UPDATE ergonomics_reviews
                   SET work_element_id=?, legacy_description=?, updated_at=?
                   WHERE id=?""",
                (target_work_element_id, legacy_title, timestamp, surviving_id),
            )
            discarded_id = None

    record_audit_event(
        project_id,
        "Ergonomics reviews",
        "Link legacy concern",
        1,
        editor_name,
        {
            "scenario_id": scenario_id,
            "legacy_review_id": legacy_review_id,
            "target_work_element_id": target_work_element_id,
            "surviving_review_id": surviving_id,
            "discarded_review_id": discarded_id,
            "legacy_title": legacy_title,
        },
    )
    return {
        "surviving_id": surviving_id,
        "discarded_id": discarded_id,
        "legacy_title": legacy_title,
        "timestamp": timestamp,
    }


MAX_VISUAL_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VISUAL_VIDEO_BYTES = 25 * 1024 * 1024


def get_ergonomics_visual_media(
    project_id: str,
    scenario_id: str,
    review_id: str | None = None,
) -> list[dict]:
    """Return ergonomics visual media records for the given project, scenario, and optional review."""
    query_str = """
        SELECT m.id, m.project_id, m.scenario_id, m.review_id, m.media_type,
               m.file_path, m.original_file_path, m.annotations_json, m.caption,
               m.sequence, m.created_at, m.created_by, m.updated_at
        FROM ergonomics_visual_media m
        WHERE m.project_id = ? AND m.scenario_id = ?
    """
    params: list[Any] = [project_id, scenario_id]
    if review_id:
        query_str += " AND m.review_id = ?"
        params.append(review_id)
    query_str += " ORDER BY m.sequence, m.created_at, m.id"

    with connection() as conn:
        rows = conn.execute(query_str, params).fetchall()
        result: list[dict] = []
        for r in rows:
            item = dict(r)
            fpath = Path(item["file_path"])
            item["exists_on_disk"] = fpath.exists() and fpath.is_file()
            if item["exists_on_disk"] and item["media_type"] == "image":
                try:
                    raw_b = fpath.read_bytes()
                    sfx = fpath.suffix.lower()
                    mime = "image/png" if sfx == ".png" else "image/webp" if sfx == ".webp" else "image/jpeg"
                    b64 = base64.b64encode(raw_b).decode("ascii")
                    item["data_url"] = f"data:{mime};base64,{b64}"
                except Exception:
                    item["data_url"] = ""
            else:
                item["data_url"] = ""
            result.append(item)
        return result


def save_ergonomics_visual_media(
    project_id: str,
    scenario_id: str,
    review_id: str,
    filename: str,
    file_bytes: bytes,
    media_type: str | None = None,
    caption: str = "",
    sequence: int = 10,
    current_editor: str = "Collaborator",
    annotations_json: str = "",
    original_file_bytes: bytes | None = None,
) -> dict:
    """Save an uploaded image or video visual aid for an Ergonomics review and record audit."""
    normalized_review_id = str(review_id or "").strip()
    if not normalized_review_id:
        raise ValueError("Choose an Ergonomics review.")
    if not file_bytes:
        raise ValueError("No file content provided.")

    suffix = Path(str(filename or "")).suffix.lower()
    image_suffixes = {".png", ".jpg", ".jpeg", ".webp"}
    video_suffixes = {".mp4", ".mov", ".webm"}
    if suffix in image_suffixes:
        detected_type = "image"
        if len(file_bytes) > MAX_VISUAL_IMAGE_BYTES:
            size_mb = len(file_bytes) / (1024 * 1024)
            raise ValueError(
                f"Image is {size_mb:.1f} MB. Photos and screenshots must be under 10 MB for fast slide rendering."
            )
    elif suffix in video_suffixes:
        detected_type = "video"
        if len(file_bytes) > MAX_VISUAL_VIDEO_BYTES:
            size_mb = len(file_bytes) / (1024 * 1024)
            raise ValueError(
                f"Video is {size_mb:.1f} MB. For fast slide loading and smooth presentation playback, please trim or compress clips under 25 MB."
            )
    else:
        raise ValueError(
            f"Unsupported file format '{suffix}'. Supported formats: PNG, JPG, JPEG, WEBP (max 10 MB), MP4, MOV, WEBM (max 25 MB)."
        )

    resolved_media_type = media_type or detected_type
    if resolved_media_type not in {"image", "video"}:
        raise ValueError("Media type must be 'image' or 'video'.")

    timestamp = now_iso()
    media_id = str(uuid4())
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_path = UPLOAD_DIR / f"ergo_visual_{normalized_review_id}_{media_id}{suffix}"
    target_path.write_bytes(file_bytes)

    orig_path_str = ""
    if resolved_media_type == "image":
        if original_file_bytes and original_file_bytes != file_bytes:
            orig_target_path = UPLOAD_DIR / f"ergo_visual_{normalized_review_id}_{media_id}_orig{suffix}"
            orig_target_path.write_bytes(original_file_bytes)
            orig_path_str = str(orig_target_path)
        else:
            orig_path_str = str(target_path)

    with connection() as conn:
        review = conn.execute(
            """SELECT id, work_element_id, status, risk_classification
               FROM ergonomics_reviews
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (normalized_review_id, project_id, scenario_id),
        ).fetchone()
        if not review:
            target_path.unlink(missing_ok=True)
            if orig_path_str and orig_path_str != str(target_path):
                Path(orig_path_str).unlink(missing_ok=True)
            raise ValueError("The selected Ergonomics review does not exist in the active planning scenario.")

        conn.execute(
            """INSERT INTO ergonomics_visual_media
               (id, project_id, scenario_id, review_id, media_type, file_path, original_file_path,
                annotations_json, caption, sequence, created_at, created_by, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                media_id,
                project_id,
                scenario_id,
                normalized_review_id,
                resolved_media_type,
                str(target_path),
                orig_path_str,
                str(annotations_json or "").strip(),
                str(caption or "").strip(),
                int(sequence),
                timestamp,
                str(current_editor or "").strip(),
                timestamp,
            ),
        )

    record_audit_event(
        project_id,
        "ergonomics_visual_media",
        "Upload visual aid",
        1,
        str(current_editor or "").strip(),
        {
            "review_id": normalized_review_id,
            "filename": filename,
            "caption": caption,
            "annotated": bool(annotations_json),
        },
    )
    return {
        "id": media_id,
        "file_path": str(target_path),
        "original_file_path": orig_path_str,
        "media_type": resolved_media_type,
        "caption": caption,
        "sequence": sequence,
    }


def update_ergonomics_visual_media(
    project_id: str,
    scenario_id: str,
    media_id: str,
    caption: str | None = None,
    sequence: int | None = None,
    current_editor: str = "Collaborator",
) -> None:
    """Update caption and/or sequence order for an ergonomics visual aid."""
    normalized_media_id = str(media_id or "").strip()
    if not normalized_media_id:
        raise ValueError("Choose a visual aid to update.")

    timestamp = now_iso()
    with connection() as conn:
        row = conn.execute(
            """SELECT id, review_id, caption, sequence FROM ergonomics_visual_media
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (normalized_media_id, project_id, scenario_id),
        ).fetchone()
        if not row:
            raise ValueError("Visual aid not found.")

        new_caption = str(caption if caption is not None else row["caption"]).strip()
        new_seq = int(sequence if sequence is not None else row["sequence"])

        conn.execute(
            """UPDATE ergonomics_visual_media
               SET caption=?, sequence=?, updated_at=?
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (new_caption, new_seq, timestamp, normalized_media_id, project_id, scenario_id),
        )

    record_audit_event(
        project_id,
        "ergonomics_visual_media",
        "Update visual aid",
        1,
        str(current_editor or "").strip(),
        {"media_id": normalized_media_id, "caption": new_caption, "sequence": new_seq},
    )
    return {
        "id": normalized_media_id,
        "caption": new_caption,
        "sequence": new_seq,
    }


def update_ergonomics_visual_annotations(
    project_id: str,
    scenario_id: str,
    media_id: str,
    annotations_json: str,
    composite_image_bytes: bytes | None = None,
    current_editor: str = "Collaborator",
) -> dict:
    """Update annotations vector JSON and composite display image for an existing ergonomics visual aid."""
    normalized_media_id = str(media_id or "").strip()
    if not normalized_media_id:
        raise ValueError("Choose a visual aid to annotate.")

    timestamp = now_iso()
    with connection() as conn:
        row = conn.execute(
            """SELECT m.id, m.file_path, m.original_file_path, m.caption, m.review_id
               FROM ergonomics_visual_media m
               WHERE m.id=? AND m.project_id=? AND m.scenario_id=?""",
            (normalized_media_id, project_id, scenario_id),
        ).fetchone()
        if not row:
            raise ValueError("Visual aid not found.")

        file_path_str = row["file_path"]
        orig_path_str = row["original_file_path"] or file_path_str
        review_id = row["review_id"]
        caption = row["caption"]

        if not row["original_file_path"] or row["original_file_path"] == file_path_str:
            curr_path = Path(file_path_str)
            if curr_path.exists() and curr_path.is_file():
                suffix = curr_path.suffix or ".png"
                new_orig_target = UPLOAD_DIR / f"ergo_visual_{review_id}_{normalized_media_id}_orig{suffix}"
                new_orig_target.write_bytes(curr_path.read_bytes())
                orig_path_str = str(new_orig_target)
                conn.execute(
                    "UPDATE ergonomics_visual_media SET original_file_path=? WHERE id=?",
                    (orig_path_str, normalized_media_id),
                )

        if composite_image_bytes:
            target = Path(file_path_str)
            target.write_bytes(composite_image_bytes)

        conn.execute(
            """UPDATE ergonomics_visual_media
               SET annotations_json=?, updated_at=?
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (str(annotations_json or "").strip(), timestamp, normalized_media_id, project_id, scenario_id),
        )

    record_audit_event(
        project_id,
        "ergonomics_visual_media",
        "Annotate visual aid",
        1,
        str(current_editor or "").strip(),
        {"review_id": review_id, "summary": f"Annotated ergonomics visual aid: '{caption or normalized_media_id}'"},
    )
    return {
        "id": normalized_media_id,
        "annotations_json": str(annotations_json or "").strip(),
        "file_path": file_path_str,
        "original_file_path": orig_path_str,
    }


def delete_ergonomics_visual_media(
    project_id: str,
    scenario_id: str,
    media_id: str,
    current_editor: str = "Collaborator",
) -> None:
    """Delete an ergonomics visual aid and underlying media files on disk."""
    normalized_media_id = str(media_id or "").strip()
    if not normalized_media_id:
        raise ValueError("Choose a visual aid to delete.")

    with connection() as conn:
        row = conn.execute(
            """SELECT m.id, m.file_path, m.original_file_path, m.caption, m.review_id
               FROM ergonomics_visual_media m
               WHERE m.id=? AND m.project_id=? AND m.scenario_id=?""",
            (normalized_media_id, project_id, scenario_id),
        ).fetchone()
        if not row:
            raise ValueError("Visual aid not found.")

        file_path_str = row["file_path"]
        orig_path_str = row["original_file_path"] or ""
        caption = row["caption"]
        review_id = row["review_id"]

        conn.execute(
            "DELETE FROM ergonomics_visual_media WHERE id=? AND project_id=? AND scenario_id=?",
            (normalized_media_id, project_id, scenario_id),
        )

    if file_path_str:
        p = Path(file_path_str)
        try:
            if p.exists() and p.is_file() and UPLOAD_DIR.resolve() in p.resolve().parents:
                p.unlink(missing_ok=True)
        except OSError:
            pass

    if orig_path_str and orig_path_str != file_path_str:
        op = Path(orig_path_str)
        try:
            if op.exists() and op.is_file() and UPLOAD_DIR.resolve() in op.resolve().parents:
                op.unlink(missing_ok=True)
        except OSError:
            pass

    record_audit_event(
        project_id,
        "ergonomics_visual_media",
        "Delete visual aid",
        1,
        str(current_editor or "").strip(),
        {"review_id": review_id, "summary": f"Deleted ergonomics visual aid: '{caption or normalized_media_id}'"},
    )


def ergonomics_slide_summary(
    project_id: str,
    scenario_id: str,
    review_id: str,
) -> dict:
    """Return all context and details required to render a complete 16:9 Ergonomics Review slide."""
    normalized_review_id = str(review_id or "").strip()
    if not normalized_review_id:
        raise ValueError("Choose an Ergonomics review.")

    with connection() as conn:
        proj = conn.execute("SELECT name FROM projects WHERE id=?", (project_id,)).fetchone()
        project_name = str(proj["name"]) if proj else ""

        scen = conn.execute(
            "SELECT id, name, takt_time_s, takt_time_unit FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone()
        if not scen:
            raise ValueError("The active planning scenario no longer exists.")
        scenario_name = str(scen["name"])
        takt_time_s = float(scen["takt_time_s"] or 0)
        takt_time_unit = str(scen["takt_time_unit"] or "seconds")

        review_row = conn.execute(
            """SELECT r.id, r.work_element_id, r.process_part_option_id,
                      r.status, r.risk_classification, r.reviewer, r.notes,
                      r.requested_due_date, r.legacy_description, r.created_at, r.updated_at
               FROM ergonomics_reviews r
               WHERE r.id=? AND r.project_id=? AND r.scenario_id=?""",
            (normalized_review_id, project_id, scenario_id),
        ).fetchone()
        if not review_row:
            raise ValueError("The selected Ergonomics review no longer exists.")
        review = dict(review_row)

        hazard_rows = conn.execute(
            """SELECT opt.id, opt.label, sel.sequence
               FROM ergonomics_review_hazard_selections sel
               JOIN ergonomic_hazard_options opt ON opt.id=sel.hazard_option_id
               WHERE sel.ergonomics_review_id=? AND sel.project_id=? AND sel.scenario_id=?
               ORDER BY sel.sequence, opt.label""",
            (normalized_review_id, project_id, scenario_id),
        ).fetchall()
        hazards = [str(hr["label"]) for hr in hazard_rows]

        work_element_id = review.get("work_element_id")
        work_info: dict[str, Any] = {}
        parts_info: list[dict[str, Any]] = []
        equipment_info: list[dict[str, Any]] = []

        if work_element_id:
            we_row = conn.execute(
                """SELECT w.id, w.operation, w.tool, w.sequence AS work_sequence,
                          w.model_applicability, w.cycle_time_s AS cycle_time,
                          y.id AS yamazumi_element_id, y.description AS yamazumi_description,
                          y.time_s, y.pitch_id,
                          p.pitch_number, p.pitch_name,
                          a.name AS area_name, sec.name AS section_name
                   FROM work_elements w
                   LEFT JOIN yamazumi_elements y
                     ON (y.process_element_id=w.id OR (y.process_element_id IS NULL AND y.id=w.id))
                    AND y.project_id=w.project_id
                   LEFT JOIN yamazumi_pitches p ON p.id=y.pitch_id AND p.project_id=w.project_id
                   LEFT JOIN yamazumi_areas a ON a.id=p.area_id AND a.scenario_id=w.scenario_id
                   LEFT JOIN assembly_sections sec ON sec.id=a.section_id AND sec.project_id=w.project_id
                   WHERE w.id=? AND w.project_id=? AND w.scenario_id=?""",
                (work_element_id, project_id, scenario_id),
            ).fetchone()
            if we_row:
                work_info = dict(we_row)

            p_rows = conn.execute(
                """SELECT p.id AS part_id, p.part_number, p.description, p.factory_nickname,
                          p.weight_lb, grp.quantity, opt.handling_type
                   FROM process_part_groups grp
                   JOIN process_part_options opt ON opt.group_id=grp.id
                   JOIN parts p ON p.id=opt.part_id AND p.project_id=grp.project_id
                   WHERE grp.work_element_id=? AND grp.project_id=? AND grp.scenario_id=?
                   ORDER BY p.part_number""",
                (work_element_id, project_id, scenario_id),
            ).fetchall()
            for pr in p_rows:
                parts_info.append(dict(pr))

            eq_rows = conn.execute(
                """SELECT e.id, e.name, t.label AS type_name
                   FROM equipment_process_links l
                   JOIN equipment_placements pl ON pl.id=l.placement_id AND pl.scenario_id=l.scenario_id
                   JOIN equipment_assets e ON e.id=pl.equipment_id AND e.project_id=l.project_id
                   LEFT JOIN equipment_types t ON t.id=e.equipment_type_id AND t.project_id=l.project_id
                   WHERE l.work_element_id=? AND l.project_id=? AND l.scenario_id=?""",
                (work_element_id, project_id, scenario_id),
            ).fetchall()
            for er in eq_rows:
                equipment_info.append(dict(er))

        media_list = get_ergonomics_visual_media(project_id, scenario_id, normalized_review_id)

        max_part_weight = 0.0
        total_parts_weight = 0.0
        has_heavy_part = False
        for p in parts_info:
            w = float(p.get("weight_lb") or 0.0)
            qty = float(p.get("quantity") or 1.0)
            if w > max_part_weight:
                max_part_weight = w
            total_parts_weight += w * qty
            if w >= 33.0 or (w * qty) >= 33.0:
                has_heavy_part = True

        return {
            "project_name": project_name,
            "scenario_name": scenario_name,
            "takt_time_s": takt_time_s,
            "takt_time_unit": takt_time_unit,
            "review": review,
            "hazards": hazards,
            "work_info": work_info,
            "parts": parts_info,
            "equipment": equipment_info,
            "media": media_list,
            "max_part_weight": max_part_weight,
            "total_parts_weight": total_parts_weight,
            "has_heavy_part": has_heavy_part,
        }


__domain_exports__ = [
    'ergonomic_hazard_options',
    'save_ergonomic_hazard_option_rows',
    'ergonomic_hazard_option_delete_impact',
    'delete_ergonomic_hazard_options',
    'ergonomics_reviews',
    'ergonomics_work_elements',
    'process_ergonomics_risk_work_element_ids',
    'ergonomics_review_audit_history',
    '_ergonomics_review_has_real_content',
    '_ergonomics_review_merge_plan',
    'ergonomics_review_save_plan',
    'save_ergonomics_review_rows',
    'save_ergonomics_review',
    'delete_ergonomics_reviews',
    'create_legacy_ergonomics_review',
    'delete_unlinked_ergonomics_reviews',
    'link_legacy_concern_to_work_element',
    'ensure_default_ergonomic_hazard_options',
    'create_or_get_ergonomic_hazard_option',
    'get_ergonomics_visual_media',
    'save_ergonomics_visual_media',
    'update_ergonomics_visual_media',
    'update_ergonomics_visual_annotations',
    'delete_ergonomics_visual_media',
    'ergonomics_slide_summary',
]
for _export_name in __domain_exports__:
    if callable(globals()[_export_name]):
        globals()[_export_name] = _db_core.domain_entrypoint(globals()[_export_name])
_db_core.register_domain_module(_sys.modules[__name__], __domain_exports__)
