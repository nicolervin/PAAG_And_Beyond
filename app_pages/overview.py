import pandas as pd
import streamlit as st

from utils.store import create_project, get_project, project_table, update_project


project_id = st.session_state.get("project_id")
st.title("Project overview")
st.caption("The current snapshot of an evolving NPI process plan.")


@st.dialog("Create an NPI project")
def new_project_dialog():
    with st.form("new_project"):
        name = st.text_input("Project name")
        program = st.text_input("Program or product")
        owner = st.text_input("Lead industrial engineer")
        takt = st.number_input("Target takt time (seconds)", min_value=0.1, value=60.0)
        if st.form_submit_button("Create project", type="primary", icon=":material/add:"):
            if not name.strip():
                st.error("Project name is required.")
            else:
                st.session_state.project_id = create_project(name, program, owner, takt)
                st.rerun()


with st.container(horizontal=True, horizontal_alignment="right"):
    if st.button("New project", icon=":material/add:"):
        new_project_dialog()

if not project_id:
    st.info("Create a project to begin.")
    st.stop()

project = get_project(project_id)
parts = project_table("parts", project_id)
elements = project_table("work_elements", project_id, "sequence")
concerns = project_table("concerns", project_id)
total_cycle = float(elements["cycle_time_s"].sum()) if not elements.empty else 0
open_concerns = int((concerns["status"] != "Closed").sum()) if not concerns.empty else 0

metric_cols = st.columns(4)
metric_cols[0].metric("Parts", len(parts), border=True)
metric_cols[1].metric("Work elements", len(elements), border=True)
metric_cols[2].metric("Draft cycle time", f"{total_cycle:.1f} s", delta=f"{total_cycle - float(project['takt_time_s']):+.1f} s vs takt", delta_color="inverse", border=True)
metric_cols[3].metric("Open concerns", open_concerns, border=True)

left, right = st.columns([3, 2])
with left.container(border=True):
    st.subheader("Project definition")
    with st.form("project_details"):
        name = st.text_input("Project name", value=project["name"])
        program = st.text_input("Program or product", value=project["program"])
        owner = st.text_input("Lead industrial engineer", value=project["owner"])
        row = st.columns(3)
        revision = row[0].text_input("Plan revision", value=project["revision"])
        status = row[1].selectbox("Status", ["Draft", "In review", "Released", "On hold"], index=["Draft", "In review", "Released", "On hold"].index(project["status"]) if project["status"] in ["Draft", "In review", "Released", "On hold"] else 0)
        takt = row[2].number_input("Target takt (seconds)", min_value=0.1, value=float(project["takt_time_s"]))
        notes = st.text_area("Planning notes", value=project["notes"], placeholder="Assumptions, scope, milestones, or known changes…")
        if st.form_submit_button("Save project", type="primary", icon=":material/save:"):
            update_project(project_id, {"name": name, "program": program, "owner": owner, "revision": revision, "status": status, "takt_time_s": takt, "notes": notes})
            st.toast("Project saved", icon=":material/check_circle:")
            st.rerun()

with right.container(border=True):
    st.subheader("Station loading")
    if elements.empty:
        st.caption("Add work elements to see the draft Yamazumi view.")
    else:
        station_load = elements.groupby("station", dropna=False)["cycle_time_s"].sum().reset_index()
        station_load["station"] = station_load["station"].replace("", "Unassigned")
        st.bar_chart(station_load, x="station", y="cycle_time_s", x_label="Station", y_label="Cycle time (s)", horizontal=True)
        st.caption(f"Target takt: {float(project['takt_time_s']):.1f} seconds")

