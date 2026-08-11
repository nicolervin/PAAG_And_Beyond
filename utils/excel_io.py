from __future__ import annotations

from io import BytesIO
import re
from datetime import date, datetime

import pandas as pd

from utils.store import (
    assembly_sections,
    fishbone_part_assignments,
    get_project,
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


def read_bom(uploaded_file, sheet_name=0) -> pd.DataFrame:
    suffix = uploaded_file.name.lower()
    if suffix.endswith((".csv", ".txt", ".tsv")):
        separator = "\t" if suffix.endswith((".txt", ".tsv")) else ","
        return pd.read_csv(uploaded_file, sep=separator, dtype=str, keep_default_na=False)
    return pd.read_excel(uploaded_file, sheet_name=sheet_name)


def is_pits_format(df: pd.DataFrame) -> bool:
    normalized = {normalize_header(column) for column in df.columns}
    return {"intracker", "partnumber", "description", "level1", "level2"}.issubset(normalized)


def has_pits_id_sheets(uploaded_file) -> bool:
    if not uploaded_file.name.lower().endswith((".xlsx", ".xlsm")):
        return False
    workbook = pd.ExcelFile(BytesIO(uploaded_file.getvalue()))
    sheets = {sheet.lower() for sheet in workbook.sheet_names}
    return {"part_tracker", "models"}.issubset(sheets)


def _clean_value(value):
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _normalized_row(row: pd.Series) -> dict[str, object]:
    return {normalize_header(column): _clean_value(value) for column, value in row.items()}


def parse_pits_id_workbook(uploaded_file) -> tuple[list[dict], list[dict]]:
    content = BytesIO(uploaded_file.getvalue())
    parts = pd.read_excel(content, sheet_name="part_tracker", dtype=object)
    content.seek(0)
    models_df = pd.read_excel(content, sheet_name="models", header=1, dtype=object)

    records = []
    for source_index, row in parts.iterrows():
        source = _normalized_row(row)
        pits_id = str(source.get("idnumber", "")).strip()
        if not pits_id:
            continue
        records.append({
            "pits_id": pits_id,
            "source_row": int(source_index) + 2,
            "part_number": str(source.get("partnumber", "")).strip(),
            "description": str(source.get("description", "")).strip(),
            "used_bom": str(source.get("usedbom", "")).strip(),
            "status": str(source.get("baseinfostatus", "")).strip(),
            "subsystem": str(source.get("subsystem", "")).strip(),
            "design_maturity": str(source.get("designmaturity", "")).strip(),
            "comments": str(source.get("comments", "")).strip(),
            "workstation": str(source.get("factoryworkstationlocation", "")).strip(),
            "source_payload": source,
        })

    models = []
    for _, row in models_df.iterrows():
        source = _normalized_row(row)
        model_number = str(source.get("modelnumber", "")).strip()
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
        result[target] = df[source] if source else (1 if target == "quantity" else "")
    result["part_number"] = result["part_number"].fillna("").astype(str).str.strip()
    result = result[result["part_number"] != ""]
    result["description"] = result["description"].fillna("").astype(str)
    result["quantity"] = pd.to_numeric(result["quantity"], errors="coerce").fillna(1)
    result["revision"] = result["revision"].fillna("").astype(str)
    result["model_applicability"] = result["model_applicability"].fillna("All").replace("", "All").astype(str)
    return result


def export_workbook(project_id: str) -> bytes:
    project = get_project(project_id)
    parts = project_table("parts", project_id, "part_number")
    elements = project_table("work_elements", project_id, "sequence")
    concerns = project_table("concerns", project_id, "created_at")
    fishbone = project_table("fishbone_nodes", project_id, "sequence")
    framework_sections = assembly_sections(project_id)
    framework_parts = fishbone_part_assignments(project_id)
    source_records = pits_records(project_id)
    source_revisions = pits_revisions(project_id)
    models = project_models(project_id)
    confirmed_fishbone = fishbone[fishbone["review_status"] == "Confirmed"] if "review_status" in fishbone.columns else fishbone.copy()
    summary = pd.DataFrame([project]).drop(columns=["id"], errors="ignore")
    lucid_columns = [
        "sequence", "station", "operation", "description", "cycle_time_s", "part_number", "tool", "torque",
        "quality_requirement", "ergo_requirement", "location", "conveyor_height_mm", "platform_height_mm",
        "pit_depth_mm", "model_applicability", "status",
    ]
    lucid = elements.reindex(columns=lucid_columns)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Project", index=False)
        parts.drop(columns=["project_id"], errors="ignore").to_excel(writer, sheet_name="Parts", index=False)
        elements.drop(columns=["project_id"], errors="ignore").to_excel(writer, sheet_name="Work Elements", index=False)
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
        lucid.to_excel(writer, sheet_name="Lucid Data Link", index=False)
        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for column_cells in worksheet.columns:
                width = min(max(len(str(cell.value or "")) for cell in column_cells) + 2, 45)
                worksheet.column_dimensions[column_cells[0].column_letter].width = width
    return output.getvalue()
