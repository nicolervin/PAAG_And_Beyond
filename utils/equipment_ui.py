"""Shared Streamlit UI for Functional Review Equipment tabs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from utils.clipboard_image import as_uploaded_file, clipboard_image, decode_clipboard_image
from utils.equipment_store import (
    CONVEYOR_ZONE_COLUMNS,
    EQUIPMENT_FUNCTION_AREAS,
    EQUIPMENT_TIERS,
    UNIT_ORIENTATION_OPTIONS,
    attach_equipment_to_function,
    conveyor_zones,
    delete_conveyor_zone_image,
    delete_conveyor_zones,
    batch_assign_pitches_to_conveyor_zone,
    delete_equipment_assets,
    delete_equipment_image,
    delete_equipment_types,
    detach_equipment_from_function,
    equipment_assets,
    equipment_deletion_impact,
    equipment_needs_vs_placements_matrix,
    equipment_pitch_options,
    equipment_placement_detail,
    equipment_placement_mismatches,
    equipment_process_options,
    equipment_torque_compatibility_warnings,
    equipment_torque_published_specifications,
    equipment_torque_requirement_ids,
    equipment_types,
    move_equipment_to_linked_pitch,
    save_conveyor_zone,
    save_equipment_placement,
    save_equipment_torque_requirements,
    save_equipment_type_rows,
    save_function_equipment_rows,
    save_pitch_ergonomics_geometry,
    scenario_conveyor_line_sizing,
    scenario_pitches_ergonomics_geometry,
    set_conveyor_zone_image,
    set_equipment_image,
    torque_requirements,
    unlink_moved_equipment_links,
)
from utils.quality_store import (
    TORQUE_TOOL_ORIENTATIONS,
    TORQUE_TOOL_TYPES,
    delete_quality_requirement_torque_details,
    quality_requirement_torque_details,
    quality_requirements,
    save_quality_requirement_torque_detail,
    torque_screw_bit_types,
)
from utils.scope_ui import section_heading_with_scope
from utils.store import audit_history, record_audit_event
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
    native_selected_rows,
    required_field_errors,
    selectable_dataframe,
    stage_native_delete_confirmation,
    table_has_unsaved_changes,
)


EQUIPMENT_HISTORY_CATEGORIES = (
    "Equipment assets",
    "Equipment types",
    "Equipment placements",
    "Equipment images",
    "Equipment Torque links",
    "Conveyor zones",
    "Pitch ergonomics",
)


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _editor_name() -> str:
    return _text(st.session_state.get("current_editor"))


def _pitch_label(row: pd.Series | dict) -> str:
    number = _text(row.get("pitch_number")) or "Unassigned"
    name = _text(row.get("pitch_name"))
    return f"{number} — {name}" if name else number


def _equipment_export(frame: pd.DataFrame) -> pd.DataFrame:
    export = frame.copy()
    export["Tier"] = export.get("equipment_tier", "")
    export["Equipment Type"] = export.get("equipment_type", "")
    export["Equipment name"] = export.get("name", "")
    export["Description"] = export.get("description", "")
    export["Manufacturer"] = export.get("manufacturer", "")
    export["Model"] = export.get("model", "")
    export["Station / Pitch"] = export.apply(_pitch_label, axis=1) if not export.empty else ""
    export["Notes"] = export.get("notes", "")
    return export.reindex(
        columns=[
            "Equipment name", "Tier", "Equipment Type", "Description", "Manufacturer",
            "Model", "Station / Pitch", "Notes",
        ]
    )


def render_equipment_history(project_id: str, *, key_prefix: str) -> None:
    with st.expander("History", icon=":material/history:"):
        groups: list[pd.DataFrame] = []
        for category in EQUIPMENT_HISTORY_CATEGORIES:
            history = audit_history(project_id, category, limit=50)
            if history.empty:
                continue
            history = history.copy()
            history.insert(0, "workflow", category)
            groups.append(history)
        combined = (
            pd.concat(groups, ignore_index=True)
            .sort_values("created_at", ascending=False, kind="stable")
            .head(100)
            if groups else pd.DataFrame()
        )
        if combined.empty:
            st.caption("No Equipment changes have been recorded yet.")
            return
        selectable_dataframe(
            combined.drop(columns=["details"], errors="ignore"),
            key=f"{key_prefix}_equipment_history_{project_id}",
            hide_index=True,
            column_config={
                "workflow": "Workflow",
                "action": "Action",
                "row_count": "Rows",
                "editor_name": "Editor",
                "created_at": st.column_config.DatetimeColumn(
                    "When", format="MMM DD, YYYY HH:mm"
                ),
            },
        )


def render_equipment_type_manager(project_id: str, *, wrap_in_expander: bool = True) -> None:
    """Render the project-wide controlled Equipment Type catalog."""
    def _render_type_content() -> None:
        st.caption(
            "Equipment Types are shared across the project. Operational Tier classifies equipment "
            "into Handheld Tools, Station/Pitch Equipment, and Capital Equipment. "
            "Functional Review applicability controls which charts appear on each review page."
        )
        logical_key = f"equipment_types_editor_{project_id}"
        editor_key = apply_pending_table_editor_reset(logical_key)
        pending_key = f"equipment_types_pending_delete_{project_id}"
        saved = equipment_types(project_id)
        visible = filter_table(
            saved,
            key=f"equipment_types_filters_{project_id}",
            dropdown_columns=["tier", "functional_areas"],
            multi_value_columns=["functional_areas"],
            search_columns=["label", "tier", "functional_areas"],
            labels={"tier": "Tier", "functional_areas": "Functional Reviews"},
            reset_widget_keys=[editor_key],
        )
        rows = direct_entry_editor_rows(
            visible,
            editor_key=editor_key,
            sort_columns=["tier", "label", "functional_areas"],
            labels={"label": "Equipment Type", "tier": "Tier", "functional_areas": "Functional Reviews"},
        )
        edited = st.data_editor(
            rows,
            key=editor_key,
            num_rows="dynamic",
            hide_index=True,
            column_order=["label", "tier", "functional_areas", "updated_at"],
            disabled=["id", "project_id", "created_at", "updated_at"],
            column_config={
                "id": None,
                "project_id": None,
                "label": st.column_config.TextColumn(
                    "Equipment Type", required=True,
                    help="Use one reusable project-wide name for this kind of equipment.",
                ),
                "tier": st.column_config.SelectboxColumn(
                    "Tier",
                    options=list(EQUIPMENT_TIERS),
                    default="Handheld Tools",
                    required=True,
                    help="Classify this type into Handheld Tools, Station/Pitch Equipment, or Capital Equipment.",
                ),
                "functional_areas": st.column_config.MultiselectColumn(
                    "Functional Reviews",
                    options=list(EQUIPMENT_FUNCTION_AREAS),
                    required=True,
                    help="Choose the Functional Reviews that should display a chart for this Equipment Type.",
                ),
                "created_at": None,
                "updated_at": st.column_config.DatetimeColumn(
                    "Updated", format="MMM DD, YYYY HH:mm"
                ),
            },
        )
        st.download_button(
            "Export filtered rows",
            dataframe_to_excel(
                visible[["label", "tier", "functional_areas", "updated_at"]],
                sheet_name="Equipment Types",
            ),
            file_name="equipment_types_filtered.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
            key=f"equipment_types_export_{project_id}",
        )
        footer = editable_table_footer(
            editor_key=editor_key,
            key_prefix=f"equipment_types_{project_id}",
            native_row_selection=True,
        )
        selected = native_selected_rows(rows, editor_key=editor_key)
        if not selected.empty:
            if table_has_unsaved_changes(editor_key, native_row_selection=True):
                st.warning("Save or undo Equipment Type edits before deleting.")
            else:
                st.session_state[pending_key] = [
                    {"id": _text(row["id"]), "label": _text(row["label"])}
                    for _, row in selected.iterrows()
                ]
                stage_native_delete_confirmation(editor_key)

        @st.dialog("Delete selected Equipment Types?", dismissible=False)
        def confirm_type_delete() -> None:
            pending = list(st.session_state.get(pending_key) or [])
            st.warning(
                "Delete the selected unused Equipment Types? Types used by equipment are blocked."
            )
            for item in pending:
                st.write(f"- {item['label']}")
            actions = st.container(horizontal=True)
            if actions.button("Cancel", key=f"cancel_equipment_type_delete_{project_id}"):
                st.session_state.pop(pending_key, None)
                request_table_editor_reset(editor_key)
                st.rerun()
            if actions.button(
                "Delete Equipment Types",
                type="primary",
                icon=":material/delete:",
                key=f"destructive_confirm_equipment_type_delete_{project_id}",
            ):
                try:
                    result = delete_equipment_types(
                        project_id,
                        [item["id"] for item in pending],
                        _editor_name(),
                    )
                    st.session_state.pop(pending_key, None)
                    request_table_editor_reset(editor_key)
                    st.toast(
                        f"Deleted {result['row_count']} Equipment Type(s)",
                        icon=":material/delete:",
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        if st.session_state.get(pending_key):
            confirm_type_delete()
        if footer.undo:
            request_table_editor_reset(editor_key)
            st.rerun()
        if footer.save_and_refresh:
            try:
                if not selected.empty:
                    raise ValueError("Clear selected rows before saving Equipment Types.")
                prepared = drop_untouched_new_rows(edited, identifying_columns=["label"])
                combined = merge_filtered_edits(saved, visible, prepared)
                result = save_equipment_type_rows(
                    project_id, combined.to_dict("records"), _editor_name()
                )
                request_table_editor_reset(editor_key)
                st.toast(
                    f"Saved {result['row_count']} Equipment Type change(s)",
                    icon=":material/check_circle:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if wrap_in_expander:
        with st.expander("Manage Equipment Types", icon=":material/category:"):
            _render_type_content()
    else:
        _render_type_content()


def _render_add_existing(
    project_id: str, functional_area: str, linked: pd.DataFrame
) -> None:
    with st.expander("Add existing equipment", icon=":material/add_link:"):
        all_assets = equipment_assets(project_id)
        linked_ids = set(linked["id"].astype(str)) if not linked.empty else set()
        applicable_type_ids = set(
            equipment_types(project_id, functional_area)["id"].astype(str)
        )
        available = all_assets.loc[
            ~all_assets["id"].astype(str).isin(linked_ids)
            & all_assets["equipment_type_id"].astype(str).isin(applicable_type_ids)
        ].copy()
        if available.empty:
            st.caption("No compatible project equipment is available to add.")
            return
        labels = {
            _text(row["id"]): f"{row['name']} — {row['equipment_type']}"
            for _, row in available.iterrows()
        }
        selected = st.multiselect(
            "Project equipment",
            options=list(labels),
            format_func=lambda value: labels.get(str(value), "Unavailable equipment"),
            key=f"equipment_attach_{project_id}_{functional_area}",
            help="Add the shared equipment record to this Functional Review without creating a copy.",
        )
        if st.button(
            "Add existing equipment",
            icon=":material/add_link:",
            disabled=not selected,
            key=f"equipment_attach_action_{project_id}_{functional_area}",
        ):
            try:
                result = attach_equipment_to_function(
                    project_id, list(selected), functional_area, _editor_name()
                )
                st.session_state.pop(f"equipment_attach_{project_id}_{functional_area}", None)
                st.toast(
                    f"Added {result['row_count']} equipment record(s)",
                    icon=":material/check_circle:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def _render_equipment_table(
    project_id: str,
    scenario_id: str | None,
    functional_area: str,
    *,
    equipment_type_id: str | None,
    type_label: str,
) -> pd.DataFrame:
    all_linked = equipment_assets(project_id, scenario_id, functional_area)
    saved = (
        all_linked.loc[
            all_linked["equipment_type_id"].astype(str).eq(equipment_type_id)
        ].copy()
        if equipment_type_id else all_linked.copy()
    )
    suffix = equipment_type_id or "all"
    logical_key = f"equipment_assets_editor_{project_id}_{functional_area}_{suffix}"
    editor_key = apply_pending_table_editor_reset(logical_key)
    pending_key = f"equipment_assets_pending_detach_{project_id}_{functional_area}_{suffix}"
    applicable_types = equipment_types(project_id, functional_area)
    type_labels = dict(zip(applicable_types["id"].astype(str), applicable_types["label"].astype(str)))
    pitches = equipment_pitch_options(project_id, scenario_id) if scenario_id else pd.DataFrame()
    pitch_labels = {
        _text(row["id"]): _pitch_label(row)
        for _, row in pitches.iterrows()
    }
    editor_source = saved.copy()
    editor_source["image"] = editor_source["image_path"].map(
        lambda value: "Attached" if _text(value) else "None"
    ) if not editor_source.empty else pd.Series(dtype="string")
    visible = filter_table(
        editor_source,
        key=f"equipment_assets_filters_{project_id}_{functional_area}_{suffix}",
        dropdown_columns=["equipment_tier", "equipment_type_id", "pitch_id"],
        search_columns=["name", "equipment_tier", "equipment_type", "description", "manufacturer", "model", "notes", "pitch_number", "pitch_name"],
        labels={"equipment_tier": "Tier", "equipment_type_id": "Equipment Type", "pitch_id": "Station / Pitch"},
        reset_widget_keys=[editor_key],
    )
    rows = direct_entry_editor_rows(
        visible,
        editor_key=editor_key,
        sort_columns=["name", "equipment_tier", "equipment_type_id", "manufacturer", "model", "pitch_id"],
        labels={
            "name": "Equipment name", "equipment_tier": "Tier", "equipment_type_id": "Equipment Type",
            "manufacturer": "Manufacturer", "model": "Model", "pitch_id": "Station / Pitch",
        },
    )
    edited = st.data_editor(
        rows,
        key=editor_key,
        num_rows="dynamic",
        hide_index=True,
        column_order=[
            "name", "equipment_tier", "equipment_type_id", "description", "manufacturer", "model",
            "pitch_id", "notes", "image", "process_link_count", "torque_requirement_count",
        ],
        disabled=[
            "id", "project_id", "equipment_tier", "equipment_type", "image_path", "functional_areas",
            "placement_id", "pitch_number", "pitch_name", "process_link_count",
            "torque_requirement_count", "created_at", "updated_at", "image",
            *(["equipment_type_id"] if equipment_type_id else []),
            *(["pitch_id"] if not scenario_id else []),
        ],
        column_config={
            "id": None,
            "project_id": None,
            "equipment_type": None,
            "functional_areas": None,
            "placement_id": None,
            "pitch_number": None,
            "pitch_name": None,
            "image_path": None,
            "created_at": None,
            "updated_at": None,
            "name": st.column_config.TextColumn(
                "Equipment name", required=True,
                help="Use a unique project-wide name that collaborators can recognize.",
            ),
            "equipment_tier": st.column_config.TextColumn(
                "Tier",
                help="Handheld Tools, Station/Pitch Equipment, or Capital Equipment.",
            ),
            "equipment_type_id": st.column_config.SelectboxColumn(
                "Equipment Type",
                options=list(type_labels),
                format_func=lambda value: type_labels.get(str(value), "Unavailable type"),
                default=equipment_type_id,
                required=True,
                help="The selected type controls which Functional Review charts display this equipment.",
            ),
            "description": st.column_config.TextColumn("Description", width="large"),
            "manufacturer": st.column_config.TextColumn("Manufacturer"),
            "model": st.column_config.TextColumn("Model"),
            "pitch_id": st.column_config.SelectboxColumn(
                "Station / Pitch",
                options=["", *pitch_labels],
                format_func=lambda value: "Unassigned" if not _text(value) else pitch_labels.get(str(value), "Unavailable Pitch"),
                help="The scenario-specific physical Pitch where this equipment is currently placed.",
            ),
            "notes": st.column_config.TextColumn("Notes", width="large"),
            "image": st.column_config.TextColumn("Primary image"),
            "process_link_count": st.column_config.NumberColumn("Process links", format="%d"),
            "torque_requirement_count": st.column_config.NumberColumn("Torque requirements", format="%d"),
        },
        height=430,
    )
    st.download_button(
        "Export filtered rows",
        dataframe_to_excel(_equipment_export(visible), sheet_name="Equipment"),
        file_name=f"{functional_area.lower()}_{type_label.lower().replace(' ', '_')}_equipment.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        key=f"equipment_export_{project_id}_{functional_area}_{suffix}",
    )
    footer = editable_table_footer(
        editor_key=editor_key,
        key_prefix=f"equipment_assets_{project_id}_{functional_area}_{suffix}",
        native_row_selection=True,
    )
    selected = native_selected_rows(rows, editor_key=editor_key)
    if not selected.empty:
        if table_has_unsaved_changes(editor_key, native_row_selection=True):
            st.warning("Save or undo equipment edits before removing Functional Review links.")
        else:
            st.session_state[pending_key] = [
                {"id": _text(row["id"]), "name": _text(row["name"])}
                for _, row in selected.iterrows()
            ]
            stage_native_delete_confirmation(editor_key)

    @st.dialog("Remove equipment from this Functional Review?", dismissible=False)
    def confirm_detach() -> None:
        pending = list(st.session_state.get(pending_key) or [])
        st.warning(
            f"Remove {len(pending)} equipment record(s) from {functional_area}? "
            "The shared equipment, placements, images, and links remain in the project."
        )
        for item in pending:
            st.write(f"- {item['name']}")
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_equipment_detach_{project_id}_{functional_area}_{suffix}"):
            st.session_state.pop(pending_key, None)
            request_table_editor_reset(editor_key)
            st.rerun()
        if actions.button(
            "Remove from Functional Review",
            type="primary",
            icon=":material/link_off:",
            key=f"destructive_confirm_equipment_detach_{project_id}_{functional_area}_{suffix}",
        ):
            try:
                result = detach_equipment_from_function(
                    project_id, [item["id"] for item in pending], functional_area, _editor_name()
                )
                st.session_state.pop(pending_key, None)
                request_table_editor_reset(editor_key)
                st.toast(
                    f"Removed {result['row_count']} equipment record(s) from {functional_area}",
                    icon=":material/link_off:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if st.session_state.get(pending_key):
        confirm_detach()
    if footer.undo:
        request_table_editor_reset(editor_key)
        st.rerun()
    if footer.save_and_refresh:
        try:
            if not selected.empty:
                raise ValueError("Clear selected rows before saving Equipment edits.")
            prepared = drop_untouched_new_rows(
                edited, identifying_columns=["name", "equipment_type_id"]
            )
            if equipment_type_id and not prepared.empty:
                prepared = prepared.copy()
                prepared["equipment_type_id"] = equipment_type_id
            combined = merge_filtered_edits(editor_source, visible, prepared)
            result = save_function_equipment_rows(
                project_id,
                functional_area,
                scenario_id,
                combined.to_dict("records"),
                _editor_name(),
            )
            request_table_editor_reset(editor_key)
            st.toast(
                f"Saved {result['row_count']} equipment change(s)",
                icon=":material/check_circle:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    return all_linked


def _render_equipment_detail(
    project_id: str,
    scenario_id: str | None,
    functional_area: str,
    linked_assets: pd.DataFrame,
) -> None:
    if linked_assets.empty:
        return
    labels = {
        _text(row["id"]): f"{row['name']} — {row['equipment_type']}"
        for _, row in linked_assets.iterrows()
    }
    selected_id = st.selectbox(
        "Equipment details",
        options=list(labels),
        index=None,
        placeholder="Choose equipment",
        format_func=lambda value: labels.get(str(value), "Unavailable equipment"),
        key=f"equipment_detail_choice_{project_id}_{functional_area}",
        help="Choose a saved equipment record to maintain its image and scenario relationships.",
    )
    if not selected_id:
        return
    selected_id = str(selected_id)
    selected = linked_assets.loc[linked_assets["id"].astype(str).eq(selected_id)]
    if selected.empty:
        st.warning("That equipment record is no longer available.")
        return
    asset = selected.iloc[0]

    with st.container(border=True):
        st.subheader(_text(asset["name"]))
        image_path = Path(_text(asset.get("image_path")))
        if image_path.is_file():
            st.image(str(image_path), caption=_text(asset["name"]), width=420)
        else:
            st.caption("No primary equipment image attached.")
        upload = st.file_uploader(
            "Upload primary equipment image",
            type=["png", "jpg", "jpeg", "webp"],
            key=f"equipment_primary_upload_{project_id}_{selected_id}",
        )
        image_actions = st.container(horizontal=True)
        if image_actions.button(
            "Save primary image",
            type="primary",
            icon=":material/upload:",
            disabled=upload is None,
            key=f"save_equipment_primary_{project_id}_{selected_id}",
        ):
            try:
                set_equipment_image(project_id, selected_id, upload, _editor_name())
                st.toast("Saved the primary equipment image", icon=":material/check_circle:")
                st.rerun()
            except (OSError, ValueError) as exc:
                st.error(str(exc))
        delete_image_key = f"equipment_image_pending_delete_{project_id}_{selected_id}"
        if image_actions.button(
            "Delete primary image",
            icon=":material/delete:",
            disabled=not image_path.is_file(),
            key=f"request_equipment_image_delete_{project_id}_{selected_id}",
        ):
            st.session_state[delete_image_key] = True

        @st.dialog("Delete primary equipment image?", dismissible=False)
        def confirm_image_delete() -> None:
            st.warning("Delete this equipment image? The equipment record and relationships remain.")
            actions = st.container(horizontal=True)
            if actions.button("Cancel", key=f"cancel_equipment_image_delete_{selected_id}"):
                st.session_state.pop(delete_image_key, None)
                st.rerun()
            if actions.button(
                "Delete image",
                type="primary",
                icon=":material/delete:",
                key=f"destructive_confirm_equipment_image_delete_{selected_id}",
            ):
                try:
                    delete_equipment_image(project_id, selected_id, _editor_name())
                    st.session_state.pop(delete_image_key, None)
                    st.toast("Deleted the primary equipment image", icon=":material/delete:")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        if st.session_state.get(delete_image_key):
            confirm_image_delete()

        st.divider()
        st.subheader("Scenario placement")
        if not scenario_id:
            st.info("Select an active planning scenario to place equipment or link Process Functions.")
        else:
            placement = equipment_placement_detail(project_id, scenario_id, selected_id)
            pitches = equipment_pitch_options(project_id, scenario_id)
            pitch_labels = {
                _text(row["id"]): _pitch_label(row) for _, row in pitches.iterrows()
            }
            selected_pitch = st.selectbox(
                "Station / Pitch",
                options=["", *pitch_labels],
                index=(
                    ["", *pitch_labels].index(_text(placement["pitch_id"]))
                    if _text(placement["pitch_id"]) in ["", *pitch_labels] else 0
                ),
                format_func=lambda value: "Unassigned" if not _text(value) else pitch_labels.get(str(value), "Unavailable Pitch"),
                key=f"equipment_detail_pitch_{project_id}_{scenario_id}_{selected_id}",
                help="One equipment placement belongs to at most one Pitch in a planning scenario.",
            )
            process_options = (
                equipment_process_options(project_id, scenario_id, str(selected_pitch))
                if selected_pitch else pd.DataFrame()
            )
            process_labels = {
                _text(row["id"]): f"{row['op_id']} — {row['work_element']}"
                for _, row in process_options.iterrows()
            }
            valid_defaults = [
                value for value in placement["work_element_ids"] if value in process_labels
            ]
            selected_work = st.multiselect(
                "Linked Process Functions",
                options=list(process_labels),
                default=valid_defaults,
                format_func=lambda value: process_labels.get(str(value), "Unavailable Process Function"),
                key=f"equipment_detail_process_{project_id}_{scenario_id}_{selected_id}_{selected_pitch or 'none'}",
                disabled=not selected_pitch,
                help="Only Process Functions currently assigned to the selected Pitch can be linked.",
            )
            is_station_tier = _text(asset.get("equipment_tier")) == "Station/Pitch Equipment"
            mark_pitch_blocked = False
            if is_station_tier and selected_pitch:
                mark_pitch_blocked = st.checkbox(
                    "Tag Station / Pitch as Blocked (dedicated station footprint)",
                    value=False,
                    key=f"equipment_block_pitch_{project_id}_{scenario_id}_{selected_id}_{selected_pitch}",
                    help="Station equipment occupies pitch space and prevents arbitrary operator rebalancing.",
                )
            if st.button(
                "Save & Refresh",
                type="primary",
                icon=":material/save:",
                key=f"save_equipment_placement_{project_id}_{scenario_id}_{selected_id}",
            ):
                try:
                    result = save_equipment_placement(
                        project_id,
                        scenario_id,
                        selected_id,
                        str(selected_pitch or ""),
                        list(selected_work),
                        _editor_name(),
                        mark_pitch_blocked=mark_pitch_blocked,
                    )
                    st.toast(
                        "Saved the equipment placement"
                        if result["row_count"] else "Equipment placement is already up to date",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        if _text(asset["equipment_type"]).casefold() == "torque tool":
            st.divider()
            st.subheader("Linked Torque requirements")
            requirements = torque_requirements(project_id)
            requirement_labels = {
                _text(row["id"]): f"{row['unique_identifier']} — {row['description']}"
                for _, row in requirements.iterrows()
            }
            selected_requirements = st.multiselect(
                "Torque Quality requirements",
                options=list(requirement_labels),
                default=[
                    value for value in equipment_torque_requirement_ids(project_id, selected_id)
                    if value in requirement_labels
                ],
                format_func=lambda value: requirement_labels.get(str(value), "Unavailable Torque requirement"),
                key=f"equipment_torque_links_{project_id}_{selected_id}",
                help="One installed Torque tool may serve several saved Torque Quality requirements.",
            )
            if selected_requirements:
                specification = (
                    equipment_torque_published_specifications(
                        project_id,
                        scenario_id,
                        selected_id,
                        list(selected_requirements),
                    )
                    if scenario_id
                    else pd.DataFrame()
                )
                if specification.empty:
                    st.info(
                        "No selected Torque requirement is published to a linked "
                        "Process Function for this equipment in the active scenario."
                    )
                else:
                    specification = specification.copy()
                specification = specification.rename(
                    columns={
                        "op_id": "Op ID",
                        "process_function": "Process Function",
                        "unique_identifier": "Unique identifier",
                        "description": "Description",
                        "target_value": "Target value",
                        "tolerances": "Tolerances",
                        "unit": "Unit",
                        "tool_type": "Tool type",
                        "tool_orientation": "Tool orientation",
                        "screw_bit_type": "Screw bit type",
                    }
                )
                if not specification.empty:
                    selectable_dataframe(
                        specification.drop(
                            columns=["quality_requirement_id", "work_element_id"],
                            errors="ignore",
                        ),
                        key=f"equipment_torque_specs_{project_id}_{selected_id}",
                        hide_index=True,
                    )
            if scenario_id:
                warnings = equipment_torque_compatibility_warnings(
                    project_id, scenario_id, selected_id
                )
                if warnings:
                    st.warning(
                        "Some linked Process Functions do not have these Torque requirements "
                        "published to the exact step. Saving is allowed, but review the links:\n\n"
                        + "\n".join(f"- {warning}" for warning in warnings)
                    )
            if st.button(
                "Save & Refresh",
                type="primary",
                icon=":material/save:",
                key=f"save_equipment_torque_links_{project_id}_{selected_id}",
            ):
                try:
                    result = save_equipment_torque_requirements(
                        project_id, selected_id, list(selected_requirements), _editor_name()
                    )
                    st.toast(
                        "Saved linked Torque requirements"
                        if result["row_count"] else "Linked Torque requirements are already up to date",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


def _render_mismatch_review(
    project_id: str,
    scenario_id: str | None,
    functional_area: str,
    linked_assets: pd.DataFrame,
) -> None:
    if not scenario_id or linked_assets.empty:
        return
    mismatches = equipment_placement_mismatches(project_id, scenario_id)
    allowed_ids = set(linked_assets["id"].astype(str))
    mismatches = mismatches.loc[mismatches["equipment_id"].astype(str).isin(allowed_ids)]
    if mismatches.empty:
        return
    with st.expander("Equipment placement review", expanded=True, icon=":material/warning:"):
        st.warning(
            "These linked Process Functions no longer match the equipment's saved Station / Pitch."
        )
        display = mismatches.rename(
            columns={
                "name": "Equipment name",
                "saved_pitch": "Saved Pitch",
                "process_function": "Linked Process Function",
                "current_pitch": "Current Pitch",
            }
        )[["Equipment name", "Saved Pitch", "Linked Process Function", "Current Pitch"]]
        selectable_dataframe(
            display,
            key=f"equipment_mismatch_table_{project_id}_{scenario_id}_{functional_area}",
            hide_index=True,
        )
        movable: dict[str, str] = {}
        for equipment_id, group in mismatches.groupby("equipment_id", sort=False):
            current_ids = {_text(value) for value in group["current_pitch_id"]}
            if "" not in current_ids and len(current_ids) == 1:
                movable[str(equipment_id)] = _text(group.iloc[0]["name"])
        if not movable:
            st.info(
                "The linked Process Functions are split across Pitches or include an unassigned step. "
                "You can unlink the moved operations below to keep equipment anchored at its saved Station / Pitch."
            )
            if st.button(
                "Unlink all moved operations (keep equipment anchored)",
                icon=":material/link_off:",
                key=f"equipment_mismatch_unlink_all_{project_id}_{scenario_id}_{functional_area}",
                help="Unlink operations that were rebalanced away, keeping equipment anchored at its saved pitch.",
            ):
                try:
                    res = unlink_moved_equipment_links(
                        project_id, scenario_id, None, _editor_name()
                    )
                    st.toast(
                        f"Unlinked {res['row_count']} moved operation(s). Equipment remains anchored at Pitch.",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            return
        selected_id = st.selectbox(
            "Equipment eligible for reconciliation",
            options=list(movable),
            format_func=lambda value: movable.get(str(value), "Unavailable equipment"),
            key=f"equipment_mismatch_move_choice_{project_id}_{scenario_id}_{functional_area}",
        )
        pending_key = f"equipment_mismatch_pending_move_{project_id}_{scenario_id}_{functional_area}"
        col_act1, col_act2 = st.columns(2)
        if col_act1.button(
            "Move equipment to current Pitch",
            icon=":material/move_item:",
            key=f"equipment_mismatch_move_{project_id}_{scenario_id}_{functional_area}",
            help="Move this equipment asset to follow its linked process steps.",
        ):
            st.session_state[pending_key] = str(selected_id)

        if col_act2.button(
            "Unlink moved steps (keep equipment anchored)",
            icon=":material/link_off:",
            key=f"equipment_mismatch_unlink_{project_id}_{scenario_id}_{functional_area}",
            help="Keep equipment anchored at its current pitch and unlink the moved step(s). The moved steps will flag as missing equipment at their new pitch.",
        ):
            try:
                res = unlink_moved_equipment_links(
                    project_id, scenario_id, str(selected_id), _editor_name()
                )
                st.toast(
                    f"Unlinked {res['row_count']} moved operation(s). Equipment remains anchored at Station / Pitch.",
                    icon=":material/check_circle:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        @st.dialog("Move equipment to current Pitch?", dismissible=False)
        def confirm_move() -> None:
            equipment_id = _text(st.session_state.get(pending_key))
            st.warning(
                f"Move {movable.get(equipment_id, 'this equipment')} to the one current Pitch "
                "shared by all of its linked Process Functions?"
            )
            actions = st.container(horizontal=True)
            if actions.button("Cancel", key=f"cancel_equipment_pitch_move_{equipment_id}"):
                st.session_state.pop(pending_key, None)
                st.rerun()
            if actions.button(
                "Move equipment",
                type="primary",
                icon=":material/move_item:",
                key=f"destructive_confirm_equipment_pitch_move_{equipment_id}",
            ):
                try:
                    move_equipment_to_linked_pitch(
                        project_id, scenario_id, equipment_id, _editor_name()
                    )
                    st.session_state.pop(pending_key, None)
                    st.toast("Moved equipment to the current Pitch", icon=":material/check_circle:")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        if st.session_state.get(pending_key):
            confirm_move()


def render_torque_requirement_specifications(project_id: str) -> None:
    """Render the moved requirement-level Torque tool details workflow."""
    with st.expander("Torque requirement specifications", icon=":material/build:"):
        st.caption(
            "These values describe a saved Torque Quality requirement. They are shared by "
            "every installed Torque tool linked to that requirement."
        )
        requirements = quality_requirements(project_id)
        torque_rows = requirements.loc[
            requirements["requirement_type"].fillna("").astype(str).str.strip().str.casefold().eq("torque")
        ].copy() if not requirements.empty else pd.DataFrame()
        labels = {
            _text(row["id"]): f"{row['unique_identifier']} — {row['description']}"
            for _, row in torque_rows.iterrows()
        }
        requirement_id = st.selectbox(
            "Saved Torque requirement",
            options=list(labels),
            index=None,
            placeholder="Choose a saved Torque requirement",
            format_func=lambda value: labels.get(str(value), "Unavailable Torque requirement"),
            key=f"equipment_torque_detail_requirement_{project_id}",
            help="Only saved Quality requirements whose Type is Torque appear here.",
        )
        if not labels:
            st.caption("Create and save a Quality requirement with Type set to Torque first.")
            return
        if not requirement_id:
            return
        requirement_id = str(requirement_id)
        editor_key = apply_pending_table_editor_reset(
            f"equipment_torque_details_editor_{project_id}_{requirement_id}"
        )
        pending_key = f"equipment_torque_details_pending_delete_{project_id}_{requirement_id}"
        details = quality_requirement_torque_details(project_id, requirement_id)
        if details.empty:
            details = pd.DataFrame([
                {
                    "id": "", "project_id": project_id,
                    "quality_requirement_id": requirement_id,
                    "tool_type": "", "tool_orientation": "", "screw_bit_type": "",
                    "created_at": "", "updated_at": "",
                }
            ])
        current_bit = _text(details.iloc[0].get("screw_bit_type"))
        bit_options = torque_screw_bit_types(project_id)
        if current_bit and current_bit not in bit_options:
            bit_options.append(current_bit)
            bit_options.sort(key=str.casefold)
        bit_key = f"equipment_torque_screw_bit_{project_id}_{requirement_id}"
        bit_value = st.selectbox(
            "Screw bit type",
            options=bit_options,
            index=bit_options.index(current_bit) if current_bit else None,
            placeholder="Choose a previous value or enter a new one",
            accept_new_options=True,
            key=bit_key,
        )
        details = details.copy()
        details["screw_bit_type"] = _text(bit_value)
        rows = direct_entry_editor_rows(
            details,
            editor_key=editor_key,
            sort_columns=["tool_type", "tool_orientation", "screw_bit_type"],
            labels={"tool_type": "Tool type", "tool_orientation": "Tool orientation", "screw_bit_type": "Screw bit type"},
        )
        edited = st.data_editor(
            rows,
            key=editor_key,
            num_rows="dynamic",
            hide_index=True,
            disabled=["id", "project_id", "quality_requirement_id", "screw_bit_type", "created_at", "updated_at"],
            column_order=["tool_type", "tool_orientation", "screw_bit_type", "updated_at"],
            column_config={
                "id": None,
                "project_id": None,
                "quality_requirement_id": None,
                "tool_type": st.column_config.SelectboxColumn(
                    "Tool type", options=TORQUE_TOOL_TYPES, required=True
                ),
                "tool_orientation": st.column_config.SelectboxColumn(
                    "Tool orientation", options=TORQUE_TOOL_ORIENTATIONS, required=True
                ),
                "screw_bit_type": st.column_config.TextColumn("Screw bit type", required=True),
                "created_at": None,
                "updated_at": st.column_config.DatetimeColumn("Updated", format="MMM DD, YYYY HH:mm"),
            },
        )
        changed_bit = current_bit != _text(bit_value)
        footer = editable_table_footer(
            editor_key=editor_key,
            key_prefix=f"equipment_torque_details_{project_id}_{requirement_id}",
            native_row_selection=True,
            additional_unsaved_changes=changed_bit,
        )
        selected = native_selected_rows(rows, editor_key=editor_key)
        if not selected.empty:
            if table_has_unsaved_changes(editor_key, native_row_selection=True) or changed_bit:
                st.warning("Save or undo other edits before deleting Torque requirement specifications.")
            else:
                st.session_state[pending_key] = [
                    {"id": _text(row["id"]), "tool_type": _text(row["tool_type"])}
                    for _, row in selected.iterrows()
                ]
                stage_native_delete_confirmation(editor_key)

        @st.dialog("Delete selected Torque requirement specifications?", dismissible=False)
        def confirm_delete() -> None:
            pending = list(st.session_state.get(pending_key) or [])
            st.warning(
                "Delete the selected specification? The Quality requirement, installed "
                "equipment, and Process assignments remain."
            )
            actions = st.container(horizontal=True)
            if actions.button("Cancel", key=f"cancel_equipment_torque_detail_delete_{requirement_id}"):
                st.session_state.pop(pending_key, None)
                request_table_editor_reset(editor_key)
                st.rerun()
            if actions.button(
                "Delete specification",
                type="primary",
                icon=":material/delete:",
                key=f"destructive_confirm_equipment_torque_detail_delete_{requirement_id}",
            ):
                try:
                    detail_ids = [item["id"] for item in pending]
                    count = delete_quality_requirement_torque_details(
                        project_id, requirement_id, detail_ids
                    )
                    record_audit_event(
                        project_id,
                        "Quality requirements",
                        "Delete Torque tool details",
                        count,
                        _editor_name(),
                        {"quality_requirement_id": requirement_id, "detail_ids": detail_ids},
                    )
                    st.session_state.pop(pending_key, None)
                    st.session_state.pop(bit_key, None)
                    request_table_editor_reset(editor_key)
                    st.toast("Deleted the Torque requirement specification", icon=":material/delete:")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        if st.session_state.get(pending_key):
            confirm_delete()
        if footer.undo:
            st.session_state.pop(bit_key, None)
            request_table_editor_reset(editor_key)
            st.rerun()
        if footer.save_and_refresh:
            try:
                if not selected.empty:
                    raise ValueError("Clear selected rows before saving Torque requirement specifications.")
                prepared = drop_untouched_new_rows(
                    edited, identifying_columns=["tool_type", "tool_orientation", "screw_bit_type"]
                )
                if len(prepared) > 1:
                    raise ValueError("Each Torque requirement can have only one specification row.")
                if prepared.empty:
                    raise ValueError("Enter the Torque requirement specification before saving.")
                prepared = prepared.copy()
                prepared.loc[:, "screw_bit_type"] = _text(bit_value)
                errors = required_field_errors(
                    prepared,
                    {"tool_type": "Tool type", "tool_orientation": "Tool orientation", "screw_bit_type": "Screw bit type"},
                )
                if errors:
                    raise ValueError(" ".join(errors))
                result = save_quality_requirement_torque_detail(
                    project_id, requirement_id, prepared.iloc[0].to_dict()
                )
                if int(result["row_count"]):
                    record_audit_event(
                        project_id,
                        "Quality requirements",
                        "Save & Refresh Torque tool details",
                        int(result["row_count"]),
                        _editor_name(),
                        {
                            "quality_requirement_id": requirement_id,
                            "torque_detail_id": result["id"],
                            "store_timestamp": result["timestamp"],
                        },
                    )
                st.session_state.pop(bit_key, None)
                request_table_editor_reset(editor_key)
                st.toast("Saved the Torque requirement specification", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def render_equipment_needs_vs_placements_matrix(
    project_id: str, scenario_id: str | None, *, wrap_in_expander: bool = True
) -> None:
    """Render the unified Equipment Needs vs Placements Audit Matrix table."""
    def _render_matrix_content() -> None:
        st.caption(
            "Verify that every Drawing Requirement (e.g. Torque specs) and PFMEA Control method "
            "(e.g. Vision systems, Scanners, Poka-Yoke, ESD) has matching Equipment placed."
        )
        if not scenario_id:
            st.caption("Select an active planning scenario to review the Equipment Audit Matrix.")
            return

        matrix = equipment_needs_vs_placements_matrix(project_id, scenario_id)
        if matrix.empty:
            st.info("No equipment requirements or controls detected for the active scenario.")
            return

        missing_count = int((~matrix["is_satisfied"]).sum())
        if missing_count > 0:
            st.warning(
                f"⚠️ **{missing_count} Equipment Requirement(s) / Control(s) are missing placed Equipment Assets.**"
            )
        else:
            st.success("🟢 **All Drawing Requirements and PFMEA Controls have placed Equipment Assets.**")

        filter_col1, filter_col2 = st.columns(2)
        status_filter = filter_col1.selectbox(
            "Filter by Coverage Status",
            options=["All", "Missing Equipment Only", "Satisfied Only"],
            key=f"equipment_matrix_status_filter_{project_id}_{scenario_id}",
        )
        source_filter = filter_col2.selectbox(
            "Filter by Source Stage",
            options=["All", "Drawing Requirement Only", "PFMEA Control Only"],
            key=f"equipment_matrix_source_filter_{project_id}_{scenario_id}",
        )

        filtered = matrix.copy()
        if status_filter == "Missing Equipment Only":
            filtered = filtered.loc[~filtered["is_satisfied"]]
        elif status_filter == "Satisfied Only":
            filtered = filtered.loc[filtered["is_satisfied"]]

        if source_filter == "Drawing Requirement Only":
            filtered = filtered.loc[filtered["source_stage"].eq("Drawing Requirement")]
        elif source_filter == "PFMEA Control Only":
            filtered = filtered.loc[filtered["source_stage"].eq("PFMEA Control")]

        st.dataframe(
            filtered,
            key=f"equipment_matrix_table_{project_id}_{scenario_id}",
            hide_index=True,
            column_order=[
                "op_id", "pitch_station", "operation", "source_stage",
                "requirement_control_desc", "expected_equipment_type",
                "linked_asset_names", "coverage_status",
            ],
            column_config={
                "op_id": "Op ID",
                "pitch_station": "Pitch / Station",
                "operation": "Operation",
                "source_stage": "Source Stage",
                "requirement_control_desc": "Requirement / Control",
                "expected_equipment_type": "Expected Equipment Type",
                "linked_asset_names": "Linked Equipment Asset",
                "coverage_status": "Coverage Status",
                "work_element_id": None,
                "is_satisfied": None,
            },
            width="stretch",
        )

    if wrap_in_expander:
        with st.expander("Equipment Needs vs. Placements Audit Matrix", icon=":material/fact_check:"):
            _render_matrix_content()
    else:
        _render_matrix_content()


def render_functional_equipment_tab(
    project_id: str,
    scenario_id: str | None,
    functional_area: str,
    *,
    render_history: bool = True,
) -> None:
    """Render one Functional Review's shared and type-specific Equipment charts."""
    if functional_area not in EQUIPMENT_FUNCTION_AREAS:
        raise ValueError("Unknown Functional Review Equipment area.")
    scenario_name = ""
    if scenario_id:
        from utils.store import get_planning_scenario
        scenario = get_planning_scenario(project_id, scenario_id)
        scenario_name = _text((scenario or {}).get("name"))
    section_heading_with_scope(
        "Equipment catalog",
        scope="scenario-aware",
        scenario_name=scenario_name or None,
        help_text=(
            "Equipment identity and Functional Review associations are shared across every "
            "scenario. Station / Pitch and Process Function links use the active scenario."
        ),
    )
    st.caption(
        f"Maintain equipment used by {functional_area}. Shared equipment edits appear in every "
        "Functional Review linked to the same record."
    )
    applicable = equipment_types(project_id, functional_area)
    labels = ["All equipment", *applicable["label"].astype(str).tolist()]
    tabs = st.tabs(
        labels,
        key=f"equipment_type_tabs_{project_id}_{functional_area}",
        on_change="rerun",
    )
    selected_type_id: str | None = None
    selected_type_label = "All equipment"
    selected_tab = tabs[0]
    for index, (_, row) in enumerate(applicable.iterrows(), start=1):
        if tabs[index].open:
            selected_tab = tabs[index]
            selected_type_id = _text(row["id"])
            selected_type_label = _text(row["label"])
            break
    with selected_tab:
        editable_table_heading(selected_type_label)
        linked_assets = _render_equipment_table(
            project_id,
            scenario_id,
            functional_area,
            equipment_type_id=selected_type_id,
            type_label=selected_type_label,
        )
        _render_add_existing(project_id, functional_area, linked_assets)
        _render_equipment_detail(project_id, scenario_id, functional_area, linked_assets)
        _render_mismatch_review(project_id, scenario_id, functional_area, linked_assets)
        if functional_area == "Quality":
            render_torque_requirement_specifications(project_id)
            render_equipment_needs_vs_placements_matrix(project_id, scenario_id)
    if render_history:
        render_equipment_history(
            project_id, key_prefix=f"{functional_area.lower()}_equipment"
        )


def render_conveyor_line_sizing(project_id: str, scenario_id: str | None) -> None:
    """Render the scenario-specific Conveyor line sizing calculator, zones, and pitch ergonomics."""
    if not scenario_id:
        st.info("Select an active planning scenario in the header to configure Conveyor Zones and calculate line sizing.")
        return

    sizing = scenario_conveyor_line_sizing(project_id, scenario_id)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Total Conveyor Length",
        f"{sizing['total_length_ft']} ft",
        f"{sizing['total_length_in']} in",
    )
    c2.metric(
        "Line Pitch Footprint",
        f"{sizing['total_pitches']} pitches",
        f"{sizing['active_pitches']} active · {sizing['helper_pitches']} helper · {sizing['growth_pitches']} growth",
        delta_color="off",
    )
    c3.metric("Standard Pitch Length", f"{sizing['standard_pitch_length_in']} in")
    c4.metric("Capital Monuments Gap", f"{sizing['monument_length_in']} in")

    st.caption(
        "Conveyor length calculation: `Total Length = (Active + Helper + Growth Pitches) × Standard Pitch Length + Monument Gaps`. "
        "Ergonomists specify conveyor elevation/width and unit orientation per zone, plus platform/pit dimensions per pitch."
    )

    st.divider()
    editable_table_heading("Conveyor Zones")
    zones = conveyor_zones(project_id, scenario_id)

    if zones.empty:
        st.caption("No conveyor zones defined yet for this scenario. Configure a zone below.")
    else:
        st.dataframe(
            zones,
            key=f"conveyor_zones_table_{project_id}_{scenario_id}",
            hide_index=True,
            column_order=[
                "sequence", "name", "assigned_pitch_numbers",
                "active_pitch_count", "helper_pitch_count", "growth_pitch_count",
                "total_pitch_count", "standard_pitch_length_in", "total_length_ft",
                "conveyor_height_in", "conveyor_width_in", "unit_orientation", "has_visual",
            ],
            column_config={
                "sequence": "Seq",
                "name": "Zone Name",
                "assigned_pitch_numbers": "Assigned Pitches",
                "start_pitch_number": None,
                "end_pitch_number": None,
                "active_pitch_count": "Active",
                "helper_pitch_count": "Helper",
                "growth_pitch_count": "Growth",
                "total_pitch_count": "Total Pitches",
                "standard_pitch_length_in": "Pitch Length (in)",
                "total_length_ft": "Total Length (ft)",
                "conveyor_height_in": "Height (in)",
                "conveyor_width_in": "Width (in)",
                "unit_orientation": "Unit Orientation",
                "has_visual": "Visual",
                "id": None,
                "project_id": None,
                "scenario_id": None,
                "start_pitch_id": None,
                "end_pitch_id": None,
                "monument_length_in": None,
                "total_length_in": None,
                "orientation_image_path": None,
                "notes": None,
                "created_at": None,
                "updated_at": None,
            },
            width="stretch",
        )

    # Expander for Add / Edit Conveyor Zone
    with st.expander("Configure Conveyor Zone", icon=":material/tune:", expanded=zones.empty):
        pitches = equipment_pitch_options(project_id, scenario_id)
        if pitches.empty:
            st.warning("No pitches exist in the active scenario yet. Create pitches in Yamazumi before configuring Conveyor Zones.")
            return

        pitches_ergo = scenario_pitches_ergonomics_geometry(project_id, scenario_id)
        pitch_options = {
            _text(row["id"]): _pitch_label(row) for _, row in pitches.iterrows()
        }
        zone_choices = ["(Create new Conveyor Zone)"]
        zone_map: dict[str, dict] = {}
        if not zones.empty:
            for _, z_row in zones.iterrows():
                z_label = f"{z_row['sequence']}. {z_row['name']}"
                zone_choices.append(z_label)
                zone_map[z_label] = z_row.to_dict()

        selected_zone_label = st.selectbox(
            "Select Conveyor Zone to edit",
            zone_choices,
            key=f"conveyor_zone_picker_{project_id}_{scenario_id}",
        )
        is_editing = selected_zone_label != "(Create new Conveyor Zone)"
        current_zone = zone_map.get(selected_zone_label, {})

        f_col1, f_col2 = st.columns(2)
        zone_name = f_col1.text_input(
            "Conveyor Zone Name",
            value=str(current_zone.get("name") or ""),
            placeholder="e.g. Zone 1 — Chassis Loading & Tacking",
            key=f"zone_name_input_{project_id}_{scenario_id}",
        )
        zone_seq = f_col2.number_input(
            "Sequence / Zone Number",
            min_value=1,
            step=1,
            value=int(current_zone.get("sequence") or (len(zones) + 1)),
            key=f"zone_seq_input_{project_id}_{scenario_id}",
        )

        # Determine pitches currently assigned to this zone
        curr_zid = str(current_zone.get("id") or "")
        assigned_pids: list[str] = []
        if curr_zid and not pitches_ergo.empty:
            assigned_pids = [
                _text(r["id"]) for _, r in pitches_ergo.iterrows()
                if _text(r.get("conveyor_zone_id")) == curr_zid
            ]
            if not assigned_pids and current_zone.get("assigned_pitch_ids"):
                assigned_pids = [str(pid) for pid in current_zone["assigned_pitch_ids"]]
            elif not assigned_pids:
                s_id = _text(current_zone.get("start_pitch_id"))
                e_id = _text(current_zone.get("end_pitch_id"))
                all_pids = list(pitch_options.keys())
                if s_id in all_pids and e_id in all_pids:
                    i1, i2 = all_pids.index(s_id), all_pids.index(e_id)
                    assigned_pids = all_pids[min(i1, i2) : max(i1, i2) + 1]
                elif s_id in all_pids:
                    assigned_pids = [s_id]

        selected_pitch_ids = st.multiselect(
            "Assigned Stations / Pitches",
            options=list(pitch_options.keys()),
            default=[pid for pid in assigned_pids if pid in pitch_options],
            format_func=lambda value: pitch_options.get(str(value), "Unavailable Pitch"),
            placeholder="Select pitches/stations that belong to this conveyor zone...",
            help="Select all pitches and workstations assigned to this conveyor section.",
            key=f"zone_pitches_multiselect_{project_id}_{scenario_id}_{curr_zid or 'new'}",
        )

        if selected_pitch_ids and not pitches_ergo.empty:
            assigned_preview = pitches_ergo[pitches_ergo["id"].isin(selected_pitch_ids)][
                ["pitch_number", "pitch_name", "area_name", "status"]
            ]
            with st.container(border=True):
                st.caption(f"**Pitches in this Conveyor Section ({len(selected_pitch_ids)}):**")
                st.dataframe(
                    assigned_preview,
                    hide_index=True,
                    column_config={
                        "pitch_number": "Pitch Number",
                        "pitch_name": "Pitch Name",
                        "area_name": "Area",
                        "status": "Status",
                    },
                    height=min(180, 36 * (len(assigned_preview) + 1)),
                    width="stretch",
                )

        st.markdown("##### Ergonomic Specifications")
        e_col1, e_col2, e_col3 = st.columns(3)
        conveyor_h = e_col1.number_input(
            "Conveyor Height (in)",
            min_value=0.0,
            step=0.5,
            value=float(current_zone.get("conveyor_height_in") or 36.0),
            help="Optimal working height specified by Ergonomist.",
            key=f"zone_h_{project_id}_{scenario_id}",
        )
        conveyor_w = e_col2.number_input(
            "Conveyor Width (in)",
            min_value=0.0,
            step=0.5,
            value=float(current_zone.get("conveyor_width_in") or 24.0),
            help="Conveyor bed width specified by Ergonomist.",
            key=f"zone_w_{project_id}_{scenario_id}",
        )
        default_orient = str(current_zone.get("unit_orientation") or "Front Facing")
        unit_orient = e_col3.selectbox(
            "Unit Orientation to Operator",
            options=list(UNIT_ORIENTATION_OPTIONS),
            index=(
                list(UNIT_ORIENTATION_OPTIONS).index(default_orient)
                if default_orient in UNIT_ORIENTATION_OPTIONS
                else 0
            ),
            help="Critical orientation of the unit relative to the operator.",
            key=f"zone_orient_{project_id}_{scenario_id}",
        )

        # Orientation visual
        st.markdown("##### Unit Orientation Diagram / Photo")
        img_col1, img_col2 = st.columns([1, 2])
        curr_img_path = str(current_zone.get("orientation_image_path") or "")
        with img_col1:
            if curr_img_path and Path(curr_img_path).exists():
                st.image(curr_img_path, caption="Saved Orientation Visual", width="stretch")
                if is_editing and st.button(
                    "Delete visual",
                    icon=":material/delete:",
                    key=f"delete_zone_img_{current_zone.get('id')}",
                ):
                    delete_conveyor_zone_image(
                        project_id, scenario_id, str(current_zone["id"]), _editor_name()
                    )
                    st.toast("Deleted orientation visual", icon=":material/check_circle:")
                    st.rerun()
            else:
                st.caption("No orientation diagram attached.")

        with img_col2:
            uploaded_file = st.file_uploader(
                "Upload orientation diagram / photo",
                type=["png", "jpg", "jpeg", "webp"],
                key=f"zone_img_upload_{project_id}_{scenario_id}_{selected_zone_label}",
                help="Attach a CAD screenshot or line illustration showing orientation.",
            )
            pasted = clipboard_image(key=f"zone_clip_paste_{project_id}_{scenario_id}_{selected_zone_label}")
            pasted_payload = getattr(pasted, "image", None)
            if pasted_payload:
                try:
                    pasted_img = decode_clipboard_image(pasted_payload)
                    uploaded_file = as_uploaded_file(pasted_img)
                    st.success("Captured screenshot from clipboard!")
                except Exception as exc:
                    st.warning(str(exc))

        st.markdown("##### Line Sizing Parameters")
        s_col1, s_col2, s_col3, s_col4 = st.columns(4)
        pitch_len = s_col1.number_input(
            "Pitch Length (in)",
            min_value=1.0,
            step=1.0,
            value=float(current_zone.get("standard_pitch_length_in") or 120.0),
            help="Standard linear station pitch length in inches.",
            key=f"zone_pitch_len_{project_id}_{scenario_id}",
        )
        helper_pitches = s_col2.number_input(
            "Helper Pitches",
            min_value=0,
            step=1,
            value=int(current_zone.get("helper_pitch_count") or 0),
            help="Additional pitches allocated for line support / helpers.",
            key=f"zone_helpers_{project_id}_{scenario_id}",
        )
        growth_pitches = s_col3.number_input(
            "Growth Pitches",
            min_value=0,
            step=1,
            value=int(current_zone.get("growth_pitch_count") or 0),
            help="Spare pitches allocated for future growth or model variation.",
            key=f"zone_growth_{project_id}_{scenario_id}",
        )
        monument_len = s_col4.number_input(
            "Monuments / Gap (in)",
            min_value=0.0,
            step=1.0,
            value=float(current_zone.get("monument_length_in") or 0.0),
            help="Linear gap allocated for stationary robots, ovens, or physical monuments.",
            key=f"zone_monuments_{project_id}_{scenario_id}",
        )

        zone_notes = st.text_area(
            "Zone Notes",
            value=str(current_zone.get("notes") or ""),
            placeholder="Ergonomic rationale, fixture notes, or tooling considerations...",
            key=f"zone_notes_{project_id}_{scenario_id}",
        )

        btn_c1, btn_c2 = st.columns(2)
        if btn_c1.button(
            "Save Conveyor Zone",
            type="primary",
            icon=":material/save:",
            key=f"save_zone_btn_{project_id}_{scenario_id}",
        ):
            try:
                zone_data = {
                    "id": current_zone.get("id"),
                    "name": zone_name,
                    "sequence": int(zone_seq),
                    "pitch_ids": [str(pid) for pid in selected_pitch_ids],
                    "conveyor_height_in": float(conveyor_h),
                    "conveyor_width_in": float(conveyor_w),
                    "unit_orientation": str(unit_orient),
                    "standard_pitch_length_in": float(pitch_len),
                    "helper_pitch_count": int(helper_pitches),
                    "growth_pitch_count": int(growth_pitches),
                    "monument_length_in": float(monument_len),
                    "notes": zone_notes,
                }
                res = save_conveyor_zone(project_id, scenario_id, zone_data, _editor_name())
                saved_id = str(res.get("id") or current_zone.get("id"))
                if uploaded_file and saved_id:
                    set_conveyor_zone_image(
                        project_id, scenario_id, saved_id, uploaded_file, _editor_name()
                    )
                st.toast("Saved Conveyor Zone", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        if is_editing and btn_c2.button(
            "Delete Conveyor Zone",
            icon=":material/delete:",
            key=f"del_zone_btn_{project_id}_{scenario_id}",
        ):
            try:
                res = delete_conveyor_zones(
                    project_id, scenario_id, [str(current_zone["id"])], _editor_name()
                )
                st.toast(f"Deleted {res['row_count']} Conveyor Zone(s)", icon=":material/delete:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    # Expander for Workstation & Conveyor Pitch Assignments
    with st.expander("Workstation & Conveyor Pitch Assignments (Ergonomics)", icon=":material/height:", expanded=False):
        st.caption(
            "All workstation pitches in this scenario are listed below. Assign pitches to conveyor zones, "
            "and configure workstation platform elevations (+in) or pit recesses (-in)."
        )
        pitches_ergo = scenario_pitches_ergonomics_geometry(project_id, scenario_id)
        if pitches_ergo.empty:
            st.caption("No pitches available in the active scenario.")
            return

        ergo_editor_key = apply_pending_table_editor_reset(f"pitch_ergo_editor_{project_id}_{scenario_id}")
        zone_options = {"": "None / Unassigned"}
        if not zones.empty:
            for _, z_row in zones.iterrows():
                zone_options[str(z_row["id"])] = f"{z_row['sequence']}. {z_row['name']}"

        # Quick Batch Assignment bar
        with st.container(border=True):
            st.markdown("###### Batch Assign Pitches to Conveyor Zone")
            st.caption("Select one or more pitches below to assign them all to a Conveyor Zone simultaneously.")
            ba_col1, ba_col2, ba_col3 = st.columns([2, 3, 1])
            batch_zone = ba_col1.selectbox(
                "Assign To Conveyor Zone",
                options=list(zone_options.keys()),
                format_func=lambda zid: zone_options.get(str(zid), "None / Unassigned"),
                key=f"batch_assign_zone_{project_id}_{scenario_id}",
            )
            batch_pitches = ba_col2.multiselect(
                "Select Pitches",
                options=list(pitch_options.keys()),
                format_func=lambda pid: pitch_options.get(str(pid), "Unavailable Pitch"),
                placeholder="Choose pitches to assign together...",
                key=f"batch_assign_pitches_{project_id}_{scenario_id}",
            )
            ba_col3.write("")
            ba_col3.write("")
            if ba_col3.button(
                "Assign Pitches",
                type="primary",
                icon=":material/done_all:",
                disabled=not batch_pitches,
                key=f"batch_assign_btn_{project_id}_{scenario_id}",
            ):
                try:
                    res = batch_assign_pitches_to_conveyor_zone(
                        project_id, scenario_id, batch_pitches, batch_zone, _editor_name()
                    )
                    request_table_editor_reset(ergo_editor_key)
                    st.toast(
                        f"Assigned {res['updated_count']} pitch(es) to conveyor zone",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        ergo_rows = direct_entry_editor_rows(
            pitches_ergo,
            editor_key=ergo_editor_key,
            sort_columns=["pitch_number", "pitch_name"],
            labels={"pitch_number": "Pitch Number", "pitch_name": "Pitch Name"},
        )
        ergo_edited = st.data_editor(
            ergo_rows,
            key=ergo_editor_key,
            hide_index=True,
            column_order=[
                "pitch_number", "pitch_name", "area_name", "status",
                "conveyor_zone_id", "platform_height_in", "pit_depth_in",
                "conveyor_height_in", "unit_orientation",
            ],
            disabled=[
                "pitch_id", "pitch_number", "pitch_name", "area_name", "status",
                "conveyor_height_in", "unit_orientation",
            ],
            column_config={
                "pitch_id": None,
                "pitch_number": st.column_config.TextColumn("Pitch Number"),
                "pitch_name": st.column_config.TextColumn("Pitch Name"),
                "area_name": st.column_config.TextColumn("Area"),
                "status": st.column_config.TextColumn("Status"),
                "conveyor_zone_id": st.column_config.SelectboxColumn(
                    "Assigned Conveyor Zone",
                    options=list(zone_options),
                    format_func=lambda value: zone_options.get(str(value), "None / Unassigned"),
                    help="Conveyor zone governing height, width, and unit orientation.",
                ),
                "platform_height_in": st.column_config.NumberColumn(
                    "Platform Height (in)",
                    min_value=0.0,
                    step=0.5,
                    format="%.1f in",
                    help="Workstation platform elevation above shop floor.",
                ),
                "pit_depth_in": st.column_config.NumberColumn(
                    "Pit Depth (in)",
                    min_value=0.0,
                    step=0.5,
                    format="%.1f in",
                    help="Recessed pit depth below shop floor.",
                ),
                "conveyor_height_in": st.column_config.NumberColumn(
                    "Zone Conveyor Height (in)",
                    format="%.1f in",
                    help="Conveyor height inherited from Assigned Conveyor Zone.",
                ),
                "unit_orientation": st.column_config.TextColumn(
                    "Zone Unit Orientation",
                    help="Orientation to operator inherited from Assigned Conveyor Zone.",
                ),
            },
            height=420,
            width="stretch",
        )
        ergo_footer = editable_table_footer(
            editor_key=ergo_editor_key,
            key_prefix=f"pitch_ergo_footer_{project_id}_{scenario_id}",
            native_row_selection=False,
        )
        if ergo_footer.undo:
            request_table_editor_reset(ergo_editor_key)
            st.rerun()
        if ergo_footer.save_and_refresh:
            try:
                combined_ergo = merge_filtered_edits(pitches_ergo, pitches_ergo, ergo_edited)
                res = save_pitch_ergonomics_geometry(
                    project_id, scenario_id, combined_ergo.to_dict("records"), _editor_name()
                )
                request_table_editor_reset(ergo_editor_key)
                st.toast(f"Saved ergonomics specs for {res['row_count']} pitch(es)", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def render_equipment_overview(
    project_id: str, scenario_id: str | None
) -> None:
    """Render the central Equipment workspace with 4 tabs and KPI cards."""
    all_assets = equipment_assets(project_id, scenario_id)
    handheld_count = int(all_assets["equipment_tier"].eq("Handheld Tools").sum()) if not all_assets.empty else 0
    station_count = int(all_assets["equipment_tier"].eq("Station/Pitch Equipment").sum()) if not all_assets.empty else 0
    capital_count = int(all_assets["equipment_tier"].eq("Capital Equipment").sum()) if not all_assets.empty else 0

    # Top KPI Metrics row
    kpi_cols = st.columns(4)
    kpi_cols[0].metric("Total Equipment", len(all_assets))
    kpi_cols[1].metric("Handheld Tools", handheld_count)
    kpi_cols[2].metric("Station Equipment", station_count)
    kpi_cols[3].metric("Capital Equipment", capital_count)

    tab_labels = [
        ":material/inventory_2: Equipment Catalog & Placements",
        ":material/conveyor_belt: Conveyor Zones & Line Sizing",
        ":material/fact_check: Needs vs. Placements Audit",
        ":material/category: Equipment Types",
    ]
    tab1, tab2, tab3, tab4 = st.tabs(tab_labels)

    with tab1:
        editable_table_heading("Equipment Catalog & Placements")
        st.caption(
            "Unified collation of all project equipment across Handheld Tools, Station/Pitch Equipment, "
            "and Capital Equipment. Assign Station / Pitch and link Process Functions in the details drawer below."
        )
        saved = all_assets.copy()
        visible = filter_table(
            saved,
            key=f"equipment_overview_filters_{project_id}",
            dropdown_columns=["equipment_tier", "equipment_type", "functional_areas", "pitch_number"],
            multi_value_columns=["functional_areas"],
            search_columns=["name", "equipment_tier", "equipment_type", "description", "manufacturer", "model", "notes", "pitch_number", "pitch_name"],
            labels={
                "equipment_tier": "Tier",
                "equipment_type": "Equipment Type",
                "functional_areas": "Functional Reviews",
                "pitch_number": "Station / Pitch",
            },
        )
        display = visible.copy()
        if not display.empty:
            display["station_pitch"] = display.apply(_pitch_label, axis=1)
            display["functional_areas_display"] = display["functional_areas"].map(lambda values: ", ".join(values))
            display["image"] = display["image_path"].map(lambda value: "Attached" if _text(value) else "None")
        else:
            display["station_pitch"] = pd.Series(dtype="string")
            display["functional_areas_display"] = pd.Series(dtype="string")
            display["image"] = pd.Series(dtype="string")

        editor_key = apply_pending_table_editor_reset(f"equipment_overview_editor_{project_id}")
        pending_key = f"equipment_overview_pending_delete_{project_id}"
        st.data_editor(
            display,
            key=editor_key,
            num_rows="delete",
            hide_index=True,
            disabled=list(display.columns),
            column_order=[
                "name", "equipment_tier", "equipment_type", "description", "manufacturer", "model",
                "station_pitch", "functional_areas_display", "notes", "image",
                "process_link_count", "torque_requirement_count",
            ],
            column_config={
                column: None
                for column in display.columns
                if column not in {
                    "name", "equipment_tier", "equipment_type", "description", "manufacturer", "model",
                    "station_pitch", "functional_areas_display", "notes", "image",
                    "process_link_count", "torque_requirement_count",
                }
            } | {
                "name": "Equipment name",
                "equipment_tier": "Tier",
                "equipment_type": "Equipment Type",
                "description": "Description",
                "manufacturer": "Manufacturer",
                "model": "Model",
                "station_pitch": "Station / Pitch",
                "functional_areas_display": "Functional Reviews",
                "notes": "Notes",
                "image": "Primary image",
                "process_link_count": "Process links",
                "torque_requirement_count": "Torque requirements",
            },
            height=430,
            width="stretch",
        )
        st.download_button(
            "Export filtered rows",
            dataframe_to_excel(_equipment_export(visible), sheet_name="Project Equipment"),
            file_name="project_equipment_filtered.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
            key=f"equipment_overview_export_{project_id}",
        )
        selected = native_selected_rows(display, editor_key=editor_key)
        if not selected.empty:
            st.session_state[pending_key] = [
                {"id": _text(row["id"]), "name": _text(row["name"])}
                for _, row in selected.iterrows()
            ]
            stage_native_delete_confirmation(editor_key)

        @st.dialog("Permanently delete selected equipment?", dismissible=False)
        def confirm_delete() -> None:
            pending = list(st.session_state.get(pending_key) or [])
            try:
                impact = equipment_deletion_impact(
                    project_id, [item["id"] for item in pending]
                )
            except ValueError as exc:
                st.error(str(exc))
                return
            st.warning(
                "This permanently deletes the shared equipment records from every Functional "
                "Review and removes their placements, Process links, Torque links, and owned image."
            )
            for item in pending:
                st.write(f"- {item['name']}")
            st.caption(
                f"{impact['function_links']} Functional Review link(s), "
                f"{impact['placements']} placement(s), {impact['process_links']} Process link(s), "
                f"{impact['torque_links']} Torque link(s), and {impact['image_files']} image file(s) are affected."
            )
            actions = st.container(horizontal=True)
            if actions.button("Cancel", key=f"cancel_equipment_delete_{project_id}"):
                st.session_state.pop(pending_key, None)
                request_table_editor_reset(editor_key)
                st.rerun()
            if actions.button(
                "Delete equipment",
                type="primary",
                icon=":material/delete:",
                key=f"destructive_confirm_equipment_delete_{project_id}",
            ):
                try:
                    result = delete_equipment_assets(
                        project_id, [item["id"] for item in pending], _editor_name()
                    )
                    st.session_state.pop(pending_key, None)
                    request_table_editor_reset(editor_key)
                    st.toast(
                        f"Deleted {result['row_count']} equipment record(s)",
                        icon=":material/delete:",
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        if st.session_state.get(pending_key):
            confirm_delete()
        _render_equipment_detail(
            project_id,
            scenario_id,
            "Project",
            saved,
        )
        _render_mismatch_review(
            project_id,
            scenario_id,
            "Project",
            saved,
        )

    with tab2:
        render_conveyor_line_sizing(project_id, scenario_id)

    with tab3:
        render_equipment_needs_vs_placements_matrix(project_id, scenario_id, wrap_in_expander=False)

    with tab4:
        render_equipment_type_manager(project_id, wrap_in_expander=False)

    st.divider()
    render_equipment_history(project_id, key_prefix="equipment_overview")
