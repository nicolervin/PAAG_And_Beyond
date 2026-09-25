"""BOM Tree page for viewing and managing model product structure.

Replaces Assembly Grid with an indented parent-child tree view sourced from
approved Fishbone, Parts Catalog, and manufacturing assembly data.
"""

import pandas as pd
import streamlit as st

from utils.scope_ui import page_title_with_scope
from utils.store import (
    audit_history,
    model_bom_tree_nodes,
    project_models,
)
from utils.table_ui import selectable_dataframe

page_title_with_scope("BOM Tree", scope="project")

project_id = st.session_state.get("project_id")
if not project_id:
    st.warning("Select or create a project first.")
    st.stop()

models_df = project_models(project_id)
if models_df.empty:
    st.info("Add official models in Model definitions to view the BOM Tree.")
    st.stop()

active_models = models_df.loc[models_df["active"].fillna(1).astype(bool)]
if active_models.empty:
    st.info("No active models found in this project. Activate or add models in Model definitions.")
    st.stop()

model_options = {
    str(row["id"]): (
        f"{row['model_number']} · {row['display_name']}".rstrip(" ·")
        if str(row.get("display_name") or "").strip()
        else str(row["model_number"])
    )
    for _, row in active_models.iterrows()
}

selected_model_id = st.selectbox(
    "Select model",
    options=list(model_options),
    format_func=lambda mid: model_options.get(mid, mid),
    key=f"bom_tree_selected_model_{project_id}",
    help="Choose an official model to display its approved product structure tree.",
)

try:
    tree_nodes = model_bom_tree_nodes(project_id, selected_model_id)
except ValueError as exc:
    st.error(str(exc))
    st.stop()

if not tree_nodes:
    st.info(
        "No approved product structure or Fishbone components have been placed for this model yet. "
        "Place parts into Fishbone sections or import PITS BOM data to build the tree."
    )
    st.stop()


def _format_traceability(node: dict) -> str:
    status = node.get("pits_sync_status") or ""
    updated_at = node.get("pits_quantity_updated_at")
    if status == "In sync" and updated_at:
        try:
            dt = pd.to_datetime(updated_at, errors="coerce")
            if pd.notna(dt):
                return f"Updated from PITS on {dt.strftime('%b %d, %Y')}"
        except Exception:
            pass
    if status and status not in ("Not linked", "In sync"):
        return status
    return ""


# Metric summary cards
total_items = len(tree_nodes)
total_assemblies = sum(1 for n in tree_nodes if n["node_type"] in ("Top-level packaged unit", "Assembly"))
total_components = sum(1 for n in tree_nodes if n["node_type"] in ("Component", "Fishbone Part"))
represented_sections = {n["built_section_name"] for n in tree_nodes if n.get("built_section_name")}

metric_cols = st.columns(4)
metric_cols[0].metric("Total tree items", total_items)
metric_cols[1].metric("Assemblies", total_assemblies)
metric_cols[2].metric("Components / Parts", total_components)
metric_cols[3].metric("Fishbone sections", len(represented_sections))

st.markdown("---")

filter_col1, filter_col2, filter_col3 = st.columns([2.5, 1.5, 1])
search_query = filter_col1.text_input(
    "Search parts, assemblies, or uses",
    placeholder="Type part number, name, or use...",
    key=f"bom_tree_search_{project_id}",
).strip().lower()

all_sections = sorted(list(represented_sections))
section_filter = filter_col2.selectbox(
    "Filter by section",
    options=["All sections"] + all_sections,
    key=f"bom_tree_sec_filter_{project_id}",
)

view_mode = filter_col3.radio(
    "View format",
    ["Tree", "Table"],
    horizontal=True,
    key=f"bom_tree_view_mode_{project_id}",
)

# Apply filters
filtered_nodes = tree_nodes
if section_filter != "All sections":
    filtered_nodes = [
        n for n in filtered_nodes
        if n.get("built_section_name") == section_filter
        or n.get("installed_section_name") == section_filter
    ]

if search_query:
    filtered_nodes = [
        n for n in filtered_nodes
        if search_query in n["part_number"].lower()
        or search_query in n["part_name"].lower()
        or search_query in n.get("use_description", "").lower()
        or search_query in n.get("category_name", "").lower()
    ]

if not filtered_nodes:
    st.info("No items match the current search and section filters.")
else:
    if view_mode == "Table":
        table_rows = []
        for n in filtered_nodes:
            indent = "    " * (n["depth"] - 1) + ("└─ " if n["depth"] > 1 else "")
            table_rows.append(
                {
                    "Structure": f"{indent}{n['part_number']} · {n['part_name']}",
                    "Depth": f"Level {n['depth']}",
                    "Part number": n["part_number"],
                    "Part Name": n["part_name"],
                    "Type": n["node_type"],
                    "Quantity": n["quantity"],
                    "Built section": n["built_section_name"],
                    "Installed section": n["installed_section_name"] or "—",
                    "Use / installation location": n["use_description"] or "—",
                    "PITS traceability": _format_traceability(n) or "—",
                }
            )
        table_df = pd.DataFrame(table_rows)
        selectable_dataframe(
            table_df,
            key=f"bom_tree_table_view_{project_id}",
            hide_index=True,
            column_config={
                "Structure": st.column_config.TextColumn("Product structure tree", width="large"),
                "Depth": st.column_config.TextColumn("Depth", width="small"),
                "Part number": st.column_config.TextColumn("Part number", width="medium"),
                "Part Name": st.column_config.TextColumn("Part Name", width="large"),
                "Type": st.column_config.TextColumn("Type", width="small"),
                "Quantity": st.column_config.NumberColumn("Quantity", format="%g", width="small"),
                "Built section": st.column_config.TextColumn("Built section", width="medium"),
                "Installed section": st.column_config.TextColumn("Installed section", width="medium"),
                "Use / installation location": st.column_config.TextColumn("Use / installation location", width="large"),
                "PITS traceability": st.column_config.TextColumn("PITS traceability", width="medium"),
            },
        )
    else:
        # Tree card/row view
        st.caption(
            "Product structure hierarchy for selected model. Quantities are read-only and synchronized from PITS/Fishbone."
        )

        # Header row
        h_cols = st.columns([3.5, 1.2, 0.8, 1.5, 1.5, 2.0, 1.5])
        h_cols[0].markdown("**Tree item (Part / Assembly)**")
        h_cols[1].markdown("**Type**")
        h_cols[2].markdown("**Quantity**")
        h_cols[3].markdown("**Built section**")
        h_cols[4].markdown("**Installed section**")
        h_cols[5].markdown("**Use / location**")
        h_cols[6].markdown("**Traceability**")

        icon_by_type = {
            "Top-level packaged unit": ":material/inventory_2:",
            "Assembly": ":material/precision_manufacturing:",
            "Component": ":material/category:",
            "Fishbone Part": ":material/account_tree:",
            "Fishbone Section": ":material/folder:",
        }

        for n in filtered_nodes:
            depth = n["depth"]
            icon = icon_by_type.get(n["node_type"], ":material/circle:")
            trace_label = _format_traceability(n)

            # Container for row
            with st.container(border=True):
                r_cols = st.columns([3.5, 1.2, 0.8, 1.5, 1.5, 2.0, 1.5])

                # Indentation prefix
                indent_str = "&nbsp;&nbsp;&nbsp;&nbsp;" * (depth - 1)
                tree_symbol = "└─ " if depth > 1 else ""
                part_display = f"{indent_str}{tree_symbol}{icon} **{n['part_number']}**"
                if n["part_name"]:
                    part_display += f" · {n['part_name']}"

                r_cols[0].markdown(part_display, unsafe_allow_html=True)
                r_cols[1].markdown(f"`{n['node_type']}`")
                qty_display = f"{n['quantity']:g}" if n["node_type"] != "Fishbone Section" else f"{int(n['quantity'])} parts"
                r_cols[2].markdown(qty_display)
                r_cols[3].markdown(n["built_section_name"] or "—")
                r_cols[4].markdown(n["installed_section_name"] or "—")
                r_cols[5].markdown(n["use_description"] or "—")
                if trace_label:
                    r_cols[6].caption(f":material/history: {trace_label}")
                else:
                    r_cols[6].markdown("—")

st.markdown("---")
with st.expander("Audit history", expanded=False):
    history = audit_history(project_id, "BOM Tree", limit=50)
    if history.empty:
        history = audit_history(project_id, "Assembly grid", limit=50)
    if history.empty:
        st.caption("No BOM Tree history has been recorded yet.")
    else:
        st.dataframe(history.drop(columns=["details"], errors="ignore"), hide_index=True)
