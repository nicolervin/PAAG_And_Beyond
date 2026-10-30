import pandas as pd
import streamlit as st

from utils.time_units import (
    TIME_UNITS, display_to_seconds, format_seconds, seconds_to_display, time_unit,
)
from utils.scope_ui import page_title_with_scope, section_heading_with_scope
from utils.table_filters import apply_pending_table_editor_reset, filter_table, merge_filtered_edits, request_table_editor_reset
from utils.table_ui import (
    dataframe_to_excel, drop_untouched_new_rows, editable_table_footer,
    editable_table_heading,
    native_selected_rows, render_audit_history_table, required_field_errors, selectable_dataframe,
    direct_entry_editor_rows, standard_details_column_config,
)
from utils.store import (
    audit_history, create_project, delete_project, format_eastern_timestamp,
    get_planning_scenario, get_project,
    get_project_deletion_impact, next_scenario_revision_label, planning_scenarios,
    project_table, projects, record_audit_event, save_planning_scenario_rows,
    active_part_ids, project_models, set_last_active_workspace, update_project,
    yamazumi_pitches_for_scenario,
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


@st.dialog("Create an NPI project")
def new_project_dialog():
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
annual_labor_hours = active_pitch_count * ANNUAL_HOURS_PER_OPERATOR
current_hpu = (
    annual_labor_hours / total_active_eau
    if (active_pitch_count > 0 and total_active_eau > 0)
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
        hpu_delta = f"{active_pitch_count} active pitch(es) · {int(round(total_active_eau)):,} EAU"
        hpu_delta_color = "off"
else:
    hpu_value_str = "—"
    if active_pitch_count == 0 and total_active_eau <= 0:
        hpu_delta = "Needs active pitches & model EAU"
    elif total_active_eau <= 0:
        hpu_delta = "Set EAU on active models"
    else:
        hpu_delta = "No active Yamazumi pitches"
    hpu_delta_color = "off"
hpu_help = (
    "Labor Hours Per Unit = (Active Yamazumi Operator Pitches × 2,000 annual working hours per operator) "
    "÷ Total EAU of Active Models. "
    f"Current scenario: {active_pitch_count} active pitch(es) ({int(annual_labor_hours):,} labor hrs/yr) "
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
        if st.form_submit_button("Save project", type="primary", icon=":material/save:"):
            if not name.strip():
                st.error("Project name is required.")
            elif not building_location.strip():
                st.error("Building location is required.")
            else:
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
                project_values = {
                    "name": name.strip(), "program": program.strip(),
                    "product_line": product_line.strip(),
                    "building_location": building_location.strip(),
                    "owner": project.get("owner", ""), "revision": revision.strip(),
                    "status": project.get("status", "Draft"),
                    "takt_time_s": project_takt_seconds,
                    "takt_time_unit": project_takt_unit,
                    "baseline_parts": (
                        float(baseline_parts_input)
                        if baseline_parts_input is not None and float(baseline_parts_input) > 0
                        else None
                    ),
                    "baseline_hpu": (
                        float(baseline_hpu_input)
                        if baseline_hpu_input is not None and float(baseline_hpu_input) > 0
                        else None
                    ),
                    "baseline_cycle_time_s": baseline_cycle_seconds,
                    "notes": notes,
                }
                project_changed_fields = [
                    field for field, value in project_values.items()
                    if value != project.get(field)
                ]
                update_project(project_id, project_values)
                record_audit_event(
                    project_id,
                    "Projects",
                    "Save project",
                    1,
                    st.session_state.get("current_editor", ""),
                    {
                        "project_id": project_id,
                        "project_name": name.strip(),
                        "project_changed_fields": project_changed_fields,
                    },
                )
                st.toast(
                    f"Saved project '{name.strip()}'"
                    + (f" ({len(project_changed_fields)} field(s) updated)" if project_changed_fields else ""),
                    icon=":material/check_circle:",
                )
                st.rerun()

if scenario:
    scenario_editor_key = f"overview_scenario_editor_{project_id}"
    scenario_editor_key = apply_pending_table_editor_reset(scenario_editor_key)
    all_scenarios = planning_scenarios(project_id, include_archived=True)
    scenario_columns = [
        "id", "view_details", "current_view", "name", "revision_label", "status",
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
        column for column in scenario_columns if column not in {"takt", "takt_time_s"}
    ]:
        scenario_rows[column] = scenario_rows[column].astype("string").fillna("")
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
            "Edit saved scenario metadata directly. A new row creates a complete branch from the "
            "currently viewed scenario, including its Yamazumi and Process at a Glance data. "
            "The newest saved branch becomes the shared scenario view across pages."
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
            dropdown_columns=["status", "parent_scenario"],
            search_columns=[
                "name", "revision_label", "status", "change_summary",
                "parent_scenario", "created_by",
            ],
            labels={"parent_scenario": "Source scenario"},
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
                "current_view", "name", "revision_label", "takt",
                "takt_time_unit",
                "change_summary", "parent_scenario", "created_by", "updated_at",
            ],
            labels={
                "current_view": "View", "name": "Scenario name",
                "revision_label": "Scenario revision", "takt": "Takt",
                "takt_time_unit": "Takt unit",
                "parent_scenario": "Source scenario", "created_by": "Created by",
                "updated_at": "Updated",
            },
        )
        edited_scenarios = st.data_editor(
            editor_rows, key=scenario_editor_key, hide_index=True,
            num_rows="dynamic", height=390,
            disabled=[
                "id", "view_details", "current_view", "parent_scenario_id",
                "parent_scenario", "created_by", "created_at", "updated_at",
            ],
            column_order=[
                "view_details", "current_view", "name", "revision_label",
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
                    record["status"] = (
                        str(original_scenarios[record_id].get("status") or "Working")
                        if record_id in original_scenarios else "Working"
                    )
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
                if result["created_ids"]:
                    newest_id = str(result["created_ids"][-1])
                    st.session_state["scenario_id"] = newest_id
                    st.session_state["global_scenario"] = newest_id
                    st.session_state["_qp_synced_scenario_id"] = newest_id
                    try:
                        st.query_params["scenario_id"] = newest_id
                    except Exception:
                        pass
                    st.session_state[selected_detail_key] = newest_id
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
            detail_metrics[1].metric("Status", detail["status"])
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
