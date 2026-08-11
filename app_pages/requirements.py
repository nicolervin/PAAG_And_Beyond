import streamlit as st

from utils.store import project_table


project_id = st.session_state.get("project_id")
st.title("Requirements view")
st.caption("Review process requirements by work element. Edit the source data in Process plan.")
if not project_id:
    st.stop()

elements = project_table("work_elements", project_id, "sequence")
if elements.empty:
    st.info("Add process steps to begin capturing requirements.")
    st.stop()

station_options = ["All"] + sorted(value for value in elements["station"].dropna().unique().tolist() if value)
station = st.selectbox("Station", station_options)
filtered = elements if station == "All" else elements[elements["station"] == station]

for _, step in filtered.iterrows():
    with st.container(border=True):
        heading = f"{int(step['sequence']) if step['sequence'] is not None else '—'} · {step['operation']}"
        st.subheader(heading)
        st.caption(f"{step['station'] or 'Unassigned station'} · {float(step['cycle_time_s'] or 0):.1f} s · {step['part_number'] or 'No part linked'}")
        tool_col, quality_col, ergo_col = st.columns(3)
        with tool_col:
            st.markdown("**Tooling and torque**")
            st.write(step["tool"] or "—")
            st.caption(step["torque"] or "No torque specified")
        with quality_col:
            st.markdown("**Quality**")
            st.write(step["quality_requirement"] or "—")
        with ergo_col:
            st.markdown("**Ergonomics**")
            st.write(step["ergo_requirement"] or "—")
        st.markdown(f"**Location:** {step['location'] or '—'} · **Conveyor:** {step['conveyor_height_mm'] or '—'} mm · **Platform:** {step['platform_height_mm'] or '—'} mm · **Pit:** {step['pit_depth_mm'] or '—'} mm")

