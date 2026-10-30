import streamlit as st

from streamlit.runtime.scriptrunner import StopException

from utils.time_units import format_seconds
from utils.gcp_auth import detect_authenticated_user_email
from utils.scope_ui import scenario_view_selector, sync_active_scenario_state

from utils.split_workspace import (
    build_page_url,
    component_event,
    split_divider,
    split_navigation,
)
from utils.table_ui import (
    begin_unsaved_tracking,
    clear_unsaved_tracking_state,
    finalize_unsaved_tracking,
    has_active_unsaved_changes,
    request_unsaved_page_navigation,
    request_unsaved_state_change,
)
from utils.help_hub import (
    open_universal_help_dialog,
    render_floating_help_button,
)
from utils.store import (
    ensure_db_initialized,
    get_last_active_workspace,
    get_project,
    init_db,
    migrate_legacy_yamazumi_flags,
    open_app_feedback_count,
    planning_scenarios,
    projects,
    recycle_bin_item_count,
    set_last_active_workspace,
)


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
    div[data-testid="stMultiSelectDropdown"]:has([role="listbox"][data-empty="true"]) {
        display: none !important;
    }
    /* Responsive forgiving button and toolbar layout across screen sizes */
    div[data-testid="stButton"] button,
    div[data-testid="stDownloadButton"] button,
    div[data-testid="stLinkButton"] a,
    div[data-testid="stPopover"] > div > button {
        min-height: 2.35rem;
        height: auto !important;
        white-space: nowrap !important;
        word-break: keep-all !important;
        overflow-wrap: normal !important;
        line-height: 1.25 !important;
        padding: 0.35rem 0.75rem !important;
    }
    div[data-testid="stButton"] button p,
    div[data-testid="stDownloadButton"] button p,
    div[data-testid="stLinkButton"] a p,
    div[data-testid="stPopover"] > div > button p {
        white-space: nowrap !important;
        word-break: keep-all !important;
        overflow-wrap: normal !important;
        line-height: 1.25 !important;
        text-align: center;
    }
    div[data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
    }
    div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:not(:has(div[data-testid="stHorizontalBlock"], div[data-testid="stDataFrame"], div[data-testid="stForm"], div[data-testid="stTabs"], div[data-testid="stMarkdown"], div[data-testid="stTextInput"], div[data-testid="stSelectbox"])):has(div[data-testid="stButton"], div[data-testid="stDownloadButton"], div[data-testid="stLinkButton"], div[data-testid="stPopover"]) {
        min-width: fit-content !important;
    }
    @media (max-width: 1200px) {
        div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
            min-width: min(100%, 160px) !important;
        }
    }
    div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:has(div[data-testid="stMetric"]) {
        min-width: min(100%, 205px) !important;
        flex: 1 1 205px !important;
    }
    div[data-testid="stMetricValue"],
    div[data-testid="stMetricValue"] > div {
        font-size: clamp(1.15rem, 1.3vw, 1.45rem) !important;
        line-height: 1.25 !important;
        white-space: normal !important;
        overflow: visible !important;
        text-overflow: unset !important;
    }
    div[data-testid="stMetricLabel"] p,
    div[data-testid="stMetricLabel"] > div {
        font-size: 0.84rem !important;
        line-height: 1.25 !important;
        white-space: normal !important;
        overflow: visible !important;
        text-overflow: unset !important;
    }
    div[data-testid="stMetricDelta"],
    div[data-testid="stMetricDelta"] > div {
        font-size: 0.78rem !important;
        line-height: 1.3 !important;
        white-space: normal !important;
        overflow: visible !important;
        text-overflow: unset !important;
        align-items: flex-start !important;
    }
    div[data-testid="stMetricDelta"] svg {
        flex-shrink: 0 !important;
        margin-top: 0.15rem !important;
    }
    @media (max-width: 768px) {
        .main .block-container {
            padding-left: 0.75rem !important;
            padding-right: 0.75rem !important;
            padding-top: 1.5rem !important;
        }
        div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
            min-width: min(100%, 260px) !important;
            flex: 1 1 100% !important;
        }
    }
    </style>
    """
)
ensure_db_initialized()

all_projects = projects()
valid_project_ids = {str(project["id"]) for project in all_projects}
if (
    "project_id" not in st.session_state
    or str(st.session_state.get("project_id") or "") not in valid_project_ids
):
    last_workspace = get_last_active_workspace()
    remembered_project_id = str(last_workspace.get("project_id") or "")
    remembered_scenario_id = str(last_workspace.get("scenario_id") or "") or None
    default_project_id = (
        remembered_project_id
        if remembered_project_id in valid_project_ids
        else (str(all_projects[0]["id"]) if all_projects else None)
    )
    default_scenario_id = (
        remembered_scenario_id
        if default_project_id and default_project_id == remembered_project_id
        else None
    )
    st.session_state["project_id"] = default_project_id
    st.session_state.setdefault(
        "scenario_id",
        default_scenario_id
        if str(st.session_state.get("project_id") or "") == str(default_project_id or "")
        else None,
    )

pending_project_id = st.session_state.pop("pending_active_project_id", None)
if pending_project_id and str(pending_project_id) in valid_project_ids:
    st.session_state.project_id = str(pending_project_id)
    st.session_state["_qp_synced_project_id"] = str(pending_project_id)
    sync_active_scenario_state(None)
    try:
        st.query_params["project_id"] = str(pending_project_id)
    except Exception:
        pass
    st.session_state.scenario_id = None
    st.session_state.pop("global_project", None)
    st.session_state.pop("global_scenario", None)

# Synchronize project context from URL query params (e.g. pop-out window or shared tab)
prev_qp_project_id = st.session_state.get("_qp_synced_project_id")
qp_project_id = st.query_params.get("project_id")
if (
    qp_project_id
    and str(qp_project_id) in valid_project_ids
    and str(qp_project_id) != str(prev_qp_project_id)
    and str(qp_project_id) != str(st.session_state.get("project_id"))
):
    st.session_state.project_id = str(qp_project_id)
    st.session_state["_qp_synced_project_id"] = str(qp_project_id)
    sync_active_scenario_state(None)
    st.session_state.scenario_id = None
    st.session_state.pop("global_project", None)
    st.session_state.pop("global_scenario", None)

if str(st.session_state.get("project_id") or "") not in valid_project_ids:
    st.session_state.project_id = default_project_id
    st.session_state.scenario_id = default_scenario_id
    st.session_state.pop("global_project", None)
    st.session_state.pop("global_scenario", None)

# Synchronize scenario context from URL query params
prev_qp_scenario_id = st.session_state.get("_qp_synced_scenario_id")
qp_scenario_id = st.query_params.get("scenario_id")
if (
    qp_scenario_id
    and str(qp_scenario_id) != str(prev_qp_scenario_id)
    and st.session_state.get("project_id")
):
    available_scenarios = planning_scenarios(st.session_state["project_id"])
    if any(str(s["id"]) == str(qp_scenario_id) for s in available_scenarios):
        st.session_state.scenario_id = str(qp_scenario_id)
        sync_active_scenario_state(str(qp_scenario_id))
project_exchange_page = st.Page(
    "app_pages/exchange.py",
    title="Import/Export Projects",
    icon=":material/sync_alt:",
)

pages = {
    "Project": [
        st.Page("app_pages/overview.py", title="Overview", icon=":material/dashboard:"),
        st.Page("app_pages/concerns.py", title="Questions and concerns", icon=":material/forum:"),
    ],
    "Product structure": [
        st.Page("app_pages/pits_exchange.py", title="Import PITs", icon=":material/sync_alt:"),
        st.Page("app_pages/models.py", title="Complexity Trees", icon=":material/view_in_ar:"),
        st.Page("app_pages/bom_tree.py", title="BOM", icon=":material/account_tree:"),
        st.Page("app_pages/parts.py", title="Parts Catalog", icon=":material/category:"),
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
recycle_bin_page = st.Page(
    "app_pages/recycle_bin.py",
    title="Recycle Bin",
    icon=":material/delete:",
    url_path="recycle_bin",
)
unlisted_pages = [
    st.Page(
        "app_pages/functional_equipment.py",
        title="Equipment",
        icon=":material/precision_manufacturing:",
        url_path="Equipment",
    ),
    st.Page(
        "app_pages/functional_ergonomics.py",
        title="Ergonomics",
        icon=":material/accessibility_new:",
        url_path="Ergonomics",
    ),
    st.Page(
        "app_pages/functional_quality.py",
        title="Quality",
        icon=":material/verified:",
        url_path="Quality",
    ),
    st.Page(
        "app_pages/functional_materials.py",
        title="Materials",
        icon=":material/inventory_2:",
        url_path="Materials",
    ),
    st.Page(
        "app_pages/functional_safety.py",
        title="Safety",
        icon=":material/health_and_safety:",
        url_path="Safety",
    ),
    recycle_bin_page,
]
navigation = st.navigation(
    {"_top": [project_exchange_page], **registered_pages, "_unlisted": unlisted_pages},
    position="hidden",
)

all_registered_pages = [
    project_exchange_page,
    *[
        app_page
        for section_pages in registered_pages.values()
        for app_page in section_pages
    ],
]
all_registered_pages.extend(unlisted_pages)

_ALIAS_TO_CANONICAL_URL_PATH = {
    "Equipment": "functional_equipment",
    "Ergonomics": "functional_ergonomics",
    "Quality": "functional_quality",
    "Materials": "functional_materials",
    "Safety": "functional_safety",
}


def _canonical_workspace_page_key(url_path: str) -> str:
    raw = str(url_path or "").strip()
    return _ALIAS_TO_CANONICAL_URL_PATH.get(raw, raw)


def _workspace_page_key(app_page) -> str:
    return app_page.url_path or "__default__"


page_by_url_path = {
    _workspace_page_key(app_page): app_page for app_page in all_registered_pages
}
raw_active_page_key = _workspace_page_key(navigation)
active_page_key = _canonical_workspace_page_key(raw_active_page_key)
prev_url_path = _canonical_workspace_page_key(st.session_state.get("current_url_path") or "")
st.session_state["current_url_path"] = active_page_key

pending_navigation = _canonical_workspace_page_key(
    st.session_state.pop("split_workspace_pending_navigation", "") or ""
)
if pending_navigation and pending_navigation in page_by_url_path and pending_navigation != active_page_key:
    st.switch_page(page_by_url_path[pending_navigation])

qp_page = _canonical_workspace_page_key(st.query_params.get("page") or "")
if (
    qp_page
    and qp_page in page_by_url_path
    and qp_page != active_page_key
    and qp_page != prev_url_path
):
    st.switch_page(page_by_url_path[qp_page])

if active_page_key and active_page_key != "__default__":
    if st.query_params.get("page") != active_page_key:
        st.query_params["page"] = active_page_key
elif "page" in st.query_params:
    try:
        del st.query_params["page"]
    except Exception:
        pass

if st.session_state.get("project_id"):
    qp_proj = str(st.session_state["project_id"])
    st.session_state["_qp_synced_project_id"] = qp_proj
    if st.query_params.get("project_id") != qp_proj:
        st.query_params["project_id"] = qp_proj
if st.session_state.get("scenario_id"):
    qp_scen = str(st.session_state["scenario_id"])
    st.session_state["_qp_synced_scenario_id"] = qp_scen
    if st.query_params.get("scenario_id") != qp_scen:
        st.query_params["scenario_id"] = qp_scen

split_secondary_key = "split_workspace_secondary_url_path"
split_ratio_key = "split_workspace_ratio"
top_split_navigation_key = "split_workspace_top_navigation"
split_navigation_key = "split_workspace_navigation"
split_divider_key = "split_workspace_divider"
split_orientation_key = "split_workspace_orientation"

secondary_url_path = _canonical_workspace_page_key(
    st.session_state.get(split_secondary_key) or ""
)
if secondary_url_path not in page_by_url_path or secondary_url_path == active_page_key:
    secondary_url_path = ""
    st.session_state.pop(split_secondary_key, None)
else:
    st.session_state[split_secondary_key] = secondary_url_path
secondary_page = page_by_url_path.get(secondary_url_path)


def _material_icon_name(icon: str) -> str:
    value = str(icon or "").strip()
    if value.startswith(":material/") and value.endswith(":"):
        return value[len(":material/"):-1]
    return "description"


top_navigation_sections = [
    {
        "name": "",
        "pages": [
            {
                "title": project_exchange_page.title,
                "url_path": _workspace_page_key(project_exchange_page),
                "icon": _material_icon_name(project_exchange_page.icon),
            }
        ],
    }
]

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


def _handle_split_navigation_from(nav_key: str) -> None:
    event = component_event(nav_key, "navigate")
    target = _canonical_workspace_page_key(event.get("url_path") or "")
    if target not in page_by_url_path:
        return
    if target == active_page_key:
        return
    if has_active_unsaved_changes():
        target_page = page_by_url_path[target]
        request_unsaved_page_navigation(
            target,
            label=str(getattr(target_page, "title", "") or target),
        )
        return
    if target == _canonical_workspace_page_key(st.session_state.get(split_secondary_key) or ""):
        st.session_state.pop(split_secondary_key, None)
    st.session_state["split_workspace_pending_navigation"] = target


def _handle_split_open_from(nav_key: str) -> None:
    event = component_event(nav_key, "split")
    target = _canonical_workspace_page_key(event.get("url_path") or "")
    if target not in page_by_url_path:
        return
    if target == active_page_key:
        st.toast("Choose a different page for the second pane", icon=":material/info:")
        return
    st.session_state[split_secondary_key] = target


def _on_top_split_navigation() -> None:
    _handle_split_navigation_from(top_split_navigation_key)


def _on_top_split_open() -> None:
    _handle_split_open_from(top_split_navigation_key)


def _on_split_navigation() -> None:
    _handle_split_navigation_from(split_navigation_key)


def _on_split_open() -> None:
    _handle_split_open_from(split_navigation_key)


def _on_split_close() -> None:
    st.session_state.pop(split_secondary_key, None)


def _on_split_ratio() -> None:
    event = component_event(split_divider_key, "ratio")
    try:
        ratio = float(event.get("value"))
    except (TypeError, ValueError):
        return
    st.session_state[split_ratio_key] = max(0.25, min(0.75, ratio))


def _on_current_editor_change(value_key: str) -> None:
    st.session_state[value_key] = str(st.session_state.get("current_editor") or "")

with st.sidebar:
    st.header("Process at a Glance")
    if all_projects:
        name_counts: dict[str, int] = {}
        for project in all_projects:
            pname = str(project["name"])
            name_counts[pname] = name_counts.get(pname, 0) + 1
        project_by_name: dict[str, str] = {}
        for project in all_projects:
            pname = str(project["name"])
            pid = str(project["id"])
            label = pname if name_counts[pname] == 1 else f"{pname} ({pid[:8]})"
            project_by_name[label] = pid
        current_name = next(
            (name for name, pid in project_by_name.items() if pid == str(st.session_state.project_id)),
            next(iter(project_by_name)),
        )
        if st.session_state.get("global_project") not in project_by_name:
            st.session_state.pop("global_project", None)
        pending_proj_name = st.session_state.pop("_pending_unsaved_project_name", None)
        if pending_proj_name in project_by_name:
            st.session_state["global_project"] = pending_proj_name
        if st.session_state.get("global_project") not in project_by_name:
            st.session_state.pop("global_project", None)

        def _on_global_project_change(prev_label: str, proj_map: dict[str, str]) -> None:
            chosen_name = str(st.session_state.get("global_project") or "")
            chosen_pid = proj_map.get(chosen_name)
            if chosen_pid and str(chosen_pid) != str(st.session_state.get("project_id") or ""):
                if has_active_unsaved_changes():
                    st.session_state["global_project"] = prev_label
                    request_unsaved_state_change(
                        {"_pending_unsaved_project_name": chosen_name},
                        label=chosen_name,
                        nav_kind="project",
                        clear_unsaved_tracking=True,
                    )

        selected_name = st.selectbox(
            "Active project",
            list(project_by_name),
            index=list(project_by_name).index(current_name),
            key="global_project",
            on_change=_on_global_project_change,
            args=(current_name, project_by_name),
        )
        selected_project_id = project_by_name[selected_name]
        if selected_project_id != st.session_state.project_id:
            clear_unsaved_tracking_state()
            st.session_state.project_id = selected_project_id
            st.session_state["_qp_synced_project_id"] = str(selected_project_id)
            sync_active_scenario_state(None)
            try:
                st.query_params["project_id"] = str(selected_project_id)
            except Exception:
                pass
            st.session_state.scenario_id = None
            st.session_state.pop("global_scenario", None)
            st.toast(f"Switched active project to '{selected_name}'", icon=":material/folder_open:")
        active_project = get_project(st.session_state.project_id)
        active_scenario = scenario_view_selector(
            st,
            project_id=st.session_state.project_id,
            key="global_scenario",
            label="Active planning scenario",
            width="stretch",
        )
        resolved_scenario_id = (
            (active_scenario or {}).get("id") or st.session_state.get("scenario_id")
        )
        workspace_pair = (
            str(st.session_state.project_id or ""),
            str(resolved_scenario_id or ""),
        )
        if st.session_state.get("project_id") and st.query_params.get("project_id") != str(st.session_state["project_id"]):
            st.query_params["project_id"] = str(st.session_state["project_id"])
        if resolved_scenario_id and st.query_params.get("scenario_id") != str(resolved_scenario_id):
            st.query_params["scenario_id"] = str(resolved_scenario_id)
        if st.session_state.get("_last_persisted_workspace") != workspace_pair:
            set_last_active_workspace(
                st.session_state.project_id,
                resolved_scenario_id,
            )
            st.session_state["_last_persisted_workspace"] = workspace_pair
        if active_scenario:
            st.caption(
                f"{active_scenario['status']} · "
                f"{format_seconds(active_scenario['takt_time_s'], active_scenario['takt_time_unit'])} takt"
            )
        split_navigation(
            top_navigation_sections,
            active_url_path=active_page_key,
            secondary_url_path=secondary_url_path,
            secondary_title=secondary_page.title if secondary_page else "",
            project_id=str(st.session_state.get("project_id") or ""),
            scenario_id=str(st.session_state.get("scenario_id") or ""),
            show_help=False,
            show_drop_zone=False,
            key=top_split_navigation_key,
            on_navigate_change=_on_top_split_navigation,
            on_split_change=_on_top_split_open,
            on_close_split_change=_on_split_close,
        )
        st.divider()
        st.subheader("Application")
        split_navigation(
            navigation_sections,
            active_url_path=active_page_key,
            secondary_url_path=secondary_url_path,
            secondary_title=secondary_page.title if secondary_page else "",
            project_id=str(st.session_state.get("project_id") or ""),
            scenario_id=str(st.session_state.get("scenario_id") or ""),
            key=split_navigation_key,
            on_navigate_change=_on_split_navigation,
            on_split_change=_on_split_open,
            on_close_split_change=_on_split_close,
        )
        st.divider()
        editor_default_key = f"editor_defaulted_{st.session_state.project_id}"
        editor_value_key = f"editor_value_{st.session_state.project_id}"
        if not st.session_state.get(editor_default_key):
            default_editor = str(
                st.session_state.get("current_editor")
                or detect_authenticated_user_email()
                or (active_project or {}).get("owner")
                or ""
            )
            st.session_state[editor_value_key] = default_editor
            st.session_state.current_editor = default_editor
            st.session_state[editor_default_key] = True
        elif st.session_state.get("current_editor"):
            st.session_state[editor_value_key] = str(st.session_state.get("current_editor") or "")
        else:
            st.session_state.current_editor = str(st.session_state.get(editor_value_key) or "")
        st.session_state[editor_value_key] = st.text_input(
            "Current editor",
            key="current_editor",
            placeholder="Enter your name",
            help="This name is recorded in table history for this browser session.",
            on_change=_on_current_editor_change,
            args=(editor_value_key,),
        )
    else:
        set_last_active_workspace(None, None)
        if active_page_key == "recycle_bin" and "overview" in page_by_url_path:
            if st.button(
                "Back to overview",
                icon=":material/dashboard:",
                width="stretch",
                key="sidebar_back_to_overview_btn",
            ):
                clear_unsaved_tracking_state()
                st.switch_page(page_by_url_path["overview"])
    st.caption("NPI process planning · local prototype")
    open_fb_count = open_app_feedback_count(st.session_state.get("project_id"))
    help_button_label = (
        f"Help & search ({open_fb_count})" if open_fb_count > 0 else "Help & search"
    )
    if st.button(
        help_button_label,
        icon=":material/help:",
        type="secondary",
        width="stretch",
        key="sidebar_help_hub_btn",
        help=(
            f"Open Help Manual for '{navigation.title}', Global Project Search, "
            "Critical Thread Guide, Op ID Decoder, and Bug / Feature Tracker."
        ),
    ):
        open_universal_help_dialog(
            active_page_key=active_page_key,
            active_page_title=str(getattr(navigation, "title", "") or "Overview"),
            project_id=st.session_state.get("project_id"),
            scenario_id=st.session_state.get("scenario_id"),
            editor_name=str(st.session_state.get("current_editor") or ""),
        )
    rb_count = recycle_bin_item_count(None)
    rb_button_label = f"Recycle bin ({rb_count})" if rb_count > 0 else "Recycle bin"
    if st.button(
        rb_button_label,
        icon=":material/delete:",
        type="primary" if active_page_key == "recycle_bin" else "secondary",
        width="stretch",
        key="sidebar_recycle_bin_btn",
        help="View and restore deleted items (kept for 30 days before permanent deletion).",
    ):
        if active_page_key != "recycle_bin":
            if has_active_unsaved_changes():
                request_unsaved_page_navigation(
                    "recycle_bin",
                    label="Recycle Bin",
                )
            else:
                clear_unsaved_tracking_state()
                st.switch_page(recycle_bin_page)

pending_navigation = str(
    st.session_state.pop("split_workspace_pending_navigation", "") or ""
)
if pending_navigation and pending_navigation in page_by_url_path:
    if has_active_unsaved_changes():
        target_page = page_by_url_path[pending_navigation]
        request_unsaved_page_navigation(
            pending_navigation,
            label=str(getattr(target_page, "title", "") or pending_navigation),
        )
    else:
        clear_unsaved_tracking_state()
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

begin_unsaved_tracking(page_by_url_path, split_secondary_key=split_secondary_key)
if st.session_state.get("_pending_unsaved_project_name"):
    st.rerun()
pending_scen_switch = st.session_state.pop("_pending_unsaved_scenario_switch", None)
if pending_scen_switch:
    sync_active_scenario_state(str(pending_scen_switch))
    set_last_active_workspace(st.session_state.get("project_id"), str(pending_scen_switch))
    st.rerun()

if secondary_page is None:
    _run_workspace_page(navigation)
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
                split_header.link_button(
                    "Pop out",
                    url=build_page_url(secondary_url_path),
                    icon=":material/open_in_new:",
                    help=f"Pop out {secondary_page.title} to a separate browser window",
                )
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
            top_icon = _material_icon_name(navigation.icon)
            bottom_icon = _material_icon_name(secondary_page.icon)
            split_row = st.container(horizontal=True, vertical_alignment="center")
            split_row.markdown(
                f"**:material/splitscreen: Split Screen (Top & Bottom)** &nbsp;&bull;&nbsp; "
                f":material/{top_icon}: **Top:** {navigation.title} &nbsp;&bull;&nbsp; "
                f":material/{bottom_icon}: **Bottom:** {secondary_page.title}"
            )
            if split_row.button(
                "Swap Panes",
                icon=":material/swap_vert:",
                key="split_swap_panes_btn",
                help="Swap top and bottom pages",
            ):
                st.session_state["split_workspace_pending_navigation"] = secondary_url_path
                st.session_state[split_secondary_key] = active_page_key
                st.rerun()
            if split_row.button(
                "Side-by-side",
                icon=":material/view_column_2:",
                key="split_to_side_by_side_btn",
                help="Switch to side-by-side columns view",
            ):
                st.session_state[split_orientation_key] = "side_by_side"
                st.rerun()
            split_row.link_button(
                "Pop out",
                url=build_page_url(secondary_url_path),
                icon=":material/open_in_new:",
                help=f"Pop out {secondary_page.title} to a separate browser window",
            )
            if split_row.button(
                "Close",
                icon=":material/close:",
                key="split_workspace_close_button",
                help="Close split view and return to full single screen",
            ):
                st.session_state.pop(split_secondary_key, None)
                st.rerun()

        with st.container(key="split_bottom_pane"):
            _run_workspace_page(secondary_page, enable=True)

finalize_unsaved_tracking(page_by_url_path, split_secondary_key=split_secondary_key)

render_floating_help_button(
    active_page_key=active_page_key,
    active_page_title=str(getattr(navigation, "title", "") or "Overview"),
    project_id=st.session_state.get("project_id"),
    scenario_id=st.session_state.get("scenario_id"),
    editor_name=str(st.session_state.get("current_editor") or ""),
)
