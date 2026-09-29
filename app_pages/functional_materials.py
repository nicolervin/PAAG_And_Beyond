import streamlit as st

from utils.equipment_ui import render_functional_equipment_tab
from utils.functional_review_ui import render_functional_review_shell
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
    "Materials",
    scope="scenario-aware",
    scenario_name=str((scenario or {}).get("name") or "") or None,
    help_text=(
        "Materials Review content uses its established scope. Shared Equipment identity "
        "is project-wide while placement uses the active planning scenario."
    ),
)
if not project_id:
    st.stop()

review_tab, equipment_tab = st.tabs(
    ["Review", "Equipment"],
    key=f"materials_page_tabs_{project_id}",
    on_change="rerun",
)
if equipment_tab.open:
    with equipment_tab:
        render_functional_equipment_tab(
            project_id, scenario_id if scenario else None, "Materials"
        )
    st.stop()

review_tab.__enter__()

render_functional_review_shell(
    title="Materials",
    description="Prepare materials observations and review items for future planning.",
    key_prefix="materials",
    show_title=False,
)
