"""Model Tree page for view-only inspection and from-scratch BOM authoring.

Provides an interactive CAD-browser-style Model Tree derived from imported PITS BOM Levels (Level 1–11)
or authored from scratch per official model, with gap reconciliation against the Parts Catalog
and Fishbone diagram, and a Properties inspector panel.
"""

from pathlib import Path
from typing import Any
import pandas as pd
import streamlit as st

from utils.cad_tree import cad_model_tree
from utils.fishbone_visual import part_thumbnail
from utils.scope_ui import page_title_with_scope
from utils.store import (
    add_project_model,
    audit_history,
    get_manual_model_bom,
    pits_bom_model_tree,
    project_models,
    save_manual_model_bom,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    has_unsaved_table_changes,
    request_table_editor_reset,
)

page_title_with_scope("Model Tree", scope="project")
st.caption(
    "Interactive product structure and CAD-style Model Tree by official model, "
    "with BOM authoring from scratch and gap reconciliation against the Parts Catalog and Fishbone diagram."
)

project_id = st.session_state.get("project_id")
if not project_id:
    st.warning("Select or create a project first.")
    st.stop()

# 1. Official models
models_df = project_models(project_id)
if models_df.empty:
    st.info("No official models are defined for this project yet. Add your first official model number below to start building the Model Tree.")
    with st.expander(":material/add_circle: Add Official Model Number", expanded=True):
        with st.form("first_model_form"):
            m_num = st.text_input("Official Model Number *", placeholder="e.g. HPS15, GTE18...").strip()
            m_name = st.text_input("Display Name", placeholder="e.g. 15 cu.ft. Top Freezer").strip()
            if st.form_submit_button("Create Model", type="primary"):
                if not m_num:
                    st.error("Model number is required.")
                else:
                    try:
                        new_mid = add_project_model(project_id, m_num, m_name, "")
                        st.session_state["model_tree_selected_model"] = new_mid
                        st.success(f"Model '{m_num}' created!")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
    st.stop()

model_options: dict[str, str] = {"all": "All models (Master BOM)"}
active_models = models_df.loc[models_df["active"].fillna(1).astype(bool)]
for _, row in active_models.iterrows():
    disp = str(row.get("display_name") or "").strip()
    num = str(row.get("model_number") or "").strip()
    label = f"{num} · {disp}".rstrip(" ·") if disp else num
    model_options[str(row["id"])] = label

# Top bar: Model search & selection + Quick Add Model
col_m_search, col_m_select, col_m_add = st.columns([1.1, 1.5, 0.7], gap="small")

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

with col_m_add:
    st.write("")
    st.write("")
    with st.popover(":material/add: New Model", help="Quickly define a new official model"):
        with st.form("quick_add_model_popover"):
            m_num = st.text_input("Model Number *", placeholder="e.g. GTE19").strip()
            m_name = st.text_input("Display Name", placeholder="e.g. 19 cu.ft. Top Mount").strip()
            if st.form_submit_button("Add Model", type="primary"):
                if m_num:
                    try:
                        new_mid = add_project_model(project_id, m_num, m_name, "")
                        st.session_state["model_tree_selected_model"] = new_mid
                        st.success(f"Model '{m_num}' created!")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))


def _component_event(component_key: str, event_name: str) -> dict:
    state = st.session_state.get(component_key, {}) or {}
    value = state.get(event_name) if hasattr(state, "get") else getattr(state, event_name, None)
    return dict(value or {})


cad_tree_key = "cad_model_tree_comp"


def on_cad_tree_select() -> None:
    event = _component_event(cad_tree_key, "select_node")
    if event and event.get("node_id"):
        st.session_state["selected_model_tree_node_id"] = str(event["node_id"])


# Top tabs: View vs Author
tab_view, tab_author = st.tabs([
    "🌲 View Model Tree",
    "✏️ Build / Author BOM from Scratch",
])

# ==============================================================================
# TAB 1: VIEW MODEL TREE
# ==============================================================================
with tab_view:
    col_s, col_f = st.columns([1.6, 1.1], gap="small")
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

    tree_data = pits_bom_model_tree(project_id, selected_model_id)
    nodes = tree_data["nodes"]
    roots = tree_data["roots"]
    metrics = tree_data["metrics"]

    if not nodes:
        target_disp = model_options.get(selected_model_id, selected_model_id)
        st.info(
            f":material/account_tree: No BOM occurrences found for **{target_disp}**. "
            "You can switch to the **✏️ Build / Author BOM from Scratch** tab above to build the product structure from scratch, "
            "or import a PITS workbook with a BOM tab via **Import/Export PITS**."
        )
    else:
        # Metric Cards
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

        # Filter nodes
        q = (search_query or "").strip().lower()
        clean_q = "".join(c for c in q if c.isalnum())
        stat = (status_filter or "All items").strip()

        matching_node_ids: set[str] = set()
        filtered_nodes: list[dict[str, Any]] = []

        for n in nodes:
            if stat == "Missing from Fishbone" and n["in_fishbone"]:
                continue
            if stat == "Missing from Parts Catalog" and n["in_catalog"]:
                continue
            if stat == "Placed in Fishbone" and not n["in_fishbone"]:
                continue

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

        node_by_id = {n["id"]: n for n in nodes}
        selected_node_id = st.session_state.get("selected_model_tree_node_id")

        if (q or stat != "All items") and matching_node_ids:
            if selected_node_id not in matching_node_ids:
                for n in nodes:
                    if n["id"] in matching_node_ids:
                        selected_node_id = n["id"]
                        st.session_state["selected_model_tree_node_id"] = selected_node_id
                        break
        elif not selected_node_id and nodes:
            selected_node_id = nodes[0]["id"]
            st.session_state["selected_model_tree_node_id"] = selected_node_id

        selected_node = node_by_id.get(selected_node_id) if selected_node_id else None

        if q or stat != "All items":
            match_count = len(matching_node_ids)
            if match_count == 0:
                st.warning(f":material/search_off: No parts found matching '{search_query}'.")
            else:
                pulled_str = f" · Pulled up **{selected_node['part_number']}** in tree & properties" if selected_node else ""
                st.success(
                    f":material/search_check: Found **{match_count}** matching item(s) in active model{pulled_str}."
                )

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

                    has_photo = bool(node.get("image_path") and Path(str(node["image_path"])).is_file())
                    photo_badge = " 📷" if has_photo else ""
                    match_badge = " 🔍 MATCH" if self_matches else ""

                    if has_children:
                        sub_count = len(node["children"])
                        expander_title = (
                            f"📁 L{d} [{node['child_tracker'] or '—'}] {node['part_number']} — {node['description']} "
                            f"(×{node['quantity']}) · {sub_count} sub-items{photo_badge}{match_badge}"
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
                                f"{photo_badge}"
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

                        img_p = n.get("image_path", "")
                        has_img = bool(img_p and Path(str(img_p)).is_file())
                        photo_uri = part_thumbnail(img_p) if has_img else None

                        table_rows.append({
                            "Photo": photo_uri,
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
                        column_config={
                            "Photo": st.column_config.ImageColumn(
                                "Photo",
                                help="Part CAD thumbnail",
                            ),
                        },
                        selection_mode="single-row",
                        on_select="rerun",
                        hide_index=True,
                        height=560,
                        key="model_tree_df",
                    )

                    if event and event.selection and event.selection.rows:
                        clicked_idx = event.selection.rows[0]
                        if clicked_idx < len(row_id_mapping):
                            new_sel_id = row_id_mapping[clicked_idx]
                            if new_sel_id != st.session_state.get("selected_model_tree_node_id"):
                                st.session_state["selected_model_tree_node_id"] = new_sel_id
                                st.rerun()

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

                    img_p = selected_node.get("image_path")
                    img_file = Path(img_p) if img_p else None
                    rendered_img = False
                    if img_file and img_file.is_file():
                        try:
                            st.image(str(img_file), caption=f"{p_num} · CAD preview")
                            rendered_img = True
                        except Exception:
                            pass
                    if not rendered_img:
                        st.caption(":material/no_photography: No photo attached in Parts Catalog")

                    if not selected_node["in_catalog"]:
                        st.error(
                            ":material/error: **Missing from Parts Catalog**\n\n"
                            "This part exists in the Model Tree but has not been added to the project's Parts Catalog."
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

                    st.markdown("##### :material/account_tree: BOM Hierarchy")
                    p_col1, p_col2 = st.columns(2)
                    with p_col1:
                        st.write("**Hierarchy Level:**", f"Level {selected_node['depth']}")
                        st.write("**Tracker / ID:**", f"#{selected_node['child_tracker']}" if selected_node['child_tracker'] else "—")
                        st.write("**Quantity:**", selected_node["quantity"])
                    with p_col2:
                        st.write("**Parent Tracker:**", f"#{selected_node['parent_tracker']}" if selected_node['parent_tracker'] else "— (Root)")
                        st.write("**Source Row:**", f"Row #{selected_node['source_row']}")
                        st.write("**Review Status:**", selected_node["review_status"] or "Needs review")

                    st.markdown("##### :material/inventory_2: Parts Catalog Master Data")
                    if not selected_node["in_catalog"]:
                        st.caption("No Parts Catalog record linked.")
                    else:
                        c_col1, c_col2 = st.columns(2)
                        with c_col1:
                            st.write("**Subsystem:**", selected_node.get("subsystem") or "—")
                            st.write("**Design Maturity:**", selected_node.get("design_maturity") or selected_node.get("revision") or "—")
                            st.write("**Make vs Buy:**", selected_node.get("make_buy") or "—")
                            st.write("**Weight:**", f"{selected_node['weight_lb']} lb" if selected_node.get("weight_lb") is not None else "—")
                            st.write("**Source Code:**", selected_node.get("source_code") or "—")
                            st.write("**Part Code:**", selected_node.get("part_code") or "—")
                        with c_col2:
                            st.write("**Design Engineer:**", selected_node.get("design_engineer") or selected_node.get("technology_engineer") or "—")
                            st.write("**Factory Nickname:**", selected_node.get("factory_nickname") or selected_node.get("official_name") or "—")
                            st.write("**Applicability:**", selected_node.get("model_applicability") or "All")
                            st.write("**PPM:**", selected_node.get("ppm") or "—")
                            st.write("**Buyer / GCL:**", selected_node.get("buyer_gcl") or "—")
                            st.write("**PMQE / AQE:**", selected_node.get("pmqe_aqe") or "—")
                            st.write("**AME / Tooling:**", selected_node.get("ame_tooling_engineer") or "—")

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


# ==============================================================================
# TAB 2: BUILD / AUTHOR BOM FROM SCRATCH
# ==============================================================================
with tab_author:
    if selected_model_id == "all":
        st.warning(
            ":material/info: Model Tree BOM authoring is model-specific. "
            "Please select a specific official model number from the **Official model number** dropdown above to create or edit its BOM structure."
        )
    else:
        target_model_label = model_options.get(selected_model_id, selected_model_id)
        st.markdown(f"### ✏️ Author BOM Structure for **{target_model_label}**")
        st.caption(
            "Build the hierarchical BOM structure (Level 1–11) for this official model. "
            "Lower levels (e.g. L2, L3) are grouped under the nearest preceding shallower level (e.g. L1, L2). "
            "Use the **Spreadsheet Editor** to type or copy/paste rows, or the **Visual Tree Builder** for interactive outline assembly."
        )

        draft_key = f"_bom_draft_{project_id}_{selected_model_id}"
        if draft_key not in st.session_state:
            saved_bom = get_manual_model_bom(project_id, selected_model_id)
            if saved_bom:
                st.session_state[draft_key] = saved_bom
            else:
                st.session_state[draft_key] = [
                    {"level": 1, "part_number": "", "description": "", "quantity": 1.0}
                ]

        sub_grid, sub_builder = st.tabs([
            "📋 Spreadsheet Editor (Grid)",
            "🌳 Visual Tree Builder (Outline)",
        ])

        # --- Sub-tab A: Spreadsheet Editor ---
        with sub_grid:
            # ── Logical editor key + instance rotation (standard pattern) ──
            bom_editor_logical_key = f"bom_grid_editor_{selected_model_id}"
            bom_editor_key = apply_pending_table_editor_reset(bom_editor_logical_key)

            # Determine whether there are unsaved changes
            is_unsaved = has_unsaved_table_changes(bom_editor_key)

            # ── Action bar: left = checkbox, right = unsaved / undo / save ──
            bar_left, bar_right = st.columns([2.5, 2], gap="small")
            with bar_left:
                auto_add_grid = st.checkbox(
                    "Automatically add new parts to Parts Catalog",
                    value=True,
                    key=f"auto_add_grid_{selected_model_id}",
                    help="If checked, any part numbers not currently in the Parts Catalog will be created automatically.",
                )
            with bar_right:
                act_cols = st.columns([2, 1, 1.4], gap="small")
                with act_cols[0]:
                    if is_unsaved:
                        st.markdown(":orange[:material/warning: **Unsaved changes**]")
                with act_cols[1]:
                    if st.button(
                        "Undo",
                        icon=":material/undo:",
                        key=f"undo_bom_grid_{selected_model_id}",
                        help="Discard unsaved edits and reload from the last saved BOM",
                        disabled=not is_unsaved,
                    ):
                        request_table_editor_reset(bom_editor_logical_key)
                        st.rerun()
                with act_cols[2]:
                    save_clicked = st.button(
                        "Save BOM Structure",
                        icon=":material/save:",
                        type="primary",
                        key=f"save_bom_grid_{selected_model_id}",
                    )

            # ── Build initial DataFrame from persisted BOM (do NOT sync on each edit) ──
            current_draft = st.session_state.get(draft_key, [])
            df_editor_data = pd.DataFrame([
                {
                    "Level": int(it.get("level", 1) or 1),
                    "Part #": str(it.get("part_number", "") or ""),
                    "Description": str(it.get("description", "") or ""),
                    "Qty": float(it.get("quantity", 1.0) or 1.0),
                }
                for it in current_draft
            ])
            if df_editor_data.empty:
                df_editor_data = pd.DataFrame([{
                    "Level": 1, "Part #": "", "Description": "", "Qty": 1.0
                }])

            # ── Data editor — Level as NumberColumn so Excel paste works ──
            edited_df = st.data_editor(
                df_editor_data,
                column_config={
                    "Level": st.column_config.NumberColumn(
                        "Level",
                        min_value=1,
                        max_value=11,
                        step=1,
                        default=1,
                        format="%d",
                        help="Hierarchy Level (1–11)",
                    ),
                    "Part #": st.column_config.TextColumn(
                        "Part # / Group #",
                        help="Part number or Assembly / Group number (required to save)",
                    ),
                    "Description": st.column_config.TextColumn(
                        "Description",
                        help="Part description or name",
                    ),
                    "Qty": st.column_config.NumberColumn(
                        "Qty",
                        min_value=0.01,
                        step=1.0,
                        default=1.0,
                        format="%.2f",
                        help="Quantity per unit",
                    ),
                },
                num_rows="dynamic",
                hide_index=True,
                key=bom_editor_key,
                width="stretch",
            )

            # ── Save action ──
            if save_clicked:
                rows_to_save = []
                validation_errors = []
                for idx, r in edited_df.iterrows():
                    pn = str(r.get("Part #") or "").strip()
                    desc = str(r.get("Description") or "").strip()
                    qty_raw = r.get("Qty")
                    lvl_raw = r.get("Level")
                    # Skip completely blank rows silently
                    if not pn and not desc:
                        continue
                    if not pn:
                        validation_errors.append(f"Row {idx + 1}: Part # is required.")
                        continue
                    try:
                        lvl = int(float(lvl_raw)) if lvl_raw is not None else 1
                        lvl = max(1, min(11, lvl))
                    except (TypeError, ValueError):
                        lvl = 1
                    try:
                        qty = float(qty_raw) if qty_raw is not None else 1.0
                        qty = max(0.01, qty)
                    except (TypeError, ValueError):
                        qty = 1.0
                    rows_to_save.append({
                        "level": lvl,
                        "part_number": pn,
                        "description": desc,
                        "quantity": qty,
                    })

                if validation_errors:
                    for err in validation_errors:
                        st.error(f":material/error: {err}")
                elif not rows_to_save:
                    st.warning("No valid BOM rows to save. Fill in at least one Part # before saving.")
                else:
                    try:
                        editor_name = st.session_state.get("current_editor", "")
                        save_res = save_manual_model_bom(
                            project_id,
                            selected_model_id,
                            rows_to_save,
                            auto_add_parts=auto_add_grid,
                            editor=editor_name,
                        )
                        # Refresh the draft key so the editor opens with saved data
                        st.session_state[draft_key] = rows_to_save
                        request_table_editor_reset(bom_editor_logical_key)
                        st.toast(
                            f"Saved {save_res['saved_count']} BOM items for "
                            f"{save_res['model_number']}  "
                            f"({save_res['parts_created']} new parts onboarded)",
                            icon=":material/check_circle:",
                        )
                        st.rerun()
                    except ValueError as val_err:
                        st.error(f":material/error: {val_err}")

            # ── Live outline preview (read-only, never modifies draft) ──
            st.markdown("---")
            st.markdown("#### :material/account_tree: Live Tree Outline Preview")
            # Build preview from editor's current state (what user sees in table)
            preview_rows = []
            if edited_df is not None and not edited_df.empty:
                for _, r in edited_df.iterrows():
                    pn = str(r.get("Part #") or "").strip()
                    if pn:
                        try:
                            lvl = int(float(r.get("Level") or 1))
                            lvl = max(1, min(11, lvl))
                        except (TypeError, ValueError):
                            lvl = 1
                        preview_rows.append({
                            "level": lvl,
                            "part_number": pn,
                            "description": str(r.get("Description") or "").strip(),
                            "quantity": float(r.get("Qty") or 1.0),
                        })
            if not preview_rows:
                st.caption("No BOM items entered yet. Type rows above to see the live outline preview.")
            else:
                with st.container(height=280):
                    for p_it in preview_rows:
                        lvl = p_it["level"]
                        pad = max(0, (lvl - 1) * 20)
                        icon = "📁" if lvl == 1 else ("📂" if lvl == 2 else "📄")
                        st.markdown(
                            f"<div style='padding-left:{pad}px; font-family:monospace; line-height:26px;'>"
                            f"{icon} <strong>L{lvl}</strong> <strong>{p_it['part_number']}</strong> &mdash; "
                            f"{p_it.get('description') or '—'} <span style='color:#666;'>&times;{p_it.get('quantity', 1.0)}</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

        # --- Sub-tab B: Visual Tree Builder ---
        with sub_builder:
            auto_add_builder = st.checkbox(
                "Automatically add new parts to Parts Catalog",
                value=True,
                key=f"auto_add_builder_{selected_model_id}",
                help="If checked, any part numbers not currently in the Parts Catalog will be created automatically.",
            )

            col_tb_add, col_tb_save = st.columns([1.5, 1.2])
            with col_tb_add:
                if st.button("➕ Add Level 1 Assembly Group", key=f"add_l1_{selected_model_id}"):
                    st.session_state[draft_key].append({
                        "level": 1, "part_number": "", "description": "", "quantity": 1.0
                    })
                    st.rerun()
            with col_tb_save:
                if st.button("💾 Save BOM Structure", type="primary", key=f"save_bom_builder_{selected_model_id}"):
                    draft_to_save = st.session_state.get(draft_key, [])
                    try:
                        editor_name = st.session_state.get("current_editor", "")
                        save_res = save_manual_model_bom(
                            project_id,
                            selected_model_id,
                            draft_to_save,
                            auto_add_parts=auto_add_builder,
                            editor=editor_name,
                        )
                        st.success(
                            f"Saved **{save_res['saved_count']}** BOM items for model **{save_res['model_number']}**! "
                            f"({save_res['parts_created']} new parts onboarded to Parts Catalog)"
                        )
                        st.rerun()
                    except ValueError as val_err:
                        st.error(f":material/error: {str(val_err)}")

            st.caption("Edit individual components in the hierarchical tree, adjust levels, indent/outdent, or insert sub-items:")

            items_list = list(st.session_state.get(draft_key, []))
            for i, it in enumerate(items_list):
                lvl = int(it.get("level", 1) or 1)
                pad_left = max(0, (lvl - 1) * 20)

                with st.container(border=True):
                    c_indent_info, c_ctrls = st.columns([3, 2.5])
                    with c_indent_info:
                        icon = "📁" if lvl == 1 else ("📂" if lvl == 2 else "📄")
                        title_pn = it.get("part_number") or f"Item #{i + 1} (Unspecified Part #)"
                        st.markdown(
                            f"<div style='padding-left:{pad_left}px; font-weight:600; font-family:monospace;'>"
                            f"{icon} Level {lvl}: {title_pn} &times;{it.get('quantity', 1.0)}"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                    with c_ctrls:
                        btn_c1, btn_c2, btn_c3, btn_c4, btn_c5, btn_c6 = st.columns(6)
                        with btn_c1:
                            if st.button("➕Sub", key=f"sub_{i}_{selected_model_id}", help="Insert sub-item at Level + 1"):
                                new_lvl = min(11, lvl + 1)
                                items_list.insert(i + 1, {"level": new_lvl, "part_number": "", "description": "", "quantity": 1.0})
                                st.session_state[draft_key] = items_list
                                st.rerun()
                        with btn_c2:
                            if st.button("➕Sib", key=f"sib_{i}_{selected_model_id}", help="Insert sibling item at same Level"):
                                items_list.insert(i + 1, {"level": lvl, "part_number": "", "description": "", "quantity": 1.0})
                                st.session_state[draft_key] = items_list
                                st.rerun()
                        with btn_c3:
                            if st.button("◀", key=f"out_{i}_{selected_model_id}", help="Outdent (Level - 1)", disabled=(lvl <= 1)):
                                it["level"] = max(1, lvl - 1)
                                st.session_state[draft_key] = items_list
                                st.rerun()
                        with btn_c4:
                            if st.button("▶", key=f"ind_{i}_{selected_model_id}", help="Indent (Level + 1)", disabled=(lvl >= 11)):
                                it["level"] = min(11, lvl + 1)
                                st.session_state[draft_key] = items_list
                                st.rerun()
                        with btn_c5:
                            if st.button("↑", key=f"up_{i}_{selected_model_id}", help="Move Up", disabled=(i == 0)):
                                items_list[i], items_list[i - 1] = items_list[i - 1], items_list[i]
                                st.session_state[draft_key] = items_list
                                st.rerun()
                        with btn_c6:
                            if st.button("🗑️", key=f"del_{i}_{selected_model_id}", help="Delete row"):
                                items_list.pop(i)
                                if not items_list:
                                    items_list = [{"level": 1, "part_number": "", "description": "", "quantity": 1.0}]
                                st.session_state[draft_key] = items_list
                                st.rerun()

                    # Inputs for this item
                    f_c1, f_c2, f_c3, f_c4 = st.columns([1, 2.5, 3, 1.2])
                    with f_c1:
                        new_lvl_val = st.selectbox(
                            "Level",
                            options=list(range(1, 12)),
                            index=lvl - 1,
                            key=f"bld_lvl_{i}_{selected_model_id}",
                        )
                        if new_lvl_val != it["level"]:
                            it["level"] = new_lvl_val
                            st.session_state[draft_key] = items_list
                    with f_c2:
                        it["part_number"] = st.text_input(
                            "Part # *",
                            value=it.get("part_number", ""),
                            key=f"bld_pn_{i}_{selected_model_id}",
                            help="Part or Assembly / Group number",
                        )
                    with f_c3:
                        it["description"] = st.text_input(
                            "Description",
                            value=it.get("description", ""),
                            key=f"bld_desc_{i}_{selected_model_id}",
                            help="Part or Assembly description",
                        )
                    with f_c4:
                        it["quantity"] = st.number_input(
                            "Qty",
                            min_value=0.01,
                            step=1.0,
                            value=float(it.get("quantity", 1.0) or 1.0),
                            key=f"bld_qty_{i}_{selected_model_id}",
                        )


# ==============================================================================
# AUDIT HISTORY (UNIVERSAL HISTORY DISPLAY STANDARD)
# ==============================================================================
st.markdown("---")
with st.expander(":material/history: Model Tree BOM History", expanded=False):
    hist_df = audit_history(project_id, "Model Tree BOM", limit=50)
    if hist_df.empty:
        st.caption("No Model Tree BOM changes recorded yet.")
    else:
        st.dataframe(hist_df, hide_index=True, width="stretch")
