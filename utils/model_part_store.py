"""Domain persistence extracted from the historical utils.store module."""

from __future__ import annotations

import sys as _sys
from utils import db_core as _db_core

globals().update({name: value for name, value in vars(_db_core).items() if not name.startswith('__')})

PART_SOURCE_CODES = ("1", "+1", "2", "2.4", "3", "4", "5", "6", "7", "8")

PART_MAKE_BUY_VALUES = ("Make", "Buy")

def project_table(
    table: str,
    project_id: str,
    order_by: str = "updated_at DESC",
    scenario_id: str | None = None,
) -> pd.DataFrame:
    allowed = {"parts", "work_elements", "concerns", "fishbone_nodes", "assembly_sections", "fishbone_part_assignments"}
    if table not in allowed:
        raise ValueError("Unsupported table")
    if table == "work_elements" and scenario_id:
        return pd.DataFrame(query(
            f"SELECT * FROM {table} WHERE project_id=? AND scenario_id=? ORDER BY {order_by}",
            (project_id, scenario_id),
        ))
    frame = pd.DataFrame(
        query(f"SELECT * FROM {table} WHERE project_id = ? ORDER BY {order_by}", (project_id,))
    )
    if table == "parts" and not frame.empty:
        links = assembly_catalog_part_applicability(project_id)
        frame["assembly_id"] = ""
        frame["assembly_number"] = ""
        if not links.empty:
            links_by_part = links.set_index(links["part_id"].astype(str))
            part_ids = frame["id"].astype(str)
            linked = part_ids.isin(links_by_part.index)
            frame.loc[linked, "assembly_id"] = part_ids[linked].map(
                links_by_part["assembly_id"]
            )
            frame.loc[linked, "assembly_number"] = part_ids[linked].map(
                links_by_part["assembly_number"]
            )
            frame.loc[linked, "model_applicability"] = part_ids[linked].map(
                links_by_part["model_applicability"]
            ).fillna("")
    return frame

def part_scenario_activity(project_id: str, scenario_id: str) -> dict[str, bool]:
    """Return explicit per-scenario part activity; missing rows default to active."""
    rows = query(
        """SELECT activity.part_id, activity.active
           FROM part_scenario_activity activity
           JOIN planning_scenarios scenario ON scenario.id=activity.scenario_id
           JOIN parts part ON part.id=activity.part_id
           WHERE activity.project_id=? AND activity.scenario_id=?
             AND scenario.project_id=? AND part.project_id=?""",
        (project_id, scenario_id, project_id, project_id),
    )
    return {str(row["part_id"]): bool(row["active"]) for row in rows}

def active_part_ids(project_id: str, scenario_id: str) -> set[str]:
    """Return project part IDs active in a scenario, defaulting new/unmapped parts to active."""
    rows = query(
        """SELECT part.id
           FROM parts part
           JOIN planning_scenarios scenario
             ON scenario.id=? AND scenario.project_id=part.project_id
           LEFT JOIN part_scenario_activity activity
             ON activity.project_id=part.project_id
            AND activity.scenario_id=scenario.id AND activity.part_id=part.id
           WHERE part.project_id=? AND COALESCE(activity.active, 1)=1""",
        (scenario_id, project_id),
    )
    return {str(row["id"]) for row in rows}

def update_part_scenario_activity(
    project_id: str, scenario_id: str, activity_by_part: dict[str, bool]
) -> str:
    """Persist scenario-specific Active flags for project parts atomically."""
    normalized_activity = {
        str(part_id): bool(active) for part_id, active in activity_by_part.items()
    }
    selected_ids = list(normalized_activity)
    timestamp = now_iso()
    with connection() as conn:
        scenario = conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone()
        if not scenario:
            raise ValueError("The active planning scenario no longer exists.")
        if selected_ids:
            placeholders = ",".join("?" for _ in selected_ids)
            valid_ids = {
                str(row[0]) for row in conn.execute(
                    f"SELECT id FROM parts WHERE project_id=? AND id IN ({placeholders})",
                    (project_id, *selected_ids),
                ).fetchall()
            }
            if valid_ids != set(selected_ids):
                raise ValueError("One or more parts no longer belong to this project.")
        for part_id in selected_ids:
            conn.execute(
                """INSERT INTO part_scenario_activity
                   (project_id, scenario_id, part_id, active, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(scenario_id, part_id) DO UPDATE SET
                     active=excluded.active, updated_at=excluded.updated_at""",
                (
                    project_id,
                    scenario_id,
                    part_id,
                    1 if normalized_activity[part_id] else 0,
                    timestamp,
                ),
            )
    return timestamp

def normalize_model_applicability(value) -> str:
    if isinstance(value, (list, tuple, set)):
        selected = [str(item).strip() for item in value if str(item).strip()]
        if not selected or "All" in selected or "All models" in selected:
            return "All"
        return ", ".join(dict.fromkeys(selected))
    text = "" if value is None or pd.isna(value) else str(value).strip()
    return text or "All"

def _clean_optional_text(value) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()

def _validated_part_catalog_fields(values) -> dict[str, str]:
    fields = {
        "technology_engineer": _clean_optional_text(values.get("technology_engineer")),
        "pits_tracker_number": _clean_optional_text(values.get("pits_tracker_number")),
        "source_code": _clean_optional_text(values.get("source_code")),
        "official_windchill_part_name": _clean_optional_text(
            values.get("official_windchill_part_name")
        ),
        "make_buy": _clean_optional_text(values.get("make_buy")),
    }
    if fields["source_code"] not in {"", *PART_SOURCE_CODES}:
        raise ValueError(
            "Source Code must be blank or an approved code: 1, +1, 2, 2.4, 3, 4, 5, 6, 7, 8."
        )
    if fields["make_buy"] not in {"", *PART_MAKE_BUY_VALUES}:
        raise ValueError("Make vs Buy must be blank, Make, or Buy.")
    return fields

def upsert_part(project_id: str, values: dict, part_id: str | None = None) -> str:
    timestamp = now_iso()
    part_id = part_id or str(uuid4())
    quantity = values.get("quantity", 1)
    quantity = None if quantity is None or pd.isna(quantity) or str(quantity).strip() == "" else float(quantity)
    catalog_fields = _validated_part_catalog_fields(values)
    if catalog_fields["pits_tracker_number"]:
        duplicate = query(
            """SELECT id FROM parts
               WHERE project_id=? AND pits_tracker_number=?
                 AND id<>? AND part_number<>?""",
            (
                project_id,
                catalog_fields["pits_tracker_number"],
                part_id,
                values["part_number"].strip(),
            ),
        )
        if duplicate:
            raise ValueError(
                "Duplicate PITS Tracker numbers are not allowed in this project: "
                f"{catalog_fields['pits_tracker_number']}"
            )
    execute(
        """INSERT INTO parts (id, project_id, part_number, description, quantity, revision, source,
           image_path, model_applicability, notes, technology_engineer, pits_tracker_number,
           source_code, official_windchill_part_name, make_buy, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(project_id, part_number) DO UPDATE SET description=excluded.description,
           quantity=excluded.quantity, revision=excluded.revision, source=excluded.source,
           model_applicability=CASE
               WHEN EXISTS (
                   SELECT 1 FROM part_feature_rules rule
                   WHERE rule.project_id=parts.project_id AND rule.part_id=parts.id
               ) THEN parts.model_applicability
               ELSE excluded.model_applicability
           END,
           notes=CASE
               WHEN TRIM(COALESCE(parts.notes, '')) <> '' THEN parts.notes
               ELSE excluded.notes
           END,
           technology_engineer=CASE WHEN excluded.technology_engineer<>'' THEN excluded.technology_engineer ELSE parts.technology_engineer END,
           pits_tracker_number=CASE WHEN excluded.pits_tracker_number<>'' THEN excluded.pits_tracker_number ELSE parts.pits_tracker_number END,
           source_code=CASE WHEN excluded.source_code<>'' THEN excluded.source_code ELSE parts.source_code END,
           official_windchill_part_name=CASE WHEN excluded.official_windchill_part_name<>'' THEN excluded.official_windchill_part_name ELSE parts.official_windchill_part_name END,
           make_buy=CASE WHEN excluded.make_buy<>'' THEN excluded.make_buy ELSE parts.make_buy END,
           updated_at=excluded.updated_at""",
        (part_id, project_id, values["part_number"].strip(), values.get("description", "").strip(),
         quantity, str(values.get("revision") or "0").strip() or "0", values.get("source", "Manual"),
         values.get("image_path", ""), normalize_model_applicability(values.get("model_applicability", "All")),
         values.get("notes", "").strip(), catalog_fields["technology_engineer"],
         catalog_fields["pits_tracker_number"], catalog_fields["source_code"],
         catalog_fields["official_windchill_part_name"], catalog_fields["make_buy"], timestamp),
    )
    rows = query("SELECT id FROM parts WHERE project_id = ? AND part_number = ?", (project_id, values["part_number"].strip()))
    return rows[0]["id"]

def update_part_rows(
    project_id: str,
    edited: pd.DataFrame,
    *,
    scenario_id: str | None = None,
    activity_by_part: dict[str, bool] | None = None,
) -> int:
    required = {"id", "part_number", "description", "quantity", "revision", "model_applicability", "notes"}
    if not required.issubset(edited.columns):
        raise ValueError("The editable parts table is missing required columns.")
    part_numbers = edited["part_number"].fillna("").astype(str).str.strip()
    if part_numbers.eq("").any():
        raise ValueError("Every part must have a part number.")
    if part_numbers.duplicated().any():
        duplicates = ", ".join(sorted(part_numbers[part_numbers.duplicated(keep=False)].unique()))
        raise ValueError(f"Duplicate part numbers are not allowed: {duplicates}")
    pits_numbers = (
        edited.get("pits_tracker_number", pd.Series("", index=edited.index))
        .fillna("")
        .astype(str)
        .str.strip()
    )
    duplicate_pits = pits_numbers.ne("") & pits_numbers.duplicated(keep=False)
    if duplicate_pits.any():
        duplicates = ", ".join(sorted(pits_numbers[duplicate_pits].unique()))
        raise ValueError(
            f"Duplicate PITS Tracker numbers are not allowed in this project: {duplicates}"
        )
    def clean_text(value) -> str:
        return "" if value is None or pd.isna(value) else str(value).strip()

    timestamp = now_iso()
    with connection() as conn:
        if scenario_id and not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        existing_parts = {
            str(existing["id"]): dict(existing)
            for existing in conn.execute(
                "SELECT * FROM parts WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        existing_ids = set(existing_parts)
        tracker_owner = {
            str(existing["pits_tracker_number"] or "").strip(): part_id
            for part_id, existing in existing_parts.items()
            if str(existing["pits_tracker_number"] or "").strip()
        }
        edited_ids = {
            str(row.get("id") or "").strip()
            for _, row in edited.iterrows()
            if row.get("id") is not None and not pd.isna(row.get("id"))
        }
        tracker_owner = {
            tracker: owner
            for tracker, owner in tracker_owner.items()
            if owner not in edited_ids
        }
        for _, row in edited.iterrows():
            tracker = clean_text(row.get("pits_tracker_number"))
            if not tracker:
                continue
            part_id = clean_text(row.get("id"))
            if tracker in tracker_owner and tracker_owner[tracker] != part_id:
                raise ValueError(
                    "Duplicate PITS Tracker numbers are not allowed in this project: "
                    f"{tracker}"
                )
            tracker_owner[tracker] = part_id
        linked_assemblies = {
            str(row["catalog_part_id"]): str(row["assembly_number"])
            for row in conn.execute(
                """SELECT catalog_part_id, assembly_number
                   FROM manufacturing_assemblies
                   WHERE project_id=? AND catalog_part_id IS NOT NULL""",
                (project_id,),
            ).fetchall()
        }
        for _, row in edited.iterrows():
            part_id = (
                str(row["id"])
                if row.get("id") is not None and not pd.isna(row.get("id")) and str(row.get("id")).strip()
                else str(uuid4())
            )
            quantity = row.get("quantity")
            quantity = None if quantity is None or pd.isna(quantity) else float(quantity)
            revision = clean_text(row.get("revision"))
            if part_id not in existing_ids and not revision:
                revision = "0"
            previous = existing_parts.get(part_id)
            part_number = str(row["part_number"]).strip()
            if (
                part_id in linked_assemblies
                and previous
                and part_number != str(previous["part_number"])
            ):
                raise ValueError(
                    f"Part number {previous['part_number']} represents assembly "
                    f"{linked_assemblies[part_id]}. Rename it through the Assembly grid."
                )
            applicability = (
                str(previous["model_applicability"] or "")
                if part_id in linked_assemblies and previous
                else normalize_model_applicability(row.get("model_applicability"))
            )
            catalog_fields = _validated_part_catalog_fields(
                {
                    field: (
                        row.get(field)
                        if field in edited.columns
                        else (previous or {}).get(field, "")
                    )
                    for field in (
                        "technology_engineer",
                        "pits_tracker_number",
                        "source_code",
                        "official_windchill_part_name",
                        "make_buy",
                    )
                }
            )
            values = (
                part_number, clean_text(row.get("description")), quantity,
                revision, applicability,
                clean_text(row.get("notes")), catalog_fields["technology_engineer"],
                catalog_fields["pits_tracker_number"], catalog_fields["source_code"],
                catalog_fields["official_windchill_part_name"],
                catalog_fields["make_buy"], timestamp,
            )
            if part_id in existing_ids:
                conn.execute(
                    """UPDATE parts SET part_number=?, description=?, quantity=?, revision=?,
                       model_applicability=?, notes=?, technology_engineer=?,
                       pits_tracker_number=?, source_code=?, official_windchill_part_name=?,
                       make_buy=?, updated_at=? WHERE id=? AND project_id=?""",
                    (*values, part_id, project_id),
                )
            else:
                conn.execute(
                    """INSERT INTO parts
                       (id, project_id, part_number, description, quantity, revision, source,
                        image_path, model_applicability, notes, technology_engineer,
                        pits_tracker_number, source_code, official_windchill_part_name,
                        make_buy, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (part_id, project_id, values[0], values[1], values[2], values[3],
                     clean_text(row.get("source")) or "Manual", *values[4:]),
                )
        if scenario_id and activity_by_part is not None:
            normalized_activity = {
                str(part_id): bool(active)
                for part_id, active in activity_by_part.items()
            }
            saved_ids = set(edited["id"].fillna("").astype(str))
            if set(normalized_activity) != saved_ids:
                raise ValueError("Part activity must be supplied for every saved row.")
            for part_id, active in normalized_activity.items():
                conn.execute(
                    """INSERT INTO part_scenario_activity
                       (project_id, scenario_id, part_id, active, updated_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(scenario_id, part_id) DO UPDATE SET
                         active=excluded.active, updated_at=excluded.updated_at""",
                    (project_id, scenario_id, part_id, 1 if active else 0, timestamp),
                )
    return len(edited)

def part_delete_impact(project_id: str, part_ids: list[str]) -> dict:
    normalized = list(dict.fromkeys(
        str(part_id).strip() for part_id in part_ids if str(part_id).strip()
    ))
    if not normalized:
        raise ValueError("Select at least one part to delete.")
    placeholders = ",".join("?" for _ in normalized)
    with connection() as conn:
        parts = conn.execute(
            f"""SELECT id, part_number FROM parts
                WHERE project_id=? AND id IN ({placeholders})
                ORDER BY part_number""",
            (project_id, *normalized),
        ).fetchall()
        if len(parts) != len(normalized):
            raise ValueError("One or more selected parts no longer exist.")
        linked = conn.execute(
            f"""SELECT catalog_part_id AS part_id, assembly_number, name AS assembly_name
                FROM manufacturing_assemblies
                WHERE project_id=? AND catalog_part_id IN ({placeholders})
                ORDER BY assembly_number""",
            (project_id, *normalized),
        ).fetchall()
        return {
            "part_ids": normalized,
            "part_numbers": [str(row["part_number"]) for row in parts],
            "linked_assemblies": [dict(row) for row in linked],
        }

def delete_project_part(project_id: str, part_id: str) -> str:
    """Delete one catalog part and its cascading fishbone uses and image records."""
    with connection() as conn:
        part = conn.execute(
            "SELECT part_number, image_path FROM parts WHERE id=? AND project_id=?",
            (part_id, project_id),
        ).fetchone()
        if not part:
            raise ValueError("That part no longer exists.")
        linked = conn.execute(
            """SELECT assembly_number FROM manufacturing_assemblies
               WHERE project_id=? AND catalog_part_id=?""",
            (project_id, part_id),
        ).fetchone()
        if linked:
            raise ValueError(
                f"Part number {part['part_number']} represents assembly "
                f"{linked['assembly_number']}. Delete or merge that assembly first."
            )
        supplemental_paths = [row[0] for row in conn.execute(
            "SELECT image_path FROM part_images WHERE part_id=?", (part_id,)
        ).fetchall()]
        conn.execute("DELETE FROM parts WHERE id=? AND project_id=?", (part_id, project_id))
    for raw_path in [part["image_path"], *supplemental_paths]:
        if raw_path:
            path = Path(raw_path)
            try:
                if path.exists() and path.is_file() and UPLOAD_DIR.resolve() in path.resolve().parents:
                    path.unlink()
            except OSError:
                pass
    return str(part["part_number"])

def set_part_image(part_id: str, uploaded_file) -> str:
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Use PNG, JPG, JPEG, or WEBP images.")
    target = UPLOAD_DIR / f"{part_id}{suffix}"
    target.write_bytes(uploaded_file.getvalue())
    execute("UPDATE parts SET image_path = ?, updated_at = ? WHERE id = ?", (str(target), now_iso(), part_id))
    return str(target)

def add_part_image(part_id: str, uploaded_file, image_type: str, caption: str) -> str:
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Use PNG, JPG, JPEG, or WEBP images.")
    image_id = str(uuid4())
    target = UPLOAD_DIR / f"{part_id}_{image_id}{suffix}"
    target.write_bytes(uploaded_file.getvalue())
    execute(
        "INSERT INTO part_images VALUES (?, ?, ?, ?, ?, ?)",
        (image_id, part_id, str(target), image_type, caption.strip(), now_iso()),
    )
    return str(target)

def part_images(part_id: str) -> list[dict]:
    return query("SELECT * FROM part_images WHERE part_id = ? ORDER BY created_at", (part_id,))

def complexity_features(project_id: str) -> pd.DataFrame:
    rows = query(
        "SELECT * FROM complexity_features WHERE project_id=? ORDER BY sequence, category, name",
        (project_id,),
    )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["allowed_choices"] = frame["allowed_values"].apply(
            lambda value: ", ".join(json.loads(value or "[]"))
        )
    return frame

def complexity_feature_delete_impacts(
    project_id: str, feature_ids: list[str]
) -> pd.DataFrame:
    """Return dependency counts used to explain a proposed feature deletion."""
    normalized_ids = list(
        dict.fromkeys(
            str(feature_id).strip()
            for feature_id in feature_ids
            if str(feature_id).strip()
        )
    )
    columns = [
        "id", "category", "name", "model_value_count", "part_rule_count",
        "affected_part_count",
    ]
    if not normalized_ids:
        return pd.DataFrame(
            {
                "id": pd.Series(dtype="string"),
                "category": pd.Series(dtype="string"),
                "name": pd.Series(dtype="string"),
                "model_value_count": pd.Series(dtype="int64"),
                "part_rule_count": pd.Series(dtype="int64"),
                "affected_part_count": pd.Series(dtype="int64"),
            }
        )
    placeholders = ", ".join("?" for _ in normalized_ids)
    return pd.DataFrame(
        query(
            f"""SELECT f.id, f.category, f.name,
                       (SELECT COUNT(*) FROM model_feature_values value
                        WHERE value.project_id=f.project_id AND value.feature_id=f.id)
                           AS model_value_count,
                       (SELECT COUNT(*) FROM part_feature_rules rule
                        WHERE rule.project_id=f.project_id AND rule.feature_id=f.id)
                           AS part_rule_count,
                       (SELECT COUNT(DISTINCT rule.part_id) FROM part_feature_rules rule
                        WHERE rule.project_id=f.project_id AND rule.feature_id=f.id)
                           AS affected_part_count
                FROM complexity_features f
                WHERE f.project_id=? AND f.id IN ({placeholders})
                ORDER BY f.sequence, f.category, f.name""",
            (project_id, *normalized_ids),
        ),
        columns=columns,
    )

def complexity_tree(project_id: str) -> pd.DataFrame:
    models = project_models(project_id)
    if models.empty:
        return pd.DataFrame(columns=["model_id", "common_name", "official_model_number"])
    result = models[["id", "display_name", "model_number"]].rename(columns={
        "id": "model_id", "display_name": "common_name", "model_number": "official_model_number",
    })
    values = query(
        "SELECT model_id, feature_id, value FROM model_feature_values WHERE project_id=?",
        (project_id,),
    )
    value_map = {(str(row["model_id"]), str(row["feature_id"])): row["value"] for row in values}
    for feature in complexity_features(project_id).to_dict("records"):
        feature_id = str(feature["id"])
        result[feature_id] = result["model_id"].astype(str).map(
            lambda model_id: value_map.get((model_id, feature_id)) or None
        )
    return result

def potential_duplicate_models(project_id: str, edited: pd.DataFrame) -> list[dict]:
    """Return active-model pairs whose mutually assigned feature values all match."""
    if "model_id" not in edited.columns:
        raise ValueError("The complexity tree is missing model identifiers.")

    features = complexity_features(project_id)
    active_features = (
        features.loc[features["active"].fillna(1).astype(bool)]
        if not features.empty
        else features
    )
    allowed_by_id = {
        str(row["id"]): {str(value) for value in json.loads(row["allowed_values"] or "[]")}
        for _, row in active_features.iterrows()
    }
    models = project_models(project_id)
    if models.empty:
        return []
    model_by_id = {str(row["id"]): row for _, row in models.iterrows()}
    active_model_ids = {
        str(row["id"])
        for _, row in models.loc[models["active"].fillna(1).astype(bool)].iterrows()
    }

    candidates: list[dict] = []
    seen_model_ids: set[str] = set()
    for _, row in edited.iterrows():
        model_id = _catalog_text(row.get("model_id"))
        if model_id not in model_by_id or model_id in seen_model_ids:
            continue
        seen_model_ids.add(model_id)
        values: dict[str, str] = {}
        for feature_id, choices in allowed_by_id.items():
            value = _catalog_text(row.get(feature_id))
            if value and value not in choices:
                raise ValueError("Choose only values defined in Feature definitions.")
            if value:
                values[feature_id] = value
        if model_id not in active_model_ids:
            continue
        model = model_by_id[model_id]
        candidates.append(
            {
                "model_id": model_id,
                "common_name": _catalog_text(model.get("display_name")),
                "official_model_number": _catalog_text(model.get("model_number")),
                "values": values,
            }
        )

    conflicts: list[dict] = []
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index + 1 :]:
            mutual_feature_ids = set(left["values"]) & set(right["values"])
            if not mutual_feature_ids:
                continue
            if all(
                left["values"][feature_id] == right["values"][feature_id]
                for feature_id in mutual_feature_ids
            ):
                conflicts.append(
                    {
                        "left_model_id": left["model_id"],
                        "left_common_name": left["common_name"],
                        "left_official_model_number": left["official_model_number"],
                        "right_model_id": right["model_id"],
                        "right_common_name": right["common_name"],
                        "right_official_model_number": right["official_model_number"],
                        "mutual_feature_count": len(mutual_feature_ids),
                    }
                )
    return conflicts

def part_feature_rules(project_id: str) -> pd.DataFrame:
    """Return saved part rules plus mapping-derived rows for linked assembly parts."""
    return pd.DataFrame(query(
        """SELECT r.part_id, r.feature_id, r.value, f.category, f.name AS feature_name
           FROM part_feature_rules r
           JOIN complexity_features f ON f.id=r.feature_id
           WHERE r.project_id=?
             AND NOT EXISTS (
                 SELECT 1 FROM manufacturing_assemblies assembly
                 WHERE assembly.project_id=r.project_id
                   AND assembly.catalog_part_id=r.part_id
             )
           UNION
           SELECT assembly.catalog_part_id AS part_id, value.feature_id, value.value,
                  f.category, f.name AS feature_name
           FROM manufacturing_assemblies assembly
           JOIN assembly_grid_model_mappings mapping
             ON mapping.project_id=assembly.project_id AND mapping.assembly_id=assembly.id
           JOIN project_models model
             ON model.id=mapping.model_id AND model.active=1
           JOIN model_feature_values value
             ON value.project_id=assembly.project_id AND value.model_id=model.id
           JOIN complexity_features f
             ON f.id=value.feature_id AND f.active=1
           WHERE assembly.project_id=? AND assembly.catalog_part_id IS NOT NULL
           ORDER BY category, feature_name, value""",
        (project_id, project_id),
    ))

def update_part_feature_rules(project_id: str, selections_by_part: dict[str, list[str]]) -> int:
    """Save feature rules and resolve them to official model numbers for downstream use."""
    features = complexity_features(project_id)
    feature_by_id = {str(row["id"]): row for _, row in features.iterrows()}
    tree = complexity_tree(project_id)
    valid_parts = {str(row["id"]) for row in query("SELECT id FROM parts WHERE project_id=?", (project_id,))}
    linked_parts = {
        str(row["part_id"]): str(row["assembly_number"])
        for row in query(
            """SELECT catalog_part_id AS part_id, assembly_number
               FROM manufacturing_assemblies
               WHERE project_id=? AND catalog_part_id IS NOT NULL""",
            (project_id,),
        )
    }
    derived_tokens: dict[str, set[str]] = {part_id: set() for part_id in linked_parts}
    for row in query(
        """SELECT assembly.catalog_part_id AS part_id, value.feature_id, value.value
           FROM manufacturing_assemblies assembly
           JOIN assembly_grid_model_mappings mapping
             ON mapping.project_id=assembly.project_id AND mapping.assembly_id=assembly.id
           JOIN project_models model ON model.id=mapping.model_id AND model.active=1
           JOIN model_feature_values value
             ON value.project_id=assembly.project_id AND value.model_id=model.id
           JOIN complexity_features feature
             ON feature.id=value.feature_id AND feature.active=1
           WHERE assembly.project_id=? AND assembly.catalog_part_id IS NOT NULL""",
        (project_id,),
    ):
        derived_tokens.setdefault(str(row["part_id"]), set()).add(
            f"{row['feature_id']}::{row['value']}"
        )
    timestamp = now_iso()
    updated = 0
    with connection() as conn:
        for part_id, raw_tokens in selections_by_part.items():
            if part_id not in valid_parts:
                continue
            tokens = [str(token).strip() for token in (raw_tokens or []) if str(token).strip()]
            if part_id in linked_parts:
                if set(tokens) != derived_tokens.get(part_id, set()):
                    raise ValueError(
                        f"Part number for assembly {linked_parts[part_id]} gets its model "
                        "applicability from the Assembly grid and cannot use Parts feature rules."
                    )
                continue
            if not tokens:
                continue  # Preserve legacy model-number applicability until the user tags it.
            if "All models" in tokens:
                conn.execute("DELETE FROM part_feature_rules WHERE project_id=? AND part_id=?", (project_id, part_id))
                conn.execute(
                    "UPDATE parts SET model_applicability='All', updated_at=? WHERE id=? AND project_id=?",
                    (timestamp, part_id, project_id),
                )
                updated += 1
                continue
            selected_by_feature: dict[str, set[str]] = {}
            for token in tokens:
                if "::" not in token:
                    raise ValueError("Choose All models or values defined in Feature definitions.")
                feature_id, value = token.split("::", 1)
                feature = feature_by_id.get(feature_id)
                allowed = json.loads(feature["allowed_values"] or "[]") if feature is not None else []
                if value not in allowed:
                    raise ValueError("A selected feature choice is no longer defined.")
                selected_by_feature.setdefault(feature_id, set()).add(value)

            matches = tree.copy()
            for feature_id, selected_values in selected_by_feature.items():
                matches = matches[matches[feature_id].isin(selected_values)]
            if matches.empty:
                raise ValueError("A feature rule matches no official models. Update the Complexity tree or the part rule.")
            model_numbers = matches["official_model_number"].dropna().astype(str).tolist()
            conn.execute("DELETE FROM part_feature_rules WHERE project_id=? AND part_id=?", (project_id, part_id))
            conn.executemany(
                """INSERT INTO part_feature_rules
                   (project_id, part_id, feature_id, value, updated_at) VALUES (?, ?, ?, ?, ?)""",
                [
                    (project_id, part_id, feature_id, value, timestamp)
                    for feature_id, values in selected_by_feature.items() for value in sorted(values)
                ],
            )
            conn.execute(
                "UPDATE parts SET model_applicability=?, updated_at=? WHERE id=? AND project_id=?",
                (normalize_model_applicability(model_numbers), timestamp, part_id, project_id),
            )
            updated += 1
    return updated

def complexity_planning_snapshot(project_id: str) -> dict:
    with connection() as conn:
        return {
            "features": [dict(row) for row in conn.execute(
                "SELECT * FROM complexity_features WHERE project_id=?", (project_id,)
            ).fetchall()],
            "values": [dict(row) for row in conn.execute(
                "SELECT * FROM model_feature_values WHERE project_id=?", (project_id,)
            ).fetchall()],
            "part_rules": [dict(row) for row in conn.execute(
                "SELECT * FROM part_feature_rules WHERE project_id=?", (project_id,)
            ).fetchall()],
            "part_applicability": [dict(row) for row in conn.execute(
                "SELECT id, model_applicability, updated_at FROM parts WHERE project_id=?", (project_id,)
            ).fetchall()],
        }

def restore_complexity_planning_snapshot(project_id: str, snapshot: dict) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM part_feature_rules WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM model_feature_values WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM complexity_features WHERE project_id=?", (project_id,))
        _insert_snapshot_rows(conn, "complexity_features", snapshot.get("features", []))
        _insert_snapshot_rows(conn, "model_feature_values", snapshot.get("values", []))
        _insert_snapshot_rows(conn, "part_feature_rules", snapshot.get("part_rules", []))
        for row in snapshot.get("part_applicability", []):
            conn.execute(
                "UPDATE parts SET model_applicability=?, updated_at=? WHERE id=? AND project_id=?",
                (row.get("model_applicability"), row.get("updated_at"), row.get("id"), project_id),
            )

def update_complexity_features(project_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "category", "name", "allowed_choices", "description", "active"}
    if not required.issubset(edited.columns):
        raise ValueError("The feature definitions table is missing required columns.")

    def clean(value) -> str:
        return "" if value is None or pd.isna(value) else str(value).strip()

    records = []
    names: list[str] = []
    for index, row in edited.reset_index(drop=True).iterrows():
        name = clean(row.get("name"))
        category = clean(row.get("category"))
        if not name and not category and not clean(row.get("allowed_choices")):
            continue
        if not category or not name:
            raise ValueError("Every feature needs both a category and a feature name.")
        choices = list(dict.fromkeys(
            choice.strip() for choice in clean(row.get("allowed_choices")).split(",") if choice.strip()
        ))
        if not choices:
            raise ValueError(f"Add at least one allowed choice for {name}.")
        names.append(name)
        records.append({
            "id": clean(row.get("id")) or str(uuid4()), "category": category, "name": name,
            "allowed_values": json.dumps(choices), "description": clean(row.get("description")),
            "active": 1 if bool(row.get("active")) else 0, "sequence": (index + 1) * 10,
        })
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("Feature names must be unique within this project.")

    timestamp = now_iso()
    with connection() as conn:
        existing_ids = {row[0] for row in conn.execute(
            "SELECT id FROM complexity_features WHERE project_id=?", (project_id,)
        )}
        retained_ids = {record["id"] for record in records}
        for feature_id in existing_ids - retained_ids:
            affected_part_ids = [row[0] for row in conn.execute(
                "SELECT DISTINCT part_id FROM part_feature_rules WHERE project_id=? AND feature_id=?",
                (project_id, feature_id),
            ).fetchall()]
            conn.execute("DELETE FROM complexity_features WHERE id=? AND project_id=?", (feature_id, project_id))
            for part_id in affected_part_ids:
                conn.execute(
                    "UPDATE parts SET model_applicability='', updated_at=? WHERE id=? AND project_id=?",
                    (timestamp, part_id, project_id),
                )
        for record in records:
            conn.execute(
                """INSERT INTO complexity_features
                   (id, project_id, category, name, allowed_values, description, sequence, active, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET category=excluded.category, name=excluded.name,
                   allowed_values=excluded.allowed_values, description=excluded.description,
                   sequence=excluded.sequence, active=excluded.active, updated_at=excluded.updated_at""",
                (record["id"], project_id, record["category"], record["name"], record["allowed_values"],
                 record["description"], record["sequence"], record["active"], timestamp),
            )
            choices = json.loads(record["allowed_values"])
            placeholders = ", ".join("?" for _ in choices)
            conn.execute(
                f"""DELETE FROM model_feature_values WHERE project_id=? AND feature_id=?
                    AND value NOT IN ({placeholders})""",
                (project_id, record["id"], *choices),
            )
            affected_part_ids = [row[0] for row in conn.execute(
                f"""SELECT DISTINCT part_id FROM part_feature_rules
                    WHERE project_id=? AND feature_id=? AND value NOT IN ({placeholders})""",
                (project_id, record["id"], *choices),
            ).fetchall()]
            conn.execute(
                f"""DELETE FROM part_feature_rules WHERE project_id=? AND feature_id=?
                    AND value NOT IN ({placeholders})""",
                (project_id, record["id"], *choices),
            )
            # Affected parts require an explicit review because their prior rule is no longer complete.
            for part_id in affected_part_ids:
                conn.execute(
                    "UPDATE parts SET model_applicability='', updated_at=? WHERE id=? AND project_id=?",
                    (timestamp, part_id, project_id),
                )
    return len(records)

def update_complexity_tree(project_id: str, edited: pd.DataFrame) -> int:
    if "model_id" not in edited.columns:
        raise ValueError("The complexity tree is missing model identifiers.")
    features = complexity_features(project_id)
    active_features = features.loc[features["active"].fillna(1).astype(bool)] if not features.empty else features
    allowed_by_id = {
        str(row["id"]): json.loads(row["allowed_values"] or "[]")
        for _, row in active_features.iterrows()
    }
    valid_models = set(project_models(project_id)["id"].astype(str))
    timestamp = now_iso()
    saved = 0
    with connection() as conn:
        for _, row in edited.iterrows():
            model_id = str(row["model_id"])
            if model_id not in valid_models:
                continue
            for feature_id, choices in allowed_by_id.items():
                value = "" if pd.isna(row.get(feature_id)) else str(row.get(feature_id) or "").strip()
                if value and value not in choices:
                    raise ValueError("Choose only values defined in Feature definitions.")
                if value:
                    conn.execute(
                        """INSERT INTO model_feature_values (project_id, model_id, feature_id, value, updated_at)
                           VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT(model_id, feature_id) DO UPDATE SET value=excluded.value,
                           updated_at=excluded.updated_at""",
                        (project_id, model_id, feature_id, value, timestamp),
                    )
                    saved += 1
                else:
                    conn.execute(
                        "DELETE FROM model_feature_values WHERE project_id=? AND model_id=? AND feature_id=?",
                        (project_id, model_id, feature_id),
                    )
        # Re-resolve every feature-tagged part when the model matrix changes.
        model_rows = conn.execute(
            "SELECT id, model_number FROM project_models WHERE project_id=?", (project_id,)
        ).fetchall()
        value_rows = conn.execute(
            "SELECT model_id, feature_id, value FROM model_feature_values WHERE project_id=?", (project_id,)
        ).fetchall()
        values_by_model = {
            str(model["id"]): {
                str(value["feature_id"]): str(value["value"])
                for value in value_rows if str(value["model_id"]) == str(model["id"])
            }
            for model in model_rows
        }
        rule_rows = conn.execute(
            "SELECT part_id, feature_id, value FROM part_feature_rules WHERE project_id=?",
            (project_id,),
        ).fetchall()
        rules_by_part: dict[str, dict[str, set[str]]] = {}
        for rule in rule_rows:
            rules_by_part.setdefault(str(rule["part_id"]), {}).setdefault(
                str(rule["feature_id"]), set()
            ).add(str(rule["value"]))
        for part_id, part_rules in rules_by_part.items():
            matching_numbers = [
                str(model["model_number"])
                for model in model_rows
                if all(values_by_model[str(model["id"])].get(feature_id) in choices
                       for feature_id, choices in part_rules.items())
            ]
            conn.execute(
                "UPDATE parts SET model_applicability=?, updated_at=? WHERE id=? AND project_id=?",
                (normalize_model_applicability(matching_numbers) if matching_numbers else "", timestamp, part_id, project_id),
            )
    return saved

def model_planning_snapshot(project_id: str) -> dict:
    """Capture model definitions and every project field affected by model renames."""
    with connection() as conn:
        return {
            "models": [dict(row) for row in conn.execute(
                "SELECT * FROM project_models WHERE project_id=?", (project_id,)
            ).fetchall()],
            "parts": [dict(row) for row in conn.execute(
                "SELECT id, model_applicability, updated_at FROM parts WHERE project_id=?", (project_id,)
            ).fetchall()],
            "work_elements": [dict(row) for row in conn.execute(
                "SELECT id, model_applicability, updated_at FROM work_elements WHERE project_id=?", (project_id,)
            ).fetchall()],
            "fishbone_nodes": [dict(row) for row in conn.execute(
                "SELECT id, applicable_models, updated_at FROM fishbone_nodes WHERE project_id=?", (project_id,)
            ).fetchall()],
            "assembly_grid_model_mappings": [dict(row) for row in conn.execute(
                "SELECT * FROM assembly_grid_model_mappings WHERE project_id=?", (project_id,)
            ).fetchall()],
        }

def _insert_snapshot_rows(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        [tuple(row.get(column) for column in columns) for row in rows],
    )

def restore_model_planning_snapshot(project_id: str, snapshot: dict) -> None:
    """Restore the last model edit along with propagated model applicability values."""
    with connection() as conn:
        conn.execute(
            "DELETE FROM assembly_grid_model_mappings WHERE project_id=?", (project_id,)
        )
        conn.execute("DELETE FROM project_models WHERE project_id=?", (project_id,))
        _insert_snapshot_rows(conn, "project_models", snapshot.get("models", []))
        _insert_snapshot_rows(
            conn,
            "assembly_grid_model_mappings",
            snapshot.get("assembly_grid_model_mappings", []),
        )
        for table, value_column in (
            ("parts", "model_applicability"),
            ("work_elements", "model_applicability"),
            ("fishbone_nodes", "applicable_models"),
        ):
            for row in snapshot.get(table, []):
                conn.execute(
                    f"UPDATE {table} SET {value_column}=?, updated_at=? WHERE id=? AND project_id=?",
                    (row.get(value_column), row.get("updated_at"), row.get("id"), project_id),
                )

def delete_project_models(project_id: str, model_ids: list[str]) -> list[str]:
    """Delete selected unreferenced models only after validating the complete selection."""
    selected_ids = list(dict.fromkeys(str(model_id) for model_id in model_ids if str(model_id)))
    if not selected_ids:
        return []
    placeholders = ",".join("?" for _ in selected_ids)
    with connection() as conn:
        models = conn.execute(
            f"""SELECT id, model_number, display_name FROM project_models
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *selected_ids),
        ).fetchall()
        if len(models) != len(selected_ids):
            raise ValueError("One or more selected models no longer exist.")
        blocked: list[str] = []
        labels: list[str] = []
        for model in models:
            model_number = str(model["model_number"])
            label = str(model["display_name"] or model_number)
            labels.append(label)
            reference_count = 0
            reference_count += conn.execute(
                """SELECT COUNT(*) FROM parts part
                   WHERE part.project_id=? AND instr(part.model_applicability, ?) > 0
                     AND NOT EXISTS (
                         SELECT 1 FROM manufacturing_assemblies assembly
                         WHERE assembly.project_id=part.project_id
                           AND assembly.catalog_part_id=part.id
                     )""",
                (project_id, model_number),
            ).fetchone()[0]
            reference_count += conn.execute(
                """SELECT COUNT(*) FROM work_elements
                   WHERE project_id=? AND instr(model_applicability, ?) > 0""",
                (project_id, model_number),
            ).fetchone()[0]
            for row in conn.execute(
                "SELECT applicable_models FROM fishbone_nodes WHERE project_id=?",
                (project_id,),
            ).fetchall():
                try:
                    assigned = json.loads(row["applicable_models"] or "[]")
                except (TypeError, json.JSONDecodeError):
                    assigned = []
                reference_count += sum(str(value) == model_number for value in assigned)
            if reference_count:
                blocked.append(label)
        if blocked:
            raise ValueError(
                f"These models are still assigned elsewhere: {', '.join(sorted(blocked))}. "
                "Remove those assignments first, or turn off Use in planning instead."
            )
        conn.execute(
            f"DELETE FROM project_models WHERE project_id=? AND id IN ({placeholders})",
            (project_id, *selected_ids),
        )
        _sync_assembly_catalog_part_applicability(conn, project_id, now_iso())
        return labels

def delete_project_model(project_id: str, model_id: str) -> str:
    """Delete one unreferenced model definition."""
    return delete_project_models(project_id, [model_id])[0]

def add_project_model(project_id: str, model_number: str, display_name: str, description: str) -> str:
    model_number = model_number.strip()
    if not model_number:
        raise ValueError("Model number is required.")
    existing = query(
        "SELECT id FROM project_models WHERE project_id = ? AND model_number = ?",
        (project_id, model_number),
    )
    timestamp = now_iso()
    if existing:
        execute(
            "UPDATE project_models SET display_name=?, description=?, active=1, updated_at=? WHERE id=?",
            (display_name.strip(), description.strip(), timestamp, existing[0]["id"]),
        )
        return existing[0]["id"]
    model_id = str(uuid4())
    execute(
        """INSERT INTO project_models
           (id, project_id, model_number, source_payload, updated_at, display_name, description, active)
           VALUES (?, ?, ?, '{}', ?, ?, ?, 1)""",
        (model_id, project_id, model_number, timestamp, display_name.strip(), description.strip()),
    )
    return model_id

def update_project_model_rows(project_id: str, edited: pd.DataFrame) -> int:
    required = {"id", "model_number", "display_name", "eau", "description", "active", "notes"}
    if not required.issubset(edited.columns):
        raise ValueError("The editable model table is missing required columns.")

    def clean_text(value) -> str:
        return "" if value is None or pd.isna(value) else str(value).strip()

    def clean_eau(value) -> float | None:
        if value is None or pd.isna(value) or str(value).strip() == "":
            return None
        try:
            numeric = float(str(value).replace(",", "").strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("EAU must be a non-negative number.") from exc
        if numeric < 0:
            raise ValueError("EAU must be a non-negative number.")
        return numeric

    model_numbers = edited["model_number"].apply(clean_text)
    if model_numbers.eq("").any():
        raise ValueError("Every model needs an official model number.")
    if model_numbers.str.casefold().duplicated().any():
        raise ValueError("Official model numbers must be unique.")

    timestamp = now_iso()
    with connection() as conn:
        existing_rows = conn.execute(
            "SELECT id, model_number FROM project_models WHERE project_id=?",
            (project_id,),
        ).fetchall()
        existing_by_id = {str(row["id"]): str(row["model_number"]) for row in existing_rows}
        proposed_by_id = {
            str(row["id"]): clean_text(row.get("model_number"))
            for _, row in edited.iterrows()
            if row.get("id") is not None and not pd.isna(row.get("id")) and str(row.get("id")).strip()
        }
        final_numbers = [proposed_by_id.get(model_id, number) for model_id, number in existing_by_id.items()]
        if len({number.casefold() for number in final_numbers}) != len(final_numbers):
            raise ValueError("Official model numbers must be unique.")
        renamed = {
            existing_by_id[model_id]: new_number
            for model_id, new_number in proposed_by_id.items()
            if model_id in existing_by_id and existing_by_id[model_id] != new_number
        }
        try:
            # Temporary values allow two official model numbers to be swapped safely.
            for model_id in proposed_by_id:
                if model_id in existing_by_id and existing_by_id[model_id] != proposed_by_id[model_id]:
                    conn.execute(
                        "UPDATE project_models SET model_number=? WHERE id=? AND project_id=?",
                        (f"__renaming__{uuid4()}", model_id, project_id),
                    )
            for _, row in edited.iterrows():
                model_id = (
                    str(row["id"])
                    if row.get("id") is not None and not pd.isna(row.get("id")) and str(row.get("id")).strip()
                    else str(uuid4())
                )
                values = (
                    clean_text(row.get("model_number")),
                    clean_text(row.get("display_name")),
                    clean_eau(row.get("eau")),
                    clean_text(row.get("description")),
                    1 if bool(row.get("active")) else 0,
                    clean_text(row.get("notes")),
                    timestamp,
                )
                if model_id in existing_by_id:
                    conn.execute(
                        """UPDATE project_models
                           SET model_number=?, display_name=?, eau=?, description=?, active=?, notes=?, updated_at=?
                           WHERE id=? AND project_id=?""",
                        (*values, model_id, project_id),
                    )
                else:
                    conn.execute(
                        """INSERT INTO project_models
                           (id, project_id, model_number, source_payload, updated_at,
                            display_name, eau, description, active, notes)
                           VALUES (?, ?, ?, '{}', ?, ?, ?, ?, ?, ?)""",
                        (
                            model_id, project_id, values[0], values[6], values[1],
                            values[2], values[3], values[4], values[5],
                        ),
                    )
            if renamed:
                def rename_csv(value) -> str:
                    tokens = [token.strip() for token in str(value or "").split(",") if token.strip()]
                    return ", ".join(renamed.get(token, token) for token in tokens)

                for table in ("parts", "work_elements"):
                    reference_rows = conn.execute(
                        f"SELECT id, model_applicability FROM {table} WHERE project_id=?",
                        (project_id,),
                    ).fetchall()
                    for reference in reference_rows:
                        updated = rename_csv(reference["model_applicability"])
                        if updated != str(reference["model_applicability"] or ""):
                            conn.execute(
                                f"UPDATE {table} SET model_applicability=?, updated_at=? WHERE id=?",
                                (updated, timestamp, reference["id"]),
                            )
                node_rows = conn.execute(
                    "SELECT id, applicable_models FROM fishbone_nodes WHERE project_id=?",
                    (project_id,),
                ).fetchall()
                for node in node_rows:
                    try:
                        assigned = json.loads(node["applicable_models"] or "[]")
                    except (TypeError, json.JSONDecodeError):
                        assigned = []
                    updated = [renamed.get(str(model), str(model)) for model in assigned]
                    if updated != assigned:
                        conn.execute(
                            "UPDATE fishbone_nodes SET applicable_models=?, updated_at=? WHERE id=?",
                            (json.dumps(updated), timestamp, node["id"]),
                        )
            _sync_assembly_catalog_part_applicability(conn, project_id, timestamp)
        except sqlite3.IntegrityError as exc:
            raise ValueError("Official model numbers must be unique.") from exc
    return len(edited)

def pits_records(project_id: str) -> pd.DataFrame:
    return pd.DataFrame(query("SELECT * FROM pits_records WHERE project_id = ? ORDER BY CAST(pits_id AS INTEGER), pits_id", (project_id,)))

def pits_revisions(project_id: str) -> pd.DataFrame:
    return pd.DataFrame(query(
        """SELECT p.pits_id, r.revision_no, r.imported_at, r.source_payload
           FROM pits_record_revisions r JOIN pits_records p ON p.id = r.record_id
           WHERE p.project_id = ? ORDER BY CAST(p.pits_id AS INTEGER), p.pits_id, r.revision_no""",
        (project_id,),
    ))

def pits_import_conflict_parts(project_id: str, records: list[dict]) -> list[dict]:
    """Return existing parts in the project catalog that were manually created or edited by collaborators."""
    part_numbers = [
        str(r.get("part_number") or "").strip()
        for r in records
        if str(r.get("part_number") or "").strip()
    ]
    if not part_numbers:
        return []
    with connection() as conn:
        placeholders = ",".join("?" for _ in part_numbers)
        rows = conn.execute(
            f"""SELECT id, part_number, description, revision, source, notes
                FROM parts
                WHERE project_id=? AND part_number IN ({placeholders})
                  AND (source <> 'PITS snapshot' OR TRIM(COALESCE(notes, '')) <> '')""",
            (project_id, *part_numbers),
        ).fetchall()
        return [dict(row) for row in rows]

def import_pits_id_snapshot(
    project_id: str,
    records: list[dict],
    models: list[dict],
    *,
    scenario_id: str | None = None,
    overwrite_manual: bool = False,
) -> dict[str, int]:
    timestamp = now_iso()
    summary = {"new": 0, "changed": 0, "unchanged": 0, "models": 0}
    with connection() as conn:
        project_exists = conn.execute(
            "SELECT 1 FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
        if not project_exists:
            raise ValueError("The selected project no longer exists.")
        if scenario_id and not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM fishbone_nodes WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
        for record in records:
            pits_id = str(record["pits_id"]).strip()
            part_number = str(record.get("part_number") or "").strip()
            description = str(record.get("description") or "").strip()
            notes = str(record.get("comments") or "").strip()
            used_in_bom = str(record.get("used_bom") or "").strip().casefold() not in {"n", "no"}
            if part_number:
                if overwrite_manual:
                    update_clause = """ON CONFLICT(project_id, part_number) DO UPDATE SET
                       description=excluded.description, quantity=excluded.quantity,
                       revision=excluded.revision, source_code=excluded.source_code,
                       source=excluded.source,
                       notes=CASE
                           WHEN TRIM(COALESCE(parts.notes, '')) <> '' THEN parts.notes
                           ELSE excluded.notes
                       END,
                       model_applicability=CASE
                           WHEN EXISTS (
                               SELECT 1 FROM part_feature_rules rule
                               WHERE rule.project_id=parts.project_id AND rule.part_id=parts.id
                           ) THEN parts.model_applicability
                           ELSE excluded.model_applicability
                       END,
                       updated_at=excluded.updated_at"""
                else:
                    update_clause = """ON CONFLICT(project_id, part_number) DO UPDATE SET
                       description=CASE WHEN parts.source='PITS snapshot' THEN excluded.description ELSE parts.description END,
                       quantity=CASE WHEN parts.source='PITS snapshot' THEN excluded.quantity ELSE parts.quantity END,
                       revision=CASE WHEN parts.source='PITS snapshot' THEN excluded.revision ELSE parts.revision END,
                       source_code=CASE WHEN parts.source='PITS snapshot' THEN excluded.source_code ELSE parts.source_code END,
                       notes=CASE
                           WHEN TRIM(COALESCE(parts.notes, '')) <> '' THEN parts.notes
                           ELSE excluded.notes
                       END,
                       model_applicability=CASE
                           WHEN EXISTS (
                               SELECT 1 FROM part_feature_rules rule
                               WHERE rule.project_id=parts.project_id AND rule.part_id=parts.id
                           ) THEN parts.model_applicability
                           ELSE excluded.model_applicability
                       END,
                       updated_at=CASE WHEN parts.source='PITS snapshot' THEN excluded.updated_at ELSE parts.updated_at END"""
                conn.execute(
                    f"""INSERT INTO parts
                       (id, project_id, part_number, description, quantity, revision, source,
                        image_path, model_applicability, notes, source_code, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)
                       {update_clause}""",
                    (
                        str(uuid4()), project_id, part_number, description,
                        record.get("quantity") if record.get("quantity") is not None else 1,
                        str(record.get("revision") or "").strip(),
                        "PITS snapshot", "All", notes,
                        str(record.get("source_code") or "").strip(), timestamp,
                    ),
                )
                if scenario_id:
                    part_row = conn.execute(
                        "SELECT id FROM parts WHERE project_id=? AND part_number=?",
                        (project_id, part_number),
                    ).fetchone()
                    conn.execute(
                        """INSERT INTO part_scenario_activity
                           (project_id, scenario_id, part_id, active, updated_at)
                           VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT(scenario_id, part_id) DO UPDATE SET
                           active=excluded.active, updated_at=excluded.updated_at""",
                        (project_id, scenario_id, part_row["id"], 1 if used_in_bom else 0, timestamp),
                    )
            payload = json.dumps(record["source_payload"], sort_keys=True, ensure_ascii=False, default=str)
            source_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            existing = conn.execute(
                "SELECT * FROM pits_records WHERE project_id = ? AND pits_id = ?", (project_id, pits_id)
            ).fetchone()
            if existing is None:
                record_id = str(uuid4())
                revision = 1
                conn.execute(
                    """INSERT INTO pits_records
                    (id, project_id, pits_id, part_number, description, used_bom, status, subsystem,
                     design_maturity, comments, workstation, source_payload, source_hash, revision_no,
                     first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (record_id, project_id, pits_id, record["part_number"], record["description"], record["used_bom"],
                     record["status"], record["subsystem"], record["design_maturity"], record["comments"],
                     record["workstation"], payload, source_hash, revision, timestamp, timestamp),
                )
                conn.execute(
                    "INSERT INTO pits_record_revisions VALUES (?, ?, ?, ?, ?)",
                    (str(uuid4()), record_id, revision, payload, timestamp),
                )
                next_sequence += 1
                conn.execute(
                    """INSERT INTO fishbone_nodes
                    (id, project_id, source_row, sequence, parent_id, depth, part_number, description, quantity,
                     branch_name, subsystem, model_feature, comments, tracker_status, planned_area, source,
                     raw_levels, review_status, updated_at, pits_id, applicable_models, source_changed)
                    VALUES (?, ?, ?, ?, NULL, 1, ?, ?, NULL, '', ?, '', ?, ?, ?, 'PITS tracker', ?, 'Needs review', ?, ?, '[]', 0)""",
                    (str(uuid4()), project_id, record["source_row"], next_sequence, record["part_number"],
                     record["description"], record["subsystem"], record["comments"], record["status"],
                     record["workstation"], payload, timestamp, pits_id),
                )
                summary["new"] += 1
            elif existing["source_hash"] != source_hash:
                revision = int(existing["revision_no"]) + 1
                conn.execute(
                    """UPDATE pits_records SET part_number=?, description=?, used_bom=?, status=?, subsystem=?,
                       design_maturity=?, comments=?, workstation=?, source_payload=?, source_hash=?, revision_no=?,
                       last_seen_at=? WHERE id=?""",
                    (record["part_number"], record["description"], record["used_bom"], record["status"],
                     record["subsystem"], record["design_maturity"], record["comments"], record["workstation"],
                     payload, source_hash, revision, timestamp, existing["id"]),
                )
                conn.execute(
                    "INSERT INTO pits_record_revisions VALUES (?, ?, ?, ?, ?)",
                    (str(uuid4()), existing["id"], revision, payload, timestamp),
                )
                conn.execute(
                    "UPDATE fishbone_nodes SET source_changed=1, updated_at=? WHERE project_id=? AND pits_id=?",
                    (timestamp, project_id, pits_id),
                )
                summary["changed"] += 1
            else:
                conn.execute("UPDATE pits_records SET last_seen_at=? WHERE id=?", (timestamp, existing["id"]))
                summary["unchanged"] += 1

        for model in models:
            payload = json.dumps(model["source_payload"], sort_keys=True, ensure_ascii=False, default=str)
            existing = conn.execute(
                "SELECT id FROM project_models WHERE project_id=? AND model_number=?",
                (project_id, model["model_number"]),
            ).fetchone()
            model_id = existing["id"] if existing else str(uuid4())
            conn.execute(
                """INSERT INTO project_models
                (id, project_id, model_number, item, platform_size, package_type, appearance, base_model,
                 eau, dg_date, dc_date, pre_pilot_date, pilot_date, production_date, sku_upc,
                 evaluate_fishbone, yamazumi, bop_l1, source_payload, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, model_number) DO UPDATE SET item=excluded.item,
                 platform_size=excluded.platform_size, package_type=excluded.package_type,
                 appearance=excluded.appearance, base_model=excluded.base_model, eau=excluded.eau,
                 dg_date=excluded.dg_date, dc_date=excluded.dc_date, pre_pilot_date=excluded.pre_pilot_date,
                 pilot_date=excluded.pilot_date, production_date=excluded.production_date,
                 sku_upc=excluded.sku_upc, evaluate_fishbone=excluded.evaluate_fishbone,
                 yamazumi=excluded.yamazumi, bop_l1=excluded.bop_l1,
                 source_payload=excluded.source_payload, updated_at=excluded.updated_at""",
                (model_id, project_id, model["model_number"], model["item"], model["platform_size"],
                 model["package_type"], model["appearance"], model["base_model"], model["eau"],
                 model["dg_date"], model["dc_date"], model["pre_pilot_date"], model["pilot_date"],
                 model["production_date"], model["sku_upc"], model["evaluate_fishbone"],
                 model["yamazumi"], model["bop_l1"], payload, timestamp),
            )
            summary["models"] += 1
    return summary

def apply_pits_updates(project_id: str, pits_ids: list[str]) -> int:
    if not pits_ids:
        return 0
    placeholders = ",".join("?" for _ in pits_ids)
    timestamp = now_iso()
    with connection() as conn:
        cursor = conn.execute(
            f"""UPDATE fishbone_nodes
                SET part_number=(SELECT part_number FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    description=(SELECT description FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    subsystem=(SELECT subsystem FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    comments=(SELECT comments FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    planned_area=(SELECT workstation FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    raw_levels=(SELECT source_payload FROM pits_records p WHERE p.project_id=fishbone_nodes.project_id AND p.pits_id=fishbone_nodes.pits_id),
                    source_changed=0, review_status='Needs review', updated_at=?
                WHERE project_id=? AND pits_id IN ({placeholders})""",
            (timestamp, project_id, *pits_ids),
        )
        return cursor.rowcount

def set_mbom_review_status(project_id: str, node_ids: list[str], status: str) -> int:
    allowed = {"Needs review", "Confirmed", "Excluded"}
    if status not in allowed:
        raise ValueError("Unsupported MBOM review status")
    if not node_ids:
        return 0
    placeholders = ",".join("?" for _ in node_ids)
    with connection() as conn:
        cursor = conn.execute(
            f"UPDATE fishbone_nodes SET review_status=?, updated_at=? WHERE project_id=? AND id IN ({placeholders})",
            (status, now_iso(), project_id, *node_ids),
        )
        return cursor.rowcount

def sync_confirmed_mbom_parts(project_id: str) -> int:
    confirmed = query(
        """SELECT part_number, MAX(description) AS description, MAX(quantity) AS quantity,
                  MAX(applicable_models) AS applicable_models, MAX(comments) AS comments
           FROM fishbone_nodes
           WHERE project_id = ? AND review_status = 'Confirmed' AND TRIM(part_number) <> ''
           GROUP BY part_number""",
        (project_id,),
    )
    for row in confirmed:
        try:
            assigned_models = json.loads(row["applicable_models"] or "[]")
        except (TypeError, json.JSONDecodeError):
            assigned_models = []
        upsert_part(
            project_id,
            {
                "part_number": row["part_number"],
                "description": row["description"] or "",
                "quantity": row["quantity"],
                "source": "Confirmed MBOM",
                "model_applicability": ", ".join(assigned_models) if assigned_models else "All",
                "notes": row["comments"] or "",
            },
        )
    return len(confirmed)

__domain_exports__ = ['PART_SOURCE_CODES', 'PART_MAKE_BUY_VALUES', 'project_table', 'part_scenario_activity', 'active_part_ids', 'update_part_scenario_activity', 'normalize_model_applicability', '_clean_optional_text', '_validated_part_catalog_fields', 'upsert_part', 'update_part_rows', 'part_delete_impact', 'delete_project_part', 'set_part_image', 'add_part_image', 'part_images', 'complexity_features', 'complexity_feature_delete_impacts', 'complexity_tree', 'potential_duplicate_models', 'part_feature_rules', 'update_part_feature_rules', 'complexity_planning_snapshot', 'restore_complexity_planning_snapshot', 'update_complexity_features', 'update_complexity_tree', 'model_planning_snapshot', '_insert_snapshot_rows', 'restore_model_planning_snapshot', 'delete_project_models', 'delete_project_model', 'add_project_model', 'update_project_model_rows', 'pits_records', 'pits_revisions', 'pits_import_conflict_parts', 'import_pits_id_snapshot', 'apply_pits_updates', 'set_mbom_review_status', 'sync_confirmed_mbom_parts']
for _export_name in __domain_exports__:
    if callable(globals()[_export_name]):
        globals()[_export_name] = _db_core.domain_entrypoint(globals()[_export_name])
_db_core.register_domain_module(_sys.modules[__name__], __domain_exports__)
