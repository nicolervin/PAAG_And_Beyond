from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from utils.fishbone_ui import ordered_yamazumi_area_ids, section_breadcrumb_labels
from utils.layout_canvas import layout_image_data_url
from utils.layout_store import from_canonical_inches, get_pitch_layout_footprints
from utils.layout_ui import render_layouts_tab
from utils.scope_ui import page_title_with_scope
from utils.store import (
    assembly_section_walk_order,
    get_planning_scenario,
    pin_map_for_scenario,
)
from utils.table_ui import dataframe_to_excel
from utils.time_units import format_seconds


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


def render_pin_map_tab(project_id: str, scenario_id: str) -> None:
    """Render the line map and 2D spatial view of pitches and reconciled Process work."""
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
        return

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

    view_mode = st.radio(
        "Pin Map Display Mode",
        ["Linear Flow Cards", "2D Plant Spatial Map"],
        horizontal=True,
        key=f"pin_map_view_mode_{scenario_id}",
    )

    if visible_pitches.empty:
        st.info("No pitches match the current filters.", icon=":material/filter_alt_off:")
    elif view_mode == "2D Plant Spatial Map":
        footprints = get_pitch_layout_footprints(project_id, scenario_id)
        if not footprints:
            st.info(
                "No workstations from this scenario have been placed on a 2D floor plan layout yet. "
                "Switch to the **Layouts** tab above to place your workstation footprints to scale on your CAD floor plan.",
                icon=":material/map:",
            )
        else:
            layouts_dict: dict[str, list[dict]] = {}
            for fp in footprints:
                layouts_dict.setdefault(str(fp["layout_id"]), []).append(fp)

            layout_id_options = list(layouts_dict.keys())
            selected_fp_layout_id = layout_id_options[0]
            if len(layout_id_options) > 1:
                selected_fp_layout_id = st.selectbox(
                    "Floor Plan Layout",
                    options=layout_id_options,
                    format_func=lambda lid: f"{layouts_dict[lid][0]['layout_name']} (Rev {layouts_dict[lid][0]['revision_number']})",
                    key=f"pin_map_fp_layout_sel_{scenario_id}",
                )

            layout_fps = layouts_dict[selected_fp_layout_id]
            sample_fp = layout_fps[0]
            layout_name = sample_fp["layout_name"]
            rev_num = sample_fp["revision_number"]
            unit = str(sample_fp["unit"] or "feet")
            px_per_in_x = float(sample_fp.get("scale_px_per_in_x") or sample_fp.get("scale_px_per_in") or 1.0)
            px_per_in_y = float(sample_fp.get("scale_px_per_in_y") or sample_fp.get("scale_px_per_in") or 1.0)
            img_w = int(sample_fp["image_width_px"] or 1200)
            img_h = int(sample_fp["image_height_px"] or 800)
            img_path = Path(str(sample_fp["image_path"]))

            visible_pitch_id_set = set(visible_pitches["pitch_id"].astype(str))
            active_fps = [fp for fp in layout_fps if str(fp["pitch_id"]) in visible_pitch_id_set]

            st.caption(
                f":material/architecture: Layout: **{layout_name}** · Rev {rev_num} · "
                f"{len(active_fps)} workstation(s) positioned to scale on plant floor plan"
            )

            img_url = (
                layout_image_data_url(str(img_path), img_path.stat().st_mtime_ns)
                if img_path.is_file()
                else ""
            )

            svg_boxes = []
            for fp in active_fps:
                fx = float(fp["x"])
                fy = float(fp["y"])
                fw = float(fp["width"])
                fh = float(fp["height"])
                frot = float(fp["rotation"] or 0)
                flabel = str(fp["pitch_number"] or fp["pitch_name"] or "")
                w_unit = from_canonical_inches(fw / px_per_in_x, unit)
                h_unit = from_canonical_inches(fh / px_per_in_y, unit)
                tooltip = f"{fp['pitch_number']} - {fp['pitch_name']} ({w_unit:.1f} × {h_unit:.1f} {unit})"
                color = str(fp["color"] or "#1976d2")
                cx = fx + fw / 2.0
                cy = fy + fh / 2.0
                rot_attr = f' transform="rotate({frot:.1f} {cx:.1f} {cy:.1f})"' if frot else ""

                svg_boxes.append(
                    f'<g{rot_attr}>'
                    f'<rect x="{fx:.1f}" y="{fy:.1f}" width="{fw:.1f}" height="{fh:.1f}" '
                    f'fill="{color}" fill-opacity="0.3" stroke="{color}" stroke-width="2.5" rx="4">'
                    f'<title>{tooltip}</title>'
                    f'</rect>'
                    f'<rect x="{fx + 4:.1f}" y="{fy + 4:.1f}" width="{max(20.0, fw - 8):.1f}" height="20" rx="3" fill="#ffffff" fill-opacity="0.85" />'
                    f'<text x="{fx + fw / 2.0:.1f}" y="{fy + 18:.1f}" text-anchor="middle" font-size="11" font-weight="bold" fill="#000000">'
                    f'{flabel}'
                    f'</text>'
                    f'</g>'
                )

            svg_markup = f"""
            <div style="width: 100%; overflow: auto; border: 1px solid #d0d7de; border-radius: 8px; background: #f6f8fa; padding: 8px;">
              <svg viewBox="0 0 {img_w} {img_h}" style="width: 100%; height: auto; max-height: 700px; display: block;" xmlns="http://www.w3.org/2000/svg">
                <image href="{img_url}" x="0" y="0" width="{img_w}" height="{img_h}" />
                {"".join(svg_boxes)}
              </svg>
            </div>
            """
            st.markdown(svg_markup, unsafe_allow_html=True)

            if active_fps:
                st.caption(
                    "Workstation footprints are placed in real-world scale on your CAD floor plan. "
                    "Hover over any workstation footprint to view pitch details and dimensions."
                )

    else:
        # Linear Flow Cards
        cards_per_row = 3
        pitch_list = visible_pitches.to_dict("records")
        for chunk_start in range(0, len(pitch_list), cards_per_row):
            pitch_chunk = pitch_list[chunk_start : chunk_start + cards_per_row]
            card_columns = st.columns(cards_per_row)
            for col_idx, pitch in enumerate(pitch_chunk):
                with card_columns[col_idx]:
                    with st.container(border=True):
                        st.caption(
                            f"Area: {clean_text(pitch.get('area_name')) or 'Unassigned'}"
                        )
                        pitch_work = visible.loc[
                            visible["pitch_id"] == pitch["pitch_id"]
                        ].dropna(subset=["process_element_id"])
                        if pitch_work.empty:
                            st.write("No linked process steps.")
                        else:
                            for _, process in pitch_work.iterrows():
                                st.markdown(
                                    f"**{clean_text(process.get('process_sequence'))}. "
                                    f"{clean_text(process.get('process_description')) or 'Untitled step'}**"
                                )
                                st.caption(
                                    f"{clean_text(process.get('work_element')) or 'No element'} · "
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
    "shown above each Yamazumi workstation or pitch, and manage 2D plant floor plan layouts."
)
st.caption(
    f"Scenario revision {scenario['revision_label']} · "
    f"{format_seconds(scenario['takt_time_s'], scenario['takt_time_unit'])} takt"
)

tab_pin_map, tab_layouts = st.tabs(["Pin Map", "Layouts"])
with tab_pin_map:
    render_pin_map_tab(project_id, scenario_id)
with tab_layouts:
    render_layouts_tab(
        project_id,
        editor_name=str(st.session_state.get("current_editor") or "").strip() or "Current Editor",
    )
