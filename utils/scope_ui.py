from __future__ import annotations

from typing import Literal

import streamlit as st

from utils.store import (
    clone_planning_scenario,
    next_scenario_revision_label,
    planning_scenarios,
)


ScopeKind = Literal["project", "scenario", "scenario-aware"]
PROJECT_WIDE_HELP = (
    "Changes on this page affect every planning scenario in this project."
)


def _activate_scenario(selector_key: str) -> None:
    """Promote a scenario selector change to the shared cross-page state."""
    selected_id = st.session_state.get(selector_key)
    if not selected_id:
        return
    st.session_state["scenario_id"] = selected_id


def scenario_option_label(scenario: dict) -> str:
    """Return the standard revision-and-name label for a scenario choice."""
    return f"Rev {scenario['revision_label']} · {scenario['name']}"


def scenario_view_selector(
    parent,
    *,
    project_id: str,
    key: str,
    label: str = "View scenario",
    label_visibility: Literal["visible", "hidden", "collapsed"] = "visible",
    width: int | Literal["stretch"] = 280,
) -> dict | None:
    """Render a selector backed by the one active scenario for this browser session.

    Each selector synchronizes from ``scenario_id`` before its widget is
    instantiated. This keeps the sidebar and page selectors aligned without
    mutating another widget after it has already rendered.
    """
    scenarios = planning_scenarios(project_id)
    if not scenarios:
        return None
    scenario_by_id = {str(scenario["id"]): scenario for scenario in scenarios}
    current_id = str(st.session_state.get("scenario_id") or "")
    if current_id not in scenario_by_id:
        current_id = str(scenarios[0]["id"])
        st.session_state["scenario_id"] = current_id
    if st.session_state.get(key) != current_id:
        st.session_state[key] = current_id
    selected_id = parent.selectbox(
        label,
        options=list(scenario_by_id),
        format_func=lambda scenario_id: scenario_option_label(
            scenario_by_id[str(scenario_id)]
        ),
        key=key,
        on_change=_activate_scenario,
        args=(key,),
        label_visibility=label_visibility,
        persist_state="session",
        width=width,
        help="Switch the active scenario used by every scenario-aware and scenario-specific page.",
    )
    return scenario_by_id[str(selected_id)]


@st.dialog("Save as planning scenario")
def save_as_scenario_dialog(
    *, project_id: str, source_scenario: dict, key_prefix: str
) -> None:
    """Create a complete branch from the scenario shown in a page-title selector."""
    source_scenario_id = str(source_scenario["id"])
    suggested_revision = next_scenario_revision_label(
        project_id, str(source_scenario["revision_label"])
    )
    st.caption(
        f"Copy Rev {source_scenario['revision_label']} · {source_scenario['name']}. "
        "The source scenario will remain unchanged."
    )
    with st.form(f"{key_prefix}_save_as_scenario_{source_scenario_id}"):
        name = st.text_input(
            "New scenario name",
            value=f"{source_scenario['name']} · Rev {suggested_revision}",
        )
        revision_label = st.text_input("Scenario revision", value=suggested_revision)
        takt_time = st.number_input(
            "Target takt time (seconds)",
            min_value=0.1,
            value=float(source_scenario["takt_time_s"]),
            step=0.1,
        )
        change_summary = st.text_area(
            "What is changing?",
            placeholder="Example: Higher demand; rebalance the same work across six stations.",
        )
        if st.form_submit_button(
            "Create scenario", type="primary", icon=":material/content_copy:"
        ):
            try:
                new_scenario_id = clone_planning_scenario(
                    project_id,
                    source_scenario_id,
                    name,
                    revision_label,
                    takt_time,
                    change_summary,
                    st.session_state.get("current_editor", ""),
                )
                st.session_state["scenario_id"] = new_scenario_id
                st.toast(
                    "Scenario created; the new branch is now active",
                    icon=":material/check_circle:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def _scope_details(
    scope: ScopeKind,
    *,
    scenario_name: str | None = None,
    help_text: str | None = None,
) -> tuple[str, str, str]:
    """Return the locked label, icon, and tooltip for one scope state."""
    if scope == "project":
        return "Project-wide", ":material/public:", PROJECT_WIDE_HELP
    if scope == "scenario":
        name = str(scenario_name or "").strip()
        if not name:
            raise ValueError("A scenario name is required for a scenario boundary badge.")
        return (
            "Scenario-specific",
            ":material/account_tree:",
            f"Changes on this page only affect the {name} scenario. Other scenarios are not affected.",
        )
    if scope == "scenario-aware":
        if not str(help_text or "").strip():
            raise ValueError(
                "A page-specific tooltip is required for a scenario-aware boundary badge."
            )
        return (
            "Scenario-aware",
            ":material/hub:",
            str(help_text).strip(),
        )
    raise ValueError(f"Unknown scope badge state: {scope}")


def scope_badge(
    parent,
    *,
    scope: ScopeKind,
    scenario_name: str | None = None,
    help_text: str | None = None,
) -> None:
    """Render one locked Scenario Boundary badge in the supplied container."""
    label, icon, tooltip = _scope_details(
        scope, scenario_name=scenario_name, help_text=help_text
    )
    parent.badge(label, icon=icon, color="blue", help=tooltip)


def page_title_with_scope(
    title: str,
    *,
    scope: ScopeKind,
    scenario_name: str | None = None,
    help_text: str | None = None,
    selector_key: str | None = None,
) -> None:
    """Render a page title, boundary badge, and applicable scenario switcher."""
    row = st.container(horizontal=True, vertical_alignment="center", gap="small")
    row.title(title)
    scope_badge(
        row,
        scope=scope,
        scenario_name=scenario_name,
        help_text=help_text,
    )
    if scope in {"scenario", "scenario-aware"}:
        project_id = str(st.session_state.get("project_id") or "")
        if project_id:
            stable_key = selector_key or "_".join(
                title.casefold().replace("&", "and").split()
            )
            selected_scenario = scenario_view_selector(
                row,
                project_id=project_id,
                key=f"page_scenario_view_{stable_key}",
                label_visibility="collapsed",
            )
            if scope == "scenario" and selected_scenario:
                if row.button(
                    "Save as scenario",
                    type="primary",
                    icon=":material/content_copy:",
                    key=f"page_save_as_scenario_{stable_key}",
                    help=(
                        "Create a complete planning branch from the scenario shown "
                        "in this page's scenario menu."
                    ),
                ):
                    save_as_scenario_dialog(
                        project_id=project_id,
                        source_scenario=selected_scenario,
                        key_prefix=stable_key,
                    )


def section_heading_with_scope(
    title: str,
    *,
    scope: ScopeKind,
    scenario_name: str | None = None,
    help_text: str | None = None,
) -> None:
    """Render an Overview section heading with its applicable boundary badge."""
    row = st.container(horizontal=True, vertical_alignment="center", gap="small")
    row.subheader(title)
    scope_badge(
        row,
        scope=scope,
        scenario_name=scenario_name,
        help_text=help_text,
    )
