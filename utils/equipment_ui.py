"""Shared Streamlit UI for Functional Review Equipment tabs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from utils.equipment_store import (
    EQUIPMENT_FUNCTION_AREAS,
    attach_equipment_to_function,
    delete_equipment_assets,
    delete_equipment_image,
    delete_equipment_types,
    detach_equipment_from_function,
    equipment_assets,
    equipment_deletion_impact,
    equipment_pitch_options,
    equipment_placement_detail,
    equipment_placement_mismatches,
    equipment_process_options,
    equipment_torque_compatibility_warnings,
    equipment_torque_published_specifications,
    equipment_torque_requirement_ids,
    equipment_types,
    move_equipment_to_linked_pitch,
    save_equipment_placement,
    save_equipment_torque_requirements,
    save_equipment_type_rows,
    save_function_equipment_rows,
    set_equipment_image,
    torque_requirements,
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
    export["Equipment Type"] = export.get("equipment_type", "")
    export["Equipment name"] = export.get("name", "")
    export["Description"] = export.get("description", "")
    export["Manufacturer"] = export.get("manufacturer", "")
    export["Model"] = export.get("model", "")
    export["Station / Pitch"] = export.apply(_pitch_label, axis=1) if not export.empty else ""
    export["Notes"] = export.get("notes", "")
    return export.reindex(
        columns=[
            "Equipment name", "Equipment Type", "Description", "Manufacturer",
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


def render_equipment_type_manager(project_id: str) -> None:
    """Render the project-wide controlled Equipment Type catalog."""
    with st.expander("Manage Equipment Types", icon=":material/category:"):
        st.caption(
            "Equipment Types are shared across the project. Functional Review applicability "
            "controls which type charts appear on each review page."
        )
        logical_key = f"equipment_types_editor_{project_id}"
        editor_key = apply_pending_table_editor_reset(logical_key)
        pending_key = f"equipment_types_pending_delete_{project_id}"
        saved = equipment_types(project_id)
        visible = filter_table(
            saved,
            key=f"equipment_types_filters_{project_id}",
            dropdown_columns=["functional_areas"],
            multi_value_columns=["functional_areas"],
            search_columns=["label", "functional_areas"],
            labels={"functional_areas": "Functional Reviews"},
            reset_widget_keys=[editor_key],
        )
        rows = direct_entry_editor_rows(
            visible,
            editor_key=editor_key,
            sort_columns=["label", "functional_areas"],
            labels={"label": "Equipment Type", "functional_areas": "Functional Reviews"},
        )
        edited = st.data_editor(
            rows,
            key=editor_key,
            num_rows="dynamic",
            hide_index=True,
            column_order=["label", "functional_areas", "updated_at"],
            disabled=["id", "project_id", "created_at", "updated_at"],
            column_config={
                "id": None,
                "project_id": None,
                "label": st.column_config.TextColumn(
                    "Equipment Type", required=True,
                    help="Use one reusable project-wide name for this kind of equipment.",
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
                visible[["label", "functional_areas", "updated_at"]],
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
        dropdown_columns=["equipment_type_id", "pitch_id"],
        search_columns=["name", "equipment_type", "description", "manufacturer", "model", "notes", "pitch_number", "pitch_name"],
        labels={"equipment_type_id": "Equipment Type", "pitch_id": "Station / Pitch"},
        reset_widget_keys=[editor_key],
    )
    rows = direct_entry_editor_rows(
        visible,
        editor_key=editor_key,
        sort_columns=["name", "equipment_type_id", "manufacturer", "model", "pitch_id"],
        labels={
            "name": "Equipment name", "equipment_type_id": "Equipment Type",
            "manufacturer": "Manufacturer", "model": "Model", "pitch_id": "Station / Pitch",
        },
    )
    edited = st.data_editor(
        rows,
        key=editor_key,
        num_rows="dynamic",
        hide_index=True,
        column_order=[
            "name", "equipment_type_id", "description", "manufacturer", "model",
            "pitch_id", "notes", "image", "process_link_count", "torque_requirement_count",
        ],
        disabled=[
            "id", "project_id", "equipment_type", "image_path", "functional_areas",
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
                "Choose the intended Pitch and Process links in Equipment details."
            )
            return
        selected_id = st.selectbox(
            "Equipment eligible for confirmed move",
            options=list(movable),
            format_func=lambda value: movable.get(str(value), "Unavailable equipment"),
            key=f"equipment_mismatch_move_choice_{project_id}_{scenario_id}_{functional_area}",
        )
        pending_key = f"equipment_mismatch_pending_move_{project_id}_{scenario_id}_{functional_area}"
        if st.button(
            "Move equipment to current Pitch",
            icon=":material/move_item:",
            key=f"equipment_mismatch_move_{project_id}_{scenario_id}_{functional_area}",
        ):
            st.session_state[pending_key] = str(selected_id)

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
    if render_history:
        render_equipment_history(
            project_id, key_prefix=f"{functional_area.lower()}_equipment"
        )


def render_equipment_overview(
    project_id: str, scenario_id: str | None
) -> None:
    """Render the central read-only collation and permanent-delete workspace."""
    render_equipment_type_manager(project_id)
    st.divider()
    editable_table_heading("Project equipment")
    st.caption(
        "This is the project-wide collation. Edit equipment from a Functional Review's "
        "Equipment tab; use selection here only for permanent deletion."
    )
    saved = equipment_assets(project_id, scenario_id)
    visible = filter_table(
        saved,
        key=f"equipment_overview_filters_{project_id}",
        dropdown_columns=["equipment_type", "functional_areas", "pitch_number"],
        multi_value_columns=["functional_areas"],
        search_columns=["name", "equipment_type", "description", "manufacturer", "model", "notes", "pitch_number", "pitch_name"],
        labels={
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
            "name", "equipment_type", "description", "manufacturer", "model",
            "station_pitch", "functional_areas_display", "notes", "image",
            "process_link_count", "torque_requirement_count",
        ],
        column_config={
            column: None
            for column in display.columns
            if column not in {
                "name", "equipment_type", "description", "manufacturer", "model",
                "station_pitch", "functional_areas_display", "notes", "image",
                "process_link_count", "torque_requirement_count",
            }
        } | {
            "name": "Equipment name",
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
        height=520,
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
    render_equipment_history(project_id, key_prefix="equipment_overview")
