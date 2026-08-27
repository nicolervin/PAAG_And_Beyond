import streamlit as st

from utils.scope_ui import scenario_view_selector
from utils.store import get_project, init_db, projects


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
    div[class*="st-key-concerns_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-model_definitions_editor_v2"] button[aria-label="Delete row(s)"],
    div[class*="st-key-complexity_feature_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-parts_catalog_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-assembly_framework_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-fishbone_assignment_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-yamazumi_region_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-yamazumi_flag_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-yamazumi_pitch_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-yamazumi_element_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-existing_process_pairings"] button[aria-label="Delete row(s)"],
    div[class*="st-key-process_editor"] button[aria-label="Delete row(s)"] {
        display: inline-flex !important;
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
        st.Page("app_pages/assemblies.py", title="Assemblies", icon=":material/account_tree:"),
        st.Page("app_pages/fishbone.py", title="Parts to fishbone", icon=":material/device_hub:"),
    ],
    "Process planning": [
        st.Page("app_pages/yamazumi.py", title="Yamazumi", icon=":material/view_column:"),
        st.Page(
            "app_pages/process.py",
            title="Process at a Glance",
            icon=":material/account_tree:",
        ),
        st.Page("app_pages/pin_map.py", title="Pin Map", icon=":material/map:"),
    ],
    "Functional Reviews": [
        st.Page(
            "app_pages/functional_equipment.py",
            title="Equipment",
            icon=":material/precision_manufacturing:",
        ),
        st.Page(
            "app_pages/functional_ergonomics.py",
            title="Ergonomics",
            icon=":material/accessibility_new:",
        ),
        st.Page(
            "app_pages/functional_quality.py",
            title="Quality",
            icon=":material/verified:",
        ),
        st.Page(
            "app_pages/functional_materials.py",
            title="Materials",
            icon=":material/inventory_2:",
        ),
        st.Page(
            "app_pages/functional_safety.py",
            title="Safety",
            icon=":material/health_and_safety:",
        ),
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
        active_scenario = scenario_view_selector(
            st,
            project_id=st.session_state.project_id,
            key="global_scenario",
            label="Active planning scenario",
            width="stretch",
        )
        if active_scenario:
            st.caption(
                f"{active_scenario['status']} · "
                f"{float(active_scenario['takt_time_s']):.1f} s takt"
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
