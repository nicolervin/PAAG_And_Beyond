"""Domain persistence extracted from the historical utils.store module."""

from __future__ import annotations

import sys as _sys
from utils import db_core as _db_core

globals().update({name: value for name, value in vars(_db_core).items() if not name.startswith('__')})

_YAMAZUMI_PITCH_ADDRESS_PATTERN = re.compile(
    r"^(?P<subline>\d+)-(?P<work_area_letters>[A-Za-z]+)"
    r"(?P<work_area_number>\d+)-(?P<position>\d+)$"
)

def _normalize_handling_type(value) -> str | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    handling_type = str(value).strip()
    if handling_type not in HANDLING_TYPES:
        raise ValueError("Handling type must be Handle or Consume.")
    return handling_type

def _normalize_fishbone_assignment_id(value) -> str | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    return str(value).strip()

def _process_part_assignment_consume_count(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    fishbone_assignment_id: str,
    *,
    exclude_process_part_option_id: str | None = None,
) -> int:
    exclude_clause = " AND option.id<>?" if exclude_process_part_option_id else ""
    params: tuple = (project_id, scenario_id, fishbone_assignment_id)
    if exclude_process_part_option_id:
        params += (exclude_process_part_option_id,)
    return int(
        conn.execute(
            f"""SELECT COUNT(*)
                FROM process_part_options option
                JOIN process_part_groups group_row ON group_row.id=option.group_id
                WHERE group_row.project_id=? AND group_row.scenario_id=?
                  AND option.fishbone_assignment_id=?
                  AND option.handling_type='Consume'{exclude_clause}""",
            params,
        ).fetchone()[0]
    )

def _validate_process_part_option_handling(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    scenario_id: str,
    section_id: str,
    process_part_option_id: str,
    part_id: str,
    handling_type: str | None,
    fishbone_assignment_id: str | None,
) -> None:
    if handling_type is None and fishbone_assignment_id is None:
        return
    if handling_type is not None and fishbone_assignment_id is None:
        raise ValueError(
            f"A Fishbone placement is required before this part can be {handling_type.lower()}d."
        )
    if fishbone_assignment_id is None:
        return

    assignment = conn.execute(
        """SELECT assignment.id, assignment.quantity, assignment.use_description,
                  part.part_number, section.name AS section_name
           FROM fishbone_part_assignments assignment
           JOIN parts part ON part.id=assignment.part_id
           JOIN assembly_sections section ON section.id=assignment.section_id
           WHERE assignment.id=? AND assignment.project_id=?
             AND assignment.part_id=? AND assignment.section_id=?""",
        (fishbone_assignment_id, project_id, part_id, section_id),
    ).fetchone()
    if not assignment:
        raise ValueError(
            "Choose a Fishbone placement for the same part in this part requirement's "
            "Fishbone section."
        )
    if handling_type is None:
        return

    other_consume_count = _process_part_assignment_consume_count(
        conn,
        project_id,
        scenario_id,
        fishbone_assignment_id,
        exclude_process_part_option_id=process_part_option_id,
    )
    placement_label = str(assignment["part_number"])
    use_description = str(assignment["use_description"] or "").strip()
    if use_description:
        placement_label = f"{placement_label} — {use_description}"
    placement_label = f"{placement_label} [{assignment['id']}]"

    if handling_type == "Consume":
        recorded_quantity = float(assignment["quantity"])
        if other_consume_count + 1 > recorded_quantity:
            raise ValueError(
                f"Fishbone placement {placement_label} has a recorded quantity of "
                f"{recorded_quantity:g}, which has already been fully consumed elsewhere "
                "in this scenario."
            )
        return

    if other_consume_count < 1:
        raise ValueError(
            f"Fishbone placement {placement_label} must be Consumed before it can be Handled "
            "in this scenario."
        )

def process_part_placement_options(
    project_id: str,
    scenario_id: str,
    section_id: str,
    part_id: str,
) -> pd.DataFrame:
    """Return exact Fishbone uses with scenario-specific Consume availability."""
    columns = [
        "fishbone_assignment_id",
        "part_id",
        "part_number",
        "section_id",
        "section_name",
        "use_description",
        "fishbone_quantity",
        "consumed_count",
        "remaining_consume_allowance",
        "can_consume",
        "can_handle",
    ]
    with connection() as conn:
        if not conn.execute(
            """SELECT 1 FROM planning_scenarios
               WHERE id=? AND project_id=?""",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        assignments = conn.execute(
            """SELECT assignment.id AS fishbone_assignment_id,
                      assignment.part_id, part.part_number,
                      assignment.section_id, section.name AS section_name,
                      assignment.use_description,
                      assignment.quantity AS fishbone_quantity
               FROM fishbone_part_assignments assignment
               JOIN parts part ON part.id=assignment.part_id
               JOIN assembly_sections section ON section.id=assignment.section_id
               LEFT JOIN part_scenario_activity activity
                 ON activity.project_id=assignment.project_id
                AND activity.scenario_id=? AND activity.part_id=assignment.part_id
               WHERE assignment.project_id=? AND assignment.section_id=?
                 AND assignment.part_id=? AND COALESCE(activity.active, 1)=1
               ORDER BY assignment.sequence, assignment.id""",
            (scenario_id, project_id, section_id, part_id),
        ).fetchall()
        rows: list[dict] = []
        for assignment in assignments:
            assignment_id = str(assignment["fishbone_assignment_id"])
            consumed_count = _process_part_assignment_consume_count(
                conn, project_id, scenario_id, assignment_id
            )
            fishbone_quantity = float(assignment["fishbone_quantity"])
            remaining = max(fishbone_quantity - consumed_count, 0.0)
            row = dict(assignment)
            row.update(
                consumed_count=consumed_count,
                remaining_consume_allowance=remaining,
                can_consume=(consumed_count + 1 <= fishbone_quantity),
                can_handle=(consumed_count >= 1),
            )
            rows.append(row)
    if not rows:
        return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})
    return pd.DataFrame(rows, columns=columns)

def validate_process_part_option_pairings(
    project_id: str,
    scenario_id: str,
    section_id: str,
    pairings: list[dict],
) -> None:
    """Validate new Process part pairings before any surrounding workflow writes."""
    with connection() as conn:
        if not conn.execute(
            """SELECT 1 FROM planning_scenarios
               WHERE id=? AND project_id=?""",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        for pairing in pairings:
            _validate_process_part_option_handling(
                conn,
                project_id=project_id,
                scenario_id=scenario_id,
                section_id=section_id,
                process_part_option_id=str(pairing.get("id") or uuid4()),
                part_id=str(pairing.get("part_id") or ""),
                handling_type=_normalize_handling_type(
                    pairing.get("handling_type")
                ),
                fishbone_assignment_id=_normalize_fishbone_assignment_id(
                    pairing.get("fishbone_assignment_id")
                ),
            )

def yamazumi_elements_for_section(
    project_id: str, scenario_id: str, section_id: str
) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT element.id, element.process_element_id, element.description,
                   element.time_s, element.model_variant, element.model_variants, element.work_type,
                   element.process_sync_status, area.id AS area_id, area.name AS area_name,
                   pitch.pitch_number, pitch.pitch_name,
                   CASE WHEN process.id IS NULL THEN 0 ELSE 1 END AS process_reflected,
                   COUNT(DISTINCT group_row.id) AS material_group_count
           FROM yamazumi_elements element
            JOIN yamazumi_areas area ON area.id=element.area_id
            LEFT JOIN yamazumi_pitches pitch ON pitch.id=element.pitch_id
            LEFT JOIN work_elements process
              ON process.id=element.process_element_id
             AND process.project_id=element.project_id
             AND process.scenario_id=area.scenario_id
            LEFT JOIN process_part_groups group_row
             ON group_row.work_element_id=element.process_element_id
            AND group_row.scenario_id=area.scenario_id
           WHERE element.project_id=? AND area.scenario_id=? AND area.section_id=?
             AND LOWER(
                   COALESCE(NULLIF(TRIM(element.work_type), ''), 'Cycle')
                 )='cycle'
           GROUP BY element.id
           ORDER BY area.name, pitch.sequence, element.sequence""",
        (project_id, scenario_id, section_id),
    ))

def yamazumi_context_for_process(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Return Yamazumi source labels linked to Process at a Glance rows."""
    rows = query(
        """SELECT element.process_element_id, element.id AS yamazumi_element_id,
                   element.description AS yamazumi_description,
                   element.time_s AS yamazumi_time_s,
                   pitch.id AS pitch_id, pitch.pitch_number, pitch.pitch_name
           FROM yamazumi_elements element
           JOIN yamazumi_areas area ON area.id=element.area_id
           LEFT JOIN yamazumi_pitches pitch ON pitch.id=element.pitch_id
           WHERE element.project_id=? AND area.scenario_id=?
             AND element.process_element_id IS NOT NULL
             AND TRIM(element.process_element_id) <> ''
           ORDER BY area.name, pitch.sequence, element.sequence""",
        (project_id, scenario_id),
    )
    return pd.DataFrame(rows)

def process_element_id_for_yamazumi(
    project_id: str, scenario_id: str, yamazumi_element_id: str
) -> str | None:
    rows = query(
        """SELECT element.process_element_id
           FROM yamazumi_elements element
           JOIN yamazumi_areas area ON area.id=element.area_id
           WHERE element.id=? AND element.project_id=? AND area.scenario_id=?""",
        (yamazumi_element_id, project_id, scenario_id),
    )
    if not rows:
        return None
    return str(rows[0].get("process_element_id") or "").strip() or None

def process_part_groups(
    project_id: str,
    scenario_id: str,
    work_element_id: str | None = None,
    *,
    active_only: bool = False,
) -> list[dict]:
    element_clause = " AND group_row.work_element_id=?" if work_element_id else ""
    params = (project_id, scenario_id, work_element_id) if work_element_id else (project_id, scenario_id)
    groups = query(
        f"""SELECT group_row.*, section.name AS section_name,
                   element.operation, element.station
            FROM process_part_groups group_row
            JOIN work_elements element ON element.id=group_row.work_element_id
            LEFT JOIN assembly_sections section ON section.id=group_row.section_id
            WHERE group_row.project_id=? AND group_row.scenario_id=?{element_clause}
            ORDER BY element.sequence, group_row.name""",
        params,
    )
    for group in groups:
        activity_join = """
            LEFT JOIN part_scenario_activity activity
              ON activity.project_id=? AND activity.scenario_id=?
             AND activity.part_id=option.part_id
        """ if active_only else ""
        activity_clause = " AND COALESCE(activity.active, 1)=1" if active_only else ""
        option_params = (
            (project_id, scenario_id, group["id"])
            if active_only else (group["id"],)
        )
        options = query(
            f"""SELECT option.id, option.part_id, option.handling_type,
                      option.fishbone_assignment_id,
                      part.part_number, part.description AS part_description,
                      part.model_applicability, part.weight_lb
               FROM process_part_options option
               JOIN parts part ON part.id=option.part_id
               {activity_join}
               WHERE option.group_id=?{activity_clause} ORDER BY part.part_number""",
            option_params,
        )
        group["options"] = options
        group["part_ids"] = [str(option["part_id"]) for option in options]
    return [group for group in groups if group["options"]] if active_only else groups

def save_process_part_group(
    project_id: str,
    scenario_id: str,
    work_element_id: str,
    section_id: str,
    group_id: str | None,
    name: str,
    selection_rule: str,
    quantity: float,
    part_ids: list[str],
    notes: str = "",
    handling_types_by_part: dict[str, str | None] | None = None,
    fishbone_assignment_ids_by_part: dict[str, str | None] | None = None,
) -> str:
    name = str(name or "").strip()
    if not name:
        raise ValueError("Part requirement name is required.")
    if selection_rule not in MATERIAL_SELECTION_RULES:
        raise ValueError("Choose a valid part-selection rule.")
    quantity = _optional_nonnegative_number(quantity, "Part quantity")
    if quantity is None or quantity <= 0:
        raise ValueError("Part quantity must be greater than zero.")
    selected_part_ids = list(dict.fromkeys(str(part_id) for part_id in part_ids if str(part_id)))
    if not selected_part_ids:
        raise ValueError("Select at least one fishbone part.")
    normalized_handling_types: dict[str, str | None] = {}
    if handling_types_by_part is not None:
        unknown_part_ids = set(handling_types_by_part) - set(selected_part_ids)
        if unknown_part_ids:
            raise ValueError("Handling types may only be supplied for selected parts.")
        for part_id, value in handling_types_by_part.items():
            normalized_handling_types[str(part_id)] = _normalize_handling_type(value)
    normalized_assignment_ids: dict[str, str | None] = {}
    if fishbone_assignment_ids_by_part is not None:
        unknown_part_ids = set(fishbone_assignment_ids_by_part) - set(selected_part_ids)
        if unknown_part_ids:
            raise ValueError("Fishbone placements may only be supplied for selected parts.")
        for part_id, value in fishbone_assignment_ids_by_part.items():
            normalized_assignment_ids[str(part_id)] = _normalize_fishbone_assignment_id(value)
    group_id = str(group_id or "").strip() or str(uuid4())
    timestamp = now_iso()
    try:
        with connection() as conn:
            if not conn.execute(
                """SELECT 1 FROM work_elements
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (work_element_id, project_id, scenario_id),
            ).fetchone():
                raise ValueError("That process-plan work element no longer exists.")
            if not conn.execute(
                "SELECT 1 FROM assembly_sections WHERE id=? AND project_id=? AND active=1",
                (section_id, project_id),
            ).fetchone():
                raise ValueError("Choose an active fishbone section.")
            existing_group = conn.execute(
                """SELECT project_id, scenario_id, work_element_id
                   FROM process_part_groups WHERE id=?""",
                (group_id,),
            ).fetchone()
            if existing_group and (
                str(existing_group["project_id"]) != project_id
                or str(existing_group["scenario_id"]) != scenario_id
                or str(existing_group["work_element_id"]) != work_element_id
            ):
                raise ValueError("That part requirement no longer belongs to this process step.")
            placeholders = ",".join("?" for _ in selected_part_ids)
            available = {
                str(row[0]) for row in conn.execute(
                    f"""SELECT DISTINCT part_id FROM fishbone_part_assignments
                        WHERE project_id=? AND section_id=? AND part_id IN ({placeholders})""",
                    (project_id, section_id, *selected_part_ids),
                ).fetchall()
            }
            if available != set(selected_part_ids):
                raise ValueError("Every selected part must be available in the active fishbone section.")
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id, name,
                    selection_rule, quantity, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET section_id=excluded.section_id,
                    name=excluded.name, selection_rule=excluded.selection_rule,
                    quantity=excluded.quantity, notes=excluded.notes,
                    updated_at=excluded.updated_at""",
                (
                    group_id, project_id, scenario_id, work_element_id, section_id,
                    name, selection_rule, quantity, str(notes or "").strip(), timestamp,
                ),
            )
            existing_options = {
                str(row["part_id"]): dict(row)
                for row in conn.execute(
                    """SELECT id, part_id, handling_type, fishbone_assignment_id
                       FROM process_part_options WHERE group_id=?""",
                    (group_id,),
                ).fetchall()
            }
            conn.execute(
                f"""DELETE FROM process_part_options
                    WHERE group_id=? AND part_id NOT IN ({placeholders})""",
                (group_id, *selected_part_ids),
            )
            for part_id in selected_part_ids:
                existing_option = existing_options.get(part_id)
                handling_type = normalized_handling_types.get(
                    part_id,
                    existing_option.get("handling_type") if existing_option else None,
                )
                fishbone_assignment_id = normalized_assignment_ids.get(
                    part_id,
                    existing_option.get("fishbone_assignment_id") if existing_option else None,
                )
                option_id = (
                    str(existing_option["id"]) if existing_option else str(uuid4())
                )
                _validate_process_part_option_handling(
                    conn,
                    project_id=project_id,
                    scenario_id=scenario_id,
                    section_id=section_id,
                    process_part_option_id=option_id,
                    part_id=part_id,
                    handling_type=handling_type,
                    fishbone_assignment_id=fishbone_assignment_id,
                )
                if existing_option:
                    conn.execute(
                        """UPDATE process_part_options
                           SET handling_type=?, fishbone_assignment_id=?, updated_at=?
                           WHERE id=? AND group_id=?""",
                        (
                            handling_type,
                            fishbone_assignment_id,
                            timestamp,
                            option_id,
                            group_id,
                        ),
                    )
                else:
                    conn.execute(
                        """INSERT INTO process_part_options
                           (id, group_id, part_id, handling_type,
                            fishbone_assignment_id, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            option_id,
                            group_id,
                            part_id,
                            handling_type,
                            fishbone_assignment_id,
                            timestamp,
                        ),
                    )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Part requirement names must be unique within a process step.") from exc
    return group_id

def set_part_weight_lb(project_id: str, part_id: str, weight_lb) -> str:
    """Set or clear a project-wide Parts Catalog weight in pounds."""
    weight = _optional_nonnegative_number(weight_lb, "Part weight")
    if weight is not None and not math.isfinite(weight):
        raise ValueError("Part weight must be a finite number.")
    timestamp = now_iso()
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM parts WHERE id=? AND project_id=?",
            (part_id, project_id),
        ).fetchone():
            raise ValueError("That part no longer exists in this project.")
        conn.execute(
            "UPDATE parts SET weight_lb=?, updated_at=? WHERE id=? AND project_id=?",
            (weight, timestamp, part_id, project_id),
        )
    return timestamp

def set_process_part_option_handling_type(
    project_id: str,
    scenario_id: str,
    process_part_option_id: str,
    handling_type: str | None,
    fishbone_assignment_id: str | None = None,
) -> str:
    """Classify one scenario-specific Process part-use, or restore compatibility NULL."""
    normalized = _normalize_handling_type(handling_type)
    timestamp = now_iso()
    with connection() as conn:
        option = conn.execute(
            """SELECT option.id, option.part_id, group_row.section_id
               FROM process_part_options option
               JOIN process_part_groups group_row ON group_row.id=option.group_id
               WHERE option.id=? AND group_row.project_id=? AND group_row.scenario_id=?""",
            (process_part_option_id, project_id, scenario_id),
        ).fetchone()
        if not option:
            raise ValueError("That Process part-use no longer exists in this scenario.")
        normalized_assignment_id = _normalize_fishbone_assignment_id(
            fishbone_assignment_id
        )
        _validate_process_part_option_handling(
            conn,
            project_id=project_id,
            scenario_id=scenario_id,
            section_id=str(option["section_id"] or ""),
            process_part_option_id=process_part_option_id,
            part_id=str(option["part_id"]),
            handling_type=normalized,
            fishbone_assignment_id=normalized_assignment_id,
        )
        conn.execute(
            """UPDATE process_part_options
               SET handling_type=?, fishbone_assignment_id=?, updated_at=?
               WHERE id=?""",
            (
                normalized,
                normalized_assignment_id,
                timestamp,
                process_part_option_id,
            ),
        )
    return timestamp

def work_element_criticality(
    project_id: str, scenario_id: str
) -> dict[str, list[str]]:
    """Return live CTQ and Safety tags keyed by scenario-owned Process step."""
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        result: dict[str, list[str]] = {
            str(row["id"]): []
            for row in conn.execute(
                """SELECT id FROM work_elements
                   WHERE project_id=? AND scenario_id=?""",
                (project_id, scenario_id),
            ).fetchall()
        }
        placeholders = ",".join("?" for _ in PFMEA_CTQ_CLASSIFICATIONS)
        for row in conn.execute(
            f"""SELECT DISTINCT entry.work_element_id
                FROM pfmea_entries entry
                JOIN work_elements work
                  ON work.id=entry.work_element_id
                 AND work.project_id=entry.project_id
                 AND work.scenario_id=entry.scenario_id
                WHERE entry.project_id=? AND entry.scenario_id=?
                  AND entry.class_code IN ({placeholders})""",
            (project_id, scenario_id, *PFMEA_CTQ_CLASSIFICATIONS),
        ).fetchall():
            work_element_id = str(row["work_element_id"])
            if work_element_id in result:
                result[work_element_id].append("CTQ")
        for row in conn.execute(
            """SELECT DISTINCT requirement.work_element_id
               FROM safety_requirements requirement
               JOIN work_elements work
                 ON work.id=requirement.work_element_id
                AND work.project_id=requirement.project_id
                AND work.scenario_id=requirement.scenario_id
               WHERE requirement.project_id=? AND requirement.scenario_id=?
                 AND requirement.active=1""",
            (project_id, scenario_id),
        ).fetchall():
            work_element_id = str(row["work_element_id"])
            if work_element_id in result:
                result[work_element_id].append("Safety")
    return result

def delete_process_part_groups(
    project_id: str, scenario_id: str, group_ids: list[str]
) -> int:
    """Delete validated process-part groups together and reopen their source parts."""
    normalized_ids = list(
        dict.fromkeys(
            str(group_id).strip()
            for group_id in group_ids
            if str(group_id).strip()
        )
    )
    if not normalized_ids:
        return 0
    placeholders = ", ".join("?" for _ in normalized_ids)
    with connection() as conn:
        group_rows = conn.execute(
            f"""SELECT id, work_element_id FROM process_part_groups
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *normalized_ids),
        ).fetchall()
        found_ids = {str(row["id"]) for row in group_rows}
        missing_ids = [group_id for group_id in normalized_ids if group_id not in found_ids]
        if missing_ids:
            raise ValueError(
                "One or more selected part pairings no longer exist. Refresh and try again."
            )
        affected_work_element_ids = {
            str(row["work_element_id"]) for row in group_rows
        }
        cursor = conn.execute(
            f"""DELETE FROM process_part_groups
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *normalized_ids),
        )
        timestamp = now_iso()
        for work_element_id in affected_work_element_ids:
            remaining = conn.execute(
                """SELECT 1 FROM process_part_groups
                   WHERE project_id=? AND scenario_id=? AND work_element_id=? LIMIT 1""",
                (project_id, scenario_id, work_element_id),
            ).fetchone()
            if not remaining:
                conn.execute(
                    """UPDATE yamazumi_elements
                       SET process_sync_status='Needs IE review', updated_at=?
                       WHERE project_id=? AND process_element_id=?""",
                    (timestamp, project_id, work_element_id),
                )
        return int(cursor.rowcount)

def delete_process_part_group(
    project_id: str, scenario_id: str, group_id: str
) -> bool:
    return bool(delete_process_part_groups(project_id, scenario_id, [group_id]))

def pin_map_for_scenario(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Load pitches and their explicitly linked Process work for one scenario."""
    rows = pd.DataFrame(query(
        """SELECT p.id AS pitch_id, p.area_id, a.name AS area_name,
                  a.section_id,
                  p.pitch_number, p.pitch_name, p.pitch_type,
                  p.status AS pitch_status, p.sequence AS pitch_sequence,
                  work.id AS process_element_id,
                  work.sequence AS process_sequence,
                  work.operation AS work_element,
                  work.description AS process_description,
                  work.cycle_time_s, work.tool, work.torque,
                  work.quality_requirement, work.ergo_requirement,
                  work.location, work.unit_orientation,
                  work.model_applicability,
                  work.status AS process_status
           FROM yamazumi_pitches p
           JOIN yamazumi_areas a ON a.id=p.area_id
           LEFT JOIN yamazumi_elements yamazumi
             ON yamazumi.pitch_id=p.id AND yamazumi.project_id=p.project_id
           LEFT JOIN work_elements work
             ON work.id=yamazumi.process_element_id
            AND work.project_id=p.project_id
            AND work.scenario_id=a.scenario_id
           WHERE p.project_id=? AND a.scenario_id=?
           ORDER BY a.name, p.sequence, p.pitch_number,
                    work.sequence, work.operation""",
        (project_id, scenario_id),
    ))
    if rows.empty:
        return pd.DataFrame({
            "pitch_id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "area_name": pd.Series(dtype="string"),
            "section_id": pd.Series(dtype="string"),
            "pitch_number": pd.Series(dtype="string"),
            "pitch_name": pd.Series(dtype="string"),
            "pitch_type": pd.Series(dtype="string"),
            "pitch_status": pd.Series(dtype="string"),
            "pitch_sequence": pd.Series(dtype="Int64"),
            "process_element_id": pd.Series(dtype="string"),
            "process_sequence": pd.Series(dtype="Int64"),
            "work_element": pd.Series(dtype="string"),
            "process_description": pd.Series(dtype="string"),
            "cycle_time_s": pd.Series(dtype="Float64"),
            "tool": pd.Series(dtype="string"),
            "torque": pd.Series(dtype="string"),
            "quality_requirement": pd.Series(dtype="string"),
            "ergo_requirement": pd.Series(dtype="string"),
            "location": pd.Series(dtype="string"),
            "unit_orientation": pd.Series(dtype="string"),
            "model_applicability": pd.Series(dtype="string"),
            "process_status": pd.Series(dtype="string"),
        })
    rows = rows.drop_duplicates(
        subset=["pitch_id", "process_element_id"], keep="first"
    )
    linked_pitch_ids = set(
        rows.loc[rows["process_element_id"].notna(), "pitch_id"].astype(str)
    )
    rows = rows.loc[
        ~(
            rows["pitch_id"].astype(str).isin(linked_pitch_ids)
            & rows["process_element_id"].isna()
        )
    ]
    return rows.reset_index(drop=True)

def reconcile_yamazumi_to_process(project_id: str, scenario_id: str, element_ids: list[str]) -> int:
    """Accept Yamazumi station/time changes while retaining IE-authored process details."""
    if not element_ids:
        return 0
    placeholders = ",".join("?" for _ in element_ids)
    timestamp = now_iso()
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT e.*, p.pitch_number, a.name AS area_name
                FROM yamazumi_elements e
                LEFT JOIN yamazumi_pitches p ON p.id=e.pitch_id
                JOIN yamazumi_areas a ON a.id=e.area_id
                WHERE e.project_id=? AND a.scenario_id=? AND e.id IN ({placeholders})""",
            (project_id, scenario_id, *element_ids),
        ).fetchall()
        for row in rows:
            station = str(row["pitch_number"] or "Unassigned")
            model_variants = parse_yamazumi_model_variants(
                row["model_variants"], row["model_variant"]
            )
            model_applicability = (
                "All"
                if any(value.casefold() == "base" for value in model_variants)
                else ", ".join(model_variants)
            )
            process_id = str(row["process_element_id"] or "").strip()
            if process_id:
                exists = conn.execute(
                    "SELECT 1 FROM work_elements WHERE id=? AND project_id=? AND scenario_id=?",
                    (process_id, project_id, scenario_id),
                ).fetchone()
            else:
                exists = None
            if exists:
                conn.execute(
                    """UPDATE work_elements SET station=?, cycle_time_s=?, model_applicability=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=?""",
                    (
                        station, float(row["time_s"] or 0),
                        model_applicability,
                        timestamp, process_id, project_id, scenario_id,
                    ),
                )
            else:
                next_sequence = conn.execute(
                    """SELECT COALESCE(MAX(sequence), 0) + 10 FROM work_elements
                       WHERE project_id=? AND scenario_id=?""",
                    (project_id, scenario_id),
                ).fetchone()[0]
                process_id = _create_work_element_with_started_ergonomics_review(
                    conn,
                    project_id,
                    scenario_id,
                    {
                        "sequence": next_sequence,
                        "station": station,
                        "operation": str(row["description"]),
                        "description": f"Yamazumi area: {row['area_name']}",
                        "cycle_time_s": float(row["time_s"] or 0),
                        "part_number": "",
                        "tool": "",
                        "torque": "",
                        "quality_requirement": "",
                        "ergo_requirement": "",
                        "location": station,
                        "conveyor_height_in": None,
                        "platform_height_in": None,
                        "pit_depth_in": None,
                        "model_applicability": model_applicability,
                        "status": "Draft",
                    },
                    timestamp,
                )
            conn.execute(
                """UPDATE yamazumi_elements SET process_element_id=?, process_sync_status='Synced', updated_at=?
                   WHERE id=? AND project_id=?""",
                (process_id, timestamp, row["id"], project_id),
            )
    return len(rows)

def _op_id_depth_letter(depth: int) -> str:
    """Return a lowercase spreadsheet-style letter for a zero-based depth."""
    value = depth + 1
    letters = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(ord("a") + remainder) + letters
    return letters

def parse_yamazumi_pitch_address(value: object) -> dict[str, object]:
    """Decode the approved Pitch convention into natural-order components."""
    address = str(value or "").strip()
    match = _YAMAZUMI_PITCH_ADDRESS_PATTERN.fullmatch(address)
    if not match:
        return {
            "address": address,
            "parsed": False,
            "subline_number": 0,
            "work_area_letters": "",
            "work_area_number": 0,
            "position_number": 0,
        }
    return {
        "address": address,
        "parsed": True,
        "subline_number": int(match.group("subline")),
        "work_area_letters": match.group("work_area_letters").casefold(),
        "work_area_number": int(match.group("work_area_number")),
        "position_number": int(match.group("position")),
    }

def work_element_op_contexts(
    project_id: str,
    scenario_id: str,
    work_element_ids: list[str] | None = None,
) -> dict[str, dict]:
    """Compute live Op ID labels and physical picker order without persisting them."""
    requested_ids = None
    if work_element_ids is not None:
        requested_ids = list(dict.fromkeys(
            str(value or "").strip() for value in work_element_ids
            if str(value or "").strip()
        ))
        if not requested_ids:
            return {}

    with connection() as conn:
        scenario = conn.execute(
            "SELECT id FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone()
        if not scenario:
            raise ValueError("The active planning scenario no longer exists in this project.")

        parameters: list[object] = [project_id, scenario_id]
        work_filter = ""
        if requested_ids is not None:
            placeholders = ",".join("?" for _ in requested_ids)
            work_filter = f" AND id IN ({placeholders})"
            parameters.extend(requested_ids)
        work_rows = conn.execute(
            f"""SELECT id, sequence AS work_sequence FROM work_elements
                WHERE project_id=? AND scenario_id=?{work_filter}
                ORDER BY sequence, id""",
            tuple(parameters),
        ).fetchall()
        work_ids = [str(row["id"]) for row in work_rows]
        work_sequence_by_id = {
            str(row["id"]): int(row["work_sequence"] or 0) for row in work_rows
        }
        if requested_ids is not None and set(work_ids) != set(requested_ids):
            raise ValueError(
                "One or more Process at a Glance Work Elements are missing or belong to "
                "another planning scenario."
            )
        if not work_ids:
            return {}

        yamazumi_rows = conn.execute(
            """SELECT element.id AS yamazumi_element_id,
                      element.process_element_id, element.pitch_id,
                      element.sequence, element.description,
                      area.id AS area_id, area.section_id,
                      pitch.id AS resolved_pitch_id, pitch.pitch_number,
                      pitch.sequence AS pitch_sequence
               FROM yamazumi_elements element
               JOIN yamazumi_areas area
                 ON area.id=element.area_id
                AND area.project_id=element.project_id
                AND area.scenario_id=?
               LEFT JOIN yamazumi_pitches pitch
                 ON pitch.id=element.pitch_id
                AND pitch.project_id=element.project_id
                AND pitch.area_id=area.id
               WHERE element.project_id=?
               ORDER BY element.sequence,
                        element.description COLLATE NOCASE,
                        element.id""",
            (scenario_id, project_id),
        ).fetchall()

    links_by_work: dict[str, list[sqlite3.Row]] = {}
    stack_rows: dict[str, list[sqlite3.Row]] = {}
    for row in yamazumi_rows:
        process_id = str(row["process_element_id"] or "").strip()
        if process_id:
            links_by_work.setdefault(process_id, []).append(row)
        pitch_id = str(row["resolved_pitch_id"] or "").strip()
        if pitch_id:
            stack_rows.setdefault(pitch_id, []).append(row)
    stack_positions = {
        str(row["yamazumi_element_id"]): position
        for rows in stack_rows.values()
        for position, row in enumerate(rows, start=1)
    }

    walk = assembly_section_walk_order(project_id)
    section_by_id = {
        str(row["id"]): row.to_dict() for _, row in walk.iterrows()
    } if not walk.empty else {}
    mainline_numbers = {
        str(row["id"]): position
        for position, (_, row) in enumerate(
            walk.loc[walk["section_type"].eq("Main spine")].iterrows(), start=1
        )
    } if not walk.empty else {}
    subassembly_children: dict[str, list[str]] = {}
    for section_id, section in section_by_id.items():
        if str(section.get("section_type") or "") != "Subassembly":
            continue
        parent_id = str(section.get("parent_id") or "").strip()
        subassembly_children.setdefault(parent_id, []).append(section_id)
    for child_ids in subassembly_children.values():
        child_ids.sort(
            key=lambda child_id: (
                int(section_by_id[child_id]["sequence"]),
                str(section_by_id[child_id]["name"]),
            )
        )

    def fishbone_prefix(section_id: str) -> str | None:
        section = section_by_id.get(section_id)
        if not section:
            return None
        if str(section.get("section_type") or "") == "Main spine":
            number = mainline_numbers.get(section_id)
            return f"M{number}" if number else None

        reverse_path: list[str] = []
        visited: set[str] = set()
        current_id = section_id
        mainline_id = ""
        while current_id and current_id not in visited:
            visited.add(current_id)
            current = section_by_id.get(current_id)
            if not current:
                return None
            section_type = str(current.get("section_type") or "")
            if section_type == "Main spine":
                mainline_id = current_id
                break
            if section_type != "Subassembly":
                return None
            reverse_path.append(current_id)
            current_id = str(current.get("parent_id") or "").strip()
        if not mainline_id or mainline_id not in mainline_numbers:
            return None

        path = list(reversed(reverse_path))
        lineages = subassembly_children.get(mainline_id, [])
        if not path or path[0] not in lineages:
            return None
        lineage_number = lineages.index(path[0]) + 1
        branch_path: list[str] = []
        for depth, path_section_id in enumerate(path):
            if depth:
                parent_id = path[depth - 1]
                siblings = subassembly_children.get(parent_id, [])
                if path_section_id not in siblings:
                    return None
                if len(siblings) > 1:
                    branch_path.append(str(siblings.index(path_section_id) + 1))
            depth_designator = _op_id_depth_letter(depth) + "".join(branch_path)
        return f"M{mainline_numbers[mainline_id]}S{lineage_number}{depth_designator}"

    section_order = {
        str(row["id"]): position
        for position, (_, row) in enumerate(walk.iterrows())
    } if not walk.empty else {}
    result: dict[str, dict] = {}

    def incomplete(work_id: str, label: str) -> None:
        result[work_id] = {
            "op_id": label,
            "complete": False,
            "sort_key": (
                1,
                work_sequence_by_id.get(work_id, 0),
                work_id,
            ),
        }

    for work_id in work_ids:
        links = links_by_work.get(work_id, [])
        if not links:
            incomplete(work_id, "Yamazumi link required")
            continue
        if len(links) != 1:
            incomplete(work_id, "Unique Yamazumi link required")
            continue
        link = links[0]
        pitch_id = str(link["resolved_pitch_id"] or "").strip()
        if not pitch_id:
            incomplete(work_id, "Yamazumi pitch required")
            continue
        section_id = str(link["section_id"] or "").strip()
        if not section_id:
            incomplete(work_id, "Fishbone link required")
            continue
        prefix = fishbone_prefix(section_id)
        if not prefix:
            incomplete(work_id, "Fishbone hierarchy required")
            continue
        position = stack_positions.get(str(link["yamazumi_element_id"]))
        if position is None:
            incomplete(work_id, "Yamazumi link required")
            continue
        pitch_address = parse_yamazumi_pitch_address(link["pitch_number"])
        result[work_id] = {
            "op_id": f"{prefix}.{link['pitch_number']}.{position}",
            "complete": True,
            "sort_key": (
                0,
                section_order.get(section_id, len(section_order)),
                0 if pitch_address["parsed"] else 1,
                int(pitch_address["subline_number"]),
                str(pitch_address["work_area_letters"]),
                int(pitch_address["work_area_number"]),
                int(pitch_address["position_number"]),
                int(link["pitch_sequence"] or 0),
                int(link["sequence"] or 0),
                position,
                work_id,
            ),
        }

    ordered_ids = sorted(result, key=lambda work_id: result[work_id]["sort_key"])
    for sort_order, work_id in enumerate(ordered_ids):
        result[work_id]["sort_order"] = sort_order
        result[work_id].pop("sort_key", None)
    return result

def work_element_op_ids(
    project_id: str,
    scenario_id: str,
    work_element_ids: list[str] | None = None,
) -> dict[str, str]:
    """Compute scenario-scoped, human-readable Op IDs without persisting them."""
    contexts = work_element_op_contexts(project_id, scenario_id, work_element_ids)
    return {work_id: str(context["op_id"]) for work_id, context in contexts.items()}

def work_element_op_id(project_id: str, scenario_id: str, work_element_id: str) -> str:
    """Compute one Op ID through the shared batch implementation."""
    normalized_id = str(work_element_id or "").strip()
    if not normalized_id:
        raise ValueError("Choose a Process at a Glance Work Element.")
    return work_element_op_ids(project_id, scenario_id, [normalized_id])[normalized_id]

def process_pitch_visual_summary(
    project_id: str, scenario_id: str, pitch_id: str
) -> dict:
    """Return one scenario-owned pitch and its Process-linked visual-summary rows."""
    normalized_pitch_id = str(pitch_id or "").strip()
    if not normalized_pitch_id:
        raise ValueError("Choose a Yamazumi pitch.")

    with connection() as conn:
        scenario = conn.execute(
            "SELECT id FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone()
        if not scenario:
            raise ValueError("The active planning scenario no longer exists in this project.")
        pitch = conn.execute(
            """SELECT pitch.id, pitch.pitch_number, pitch.pitch_name, pitch.sequence,
                      area.id AS area_id, area.section_id, area.name AS area_name
               FROM yamazumi_pitches pitch
               JOIN yamazumi_areas area
                 ON area.id=pitch.area_id AND area.project_id=pitch.project_id
               WHERE pitch.id=? AND pitch.project_id=? AND area.scenario_id=?""",
            (normalized_pitch_id, project_id, scenario_id),
        ).fetchone()
        if not pitch:
            raise ValueError("The selected pitch no longer exists in the active planning scenario.")

        rows = conn.execute(
            """SELECT work.id AS work_element_id, work.operation,
                      work.model_applicability, work.sequence AS process_sequence,
                      yamazumi.id AS yamazumi_element_id,
                      yamazumi.description AS yamazumi_description,
                      yamazumi.time_s, yamazumi.sequence AS stack_sequence
               FROM yamazumi_elements yamazumi
               JOIN yamazumi_areas area
                 ON area.id=yamazumi.area_id
                AND area.project_id=yamazumi.project_id
                AND area.scenario_id=?
               JOIN work_elements work
                 ON work.id=yamazumi.process_element_id
                AND work.project_id=yamazumi.project_id
                AND work.scenario_id=area.scenario_id
               WHERE yamazumi.project_id=? AND yamazumi.pitch_id=?
               ORDER BY yamazumi.sequence,
                        yamazumi.description COLLATE NOCASE,
                        yamazumi.id""",
            (scenario_id, project_id, normalized_pitch_id),
        ).fetchall()
        work_ids = [str(row["work_element_id"]) for row in rows]
        cards = [dict(row) for row in rows]

        parts_by_work: dict[str, list[dict]] = {work_id: [] for work_id in work_ids}
        handling_by_work: dict[str, list[str | None]] = {
            work_id: [] for work_id in work_ids
        }
        torque_by_work: dict[str, list[dict]] = {work_id: [] for work_id in work_ids}
        if work_ids:
            placeholders = ",".join("?" for _ in work_ids)
            part_rows = conn.execute(
                f"""SELECT group_row.work_element_id, option.handling_type,
                           part.id AS part_id, part.part_number,
                           part.description AS part_description,
                           COALESCE(NULLIF(TRIM(part.image_path), ''), (
                               SELECT image.image_path FROM part_images image
                               WHERE image.part_id=part.id
                               ORDER BY image.created_at, image.id LIMIT 1
                           ), '') AS image_path
                    FROM process_part_groups group_row
                    JOIN process_part_options option ON option.group_id=group_row.id
                    JOIN parts part
                      ON part.id=option.part_id AND part.project_id=group_row.project_id
                    LEFT JOIN part_scenario_activity activity
                      ON activity.project_id=group_row.project_id
                     AND activity.scenario_id=group_row.scenario_id
                     AND activity.part_id=part.id
                    WHERE group_row.project_id=? AND group_row.scenario_id=?
                      AND group_row.work_element_id IN ({placeholders})
                      AND COALESCE(activity.active, 1)=1
                    ORDER BY group_row.work_element_id, group_row.name,
                             part.part_number""",
                (project_id, scenario_id, *work_ids),
            ).fetchall()
            for row in part_rows:
                work_id = str(row["work_element_id"])
                part = dict(row)
                handling_by_work[work_id].append(part.pop("handling_type"))
                part.pop("work_element_id", None)
                parts_by_work[work_id].append(part)

            torque_rows = conn.execute(
                f"""SELECT assignment.work_element_id, assignment.unique_identifier,
                           assignment.target_value, assignment.tolerances,
                           assignment.unit
                    FROM quality_requirement_assignments assignment
                    JOIN quality_requirement_torque_details detail
                      ON detail.quality_requirement_id=assignment.quality_requirement_id
                     AND detail.project_id=assignment.project_id
                    WHERE assignment.project_id=? AND assignment.scenario_id=?
                      AND assignment.requirement_type='Torque'
                      AND assignment.work_element_id IN ({placeholders})
                    ORDER BY assignment.work_element_id,
                             assignment.unique_identifier COLLATE NOCASE,
                             assignment.id""",
                (project_id, scenario_id, *work_ids),
            ).fetchall()
            for row in torque_rows:
                torque = dict(row)
                work_id = str(torque.pop("work_element_id"))
                torque_by_work[work_id].append(torque)

    op_ids = work_element_op_ids(project_id, scenario_id, work_ids) if work_ids else {}
    risk_ids = process_ergonomics_risk_work_element_ids(project_id, scenario_id)
    for card in cards:
        work_id = str(card["work_element_id"])
        handling_values = handling_by_work.get(work_id, [])
        normalized_handling = {
            str(value).strip() for value in handling_values if str(value or "").strip()
        }
        has_null = any(not str(value or "").strip() for value in handling_values)
        if normalized_handling == {"Consume"} and not has_null:
            classification = "Value-Added (VA)"
            color = "green"
        elif normalized_handling == {"Handle"} and not has_null:
            classification = "Non-Value-Added but Necessary (NVAN)"
            color = "orange"
        else:
            classification = "Unclassified"
            color = "gray"
        card.update(
            op_id=op_ids.get(work_id, "Yamazumi link required"),
            parts=parts_by_work.get(work_id, []),
            motion_classification=classification,
            motion_color=color,
            ergonomics_risk=work_id in risk_ids,
            torque_requirements=torque_by_work.get(work_id, []),
        )

    return {**dict(pitch), "elements": cards}

def replace_work_elements(project_id: str, scenario_id: str, edited: pd.DataFrame) -> None:
    fields = ["sequence", "station", "operation", "description", "cycle_time_s", "part_number", "tool", "torque",
              "quality_requirement", "ergo_requirement", "location", "unit_orientation", "conveyor_height_in", "platform_height_in",
              "pit_depth_in", "model_applicability", "status", "output_assembly_number",
              "output_assembly_name"]
    records: list[tuple[str, list]] = []
    assembly_numbers: set[str] = set()
    for _, row in edited.iterrows():
        if not str(row.get("operation", "")).strip():
            continue
        element_id = (
            str(row.get("id"))
            if row.get("id") is not None and not pd.isna(row.get("id")) and str(row.get("id")).strip()
            else str(uuid4())
        )
        values = []
        for field in fields:
            value = row.get(field, "")
            if value is None or pd.isna(value):
                value = None if field.endswith("_in") else (0 if field in {"sequence", "cycle_time_s"} else "")
            values.append(value)
        output_number = str(values[fields.index("output_assembly_number")] or "").strip()
        if output_number:
            normalized = output_number.casefold()
            if normalized in assembly_numbers:
                raise ValueError("Each made-assembly output number can be completed only once in a scenario.")
            assembly_numbers.add(normalized)
        records.append((element_id, values))

    with connection() as conn:
        existing_ids = {
            str(row[0]) for row in conn.execute(
                "SELECT id FROM work_elements WHERE project_id=? AND scenario_id=?",
                (project_id, scenario_id),
            ).fetchall()
        }
        saved_ids = {element_id for element_id, _ in records}
        assignments = ", ".join(f"{field}=?" for field in fields)
        for element_id, values in records:
            timestamp = now_iso()
            if element_id in existing_ids:
                conn.execute(
                    f"""UPDATE work_elements
                        SET {assignments}, updated_at=?
                        WHERE id=? AND project_id=? AND scenario_id=?""",
                    (*values, timestamp, element_id, project_id, scenario_id),
                )
            else:
                _create_work_element_with_started_ergonomics_review(
                    conn,
                    project_id,
                    scenario_id,
                    dict(zip(fields, values)),
                    timestamp,
                    work_element_id=element_id,
                )
        removed = existing_ids - saved_ids
        if removed:
            placeholders = ",".join("?" for _ in removed)
            removed_rows = conn.execute(
                f"""SELECT id, operation, description, station, sequence, location
                    FROM work_elements
                    WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
                (project_id, scenario_id, *removed),
            ).fetchall()
            now_str = now_iso()
            for r in removed_rows:
                elem_id = r[0]
                op_val = str(r[1] or "")
                desc_val = str(r[2] or "")
                pitch_val = str(r[3] or "")
                seq_val = int(r[4] or 0)
                loc_val = str(r[5] or "")

                conn.execute(
                    """UPDATE quality_requirement_assignments
                       SET process_operation_snapshot = CASE WHEN process_operation_snapshot = '' THEN ? ELSE process_operation_snapshot END,
                           process_description_snapshot = CASE WHEN process_description_snapshot = '' THEN ? ELSE process_description_snapshot END,
                           station_pitch_snapshot = CASE WHEN station_pitch_snapshot = '' THEN ? ELSE station_pitch_snapshot END,
                           unlinked_at = CASE WHEN unlinked_at = '' THEN ? ELSE unlinked_at END,
                           work_element_id = NULL,
                           updated_at = ?
                       WHERE project_id=? AND scenario_id=? AND work_element_id=?""",
                    (op_val, desc_val, pitch_val, now_str, now_str, project_id, scenario_id, elem_id),
                )

                conn.execute(
                    """UPDATE equipment_process_links
                       SET process_operation_snapshot = CASE WHEN process_operation_snapshot = '' THEN ? ELSE process_operation_snapshot END,
                           process_description_snapshot = CASE WHEN process_description_snapshot = '' THEN ? ELSE process_description_snapshot END,
                           station_pitch_snapshot = CASE WHEN station_pitch_snapshot = '' THEN ? ELSE station_pitch_snapshot END,
                           unlinked_at = CASE WHEN unlinked_at = '' THEN ? ELSE unlinked_at END,
                           work_element_id = NULL,
                           updated_at = ?
                       WHERE project_id=? AND scenario_id=? AND work_element_id=?""",
                    (op_val, desc_val, pitch_val, now_str, now_str, project_id, scenario_id, elem_id),
                )

                conn.execute(
                    """UPDATE pfmea_entries
                       SET process_operation_snapshot = CASE WHEN process_operation_snapshot = '' THEN ? ELSE process_operation_snapshot END,
                           process_description_snapshot = CASE WHEN process_description_snapshot = '' THEN ? ELSE process_description_snapshot END,
                           process_pitch_snapshot = CASE WHEN process_pitch_snapshot = '' THEN ? ELSE process_pitch_snapshot END,
                           process_location_snapshot = CASE WHEN process_location_snapshot = '' THEN ? ELSE process_location_snapshot END,
                           process_sequence_snapshot = CASE WHEN process_sequence_snapshot = 0 THEN ? ELSE process_sequence_snapshot END,
                           work_element_id = NULL,
                           updated_at = ?
                       WHERE project_id=? AND scenario_id=? AND work_element_id=?""",
                    (op_val, desc_val, pitch_val, loc_val, seq_val, now_str, project_id, scenario_id, elem_id),
                )

            conn.execute(
                f"""UPDATE yamazumi_elements
                    SET process_element_id=NULL, process_sync_status='Needs IE review', updated_at=?
                    WHERE project_id=? AND process_element_id IN ({placeholders})""",
                (now_str, project_id, *removed),
            )
            conn.execute(
                f"""DELETE FROM work_elements WHERE project_id=? AND scenario_id=?
                    AND id IN ({placeholders})""",
                (project_id, scenario_id, *removed),
            )


def work_element_downstream_impact(
    project_id: str,
    scenario_id: str,
    work_element_ids: list[str] | set[str] | tuple[str, ...],
) -> dict:
    """Calculate the downstream impact across Quality, PFMEA, Equipment, and Safety before deleting work elements."""
    ids = [str(x) for x in work_element_ids if str(x).strip()]
    if not ids:
        return {
            "total_impact": 0,
            "has_impact": False,
            "quality_count": 0,
            "pfmea_count": 0,
            "equipment_count": 0,
            "safety_count": 0,
            "quality_records": [],
            "pfmea_records": [],
            "equipment_records": [],
            "safety_records": [],
            "operations_affected": [],
        }
    with _db_core.connection() as conn:
        placeholders = ",".join("?" for _ in ids)

        op_rows = conn.execute(
            f"""SELECT id, operation, description, station FROM work_elements
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        ).fetchall()
        op_map = {row[0]: {"operation": row[1] or "", "description": row[2] or "", "station": row[3] or ""} for row in op_rows}

        def _has_table(tbl: str) -> bool:
            return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tbl,)).fetchone() is not None

        quality_records = []
        if _has_table("quality_requirement_assignments"):
            q_rows = conn.execute(
                f"""SELECT id, quality_requirement_id, requirement_type, description, unique_identifier, work_element_id
                    FROM quality_requirement_assignments
                    WHERE project_id=? AND scenario_id=? AND work_element_id IN ({placeholders})""",
                (project_id, scenario_id, *ids),
            ).fetchall()
            quality_records = [
                {
                    "id": r[0],
                    "quality_requirement_id": r[1],
                    "requirement_type": r[2],
                    "description": r[3],
                    "unique_identifier": r[4],
                    "work_element_id": r[5],
                    "operation": op_map.get(r[5], {}).get("operation", ""),
                    "station": op_map.get(r[5], {}).get("station", ""),
                }
                for r in q_rows
            ]

        pfmea_records = []
        if _has_table("pfmea_entries"):
            pfmea_rows = conn.execute(
                f"""SELECT id, potential_failure_mode, class_code, work_element_id
                    FROM pfmea_entries
                    WHERE project_id=? AND scenario_id=? AND work_element_id IN ({placeholders})""",
                (project_id, scenario_id, *ids),
            ).fetchall()
            pfmea_records = [
                {
                    "id": r[0],
                    "potential_failure_mode": r[1],
                    "class_code": r[2],
                    "work_element_id": r[3],
                    "operation": op_map.get(r[3], {}).get("operation", ""),
                    "station": op_map.get(r[3], {}).get("station", ""),
                }
                for r in pfmea_rows
            ]

        equipment_records = []
        if _has_table("equipment_process_links"):
            eq_rows = conn.execute(
                f"""SELECT id, placement_id, work_element_id
                    FROM equipment_process_links
                    WHERE project_id=? AND scenario_id=? AND work_element_id IN ({placeholders})""",
                (project_id, scenario_id, *ids),
            ).fetchall()
            equipment_records = [
                {
                    "id": r[0],
                    "placement_id": r[1],
                    "work_element_id": r[2],
                    "operation": op_map.get(r[2], {}).get("operation", ""),
                    "station": op_map.get(r[2], {}).get("station", ""),
                }
                for r in eq_rows
            ]

        safety_records = []
        if _has_table("safety_requirements"):
            safe_rows = conn.execute(
                f"""SELECT id, requirement_description, work_element_id
                    FROM safety_requirements
                    WHERE project_id=? AND scenario_id=? AND work_element_id IN ({placeholders}) AND active=1""",
                (project_id, scenario_id, *ids),
            ).fetchall()
            safety_records = [
                {
                    "id": r[0],
                    "requirement_description": r[1],
                    "work_element_id": r[2],
                    "operation": op_map.get(r[2], {}).get("operation", ""),
                    "station": op_map.get(r[2], {}).get("station", ""),
                }
                for r in safe_rows
            ]

        ops_affected = sorted({
            op_map[w_id]["operation"]
            for w_id in (
                [r["work_element_id"] for r in quality_records]
                + [r["work_element_id"] for r in pfmea_records]
                + [r["work_element_id"] for r in equipment_records]
                + [r["work_element_id"] for r in safety_records]
            )
            if w_id in op_map and op_map[w_id]["operation"]
        })

        total = len(quality_records) + len(pfmea_records) + len(equipment_records) + len(safety_records)
        return {
            "total_impact": total,
            "has_impact": total > 0,
            "quality_count": len(quality_records),
            "pfmea_count": len(pfmea_records),
            "equipment_count": len(equipment_records),
            "safety_count": len(safety_records),
            "quality_records": quality_records,
            "pfmea_records": pfmea_records,
            "equipment_records": equipment_records,
            "safety_records": safety_records,
            "operations_affected": ops_affected,
        }


__domain_exports__ = ['_YAMAZUMI_PITCH_ADDRESS_PATTERN', '_normalize_handling_type', '_normalize_fishbone_assignment_id', '_process_part_assignment_consume_count', '_validate_process_part_option_handling', 'process_part_placement_options', 'validate_process_part_option_pairings', 'yamazumi_elements_for_section', 'yamazumi_context_for_process', 'process_element_id_for_yamazumi', 'process_part_groups', 'save_process_part_group', 'set_part_weight_lb', 'set_process_part_option_handling_type', 'work_element_criticality', 'delete_process_part_groups', 'delete_process_part_group', 'pin_map_for_scenario', 'reconcile_yamazumi_to_process', '_op_id_depth_letter', 'parse_yamazumi_pitch_address', 'work_element_op_contexts', 'work_element_op_ids', 'work_element_op_id', 'process_pitch_visual_summary', 'replace_work_elements', 'work_element_downstream_impact']
for _export_name in __domain_exports__:
    if callable(globals()[_export_name]):
        globals()[_export_name] = _db_core.domain_entrypoint(globals()[_export_name])
_db_core.register_domain_module(_sys.modules[__name__], __domain_exports__)
