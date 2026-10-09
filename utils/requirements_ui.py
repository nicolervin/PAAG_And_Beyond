from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.assignment_ui import (
    ASSIGN_REQ_DIALOG_OPEN_KEY,
    open_assign_requirement_dialog,
    render_assign_requirement_dialog,
)
from utils.control_plan_store import control_plan_assignment_impact
from utils import quality_store
from utils.quality_store import (
    PROTECTED_QUALITY_REQUIREMENT_TYPE,
    TORQUE_TOOL_ORIENTATIONS,
    TORQUE_TOOL_TYPES,
)
from utils import store, table_ui
from utils.scope_ui import scope_badge, section_heading_with_scope
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
    selected_dataframe_rows,
    selected_rows_action_bar,
    stable_id_from_button_click,
    stage_native_delete_confirmation,
    table_has_unsaved_changes,
)


def record_audit_event(*args, **kwargs):
    return store.record_audit_event(*args, **kwargs)


def selectable_dataframe(*args, **kwargs):
    return table_ui.selectable_dataframe(*args, **kwargs)


LINKED_STEP_FILTER_COLUMNS = [
    "Scenario",
    "Pitch",
    "Work Element",
    "Quality requirement Unique identifier",
    "Type",
    "Status",
    "Repository update pending",
]
LINKED_STEP_VISIBLE_COLUMNS = [
    "Scenario",
    "Op ID",
    "Pitch",
    "Pitch Name",
    "Work Element",
    "Status",
    "Seq",
    "Quality requirement Unique identifier",
    "Type",
    "Description",
    "Pass/fail",
    "Target value",
    "Tolerances",
    "Unit",
    "Repository update pending",
    "Upstream modified",
]
LINKED_STEP_DIALOG_COLUMNS = [
    "Scenario",
    "Op ID",
    "Pitch",
    "Pitch Name",
    "Work Element",
    "Status",
    "Seq",
    "Repository update pending",
]


def _clear_linked_step_filters(project_id: str) -> None:
    """Clear only the existing linked-step panel's transient filter widgets."""
    filter_key = f"quality_requirement_linked_step_filters_{project_id}"
    st.session_state.pop(f"{filter_key}_keyword", None)
    for column in LINKED_STEP_FILTER_COLUMNS:
        st.session_state.pop(f"{filter_key}_{column}", None)


def _linked_step_display_rows(source: pd.DataFrame) -> pd.DataFrame:
    """Return the shared friendly, published linked-step display rows."""
    if source.empty:
        return pd.DataFrame(columns=LINKED_STEP_VISIBLE_COLUMNS)

    linked_steps = source.copy()
    linked_steps["scenario"] = linked_steps.apply(
        lambda row: f"Rev {row['scenario_revision']} · {row['scenario_name']}",
        axis=1,
    )
    linked_steps = linked_steps.rename(
        columns={
            "op_id": "Op ID",
            "pitch": "Pitch",
            "pitch_name": "Pitch Name",
            "work_element": "Work Element",
            "status": "Status",
            "sequence": "Seq",
            "scenario": "Scenario",
            "unique_identifier": "Quality requirement Unique identifier",
            "requirement_type": "Type",
            "description": "Description",
            "pass_fail": "Pass/fail",
            "target_value": "Target value",
            "tolerances": "Tolerances",
            "unit": "Unit",
            "repository_update_pending": "Repository update pending",
        }
    )
    linked_steps["Pass/fail"] = linked_steps["Pass/fail"].fillna(0).astype(bool)
    linked_steps["Repository update pending"] = (
        linked_steps["Repository update pending"].fillna(0).astype(bool)
    )
    if "upstream_modified" in linked_steps.columns:
        linked_steps["Upstream modified"] = (
            linked_steps["upstream_modified"].fillna(0).astype(bool)
        )
    cols = [col for col in LINKED_STEP_VISIBLE_COLUMNS if col in linked_steps.columns]
    return linked_steps.reindex(columns=cols)


def _requirement_friendly_values(requirement: pd.Series) -> tuple[str, str]:
    """Return safe current repository text for linked-step view headings."""
    identifier_value = requirement.get("unique_identifier")
    description_value = requirement.get("description")
    identifier = (
        str(identifier_value).strip()
        if identifier_value is not None and not pd.isna(identifier_value)
        else ""
    )
    description = (
        str(description_value).strip()
        if description_value is not None and not pd.isna(description_value)
        else ""
    )
    return identifier or "No identifier", description or "No description"


def render_quality_requirement_type_catalog(
    project_id: str,
    *,
    repository_editor_key: str,
    repository_busy: bool,
) -> None:
    """Render the project-wide controlled Type catalog and confirmed workflows."""
    types = quality_store.quality_requirement_types(project_id)
    if types.empty:
        types = pd.DataFrame(
            {
                "id": pd.Series(dtype="string"),
                "project_id": pd.Series(dtype="string"),
                "label": pd.Series(dtype="string"),
                "active": pd.Series(dtype="bool"),
                "requirement_count": pd.Series(dtype="int64"),
                "created_at": pd.Series(dtype="string"),
                "updated_at": pd.Series(dtype="string"),
            }
        )
    else:
        types = types.copy()
        types["active"] = types["active"].fillna(0).astype(bool)
        types["requirement_count"] = (
            pd.to_numeric(types["requirement_count"], errors="coerce")
            .fillna(0)
            .astype(int)
        )
    logical_key = f"quality_requirement_types_editor_{project_id}"
    type_editor_key = apply_pending_table_editor_reset(logical_key)
    pending_rename_key = f"quality_requirement_types_pending_rename_{project_id}"
    pending_delete_key = f"quality_requirement_types_pending_delete_{project_id}"

    def save_types(edited_rows: pd.DataFrame, *, confirm_renames: bool) -> None:
        result = quality_store.save_quality_requirement_type_rows(
            project_id,
            edited_rows.reindex(columns=["id", "label", "units_available", "active"]),
            confirm_in_use_renames=confirm_renames,
        )
        changed_count = int(result["row_count"])
        affected_requirements = list(result["renamed_requirement_ids"])
        if changed_count or affected_requirements:
            record_audit_event(
                project_id,
                "Quality requirement types",
                "Save & Refresh",
                changed_count + len(affected_requirements),
                st.session_state.get("current_editor", ""),
                {
                    "created_ids": result["created_ids"],
                    "updated_ids": result["updated_ids"],
                    "renamed_requirement_ids": affected_requirements,
                    "rename_mapping": result["rename_mapping"],
                    "store_timestamp": result["timestamp"],
                },
            )
        request_table_editor_reset(type_editor_key)
        request_table_editor_reset(repository_editor_key)
        st.toast(
            (
                "Saved Quality requirement Types"
                if changed_count or affected_requirements
                else "Quality requirement Types are already up to date"
            ),
            icon=":material/check_circle:",
        )
        st.rerun()

    with st.expander("Manage Quality requirement types", icon=":material/settings:"):
        badge_row = st.container(horizontal=True, vertical_alignment="center")
        badge_row.caption(
            "Maintain the reusable Type choices offered by the Quality requirements table."
        )
        scope_badge(badge_row, scope="project")
        visible_types = filter_table(
            types,
            key=f"quality_requirement_types_filters_{project_id}",
            dropdown_columns=["active"],
            search_columns=["label", "units_available"],
            labels={"label": "Label", "units_available": "Units available", "active": "Active"},
            reset_widget_keys=[type_editor_key],
        )
        type_editor_rows = direct_entry_editor_rows(
            visible_types,
            editor_key=type_editor_key,
            sort_columns=["label", "units_available", "active", "requirement_count"],
            labels={
                "label": "Label",
                "units_available": "Units available",
                "active": "Active",
                "requirement_count": "Quality requirements",
            },
        )
        new_rows = type_editor_rows["id"].fillna("").astype(str).str.strip().eq("")
        type_editor_rows.loc[new_rows, "active"] = True
        edited_types = st.data_editor(
            type_editor_rows,
            key=type_editor_key,
            num_rows="dynamic",
            hide_index=True,
            column_order=["label", "units_available", "active", "requirement_count"],
            disabled=["requirement_count"],
            column_config={
                "id": None,
                "project_id": None,
                "created_at": None,
                "updated_at": None,
                "label": st.column_config.TextColumn(
                    "Label",
                    required=True,
                    help=(
                        "This text appears in the Quality requirement Type dropdown. "
                        "Renaming an in-use label requires confirmation."
                    ),
                ),
                "units_available": st.column_config.TextColumn(
                    "Units available",
                    help=(
                        "Enter allowed units for this Type separated by semicolons "
                        "(e.g., inch;mm;mil or in-lbs;ft-lbs;N·m)."
                    ),
                ),
                "active": st.column_config.CheckboxColumn(
                    "Active",
                    help=(
                        "Inactive Types remain on existing requirements but cannot be "
                        "assigned to new or changed requirements."
                    ),
                ),
                "requirement_count": st.column_config.NumberColumn(
                    "Quality requirements",
                    disabled=True,
                    help="Number of repository requirements currently using this Type.",
                ),
            },
        )
        footer = editable_table_footer(
            editor_key=type_editor_key,
            key_prefix=f"quality_requirement_types_{project_id}",
            native_row_selection=True,
        )
        if footer.undo:
            st.session_state.pop(pending_rename_key, None)
            request_table_editor_reset(type_editor_key)
            st.toast("Discarded the unsaved Type catalog edits", icon=":material/undo:")
            st.rerun()

        st.download_button(
            "Export filtered rows",
            data=dataframe_to_excel(
                visible_types[["label", "active", "requirement_count"]],
                "Quality requirement types",
            ),
            file_name="quality_requirement_types.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
            key=f"quality_requirement_types_export_{project_id}",
        )

        selected_types = native_selected_rows(
            type_editor_rows, editor_key=type_editor_key
        )
        if not selected_types.empty:
            if repository_busy or table_has_unsaved_changes(
                type_editor_key, native_row_selection=True
            ):
                st.warning(
                    "Save or undo other repository and Type catalog edits before deleting "
                    "selected Types."
                )
            elif not st.session_state.get(pending_delete_key):
                st.session_state[pending_delete_key] = [
                    {
                        "id": str(row["id"]),
                        "label": str(row["label"]),
                        "requirement_count": int(row.get("requirement_count") or 0),
                        "protected": str(row["label"]).casefold()
                        == PROTECTED_QUALITY_REQUIREMENT_TYPE.casefold(),
                    }
                    for _, row in selected_types.iterrows()
                ]
                stage_native_delete_confirmation(type_editor_key)

        if footer.save_and_refresh:
            if repository_busy:
                st.warning(
                    "Save or undo Quality requirement edits and clear repository row "
                    "selections before changing the Type catalog."
                )
            elif not selected_types.empty:
                st.warning("Clear selected Type rows before saving catalog edits.")
            else:
                try:
                    cleaned_types = drop_untouched_new_rows(
                        edited_types, identifying_columns=["label"]
                    )
                    validation_errors = required_field_errors(
                        cleaned_types, {"label": "Label"}
                    )
                    if validation_errors:
                        raise ValueError(" ".join(validation_errors))
                    complete_types = merge_filtered_edits(
                        types, visible_types, cleaned_types
                    )
                    rename_impact = quality_store.quality_requirement_type_rename_impact(
                        project_id,
                        complete_types.reindex(columns=["id", "label", "active"]),
                    )
                    if rename_impact:
                        st.session_state[pending_rename_key] = {
                            "rows": complete_types[
                                ["id", "label", "active"]
                            ].to_dict("records"),
                            "impact": rename_impact,
                        }
                    else:
                        save_types(complete_types, confirm_renames=False)
                except ValueError as exc:
                    st.error(str(exc))

    @st.dialog("Rename in-use Quality requirement Types?", dismissible=False)
    def confirm_type_renames() -> None:
        pending = st.session_state.get(pending_rename_key) or {}
        impact = list(pending.get("impact") or [])
        st.warning(
            "Confirm these Type renames. Matching repository requirements will change, "
            "but linked Process-step copies will wait for the existing push action."
        )
        for item in impact:
            st.write(
                f"- {item['old_label']} → {item['new_label']} — "
                f"{item['requirement_count']} Quality requirement(s)"
            )
        actions = st.container(horizontal=True)
        if actions.button(
            "Cancel", key=f"cancel_quality_requirement_type_rename_{project_id}"
        ):
            st.session_state.pop(pending_rename_key, None)
            st.rerun()
        if actions.button(
            "Confirm rename",
            type="primary",
            icon=":material/edit:",
            key=f"confirm_quality_requirement_type_rename_{project_id}",
        ):
            try:
                pending_rows = pd.DataFrame(pending.get("rows") or [])
                save_types(pending_rows, confirm_renames=True)
            except ValueError as exc:
                st.error(str(exc))

    @st.dialog("Delete selected Quality requirement Types?", dismissible=False)
    def confirm_type_delete() -> None:
        pending = list(st.session_state.get(pending_delete_key) or [])
        st.warning(
            f"Delete {len(pending)} selected Type catalog entry or entries? "
            "Quality requirements are preserved."
        )
        for item in pending:
            st.write(
                f"- {item['label']} — {item['requirement_count']} Quality requirement(s)"
            )
        blocked = any(
            bool(item["protected"]) or int(item["requirement_count"]) > 0
            for item in pending
        )
        if any(bool(item["protected"]) for item in pending):
            st.error("Torque is permanent and cannot be deleted.")
        if any(int(item["requirement_count"]) > 0 for item in pending):
            st.error("A Type cannot be deleted while Quality requirements use it.")
        actions = st.container(horizontal=True)
        if actions.button(
            "Cancel", key=f"cancel_quality_requirement_type_delete_{project_id}"
        ):
            st.session_state.pop(pending_delete_key, None)
            request_table_editor_reset(type_editor_key)
            st.rerun()
        if actions.button(
            "Delete",
            type="primary",
            icon=":material/delete:",
            disabled=blocked,
            key=f"destructive_confirm_quality_requirement_type_delete_{project_id}",
        ):
            try:
                result = quality_store.delete_quality_requirement_types(
                    project_id, [str(item["id"]) for item in pending]
                )
                record_audit_event(
                    project_id,
                    "Quality requirement types",
                    "Bulk delete",
                    int(result["row_count"]),
                    st.session_state.get("current_editor", ""),
                    {
                        "deleted_ids": result["deleted_ids"],
                        "labels": [item["label"] for item in pending],
                        "store_timestamp": result["timestamp"],
                    },
                )
                st.session_state.pop(pending_delete_key, None)
                request_table_editor_reset(type_editor_key)
                request_table_editor_reset(repository_editor_key)
                st.toast(
                    f"Deleted {result['row_count']} Quality requirement Type(s)",
                    icon=":material/delete:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if st.session_state.get(pending_rename_key):
        confirm_type_renames()
    elif st.session_state.get(pending_delete_key):
        confirm_type_delete()


def render_requirements_repository_tab(
    project_id: str,
    scenario_id: str | None = None,
    active_scenario: dict | None = None,
) -> None:
    """Render the full Requirements Repository tab workflow."""
    scenario_id = str(scenario_id or "")
    logical_editor_key = f"quality_requirements_editor_{project_id}"
    editor_key = apply_pending_table_editor_reset(logical_editor_key)
    pending_delete_key = f"quality_requirements_pending_delete_{project_id}"
    pending_push_key = f"quality_requirements_pending_push_{project_id}"
    pending_unlink_key = f"quality_requirement_pending_unlink_{project_id}"
    linked_steps_focus_key = f"quality_requirement_linked_steps_focus_{project_id}"
    linked_steps_dialog_key = f"quality_requirement_linked_steps_dialog_{project_id}"
    linked_steps_click_key = f"quality_requirement_linked_steps_click_{project_id}"

    table_columns = [
        "id", "requirement_type", "description", "unique_identifier", "pass_fail",
        "target_value", "tolerances", "unit", "assignment_count",
        "pending_assignment_count", "updated_at",
        "torque_detail_count", "pfmea_pattern_reference_count",
        "equipment_torque_link_count",
    ]
    requirements = quality_store.quality_requirements(project_id)
    requirement_type_catalog = quality_store.quality_requirement_types(project_id)
    if requirements.empty:
        requirements = pd.DataFrame(
            {
                "id": pd.Series(dtype="string"),
                "requirement_type": pd.Series(dtype="string"),
                "description": pd.Series(dtype="string"),
                "unique_identifier": pd.Series(dtype="string"),
                "pass_fail": pd.Series(dtype="bool"),
                "target_value": pd.Series(dtype="float64"),
                "tolerances": pd.Series(dtype="string"),
                "unit": pd.Series(dtype="string"),
                "assignment_count": pd.Series(dtype="int64"),
                "assignment_status": pd.Series(dtype="string"),
                "pending_assignment_count": pd.Series(dtype="int64"),
                "torque_detail_count": pd.Series(dtype="int64"),
                "equipment_torque_link_count": pd.Series(dtype="int64"),
                "pfmea_pattern_reference_count": pd.Series(dtype="int64"),
                "updated_at": pd.Series(dtype="string"),
            }
        )
    else:
        requirements = requirements.reindex(columns=table_columns).copy()
        requirements["pass_fail"] = requirements["pass_fail"].fillna(0).astype(bool)
        requirements["target_value"] = pd.to_numeric(
            requirements["target_value"], errors="coerce"
        )
        for count_column in [
            "assignment_count", "pending_assignment_count", "torque_detail_count",
            "pfmea_pattern_reference_count", "equipment_torque_link_count",
        ]:
            requirements[count_column] = (
                pd.to_numeric(requirements[count_column], errors="coerce")
                .fillna(0)
                .astype(int)
            )

    requirements["assignment_status"] = requirements["assignment_count"].apply(
        lambda count: "Assigned" if int(count or 0) > 0 else "Unassigned / Needs Process Step"
    )

    catalog_by_key = {
        str(row["label"]).strip().casefold(): row
        for _, row in requirement_type_catalog.iterrows()
    }
    active_type_labels = [
        str(row["label"])
        for _, row in requirement_type_catalog.iterrows()
        if bool(row.get("active"))
    ]
    preserved_type_labels = [
        str(value).strip()
        for value in requirements.get("requirement_type", pd.Series(dtype="string"))
        if str(value).strip()
    ]
    type_options = list(dict.fromkeys([*active_type_labels, *preserved_type_labels]))

    catalog_units: list[str] = []
    for _, row in requirement_type_catalog.iterrows():
        if bool(row.get("active")):
            raw = str(row.get("units_available") or "").strip()
            if raw:
                for u in raw.split(";"):
                    cleaned_u = u.strip()
                    if cleaned_u:
                        catalog_units.append(cleaned_u)

    preserved_units = [
        str(value).strip()
        for value in requirements.get("unit", pd.Series(dtype="string"))
        if str(value).strip()
    ]

    if catalog_units:
        unit_options = list(dict.fromkeys(["", *catalog_units, *preserved_units]))
    else:
        COMMON_QUALITY_UNITS = [
            "",
            "inch", "in", "mm", "cm", "m", "ft", "yd", "µm", "mil",
            "in-lbs", "ft-lbs", "N·m", "cN·m", "in-oz",
            "deg", "°", "rad",
            "lbf", "N", "kN", "psi", "bar", "kPa", "MPa",
            "V", "mV", "A", "mA", "Ω", "kΩ", "Hz",
            "s", "sec", "min", "°C", "°F", "%", "pcs", "kg", "g",
        ]
        unit_options = list(dict.fromkeys(["", *COMMON_QUALITY_UNITS, *preserved_units]))
    type_status_warnings: list[str] = []
    for _, row in requirements.iterrows():
        current_type = str(row.get("requirement_type") or "").strip()
        catalog_row = catalog_by_key.get(current_type.casefold())
        if catalog_row is not None and bool(catalog_row.get("active")):
            continue
        status = "inactive" if catalog_row is not None else "not in the Type catalog"
        type_status_warnings.append(
            f"{row.get('unique_identifier') or 'No identifier'} — {current_type or 'Blank'} "
            f"({status})"
        )

    editable_table_heading("Quality requirements")
    if type_status_warnings:
        st.warning(
            "These saved requirements retain Types that cannot be newly assigned. Choose an "
            "active Type when deliberately reconciling them:\n\n"
            + "\n".join(f"- {warning}" for warning in type_status_warnings)
        )
    visible_requirements = filter_table(
        requirements,
        key=f"quality_requirements_filters_{project_id}",
        dropdown_columns=["requirement_type", "assignment_status", "unit"],
        search_columns=[
            "requirement_type", "description", "unique_identifier", "tolerances", "unit",
        ],
        labels={"requirement_type": "Type", "assignment_status": "Assignment status", "unit": "Unit"},
        reset_widget_keys=[editor_key],
    )
    editor_rows = direct_entry_editor_rows(
        visible_requirements,
        editor_key=editor_key,
        sort_columns=[
            "requirement_type", "unique_identifier", "description", "pass_fail",
            "target_value", "unit", "assignment_count", "pending_assignment_count",
            "updated_at",
        ],
        labels={
            "requirement_type": "Type",
            "unique_identifier": "Unique identifier",
            "pass_fail": "Pass/fail",
            "target_value": "Target value",
            "assignment_count": "Linked Process steps",
            "pending_assignment_count": "Pending linked updates",
            "updated_at": "Updated",
        },
    )
    editor_rows["assignment_count"] = editor_rows["assignment_count"].apply(
        lambda value: "" if pd.isna(value) else str(int(value))
    )

    def show_linked_steps_for_clicked_requirement() -> None:
        requirement_id = stable_id_from_button_click(
            editor_rows, st.session_state.get(linked_steps_click_key)
        )
        if not requirement_id:
            return
        st.session_state[linked_steps_focus_key] = requirement_id
        st.session_state[linked_steps_dialog_key] = requirement_id
        _clear_linked_step_filters(project_id)

    edited_requirements = st.data_editor(
        editor_rows,
        key=editor_key,
        num_rows="dynamic",
        hide_index=True,
        height=430,
        disabled=["id", "assignment_count", "pending_assignment_count", "updated_at"],
        column_order=[
            "requirement_type", "description", "unique_identifier", "pass_fail",
            "target_value", "tolerances", "unit", "assignment_count",
            "pending_assignment_count", "updated_at",
        ],
        column_config={
            "id": None,
            "requirement_type": st.column_config.SelectboxColumn(
                "Type", options=type_options, required=True, pinned=True,
                help=(
                    "Choose an active project Type. Existing inactive or unmatched values "
                    "remain visible but cannot be assigned to another requirement."
                ),
            ),
            "description": st.column_config.TextColumn(
                "Description", required=True, width="large",
                help="State what must be checked and what acceptable work looks like.",
            ),
            "unique_identifier": st.column_config.TextColumn(
                "Unique identifier", required=True,
                help=(
                    "Use a stable project identifier so this definition remains recognizable "
                    "when its description changes."
                ),
            ),
            "pass_fail": st.column_config.CheckboxColumn(
                "Pass/fail", default=False,
                help="Turn on when the result is recorded as a pass-or-fail check.",
            ),
            "target_value": st.column_config.NumberColumn(
                "Target value", help="Enter the required numeric value when the check has one.",
            ),
            "tolerances": st.column_config.TextColumn(
                "Tolerances", help="Describe the permitted variation around the target value.",
            ),
            "unit": st.column_config.SelectboxColumn(
                "Unit",
                options=unit_options,
                help=(
                    "Choose a unit for the requirement (e.g. mm or in for Dimensions; "
                    "in-lbs, ft-lbs, or N·m for Torque)."
                ),
            ),
            "assignment_count": st.column_config.ButtonColumn(
                "Linked Process steps",
                type="tertiary",
                on_click=show_linked_steps_for_clicked_requirement,
                key=linked_steps_click_key,
                help="Number of Process at a Glance steps currently using this requirement.",
            ),
            "pending_assignment_count": st.column_config.NumberColumn(
                "Pending linked updates",
                help=(
                    "Number of linked Process requirements still carrying the previously "
                    "published values."
                ),
            ),
            "updated_at": st.column_config.DatetimeColumn(
                "Updated", format="MMM DD, YYYY HH:mm"
            ),
            "torque_detail_count": None,
            "pfmea_pattern_reference_count": None,
        },
    )
    footer_actions = editable_table_footer(
        editor_key=editor_key,
        key_prefix=f"quality_requirements_{project_id}",
        native_row_selection=True,
    )
    if footer_actions.undo:
        request_table_editor_reset(editor_key)
        st.toast("Discarded the unsaved Quality requirement edits", icon=":material/undo:")
        st.rerun()

    st.caption(
        "Type or paste new requirements into the blank entry row. Save repository edits "
        "before publishing them to linked Process at a Glance steps."
    )
    export_columns = [
        "requirement_type", "description", "unique_identifier", "pass_fail",
        "target_value", "tolerances", "unit", "assignment_count",
        "pending_assignment_count", "updated_at",
    ]
    col_exp, col_assign = st.columns([1, 1.5])
    with col_exp:
        st.download_button(
            "Export filtered rows",
            data=dataframe_to_excel(
                visible_requirements.reindex(columns=export_columns), "Quality requirements"
            ),
            file_name="quality_requirements_filtered.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
        )
    with col_assign:
        if st.button(
            "Assign to Process Steps",
            icon=":material/playlist_add_check:",
            key=f"btn_open_bulk_assign_{project_id}",
            help="Open assignment dialog to filter steps by Pitch and bulk attach requirements.",
        ):
            open_assign_requirement_dialog()
            st.rerun()

    selected_requirements_for_deletion = native_selected_rows(
        editor_rows, editor_key=editor_key
    )

    if not selected_requirements_for_deletion.empty:
        if table_has_unsaved_changes(editor_key, native_row_selection=True):
            st.warning(
                "Save or undo other table edits before deleting selected Quality requirements."
            )
        else:
            st.session_state[pending_delete_key] = [
                {
                    "id": str(row["id"]),
                    "unique_identifier": str(row["unique_identifier"]),
                    "description": str(row["description"]),
                    "assignment_count": int(row.get("assignment_count") or 0),
                    "torque_detail_count": int(row.get("torque_detail_count") or 0),
                    "pfmea_pattern_reference_count": int(
                        row.get("pfmea_pattern_reference_count") or 0
                    ),
                }
                for _, row in selected_requirements_for_deletion.iterrows()
            ]
            stage_native_delete_confirmation(editor_key)

    @st.dialog("Delete selected Quality requirements?", dismissible=False)
    def confirm_quality_requirement_delete() -> None:
        pending = st.session_state.get(pending_delete_key, [])
        linked_count = sum(int(item["assignment_count"]) for item in pending)
        torque_detail_count = sum(int(item["torque_detail_count"]) for item in pending)
        pattern_reference_count = sum(
            int(item.get("pfmea_pattern_reference_count", 0)) for item in pending
        )
        st.warning(
            f"Delete {len(pending)} selected Quality requirement(s)? This permanently "
            "removes the project repository definitions."
        )
        for item in pending:
            st.write(
                f"- {item['unique_identifier']}: {item['description']} "
                f"— {item['assignment_count']} linked Process step(s), "
                f"{item['torque_detail_count']} Torque tool detail record(s), "
                f"{item.get('pfmea_pattern_reference_count', 0)} PFMEA pattern reference(s)"
            )
        if linked_count:
            st.error(
                "These definitions cannot be deleted until their linked Process requirement "
                "assignments are removed."
            )
        if torque_detail_count:
            st.error(
                "These definitions cannot be deleted until their linked Torque tool "
                "details are removed."
            )
        if pattern_reference_count:
            st.error(
                "These definitions cannot be deleted until their PFMEA pattern control "
                "references are removed."
            )
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_quality_requirement_delete_{project_id}"):
            st.session_state.pop(pending_delete_key, None)
            request_table_editor_reset(editor_key)
            st.rerun()
        if actions.button(
            "Delete", type="primary", icon=":material/delete:",
            disabled=bool(linked_count or torque_detail_count or pattern_reference_count),
            key=f"destructive_confirm_quality_requirement_delete_{project_id}",
        ):
            try:
                requirement_ids = [item["id"] for item in pending]
                deleted_count = quality_store.delete_quality_requirements(project_id, requirement_ids)
                record_audit_event(
                    project_id, "Quality requirements", "Bulk delete", deleted_count,
                    st.session_state.get("current_editor", ""),
                    {
                        "requirement_ids": requirement_ids,
                        "unique_identifiers": [item["unique_identifier"] for item in pending],
                    },
                )
                st.session_state.pop(pending_delete_key, None)
                request_table_editor_reset(editor_key)
                st.toast(
                    f"Deleted {deleted_count} Quality requirement(s)", icon=":material/delete:"
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if st.session_state.get(pending_delete_key):
        confirm_quality_requirement_delete()

    if footer_actions.save_and_refresh:
        try:
            if not selected_requirements_for_deletion.empty:
                raise ValueError(
                    "Clear selected rows before saving table edits. Selection is reserved "
                    "for the confirmed deletion workflow."
                )
            edited_requirements = drop_untouched_new_rows(
                edited_requirements,
                identifying_columns=["requirement_type", "description", "unique_identifier"],
            )
            validation_errors = required_field_errors(
                edited_requirements,
                {
                    "requirement_type": "Type",
                    "description": "Description",
                    "unique_identifier": "Unique identifier",
                },
            )
            if validation_errors:
                raise ValueError(" ".join(validation_errors))
            combined_requirements = merge_filtered_edits(
                requirements, visible_requirements, edited_requirements
            )
            result = quality_store.save_quality_requirement_rows(
                project_id,
                combined_requirements.reindex(
                    columns=[
                        "id", "requirement_type", "description", "unique_identifier",
                        "pass_fail", "target_value", "tolerances", "unit",
                    ]
                ),
            )
            changed_count = int(result["row_count"])
            if changed_count:
                record_audit_event(
                    project_id, "Quality requirements", "Save & Refresh", changed_count,
                    st.session_state.get("current_editor", ""),
                    {
                        "created_ids": result["created_ids"],
                        "updated_ids": result["updated_ids"],
                        "store_timestamp": result["timestamp"],
                    },
                )
            request_table_editor_reset(editor_key)
            st.toast(
                (
                    f"Saved {changed_count} Quality requirement(s)"
                    if changed_count else "Quality requirements are already up to date"
                ),
                icon=":material/check_circle:",
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    has_unsaved_edits = table_has_unsaved_changes(
        editor_key, native_row_selection=True
    )

    render_quality_requirement_type_catalog(
        project_id,
        repository_editor_key=editor_key,
        repository_busy=(
            has_unsaved_edits or not selected_requirements_for_deletion.empty
        ),
    )

    linked_process_section = st.container()
    if False:  # Legacy Torque editor moved to Quality → Equipment.
        selected_torque_requirement_id = str(selected_torque_requirement_id)
        torque_editor_key = apply_pending_table_editor_reset(
            f"quality_torque_details_editor_{project_id}_{selected_torque_requirement_id}"
        )
        torque_pending_delete_key = (
            f"quality_torque_details_pending_delete_{project_id}_"
            f"{selected_torque_requirement_id}"
        )
        torque_details = quality_store.quality_requirement_torque_details(
            project_id, selected_torque_requirement_id
        )
        if torque_details.empty:
            torque_details = pd.DataFrame(
                [
                    {
                        "id": "",
                        "project_id": project_id,
                        "quality_requirement_id": selected_torque_requirement_id,
                        "tool_type": "",
                        "tool_orientation": "",
                        "screw_bit_type": "",
                        "created_at": "",
                        "updated_at": "",
                    }
                ]
            )
        current_screw_bit_type = str(
            torque_details.iloc[0].get("screw_bit_type") or ""
        ).strip()
        screw_bit_options = quality_store.torque_screw_bit_types(project_id)
        if current_screw_bit_type and current_screw_bit_type not in screw_bit_options:
            screw_bit_options.append(current_screw_bit_type)
            screw_bit_options.sort(key=str.casefold)
        screw_bit_key = (
            f"quality_torque_screw_bit_type_{project_id}_{selected_torque_requirement_id}"
        )
        screw_bit_type = st.selectbox(
            "Screw bit type",
            options=screw_bit_options,
            index=(
                screw_bit_options.index(current_screw_bit_type)
                if current_screw_bit_type else None
            ),
            placeholder="Choose a previous value or enter a new one",
            accept_new_options=True,
            key=screw_bit_key,
            help=(
                "Choose a Screw bit type already used in this project or type a new value. "
                "New values become available after Save & Refresh."
            ),
        )
        torque_details = torque_details.copy()
        torque_details["screw_bit_type"] = str(screw_bit_type or "").strip()
        torque_editor_rows = direct_entry_editor_rows(
            torque_details,
            editor_key=torque_editor_key,
            sort_columns=["tool_type", "tool_orientation", "screw_bit_type"],
            labels={
                "tool_type": "Tool type",
                "tool_orientation": "Tool orientation",
                "screw_bit_type": "Screw bit type",
            },
        )
        edited_torque_details = st.data_editor(
            torque_editor_rows,
            key=torque_editor_key,
            num_rows="dynamic",
            hide_index=True,
            disabled=[
                "id", "project_id", "quality_requirement_id", "screw_bit_type",
                "created_at", "updated_at",
            ],
            column_order=[
                "tool_type", "tool_orientation", "screw_bit_type", "updated_at",
            ],
            column_config={
                "id": None,
                "project_id": None,
                "quality_requirement_id": None,
                "tool_type": st.column_config.SelectboxColumn(
                    "Tool type",
                    options=TORQUE_TOOL_TYPES,
                    required=True,
                    help="Select the power and control category used by the torque tool.",
                ),
                "tool_orientation": st.column_config.SelectboxColumn(
                    "Tool orientation",
                    options=TORQUE_TOOL_ORIENTATIONS,
                    required=True,
                    help="Select how the torque tool is held or positioned during use.",
                ),
                "screw_bit_type": st.column_config.TextColumn(
                    "Screw bit type",
                    required=True,
                    help="Use the selector above to choose a previous value or enter a new one.",
                ),
                "created_at": None,
                "updated_at": st.column_config.DatetimeColumn(
                    "Updated", format="MMM DD, YYYY HH:mm"
                ),
            },
        )
        screw_bit_changed = current_screw_bit_type != str(screw_bit_type or "").strip()
        torque_footer_actions = editable_table_footer(
            editor_key=torque_editor_key,
            key_prefix=(
                f"quality_torque_details_{project_id}_{selected_torque_requirement_id}"
            ),
            native_row_selection=True,
            additional_unsaved_changes=screw_bit_changed,
        )
        if torque_footer_actions.undo:
            st.session_state.pop(screw_bit_key, None)
            request_table_editor_reset(torque_editor_key)
            st.toast("Discarded the unsaved Torque tool detail edits", icon=":material/undo:")
            st.rerun()

        selected_torque_details = native_selected_rows(
            torque_editor_rows, editor_key=torque_editor_key
        )
        if not selected_torque_details.empty:
            if table_has_unsaved_changes(
                torque_editor_key, native_row_selection=True
            ) or screw_bit_changed:
                st.warning("Save or undo other edits before deleting Torque tool details.")
            else:
                st.session_state[torque_pending_delete_key] = [
                    {
                        "id": str(row["id"]),
                        "tool_type": str(row["tool_type"]),
                        "tool_orientation": str(row["tool_orientation"]),
                        "screw_bit_type": str(row["screw_bit_type"]),
                    }
                    for _, row in selected_torque_details.iterrows()
                ]
                stage_native_delete_confirmation(torque_editor_key)

        @st.dialog("Delete selected Torque tool details?", dismissible=False)
        def confirm_torque_detail_delete() -> None:
            pending = st.session_state.get(torque_pending_delete_key, [])
            st.warning(
                "Delete the selected Torque tool detail record? The linked Quality "
                "requirement and its Process-step assignments will be preserved."
            )
            for item in pending:
                st.write(
                    f"- {item['tool_type']} · {item['tool_orientation']} · "
                    f"{item['screw_bit_type']}"
                )
            actions = st.container(horizontal=True)
            if actions.button(
                "Cancel",
                key=(
                    f"cancel_quality_torque_detail_delete_{project_id}_"
                    f"{selected_torque_requirement_id}"
                ),
            ):
                st.session_state.pop(torque_pending_delete_key, None)
                request_table_editor_reset(torque_editor_key)
                st.rerun()
            if actions.button(
                "Delete",
                type="primary",
                icon=":material/delete:",
                key=(
                    f"destructive_confirm_quality_torque_detail_delete_{project_id}_"
                    f"{selected_torque_requirement_id}"
                ),
            ):
                try:
                    detail_ids = [str(item["id"]) for item in pending]
                    deleted_count = quality_store.delete_quality_requirement_torque_details(
                        project_id, selected_torque_requirement_id, detail_ids
                    )
                    record_audit_event(
                        project_id,
                        "Quality requirements",
                        "Delete Torque tool details",
                        deleted_count,
                        st.session_state.get("current_editor", ""),
                        {
                            "quality_requirement_id": selected_torque_requirement_id,
                            "detail_ids": detail_ids,
                        },
                    )
                    st.session_state.pop(torque_pending_delete_key, None)
                    st.session_state.pop(screw_bit_key, None)
                    request_table_editor_reset(torque_editor_key)
                    st.toast("Deleted the Torque tool details", icon=":material/delete:")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        if st.session_state.get(torque_pending_delete_key):
            confirm_torque_detail_delete()

        if torque_footer_actions.save_and_refresh:
            try:
                if not selected_torque_details.empty:
                    raise ValueError(
                        "Clear selected rows before saving. Selection is reserved for "
                        "the confirmed deletion workflow."
                    )
                prepared_torque_details = drop_untouched_new_rows(
                    edited_torque_details,
                    identifying_columns=[
                        "tool_type", "tool_orientation", "screw_bit_type",
                    ],
                )
                if len(prepared_torque_details) > 1:
                    raise ValueError(
                        "Each Torque requirement can have only one Torque tool detail record."
                    )
                if prepared_torque_details.empty:
                    raise ValueError("Enter the Torque tool details before saving.")
                prepared_torque_details = prepared_torque_details.copy()
                prepared_torque_details.loc[:, "screw_bit_type"] = str(
                    screw_bit_type or ""
                ).strip()
                validation_errors = required_field_errors(
                    prepared_torque_details,
                    {
                        "tool_type": "Tool type",
                        "tool_orientation": "Tool orientation",
                        "screw_bit_type": "Screw bit type",
                    },
                )
                if validation_errors:
                    raise ValueError(" ".join(validation_errors))
                result = quality_store.save_quality_requirement_torque_detail(
                    project_id,
                    selected_torque_requirement_id,
                    prepared_torque_details.iloc[0].to_dict(),
                )
                changed_count = int(result["row_count"])
                if changed_count:
                    record_audit_event(
                        project_id,
                        "Quality requirements",
                        "Save & Refresh Torque tool details",
                        changed_count,
                        st.session_state.get("current_editor", ""),
                        {
                            "quality_requirement_id": selected_torque_requirement_id,
                            "torque_detail_id": result["id"],
                            "store_timestamp": result["timestamp"],
                        },
                    )
                st.session_state.pop(screw_bit_key, None)
                request_table_editor_reset(torque_editor_key)
                st.toast(
                    (
                        "Saved the Torque tool details"
                        if changed_count else "Torque tool details are already up to date"
                    ),
                    icon=":material/check_circle:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    linked_process_section.__enter__()
    st.divider()
    all_requirement_links = quality_store.quality_requirement_links(project_id)
    if active_scenario:
        c_head, c_btn = st.columns([3, 1])
        with c_head:
            section_heading_with_scope(
                "Link to Process at a Glance",
                scope="scenario",
                scenario_name=str(active_scenario["name"]),
            )
            st.caption(
                f"Attach saved repository requirements to Process at a Glance steps within Rev "
                f"{active_scenario['revision_label']} · {active_scenario['name']}. Links "
                "continue to follow the same step when its Pitch or Seq changes."
            )
        with c_btn:
            st.write("")
            if st.button(
                "🔗 Assign Steps...",
                type="primary",
                key=f"btn_bulk_assign_from_link_panel_{project_id}_{scenario_id}",
                help="Open assignment dialog with Pitch filter and multi-select to attach requirements.",
                disabled=has_unsaved_edits,
            ):
                open_assign_requirement_dialog()
                st.rerun()
        if has_unsaved_edits:
            st.info(
                "Save or undo repository table edits before attaching or unlinking a requirement."
            )
    else:
        st.subheader("Link to Process at a Glance")
        st.info(
            "Select an active planning scenario before attaching or unlinking Quality requirements."
        )

    @st.dialog("Unlink Quality requirement process link(s)?", dismissible=False)
    def confirm_quality_requirement_unlink() -> None:
        pending = st.session_state.get(pending_unlink_key, {})
        assignment_ids = [
            str(aid)
            for aid in (
                pending.get("assignment_ids")
                or ([pending["assignment_id"]] if pending.get("assignment_id") else [])
            )
        ]
        count = len(assignment_ids)
        st.warning(
            f"Unlink {count} selected Process at a Glance link{'s' if count != 1 else ''}?"
        )
        st.write(
            "Only scenario-specific connection(s) will be removed. Saved Quality requirements "
            "and Process at a Glance steps will be preserved."
        )
        items = pending.get("items") or []
        if items:
            for item in items[:10]:
                req = item.get("requirement", "Quality requirement")
                step = item.get("process_step", "Process step")
                st.write(f"- **{req}** linked to **{step}**")
            if len(items) > 10:
                st.caption(f"...and {len(items) - 10} more link(s)")
        elif pending.get("requirement") and pending.get("process_step"):
            st.write(
                f"- **{pending['requirement']}** linked to **{pending['process_step']}**"
            )

        pfmea_impact = pending.get("pfmea_impact") or {}
        control_plan_impact = pending.get("control_plan_impact") or {}
        if int(pfmea_impact.get("selection_count", 0)):
            st.warning(
                f"This also removes {pfmea_impact['selection_count']} dependent structured "
                f"PFMEA control selection(s) from {pfmea_impact.get('cause_count', 0)} Cause(s). "
                "Those Causes will be marked Review required; Detection ratings are preserved."
            )
        if int(control_plan_impact.get("item_count", 0)):
            st.warning(
                f"This also preserves {control_plan_impact['item_count']} dependent Control "
                "Plan working-draft item(s) as orphaned records for explicit review and relinking."
            )
        scenario_changed = str(pending.get("scenario_id") or "") != scenario_id
        if scenario_changed:
            st.error(
                "The active planning scenario changed. Cancel and choose the link again."
            )
        actions = st.container(horizontal=True)
        if actions.button(
            "Cancel", key=f"cancel_quality_requirement_unlink_{project_id}"
        ):
            st.session_state.pop(pending_unlink_key, None)
            st.rerun()
        if actions.button(
            "Unlink",
            type="primary",
            icon=":material/link_off:",
            disabled=scenario_changed or not assignment_ids,
            key=(
                f"destructive_confirm_quality_requirement_unlink_{project_id}_"
                f"{'_'.join(assignment_ids[:3])}"
            ),
        ):
            try:
                deleted_count = quality_store.delete_quality_requirement_assignments(
                    project_id,
                    str(pending["scenario_id"]),
                    assignment_ids,
                    st.session_state.get("current_editor", ""),
                )
                record_audit_event(
                    project_id,
                    "Quality requirements",
                    "Unlink from Process step",
                    deleted_count,
                    st.session_state.get("current_editor", ""),
                    pending,
                )
                if int(pfmea_impact.get("selection_count", 0)):
                    record_audit_event(
                        project_id,
                        "PFMEA",
                        "Quality assignment unlink cascade",
                        int(pfmea_impact["selection_count"]),
                        st.session_state.get("current_editor", ""),
                        {
                            "scenario_id": pending["scenario_id"],
                            "assignment_ids": assignment_ids,
                            "cause_count": pfmea_impact.get("cause_count", 0),
                        },
                    )
                st.session_state.pop(pending_unlink_key, None)
                st.toast(
                    f"Unlinked {deleted_count} Quality requirement link{'s' if deleted_count != 1 else ''}",
                    icon=":material/check_circle:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if st.session_state.get(pending_unlink_key):
        confirm_quality_requirement_unlink()

    focused_requirement_id = str(
        st.session_state.get(linked_steps_focus_key) or ""
    ).strip()
    dialog_requirement_id = str(
        st.session_state.get(linked_steps_dialog_key) or ""
    ).strip()
    requirement_ids = set(
        requirements.get("id", pd.Series(dtype="string")).dropna().astype(str)
    )
    if focused_requirement_id and focused_requirement_id not in requirement_ids:
        st.session_state.pop(linked_steps_focus_key, None)
        focused_requirement_id = ""
    if dialog_requirement_id and dialog_requirement_id not in requirement_ids:
        st.session_state.pop(linked_steps_dialog_key, None)
        dialog_requirement_id = ""

    def clear_linked_steps_dialog_request() -> None:
        st.session_state.pop(linked_steps_dialog_key, None)

    @st.dialog(
        "Linked Process steps",
        width="large",
        icon=":material/account_tree:",
        on_dismiss=clear_linked_steps_dialog_request,
    )
    def show_linked_steps_dialog() -> None:
        requirement_id = str(
            st.session_state.get(linked_steps_dialog_key) or ""
        ).strip()
        requirement_rows = requirements.loc[
            requirements["id"].astype(str).eq(requirement_id)
        ]
        if requirement_rows.empty:
            st.error("This Quality requirement is no longer available in this project.")
        else:
            identifier, description = _requirement_friendly_values(
                requirement_rows.iloc[0]
            )
            st.markdown(f"**{identifier}** — {description}")
            st.caption(
                "These are the published links currently attached across this project's "
                "planning scenarios."
            )
            if "quality_requirement_id" in all_requirement_links:
                dialog_source = all_requirement_links.loc[
                    all_requirement_links["quality_requirement_id"]
                    .astype(str)
                    .eq(requirement_id)
                ].copy()
            else:
                dialog_source = all_requirement_links.iloc[0:0].copy()
            dialog_rows = _linked_step_display_rows(dialog_source).reindex(
                columns=LINKED_STEP_DIALOG_COLUMNS
            )
            if dialog_rows.empty:
                st.info("No linked Process steps")
            else:
                st.caption(
                    f"{len(dialog_rows)} linked Process step"
                    f"{'s' if len(dialog_rows) != 1 else ''}"
                )
                dialog_table_key = (
                    "quality_requirement_linked_steps_dialog_table_"
                    f"{project_id}_{requirement_id}"
                )
                selectable_dataframe(
                    dialog_rows,
                    key=dialog_table_key,
                    hide_index=True,
                    column_config={
                        "Scenario": st.column_config.TextColumn("Scenario", pinned=True),
                        "Pitch": st.column_config.TextColumn("Pitch", pinned=True),
                        "Pitch Name": st.column_config.TextColumn("Pitch Name"),
                        "Work Element": st.column_config.TextColumn(
                            "Work Element", width="large"
                        ),
                        "Status": st.column_config.TextColumn("Status"),
                        "Seq": st.column_config.NumberColumn("Seq", format="%d"),
                        "Repository update pending": st.column_config.CheckboxColumn(
                            "Repository update pending",
                            help=(
                                "Shows that the saved repository definition differs from "
                                "the published values attached to this Process step."
                            ),
                        ),
                        "Upstream modified": st.column_config.CheckboxColumn(
                            "Upstream modified",
                            help=(
                                "Shows that upstream PAAG step attributes (pitch, operation, or description) "
                                "have changed since the requirement was attached."
                            ),
                        ),
                    },
                )

        dialog_actions = st.container(
            horizontal=True,
            horizontal_alignment="right",
        )
        if dialog_actions.button(
            "Close",
            icon=":material/close:",
            key=f"close_quality_requirement_linked_steps_{project_id}",
        ):
            clear_linked_steps_dialog_request()
            st.rerun()

    if dialog_requirement_id and not any(
        st.session_state.get(key)
        for key in (pending_delete_key, pending_push_key, pending_unlink_key)
    ):
        show_linked_steps_dialog()

    with st.expander(
        "View Quality requirements linked to Process steps",
        icon=":material/account_tree:",
        expanded=bool(focused_requirement_id),
    ):
        st.caption(
            "Each row shows the published requirement values attached to one Process at a "
            "Glance step across every planning scenario in this project."
        )
        linked_steps_source = all_requirement_links.copy()
        if focused_requirement_id:
            focused_requirement = requirements.loc[
                requirements["id"].astype(str).eq(focused_requirement_id)
            ].iloc[0]
            focused_identifier, focused_description = _requirement_friendly_values(
                focused_requirement
            )
            st.caption(f"Showing links for {focused_identifier} — {focused_description}")
            if "quality_requirement_id" in linked_steps_source:
                linked_steps_source = linked_steps_source.loc[
                    linked_steps_source["quality_requirement_id"]
                    .astype(str)
                    .eq(focused_requirement_id)
                ].copy()
            else:
                linked_steps_source = linked_steps_source.iloc[0:0].copy()
            if st.button(
                "Show all linked Process steps",
                icon=":material/select_all:",
                key=f"quality_requirement_show_all_linked_steps_{project_id}",
            ):
                st.session_state.pop(linked_steps_focus_key, None)
                st.session_state.pop(linked_steps_dialog_key, None)
                _clear_linked_step_filters(project_id)
                st.rerun()

        if linked_steps_source.empty:
            st.caption(
                (
                    "No linked Process steps were found for this Quality requirement."
                    if focused_requirement_id
                    else "No Quality requirements are linked to Process at a Glance steps "
                    "in this project."
                )
            )
        else:
            linked_step_rows = _linked_step_display_rows(linked_steps_source)
            visible_linked_steps = filter_table(
                linked_step_rows,
                key=f"quality_requirement_linked_step_filters_{project_id}",
                dropdown_columns=LINKED_STEP_FILTER_COLUMNS,
                search_columns=[
                    "Scenario", "Pitch", "Pitch Name", "Work Element", "Status",
                    "Quality requirement Unique identifier", "Type", "Description",
                    "Tolerances", "Unit",
                ],
                labels={
                    "Quality requirement Unique identifier": "Quality requirement",
                },
            )
            linked_steps_table_key = f"quality_requirement_linked_steps_{project_id}"
            selection_event = selectable_dataframe(
                visible_linked_steps,
                key=linked_steps_table_key,
                hide_index=True,
                column_order=LINKED_STEP_VISIBLE_COLUMNS,
                column_config={
                    "Scenario": st.column_config.TextColumn("Scenario", pinned=True),
                    "Op ID": st.column_config.TextColumn("Op ID", pinned=True),
                    "Pitch": st.column_config.TextColumn("Pitch", pinned=True),
                    "Pitch Name": st.column_config.TextColumn("Pitch Name"),
                    "Work Element": st.column_config.TextColumn("Work Element", width="large"),
                    "Status": st.column_config.TextColumn("Status"),
                    "Seq": st.column_config.NumberColumn("Seq", format="%d"),
                    "Quality requirement Unique identifier": st.column_config.TextColumn(
                        "Quality requirement Unique identifier",
                        pinned=True,
                        help="The published Unique identifier currently attached to this Process step.",
                    ),
                    "Type": st.column_config.TextColumn("Type"),
                    "Description": st.column_config.TextColumn("Description", width="large"),
                    "Pass/fail": st.column_config.CheckboxColumn("Pass/fail"),
                    "Target value": st.column_config.NumberColumn("Target value"),
                    "Tolerances": st.column_config.TextColumn("Tolerances"),
                    "Unit": st.column_config.TextColumn("Unit"),
                    "Repository update pending": st.column_config.CheckboxColumn(
                        "Repository update pending",
                        help=(
                            "Shows that the saved repository definition differs from the "
                            "published values currently attached to this Process step."
                        ),
                    ),
                    "Upstream modified": st.column_config.CheckboxColumn(
                        "Upstream modified",
                        help=(
                            "Shows that upstream PAAG step attributes (pitch, operation, or description) "
                            "have changed since the requirement was attached."
                        ),
                    ),
                },
            )
            selected_links = selected_dataframe_rows(
                visible_linked_steps, selection_event, id_column="Quality requirement Unique identifier"
            )
            if not selected_links.empty:
                action_bar = selected_rows_action_bar()
                unlink_count = len(selected_links)
                if action_bar.button(
                    f"Unlink {unlink_count} selected link{'s' if unlink_count != 1 else ''}",
                    type="primary",
                    icon=":material/link_off:",
                    disabled=has_unsaved_edits,
                    key=f"quality_requirement_request_bulk_unlink_{project_id}",
                ):
                    items = []
                    for s_idx, s_row in selected_links.iterrows():
                        source_row = linked_steps_source.loc[s_idx]
                        op = str(s_row.get("Op ID") or "No Op ID")
                        we = str(s_row.get("Work Element") or "Unnamed work element")
                        pn = str(s_row.get("Pitch Name") or "")
                        step_str = f"{op} - {we}{' (' + pn + ')' if pn else ''}"
                        req_id_val = str(s_row.get("Quality requirement Unique identifier") or "")
                        desc_val = str(s_row.get("Description") or "")
                        req_str = f"{req_id_val} — {desc_val}" if desc_val else req_id_val
                        items.append({
                            "assignment_id": str(source_row["assignment_id"]),
                            "scenario_id": str(source_row["scenario_id"]),
                            "requirement": req_str,
                            "process_step": step_str,
                        })
                    sc_id = str(items[0]["scenario_id"])
                    ass_ids = [str(r["assignment_id"]) for r in items]
                    st.session_state[pending_unlink_key] = {
                        "assignment_ids": ass_ids,
                        "scenario_id": sc_id,
                        "items": items,
                        "pfmea_impact": quality_store.quality_assignment_pfmea_impact(
                            project_id, sc_id, ass_ids
                        ),
                        "control_plan_impact": control_plan_assignment_impact(
                            project_id, sc_id, ass_ids
                        ),
                    }
                    st.rerun()

    linked_process_section.__exit__(None, None, None)

    pending_push = requirements.loc[
        requirements["pending_assignment_count"].fillna(0).astype(int) > 0
    ].copy()
    st.subheader("Publish saved updates")
    st.caption(
        "Publishing replaces linked Process requirement copies with the currently saved "
        "repository values. Unsaved table edits are never published."
    )
    push_updates = st.button(
        "Push saved updates to linked Process steps",
        type="primary",
        icon=":material/publish:",
        disabled=pending_push.empty or has_unsaved_edits,
        help=(
            "Review and publish every saved repository definition that has older values "
            "on linked Process at a Glance steps."
        ),
    )
    if has_unsaved_edits and not pending_push.empty:
        st.info("Save or undo the current table edits before publishing saved updates.")
    elif pending_push.empty:
        st.caption("All linked Process requirements already match the saved repository.")

    if push_updates:
        st.session_state[pending_push_key] = [
            {
                "id": str(row["id"]),
                "unique_identifier": str(row["unique_identifier"]),
                "pending_assignment_count": int(row["pending_assignment_count"]),
            }
            for _, row in pending_push.iterrows()
        ]

    @st.dialog("Push saved Quality requirement updates?", dismissible=False)
    def confirm_quality_requirement_push() -> None:
        pending = st.session_state.get(pending_push_key, [])
        affected_count = sum(int(item["pending_assignment_count"]) for item in pending)
        st.warning(
            f"Update {affected_count} linked Process requirement(s) with the "
            "saved repository values?"
        )
        for item in pending:
            st.write(
                f"- {item['unique_identifier']} — "
                f"{item['pending_assignment_count']} linked update(s)"
            )
        actions = st.container(horizontal=True)
        if actions.button("Cancel", key=f"cancel_quality_requirement_push_{project_id}"):
            st.session_state.pop(pending_push_key, None)
            st.rerun()
        if actions.button(
            "Push updates", type="primary", icon=":material/publish:",
            key=f"confirm_quality_requirement_push_{project_id}",
        ):
            try:
                requirement_ids = [item["id"] for item in pending]
                updated_count = quality_store.push_quality_requirements(project_id, requirement_ids)
                record_audit_event(
                    project_id, "Quality requirements", "Push to linked Process steps",
                    updated_count, st.session_state.get("current_editor", ""),
                    {
                        "requirement_ids": requirement_ids,
                        "unique_identifiers": [item["unique_identifier"] for item in pending],
                    },
                )
                st.session_state.pop(pending_push_key, None)
                request_table_editor_reset(editor_key)
                st.toast(
                    f"Updated {updated_count} linked Process requirement(s)",
                    icon=":material/check_circle:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if st.session_state.get(pending_push_key):
        confirm_quality_requirement_push()
