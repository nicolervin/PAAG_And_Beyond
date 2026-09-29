"""Domain persistence extracted from the historical utils.store module."""

from __future__ import annotations

import sys as _sys
from utils import db_core as _db_core

globals().update({name: value for name, value in vars(_db_core).items() if not name.startswith('__')})

def projects() -> list[dict]:
    return query("SELECT * FROM projects ORDER BY updated_at DESC")

def get_project(project_id: str) -> dict | None:
    rows = query("SELECT * FROM projects WHERE id = ?", (project_id,))
    return rows[0] if rows else None

def planning_scenarios(project_id: str, include_archived: bool = False) -> list[dict]:
    archived_clause = "" if include_archived else "AND s.status <> 'Archived'"
    return query(
        f"""SELECT s.*, parent.name AS parent_name, parent.revision_label AS parent_revision_label
            FROM planning_scenarios s
            LEFT JOIN planning_scenarios parent ON parent.id=s.parent_scenario_id
            WHERE s.project_id=? {archived_clause}
            ORDER BY s.revision_sequence DESC, s.created_at DESC""",
        (project_id,),
    )

def get_planning_scenario(project_id: str, scenario_id: str) -> dict | None:
    rows = query(
        "SELECT * FROM planning_scenarios WHERE id=? AND project_id=?",
        (scenario_id, project_id),
    )
    return rows[0] if rows else None

def next_scenario_revision_label(project_id: str, current_label: str) -> str:
    """Suggest the next numeric or alphabetic label without using labels as identifiers."""
    label = str(current_label or "").strip()
    if label.isdigit():
        candidate = str(int(label) + 1)
    elif label.isalpha():
        number = 0
        for char in label.upper():
            number = number * 26 + (ord(char) - ord("A") + 1)
        number += 1
        letters: list[str] = []
        while number:
            number, remainder = divmod(number - 1, 26)
            letters.append(chr(ord("A") + remainder))
        candidate = "".join(reversed(letters))
    else:
        candidate = f"{label or 'Rev'}-2"
    used = {str(row["revision_label"]).casefold() for row in planning_scenarios(project_id, True)}
    base, suffix = candidate, 2
    while candidate.casefold() in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate

def update_planning_scenario(
    project_id: str,
    scenario_id: str,
    values: dict,
    *,
    _conn: sqlite3.Connection | None = None,
) -> None:
    name = str(values.get("name") or "").strip()
    revision_label = str(values.get("revision_label") or "").strip()
    status = str(values.get("status") or "Working").strip().title()
    if not name or not revision_label:
        raise ValueError("Scenario name and revision label are required.")
    if status not in {"Working", "Frozen", "Released", "Archived"}:
        raise ValueError("Choose a valid scenario status.")
    takt_unit = normalize_time_unit(values.get("takt_time_unit", "seconds"))
    try:
        takt = float(values.get("takt_time_s"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Scenario takt time must be a number.") from exc
    if takt <= 0:
        raise ValueError("Scenario takt time must be greater than zero.")
    try:
        context = nullcontext(_conn) if _conn is not None else connection()
        with context as conn:
            cursor = conn.execute(
                """UPDATE planning_scenarios
                   SET name=?, revision_label=?, status=?, takt_time_s=?, takt_time_unit=?,
                       change_summary=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (
                    name, revision_label, status, takt, takt_unit,
                    str(values.get("change_summary") or "").strip(), now_iso(),
                    scenario_id, project_id,
                ),
            )
            if not cursor.rowcount:
                raise ValueError("The planning scenario no longer exists.")
    except sqlite3.IntegrityError as exc:
        raise ValueError("Scenario names and revision labels must be unique within this project.") from exc

def update_yamazumi_time_unit(
    project_id: str, scenario_id: str, value: object
) -> dict[str, str]:
    """Save one scenario's Yamazumi presentation unit without rewriting times."""
    unit = normalize_time_unit(value)
    timestamp = now_iso()
    with connection() as conn:
        current = conn.execute(
            "SELECT yamazumi_time_unit FROM planning_scenarios "
            "WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone()
        if not current:
            raise ValueError("The active planning scenario no longer exists in this project.")
        previous = normalize_time_unit(current["yamazumi_time_unit"])
        conn.execute(
            "UPDATE planning_scenarios SET yamazumi_time_unit=?, updated_at=? "
            "WHERE id=? AND project_id=?",
            (unit, timestamp, scenario_id, project_id),
        )
    return {"old_unit": previous, "new_unit": unit, "updated_at": timestamp}

def clone_planning_scenario(
    project_id: str,
    source_scenario_id: str,
    name: str,
    revision_label: str,
    takt_time_s: float,
    change_summary: str = "",
    created_by: str = "",
    *,
    takt_time_unit: str | None = None,
    _conn: sqlite3.Connection | None = None,
) -> str:
    """Clone a complete balancing branch and preserve its internal lineage links."""
    name = str(name or "").strip()
    revision_label = str(revision_label or "").strip()
    if not name or not revision_label:
        raise ValueError("Scenario name and revision label are required.")
    try:
        takt = float(takt_time_s)
    except (TypeError, ValueError) as exc:
        raise ValueError("Scenario takt time must be a number.") from exc
    if takt <= 0:
        raise ValueError("Scenario takt time must be greater than zero.")

    new_scenario_id = str(uuid4())
    timestamp = now_iso()
    try:
        context = nullcontext(_conn) if _conn is not None else connection()
        with context as conn:
            source = conn.execute(
                "SELECT * FROM planning_scenarios WHERE id=? AND project_id=?",
                (source_scenario_id, project_id),
            ).fetchone()
            if not source:
                raise ValueError("The source scenario no longer exists.")
            _validate_yamazumi_scenario_pitch_addresses(
                conn, project_id, source_scenario_id
            )
            sequence = conn.execute(
                "SELECT COALESCE(MAX(revision_sequence), 0) + 1 FROM planning_scenarios WHERE project_id=?",
                (project_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, parent_scenario_id,
                    status, takt_time_s, takt_time_unit, yamazumi_time_unit,
                    change_summary, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'Working', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_scenario_id, project_id, name, revision_label, sequence,
                    source_scenario_id, takt,
                    normalize_time_unit(takt_time_unit or source["takt_time_unit"]),
                    normalize_time_unit(source["yamazumi_time_unit"]),
                    str(change_summary or "").strip(),
                    str(created_by or "").strip(), timestamp, timestamp,
                ),
            )
            conn.execute(
                """INSERT INTO part_scenario_activity
                   (project_id, scenario_id, part_id, active, updated_at)
                   SELECT project_id, ?, part_id, active, ?
                   FROM part_scenario_activity
                   WHERE project_id=? AND scenario_id=?""",
                (new_scenario_id, timestamp, project_id, source_scenario_id),
            )
            conn.execute(
                """INSERT INTO assembly_scenario_policies
                   (project_id, scenario_id, assembly_id, sourcing_decision, supplier,
                    build_area, buffer_policy, storage_location, minimum_quantity,
                    target_quantity, maximum_quantity, updated_at)
                   SELECT project_id, ?, assembly_id, sourcing_decision, supplier,
                          build_area, buffer_policy, storage_location, minimum_quantity,
                          target_quantity, maximum_quantity, ?
                   FROM assembly_scenario_policies
                   WHERE project_id=? AND scenario_id=?""",
                (new_scenario_id, timestamp, project_id, source_scenario_id),
            )

            process_id_map: dict[str, str] = {}
            for source_row in conn.execute(
                "SELECT * FROM work_elements WHERE project_id=? AND scenario_id=? ORDER BY sequence",
                (project_id, source_scenario_id),
            ).fetchall():
                row = dict(source_row)
                old_id, new_id = str(row["id"]), str(uuid4())
                process_id_map[old_id] = new_id
                _create_work_element_with_started_ergonomics_review(
                    conn,
                    project_id,
                    new_scenario_id,
                    {
                        column: value
                        for column, value in row.items()
                        if column not in {"id", "project_id", "scenario_id", "updated_at"}
                    },
                    timestamp,
                    work_element_id=new_id,
                )

            process_part_option_id_map: dict[str, str] = {}
            for source_group in conn.execute(
                """SELECT * FROM process_part_groups
                   WHERE project_id=? AND scenario_id=? ORDER BY name""",
                (project_id, source_scenario_id),
            ).fetchall():
                group = dict(source_group)
                old_group_id = str(group["id"])
                new_work_element_id = process_id_map.get(str(group["work_element_id"]))
                if not new_work_element_id:
                    continue
                new_group_id = str(uuid4())
                group.update(
                    id=new_group_id,
                    scenario_id=new_scenario_id,
                    work_element_id=new_work_element_id,
                    updated_at=timestamp,
                )
                columns = list(group)
                conn.execute(
                    f"INSERT INTO process_part_groups ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    tuple(group[column] for column in columns),
                )
                for source_option in conn.execute(
                    "SELECT * FROM process_part_options WHERE group_id=?", (old_group_id,)
                ).fetchall():
                    option = dict(source_option)
                    old_option_id = str(option["id"])
                    new_option_id = str(uuid4())
                    process_part_option_id_map[old_option_id] = new_option_id
                    option.update(id=new_option_id, group_id=new_group_id, updated_at=timestamp)
                    option_columns = list(option)
                    conn.execute(
                        f"INSERT INTO process_part_options ({', '.join(option_columns)}) VALUES ({', '.join('?' for _ in option_columns)})",
                        tuple(option[column] for column in option_columns),
                    )

            _clone_ergonomics_reviews(
                conn,
                project_id,
                source_scenario_id,
                new_scenario_id,
                process_id_map,
                process_part_option_id_map,
                timestamp,
            )

            for source_requirement in conn.execute(
                """SELECT * FROM safety_requirements
                   WHERE project_id=? AND scenario_id=?
                   ORDER BY created_at, id""",
                (project_id, source_scenario_id),
            ).fetchall():
                requirement = dict(source_requirement)
                new_work_element_id = process_id_map.get(
                    str(requirement["work_element_id"])
                )
                if not new_work_element_id:
                    raise ValueError(
                        "A Safety requirement Process Function could not be remapped "
                        "while cloning the scenario."
                    )
                requirement.update(
                    id=str(uuid4()),
                    scenario_id=new_scenario_id,
                    work_element_id=new_work_element_id,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                requirement_columns = list(requirement)
                conn.execute(
                    f"INSERT INTO safety_requirements "
                    f"({', '.join(requirement_columns)}) VALUES "
                    f"({', '.join('?' for _ in requirement_columns)})",
                    tuple(requirement[column] for column in requirement_columns),
                )

            quality_assignment_id_map: dict[str, str] = {}
            clone_quality_requirement_assignments(
                conn,
                project_id,
                source_scenario_id,
                new_scenario_id,
                process_id_map,
                timestamp,
                quality_assignment_id_map,
            )
            pfmea_entry_id_map: dict[str, str] = {}
            clone_pfmea_scenario(
                conn,
                project_id,
                source_scenario_id,
                new_scenario_id,
                process_id_map,
                quality_assignment_id_map,
                timestamp,
                pfmea_entry_id_map,
            )
            clone_control_plan_scenario(
                conn,
                project_id,
                source_scenario_id,
                new_scenario_id,
                pfmea_entry_id_map,
                quality_assignment_id_map,
                timestamp,
            )

            area_id_map: dict[str, str] = {}
            for source_row in conn.execute(
                "SELECT * FROM yamazumi_areas WHERE project_id=? AND scenario_id=? ORDER BY name",
                (project_id, source_scenario_id),
            ).fetchall():
                row = dict(source_row)
                old_id, new_id = str(row["id"]), str(uuid4())
                area_id_map[old_id] = new_id
                row.update(id=new_id, scenario_id=new_scenario_id, updated_at=timestamp)
                columns = list(row)
                conn.execute(
                    f"INSERT INTO yamazumi_areas ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    tuple(row[column] for column in columns),
                )

            pitch_id_map: dict[str, str] = {}
            pending_pitch_feeds: list[tuple[str, str, str | None]] = []
            yamazumi_element_id_map: dict[str, str] = {}
            for old_area_id, new_area_id in area_id_map.items():
                for source_row in conn.execute(
                    "SELECT * FROM yamazumi_pitches WHERE project_id=? AND area_id=? ORDER BY sequence",
                    (project_id, old_area_id),
                ).fetchall():
                    row = dict(source_row)
                    old_id, new_id = str(row["id"]), str(uuid4())
                    pitch_id_map[old_id] = new_id
                    old_feed_target_id = str(row.get("feeds_into_pitch_id") or "").strip() or None
                    row.update(
                        id=new_id,
                        area_id=new_area_id,
                        feeds_into_pitch_id=None,
                        updated_at=timestamp,
                    )
                    pending_pitch_feeds.append(
                        (new_id, new_area_id, old_feed_target_id)
                    )
                    columns = list(row)
                    conn.execute(
                        f"INSERT INTO yamazumi_pitches ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                        tuple(row[column] for column in columns),
                    )
                for source_row in conn.execute(
                    "SELECT * FROM yamazumi_work_regions WHERE project_id=? AND area_id=? ORDER BY sequence",
                    (project_id, old_area_id),
                ).fetchall():
                    row = dict(source_row)
                    row.update(id=str(uuid4()), area_id=new_area_id, updated_at=timestamp)
                    columns = list(row)
                    conn.execute(
                        f"INSERT INTO yamazumi_work_regions ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                        tuple(row[column] for column in columns),
                    )
                for source_row in conn.execute(
                    "SELECT * FROM yamazumi_elements WHERE project_id=? AND area_id=? ORDER BY sequence",
                    (project_id, old_area_id),
                ).fetchall():
                    row = dict(source_row)
                    old_element_id = str(row["id"])
                    new_element_id = str(uuid4())
                    yamazumi_element_id_map[old_element_id] = new_element_id
                    old_process_id = str(row.get("process_element_id") or "")
                    row.update(
                        id=new_element_id,
                        area_id=new_area_id,
                        pitch_id=pitch_id_map.get(str(row.get("pitch_id") or "")),
                        process_element_id=process_id_map.get(old_process_id),
                        updated_at=timestamp,
                    )
                    columns = list(row)
                    conn.execute(
                        f"INSERT INTO yamazumi_elements ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                        tuple(row[column] for column in columns),
                    )

            for new_pitch_id, new_area_id, old_feed_target_id in pending_pitch_feeds:
                new_feed_target_id = (
                    pitch_id_map.get(old_feed_target_id) if old_feed_target_id else None
                )
                if old_feed_target_id and not new_feed_target_id:
                    raise ValueError(
                        "A Yamazumi pitch feed target could not be remapped while cloning the scenario."
                    )
                conn.execute(
                    "UPDATE yamazumi_pitches SET feeds_into_pitch_id=? WHERE id=?",
                    (new_feed_target_id, new_pitch_id),
                )
            for new_area_id in area_id_map.values():
                _validate_yamazumi_pitch_feeds(conn, project_id, new_area_id)

            clone_equipment_scenario(
                conn,
                project_id,
                source_scenario_id,
                new_scenario_id,
                pitch_id_map,
                process_id_map,
                timestamp,
            )

            for source_group in conn.execute(
                """SELECT * FROM work_element_material_groups
                   WHERE project_id=? AND scenario_id=? ORDER BY name""",
                (project_id, source_scenario_id),
            ).fetchall():
                group = dict(source_group)
                old_group_id = str(group["id"])
                new_element_id = yamazumi_element_id_map.get(str(group["yamazumi_element_id"]))
                if not new_element_id:
                    continue
                new_group_id = str(uuid4())
                group.update(
                    id=new_group_id,
                    scenario_id=new_scenario_id,
                    yamazumi_element_id=new_element_id,
                    updated_at=timestamp,
                )
                columns = list(group)
                conn.execute(
                    f"INSERT INTO work_element_material_groups ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    tuple(group[column] for column in columns),
                )
                for source_option in conn.execute(
                    "SELECT * FROM work_element_material_options WHERE group_id=?",
                    (old_group_id,),
                ).fetchall():
                    option = dict(source_option)
                    option.update(id=str(uuid4()), group_id=new_group_id, updated_at=timestamp)
                    option_columns = list(option)
                    conn.execute(
                        f"INSERT INTO work_element_material_options ({', '.join(option_columns)}) VALUES ({', '.join('?' for _ in option_columns)})",
                        tuple(option[column] for column in option_columns),
                    )

            conn.execute(
                "UPDATE projects SET updated_at=? WHERE id=?", (timestamp, project_id)
            )
            conn.execute(
                """INSERT INTO audit_log
                   (id, project_id, table_name, action, row_count, editor_name, details, created_at)
                   VALUES (?, ?, 'Planning scenarios', 'Save as scenario', 1, ?, ?, ?)""",
                (
                    str(uuid4()), project_id, str(created_by or "").strip(),
                    json.dumps({"source_scenario_id": source_scenario_id, "new_scenario_id": new_scenario_id}),
                    timestamp,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Scenario names and revision labels must be unique within this project.") from exc
    return new_scenario_id

def save_planning_scenario_rows(
    project_id: str,
    source_scenario_id: str,
    records: list[dict],
    created_by: str = "",
) -> dict[str, object]:
    """Save the Overview scenario table and branch new rows from one source.

    Every row is validated before the first write. Existing scenario IDs update
    metadata in place; rows without an ID use the complete scenario-cloning
    workflow so their scenario-owned planning data is preserved.
    """
    existing = planning_scenarios(project_id, include_archived=True)
    existing_ids = {str(row["id"]) for row in existing}
    if source_scenario_id not in existing_ids:
        raise ValueError("The source scenario no longer exists.")

    cleaned: list[dict] = []
    names: set[str] = set()
    revisions: set[str] = set()
    valid_statuses = {"Working", "Frozen", "Released", "Archived"}
    for record in records:
        scenario_id = str(record.get("id") or "").strip()
        if scenario_id and scenario_id not in existing_ids:
            raise ValueError("One of the planning scenarios no longer exists. Refresh and try again.")
        name = str(record.get("name") or "").strip()
        revision_label = str(record.get("revision_label") or "").strip()
        status = str(record.get("status") or "Working").strip().title()
        if not name or not revision_label:
            raise ValueError("Scenario name and revision label are required in every row.")
        if status not in valid_statuses:
            raise ValueError("Choose a valid scenario status in every row.")
        takt_unit = normalize_time_unit(record.get("takt_time_unit", "seconds"))
        try:
            takt = float(record.get("takt_time_s"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Scenario takt time must be a number in every row.") from exc
        if takt <= 0:
            raise ValueError("Scenario takt time must be greater than zero in every row.")
        if name.casefold() in names:
            raise ValueError("Scenario names must be unique within this project.")
        if revision_label.casefold() in revisions:
            raise ValueError("Scenario revision labels must be unique within this project.")
        names.add(name.casefold())
        revisions.add(revision_label.casefold())
        cleaned.append(
            {
                "id": scenario_id,
                "name": name,
                "revision_label": revision_label,
                "status": status,
                "takt_time_s": takt,
                "takt_time_unit": takt_unit,
                "change_summary": str(record.get("change_summary") or "").strip(),
            }
        )

    updated_count = 0
    created_ids: list[str] = []
    with connection() as conn:
        for record in cleaned:
            if record["id"]:
                update_planning_scenario(
                    project_id, str(record["id"]), record, _conn=conn
                )
                updated_count += 1
                continue
            new_id = clone_planning_scenario(
                project_id,
                source_scenario_id,
                str(record["name"]),
                str(record["revision_label"]),
                float(record["takt_time_s"]),
                str(record["change_summary"]),
                created_by,
                takt_time_unit=str(record["takt_time_unit"]),
                _conn=conn,
            )
            if record["status"] != "Working":
                update_planning_scenario(project_id, new_id, record, _conn=conn)
            created_ids.append(new_id)

    return {
        "updated_count": updated_count,
        "created_ids": created_ids,
        "saved_count": len(cleaned),
    }

def create_project(
    name: str,
    program: str,
    owner: str,
    takt_time_s: float,
    product_line: str = "",
    takt_time_unit: str = "seconds",
) -> str:
    project_id, timestamp = str(uuid4()), now_iso()
    takt_unit = normalize_time_unit(takt_time_unit)
    execute(
        """INSERT INTO projects
           (id, name, program, product_line, owner, revision, status,
            takt_time_s, takt_time_unit, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'A', 'Draft', ?, ?, '', ?, ?)""",
        (
            project_id, name.strip(), program.strip(), product_line.strip(),
            owner.strip(), takt_time_s, takt_unit, timestamp, timestamp,
        ),
    )
    return project_id

def update_project_yamazumi_line_code(project_id: str, value: object) -> dict:
    """Save the project-wide line code used only for Yamazumi address suggestions."""
    code = normalize_yamazumi_line_code(value, allow_blank=True)
    timestamp = now_iso()
    with connection() as conn:
        current = conn.execute(
            "SELECT yamazumi_line_code FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if not current:
            raise ValueError("The active project no longer exists.")
        old_code = str(current["yamazumi_line_code"] or "")
        conn.execute(
            "UPDATE projects SET yamazumi_line_code=?, updated_at=? WHERE id=?",
            (code, timestamp, project_id),
        )
    return {
        "old_line_code": old_code,
        "new_line_code": code,
        "updated_at": timestamp,
    }

def update_project(project_id: str, values: dict) -> None:
    takt_unit = normalize_time_unit(values.get("takt_time_unit", "seconds"))
    values = {**values, "takt_time_unit": takt_unit}
    fields = [
        "name", "program", "product_line", "owner", "revision", "status",
        "takt_time_s", "takt_time_unit", "notes",
    ]
    execute(
        f"UPDATE projects SET {', '.join(f'{field} = ?' for field in fields)}, updated_at = ? WHERE id = ?",
        tuple(values.get(field, "") for field in fields) + (now_iso(), project_id),
    )

def replace_concerns(project_id: str, edited: pd.DataFrame) -> None:
    fields = ["category", "subject", "detail", "owner", "priority", "status", "related_part", "related_station"]
    with connection() as conn:
        conn.execute("DELETE FROM concerns WHERE project_id = ?", (project_id,))
        for _, row in edited.iterrows():
            if not str(row.get("subject", "")).strip():
                continue
            timestamp = now_iso()
            values = ["" if pd.isna(row.get(field, "")) else row.get(field, "") for field in fields]
            conn.execute(
                f"INSERT INTO concerns (id, project_id, {', '.join(fields)}, created_at, updated_at) VALUES ({', '.join(['?'] * (len(fields) + 4))})",
                (str(row.get("id")) if row.get("id") and not pd.isna(row.get("id")) else str(uuid4()), project_id, *values,
                 str(row.get("created_at")) if row.get("created_at") and not pd.isna(row.get("created_at")) else timestamp, timestamp),
            )

__domain_exports__ = ['projects', 'get_project', 'planning_scenarios', 'get_planning_scenario', 'next_scenario_revision_label', 'update_planning_scenario', 'update_yamazumi_time_unit', 'clone_planning_scenario', 'save_planning_scenario_rows', 'create_project', 'update_project_yamazumi_line_code', 'update_project', 'replace_concerns']
for _export_name in __domain_exports__:
    if callable(globals()[_export_name]):
        globals()[_export_name] = _db_core.domain_entrypoint(globals()[_export_name])
_db_core.register_domain_module(_sys.modules[__name__], __domain_exports__)
