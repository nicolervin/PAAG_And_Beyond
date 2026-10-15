"""Model Tree page for view-only inspection and from-scratch BOM authoring.

Provides an interactive CAD-browser-style Model Tree derived from imported PITS BOM Levels (Level 1–11)
or authored from scratch per official model, with gap reconciliation against the Parts Catalog
and Fishbone diagram, and a Properties inspector panel.
"""

import io
from pathlib import Path
from typing import Any
from uuid import uuid4
import openpyxl
import pandas as pd
import streamlit as st

from utils.cad_tree import cad_model_tree
from utils.bom_table_listener import bom_table_listener
from utils.fishbone_visual import part_thumbnail
from utils.scope_ui import page_title_with_scope
from utils.store import (
    add_project_model,
    audit_history,
    delete_bom_rows,
    detect_unexpanded_subassemblies,
    expand_subassembly_items,
    get_known_subassembly_structure,
    get_live_bom_editor_items,
    get_manual_model_bom,
    get_model_level1_assemblies,
    move_bom_rows_down,
    move_bom_rows_up,
    pits_bom_model_tree,
    project_models,
    query,
    save_manual_model_bom,
    sync_builder_inputs_to_items,
)
from utils.table_filters import (
    _EDITOR_INSTANCE_MARKER,
    apply_pending_table_editor_reset,
    has_unsaved_table_changes,
    request_table_editor_reset,
)
from utils.table_ui import format_clean_number

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
                        st.session_state["_pending_model_tree_model"] = new_mid
                        st.success(f"Model '{m_num}' created!")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
    st.stop()

# Consume pending model selection before widgets are instantiated
pending_mid = st.session_state.pop("_pending_model_tree_model", None)
if pending_mid:
    st.session_state["model_tree_selected_model"] = pending_mid
    st.session_state["model_tree_model_search"] = ""
    st.session_state["_last_model_tree_search"] = ""

model_options: dict[str, str] = {"all": "All models (Master BOM)"}
active_models = (
    models_df.loc[models_df["active"].fillna(1).astype(bool)]
    if "active" in models_df.columns
    else models_df
)
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
    sb_kwargs: dict[str, Any] = {
        "options": dropdown_keys,
        "format_func": lambda k: model_options.get(k, k),
        "key": "model_tree_selected_model",
    }
    if "model_tree_selected_model" not in st.session_state:
        sb_kwargs["index"] = selected_idx
    selected_model_id = st.selectbox("Official model number", **sb_kwargs)

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
                        st.session_state["_pending_model_tree_model"] = new_mid
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

                    has_distinct_trk = bool(
                        node.get("child_tracker")
                        and str(node["child_tracker"]).strip() != str(node.get("part_number") or "").strip()
                    )
                    trk_bracket = f" [{node['child_tracker']}]" if has_distinct_trk else ""
                    trk_caption = f" · Tracker #{node['child_tracker']}" if has_distinct_trk else ""

                    if has_children:
                        sub_count = len(node["children"])
                        expander_title = (
                            f"📁 L{d}{trk_bracket} {node['part_number']} — {node['description']} "
                            f"(×{format_clean_number(node['quantity'], decimal_places=5)}) · {sub_count} sub-items{photo_badge}{match_badge}"
                        )
                        with st.expander(expander_title, expanded=is_expanded):
                            c_btn, c_badge = st.columns([1.2, 4])
                            with c_btn:
                                if st.button("Inspect properties", key=f"exp_insp_{node['id']}", type="primary" if is_active else "secondary"):
                                    st.session_state["selected_model_tree_node_id"] = node["id"]
                                    st.rerun()
                            with c_badge:
                                st.caption(f"Status: {status_txt}{trk_caption}")

                            for child in node["children"]:
                                render_expander_branch(child, expand_all)
                    else:
                        indent_px = max(0, (d - 1) * 16)
                        c_item, c_act = st.columns([5, 1])
                        with c_item:
                            bg_style = "background:#fff8c5; border-left:3px solid #d4a72c; padding:2px 6px; border-radius:3px;" if self_matches else ""
                            st.markdown(
                                f"<div style='padding-left:{indent_px}px; font-family:monospace; font-size:0.88rem; line-height:28px; {bg_style}'>"
                                f"📄 <strong>L{d}</strong>{trk_bracket} "
                                f"<strong>{node['part_number']}</strong> &mdash; {node['description']} "
                                f"<span style='color:#666;'>&times;{format_clean_number(node['quantity'], decimal_places=5)}</span> "
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
                            "PITS Qty": round(float(n["quantity"]), 5),
                            "PITS Tracker": f"#{n['child_tracker']}" if n.get("child_tracker") and str(n["child_tracker"]).strip() != str(n.get("part_number") or "").strip() else "—",
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
                            "PITS Qty": st.column_config.NumberColumn(
                                "PITS Qty",
                                format="%.5f",
                                help="Quantity per unit (up to 5 decimal places)",
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
                        distinct_trk = selected_node.get("child_tracker") if (selected_node.get("child_tracker") and str(selected_node["child_tracker"]).strip() != str(selected_node.get("part_number") or "").strip()) else ""
                        st.write("**Hierarchy Level:**", f"Level {selected_node['depth']}")
                        st.write("**Tracker / ID:**", f"#{distinct_trk}" if distinct_trk else "—")
                        st.write("**Quantity:**", format_clean_number(selected_node["quantity"], decimal_places=5))
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


def generate_bom_excel_template(items: list[dict[str, Any]] | None = None) -> bytes:
    """Generate an Excel template/spreadsheet for Model BOM authoring.

    If items contains existing tree rows, exports those rows.
    If items is empty or blank, exports generic sample rows.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BOM"
    ws.append(["Level", "Part #", "Description", "Qty"])

    # Header styling
    header_fill = openpyxl.styles.PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = openpyxl.styles.Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    for col_idx in range(1, 5):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = openpyxl.styles.Alignment(horizontal="center" if col_idx in (1, 4) else "left", vertical="center")

    valid_items = [
        it for it in (items or [])
        if str(it.get("part_number") or "").strip() or str(it.get("description") or "").strip()
    ]

    if valid_items:
        for it in valid_items:
            try:
                lvl = int(it.get("level", 1) or 1)
                lvl = max(1, min(11, lvl))
            except (TypeError, ValueError):
                lvl = 1
            pn = str(it.get("part_number") or "").strip()
            desc = str(it.get("description") or "").strip()
            try:
                qty = float(it.get("quantity", 1.0) or 1.0)
                qty = max(0.00001, round(qty, 5))
            except (TypeError, ValueError):
                qty = 1.0
            ws.append([lvl, pn, desc, qty])
    else:
        # Default generic sample rows if tree is blank
        ws.append([1, "SAMPLE_MAIN_ASY", "Main Top-Level Assembly", 1.0])
        ws.append([2, "SAMPLE_SUB_ASY", "Subassembly Module", 1.0])
        ws.append([3, "SAMPLE_COMP_01", "Component Part A", 2.0])
        ws.append([3, "SAMPLE_COMP_02", "Component Part B", 4.0])

    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 25
    ws.column_dimensions["C"].width = 45
    ws.column_dimensions["D"].width = 12
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def parse_uploaded_bom_file(uploaded_file: Any) -> list[dict[str, Any]]:
    """Parse an uploaded Excel or CSV BOM file into normalized row items."""
    fname = getattr(uploaded_file, "name", "").lower()
    if fname.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    col_map: dict[str, str] = {}
    for c in df.columns:
        c_str = str(c).strip().lower()
        if "level" in c_str or c_str in ("lvl", "l"):
            col_map["level"] = str(c)
        elif any(k in c_str for k in ("part", "pn", "number", "item")):
            col_map["part_number"] = str(c)
        elif any(k in c_str for k in ("desc", "name")):
            col_map["description"] = str(c)
        elif any(k in c_str for k in ("qty", "quantity", "count")):
            col_map["quantity"] = str(c)

    items: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        pn = str(r.get(col_map.get("part_number", "Part #"), "") or "").strip()
        desc = str(r.get(col_map.get("description", "Description"), "") or "").strip()
        if not pn and not desc:
            continue
        lvl_raw = r.get(col_map.get("level", "Level"))
        try:
            lvl = int(float(lvl_raw)) if lvl_raw is not None and not pd.isna(lvl_raw) else 1
            lvl = max(1, min(11, lvl))
        except (TypeError, ValueError):
            lvl = 1
        qty_raw = r.get(col_map.get("quantity", "Qty"))
        try:
            qty = float(qty_raw) if qty_raw is not None and not pd.isna(qty_raw) else 1.0
            qty = max(0.00001, round(qty, 5))
        except (TypeError, ValueError):
            qty = 1.0
        items.append({
            "level": lvl,
            "part_number": pn,
            "description": desc,
            "quantity": qty,
            "_uid": str(uuid4())[:8],
        })
    return items


def build_live_assembly_hierarchy(
    items: list[dict[str, Any]],
    catalog_map: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Build nested assembly tree nodes, CAD-ready roots, and validation warnings from flat BOM items."""
    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []
    warnings: list[str] = []

    valid_items = [it for it in items if str(it.get("part_number") or "").strip() or str(it.get("description") or "").strip()]

    if valid_items and int(valid_items[0].get("level", 1) or 1) != 1:
        warnings.append("Row 1 must be Level 1 (Top-Level Model Assembly).")

    prev_lvl = 0
    for idx, it in enumerate(items):
        pn = str(it.get("part_number") or "").strip()
        desc = str(it.get("description") or "").strip()
        if not pn and not desc:
            continue
        qty = round(float(it.get("quantity", 1.0) or 1.0), 5)
        lvl = int(it.get("level", 1) or 1)

        if not pn:
            warnings.append(f"Row {idx + 1}: Missing Part Number.")

        if prev_lvl > 0 and lvl > prev_lvl + 1:
            warnings.append(f"Row {idx + 1} ({pn or 'Blank'}): Skips level from L{prev_lvl} to L{lvl}.")

        prev_lvl = lvl

        cat_info = catalog_map.get(pn.upper(), {})
        node = {
            "row_index": idx,
            "id": f"live_node_{idx}_{pn}",
            "depth": lvl,
            "level": lvl,
            "part_number": pn,
            "description": desc or cat_info.get("description", ""),
            "quantity": qty,
            "in_catalog": bool(cat_info),
            "in_fishbone": False,
            "fishbone_sections": [],
            "image_path": cat_info.get("image_path", ""),
            "factory_nickname": cat_info.get("nickname", ""),
            "children": [],
            "is_assembly": (lvl == 1),
        }

        while stack and stack[-1][0] >= lvl:
            stack.pop()

        if not stack:
            roots.append(node)
        else:
            parent = stack[-1][1]
            parent["children"].append(node)
            parent["is_assembly"] = True

        stack.append((lvl, node))

    return roots, roots, warnings


@st.dialog("Copy BOM from another model")
def copy_bom_dialog(
    proj_id: str,
    curr_model_id: str,
    d_key: str,
    ed_logical_key: str,
    s_model_key: str,
) -> None:
    models_df = project_models(proj_id)
    available = []
    if not models_df.empty:
        for _, m_row in models_df.iterrows():
            mid = str(m_row["id"])
            if mid == curr_model_id:
                continue
            b = get_manual_model_bom(proj_id, mid)
            if b:
                available.append((mid, str(m_row.get("model_number") or mid), b))

    if not available:
        st.info("No other models in this project currently have a saved BOM structure to copy from.")
        if st.button("Close", key="close_empty_copy_dlg"):
            st.rerun()
        return

    labels = {sid: f"{m_num} ({len(b)} items)" for sid, m_num, b in available}
    sel_src = st.selectbox(
        "Source Model *",
        options=[sid for sid, _, _ in available],
        format_func=lambda s: labels.get(s, s),
        help="Select the model whose BOM hierarchy will be copied as a template.",
    )

    src_data = next((item for item in available if item[0] == sel_src), None)
    if not src_data:
        return
    _, src_num, src_bom = src_data
    src_lvl1 = next((r for r in src_bom if r.get("level") == 1), None)
    src_lvl1_pn = str(src_lvl1.get("part_number") or "") if src_lvl1 else ""

    st.markdown(
        f"**Source Top-Level Assembly (Level 1):** `{src_lvl1_pn}`\n\n"
        f"This model will inherit {len(src_bom) - 1} component rows from levels 2+.\n\n"
        f":material/info: *Each model must have a unique Level 1 Assembly Number.*"
    )

    new_lvl1 = st.text_input(
        "New Level 1 Assembly Number *",
        value="",
        placeholder=f"e.g. {src_lvl1_pn}_NEW",
        help="Enter the distinct top-level assembly or group number for this model.",
        key="copy_new_lvl1_input",
    ).strip()

    new_desc = st.text_input(
        "New Level 1 Description (optional)",
        value="",
        placeholder="Assembly description (optional)",
        key="copy_new_desc_input",
    ).strip()

    c1, c2 = st.columns([1, 1.5])
    with c1:
        if st.button("Cancel", key="cancel_copy_dlg"):
            st.rerun()
    with c2:
        if st.button("Copy to BOM Editor", type="primary", key="confirm_copy_dlg"):
            if not new_lvl1:
                st.error("Please enter a new Level 1 Assembly Number.")
                return
            if new_lvl1.upper() == src_lvl1_pn.upper():
                st.error(f"Level 1 Assembly Number must be different from source model's Level 1 ('{src_lvl1_pn}').")
                return

            # Check uniqueness against other models in the project
            other_l1 = get_model_level1_assemblies(proj_id, exclude_model_id=curr_model_id)
            if new_lvl1.upper() in other_l1:
                st.error(f"Level 1 Assembly Number '{new_lvl1}' is already assigned to model '{other_l1[new_lvl1.upper()]}'.")
                return

            copied_draft = []
            for it in src_bom:
                lvl = int(it.get("level", 1) or 1)
                if lvl == 1:
                    copied_draft.append({
                        "level": 1,
                        "part_number": new_lvl1,
                        "description": new_desc,
                        "quantity": round(float(it.get("quantity", 1.0) or 1.0), 5),
                        "_uid": str(uuid4())[:8],
                    })
                else:
                    copied_draft.append({
                        "level": lvl,
                        "part_number": str(it.get("part_number") or ""),
                        "description": str(it.get("description") or ""),
                        "quantity": round(float(it.get("quantity", 1.0) or 1.0), 5),
                        "_uid": str(uuid4())[:8],
                    })

            st.session_state[d_key] = copied_draft
            st.session_state[s_model_key] = sel_src
            _clear_bld_widget_keys(curr_model_id)
            request_table_editor_reset(ed_logical_key)
            st.toast(f"BOM copied from {src_num} with Level 1 assembly {new_lvl1}!", icon=":material/content_copy:")
            st.rerun()


def _clear_bld_widget_keys(model_id: str) -> None:
    suffix = f"_{model_id}"
    keys_to_del = [
        k for k in list(st.session_state.keys())
        if k.endswith(suffix) and (
            k.startswith("bld_pn_") or k.startswith("bld_desc_") or
            k.startswith("bld_qty_") or k.startswith("bld_lvl_")
        )
    ]
    for k in keys_to_del:
        st.session_state.pop(k, None)


_sync_builder_inputs_to_items = sync_builder_inputs_to_items
_get_live_editor_items = get_live_bom_editor_items


def _commit_bom_save(
    proj_id: str,
    curr_model_id: str,
    rows: list[dict[str, Any]],
    auto_add: bool,
    d_key: str,
    ed_logical_key: str,
    s_model_key: str,
) -> None:
    editor_name = st.session_state.get("current_editor", "")
    source_mid = st.session_state.get(s_model_key)
    try:
        save_res = save_manual_model_bom(
            proj_id,
            curr_model_id,
            rows,
            auto_add_parts=auto_add,
            editor=editor_name,
            source_model_id=source_mid,
        )
        saved_reloaded = get_manual_model_bom(proj_id, curr_model_id)
        final_items = saved_reloaded if saved_reloaded else rows
        for it in final_items:
            if "_uid" not in it:
                it["_uid"] = str(uuid4())[:8]
        st.session_state[d_key] = final_items
        st.session_state.pop(s_model_key, None)
        st.session_state.pop(f"_draft_modified_{curr_model_id}", None)
        st.session_state.pop(f"row_tools_idx_{curr_model_id}", None)
        st.session_state[f"bom_selected_indices_{curr_model_id}"] = set()
        st.session_state.pop(f"bom_anchor_row_{curr_model_id}", None)
        _clear_bld_widget_keys(curr_model_id)
        request_table_editor_reset(ed_logical_key)
        feat_inf = save_res.get("features_inferred", 0)
        feat_msg = f", {feat_inf} feature rules updated" if feat_inf else ""
        st.toast(
            f"Saved {save_res['saved_count']} BOM items for {save_res['model_number']} "
            f"({save_res['parts_created']} new parts onboarded{feat_msg})",
            icon=":material/check_circle:",
        )
        st.rerun()
    except ValueError as val_err:
        st.error(f":material/error: {val_err}")


@st.dialog("Auto-detect & Autofill BOM")
def autofill_bom_dialog(
    proj_id: str,
    curr_model_id: str,
    d_key: str,
    ed_logical_key: str,
) -> None:
    current_items = _get_live_editor_items(curr_model_id, d_key, ed_logical_key)
    valid_pns = [str(it.get("part_number") or "").strip() for it in current_items if str(it.get("part_number") or "").strip()]
    if not valid_pns:
        st.info("No parts entered in the BOM yet to analyze. Add part numbers in the editor first.")
        if st.button("Close", key="close_empty_autofill_dlg"):
            st.rerun()
        return

    # 1. Check description matches from Parts Catalog
    cat_rows = query("SELECT part_number, description FROM parts WHERE project_id=?", (proj_id,))
    catalog_parts = {
        str(r["part_number"]).strip().upper(): str(r["description"] or "").strip()
        for r in cat_rows
    }

    desc_matches = []
    for it in current_items:
        pn = str(it.get("part_number") or "").strip()
        desc = str(it.get("description") or "").strip()
        pn_upper = pn.upper()
        if pn and not desc and pn_upper in catalog_parts and catalog_parts[pn_upper]:
            desc_matches.append((pn, catalog_parts[pn_upper]))

    # 2. Check for known subassemblies using detect_unexpanded_subassemblies
    detected_subassemblies = detect_unexpanded_subassemblies(proj_id, current_items)

    st.markdown("#### :material/manage_search: BOM Analysis")
    if desc_matches:
        st.success(f":material/check_circle: Found **{len(desc_matches)}** missing description(s) in the Parts Catalog:")
        for pn, cat_desc in desc_matches[:5]:
            st.caption(f"• `{pn}`: {cat_desc}")
        if len(desc_matches) > 5:
            st.caption(f"• ... and {len(desc_matches) - 5} more")
    else:
        st.caption(":material/check: All entered parts already have descriptions or are not yet in the Parts Catalog.")

    selected_sub_expansions: dict[str, bool] = {}
    if detected_subassemblies:
        st.markdown(f"##### :material/account_tree: Known Subassemblies Detected ({len(detected_subassemblies)})")
        st.caption("The following parts were previously defined as subassemblies with child components in this project:")
        for sub in detected_subassemblies:
            st.markdown(f"**{sub['part_number']}** (Level {sub['level']}): {len(sub['children'])} sub-tier part(s)")
            preview_text = ", ".join(f"{c['part_number']} (L{min(11, sub['level'] + c['relative_level'])})" for c in sub['children'][:4])
            if len(sub['children']) > 4:
                preview_text += f", ... (+{len(sub['children']) - 4} more)"
            st.caption(preview_text)
            selected_sub_expansions[sub["part_number"]] = st.checkbox(
                f"Insert child parts under `{sub['part_number']}`",
                value=True,
                key=f"chk_sub_expand_{sub['part_number']}",
            )
    else:
        st.caption(":material/info: No unexpanded known subassemblies detected.")

    c1, c2 = st.columns([1, 1.5])
    with c1:
        if st.button("Cancel", key="cancel_autofill_dlg"):
            st.rerun()
    with c2:
        if st.button("Apply to Editor", type="primary", key="confirm_autofill_dlg"):
            # Apply descriptions
            for it in current_items:
                pn = str(it.get("part_number") or "").strip().upper()
                if pn and not str(it.get("description") or "").strip() and pn in catalog_parts and catalog_parts[pn]:
                    it["description"] = catalog_parts[pn]

            # Apply subassemblies using expand_subassembly_items
            if detected_subassemblies:
                selected_pns = {pn.upper() for pn, checked in selected_sub_expansions.items() if checked}
                current_items = expand_subassembly_items(
                    current_items,
                    detected_subassemblies,
                    selected_pns=selected_pns,
                    catalog_parts=catalog_parts,
                )

            for it in current_items:
                if "_uid" not in it:
                    it["_uid"] = str(uuid4())[:8]

            st.session_state[d_key] = current_items
            st.session_state[f"_draft_modified_{curr_model_id}"] = True
            _clear_bld_widget_keys(curr_model_id)
            request_table_editor_reset(ed_logical_key)
            st.toast("Autofill and subassembly expansion applied!", icon=":material/check_circle:")
            st.rerun()


@st.dialog("Expand Subassembly Groups Before Saving?")
def save_subassembly_prompt_dialog(
    proj_id: str,
    curr_model_id: str,
    d_key: str,
    ed_logical_key: str,
    s_model_key: str,
) -> None:
    flow_data = st.session_state.get(f"_pending_save_flow_{curr_model_id}")
    if not flow_data:
        st.rerun()
        return

    rows = flow_data["rows"]
    detected = flow_data["detected"]
    auto_add = flow_data.get("auto_add", True)

    st.markdown("#### :material/account_tree: Known Subassembly Structure Detected")
    st.markdown(
        f"We found **{len(detected)}** part/group number(s) with known child components from other models or PITS records in this project. "
        "Would you like to insert these child parts into your BOM structure before saving?"
    )

    selected_pns: set[str] = set()
    for sub in detected:
        pn = sub["part_number"]
        lvl = sub["level"]
        ch = sub["children"]
        st.markdown(f"**`{pn}`** (Level {lvl}) &mdash; {len(ch)} child part(s)")
        preview_text = ", ".join(f"`{c['part_number']}` (L{min(11, lvl + c['relative_level'])})" for c in ch[:4])
        if len(ch) > 4:
            preview_text += f", ... (+{len(ch) - 4} more)"
        st.caption(preview_text)
        chk = st.checkbox(
            f"Expand child parts under `{pn}`",
            value=True,
            key=f"save_dlg_chk_{pn}_{curr_model_id}",
        )
        if chk:
            selected_pns.add(pn.upper())

    st.caption(":material/info: New rows will be added in between assemblies. Top-level and subsequent assemblies will not be overwritten.")

    b_col1, b_col2, b_col3, b_col4 = st.columns([1, 1.3, 1.4, 1.5], gap="small")
    with b_col1:
        if st.button("Cancel", key="btn_cancel_save_prompt"):
            st.session_state.pop(f"_pending_save_flow_{curr_model_id}", None)
            st.rerun()
    with b_col2:
        if st.button("Save As-Is", key="btn_save_asis_prompt", help="Save the BOM exactly as entered without expanding subassemblies"):
            st.session_state.pop(f"_pending_save_flow_{curr_model_id}", None)
            _commit_bom_save(proj_id, curr_model_id, rows, auto_add, d_key, ed_logical_key, s_model_key)
    with b_col3:
        if st.button("Expand into Editor", key="btn_expand_editor_prompt", help="Insert child rows into the editor to review and edit before saving"):
            cat_rows = query("SELECT part_number, description FROM parts WHERE project_id=?", (proj_id,))
            cat_parts = {
                str(r["part_number"]).strip().upper(): str(r["description"] or "").strip()
                for r in cat_rows
            }
            expanded = expand_subassembly_items(rows, detected, selected_pns, cat_parts)
            for it in expanded:
                if "_uid" not in it:
                    it["_uid"] = str(uuid4())[:8]
            st.session_state[d_key] = expanded
            st.session_state[f"_draft_modified_{curr_model_id}"] = True
            _clear_bld_widget_keys(curr_model_id)
            request_table_editor_reset(ed_logical_key)
            st.session_state.pop(f"_pending_save_flow_{curr_model_id}", None)
            st.toast("Child rows inserted into editor! Review them and click Save when ready.", icon=":material/check_circle:")
            st.rerun()
    with b_col4:
        if st.button("Expand & Save", type="primary", key="btn_expand_save_prompt", help="Insert child rows between assemblies and save BOM"):
            cat_rows = query("SELECT part_number, description FROM parts WHERE project_id=?", (proj_id,))
            cat_parts = {
                str(r["part_number"]).strip().upper(): str(r["description"] or "").strip()
                for r in cat_rows
            }
            expanded = expand_subassembly_items(rows, detected, selected_pns, cat_parts)
            st.session_state.pop(f"_pending_save_flow_{curr_model_id}", None)
            _commit_bom_save(proj_id, curr_model_id, expanded, auto_add, d_key, ed_logical_key, s_model_key)


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
        source_model_key = f"_bom_source_model_{project_id}_{selected_model_id}"
        bom_editor_logical_key = f"bom_grid_editor_{selected_model_id}"

        if draft_key not in st.session_state:
            saved_bom = get_manual_model_bom(project_id, selected_model_id)
            if saved_bom:
                for it in saved_bom:
                    if "_uid" not in it:
                        it["_uid"] = str(uuid4())[:8]
                st.session_state[draft_key] = saved_bom
            else:
                st.session_state[draft_key] = [
                    {"level": 1, "part_number": "", "description": "", "quantity": 1.0, "_uid": str(uuid4())[:8]}
                ]
        else:
            for it in st.session_state[draft_key]:
                if "_uid" not in it:
                    it["_uid"] = str(uuid4())[:8]

        # Check if a pending save prompt flow is awaiting user action
        if f"_pending_save_flow_{selected_model_id}" in st.session_state:
            save_subassembly_prompt_dialog(
                project_id,
                selected_model_id,
                draft_key,
                bom_editor_logical_key,
                source_model_key,
            )

        # ── Toolbar: Copy from Model & Auto-detect / Autofill ──
        tb_col1, tb_col2, tb_col_space = st.columns([1.5, 1.4, 2.5], gap="small")
        with tb_col1:
            if st.button(
                "Copy BOM from another model",
                icon=":material/content_copy:",
                key=f"btn_copy_bom_{selected_model_id}",
                help="Copy the hierarchical BOM structure from another model and assign a new Level 1 Assembly Number.",
            ):
                copy_bom_dialog(project_id, selected_model_id, draft_key, bom_editor_logical_key, source_model_key)
        with tb_col2:
            if st.button(
                "Auto-detect & Autofill",
                icon=":material/auto_fix_high:",
                key=f"btn_autofill_bom_{selected_model_id}",
                help="Auto-fill part descriptions from the Parts Catalog and detect known subassemblies to expand.",
            ):
                autofill_bom_dialog(project_id, selected_model_id, draft_key, bom_editor_logical_key)

        # ── Banner if draft was copied from a model ──
        if st.session_state.get(source_model_key):
            src_mid = st.session_state[source_model_key]
            src_row = models_df[models_df["id"].astype(str) == str(src_mid)]
            src_name = str(src_row.iloc[0]["model_number"]).strip() if not src_row.empty else src_mid
            curr_draft = st.session_state.get(draft_key, [])
            curr_lvl1 = curr_draft[0].get("part_number", "") if curr_draft else ""
            st.info(
                f":material/content_copy: **Draft copied from model `{src_name}`.** "
                f"Level 1 assembly set to `{curr_lvl1}`. "
                f"Per manufacturing planning rules, at least one Level 2+ component or quantity must be modified before saving."
            )

        # ── Side-by-Side BOM Authoring Workspace (55% Spreadsheet / 45% Live Tree) ──
        col_table, col_tree = st.columns([1.2, 1.0], gap="medium")

        # --- Left Column: Spreadsheet Editor ---
        with col_table:
            st.markdown("#### :material/table_view: BOM Spreadsheet Editor")
            st.caption("Edit levels, parts, descriptions, and quantities just like Excel. Rows and levels define the assembly hierarchy.")
            # ── Logical editor key + instance rotation (standard pattern) ──
            bom_editor_logical_key = f"bom_grid_editor_{selected_model_id}"
            bom_editor_key = apply_pending_table_editor_reset(bom_editor_logical_key)

            # Determine whether there are unsaved changes
            draft_mod_key = f"_draft_modified_{selected_model_id}"
            is_unsaved = has_unsaved_table_changes(bom_editor_key) or bool(st.session_state.get(draft_mod_key))

            # Current draft
            current_draft = st.session_state.get(draft_key, [])
            if not current_draft:
                current_draft = [
                    {"level": 1, "part_number": "", "description": "", "quantity": 1.0, "_uid": str(uuid4())[:8]}
                ]
                st.session_state[draft_key] = current_draft

            # Selection keys
            row_tools_idx_key = f"row_tools_idx_{selected_model_id}"
            sel_indices_key = f"bom_selected_indices_{selected_model_id}"
            anchor_row_key = f"bom_anchor_row_{selected_model_id}"

            # Selection state initialization: DEFAULT TO EMPTY SET (Never auto-select row 0!)
            if sel_indices_key not in st.session_state or not isinstance(st.session_state[sel_indices_key], set):
                st.session_state[sel_indices_key] = set()
            if anchor_row_key not in st.session_state:
                st.session_state[anchor_row_key] = 0
            if row_tools_idx_key not in st.session_state:
                st.session_state[row_tools_idx_key] = 0

            # Shift-click range listener
            client_event = bom_table_listener(key=f"bom_tbl_listener_{selected_model_id}")
            if client_event and isinstance(client_event, dict):
                if "range_select" in client_event:
                    rng = client_event["range_select"]
                    from_r = max(0, min(len(current_draft) - 1, int(rng.get("from", 0))))
                    to_r = max(0, min(len(current_draft) - 1, int(rng.get("to", 0))))
                    st.session_state[sel_indices_key] = set(range(min(from_r, to_r), max(from_r, to_r) + 1))
                    st.session_state[anchor_row_key] = to_r
                    st.session_state[row_tools_idx_key] = to_r
                    request_table_editor_reset(bom_editor_logical_key)
                    st.rerun()
                elif "shortcut" in client_event:
                    action = client_event["shortcut"].get("action")
                    if action == "move_up" and current_draft:
                        live_items = _get_live_editor_items(selected_model_id, draft_key, bom_editor_logical_key)
                        cur_sel = st.session_state.get(sel_indices_key, set())
                        if cur_sel and not (0 in cur_sel and sorted(cur_sel) == list(range(len(cur_sel)))):
                            new_items, new_sel = move_bom_rows_up(live_items, cur_sel)
                            st.session_state[draft_key] = new_items
                            st.session_state[draft_mod_key] = True
                            st.session_state[sel_indices_key] = new_sel
                            st.session_state[anchor_row_key] = min(new_sel) if new_sel else 0
                            st.session_state[row_tools_idx_key] = min(new_sel) if new_sel else 0
                            request_table_editor_reset(bom_editor_logical_key)
                            st.rerun()
                    elif action == "move_down" and current_draft:
                        live_items = _get_live_editor_items(selected_model_id, draft_key, bom_editor_logical_key)
                        cur_sel = st.session_state.get(sel_indices_key, set())
                        if cur_sel and not (len(current_draft) - 1 in cur_sel and sorted(cur_sel) == list(range(len(current_draft) - len(cur_sel), len(current_draft)))):
                            new_items, new_sel = move_bom_rows_down(live_items, cur_sel)
                            st.session_state[draft_key] = new_items
                            st.session_state[draft_mod_key] = True
                            st.session_state[sel_indices_key] = new_sel
                            st.session_state[anchor_row_key] = max(new_sel) if new_sel else 0
                            st.session_state[row_tools_idx_key] = max(new_sel) if new_sel else 0
                            request_table_editor_reset(bom_editor_logical_key)
                            st.rerun()
                elif "row_anchor" in client_event:
                    st.session_state[anchor_row_key] = int(client_event["row_anchor"].get("row", 0))

            # Read user edits on the Select checkbox column
            generation = int(st.session_state.get(f"_table_editor_generation_{bom_editor_logical_key}", 0) or 0)
            active_inst_key = f"{bom_editor_logical_key}{_EDITOR_INSTANCE_MARKER}{generation}"
            ed_state = st.session_state.get(active_inst_key)
            if isinstance(ed_state, dict):
                edited_rows = ed_state.get("edited_rows") or {}
                for idx_str, edits in edited_rows.items():
                    try:
                        idx = int(idx_str)
                    except (TypeError, ValueError):
                        continue
                    if "Select" in edits:
                        if edits["Select"]:
                            st.session_state[sel_indices_key].add(idx)
                            st.session_state[anchor_row_key] = idx
                            st.session_state[row_tools_idx_key] = idx
                        else:
                            st.session_state[sel_indices_key].discard(idx)
                    elif edits:
                        st.session_state[row_tools_idx_key] = idx

            # Valid selection (NO forced fallback to row 0)
            valid_indices = {i for i in st.session_state.get(sel_indices_key, set()) if 0 <= i < len(current_draft)}
            st.session_state[sel_indices_key] = valid_indices
            selected_indices = valid_indices

            # ── Top Action Bar ──
            bar_left, bar_right = st.columns([1.8, 2.2], vertical_alignment="center")
            with bar_left:
                auto_add_grid = st.checkbox(
                    "Auto-add new parts to Parts Catalog",
                    value=True,
                    key=f"auto_add_grid_{selected_model_id}",
                    help="Automatically register unknown part numbers into the project Parts Catalog when saving.",
                )
            with bar_right:
                act_cols = st.columns([1.5, 0.9, 1.8], gap="small", vertical_alignment="center")
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
                        saved_bom = get_manual_model_bom(project_id, selected_model_id)
                        if saved_bom:
                            for it in saved_bom:
                                if "_uid" not in it:
                                    it["_uid"] = str(uuid4())[:8]
                            st.session_state[draft_key] = saved_bom
                        else:
                            st.session_state[draft_key] = [
                                {"level": 1, "part_number": "", "description": "", "quantity": 1.0, "_uid": str(uuid4())[:8]}
                            ]
                        st.session_state.pop(draft_mod_key, None)
                        st.session_state[sel_indices_key] = set()
                        st.session_state.pop(f"row_tools_idx_{selected_model_id}", None)
                        st.session_state.pop(f"bom_anchor_row_{selected_model_id}", None)
                        _clear_bld_widget_keys(selected_model_id)
                        request_table_editor_reset(bom_editor_logical_key)
                        st.toast("Discarded unsaved changes.", icon=":material/undo:")
                        st.rerun()
                with act_cols[2]:
                    save_clicked = st.button(
                        "Save BOM Structure",
                        icon=":material/save:",
                        type="primary",
                        key=f"save_bom_grid_{selected_model_id}",
                        width="stretch",
                    )

            # ── Excel-Style Hierarchy & Row Toolbar ──
            with st.container(border=True):
                # Row 1: Indent, Outdent, Move, Delete
                h_c1, h_c2, h_c3, h_c4, h_c5 = st.columns([1.2, 1.2, 0.9, 0.9, 1.1], gap="small")
                with h_c1:
                    btn_indent = st.button(
                        "Indent →",
                        icon=":material/format_indent_increase:",
                        key=f"btn_indent_{selected_model_id}",
                        help="Increase Level (+1) for selected row(s) or specified range",
                        width="stretch",
                    )
                with h_c2:
                    btn_outdent = st.button(
                        "← Outdent",
                        icon=":material/format_indent_decrease:",
                        key=f"btn_outdent_{selected_model_id}",
                        help="Decrease Level (-1) for selected row(s) or specified range",
                        width="stretch",
                    )
                with h_c3:
                    btn_move_up = st.button(
                        "⬆️ Up",
                        key=f"btn_mv_up_{selected_model_id}",
                        help="Move selected row(s) up",
                        width="stretch",
                    )
                with h_c4:
                    btn_move_down = st.button(
                        "⬇️ Down",
                        key=f"btn_mv_dn_{selected_model_id}",
                        help="Move selected row(s) down",
                        width="stretch",
                    )
                with h_c5:
                    btn_delete_rows = st.button(
                        "🗑️ Delete",
                        key=f"btn_del_rows_{selected_model_id}",
                        help="Delete selected row(s) or specified range",
                        width="stretch",
                    )

                # Row 2: Range selector & Selection pills
                rng_c1, rng_c2, rng_c3, rng_c4, rng_c5, rng_c6 = st.columns(
                    [1.2, 0.9, 0.3, 0.9, 1.3, 1.4],
                    vertical_alignment="center",
                )
                with rng_c1:
                    st.caption("**:material/tune: Range Tool:**")
                with rng_c2:
                    default_from = min(selected_indices) + 1 if selected_indices else 1
                    range_from = st.number_input(
                        "From Row",
                        min_value=1,
                        max_value=max(1, len(current_draft)),
                        value=default_from,
                        step=1,
                        label_visibility="collapsed",
                        key=f"rng_from_{selected_model_id}",
                    )
                with rng_c3:
                    st.markdown("<div style='text-align:center; font-size:0.85rem; color:gray;'>to</div>", unsafe_allow_html=True)
                with rng_c4:
                    default_to = max(selected_indices) + 1 if selected_indices else min(len(current_draft), default_from + 2)
                    range_to = st.number_input(
                        "To Row",
                        min_value=1,
                        max_value=max(1, len(current_draft)),
                        value=default_to,
                        step=1,
                        label_visibility="collapsed",
                        key=f"rng_to_{selected_model_id}",
                    )
                with rng_c5:
                    btn_apply_range = st.button(
                        ":material/arrow_range: Select Range",
                        key=f"btn_apply_range_{selected_model_id}",
                        help=f"Select rows {range_from} to {range_to}",
                        width="stretch",
                    )
                with rng_c6:
                    b_sel_all, b_clr_sel = st.columns(2)
                    with b_sel_all:
                        btn_select_all = st.button(":material/select_all: All", key=f"btn_sel_all_{selected_model_id}", help="Select all rows", width="stretch")
                    with b_clr_sel:
                        btn_clear_sel = st.button(":material/deselect: Clear", key=f"btn_clr_sel_{selected_model_id}", help="Clear selection", width="stretch")

                # Row 3: Transfer & Tools (Insert, Copy Model, Autofill)
                t_c1, t_c2, t_c3, t_c4 = st.columns([1.3, 1.3, 1.3, 1.3], gap="small")
                with t_c1:
                    if st.button("➕ Insert Above", key=f"btn_ins_above_{selected_model_id}", help="Insert a blank row above selected position", width="stretch"):
                        live_items = _get_live_editor_items(selected_model_id, draft_key, bom_editor_logical_key)
                        ins_pos = min(selected_indices) if selected_indices else (int(range_from) - 1)
                        ins_pos = max(0, min(len(live_items), ins_pos))
                        ref_lvl = int(live_items[ins_pos].get("level", 1) or 1) if ins_pos < len(live_items) else 1
                        live_items.insert(ins_pos, {"level": ref_lvl, "part_number": "", "description": "", "quantity": 1.0, "_uid": str(uuid4())[:8]})
                        st.session_state[draft_key] = live_items
                        st.session_state[draft_mod_key] = True
                        request_table_editor_reset(bom_editor_logical_key)
                        st.rerun()
                with t_c2:
                    if st.button("➕ Insert Below", key=f"btn_ins_below_{selected_model_id}", help="Insert a blank row below selected position", width="stretch"):
                        live_items = _get_live_editor_items(selected_model_id, draft_key, bom_editor_logical_key)
                        ref_pos = max(selected_indices) if selected_indices else (int(range_to) - 1)
                        ref_pos = max(0, min(len(live_items) - 1, ref_pos))
                        ins_pos = min(len(live_items), ref_pos + 1)
                        ref_lvl = int(live_items[ref_pos].get("level", 1) or 1) if ref_pos < len(live_items) else 1
                        live_items.insert(ins_pos, {"level": ref_lvl, "part_number": "", "description": "", "quantity": 1.0, "_uid": str(uuid4())[:8]})
                        st.session_state[draft_key] = live_items
                        st.session_state[draft_mod_key] = True
                        request_table_editor_reset(bom_editor_logical_key)
                        st.rerun()
                with t_c3:
                    if st.button(":material/content_copy: Copy Model", key=f"btn_open_copy_{selected_model_id}", help="Copy BOM hierarchy from another model", width="stretch"):
                        copy_bom_dialog(project_id, selected_model_id, draft_key, bom_editor_logical_key, source_model_key)
                with t_c4:
                    if st.button(":material/auto_fix_high: Autofill", key=f"btn_open_autofill_{selected_model_id}", help="Autofill descriptions from catalog & expand known subassemblies", width="stretch"):
                        autofill_bom_dialog(project_id, selected_model_id, draft_key, bom_editor_logical_key)

                # Row 4: Excel Tools row
                ex_c1, ex_c2 = st.columns([1, 1], gap="small")
                with ex_c1:
                    live_for_dl = _get_live_editor_items(selected_model_id, draft_key, bom_editor_logical_key)
                    has_tree_items = any(
                        bool(str(it.get("part_number") or "").strip() or str(it.get("description") or "").strip())
                        for it in live_for_dl
                    )
                    clean_model_tag = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(target_model_label).strip())
                    dl_file_name = f"BOM_{clean_model_tag}.xlsx" if has_tree_items else f"BOM_Template_{clean_model_tag}.xlsx"
                    dl_help = (
                        f"Download the existing BOM hierarchy for {target_model_label} (Level, Part #, Description, Qty) to edit in Excel"
                        if has_tree_items
                        else "Download an Excel template pre-formatted with Level, Part #, Description, Qty"
                    )
                    st.download_button(
                        label="📥 Download Excel Template",
                        data=generate_bom_excel_template(live_for_dl),
                        file_name=dl_file_name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_template_{selected_model_id}",
                        help=dl_help,
                        width="stretch",
                    )
                with ex_c2:
                    with st.popover("📤 Import Excel / CSV", help="Upload a BOM spreadsheet to populate the table"):
                        up_file = st.file_uploader("Upload spreadsheet (.xlsx, .csv)", type=["xlsx", "xls", "csv"], key=f"up_bom_{selected_model_id}")
                        if up_file is not None:
                            if st.button("Apply to Editor", type="primary", key=f"btn_apply_up_{selected_model_id}"):
                                try:
                                    parsed = parse_uploaded_bom_file(up_file)
                                    if not parsed:
                                        st.error("No valid BOM rows found in the uploaded file.")
                                    else:
                                        st.session_state[draft_key] = parsed
                                        st.session_state[draft_mod_key] = True
                                        request_table_editor_reset(bom_editor_logical_key)
                                        st.toast(f"Imported {len(parsed)} rows from {up_file.name}!", icon=":material/check_circle:")
                                        st.rerun()
                                except Exception as up_err:
                                    st.error(f"Failed to read file: {up_err}")

            # Hierarchy action processing
            target_indices = selected_indices if selected_indices else set(range(min(int(range_from) - 1, int(range_to) - 1), max(int(range_from) - 1, int(range_to) - 1) + 1))

            if btn_indent and current_draft:
                live_items = _get_live_editor_items(selected_model_id, draft_key, bom_editor_logical_key)
                if target_indices:
                    for idx in target_indices:
                        if 0 <= idx < len(live_items):
                            c_lvl = int(live_items[idx].get("level", 1) or 1)
                            live_items[idx]["level"] = min(11, c_lvl + 1)
                    st.session_state[draft_key] = live_items
                    st.session_state[draft_mod_key] = True
                    request_table_editor_reset(bom_editor_logical_key)
                    st.toast(f"Indented {len(target_indices)} row(s) (+1 Level)", icon=":material/format_indent_increase:")
                    st.rerun()

            if btn_outdent and current_draft:
                live_items = _get_live_editor_items(selected_model_id, draft_key, bom_editor_logical_key)
                if target_indices:
                    for idx in target_indices:
                        if 0 <= idx < len(live_items):
                            c_lvl = int(live_items[idx].get("level", 1) or 1)
                            live_items[idx]["level"] = max(1, c_lvl - 1)
                    st.session_state[draft_key] = live_items
                    st.session_state[draft_mod_key] = True
                    request_table_editor_reset(bom_editor_logical_key)
                    st.toast(f"Outdented {len(target_indices)} row(s) (-1 Level)", icon=":material/format_indent_decrease:")
                    st.rerun()

            if btn_move_up and current_draft and target_indices:
                live_items = _get_live_editor_items(selected_model_id, draft_key, bom_editor_logical_key)
                new_items, new_sel = move_bom_rows_up(live_items, target_indices)
                st.session_state[draft_key] = new_items
                st.session_state[draft_mod_key] = True
                st.session_state[sel_indices_key] = new_sel
                request_table_editor_reset(bom_editor_logical_key)
                st.rerun()

            if btn_move_down and current_draft and target_indices:
                live_items = _get_live_editor_items(selected_model_id, draft_key, bom_editor_logical_key)
                new_items, new_sel = move_bom_rows_down(live_items, target_indices)
                st.session_state[draft_key] = new_items
                st.session_state[draft_mod_key] = True
                st.session_state[sel_indices_key] = new_sel
                request_table_editor_reset(bom_editor_logical_key)
                st.rerun()

            if btn_delete_rows and current_draft and target_indices:
                live_items = _get_live_editor_items(selected_model_id, draft_key, bom_editor_logical_key)
                new_items, new_sel = delete_bom_rows(live_items, target_indices)
                st.session_state[draft_key] = new_items
                st.session_state[draft_mod_key] = True
                st.session_state[sel_indices_key] = new_sel
                request_table_editor_reset(bom_editor_logical_key)
                st.toast(f"Deleted {len(target_indices)} row(s)", icon=":material/delete:")
                st.rerun()

            if btn_apply_range and current_draft:
                f_idx = max(0, min(len(current_draft) - 1, int(range_from) - 1))
                t_idx = max(0, min(len(current_draft) - 1, int(range_to) - 1))
                st.session_state[sel_indices_key] = set(range(min(f_idx, t_idx), max(f_idx, t_idx) + 1))
                request_table_editor_reset(bom_editor_logical_key)
                st.rerun()

            if btn_select_all and current_draft:
                st.session_state[sel_indices_key] = set(range(len(current_draft)))
                request_table_editor_reset(bom_editor_logical_key)
                st.rerun()

            if btn_clear_sel and current_draft:
                st.session_state[sel_indices_key] = set()
                request_table_editor_reset(bom_editor_logical_key)
                st.rerun()

            # ── Build DataFrame from current draft ──
            # Columns match Excel order: Level, Part #, Description, Qty, Select
            df_editor_data = pd.DataFrame([
                {
                    "Level": int(it.get("level", 1) or 1),
                    "Part #": str(it.get("part_number", "") or ""),
                    "Description": str(it.get("description", "") or ""),
                    "Qty": round(float(it.get("quantity", 1.0) or 1.0), 5),
                    "Select": idx in selected_indices,
                }
                for idx, it in enumerate(current_draft)
            ])
            if df_editor_data.empty:
                df_editor_data = pd.DataFrame([{
                    "Level": 1,
                    "Part #": "",
                    "Description": "",
                    "Qty": 1.0,
                    "Select": False,
                }])

            # ── Spreadsheet data_editor with native dynamic rows ──
            edited_df = st.data_editor(
                df_editor_data,
                column_config={
                    "Level": st.column_config.NumberColumn(
                        "Level",
                        min_value=1,
                        max_value=11,
                        step=1,
                        default=2,
                        format="%d",
                        help="Hierarchy Level (1 = Top Assembly, 2 = Subassembly, 3+ = Component)",
                        width="small",
                    ),
                    "Part #": st.column_config.TextColumn(
                        "Part # / Group #",
                        help="Part number or Assembly / Group number (required to save)",
                        width="medium",
                    ),
                    "Description": st.column_config.TextColumn(
                        "Description",
                        help="Part description or name",
                        width="large",
                    ),
                    "Qty": st.column_config.NumberColumn(
                        "Qty",
                        min_value=0.00001,
                        step=1.0,
                        default=1.0,
                        format="%.5f",
                        help="Quantity per unit",
                        width="small",
                    ),
                    "Select": st.column_config.CheckboxColumn(
                        "Select",
                        help="Check to select row for Indent/Outdent/Move actions",
                        width="small",
                        default=False,
                    ),
                },
                num_rows="dynamic",
                hide_index=False,
                key=bom_editor_key,
                width="stretch",
                height=560,
            )

            # ── Save action ──
            if save_clicked:
                rows_to_save = []
                validation_errors = []
                for pos_idx, (_, r) in enumerate(edited_df.iterrows(), start=1):
                    pn = str(r.get("Part #") or "").strip()
                    desc = str(r.get("Description") or "").strip()
                    qty_raw = r.get("Qty")
                    lvl_raw = r.get("Level")
                    # Skip completely blank rows silently
                    if not pn and not desc:
                        continue
                    if not pn:
                        validation_errors.append(f"Row {pos_idx}: Part # is required.")
                        continue
                    try:
                        lvl = int(float(lvl_raw)) if lvl_raw is not None else 1
                        lvl = max(1, min(11, lvl))
                    except (TypeError, ValueError):
                        lvl = 1
                    try:
                        qty = float(qty_raw) if qty_raw is not None else 1.0
                        qty = max(0.00001, round(qty, 5))
                    except (TypeError, ValueError):
                        qty = 1.0
                    rows_to_save.append({
                        "level": lvl,
                        "part_number": pn,
                        "description": desc,
                        "quantity": qty,
                        "_uid": str(uuid4())[:8],
                    })

                if validation_errors:
                    for err in validation_errors:
                        st.error(f":material/error: {err}")
                elif not rows_to_save:
                    st.warning("No valid BOM rows to save. Fill in at least one Part # before saving.")
                else:
                    detected = detect_unexpanded_subassemblies(project_id, rows_to_save)
                    if detected:
                        st.session_state[f"_pending_save_flow_{selected_model_id}"] = {
                            "rows": rows_to_save,
                            "detected": detected,
                            "auto_add": auto_add_grid,
                        }
                        st.rerun()
                    else:
                        st.session_state.pop(draft_mod_key, None)
                        st.session_state.pop(row_tools_idx_key, None)
                        _commit_bom_save(
                            project_id,
                            selected_model_id,
                            rows_to_save,
                            auto_add_grid,
                            draft_key,
                            bom_editor_logical_key,
                            source_model_key,
                        )



        # --- Right Column: Live Visual Tree ---
        with col_tree:
            st.markdown("#### :material/account_tree: Live Visual Tree")

            # Query catalog parts once for live matching
            cat_rows = query("SELECT part_number, description, factory_nickname, image_path FROM parts WHERE project_id=?", (project_id,))
            cat_map = {
                str(r["part_number"]).strip().upper(): {
                    "description": str(r["description"] or "").strip(),
                    "nickname": str(r.get("factory_nickname") or "").strip(),
                    "image_path": str(r.get("image_path") or "").strip(),
                }
                for r in cat_rows
            }

            # Build live tree items from current editor state
            live_items = _get_live_editor_items(selected_model_id, draft_key, bom_editor_logical_key)

            # Build tree hierarchy
            roots, cad_roots, warnings = build_live_assembly_hierarchy(live_items, cat_map)

            # Metrics
            total_items_count = len([it for it in live_items if it.get("part_number") or it.get("description")])
            asm_count = sum(1 for it in live_items if int(it.get("level", 1) or 1) in (1, 2))
            max_depth = max([int(it.get("level", 1) or 1) for it in live_items], default=1)

            st.caption(
                f"**{total_items_count}** parts &bull; "
                f"**{asm_count}** assembly group(s) &bull; "
                f"Max depth: **L{max_depth}**"
            )

            # Quick tree shortcuts
            t_col_add1, t_col_add2 = st.columns(2)
            with t_col_add1:
                if st.button("➕ Add Subassembly (L2)", key=f"btn_add_sub_{selected_model_id}", help="Append a new Level 2 subassembly to the BOM", width="stretch"):
                    live_items.append({"level": 2, "part_number": "", "description": "", "quantity": 1.0, "_uid": str(uuid4())[:8]})
                    st.session_state[draft_key] = live_items
                    st.session_state[draft_mod_key] = True
                    request_table_editor_reset(bom_editor_logical_key)
                    st.rerun()
            with t_col_add2:
                if st.button("➕ Add Component (L3)", key=f"btn_add_comp_{selected_model_id}", help="Append a new Level 3 child part to the BOM", width="stretch"):
                    live_items.append({"level": 3, "part_number": "", "description": "", "quantity": 1.0, "_uid": str(uuid4())[:8]})
                    st.session_state[draft_key] = live_items
                    st.session_state[draft_mod_key] = True
                    request_table_editor_reset(bom_editor_logical_key)
                    st.rerun()

            # Structural validation callouts
            if warnings:
                for w in warnings[:3]:
                    st.warning(f":material/warning: {w}")
                if len(warnings) > 3:
                    st.caption(f"... and {len(warnings) - 3} more issue(s). Check row levels above.")

            # Tabs for Outline vs CAD tree
            tab_tree_outline, tab_tree_cad = st.tabs(["🌳 Live Hierarchy", "🌲 CAD Browser Tree"])

            with tab_tree_outline:
                with st.container(border=True, height=520):
                    if not roots:
                        st.caption("No parts entered in spreadsheet. Type parts on the left to see the live hierarchy.")
                    else:
                        def render_live_node(node: dict[str, Any], depth: int = 0) -> None:
                            lvl = node["level"]
                            pn = node["part_number"] or "—"
                            desc = node["description"] or ""
                            qty = node["quantity"]
                            is_asm = node.get("is_assembly", False)
                            in_cat = node.get("in_catalog", False)
                            img_p = node.get("image_path", "")

                            pad = (lvl - 1) * 16
                            if lvl == 1:
                                icon = "📦"
                                role_badge = "<span style='background:#e8f0fe; color:#1a73e8; border-radius:4px; padding:1px 5px; font-size:10px; font-weight:700;'>Top Assembly</span>"
                            elif is_asm:
                                icon = "📁"
                                role_badge = "<span style='background:#f1f3f4; color:#3c4043; border-radius:4px; padding:1px 5px; font-size:10px; font-weight:600;'>Subassembly</span>"
                            else:
                                icon = "📄"
                                role_badge = ""

                            cat_badge = (
                                "<span style='color:#137333; font-size:10px; font-weight:600;'>🟢 Catalog</span>"
                                if in_cat
                                else "<span style='color:#b06000; font-size:10px; font-weight:600;'>⚠️ New</span>"
                            )
                            photo_icon = " 📷" if img_p else ""

                            node_html = (
                                f"<div style='margin-left:{pad}px; padding:4px 0; border-left:2px solid #e0e0e0; padding-left:8px; line-height:1.4;'>"
                                f"<span style='font-size:13px;'>{icon} <strong>L{lvl}</strong> <code style='font-size:12px; font-weight:700;'>{pn}</code>{photo_icon}</span> "
                                f"<span style='color:#555; font-size:12px;'>{desc}</span> "
                                f"<span style='background:#f6f8fa; border:1px solid #d0d7de; border-radius:10px; padding:0 5px; font-size:11px;'>×{format_clean_number(qty, decimal_places=5)}</span> "
                                f"{role_badge} {cat_badge}"
                                f"</div>"
                            )
                            st.markdown(node_html, unsafe_allow_html=True)

                            for child in node.get("children", []):
                                render_live_node(child, depth + 1)

                        for r in roots:
                            render_live_node(r)

            with tab_tree_cad:
                if not cad_roots:
                    st.caption("No parts entered in spreadsheet.")
                else:
                    cad_model_tree(
                        roots=cad_roots,
                        key=f"author_cad_tree_{selected_model_id}",
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
