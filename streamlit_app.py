import streamlit as st

from utils.store import get_planning_scenario, get_project, init_db, planning_scenarios, projects


st.set_page_config(page_title="Process at a Glance", page_icon=":material/precision_manufacturing:", layout="wide")
st.html(
    """
    <style>
    div[class*="st-key-destructive_"] button {
        background-color: #c62828 !important;
        border-color: #c62828 !important;
        color: #ffffff !important;
    }
    div[class*="st-key-destructive_"] button:hover {
        background-color: #a71919 !important;
        border-color: #a71919 !important;
        color: #ffffff !important;
    }
    div[class*="st-key-destructive_"] button:disabled {
        opacity: 0.45;
    }
    div[data-testid="stDataFrame"] button[aria-label="Delete row(s)"] {
        display: none !important;
    }
    </style>
    """
)
init_db()

all_projects = projects()
st.session_state.setdefault("project_id", all_projects[0]["id"] if all_projects else None)
st.session_state.setdefault("scenario_id", None)

pages = {
    "Project": [
        st.Page("app_pages/overview.py", title="Overview", icon=":material/dashboard:"),
        st.Page("app_pages/concerns.py", title="Questions & concerns", icon=":material/forum:"),
    ],
    "Product structure": [
        st.Page("app_pages/exchange.py", title="Import PITS & export", icon=":material/sync_alt:"),
        st.Page("app_pages/models.py", title="Model definitions", icon=":material/view_in_ar:"),
        st.Page("app_pages/parts.py", title="Parts Catalog", icon=":material/category:"),
        st.Page("app_pages/fishbone.py", title="Parts to fishbone", icon=":material/device_hub:"),
    ],
    "Process planning": [
        st.Page("app_pages/yamazumi.py", title="Yamazumi", icon=":material/view_column:"),
        st.Page(
            "app_pages/process.py",
            title="Process at a Glance",
            icon=":material/account_tree:",
        ),
        st.Page("app_pages/requirements.py", title="Requirements", icon=":material/fact_check:"),
    ],
}
navigation = st.navigation(pages, position="hidden")

with st.sidebar:
    st.header("Process at a Glance")
    if all_projects:
        project_by_name = {project["name"]: project["id"] for project in all_projects}
        current_name = next((name for name, pid in project_by_name.items() if pid == st.session_state.project_id), all_projects[0]["name"])
        selected_name = st.selectbox("Active project", list(project_by_name), index=list(project_by_name).index(current_name), key="global_project")
        selected_project_id = project_by_name[selected_name]
        if selected_project_id != st.session_state.project_id:
            st.session_state.project_id = selected_project_id
            st.session_state.scenario_id = None
            st.session_state.pop("global_scenario", None)
        active_project = get_project(st.session_state.project_id)
        available_scenarios = planning_scenarios(st.session_state.project_id)
        if available_scenarios:
            scenario_by_id = {scenario["id"]: scenario for scenario in available_scenarios}
            if st.session_state.scenario_id not in scenario_by_id:
                st.session_state.scenario_id = available_scenarios[0]["id"]
            selected_scenario_id = st.selectbox(
                "Active planning scenario",
                list(scenario_by_id),
                index=list(scenario_by_id).index(st.session_state.scenario_id),
                format_func=lambda scenario_id: (
                    f"Rev {scenario_by_id[scenario_id]['revision_label']} · "
                    f"{scenario_by_id[scenario_id]['name']}"
                ),
                key="global_scenario",
            )
            st.session_state.scenario_id = selected_scenario_id
            active_scenario = get_planning_scenario(st.session_state.project_id, selected_scenario_id)
            st.caption(
                f"{active_scenario['status']} · {float(active_scenario['takt_time_s']):.1f} s takt"
            )
        st.divider()
        st.subheader("Application")
        for section, section_pages in pages.items():
            st.markdown(f"**{section}**")
            for app_page in section_pages:
                st.page_link(app_page, width="stretch")
        st.divider()
        editor_default_key = f"editor_defaulted_{st.session_state.project_id}"
        if not st.session_state.get(editor_default_key):
            st.session_state.current_editor = str((active_project or {}).get("owner") or "")
            st.session_state[editor_default_key] = True
        st.text_input(
            "Current editor",
            key="current_editor",
            placeholder="Enter your name",
            help="This name is recorded in table history for this browser session.",
        )
    st.caption("NPI process planning · local prototype")

navigation.run()
