from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.time_units import format_seconds

from utils.fishbone_ui import ordered_yamazumi_area_ids, section_breadcrumb_labels
from utils.scope_ui import page_title_with_scope
from utils.store import (
    assembly_section_walk_order,
    get_planning_scenario,
    pin_map_for_scenario,
)
from utils.table_ui import dataframe_to_excel


def clean_text(value: object) -> str:
    """Return display-safe text for nullable Process and pitch values."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def seconds_label(value: object) -> str:
    """Format a nullable duration consistently for the visual cards."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = 0.0
    if pd.isna(seconds):
        seconds = 0.0
    return f"{seconds:.1f} s"


project_id = st.session_state.get("project_id")
scenario_id = st.session_state.get("scenario_id")
if not project_id or not scenario_id:
    st.stop()

scenario = get_planning_scenario(project_id, scenario_id)
if not scenario:
    st.error("The active planning scenario no longer exists.")
    st.stop()

page_title_with_scope(
    "Pin Map", scope="scenario", scenario_name=scenario["name"]
)
st.caption(
    "See the active scenario as a line map, with linked Process at a Glance work "
    "shown above each Yamazumi workstation or pitch."
)
st.caption(
    f"Scenario revision {scenario['revision_label']} · "
    f"{format_seconds(scenario['takt_time_s'], scenario['takt_time_unit'])} takt"
)

pin_map = pin_map_for_scenario(project_id, scenario_id)
if pin_map.empty:
    st.info(
        "Add Yamazumi pitch addresses to this scenario to begin the Pin Map.",
        icon=":material/map:",
    )
    with st.expander("History", icon=":material/history:"):
        st.caption(
            "Pin Map is a read-only view of Yamazumi and Process at a Glance data; "
            "it does not create its own saved history."
        )
    st.stop()

pitch_rows = pin_map.drop_duplicates(subset=["pitch_id"], keep="first").copy()
controls = st.container(horizontal=True, vertical_alignment="bottom")
sections = assembly_section_walk_order(project_id)
section_labels = section_breadcrumb_labels(sections)
area_rows = (
    pitch_rows[["area_id", "area_name", "section_id"]]
    .drop_duplicates(subset=["area_id"], keep="first")
    .rename(columns={"area_id": "id", "area_name": "name"})
)
area_options = ordered_yamazumi_area_ids(
    area_rows,
    sections["id"].astype(str).tolist() if not sections.empty else [],
)
area_labels = {}
for _, area_row in area_rows.iterrows():
    area_id = str(area_row["id"])
    area_name = str(area_row["name"])
    section_id = clean_text(area_row.get("section_id"))
    area_labels[area_id] = (
        f"{area_name} · Fishbone: {section_labels[section_id]}"
        if section_id in section_labels else f"{area_name} · Unlinked"
    )
area_filter_key = f"pin_map_areas_{scenario_id}"
stored_areas = st.session_state.get(area_filter_key, [])
if isinstance(stored_areas, (list, tuple)):
    area_id_by_name = {
        str(row["name"]): str(row["id"]) for _, row in area_rows.iterrows()
    }
    normalized_areas = [
        str(value) if str(value) in area_labels else area_id_by_name.get(str(value), "")
        for value in stored_areas
    ]
    st.session_state[area_filter_key] = [
        area_id for area_id in normalized_areas if area_id in area_labels
    ]
selected_area_ids = controls.multiselect(
    "Yamazumi areas",
    options=area_options,
    format_func=lambda value: area_labels.get(value, value),
    placeholder="All areas",
    key=area_filter_key,
)
status_options = pitch_rows["pitch_status"].dropna().astype(str).unique().tolist()
selected_statuses = controls.multiselect(
    "Pitch status",
    options=status_options,
    placeholder="All statuses",
    key=f"pin_map_statuses_{scenario_id}",
)
type_options = pitch_rows["pitch_type"].dropna().astype(str).unique().tolist()
selected_types = controls.multiselect(
    "Pitch type",
    options=type_options,
    placeholder="All types",
    key=f"pin_map_types_{scenario_id}",
)
keyword = controls.text_input(
    "Filter by keyword",
    placeholder="Search pitches or process work",
    icon=":material/search:",
    key=f"pin_map_keyword_{scenario_id}",
)

visible = pin_map.copy()
if selected_area_ids:
    visible = visible[visible["area_id"].astype(str).isin(selected_area_ids)]
if selected_statuses:
    visible = visible[visible["pitch_status"].isin(selected_statuses)]
if selected_types:
    visible = visible[visible["pitch_type"].isin(selected_types)]
if keyword.strip():
    search_columns = [
        "area_name", "pitch_number", "pitch_name", "pitch_type",
        "work_element", "process_description", "tool", "location",
    ]
    searchable = visible[search_columns].fillna("").astype(str).agg(" ".join, axis=1)
    visible = visible[
        searchable.str.contains(keyword.strip(), case=False, regex=False)
    ]

visible_pitches = visible.drop_duplicates(subset=["pitch_id"], keep="first")
linked_work = visible.loc[visible["process_element_id"].notna()].drop_duplicates(
    subset=["process_element_id"], keep="first"
)
summary = st.columns(3)
summary[0].metric("Visible pitches", len(visible_pitches))
summary[1].metric("Linked process steps", len(linked_work))
summary[2].metric(
    "Linked cycle time",
    f"{pd.to_numeric(linked_work['cycle_time_s'], errors='coerce').fillna(0).sum():.1f} s",
)

if visible_pitches.empty:
    st.info("No pitches match the current filters.", icon=":material/filter_alt_off:")
else:
    st.caption(
        "Line flow runs left to right. Process work appears above its workstation or pitch."
    )
    visible_area_ids = [
        area_id for area_id in area_options
        if area_id in set(visible_pitches["area_id"].astype(str))
    ]
    for area_id in visible_area_ids:
        area_name = clean_text(
            visible_pitches.loc[
                visible_pitches["area_id"].astype(str).eq(area_id), "area_name"
            ].iloc[0]
        )
        st.subheader(str(area_name))
        area_pitches = visible_pitches.loc[
            visible_pitches["area_id"].astype(str) == area_id
        ].sort_values(["pitch_sequence", "pitch_number"], kind="stable")
        line = st.container(horizontal=True, vertical_alignment="top", gap="small")
        for _, pitch in area_pitches.iterrows():
            pitch_id = str(pitch["pitch_id"])
            process_rows = visible.loc[
                (visible["pitch_id"].astype(str) == pitch_id)
                & visible["process_element_id"].notna()
            ].drop_duplicates(subset=["process_element_id"], keep="first")
            with line.container(border=True, width=320):
                st.caption("PROCESS AT A GLANCE")
                if process_rows.empty:
                    st.write("No linked process work")
                else:
                    for _, process in process_rows.iterrows():
                        sequence = process.get("process_sequence")
                        sequence_label = (
                            str(int(sequence)) if pd.notna(sequence) else "—"
                        )
                        st.markdown(
                            f"**{sequence_label} · "
                            f"{clean_text(process.get('work_element')) or 'Untitled work element'}**"
                        )
                        description = clean_text(process.get("process_description"))
                        if description:
                            st.write(description)
                        st.caption(
                            f"{seconds_label(process.get('cycle_time_s'))} · "
                            f"{clean_text(process.get('process_status')) or 'No status'}"
                        )
                        process_context = " · ".join(
                            value
                            for value in (
                                clean_text(process.get("location")),
                                clean_text(process.get("tool")),
                            )
                            if value
                        )
                        if process_context:
                            st.caption(process_context)
                st.divider()
                st.subheader(clean_text(pitch.get("pitch_number")) or "Unassigned")
                pitch_name = clean_text(pitch.get("pitch_name"))
                if pitch_name:
                    st.write(pitch_name)
                st.caption(clean_text(pitch.get("pitch_type")) or "Pitch")
                st.badge(
                    clean_text(pitch.get("pitch_status")) or "No status",
                    color=(
                        "green"
                        if clean_text(pitch.get("pitch_status")) == "Active"
                        else "gray"
                    ),
                )

export_columns = [
    "area_name", "pitch_number", "pitch_name", "pitch_type", "pitch_status",
    "process_sequence", "work_element", "process_description", "cycle_time_s",
    "tool", "torque", "quality_requirement", "ergo_requirement", "location",
    "unit_orientation", "model_applicability", "process_status",
]
st.download_button(
    "Export filtered Pin Map data",
    data=dataframe_to_excel(visible.reindex(columns=export_columns), "Pin Map"),
    file_name="pin_map_filtered.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    icon=":material/download:",
)

with st.expander("History", icon=":material/history:"):
    st.caption(
        "Pin Map is a read-only view of Yamazumi and Process at a Glance data; "
        "changes and history remain with those source workflows."
    )
