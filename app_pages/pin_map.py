from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from utils.fishbone_ui import ordered_yamazumi_area_ids, section_breadcrumb_labels
from utils.layout_canvas import layout_image_data_url
from utils.layout_store import (
    from_canonical_inches,
    get_pin_map_readiness_metrics,
    get_pitch_layout_footprints,
    get_scenario_pitch_metrics_for_pin_map,
    to_canonical_inches,
)
from utils.layout_ui import render_layouts_tab
from utils.scope_ui import page_title_with_scope
from utils.store import (
    assembly_section_walk_order,
    audit_history,
    get_planning_scenario,
    pin_map_for_scenario,
)
from utils.table_ui import dataframe_to_excel, selectable_dataframe
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


def render_pin_map_tab(
    project_id: str, scenario_id: str, *, include_history: bool = True
) -> None:
    """Render the line map and 2D spatial view of pitches and reconciled Process work."""
    pin_map = pin_map_for_scenario(project_id, scenario_id)
    if pin_map.empty:
        st.info(
            "Add Yamazumi pitch addresses to this scenario to begin the Pin Map.",
            icon=":material/map:",
        )
        if include_history:
            with st.expander("History", icon=":material/history:"):
                st.caption(
                    "Pin Map is a read-only view of Yamazumi and Process at a Glance data; "
                    "it does not create its own saved history."
                )
        return

    pitch_rows = pin_map.drop_duplicates(subset=["pitch_id"], keep="first").copy()
    controls = st.container(horizontal=True, vertical_alignment="bottom")
    sections = assembly_section_walk_order(project_id)
    section_labels = dict(zip(sections["id"].astype(str), sections["name"].astype(str))) if not sections.empty else {}
    area_rows = (
        pitch_rows[["area_id", "area_name", "section_id"]]
        .drop_duplicates(subset=["area_id"], keep="first")
        .rename(columns={"area_id": "id", "area_name": "name"})
    )
    area_options = ordered_yamazumi_area_ids(
        area_rows,
        sections["id"].astype(str).tolist() if not sections.empty else [],
    )
    area_labels = {
        str(area_row["id"]): str(area_row["name"])
        for _, area_row in area_rows.iterrows()
    }
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
    _vis_ct = pd.to_numeric(linked_work["cycle_time_s"], errors="coerce").fillna(0).sum()
    st.caption(
        f"Filtered view: **{len(visible_pitches):,}** visible pitch{'es' if len(visible_pitches) != 1 else ''} · "
        f"**{len(linked_work):,}** linked Process step{'s' if len(linked_work) != 1 else ''} · "
        f"**{_vis_ct:.1f} s** linked cycle time"
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

            ctrl_cols = st.columns(
                [3, 3, 2.5] if len(layout_id_options) > 1 else [4, 2.5],
                vertical_alignment="bottom",
            )
            if len(layout_id_options) > 1:
                with ctrl_cols[0]:
                    selected_fp_layout_id = st.selectbox(
                        "Floor Plan Layout",
                        options=layout_id_options,
                        format_func=lambda lid: f"{layouts_dict[lid][0]['layout_name']} (Rev {layouts_dict[lid][0]['revision_number']})",
                        key=f"pin_map_fp_layout_sel_{scenario_id}",
                    )
                overlay_col = ctrl_cols[1]
                action_col = ctrl_cols[2]
            else:
                overlay_col = ctrl_cols[0]
                action_col = ctrl_cols[1]

            with overlay_col:
                color_overlay_mode = st.segmented_control(
                    "Color Overlay",
                    options=["Takt Utilization", "Shape Color", "Pitch Status"],
                    default="Takt Utilization",
                    key=f"pin_map_fp_overlay_mode_{scenario_id}",
                ) or "Takt Utilization"

            with action_col:
                if st.button(
                    "Open in Layouts Canvas",
                    icon=":material/edit_square:",
                    key=f"pin_map_open_in_canvas_{selected_fp_layout_id}_{scenario_id}",
                    width="stretch",
                ):
                    st.session_state["active_layout_id"] = selected_fp_layout_id
                    st.session_state["active_revision_id"] = str(
                        layouts_dict[selected_fp_layout_id][0]["revision_id"]
                    )
                    st.session_state[f"pin_map_workspace_mode_{project_id}_{scenario_id}"] = (
                        "2D Plant Layout & Pin Map Canvas"
                    )
                    st.rerun()

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
            pitch_metrics_map = get_scenario_pitch_metrics_for_pin_map(project_id, scenario_id)

            cad_path_str = str(sample_fp.get("cad_file_path") or "").strip()
            cad_name_str = str(sample_fp.get("cad_file_name") or "").strip()
            cad_size_int = int(sample_fp.get("cad_file_size_bytes") or 0)
            cad_url_str = str(sample_fp.get("cad_web_url") or "").strip()
            cad_p = Path(cad_path_str) if cad_path_str else None
            has_cad_file = bool(cad_p and cad_p.is_file())
            has_cad_url = bool(cad_url_str)

            col_caption, col_dl, col_link = st.columns([5, 2, 2], vertical_alignment="center")
            with col_caption:
                st.caption(
                    f":material/architecture: Layout: **{layout_name}** · Rev {rev_num} · "
                    f"{len(active_fps)} workstation(s) positioned to scale on plant floor plan"
                )
            with col_dl:
                if has_cad_file:
                    try:
                        size_mb = cad_size_int / (1024 * 1024)
                        btn_txt = f"Download AutoCAD ({cad_name_str})" if size_mb < 0.1 else f"Download AutoCAD ({cad_name_str} · {size_mb:.1f} MB)"
                        st.download_button(
                            btn_txt,
                            data=cad_p.read_bytes,
                            file_name=cad_name_str,
                            mime="application/octet-stream",
                            icon=":material/download:",
                            key=f"pin_map_dl_cad_{selected_fp_layout_id}_{scenario_id}",
                            width="stretch",
                        )
                    except Exception:
                        pass
            with col_link:
                if has_cad_url:
                    st.link_button(
                        "Open CAD in Vault / Web",
                        url=cad_url_str,
                        icon=":material/open_in_new:",
                        width="stretch",
                    )

            notes_lower = str(sample_fp.get("revision_notes") or "").lower()
            img_path_str = str(sample_fp["image_path"] or "")
            is_blank_canvas = (
                "blank scaled" in notes_lower
                or "blank_scaled_canvas" in img_path_str.lower()
            )
            img_url = (
                layout_image_data_url(str(img_path), img_path.stat().st_mtime_ns)
                if (img_path.is_file() and not is_blank_canvas)
                else ""
            )

            import html as _html

            unit_in = to_canonical_inches(1.0, unit)
            minor_grid_x = max(8.0, unit_in * px_per_in_x)
            minor_grid_y = max(8.0, unit_in * px_per_in_y)
            major_grid_x = minor_grid_x * 5.0
            major_grid_y = minor_grid_y * 5.0

            svg_boxes = []
            for fp in active_fps:
                fx = float(fp["x"])
                fy = float(fp["y"])
                fw = float(fp["width"])
                fh = float(fp["height"])
                frot = float(fp["rotation"] or 0)
                stype = str(fp.get("shape_type") or "rectangle").strip().lower()
                pid_str = str(fp["pitch_id"])
                pm = pitch_metrics_map.get(pid_str, {})

                raw_style = fp.get("style_json")
                style_dict: dict = {}
                if isinstance(raw_style, dict):
                    style_dict = raw_style
                elif isinstance(raw_style, str) and raw_style.strip():
                    try:
                        parsed_s = json.loads(raw_style)
                        if isinstance(parsed_s, dict):
                            style_dict = parsed_s
                    except Exception:
                        style_dict = {}

                base_color = str(style_dict.get("fill_color") or fp.get("color") or "#1976d2")
                base_stroke = str(style_dict.get("stroke_color") or fp.get("color") or "#1976d2")

                util_pct = pm.get("utilization_pct")
                ct_sec = float(pm.get("cycle_time_sec") or 0.0)
                takt_sec = pm.get("target_takt_sec") or pm.get("takt_time_sec")
                op_cnt = int(pm.get("operator_count") or 0)
                steps_list = pm.get("steps") or []
                pitch_status = str(fp.get("pitch_status") or pm.get("pitch_status") or "Active")

                if color_overlay_mode == "Takt Utilization" and util_pct is not None:
                    u_val = float(util_pct)
                    if u_val > 100.0:
                        fill_col, stroke_col = "#fecaca", "#dc2626"
                    elif u_val >= 85.0:
                        fill_col, stroke_col = "#bbf7d0", "#16a34a"
                    else:
                        fill_col, stroke_col = "#fef08a", "#ca8a04"
                elif color_overlay_mode == "Pitch Status":
                    st_lower = pitch_status.lower()
                    if st_lower == "blocked":
                        fill_col, stroke_col = "#fecaca", "#dc2626"
                    elif st_lower == "open":
                        fill_col, stroke_col = "#e2e8f0", "#64748b"
                    else:
                        fill_col, stroke_col = "#bfdbfe", "#2563eb"
                else:
                    fill_col, stroke_col = base_color, base_stroke

                fill_col_esc = _html.escape(fill_col, quote=True)
                stroke_col_esc = _html.escape(stroke_col, quote=True)

                flabel = _html.escape(
                    str(fp.get("label") or fp["pitch_number"] or fp["pitch_name"] or "")
                )
                w_unit = from_canonical_inches(fw / px_per_in_x, unit)
                h_unit = from_canonical_inches(fh / px_per_in_y, unit)

                takt_str = (
                    f"{ct_sec:.1f}s / {float(takt_sec):.1f}s ({float(util_pct):.0f}%)"
                    if takt_sec and util_pct is not None
                    else f"{ct_sec:.1f}s CT"
                )
                step_preview = ", ".join(
                    f"{s.get('operation') or s.get('step_code') or ''} {s.get('description') or s.get('title') or ''}".strip()
                    for s in steps_list[:4]
                )
                if len(steps_list) > 4:
                    step_preview += f" (+{len(steps_list) - 4} more)"

                tooltip_lines = [
                    f"{fp['pitch_number']} - {fp['pitch_name']} ({w_unit:.1f} × {h_unit:.1f} {unit})",
                    f"Status: {pitch_status} · Footprint: {stype}",
                    f"Cycle / Takt: {takt_str} · Operators: {op_cnt}",
                ]
                if step_preview:
                    tooltip_lines.append(f"PAAG Steps ({len(steps_list)}): {step_preview}")
                tooltip = _html.escape(" | ".join(tooltip_lines))

                cx = fx + fw / 2.0
                cy = fy + fh / 2.0
                rot_attr = f' transform="rotate({frot:.1f} {cx:.1f} {cy:.1f})"' if frot else ""

                if stype in ("circle", "oval"):
                    geom_svg = (
                        f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{fw / 2.0:.1f}" ry="{fh / 2.0:.1f}" '
                        f'fill="{fill_col_esc}" fill-opacity="0.42" stroke="{stroke_col_esc}" stroke-width="2.5">'
                        f"<title>{tooltip}</title></ellipse>"
                    )
                elif stype == "diamond":
                    pts_str = f"{cx:.1f},{fy:.1f} {fx + fw:.1f},{cy:.1f} {cx:.1f},{fy + fh:.1f} {fx:.1f},{cy:.1f}"
                    geom_svg = (
                        f'<polygon points="{pts_str}" '
                        f'fill="{fill_col_esc}" fill-opacity="0.42" stroke="{stroke_col_esc}" stroke-width="2.5">'
                        f"<title>{tooltip}</title></polygon>"
                    )
                elif stype == "l_shape":
                    pts_str = (
                        f"{fx:.1f},{fy:.1f} {fx + fw * 0.42:.1f},{fy:.1f} "
                        f"{fx + fw * 0.42:.1f},{fy + fh * 0.58:.1f} {fx + fw:.1f},{fy + fh * 0.58:.1f} "
                        f"{fx + fw:.1f},{fy + fh:.1f} {fx:.1f},{fy + fh:.1f}"
                    )
                    geom_svg = (
                        f'<polygon points="{pts_str}" '
                        f'fill="{fill_col_esc}" fill-opacity="0.42" stroke="{stroke_col_esc}" stroke-width="2.5">'
                        f"<title>{tooltip}</title></polygon>"
                    )
                elif stype == "t_shape":
                    pts_str = (
                        f"{fx:.1f},{fy:.1f} {fx + fw:.1f},{fy:.1f} "
                        f"{fx + fw:.1f},{fy + fh * 0.36:.1f} {fx + fw * 0.68:.1f},{fy + fh * 0.36:.1f} "
                        f"{fx + fw * 0.68:.1f},{fy + fh:.1f} {fx + fw * 0.32:.1f},{fy + fh:.1f} "
                        f"{fx + fw * 0.32:.1f},{fy + fh * 0.36:.1f} {fx:.1f},{fy + fh * 0.36:.1f}"
                    )
                    geom_svg = (
                        f'<polygon points="{pts_str}" '
                        f'fill="{fill_col_esc}" fill-opacity="0.42" stroke="{stroke_col_esc}" stroke-width="2.5">'
                        f"<title>{tooltip}</title></polygon>"
                    )
                elif stype == "u_shape":
                    pts_str = (
                        f"{fx:.1f},{fy:.1f} {fx + fw * 0.28:.1f},{fy:.1f} "
                        f"{fx + fw * 0.28:.1f},{fy + fh * 0.62:.1f} {fx + fw * 0.72:.1f},{fy + fh * 0.62:.1f} "
                        f"{fx + fw * 0.72:.1f},{fy:.1f} {fx + fw:.1f},{fy:.1f} "
                        f"{fx + fw:.1f},{fy + fh:.1f} {fx:.1f},{fy + fh:.1f}"
                    )
                    geom_svg = (
                        f'<polygon points="{pts_str}" '
                        f'fill="{fill_col_esc}" fill-opacity="0.42" stroke="{stroke_col_esc}" stroke-width="2.5">'
                        f"<title>{tooltip}</title></polygon>"
                    )
                elif stype == "custom_polygon" and isinstance(style_dict.get("points"), list) and len(style_dict["points"]) >= 3:
                    poly_pts = []
                    for pt in style_dict["points"]:
                        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                            px_val = fx + float(pt[0]) * fw
                            py_val = fy + float(pt[1]) * fh
                            poly_pts.append(f"{px_val:.1f},{py_val:.1f}")
                    if len(poly_pts) >= 3:
                        pts_str = " ".join(poly_pts)
                        geom_svg = (
                            f'<polygon points="{pts_str}" '
                            f'fill="{fill_col_esc}" fill-opacity="0.42" stroke="{stroke_col_esc}" stroke-width="2.5">'
                            f"<title>{tooltip}</title></polygon>"
                        )
                    else:
                        geom_svg = (
                            f'<rect x="{fx:.1f}" y="{fy:.1f}" width="{fw:.1f}" height="{fh:.1f}" '
                            f'fill="{fill_col_esc}" fill-opacity="0.42" stroke="{stroke_col_esc}" stroke-width="2.5" rx="4">'
                            f"<title>{tooltip}</title></rect>"
                        )
                else:
                    geom_svg = (
                        f'<rect x="{fx:.1f}" y="{fy:.1f}" width="{fw:.1f}" height="{fh:.1f}" '
                        f'fill="{fill_col_esc}" fill-opacity="0.42" stroke="{stroke_col_esc}" stroke-width="2.5" rx="4">'
                        f"<title>{tooltip}</title></rect>"
                    )

                badge_svg = ""
                if fh >= 42 and fw >= 44:
                    sub_txt = (
                        f"{float(util_pct):.0f}% · {op_cnt} op"
                        if util_pct is not None
                        else f"{ct_sec:.0f}s · {op_cnt} op"
                    )
                    sub_esc = _html.escape(sub_txt)
                    badge_svg = (
                        f'<text x="{cx:.1f}" y="{fy + 33:.1f}" text-anchor="middle" '
                        f'font-size="9.5" font-weight="600" fill="#1e293b">{sub_esc}</text>'
                    )

                svg_boxes.append(
                    f'<g{rot_attr}>'
                    f'{geom_svg}'
                    f'<rect x="{fx + 4:.1f}" y="{fy + 4:.1f}" width="{max(20.0, fw - 8):.1f}" height="20" rx="3" fill="#ffffff" fill-opacity="0.88" />'
                    f'<text x="{cx:.1f}" y="{fy + 18:.1f}" text-anchor="middle" font-size="11" font-weight="bold" fill="#0f172a">'
                    f'{flabel}'
                    f'</text>'
                    f'{badge_svg}'
                    f'</g>'
                )

            bg_image_svg = (
                f'<image href="{img_url}" x="0" y="0" width="{img_w}" height="{img_h}" />'
                if img_url
                else f'<rect x="0" y="0" width="{img_w}" height="{img_h}" fill="#ffffff" />'
            )

            svg_markup = f"""
            <div style="width: 100%; overflow: auto; border: 1px solid #d0d7de; border-radius: 8px; background: #f6f8fa; padding: 8px;">
              <svg viewBox="0 0 {img_w} {img_h}" style="width: 100%; height: auto; max-height: 700px; display: block;" xmlns="http://www.w3.org/2000/svg">
                <defs>
                  <pattern id="paagMinorGrid" width="{minor_grid_x:.2f}" height="{minor_grid_y:.2f}" patternUnits="userSpaceOnUse">
                    <path d="M {minor_grid_x:.2f} 0 L 0 0 0 {minor_grid_y:.2f}" fill="none" stroke="#94a3b8" stroke-width="0.5" stroke-opacity="0.35" />
                  </pattern>
                  <pattern id="paagMajorGrid" width="{major_grid_x:.2f}" height="{major_grid_y:.2f}" patternUnits="userSpaceOnUse">
                    <rect width="{major_grid_x:.2f}" height="{major_grid_y:.2f}" fill="url(#paagMinorGrid)" />
                    <path d="M {major_grid_x:.2f} 0 L 0 0 0 {major_grid_y:.2f}" fill="none" stroke="#64748b" stroke-width="1" stroke-opacity="0.45" />
                  </pattern>
                </defs>
                {bg_image_svg}
                <rect x="0" y="0" width="{img_w}" height="{img_h}" fill="url(#paagMajorGrid)" />
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
        data=lambda: dataframe_to_excel(visible.reindex(columns=export_columns), "Pin Map"),
        file_name="pin_map_filtered.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
    )

    if include_history:
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

editor_name = str(st.session_state.get("current_editor") or "").strip() or "Current Editor"

_pm_readiness = get_pin_map_readiness_metrics(project_id, scenario_id)
_tot_act_pitches = int(_pm_readiness["total_active_pitches"])
_placed_pitches = int(_pm_readiness["placed_active_pitches"])
_placed_layouts = int(_pm_readiness["placed_layouts_count"])
if _tot_act_pitches == 0:
    _fp_val = "🟢 0 / 0"
    _fp_delta = "No active pitches yet"
    _fp_dcol = "off"
else:
    _fp_pct = round(_placed_pitches / _tot_act_pitches * 100)
    _unplaced = max(_tot_act_pitches - _placed_pitches, 0)
    if _unplaced == 0:
        _fp_val = f"🟢 100% ({_placed_pitches:,}/{_tot_act_pitches:,})"
        _fp_delta = f"All placed across {max(1, _placed_layouts):,} layout{'s' if _placed_layouts != 1 else ''}"
        _fp_dcol = "normal"
    else:
        _fp_icon = "🟡" if _fp_pct >= 50 else "🔴"
        _fp_val = f"{_fp_icon} {_fp_pct}% ({_placed_pitches:,}/{_tot_act_pitches:,})"
        _fp_delta = f"{_unplaced:,} pitch{'es' if _unplaced != 1 else ''} not yet placed on floor plan"
        _fp_dcol = "inverse"

_work_pitches = int(_pm_readiness["pitches_with_work"])
_linked_steps = int(_pm_readiness["linked_steps_count"])
_linked_ct = float(_pm_readiness["linked_cycle_time_s"])
if _tot_act_pitches == 0:
    _lnk_val = "🟢 0 / 0"
    _lnk_delta = "No active pitches yet"
    _lnk_dcol = "off"
else:
    _lnk_pct = round(_work_pitches / _tot_act_pitches * 100)
    _missing_work = max(_tot_act_pitches - _work_pitches, 0)
    if _missing_work == 0:
        _lnk_val = f"🟢 100% ({_work_pitches:,}/{_tot_act_pitches:,})"
        _lnk_delta = f"{_linked_steps:,} steps · {_linked_ct:.1f} s total"
        _lnk_dcol = "normal"
    else:
        _lnk_icon = "🟡" if _lnk_pct >= 50 else "🔴"
        _lnk_val = f"{_lnk_icon} {_lnk_pct}% ({_work_pitches:,}/{_tot_act_pitches:,})"
        _lnk_delta = f"{_missing_work:,} missing work · {_linked_steps:,} steps ({_linked_ct:.1f} s)"
        _lnk_dcol = "inverse"

_hotspots = int(_pm_readiness["hotspots_count"])
_over_takt = int(_pm_readiness["over_takt_count"])
_blocked = int(_pm_readiness["blocked_count"])
_under_85 = int(_pm_readiness["under_85_count"])
_tot_pitches_all = int(_pm_readiness["total_pitches"])
if _tot_pitches_all == 0:
    _hot_val = "🟢 0"
    _hot_delta = "0 over takt · 0 blocked · 0 under 85%"
    _hot_dcol = "off"
elif _hotspots == 0 and _under_85 == 0:
    _hot_val = "🟢 0"
    _hot_delta = "All active pitches within 85–100% takt"
    _hot_dcol = "normal"
elif _hotspots == 0:
    _hot_val = f"🟡 0 ({_under_85:,} <85%)"
    _hot_delta = f"0 over takt · 0 blocked · {_under_85:,} under 85% util"
    _hot_dcol = "off"
else:
    _hot_val = f"🔴 {_hotspots:,}"
    _hot_delta = f"{_over_takt:,} over takt (>100%) · {_blocked:,} blocked · {_under_85:,} <85%"
    _hot_dcol = "inverse"

_tot_layouts = int(_pm_readiness["total_layouts"])
_cal_layouts = int(_pm_readiness["calibrated_layouts"])
_cad_layouts = int(_pm_readiness["cad_or_bg_layouts"])
_tot_shapes = int(_pm_readiness["total_shapes"])
if _tot_layouts == 0:
    _cal_val = "🟡 0"
    _cal_delta = "Open Canvas to initialize floor plan"
    _cal_dcol = "off"
elif _cal_layouts == _tot_layouts:
    _cal_val = f"🟢 {_tot_layouts:,} (100% scaled)"
    _cal_delta = f"{_tot_shapes:,} shape{'s' if _tot_shapes != 1 else ''} · {_cad_layouts:,} with floorplan/CAD"
    _cal_dcol = "normal" if _tot_shapes > 0 else "off"
else:
    _uncal = max(_tot_layouts - _cal_layouts, 0)
    _cal_val = f"🟡 {_cal_layouts:,}/{_tot_layouts:,} scaled"
    _cal_delta = f"{_uncal:,} missing scale · {_tot_shapes:,} shape{'s' if _tot_shapes != 1 else ''}"
    _cal_dcol = "inverse"

_callout_pitches = int(_pm_readiness["callout_pitches_count"])
_te_cnt = int(_pm_readiness["tool_eq_pitches_count"])
_qu_cnt = int(_pm_readiness["qual_pitches_count"])
_er_cnt = int(_pm_readiness["ergo_pitches_count"])
_sa_cnt = int(_pm_readiness["safety_pitches_count"])
_callout_breakdown = f"{_te_cnt:,} Tool/Eq · {_qu_cnt:,} Qual · {_er_cnt:,} Ergo · {_sa_cnt:,} Safety"
if _tot_act_pitches == 0:
    _co_val = "🟢 0 / 0"
    _co_delta = _callout_breakdown
    _co_dcol = "off"
else:
    _co_pct = round(_callout_pitches / _tot_act_pitches * 100)
    _co_icon = "🟢" if _callout_pitches > 0 else "🟡"
    _co_val = f"{_co_icon} {_co_pct}% ({_callout_pitches:,}/{_tot_act_pitches:,})"
    _co_delta = _callout_breakdown
    _co_dcol = "normal" if _callout_pitches == _tot_act_pitches else "off"

_pmc1, _pmc2, _pmc3, _pmc4, _pmc5 = st.columns(5)
_pmc1.metric(
    "2D layout footprint coverage",
    _fp_val,
    delta=_fp_delta,
    delta_color=_fp_dcol,
    help=(
        "Share of active Yamazumi pitches in this scenario that have been placed as "
        "workstation footprints on a 2D plant floor plan layout."
    ),
)
_pmc2.metric(
    "Process linkage on Pin Map",
    _lnk_val,
    delta=_lnk_delta,
    delta_color=_lnk_dcol,
    help=(
        "Share of active pitches with linked Process at a Glance work elements on the Pin Map, "
        "plus total linked steps and cycle time."
    ),
)
_pmc3.metric(
    "Spatial takt & status hotspots",
    _hot_val,
    delta=_hot_delta,
    delta_color=_hot_dcol,
    help=(
        "Flags pitches exceeding target takt time (>100% utilization) or marked Blocked, "
        "plus active pitches running below 85% takt utilization."
    ),
)
_pmc4.metric(
    "Floor plan calibration & CAD",
    _cal_val,
    delta=_cal_delta,
    delta_color=_cal_dcol,
    help=(
        "Tracks project 2D floor plan layouts, real-world dimension scale calibration, "
        "total placed canvas shapes, and floorplan/CAD attachments."
    ),
)
_pmc5.metric(
    "Functional & tool callouts",
    _co_val,
    delta=_co_delta,
    delta_color=_co_dcol,
    help=(
        "Active pitches carrying Tool/Equipment, Quality/Torque, Ergonomics, or Safety "
        "callouts on the Pin Map."
    ),
)

pin_map_workspace_mode = st.radio(
    "Pin Map view",
    options=["2D Plant Layout & Pin Map Canvas", "Pin Map Matrix, Linear Flow & Excel Export"],
    horizontal=True,
    label_visibility="collapsed",
    key=f"pin_map_workspace_mode_{project_id}_{scenario_id}",
)

if pin_map_workspace_mode == "Pin Map Matrix, Linear Flow & Excel Export":
    render_pin_map_tab(project_id, scenario_id, include_history=False)
else:
    render_layouts_tab(
        project_id,
        editor_name=editor_name,
        scenario_id=scenario_id,
        embedded_in_pin_map=True,
    )

with st.expander("History", icon=":material/history:"):
    st.caption(
        "Pin Map layout canvas, layer, and scale calibration changes are logged below. "
        "Underlying Yamazumi and Process at a Glance work history remains with those source workflows."
    )
    history_df = audit_history(project_id, table_name="Layouts", limit=50)
    if history_df.empty:
        st.caption("No layout or Pin Map canvas history recorded yet.")
    else:
        selectable_dataframe(
            history_df.drop(columns=["details"], errors="ignore"),
            key=f"pin_map_layout_audit_history_{project_id}",
            hide_index=True,
            column_config={
                "action": "Action",
                "row_count": "Count",
                "editor_name": "Editor",
                "created_at": st.column_config.DatetimeColumn(
                    "When", format="MMM DD, YYYY HH:mm", timezone="America/New_York"
                ),
            },
        )



