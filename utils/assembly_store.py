"""Domain persistence extracted from the historical utils.store module."""

from __future__ import annotations

import sys as _sys
from utils import db_core as _db_core

globals().update({name: value for name, value in vars(_db_core).items() if not name.startswith('__')})

ASSEMBLY_PLANNING_REASONS = {
    "Purchased complete", "Separate build process", "Inventory buffer",
    "Independent test or traceability", "Other",
}

ASSEMBLY_SOURCING_DECISIONS = {"Undecided", "Make", "Buy"}

ASSEMBLY_BUFFER_POLICIES = {"None", "WIP buffer", "Safety stock"}

MATERIAL_SELECTION_RULES = {"Choose one", "Use all", "Optional"}

def _catalog_records(rows) -> list[dict]:
    if isinstance(rows, pd.DataFrame):
        return rows.to_dict("records")
    return [dict(row) for row in rows]

def _catalog_text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()

def _require_catalog_assembly(
    conn: sqlite3.Connection, project_id: str, assembly_id: str
) -> sqlite3.Row:
    assembly = conn.execute(
        "SELECT * FROM manufacturing_assemblies WHERE id=? AND project_id=?",
        (assembly_id, project_id),
    ).fetchone()
    if not assembly:
        raise ValueError("The selected assembly no longer exists in this project.")
    return assembly

def _catalog_part_by_number(
    conn: sqlite3.Connection,
    project_id: str,
    part_number: str,
) -> sqlite3.Row | None:
    matches = conn.execute(
        """SELECT * FROM parts
           WHERE project_id=? AND LOWER(TRIM(part_number))=LOWER(TRIM(?))
           ORDER BY CASE WHEN part_number=? THEN 0 ELSE 1 END, id""",
        (project_id, part_number, part_number),
    ).fetchall()
    if len(matches) > 1:
        raise ValueError(
            f"Part number {part_number} matches multiple Parts Catalog rows. "
            "Resolve the duplicate catalog numbers before saving assemblies."
        )
    return matches[0] if matches else None

def _assembly_part_relationship_counts(
    conn: sqlite3.Connection, part_id: str
) -> dict[str, int]:
    def count(table: str, column: str = "part_id") -> int:
        return int(conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column}=?", (part_id,)
        ).fetchone()[0])

    return {
        "fishbone_use_count": count("fishbone_part_assignments"),
        "process_option_count": count("process_part_options"),
        "feature_rule_count": count("part_feature_rules"),
        "scenario_activity_count": count("part_scenario_activity"),
        "supplemental_image_count": count("part_images"),
    }

def _release_or_remove_generated_assembly_part(
    conn: sqlite3.Connection,
    project_id: str,
    part_id: str | None,
) -> str:
    """Remove only an untouched generated orphan; preserve every used/authored part."""
    if not part_id:
        return "none"
    part = conn.execute(
        "SELECT * FROM parts WHERE id=? AND project_id=?", (part_id, project_id)
    ).fetchone()
    if not part:
        return "none"
    linked = conn.execute(
        "SELECT 1 FROM manufacturing_assemblies WHERE catalog_part_id=? LIMIT 1",
        (part_id,),
    ).fetchone()
    relationships = _assembly_part_relationship_counts(conn, part_id)
    generated = str(part["source"] or "") == "Assembly grid"
    untouched = (
        float(part["quantity"] or 0) == 1
        and str(part["revision"] or "") == "0"
        and not str(part["image_path"] or "").strip()
        and not str(part["notes"] or "").strip()
    )
    if not linked and generated and untouched and not any(relationships.values()):
        conn.execute("DELETE FROM parts WHERE id=? AND project_id=?", (part_id, project_id))
        return "deleted generated orphan"
    return "preserved independent part"

def _ensure_assembly_catalog_part(
    conn: sqlite3.Connection,
    project_id: str,
    assembly_id: str,
    assembly_number: str,
    assembly_name: str,
    timestamp: str,
    *,
    allow_existing_relink: bool = False,
) -> dict:
    assembly = conn.execute(
        "SELECT catalog_part_id FROM manufacturing_assemblies WHERE id=? AND project_id=?",
        (assembly_id, project_id),
    ).fetchone()
    if not assembly:
        raise ValueError("The selected assembly no longer exists in this project.")
    old_part_id = _catalog_text(assembly["catalog_part_id"]) or None
    old_part = (
        conn.execute(
            "SELECT * FROM parts WHERE id=? AND project_id=?", (old_part_id, project_id)
        ).fetchone()
        if old_part_id else None
    )
    matching_part = _catalog_part_by_number(conn, project_id, assembly_number)
    if matching_part and str(matching_part["id"]) != old_part_id:
        owner = conn.execute(
            """SELECT assembly_number FROM manufacturing_assemblies
               WHERE project_id=? AND catalog_part_id=? AND id<>?""",
            (project_id, matching_part["id"], assembly_id),
        ).fetchone()
        if owner:
            raise ValueError(
                f"Part number {assembly_number} is already linked to assembly "
                f"{owner['assembly_number']}."
            )
        if old_part and not allow_existing_relink:
            raise ValueError(
                f"Part number {assembly_number} already exists in the Parts Catalog. "
                "Review and confirm the catalog-part relink before saving."
            )
        part_id = str(matching_part["id"])
        action = "reused existing part"
    elif matching_part:
        part_id = str(matching_part["id"])
        action = "kept linked part"
    elif old_part:
        conn.execute(
            "UPDATE parts SET part_number=?, updated_at=? WHERE id=? AND project_id=?",
            (assembly_number, timestamp, old_part_id, project_id),
        )
        part_id = old_part_id
        action = "renamed linked part"
    else:
        part_id = str(uuid4())
        conn.execute(
            """INSERT INTO parts
               (id, project_id, part_number, description, quantity, revision, source,
                image_path, model_applicability, notes, updated_at)
               VALUES (?, ?, ?, ?, 1, '0', 'Assembly grid', '', '', '', ?)""",
            (part_id, project_id, assembly_number, assembly_name, timestamp),
        )
        action = "created part"
    conn.execute(
        """UPDATE manufacturing_assemblies SET catalog_part_id=?, updated_at=?
           WHERE id=? AND project_id=?""",
        (part_id, timestamp, assembly_id, project_id),
    )
    old_part_action = (
        _release_or_remove_generated_assembly_part(conn, project_id, old_part_id)
        if old_part_id and old_part_id != part_id else "none"
    )
    return {
        "assembly_id": assembly_id,
        "assembly_number": assembly_number,
        "part_id": part_id,
        "action": action,
        "old_part_id": old_part_id,
        "old_part_action": old_part_action,
    }

def _sync_assembly_catalog_part_applicability(
    conn: sqlite3.Connection,
    project_id: str,
    timestamp: str,
) -> list[dict]:
    changes: list[dict] = []
    assemblies = conn.execute(
        """SELECT id, assembly_number, catalog_part_id
           FROM manufacturing_assemblies
           WHERE project_id=? AND catalog_part_id IS NOT NULL""",
        (project_id,),
    ).fetchall()
    for assembly in assemblies:
        model_numbers = [
            str(row[0])
            for row in conn.execute(
                """SELECT DISTINCT model.model_number
                   FROM assembly_grid_model_mappings mapping
                   JOIN project_models model ON model.id=mapping.model_id
                   WHERE mapping.project_id=? AND mapping.assembly_id=? AND model.active=1
                   ORDER BY model.model_number""",
                (project_id, assembly["id"]),
            ).fetchall()
        ]
        applicability = normalize_model_applicability(model_numbers) if model_numbers else ""
        part = conn.execute(
            "SELECT model_applicability FROM parts WHERE id=? AND project_id=?",
            (assembly["catalog_part_id"], project_id),
        ).fetchone()
        if part and str(part["model_applicability"] or "") != applicability:
            conn.execute(
                """UPDATE parts SET model_applicability=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (applicability, timestamp, assembly["catalog_part_id"], project_id),
            )
            changes.append(
                {
                    "assembly_id": str(assembly["id"]),
                    "assembly_number": str(assembly["assembly_number"]),
                    "part_id": str(assembly["catalog_part_id"]),
                    "model_applicability": applicability,
                }
            )
    return changes

def assembly_grid_categories(
    project_id: str, section_id: str | None = None
) -> pd.DataFrame:
    params: list[str] = [project_id]
    section_clause = ""
    if _catalog_text(section_id):
        section_clause = " AND category.section_id=?"
        params.append(_catalog_text(section_id))
    rows = pd.DataFrame(query(
        f"""SELECT category.*, built.name AS section_name,
                   installed.name AS installed_section_name,
                   COUNT(DISTINCT mapping.id) AS mapping_count,
                   COUNT(DISTINCT mapping.assembly_id) AS assembly_count
            FROM assembly_grid_categories category
            JOIN assembly_sections built ON built.id=category.section_id
            LEFT JOIN assembly_sections installed
              ON installed.id=category.installed_section_id
            LEFT JOIN assembly_grid_model_mappings mapping
              ON mapping.category_id=category.id
            WHERE category.project_id=?{section_clause}
            GROUP BY category.id
            ORDER BY built.sequence, category.sequence, category.display_name""",
        tuple(params),
    ))
    if rows.empty:
        return pd.DataFrame({
            "id": pd.Series(dtype="string"),
            "project_id": pd.Series(dtype="string"),
            "section_id": pd.Series(dtype="string"),
            "ebom_name": pd.Series(dtype="string"),
            "display_name": pd.Series(dtype="string"),
            "root_number": pd.Series(dtype="string"),
            "is_top_level": pd.Series(dtype="bool"),
            "installed_section_id": pd.Series(dtype="string"),
            "sequence": pd.Series(dtype="int64"),
            "created_at": pd.Series(dtype="string"),
            "updated_at": pd.Series(dtype="string"),
            "section_name": pd.Series(dtype="string"),
            "installed_section_name": pd.Series(dtype="string"),
            "mapping_count": pd.Series(dtype="int64"),
            "assembly_count": pd.Series(dtype="int64"),
        })
    return rows

def assembly_grid_model_mappings(
    project_id: str, section_id: str | None = None
) -> pd.DataFrame:
    params: list[str] = [project_id]
    section_clause = ""
    if _catalog_text(section_id):
        section_clause = " AND category.section_id=?"
        params.append(_catalog_text(section_id))
    return pd.DataFrame(query(
        f"""SELECT mapping.*, category.section_id, category.ebom_name,
                   category.display_name AS category_display_name,
                   category.root_number, category.is_top_level,
                   category.installed_section_id,
                   model.model_number, model.display_name AS model_display_name,
                   model.active AS model_active,
                   assembly.assembly_number, assembly.name AS assembly_name,
                   assembly.built_section_id AS assembly_built_section_id,
                   assembly.installed_section_id AS assembly_installed_section_id
            FROM assembly_grid_model_mappings mapping
            JOIN assembly_grid_categories category ON category.id=mapping.category_id
            JOIN project_models model ON model.id=mapping.model_id
            JOIN manufacturing_assemblies assembly ON assembly.id=mapping.assembly_id
            WHERE mapping.project_id=?{section_clause}
            ORDER BY category.sequence, category.display_name, model.model_number""",
        tuple(params),
    ))

def assembly_grid_feature_visibility(
    project_id: str, section_id: str
) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT feature.id AS feature_id, feature.category, feature.name,
                  feature.sequence, feature.active,
                  COALESCE(preference.is_visible, 1) AS is_visible,
                  preference.id, preference.created_at, preference.updated_at
           FROM complexity_features feature
           LEFT JOIN assembly_grid_feature_visibility preference
             ON preference.feature_id=feature.id AND preference.section_id=?
           WHERE feature.project_id=?
           ORDER BY feature.sequence, feature.category, feature.name""",
        (section_id, project_id),
    ))

def save_assembly_grid_categories(
    project_id: str, section_id: str, rows, *, _conn: sqlite3.Connection | None = None
) -> dict:
    """Upsert category rows and continuously sync their mapped assemblies."""
    records = _catalog_records(rows)
    section_id = _catalog_text(section_id)
    timestamp = now_iso()
    with (connection() if _conn is None else nullcontext(_conn)) as conn:
        section = conn.execute(
            "SELECT id FROM assembly_sections WHERE id=? AND project_id=?",
            (section_id, project_id),
        ).fetchone()
        if not section:
            raise ValueError("Choose an existing Fishbone section from this project.")
        valid_installed = {
            str(row[0]) for row in conn.execute(
                "SELECT id FROM assembly_sections WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        current = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM assembly_grid_categories WHERE project_id=?",
                (project_id,),
            ).fetchall()
        }
        normalized: list[dict] = []
        seen_ids: set[str] = set()
        for raw in records:
            category_id = _catalog_text(raw.get("id")) or str(uuid4())
            ebom_name = _catalog_text(raw.get("ebom_name"))
            display_name = _catalog_text(raw.get("display_name"))
            is_top_level = int(
                raw.get("is_top_level") in (True, 1, "1", "true", "True")
            )
            installed_section_id = _catalog_text(raw.get("installed_section_id")) or None
            if category_id in seen_ids:
                raise ValueError("The assembly grid contains a duplicate category identifier.")
            if not ebom_name or not display_name:
                raise ValueError(
                    "Every assembly-grid category requires an Official EBOM category name "
                    "and Display name."
                )
            if installed_section_id and installed_section_id not in valid_installed:
                raise ValueError("Choose an existing Installed section from this project.")
            previous = current.get(category_id)
            root_number = (
                _catalog_text(raw.get("root_number"))
                if "root_number" in raw
                else _catalog_text((previous or {}).get("root_number"))
            )
            if previous and _catalog_text(previous.get("section_id")) != section_id:
                if not bool(previous.get("is_top_level")):
                    raise ValueError(
                        "A category can be moved to another Fishbone section only through the "
                        "approved section-continuity workflow."
                    )
            if previous and bool(previous.get("is_top_level")) != bool(is_top_level):
                raise ValueError(
                    "The protected Top-level packaged unit row cannot be converted to or "
                    "from a Fishbone-section category."
                )
            if is_top_level and (
                ebom_name != "Top-level packaged unit"
                or display_name != "Top-level packaged unit"
            ):
                raise ValueError(
                    "The protected row must keep the name Top-level packaged unit."
                )
            try:
                sequence = int(raw.get("sequence", 10))
            except (TypeError, ValueError) as exc:
                raise ValueError("Assembly-grid category sequence values must be whole numbers.") from exc
            seen_ids.add(category_id)
            normalized.append(
                {
                    "id": category_id,
                    "ebom_name": ebom_name,
                    "display_name": display_name,
                    "root_number": root_number,
                    "is_top_level": is_top_level,
                    "installed_section_id": installed_section_id,
                    "sequence": sequence,
                }
            )

        merged = {category_id: dict(value) for category_id, value in current.items()}
        merged.update(
            {
                row["id"]: {
                    **row,
                    "project_id": project_id,
                    "section_id": section_id,
                }
                for row in normalized
            }
        )
        top_level_ids = [
            category_id
            for category_id, row in merged.items()
            if bool(row.get("is_top_level"))
        ]
        if len(top_level_ids) > 1:
            raise ValueError(
                "Only one Top-level packaged unit row is allowed in a project."
            )
        for field, label in (("ebom_name", "Official EBOM category name"), ("display_name", "Display name")):
            seen: dict[tuple[str, str], str] = {}
            for category_id, row in merged.items():
                key = (
                    _catalog_text(row.get("section_id")),
                    _catalog_text(row.get(field)).casefold(),
                )
                if key in seen and seen[key] != category_id:
                    raise ValueError(f"{label} values must be unique within a Fishbone section.")
                seen[key] = category_id

        sync_changes: list[dict] = []
        built_sync_changes: list[dict] = []
        for row in normalized:
            previous = current.get(row["id"])
            created_at = _catalog_text(previous.get("created_at")) if previous else timestamp
            conn.execute(
                """INSERT INTO assembly_grid_categories
                   (id, project_id, section_id, ebom_name, display_name, root_number,
                    is_top_level, installed_section_id, sequence, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       section_id=excluded.section_id,
                       ebom_name=excluded.ebom_name,
                       display_name=excluded.display_name,
                       root_number=excluded.root_number,
                       is_top_level=excluded.is_top_level,
                       installed_section_id=excluded.installed_section_id,
                       sequence=excluded.sequence,
                       updated_at=excluded.updated_at""",
                (
                    row["id"], project_id, section_id, row["ebom_name"],
                    row["display_name"], row["root_number"],
                    row["is_top_level"], row["installed_section_id"], row["sequence"],
                    created_at, timestamp,
                ),
            )
            mapped = conn.execute(
                """SELECT DISTINCT assembly.id, assembly.assembly_number,
                          assembly.installed_section_id
                   FROM assembly_grid_model_mappings mapping
                   JOIN manufacturing_assemblies assembly ON assembly.id=mapping.assembly_id
                   WHERE mapping.project_id=? AND mapping.category_id=?""",
                (project_id, row["id"]),
            ).fetchall()
            for assembly in mapped:
                previous_built_section_id = (
                    _catalog_text((previous or {}).get("section_id")) or None
                )
                if (
                    row["is_top_level"]
                    and previous_built_section_id
                    and previous_built_section_id != section_id
                ):
                    conn.execute(
                        """UPDATE fishbone_part_assignments SET section_id=?, updated_at=?
                           WHERE project_id=? AND id IN (
                               SELECT fishbone_assignment_id
                               FROM manufacturing_assembly_components
                               WHERE project_id=? AND assembly_id=?
                           )""",
                        (
                            section_id,
                            timestamp,
                            project_id,
                            project_id,
                            assembly["id"],
                        ),
                    )
                    conn.execute(
                        """UPDATE manufacturing_assemblies
                           SET built_section_id=?, updated_at=?
                           WHERE id=? AND project_id=?""",
                        (section_id, timestamp, assembly["id"], project_id),
                    )
                    built_sync_changes.append(
                        {
                            "assembly_id": str(assembly["id"]),
                            "assembly_number": str(assembly["assembly_number"]),
                            "old_built_section_id": previous_built_section_id,
                            "new_built_section_id": section_id,
                        }
                    )
                old_value = _catalog_text(assembly["installed_section_id"]) or None
                if old_value == row["installed_section_id"]:
                    continue
                conn.execute(
                    """UPDATE manufacturing_assemblies
                       SET installed_section_id=?, updated_at=?
                       WHERE id=? AND project_id=?""",
                    (row["installed_section_id"], timestamp, assembly["id"], project_id),
                )
                sync_changes.append(
                    {
                        "assembly_id": str(assembly["id"]),
                        "assembly_number": str(assembly["assembly_number"]),
                        "old_installed_section_id": old_value,
                        "new_installed_section_id": row["installed_section_id"],
                    }
                )
    return {
        "count": len(normalized),
        "category_ids": [row["id"] for row in normalized],
        "built_section_sync_changes": built_sync_changes,
        "installed_section_sync_changes": sync_changes,
        "updated_at": timestamp,
    }

def assembly_grid_part_relink_impact(
    project_id: str, rows, *, _conn: sqlite3.Connection | None = None
) -> list[dict]:
    """Describe mapped-assembly renames that would relink to an existing catalog part."""
    records = _catalog_records(rows)
    with (connection() if _conn is None else nullcontext(_conn)) as conn:
        assemblies = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM manufacturing_assemblies WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        assembly_by_number = {
            _catalog_text(row["assembly_number"]).casefold(): assembly_id
            for assembly_id, row in assemblies.items()
        }
        candidates: dict[str, dict[str, str]] = {}
        for raw in records:
            assembly_id = _catalog_text(raw.get("assembly_id"))
            requested_number = _catalog_text(raw.get("assembly_number"))
            if (
                assembly_id in assemblies
                and requested_number
                and requested_number.casefold()
                != _catalog_text(assemblies[assembly_id]["assembly_number"]).casefold()
            ):
                candidates.setdefault(assembly_id, {})[
                    requested_number.casefold()
                ] = requested_number

        impacts: list[dict] = []
        for assembly_id, requested in candidates.items():
            if len(requested) != 1:
                continue
            target_number = next(iter(requested.values()))
            if assembly_by_number.get(target_number.casefold()) not in {None, assembly_id}:
                continue
            assembly = assemblies[assembly_id]
            source_part_id = _catalog_text(assembly.get("catalog_part_id"))
            target_part = _catalog_part_by_number(conn, project_id, target_number)
            if not source_part_id or not target_part or str(target_part["id"]) == source_part_id:
                continue
            owner = conn.execute(
                """SELECT assembly_number FROM manufacturing_assemblies
                   WHERE project_id=? AND catalog_part_id=? AND id<>?""",
                (project_id, target_part["id"], assembly_id),
            ).fetchone()
            if owner:
                raise ValueError(
                    f"Part number {target_number} is already linked to assembly "
                    f"{owner['assembly_number']}."
                )
            source_part = conn.execute(
                "SELECT * FROM parts WHERE id=? AND project_id=?",
                (source_part_id, project_id),
            ).fetchone()
            relationships = _assembly_part_relationship_counts(conn, source_part_id)
            generated_orphan = bool(
                source_part
                and str(source_part["source"] or "") == "Assembly grid"
                and float(source_part["quantity"] or 0) == 1
                and str(source_part["revision"] or "") == "0"
                and not str(source_part["image_path"] or "").strip()
                and not str(source_part["notes"] or "").strip()
                and not any(relationships.values())
            )
            impacts.append(
                {
                    "assembly_id": assembly_id,
                    "source_assembly_number": _catalog_text(assembly["assembly_number"]),
                    "target_assembly_number": target_number,
                    "source_part_id": source_part_id,
                    "target_part_id": str(target_part["id"]),
                    "source_part_number": str(source_part["part_number"]) if source_part else "",
                    "target_part_number": str(target_part["part_number"]),
                    "source_part_action": (
                        "deleted generated orphan" if generated_orphan
                        else "preserved independent part"
                    ),
                    **relationships,
                }
            )
        return impacts

def save_assembly_grid_model_mappings(
    project_id: str,
    rows,
    *,
    catalog_part_relinks: list[dict] | None = None,
    _validate_containment: bool = True,
    _conn: sqlite3.Connection | None = None,
) -> dict:
    """Replace the complete project mapping state after validating every relationship."""
    records = _catalog_records(rows)
    timestamp = now_iso()
    with (connection() if _conn is None else nullcontext(_conn)) as conn:
        actual_part_relinks = assembly_grid_part_relink_impact(
            project_id, records, _conn=conn
        )
        actual_relink_pairs = {
            (row["assembly_id"], row["target_part_id"])
            for row in actual_part_relinks
        }
        confirmed_relink_pairs = {
            (
                _catalog_text(row.get("assembly_id")),
                _catalog_text(row.get("target_part_id")),
            )
            for row in (catalog_part_relinks or [])
        }
        if actual_relink_pairs != confirmed_relink_pairs:
            if actual_relink_pairs:
                raise ValueError(
                    "Review and confirm the existing Parts Catalog relink before saving."
                )
            raise ValueError(
                "The pending Parts Catalog relink is no longer present. Review the grid again."
            )
        confirmed_relink_assemblies = {row[0] for row in actual_relink_pairs}
        categories = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM assembly_grid_categories WHERE project_id=?",
                (project_id,),
            ).fetchall()
        }
        models = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT id, model_number FROM project_models WHERE project_id=?",
                (project_id,),
            ).fetchall()
        }
        assemblies = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM manufacturing_assemblies WHERE project_id=?",
                (project_id,),
            ).fetchall()
        }
        existing_mappings = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM assembly_grid_model_mappings WHERE project_id=?",
                (project_id,),
            ).fetchall()
        }
        original_numbers = {
            assembly_id: _catalog_text(row["assembly_number"])
            for assembly_id, row in assemblies.items()
        }
        rename_candidates: dict[str, dict[str, str]] = {}
        for raw in records:
            assembly_id = _catalog_text(raw.get("assembly_id"))
            requested_number = _catalog_text(raw.get("assembly_number"))
            current_number = original_numbers.get(assembly_id, "")
            if (
                assembly_id in assemblies
                and requested_number
                and requested_number != current_number
            ):
                rename_candidates.setdefault(assembly_id, {})[
                    requested_number.casefold()
                ] = requested_number

        planned_renames: dict[str, str] = {}
        for assembly_id, candidates in rename_candidates.items():
            changed_numbers = {
                key: value
                for key, value in candidates.items()
                if key != original_numbers[assembly_id].casefold()
            }
            if len(changed_numbers) > 1:
                raise ValueError(
                    f"Assembly {original_numbers[assembly_id]} has conflicting Part number "
                    "edits. Use one Part number for every model mapped to that assembly."
                )
            if changed_numbers:
                planned_renames[assembly_id] = next(iter(changed_numbers.values()))
            elif candidates:
                # Preserve deliberate capitalization-only corrections.
                planned_renames[assembly_id] = next(iter(candidates.values()))

        final_number_owners: dict[str, str] = {}
        renamed_assemblies: list[dict] = []
        for assembly_id, assembly in assemblies.items():
            old_number = original_numbers[assembly_id]
            final_number = planned_renames.get(assembly_id, old_number)
            owner = final_number_owners.get(final_number.casefold())
            if owner and owner != assembly_id:
                raise ValueError(
                    f"Part number {final_number} already belongs to another assembly. "
                    "Choose a unique Part number."
                )
            final_number_owners[final_number.casefold()] = assembly_id
            if final_number != old_number:
                assembly["assembly_number"] = final_number
                renamed_assemblies.append(
                    {
                        "assembly_id": assembly_id,
                        "old_assembly_number": old_number,
                        "assembly_number": final_number,
                    }
                )
        assembly_by_number = dict(final_number_owners)
        normalized: list[dict] = []
        seen_ids: set[str] = set()
        seen_cells: set[tuple[str, str]] = set()
        category_by_assembly: dict[str, str] = {}
        created_assemblies: list[dict] = []
        for raw in records:
            mapping_id = _catalog_text(raw.get("id")) or str(uuid4())
            category_id = _catalog_text(raw.get("category_id"))
            model_id = _catalog_text(raw.get("model_id"))
            category = categories.get(category_id)
            model = models.get(model_id)
            if not category:
                raise ValueError("Every mapping must use a current project assembly-grid category.")
            if not model:
                raise ValueError("Every mapping must use a current official model.")
            assembly_id = _catalog_text(raw.get("assembly_id"))
            assembly_number = _catalog_text(raw.get("assembly_number"))
            assembly = assemblies.get(assembly_id) if assembly_id else None
            if assembly is None:
                if not assembly_number:
                    raise ValueError("Every mapping requires an assembly number.")
                existing_id = assembly_by_number.get(assembly_number.casefold())
                if existing_id:
                    assembly_id = existing_id
                    assembly = assemblies[assembly_id]
                else:
                    assembly_id = str(uuid4())
                    assembly = {
                        "id": assembly_id,
                        "project_id": project_id,
                        "assembly_number": assembly_number,
                        "name": _catalog_text(category.get("display_name")),
                        "make_buy": "",
                        "built_section_id": category["section_id"],
                        "installed_section_id": category["installed_section_id"],
                    }
                    assemblies[assembly_id] = assembly
                    assembly_by_number[assembly_number.casefold()] = assembly_id
                    created_assemblies.append(assembly)
            if mapping_id in seen_ids:
                raise ValueError("The assembly grid contains a duplicate mapping identifier.")
            cell = (category_id, model_id)
            if cell in seen_cells:
                raise ValueError("Each category may map an official model only once.")
            if _catalog_text(assembly.get("built_section_id")) != _catalog_text(category.get("section_id")):
                raise ValueError(
                    f"Assembly {assembly['assembly_number']} is built in a different Fishbone "
                    "section and cannot be mapped here."
                )
            assembly_installed = _catalog_text(assembly.get("installed_section_id")) or None
            category_installed = _catalog_text(category.get("installed_section_id")) or None
            if assembly_installed != category_installed:
                raise ValueError(
                    f"Assembly {assembly['assembly_number']} has an Installed section that "
                    "does not match this category. Reconcile it before mapping."
                )
            prior_category = category_by_assembly.get(assembly_id)
            if prior_category and prior_category != category_id:
                prior = categories[prior_category]
                raise ValueError(
                    f"Assembly {assembly['assembly_number']} is already mapped under category "
                    f"{prior['display_name']} and cannot also be mapped under "
                    f"{category['display_name']} for model {model['model_number']}."
                )
            category_by_assembly[assembly_id] = category_id
            seen_ids.add(mapping_id)
            seen_cells.add(cell)
            normalized.append(
                {
                    "id": mapping_id,
                    "category_id": category_id,
                    "model_id": model_id,
                    "assembly_id": assembly_id,
                }
            )

        for assembly in created_assemblies:
            conn.execute(
                """INSERT INTO manufacturing_assemblies
                   (id, project_id, assembly_number, name, make_buy, pits_reference,
                    planning_reason, parent_id, built_section_id, installed_section_id,
                    image_path, created_at, active, notes, updated_at)
                   VALUES (?, ?, ?, ?, '', '', 'Other', NULL, ?, ?, '', ?, 1, '', ?)""",
                (
                    assembly["id"], project_id, assembly["assembly_number"], assembly["name"],
                    assembly["built_section_id"], assembly["installed_section_id"],
                    timestamp, timestamp,
                ),
            )
        catalog_part_changes: list[dict] = []
        for assembly in created_assemblies:
            catalog_part_changes.append(
                _ensure_assembly_catalog_part(
                    conn, project_id, assembly["id"], assembly["assembly_number"],
                    assembly["name"], timestamp,
                )
            )
        for assembly in renamed_assemblies:
            conn.execute(
                """UPDATE manufacturing_assemblies
                   SET assembly_number=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (
                    assembly["assembly_number"], timestamp,
                    assembly["assembly_id"], project_id,
                ),
            )
            catalog_part_changes.append(
                _ensure_assembly_catalog_part(
                    conn, project_id, assembly["assembly_id"],
                    assembly["assembly_number"],
                    _catalog_text(assemblies[assembly["assembly_id"]].get("name")),
                    timestamp,
                    allow_existing_relink=(
                        assembly["assembly_id"] in confirmed_relink_assemblies
                    ),
                )
            )
        for assembly_id, assembly in assemblies.items():
            if assembly_id in {row["id"] for row in created_assemblies}:
                continue
            if assembly_id in {row["assembly_id"] for row in renamed_assemblies}:
                continue
            if not _catalog_text(assembly.get("catalog_part_id")):
                catalog_part_changes.append(
                    _ensure_assembly_catalog_part(
                        conn, project_id, assembly_id,
                        _catalog_text(assembly.get("assembly_number")),
                        _catalog_text(assembly.get("name")), timestamp,
                    )
                )
        conn.execute(
            "DELETE FROM assembly_grid_model_mappings WHERE project_id=?", (project_id,)
        )
        conn.executemany(
            """INSERT INTO assembly_grid_model_mappings
               (id, project_id, category_id, model_id, assembly_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    row["id"], project_id, row["category_id"], row["model_id"],
                    row["assembly_id"],
                    _catalog_text(existing_mappings.get(row["id"], {}).get("created_at"))
                    or timestamp,
                    timestamp,
                )
                for row in normalized
            ],
        )
        applicability_changes = _sync_assembly_catalog_part_applicability(
            conn, project_id, timestamp
        )
        if _validate_containment:
            _validate_assembly_containment(conn, project_id)
    return {
        "count": len(normalized),
        "mapping_ids": [row["id"] for row in normalized],
        "created_assemblies": [
            {"assembly_id": row["id"], "assembly_number": row["assembly_number"]}
            for row in created_assemblies
        ],
        "renamed_assemblies": renamed_assemblies,
        "catalog_part_changes": catalog_part_changes,
        "catalog_part_relinks": actual_part_relinks,
        "catalog_part_applicability_changes": applicability_changes,
        "updated_at": timestamp,
    }

def assembly_grid_number_merge_impact(
    project_id: str, rows, *, _conn: sqlite3.Connection | None = None
) -> list[dict]:
    """Describe saved assemblies that a grid draft would replace with existing numbers."""
    records = _catalog_records(rows)
    with (connection() if _conn is None else nullcontext(_conn)) as conn:
        assemblies = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM manufacturing_assemblies WHERE project_id=?",
                (project_id,),
            ).fetchall()
        }
        assembly_by_number = {
            _catalog_text(row["assembly_number"]).casefold(): assembly_id
            for assembly_id, row in assemblies.items()
        }
        requested_targets: dict[str, str] = {}
        categories_by_assembly: dict[str, set[str]] = {}
        for raw in records:
            assembly_id = _catalog_text(raw.get("assembly_id"))
            category_id = _catalog_text(raw.get("category_id"))
            requested_number = _catalog_text(raw.get("assembly_number"))
            if assembly_id:
                categories_by_assembly.setdefault(assembly_id, set()).add(category_id)
            target_id = assembly_by_number.get(requested_number.casefold())
            if not assembly_id or assembly_id not in assemblies or not target_id:
                continue
            if target_id == assembly_id:
                continue
            previous_target = requested_targets.get(assembly_id)
            if previous_target and previous_target != target_id:
                raise ValueError(
                    f"Assembly {assemblies[assembly_id]['assembly_number']} has conflicting "
                    "Part number edits. Use one Part number for every model mapped to it."
                )
            requested_targets[assembly_id] = target_id

        impacts: list[dict] = []
        for source_id, target_id in requested_targets.items():
            if target_id in requested_targets:
                raise ValueError(
                    "Assembly-number merges cannot be chained in one save. Complete one merge "
                    "and refresh the grid before starting another."
                )
            source_categories = categories_by_assembly.get(source_id, set()) - {""}
            target_categories = categories_by_assembly.get(target_id, set()) - {""}
            combined_categories = source_categories | target_categories
            if len(combined_categories) > 1:
                category_rows = conn.execute(
                    f"""SELECT id, display_name FROM assembly_grid_categories
                        WHERE project_id=? AND id IN ({','.join('?' for _ in combined_categories)})""",
                    (project_id, *combined_categories),
                ).fetchall()
                category_names = ", ".join(str(row["display_name"]) for row in category_rows)
                raise ValueError(
                    f"Assembly {assemblies[target_id]['assembly_number']} is mapped under a "
                    f"different category ({category_names}). Move or clear those mappings "
                    "before merging assembly numbers."
                )

            def direct_count(table: str, column: str = "assembly_id") -> int:
                return int(conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column}=?",
                    (source_id,),
                ).fetchone()[0])

            source_image_paths = [
                str(row[0])
                for row in conn.execute(
                    """SELECT image_path FROM manufacturing_assemblies
                       WHERE project_id=? AND id=?
                         AND TRIM(COALESCE(image_path, ''))<>''
                       UNION ALL
                       SELECT image_path FROM manufacturing_assembly_images
                       WHERE project_id=? AND assembly_id=?""",
                    (project_id, source_id, project_id, source_id),
                ).fetchall()
            ]
            source_part_id = _catalog_text(
                assemblies[source_id].get("catalog_part_id")
            )
            target_part_id = _catalog_text(
                assemblies[target_id].get("catalog_part_id")
            )
            source_part_relationships = (
                _assembly_part_relationship_counts(conn, source_part_id)
                if source_part_id else {
                    "fishbone_use_count": 0,
                    "process_option_count": 0,
                    "feature_rule_count": 0,
                    "scenario_activity_count": 0,
                    "supplemental_image_count": 0,
                }
            )
            source_part = conn.execute(
                "SELECT * FROM parts WHERE id=? AND project_id=?",
                (source_part_id, project_id),
            ).fetchone() if source_part_id else None
            source_part_action = "none"
            if source_part:
                removable_generated_part = bool(
                    str(source_part["source"] or "") == "Assembly grid"
                    and float(source_part["quantity"] or 0) == 1
                    and str(source_part["revision"] or "") == "0"
                    and not str(source_part["image_path"] or "").strip()
                    and not str(source_part["notes"] or "").strip()
                    and not any(source_part_relationships.values())
                )
                source_part_action = (
                    "deleted generated orphan" if removable_generated_part
                    else "preserved independent part"
                )
            impacts.append(
                {
                    "source_assembly_id": source_id,
                    "source_assembly_number": str(assemblies[source_id]["assembly_number"]),
                    "target_assembly_id": target_id,
                    "target_assembly_number": str(assemblies[target_id]["assembly_number"]),
                    "source_component_count": direct_count(
                        "manufacturing_assembly_components"
                    ),
                    "target_component_count": int(conn.execute(
                        """SELECT COUNT(*) FROM manufacturing_assembly_components
                           WHERE project_id=? AND assembly_id=?""",
                        (project_id, target_id),
                    ).fetchone()[0]),
                    "source_rule_count": direct_count(
                        "manufacturing_assembly_feature_rules"
                    ),
                    "source_supplemental_image_count": direct_count(
                        "manufacturing_assembly_images"
                    ),
                    "source_primary_image_count": int(bool(
                        _catalog_text(assemblies[source_id].get("image_path"))
                    )),
                    "source_child_count": int(conn.execute(
                        """SELECT COUNT(*) FROM manufacturing_assemblies
                           WHERE project_id=? AND parent_id=?""",
                        (project_id, source_id),
                    ).fetchone()[0]),
                    "source_policy_count": direct_count("assembly_scenario_policies"),
                    "source_material_option_count": direct_count(
                        "work_element_material_options"
                    ),
                    "source_target_link_count": direct_count(
                        "work_element_material_groups", "target_assembly_id"
                    ),
                    "source_mapping_count": direct_count("assembly_grid_model_mappings"),
                    "reassigned_mapping_count": sum(
                        1
                        for raw in records
                        if _catalog_text(raw.get("assembly_id")) == source_id
                    ),
                    "source_part_id": source_part_id,
                    "target_part_id": target_part_id,
                    "source_part_number": (
                        str(source_part["part_number"]) if source_part else ""
                    ),
                    "source_part_action": source_part_action,
                    **source_part_relationships,
                    "source_image_paths": source_image_paths,
                }
            )
        return impacts

def save_assembly_grid_feature_visibility(
    project_id: str, section_id: str, rows, *, _conn: sqlite3.Connection | None = None
) -> dict:
    """Persist only non-default hidden-feature preferences for one section."""
    records = _catalog_records(rows)
    timestamp = now_iso()
    with (connection() if _conn is None else nullcontext(_conn)) as conn:
        if not conn.execute(
            "SELECT 1 FROM assembly_sections WHERE id=? AND project_id=?",
            (section_id, project_id),
        ).fetchone():
            raise ValueError("Choose an existing Fishbone section from this project.")
        valid_features = {
            str(row[0]) for row in conn.execute(
                "SELECT id FROM complexity_features WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        existing = {
            str(row["feature_id"]): dict(row)
            for row in conn.execute(
                """SELECT * FROM assembly_grid_feature_visibility
                   WHERE project_id=? AND section_id=?""",
                (project_id, section_id),
            ).fetchall()
        }
        hidden_features: list[str] = []
        seen: set[str] = set()
        for raw in records:
            feature_id = _catalog_text(raw.get("feature_id"))
            if feature_id not in valid_features:
                raise ValueError("Every feature preference must use a current project feature.")
            if feature_id in seen:
                raise ValueError("A feature may have only one visibility preference per section.")
            seen.add(feature_id)
            if not bool(raw.get("is_visible", True)):
                hidden_features.append(feature_id)
        conn.execute(
            """DELETE FROM assembly_grid_feature_visibility
               WHERE project_id=? AND section_id=?""",
            (project_id, section_id),
        )
        conn.executemany(
            """INSERT INTO assembly_grid_feature_visibility
               (id, project_id, section_id, feature_id, is_visible, created_at, updated_at)
               VALUES (?, ?, ?, ?, 0, ?, ?)""",
            [
                (
                    _catalog_text(existing.get(feature_id, {}).get("id")) or str(uuid4()),
                    project_id, section_id, feature_id,
                    _catalog_text(existing.get(feature_id, {}).get("created_at")) or timestamp,
                    timestamp,
                )
                for feature_id in hidden_features
            ],
        )
    return {
        "count": len(hidden_features),
        "hidden_feature_ids": hidden_features,
        "updated_at": timestamp,
    }

def save_assembly_grid_section(
    project_id: str,
    section_id: str,
    category_rows,
    complete_mapping_rows,
    feature_visibility_rows,
    component_rows_by_assembly: dict[str, list[dict]] | None = None,
    assembly_merges: list[dict] | None = None,
    catalog_part_relinks: list[dict] | None = None,
) -> dict:
    """Validate and save one complete grid draft in a single transaction."""
    deleted_image_paths: list[str] = []
    with connection() as conn:
        merge_impact = assembly_grid_number_merge_impact(
            project_id, complete_mapping_rows, _conn=conn
        )
        part_relink_impact = assembly_grid_part_relink_impact(
            project_id, complete_mapping_rows, _conn=conn
        )
        actual_part_relinks = {
            (row["assembly_id"], row["target_part_id"])
            for row in part_relink_impact
        }
        confirmed_part_relinks = {
            (
                _catalog_text(row.get("assembly_id")),
                _catalog_text(row.get("target_part_id")),
            )
            for row in (catalog_part_relinks or [])
        }
        if actual_part_relinks != confirmed_part_relinks:
            if actual_part_relinks:
                raise ValueError(
                    "Review and confirm the existing Parts Catalog relink before saving."
                )
            raise ValueError(
                "The pending Parts Catalog relink is no longer present. Review the grid again."
            )
        actual_merges = {
            (row["source_assembly_id"], row["target_assembly_id"])
            for row in merge_impact
        }
        confirmed_merges = {
            (
                _catalog_text(row.get("source_assembly_id")),
                _catalog_text(row.get("target_assembly_id")),
            )
            for row in (assembly_merges or [])
        }
        if actual_merges != confirmed_merges:
            if actual_merges:
                raise ValueError(
                    "Review and confirm the assembly-number merge before saving."
                )
            raise ValueError(
                "The pending assembly-number merge is no longer present. Review the grid again."
            )
        target_by_source = dict(actual_merges)
        resolved_mapping_rows = []
        for raw in _catalog_records(complete_mapping_rows):
            source_id = _catalog_text(raw.get("assembly_id"))
            target_id = target_by_source.get(source_id)
            if target_id:
                target_number = next(
                    row["target_assembly_number"]
                    for row in merge_impact
                    if row["source_assembly_id"] == source_id
                )
                resolved_mapping_rows.append(
                    {**raw, "assembly_id": target_id, "assembly_number": target_number}
                )
            else:
                resolved_mapping_rows.append(raw)
        categories_result = save_assembly_grid_categories(
            project_id, section_id, category_rows, _conn=conn
        )
        mappings_result = save_assembly_grid_model_mappings(
            project_id,
            resolved_mapping_rows,
            catalog_part_relinks=part_relink_impact,
            _validate_containment=False,
            _conn=conn,
        )
        visibility_result = save_assembly_grid_feature_visibility(
            project_id, section_id, feature_visibility_rows, _conn=conn
        )
        component_results: dict[str, dict] = {}
        for assembly_id, rows in (component_rows_by_assembly or {}).items():
            if str(assembly_id) in target_by_source:
                continue
            component_results[str(assembly_id)] = save_assembly_bom_components(
                project_id,
                str(assembly_id),
                rows,
                _validate_containment=False,
                _conn=conn,
            )
        for impact in merge_impact:
            deleted_image_paths.extend(impact["source_image_paths"])
            conn.execute(
                "DELETE FROM manufacturing_assemblies WHERE project_id=? AND id=?",
                (project_id, impact["source_assembly_id"]),
            )
            impact["source_part_action"] = _release_or_remove_generated_assembly_part(
                conn, project_id, impact.get("source_part_id")
            )
        _validate_assembly_containment(conn, project_id)
    for image_path in deleted_image_paths:
        _remove_owned_upload(image_path)
    return {
        "categories": categories_result,
        "mappings": mappings_result,
        "feature_visibility": visibility_result,
        "components": component_results,
        "assembly_merges": merge_impact,
        "catalog_part_relinks": part_relink_impact,
        "updated_at": now_iso(),
    }

def save_assembly_grid_sections(
    project_id: str,
    section_payloads: list[dict],
    complete_mapping_rows,
    component_rows_by_assembly: dict[str, list[dict]] | None = None,
    assembly_merges: list[dict] | None = None,
    catalog_part_relinks: list[dict] | None = None,
) -> dict:
    """Validate and atomically save every displayed Assembly grid section."""
    payloads = [dict(payload) for payload in section_payloads]
    section_ids = [_catalog_text(payload.get("section_id")) for payload in payloads]
    if not section_ids or any(not section_id for section_id in section_ids):
        raise ValueError("Select at least one Fishbone section to save.")
    if len(section_ids) != len(set(section_ids)):
        raise ValueError("Each selected Fishbone section may appear only once in a grid save.")

    deleted_image_paths: list[str] = []
    with connection() as conn:
        merge_impact = assembly_grid_number_merge_impact(
            project_id, complete_mapping_rows, _conn=conn
        )
        part_relink_impact = assembly_grid_part_relink_impact(
            project_id, complete_mapping_rows, _conn=conn
        )
        actual_part_relinks = {
            (row["assembly_id"], row["target_part_id"])
            for row in part_relink_impact
        }
        confirmed_part_relinks = {
            (
                _catalog_text(row.get("assembly_id")),
                _catalog_text(row.get("target_part_id")),
            )
            for row in (catalog_part_relinks or [])
        }
        if actual_part_relinks != confirmed_part_relinks:
            if actual_part_relinks:
                raise ValueError(
                    "Review and confirm the existing Parts Catalog relink before saving."
                )
            raise ValueError(
                "The pending Parts Catalog relink is no longer present. Review the grid again."
            )
        actual_merges = {
            (row["source_assembly_id"], row["target_assembly_id"])
            for row in merge_impact
        }
        confirmed_merges = {
            (
                _catalog_text(row.get("source_assembly_id")),
                _catalog_text(row.get("target_assembly_id")),
            )
            for row in (assembly_merges or [])
        }
        if actual_merges != confirmed_merges:
            if actual_merges:
                raise ValueError("Review and confirm the assembly-number merge before saving.")
            raise ValueError(
                "The pending assembly-number merge is no longer present. Review the grid again."
            )

        target_by_source = dict(actual_merges)
        target_number_by_source = {
            row["source_assembly_id"]: row["target_assembly_number"]
            for row in merge_impact
        }
        resolved_mapping_rows = []
        for raw in _catalog_records(complete_mapping_rows):
            source_id = _catalog_text(raw.get("assembly_id"))
            target_id = target_by_source.get(source_id)
            resolved_mapping_rows.append(
                {
                    **raw,
                    **(
                        {
                            "assembly_id": target_id,
                            "assembly_number": target_number_by_source[source_id],
                        }
                        if target_id else {}
                    ),
                }
            )

        section_results: dict[str, dict] = {}
        for section_id, payload in zip(section_ids, payloads):
            section_results[section_id] = {
                "categories": save_assembly_grid_categories(
                    project_id,
                    section_id,
                    payload.get("categories", []),
                    _conn=conn,
                )
            }
        mappings_result = save_assembly_grid_model_mappings(
            project_id,
            resolved_mapping_rows,
            catalog_part_relinks=part_relink_impact,
            _validate_containment=False,
            _conn=conn,
        )
        for section_id, payload in zip(section_ids, payloads):
            section_results[section_id]["feature_visibility"] = (
                save_assembly_grid_feature_visibility(
                    project_id,
                    section_id,
                    payload["feature_visibility"],
                    _conn=conn,
                )
                if "feature_visibility" in payload
                else {
                    "count": 0,
                    "hidden_feature_ids": [],
                    "updated_at": now_iso(),
                }
            )

        component_results: dict[str, dict] = {}
        for assembly_id, rows in (component_rows_by_assembly or {}).items():
            if str(assembly_id) in target_by_source:
                continue
            component_results[str(assembly_id)] = save_assembly_bom_components(
                project_id,
                str(assembly_id),
                rows,
                _validate_containment=False,
                _conn=conn,
            )
        for impact in merge_impact:
            deleted_image_paths.extend(impact["source_image_paths"])
            conn.execute(
                "DELETE FROM manufacturing_assemblies WHERE project_id=? AND id=?",
                (project_id, impact["source_assembly_id"]),
            )
            impact["source_part_action"] = _release_or_remove_generated_assembly_part(
                conn, project_id, impact.get("source_part_id")
            )
        _validate_assembly_containment(conn, project_id)

    for image_path in deleted_image_paths:
        _remove_owned_upload(image_path)
    return {
        "sections": section_results,
        "mappings": mappings_result,
        "components": component_results,
        "assembly_merges": merge_impact,
        "catalog_part_relinks": part_relink_impact,
        "updated_at": now_iso(),
    }

def delete_assembly_grid_categories(
    project_id: str, section_id: str, category_ids: list[str]
) -> dict:
    """Delete selected grid categories and mappings while preserving assemblies."""
    normalized = list(dict.fromkeys(
        _catalog_text(category_id) for category_id in category_ids
        if _catalog_text(category_id)
    ))
    if not normalized:
        raise ValueError("Select at least one assembly-grid category to delete.")
    placeholders = ", ".join("?" for _ in normalized)
    with connection() as conn:
        categories = conn.execute(
            f"""SELECT id, display_name, is_top_level FROM assembly_grid_categories
                WHERE project_id=? AND section_id=? AND id IN ({placeholders})""",
            (project_id, section_id, *normalized),
        ).fetchall()
        if len(categories) != len(normalized):
            raise ValueError("One or more selected assembly-grid categories no longer exist.")
        if any(bool(row["is_top_level"]) for row in categories):
            raise ValueError(
                "The Top-level packaged unit row cannot be deleted. Clear its model "
                "mappings instead."
            )
        mapping_count = int(conn.execute(
            f"""SELECT COUNT(*) FROM assembly_grid_model_mappings
                WHERE project_id=? AND category_id IN ({placeholders})""",
            (project_id, *normalized),
        ).fetchone()[0])
        conn.execute(
            f"""DELETE FROM assembly_grid_categories
                WHERE project_id=? AND section_id=? AND id IN ({placeholders})""",
            (project_id, section_id, *normalized),
        )
        applicability_changes = _sync_assembly_catalog_part_applicability(
            conn, project_id, now_iso()
        )
    return {
        "deleted_count": len(normalized),
        "mapping_count": mapping_count,
        "category_ids": normalized,
        "category_names": [str(row["display_name"]) for row in categories],
        "catalog_part_applicability_changes": applicability_changes,
    }

def assembly_catalog_rows(project_id: str) -> pd.DataFrame:
    """Return project-wide assembly catalog rows without scenario-policy joins."""
    rows = query(
        """SELECT assembly.*, parent.assembly_number AS parent_assembly_number,
                  parent.name AS parent_name,
                  built.name AS built_section_name,
                  installed.name AS installed_section_name,
                  (SELECT COUNT(*) FROM manufacturing_assembly_components component
                   WHERE component.assembly_id=assembly.id) AS component_count,
                  (SELECT COUNT(*) FROM manufacturing_assembly_feature_rules rule
                   WHERE rule.assembly_id=assembly.id) AS rule_count,
                  (SELECT COUNT(*) FROM manufacturing_assembly_images image
                   WHERE image.assembly_id=assembly.id) AS supplemental_image_count,
                  (SELECT COUNT(*) FROM manufacturing_assembly_components component
                   JOIN fishbone_part_assignments assignment
                     ON assignment.id=component.fishbone_assignment_id
                   WHERE component.assembly_id=assembly.id
                     AND (assembly.built_section_id IS NULL
                          OR assignment.section_id<>assembly.built_section_id)) AS component_mismatch_count
           FROM manufacturing_assemblies assembly
           LEFT JOIN manufacturing_assemblies parent ON parent.id=assembly.parent_id
           LEFT JOIN assembly_sections built ON built.id=assembly.built_section_id
           LEFT JOIN assembly_sections installed ON installed.id=assembly.installed_section_id
           WHERE assembly.project_id=?
           ORDER BY assembly.assembly_number""",
        (project_id,),
    )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    stale_counts: dict[str, int] = {}
    for row in query(
        """SELECT rule.assembly_id, rule.value, feature.allowed_values, feature.active
           FROM manufacturing_assembly_feature_rules rule
           LEFT JOIN complexity_features feature ON feature.id=rule.feature_id
           WHERE rule.project_id=?""",
        (project_id,),
    ):
        try:
            allowed_values = json.loads(row.get("allowed_values") or "[]")
        except json.JSONDecodeError:
            allowed_values = []
        if not bool(row.get("active")) or str(row.get("value")) not in {
            str(value) for value in allowed_values
        }:
            assembly_id = str(row["assembly_id"])
            stale_counts[assembly_id] = stale_counts.get(assembly_id, 0) + 1
    result["stale_rule_count"] = (
        result["id"].astype(str).map(stale_counts).fillna(0).astype(int)
    )
    return result

def save_assembly_catalog_rows(project_id: str, rows) -> dict:
    """Save catalog-owned assembly fields without touching scenario-policy data."""
    records = _catalog_records(rows)
    timestamp = now_iso()
    with connection() as conn:
        current = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM manufacturing_assemblies WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        valid_sections = {
            str(row[0]) for row in conn.execute(
                "SELECT id FROM assembly_sections WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        normalized: list[dict] = []
        seen_ids: set[str] = set()
        for raw in records:
            assembly_id = _catalog_text(raw.get("id")) or str(uuid4())
            assembly_number = _catalog_text(raw.get("assembly_number"))
            name = _catalog_text(raw.get("name"))
            make_buy = _catalog_text(raw.get("make_buy"))
            built_section_id = _catalog_text(raw.get("built_section_id"))
            installed_section_id = _catalog_text(raw.get("installed_section_id"))
            parent_id = _catalog_text(raw.get("parent_id")) or None
            if assembly_id in seen_ids:
                raise ValueError("The assembly table contains a duplicate internal identifier.")
            if not assembly_number or not name:
                raise ValueError("Every assembly requires an Assembly number and Assembly name.")
            if make_buy not in {"", "Make", "Buy"}:
                raise ValueError("Make / buy must be Make or Buy.")
            previous = current.get(assembly_id)
            if previous is None and not make_buy:
                raise ValueError("Every new assembly requires a Make / buy selection.")
            if previous and _catalog_text(previous.get("make_buy")) and not make_buy:
                raise ValueError("Make / buy cannot be cleared. Choose Make or Buy.")
            managed_category = conn.execute(
                """SELECT DISTINCT category.id, category.display_name, category.section_id,
                          category.installed_section_id
                   FROM assembly_grid_model_mappings mapping
                   JOIN assembly_grid_categories category ON category.id=mapping.category_id
                   WHERE mapping.project_id=? AND mapping.assembly_id=?""",
                (project_id, assembly_id),
            ).fetchone()
            if (
                built_section_id not in valid_sections
                or (installed_section_id and installed_section_id not in valid_sections)
                or (not installed_section_id and not managed_category)
            ):
                raise ValueError(
                    "Every assembly requires valid Built section and Installed section values. "
                    "A grid-managed assembly may remain without an Installed section while its "
                    "category is unassigned."
                )
            if managed_category and (
                built_section_id != _catalog_text(managed_category["section_id"])
                or (installed_section_id or None)
                != (_catalog_text(managed_category["installed_section_id"]) or None)
            ):
                raise ValueError(
                    f"Assembly {assembly_number} is mapped under category "
                    f"{managed_category['display_name']}. Change its Built or Installed section "
                    "through the assembly grid category."
                )
            if parent_id == assembly_id:
                raise ValueError(f"Assembly {assembly_number} cannot be its own parent.")
            raw_active = raw.get("active", True)
            active = 1 if raw_active is None or pd.isna(raw_active) else int(bool(raw_active))
            seen_ids.add(assembly_id)
            normalized.append(
                {
                    "id": assembly_id,
                    "assembly_number": assembly_number,
                    "name": name,
                    "make_buy": make_buy,
                    "parent_id": parent_id,
                    "built_section_id": built_section_id,
                    "installed_section_id": installed_section_id,
                    "active": active,
                    "notes": _catalog_text(raw.get("notes")),
                }
            )

        merged = {assembly_id: dict(value) for assembly_id, value in current.items()}
        merged.update({row["id"]: row for row in normalized})
        numbers: dict[str, str] = {}
        for assembly_id, row in merged.items():
            number_key = _catalog_text(row.get("assembly_number")).casefold()
            if number_key in numbers and numbers[number_key] != assembly_id:
                raise ValueError("Assembly numbers must be unique within the project.")
            numbers[number_key] = assembly_id
        for row in normalized:
            parent_id = row["parent_id"]
            if parent_id and parent_id not in merged:
                raise ValueError(f"Assembly {row['assembly_number']} has an invalid parent assembly.")

        parent_by_id = {
            assembly_id: _catalog_text(row.get("parent_id")) or None
            for assembly_id, row in merged.items()
        }
        for assembly_id in parent_by_id:
            visited: set[str] = set()
            cursor = assembly_id
            while cursor:
                if cursor in visited:
                    raise ValueError("Assembly nesting cannot contain a cycle.")
                visited.add(cursor)
                cursor = parent_by_id.get(cursor)

        mismatch_warnings: list[dict] = []
        for row in normalized:
            parent_id = row["parent_id"]
            parent = merged.get(parent_id) if parent_id else None
            if parent and _catalog_text(row["installed_section_id"]) != _catalog_text(
                parent.get("built_section_id")
            ):
                mismatch_warnings.append(
                    {
                        "assembly_id": row["id"],
                        "assembly_number": row["assembly_number"],
                        "parent_assembly_number": _catalog_text(parent.get("assembly_number")),
                    }
                )

        make_buy_changes: list[dict] = []
        catalog_part_changes: list[dict] = []
        for row in normalized:
            previous = current.get(row["id"])
            previous_make_buy = _catalog_text(previous.get("make_buy")) if previous else ""
            if previous_make_buy != row["make_buy"]:
                make_buy_changes.append(
                    {
                        "assembly_id": row["id"],
                        "assembly_number": row["assembly_number"],
                        "old_value": previous_make_buy,
                        "new_value": row["make_buy"],
                    }
                )
            if previous:
                if _catalog_text(previous.get("built_section_id")) != row["built_section_id"]:
                    conn.execute(
                        """UPDATE fishbone_part_assignments SET section_id=?, updated_at=?
                           WHERE project_id=? AND id IN (
                               SELECT fishbone_assignment_id
                               FROM manufacturing_assembly_components
                               WHERE project_id=? AND assembly_id=?
                           )""",
                        (row["built_section_id"], timestamp, project_id, project_id, row["id"]),
                    )
                conn.execute(
                    """UPDATE manufacturing_assemblies
                       SET assembly_number=?, name=?, make_buy=?, parent_id=?, built_section_id=?,
                           installed_section_id=?, active=?, notes=?, updated_at=?
                       WHERE id=? AND project_id=?""",
                    (
                        row["assembly_number"], row["name"], row["make_buy"], row["parent_id"],
                        row["built_section_id"], row["installed_section_id"],
                        row["active"], row["notes"], timestamp, row["id"], project_id,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO manufacturing_assemblies
                       (id, project_id, assembly_number, name, make_buy, pits_reference,
                        planning_reason, parent_id, built_section_id, installed_section_id,
                        image_path, created_at, active, notes, updated_at)
                       VALUES (?, ?, ?, ?, ?, '', 'Other', ?, ?, ?, '', ?, ?, ?, ?)""",
                    (
                        row["id"], project_id, row["assembly_number"], row["name"],
                        row["make_buy"], row["parent_id"], row["built_section_id"],
                        row["installed_section_id"], timestamp, row["active"],
                        row["notes"], timestamp,
                    ),
                )
            catalog_part_changes.append(
                _ensure_assembly_catalog_part(
                    conn,
                    project_id,
                    row["id"],
                    row["assembly_number"],
                    row["name"],
                    timestamp,
                )
            )
        applicability_changes = _sync_assembly_catalog_part_applicability(
            conn, project_id, timestamp
        )
    return {
        "count": len(normalized),
        "updated_at": timestamp,
        "mismatch_warnings": mismatch_warnings,
        "make_buy_changes": make_buy_changes,
        "catalog_part_changes": catalog_part_changes,
        "catalog_part_applicability_changes": applicability_changes,
        "assembly_ids": [row["id"] for row in normalized],
    }

def assembly_bom_components(project_id: str, assembly_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT component.*, assignment.part_id, assignment.section_id,
                  assignment.quantity AS fishbone_quantity,
                  assignment.use_description, assignment.notes AS fishbone_notes,
                  part.part_number, part.description AS part_name,
                  child.id AS nested_assembly_id,
                  child.assembly_number AS nested_assembly_number,
                  section.name AS current_section_name,
                  assembly.built_section_id,
                  CASE WHEN assignment.section_id=assembly.built_section_id THEN 0 ELSE 1 END
                       AS section_mismatch
           FROM manufacturing_assembly_components component
           JOIN manufacturing_assemblies assembly ON assembly.id=component.assembly_id
           JOIN fishbone_part_assignments assignment
             ON assignment.id=component.fishbone_assignment_id
           JOIN parts part ON part.id=assignment.part_id
           LEFT JOIN manufacturing_assemblies child
             ON child.catalog_part_id=part.id AND child.project_id=component.project_id
           JOIN assembly_sections section ON section.id=assignment.section_id
           WHERE component.project_id=? AND component.assembly_id=?
           ORDER BY part.part_number, assignment.sequence""",
        (project_id, assembly_id),
    ))

def _assembly_containment_edges(
    conn: sqlite3.Connection, project_id: str
) -> list[dict]:
    """Return operational parent/child assembly links derived from mini-BOM parts."""
    return [
        dict(row)
        for row in conn.execute(
            """SELECT DISTINCT component.assembly_id AS parent_assembly_id,
                              child.id AS child_assembly_id,
                              parent.assembly_number AS parent_assembly_number,
                              child.assembly_number AS child_assembly_number
               FROM manufacturing_assembly_components component
               JOIN manufacturing_assemblies parent
                 ON parent.id=component.assembly_id AND parent.project_id=component.project_id
               JOIN fishbone_part_assignments assignment
                 ON assignment.id=component.fishbone_assignment_id
                AND assignment.project_id=component.project_id
               JOIN manufacturing_assemblies child
                 ON child.catalog_part_id=assignment.part_id
                AND child.project_id=component.project_id
               WHERE component.project_id=?""",
            (project_id,),
        ).fetchall()
    ]

def _validate_assembly_containment(
    conn: sqlite3.Connection, project_id: str
) -> None:
    """Reject mini-BOM assembly cycles and incomplete child model coverage."""
    edges = _assembly_containment_edges(conn, project_id)
    children_by_parent: dict[str, set[str]] = {}
    number_by_id: dict[str, str] = {}
    for edge in edges:
        parent_id = str(edge["parent_assembly_id"])
        child_id = str(edge["child_assembly_id"])
        number_by_id[parent_id] = str(edge["parent_assembly_number"])
        number_by_id[child_id] = str(edge["child_assembly_number"])
        if parent_id == child_id:
            raise ValueError(
                f"Assembly {number_by_id[parent_id]} cannot contain itself in its mini-BOM."
            )
        children_by_parent.setdefault(parent_id, set()).add(child_id)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(assembly_id: str, path: list[str]) -> None:
        if assembly_id in visiting:
            cycle_start = path.index(assembly_id)
            cycle = path[cycle_start:] + [assembly_id]
            labels = " → ".join(number_by_id.get(value, value) for value in cycle)
            raise ValueError(f"Assembly mini-BOM nesting cannot contain a cycle: {labels}.")
        if assembly_id in visited:
            return
        visiting.add(assembly_id)
        for child_id in children_by_parent.get(assembly_id, set()):
            visit(child_id, [*path, child_id])
        visiting.remove(assembly_id)
        visited.add(assembly_id)

    for parent_id in children_by_parent:
        visit(parent_id, [parent_id])

    mapped_models: dict[str, set[str]] = {}
    model_number_by_id: dict[str, str] = {}
    for row in conn.execute(
        """SELECT mapping.assembly_id, mapping.model_id, model.model_number
           FROM assembly_grid_model_mappings mapping
           JOIN project_models model
             ON model.id=mapping.model_id AND model.project_id=mapping.project_id
           WHERE mapping.project_id=?""",
        (project_id,),
    ).fetchall():
        mapped_models.setdefault(str(row["assembly_id"]), set()).add(str(row["model_id"]))
        model_number_by_id[str(row["model_id"])] = str(row["model_number"])
    for edge in edges:
        parent_id = str(edge["parent_assembly_id"])
        child_id = str(edge["child_assembly_id"])
        missing = mapped_models.get(parent_id, set()) - mapped_models.get(child_id, set())
        if missing:
            labels = ", ".join(
                sorted(model_number_by_id.get(model_id, model_id) for model_id in missing)
            )
            raise ValueError(
                f"Child assembly {edge['child_assembly_number']} does not cover every model "
                f"mapped to parent assembly {edge['parent_assembly_number']}. Missing: {labels}."
            )

def save_assembly_bom_components(
    project_id: str,
    assembly_id: str,
    rows,
    *,
    _validate_containment: bool = True,
    _conn: sqlite3.Connection | None = None,
) -> dict:
    records = _catalog_records(rows)
    timestamp = now_iso()
    with (connection() if _conn is None else nullcontext(_conn)) as conn:
        assembly = _require_catalog_assembly(conn, project_id, assembly_id)
        built_section_id = _catalog_text(assembly["built_section_id"])
        if not built_section_id:
            raise ValueError("Choose the assembly's Built section before editing its mini-BOM.")
        existing = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                """SELECT * FROM manufacturing_assembly_components
                   WHERE project_id=? AND assembly_id=?""",
                (project_id, assembly_id),
            ).fetchall()
        }
        normalized: list[dict] = []
        created_fishbone_uses: list[dict] = []
        assignment_ids: set[str] = set()
        row_ids: set[str] = set()
        for raw in records:
            row_id = _catalog_text(raw.get("id")) or str(uuid4())
            assignment_id = _catalog_text(raw.get("fishbone_assignment_id"))
            nested_assembly_id = _catalog_text(raw.get("nested_assembly_id"))
            if nested_assembly_id and not assignment_id:
                child = conn.execute(
                    """SELECT id, assembly_number, catalog_part_id
                       FROM manufacturing_assemblies
                       WHERE id=? AND project_id=?""",
                    (nested_assembly_id, project_id),
                ).fetchone()
                if not child or not _catalog_text(child["catalog_part_id"]):
                    raise ValueError(
                        "Every nested subassembly must be a current project assembly with a "
                        "linked Parts Catalog row."
                    )
                existing_use = conn.execute(
                    """SELECT id FROM fishbone_part_assignments
                       WHERE project_id=? AND section_id=? AND part_id=?
                       ORDER BY sequence, id LIMIT 1""",
                    (project_id, built_section_id, child["catalog_part_id"]),
                ).fetchone()
                if existing_use:
                    assignment_id = str(existing_use["id"])
                else:
                    assignment_id = str(uuid4())
                    next_sequence = conn.execute(
                        """SELECT COALESCE(MAX(sequence), 0) + 10
                           FROM fishbone_part_assignments
                           WHERE project_id=? AND section_id=?""",
                        (project_id, built_section_id),
                    ).fetchone()[0]
                    raw_quantity = raw.get("quantity")
                    try:
                        placement_quantity = float(raw_quantity or 1)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            "Nested subassembly quantities must be numbers greater than zero."
                        ) from exc
                    if not math.isfinite(placement_quantity) or placement_quantity <= 0:
                        raise ValueError(
                            "Nested subassembly quantities must be numbers greater than zero."
                        )
                    conn.execute(
                        """INSERT INTO fishbone_part_assignments
                           (id, project_id, part_id, section_id, sequence, quantity,
                            use_description, notes, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, '', ?)""",
                        (
                            assignment_id,
                            project_id,
                            child["catalog_part_id"],
                            built_section_id,
                            next_sequence,
                            placement_quantity,
                            f"Nested assembly {child['assembly_number']}",
                            timestamp,
                        ),
                    )
                    created_fishbone_uses.append(
                        {
                            "assignment_id": assignment_id,
                            "parent_assembly_id": assembly_id,
                            "parent_assembly_number": str(assembly["assembly_number"]),
                            "child_assembly_id": nested_assembly_id,
                            "child_assembly_number": str(child["assembly_number"]),
                            "section_id": built_section_id,
                        }
                    )
            if row_id in row_ids or assignment_id in assignment_ids:
                raise ValueError("Each Fishbone use may appear only once in one assembly mini-BOM.")
            assignment = conn.execute(
                """SELECT id, section_id, quantity FROM fishbone_part_assignments
                   WHERE id=? AND project_id=?""",
                (assignment_id, project_id),
            ).fetchone()
            if not assignment:
                raise ValueError("Every mini-BOM row must reference a current project Fishbone use.")
            previous = existing.get(row_id)
            raw_quantity = raw.get("quantity")
            if (
                not previous
                and (
                    raw_quantity is None
                    or pd.isna(raw_quantity)
                    or _catalog_text(raw_quantity) == ""
                )
            ):
                raw_quantity = assignment["quantity"]
            try:
                quantity = float(raw_quantity)
            except (TypeError, ValueError) as exc:
                raise ValueError("Mini-BOM quantities must be numbers greater than zero.") from exc
            if not math.isfinite(quantity) or quantity <= 0:
                raise ValueError("Mini-BOM quantities must be numbers greater than zero.")
            unchanged_stale = bool(
                previous
                and str(previous["fishbone_assignment_id"]) == assignment_id
                and round(float(previous["quantity"]), 9) == round(quantity, 9)
            )
            if str(assignment["section_id"]) != built_section_id and not unchanged_stale:
                raise ValueError(
                    "New or changed mini-BOM rows must use parts currently placed in the assembly's Built section."
                )
            row_ids.add(row_id)
            assignment_ids.add(assignment_id)
            normalized.append(
                {"id": row_id, "fishbone_assignment_id": assignment_id, "quantity": quantity}
            )
        conn.execute(
            "DELETE FROM manufacturing_assembly_components WHERE project_id=? AND assembly_id=?",
            (project_id, assembly_id),
        )
        conn.executemany(
            """INSERT INTO manufacturing_assembly_components
               (id, project_id, assembly_id, fishbone_assignment_id, quantity,
                created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    row["id"], project_id, assembly_id, row["fishbone_assignment_id"],
                    row["quantity"], existing.get(row["id"], {}).get("created_at", timestamp),
                    timestamp,
                )
                for row in normalized
            ],
        )
        if _validate_containment:
            _validate_assembly_containment(conn, project_id)
        nested_relationships = [
            edge
            for edge in _assembly_containment_edges(conn, project_id)
            if str(edge["parent_assembly_id"]) == str(assembly_id)
        ]
    return {
        "count": len(normalized),
        "created_fishbone_uses": created_fishbone_uses,
        "nested_relationships": nested_relationships,
        "updated_at": timestamp,
    }

def assembly_feature_rules(project_id: str, assembly_id: str) -> pd.DataFrame:
    rows = query(
        """SELECT rule.*, feature.name AS feature_name, feature.category,
                  feature.allowed_values, feature.active AS feature_active
           FROM manufacturing_assembly_feature_rules rule
           LEFT JOIN complexity_features feature ON feature.id=rule.feature_id
           WHERE rule.project_id=? AND rule.assembly_id=?
           ORDER BY feature.category, feature.name, rule.created_at""",
        (project_id, assembly_id),
    )
    result = pd.DataFrame(rows)
    if result.empty:
        return result

    def stale(row) -> bool:
        try:
            choices = json.loads(row.get("allowed_values") or "[]")
        except json.JSONDecodeError:
            choices = []
        return not bool(row.get("feature_active")) or str(row.get("value")) not in {
            str(choice) for choice in choices
        }

    result["stale"] = result.apply(stale, axis=1)
    result["warning"] = result["stale"].map(
        lambda value: "Warning: references a removed choice — review and update" if value else ""
    )
    return result

def save_assembly_feature_rules(project_id: str, assembly_id: str, rows) -> dict:
    records = _catalog_records(rows)
    timestamp = now_iso()
    with connection() as conn:
        _require_catalog_assembly(conn, project_id, assembly_id)
        existing = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                """SELECT * FROM manufacturing_assembly_feature_rules
                   WHERE project_id=? AND assembly_id=?""",
                (project_id, assembly_id),
            ).fetchall()
        }
        features = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM complexity_features WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        normalized: list[dict] = []
        feature_ids: set[str] = set()
        row_ids: set[str] = set()
        for raw in records:
            row_id = _catalog_text(raw.get("id")) or str(uuid4())
            feature_id = _catalog_text(raw.get("feature_id"))
            value = _catalog_text(raw.get("value"))
            if row_id in row_ids or feature_id in feature_ids:
                raise ValueError("An assembly may have at most one choice for each feature.")
            feature = features.get(feature_id)
            previous = existing.get(row_id)
            unchanged_stale = bool(
                previous
                and str(previous["feature_id"]) == feature_id
                and str(previous["value"]) == value
            )
            try:
                allowed = {
                    str(choice) for choice in json.loads((feature or {}).get("allowed_values") or "[]")
                }
            except json.JSONDecodeError:
                allowed = set()
            if (
                not feature
                or not bool(feature.get("active"))
                or value not in allowed
            ) and not unchanged_stale:
                raise ValueError(
                    "New or changed assembly rules must use an active feature and one of its current choices."
                )
            row_ids.add(row_id)
            feature_ids.add(feature_id)
            normalized.append({"id": row_id, "feature_id": feature_id, "value": value})
        conn.execute(
            """DELETE FROM manufacturing_assembly_feature_rules
               WHERE project_id=? AND assembly_id=?""",
            (project_id, assembly_id),
        )
        conn.executemany(
            """INSERT INTO manufacturing_assembly_feature_rules
               (id, project_id, assembly_id, feature_id, value, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    row["id"], project_id, assembly_id, row["feature_id"], row["value"],
                    existing.get(row["id"], {}).get("created_at", timestamp), timestamp,
                )
                for row in normalized
            ],
        )
    return {"count": len(normalized), "updated_at": timestamp}

def assembly_model_applicability(project_id: str, assembly_id: str) -> dict:
    """Return active official models explicitly paired to an assembly in the grid."""
    models = project_models(project_id)
    if not models.empty:
        models = models.loc[models["active"].fillna(1).astype(bool)].copy()
    mapped_ids = {
        str(row["model_id"])
        for row in query(
            """SELECT DISTINCT model_id FROM assembly_grid_model_mappings
               WHERE project_id=? AND assembly_id=?""",
            (project_id, assembly_id),
        )
    }
    matching = models.loc[models["id"].astype(str).isin(mapped_ids)].copy()
    return {
        "stale": False,
        "summary": "Mapped in Assembly grid" if mapped_ids else "No mapped models",
        "models": matching,
    }

def assembly_images(project_id: str, assembly_id: str) -> list[dict]:
    return query(
        """SELECT * FROM manufacturing_assembly_images
           WHERE project_id=? AND assembly_id=? ORDER BY created_at""",
        (project_id, assembly_id),
    )

def _assembly_image_target(assembly_id: str, uploaded_file) -> Path:
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Use PNG, JPG, JPEG, or WEBP images.")
    return UPLOAD_DIR / f"assembly_{assembly_id}_{uuid4()}{suffix}"

def _remove_owned_upload(path_value) -> None:
    if not path_value:
        return
    path = Path(str(path_value))
    try:
        if path.exists() and path.is_file() and UPLOAD_DIR.resolve() in path.resolve().parents:
            path.unlink()
    except OSError:
        pass

def set_assembly_image(project_id: str, assembly_id: str, uploaded_file) -> str:
    target = _assembly_image_target(assembly_id, uploaded_file)
    content = uploaded_file.getvalue()
    if not content:
        raise ValueError("Choose a non-empty image.")
    target.write_bytes(content)
    previous_path = ""
    try:
        with connection() as conn:
            assembly = _require_catalog_assembly(conn, project_id, assembly_id)
            previous_path = _catalog_text(assembly["image_path"])
            conn.execute(
                """UPDATE manufacturing_assemblies SET image_path=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (str(target), now_iso(), assembly_id, project_id),
            )
    except Exception:
        _remove_owned_upload(target)
        raise
    if previous_path != str(target):
        _remove_owned_upload(previous_path)
    return str(target)

def add_assembly_image(
    project_id: str, assembly_id: str, uploaded_file, caption: str = ""
) -> str:
    target = _assembly_image_target(assembly_id, uploaded_file)
    content = uploaded_file.getvalue()
    if not content:
        raise ValueError("Choose a non-empty image.")
    target.write_bytes(content)
    image_id = str(uuid4())
    try:
        with connection() as conn:
            _require_catalog_assembly(conn, project_id, assembly_id)
            conn.execute(
                """INSERT INTO manufacturing_assembly_images
                   (id, project_id, assembly_id, image_path, caption, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (image_id, project_id, assembly_id, str(target), _catalog_text(caption), now_iso()),
            )
    except Exception:
        _remove_owned_upload(target)
        raise
    return image_id

def delete_assembly_images(
    project_id: str, assembly_id: str, image_ids: list[str]
) -> int:
    normalized = list(
        dict.fromkeys(_catalog_text(value) for value in image_ids if _catalog_text(value))
    )
    if not normalized:
        return 0
    placeholders = ",".join("?" for _ in normalized)
    with connection() as conn:
        _require_catalog_assembly(conn, project_id, assembly_id)
        rows = conn.execute(
            f"""SELECT id, image_path FROM manufacturing_assembly_images
                WHERE project_id=? AND assembly_id=? AND id IN ({placeholders})""",
            (project_id, assembly_id, *normalized),
        ).fetchall()
        if len(rows) != len(normalized):
            raise ValueError("One or more selected assembly images no longer exist.")
        conn.execute(
            f"""DELETE FROM manufacturing_assembly_images
                WHERE project_id=? AND assembly_id=? AND id IN ({placeholders})""",
            (project_id, assembly_id, *normalized),
        )
    for row in rows:
        _remove_owned_upload(row["image_path"])
    return len(rows)

def assemblies_for_section(project_id: str, section_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT assembly.id, assembly.assembly_number, assembly.name,
                  'Built here' AS relationship
           FROM manufacturing_assemblies assembly
           WHERE assembly.project_id=? AND assembly.built_section_id=?
           UNION ALL
           SELECT assembly.id, assembly.assembly_number, assembly.name,
                  'Installed here' AS relationship
           FROM manufacturing_assemblies assembly
           WHERE assembly.project_id=? AND assembly.installed_section_id=?
           ORDER BY assembly_number, relationship""",
        (project_id, section_id, project_id, section_id),
    ))

def fishbone_assignment_assembly_impact(
    project_id: str, assignment_ids: list[str]
) -> pd.DataFrame:
    normalized = list(
        dict.fromkeys(_catalog_text(value) for value in assignment_ids if _catalog_text(value))
    )
    if not normalized:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in normalized)
    return pd.DataFrame(query(
        f"""SELECT component.id AS component_id, component.fishbone_assignment_id,
                   assembly.id AS assembly_id, assembly.assembly_number, assembly.name
            FROM manufacturing_assembly_components component
            JOIN manufacturing_assemblies assembly ON assembly.id=component.assembly_id
            WHERE component.project_id=?
              AND component.fishbone_assignment_id IN ({placeholders})
            ORDER BY assembly.assembly_number""",
        (project_id, *normalized),
    ))

def assembly_section_reference_impact(
    project_id: str,
    section_ids: list[str],
    connection: sqlite3.Connection | None = None,
) -> pd.DataFrame:
    normalized = list(
        dict.fromkeys(_catalog_text(value) for value in section_ids if _catalog_text(value))
    )
    if not normalized:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in normalized)
    sql = f"""SELECT assembly.id AS assembly_id, assembly.assembly_number, assembly.name,
                     assembly.built_section_id, built.name AS built_section_name,
                     assembly.installed_section_id, installed.name AS installed_section_name
              FROM manufacturing_assemblies assembly
              LEFT JOIN assembly_sections built ON built.id=assembly.built_section_id
              LEFT JOIN assembly_sections installed ON installed.id=assembly.installed_section_id
              WHERE assembly.project_id=? AND (
                  assembly.built_section_id IN ({placeholders})
                  OR assembly.installed_section_id IN ({placeholders})
              ) ORDER BY assembly.assembly_number"""
    params = (project_id, *normalized, *normalized)
    if connection is not None:
        return pd.DataFrame([dict(row) for row in connection.execute(sql, params).fetchall()])
    return pd.DataFrame(query(sql, params))

def repoint_assembly_section_references(
    project_id: str, replacements, connection: sqlite3.Connection | None = None
) -> int:
    records = _catalog_records(replacements)
    timestamp = now_iso()
    context = nullcontext(connection) if connection is not None else globals()["connection"]()
    with context as conn:
        valid_sections = {
            str(row[0]) for row in conn.execute(
                "SELECT id FROM assembly_sections WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        normalized: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for row in records:
            assembly_id = _catalog_text(row.get("assembly_id"))
            field = _catalog_text(row.get("field"))
            section_id = _catalog_text(row.get("section_id"))
            if field not in {"built_section_id", "installed_section_id"}:
                raise ValueError("Choose whether each replacement applies to Built or Installed section.")
            if section_id not in valid_sections:
                raise ValueError("Every assembly section replacement must be a current project section.")
            _require_catalog_assembly(conn, project_id, assembly_id)
            if (assembly_id, field) in seen:
                raise ValueError("Each assembly section relationship needs exactly one replacement.")
            seen.add((assembly_id, field))
            normalized.append((assembly_id, field, section_id))
        for assembly_id, field, section_id in normalized:
            if field == "built_section_id":
                conn.execute(
                    """UPDATE fishbone_part_assignments SET section_id=?, updated_at=?
                       WHERE project_id=? AND id IN (
                           SELECT fishbone_assignment_id
                           FROM manufacturing_assembly_components
                           WHERE project_id=? AND assembly_id=?
                       )""",
                    (section_id, timestamp, project_id, project_id, assembly_id),
                )
            conn.execute(
                f"""UPDATE manufacturing_assemblies SET {field}=?, updated_at=?
                    WHERE id=? AND project_id=?""",
                (section_id, timestamp, assembly_id, project_id),
            )
    return len(normalized)

def assembly_catalog_delete_impact(project_id: str, assembly_ids: list[str]) -> dict:
    normalized = list(
        dict.fromkeys(_catalog_text(value) for value in assembly_ids if _catalog_text(value))
    )
    if not normalized:
        raise ValueError("Select at least one assembly to delete.")
    placeholders = ",".join("?" for _ in normalized)
    with connection() as conn:
        selected_count = conn.execute(
            f"""SELECT COUNT(*) FROM manufacturing_assemblies
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *normalized),
        ).fetchone()[0]
        if int(selected_count) != len(normalized):
            raise ValueError("One or more selected assemblies no longer exist.")
        rows = conn.execute(
            f"""WITH RECURSIVE tree(id, assembly_number, name, parent_id, depth) AS (
                    SELECT id, assembly_number, name, parent_id, 0
                    FROM manufacturing_assemblies
                    WHERE project_id=? AND id IN ({placeholders})
                    UNION
                    SELECT child.id, child.assembly_number, child.name, child.parent_id,
                           tree.depth + 1
                    FROM manufacturing_assemblies child JOIN tree ON child.parent_id=tree.id
                    WHERE child.project_id=?
                )
                SELECT id, assembly_number, name, parent_id, MIN(depth) AS depth
                FROM tree GROUP BY id, assembly_number, name, parent_id
                ORDER BY depth, assembly_number""",
            (project_id, *normalized, project_id),
        ).fetchall()
        affected_ids = [str(row["id"]) for row in rows]
        affected_placeholders = ",".join("?" for _ in affected_ids)

        def count(table: str, column: str = "assembly_id") -> int:
            return int(conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IN ({affected_placeholders})",
                tuple(affected_ids),
            ).fetchone()[0])

        levels: dict[int, list[dict]] = {}
        for row in rows:
            levels.setdefault(int(row["depth"]), []).append(dict(row))
        image_paths = [
            str(row[0]) for row in conn.execute(
                f"""SELECT image_path FROM manufacturing_assemblies
                    WHERE id IN ({affected_placeholders}) AND TRIM(COALESCE(image_path, ''))<>''
                    UNION ALL
                    SELECT image_path FROM manufacturing_assembly_images
                    WHERE assembly_id IN ({affected_placeholders})""",
                (*affected_ids, *affected_ids),
            ).fetchall()
        ]
        preserved_catalog_parts = [
            dict(row)
            for row in conn.execute(
                f"""SELECT assembly.id AS assembly_id, assembly.assembly_number,
                            part.id AS part_id, part.part_number
                     FROM manufacturing_assemblies assembly
                     JOIN parts part ON part.id=assembly.catalog_part_id
                     WHERE assembly.id IN ({affected_placeholders})
                     ORDER BY assembly.assembly_number""",
                tuple(affected_ids),
            ).fetchall()
        ]
        nested_parent_links = [
            dict(row)
            for row in conn.execute(
                f"""SELECT DISTINCT child.id AS child_assembly_id,
                                   child.assembly_number AS child_assembly_number,
                                   parent.id AS parent_assembly_id,
                                   parent.assembly_number AS parent_assembly_number
                    FROM manufacturing_assemblies child
                    JOIN fishbone_part_assignments assignment
                      ON assignment.part_id=child.catalog_part_id
                     AND assignment.project_id=child.project_id
                    JOIN manufacturing_assembly_components component
                      ON component.fishbone_assignment_id=assignment.id
                     AND component.project_id=child.project_id
                    JOIN manufacturing_assemblies parent
                      ON parent.id=component.assembly_id
                    WHERE child.project_id=?
                      AND child.id IN ({affected_placeholders})
                    ORDER BY child.assembly_number, parent.assembly_number""",
                (project_id, *affected_ids),
            ).fetchall()
        ]
        return {
            "selected_ids": normalized,
            "affected_ids": affected_ids,
            "selected_count": len(normalized),
            "descendant_count": len(affected_ids) - len(normalized),
            "levels": levels,
            "component_count": count("manufacturing_assembly_components"),
            "rule_count": count("manufacturing_assembly_feature_rules"),
            "supplemental_image_count": count("manufacturing_assembly_images"),
            "grid_mapping_count": count("assembly_grid_model_mappings"),
            "primary_image_count": int(conn.execute(
                f"""SELECT COUNT(*) FROM manufacturing_assemblies
                    WHERE id IN ({affected_placeholders})
                      AND TRIM(COALESCE(image_path, ''))<>''""",
                tuple(affected_ids),
            ).fetchone()[0]),
            "image_paths": image_paths,
            "image_file_count": len(image_paths),
            "policy_count": count("assembly_scenario_policies"),
            "material_option_count": count("work_element_material_options"),
            "target_assembly_link_count": count(
                "work_element_material_groups", "target_assembly_id"
            ),
            "preserved_catalog_parts": preserved_catalog_parts,
            "preserved_catalog_part_count": len(preserved_catalog_parts),
            "nested_parent_links": nested_parent_links,
            "nested_parent_link_count": len(nested_parent_links),
        }

def delete_assembly_catalog_rows(
    project_id: str, assembly_ids: list[str], level_actions: dict
) -> dict:
    impact = assembly_catalog_delete_impact(project_id, assembly_ids)
    actions = {int(depth): str(action) for depth, action in dict(level_actions or {}).items()}
    allowed = {"Move to grandparent", "Delete entirely", "Become unassigned"}
    for depth in impact["levels"]:
        if depth > 0 and actions.get(depth) not in allowed:
            raise ValueError(f"Choose what happens to child assemblies at level {depth}.")
    selected_ids = set(impact["selected_ids"])
    deleted_ids = set(selected_ids)
    for depth, rows in impact["levels"].items():
        if depth > 0 and actions.get(depth) == "Delete entirely":
            deleted_ids.update(str(row["id"]) for row in rows)
    all_rows = {
        str(row["id"]): dict(row)
        for depth_rows in impact["levels"].values() for row in depth_rows
    }
    image_paths: list[str] = []
    timestamp = now_iso()
    with connection() as conn:
        if deleted_ids:
            placeholders = ",".join("?" for _ in deleted_ids)
            image_paths.extend(
                str(row[0]) for row in conn.execute(
                    f"""SELECT image_path FROM manufacturing_assemblies
                        WHERE project_id=? AND id IN ({placeholders})
                          AND TRIM(COALESCE(image_path, ''))<>''""",
                    (project_id, *deleted_ids),
                ).fetchall()
            )
            image_paths.extend(
                str(row[0]) for row in conn.execute(
                    f"""SELECT image_path FROM manufacturing_assembly_images
                        WHERE project_id=? AND assembly_id IN ({placeholders})""",
                    (project_id, *deleted_ids),
                ).fetchall()
            )
        for depth, rows in impact["levels"].items():
            if depth == 0 or actions.get(depth) == "Delete entirely":
                continue
            action = actions[depth]
            for row in rows:
                assembly_id = str(row["id"])
                if assembly_id in deleted_ids:
                    continue
                if action == "Become unassigned":
                    conn.execute(
                        """UPDATE manufacturing_assemblies
                           SET parent_id=NULL, built_section_id=NULL, installed_section_id=NULL,
                               updated_at=? WHERE id=? AND project_id=?""",
                        (timestamp, assembly_id, project_id),
                    )
                else:
                    parent_id = _catalog_text(row.get("parent_id")) or None
                    while parent_id in deleted_ids:
                        parent_id = (
                            _catalog_text(all_rows.get(parent_id, {}).get("parent_id")) or None
                        )
                    conn.execute(
                        """UPDATE manufacturing_assemblies SET parent_id=?, updated_at=?
                           WHERE id=? AND project_id=?""",
                        (parent_id, timestamp, assembly_id, project_id),
                    )
        if deleted_ids:
            placeholders = ",".join("?" for _ in deleted_ids)
            conn.execute(
                f"""DELETE FROM manufacturing_assemblies
                    WHERE project_id=? AND id IN ({placeholders})""",
                (project_id, *deleted_ids),
            )
    for path in image_paths:
        _remove_owned_upload(path)
    return {**impact, "deleted_count": len(deleted_ids), "level_actions": actions}

def reset_manufacturing_assembly_catalog(
    verified_backup_path: str | Path,
    editor_name: str,
) -> dict:
    """Perform the approved one-time catalog reset after validating its DB backup."""
    backup_path = Path(verified_backup_path).resolve()
    if not backup_path.exists() or not backup_path.is_file() or backup_path.stat().st_size <= 0:
        raise ValueError("Confirm a valid PAAG database backup before resetting assemblies.")
    if backup_path == DB_PATH.resolve():
        raise ValueError("The verified backup must be separate from the live PAAG database.")
    with closing(sqlite3.connect(
        f"file:{backup_path.as_posix()}?mode=ro", uri=True
    )) as backup_conn:
        result = backup_conn.execute("PRAGMA quick_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            raise ValueError("The verified PAAG database backup did not pass SQLite validation.")

    timestamp = now_iso()
    image_paths: list[str] = []
    summary: dict = {}
    with connection() as conn:
        project_counts = [dict(row) for row in conn.execute(
            """SELECT project_id, COUNT(*) AS assembly_count
               FROM manufacturing_assemblies GROUP BY project_id"""
        ).fetchall()]

        def table_count(table: str) -> int:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

        image_paths = [
            str(row[0])
            for row in conn.execute(
                """SELECT image_path FROM manufacturing_assemblies
                   WHERE TRIM(COALESCE(image_path, ''))<>''
                   UNION ALL
                   SELECT image_path FROM manufacturing_assembly_images"""
            ).fetchall()
        ]
        summary = {
            "assembly_count": table_count("manufacturing_assemblies"),
            "component_count": table_count("manufacturing_assembly_components"),
            "feature_rule_count": table_count("manufacturing_assembly_feature_rules"),
            "supplemental_image_count": table_count("manufacturing_assembly_images"),
            "owned_image_file_count": len(image_paths),
            "grid_mapping_count": table_count("assembly_grid_model_mappings"),
            "scenario_policy_count": table_count("assembly_scenario_policies"),
            "material_option_count": int(conn.execute(
                "SELECT COUNT(*) FROM work_element_material_options WHERE assembly_id IS NOT NULL"
            ).fetchone()[0]),
            "material_target_count": int(conn.execute(
                "SELECT COUNT(*) FROM work_element_material_groups WHERE target_assembly_id IS NOT NULL"
            ).fetchone()[0]),
            "backup_path": str(backup_path),
        }
        conn.execute("DELETE FROM manufacturing_assemblies")
        for project in project_counts:
            details = {
                **summary,
                "project_assembly_count": int(project["assembly_count"]),
                "scope": "Approved Task 09 one-time assembly-catalog reset",
            }
            conn.execute(
                """INSERT INTO audit_log
                   (id, project_id, table_name, action, row_count, editor_name, details, created_at)
                   VALUES (?, ?, 'Assemblies catalog', 'Prototype data reset', ?, ?, ?, ?)""",
                (
                    str(uuid4()),
                    str(project["project_id"]),
                    int(project["assembly_count"]),
                    editor_name.strip(),
                    json.dumps(details, ensure_ascii=False),
                    timestamp,
                ),
            )
    for image_path in image_paths:
        _remove_owned_upload(image_path)
    return summary

def manufacturing_assemblies(project_id: str, scenario_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT a.*, parent.assembly_number AS parent_assembly_number,
                  parent.name AS parent_name,
                  COALESCE(policy.sourcing_decision, 'Undecided') AS sourcing_decision,
                  COALESCE(policy.supplier, '') AS supplier,
                  COALESCE(policy.build_area, '') AS build_area,
                  COALESCE(policy.buffer_policy, 'None') AS buffer_policy,
                  COALESCE(policy.storage_location, '') AS storage_location,
                  policy.minimum_quantity, policy.target_quantity, policy.maximum_quantity
           FROM manufacturing_assemblies a
           LEFT JOIN manufacturing_assemblies parent ON parent.id=a.parent_id
           LEFT JOIN assembly_scenario_policies policy
             ON policy.assembly_id=a.id AND policy.scenario_id=?
           WHERE a.project_id=?
           ORDER BY a.assembly_number""",
        (scenario_id, project_id),
    ))

def _optional_nonnegative_number(value, label: str) -> float | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if number < 0:
        raise ValueError(f"{label} cannot be negative.")
    return number

def _assembly_text(value) -> str:
    """Normalize nullable values coming from pandas-backed table editors."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()

def replace_manufacturing_assemblies(
    project_id: str, scenario_id: str, edited: pd.DataFrame
) -> int:
    required = {
        "id", "assembly_number", "name", "pits_reference", "planning_reason",
        "parent_id", "active", "notes", "sourcing_decision", "supplier",
        "build_area", "buffer_policy", "storage_location", "minimum_quantity",
        "target_quantity", "maximum_quantity",
    }
    if not required.issubset(edited.columns):
        raise ValueError("The manufacturing-assembly table is missing required columns.")
    if not get_planning_scenario(project_id, scenario_id):
        raise ValueError("The active planning scenario no longer exists.")

    timestamp = now_iso()
    records: list[dict] = []
    seen_numbers: set[str] = set()
    for row in edited.to_dict("records"):
        assembly_number = _assembly_text(row.get("assembly_number"))
        name = _assembly_text(row.get("name"))
        if not assembly_number or not name:
            raise ValueError("Every manufacturing assembly needs an assembly number and name.")
        normalized_number = assembly_number.casefold()
        if normalized_number in seen_numbers:
            raise ValueError("Manufacturing assembly numbers must be unique within the project.")
        seen_numbers.add(normalized_number)
        planning_reason = _assembly_text(row.get("planning_reason")) or "Other"
        sourcing = (_assembly_text(row.get("sourcing_decision")) or "Undecided").title()
        buffer_policy = _assembly_text(row.get("buffer_policy")) or "None"
        if planning_reason not in ASSEMBLY_PLANNING_REASONS:
            raise ValueError(f"Choose a valid planning reason for {assembly_number}.")
        if sourcing not in ASSEMBLY_SOURCING_DECISIONS:
            raise ValueError(f"Choose Make, Buy, or Undecided for {assembly_number}.")
        if buffer_policy not in ASSEMBLY_BUFFER_POLICIES:
            raise ValueError(f"Choose a valid buffer policy for {assembly_number}.")
        minimum = _optional_nonnegative_number(row.get("minimum_quantity"), "Minimum quantity")
        target = _optional_nonnegative_number(row.get("target_quantity"), "Target quantity")
        maximum = _optional_nonnegative_number(row.get("maximum_quantity"), "Maximum quantity")
        ordered = [value for value in (minimum, target, maximum) if value is not None]
        if ordered != sorted(ordered):
            raise ValueError(
                f"Minimum, target, and maximum quantities must increase in that order for {assembly_number}."
            )
        records.append({
            "id": _assembly_text(row.get("id")) or str(uuid4()),
            "assembly_number": assembly_number,
            "name": name,
            "pits_reference": _assembly_text(row.get("pits_reference")),
            "planning_reason": planning_reason,
            "parent_id": _assembly_text(row.get("parent_id")) or None,
            "active": int(True if pd.isna(row.get("active")) else bool(row.get("active"))),
            "notes": _assembly_text(row.get("notes")),
            "sourcing_decision": sourcing,
            "supplier": _assembly_text(row.get("supplier")),
            "build_area": _assembly_text(row.get("build_area")),
            "buffer_policy": buffer_policy,
            "storage_location": _assembly_text(row.get("storage_location")),
            "minimum_quantity": minimum,
            "target_quantity": target,
            "maximum_quantity": maximum,
        })

    ids = {record["id"] for record in records}
    parent_by_id = {record["id"]: record["parent_id"] for record in records}
    for assembly_id, parent_id in parent_by_id.items():
        if parent_id and parent_id not in ids:
            raise ValueError("Every parent assembly must exist in the saved table.")
        if parent_id == assembly_id:
            raise ValueError("An assembly cannot be its own parent.")
        visited: set[str] = set()
        cursor = assembly_id
        while cursor:
            if cursor in visited:
                raise ValueError("Assembly parent relationships cannot contain a cycle.")
            visited.add(cursor)
            cursor = parent_by_id.get(cursor)

    try:
        with connection() as conn:
            existing = {
                str(row[0]) for row in conn.execute(
                    "SELECT id FROM manufacturing_assemblies WHERE project_id=?", (project_id,)
                ).fetchall()
            }
            kept = {record["id"] for record in records}
            for record in records:
                conn.execute(
                    """INSERT INTO manufacturing_assemblies
                       (id, project_id, assembly_number, name, pits_reference, planning_reason,
                        parent_id, active, notes, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET assembly_number=excluded.assembly_number,
                        name=excluded.name, pits_reference=excluded.pits_reference,
                        planning_reason=excluded.planning_reason, parent_id=NULL,
                        active=excluded.active, notes=excluded.notes, updated_at=excluded.updated_at""",
                    (
                        record["id"], project_id, record["assembly_number"], record["name"],
                        record["pits_reference"], record["planning_reason"], record["active"],
                        record["notes"], timestamp,
                    ),
                )
                conn.execute(
                    """INSERT INTO assembly_scenario_policies
                       (project_id, scenario_id, assembly_id, sourcing_decision, supplier,
                        build_area, buffer_policy, storage_location, minimum_quantity,
                        target_quantity, maximum_quantity, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(scenario_id, assembly_id) DO UPDATE SET
                        sourcing_decision=excluded.sourcing_decision, supplier=excluded.supplier,
                        build_area=excluded.build_area, buffer_policy=excluded.buffer_policy,
                        storage_location=excluded.storage_location,
                        minimum_quantity=excluded.minimum_quantity,
                        target_quantity=excluded.target_quantity,
                        maximum_quantity=excluded.maximum_quantity,
                        updated_at=excluded.updated_at""",
                    (
                        project_id, scenario_id, record["id"], record["sourcing_decision"],
                        record["supplier"], record["build_area"], record["buffer_policy"],
                        record["storage_location"], record["minimum_quantity"],
                        record["target_quantity"], record["maximum_quantity"], timestamp,
                    ),
                )
            for record in records:
                conn.execute(
                    "UPDATE manufacturing_assemblies SET parent_id=? WHERE id=? AND project_id=?",
                    (record["parent_id"], record["id"], project_id),
                )
            removed = existing - kept
            if removed:
                placeholders = ",".join("?" for _ in removed)
                conn.execute(
                    f"DELETE FROM manufacturing_assemblies WHERE project_id=? AND id IN ({placeholders})",
                    (project_id, *removed),
                )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Manufacturing assembly numbers must be unique within the project.") from exc
    return len(records)

def bulk_update_assembly_policy(
    project_id: str,
    scenario_id: str,
    assembly_ids: list[str],
    sourcing_decision: str | None = None,
    buffer_policy: str | None = None,
) -> int:
    if not assembly_ids:
        return 0
    if sourcing_decision and sourcing_decision not in ASSEMBLY_SOURCING_DECISIONS:
        raise ValueError("Choose Make, Buy, or Undecided.")
    if buffer_policy and buffer_policy not in ASSEMBLY_BUFFER_POLICIES:
        raise ValueError("Choose a valid buffer policy.")
    if not sourcing_decision and not buffer_policy:
        raise ValueError("Choose a sourcing decision or buffer policy to apply.")
    timestamp = now_iso()
    with connection() as conn:
        valid_ids = {
            str(row[0]) for row in conn.execute(
                f"""SELECT id FROM manufacturing_assemblies
                    WHERE project_id=? AND id IN ({','.join('?' for _ in assembly_ids)})""",
                (project_id, *assembly_ids),
            ).fetchall()
        }
        for assembly_id in valid_ids:
            conn.execute(
                """INSERT INTO assembly_scenario_policies
                   (project_id, scenario_id, assembly_id, sourcing_decision, buffer_policy, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(scenario_id, assembly_id) DO UPDATE SET
                    sourcing_decision=COALESCE(?, sourcing_decision),
                    buffer_policy=COALESCE(?, buffer_policy), updated_at=?""",
                (
                    project_id, scenario_id, assembly_id,
                    sourcing_decision or "Undecided", buffer_policy or "None", timestamp,
                    sourcing_decision, buffer_policy, timestamp,
                ),
            )
    return len(valid_ids)

def delete_manufacturing_assembly(project_id: str, assembly_id: str) -> str:
    with connection() as conn:
        row = conn.execute(
            "SELECT assembly_number, name FROM manufacturing_assemblies WHERE id=? AND project_id=?",
            (assembly_id, project_id),
        ).fetchone()
        if not row:
            raise ValueError("That manufacturing assembly no longer exists.")
        conn.execute(
            "DELETE FROM manufacturing_assemblies WHERE id=? AND project_id=?",
            (assembly_id, project_id),
        )
        return f"{row['assembly_number']} — {row['name']}"

def work_element_material_groups(
    project_id: str, scenario_id: str, yamazumi_element_id: str
) -> list[dict]:
    groups = query(
        """SELECT group_row.*, target.assembly_number AS target_assembly_number,
                  target.name AS target_assembly_name
           FROM work_element_material_groups group_row
           LEFT JOIN manufacturing_assemblies target ON target.id=group_row.target_assembly_id
           WHERE group_row.project_id=? AND group_row.scenario_id=?
             AND group_row.yamazumi_element_id=?
           ORDER BY group_row.name""",
        (project_id, scenario_id, yamazumi_element_id),
    )
    for group in groups:
        options = query(
            """SELECT option.id, option.part_id, option.assembly_id,
                      part.part_number, part.description AS part_description,
                      assembly.assembly_number, assembly.name AS assembly_name
               FROM work_element_material_options option
               LEFT JOIN parts part ON part.id=option.part_id
               LEFT JOIN manufacturing_assemblies assembly ON assembly.id=option.assembly_id
               WHERE option.group_id=? ORDER BY part.part_number, assembly.assembly_number""",
            (group["id"],),
        )
        group["options"] = options
        group["option_tokens"] = [
            f"part:{option['part_id']}" if option.get("part_id") else f"assembly:{option['assembly_id']}"
            for option in options
        ]
    return groups

def save_work_element_material_group(
    project_id: str,
    scenario_id: str,
    yamazumi_element_id: str,
    group_id: str | None,
    target_assembly_id: str | None,
    name: str,
    selection_rule: str,
    quantity: float,
    option_tokens: list[str],
    notes: str = "",
) -> str:
    name = str(name or "").strip()
    if not name:
        raise ValueError("Material requirement name is required.")
    if selection_rule not in MATERIAL_SELECTION_RULES:
        raise ValueError("Choose a valid material selection rule.")
    try:
        quantity = float(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("Material quantity must be a number.") from exc
    if quantity <= 0:
        raise ValueError("Material quantity must be greater than zero.")
    tokens = list(dict.fromkeys(str(token) for token in option_tokens if str(token)))
    if not tokens:
        raise ValueError("Choose at least one part or manufacturing assembly.")
    group_id = str(group_id or "").strip() or str(uuid4())
    timestamp = now_iso()
    try:
        with connection() as conn:
            valid_element = conn.execute(
                """SELECT 1 FROM yamazumi_elements element
                   JOIN yamazumi_areas area ON area.id=element.area_id
                   WHERE element.id=? AND element.project_id=? AND area.scenario_id=?""",
                (yamazumi_element_id, project_id, scenario_id),
            ).fetchone()
            if not valid_element:
                raise ValueError("That Yamazumi work element no longer exists in this scenario.")
            target_assembly_id = str(target_assembly_id or "").strip() or None
            if target_assembly_id and not conn.execute(
                """SELECT 1 FROM manufacturing_assemblies
                   WHERE id=? AND project_id=? AND active=1""",
                (target_assembly_id, project_id),
            ).fetchone():
                raise ValueError("The selected target assembly no longer exists or is inactive.")
            conn.execute(
                """INSERT INTO work_element_material_groups
                   (id, project_id, scenario_id, yamazumi_element_id, target_assembly_id, name,
                    selection_rule, quantity, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                    target_assembly_id=excluded.target_assembly_id,
                    selection_rule=excluded.selection_rule, quantity=excluded.quantity,
                    notes=excluded.notes, updated_at=excluded.updated_at""",
                (
                    group_id, project_id, scenario_id, yamazumi_element_id,
                    target_assembly_id, name,
                    selection_rule, quantity, str(notes or "").strip(), timestamp,
                ),
            )
            conn.execute("DELETE FROM work_element_material_options WHERE group_id=?", (group_id,))
            for token in tokens:
                kind, separator, item_id = token.partition(":")
                if not separator or kind not in {"part", "assembly"} or not item_id:
                    raise ValueError("A selected material option is invalid.")
                table = "parts" if kind == "part" else "manufacturing_assemblies"
                if not conn.execute(
                    f"SELECT 1 FROM {table} WHERE id=? AND project_id=?", (item_id, project_id)
                ).fetchone():
                    raise ValueError("A selected material option no longer exists in this project.")
                conn.execute(
                    """INSERT INTO work_element_material_options
                       (id, group_id, part_id, assembly_id, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        str(uuid4()), group_id, item_id if kind == "part" else None,
                        item_id if kind == "assembly" else None, timestamp,
                    ),
                )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Material requirement names must be unique within a work element.") from exc
    return group_id

def delete_work_element_material_group(
    project_id: str, scenario_id: str, group_id: str
) -> bool:
    with connection() as conn:
        cursor = conn.execute(
            """DELETE FROM work_element_material_groups
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (group_id, project_id, scenario_id),
        )
        return bool(cursor.rowcount)

def material_consumption_for_scenario(project_id: str, scenario_id: str) -> pd.DataFrame:
    rows = query(
        """SELECT group_row.id AS group_id, element.id AS process_element_id,
                  group_row.section_id, section.name AS section_name,
                  group_row.name AS requirement,
                  group_row.selection_rule, group_row.quantity,
                  part.part_number, part.description AS part_description,
                  option.handling_type, option.fishbone_assignment_id, part.weight_lb,
                  group_row.notes
           FROM process_part_groups group_row
           JOIN work_elements element ON element.id=group_row.work_element_id
           LEFT JOIN assembly_sections section ON section.id=group_row.section_id
           LEFT JOIN process_part_options option ON option.group_id=group_row.id
           LEFT JOIN parts part ON part.id=option.part_id
           LEFT JOIN part_scenario_activity activity
             ON activity.project_id=group_row.project_id
            AND activity.scenario_id=group_row.scenario_id
            AND activity.part_id=option.part_id
           WHERE group_row.project_id=? AND group_row.scenario_id=?
             AND (option.part_id IS NULL OR COALESCE(activity.active, 1)=1)
           ORDER BY element.sequence, group_row.name, part.part_number""",
        (project_id, scenario_id),
    )
    return pd.DataFrame(rows)

def assembly_catalog_part_applicability(project_id: str) -> pd.DataFrame:
    """Return linked assembly parts and their directly mapped active official models."""
    rows = query(
        """SELECT assembly.catalog_part_id AS part_id, assembly.id AS assembly_id,
                  assembly.assembly_number, model.model_number
           FROM manufacturing_assemblies assembly
           LEFT JOIN assembly_grid_model_mappings mapping
             ON mapping.project_id=assembly.project_id AND mapping.assembly_id=assembly.id
           LEFT JOIN project_models model
             ON model.id=mapping.model_id AND model.project_id=assembly.project_id
            AND model.active=1
           WHERE assembly.project_id=? AND assembly.catalog_part_id IS NOT NULL
           ORDER BY assembly.assembly_number, model.model_number""",
        (project_id,),
    )
    grouped: dict[str, dict] = {}
    for row in rows:
        part_id = str(row["part_id"])
        grouped.setdefault(
            part_id,
            {
                "part_id": part_id,
                "assembly_id": str(row["assembly_id"]),
                "assembly_number": str(row["assembly_number"]),
                "model_numbers": [],
            },
        )
        if row.get("model_number") is not None:
            grouped[part_id]["model_numbers"].append(str(row["model_number"]))
    result = []
    for row in grouped.values():
        model_numbers = list(dict.fromkeys(row.pop("model_numbers")))
        result.append({**row, "model_applicability": ", ".join(model_numbers)})
    return pd.DataFrame(
        result,
        columns=["part_id", "assembly_id", "assembly_number", "model_applicability"],
    )

__domain_exports__ = ['ASSEMBLY_PLANNING_REASONS', 'ASSEMBLY_SOURCING_DECISIONS', 'ASSEMBLY_BUFFER_POLICIES', 'MATERIAL_SELECTION_RULES', '_catalog_records', '_catalog_text', '_require_catalog_assembly', '_catalog_part_by_number', '_assembly_part_relationship_counts', '_release_or_remove_generated_assembly_part', '_ensure_assembly_catalog_part', '_sync_assembly_catalog_part_applicability', 'assembly_grid_categories', 'assembly_grid_model_mappings', 'assembly_grid_feature_visibility', 'save_assembly_grid_categories', 'assembly_grid_part_relink_impact', 'save_assembly_grid_model_mappings', 'assembly_grid_number_merge_impact', 'save_assembly_grid_feature_visibility', 'save_assembly_grid_section', 'save_assembly_grid_sections', 'delete_assembly_grid_categories', 'assembly_catalog_rows', 'save_assembly_catalog_rows', 'assembly_bom_components', '_assembly_containment_edges', '_validate_assembly_containment', 'save_assembly_bom_components', 'assembly_feature_rules', 'save_assembly_feature_rules', 'assembly_model_applicability', 'assembly_images', '_assembly_image_target', '_remove_owned_upload', 'set_assembly_image', 'add_assembly_image', 'delete_assembly_images', 'assemblies_for_section', 'fishbone_assignment_assembly_impact', 'assembly_section_reference_impact', 'repoint_assembly_section_references', 'assembly_catalog_delete_impact', 'delete_assembly_catalog_rows', 'reset_manufacturing_assembly_catalog', 'manufacturing_assemblies', '_optional_nonnegative_number', '_assembly_text', 'replace_manufacturing_assemblies', 'bulk_update_assembly_policy', 'delete_manufacturing_assembly', 'work_element_material_groups', 'save_work_element_material_group', 'delete_work_element_material_group', 'material_consumption_for_scenario', 'assembly_catalog_part_applicability']
for _export_name in __domain_exports__:
    if callable(globals()[_export_name]):
        globals()[_export_name] = _db_core.domain_entrypoint(globals()[_export_name])
_db_core.register_domain_module(_sys.modules[__name__], __domain_exports__)
