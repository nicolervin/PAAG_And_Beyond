"""Domain persistence extracted from the historical utils.store module."""

from __future__ import annotations

import sys as _sys
from utils import db_core as _db_core
from utils.cache_store import cached_store_read

globals().update({name: value for name, value in vars(_db_core).items() if not name.startswith('__')})

@cached_store_read
def assembly_sections(project_id: str) -> pd.DataFrame:
    rows = query(
        "SELECT * FROM assembly_sections WHERE project_id = ? ORDER BY sequence, name",
        (project_id,),
    )
    if not rows:
        return pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "name": pd.Series(dtype="string"),
            "section_type": pd.Series(dtype="string"),
            "parent_id": pd.Series(dtype="string"),
            "sequence": pd.Series(dtype="int64"),
            "description": pd.Series(dtype="string"),
            "active": pd.Series(dtype="int64"),
            "grid_x": pd.Series(dtype="Int64"),
            "grid_y": pd.Series(dtype="Int64"),
            "created_at": pd.Series(dtype="string"),
            "updated_at": pd.Series(dtype="string"),
        })
    return pd.DataFrame(rows)

@cached_store_read
def assembly_section_walk_order(project_id: str) -> pd.DataFrame:
    """Return Fishbone sections in deterministic depth-first framework order."""
    sections = assembly_sections(project_id)
    if sections.empty:
        result = sections.copy()
        result["depth"] = pd.Series(dtype="Int64")
        return result

    def normalized_parent_id(value) -> str:
        if value is None or pd.isna(value):
            return ""
        return str(value).strip()

    records = {
        str(row["id"]): row.to_dict() for _, row in sections.iterrows()
    }
    children: dict[str, list[str]] = {}
    for section_id, row in records.items():
        parent_id = normalized_parent_id(row.get("parent_id"))
        children.setdefault(parent_id, []).append(section_id)
    for child_ids in children.values():
        child_ids.sort(
            key=lambda child_id: (
                int(records[child_id]["sequence"]),
                records[child_id]["name"],
            )
        )

    order: list[str] = []
    depth_by_id: dict[str, int] = {}

    def add_branch(section_id: str, depth: int) -> None:
        if section_id in depth_by_id:
            return
        depth_by_id[section_id] = depth
        order.append(section_id)
        for child_id in children.get(section_id, []):
            add_branch(child_id, depth + 1)

    root_ids = [
        section_id
        for section_id, row in records.items()
        if not normalized_parent_id(row.get("parent_id"))
        or row["section_type"] in {"Main spine", "Support Operations"}
    ]
    root_ids.sort(
        key=lambda section_id: (
            int(records[section_id]["sequence"]),
            records[section_id]["name"],
        )
    )
    for root_id in root_ids:
        add_branch(root_id, 0)
    for section_id in records:
        add_branch(section_id, 0)

    result = (
        sections.set_index(sections["id"].astype(str), drop=False)
        .loc[order]
        .reset_index(drop=True)
    )
    result["depth"] = result["id"].astype(str).map(depth_by_id).astype("Int64")
    return result

def _assembly_section_delete_rows(
    conn: sqlite3.Connection, project_id: str, section_ids: list[str]
) -> list[sqlite3.Row]:
    normalized_ids = list(dict.fromkeys(
        str(section_id).strip() for section_id in section_ids if str(section_id).strip()
    ))
    if not normalized_ids:
        raise ValueError("Select at least one Fishbone section to delete.")
    placeholders = ", ".join("?" for _ in normalized_ids)
    selected_count = conn.execute(
        f"""SELECT COUNT(*) FROM assembly_sections
            WHERE project_id=? AND id IN ({placeholders})""",
        (project_id, *normalized_ids),
    ).fetchone()[0]
    if int(selected_count) != len(normalized_ids):
        raise ValueError("One or more selected Fishbone sections no longer exist.")
    return conn.execute(
        f"""WITH RECURSIVE affected(id, name, parent_id, depth) AS (
                SELECT id, name, parent_id, 0 FROM assembly_sections
                WHERE project_id=? AND id IN ({placeholders})
                UNION
                SELECT child.id, child.name, child.parent_id, affected.depth + 1
                FROM assembly_sections child
                JOIN affected ON child.parent_id=affected.id
                WHERE child.project_id=?
            )
            SELECT id, name, MAX(depth) AS depth FROM affected
            GROUP BY id, name ORDER BY depth, name""",
        (project_id, *normalized_ids, project_id),
    ).fetchall()

def _assembly_section_target_validation(
    conn: sqlite3.Connection,
    project_id: str,
    affected_ids: list[str],
    target_section_id: str,
    active_scenario_id: str | None = None,
) -> dict:
    target_id = _catalog_text(target_section_id)
    if not target_id:
        raise ValueError("Choose an existing Fishbone section to continue this work under.")
    if target_id in affected_ids:
        raise ValueError("The target Fishbone section must be outside the deletion set.")
    target = conn.execute(
        "SELECT id, name FROM assembly_sections WHERE id=? AND project_id=?",
        (target_id, project_id),
    ).fetchone()
    if not target:
        raise ValueError("Choose an existing Fishbone section from this project.")
    active_scenario = _catalog_text(active_scenario_id) or None
    if active_scenario and not conn.execute(
        "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
        (active_scenario, project_id),
    ).fetchone():
        raise ValueError("The active planning scenario no longer exists in this project.")

    placeholders = ", ".join("?" for _ in affected_ids)
    # Yamazumi areas may now converge on the selected target; deletion merges
    # their contents per scenario instead of treating convergence as a conflict.
    conflicts: list[dict] = []
    category_conflicts: list[dict] = []
    incoming_categories = [
        dict(row)
        for row in conn.execute(
            f"""SELECT id, ebom_name, display_name
                FROM assembly_grid_categories
                WHERE project_id=? AND section_id IN ({placeholders})
                ORDER BY sequence, display_name""",
            (project_id, *affected_ids),
        ).fetchall()
    ]
    target_categories = [
        dict(row)
        for row in conn.execute(
            """SELECT id, ebom_name, display_name
               FROM assembly_grid_categories
               WHERE project_id=? AND section_id=?
               ORDER BY sequence, display_name""",
            (project_id, target_id),
        ).fetchall()
    ]
    for field, label in (
        ("ebom_name", "Official EBOM category name"),
        ("display_name", "Display name"),
    ):
        combined: list[tuple[dict, bool]] = [
            *((row, False) for row in target_categories),
            *((row, True) for row in incoming_categories),
        ]
        seen_values: dict[str, tuple[dict, bool]] = {}
        for category, is_incoming in combined:
            value = _catalog_text(category.get(field))
            key = value.casefold()
            previous = seen_values.get(key)
            if previous and (is_incoming or previous[1]):
                incoming = category if is_incoming else previous[0]
                conflicting = previous[0] if is_incoming else category
                category_conflicts.append(
                    {
                        "type": "category",
                        "field": field,
                        "field_label": label,
                        "value": value,
                        "incoming_category_id": str(incoming["id"]),
                        "incoming_category_name": str(incoming["display_name"]),
                        "conflicting_category_id": str(conflicting["id"]),
                        "conflicting_category_name": str(conflicting["display_name"]),
                    }
                )
                continue
            seen_values[key] = (category, is_incoming)
    message = ""
    if conflicts:
        first = conflicts[0]
        if int(first["target_area_count"]) > 0:
            message = (
                "The selected target section already has its own Yamazumi area. "
                "Choose a different target, or reconcile the duplicate manually in "
                "Yamazumi before deleting."
            )
        else:
            message = (
                "More than one Yamazumi area would be re-pointed to the selected target "
                "section. Choose a different target, or reconcile the duplicate manually "
                "in Yamazumi before deleting."
            )
        if str(first["scenario_id"]) != str(active_scenario or ""):
            message += (
                f" Conflict found in Rev {first['revision_label']} · "
                f"{first['scenario_name']}."
            )
    elif category_conflicts:
        first = category_conflicts[0]
        message = (
            f"Cannot continue under Fishbone section {target['name']}: incoming category "
            f"{first['incoming_category_name']} has {first['field_label']} "
            f"\"{first['value']}\" that conflicts with category "
            f"{first['conflicting_category_name']}. Choose a different target Fishbone section."
        )
    return {
        "valid": not conflicts and not category_conflicts,
        "message": message,
        "target_section_id": target_id,
        "target_section_name": str(target["name"]),
        "conflicts": [*conflicts, *category_conflicts],
        "category_conflicts": category_conflicts,
    }

def _merge_yamazumi_areas_for_section_delete(
    conn: sqlite3.Connection,
    project_id: str,
    affected_ids: list[str],
    target_section_id: str,
    timestamp: str,
) -> tuple[int, int]:
    """Move affected area contents into one target-linked area per scenario."""
    placeholders = ", ".join("?" for _ in affected_ids)
    rows = conn.execute(
        f"""SELECT id, scenario_id, section_id
            FROM yamazumi_areas
            WHERE project_id=?
              AND (section_id=? OR section_id IN ({placeholders}))
            ORDER BY CASE WHEN section_id=? THEN 0 ELSE 1 END, rowid""",
        (project_id, target_section_id, *affected_ids, target_section_id),
    ).fetchall()
    by_scenario: dict[str | None, list[sqlite3.Row]] = {}
    for row in rows:
        by_scenario.setdefault(row["scenario_id"], []).append(row)

    moved_area_count = 0
    merged_area_count = 0
    for scenario_rows in by_scenario.values():
        incoming = [
            row for row in scenario_rows if str(row["section_id"]) in affected_ids
        ]
        if not incoming:
            continue
        survivor = scenario_rows[0]
        survivor_id = str(survivor["id"])
        if str(survivor["section_id"]) in affected_ids:
            conn.execute(
                "UPDATE yamazumi_areas SET section_id=?, updated_at=? WHERE id=?",
                (target_section_id, timestamp, survivor_id),
            )
            moved_area_count += 1

        for donor in scenario_rows[1:]:
            donor_id = str(donor["id"])
            if str(donor["section_id"]) not in affected_ids:
                continue
            conn.execute(
                """DELETE FROM yamazumi_work_regions
                   WHERE area_id=? AND EXISTS (
                       SELECT 1 FROM yamazumi_work_regions target_region
                       WHERE target_region.area_id=?
                         AND target_region.name=yamazumi_work_regions.name
                   )""",
                (donor_id, survivor_id),
            )
            conn.execute(
                "UPDATE yamazumi_work_regions SET area_id=?, updated_at=? WHERE area_id=?",
                (survivor_id, timestamp, donor_id),
            )
            conn.execute(
                "UPDATE yamazumi_elements SET area_id=?, updated_at=? WHERE area_id=?",
                (survivor_id, timestamp, donor_id),
            )
            conn.execute(
                "UPDATE yamazumi_pitches SET area_id=?, updated_at=? WHERE area_id=?",
                (survivor_id, timestamp, donor_id),
            )
            conn.execute("DELETE FROM yamazumi_areas WHERE id=?", (donor_id,))
            moved_area_count += 1
            merged_area_count += 1
    return moved_area_count, merged_area_count

def assembly_section_delete_target_validation(
    project_id: str,
    section_ids: list[str],
    target_section_id: str,
    active_scenario_id: str | None = None,
) -> dict:
    """Validate one shared continuity target without changing persisted records."""
    with connection() as conn:
        section_rows = _assembly_section_delete_rows(conn, project_id, section_ids)
        affected_ids = [str(row["id"]) for row in section_rows]
        return _assembly_section_target_validation(
            conn, project_id, affected_ids, target_section_id, active_scenario_id
        )

def assembly_section_delete_impact(
    project_id: str, section_ids: list[str]
) -> dict:
    """Describe the complete, approved effect of deleting Fishbone sections."""
    normalized_ids = list(dict.fromkeys(
        str(section_id).strip() for section_id in section_ids if str(section_id).strip()
    ))
    with connection() as conn:
        section_rows = _assembly_section_delete_rows(conn, project_id, normalized_ids)
        affected_ids = [str(row["id"]) for row in section_rows]
        affected_placeholders = ", ".join("?" for _ in affected_ids)

        def count_rows(table: str) -> int:
            return int(conn.execute(
                f"""SELECT COUNT(*) FROM {table}
                    WHERE project_id=? AND section_id IN ({affected_placeholders})""",
                (project_id, *affected_ids),
            ).fetchone()[0])

        assembly_impact = assembly_section_reference_impact(
            project_id, affected_ids, connection=conn
        )
        assembly_references = assembly_impact.to_dict("records")
        assembly_component_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM manufacturing_assembly_components component
                JOIN fishbone_part_assignments assignment
                  ON assignment.id=component.fishbone_assignment_id
                WHERE component.project_id=?
                  AND assignment.section_id IN ({affected_placeholders})""",
            (project_id, *affected_ids),
        ).fetchone()[0])

        yamazumi_area_count = count_rows("yamazumi_areas")
        process_link_count = count_rows("process_part_groups")
        category_references = [
            dict(row)
            for row in conn.execute(
                f"""SELECT id AS category_id, ebom_name, display_name,
                           section_id, installed_section_id
                    FROM assembly_grid_categories
                    WHERE project_id=? AND (
                        section_id IN ({affected_placeholders}) OR
                        installed_section_id IN ({affected_placeholders})
                    )
                    ORDER BY sequence, display_name""",
                (project_id, *affected_ids, *affected_ids),
            ).fetchall()
        ]
        category_built_reference_count = sum(
            int(str(row.get("section_id")) in affected_ids)
            for row in category_references
        )
        category_installed_reference_count = sum(
            int(str(row.get("installed_section_id")) in affected_ids)
            for row in category_references
        )
        feature_visibility_preference_count = count_rows(
            "assembly_grid_feature_visibility"
        )
        pits_bom_approved_occurrence_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM pits_bom_occurrences
                WHERE project_id=? AND review_status='Approved'
                  AND confirmed_section_id IN ({affected_placeholders})""",
            (project_id, *affected_ids),
        ).fetchone()[0])
        assembly_reference_count = sum(
            int(str(row.get("built_section_id")) in affected_ids)
            + int(str(row.get("installed_section_id")) in affected_ids)
            for row in assembly_references
        )
        connection_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM assembly_section_connections
                WHERE project_id=? AND (from_section_id IN ({affected_placeholders}) OR to_section_id IN ({affected_placeholders}))""",
            (project_id, *affected_ids, *affected_ids),
        ).fetchone()[0])
        return {
            "selected_section_count": len(normalized_ids),
            "affected_section_count": len(affected_ids),
            "descendant_section_count": len(affected_ids) - len(normalized_ids),
            "section_ids": affected_ids,
            "section_names": [str(row["name"]) for row in section_rows],
            "fishbone_use_count": count_rows("fishbone_part_assignments"),
            "connection_count": connection_count,
            "yamazumi_area_count": yamazumi_area_count,
            "process_link_count": process_link_count,
            "assembly_reference_count": assembly_reference_count,
            "assembly_references": assembly_references,
            "category_built_reference_count": category_built_reference_count,
            "category_installed_reference_count": category_installed_reference_count,
            "category_reference_count": (
                category_built_reference_count + category_installed_reference_count
            ),
            "category_references": category_references,
            "feature_visibility_preference_count": feature_visibility_preference_count,
            "assembly_component_count": assembly_component_count,
            "pits_bom_approved_occurrence_count": pits_bom_approved_occurrence_count,
            "requires_repointing": bool(
                yamazumi_area_count
                or process_link_count
                or assembly_reference_count
                or category_built_reference_count
                or category_installed_reference_count
            ),
        }

def delete_assembly_sections(
    project_id: str,
    section_ids: list[str],
    target_section_id: str | None = None,
    active_scenario_id: str | None = None,
    *,
    rehome_parts: bool = False,
    cascade_delete_content: bool = False,
) -> dict:
    """Atomically re-point continuity references, re-home content, or cascade-delete Fishbone sections."""
    impact = assembly_section_delete_impact(project_id, section_ids)
    timestamp = now_iso()
    target_id = _catalog_text(target_section_id) or None
    target_validation = None
    yamazumi_repointed = 0
    yamazumi_merged = 0
    process_repointed = 0
    category_built_repointed = 0
    category_installed_repointed = 0
    feature_visibility_deleted = 0
    assembly_replacements: list[dict] = []
    with connection() as conn:
        section_rows = _assembly_section_delete_rows(conn, project_id, section_ids)
        affected_ids = [str(row["id"]) for row in section_rows]
        placeholders = ", ".join("?" for _ in affected_ids)
        yamazumi_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM yamazumi_areas
                WHERE project_id=? AND section_id IN ({placeholders})""",
            (project_id, *affected_ids),
        ).fetchone()[0])
        process_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM process_part_groups
                WHERE project_id=? AND section_id IN ({placeholders})""",
            (project_id, *affected_ids),
        ).fetchone()[0])
        pits_bom_approved_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM pits_bom_occurrences
                WHERE project_id=? AND review_status='Approved'
                  AND confirmed_section_id IN ({placeholders})""",
            (project_id, *affected_ids),
        ).fetchone()[0])
        if pits_bom_approved_count:
            raise ValueError(
                "One or more affected Fishbone sections contain approved PITS BOM occurrences. "
                "Detach those occurrences in Import/Export Projects before deleting the sections."
            )
        assembly_impact = assembly_section_reference_impact(
            project_id, affected_ids, connection=conn
        )
        assembly_rows = assembly_impact.to_dict("records")
        assembly_reference_count = sum(
            int(_catalog_text(row.get("built_section_id")) in affected_ids)
            + int(_catalog_text(row.get("installed_section_id")) in affected_ids)
            for row in assembly_rows
        )
        category_built_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM assembly_grid_categories
                WHERE project_id=? AND section_id IN ({placeholders})""",
            (project_id, *affected_ids),
        ).fetchone()[0])
        category_installed_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM assembly_grid_categories
                WHERE project_id=? AND installed_section_id IN ({placeholders})""",
            (project_id, *affected_ids),
        ).fetchone()[0])
        feature_visibility_deleted = int(conn.execute(
            f"""SELECT COUNT(*) FROM assembly_grid_feature_visibility
                WHERE project_id=? AND section_id IN ({placeholders})""",
            (project_id, *affected_ids),
        ).fetchone()[0])
        requires_repointing = bool(
            yamazumi_count
            or process_count
            or assembly_reference_count
            or category_built_count
            or category_installed_count
        )

        if cascade_delete_content:
            # Delete Yamazumi work regions, elements, pitches, and areas
            conn.execute(
                f"""DELETE FROM yamazumi_work_regions WHERE area_id IN (
                    SELECT id FROM yamazumi_areas WHERE project_id=? AND section_id IN ({placeholders})
                )""",
                (project_id, *affected_ids),
            )
            conn.execute(
                f"""DELETE FROM yamazumi_elements WHERE area_id IN (
                    SELECT id FROM yamazumi_areas WHERE project_id=? AND section_id IN ({placeholders})
                )""",
                (project_id, *affected_ids),
            )
            conn.execute(
                f"""DELETE FROM yamazumi_pitches WHERE area_id IN (
                    SELECT id FROM yamazumi_areas WHERE project_id=? AND section_id IN ({placeholders})
                )""",
                (project_id, *affected_ids),
            )
            conn.execute(
                f"DELETE FROM yamazumi_areas WHERE project_id=? AND section_id IN ({placeholders})",
                (project_id, *affected_ids),
            )
            # Delete process plan groups
            conn.execute(
                f"DELETE FROM process_part_groups WHERE project_id=? AND section_id IN ({placeholders})",
                (project_id, *affected_ids),
            )
            # Delete assembly grid categories and feature visibility
            conn.execute(
                f"DELETE FROM assembly_grid_feature_visibility WHERE project_id=? AND section_id IN ({placeholders})",
                (project_id, *affected_ids),
            )
            conn.execute(
                f"""DELETE FROM assembly_grid_categories
                    WHERE project_id=? AND (section_id IN ({placeholders}) OR installed_section_id IN ({placeholders}))""",
                (project_id, *affected_ids, *affected_ids),
            )
            # Clear assembly references
            conn.execute(
                f"UPDATE manufacturing_assemblies SET built_section_id=NULL WHERE project_id=? AND built_section_id IN ({placeholders})",
                (project_id, *affected_ids),
            )
            conn.execute(
                f"UPDATE manufacturing_assemblies SET installed_section_id=NULL WHERE project_id=? AND installed_section_id IN ({placeholders})",
                (project_id, *affected_ids),
            )
            # Delete flow connections
            conn.execute(
                f"""DELETE FROM assembly_section_connections
                    WHERE project_id=? AND (from_section_id IN ({placeholders}) OR to_section_id IN ({placeholders}))""",
                (project_id, *affected_ids, *affected_ids),
            )
            # Delete part assignments (unassigning parts so they return to palette)
            section_assignment_ids = [
                str(r[0])
                for r in conn.execute(
                    f"SELECT id FROM fishbone_part_assignments WHERE project_id=? AND section_id IN ({placeholders})",
                    (project_id, *affected_ids),
                ).fetchall()
            ]
            if section_assignment_ids:
                _release_fishbone_assignment_references(
                    conn, project_id, section_assignment_ids, timestamp, detach_pits_occurrences=True
                )
            conn.execute(
                f"DELETE FROM fishbone_part_assignments WHERE project_id=? AND section_id IN ({placeholders})",
                (project_id, *affected_ids),
            )
            # Delete sections
            conn.execute(
                f"DELETE FROM assembly_sections WHERE project_id=? AND id IN ({placeholders})",
                (project_id, *affected_ids),
            )
        else:
            if requires_repointing:
                target_validation = _assembly_section_target_validation(
                    conn, project_id, affected_ids, target_id or "", active_scenario_id
                )
                if not target_validation["valid"]:
                    raise ValueError(str(target_validation["message"]))
                yamazumi_repointed, yamazumi_merged = (
                    _merge_yamazumi_areas_for_section_delete(
                        conn, project_id, affected_ids, str(target_id), timestamp
                    )
                )
                process_repointed = conn.execute(
                    f"""UPDATE process_part_groups SET section_id=?, updated_at=?
                        WHERE project_id=? AND section_id IN ({placeholders})""",
                    (target_id, timestamp, project_id, *affected_ids),
                ).rowcount
                category_built_repointed = conn.execute(
                    f"""UPDATE assembly_grid_categories
                        SET section_id=?, updated_at=?
                        WHERE project_id=? AND section_id IN ({placeholders})""",
                    (target_id, timestamp, project_id, *affected_ids),
                ).rowcount
                category_installed_repointed = conn.execute(
                    f"""UPDATE assembly_grid_categories
                        SET installed_section_id=?, updated_at=?
                        WHERE project_id=? AND installed_section_id IN ({placeholders})""",
                    (target_id, timestamp, project_id, *affected_ids),
                ).rowcount
                for row in assembly_rows:
                    if _catalog_text(row.get("built_section_id")) in affected_ids:
                        assembly_replacements.append(
                            {
                                "assembly_id": str(row["assembly_id"]),
                                "field": "built_section_id",
                                "section_id": target_id,
                            }
                        )
                    if _catalog_text(row.get("installed_section_id")) in affected_ids:
                        assembly_replacements.append(
                            {
                                "assembly_id": str(row["assembly_id"]),
                                "field": "installed_section_id",
                                "section_id": target_id,
                            }
                        )
            elif target_id:
                _assembly_section_target_validation(
                    conn, project_id, affected_ids, target_id, active_scenario_id
                )

            if assembly_replacements:
                repoint_assembly_section_references(
                    project_id, assembly_replacements, connection=conn
                )

            if rehome_parts and target_id:
                conn.execute(
                    f"""UPDATE fishbone_part_assignments SET section_id=?, updated_at=?
                        WHERE project_id=? AND section_id IN ({placeholders})""",
                    (target_id, timestamp, project_id, *affected_ids),
                )
            else:
                section_assignment_ids = [
                    str(r[0])
                    for r in conn.execute(
                        f"SELECT id FROM fishbone_part_assignments WHERE project_id=? AND section_id IN ({placeholders})",
                        (project_id, *affected_ids),
                    ).fetchall()
                ]
                if section_assignment_ids:
                    _release_fishbone_assignment_references(
                        conn, project_id, section_assignment_ids, timestamp, detach_pits_occurrences=True
                    )
                conn.execute(
                    f"DELETE FROM fishbone_part_assignments WHERE project_id=? AND section_id IN ({placeholders})",
                    (project_id, *affected_ids),
                )

            if target_id:
                # Delete connections between affected_ids and target_id (avoid self loops) and internal connections among affected_ids
                conn.execute(
                    f"""DELETE FROM assembly_section_connections
                        WHERE project_id=? AND (
                            (from_section_id IN ({placeholders}) AND to_section_id=?) OR
                            (to_section_id IN ({placeholders}) AND from_section_id=?) OR
                            (from_section_id IN ({placeholders}) AND to_section_id IN ({placeholders}))
                        )""",
                    (project_id, *affected_ids, target_id, *affected_ids, target_id, *affected_ids, *affected_ids),
                )
                # Re-route incoming connections to target_id
                existing_incoming = {
                    row["from_section_id"]
                    for row in conn.execute(
                        "SELECT from_section_id FROM assembly_section_connections WHERE project_id=? AND to_section_id=?",
                        (project_id, target_id),
                    ).fetchall()
                }
                for c_row in conn.execute(
                    f"SELECT id, from_section_id FROM assembly_section_connections WHERE project_id=? AND to_section_id IN ({placeholders})",
                    (project_id, *affected_ids),
                ).fetchall():
                    cid = c_row["id"]
                    from_sid = c_row["from_section_id"]
                    if from_sid in existing_incoming:
                        conn.execute("DELETE FROM assembly_section_connections WHERE id=?", (cid,))
                    else:
                        conn.execute(
                            "UPDATE assembly_section_connections SET to_section_id=?, updated_at=? WHERE id=?",
                            (target_id, timestamp, cid),
                        )
                        existing_incoming.add(from_sid)

                # Re-route outgoing connections from target_id
                existing_outgoing = {
                    row["to_section_id"]
                    for row in conn.execute(
                        "SELECT to_section_id FROM assembly_section_connections WHERE project_id=? AND from_section_id=?",
                        (project_id, target_id),
                    ).fetchall()
                }
                for c_row in conn.execute(
                    f"SELECT id, to_section_id FROM assembly_section_connections WHERE project_id=? AND from_section_id IN ({placeholders})",
                    (project_id, *affected_ids),
                ).fetchall():
                    cid = c_row["id"]
                    to_sid = c_row["to_section_id"]
                    if to_sid in existing_outgoing:
                        conn.execute("DELETE FROM assembly_section_connections WHERE id=?", (cid,))
                    else:
                        conn.execute(
                            "UPDATE assembly_section_connections SET from_section_id=?, updated_at=? WHERE id=?",
                            (target_id, timestamp, cid),
                        )
                        existing_outgoing.add(to_sid)

                # Clean up any lingering connections involving affected_ids
                conn.execute(
                    f"""DELETE FROM assembly_section_connections
                        WHERE project_id=? AND (from_section_id IN ({placeholders}) OR to_section_id IN ({placeholders}))""",
                    (project_id, *affected_ids, *affected_ids),
                )
            else:
                conn.execute(
                    f"""DELETE FROM assembly_section_connections
                        WHERE project_id=? AND (from_section_id IN ({placeholders}) OR to_section_id IN ({placeholders}))""",
                    (project_id, *affected_ids, *affected_ids),
                )

            conn.execute(
                f"DELETE FROM assembly_sections WHERE project_id=? AND id IN ({placeholders})",
                (project_id, *affected_ids),
            )

    return {
        **impact,
        "target_section_id": target_id,
        "target_section_name": (
            str(target_validation["target_section_name"]) if target_validation else ""
        ),
        "yamazumi_repointed_count": int(yamazumi_repointed),
        "yamazumi_merged_count": int(yamazumi_merged),
        "process_repointed_count": int(process_repointed),
        "assembly_replacement_count": len(assembly_replacements),
        "category_built_repointed_count": int(category_built_repointed),
        "category_installed_repointed_count": int(category_installed_repointed),
        "category_repointed_count": int(
            category_built_repointed + category_installed_repointed
        ),
        "feature_visibility_deleted_count": int(feature_visibility_deleted),
        "rehome_parts": bool(rehome_parts and target_id),
        "cascade_delete_content": bool(cascade_delete_content),
    }

def _create_yamazumi_areas_for_section(
    conn: sqlite3.Connection,
    project_id: str,
    section_id: str,
    section_name: str,
    timestamp: str,
) -> dict[str, object]:
    """Create one linked area per existing scenario without altering conflicts."""
    created: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    scenarios = conn.execute(
        """SELECT id, name, revision_label, status
           FROM planning_scenarios WHERE project_id=?
           ORDER BY revision_sequence, created_at, id""",
        (project_id,),
    ).fetchall()
    for scenario in scenarios:
        scenario_id = str(scenario["id"])
        linked = conn.execute(
            """SELECT id FROM yamazumi_areas
               WHERE project_id=? AND scenario_id=? AND section_id=? LIMIT 1""",
            (project_id, scenario_id, section_id),
        ).fetchone()
        if linked:
            continue
        same_name = conn.execute(
            """SELECT id, section_id FROM yamazumi_areas
               WHERE project_id=? AND scenario_id=? AND name=? COLLATE NOCASE
               ORDER BY id LIMIT 1""",
            (project_id, scenario_id, section_name),
        ).fetchone()
        if same_name:
            conflicts.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_name": str(scenario["name"]),
                    "revision_label": str(scenario["revision_label"]),
                    "status": str(scenario["status"]),
                    "area_id": str(same_name["id"]),
                    "reason": "same_name_area",
                }
            )
            continue
        area_id = str(uuid4())
        conn.execute(
            """INSERT INTO yamazumi_areas
               (id, project_id, scenario_id, section_id, name, takt_override_s, updated_at)
               VALUES (?, ?, ?, ?, ?, NULL, ?)""",
            (area_id, project_id, scenario_id, section_id, section_name, timestamp),
        )
        created.append(
            {
                "area_id": area_id,
                "scenario_id": scenario_id,
                "scenario_name": str(scenario["name"]),
                "revision_label": str(scenario["revision_label"]),
                "status": str(scenario["status"]),
            }
        )
    return {"created": created, "conflicts": conflicts}

def yamazumi_area_creation_summary(
    project_id: str, section_id: str
) -> dict[str, object]:
    """Describe linked areas and preserved name conflicts for one section."""
    section_rows = query(
        "SELECT name FROM assembly_sections WHERE id=? AND project_id=?",
        (section_id, project_id),
    )
    if not section_rows:
        raise ValueError("The Fishbone section no longer exists.")
    section_name = str(section_rows[0]["name"])
    linked = query(
        """SELECT area.id AS area_id, scenario.id AS scenario_id,
                  scenario.name AS scenario_name,
                  scenario.revision_label, scenario.status
           FROM planning_scenarios scenario
           JOIN yamazumi_areas area
             ON area.scenario_id=scenario.id AND area.project_id=scenario.project_id
           WHERE scenario.project_id=? AND area.section_id=?
           ORDER BY scenario.revision_sequence, scenario.created_at, scenario.id""",
        (project_id, section_id),
    )
    conflicts = query(
        """SELECT area.id AS area_id, scenario.id AS scenario_id,
                  scenario.name AS scenario_name,
                  scenario.revision_label, scenario.status
           FROM planning_scenarios scenario
           JOIN yamazumi_areas area
             ON area.scenario_id=scenario.id AND area.project_id=scenario.project_id
           WHERE scenario.project_id=? AND area.name=? COLLATE NOCASE
             AND (area.section_id IS NULL OR area.section_id<>?)
           ORDER BY scenario.revision_sequence, scenario.created_at, scenario.id""",
        (project_id, section_name, section_id),
    )
    for row in conflicts:
        row["reason"] = "same_name_area"
    return {
        "section_id": section_id,
        "section_name": section_name,
        "created": linked,
        "conflicts": conflicts,
    }

def add_assembly_section(
    project_id: str,
    name: str,
    section_type: str,
    parent_id: str | None,
    description: str,
    grid_x: int | None = None,
    grid_y: int | None = None,
) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Section name is required.")
    if section_type not in {"Assembly", "Support Operations", "Main spine", "Subassembly"}:
        raise ValueError("Choose Assembly or Support Operations.")
    parent_id = parent_id or None
    if section_type == "Subassembly" and not parent_id:
        raise ValueError("A subassembly must have a parent assembly.")
    if section_type == "Main spine":
        parent_id = None
    if section_type in {"Main spine", "Subassembly"}:
        section_type = "Assembly"
    timestamp = now_iso()
    section_id = str(uuid4())
    try:
        with connection() as conn:
            if section_type == "Support Operations" and parent_id:
                parent_exists = conn.execute(
                    "SELECT 1 FROM assembly_sections WHERE id=? AND project_id=?",
                    (parent_id, project_id),
                ).fetchone()
                if not parent_exists:
                    parent_id = None
            next_sequence = conn.execute(
                """SELECT COALESCE(MAX(sequence), 0) + 10 FROM assembly_sections
                   WHERE project_id=? AND parent_id IS ?""",
                (project_id, parent_id),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO assembly_sections
                   (id, project_id, name, section_type, parent_id, sequence, description, active, grid_x, grid_y, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                (section_id, project_id, name, section_type, parent_id, next_sequence, description.strip(), grid_x, grid_y, timestamp, timestamp),
            )
            _create_yamazumi_areas_for_section(
                conn, project_id, section_id, name, timestamp
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"A section named {name} already exists in this project.") from exc
    return section_id

def reorder_assembly_section(project_id: str, section_id: str, action: str) -> bool:
    allowed = {"Move earlier", "Move later", "Move to start", "Move to end"}
    if action not in allowed:
        raise ValueError("Unsupported framework reorder action.")
    with connection() as conn:
        target = conn.execute(
            "SELECT id, parent_id FROM assembly_sections WHERE id=? AND project_id=?",
            (section_id, project_id),
        ).fetchone()
        if not target:
            raise ValueError("The selected framework item no longer exists.")
        siblings = conn.execute(
            """SELECT id FROM assembly_sections WHERE project_id=? AND parent_id IS ?
               ORDER BY sequence, name""",
            (project_id, target["parent_id"]),
        ).fetchall()
        ordered_ids = [row["id"] for row in siblings]
        old_index = ordered_ids.index(section_id)
        new_index = old_index
        if action == "Move earlier":
            new_index = max(0, old_index - 1)
        elif action == "Move later":
            new_index = min(len(ordered_ids) - 1, old_index + 1)
        elif action == "Move to start":
            new_index = 0
        elif action == "Move to end":
            new_index = len(ordered_ids) - 1
        ordered_ids.insert(new_index, ordered_ids.pop(old_index))
        timestamp = now_iso()
        for index, sibling_id in enumerate(ordered_ids, start=1):
            conn.execute(
                "UPDATE assembly_sections SET sequence=?, updated_at=? WHERE id=?",
                (index * 10, timestamp, sibling_id),
            )
    return new_index != old_index

def update_assembly_section_rows(
    project_id: str,
    edited: pd.DataFrame,
    *,
    _connection: sqlite3.Connection | None = None,
) -> int:
    required = {"id", "name", "section_type", "parent_id", "sequence", "description", "active"}
    if not required.issubset(edited.columns):
        raise ValueError("The assembly framework table is missing required columns.")
    records = edited.to_dict("records")
    ids = {str(row["id"]) for row in records}
    names = [str(row.get("name") or "").strip() for row in records]
    if any(not name for name in names):
        raise ValueError("Every framework row needs a name.")
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("Framework names must be unique within the project.")

    parent_by_id: dict[str, str | None] = {}
    type_by_id: dict[str, str] = {}
    for row in records:
        section_id = str(row["id"])
        section_type = str(row.get("section_type") or "").strip()
        parent_id = row.get("parent_id")
        parent_id = None if parent_id is None or pd.isna(parent_id) or not str(parent_id).strip() else str(parent_id).strip()
        if section_type not in {"Assembly", "Support Operations", "Main spine", "Subassembly"}:
            raise ValueError("Each framework row must be Assembly or Support Operations.")
        if section_type == "Main spine":
            parent_id = None
            section_type = "Assembly"
        elif section_type == "Subassembly":
            if not parent_id:
                raise ValueError(f"Subassembly {row['name']} needs a parent assembly.")
            section_type = "Assembly"
        elif section_type == "Support Operations" and parent_id and parent_id not in ids:
            parent_id = None
        if parent_id == section_id or (parent_id and parent_id not in ids):
            raise ValueError(f"Choose a valid parent for {row['name']}.")
        parent_by_id[section_id] = parent_id
        type_by_id[section_id] = section_type

    for section_id in ids:
        visited: set[str] = set()
        cursor = section_id
        while cursor:
            if cursor in visited:
                raise ValueError("The assembly framework cannot contain a circular parent relationship.")
            visited.add(cursor)
            cursor = parent_by_id.get(cursor)

    timestamp = now_iso()
    try:
        with (nullcontext(_connection) if _connection is not None else connection()) as conn:
            for row in records:
                section_id = str(row["id"])
                conn.execute(
                    """UPDATE assembly_sections SET name=?, section_type=?, parent_id=?, sequence=?,
                       description=?, active=?, updated_at=? WHERE id=? AND project_id=?""",
                    (
                        str(row["name"]).strip(), type_by_id[section_id], parent_by_id[section_id],
                        int(row.get("sequence") or 0), str(row.get("description") or "").strip(),
                        1 if bool(row.get("active")) else 0, timestamp, section_id, project_id,
                    ),
                )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Framework names must be unique within the project.") from exc
    return len(records)

@cached_store_read
def fishbone_part_assignments(
    project_id: str, scenario_id: str | None = None
) -> pd.DataFrame:
    activity_join = """
        LEFT JOIN part_scenario_activity activity
          ON activity.project_id=a.project_id AND activity.part_id=a.part_id
         AND activity.scenario_id=?
    """ if scenario_id else ""
    activity_clause = " AND COALESCE(activity.active, 1)=1" if scenario_id else ""
    params = (scenario_id, project_id) if scenario_id else (project_id,)
    return pd.DataFrame(query(
        f"""SELECT a.id, a.project_id, a.part_id, a.section_id,
                  COALESCE(a.step_number, 1) AS step_number, a.sequence, a.quantity,
                  a.use_description, a.notes, a.pits_sync_status, a.pits_quantity_updated_at,
                  a.updated_at, p.part_number, p.description, p.revision, p.model_applicability,
                  COALESCE(p.factory_nickname, '') AS factory_nickname,
                  s.name AS section_name
           FROM fishbone_part_assignments a
           JOIN parts p ON p.id = a.part_id
           JOIN assembly_sections s ON s.id = a.section_id
           {activity_join}
           WHERE a.project_id = ?{activity_clause}
           ORDER BY s.sequence, a.step_number, a.sequence, p.part_number""",
        params,
    ))

def search_parts_and_fishbone(
    project_id: str, search_text: str, scenario_id: str | None = None
) -> pd.DataFrame:
    """Find catalog parts by number, description, or fishbone-use text across all sections."""
    columns = [
        "part_id",
        "part_number",
        "description",
        "factory_nickname",
        "revision",
        "model_applicability",
        "assignment_id",
        "section_id",
        "section_name",
        "quantity",
        "use_description",
        "assignment_notes",
    ]
    tokens = list(dict.fromkeys(str(search_text or "").casefold().split()))
    if not tokens:
        return pd.DataFrame({column: pd.Series(dtype="string") for column in columns})

    token_clauses: list[str] = []
    params: list = [scenario_id, project_id] if scenario_id else [project_id]
    for token in tokens:
        pattern = f"%{token}%"
        token_clauses.append(
            """(LOWER(p.part_number) LIKE ? OR LOWER(p.description) LIKE ?
                 OR LOWER(COALESCE(p.factory_nickname, '')) LIKE ?
                 OR LOWER(COALESCE(a.use_description, '')) LIKE ?
                 OR LOWER(COALESCE(s.name, '')) LIKE ?)"""
        )
        params.extend([pattern, pattern, pattern, pattern, pattern])
    params.append(100)
    activity_join = """
            LEFT JOIN part_scenario_activity activity
              ON activity.project_id=p.project_id AND activity.part_id=p.id
             AND activity.scenario_id=?
    """ if scenario_id else ""
    activity_clause = " AND COALESCE(activity.active, 1)=1" if scenario_id else ""
    rows = query(
        f"""SELECT p.id AS part_id, p.part_number, p.description,
                   COALESCE(p.factory_nickname, '') AS factory_nickname,
                   p.revision, p.model_applicability, a.id AS assignment_id,
                   a.section_id, s.name AS section_name, a.quantity,
                   a.use_description, a.notes AS assignment_notes
            FROM parts p
            LEFT JOIN fishbone_part_assignments a
              ON a.part_id=p.id AND a.project_id=p.project_id
            LEFT JOIN assembly_sections s ON s.id=a.section_id
            {activity_join}
            WHERE p.project_id=? AND ({' OR '.join(token_clauses)}){activity_clause}
            ORDER BY p.part_number, s.sequence, a.sequence
            LIMIT ?""",
        tuple(params),
    )
    return pd.DataFrame(rows, columns=columns)

def create_part_and_assign_to_section(
    project_id: str,
    section_id: str,
    values: dict,
    placement_quantity: float,
    use_description: str = "",
    placement_notes: str = "",
    step_number: int = 1,
) -> tuple[str, str, str]:
    """Create one catalog part and its first fishbone use in one transaction."""
    part_number = str(values.get("part_number") or "").strip()
    description = str(values.get("description") or "").strip()
    revision = str(values.get("revision") or "0").strip() or "0"
    catalog_notes = str(values.get("notes") or "").strip()
    if not part_number:
        raise ValueError("Part number is required.")
    if not description:
        raise ValueError("Part Name is required.")
    try:
        numeric_quantity = float(placement_quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("Fishbone quantity must be a number greater than zero.") from exc
    if not math.isfinite(numeric_quantity) or numeric_quantity <= 0:
        raise ValueError("Fishbone quantity must be a number greater than zero.")
    quantity = numeric_quantity

    part_id = str(uuid4())
    assignment_id = str(uuid4())
    timestamp = now_iso()
    try:
        with connection() as conn:
            section = conn.execute(
                "SELECT id FROM assembly_sections WHERE id=? AND project_id=? AND active=1",
                (section_id, project_id),
            ).fetchone()
            if not section:
                raise ValueError("Choose an active fishbone section.")
            duplicate = conn.execute(
                """SELECT part_number FROM parts
                   WHERE project_id=? AND LOWER(TRIM(part_number))=LOWER(?)""",
                (project_id, part_number),
            ).fetchone()
            if duplicate:
                raise ValueError(
                    f"Part {duplicate['part_number']} already exists. Use Find existing instead."
                )
            conn.execute(
                """INSERT INTO parts
                   (id, project_id, part_number, description, quantity, revision, source,
                    image_path, model_applicability, notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'Manual', '', ?, ?, ?, ?)""",
                (
                    part_id,
                    project_id,
                    part_number,
                    description,
                    quantity,
                    revision,
                    normalize_model_applicability(values.get("model_applicability", "All")),
                    catalog_notes,
                    timestamp,
                    timestamp,
                ),
            )
            next_sequence = conn.execute(
                """SELECT COALESCE(MAX(sequence), 0) + 10
                   FROM fishbone_part_assignments WHERE project_id=? AND section_id=?""",
                (project_id, section_id),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, part_id, section_id, step_number, sequence, quantity,
                    use_description, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    assignment_id,
                    project_id,
                    part_id,
                    section_id,
                    int(step_number or 1),
                    next_sequence,
                    quantity,
                    str(use_description or "").strip(),
                    str(placement_notes or "").strip(),
                    timestamp,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("That part number already exists in this project.") from exc
    return part_id, assignment_id, timestamp

def move_fishbone_part_assignment(
    project_id: str, assignment_id: str, section_id: str
) -> str:
    """Move one existing fishbone occurrence to the end of another active section."""
    timestamp = now_iso()
    with connection() as conn:
        assignment = conn.execute(
            """SELECT section_id, part_id FROM fishbone_part_assignments
               WHERE id=? AND project_id=?""",
            (assignment_id, project_id),
        ).fetchone()
        if not assignment:
            raise ValueError("The selected fishbone use no longer exists.")
        section = conn.execute(
            "SELECT id FROM assembly_sections WHERE id=? AND project_id=? AND active=1",
            (section_id, project_id),
        ).fetchone()
        if not section:
            raise ValueError("Choose an active fishbone section.")
        if str(assignment["section_id"]) == str(section_id):
            raise ValueError("That fishbone use is already in the selected section.")
        another_source_use = conn.execute(
            """SELECT 1 FROM fishbone_part_assignments
               WHERE project_id=? AND section_id=? AND part_id=? AND id<>? LIMIT 1""",
            (
                project_id,
                assignment["section_id"],
                assignment["part_id"],
                assignment_id,
            ),
        ).fetchone()
        paired_in_source = conn.execute(
            """SELECT 1 FROM process_part_groups group_row
               JOIN process_part_options option_row ON option_row.group_id=group_row.id
               WHERE group_row.project_id=? AND group_row.section_id=?
                 AND option_row.part_id=? LIMIT 1""",
            (project_id, assignment["section_id"], assignment["part_id"]),
        ).fetchone()
        if paired_in_source and not another_source_use:
            raise ValueError(
                "This fishbone use is already paired to Process at a Glance work in its current "
                "section. Remove or update that pairing before moving it."
            )
        next_sequence = conn.execute(
            """SELECT COALESCE(MAX(sequence), 0) + 10
               FROM fishbone_part_assignments WHERE project_id=? AND section_id=?""",
            (project_id, section_id),
        ).fetchone()[0]
        conn.execute(
            """UPDATE fishbone_part_assignments
               SET section_id=?, sequence=?, updated_at=?
               WHERE id=? AND project_id=?""",
            (section_id, next_sequence, timestamp, assignment_id, project_id),
        )
    return timestamp

def reorder_fishbone_part_assignments(
    project_id: str,
    section_id: str,
    ordered_assignment_ids: list[str],
    *,
    editor_name: str = "",
) -> int:
    """Update sequence order of part assignments in an assembly section."""
    if not ordered_assignment_ids:
        return 0
    timestamp = now_iso()
    updated_count = 0
    with connection() as conn:
        for idx, aid in enumerate(ordered_assignment_ids):
            aid_str = str(aid).strip()
            if not aid_str or aid_str.startswith("draft_"):
                continue
            cur = conn.execute(
                """UPDATE fishbone_part_assignments
                   SET sequence = ?, updated_at = ?
                   WHERE id = ? AND section_id = ? AND project_id = ?""",
                ((idx + 1) * 10, timestamp, aid_str, section_id, project_id),
            )
            updated_count += cur.rowcount
    if updated_count > 0:
        record_audit_event(
            project_id,
            "Fishbone uses",
            "Reorder fishbone uses",
            updated_count,
            editor_name,
            {"section_id": section_id, "ordered_assignment_ids": ordered_assignment_ids},
        )
    return updated_count

def assign_parts_to_section(
    project_id: str,
    part_ids: list[str],
    section_id: str,
    use_description: str = "",
    *,
    step_number: int = 1,
    allow_additional_use: bool = False,
    quantities_by_part: dict[str, float] | None = None,
) -> int:
    if not part_ids:
        return 0
    timestamp = now_iso()
    count = 0
    with connection() as conn:
        section = conn.execute(
            "SELECT id FROM assembly_sections WHERE id=? AND project_id=? AND active=1",
            (section_id, project_id),
        ).fetchone()
        if not section:
            raise ValueError("Choose an active assembly section.")
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM fishbone_part_assignments WHERE project_id=? AND section_id=?",
            (project_id, section_id),
        ).fetchone()[0]
        for part_id in dict.fromkeys(part_ids):
            part = conn.execute("SELECT quantity FROM parts WHERE id=? AND project_id=?", (part_id, project_id)).fetchone()
            if not part:
                continue
            already_placed = conn.execute(
                "SELECT 1 FROM fishbone_part_assignments WHERE project_id=? AND part_id=? LIMIT 1",
                (project_id, part_id),
            ).fetchone()
            if already_placed and not allow_additional_use:
                continue
            next_sequence += 10
            requested_quantity = (
                quantities_by_part.get(part_id)
                if quantities_by_part and part_id in quantities_by_part
                else part["quantity"]
            )
            try:
                numeric_quantity = float(
                    requested_quantity if requested_quantity is not None else 1
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Fishbone quantities must be numbers greater than zero."
                ) from exc
            if not math.isfinite(numeric_quantity) or numeric_quantity <= 0:
                raise ValueError("Fishbone quantities must be numbers greater than zero.")
            quantity = numeric_quantity
            assignment_id = str(uuid4())
            conn.execute(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, part_id, section_id, step_number, sequence, quantity, use_description, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?)""",
                (
                    assignment_id, project_id, part_id, section_id, int(step_number or 1), next_sequence,
                    quantity, use_description.strip(), timestamp,
                ),
            )
            count += 1
    return count

def _release_fishbone_assignment_references(
    conn: sqlite3.Connection,
    project_id: str,
    assignment_ids: list[str],
    timestamp: str,
    *,
    detach_pits_occurrences: bool = False,
) -> None:
    """Safely repoint or clear foreign-key references before deleting fishbone_part_assignments."""
    target_ids = [
        str(aid).strip()
        for aid in dict.fromkeys(assignment_ids)
        if str(aid or "").strip()
    ]
    if not target_ids:
        return
    placeholders = ",".join("?" for _ in target_ids)
    deleting_rows = conn.execute(
        f"""SELECT id, part_id, section_id
            FROM fishbone_part_assignments
            WHERE project_id = ? AND id IN ({placeholders})""",
        (project_id, *target_ids),
    ).fetchall()
    for row in deleting_rows:
        aid = str(row["id"])
        part_id = str(row["part_id"])
        section_id = str(row["section_id"])
        replacement = conn.execute(
            f"""SELECT id, quantity
                FROM fishbone_part_assignments
                WHERE project_id = ? AND part_id = ? AND section_id = ?
                  AND id NOT IN ({placeholders})
                ORDER BY sequence, id LIMIT 1""",
            (project_id, part_id, section_id, *target_ids),
        ).fetchone()
        if replacement:
            rep_id = str(replacement["id"])
            rep_qty = float(replacement["quantity"] or 0.0)
            existing_rep_uses = conn.execute(
                "SELECT COUNT(*) FROM process_part_options WHERE fishbone_assignment_id = ?",
                (rep_id,),
            ).fetchone()[0]
            aid_consume_count = conn.execute(
                """SELECT COUNT(*) FROM process_part_options
                   WHERE fishbone_assignment_id = ? AND handling_type = 'Consume'""",
                (aid,),
            ).fetchone()[0]
            if existing_rep_uses == 0 and rep_qty >= aid_consume_count:
                conn.execute(
                    """UPDATE process_part_options
                       SET fishbone_assignment_id = ?, updated_at = ?
                       WHERE fishbone_assignment_id = ?""",
                    (rep_id, timestamp, aid),
                )
        conn.execute(
            """UPDATE process_part_options
               SET handling_type = NULL, fishbone_assignment_id = NULL, updated_at = ?
               WHERE fishbone_assignment_id = ?""",
            (timestamp, aid),
        )
        if detach_pits_occurrences:
            occ_row = conn.execute(
                """SELECT id FROM pits_bom_occurrences
                   WHERE project_id = ? AND approved_assignment_id = ?""",
                (project_id, aid),
            ).fetchone()
            if occ_row:
                unclaimed_replacement = conn.execute(
                    f"""SELECT f.id, f.section_id
                        FROM fishbone_part_assignments f
                        LEFT JOIN pits_bom_occurrences o
                          ON o.project_id = f.project_id AND o.approved_assignment_id = f.id
                        WHERE f.project_id = ? AND f.part_id = ?
                          AND f.id NOT IN ({placeholders})
                          AND o.id IS NULL
                        ORDER BY CASE WHEN f.section_id = ? THEN 0 ELSE 1 END, f.sequence, f.id
                        LIMIT 1""",
                    (project_id, part_id, *target_ids, section_id),
                ).fetchone()
                if unclaimed_replacement:
                    conn.execute(
                        """UPDATE pits_bom_occurrences
                           SET approved_assignment_id = ?, confirmed_section_id = ?, updated_at = ?
                           WHERE id = ? AND project_id = ?""",
                        (
                            str(unclaimed_replacement["id"]),
                            str(unclaimed_replacement["section_id"]),
                            timestamp,
                            str(occ_row["id"]),
                            project_id,
                        ),
                    )
                else:
                    conn.execute(
                        """UPDATE pits_bom_occurrences
                           SET review_status = 'Needs review',
                               confirmed_section_id = NULL,
                               approved_assignment_id = NULL,
                               reviewed_source_fingerprint = NULL,
                               last_reviewed_import_id = NULL,
                               source_state = CASE WHEN source_state = 'Missing' THEN 'Missing' ELSE 'New' END,
                               updated_at = ?
                           WHERE id = ? AND project_id = ?""",
                        (timestamp, str(occ_row["id"]), project_id),
                    )
    conn.execute(
        f"""UPDATE process_part_options
            SET handling_type = NULL, fishbone_assignment_id = NULL, updated_at = ?
            WHERE fishbone_assignment_id IN ({placeholders})""",
        (timestamp, *target_ids),
    )

def delete_fishbone_part_assignments(project_id: str, assignment_ids: list[str]) -> int:
    """Delete selected fishbone uses atomically, leaving master Parts records untouched."""
    selected_ids = list(
        dict.fromkeys(str(assignment_id) for assignment_id in assignment_ids if str(assignment_id))
    )
    if not selected_ids:
        return 0
    placeholders = ",".join("?" for _ in selected_ids)
    timestamp = now_iso()
    with connection() as conn:
        found = conn.execute(
            f"""SELECT COUNT(*) FROM fishbone_part_assignments
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *selected_ids),
        ).fetchone()[0]
        if found != len(selected_ids):
            raise ValueError("One or more selected fishbone uses no longer exist.")
        linked = conn.execute(
            f"""SELECT COUNT(*) FROM pits_bom_occurrences
                WHERE project_id=? AND approved_assignment_id IN ({placeholders})""",
            (project_id, *selected_ids),
        ).fetchone()[0]
        if linked:
            raise ValueError(
                "One or more selected Fishbone uses are approved PITS BOM occurrences. "
                "Detach those occurrences in Import/Export Projects before deleting the uses."
            )
        _release_fishbone_assignment_references(conn, project_id, selected_ids, timestamp)
        cursor = conn.execute(
            f"""DELETE FROM fishbone_part_assignments
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *selected_ids),
        )
        return int(cursor.rowcount)

def delete_fishbone_part_assignment(project_id: str, assignment_id: str) -> bool:
    """Delete one fishbone use while leaving its master Parts record untouched."""
    return delete_fishbone_part_assignments(project_id, [assignment_id]) == 1

def replace_fishbone_part_assignments(
    project_id: str,
    edited: pd.DataFrame,
    *,
    _connection: sqlite3.Connection | None = None,
) -> int:
    required = {"id", "part_id", "section_id", "sequence", "quantity", "use_description", "notes"}
    if not required.issubset(edited.columns):
        raise ValueError("The part assignment table is missing required columns.")
    timestamp = now_iso()
    with (nullcontext(_connection) if _connection is not None else connection()) as conn:
        valid_parts = {row[0] for row in conn.execute("SELECT id FROM parts WHERE project_id=?", (project_id,))}
        valid_sections = {row[0] for row in conn.execute("SELECT id FROM assembly_sections WHERE project_id=?", (project_id,))}
        records = []
        for _, row in edited.iterrows():
            part_id, section_id = str(row["part_id"]), str(row["section_id"])
            if part_id not in valid_parts or section_id not in valid_sections:
                raise ValueError("Every assignment must reference a valid project part and assembly section.")
            try:
                quantity = float(row.get("quantity"))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Fishbone quantities must be numbers greater than zero."
                ) from exc
            if not math.isfinite(quantity) or quantity <= 0:
                raise ValueError("Fishbone quantities must be numbers greater than zero.")
            records.append((
                str(row.get("id") or uuid4()), project_id, part_id, section_id,
                int(row.get("step_number") or 1),
                int(row.get("sequence") or 0), quantity,
                str(row.get("use_description") or "").strip(),
                str(row.get("notes") or "").strip(), timestamp,
            ))
        desired_by_id = {record[0]: record for record in records}
        linked_rows = conn.execute(
            """SELECT occurrence.approved_assignment_id, assignment.part_id,
                      assignment.section_id, assignment.quantity
               FROM pits_bom_occurrences occurrence
               JOIN fishbone_part_assignments assignment
                 ON assignment.id=occurrence.approved_assignment_id
               WHERE occurrence.project_id=?""",
            (project_id,),
        ).fetchall()
        for linked in linked_rows:
            assignment_id = str(linked["approved_assignment_id"])
            desired = desired_by_id.get(assignment_id)
            if desired is None:
                raise ValueError(
                    "An approved PITS BOM Fishbone use cannot be removed here. Detach its "
                    "occurrence in Import/Export Projects first."
                )
            if desired[2] != str(linked["part_id"]) or desired[3] != str(linked["section_id"]):
                raise ValueError(
                    "The part or Fishbone section of an approved PITS BOM use cannot be changed "
                    "here. Detach its occurrence first."
                )
            if round(float(desired[6]), 9) != round(float(linked["quantity"]), 9):
                raise ValueError(
                    "The quantity of an approved PITS BOM use is determined by PITS and cannot be changed here. "
                    "Correct the quantity in PITS."
                )
        desired_ids = set(desired_by_id)
        existing_ids = {
            str(row[0]) for row in conn.execute(
                "SELECT id FROM fishbone_part_assignments WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        stale_ids = existing_ids - desired_ids
        conn.executemany(
            """INSERT INTO fishbone_part_assignments
               (id, project_id, part_id, section_id, step_number, sequence, quantity,
                use_description, notes, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 step_number=excluded.step_number, sequence=excluded.sequence,
                 quantity=excluded.quantity, use_description=excluded.use_description,
                 notes=excluded.notes, updated_at=excluded.updated_at""",
            records,
        )
        if stale_ids:
            stale_list = list(stale_ids)
            _release_fishbone_assignment_references(conn, project_id, stale_list, timestamp)
            stale_placeholders = ",".join("?" for _ in stale_list)
            conn.execute(
                f"""DELETE FROM fishbone_part_assignments
                    WHERE project_id=? AND id IN ({stale_placeholders})""",
                (project_id, *stale_list),
            )
    return len(records)

def save_fishbone_plan(
    project_id: str,
    framework: pd.DataFrame | None,
    assignments: pd.DataFrame | None,
) -> tuple[int, int]:
    """Validate and save framework and placement edits in one transaction."""
    with connection() as conn:
        framework_count = (
            update_assembly_section_rows(project_id, framework, _connection=conn)
            if framework is not None
            else 0
        )
        assignment_count = (
            replace_fishbone_part_assignments(project_id, assignments, _connection=conn)
            if assignments is not None
            else 0
        )
    return framework_count, assignment_count

def replace_fishbone_nodes(project_id: str, edited: pd.DataFrame) -> None:
    fields = ["source_row", "sequence", "parent_id", "depth", "part_number", "description", "quantity",
              "branch_name", "subsystem", "model_feature", "comments", "tracker_status", "planned_area", "source", "raw_levels", "review_status",
              "pits_id", "applicable_models", "source_changed"]
    with connection() as conn:
        conn.execute("DELETE FROM fishbone_nodes WHERE project_id = ?", (project_id,))
        for idx, row in edited.iterrows():
            part_number = "" if pd.isna(row.get("part_number", "")) else str(row.get("part_number", "")).strip()
            description = "" if pd.isna(row.get("description", "")) else str(row.get("description", "")).strip()
            if not part_number and not description:
                continue
            values = []
            for field in fields:
                value = row.get(field, "")
                if field == "applicable_models" and isinstance(value, (list, tuple, set)):
                    value = json.dumps(list(value))
                if pd.isna(value):
                    value = None if field in {"source_row", "parent_id", "quantity"} else (1 if field == "depth" else (0 if field == "source_changed" else ""))
                values.append(value)
            node_id = str(row.get("id")) if row.get("id") and not pd.isna(row.get("id")) else str(uuid4())
            conn.execute(
                f"INSERT INTO fishbone_nodes (id, project_id, {', '.join(fields)}, updated_at) VALUES ({', '.join(['?'] * (len(fields) + 3))})",
                (node_id, project_id, *values, now_iso()),
            )

def import_fishbone_nodes(project_id: str, nodes: pd.DataFrame, replace: bool = True) -> int:
    timestamp = now_iso()
    with connection() as conn:
        if replace:
            conn.execute("DELETE FROM fishbone_nodes WHERE project_id = ?", (project_id,))
        id_by_sequence: dict[int, str] = {}
        for _, row in nodes.iterrows():
            node_id = str(uuid4())
            parent_sequence = row.get("parent_sequence")
            parent_id = id_by_sequence.get(int(parent_sequence)) if pd.notna(parent_sequence) else None
            sequence = int(row["sequence"])
            id_by_sequence[sequence] = node_id
            conn.execute(
                """INSERT INTO fishbone_nodes
                (id, project_id, source_row, sequence, parent_id, depth, part_number, description,
                 quantity, branch_name, subsystem, model_feature, comments, tracker_status,
                 planned_area, source, raw_levels, review_status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PITS import', ?, 'Needs review', ?)""",
                (node_id, project_id, int(row["source_row"]), sequence, parent_id, int(row["depth"]),
                 row["part_number"], row["description"], None, row["branch_name"],
                 row["subsystem"], row["model_feature"], row["comments"], row["tracker_status"],
                 row["planned_area"], json.dumps(row["raw_levels"], ensure_ascii=False), timestamp),
            )
    return len(nodes)

@cached_store_read
def project_models(project_id: str) -> pd.DataFrame:
    return pd.DataFrame(query("SELECT * FROM project_models WHERE project_id = ? ORDER BY model_number", (project_id,)))

@cached_store_read
def fishbone_plan_snapshot(project_id: str) -> dict:
    """Capture the framework and every section-linked record needed for saved-state Undo."""
    with connection() as conn:
        return {
            "sections": [dict(row) for row in conn.execute(
                "SELECT * FROM assembly_sections WHERE project_id=?", (project_id,)
            ).fetchall()],
            "assignments": [dict(row) for row in conn.execute(
                "SELECT * FROM fishbone_part_assignments WHERE project_id=?", (project_id,)
            ).fetchall()],
            "assembly_components": [dict(row) for row in conn.execute(
                "SELECT * FROM manufacturing_assembly_components WHERE project_id=?",
                (project_id,),
            ).fetchall()],
            "yamazumi_section_references": [dict(row) for row in conn.execute(
                "SELECT id, section_id FROM yamazumi_areas WHERE project_id=?",
                (project_id,),
            ).fetchall()],
            "process_section_references": [dict(row) for row in conn.execute(
                "SELECT id, section_id FROM process_part_groups WHERE project_id=?",
                (project_id,),
            ).fetchall()],
            "assembly_section_references": [dict(row) for row in conn.execute(
                """SELECT id, built_section_id, installed_section_id, updated_at
                   FROM manufacturing_assemblies WHERE project_id=?""",
                (project_id,),
            ).fetchall()],
            "assembly_grid_categories": [dict(row) for row in conn.execute(
                "SELECT * FROM assembly_grid_categories WHERE project_id=?",
                (project_id,),
            ).fetchall()],
            "assembly_grid_model_mappings": [dict(row) for row in conn.execute(
                "SELECT * FROM assembly_grid_model_mappings WHERE project_id=?",
                (project_id,),
            ).fetchall()],
            "assembly_grid_feature_visibility": [dict(row) for row in conn.execute(
                "SELECT * FROM assembly_grid_feature_visibility WHERE project_id=?",
                (project_id,),
            ).fetchall()],
            "connections": [dict(row) for row in conn.execute(
                "SELECT * FROM assembly_section_connections WHERE project_id=?",
                (project_id,),
            ).fetchall()],
        }

@cached_store_read
def fishbone_assignment_snapshot(project_id: str) -> list[dict]:
    """Capture assigned part uses without changing the assembly framework."""
    with connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM fishbone_part_assignments WHERE project_id=?", (project_id,)
        ).fetchall()]

def restore_fishbone_plan_snapshot(project_id: str, snapshot: dict) -> None:
    """Restore a framework snapshot and its section-linked records atomically."""
    sections = snapshot.get("sections", [])
    assignments = snapshot.get("assignments", [])
    assembly_components = snapshot.get("assembly_components", [])
    grid_categories = snapshot.get("assembly_grid_categories", [])
    grid_mappings = snapshot.get("assembly_grid_model_mappings", [])
    grid_feature_visibility = snapshot.get(
        "assembly_grid_feature_visibility", []
    )
    with connection() as conn:
        # The framework is rebuilt as one unit. Temporarily release every section
        # reference so RESTRICT relationships cannot leave a partial restore.
        conn.execute(
            "UPDATE yamazumi_areas SET section_id=NULL WHERE project_id=?", (project_id,)
        )
        conn.execute(
            "UPDATE process_part_groups SET section_id=NULL WHERE project_id=?", (project_id,)
        )
        conn.execute(
            """UPDATE manufacturing_assemblies
               SET built_section_id=NULL, installed_section_id=NULL
               WHERE project_id=?""",
            (project_id,),
        )
        # Category section references are RESTRICT relationships. Remove the
        # project-owned grid state before rebuilding the framework, then restore
        # the same stable category, mapping, and preference IDs afterward.
        conn.execute(
            "DELETE FROM assembly_grid_model_mappings WHERE project_id=?", (project_id,)
        )
        conn.execute(
            "DELETE FROM assembly_grid_categories WHERE project_id=?", (project_id,)
        )
        conn.execute(
            "DELETE FROM assembly_grid_feature_visibility WHERE project_id=?",
            (project_id,),
        )
        saved_option_assignments = [
            dict(row)
            for row in conn.execute(
                """SELECT option.id, option.handling_type, option.fishbone_assignment_id
                   FROM process_part_options option
                   JOIN process_part_groups group_row ON group_row.id = option.group_id
                   WHERE group_row.project_id = ? AND option.fishbone_assignment_id IS NOT NULL""",
                (project_id,),
            ).fetchall()
        ]
        saved_pits_occurrences = [
            dict(row)
            for row in conn.execute(
                """SELECT id, confirmed_section_id, approved_assignment_id
                   FROM pits_bom_occurrences
                   WHERE project_id = ?
                     AND (confirmed_section_id IS NOT NULL OR approved_assignment_id IS NOT NULL)""",
                (project_id,),
            ).fetchall()
        ]
        if saved_option_assignments:
            opt_ids = [str(r["id"]) for r in saved_option_assignments]
            opt_placeholders = ",".join("?" for _ in opt_ids)
            conn.execute(
                f"UPDATE process_part_options SET fishbone_assignment_id=NULL WHERE id IN ({opt_placeholders})",
                tuple(opt_ids),
            )
        if saved_pits_occurrences:
            conn.execute(
                "UPDATE pits_bom_occurrences SET confirmed_section_id=NULL, approved_assignment_id=NULL WHERE project_id=?",
                (project_id,),
            )
        conn.execute("DELETE FROM assembly_section_connections WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM fishbone_part_assignments WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM assembly_sections WHERE project_id=?", (project_id,))
        # Insert parents and children with empty parent IDs first, then reconnect them.
        section_rows = [{**row, "parent_id": None} for row in sections]
        _insert_snapshot_rows(conn, "assembly_sections", section_rows)
        for row in sections:
            if row.get("parent_id"):
                conn.execute(
                    "UPDATE assembly_sections SET parent_id=? WHERE id=? AND project_id=?",
                    (row["parent_id"], row["id"], project_id),
                )
        _insert_snapshot_rows(conn, "assembly_section_connections", snapshot.get("connections", []))
        _insert_snapshot_rows(conn, "fishbone_part_assignments", assignments)
        restored_assignment_ids = {str(r.get("id")) for r in assignments if r.get("id")}
        restored_section_ids = {str(r.get("id")) for r in sections if r.get("id")}
        for row in saved_option_assignments:
            aid = str(row.get("fishbone_assignment_id") or "")
            if aid in restored_assignment_ids:
                conn.execute(
                    "UPDATE process_part_options SET fishbone_assignment_id=? WHERE id=?",
                    (aid, row["id"]),
                )
            else:
                conn.execute(
                    "UPDATE process_part_options SET handling_type=NULL, fishbone_assignment_id=NULL WHERE id=?",
                    (row["id"],),
                )
        for row in saved_pits_occurrences:
            sec_id = row.get("confirmed_section_id")
            aid = row.get("approved_assignment_id")
            conn.execute(
                """UPDATE pits_bom_occurrences
                   SET confirmed_section_id=?, approved_assignment_id=?
                   WHERE id=? AND project_id=?""",
                (
                    sec_id if str(sec_id or "") in restored_section_ids else None,
                    aid if str(aid or "") in restored_assignment_ids else None,
                    row["id"],
                    project_id,
                ),
            )
        _insert_snapshot_rows(conn, "manufacturing_assembly_components", assembly_components)
        _insert_snapshot_rows(conn, "assembly_grid_categories", grid_categories)
        _insert_snapshot_rows(conn, "assembly_grid_model_mappings", grid_mappings)
        _insert_snapshot_rows(
            conn, "assembly_grid_feature_visibility", grid_feature_visibility
        )
        for row in snapshot.get("yamazumi_section_references", []):
            conn.execute(
                "UPDATE yamazumi_areas SET section_id=? WHERE id=? AND project_id=?",
                (row.get("section_id"), row.get("id"), project_id),
            )
        for row in snapshot.get("process_section_references", []):
            conn.execute(
                "UPDATE process_part_groups SET section_id=? WHERE id=? AND project_id=?",
                (row.get("section_id"), row.get("id"), project_id),
            )
        for row in snapshot.get("assembly_section_references", []):
            conn.execute(
                """UPDATE manufacturing_assemblies
                   SET built_section_id=?, installed_section_id=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (
                    row.get("built_section_id"),
                    row.get("installed_section_id"),
                    row.get("updated_at"),
                    row.get("id"),
                    project_id,
                ),
            )

def restore_fishbone_assignment_snapshot(project_id: str, snapshot: list[dict]) -> None:
    """Restore the last set of fishbone part uses."""
    with connection() as conn:
        saved_option_assignments = [
            dict(row)
            for row in conn.execute(
                """SELECT option.id, option.handling_type, option.fishbone_assignment_id
                   FROM process_part_options option
                   JOIN process_part_groups group_row ON group_row.id = option.group_id
                   WHERE group_row.project_id = ? AND option.fishbone_assignment_id IS NOT NULL""",
                (project_id,),
            ).fetchall()
        ]
        saved_pits_occurrences = [
            dict(row)
            for row in conn.execute(
                """SELECT id, approved_assignment_id
                   FROM pits_bom_occurrences
                   WHERE project_id = ? AND approved_assignment_id IS NOT NULL""",
                (project_id,),
            ).fetchall()
        ]
        if saved_option_assignments:
            opt_ids = [str(r["id"]) for r in saved_option_assignments]
            opt_placeholders = ",".join("?" for _ in opt_ids)
            conn.execute(
                f"UPDATE process_part_options SET fishbone_assignment_id=NULL WHERE id IN ({opt_placeholders})",
                tuple(opt_ids),
            )
        if saved_pits_occurrences:
            conn.execute(
                "UPDATE pits_bom_occurrences SET approved_assignment_id=NULL WHERE project_id=?",
                (project_id,),
            )
        conn.execute("DELETE FROM fishbone_part_assignments WHERE project_id=?", (project_id,))
        _insert_snapshot_rows(conn, "fishbone_part_assignments", snapshot)
        restored_assignment_ids = {str(r.get("id")) for r in snapshot if r.get("id")}
        for row in saved_option_assignments:
            aid = str(row.get("fishbone_assignment_id") or "")
            if aid in restored_assignment_ids:
                conn.execute(
                    "UPDATE process_part_options SET fishbone_assignment_id=? WHERE id=?",
                    (aid, row["id"]),
                )
            else:
                conn.execute(
                    "UPDATE process_part_options SET handling_type=NULL, fishbone_assignment_id=NULL WHERE id=?",
                    (row["id"],),
                )
        for row in saved_pits_occurrences:
            aid = row.get("approved_assignment_id")
            if str(aid or "") in restored_assignment_ids:
                conn.execute(
                    "UPDATE pits_bom_occurrences SET approved_assignment_id=? WHERE id=? AND project_id=?",
                    (aid, row["id"], project_id),
                )

def update_fishbone_assignment_use(
    project_id: str,
    assignment_id: str,
    use_description: str,
    editor_name: str = "",
) -> None:
    """Update the use / installation location description for a fishbone part assignment."""
    clean_use = str(use_description or "").strip()
    timestamp = now_iso()
    with connection() as conn:
        current = conn.execute(
            "SELECT id, part_id, section_id, use_description FROM fishbone_part_assignments WHERE id=? AND project_id=?",
            (assignment_id, project_id),
        ).fetchone()
        if not current:
            raise ValueError("Fishbone assignment not found.")
        conn.execute(
            "UPDATE fishbone_part_assignments SET use_description=?, updated_at=? WHERE id=? AND project_id=?",
            (clean_use, timestamp, assignment_id, project_id),
        )
        record_audit_event(
            project_id,
            "Fishbone part assignments",
            "Update use location",
            1,
            str(editor_name or "").strip(),
            {
                "assignment_id": assignment_id,
                "part_id": current["part_id"],
                "section_id": current["section_id"],
                "old_use_description": current["use_description"],
                "new_use_description": clean_use,
            },
            _conn=conn,
        )

@cached_store_read
def assembly_section_connections(project_id: str) -> pd.DataFrame:
    """Return all directed flow connections between sections for a project."""
    return pd.DataFrame(query(
        """SELECT * FROM assembly_section_connections
           WHERE project_id = ?
           ORDER BY sequence, created_at""",
        (project_id,),
    ))

def save_assembly_section_connection(
    project_id: str,
    from_section_id: str,
    to_section_id: str,
    connection_type: str,
    sequence: int = 10,
    editor_name: str = "",
) -> str:
    """Create or update a flow connection between two sections."""
    from_id = str(from_section_id).strip()
    to_id = str(to_section_id).strip()
    conn_type = str(connection_type).strip().lower()
    if not from_id or not to_id:
        raise ValueError("Both source and destination sections must be provided.")
    if from_id == to_id:
        raise ValueError("A section cannot connect to itself.")
    if conn_type not in {"subassembly", "series", "parallel"}:
        raise ValueError("Connection type must be 'subassembly', 'series', or 'parallel'.")
    timestamp = now_iso()
    with connection() as conn:
        sections = conn.execute(
            "SELECT id, name, section_type, parent_id FROM assembly_sections WHERE id IN (?, ?) AND project_id = ?",
            (from_id, to_id, project_id),
        ).fetchall()
        if len(sections) < 2:
            raise ValueError("One or both sections could not be found in this project.")
        sec_by_id = {row["id"]: row for row in sections}
        from_sec = sec_by_id[from_id]
        to_sec = sec_by_id[to_id]

        existing = conn.execute(
            """SELECT id, connection_type FROM assembly_section_connections
               WHERE project_id = ? AND from_section_id = ? AND to_section_id = ?""",
            (project_id, from_id, to_id),
        ).fetchone()
        if existing:
            conn_id = str(existing["id"])
            conn.execute(
                """UPDATE assembly_section_connections
                   SET connection_type = ?, sequence = ?, updated_at = ?
                   WHERE id = ?""",
                (conn_type, sequence, timestamp, conn_id),
            )
        else:
            conn_id = str(uuid4())
            conn.execute(
                """INSERT INTO assembly_section_connections (
                       id, project_id, from_section_id, to_section_id, connection_type, sequence, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (conn_id, project_id, from_id, to_id, conn_type, sequence, timestamp, timestamp),
            )
        if conn_type in {"subassembly", "parallel"} and from_sec["section_type"] in {"Assembly", "Subassembly"}:
            conn.execute(
                "UPDATE assembly_sections SET parent_id = ?, updated_at = ? WHERE id = ? AND project_id = ?",
                (to_id, timestamp, from_id, project_id),
            )
        record_audit_event(
            project_id,
            "Fishbone framework",
            "Save connection",
            1,
            str(editor_name or "").strip(),
            {
                "connection_id": conn_id,
                "from_section_id": from_id,
                "from_section_name": from_sec["name"],
                "to_section_id": to_id,
                "to_section_name": to_sec["name"],
                "connection_type": conn_type,
            },
            _conn=conn,
        )
        return conn_id

def delete_assembly_section_connection(
    project_id: str,
    connection_id: str,
    editor_name: str = "",
) -> None:
    """Delete a flow connection and repair subassembly parent_id if needed."""
    timestamp = now_iso()
    with connection() as conn:
        row = conn.execute(
            """SELECT id, from_section_id, to_section_id, connection_type
               FROM assembly_section_connections WHERE id = ? AND project_id = ?""",
            (connection_id, project_id),
        ).fetchone()
        if not row:
            return
        conn.execute(
            "DELETE FROM assembly_section_connections WHERE id = ? AND project_id = ?",
            (connection_id, project_id),
        )
        if row["connection_type"] == "subassembly":
            other = conn.execute(
                """SELECT to_section_id FROM assembly_section_connections
                   WHERE project_id = ? AND from_section_id = ? AND connection_type = 'subassembly'
                   LIMIT 1""",
                (project_id, row["from_section_id"]),
            ).fetchone()
            new_parent = other["to_section_id"] if other else None
            conn.execute(
                "UPDATE assembly_sections SET parent_id = ?, updated_at = ? WHERE id = ? AND project_id = ?",
                (new_parent, timestamp, row["from_section_id"], project_id),
            )
        record_audit_event(
            project_id,
            "Fishbone framework",
            "Delete connection",
            1,
            str(editor_name or "").strip(),
            {
                "connection_id": connection_id,
                "from_section_id": row["from_section_id"],
                "to_section_id": row["to_section_id"],
                "connection_type": row["connection_type"],
            },
            _conn=conn,
        )


def move_assembly_section_connection(
    project_id: str,
    connection_id: str,
    new_to_section_id: str,
    editor_name: str = "",
) -> None:
    """Move an existing flow connection to a new destination section."""
    cid = str(connection_id).strip()
    to_id = str(new_to_section_id).strip()
    if not cid:
        raise ValueError("Connection ID must be provided.")
    if not to_id:
        raise ValueError("Target destination section must be provided.")
    timestamp = now_iso()
    with connection() as conn:
        row = conn.execute(
            """SELECT id, from_section_id, to_section_id, connection_type, sequence
               FROM assembly_section_connections WHERE id = ? AND project_id = ?""",
            (cid, project_id),
        ).fetchone()
        if not row:
            raise ValueError("Connection could not be found.")
        from_id = str(row["from_section_id"])
        if from_id == to_id:
            raise ValueError("A section cannot connect to itself.")

        # Verify destination section exists
        to_sec = conn.execute(
            "SELECT id, name FROM assembly_sections WHERE id = ? AND project_id = ?",
            (to_id, project_id),
        ).fetchone()
        if not to_sec:
            raise ValueError("Target destination section could not be found.")

        from_sec = conn.execute(
            "SELECT id, name, section_type FROM assembly_sections WHERE id = ? AND project_id = ?",
            (from_id, project_id),
        ).fetchone()

        # Check if a connection from from_id to to_id already exists
        dup = conn.execute(
            """SELECT id FROM assembly_section_connections
               WHERE project_id = ? AND from_section_id = ? AND to_section_id = ? AND id != ?""",
            (project_id, from_id, to_id, cid),
        ).fetchone()
        if dup:
            conn.execute("DELETE FROM assembly_section_connections WHERE id = ?", (cid,))
        else:
            conn.execute(
                """UPDATE assembly_section_connections
                   SET to_section_id = ?, updated_at = ?
                   WHERE id = ? AND project_id = ?""",
                (to_id, timestamp, cid, project_id),
            )

        if str(row["connection_type"]) in {"subassembly", "parallel"} and from_sec and from_sec["section_type"] in {"Assembly", "Subassembly"}:
            conn.execute(
                "UPDATE assembly_sections SET parent_id = ?, updated_at = ? WHERE id = ? AND project_id = ?",
                (to_id, timestamp, from_id, project_id),
            )

        record_audit_event(
            project_id,
            "Fishbone framework",
            "Move connection",
            1,
            str(editor_name or "").strip(),
            {
                "connection_id": cid,
                "from_section_id": from_id,
                "from_section_name": from_sec["name"] if from_sec else from_id,
                "old_to_section_id": str(row["to_section_id"]),
                "new_to_section_id": to_id,
                "new_to_section_name": to_sec["name"],
                "connection_type": str(row["connection_type"]),
            },
            _conn=conn,
        )


def save_fishbone_canvas_positions(
    project_id: str,
    positions: dict[str, tuple[int | None, int | None]],
    editor_name: str = "",
) -> None:
    """Persist grid_x, grid_y coordinates for Fishbone sections."""
    if not positions:
        return
    timestamp = now_iso()
    with connection() as conn:
        for section_id, coords in positions.items():
            gx = coords[0] if coords else None
            gy = coords[1] if coords else None
            conn.execute(
                """UPDATE assembly_sections
                   SET grid_x = ?, grid_y = ?, updated_at = ?
                   WHERE id = ? AND project_id = ?""",
                (gx, gy, timestamp, section_id, project_id),
            )
        record_audit_event(
            project_id,
            "Fishbone framework",
            "Update canvas layout",
            len(positions),
            str(editor_name or "").strip(),
            {"positions_count": len(positions)},
            _conn=conn,
        )

def save_fishbone_canvas_draft(
    project_id: str,
    *,
    positions: dict[str, tuple[int | None, int | None]] | None = None,
    connections: list[dict] | None = None,
    deleted_connection_ids: list[str] | None = None,
    new_assignments: list[dict] | None = None,
    updated_assignments: list[dict] | None = None,
    deleted_assignment_ids: list[str] | None = None,
    editor_name: str = "",
) -> dict[str, int]:
    """Atomically commit canvas positions, connections, and part assignments from a visual edit draft."""
    timestamp = now_iso()
    positions_saved = 0
    conns_saved = 0
    conns_deleted = 0
    assignments_saved = 0
    assignments_updated = 0
    assignments_deleted = 0
    with connection() as conn:
        if positions:
            for section_id, coords in positions.items():
                gx = coords[0] if coords else None
                gy = coords[1] if coords else None
                conn.execute(
                    """UPDATE assembly_sections
                       SET grid_x = ?, grid_y = ?, updated_at = ?
                       WHERE id = ? AND project_id = ?""",
                    (gx, gy, timestamp, section_id, project_id),
                )
                positions_saved += 1
        if deleted_connection_ids:
            for cid in deleted_connection_ids:
                row = conn.execute(
                    "SELECT from_section_id, connection_type FROM assembly_section_connections WHERE id = ? AND project_id = ?",
                    (cid, project_id),
                ).fetchone()
                if row:
                    conn.execute("DELETE FROM assembly_section_connections WHERE id = ? AND project_id = ?", (cid, project_id))
                    conns_deleted += 1
                    if row["connection_type"] in {"subassembly", "parallel"}:
                        other = conn.execute(
                            "SELECT to_section_id FROM assembly_section_connections WHERE project_id=? AND from_section_id=? AND connection_type IN ('subassembly', 'parallel') LIMIT 1",
                            (project_id, row["from_section_id"]),
                        ).fetchone()
                        new_parent = other["to_section_id"] if other else None
                        conn.execute("UPDATE assembly_sections SET parent_id=?, updated_at=? WHERE id=? AND project_id=?", (new_parent, timestamp, row["from_section_id"], project_id))
        if connections:
            for c in connections:
                from_id = str(c.get("from_section_id") or "").strip()
                to_id = str(c.get("to_section_id") or "").strip()
                c_type = str(c.get("connection_type") or "subassembly").strip().lower()
                seq = int(c.get("sequence") or 10)
                if not from_id or not to_id or from_id == to_id:
                    continue
                cid = str(c.get("id") or uuid4())
                conn.execute(
                    """INSERT INTO assembly_section_connections (
                           id, project_id, from_section_id, to_section_id, connection_type, sequence, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(project_id, from_section_id, to_section_id)
                       DO UPDATE SET connection_type = excluded.connection_type, sequence = excluded.sequence, updated_at = excluded.updated_at""",
                    (cid, project_id, from_id, to_id, c_type, seq, timestamp, timestamp),
                )
                conns_saved += 1
                if c_type in {"subassembly", "parallel"}:
                    conn.execute(
                        "UPDATE assembly_sections SET parent_id=?, updated_at=? WHERE id=? AND project_id=? AND section_type IN ('Assembly', 'Subassembly')",
                        (to_id, timestamp, from_id, project_id),
                    )
        if updated_assignments:
            for ua in updated_assignments:
                ua_id = str(ua.get("id") or ua.get("assignment_id") or "").strip()
                if ua_id:
                    existing_row = conn.execute(
                        "SELECT step_number, section_id, sequence, quantity, use_description FROM fishbone_part_assignments WHERE id = ? AND project_id = ?",
                        (ua_id, project_id),
                    ).fetchone()
                    if not existing_row:
                        continue
                    step_num = int(ua.get("step_number") if ua.get("step_number") is not None else (existing_row["step_number"] or 1))
                    target_sid = str(ua.get("section_id") or existing_row["section_id"] or "").strip()
                    seq = int(ua.get("sequence") if ua.get("sequence") is not None else (existing_row["sequence"] or 10))
                    qty = float(ua.get("quantity") if ua.get("quantity") is not None else (existing_row["quantity"] or 1.0))
                    use_desc = str(ua.get("use_description") if ua.get("use_description") is not None else (existing_row["use_description"] or "")).strip()
                    conn.execute(
                        """UPDATE fishbone_part_assignments
                           SET step_number = ?, section_id = ?, sequence = ?, quantity = ?, use_description = ?, updated_at = ?
                           WHERE id = ? AND project_id = ?""",
                        (step_num, target_sid, seq, qty, use_desc, timestamp, ua_id, project_id),
                    )
                    if target_sid != str(existing_row["section_id"] or ""):
                        conn.execute(
                            """UPDATE process_part_options
                               SET handling_type = NULL, fishbone_assignment_id = NULL, updated_at = ?
                               WHERE fishbone_assignment_id = ?
                                 AND group_id IN (
                                     SELECT id FROM process_part_groups
                                     WHERE project_id = ? AND COALESCE(section_id, '') <> ?
                                 )""",
                            (timestamp, ua_id, project_id, target_sid),
                        )
                        conn.execute(
                            """UPDATE pits_bom_occurrences
                               SET confirmed_section_id = ?, updated_at = ?
                               WHERE project_id = ? AND approved_assignment_id = ?""",
                            (target_sid, timestamp, project_id, ua_id),
                        )
                    assignments_updated += 1
        if new_assignments:
            for a in new_assignments:
                pid = str(a.get("part_id") or "").strip()
                sid = str(a.get("section_id") or "").strip()
                qty = float(a.get("quantity") or 1.0)
                use_desc = str(a.get("use_description") or "").strip()
                if pid and sid:
                    aid = str(a.get("id") or uuid4())
                    conn.execute(
                        """INSERT INTO fishbone_part_assignments (
                               id, project_id, part_id, section_id, step_number, sequence, quantity, use_description, updated_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (aid, project_id, pid, sid, int(a.get("step_number") or 1), int(a.get("sequence") or 10), qty, use_desc, timestamp),
                    )
                    assignments_saved += 1
        if deleted_assignment_ids:
            clean_deleted_ids = [
                str(aid).strip()
                for aid in dict.fromkeys(deleted_assignment_ids)
                if str(aid or "").strip()
            ]
            if clean_deleted_ids:
                _release_fishbone_assignment_references(
                    conn, project_id, clean_deleted_ids, timestamp, detach_pits_occurrences=True
                )
                for aid in clean_deleted_ids:
                    conn.execute(
                        "DELETE FROM fishbone_part_assignments WHERE id = ? AND project_id = ?",
                        (aid, project_id),
                    )
                    assignments_deleted += 1
        total_changes = positions_saved + conns_saved + conns_deleted + assignments_saved + assignments_updated + assignments_deleted
        record_audit_event(
            project_id,
            "Fishbone framework",
            "Save canvas draft",
            total_changes,
            str(editor_name or "").strip(),
            {
                "positions_saved": positions_saved,
                "connections_saved": conns_saved,
                "connections_deleted": conns_deleted,
                "assignments_saved": assignments_saved,
                "assignments_updated": assignments_updated,
                "assignments_deleted": assignments_deleted,
            },
            _conn=conn,
        )
    return {
        "positions_saved": positions_saved,
        "connections_saved": conns_saved,
        "connections_deleted": conns_deleted,
        "assignments_saved": assignments_saved,
        "assignments_updated": assignments_updated,
        "assignments_deleted": assignments_deleted,
    }


def clear_interactive_fishbone(
    project_id: str,
    mode: str,
    section_ids: list[str] | None = None,
    editor_name: str = "",
) -> dict:
    """Clear placed parts and/or delete sections from the Interactive Fishbone canvas."""
    clean_mode = str(mode or "").strip().lower()
    if clean_mode not in {"clear_parts", "delete_sections", "delete_empty_sections", "both"}:
        raise ValueError(
            "Invalid clear mode. Expected 'clear_parts', 'delete_sections', 'delete_empty_sections', or 'both'."
        )
    timestamp = now_iso()
    parts_cleared = 0
    sections_deleted = 0
    connections_deleted = 0
    yamazumi_areas_deleted = 0
    process_groups_deleted = 0
    deleted_section_ids: list[str] = []
    deleted_section_names: list[str] = []

    with connection() as conn:
        if clean_mode == "clear_parts":
            if section_ids is not None:
                clean_sec_ids = [
                    str(s).strip() for s in dict.fromkeys(section_ids) if str(s or "").strip()
                ]
                if clean_sec_ids:
                    sec_placeholders = ", ".join("?" for _ in clean_sec_ids)
                    assignment_ids = [
                        str(r[0])
                        for r in conn.execute(
                            f"SELECT id FROM fishbone_part_assignments WHERE project_id=? AND section_id IN ({sec_placeholders})",
                            (project_id, *clean_sec_ids),
                        ).fetchall()
                    ]
                else:
                    assignment_ids = []
            else:
                assignment_ids = [
                    str(r[0])
                    for r in conn.execute(
                        "SELECT id FROM fishbone_part_assignments WHERE project_id=?",
                        (project_id,),
                    ).fetchall()
                ]
            if assignment_ids:
                _release_fishbone_assignment_references(
                    conn, project_id, assignment_ids, timestamp, detach_pits_occurrences=True
                )
                aid_placeholders = ", ".join("?" for _ in assignment_ids)
                conn.execute(
                    f"""DELETE FROM manufacturing_assembly_components
                        WHERE project_id = ? AND fishbone_assignment_id IN ({aid_placeholders})""",
                    (project_id, *assignment_ids),
                )
                parts_cleared = conn.execute(
                    f"DELETE FROM fishbone_part_assignments WHERE project_id=? AND id IN ({aid_placeholders})",
                    (project_id, *assignment_ids),
                ).rowcount
        else:
            all_sec_rows = conn.execute(
                "SELECT id, name, parent_id FROM assembly_sections WHERE project_id=? ORDER BY sequence, name",
                (project_id,),
            ).fetchall()
            if clean_mode == "both" or (clean_mode == "delete_sections" and section_ids is None):
                affected_rows = list(all_sec_rows)
            elif clean_mode == "delete_empty_sections":
                sec_with_parts = {
                    str(r[0])
                    for r in conn.execute(
                        "SELECT DISTINCT section_id FROM fishbone_part_assignments WHERE project_id=?",
                        (project_id,),
                    ).fetchall()
                }
                parent_by_id = {str(r["id"]): str(r["parent_id"] or "") for r in all_sec_rows}
                protected_ids = set(sec_with_parts)
                for sid in list(sec_with_parts):
                    curr = parent_by_id.get(sid, "")
                    visited = set()
                    while curr and curr not in visited:
                        visited.add(curr)
                        protected_ids.add(curr)
                        curr = parent_by_id.get(curr, "")
                affected_rows = [r for r in all_sec_rows if str(r["id"]) not in protected_ids]
            else:
                clean_sec_ids = [
                    str(s).strip() for s in dict.fromkeys(section_ids or []) if str(s or "").strip()
                ]
                if clean_sec_ids:
                    affected_rows = _assembly_section_delete_rows(conn, project_id, clean_sec_ids)
                else:
                    affected_rows = []

            affected_ids = [str(r["id"]) for r in affected_rows]
            deleted_section_ids = affected_ids
            deleted_section_names = [str(r["name"]) for r in affected_rows]

            if clean_mode == "both":
                all_assignment_ids = [
                    str(r[0])
                    for r in conn.execute(
                        "SELECT id FROM fishbone_part_assignments WHERE project_id=?",
                        (project_id,),
                    ).fetchall()
                ]
            elif affected_ids:
                sec_placeholders = ", ".join("?" for _ in affected_ids)
                all_assignment_ids = [
                    str(r[0])
                    for r in conn.execute(
                        f"SELECT id FROM fishbone_part_assignments WHERE project_id=? AND section_id IN ({sec_placeholders})",
                        (project_id, *affected_ids),
                    ).fetchall()
                ]
            else:
                all_assignment_ids = []

            if all_assignment_ids:
                _release_fishbone_assignment_references(
                    conn, project_id, all_assignment_ids, timestamp, detach_pits_occurrences=True
                )
                aid_placeholders = ", ".join("?" for _ in all_assignment_ids)
                conn.execute(
                    f"""DELETE FROM manufacturing_assembly_components
                        WHERE project_id = ? AND fishbone_assignment_id IN ({aid_placeholders})""",
                    (project_id, *all_assignment_ids),
                )
                parts_cleared = conn.execute(
                    f"DELETE FROM fishbone_part_assignments WHERE project_id=? AND id IN ({aid_placeholders})",
                    (project_id, *all_assignment_ids),
                ).rowcount

            if affected_ids:
                placeholders = ", ".join("?" for _ in affected_ids)
                conn.execute(
                    f"""UPDATE pits_bom_occurrences
                        SET review_status = CASE WHEN review_status = 'Approved' THEN 'Needs review' ELSE review_status END,
                            confirmed_section_id = NULL,
                            approved_assignment_id = NULL,
                            reviewed_source_fingerprint = CASE WHEN review_status = 'Approved' THEN NULL ELSE reviewed_source_fingerprint END,
                            last_reviewed_import_id = CASE WHEN review_status = 'Approved' THEN NULL ELSE last_reviewed_import_id END,
                            source_state = CASE WHEN source_state = 'Missing' THEN 'Missing' ELSE 'New' END,
                            updated_at = ?
                        WHERE project_id = ? AND confirmed_section_id IN ({placeholders})""",
                    (timestamp, project_id, *affected_ids),
                )
                conn.execute(
                    f"""DELETE FROM yamazumi_work_regions WHERE area_id IN (
                        SELECT id FROM yamazumi_areas WHERE project_id=? AND section_id IN ({placeholders})
                    )""",
                    (project_id, *affected_ids),
                )
                conn.execute(
                    f"""DELETE FROM yamazumi_elements WHERE area_id IN (
                        SELECT id FROM yamazumi_areas WHERE project_id=? AND section_id IN ({placeholders})
                    )""",
                    (project_id, *affected_ids),
                )
                conn.execute(
                    f"""DELETE FROM yamazumi_pitches WHERE area_id IN (
                        SELECT id FROM yamazumi_areas WHERE project_id=? AND section_id IN ({placeholders})
                    )""",
                    (project_id, *affected_ids),
                )
                yamazumi_areas_deleted = conn.execute(
                    f"DELETE FROM yamazumi_areas WHERE project_id=? AND section_id IN ({placeholders})",
                    (project_id, *affected_ids),
                ).rowcount
                process_groups_deleted = conn.execute(
                    f"DELETE FROM process_part_groups WHERE project_id=? AND section_id IN ({placeholders})",
                    (project_id, *affected_ids),
                ).rowcount
                conn.execute(
                    f"""DELETE FROM assembly_grid_model_mappings
                        WHERE project_id=? AND category_id IN (
                            SELECT id FROM assembly_grid_categories
                            WHERE project_id=? AND (section_id IN ({placeholders}) OR installed_section_id IN ({placeholders}))
                        )""",
                    (project_id, project_id, *affected_ids, *affected_ids),
                )
                conn.execute(
                    f"DELETE FROM assembly_grid_feature_visibility WHERE project_id=? AND section_id IN ({placeholders})",
                    (project_id, *affected_ids),
                )
                conn.execute(
                    f"""DELETE FROM assembly_grid_categories
                        WHERE project_id=? AND (section_id IN ({placeholders}) OR installed_section_id IN ({placeholders}))""",
                    (project_id, *affected_ids, *affected_ids),
                )
                conn.execute(
                    f"UPDATE manufacturing_assemblies SET built_section_id=NULL WHERE project_id=? AND built_section_id IN ({placeholders})",
                    (project_id, *affected_ids),
                )
                conn.execute(
                    f"UPDATE manufacturing_assemblies SET installed_section_id=NULL WHERE project_id=? AND installed_section_id IN ({placeholders})",
                    (project_id, *affected_ids),
                )
                connections_deleted = conn.execute(
                    f"""DELETE FROM assembly_section_connections
                        WHERE project_id=? AND (from_section_id IN ({placeholders}) OR to_section_id IN ({placeholders}))""",
                    (project_id, *affected_ids, *affected_ids),
                ).rowcount
                conn.execute(
                    f"UPDATE assembly_sections SET parent_id=NULL WHERE project_id=? AND parent_id IN ({placeholders})",
                    (project_id, *affected_ids),
                )
                sections_deleted = conn.execute(
                    f"DELETE FROM assembly_sections WHERE project_id=? AND id IN ({placeholders})",
                    (project_id, *affected_ids),
                ).rowcount

        record_audit_event(
            project_id,
            "Fishbone framework",
            "Clear interactive fishbone",
            parts_cleared + sections_deleted,
            str(editor_name or "").strip(),
            {
                "mode": clean_mode,
                "parts_cleared": parts_cleared,
                "sections_deleted": sections_deleted,
                "deleted_section_names": deleted_section_names,
                "connections_deleted": connections_deleted,
                "yamazumi_areas_deleted": yamazumi_areas_deleted,
                "process_groups_deleted": process_groups_deleted,
            },
            _conn=conn,
        )

    return {
        "mode": clean_mode,
        "parts_cleared": parts_cleared,
        "sections_deleted": sections_deleted,
        "deleted_section_ids": deleted_section_ids,
        "deleted_section_names": deleted_section_names,
        "connections_deleted": connections_deleted,
        "yamazumi_areas_deleted": yamazumi_areas_deleted,
        "process_groups_deleted": process_groups_deleted,
    }

__domain_exports__ = ['assembly_sections', 'assembly_section_walk_order', '_assembly_section_delete_rows', '_assembly_section_target_validation', '_merge_yamazumi_areas_for_section_delete', 'assembly_section_delete_target_validation', 'assembly_section_delete_impact', 'delete_assembly_sections', '_create_yamazumi_areas_for_section', 'yamazumi_area_creation_summary', 'add_assembly_section', 'reorder_assembly_section', 'update_assembly_section_rows', 'fishbone_part_assignments', 'search_parts_and_fishbone', 'create_part_and_assign_to_section', 'move_fishbone_part_assignment', 'reorder_fishbone_part_assignments', 'assign_parts_to_section', 'delete_fishbone_part_assignments', 'delete_fishbone_part_assignment', 'replace_fishbone_part_assignments', 'save_fishbone_plan', 'replace_fishbone_nodes', 'import_fishbone_nodes', 'project_models', 'fishbone_plan_snapshot', 'fishbone_assignment_snapshot', 'restore_fishbone_plan_snapshot', 'restore_fishbone_assignment_snapshot', 'update_fishbone_assignment_use', 'assembly_section_connections', 'save_assembly_section_connection', 'delete_assembly_section_connection', 'move_assembly_section_connection', 'save_fishbone_canvas_positions', 'save_fishbone_canvas_draft', 'clear_interactive_fishbone']
for _export_name in __domain_exports__:
    if callable(globals()[_export_name]):
        globals()[_export_name] = _db_core.domain_entrypoint(globals()[_export_name])
_db_core.register_domain_module(_sys.modules[__name__], __domain_exports__)
