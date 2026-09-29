"""Domain persistence extracted from the historical utils.store module."""

from __future__ import annotations

import sys as _sys
from utils import db_core as _db_core

globals().update({name: value for name, value in vars(_db_core).items() if not name.startswith('__')})

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
                           COALESCE(work.station, '') AS pitch
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
                      COALESCE(work.station, '') AS pitch,
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
                           requested_due_date=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=?""",
                    (
                        row["work_element_id"],
                        row["process_part_option_id"],
                        row["status"],
                        row["risk_classification"],
                        row["reviewer"],
                        row["notes"],
                        row["requested_due_date"],
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
                        requested_due_date, created_at, updated_at,
                        risk_classification)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                       requested_due_date=?, updated_at=?
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (
                    work_element_id,
                    process_part_option_id,
                    status,
                    risk_classification,
                    reviewer,
                    notes,
                    requested_due_date,
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
                    requested_due_date, created_at, updated_at,
                    risk_classification)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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

__domain_exports__ = ['ergonomic_hazard_options', 'save_ergonomic_hazard_option_rows', 'ergonomic_hazard_option_delete_impact', 'delete_ergonomic_hazard_options', 'ergonomics_reviews', 'ergonomics_work_elements', 'process_ergonomics_risk_work_element_ids', 'ergonomics_review_audit_history', '_ergonomics_review_has_real_content', '_ergonomics_review_merge_plan', 'ergonomics_review_save_plan', 'save_ergonomics_review_rows', 'save_ergonomics_review', 'delete_ergonomics_reviews']
for _export_name in __domain_exports__:
    if callable(globals()[_export_name]):
        globals()[_export_name] = _db_core.domain_entrypoint(globals()[_export_name])
_db_core.register_domain_module(_sys.modules[__name__], __domain_exports__)
