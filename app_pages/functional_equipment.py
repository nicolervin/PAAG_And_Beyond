import streamlit as st

from utils.equipment_ui import render_equipment_overview
from utils.layout_ui import render_layouts_tab
from utils.scope_ui import page_title_with_scope
from utils.store import get_planning_scenario

project_id = str(st.session_state.get("project_id") or "")
scenario_id = str(st.session_state.get("scenario_id") or "")
scenario = (
    get_planning_scenario(project_id, scenario_id)
    if project_id and scenario_id
    else None
)

page_title_with_scope(
    "Equipment and Layouts",
    scope="scenario-aware",
    scenario_name=str((scenario or {}).get("name") or "") or None,
    help_text=(
        "Equipment identity, types, and plant floor plan layouts are project-wide. "
        "Station / Pitch and Process Function relationships use the active planning scenario."
    ),
)
st.caption(
    "Manage the project-wide Equipment Type catalog, shared equipment assets, "
    "and 2D plant floor plan layouts to scale. Station / Pitch links use the active planning scenario."
)
if not project_id:
    st.stop()

tab_equipment, tab_layouts = st.tabs(["Equipment", "Layouts"])
with tab_equipment:
    render_equipment_overview(project_id, scenario_id if scenario else None)
with tab_layouts:
    render_layouts_tab(project_id, scenario_id if scenario else None)
