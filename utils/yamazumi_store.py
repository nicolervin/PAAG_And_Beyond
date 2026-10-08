"""Domain persistence extracted from the historical utils.store module."""

from __future__ import annotations

import sys as _sys
from utils import db_core as _db_core

globals().update({name: value for name, value in vars(_db_core).items() if not name.startswith('__')})

def yamazumi_areas(project_id: str, scenario_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT a.*, s.name AS section_name
           FROM yamazumi_areas a LEFT JOIN assembly_sections s ON s.id=a.section_id
           WHERE a.project_id=? AND a.scenario_id=? ORDER BY a.name""",
        (project_id, scenario_id),
    ))

def yamazumi_area_link_status(project_id: str, scenario_id: str) -> dict[str, int | bool]:
    """Report active Fishbone-section gaps and existing one-to-one link conflicts."""
    sections = query(
        """SELECT id, name, section_type FROM assembly_sections
           WHERE project_id=? AND active=1
           ORDER BY sequence, name""",
        (project_id,),
    )
    areas = query(
        """SELECT id, name, section_id FROM yamazumi_areas
           WHERE project_id=? AND scenario_id=? ORDER BY name, id""",
        (project_id, scenario_id),
    )
    link_counts: dict[str, int] = {}
    for area in areas:
        section_id = str(area.get("section_id") or "").strip()
        if section_id:
            link_counts[section_id] = link_counts.get(section_id, 0) + 1
    missing = sum(1 for section in sections if link_counts.get(str(section["id"]), 0) == 0)
    conflicting = sum(max(0, count - 1) for count in link_counts.values())
    section_by_name = {str(section["name"]).casefold(): str(section["id"]) for section in sections}
    mislinked = sum(
        1
        for area in areas
        if str(area["name"]).casefold() in section_by_name
        and str(area.get("section_id") or "") != section_by_name[str(area["name"]).casefold()]
    )
    return {
        "active_sections": len(sections),
        "missing": missing,
        "mislinked": mislinked,
        "conflicting": conflicting,
        "needs_sync": bool(missing or mislinked or conflicting),
    }

def yamazumi_pitches(project_id: str, area_id: str) -> pd.DataFrame:
    rows = pd.DataFrame(query(
        """SELECT * FROM yamazumi_pitches WHERE project_id=? AND area_id=?
           ORDER BY sequence, pitch_number""",
        (project_id, area_id),
    ))
    if rows.empty:
        return pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "pitch_number": pd.Series(dtype="string"),
            "pitch_name": pd.Series(dtype="string"),
            "status": pd.Series(dtype="string"),
            "sequence": pd.Series(dtype="Int64"),
            "model_variants": pd.Series(dtype="string"),
            "pitch_type": pd.Series(dtype="string"),
            "feeds_into_pitch_id": pd.Series(dtype="string"),
            "updated_at": pd.Series(dtype="string"),
        })
    return rows

def yamazumi_elements(project_id: str, area_id: str) -> pd.DataFrame:
    rows = pd.DataFrame(query(
        """SELECT e.*, p.pitch_number, p.pitch_name, p.status AS pitch_status
           FROM yamazumi_elements e LEFT JOIN yamazumi_pitches p ON p.id=e.pitch_id
           WHERE e.project_id=? AND e.area_id=?
           ORDER BY COALESCE(p.sequence, 999999), e.model_variant, e.sequence, e.description""",
        (project_id, area_id),
    ))
    if rows.empty:
        return pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "pitch_id": pd.Series(dtype="string"),
            "model_variant": pd.Series(dtype="string"),
            "model_variants": pd.Series(dtype="string"),
            "work_type": pd.Series(dtype="string"),
            "description": pd.Series(dtype="string"),
            "time_s": pd.Series(dtype="Float64"),
            "work_region": pd.Series(dtype="string"),
            "sequence": pd.Series(dtype="Int64"),
            "source": pd.Series(dtype="string"),
            "process_element_id": pd.Series(dtype="string"),
            "process_sync_status": pd.Series(dtype="string"),
            "updated_at": pd.Series(dtype="string"),
            "pitch_number": pd.Series(dtype="string"),
            "pitch_name": pd.Series(dtype="string"),
            "pitch_status": pd.Series(dtype="string"),
        })
    return rows

def yamazumi_pitches_for_scenario(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Load pitch addresses across every Yamazumi area in one scenario."""
    rows = pd.DataFrame(query(
        """SELECT p.*, a.name AS area_name, a.section_id, s.name AS section_name
           FROM yamazumi_pitches p
           JOIN yamazumi_areas a ON a.id=p.area_id
           LEFT JOIN assembly_sections s ON s.id=a.section_id
           WHERE p.project_id=? AND a.scenario_id=?
           ORDER BY a.name, p.sequence, p.pitch_number""",
        (project_id, scenario_id),
    ))
    if rows.empty:
        return pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "pitch_number": pd.Series(dtype="string"),
            "pitch_name": pd.Series(dtype="string"),
            "status": pd.Series(dtype="string"),
            "sequence": pd.Series(dtype="Int64"),
            "model_variants": pd.Series(dtype="string"),
            "pitch_type": pd.Series(dtype="string"),
            "feeds_into_pitch_id": pd.Series(dtype="string"),
            "updated_at": pd.Series(dtype="string"),
            "area_name": pd.Series(dtype="string"),
            "section_id": pd.Series(dtype="string"),
            "section_name": pd.Series(dtype="string"),
        })
    return rows


def yamazumi_elements_for_scenario(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Load work elements across every Yamazumi area in one scenario."""
    rows = pd.DataFrame(query(
        """SELECT e.*, p.pitch_number, p.pitch_name, p.status AS pitch_status,
                  a.name AS area_name
           FROM yamazumi_elements e
           JOIN yamazumi_areas a ON a.id=e.area_id
           LEFT JOIN yamazumi_pitches p ON p.id=e.pitch_id
           WHERE e.project_id=? AND a.scenario_id=?
           ORDER BY a.name, COALESCE(p.sequence, 999999),
                    e.model_variant, e.sequence, e.description""",
        (project_id, scenario_id),
    ))
    if rows.empty:
        return pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "pitch_id": pd.Series(dtype="string"),
            "model_variant": pd.Series(dtype="string"),
            "model_variants": pd.Series(dtype="string"),
            "work_type": pd.Series(dtype="string"),
            "description": pd.Series(dtype="string"),
            "time_s": pd.Series(dtype="Float64"),
            "work_region": pd.Series(dtype="string"),
            "sequence": pd.Series(dtype="Int64"),
            "source": pd.Series(dtype="string"),
            "process_element_id": pd.Series(dtype="string"),
            "process_sync_status": pd.Series(dtype="string"),
            "updated_at": pd.Series(dtype="string"),
            "pitch_number": pd.Series(dtype="string"),
            "pitch_name": pd.Series(dtype="string"),
            "pitch_status": pd.Series(dtype="string"),
            "area_name": pd.Series(dtype="string"),
        })
    return rows

def yamazumi_work_regions(project_id: str, area_id: str) -> pd.DataFrame:
    rows = pd.DataFrame(query(
        """SELECT * FROM yamazumi_work_regions
           WHERE project_id=? AND area_id=? ORDER BY sequence, name""",
        (project_id, area_id),
    ))
    if rows.empty:
        return pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "name": pd.Series(dtype="string"),
            "description": pd.Series(dtype="string"),
            "active": pd.Series(dtype="bool"),
            "color": pd.Series(dtype="string"),
            "sequence": pd.Series(dtype="int64"),
            "updated_at": pd.Series(dtype="string"),
        })
    if "name" in rows.columns:
        rows["name"] = rows["name"].map(lambda value: "" if pd.isna(value) else str(value))
    if "description" in rows.columns:
        rows["description"] = rows["description"].map(lambda value: "" if pd.isna(value) else str(value))
    return rows

def replace_yamazumi_work_regions(project_id: str, area_id: str, records: list[dict]) -> int:
    """Replace area-specific work-region definitions."""
    import re

    cleaned: list[dict] = []
    seen: set[str] = set()
    for index, record in enumerate(records, start=1):
        name = str(record.get("name") or "").strip()
        if not name:
            continue
        if name.casefold() == "none":
            raise ValueError("None is reserved for elements without a work-region highlight.")
        if name.casefold() in seen:
            raise ValueError("Work-region names must be unique.")
        seen.add(name.casefold())
        raw_color = record.get("color")
        color = (
            "#35c84a"
            if raw_color is None or pd.isna(raw_color) or not str(raw_color).strip()
            else str(raw_color).strip().lower()
        )
        if not re.fullmatch(r"#[0-9a-f]{6}", color):
            raise ValueError(f"Choose a valid color for {name}.")
        cleaned.append({
            "id": str(record.get("id") or "").strip() or str(uuid4()),
            "name": name,
            "description": str(record.get("description") or "").strip(),
            "active": int(
                True
                if record.get("active") is None or pd.isna(record.get("active"))
                else bool(record.get("active"))
            ),
            "color": color,
            "sequence": (
                index * 10
                if record.get("sequence") is None or pd.isna(record.get("sequence"))
                else int(record.get("sequence"))
            ),
        })
    timestamp = now_iso()
    with connection() as conn:
        valid_area = conn.execute(
            "SELECT 1 FROM yamazumi_areas WHERE id=? AND project_id=?", (area_id, project_id)
        ).fetchone()
        if not valid_area:
            raise ValueError("That Yamazumi area no longer exists.")
        existing = {
            str(row["id"]): str(row["name"])
            for row in conn.execute(
                "SELECT id, name FROM yamazumi_work_regions WHERE project_id=? AND area_id=?",
                (project_id, area_id),
            ).fetchall()
        }
        kept = {record["id"] for record in cleaned}
        removed_names = [name for region_id, name in existing.items() if region_id not in kept]
        if removed_names:
            placeholders = ",".join("?" for _ in removed_names)
            conn.execute(
                f"""UPDATE yamazumi_elements
                    SET work_region='None', process_sync_status='Needs IE review', updated_at=?
                    WHERE project_id=? AND area_id=? AND work_region IN ({placeholders})""",
                (timestamp, project_id, area_id, *removed_names),
            )
        for record in cleaned:
            old_name = existing.get(record["id"])
            if old_name and old_name != record["name"]:
                conn.execute(
                    """UPDATE yamazumi_elements SET work_region=?, updated_at=?
                       WHERE project_id=? AND area_id=? AND work_region=?""",
                    (record["name"], timestamp, project_id, area_id, old_name),
                )
        for record in cleaned:
            conn.execute(
                """INSERT INTO yamazumi_work_regions
                   (id, project_id, area_id, name, description, active, color, sequence, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                   description=excluded.description, active=excluded.active,
                   color=excluded.color, sequence=excluded.sequence, updated_at=excluded.updated_at""",
                (
                    record["id"], project_id, area_id, record["name"], record["description"],
                    record["active"], record["color"], record["sequence"], timestamp,
                ),
            )
        removed_ids = set(existing) - kept
        if removed_ids:
            placeholders = ",".join("?" for _ in removed_ids)
            conn.execute(f"DELETE FROM yamazumi_work_regions WHERE id IN ({placeholders})", tuple(removed_ids))
    return len(cleaned)

def migrate_legacy_yamazumi_flags(project_id: str, editor_name: str) -> dict:
    """Discard retired Yamazumi flags once per project and retire their schema."""
    timestamp = now_iso()
    editor = str(editor_name or "").strip()
    with connection() as conn:
        table_exists = conn.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name='yamazumi_flag_definitions'"""
        ).fetchone() is not None
        element_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(yamazumi_elements)")
        }
        has_flags_column = "flags" in element_columns
        definition_count = (
            int(conn.execute(
                "SELECT COUNT(*) FROM yamazumi_flag_definitions WHERE project_id=?",
                (project_id,),
            ).fetchone()[0])
            if table_exists else 0
        )
        affected_element_count = (
            int(conn.execute(
                """SELECT COUNT(*) FROM yamazumi_elements
                   WHERE project_id=? AND COALESCE(TRIM(flags), '') NOT IN ('', '[]')""",
                (project_id,),
            ).fetchone()[0])
            if has_flags_column else 0
        )
        if (definition_count or affected_element_count) and not editor:
            raise ValueError(
                "Enter the Current editor to retire legacy Yamazumi flags for this project."
            )
        if has_flags_column and affected_element_count:
            conn.execute(
                "UPDATE yamazumi_elements SET flags='[]' WHERE project_id=?",
                (project_id,),
            )
        if table_exists and definition_count:
            conn.execute(
                "DELETE FROM yamazumi_flag_definitions WHERE project_id=?",
                (project_id,),
            )
        if definition_count or affected_element_count:
            record_audit_event(
                project_id,
                "Yamazumi",
                "Retire legacy flags",
                affected_element_count,
                editor,
                {
                    "definition_count": definition_count,
                    "affected_element_count": affected_element_count,
                    "updated_at": timestamp,
                },
                _conn=conn,
            )

        remaining_definitions = (
            int(conn.execute(
                "SELECT COUNT(*) FROM yamazumi_flag_definitions"
            ).fetchone()[0])
            if table_exists else 0
        )
        remaining_flag_values = (
            int(conn.execute(
                """SELECT COUNT(*) FROM yamazumi_elements
                   WHERE COALESCE(TRIM(flags), '') NOT IN ('', '[]')"""
            ).fetchone()[0])
            if has_flags_column else 0
        )
        if not remaining_definitions and not remaining_flag_values:
            if table_exists:
                conn.execute("DROP TABLE yamazumi_flag_definitions")
            if has_flags_column:
                conn.execute("ALTER TABLE yamazumi_elements DROP COLUMN flags")
    return {
        "definition_count": definition_count,
        "affected_element_count": affected_element_count,
        "timestamp": timestamp,
    }

def rename_yamazumi_variants(
    project_id: str, scenario_id: str, label_mapping: dict[str, str]
) -> dict[str, object]:
    """Normalize saved Yamazumi labels and describe every persisted change."""
    mapping = {str(old): str(new) for old, new in label_mapping.items() if str(old) != str(new)}
    if not mapping:
        return {"changed_count": 0, "element_changes": [], "pitch_changes": []}
    element_changes: list[dict[str, object]] = []
    pitch_changes: list[dict[str, object]] = []
    timestamp = now_iso()
    with connection() as conn:
        elements = conn.execute(
            """SELECT e.id, e.model_variant, e.model_variants FROM yamazumi_elements e
               JOIN yamazumi_areas a ON a.id=e.area_id
               WHERE e.project_id=? AND a.scenario_id=?""", (project_id, scenario_id)
        ).fetchall()
        for element in elements:
            variants = parse_yamazumi_model_variants(
                element["model_variants"], str(element["model_variant"] or "Base")
            )
            normalized = list(dict.fromkeys(mapping.get(value, value) for value in variants))
            primary_variant = normalized[0]
            if normalized != variants or primary_variant != str(element["model_variant"]):
                conn.execute(
                    """UPDATE yamazumi_elements
                       SET model_variant=?, model_variants=?, updated_at=? WHERE id=?""",
                    (primary_variant, json.dumps(normalized), timestamp, element["id"]),
                )
                element_changes.append(
                    {
                        "element_id": str(element["id"]),
                        "old_primary_variant": str(element["model_variant"] or "Base"),
                        "new_primary_variant": primary_variant,
                        "old_variants": variants,
                        "new_variants": normalized,
                    }
                )
        pitches = conn.execute(
            """SELECT p.id, p.area_id, p.pitch_number, p.pitch_name, p.pitch_type,
                      p.feeds_into_pitch_id, p.model_variants
               FROM yamazumi_pitches p
               JOIN yamazumi_areas a ON a.id=p.area_id
               WHERE p.project_id=? AND a.scenario_id=?""", (project_id, scenario_id)
        ).fetchall()
        for pitch in pitches:
            variants = json.loads(pitch["model_variants"] or "[]")
            normalized = list(dict.fromkeys(mapping.get(str(value), str(value)) for value in variants))
            if normalized != variants:
                _require_yamazumi_feed_target_for_pitch_write(
                    conn, project_id, pitch
                )
                conn.execute(
                    "UPDATE yamazumi_pitches SET model_variants=?, updated_at=? WHERE id=?",
                    (json.dumps(normalized), timestamp, pitch["id"]),
                )
                pitch_changes.append(
                    {
                        "pitch_id": str(pitch["id"]),
                        "old_variants": variants,
                        "new_variants": normalized,
                    }
                )
    return {
        "changed_count": len(element_changes) + len(pitch_changes),
        "element_changes": element_changes,
        "pitch_changes": pitch_changes,
    }

def clear_yamazumi_data(project_id: str, scenario_id: str, area_id: str | None = None) -> dict[str, int]:
    """Delete Yamazumi-only areas, pitches, and work without changing Fishbone or Process Plan."""
    with connection() as conn:
        if area_id:
            area = conn.execute(
                "SELECT id FROM yamazumi_areas WHERE id=? AND project_id=? AND scenario_id=?",
                (area_id, project_id, scenario_id),
            ).fetchone()
            if not area:
                raise ValueError("That Yamazumi area no longer exists.")
            counts = {
                "areas": 1,
                "pitches": conn.execute(
                    "SELECT COUNT(*) FROM yamazumi_pitches WHERE project_id=? AND area_id=?",
                    (project_id, area_id),
                ).fetchone()[0],
                "elements": conn.execute(
                    "SELECT COUNT(*) FROM yamazumi_elements WHERE project_id=? AND area_id=?",
                    (project_id, area_id),
                ).fetchone()[0],
            }
            conn.execute(
                """UPDATE yamazumi_pitches SET feeds_into_pitch_id=NULL
                   WHERE project_id=? AND area_id=?""",
                (project_id, area_id),
            )
            conn.execute("DELETE FROM yamazumi_areas WHERE id=? AND project_id=?", (area_id, project_id))
        else:
            counts = {
                "areas": conn.execute(
                    "SELECT COUNT(*) FROM yamazumi_areas WHERE project_id=? AND scenario_id=?", (project_id, scenario_id)
                ).fetchone()[0],
                "pitches": conn.execute(
                    """SELECT COUNT(*) FROM yamazumi_pitches p JOIN yamazumi_areas a ON a.id=p.area_id
                       WHERE p.project_id=? AND a.scenario_id=?""", (project_id, scenario_id)
                ).fetchone()[0],
                "elements": conn.execute(
                    """SELECT COUNT(*) FROM yamazumi_elements e JOIN yamazumi_areas a ON a.id=e.area_id
                       WHERE e.project_id=? AND a.scenario_id=?""", (project_id, scenario_id)
                ).fetchone()[0],
            }
            conn.execute(
                """UPDATE yamazumi_pitches SET feeds_into_pitch_id=NULL
                   WHERE project_id=? AND area_id IN (
                       SELECT id FROM yamazumi_areas
                       WHERE project_id=? AND scenario_id=?
                   )""",
                (project_id, project_id, scenario_id),
            )
            conn.execute(
                "DELETE FROM yamazumi_areas WHERE project_id=? AND scenario_id=?",
                (project_id, scenario_id),
            )
    return counts

def upsert_yamazumi_area(
    project_id: str, scenario_id: str, name: str,
    section_id: str | None = None, takt_override_s: float | None = None,
    *, _conn: sqlite3.Connection | None = None,
) -> str:
    name = str(name or "").strip()
    if not name:
        raise ValueError("Yamazumi area name is required.")
    timestamp = now_iso()
    context = nullcontext(_conn) if _conn is not None else connection()
    with context as conn:
        existing = conn.execute(
            "SELECT id, section_id FROM yamazumi_areas WHERE project_id=? AND scenario_id=? AND name=?",
            (project_id, scenario_id, name),
        ).fetchone()
        area_id = str(existing["id"]) if existing else str(uuid4())
        normalized_section_id = str(section_id or "").strip() or None
        existing_section_id = (
            str(existing["section_id"] or "").strip() or None if existing else None
        )
        if existing_section_id and normalized_section_id and normalized_section_id != existing_section_id:
            raise ValueError(
                "This Yamazumi area is already linked from the Fishbone and cannot be relinked automatically."
            )
        if normalized_section_id:
            _validate_yamazumi_area_link(
                conn, project_id, scenario_id, normalized_section_id, area_id
            )
        if existing:
            conn.execute(
                """UPDATE yamazumi_areas SET section_id=COALESCE(?, section_id),
                   takt_override_s=COALESCE(?, takt_override_s), updated_at=? WHERE id=?""",
                (normalized_section_id, takt_override_s, timestamp, area_id),
            )
        else:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, takt_override_s, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (area_id, project_id, scenario_id, normalized_section_id, name, takt_override_s, timestamp),
            )
    return area_id

def _validate_yamazumi_area_link(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    section_id: str,
    area_id: str,
) -> None:
    section = conn.execute(
        "SELECT name FROM assembly_sections WHERE id=? AND project_id=?",
        (section_id, project_id),
    ).fetchone()
    if not section:
        raise ValueError("Choose a Fishbone section from this project.")
    conflict = conn.execute(
        """SELECT name FROM yamazumi_areas
           WHERE project_id=? AND scenario_id=? AND section_id=? AND id<>?""",
        (project_id, scenario_id, section_id, area_id),
    ).fetchone()
    if conflict:
        raise ValueError(
            f"Fishbone section {section['name']} is already linked to Yamazumi area {conflict['name']}."
        )

def update_yamazumi_settings(
    project_id: str,
    scenario_id: str,
    area_id: str,
    yamazumi_time_unit: object,
    section_id: str | None,
    takt_override_s: object,
    editor_name: str,
) -> dict[str, object]:
    """Atomically save the scenario unit and selected area's editable settings."""
    unit = normalize_time_unit(yamazumi_time_unit)
    normalized_section_id = str(section_id or "").strip() or None
    if takt_override_s is None or pd.isna(takt_override_s) or str(takt_override_s).strip() == "":
        takt = None
    else:
        takt = float(takt_override_s)
        if not math.isfinite(takt) or takt <= 0:
            raise ValueError("Takt override must be a finite number greater than zero.")

    timestamp = now_iso()
    with connection() as conn:
        scenario = conn.execute(
            """SELECT yamazumi_time_unit FROM planning_scenarios
               WHERE id=? AND project_id=?""",
            (scenario_id, project_id),
        ).fetchone()
        if not scenario:
            raise ValueError("The active planning scenario no longer exists in this project.")
        area = conn.execute(
            """SELECT scenario_id, section_id, takt_override_s FROM yamazumi_areas
               WHERE id=? AND project_id=?""",
            (area_id, project_id),
        ).fetchone()
        if not area or str(area["scenario_id"] or "") != scenario_id:
            raise ValueError("That Yamazumi area no longer exists in the active planning scenario.")

        existing_section_id = str(area["section_id"] or "").strip() or None
        if existing_section_id and normalized_section_id != existing_section_id:
            raise ValueError(
                "This Yamazumi area is already linked from the Fishbone and cannot be relinked manually."
            )
        if normalized_section_id:
            _validate_yamazumi_area_link(
                conn, project_id, scenario_id, normalized_section_id, area_id
            )

        previous_unit = normalize_time_unit(scenario["yamazumi_time_unit"])
        previous_takt = (
            None
            if area["takt_override_s"] is None
            else float(area["takt_override_s"])
        )
        changes: dict[str, dict[str, object]] = {}
        if previous_unit != unit:
            changes["yamazumi_time_unit"] = {
                "old": previous_unit,
                "new": unit,
            }
        if previous_takt != takt:
            changes["takt_override_s"] = {
                "old": previous_takt,
                "new": takt,
            }
        if existing_section_id != normalized_section_id:
            changes["section_id"] = {
                "old": existing_section_id,
                "new": normalized_section_id,
            }

        if "yamazumi_time_unit" in changes:
            conn.execute(
                """UPDATE planning_scenarios
                   SET yamazumi_time_unit=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (unit, timestamp, scenario_id, project_id),
            )
        if {"takt_override_s", "section_id"} & changes.keys():
            conn.execute(
                """UPDATE yamazumi_areas
                   SET section_id=?, takt_override_s=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (normalized_section_id, takt, timestamp, area_id, project_id),
            )
        if changes:
            record_audit_event(
                project_id,
                "Yamazumi",
                "Save & Refresh",
                1,
                editor_name,
                {
                    "scenario_id": scenario_id,
                    "area_id": area_id,
                    "changes": changes,
                },
                _conn=conn,
            )

    return {
        "changed": bool(changes),
        "time_unit_changed": "yamazumi_time_unit" in changes,
        "changes": changes,
        "updated_at": timestamp,
    }

def sync_yamazumi_areas_from_fishbone(project_id: str, scenario_id: str) -> dict[str, int]:
    """Create and repair one linked area per active Fishbone section."""
    timestamp = now_iso()
    summary = {"created": 0, "relinked": 0, "conflicts_cleared": 0}
    with connection() as conn:
        sections = conn.execute(
            """SELECT id, name FROM assembly_sections
               WHERE project_id=? AND active=1
               ORDER BY sequence, name""",
            (project_id,),
        ).fetchall()
        if not sections:
            return summary

        # Restart after every change. Re-reading the links prevents a repair
        # from hiding a newly missing section until the next button click.
        area_count = conn.execute(
            "SELECT COUNT(*) FROM yamazumi_areas WHERE project_id=? AND scenario_id=?",
            (project_id, scenario_id),
        ).fetchone()[0]
        max_changes = max(10, (len(sections) + int(area_count)) * 3)
        for _ in range(max_changes):
            changed = False

            duplicate = conn.execute(
                """SELECT section_id FROM yamazumi_areas
                   WHERE project_id=? AND scenario_id=? AND section_id IS NOT NULL
                   GROUP BY section_id HAVING COUNT(*) > 1 LIMIT 1""",
                (project_id, scenario_id),
            ).fetchone()
            if duplicate:
                section = conn.execute(
                    "SELECT name FROM assembly_sections WHERE id=? AND project_id=?",
                    (duplicate["section_id"], project_id),
                ).fetchone()
                linked = conn.execute(
                    """SELECT id, name FROM yamazumi_areas
                       WHERE project_id=? AND scenario_id=? AND section_id=?
                       ORDER BY name, id""",
                    (project_id, scenario_id, duplicate["section_id"]),
                ).fetchall()
                preferred = next(
                    (
                        row for row in linked
                        if section and str(row["name"]).casefold() == str(section["name"]).casefold()
                    ),
                    linked[0],
                )
                for row in linked:
                    if row["id"] == preferred["id"]:
                        continue
                    conn.execute(
                        "UPDATE yamazumi_areas SET section_id=NULL, updated_at=? WHERE id=?",
                        (timestamp, row["id"]),
                    )
                    summary["conflicts_cleared"] += 1
                changed = True

            if changed:
                continue

            for section in sections:
                matching_area = conn.execute(
                    """SELECT id, name, section_id FROM yamazumi_areas
                       WHERE project_id=? AND scenario_id=? AND name=? COLLATE NOCASE
                       ORDER BY id LIMIT 1""",
                    (project_id, scenario_id, section["name"]),
                ).fetchone()
                if matching_area and str(matching_area["section_id"] or "") != str(section["id"]):
                    current_target = conn.execute(
                        """SELECT id FROM yamazumi_areas
                           WHERE project_id=? AND scenario_id=? AND section_id=? AND id<>?""",
                        (project_id, scenario_id, section["id"], matching_area["id"]),
                    ).fetchone()
                    if current_target:
                        conn.execute(
                            "UPDATE yamazumi_areas SET section_id=NULL, updated_at=? WHERE id=?",
                            (timestamp, current_target["id"]),
                        )
                        summary["conflicts_cleared"] += 1
                    conn.execute(
                        "UPDATE yamazumi_areas SET section_id=?, updated_at=? WHERE id=?",
                        (section["id"], timestamp, matching_area["id"]),
                    )
                    summary["relinked"] += 1
                    changed = True
                    break

            if changed:
                continue

            for section in sections:
                linked = conn.execute(
                    """SELECT id FROM yamazumi_areas
                       WHERE project_id=? AND scenario_id=? AND section_id=?""",
                    (project_id, scenario_id, section["id"]),
                ).fetchone()
                if linked:
                    continue
                conn.execute(
                    """INSERT INTO yamazumi_areas
                       (id, project_id, scenario_id, section_id, name, takt_override_s, updated_at)
                       VALUES (?, ?, ?, ?, ?, NULL, ?)""",
                    (str(uuid4()), project_id, scenario_id, section["id"], section["name"], timestamp),
                )
                summary["created"] += 1
                changed = True
                break

            if not changed:
                return summary
        raise ValueError("Fishbone-to-Yamazumi links could not be repaired safely.")

def yamazumi_pitch_label(pitch_number: object, pitch_name: object = "") -> str:
    """Return the human-readable pitch identity used in validation and UI."""
    number = str(pitch_number or "").strip() or "Unnamed pitch"
    name = str(pitch_name or "").strip()
    return f"{number} — {name}" if name else number

def _yamazumi_pitch_address_conflict_rows(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        """WITH duplicate_addresses AS (
               SELECT TRIM(pitch.pitch_number) AS normalized_address
               FROM yamazumi_pitches pitch
               JOIN yamazumi_areas area ON area.id=pitch.area_id
               WHERE pitch.project_id=? AND area.scenario_id=?
               GROUP BY TRIM(pitch.pitch_number) COLLATE NOCASE
               HAVING COUNT(*)>1
           )
           SELECT pitch.id, pitch.area_id, TRIM(pitch.pitch_number) AS pitch_number,
                  pitch.pitch_name, area.name AS area_name
           FROM yamazumi_pitches pitch
           JOIN yamazumi_areas area ON area.id=pitch.area_id
           JOIN duplicate_addresses duplicate
             ON TRIM(pitch.pitch_number)=duplicate.normalized_address COLLATE NOCASE
           WHERE pitch.project_id=? AND area.scenario_id=?
           ORDER BY TRIM(pitch.pitch_number) COLLATE NOCASE,
                    area.name COLLATE NOCASE, pitch.sequence, pitch.id""",
        (project_id, scenario_id, project_id, scenario_id),
    ).fetchall()

def yamazumi_pitch_address_conflicts(
    project_id: str, scenario_id: str
) -> pd.DataFrame:
    """Return every pitch participating in a scenario-wide address conflict."""
    with connection() as conn:
        rows = _yamazumi_pitch_address_conflict_rows(
            conn, project_id, scenario_id
        )
    columns = ["id", "area_id", "pitch_number", "pitch_name", "area_name"]
    if not rows:
        return pd.DataFrame(
            {
                column: pd.Series(dtype="string")
                for column in columns
            }
        )
    return pd.DataFrame([dict(row) for row in rows], columns=columns).astype(
        "string"
    )

def _yamazumi_pitch_address_owner(
    conn: sqlite3.Connection,
    project_id: str,
    area_id: str,
    pitch_number: str,
    *,
    exclude_pitch_id: str | None = None,
) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT existing.id, existing_area.name AS area_name
           FROM yamazumi_pitches existing
           JOIN yamazumi_areas existing_area ON existing_area.id=existing.area_id
           JOIN yamazumi_areas requested_area ON requested_area.id=?
           WHERE existing.project_id=?
             AND existing_area.scenario_id IS requested_area.scenario_id
             AND TRIM(existing.pitch_number)=TRIM(?) COLLATE NOCASE
             AND (? IS NULL OR existing.id<>?)
           ORDER BY existing_area.name COLLATE NOCASE, existing.sequence
           LIMIT 1""",
        (
            area_id,
            project_id,
            pitch_number,
            exclude_pitch_id,
            exclude_pitch_id,
        ),
    ).fetchone()

def _validate_yamazumi_pitch_address_available(
    conn: sqlite3.Connection,
    project_id: str,
    area_id: str,
    pitch_number: str,
    *,
    exclude_pitch_id: str | None = None,
) -> None:
    owner = _yamazumi_pitch_address_owner(
        conn,
        project_id,
        area_id,
        pitch_number,
        exclude_pitch_id=exclude_pitch_id,
    )
    if owner:
        raise ValueError(
            f"Pitch address {pitch_number} already exists in Yamazumi area "
            f"{owner['area_name']} in this planning scenario. Pitch addresses "
            "must be unique across the scenario."
        )

def _validate_yamazumi_scenario_pitch_addresses(
    conn: sqlite3.Connection, project_id: str, scenario_id: str
) -> None:
    conflicts = _yamazumi_pitch_address_conflict_rows(
        conn, project_id, scenario_id
    )
    if not conflicts:
        return
    addresses = list(
        dict.fromkeys(str(row["pitch_number"]) for row in conflicts)
    )
    raise ValueError(
        "Resolve duplicate pitch addresses in this planning scenario before "
        f"saving: {', '.join(addresses)}."
    )

def _validate_yamazumi_pitch_conflict_progress(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    before_conflicts: list[sqlite3.Row],
) -> None:
    """Allow a legacy-conflict correction while rejecting unchanged/new conflicts."""
    after_conflicts = _yamazumi_pitch_address_conflict_rows(
        conn, project_id, scenario_id
    )
    if not after_conflicts:
        return
    before_ids = {str(row["id"]) for row in before_conflicts}
    after_ids = {str(row["id"]) for row in after_conflicts}
    if before_ids and after_ids < before_ids:
        return
    addresses = list(
        dict.fromkeys(str(row["pitch_number"]) for row in after_conflicts)
    )
    raise ValueError(
        "Resolve duplicate pitch addresses in this planning scenario before "
        f"saving: {', '.join(addresses)}."
    )

def yamazumi_pitch_feed_target_status(
    pitch_type: object, feeds_into_pitch_id: object
) -> str:
    """Return the visible compatibility-null indicator for feeder pitches."""
    normalized_type = str(pitch_type or "Pitch").strip().title()
    target_id = (
        ""
        if feeds_into_pitch_id is None or pd.isna(feeds_into_pitch_id)
        else str(feeds_into_pitch_id).strip()
    )
    if normalized_type in YAMAZUMI_FEEDER_PITCH_TYPES and not target_id:
        return "Feed target required"
    return ""

def _normalize_yamazumi_feed_target(
    pitch_type: str,
    feeds_into_pitch_id: object,
    *,
    require_target: bool,
    pitch_label: str,
) -> str | None:
    target_id = (
        None
        if feeds_into_pitch_id is None or pd.isna(feeds_into_pitch_id)
        else str(feeds_into_pitch_id).strip() or None
    )
    if pitch_type not in YAMAZUMI_FEEDER_PITCH_TYPES:
        return None
    if require_target and target_id is None:
        raise ValueError(
            f"Feeds into pitch is required for {pitch_type} pitch {pitch_label}."
        )
    return target_id

def _validate_yamazumi_pitch_feeds(
    conn: sqlite3.Connection, project_id: str, area_id: str
) -> None:
    """Validate the complete directed feeds-into graph for one Yamazumi area."""
    rows = conn.execute(
        """SELECT id, project_id, area_id, pitch_number, pitch_name, pitch_type,
                  feeds_into_pitch_id
           FROM yamazumi_pitches
           WHERE project_id=? AND area_id=?""",
        (project_id, area_id),
    ).fetchall()
    pitch_by_id = {str(row["id"]): row for row in rows}
    target_by_source: dict[str, str] = {}
    label_by_id = {
        pitch_id: yamazumi_pitch_label(row["pitch_number"], row["pitch_name"])
        for pitch_id, row in pitch_by_id.items()
    }
    for source_id, source in pitch_by_id.items():
        pitch_type = str(source["pitch_type"] or "Pitch").strip().title()
        target_id = str(source["feeds_into_pitch_id"] or "").strip()
        if not target_id:
            continue
        if pitch_type not in YAMAZUMI_FEEDER_PITCH_TYPES:
            raise ValueError(
                f"Pitch {label_by_id[source_id]} cannot have a feed target when its type is {pitch_type}."
            )
        if source_id == target_id:
            raise ValueError(f"Pitch {label_by_id[source_id]} cannot feed into itself.")
        target = conn.execute(
            """SELECT p.id, p.project_id, p.area_id, a.scenario_id
               FROM yamazumi_pitches p
               JOIN yamazumi_areas a ON a.id=p.area_id
               WHERE p.id=?""",
            (target_id,),
        ).fetchone()
        if not target:
            raise ValueError(
                f"The feed target selected for pitch {label_by_id[source_id]} no longer exists."
            )
        if str(target["project_id"]) != project_id or str(target["area_id"]) != area_id:
            raise ValueError(
                f"Pitch {label_by_id[source_id]} must feed into another pitch in the same Yamazumi area."
            )
        target_by_source[source_id] = target_id

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(pitch_id: str, path: list[str]) -> None:
        if pitch_id in visiting:
            cycle_start = path.index(pitch_id)
            cycle = path[cycle_start:]
            labels = " → ".join(label_by_id.get(value, value) for value in cycle)
            raise ValueError(f"Yamazumi pitch feeds-into relationships cannot contain a cycle: {labels}.")
        if pitch_id in visited:
            return
        visiting.add(pitch_id)
        target_id = target_by_source.get(pitch_id)
        if target_id:
            visit(target_id, [*path, target_id])
        visiting.remove(pitch_id)
        visited.add(pitch_id)

    for source_id in target_by_source:
        visit(source_id, [source_id])

def _validate_yamazumi_feed_target_context(
    conn: sqlite3.Connection,
    project_id: str,
    area_id: str,
    source_id: str,
    source_label: str,
    target_id: str | None,
) -> None:
    if not target_id:
        return
    if source_id == target_id:
        raise ValueError(f"Pitch {source_label} cannot feed into itself.")
    target = conn.execute(
        "SELECT project_id, area_id FROM yamazumi_pitches WHERE id=?",
        (target_id,),
    ).fetchone()
    if not target:
        raise ValueError(
            f"The feed target selected for pitch {source_label} no longer exists."
        )
    if str(target["project_id"]) != project_id or str(target["area_id"]) != area_id:
        raise ValueError(
            f"Pitch {source_label} must feed into another pitch in the same Yamazumi area."
        )

def _require_yamazumi_feed_target_for_pitch_write(
    conn: sqlite3.Connection, project_id: str, pitch: sqlite3.Row
) -> None:
    pitch_type = str(pitch["pitch_type"] or "Pitch").strip().title()
    label = yamazumi_pitch_label(pitch["pitch_number"], pitch["pitch_name"])
    target_id = _normalize_yamazumi_feed_target(
        pitch_type,
        pitch["feeds_into_pitch_id"],
        require_target=True,
        pitch_label=label,
    )
    _validate_yamazumi_feed_target_context(
        conn,
        project_id,
        str(pitch["area_id"]),
        str(pitch["id"]),
        label,
        target_id,
    )

def _yamazumi_pitch_reference_blockers(
    conn: sqlite3.Connection,
    project_id: str,
    area_id: str,
    pitch_ids: set[str],
) -> list[dict]:
    if not pitch_ids:
        return []
    placeholders = ",".join("?" for _ in pitch_ids)
    return [
        dict(row)
        for row in conn.execute(
            f"""SELECT source.id AS source_pitch_id,
                       source.pitch_number AS source_pitch_number,
                       source.pitch_name AS source_pitch_name,
                       target.id AS target_pitch_id,
                       target.pitch_number AS target_pitch_number,
                       target.pitch_name AS target_pitch_name
                FROM yamazumi_pitches source
                JOIN yamazumi_pitches target ON target.id=source.feeds_into_pitch_id
                WHERE target.project_id=? AND target.area_id=?
                  AND target.id IN ({placeholders})
                  AND source.id NOT IN ({placeholders})
                ORDER BY target.sequence, source.sequence""",
            (project_id, area_id, *pitch_ids, *pitch_ids),
        ).fetchall()
    ]

def yamazumi_pitch_delete_blockers(
    project_id: str, area_id: str, pitch_ids: list[str]
) -> list[dict]:
    """Return feeder pitches that must be re-pointed before target deletion."""
    normalized_ids = {str(value).strip() for value in pitch_ids if str(value).strip()}
    with connection() as conn:
        return _yamazumi_pitch_reference_blockers(
            conn, project_id, area_id, normalized_ids
        )

def _raise_yamazumi_pitch_reference_blockers(blockers: list[dict]) -> None:
    if not blockers:
        return
    relationships = ", ".join(
        f"{yamazumi_pitch_label(row['source_pitch_number'], row['source_pitch_name'])} → "
        f"{yamazumi_pitch_label(row['target_pitch_number'], row['target_pitch_name'])}"
        for row in blockers
    )
    raise ValueError(
        "Re-point these feeder pitches or change their pitch type before deleting the target: "
        + relationships
        + "."
    )

def add_yamazumi_pitch(
    project_id: str,
    area_id: str,
    pitch_number: str,
    pitch_name: str = "",
    status: str = "Active",
    model_variants: list[str] | None = None,
    pitch_type: str = "Pitch",
    feeds_into_pitch_id: str | None = None,
) -> str:
    """Add one physical pitch address to a Yamazumi area."""
    pitch_number = str(pitch_number or "").strip()
    if not pitch_number:
        raise ValueError("Pitch address is required.")
    status = str(status or "Active").title()
    if status not in {"Active", "Blocked", "Open"}:
        raise ValueError("Pitch status must be Active, Blocked, or Open.")
    pitch_type = str(pitch_type or "Pitch").strip().title()
    if pitch_type not in YAMAZUMI_PITCH_TYPES:
        raise ValueError("Choose a valid pitch type.")
    feed_target_id = _normalize_yamazumi_feed_target(
        pitch_type,
        feeds_into_pitch_id,
        require_target=True,
        pitch_label=pitch_number,
    )
    timestamp = now_iso()
    variants = list(dict.fromkeys(str(value).strip() for value in (model_variants or ["Base"]) if str(value).strip()))
    if not variants:
        raise ValueError("Choose at least one model variant for the pitch.")
    pitch_id = str(uuid4())
    try:
        with connection() as conn:
            valid_area = conn.execute(
                "SELECT scenario_id FROM yamazumi_areas WHERE id=? AND project_id=?",
                (area_id, project_id),
            ).fetchone()
            if not valid_area:
                raise ValueError("That Yamazumi area no longer exists.")
            before_conflicts = _yamazumi_pitch_address_conflict_rows(
                conn, project_id, str(valid_area["scenario_id"])
            )
            _validate_yamazumi_pitch_address_available(
                conn, project_id, area_id, pitch_number
            )
            _validate_yamazumi_feed_target_context(
                conn, project_id, area_id, pitch_id, pitch_number, feed_target_id
            )
            sequence = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 10 FROM yamazumi_pitches WHERE project_id=? AND area_id=?",
                (project_id, area_id),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO yamazumi_pitches
                (id, project_id, area_id, pitch_number, pitch_name, status, sequence,
                 model_variants, pitch_type, feeds_into_pitch_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pitch_id, project_id, area_id, pitch_number, str(pitch_name or "").strip(),
                 status, sequence, json.dumps(variants), pitch_type, feed_target_id, timestamp),
            )
            _validate_yamazumi_pitch_feeds(conn, project_id, area_id)
            _validate_yamazumi_pitch_conflict_progress(
                conn,
                project_id,
                str(valid_area["scenario_id"]),
                before_conflicts,
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(
            f"Pitch address {pitch_number} already exists in this planning scenario."
        ) from exc
    return pitch_id

def add_yamazumi_element(
    project_id: str,
    area_id: str,
    pitch_id: str | None,
    values: dict,
) -> str:
    """Add one Yamazumi work element from the balancing board."""
    description = str(values.get("description") or "").strip()
    if not description:
        raise ValueError("Work description is required.")
    try:
        time_s = float(values.get("time_s") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Work-element time must be a number.") from exc
    if time_s < 0:
        raise ValueError("Work-element time cannot be negative.")
    pitch_id = str(pitch_id or "").strip() or None
    raw_variants = (
        values.get("model_variants")
        if "model_variants" in values
        else values.get("model_variant") or "Base"
    )
    selected_variants = parse_yamazumi_model_variants(raw_variants, fallback=None)
    if not selected_variants:
        raise ValueError("Choose at least one model variant for the work element.")
    primary_variant = selected_variants[0]
    work_type = str(values.get("work_type") or "Cycle").strip().title()
    if work_type not in {"Cycle", "Periodic", "Fluctuation"}:
        raise ValueError("Work type must be Cycle, Periodic, or Fluctuation.")
    element_id = str(uuid4())
    timestamp = now_iso()
    with connection() as conn:
        if pitch_id:
            active_pitch = conn.execute(
                """SELECT id, area_id, pitch_number, pitch_name, pitch_type,
                          feeds_into_pitch_id, model_variants
                   FROM yamazumi_pitches
                   WHERE id=? AND project_id=? AND area_id=? AND status='Active'""",
                (pitch_id, project_id, area_id),
            ).fetchone()
            if not active_pitch:
                raise ValueError("Work can only be added to an Active pitch.")
            pitch_variants = list(dict.fromkeys(
                str(value).strip()
                for value in json.loads(active_pitch["model_variants"] or "[]")
                if str(value).strip()
            ))
            missing_variants = [
                variant for variant in selected_variants if variant not in pitch_variants
            ]
            if missing_variants:
                _require_yamazumi_feed_target_for_pitch_write(
                    conn, project_id, active_pitch
                )
                pitch_variants.extend(missing_variants)
                conn.execute(
                    """UPDATE yamazumi_pitches SET model_variants=?, updated_at=?
                       WHERE id=? AND project_id=? AND area_id=?""",
                    (json.dumps(pitch_variants), timestamp, pitch_id, project_id, area_id),
                )
        sequence = conn.execute(
            """SELECT COALESCE(MAX(sequence), 0) + 10 FROM yamazumi_elements
               WHERE project_id=? AND area_id=? AND pitch_id IS ?""",
            (project_id, area_id, pitch_id),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO yamazumi_elements
               (id, project_id, area_id, pitch_id, model_variant, model_variants,
                work_type, description,
                time_s, work_region, sequence, source, process_sync_status, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Interactive board', 'Needs IE review', ?)""",
            (
                element_id, project_id, area_id, pitch_id,
                primary_variant, json.dumps(selected_variants),
                work_type, description, time_s,
                str(values.get("work_region") or "None").strip(), sequence, timestamp,
            ),
        )
    return element_id

def _prepare_yamazumi_copy(
    conn: sqlite3.Connection,
    project_id: str,
    source_scenario_id: str,
    source_area_id: str,
    target_scenario_id: str,
    target_area_id: str,
    pitch_ids: list[str],
    element_ids: list[str],
    *,
    standalone_target_pitch_id: str | None = None,
    pitch_number_overrides: dict[str, str] | None = None,
    feed_target_overrides: dict[str, str] | None = None,
) -> dict:
    """Validate and describe one Yamazumi cross-area copy without writing."""
    source = conn.execute(
        """SELECT area.id, area.name, area.scenario_id, scenario.name AS scenario_name
           FROM yamazumi_areas area
           JOIN planning_scenarios scenario ON scenario.id=area.scenario_id
           WHERE area.id=? AND area.project_id=? AND area.scenario_id=?
             AND scenario.project_id=? AND scenario.status<>'Archived'""",
        (source_area_id, project_id, source_scenario_id, project_id),
    ).fetchone()
    if not source:
        raise ValueError("The source Yamazumi area is not available in that planning scenario.")
    target = conn.execute(
        """SELECT area.id, area.name, area.scenario_id, scenario.name AS scenario_name
           FROM yamazumi_areas area
           JOIN planning_scenarios scenario ON scenario.id=area.scenario_id
           WHERE area.id=? AND area.project_id=? AND area.scenario_id=?
             AND scenario.project_id=? AND scenario.status<>'Archived'""",
        (target_area_id, project_id, target_scenario_id, project_id),
    ).fetchone()
    if not target:
        raise ValueError("The target Yamazumi area is not available in that planning scenario.")
    if source_area_id == target_area_id:
        raise ValueError("Choose a different target Yamazumi area.")

    normalized_pitch_ids = list(dict.fromkeys(
        str(value or "").strip() for value in pitch_ids if str(value or "").strip()
    ))
    normalized_element_ids = list(dict.fromkeys(
        str(value or "").strip() for value in element_ids if str(value or "").strip()
    ))
    if not normalized_pitch_ids and not normalized_element_ids:
        raise ValueError("Select at least one saved pitch or Yamazumi work element to copy.")

    source_pitches = [
        dict(row)
        for row in conn.execute(
            """SELECT * FROM yamazumi_pitches
               WHERE project_id=? AND area_id=?
               ORDER BY sequence, pitch_number COLLATE NOCASE, id""",
            (project_id, source_area_id),
        ).fetchall()
    ]
    source_pitch_by_id = {str(row["id"]): row for row in source_pitches}
    missing_pitch_ids = set(normalized_pitch_ids) - set(source_pitch_by_id)
    if missing_pitch_ids:
        raise ValueError("A selected source pitch is stale or belongs to another Yamazumi area.")
    selected_pitches = [
        row for row in source_pitches if str(row["id"]) in set(normalized_pitch_ids)
    ]

    source_elements = [
        dict(row)
        for row in conn.execute(
            """SELECT * FROM yamazumi_elements
               WHERE project_id=? AND area_id=?
               ORDER BY COALESCE(pitch_id, ''), sequence, description COLLATE NOCASE, id""",
            (project_id, source_area_id),
        ).fetchall()
    ]
    source_element_by_id = {str(row["id"]): row for row in source_elements}
    missing_element_ids = set(normalized_element_ids) - set(source_element_by_id)
    if missing_element_ids:
        raise ValueError(
            "A selected source work element is stale or belongs to another Yamazumi area."
        )
    selected_pitch_id_set = set(normalized_pitch_ids)
    pitch_elements = [
        row
        for row in source_elements
        if str(row.get("pitch_id") or "") in selected_pitch_id_set
    ]
    pitch_element_ids = {str(row["id"]) for row in pitch_elements}
    copied_element_pitch_ids = {
        str(row.get("pitch_id") or "") for row in pitch_elements
    }
    for source_pitch in selected_pitches:
        if (
            str(source_pitch["id"]) in copied_element_pitch_ids
            and str(source_pitch.get("status") or "") != "Active"
        ):
            raise ValueError(
                "A pitch containing work must be Active before it can be copied with its work elements."
            )
    standalone_elements = [
        row
        for row in source_elements
        if str(row["id"]) in set(normalized_element_ids)
        and str(row["id"]) not in pitch_element_ids
    ]
    elements_to_copy = [*pitch_elements, *standalone_elements]

    target_pitches = [
        dict(row)
        for row in conn.execute(
            """SELECT * FROM yamazumi_pitches
               WHERE project_id=? AND area_id=?
               ORDER BY sequence, pitch_number COLLATE NOCASE, id""",
            (project_id, target_area_id),
        ).fetchall()
    ]
    target_pitch_by_id = {str(row["id"]): row for row in target_pitches}
    normalized_target_pitch_id = str(standalone_target_pitch_id or "").strip() or None
    if standalone_elements and normalized_target_pitch_id:
        destination = target_pitch_by_id.get(normalized_target_pitch_id)
        if not destination or str(destination.get("status") or "") != "Active":
            raise ValueError(
                "Standalone work elements can only be copied to an Active pitch in the target area."
            )

    number_overrides = {
        str(key): str(value or "").strip()
        for key, value in (pitch_number_overrides or {}).items()
    }
    occupied_numbers = {
        str(row["pitch_number"] or "").strip().casefold()
        for row in conn.execute(
            """SELECT pitch.pitch_number
               FROM yamazumi_pitches pitch
               JOIN yamazumi_areas area ON area.id=pitch.area_id
               WHERE pitch.project_id=? AND area.scenario_id=?""",
            (project_id, target_scenario_id),
        ).fetchall()
    }
    proposed_numbers: dict[str, str] = {}
    number_conflicts: list[dict] = []
    proposed_casefold: dict[str, str] = {}
    for row in selected_pitches:
        source_id = str(row["id"])
        number = number_overrides.get(source_id) or str(row.get("pitch_number") or "").strip()
        proposed_numbers[source_id] = number
        conflict_reason = ""
        if not number:
            conflict_reason = "A destination pitch address is required."
        elif number.casefold() in occupied_numbers:
            conflict_reason = "That pitch address already exists in the target scenario."
        elif number.casefold() in proposed_casefold:
            conflict_reason = "Another selected pitch uses the same destination address."
        if conflict_reason:
            number_conflicts.append(
                {
                    "source_pitch_id": source_id,
                    "source_pitch_number": str(row.get("pitch_number") or ""),
                    "source_pitch_name": str(row.get("pitch_name") or ""),
                    "proposed_pitch_number": number,
                    "reason": conflict_reason,
                }
            )
        proposed_casefold[number.casefold()] = source_id

    feed_overrides = {
        str(key): str(value or "").strip()
        for key, value in (feed_target_overrides or {}).items()
        if str(value or "").strip()
    }
    feed_mappings: dict[str, dict] = {}
    feed_mapping_required: list[dict] = []
    for row in selected_pitches:
        source_id = str(row["id"])
        pitch_type = str(row.get("pitch_type") or "Pitch").strip().title()
        if pitch_type not in YAMAZUMI_FEEDER_PITCH_TYPES:
            continue
        old_target_id = str(row.get("feeds_into_pitch_id") or "").strip()
        if old_target_id and old_target_id in selected_pitch_id_set:
            feed_mappings[source_id] = {
                "kind": "copied",
                "source_target_pitch_id": old_target_id,
                "target_pitch_id": None,
                "target_label": proposed_numbers.get(old_target_id, "Copied pitch"),
            }
            continue
        target_pitch_id = feed_overrides.get(source_id)
        destination = target_pitch_by_id.get(str(target_pitch_id or ""))
        if not destination:
            feed_mapping_required.append(
                {
                    "source_pitch_id": source_id,
                    "source_pitch_number": str(row.get("pitch_number") or ""),
                    "source_pitch_name": str(row.get("pitch_name") or ""),
                }
            )
            continue
        feed_mappings[source_id] = {
            "kind": "existing",
            "source_target_pitch_id": old_target_id or None,
            "target_pitch_id": str(destination["id"]),
            "target_label": yamazumi_pitch_label(
                destination.get("pitch_number"), destination.get("pitch_name")
            ),
        }

    variant_additions: dict[str, list[str]] = {}
    if standalone_elements and normalized_target_pitch_id:
        destination = target_pitch_by_id[normalized_target_pitch_id]
        current_variants = parse_yamazumi_model_variants(
            destination.get("model_variants"), fallback=None
        )
        required_variants = list(dict.fromkeys(
            variant
            for element in standalone_elements
            for variant in parse_yamazumi_model_variants(
                element.get("model_variants"), element.get("model_variant")
            )
        ))
        missing_variants = [
            variant for variant in required_variants if variant not in current_variants
        ]
        if missing_variants:
            _require_yamazumi_feed_target_for_pitch_write(
                conn, project_id, destination
            )
            variant_additions[normalized_target_pitch_id] = missing_variants

    active_target_regions = {
        str(row["name"]).strip().casefold()
        for row in conn.execute(
            """SELECT name FROM yamazumi_work_regions
               WHERE project_id=? AND area_id=? AND active=1""",
            (project_id, target_area_id),
        ).fetchall()
    }
    legacy_work_regions = sorted({
        str(row.get("work_region") or "None").strip()
        for row in elements_to_copy
        if str(row.get("work_region") or "None").strip()
        and str(row.get("work_region") or "None").strip().casefold() != "none"
        and str(row.get("work_region") or "None").strip().casefold()
        not in active_target_regions
    })

    return {
        "source": dict(source),
        "target": dict(target),
        "selected_pitches": selected_pitches,
        "pitch_elements": pitch_elements,
        "standalone_elements": standalone_elements,
        "elements_to_copy": elements_to_copy,
        "target_pitches": target_pitches,
        "standalone_target_pitch_id": normalized_target_pitch_id,
        "proposed_pitch_numbers": proposed_numbers,
        "number_conflicts": number_conflicts,
        "feed_mappings": feed_mappings,
        "feed_mapping_required": feed_mapping_required,
        "variant_additions": variant_additions,
        "legacy_work_regions": legacy_work_regions,
        "ready": not number_conflicts and not feed_mapping_required,
    }

def preview_yamazumi_copy(
    project_id: str,
    source_scenario_id: str,
    source_area_id: str,
    target_scenario_id: str,
    target_area_id: str,
    pitch_ids: list[str],
    element_ids: list[str],
    *,
    standalone_target_pitch_id: str | None = None,
    pitch_number_overrides: dict[str, str] | None = None,
    feed_target_overrides: dict[str, str] | None = None,
) -> dict:
    """Return a no-write preflight for a Yamazumi cross-area copy."""
    with connection() as conn:
        return _prepare_yamazumi_copy(
            conn,
            project_id,
            source_scenario_id,
            source_area_id,
            target_scenario_id,
            target_area_id,
            pitch_ids,
            element_ids,
            standalone_target_pitch_id=standalone_target_pitch_id,
            pitch_number_overrides=pitch_number_overrides,
            feed_target_overrides=feed_target_overrides,
        )

def copy_yamazumi_records(
    project_id: str,
    source_scenario_id: str,
    source_area_id: str,
    target_scenario_id: str,
    target_area_id: str,
    pitch_ids: list[str],
    element_ids: list[str],
    *,
    standalone_target_pitch_id: str | None = None,
    pitch_number_overrides: dict[str, str] | None = None,
    feed_target_overrides: dict[str, str] | None = None,
    editor_name: str,
) -> dict:
    """Atomically copy saved Yamazumi records into another area and audit once."""
    normalized_editor = str(editor_name or "").strip()
    if not normalized_editor:
        raise ValueError("Enter the Current editor before copying Yamazumi records.")
    timestamp = now_iso()
    with connection() as conn:
        plan = _prepare_yamazumi_copy(
            conn,
            project_id,
            source_scenario_id,
            source_area_id,
            target_scenario_id,
            target_area_id,
            pitch_ids,
            element_ids,
            standalone_target_pitch_id=standalone_target_pitch_id,
            pitch_number_overrides=pitch_number_overrides,
            feed_target_overrides=feed_target_overrides,
        )
        if not plan["ready"]:
            if plan["number_conflicts"]:
                raise ValueError(
                    "Resolve every destination pitch-address conflict before copying."
                )
            raise ValueError(
                "Choose a destination feed target for every copied Subassembly or Kitter pitch."
            )

        next_pitch_sequence = int(conn.execute(
            """SELECT COALESCE(MAX(sequence), 0) FROM yamazumi_pitches
               WHERE project_id=? AND area_id=?""",
            (project_id, target_area_id),
        ).fetchone()[0] or 0)
        pitch_id_map: dict[str, str] = {}
        for offset, source_pitch in enumerate(plan["selected_pitches"], start=1):
            old_id = str(source_pitch["id"])
            new_id = str(uuid4())
            pitch_id_map[old_id] = new_id
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status,
                    sequence, model_variants, pitch_type, feeds_into_pitch_id,
                    updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                (
                    new_id,
                    project_id,
                    target_area_id,
                    plan["proposed_pitch_numbers"][old_id],
                    str(source_pitch.get("pitch_name") or "").strip(),
                    str(source_pitch.get("status") or "Active"),
                    next_pitch_sequence + offset * 10,
                    json.dumps(parse_yamazumi_model_variants(
                        source_pitch.get("model_variants"), fallback=None
                    )),
                    str(source_pitch.get("pitch_type") or "Pitch"),
                    timestamp,
                ),
            )

        for source_pitch in plan["selected_pitches"]:
            old_id = str(source_pitch["id"])
            mapping = plan["feed_mappings"].get(old_id)
            if not mapping:
                continue
            target_pitch_id = (
                pitch_id_map[str(mapping["source_target_pitch_id"])]
                if mapping["kind"] == "copied"
                else str(mapping["target_pitch_id"])
            )
            conn.execute(
                "UPDATE yamazumi_pitches SET feeds_into_pitch_id=? WHERE id=?",
                (target_pitch_id, pitch_id_map[old_id]),
            )

        for destination_pitch_id, additions in plan["variant_additions"].items():
            destination = conn.execute(
                """SELECT id, area_id, pitch_number, pitch_name, pitch_type,
                          feeds_into_pitch_id, model_variants
                   FROM yamazumi_pitches
                   WHERE id=? AND project_id=? AND area_id=? AND status='Active'""",
                (destination_pitch_id, project_id, target_area_id),
            ).fetchone()
            if not destination:
                raise ValueError("The destination pitch changed before the copy was confirmed.")
            _require_yamazumi_feed_target_for_pitch_write(
                conn, project_id, destination
            )
            current_variants = parse_yamazumi_model_variants(
                destination["model_variants"], fallback=None
            )
            conn.execute(
                """UPDATE yamazumi_pitches SET model_variants=?, updated_at=?
                   WHERE id=? AND project_id=? AND area_id=?""",
                (
                    json.dumps(list(dict.fromkeys([*current_variants, *additions]))),
                    timestamp,
                    destination_pitch_id,
                    project_id,
                    target_area_id,
                ),
            )

        next_sequence_by_pitch: dict[str | None, int] = {}
        standalone_target = plan["standalone_target_pitch_id"]
        if plan["standalone_elements"]:
            next_sequence_by_pitch[standalone_target] = int(conn.execute(
                """SELECT COALESCE(MAX(sequence), 0) FROM yamazumi_elements
                   WHERE project_id=? AND area_id=? AND pitch_id IS ?""",
                (project_id, target_area_id, standalone_target),
            ).fetchone()[0] or 0)
        element_id_map: dict[str, str] = {}
        copied_pitch_positions: dict[str, int] = {}
        pitch_element_ids = {str(row["id"]) for row in plan["pitch_elements"]}
        for source_element in plan["elements_to_copy"]:
            old_element_id = str(source_element["id"])
            old_pitch_id = str(source_element.get("pitch_id") or "")
            if old_element_id in pitch_element_ids:
                destination_pitch_id = pitch_id_map[old_pitch_id]
                copied_pitch_positions[destination_pitch_id] = (
                    copied_pitch_positions.get(destination_pitch_id, 0) + 10
                )
                sequence = copied_pitch_positions[destination_pitch_id]
            else:
                destination_pitch_id = standalone_target
                next_sequence_by_pitch[destination_pitch_id] = (
                    next_sequence_by_pitch.get(destination_pitch_id, 0) + 10
                )
                sequence = next_sequence_by_pitch[destination_pitch_id]
            variants = parse_yamazumi_model_variants(
                source_element.get("model_variants"), source_element.get("model_variant")
            )
            new_element_id = str(uuid4())
            element_id_map[old_element_id] = new_element_id
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, model_variant, model_variants,
                    work_type, description, time_s, work_region, sequence,
                    source, process_element_id, process_sync_status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           'Yamazumi copy', NULL, 'Needs IE review', ?)""",
                (
                    new_element_id,
                    project_id,
                    target_area_id,
                    destination_pitch_id,
                    variants[0] if variants else "Base",
                    json.dumps(variants or ["Base"]),
                    str(source_element.get("work_type") or "Cycle"),
                    str(source_element.get("description") or "").strip(),
                    float(source_element.get("time_s") or 0),
                    str(source_element.get("work_region") or "None").strip(),
                    sequence,
                    timestamp,
                ),
            )

        _validate_yamazumi_pitch_feeds(conn, project_id, target_area_id)
        details = {
            "source_scenario_id": source_scenario_id,
            "source_area_id": source_area_id,
            "source_area": str(plan["source"].get("name") or ""),
            "target_scenario_id": target_scenario_id,
            "target_area_id": target_area_id,
            "target_area": str(plan["target"].get("name") or ""),
            "pitch_id_map": pitch_id_map,
            "element_id_map": element_id_map,
            "pitch_numbers": plan["proposed_pitch_numbers"],
            "feed_mappings": plan["feed_mappings"],
            "variant_additions": plan["variant_additions"],
            "process_links_copied": False,
            "created_at": timestamp,
        }
        record_audit_event(
            project_id,
            "Yamazumi",
            "Copy to another area",
            len(pitch_id_map) + len(element_id_map),
            normalized_editor,
            details,
            _conn=conn,
        )

    return {
        "pitches_created": len(pitch_id_map),
        "elements_created": len(element_id_map),
        "pitch_id_map": pitch_id_map,
        "element_id_map": element_id_map,
        "variant_additions": plan["variant_additions"],
        "timestamp": timestamp,
    }

def update_yamazumi_pitch(project_id: str, area_id: str, pitch_id: str, values: dict) -> None:
    """Update one pitch from the interactive board without replacing the area table."""
    pitch_number = str(values.get("pitch_number") or "").strip()
    if not pitch_number:
        raise ValueError("Pitch address is required.")
    status = str(values.get("status") or "Active").title()
    if status not in {"Active", "Blocked", "Open"}:
        raise ValueError("Pitch status must be Active, Blocked, or Open.")
    pitch_type = str(values.get("pitch_type") or "Pitch").strip().title()
    if pitch_type not in YAMAZUMI_PITCH_TYPES:
        raise ValueError("Choose a valid pitch type.")
    feed_target_id = _normalize_yamazumi_feed_target(
        pitch_type,
        values.get("feeds_into_pitch_id"),
        require_target=True,
        pitch_label=pitch_number,
    )
    variants = list(
        dict.fromkeys(
            str(value).strip()
            for value in (values.get("model_variants") or [])
            if str(value).strip()
        )
    )
    if not variants:
        raise ValueError("Choose at least one model variant for the pitch.")
    with connection() as conn:
        existing = conn.execute(
            """SELECT area.scenario_id
               FROM yamazumi_pitches pitch
               JOIN yamazumi_areas area ON area.id=pitch.area_id
               WHERE pitch.id=? AND pitch.project_id=? AND pitch.area_id=?""",
            (pitch_id, project_id, area_id),
        ).fetchone()
        if not existing:
            raise ValueError("That pitch no longer exists.")
        before_conflicts = _yamazumi_pitch_address_conflict_rows(
            conn, project_id, str(existing["scenario_id"])
        )
        _validate_yamazumi_pitch_address_available(
            conn,
            project_id,
            area_id,
            pitch_number,
            exclude_pitch_id=pitch_id,
        )
        _validate_yamazumi_feed_target_context(
            conn, project_id, area_id, pitch_id, pitch_number, feed_target_id
        )
        assigned = conn.execute(
            "SELECT model_variant, model_variants FROM yamazumi_elements WHERE pitch_id=?",
            (pitch_id,),
        ).fetchall()
        if status != "Active" and assigned:
            raise ValueError("Move work out of this pitch before changing it to Open or Blocked.")
        used_variants = {
            variant
            for row in assigned
            for variant in parse_yamazumi_model_variants(row["model_variants"], row["model_variant"])
        }
        missing_used = used_variants - set(variants)
        if missing_used:
            raise ValueError(
                "This pitch still contains work for: "
                + ", ".join(sorted(missing_used))
                + ". Move or retag that work first."
            )
        try:
            conn.execute(
                """UPDATE yamazumi_pitches
                   SET pitch_number=?, pitch_name=?, status=?, model_variants=?, pitch_type=?,
                       feeds_into_pitch_id=?, updated_at=?
                   WHERE id=? AND project_id=? AND area_id=?""",
                (
                    pitch_number,
                    str(values.get("pitch_name") or "").strip(),
                    status,
                    json.dumps(variants),
                    pitch_type,
                    feed_target_id,
                    now_iso(),
                    pitch_id,
                    project_id,
                    area_id,
                ),
            )
            _validate_yamazumi_pitch_feeds(conn, project_id, area_id)
            _validate_yamazumi_pitch_conflict_progress(
                conn,
                project_id,
                str(existing["scenario_id"]),
                before_conflicts,
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"Pitch address {pitch_number} already exists in this planning scenario."
            ) from exc

def update_yamazumi_element(project_id: str, area_id: str, element_id: str, values: dict) -> None:
    """Update one work element from an interactive pitch card."""
    description = str(values.get("description") or "").strip()
    if not description:
        raise ValueError("Work description is required.")
    try:
        time_s = float(values.get("time_s") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Work-element time must be a number.") from exc
    if time_s < 0:
        raise ValueError("Work-element time cannot be negative.")
    pitch_id = str(values.get("pitch_id") or "").strip() or None
    raw_variants = (
        values.get("model_variants")
        if "model_variants" in values
        else values.get("model_variant") or "Base"
    )
    model_variants = parse_yamazumi_model_variants(raw_variants, fallback=None)
    if not model_variants:
        raise ValueError("Choose at least one model variant for the work element.")
    primary_variant = model_variants[0]
    work_type = str(values.get("work_type") or "Cycle").strip().title()
    if work_type not in {"Cycle", "Periodic", "Fluctuation"}:
        raise ValueError("Work type must be Cycle, Periodic, or Fluctuation.")
    with connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM yamazumi_elements WHERE id=? AND project_id=? AND area_id=?",
            (element_id, project_id, area_id),
        ).fetchone()
        if not existing:
            raise ValueError("That work element no longer exists.")
        if pitch_id:
            destination = conn.execute(
                """SELECT model_variants FROM yamazumi_pitches
                   WHERE id=? AND project_id=? AND area_id=? AND status='Active'""",
                (pitch_id, project_id, area_id),
            ).fetchone()
            if not destination:
                raise ValueError("Work can only be assigned to an Active pitch.")
            destination_variants = set(parse_yamazumi_model_variants(destination[0], fallback=None))
            missing_variants = set(model_variants) - destination_variants
            if missing_variants:
                raise ValueError(
                    "Enable these model variants on the destination pitch first: "
                    + ", ".join(sorted(missing_variants))
                    + "."
                )
        conn.execute(
            """UPDATE yamazumi_elements
               SET pitch_id=?, model_variant=?, model_variants=?, work_type=?, description=?, time_s=?,
                   work_region=?, process_sync_status='Needs IE review', updated_at=?
               WHERE id=? AND project_id=? AND area_id=?""",
            (
                pitch_id,
                primary_variant,
                json.dumps(model_variants),
                work_type,
                description,
                time_s,
                str(values.get("work_region") or "None").strip(),
                now_iso(),
                element_id,
                project_id,
                area_id,
            ),
        )

def _yamazumi_element_delete_impact(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    area_id: str,
    element_id: str,
) -> dict[str, object]:
    row = conn.execute(
        """SELECT element.id AS element_id, element.description,
                  element.pitch_id, pitch.pitch_number, pitch.pitch_name,
                  element.process_element_id,
                  process.operation AS process_operation,
                  CASE WHEN process.id IS NULL THEN 0 ELSE 1 END AS process_step_exists,
                  (SELECT COUNT(*) FROM work_element_material_groups material_group
                   WHERE material_group.yamazumi_element_id=element.id)
                    AS legacy_material_group_count,
                  (SELECT COUNT(*)
                   FROM work_element_material_options material_option
                   JOIN work_element_material_groups material_group
                     ON material_group.id=material_option.group_id
                   WHERE material_group.yamazumi_element_id=element.id)
                    AS legacy_material_option_count
           FROM yamazumi_elements element
           JOIN yamazumi_areas area ON area.id=element.area_id
           LEFT JOIN yamazumi_pitches pitch ON pitch.id=element.pitch_id
           LEFT JOIN work_elements process
             ON process.id=element.process_element_id
            AND process.project_id=element.project_id
            AND process.scenario_id=area.scenario_id
           WHERE element.id=? AND element.project_id=? AND element.area_id=?
             AND area.project_id=? AND area.scenario_id=?""",
        (element_id, project_id, area_id, project_id, scenario_id),
    ).fetchone()
    if not row:
        raise ValueError(
            "That Yamazumi work element no longer exists in this planning scenario."
        )
    impact = dict(row)
    impact["process_step_exists"] = bool(impact["process_step_exists"])
    return impact

def yamazumi_element_delete_impact(
    project_id: str, scenario_id: str, area_id: str, element_id: str
) -> dict[str, object]:
    """Describe the persisted effects of deleting one scenario-owned work element."""
    with connection() as conn:
        return _yamazumi_element_delete_impact(
            conn, project_id, scenario_id, area_id, element_id
        )

def delete_yamazumi_element(
    project_id: str,
    scenario_or_area_id: str,
    area_or_element_id: str,
    element_id: str | None = None,
    *,
    scenario_id: str | None = None,
    audit_editor_name: str | None = None,
    audit_details: dict | None = None,
) -> dict[str, object]:
    """Delete one scenario-owned Yamazumi element and return its actual impact.

    Accept both the scenario-first store API and the established interactive-board
    call shape so the delete and its optional audit evidence share one transaction.
    """
    if element_id is None:
        area_id = scenario_or_area_id
        element_id = area_or_element_id
        resolved_scenario_id = scenario_id
    else:
        resolved_scenario_id = scenario_or_area_id
        area_id = area_or_element_id
        if scenario_id is not None and scenario_id != resolved_scenario_id:
            raise ValueError("The requested planning scenario does not match the delete target.")
    editor_name = None if audit_editor_name is None else audit_editor_name.strip()
    if audit_editor_name is not None and not editor_name:
        raise ValueError("Enter the Current editor before deleting a work element.")
    with connection() as conn:
        if resolved_scenario_id is None:
            area = conn.execute(
                "SELECT scenario_id FROM yamazumi_areas WHERE id=? AND project_id=?",
                (area_id, project_id),
            ).fetchone()
            if not area:
                raise ValueError("That Yamazumi area no longer exists in this project.")
            resolved_scenario_id = str(area["scenario_id"])
        impact = _yamazumi_element_delete_impact(
            conn, project_id, resolved_scenario_id, area_id, element_id
        )
        deleted = conn.execute(
            "DELETE FROM yamazumi_elements WHERE id=? AND project_id=? AND area_id=?",
            (element_id, project_id, area_id),
        ).rowcount
        if deleted != 1:
            raise ValueError(
                "That Yamazumi work element changed before it could be deleted."
            )
        if editor_name is not None:
            record_audit_event(
                project_id,
                "Yamazumi elements",
                "Delete from interactive board",
                1,
                editor_name,
                {
                    **(audit_details or {}),
                    "scenario_id": resolved_scenario_id,
                    "area_id": area_id,
                    **impact,
                },
                _conn=conn,
            )
        return impact


def delete_yamazumi_elements(
    project_id: str,
    scenario_id: str,
    element_ids: list[str],
    *,
    audit_editor_name: str,
) -> dict[str, object]:
    """Delete selected scenario-owned work elements in one audited transaction."""
    normalized_ids = list(dict.fromkeys(
        str(value).strip() for value in element_ids if str(value).strip()
    ))
    if not normalized_ids:
        raise ValueError("Select at least one Yamazumi work element to delete.")
    editor_name = str(audit_editor_name or "").strip()
    if not editor_name:
        raise ValueError("Enter the Current editor before deleting work elements.")
    placeholders = ",".join("?" for _ in normalized_ids)
    with connection() as conn:
        targets = conn.execute(
            f"""SELECT element.id, element.area_id
                 FROM yamazumi_elements element
                 JOIN yamazumi_areas area ON area.id=element.area_id
                 WHERE element.project_id=? AND area.scenario_id=?
                   AND element.id IN ({placeholders})""",
            (project_id, scenario_id, *normalized_ids),
        ).fetchall()
        target_by_id = {str(row["id"]): row for row in targets}
        missing_ids = [
            element_id for element_id in normalized_ids
            if element_id not in target_by_id
        ]
        if missing_ids:
            raise ValueError(
                "One or more selected Yamazumi work elements no longer exist in "
                "this planning scenario. No work elements were deleted."
            )
        impacts = [
            _yamazumi_element_delete_impact(
                conn,
                project_id,
                scenario_id,
                str(target_by_id[element_id]["area_id"]),
                element_id,
            )
            for element_id in normalized_ids
        ]
        deleted = conn.execute(
            f"""DELETE FROM yamazumi_elements
                 WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *normalized_ids),
        ).rowcount
        if deleted != len(normalized_ids):
            raise ValueError(
                "The selected Yamazumi work elements changed before they could be "
                "deleted. No work elements were deleted."
            )
        record_audit_event(
            project_id,
            "Yamazumi elements",
            "Bulk delete",
            deleted,
            editor_name,
            {"scenario_id": scenario_id, "elements": impacts},
            _conn=conn,
        )
    return {"deleted_count": deleted, "elements": impacts}


def delete_yamazumi_pitch(
    project_id: str,
    area_id: str,
    pitch_id: str,
    *,
    scenario_id: str | None = None,
    audit_editor_name: str | None = None,
    audit_details: dict | None = None,
) -> int:
    """Delete one pitch and return its work elements to the unassigned pool."""
    editor_name = None if audit_editor_name is None else audit_editor_name.strip()
    if audit_editor_name is not None and not editor_name:
        raise ValueError("Enter the Current editor before deleting a pitch.")
    timestamp = now_iso()
    with connection() as conn:
        params: list[object] = [pitch_id, project_id, area_id]
        scenario_clause = ""
        if scenario_id is not None:
            scenario_clause = " AND area.scenario_id=?"
            params.append(scenario_id)
        existing = conn.execute(
            f"""SELECT pitch.id, pitch.pitch_number, pitch.pitch_name, area.scenario_id
                FROM yamazumi_pitches pitch
                JOIN yamazumi_areas area ON area.id=pitch.area_id
                WHERE pitch.id=? AND pitch.project_id=? AND pitch.area_id=?
                {scenario_clause}""",
            tuple(params),
        ).fetchone()
        if not existing:
            raise ValueError("That pitch is no longer available in the active scenario.")
        _raise_yamazumi_pitch_reference_blockers(
            _yamazumi_pitch_reference_blockers(
                conn, project_id, area_id, {str(pitch_id)}
            )
        )
        moved = conn.execute(
            "SELECT COUNT(*) FROM yamazumi_elements WHERE pitch_id=?", (pitch_id,)
        ).fetchone()[0]
        conn.execute(
            """UPDATE yamazumi_elements
               SET pitch_id=NULL, process_sync_status='Needs IE review', updated_at=?
               WHERE pitch_id=?""",
            (timestamp, pitch_id),
        )
        conn.execute(
            "DELETE FROM yamazumi_pitches WHERE id=? AND project_id=? AND area_id=?",
            (pitch_id, project_id, area_id),
        )
        if editor_name is not None:
            details = {
                **(audit_details or {}),
                "area_id": area_id,
                "scenario_id": str(existing["scenario_id"]),
                "pitch_id": pitch_id,
                "pitch_number": str(existing["pitch_number"] or ""),
                "pitch_name": str(existing["pitch_name"] or ""),
                "elements_unassigned": int(moved),
            }
            record_audit_event(
                project_id,
                "Yamazumi pitches",
                "Delete from interactive board",
                1,
                editor_name,
                details,
                _conn=conn,
            )
    return int(moved)


def _prepare_yamazumi_pitch_move(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    source_area_id: str,
    target_area_id: str,
    pitch_ids: list[str],
) -> dict:
    """Validate a same-scenario pitch move without changing persisted records."""
    normalized_ids = list(dict.fromkeys(
        str(pitch_id).strip() for pitch_id in pitch_ids if str(pitch_id).strip()
    ))
    if not normalized_ids:
        raise ValueError("Select at least one pitch to move.")
    if source_area_id == target_area_id:
        raise ValueError("Choose a different destination Yamazumi area.")

    area_rows = conn.execute(
        """SELECT id, name, scenario_id FROM yamazumi_areas
           WHERE project_id=? AND id IN (?, ?)""",
        (project_id, source_area_id, target_area_id),
    ).fetchall()
    area_by_id = {str(row["id"]): row for row in area_rows}
    source = area_by_id.get(source_area_id)
    target = area_by_id.get(target_area_id)
    if not source:
        raise ValueError("The source Yamazumi area no longer exists.")
    if not target:
        raise ValueError("The destination Yamazumi area no longer exists.")
    if str(source["scenario_id"] or "") != scenario_id:
        raise ValueError("The source Yamazumi area is not in the active planning scenario.")
    if str(target["scenario_id"] or "") != scenario_id:
        raise ValueError(
            "Pitches can only be moved between Yamazumi areas in the active planning scenario."
        )

    placeholders = ",".join("?" for _ in normalized_ids)
    selected_rows = [
        dict(row)
        for row in conn.execute(
            f"""SELECT id, pitch_number, pitch_name, pitch_type, status,
                       feeds_into_pitch_id, sequence
                FROM yamazumi_pitches
                WHERE project_id=? AND area_id=? AND id IN ({placeholders})
                ORDER BY sequence, pitch_number COLLATE NOCASE, id""",
            (project_id, source_area_id, *normalized_ids),
        ).fetchall()
    ]
    selected_id_set = {str(row["id"]) for row in selected_rows}
    missing_ids = [pitch_id for pitch_id in normalized_ids if pitch_id not in selected_id_set]
    if missing_ids:
        raise ValueError(
            "One or more selected pitches no longer exist in the source Yamazumi area."
        )

    target_numbers = {
        str(row["pitch_number"] or "").strip().casefold(): dict(row)
        for row in conn.execute(
            """SELECT id, pitch_number, pitch_name FROM yamazumi_pitches
               WHERE project_id=? AND area_id=?""",
            (project_id, target_area_id),
        ).fetchall()
    }
    address_conflicts = []
    for row in selected_rows:
        number_key = str(row.get("pitch_number") or "").strip().casefold()
        conflict = target_numbers.get(number_key)
        if conflict:
            address_conflicts.append({
                "pitch_id": str(row["id"]),
                "pitch_label": yamazumi_pitch_label(
                    row.get("pitch_number"), row.get("pitch_name")
                ),
                "conflicting_pitch_id": str(conflict["id"]),
                "conflicting_pitch_label": yamazumi_pitch_label(
                    conflict.get("pitch_number"), conflict.get("pitch_name")
                ),
            })

    relationship_rows = conn.execute(
        f"""SELECT source.id AS source_pitch_id,
                   source.pitch_number AS source_pitch_number,
                   source.pitch_name AS source_pitch_name,
                   source.feeds_into_pitch_id AS target_pitch_id,
                   target.pitch_number AS target_pitch_number,
                   target.pitch_name AS target_pitch_name
            FROM yamazumi_pitches source
            LEFT JOIN yamazumi_pitches target
              ON target.id=source.feeds_into_pitch_id
            WHERE source.project_id=?
              AND (source.area_id=? OR source.feeds_into_pitch_id IN ({placeholders}))
              AND source.feeds_into_pitch_id IS NOT NULL""",
        (project_id, source_area_id, *normalized_ids),
    ).fetchall()
    feed_blockers = []
    for row in relationship_rows:
        source_pitch_id = str(row["source_pitch_id"])
        target_pitch_id = str(row["target_pitch_id"] or "")
        source_moves = source_pitch_id in selected_id_set
        target_moves = target_pitch_id in selected_id_set
        if source_moves == target_moves:
            continue
        feed_blockers.append({
            "source_pitch_id": source_pitch_id,
            "source_pitch_label": yamazumi_pitch_label(
                row["source_pitch_number"], row["source_pitch_name"]
            ),
            "target_pitch_id": target_pitch_id,
            "target_pitch_label": yamazumi_pitch_label(
                row["target_pitch_number"], row["target_pitch_name"]
            ),
        })

    element_rows = [
        dict(row)
        for row in conn.execute(
            f"""SELECT id, pitch_id, process_element_id
                FROM yamazumi_elements
                WHERE project_id=? AND area_id=? AND pitch_id IN ({placeholders})""",
            (project_id, source_area_id, *normalized_ids),
        ).fetchall()
    ]
    assigned_count = len(element_rows)
    linked_process_count = sum(
        bool(str(row.get("process_element_id") or "").strip())
        for row in element_rows
    )
    return {
        "source_area_id": source_area_id,
        "source_area_name": str(source["name"]),
        "target_area_id": target_area_id,
        "target_area_name": str(target["name"]),
        "scenario_id": scenario_id,
        "pitches": selected_rows,
        "pitch_ids": [str(row["id"]) for row in selected_rows],
        "assigned_element_count": assigned_count,
        "linked_process_count": linked_process_count,
        "feed_blockers": feed_blockers,
        "address_conflicts": address_conflicts,
        "ready": not feed_blockers and not address_conflicts,
    }


def preview_yamazumi_pitch_move(
    project_id: str,
    scenario_id: str,
    source_area_id: str,
    target_area_id: str,
    pitch_ids: list[str],
) -> dict:
    """Return a no-write preflight for moving pitches between scenario areas."""
    with connection() as conn:
        return _prepare_yamazumi_pitch_move(
            conn,
            project_id,
            scenario_id,
            source_area_id,
            target_area_id,
            pitch_ids,
        )


def move_yamazumi_pitches(
    project_id: str,
    scenario_id: str,
    source_area_id: str,
    target_area_id: str,
    pitch_ids: list[str],
    *,
    editor_name: str,
) -> dict:
    """Move pitches and their assigned work to another area atomically."""
    normalized_editor = str(editor_name or "").strip()
    if not normalized_editor:
        raise ValueError("Enter the Current editor before moving pitches.")
    timestamp = now_iso()
    with connection() as conn:
        plan = _prepare_yamazumi_pitch_move(
            conn,
            project_id,
            scenario_id,
            source_area_id,
            target_area_id,
            pitch_ids,
        )
        if plan["address_conflicts"]:
            labels = ", ".join(
                conflict["pitch_label"] for conflict in plan["address_conflicts"]
            )
            raise ValueError(
                f"The destination Yamazumi area already contains these pitch addresses: {labels}."
            )
        if plan["feed_blockers"]:
            relationships = ", ".join(
                f"{row['source_pitch_label']} → {row['target_pitch_label']}"
                for row in plan["feed_blockers"]
            )
            raise ValueError(
                "Move every pitch in each feed relationship together, or re-point the "
                f"relationship before moving: {relationships}."
            )

        next_sequence = int(conn.execute(
            """SELECT COALESCE(MAX(sequence), 0) FROM yamazumi_pitches
               WHERE project_id=? AND area_id=?""",
            (project_id, target_area_id),
        ).fetchone()[0] or 0)
        for pitch in plan["pitches"]:
            next_sequence += 10
            conn.execute(
                """UPDATE yamazumi_pitches
                   SET area_id=?, sequence=?, updated_at=?
                   WHERE id=? AND project_id=? AND area_id=?""",
                (
                    target_area_id,
                    next_sequence,
                    timestamp,
                    str(pitch["id"]),
                    project_id,
                    source_area_id,
                ),
            )

        placeholders = ",".join("?" for _ in plan["pitch_ids"])
        moved_elements = conn.execute(
            f"""UPDATE yamazumi_elements
                SET area_id=?, process_sync_status='Needs IE review', updated_at=?
                WHERE project_id=? AND area_id=?
                  AND pitch_id IN ({placeholders})""",
            (
                target_area_id,
                timestamp,
                project_id,
                source_area_id,
                *plan["pitch_ids"],
            ),
        ).rowcount
        if moved_elements != plan["assigned_element_count"]:
            raise ValueError(
                "The assigned work changed before the pitches could be moved. No pitches were moved."
            )

        _validate_yamazumi_pitch_feeds(conn, project_id, source_area_id)
        _validate_yamazumi_pitch_feeds(conn, project_id, target_area_id)
        _validate_yamazumi_scenario_pitch_addresses(conn, project_id, scenario_id)
        audit_details = {
            "scenario_id": scenario_id,
            "source_area_id": source_area_id,
            "source_area_name": plan["source_area_name"],
            "target_area_id": target_area_id,
            "target_area_name": plan["target_area_name"],
            "pitches": [
                {
                    "id": str(row["id"]),
                    "pitch_number": str(row.get("pitch_number") or ""),
                    "pitch_name": str(row.get("pitch_name") or ""),
                }
                for row in plan["pitches"]
            ],
            "work_elements_moved": int(moved_elements),
            "linked_process_steps_marked_for_review": int(
                plan["linked_process_count"]
            ),
        }
        record_audit_event(
            project_id,
            "Yamazumi pitches",
            "Move to another area",
            len(plan["pitch_ids"]),
            normalized_editor,
            audit_details,
            _conn=conn,
        )
    return {
        **audit_details,
        "pitch_count": len(plan["pitch_ids"]),
        "element_count": int(moved_elements),
    }

def replace_yamazumi_pitches(project_id: str, area_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "pitch_number", "pitch_name", "status", "sequence", "model_variants", "pitch_type"}
    if not required.issubset(edited.columns):
        raise ValueError("The pitch table is missing required columns.")
    records = edited.to_dict("records")
    numbers = [str(row.get("pitch_number") or "").strip() for row in records]
    if any(not number for number in numbers):
        raise ValueError("Every pitch needs an address/number.")
    if len({number.casefold() for number in numbers}) != len(numbers):
        raise ValueError("Pitch addresses must be unique across the planning scenario.")
    allowed = {"Active", "Blocked", "Open"}
    timestamp = now_iso()
    with connection() as conn:
        area = conn.execute(
            "SELECT scenario_id FROM yamazumi_areas WHERE id=? AND project_id=?",
            (area_id, project_id),
        ).fetchone()
        if not area:
            raise ValueError("That Yamazumi area no longer exists.")
        before_conflicts = _yamazumi_pitch_address_conflict_rows(
            conn, project_id, str(area["scenario_id"])
        )
        existing_rows = conn.execute(
            """SELECT id, feeds_into_pitch_id FROM yamazumi_pitches
               WHERE project_id=? AND area_id=?""",
            (project_id, area_id),
        ).fetchall()
        existing = {str(row["id"]) for row in existing_rows}
        existing_targets = {
            str(row["id"]): str(row["feeds_into_pitch_id"] or "").strip() or None
            for row in existing_rows
        }
        incoming_ids = {
            str(row.get("id") or "").strip()
            for row in records
            if str(row.get("id") or "").strip()
        }
        removed = existing - incoming_ids
        if removed:
            _raise_yamazumi_pitch_reference_blockers(
                _yamazumi_pitch_reference_blockers(
                    conn, project_id, area_id, removed
                )
            )
            placeholders = ",".join("?" for _ in removed)
            conn.execute(
                f"UPDATE yamazumi_pitches SET feeds_into_pitch_id=NULL WHERE id IN ({placeholders})",
                tuple(removed),
            )
            conn.execute(
                f"""UPDATE yamazumi_elements
                    SET pitch_id=NULL, process_sync_status='Needs IE review', updated_at=?
                    WHERE pitch_id IN ({placeholders})""",
                (timestamp, *removed),
            )
            conn.execute(
                f"DELETE FROM yamazumi_pitches WHERE id IN ({placeholders})",
                tuple(removed),
            )
        staged_targets: dict[str, str | None] = {}
        for index, row in enumerate(records, start=1):
            pitch_id = str(row.get("id") or "").strip() or str(uuid4())
            elsewhere = conn.execute(
                """SELECT 1 FROM yamazumi_pitches
                   WHERE id=? AND (project_id<>? OR area_id<>?)""",
                (pitch_id, project_id, area_id),
            ).fetchone()
            if elsewhere:
                raise ValueError("A pitch row does not belong to this Yamazumi area.")
            _validate_yamazumi_pitch_address_available(
                conn,
                project_id,
                area_id,
                numbers[index - 1],
                exclude_pitch_id=pitch_id,
            )
            status = str(row.get("status") or "Active").title()
            if status not in allowed:
                raise ValueError("Pitch status must be Active, Blocked, or Open.")
            pitch_type = str(row.get("pitch_type") or "Pitch").strip().title()
            if pitch_type not in YAMAZUMI_PITCH_TYPES:
                raise ValueError("Choose a valid pitch type for every pitch.")
            raw_target = (
                row.get("feeds_into_pitch_id")
                if "feeds_into_pitch_id" in edited.columns
                else existing_targets.get(pitch_id)
            )
            feed_target_id = _normalize_yamazumi_feed_target(
                pitch_type,
                raw_target,
                require_target=True,
                pitch_label=numbers[index - 1],
            )
            if status != "Active":
                assigned_count = conn.execute(
                    "SELECT COUNT(*) FROM yamazumi_elements WHERE pitch_id=?", (pitch_id,)
                ).fetchone()[0]
                if assigned_count:
                    raise ValueError(
                        f"Move work out of pitch {numbers[index - 1]} before changing it to {status}."
                    )
            raw_variants = row.get("model_variants") or []
            variants = raw_variants if isinstance(raw_variants, list) else json.loads(str(raw_variants) or "[]")
            variants = list(dict.fromkeys(str(value).strip() for value in variants if str(value).strip()))
            if not variants:
                raise ValueError(f"Choose at least one model variant for pitch {numbers[index - 1]}.")
            used_variants = {
                variant
                for used in conn.execute(
                    "SELECT model_variant, model_variants FROM yamazumi_elements WHERE pitch_id=?",
                    (pitch_id,),
                ).fetchall()
                for variant in parse_yamazumi_model_variants(
                    used["model_variants"], used["model_variant"]
                )
            }
            missing_used = used_variants - set(variants)
            if missing_used:
                raise ValueError(
                    f"Pitch {numbers[index - 1]} still contains work for: {', '.join(sorted(missing_used))}. Move or retag that work first."
                )
            staged_targets[pitch_id] = feed_target_id
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status, sequence,
                    model_variants, pitch_type, feeds_into_pitch_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                   ON CONFLICT(id) DO UPDATE SET pitch_number=excluded.pitch_number,
                   pitch_name=excluded.pitch_name, status=excluded.status,
                   sequence=excluded.sequence, model_variants=excluded.model_variants,
                   pitch_type=excluded.pitch_type,
                   feeds_into_pitch_id=NULL,
                   updated_at=excluded.updated_at""",
                (pitch_id, project_id, area_id, numbers[index - 1], str(row.get("pitch_name") or "").strip(),
                 status, int(row.get("sequence") or index * 10), json.dumps(variants), pitch_type, timestamp),
            )
        for pitch_id, feed_target_id in staged_targets.items():
            source = conn.execute(
                "SELECT pitch_number, pitch_name FROM yamazumi_pitches WHERE id=?",
                (pitch_id,),
            ).fetchone()
            _validate_yamazumi_feed_target_context(
                conn,
                project_id,
                area_id,
                pitch_id,
                yamazumi_pitch_label(source["pitch_number"], source["pitch_name"]),
                feed_target_id,
            )
            conn.execute(
                "UPDATE yamazumi_pitches SET feeds_into_pitch_id=? WHERE id=?",
                (feed_target_id, pitch_id),
            )
        _validate_yamazumi_pitch_feeds(conn, project_id, area_id)
        _validate_yamazumi_pitch_conflict_progress(
            conn,
            project_id,
            str(area["scenario_id"]),
            before_conflicts,
        )
    return len(records)

def yamazumi_pitch_address_suggestion(project_id: str, area_id: str) -> dict:
    """Return project and Fishbone-aware defaults for creating pitch addresses."""
    section_walk = assembly_section_walk_order(project_id)
    with connection() as conn:
        area = conn.execute(
            """SELECT area.id, area.name, area.scenario_id, area.section_id,
                      project.yamazumi_line_code
               FROM yamazumi_areas area
               JOIN projects project ON project.id=area.project_id
               WHERE area.id=? AND area.project_id=?""",
            (area_id, project_id),
        ).fetchone()
        if not area:
            raise ValueError("That Yamazumi area no longer exists.")
        pitch_rows = conn.execute(
            """SELECT pitch.pitch_number, linked_area.section_id, linked_area.name,
                      linked_area.scenario_id
               FROM yamazumi_pitches pitch
               JOIN yamazumi_areas linked_area ON linked_area.id=pitch.area_id
               WHERE pitch.project_id=?""",
            (project_id,),
        ).fetchall()

    parsed_rows = [
        (row, parse_guided_yamazumi_pitch_address(row["pitch_number"]))
        for row in pitch_rows
    ]
    parsed_rows = [(row, parsed) for row, parsed in parsed_rows if parsed]
    section_id = str(area["section_id"] or "").strip() or None

    known_by_section: dict[str, set[str]] = {}
    for row, parsed in parsed_rows:
        linked_section_id = str(row["section_id"] or "").strip()
        if linked_section_id:
            known_by_section.setdefault(linked_section_id, set()).add(
                parsed.section_code
            )

    assigned_codes: set[str] = {
        next(iter(codes))
        for codes in known_by_section.values()
        if len(codes) == 1
    }
    section_code = ""
    if section_id and len(known_by_section.get(section_id, set())) == 1:
        section_code = next(iter(known_by_section[section_id]))
    elif section_id and not section_walk.empty:
        for _, section in section_walk.iterrows():
            walk_section_id = str(section["id"])
            known_codes = known_by_section.get(walk_section_id, set())
            if len(known_codes) == 1:
                candidate = next(iter(known_codes))
            else:
                candidate = suggest_yamazumi_section_code(
                    section.get("name"), assigned_codes
                )
            assigned_codes.add(candidate)
            if walk_section_id == section_id:
                section_code = candidate
                break
    if not section_code:
        matching_unlinked_codes = {
            parsed.section_code
            for row, parsed in parsed_rows
            if not str(row["section_id"] or "").strip()
            and str(row["name"] or "").strip().casefold()
            == str(area["name"] or "").strip().casefold()
        }
        section_code = (
            next(iter(matching_unlinked_codes))
            if len(matching_unlinked_codes) == 1
            else suggest_yamazumi_section_code(area["name"], assigned_codes)
        )

    line_code = normalize_yamazumi_line_code(
        area["yamazumi_line_code"], allow_blank=True
    )
    matching_numbers = [
        parsed.number
        for row, parsed in parsed_rows
        if str(row["scenario_id"]) == str(area["scenario_id"])
        and parsed.line_code == line_code
        and parsed.section_code == section_code
    ]
    next_number = max(matching_numbers, default=0) + 1
    suggested_address = (
        format_yamazumi_pitch_address(line_code, section_code, next_number)
        if line_code
        else ""
    )
    return {
        "line_code": line_code,
        "section_code": section_code,
        "next_number": next_number,
        "suggested_address": suggested_address,
    }

def generate_yamazumi_pitch_range(
    project_id: str,
    area_id: str,
    first_address: str,
    last_address: str,
    number_mode: str = "All numbers",
    status: str = "Active",
    model_variants: list[str] | None = None,
    pitch_type: str = "Pitch",
    feeds_into_pitch_id: str | None = None,
    project_line_code: str | None = None,
) -> tuple[int, list[str]]:
    """Generate physical pitch addresses between matching numeric-suffix endpoints."""
    import re

    first = str(first_address or "").strip()
    last = str(last_address or "").strip()
    first_match = re.match(r"^(.*?)(\d+)$", first)
    last_match = re.match(r"^(.*?)(\d+)$", last)
    if not first_match or not last_match:
        raise ValueError("First and last pitch addresses must end in a number.")
    if first_match.group(1) != last_match.group(1):
        raise ValueError("First and last pitch addresses must use the same prefix.")
    start, end = int(first_match.group(2)), int(last_match.group(2))
    if end < start:
        raise ValueError("The last pitch number must be greater than or equal to the first.")
    if number_mode not in {"All numbers", "Odd only", "Even only"}:
        raise ValueError("Choose All numbers, Odd only, or Even only.")
    status = str(status or "Active").title()
    if status not in {"Active", "Blocked", "Open"}:
        raise ValueError("Pitch status must be Active, Blocked, or Open.")
    pitch_type = str(pitch_type or "Pitch").strip().title()
    if pitch_type not in YAMAZUMI_PITCH_TYPES:
        raise ValueError("Choose a valid pitch type.")
    feed_target_id = _normalize_yamazumi_feed_target(
        pitch_type,
        feeds_into_pitch_id,
        require_target=True,
        pitch_label=f"range {first}–{last}",
    )
    normalized_project_line_code = (
        normalize_yamazumi_line_code(project_line_code)
        if project_line_code is not None
        else None
    )
    prefix = first_match.group(1)
    width = max(3, len(first_match.group(2)))
    values = list(range(start, end + 1))
    if number_mode == "Odd only":
        values = [value for value in values if value % 2 == 1]
    elif number_mode == "Even only":
        values = [value for value in values if value % 2 == 0]
    if not values:
        raise ValueError("That range contains no pitch numbers for the selected numbering option.")
    timestamp = now_iso()
    variants = list(dict.fromkeys(str(value).strip() for value in (model_variants or ["Base"]) if str(value).strip()))
    if not variants:
        raise ValueError("Choose at least one model variant for the generated pitches.")
    with connection() as conn:
        area = conn.execute(
            "SELECT scenario_id FROM yamazumi_areas WHERE id=? AND project_id=?",
            (area_id, project_id),
        ).fetchone()
        if not area:
            raise ValueError("That Yamazumi area no longer exists.")
        scenario_id = str(area["scenario_id"])
        if normalized_project_line_code is not None:
            conn.execute(
                "UPDATE projects SET yamazumi_line_code=?, updated_at=? WHERE id=?",
                (normalized_project_line_code, timestamp, project_id),
            )
        _validate_yamazumi_scenario_pitch_addresses(
            conn, project_id, scenario_id
        )
        _validate_yamazumi_feed_target_context(
            conn,
            project_id,
            area_id,
            "",
            f"range {first}–{last}",
            feed_target_id,
        )
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM yamazumi_pitches WHERE project_id=? AND area_id=?",
            (project_id, area_id),
        ).fetchone()[0]
        existing_addresses = {
            str(row["pitch_number"]).strip().casefold()
            for row in conn.execute(
                """SELECT pitch.pitch_number
                   FROM yamazumi_pitches pitch
                   JOIN yamazumi_areas area ON area.id=pitch.area_id
                   WHERE pitch.project_id=? AND area.scenario_id=?""",
                (project_id, scenario_id),
            ).fetchall()
        }
        created = 0
        skipped: list[str] = []
        for offset, value in enumerate(values, start=1):
            address = f"{prefix}{value:0{width}d}"
            if address.casefold() in existing_addresses:
                skipped.append(address)
                continue
            conn.execute(
                """INSERT INTO yamazumi_pitches
                   (id, project_id, area_id, pitch_number, pitch_name, status, sequence,
                    model_variants, pitch_type, feeds_into_pitch_id, updated_at)
                   VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), project_id, area_id, address, status,
                 next_sequence + offset * 10, json.dumps(variants), pitch_type,
                 feed_target_id, timestamp),
            )
            created += 1
            existing_addresses.add(address.casefold())
        _validate_yamazumi_pitch_feeds(conn, project_id, area_id)
    return created, skipped

def replace_yamazumi_elements(project_id: str, area_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "pitch_id", "model_variants", "work_type", "description", "time_s", "work_region", "sequence"}
    if not required.issubset(edited.columns):
        raise ValueError("The Yamazumi work-element table is missing required columns.")
    records = edited.to_dict("records")
    timestamp = now_iso()
    valid_pitches = {
        str(row["id"]) for row in query(
            "SELECT id FROM yamazumi_pitches WHERE project_id=? AND area_id=? AND status='Active'",
            (project_id, area_id),
        )
    }
    with connection() as conn:
        existing = {row[0] for row in conn.execute("SELECT id FROM yamazumi_elements WHERE project_id=? AND area_id=?", (project_id, area_id))}
        kept: set[str] = set()
        for index, row in enumerate(records, start=1):
            description = str(row.get("description") or "").strip()
            if not description:
                raise ValueError("Every Yamazumi work element needs a description.")
            time_s = float(row.get("time_s") or 0)
            if time_s < 0:
                raise ValueError("Work-element time cannot be negative.")
            element_id = str(row.get("id") or "").strip() or str(uuid4())
            pitch_id = str(row.get("pitch_id") or "").strip() or None
            if pitch_id and pitch_id not in valid_pitches:
                raise ValueError("Choose an Active pitch from the selected Yamazumi area.")
            model_variants = parse_yamazumi_model_variants(
                row.get("model_variants"), fallback=None
            )
            if not model_variants:
                raise ValueError("Choose at least one model variant for every work element.")
            primary_variant = model_variants[0]
            work_type = str(row.get("work_type") or "Cycle").strip().title()
            if work_type not in {"Cycle", "Periodic", "Fluctuation"}:
                raise ValueError("Work type must be Cycle, Periodic, or Fluctuation.")
            if pitch_id:
                pitch_variants_row = conn.execute(
                    "SELECT model_variants FROM yamazumi_pitches WHERE id=?", (pitch_id,)
                ).fetchone()
                pitch_variants = set(
                    parse_yamazumi_model_variants(pitch_variants_row[0], fallback=None)
                )
                missing_variants = set(model_variants) - pitch_variants
                if missing_variants:
                    raise ValueError(
                        "Enable these model variants on the selected pitch first: "
                        + ", ".join(sorted(missing_variants))
                        + "."
                    )
            kept.add(element_id)
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, model_variant, model_variants,
                    work_type, description,
                    time_s, work_region, sequence, source, process_element_id,
                    process_sync_status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET pitch_id=excluded.pitch_id,
                    model_variant=excluded.model_variant, model_variants=excluded.model_variants,
                    work_type=excluded.work_type,
                    description=excluded.description, time_s=excluded.time_s,
                    work_region=excluded.work_region,
                    sequence=excluded.sequence, process_sync_status='Needs IE review',
                    updated_at=excluded.updated_at""",
                (element_id, project_id, area_id, pitch_id, primary_variant,
                 json.dumps(model_variants),
                 work_type, description, time_s,
                 str(row.get("work_region") or "None").strip(),
                 int(row.get("sequence") or index * 10), str(row.get("source") or "Manual"),
                 row.get("process_element_id"), str(row.get("process_sync_status") or "Needs IE review"), timestamp),
            )
        removed = existing - kept
        if removed:
            placeholders = ",".join("?" for _ in removed)
            conn.execute(f"DELETE FROM yamazumi_elements WHERE id IN ({placeholders})", tuple(removed))
    return len(records)

def move_yamazumi_element(
    project_id: str, element_id: str, pitch_id: str | None
) -> list[str]:
    """Move one linked work record and return variants added to the destination pitch."""
    timestamp = now_iso()
    enabled_variants: list[str] = []
    with connection() as conn:
        element = conn.execute(
            """SELECT model_variant, model_variants FROM yamazumi_elements
               WHERE id=? AND project_id=?""",
            (element_id, project_id),
        ).fetchone()
        if not element:
            raise ValueError("That work element no longer exists.")
        element_variants = parse_yamazumi_model_variants(
            element["model_variants"], element["model_variant"]
        )
        if pitch_id:
            destination = conn.execute(
                """SELECT id, area_id, pitch_number, pitch_name, pitch_type,
                          feeds_into_pitch_id, model_variants
                   FROM yamazumi_pitches
                   WHERE id=? AND project_id=? AND status='Active'""",
                (pitch_id, project_id),
            ).fetchone()
            if not destination:
                raise ValueError("Work can only be moved into an Active pitch.")
            destination_variants = parse_yamazumi_model_variants(
                destination["model_variants"], fallback=None
            )
            enabled_variants = [
                variant for variant in element_variants
                if variant not in destination_variants
            ]
            if enabled_variants:
                _require_yamazumi_feed_target_for_pitch_write(
                    conn, project_id, destination
                )
                conn.execute(
                    """UPDATE yamazumi_pitches SET model_variants=?, updated_at=?
                       WHERE id=? AND project_id=?""",
                    (
                        json.dumps([*destination_variants, *enabled_variants]),
                        timestamp,
                        pitch_id,
                        project_id,
                    ),
                )
        conn.execute(
            """UPDATE yamazumi_elements
               SET pitch_id=?, process_sync_status='Needs IE review', updated_at=?
               WHERE id=? AND project_id=?""",
            (pitch_id or None, timestamp, element_id, project_id),
        )
    return enabled_variants

def save_yamazumi_stack_draft(
    project_id: str,
    scenario_id: str,
    area_id: str,
    stacks: dict[str, list[str]],
) -> dict:
    """Validate and atomically persist complete centerline-outward stack order."""
    if not isinstance(stacks, dict):
        raise ValueError("The Yamazumi board draft is invalid. Undo it and try again.")
    normalized: dict[str, list[str]] = {}
    for raw_stack_id, raw_element_ids in stacks.items():
        stack_key = str(raw_stack_id or "").strip()
        if not stack_key or not isinstance(raw_element_ids, list):
            raise ValueError("Every Yamazumi draft stack needs a stable destination and order.")
        normalized[stack_key] = [str(value or "").strip() for value in raw_element_ids]
        if any(not value for value in normalized[stack_key]):
            raise ValueError("Every Yamazumi draft element needs a stable ID.")

    timestamp = now_iso()
    with connection() as conn:
        area = conn.execute(
            """SELECT id, name FROM yamazumi_areas
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (area_id, project_id, scenario_id),
        ).fetchone()
        if not area:
            raise ValueError("That Yamazumi area is not in the active planning scenario.")

        pitch_rows = conn.execute(
            """SELECT id, pitch_number, pitch_name, status, pitch_type,
                      feeds_into_pitch_id, model_variants
               FROM yamazumi_pitches
               WHERE project_id=? AND area_id=?""",
            (project_id, area_id),
        ).fetchall()
        pitches = {str(row["id"]): row for row in pitch_rows}
        element_rows = conn.execute(
            """SELECT id, pitch_id, model_variant, model_variants, description,
                      sequence, process_sync_status
               FROM yamazumi_elements
               WHERE project_id=? AND area_id=?
               ORDER BY sequence, description COLLATE NOCASE, id""",
            (project_id, area_id),
        ).fetchall()
        elements = {str(row["id"]): row for row in element_rows}

        submitted_ids = [element_id for values in normalized.values() for element_id in values]
        if len(submitted_ids) != len(set(submitted_ids)):
            raise ValueError("A Yamazumi work element appears more than once in the board draft.")
        submitted_set = set(submitted_ids)
        existing_set = set(elements)
        missing = existing_set - submitted_set
        stale = submitted_set - existing_set
        if missing or stale:
            parts = []
            if missing:
                parts.append(f"missing {len(missing)} current element(s)")
            if stale:
                parts.append(f"containing {len(stale)} stale or foreign element(s)")
            raise ValueError(
                "The Yamazumi board draft is incomplete or out of date ("
                + " and ".join(parts)
                + "). Undo it and try again."
            )

        for stack_key, element_ids in normalized.items():
            if stack_key == UNASSIGNED_STACK_ID:
                continue
            pitch = pitches.get(stack_key)
            if not pitch:
                raise ValueError(
                    "A Yamazumi draft destination is missing or belongs to another area or scenario."
                )
            if element_ids and str(pitch["status"]) != "Active":
                label = yamazumi_pitch_label(pitch["pitch_number"], pitch["pitch_name"])
                raise ValueError(f"Work can only be saved into an Active pitch; {label} is not Active.")

        current = build_stack_draft(dict(row) for row in element_rows)
        affected_stack_ids = sorted(
            stack_key
            for stack_key in set(current) | set(normalized)
            if current.get(stack_key, []) != normalized.get(stack_key, [])
        )
        desired: dict[str, tuple[str | None, int]] = {}
        for stack_key in affected_stack_ids:
            pitch_id = None if stack_key == UNASSIGNED_STACK_ID else stack_key
            for position, element_id in enumerate(normalized.get(stack_key, []), start=1):
                desired[element_id] = (pitch_id, position * 10)

        enabled_variants: dict[str, list[str]] = {}
        for stack_key in affected_stack_ids:
            if stack_key == UNASSIGNED_STACK_ID or stack_key not in pitches:
                continue
            destination = pitches[stack_key]
            destination_variants = parse_yamazumi_model_variants(
                destination["model_variants"], fallback=None
            )
            required_variants = list(dict.fromkeys(
                variant
                for element_id in normalized.get(stack_key, [])
                for variant in parse_yamazumi_model_variants(
                    elements[element_id]["model_variants"],
                    elements[element_id]["model_variant"],
                )
            ))
            missing_variants = [
                variant for variant in required_variants
                if variant not in destination_variants
            ]
            if missing_variants:
                _require_yamazumi_feed_target_for_pitch_write(
                    conn, project_id, destination
                )
                conn.execute(
                    """UPDATE yamazumi_pitches SET model_variants=?, updated_at=?
                       WHERE id=? AND project_id=? AND area_id=?""",
                    (
                        json.dumps([*destination_variants, *missing_variants]),
                        timestamp,
                        stack_key,
                        project_id,
                        area_id,
                    ),
                )
                enabled_variants[stack_key] = missing_variants

        changed_element_ids: list[str] = []
        for element_id, (pitch_id, sequence) in desired.items():
            existing = elements[element_id]
            old_pitch_id = str(existing["pitch_id"] or "").strip() or None
            if old_pitch_id == pitch_id and int(existing["sequence"]) == sequence:
                continue
            sync_status = (
                "Needs IE review"
                if old_pitch_id != pitch_id
                else str(existing["process_sync_status"] or "Needs IE review")
            )
            cursor = conn.execute(
                """UPDATE yamazumi_elements
                   SET pitch_id=?, sequence=?, process_sync_status=?, updated_at=?
                   WHERE id=? AND project_id=? AND area_id=?""",
                (
                    pitch_id, sequence, sync_status, timestamp,
                    element_id, project_id, area_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "A Yamazumi work element changed while the draft was being saved. No changes were applied."
                )
            changed_element_ids.append(element_id)

        affected_stacks = []
        for stack_key in affected_stack_ids:
            pitch = pitches.get(stack_key)
            affected_stacks.append({
                "pitch_id": stack_key,
                "pitch_address": (
                    str(pitch["pitch_number"] or "") if pitch else "Unassigned"
                ),
                "pitch_name": str(pitch["pitch_name"] or "") if pitch else "Unassigned",
                "elements": [
                    {
                        "element_id": element_id,
                        "description": str(elements[element_id]["description"] or ""),
                        "sequence": position * 10,
                    }
                    for position, element_id in enumerate(
                        normalized.get(stack_key, []), start=1
                    )
                ],
            })

    return {
        "area_id": area_id,
        "area_name": str(area["name"] or ""),
        "affected_stacks": affected_stacks,
        "enabled_variants": enabled_variants,
        "changed_element_ids": changed_element_ids,
    }

def import_yamazumi_rows(
    project_id: str,
    scenario_id: str,
    rows: pd.DataFrame,
    section_ids_by_name: dict[str, str],
    *,
    replace_existing_elements: bool = False,
    source_label: str = "Excel import",
    pitch_rows: pd.DataFrame | None = None,
) -> tuple[int, int, int]:
    required = {"Sub-Line", "Pitch_number", "Pitch_status", "Pitch_name", "Pitch_Takt_time", "Model_variant", "Work_Type", "Work_Description", "Work_Time_to_complete", "Work_region"}
    missing = required - set(rows.columns)
    if missing:
        raise ValueError(f"The Yamazumi file is missing: {', '.join(sorted(missing))}.")
    pitch_required = {
        "Sub-Line", "Pitch_number", "Pitch_status", "Pitch_name",
        "Pitch_Takt_time",
    }
    if pitch_rows is not None:
        missing_pitch_columns = pitch_required - set(pitch_rows.columns)
        if missing_pitch_columns:
            raise ValueError(
                "The Yamazumi pitch data is missing: "
                f"{', '.join(sorted(missing_pitch_columns))}."
            )
    timestamp = now_iso()
    area_ids: dict[str, str] = {}
    pitch_ids: dict[tuple[str, str], str] = {}
    prepared_pitches: list[tuple[pd.Series, str, str]] = []
    prepared_rows: list[tuple[int, pd.Series, str, str, str]] = []
    elements_added = 0
    with connection() as conn:
        scenario = conn.execute(
            "SELECT takt_time_unit, yamazumi_time_unit FROM planning_scenarios "
            "WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone()
        if not scenario:
            raise ValueError("The active planning scenario no longer exists in this project.")
        import_takt_unit = normalize_time_unit(scenario["takt_time_unit"])
        import_work_unit = normalize_time_unit(scenario["yamazumi_time_unit"])
        _validate_yamazumi_scenario_pitch_addresses(
            conn, project_id, scenario_id
        )
        pitch_sources = []
        if pitch_rows is not None:
            pitch_sources.append(pitch_rows)
        pitch_sources.append(rows)
        seen_pitch_keys: set[tuple[str, str]] = set()
        for pitch_source in pitch_sources:
            for _, pitch_row in pitch_source.iterrows():
                area_name = str(pitch_row.get("Sub-Line") or "").strip()
                pitch_number = str(pitch_row.get("Pitch_number") or "").strip()
                if not area_name or not pitch_number:
                    continue
                pitch_key = (area_name.casefold(), pitch_number.casefold())
                if pitch_key in seen_pitch_keys:
                    continue
                seen_pitch_keys.add(pitch_key)
                prepared_pitches.append((pitch_row, area_name, pitch_number))
                if area_name in area_ids:
                    continue
                takt_raw = pitch_row.get("Pitch_Takt_time")
                takt = (
                    None
                    if pd.isna(takt_raw) or str(takt_raw).strip() == ""
                    else display_to_seconds(takt_raw, import_takt_unit)
                )
                area_ids[area_name] = upsert_yamazumi_area(
                    project_id,
                    scenario_id,
                    area_name,
                    section_ids_by_name.get(area_name),
                    takt,
                    _conn=conn,
                )

        for row_position, (_, row) in enumerate(rows.iterrows(), start=1):
            area_name = str(row.get("Sub-Line") or "").strip()
            pitch_number = str(row.get("Pitch_number") or "").strip()
            description = str(row.get("Work_Description") or "").strip()
            if not area_name or not pitch_number or not description:
                continue
            prepared_rows.append(
                (row_position, row, area_name, pitch_number, description)
            )

        if replace_existing_elements:
            for area_id in dict.fromkeys(area_ids.values()):
                conn.execute(
                    "DELETE FROM yamazumi_elements WHERE project_id=? AND area_id=?",
                    (project_id, area_id),
                )
                conn.execute(
                    """UPDATE yamazumi_pitches SET feeds_into_pitch_id=NULL
                       WHERE project_id=? AND area_id=?""",
                    (project_id, area_id),
                )
                conn.execute(
                    "DELETE FROM yamazumi_pitches WHERE project_id=? AND area_id=?",
                    (project_id, area_id),
                )

        for row, area_name, pitch_number in prepared_pitches:
            area_id = area_ids[area_name]
            pitch_key = (area_id, pitch_number.casefold())
            if pitch_key not in pitch_ids:
                existing_pitch = conn.execute(
                    """SELECT id, pitch_number, pitch_type, feeds_into_pitch_id
                       FROM yamazumi_pitches
                       WHERE project_id=? AND area_id=?
                         AND TRIM(pitch_number)=TRIM(?) COLLATE NOCASE""",
                    (project_id, area_id, pitch_number),
                ).fetchone()
                if existing_pitch:
                    existing_target_id = _normalize_yamazumi_feed_target(
                        str(existing_pitch["pitch_type"] or "Pitch").title(),
                        existing_pitch["feeds_into_pitch_id"],
                        require_target=True,
                        pitch_label=pitch_number,
                    )
                    _validate_yamazumi_feed_target_context(
                        conn,
                        project_id,
                        area_id,
                        str(existing_pitch["id"]),
                        pitch_number,
                        existing_target_id,
                    )
                else:
                    _validate_yamazumi_pitch_address_available(
                        conn, project_id, area_id, pitch_number
                    )
                pitch_id = str(existing_pitch["id"]) if existing_pitch else str(uuid4())
                pitch_ids[pitch_key] = pitch_id
                status = str(row.get("Pitch_status") or "Active").strip().title()
                if status not in {"Active", "Blocked", "Open"}:
                    status = "Active"
                pitch_variants = parse_yamazumi_model_variants(
                    row.get("Model_variants", row.get("Model_variant")),
                    fallback="Base",
                )
                conn.execute(
                    """INSERT INTO yamazumi_pitches
                       (id, project_id, area_id, pitch_number, pitch_name, status,
                        sequence, model_variants, pitch_type, feeds_into_pitch_id, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pitch', NULL, ?)
                       ON CONFLICT(id) DO UPDATE SET pitch_name=excluded.pitch_name,
                       status=excluded.status, updated_at=excluded.updated_at""",
                    (pitch_id, project_id, area_id, pitch_number,
                     str(row.get("Pitch_name") or "").strip(), status,
                     len(pitch_ids) * 10, json.dumps(pitch_variants), timestamp),
                )

        for row_position, row, area_name, pitch_number, description in prepared_rows:
            area_id = area_ids[area_name]
            pitch_key = (area_id, pitch_number.casefold())
            import_pitch_id = pitch_ids[pitch_key]
            import_pitch = conn.execute(
                "SELECT status FROM yamazumi_pitches WHERE id=?", (import_pitch_id,)
            ).fetchone()
            assigned_pitch_id = (
                import_pitch_id if import_pitch and import_pitch["status"] == "Active" else None
            )
            imported_variant = str(row.get("Model_variant") or "Base").strip().title()
            conn.execute(
                """INSERT INTO yamazumi_elements
                   (id, project_id, area_id, pitch_id, model_variant, model_variants,
                    work_type, description, time_s, work_region, sequence,
                    source, process_sync_status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, 'Needs IE review', ?)""",
                (str(uuid4()), project_id, area_id, assigned_pitch_id, imported_variant,
                 json.dumps([imported_variant]),
                 str(row.get("Work_Type") or "Cycle").strip().title(), description,
                 display_to_seconds(
                     row.get("Work_Time_to_complete") or 0, import_work_unit
                 ),
                 str(row.get("Work_region") or "None").strip(),
                 row_position * 10, source_label, timestamp),
            )
            current_pitch = conn.execute(
                "SELECT model_variants FROM yamazumi_pitches WHERE id=?",
                (import_pitch_id,),
            ).fetchone()
            selected_variants = json.loads(current_pitch["model_variants"] or "[]")
            if imported_variant not in selected_variants:
                selected_variants.append(imported_variant)
                conn.execute(
                    "UPDATE yamazumi_pitches SET model_variants=? WHERE id=?",
                    (json.dumps(selected_variants), import_pitch_id),
                )
            elements_added += 1
        for area_id in set(area_ids.values()):
            _validate_yamazumi_pitch_feeds(conn, project_id, area_id)
        _validate_yamazumi_scenario_pitch_addresses(
            conn, project_id, scenario_id
        )
    return len(area_ids), len(pitch_ids), elements_added

__domain_exports__ = ['yamazumi_areas', 'yamazumi_area_link_status', 'yamazumi_pitches', 'yamazumi_elements', 'yamazumi_pitches_for_scenario', 'yamazumi_elements_for_scenario', 'yamazumi_work_regions', 'replace_yamazumi_work_regions', 'migrate_legacy_yamazumi_flags', 'rename_yamazumi_variants', 'clear_yamazumi_data', 'upsert_yamazumi_area', '_validate_yamazumi_area_link', 'update_yamazumi_settings', 'sync_yamazumi_areas_from_fishbone', 'yamazumi_pitch_label', '_yamazumi_pitch_address_conflict_rows', 'yamazumi_pitch_address_conflicts', '_yamazumi_pitch_address_owner', '_validate_yamazumi_pitch_address_available', '_validate_yamazumi_scenario_pitch_addresses', '_validate_yamazumi_pitch_conflict_progress', 'yamazumi_pitch_feed_target_status', '_normalize_yamazumi_feed_target', '_validate_yamazumi_pitch_feeds', '_validate_yamazumi_feed_target_context', '_require_yamazumi_feed_target_for_pitch_write', '_yamazumi_pitch_reference_blockers', 'yamazumi_pitch_delete_blockers', '_raise_yamazumi_pitch_reference_blockers', 'add_yamazumi_pitch', 'add_yamazumi_element', '_prepare_yamazumi_copy', 'preview_yamazumi_copy', 'copy_yamazumi_records', 'update_yamazumi_pitch', 'update_yamazumi_element', '_yamazumi_element_delete_impact', 'yamazumi_element_delete_impact', 'delete_yamazumi_element', 'delete_yamazumi_elements', 'delete_yamazumi_pitch', '_prepare_yamazumi_pitch_move', 'preview_yamazumi_pitch_move', 'move_yamazumi_pitches', 'replace_yamazumi_pitches', 'yamazumi_pitch_address_suggestion', 'generate_yamazumi_pitch_range', 'replace_yamazumi_elements', 'move_yamazumi_element', 'save_yamazumi_stack_draft', 'import_yamazumi_rows']
for _export_name in __domain_exports__:
    if callable(globals()[_export_name]):
        globals()[_export_name] = _db_core.domain_entrypoint(globals()[_export_name])
_db_core.register_domain_module(_sys.modules[__name__], __domain_exports__)
