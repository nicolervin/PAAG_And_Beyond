"""Domain persistence extracted from the historical utils.store module."""

from __future__ import annotations

import sys as _sys
from utils import db_core as _db_core

globals().update({name: value for name, value in vars(_db_core).items() if not name.startswith('__')})

@cached_store_read
def projects() -> list[dict]:
    return query("SELECT * FROM projects ORDER BY datetime(updated_at) DESC, updated_at DESC")

@cached_store_read
def get_project(project_id: str) -> dict | None:
    rows = query("SELECT * FROM projects WHERE id = ?", (project_id,))
    return rows[0] if rows else None

def _last_active_workspace_path() -> Path:
    db_path = Path(DB_PATH)
    return db_path.with_name(f"{db_path.name}-session")


def get_last_active_workspace() -> dict[str, str | None]:
    """Return the last active project_id and scenario_id for the current local database."""
    path = _last_active_workspace_path()
    if not path.is_file():
        return {"project_id": None, "scenario_id": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {"project_id": None, "scenario_id": None}
    if not isinstance(payload, dict):
        return {"project_id": None, "scenario_id": None}
    project_id = str(payload.get("project_id") or "").strip() or None
    scenario_id = str(payload.get("scenario_id") or "").strip() or None
    return {"project_id": project_id, "scenario_id": scenario_id}


def set_last_active_workspace(
    project_id: str | None,
    scenario_id: str | None = None,
) -> None:
    """Persist the last active project_id and scenario_id for the current local database."""
    path = _last_active_workspace_path()
    normalized_project_id = str(project_id or "").strip() or None
    normalized_scenario_id = (
        (str(scenario_id or "").strip() or None) if normalized_project_id else None
    )
    current = get_last_active_workspace()
    if (
        current.get("project_id") == normalized_project_id
        and current.get("scenario_id") == normalized_scenario_id
        and path.is_file()
    ):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "project_id": normalized_project_id,
                    "scenario_id": normalized_scenario_id,
                }
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


@cached_store_read
def planning_scenarios(project_id: str, include_archived: bool = False) -> list[dict]:
    archived_clause = "" if include_archived else "AND s.status <> 'Archived'"
    sql = f"""SELECT s.*, parent.name AS parent_name, parent.revision_label AS parent_revision_label
            FROM planning_scenarios s
            LEFT JOIN planning_scenarios parent ON parent.id=s.parent_scenario_id
            WHERE s.project_id=? {archived_clause}
            ORDER BY s.revision_sequence DESC, datetime(s.created_at) DESC, s.created_at DESC"""
    rows = query(sql, (project_id,))
    if not rows and project_id and is_cacheable_runtime():
        created_default = False
        with connection() as conn:
            has_any = conn.execute(
                "SELECT 1 FROM planning_scenarios WHERE project_id=? LIMIT 1",
                (project_id,),
            ).fetchone()
            if not has_any:
                proj = conn.execute(
                    "SELECT id, revision, takt_time_s, takt_time_unit, owner FROM projects WHERE id=?",
                    (project_id,),
                ).fetchone()
                if proj:
                    timestamp = now_iso()
                    conn.execute(
                        """INSERT INTO planning_scenarios
                           (id, project_id, name, revision_label, revision_sequence, status,
                            takt_time_s, takt_time_unit, change_summary, created_by,
                            created_at, updated_at)
                           VALUES (?, ?, 'Current plan', ?, 1, 'Working', ?, ?,
                                   'Migrated from the original project plan', ?, ?, ?)""",
                        (
                            str(uuid4()),
                            proj["id"],
                            str(proj["revision"] or "A"),
                            _safe_positive_float(proj["takt_time_s"], 60.0),
                            normalize_time_unit(proj["takt_time_unit"]),
                            str(proj["owner"] or ""),
                            timestamp,
                            timestamp,
                        ),
                    )
                    created_default = True
        if created_default:
            rows = query(sql, (project_id,))
    return rows

@cached_store_read
def get_planning_scenario(project_id: str, scenario_id: str) -> dict | None:
    rows = query(
        "SELECT * FROM planning_scenarios WHERE id=? AND project_id=?",
        (scenario_id, project_id),
    )
    return rows[0] if rows else None

@cached_store_read
def table_view_preference(
    project_id: str,
    editor_name: str,
    view_key: str,
) -> dict | None:
    """Return one project/editor table-layout preference with decoded columns."""
    normalized_view_key = str(view_key or "").strip()
    if not normalized_view_key:
        raise ValueError("A table view name is required.")
    rows = query(
        """SELECT id, project_id, editor_name, view_key,
                  visible_columns_json, column_order_json, created_at, updated_at
           FROM table_view_preferences
           WHERE project_id=? AND editor_name=? AND view_key=?""",
        (
            project_id,
            str(editor_name or "").strip(),
            normalized_view_key,
        ),
    )
    if not rows:
        return None
    result = dict(rows[0])
    try:
        result["visible_columns"] = json.loads(
            result.pop("visible_columns_json") or "[]"
        )
        result["column_order"] = json.loads(
            result.pop("column_order_json") or "[]"
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("The saved table view is invalid. Reset it to the default view.") from exc
    return result

def save_table_view_preference(
    project_id: str,
    editor_name: str,
    view_key: str,
    visible_columns: list[str],
    column_order: list[str],
    *,
    _conn: sqlite3.Connection | None = None,
) -> dict:
    """Validate and upsert one project/editor table layout."""
    normalized_view_key = str(view_key or "").strip()
    if not normalized_view_key:
        raise ValueError("A table view name is required.")
    normalized_visible = list(
        dict.fromkeys(
            str(column).strip()
            for column in (visible_columns or [])
            if str(column).strip()
        )
    )
    normalized_order = list(
        dict.fromkeys(
            str(column).strip()
            for column in (column_order or [])
            if str(column).strip()
        )
    )
    if not normalized_visible:
        raise ValueError("Show at least one column in the saved table view.")
    if set(normalized_visible) != set(normalized_order):
        raise ValueError("The visible columns and column order must contain the same columns.")

    normalized_editor = str(editor_name or "").strip()
    timestamp = now_iso()
    context = nullcontext(_conn) if _conn is not None else connection()
    with context as conn:
        if not conn.execute(
            "SELECT 1 FROM projects WHERE id=?", (project_id,)
        ).fetchone():
            raise ValueError("The active project no longer exists.")
        existing = conn.execute(
            """SELECT id, visible_columns_json, column_order_json
               FROM table_view_preferences
               WHERE project_id=? AND editor_name=? AND view_key=?""",
            (project_id, normalized_editor, normalized_view_key),
        ).fetchone()
        previous_visible = (
            json.loads(existing["visible_columns_json"] or "[]") if existing else []
        )
        previous_order = (
            json.loads(existing["column_order_json"] or "[]") if existing else []
        )
        preference_id = str(existing["id"]) if existing else str(uuid4())
        created_at = timestamp
        if existing:
            conn.execute(
                """UPDATE table_view_preferences
                   SET visible_columns_json=?, column_order_json=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (
                    json.dumps(normalized_visible),
                    json.dumps(normalized_order),
                    timestamp,
                    preference_id,
                    project_id,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO table_view_preferences
                   (id, project_id, editor_name, view_key, visible_columns_json,
                    column_order_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    preference_id,
                    project_id,
                    normalized_editor,
                    normalized_view_key,
                    json.dumps(normalized_visible),
                    json.dumps(normalized_order),
                    created_at,
                    timestamp,
                ),
            )
    return {
        "id": preference_id,
        "changed": (
            previous_visible != normalized_visible
            or previous_order != normalized_order
        ),
        "old_visible_columns": previous_visible,
        "old_column_order": previous_order,
        "visible_columns": normalized_visible,
        "column_order": normalized_order,
        "updated_at": timestamp,
    }

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
            source_part_groups = conn.execute(
                """SELECT * FROM process_part_groups
                   WHERE project_id=? AND scenario_id=? ORDER BY name""",
                (project_id, source_scenario_id),
            ).fetchall()
            options_by_group: dict[str, list[sqlite3.Row]] = {}
            if source_part_groups:
                group_ids = [str(g["id"]) for g in source_part_groups]
                placeholders = ",".join("?" for _ in group_ids)
                for source_option in conn.execute(
                    f"SELECT * FROM process_part_options WHERE group_id IN ({placeholders})",
                    tuple(group_ids),
                ).fetchall():
                    options_by_group.setdefault(str(source_option["group_id"]), []).append(source_option)
            for source_group in source_part_groups:
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
                for source_option in options_by_group.get(old_group_id, []):
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
            pitches_by_area: dict[str, list[sqlite3.Row]] = {}
            regions_by_area: dict[str, list[sqlite3.Row]] = {}
            elements_by_area: dict[str, list[sqlite3.Row]] = {}
            if area_id_map:
                old_area_ids = list(area_id_map.keys())
                area_placeholders = ",".join("?" for _ in old_area_ids)
                for r in conn.execute(
                    f"SELECT * FROM yamazumi_pitches WHERE project_id=? AND area_id IN ({area_placeholders}) ORDER BY sequence",
                    (project_id, *old_area_ids),
                ).fetchall():
                    pitches_by_area.setdefault(str(r["area_id"]), []).append(r)
                for r in conn.execute(
                    f"SELECT * FROM yamazumi_work_regions WHERE project_id=? AND area_id IN ({area_placeholders}) ORDER BY sequence",
                    (project_id, *old_area_ids),
                ).fetchall():
                    regions_by_area.setdefault(str(r["area_id"]), []).append(r)
                for r in conn.execute(
                    f"SELECT * FROM yamazumi_elements WHERE project_id=? AND area_id IN ({area_placeholders}) ORDER BY sequence",
                    (project_id, *old_area_ids),
                ).fetchall():
                    elements_by_area.setdefault(str(r["area_id"]), []).append(r)

            for old_area_id, new_area_id in area_id_map.items():
                for source_row in pitches_by_area.get(old_area_id, []):
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
                for source_row in regions_by_area.get(old_area_id, []):
                    row = dict(source_row)
                    row.update(id=str(uuid4()), area_id=new_area_id, updated_at=timestamp)
                    columns = list(row)
                    conn.execute(
                        f"INSERT INTO yamazumi_work_regions ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                        tuple(row[column] for column in columns),
                    )
                for source_row in elements_by_area.get(old_area_id, []):
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
            clone_process_visual_media_scenario(
                conn,
                project_id,
                source_scenario_id,
                new_scenario_id,
                pitch_id_map,
                process_id_map,
                timestamp,
            )

            source_mat_groups = conn.execute(
                """SELECT * FROM work_element_material_groups
                   WHERE project_id=? AND scenario_id=? ORDER BY name""",
                (project_id, source_scenario_id),
            ).fetchall()
            mat_options_by_group: dict[str, list[sqlite3.Row]] = {}
            if source_mat_groups:
                mat_group_ids = [str(g["id"]) for g in source_mat_groups]
                mat_placeholders = ",".join("?" for _ in mat_group_ids)
                for source_option in conn.execute(
                    f"SELECT * FROM work_element_material_options WHERE group_id IN ({mat_placeholders})",
                    tuple(mat_group_ids),
                ).fetchall():
                    mat_options_by_group.setdefault(str(source_option["group_id"]), []).append(source_option)
            for source_group in source_mat_groups:
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
                for source_option in mat_options_by_group.get(old_group_id, []):
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
    building_location: str = "",
) -> str:
    project_id, timestamp = str(uuid4()), now_iso()
    try:
        takt_time_s = float(takt_time_s)
    except (TypeError, ValueError) as exc:
        raise ValueError("Project takt time must be a number.") from exc
    if takt_time_s <= 0:
        raise ValueError("Project takt time must be greater than zero.")
    takt_unit = normalize_time_unit(takt_time_unit)
    execute(
        """INSERT INTO projects
           (id, name, program, product_line, building_location, owner, revision, status,
            takt_time_s, takt_time_unit, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 'A', 'Draft', ?, ?, '', ?, ?)""",
        (
            project_id, name.strip(), program.strip(), product_line.strip(),
            building_location.strip(),
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

def _optional_positive_real(value: object, label: str) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if math.isnan(parsed) or parsed <= 0:
        return None
    return parsed


def update_project(project_id: str, values: dict) -> None:
    existing = get_project(project_id) or {}
    takt_unit = normalize_time_unit(values.get("takt_time_unit", "seconds"))
    baseline_parts = _optional_positive_real(
        values["baseline_parts"] if "baseline_parts" in values else existing.get("baseline_parts"),
        "Baseline parts",
    )
    baseline_hpu = _optional_positive_real(
        values["baseline_hpu"] if "baseline_hpu" in values else existing.get("baseline_hpu"),
        "Baseline HPU",
    )
    baseline_cycle_time_s = _optional_positive_real(
        values["baseline_cycle_time_s"]
        if "baseline_cycle_time_s" in values
        else existing.get("baseline_cycle_time_s"),
        "Baseline cycle time",
    )
    values = {
        **values,
        "takt_time_unit": takt_unit,
        "baseline_parts": baseline_parts,
        "baseline_hpu": baseline_hpu,
        "baseline_cycle_time_s": baseline_cycle_time_s,
    }
    fields = [
        "name", "program", "product_line", "building_location", "owner", "revision", "status",
        "takt_time_s", "takt_time_unit", "baseline_parts", "baseline_hpu",
        "baseline_cycle_time_s", "notes",
    ]
    execute(
        f"UPDATE projects SET {', '.join(f'{field} = ?' for field in fields)}, updated_at = ? WHERE id = ?",
        tuple(
            values.get(field) if field.startswith("baseline_") else values.get(field, "")
            for field in fields
        ) + (now_iso(), project_id),
    )

def replace_concerns(project_id: str, edited: pd.DataFrame, editor_name: str = "") -> None:
    def _clean(row: pd.Series, key: str, default: str = "") -> str:
        val = row.get(key, default)
        if val is None or pd.isna(val):
            return default
        return str(val).strip()

    validated_rows: list[dict[str, str]] = []
    for _, row in edited.iterrows():
        detail_val = _clean(row, "detail") or _clean(row, "subject") or _clean(row, "title")
        comments_val = _clean(row, "comments")
        res_comments_val = _clean(row, "resolution_comments") or _clean(row, "resolution_notes")
        owner_val = _clean(row, "owner")
        if not detail_val and not comments_val and not res_comments_val and not owner_val:
            continue
        if not detail_val:
            raise ValueError("Description is required for every question or concern.")

        status_val = _clean(row, "status", "Open") or "Open"
        if status_val == "Closed":
            status_val = "Resolved"
        if status_val not in CONCERN_STATUSES:
            raise ValueError(
                f"Invalid status '{status_val}'. Allowed statuses: {', '.join(CONCERN_STATUSES)}."
            )
        if status_val == "Resolved" and not res_comments_val:
            raise ValueError(
                f"Resolution comments are required when Status is set to 'Resolved' (Description: {detail_val[:60]})."
            )

        category_val = _clean(row, "category", "Other") or "Other"
        if category_val not in CONCERN_CATEGORIES:
            category_val = "Other"
        priority_val = _clean(row, "priority", "Medium") or "Medium"

        validated_rows.append(
            {
                "id": _clean(row, "id"),
                "category": category_val,
                "subject": _clean(row, "subject") if "subject" in edited.columns else "",
                "detail": detail_val,
                "owner": owner_val,
                "priority": priority_val,
                "status": status_val,
                "comments": comments_val,
                "resolution_comments": res_comments_val,
                "submitted_by": _clean(row, "submitted_by"),
                "related_part": _clean(row, "related_part") if "related_part" in edited.columns else "",
                "related_station": _clean(row, "related_station") if "related_station" in edited.columns else "",
                "created_at": _clean(row, "created_at"),
                "updated_at": _clean(row, "updated_at"),
            }
        )

    fields = [
        "category",
        "subject",
        "detail",
        "owner",
        "priority",
        "status",
        "comments",
        "resolution_comments",
        "submitted_by",
        "related_part",
        "related_station",
    ]
    with connection() as conn:
        from utils.recycle_bin_store import capture_deletion_to_recycle_bin

        existing_concerns = conn.execute(
            "SELECT * FROM concerns WHERE project_id = ?", (project_id,)
        ).fetchall()
        existing_by_id = {str(r["id"]): dict(r) for r in existing_concerns}
        kept_ids = {
            r["id"]
            for r in validated_rows
            if r["id"] and r["id"] in existing_by_id
        }
        for c_row in existing_concerns:
            c_id = str(c_row["id"])
            if c_id not in kept_ids:
                label = str(c_row["detail"] or c_row["subject"] or c_id)
                with capture_deletion_to_recycle_bin(
                    conn,
                    project_id=project_id,
                    entity_type="Concern",
                    entity_table="concerns",
                    entity_id=c_id,
                    entity_label=label,
                    deleted_by=editor_name,
                ):
                    conn.execute(
                        "DELETE FROM concerns WHERE id = ? AND project_id = ?",
                        (c_id, project_id),
                    )
        conn.execute("DELETE FROM concerns WHERE project_id = ?", (project_id,))
        timestamp = now_iso()
        for r in validated_rows:
            row_id = r["id"]
            if row_id and row_id in existing_by_id:
                prev = existing_by_id[row_id]
                submitted_by_val = (
                    r["submitted_by"]
                    or str(prev.get("submitted_by") or "").strip()
                    or str(editor_name or "").strip()
                )
                related_part_val = (
                    r["related_part"]
                    if "related_part" in edited.columns
                    else str(prev.get("related_part") or "")
                )
                related_station_val = (
                    r["related_station"]
                    if "related_station" in edited.columns
                    else str(prev.get("related_station") or "")
                )
                subject_val = (
                    r["subject"]
                    if ("subject" in edited.columns and r["subject"])
                    else r["detail"]
                )
                created_at_val = r["created_at"] or str(prev.get("created_at") or timestamp)
                prev_comparable = (
                    str(prev.get("category") or ""),
                    str(prev.get("detail") or prev.get("subject") or ""),
                    str(prev.get("owner") or ""),
                    str(prev.get("priority") or ""),
                    str(prev.get("status") or ""),
                    str(prev.get("comments") or ""),
                    str(prev.get("resolution_comments") or ""),
                    str(prev.get("submitted_by") or "").strip() or submitted_by_val,
                )
                curr_comparable = (
                    r["category"],
                    r["detail"],
                    r["owner"],
                    r["priority"],
                    r["status"],
                    r["comments"],
                    r["resolution_comments"],
                    submitted_by_val,
                )
                updated_at_val = (
                    timestamp
                    if curr_comparable != prev_comparable
                    else str(prev.get("updated_at") or timestamp)
                )
            else:
                row_id = row_id or str(uuid4())
                submitted_by_val = r["submitted_by"] or str(editor_name or "").strip()
                related_part_val = r["related_part"]
                related_station_val = r["related_station"]
                subject_val = r["subject"] or r["detail"]
                created_at_val = r["created_at"] or timestamp
                updated_at_val = timestamp

            values = [
                r["category"],
                subject_val,
                r["detail"],
                r["owner"],
                r["priority"],
                r["status"],
                r["comments"],
                r["resolution_comments"],
                submitted_by_val,
                related_part_val,
                related_station_val,
            ]
            conn.execute(
                f"INSERT INTO concerns (id, project_id, {', '.join(fields)}, created_at, updated_at) VALUES ({', '.join(['?'] * (len(fields) + 4))})",
                (row_id, project_id, *values, created_at_val, updated_at_val),
            )


def _legacy_replace_concerns_unused(project_id: str, edited: pd.DataFrame) -> None:
    fields = ["category", "subject", "detail", "owner", "priority", "status", "related_part", "related_station"]
    with connection() as conn:
        from utils.recycle_bin_store import capture_deletion_to_recycle_bin
        existing_concerns = conn.execute(
            "SELECT id, subject FROM concerns WHERE project_id = ?", (project_id,)
        ).fetchall()
        kept_ids = {
            str(row.get("id")).strip()
            for _, row in edited.iterrows()
            if str(row.get("subject", "")).strip()
            and row.get("id")
            and not pd.isna(row.get("id"))
        }
        for c_row in existing_concerns:
            c_id = str(c_row["id"])
            if c_id not in kept_ids:
                with capture_deletion_to_recycle_bin(
                    conn,
                    project_id=project_id,
                    entity_type="Concern",
                    entity_table="concerns",
                    entity_id=c_id,
                    entity_label=str(c_row["subject"] or c_id),
                ):
                    conn.execute(
                        "DELETE FROM concerns WHERE id = ? AND project_id = ?",
                        (c_id, project_id),
                    )
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

def get_project_deletion_impact(project_id: str) -> dict[str, int]:
    """Return counts of major entities and files belonging to the project for deletion disclosure."""
    from utils.project_transfer import _registered_rows, _upload_manifest
    with connection() as conn:
        counts = {}
        for entity, tbl in [
            ("scenarios", "planning_scenarios"),
            ("parts", "parts"),
            ("sections", "assembly_sections"),
            ("pitches", "yamazumi_pitches"),
            ("work_elements", "work_elements"),
            ("concerns", "concerns"),
        ]:
            counts[entity] = conn.execute(
                f"SELECT COUNT(*) FROM {tbl} WHERE project_id=?", (project_id,)
            ).fetchone()[0]
        try:
            tables, _ = _registered_rows(conn, project_id)
            uploads = _upload_manifest(tables)
            counts["uploads"] = len(uploads)
        except Exception:
            counts["uploads"] = 0
        return counts

def delete_project(project_id: str, editor_name: str = "") -> dict[str, Any]:
    """Permanently delete a project and all associated database records and uploads."""
    from pathlib import Path
    from utils.project_transfer import _registered_rows, _upload_manifest
    with connection() as conn:
        target = conn.execute(
            "SELECT id, name FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if target is None:
            raise ValueError("The project to delete no longer exists.")
        project_name = str(target["name"] or "")

        tables, record_counts = _registered_rows(conn, project_id)
        uploads = _upload_manifest(tables)

        from utils.recycle_bin_store import capture_deletion_to_recycle_bin
        with capture_deletion_to_recycle_bin(
            conn,
            project_id=project_id,
            entity_type="Project",
            entity_table="projects",
            entity_id=project_id,
            entity_label=project_name,
            deleted_by=editor_name,
            extra_file_paths=[
                str(u.get("database_path") or u.get("source_path") or "")
                for u in uploads
            ],
        ):
            conn.execute("DELETE FROM projects WHERE id=?", (project_id,))

    deleted_files_count = 0
    for upload in uploads:
        file_path = upload.get("source_path")
        if file_path and isinstance(file_path, Path) and file_path.is_file():
            try:
                from utils.recycle_bin_store import safe_unlink_upload_path
                if safe_unlink_upload_path(file_path):
                    deleted_files_count += 1
            except OSError:
                pass

    return {
        "project_id": project_id,
        "project_name": project_name,
        "record_counts": record_counts,
        "deleted_files_count": deleted_files_count,
    }

__domain_exports__ = ['projects', 'get_project', 'get_last_active_workspace', 'set_last_active_workspace', 'planning_scenarios', 'get_planning_scenario', 'table_view_preference', 'save_table_view_preference', 'next_scenario_revision_label', 'update_planning_scenario', 'update_yamazumi_time_unit', 'clone_planning_scenario', 'save_planning_scenario_rows', 'create_project', 'update_project_yamazumi_line_code', 'update_project', 'replace_concerns', 'get_project_deletion_impact', 'delete_project']
for _export_name in __domain_exports__:
    if callable(globals()[_export_name]):
        globals()[_export_name] = _db_core.domain_entrypoint(globals()[_export_name])
_db_core.register_domain_module(_sys.modules[__name__], __domain_exports__)
