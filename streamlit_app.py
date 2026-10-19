import streamlit as st

from streamlit.runtime.scriptrunner import StopException

from utils.time_units import format_seconds
from utils.fishbone_ui import FISHBONE_LINKED_PAGES, render_fishbone_sidebar_context
from utils.scope_ui import scenario_view_selector

from utils.split_workspace import component_event, split_divider, split_navigation
from utils.store import get_project, init_db, migrate_legacy_yamazumi_flags, projects


st.set_page_config(page_title="Process at a Glance", page_icon=":material/precision_manufacturing:", layout="wide")
st.html(
    """
    <style>
    div[class*="st-key-destructive_"] button {
        background-color: #c62828 !important;
        border-color: #c62828 !important;
        color: #ffffff !important;
    }
    div[class*="st-key-destructive_"] button p,
    div[class*="st-key-destructive_"] button span,
    div[class*="st-key-destructive_"] button [data-testid="stIconMaterial"] {
        color: #ffffff !important;
    }
    div[class*="st-key-destructive_"] button:hover {
        background-color: #a71919 !important;
        border-color: #a71919 !important;
        color: #ffffff !important;
    }
    div[class*="st-key-destructive_"] button:focus,
    div[class*="st-key-destructive_"] button:active {
        background-color: #8e0000 !important;
        border-color: #8e0000 !important;
        color: #ffffff !important;
        box-shadow: none !important;
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
    div[class*="st-key-assembly_catalog_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-assembly_bom_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-assembly_rule_list"] button[aria-label="Delete row(s)"],
    div[class*="st-key-assembly_image_selection"] button[aria-label="Delete row(s)"],
    div[class*="st-key-assembly_framework_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-fishbone_assignment_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-yamazumi_region_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-yamazumi_pitch_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-yamazumi_element_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-safety_requirements_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-existing_process_pairings"] button[aria-label="Delete row(s)"],
    div[class*="st-key-process_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-pfmea_flat_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-control_plan_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-pfmea_prevention_options_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-pfmea_detection_options_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-pfmea_patterns_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-quality_requirement_types_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-quality_requirements_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-equipment_types_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-equipment_assets_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-equipment_overview_editor"] button[aria-label="Delete row(s)"],
    div[class*="st-key-equipment_torque_details_editor"] button[aria-label="Delete row(s)"] {
        display: inline-flex !important;
    }
    </style>
    """
)
init_db()

all_projects = projects()
st.session_state.setdefault("project_id", all_projects[0]["id"] if all_projects else None)
st.session_state.setdefault("scenario_id", None)

pending_project_id = st.session_state.pop("pending_active_project_id", None)
if pending_project_id and any(
    str(project["id"]) == str(pending_project_id) for project in all_projects
):
    st.session_state.project_id = str(pending_project_id)
    st.session_state.scenario_id = None
    st.session_state.pop("global_project", None)
    st.session_state.pop("global_scenario", None)

valid_project_ids = {str(project["id"]) for project in all_projects}
if st.session_state.get("project_id") not in valid_project_ids:
    st.session_state.project_id = all_projects[0]["id"] if all_projects else None
    st.session_state.scenario_id = None
    st.session_state.pop("global_project", None)
    st.session_state.pop("global_scenario", None)

project_exchange_page = st.Page(
    "app_pages/exchange.py",
    title="Import/Export Projects",
    icon=":material/sync_alt:",
)

pages = {
    "Project": [
        project_exchange_page,
        st.Page("app_pages/overview.py", title="Overview", icon=":material/dashboard:"),
        st.Page("app_pages/concerns.py", title="Questions and concerns", icon=":material/forum:"),
    ],
    "Product structure": [
        st.Page("app_pages/pits_exchange.py", title="Import PITs", icon=":material/sync_alt:"),
        st.Page("app_pages/models.py", title="Complexity Trees", icon=":material/view_in_ar:"),
        st.Page("app_pages/parts.py", title="Parts Catalog", icon=":material/category:"),
        st.Page("app_pages/bom_tree.py", title="BOM", icon=":material/account_tree:"),
        st.Page("app_pages/fishbone.py", title="Fishbone", icon=":material/device_hub:"),
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
registered_pages = pages
unlisted_pages = [
    st.Page("app_pages/functional_equipment.py", title="Equipment", url_path="Equipment"),
    st.Page("app_pages/functional_ergonomics.py", title="Ergonomics", url_path="Ergonomics"),
    st.Page("app_pages/functional_quality.py", title="Quality", url_path="Quality"),
    st.Page("app_pages/functional_materials.py", title="Materials", url_path="Materials"),
    st.Page("app_pages/functional_safety.py", title="Safety", url_path="Safety"),
]
navigation = st.navigation({**registered_pages, "_unlisted": unlisted_pages}, position="hidden")

all_registered_pages = [
    app_page
    for section_pages in registered_pages.values()
    for app_page in section_pages
]
all_registered_pages.extend(unlisted_pages)


def _workspace_page_key(app_page) -> str:
    return app_page.url_path or "__default__"


page_by_url_path = {
    _workspace_page_key(app_page): app_page for app_page in all_registered_pages
}
active_page_key = _workspace_page_key(navigation)

split_secondary_key = "split_workspace_secondary_url_path"
split_ratio_key = "split_workspace_ratio"
split_navigation_key = "split_workspace_navigation"
split_divider_key = "split_workspace_divider"
split_orientation_key = "split_workspace_orientation"

secondary_url_path = str(st.session_state.get(split_secondary_key) or "")
if secondary_url_path not in page_by_url_path or secondary_url_path == active_page_key:
    secondary_url_path = ""
    st.session_state.pop(split_secondary_key, None)
secondary_page = page_by_url_path.get(secondary_url_path)


def _material_icon_name(icon: str) -> str:
    value = str(icon or "").strip()
    if value.startswith(":material/") and value.endswith(":"):
        return value[len(":material/"):-1]
    return "description"


navigation_sections = [
    {
        "name": section,
        "pages": [
            {
                "title": app_page.title,
                "url_path": _workspace_page_key(app_page),
                "icon": _material_icon_name(app_page.icon),
            }
            for app_page in section_pages
        ],
    }
    for section, section_pages in registered_pages.items()
]


def _on_split_navigation() -> None:
    event = component_event(split_navigation_key, "navigate")
    target = str(event.get("url_path") or "")
    if target not in page_by_url_path:
        return
    if target == str(st.session_state.get(split_secondary_key) or ""):
        st.session_state.pop(split_secondary_key, None)
    st.session_state["split_workspace_pending_navigation"] = target


def _on_split_open() -> None:
    event = component_event(split_navigation_key, "split")
    target = str(event.get("url_path") or "")
    if target not in page_by_url_path:
        return
    if target == active_page_key:
        st.toast("Choose a different page for the second pane", icon=":material/info:")
        return
    st.session_state[split_secondary_key] = target


def _on_split_close() -> None:
    st.session_state.pop(split_secondary_key, None)


def _on_split_ratio() -> None:
    event = component_event(split_divider_key, "ratio")
    try:
        ratio = float(event.get("value"))
    except (TypeError, ValueError):
        return
    st.session_state[split_ratio_key] = max(0.25, min(0.75, ratio))

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
                f"{format_seconds(active_scenario['takt_time_s'], active_scenario['takt_time_unit'])} takt"
            )
        fishbone_context_title = navigation.title
        if (
            fishbone_context_title not in FISHBONE_LINKED_PAGES
            and secondary_page is not None
            and secondary_page.title in FISHBONE_LINKED_PAGES
        ):
            fishbone_context_title = secondary_page.title
        render_fishbone_sidebar_context(
            st,
            page_title=fishbone_context_title,
            project_id=st.session_state.project_id,
            scenario_id=(active_scenario or {}).get("id"),
        )
        st.divider()
        st.subheader("Application")
        split_navigation(
            navigation_sections,
            active_url_path=active_page_key,
            secondary_url_path=secondary_url_path,
            secondary_title=secondary_page.title if secondary_page else "",
            key=split_navigation_key,
            on_navigate_change=_on_split_navigation,
            on_split_change=_on_split_open,
            on_close_split_change=_on_split_close,
        )
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

pending_navigation = str(
    st.session_state.pop("split_workspace_pending_navigation", "") or ""
)
if pending_navigation and pending_navigation in page_by_url_path:
    st.switch_page(page_by_url_path[pending_navigation])

if st.session_state.get("project_id"):
    try:
        migrate_legacy_yamazumi_flags(
            st.session_state["project_id"],
            st.session_state.get("current_editor", ""),
        )
    except ValueError as exc:
        st.error(str(exc))
        st.stop()


def _run_workspace_page(app_page, *, enable: bool = False) -> None:
    if enable:
        app_page._can_be_called = True
    try:
        app_page.run()
    except StopException:
        pass


if active_page_key != "parts" and secondary_url_path != "parts":
    st.session_state.pop("_parts_page_mounted_token", None)

if secondary_page is None:
    navigation.run()
else:
    # Relax container horizontal margins so split panes autofill the available monitor space
    st.html(
        """
        <style>
        .main .block-container {
            max-width: 100% !important;
            padding-left: 1.5rem !important;
            padding-right: 1.5rem !important;
        }
        div[data-testid="stHorizontalBlock"] {
            width: 100% !important;
        }
        </style>
        """
    )
    split_orientation = str(st.session_state.get(split_orientation_key) or "top_bottom")

    if split_orientation == "side_by_side":
        # Side-by-side mode (if user toggles to columns)
        st.html(
            """
            <style>
            .st-key-split_side_by_side > div[data-testid="stHorizontalBlock"] {
                flex-wrap: nowrap !important;
                width: 100% !important;
            }
            .st-key-split_side_by_side div[data-testid="stColumn"] {
                min-width: 0 !important;
            }
            </style>
            """
        )
        split_ratio = max(
            0.25,
            min(0.75, float(st.session_state.get(split_ratio_key, 0.5))),
        )
        with st.container(key="split_side_by_side"):
            primary_pane, divider_pane, secondary_pane = st.columns(
                [split_ratio, 0.018, 1.0 - split_ratio],
                gap="small",
            )
            with primary_pane:
                _run_workspace_page(navigation)
            with divider_pane:
                split_divider(
                    split_ratio,
                    key=split_divider_key,
                    on_ratio_change=_on_split_ratio,
                )
            with secondary_pane:
                split_header = st.container(
                    horizontal=True,
                    horizontal_alignment="right",
                    vertical_alignment="center",
                )
                split_header.caption(f"Split pane · {secondary_page.title}")
                if split_header.button(
                    "Top & Bottom",
                    icon=":material/splitscreen:",
                    key="split_to_top_bottom_btn",
                    help="Switch to full-width Top & Bottom layout",
                ):
                    st.session_state[split_orientation_key] = "top_bottom"
                    st.rerun()
                if split_header.button(
                    "Close",
                    icon=":material/close:",
                    key="split_workspace_close_button",
                    help="Close the second pane",
                ):
                    st.session_state.pop(split_secondary_key, None)
                    st.rerun()
                _run_workspace_page(secondary_page, enable=True)
    else:
        # Default: Top & Bottom (stacked) mode — both screens span 100% full width of monitor!
        with st.container(key="split_top_pane"):
            _run_workspace_page(navigation)

        st.markdown("---")
        split_bar = st.container(border=True, key="split_divider_toolbar")
        with split_bar:
            b_info, b_swap, b_orient, b_close = st.columns(
                [2.8, 1.1, 1.1, 0.9],
                vertical_alignment="center",
                gap="small",
            )
            with b_info:
                top_icon = _material_icon_name(navigation.icon)
                bottom_icon = _material_icon_name(secondary_page.icon)
                st.markdown(
                    f"**:material/splitscreen: Split Screen (Top & Bottom)** &nbsp;&bull;&nbsp; "
                    f":material/{top_icon}: **Top:** {navigation.title} &nbsp;&bull;&nbsp; "
                    f":material/{bottom_icon}: **Bottom:** {secondary_page.title}"
                )
            with b_swap:
                if st.button(
                    "Swap Panes",
                    icon=":material/swap_vert:",
                    key="split_swap_panes_btn",
                    help="Swap top and bottom pages",
                    width="stretch",
                ):
                    st.session_state["split_workspace_pending_navigation"] = secondary_url_path
                    st.session_state[split_secondary_key] = active_page_key
                    st.rerun()
            with b_orient:
                if st.button(
                    "Side-by-side",
                    icon=":material/view_column_2:",
                    key="split_to_side_by_side_btn",
                    help="Switch to side-by-side columns view",
                    width="stretch",
                ):
                    st.session_state[split_orientation_key] = "side_by_side"
                    st.rerun()
            with b_close:
                if st.button(
                    "Close",
                    icon=":material/close:",
                    key="split_workspace_close_button",
                    help="Close split view and return to full single screen",
                    width="stretch",
                ):
                    st.session_state.pop(split_secondary_key, None)
                    st.rerun()

        with st.container(key="split_bottom_pane"):
            _run_workspace_page(secondary_page, enable=True)
