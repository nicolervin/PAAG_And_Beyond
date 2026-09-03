import json
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from utils.assembly_grid import assembly_grid as render_assembly_grid
from utils.clipboard_image import as_uploaded_file, clipboard_image, decode_clipboard_image
from utils.component_payload import is_empty_unsaved_grid_category
from utils.scope_ui import page_title_with_scope
from utils.store import (
    add_assembly_image,
    assign_parts_to_section,
    assembly_bom_components,
    assembly_catalog_delete_impact,
    assembly_catalog_rows,
    assembly_grid_categories,
    assembly_grid_feature_visibility,
    assembly_grid_model_mappings,
    assembly_images,
    assembly_sections,
    audit_history,
    complexity_features,
    complexity_tree,
    create_part_and_assign_to_section,
    delete_assembly_grid_categories,
    delete_assembly_catalog_rows,
    delete_assembly_images,
    fishbone_part_assignments,
    project_models,
    record_audit_event,
    save_assembly_bom_components,
    save_assembly_catalog_rows,
    save_assembly_grid_model_mappings,
    save_assembly_grid_section,
    search_parts_and_fishbone,
    set_assembly_image,
)
from utils.table_filters import (
    apply_pending_table_editor_reset,
    filter_table,
    merge_filtered_edits,
    request_table_editor_reset,
)
from utils.table_ui import (
    dataframe_to_excel,
    direct_entry_editor_rows,
    drop_untouched_new_rows,
    editable_table_footer,
    editable_table_heading,
    format_clean_number,
    native_selected_rows,
    part_number_cell_style,
    selectable_dataframe,
    standard_details_column_config,
    table_has_unsaved_changes,
)


project_id = st.session_state.get("project_id")
page_title_with_scope("Assembly grid", scope="project")
st.caption(
    "Map named EBOM categories to real assembly numbers by official model, then open Details "
    "for the full assembly editor."
)
if not project_id:
    st.stop()

catalog_editor_key = f"assembly_catalog_editor_{project_id}"
selected_assembly_key = f"assemblies_selected_id_{project_id}"
apply_pending_table_editor_reset(catalog_editor_key)

catalog = assembly_catalog_rows(project_id)
sections = assembly_sections(project_id)
section_name_by_id = (
    {str(row["id"]): str(row["name"]) for _, row in sections.iterrows()}
    if not sections.empty else {}
)
section_id_by_name = {name: section_id for section_id, name in section_name_by_id.items()}


def _component_event(component_key: str, event_name: str) -> dict:
    state = st.session_state.get(component_key, {}) or {}
    value = state.get(event_name) if hasattr(state, "get") else getattr(state, event_name, None)
    return dict(value or {})


if sections.empty:
    st.info("Create at least one Fishbone section before building an assembly grid.")
else:
    selected_section_id = st.selectbox(
        "Fishbone section",
        sections["id"].astype(str).tolist(),
        format_func=lambda value: section_name_by_id.get(value, value),
        key=f"assembly_grid_section_{project_id}",
        help="Each grid category is built in this Fishbone section.",
    )
    saved_categories = assembly_grid_categories(project_id, selected_section_id)
    saved_section_mappings = assembly_grid_model_mappings(project_id, selected_section_id)
    saved_all_mappings = assembly_grid_model_mappings(project_id)
    models = complexity_tree(project_id)
    model_definitions = {
        str(row["id"]): dict(row)
        for row in project_models(project_id).to_dict("records")
    }
    active_model_ids = [
        str(model_id)
        for model_id, row in model_definitions.items()
        if bool(row.get("active", True))
    ]
    model_labels = {
        model_id: (
            f"{model_definitions[model_id].get('model_number', '')} · "
            f"{model_definitions[model_id].get('display_name', '')}".rstrip(" ·")
        )
        for model_id in active_model_ids
    }
    visible_model_ids = st.multiselect(
        "Visible official models",
        active_model_ids,
        default=active_model_ids,
        format_func=lambda value: model_labels.get(value, value),
        key=f"assembly_grid_visible_models_{project_id}_{selected_section_id}",
        help="This affects display only. Hidden models and their saved mappings are preserved.",
    )

    features = complexity_features(project_id)
    active_features = (
        features.loc[features["active"].fillna(1).astype(bool)].copy()
        if not features.empty else features
    )
    feature_preferences = assembly_grid_feature_visibility(
        project_id, selected_section_id
    )
    preference_by_id = (
        {
            str(row["feature_id"]): bool(row["is_visible"])
            for _, row in feature_preferences.iterrows()
        }
        if not feature_preferences.empty else {}
    )
    feature_label_by_id = {
        str(row["id"]): f"{row['category']} · {row['name']}"
        for _, row in active_features.iterrows()
    }
    default_visible_features = [
        feature_id for feature_id in feature_label_by_id
        if preference_by_id.get(feature_id, True)
    ]
    visible_feature_ids = st.multiselect(
        "Visible feature headers",
        list(feature_label_by_id),
        default=default_visible_features,
        format_func=lambda value: feature_label_by_id.get(value, value),
        key=f"assembly_grid_visible_features_{project_id}_{selected_section_id}",
        help="Only active features can appear. This display preference is saved per Fishbone section.",
    )
    missing_part_key = f"assembly_grid_missing_part_{project_id}_{selected_section_id}"
    if st.button(
        "Find or add a missing part",
        icon=":material/search:",
        type="tertiary",
        key=f"assembly_grid_find_part_{project_id}_{selected_section_id}",
    ):
        st.session_state[missing_part_key] = True

    @st.dialog(
        "Find or add a Fishbone part",
        width="large",
        dismissible=False,
        icon=":material/search:",
    )
    def assembly_grid_missing_part_dialog() -> None:
        st.caption(
            f"Components must reference an exact Fishbone use in "
            f"{section_name_by_id.get(selected_section_id, selected_section_id)}. "
            "Search the whole Parts Catalog before creating a new part."
        )
        find_tab, add_tab = st.tabs(["Find existing", "Add new part"])
        with find_tab:
            search_text = st.text_input(
                "Search by part number or Part Name",
                key=f"assembly_grid_part_search_{project_id}_{selected_section_id}",
            ).strip()
            if len(search_text) < 2:
                st.info("Enter at least two characters to search.")
            else:
                matches = search_parts_and_fishbone(project_id, search_text)
                if matches.empty:
                    st.warning("No similar catalog parts were found. Use Add new part if this is new.")
                else:
                    summary = matches[["part_id", "part_number", "description", "revision"]].drop_duplicates()
                    selectable_dataframe(
                        summary.drop(columns=["part_id"]),
                        key=f"assembly_grid_part_matches_{project_id}_{selected_section_id}",
                        hide_index=True,
                        column_config={
                            "part_number": "Part number",
                            "description": st.column_config.TextColumn("Part Name", width="large"),
                            "revision": "Revision",
                        },
                    )
                    labels = {
                        str(row["part_id"]): f"{row['part_number']} · {row['description']}"
                        for _, row in summary.iterrows()
                    }
                    part_id = st.selectbox(
                        "Part to place",
                        list(labels),
                        format_func=lambda value: labels.get(value, value),
                        key=f"assembly_grid_part_choice_{project_id}_{selected_section_id}",
                    )
                    current_uses = matches.loc[
                        matches["part_id"].astype(str).eq(str(part_id))
                        & matches["section_id"].fillna("").astype(str).eq(selected_section_id)
                    ]
                    if current_uses.empty:
                        placement = st.container(horizontal=True, vertical_alignment="bottom")
                        quantity = placement.number_input(
                            "Fishbone quantity", value=1.0, step=0.01, format="%g",
                            key=f"assembly_grid_place_quantity_{project_id}_{selected_section_id}",
                        )
                        use_description = placement.text_input(
                            "Use / installation location",
                            key=f"assembly_grid_place_use_{project_id}_{selected_section_id}",
                        )
                        if st.button(
                            "Place in this Fishbone section",
                            type="primary",
                            icon=":material/account_tree:",
                            key=f"assembly_grid_place_part_{project_id}_{selected_section_id}",
                        ):
                            try:
                                assign_parts_to_section(
                                    project_id, [str(part_id)], selected_section_id,
                                    use_description,
                                    allow_additional_use=True,
                                    quantities_by_part={str(part_id): float(quantity)},
                                )
                                record_audit_event(
                                    project_id, "Fishbone part assignments", "Place part", 1,
                                    st.session_state.get("current_editor", ""),
                                    {"part_id": str(part_id), "section_id": selected_section_id},
                                )
                                st.session_state.pop(missing_part_key, None)
                                st.toast("Placed the part; it is now available in the grid", icon=":material/check_circle:")
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))
                    else:
                        st.success(
                            f"This part already has {len(current_uses)} Fishbone use(s) in this section. "
                            "Close this dialog and choose the exact use in the grid."
                        )
        with add_tab:
            st.caption("Create the Parts Catalog record and its first Fishbone use together.")
            part_number = st.text_input(
                "Part number", key=f"assembly_grid_new_part_number_{project_id}_{selected_section_id}"
            )
            part_name = st.text_input(
                "Part Name", key=f"assembly_grid_new_part_name_{project_id}_{selected_section_id}"
            )
            revision = st.text_input(
                "Revision", value="0", key=f"assembly_grid_new_part_revision_{project_id}_{selected_section_id}"
            )
            new_row = st.container(horizontal=True, vertical_alignment="bottom")
            quantity = new_row.number_input(
                "Fishbone quantity", value=1.0, step=0.01, format="%g",
                key=f"assembly_grid_new_part_quantity_{project_id}_{selected_section_id}",
            )
            use_description = new_row.text_input(
                "Use / installation location",
                key=f"assembly_grid_new_part_use_{project_id}_{selected_section_id}",
            )
            notes = st.text_area(
                "Part notes", key=f"assembly_grid_new_part_notes_{project_id}_{selected_section_id}"
            )
            if st.button(
                "Add part and place it",
                type="primary",
                icon=":material/add_circle:",
                key=f"assembly_grid_create_part_{project_id}_{selected_section_id}",
            ):
                try:
                    part_id, assignment_id, updated_at = create_part_and_assign_to_section(
                        project_id,
                        selected_section_id,
                        {
                            "part_number": part_number,
                            "description": part_name,
                            "revision": revision,
                            "model_applicability": "All",
                            "notes": notes,
                        },
                        float(quantity),
                        use_description,
                    )
                    editor = st.session_state.get("current_editor", "")
                    record_audit_event(
                        project_id, "Parts", "Create from Assembly grid", 1, editor,
                        {"part_id": part_id, "updated_at": updated_at},
                    )
                    record_audit_event(
                        project_id, "Fishbone part assignments", "Place new part", 1, editor,
                        {"part_id": part_id, "assignment_id": assignment_id,
                         "section_id": selected_section_id, "updated_at": updated_at},
                    )
                    st.session_state.pop(missing_part_key, None)
                    st.toast("Added and placed the new part", icon=":material/check_circle:")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        if st.button(
            "Cancel", icon=":material/close:",
            key=f"assembly_grid_missing_part_cancel_{project_id}_{selected_section_id}",
        ):
            st.session_state.pop(missing_part_key, None)
            st.rerun()

    if st.session_state.get(missing_part_key):
        assembly_grid_missing_part_dialog()

    value_by_model_feature = {}
    if not models.empty:
        for _, row in models.iterrows():
            for feature_id in feature_label_by_id:
                value_by_model_feature[(str(row["model_id"]), feature_id)] = row.get(feature_id)
    component_cache: dict[str, list[dict]] = {}
    for assembly_id in (
        saved_section_mappings.get("assembly_id", pd.Series(dtype="string"))
        .dropna().astype(str).unique().tolist()
    ):
        assembly_components = assembly_bom_components(project_id, assembly_id)
        component_cache[assembly_id] = [
            {
                "id": str(component["id"]),
                "fishbone_assignment_id": str(component["fishbone_assignment_id"]),
                "part_number": (
                    ""
                    if pd.isna(component.get("part_number"))
                    else str(component.get("part_number"))
                ),
                "part_name": (
                    ""
                    if pd.isna(component.get("part_name"))
                    else str(component.get("part_name"))
                ),
                "quantity": float(component["quantity"]),
            }
            for _, component in assembly_components.iterrows()
        ]
    grid_uses = fishbone_part_assignments(project_id)
    grid_uses = (
        grid_uses.loc[grid_uses["section_id"].astype(str).eq(selected_section_id)].copy()
        if not grid_uses.empty else grid_uses
    )
    mapping_by_cell = {
        (str(row["category_id"]), str(row["model_id"])): dict(row)
        for _, row in saved_section_mappings.iterrows()
    } if not saved_section_mappings.empty else {}
    initial_grid_draft: list[dict] = []
    for _, category in saved_categories.iterrows():
        cells = {}
        for model_id in active_model_ids:
            mapping = mapping_by_cell.get((str(category["id"]), model_id), {})
            assembly_number = str(mapping.get("assembly_number") or "")
            cells[model_id] = {
                "mapping_id": str(mapping.get("id") or ""),
                "assembly_id": str(mapping.get("assembly_id") or ""),
                "assembly_number": assembly_number,
                "components": component_cache.get(str(mapping.get("assembly_id") or ""), []),
            }
        initial_grid_draft.append(
            {
                "id": str(category["id"]),
                "ebom_name": str(category["ebom_name"]),
                "display_name": str(category["display_name"]),
                "installed_section_id": str(category.get("installed_section_id") or ""),
                "sequence": int(category.get("sequence") or 10),
                "cells": cells,
            }
        )

    grid_key = f"assembly_grid_component_v5_{project_id}_{selected_section_id}"
    pending_category_key = f"assembly_grid_pending_category_delete_{project_id}"
    pending_mapping_key = f"assembly_grid_pending_mapping_clear_{project_id}"
    pending_component_key = f"assembly_grid_pending_component_delete_{project_id}"

    def grid_draft() -> list[dict]:
        state = st.session_state.get(grid_key, {}) or {}
        return list(state.get("draft", initial_grid_draft))

    def set_grid_draft(rows: list[dict]) -> None:
        state = st.session_state.get(grid_key, {}) or {}
        state["draft"] = rows
        st.session_state[grid_key] = state

    def on_grid_draft_change() -> None:
        return None

    def on_grid_details_change() -> None:
        event = _component_event(grid_key, "details")
        if event.get("assembly_id"):
            st.session_state[selected_assembly_key] = str(event["assembly_id"])

    def on_grid_category_delete_change() -> None:
        event = _component_event(grid_key, "delete_category")
        if event:
            st.session_state[pending_category_key] = event

    def on_grid_mapping_clear_change() -> None:
        event = _component_event(grid_key, "clear_mapping")
        if event:
            st.session_state[pending_mapping_key] = event

    def on_grid_component_delete_change() -> None:
        event = _component_event(grid_key, "delete_component")
        if event:
            st.session_state[pending_component_key] = event

    @st.dialog("Delete assembly-grid category?", dismissible=False)
    def confirm_grid_category_delete() -> None:
        pending = dict(st.session_state.get(pending_category_key, {}))
        category_id = str(pending.get("category_id") or "")
        st.warning(
            f"Delete category {pending.get('display_name') or 'Untitled category'} and all of "
            "its model mappings? Every real assembly record, mini-BOM, feature rule, image, "
            "nesting relationship, and uploaded file remains unchanged."
        )
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_grid_category_delete_{project_id}"):
            st.session_state.pop(pending_category_key, None)
            st.rerun()
        if actions.button(
            "Delete category", type="primary", icon=":material/delete:",
            key=f"destructive_grid_category_delete_{project_id}",
        ):
            if category_id:
                result = delete_assembly_grid_categories(
                    project_id, selected_section_id, [category_id]
                )
                record_audit_event(
                    project_id, "Assembly grid categories", "Delete category",
                    result["deleted_count"], st.session_state.get("current_editor", ""), result,
                )
                st.session_state.pop(grid_key, None)
            else:
                rows = grid_draft()
                index = int(pending.get("category_index", -1))
                if 0 <= index < len(rows):
                    rows.pop(index)
                    set_grid_draft(rows)
            st.session_state.pop(pending_category_key, None)
            st.toast("Deleted assembly-grid category", icon=":material/delete:")
            st.rerun()

    @st.dialog("Clear model mapping?", dismissible=False)
    def confirm_grid_mapping_clear() -> None:
        pending = dict(st.session_state.get(pending_mapping_key, {}))
        st.warning(
            f"Clear the mapping to assembly {pending.get('assembly_number') or 'this assembly'}? "
            "Only the model-to-assembly link is removed. The real assembly and all of its "
            "mini-BOM, rules, images, nesting, and uploaded files remain unchanged."
        )
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_grid_mapping_clear_{project_id}"):
            st.session_state.pop(pending_mapping_key, None)
            st.rerun()
        if actions.button(
            "Clear mapping", type="primary", icon=":material/link_off:",
            key=f"destructive_grid_mapping_clear_{project_id}",
        ):
            mapping_id = str(pending.get("mapping_id") or "")
            if mapping_id:
                retained = saved_all_mappings.loc[
                    ~saved_all_mappings["id"].astype(str).eq(mapping_id)
                ].to_dict("records")
                result = save_assembly_grid_model_mappings(project_id, retained)
                record_audit_event(
                    project_id, "Assembly grid mappings", "Clear mapping", 1,
                    st.session_state.get("current_editor", ""),
                    {"mapping_id": mapping_id, "assembly_id": pending.get("assembly_id"),
                     "remaining_count": result["count"]},
                )
            st.session_state.pop(pending_mapping_key, None)
            st.session_state.pop(grid_key, None)
            st.toast("Cleared model mapping; assembly preserved", icon=":material/link_off:")
            st.rerun()

    @st.dialog("Delete mini-BOM component?", dismissible=False)
    def confirm_grid_component_delete() -> None:
        pending = dict(st.session_state.get(pending_component_key, {}))
        st.warning(
            f"Delete component {pending.get('part_number') or ''} from this assembly mini-BOM? "
            "The Fishbone use and Parts Catalog record remain unchanged."
        )
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_grid_component_delete_{project_id}"):
            st.session_state.pop(pending_component_key, None)
            st.rerun()
        if actions.button(
            "Delete component", type="primary", icon=":material/delete:",
            key=f"destructive_grid_component_delete_{project_id}",
        ):
            assembly_id = str(pending.get("assembly_id") or "")
            component_id = str(pending.get("component_id") or "")
            if component_id:
                remaining = assembly_bom_components(project_id, assembly_id)
                remaining = remaining.loc[~remaining["id"].astype(str).eq(component_id)]
                result = save_assembly_bom_components(
                    project_id, assembly_id, remaining.to_dict("records")
                )
                record_audit_event(
                    project_id, "Assembly mini-BOM", "Delete components", 1,
                    st.session_state.get("current_editor", ""),
                    {"assembly_id": assembly_id, "component_id": component_id,
                     "remaining_count": result["count"]},
                )
                st.session_state.pop(grid_key, None)
            else:
                rows = grid_draft()
                component_index = int(pending.get("component_index", -1))
                for category in rows:
                    for cell in dict(category.get("cells") or {}).values():
                        if str(cell.get("assembly_id") or "") != assembly_id:
                            continue
                        components = list(cell.get("components") or [])
                        if 0 <= component_index < len(components):
                            components.pop(component_index)
                        cell["components"] = components
                set_grid_draft(rows)
            st.session_state.pop(pending_component_key, None)
            st.toast("Deleted mini-BOM component", icon=":material/delete:")
            st.rerun()

    if st.session_state.get(pending_category_key):
        confirm_grid_category_delete()
    if st.session_state.get(pending_mapping_key):
        confirm_grid_mapping_clear()
    if st.session_state.get(pending_component_key):
        confirm_grid_component_delete()

    model_payload = [
        {
            "id": model_id,
            "model_number": model_definitions[model_id].get("model_number", ""),
            "display_name": model_definitions[model_id].get("display_name", ""),
            "features": {
                feature_id: value_by_model_feature.get((model_id, feature_id))
                for feature_id in visible_feature_ids
            },
        }
        for model_id in visible_model_ids
    ]
    grid_use_payload = []
    for _, row in grid_uses.iterrows():
        part_number = str(row["part_number"])
        part_name = "" if pd.isna(row.get("description")) else str(row.get("description"))
        use_description = (
            ""
            if pd.isna(row.get("use_description"))
            else str(row.get("use_description") or "")
        )
        grid_use_payload.append(
            {
                "id": str(row["id"]),
                "part_number": part_number,
                "part_name": part_name,
                "quantity": float(row["quantity"]),
                "label": (
                    f"{part_number} · {part_name or 'No Part Name'} · "
                    f"{use_description or 'No use description'} · "
                    f"Fishbone qty {format_clean_number(row['quantity'])}"
                ),
            }
        )
    render_assembly_grid(
        key=grid_key,
        draft=initial_grid_draft,
        models=model_payload,
        features=[
            {"id": feature_id, "label": feature_label_by_id[feature_id]}
            for feature_id in visible_feature_ids
        ],
        sections=[
            {"id": str(row["id"]), "name": str(row["name"])}
            for _, row in sections.iterrows()
        ],
        uses=grid_use_payload,
        on_draft_change=on_grid_draft_change,
        on_details_change=on_grid_details_change,
        on_delete_category_change=on_grid_category_delete_change,
        on_clear_mapping_change=on_grid_mapping_clear_change,
        on_delete_component_change=on_grid_component_delete_change,
    )
    current_draft = grid_draft()
    draft_dirty = json.dumps(current_draft, sort_keys=True, default=str) != json.dumps(
        initial_grid_draft, sort_keys=True, default=str
    )
    visibility_dirty = set(visible_feature_ids) != set(default_visible_features)
    grid_actions = editable_table_footer(
        editor_key=f"assembly_grid_footer_state_{project_id}",
        key_prefix=f"assembly_grid_{project_id}_{selected_section_id}",
        additional_unsaved_changes=draft_dirty or visibility_dirty,
    )
    if grid_actions.undo:
        st.session_state.pop(grid_key, None)
        st.session_state[
            f"assembly_grid_visible_features_{project_id}_{selected_section_id}"
        ] = default_visible_features
        st.toast("Discarded unsaved assembly-grid changes", icon=":material/undo:")
        st.rerun()
    if grid_actions.save_and_refresh:
        try:
            current_draft = [
                category
                for category in current_draft
                if not is_empty_unsaved_grid_category(category)
            ]
            prepared_categories = []
            category_id_map = {}
            for index, category in enumerate(current_draft):
                category_id = str(category.get("id") or uuid4())
                category_id_map[index] = category_id
                prepared_categories.append({**category, "id": category_id})
            complete_mappings = (
                saved_all_mappings.loc[
                    ~saved_all_mappings["section_id"].astype(str).eq(selected_section_id)
                ].to_dict("records")
                if not saved_all_mappings.empty else []
            )
            if not saved_section_mappings.empty:
                complete_mappings.extend(
                    saved_section_mappings.loc[
                        ~saved_section_mappings["model_id"].astype(str).isin(active_model_ids)
                    ].to_dict("records")
                )
            component_rows_by_assembly = {}
            for index, category in enumerate(prepared_categories):
                for model_id, cell in dict(category.get("cells") or {}).items():
                    assembly_number = str(cell.get("assembly_number") or "").strip()
                    if not assembly_number:
                        continue
                    assembly_id = str(cell.get("assembly_id") or "")
                    complete_mappings.append(
                        {
                            "id": str(cell.get("mapping_id") or ""),
                            "category_id": category_id_map[index],
                            "model_id": str(model_id),
                            "assembly_id": assembly_id,
                            "assembly_number": assembly_number,
                        }
                    )
                    if assembly_id and cell.get("components") is not None:
                        component_rows_by_assembly[assembly_id] = list(cell["components"])
            result = save_assembly_grid_section(
                project_id,
                selected_section_id,
                [{key: value for key, value in category.items() if key != "cells"}
                 for category in prepared_categories],
                complete_mappings,
                [
                    {"feature_id": feature_id, "is_visible": feature_id in visible_feature_ids}
                    for feature_id in feature_label_by_id
                ],
                component_rows_by_assembly,
            )
            editor = st.session_state.get("current_editor", "")
            record_audit_event(
                project_id, "Assembly grid categories", "Save & Refresh",
                result["categories"]["count"], editor,
                {"section_id": selected_section_id,
                 "installed_section_sync_changes": result["categories"]["installed_section_sync_changes"]},
            )
            record_audit_event(
                project_id, "Assembly grid mappings", "Save & Refresh",
                result["mappings"]["count"], editor,
                {"section_id": selected_section_id,
                 "created_assemblies": result["mappings"]["created_assemblies"],
                 "renamed_assemblies": result["mappings"]["renamed_assemblies"]},
            )
            record_audit_event(
                project_id, "Assembly grid feature visibility", "Save & Refresh",
                result["feature_visibility"]["count"], editor,
                {"section_id": selected_section_id,
                 "hidden_feature_ids": result["feature_visibility"]["hidden_feature_ids"]},
            )
            if result["components"]:
                record_audit_event(
                    project_id, "Assembly mini-BOM", "Grid Save & Refresh",
                    sum(item["count"] for item in result["components"].values()), editor,
                    {"section_id": selected_section_id,
                     "assembly_ids": list(result["components"])},
                )
            st.session_state.pop(grid_key, None)
            st.toast("Saved and refreshed the assembly grid", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

st.divider()
st.caption(
    "The full Task 04 catalog remains below for assembly metadata, nesting, deletion, "
    "images, and mini-BOM additions. Grid-mapped Built and Installed sections "
    "are controlled by their category."
)


def empty_catalog_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": pd.Series(dtype="string"),
            "assembly_number": pd.Series(dtype="string"),
            "name": pd.Series(dtype="string"),
            "make_buy": pd.Series(dtype="string"),
            "built_section_id": pd.Series(dtype="string"),
            "installed_section_id": pd.Series(dtype="string"),
            "parent_id": pd.Series(dtype="string"),
            "active": pd.Series(dtype="bool"),
            "notes": pd.Series(dtype="string"),
        }
    )


def save_catalog_records(records: list[dict]) -> None:
    result = save_assembly_catalog_rows(project_id, records)
    record_audit_event(
        project_id,
        "Assemblies catalog",
        "Save & Refresh",
        result["count"],
        st.session_state.get("current_editor", ""),
        {
            "assembly_ids": result["assembly_ids"],
            "make_buy_changes": result["make_buy_changes"],
            "nesting_mismatch_count": len(result["mismatch_warnings"]),
            "updated_at": result["updated_at"],
        },
    )
    st.session_state.pop(f"assembly_catalog_pending_save_{project_id}", None)
    request_table_editor_reset(catalog_editor_key)
    st.toast(f"Saved {result['count']} assemblies", icon=":material/check_circle:")
    st.rerun()


editable_table_heading("Full assembly catalog and deletion")
st.caption(
    "Built section is where component work occurs. Installed section is where the completed "
    "assembly will eventually be available to downstream Process planning."
)
if sections.empty:
    st.info("Create at least one Fishbone section before adding an assembly.")
else:
    catalog_source = catalog.copy() if not catalog.empty else empty_catalog_rows()
    catalog_source["make_buy"] = (
        catalog_source.get("make_buy", pd.Series(dtype="string"))
        .fillna("")
        .astype("string")
        .replace("", pd.NA)
    )
    catalog_source["make_buy_filter"] = catalog_source["make_buy"].fillna("Unclassified")
    assembly_number_by_id = (
        {str(row["id"]): str(row["assembly_number"]) for _, row in catalog.iterrows()}
        if not catalog.empty else {}
    )
    assembly_id_by_number = {
        number: assembly_id for assembly_id, number in assembly_number_by_id.items()
    }
    catalog_source["built_section"] = catalog_source.get(
        "built_section_id", pd.Series(dtype="string")
    ).map(section_name_by_id)
    catalog_source["installed_section"] = catalog_source.get(
        "installed_section_id", pd.Series(dtype="string")
    ).map(section_name_by_id).fillna("Not assigned")
    catalog_source["parent_assembly"] = catalog_source.get(
        "parent_id", pd.Series(dtype="string")
    ).map(assembly_number_by_id).fillna("No parent")
    catalog_source["details"] = ":material/open_in_new: Details"
    catalog_source["warnings"] = catalog_source.apply(
        lambda row: " · ".join(
            message for message in [
                (
                    f"{int(row.get('component_mismatch_count') or 0)} mini-BOM mismatch(es)"
                    if int(row.get("component_mismatch_count") or 0) else ""
                ),
                (
                    f"{int(row.get('stale_rule_count') or 0)} stale rule(s)"
                    if int(row.get("stale_rule_count") or 0) else ""
                ),
            ] if message
        ),
        axis=1,
    )
    full_catalog_source = catalog_source.copy()
    visible_catalog = filter_table(
        catalog_source,
        key=f"assembly_catalog_filters_{project_id}",
        dropdown_columns=["make_buy_filter", "built_section", "installed_section", "active"],
        search_columns=["assembly_number", "name", "notes"],
        labels={
            "built_section": "Built section",
            "installed_section": "Installed section",
            "make_buy_filter": "Make / buy",
            "active": "Active",
        },
        reset_widget_keys=[catalog_editor_key],
    )
    visible_catalog = direct_entry_editor_rows(
        visible_catalog,
        editor_key=catalog_editor_key,
        sort_columns=[
            "assembly_number", "name", "make_buy", "built_section", "installed_section"
        ],
    )

    def open_assembly_details() -> None:
        click = st.session_state.get("assembly_catalog_details_action") or {}
        if 0 <= int(click.get("row", -1)) < len(visible_catalog):
            assembly_id = str(visible_catalog.iloc[int(click["row"])].get("id") or "")
            if assembly_id:
                st.session_state[selected_assembly_key] = assembly_id

    edited_catalog = st.data_editor(
        visible_catalog,
        key=catalog_editor_key,
        hide_index=True,
        num_rows="dynamic",
        disabled=[
            "id", "details", "warnings", "component_count", "rule_count",
            "supplemental_image_count", "component_mismatch_count", "stale_rule_count",
        ],
        column_order=[
            "details", "assembly_number", "name", "make_buy", "built_section",
            "installed_section", "parent_assembly", "active", "notes", "warnings",
        ],
        column_config={
            "id": None,
            "details": standard_details_column_config(
                on_click=open_assembly_details, key="assembly_catalog_details_action"
            ),
            "assembly_number": st.column_config.TextColumn(
                "Assembly number", required=True, pinned=True
            ),
            "name": st.column_config.TextColumn("Assembly name", required=True, width="large"),
            "make_buy": st.column_config.SelectboxColumn(
                "Make / buy",
                options=["Make", "Buy"],
                help=(
                    "Make means the assembly is produced internally. Buy means it is obtained "
                    "as a complete assembly. This classification applies across every planning "
                    "scenario."
                ),
            ),
            "built_section": st.column_config.SelectboxColumn(
                "Built section",
                options=list(section_id_by_name),
                required=True,
                help="The Fishbone section containing the part uses eligible for this assembly's mini-BOM.",
            ),
            "installed_section": st.column_config.SelectboxColumn(
                "Installed section",
                options=["Not assigned", *list(section_id_by_name)],
                required=True,
                help=(
                    "The Fishbone section where the completed assembly is installed. A mapped "
                    "assembly may show Not assigned until its grid category is assigned."
                ),
            ),
            "parent_assembly": st.column_config.SelectboxColumn(
                "Parent assembly", options=["No parent", *list(assembly_id_by_number)]
            ),
            "active": st.column_config.CheckboxColumn("Active", default=True),
            "notes": st.column_config.TextColumn("Notes", width="large"),
            "warnings": st.column_config.TextColumn("Review", width="large"),
        },
    )
    catalog_actions = editable_table_footer(
        editor_key=catalog_editor_key,
        key_prefix="assembly_catalog",
        native_row_selection=True,
    )
    if catalog_actions.undo:
        st.session_state.pop(catalog_editor_key, None)
        st.toast("Discarded unsaved assembly edits", icon=":material/undo:")
        st.rerun()

    selected_catalog_rows = native_selected_rows(
        visible_catalog, editor_key=catalog_editor_key
    )
    catalog_delete_key = f"assembly_catalog_pending_delete_{project_id}"
    if not selected_catalog_rows.empty and not table_has_unsaved_changes(
        catalog_editor_key, native_row_selection=True
    ):
        st.session_state[catalog_delete_key] = selected_catalog_rows["id"].astype(str).tolist()

    @st.dialog("Delete selected assemblies?", width="large")
    def confirm_catalog_delete() -> None:
        pending_ids = st.session_state.get(catalog_delete_key, [])
        try:
            impact = assembly_catalog_delete_impact(project_id, pending_ids)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.warning(
            f"Delete {impact['selected_count']} selected assembly record(s)? "
            f"The complete tree contains {impact['descendant_count']} child assembly record(s)."
        )
        st.markdown(
            f"- **{impact['component_count']}** mini-BOM row(s)\n"
            f"- **{impact['rule_count']}** feature-rule row(s)\n"
            f"- **{impact['primary_image_count']}** primary image(s)\n"
            f"- **{impact['supplemental_image_count']}** supplemental image row(s)\n"
            f"- **{impact['grid_mapping_count']}** direct assembly-grid mapping(s)\n"
            f"- **{impact['image_file_count']}** owned uploaded image file(s)\n"
            f"- **{impact['policy_count']}** dormant scenario-policy row(s)\n"
            f"- **{impact['material_option_count']}** dormant material-option row(s)\n"
            f"- **{impact['target_assembly_link_count']}** dormant target-assembly link(s)"
        )
        level_actions = {}
        for depth, level_rows in sorted(impact["levels"].items()):
            labels = ", ".join(str(row["assembly_number"]) for row in level_rows)
            if depth == 0:
                st.caption(f"Selected for deletion: {labels}")
                continue
            level_actions[depth] = st.selectbox(
                f"Child level {depth}: {labels}",
                ["Move to grandparent", "Delete entirely", "Become unassigned"],
                key=f"assembly_delete_level_{project_id}_{depth}",
            )
        action_row = st.container(horizontal=True)
        if action_row.button("Cancel", key=f"cancel_assembly_delete_{project_id}"):
            st.session_state.pop(catalog_delete_key, None)
            request_table_editor_reset(catalog_editor_key)
            st.rerun()
        if action_row.button(
            "Delete assemblies",
            type="primary",
            icon=":material/delete:",
            key=f"destructive_confirm_assembly_delete_{project_id}",
        ):
            result = delete_assembly_catalog_rows(project_id, pending_ids, level_actions)
            record_audit_event(
                project_id,
                "Assemblies catalog",
                "Bulk delete",
                result["deleted_count"],
                st.session_state.get("current_editor", ""),
                {
                    "selected_ids": pending_ids,
                    "deleted_count": result["deleted_count"],
                    "level_actions": level_actions,
                    "component_count": result["component_count"],
                    "rule_count": result["rule_count"],
                    "policy_count": result["policy_count"],
                },
            )
            if st.session_state.get(selected_assembly_key) in result["affected_ids"]:
                st.session_state.pop(selected_assembly_key, None)
            st.session_state.pop(catalog_delete_key, None)
            request_table_editor_reset(catalog_editor_key)
            st.toast(f"Deleted {result['deleted_count']} assemblies", icon=":material/delete:")
            st.rerun()

    if st.session_state.get(catalog_delete_key):
        confirm_catalog_delete()

    merged_catalog = merge_filtered_edits(
        full_catalog_source, visible_catalog, edited_catalog
    )
    merged_catalog = drop_untouched_new_rows(
        merged_catalog, identifying_columns=["assembly_number", "name"]
    )
    catalog_records = []
    for _, row in merged_catalog.iterrows():
        row_id = "" if pd.isna(row.get("id")) else str(row.get("id") or "").strip()
        catalog_records.append(
            {
                "id": row_id or str(uuid4()),
                "assembly_number": str(row.get("assembly_number") or "").strip(),
                "name": str(row.get("name") or "").strip(),
                "make_buy": (
                    "" if pd.isna(row.get("make_buy"))
                    else str(row.get("make_buy") or "").strip()
                ),
                "built_section_id": section_id_by_name.get(str(row.get("built_section") or "")),
                "installed_section_id": section_id_by_name.get(
                    str(row.get("installed_section") or "")
                ),
                "parent_id": assembly_id_by_number.get(
                    str(row.get("parent_assembly") or "")
                ),
                "active": True if pd.isna(row.get("active")) else bool(row.get("active")),
                "notes": str(row.get("notes") or "").strip(),
            }
        )

    @st.dialog("Review assembly nesting", width="large")
    def confirm_catalog_mismatch_save() -> None:
        pending = st.session_state.get(f"assembly_catalog_pending_save_{project_id}", [])
        by_id = {row["id"]: row for row in pending}
        mismatches = []
        for row in pending:
            parent = by_id.get(row.get("parent_id"))
            if parent and row.get("installed_section_id") != parent.get("built_section_id"):
                mismatches.append(
                    f"{row['assembly_number']} is installed in "
                    f"{section_name_by_id.get(row.get('installed_section_id'), 'Unknown')} while "
                    f"parent {parent['assembly_number']} is built in "
                    f"{section_name_by_id.get(parent.get('built_section_id'), 'Unknown')}."
                )
        st.warning("The selected nesting does not match the expected built/installed pattern.")
        for mismatch in mismatches:
            st.write(f"- {mismatch}")
        st.caption("This is a review warning only. You may save the selected parent relationship.")
        actions = st.container(horizontal=True)
        if actions.button("Review table", key=f"review_assembly_nesting_{project_id}"):
            st.session_state.pop(f"assembly_catalog_pending_save_{project_id}", None)
            st.rerun()
        if actions.button(
            "Save anyway",
            type="primary",
            icon=":material/save:",
            key=f"save_assembly_nesting_anyway_{project_id}",
        ):
            save_catalog_records(pending)

    if catalog_actions.save_and_refresh:
        try:
            if not selected_catalog_rows.empty:
                raise ValueError("Clear selected assembly rows before saving.")
            by_id = {row["id"]: row for row in catalog_records}
            mismatched = any(
                by_id.get(row.get("parent_id"))
                and row.get("installed_section_id")
                != by_id[row["parent_id"]].get("built_section_id")
                for row in catalog_records
            )
            if mismatched:
                st.session_state[f"assembly_catalog_pending_save_{project_id}"] = catalog_records
            else:
                save_catalog_records(catalog_records)
        except ValueError as exc:
            st.error(str(exc))
    if st.session_state.get(f"assembly_catalog_pending_save_{project_id}"):
        confirm_catalog_mismatch_save()

    st.download_button(
        "Export filtered assemblies",
        dataframe_to_excel(
            visible_catalog.drop(columns=["details", "make_buy_filter"], errors="ignore"),
            "Assemblies",
        ),
        file_name="assemblies.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
    )


catalog = assembly_catalog_rows(project_id)
if not catalog.empty:
    valid_ids = set(catalog["id"].astype(str))
    if st.session_state.get(selected_assembly_key) not in valid_ids:
        st.session_state[selected_assembly_key] = str(catalog.iloc[0]["id"])
    assembly_id = str(st.session_state[selected_assembly_key])
    assembly = catalog.loc[catalog["id"].astype(str).eq(assembly_id)].iloc[0].to_dict()
    st.subheader(f"Assembly details · {assembly['assembly_number']} {assembly['name']}")
    images_tab, bom_tab = st.tabs(["Images", "Mini-BOM"])

    with bom_tab:
        st.caption(
            f"Components must come from exact Fishbone uses in Built section: "
            f"{assembly.get('built_section_name') or 'Not assigned'}. Quantities are independent after saving."
        )
        components = assembly_bom_components(project_id, assembly_id)
        if components.empty:
            if str(assembly.get("make_buy") or "") == "Buy":
                st.caption(
                    "No components listed. A Buy assembly may intentionally have an empty mini-BOM."
                )
            elif str(assembly.get("make_buy") or "") == "Make":
                st.caption("No components listed yet.")
            else:
                st.caption("No components listed.")
        all_uses = fishbone_part_assignments(project_id)
        eligible = all_uses.loc[
            all_uses["section_id"].astype(str).eq(str(assembly.get("built_section_id") or ""))
        ].copy() if not all_uses.empty else all_uses
        existing_use_ids = (
            set(components["fishbone_assignment_id"].astype(str))
            if not components.empty else set()
        )
        use_options = eligible.copy()
        if existing_use_ids and not all_uses.empty:
            use_options = pd.concat(
                [use_options, all_uses.loc[all_uses["id"].astype(str).isin(existing_use_ids)]],
                ignore_index=True,
            ).drop_duplicates("id")
        use_label_by_id = {
            str(row["id"]): (
                f"{row['part_number']} · {row.get('use_description') or 'No use description'} "
                f"· Fishbone qty {format_clean_number(row['quantity'])}"
            )
            for _, row in use_options.iterrows()
        }
        use_id_by_label = {label: use_id for use_id, label in use_label_by_id.items()}
        bom_editor_key = f"assembly_bom_editor_{assembly_id}"
        apply_pending_table_editor_reset(bom_editor_key)
        if components.empty:
            bom_source = pd.DataFrame(
                {
                    "id": pd.Series(dtype="string"),
                    "part_number": pd.Series(dtype="string"),
                    "fishbone_use": pd.Series(dtype="string"),
                    "quantity": pd.Series(dtype="float"),
                    "status": pd.Series(dtype="string"),
                }
            )
        else:
            bom_source = components.copy()
            bom_source["fishbone_use"] = bom_source["fishbone_assignment_id"].astype(str).map(
                use_label_by_id
            )
            bom_source["status"] = bom_source["section_mismatch"].map(
                lambda value: "Warning: Fishbone use is outside the Built section" if value else "Current"
            )
        bom_source = direct_entry_editor_rows(
            bom_source,
            editor_key=bom_editor_key,
            sort_columns=["part_number", "fishbone_use", "quantity"],
        )
        styled_bom_source = bom_source.style.map(
            part_number_cell_style, subset=["part_number"]
        )
        edited_bom = st.data_editor(
            styled_bom_source,
            key=bom_editor_key,
            hide_index=True,
            num_rows="dynamic",
            disabled=["id", "part_number", "status"],
            column_order=["part_number", "fishbone_use", "quantity", "status"],
            column_config={
                "id": None,
                "part_number": st.column_config.TextColumn(
                    "Part number", pinned=True
                ),
                "fishbone_use": st.column_config.SelectboxColumn(
                    "Fishbone use", options=list(use_id_by_label), required=True, width="large"
                ),
                "quantity": st.column_config.NumberColumn(
                    "Quantity", step=0.01, format="%g",
                    help="A blank new quantity defaults to the Fishbone quantity when saved.",
                ),
                "status": st.column_config.TextColumn("Review", width="large"),
            },
        )
        bom_actions = editable_table_footer(
            editor_key=bom_editor_key,
            key_prefix=f"assembly_bom_{assembly_id}",
            native_row_selection=True,
        )
        if bom_actions.undo:
            st.session_state.pop(bom_editor_key, None)
            st.rerun()
        selected_bom = native_selected_rows(bom_source, editor_key=bom_editor_key)
        bom_to_save = drop_untouched_new_rows(
            edited_bom, identifying_columns=["fishbone_use"]
        )
        bom_records = [
            {
                "id": "" if pd.isna(row.get("id")) else str(row.get("id") or ""),
                "fishbone_assignment_id": use_id_by_label.get(str(row.get("fishbone_use") or "")),
                "quantity": row.get("quantity"),
            }
            for _, row in bom_to_save.iterrows()
        ]

        @st.dialog("Delete selected mini-BOM rows?")
        def confirm_bom_delete() -> None:
            st.warning(
                f"Delete {len(selected_bom)} selected component row(s) from "
                f"assembly {assembly['assembly_number']}? Fishbone uses remain unchanged."
            )
            actions = st.container(horizontal=True)
            if actions.button("Cancel", key=f"cancel_bom_delete_{assembly_id}"):
                request_table_editor_reset(bom_editor_key)
                st.rerun()
            if actions.button(
                "Delete components", type="primary", icon=":material/delete:",
                key=f"destructive_bom_delete_{assembly_id}",
            ):
                result = save_assembly_bom_components(project_id, assembly_id, bom_records)
                record_audit_event(
                    project_id, "Assembly mini-BOM", "Delete components", len(selected_bom),
                    st.session_state.get("current_editor", ""),
                    {"assembly_id": assembly_id, "remaining_count": result["count"]},
                )
                request_table_editor_reset(bom_editor_key)
                st.rerun()

        if not selected_bom.empty:
            confirm_bom_delete()
        if bom_actions.save_and_refresh:
            try:
                if not selected_bom.empty:
                    raise ValueError("Clear selected mini-BOM rows before saving.")
                result = save_assembly_bom_components(project_id, assembly_id, bom_records)
                record_audit_event(
                    project_id, "Assembly mini-BOM", "Save & Refresh", result["count"],
                    st.session_state.get("current_editor", ""),
                    {"assembly_id": assembly_id, "updated_at": result["updated_at"]},
                )
                request_table_editor_reset(bom_editor_key)
                st.toast("Saved assembly mini-BOM", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


    with images_tab:
        image_path = Path(str(assembly.get("image_path") or ""))
        st.subheader("Primary assembly image")
        if image_path.is_file():
            st.image(str(image_path), caption=str(assembly["assembly_number"]))
        else:
            st.caption("No primary image attached.")
        primary_upload = st.file_uploader(
            "Upload primary assembly image", type=["png", "jpg", "jpeg", "webp"],
            key=f"assembly_primary_upload_{assembly_id}",
        )
        if primary_upload and st.button(
            "Save primary image", type="primary", icon=":material/upload:",
            key=f"save_assembly_primary_{assembly_id}",
        ):
            set_assembly_image(project_id, assembly_id, primary_upload)
            record_audit_event(
                project_id, "Assembly images", "Save primary image", 1,
                st.session_state.get("current_editor", ""), {"assembly_id": assembly_id},
            )
            st.rerun()
        st.caption("Or paste a Windows screenshot; it saves immediately as the primary image.")
        primary_paste = clipboard_image(key=f"assembly_primary_paste_{assembly_id}")
        if getattr(primary_paste, "image", None):
            try:
                payload = decode_clipboard_image(primary_paste.image)
                set_assembly_image(project_id, assembly_id, as_uploaded_file(payload))
                record_audit_event(
                    project_id, "Assembly images", "Paste primary image", 1,
                    st.session_state.get("current_editor", ""), {"assembly_id": assembly_id},
                )
                st.rerun()
            except (OSError, ValueError) as exc:
                st.error(str(exc))
        st.subheader("Supplemental images")
        supplemental = assembly_images(project_id, assembly_id)
        for image in supplemental:
            supplemental_path = Path(str(image["image_path"]))
            if supplemental_path.is_file():
                st.image(str(supplemental_path), caption=image.get("caption") or "Supplemental image")
        extra_caption = st.text_input("Supplemental image caption", key=f"assembly_extra_caption_{assembly_id}")
        extra_upload = st.file_uploader(
            "Upload supplemental image", type=["png", "jpg", "jpeg", "webp"],
            key=f"assembly_extra_upload_{assembly_id}",
        )
        if extra_upload and st.button(
            "Add supplemental image", icon=":material/add_photo_alternate:",
            key=f"add_assembly_extra_{assembly_id}",
        ):
            add_assembly_image(project_id, assembly_id, extra_upload, extra_caption)
            record_audit_event(
                project_id, "Assembly images", "Add supplemental image", 1,
                st.session_state.get("current_editor", ""), {"assembly_id": assembly_id},
            )
            st.rerun()
        st.caption("You can also paste a screenshot as a supplemental image.")
        supplemental_paste = clipboard_image(key=f"assembly_extra_paste_{assembly_id}")
        if getattr(supplemental_paste, "image", None):
            try:
                payload = decode_clipboard_image(supplemental_paste.image)
                add_assembly_image(
                    project_id, assembly_id, as_uploaded_file(payload), extra_caption
                )
                record_audit_event(
                    project_id, "Assembly images", "Paste supplemental image", 1,
                    st.session_state.get("current_editor", ""), {"assembly_id": assembly_id},
                )
                st.rerun()
            except (OSError, ValueError) as exc:
                st.error(str(exc))
        if supplemental:
            image_table = pd.DataFrame(supplemental)[["id", "caption", "created_at"]]
            image_editor_key = f"assembly_image_selection_{assembly_id}"
            apply_pending_table_editor_reset(image_editor_key)
            st.data_editor(
                image_table,
                key=image_editor_key,
                hide_index=True,
                num_rows="delete",
                disabled=list(image_table.columns),
                column_config={"id": None, "caption": "Caption", "created_at": "Added"},
            )
            selected_images = native_selected_rows(
                image_table, editor_key=image_editor_key
            )
            if not selected_images.empty:
                st.session_state[f"assembly_images_pending_delete_{assembly_id}"] = (
                    selected_images["id"].astype(str).tolist()
                )

            @st.dialog("Delete selected assembly images?")
            def confirm_image_delete() -> None:
                pending_key = f"assembly_images_pending_delete_{assembly_id}"
                pending_ids = st.session_state.get(pending_key, [])
                st.warning(
                    f"Delete {len(pending_ids)} supplemental image(s) from "
                    f"assembly {assembly['assembly_number']}? The uploaded files will also be removed."
                )
                actions = st.container(horizontal=True)
                if actions.button("Cancel", key=f"cancel_assembly_image_delete_{assembly_id}"):
                    st.session_state.pop(pending_key, None)
                    request_table_editor_reset(image_editor_key)
                    st.rerun()
                if actions.button(
                    "Delete images", type="primary", icon=":material/delete:",
                    key=f"destructive_confirm_assembly_image_delete_{assembly_id}",
                ):
                    count = delete_assembly_images(
                        project_id, assembly_id, pending_ids
                    )
                    record_audit_event(
                        project_id, "Assembly images", "Delete supplemental images", count,
                        st.session_state.get("current_editor", ""), {"assembly_id": assembly_id},
                    )
                    st.session_state.pop(pending_key, None)
                    request_table_editor_reset(image_editor_key)
                    st.rerun()

            if st.session_state.get(f"assembly_images_pending_delete_{assembly_id}"):
                confirm_image_delete()


with st.expander("History", icon=":material/history:"):
    history_tabs = st.tabs(
        ["Grid categories", "Grid mappings", "Feature visibility", "Catalog", "Mini-BOM", "Images"]
    )
    for tab, table_name in zip(
        history_tabs,
        [
            "Assembly grid categories", "Assembly grid mappings",
            "Assembly grid feature visibility", "Assemblies catalog",
            "Assembly mini-BOM", "Assembly images",
        ],
    ):
        with tab:
            history = audit_history(project_id, table_name, limit=50)
            if history.empty:
                st.caption("No standardized changes recorded yet.")
            else:
                if table_name == "Assemblies catalog":
                    def make_buy_history_summary(raw_details) -> str:
                        try:
                            details = json.loads(str(raw_details or "{}"))
                        except (TypeError, json.JSONDecodeError):
                            return ""
                        summaries = []
                        for change in details.get("make_buy_changes", []):
                            old_value = str(change.get("old_value") or "Unclassified")
                            new_value = str(change.get("new_value") or "Unclassified")
                            summaries.append(
                                f"{change.get('assembly_number') or 'Unknown assembly'}: "
                                f"{old_value} → {new_value}"
                            )
                        return "; ".join(summaries)

                    history = history.copy()
                    history["make_buy_changes"] = history["details"].apply(
                        make_buy_history_summary
                    )
                history_column_config = {
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                }
                if "make_buy_changes" in history.columns:
                    history_column_config["make_buy_changes"] = st.column_config.TextColumn(
                        "Make / buy changes", width="large"
                    )
                selectable_dataframe(
                    history.drop(columns=["details"], errors="ignore"),
                    key=f"assembly_history_{project_id}_{table_name}",
                    hide_index=True,
                    column_config=history_column_config,
                )
