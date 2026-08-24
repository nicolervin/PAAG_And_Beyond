import pandas as pd
import streamlit as st

from utils.scope_ui import page_title_with_scope, section_heading_with_scope
from utils.table_filters import apply_pending_table_editor_reset, filter_table, merge_filtered_edits, request_table_editor_reset
from utils.table_ui import (
    dataframe_to_excel, drop_untouched_new_rows, editable_table_header,
    native_selected_rows, required_field_errors, selectable_dataframe,
    direct_entry_editor_rows, standard_details_column_config,
)
from utils.store import (
    audit_history, create_project, get_planning_scenario, get_project,
    next_scenario_revision_label, planning_scenarios, project_table,
    record_audit_event, save_planning_scenario_rows, update_project,
)


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
page_title_with_scope(
    "Project overview",
    scope="scenario-aware",
    help_text=(
        "Project definition data is shared across every scenario. The planning scenarios "
        "table identifies the currently selected scenario and manages every saved branch."
    ),
)
st.caption("The current snapshot of an evolving NPI process plan.")


@st.dialog("Create an NPI project")
def new_project_dialog():
    with st.form("new_project"):
        name = st.text_input("Project name")
        program = st.text_input("Program or product")
        product_line = st.text_input("Product line")
        owner = st.text_input("Lead industrial engineer")
        takt = st.number_input("Target takt time (seconds)", min_value=0.1, value=60.0)
        if st.form_submit_button("Create project", type="primary", icon=":material/add:"):
            if not name.strip():
                st.error("Project name is required.")
            else:
                st.session_state.project_id = create_project(
                    name, program, owner, takt, product_line=product_line
                )
                st.rerun()


with st.container(horizontal=True, horizontal_alignment="right"):
    if st.button("New project", icon=":material/add:"):
        new_project_dialog()

if not project_id:
    st.info("Create a project to begin.")
    st.stop()

project = get_project(project_id)
scenario = get_planning_scenario(project_id, scenario_id) if scenario_id else None
parts = project_table("parts", project_id)
elements = project_table("work_elements", project_id, "sequence", scenario_id=scenario_id)
concerns = project_table("concerns", project_id)
total_cycle = float(elements["cycle_time_s"].sum()) if not elements.empty else 0
open_concerns = int((concerns["status"] != "Closed").sum()) if not concerns.empty else 0

metric_cols = st.columns(4)
metric_cols[0].metric("Parts", len(parts), border=True)
metric_cols[1].metric("Work elements", len(elements), border=True)
active_takt = float((scenario or project)["takt_time_s"])
metric_cols[2].metric(
    "Draft cycle time", f"{total_cycle:.1f} s",
    delta=f"{total_cycle - active_takt:+.1f} s vs takt",
    delta_color="inverse", border=True,
)
metric_cols[3].metric("Open concerns", open_concerns, border=True)

with st.container(border=True):
    section_heading_with_scope("Project definition", scope="project")
    with st.form("project_details"):
        identity_row = st.columns(2)
        name = identity_row[0].text_input("Project name", value=project["name"])
        program = identity_row[1].text_input("Program or product", value=project["program"])
        ownership_row = st.columns(2)
        product_line = ownership_row[0].text_input(
            "Product line", value=project.get("product_line", "")
        )
        owner = ownership_row[1].text_input("Lead industrial engineer", value=project["owner"])
        row = st.columns(3)
        revision = row[0].text_input("Product baseline revision", value=project["revision"])
        project_statuses = ["Draft", "In review", "Released", "On hold"]
        status = row[1].selectbox(
            "Status", project_statuses,
            index=project_statuses.index(project["status"]) if project["status"] in project_statuses else 0,
        )
        takt = row[2].number_input(
            "Default takt for new scenarios", min_value=0.1,
            value=float(project["takt_time_s"]),
        )
        notes = st.text_area(
            "Planning notes", value=project["notes"],
            placeholder="Assumptions, scope, milestones, or known changes…",
        )
        if st.form_submit_button("Save project", type="primary", icon=":material/save:"):
            update_project(
                project_id,
                {
                    "name": name, "program": program, "product_line": product_line,
                    "owner": owner, "revision": revision, "status": status,
                    "takt_time_s": takt, "notes": notes,
                },
            )
            st.toast("Project saved", icon=":material/check_circle:")
            st.rerun()

if scenario:
    scenario_editor_key = f"overview_scenario_editor_{project_id}"
    apply_pending_table_editor_reset(scenario_editor_key)
    all_scenarios = planning_scenarios(project_id, include_archived=True)
    scenario_columns = [
        "id", "view_details", "current_view", "name", "revision_label", "status",
        "takt_time_s", "change_summary", "parent_scenario_id", "parent_scenario",
        "created_by", "created_at", "updated_at",
    ]
    scenario_rows = pd.DataFrame(all_scenarios)
    scenario_rows["view_details"] = ":material/visibility: View details"
    scenario_rows["current_view"] = scenario_rows["id"].astype(str).map(
        lambda value: "Current view" if value == str(scenario_id) else ""
    )
    scenario_rows["parent_scenario"] = scenario_rows.apply(
        lambda row: (
            f"Rev {row.get('parent_revision_label')} · {row.get('parent_name')}"
            if pd.notna(row.get("parent_scenario_id"))
            and str(row.get("parent_scenario_id")).strip()
            else "Original scenario"
        ), axis=1,
    )
    scenario_rows = scenario_rows.reindex(columns=scenario_columns)
    for column in [column for column in scenario_columns if column != "takt_time_s"]:
        scenario_rows[column] = scenario_rows[column].astype("string").fillna("")
    scenario_rows["takt_time_s"] = pd.to_numeric(
        scenario_rows["takt_time_s"], errors="coerce"
    ).astype("float64")
    for column in ["created_at", "updated_at"]:
        scenario_rows[column] = pd.to_datetime(
            scenario_rows[column], errors="coerce", utc=True
        )

    with st.container(border=True):
        section_heading_with_scope(
            "Planning scenarios", scope="scenario", scenario_name=scenario["name"]
        )
        st.caption(
            "Edit saved scenario metadata directly. A new row creates a complete branch from the "
            "currently viewed scenario, including its Yamazumi and Process at a Glance data. "
            "The newest saved branch becomes the shared scenario view across pages."
        )
        scenario_actions = editable_table_header(
            "Scenario definitions", editor_key=scenario_editor_key,
            key_prefix=f"overview_scenarios_{project_id}", native_row_selection=True,
        )
        if scenario_actions.undo:
            request_table_editor_reset(scenario_editor_key)
            st.rerun()

        visible_scenarios = filter_table(
            scenario_rows, key=f"overview_scenario_filters_{project_id}",
            dropdown_columns=["status", "parent_scenario"],
            search_columns=[
                "name", "revision_label", "status", "change_summary",
                "parent_scenario", "created_by",
            ],
            labels={"parent_scenario": "Source scenario"},
            reset_widget_keys=[scenario_editor_key],
        )
        selected_detail_key = f"overview_scenario_details_{project_id}"

        def open_scenario_details() -> None:
            click = st.session_state.get(f"overview_scenario_details_action_{project_id}") or {}
            position = click.get("row")
            if position is not None and 0 <= int(position) < len(visible_scenarios):
                selected_id = str(editor_rows.iloc[int(position)]["id"] or "")
                if selected_id:
                    st.session_state[selected_detail_key] = selected_id

        suggested_revision = next_scenario_revision_label(
            project_id, str(scenario["revision_label"])
        )
        editor_rows = direct_entry_editor_rows(
            visible_scenarios, editor_key=scenario_editor_key,
            sort_columns=[
                "current_view", "name", "revision_label", "status", "takt_time_s",
                "change_summary", "parent_scenario", "created_by", "updated_at",
            ],
            labels={
                "current_view": "View", "name": "Scenario name",
                "revision_label": "Scenario revision", "takt_time_s": "Takt (seconds)",
                "parent_scenario": "Source scenario", "created_by": "Created by",
                "updated_at": "Updated",
            },
        )
        edited_scenarios = st.data_editor(
            editor_rows, key=scenario_editor_key, hide_index=True,
            num_rows="dynamic", height=390,
            disabled=[
                "id", "view_details", "current_view", "parent_scenario_id",
                "parent_scenario", "created_by", "created_at", "updated_at",
            ],
            column_order=[
                "view_details", "current_view", "name", "revision_label", "status",
                "takt_time_s", "change_summary", "parent_scenario", "created_by", "updated_at",
            ],
            column_config={
                "id": None,
                "view_details": standard_details_column_config(
                    on_click=open_scenario_details,
                    key=f"overview_scenario_details_action_{project_id}",
                ),
                "current_view": st.column_config.TextColumn("View", pinned=True),
                "name": st.column_config.TextColumn("Scenario name", required=True, pinned=True),
                "revision_label": st.column_config.TextColumn(
                    "Scenario revision", required=True, default=suggested_revision
                ),
                "status": st.column_config.SelectboxColumn(
                    "Status", options=["Working", "Frozen", "Released", "Archived"],
                    required=True, default="Working",
                ),
                "takt_time_s": st.column_config.NumberColumn(
                    "Takt (seconds)", required=True, min_value=0.1,
                    step=0.1, format="%.1f", default=float(scenario["takt_time_s"]),
                ),
                "change_summary": st.column_config.TextColumn("Change summary", width="large"),
                "parent_scenario_id": None,
                "parent_scenario": st.column_config.TextColumn("Source scenario"),
                "created_by": st.column_config.TextColumn("Created by"),
                "created_at": st.column_config.DatetimeColumn(
                    "Created", format="MMM DD, YYYY HH:mm"
                ),
                "updated_at": st.column_config.DatetimeColumn(
                    "Updated", format="MMM DD, YYYY HH:mm"
                ),
            },
        )
        selected_scenarios = native_selected_rows(
            editor_rows, editor_key=scenario_editor_key
        )
        scenario_export = visible_scenarios.drop(
            columns=["id", "view_details", "parent_scenario_id"], errors="ignore"
        ).copy()
        for column in ["created_at", "updated_at"]:
            if column in scenario_export:
                scenario_export[column] = scenario_export[column].astype("string")
        with st.container(horizontal=True, horizontal_alignment="right"):
            st.download_button(
                "Export filtered",
                data=dataframe_to_excel(scenario_export, "Planning scenarios"),
                file_name="planning_scenarios_filtered.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                icon=":material/download:", key=f"overview_scenarios_export_{project_id}",
            )

        if scenario_actions.save_and_refresh:
            try:
                if not selected_scenarios.empty:
                    raise ValueError("Clear selected rows before saving scenario edits.")
                edited_scenarios = drop_untouched_new_rows(
                    edited_scenarios, identifying_columns=["name"]
                )
                merged_scenarios = merge_filtered_edits(
                    scenario_rows, visible_scenarios, edited_scenarios
                )
                errors = required_field_errors(
                    merged_scenarios,
                    {
                        "name": "Scenario name", "revision_label": "Scenario revision",
                        "status": "Status", "takt_time_s": "Takt (seconds)",
                    },
                )
                if errors:
                    raise ValueError(" ".join(errors))
                result = save_planning_scenario_rows(
                    project_id, str(scenario_id), merged_scenarios.to_dict("records"),
                    st.session_state.get("current_editor", ""),
                )
                record_audit_event(
                    project_id, "Planning scenarios", "Save & refresh",
                    int(result["saved_count"]),
                    st.session_state.get("current_editor", ""),
                    {
                        "source_scenario_id": str(scenario_id),
                        "created_scenario_ids": result["created_ids"],
                        "updated_count": result["updated_count"],
                    },
                )
                if result["created_ids"]:
                    newest_id = str(result["created_ids"][-1])
                    st.session_state["scenario_id"] = newest_id
                    st.session_state[selected_detail_key] = newest_id
                request_table_editor_reset(scenario_editor_key)
                st.toast("Planning scenarios saved", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        selected_detail_id = str(st.session_state.get(selected_detail_key) or "")
        detail = next(
            (row for row in all_scenarios if str(row["id"]) == selected_detail_id), None
        )
        if detail:
            st.divider()
            st.subheader(f"Scenario details · {detail['name']}")
            detail_metrics = st.columns(4)
            detail_metrics[0].metric("Revision", detail["revision_label"], border=True)
            detail_metrics[1].metric("Status", detail["status"], border=True)
            detail_metrics[2].metric(
                "Takt", f"{float(detail['takt_time_s']):.1f} s", border=True
            )
            detail_metrics[3].metric(
                "Current view", "Yes" if str(detail["id"]) == str(scenario_id) else "No",
                border=True,
            )
            source_label = (
                f"Rev {detail.get('parent_revision_label')} · {detail.get('parent_name')}"
                if detail.get("parent_scenario_id") else "Original scenario"
            )
            st.markdown(f"**Source scenario:** {source_label}")
            st.markdown(
                f"**Change summary:** {detail.get('change_summary') or 'No change summary entered.'}"
            )
            st.caption(
                f"Created by {detail.get('created_by') or 'Not recorded'} on "
                f"{detail.get('created_at') or 'an unknown date'} · Last updated "
                f"{detail.get('updated_at') or 'on an unknown date'}"
            )

scenario_history = audit_history(project_id, "Planning scenarios")
with st.expander("History", icon=":material/history:"):
    if scenario_history.empty:
        st.info("No planning-scenario history has been recorded yet.")
    else:
        selectable_dataframe(
            scenario_history, key=f"overview_scenario_history_{project_id}",
            hide_index=True,
            column_order=["created_at", "action", "row_count", "editor_name", "details"],
            column_config={
                "created_at": st.column_config.DatetimeColumn(
                    "When", format="MMM DD, YYYY HH:mm"
                ),
                "action": st.column_config.TextColumn("Action"),
                "row_count": st.column_config.NumberColumn("Rows", format="%d"),
                "editor_name": st.column_config.TextColumn("Current editor"),
                "details": st.column_config.JsonColumn("Details"),
            },
        )
