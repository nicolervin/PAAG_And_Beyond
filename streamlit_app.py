import streamlit as st

from utils.store import init_db, projects


st.set_page_config(page_title="Process at a Glance", page_icon=":material/precision_manufacturing:", layout="wide")
init_db()

all_projects = projects()
st.session_state.setdefault("project_id", all_projects[0]["id"] if all_projects else None)

with st.sidebar:
    st.header("Process at a Glance")
    if all_projects:
        project_by_name = {project["name"]: project["id"] for project in all_projects}
        current_name = next((name for name, pid in project_by_name.items() if pid == st.session_state.project_id), all_projects[0]["name"])
        selected_name = st.selectbox("Active project", list(project_by_name), index=list(project_by_name).index(current_name), key="global_project")
        st.session_state.project_id = project_by_name[selected_name]
    st.caption("NPI process planning · local prototype")

pages = {
    "Project": [
        st.Page("app_pages/overview.py", title="Overview", icon=":material/dashboard:"),
        st.Page("app_pages/concerns.py", title="Questions & concerns", icon=":material/forum:"),
    ],
    "Product structure": [
        st.Page("app_pages/exchange.py", title="Import PITS & export", icon=":material/sync_alt:"),
        st.Page("app_pages/models.py", title="Model definitions", icon=":material/view_in_ar:"),
        st.Page("app_pages/parts.py", title="Parts", icon=":material/category:"),
        st.Page("app_pages/fishbone.py", title="Parts to fishbone", icon=":material/device_hub:"),
    ],
    "Process planning": [
        st.Page("app_pages/process.py", title="Process plan", icon=":material/account_tree:"),
        st.Page("app_pages/requirements.py", title="Requirements", icon=":material/fact_check:"),
    ],
}
navigation = st.navigation(pages, position="sidebar")
navigation.run()
