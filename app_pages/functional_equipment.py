import streamlit as st

from utils.equipment_ui import render_equipment_overview
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
    "Equipment",
    scope="scenario-aware",
    scenario_name=str((scenario or {}).get("name") or "") or None,
    help_text=(
        "Equipment identity, types, and shared assets are project-wide. "
        "Station / Pitch and Process Function relationships use the active planning scenario."
    ),
)
st.caption(
    "Manage the project-wide Equipment Type catalog, shared equipment assets, "
    "and workstation assignments. Station / Pitch links use the active planning scenario."
)
if not project_id:
    st.stop()

render_equipment_overview(project_id, scenario_id if scenario else None)
