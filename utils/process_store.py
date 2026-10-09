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

def get_pitch_visual_media(
    project_id: str, scenario_id: str, pitch_id: str
) -> list[dict]:
    """Return all visual media records and their tagged work elements for a pitch."""
    normalized_pitch_id = str(pitch_id or "").strip()
    if not normalized_pitch_id:
        return []
    with connection() as conn:
        media_rows = conn.execute(
            """SELECT m.*, pitch.pitch_number, pitch.pitch_name
               FROM process_visual_media m
               JOIN yamazumi_pitches pitch ON pitch.id=m.pitch_id
               WHERE m.project_id=? AND m.scenario_id=? AND m.pitch_id=?
               ORDER BY m.sequence, m.created_at, m.id""",
            (project_id, scenario_id, normalized_pitch_id),
        ).fetchall()
        if not media_rows:
            return []

        media_ids = [str(r["id"]) for r in media_rows]
        placeholders = ",".join("?" for _ in media_ids)
        tags_rows = conn.execute(
            f"""SELECT t.media_id, t.work_element_id, work.operation, work.sequence AS work_sequence
                FROM process_visual_media_tags t
                JOIN work_elements work ON work.id=t.work_element_id
                WHERE t.project_id=? AND t.scenario_id=? AND t.media_id IN ({placeholders})
                ORDER BY work.sequence, work.id""",
            (project_id, scenario_id, *media_ids),
        ).fetchall()
        tags_by_media: dict[str, list[dict]] = {mid: [] for mid in media_ids}
        for tr in tags_rows:
            tags_by_media[str(tr["media_id"])].append(dict(tr))

        results: list[dict] = []
        for mr in media_rows:
            row_dict = dict(mr)
            row_tags = tags_by_media.get(str(mr["id"]), [])
            row_dict["tagged_work_element_ids"] = [t["work_element_id"] for t in row_tags]
            row_dict["tagged_work_elements"] = row_tags
            results.append(row_dict)
        return results


MAX_VISUAL_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_VISUAL_VIDEO_BYTES = 25 * 1024 * 1024  # 25 MB


def save_pitch_visual_media(
    project_id: str,
    scenario_id: str,
    pitch_id: str,
    filename: str,
    file_bytes: bytes,
    media_type: str | None = None,
    caption: str = "",
    tagged_work_element_ids: list[str] | None = None,
    sequence: int = 10,
    current_editor: str = "Collaborator",
) -> dict:
    """Save an uploaded image or video visual aid, attach element tags, and record audit."""
    normalized_pitch_id = str(pitch_id or "").strip()
    if not normalized_pitch_id:
        raise ValueError("Choose a Yamazumi pitch.")
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
    target_path = UPLOAD_DIR / f"process_visual_{normalized_pitch_id}_{media_id}{suffix}"
    target_path.write_bytes(file_bytes)

    with connection() as conn:
        pitch = conn.execute(
            """SELECT pitch.id, pitch.pitch_number
               FROM yamazumi_pitches pitch
               JOIN yamazumi_areas area ON area.id=pitch.area_id
               WHERE pitch.id=? AND pitch.project_id=? AND area.scenario_id=?""",
            (normalized_pitch_id, project_id, scenario_id),
        ).fetchone()
        if not pitch:
            target_path.unlink(missing_ok=True)
            raise ValueError("The selected pitch does not exist in the active planning scenario.")

        conn.execute(
            """INSERT INTO process_visual_media
               (id, project_id, scenario_id, pitch_id, media_type, file_path, caption,
                sequence, created_at, created_by, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                media_id,
                project_id,
                scenario_id,
                normalized_pitch_id,
                resolved_media_type,
                str(target_path),
                str(caption or "").strip(),
                int(sequence or 10),
                timestamp,
                str(current_editor or "").strip(),
                timestamp,
            ),
        )

        valid_tags: list[str] = []
        if tagged_work_element_ids:
            for we_id in tagged_work_element_ids:
                cleaned_we_id = str(we_id or "").strip()
                if not cleaned_we_id:
                    continue
                exists = conn.execute(
                    "SELECT id FROM work_elements WHERE id=? AND project_id=? AND scenario_id=?",
                    (cleaned_we_id, project_id, scenario_id),
                ).fetchone()
                if exists:
                    tag_id = str(uuid4())
                    conn.execute(
                        """INSERT OR IGNORE INTO process_visual_media_tags
                           (id, media_id, work_element_id, project_id, scenario_id, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (tag_id, media_id, cleaned_we_id, project_id, scenario_id, timestamp),
                    )
                    valid_tags.append(cleaned_we_id)

    record_audit_event(
        project_id,
        "process_visual_media",
        "Add visual aid",
        1,
        str(current_editor or "").strip(),
        {"summary": f"Added {resolved_media_type} to pitch {pitch['pitch_number']}: '{caption or filename}'"},
    )
    return {
        "id": media_id,
        "project_id": project_id,
        "scenario_id": scenario_id,
        "pitch_id": normalized_pitch_id,
        "media_type": resolved_media_type,
        "file_path": str(target_path),
        "caption": str(caption or "").strip(),
        "sequence": int(sequence or 10),
        "tagged_work_element_ids": valid_tags,
        "created_at": timestamp,
        "created_by": str(current_editor or "").strip(),
    }


def update_pitch_visual_media(
    project_id: str,
    scenario_id: str,
    media_id: str,
    caption: str,
    tagged_work_element_ids: list[str] | None = None,
    sequence: int | None = None,
    current_editor: str = "Collaborator",
) -> None:
    """Update caption, sequence, and tagged elements for a visual aid."""
    normalized_media_id = str(media_id or "").strip()
    if not normalized_media_id:
        raise ValueError("Choose a visual aid to update.")

    timestamp = now_iso()
    with connection() as conn:
        existing = conn.execute(
            """SELECT m.id, m.pitch_id, pitch.pitch_number
               FROM process_visual_media m
               JOIN yamazumi_pitches pitch ON pitch.id=m.pitch_id
               WHERE m.id=? AND m.project_id=? AND m.scenario_id=?""",
            (normalized_media_id, project_id, scenario_id),
        ).fetchone()
        if not existing:
            raise ValueError("Visual aid not found in this scenario.")

        if sequence is not None:
            conn.execute(
                """UPDATE process_visual_media
                   SET caption=?, sequence=?, updated_at=?
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (str(caption or "").strip(), int(sequence), timestamp, normalized_media_id, project_id, scenario_id),
            )
        else:
            conn.execute(
                """UPDATE process_visual_media
                   SET caption=?, updated_at=?
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (str(caption or "").strip(), timestamp, normalized_media_id, project_id, scenario_id),
            )

        if tagged_work_element_ids is not None:
            conn.execute(
                "DELETE FROM process_visual_media_tags WHERE media_id=? AND project_id=? AND scenario_id=?",
                (normalized_media_id, project_id, scenario_id),
            )
            for we_id in tagged_work_element_ids:
                cleaned_we_id = str(we_id or "").strip()
                if not cleaned_we_id:
                    continue
                exists = conn.execute(
                    "SELECT id FROM work_elements WHERE id=? AND project_id=? AND scenario_id=?",
                    (cleaned_we_id, project_id, scenario_id),
                ).fetchone()
                if exists:
                    tag_id = str(uuid4())
                    conn.execute(
                        """INSERT OR IGNORE INTO process_visual_media_tags
                           (id, media_id, work_element_id, project_id, scenario_id, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (tag_id, normalized_media_id, cleaned_we_id, project_id, scenario_id, timestamp),
                    )

    record_audit_event(
        project_id,
        "process_visual_media",
        "Update visual aid",
        1,
        str(current_editor or "").strip(),
        {"summary": f"Updated visual aid on pitch {existing['pitch_number']}: '{caption}'"},
    )


def delete_pitch_visual_media(
    project_id: str,
    scenario_id: str,
    media_id: str,
    current_editor: str = "Collaborator",
) -> None:
    """Delete a visual aid, its tags, and underlying media file on disk."""
    normalized_media_id = str(media_id or "").strip()
    if not normalized_media_id:
        raise ValueError("Choose a visual aid to delete.")

    with connection() as conn:
        row = conn.execute(
            """SELECT m.id, m.file_path, m.caption, pitch.pitch_number
               FROM process_visual_media m
               JOIN yamazumi_pitches pitch ON pitch.id=m.pitch_id
               WHERE m.id=? AND m.project_id=? AND m.scenario_id=?""",
            (normalized_media_id, project_id, scenario_id),
        ).fetchone()
        if not row:
            raise ValueError("Visual aid not found.")

        file_path_str = row["file_path"]
        pitch_number = row["pitch_number"]
        caption = row["caption"]

        conn.execute(
            "DELETE FROM process_visual_media WHERE id=? AND project_id=? AND scenario_id=?",
            (normalized_media_id, project_id, scenario_id),
        )

    if file_path_str:
        p = Path(file_path_str)
        try:
            if p.exists() and p.is_file() and UPLOAD_DIR.resolve() in p.resolve().parents:
                p.unlink(missing_ok=True)
        except OSError:
            pass

    record_audit_event(
        project_id,
        "process_visual_media",
        "Delete visual aid",
        1,
        str(current_editor or "").strip(),
        {"summary": f"Deleted visual aid from pitch {pitch_number}: '{caption}'"},
    )


def process_pitch_visual_summary(
    project_id: str, scenario_id: str, pitch_id: str
) -> dict:
    """Return one scenario-owned pitch and its Process-linked visual-summary rows."""
    normalized_pitch_id = str(pitch_id or "").strip()
    if not normalized_pitch_id:
        raise ValueError("Choose a Yamazumi pitch.")

    with connection() as conn:
        project_row = conn.execute(
            "SELECT name FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        project_name = project_row["name"] if project_row else ""

        scenario = conn.execute(
            "SELECT id, name, takt_time_s, takt_time_unit, yamazumi_time_unit FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone()
        if not scenario:
            raise ValueError("The active planning scenario no longer exists in this project.")
        scenario_name = scenario["name"]
        scenario_takt_s = float(scenario["takt_time_s"] or 0)
        scenario_takt_unit = scenario["takt_time_unit"] or "seconds"

        pitch = conn.execute(
            """SELECT pitch.id, pitch.pitch_number, pitch.pitch_name, pitch.sequence,
                      area.id AS area_id, area.section_id, area.name AS area_name,
                      sec.name AS section_name
               FROM yamazumi_pitches pitch
               JOIN yamazumi_areas area
                 ON area.id=pitch.area_id AND area.project_id=pitch.project_id
               LEFT JOIN assembly_sections sec
                 ON sec.id=area.section_id AND sec.project_id=pitch.project_id
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
        aggregated_parts_map: dict[str, dict] = {}

        if work_ids:
            placeholders = ",".join("?" for _ in work_ids)
            part_rows = conn.execute(
                f"""SELECT group_row.work_element_id, option.handling_type,
                           group_row.quantity,
                           part.id AS part_id, part.part_number,
                           part.description AS part_description,
                           part.factory_nickname,
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
                h_type = part.pop("handling_type")
                handling_by_work[work_id].append(h_type)
                part.pop("work_element_id", None)
                parts_by_work[work_id].append(part)

                p_num = str(row["part_number"] or "").strip()
                if p_num:
                    qty = float(row["quantity"] or 1.0)
                    if p_num not in aggregated_parts_map:
                        aggregated_parts_map[p_num] = {
                            "part_id": str(row["part_id"]),
                            "part_number": p_num,
                            "description": row["part_description"] or "",
                            "factory_nickname": row["factory_nickname"] or "",
                            "image_path": row["image_path"] or "",
                            "quantity": qty,
                            "handling_types": {h_type} if h_type else set(),
                        }
                    else:
                        aggregated_parts_map[p_num]["quantity"] += qty
                        if h_type:
                            aggregated_parts_map[p_num]["handling_types"].add(h_type)

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

        # Equipment / Tools placed on pitch or linked to work elements
        tool_placeholders = ",".join("?" for _ in work_ids) if work_ids else "''"
        equipment_rows = conn.execute(
            f"""SELECT DISTINCT
                   asset.id AS equipment_id,
                   asset.name,
                   COALESCE(eq_type.label, '') AS type_name,
                   asset.manufacturer,
                   asset.model,
                   asset.description,
                   asset.notes,
                   asset.image_path,
                   placement.pitch_id
               FROM equipment_assets asset
               LEFT JOIN equipment_types eq_type ON eq_type.id=asset.equipment_type_id
               JOIN equipment_placements placement ON placement.equipment_id=asset.id AND placement.scenario_id=?
               LEFT JOIN equipment_process_links link ON link.placement_id=placement.id
               WHERE asset.project_id=?
                 AND (placement.pitch_id=? OR (link.work_element_id IN ({tool_placeholders})))
               ORDER BY asset.name COLLATE NOCASE""",
            (scenario_id, project_id, normalized_pitch_id, *work_ids) if work_ids else (scenario_id, project_id, normalized_pitch_id),
        ).fetchall()
        tools_list: list[dict] = []
        for eq in equipment_rows:
            tool_title = f"{eq['name']} ({eq['type_name']})" if eq["type_name"] else eq["name"]
            pieces = [p for p in [eq["manufacturer"], eq["model"], eq["description"]] if p]
            summary_line = f"{tool_title}: {' '.join(pieces)}" if pieces else tool_title
            is_ppe = any(k in f"{eq['name']} {eq['type_name']} {eq['description']}".upper() for k in ["PPE", "PROTECTIVE", "GLOVE", "GLASSES", "EARPLUG", "SHIELD"])
            tools_list.append({
                "equipment_id": str(eq["equipment_id"]),
                "name": eq["name"],
                "type_name": eq["type_name"],
                "manufacturer": eq["manufacturer"] or "",
                "model": eq["model"] or "",
                "description": eq["description"] or "",
                "notes": eq["notes"] or "",
                "image_path": eq["image_path"] or "",
                "is_ppe": is_ppe,
                "summary_line": summary_line,
            })

        if work_ids:
            we_tools = conn.execute(
                f"""SELECT DISTINCT tool FROM work_elements
                    WHERE id IN ({tool_placeholders}) AND tool IS NOT NULL AND TRIM(tool) != ''""",
                work_ids,
            ).fetchall()
            existing_names = {t["name"].casefold() for t in tools_list}
            for row in we_tools:
                tool_val = str(row["tool"]).strip()
                if tool_val and tool_val.casefold() not in existing_names:
                    tools_list.append({
                        "equipment_id": tool_val,
                        "name": tool_val,
                        "type_name": "Tool",
                        "manufacturer": "",
                        "model": "",
                        "description": "",
                        "notes": "",
                        "image_path": "",
                        "is_ppe": False,
                        "summary_line": tool_val,
                    })
                    existing_names.add(tool_val.casefold())

        # Mini Yamazumi pitch stack
        yamazumi_pitch_elements = conn.execute(
            """SELECT yamazumi.id, yamazumi.description, yamazumi.time_s, yamazumi.sequence,
                      yamazumi.model_variants, COALESCE(yamazumi.work_type, 'Cycle') AS work_type,
                      yamazumi.process_element_id
               FROM yamazumi_elements yamazumi
               WHERE yamazumi.project_id=? AND yamazumi.pitch_id=?
               ORDER BY yamazumi.sequence, yamazumi.id""",
            (project_id, normalized_pitch_id),
        ).fetchall()

        # Functional Alerts
        alerts: dict[str, list[dict]] = {
            "quality": [],
            "ergo": [],
            "safety": [],
            "materials": [],
            "equipment": [],
        }
        if work_ids:
            # Quality torque alerts
            for t_list in torque_by_work.values():
                for t in t_list:
                    uid = t.get("unique_identifier", "Torque")
                    val = t.get("target_value", "")
                    tol = t.get("tolerances", "")
                    unit = t.get("unit", "")
                    spec = " ".join(str(p) for p in [val, tol, unit] if p)
                    alerts["quality"].append({
                        "label": f"Torque: {uid} ({spec})",
                        "detail": f"Work Element Torque Specification: {uid} target {spec}",
                    })

            # PFMEA alerts
            pfmea_rows = conn.execute(
                f"""SELECT pfmea.potential_failure_mode, effect.severity, risk.rpn, work.operation
                    FROM pfmea_entries pfmea
                    JOIN work_elements work ON work.id=pfmea.work_element_id
                    LEFT JOIN pfmea_effects effect ON effect.pfmea_entry_id=pfmea.id
                    LEFT JOIN pfmea_risk_rows risk ON risk.pfmea_entry_id=pfmea.id
                    WHERE pfmea.project_id=? AND pfmea.scenario_id=?
                      AND pfmea.work_element_id IN ({placeholders})
                      AND (COALESCE(effect.severity, 0) >= 8 OR COALESCE(risk.rpn, 0) >= 100)""",
                (project_id, scenario_id, *work_ids),
            ).fetchall()
            for pfr in pfmea_rows:
                sev_text = f"Sev {int(pfr['severity'])}" if pfr['severity'] is not None else ""
                rpn_text = f"RPN {int(pfr['rpn'])}" if pfr['rpn'] is not None else ""
                score_str = ", ".join(p for p in [sev_text, rpn_text] if p)
                alerts["quality"].append({
                    "label": f"PFMEA: {pfr['potential_failure_mode']} ({score_str})" if score_str else f"PFMEA: {pfr['potential_failure_mode']}",
                    "detail": f"Step '{pfr['operation']}' has PFMEA Failure Mode '{pfr['potential_failure_mode']}' ({score_str})",
                })

            # Ergo alerts
            ergo_rows = conn.execute(
                f"""SELECT review.risk_classification, review.reviewer, review.notes, work.operation
                    FROM ergonomics_reviews review
                    JOIN work_elements work ON work.id=review.work_element_id
                    WHERE review.project_id=? AND review.scenario_id=?
                      AND review.work_element_id IN ({placeholders})
                      AND review.risk_classification IN ('Red', 'Favorable Red', 'Yellow')
                      AND review.status IN ('Open', 'Pending')""",
                (project_id, scenario_id, *work_ids),
            ).fetchall()
            for er in ergo_rows:
                alerts["ergo"].append({
                    "label": f"Ergo Risk ({er['risk_classification']}): {er['operation']}",
                    "detail": f"Ergonomics review marked as {er['risk_classification']}. Reviewer notes: {er['notes'] or 'None'}",
                })

            # Safety alerts
            safety_rows = conn.execute(
                f"""SELECT safety.requirement_description, work.operation
                    FROM safety_requirements safety
                    JOIN work_elements work ON work.id=safety.work_element_id
                    WHERE safety.project_id=? AND safety.scenario_id=?
                      AND safety.active=1
                      AND safety.work_element_id IN ({placeholders})""",
                (project_id, scenario_id, *work_ids),
            ).fetchall()
            for sr in safety_rows:
                alerts["safety"].append({
                    "label": f"Safety: {sr['requirement_description']}",
                    "detail": f"Safety requirement for step '{sr['operation']}': {sr['requirement_description']}",
                })

        # Materials alerts
        for p in aggregated_parts_map.values():
            if not p["handling_types"]:
                alerts["materials"].append({
                    "label": f"Part {p['part_number']}: Unclassified Handling",
                    "detail": f"Part {p['part_number']} ({p['description']}) is neither marked Consume nor Handle on this pitch.",
                })

        # Equipment alerts
        if not tools_list and work_ids:
            alerts["equipment"].append({
                "label": "No tools or equipment placed on pitch",
                "detail": "This pitch contains work elements but no equipment or tools are placed or linked.",
            })

    op_ids = work_element_op_ids(project_id, scenario_id, work_ids) if work_ids else {}
    risk_ids = process_ergonomics_risk_work_element_ids(project_id, scenario_id)
    card_motion_map: dict[str, tuple[str, str]] = {}
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
        card_motion_map[work_id] = (classification, color)
        card.update(
            op_id=op_ids.get(work_id, "Yamazumi link required"),
            parts=parts_by_work.get(work_id, []),
            motion_classification=classification,
            motion_color=color,
            ergonomics_risk=work_id in risk_ids,
            torque_requirements=torque_by_work.get(work_id, []),
        )

    # Build Mini Yamazumi Variant Stacks
    variant_stacks: dict[str, list[dict]] = {}
    for yel in yamazumi_pitch_elements:
        wid = str(yel["process_element_id"] or "")
        m_class, m_color = card_motion_map.get(wid, ("Unclassified", "gray"))
        variants = parse_yamazumi_model_variants(yel["model_variants"], fallback="Base")
        item_data = {
            "id": yel["id"],
            "description": yel["description"],
            "time_s": float(yel["time_s"] or 0),
            "sequence": yel["sequence"],
            "motion_classification": m_class,
            "motion_color": m_color,
            "work_type": yel["work_type"],
        }
        for v in variants:
            if v not in variant_stacks:
                variant_stacks[v] = []
            variant_stacks[v].append(item_data)
    if not variant_stacks:
        variant_stacks["Base"] = []

    # Aggregated parts list with sorted handling types
    final_parts: list[dict] = []
    for p in aggregated_parts_map.values():
        final_parts.append({
            **p,
            "handling_types": sorted(p["handling_types"]),
        })

    # Fetch and sequence visual media
    visual_media_items = get_pitch_visual_media(project_id, scenario_id, normalized_pitch_id)
    work_seq_map = {card["work_element_id"]: idx for idx, card in enumerate(cards)}
    def _media_sort_key(item: dict) -> tuple:
        tagged = item.get("tagged_work_element_ids", [])
        indices = [work_seq_map[wid] for wid in tagged if wid in work_seq_map]
        min_idx = min(indices) if indices else 999999
        return (min_idx, int(item.get("sequence", 10)), str(item.get("created_at", "")))
    sorted_visual_media = sorted(visual_media_items, key=_media_sort_key)
    slide_count = max(1, (len(sorted_visual_media) + 5) // 6)

    # Op ID range summary
    op_id_vals = [c.get("op_id") for c in cards if c.get("op_id") and c.get("op_id") != "Yamazumi link required"]
    op_id_summary = f"{op_id_vals[0]} – {op_id_vals[-1]}" if len(op_id_vals) > 1 else (op_id_vals[0] if op_id_vals else "N/A")

    return {
        **dict(pitch),
        "project_name": project_name,
        "scenario_name": scenario_name,
        "scenario_takt_s": scenario_takt_s,
        "scenario_takt_unit": scenario_takt_unit,
        "op_id_summary": op_id_summary,
        "elements": cards,
        "tools": tools_list,
        "parts": final_parts,
        "yamazumi_stacks": variant_stacks,
        "visual_media": sorted_visual_media,
        "alerts": alerts,
        "slide_count": slide_count,
    }


def update_work_element_tool_and_resource(
    project_id: str,
    scenario_id: str,
    work_element_id: str,
    tool: str = "",
    resource_type: str = "Human",
    resource_detail: str = "",
    editor_name: str = "",
) -> None:
    """Update tool, resource type, and resource detail on a work element."""
    timestamp = now_iso()
    with connection() as conn:
        conn.execute(
            """UPDATE work_elements
               SET tool=?, resource_type=?, resource_detail=?, updated_at=?
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (tool, resource_type, resource_detail, timestamp, work_element_id, project_id, scenario_id),
        )


def replace_work_elements(project_id: str, scenario_id: str, edited: pd.DataFrame) -> None:
    fields = [
        "sequence", "station", "operation", "description", "cycle_time_s", "part_number", "tool", "torque",
        "quality_requirement", "ergo_requirement", "location", "unit_orientation", "conveyor_height_in", "platform_height_in",
        "pit_depth_in", "model_applicability", "status", "output_assembly_number",
        "output_assembly_name", "resource_type", "resource_detail",
    ]
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
            protected_count = conn.execute(
                f"""SELECT COUNT(*) FROM pfmea_entries
                    WHERE project_id=? AND scenario_id=? AND work_element_id IN ({placeholders})""",
                (project_id, scenario_id, *removed),
            ).fetchone()[0]
            if protected_count:
                raise ValueError(
                    "Remove the linked PFMEA entries before deleting this Process at a Glance step."
                )
            conn.execute(
                f"""UPDATE yamazumi_elements
                    SET process_element_id=NULL, process_sync_status='Needs IE review', updated_at=?
                    WHERE project_id=? AND process_element_id IN ({placeholders})""",
                (now_iso(), project_id, *removed),
            )
            conn.execute(
                f"""DELETE FROM work_elements WHERE project_id=? AND scenario_id=?
                    AND id IN ({placeholders})""",
                (project_id, scenario_id, *removed),
            )

__domain_exports__ = ['_YAMAZUMI_PITCH_ADDRESS_PATTERN', '_normalize_handling_type', '_normalize_fishbone_assignment_id', '_process_part_assignment_consume_count', '_validate_process_part_option_handling', 'process_part_placement_options', 'validate_process_part_option_pairings', 'yamazumi_elements_for_section', 'yamazumi_context_for_process', 'process_element_id_for_yamazumi', 'process_part_groups', 'save_process_part_group', 'set_part_weight_lb', 'set_process_part_option_handling_type', 'work_element_criticality', 'delete_process_part_groups', 'delete_process_part_group', 'pin_map_for_scenario', 'reconcile_yamazumi_to_process', '_op_id_depth_letter', 'parse_yamazumi_pitch_address', 'work_element_op_contexts', 'work_element_op_ids', 'work_element_op_id', 'process_pitch_visual_summary', 'update_work_element_tool_and_resource', 'replace_work_elements', 'get_pitch_visual_media', 'save_pitch_visual_media', 'update_pitch_visual_media', 'delete_pitch_visual_media', 'MAX_VISUAL_IMAGE_BYTES', 'MAX_VISUAL_VIDEO_BYTES']
for _export_name in __domain_exports__:
    if callable(globals()[_export_name]):
        globals()[_export_name] = _db_core.domain_entrypoint(globals()[_export_name])
_db_core.register_domain_module(_sys.modules[__name__], __domain_exports__)
