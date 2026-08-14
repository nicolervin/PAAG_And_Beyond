import streamlit as st

from utils.store import (
    create_project,
    get_planning_scenario,
    get_project,
    project_table,
    update_planning_scenario,
    update_project,
)


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
st.title("Project overview")
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
metric_cols[2].metric("Draft cycle time", f"{total_cycle:.1f} s", delta=f"{total_cycle - active_takt:+.1f} s vs takt", delta_color="inverse", border=True)
metric_cols[3].metric("Open concerns", open_concerns, border=True)

with st.container(border=True):
    st.subheader("Project definition")
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
        status = row[1].selectbox("Status", ["Draft", "In review", "Released", "On hold"], index=["Draft", "In review", "Released", "On hold"].index(project["status"]) if project["status"] in ["Draft", "In review", "Released", "On hold"] else 0)
        takt = row[2].number_input("Default takt for new scenarios", min_value=0.1, value=float(project["takt_time_s"]))
        notes = st.text_area("Planning notes", value=project["notes"], placeholder="Assumptions, scope, milestones, or known changes…")
        if st.form_submit_button("Save project", type="primary", icon=":material/save:"):
            update_project(
                project_id,
                {
                    "name": name,
                    "program": program,
                    "product_line": product_line,
                    "owner": owner,
                    "revision": revision,
                    "status": status,
                    "takt_time_s": takt,
                    "notes": notes,
                },
            )
            st.toast("Project saved", icon=":material/check_circle:")
            st.rerun()

if scenario:
    with st.container(border=True):
        st.subheader("Active planning scenario")
        parent_text = ""
        if scenario.get("parent_scenario_id"):
            parent_text = " This scenario was created with Save as and retains its source lineage."
        st.caption(
            f"Rev {scenario['revision_label']} · {scenario['status']}.{parent_text} "
            "Changes here apply only to this scenario."
        )
        with st.form(f"scenario_details_{scenario_id}"):
            scenario_row = st.columns([2, 1, 1])
            scenario_name = scenario_row[0].text_input("Scenario name", value=scenario["name"])
            scenario_revision = scenario_row[1].text_input("Scenario revision", value=scenario["revision_label"])
            scenario_takt = scenario_row[2].number_input(
                "Scenario takt (seconds)", min_value=0.1, value=float(scenario["takt_time_s"])
            )
            change_summary = st.text_area(
                "Change summary",
                value=scenario["change_summary"],
                placeholder="Demand, staffing, equipment, or balancing assumptions for this branch…",
            )
            if st.form_submit_button("Save scenario details", type="primary", icon=":material/save:"):
                try:
                    update_planning_scenario(
                        project_id,
                        scenario_id,
                        {
                            "name": scenario_name,
                            "revision_label": scenario_revision,
                            "status": scenario["status"],
                            "takt_time_s": scenario_takt,
                            "change_summary": change_summary,
                        },
                    )
                    st.toast("Scenario details saved", icon=":material/check_circle:")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
