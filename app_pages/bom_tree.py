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
col_m_search, col_m_select, col_s, col_f = st.columns([1.1, 1.4, 1.6, 1.1], gap="small")

with col_m_search:
    model_search_query = st.text_input(
        "Search model #",
        placeholder="Type e.g. HPS15, GTE18...",
        key="model_tree_model_search",
        help="Type to search and filter official model numbers.",
    )

clean_m_search = (model_search_query or "").strip().upper()
last_m_search = st.session_state.get("_last_model_tree_search", "")

if clean_m_search:
    matched_model_keys = [
        k for k, v in model_options.items()
        if k != "all" and (clean_m_search in v.upper() or clean_m_search in k.upper())
    ]
    if matched_model_keys:
        dropdown_keys = matched_model_keys
        st.caption(f":material/check: {len(matched_model_keys)} model(s) found")
        curr = st.session_state.get("model_tree_selected_model")
        if clean_m_search != last_m_search or curr not in matched_model_keys:
            st.session_state["model_tree_selected_model"] = matched_model_keys[0]
    else:
        dropdown_keys = ["all"]
        st.caption(":material/search_off: No models matched")
        st.session_state["model_tree_selected_model"] = "all"
else:
    dropdown_keys = list(model_options.keys())
    curr = st.session_state.get("model_tree_selected_model")
    if curr not in dropdown_keys:
        st.session_state["model_tree_selected_model"] = "all"

st.session_state["_last_model_tree_search"] = clean_m_search

curr_selected = st.session_state.get("model_tree_selected_model")
selected_idx = dropdown_keys.index(curr_selected) if curr_selected in dropdown_keys else 0

with col_m_select:
    selected_model_id = st.selectbox(
        "Official model number",
        options=dropdown_keys,
        index=selected_idx,
        format_func=lambda k: model_options.get(k, k),
        key="model_tree_selected_model",
    )

with col_s:
    search_query = st.text_input(
        "Search parts in tree",
        placeholder="Part #, description, tracker...",
        key="model_tree_search",
        help="Type a part number, description, or tracker to highlight and pull up in the tree.",
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
q = (search_query or "").strip().lower()
clean_q = "".join(c for c in q if c.isalnum())
stat = (status_filter or "All items").strip()

matching_node_ids: set[str] = set()
filtered_nodes: list[dict[str, Any]] = []

for n in nodes:
    # Status filter match
    if stat == "Missing from Fishbone" and n["in_fishbone"]:
        continue
    if stat == "Missing from Parts Catalog" and n["in_catalog"]:
        continue
    if stat == "Placed in Fishbone" and not n["in_fishbone"]:
        continue

    # Search query match
    if q:
        pnum_str = str(n["part_number"]).lower()
        clean_pnum = "".join(c for c in pnum_str if c.isalnum())
        match_pnum = (q in pnum_str) or (len(clean_q) >= 3 and clean_q in clean_pnum)
        match_desc = q in str(n["description"]).lower()
        match_trk = q in str(n["child_tracker"]).lower()
        match_sec = any(q in str(s).lower() for s in n.get("fishbone_sections", []))
        if not (match_pnum or match_desc or match_trk or match_sec):
            continue

    matching_node_ids.add(n["id"])
    filtered_nodes.append(n)

# Build a lookup for quick selection
node_by_id = {n["id"]: n for n in nodes}

# State for selected node
selected_node_id = st.session_state.get("selected_model_tree_node_id")

# PULL UP THE PART: When the user searched or filtered, auto-select the first matching node!
if (q or stat != "All items") and matching_node_ids:
    if selected_node_id not in matching_node_ids:
        # Pick the first matching node in outline order
        for n in nodes:
            if n["id"] in matching_node_ids:
                selected_node_id = n["id"]
                st.session_state["selected_model_tree_node_id"] = selected_node_id
                break
elif not selected_node_id and nodes:
    selected_node_id = nodes[0]["id"]
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


# Search feedback banner
if q or stat != "All items":
    match_count = len(matching_node_ids)
    if match_count == 0:
        st.warning(f":material/search_off: No parts found matching '{search_query}'.")
    else:
        pulled_str = f" · Pulled up **{selected_node['part_number']}** in tree & properties" if selected_node else ""
        st.success(
            f":material/search_check: Found **{match_count}** matching item(s) in active model{pulled_str}."
        )

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
            "Click **▶** or folder to expand any group and view subassemblies. "
            "Single-click any part or subassembly to inspect its properties."
        )
        cad_model_tree(
            roots=roots,
            selected_id=selected_node_id,
            search_query=search_query,
            status_filter=status_filter,
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

        has_filter = bool(q or stat != "All items")
        descendant_matches: dict[str, bool] = {}

        def check_matches(n: dict[str, Any]) -> bool:
            self_m = n["id"] in matching_node_ids
            child_m = any(check_matches(c) for c in n.get("children", []))
            res = self_m or child_m
            descendant_matches[n["id"]] = res
            return res

        for r in roots:
            check_matches(r)

        def render_expander_branch(node: dict[str, Any], expand_all: bool) -> None:
            if has_filter and not descendant_matches.get(node["id"], False):
                return
            has_children = bool(node.get("children"))
            d = node["depth"]
            is_active = node["id"] == selected_node_id
            self_matches = node["id"] in matching_node_ids
            is_expanded = expand_all or (has_filter and descendant_matches.get(node["id"], False))

            if not node["in_catalog"]:
                status_txt = "🛑 Missing from Catalog"
            elif not node["in_fishbone"]:
                status_txt = "⚠️ Missing from Fishbone"
            else:
                sec_lbl = ", ".join(node["fishbone_sections"])
                status_txt = f"✅ Placed: {sec_lbl}"

            match_badge = " 🔍 MATCH" if self_matches else ""

            if has_children:
                sub_count = len(node["children"])
                expander_title = (
                    f"📁 L{d} [{node['child_tracker'] or '—'}] {node['part_number']} — {node['description']} "
                    f"(×{node['quantity']}) · {sub_count} sub-items{match_badge}"
                )
                with st.expander(expander_title, expanded=is_expanded):
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
                    bg_style = "background:#fff8c5; border-left:3px solid #d4a72c; padding:2px 6px; border-radius:3px;" if self_matches else ""
                    st.markdown(
                        f"<div style='padding-left:{indent_px}px; font-family:monospace; font-size:0.88rem; line-height:28px; {bg_style}'>"
                        f"📄 <strong>L{d}</strong> [{node['child_tracker'] or '—'}] "
                        f"<strong>{node['part_number']}</strong> &mdash; {node['description']} "
                        f"<span style='color:#666;'>&times;{node['quantity']}</span> "
                        f"<small style='margin-left:6px;'>[{status_txt}]</small>"
                        f"{match_badge}"
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
