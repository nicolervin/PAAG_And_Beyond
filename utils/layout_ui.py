"""User interface for 2D plant floor plan layouts, image calibration, revision history,
and interactive shape annotations to scale.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import streamlit as st

from utils.layout_canvas import layout_canvas, layout_image_data_url
from utils.layout_store import (
    LAYOUT_UNITS,
    UNIT_TO_INCHES,
    create_layout,
    create_layout_revision,
    delete_layout,
    delete_layout_revision,
    format_dimension,
    from_canonical_inches,
    get_layout,
    get_layout_revision,
    get_section_pitch_standards,
    layout_deletion_impact,
    list_layout_revisions,
    list_layout_shapes,
    list_layouts,
    list_project_yamazumi_pitches,
    save_layout_shapes,
    set_section_pitch_standard,
    to_canonical_inches,
    update_layout,
    update_layout_revision_scale,
)
from utils.scope_ui import section_heading_with_scope
from utils.store import assembly_sections, audit_history
from utils.table_ui import editable_table_footer, selectable_dataframe

SHAPE_TYPES: list[str] = [
    "rectangle",
    "circle",
    "oval",
    "triangle",
    "hexagon",
    "arrow",
    "text",
]

SHAPE_TYPE_LABELS: dict[str, str] = {
    "rectangle": "Rectangle / Cell",
    "circle": "Circle",
    "oval": "Oval / Ellipse",
    "triangle": "Triangle",
    "hexagon": "Hexagon",
    "arrow": "Arrow / Flow Direction",
    "text": "Text Box / Note",
}

SHAPE_TYPE_ICONS: dict[str, str] = {
    "rectangle": "⏹️",
    "circle": "⏺️",
    "oval": "🥚",
    "triangle": "🔺",
    "hexagon": "⬡",
    "arrow": "➡️",
    "text": "📝",
}

LINE_THICKNESS_OPTIONS: list[int] = [1, 2, 3, 4, 6, 8]
LINE_STYLE_OPTIONS: list[str] = ["solid", "dashed", "dotted"]
FONT_SIZE_OPTIONS: list[int] = [10, 12, 14, 16, 18, 20, 24, 28, 36]

FOOTPRINT_PRESETS: dict[str, dict[str, Any]] = {
    "Workstation Pitch": {
        "shape_type": "rectangle",
        "label": "Workstation",
        "w_default": 12.0,
        "h_default": 8.0,
        "stroke_color": "#1976D2",
        "stroke_width": 2,
        "stroke_style": "solid",
        "fill_color": "#1976D2",
        "fill_opacity": 0.25,
        "font_size": 14,
        "font_color": "#1a1a1a",
        "font_weight": "bold",
        "bg_pill": True,
    },
    "Machine / Equipment": {
        "shape_type": "rectangle",
        "label": "CNC / Machine",
        "w_default": 15.0,
        "h_default": 10.0,
        "stroke_color": "#263238",
        "stroke_width": 3,
        "stroke_style": "solid",
        "fill_color": "#263238",
        "fill_opacity": 0.35,
        "font_size": 14,
        "font_color": "#1a1a1a",
        "font_weight": "bold",
        "bg_pill": True,
    },
    "Conveyor Segment": {
        "shape_type": "rectangle",
        "label": "Conveyor",
        "w_default": 24.0,
        "h_default": 3.5,
        "stroke_color": "#607D8B",
        "stroke_width": 3,
        "stroke_style": "dashed",
        "fill_color": "#607D8B",
        "fill_opacity": 0.25,
        "font_size": 12,
        "font_color": "#1a1a1a",
        "font_weight": "normal",
        "bg_pill": False,
    },
    "Material Storage / Rack": {
        "shape_type": "rectangle",
        "label": "Storage Rack",
        "w_default": 10.0,
        "h_default": 5.0,
        "stroke_color": "#F57C00",
        "stroke_width": 2,
        "stroke_style": "solid",
        "fill_color": "#F57C00",
        "fill_opacity": 0.30,
        "font_size": 12,
        "font_color": "#1a1a1a",
        "font_weight": "bold",
        "bg_pill": True,
    },
    "Safety Clearance / Buffer": {
        "shape_type": "rectangle",
        "label": "Aisle Clearance",
        "w_default": 12.0,
        "h_default": 4.0,
        "stroke_color": "#FBC02D",
        "stroke_width": 3,
        "stroke_style": "dashed",
        "fill_color": "#FBC02D",
        "fill_opacity": 0.20,
        "font_size": 12,
        "font_color": "#1a1a1a",
        "font_weight": "normal",
        "bg_pill": False,
    },
    "Quality Gate / Audit": {
        "shape_type": "rectangle",
        "label": "Quality Audit",
        "w_default": 8.0,
        "h_default": 6.0,
        "stroke_color": "#388E3C",
        "stroke_width": 2,
        "stroke_style": "solid",
        "fill_color": "#388E3C",
        "fill_opacity": 0.25,
        "font_size": 14,
        "font_color": "#1a1a1a",
        "font_weight": "bold",
        "bg_pill": True,
    },
    "Flow Arrow": {
        "shape_type": "arrow",
        "label": "",
        "w_default": 16.0,
        "h_default": 4.0,
        "stroke_color": "#1976D2",
        "stroke_width": 4,
        "stroke_style": "solid",
        "fill_color": "#1976D2",
        "fill_opacity": 1.0,
        "font_size": 12,
        "font_color": "#1a1a1a",
        "font_weight": "normal",
        "bg_pill": False,
    },
    "Text Note": {
        "shape_type": "text",
        "label": "Area Note",
        "w_default": 15.0,
        "h_default": 4.0,
        "stroke_color": "#1976D2",
        "stroke_width": 1,
        "stroke_style": "solid",
        "fill_color": "#ffffff",
        "fill_opacity": 0.90,
        "font_size": 16,
        "font_color": "#1a1a1a",
        "font_weight": "bold",
        "bg_pill": True,
    },
    "Custom Shape": {
        "shape_type": "rectangle",
        "label": "Annotation",
        "w_default": 10.0,
        "h_default": 8.0,
        "stroke_color": "#1976D2",
        "stroke_width": 2,
        "stroke_style": "solid",
        "fill_color": "#1976D2",
        "fill_opacity": 0.25,
        "font_size": 14,
        "font_color": "#1a1a1a",
        "font_weight": "normal",
        "bg_pill": False,
    },
}


def _px_to_units(px: float, px_per_in: float, unit: str) -> float:
    """Convert pixel dimension to real-world units based on scale."""
    if px_per_in <= 0:
        return 0.0
    inches = px / px_per_in
    unit_factor = (
        12.0
        if unit == "feet"
        else (36.0 if unit == "yards" else (63360.0 if unit == "miles" else 1.0))
    )
    return inches / unit_factor


def _units_to_px(val: float, px_per_in: float, unit: str) -> float:
    """Convert real-world unit value to pixel dimension."""
    unit_factor = (
        12.0
        if unit == "feet"
        else (36.0 if unit == "yards" else (63360.0 if unit == "miles" else 1.0))
    )
    inches = val * unit_factor
    return inches * px_per_in


def _calculate_shape_area(shape_type: str, w_units: float, h_units: float) -> float:
    """Calculate geometric area in square units."""
    stype = (shape_type or "").lower()
    if stype == "circle":
        r = min(w_units, h_units) / 2.0
        return math.pi * r * r
    elif stype == "oval":
        return math.pi * (w_units / 2.0) * (h_units / 2.0)
    elif stype == "triangle":
        return (w_units * h_units) / 2.0
    elif stype == "hexagon":
        r = min(w_units, h_units) / 2.0
        return (3.0 * math.sqrt(3.0) / 2.0) * r * r
    elif stype in {"rectangle", "text"}:
        return w_units * h_units
    return 0.0


def _format_shape_dim(px: float, px_per_in: float, unit: str) -> str:
    """Format dimension to 1-2 decimal places."""
    val = _px_to_units(px, px_per_in, unit)
    return f"{val:.1f} {unit}" if val >= 10 else f"{val:.2f} {unit}"


@st.dialog("Create new floor plan layout", width="medium")
def _create_layout_dialog(project_id: str, editor_name: str) -> None:
    st.write("Add a new named 2D plant floor plan layout for this project.")
    name = st.text_input(
        "Layout name",
        placeholder="e.g., Main Assembly Line, Building 2 Mezzanine",
        key="new_layout_name",
    )
    description = st.text_area(
        "Description (optional)",
        placeholder="Brief context about this floor plan layout...",
        key="new_layout_desc",
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Cancel", width="stretch", key="cancel_new_layout"):
            st.rerun()
    with col2:
        if st.button(
            "Create layout", type="primary", width="stretch", key="submit_new_layout"
        ):
            if not name.strip():
                st.error("Please enter a layout name.")
                return
            if not editor_name.strip():
                st.error("Please specify a Current editor attribution.")
                return
            try:
                created = create_layout(project_id, name, description, editor_name)
                st.session_state["active_layout_id"] = created["id"]
                st.toast(f"Created layout '{name}'", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


@st.dialog("Add new layout revision", width="large")
def _create_revision_dialog(
    project_id: str,
    layout: dict[str, Any],
    latest_rev: dict[str, Any] | None,
    editor_name: str,
) -> None:
    st.write(
        f"Upload or paste an updated drawing revision for **{layout['name']}**."
    )
    st.caption(
        "The calibrated scale will determine footprint dimensions and pitch scaling."
    )

    input_mode = st.radio(
        "Image source",
        ["Upload image file", "Paste screenshot from clipboard"],
        horizontal=True,
        key="rev_image_source_mode",
    )

    image_file = None
    if input_mode == "Upload image file":
        image_file = st.file_uploader(
            "Upload floor plan image (PNG, JPG, WEBP)",
            type=["png", "jpg", "jpeg", "webp"],
            key="rev_file_upload",
        )
    else:
        st.caption(
            "Click inside the paste box below and press **Ctrl+V** (or Cmd+V) to paste a screenshot."
        )
        try:
            from utils.clipboard_image import clipboard_image

            paste_result = clipboard_image(
                key="rev_clipboard_paste",
                button_label="Paste image from clipboard",
            )
            if paste_result and getattr(paste_result, "image", None):
                image_file = paste_result.image
                st.success("Screenshot captured from clipboard!")
        except Exception:
            st.info(
                "Clipboard paste component unavailable; please use Upload image file instead."
            )

    st.markdown("##### Calibrate Physical Scale")
    st.caption(
        "Specify the real-world distance represented by the entire width and height of this drawing."
    )

    default_unit = latest_rev["unit"] if latest_rev else "feet"
    default_w = float(latest_rev["width_value"]) if latest_rev else 100.0
    default_h = float(latest_rev["height_value"]) if latest_rev else 50.0

    unit_idx = (
        LAYOUT_UNITS.index(default_unit) if default_unit in LAYOUT_UNITS else 0
    )

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        width_val = st.number_input(
            "Physical Width",
            min_value=0.01,
            value=default_w,
            step=1.0,
            format="%.2f",
            key="rev_scale_w",
        )
    with c2:
        height_val = st.number_input(
            "Physical Height",
            min_value=0.01,
            value=default_h,
            step=1.0,
            format="%.2f",
            key="rev_scale_h",
        )
    with c3:
        unit = st.selectbox(
            "Scale Unit",
            LAYOUT_UNITS,
            index=unit_idx,
            key="rev_scale_unit",
        )

    copy_shapes = False
    if latest_rev:
        copy_shapes = st.checkbox(
            f"Copy forward shapes from Rev {latest_rev['revision_number']} (retains prior equipment / pitch annotations for easy adjustment)",
            value=True,
            key="rev_copy_shapes",
        )

    notes = st.text_input(
        "Revision notes / CAD version (optional)",
        placeholder="e.g., Updated line layout from CAD team 2026-09",
        key="rev_notes",
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Cancel", width="stretch", key="cancel_new_rev"):
            st.rerun()
    with col2:
        if st.button(
            "Save revision",
            type="primary",
            width="stretch",
            key="submit_new_rev",
        ):
            if not image_file:
                st.error("Please provide an image by upload or paste.")
                return
            if not editor_name.strip():
                st.error("Please specify a Current editor attribution.")
                return
            try:
                copy_rev_id = str(latest_rev["id"]) if (latest_rev and copy_shapes) else None
                new_rev = create_layout_revision(
                    project_id=project_id,
                    layout_id=str(layout["id"]),
                    image_file=image_file,
                    width_value=width_val,
                    height_value=height_val,
                    unit=unit,
                    notes=notes,
                    editor_name=editor_name,
                    copy_from_revision_id=copy_rev_id,
                )
                st.session_state["active_revision_id"] = new_rev["id"]
                st.toast(
                    f"Created Revision {new_rev['revision_number']} for '{layout['name']}'",
                    icon=":material/check_circle:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


@st.dialog("Confirm delete layout", width="medium")
def _delete_layout_dialog(
    project_id: str, layout: dict[str, Any], editor_name: str
) -> None:
    impact = layout_deletion_impact(project_id, str(layout["id"]))
    st.write(
        f"Are you sure you want to permanently delete **{layout['name']}**?"
    )
    st.error(
        f"**Deletion Impact:**\n"
        f"- **{impact['revisions_count']}** revision(s) will be deleted\n"
        f"- **{impact['shapes_count']}** annotation shape(s) will be deleted\n"
        f"- **{impact['images_count']}** uploaded drawing image(s) will be permanently purged"
    )
    st.caption("This action is immediate and cannot be undone.")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Cancel", width="stretch", key="cancel_del_layout"):
            st.rerun()
    with col2:
        if st.button(
            "Permanently delete layout",
            type="primary",
            width="stretch",
            key=f"destructive_confirm_del_layout_{layout['id']}",
        ):
            if not editor_name.strip():
                st.error("Current editor attribution required.")
                return
            try:
                delete_layout(project_id, str(layout["id"]), editor_name)
                st.session_state.pop("active_layout_id", None)
                st.session_state.pop("active_revision_id", None)
                st.toast(
                    f"Deleted layout '{layout['name']}'",
                    icon=":material/delete_forever:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


@st.dialog("Confirm delete revision", width="medium")
def _delete_revision_dialog(
    project_id: str,
    layout_name: str,
    revision: dict[str, Any],
    editor_name: str,
) -> None:
    st.write(
        f"Delete **Revision {revision['revision_number']}** of **{layout_name}**?"
    )
    st.warning(
        f"This revision has **{revision['shape_count']}** shape annotation(s). "
        f"Deleting it will remove this revision and delete its uploaded drawing file."
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Cancel", width="stretch", key="cancel_del_rev"):
            st.rerun()
    with col2:
        if st.button(
            "Delete revision",
            type="primary",
            width="stretch",
            key=f"destructive_confirm_del_rev_{revision['id']}",
        ):
            if not editor_name.strip():
                st.error("Current editor attribution required.")
                return
            try:
                delete_layout_revision(
                    project_id, str(revision["id"]), editor_name
                )
                st.session_state.pop("active_revision_id", None)
                st.toast(
                    f"Deleted Revision {revision['revision_number']}",
                    icon=":material/delete:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


@st.dialog("Section Workstation Pitch Standards", width="large")
def _section_standards_dialog(
    project_id: str,
    layout_id: str,
    unit: str,
    editor_name: str,
) -> None:
    st.write(
        "Configure standard workstation pitch dimensions (Length × Width) "
        "for each Fishbone section in this plant layout. Newly placed pitches "
        "will automatically adopt these standard dimensions."
    )
    sections_df = assembly_sections(project_id)
    if sections_df.empty:
        st.info("No Fishbone assembly sections created for this project yet.")
        return

    existing_standards = get_section_pitch_standards(layout_id)

    with st.form(key=f"section_standards_form_{layout_id}"):
        st.markdown(f"**Units:** `{unit}`")
        updates: dict[str, tuple[float, float]] = {}

        for _, sec in sections_df.iterrows():
            sec_id = str(sec["id"])
            sec_name = str(sec["name"])
            current = existing_standards.get(sec_id, {})
            curr_w = current.get("pitch_width", 12.0)
            curr_h = current.get("pitch_height", 8.0)

            c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="bottom")
            with c1:
                st.markdown(f"**{sec_name}**")
                st.caption(f"Type: {sec.get('section_type', 'Section')}")
            with c2:
                w_val = st.number_input(
                    f"Length ({unit})",
                    min_value=0.5,
                    value=float(curr_w),
                    step=1.0,
                    key=f"sec_std_w_{sec_id}",
                )
            with c3:
                h_val = st.number_input(
                    f"Width ({unit})",
                    min_value=0.5,
                    value=float(curr_h),
                    step=1.0,
                    key=f"sec_std_h_{sec_id}",
                )
            updates[sec_id] = (w_val, h_val)
            st.divider()

        submitted = st.form_submit_button(
            "Save Section Pitch Standards",
            type="primary",
            width="stretch",
        )
        if submitted:
            if not editor_name.strip():
                st.error("Current editor attribution is required.")
                return
            try:
                for sec_id, (w, h) in updates.items():
                    set_section_pitch_standard(
                        project_id=project_id,
                        layout_id=layout_id,
                        section_id=sec_id,
                        pitch_width=w,
                        pitch_height=h,
                        unit=unit,
                        editor_name=editor_name,
                    )
                st.toast("Saved section pitch dimensional standards!", icon=":material/check:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


@st.dialog("Add shape to floor plan", width="large")
def _add_shape_dialog(
    active_rev: dict[str, Any],
    px_per_in: float,
    unit: str,
    draft_shapes_key: str,
    has_unsaved_shapes_key: str,
    selected_shape_id_key: str,
) -> None:
    st.write("Configure and place a scaled footprint annotation on this floor plan.")

    preset_name = st.selectbox(
        "Footprint Template Preset",
        list(FOOTPRINT_PRESETS.keys()),
        index=0,
        key="add_shape_preset_select",
    )
    preset = FOOTPRINT_PRESETS[preset_name]

    col_t1, col_t2 = st.columns([1, 1])
    with col_t1:
        shape_type = st.selectbox(
            "Shape Geometry",
            SHAPE_TYPES,
            index=SHAPE_TYPES.index(preset["shape_type"]),
            format_func=lambda s: f"{SHAPE_TYPE_ICONS.get(s, '')} {SHAPE_TYPE_LABELS.get(s, s)}",
            key="add_shape_geom_type",
        )
    with col_t2:
        label = st.text_input(
            "Annotation Label / Pitch ID",
            value=preset["label"],
            key="add_shape_label_input",
        )

    st.markdown("##### Real-World Scaled Dimensions")
    cd1, cd2, cd3 = st.columns([1, 1, 1])
    with cd1:
        w_units = st.number_input(
            f"Width ({unit})",
            min_value=0.1,
            value=float(preset["w_default"]),
            step=1.0,
            format="%.2f",
            key="add_shape_w_units",
        )
    with cd2:
        h_units = st.number_input(
            f"Height ({unit})",
            min_value=0.1,
            value=float(preset["h_default"]),
            step=1.0,
            format="%.2f",
            key="add_shape_h_units",
        )
    with cd3:
        area_units = _calculate_shape_area(shape_type, w_units, h_units)
        unit_area_label = (
            "sq ft"
            if unit == "feet"
            else ("sq in" if unit == "inches" else f"sq {unit}")
        )
        st.metric("Scaled Area", f"{area_units:,.1f} {unit_area_label}")

    w_px = max(15.0, _units_to_px(w_units, px_per_in, unit))
    h_px = max(15.0, _units_to_px(h_units, px_per_in, unit))
    st.caption(f":material/straighten: Equivalent image footprint: **{w_px:.0f} × {h_px:.0f} px**")

    st.markdown("##### Visual Styling & Contrast")
    cs1, cs2, cs3 = st.columns(3)
    with cs1:
        stroke_color = st.color_picker(
            "Line / Border Color",
            value=preset["stroke_color"],
            key="add_shape_stroke_color",
        )
        stroke_width = st.selectbox(
            "Line Thickness",
            LINE_THICKNESS_OPTIONS,
            index=LINE_THICKNESS_OPTIONS.index(preset["stroke_width"]),
            format_func=lambda t: f"{t} px",
            key="add_shape_stroke_width",
        )
        stroke_style = st.selectbox(
            "Line Style",
            LINE_STYLE_OPTIONS,
            index=LINE_STYLE_OPTIONS.index(preset["stroke_style"]),
            key="add_shape_stroke_style",
        )
    with cs2:
        fill_color = st.color_picker(
            "Fill Color",
            value=preset["fill_color"],
            key="add_shape_fill_color",
        )
        fill_opacity = st.slider(
            "Fill Opacity / Transparency",
            min_value=0,
            max_value=100,
            value=int(preset["fill_opacity"] * 100),
            step=5,
            format="%d%%",
            help="Semi-transparent fills let the underlying CAD lines remain visible.",
            key="add_shape_fill_opacity",
        )
    with cs3:
        font_size = st.selectbox(
            "Font Size",
            FONT_SIZE_OPTIONS,
            index=FONT_SIZE_OPTIONS.index(preset["font_size"]),
            format_func=lambda fs: f"{fs} pt",
            key="add_shape_font_size",
        )
        font_color = st.color_picker(
            "Font Color",
            value=preset["font_color"],
            key="add_shape_font_color",
        )
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            bold = st.checkbox("Bold", value=preset["font_weight"] == "bold", key="add_shape_bold")
        with col_b2:
            bg_pill = st.checkbox(
                "Label card",
                value=preset["bg_pill"],
                help="High-contrast pill card behind label text.",
                key="add_shape_bg_pill",
            )

    st.markdown("##### Initial Position")
    img_w = float(active_rev["image_width_px"])
    img_h = float(active_rev["image_height_px"])
    center_x = max(0.0, (img_w - w_px) / 2.0)
    center_y = max(0.0, (img_h - h_px) / 2.0)

    pos_c1, pos_c2 = st.columns(2)
    with pos_c1:
        x_units = st.number_input(
            f"X position ({unit})",
            value=float(_px_to_units(center_x, px_per_in, unit)),
            step=1.0,
            format="%.1f",
            key="add_shape_x_units",
        )
    with pos_c2:
        y_units = st.number_input(
            f"Y position ({unit})",
            value=float(_px_to_units(center_y, px_per_in, unit)),
            step=1.0,
            format="%.1f",
            key="add_shape_y_units",
        )

    pos_x_px = _units_to_px(x_units, px_per_in, unit)
    pos_y_px = _units_to_px(y_units, px_per_in, unit)

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Cancel", width="stretch", key="cancel_add_shape"):
            st.rerun()
    with col2:
        if st.button("Add shape to floor plan", type="primary", width="stretch", key="submit_add_shape"):
            new_shape_id = str(uuid4())
            style_dict = {
                "stroke_color": stroke_color,
                "stroke_width": stroke_width,
                "stroke_style": stroke_style,
                "fill_color": fill_color,
                "fill_opacity": fill_opacity / 100.0,
                "font_size": font_size,
                "font_color": font_color,
                "font_weight": "bold" if bold else "normal",
                "bg_pill": bg_pill,
            }
            new_shape = {
                "id": new_shape_id,
                "revision_id": str(active_rev["id"]),
                "shape_type": shape_type,
                "label": label.strip(),
                "x": round(pos_x_px, 1),
                "y": round(pos_y_px, 1),
                "width": round(w_px, 1),
                "height": round(h_px, 1),
                "rotation": 0.0,
                "color": stroke_color,
                "style_json": json.dumps(style_dict),
                "pitch_id": None,
                "equipment_id": None,
            }
            draft = list(st.session_state.get(draft_shapes_key, []))
            draft.append(new_shape)
            st.session_state[draft_shapes_key] = draft
            st.session_state[has_unsaved_shapes_key] = True
            st.session_state[selected_shape_id_key] = new_shape_id
            st.toast(f"Placed '{label or shape_type}' on floor plan", icon=":material/check_circle:")
            st.rerun()


@st.dialog("Confirm delete shape", width="medium")
def _delete_shape_dialog(
    shape: dict[str, Any],
    revision_number: int,
    draft_shapes_key: str,
    has_unsaved_shapes_key: str,
    selected_shape_id_key: str,
) -> None:
    shape_label = shape.get("label") or shape.get("shape_type") or "Annotation"
    st.write(f"Are you sure you want to delete **{shape_label}**?")
    st.caption(f"This will remove the annotation from Revision {revision_number} draft.")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Cancel", width="stretch", key="cancel_del_single_shape"):
            st.session_state["pending_delete_shape"] = None
            st.rerun()
    with col2:
        if st.button(
            "Delete shape",
            type="primary",
            width="stretch",
            key=f"destructive_confirm_del_shape_{shape['id']}",
        ):
            draft = list(st.session_state.get(draft_shapes_key, []))
            st.session_state[draft_shapes_key] = [s for s in draft if s.get("id") != shape.get("id")]
            st.session_state[has_unsaved_shapes_key] = True
            st.session_state[selected_shape_id_key] = None
            st.session_state["pending_delete_shape"] = None
            st.toast(f"Removed shape '{shape_label}'", icon=":material/delete:")
            st.rerun()


@st.dialog("Confirm clear all shapes", width="medium")
def _clear_all_shapes_dialog(
    count: int,
    revision_number: int,
    draft_shapes_key: str,
    has_unsaved_shapes_key: str,
    selected_shape_id_key: str,
) -> None:
    st.write(f"Clear all **{count}** annotation shapes from Revision {revision_number} draft?")
    st.warning("All shapes will be cleared from the active workspace. Remember to click 'Save & Refresh' to commit.")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Cancel", width="stretch", key="cancel_clear_all_shapes"):
            st.rerun()
    with col2:
        if st.button(
            "Clear all shapes",
            type="primary",
            width="stretch",
            key="destructive_confirm_clear_all_shapes",
        ):
            st.session_state[draft_shapes_key] = []
            st.session_state[has_unsaved_shapes_key] = True
            st.session_state[selected_shape_id_key] = None
            st.toast(f"Cleared all shapes from Rev {revision_number} draft", icon=":material/delete_sweep:")
            st.rerun()


def _render_scale_bar_html(px_per_ft: float, unit: str) -> str:
    """Render an interactive visual scale reference bar in HTML."""
    if px_per_ft <= 0:
        return ""

    if unit == "feet":
        step_units = 10.0 if px_per_ft * 10.0 < 400 else 5.0
        bar_px = px_per_ft * step_units
        unit_text = f"{step_units:g} ft"
    elif unit == "inches":
        px_per_in = px_per_ft / 12.0
        step_units = 24.0 if px_per_in * 24.0 < 400 else 12.0
        bar_px = px_per_in * step_units
        unit_text = f"{step_units:g} in"
    elif unit == "yards":
        step_units = 5.0
        bar_px = px_per_ft * 3.0 * step_units
        unit_text = f"{step_units:g} yd"
    else:
        step_units = 1.0
        bar_px = px_per_ft * step_units
        unit_text = f"{step_units:g} {unit}"

    if bar_px < 20 or bar_px > 600:
        bar_px = max(40.0, min(500.0, bar_px))

    return f"""
    <div style="display:flex; align-items:center; gap:12px; margin:6px 0 10px 0; font-size:0.8rem; color:#57606a;">
      <span style="font-weight:600; text-transform:uppercase; font-size:0.75rem; letter-spacing:0.5px;">Scale:</span>
      <div style="display:inline-flex; flex-direction:column; align-items:center;">
        <span style="font-size:0.75rem; font-weight:600; color:#1976d2; margin-bottom:2px;">{unit_text}</span>
        <div style="width:{bar_px:.1f}px; height:6px; border:2px solid #1976d2; border-top:none; background:linear-gradient(to right, #1976d2 50%, transparent 50%); background-size:50% 100%;"></div>
      </div>
      <span style="font-size:0.75rem;">({bar_px:.0f} px on canvas)</span>
    </div>
    """


def render_layouts_tab(project_id: str, editor_name: str) -> None:
    """Render the Plant Floor Plan Layouts sub-tab with scale dashboard, canvas, and shape annotations."""
    section_heading_with_scope(
        "Plant Floor Plan Layouts",
        scope="project",
        help_text="Project-wide 2D architectural drawings, scaling, and equipment footprints",
    )

    layouts = list_layouts(project_id)

    # Top Control Bar
    top_col1, top_col2 = st.columns([3, 1], vertical_alignment="bottom")
    with top_col1:
        if not layouts:
            st.info("No floor plan layouts created yet. Click **New layout** to add your first plant layout.")
            if st.button("+ New layout", type="primary", icon=":material/add:"):
                _create_layout_dialog(project_id, editor_name)
            return

        layout_options = {l["id"]: l["name"] for l in layouts}
        saved_layout_id = st.session_state.get("active_layout_id")
        if saved_layout_id not in layout_options:
            saved_layout_id = layouts[0]["id"]
            st.session_state["active_layout_id"] = saved_layout_id

        selected_layout_id = st.selectbox(
            "Selected layout",
            options=list(layout_options.keys()),
            format_func=lambda lid: layout_options[lid],
            index=list(layout_options.keys()).index(saved_layout_id),
            key="layout_plan_selector",
        )
        st.session_state["active_layout_id"] = selected_layout_id

    with top_col2:
        if st.button("+ New layout", icon=":material/add:", width="stretch", key="btn_open_new_layout"):
            _create_layout_dialog(project_id, editor_name)

    current_layout = get_layout(project_id, selected_layout_id)
    if not current_layout:
        st.warning("Selected layout could not be loaded.")
        return

    if current_layout.get("description"):
        st.caption(f":material/description: {current_layout['description']}")

    # Revisions for selected layout
    revisions = list_layout_revisions(selected_layout_id)

    # Revision Selector & Actions
    rev_bar1, rev_bar2 = st.columns([3, 1], vertical_alignment="bottom")
    with rev_bar1:
        if not revisions:
            st.warning(
                f"Layout '{current_layout['name']}' has no revisions uploaded yet. "
                f"Add your first CAD drawing or screenshot below."
            )
            if st.button("+ Add initial drawing revision", type="primary", icon=":material/upload:"):
                _create_revision_dialog(project_id, current_layout, None, editor_name)
            return

        rev_map = {
            r["id"]: f"Rev {r['revision_number']} ({r['width_value']:g} × {r['height_value']:g} {r['unit']}) — {r['created_at'][:10]}"
            for r in revisions
        }
        saved_rev_id = st.session_state.get("active_revision_id")
        if saved_rev_id not in rev_map:
            saved_rev_id = revisions[0]["id"]
            st.session_state["active_revision_id"] = saved_rev_id

        selected_rev_id = st.selectbox(
            "Revision",
            options=list(rev_map.keys()),
            format_func=lambda rid: rev_map[rid],
            index=list(rev_map.keys()).index(saved_rev_id),
            key="layout_revision_selector",
        )
        st.session_state["active_revision_id"] = selected_rev_id

    with rev_bar2:
        latest_rev = revisions[0] if revisions else None
        if st.button("+ New revision", icon=":material/upload:", width="stretch", key="btn_open_new_rev"):
            _create_revision_dialog(project_id, current_layout, latest_rev, editor_name)

    active_rev = get_layout_revision(selected_rev_id)
    if not active_rev:
        st.warning("Could not load revision details.")
        return

    # Scale metrics & parameters
    w_in = float(active_rev["scale_width_in"])
    h_in = float(active_rev["scale_height_in"])
    w_px = int(active_rev["image_width_px"])
    h_px = int(active_rev["image_height_px"])
    unit = str(active_rev["unit"])

    px_per_in = (w_px / w_in) if w_in > 0 else 0.0
    in_per_px = (w_in / w_px) if w_px > 0 else 0.0
    px_per_ft = px_per_in * 12.0

    # Scale Dashboard Cards
    with st.container(border=True):
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric(
                "Physical Dimensions",
                f"{active_rev['width_value']:g} × {active_rev['height_value']:g} {unit}",
                help=f"Canonical Imperial: {w_in:,.1f} in × {h_in:,.1f} in",
            )
        with m2:
            st.metric(
                "Image Resolution",
                f"{w_px:,} × {h_px:,} px",
                help="Native pixel resolution of uploaded drawing",
            )
        with m3:
            scale_label = f"1 px = {in_per_px:.2f} in" if in_per_px < 12 else f"1 px = {in_per_px/12:.2f} ft"
            st.metric(
                "Layout Scale",
                scale_label,
                help=f"{px_per_ft:.2f} px / ft ({px_per_in:.3f} px / in)",
            )
        with m4:
            st.metric(
                "Revision Details",
                f"Rev {active_rev['revision_number']}",
                help=str(active_rev.get("notes") or ""),
            )
            if active_rev["notes"]:
                st.caption(f":material/notes: {active_rev['notes']}")

        scale_bar_html = _render_scale_bar_html(px_per_ft, unit)
        if scale_bar_html:
            st.markdown(scale_bar_html, unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # 2D Interactive Layout & Shape Annotations Workspace
    # -------------------------------------------------------------------------
    img_path = Path(str(active_rev["image_path"]))
    if not img_path.exists():
        st.error(f"Image file not found at: {img_path}")
        return

    draft_shapes_key = f"layout_shapes_draft_{active_rev['id']}"
    has_unsaved_shapes_key = f"layout_shapes_has_unsaved_{active_rev['id']}"
    selected_shape_id_key = f"layout_selected_shape_{active_rev['id']}"
    canvas_key = f"layout_canvas_{active_rev['id']}"

    # Initialize draft shapes in session state if absent
    if draft_shapes_key not in st.session_state:
        persisted_shapes = list_layout_shapes(str(active_rev["id"]))
        st.session_state[draft_shapes_key] = [dict(s) for s in persisted_shapes]

    draft_shapes: list[dict[str, Any]] = st.session_state.get(draft_shapes_key, [])
    has_unsaved_shapes: bool = st.session_state.get(has_unsaved_shapes_key, False)
    selected_shape_id: str | None = st.session_state.get(selected_shape_id_key)

    # Canvas Workspace Toolbar
    with st.container(border=True):
        tb1, tb2, tb3 = st.columns([2, 3, 3], vertical_alignment="center")
        with tb1:
            st.markdown("#### :material/draw: 2D Floor Plan Canvas")
        with tb2:
            st.caption(
                f":material/layers: **{len(draft_shapes)}** annotation(s) placed on Rev {active_rev['revision_number']}. "
                f"Drag canvas to pan · Scroll to zoom · Click shape to select / drag to move"
            )
        with tb3:
            btn_col1, btn_col2 = st.columns([1, 1])
            with btn_col1:
                if st.button(
                    "Pitch Standards",
                    icon=":material/straighten:",
                    width="stretch",
                    help="Configure section pitch dimensions (Length × Width)",
                    key=f"btn_open_standards_{active_rev['id']}",
                ):
                    _section_standards_dialog(
                        project_id=project_id,
                        layout_id=selected_layout_id,
                        unit=unit,
                        editor_name=editor_name,
                    )
            with btn_col2:
                if st.button(
                    "+ Add Shape",
                    type="primary",
                    icon=":material/add:",
                    width="stretch",
                    key=f"btn_open_add_shape_{active_rev['id']}",
                ):
                    _add_shape_dialog(
                        active_rev=active_rev,
                        px_per_in=px_per_in,
                        unit=unit,
                        draft_shapes_key=draft_shapes_key,
                        has_unsaved_shapes_key=has_unsaved_shapes_key,
                        selected_shape_id_key=selected_shape_id_key,
                    )

    # Cross-Scenario Yamazumi Pitches Palette
    project_pitches = list_project_yamazumi_pitches(project_id)
    section_standards = get_section_pitch_standards(selected_layout_id)

    with st.expander(
        f":material/view_column: Yamazumi Pitches Palette ({len(project_pitches)} workstation pitches across scenarios)",
        expanded=False,
    ):
        if not project_pitches:
            st.info(
                "No Yamazumi pitches found in this project. Create pitches under the "
                "Yamazumi tab to place workstation footprints to scale.",
                icon=":material/info:",
            )
        else:
            st.caption(
                "Workstations adopt standard dimensions configured per section. "
                "Pitches are magnetically aligned and snap into straight contiguous lines."
            )
            # Group by area
            areas_map: dict[str, list[dict[str, Any]]] = {}
            for p in project_pitches:
                area_key = f"{p['area_name']} (Section: {p.get('section_id') or 'Unlinked'})"
                areas_map.setdefault(area_key, []).append(p)

            for area_title, area_pitch_list in areas_map.items():
                first_p = area_pitch_list[0]
                sec_id = str(first_p.get("section_id") or "")
                std_dim = section_standards.get(sec_id, {})
                std_w = std_dim.get("pitch_width", 12.0)
                std_h = std_dim.get("pitch_height", 8.0)

                col_hdr1, col_hdr2 = st.columns([3, 1], vertical_alignment="center")
                with col_hdr1:
                    st.markdown(f"**{area_title}** · Standard Size: `{std_w:g} × {std_h:g} {unit}`")
                with col_hdr2:
                    if st.button("Edit Size", icon=":material/straighten:", key=f"btn_edit_sec_sz_{sec_id}_{area_title}"):
                        _section_standards_dialog(project_id, selected_layout_id, unit, editor_name)

                pitch_cols = st.columns(3)
                for idx, pitch in enumerate(area_pitch_list):
                    col = pitch_cols[idx % 3]
                    p_id = str(pitch["pitch_id"])
                    is_placed = any(s.get("pitch_id") == p_id for s in draft_shapes)
                    with col.container(border=True):
                        st.markdown(f"**{pitch['pitch_number']}** — {pitch['pitch_name']}")
                        st.caption(f":material/history_edu: Rev {pitch['scenario_revision_label']} · {pitch['scenario_name']}")
                        if is_placed:
                            st.caption(":green[:material/check_circle: Placed on layout]")
                            if st.button("Select on canvas", key=f"sel_placed_{p_id}", width="stretch"):
                                placed_shape = next((s for s in draft_shapes if s.get("pitch_id") == p_id), None)
                                if placed_shape:
                                    st.session_state[selected_shape_id_key] = placed_shape["id"]
                                    st.rerun()
                        else:
                            if st.button(
                                "+ Place on layout",
                                key=f"btn_place_pitch_{p_id}",
                                type="secondary",
                                width="stretch",
                            ):
                                w_in_canon = to_canonical_inches(std_w, unit)
                                h_in_canon = to_canonical_inches(std_h, unit)
                                w_px_calc = max(24, round(w_in_canon * px_per_in))
                                h_px_calc = max(24, round(h_in_canon * px_per_in))

                                # Calculate snap placement adjacent to previous pitch in this area
                                same_area_placed = [
                                    s for s in draft_shapes
                                    if any(
                                        p2["pitch_id"] == s.get("pitch_id")
                                        for p2 in area_pitch_list
                                    )
                                ]
                                if same_area_placed:
                                    prev_s = same_area_placed[-1]
                                    new_x = prev_s["x"] + prev_s["width"]
                                    new_y = prev_s["y"]
                                else:
                                    new_x = 100
                                    new_y = 100 + len(draft_shapes) * 20

                                new_shape_id = str(uuid4())
                                new_pitch_shape = {
                                    "id": new_shape_id,
                                    "revision_id": str(active_rev["id"]),
                                    "shape_type": "rectangle",
                                    "x": int(new_x),
                                    "y": int(new_y),
                                    "width": int(w_px_calc),
                                    "height": int(h_px_calc),
                                    "rotation": 0.0,
                                    "color": "#1976d2",
                                    "label": f"{pitch['pitch_number']} - {pitch['pitch_name']}",
                                    "style_json": json.dumps({
                                        "stroke_color": "#1565c0",
                                        "stroke_width": 2,
                                        "stroke_style": "solid",
                                        "fill_color": "#e3f2fd",
                                        "fill_opacity": 0.6,
                                        "font_size": 13,
                                        "font_color": "#0d47a1",
                                        "font_weight": "bold",
                                        "bg_pill": True,
                                    }),
                                    "pitch_id": p_id,
                                    "equipment_id": None,
                                }
                                draft_shapes.append(new_pitch_shape)
                                st.session_state[draft_shapes_key] = draft_shapes
                                st.session_state[has_unsaved_shapes_key] = True
                                st.session_state[selected_shape_id_key] = new_shape_id
                                st.toast(f"Placed workstation {pitch['pitch_number']} on floor plan!", icon=":material/add_box:")
                                st.rerun()
                st.divider()

    # Custom component callback handlers
    def handle_select_shape() -> None:
        state = st.session_state.get(canvas_key)
        trigger = getattr(state, "select_shape", None) if state is not None else None
        if not trigger and isinstance(state, dict):
            trigger = state.get("select_shape")
        if trigger and "shape_id" in trigger:
            st.session_state[selected_shape_id_key] = trigger["shape_id"] or None

    def handle_shape_moved() -> None:
        state = st.session_state.get(canvas_key)
        trigger = getattr(state, "shape_moved", None) if state is not None else None
        if not trigger and isinstance(state, dict):
            trigger = state.get("shape_moved")
        if trigger and "shape_id" in trigger:
            s_id = trigger["shape_id"]
            draft = list(st.session_state.get(draft_shapes_key, []))
            for s in draft:
                if s.get("id") == s_id:
                    s["x"] = float(trigger.get("x", s.get("x", 0.0)))
                    s["y"] = float(trigger.get("y", s.get("y", 0.0)))
                    if "width" in trigger:
                        s["width"] = float(trigger["width"])
                    if "height" in trigger:
                        s["height"] = float(trigger["height"])
                    break
            st.session_state[draft_shapes_key] = draft
            st.session_state[has_unsaved_shapes_key] = True
            st.session_state[selected_shape_id_key] = s_id

    # Render interactive layout canvas
    image_data_url = (
        layout_image_data_url(str(img_path), img_path.stat().st_mtime_ns)
        if img_path.is_file()
        else ""
    )

    layout_canvas(
        image_url=image_data_url,
        image_width=w_px,
        image_height=h_px,
        scale_factor_px_per_in=px_per_in,
        unit=unit,
        shapes=draft_shapes,
        selected_shape_id=selected_shape_id,
        key=canvas_key,
        on_select_shape=handle_select_shape,
        on_shape_moved=handle_shape_moved,
    )

    # -------------------------------------------------------------------------
    # Selected Shape Inspector & Quick Editor
    # -------------------------------------------------------------------------
    selected_shape = next(
        (s for s in draft_shapes if s.get("id") == selected_shape_id), None
    )

    if selected_shape:
        st.markdown("---")
        with st.container(border=True):
            stype = selected_shape.get("shape_type", "rectangle")
            slabel = selected_shape.get("label") or selected_shape.get("shape_type") or "Annotation"
            icon = SHAPE_TYPE_ICONS.get(stype, "⏹️")
            sw_units = _px_to_units(float(selected_shape.get("width", 0)), px_per_in, unit)
            sh_units = _px_to_units(float(selected_shape.get("height", 0)), px_per_in, unit)
            sarea = _calculate_shape_area(stype, sw_units, sh_units)
            unit_area_label = (
                "sq ft"
                if unit == "feet"
                else ("sq in" if unit == "inches" else f"sq {unit}")
            )

            # Inspector Header
            ih1, ih2 = st.columns([3, 1], vertical_alignment="center")
            with ih1:
                st.markdown(
                    f"##### {icon} Selected Shape: **{slabel}** "
                    f"&nbsp;·&nbsp; <small style='color:#1976d2; font-weight:600;'>{sw_units:.1f} × {sh_units:.1f} {unit} ({sarea:,.1f} {unit_area_label})</small>",
                    unsafe_allow_html=True,
                )
            with ih2:
                if st.button("Deselect", icon=":material/close:", width="stretch", key="btn_deselect_shape"):
                    st.session_state[selected_shape_id_key] = None
                    st.rerun()

            # Parse existing style JSON
            style = {}
            try:
                style_raw = selected_shape.get("style_json")
                style = json.loads(style_raw) if isinstance(style_raw, str) else (style_raw or {})
            except Exception:
                style = {}

            # Editor Controls in 3 columns
            ec1, ec2, ec3 = st.columns(3)
            with ec1:
                st.caption("**Identity & Scale**")
                new_slabel = st.text_input(
                    "Label / ID",
                    value=selected_shape.get("label", ""),
                    key=f"insp_label_{selected_shape['id']}",
                )
                cur_pitch_id = selected_shape.get("pitch_id") or ""
                pitch_opts = {"": "None (Generic Shape)"}
                for p in project_pitches:
                    pitch_opts[p["pitch_id"]] = f"{p['pitch_number']} - {p['pitch_name']} ({p['scenario_name']})"

                selected_pitch_link = st.selectbox(
                    "Linked Workstation Pitch",
                    options=list(pitch_opts.keys()),
                    format_func=lambda pid: pitch_opts[pid],
                    index=list(pitch_opts.keys()).index(cur_pitch_id) if cur_pitch_id in pitch_opts else 0,
                    key=f"insp_pitch_link_{selected_shape['id']}",
                )
                new_w_units = st.number_input(
                    f"Width ({unit})",
                    min_value=0.1,
                    value=float(sw_units),
                    step=1.0,
                    format="%.2f",
                    key=f"insp_w_{selected_shape['id']}",
                )
                new_h_units = st.number_input(
                    f"Height ({unit})",
                    min_value=0.1,
                    value=float(sh_units),
                    step=1.0,
                    format="%.2f",
                    key=f"insp_h_{selected_shape['id']}",
                )
                new_rot = st.slider(
                    "Rotation (degrees)",
                    min_value=0,
                    max_value=360,
                    value=int(selected_shape.get("rotation", 0)),
                    step=5,
                    key=f"insp_rot_{selected_shape['id']}",
                )

            with ec2:
                st.caption("**Border & Fill Styling**")
                cur_stroke = style.get("stroke_color") or selected_shape.get("color") or "#1976d2"
                new_stroke = st.color_picker(
                    "Border Color",
                    value=cur_stroke,
                    key=f"insp_stroke_{selected_shape['id']}",
                )
                cur_thick = int(style.get("stroke_width", 2))
                thick_idx = (
                    LINE_THICKNESS_OPTIONS.index(cur_thick)
                    if cur_thick in LINE_THICKNESS_OPTIONS
                    else 1
                )
                new_thick = st.selectbox(
                    "Line Thickness",
                    LINE_THICKNESS_OPTIONS,
                    index=thick_idx,
                    format_func=lambda t: f"{t} px",
                    key=f"insp_thick_{selected_shape['id']}",
                )
                cur_lstyle = style.get("stroke_style", "solid")
                lstyle_idx = (
                    LINE_STYLE_OPTIONS.index(cur_lstyle)
                    if cur_lstyle in LINE_STYLE_OPTIONS
                    else 0
                )
                new_lstyle = st.selectbox(
                    "Line Style",
                    LINE_STYLE_OPTIONS,
                    index=lstyle_idx,
                    key=f"insp_lstyle_{selected_shape['id']}",
                )
                cur_fill = style.get("fill_color") or selected_shape.get("color") or "#1976d2"
                new_fill = st.color_picker(
                    "Fill Color",
                    value=cur_fill,
                    key=f"insp_fill_{selected_shape['id']}",
                )
                cur_opac = int(float(style.get("fill_opacity", 0.25)) * 100)
                new_opac = st.slider(
                    "Fill Opacity",
                    min_value=0,
                    max_value=100,
                    value=cur_opac,
                    step=5,
                    format="%d%%",
                    key=f"insp_opac_{selected_shape['id']}",
                )

            with ec3:
                st.caption("**Text / Label Styling**")
                cur_fsize = int(style.get("font_size", 14))
                fsize_idx = (
                    FONT_SIZE_OPTIONS.index(cur_fsize)
                    if cur_fsize in FONT_SIZE_OPTIONS
                    else 2
                )
                new_fsize = st.selectbox(
                    "Font Size",
                    FONT_SIZE_OPTIONS,
                    index=fsize_idx,
                    format_func=lambda fs: f"{fs} pt",
                    key=f"insp_fsize_{selected_shape['id']}",
                )
                cur_fcolor = style.get("font_color", "#1a1a1a")
                new_fcolor = st.color_picker(
                    "Font Color",
                    value=cur_fcolor,
                    key=f"insp_fcolor_{selected_shape['id']}",
                )
                new_bold = st.checkbox(
                    "Bold",
                    value=style.get("font_weight", "bold") == "bold",
                    key=f"insp_bold_{selected_shape['id']}",
                )
                new_bg_pill = st.checkbox(
                    "Contrast label card",
                    value=bool(style.get("bg_pill", True)),
                    key=f"insp_pill_{selected_shape['id']}",
                )

                st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
                # Action Buttons
                col_dup, col_del = st.columns(2)
                with col_dup:
                    if st.button("Duplicate", icon=":material/content_copy:", width="stretch", key=f"btn_dup_{selected_shape['id']}"):
                        dup_shape = dict(selected_shape)
                        dup_shape["id"] = str(uuid4())
                        dup_shape["label"] = f"{slabel} (Copy)"
                        dup_shape["x"] = float(selected_shape.get("x", 0)) + 30.0
                        dup_shape["y"] = float(selected_shape.get("y", 0)) + 30.0
                        draft_shapes.append(dup_shape)
                        st.session_state[draft_shapes_key] = draft_shapes
                        st.session_state[has_unsaved_shapes_key] = True
                        st.session_state[selected_shape_id_key] = dup_shape["id"]
                        st.toast(f"Duplicated shape as '{dup_shape['label']}'", icon=":material/content_copy:")
                        st.rerun()

                with col_del:
                    if st.button("Delete...", icon=":material/delete:", width="stretch", key=f"btn_del_shape_{selected_shape['id']}"):
                        _delete_shape_dialog(
                            shape=selected_shape,
                            revision_number=int(active_rev["revision_number"]),
                            draft_shapes_key=draft_shapes_key,
                            has_unsaved_shapes_key=has_unsaved_shapes_key,
                            selected_shape_id_key=selected_shape_id_key,
                        )

            # Check if inspector values changed and apply them to draft
            target_w_px = round(_units_to_px(new_w_units, px_per_in, unit), 1)
            target_h_px = round(_units_to_px(new_h_units, px_per_in, unit), 1)

            new_style_dict = {
                "stroke_color": new_stroke,
                "stroke_width": new_thick,
                "stroke_style": new_lstyle,
                "fill_color": new_fill,
                "fill_opacity": new_opac / 100.0,
                "font_size": new_fsize,
                "font_color": new_fcolor,
                "font_weight": "bold" if new_bold else "normal",
                "bg_pill": new_bg_pill,
            }
            new_style_json = json.dumps(new_style_dict)

            inspector_changed = (
                new_slabel != selected_shape.get("label", "")
                or abs(target_w_px - float(selected_shape.get("width", 0))) > 0.5
                or abs(target_h_px - float(selected_shape.get("height", 0))) > 0.5
                or float(new_rot) != float(selected_shape.get("rotation", 0))
                or new_stroke != cur_stroke
                or new_thick != cur_thick
                or new_lstyle != cur_lstyle
                or new_fill != cur_fill
                or new_opac != cur_opac
                or new_fsize != cur_fsize
                or new_fcolor != cur_fcolor
                or (new_bold != (style.get("font_weight", "bold") == "bold"))
                or (new_bg_pill != bool(style.get("bg_pill", True)))
                or ((selected_pitch_link or None) != (selected_shape.get("pitch_id") or None))
            )

            if inspector_changed:
                selected_shape["label"] = new_slabel
                selected_shape["pitch_id"] = selected_pitch_link or None
                selected_shape["width"] = target_w_px
                selected_shape["height"] = target_h_px
                selected_shape["rotation"] = float(new_rot)
                selected_shape["color"] = new_stroke
                selected_shape["style_json"] = new_style_json
                st.session_state[draft_shapes_key] = draft_shapes
                st.session_state[has_unsaved_shapes_key] = True
                st.rerun()

    # -------------------------------------------------------------------------
    # Annotation Inventory Table
    # -------------------------------------------------------------------------
    with st.expander(f"Annotation Inventory ({len(draft_shapes)} shapes)", expanded=False):
        if not draft_shapes:
            st.caption("No annotations placed yet. Click **+ Add Shape** above to place your first footprint.")
        else:
            table_rows = []
            for s in draft_shapes:
                stype = s.get("shape_type", "rectangle")
                icon = SHAPE_TYPE_ICONS.get(stype, "⏹️")
                sw_u = _px_to_units(float(s.get("width", 0)), px_per_in, unit)
                sh_u = _px_to_units(float(s.get("height", 0)), px_per_in, unit)
                area_u = _calculate_shape_area(stype, sw_u, sh_u)
                unit_area_label = (
                    "sq ft"
                    if unit == "feet"
                    else ("sq in" if unit == "inches" else f"sq {unit}")
                )

                s_style = {}
                try:
                    s_style = json.loads(s.get("style_json", "{}"))
                except Exception:
                    pass

                table_rows.append(
                    {
                        "id": s.get("id"),
                        "Shape": f"{icon} {stype.capitalize()}",
                        "Label": s.get("label") or "(No label)",
                        "Dimensions": f"{sw_u:.1f} × {sh_u:.1f} {unit}",
                        "Area": f"{area_u:,.1f} {unit_area_label}",
                        "Border": f"{s_style.get('stroke_width', 2)}px {s_style.get('stroke_style', 'solid')}",
                        "Border Color": s_style.get("stroke_color") or s.get("color", "#1976d2"),
                        "Fill Color": s_style.get("fill_color") or s.get("color", "#1976d2"),
                        "Opacity": f"{int(float(s_style.get('fill_opacity', 0.25)) * 100)}%",
                    }
                )

            df_shapes = pd.DataFrame(table_rows)
            st.dataframe(
                df_shapes.drop(columns=["id"]),
                hide_index=True,
                width="stretch",
            )

            tc1, tc2 = st.columns([3, 1], vertical_alignment="center")
            with tc1:
                shape_picker_map = {s["id"]: f"{SHAPE_TYPE_ICONS.get(s.get('shape_type'), '')} {s.get('label') or s.get('shape_type')} [{_px_to_units(float(s.get('width', 0)), px_per_in, unit):.1f} × {_px_to_units(float(s.get('height', 0)), px_per_in, unit):.1f} {unit}]" for s in draft_shapes}
                curr_sel_idx = (
                    list(shape_picker_map.keys()).index(selected_shape_id)
                    if selected_shape_id in shape_picker_map
                    else 0
                )
                picked_shape_id = st.selectbox(
                    "Select shape to inspect/edit",
                    options=list(shape_picker_map.keys()),
                    format_func=lambda sid: shape_picker_map[sid],
                    index=curr_sel_idx,
                    key="table_shape_picker",
                )
                if st.button("Inspect selected shape", icon=":material/edit:", key="btn_inspect_picked"):
                    st.session_state[selected_shape_id_key] = picked_shape_id
                    st.rerun()

            with tc2:
                if st.button("Clear all shapes...", icon=":material/delete_sweep:", width="stretch", key="btn_open_clear_all"):
                    _clear_all_shapes_dialog(
                        count=len(draft_shapes),
                        revision_number=int(active_rev["revision_number"]),
                        draft_shapes_key=draft_shapes_key,
                        has_unsaved_shapes_key=has_unsaved_shapes_key,
                        selected_shape_id_key=selected_shape_id_key,
                    )

    # -------------------------------------------------------------------------
    # Universal Save Action Standard Footer for Shapes
    # -------------------------------------------------------------------------
    shape_footer_actions = editable_table_footer(
        editor_key=f"layout_shapes_footer_{active_rev['id']}",
        key_prefix=f"layout_shapes_{active_rev['id']}",
        additional_unsaved_changes=has_unsaved_shapes,
    )

    if shape_footer_actions.undo:
        st.session_state.pop(draft_shapes_key, None)
        st.session_state.pop(has_unsaved_shapes_key, None)
        st.session_state.pop(selected_shape_id_key, None)
        st.toast("Restored last-saved annotations", icon=":material/undo:")
        st.rerun()

    if shape_footer_actions.save_and_refresh:
        if not editor_name:
            st.error("Please enter Current editor attribution.")
        else:
            try:
                save_layout_shapes(
                    project_id=project_id,
                    revision_id=str(active_rev["id"]),
                    shapes=draft_shapes,
                    editor_name=editor_name,
                )
                st.session_state[has_unsaved_shapes_key] = False
                st.toast(
                    f"Saved {len(draft_shapes)} annotation(s) to Rev {active_rev['revision_number']}",
                    icon=":material/check_circle:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    # -------------------------------------------------------------------------
    # Scale Adjustment / Calibration Form (Universal Save Action Standard)
    # -------------------------------------------------------------------------
    with st.expander("Calibrate / Edit Scale", expanded=False):
        st.caption("Adjust the real-world physical dimensions represented by this floor plan.")
        edit_w_key = f"edit_scale_w_{active_rev['id']}"
        edit_h_key = f"edit_scale_h_{active_rev['id']}"
        edit_u_key = f"edit_scale_u_{active_rev['id']}"
        edit_n_key = f"edit_scale_n_{active_rev['id']}"

        curr_unit_idx = LAYOUT_UNITS.index(unit) if unit in LAYOUT_UNITS else 0

        ec1, ec2, ec3 = st.columns([1, 1, 1])
        with ec1:
            new_w = st.number_input(
                "Width",
                min_value=0.01,
                value=float(active_rev["width_value"]),
                step=1.0,
                format="%.2f",
                key=edit_w_key,
            )
        with ec2:
            new_h = st.number_input(
                "Height",
                min_value=0.01,
                value=float(active_rev["height_value"]),
                step=1.0,
                format="%.2f",
                key=edit_h_key,
            )
        with ec3:
            new_unit = st.selectbox(
                "Unit",
                LAYOUT_UNITS,
                index=curr_unit_idx,
                key=edit_u_key,
            )

        new_notes = st.text_input(
            "Revision notes",
            value=str(active_rev.get("notes") or ""),
            key=edit_n_key,
        )

        scale_changed = (
            abs(new_w - float(active_rev["width_value"])) > 1e-4
            or abs(new_h - float(active_rev["height_value"])) > 1e-4
            or new_unit != unit
            or new_notes != str(active_rev.get("notes") or "")
        )

        fc1, fc2, fc3 = st.columns([3, 1, 1], vertical_alignment="center")
        with fc1:
            if scale_changed:
                st.markdown(":orange[:material/warning: **Unsaved scale changes**]")
        with fc2:
            if st.button("Undo", icon=":material/undo:", disabled=not scale_changed, key=f"undo_scale_{active_rev['id']}"):
                st.rerun()
        with fc3:
            if st.button(
                "Save & Refresh",
                type="primary",
                icon=":material/save:",
                key=f"save_scale_{active_rev['id']}",
            ):
                if not editor_name:
                    st.error("Please enter Current editor attribution.")
                    return
                try:
                    update_layout_revision_scale(
                        project_id=project_id,
                        revision_id=str(active_rev["id"]),
                        width_value=new_w,
                        height_value=new_h,
                        unit=new_unit,
                        notes=new_notes,
                        editor_name=editor_name,
                    )
                    st.toast("Layout scale updated successfully", icon=":material/check_circle:")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    # Revision History & Management
    with st.expander("Revision History & Management", expanded=False):
        st.markdown("##### All revisions for this layout")
        rev_rows = []
        for r in revisions:
            rev_rows.append(
                {
                    "Rev": f"Rev {r['revision_number']}",
                    "Scale": f"{r['width_value']:g} × {r['height_value']:g} {r['unit']}",
                    "Dimensions (in)": f"{r['scale_width_in']:,.0f} × {r['scale_height_in']:,.0f} in",
                    "Resolution": f"{r['image_width_px']} × {r['image_height_px']} px",
                    "Shapes": r["shape_count"],
                    "Author": r["created_by"] or "Unknown",
                    "Date": str(r["created_at"])[:19].replace("T", " "),
                    "Notes": r["notes"],
                }
            )
        st.dataframe(pd.DataFrame(rev_rows), hide_index=True, width="stretch")

        if len(revisions) > 1:
            st.markdown("---")
            if st.button(
                f"Delete Rev {active_rev['revision_number']}",
                icon=":material/delete:",
                key=f"btn_open_del_rev_{active_rev['id']}",
                help="Delete only this revision while preserving other revisions.",
            ):
                _delete_revision_dialog(project_id, current_layout["name"], active_rev, editor_name)

    # Layout Settings & Deletion Expander
    with st.expander("Layout Settings & Deletion", expanded=False):
        edit_lname = st.text_input(
            "Layout name",
            value=str(current_layout["name"]),
            key=f"edit_layout_name_{current_layout['id']}",
        )
        edit_ldesc = st.text_area(
            "Layout description",
            value=str(current_layout.get("description") or ""),
            key=f"edit_layout_desc_{current_layout['id']}",
        )
        col_save_l, col_del_l = st.columns([1, 1])
        with col_save_l:
            if st.button("Save layout details", icon=":material/save:", key=f"save_layout_meta_{current_layout['id']}"):
                if not editor_name:
                    st.error("Please enter Current editor attribution.")
                    return
                try:
                    update_layout(project_id, str(current_layout["id"]), edit_lname, edit_ldesc, editor_name)
                    st.toast("Layout details updated", icon=":material/check_circle:")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with col_del_l:
            if st.button(
                "Delete layout...",
                icon=":material/delete_forever:",
                key=f"btn_open_del_layout_{current_layout['id']}",
                help="Permanently delete this entire layout, its revisions, and all owned uploads.",
            ):
                _delete_layout_dialog(project_id, current_layout, editor_name)

    # Universal History Expander at bottom
    with st.expander("History", expanded=False):
        history_df = audit_history(project_id, table_name="Layouts", limit=50)
        if history_df.empty:
            st.caption("No Layout history recorded yet.")
        else:
            selectable_dataframe(
                history_df.drop(columns=["details"], errors="ignore"),
                key=f"layout_audit_history_{project_id}",
                hide_index=True,
                column_config={
                    "action": "Action",
                    "row_count": "Count",
                    "editor_name": "Editor",
                    "created_at": st.column_config.DatetimeColumn(
                        "When", format="MMM DD, YYYY HH:mm"
                    ),
                },
            )
