import streamlit as st

from utils.store import get_planning_scenario, material_consumption_for_scenario, project_table


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
st.title("Requirements view")
st.caption("Review process requirements by work element. Edit the source data in Process plan.")
if not project_id or not scenario_id:
    st.stop()

scenario = get_planning_scenario(project_id, scenario_id)
if not scenario:
    st.error("The active planning scenario no longer exists.")
    st.stop()
st.caption(f"Rev {scenario['revision_label']} · {scenario['name']} · {float(scenario['takt_time_s']):.1f} s takt")
elements = project_table("work_elements", project_id, "sequence", scenario_id=scenario_id)
materials = material_consumption_for_scenario(project_id, scenario_id)
if elements.empty:
    st.info("Add process steps to begin capturing requirements.")
    st.stop()

station_options = ["All"] + sorted(value for value in elements["station"].dropna().unique().tolist() if value)
station = st.selectbox("Station", station_options, key=f"requirements_station_{scenario_id}")
filtered = elements if station == "All" else elements[elements["station"] == station]

for _, step in filtered.iterrows():
    with st.container(border=True):
        heading = f"{int(step['sequence']) if step['sequence'] is not None else '—'} · {step['operation']}"
        st.subheader(heading)
        st.caption(f"{step['station'] or 'Unassigned pitch'} · {float(step['cycle_time_s'] or 0):.1f} s")
        if str(step.get("output_assembly_number") or "").strip():
            st.success(
                f"Creates assembly {step['output_assembly_number']} · "
                f"{step.get('output_assembly_name') or ''}"
            )
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
        step_materials = (
            materials.loc[materials["process_element_id"].astype(str) == str(step["id"])]
            if not materials.empty else materials
        )
        if not step_materials.empty:
            st.markdown("**Materials consumed**")
            for _, requirement_rows in step_materials.groupby("group_id", sort=False):
                requirement = requirement_rows.iloc[0]
                options = [str(row["part_number"]) for _, row in requirement_rows.iterrows()]
                section = str(requirement.get("section_name") or "").strip()
                section_text = f" · Fishbone: {section}" if section else ""
                st.write(
                    f"{requirement['requirement']} · {requirement['selection_rule']} · "
                    f"Qty {float(requirement['quantity']):g}: {', '.join(options)}{section_text}"
                )
        st.markdown(f"**Location:** {step['location'] or '—'} · **Conveyor:** {step['conveyor_height_mm'] or '—'} mm · **Platform:** {step['platform_height_mm'] or '—'} mm · **Pit:** {step['pit_depth_mm'] or '—'} mm")
