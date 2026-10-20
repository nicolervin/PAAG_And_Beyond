import pandas as pd
import streamlit as st

from utils.fishbone_ui import section_breadcrumb_labels
from utils.store import (
    active_part_ids,
    add_assembly_section,
    assemblies_for_section,
    assembly_section_connections,
    assembly_section_delete_impact,
    assembly_section_delete_target_validation,
    assembly_section_walk_order,
    assign_parts_to_section,
    audit_history,
    delete_assembly_section_connection,
    delete_assembly_sections,
    delete_fishbone_part_assignment,
    delete_fishbone_part_assignments,
    fishbone_assignment_snapshot,
    fishbone_assignment_assembly_impact,
    fishbone_part_assignments,
    fishbone_plan_snapshot,
    part_feature_rules,
    pits_bom_model_tree,
    project_models,
    project_table,
    record_audit_event,
    reorder_assembly_section,
    replace_fishbone_part_assignments,
    restore_fishbone_assignment_snapshot,
    restore_fishbone_plan_snapshot,
    save_assembly_section_connection,
    save_fishbone_canvas_draft,
    save_fishbone_canvas_positions,
    update_assembly_section_rows,
    yamazumi_area_creation_summary,
)
from utils.scope_ui import page_title_with_scope
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
    decimal_values_equal,
    editable_table_footer,
    native_selected_rows,
    stage_native_delete_confirmation,
    selectable_dataframe,
    table_has_unsaved_changes,
)


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
page_title_with_scope(
    "Parts to fishbone",
    scope="scenario-aware",
    help_text=(
        "The Fishbone framework is shared across every scenario. Which parts are visible and "
        "available on this page depends on the currently selected scenario."
    ),
)
st.caption("Build the Fishbone framework first, then place approved Parts Catalog content into its sections and subassemblies.")
if not project_id or not scenario_id:
    st.stop()
pool_editor_key = f"parts_fishbone_pool_v3_{project_id}_{scenario_id}"
assignment_editor_key = f"fishbone_assignment_editor_{scenario_id}"
framework_editor_key = apply_pending_table_editor_reset("assembly_framework_editor")
assignment_editor_key = apply_pending_table_editor_reset(assignment_editor_key)
pool_editor_key = apply_pending_table_editor_reset(pool_editor_key)

scenario_active_part_ids = active_part_ids(project_id, scenario_id)
parts = project_table("parts", project_id, "part_number")
if not parts.empty:
    parts = parts.loc[parts["id"].astype(str).isin(scenario_active_part_ids)].copy()
sections = assembly_section_walk_order(project_id)
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
active_sections = sections.loc[sections["active"].fillna(1).astype(bool)].copy() if not sections.empty else sections
section_name_by_id = dict(zip(sections["id"].astype(str), sections["name"].astype(str))) if not sections.empty else {}
section_option_labels = section_breadcrumb_labels(sections)
parent_options = active_sections["id"].astype(str).tolist() if not active_sections.empty else []
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
    return ", ".join(familiar_model_names.get(model, "Common name not defined") for model in model_numbers)


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


def audit_text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def audit_int(value) -> int:
    if value is None or pd.isna(value):
        return 0
    return int(value)


def audit_bool(value) -> bool:
    if value is None or pd.isna(value):
        return False
    return bool(value)


metrics = st.columns(4)
metrics[0].metric("Parts available", len(parts), border=True)
metrics[1].metric("Fishbone sections", len(sections), border=True)
placed_catalog_parts = assignments["part_id"].nunique() if not assignments.empty else 0
metrics[2].metric("Fishbone uses placed", len(assignments), border=True)
metrics[3].metric("Parts not yet placed", max(0, len(parts) - placed_catalog_parts), border=True)


master_tree_data = pits_bom_model_tree(project_id, "all")
master_nodes = master_tree_data.get("nodes", [])

master_info_by_part_id = {}
master_info_by_pnum = {}
for idx, node in enumerate(master_nodes):
    pid = str(node.get("part_id") or "").strip()
    pnum = str(node.get("part_number") or "").strip()
    depth = node.get("depth", 1)
    raw_qty = node.get("quantity", 1)
    try:
        qty = float(raw_qty) if raw_qty is not None and float(raw_qty) > 0 else 1.0
    except (ValueError, TypeError):
        qty = 1.0
    info = {
        "order": idx,
        "level": f"L{depth}",
        "quantity": qty,
    }
    if pid and pid not in master_info_by_part_id:
        master_info_by_part_id[pid] = info
    if pnum and pnum not in master_info_by_pnum:
        master_info_by_pnum[pnum] = info


assign_parts_tab, fishbone_tab, framework_tab = st.tabs(
    ["Assign Parts", "Fishbone", "Framework Set Up"],
    key=f"fishbone_main_tabs_{project_id}",
)

with assign_parts_tab:
    place_parts_title, place_parts_undo = st.columns([5, 0.7], vertical_alignment="center")
    place_parts_title.subheader("Place Parts into Fishbone")
    placement_has_unsaved = has_unsaved_table_changes(pool_editor_key)
    undo_placement = place_parts_undo.button(
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
            request_table_editor_reset(pool_editor_key)
            st.toast("Discarded the unsaved placement table edits", icon=":material/undo:")
        else:
            undo_state = st.session_state.pop(assignment_undo_key)
            restore_fishbone_assignment_snapshot(project_id, undo_state["assignments"])
            st.session_state[pending_use_key] = undo_state.get("pending_use_ids", [])
            request_table_editor_reset(pool_editor_key)
            request_table_editor_reset(assignment_editor_key)
            st.toast("Undid the last part placement change", icon=":material/undo:")
        st.rerun()
    if parts.empty:
        st.info("Add or import parts in the Parts Catalog before building the Fishbone framework.")
    elif active_sections.empty:
        st.info("Create and activate a Fishbone section in Framework Set Up before placing parts.")
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

        def resolve_part_meta(row, catalog_idx: int):
            pid = str(row["id"])
            pnum = str(row.get("part_number") or "").strip()
            info = master_info_by_part_id.get(pid) or master_info_by_pnum.get(pnum)
            if info:
                return info["order"], info["level"], info["quantity"]
            fallback_qty = row.get("quantity")
            try:
                fqty = float(fallback_qty) if fallback_qty is not None and float(fallback_qty) > 0 else 1.0
            except (ValueError, TypeError):
                fqty = 1.0
            return 1_000_000 + catalog_idx, "—", fqty

        meta_results = [
            resolve_part_meta(row, i)
            for i, (_, row) in enumerate(part_pool.iterrows())
        ]
        part_pool["_master_order"] = [m[0] for m in meta_results]
        part_pool["level"] = [m[1] for m in meta_results]
        part_pool["quantity"] = [m[2] for m in meta_results]
        part_pool = part_pool.sort_values(by=["_master_order", "part_number"], ascending=[True, True]).reset_index(drop=True)

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
            searchable = visible_parts[["part_number", "description", "level"]].fillna("").astype(str).agg(" ".join, axis=1)
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
            disabled=["id", "_master_order", "part_number", "level", "description", "revision", "model_applicability", "models_familiar", "fishbone_section"],
            column_order=["place", "edit_part", "part_number", "level", "description", "quantity", "revision", "models_familiar", "fishbone_section"],
            column_config={
                "id": None,
                "_master_order": None,
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
                    help="Open this exact catalog part in the Parts Catalog to edit its models, details, and photos.",
                ),
                "part_number": st.column_config.TextColumn("Part number", pinned=True),
                "level": st.column_config.TextColumn(
                    "Level",
                    width="small",
                    help="BOM hierarchy level from the Model Tree master list (e.g. L1, L2, L3).",
                ),
                "description": st.column_config.TextColumn("Part Name", width="large"),
                "quantity": st.column_config.NumberColumn(
                    "Fishbone quantity", step=0.01, format="%g",
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
            str(row["id"]): float(row["quantity"])
            for _, row in selected_parts.iterrows()
        }
        placed_part_ids = set(assignments["part_id"].astype(str)) if not assignments.empty else set()
        selected_unplaced_ids = [part_id for part_id in selected_part_ids if part_id not in placed_part_ids]
        selected_additional_use_ids = [part_id for part_id in selected_part_ids if part_id in pending_use_ids]
        placement_row = st.container(horizontal=True, vertical_alignment="bottom")
        target_section_id = placement_row.selectbox(
            "Place selected parts in",
            options=active_sections["id"].astype(str).tolist(),
            format_func=lambda section_id: section_option_labels.get(section_id, section_id),
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
                selected_part_details = {
                    str(row["id"]): row for _, row in selected_parts.iterrows()
                }
                placed_part_uses = [
                    {
                        "part_id": part_id,
                        "part_number": audit_text(
                            selected_part_details[part_id].get("part_number")
                        ),
                        "section_id": str(target_section_id),
                        "section_name": section_name_by_id[target_section_id],
                        "additional_use": part_id in selected_additional_use_ids,
                    }
                    for part_id in [*selected_unplaced_ids, *selected_additional_use_ids]
                ]
                record_audit_event(
                    project_id,
                    "Fishbone part assignments",
                    "Place selected parts",
                    count,
                    st.session_state.get("current_editor", ""),
                    {
                        "placed_part_uses": placed_part_uses,
                        "first_uses_added": len(selected_unplaced_ids),
                        "additional_uses_added": len(selected_additional_use_ids),
                    },
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
            "Place selected parts automatically handles both first-time parts and additional uses staged from Assigned Parts."
        )


    st.subheader("Assigned Parts")
    assignments_have_unsaved = table_has_unsaved_changes(
        assignment_editor_key, native_row_selection=True
    )
    refresh_part_placement = False
    selected_assignment_rows = assignments.iloc[0:0].copy()
    if assignments.empty:
        st.caption("Assigned parts will appear here for ordering within each Fishbone section.")
    else:
        full_assignment_editor = assignments.copy()

        def _format_pits_sync_status(row: pd.Series) -> str:
            status = str(row.get("pits_sync_status") or "")
            updated_at = row.get("pits_quantity_updated_at")
            if status == "In sync" and updated_at and pd.notna(updated_at):
                try:
                    dt = pd.to_datetime(updated_at, errors="coerce")
                    if pd.notna(dt):
                        return f"Updated from PITS on {dt.strftime('%b %d, %Y')}"
                except Exception:
                    pass
            return status
        full_assignment_editor["section"] = full_assignment_editor["section_id"].astype(str).map(section_option_labels)
        full_assignment_editor["model_applicability"] = full_assignment_editor.apply(
            lambda row: feature_applicability(row["part_id"], row["model_applicability"]), axis=1
        )
        full_assignment_editor["pits_sync_status"] = full_assignment_editor.apply(
            _format_pits_sync_status, axis=1
        )
        assignment_editor = filter_table(
            full_assignment_editor,
            key="fishbone_assignment_filters",
            dropdown_columns=["section", "revision", "model_applicability"],
            search_columns=["section", "part_number", "description", "use_description", "revision", "model_applicability", "notes"],
            labels={"section": "Fishbone section", "model_applicability": "Feature applicability"},
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
            st.toast("Part returned to Place Parts into Fishbone and is ready to place again.", icon=":material/arrow_upward:")

        edited_assignments = st.data_editor(
            assignment_editor,
            key=assignment_editor_key,
            hide_index=True,
            num_rows="delete",
            height=430,
            disabled=[
                "id", "part_id", "part_number", "description", "revision",
                "model_applicability", "pits_sync_status", "updated_at",
            ],
            column_order=[
                "edit_part", "add_use", "section", "part_number", "description",
                "quantity", "pits_sync_status", "model_applicability", "revision",
                "use_description", "notes", "sequence",
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
                    help="Open this exact part in the Parts Catalog to edit its catalog details and photos.",
                ),
                "add_use": st.column_config.ButtonColumn(
                    "Another Fishbone use",
                    pinned=True,
                    type="tertiary",
                    on_click=add_assigned_part_use,
                    key="fishbone_assignment_add_use",
                    help="Return this catalog part to Section 2 so its additional use can be placed deliberately.",
                ),
                "section": st.column_config.SelectboxColumn(
                    "Fishbone section",
                    options=[
                        section_option_labels[str(section_id)]
                        for section_id in active_sections["id"].astype(str)
                    ],
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
                "quantity": st.column_config.NumberColumn(
                    "Fishbone quantity",
                    step=0.01,
                    format="%g",
                    help="For PITS BOM uses, quantity is maintained in PITS and updated automatically on import.",
                ),
                "pits_sync_status": st.column_config.TextColumn(
                    "PITS status",
                    width="medium",
                    help=(
                        "Shows whether this approved Fishbone use matches its linked PITS BOM occurrence. "
                        "PITS imports automatically update approved quantities."
                    ),
                ),
                "pits_quantity_updated_at": None,
                "model_applicability": st.column_config.TextColumn("Feature applicability", width="medium"),
                "notes": st.column_config.TextColumn("IE notes", width="large"),
                "updated_at": None,
            },
        )
        assignment_actions = editable_table_footer(
            editor_key=assignment_editor_key,
            key_prefix="fishbone_assignments",
            undo_available=assignment_undo_key in st.session_state,
            native_row_selection=True,
        )
        refresh_part_placement = assignment_actions.save_and_refresh
        if assignment_actions.undo:
            if assignments_have_unsaved:
                request_table_editor_reset(assignment_editor_key)
                st.toast("Discarded the unsaved assigned-parts edits", icon=":material/undo:")
            else:
                undo_state = st.session_state.pop(assignment_undo_key)
                restore_fishbone_assignment_snapshot(project_id, undo_state["assignments"])
                st.session_state[pending_use_key] = undo_state.get("pending_use_ids", [])
                request_table_editor_reset(assignment_editor_key)
                st.toast("Undid the last assigned-parts change", icon=":material/undo:")
            st.rerun()
        if st.session_state.pop(f"fishbone_open_part_{project_id}", False):
            st.switch_page("app_pages/parts.py")
        selected_assignment_rows = native_selected_rows(
            assignment_editor, editor_key=assignment_editor_key
        )
        request_assignment_delete = not selected_assignment_rows.empty
        if request_assignment_delete:
            if table_has_unsaved_changes(
                assignment_editor_key, native_row_selection=True
            ):
                st.warning("Save or undo other assigned-part edits before deleting selected uses.")
            else:
                st.session_state[f"fishbone_assignments_pending_delete_{project_id}"] = (
                    selected_assignment_rows["id"].astype(str).tolist()
                )
                stage_native_delete_confirmation(assignment_editor_key)

        @st.dialog("Delete selected Fishbone uses?", dismissible=False)
        def confirm_assignment_delete() -> None:
            pending_key = f"fishbone_assignments_pending_delete_{project_id}"
            pending_ids = st.session_state.get(pending_key, [])
            assembly_impact = fishbone_assignment_assembly_impact(project_id, pending_ids)
            st.warning(
                f"Delete {len(pending_ids)} selected Fishbone use(s)? Parts Catalog records and other "
                "uses will remain."
            )
            if not assembly_impact.empty:
                st.markdown(
                    f"**{len(assembly_impact)} assembly mini-BOM component row(s) will also be deleted:**"
                )
                for assembly_number, rows in assembly_impact.groupby("assembly_number", sort=False):
                    st.write(f"- {assembly_number}: {len(rows)} component row(s)")
            actions = st.container(horizontal=True)
            if actions.button("Cancel", key=f"cancel_fishbone_assignment_delete_{project_id}"):
                st.session_state.pop(pending_key, None)
                request_table_editor_reset(assignment_editor_key)
                st.rerun()
            if actions.button(
                "Delete Fishbone uses",
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
                        {
                            "assignment_ids": pending_ids,
                            "assembly_component_rows_deleted": len(assembly_impact),
                            "assembly_numbers_affected": (
                                assembly_impact["assembly_number"].astype(str).drop_duplicates().tolist()
                                if not assembly_impact.empty else []
                            ),
                        },
                    )
                    st.session_state.pop(pending_key, None)
                    request_table_editor_reset(assignment_editor_key)
                    st.toast(f"Deleted {count} selected Fishbone uses", icon=":material/delete:")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        if st.session_state.get(f"fishbone_assignments_pending_delete_{project_id}"):
            confirm_assignment_delete()

        st.caption(
            "Each row is one use of a catalog part. Edit its location, Fishbone quantity, section, or order, then select Save & Refresh below the table. "
            "Another use stages the part in Place Parts into Fishbone instead of creating a duplicate here."
        )
        assignments_to_save = merge_filtered_edits(
            full_assignment_editor, assignment_editor, edited_assignments
        )
        assignments_to_save = assignments_to_save.drop(
            columns=["edit_part", "add_use"], errors="ignore"
        )
        section_id_by_label = {
            label: section_id for section_id, label in section_option_labels.items()
        }
        assignments_to_save["section_id"] = assignments_to_save["section"].map(section_id_by_label)
        if not inactive_assignments.empty:
            assignments_to_save = pd.concat(
                [assignments_to_save, inactive_assignments], ignore_index=True, sort=False
            )
        if refresh_part_placement:
            try:
                if not selected_assignment_rows.empty:
                    raise ValueError("Clear selected rows before saving assigned-part edits.")
                previous_assignments_by_id = {
                    str(row["id"]): row for _, row in all_assignments.iterrows()
                }
                added_assignment_ids = []
                edited_assignment_ids = []
                for _, row in assignments_to_save.iterrows():
                    assignment_id = (
                        "" if pd.isna(row.get("id")) else str(row.get("id")).strip()
                    )
                    previous = previous_assignments_by_id.get(assignment_id)
                    if not assignment_id or previous is None:
                        added_assignment_ids.append(assignment_id)
                        continue
                    assignment_changed = any(
                        audit_text(row.get(field)) != audit_text(previous.get(field))
                        for field in ["section_id", "use_description", "notes"]
                    ) or audit_int(row.get("sequence")) != audit_int(
                        previous.get("sequence")
                    ) or not decimal_values_equal(
                        row.get("quantity"), previous.get("quantity")
                    )
                    if assignment_changed:
                        edited_assignment_ids.append(assignment_id)
                count = replace_fishbone_part_assignments(project_id, assignments_to_save)
                record_audit_event(
                    project_id,
                    "Fishbone part assignments",
                    "Save & Refresh",
                    len(added_assignment_ids) + len(edited_assignment_ids),
                    st.session_state.get("current_editor", ""),
                    {
                        "assignments_added": len(added_assignment_ids),
                        "assignments_edited": len(edited_assignment_ids),
                        "assignment_ids_added": added_assignment_ids,
                        "assignment_ids_edited": edited_assignment_ids,
                    },
                )
                st.session_state[assignment_undo_key] = current_assignment_undo
                request_table_editor_reset(assignment_editor_key)
                st.toast(f"Saved {count} fishbone part assignments", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))




with fishbone_tab:
    if sections.empty:
        st.info("No Fishbone sections created yet. Use **➕ Add Section** above or in the canvas toolbar to create your first Main spine.")
    if True:
        visible_sections = sections.loc[sections["active"].fillna(1).astype(bool)].copy() if not sections.empty else sections.copy()
        records = {str(row["id"]): row.to_dict() for _, row in visible_sections.iterrows()}

        # Connections from database
        connections_df = assembly_section_connections(project_id)

        # Canvas draft management
        canvas_draft_key = f"fishbone_canvas_draft_{project_id}"
        draft = st.session_state.setdefault(
            canvas_draft_key,
            {
                "positions": {},
                "connections": [],
                "deleted_connections": set(),
                "new_assignments": [],
                "updated_assignments": [],
                "deleted_assignments": set(),
            },
        )
        if "updated_assignments" not in draft:
            draft["updated_assignments"] = []

        canvas_key = f"interactive_fishbone_{project_id}"
        canvas_state = st.session_state.get(canvas_key)
        if canvas_state is not None:
            if p := getattr(canvas_state, "create_section", None):
                sec_name = str(p.get("name") or "").strip()
                sec_type = str(p.get("section_type") or "Subassembly")
                parent_id = p.get("parent_id") or None
                gx = p.get("grid_x")
                gy = p.get("grid_y")
                if sec_name:
                    try:
                        st.session_state[framework_undo_key] = current_plan_snapshot
                        new_sec_id = add_assembly_section(
                            project_id,
                            sec_name,
                            sec_type,
                            parent_id if sec_type == "Subassembly" else None,
                            "",
                            grid_x=int(gx) if gx is not None else None,
                            grid_y=int(gy) if gy is not None else None,
                        )
                        if parent_id and sec_type == "Subassembly":
                            save_assembly_section_connection(
                                project_id,
                                new_sec_id,
                                parent_id,
                                connection_type="subassembly",
                                sequence=10,
                                editor_name=st.session_state.get("current_editor", ""),
                            )
                        area_summary = yamazumi_area_creation_summary(project_id, new_sec_id)
                        created_areas = list(area_summary.get("created", []))
                        area_conflicts = list(area_summary.get("conflicts", []))
                        record_audit_event(
                            project_id,
                            "Fishbone framework",
                            "Add section from canvas",
                            1,
                            st.session_state.get("current_editor", ""),
                            {
                                "framework_section_added": {
                                    "section_id": new_sec_id,
                                    "section_name": sec_name,
                                    "section_type": sec_type,
                                    "grid_x": gx,
                                    "grid_y": gy,
                                },
                                "automatic_yamazumi_areas": created_areas,
                                "yamazumi_area_conflicts": area_conflicts,
                            },
                        )
                        request_table_editor_reset(framework_editor_key)
                        st.toast(f"Created {sec_type} '{sec_name}'", icon=":material/check_circle:")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            if p := getattr(canvas_state, "move_node", None):
                if sec_id := p.get("section_id"):
                    draft["positions"][sec_id] = (p.get("grid_x"), p.get("grid_y"))
            if p := getattr(canvas_state, "auto_arrange", None):
                if pos_map := p.get("positions"):
                    draft["positions"].update(pos_map)
            if p := getattr(canvas_state, "create_connection", None):
                f_id = p.get("from_section_id")
                t_id = p.get("to_section_id")
                c_type = p.get("connection_type", "subassembly")
                if f_id and t_id and f_id != t_id:
                    if not any(
                        dc["from_section_id"] == f_id and dc["to_section_id"] == t_id
                        for dc in draft["connections"]
                    ):
                        draft["connections"].append({
                            "from_section_id": f_id,
                            "to_section_id": t_id,
                            "connection_type": c_type,
                            "sequence": 10,
                        })
            if p := getattr(canvas_state, "delete_connection", None):
                if cid := p.get("connection_id"):
                    draft["deleted_connections"].add(cid)
            if p := getattr(canvas_state, "drop_part", None):
                pid = p.get("part_id")
                sid = p.get("section_id")
                if pid and sid:
                    draft["new_assignments"].append({
                        "part_id": pid,
                        "section_id": sid,
                        "quantity": float(p.get("quantity") or 1.0),
                        "use_description": str(p.get("use_description") or ""),
                    })
            if p := getattr(canvas_state, "drop_assembly", None):
                asm_pid = p.get("assembly_part_id")
                built_sid = p.get("built_section_id")
                inst_sid = p.get("installed_section_id")
                if asm_pid and built_sid and inst_sid:
                    tree = pits_bom_model_tree(project_id)
                    matched_node = next(
                        (
                            n
                            for n in tree.get("nodes", [])
                            if str(n.get("part_id")) == str(asm_pid)
                            or str(n.get("child_part_id")) == str(asm_pid)
                            or str(n.get("part_number")) == str(asm_pid)
                        ),
                        None,
                    )
                    child_nodes = matched_node.get("children", []) if matched_node else []
                    for c in child_nodes:
                        c_pid = str(c.get("part_id") or c.get("child_part_id") or "")
                        if c_pid:
                            draft["new_assignments"].append({
                                "part_id": c_pid,
                                "section_id": built_sid,
                                "quantity": float(c.get("quantity") or c.get("proposed_quantity") or 1.0),
                                "use_description": "Built subcomponent",
                            })
                    draft["new_assignments"].append({
                        "part_id": asm_pid,
                        "section_id": inst_sid,
                        "quantity": 1.0,
                        "use_description": "Installed assembly",
                    })
            if p := getattr(canvas_state, "remove_part", None):
                if aid := p.get("assignment_id"):
                    draft["deleted_assignments"].add(aid)
                pid = p.get("part_id")
                if pid:
                    draft["new_assignments"] = [
                        na for na in draft["new_assignments"] if na.get("part_id") != pid
                    ]

        image_path_by_part = (
            parts.set_index(parts["id"].astype(str))["image_path"].to_dict()
            if not parts.empty and "image_path" in parts.columns
            else {}
        )
        visual_feature_options = sorted(
            {label for labels in feature_labels_by_part.values() for label in labels},
            key=str.casefold,
        )
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
            help="Open the Parts Catalog to edit part details or add more photos.",
        ):
            st.switch_page("app_pages/parts.py")

        # Effective assignments (DB minus deleted plus draft new)
        effective_assigned_part_ids = set()
        for _, a in assignments.iterrows():
            if str(a["id"]) not in draft["deleted_assignments"]:
                effective_assigned_part_ids.add(str(a["part_id"]))
        for na in draft["new_assignments"]:
            effective_assigned_part_ids.add(str(na["part_id"]))

        # Build Parts Palette items (Parts Catalog + BOM tree assembly hierarchy)
        bom_tree = pits_bom_model_tree(project_id)
        bom_nodes = bom_tree.get("nodes", []) if bom_tree else []
        asm_children_by_pid = {}
        for node in bom_nodes:
            np_id = str(node.get("part_id") or node.get("child_part_id") or "")
            children = node.get("children", [])
            if np_id and children:
                asm_children_by_pid[np_id] = [
                    {
                        "part_id": str(c.get("part_id") or c.get("child_part_id") or ""),
                        "part_number": str(c.get("part_number") or ""),
                        "quantity": float(c.get("quantity") or c.get("proposed_quantity") or 1.0),
                    }
                    for c in children
                ]

        palette_items = []
        seen_pids = set()
        seen_pns = set()

        for _, p in parts.iterrows():
            pid = str(p["id"])
            pn = str(p.get("part_number") or "").strip()
            if not pid or pid in seen_pids:
                continue
            seen_pids.add(pid)
            if pn:
                seen_pns.add(pn)

            ch_list = asm_children_by_pid.get(pid, [])
            is_asm = len(ch_list) > 0
            raw_qty = p.get("quantity")
            try:
                qty = float(raw_qty) if raw_qty is not None and float(raw_qty) > 0 else 1.0
            except (ValueError, TypeError):
                qty = 1.0

            palette_items.append({
                "part_id": pid,
                "part_number": pn or "—",
                "description": str(p.get("description", "") or ""),
                "quantity": qty,
                "is_assembly": is_asm,
                "child_count": len(ch_list),
                "child_parts": ch_list,
                "image": part_thumbnail(image_path_by_part.get(pid, "")),
                "placed": pid in effective_assigned_part_ids,
            })

        for node in bom_nodes:
            np_id = str(node.get("part_id") or node.get("child_part_id") or "")
            np_pn = str(node.get("part_number") or "").strip()
            if not np_id or np_id in seen_pids or (np_pn and np_pn in seen_pns):
                continue
            seen_pids.add(np_id)
            if np_pn:
                seen_pns.add(np_pn)
            ch_list = node.get("children", [])
            is_asm = len(ch_list) > 0
            palette_items.append({
                "part_id": np_id,
                "part_number": np_pn or "—",
                "description": str(node.get("description") or node.get("part_name") or ""),
                "quantity": float(node.get("quantity") or node.get("proposed_quantity") or 1.0),
                "is_assembly": is_asm,
                "child_count": len(ch_list),
                "child_parts": [
                    {
                        "part_id": str(c.get("part_id") or c.get("child_part_id") or ""),
                        "part_number": str(c.get("part_number") or ""),
                        "quantity": float(c.get("quantity") or c.get("proposed_quantity") or 1.0),
                    }
                    for c in ch_list
                ],
                "image": part_thumbnail(image_path_by_part.get(np_id, "")),
                "placed": np_id in effective_assigned_part_ids,
            })

        def get_palette_sort_key(item):
            pid = item["part_id"]
            pnum = item["part_number"]
            info = master_info_by_part_id.get(pid) or master_info_by_pnum.get(pnum)
            order = info["order"] if info else 1_000_000
            return (order, pnum.casefold())

        palette_items.sort(key=get_palette_sort_key)

        # Visual Placed Parts
        staged_updates_by_aid = {
            ua["assignment_id"]: ua
            for ua in draft.get("updated_assignments", [])
            if ua.get("assignment_id")
        }
        visual_parts = []
        for _, assignment in assignments.iterrows():
            aid = str(assignment["id"])
            if aid in draft["deleted_assignments"]:
                continue
            part_id = str(assignment["part_id"])
            section_id = str(assignment["section_id"])
            staged = staged_updates_by_aid.get(aid)
            current_sec_id = staged.get("section_id") if staged and staged.get("section_id") else section_id
            if current_sec_id not in records:
                continue
            applicability_label = feature_applicability(part_id, assignment["model_applicability"])
            if (
                selected_visual_features
                and applicability_label != "All models"
                and not set(selected_visual_features) & set(feature_labels_by_part.get(part_id, []))
            ):
                continue
            visual_parts.append({
                "id": aid,
                "part_id": part_id,
                "section_id": current_sec_id,
                "section_name": str(records.get(current_sec_id, {}).get("name") or assignment["section_name"]),
                "part_number": str(assignment["part_number"] or ""),
                "description": str(assignment["description"] or ""),
                "use_description": str(assignment["use_description"] or ""),
                "quantity": float(assignment["quantity"] or 0),
                "models": applicability_label,
                "image": part_thumbnail(image_path_by_part.get(part_id, "")),
            })
        for idx, na in enumerate(draft["new_assignments"]):
            part_row = parts.loc[parts["id"].astype(str) == na["part_id"]]
            pn = str(part_row["part_number"].iloc[0]) if not part_row.empty else "—"
            p_desc = str(part_row["description"].iloc[0]) if not part_row.empty and "description" in part_row.columns else "—"
            sec_name = records.get(na["section_id"], {}).get("name", "Section")
            visual_parts.append({
                "id": f"draft_a_{idx}",
                "part_id": na["part_id"],
                "section_id": na["section_id"],
                "section_name": sec_name,
                "part_number": pn,
                "description": p_desc,
                "use_description": na.get("use_description", ""),
                "quantity": float(na.get("quantity") or 1.0),
                "models": "All models",
                "image": part_thumbnail(image_path_by_part.get(na["part_id"], "")),
            })

        # Node rows with grid coordinates and op prefix
        node_rows = []
        all_sections_list = [
            {
                "id": str(r["id"]),
                "name": str(r["name"]),
                "type": str(r["section_type"]),
                "parent_id": str(r["parent_id"]) if pd.notna(r.get("parent_id")) else None,
            }
            for _, r in visible_sections.iterrows()
        ]
        for _, row in visible_sections.iterrows():
            sec_id = str(row["id"])
            gx = draft["positions"].get(sec_id, (row.get("grid_x"), None))[0] if sec_id in draft["positions"] else row.get("grid_x")
            gy = draft["positions"].get(sec_id, (None, row.get("grid_y")))[1] if sec_id in draft["positions"] else row.get("grid_y")
            gx = int(gx) if gx is not None and pd.notna(gx) else None
            gy = int(gy) if gy is not None and pd.notna(gy) else None
            node_rows.append({
                "id": sec_id,
                "name": str(row["name"]),
                "type": str(row["section_type"]),
                "order": int(row["sequence"]),
                "parent_id": str(row["parent_id"]) if pd.notna(row.get("parent_id")) else None,
                "grid_x": gx,
                "grid_y": gy,
                "op_prefix": "",
                "parts": len([p for p in visual_parts if p["section_id"] == sec_id]),
            })

        # Connection rows
        conn_rows = []
        if not connections_df.empty:
            for _, conn_r in connections_df.iterrows():
                cid = str(conn_r["id"])
                if cid in draft["deleted_connections"]:
                    continue
                conn_rows.append({
                    "id": cid,
                    "from_section_id": str(conn_r["from_section_id"]),
                    "to_section_id": str(conn_r["to_section_id"]),
                    "connection_type": str(conn_r["connection_type"]),
                    "sequence": int(conn_r["sequence"]),
                })
        else:
            for sec_id, row in records.items():
                pid = normalized_parent_id(row.get("parent_id"))
                if pid and pid in records:
                    conn_rows.append({
                        "id": f"init_{sec_id}_{pid}",
                        "from_section_id": sec_id,
                        "to_section_id": pid,
                        "connection_type": "subassembly",
                        "sequence": 10,
                    })
            main_sec_ids = [
                str(r["id"]) for _, r in visible_sections.iterrows() if r["section_type"] == "Main spine"
            ]
            for left_id, right_id in zip(main_sec_ids, main_sec_ids[1:]):
                conn_rows.append({
                    "id": f"init_{left_id}_{right_id}",
                    "from_section_id": left_id,
                    "to_section_id": right_id,
                    "connection_type": "series",
                    "sequence": 10,
                })
        for idx, dc in enumerate(draft["connections"]):
            conn_rows.append({
                "id": f"draft_{idx}",
                "from_section_id": dc["from_section_id"],
                "to_section_id": dc["to_section_id"],
                "connection_type": dc["connection_type"],
                "sequence": dc.get("sequence", 10),
            })

        # Render Interactive Fishbone Canvas Builder
        interactive_fishbone(
            sections=node_rows,
            connections=conn_rows,
            parts=visual_parts,
            palette_items=palette_items,
            all_sections=all_sections_list,
            key=canvas_key,
        )

        has_canvas_draft = bool(
            draft["positions"]
            or draft["connections"]
            or draft["deleted_connections"]
            or draft["new_assignments"]
            or draft.get("updated_assignments")
            or draft["deleted_assignments"]
        )
        if has_canvas_draft:
            total_actions = (
                len(draft["positions"])
                + len(draft["connections"])
                + len(draft["deleted_connections"])
                + len(draft["new_assignments"])
                + len(draft.get("updated_assignments", []))
                + len(draft["deleted_assignments"])
            )
            st.info(
                f"Unsaved canvas changes ({total_actions} staged edit{'s' if total_actions != 1 else ''}). Click Save & Refresh below to commit."
            )

        canvas_actions = editable_table_footer(
            editor_key=f"fishbone_canvas_footer_{project_id}",
            key_prefix=f"fishbone_canvas_{project_id}",
            additional_unsaved_changes=has_canvas_draft,
        )
        if canvas_actions.undo:
            if has_canvas_draft:
                st.session_state.pop(canvas_draft_key, None)
                st.toast("Discarded canvas draft changes", icon=":material/undo:")
                st.rerun()
            elif framework_undo_key in st.session_state:
                restore_fishbone_plan_snapshot(project_id, st.session_state.pop(framework_undo_key))
                st.toast("Restored Fishbone framework to previous saved state", icon=":material/undo:")
                st.rerun()

        if canvas_actions.save_and_refresh:
            try:
                st.session_state[framework_undo_key] = current_plan_snapshot
                save_fishbone_canvas_draft(
                    project_id=project_id,
                    positions=draft["positions"] if draft["positions"] else None,
                    connections=draft["connections"] if draft["connections"] else None,
                    deleted_connection_ids=list(draft["deleted_connections"]) if draft["deleted_connections"] else None,
                    new_assignments=draft["new_assignments"] if draft["new_assignments"] else None,
                    updated_assignments=draft.get("updated_assignments") if draft.get("updated_assignments") else None,
                    deleted_assignment_ids=list(draft["deleted_assignments"]) if draft["deleted_assignments"] else None,
                    editor_name=st.session_state.get("current_editor", ""),
                )
                st.session_state.pop(canvas_draft_key, None)
                request_table_editor_reset(pool_editor_key)
                request_table_editor_reset(assignment_editor_key)
                request_table_editor_reset(framework_editor_key)
                st.toast("Saved all Fishbone canvas changes", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        # Stacked Layout: Collapsible Table Editors
        st.divider()
        with st.expander("Framework Sections Table", expanded=False):
            st.caption(
                "Framework sections establish product assembly order and subassembly feeding relationships."
            )
            sec_cols = [c for c in ["name", "section_type", "sequence", "active"] if c in visible_sections.columns]
            display_sections = visible_sections[sec_cols].copy() if not visible_sections.empty else pd.DataFrame(columns=["name", "section_type", "sequence", "active"])
            st.dataframe(display_sections, width="stretch", hide_index=True)

        with st.expander("Parts Placement Table", expanded=False):
            st.caption("Parts placed into Fishbone assembly sections and subassemblies.")
            if not assignments.empty:
                display_cols = ["section_name", "part_number", "description", "quantity", "use_description"]
                display_assignments = assignments[
                    [c for c in display_cols if c in assignments.columns]
                ].copy()
                st.dataframe(
                    display_assignments,
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("No parts placed yet.")



with framework_tab:
    st.subheader("Build the Fishbone framework")
    framework_has_unsaved = table_has_unsaved_changes(
        framework_editor_key, native_row_selection=True
    )
    refresh_framework = False
    st.caption("Main-spine Fishbone sections establish product assembly order. Subassemblies—such as Wheel Subassembly—must attach to a parent Fishbone section or subassembly.")


    with st.container(border=True):
        st.subheader("Add a Fishbone section or subassembly")
        section_form_version_key = f"section_form_version_{project_id}"
        st.session_state.setdefault(section_form_version_key, 0)
        with st.form(f"add_assembly_section_{st.session_state[section_form_version_key]}"):
            section_row = st.columns([2, 1, 2])
            section_name = section_row[0].text_input("Name", placeholder="Wheel Subassembly")
            section_type = section_row[1].selectbox("Type", ["Main spine", "Subassembly", "Support Operations"])
            parent_id = section_row[2].selectbox(
                "Parent assembly",
                options=[None, *parent_options],
                format_func=lambda value: (
                    "Product / main assembly"
                    if value is None else section_option_labels.get(value, value)
                ),
                help="Required for a subassembly. Main-spine sections attach directly to the product. Support Operations are independent of the main spine.",
            )
            section_description = st.text_area("Fishbone section description", placeholder="What is assembled in this section?")
            if st.form_submit_button("Add to Fishbone framework", type="primary", icon=":material/account_tree:"):
                try:
                    section_id = add_assembly_section(
                        project_id, section_name, section_type, parent_id,
                        section_description,
                    )
                    area_summary = yamazumi_area_creation_summary(
                        project_id, section_id
                    )
                    created_areas = list(area_summary["created"])
                    area_conflicts = list(area_summary["conflicts"])
                    record_audit_event(
                        project_id,
                        "Fishbone framework",
                        "Add to framework",
                        1,
                        st.session_state.get("current_editor", ""),
                        {
                            "framework_section_added": {
                                "section_id": section_id,
                                "section_name": section_name.strip(),
                                "section_type": (
                                    "main-spine"
                                    if section_type == "Main spine"
                                    else "support-operations"
                                    if section_type == "Support Operations"
                                    else "subassembly"
                                ),
                            },
                            "automatic_yamazumi_areas": created_areas,
                            "yamazumi_area_conflicts": area_conflicts,
                        },
                    )
                    if created_areas:
                        record_audit_event(
                            project_id,
                            "Yamazumi",
                            "Create areas from Fishbone",
                            len(created_areas),
                            st.session_state.get("current_editor", ""),
                            {
                                "section_id": section_id,
                                "section_name": section_name.strip(),
                                "created_areas": created_areas,
                                "conflicts": area_conflicts,
                            },
                        )
                    st.session_state[framework_undo_key] = current_plan_snapshot
                    st.session_state[section_form_version_key] += 1
                    result_message = (
                        f"Fishbone section added; {len(created_areas)} Yamazumi area(s) created"
                    )
                    if area_conflicts:
                        result_message += (
                            f"; {len(area_conflicts)} scenario(s) need manual link repair"
                        )
                    st.toast(result_message, icon=":material/check_circle:")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    if sections.empty:
        st.info("Add at least one main-spine Fishbone section to begin the Fishbone framework.")
    else:
        framework_walk = sections
        framework_depth = dict(zip(
            framework_walk["id"].astype(str),
            framework_walk["depth"].astype(int),
        ))
        framework = framework_walk.drop(columns=["depth"])
        framework["hierarchy"] = framework.apply(
            lambda row: (
                f"🟪  {row['name']}"
                if str(row.get("section_type") or "") == "Support Operations"
                else (
                    f"🟦  {row['name']}"
                    if framework_depth.get(str(row["id"]), 0) == 0
                    else f"{' ' * framework_depth.get(str(row['id']), 0)}└─ 🟧  {row['name']}"
                )
            ),
            axis=1,
        )
        framework["parent_assembly"] = framework.apply(
            lambda row: (
                "Independent / Support"
                if str(row.get("section_type") or "") == "Support Operations" and not normalized_parent_id(row.get("parent_id"))
                else (
                    "Product / main assembly"
                    if not normalized_parent_id(row.get("parent_id"))
                    else section_option_labels.get(
                        normalized_parent_id(row.get("parent_id")), normalized_parent_id(row.get("parent_id"))
                    )
                )
            ),
            axis=1,
        )
        framework["order_actions"] = [[
            ":material/first_page: Move to start",
            ":material/arrow_upward: Move earlier",
            ":material/arrow_downward: Move later",
            ":material/last_page: Move to end",
        ]] * len(framework)
        framework["assemblies_action"] = ":material/grid_on: Assembly grid"
        full_framework = framework.copy()
        framework = filter_table(
            full_framework,
            key="assembly_framework_filters",
            dropdown_columns=["section_type", "parent_assembly", "active"],
            search_columns=["hierarchy", "name", "parent_assembly", "description"],
            labels={"section_type": "Fishbone section type", "parent_assembly": "Parent assembly", "active": "Active status"},
            reset_widget_keys=[framework_editor_key],
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
                section_name = str(framework.iloc[click["row"]]["name"])
                parent_id = normalized_parent_id(
                    framework.iloc[click["row"]].get("parent_id")
                )
                moved = reorder_assembly_section(project_id, section_id, action)
                if moved:
                    reordered_sections = assembly_section_walk_order(project_id)
                    reordered_parent_ids = reordered_sections["parent_id"].apply(
                        normalized_parent_id
                    )
                    sibling_order = reordered_sections.loc[
                        reordered_parent_ids == parent_id
                    ].sort_values(["sequence", "name"])
                    new_order = [
                        {
                            "section_id": str(row["id"]),
                            "section_name": str(row["name"]),
                            "sequence": int(row["sequence"]),
                        }
                        for _, row in sibling_order.iterrows()
                    ]
                    record_audit_event(
                        project_id,
                        "Fishbone framework",
                        "Reorder framework",
                        len(new_order),
                        st.session_state.get("current_editor", ""),
                        {
                            "framework_section_reordered": section_name,
                            "move_action": action,
                            "new_order": new_order,
                        },
                    )
                    st.session_state[framework_undo_key] = current_plan_snapshot
                    st.toast(f"{framework.iloc[click['row']]['name']}: {action.lower()}", icon=":material/swap_vert:")

        def show_framework_assemblies() -> None:
            click = st.session_state.get("framework_assemblies_action") or {}
            if 0 <= int(click.get("row", -1)) < len(framework):
                st.session_state[f"fishbone_assembly_section_{project_id}"] = str(
                    framework.iloc[int(click["row"])]["id"]
                )

        framework_editor = st.data_editor(
            framework,
            key=framework_editor_key,
            hide_index=True,
            num_rows="delete",
            height=300,
            disabled=["id", "hierarchy", "sequence", "created_at", "updated_at", "assemblies_action"],
            column_order=["hierarchy", "active", "sequence", "order_actions", "assemblies_action", "name", "section_type", "parent_assembly", "description"],
            column_config={
                "id": None,
                "project_id": None,
                "parent_id": None,
                "hierarchy": st.column_config.TextColumn(
                    "Fishbone section hierarchy",
                    pinned=True,
                    width="large",
                    help="Blue rows are main-spine sections. Orange indented rows are subassemblies grouped under their parent. Purple rows are support operations.",
                ),
                "active": st.column_config.CheckboxColumn("Active", help="Inactive Fishbone sections remain in history but are hidden from new part placement."),
                "sequence": st.column_config.NumberColumn("Order", format="%d", pinned=True, help="Managed automatically by the move actions."),
                "order_actions": st.column_config.ButtonColumn(
                    "Move",
                    pinned=True,
                    type="secondary",
                    on_click=handle_framework_order,
                    key="framework_order_action",
                ),
                "assemblies_action": st.column_config.ButtonColumn(
                    "Assembly grid",
                    pinned=True,
                    type="tertiary",
                    on_click=show_framework_assemblies,
                    key="framework_assemblies_action",
                    help="Show assembly numbers built or installed in this section.",
                ),
                "name": st.column_config.TextColumn("Fishbone section", required=True, pinned=True, width="large"),
                "section_type": st.column_config.SelectboxColumn("Type", options=["Main spine", "Subassembly", "Support Operations"], required=True),
                "parent_assembly": st.column_config.SelectboxColumn(
                    "Parent assembly",
                    options=[
                        "Product / main assembly",
                        "Independent / Support",
                        *[
                            section_option_labels[str(section_id)]
                            for section_id in sections["id"].astype(str)
                        ],
                    ],
                    required=True,
                    width="large",
                ),
                "description": st.column_config.TextColumn("Fishbone section description", width="large"),
                "created_at": None,
                "updated_at": st.column_config.DatetimeColumn("Updated", format="MMM DD, YYYY HH:mm"),
            },
        )
        framework_actions = editable_table_footer(
            editor_key=framework_editor_key,
            key_prefix="assembly_framework",
            undo_available=framework_undo_key in st.session_state,
            native_row_selection=True,
        )
        refresh_framework = framework_actions.save_and_refresh
        if framework_actions.undo:
            if framework_has_unsaved:
                request_table_editor_reset(framework_editor_key)
                st.toast("Discarded the unsaved Fishbone framework edits", icon=":material/undo:")
            else:
                restore_fishbone_plan_snapshot(project_id, st.session_state.pop(framework_undo_key))
                st.session_state.pop(assignment_undo_key, None)
                request_table_editor_reset(framework_editor_key)
                request_table_editor_reset(assignment_editor_key)
                st.toast("Undid the last Fishbone framework change", icon=":material/undo:")
            st.rerun()
        selected_framework_rows = native_selected_rows(
            framework, editor_key=framework_editor_key
        )
        framework_delete_key = f"fishbone_framework_pending_delete_{project_id}"
        if not selected_framework_rows.empty:
            if table_has_unsaved_changes(
                "assembly_framework_editor", native_row_selection=True
            ):
                st.warning("Save or undo other Fishbone framework edits before deleting sections.")
            else:
                st.session_state[framework_delete_key] = (
                    selected_framework_rows["id"].astype(str).tolist()
                )

        @st.dialog("Delete selected Fishbone sections?")
        def confirm_framework_delete() -> None:
            pending_ids = st.session_state.get(framework_delete_key, [])
            try:
                impact = assembly_section_delete_impact(project_id, pending_ids)
            except ValueError as exc:
                st.error(str(exc))
                return
            st.warning(
                f"Delete {impact['affected_section_count']} Fishbone section(s), including "
                f"{impact['descendant_section_count']} child section(s)?"
            )
            st.markdown(
                f"- **{impact['fishbone_use_count']}** Fishbone use(s) are currently in these sections; "
                "mini-BOM uses tied to a re-pointed Built section move to the target, and all "
                "other uses return to Not placed.\n"
                f"- **{impact['yamazumi_area_count']}** Yamazumi area(s) will move or merge into the target area, keeping their pitches and work.\n"
                f"- **{impact['process_link_count']}** Process at a Glance part requirement(s) will be re-pointed.\n"
                f"- **{impact['assembly_reference_count']}** assembly Built/Installed reference(s) will be re-pointed.\n"
                f"- **{impact['category_built_reference_count']}** assembly-grid category Built reference(s) will be re-pointed.\n"
                f"- **{impact['category_installed_reference_count']}** assembly-grid category Installed reference(s) will be re-pointed.\n"
                f"- **{impact['feature_visibility_preference_count']}** section-specific grid feature visibility preference(s) will be removed.\n"
                f"- **{impact['assembly_component_count']}** mini-BOM row(s) reference uses in these sections.\n"
                f"- **{impact['pits_bom_approved_occurrence_count']}** approved PITS BOM occurrence(s) must be detached before deletion."
            )
            if impact["pits_bom_approved_occurrence_count"]:
                st.error(
                    "Detach the approved PITS BOM occurrences in Import/Export Projects before "
                    "deleting these Fishbone sections."
                )
            st.caption("Sections: " + ", ".join(impact["section_names"]))
            replacement_sections = sections.loc[
                ~sections["id"].astype(str).isin(impact["section_ids"])
            ].copy()
            replacement_ids = replacement_sections["id"].astype(str).tolist()
            replacement_labels = {
                str(row["id"]): section_option_labels.get(
                    str(row["id"]), str(row["name"])
                )
                for _, row in replacement_sections.iterrows()
            }
            target_section_id = None
            target_is_valid = not impact["requires_repointing"]
            if impact["requires_repointing"] and not replacement_ids:
                st.error(
                    "Create another Fishbone section before deleting these sections. Yamazumi, "
                    "Process at a Glance, assembly, and assembly-grid category references require "
                    "a continuity target."
                )
            if impact["requires_repointing"] and replacement_ids:
                st.info(
                    "Choose one existing Fishbone section to continue all affected Yamazumi, "
                    "Process at a Glance, assembly, and assembly-grid category references under "
                    "before deleting."
                )
                target_section_id = st.selectbox(
                    "Continue work under Fishbone section",
                    replacement_ids,
                    index=None,
                    placeholder="Choose a target Fishbone section",
                    format_func=lambda value: replacement_labels.get(value, value),
                    key=f"fishbone_delete_target_{project_id}",
                    help=(
                        "This one target receives every affected Yamazumi, Process at a Glance, "
                        "assembly Built or Installed, and assembly-grid category Built or "
                        "Installed section reference. Section-specific grid feature visibility "
                        "preferences are removed instead of re-pointed."
                    ),
                )
                if target_section_id:
                    try:
                        target_validation = assembly_section_delete_target_validation(
                            project_id,
                            pending_ids,
                            str(target_section_id),
                            scenario_id,
                        )
                        target_is_valid = bool(target_validation["valid"])
                        if not target_is_valid:
                            st.error(str(target_validation["message"]))
                    except ValueError as exc:
                        target_is_valid = False
                        st.error(str(exc))
            actions = st.container(horizontal=True)
            if actions.button(
                "Cancel", key=f"cancel_fishbone_framework_delete_{project_id}"
            ):
                st.session_state.pop(framework_delete_key, None)
                request_table_editor_reset("assembly_framework_editor")
                st.rerun()
            if actions.button(
                "Delete sections",
                type="primary",
                icon=":material/delete:",
                disabled=bool(
                    impact["pits_bom_approved_occurrence_count"]
                    or (impact["requires_repointing"] and not target_is_valid)
                ),
                key=f"destructive_confirm_fishbone_framework_delete_{project_id}",
            ):
                try:
                    deleted = delete_assembly_sections(
                        project_id,
                        pending_ids,
                        str(target_section_id) if target_section_id else None,
                        scenario_id,
                    )
                    st.session_state[framework_undo_key] = current_plan_snapshot
                    record_audit_event(
                        project_id,
                        "Fishbone framework",
                        "Bulk delete",
                        deleted["affected_section_count"],
                        st.session_state.get("current_editor", ""),
                        deleted,
                    )
                    st.session_state.pop(framework_delete_key, None)
                    request_table_editor_reset("assembly_framework_editor")
                    st.toast(
                        f"Deleted {deleted['affected_section_count']} Fishbone sections",
                        icon=":material/delete:",
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        if st.session_state.get(framework_delete_key):
            confirm_framework_delete()

        assembly_section_key = f"fishbone_assembly_section_{project_id}"
        if st.session_state.get(assembly_section_key) in set(sections["id"].astype(str)):
            selected_section_id = str(st.session_state[assembly_section_key])
            section_assemblies = assemblies_for_section(project_id, selected_section_id)
            with st.container(border=True):
                st.markdown(
                    f"#### Assemblies for {section_name_by_id.get(selected_section_id, selected_section_id)}"
                )
                st.caption(
                    "Project-wide assembly numbers related to this selected Fishbone section. "
                    "Open Details for full editing on the Assembly grid page."
                )
                if section_assemblies.empty:
                    st.caption("No assemblies are built or installed in this section.")
                else:
                    section_assemblies = section_assemblies.copy()
                    section_assemblies["details"] = ":material/open_in_new: Details"

                    def open_section_assembly() -> None:
                        click = st.session_state.get("fishbone_assembly_details_action") or {}
                        if 0 <= int(click.get("row", -1)) < len(section_assemblies):
                            assembly_id = str(section_assemblies.iloc[int(click["row"])]["id"])
                            st.session_state[f"assemblies_selected_id_{project_id}"] = assembly_id
                            st.session_state[f"fishbone_open_assembly_{project_id}"] = True

                    st.dataframe(
                        section_assemblies,
                        hide_index=True,
                        column_order=["details", "assembly_number", "name", "relationship"],
                        column_config={
                            "id": None,
                            "details": st.column_config.ButtonColumn(
                                "Details",
                                type="tertiary",
                                on_click=open_section_assembly,
                                key="fishbone_assembly_details_action",
                            ),
                            "assembly_number": "Assembly number",
                            "name": "Assembly name",
                            "relationship": "Relationship",
                        },
                    )
            if st.session_state.pop(f"fishbone_open_assembly_{project_id}", False):
                st.switch_page("app_pages/assemblies.py")

        st.caption("🟦 Main-spine section · 🟧 Subassembly · 🟪 Support Operations · indentation shows the parent-child relationship.")
        id_by_label = {
            label: section_id for section_id, label in section_option_labels.items()
        }
        framework_to_save = merge_filtered_edits(full_framework, framework, framework_editor)
        framework_to_save["parent_id"] = framework_to_save["parent_assembly"].apply(
            lambda name: None if name in {"Product / main assembly", "Independent / Support"} else id_by_label.get(name)
        )
        if refresh_framework:
            try:
                if not selected_framework_rows.empty:
                    raise ValueError("Clear selected rows before saving the Fishbone framework.")
                previous_sections_by_id = {
                    str(row["id"]): row for _, row in sections.iterrows()
                }
                framework_changes = []
                for _, row in framework_to_save.iterrows():
                    section_id = str(row["id"])
                    previous = previous_sections_by_id.get(section_id)
                    if previous is None:
                        continue
                    changed_fields = []
                    for field in ["name", "section_type", "description"]:
                        current_value = audit_text(row.get(field))
                        previous_value = audit_text(previous.get(field))
                        if current_value != previous_value:
                            changed_fields.append(field)
                    if normalized_parent_id(row.get("parent_id")) != normalized_parent_id(
                        previous.get("parent_id")
                    ):
                        changed_fields.append("parent_id")
                    if audit_int(row.get("sequence")) != audit_int(
                        previous.get("sequence")
                    ):
                        changed_fields.append("sequence")
                    if audit_bool(row.get("active")) != audit_bool(
                        previous.get("active")
                    ):
                        changed_fields.append("active")
                    if changed_fields:
                        framework_changes.append(
                            {
                                "section_id": section_id,
                                "section_name": str(row["name"]),
                                "changed_fields": changed_fields,
                            }
                        )
                count = update_assembly_section_rows(project_id, framework_to_save)
                record_audit_event(
                    project_id,
                    "Fishbone framework",
                    "Save & Refresh",
                    len(framework_changes),
                    st.session_state.get("current_editor", ""),
                    {
                        "framework_sections_changed": framework_changes,
                        "new_section_order": [
                            {
                                "section_id": str(row["id"]),
                                "section_name": str(row["name"]),
                                "parent_id": normalized_parent_id(row.get("parent_id")),
                                "sequence": audit_int(row.get("sequence")),
                            }
                            for _, row in framework_to_save.iterrows()
                        ],
                    },
                )
                st.session_state[framework_undo_key] = current_plan_snapshot
                request_table_editor_reset(framework_editor_key)
                st.toast(f"Saved {count} Fishbone sections", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))




with st.expander("History", icon=":material/history:"):
    framework_history_tab, uses_history_tab = st.tabs(
        ["Fishbone framework", "Fishbone uses"]
    )
    with framework_history_tab:
        framework_history = audit_history(project_id, "Fishbone framework", limit=50)
        if framework_history.empty:
            st.caption("No Fishbone framework history has been recorded yet.")
        else:
            selectable_dataframe(
                framework_history.drop(columns=["details"], errors="ignore"),
                key=f"fishbone_framework_history_{project_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
    with uses_history_tab:
        uses_history = audit_history(
            project_id, "Fishbone part assignments", limit=50
        )
        if uses_history.empty:
            st.caption("No Fishbone use history has been recorded yet.")
        else:
            selectable_dataframe(
                uses_history.drop(columns=["details"], errors="ignore"),
                key=f"fishbone_uses_history_{project_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
