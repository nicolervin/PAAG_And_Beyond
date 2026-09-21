from __future__ import annotations

from io import BytesIO
import re
from datetime import date, datetime

import pandas as pd

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
    else:
        for sheet_name in workbook.sheet_names:
            normalized = _normalized_sheet_name(sheet_name)
            if ("model" in normalized or "vehicle" in normalized) and "tracker" not in normalized:
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


def parse_pits_id_workbook(uploaded_file) -> tuple[list[dict], list[dict]]:
    content = BytesIO(uploaded_file.getvalue())
    workbook = pd.ExcelFile(content)
    tracker_sheet = _find_pits_sheet(workbook, type_name="part_tracker")
    model_sheet = _find_pits_sheet(workbook, type_name="models")
    if tracker_sheet is None or model_sheet is None:
        raise ValueError("This file does not contain the expected PITS tracker and model sheets.")

    content.seek(0)
    parts_raw = pd.read_excel(content, sheet_name=tracker_sheet, header=None, dtype=object)
    content.seek(0)
    models_raw = pd.read_excel(content, sheet_name=model_sheet, header=None, dtype=object)

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
        revision = _excel_column_value(row, "BL")
        source["source_code"] = source_code
        source["revision"] = revision
        records.append({
            "pits_id": pits_id,
            "source_row": int(source_index) + 2,
            "part_number": part_number or str(source.get("partnumber1", "")).strip(),
            "description": description,
            "revision": revision,
            "source_code": source_code,
            "used_bom": str(source.get("usedbom", "")).strip(),
            "status": str(source.get("baseinfostatus", "")).strip() or str(source.get("status", "")).strip(),
            "subsystem": str(source.get("subsystem", "")).strip(),
            "design_maturity": str(source.get("designmaturity", "")).strip(),
            "comments": str(source.get("comments", "")).strip(),
            "workstation": str(source.get("factoryworkstationlocation", "")).strip(),
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
        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for column_cells in worksheet.columns:
                width = min(max(len(str(cell.value or "")) for cell in column_cells) + 2, 45)
                worksheet.column_dimensions[column_cells[0].column_letter].width = width
    return output.getvalue()
