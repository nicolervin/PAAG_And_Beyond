import pandas as pd
import streamlit as st

from utils.store import (
    active_part_ids,
    add_assembly_section,
    assembly_sections,
    assign_parts_to_section,
    delete_fishbone_part_assignments,
    fishbone_assignment_snapshot,
    fishbone_part_assignments,
    fishbone_plan_snapshot,
    part_feature_rules,
    project_models,
    project_table,
    record_audit_event,
    reorder_assembly_section,
    replace_fishbone_part_assignments,
    restore_fishbone_assignment_snapshot,
    restore_fishbone_plan_snapshot,
    save_fishbone_plan,
    update_assembly_section_rows,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    has_unsaved_table_changes,
    matches_filter_value,
    merge_filtered_edits,
    request_table_editor_reset,
    split_filter_values,
)
from utils.fishbone_visual import interactive_fishbone, part_thumbnail
from utils.table_ui import (
    native_selected_rows,
    table_has_unsaved_changes,
)


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
st.title("Parts to assembly fishbone")
st.caption("Build the assembly framework first, then place approved Parts-table content into its sections and subassemblies.")
if not project_id or not scenario_id:
    st.stop()
pool_editor_key = f"parts_fishbone_pool_v3_{project_id}_{scenario_id}"
assignment_editor_key = f"fishbone_assignment_editor_{scenario_id}"
for editor_key in (
    "assembly_framework_editor",
    assignment_editor_key,
    pool_editor_key,
):
    apply_pending_table_editor_reset(editor_key)

scenario_active_part_ids = active_part_ids(project_id, scenario_id)
parts = project_table("parts", project_id, "part_number")
if not parts.empty:
    parts = parts.loc[parts["id"].astype(str).isin(scenario_active_part_ids)].copy()
sections = assembly_sections(project_id)
all_assignments = fishbone_part_assignments(project_id)
if all_assignments.empty:
    assignments = all_assignments.copy()
    inactive_assignments = all_assignments.copy()
else:
    assignment_is_active = all_assignments["part_id"].astype(str).isin(
        scenario_active_part_ids
    )
    assignments = all_assignments.loc[assignment_is_active].copy()
    inactive_assignments = all_assignments.loc[~assignment_is_active].copy()
models = project_models(project_id)
feature_rules = part_feature_rules(project_id)
feature_labels_by_part: dict[str, list[str]] = {}
if not feature_rules.empty:
    for part_id, part_rules in feature_rules.groupby("part_id", sort=False):
        feature_labels_by_part[str(part_id)] = [
            f"{row['category']} · {row['feature_name']} = {row['value']}"
            for _, row in part_rules.iterrows()
        ]
framework_undo_key = f"fishbone_framework_undo_{project_id}"
assignment_undo_key = f"fishbone_assignment_undo_{project_id}"
pending_use_key = f"fishbone_pending_additional_uses_{project_id}"
current_plan_snapshot = fishbone_plan_snapshot(project_id)
current_assignment_undo = {
    "assignments": fishbone_assignment_snapshot(project_id),
    "pending_use_ids": list(st.session_state.get(pending_use_key, [])),
}
familiar_model_names = {
    str(row["model_number"]).strip(): str(row["display_name"]).strip()
    for _, row in models.iterrows()
    if str(row["display_name"]).strip()
}


def familiar_models(value) -> str:
    model_numbers = split_filter_values(value)
    if not model_numbers or any(model.casefold() in {"all", "all models"} for model in model_numbers):
        return "All models"
    return ", ".join(familiar_model_names.get(model, "Familiar name not defined") for model in model_numbers)


def feature_applicability(part_id, legacy_value) -> str:
    labels = feature_labels_by_part.get(str(part_id), [])
    if labels:
        return "; ".join(labels)
    if str(legacy_value or "").strip().casefold() in {"all", "all models"}:
        return "All models"
    return "Needs feature tagging"


def normalized_parent_id(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


metrics = st.columns(4)
metrics[0].metric("Parts available", len(parts), border=True)
metrics[1].metric("Framework sections", len(sections), border=True)
placed_catalog_parts = assignments["part_id"].nunique() if not assignments.empty else 0
metrics[2].metric("Part uses placed", len(assignments), border=True)
metrics[3].metric("Parts not yet placed", max(0, len(parts) - placed_catalog_parts), border=True)

st.subheader("Fishbone framework")
fishbone_visual_slot = st.empty()

with st.expander(
    "1 · Build the assembly framework",
    icon=":material/account_tree:",
    expanded=True,
):
    _, section_1_warning, section_1_undo, section_1_action = st.columns(
        [4, 0.8, 0.7, 1], vertical_alignment="center"
    )
    framework_has_unsaved = table_has_unsaved_changes(
        "assembly_framework_editor", native_row_selection=True
    )
    if framework_has_unsaved:
        section_1_warning.markdown(":orange[:material/warning: **Unsaved changes**]")
    undo_framework = section_1_undo.button(
        "Undo",
        icon=":material/undo:",
        disabled=framework_undo_key not in st.session_state and not framework_has_unsaved,
        help=(
            "Discard the current unsaved framework edits."
            if framework_has_unsaved
            else "Undo the last saved framework change in this browser session."
        ),
        key="undo_assembly_framework",
    )
    refresh_framework = section_1_action.button(
        "Refresh assembly framework",
        type="primary",
        icon=":material/refresh:",
        key="refresh_assembly_framework_top",
    )
    if undo_framework:
        if framework_has_unsaved:
            st.session_state.pop("assembly_framework_editor", None)
            st.toast("Discarded the unsaved framework edits", icon=":material/undo:")
        else:
            restore_fishbone_plan_snapshot(project_id, st.session_state.pop(framework_undo_key))
            st.session_state.pop(assignment_undo_key, None)
            st.session_state.pop("assembly_framework_editor", None)
            st.session_state.pop(assignment_editor_key, None)
            st.toast("Undid the last assembly framework change", icon=":material/undo:")
        st.rerun()
    st.caption("Main-spine sections establish product assembly order. Subassemblies—such as Wheel Subassembly—must attach to a parent section or subassembly.")

    active_sections = sections.loc[sections["active"].fillna(1).astype(bool)].copy() if not sections.empty else sections
    section_name_by_id = dict(zip(sections["id"].astype(str), sections["name"].astype(str))) if not sections.empty else {}
    parent_options = active_sections["id"].astype(str).tolist() if not active_sections.empty else []

    with st.container(border=True):
        st.subheader("Add a section or subassembly")
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
                    st.session_state[framework_undo_key] = current_plan_snapshot
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
                    st.session_state[framework_undo_key] = current_plan_snapshot
                    st.toast(f"{framework.iloc[click['row']]['name']}: {action.lower()}", icon=":material/swap_vert:")

        framework_editor = st.data_editor(
            framework,
            key="assembly_framework_editor",
            hide_index=True,
            num_rows="delete",
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
        selected_framework_rows = native_selected_rows(
            framework, editor_key="assembly_framework_editor"
        )
        st.caption("🟦 Main-spine section · 🟧 Subassembly · indentation shows the parent-child relationship.")
        id_by_name = {name: section_id for section_id, name in section_name_by_id.items()}
        framework_to_save = merge_filtered_edits(full_framework, framework, framework_editor)
        framework_to_save["parent_id"] = framework_to_save["parent_assembly"].apply(
            lambda name: None if name == "Product / main assembly" else id_by_name.get(name)
        )
        if refresh_framework:
            try:
                if not selected_framework_rows.empty:
                    raise ValueError("Clear selected rows before saving the assembly framework.")
                count = update_assembly_section_rows(project_id, framework_to_save)
                st.session_state[framework_undo_key] = current_plan_snapshot
                request_table_editor_reset("assembly_framework_editor")
                st.toast(f"Saved {count} framework items", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

if sections.empty:
    fishbone_visual_slot.caption("The visual framework will appear after the first section is added.")
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

    def place_fin(section_id: str, x: float, y: float, depth: int, side: int) -> None:
        """Continue nested subassemblies outward on a diagonal fin."""
        coordinates[section_id] = (x, y, depth)
        for index, child_id in enumerate(children.get(section_id, [])):
            place_fin(
                child_id,
                x - 0.48 - index * 0.10,
                y + side * (0.88 + index * 0.16),
                depth + 1,
                side,
            )

    for main_index, section_id in enumerate(main_ids):
        coordinates[section_id] = (float(main_index), 0.0, 0)
        direct_subassemblies = children.get(section_id, [])
        for branch_index, child_id in enumerate(direct_subassemblies):
            side = -1 if (main_index + branch_index) % 2 == 0 else 1
            lane = branch_index // 2
            place_fin(
                child_id,
                float(main_index) - 0.48 - lane * 0.10,
                side * (1.0 + lane * 0.18),
                1,
                side,
            )

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
            edge_rows.append({"from": parent_id, "to": section_id})
    for left_id, right_id in zip(main_ids, main_ids[1:]):
        edge_rows.append({"from": left_id, "to": right_id})

    if not node_rows:
        fishbone_visual_slot.info("Activate at least one main-spine section to draw the framework.")
    else:
        image_path_by_part = (
            parts.set_index(parts["id"].astype(str))["image_path"].to_dict()
            if not parts.empty and "image_path" in parts.columns
            else {}
        )
        visual_feature_options = sorted(
            {label for labels in feature_labels_by_part.values() for label in labels}, key=str.casefold
        )
        with fishbone_visual_slot.container():
            visual_controls = st.container(horizontal=True, vertical_alignment="bottom")
            selected_visual_features = visual_controls.multiselect(
                    "View fishbone for features",
                    options=visual_feature_options,
                    placeholder="All feature configurations · complete fishbone",
                    key=f"fishbone_visual_features_{project_id}",
                    help="Feature views include parts tagged to any selected choice plus parts tagged All models.",
                )
            if visual_controls.button(
                "Edit parts & photos",
                icon=":material/edit:",
                key="fishbone_edit_parts_visual",
                help="Open the Parts page to edit part details or add more photos.",
            ):
                st.switch_page("app_pages/parts.py")
            fishbone_refresh_key = f"fishbone_refresh_version_{project_id}"
            st.session_state.setdefault(fishbone_refresh_key, 0)
            if visual_controls.button(
                "Save all changes & refresh",
                icon=":material/refresh:",
                type="primary",
                key="fishbone_refresh_visual",
                help="Save edits in Sections 1 and 3, then rebuild the fishbone. Section 2 selections are preserved.",
            ):
                st.session_state[f"fishbone_save_all_{project_id}"] = True
            visual_parts = []
            for _, assignment in assignments.iterrows():
                part_id = str(assignment["part_id"])
                section_id = str(assignment["section_id"])
                if section_id not in coordinates:
                    continue
                applicability_label = feature_applicability(part_id, assignment["model_applicability"])
                if (
                    selected_visual_features
                    and applicability_label != "All models"
                    and not set(selected_visual_features) & set(feature_labels_by_part.get(part_id, []))
                ):
                    continue
                visual_parts.append({
                    "id": str(assignment["id"]),
                    "part_id": part_id,
                    "section_id": section_id,
                    "section_name": str(assignment["section_name"]),
                    "part_number": str(assignment["part_number"] or ""),
                    "description": str(assignment["description"] or ""),
                    "use_description": str(assignment["use_description"] or ""),
                    "quantity": int(assignment["quantity"] or 0),
                    "models": applicability_label,
                    "image": part_thumbnail(image_path_by_part.get(part_id, "")),
                })
            visible_counts: dict[str, int] = {}
            for part in visual_parts:
                visible_counts[part["section_id"]] = visible_counts.get(part["section_id"], 0) + 1
            for node in node_rows:
                node["parts"] = visible_counts.get(node["id"], 0)
            interactive_fishbone(
                node_rows,
                edge_rows,
                visual_parts,
                key=f"interactive_fishbone_{project_id}_{st.session_state[fishbone_refresh_key]}",
            )

section_2_title, section_2_undo = st.columns([5, 0.7], vertical_alignment="center")
section_2_title.header("2 · Place parts into the framework")
placement_has_unsaved = has_unsaved_table_changes(pool_editor_key)
undo_placement = section_2_undo.button(
    "Undo",
    icon=":material/undo:",
    disabled=assignment_undo_key not in st.session_state and not placement_has_unsaved,
    help=(
        "Discard the current unsaved selections or quantities."
        if placement_has_unsaved
        else "Undo the last part placement or additional-use staging."
    ),
    key="undo_part_placement",
)
if undo_placement:
    if placement_has_unsaved:
        st.session_state.pop(pool_editor_key, None)
        st.toast("Discarded the unsaved placement table edits", icon=":material/undo:")
    else:
        undo_state = st.session_state.pop(assignment_undo_key)
        restore_fishbone_assignment_snapshot(project_id, undo_state["assignments"])
        st.session_state[pending_use_key] = undo_state.get("pending_use_ids", [])
        st.session_state.pop(pool_editor_key, None)
        st.session_state.pop(assignment_editor_key, None)
        st.toast("Undid the last part placement change", icon=":material/undo:")
    st.rerun()
if parts.empty:
    st.info("Add or import parts on the Parts page before building the fishbone.")
elif active_sections.empty:
    st.info("Create and activate a framework section before placing parts.")
else:
    pending_use_ids = {
        str(part_id) for part_id in st.session_state.get(pending_use_key, [])
        if str(part_id) in set(parts["id"].astype(str))
    }
    placed_by_part = {}
    if not assignments.empty:
        for part_id, uses in assignments.groupby("part_id", sort=False):
            section_names = list(dict.fromkeys(uses["section_name"].astype(str)))
            section_summary = ", ".join(section_names)
            placed_by_part[str(part_id)] = f"{len(uses)} use{'s' if len(uses) != 1 else ''} · {section_summary}"
    part_pool = parts[["id", "part_number", "description", "quantity", "revision", "model_applicability"]].copy()
    # Quantity belongs to each fishbone use, not the master catalog part.
    part_pool["quantity"] = 1
    part_pool["feature_applicability"] = part_pool.apply(
        lambda row: feature_applicability(row["id"], row["model_applicability"]), axis=1
    )
    part_pool["fishbone_section"] = part_pool["id"].map(placed_by_part).fillna("Not placed")
    part_pool.loc[
        part_pool["id"].astype(str).isin(pending_use_ids), "fishbone_section"
    ] = "Ready for another use"
    pool_controls = st.container(horizontal=True)
    placement_filter_key = f"fishbone_placement_filters_{project_id}"
    placement_filters = pool_controls.multiselect(
        "Show",
        ["Not placed", "Ready for another use", "Placed"],
        default=["Not placed"],
        placeholder="All placement states",
        key=placement_filter_key,
    )
    part_search = pool_controls.text_input("Search parts", placeholder="Part number or part name")
    pool_feature_options = sorted(
        {label for labels in feature_labels_by_part.values() for label in labels}, key=str.casefold
    )
    selected_pool_features = pool_controls.multiselect(
        "Features",
        options=pool_feature_options,
        placeholder="All feature configurations",
        key=f"fishbone_pool_features_{project_id}",
    )
    visible_parts = part_pool.copy()
    if placement_filters:
        placement_state = visible_parts["fishbone_section"].where(
            visible_parts["fishbone_section"].isin(["Not placed", "Ready for another use"]),
            "Placed",
        )
        visible_parts = visible_parts[placement_state.isin(placement_filters)]
    if part_search:
        searchable = visible_parts[["part_number", "description"]].fillna("").astype(str).agg(" ".join, axis=1)
        visible_parts = visible_parts[searchable.str.contains(part_search, case=False, regex=False)]
    if selected_pool_features:
        visible_parts = visible_parts[
            visible_parts.apply(
                lambda row: row["feature_applicability"] == "All models"
                or bool(
                    set(selected_pool_features)
                    & set(feature_labels_by_part.get(str(row["id"]), []))
                ),
                axis=1,
            )
        ]

    pool_key = pool_editor_key
    pool_signature_key = f"parts_fishbone_pool_signature_{project_id}"
    pool_signature = (
        tuple(placement_filters),
        part_search.strip().casefold(),
        tuple(selected_pool_features),
        tuple(visible_parts["id"].astype(str)),
    )
    if st.session_state.get(pool_signature_key) != pool_signature:
        st.session_state[pool_signature_key] = pool_signature
        st.session_state.pop(pool_key, None)

    visible_parts = visible_parts.copy()
    visible_parts["place"] = False
    visible_parts["edit_part"] = ":material/edit: Edit part"
    visible_parts["models_familiar"] = visible_parts["feature_applicability"]

    def open_pool_part() -> None:
        click = st.session_state.get("fishbone_pool_edit_part")
        if not click or not 0 <= click["row"] < len(visible_parts):
            return
        row = visible_parts.iloc[click["row"]]
        st.session_state[f"parts_selected_id_{project_id}"] = str(row["id"])
        st.session_state["part_catalog_filters_keyword"] = str(row["part_number"])
        st.session_state["part_catalog_filters_source"] = []
        st.session_state["part_catalog_filters_revision"] = []
        st.session_state["part_catalog_filters_model_applicability"] = []
        st.session_state[f"fishbone_open_pool_part_{project_id}"] = True

    edited_pool = st.data_editor(
        visible_parts,
        key=pool_key,
        hide_index=True,
        height=330,
        num_rows="delete",
        disabled=["id", "part_number", "description", "revision", "model_applicability", "models_familiar", "fishbone_section"],
        column_order=["place", "edit_part", "part_number", "description", "quantity", "revision", "models_familiar", "fishbone_section"],
        column_config={
            "id": None,
            "place": st.column_config.CheckboxColumn(
                "Place?",
                pinned=True,
                help="Check one or more rows to enable the appropriate placement button below.",
            ),
            "edit_part": st.column_config.ButtonColumn(
                "Select",
                pinned=True,
                type="tertiary",
                on_click=open_pool_part,
                key="fishbone_pool_edit_part",
                help="Open this exact catalog part on the Parts page to edit its models, details, and photos.",
            ),
            "part_number": st.column_config.TextColumn("Part number", pinned=True),
            "description": st.column_config.TextColumn("Part Name", width="large"),
            "quantity": st.column_config.NumberColumn(
                "Qty for this use", min_value=0, step=1, format="%d",
                help="This quantity applies to the fishbone occurrence being placed; it does not change the master Parts record.",
            ),
            "model_applicability": None,
            "models_familiar": st.column_config.TextColumn("Feature applicability", width="medium"),
            "fishbone_section": st.column_config.TextColumn("Fishbone uses", width="large"),
        },
    )
    if st.session_state.pop(f"fishbone_open_pool_part_{project_id}", False):
        st.switch_page("app_pages/parts.py")
    selected_parts = edited_pool.loc[edited_pool["place"].fillna(False).astype(bool)].copy()
    selected_part_ids = selected_parts["id"].astype(str).tolist()
    selected_quantities = {
        str(row["id"]): int(row["quantity"])
        for _, row in selected_parts.iterrows()
    }
    placed_part_ids = set(assignments["part_id"].astype(str)) if not assignments.empty else set()
    selected_unplaced_ids = [part_id for part_id in selected_part_ids if part_id not in placed_part_ids]
    selected_additional_use_ids = [part_id for part_id in selected_part_ids if part_id in pending_use_ids]
    placement_row = st.container(horizontal=True, vertical_alignment="bottom")
    target_section_id = placement_row.selectbox(
        "Place selected parts in",
        options=active_sections["id"].astype(str).tolist(),
        format_func=lambda section_id: section_name_by_id.get(section_id, section_id),
    )
    use_description_key = f"fishbone_new_use_description_{project_id}"
    clear_use_description_key = f"fishbone_clear_use_description_{project_id}"
    if st.session_state.pop(clear_use_description_key, False):
        st.session_state.pop(use_description_key, None)
    use_description = placement_row.text_input(
        "Use / installation location",
        placeholder="Example: Door hinge — upper left",
        help="Describe this occurrence so repeated uses of the same part are easy to distinguish.",
        key=use_description_key,
    )
    if placement_row.button(
        "Place selected parts",
        type="primary",
        icon=":material/arrow_downward:",
        disabled=not (selected_unplaced_ids or selected_additional_use_ids),
        help="Places first-time parts and staged additional uses with the correct behavior automatically.",
    ):
        try:
            st.session_state[assignment_undo_key] = current_assignment_undo
            count = 0
            if selected_unplaced_ids:
                count += assign_parts_to_section(
                    project_id,
                    selected_unplaced_ids,
                    target_section_id,
                    use_description,
                    quantities_by_part={part_id: selected_quantities[part_id] for part_id in selected_unplaced_ids},
                )
            if selected_additional_use_ids:
                count += assign_parts_to_section(
                    project_id,
                    selected_additional_use_ids,
                    target_section_id,
                    use_description,
                    allow_additional_use=True,
                    quantities_by_part={part_id: selected_quantities[part_id] for part_id in selected_additional_use_ids},
                )
            pending_use_ids.difference_update(selected_additional_use_ids)
            st.session_state[pending_use_key] = sorted(pending_use_ids)
            request_table_editor_reset(pool_editor_key)
            st.toast(f"Placed {count} part uses in {section_name_by_id[target_section_id]}", icon=":material/check_circle:")
            st.session_state[clear_use_description_key] = True
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    st.caption(
        "Place selected parts automatically handles both first-time parts and additional uses staged from Section 3."
    )

section_3_title, section_3_warning, section_3_undo, section_3_action = st.columns(
    [4, 0.8, 0.7, 1], vertical_alignment="center"
)
section_3_title.header("3 · Order assigned parts")
assignments_have_unsaved = table_has_unsaved_changes(
    assignment_editor_key, native_row_selection=True
)
if assignments_have_unsaved:
    section_3_warning.markdown(":orange[:material/warning: **Unsaved changes**]")
undo_assigned_parts = section_3_undo.button(
    "Undo",
    icon=":material/undo:",
    disabled=assignment_undo_key not in st.session_state and not assignments_have_unsaved,
    help=(
        "Discard the current unsaved assigned-parts edits."
        if assignments_have_unsaved
        else "Undo the last saved assigned-parts change."
    ),
    key="undo_assigned_parts",
)
refresh_part_placement = section_3_action.button(
    "Refresh part placement and order",
    type="primary",
    icon=":material/refresh:",
    key="refresh_part_placement_top",
)
if undo_assigned_parts:
    if assignments_have_unsaved:
        st.session_state.pop(assignment_editor_key, None)
        st.toast("Discarded the unsaved assigned-parts edits", icon=":material/undo:")
    else:
        undo_state = st.session_state.pop(assignment_undo_key)
        restore_fishbone_assignment_snapshot(project_id, undo_state["assignments"])
        st.session_state[pending_use_key] = undo_state.get("pending_use_ids", [])
        st.session_state.pop(assignment_editor_key, None)
        st.toast("Undid the last assigned-parts change", icon=":material/undo:")
    st.rerun()
selected_assignment_rows = assignments.iloc[0:0].copy()
if assignments.empty:
    st.caption("Assigned parts will appear here for ordering within each framework section.")
else:
    full_assignment_editor = assignments.copy()
    full_assignment_editor["section"] = full_assignment_editor["section_id"].astype(str).map(section_name_by_id)
    full_assignment_editor["model_applicability"] = full_assignment_editor.apply(
        lambda row: feature_applicability(row["part_id"], row["model_applicability"]), axis=1
    )
    assignment_editor = filter_table(
        full_assignment_editor,
        key="fishbone_assignment_filters",
        dropdown_columns=["section", "revision", "model_applicability"],
        search_columns=["section", "part_number", "description", "use_description", "revision", "model_applicability", "notes"],
        labels={"section": "Assembly section", "model_applicability": "Feature applicability"},
        reset_widget_keys=[assignment_editor_key],
        multi_value_columns=["model_applicability"],
        universal_values={"model_applicability": ["All", "All models", ""]},
    )
    assignment_editor["edit_part"] = ":material/edit: Edit part"
    assignment_editor["add_use"] = ":material/content_copy: Add use"

    def open_assigned_part() -> None:
        click = st.session_state.get("fishbone_assignment_edit_part")
        if not click or not 0 <= click["row"] < len(assignment_editor):
            return
        part_id = str(assignment_editor.iloc[click["row"]]["part_id"])
        part_number = str(assignment_editor.iloc[click["row"]]["part_number"])
        st.session_state[f"parts_selected_id_{project_id}"] = part_id
        st.session_state["part_catalog_filters_keyword"] = part_number
        st.session_state["part_catalog_filters_source"] = []
        st.session_state["part_catalog_filters_revision"] = []
        st.session_state["part_catalog_filters_model_applicability"] = []
        # Navigation triggers a rerun, so defer it until the callback has finished.
        st.session_state[f"fishbone_open_part_{project_id}"] = True

    def add_assigned_part_use() -> None:
        click = st.session_state.get("fishbone_assignment_add_use")
        if not click or not 0 <= click["row"] < len(assignment_editor):
            return
        row = assignment_editor.iloc[click["row"]]
        staged_ids = set(st.session_state.get(f"fishbone_pending_additional_uses_{project_id}", []))
        staged_ids.add(str(row["part_id"]))
        st.session_state[assignment_undo_key] = current_assignment_undo
        st.session_state[f"fishbone_pending_additional_uses_{project_id}"] = sorted(staged_ids)
        st.session_state[f"fishbone_placement_filters_{project_id}"] = ["Ready for another use"]
        st.toast("Part returned to Section 2 and is ready to place again.", icon=":material/arrow_upward:")

    edited_assignments = st.data_editor(
        assignment_editor,
        key=assignment_editor_key,
        hide_index=True,
        num_rows="delete",
        height=430,
        disabled=["id", "part_id", "part_number", "description", "revision", "model_applicability", "updated_at"],
        column_order=[
            "edit_part", "add_use", "section", "part_number", "description",
            "quantity", "model_applicability", "revision", "use_description", "notes", "sequence",
        ],
        column_config={
            "id": None,
            "project_id": None,
            "part_id": None,
            "section_id": None,
            "section_name": None,
            "edit_part": st.column_config.ButtonColumn(
                "Select",
                pinned=True,
                type="tertiary",
                on_click=open_assigned_part,
                key="fishbone_assignment_edit_part",
                help="Open this exact part on the Parts page to edit its catalog details and photos.",
            ),
            "add_use": st.column_config.ButtonColumn(
                "Another use",
                pinned=True,
                type="tertiary",
                on_click=add_assigned_part_use,
                key="fishbone_assignment_add_use",
                help="Return this catalog part to Section 2 so its additional use can be placed deliberately.",
            ),
            "section": st.column_config.SelectboxColumn(
                "Assembly section",
                options=active_sections["name"].astype(str).tolist(),
                required=True,
                pinned=True,
                width="medium",
            ),
            "sequence": st.column_config.NumberColumn("Order in section", min_value=1, step=1, format="%d"),
            "part_number": st.column_config.TextColumn("Part number", pinned=True),
            "description": st.column_config.TextColumn("Part Name", width="medium", pinned=True),
            "use_description": st.column_config.TextColumn(
                "Use / installation location",
                width="large",
                help="What this occurrence does or where it is installed.",
            ),
            "quantity": st.column_config.NumberColumn("Qty", min_value=0, step=1, format="%d"),
            "model_applicability": st.column_config.TextColumn("Feature applicability", width="medium"),
            "notes": st.column_config.TextColumn("IE notes", width="large"),
            "updated_at": None,
        },
    )
    if st.session_state.pop(f"fishbone_open_part_{project_id}", False):
        st.switch_page("app_pages/parts.py")
    selected_assignment_rows = native_selected_rows(
        assignment_editor, editor_key=assignment_editor_key
    )
    request_assignment_delete = False
    if request_assignment_delete:
        if table_has_unsaved_changes(
            assignment_editor_key, native_row_selection=True
        ):
            st.warning("Save or undo other assigned-part edits before deleting selected uses.")
        else:
            st.session_state[f"fishbone_assignments_pending_delete_{project_id}"] = (
                selected_assignment_rows["id"].astype(str).tolist()
            )

    @st.dialog("Delete selected fishbone uses?")
    def confirm_assignment_delete() -> None:
        pending_key = f"fishbone_assignments_pending_delete_{project_id}"
        pending_ids = st.session_state.get(pending_key, [])
        st.warning(
            f"Delete {len(pending_ids)} selected Fishbone use(s)? Master Parts records and other "
            "uses will remain."
        )
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_fishbone_assignment_delete_{project_id}"):
            st.session_state.pop(pending_key, None)
            st.rerun()
        if actions.button(
            "Delete uses",
            type="primary",
            icon=":material/delete:",
            key=f"destructive_confirm_fishbone_assignment_delete_{project_id}",
        ):
            try:
                count = delete_fishbone_part_assignments(project_id, pending_ids)
                st.session_state[assignment_undo_key] = current_assignment_undo
                record_audit_event(
                    project_id,
                    "Fishbone part assignments",
                    "Bulk delete",
                    count,
                    st.session_state.get("current_editor", ""),
                    {"assignment_ids": pending_ids},
                )
                st.session_state.pop(pending_key, None)
                request_table_editor_reset(assignment_editor_key)
                st.toast(f"Deleted {count} selected Fishbone uses", icon=":material/delete:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    st.session_state.pop(f"fishbone_assignments_pending_delete_{project_id}", None)

    st.caption(
        "Each row is one use of a catalog part. Edit its location, Qty, section, or order, then select Save all changes & refresh above the fishbone. "
        "Another use stages the part in Section 2 instead of creating a duplicate here."
    )
    assignments_to_save = merge_filtered_edits(
        full_assignment_editor, assignment_editor, edited_assignments
    )
    assignments_to_save = assignments_to_save.drop(
        columns=["edit_part", "add_use"], errors="ignore"
    )
    section_id_by_name = {name: section_id for section_id, name in section_name_by_id.items()}
    assignments_to_save["section_id"] = assignments_to_save["section"].map(section_id_by_name)
    if not inactive_assignments.empty:
        assignments_to_save = pd.concat(
            [assignments_to_save, inactive_assignments], ignore_index=True, sort=False
        )
    if refresh_part_placement:
        try:
            if not selected_assignment_rows.empty:
                raise ValueError("Clear selected rows before saving assigned-part edits.")
            count = replace_fishbone_part_assignments(project_id, assignments_to_save)
            st.session_state[assignment_undo_key] = current_assignment_undo
            request_table_editor_reset(assignment_editor_key)
            st.toast(f"Saved {count} fishbone part assignments", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

if st.session_state.pop(f"fishbone_save_all_{project_id}", False):
    try:
        if not sections.empty and not selected_framework_rows.empty:
            raise ValueError("Clear selected framework rows before saving the Fishbone plan.")
        if not selected_assignment_rows.empty:
            raise ValueError("Clear selected assigned-part rows before saving the Fishbone plan.")
        framework_count, assignment_count = save_fishbone_plan(
            project_id,
            framework_to_save if not sections.empty else None,
            assignments_to_save if not assignments.empty else None,
        )
        st.session_state[framework_undo_key] = current_plan_snapshot
        st.session_state[assignment_undo_key] = current_assignment_undo
        request_table_editor_reset("assembly_framework_editor")
        request_table_editor_reset(assignment_editor_key)
        st.session_state[f"fishbone_refresh_version_{project_id}"] = (
            st.session_state.get(f"fishbone_refresh_version_{project_id}", 0) + 1
        )
        st.toast(
            f"Saved {framework_count} framework items and {assignment_count} part uses",
            icon=":material/check_circle:",
        )
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))
