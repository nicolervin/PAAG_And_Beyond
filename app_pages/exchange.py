import streamlit as st

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
from utils.store import get_project, import_fishbone_nodes, import_pits_id_snapshot, upsert_part


project_id = st.session_state.get("project_id")
st.title("Import and export")
st.caption("Start from a draft BOM and publish a stable, tabular snapshot for Excel or Lucid data linking.")
if not project_id:
    st.stop()

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
                st.dataframe(preview[:50], hide_index=True, height=360,
                             column_config={"pits_id": st.column_config.TextColumn("PITS ID", pinned=True), "part_number": st.column_config.TextColumn("Part number", pinned=True)})
                with st.expander("Models in this workbook", icon=":material/precision_manufacturing:"):
                    model_preview = [{key: value for key, value in model.items() if key != "source_payload"} for model in models]
                    st.dataframe(model_preview, hide_index=True)
                if st.button("Import PITS snapshot", type="primary", icon=":material/upload:"):
                    summary = import_pits_id_snapshot(project_id, records, models)
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
                st.dataframe(parsed[["sequence", "depth", "part_number", "description", "level_evidence", "subsystem", "model_feature", "comments"]].head(50), hide_index=True,
                             column_config={"depth": st.column_config.NumberColumn("Proposed depth"), "level_evidence": st.column_config.TextColumn("Uninterpreted Level values", width="large")})
                replace_existing = st.toggle("Replace the current fishbone", value=True, help="Turn this off to append another PITS section or model family.")
                if st.button("Send PITS candidates to MBOM review", type="primary", icon=":material/upload:"):
                    count = import_fishbone_nodes(project_id, parsed, replace=replace_existing)
                    st.success(f"Sent {count:,} source occurrences to MBOM review. No candidate was accepted into the part catalog automatically.", icon=":material/check_circle:")
                st.stop()
            suggestions = suggest_mapping(raw.columns)
            options = [None] + raw.columns.tolist()
            st.caption(f"{len(raw):,} rows found. Confirm the column mapping before importing.")
            mapping = {}
            for target, label in [("part_number", "Part number"), ("description", "Description"), ("quantity", "Quantity"), ("revision", "Revision"), ("model_applicability", "Model applicability")]:
                suggested = suggestions[target]
                mapping[target] = st.selectbox(label, options, index=options.index(suggested) if suggested in options else 0, key=f"map_{target}")
            preview = mapped_bom(raw, mapping)
            st.dataframe(preview.head(20), hide_index=True)
            if st.button("Import parts", type="primary", icon=":material/upload:"):
                if not mapping["part_number"]:
                    st.error("Choose a part-number column.")
                else:
                    for row in preview.to_dict("records"):
                        upsert_part(project_id, {**row, "source": "BOM import"})
                    st.success(f"Imported or updated {len(preview):,} parts.", icon=":material/check_circle:")
        except Exception as exc:
            st.error(f"Could not read this file: {exc}")

with export_col.container(border=True):
    st.subheader("Export planning snapshot")
    st.write("The workbook contains project, confirmed parts, Manufacturing BOM review, work elements, and concerns sheets, plus a flattened **Lucid Data Link** sheet.")
    st.caption("This is a snapshot export. A later release can add a controlled sync and Lucid-specific identifier strategy.")
    project = get_project(project_id)
    workbook = export_workbook(project_id)
    safe_name = "".join(char if char.isalnum() or char in "-_" else "_" for char in project["name"])
    st.download_button("Download Excel workbook", workbook, file_name=f"{safe_name}_rev_{project['revision']}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", icon=":material/download:")
