"""Model Tree page for view-only product structure derived from PITS BOM tab.

Provides an interactive CAD-browser-style Model Tree derived directly from
imported PITS BOM Levels (Level 1–11), filterable by official model, with
reconciliation flags identifying parts missing from the Parts Catalog and/or
missing from the Fishbone diagram, and a Properties inspector panel.
"""

from typing import Any
import pandas as pd
import streamlit as st

from utils.scope_ui import page_title_with_scope
from utils.store import (
    pits_bom_model_tree,
    project_models,
)

page_title_with_scope("Model Tree", scope="project")
st.caption(
    "View-only product structure derived directly from PITS BOM tab Levels (1–11), "
    "interactive by official model, with gap reconciliation against the Parts Catalog and Fishbone diagram."
)

project_id = st.session_state.get("project_id")
if not project_id:
    st.warning("Select or create a project first.")
    st.stop()

# 1. Model selection
models_df = project_models(project_id)
model_options: dict[str, str] = {"all": "All models (Master BOM)"}
if not models_df.empty:
    active_models = models_df.loc[models_df["active"].fillna(1).astype(bool)]
    for _, row in active_models.iterrows():
        disp = str(row.get("display_name") or "").strip()
        num = str(row.get("model_number") or "").strip()
        label = f"{num} · {disp}".rstrip(" ·") if disp else num
        model_options[str(row["id"])] = label

# Top filter bar
col_m, col_s, col_f = st.columns([1.5, 1.5, 1.2], gap="small")
with col_m:
    selected_model_id = st.selectbox(
        "Official model number",
        options=list(model_options.keys()),
        format_func=lambda k: model_options[k],
        key="model_tree_selected_model",
    )
with col_s:
    search_query = st.text_input(
        "Search Model Browser",
        placeholder="Filter by part number, description, or tracker...",
        key="model_tree_search",
    )
with col_f:
    status_filter = st.selectbox(
        "Reconciliation status",
        options=[
            "All items",
            "Missing from Fishbone",
            "Missing from Parts Catalog",
            "Placed in Fishbone",
        ],
        key="model_tree_status_filter",
    )

# 2. Fetch tree data
tree_data = pits_bom_model_tree(project_id, selected_model_id)
nodes = tree_data["nodes"]
roots = tree_data["roots"]
metrics = tree_data["metrics"]

if not nodes:
    st.info(
        ":material/account_tree: No PITS BOM occurrences found for this project. "
        "Import a PITS workbook with a BOM tab via **Import/Export Projects** to explore the Model Tree."
    )
    st.stop()

# 3. Summary Metric Cards
m_col1, m_col2, m_col3, m_col4 = st.columns(4)
with m_col1:
    st.metric("Total items in tree", metrics["total"])
with m_col2:
    st.metric("Placed in Fishbone", metrics["placed_fishbone"])
with m_col3:
    st.metric("Missing from Fishbone", metrics["missing_fishbone"])
with m_col4:
    st.metric("Missing from Catalog", metrics["missing_catalog"])

st.markdown("---")

# 4. Filter nodes by search and status
filtered_nodes: list[dict[str, Any]] = []
q = (search_query or "").strip().lower()

for n in nodes:
    # Status filter match
    if status_filter == "Missing from Fishbone" and n["in_fishbone"]:
        continue
    if status_filter == "Missing from Parts Catalog" and n["in_catalog"]:
        continue
    if status_filter == "Placed in Fishbone" and not n["in_fishbone"]:
        continue

    # Search query match
    if q:
        match_pnum = q in str(n["part_number"]).lower()
        match_desc = q in str(n["description"]).lower()
        match_trk = q in str(n["child_tracker"]).lower()
        match_sec = any(q in str(s).lower() for s in n["fishbone_sections"])
        if not (match_pnum or match_desc or match_trk or match_sec):
            continue

    filtered_nodes.append(n)

# Build a lookup for quick selection
node_by_id = {n["id"]: n for n in nodes}

# State for selected node
selected_node_id = st.session_state.get("selected_model_tree_node_id")
if selected_node_id and selected_node_id not in node_by_id:
    selected_node_id = None
if not selected_node_id and filtered_nodes:
    selected_node_id = filtered_nodes[0]["id"]
    st.session_state["selected_model_tree_node_id"] = selected_node_id

selected_node = node_by_id.get(selected_node_id) if selected_node_id else None

from utils.cad_tree import cad_model_tree


def _component_event(component_key: str, event_name: str) -> dict:
    state = st.session_state.get(component_key, {}) or {}
    value = state.get(event_name) if hasattr(state, "get") else getattr(state, event_name, None)
    return dict(value or {})


cad_tree_key = "cad_model_tree_comp"


def on_cad_tree_select() -> None:
    event = _component_event(cad_tree_key, "select_node")
    if event and event.get("node_id"):
        st.session_state["selected_model_tree_node_id"] = str(event["node_id"])


# 5. Split CAD-Browser Layout
col_browser, col_props = st.columns([1.4, 1.0], gap="medium")

with col_browser:
    st.markdown("### :material/account_tree: Model Browser")

    tab_cad, tab_expanders, tab_table = st.tabs([
        "🌲 CAD Tree (Interactive)",
        "📂 Native Expanders",
        "📋 Data Table",
    ])

    with tab_cad:
        st.caption(
            "Click **▶** to expand any group number and view its subassemblies. "
            "Single-click any part or subassembly to inspect its properties."
        )
        cad_model_tree(
            roots=roots,
            selected_id=selected_node_id,
            key=cad_tree_key,
            on_select_node=on_cad_tree_select,
        )

    with tab_expanders:
        st.caption("Native Streamlit collapsible hierarchy. Click any group header to expand its subassemblies.")
        col_c1, col_c2 = st.columns([2, 1])
        with col_c1:
            expand_all_native = st.checkbox(
                "Expand all subassembly groups",
                value=False,
                key="model_tree_native_expand_all",
            )
        with col_c2:
            st.caption(f"{len(roots)} root assembly group(s)")

        def render_expander_branch(node: dict[str, Any], expand_all: bool) -> None:
            has_children = bool(node.get("children"))
            d = node["depth"]
            is_active = node["id"] == selected_node_id

            if not node["in_catalog"]:
                status_txt = "🛑 Missing from Catalog"
            elif not node["in_fishbone"]:
                status_txt = "⚠️ Missing from Fishbone"
            else:
                sec_lbl = ", ".join(node["fishbone_sections"])
                status_txt = f"✅ Placed: {sec_lbl}"

            if has_children:
                sub_count = len(node["children"])
                expander_title = (
                    f"📁 L{d} [{node['child_tracker'] or '—'}] {node['part_number']} — {node['description']} "
                    f"(×{node['quantity']}) · {sub_count} sub-items"
                )
                with st.expander(expander_title, expanded=expand_all):
                    c_btn, c_badge = st.columns([1.2, 4])
                    with c_btn:
                        if st.button("Inspect properties", key=f"exp_insp_{node['id']}", type="primary" if is_active else "secondary"):
                            st.session_state["selected_model_tree_node_id"] = node["id"]
                            st.rerun()
                    with c_badge:
                        st.caption(f"Status: {status_txt} · Tracker #{node['child_tracker']}")

                    for child in node["children"]:
                        render_expander_branch(child, expand_all)
            else:
                indent_px = max(0, (d - 1) * 16)
                c_item, c_act = st.columns([5, 1])
                with c_item:
                    st.markdown(
                        f"<div style='padding-left:{indent_px}px; font-family:monospace; font-size:0.88rem; line-height:28px;'>"
                        f"📄 <strong>L{d}</strong> [{node['child_tracker'] or '—'}] "
                        f"<strong>{node['part_number']}</strong> &mdash; {node['description']} "
                        f"<span style='color:#666;'>&times;{node['quantity']}</span> "
                        f"<small style='margin-left:6px;'>[{status_txt}]</small>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                with c_act:
                    if st.button("Inspect", key=f"leaf_insp_{node['id']}", type="primary" if is_active else "secondary"):
                        st.session_state["selected_model_tree_node_id"] = node["id"]
                        st.rerun()

        with st.container(height=560):
            for r in roots:
                render_expander_branch(r, expand_all_native)

    with tab_table:
        if not filtered_nodes:
            st.info("No items match the active search and status filter.")
        else:
            table_rows = []
            row_id_mapping = []

            for n in filtered_nodes:
                d = n["depth"]
                indent = "　" * max(0, d - 1)
                prefix = f"{indent}L{d} "

                if not n["in_catalog"]:
                    cat_badge = "❌ Missing"
                else:
                    cat_badge = "✅ In Catalog"

                if n["in_fishbone"]:
                    sec_str = ", ".join(n["fishbone_sections"])
                    fb_badge = f"✅ Placed ({sec_str})"
                else:
                    fb_badge = "⚠️ Missing"

                table_rows.append({
                    "Tree Structure": f"{prefix}{n['part_number']}",
                    "Description": n["description"],
                    "Level": f"L{d}",
                    "PITS Qty": n["quantity"],
                    "PITS Tracker": f"#{n['child_tracker']}" if n["child_tracker"] else "—",
                    "Fishbone Status": fb_badge,
                    "Parts Catalog": cat_badge,
                })
                row_id_mapping.append(n["id"])

            df_display = pd.DataFrame(table_rows)

            event = st.dataframe(
                df_display,
                selection_mode="single-row",
                on_select="rerun",
                hide_index=True,
                height=560,
                key="model_tree_df",
            )

            # Handle row click selection
            if event and event.selection and event.selection.rows:
                clicked_idx = event.selection.rows[0]
                if clicked_idx < len(row_id_mapping):
                    new_sel_id = row_id_mapping[clicked_idx]
                    if new_sel_id != st.session_state.get("selected_model_tree_node_id"):
                        st.session_state["selected_model_tree_node_id"] = new_sel_id
                        st.rerun()

# 6. Properties Inspector Panel (Right Column)
with col_props:
    with st.container(border=True):
        st.markdown("### :material/tune: Properties")

        if not selected_node:
            st.info(
                ":material/touch_app: Select an item in the Model Tree to inspect its properties.",
                icon=None,
            )
        else:
            p_num = selected_node["part_number"]
            p_desc = selected_node["description"]
            st.markdown(f"#### {p_num}")
            st.markdown(f"*{p_desc}*")

            # Status alert banner
            if not selected_node["in_catalog"]:
                st.error(
                    ":material/error: **Missing from Parts Catalog**\n\n"
                    "This part exists in the PITS BOM tree but has not been added to the project's Parts Catalog."
                )
            elif selected_node["in_fishbone"]:
                sec_list = ", ".join(selected_node["fishbone_sections"])
                st.success(
                    f":material/check_circle: **Placed in Fishbone**\n\n"
                    f"Assigned to Fishbone section: **{sec_list}**."
                )
            else:
                st.warning(
                    ":material/warning: **Missing from Fishbone**\n\n"
                    "This part exists in the Parts Catalog but has NOT been placed into any Fishbone section."
                )

            st.markdown("##### :material/account_tree: PITS BOM Hierarchy")
            p_col1, p_col2 = st.columns(2)
            with p_col1:
                st.write("**Hierarchy Level:**", f"Level {selected_node['depth']}")
                st.write("**PITS Tracker ID:**", f"#{selected_node['child_tracker']}" if selected_node['child_tracker'] else "—")
                st.write("**PITS Quantity:**", selected_node["quantity"])
            with p_col2:
                st.write("**Parent Tracker:**", f"#{selected_node['parent_tracker']}" if selected_node['parent_tracker'] else "— (Root)")
                st.write("**PITS Source Row:**", f"Row #{selected_node['source_row']}")
                st.write("**Review Status:**", selected_node["review_status"] or "Needs review")

            st.markdown("##### :material/inventory_2: Parts Catalog Master Data")
            if not selected_node["in_catalog"]:
                st.caption("No Parts Catalog record linked for this tracker number.")
            else:
                c_col1, c_col2 = st.columns(2)
                with c_col1:
                    st.write("**Make vs Buy:**", selected_node["make_buy"] or "—")
                    st.write("**Weight:**", f"{selected_node['weight_lb']} lb" if selected_node['weight_lb'] is not None else "—")
                    st.write("**Source Code:**", selected_node["source_code"] or "—")
                with c_col2:
                    st.write("**Technology Engineer:**", selected_node["technology_engineer"] or "—")
                    st.write("**Official Name:**", selected_node["official_name"] or "—")
                    st.write("**Applicability:**", selected_node["model_applicability"] or "All")

            st.markdown("##### :material/schema: Fishbone Placement")
            if not selected_node["in_fishbone"]:
                st.caption("Not placed in any Fishbone section.")
            else:
                f_col1, f_col2 = st.columns(2)
                with f_col1:
                    st.write("**Fishbone Section(s):**", ", ".join(selected_node["fishbone_sections"]))
                with f_col2:
                    uses_str = ", ".join(selected_node["fishbone_uses"]) if selected_node["fishbone_uses"] else "—"
                    st.write("**Use / Installation:**", uses_str)
