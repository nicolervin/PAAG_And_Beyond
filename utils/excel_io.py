from __future__ import annotations

import copy
from io import BytesIO
from pathlib import Path
import re
from datetime import date, datetime

import pandas as pd

from utils.time_units import seconds_to_display, time_unit
from utils.store import (
    active_part_ids,
    assembly_sections,
    fishbone_part_assignments,
    get_planning_scenario,
    get_project,
    material_consumption_for_scenario,
    pits_records,
    pits_revisions,
    project_models,
    project_table,
)
ALIASES = {
    "part_number": {"partnumber", "partno", "partnum", "pn", "material", "materialnumber", "itemnumber"},
    "description": {"description", "partdescription", "materialdescription", "name"},
    "quantity": {"quantity", "qty", "usage", "quantityper", "qtyper"},
    "revision": {"revision", "rev", "version"},
    "model_applicability": {"model", "models", "variant", "applicability", "modelapplicability"},
}
COMPANY_PFMEA_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "templates" / "FRM-GEA-QYS-033_PFMEA_Template.xlsx"
)


def normalize_header(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _clean_excel_header(value: object, index: int) -> str:
    text = "" if value is None or pd.isna(value) else str(value).strip()
    if not text:
        return f"Unnamed: {index}"
    return text


def read_bom(uploaded_file, sheet_name=0) -> pd.DataFrame:
    suffix = uploaded_file.name.lower()
    if suffix.endswith((".csv", ".txt", ".tsv")):
        separator = "\t" if suffix.endswith((".txt", ".tsv")) else ","
        return pd.read_csv(uploaded_file, sep=separator, dtype=str, keep_default_na=False)

    raw = pd.read_excel(uploaded_file, sheet_name=sheet_name, header=None, dtype=object)
    if raw.empty:
        return raw

    best_header_row = 0
    best_score = -1
    for row_index in range(len(raw)):
        row = raw.iloc[row_index]
        populated = row.dropna().astype(str).map(str.strip).loc[lambda values: values != ""]
        if populated.empty:
            continue
        score = len(populated)
        if score > best_score:
            best_score = score
            best_header_row = row_index

    header_row = raw.iloc[best_header_row].copy()
    values = raw.iloc[best_header_row + 1:].copy() if best_header_row + 1 < len(raw) else raw.iloc[0:0].copy()
    values.columns = [
        _clean_excel_header(value, index)
        for index, value in enumerate(header_row)
    ]
    values = values.loc[:, [str(column).strip() != "" for column in values.columns]].copy()
    values = values.dropna(how="all").reset_index(drop=True)
    return values


def is_pits_format(df: pd.DataFrame) -> bool:
    normalized = {normalize_header(column) for column in df.columns}
    return {"intracker", "partnumber", "description", "level1", "level2"}.issubset(normalized)


def _normalized_sheet_name(name: object) -> str:
    return normalize_header(name)


def _find_pits_sheet(workbook, *, type_name: str) -> str | None:
    normalized_names = { _normalized_sheet_name(sheet): sheet for sheet in workbook.sheet_names }
    aliases = {
        "part_tracker": {"parttracker", "parttracker", "pitstracker", "pitstracker", "parttracker"},
        "models": {"models", "modeldefinitions", "modeldefinition", "modelsheet", "modeldetails"},
        "bom": {"bom", "billofmaterials", "materialbom", "engineeringbom", "ebom"},
    }
    lookup = aliases[type_name]
    for normalized in lookup:
        if normalized in normalized_names:
            return normalized_names[normalized]

    if type_name == "part_tracker":
        for sheet_name in workbook.sheet_names:
            normalized = _normalized_sheet_name(sheet_name)
            if ("part" in normalized or "pits" in normalized or "tracker" in normalized) and "model" not in normalized:
                return sheet_name
    elif type_name == "models":
        for sheet_name in workbook.sheet_names:
            normalized = _normalized_sheet_name(sheet_name)
            if ("model" in normalized or "vehicle" in normalized) and "tracker" not in normalized:
                return sheet_name
    else:
        for sheet_name in workbook.sheet_names:
            normalized = _normalized_sheet_name(sheet_name)
            if (normalized == "bom" or normalized.endswith("bom") or "bom" in normalized) and "bop" not in normalized:
                return sheet_name
    return None


def has_pits_id_sheets(uploaded_file) -> bool:
    if not uploaded_file.name.lower().endswith((".xlsx", ".xlsm")):
        return False
    workbook = pd.ExcelFile(BytesIO(uploaded_file.getvalue()))
    return bool(_find_pits_sheet(workbook, type_name="part_tracker")) and bool(_find_pits_sheet(workbook, type_name="models"))


def _clean_value(value):
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _excel_column_value(row: pd.Series, column: str) -> str:
    """Read a source value by its stable spreadsheet column position."""
    position = 0
    for character in column.upper():
        position = position * 26 + ord(character) - ord("A") + 1
    zero_based_position = position - 1
    if zero_based_position >= len(row):
        return ""
    value = _clean_value(row.iloc[zero_based_position])
    return "" if value is None else str(value).strip()


def _source_code_number(value: str) -> str:
    """Keep only the numeric PITS source code prefix from column T."""
    match = re.match(r"^[+]?\d+(?:\.\d+)?", str(value or "").strip())
    return match.group(0) if match else ""


def _normalized_row(row: pd.Series) -> dict[str, object]:
    return {normalize_header(column): _clean_value(value) for column, value in row.items()}


def _detect_header_row(raw_df: pd.DataFrame, required_tokens: set[str]) -> int:
    best_row = 0
    best_score = -1
    for row_index, row in raw_df.iterrows():
        row_values = [str(value).strip() for value in row.to_list() if value is not None and not pd.isna(value)]
        if not row_values:
            continue
        score = 0
        for value in row_values:
            normalized = normalize_header(value)
            if any(token in normalized for token in required_tokens):
                score += 1
        if score > best_score:
            best_score = score
            best_row = row_index
    return best_row


def _sheet_with_header(raw_df: pd.DataFrame, required_tokens: set[str]) -> pd.DataFrame:
    header_row = _detect_header_row(raw_df, required_tokens)
    header = raw_df.iloc[header_row].tolist()
    data = raw_df.iloc[header_row + 1:].copy()
    data.columns = [
        _clean_excel_header(value, index)
        for index, value in enumerate(header)
    ]
    data = data.dropna(how="all").reset_index(drop=True)
    return data


def _clean_tracker_number(value: object) -> str:
    """Preserve tracker identifiers as trimmed text without float artifacts."""
    cleaned = _clean_value(value)
    return "" if cleaned is None else str(cleaned).strip()


def _parse_pits_bom_sheet(raw_df: pd.DataFrame, sheet_name: str) -> dict:
    header_row = _detect_header_row(raw_df, {"intracker", "partnumber", "level1", "level2"})
    header = raw_df.iloc[header_row].tolist()
    data = raw_df.iloc[header_row + 1:].copy().reset_index(drop=True)
    data.columns = [_clean_excel_header(value, index) for index, value in enumerate(header)]

    level_columns: dict[int, int] = {}
    for column_index, column_name in enumerate(data.columns):
        match = re.fullmatch(r"level(\d+)", normalize_header(column_name))
        if match:
            level_number = int(match.group(1))
            if 1 <= level_number <= 11 and level_number not in level_columns:
                level_columns[level_number] = column_index
    if not level_columns:
        return {
            "sheet_name": sheet_name,
            "source_row_count": len(data),
            "occurrences": [],
            "issues": [{
                "source_row": int(header_row) + 1,
                "issue": "No Level 1-11 hierarchy columns",
                "blocking": False,
                "child_tracker_number": "",
                "part_number": "",
                "description": "",
                "proposed_depth": None,
                "raw_quantity_text": "",
            }],
            "duplicates": [],
            "source_root_depth": 1,
            "level_columns": [],
        }

    populated_source_levels = [
        level_number
        for _, row in data.iterrows()
        for level_number, column_index in level_columns.items()
        if column_index < len(row)
        and row.iloc[column_index] is not None
        and not pd.isna(row.iloc[column_index])
        and str(row.iloc[column_index]).strip()
    ]
    source_root_depth = min(populated_source_levels) if populated_source_levels else 1
    occurrences: list[dict] = []
    issues: list[dict] = []
    stack: dict[int, str] = {}
    seen_keys: dict[tuple[str, str], int] = {}
    duplicate_keys: list[dict] = []

    # Detect model usage columns (typically columns U through DZ, above header row)
    model_columns: dict[int, str] = {}
    for col_idx in range(14, raw_df.shape[1]):
        for r_check in range(header_row):
            val = raw_df.iat[r_check, col_idx]
            if val is not None:
                s_val = str(val).strip()
                if (
                    len(s_val) >= 3
                    and not any(kw in s_val.lower() for kw in ("pick cost", "standard", "engineering manager", "po", "level codes"))
                ):
                    try:
                        float(s_val)
                    except ValueError:
                        model_columns[col_idx] = s_val
                        break

    for source_index, row in data.iterrows():
        source_row = int(source_index) + int(header_row) + 2
        child_tracker = _clean_tracker_number(row.iloc[0] if len(row) else "")
        part_number = _clean_tracker_number(row.iloc[1] if len(row) > 1 else "")
        description = _clean_tracker_number(row.iloc[2] if len(row) > 2 else "")
        level_values = {
            level_number: row.iloc[column_index] if column_index < len(row) else None
            for level_number, column_index in level_columns.items()
        }
        populated_levels = [
            level_number
            for level_number, value in level_values.items()
            if value is not None and not pd.isna(value) and str(value).strip()
        ]
        if not child_tracker and not part_number and not description and not populated_levels:
            continue
        if not populated_levels:
            issues.append({
                "source_row": source_row,
                "issue": "No Level 1-11 value",
                "blocking": False,
                "child_tracker_number": child_tracker,
                "part_number": part_number,
                "description": description,
                "proposed_depth": None,
                "raw_quantity_text": "",
            })
            continue

        depth = populated_levels[0]
        parent_tracker = "" if depth == source_root_depth else stack.get(depth - 1, "")
        raw_quantity = level_values[depth]
        raw_quantity_text = _clean_tracker_number(raw_quantity)
        if not child_tracker:
            issues.append({
                "source_row": source_row,
                "issue": "Missing child tracker number in Column A",
                "blocking": True,
                "child_tracker_number": "",
                "part_number": part_number,
                "description": description,
                "proposed_depth": depth,
                "raw_quantity_text": raw_quantity_text,
            })
            continue
        if depth > source_root_depth and not parent_tracker:
            issues.append({
                "source_row": source_row,
                "issue": "Missing parent tracker number",
                "blocking": True,
                "child_tracker_number": child_tracker,
                "part_number": part_number,
                "description": description,
                "proposed_depth": depth,
                "expected_parent_level": depth - 1,
                "raw_quantity_text": raw_quantity_text,
            })
            continue

        model_usages: dict[str, float] = {}
        for col_idx, m_name in model_columns.items():
            if col_idx < len(row):
                u_val = row.iloc[col_idx]
                if u_val is not None:
                    try:
                        u_qty = float(u_val)
                        if u_qty > 0:
                            model_usages[m_name] = u_qty
                    except (ValueError, TypeError):
                        pass

        proposed_quantity = None
        if model_usages:
            proposed_quantity = next(iter(model_usages.values()))
            raw_quantity_text = str(proposed_quantity)
        else:
            try:
                numeric_quantity = float(raw_quantity_text)
                if pd.notna(numeric_quantity):
                    proposed_quantity = numeric_quantity
            except (TypeError, ValueError):
                pass
        raw_levels = {
            f"Level {level_number}": _clean_value(value)
            for level_number, value in level_values.items()
            if value is not None and not pd.isna(value) and str(value).strip()
        }
        if model_usages:
            raw_levels["model_usages"] = model_usages
        occurrence = {
            "parent_tracker_number": parent_tracker,
            "child_tracker_number": child_tracker,
            "part_number": part_number,
            "description": description,
            "proposed_depth": depth,
            "raw_quantity_text": raw_quantity_text,
            "proposed_quantity": proposed_quantity,
            "source_row": source_row,
            "raw_levels": raw_levels,
            "source_root_depth": source_root_depth,
        }
        key = (parent_tracker, child_tracker)
        if key in seen_keys:
            duplicate_keys.append({
                "parent_tracker_number": parent_tracker,
                "child_tracker_number": child_tracker,
                "first_source_row": seen_keys[key],
                "duplicate_source_row": source_row,
                "part_number": part_number,
                "description": description,
                "proposed_depth": depth,
                "raw_quantity_text": raw_quantity_text,
            })
        else:
            seen_keys[key] = source_row
            occurrences.append(occurrence)
        stack[depth] = child_tracker
        stack = {level: tracker for level, tracker in stack.items() if level <= depth}

    return {
        "sheet_name": sheet_name,
        "source_row_count": len(data),
        "occurrences": occurrences,
        "issues": issues,
        "duplicates": duplicate_keys,
        "source_root_depth": source_root_depth,
        "level_columns": sorted(level_columns),
    }


def parse_pits_combined_workbook(uploaded_file) -> tuple[list[dict], list[dict], dict]:
    """Parse Tracker, Models, and BOM from one reusable Excel reader."""
    content = BytesIO(uploaded_file.getvalue())
    workbook = pd.ExcelFile(content)
    tracker_sheet = _find_pits_sheet(workbook, type_name="part_tracker")
    model_sheet = _find_pits_sheet(workbook, type_name="models")
    bom_sheet = _find_pits_sheet(workbook, type_name="bom")
    if tracker_sheet is None or model_sheet is None:
        raise ValueError("This file does not contain the expected PITS tracker and model sheets.")

    parts_raw = workbook.parse(sheet_name=tracker_sheet, header=None, dtype=object)
    models_raw = workbook.parse(sheet_name=model_sheet, header=None, dtype=object)
    bom_pits_ids_by_part: dict[str, set[str]] = {}
    bom_raw = None
    if bom_sheet is not None:
        bom_raw = workbook.parse(sheet_name=bom_sheet, header=None, dtype=object)
        bom = _sheet_with_header(bom_raw, {"tracker", "part", "description"})
        for _, row in bom.iterrows():
            bom_pits_id = _excel_column_value(row, "A")
            bom_part_number = _excel_column_value(row, "B")
            if bom_pits_id and bom_part_number:
                bom_pits_ids_by_part.setdefault(bom_part_number, set()).add(bom_pits_id)

    parts = _sheet_with_header(parts_raw, {"id", "part", "description", "status", "subsystem", "design"})
    models_df = _sheet_with_header(models_raw, {"model", "item", "platform", "package", "appearance", "base"})

    records = []
    for source_index, row in parts.iterrows():
        source = _normalized_row(row)
        pits_id = str(source.get("idnumber", "")).strip() or str(source.get("id", "")).strip()
        if not pits_id:
            continue
        part_number = next(
            (str(source.get(alias, "")).strip() for alias in (
                "partnumber", "partno", "partnum", "pn", "material",
                "materialnumber", "itemnumber",
            ) if str(source.get(alias, "")).strip()),
            "",
        )
        description = next(
            (str(source.get(alias, "")).strip() for alias in (
                "description", "partdescription", "materialdescription", "name",
            ) if str(source.get(alias, "")).strip()),
            "",
        )
        source_code = _source_code_number(_excel_column_value(row, "T"))
        catalog_part_number = part_number or str(source.get("partnumber1", "")).strip()
        subsystem = _excel_column_value(row, "F") or str(source.get("subsystem", "")).strip()
        design_maturity = _excel_column_value(row, "G") or str(source.get("designmaturity", "")).strip()
        raw_revision = _excel_column_value(row, "BL")
        revision = design_maturity or raw_revision
        design_engineer = _excel_column_value(row, "I") or next(
            (str(source.get(alias, "")).strip() for alias in (
                "designengineer", "technologyengineer", "leadengineer",
            ) if str(source.get(alias, "")).strip()),
            "",
        )
        technology_engineer = _excel_column_value(row, "I") or design_engineer
        ppm = _excel_column_value(row, "J") or next(
            (str(source.get(alias, "")).strip() for alias in ("ppm", "partprojectmanager") if str(source.get(alias, "")).strip()),
            "",
        )
        buyer_gcl = _excel_column_value(row, "K") or next(
            (str(source.get(alias, "")).strip() for alias in ("buyergcl", "buyer", "gcl") if str(source.get(alias, "")).strip()),
            "",
        )
        pmqe_aqe = _excel_column_value(row, "L") or next(
            (str(source.get(alias, "")).strip() for alias in ("pmqeaqe", "pmqe", "aqe") if str(source.get(alias, "")).strip()),
            "",
        )
        ame_tooling_engineer = _excel_column_value(row, "M") or next(
            (str(source.get(alias, "")).strip() for alias in ("ametoolingengineer", "toolingengineer", "ame") if str(source.get(alias, "")).strip()),
            "",
        )
        part_code = _excel_column_value(row, "N") or next(
            (str(source.get(alias, "")).strip() for alias in ("partcode", "code") if str(source.get(alias, "")).strip()),
            "",
        )
        source["source_code"] = source_code
        source["subsystem"] = subsystem
        source["design_maturity"] = design_maturity
        source["revision"] = revision
        source["design_engineer"] = design_engineer
        source["technology_engineer"] = technology_engineer
        source["ppm"] = ppm
        source["buyer_gcl"] = buyer_gcl
        source["pmqe_aqe"] = pmqe_aqe
        source["ame_tooling_engineer"] = ame_tooling_engineer
        source["part_code"] = part_code
        records.append({
            "pits_id": pits_id,
            "source_row": int(source_index) + 2,
            "part_number": catalog_part_number,
            "description": description,
            "revision": revision,
            "design_maturity": design_maturity,
            "source_code": source_code,
            "design_engineer": design_engineer,
            "technology_engineer": technology_engineer,
            "ppm": ppm,
            "buyer_gcl": buyer_gcl,
            "pmqe_aqe": pmqe_aqe,
            "ame_tooling_engineer": ame_tooling_engineer,
            "part_code": part_code,
            "used_bom": str(source.get("usedbom", "")).strip(),
            "status": str(source.get("baseinfostatus", "")).strip() or str(source.get("status", "")).strip(),
            "subsystem": subsystem,
            "design_maturity": design_maturity,
            "comments": str(source.get("comments", "")).strip(),
            "workstation": str(source.get("factoryworkstationlocation", "")).strip(),
            "_bom_pits_ids": sorted(bom_pits_ids_by_part.get(catalog_part_number, set())),
            "source_payload": source,
        })

    models = []
    for _, row in models_df.iterrows():
        source = _normalized_row(row)
        model_number = str(source.get("modelnumber", "")).strip() or str(source.get("model", "")).strip()
        if not model_number:
            continue
        eau_value = source.get("eau", "")
        try:
            eau = float(eau_value) if eau_value != "" else None
        except (TypeError, ValueError):
            eau = None
        models.append({
            "model_number": model_number,
            "item": str(source.get("item", "")),
            "platform_size": str(source.get("platformsize", "")),
            "package_type": str(source.get("packagetype", "")),
            "appearance": str(source.get("appearance", "")),
            "base_model": str(source.get("basemodel", "")),
            "eau": eau,
            "dg_date": str(source.get("dgdate", "")),
            "dc_date": str(source.get("dcdate", "")),
            "pre_pilot_date": str(source.get("prepilotdate", "")),
            "pilot_date": str(source.get("pilotdate", "")),
            "production_date": str(source.get("productiondate", "")),
            "sku_upc": str(source.get("skuupc", "")),
            "evaluate_fishbone": str(source.get("evaluateinfishbone", "")),
            "yamazumi": str(source.get("yamazumi", "")),
            "bop_l1": str(source.get("bopl1", "")),
            "source_payload": source,
        })
    bom_snapshot = {
        "sheet_name": "",
        "source_row_count": 0,
        "occurrences": [],
        "issues": [],
        "duplicates": [],
    }
    if bom_sheet is not None and bom_raw is not None:
        bom_snapshot = _parse_pits_bom_sheet(bom_raw, bom_sheet)
    elif bom_sheet is not None:
        bom_raw = workbook.parse(sheet_name=bom_sheet, header=None, dtype=object)
        bom_snapshot = _parse_pits_bom_sheet(bom_raw, bom_sheet)
    return records, models, bom_snapshot


def parse_pits_id_workbook(uploaded_file) -> tuple[list[dict], list[dict]]:
    """Backward-compatible Tracker+Models parser for non-combined callers."""
    records, models, _ = parse_pits_combined_workbook(uploaded_file)
    return records, models


def parse_pits(df: pd.DataFrame) -> pd.DataFrame:
    columns_by_normalized = {normalize_header(column): column for column in df.columns}
    level_columns = [columns_by_normalized.get(f"level{i}") for i in range(1, 12)]
    level_columns = [column for column in level_columns if column]
    if not level_columns:
        raise ValueError("No Level columns were found.")

    part_col = columns_by_normalized.get("partnumber")
    desc_col = columns_by_normalized.get("description")
    tracker_col = columns_by_normalized.get("intracker")
    subsystem_col = columns_by_normalized.get("subsystem")
    feature_col = columns_by_normalized.get("feature")
    comments_col = columns_by_normalized.get("comments")
    area_col = next((column for normalized, column in columns_by_normalized.items() if normalized.startswith("areaworkstation")), None)
    nodes = []
    stack: dict[int, int] = {}
    for source_index, row in df.iterrows():
        part_number = str(row.get(part_col, "")).strip()
        description = str(row.get(desc_col, "")).strip()
        if not part_number and not description:
            continue
        # Retain every populated source field because PITS conventions vary by program.
        raw_levels = {str(column): str(row.get(column, "")).strip() for column in df.columns if str(row.get(column, "")).strip()}
        nonempty_levels = [i for i, column in enumerate(level_columns, start=1) if str(row.get(column, "")).strip()]
        # Only the header position is used. Cell contents remain uninterpreted source evidence.
        depth = nonempty_levels[0] if nonempty_levels else 1
        quantity = None
        branch_name = ""
        level_evidence = " | ".join(f"{column}: {row.get(column, '')}" for column in level_columns if str(row.get(column, "")).strip())
        parent_sequence = next((stack[d] for d in range(depth - 1, 0, -1) if d in stack), None)
        sequence = len(nodes) + 1
        stack[depth] = sequence
        stack = {d: seq for d, seq in stack.items() if d <= depth}
        nodes.append({
            "source_row": int(source_index) + 2,
            "sequence": sequence,
            "parent_sequence": parent_sequence,
            "depth": depth,
            "part_number": part_number,
            "description": description,
            "quantity": quantity,
            "branch_name": branch_name,
            "subsystem": str(row.get(subsystem_col, "")).strip(),
            "model_feature": str(row.get(feature_col, "")).strip(),
            "comments": str(row.get(comments_col, "")).strip(),
            "tracker_status": str(row.get(tracker_col, "")).strip(),
            "planned_area": str(row.get(area_col, "")).strip() if area_col else "",
            "raw_levels": raw_levels,
            "level_evidence": level_evidence,
            "review_status": "Needs review",
        })
    return pd.DataFrame(nodes)


def suggest_mapping(columns) -> dict[str, str | None]:
    mapping = {}
    normalized = {normalize_header(column): column for column in columns}
    for target, aliases in ALIASES.items():
        mapping[target] = next((normalized[a] for a in aliases if a in normalized), None)
    return mapping


def mapped_bom(df: pd.DataFrame, mapping: dict[str, str | None]) -> pd.DataFrame:
    result = pd.DataFrame()
    for target in ALIASES:
        source = mapping.get(target)
        if source:
            result[target] = df[source]
        elif target == "quantity":
            result[target] = 1
        elif target == "revision":
            result[target] = "0"
        else:
            result[target] = ""
    result["part_number"] = result["part_number"].fillna("").astype(str).str.strip()
    result = result[result["part_number"] != ""]
    result["description"] = result["description"].fillna("").astype(str)
    result["quantity"] = pd.to_numeric(result["quantity"], errors="coerce").fillna(1)
    result["revision"] = (
        result["revision"].fillna("0").astype(str).str.strip().replace("", "0")
    )
    result["model_applicability"] = result["model_applicability"].fillna("All").replace("", "All").astype(str)
    return result


def _cell_str(val: object) -> str:
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (ValueError, TypeError):
        pass
    return str(val).strip()


def _format_responsibility_target(
    responsibility: object,
    target_completion_date: object,
    fallback: object = "",
) -> str:
    resp = _cell_str(responsibility)
    tgt = _cell_str(target_completion_date)
    if resp and tgt:
        return f"{resp} | {tgt}"
    if tgt:
        return f"Target: {tgt}"
    if resp:
        return resp
    return _cell_str(fallback)


def export_workbook(project_id: str, scenario_id: str | None = None) -> bytes:
    project = get_project(project_id)
    scenario = get_planning_scenario(project_id, scenario_id) if scenario_id else None
    parts = project_table("parts", project_id, "part_number")
    if scenario_id and not parts.empty:
        scenario_active_ids = active_part_ids(project_id, scenario_id)
        parts = parts.loc[parts["id"].astype(str).isin(scenario_active_ids)].copy()
    elements = project_table("work_elements", project_id, "sequence", scenario_id=scenario_id)
    concerns = project_table("concerns", project_id, "created_at")
    fishbone = project_table("fishbone_nodes", project_id, "sequence")
    framework_sections = assembly_sections(project_id)
    framework_parts = fishbone_part_assignments(project_id, scenario_id)
    source_records = pits_records(project_id)
    source_revisions = pits_revisions(project_id)
    models = project_models(project_id)
    material_consumption = (
        material_consumption_for_scenario(project_id, scenario_id)
        if scenario_id else pd.DataFrame()
    )
    confirmed_fishbone = fishbone[fishbone["review_status"] == "Confirmed"] if "review_status" in fishbone.columns else fishbone.copy()
    summary = pd.DataFrame([project]).drop(columns=["id"], errors="ignore")
    scenario_summary = pd.DataFrame([scenario]).drop(
        columns=["id", "project_id", "parent_scenario_id"], errors="ignore"
    ) if scenario else pd.DataFrame()
    for frame in (summary, scenario_summary):
        if not frame.empty:
            unit_key = str(frame.iloc[0]["takt_time_unit"])
            frame["takt_time"] = seconds_to_display(
                frame.iloc[0]["takt_time_s"], unit_key
            )
            frame["takt_unit"] = time_unit(unit_key).label
    export_elements = elements.copy()
    lucid_columns = [
        "sequence", "station", "operation", "description", "cycle_time_s", "part_number", "tool", "torque",
        "quality_requirement", "ergo_requirement", "location", "unit_orientation", "conveyor_height_in",
        "platform_height_in", "pit_depth_in", "model_applicability", "status", "output_assembly_number",
        "output_assembly_name",
    ]
    lucid = export_elements.reindex(columns=lucid_columns)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Project", index=False)
        if not scenario_summary.empty:
            scenario_summary.to_excel(writer, sheet_name="Planning Scenario", index=False)
        parts.drop(columns=["project_id"], errors="ignore").to_excel(writer, sheet_name="Parts", index=False)
        export_elements.drop(columns=["project_id", "scenario_id"], errors="ignore").to_excel(
            writer, sheet_name="Work Elements", index=False
        )
        concerns.drop(columns=["project_id"], errors="ignore").to_excel(writer, sheet_name="Concerns", index=False)
        fishbone.drop(columns=["project_id"], errors="ignore").to_excel(writer, sheet_name="MBOM Review", index=False)
        confirmed_fishbone.drop(columns=["project_id"], errors="ignore").to_excel(
            writer, sheet_name="Assembly Fishbone", index=False
        )
        framework_sections.drop(columns=["project_id"], errors="ignore").to_excel(
            writer, sheet_name="Fishbone Sections", index=False
        )
        framework_parts.drop(columns=["project_id"], errors="ignore").to_excel(
            writer, sheet_name="Fishbone Parts", index=False
        )
        source_records.drop(columns=["project_id"], errors="ignore").to_excel(writer, sheet_name="PITS Current", index=False)
        source_revisions.to_excel(writer, sheet_name="PITS Revision History", index=False)
        models.drop(columns=["project_id"], errors="ignore").to_excel(writer, sheet_name="Models", index=False)
        if not material_consumption.empty:
            material_consumption.drop(
                columns=["group_id", "process_element_id", "section_id"], errors="ignore"
            ).to_excel(writer, sheet_name="Material Consumption", index=False)
        lucid.to_excel(writer, sheet_name="Lucid Data Link", index=False)
        # Quality Requirements & Assignments
        try:
            from utils import quality_store
            qr_df = quality_store.quality_requirements_table(project_id)
            if not qr_df.empty:
                qr_df.drop(columns=["project_id"], errors="ignore").to_excel(
                    writer, sheet_name="Quality Requirements", index=False
                )
            if scenario_id:
                qa_df = quality_store.quality_assignments_table(project_id, scenario_id)
                if not qa_df.empty:
                    qa_df.drop(columns=["project_id", "scenario_id"], errors="ignore").to_excel(
                        writer, sheet_name="Quality Assignments", index=False
                    )
        except Exception:
            pass

        # PFMEA
        if scenario_id:
            try:
                from utils import pfmea_store
                pfmea_df = pfmea_store.pfmea_flat_rows(project_id, scenario_id)
                if not pfmea_df.empty:
                    pfmea_export = pfmea_df.copy()
                    pfmea_export["responsibility_target"] = pfmea_export.apply(
                        lambda r: _format_responsibility_target(
                            r.get("responsibility"),
                            r.get("target_completion_date"),
                            r.get("responsibility_target"),
                        ),
                        axis=1,
                    )
                    pfmea_cols = [
                        "item_number", "process_function", "potential_failure_mode", "potential_effects",
                        "severity", "classification", "potential_causes", "occurrence",
                        "prevention_controls", "detection_controls", "detection", "rpn",
                        "recommended_action", "responsibility_target", "actions_taken",
                        "resulting_severity", "resulting_occurrence", "resulting_detection", "resulting_rpn",
                    ]
                    pfmea_view = pfmea_export[[c for c in pfmea_cols if c in pfmea_export.columns]].copy()
                    pfmea_view.rename(columns={
                        "item_number": "Item #", "process_function": "Process Function",
                        "potential_failure_mode": "Potential Failure Mode",
                        "potential_effects": "Potential Effect(s) of Failure", "severity": "Severity",
                        "classification": "Classification", "potential_causes": "Potential Causes(s) of Failure",
                        "occurrence": "Occurrence", "prevention_controls": "Current Process Controls — Prevention",
                        "detection_controls": "Current Process Controls — Detection", "detection": "Detection",
                        "rpn": "RPN", "recommended_action": "Recommended Action",
                        "responsibility_target": "Responsibility & Target Completion Date",
                        "actions_taken": "Actions Taken", "resulting_severity": "Resulting Severity",
                        "resulting_occurrence": "Resulting Occurrence",
                        "resulting_detection": "Resulting Detection", "resulting_rpn": "Resulting RPN",
                    }).to_excel(writer, sheet_name="PFMEA", index=False)
            except Exception:
                pass

        # Control Plan
        if scenario_id:
            try:
                from utils import control_plan_store
                cp_df = control_plan_store.control_plan_projection(project_id, scenario_id)
                if not cp_df.empty:
                    cp_cols = [
                        "pr_number", "station_pitch", "op_id", "machine_fixture_operation",
                        "characteristic_suffix", "characteristic_placement",
                        "product_part_characteristic", "process_characteristic", "classification",
                        "specification_requirement", "measurement_evaluation",
                        "sample_size", "sample_frequency", "who", "control_method", "decision_rule",
                    ]
                    cp_view = cp_df[[c for c in cp_cols if c in cp_df.columns]].copy()
                    cp_view.rename(columns={
                        "pr_number": "Pr. Nº", "station_pitch": "Station / Pitch",
                        "op_id": "Op ID", "machine_fixture_operation": "Machine/Fixt. & Operation",
                        "characteristic_suffix": "Characteristic suffix",
                        "characteristic_placement": "Characteristic type",
                        "product_part_characteristic": "Product / Part characteristic",
                        "process_characteristic": "Process characteristic", "classification": "CL",
                        "specification_requirement": "Specification / Requirement",
                        "measurement_evaluation": "Measurement / Evaluation",
                        "sample_size": "Sample size", "sample_frequency": "Sample frequency",
                        "who": "Who", "control_method": "Control method",
                        "decision_rule": "Decision rule / corrective action and reference documents",
                    }).to_excel(writer, sheet_name="Control Plan", index=False)
            except Exception:
                pass

        # Traceability Matrix
        if scenario_id:
            try:
                from utils import traceability_store
                mat = traceability_store.cross_functional_traceability_matrix(project_id, scenario_id)
                mat_rows = mat.get("rows", [])
                if mat_rows:
                    pd.DataFrame(mat_rows).drop(
                        columns=["project_id", "scenario_id", "work_element_id", "quality_assignment_id",
                                 "quality_requirement_id", "pfmea_entry_id", "control_plan_item_id"],
                        errors="ignore",
                    ).to_excel(writer, sheet_name="Traceability Matrix", index=False)
            except Exception:
                pass
        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for column_cells in worksheet.columns:
                width = min(max(len(str(cell.value or "")) for cell in column_cells) + 2, 45)
                worksheet.column_dimensions[column_cells[0].column_letter].width = width
    return output.getvalue()


def export_pfmea_to_company_template(
    project_id: str,
    scenario_id: str | None = None,
    rows: pd.DataFrame | None = None,
    control_labels: dict[str, str] | None = None,
    prepared_by: str = "",
) -> bytes:
    """Export PFMEA rows into the official company FRM-GEA-QYS-033 Excel template (PFMEA-A sheet)."""
    import openpyxl

    project = (get_project(project_id) if project_id else None) or {}
    if rows is None:
        from utils.pfmea_store import pfmea_flat_rows
        rows = pfmea_flat_rows(project_id, scenario_id) if scenario_id else pd.DataFrame()

    control_labels = control_labels or {}
    template_path = COMPANY_PFMEA_TEMPLATE_PATH
    if template_path.exists():
        wb = openpyxl.load_workbook(template_path)
    else:
        wb = openpyxl.Workbook()
        ws_default = wb.active
        ws_default.title = "PFMEA-A"

    if "PFMEA-A" in wb.sheetnames:
        ws = wb["PFMEA-A"]
    else:
        ws = wb.active

    # Header block
    proj_name = str(project.get("name") or "PFMEA")
    ws["D10"] = proj_name
    ws["I10"] = "Assembly"
    ws["O6"] = f"PFMEA-{proj_name}"
    ws["O8"] = prepared_by or str(project.get("lead") or "")
    created = str(project.get("created_at") or "")[:10]
    ws["O10"] = created if created else datetime.now().strftime("%Y-%m-%d")
    ws["O12"] = datetime.now().strftime("%Y-%m-%d")
    team = str(project.get("team") or "")
    if team:
        ws["C14"] = team

    def _int_val(val):
        if val is None or val == "":
            return None
        try:
            if pd.isna(val):
                return None
        except (TypeError, ValueError):
            pass
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return None

    def _fmt_ctrl(val):
        if val is None:
            return ""
        if isinstance(val, (list, tuple, set)) or hasattr(val, "__iter__") and not isinstance(val, (str, bytes)):
            res = []
            for item in val:
                s = str(item).strip()
                if control_labels and s in control_labels:
                    res.append(control_labels[s])
                elif s.startswith("manual:"):
                    res.append(s[7:])
                elif s:
                    res.append(s)
            return "\n".join(res)
        try:
            if pd.isna(val):
                return ""
        except (ValueError, TypeError):
            pass
        return str(val).strip()

    start_row = 21
    for idx, (_, row) in enumerate(rows.iterrows()):
        r = start_row + idx
        ws.cell(r, 1, _cell_str(row.get("item_number")))
        ws.cell(r, 2, _cell_str(row.get("process_function")))
        ws.cell(r, 3, _cell_str(row.get("potential_failure_mode")))
        ws.cell(r, 4, _cell_str(row.get("potential_effects")))
        ws.cell(r, 5, _int_val(row.get("severity")))
        ws.cell(r, 6, _cell_str(row.get("classification")))
        ws.cell(r, 7, _cell_str(row.get("potential_causes")))
        ws.cell(r, 8, _int_val(row.get("occurrence")))
        ws.cell(r, 9, _fmt_ctrl(row.get("prevention_controls")))
        ws.cell(r, 10, _fmt_ctrl(row.get("detection_controls")))
        ws.cell(r, 11, _int_val(row.get("detection")))
        ws.cell(r, 12, f'=IF(E{r}<>"",E{r}*H{r}*K{r},"")')
        rec = _cell_str(row.get("recommended_action"))
        ws.cell(r, 13, rec if rec else f'=IF(E{r}<>"","None","")')
        ws.cell(
            r,
            14,
            _format_responsibility_target(
                row.get("responsibility"),
                row.get("target_completion_date"),
                row.get("responsibility_target"),
            ),
        )
        ws.cell(r, 15, _cell_str(row.get("actions_taken")))
        ws.cell(r, 16, _int_val(row.get("resulting_severity")))
        ws.cell(r, 17, _int_val(row.get("resulting_occurrence")))
        ws.cell(r, 18, _int_val(row.get("resulting_detection")))
        ws.cell(r, 19, f'=IF(P{r}<>"",P{r}*Q{r}*R{r},"")')

        if r > 54:
            for c in range(1, 20):
                ref_cell = ws.cell(54, c)
                target_cell = ws.cell(r, c)
                if ref_cell.has_style:
                    target_cell.font = copy.copy(ref_cell.font)
                    target_cell.border = copy.copy(ref_cell.border)
                    target_cell.fill = copy.copy(ref_cell.fill)
                    target_cell.alignment = copy.copy(ref_cell.alignment)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
