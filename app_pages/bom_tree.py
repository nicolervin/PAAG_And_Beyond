"""BOM Tree page for viewing and managing model product structure.

Replaces Assembly Grid with an indented parent-child tree view sourced from
approved Fishbone, Parts Catalog, and manufacturing assembly data, with
inline PITS BOM occurrence review and approval, editable Use / installation
locations, and EBOM category-to-model mapping.
"""

from uuid import uuid4
import pandas as pd
import streamlit as st

from utils.scope_ui import page_title_with_scope
from utils.store import (
    assembly_catalog_rows,
    assembly_grid_categories,
    assembly_grid_model_mappings,
    assembly_sections,
    audit_history,
    escalate_pits_bom_occurrence,
    model_bom_tree_nodes,
    pits_bom_occurrences,
    project_models,
    record_audit_event,
    review_pits_bom_occurrences,
    save_assembly_catalog_rows,
    save_assembly_grid_model_mappings,
    save_assembly_grid_sections,
    update_fishbone_assignment_use,
)
from utils.table_ui import selectable_dataframe, selected_dataframe_rows

page_title_with_scope("BOM Tree", scope="project")

project_id = st.session_state.get("project_id")
if not project_id:
    st.warning("Select or create a project first.")
    st.stop()

editor_name = str(st.session_state.get("current_editor") or "").strip() or "Collaborator"

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

sections_df = assembly_sections(project_id)
active_sections = (
    sections_df.loc[sections_df["active"].fillna(1).astype(bool)]
    if not sections_df.empty
    else pd.DataFrame()
)
section_labels = {
    str(row["id"]): str(row["name"]) for _, row in active_sections.iterrows()
}
default_section_id = str(active_sections.iloc[0]["id"]) if not active_sections.empty else ""

# Category-to-model mapping per Must-Have Scope Item 6
grid_cats = assembly_grid_categories(project_id)
grid_maps = assembly_grid_model_mappings(project_id)
catalog_asms = assembly_catalog_rows(project_id)

with st.expander(
    f":material/hub: Category-to-model mapping ({len(grid_cats)} categories)",
    expanded=False,
):
    st.write(
        "Map named EBOM categories to real assembly part numbers for the selected model. "
        "Top-level packaged units and subassembly configurations are preserved project-wide."
    )
    if grid_cats.empty:
        st.info("No EBOM categories defined for this project yet. Add categories below.")
    else:
        st.caption(f"Configuring assembly assignments for model: **{model_options.get(selected_model_id)}**")
        model_mappings = grid_maps.loc[grid_maps["model_id"].astype(str).eq(str(selected_model_id))]
        cat_to_asm = {
            str(r["category_id"]): str(r["assembly_id"])
            for _, r in model_mappings.iterrows()
            if pd.notna(r.get("assembly_id"))
        }

        cat_choices = {}
        for _, cat in grid_cats.iterrows():
            cid = str(cat["id"])
            c_name = cat["display_name"] or cat["ebom_name"]
            c_sec = cat.get("section_name", "")
            is_top = bool(cat.get("is_top_level"))
            badge = " [Top-level packaged unit]" if is_top else ""

            matching_asms = catalog_asms.loc[
                catalog_asms["built_section_id"].astype(str).eq(str(cat["section_id"]))
            ]
            asm_options = {"": "— None (Unassigned) —"}
            for _, a in matching_asms.iterrows():
                asm_options[str(a["id"])] = f"{a['assembly_number']} · {a['name']}"

            curr_asm_id = cat_to_asm.get(cid, "")
            if curr_asm_id and curr_asm_id not in asm_options:
                asm_row = catalog_asms.loc[catalog_asms["id"].astype(str).eq(curr_asm_id)]
                if not asm_row.empty:
                    asm_options[curr_asm_id] = f"{asm_row.iloc[0]['assembly_number']} · {asm_row.iloc[0]['name']}"

            init_idx = list(asm_options.keys()).index(curr_asm_id) if curr_asm_id in asm_options else 0
            selected_asm = st.selectbox(
                f"{c_name}{badge} (Section: {c_sec})",
                options=list(asm_options.keys()),
                index=init_idx,
                format_func=lambda aid: asm_options.get(aid, aid),
                key=f"cat_map_sel_{selected_model_id}_{cid}",
            )
            cat_choices[cid] = selected_asm

        col_save_m, _ = st.columns([2, 5])
        if col_save_m.button("Save category mappings", type="primary", key=f"btn_save_cat_maps_{project_id}"):
            other_mappings = grid_maps.loc[~grid_maps["model_id"].astype(str).eq(str(selected_model_id))]
            retained_records = []
            for _, r in other_mappings.iterrows():
                retained_records.append({
                    "id": str(r["id"]),
                    "category_id": str(r["category_id"]),
                    "model_id": str(r["model_id"]),
                    "assembly_id": str(r["assembly_id"]) if pd.notna(r.get("assembly_id")) else None,
                    "assembly_number": str(r["assembly_number"]) if pd.notna(r.get("assembly_number")) else None,
                })

            for cid, aid in cat_choices.items():
                if aid:
                    asm_row = catalog_asms.loc[catalog_asms["id"].astype(str).eq(aid)]
                    asm_num = str(asm_row.iloc[0]["assembly_number"]) if not asm_row.empty else ""
                    retained_records.append({
                        "category_id": cid,
                        "model_id": selected_model_id,
                        "assembly_id": aid,
                        "assembly_number": asm_num,
                    })

            try:
                res = save_assembly_grid_model_mappings(project_id, retained_records)
                record_audit_event(
                    project_id,
                    "BOM Tree",
                    "Update category mappings",
                    len(cat_choices),
                    editor_name,
                    {"model_id": selected_model_id, "total_mappings": res.get("count")},
                )
                st.toast("Saved category mappings for model!", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    st.markdown("---")
    with st.expander(":material/add: Add new EBOM category", expanded=False):
        with st.form(key=f"add_ebom_cat_form_{project_id}"):
            new_ebom_name = st.text_input("Official EBOM category name *")
            new_disp_name = st.text_input("Display name (optional)")
            new_cat_sec = st.selectbox(
                "Fishbone section *",
                options=list(section_labels.keys()),
                format_func=lambda sid: section_labels.get(sid, sid),
            )
            new_inst_sec = st.selectbox(
                "Installed section (optional)",
                options=["None"] + list(section_labels.keys()),
                format_func=lambda sid: "Same as built section" if sid == "None" else section_labels.get(sid, sid),
            )
            is_top_unit = st.checkbox("Top-level packaged unit")
            submit_cat = st.form_submit_button("Create category", type="primary")
            if submit_cat:
                if not new_ebom_name.strip():
                    st.error("Official EBOM category name is required.")
                else:
                    inst_val = None if new_inst_sec == "None" else new_inst_sec
                    try:
                        save_assembly_grid_sections(
                            project_id,
                            new_cat_sec,
                            [{
                                "id": str(uuid4()),
                                "ebom_name": new_ebom_name.strip(),
                                "display_name": (new_disp_name.strip() or new_ebom_name.strip()),
                                "root_number": "",
                                "is_top_level": is_top_unit,
                                "installed_section_id": inst_val,
                                "sequence": (len(grid_cats) + 1) * 10,
                            }],
                        )
                        record_audit_event(
                            project_id,
                            "BOM Tree",
                            "Create EBOM category",
                            1,
                            editor_name,
                            {"ebom_name": new_ebom_name, "section_id": new_cat_sec},
                        )
                        st.toast(f"Created EBOM category '{new_ebom_name}'", icon=":material/check_circle:")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

# Review queue expander per Must-Have Scope Item 2
staged_queue = pits_bom_occurrences(project_id, actionable_only=True)
if not staged_queue.empty:
    with st.expander(
        f":material/pending_actions: PITS BOM structure review queue ({len(staged_queue)} pending review)",
        expanded=False,
    ):
        st.write(
            "Review staged PITS BOM occurrences for this project. You can approve or escalate items here in batch, "
            "or review them inline directly within the tree view below."
        )
        display_queue = staged_queue.copy()
        display_queue["depth_label"] = "Level " + display_queue["proposed_depth"].astype(str)
        q_event = selectable_dataframe(
            display_queue,
            key=f"bom_tree_review_queue_table_{project_id}",
            hide_index=True,
            column_order=[
                "depth_label",
                "parent_tracker_number",
                "child_tracker_number",
                "child_part_number",
                "child_part_name",
                "proposed_quantity",
                "source_state",
                "review_status",
            ],
            column_config={
                "depth_label": st.column_config.TextColumn("Depth", width="small"),
                "parent_tracker_number": st.column_config.TextColumn("Parent tracker", width="small"),
                "child_tracker_number": st.column_config.TextColumn("Child tracker", width="small"),
                "child_part_number": st.column_config.TextColumn("Part number", width="medium"),
                "child_part_name": st.column_config.TextColumn("Part name", width="large"),
                "proposed_quantity": st.column_config.NumberColumn("Quantity", format="%g", width="small"),
                "source_state": st.column_config.TextColumn("Source state", width="small"),
                "review_status": st.column_config.TextColumn("Review status", width="small"),
            },
        )
        selected_q_rows = selected_dataframe_rows(display_queue, q_event)
        q_cols = st.columns([3, 1.5, 1.5])
        q_target_sec = q_cols[0].selectbox(
            "Target Fishbone section for selected items",
            options=list(section_labels.keys()),
            format_func=lambda sid: section_labels.get(sid, sid),
            key=f"bom_tree_queue_sec_{project_id}",
        )
        if q_cols[1].button("Approve selected", disabled=selected_q_rows.empty, type="primary"):
            approved_count = 0
            for _, r in selected_q_rows.iterrows():
                try:
                    review_pits_bom_occurrences(
                        project_id,
                        [str(r["id"])],
                        "Approve",
                        editor_name,
                        section_id=q_target_sec,
                    )
                    approved_count += 1
                except ValueError as exc:
                    st.error(f"Error approving {r.get('child_part_number')}: {exc}")
                    break
            if approved_count > 0:
                st.toast(f"Approved {approved_count} occurrence(s)", icon=":material/check_circle:")
                st.rerun()

        if q_cols[2].button("Escalate selected", disabled=selected_q_rows.empty):
            escalated_count = 0
            for _, r in selected_q_rows.iterrows():
                try:
                    escalate_pits_bom_occurrence(project_id, str(r["id"]), editor_name)
                    escalated_count += 1
                except ValueError as exc:
                    st.error(f"Error escalating {r.get('child_part_number')}: {exc}")
                    break
            if escalated_count > 0:
                st.warning(f"Escalated {escalated_count} occurrence(s) to Questions & concerns")
                st.rerun()

try:
    tree_nodes = model_bom_tree_nodes(project_id, selected_model_id, include_staged=True)
except ValueError as exc:
    st.error(str(exc))
    st.stop()

if not tree_nodes:
    st.info(
        "No product structure or Fishbone components have been placed for this model yet. "
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
total_pending = sum(1 for n in tree_nodes if n.get("review_status") == "Needs review")

metric_cols = st.columns(4)
metric_cols[0].metric("Total tree items", total_items)
metric_cols[1].metric("Assemblies", total_assemblies)
metric_cols[2].metric("Components / Parts", total_components)
metric_cols[3].metric("Needs review", total_pending)

st.markdown("---")

filter_col1, filter_col2, filter_col3 = st.columns([2.5, 1.5, 1])
search_query = filter_col1.text_input(
    "Search parts, assemblies, or uses",
    placeholder="Type part number, name, or use...",
    key=f"bom_tree_search_{project_id}",
).strip().lower()

all_sections = sorted(list(section_labels.values()))
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
                    "node_id": n["id"],
                    "Structure": f"{indent}{n['part_number']} · {n['part_name']}",
                    "Depth": f"Level {n['depth']}",
                    "Part number": n["part_number"],
                    "Part Name": n["part_name"],
                    "Type": n["node_type"],
                    "Quantity": n["quantity"],
                    "Status": n["review_status"],
                    "Built section": n["built_section_name"],
                    "Installed section": n["installed_section_name"] or "—",
                    "Use / installation location": n["use_description"] or "—",
                    "PITS traceability": _format_traceability(n) or "—",
                }
            )
        table_df = pd.DataFrame(table_rows)
        tbl_event = selectable_dataframe(
            table_df,
            key=f"bom_tree_table_view_{project_id}",
            hide_index=True,
            column_order=[
                "Structure",
                "Depth",
                "Part number",
                "Part Name",
                "Type",
                "Quantity",
                "Status",
                "Built section",
                "Installed section",
                "Use / installation location",
                "PITS traceability",
            ],
            column_config={
                "Structure": st.column_config.TextColumn("Product structure tree", width="large"),
                "Depth": st.column_config.TextColumn("Depth", width="small"),
                "Part number": st.column_config.TextColumn("Part number", width="medium"),
                "Part Name": st.column_config.TextColumn("Part Name", width="large"),
                "Type": st.column_config.TextColumn("Type", width="small"),
                "Quantity": st.column_config.NumberColumn("Quantity", format="%g", width="small"),
                "Status": st.column_config.TextColumn("Review status", width="small"),
                "Built section": st.column_config.TextColumn("Built section", width="medium"),
                "Installed section": st.column_config.TextColumn("Installed section", width="medium"),
                "Use / installation location": st.column_config.TextColumn("Use / installation location", width="large"),
                "PITS traceability": st.column_config.TextColumn("PITS traceability", width="medium"),
            },
        )
        selected_tbl_rows = selected_dataframe_rows(table_df, tbl_event)
        if not selected_tbl_rows.empty:
            sel_item = selected_tbl_rows.iloc[0]
            matched_node = next((n for n in filtered_nodes if n["id"] == sel_item.get("node_id")), None)
            if matched_node and matched_node.get("assignment_id"):
                st.markdown("---")
                st.markdown(
                    f"**:material/edit: Edit Use / installation location for `{matched_node['part_number']}` · {matched_node['part_name']}**"
                )
                col_u1, col_u2 = st.columns([4, 1])
                new_tbl_use = col_u1.text_input(
                    "Use / installation location",
                    value=matched_node.get("use_description") or "",
                    key=f"table_edit_use_{matched_node['id']}",
                )
                if col_u2.button("Save location", type="primary", key=f"table_save_use_{matched_node['id']}"):
                    try:
                        update_fishbone_assignment_use(project_id, matched_node["assignment_id"], new_tbl_use, editor_name)
                        st.toast(f"Updated use location for {matched_node['part_number']}", icon=":material/check_circle:")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
    else:
        # Tree card/row view with inline approval actions and use editing
        st.caption(
            "Product structure hierarchy for selected model. Quantities are read-only and synchronized from PITS/Fishbone."
        )

        # Header row
        h_cols = st.columns([3.0, 1.1, 0.7, 1.3, 1.3, 1.6, 1.4, 1.6])
        h_cols[0].markdown("**Tree item (Part / Assembly)**")
        h_cols[1].markdown("**Type**")
        h_cols[2].markdown("**Quantity**")
        h_cols[3].markdown("**Built section**")
        h_cols[4].markdown("**Installed section**")
        h_cols[5].markdown("**Use / location**")
        h_cols[6].markdown("**Status / Traceability**")
        h_cols[7].markdown("**Action**")

        icon_by_type = {
            "Top-level packaged unit": ":material/inventory_2:",
            "Assembly": ":material/precision_manufacturing:",
            "Component": ":material/category:",
            "Fishbone Part": ":material/account_tree:",
            "Fishbone Section": ":material/folder:",
        }

        for idx, n in enumerate(filtered_nodes):
            depth = n["depth"]
            icon = icon_by_type.get(n["node_type"], ":material/circle:")
            trace_label = _format_traceability(n)
            is_unapproved = n.get("review_status") == "Needs review"

            # Container for row
            with st.container(border=True):
                r_cols = st.columns([3.0, 1.1, 0.7, 1.3, 1.3, 1.6, 1.4, 1.6])

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

                # Editable use / installation location per Must-Have Scope Item 5
                if n.get("assignment_id"):
                    with r_cols[5]:
                        curr_use = n["use_description"] or "—"
                        with st.popover(curr_use, help="Click to edit use / installation location"):
                            edit_use_val = st.text_input(
                                "Use / installation location",
                                value=n["use_description"] or "",
                                key=f"pop_use_{idx}_{n['id']}",
                            )
                            if st.button("Save location", key=f"btn_pop_save_{idx}_{n['id']}", type="primary"):
                                try:
                                    update_fishbone_assignment_use(
                                        project_id, n["assignment_id"], edit_use_val, editor_name
                                    )
                                    st.toast(f"Updated use location for {n['part_number']}", icon=":material/check_circle:")
                                    st.rerun()
                                except ValueError as exc:
                                    st.error(str(exc))
                else:
                    r_cols[5].markdown(n["use_description"] or "—")

                if is_unapproved:
                    r_cols[6].markdown(f":material/warning: **Needs review** (`{n.get('source_state', 'New')}`)")
                    occ_id = n["occurrence_id"]

                    # Action column per Item 7
                    if not n["is_g_format"]:
                        # Ordinary piece part: immediate inline Approve button with no dialog
                        target_sec = n["built_section_id"] or default_section_id
                        if r_cols[7].button(
                            "Approve",
                            key=f"inline_appr_part_{idx}_{occ_id}",
                            type="primary",
                            help="Immediately approve this piece part into Fishbone with no dialog",
                        ):
                            try:
                                review_pits_bom_occurrences(
                                    project_id,
                                    [occ_id],
                                    "Approve",
                                    editor_name,
                                    section_id=target_sec,
                                )
                                st.toast(f"Approved {n['part_number']}", icon=":material/check_circle:")
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))
                    else:
                        # Gxxx assembly group: accordion expand in-place
                        is_expanded = st.session_state.get(f"expand_g_{occ_id}", False)
                        btn_txt = "Collapse" if is_expanded else "Review & Assign…"
                        if r_cols[7].button(
                            btn_txt,
                            key=f"inline_tgl_asm_{idx}_{occ_id}",
                            help="Expand in place to assign Built and Installed sections",
                        ):
                            st.session_state[f"expand_g_{occ_id}"] = not is_expanded
                            st.rerun()

                        if is_expanded:
                            st.markdown("---")
                            st.markdown(
                                f"**:material/tune: Assign Fishbone sections for assembly `{n['part_number']}` · {n['part_name']}**"
                            )
                            col_b, col_i, col_acts = st.columns([2.5, 2.5, 2.0])
                            built_choice = col_b.selectbox(
                                "Built section *",
                                options=list(section_labels.keys()),
                                format_func=lambda sid: section_labels.get(sid, sid),
                                key=f"bsec_sel_{idx}_{occ_id}",
                                help="Section where this assembly group is physically fabricated / subassembled.",
                            )
                            installed_choice = col_i.selectbox(
                                "Installed section (optional)",
                                options=["None"] + list(section_labels.keys()),
                                format_func=lambda sid: "Same as Built section" if sid == "None" else section_labels.get(sid, sid),
                                key=f"isec_sel_{idx}_{occ_id}",
                                help="Section where this subassembly is installed into the main product.",
                            )
                            with col_acts:
                                st.write("")
                                col_b1, col_b2 = st.columns(2)
                                if col_b1.button("Approve", key=f"appr_g_btn_{idx}_{occ_id}", type="primary"):
                                    inst_id = None if installed_choice == "None" else installed_choice
                                    try:
                                        review_pits_bom_occurrences(
                                            project_id,
                                            [occ_id],
                                            "Approve",
                                            editor_name,
                                            section_id=built_choice,
                                        )
                                        save_assembly_catalog_rows(project_id, [{
                                            "id": str(uuid4()),
                                            "assembly_number": n["part_number"],
                                            "name": n["part_name"] or n["part_number"],
                                            "built_section_id": built_choice,
                                            "installed_section_id": inst_id,
                                            "active": True,
                                            "catalog_part_id": n.get("part_id"),
                                        }])
                                        st.session_state[f"expand_g_{occ_id}"] = False
                                        st.toast(f"Approved {n['part_number']} assembly", icon=":material/check_circle:")
                                        st.rerun()
                                    except ValueError as exc:
                                        st.error(str(exc))
                                if col_b2.button("Escalate", key=f"esc_g_btn_{idx}_{occ_id}"):
                                    try:
                                        cid = escalate_pits_bom_occurrence(project_id, occ_id, editor_name)
                                        st.session_state[f"expand_g_{occ_id}"] = False
                                        st.warning(f"Escalated to Questions & concerns (#{cid[:8]})")
                                        st.rerun()
                                    except ValueError as exc:
                                        st.error(str(exc))
                else:
                    if trace_label:
                        r_cols[6].caption(f":material/history: {trace_label}")
                    else:
                        r_cols[6].markdown("—")
                    r_cols[7].caption(":material/check_circle: Approved")

st.markdown("---")
with st.expander("Audit history", expanded=False):
    history = audit_history(project_id, "BOM Tree", limit=50)
    if history.empty:
        history = audit_history(project_id, "Assembly grid", limit=50)
    if history.empty:
        st.caption("No BOM Tree history has been recorded yet.")
    else:
        st.dataframe(history.drop(columns=["details"], errors="ignore"), hide_index=True)
