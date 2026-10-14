"""Domain persistence extracted from the historical utils.store module."""

from __future__ import annotations
import re
from typing import Any

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
        pits_catalog_evidence = query(
            """SELECT pits_id, subsystem,
                      COALESCE(
                          NULLIF(TRIM(json_extract(source_payload, '$.part_code')), ''),
                          NULLIF(TRIM(json_extract(source_payload, '$.partspartcode')), ''),
                          ''
                      ) AS part_code
               FROM pits_records WHERE project_id=?""",
            (project_id,),
        )
        subsystem_by_pits_id = {
            str(row["pits_id"]): str(row["subsystem"] or "").strip()
            for row in pits_catalog_evidence
        }
        part_code_by_pits_id = {
            str(row["pits_id"]): str(row["part_code"] or "").strip()
            for row in pits_catalog_evidence
        }
        derived_subsystem = (
            frame["pits_tracker_number"]
            .fillna("")
            .astype(str)
            .map(subsystem_by_pits_id)
            .fillna("")
        )
        existing_subsystem = frame["subsystem"].fillna("").astype(str) if "subsystem" in frame.columns else ""
        frame["subsystem"] = derived_subsystem.where(derived_subsystem != "", existing_subsystem)

        derived_part_code = (
            frame["pits_tracker_number"]
            .fillna("")
            .astype(str)
            .map(part_code_by_pits_id)
            .fillna("")
        )
        existing_part_code = frame["part_code"].fillna("").astype(str) if "part_code" in frame.columns else ""
        frame["part_code"] = derived_part_code.where(derived_part_code != "", existing_part_code)
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


def _validated_part_catalog_fields(values, previous: dict | None = None) -> dict[str, str]:
    prev = previous or {}
    prev_de = _clean_optional_text(prev.get("design_engineer") or prev.get("technology_engineer"))
    prev_fn = _clean_optional_text(prev.get("factory_nickname") or prev.get("official_windchill_part_name"))
    prev_dm = _clean_optional_text(prev.get("design_maturity") or prev.get("revision"))

    raw_de = _clean_optional_text(values.get("design_engineer"))
    raw_te = _clean_optional_text(values.get("technology_engineer"))
    if "design_engineer" in values and "technology_engineer" in values:
        if raw_de != prev_de and raw_te == prev_de:
            design_eng = raw_de
        elif raw_te != prev_de and raw_de == prev_de:
            design_eng = raw_te
        else:
            design_eng = raw_de or raw_te
    elif "design_engineer" in values:
        design_eng = raw_de
    elif "technology_engineer" in values:
        design_eng = raw_te
    else:
        design_eng = raw_de or raw_te

    raw_fn = _clean_optional_text(values.get("factory_nickname"))
    raw_wn = _clean_optional_text(values.get("official_windchill_part_name"))
    if "factory_nickname" in values and "official_windchill_part_name" in values:
        if raw_fn != prev_fn and raw_wn == prev_fn:
            fac_nickname = raw_fn
        elif raw_wn != prev_fn and raw_fn == prev_fn:
            fac_nickname = raw_wn
        else:
            fac_nickname = raw_fn or raw_wn
    elif "factory_nickname" in values:
        fac_nickname = raw_fn
    elif "official_windchill_part_name" in values:
        fac_nickname = raw_wn
    else:
        fac_nickname = raw_fn or raw_wn

    raw_dm = _clean_optional_text(values.get("design_maturity"))
    raw_rev = _clean_optional_text(values.get("revision"))
    if "design_maturity" in values and "revision" in values:
        if raw_dm != prev_dm and raw_rev == prev_dm:
            design_mat = raw_dm
        elif raw_rev != prev_dm and raw_dm == prev_dm:
            design_mat = raw_rev
        else:
            design_mat = raw_dm or raw_rev
    elif "design_maturity" in values:
        design_mat = raw_dm
    elif "revision" in values:
        design_mat = raw_rev
    else:
        design_mat = raw_dm or raw_rev

    fields = {
        "design_engineer": design_eng,
        "technology_engineer": design_eng,
        "pits_tracker_number": _clean_optional_text(values.get("pits_tracker_number")),
        "source_code": _clean_optional_text(values.get("source_code")),
        "factory_nickname": fac_nickname,
        "official_windchill_part_name": fac_nickname,
        "make_buy": _clean_optional_text(values.get("make_buy")),
        "ppm": _clean_optional_text(values.get("ppm")),
        "buyer_gcl": _clean_optional_text(values.get("buyer_gcl")),
        "pmqe_aqe": _clean_optional_text(values.get("pmqe_aqe")),
        "ame_tooling_engineer": _clean_optional_text(values.get("ame_tooling_engineer")),
        "part_code": _clean_optional_text(values.get("part_code")),
        "subsystem": _clean_optional_text(values.get("subsystem")),
        "design_maturity": design_mat,
        "revision": design_mat,
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
    previous = None
    if (
        ("design_engineer" in values and "technology_engineer" in values and values.get("design_engineer") != values.get("technology_engineer"))
        or ("factory_nickname" in values and "official_windchill_part_name" in values and values.get("factory_nickname") != values.get("official_windchill_part_name"))
        or ("design_maturity" in values and "revision" in values and values.get("design_maturity") != values.get("revision"))
    ):
        prev_rows = query("SELECT * FROM parts WHERE project_id=? AND (id=? OR part_number=?)", (project_id, part_id, str(values.get("part_number") or "")))
        previous = prev_rows[0] if prev_rows else None
    catalog_fields = _validated_part_catalog_fields(values, previous=previous)
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
                "Duplicate PITS IDs are not allowed in this project: "
                f"{catalog_fields['pits_tracker_number']}"
            )
    execute(
        """INSERT INTO parts (id, project_id, part_number, description, quantity, revision,
           design_maturity, subsystem, source, image_path, model_applicability, notes,
           technology_engineer, design_engineer, pits_tracker_number, source_code,
           official_windchill_part_name, factory_nickname, make_buy, ppm, buyer_gcl,
           pmqe_aqe, ame_tooling_engineer, part_code, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(project_id, part_number) DO UPDATE SET description=excluded.description,
           quantity=excluded.quantity, revision=excluded.revision, design_maturity=excluded.design_maturity,
           subsystem=CASE WHEN excluded.subsystem<>'' THEN excluded.subsystem ELSE parts.subsystem END,
           source=excluded.source,
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
           design_engineer=CASE WHEN excluded.design_engineer<>'' THEN excluded.design_engineer ELSE parts.design_engineer END,
           pits_tracker_number=CASE WHEN excluded.pits_tracker_number<>'' THEN excluded.pits_tracker_number ELSE parts.pits_tracker_number END,
           source_code=CASE WHEN excluded.source_code<>'' THEN excluded.source_code ELSE parts.source_code END,
           official_windchill_part_name=CASE WHEN excluded.official_windchill_part_name<>'' THEN excluded.official_windchill_part_name ELSE parts.official_windchill_part_name END,
           factory_nickname=CASE WHEN excluded.factory_nickname<>'' THEN excluded.factory_nickname ELSE parts.factory_nickname END,
           make_buy=CASE WHEN excluded.make_buy<>'' THEN excluded.make_buy ELSE parts.make_buy END,
           ppm=CASE WHEN excluded.ppm<>'' THEN excluded.ppm ELSE parts.ppm END,
           buyer_gcl=CASE WHEN excluded.buyer_gcl<>'' THEN excluded.buyer_gcl ELSE parts.buyer_gcl END,
           pmqe_aqe=CASE WHEN excluded.pmqe_aqe<>'' THEN excluded.pmqe_aqe ELSE parts.pmqe_aqe END,
           ame_tooling_engineer=CASE WHEN excluded.ame_tooling_engineer<>'' THEN excluded.ame_tooling_engineer ELSE parts.ame_tooling_engineer END,
           part_code=CASE WHEN excluded.part_code<>'' THEN excluded.part_code ELSE parts.part_code END,
           updated_at=excluded.updated_at""",
        (part_id, project_id, values["part_number"].strip(), values.get("description", "").strip(),
         quantity, catalog_fields["revision"] or "0", catalog_fields["design_maturity"],
         catalog_fields["subsystem"], values.get("source", "Manual"),
         values.get("image_path", ""), normalize_model_applicability(values.get("model_applicability", "All")),
         values.get("notes", "").strip(), catalog_fields["technology_engineer"],
         catalog_fields["design_engineer"], catalog_fields["pits_tracker_number"], catalog_fields["source_code"],
         catalog_fields["official_windchill_part_name"], catalog_fields["factory_nickname"], catalog_fields["make_buy"],
         catalog_fields["ppm"], catalog_fields["buyer_gcl"], catalog_fields["pmqe_aqe"],
         catalog_fields["ame_tooling_engineer"], catalog_fields["part_code"], timestamp),
    )
    rows = query("SELECT id FROM parts WHERE project_id = ? AND part_number = ?", (project_id, values["part_number"].strip()))
    return rows[0]["id"]

def update_part_rows(
    project_id: str,
    edited: pd.DataFrame,
    *,
    scenario_id: str | None = None,
    activity_by_part: dict[str, bool] | None = None,
    _conn: sqlite3.Connection | None = None,
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
            f"Duplicate PITS IDs are not allowed in this project: {duplicates}"
        )
    def clean_text(value) -> str:
        return "" if value is None or pd.isna(value) else str(value).strip()

    timestamp = now_iso()
    context = nullcontext(_conn) if _conn is not None else connection()
    with context as conn:
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
                    "Duplicate PITS IDs are not allowed in this project: "
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
                        "design_engineer",
                        "pits_tracker_number",
                        "source_code",
                        "official_windchill_part_name",
                        "factory_nickname",
                        "make_buy",
                        "ppm",
                        "buyer_gcl",
                        "pmqe_aqe",
                        "ame_tooling_engineer",
                        "part_code",
                        "subsystem",
                        "design_maturity",
                        "revision",
                    )
                },
                previous=previous,
            )
            revision = catalog_fields["revision"]
            if part_id not in existing_ids and not revision:
                revision = "0"
            design_maturity = catalog_fields["design_maturity"]
            subsystem = catalog_fields["subsystem"]
            values = (
                part_number, clean_text(row.get("description")), quantity,
                revision, design_maturity, subsystem, applicability,
                clean_text(row.get("notes")), catalog_fields["technology_engineer"],
                catalog_fields["design_engineer"],
                catalog_fields["pits_tracker_number"], catalog_fields["source_code"],
                catalog_fields["official_windchill_part_name"],
                catalog_fields["factory_nickname"],
                catalog_fields["make_buy"],
                catalog_fields["ppm"],
                catalog_fields["buyer_gcl"],
                catalog_fields["pmqe_aqe"],
                catalog_fields["ame_tooling_engineer"],
                catalog_fields["part_code"],
                timestamp,
            )
            if part_id in existing_ids:
                conn.execute(
                    """UPDATE parts SET part_number=?, description=?, quantity=?, revision=?,
                       design_maturity=?, subsystem=?,
                       model_applicability=?, notes=?, technology_engineer=?, design_engineer=?,
                       pits_tracker_number=?, source_code=?, official_windchill_part_name=?,
                       factory_nickname=?, make_buy=?, ppm=?, buyer_gcl=?, pmqe_aqe=?,
                       ame_tooling_engineer=?, part_code=?, updated_at=? WHERE id=? AND project_id=?""",
                    (*values, part_id, project_id),
                )
            else:
                conn.execute(
                    """INSERT INTO parts
                       (id, project_id, part_number, description, quantity, revision,
                        design_maturity, subsystem, source,
                        image_path, model_applicability, notes, technology_engineer, design_engineer,
                        pits_tracker_number, source_code, official_windchill_part_name,
                        factory_nickname, make_buy, ppm, buyer_gcl, pmqe_aqe, ame_tooling_engineer,
                        part_code, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (part_id, project_id, values[0], values[1], values[2], values[3],
                     values[4], values[5],
                     clean_text(row.get("source")) or "Manual", *values[6:]),
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

def set_part_image_url(part_id: str, url: str) -> str:
    clean_url = str(url or "").strip()
    if not clean_url.startswith(("http://", "https://")):
        raise ValueError("Web link URL must start with http:// or https://")
    execute("UPDATE parts SET image_path = ?, updated_at = ? WHERE id = ?", (clean_url, now_iso(), part_id))
    return clean_url

def clear_part_image(part_id: str) -> None:
    rows = query("SELECT image_path FROM parts WHERE id=?", (part_id,))
    if rows and rows[0]["image_path"]:
        raw_path = str(rows[0]["image_path"])
        if not raw_path.startswith(("http://", "https://")):
            p = Path(raw_path)
            try:
                if p.is_file() and UPLOAD_DIR.resolve() in p.resolve().parents:
                    p.unlink(missing_ok=True)
            except OSError:
                pass
    execute("UPDATE parts SET image_path = '', updated_at = ? WHERE id = ?", (now_iso(), part_id))

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

def add_part_image_url(part_id: str, url: str, image_type: str, caption: str) -> str:
    clean_url = str(url or "").strip()
    if not clean_url.startswith(("http://", "https://")):
        raise ValueError("Web link URL must start with http:// or https://")
    image_id = str(uuid4())
    execute(
        "INSERT INTO part_images VALUES (?, ?, ?, ?, ?, ?)",
        (image_id, part_id, clean_url, image_type, caption.strip(), now_iso()),
    )
    return image_id

def delete_part_image(image_id: str) -> None:
    rows = query("SELECT image_path FROM part_images WHERE id=?", (image_id,))
    if rows and rows[0]["image_path"]:
        raw_path = str(rows[0]["image_path"])
        if not raw_path.startswith(("http://", "https://")):
            p = Path(raw_path)
            try:
                if p.is_file() and UPLOAD_DIR.resolve() in p.resolve().parents:
                    p.unlink(missing_ok=True)
            except OSError:
                pass
    execute("DELETE FROM part_images WHERE id=?", (image_id,))

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

def update_part_feature_rules(
    project_id: str,
    selections_by_part: dict[str, list[str]],
    *,
    _conn: sqlite3.Connection | None = None,
) -> int:
    """Save feature rules and resolve them to official model numbers for downstream use."""
    features = complexity_features(project_id)
    feature_by_id = {str(row["id"]): row for _, row in features.iterrows()}
    tree = complexity_tree(project_id)
    read_rows = (
        lambda sql, params=(): [dict(row) for row in _conn.execute(sql, params).fetchall()]
        if _conn is not None
        else query(sql, params)
    )
    valid_parts = {
        str(row["id"])
        for row in read_rows("SELECT id FROM parts WHERE project_id=?", (project_id,))
    }
    linked_parts = {
        str(row["part_id"]): str(row["assembly_number"])
        for row in read_rows(
            """SELECT catalog_part_id AS part_id, assembly_number
               FROM manufacturing_assemblies
               WHERE project_id=? AND catalog_part_id IS NOT NULL""",
            (project_id,),
        )
    }
    derived_tokens: dict[str, set[str]] = {part_id: set() for part_id in linked_parts}
    for row in read_rows(
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
    context = nullcontext(_conn) if _conn is not None else connection()
    with context as conn:
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

_INFERENCE_SUBWORDS = (
    "back", "plate", "wire", "harness", "light", "panel", "board", "switch",
    "valve", "motor", "door", "drum", "gas", "electric", "steam", "fascia",
    "housing", "knob", "heater", "control",
)


def _tokenize_part_text(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
    tokens = set(words)
    for w in words:
        if len(w) > 4:
            for sub in _INFERENCE_SUBWORDS:
                if sub in w and sub != w:
                    tokens.add(sub)
    return tokens


def infer_part_feature_rules(
    project_id: str,
    part_ids: list[str] | None = None,
    *,
    _conn: sqlite3.Connection | None = None,
) -> dict[str, list[str]]:
    """Infer feature applicability tokens for project parts based on Complexity Tree assignments.

    Evaluates model occurrences in the BOM and project model configuration against the
    Complexity Tree matrix and returns a mapping of {part_id: [rule_token, ...]}, where each
    token is formatted as '<feature_id>::<value>' or 'All models'.
    """
    read_rows = (
        lambda sql, params=(): [dict(row) for row in _conn.execute(sql, params).fetchall()]
        if _conn is not None
        else query(sql, params)
    )

    model_rows = read_rows(
        "SELECT id, model_number, active FROM project_models WHERE project_id=?",
        (project_id,),
    )
    if not model_rows:
        return {}
    active_models = {
        str(row["model_number"]).strip()
        for row in model_rows
        if bool(row.get("active", 1)) and str(row.get("model_number") or "").strip()
    }
    if not active_models:
        return {}

    feature_rows = read_rows(
        "SELECT id, name, category, allowed_values, active FROM complexity_features WHERE project_id=?",
        (project_id,),
    )
    active_features_by_id = {
        str(row["id"]): row
        for row in feature_rows
        if bool(row.get("active", 1))
    }
    if not active_features_by_id:
        return {}

    val_rows = read_rows(
        """SELECT v.feature_id, v.value, m.model_number
           FROM model_feature_values v
           JOIN project_models m ON m.id = v.model_id
           WHERE v.project_id=? AND m.active=1""",
        (project_id,),
    )

    feature_choice_models: dict[tuple[str, str], set[str]] = {}
    configured_tree_models: set[str] = set()
    for row in val_rows:
        fid = str(row["feature_id"])
        val = str(row["value"] or "").strip()
        model_num = str(row["model_number"] or "").strip()
        if fid in active_features_by_id and val and model_num in active_models:
            feature_choice_models.setdefault((fid, val), set()).add(model_num)
            configured_tree_models.add(model_num)

    if not configured_tree_models:
        return {}

    sql_parts = "SELECT id, part_number, description, model_applicability, pits_tracker_number FROM parts WHERE project_id=?"
    params_parts: list[Any] = [project_id]
    if part_ids is not None:
        if not part_ids:
            return {}
        placeholders = ",".join("?" for _ in part_ids)
        sql_parts += f" AND id IN ({placeholders})"
        params_parts.extend(part_ids)
    part_rows = read_rows(sql_parts, tuple(params_parts))
    if not part_rows:
        return {}

    part_by_id = {str(row["id"]): row for row in part_rows}
    part_by_tracker = {
        str(row["pits_tracker_number"]).strip(): row
        for row in part_rows
        if str(row.get("pits_tracker_number") or "").strip()
    }

    bom_rows = read_rows(
        """SELECT child_part_id, child_tracker_number, raw_levels_json
           FROM pits_bom_occurrences WHERE project_id=?""",
        (project_id,),
    )
    part_models: dict[str, set[str]] = {}
    for b in bom_rows:
        cid = str(b.get("child_part_id") or "").strip()
        ctracker = str(b.get("child_tracker_number") or "").strip()
        p = part_by_id.get(cid) or part_by_tracker.get(ctracker)
        if not p:
            continue
        pid = str(p["id"])
        try:
            levels = json.loads(b["raw_levels_json"] or "{}")
            usages = levels.get("model_usages") or {}
            if isinstance(usages, dict):
                part_models.setdefault(pid, set()).update(
                    str(m).strip() for m in usages if str(m).strip()
                )
        except Exception:
            pass

    for p in part_rows:
        pid = str(p["id"])
        if pid not in part_models:
            app_text = str(p.get("model_applicability") or "").strip()
            if app_text and app_text.lower() != "all":
                mods = {m.strip() for m in app_text.split(",") if m.strip()}
                if mods:
                    part_models[pid] = mods

    inferred: dict[str, list[str]] = {}
    for p in part_rows:
        pid = str(p["id"])
        raw_models = part_models.get(pid, set())
        p_models = raw_models & configured_tree_models

        if not p_models:
            if str(p.get("model_applicability") or "").strip().lower() == "all":
                inferred[pid] = ["All models"]
            continue

        if p_models >= configured_tree_models or len(raw_models) >= len(configured_tree_models):
            inferred[pid] = ["All models"]
            continue

        desc = str(p.get("description") or "")
        part_num = str(p.get("part_number") or "")
        p_tokens = _tokenize_part_text(desc) | _tokenize_part_text(part_num)

        candidates: list[dict[str, Any]] = []
        for (fid, val), c_models in feature_choice_models.items():
            if not c_models:
                continue
            if val.strip().upper() in ("N/A", "NONE"):
                continue
            if not (p_models <= c_models):
                continue

            feat = active_features_by_id[fid]
            allowed = json.loads(feat.get("allowed_values") or "[]")
            conflicts = False
            for other_val in allowed:
                if other_val != val:
                    other_models = feature_choice_models.get((fid, other_val), set())
                    if p_models & other_models:
                        conflicts = True
                        break
            if conflicts:
                continue

            f_name = str(feat.get("name") or "")
            f_cat = str(feat.get("category") or "")
            f_tokens = _tokenize_part_text(f_name) | _tokenize_part_text(f_cat) | _tokenize_part_text(val)
            overlap = len(p_tokens & f_tokens)

            exact_match = 1.0 if p_models == c_models else 0.0
            coverage = len(p_models) / len(c_models) if c_models else 0.0
            specificity = 1.0 / len(c_models) if c_models else 0.0

            score = (overlap * 100.0) + (exact_match * 50.0) + (coverage * 20.0) + specificity
            candidates.append({
                "score": score,
                "feature_id": fid,
                "value": val,
                "overlap": overlap,
                "exact_match": exact_match,
                "category": f_cat,
                "name": f_name,
            })

        if not candidates:
            continue

        candidates.sort(key=lambda c: c["score"], reverse=True)

        features_seen: set[str] = set()
        chosen_tokens: list[str] = []

        top = candidates[0]
        chosen_tokens.append(f"{top['feature_id']}::{top['value']}")
        features_seen.add(top["feature_id"])

        if top["overlap"] > 0:
            for other in candidates[1:]:
                if other["feature_id"] in features_seen:
                    continue
                if other["overlap"] > 0:
                    combined_models = (
                        feature_choice_models.get((top["feature_id"], top["value"]), set())
                        & feature_choice_models.get((other["feature_id"], other["value"]), set())
                    )
                    if p_models <= combined_models:
                        chosen_tokens.append(f"{other['feature_id']}::{other['value']}")
                        features_seen.add(other["feature_id"])

        inferred[pid] = chosen_tokens

    return inferred


def preview_inferred_part_feature_rules(
    project_id: str,
    overwrite_existing: bool = False,
    part_ids: list[str] | None = None,
    *,
    _conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Preview inferred feature applicability tokens and group them by review requirement.

    Separates unambiguous single-feature parts from parts matching multiple feature choices.
    Returns:
        direct: {part_id: [rule_token, ...]} for unambiguous parts (single-feature or 'All models').
        review: list of dicts for parts with multiple inferred rules:
            [{
                "part_id": str,
                "part_number": str,
                "description": str,
                "models": str,
                "feature_applicability": list[str], # Human-readable labels pre-populated
                "inferred_tokens": list[str],        # The original tokens
            }]
        feature_options: list of human-readable feature labels (including 'All models').
        feature_token_by_label: mapping of human-readable labels to rule tokens.
        skipped_existing_count: number of parts skipped due to existing rules.
        skipped_assembly_count: number of parts skipped due to linked manufacturing assemblies.
        total_inferred: total count of parts evaluated.
    """
    inferred = infer_part_feature_rules(project_id, part_ids=part_ids, _conn=_conn)

    read_rows = (
        lambda sql, params=(): [dict(row) for row in _conn.execute(sql, params).fetchall()]
        if _conn is not None
        else query(sql, params)
    )

    feature_rows = read_rows(
        "SELECT id, name, category, allowed_values FROM complexity_features WHERE project_id=? AND active=1 ORDER BY category, name",
        (project_id,),
    )
    feature_option_labels: dict[str, str] = {"All models": "All models"}
    feature_token_by_label: dict[str, str] = {"All models": "All models"}
    for f in feature_rows:
        fid = str(f["id"])
        cat = str(f.get("category") or "").strip()
        fname = str(f.get("name") or "").strip()
        try:
            allowed = json.loads(f.get("allowed_values") or "[]")
        except Exception:
            allowed = []
        for val in allowed:
            val_str = str(val).strip()
            token = f"{fid}::{val_str}"
            label = f"{cat} · {fname} = {val_str}" if cat else f"{fname} = {val_str}"
            feature_option_labels[token] = label
            feature_token_by_label[label] = token
    feature_options = list(feature_token_by_label.keys())

    if not inferred:
        return {
            "direct": {},
            "review": [],
            "feature_options": feature_options,
            "feature_token_by_label": feature_token_by_label,
            "skipped_existing_count": 0,
            "skipped_assembly_count": 0,
            "total_inferred": 0,
        }

    existing_rules = {
        str(row["part_id"])
        for row in read_rows(
            "SELECT DISTINCT part_id FROM part_feature_rules WHERE project_id=?",
            (project_id,),
        )
    }
    existing_applicability = {
        str(row["id"]): str(row["model_applicability"] or "").strip()
        for row in read_rows(
            "SELECT id, model_applicability FROM parts WHERE project_id=?",
            (project_id,),
        )
    }
    linked_assemblies = {
        str(row["catalog_part_id"])
        for row in read_rows(
            "SELECT catalog_part_id FROM manufacturing_assemblies WHERE project_id=? AND catalog_part_id IS NOT NULL",
            (project_id,),
        )
    }

    part_rows = read_rows(
        "SELECT id, part_number, description, model_applicability FROM parts WHERE project_id=?",
        (project_id,),
    )
    part_info = {str(row["id"]): row for row in part_rows}

    bom_rows = read_rows(
        "SELECT child_part_id, raw_levels_json FROM pits_bom_occurrences WHERE project_id=?",
        (project_id,),
    )
    part_models_map: dict[str, set[str]] = {}
    for b in bom_rows:
        cid = str(b.get("child_part_id") or "").strip()
        if cid:
            try:
                levels = json.loads(b.get("raw_levels_json") or "{}")
                usages = levels.get("model_usages") or {}
                if isinstance(usages, dict):
                    part_models_map.setdefault(cid, set()).update(
                        str(m).strip() for m in usages if str(m).strip()
                    )
            except Exception:
                pass

    direct_to_apply: dict[str, list[str]] = {}
    review_rows: list[dict[str, Any]] = []
    skipped_existing_count = 0
    skipped_assembly_count = 0

    for part_id, tokens in inferred.items():
        if part_id in linked_assemblies:
            skipped_assembly_count += 1
            continue
        if not overwrite_existing and part_id in existing_rules:
            skipped_existing_count += 1
            continue
        if (
            not overwrite_existing
            and tokens == ["All models"]
            and existing_applicability.get(part_id, "").lower() == "all"
        ):
            skipped_existing_count += 1
            continue

        if len(tokens) > 1:
            p = part_info.get(part_id, {})
            models_set = part_models_map.get(part_id)
            if not models_set:
                app_str = str(p.get("model_applicability") or "").strip()
                if app_str and app_str.lower() != "all":
                    models_set = {m.strip() for m in app_str.split(",") if m.strip()}
            models_display = ", ".join(sorted(models_set)) if models_set else "Not specified"
            labels = [feature_option_labels.get(t, t) for t in tokens]
            review_rows.append({
                "part_id": part_id,
                "part_number": str(p.get("part_number") or ""),
                "description": str(p.get("description") or ""),
                "models": models_display,
                "feature_applicability": labels,
                "inferred_tokens": tokens,
            })
        else:
            direct_to_apply[part_id] = tokens

    review_rows.sort(key=lambda r: r["part_number"])
    return {
        "direct": direct_to_apply,
        "review": review_rows,
        "feature_options": feature_options,
        "feature_token_by_label": feature_token_by_label,
        "skipped_existing_count": skipped_existing_count,
        "skipped_assembly_count": skipped_assembly_count,
        "total_inferred": len(inferred),
    }


def apply_inferred_part_feature_rules(
    project_id: str,
    overwrite_existing: bool = False,
    part_ids: list[str] | None = None,
    editor_name: str = "",
    skip_multi_feature: bool = False,
    *,
    _conn: sqlite3.Connection | None = None,
) -> int:
    """Infer and apply feature applicability rules to project parts based on the Complexity Tree.

    Updates part_feature_rules and recalculates parts.model_applicability accordingly.
    When overwrite_existing is False, preserves manually assigned part_feature_rules and
    does not overwrite parts already configured as 'All'.
    When skip_multi_feature is True, only applies unambiguous single-feature or 'All models' rules.
    """
    preview = preview_inferred_part_feature_rules(
        project_id,
        overwrite_existing=overwrite_existing,
        part_ids=part_ids,
        _conn=_conn,
    )
    to_apply = dict(preview["direct"])
    if not skip_multi_feature:
        for r in preview["review"]:
            to_apply[r["part_id"]] = r["inferred_tokens"]

    if not to_apply:
        return 0

    context = nullcontext(_conn) if _conn is not None else connection()
    with context as conn:
        updated = update_part_feature_rules(project_id, to_apply, _conn=conn)
        if updated > 0:
            record_audit_event(
                project_id,
                "Parts",
                "Auto-assign from Complexity tree",
                updated,
                editor_name,
                {"parts_updated": updated, "overwrite_existing": overwrite_existing},
                _conn=conn,
            )
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

def pits_bom_occurrences(
    project_id: str, *, actionable_only: bool = False
) -> pd.DataFrame:
    """Return staged BOM occurrences with friendly relationship context."""
    action_clause = (
        "AND (occurrence.review_status='Needs review' "
        "OR occurrence.source_state IN ('Changed', 'Missing') "
        "OR occurrence.validation_issues_json<>'[]')"
        if actionable_only
        else ""
    )
    return pd.DataFrame(query(
        f"""SELECT occurrence.*, parent_part.part_number AS parent_part_number,
                   child_part.part_number AS child_part_number,
                   child_part.description AS child_part_name,
                   section.name AS confirmed_section_name,
                   assignment.quantity AS approved_quantity,
                   assignment.pits_sync_status
            FROM pits_bom_occurrences occurrence
            LEFT JOIN parts parent_part ON parent_part.id=occurrence.parent_part_id
            LEFT JOIN parts child_part ON child_part.id=occurrence.child_part_id
            LEFT JOIN assembly_sections section ON section.id=occurrence.confirmed_section_id
            LEFT JOIN fishbone_part_assignments assignment
              ON assignment.id=occurrence.approved_assignment_id
            WHERE occurrence.project_id=? {action_clause}
            ORDER BY CASE occurrence.source_state
                       WHEN 'Missing' THEN 1 WHEN 'Changed' THEN 2
                       WHEN 'New' THEN 3 ELSE 4 END,
                     occurrence.source_row, occurrence.id""",
        (project_id,),
    ))


def _pits_bom_fingerprint(depth: int, raw_quantity_text: str, quantity) -> str:
    normalized_quantity = None
    if quantity is not None:
        try:
            numeric = float(quantity)
            if math.isfinite(numeric):
                normalized_quantity = round(numeric, 9)
        except (TypeError, ValueError):
            pass
    payload = json.dumps(
        {
            "depth": int(depth),
            "quantity": normalized_quantity,
            "raw_quantity": "" if normalized_quantity is not None else raw_quantity_text,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _refresh_pits_assignment_sync_status(
    conn: sqlite3.Connection, project_id: str
) -> None:
    conn.execute(
        """UPDATE fishbone_part_assignments
           SET pits_sync_status='Not linked', pits_quantity_updated_at=NULL
           WHERE project_id=?
             AND NOT EXISTS (
                 SELECT 1 FROM pits_bom_occurrences occurrence
                 WHERE occurrence.project_id=fishbone_part_assignments.project_id
                   AND occurrence.approved_assignment_id=fishbone_part_assignments.id
             )""",
        (project_id,),
    )
    conn.execute(
        """UPDATE fishbone_part_assignments
           SET pits_sync_status=(
               SELECT CASE
                   WHEN occurrence.source_state='Missing' THEN 'No longer found'
                   WHEN occurrence.proposed_quantity IS NOT NULL
                    AND ROUND(occurrence.proposed_quantity, 9)=ROUND(fishbone_part_assignments.quantity, 9)
                       THEN 'In sync'
                   ELSE 'Quantity differs'
               END
               FROM pits_bom_occurrences occurrence
               WHERE occurrence.project_id=fishbone_part_assignments.project_id
                 AND occurrence.approved_assignment_id=fishbone_part_assignments.id
           )
           WHERE project_id=?
             AND EXISTS (
                 SELECT 1 FROM pits_bom_occurrences occurrence
                 WHERE occurrence.project_id=fishbone_part_assignments.project_id
                   AND occurrence.approved_assignment_id=fishbone_part_assignments.id
             )""",
        (project_id,),
    )


def _import_pits_bom_snapshot(
    conn: sqlite3.Connection,
    project_id: str,
    bom_snapshot: dict,
    *,
    workbook_name: str,
    workbook_sha256: str,
    editor_name: str,
    timestamp: str,
) -> dict[str, int | str]:
    occurrences = list(bom_snapshot.get("occurrences") or [])
    duplicates = list(bom_snapshot.get("duplicates") or [])
    blocking_issues = [
        issue for issue in (bom_snapshot.get("issues") or []) if issue.get("blocking")
    ]
    if blocking_issues:
        examples = ", ".join(
            f"row {issue.get('source_row')}: {issue.get('issue')}"
            for issue in blocking_issues[:5]
        )
        raise ValueError(
            "The BOM hierarchy contains rows without stable occurrence identities. "
            f"Resolve them before importing: {examples}"
        )

    duplicate_rows_by_key: dict[tuple[str, str], set[int]] = {}
    for duplicate in duplicates:
        key = (
            str(duplicate.get("parent_tracker_number") or "").strip(),
            str(duplicate.get("child_tracker_number") or "").strip(),
        )
        if not key[1]:
            continue
        rows = duplicate_rows_by_key.setdefault(key, set())
        for field in ("first_source_row", "duplicate_source_row"):
            try:
                rows.add(int(duplicate.get(field)))
            except (TypeError, ValueError):
                pass

    first_occurrence_by_key: dict[tuple[str, str], dict] = {}
    normalized_occurrences: list[dict] = []
    for occurrence in occurrences:
        key = (
            str(occurrence.get("parent_tracker_number") or "").strip(),
            str(occurrence.get("child_tracker_number") or "").strip(),
        )
        if not key[1]:
            raise ValueError("Every BOM occurrence requires a child tracker number.")
        if key in first_occurrence_by_key:
            rows = duplicate_rows_by_key.setdefault(key, set())
            for candidate in (first_occurrence_by_key[key], occurrence):
                try:
                    rows.add(int(candidate.get("source_row")))
                except (TypeError, ValueError):
                    pass
            continue
        first_occurrence_by_key[key] = occurrence
        normalized_occurrences.append(occurrence)
    occurrences = normalized_occurrences

    import_id = str(uuid4())
    import_sequence = int(conn.execute(
        "SELECT COALESCE(MAX(import_sequence), 0) + 1 FROM pits_bom_imports WHERE project_id=?",
        (project_id,),
    ).fetchone()[0])
    part_by_tracker = {
        str(row["pits_tracker_number"]).strip(): dict(row)
        for row in conn.execute(
            """SELECT id, part_number, pits_tracker_number FROM parts
               WHERE project_id=? AND TRIM(COALESCE(pits_tracker_number, ''))<>''""",
            (project_id,),
        ).fetchall()
    }
    issue_count = len(bom_snapshot.get("issues") or [])
    summary: dict[str, int | str] = {
        "import_id": import_id, "new": 0, "changed": 0,
        "unchanged": 0, "missing": 0, "issues": 0,
        "duplicate_pairs": len(duplicate_rows_by_key),
        "quantity_updates": 0,
    }
    conn.execute(
        """INSERT INTO pits_bom_imports
           (id, project_id, import_sequence, workbook_name, workbook_sha256,
            bom_sheet_name, source_row_count, occurrence_count, issue_count,
            imported_by, imported_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
        (
            import_id, project_id, import_sequence, str(workbook_name or "").strip(),
            str(workbook_sha256 or "").strip(),
            str(bom_snapshot.get("sheet_name") or "BOM").strip() or "BOM",
            int(bom_snapshot.get("source_row_count") or 0), len(occurrences),
            str(editor_name or "").strip(), timestamp,
        ),
    )

    for source in occurrences:
        parent_tracker = str(source.get("parent_tracker_number") or "").strip()
        child_tracker = str(source.get("child_tracker_number") or "").strip()
        depth = int(source.get("proposed_depth") or 0)
        source_root_depth = int(source.get("source_root_depth") or 1)
        if depth < 1 or depth > 11:
            raise ValueError(f"BOM row {source.get('source_row')} has an invalid Level depth.")
        raw_quantity_text = str(source.get("raw_quantity_text") or "").strip()
        proposed_quantity = source.get("proposed_quantity")
        quantity_is_valid = False
        try:
            numeric_quantity = float(proposed_quantity)
            quantity_is_valid = math.isfinite(numeric_quantity) and numeric_quantity > 0
            proposed_quantity = numeric_quantity if math.isfinite(numeric_quantity) else None
        except (TypeError, ValueError):
            proposed_quantity = None
        validation_issues: list[str] = []
        parent_part = part_by_tracker.get(parent_tracker) if parent_tracker else None
        child_part = part_by_tracker.get(child_tracker)
        source_row = int(source["source_row"])
        if parent_tracker and parent_part is None:
            validation_issues.append(
                f"BOM row {source_row}: Parent tracker {parent_tracker or '[blank]'} is not "
                "matched to a Parts Catalog record"
            )
        if not parent_tracker and depth != source_root_depth:
            validation_issues.append(
                f"BOM row {source_row}: Level {depth} has no parent at Level {depth - 1}"
            )
        if child_part is None:
            validation_issues.append(
                f"BOM row {source_row}: Child tracker {child_tracker} is not matched to a "
                "Parts Catalog record"
            )
        if not quantity_is_valid:
            validation_issues.append(
                f"BOM row {source_row}: Level {depth} value {raw_quantity_text or '[blank]'} "
                "must be a finite number greater than zero"
            )
        duplicate_source_rows = sorted(duplicate_rows_by_key.get(
            (parent_tracker, child_tracker), set()
        ))
        if duplicate_source_rows:
            row_list = ", ".join(str(row) for row in duplicate_source_rows)
            validation_issues.append(
                f"Duplicate parent/child pair appears on BOM rows {row_list}; "
                "resolve the duplicate in PITS and re-import before approval"
            )
        issue_count += len(validation_issues)
        fingerprint = _pits_bom_fingerprint(depth, raw_quantity_text, proposed_quantity)
        raw_levels_json = json.dumps(
            source.get("raw_levels") or {}, ensure_ascii=False, sort_keys=True, default=str
        )
        existing = conn.execute(
            """SELECT * FROM pits_bom_occurrences
               WHERE project_id=? AND parent_tracker_number=? AND child_tracker_number=?""",
            (project_id, parent_tracker, child_tracker),
        ).fetchone()
        if existing is None:
            occurrence_id = str(uuid4())
            conn.execute(
                """INSERT INTO pits_bom_occurrences
                   (id, project_id, parent_tracker_number, child_tracker_number,
                    parent_part_id, child_part_id, proposed_depth, raw_quantity_text,
                    proposed_quantity, source_row, raw_levels_json, source_fingerprint,
                    review_status, source_state, validation_issues_json,
                    first_seen_import_id, last_seen_import_id,
                    first_seen_at, last_seen_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Needs review', 'New',
                           ?, ?, ?, ?, ?, ?)""",
                (
                    occurrence_id, project_id, parent_tracker, child_tracker,
                    parent_part["id"] if parent_part else None,
                    child_part["id"] if child_part else None,
                    depth, raw_quantity_text, proposed_quantity, source_row,
                    raw_levels_json, fingerprint,
                    json.dumps(validation_issues, ensure_ascii=False),
                    import_id, import_id, timestamp, timestamp, timestamp,
                ),
            )
            revision_no = 1
            summary["new"] = int(summary["new"]) + 1
        else:
            occurrence_id = str(existing["id"])
            depth_changed = int(existing["proposed_depth"]) != depth
            changed = str(existing["source_fingerprint"]) != fingerprint
            reviewed_fingerprint = existing["reviewed_source_fingerprint"]
            approved_assignment_id = existing["approved_assignment_id"]
            is_approved = (
                str(existing["review_status"]) == "Approved" and bool(approved_assignment_id)
            )
            quantity_updated = False
            if is_approved and proposed_quantity is not None:
                assignment = conn.execute(
                    "SELECT id, quantity FROM fishbone_part_assignments WHERE id=?",
                    (approved_assignment_id,),
                ).fetchone()
                if assignment and assignment["quantity"] is not None:
                    try:
                        old_qty = float(assignment["quantity"])
                        new_qty = float(proposed_quantity)
                        if round(old_qty, 9) != round(new_qty, 9):
                            conn.execute(
                                """UPDATE fishbone_part_assignments
                                   SET quantity=?, pits_quantity_updated_at=?, updated_at=?
                                   WHERE id=?""",
                                (new_qty, timestamp, timestamp, approved_assignment_id),
                            )
                            quantity_updated = True
                    except (TypeError, ValueError):
                        pass

            if is_approved:
                if depth_changed:
                    source_state = "Changed"
                else:
                    source_state = "Current"
                    reviewed_fingerprint = fingerprint
                review_status = "Approved"
                structural_changed = depth_changed
            else:
                source_state = (
                    "New" if not reviewed_fingerprint
                    else ("Current" if str(reviewed_fingerprint) == fingerprint else "Changed")
                )
                review_status = str(existing["review_status"])
                if changed and review_status == "Rejected":
                    review_status = "Needs review"
                structural_changed = changed

            conn.execute(
                """UPDATE pits_bom_occurrences
                   SET parent_part_id=?, child_part_id=?, proposed_depth=?, raw_quantity_text=?,
                       proposed_quantity=?, source_row=?, raw_levels_json=?, source_fingerprint=?,
                       reviewed_source_fingerprint=?, review_status=?, source_state=?,
                       validation_issues_json=?, last_seen_import_id=?, last_seen_at=?, updated_at=?
                   WHERE id=? AND project_id=?""",
                (
                    parent_part["id"] if parent_part else None,
                    child_part["id"] if child_part else None,
                    depth, raw_quantity_text, proposed_quantity, source_row,
                    raw_levels_json, fingerprint, reviewed_fingerprint,
                    review_status, source_state,
                    json.dumps(validation_issues, ensure_ascii=False),
                    import_id, timestamp, timestamp, occurrence_id, project_id,
                ),
            )
            revision_no = int(conn.execute(
                """SELECT COALESCE(MAX(revision_no), 0) + 1
                   FROM pits_bom_occurrence_revisions WHERE occurrence_id=?""",
                (occurrence_id,),
            ).fetchone()[0])
            summary["changed" if structural_changed else "unchanged"] = (
                int(summary["changed" if structural_changed else "unchanged"]) + 1
            )
            if quantity_updated:
                summary["quantity_updates"] = int(summary["quantity_updates"]) + 1

        revision_exists = conn.execute(
            """SELECT 1 FROM pits_bom_occurrence_revisions
               WHERE occurrence_id=? AND source_fingerprint=?""",
            (occurrence_id, fingerprint),
        ).fetchone()
        if not revision_exists:
            conn.execute(
                """INSERT INTO pits_bom_occurrence_revisions
                   (id, occurrence_id, import_id, revision_no, source_row, proposed_depth,
                    raw_quantity_text, proposed_quantity, raw_levels_json,
                    source_fingerprint, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()), occurrence_id, import_id, revision_no,
                    source_row, depth, raw_quantity_text,
                    proposed_quantity, raw_levels_json, fingerprint, timestamp,
                ),
            )

    missing_cursor = conn.execute(
        """UPDATE pits_bom_occurrences
           SET source_state='Missing', updated_at=?
           WHERE project_id=? AND last_seen_import_id<>? AND source_state<>'Missing'""",
        (timestamp, project_id, import_id),
    )
    summary["missing"] = max(int(missing_cursor.rowcount), 0)
    summary["issues"] = issue_count
    conn.execute("UPDATE pits_bom_imports SET issue_count=? WHERE id=?", (issue_count, import_id))
    _refresh_pits_assignment_sync_status(conn, project_id)
    record_audit_event(
        project_id, "PITS BOM structure", "Import PITS BOM structure",
        len(occurrences), editor_name,
        {
            "import_id": import_id,
            "new_occurrences": summary["new"],
            "changed_occurrences": summary["changed"],
            "unchanged_occurrences": summary["unchanged"],
            "missing_occurrences": summary["missing"],
            "duplicate_parent_child_pairs": summary["duplicate_pairs"],
            "quantity_updates": summary["quantity_updates"],
            "issue_count": issue_count,
        },
        _conn=conn,
    )
    return summary


def review_pits_bom_occurrences(
    project_id: str,
    occurrence_ids: list[str],
    action: str,
    editor_name: str = "",
    *,
    section_id: str | None = None,
    existing_assignment_id: str | None = None,
    rejection_reason: str = "",
) -> dict[str, int | str]:
    """Approve, reject, acknowledge, or detach staged BOM occurrences atomically."""
    selected_ids = list(dict.fromkeys(
        str(value).strip() for value in occurrence_ids if str(value).strip()
    ))
    if not selected_ids:
        raise ValueError("Select at least one PITS BOM occurrence.")
    allowed_actions = {"Approve", "Reject", "Acknowledge", "Detach"}
    if action not in allowed_actions:
        raise ValueError("Unsupported PITS BOM review action.")
    if action == "Approve" and len(selected_ids) != 1:
        raise ValueError("Approve one occurrence at a time so its Fishbone section is explicit.")
    placeholders = ",".join("?" for _ in selected_ids)
    timestamp = now_iso()
    created_assignments = 0
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT * FROM pits_bom_occurrences
                WHERE project_id=? AND id IN ({placeholders})""",
            (project_id, *selected_ids),
        ).fetchall()
        if len(rows) != len(selected_ids):
            raise ValueError("One or more selected PITS BOM occurrences no longer exist.")

        if action == "Approve":
            occurrence = rows[0]
            if occurrence["source_state"] == "Missing":
                raise ValueError("A missing occurrence cannot be approved.")
            try:
                validation_issues = json.loads(occurrence["validation_issues_json"] or "[]")
            except json.JSONDecodeError:
                validation_issues = ["Stored validation details are invalid"]
            if validation_issues:
                raise ValueError("Resolve the occurrence's validation issues before approval.")
            child_part_id = occurrence["child_part_id"]
            if not child_part_id:
                raise ValueError("Match the child tracker number to a Parts Catalog record first.")
            try:
                quantity = float(occurrence["proposed_quantity"])
            except (TypeError, ValueError) as exc:
                raise ValueError("A positive PITS quantity is required before approval.") from exc
            if not math.isfinite(quantity) or quantity <= 0:
                raise ValueError("A positive PITS quantity is required before approval.")
            section = conn.execute(
                "SELECT id FROM assembly_sections WHERE id=? AND project_id=? AND active=1",
                (section_id, project_id),
            ).fetchone()
            if not section:
                raise ValueError("Choose an active Fishbone section.")
            assignment_id = str(existing_assignment_id or "").strip()
            if assignment_id:
                assignment = conn.execute(
                    """SELECT id FROM fishbone_part_assignments
                       WHERE id=? AND project_id=? AND part_id=? AND section_id=?""",
                    (assignment_id, project_id, child_part_id, section_id),
                ).fetchone()
                if not assignment:
                    raise ValueError(
                        "The selected Fishbone use must use the same part and Fishbone section."
                    )
                claimed = conn.execute(
                    """SELECT 1 FROM pits_bom_occurrences
                       WHERE project_id=? AND approved_assignment_id=? AND id<>?""",
                    (project_id, assignment_id, occurrence["id"]),
                ).fetchone()
                if claimed:
                    raise ValueError("That Fishbone use is already linked to another occurrence.")
            else:
                assignment_id = str(uuid4())
                next_sequence = int(conn.execute(
                    """SELECT COALESCE(MAX(sequence), 0) + 10
                       FROM fishbone_part_assignments
                       WHERE project_id=? AND section_id=?""",
                    (project_id, section_id),
                ).fetchone()[0])
                conn.execute(
                    """INSERT INTO fishbone_part_assignments
                       (id, project_id, part_id, section_id, sequence, quantity,
                        use_description, notes, pits_sync_status, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, '', 'Not linked', ?)""",
                    (
                        assignment_id, project_id, child_part_id, section_id,
                        next_sequence, quantity,
                        f"PITS {occurrence['parent_tracker_number'] or 'root'} â†’ "
                        f"{occurrence['child_tracker_number']}",
                        timestamp,
                    ),
                )
                created_assignments = 1
            conn.execute(
                """UPDATE pits_bom_occurrences
                   SET review_status='Approved', source_state='Current',
                       reviewed_source_fingerprint=source_fingerprint,
                       confirmed_section_id=?, approved_assignment_id=?,
                       last_reviewed_import_id=last_seen_import_id,
                       reviewed_by=?, reviewed_at=?, rejection_reason='', updated_at=?
                   WHERE id=? AND project_id=?""",
                (
                    section_id, assignment_id, str(editor_name or "").strip(),
                    timestamp, timestamp, occurrence["id"], project_id,
                ),
            )
        elif action == "Reject":
            if any(row["review_status"] == "Approved" for row in rows):
                raise ValueError("Detach an approved occurrence before rejecting it.")
            if any(row["source_state"] == "Missing" for row in rows):
                raise ValueError("A missing unapproved occurrence does not require rejection.")
            conn.execute(
                f"""UPDATE pits_bom_occurrences
                    SET review_status='Rejected', source_state='Current',
                        reviewed_source_fingerprint=source_fingerprint,
                        last_reviewed_import_id=last_seen_import_id,
                        reviewed_by=?, reviewed_at=?, rejection_reason=?, updated_at=?
                    WHERE project_id=? AND id IN ({placeholders})""",
                (
                    str(editor_name or "").strip(), timestamp,
                    str(rejection_reason or "").strip(), timestamp,
                    project_id, *selected_ids,
                ),
            )
        elif action == "Acknowledge":
            for row in rows:
                if row["source_state"] == "Changed":
                    conn.execute(
                        """UPDATE pits_bom_occurrences
                           SET reviewed_source_fingerprint=source_fingerprint,
                               source_state='Current', last_reviewed_import_id=last_seen_import_id,
                               reviewed_by=?, reviewed_at=?, updated_at=?
                           WHERE id=? AND project_id=?""",
                        (
                            str(editor_name or "").strip(), timestamp, timestamp,
                            row["id"], project_id,
                        ),
                    )
                else:
                    conn.execute(
                        """UPDATE pits_bom_occurrences
                           SET reviewed_by=?, reviewed_at=?, updated_at=?
                           WHERE id=? AND project_id=?""",
                        (
                            str(editor_name or "").strip(), timestamp, timestamp,
                            row["id"], project_id,
                        ),
                    )
        else:
            if any(row["review_status"] != "Approved" for row in rows):
                raise ValueError("Only approved occurrences can be detached.")
            conn.execute(
                f"""UPDATE pits_bom_occurrences
                    SET review_status='Needs review', confirmed_section_id=NULL,
                        approved_assignment_id=NULL, reviewed_source_fingerprint=NULL,
                        last_reviewed_import_id=NULL, reviewed_by=?, reviewed_at=?,
                        source_state=CASE WHEN source_state='Missing' THEN 'Missing' ELSE 'New' END,
                        updated_at=?
                    WHERE project_id=? AND id IN ({placeholders})""",
                (
                    str(editor_name or "").strip(), timestamp, timestamp,
                    project_id, *selected_ids,
                ),
            )

        _refresh_pits_assignment_sync_status(conn, project_id)
        record_audit_event(
            project_id, "PITS BOM structure", action, len(selected_ids), editor_name,
            {
                "occurrence_ids": selected_ids,
                "section_id": section_id,
                "existing_assignment_id": existing_assignment_id,
                "created_assignments": created_assignments,
            },
            _conn=conn,
        )
    return {
        "reviewed": len(selected_ids),
        "created_assignments": created_assignments,
        "timestamp": timestamp,
    }


def escalate_pits_bom_occurrence(
    project_id: str, occurrence_id: str, editor_name: str = ""
) -> str:
    """Create a linked concern without clearing any PITS difference state."""
    timestamp = now_iso()
    concern_id = str(uuid4())
    with connection() as conn:
        occurrence = conn.execute(
            """SELECT occurrence.*, child_part.part_number AS child_part_number,
                      assignment.pits_sync_status
               FROM pits_bom_occurrences occurrence
               LEFT JOIN parts child_part ON child_part.id=occurrence.child_part_id
               LEFT JOIN fishbone_part_assignments assignment
                 ON assignment.id=occurrence.approved_assignment_id
               WHERE occurrence.id=? AND occurrence.project_id=?""",
            (occurrence_id, project_id),
        ).fetchone()
        if not occurrence:
            raise ValueError("The selected PITS BOM occurrence no longer exists.")
        source_state = str(occurrence["source_state"])
        escalation_state = source_state
        if source_state == "Current" and occurrence["pits_sync_status"] == "No longer found":
            escalation_state = "Missing"
        if escalation_state not in {"New", "Changed", "Missing"}:
            raise ValueError("Only a new, changed, or missing occurrence can be escalated.")
        child_label = str(
            occurrence["child_part_number"] or occurrence["child_tracker_number"]
        )
        parent_label = str(occurrence["parent_tracker_number"] or "Product / main assembly")
        conn.execute(
            """INSERT INTO concerns
               (id, project_id, category, subject, detail, owner, priority, status,
                related_part, related_station, created_at, updated_at)
               VALUES (?, ?, 'Concern', ?, ?, '', 'Medium', 'Open', ?, '', ?, ?)""",
            (
                concern_id, project_id,
                f"PITS BOM occurrence requires review: {parent_label} â†’ {child_label}",
                f"Source state: {escalation_state}. PITS tracker relationship "
                f"{parent_label} â†’ {occurrence['child_tracker_number']}.",
                child_label, timestamp, timestamp,
            ),
        )
        conn.execute(
            """INSERT INTO pits_bom_occurrence_concerns
               (id, project_id, occurrence_id, concern_id, escalated_source_state,
                escalated_source_fingerprint, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()), project_id, occurrence_id, concern_id, escalation_state,
                str(occurrence["source_fingerprint"]),
                str(editor_name or "").strip(), timestamp,
            ),
        )
        record_audit_event(
            project_id, "PITS BOM structure", "Escalate", 1, editor_name,
            {"occurrence_id": occurrence_id, "concern_id": concern_id},
            _conn=conn,
        )
    return concern_id


def pits_catalog_id_resolution(records: list[dict]) -> dict[str, object]:
    """Resolve one catalog PITS ID per part number, using BOM evidence when needed."""
    tracker_ids_by_part: dict[str, set[str]] = {}
    bom_ids_by_part: dict[str, set[str]] = {}
    for record in records:
        part_number = str(record.get("part_number") or "").strip()
        pits_id = str(record.get("pits_id") or "").strip()
        if not part_number:
            continue
        if pits_id:
            tracker_ids_by_part.setdefault(part_number, set()).add(pits_id)
        raw_bom_ids = record.get("_bom_pits_ids") or []
        if isinstance(raw_bom_ids, str):
            raw_bom_ids = [raw_bom_ids]
        for bom_pits_id in raw_bom_ids:
            cleaned_bom_id = str(bom_pits_id or "").strip()
            if cleaned_bom_id:
                bom_ids_by_part.setdefault(part_number, set()).add(cleaned_bom_id)

    resolved_ids: dict[str, str] = {}
    resolved_from_bom: set[str] = set()
    missing_bom_match: set[str] = set()
    mismatched_bom_match: set[str] = set()
    multiple_bom_ids = {
        part_number: sorted(pits_ids)
        for part_number, pits_ids in bom_ids_by_part.items()
        if len(pits_ids) > 1
    }
    for part_number, tracker_ids in tracker_ids_by_part.items():
        if len(tracker_ids) == 1:
            resolved_ids[part_number] = next(iter(tracker_ids))
            continue
        bom_ids = bom_ids_by_part.get(part_number, set())
        if len(bom_ids) == 1:
            bom_pits_id = next(iter(bom_ids))
            if bom_pits_id in tracker_ids:
                resolved_ids[part_number] = bom_pits_id
                resolved_from_bom.add(part_number)
            else:
                mismatched_bom_match.add(part_number)
        elif not bom_ids:
            missing_bom_match.add(part_number)

    unresolved_tracker_parts = {
        part_number
        for part_number, tracker_ids in tracker_ids_by_part.items()
        if len(tracker_ids) > 1 and part_number not in resolved_ids
    }
    return {
        "resolved_ids": resolved_ids,
        "resolved_from_bom": resolved_from_bom,
        "multiple_bom_ids": multiple_bom_ids,
        "missing_bom_match": missing_bom_match,
        "mismatched_bom_match": mismatched_bom_match,
        "unresolved_tracker_parts": unresolved_tracker_parts,
    }


def _pits_tracker_number_claims(
    conn: sqlite3.Connection,
    project_id: str,
    records: list[dict],
) -> tuple[list[str], list[dict]]:
    """Resolve blank-only tracker-number claims without violating project uniqueness."""
    id_resolution = pits_catalog_id_resolution(records)
    resolved_ids = id_resolution["resolved_ids"]
    existing_parts = conn.execute(
        """SELECT id, part_number, pits_tracker_number
           FROM parts WHERE project_id=?""",
        (project_id,),
    ).fetchall()
    tracker_by_part = {
        str(row["part_number"]): str(row["pits_tracker_number"] or "").strip()
        for row in existing_parts
    }
    owner_by_tracker = {
        str(row["pits_tracker_number"] or "").strip(): {
            "id": str(row["id"]),
            "part_number": str(row["part_number"]),
        }
        for row in existing_parts
        if str(row["pits_tracker_number"] or "").strip()
    }
    tracker_numbers = [""] * len(records)
    conflicts: list[dict] = []
    reported_conflicts: set[tuple[str, str, str]] = set()
    for record_index, record in enumerate(records):
        part_number = str(record.get("part_number") or "").strip()
        pits_id = str(record.get("pits_id") or "").strip()
        tracker_number = resolved_ids.get(part_number, "")
        if not part_number or not tracker_number:
            continue
        if pits_id != tracker_number:
            continue
        if tracker_by_part.get(part_number, ""):
            continue
        owner = owner_by_tracker.get(tracker_number)
        if owner and owner["part_number"] != part_number:
            conflict_key = (part_number, tracker_number, owner["part_number"])
            if conflict_key not in reported_conflicts:
                conflicts.append({
                    "conflict_type": "pits_tracker_number",
                    "part_number": part_number,
                    "pits_tracker_number": tracker_number,
                    "existing_part_id": owner["id"],
                    "existing_part_number": owner["part_number"],
                })
                reported_conflicts.add(conflict_key)
            continue
        tracker_numbers[record_index] = tracker_number
        tracker_by_part[part_number] = tracker_number
        owner_by_tracker[tracker_number] = {
            "id": "",
            "part_number": part_number,
        }
    return tracker_numbers, conflicts


def pits_import_conflict_parts(project_id: str, records: list[dict]) -> list[dict]:
    """Return protected manual values and PITS Tracker number conflicts."""
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
        manual_conflicts = [
            {**dict(row), "conflict_type": "manual_values"}
            for row in rows
        ]
        _, tracker_conflicts = _pits_tracker_number_claims(conn, project_id, records)
        return [*manual_conflicts, *tracker_conflicts]


def detect_pits_new_and_changed_parts(
    project_id: str,
    records: list[dict],
    bom_snapshot: dict | None = None,
) -> list[dict]:
    """Detect new part numbers and modified descriptions from uploaded PITS records and BOM occurrences.

    Deduplicates incoming records by part number so each part is reviewed once.
    Detects if an incoming part replaces a previous part number sharing the same PITS tracker ID.
    Returns a list of dicts for each detected new part or modified description.
    """
    seen_part_numbers: dict[str, dict] = {}
    for record in records:
        part_number = str(record.get("part_number") or "").strip()
        if not part_number:
            continue
        pits_id = str(record.get("pits_id") or "").strip()
        desc = str(record.get("description") or "").strip()
        if part_number not in seen_part_numbers:
            seen_part_numbers[part_number] = {
                "part_number": part_number,
                "incoming_description": desc,
                "pits_id": pits_id,
                "all_pits_ids": [pits_id] if pits_id else [],
                "subsystem": str(record.get("subsystem") or "").strip(),
                "design_maturity": str(record.get("design_maturity") or record.get("revision") or "").strip(),
                "design_engineer": str(record.get("design_engineer") or record.get("technology_engineer") or "").strip(),
                "ppm": str(record.get("ppm") or "").strip(),
                "buyer_gcl": str(record.get("buyer_gcl") or "").strip(),
                "source_code": str(record.get("source_code") or "").strip(),
                "comments": str(record.get("comments") or "").strip(),
            }
        else:
            item = seen_part_numbers[part_number]
            if pits_id and pits_id not in item["all_pits_ids"]:
                item["all_pits_ids"].append(pits_id)
            if not item["incoming_description"] and desc:
                item["incoming_description"] = desc

    if bom_snapshot and isinstance(bom_snapshot.get("occurrences"), list):
        for occ in bom_snapshot["occurrences"]:
            part_number = str(occ.get("part_number") or "").strip()
            if not part_number:
                continue
            pits_id = str(occ.get("child_tracker_number") or "").strip()
            desc = str(occ.get("description") or "").strip()
            if part_number not in seen_part_numbers:
                seen_part_numbers[part_number] = {
                    "part_number": part_number,
                    "incoming_description": desc,
                    "pits_id": pits_id,
                    "all_pits_ids": [pits_id] if pits_id else [],
                    "subsystem": "",
                    "design_maturity": "",
                    "design_engineer": "",
                    "ppm": "",
                    "buyer_gcl": "",
                    "source_code": "",
                    "comments": "",
                }
            else:
                item = seen_part_numbers[part_number]
                if pits_id and pits_id not in item["all_pits_ids"]:
                    item["all_pits_ids"].append(pits_id)
                if not item["incoming_description"] and desc:
                    item["incoming_description"] = desc

    if not seen_part_numbers:
        return []

    all_incoming_pits_ids = {
        pid
        for item in seen_part_numbers.values()
        for pid in item["all_pits_ids"]
        if pid
    }

    with connection() as conn:
        placeholders = ",".join("?" for _ in seen_part_numbers)
        rows = conn.execute(
            f"""SELECT id, part_number, description, subsystem, design_maturity,
                       design_engineer, technology_engineer, ppm, buyer_gcl, pits_tracker_number
                FROM parts
                WHERE project_id=? AND part_number IN ({placeholders})""",
            (project_id, *seen_part_numbers.keys()),
        ).fetchall()
        existing_by_part = {
            str(row["part_number"]): dict(row)
            for row in rows
        }

        tracker_owners: dict[str, dict] = {}
        if all_incoming_pits_ids:
            t_placeholders = ",".join("?" for _ in all_incoming_pits_ids)
            t_rows = conn.execute(
                f"""SELECT id, part_number, description, pits_tracker_number
                    FROM parts
                    WHERE project_id=? AND pits_tracker_number IN ({t_placeholders})""",
                (project_id, *all_incoming_pits_ids),
            ).fetchall()
            for r in t_rows:
                tracker_owners[str(r["pits_tracker_number"])] = dict(r)

    detected = []
    for part_number, item in seen_part_numbers.items():
        if part_number not in existing_by_part:
            item["change_type"] = "new_part"
            item["current_description"] = ""
            for pid in item["all_pits_ids"]:
                if pid in tracker_owners and tracker_owners[pid]["part_number"] != part_number:
                    replaces = tracker_owners[pid]
                    item["replaces_part_number"] = replaces["part_number"]
                    item["replaces_description"] = replaces.get("description", "")
                    item["replaces_part_id"] = replaces.get("id", "")
                    item["replaces_tracker_id"] = pid
                    break
            detected.append(item)
        else:
            existing = existing_by_part[part_number]
            curr_desc = str(existing.get("description") or "").strip()
            inc_desc = item["incoming_description"]
            if inc_desc and inc_desc != curr_desc:
                item["change_type"] = "changed_description"
                item["current_description"] = curr_desc
                detected.append(item)

    return detected


def pits_part_downstream_impacts(
    project_id: str,
    part_number: str,
    scenario_id: str | None = None,
    bom_snapshot: dict | None = None,
    replaces_part_number: str | None = None,
) -> dict:
    """Compute downstream planning impacts for a given part across Fishbone, Model Tree, Yamazumi, Process plan, and Concerns."""
    part_number = str(part_number or "").strip()
    with connection() as conn:
        part_row = conn.execute(
            "SELECT id, part_number, description FROM parts WHERE project_id=? AND part_number=?",
            (project_id, part_number),
        ).fetchone()
        part_id = part_row["id"] if part_row else None

        replaces_part_id = None
        if replaces_part_number:
            replaces_row = conn.execute(
                "SELECT id, part_number, description FROM parts WHERE project_id=? AND part_number=?",
                (project_id, replaces_part_number),
            ).fetchone()
            replaces_part_id = replaces_row["id"] if replaces_row else None

        fb_assignments = []
        if part_id:
            rows = conn.execute(
                """SELECT f.id, f.section_id, s.name AS section_name, f.quantity,
                          f.use_description, f.pits_sync_status
                   FROM fishbone_part_assignments f
                   LEFT JOIN assembly_sections s ON f.section_id = s.id
                   WHERE f.project_id=? AND f.part_id=?
                   ORDER BY s.sequence, f.sequence""",
                (project_id, part_id),
            ).fetchall()
            for r in rows:
                fb_assignments.append({
                    "assignment_id": str(r["id"]),
                    "section_id": str(r["section_id"] or ""),
                    "section_name": str(r["section_name"] or "Unassigned Section"),
                    "quantity": float(r["quantity"] or 1),
                    "use_description": str(r["use_description"] or ""),
                    "pits_sync_status": str(r["pits_sync_status"] or "Synced"),
                })

        replaces_fb_assignments = []
        if replaces_part_id:
            r_rows = conn.execute(
                """SELECT f.id, f.section_id, s.name AS section_name, f.quantity,
                          f.use_description, f.pits_sync_status
                   FROM fishbone_part_assignments f
                   LEFT JOIN assembly_sections s ON f.section_id = s.id
                   WHERE f.project_id=? AND f.part_id=?
                   ORDER BY s.sequence, f.sequence""",
                (project_id, replaces_part_id),
            ).fetchall()
            for r in r_rows:
                replaces_fb_assignments.append({
                    "assignment_id": str(r["id"]),
                    "section_id": str(r["section_id"] or ""),
                    "section_name": str(r["section_name"] or "Unassigned Section"),
                    "quantity": float(r["quantity"] or 1),
                    "use_description": str(r["use_description"] or ""),
                    "pits_sync_status": str(r["pits_sync_status"] or "Synced"),
                    "part_number": replaces_part_number,
                    "is_replaced_part": True,
                })

        uploaded_occurrences = []
        if bom_snapshot and isinstance(bom_snapshot.get("occurrences"), list):
            for occ in bom_snapshot["occurrences"]:
                if str(occ.get("part_number") or "").strip() == part_number:
                    uploaded_occurrences.append({
                        "source": "Uploaded BOM",
                        "parent_tracker_number": str(occ.get("parent_tracker_number") or ""),
                        "proposed_depth": int(occ.get("proposed_depth") or 1),
                        "proposed_quantity": float(occ.get("proposed_quantity") or 1),
                        "description": str(occ.get("description") or ""),
                        "review_status": "Staged candidate",
                    })

        db_occurrences = []
        if part_id:
            db_rows = conn.execute(
                """SELECT parent_tracker_number, proposed_depth, proposed_quantity, review_status
                   FROM pits_bom_occurrences
                   WHERE project_id=? AND child_part_id=?
                   ORDER BY proposed_depth""",
                (project_id, part_id),
            ).fetchall()
            for r in db_rows:
                db_occurrences.append({
                    "source": "Active Model Tree",
                    "parent_tracker_number": str(r["parent_tracker_number"] or ""),
                    "proposed_depth": int(r["proposed_depth"] or 1),
                    "proposed_quantity": float(r["proposed_quantity"] or 1),
                    "description": "",
                    "review_status": str(r["review_status"] or "Needs review"),
                })

        replaces_db_occurrences = []
        if replaces_part_id:
            r_db_rows = conn.execute(
                """SELECT parent_tracker_number, proposed_depth, proposed_quantity, review_status
                   FROM pits_bom_occurrences
                   WHERE project_id=? AND child_part_id=?
                   ORDER BY proposed_depth""",
                (project_id, replaces_part_id),
            ).fetchall()
            for r in r_db_rows:
                replaces_db_occurrences.append({
                    "source": "Active Model Tree",
                    "parent_tracker_number": str(r["parent_tracker_number"] or ""),
                    "proposed_depth": int(r["proposed_depth"] or 1),
                    "proposed_quantity": float(r["proposed_quantity"] or 1),
                    "description": "",
                    "review_status": str(r["review_status"] or "Needs review"),
                    "part_number": replaces_part_number,
                    "is_replaced_part": True,
                })

        yamazumi_elements = []
        ye_query = """SELECT id, station, operation, description, cycle_time_s, sequence, scenario_id
                      FROM work_elements
                      WHERE project_id=? AND part_number=?"""
        ye_params: list = [project_id, part_number]
        if scenario_id:
            ye_query += " AND (scenario_id=? OR scenario_id IS NULL)"
            ye_params.append(scenario_id)
        ye_query += " ORDER BY sequence"
        ye_rows = conn.execute(ye_query, tuple(ye_params)).fetchall()
        for r in ye_rows:
            yamazumi_elements.append({
                "id": str(r["id"]),
                "station": str(r["station"] or ""),
                "operation": str(r["operation"] or ""),
                "description": str(r["description"] or ""),
                "cycle_time_s": float(r["cycle_time_s"] or 0),
            })

        replaces_yamazumi_elements = []
        if replaces_part_number:
            rye_query = """SELECT id, station, operation, description, cycle_time_s, sequence, scenario_id
                           FROM work_elements
                           WHERE project_id=? AND part_number=?"""
            rye_params: list = [project_id, replaces_part_number]
            if scenario_id:
                rye_query += " AND (scenario_id=? OR scenario_id IS NULL)"
                rye_params.append(scenario_id)
            rye_query += " ORDER BY sequence"
            rye_rows = conn.execute(rye_query, tuple(rye_params)).fetchall()
            for r in rye_rows:
                replaces_yamazumi_elements.append({
                    "id": str(r["id"]),
                    "station": str(r["station"] or ""),
                    "operation": str(r["operation"] or ""),
                    "description": str(r["description"] or ""),
                    "cycle_time_s": float(r["cycle_time_s"] or 0),
                    "part_number": replaces_part_number,
                    "is_replaced_part": True,
                })

        process_options = []
        if part_id:
            po_query = """SELECT o.id, o.handling_type, g.name AS group_name,
                                 w.station, w.operation
                          FROM process_part_options o
                          JOIN process_part_groups g ON o.group_id = g.id
                          JOIN work_elements w ON g.work_element_id = w.id
                          WHERE g.project_id=? AND o.part_id=?"""
            po_params: list = [project_id, part_id]
            if scenario_id:
                po_query += " AND g.scenario_id=?"
                po_params.append(scenario_id)
            po_rows = conn.execute(po_query, tuple(po_params)).fetchall()
            for r in po_rows:
                process_options.append({
                    "id": str(r["id"]),
                    "group_name": str(r["group_name"] or ""),
                    "handling_type": str(r["handling_type"] or "Consume"),
                    "station": str(r["station"] or ""),
                    "operation": str(r["operation"] or ""),
                })

        replaces_process_options = []
        if replaces_part_id:
            rpo_query = """SELECT o.id, o.handling_type, g.name AS group_name,
                                  w.station, w.operation
                           FROM process_part_options o
                           JOIN process_part_groups g ON o.group_id = g.id
                           JOIN work_elements w ON g.work_element_id = w.id
                           WHERE g.project_id=? AND o.part_id=?"""
            rpo_params: list = [project_id, replaces_part_id]
            if scenario_id:
                rpo_query += " AND g.scenario_id=?"
                rpo_params.append(scenario_id)
            rpo_rows = conn.execute(rpo_query, tuple(rpo_params)).fetchall()
            for r in rpo_rows:
                replaces_process_options.append({
                    "id": str(r["id"]),
                    "group_name": str(r["group_name"] or ""),
                    "handling_type": str(r["handling_type"] or "Consume"),
                    "station": str(r["station"] or ""),
                    "operation": str(r["operation"] or ""),
                    "part_number": replaces_part_number,
                    "is_replaced_part": True,
                })

        concern_items = []
        c_rows = conn.execute(
            """SELECT id, category, subject, priority, status
               FROM concerns
               WHERE project_id=? AND related_part=? AND status <> 'Closed'
               ORDER BY priority DESC""",
            (project_id, part_number),
        ).fetchall()
        for r in c_rows:
            concern_items.append({
                "id": str(r["id"]),
                "category": str(r["category"] or "Question"),
                "subject": str(r["subject"] or ""),
                "priority": str(r["priority"] or "Medium"),
                "status": str(r["status"] or "Open"),
            })

        replaces_concern_items = []
        if replaces_part_number:
            rc_rows = conn.execute(
                """SELECT id, category, subject, priority, status
                   FROM concerns
                   WHERE project_id=? AND related_part=? AND status <> 'Closed'
                   ORDER BY priority DESC""",
                (project_id, replaces_part_number),
            ).fetchall()
            for r in rc_rows:
                replaces_concern_items.append({
                    "id": str(r["id"]),
                    "category": str(r["category"] or "Question"),
                    "subject": str(r["subject"] or ""),
                    "priority": str(r["priority"] or "Medium"),
                    "status": str(r["status"] or "Open"),
                    "part_number": replaces_part_number,
                    "is_replaced_part": True,
                })

    return {
        "part_number": part_number,
        "is_existing": part_id is not None,
        "replaces_part_number": replaces_part_number or "",
        "fishbone": {
            "is_placed": len(fb_assignments) > 0,
            "count": len(fb_assignments),
            "assignments": fb_assignments,
            "replaces_count": len(replaces_fb_assignments),
            "replaces_assignments": replaces_fb_assignments,
        },
        "model_tree": {
            "occurrences": uploaded_occurrences if uploaded_occurrences else db_occurrences,
            "uploaded_count": len(uploaded_occurrences),
            "active_tree_count": len(db_occurrences),
            "replaces_count": len(replaces_db_occurrences),
            "replaces_occurrences": replaces_db_occurrences,
        },
        "yamazumi": {
            "count": len(yamazumi_elements),
            "elements": yamazumi_elements,
            "replaces_count": len(replaces_yamazumi_elements),
            "replaces_elements": replaces_yamazumi_elements,
        },
        "process": {
            "count": len(process_options),
            "options": process_options,
            "replaces_count": len(replaces_process_options),
            "replaces_options": replaces_process_options,
        },
        "concerns": {
            "count": len(concern_items),
            "items": concern_items,
            "replaces_count": len(replaces_concern_items),
            "replaces_items": replaces_concern_items,
        },
    }


def import_pits_id_snapshot(
    project_id: str,
    records: list[dict],
    models: list[dict],
    *,
    scenario_id: str | None = None,
    overwrite_manual: bool = False,
    bom_snapshot: dict | None = None,
    workbook_name: str = "",
    workbook_sha256: str = "",
    editor_name: str = "",
) -> dict:
    timestamp = now_iso()
    id_resolution = pits_catalog_id_resolution(records)
    unique_pits_id_by_part = id_resolution["resolved_ids"]
    linked_part_numbers: set[str] = set()
    summary = {
        "new": 0,
        "changed": 0,
        "unchanged": 0,
        "models": 0,
        "tracker_conflicts": 0,
        "pits_ids_linked": 0,
        "pits_ids_resolved_from_bom": len(id_resolution["resolved_from_bom"]),
        "pits_id_conflicts": len(id_resolution["unresolved_tracker_parts"]),
        "bom_pits_id_conflicts": len(id_resolution["multiple_bom_ids"]),
        "pits_id_missing_bom_matches": len(id_resolution["missing_bom_match"]),
        "pits_id_mismatched_bom_matches": len(id_resolution["mismatched_bom_match"]),
        "bom": None,
    }
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

        tracker_numbers, tracker_conflicts = _pits_tracker_number_claims(
            conn, project_id, records
        )
        summary["tracker_conflicts"] = len(tracker_conflicts)
        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM fishbone_nodes WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
        for record_index, record in enumerate(records):
            pits_id = str(record["pits_id"]).strip()
            part_number = str(record.get("part_number") or "").strip()
            catalog_pits_id = unique_pits_id_by_part.get(part_number, "")
            description = str(record.get("description") or "").strip()
            notes = str(record.get("comments") or "").strip()
            used_in_bom = str(record.get("used_bom") or "").strip().casefold() not in {"n", "no"}
            design_engineer = str(record.get("design_engineer") or record.get("technology_engineer") or "").strip()
            catalog_technology_engineer = (
                design_engineer
                if pits_id == catalog_pits_id
                else ""
            )
            ppm = str(record.get("ppm") or "").strip()
            buyer_gcl = str(record.get("buyer_gcl") or "").strip()
            pmqe_aqe = str(record.get("pmqe_aqe") or "").strip()
            ame_tooling_engineer = str(record.get("ame_tooling_engineer") or "").strip()
            part_code = str(record.get("part_code") or "").strip()
            subsystem = str(record.get("subsystem") or "").strip()
            if "revision" in record:
                revision = str(record.get("revision") or "").strip()
                design_maturity = str(record.get("design_maturity") or revision or "").strip()
            else:
                design_maturity = str(record.get("design_maturity") or "").strip()
                revision = design_maturity
            if part_number:
                if overwrite_manual:
                    update_clause = """ON CONFLICT(project_id, part_number) DO UPDATE SET
                       description=excluded.description, quantity=excluded.quantity,
                       revision=excluded.revision, design_maturity=excluded.design_maturity,
                       subsystem=CASE WHEN excluded.subsystem<>'' THEN excluded.subsystem ELSE parts.subsystem END,
                       source_code=excluded.source_code,
                       design_engineer=CASE WHEN excluded.technology_engineer<>'' THEN excluded.technology_engineer ELSE parts.design_engineer END,
                       technology_engineer=CASE WHEN excluded.technology_engineer<>'' THEN excluded.technology_engineer ELSE parts.technology_engineer END,
                       ppm=CASE WHEN excluded.ppm<>'' THEN excluded.ppm ELSE parts.ppm END,
                       buyer_gcl=CASE WHEN excluded.buyer_gcl<>'' THEN excluded.buyer_gcl ELSE parts.buyer_gcl END,
                       pmqe_aqe=CASE WHEN excluded.pmqe_aqe<>'' THEN excluded.pmqe_aqe ELSE parts.pmqe_aqe END,
                       ame_tooling_engineer=CASE WHEN excluded.ame_tooling_engineer<>'' THEN excluded.ame_tooling_engineer ELSE parts.ame_tooling_engineer END,
                       part_code=CASE WHEN excluded.part_code<>'' THEN excluded.part_code ELSE parts.part_code END,
                       source=excluded.source,
                       notes=CASE
                           WHEN TRIM(COALESCE(parts.notes, '')) <> '' THEN parts.notes
                           ELSE excluded.notes
                       END,
                       pits_tracker_number=CASE
                           WHEN excluded.pits_tracker_number<>'' THEN excluded.pits_tracker_number
                           ELSE parts.pits_tracker_number
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
                       design_maturity=CASE WHEN parts.source='PITS snapshot' OR TRIM(COALESCE(parts.design_maturity, '')) = '' THEN excluded.design_maturity ELSE parts.design_maturity END,
                       subsystem=CASE WHEN parts.source='PITS snapshot' OR TRIM(COALESCE(parts.subsystem, '')) = '' THEN excluded.subsystem ELSE parts.subsystem END,
                       source_code=CASE WHEN parts.source='PITS snapshot' THEN excluded.source_code ELSE parts.source_code END,
                       design_engineer=CASE
                           WHEN excluded.technology_engineer<>''
                            AND (parts.source='PITS snapshot' OR parts.design_engineer='')
                           THEN excluded.technology_engineer
                           ELSE parts.design_engineer
                       END,
                       technology_engineer=CASE
                           WHEN excluded.technology_engineer<>''
                            AND (parts.source='PITS snapshot' OR parts.technology_engineer='')
                           THEN excluded.technology_engineer
                           ELSE parts.technology_engineer
                       END,
                       ppm=CASE WHEN parts.source='PITS snapshot' OR TRIM(COALESCE(parts.ppm, '')) = '' THEN excluded.ppm ELSE parts.ppm END,
                       buyer_gcl=CASE WHEN parts.source='PITS snapshot' OR TRIM(COALESCE(parts.buyer_gcl, '')) = '' THEN excluded.buyer_gcl ELSE parts.buyer_gcl END,
                       pmqe_aqe=CASE WHEN parts.source='PITS snapshot' OR TRIM(COALESCE(parts.pmqe_aqe, '')) = '' THEN excluded.pmqe_aqe ELSE parts.pmqe_aqe END,
                       ame_tooling_engineer=CASE WHEN parts.source='PITS snapshot' OR TRIM(COALESCE(parts.ame_tooling_engineer, '')) = '' THEN excluded.ame_tooling_engineer ELSE parts.ame_tooling_engineer END,
                       part_code=CASE WHEN parts.source='PITS snapshot' OR TRIM(COALESCE(parts.part_code, '')) = '' THEN excluded.part_code ELSE parts.part_code END,
                       notes=CASE
                           WHEN TRIM(COALESCE(parts.notes, '')) <> '' THEN parts.notes
                           ELSE excluded.notes
                       END,
                       pits_tracker_number=CASE
                           WHEN excluded.pits_tracker_number<>''
                            AND (parts.source='PITS snapshot' OR parts.pits_tracker_number='')
                           THEN excluded.pits_tracker_number
                           ELSE parts.pits_tracker_number
                       END,
                       model_applicability=CASE
                           WHEN EXISTS (
                               SELECT 1 FROM part_feature_rules rule
                               WHERE rule.project_id=parts.project_id AND rule.part_id=parts.id
                           ) THEN parts.model_applicability
                           ELSE excluded.model_applicability
                       END,
                       updated_at=CASE WHEN parts.source='PITS snapshot' THEN excluded.updated_at ELSE parts.updated_at END"""
                if catalog_pits_id:
                    conn.execute(
                        """UPDATE parts SET pits_tracker_number=''
                           WHERE project_id=? AND pits_tracker_number=? AND part_number<>?""",
                        (project_id, catalog_pits_id, part_number),
                    )
                try:
                    conn.execute(
                        f"""INSERT INTO parts
                           (id, project_id, part_number, description, quantity, revision,
                            design_maturity, subsystem, source,
                            image_path, model_applicability, notes, pits_tracker_number,
                            source_code, design_engineer, technology_engineer, ppm, buyer_gcl,
                            pmqe_aqe, ame_tooling_engineer, part_code, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           {update_clause}""",
                        (
                            str(uuid4()), project_id, part_number, description,
                            record.get("quantity") if record.get("quantity") is not None else 1,
                            revision, design_maturity, subsystem,
                            "PITS snapshot", "All", notes, catalog_pits_id,
                            str(record.get("source_code") or "").strip(),
                            catalog_technology_engineer, catalog_technology_engineer, ppm, buyer_gcl, pmqe_aqe,
                            ame_tooling_engineer, part_code, timestamp,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    if "parts.project_id, parts.pits_tracker_number" in str(exc):
                        raise ValueError(
                            f"PITS ID {catalog_pits_id} is already assigned to another part in this project."
                        ) from exc
                    raise
                if catalog_pits_id:
                    linked_row = conn.execute(
                        """SELECT pits_tracker_number FROM parts
                           WHERE project_id=? AND part_number=?""",
                        (project_id, part_number),
                    ).fetchone()
                    if (
                        linked_row
                        and str(linked_row["pits_tracker_number"] or "").strip()
                        == catalog_pits_id
                    ):
                        linked_part_numbers.add(part_number)
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

        summary["pits_ids_linked"] = len(linked_part_numbers)
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
        if bom_snapshot and str(bom_snapshot.get("sheet_name") or "").strip():
            summary["bom"] = _import_pits_bom_snapshot(
                conn,
                project_id,
                bom_snapshot,
                workbook_name=workbook_name,
                workbook_sha256=workbook_sha256,
                editor_name=editor_name,
                timestamp=timestamp,
            )
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

G_FORMAT_REGEX = re.compile(r"G\d+", re.IGNORECASE)


def is_g_format_number(number_str: str) -> bool:
    """Return True if the given part or assembly number matches the Gxxx group pattern."""
    if not number_str:
        return False
    return bool(G_FORMAT_REGEX.search(str(number_str).strip()))


def model_bom_tree_nodes(
    project_id: str, model_id: str, include_staged: bool = True
) -> list[dict]:
    """Return the product structure tree for a model as an ordered list of nodes.

    Includes approved product structure sourced from assembly_sections,
    fishbone_part_assignments, and manufacturing_assembly_components.
    When include_staged is True, also weaves in unapproved PITS BOM occurrences
    marked with review_status='Needs review'.
    """
    with connection() as conn:
        model = conn.execute(
            "SELECT id, model_number, display_name FROM project_models WHERE id=? AND project_id=?",
            (model_id, project_id),
        ).fetchone()
        if not model:
            raise ValueError("The selected model does not exist in this project.")
        model_num = str(model["model_number"] or "").strip()

        sections = conn.execute(
            "SELECT id, name, sequence FROM assembly_sections WHERE project_id=? ORDER BY sequence",
            (project_id,),
        ).fetchall()
        section_name_map = {str(s["id"]): str(s["name"]) for s in sections}

        mappings = conn.execute(
            """SELECT m.id AS mapping_id, m.category_id, m.assembly_id,
                      c.ebom_name, c.display_name AS category_name, c.is_top_level,
                      c.section_id AS category_section_id, c.installed_section_id AS category_installed_section_id,
                      a.assembly_number, a.name AS assembly_name, a.catalog_part_id,
                      built.name AS built_section_name,
                      installed.name AS installed_section_name
               FROM assembly_grid_model_mappings m
               JOIN assembly_grid_categories c ON m.category_id = c.id
               JOIN manufacturing_assemblies a ON m.assembly_id = a.id
               LEFT JOIN assembly_sections built ON c.section_id = built.id
               LEFT JOIN assembly_sections installed ON c.installed_section_id = installed.id
               WHERE m.project_id=? AND m.model_id=?
               ORDER BY c.is_top_level DESC, c.sequence, c.display_name""",
            (project_id, model_id),
        ).fetchall()

        mapped_assembly_ids = [str(m["assembly_id"]) for m in mappings if m["assembly_id"]]
        comps_by_asm: dict[str, list[dict]] = {}
        if mapped_assembly_ids:
            placeholders = ",".join("?" for _ in mapped_assembly_ids)
            comp_rows = conn.execute(
                f"""SELECT c.id, c.assembly_id, c.quantity,
                           f.id AS assignment_id, f.use_description, f.pits_sync_status, f.pits_quantity_updated_at,
                           f.section_id, s.name AS section_name,
                           p.id AS part_id, p.part_number, p.description AS part_name,
                           child_asm.id AS nested_assembly_id, child_asm.assembly_number AS nested_assembly_number,
                           child_asm.built_section_id AS nested_built_section_id,
                           child_asm.installed_section_id AS nested_installed_section_id
                    FROM manufacturing_assembly_components c
                    JOIN fishbone_part_assignments f ON c.fishbone_assignment_id = f.id
                    JOIN parts p ON f.part_id = p.id
                    LEFT JOIN assembly_sections s ON f.section_id = s.id
                    LEFT JOIN manufacturing_assemblies child_asm
                      ON child_asm.catalog_part_id = p.id AND child_asm.project_id=?
                    WHERE c.assembly_id IN ({placeholders})
                    ORDER BY p.part_number""",
                (project_id, *mapped_assembly_ids),
            ).fetchall()
            for r in comp_rows:
                comps_by_asm.setdefault(str(r["assembly_id"]), []).append(dict(r))

        nested_asm_ids = [
            str(r["nested_assembly_id"])
            for clist in comps_by_asm.values()
            for r in clist
            if r.get("nested_assembly_id") and str(r["nested_assembly_id"]) not in comps_by_asm
        ]
        if nested_asm_ids:
            placeholders = ",".join("?" for _ in nested_asm_ids)
            nested_comp_rows = conn.execute(
                f"""SELECT c.id, c.assembly_id, c.quantity,
                           f.id AS assignment_id, f.use_description, f.pits_sync_status, f.pits_quantity_updated_at,
                           f.section_id, s.name AS section_name,
                           p.id AS part_id, p.part_number, p.description AS part_name,
                           NULL AS nested_assembly_id, NULL AS nested_assembly_number
                    FROM manufacturing_assembly_components c
                    JOIN fishbone_part_assignments f ON c.fishbone_assignment_id = f.id
                    JOIN parts p ON f.part_id = p.id
                    LEFT JOIN assembly_sections s ON f.section_id = s.id
                    WHERE c.assembly_id IN ({placeholders})
                    ORDER BY p.part_number""",
                tuple(nested_asm_ids),
            ).fetchall()
            for r in nested_comp_rows:
                comps_by_asm.setdefault(str(r["assembly_id"]), []).append(dict(r))

        fpa_rows = conn.execute(
            """SELECT f.id AS assignment_id, f.section_id, s.name AS section_name,
                      f.part_id, p.part_number, p.description AS part_name, p.model_applicability,
                      f.quantity, f.use_description, f.pits_sync_status, f.pits_quantity_updated_at
               FROM fishbone_part_assignments f
               JOIN parts p ON f.part_id = p.id
               LEFT JOIN assembly_sections s ON f.section_id = s.id
               WHERE f.project_id=?
               ORDER BY s.sequence, f.sequence""",
            (project_id,),
        ).fetchall()

        fpa_in_mapped_asm = {
            str(c["assignment_id"])
            for clist in comps_by_asm.values()
            for c in clist
            if c.get("assignment_id")
        }

        direct_fpa_by_section: dict[str, list[dict]] = {}
        for f in fpa_rows:
            f_dict = dict(f)
            if str(f_dict["assignment_id"]) in fpa_in_mapped_asm:
                continue
            app = str(f_dict.get("model_applicability") or "").strip() or "All"
            app_models = [x.strip() for x in app.split(",") if x.strip()]
            if "All" in app_models or "All models" in app_models or model_num in app_models:
                direct_fpa_by_section.setdefault(str(f_dict["section_id"]), []).append(f_dict)

        nodes: list[dict] = []

        def make_node(
            node_id: str,
            depth: int,
            parent_id: str | None,
            node_type: str,
            part_number: str,
            part_name: str,
            built_sec_id: str | None,
            built_sec_name: str | None,
            inst_sec_id: str | None,
            inst_sec_name: str | None,
            quantity: float,
            use_desc: str,
            pits_status: str,
            pits_updated_at: str,
            category_id: str | None = None,
            category_name: str = "",
            assembly_id: str | None = None,
            assignment_id: str | None = None,
            part_id: str | None = None,
            review_status: str = "Approved",
            occurrence_id: str | None = None,
            source_state: str = "",
        ) -> dict:
            p_num = str(part_number or "").strip()
            return {
                "id": node_id,
                "depth": depth,
                "parent_id": parent_id,
                "node_type": node_type,
                "part_number": p_num,
                "part_name": str(part_name or "").strip(),
                "built_section_id": str(built_sec_id or ""),
                "built_section_name": str(built_sec_name or ""),
                "installed_section_id": str(inst_sec_id or ""),
                "installed_section_name": str(inst_sec_name or ""),
                "quantity": float(quantity) if quantity is not None else 1.0,
                "use_description": str(use_desc or "").strip(),
                "pits_sync_status": str(pits_status or "Not linked"),
                "pits_quantity_updated_at": str(pits_updated_at or ""),
                "category_id": category_id,
                "category_name": category_name or "",
                "assembly_id": assembly_id,
                "assignment_id": assignment_id,
                "part_id": part_id,
                "is_g_format": is_g_format_number(p_num),
                "review_status": review_status,
                "occurrence_id": occurrence_id,
                "source_state": source_state,
            }

        top_level_mappings = [m for m in mappings if m["is_top_level"]]
        other_mappings = [m for m in mappings if not m["is_top_level"]]

        if top_level_mappings:
            for t in top_level_mappings:
                t_node_id = f"asm_{t['assembly_id']}"
                nodes.append(make_node(
                    t_node_id, 1, None, "Top-level packaged unit",
                    t["assembly_number"], t["assembly_name"] or t["category_name"],
                    t["category_section_id"], t["built_section_name"],
                    t["category_installed_section_id"], t["installed_section_name"],
                    1.0, "", "", "",
                    category_id=str(t["category_id"]), category_name=str(t["category_name"]),
                    assembly_id=str(t["assembly_id"]), part_id=str(t["catalog_part_id"] or ""),
                ))
                for m in other_mappings:
                    m_node_id = f"asm_{m['assembly_id']}"
                    cat_display = str(m["category_name"])
                    asm_display = str(m["assembly_name"] or "")
                    disp = f"{cat_display} ({asm_display})" if asm_display and asm_display != cat_display else cat_display
                    nodes.append(make_node(
                        m_node_id, 2, t_node_id, "Assembly",
                        m["assembly_number"], disp,
                        m["category_section_id"], m["built_section_name"],
                        m["category_installed_section_id"], m["installed_section_name"],
                        1.0, "", "", "",
                        category_id=str(m["category_id"]), category_name=str(m["category_name"]),
                        assembly_id=str(m["assembly_id"]), part_id=str(m["catalog_part_id"] or ""),
                    ))
                    for c in comps_by_asm.get(str(m["assembly_id"]), []):
                        c_node_id = f"comp_{c['id']}"
                        nodes.append(make_node(
                            c_node_id, 3, m_node_id, "Component",
                            c["part_number"], c["part_name"],
                            c["section_id"], c["section_name"],
                            "", "",
                            c["quantity"], c["use_description"], c["pits_sync_status"], c["pits_quantity_updated_at"],
                            assignment_id=str(c["assignment_id"]), part_id=str(c["part_id"]),
                        ))
                        nested_id = str(c.get("nested_assembly_id") or "")
                        if nested_id and nested_id in comps_by_asm:
                            for nc in comps_by_asm[nested_id]:
                                nc_node_id = f"nested_comp_{nc['id']}"
                                nodes.append(make_node(
                                    nc_node_id, 4, c_node_id, "Component",
                                    nc["part_number"], nc["part_name"],
                                    nc["section_id"], nc["section_name"],
                                    "", "",
                                    nc["quantity"], nc["use_description"], nc["pits_sync_status"], nc["pits_quantity_updated_at"],
                                    assignment_id=str(nc["assignment_id"]), part_id=str(nc["part_id"]),
                                ))
                for c in comps_by_asm.get(str(t["assembly_id"]), []):
                    c_node_id = f"comp_{c['id']}"
                    nodes.append(make_node(
                        c_node_id, 2, t_node_id, "Component",
                        c["part_number"], c["part_name"],
                        c["section_id"], c["section_name"],
                        "", "",
                        c["quantity"], c["use_description"], c["pits_sync_status"], c["pits_quantity_updated_at"],
                        assignment_id=str(c["assignment_id"]), part_id=str(c["part_id"]),
                    ))
        elif other_mappings:
            for m in other_mappings:
                m_node_id = f"asm_{m['assembly_id']}"
                cat_display = str(m["category_name"])
                asm_display = str(m["assembly_name"] or "")
                disp = f"{cat_display} ({asm_display})" if asm_display and asm_display != cat_display else cat_display
                nodes.append(make_node(
                    m_node_id, 1, None, "Assembly",
                    m["assembly_number"], disp,
                    m["category_section_id"], m["built_section_name"],
                    m["category_installed_section_id"], m["installed_section_name"],
                    1.0, "", "", "",
                    category_id=str(m["category_id"]), category_name=str(m["category_name"]),
                    assembly_id=str(m["assembly_id"]), part_id=str(m["catalog_part_id"] or ""),
                ))
                for c in comps_by_asm.get(str(m["assembly_id"]), []):
                    c_node_id = f"comp_{c['id']}"
                    nodes.append(make_node(
                        c_node_id, 2, m_node_id, "Component",
                        c["part_number"], c["part_name"],
                        c["section_id"], c["section_name"],
                        "", "",
                        c["quantity"], c["use_description"], c["pits_sync_status"], c["pits_quantity_updated_at"],
                        assignment_id=str(c["assignment_id"]), part_id=str(c["part_id"]),
                    ))
                    nested_id = str(c.get("nested_assembly_id") or "")
                    if nested_id and nested_id in comps_by_asm:
                        for nc in comps_by_asm[nested_id]:
                            nc_node_id = f"nested_comp_{nc['id']}"
                            nodes.append(make_node(
                                nc_node_id, 3, c_node_id, "Component",
                                nc["part_number"], nc["part_name"],
                                nc["section_id"], nc["section_name"],
                                "", "",
                                nc["quantity"], nc["use_description"], nc["pits_sync_status"], nc["pits_quantity_updated_at"],
                                assignment_id=str(nc["assignment_id"]), part_id=str(nc["part_id"]),
                            ))

        if direct_fpa_by_section:
            for sec_id, fpa_list in direct_fpa_by_section.items():
                sec_name = fpa_list[0].get("section_name") or section_name_map.get(sec_id, "Fishbone Section")
                sec_node_id = f"sec_{sec_id}"
                nodes.append(make_node(
                    sec_node_id, 1 if not top_level_mappings else 2, None, "Fishbone Section",
                    sec_name, f"Section ({len(fpa_list)} parts)",
                    sec_id, sec_name, "", "",
                    float(len(fpa_list)), "", "", "",
                ))
                for f in fpa_list:
                    f_node_id = f"fpa_{f['assignment_id']}"
                    nodes.append(make_node(
                        f_node_id, 2 if not top_level_mappings else 3, sec_node_id, "Fishbone Part",
                        f["part_number"], f["part_name"],
                        f["section_id"], sec_name, "", "",
                        f["quantity"], f["use_description"], f["pits_sync_status"], f["pits_quantity_updated_at"],
                        assignment_id=str(f["assignment_id"]), part_id=str(f["part_id"]),
                    ))

        if include_staged:
            staged_rows = conn.execute(
                """SELECT o.id, o.proposed_depth, o.parent_tracker_number, o.child_tracker_number,
                          o.parent_part_id, o.child_part_id, o.proposed_quantity,
                          o.source_state, o.review_status,
                          p.part_number, p.description AS part_name, p.model_applicability
                   FROM pits_bom_occurrences o
                   LEFT JOIN parts p ON o.child_part_id = p.id
                   WHERE o.project_id=? AND o.review_status='Needs review'
                   ORDER BY o.source_row""",
                (project_id,),
            ).fetchall()

            if staged_rows:
                clean_m = re.sub(r"[^A-Za-z0-9]", "", model_num).upper()
                l1_occurrences = [s for s in staged_rows if s["proposed_depth"] == 1]
                matched_l1 = None
                for l1 in l1_occurrences:
                    desc = re.sub(r"[^A-Za-z0-9]", "", str(l1["part_name"] or "")).upper()
                    pnum = re.sub(r"[^A-Za-z0-9]", "", str(l1["part_number"] or "")).upper()
                    if clean_m in desc or clean_m in pnum or (len(clean_m) >= 6 and clean_m[:6] in desc):
                        matched_l1 = l1
                        break

                relevant_staged: list[sqlite3.Row] = []
                seen_occ_ids: set[str] = set()
                if matched_l1:
                    by_parent_tracker: dict[str, list[sqlite3.Row]] = {}
                    for s in staged_rows:
                        p_trk = str(s["parent_tracker_number"] or "").strip()
                        by_parent_tracker.setdefault(p_trk, []).append(s)

                    frontier = [str(matched_l1["child_tracker_number"])]
                    relevant_staged.append(matched_l1)
                    seen_occ_ids.add(str(matched_l1["id"]))
                    while frontier:
                        nxt = []
                        for t in frontier:
                            for c in by_parent_tracker.get(t, []):
                                c_id = str(c["id"])
                                if c_id not in seen_occ_ids:
                                    seen_occ_ids.add(c_id)
                                    relevant_staged.append(c)
                                    c_trk = str(c["child_tracker_number"] or "").strip()
                                    if c_trk:
                                        nxt.append(c_trk)
                        frontier = nxt

                    if len(relevant_staged) == 1 and by_parent_tracker:
                        largest_trk = max(by_parent_tracker.keys(), key=lambda k: len(by_parent_tracker[k]) if k else 0)
                        if largest_trk:
                            frontier = [largest_trk]
                            while frontier:
                                nxt = []
                                for t in frontier:
                                    for c in by_parent_tracker.get(t, []):
                                        c_id = str(c["id"])
                                        if c_id not in seen_occ_ids:
                                            seen_occ_ids.add(c_id)
                                            relevant_staged.append(c)
                                            c_trk = str(c["child_tracker_number"] or "").strip()
                                            if c_trk:
                                                nxt.append(c_trk)
                                frontier = nxt
                else:
                    for s in staged_rows:
                        c_id = str(s["id"])
                        if c_id not in seen_occ_ids:
                            app = str(s["model_applicability"] or "").strip() or "All"
                            app_models = [x.strip() for x in app.split(",") if x.strip()]
                            if "All" in app_models or "All models" in app_models or model_num in app_models:
                                seen_occ_ids.add(c_id)
                                relevant_staged.append(s)

                for s in relevant_staged:
                    is_g = is_g_format_number(s["part_number"])
                    p_depth = int(s["proposed_depth"] or 2)
                    nodes.append(make_node(
                        f"occ_{s['id']}",
                        p_depth,
                        None,
                        "Assembly" if is_g else "Component",
                        s["part_number"] or s["child_tracker_number"],
                        s["part_name"] or "",
                        "", "", "", "",
                        s["proposed_quantity"] or 1.0,
                        f"PITS {s['parent_tracker_number'] or 'root'} → {s['child_tracker_number']}",
                        "Needs review", "",
                        part_id=str(s["child_part_id"] or ""),
                        review_status="Needs review",
                        occurrence_id=str(s["id"]),
                        source_state=str(s["source_state"] or "New"),
                    ))

        return nodes


def pits_bom_model_tree(project_id: str, model_id: str | None = None) -> dict[str, Any]:
    """Retrieve the PITS BOM tree structure with reconciliation status against Parts Catalog and Fishbone.

    Returns a dict containing:
      - 'roots': list of root node dicts (hierarchically containing 'children')
      - 'nodes': flat list of all nodes in tree traversal order
      - 'metrics': dict with counts of total, placed_fishbone, missing_fishbone, missing_catalog
      - 'target_model': model number if filtered by model, else None
    """
    with connection() as conn:
        occ_rows = conn.execute(
            """
            SELECT o.id, o.proposed_depth, o.parent_tracker_number, o.child_tracker_number,
                   o.parent_part_id, o.child_part_id, o.proposed_quantity, o.raw_quantity_text,
                   o.source_row, o.raw_levels_json, o.review_status, o.source_state,
                   p.part_number, p.description, p.weight_lb, p.make_buy,
                   p.subsystem, p.design_maturity, p.revision,
                   p.technology_engineer, p.design_engineer, p.source_code, p.model_applicability,
                   p.official_windchill_part_name, p.factory_nickname,
                   p.ppm, p.buyer_gcl, p.pmqe_aqe, p.ame_tooling_engineer, p.part_code,
                   COALESCE(NULLIF(TRIM(p.image_path), ''), (
                       SELECT pi.image_path FROM part_images pi WHERE pi.part_id = p.id ORDER BY pi.created_at, pi.id LIMIT 1
                   ), '') AS image_path
            FROM pits_bom_occurrences o
            LEFT JOIN parts p ON p.id = o.child_part_id
            WHERE o.project_id = ?
            ORDER BY o.source_row
            """,
            (project_id,),
        ).fetchall()

        if not occ_rows:
            return {
                "roots": [],
                "nodes": [],
                "metrics": {
                    "total": 0,
                    "placed_fishbone": 0,
                    "missing_fishbone": 0,
                    "missing_catalog": 0,
                },
                "target_model": None,
            }

        fb_rows = conn.execute(
            """
            SELECT a.part_id, s.name as section_name, a.use_description, a.quantity
            FROM fishbone_part_assignments a
            JOIN assembly_sections s ON s.id = a.section_id
            WHERE a.project_id = ?
            """,
            (project_id,),
        ).fetchall()

        fb_by_part: dict[str, list[dict[str, Any]]] = {}
        for r in fb_rows:
            pid = str(r["part_id"])
            if pid not in fb_by_part:
                fb_by_part[pid] = []
            fb_by_part[pid].append({
                "section": r["section_name"],
                "use": r["use_description"],
                "quantity": r["quantity"],
            })

        parsed_rows: list[dict[str, Any]] = []
        has_any_model_usages = False
        all_model_keys: set[str] = set()

        for r in occ_rows:
            usages: dict[str, float] = {}
            data: dict[str, Any] = {}
            if r["raw_levels_json"]:
                try:
                    data = json.loads(r["raw_levels_json"])
                    if isinstance(data, dict):
                        u = data.get("model_usages")
                        if isinstance(u, dict):
                            usages = {str(k): float(v) for k, v in u.items() if v is not None}
                except Exception:
                    data = {}
            if usages:
                has_any_model_usages = True
                all_model_keys.update(usages.keys())
            parsed_rows.append({"r": r, "usages": usages, "data": data})

        target_model = None
        if model_id and model_id != "all":
            m_row = conn.execute(
                "SELECT model_number FROM project_models WHERE id=? AND project_id=?",
                (model_id, project_id),
            ).fetchone()
            if m_row:
                target_model = m_row["model_number"]
            else:
                target_model = model_id

        # Case A: Model-specific tree using PITS model usages
        if target_model and has_any_model_usages:
            clean_target = re.sub(r"[^A-Za-z0-9]", "", target_model).upper()
            matched_model_key = None
            # 1. Exact match has priority
            for mk in all_model_keys:
                if mk == target_model or re.sub(r"[^A-Za-z0-9]", "", mk).upper() == clean_target:
                    matched_model_key = mk
                    break
            # 2. Fuzzy/prefix match only as fallback
            if not matched_model_key:
                for mk in all_model_keys:
                    clean_mk = re.sub(r"[^A-Za-z0-9]", "", mk).upper()
                    if (len(clean_target) >= 6 and clean_target[:6] in clean_mk) or (len(clean_mk) >= 6 and clean_mk[:6] in clean_target):
                        matched_model_key = mk
                        break

            qualifying_nodes: list[dict[str, Any]] = []
            stack: dict[int, dict[str, Any]] = {}

            for pr in parsed_rows:
                r = pr["r"]
                usages = pr["usages"]
                pr_data = pr.get("data") or {}

                model_qty = None
                if target_model in usages:
                    model_qty = usages[target_model]
                elif matched_model_key and matched_model_key in usages:
                    model_qty = usages[matched_model_key]
                else:
                    for mk, q in usages.items():
                        if re.sub(r"[^A-Za-z0-9]", "", str(mk)).upper() == clean_target:
                            model_qty = q
                            break
                    if model_qty is None:
                        for mk, q in usages.items():
                            clean_mk = re.sub(r"[^A-Za-z0-9]", "", str(mk)).upper()
                            if (len(clean_target) >= 6 and clean_target[:6] in clean_mk) or (len(clean_mk) >= 6 and clean_mk[:6] in clean_target):
                                model_qty = q
                                break

                # If this row is not used on this model, skip it
                if model_qty is None or float(model_qty) <= 0:
                    continue

                pid = str(r["child_part_id"]) if r["child_part_id"] else None
                in_catalog = pid is not None
                fb_info = fb_by_part.get(pid, []) if pid else []
                in_fishbone = len(fb_info) > 0

                p_num = r["part_number"] or pr_data.get("part_number") or (
                    f"Uncataloged (Tracker #{r['child_tracker_number']})" if r["child_tracker_number"] else "—"
                )
                p_desc = r["description"] or pr_data.get("description") or "—"
                depth = int(r["proposed_depth"] or 1)

                node: dict[str, Any] = {
                    "id": str(r["id"]),
                    "part_id": pid,
                    "depth": depth,
                    "parent_tracker": "",
                    "child_tracker": str(r["child_tracker_number"] or "").strip(),
                    "part_number": p_num,
                    "description": p_desc,
                    "quantity": round(float(model_qty), 5),
                    "raw_quantity_text": str(round(float(model_qty), 5)),
                    "in_catalog": in_catalog,
                    "in_fishbone": in_fishbone,
                    "fishbone_sections": [x["section"] for x in fb_info],
                    "fishbone_uses": [x["use"] for x in fb_info if x["use"]],
                    "weight_lb": r["weight_lb"],
                    "make_buy": r["make_buy"],
                    "subsystem": str(r["subsystem"] or ""),
                    "design_maturity": str(r["design_maturity"] or r["revision"] or ""),
                    "revision": str(r["design_maturity"] or r["revision"] or ""),
                    "technology_engineer": r["technology_engineer"],
                    "design_engineer": r["design_engineer"] or r["technology_engineer"],
                    "source_code": r["source_code"],
                    "official_name": r["official_windchill_part_name"],
                    "factory_nickname": r["factory_nickname"] or r["official_windchill_part_name"],
                    "ppm": r["ppm"],
                    "buyer_gcl": r["buyer_gcl"],
                    "pmqe_aqe": r["pmqe_aqe"],
                    "ame_tooling_engineer": r["ame_tooling_engineer"],
                    "part_code": r["part_code"],
                    "model_applicability": r["model_applicability"],
                    "image_path": str(r["image_path"] or ""),
                    "source_state": r["source_state"],
                    "review_status": r["review_status"],
                    "source_row": r["source_row"],
                    "children": [],
                }

                # Outline rule: parent is the level right above the child
                parent_node = stack.get(depth - 1)
                if parent_node:
                    parent_node["children"].append(node)
                    node["parent_tracker"] = parent_node["child_tracker"]

                stack[depth] = node
                stack = {lvl: n for lvl, n in stack.items() if lvl <= depth}
                qualifying_nodes.append(node)

            all_roots = [n for n in qualifying_nodes if n["depth"] == 1 or not n["parent_tracker"]]
            # Prioritize active roots that have children (e.g. main assembly BOM)
            active_roots = [rt for rt in all_roots if len(rt["children"]) > 0] or all_roots

            reachable_nodes: list[dict[str, Any]] = []
            seen_ids: set[str] = set()

            def collect_model(n: dict[str, Any]) -> None:
                if n["id"] in seen_ids:
                    return
                seen_ids.add(n["id"])
                reachable_nodes.append(n)
                for c in n["children"]:
                    collect_model(c)

            for root_item in active_roots:
                collect_model(root_item)

            metrics = {
                "total": len(reachable_nodes),
                "placed_fishbone": sum(1 for n in reachable_nodes if n["in_fishbone"]),
                "missing_fishbone": sum(1 for n in reachable_nodes if not n["in_fishbone"]),
                "missing_catalog": sum(1 for n in reachable_nodes if not n["in_catalog"]),
            }

            return {
                "roots": active_roots,
                "nodes": reachable_nodes,
                "metrics": metrics,
                "target_model": target_model,
            }

        # Case B: Master BOM or legacy data without model usages
        all_nodes: list[dict[str, Any]] = []
        stack_b: dict[int, dict[str, Any]] = {}
        children_map: dict[str, list[dict[str, Any]]] = {}

        for pr in parsed_rows:
            r = pr["r"]
            pid = str(r["child_part_id"]) if r["child_part_id"] else None
            in_catalog = pid is not None
            fb_info = fb_by_part.get(pid, []) if pid else []
            in_fishbone = len(fb_info) > 0

            pr_data = pr.get("data") or {}
            p_num = r["part_number"] or pr_data.get("part_number") or (
                f"Uncataloged (Tracker #{r['child_tracker_number']})" if r["child_tracker_number"] else "—"
            )
            p_desc = r["description"] or pr_data.get("description") or "—"
            depth = int(r["proposed_depth"] or 1)

            node: dict[str, Any] = {
                "id": str(r["id"]),
                "part_id": pid,
                "depth": depth,
                "parent_tracker": str(r["parent_tracker_number"] or "").strip(),
                "child_tracker": str(r["child_tracker_number"] or "").strip(),
                "part_number": p_num,
                "description": p_desc,
                "quantity": r["proposed_quantity"] if r["proposed_quantity"] is not None else (r["raw_quantity_text"] or 1),
                "raw_quantity_text": str(r["raw_quantity_text"] or ""),
                "in_catalog": in_catalog,
                "in_fishbone": in_fishbone,
                "fishbone_sections": [x["section"] for x in fb_info],
                "fishbone_uses": [x["use"] for x in fb_info if x["use"]],
                "weight_lb": r["weight_lb"],
                "make_buy": r["make_buy"],
                "subsystem": str(r["subsystem"] or ""),
                "design_maturity": str(r["design_maturity"] or r["revision"] or ""),
                "revision": str(r["design_maturity"] or r["revision"] or ""),
                "technology_engineer": r["technology_engineer"],
                "design_engineer": r["design_engineer"] or r["technology_engineer"],
                "source_code": r["source_code"],
                "official_name": r["official_windchill_part_name"],
                "factory_nickname": r["factory_nickname"] or r["official_windchill_part_name"],
                "ppm": r["ppm"],
                "buyer_gcl": r["buyer_gcl"],
                "pmqe_aqe": r["pmqe_aqe"],
                "ame_tooling_engineer": r["ame_tooling_engineer"],
                "part_code": r["part_code"],
                "model_applicability": r["model_applicability"],
                "image_path": str(r["image_path"] or ""),
                "source_state": r["source_state"],
                "review_status": r["review_status"],
                "source_row": r["source_row"],
                "children": [],
            }
            all_nodes.append(node)

            if has_any_model_usages:
                # Outline stack hierarchy for Master BOM
                parent_node = stack_b.get(depth - 1)
                if parent_node:
                    parent_node["children"].append(node)
                    node["parent_tracker"] = parent_node["child_tracker"]
                stack_b[depth] = node
                stack_b = {lvl: n for lvl, n in stack_b.items() if lvl <= depth}
            else:
                # Legacy parent_tracker mapping
                p_tr = node["parent_tracker"]
                if p_tr not in children_map:
                    children_map[p_tr] = []
                children_map[p_tr].append(node)

        if not has_any_model_usages:
            for node in all_nodes:
                c_tr = node["child_tracker"]
                if c_tr in children_map:
                    node["children"] = children_map[c_tr]

        roots = [n for n in all_nodes if not n["parent_tracker"] or n["depth"] == 1]
        if not roots and all_nodes:
            roots = all_nodes

        filtered_roots = roots
        if target_model:
            clean_m = re.sub(r"[^A-Za-z0-9]", "", target_model).upper()
            matched = [
                rt
                for rt in roots
                if clean_m in re.sub(r"[^A-Za-z0-9]", "", rt["description"]).upper()
                or clean_m in re.sub(r"[^A-Za-z0-9]", "", rt["part_number"]).upper()
                or (len(clean_m) >= 6 and clean_m[:6] in re.sub(r"[^A-Za-z0-9]", "", rt["description"]).upper())
            ]
            if matched:
                filtered_roots = matched

        reachable_nodes = []
        seen_ids = set()

        def collect(n: dict[str, Any]) -> None:
            if n["id"] in seen_ids:
                return
            seen_ids.add(n["id"])
            reachable_nodes.append(n)
            for c in n["children"]:
                collect(c)

        for rt in filtered_roots:
            collect(rt)

        if not reachable_nodes and all_nodes:
            reachable_nodes = all_nodes

        metrics = {
            "total": len(reachable_nodes),
            "placed_fishbone": sum(1 for n in reachable_nodes if n["in_fishbone"]),
            "missing_fishbone": sum(1 for n in reachable_nodes if not n["in_fishbone"]),
            "missing_catalog": sum(1 for n in reachable_nodes if not n["in_catalog"]),
        }

        return {
            "roots": filtered_roots,
            "nodes": reachable_nodes,
            "metrics": metrics,
            "target_model": target_model,
        }


def pits_assembly_mini_bom(
    project_id: str,
    part_id: str = "",
    part_number: str = "",
    pits_tracker_number: str = "",
) -> pd.DataFrame:
    """Returns an indented Mini-BOM dataframe for parts contained within an assembly from PITS BOM occurrences.

    Matches the assembly in pits_bom_occurrences by:
      1. child_part_id = part_id, or child_tracker_number = pits_tracker_number, or parts.part_number = part_number.
      2. verifies whether this occurrence has children (either subsequent rows in source_row order with
         proposed_depth > base_depth, or rows with parent_tracker_number matching this part's child_tracker_number).
      3. if matched, extracts all descendant occurrences in the assembly's subtree (until proposed_depth <= base_depth)
         and returns an indented hierarchy dataframe with tree-formatted part numbers, descriptions, quantities,
         levels, tracker numbers, and make/buy info.
    """
    if not project_id:
        return pd.DataFrame()

    with connection() as conn:
        occ_rows = conn.execute(
            """SELECT o.source_row, o.proposed_depth, o.child_tracker_number
               FROM pits_bom_occurrences o
               LEFT JOIN parts p ON p.id = o.child_part_id
               WHERE o.project_id = ?
                 AND (
                   (? <> '' AND o.child_part_id = ?)
                   OR (? <> '' AND o.child_tracker_number = ?)
                   OR (? <> '' AND p.part_number = ?)
                 )
               ORDER BY o.source_row""",
            (
                project_id,
                part_id, part_id,
                pits_tracker_number, pits_tracker_number,
                part_number, part_number,
            ),
        ).fetchall()

        matched_occ = None
        for r in occ_rows:
            sr, d, tr = int(r["source_row"]), int(r["proposed_depth"]), str(r["child_tracker_number"] or "").strip()
            next_r = conn.execute(
                """SELECT proposed_depth FROM pits_bom_occurrences
                   WHERE project_id = ? AND source_row > ?
                   ORDER BY source_row LIMIT 1""",
                (project_id, sr),
            ).fetchone()
            if next_r and int(next_r["proposed_depth"]) > d:
                matched_occ = (sr, d, tr)
                break
            if tr:
                has_child = conn.execute(
                    """SELECT 1 FROM pits_bom_occurrences
                       WHERE project_id = ? AND parent_tracker_number = ? LIMIT 1""",
                    (project_id, tr),
                ).fetchone()
                if has_child:
                    matched_occ = (sr, d, tr)
                    break

        if not matched_occ and pits_tracker_number:
            p_children = conn.execute(
                """SELECT min(source_row), min(proposed_depth)
                   FROM pits_bom_occurrences
                   WHERE project_id = ? AND parent_tracker_number = ?""",
                (project_id, pits_tracker_number),
            ).fetchone()
            if p_children and p_children[0] is not None:
                min_sr, min_d = int(p_children[0]), int(p_children[1])
                matched_occ = (min_sr - 1, min_d - 1, pits_tracker_number)

        if not matched_occ:
            return pd.DataFrame()

        base_sr, base_d, _ = matched_occ
        slice_rows = conn.execute(
            """SELECT o.id, o.source_row, o.proposed_depth, o.parent_tracker_number, o.child_tracker_number,
                      o.proposed_quantity, o.raw_quantity_text,
                      p.id AS part_id, p.part_number, p.description, p.make_buy, p.subsystem,
                      p.design_maturity, p.revision, p.part_code
               FROM pits_bom_occurrences o
               LEFT JOIN parts p ON p.id = o.child_part_id
               WHERE o.project_id = ? AND o.source_row > ?
               ORDER BY o.source_row""",
            (project_id, base_sr),
        ).fetchall()

        result_rows = []
        for r in slice_rows:
            d = int(r["proposed_depth"])
            if d <= base_d:
                break
            rel_depth = d - base_d
            indent = "　" * (rel_depth - 1)
            pn = str(r["part_number"] or "").strip()
            if not pn:
                pn = f"Tracker #{r['child_tracker_number']}" if r["child_tracker_number"] else "—"
            tree_pn = f"{indent}↳ {pn}" if rel_depth > 1 else pn
            qty = r["proposed_quantity"] if r["proposed_quantity"] is not None else (r["raw_quantity_text"] or 1)
            result_rows.append({
                "occurrence_id": str(r["id"]),
                "part_id": str(r["part_id"] or ""),
                "tree_part_number": tree_pn,
                "part_number": pn,
                "part_name": str(r["description"] or "—"),
                "quantity": qty,
                "level": f"L{d}",
                "tracker_number": f"#{r['child_tracker_number']}" if r["child_tracker_number"] else "—",
                "make_buy": str(r["make_buy"] or "—"),
                "part_code": str(r["part_code"] or "—"),
                "subsystem": str(r["subsystem"] or "—"),
                "design_maturity": str(r["design_maturity"] or r["revision"] or "—"),
                "depth": d,
                "rel_depth": rel_depth,
            })

        return pd.DataFrame(result_rows)


def sort_bom_hierarchy(
    raw_items: list[dict[str, Any]],
    model_number: str = "",
) -> list[dict[str, Any]]:
    """Sort BOM items in strict hierarchical tree order (depth-first pre-order traversal).

    Guarantees:
    - Parent assemblies and group numbers always appear before their child components.
    - Child components never appear above their group number.
    - Levels naturally progress (1 -> 2 -> 3) and never jump (1 -> 3 -> 2).
    - Preserves sibling order using model-specific sequence or source_row.
    """
    if not raw_items or len(raw_items) <= 1:
        return [dict(it) for it in raw_items]

    # Assign an initial index to guarantee stable sorting among siblings
    for i, it in enumerate(raw_items):
        it["_orig_idx"] = i

    all_child_trackers = {
        str(it.get("child_tracker") or it.get("part_number") or "").strip().upper()
        for it in raw_items
        if it.get("child_tracker") or it.get("part_number")
    }

    def _sort_key(node: dict[str, Any]) -> tuple:
        seq = node.get("model_seq")
        s_row = node.get("source_row")
        return (
            0 if seq is not None else 1,
            seq if seq is not None else (s_row if s_row is not None else 0),
            node.get("_orig_idx", 0),
        )

    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []

    for it in raw_items:
        pt = str(it.get("parent_tracker") or "").strip()
        lvl = int(it.get("level", 1) or 1)
        # Root if level 1, or empty parent tracker, or parent tracker not present in this set of items
        if lvl == 1 or not pt or pt.upper() not in all_child_trackers:
            roots.append(it)
        else:
            pt_clean = pt.upper()
            if pt_clean not in children_by_parent:
                children_by_parent[pt_clean] = []
            children_by_parent[pt_clean].append(it)

    roots.sort(key=_sort_key)
    for pt_clean in children_by_parent:
        children_by_parent[pt_clean].sort(key=_sort_key)

    ordered: list[dict[str, Any]] = []
    visited: set[Any] = set()

    def _traverse(node: dict[str, Any], current_depth: int) -> None:
        oid = node.get("occurrence_id") or node.get("_uid") or node["_orig_idx"]
        if oid in visited:
            return
        visited.add(oid)

        node_copy = dict(node)
        node_copy["level"] = max(1, min(11, current_depth))
        node_copy.pop("_orig_idx", None)
        ordered.append(node_copy)

        ct = str(node.get("child_tracker") or node.get("part_number") or "").strip().upper()
        # Direct children by child_tracker
        children = children_by_parent.get(ct, [])
        for ch in children:
            _traverse(ch, current_depth + 1)

    for r in roots:
        _traverse(r, 1)

    # Any remaining unvisited items (e.g. disconnected nodes) are appended in original order
    for it in raw_items:
        oid = it.get("occurrence_id") or it.get("_uid") or it["_orig_idx"]
        if oid not in visited:
            node_copy = dict(it)
            node_copy.pop("_orig_idx", None)
            ordered.append(node_copy)

    # Final pass: normalize levels to guarantee no row skips (e.g. curr_lvl <= prev_lvl + 1)
    if ordered:
        ordered[0]["level"] = 1
        for i in range(1, len(ordered)):
            prev_l = ordered[i - 1]["level"]
            curr_l = ordered[i]["level"]
            if curr_l > prev_l + 1:
                ordered[i]["level"] = prev_l + 1

    return ordered


def get_manual_model_bom(
    project_id: str,
    model_id: str,
    _conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Retrieve editable BOM items for the selected official model in source row order."""
    def _execute(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        m_row = conn.execute(
            "SELECT id, model_number FROM project_models WHERE id=? AND project_id=?",
            (model_id, project_id),
        ).fetchone()
        if not m_row:
            return []
        model_number = str(m_row["model_number"]).strip()
        target_model = model_number
        clean_target = re.sub(r"[^A-Za-z0-9]", "", model_number).upper()

        occ_rows = conn.execute(
            """
            SELECT o.id, o.proposed_depth, o.parent_tracker_number, o.child_tracker_number,
                   o.parent_part_id, o.child_part_id, o.proposed_quantity, o.raw_quantity_text,
                   o.source_row, o.raw_levels_json, o.source_state,
                   p.part_number, p.description
            FROM pits_bom_occurrences o
            LEFT JOIN parts p ON p.id = o.child_part_id
            WHERE o.project_id = ?
            ORDER BY o.source_row ASC, o.id ASC
            """,
            (project_id,),
        ).fetchall()

        results: list[dict[str, Any]] = []
        for r in occ_rows:
            usages: dict[str, float] = {}
            group_num = ""
            data: dict[str, Any] = {}
            raw_levels_str = r["raw_levels_json"]
            if raw_levels_str:
                try:
                    data = json.loads(raw_levels_str)
                    if isinstance(data, dict):
                        u = data.get("model_usages")
                        if isinstance(u, dict):
                            usages = {str(k): float(v) for k, v in u.items() if v is not None}
                        group_num = str(data.get("group_number") or "")
                except Exception:
                    data = {}

            # Match model usage
            model_qty = None
            if usages:
                # 1. Exact match
                if target_model in usages:
                    model_qty = usages[target_model]
                else:
                    for mk, q in usages.items():
                        if re.sub(r"[^A-Za-z0-9]", "", str(mk)).upper() == clean_target:
                            model_qty = q
                            break
                    if model_qty is None:
                        for mk, q in usages.items():
                            clean_mk = re.sub(r"[^A-Za-z0-9]", "", str(mk)).upper()
                            if (len(clean_target) >= 6 and clean_target[:6] in clean_mk) or (len(clean_mk) >= 6 and clean_mk[:6] in clean_target):
                                model_qty = q
                                break
            elif data and "model_usages" in data:
                # model_usages was explicitly configured on this occurrence, but this model is not used on it!
                model_qty = None
            else:
                # Occurrences with no explicit model_usages (legacy or master occurrences)
                model_qty = r["proposed_quantity"] if r["proposed_quantity"] is not None else 1.0

            if model_qty is None or float(model_qty) <= 0:
                continue

            p_num = str(r["part_number"] or data.get("part_number") or r["child_tracker_number"] or "").strip()
            desc = str(r["description"] or data.get("description") or "").strip()
            depth = int(r["proposed_depth"] or 1)

            # Check if data has model_sequence
            seq = None
            if isinstance(data, dict):
                ms = data.get("model_sequence")
                if isinstance(ms, dict):
                    if target_model in ms:
                        seq = ms[target_model]
                    else:
                        for mk, val in ms.items():
                            if re.sub(r"[^A-Za-z0-9]", "", str(mk)).upper() == clean_target:
                                seq = val
                                break

            results.append({
                "level": depth,
                "group_number": group_num,
                "part_number": p_num,
                "description": desc,
                "quantity": round(float(model_qty), 5),
                "child_tracker": str(r["child_tracker_number"] or "").strip(),
                "parent_tracker": str(r["parent_tracker_number"] or "").strip(),
                "occurrence_id": str(r["id"]),
                "source_row": int(r["source_row"] or 0),
                "model_seq": seq,
            })

        return sort_bom_hierarchy(results, model_number=target_model)

    if _conn is not None:
        return _execute(_conn)
    with connection() as conn:
        return _execute(conn)


def get_known_subassembly_structure(
    project_id: str,
    part_number: str,
    max_depth: int = 5,
    _conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Find known child components for a part_number defined in pits_bom_occurrences across the project.

    Uses recursive Pre-order Depth-First Search (DFS) so subassemblies are immediately followed
    by their own child components and sub-tier parts in proper tree hierarchy.

    Returns a list of dicts:
    [{'part_number': str, 'description': str, 'quantity': float, 'relative_level': int, 'parent_tracker': str, 'child_tracker': str}]
    """
    clean_pn = str(part_number or "").strip()
    if not clean_pn:
        return []

    def _execute(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        part_row = conn.execute(
            "SELECT id FROM parts WHERE project_id=? AND UPPER(part_number)=UPPER(?)",
            (project_id, clean_pn),
        ).fetchone()
        part_id = None
        if part_row:
            part_id = str(part_row["id"] if isinstance(part_row, (sqlite3.Row, dict)) else part_row[0])

        results: list[dict[str, Any]] = []
        visited = {clean_pn.upper()}

        def _dfs(parent_trk: str, parent_pid: str | None, rel_lvl: int) -> None:
            if rel_lvl > max_depth:
                return

            child_rows = conn.execute(
                """SELECT o.id, o.child_tracker_number, o.proposed_quantity, o.child_part_id,
                          p.part_number, p.description
                   FROM pits_bom_occurrences o
                   LEFT JOIN parts p ON o.child_part_id = p.id
                   WHERE o.project_id = ?
                     AND (
                         (o.parent_tracker_number <> '' AND (UPPER(o.parent_tracker_number) = UPPER(?) OR UPPER(o.parent_tracker_number) LIKE UPPER(?) || '#%'))
                         OR (? IS NOT NULL AND o.parent_part_id = ?)
                     )
                   ORDER BY o.proposed_depth ASC, o.source_row ASC, o.id ASC""",
                (project_id, parent_trk, parent_trk, parent_pid, parent_pid),
            ).fetchall()

            for cr in child_rows:
                c_pn = str(cr["part_number"] or cr["child_tracker_number"] or "").strip()
                if not c_pn or c_pn.upper() in visited:
                    continue
                visited.add(c_pn.upper())

                c_desc = str(cr["description"] or "").strip()
                if not c_desc:
                    p_lookup = conn.execute(
                        "SELECT description FROM parts WHERE project_id=? AND UPPER(part_number)=UPPER(?)",
                        (project_id, c_pn),
                    ).fetchone()
                    if p_lookup and (p_lookup["description"] if isinstance(p_lookup, (sqlite3.Row, dict)) else p_lookup[0]):
                        c_desc = str(p_lookup["description"] if isinstance(p_lookup, (sqlite3.Row, dict)) else p_lookup[0]).strip()

                c_qty = round(float(cr["proposed_quantity"] if cr["proposed_quantity"] is not None else 1.0), 5)
                c_pid = str(cr["child_part_id"]) if cr["child_part_id"] else None

                results.append({
                    "part_number": c_pn,
                    "description": c_desc,
                    "quantity": c_qty,
                    "relative_level": rel_lvl,
                    "parent_tracker": parent_trk,
                    "child_tracker": c_pn,
                })

                # Recursively visit children of this child immediately (DFS Pre-order)
                _dfs(c_pn, c_pid, rel_lvl + 1)

        _dfs(clean_pn, part_id, 1)
        return results

    if _conn is not None:
        return _execute(_conn)
    with connection() as conn:
        return _execute(conn)


def detect_unexpanded_subassemblies(
    project_id: str,
    items: list[dict[str, Any]],
    _conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Scan items in a BOM draft for any part/group numbers that have known child components
    in pits_bom_occurrences across the project which are not yet present in the draft.

    Returns a list of dicts:
    [
        {
            "part_number": str,
            "level": int,
            "description": str,
            "children": list[dict[str, Any]],
        }
    ]
    """
    clean_items = [it for it in items if str(it.get("part_number") or "").strip()]
    if not clean_items:
        return []

    existing_pns = {str(it["part_number"]).strip().upper() for it in clean_items}
    detected: list[dict[str, Any]] = []
    seen_detected_pns: set[str] = set()

    def _execute(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        for it in clean_items:
            pn = str(it["part_number"]).strip()
            pn_upper = pn.upper()
            if pn_upper in seen_detected_pns:
                continue

            sub_children = get_known_subassembly_structure(project_id, pn, _conn=conn)
            if not sub_children:
                continue

            # Identify which children are not already in the BOM
            missing_children = [
                c for c in sub_children
                if c["part_number"].upper() not in existing_pns
            ]
            if missing_children:
                seen_detected_pns.add(pn_upper)
                detected.append({
                    "part_number": pn,
                    "level": int(it.get("level", 1) or 1),
                    "description": str(it.get("description") or ""),
                    "children": missing_children,
                })
        return detected

    if _conn is not None:
        return _execute(_conn)
    with connection() as conn:
        return _execute(conn)


def expand_subassembly_items(
    items: list[dict[str, Any]],
    detected_subassemblies: list[dict[str, Any]],
    selected_pns: set[str] | None = None,
    catalog_parts: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Insert child components directly beneath their parent subassembly, preserving all assemblies.

    Rows are inserted between the parent assembly and whatever rows follow it.
    Existing assemblies, including top-level assemblies and subsequent assemblies, are never overwritten.
    Child components are inserted in strict Pre-order Depth-First tree order beneath the group number.
    """
    sub_map = {
        d["part_number"].strip().upper(): d["children"]
        for d in detected_subassemblies
        if selected_pns is None or d["part_number"].strip().upper() in selected_pns
    }

    if not sub_map:
        return [dict(it) for it in items]

    expanded: list[dict[str, Any]] = []
    seen_pns = {str(it.get("part_number") or "").strip().upper() for it in items if it.get("part_number")}

    for it in items:
        curr = dict(it)
        pn = str(curr.get("part_number") or "").strip()
        pn_upper = pn.upper()

        # If description is missing, autofill from catalog if provided
        if catalog_parts and not curr.get("description") and pn_upper in catalog_parts:
            curr["description"] = catalog_parts[pn_upper]

        # 1. ALWAYS preserve the parent / current item itself intact!
        expanded.append(curr)

        # 2. If this item was selected for subassembly expansion, insert its children
        if pn_upper in sub_map:
            parent_lvl = int(curr.get("level", 1) or 1)
            for child in sub_map[pn_upper]:
                c_pn = str(child.get("part_number") or "").strip()
                if not c_pn or c_pn.upper() in seen_pns:
                    continue
                seen_pns.add(c_pn.upper())

                c_desc = str(child.get("description") or "").strip()
                if not c_desc and catalog_parts and c_pn.upper() in catalog_parts:
                    c_desc = catalog_parts[c_pn.upper()]

                try:
                    c_qty = round(float(child.get("quantity", 1.0) or 1.0), 5)
                except (TypeError, ValueError):
                    c_qty = 1.0

                rel_lvl = int(child.get("relative_level", 1) or 1)
                expanded.append({
                    "level": min(11, parent_lvl + rel_lvl),
                    "part_number": c_pn,
                    "description": c_desc,
                    "quantity": c_qty,
                    "_uid": str(uuid4())[:8],
                })

    return expanded


def get_model_level1_assemblies(
    project_id: str,
    exclude_model_id: str | None = None,
    _conn: sqlite3.Connection | None = None,
) -> dict[str, str]:
    """Returns mapping of UPPER(level1_part_number) -> model_number for models in the project."""
    def _execute(conn: sqlite3.Connection) -> dict[str, str]:
        q = "SELECT id, model_number FROM project_models WHERE project_id=?"
        params = [project_id]
        if exclude_model_id:
            q += " AND id <> ?"
            params.append(exclude_model_id)
        models = conn.execute(q, params).fetchall()

        mapping: dict[str, str] = {}
        for m in models:
            m_id = str(m["id"])
            m_num = str(m["model_number"]).strip()
            bom = get_manual_model_bom(project_id, m_id, _conn=conn)
            lvl1 = next((it for it in bom if it.get("level") == 1), None)
            if lvl1 and lvl1.get("part_number"):
                pn_clean = str(lvl1["part_number"]).strip().upper()
                if pn_clean:
                    mapping[pn_clean] = m_num
        return mapping

    if _conn is not None:
        return _execute(_conn)
    with connection() as conn:
        return _execute(conn)


def save_manual_model_bom(
    project_id: str,
    model_id: str,
    items: list[dict[str, Any]],
    auto_add_parts: bool = True,
    editor: str = "",
    source_model_id: str | None = None,
) -> dict[str, Any]:
    """Validate and atomically persist a model-specific BOM hierarchy in pits_bom_occurrences."""
    with connection() as conn:
        m_row = conn.execute(
            "SELECT id, model_number FROM project_models WHERE id=? AND project_id=?",
            (model_id, project_id),
        ).fetchone()
        if not m_row:
            raise ValueError("The selected official model was not found in this project.")
        model_number = str(m_row["model_number"]).strip()
        clean_model_key = model_number

        cleaned_items: list[dict[str, Any]] = []
        for idx, it in enumerate(items):
            p_num = str(it.get("part_number") or "").strip()
            if not p_num:
                continue
            raw_lvl = it.get("level")
            try:
                lvl = int(raw_lvl)
            except (TypeError, ValueError):
                raise ValueError(f"Row {idx + 1}: Level must be an integer between 1 and 11.")
            if not (1 <= lvl <= 11):
                raise ValueError(f"Row {idx + 1}: Level must be between 1 and 11.")
            raw_qty = it.get("quantity")
            try:
                qty = round(float(raw_qty), 5) if raw_qty is not None and str(raw_qty).strip() != "" else 1.0
            except (TypeError, ValueError):
                raise ValueError(f"Row {idx + 1} ('{p_num}'): Quantity must be a valid number.")
            if qty <= 0:
                raise ValueError(f"Row {idx + 1} ('{p_num}'): Quantity must be greater than 0.")
            desc = str(it.get("description") or "").strip()
            grp = str(it.get("group_number") or "").strip()
            trk = str(it.get("child_tracker") or it.get("tracker") or p_num).strip()
            cleaned_items.append({
                "level": lvl,
                "group_number": grp,
                "part_number": p_num,
                "description": desc,
                "quantity": qty,
                "child_tracker": trk,
            })

        if not cleaned_items:
            raise ValueError("The BOM must contain at least one item with a valid Part Number.")

        # Ensure first item starts at Level 1
        if cleaned_items[0]["level"] > 1:
            cleaned_items[0]["level"] = 1

        # Validate no skipped levels (e.g. L1 directly to L3)
        for i in range(1, len(cleaned_items)):
            curr_lvl = cleaned_items[i]["level"]
            prev_lvl = cleaned_items[i - 1]["level"]
            if curr_lvl > prev_lvl + 1:
                raise ValueError(
                    f"Row {i + 1} ('{cleaned_items[i]['part_number']}'): Cannot skip levels (went from Level {prev_lvl} to Level {curr_lvl}). A subassembly level cannot exceed the preceding level + 1."
                )

        # Validate Level 1 Assembly uniqueness across models in the project
        lvl1_items = [it for it in cleaned_items if it["level"] == 1]
        if not lvl1_items:
            raise ValueError("The BOM must contain at least one top-level item at Level 1.")
        curr_lvl1_pn = lvl1_items[0]["part_number"].strip().upper()

        other_lvl1_map = get_model_level1_assemblies(project_id, exclude_model_id=model_id, _conn=conn)
        if curr_lvl1_pn in other_lvl1_map:
            conflict_model = other_lvl1_map[curr_lvl1_pn]
            raise ValueError(
                f"Level 1 Assembly Number '{lvl1_items[0]['part_number']}' is already assigned to model '{conflict_model}'. "
                f"Each model must have a distinct Level 1 Assembly Number."
            )

        # Validate Level 2+ difference when copied from a source model
        if source_model_id and source_model_id != model_id:
            src_bom = get_manual_model_bom(project_id, source_model_id, _conn=conn)
            if src_bom:
                curr_lvl2 = [
                    (it["level"], it["part_number"].strip().upper(), round(float(it["quantity"]), 5))
                    for it in cleaned_items if it["level"] >= 2
                ]
                src_lvl2 = [
                    (it.get("level", 1), str(it.get("part_number", "")).strip().upper(), round(float(it.get("quantity", 1.0) or 1.0), 5))
                    for it in src_bom if it.get("level", 1) >= 2
                ]
                if curr_lvl2 and src_lvl2 and curr_lvl2 == src_lvl2:
                    src_m = conn.execute(
                        "SELECT model_number FROM project_models WHERE id=?",
                        (source_model_id,),
                    ).fetchone()
                    src_name = str(src_m["model_number"]).strip() if src_m else source_model_id
                    raise ValueError(
                        f"Cannot save BOM: The Level 2+ structure is 100% identical to source model '{src_name}'. "
                        f"A model with a new Level 1 assembly must have at least one component, quantity, or variant difference in its Level 2+ structure."
                    )

        # 1. Onboard parts into Parts Catalog if requested, and autofill missing descriptions
        parts_created = 0
        existing_part_rows = conn.execute(
            "SELECT id, part_number, description FROM parts WHERE project_id=?",
            (project_id,),
        ).fetchall()
        part_lookup = {r["part_number"]: r["id"] for r in existing_part_rows}
        part_desc_lookup = {
            r["part_number"].upper(): str(r["description"] or "").strip()
            for r in existing_part_rows
        }

        # Autofill missing descriptions from catalog
        for it in cleaned_items:
            pn_upper = it["part_number"].upper()
            if not it["description"] and pn_upper in part_desc_lookup and part_desc_lookup[pn_upper]:
                it["description"] = part_desc_lookup[pn_upper]

        now_ts = now_iso()
        if auto_add_parts:
            for it in cleaned_items:
                pn = it["part_number"]
                raw_pits_id = str(it.get("pits_tracker_number") or it.get("pits_id") or "").strip()
                pits_id = raw_pits_id if raw_pits_id and raw_pits_id != pn else ""
                desc_val = str(it.get("description") or "").strip()
                if pn not in part_lookup:
                    new_pid = str(uuid4())
                    conn.execute(
                        """INSERT INTO parts (id, project_id, part_number, description, pits_tracker_number, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (new_pid, project_id, pn, desc_val, pits_id, now_ts),
                    )
                    part_lookup[pn] = new_pid
                    part_desc_lookup[pn.upper()] = desc_val
                    parts_created += 1
                else:
                    # Clean up any stale part_number that was previously copied to pits_tracker_number
                    # AND sync any non-empty description to the Parts Catalog table
                    if desc_val:
                        conn.execute(
                            """UPDATE parts SET description = ?, pits_tracker_number = '', updated_at = ?
                               WHERE project_id = ? AND part_number = ?""",
                            (desc_val, now_ts, project_id, pn),
                        )
                        part_desc_lookup[pn.upper()] = desc_val
                    else:
                        conn.execute(
                            """UPDATE parts SET pits_tracker_number = '', updated_at = ?
                               WHERE project_id = ? AND part_number = ? AND pits_tracker_number = ?""",
                            (now_ts, project_id, pn, pn),
                        )
        else:
            for it in cleaned_items:
                pn = it["part_number"]
                desc_val = str(it.get("description") or "").strip()
                if pn in part_lookup and desc_val:
                    conn.execute(
                        """UPDATE parts SET description = ?, updated_at = ?
                           WHERE project_id = ? AND part_number = ? AND (description IS NULL OR description <> ?)""",
                        (desc_val, now_ts, project_id, pn, desc_val),
                    )
                    part_desc_lookup[pn.upper()] = desc_val

        # 2. Ensure an import record exists in pits_bom_imports
        imp_row = conn.execute(
            "SELECT id FROM pits_bom_imports WHERE project_id=? ORDER BY import_sequence ASC LIMIT 1",
            (project_id,),
        ).fetchone()
        if imp_row:
            import_id = str(imp_row["id"])
        else:
            import_id = str(uuid4())
            conn.execute(
                """INSERT INTO pits_bom_imports (id, project_id, import_sequence, workbook_name, workbook_sha256, bom_sheet_name, imported_by, imported_at)
                   VALUES (?, ?, 1, 'Manual Model Tree', 'manual', 'Model Tree', ?, ?)""",
                (import_id, project_id, editor or "Collaborator", now_ts),
            )

        # 3. Resolve parentage via outline stack traversal
        stack: dict[int, dict[str, Any]] = {}
        processed_occurrences: list[dict[str, Any]] = []
        seen_parent_child_trackers: set[tuple[str, str]] = set()
        dup_counter: dict[tuple[str, str], int] = {}

        for idx, it in enumerate(cleaned_items):
            lvl = it["level"]
            parent_node = stack.get(lvl - 1)
            parent_trk = parent_node["child_tracker"] if parent_node else ""
            parent_part_id = parent_node["part_id"] if parent_node else None

            child_part_id = part_lookup.get(it["part_number"])

            base_trk = str(it.get("child_tracker") or it.get("tracker") or it["part_number"]).strip()
            pair_key = (parent_trk, base_trk)
            if pair_key in seen_parent_child_trackers:
                dup_idx = dup_counter.get(pair_key, 1) + 1
                dup_counter[pair_key] = dup_idx
                child_trk = f"{base_trk}#{dup_idx}"
            else:
                seen_parent_child_trackers.add(pair_key)
                dup_counter[pair_key] = 1
                child_trk = base_trk

            stack[lvl] = {
                "child_tracker": child_trk,
                "part_id": child_part_id,
                "part_number": it["part_number"],
            }
            stack = {d: n for d, n in stack.items() if d <= lvl}

            processed_occurrences.append({
                "source_row": idx + 1,
                "depth": lvl,
                "parent_tracker": parent_trk,
                "child_tracker": child_trk,
                "parent_part_id": parent_part_id,
                "child_part_id": child_part_id,
                "part_number": it["part_number"],
                "description": it["description"],
                "quantity": it["quantity"],
                "group_number": it["group_number"],
            })

        # 4. Fetch all existing occurrences for this project
        existing_occ_rows = conn.execute(
            "SELECT * FROM pits_bom_occurrences WHERE project_id=?",
            (project_id,),
        ).fetchall()

        # Build mapping: (parent_trk, child_trk) -> row
        existing_by_key = {
            (r["parent_tracker_number"], r["child_tracker_number"]): dict(r)
            for r in existing_occ_rows
        }

        # Track which keys this new model uses
        new_keys_used = set()
        clean_target = re.sub(r"[^A-Za-z0-9]", "", clean_model_key).upper()

        for occ_data in processed_occurrences:
            k = (occ_data["parent_tracker"], occ_data["child_tracker"])
            new_keys_used.add(k)

            depth = occ_data["depth"]
            qty = round(float(occ_data["quantity"]), 5)
            raw_qty_text = f"{qty:.5f}".rstrip("0").rstrip(".") if "." in f"{qty:.5f}" else str(qty)
            fingerprint = _pits_bom_fingerprint(depth, raw_qty_text, qty)

            existing = existing_by_key.get(k)
            if existing is not None:
                # Update existing occurrence
                occ_id = str(existing["id"])
                usages: dict[str, float] = {}
                try:
                    data = json.loads(existing["raw_levels_json"] or "{}")
                    if isinstance(data, dict):
                        u = data.get("model_usages")
                        if isinstance(u, dict):
                            usages = {str(k_u): float(v_u) for k_u, v_u in u.items() if v_u is not None}
                except Exception:
                    data = {}

                # Purge any stale or conflicting keys for this model
                keys_to_purge = [
                    k_u for k_u in usages
                    if str(k_u) == clean_model_key
                    or re.sub(r"[^A-Za-z0-9]", "", str(k_u)).upper() == clean_target
                    or (len(clean_target) >= 6 and (clean_target[:6] in str(k_u).upper() or str(k_u).upper()[:6] in clean_target))
                ]
                for kp in keys_to_purge:
                    del usages[kp]
                usages[clean_model_key] = qty
                data["model_usages"] = usages

                # Store per-model row sequence in raw_levels_json to prevent cross-model source_row collisions
                model_seq = data.get("model_sequence")
                if not isinstance(model_seq, dict):
                    model_seq = {}
                for kp in keys_to_purge:
                    model_seq.pop(kp, None)
                model_seq[clean_model_key] = idx + 1
                data["model_sequence"] = model_seq

                if occ_data["group_number"]:
                    data["group_number"] = occ_data["group_number"]
                data["description"] = occ_data["description"]
                data["part_number"] = occ_data["part_number"]
                data["source"] = "manual"

                conn.execute(
                    """UPDATE pits_bom_occurrences
                       SET child_part_id=?, parent_part_id=?, proposed_depth=?,
                           proposed_quantity=?, raw_quantity_text=?, source_row=?,
                           raw_levels_json=?, source_fingerprint=?, updated_at=?
                       WHERE id=?""",
                    (
                        occ_data["child_part_id"], occ_data["parent_part_id"], depth,
                        qty, raw_qty_text, occ_data["source_row"],
                        json.dumps(data, ensure_ascii=False), fingerprint, now_ts,
                        occ_id,
                    ),
                )
                existing["raw_levels_json"] = json.dumps(data, ensure_ascii=False)
            else:
                # Insert new occurrence
                occ_id = str(uuid4())
                usages = {clean_model_key: qty}
                model_seq = {clean_model_key: idx + 1}
                data = {
                    "model_usages": usages,
                    "model_sequence": model_seq,
                    "group_number": occ_data["group_number"],
                    "description": occ_data["description"],
                    "part_number": occ_data["part_number"],
                    "source": "manual",
                }
                conn.execute(
                    """INSERT INTO pits_bom_occurrences
                       (id, project_id, parent_tracker_number, child_tracker_number,
                        parent_part_id, child_part_id, proposed_depth, raw_quantity_text,
                        proposed_quantity, source_row, raw_levels_json, source_fingerprint,
                        review_status, source_state, validation_issues_json,
                        first_seen_import_id, last_seen_import_id,
                        first_seen_at, last_seen_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Needs review', 'Current', '[]',
                               ?, ?, ?, ?, ?)""",
                    (
                        occ_id, project_id, occ_data["parent_tracker"], occ_data["child_tracker"],
                        occ_data["parent_part_id"], occ_data["child_part_id"], depth,
                        raw_qty_text, qty, occ_data["source_row"],
                        json.dumps(data, ensure_ascii=False), fingerprint,
                        import_id, import_id, now_ts, now_ts, now_ts,
                    ),
                )
                existing_by_key[k] = {"id": occ_id, "raw_levels_json": json.dumps(data, ensure_ascii=False)}

        # 5. Clean up any previous usages of this model that were removed
        for k, existing in existing_by_key.items():
            if k not in new_keys_used and "raw_levels_json" in existing:
                try:
                    data = json.loads(existing["raw_levels_json"] or "{}")
                    if isinstance(data, dict):
                        usages = data.get("model_usages", {})
                        if isinstance(usages, dict):
                            keys_to_purge = [
                                mk for mk in usages
                                if str(mk) == clean_model_key
                                or re.sub(r"[^A-Za-z0-9]", "", str(mk)).upper() == clean_target
                                or (len(clean_target) >= 6 and (clean_target[:6] in str(mk).upper() or str(mk).upper()[:6] in clean_target))
                            ]
                            if keys_to_purge:
                                for kp in keys_to_purge:
                                    del usages[kp]
                                data["model_usages"] = usages
                                if "model_sequence" in data and isinstance(data["model_sequence"], dict):
                                    for kp in keys_to_purge:
                                        data["model_sequence"].pop(kp, None)
                                if not usages and (data.get("source") == "manual" or str(existing.get("source_state", "")).lower() == "manual"):
                                    conn.execute("DELETE FROM pits_bom_occurrences WHERE id=?", (existing["id"],))
                                else:
                                    conn.execute(
                                        "UPDATE pits_bom_occurrences SET raw_levels_json=?, updated_at=? WHERE id=?",
                                        (json.dumps(data, ensure_ascii=False), now_ts, existing["id"]),
                                    )
                except Exception:
                    pass

        # 6. Audit event
        record_audit_event(
            project_id,
            "Model Tree BOM",
            f"Saved BOM for model '{clean_model_key}'",
            len(processed_occurrences),
            editor_name=editor,
            _conn=conn,
        )

        return {
            "saved_count": len(processed_occurrences),
            "parts_created": parts_created,
            "model_number": clean_model_key,
        }


def sync_builder_inputs_to_items(items: list[dict[str, Any]], model_id: str) -> None:
    """Synchronize Streamlit session state widget values into the in-memory items list."""
    import streamlit as st
    for it in items:
        uid = it.get("_uid")
        if not uid:
            continue
        pn_k = f"bld_pn_{uid}_{model_id}"
        if pn_k in st.session_state:
            it["part_number"] = str(st.session_state[pn_k]).strip()
        desc_k = f"bld_desc_{uid}_{model_id}"
        if desc_k in st.session_state:
            it["description"] = str(st.session_state[desc_k]).strip()
        qty_k = f"bld_qty_{uid}_{model_id}"
        if qty_k in st.session_state:
            try:
                it["quantity"] = max(0.00001, round(float(st.session_state[qty_k]), 5))
            except (TypeError, ValueError):
                pass
        lvl_k = f"bld_lvl_{uid}_{model_id}"
        if lvl_k in st.session_state:
            try:
                it["level"] = max(1, min(11, int(st.session_state[lvl_k])))
            except (TypeError, ValueError):
                pass


def get_live_bom_editor_items(curr_model_id: str, d_key: str, ed_logical_key: str) -> list[dict[str, Any]]:
    """Capture live un-saved cell edits, additions, and deletions from Streamlit Session State."""
    import streamlit as st
    from utils.table_filters import _EDITOR_INSTANCE_MARKER

    base_items = [dict(it) for it in st.session_state.get(d_key, [])]
    if not base_items:
        base_items = [{"level": 1, "part_number": "", "description": "", "quantity": 1.0, "_uid": str(uuid4())[:8]}]

    has_builder_keys = any(
        k.startswith("bld_pn_") and k.endswith(f"_{curr_model_id}")
        for k in st.session_state
    )
    if has_builder_keys:
        sync_builder_inputs_to_items(base_items, curr_model_id)
        return base_items

    generation = int(st.session_state.get(f"_table_editor_generation_{ed_logical_key}", 0) or 0)
    ed_key = f"{ed_logical_key}{_EDITOR_INSTANCE_MARKER}{generation}"
    ed_state = st.session_state.get(ed_key)
    if not isinstance(ed_state, dict):
        return base_items

    edited_rows = ed_state.get("edited_rows") or {}
    for idx_str, edits in edited_rows.items():
        try:
            idx = int(idx_str)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(base_items):
            if "Select" in edits:
                base_items[idx]["_selected"] = bool(edits["Select"])
            if "Level" in edits:
                try:
                    base_items[idx]["level"] = max(1, min(11, int(edits["Level"])))
                except (TypeError, ValueError):
                    pass
            if "Part #" in edits:
                base_items[idx]["part_number"] = str(edits["Part #"]).strip()
            if "Description" in edits:
                base_items[idx]["description"] = str(edits["Description"]).strip()
            if "Qty" in edits:
                try:
                    base_items[idx]["quantity"] = max(0.00001, round(float(edits["Qty"]), 5))
                except (TypeError, ValueError):
                    pass

    added_rows = ed_state.get("added_rows") or []
    for add in added_rows:
        try:
            lvl = max(1, min(11, int(add.get("Level", 1) or 1)))
        except (TypeError, ValueError):
            lvl = 1
        try:
            qty = max(0.00001, round(float(add.get("Qty", 1.0) or 1.0), 5))
        except (TypeError, ValueError):
            qty = 1.0
        base_items.append({
            "level": lvl,
            "part_number": str(add.get("Part #") or "").strip(),
            "description": str(add.get("Description") or "").strip(),
            "quantity": qty,
            "_uid": str(uuid4())[:8],
        })

    deleted_rows = set(ed_state.get("deleted_rows") or [])
    if deleted_rows:
        base_items = [it for idx, it in enumerate(base_items) if idx not in deleted_rows]

    return base_items


def move_bom_rows_up(items: list[dict[str, Any]], selected_indices: set[int] | list[int]) -> tuple[list[dict[str, Any]], set[int]]:
    """Move selected rows up by one position, preserving relative order."""
    sel = {int(i) for i in selected_indices if isinstance(i, (int, str)) and str(i).isdigit()}
    if not items or not sel:
        return list(items), set()
    new_items = [dict(it) for it in items]
    new_selected = set()
    for idx in sorted(sel):
        if idx > 0 and (idx - 1) not in new_selected:
            new_items[idx - 1], new_items[idx] = new_items[idx], new_items[idx - 1]
            new_selected.add(idx - 1)
        else:
            new_selected.add(idx)
    return new_items, new_selected


def move_bom_rows_down(items: list[dict[str, Any]], selected_indices: set[int] | list[int]) -> tuple[list[dict[str, Any]], set[int]]:
    """Move selected rows down by one position, preserving relative order."""
    sel = {int(i) for i in selected_indices if isinstance(i, (int, str)) and str(i).isdigit()}
    if not items or not sel:
        return list(items), set()
    new_items = [dict(it) for it in items]
    new_selected = set()
    for idx in sorted(sel, reverse=True):
        if idx < len(new_items) - 1 and (idx + 1) not in new_selected:
            new_items[idx + 1], new_items[idx] = new_items[idx], new_items[idx + 1]
            new_selected.add(idx + 1)
        else:
            new_selected.add(idx)
    return new_items, new_selected


def delete_bom_rows(items: list[dict[str, Any]], selected_indices: set[int] | list[int]) -> tuple[list[dict[str, Any]], set[int]]:
    """Delete all selected rows from items. Returns new items and new active selection."""
    sel = {int(i) for i in selected_indices if isinstance(i, (int, str)) and str(i).isdigit()}
    if not items or not sel:
        return list(items), set()
    new_items = [dict(it) for idx, it in enumerate(items) if idx not in sel]
    if not new_items:
        new_items = [{"level": 1, "part_number": "", "description": "", "quantity": 1.0, "_uid": str(uuid4())[:8]}]
        return new_items, {0}
    min_sel = min(sel)
    next_sel = min(min_sel, len(new_items) - 1)
    return new_items, {next_sel}


__domain_exports__ = [
    'pits_catalog_id_resolution', 'PART_SOURCE_CODES', 'PART_MAKE_BUY_VALUES',
    'project_table', 'part_scenario_activity', 'active_part_ids',
    'update_part_scenario_activity', 'normalize_model_applicability',
    '_clean_optional_text', '_validated_part_catalog_fields', 'upsert_part',
    'update_part_rows', 'part_delete_impact', 'delete_project_part',
    'set_part_image', 'set_part_image_url', 'clear_part_image', 'add_part_image', 'add_part_image_url', 'delete_part_image', 'part_images', 'complexity_features',
    'complexity_feature_delete_impacts', 'complexity_tree',
    'potential_duplicate_models', 'part_feature_rules',
    'update_part_feature_rules', 'infer_part_feature_rules',
    'apply_inferred_part_feature_rules', 'preview_inferred_part_feature_rules',
    'complexity_planning_snapshot', 'restore_complexity_planning_snapshot',
    'update_complexity_features', 'update_complexity_tree',
    'model_planning_snapshot', '_insert_snapshot_rows',
    'restore_model_planning_snapshot', 'delete_project_models',
    'delete_project_model', 'add_project_model', 'update_project_model_rows',
    'pits_records', 'pits_revisions', 'pits_import_conflict_parts',
    'detect_pits_new_and_changed_parts', 'pits_part_downstream_impacts',
    'import_pits_id_snapshot', 'apply_pits_updates', 'set_mbom_review_status',
    'sync_confirmed_mbom_parts', 'pits_bom_occurrences',
    'review_pits_bom_occurrences', 'escalate_pits_bom_occurrence',
    'G_FORMAT_REGEX', 'is_g_format_number', 'model_bom_tree_nodes',
    'pits_bom_model_tree', 'pits_assembly_mini_bom', 'get_manual_model_bom',
    'save_manual_model_bom', 'get_known_subassembly_structure',
    'get_model_level1_assemblies', 'detect_unexpanded_subassemblies',
    'expand_subassembly_items', 'sort_bom_hierarchy',
    'sync_builder_inputs_to_items', 'get_live_bom_editor_items',
    'move_bom_rows_up', 'move_bom_rows_down', 'delete_bom_rows'
]
for _export_name in __domain_exports__:
    if callable(globals()[_export_name]):
        globals()[_export_name] = _db_core.domain_entrypoint(globals()[_export_name])
_db_core.register_domain_module(_sys.modules[__name__], __domain_exports__)
