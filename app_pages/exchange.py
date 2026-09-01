import streamlit as st
import pandas as pd

from utils.excel_io import (
    export_workbook,
    has_pits_id_sheets,
    is_pits_format,
    mapped_bom,
    parse_pits,
    parse_pits_id_workbook,
    read_bom,
    suggest_mapping,
)
from utils.store import (
    audit_history,
    get_planning_scenario,
    get_project,
    import_fishbone_nodes,
    import_pits_id_snapshot,
    pits_records,
    project_models,
    record_audit_event,
    upsert_part,
)
from utils.scope_ui import page_title_with_scope
from utils.table_filters import filter_table, split_filter_values
from utils.table_ui import selectable_dataframe


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
page_title_with_scope("Import PITS and export", scope="project")
st.caption("Start from a draft BOM and publish a stable, tabular snapshot for Excel or Lucid data linking.")
if not project_id:
    st.stop()

defined_models = project_models(project_id)
model_labels = {
    str(row["model_number"]): (str(row["display_name"]).strip() or "Familiar name not defined")
    for _, row in defined_models.iterrows()
}

import_col, export_col = st.columns(2)
with import_col.container(border=True):
    st.subheader("Import a BOM draft")
    uploaded = st.file_uploader("Excel, CSV, TSV, or pasted text file", type=["xlsx", "xlsm", "csv", "tsv", "txt"])
    if uploaded:
        try:
            if has_pits_id_sheets(uploaded):
                records, models = parse_pits_id_workbook(uploaded)
                st.success("ID-based PITS tracker detected", icon=":material/key:")
                summary_cols = st.columns(3)
                summary_cols[0].metric("PITS records", len(records))
                summary_cols[1].metric("Unique IDs", len({record["pits_id"] for record in records}))
                summary_cols[2].metric("Models", len(models))
                st.caption("ID Number is the stable source key. Re-imports create source revisions and flag changed MBOM candidates without overwriting IE decisions.")
                preview = [{key: value for key, value in record.items() if key != "source_payload"} for record in records]
                preview_table = filter_table(
                    pd.DataFrame(preview),
                    key="pits_import_preview_filters",
                    dropdown_columns=["status", "subsystem", "design_maturity", "workstation"],
                    search_columns=["pits_id", "part_number", "description", "comments", "subsystem"],
                )
                selectable_dataframe(preview_table.head(50), key="pits_import_preview_table", hide_index=True, height=360,
                             column_config={"pits_id": st.column_config.TextColumn("PITS ID", pinned=True), "part_number": st.column_config.TextColumn("Part number", pinned=True), "description": st.column_config.TextColumn("Part Name")})
                with st.expander("Models in this workbook", icon=":material/precision_manufacturing:"):
                    model_preview = [{key: value for key, value in model.items() if key != "source_payload"} for model in models]
                    model_preview_table = filter_table(
                        pd.DataFrame(model_preview),
                        key="pits_model_preview_filters",
                        dropdown_columns=["platform_size", "package_type", "base_model"],
                        search_columns=["model_number", "appearance", "sku_upc"],
                    )
                    selectable_dataframe(model_preview_table, key="pits_model_preview_table", hide_index=True)
                if st.button("Import PITS snapshot", type="primary", icon=":material/upload:"):
                    existing_pits = pits_records(project_id)
                    previous_revisions = {
                        str(row["pits_id"]): int(row["revision_no"])
                        for _, row in existing_pits.iterrows()
                    }
                    summary = import_pits_id_snapshot(project_id, records, models)
                    imported_pits = pits_records(project_id)
                    imported_ids = {str(record["pits_id"]).strip() for record in records}
                    created_revisions = []
                    updated_revisions = []
                    for _, row in imported_pits.iterrows():
                        pits_id = str(row["pits_id"])
                        if pits_id not in imported_ids:
                            continue
                        revision = int(row["revision_no"])
                        revision_detail = {"pits_id": pits_id, "revision_no": revision}
                        previous_revision = previous_revisions.get(pits_id)
                        if previous_revision is None:
                            created_revisions.append(revision_detail)
                        elif revision > previous_revision:
                            updated_revisions.append(revision_detail)
                    record_audit_event(
                        project_id,
                        "PITS snapshot",
                        "Import PITS snapshot",
                        len(records),
                        st.session_state.get("current_editor", ""),
                        {
                            "rows_imported": len(records),
                            "pits_revisions_created": created_revisions,
                            "pits_revisions_updated": updated_revisions,
                            "models_synchronized": summary["models"],
                            "unchanged_pits_records": summary["unchanged"],
                        },
                    )
                    st.success(
                        f"Imported {summary['new']} new IDs, detected {summary['changed']} revised IDs, "
                        f"left {summary['unchanged']} unchanged, and synchronized {summary['models']} models.",
                        icon=":material/check_circle:",
                    )
                st.stop()
            raw = read_bom(uploaded)
            if is_pits_format(raw):
                parsed = parse_pits(raw)
                st.success("PITS hierarchy detected", icon=":material/account_tree:")
                summary_cols = st.columns(3)
                summary_cols[0].metric("Rows", len(parsed))
                summary_cols[1].metric("Unique parts", parsed["part_number"].replace("", None).nunique())
                summary_cols[2].metric("Maximum level", int(parsed["depth"].max()) if not parsed.empty else 0)
                st.warning("Level cell contents are program-specific and will not be interpreted as quantities, sequence, or model codes. Proposed depth uses only the leftmost populated Level column and must be reviewed.", icon=":material/warning:")
                parsed_preview = filter_table(
                    parsed[["sequence", "depth", "part_number", "description", "level_evidence", "subsystem", "model_feature", "comments"]],
                    key="legacy_pits_preview_filters",
                    dropdown_columns=["depth", "subsystem", "model_feature"],
                    search_columns=["part_number", "description", "level_evidence", "comments"],
                )
                selectable_dataframe(parsed_preview.head(50), key="legacy_pits_preview_table", hide_index=True,
                             column_config={"depth": st.column_config.NumberColumn("Proposed depth"), "description": st.column_config.TextColumn("Part Name"), "level_evidence": st.column_config.TextColumn("Uninterpreted Level values", width="large")})
                replace_existing = st.toggle("Replace the current fishbone", value=True, help="Turn this off to append another PITS section or model family.")
                if st.button("Send PITS candidates to MBOM review", type="primary", icon=":material/upload:"):
                    count = import_fishbone_nodes(project_id, parsed, replace=replace_existing)
                    record_audit_event(
                        project_id,
                        "MBOM review",
                        "Send PITS candidates to MBOM review",
                        count,
                        st.session_state.get("current_editor", ""),
                        {
                            "candidates_sent": count,
                            "review_status": "Needs review",
                            "replaced_existing_fishbone": replace_existing,
                        },
                    )
                    st.success(f"Sent {count:,} source occurrences to MBOM review. No candidate was accepted into the part catalog automatically.", icon=":material/check_circle:")
                st.stop()
            suggestions = suggest_mapping(raw.columns)
            options = [None] + raw.columns.tolist()
            st.caption(f"{len(raw):,} rows found. Confirm the column mapping before importing.")
            mapping = {}
            for target, label in [("part_number", "Part number"), ("description", "Part Name"), ("quantity", "Quantity"), ("revision", "Revision"), ("model_applicability", "Model applicability")]:
                suggested = suggestions[target]
                mapping[target] = st.selectbox(label, options, index=options.index(suggested) if suggested in options else 0, key=f"map_{target}")
            preview = mapped_bom(raw, mapping)
            preview_for_display = preview.copy()
            preview_for_display["model_applicability"] = preview_for_display["model_applicability"].apply(
                lambda value: ", ".join(
                    "All models" if model.casefold() in {"all", "all models"} else model_labels.get(model, model)
                    for model in (split_filter_values(value) or ["All"])
                )
            )
            mapped_preview = filter_table(
                preview_for_display,
                key="mapped_bom_preview_filters",
                dropdown_columns=["revision", "model_applicability"],
                search_columns=["part_number", "description", "revision", "model_applicability"],
                multi_value_columns=["model_applicability"],
                universal_values={"model_applicability": ["All", "All models", ""]},
            )
            selectable_dataframe(
                mapped_preview.head(20),
                key="mapped_bom_preview_table",
                hide_index=True,
                column_config={"description": st.column_config.TextColumn("Part Name")},
            )
            if st.button("Import parts", type="primary", icon=":material/upload:"):
                if not mapping["part_number"]:
                    st.error("Choose a part-number column.")
                else:
                    for row in preview.to_dict("records"):
                        upsert_part(project_id, {**row, "source": "BOM import"})
                    record_audit_event(
                        project_id,
                        "Parts",
                        "Import parts",
                        len(preview),
                        st.session_state.get("current_editor", ""),
                        {
                            "parts_imported_or_updated": len(preview),
                            "source": "BOM import",
                        },
                    )
                    st.success(f"Imported or updated {len(preview):,} parts.", icon=":material/check_circle:")
        except Exception as exc:
            st.error(f"Could not read this file: {exc}")

with export_col.container(border=True):
    st.subheader("Export planning snapshot")
    st.write("The workbook contains project, confirmed parts, Manufacturing BOM review, work elements, and concerns sheets, plus a flattened **Lucid Data Link** sheet.")
    st.caption("This is a snapshot export. A later release can add a controlled sync and Lucid-specific identifier strategy.")
    project = get_project(project_id)
    workbook = export_workbook(project_id, scenario_id)
    scenario = get_planning_scenario(project_id, scenario_id) if scenario_id else None
    safe_name = "".join(char if char.isalnum() or char in "-_" else "_" for char in project["name"])
    revision_label = scenario["revision_label"] if scenario else project["revision"]
    st.download_button("Download Excel workbook", workbook, file_name=f"{safe_name}_rev_{revision_label}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", icon=":material/download:")


with st.expander("History", icon=":material/history:"):
    pits_history_tab, mbom_history_tab, parts_history_tab = st.tabs(
        ["PITS snapshots", "MBOM review", "Parts import"]
    )
    with pits_history_tab:
        pits_history = audit_history(project_id, "PITS snapshot", limit=50)
        if pits_history.empty:
            st.caption("No PITS snapshot history has been recorded yet.")
        else:
            selectable_dataframe(
                pits_history.drop(columns=["details"], errors="ignore"),
                key=f"exchange_pits_history_{project_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
    with mbom_history_tab:
        mbom_history = audit_history(project_id, "MBOM review", limit=50)
        if mbom_history.empty:
            st.caption("No MBOM review history has been recorded yet.")
        else:
            selectable_dataframe(
                mbom_history.drop(columns=["details"], errors="ignore"),
                key=f"exchange_mbom_history_{project_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
    with parts_history_tab:
        parts_import_history = audit_history(project_id, "Parts", limit=50)
        if not parts_import_history.empty:
            parts_import_history = parts_import_history.loc[
                parts_import_history["action"] == "Import parts"
            ].copy()
        if parts_import_history.empty:
            st.caption("No parts-import history has been recorded yet.")
        else:
            selectable_dataframe(
                parts_import_history.drop(columns=["details"], errors="ignore"),
                key=f"exchange_parts_import_history_{project_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
