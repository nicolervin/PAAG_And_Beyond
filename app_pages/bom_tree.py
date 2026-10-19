"""Model Tree page for view-only inspection and from-scratch BOM authoring.

Provides an interactive CAD-browser-style Model Tree derived from imported PITS BOM Levels (Level 1–11)
or authored from scratch per official model, with gap reconciliation against the Parts Catalog
and Fishbone diagram, and a Properties inspector panel.
"""

import csv
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
    check_group_number_conflicts,
    clean_bom_cell_text,
    delete_bom_rows,
    detect_unexpanded_subassemblies,
    expand_subassembly_items,
    get_known_subassembly_structure,
    get_live_bom_editor_items,
    get_manual_model_bom,
    get_model_level1_assemblies,
    is_drawing_group,
    is_piece_part,
    move_bom_rows_down,
    move_bom_rows_up,
    pits_bom_model_tree,
    predict_model_bom_from_features,
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

page_title_with_scope("BOM", scope="project")
st.caption(
    "Interactive product structure and CAD-style BOM tree by official model, "
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
    "🌲 View BOM",
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

                def render_expander_branch(node: dict[str, Any], expand_all: bool, path: str = "0") -> None:
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
                                if st.button("Inspect properties", key=f"exp_insp_{path}_{node['id']}", type="primary" if is_active else "secondary"):
                                    st.session_state["selected_model_tree_node_id"] = node["id"]
                                    st.rerun()
                            with c_badge:
                                st.caption(f"Status: {status_txt}{trk_caption}")

                            for c_idx, child in enumerate(node["children"]):
                                render_expander_branch(child, expand_all, f"{path}_{c_idx}")
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
                            if st.button("Inspect", key=f"leaf_insp_{path}_{node['id']}", type="primary" if is_active else "secondary"):
                                st.session_state["selected_model_tree_node_id"] = node["id"]
                                st.rerun()

                with st.container(height=560):
                    for r_idx, r in enumerate(roots):
                        render_expander_branch(r, expand_all_native, f"r{r_idx}")

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
        if clean_bom_cell_text(it.get("part_number")) or clean_bom_cell_text(it.get("description"))
    ]

    if valid_items:
        for it in valid_items:
            try:
                lvl = int(it.get("level", 1) or 1)
                lvl = max(1, min(11, lvl))
            except (TypeError, ValueError):
                lvl = 1
            pn = clean_bom_cell_text(it.get("part_number"))
            desc = " ".join(clean_bom_cell_text(it.get("description")).split())
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
        pn = clean_bom_cell_text(r.get(col_map.get("part_number", "Part #")))
        desc = " ".join(clean_bom_cell_text(r.get(col_map.get("description", "Description"))).split())
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


def parse_pasted_bom_text(text: str) -> list[dict[str, Any]]:
    """Parse clipboard text (tab-separated or comma-separated from Excel) into normalized BOM row items.

    Handles empty lines, header rows, multiline quoted descriptions, and converts any 'nan'/bogus null values to empty string.
    """
    if not text or not text.strip():
        return []

    # Detect delimiter: Excel clipboard uses tab; CSV uses comma
    first_line = text.split("\n", 1)[0]
    delim = "\t" if "\t" in first_line else ("," if "," in first_line else "\t")

    try:
        reader = csv.reader(io.StringIO(text.strip()), delimiter=delim)
        raw_rows: list[list[str]] = []
        for row in reader:
            if not any(clean_bom_cell_text(cell) for cell in row):
                continue
            raw_rows.append([clean_bom_cell_text(cell) for cell in row])
    except Exception:
        lines = [line for line in text.splitlines() if line.strip()]
        raw_rows = [[clean_bom_cell_text(c) for c in line.split(delim)] for line in lines]

    if not raw_rows:
        return []

    header = [c.lower() for c in raw_rows[0]]
    has_header = False
    col_map = {"level": -1, "part_number": -1, "description": -1, "quantity": -1}

    for idx, col_name in enumerate(header):
        if "level" in col_name or col_name in ("lvl", "l"):
            col_map["level"] = idx
            has_header = True
        elif any(k in col_name for k in ("part", "pn", "item", "number", "#", "p/n")):
            col_map["part_number"] = idx
            has_header = True
        elif any(k in col_name for k in ("desc", "name", "title")):
            col_map["description"] = idx
            has_header = True
        elif any(k in col_name for k in ("qty", "quantity", "count", "amount")):
            col_map["quantity"] = idx
            has_header = True

    # If has_header is True but part_number was not explicitly matched, pick first unmapped column
    if has_header and col_map["part_number"] == -1:
        for i in range(len(header)):
            if i not in (col_map["level"], col_map["description"], col_map["quantity"]):
                col_map["part_number"] = i
                break

    start_idx = 1 if has_header else 0
    items: list[dict[str, Any]] = []

    for r in raw_rows[start_idx:]:
        if not any(r):
            continue

        if has_header:
            pn = r[col_map["part_number"]] if 0 <= col_map["part_number"] < len(r) else ""
            desc = r[col_map["description"]] if 0 <= col_map["description"] < len(r) else ""
            lvl_val = r[col_map["level"]] if 0 <= col_map["level"] < len(r) else ""
            qty_val = r[col_map["quantity"]] if 0 <= col_map["quantity"] < len(r) else ""
        else:
            if len(r) >= 4:
                lvl_val, pn, desc, qty_val = r[0], r[1], r[2], r[3]
            elif len(r) == 3:
                if r[0].isdigit() and 1 <= int(r[0]) <= 11:
                    lvl_val, pn, desc, qty_val = r[0], r[1], r[2], "1.0"
                else:
                    lvl_val, pn, desc, qty_val = "2", r[0], r[1], r[2]
            elif len(r) == 2:
                lvl_val, pn, desc, qty_val = "2", r[0], r[1], "1.0"
            else:
                lvl_val, pn, desc, qty_val = "2", r[0], "", "1.0"

        pn = clean_bom_cell_text(pn)
        desc = " ".join(clean_bom_cell_text(desc).split())
        if not pn and not desc:
            continue

        try:
            lvl = int(float(lvl_val)) if lvl_val else 2
            lvl = max(1, min(11, lvl))
        except (TypeError, ValueError):
            lvl = 2

        try:
            qty = float(qty_val) if qty_val else 1.0
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

    valid_items = [it for it in items if clean_bom_cell_text(it.get("part_number")) or clean_bom_cell_text(it.get("description"))]

    if valid_items and int(valid_items[0].get("level", 1) or 1) != 1:
        warnings.append("Row 1 must be Level 1 (Top-Level Model Assembly).")

    prev_lvl = 0
    for idx, it in enumerate(items):
        pn = clean_bom_cell_text(it.get("part_number"))
        desc = clean_bom_cell_text(it.get("description"))
        if not pn and not desc:
            continue
        try:
            qty = round(float(it.get("quantity", 1.0) or 1.0), 5)
        except (TypeError, ValueError):
            qty = 1.0
        try:
            lvl = int(it.get("level", 1) or 1)
        except (TypeError, ValueError):
            lvl = 1

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
            "is_assembly": (lvl == 1) or is_drawing_group(pn),
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
    curr_model_label = curr_model_id
    if not models_df.empty:
        curr_m_row = models_df.loc[models_df["id"].astype(str) == str(curr_model_id)]
        if not curr_m_row.empty:
            curr_row = curr_m_row.iloc[0]
            c_num = str(curr_row.get("model_number") or curr_model_id).strip()
            c_disp = str(curr_row.get("display_name") or curr_row.get("name") or "").strip()
            curr_model_label = f"{c_num} · {c_disp}".rstrip(" ·") if c_disp else c_num

        for _, m_row in models_df.iterrows():
            mid = str(m_row["id"])
            if mid == curr_model_id:
                continue
            b = get_manual_model_bom(proj_id, mid)
            if b:
                m_num = str(m_row.get("model_number") or mid).strip()
                m_disp = str(m_row.get("display_name") or m_row.get("name") or "").strip()
                available.append((mid, m_num, m_disp, b))

    if not available:
        st.info("No other models in this project currently have a saved BOM structure to copy from.")
        if st.button("Close", key="close_empty_copy_dlg"):
            st.rerun()
        return

    st.markdown(f"#### Copy BOM for **{curr_model_label}**")

    labels = {
        sid: f"{m_num} · {m_disp} ({len(b)} items)" if m_disp else f"{m_num} ({len(b)} items)"
        for sid, m_num, m_disp, b in available
    }
    sel_src = st.selectbox(
        "Source Model *",
        options=[sid for sid, _, _, _ in available],
        format_func=lambda s: labels.get(s, s),
        help="Select the model whose BOM hierarchy will be copied as a template.",
    )

    src_data = next((item for item in available if item[0] == sel_src), None)
    if not src_data:
        return
    _, src_num, src_disp, src_bom = src_data
    src_label = f"{src_num} · {src_disp}".rstrip(" ·") if src_disp else src_num
    src_lvl1 = next((r for r in src_bom if r.get("level") == 1), None)
    src_lvl1_pn = str(src_lvl1.get("part_number") or "") if src_lvl1 else ""

    st.info(
        f":material/account_tree: **Source Model:** **{src_label}**\n\n"
        f"**Source Top-Level Assembly (Level 1):** `{src_lvl1_pn}`\n\n"
        f"This model will inherit {len(src_bom) - 1} component rows from levels 2+.\n\n"
        f":material/info: *Each model must have a unique Level 1 Assembly Number.*"
    )

    st.markdown("##### :material/tag: Level 1 Assembly Number *")
    st.caption(
        "Specify the top-level assembly part number for this model. "
        "You can search and select an assembly from the Parts Catalog, or type a part number directly."
    )

    cat_rows = query("SELECT part_number, description FROM parts WHERE project_id=? ORDER BY part_number", (proj_id,))
    cat_parts_dict = {
        str(r["part_number"]).strip(): str(r["description"] or "").strip()
        for r in cat_rows
        if clean_bom_cell_text(r.get("part_number"))
    }
    cat_options = ["-- Select from Parts Catalog --"] + [
        f"{pn} · {desc}".rstrip(" ·") for pn, desc in cat_parts_dict.items()
    ]

    pn_key = f"copy_lvl1_pn_{curr_model_id}"
    desc_key = f"copy_lvl1_desc_{curr_model_id}"
    last_sel_key = f"_last_copy_cat_select_{curr_model_id}"
    cat_sel_key = f"copy_cat_select_{curr_model_id}"
    show_all_key = f"show_all_copy_prev_{curr_model_id}"

    if pn_key not in st.session_state:
        curr_draft = st.session_state.get(d_key, [])
        existing_l1 = next((r for r in curr_draft if r.get("level") == 1 and clean_bom_cell_text(r.get("part_number"))), None)
        if existing_l1 and not str(existing_l1.get("part_number", "")).endswith("_TOP"):
            st.session_state[pn_key] = str(existing_l1.get("part_number") or "").strip()
            st.session_state[desc_key] = str(existing_l1.get("description") or "").strip()
        else:
            st.session_state[pn_key] = ""
            st.session_state[desc_key] = ""

    sel_cat = st.selectbox(
        "Search & Choose from Parts Catalog",
        options=cat_options,
        key=cat_sel_key,
        help="Search the Parts Catalog by part number or description to populate the Level 1 assembly.",
    )

    if sel_cat != "-- Select from Parts Catalog --":
        if sel_cat != st.session_state.get(last_sel_key):
            selected_pn = sel_cat.split(" · ")[0].strip()
            selected_desc = cat_parts_dict.get(selected_pn, "")
            st.session_state[last_sel_key] = sel_cat
            st.session_state[pn_key] = selected_pn
            st.session_state[desc_key] = selected_desc
    else:
        st.session_state[last_sel_key] = ""

    c_pn, c_desc = st.columns([1, 1.4], gap="small")
    with c_pn:
        new_lvl1 = clean_bom_cell_text(st.text_input(
            "New Level 1 Assembly Number *",
            key=pn_key,
            placeholder=f"e.g. {src_lvl1_pn}_NEW",
            help="Enter the distinct top-level assembly or group number for this model.",
        ))
    with c_desc:
        new_desc = clean_bom_cell_text(st.text_input(
            "New Level 1 Description (optional)",
            key=desc_key,
            placeholder="Assembly description (optional)",
            help="Description for the Level 1 assembly.",
        ))

    st.markdown(f"##### Preview Copied Structure ({len(src_bom)} items)")
    prev_copied = []
    first_l1_done_prev = False
    for it in src_bom:
        lvl = int(it.get("level", 1) or 1)
        if lvl == 1 and not first_l1_done_prev:
            prev_copied.append({
                "level": 1,
                "part_number": new_lvl1 or "(Required: enter Level 1 assembly above)",
                "description": new_desc or "",
                "quantity": round(float(it.get("quantity", 1.0) or 1.0), 5),
            })
            first_l1_done_prev = True
        else:
            prev_copied.append({
                "level": lvl if lvl > 1 else 2,
                "part_number": clean_bom_cell_text(it.get("part_number")),
                "description": clean_bom_cell_text(it.get("description")),
                "quantity": round(float(it.get("quantity", 1.0) or 1.0), 5),
            })

    show_all_copy = bool(st.session_state.get(show_all_key, False))
    display_copied = prev_copied if show_all_copy else prev_copied[:12]

    prev_df = pd.DataFrame([
        {
            "Level": it["level"],
            "Part #": it["part_number"],
            "Description": it["description"],
            "Qty": it["quantity"],
        }
        for it in display_copied
    ])
    copy_df_kwargs: dict[str, Any] = {"hide_index": True, "width": "stretch"}
    if show_all_copy:
        copy_df_kwargs["height"] = 320
    st.dataframe(prev_df, **copy_df_kwargs)
    if len(prev_copied) > 12:
        prev_c1, prev_c2 = st.columns([2, 1], vertical_alignment="center")
        with prev_c1:
            if not show_all_copy:
                st.caption(f"... and {len(prev_copied) - 12} more items.")
            else:
                st.caption(f"Showing all {len(prev_copied)} items.")
        with prev_c2:
            if not show_all_copy:
                if st.button(f"👁️ View all ({len(prev_copied)})", key=f"btn_expand_copy_{curr_model_id}", help="Show all rows in a scrollable preview"):
                    st.session_state[show_all_key] = True
                    st.rerun(scope="fragment")
            else:
                if st.button("Collapse preview", key=f"btn_collapse_copy_{curr_model_id}", help="Show first 12 items"):
                    st.session_state[show_all_key] = False
                    st.rerun(scope="fragment")

    c1, c2 = st.columns([1, 1.5], gap="small")
    with c1:
        if st.button("Cancel", key="cancel_copy_dlg"):
            st.session_state.pop(pn_key, None)
            st.session_state.pop(desc_key, None)
            st.session_state.pop(last_sel_key, None)
            st.session_state.pop(cat_sel_key, None)
            st.session_state.pop(show_all_key, None)
            st.rerun()
    with c2:
        if st.button("Copy to BOM Editor", type="primary", key="confirm_copy_dlg"):
            if not new_lvl1:
                st.error("Level 1 Assembly Number is required. Please search the Parts Catalog or enter a part number.")
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
            first_l1_done = False
            for it in src_bom:
                lvl = int(it.get("level", 1) or 1)
                if lvl == 1 and not first_l1_done:
                    copied_draft.append({
                        "level": 1,
                        "part_number": new_lvl1,
                        "description": new_desc,
                        "quantity": round(float(it.get("quantity", 1.0) or 1.0), 5),
                        "_uid": str(uuid4())[:8],
                    })
                    first_l1_done = True
                else:
                    copied_draft.append({
                        "level": lvl if lvl > 1 else 2,
                        "part_number": clean_bom_cell_text(it.get("part_number")),
                        "description": clean_bom_cell_text(it.get("description")),
                        "quantity": round(float(it.get("quantity", 1.0) or 1.0), 5),
                        "_uid": str(uuid4())[:8],
                    })

            st.session_state[d_key] = copied_draft
            st.session_state[s_model_key] = sel_src
            st.session_state.pop(pn_key, None)
            st.session_state.pop(desc_key, None)
            st.session_state.pop(last_sel_key, None)
            st.session_state.pop(cat_sel_key, None)
            st.session_state.pop(show_all_key, None)
            _clear_bld_widget_keys(curr_model_id)
            request_table_editor_reset(ed_logical_key)
            st.toast(f"BOM copied from {src_label} with Level 1 assembly {new_lvl1}!", icon=":material/content_copy:")
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
    valid_pns = [clean_bom_cell_text(it.get("part_number")) for it in current_items if clean_bom_cell_text(it.get("part_number"))]
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
        pn = clean_bom_cell_text(it.get("part_number"))
        desc = clean_bom_cell_text(it.get("description"))
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
                pn = clean_bom_cell_text(it.get("part_number")).upper()
                if pn and not clean_bom_cell_text(it.get("description")) and pn in catalog_parts and catalog_parts[pn]:
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


@st.dialog("📋 Paste BOM from Excel")
def paste_bom_from_excel_dialog(
    proj_id: str,
    curr_model_id: str,
    d_key: str,
    ed_logical_key: str,
) -> None:
    st.markdown(
        "Copy your BOM cells from Excel (**Ctrl+C**) and paste (**Ctrl+V**) into the box below.\n\n"
        "Supported columns: `Level` (1–11), `Part #`, `Description`, `Qty`. "
        "Header row is detected automatically."
    )
    pasted_text = st.text_area(
        "Paste Excel data here",
        placeholder="Level\tPart #\tDescription\tQty\n1\t999D8402G002\tMain Assembly\t1.0\n2\t999D8506P002\tBracket\t2.0",
        height=180,
        key=f"paste_bom_area_{curr_model_id}",
    )

    if pasted_text and pasted_text.strip():
        parsed = parse_pasted_bom_text(pasted_text)
        if parsed:
            st.success(f":material/check_circle: Detected **{len(parsed)}** row(s) from clipboard:")
            show_all_paste_key = f"show_all_paste_prev_{curr_model_id}"
            show_all_paste = bool(st.session_state.get(show_all_paste_key, False))
            display_parsed = parsed if show_all_paste else parsed[:10]

            preview_df = pd.DataFrame([
                {
                    "Level": it["level"],
                    "Part #": it["part_number"],
                    "Description": it["description"],
                    "Qty": it["quantity"],
                }
                for it in display_parsed
            ])
            paste_df_kwargs: dict[str, Any] = {"hide_index": True, "width": "stretch"}
            if show_all_paste:
                paste_df_kwargs["height"] = 320
            st.dataframe(preview_df, **paste_df_kwargs)
            if len(parsed) > 10:
                pst_c1, pst_c2 = st.columns([2, 1], vertical_alignment="center")
                with pst_c1:
                    if not show_all_paste:
                        st.caption(f"... and {len(parsed) - 10} more rows.")
                    else:
                        st.caption(f"Showing all {len(parsed)} rows.")
                with pst_c2:
                    if not show_all_paste:
                        if st.button(f"👁️ View all ({len(parsed)})", key=f"btn_expand_paste_{curr_model_id}", help="Show all pasted rows in a scrollable preview"):
                            st.session_state[show_all_paste_key] = True
                            st.rerun(scope="fragment")
                    else:
                        if st.button("Collapse preview", key=f"btn_collapse_paste_{curr_model_id}", help="Show first 10 rows"):
                            st.session_state[show_all_paste_key] = False
                            st.rerun(scope="fragment")

            c_act1, c_act2, c_act3 = st.columns([1, 1.4, 1.4], gap="small")
            with c_act1:
                if st.button("Cancel", key="btn_cancel_paste_dlg"):
                    st.session_state.pop(show_all_paste_key, None)
                    st.rerun()
            with c_act2:
                if st.button("Replace Editor BOM", type="primary", key="btn_replace_paste_dlg", help="Replace existing rows with pasted data"):
                    st.session_state[d_key] = parsed
                    st.session_state[f"_draft_modified_{curr_model_id}"] = True
                    st.session_state.pop(show_all_paste_key, None)
                    _clear_bld_widget_keys(curr_model_id)
                    request_table_editor_reset(ed_logical_key)
                    st.toast(f"Loaded {len(parsed)} rows into BOM editor!", icon=":material/check_circle:")
                    st.rerun()
            with c_act3:
                if st.button("Append to BOM", key="btn_append_paste_dlg", help="Add pasted rows to bottom of current table"):
                    current_items = _get_live_editor_items(curr_model_id, d_key, ed_logical_key)
                    current_valid = [it for it in current_items if clean_bom_cell_text(it.get("part_number")) or clean_bom_cell_text(it.get("description"))]
                    combined = current_valid + parsed
                    st.session_state[d_key] = combined
                    st.session_state[f"_draft_modified_{curr_model_id}"] = True
                    st.session_state.pop(show_all_paste_key, None)
                    _clear_bld_widget_keys(curr_model_id)
                    request_table_editor_reset(ed_logical_key)
                    st.toast(f"Appended {len(parsed)} rows to BOM editor!", icon=":material/check_circle:")
                    st.rerun()
        else:
            st.warning("Could not extract any valid parts or rows from the pasted text. Please verify the columns.")
            if st.button("Close", key="btn_close_invalid_paste"):
                st.rerun()
    else:
        if st.button("Cancel", key="btn_cancel_empty_paste"):
            st.rerun()


@st.dialog("✨ Predict BOM from Feature Choices")
def generate_bom_from_features_dialog(
    proj_id: str,
    curr_model_id: str,
    d_key: str,
    ed_logical_key: str,
) -> None:
    try:
        prediction = predict_model_bom_from_features(proj_id, curr_model_id)
    except Exception as e:
        st.error(f"Error predicting BOM: {e}")
        if st.button("Close", key="btn_close_pred_err"):
            st.rerun()
        return

    model_num = prediction["model_number"]
    model_name = str(prediction.get("model_name") or "").strip()
    model_disp = f"{model_num} · {model_name}".rstrip(" ·") if model_name else model_num

    tmpl_num = prediction.get("template_model_number")
    tmpl_name = str(prediction.get("template_model_name") or "").strip()
    tmpl_disp = f"{tmpl_num} · {tmpl_name}".rstrip(" ·") if tmpl_name else (tmpl_num or "")
    feat_matches = prediction.get("feature_matches", [])
    substitutions = prediction.get("substitutions", [])
    predicted_items = prediction.get("predicted_items", [])

    st.markdown(f"#### Predicted BOM for **{model_disp}**")

    if tmpl_num:
        st.info(
            f":material/account_tree: **Structural Template:** Based on closest matching model **{tmpl_disp}** with "
            f"**{len(substitutions)}** feature-based part substitution(s)."
        )
    else:
        st.caption(":material/info: No existing model BOM was found to copy hierarchy from. Constructing flat Level 1/2 BOM from catalog parts.")

    if feat_matches:
        with st.expander(f":material/tune: Feature Choices ({len(feat_matches)})", expanded=False):
            for fm in feat_matches:
                parts_str = f" &rarr; Parts: `{', '.join(fm['matched_parts'])}`" if fm['matched_parts'] else " &rarr; *(No part rules)*"
                st.markdown(f"• **{fm['feature_name']}**: `{fm['selected_value']}`{parts_str}")

    if substitutions:
        with st.expander(f":material/swap_horiz: Feature Part Substitutions ({len(substitutions)})", expanded=True):
            sub_df = pd.DataFrame([
                {
                    "Feature": s["feature_name"],
                    "Original Part": s["from_part"],
                    "Replaced With": s["to_part"],
                    "Choice": f"{s['from_value']} → {s['to_value']}",
                }
                for s in substitutions
            ])
            st.dataframe(sub_df, hide_index=True, width="stretch")

    st.markdown("##### :material/tag: Level 1 Assembly Number *")
    st.caption(
        "Specify the top-level assembly part number for this model. "
        "You can search and select an assembly from the Parts Catalog, or type a part number directly."
    )

    cat_rows = query("SELECT part_number, description FROM parts WHERE project_id=? ORDER BY part_number", (proj_id,))
    cat_parts_dict = {
        str(r["part_number"]).strip(): str(r["description"] or "").strip()
        for r in cat_rows
        if clean_bom_cell_text(r.get("part_number"))
    }
    cat_options = ["-- Select from Parts Catalog --"] + [
        f"{pn} · {desc}".rstrip(" ·") for pn, desc in cat_parts_dict.items()
    ]

    pn_key = f"pred_lvl1_pn_{curr_model_id}"
    desc_key = f"pred_lvl1_desc_{curr_model_id}"
    last_sel_key = f"_last_pred_cat_select_{curr_model_id}"
    cat_sel_key = f"pred_cat_select_{curr_model_id}"

    if pn_key not in st.session_state:
        curr_draft = st.session_state.get(d_key, [])
        existing_l1 = next((r for r in curr_draft if r.get("level") == 1 and clean_bom_cell_text(r.get("part_number"))), None)
        if existing_l1 and not str(existing_l1.get("part_number", "")).endswith("_TOP"):
            st.session_state[pn_key] = str(existing_l1.get("part_number") or "").strip()
            st.session_state[desc_key] = str(existing_l1.get("description") or "").strip()
        else:
            st.session_state[pn_key] = ""
            st.session_state[desc_key] = ""

    sel_cat = st.selectbox(
        "Search & Choose from Parts Catalog",
        options=cat_options,
        key=cat_sel_key,
        help="Search the Parts Catalog by part number or description to populate the Level 1 assembly.",
    )

    if sel_cat != "-- Select from Parts Catalog --":
        if sel_cat != st.session_state.get(last_sel_key):
            selected_pn = sel_cat.split(" · ")[0].strip()
            selected_desc = cat_parts_dict.get(selected_pn, "")
            st.session_state[last_sel_key] = sel_cat
            st.session_state[pn_key] = selected_pn
            st.session_state[desc_key] = selected_desc
    else:
        st.session_state[last_sel_key] = ""

    c_pn, c_desc = st.columns([1, 1.4], gap="small")
    with c_pn:
        lvl1_pn = clean_bom_cell_text(st.text_input(
            "Level 1 Assembly Number *",
            key=pn_key,
            placeholder="e.g. 999D8842G001",
            help="Required top-level assembly number.",
        ))
    with c_desc:
        lvl1_desc = clean_bom_cell_text(st.text_input(
            "Level 1 Description",
            key=desc_key,
            placeholder="e.g. Urban Coupe Final Assembly",
            help="Description for the Level 1 assembly.",
        ))

    st.markdown(f"##### Preview Predicted Structure ({len(predicted_items)} items)")
    prev_items = [dict(it) for it in predicted_items]
    if prev_items and prev_items[0].get("level") == 1:
        prev_items[0]["part_number"] = lvl1_pn or "(Required: enter Level 1 assembly above)"
        prev_items[0]["description"] = lvl1_desc or ""

    show_all_key = f"show_all_pred_prev_{curr_model_id}"
    show_all = bool(st.session_state.get(show_all_key, False))
    display_items = prev_items if show_all else prev_items[:12]

    prev_df = pd.DataFrame([
        {
            "Level": it["level"],
            "Part #": it["part_number"],
            "Description": it["description"],
            "Qty": it["quantity"],
        }
        for it in display_items
    ])
    pred_df_kwargs: dict[str, Any] = {"hide_index": True, "width": "stretch"}
    if show_all:
        pred_df_kwargs["height"] = 320
    st.dataframe(prev_df, **pred_df_kwargs)
    if len(prev_items) > 12:
        prev_c1, prev_c2 = st.columns([2, 1], vertical_alignment="center")
        with prev_c1:
            if not show_all:
                st.caption(f"... and {len(prev_items) - 12} more items.")
            else:
                st.caption(f"Showing all {len(prev_items)} items.")
        with prev_c2:
            if not show_all:
                if st.button(f"👁️ View all ({len(prev_items)})", key=f"btn_expand_pred_{curr_model_id}", help="Show all predicted rows in a scrollable preview"):
                    st.session_state[show_all_key] = True
                    st.rerun(scope="fragment")
            else:
                if st.button("Collapse preview", key=f"btn_collapse_pred_{curr_model_id}", help="Show first 12 items"):
                    st.session_state[show_all_key] = False
                    st.rerun(scope="fragment")

    c1, c2 = st.columns([1, 1.5], gap="small")
    with c1:
        if st.button("Cancel", key="btn_cancel_pred_dlg"):
            st.session_state.pop(pn_key, None)
            st.session_state.pop(desc_key, None)
            st.session_state.pop(last_sel_key, None)
            st.session_state.pop(cat_sel_key, None)
            st.session_state.pop(show_all_key, None)
            st.rerun()
    with c2:
        if st.button("Apply to BOM Editor", type="primary", key="btn_apply_pred_dlg"):
            if not lvl1_pn:
                st.error("Level 1 Assembly Number is required. Please search the Parts Catalog or enter a part number.")
                return

            other_l1 = get_model_level1_assemblies(proj_id, exclude_model_id=curr_model_id)
            if lvl1_pn.upper() in other_l1:
                st.error(
                    f"Level 1 Assembly Number '{lvl1_pn}' is already assigned to model '{other_l1[lvl1_pn.upper()]}'. "
                    f"Each model must have a distinct Level 1 Assembly Number."
                )
                return

            final_items = [dict(it) for it in predicted_items]
            if final_items and final_items[0].get("level") == 1:
                final_items[0]["part_number"] = lvl1_pn
                final_items[0]["description"] = lvl1_desc
                final_items[0]["quantity"] = 1.0
            else:
                final_items.insert(0, {
                    "level": 1,
                    "part_number": lvl1_pn,
                    "description": lvl1_desc,
                    "quantity": 1.0,
                    "_uid": str(uuid4())[:8],
                })

            st.session_state[d_key] = final_items
            st.session_state[f"_draft_modified_{curr_model_id}"] = True
            _clear_bld_widget_keys(curr_model_id)
            request_table_editor_reset(ed_logical_key)
            st.session_state.pop(pn_key, None)
            st.session_state.pop(desc_key, None)
            st.session_state.pop(last_sel_key, None)
            st.session_state.pop(cat_sel_key, None)
            st.session_state.pop(show_all_key, None)
            st.toast(f"Loaded predicted BOM ({len(final_items)} items) with Level 1 assembly {lvl1_pn} into editor!", icon=":material/check_circle:")
            st.rerun()


@st.dialog("⚠️ Group Number Structure Conflict")
def group_conflict_dialog(
    proj_id: str,
    curr_model_id: str,
    d_key: str,
    ed_logical_key: str,
    s_model_key: str,
) -> None:
    conflict_data = st.session_state.get(f"_pending_group_conflict_{curr_model_id}")
    if not conflict_data:
        st.rerun()
        return

    rows = conflict_data["rows"]
    conflicts = conflict_data["conflicts"]
    auto_add = conflict_data.get("auto_add", True)

    st.warning(
        ":material/warning: **Structure Discrepancy on Shared Group / Drawing Number**\n\n"
        "One or more group numbers or drawing assemblies in your BOM have a different set of child components "
        "or quantities compared to existing saved BOMs in this project. "
        "In manufacturing engineering, identical group numbers should represent identical assemblies unless a designated variation is intended."
    )

    for cf in conflicts:
        g_id = cf["group_identifier"]
        g_type = cf.get("group_type", "Group Number")
        other_num = cf["conflicting_model_number"]
        diffs = cf.get("differences", [])

        st.markdown(f"##### {g_type} `{g_id}` conflicts with Model **{other_num}**")
        diff_rows = []
        for d in diffs:
            t = d["type"]
            t_label = "Qty Mismatch" if t == "quantity_mismatch" else ("Missing in Current" if t == "missing_in_current" else "Extra in Current")
            diff_rows.append({
                "Component Part": d["part_number"],
                "Issue": t_label,
                "Current Qty": d["current_qty"],
                f"Model {other_num} Qty": d["other_qty"],
            })
        st.dataframe(pd.DataFrame(diff_rows), hide_index=True, width="stretch")

    c1, c2 = st.columns([1, 1.5], gap="small")
    with c1:
        if st.button("Revise Group in Editor", key="btn_cancel_conflict_dlg", help="Return to editor to adjust group number or parts"):
            st.session_state.pop(f"_pending_group_conflict_{curr_model_id}", None)
            st.rerun()
    with c2:
        if st.button("Confirm Variation & Proceed", type="primary", key="btn_bypass_conflict_dlg", help="Confirm that this variation is intended and proceed with saving"):
            st.session_state.pop(f"_pending_group_conflict_{curr_model_id}", None)
            detected = detect_unexpanded_subassemblies(proj_id, rows)
            if detected:
                st.session_state[f"_pending_save_flow_{curr_model_id}"] = {
                    "rows": rows,
                    "detected": detected,
                    "auto_add": auto_add,
                }
                st.rerun()
            else:
                _commit_bom_save(proj_id, curr_model_id, rows, auto_add, d_key, ed_logical_key, s_model_key)


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

        # Check if a pending group conflict or save prompt flow is awaiting user action
        if f"_pending_group_conflict_{selected_model_id}" in st.session_state:
            group_conflict_dialog(
                project_id,
                selected_model_id,
                draft_key,
                bom_editor_logical_key,
                source_model_key,
            )
        elif f"_pending_save_flow_{selected_model_id}" in st.session_state:
            save_subassembly_prompt_dialog(
                project_id,
                selected_model_id,
                draft_key,
                bom_editor_logical_key,
                source_model_key,
            )


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

            row_tools_idx_key = f"row_tools_idx_{selected_model_id}"

            # ── Action Bar (Row 1): Checkbox & Save Actions ──
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

            # ── Action Bar (Row 2): Template, Import, Paste, Copy, Predict ──
            tool_c1, tool_c2, tool_c3, tool_c4, tool_c5 = st.columns([1, 1, 1, 1.1, 1.2], gap="small")
            with tool_c1:
                live_for_dl = _get_live_editor_items(selected_model_id, draft_key, bom_editor_logical_key)
                has_tree_items = any(
                    bool(clean_bom_cell_text(it.get("part_number")) or clean_bom_cell_text(it.get("description")))
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
                    label="📥 Download Template",
                    data=generate_bom_excel_template(live_for_dl),
                    file_name=dl_file_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_template_{selected_model_id}",
                    help=dl_help,
                    width="stretch",
                )
            with tool_c2:
                with st.popover("📤 Import File", help="Upload a BOM spreadsheet to populate the table"):
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
            with tool_c3:
                if st.button(
                    "📋 Paste from Excel",
                    key=f"btn_paste_{selected_model_id}",
                    help="Paste tabular data directly from Excel clipboard",
                    width="stretch",
                ):
                    paste_bom_from_excel_dialog(project_id, selected_model_id, draft_key, bom_editor_logical_key)
            with tool_c4:
                if st.button(
                    "👥 Copy from Model",
                    key=f"btn_copy_model_{selected_model_id}",
                    help="Copy the BOM hierarchy from another saved model in this project",
                    width="stretch",
                ):
                    copy_bom_dialog(project_id, selected_model_id, draft_key, bom_editor_logical_key, source_model_key)
            with tool_c5:
                if st.button(
                    "✨ Predict from Features",
                    key=f"btn_predict_features_{selected_model_id}",
                    help="Predict BOM structure based on Complexity Trees feature choices",
                    width="stretch",
                ):
                    generate_bom_from_features_dialog(project_id, selected_model_id, draft_key, bom_editor_logical_key)

            # ── Build DataFrame from current draft ──
            # Columns match Excel order: Level, Part #, Description, Qty
            df_editor_data = pd.DataFrame([
                {
                    "Level": int(it.get("level", 1) or 1),
                    "Part #": str(it.get("part_number", "") or ""),
                    "Description": str(it.get("description", "") or ""),
                    "Qty": round(float(it.get("quantity", 1.0) or 1.0), 5),
                }
                for it in current_draft
            ])
            if df_editor_data.empty:
                df_editor_data = pd.DataFrame([{
                    "Level": 1,
                    "Part #": "",
                    "Description": "",
                    "Qty": 1.0,
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
                },
                num_rows="dynamic",
                hide_index=True,
                key=bom_editor_key,
                width="stretch",
                height=560,
            )

            # ── Save action ──
            if save_clicked:
                rows_to_save = []
                validation_errors = []
                for pos_idx, (_, r) in enumerate(edited_df.iterrows(), start=1):
                    pn = clean_bom_cell_text(r.get("Part #"))
                    desc = " ".join(clean_bom_cell_text(r.get("Description")).split())
                    qty_raw = r.get("Qty")
                    lvl_raw = r.get("Level")
                    # Skip completely blank rows silently
                    if not pn and not desc:
                        continue
                    if not pn:
                        validation_errors.append(f"Row {pos_idx}: Part # is required.")
                        continue
                    try:
                        lvl = int(float(lvl_raw)) if lvl_raw is not None and not pd.isna(lvl_raw) else 1
                        lvl = max(1, min(11, lvl))
                    except (TypeError, ValueError):
                        lvl = 1
                    try:
                        qty = float(qty_raw) if qty_raw is not None and not pd.isna(qty_raw) else 1.0
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
                    conflicts = check_group_number_conflicts(project_id, selected_model_id, rows_to_save)
                    if conflicts:
                        st.session_state[f"_pending_group_conflict_{selected_model_id}"] = {
                            "rows": rows_to_save,
                            "conflicts": conflicts,
                            "auto_add": auto_add_grid,
                        }
                        st.rerun()

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
