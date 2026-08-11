import pandas as pd
import streamlit as st

from utils.store import get_project, project_table, replace_work_elements


project_id = st.session_state.get("project_id")
st.title("Process plan")
st.caption("Build the ordered work sequence and draft Yamazumi timing. Add or delete rows directly in the table, then save.")
if not project_id:
    st.stop()

project = get_project(project_id)
elements = project_table("work_elements", project_id, "sequence")
parts = project_table("parts", project_id, "part_number")
columns = ["id", "sequence", "station", "operation", "description", "cycle_time_s", "part_number", "tool", "torque",
           "quality_requirement", "ergo_requirement", "location", "conveyor_height_mm", "platform_height_mm", "pit_depth_mm",
           "model_applicability", "status"]
if elements.empty:
    elements = pd.DataFrame(columns=columns)
else:
    elements = elements.reindex(columns=columns)

edited = st.data_editor(
    elements,
    key="process_editor",
    hide_index=True,
    num_rows="dynamic",
    height=440,
    disabled=["id"],
    column_order=[column for column in columns if column != "id"],
    column_config={
        "id": None,
        "sequence": st.column_config.NumberColumn("Seq.", min_value=0, step=10, pinned=True),
        "station": st.column_config.TextColumn("Station", pinned=True),
        "operation": st.column_config.TextColumn("Operation", required=True, pinned=True),
        "description": st.column_config.TextColumn("Step description", width="large"),
        "cycle_time_s": st.column_config.NumberColumn("Time (s)", min_value=0.0, step=0.1, format="%.1f"),
        "part_number": st.column_config.SelectboxColumn("Part number", options=parts["part_number"].tolist() if not parts.empty else []),
        "conveyor_height_mm": st.column_config.NumberColumn("Conveyor (mm)", min_value=0.0),
        "platform_height_mm": st.column_config.NumberColumn("Platform (mm)", min_value=0.0),
        "pit_depth_mm": st.column_config.NumberColumn("Pit depth (mm)", min_value=0.0),
        "status": st.column_config.SelectboxColumn("Status", options=["Draft", "In review", "Released"]),
    },
)

with st.container(horizontal=True, horizontal_alignment="right"):
    if st.button("Save process plan", type="primary", icon=":material/save:"):
        replace_work_elements(project_id, edited)
        st.toast("Process plan saved", icon=":material/check_circle:")
        st.rerun()

if not edited.empty:
    clean_times = pd.to_numeric(edited["cycle_time_s"], errors="coerce").fillna(0)
    total = float(clean_times.sum())
    stations = edited.assign(cycle_time_s=clean_times).groupby("station", dropna=False)["cycle_time_s"].sum().reset_index()
    metric_cols = st.columns(3)
    metric_cols[0].metric("Total work content", f"{total:.1f} s", border=True)
    metric_cols[1].metric("Target takt", f"{float(project['takt_time_s']):.1f} s", border=True)
    metric_cols[2].metric("Stations represented", len(stations), border=True)
    st.subheader("Draft Yamazumi by station")
    st.bar_chart(stations, x="station", y="cycle_time_s", x_label="Station", y_label="Cycle time (s)")

