import altair as alt
import pandas as pd
import streamlit as st

from utils.store import (
    add_assembly_section,
    assembly_sections,
    assign_parts_to_section,
    fishbone_part_assignments,
    project_table,
    reorder_assembly_section,
    replace_fishbone_part_assignments,
    update_assembly_section_rows,
)
from utils.table_filters import filter_table, matches_filter_value, merge_filtered_edits, split_filter_values


project_id = st.session_state.get("project_id")
st.title("Parts to assembly fishbone")
st.caption("Build the assembly framework first, then place approved Parts-table content into its sections and subassemblies.")
if not project_id:
    st.stop()

parts = project_table("parts", project_id, "part_number")
sections = assembly_sections(project_id)
assignments = fishbone_part_assignments(project_id)


def normalized_parent_id(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()

metrics = st.columns(4)
metrics[0].metric("Parts available", len(parts), border=True)
metrics[1].metric("Framework sections", len(sections), border=True)
metrics[2].metric("Parts placed", len(assignments), border=True)
metrics[3].metric("Parts remaining", max(0, len(parts) - len(assignments)), border=True)

st.header("1 · Build the assembly framework")
st.caption("Main-spine sections establish product assembly order. Subassemblies—such as Wheel Subassembly—must attach to a parent section or subassembly.")

active_sections = sections.loc[sections["active"].fillna(1).astype(bool)].copy() if not sections.empty else sections
section_name_by_id = dict(zip(sections["id"].astype(str), sections["name"].astype(str))) if not sections.empty else {}
parent_options = active_sections["id"].astype(str).tolist() if not active_sections.empty else []

with st.expander("Add a section or subassembly", icon=":material/add:", expanded=sections.empty):
    section_form_version_key = f"section_form_version_{project_id}"
    st.session_state.setdefault(section_form_version_key, 0)
    with st.form(f"add_assembly_section_{st.session_state[section_form_version_key]}"):
        section_row = st.columns([2, 1, 2])
        section_name = section_row[0].text_input("Name", placeholder="Wheel Subassembly")
        section_type = section_row[1].selectbox("Type", ["Main spine", "Subassembly"])
        parent_id = section_row[2].selectbox(
            "Parent assembly",
            options=[None, *parent_options],
            format_func=lambda value: "Product / main assembly" if value is None else section_name_by_id.get(value, value),
            help="Required for a subassembly. Main-spine sections attach directly to the product.",
        )
        section_description = st.text_area("Framework description", placeholder="What is assembled in this section?")
        if st.form_submit_button("Add to framework", type="primary", icon=":material/account_tree:"):
            try:
                add_assembly_section(project_id, section_name, section_type, parent_id, section_description)
                st.session_state[section_form_version_key] += 1
                st.toast("Framework item added", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

if sections.empty:
    st.info("Add at least one main-spine section to begin the assembly framework.")
else:
    framework_records = {str(row["id"]): row.to_dict() for _, row in sections.iterrows()}
    framework_children: dict[str, list[str]] = {}
    for section_id, row in framework_records.items():
        parent_id = normalized_parent_id(row.get("parent_id"))
        framework_children.setdefault(parent_id, []).append(section_id)
    for child_ids in framework_children.values():
        child_ids.sort(key=lambda child_id: (int(framework_records[child_id]["sequence"]), framework_records[child_id]["name"]))

    framework_order: list[str] = []
    framework_depth: dict[str, int] = {}

    def add_framework_branch(section_id: str, depth: int) -> None:
        if section_id in framework_depth:
            return
        framework_depth[section_id] = depth
        framework_order.append(section_id)
        for child_id in framework_children.get(section_id, []):
            add_framework_branch(child_id, depth + 1)

    root_ids = [
        section_id for section_id, row in framework_records.items()
        if not normalized_parent_id(row.get("parent_id")) or row["section_type"] == "Main spine"
    ]
    root_ids.sort(key=lambda section_id: (int(framework_records[section_id]["sequence"]), framework_records[section_id]["name"]))
    for root_id in root_ids:
        add_framework_branch(root_id, 0)
    for section_id in framework_records:
        add_framework_branch(section_id, 0)

    framework = sections.set_index(sections["id"].astype(str), drop=False).loc[framework_order].reset_index(drop=True)
    framework["hierarchy"] = framework.apply(
        lambda row: (
            f"🟦  {row['name']}"
            if framework_depth[str(row["id"])] == 0
            else f"{' ' * framework_depth[str(row['id'])]}└─ 🟧  {row['name']}"
        ),
        axis=1,
    )
    framework["parent_assembly"] = framework["parent_id"].apply(
        lambda value: (
            "Product / main assembly"
            if not normalized_parent_id(value)
            else section_name_by_id.get(normalized_parent_id(value), normalized_parent_id(value))
        )
    )
    framework["order_actions"] = [[
        ":material/first_page: Move to start",
        ":material/arrow_upward: Move earlier",
        ":material/arrow_downward: Move later",
        ":material/last_page: Move to end",
    ]] * len(framework)
    full_framework = framework.copy()
    framework = filter_table(
        full_framework,
        key="assembly_framework_filters",
        dropdown_columns=["section_type", "parent_assembly", "active"],
        search_columns=["hierarchy", "name", "parent_assembly", "description"],
        labels={"section_type": "Framework type", "parent_assembly": "Parent assembly", "active": "Use status"},
        reset_widget_keys=["assembly_framework_editor"],
    )

    def handle_framework_order() -> None:
        click = st.session_state.get("framework_order_action")
        if not click or not 0 <= click["row"] < len(framework):
            return
        label = click["label"]
        action = next(
            (candidate for candidate in ["Move to start", "Move earlier", "Move later", "Move to end"] if candidate in label),
            None,
        )
        if action:
            section_id = str(framework.iloc[click["row"]]["id"])
            moved = reorder_assembly_section(project_id, section_id, action)
            if moved:
                st.toast(f"{framework.iloc[click['row']]['name']}: {action.lower()}", icon=":material/swap_vert:")

    framework_editor = st.data_editor(
        framework,
        key="assembly_framework_editor",
        hide_index=True,
        num_rows="fixed",
        height=300,
        disabled=["id", "hierarchy", "sequence", "created_at", "updated_at"],
        column_order=["hierarchy", "active", "sequence", "order_actions", "name", "section_type", "parent_assembly", "description"],
        column_config={
            "id": None,
            "project_id": None,
            "parent_id": None,
            "hierarchy": st.column_config.TextColumn(
                "Assembly hierarchy",
                pinned=True,
                width="large",
                help="Blue rows are main-spine sections. Orange indented rows are subassemblies grouped under their parent.",
            ),
            "active": st.column_config.CheckboxColumn("Use", help="Inactive framework items remain in history but are hidden from new part placement."),
            "sequence": st.column_config.NumberColumn("Order", format="%d", pinned=True, help="Managed automatically by the move actions."),
            "order_actions": st.column_config.ButtonColumn(
                "Move",
                pinned=True,
                type="secondary",
                on_click=handle_framework_order,
                key="framework_order_action",
            ),
            "name": st.column_config.TextColumn("Section / subassembly", required=True, pinned=True, width="large"),
            "section_type": st.column_config.SelectboxColumn("Type", options=["Main spine", "Subassembly"], required=True),
            "parent_assembly": st.column_config.SelectboxColumn(
                "Parent assembly",
                options=["Product / main assembly", *sections["name"].astype(str).tolist()],
                required=True,
                width="large",
            ),
            "description": st.column_config.TextColumn("Framework description", width="large"),
            "created_at": None,
            "updated_at": st.column_config.DatetimeColumn("Updated", format="MMM DD, YYYY HH:mm"),
        },
    )
    st.caption("🟦 Main-spine section · 🟧 Subassembly · indentation shows the parent-child relationship.")
    if st.button("Refresh assembly framework", type="primary", icon=":material/refresh:"):
        try:
            id_by_name = {name: section_id for section_id, name in section_name_by_id.items()}
            framework_to_save = merge_filtered_edits(full_framework, framework, framework_editor)
            framework_to_save["parent_id"] = framework_to_save["parent_assembly"].apply(
                lambda name: None if name == "Product / main assembly" else id_by_name.get(name)
            )
            count = update_assembly_section_rows(project_id, framework_to_save)
            st.toast(f"Saved {count} framework items", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

st.subheader("Fishbone framework")
if sections.empty:
    st.caption("The visual framework will appear after the first section is added.")
else:
    visible_sections = sections.loc[sections["active"].fillna(1).astype(bool)].copy()
    records = {str(row["id"]): row.to_dict() for _, row in visible_sections.iterrows()}
    children: dict[str, list[str]] = {}
    for section_id, row in records.items():
        parent_id = normalized_parent_id(row.get("parent_id"))
        children.setdefault(parent_id, []).append(section_id)
    for child_ids in children.values():
        child_ids.sort(key=lambda section_id: (int(records[section_id]["sequence"]), records[section_id]["name"]))

    main_ids = [section_id for section_id, row in records.items() if row["section_type"] == "Main spine"]
    main_ids.sort(key=lambda section_id: (int(records[section_id]["sequence"]), records[section_id]["name"]))
    coordinates: dict[str, tuple[float, float, int]] = {}

    def place_branch(section_id: str, x: float, depth: int) -> None:
        coordinates[section_id] = (x, -float(depth), depth)
        siblings = children.get(section_id, [])
        center = (len(siblings) - 1) / 2
        for index, child_id in enumerate(siblings):
            place_branch(child_id, x + (index - center) * 0.28, depth + 1)

    for index, section_id in enumerate(main_ids):
        place_branch(section_id, float(index), 0)

    node_rows = []
    edge_rows = []
    assignment_counts = assignments["section_id"].astype(str).value_counts().to_dict() if not assignments.empty else {}
    for section_id, (x, y, depth) in coordinates.items():
        row = records[section_id]
        node_rows.append({
            "id": section_id, "x": x, "y": y, "name": row["name"], "type": row["section_type"],
            "order": row["sequence"], "parts": assignment_counts.get(section_id, 0), "depth": depth,
        })
        parent_id = normalized_parent_id(row.get("parent_id"))
        if parent_id in coordinates:
            parent_x, parent_y, _ = coordinates[parent_id]
            edge_rows.append({"x": parent_x, "y": parent_y, "x2": x, "y2": y})
    for left_id, right_id in zip(main_ids, main_ids[1:]):
        left_x, left_y, _ = coordinates[left_id]
        right_x, right_y, _ = coordinates[right_id]
        edge_rows.append({"x": left_x, "y": left_y, "x2": right_x, "y2": right_y})

    if not node_rows:
        st.info("Activate at least one main-spine section to draw the framework.")
    else:
        nodes_chart = pd.DataFrame(node_rows)
        edges_chart = pd.DataFrame(edge_rows, columns=["x", "y", "x2", "y2"])
        base = alt.Chart(nodes_chart).encode(
            x=alt.X("x:Q", axis=None),
            y=alt.Y("y:Q", axis=None),
            tooltip=[
                alt.Tooltip("name:N", title="Assembly section"),
                alt.Tooltip("type:N", title="Type"),
                alt.Tooltip("order:Q", title="Order"),
                alt.Tooltip("parts:Q", title="Assigned parts"),
            ],
        )
        chart = base.mark_circle(size=420).encode(color=alt.Color("type:N", title="Framework type"))
        chart += base.mark_text(dy=-22, fontSize=12, fontWeight="bold").encode(text="name:N")
        if not edges_chart.empty:
            edges = alt.Chart(edges_chart).mark_rule(color="#8B98A5", strokeWidth=2).encode(
                x=alt.X("x:Q", axis=None), y=alt.Y("y:Q", axis=None), x2="x2:Q", y2="y2:Q"
            )
            chart = edges + chart
        st.altair_chart(chart.properties(height=max(240, 170 + int(nodes_chart["depth"].max()) * 80)))

st.header("2 · Place parts into the framework")
if parts.empty:
    st.info("Add or import parts on the Parts page before building the fishbone.")
elif active_sections.empty:
    st.info("Create and activate a framework section before placing parts.")
else:
    placed_by_part = assignments.set_index("part_id")["section_name"].to_dict() if not assignments.empty else {}
    part_pool = parts[["id", "part_number", "description", "quantity", "revision", "model_applicability"]].copy()
    part_pool["fishbone_section"] = part_pool["id"].map(placed_by_part).fillna("Not placed")
    pool_controls = st.container(horizontal=True)
    placement_filter = pool_controls.segmented_control("Show", ["Not placed", "Placed", "All"], default="Not placed")
    part_search = pool_controls.text_input("Search parts", placeholder="Part number or description")
    pool_model_options = sorted(
        {
            model
            for value in part_pool["model_applicability"]
            for model in split_filter_values(value)
            if model.casefold() not in {"all", "all models"}
        },
        key=str.casefold,
    )
    selected_pool_model = pool_controls.selectbox(
        "Model",
        options=[None, *pool_model_options],
        format_func=lambda value: "All" if value is None else value,
    )
    visible_parts = part_pool.copy()
    if placement_filter == "Not placed":
        visible_parts = visible_parts[visible_parts["fishbone_section"] == "Not placed"]
    elif placement_filter == "Placed":
        visible_parts = visible_parts[visible_parts["fishbone_section"] != "Not placed"]
    if part_search:
        searchable = visible_parts[["part_number", "description"]].fillna("").astype(str).agg(" ".join, axis=1)
        visible_parts = visible_parts[searchable.str.contains(part_search, case=False, regex=False)]
    if selected_pool_model is not None:
        visible_parts = visible_parts[
            visible_parts["model_applicability"].apply(
                lambda value: matches_filter_value(
                    value,
                    selected_pool_model,
                    universal_values=["All", "All models", ""],
                )
            )
        ]

    pool_key = f"parts_fishbone_pool_{project_id}"
    pool_signature_key = f"parts_fishbone_pool_signature_{project_id}"
    pool_signature = (
        placement_filter,
        part_search.strip().casefold(),
        selected_pool_model,
        tuple(visible_parts["id"].astype(str)),
    )
    if st.session_state.get(pool_signature_key) != pool_signature:
        st.session_state[pool_signature_key] = pool_signature
        st.session_state.pop(pool_key, None)

    pool_event = st.dataframe(
        visible_parts,
        key=pool_key,
        hide_index=True,
        height=330,
        on_select="rerun",
        selection_mode="multi-row",
        column_order=["part_number", "description", "quantity", "revision", "model_applicability", "fishbone_section"],
        column_config={
            "id": None,
            "part_number": st.column_config.TextColumn("Part number", pinned=True),
            "description": st.column_config.TextColumn("Description", width="large"),
            "quantity": st.column_config.NumberColumn("Qty", format="%d"),
            "model_applicability": st.column_config.TextColumn("Models", width="large"),
            "fishbone_section": st.column_config.TextColumn("Current section", width="large"),
        },
    )
    selected_rows = [
        int(row_index)
        for row_index in pool_event.selection.rows
        if 0 <= int(row_index) < len(visible_parts)
    ]
    selected_part_ids = visible_parts.iloc[selected_rows]["id"].astype(str).tolist() if selected_rows else []
    placement_row = st.container(horizontal=True, vertical_alignment="bottom")
    target_section_id = placement_row.selectbox(
        "Place selected parts in",
        options=active_sections["id"].astype(str).tolist(),
        format_func=lambda section_id: section_name_by_id.get(section_id, section_id),
    )
    if placement_row.button(
        "Place selected parts",
        type="primary",
        icon=":material/arrow_downward:",
        disabled=not selected_part_ids,
    ):
        try:
            count = assign_parts_to_section(project_id, selected_part_ids, target_section_id)
            st.toast(f"Placed {count} parts in {section_name_by_id[target_section_id]}", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

st.header("3 · Order assigned parts")
if assignments.empty:
    st.caption("Assigned parts will appear here for ordering within each framework section.")
else:
    full_assignment_editor = assignments.copy()
    full_assignment_editor["section"] = full_assignment_editor["section_id"].astype(str).map(section_name_by_id)
    assignment_editor = filter_table(
        full_assignment_editor,
        key="fishbone_assignment_filters",
        dropdown_columns=["section", "revision", "model_applicability"],
        search_columns=["section", "part_number", "description", "revision", "model_applicability", "notes"],
        labels={"section": "Assembly section", "model_applicability": "Models"},
        reset_widget_keys=["fishbone_assignment_editor"],
        multi_value_columns=["model_applicability"],
        universal_values={"model_applicability": ["All", "All models", ""]},
    )
    edited_assignments = st.data_editor(
        assignment_editor,
        key="fishbone_assignment_editor",
        hide_index=True,
        num_rows="delete",
        height=430,
        disabled=["id", "part_id", "part_number", "description", "revision", "model_applicability", "updated_at"],
        column_order=["section", "sequence", "part_number", "description", "quantity", "revision", "model_applicability", "notes"],
        column_config={
            "id": None,
            "project_id": None,
            "part_id": None,
            "section_id": None,
            "section_name": None,
            "section": st.column_config.SelectboxColumn(
                "Assembly section", options=active_sections["name"].astype(str).tolist(), required=True, pinned=True, width="large"
            ),
            "sequence": st.column_config.NumberColumn("Order in section", min_value=1, step=1, format="%d", pinned=True),
            "part_number": st.column_config.TextColumn("Part number", pinned=True),
            "description": st.column_config.TextColumn("Description", width="large"),
            "quantity": st.column_config.NumberColumn("Qty", min_value=0, step=1, format="%d"),
            "model_applicability": st.column_config.TextColumn("Models", width="large"),
            "notes": st.column_config.TextColumn("IE notes", width="large"),
            "updated_at": None,
        },
    )
    st.caption("Delete a row here to return that part to the unplaced pool; the part remains in the Parts table.")
    if st.button("Refresh part placement and order", type="primary", icon=":material/refresh:"):
        try:
            section_id_by_name = {name: section_id for section_id, name in section_name_by_id.items()}
            assignments_to_save = merge_filtered_edits(
                full_assignment_editor, assignment_editor, edited_assignments
            )
            assignments_to_save["section_id"] = assignments_to_save["section"].map(section_id_by_name)
            count = replace_fishbone_part_assignments(project_id, assignments_to_save)
            st.toast(f"Saved {count} fishbone part assignments", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
