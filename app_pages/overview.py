import pandas as pd
import streamlit as st

from utils.time_units import (
    TIME_UNITS, display_to_seconds, format_seconds, seconds_to_display, time_unit,
)
from utils.scope_ui import page_title_with_scope, section_heading_with_scope, sync_active_scenario_state
from utils.table_filters import apply_pending_table_editor_reset, filter_table, merge_filtered_edits, request_table_editor_reset
from utils.table_ui import (
    check_standalone_conflict_resolution,
    compare_record_field_conflicts,
    dataframe_to_excel, drop_untouched_new_rows, editable_table_footer,
    editable_table_heading,
    native_selected_rows, render_audit_history_table, render_standalone_conflict_dialog,
    required_field_errors, selectable_dataframe,
    direct_entry_editor_rows, standard_details_column_config,
    trigger_standalone_conflict_dialog,
)
from utils.store import (
    audit_history, copy_project, create_project, delete_project, format_eastern_timestamp,
    get_planning_scenario, get_project,
    get_project_deletion_impact, next_scenario_revision_label, planning_scenarios,
    project_table, projects, record_audit_event, save_planning_scenario_rows,
    active_part_ids, project_models, set_last_active_workspace, update_project,
    yamazumi_areas, yamazumi_pitches_for_scenario,
)


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
page_title_with_scope(
    "Project overview",
    scope="scenario-aware",
    help_text=(
        "Project definition data is shared across every scenario. The planning scenarios "
        "table identifies the currently selected scenario and manages every saved branch."
    ),
)
st.caption("The current snapshot of an evolving NPI process plan.")

DESTRUCTIVE_BUTTON_CSS = """
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
</style>
"""
st.html(DESTRUCTIVE_BUTTON_CSS)


def _render_copy_project_form(
    form_key_suffix: str, default_source_project_id: str | None = None
) -> None:
    available_projects = projects()
    if not available_projects:
        st.info("No existing projects are available to copy.")
        return
    project_ids = [str(row["id"]) for row in available_projects]
    project_labels = {
        str(row["id"]): (
            f"{row['name']} ({row['program']})"
            if str(row.get("program") or "").strip()
            else str(row["name"])
        )
        for row in available_projects
    }
    default_idx = (
        project_ids.index(str(default_source_project_id))
        if default_source_project_id and str(default_source_project_id) in project_ids
        else 0
    )
    source_project_id = st.selectbox(
        "Copy from existing project",
        options=project_ids,
        index=default_idx,
        format_func=lambda pid: project_labels.get(str(pid), str(pid)),
        key=f"copy_project_source_select_{form_key_suffix}",
        help=(
            "Copies project-wide master data (models, Parts Catalog, BOM, Fishbone, "
            "Quality requirements, equipment library, questions/concerns) and only "
            "Active planning scenarios into a new project."
        ),
    )
    source_project = get_project(source_project_id) or {}
    source_active_scenarios = planning_scenarios(source_project_id, include_archived=False)
    source_all_scenarios = planning_scenarios(source_project_id, include_archived=True)
    inactive_count = max(0, len(source_all_scenarios) - len(source_active_scenarios))
    st.caption(
        f"Will copy **{len(source_active_scenarios)}** active scenario(s) from "
        f"**{source_project.get('name', 'selected project')}**"
        + (f" ({inactive_count} inactive scenario(s) will be skipped)." if inactive_count else ".")
    )
    default_takt_unit = str(source_project.get("takt_time_unit") or "seconds")
    if default_takt_unit not in TIME_UNITS:
        default_takt_unit = "seconds"
    default_takt_s = float(source_project.get("takt_time_s") or 60.0)
    with st.form(f"copy_project_form_{form_key_suffix}_{source_project_id}"):
        name = st.text_input(
            "New Program Name",
            value=f"{source_project.get('name', '').strip()} (Copy)".strip(),
        )
        program = st.text_input(
            "Product",
            value=str(source_project.get("program") or ""),
        )
        loc_cols = st.columns(2)
        product_line = loc_cols[0].text_input(
            "Assembly Line",
            value=str(source_project.get("product_line") or ""),
        )
        building_location = loc_cols[1].text_input(
            "Building Location",
            value=str(source_project.get("building_location") or ""),
            placeholder="e.g. Building 2, AP1, Plant 4",
        )
        rev_cols = st.columns(3)
        revision = rev_cols[0].text_input(
            "Product baseline revision",
            value=str(source_project.get("revision") or "A"),
        )
        takt_unit = rev_cols[1].selectbox(
            "Target takt unit",
            list(TIME_UNITS),
            index=list(TIME_UNITS).index(default_takt_unit),
            format_func=lambda value: TIME_UNITS[value].label,
        )
        unit_config = time_unit(takt_unit)
        takt = rev_cols[2].number_input(
            f"Target takt time ({unit_config.label.lower()})",
            min_value=unit_config.step,
            value=seconds_to_display(default_takt_s, takt_unit),
            step=unit_config.step,
            format=f"%.{unit_config.decimals}f",
        )
        if st.form_submit_button(
            "Create project from copy",
            type="primary",
            icon=":material/content_copy:",
        ):
            if not name.strip():
                st.error("New Program Name is required.")
            elif not building_location.strip():
                st.error("Building Location is required.")
            else:
                try:
                    editor_name = st.session_state.get("current_editor", "")
                    copy_result = copy_project(
                        source_project_id,
                        name=name.strip(),
                        program=program.strip(),
                        revision=revision.strip(),
                        takt_time_s=display_to_seconds(takt, takt_unit),
                        product_line=product_line.strip(),
                        takt_time_unit=takt_unit,
                        building_location=building_location.strip(),
                        active_scenarios_only=True,
                        editor_name=editor_name,
                    )
                    created_project_id = str(copy_result["project_id"])
                    st.session_state.project_id = created_project_id
                    st.session_state.pending_active_project_id = created_project_id
                    st.session_state.scenario_id = None
                    st.session_state.pop("global_project", None)
                    st.session_state.pop("global_scenario", None)
                    set_last_active_workspace(created_project_id, None)
                    st.toast(
                        f"Created project '{name.strip()}' copied from '{source_project.get('name', '')}'",
                        icon=":material/check_circle:",
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


@st.dialog("Copy project to new NPI project")
def copy_project_dialog(default_source_project_id: str | None = None):
    _render_copy_project_form("standalone", default_source_project_id)


@st.dialog("Create an NPI project")
def new_project_dialog():
    available_projects = projects()
    creation_mode = "Blank project"
    if available_projects:
        creation_mode = st.radio(
            "Starting point",
            options=["Blank project", "Copy from an existing project"],
            horizontal=True,
            key="new_project_creation_mode",
        )
    if creation_mode == "Copy from an existing project":
        _render_copy_project_form("from_new_dialog", project_id)
        return
    with st.form("new_project"):
        name = st.text_input("Program Name")
        program = st.text_input("Product")
        loc_cols = st.columns(2)
        product_line = loc_cols[0].text_input("Assembly Line")
        building_location = loc_cols[1].text_input("Building Location", placeholder="e.g. Building 2, AP1, Plant 4")
        takt_unit = st.selectbox(
            "Target takt unit", list(TIME_UNITS), format_func=lambda value: TIME_UNITS[value].label
        )
        unit_config = time_unit(takt_unit)
        takt = st.number_input(
            f"Target takt time ({unit_config.label.lower()})",
            min_value=unit_config.step,
            value=seconds_to_display(60, takt_unit),
            step=unit_config.step,
            format=f"%.{unit_config.decimals}f",
        )
        if st.form_submit_button("Create project", type="primary", icon=":material/add:"):
            if not name.strip():
                st.error("Program Name is required.")
            elif not building_location.strip():
                st.error("Building Location is required.")
            else:
                created_project_id = create_project(
                    name, program, "", display_to_seconds(takt, takt_unit),
                    product_line=product_line, takt_time_unit=takt_unit,
                    building_location=building_location.strip(),
                )
                record_audit_event(
                    created_project_id,
                    "Projects",
                    "Create project",
                    1,
                    st.session_state.get("current_editor", ""),
                    {
                        "created_project_id": created_project_id,
                        "created_project_name": name.strip(),
                        "building_location": building_location.strip(),
                    },
                )
                st.session_state.project_id = created_project_id
                st.session_state.pending_active_project_id = created_project_id
                st.session_state.scenario_id = None
                st.session_state.pop("global_project", None)
                st.session_state.pop("global_scenario", None)
                set_last_active_workspace(created_project_id, None)
                st.toast(f"Created project '{name.strip()}' and set it as active", icon=":material/check_circle:")
                st.rerun()


@st.dialog("Delete project?", dismissible=False)
def confirm_delete_project_dialog(target_project_id: str):
    st.html(DESTRUCTIVE_BUTTON_CSS)
    target = get_project(target_project_id)
    if not target:
        st.warning("The project no longer exists.")
        if st.button("Close"):
            st.rerun()
        return
    impact = get_project_deletion_impact(target_project_id)
    st.error(
        f"**Permanently delete project:** {target['name']}?\n\n"
        "This action cannot be undone. All planning scenarios, parts, fishbone structures, "
        "Yamazumi lines, Process plans, PFMEAs, and uploaded files for this project will be permanently erased."
    )
    col1, col2, col3 = st.columns(3)
    col1.metric("Planning scenarios", impact.get("scenarios", 0))
    col2.metric("Parts", impact.get("parts", 0))
    col3.metric("Work elements", impact.get("work_elements", 0))

    col4, col5, col6 = st.columns(3)
    col4.metric("Fishbone sections", impact.get("sections", 0))
    col5.metric("Yamazumi pitches", impact.get("pitches", 0))
    col6.metric("Uploaded files", impact.get("uploads", 0))

    actions = st.container(horizontal=True)
    if actions.button("Cancel", key=f"cancel_delete_project_{target_project_id}"):
        st.rerun()
    if actions.button(
        "Delete project",
        type="primary",
        icon=":material/delete_forever:",
        key=f"destructive_confirm_delete_project_{target_project_id}",
    ):
        try:
            delete_project(target_project_id, st.session_state.get("current_editor", ""))
            all_projs = [p for p in projects() if p["id"] != target_project_id]
            if all_projs:
                st.session_state.project_id = all_projs[0]["id"]
                st.session_state.pending_active_project_id = all_projs[0]["id"]
                st.session_state.scenario_id = None
                st.session_state.pop("global_project", None)
                st.session_state.pop("global_scenario", None)
                set_last_active_workspace(all_projs[0]["id"], None)
            else:
                st.session_state.project_id = None
                st.session_state.pending_active_project_id = None
                st.session_state.scenario_id = None
                st.session_state.pop("global_project", None)
                st.session_state.pop("global_scenario", None)
                set_last_active_workspace(None, None)
            st.toast(f"Project '{target['name']}' deleted", icon=":material/check_circle:")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


if not project_id:
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("New project", icon=":material/add:"):
            new_project_dialog()
    st.info("Create a project to begin.")
    st.stop()

project = get_project(project_id)
if not project:
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("New project", icon=":material/add:"):
            new_project_dialog()
    st.info("The selected project was not found. Please select or create a project.")
    st.stop()

scenario = get_planning_scenario(project_id, scenario_id) if scenario_id else None
parts = project_table("parts", project_id)
elements = project_table("work_elements", project_id, "sequence", scenario_id=scenario_id)
concerns = project_table("concerns", project_id)
total_cycle = float(elements["cycle_time_s"].sum()) if not elements.empty else 0.0
active_takt_unit = str((scenario or project).get("takt_time_unit") or "seconds")

# 1. Active parts metric
active_parts_count = len(active_part_ids(project_id, scenario_id)) if scenario_id else len(parts)
total_catalog_parts = len(parts)
baseline_parts_val = project.get("baseline_parts")
has_baseline_parts = (
    baseline_parts_val is not None
    and not pd.isna(baseline_parts_val)
    and float(baseline_parts_val) > 0
)
if has_baseline_parts:
    base_parts = float(baseline_parts_val)
    parts_pct_diff = ((active_parts_count - base_parts) / base_parts) * 100.0
    parts_icon = (
        "🟢"
        if active_parts_count <= base_parts
        else ("🟡" if active_parts_count <= base_parts * 1.05 else "🔴")
    )
    parts_value_str = f"{parts_icon} {active_parts_count:,}"
    parts_delta = f"{parts_pct_diff:+.1f}% vs. baseline ({int(round(base_parts)):,})"
    parts_delta_color = "inverse"
else:
    parts_value_str = f"{active_parts_count:,}"
    parts_delta = f"{total_catalog_parts:,} in catalog · Set baseline below"
    parts_delta_color = "off"
parts_help = (
    f"Number of Parts Catalog items marked Active in the current scenario "
    f"({active_parts_count:,} of {total_catalog_parts:,} total catalog parts). "
    "Compared against Baseline parts in Project definition—a negative % means fewer parts than "
    "baseline (🟢 at/below baseline, 🟡 within +5%, 🔴 >5% above baseline)."
)

# 2. Hours per unit (HPU) metric — Option A: (Active Operator Pitches × 2,000 hrs/yr) ÷ Active Model EAU
ANNUAL_HOURS_PER_OPERATOR = 2000.0
pitches_df = (
    yamazumi_pitches_for_scenario(project_id, scenario_id)
    if scenario_id
    else pd.DataFrame()
)
active_pitch_count = (
    int((pitches_df["status"].fillna("").astype(str) == "Active").sum())
    if not pitches_df.empty and "status" in pitches_df.columns
    else 0
)
areas_df = (
    yamazumi_areas(project_id, scenario_id)
    if scenario_id
    else pd.DataFrame()
)
team_leaders_count = (
    int(
        pd.to_numeric(areas_df["team_leaders"], errors="coerce")
        .fillna(0)
        .clip(lower=0)
        .sum()
    )
    if not areas_df.empty and "team_leaders" in areas_df.columns
    else 0
)
control_person_count = (
    int(
        pd.to_numeric(areas_df["control_person"], errors="coerce")
        .fillna(0)
        .clip(lower=0)
        .sum()
    )
    if not areas_df.empty and "control_person" in areas_df.columns
    else 0
)
replacement_operators_count = (
    int(
        pd.to_numeric(areas_df["replacement_operators"], errors="coerce")
        .fillna(0)
        .clip(lower=0)
        .sum()
    )
    if not areas_df.empty and "replacement_operators" in areas_df.columns
    else 0
)
area_support_headcount = (
    team_leaders_count + control_person_count + replacement_operators_count
)
total_headcount = active_pitch_count + area_support_headcount
models_df = project_models(project_id)
active_models_df = (
    models_df[models_df["active"].fillna(1).astype(bool)]
    if not models_df.empty and "active" in models_df.columns
    else models_df
)
total_active_eau = (
    float(
        pd.to_numeric(active_models_df["eau"], errors="coerce")
        .fillna(0.0)
        .clip(lower=0.0)
        .sum()
    )
    if not active_models_df.empty and "eau" in active_models_df.columns
    else 0.0
)
annual_labor_hours = total_headcount * ANNUAL_HOURS_PER_OPERATOR
current_hpu = (
    annual_labor_hours / total_active_eau
    if (total_headcount > 0 and total_active_eau > 0)
    else None
)
baseline_hpu_val = project.get("baseline_hpu")
has_baseline_hpu = (
    baseline_hpu_val is not None
    and not pd.isna(baseline_hpu_val)
    and float(baseline_hpu_val) > 0
)
if current_hpu is not None:
    hpu_num_str = f"{current_hpu:.2f}" if current_hpu >= 1.0 else f"{current_hpu:.3f}"
    if has_baseline_hpu:
        base_hpu = float(baseline_hpu_val)
        hpu_pct_diff = ((current_hpu - base_hpu) / base_hpu) * 100.0
        hpu_icon = (
            "🟢"
            if current_hpu <= base_hpu
            else ("🟡" if current_hpu <= base_hpu * 1.05 else "🔴")
        )
        hpu_value_str = f"{hpu_icon} {hpu_num_str} hrs"
        base_hpu_str = f"{base_hpu:.2f}" if base_hpu >= 1.0 else f"{base_hpu:.3f}"
        hpu_delta = f"{hpu_pct_diff:+.1f}% vs. baseline ({base_hpu_str} hrs)"
        hpu_delta_color = "inverse"
    else:
        hpu_value_str = f"{hpu_num_str} hrs"
        hpu_delta = (
            f"{total_headcount} total headcount ({active_pitch_count} pitch(es) + {area_support_headcount} area support) · {int(round(total_active_eau)):,} EAU"
            if area_support_headcount > 0
            else f"{active_pitch_count} active pitch(es) · {int(round(total_active_eau)):,} EAU"
        )
        hpu_delta_color = "off"
else:
    hpu_value_str = "—"
    if total_headcount == 0 and total_active_eau <= 0:
        hpu_delta = "Needs active pitches & model EAU"
    elif total_active_eau <= 0:
        hpu_delta = "Set EAU on active models"
    else:
        hpu_delta = "No active Yamazumi pitches"
    hpu_delta_color = "off"
hpu_help = (
    "Labor Hours Per Unit = (Total Headcount × 2,000 annual working hours per operator) "
    "÷ Total EAU of Active Models, where Total Headcount = Active Yamazumi Operator Pitches "
    "+ Team Leaders + Control Person + Replacement Operators across Yamazumi areas. "
    f"Current scenario: {total_headcount} total headcount ({active_pitch_count} active pitch(es), "
    f"{team_leaders_count} team leader(s), {control_person_count} control person(s), "
    f"{replacement_operators_count} replacement operator(s); {int(annual_labor_hours):,} labor hrs/yr) "
    f"÷ {int(round(total_active_eau)):,} active-model EAU. "
    "Compared against Baseline HPU in Project definition—a negative % means fewer labor hours per unit."
)

# 3. Σ Cycle time metric
baseline_cycle_val = project.get("baseline_cycle_time_s")
has_baseline_cycle = (
    baseline_cycle_val is not None
    and not pd.isna(baseline_cycle_val)
    and float(baseline_cycle_val) > 0
)
cycle_formatted = format_seconds(total_cycle, active_takt_unit)
if has_baseline_cycle:
    base_cycle_s = float(baseline_cycle_val)
    cycle_pct_diff = ((total_cycle - base_cycle_s) / base_cycle_s) * 100.0
    cycle_icon = (
        "🟢"
        if total_cycle <= base_cycle_s
        else ("🟡" if total_cycle <= base_cycle_s * 1.05 else "🔴")
    )
    cycle_value_str = f"{cycle_icon} {cycle_formatted}"
    cycle_delta = (
        f"{cycle_pct_diff:+.1f}% vs. baseline "
        f"({format_seconds(base_cycle_s, active_takt_unit)})"
    )
    cycle_delta_color = "inverse"
else:
    cycle_value_str = cycle_formatted
    cycle_delta = f"{len(elements)} work element(s) · Set baseline below"
    cycle_delta_color = "off"
cycle_help = (
    f"Sum of work-element cycle times (Σ cycle_time_s) across {len(elements)} Process at a Glance "
    "step(s) in the active scenario. Compared against Baseline Σ cycle time in Project definition—"
    "a negative % means less total cycle time than baseline."
)

# 4. Open concerns metric
open_concerns_df = (
    concerns[~concerns["status"].isin(["Resolved", "Closed"])]
    if not concerns.empty
    else concerns
)
open_concerns = int(len(open_concerns_df))
resolved_concerns = int(len(concerns) - open_concerns)
critical_open = (
    int((open_concerns_df["priority"].fillna("") == "Critical").sum())
    if not open_concerns_df.empty and "priority" in open_concerns_df.columns
    else 0
)
high_open = (
    int((open_concerns_df["priority"].fillna("") == "High").sum())
    if not open_concerns_df.empty and "priority" in open_concerns_df.columns
    else 0
)
concerns_icon = "🟢" if open_concerns == 0 else ("🔴" if critical_open > 0 else "🟡")
concerns_value_str = f"{concerns_icon} {open_concerns}"
if len(concerns) == 0:
    concerns_delta = "No concerns logged (target: 0 open)"
    concerns_delta_color = "off"
elif open_concerns == 0:
    concerns_delta = f"All {resolved_concerns} resolved (target: 0 open)"
    concerns_delta_color = "normal"
elif critical_open > 0:
    concerns_delta = (
        f"{critical_open} critical, {high_open} high · "
        f"{resolved_concerns}/{len(concerns)} resolved"
    )
    concerns_delta_color = "inverse"
else:
    concerns_delta = f"{high_open} high priority · {resolved_concerns}/{len(concerns)} resolved"
    concerns_delta_color = "off"
concerns_help = (
    "Unresolved items in Questions and concerns (status of Open, Investigating, or Waiting; "
    "target is 0 open). 🟢 = 0 open concerns, 🟡 = open concerns (none Critical), "
    "🔴 = 1 or more Critical open concerns."
)

metric_cols = st.columns(4)
metric_cols[0].metric(
    "Active parts",
    parts_value_str,
    delta=parts_delta,
    delta_color=parts_delta_color,
    help=parts_help,
)
metric_cols[1].metric(
    "Hours per unit (HPU)",
    hpu_value_str,
    delta=hpu_delta,
    delta_color=hpu_delta_color,
    help=hpu_help,
)
metric_cols[2].metric(
    "Σ Cycle time",
    cycle_value_str,
    delta=cycle_delta,
    delta_color=cycle_delta_color,
    help=cycle_help,
)
metric_cols[3].metric(
    "Open concerns",
    concerns_value_str,
    delta=concerns_delta,
    delta_color=concerns_delta_color,
    help=concerns_help,
)

with st.container(horizontal=True, horizontal_alignment="right"):
    if st.button("New project", icon=":material/add:"):
        new_project_dialog()
    if project_id and st.button(
        "Delete project",
        icon=":material/delete:",
        help="Permanently delete the active project",
        key=f"destructive_delete_project_{project_id}",
    ):
        confirm_delete_project_dialog(project_id)

with st.container(border=True):
    section_heading_with_scope("Project definition", scope="project")
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.caption(
            "Starting a new NPI program from current production or a previous project? "
            "Copy this project (including only its Active scenarios) into a new project."
        )
        if st.button(
            "New project from existing project",
            icon=":material/content_copy:",
            help="Create a new project initialized with shared project data and all Active scenarios from an existing project",
            key=f"copy_project_from_definition_{project_id}",
        ):
            copy_project_dialog(project_id)
    with st.form("project_details"):
        identity_row = st.columns(2)
        name = identity_row[0].text_input("Project name", value=project["name"])
        program = identity_row[1].text_input("Program or product", value=project["program"])
        loc_row = st.columns(2)
        product_line = loc_row[0].text_input(
            "Product line", value=project.get("product_line", "")
        )
        building_location = loc_row[1].text_input(
            "Building location", value=project.get("building_location", "")
        )
        row = st.columns(3)
        revision = row[0].text_input("Product baseline revision", value=project["revision"])
        project_takt_unit = row[1].selectbox(
            "Default takt unit",
            list(TIME_UNITS),
            index=list(TIME_UNITS).index(str(project.get("takt_time_unit") or "seconds")),
            format_func=lambda value: TIME_UNITS[value].label,
        )
        project_unit_config = time_unit(project_takt_unit)
        project_original_display = seconds_to_display(
            project["takt_time_s"], project.get("takt_time_unit") or "seconds"
        )
        takt = row[2].number_input(
            f"Default takt ({project_unit_config.label.lower()})",
            min_value=project_unit_config.step,
            value=project_original_display,
            step=project_unit_config.step,
            format=f"%.{project_unit_config.decimals}f",
        )
        baseline_row = st.columns(3)
        raw_base_parts = project.get("baseline_parts")
        has_base_parts = (
            raw_base_parts is not None
            and not pd.isna(raw_base_parts)
            and float(raw_base_parts) > 0
        )
        baseline_parts_input = baseline_row[0].number_input(
            "Baseline parts",
            min_value=0,
            value=int(round(float(raw_base_parts))) if has_base_parts else None,
            step=1,
            placeholder="Optional target...",
            help=(
                "Reference or carry-over part count used to calculate % difference on the "
                "Active parts banner metric (lower than baseline is favorable)."
            ),
        )
        raw_base_hpu = project.get("baseline_hpu")
        has_base_hpu = (
            raw_base_hpu is not None
            and not pd.isna(raw_base_hpu)
            and float(raw_base_hpu) > 0
        )
        baseline_hpu_input = baseline_row[1].number_input(
            "Baseline HPU (hrs/unit)",
            min_value=0.0,
            value=float(raw_base_hpu) if has_base_hpu else None,
            step=0.01,
            format="%.3f",
            placeholder="Optional target...",
            help=(
                "Reference or carry-over Hours Per Unit (HPU) used to calculate % difference on the "
                "Hours per unit banner metric (lower than baseline is favorable)."
            ),
        )
        raw_base_cycle = project.get("baseline_cycle_time_s")
        has_base_cycle = (
            raw_base_cycle is not None
            and not pd.isna(raw_base_cycle)
            and float(raw_base_cycle) > 0
        )
        baseline_cycle_original_display = (
            seconds_to_display(
                float(raw_base_cycle), project.get("takt_time_unit") or "seconds"
            )
            if has_base_cycle
            else None
        )
        baseline_cycle_input = baseline_row[2].number_input(
            f"Baseline Σ cycle time ({project_unit_config.label.lower()})",
            min_value=0.0,
            value=(
                float(baseline_cycle_original_display)
                if baseline_cycle_original_display is not None
                else None
            ),
            step=project_unit_config.step,
            format=f"%.{project_unit_config.decimals}f",
            placeholder="Optional target...",
            help=(
                "Reference or carry-over total work-element cycle time (in the default takt unit) "
                "used to calculate % difference on the Σ Cycle time banner metric."
            ),
        )
        notes = st.text_area(
            "Planning notes", value=project["notes"],
            placeholder="Assumptions, scope, milestones, or known changes…",
        )
        proj_base_key = f"project_def_baseline_{project_id}"
        proj_conflict_key = f"project_def_conflict_{project_id}"
        live_proj_fields = {
            "name": str(project.get("name") or "").strip(),
            "program": str(project.get("program") or "").strip(),
            "product_line": str(project.get("product_line") or "").strip(),
            "building_location": str(project.get("building_location") or "").strip(),
            "revision": str(project.get("revision") or "").strip(),
            "takt_time_s": round(float(project.get("takt_time_s") or 60.0), 4),
            "takt_time_unit": str(project.get("takt_time_unit") or "seconds"),
            "baseline_parts": float(raw_base_parts) if has_base_parts else None,
            "baseline_hpu": round(float(raw_base_hpu), 4) if has_base_hpu else None,
            "baseline_cycle_time_s": round(float(raw_base_cycle), 4) if has_base_cycle else None,
            "notes": str(project.get("notes") or ""),
        }
        if proj_base_key not in st.session_state:
            st.session_state[proj_base_key] = dict(live_proj_fields)

        save_project_submitted = st.form_submit_button("Save project", type="primary", icon=":material/save:")

    proj_conflict_res, proj_conflict_payload = check_standalone_conflict_resolution(proj_conflict_key)
    if proj_conflict_res == "discard":
        st.session_state[proj_base_key] = dict(live_proj_fields)
        st.rerun()

    if save_project_submitted or proj_conflict_res is True:
        if proj_conflict_res is True and isinstance(proj_conflict_payload, dict) and isinstance(proj_conflict_payload.get("project_values"), dict):
            project_values = dict(proj_conflict_payload["project_values"])
            valid_proj = True
        else:
            valid_proj = False
            if not name.strip():
                st.error("Project name is required.")
            elif not building_location.strip():
                st.error("Building location is required.")
            else:
                valid_proj = True
                project_takt_seconds = (
                    float(project["takt_time_s"])
                    if project_takt_unit != str(project.get("takt_time_unit") or "seconds")
                    and float(takt) == float(project_original_display)
                    else display_to_seconds(takt, project_takt_unit)
                )
                if baseline_cycle_input is None or float(baseline_cycle_input) <= 0:
                    baseline_cycle_seconds = None
                elif (
                    has_base_cycle
                    and project_takt_unit != str(project.get("takt_time_unit") or "seconds")
                    and baseline_cycle_original_display is not None
                    and float(baseline_cycle_input) == float(baseline_cycle_original_display)
                ):
                    baseline_cycle_seconds = float(raw_base_cycle)
                else:
                    baseline_cycle_seconds = display_to_seconds(
                        float(baseline_cycle_input), project_takt_unit
                    )
                user_proj_fields = {
                    "name": name.strip(),
                    "program": program.strip(),
                    "product_line": product_line.strip(),
                    "building_location": building_location.strip(),
                    "revision": revision.strip(),
                    "takt_time_s": round(float(project_takt_seconds), 4),
                    "takt_time_unit": str(project_takt_unit),
                    "baseline_parts": (
                        float(baseline_parts_input)
                        if baseline_parts_input is not None and float(baseline_parts_input) > 0
                        else None
                    ),
                    "baseline_hpu": (
                        round(float(baseline_hpu_input), 4)
                        if baseline_hpu_input is not None and float(baseline_hpu_input) > 0
                        else None
                    ),
                    "baseline_cycle_time_s": (
                        round(float(baseline_cycle_seconds), 4)
                        if baseline_cycle_seconds is not None
                        else None
                    ),
                    "notes": str(notes or ""),
                }
                base_proj_fields = st.session_state.get(proj_base_key, live_proj_fields)
                merged_proj_fields, proj_conflicts = compare_record_field_conflicts(
                    row_label="Project Definition",
                    baseline=base_proj_fields,
                    live=live_proj_fields,
                    user_values=user_proj_fields,
                    field_labels={
                        "name": "Project Name",
                        "program": "Program or Product",
                        "product_line": "Product Line",
                        "building_location": "Building Location",
                        "revision": "Product Baseline Revision",
                        "takt_time_s": "Default Takt (s)",
                        "takt_time_unit": "Default Takt Unit",
                        "baseline_parts": "Baseline Parts",
                        "baseline_hpu": "Baseline HPU",
                        "baseline_cycle_time_s": "Baseline Σ Cycle Time (s)",
                        "notes": "Planning Notes",
                    },
                )
                project_values = {
                    "name": merged_proj_fields["name"],
                    "program": merged_proj_fields["program"],
                    "product_line": merged_proj_fields["product_line"],
                    "building_location": merged_proj_fields["building_location"],
                    "owner": project.get("owner", ""),
                    "revision": merged_proj_fields["revision"],
                    "status": project.get("status", "Draft"),
                    "takt_time_s": float(merged_proj_fields["takt_time_s"]),
                    "takt_time_unit": merged_proj_fields["takt_time_unit"],
                    "baseline_parts": merged_proj_fields["baseline_parts"],
                    "baseline_hpu": merged_proj_fields["baseline_hpu"],
                    "baseline_cycle_time_s": merged_proj_fields["baseline_cycle_time_s"],
                    "notes": merged_proj_fields["notes"],
                }
                if proj_conflicts:
                    overwrite_values = {
                        **project_values,
                        **user_proj_fields,
                        "owner": project.get("owner", ""),
                        "status": project.get("status", "Draft"),
                    }
                    trigger_standalone_conflict_dialog(
                        proj_conflict_key,
                        proj_conflicts,
                        payload={"project_values": overwrite_values},
                    )
                    st.rerun()

        if valid_proj:
            project_changed_fields = [
                field for field, value in project_values.items()
                if value != project.get(field)
            ]
            update_project(project_id, project_values)
            st.session_state[proj_base_key] = {
                k: project_values.get(k) for k in live_proj_fields.keys()
            }
            record_audit_event(
                project_id,
                "Projects",
                "Save project",
                1,
                st.session_state.get("current_editor", ""),
                {
                    "project_id": project_id,
                    "project_name": str(project_values["name"]).strip(),
                    "project_changed_fields": project_changed_fields,
                },
            )
            st.toast(
                f"Saved project '{str(project_values['name']).strip()}'"
                + (f" ({len(project_changed_fields)} field(s) updated)" if project_changed_fields else ""),
                icon=":material/check_circle:",
            )
            st.rerun()
    render_standalone_conflict_dialog(proj_conflict_key)

if scenario:
    scenario_editor_key = f"overview_scenario_editor_{project_id}"
    scenario_editor_key = apply_pending_table_editor_reset(scenario_editor_key)
    all_scenarios = planning_scenarios(project_id, include_archived=True)
    scenario_columns = [
        "id", "view_details", "current_view", "active", "name", "revision_label", "status",
        "takt", "takt_time_unit", "takt_time_s", "change_summary",
        "parent_scenario_id", "parent_scenario",
        "created_by", "created_at", "updated_at",
    ]
    scenario_rows = pd.DataFrame(all_scenarios)
    scenario_rows["view_details"] = ":material/visibility: View details"
    scenario_rows["current_view"] = [
        "Current view" if str(value) == str(scenario_id) else ""
        for value in scenario_rows["id"]
    ]
    scenario_rows["active"] = [
        str(status_val or "Working").strip().title() != "Archived"
        for status_val in scenario_rows.get("status", [])
    ]
    scenario_rows["takt"] = [
        seconds_to_display(ts, tu)
        for ts, tu in zip(scenario_rows["takt_time_s"], scenario_rows["takt_time_unit"])
    ]
    scenario_rows["parent_scenario"] = [
        f"Rev {prev} · {pname}"
        if pd.notna(pid) and str(pid).strip()
        else "Original scenario"
        for pid, prev, pname in zip(
            scenario_rows.get("parent_scenario_id", []),
            scenario_rows.get("parent_revision_label", []),
            scenario_rows.get("parent_name", []),
        )
    ]
    scenario_rows = scenario_rows.reindex(columns=scenario_columns)
    for column in [
        column for column in scenario_columns if column not in {"active", "takt", "takt_time_s"}
    ]:
        scenario_rows[column] = scenario_rows[column].astype("string").fillna("")
    scenario_rows["active"] = scenario_rows["active"].fillna(True).astype(bool)
    scenario_rows["takt_time_s"] = pd.to_numeric(
        scenario_rows["takt_time_s"], errors="coerce"
    ).astype("float64")
    scenario_rows["takt"] = pd.to_numeric(
        scenario_rows["takt"], errors="coerce"
    ).astype("float64")
    for column in ["created_at", "updated_at"]:
        scenario_rows[column] = pd.to_datetime(
            scenario_rows[column], errors="coerce", utc=True
        ).dt.tz_convert("America/New_York")

    with st.container(border=True):
        section_heading_with_scope(
            "Planning scenarios", scope="scenario", scenario_name=scenario["name"]
        )
        st.caption(
            "Edit saved scenario metadata directly. Use the Active checkbox to turn scenarios "
            "on or off across workspace scenario selectors (and control which scenarios are "
            "included when copying a project). A new row creates a complete branch from the "
            "currently viewed scenario, including its Yamazumi and Process at a Glance data."
        )
        st.info(
            "When you switch scenarios, the app changes which Parts Catalog records are Active, "
            "along with the Yamazumi plan, Process at a Glance plan, and derived Pin Map. Project "
            "definitions, Model definitions, Parts Catalog master records, Assembly grid, the "
            "Fishbone framework and uses, imports, and Questions and concerns stay shared across "
            "all scenarios, so edits to that shared data affect every scenario.",
            icon=":material/info:",
        )
        editable_table_heading("Scenario definitions")

        visible_scenarios = filter_table(
            scenario_rows, key=f"overview_scenario_filters_{project_id}",
            dropdown_columns=["active", "parent_scenario"],
            search_columns=[
                "name", "revision_label", "status", "change_summary",
                "parent_scenario", "created_by",
            ],
            labels={"active": "Active", "parent_scenario": "Source scenario"},
            reset_widget_keys=[scenario_editor_key],
        )
        selected_detail_key = f"overview_scenario_details_{project_id}"

        def open_scenario_details() -> None:
            click = st.session_state.get(f"overview_scenario_details_action_{project_id}") or {}
            position = click.get("row")
            if position is not None and 0 <= int(position) < len(visible_scenarios):
                selected_id = str(editor_rows.iloc[int(position)]["id"] or "")
                if selected_id:
                    st.session_state[selected_detail_key] = selected_id

        suggested_revision = next_scenario_revision_label(
            project_id, str(scenario["revision_label"])
        )
        editor_rows = direct_entry_editor_rows(
            visible_scenarios, editor_key=scenario_editor_key,
            sort_columns=[
                "current_view", "active", "name", "revision_label", "takt",
                "takt_time_unit",
                "change_summary", "parent_scenario", "created_by", "updated_at",
            ],
            labels={
                "current_view": "View", "active": "Active", "name": "Scenario name",
                "revision_label": "Scenario revision", "takt": "Takt",
                "takt_time_unit": "Takt unit",
                "parent_scenario": "Source scenario", "created_by": "Created by",
                "updated_at": "Updated",
            },
        )
        if "active" in editor_rows.columns:
            new_scen_mask = editor_rows["id"].fillna("").astype(str).str.strip() == ""
            editor_rows.loc[new_scen_mask, "active"] = True
            editor_rows["active"] = editor_rows["active"].fillna(True).astype(bool)
        edited_scenarios = st.data_editor(
            editor_rows, key=scenario_editor_key, hide_index=True,
            num_rows="dynamic", height=390,
            disabled=[
                "id", "view_details", "current_view", "parent_scenario_id",
                "parent_scenario", "created_by", "created_at", "updated_at",
            ],
            column_order=[
                "view_details", "current_view", "active", "name", "revision_label",
                "takt", "takt_time_unit", "change_summary", "parent_scenario",
                "created_by", "updated_at",
            ],
            column_config={
                "id": None,
                "view_details": standard_details_column_config(
                    on_click=open_scenario_details,
                    key=f"overview_scenario_details_action_{project_id}",
                ),
                "current_view": st.column_config.TextColumn("View", pinned=True),
                "active": st.column_config.CheckboxColumn(
                    "Active",
                    default=True,
                    help=(
                        "Active scenarios appear in scenario selectors across the workspace "
                        "and are included when copying this project to a new NPI project. "
                        "Uncheck to hide a scenario from active selectors without deleting its data."
                    ),
                ),
                "name": st.column_config.TextColumn("Scenario name", required=True, pinned=True),
                "revision_label": st.column_config.TextColumn(
                    "Scenario revision", required=True, default=suggested_revision
                ),
                "status": None,
                "takt": st.column_config.NumberColumn(
                    "Takt", required=True, min_value=0.0001,
                    step=0.0001, format="%.4f",
                    default=seconds_to_display(
                        project["takt_time_s"], project["takt_time_unit"]
                    ),
                ),
                "takt_time_unit": st.column_config.SelectboxColumn(
                    "Takt unit", options=list(TIME_UNITS), required=True,
                    default=str(project["takt_time_unit"]),
                ),
                "takt_time_s": None,
                "change_summary": st.column_config.TextColumn("Change summary", width="large"),
                "parent_scenario_id": None,
                "parent_scenario": st.column_config.TextColumn("Source scenario"),
                "created_by": st.column_config.TextColumn("Created by"),
                "created_at": st.column_config.DatetimeColumn(
                    "Created", format="MMM DD, YYYY HH:mm", timezone="America/New_York"
                ),
                "updated_at": st.column_config.DatetimeColumn(
                    "Updated", format="MMM DD, YYYY HH:mm", timezone="America/New_York"
                ),
            },
        )
        scenario_actions = editable_table_footer(
            editor_key=scenario_editor_key,
            key_prefix=f"overview_scenarios_{project_id}",
            native_row_selection=True,
        )
        if scenario_actions.undo:
            request_table_editor_reset(scenario_editor_key)
            st.toast("Discarded the unsaved planning scenario edits", icon=":material/undo:")
            st.rerun()
        selected_scenarios = native_selected_rows(
            editor_rows, editor_key=scenario_editor_key
        )
        def _export_planning_scenarios() -> bytes:
            scenario_export = visible_scenarios.drop(
                columns=["id", "view_details", "parent_scenario_id", "takt_time_s"],
                errors="ignore"
            ).copy()
            scenario_export["takt_time_unit"] = [
                TIME_UNITS[str(value)].label for value in scenario_export["takt_time_unit"]
            ]
            for column in ["created_at", "updated_at"]:
                if column in scenario_export:
                    scenario_export[column] = scenario_export[column].astype("string")
            return dataframe_to_excel(scenario_export, "Planning scenarios")

        with st.container(horizontal=True, horizontal_alignment="right"):
            st.download_button(
                "Export filtered",
                data=_export_planning_scenarios,
                file_name="planning_scenarios_filtered.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                icon=":material/download:", key=f"overview_scenarios_export_{project_id}",
            )

        if scenario_actions.save_and_refresh:
            try:
                if not selected_scenarios.empty:
                    raise ValueError("Clear selected rows before saving scenario edits.")
                edited_scenarios = drop_untouched_new_rows(
                    edited_scenarios, identifying_columns=["name"]
                )
                merged_scenarios = merge_filtered_edits(
                    scenario_rows, visible_scenarios, edited_scenarios
                )
                errors = required_field_errors(
                    merged_scenarios,
                    {
                        "name": "Scenario name", "revision_label": "Scenario revision",
                        "takt": "Takt",
                        "takt_time_unit": "Takt unit",
                    },
                )
                if errors:
                    raise ValueError(" ".join(errors))
                original_scenarios = {
                    str(row["id"]): row for row in all_scenarios
                }
                save_records = []
                for record in merged_scenarios.to_dict("records"):
                    record_id = str(record.get("id") or "")
                    orig_status = (
                        str(original_scenarios[record_id].get("status") or "Working").strip().title()
                        if record_id in original_scenarios else "Working"
                    )
                    raw_active = record.get("active")
                    is_active = True if raw_active is None or pd.isna(raw_active) else bool(raw_active)
                    if is_active:
                        record["status"] = orig_status if orig_status != "Archived" else "Working"
                    else:
                        record["status"] = "Archived"
                    record["active"] = is_active
                    selected_unit = str(record.get("takt_time_unit") or "seconds")
                    original = original_scenarios.get(record_id)
                    original_display = (
                        seconds_to_display(
                            original["takt_time_s"], original["takt_time_unit"]
                        )
                        if original else None
                    )
                    if (
                        original
                        and selected_unit != str(original["takt_time_unit"])
                        and float(record["takt"]) == float(original_display)
                    ):
                        record["takt_time_s"] = float(original["takt_time_s"])
                    else:
                        record["takt_time_s"] = display_to_seconds(
                            record["takt"], selected_unit
                        )
                    save_records.append(record)
                active_scenario_row = pd.DataFrame(save_records).loc[
                    merged_scenarios["id"].astype(str) == str(scenario_id)
                ]
                active_scenario_values = (
                    active_scenario_row.iloc[0].to_dict()
                    if not active_scenario_row.empty else scenario
                )
                active_scenario_changed_fields = [
                    field
                    for field in [
                        "name", "revision_label", "status", "takt_time_s",
                        "takt_time_unit",
                        "change_summary",
                    ]
                    if active_scenario_values.get(field) != scenario.get(field)
                ]
                result = save_planning_scenario_rows(
                    project_id, str(scenario_id), save_records,
                    st.session_state.get("current_editor", ""),
                )
                record_audit_event(
                    project_id, "Planning scenarios", "Save & Refresh",
                    int(result["saved_count"]),
                    st.session_state.get("current_editor", ""),
                    {
                        "source_scenario_id": str(scenario_id),
                        "created_scenario_ids": result["created_ids"],
                        "created_count": len(result["created_ids"]), "updated_count": int(result.get("modified_count", result["updated_count"])),
                        "active_scenario_name": str(active_scenario_values.get("name") or ""),
                        "active_scenario_changed_fields": active_scenario_changed_fields,
                    },
                )
                active_after_save = planning_scenarios(project_id, include_archived=False)
                active_ids_after_save = [str(row["id"]) for row in active_after_save]
                if result["created_ids"]:
                    newest_id = str(result["created_ids"][-1])
                    sync_active_scenario_state(newest_id, update_query_params=True)
                    set_last_active_workspace(project_id, newest_id)
                    st.session_state[selected_detail_key] = newest_id
                elif str(scenario_id) not in active_ids_after_save and active_ids_after_save:
                    fallback_id = active_ids_after_save[0]
                    sync_active_scenario_state(fallback_id, update_query_params=True)
                    set_last_active_workspace(project_id, fallback_id)
                    st.session_state[selected_detail_key] = fallback_id
                request_table_editor_reset(scenario_editor_key)
                created_scen_count = len(result["created_ids"])
                updated_scen_count = int(result["updated_count"])
                scen_toast = f"Saved {result['saved_count']} planning scenario(s)"
                scen_details: list[str] = []
                if updated_scen_count:
                    scen_details.append(f"{updated_scen_count} updated")
                if created_scen_count:
                    scen_details.append(f"{created_scen_count} branched and set active")
                if scen_details:
                    scen_toast += f" ({', '.join(scen_details)})"
                st.toast(scen_toast, icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        selected_detail_id = str(st.session_state.get(selected_detail_key) or "")
        detail = next(
            (row for row in all_scenarios if str(row["id"]) == selected_detail_id), None
        )
        if detail:
            st.divider()
            st.subheader(f"Scenario details · {detail['name']}")
            detail_metrics = st.columns(4)
            detail_metrics[0].metric("Revision", detail["revision_label"])
            detail_metrics[1].metric("Active", "Yes" if str(detail.get("status") or "Working").strip().title() != "Archived" else "No")
            detail_metrics[2].metric("Takt", format_seconds(detail["takt_time_s"], detail["takt_time_unit"]))
            detail_metrics[3].metric("Current view", "Yes" if str(detail["id"]) == str(scenario_id) else "No")
            source_label = (
                f"Rev {detail.get('parent_revision_label')} · {detail.get('parent_name')}"
                if detail.get("parent_scenario_id") else "Original scenario"
            )
            st.markdown(f"**Source scenario:** {source_label}")
            st.markdown(
                f"**Change summary:** {detail.get('change_summary') or 'No change summary entered.'}"
            )
            st.caption(
                f"Created by {detail.get('created_by') or 'Not recorded'} on "
                f"{format_eastern_timestamp(detail.get('created_at')) or 'an unknown date'} · Last updated "
                f"{format_eastern_timestamp(detail.get('updated_at')) or 'on an unknown date'}"
            )

with st.expander("History", icon=":material/history:"):
    project_history_tab, scenario_history_tab = st.tabs(
        ["Project", "Planning scenarios"]
    )
    with project_history_tab:
        project_history = audit_history(project_id, "Projects", limit=50)
        if project_history.empty:
            st.caption("No project history has been recorded yet.")
        else:
            render_audit_history_table(
                project_history.drop(columns=["details"], errors="ignore"),
                key=f"overview_project_history_{project_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm", timezone="America/New_York"
                    ),
                },
            )
    with scenario_history_tab:
        scenario_history = audit_history(project_id, "Planning scenarios", limit=50)
        if scenario_history.empty:
            st.caption("No planning-scenario history has been recorded yet.")
        else:
            render_audit_history_table(
                scenario_history.drop(columns=["details"], errors="ignore"),
                key=f"overview_scenario_history_{project_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Rows",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm", timezone="America/New_York"
                    ),
                },
            )
