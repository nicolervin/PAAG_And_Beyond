"""User interface for 2D plant floor plan layouts, image calibration, revision history,
and interactive shape annotations to scale.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import streamlit as st

from utils.layout_canvas import layout_canvas, layout_image_data_url
from utils.layout_store import (
    IMPERIAL_LAYOUT_UNITS,
    LAYOUT_UNITS,
    UNIT_TO_INCHES,
    annotate_preview_with_dimensions,
    apply_image_crop,
    attach_layout_revision_cad,
    auto_detect_whitespace_crop,
    calibrate_revision_scale_by_reference,
    create_blank_scaled_revision,
    create_layout,
    create_layout_layer,
    create_layout_revision,
    delete_layout,
    delete_layout_custom_stencil,
    delete_layout_layer,
    delete_layout_revision,
    ensure_default_layers_for_revision,
    ensure_default_pin_map_page,
    format_dimension,
    from_canonical_inches,
    get_layout,
    get_layout_revision,
    get_pdf_page_count,
    get_scenario_pitch_metrics_for_pin_map,
    get_section_pitch_standards,
    import_shapes_from_revision,
    layout_deletion_impact,
    list_layout_custom_stencils,
    list_layout_layers,
    list_layout_revisions,
    list_layout_shapes,
    list_layouts,
    list_project_yamazumi_pitches,
    load_and_orient_layout_preview,
    remove_layout_revision_cad,
    reorder_layout_layers,
    save_layout_custom_stencil,
    save_layout_shapes,
    set_section_pitch_standard,
    to_canonical_inches,
    update_layout,
    update_layout_layer,
    update_layout_revision_scale,
    update_revision_background_from_data_url,
)
from utils.scope_ui import section_heading_with_scope
from utils.store import assembly_sections, audit_history, format_eastern_timestamp
from utils.table_ui import editable_table_footer, selectable_dataframe

SHAPE_TYPES: list[str] = [
    "rectangle",
    "square",
    "rounded_rect",
    "pill",
    "circle",
    "oval",
    "semicircle",
    "quarter_circle",
    "arc_line",
    "line",
    "triangle",
    "right_triangle",
    "diamond",
    "pentagon",
    "hexagon",
    "octagon",
    "trapezoid",
    "parallelogram",
    "l_shape",
    "t_shape",
    "u_shape",
    "cross",
    "star",
    "arrow_block",
    "x_box",
    "pitch_box",
    "conveyor",
    "conveyor_curve",
    "turntable",
    "area_header",
    "custom_polygon",
    "worker",
    "screen",
    "scanner",
    "computer_kiosk",
    "quality_gate",
    "rack",
    "supermarket",
    "pallet",
    "agv",
    "callout",
    "frame",
    "safety_zone",
    "dimension",
    "connector",
    "arrow",
    "text",
]

SHAPE_TYPE_LABELS: dict[str, str] = {
    "rectangle": "Rectangle / Cell",
    "square": "Square",
    "rounded_rect": "Rounded Rectangle",
    "pill": "Pill / Capsule",
    "circle": "Circle",
    "oval": "Oval / Ellipse",
    "semicircle": "Half-Circle (Semicircle)",
    "quarter_circle": "Quarter-Circle Wedge",
    "arc_line": "Half-Circle / Arc Line",
    "line": "Straight Line",
    "triangle": "Triangle",
    "right_triangle": "Right Triangle",
    "diamond": "Diamond",
    "pentagon": "Pentagon",
    "hexagon": "Hexagon",
    "octagon": "Octagon",
    "trapezoid": "Trapezoid",
    "parallelogram": "Parallelogram",
    "l_shape": "L-Shape Footprint",
    "t_shape": "T-Shape Footprint",
    "u_shape": "U-Shape Cell",
    "cross": "Cross / Plus",
    "star": "Star / Kaizen Burst",
    "arrow_block": "Block Arrow",
    "x_box": "Crossed Box (X-Footprint)",
    "pitch_box": "Workstation Pitch",
    "conveyor": "Straight Roller Conveyor",
    "conveyor_curve": "90° Curved Roller Turn",
    "turntable": "Turntable / Indexer",
    "area_header": "Area / Section Header Badge",
    "custom_polygon": "Custom / Welded Polygon",
    "worker": "Operator / Worker (Top-Down)",
    "screen": "HMI / Andon Display",
    "scanner": "Barcode / RFID Scanner",
    "computer_kiosk": "MES Terminal / Kiosk",
    "quality_gate": "Quality Gate / Inspection",
    "rack": "Lineside Flow Rack",
    "supermarket": "Kanban Supermarket",
    "pallet": "Pallet / Skid Drop",
    "agv": "AGV / Tugger Path Stop",
    "callout": "Engineering Callout",
    "frame": "Area Frame / Boundary",
    "safety_zone": "Safety / Keep-Out Zone",
    "dimension": "Dimension Line",
    "connector": "Smart Flow Connector",
    "arrow": "Arrow / Flow Direction",
    "text": "Text Box / Note",
}

SHAPE_TYPE_ICONS: dict[str, str] = {
    "rectangle": "⏹️",
    "square": "🟦",
    "rounded_rect": "▢",
    "pill": "💊",
    "circle": "⏺️",
    "oval": "🥚",
    "semicircle": "🌓",
    "quarter_circle": "🍕",
    "arc_line": "⌒",
    "line": "➖",
    "triangle": "🔺",
    "right_triangle": "📐",
    "diamond": "🔷",
    "pentagon": "⬠",
    "hexagon": "⬡",
    "octagon": "🛑",
    "trapezoid": "⏢",
    "parallelogram": "▱",
    "l_shape": "⌞",
    "t_shape": "⊤",
    "u_shape": "⊔",
    "cross": "➕",
    "star": "⭐",
    "arrow_block": "⏩",
    "x_box": "☒",
    "pitch_box": "🏭",
    "conveyor": "⛓️",
    "conveyor_curve": "↪️",
    "turntable": "🔄",
    "area_header": "🏷️",
    "custom_polygon": "⬟",
    "worker": "👷",
    "screen": "🖥️",
    "scanner": "📡",
    "computer_kiosk": "💻",
    "quality_gate": "✅",
    "rack": "🗄️",
    "supermarket": "🛒",
    "pallet": "📦",
    "agv": "🤖",
    "callout": "💬",
    "frame": "🖼️",
    "safety_zone": "⚠️",
    "dimension": "📏",
    "connector": "🔀",
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


_COLOR_PICKER_CSS = """
<style>
/* -------------------------------------------------------------------------
   Floating UI & Color Picker Stacking Fix
   Ensures color picker popovers float strictly above all Streamlit modals,
   dialogs, selectbox menus, container borders, and canvas elements.
   ------------------------------------------------------------------------- */
div[data-floating-ui-portal],
[data-floating-ui-portal] {
    position: relative !important;
    z-index: 99999999 !important;
    pointer-events: auto !important;
}

div[data-testid="stColorPickerPopover"],
div[data-baseweb="popover"],
div[data-baseweb="menu"],
div[role="dialog"][aria-label*="color picker"],
div[role="dialog"][aria-label*="Color picker"] {
    z-index: 99999999 !important;
    pointer-events: auto !important;
}

div[data-testid="stColorPickerPopover"] *,
div[role="dialog"][aria-label*="color picker"] *,
div[role="dialog"][aria-label*="Color picker"] * {
    pointer-events: auto !important;
}

button[data-testid="stColorPickerBlock"] {
    cursor: pointer !important;
}
</style>
"""

LAYOUT_SWATCH_PALETTE: dict[str, str] = {
    "🔵": "#1976d2",  # Workstation / Pitch Blue
    "🟠": "#f57c00",  # Conveyor / Material Flow Orange
    "🟢": "#388e3c",  # Staging / Buffer Green
    "🟣": "#7b1fa2",  # Walking Path / Aisle Purple
    "🔴": "#d32f2f",  # Quality / Defect / Hazard Red
    "🟡": "#fbc02d",  # Caution / Warning Yellow
    "🔘": "#607d8b",  # Machinery / Equipment Slate
    "⚫": "#212121",  # Dark Charcoal / Black
    "⚪": "#ffffff",  # White / Clear Fill
}


def _normalize_hex_color(val: Any, default: str = "#1976d2") -> str:
    """Safely validate and normalize a color string to a 7-character lowercase hex string (#rrggbb)."""
    if not val or not isinstance(val, str):
        return default
    s = val.strip()
    if not s.startswith("#"):
        s = "#" + s
    if len(s) == 4:
        s = "#" + "".join(c * 2 for c in s[1:])
    if len(s) == 7:
        try:
            int(s[1:], 16)
            return s.lower()
        except ValueError:
            pass
    return default


def _render_color_selector(
    label: str,
    current_color: str,
    key_prefix: str,
    help_text: str | None = None,
) -> str:
    """Render a robust color picker with 1-click quick-palette swatches and CSS stacking fix."""
    norm_current = _normalize_hex_color(current_color, default="#1976d2")
    picker_key = f"{key_prefix}_pick"
    pill_key = f"{key_prefix}_pill"
    ext_last_key = f"{key_prefix}_ext_last"

    # Synchronize if external caller passed a new color
    if st.session_state.get(ext_last_key) != norm_current:
        st.session_state[picker_key] = norm_current
        st.session_state[ext_last_key] = norm_current

    if picker_key not in st.session_state:
        st.session_state[picker_key] = norm_current

    # Check if a quick-palette pill was selected
    pill_val = st.session_state.get(pill_key)
    if pill_val and pill_val in LAYOUT_SWATCH_PALETTE:
        chosen_hex = LAYOUT_SWATCH_PALETTE[pill_val]
        st.session_state[picker_key] = chosen_hex
        st.session_state[ext_last_key] = chosen_hex
        st.session_state[pill_key] = None

    val = st.color_picker(
        label,
        key=picker_key,
        help=help_text,
    )
    st.pills(
        f"{label} Quick Palette",
        options=list(LAYOUT_SWATCH_PALETTE.keys()),
        key=pill_key,
        label_visibility="collapsed",
    )
    return _normalize_hex_color(val, default=norm_current)


def _px_to_units(px: float, px_per_in: float, unit: str) -> float:
    """Convert pixel dimension to real-world units based on scale."""
    if px_per_in <= 0:
        return 0.0
    inches = px / px_per_in
    unit_factor = float(UNIT_TO_INCHES.get(unit, 12.0))
    return inches / unit_factor


def _units_to_px(val: float, px_per_in: float, unit: str) -> float:
    """Convert real-world unit value to pixel dimension."""
    unit_factor = float(UNIT_TO_INCHES.get(unit, 12.0))
    inches = val * unit_factor
    return inches * px_per_in


def _calculate_shape_area(shape_type: str, w_units: float, h_units: float) -> float:
    """Calculate geometric area in square units."""
    stype = (shape_type or "").lower()
    if stype in {"circle", "turntable", "worker"}:
        r = min(w_units, h_units) / 2.0
        return math.pi * r * r
    elif stype == "oval":
        return math.pi * (w_units / 2.0) * (h_units / 2.0)
    elif stype == "triangle":
        return (w_units * h_units) / 2.0
    elif stype in {"hexagon", "quality_gate"}:
        r = min(w_units, h_units) / 2.0
        return (3.0 * math.sqrt(3.0) / 2.0) * r * r
    elif stype in {"connector", "arrow", "dimension"}:
        return 0.0
    return w_units * h_units


def _format_shape_dim(px: float, px_per_in: float, unit: str) -> str:
    """Format dimension to 1-2 decimal places."""
    val = _px_to_units(px, px_per_in, unit)
    return f"{val:.1f} {unit}" if val >= 10 else f"{val:.2f} {unit}"


@st.dialog("Create new Pin Map / floor plan layout", width="medium")
def _create_layout_dialog(project_id: str, editor_name: str) -> None:
    st.write("Add a new named 2D plant floor plan & Pin Map workspace for this project.")
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

    init_blank = st.checkbox(
        "Initialize immediately with a Blank Scaled Canvas (no CAD image needed)",
        value=True,
        key="new_layout_init_blank",
        help="Creates Revision 1 immediately as a high-resolution scaled engineering grid so you can start placing pitches, workers, screens, and flow arrows right away.",
    )
    blank_w, blank_h, blank_unit = 200.0, 100.0, "feet"
    if init_blank:
        bc1, bc2, bc3 = st.columns(3)
        with bc1:
            blank_w = st.number_input("Canvas Width", min_value=1.0, value=200.0, step=10.0, key="new_layout_blank_w")
        with bc2:
            blank_h = st.number_input("Canvas Height", min_value=1.0, value=100.0, step=10.0, key="new_layout_blank_h")
        with bc3:
            blank_unit = st.selectbox("Scale Unit", LAYOUT_UNITS, index=0, key="new_layout_blank_unit")

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
                st.session_state["layout_plan_selector"] = created["id"]
                st.session_state["_last_seen_active_layout_id"] = created["id"]
                if init_blank:
                    rev = create_blank_scaled_revision(
                        project_id=project_id,
                        layout_id=str(created["id"]),
                        width_value=blank_w,
                        height_value=blank_h,
                        unit=blank_unit,
                        notes="Initial scaled engineering canvas",
                        editor_name=editor_name,
                    )
                    st.session_state["active_revision_id"] = rev["id"]
                    st.session_state["layout_revision_selector"] = rev["id"]
                    st.session_state["_last_seen_active_rev_id"] = rev["id"]
                else:
                    st.session_state.pop("active_revision_id", None)
                    st.session_state.pop("layout_revision_selector", None)
                    st.session_state.pop("_last_seen_active_rev_id", None)
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
    current_draft_shapes: list[dict[str, Any]] | None = None,
) -> None:
    st.write(
        f"Create a new scaled canvas or upload/paste an updated drawing revision for **{layout['name']}**."
    )
    st.caption(
        "The calibrated physical scale determines footprint dimensions, gridlines, rulers, and pitch scaling."
    )

    input_mode = st.radio(
        "Drawing source",
        [
            "Blank scaled canvas (no image required)",
            "Upload drawing file",
            "Paste screenshot from clipboard",
        ],
        horizontal=True,
        key="rev_image_source_mode",
    )

    is_blank_canvas = input_mode == "Blank scaled canvas (no image required)"
    image_file = None
    if input_mode == "Upload drawing file":
        image_file = st.file_uploader(
            "Upload floor plan drawing (PDF, DXF, PNG, JPG, WEBP)",
            type=["pdf", "dxf", "png", "jpg", "jpeg", "webp"],
            key="rev_file_upload",
            help="Upload an architectural floor plan drawing. Vector PDFs and CAD DXFs will be automatically converted to high-resolution layout images.",
        )
    elif input_mode == "Paste screenshot from clipboard":
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
                "Clipboard paste component unavailable; please use Upload drawing file instead."
            )
    else:
        st.info(
            ":material/grid_4x4: Creates a clean, high-resolution architectural grid scaled to your exact real-world dimensions—ideal for Lucidchart-style top-down line layout when a CAD image is not needed."
        )

    default_unit = latest_rev["unit"] if latest_rev else "feet"
    default_w = float(latest_rev["width_value"]) if latest_rev else 200.0
    default_h = float(latest_rev["height_value"]) if latest_rev else 100.0

    selected_page = 1
    rotation_angle = 0
    filename = ""
    crop_l = 0.0
    crop_r = 0.0
    crop_t = 0.0
    crop_b = 0.0
    preview_img = None
    uncropped_img = None
    preview_error = None

    if image_file and not is_blank_canvas:
        filename = str(getattr(image_file, "name", "screenshot.png"))
        suffix = Path(filename).suffix.lower()

        # Multi-page PDF sheet selection
        if suffix == ".pdf":
            try:
                pdf_bytes = (
                    image_file.getvalue()
                    if hasattr(image_file, "getvalue")
                    else image_file.read()
                )
                if hasattr(image_file, "seek"):
                    image_file.seek(0)
                page_count = get_pdf_page_count(pdf_bytes)
                if page_count > 1:
                    selected_page = st.number_input(
                        f"Select PDF Sheet / Page (1 to {page_count})",
                        min_value=1,
                        max_value=page_count,
                        value=1,
                        step=1,
                        key="rev_pdf_page_selector",
                        help="Multi-sheet CAD drawings: choose which sheet/layout to import.",
                    )
            except Exception:
                selected_page = 1

        # Orientation / Rotation Controls
        c_rot, c_swap = st.columns([3, 2])
        with c_rot:
            orientation_labels = {
                0: "0° (Original orientation)",
                90: "90° Clockwise",
                180: "180° (Upside down)",
                270: "270° Clockwise (90° CCW)",
            }
            rotation_angle = st.selectbox(
                "Drawing orientation",
                options=[0, 90, 180, 270],
                format_func=lambda deg: orientation_labels[deg],
                key="rev_rotation_angle",
                help="Adjust orientation upon import if drawing was scanned or exported in landscape/portrait.",
            )
        with c_swap:
            st.write("")
            st.write("")
            if st.button(
                "⇄ Swap Width & Height",
                key="btn_swap_scale_wh",
                help="Swap physical width and height values (convenient when rotating 90° or 270°).",
            ):
                current_w = float(st.session_state.get("rev_scale_w", default_w))
                current_h = float(st.session_state.get("rev_scale_h", default_h))
                st.session_state["rev_scale_w"] = current_h
                st.session_state["rev_scale_h"] = current_w
                st.rerun()

        # Load oriented base image to support cropping and preview
        if image_file:
            try:
                uncropped_img = load_and_orient_layout_preview(
                    image_file,
                    rotation_angle=rotation_angle,
                    pdf_page=selected_page,
                )
            except Exception as exc:
                preview_error = str(exc)

        # Margin Cropping & Trim Section
        st.markdown("##### Crop & Trim Margins (Remove Excess Whitespace)")
        st.caption(
            "Trim outer margins, title blocks, or blank borders so your physical dimensions scale strictly to the factory floor plan."
        )

        c_crop_actions, c_crop_stat = st.columns([3, 4], vertical_alignment="center")
        with c_crop_actions:
            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                if st.button(
                    "🪄 Auto-trim whitespace",
                    key="btn_auto_trim_margins",
                    help="Automatically detect and trim outer white borders around the drawing.",
                    width="stretch",
                ):
                    if uncropped_img:
                        bbox = auto_detect_whitespace_crop(uncropped_img)
                        st.session_state["rev_crop_left"] = round((bbox[0] / uncropped_img.width) * 100.0, 1)
                        st.session_state["rev_crop_top"] = round((bbox[1] / uncropped_img.height) * 100.0, 1)
                        st.session_state["rev_crop_right"] = round(((uncropped_img.width - bbox[2]) / uncropped_img.width) * 100.0, 1)
                        st.session_state["rev_crop_bottom"] = round(((uncropped_img.height - bbox[3]) / uncropped_img.height) * 100.0, 1)
                        st.rerun()
            with c_btn2:
                if st.button(
                    "↺ Reset crop",
                    key="btn_reset_crop_margins",
                    help="Reset all crop margins back to 0% (restore full original drawing).",
                    width="stretch",
                ):
                    st.session_state["rev_crop_left"] = 0.0
                    st.session_state["rev_crop_top"] = 0.0
                    st.session_state["rev_crop_right"] = 0.0
                    st.session_state["rev_crop_bottom"] = 0.0
                    st.rerun()

        crop_l = float(st.session_state.get("rev_crop_left", 0.0))
        crop_r = float(st.session_state.get("rev_crop_right", 0.0))
        crop_t = float(st.session_state.get("rev_crop_top", 0.0))
        crop_b = float(st.session_state.get("rev_crop_bottom", 0.0))

        c_cr1, c_cr2, c_cr3, c_cr4 = st.columns(4)
        with c_cr1:
            crop_l = st.slider("Crop Left (%)", min_value=0.0, max_value=45.0, value=crop_l, step=0.5, key="rev_crop_left")
        with c_cr2:
            crop_r = st.slider("Crop Right (%)", min_value=0.0, max_value=45.0, value=crop_r, step=0.5, key="rev_crop_right")
        with c_cr3:
            crop_t = st.slider("Crop Top (%)", min_value=0.0, max_value=45.0, value=crop_t, step=0.5, key="rev_crop_top")
        with c_cr4:
            crop_b = st.slider("Crop Bottom (%)", min_value=0.0, max_value=45.0, value=crop_b, step=0.5, key="rev_crop_bottom")

        preview_img = apply_image_crop(uncropped_img, crop_l, crop_t, crop_r, crop_b) if uncropped_img else None

    st.markdown("##### Calibrate Physical Scale")
    st.caption(
        "Specify the real-world distance across the drawing or canvas. "
        "Physical Width applies horizontally (Left ↔ Right), and Physical Height / Length applies vertically (Top ↕ Bottom)."
    )

    unit_idx = (
        IMPERIAL_LAYOUT_UNITS.index(default_unit) if default_unit in IMPERIAL_LAYOUT_UNITS else 0
    )

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        width_val = st.number_input(
            "Physical Width (Horizontal ↔)",
            min_value=0.01,
            value=default_w,
            step=1.0,
            format="%.2f",
            key="rev_scale_w",
            help="Real-world distance along the horizontal (left-to-right) axis of the drawing.",
        )
    with c2:
        height_val = st.number_input(
            "Physical Height / Length (Vertical ↕)",
            min_value=0.01,
            value=default_h,
            step=1.0,
            format="%.2f",
            key="rev_scale_h",
            help="Real-world distance along the vertical (top-to-bottom) axis of the drawing.",
        )
    with c3:
        unit = st.selectbox(
            "Scale Unit",
            IMPERIAL_LAYOUT_UNITS,
            index=unit_idx,
            key="rev_scale_unit",
        )

    copy_from_rev_id = None
    copy_shapes_count = 0
    target_copy_rev = None
    all_revisions = list_layout_revisions(str(layout["id"]))
    if all_revisions:
        rev_options: dict[str, str] = {}
        for r in all_revisions:
            s_count = int(r.get("shape_count", 0))
            rev_date = format_eastern_timestamp(r.get("created_at"), "%Y-%m-%d")[:10]
            rev_options[r["id"]] = f"Rev {r['revision_number']} ({s_count} shape(s) — {rev_date})"
        rev_options["none"] = "None (start with a blank layout)"

        default_copy_id = "none"
        if latest_rev and latest_rev.get("id") in rev_options:
            default_copy_id = latest_rev["id"]
        else:
            rev_with_shapes = next((r["id"] for r in all_revisions if r.get("shape_count", 0) > 0), None)
            default_copy_id = rev_with_shapes or all_revisions[0]["id"]

        selected_copy_choice = st.selectbox(
            "Copy forward shapes / annotations from",
            options=list(rev_options.keys()),
            format_func=lambda rid: rev_options[rid],
            index=list(rev_options.keys()).index(default_copy_id) if default_copy_id in rev_options else 0,
            key="rev_copy_shapes_selector",
            help="Copy equipment footprints, workstation pitches, and annotations from an earlier revision. Shapes are automatically scaled and positioned in the exact same spots on the new drawing.",
        )
        if selected_copy_choice != "none":
            copy_from_rev_id = selected_copy_choice
            target_copy_rev = next((r for r in all_revisions if r["id"] == copy_from_rev_id), None)
            copy_shapes_count = int(target_copy_rev.get("shape_count", 0)) if target_copy_rev else 0
            if copy_shapes_count > 0:
                st.info(
                    f":material/content_copy: **{copy_shapes_count} shape annotation(s)** from Rev {target_copy_rev['revision_number']} "
                    f"will be imported into the exact same spots on this new drawing. "
                    f"You can then edit, resize, or move them without starting from scratch."
                )
            else:
                st.caption(f"Rev {target_copy_rev['revision_number']} currently has no shapes placed on it.")

    notes = st.text_input(
        "Revision notes / CAD version (optional)",
        placeholder="e.g., Updated line layout from CAD team 2026-09",
        key="rev_notes",
    )

    if not is_blank_canvas:
        # Live Preview before Save
        st.markdown("##### Drawing Preview & Calibration Guides")
        if preview_img:
            rev_target_num = (latest_rev["revision_number"] + 1) if latest_rev else 1
            st.caption(
                f"Review the oriented and cropped drawing that will be saved to Revision {rev_target_num}."
            )
            with st.container(border=True):
                # Dimension Orientation Cards
                st.markdown(
                    f"""
                    <div style="display:flex; gap:12px; margin-bottom:12px;">
                        <div style="flex:1; background:#e3f2fd; border-left:4px solid #1976d2; padding:8px 12px; border-radius:4px;">
                            <div style="font-size:0.75rem; font-weight:600; color:#0d47a1; text-transform:uppercase; letter-spacing:0.5px;">↔ Horizontal Dimension (Width)</div>
                            <div style="font-size:1.05rem; font-weight:700; color:#1565c0;">{width_val:g} {unit}</div>
                            <div style="font-size:0.8rem; color:#546e7a;">Mapped across <b>{preview_img.width} px</b> horizontally</div>
                        </div>
                        <div style="flex:1; background:#f3e5f5; border-left:4px solid #7b1fa2; padding:8px 12px; border-radius:4px;">
                            <div style="font-size:0.75rem; font-weight:600; color:#4a148c; text-transform:uppercase; letter-spacing:0.5px;">↕ Vertical Dimension (Height / Length)</div>
                            <div style="font-size:1.05rem; font-weight:700; color:#6a1b9a;">{height_val:g} {unit}</div>
                            <div style="font-size:0.8rem; color:#546e7a;">Mapped across <b>{preview_img.height} px</b> vertically</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                is_cropped = (crop_l > 0 or crop_r > 0 or crop_t > 0 or crop_b > 0)
                if is_cropped and uncropped_img:
                    st.caption(
                        f":material/crop: **Cropped drawing:** `{preview_img.width} × {preview_img.height} px` "
                        f"(trimmed {crop_l}% left, {crop_r}% right, {crop_t}% top, {crop_b}% bottom from original `{uncropped_img.width} × {uncropped_img.height} px`). "
                        f"Scale: **{(preview_img.width / to_canonical_inches(width_val, unit) * 12.0):.1f} px/ft**."
                    )

                if copy_from_rev_id and target_copy_rev and copy_shapes_count > 0:
                    st.caption(
                        f":material/check: Will import and align **{copy_shapes_count} shape(s)** from Rev {target_copy_rev['revision_number']} in the exact spots on this drawing."
                    )

                show_guides = st.checkbox(
                    "Show dimension guides on preview (Width ↔ on top, Height/Length ↕ on left)",
                    value=bool(st.session_state.get("rev_show_dim_guides", True)),
                    key="rev_show_dim_guides",
                    help="Draws architectural dimension markers on the preview frame to visually verify width and length orientation.",
                )

                if show_guides:
                    display_img = annotate_preview_with_dimensions(
                        preview_img,
                        width_val=width_val,
                        height_val=height_val,
                        unit=unit,
                    )
                else:
                    display_img = preview_img

                st.image(
                    display_img,
                    caption=f"Preview: {filename or 'Clipboard'} ({preview_img.width} × {preview_img.height} px, {rotation_angle}° orientation)",
                    width="stretch",
                )
        elif preview_error:
            st.warning(f"Could not load drawing preview: {preview_error}")
        else:
            st.info("Upload or paste a drawing above to preview it in its correct orientation and crop here before saving.")

    rev_cad_file = None
    rev_cad_url = ""
    if not is_blank_canvas:
        with st.expander("Native AutoCAD Drawing (.dwg / .dxf) or CAD Web Link (Optional)", expanded=False):
            st.caption(
                "Attach the original native CAD file (.dwg or .dxf up to 100 MB) or provide a corporate CAD web link "
                "(Autodesk Vault, BIM 360, SharePoint) for download by engineering collaborators."
            )
            rev_cad_file = st.file_uploader(
                "Attach AutoCAD drawing file (.dwg, .dxf - max 100 MB)",
                type=["dwg", "dxf"],
                key="rev_cad_file_upload",
                help="Original AutoCAD drawing file. Max 100 MB per file.",
            )
            rev_cad_url = st.text_input(
                "Or CAD Web Link (Autodesk Vault / Cloud / SharePoint)",
                key="rev_cad_url_input",
                placeholder="https://autodesk360.com/... or https://company.sharepoint.com/...",
                help="Direct web link to open the drawing in Autodesk Vault, Autodesk Construction Cloud, or corporate PLM.",
            )

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Cancel", width="stretch", key="cancel_new_rev"):
            st.session_state.pop("rev_crop_left", None)
            st.session_state.pop("rev_crop_top", None)
            st.session_state.pop("rev_crop_right", None)
            st.session_state.pop("rev_crop_bottom", None)
            st.session_state.pop("rev_show_dim_guides", None)
            st.rerun()
    with col2:
        if st.button(
            "Save revision",
            type="primary",
            width="stretch",
            key="submit_new_rev",
        ):
            if not is_blank_canvas and not image_file:
                st.error("Please provide a drawing or image by upload or paste, or choose Blank scaled canvas.")
                return
            if not editor_name.strip():
                st.error("Please specify a Current editor attribution.")
                return
            try:
                src_shapes = None
                if current_draft_shapes and latest_rev and copy_from_rev_id == latest_rev.get("id"):
                    src_shapes = current_draft_shapes

                if is_blank_canvas:
                    new_rev = create_blank_scaled_revision(
                        project_id=project_id,
                        layout_id=str(layout["id"]),
                        width_value=width_val,
                        height_value=height_val,
                        unit=unit,
                        notes=notes or "Scaled engineering canvas",
                        editor_name=editor_name,
                        copy_from_revision_id=copy_from_rev_id,
                        source_shapes=src_shapes,
                    )
                else:
                    new_rev = create_layout_revision(
                        project_id=project_id,
                        layout_id=str(layout["id"]),
                        image_file=image_file,
                        width_value=width_val,
                        height_value=height_val,
                        unit=unit,
                        notes=notes,
                        editor_name=editor_name,
                        copy_from_revision_id=copy_from_rev_id,
                        rotation_angle=rotation_angle,
                        pdf_page=selected_page,
                        source_shapes=src_shapes,
                        crop_left_pct=crop_l,
                        crop_top_pct=crop_t,
                        crop_right_pct=crop_r,
                        crop_bottom_pct=crop_b,
                        cad_file=rev_cad_file,
                        cad_web_url=rev_cad_url,
                    )
                st.session_state.pop("rev_crop_left", None)
                st.session_state.pop("rev_crop_top", None)
                st.session_state.pop("rev_crop_right", None)
                st.session_state.pop("rev_crop_bottom", None)
                st.session_state.pop("rev_show_dim_guides", None)

                st.session_state["active_revision_id"] = new_rev["id"]
                st.session_state["layout_revision_selector"] = new_rev["id"]
                st.session_state["_last_seen_active_rev_id"] = new_rev["id"]
                st.toast(
                    f"Created Revision {new_rev['revision_number']} for '{layout['name']}'",
                    icon=":material/check_circle:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


@st.dialog("Import shapes from previous revision", width="medium")
def _import_shapes_dialog(
    project_id: str,
    layout: dict[str, Any],
    active_rev: dict[str, Any],
    other_revs: list[dict[str, Any]],
    editor_name: str,
) -> None:
    st.write(
        f"Import existing equipment, pitches, and annotations into **Rev {active_rev['revision_number']}**."
    )
    st.caption(
        "Shapes will be automatically scaled to align with this revision's drawing resolution "
        "so they land in the exact same spots and can be edited directly."
    )

    rev_choices = {
        r["id"]: f"Rev {r['revision_number']} ({r.get('shape_count', 0)} shapes — {format_eastern_timestamp(r.get('created_at'), '%Y-%m-%d')[:10]})"
        for r in other_revs
    }
    selected_source_id = st.selectbox(
        "Select source revision to import from",
        options=list(rev_choices.keys()),
        format_func=lambda rid: rev_choices[rid],
        key="dlg_import_shapes_source",
    )

    curr_shapes = list_layout_shapes(str(active_rev["id"]))
    replace_existing = False
    if curr_shapes:
        replace_existing = st.checkbox(
            f"Replace existing {len(curr_shapes)} shape(s) currently on Rev {active_rev['revision_number']}",
            value=True,
            key="dlg_import_shapes_replace",
            help="Check to clear current shapes before importing. Uncheck to append imported shapes.",
        )

    st.info(
        ":material/info: After importing, you can click, drag, resize, and edit the annotations right on the canvas."
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Cancel", width="stretch", key="btn_cancel_import_dlg"):
            st.rerun()
    with col2:
        if st.button("Import & align shapes", type="primary", width="stretch", key="btn_confirm_import_dlg"):
            if not editor_name:
                st.error("Please enter Current editor attribution.")
                return
            try:
                count = import_shapes_from_revision(
                    project_id=project_id,
                    target_revision_id=str(active_rev["id"]),
                    source_revision_id=selected_source_id,
                    editor_name=editor_name,
                    replace_existing=replace_existing,
                )
                st.session_state.pop(f"layout_shapes_draft_{active_rev['id']}", None)
                st.session_state.pop(f"layout_shapes_has_unsaved_{active_rev['id']}", None)
                st.session_state.pop(f"layout_selected_shape_{active_rev['id']}", None)
                st.toast(
                    f"Successfully imported {count} shape(s) into Rev {active_rev['revision_number']}!",
                    icon=":material/check_circle:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


@st.dialog("Confirm delete layout", width="medium", dismissible=False)
def _delete_layout_dialog(
    project_id: str, layout: dict[str, Any], editor_name: str
) -> None:
    impact = layout_deletion_impact(project_id, str(layout["id"]))
    st.write(
        f"Are you sure you want to permanently delete **{layout['name']}**?"
    )
    rev_count = impact.get("revision_count", impact.get("revisions_count", 0))
    s_count = impact.get("shape_count", impact.get("shapes_count", 0))
    img_count = impact.get("image_count", impact.get("images_count", 0))
    st.error(
        f"**Downstream Impact:**\n"
        f"- **{rev_count}** revision(s) will be deleted\n"
        f"- **{s_count}** Pin Map shape(s) will be deleted\n"
        f"- **{img_count}** uploaded floorplan / CAD file(s) will be permanently purged"
    )
    st.caption(
        "Yamazumi pitches, work elements, Process at a Glance steps, and Equipment Catalog records linked to shapes are preserved. "
        "This action is immediate and cannot be undone."
    )

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
                st.session_state.pop("layout_plan_selector", None)
                st.session_state.pop("_last_seen_active_layout_id", None)
                st.session_state.pop("active_revision_id", None)
                st.session_state.pop("layout_revision_selector", None)
                st.session_state.pop("_last_seen_active_rev_id", None)
                st.toast(
                    f"Deleted layout '{layout['name']}'",
                    icon=":material/delete_forever:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


@st.dialog("Confirm delete revision", width="medium", dismissible=False)
def _delete_revision_dialog(
    project_id: str,
    layout_name: str,
    revision: dict[str, Any],
    editor_name: str,
) -> None:
    rev_num = revision.get("revision_number", 1)
    s_count = revision.get("shape_count")
    if s_count is None:
        try:
            s_count = len(list_layout_shapes(str(revision["id"])))
        except Exception:
            s_count = 0

    st.write(
        f"Delete **Revision {rev_num}** of **{layout_name}**?"
    )
    st.warning(
        f"Downstream effects: This revision has **{s_count}** Pin Map shape annotation(s). "
        f"Deleting it permanently removes this revision, its shapes, and its uploaded floorplan / CAD file. "
        f"Other revisions of this layout, Yamazumi pitches, and Equipment Catalog records remain intact."
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
                st.session_state.pop("layout_revision_selector", None)
                st.session_state.pop("_last_seen_active_rev_id", None)
                st.toast(
                    f"Deleted Revision {revision['revision_number']}",
                    icon=":material/delete:",
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


@st.dialog("Manage Native AutoCAD Drawing & CAD Links", width="medium")
def _attach_cad_dialog(
    project_id: str,
    layout_name: str,
    revision: dict[str, Any],
    editor_name: str,
) -> None:
    rev_num = revision.get("revision_number", 1)
    cad_name = str(revision.get("cad_file_name") or "").strip()
    cad_path = str(revision.get("cad_file_path") or "").strip()
    cad_url = str(revision.get("cad_web_url") or "").strip()
    cad_size = int(revision.get("cad_file_size_bytes") or 0)
    has_file = bool(cad_path and Path(cad_path).exists())

    st.write(f"Manage native AutoCAD engineering drawings for **{layout_name} — Rev {rev_num}**.")

    if has_file:
        size_mb = cad_size / (1024 * 1024)
        st.success(f":material/architecture: **Attached AutoCAD File:** `{cad_name}` ({size_mb:.1f} MB)")
    if cad_url:
        st.info(f":material/link: **Attached CAD Web Link:** {cad_url}")

    st.markdown("---")
    st.markdown("##### Upload New or Replacement AutoCAD Drawing")
    st.caption("Supported formats: `.dwg`, `.dxf`. Maximum file size: 100 MB.")
    new_cad_file = st.file_uploader(
        "AutoCAD Drawing (.dwg, .dxf)",
        type=["dwg", "dxf"],
        key=f"dialog_cad_upload_{revision['id']}",
        help="Upload native AutoCAD drawing file up to 100 MB.",
    )

    st.markdown("##### Or CAD Web Link (Cloud / Vault / PLM)")
    new_cad_url = st.text_input(
        "Corporate CAD URL",
        value=cad_url,
        key=f"dialog_cad_url_{revision['id']}",
        placeholder="https://autodesk360.com/... or https://company.sharepoint.com/...",
        help="Direct web link to open the drawing in Autodesk Vault, Autodesk Construction Cloud, or corporate PLM.",
    )

    col_save, col_detach, col_cancel = st.columns([1, 1, 1])
    with col_save:
        if st.button("Save CAD source", type="primary", width="stretch", key=f"btn_save_cad_{revision['id']}"):
            if not editor_name.strip():
                st.error("Please enter Current editor attribution.")
                return
            if not new_cad_file and not new_cad_url.strip():
                st.error("Please upload an AutoCAD drawing file or provide a CAD Web Link.")
                return
            try:
                attach_layout_revision_cad(
                    project_id=project_id,
                    revision_id=str(revision["id"]),
                    cad_file=new_cad_file,
                    cad_web_url=new_cad_url,
                    editor_name=editor_name,
                )
                st.toast("AutoCAD source updated successfully!", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with col_detach:
        if (has_file or cad_url) and st.button("Detach CAD", width="stretch", key=f"destructive_btn_detach_cad_{revision['id']}"):
            if not editor_name.strip():
                st.error("Please enter Current editor attribution.")
                return
            st.session_state["_open_pin_map_dialog"] = "confirm_detach_cad"
            st.rerun()

    with col_cancel:
        if st.button("Close", width="stretch", key=f"btn_close_cad_{revision['id']}"):
            st.rerun()


@st.dialog("Detach CAD Source?", width="medium", dismissible=False)
def _confirm_detach_cad_dialog(
    project_id: str,
    layout_name: str,
    revision: dict[str, Any],
    editor_name: str,
) -> None:
    rev_num = revision.get("revision_number", 1)
    cad_name = str(revision.get("cad_file_name") or "").strip()
    cad_url = str(revision.get("cad_web_url") or "").strip()
    st.warning(f"Detach the AutoCAD source from **{layout_name} — Rev {rev_num}**?")
    st.caption(
        f"Downstream effects: This removes the attached AutoCAD drawing file (`{cad_name or 'None'}`) and CAD web link (`{cad_url or 'None'}`) from this revision. "
        "The rendered floorplan image and all placed Pin Map shapes, workstation pitches, and equipment placements remain intact."
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Cancel", width="stretch", key=f"cancel_detach_cad_{revision['id']}"):
            st.session_state["_open_pin_map_dialog"] = "attach_cad"
            st.rerun()
    with c2:
        if st.button(
            "Detach CAD",
            type="primary",
            icon=":material/link_off:",
            width="stretch",
            key=f"destructive_confirm_detach_cad_{revision['id']}",
        ):
            try:
                remove_layout_revision_cad(
                    project_id=project_id,
                    revision_id=str(revision["id"]),
                    editor_name=editor_name,
                )
                st.toast("CAD source detached.", icon=":material/check_circle:")
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


def _render_scale_bar_html(px_per_ft: float, unit: str) -> str:
    """Render an interactive visual scale reference bar in HTML."""
    if px_per_ft <= 0:
        return ""

    if unit == "feet":
        candidate_steps = [1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0]
        step_units = 50.0
        for s in candidate_steps:
            if s * px_per_ft >= 50:
                step_units = s
                break
        bar_px = px_per_ft * step_units
        unit_text = f"{step_units:g} ft"
    elif unit == "inches":
        px_per_in = px_per_ft / 12.0
        candidate_steps = [1.0, 6.0, 12.0, 24.0, 48.0, 120.0, 240.0, 600.0]
        step_units = 12.0
        for s in candidate_steps:
            if s * px_per_in >= 50:
                step_units = s
                break
        bar_px = px_per_in * step_units
        unit_text = f"{step_units:g} in"
    elif unit == "yards":
        px_per_yd = px_per_ft * 3.0
        candidate_steps = [1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0]
        step_units = 5.0
        for s in candidate_steps:
            if s * px_per_yd >= 50:
                step_units = s
                break
        bar_px = px_per_yd * step_units
        unit_text = f"{step_units:g} yd"
    else:
        step_units = 1.0
        bar_px = max(20.0, px_per_ft * step_units)
        unit_text = f"{step_units:g} {unit}"

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


def _sync_draft_layers_to_db(
    project_id: str,
    revision_id: str,
    draft_layers: list[dict[str, Any]],
    editor_name: str,
) -> dict[str, str]:
    """Synchronize client-side layer edits (add/rename/visibility/lock/opacity/color/order/delete) to SQLite.
    Returns a mapping from any temporary client layer ID to its persisted DB layer ID.
    """
    existing = list_layout_layers(revision_id)
    existing_by_id = {str(l["id"]): l for l in existing}
    id_map: dict[str, str] = {}

    draft_ids = {str(dl.get("id", "")) for dl in draft_layers if dl.get("id")}

    # First create or update layers in draft_layers
    ordered_real_ids: list[str] = []
    for idx, dl in enumerate(draft_layers):
        raw_id = str(dl.get("id") or "")
        name = str(dl.get("name") or f"Layer {idx + 1}").strip()
        color = str(dl.get("color") or "#1976D2").strip()
        visible = bool(dl.get("visible", True))
        locked = bool(dl.get("locked", False))
        opacity = float(dl.get("opacity", 1.0))
        target_z = int(dl.get("z_index", (idx + 1) * 10))

        if raw_id in existing_by_id:
            ex = existing_by_id[raw_id]
            changed = (
                str(ex.get("name", "")) != name
                or str(ex.get("color", "")) != color
                or bool(ex.get("visible", True)) != visible
                or bool(ex.get("locked", False)) != locked
                or abs(float(ex.get("opacity", 1.0)) - opacity) > 1e-3
                or int(ex.get("z_index", target_z)) != target_z
            )
            if changed:
                update_layout_layer(
                    project_id=project_id,
                    layer_id=raw_id,
                    editor_name=editor_name,
                    name=name,
                    visible=visible,
                    locked=locked,
                    opacity=opacity,
                    color=color,
                    z_index=target_z,
                )
            id_map[raw_id] = raw_id
            ordered_real_ids.append(raw_id)
        else:
            created = create_layout_layer(
                project_id=project_id,
                revision_id=revision_id,
                name=name,
                color=color,
                editor_name=editor_name,
            )
            real_id = str(created["id"])
            if (
                not visible
                or locked
                or abs(opacity - 1.0) > 1e-3
                or target_z != int(created.get("z_index", target_z))
            ):
                update_layout_layer(
                    project_id=project_id,
                    layer_id=real_id,
                    editor_name=editor_name,
                    visible=visible,
                    locked=locked,
                    opacity=opacity,
                    z_index=target_z,
                )
            if raw_id:
                id_map[raw_id] = real_id
            ordered_real_ids.append(real_id)

    # Delete any removed layers (keeping at least 1 layer)
    remaining_existing = [lid for lid in existing_by_id if lid not in draft_ids]
    if len(ordered_real_ids) >= 1:
        for rem_id in remaining_existing:
            try:
                delete_layout_layer(project_id, rem_id, editor_name)
            except ValueError:
                pass

    return id_map


def render_layouts_tab(
    project_id: str,
    editor_name: str,
    scenario_id: str | None = None,
    embedded_in_pin_map: bool = False,
) -> None:
    """Render the clean, zero-clutter Lucidchart-style Pin Map workspace."""
    effective_scenario_id = scenario_id or st.session_state.get("scenario_id")
    effective_editor = str(editor_name or "").strip() or "Workspace"

    # Ensure at least one layout page ("Page 1") and one scaled revision exist automatically
    layouts = list_layouts(project_id)
    if not layouts:
        default_layout, default_rev = ensure_default_pin_map_page(project_id, effective_editor)
        layouts = list_layouts(project_id)
        st.session_state["active_layout_id"] = str(default_layout["id"])
        st.session_state["active_revision_id"] = str(default_rev["id"])

    layout_by_id = {str(l["id"]): l for l in layouts}
    active_layout_id = str(st.session_state.get("active_layout_id") or "")
    if active_layout_id not in layout_by_id:
        active_layout_id = str(layouts[0]["id"])
        st.session_state["active_layout_id"] = active_layout_id

    current_layout = layout_by_id[active_layout_id]
    revisions = list_layout_revisions(active_layout_id)
    if not revisions:
        created_rev = create_blank_scaled_revision(
            project_id=project_id,
            layout_id=active_layout_id,
            width_value=200.0,
            height_value=100.0,
            unit="feet",
            notes="Blank scaled grid canvas",
            editor_name=effective_editor,
        )
        revisions = list_layout_revisions(active_layout_id)
        st.session_state["active_revision_id"] = str(created_rev["id"])

    rev_by_id = {str(r["id"]): r for r in revisions}
    active_rev_id = str(st.session_state.get("active_revision_id") or "")
    if active_rev_id not in rev_by_id:
        active_rev_id = str(revisions[0]["id"])
        st.session_state["active_revision_id"] = active_rev_id

    active_rev = rev_by_id[active_rev_id]
    rev_id = str(active_rev["id"])
    st.session_state["layout_plan_selector"] = active_layout_id
    st.session_state["layout_revision_selector"] = rev_id

    unit = str(active_rev.get("unit") or "feet")

    draft_shapes_key = f"layout_shapes_draft_{rev_id}"
    draft_layers_key = f"layout_layers_draft_{rev_id}"
    has_unsaved_shapes_key = f"layout_shapes_has_unsaved_{rev_id}"
    selected_shape_id_key = f"layout_selected_shape_{rev_id}"
    last_commit_sig_key = f"layout_last_commit_sig_{rev_id}"
    canvas_key = f"layout_canvas_{rev_id}"

    persisted_layers = [dict(l) for l in list_layout_layers(rev_id)]
    persisted_shapes = [dict(s) for s in list_layout_shapes(rev_id)]

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
            st.session_state[selected_shape_id_key] = s_id

    def handle_canvas_commit() -> bool:
        state = st.session_state.get(canvas_key)
        trigger = getattr(state, "canvas_commit", None) if state is not None else None
        if not trigger and isinstance(state, dict):
            trigger = state.get("canvas_commit")
        if not trigger or not isinstance(trigger, dict):
            return False

        action = str(trigger.get("action") or "save")
        bg_raw = str(trigger.get("background_data_url") or "")
        bg_digest = hashlib.sha256(bg_raw.encode("utf-8")).hexdigest() if bg_raw else ""
        sig_payload = json.dumps(
            {
                "cid": trigger.get("commit_id"),
                "a": action,
                "shapes": trigger.get("shapes"),
                "layers": trigger.get("layers"),
                "sel": trigger.get("selected_shape_id"),
                "cal": trigger.get("scale_calibration"),
                "su": trigger.get("scale_update"),
                "wv": trigger.get("width_value"),
                "hv": trigger.get("height_value"),
                "u": trigger.get("unit"),
                "pxd": trigger.get("pixel_distance"),
                "phd": trigger.get("physical_distance") or trigger.get("real_distance"),
                "pt": trigger.get("page_title") or trigger.get("page_name"),
                "pid": trigger.get("target_page_id") or trigger.get("page_id"),
                "cs": trigger.get("custom_stencil"),
                "csid": trigger.get("stencil_id"),
                "bg": bg_digest,
            },
            sort_keys=True,
            default=str,
        )
        commit_sig = hashlib.sha256(sig_payload.encode("utf-8")).hexdigest()
        if st.session_state.get(last_commit_sig_key) == commit_sig:
            return False
        st.session_state[last_commit_sig_key] = commit_sig

        if "selected_shape_id" in trigger:
            st.session_state[selected_shape_id_key] = trigger.get("selected_shape_id") or None

        # Persist layers and shapes whenever included in the commit payload
        incoming_layers = trigger.get("layers") if isinstance(trigger.get("layers"), list) else persisted_layers
        incoming_shapes = trigger.get("shapes") if isinstance(trigger.get("shapes"), list) else persisted_shapes
        try:
            layer_id_map = _sync_draft_layers_to_db(
                project_id=project_id,
                revision_id=rev_id,
                draft_layers=[dict(l) for l in incoming_layers],
                editor_name=effective_editor,
            )
            cleaned_shapes = []
            for raw_s in incoming_shapes:
                s_copy = dict(raw_s)
                raw_lid = str(s_copy.get("layer_id") or "")
                if raw_lid in layer_id_map:
                    s_copy["layer_id"] = layer_id_map[raw_lid]
                cleaned_shapes.append(s_copy)
            save_layout_shapes(
                project_id=project_id,
                revision_id=rev_id,
                shapes=cleaned_shapes,
                editor_name=effective_editor,
            )
            st.session_state[draft_shapes_key] = cleaned_shapes
            st.session_state[draft_layers_key] = [dict(l) for l in list_layout_layers(rev_id)]
            st.session_state[has_unsaved_shapes_key] = False
        except ValueError as exc:
            st.error(str(exc))
            return

        try:
            if action == "calibrate_scale":
                cal = (
                    trigger["scale_calibration"]
                    if isinstance(trigger.get("scale_calibration"), dict)
                    else trigger
                )
                px_dist = float(cal.get("pixel_distance") or 0.0)
                if px_dist <= 0 and "x1_px" in cal and "x2_px" in cal:
                    px_dist = math.hypot(
                        float(cal.get("x2_px") or 0.0) - float(cal.get("x1_px") or 0.0),
                        float(cal.get("y2_px") or 0.0) - float(cal.get("y1_px") or 0.0),
                    )
                phys_dist = float(
                    cal.get("physical_distance") or cal.get("real_distance") or 0.0
                )
                cal_unit = str(cal.get("unit") or unit)
                if px_dist > 0 and phys_dist > 0:
                    calibrate_revision_scale_by_reference(
                        project_id=project_id,
                        revision_id=rev_id,
                        pixel_distance=px_dist,
                        physical_distance=phys_dist,
                        unit=cal_unit,
                        editor_name=effective_editor,
                    )
            elif action == "update_scale":
                su = (
                    trigger["scale_update"]
                    if isinstance(trigger.get("scale_update"), dict)
                    else trigger
                )
                new_w = max(1.0, float(su.get("width_value") or active_rev["width_value"] or 200.0))
                new_h = max(1.0, float(su.get("height_value") or active_rev["height_value"] or 100.0))
                new_u = str(su.get("unit") or unit)
                update_layout_revision_scale(
                    project_id=project_id,
                    revision_id=rev_id,
                    width_value=new_w,
                    height_value=new_h,
                    unit=new_u,
                    notes=str(active_rev.get("notes") or ""),
                    editor_name=effective_editor,
                )
            elif action == "rename_page":
                target_id = str(trigger.get("target_page_id") or trigger.get("page_id") or active_layout_id or "").strip()
                new_title = str(trigger.get("page_title") or "").strip()
                target_layout = layout_by_id.get(target_id) if target_id else current_layout
                if new_title and target_layout and new_title != str(target_layout["name"]):
                    update_layout(
                        project_id,
                        str(target_layout["id"]),
                        new_title,
                        str(target_layout.get("description") or ""),
                        effective_editor,
                    )
            elif action == "add_page":
                existing_names = {str(l["name"]).strip().lower() for l in list_layouts(project_id)}
                idx = len(existing_names) + 1
                candidate_name = (
                    str(trigger.get("page_name") or trigger.get("page_title") or f"Page {idx}").strip()
                    or f"Page {idx}"
                )
                while candidate_name.lower() in existing_names:
                    idx += 1
                    candidate_name = f"Page {idx}"
                new_layout = create_layout(
                    project_id=project_id,
                    name=candidate_name,
                    description="Pin Map & Scaled Line Layout",
                    editor_name=effective_editor,
                )
                new_rev = create_blank_scaled_revision(
                    project_id=project_id,
                    layout_id=str(new_layout["id"]),
                    width_value=200.0,
                    height_value=100.0,
                    unit=unit,
                    notes="Blank scaled grid canvas",
                    editor_name=effective_editor,
                )
                st.session_state["active_layout_id"] = str(new_layout["id"])
                st.session_state["active_revision_id"] = str(new_rev["id"])
            elif action == "switch_page":
                target_page_id = str(trigger.get("target_page_id") or trigger.get("page_id") or "")
                if target_page_id and target_page_id in layout_by_id:
                    st.session_state["active_layout_id"] = target_page_id
                    target_revs = list_layout_revisions(target_page_id)
                    if target_revs:
                        st.session_state["active_revision_id"] = str(target_revs[0]["id"])
            elif action == "delete_page":
                target_page_id = str(trigger.get("target_page_id") or trigger.get("page_id") or "")
                all_layouts = list_layouts(project_id)
                if target_page_id and len(all_layouts) > 1:
                    delete_layout(project_id, target_page_id, effective_editor)
                    remaining = list_layouts(project_id)
                    if remaining:
                        st.session_state["active_layout_id"] = str(remaining[0]["id"])
                        rem_revs = list_layout_revisions(str(remaining[0]["id"]))
                        if rem_revs:
                            st.session_state["active_revision_id"] = str(rem_revs[0]["id"])
            elif action == "upload_background":
                bg_data_url = str(trigger.get("background_data_url") or "")
                if bg_data_url:
                    update_revision_background_from_data_url(
                        project_id=project_id,
                        revision_id=rev_id,
                        data_url=bg_data_url,
                        editor_name=effective_editor,
                    )
            elif action == "clear_background":
                update_revision_background_from_data_url(
                    project_id=project_id,
                    revision_id=rev_id,
                    data_url="",
                    editor_name=effective_editor,
                )
            elif action == "save_custom_stencil":
                cs = trigger.get("custom_stencil")
                if isinstance(cs, dict):
                    cs_name = str(cs.get("name") or trigger.get("stencil_name") or "").strip()
                    cs_data = cs.get("stencil_data") if isinstance(cs.get("stencil_data"), dict) else cs
                    cs_cat = str(cs.get("category") or "Saved Shapes").strip() or "Saved Shapes"
                    cs_id = str(cs.get("id") or trigger.get("stencil_id") or "").strip() or None
                    if cs_name:
                        save_layout_custom_stencil(
                            project_id=project_id,
                            name=cs_name,
                            stencil_data=cs_data,
                            editor_name=effective_editor,
                            category=cs_cat,
                            stencil_id=cs_id,
                        )
            elif action == "delete_custom_stencil":
                cs_id = str(trigger.get("stencil_id") or "").strip()
                if cs_id:
                    delete_layout_custom_stencil(
                        project_id=project_id,
                        stencil_id=cs_id,
                        editor_name=effective_editor,
                    )
            elif action == "open_section_standards":
                st.session_state["_open_pin_map_dialog"] = "section_standards"
            elif action == "open_cad_revisions":
                st.session_state["_open_pin_map_dialog"] = "cad_revisions"
        except ValueError as exc:
            st.error(str(exc))
            return False
        return True

    # Process any pending canvas commit before building props so post-commit state is fresh
    committed = handle_canvas_commit()

    if committed:
        # Reload active page/revision/shapes/layers/background after commit processing
        layouts = list_layouts(project_id)
        layout_by_id = {str(l["id"]): l for l in layouts}
        active_layout_id = str(st.session_state.get("active_layout_id") or "")
        if active_layout_id not in layout_by_id:
            active_layout_id = str(layouts[0]["id"])
            st.session_state["active_layout_id"] = active_layout_id
        current_layout = layout_by_id[active_layout_id]

        revisions = list_layout_revisions(active_layout_id)
        rev_by_id = {str(r["id"]): r for r in revisions}
        active_rev_id = str(st.session_state.get("active_revision_id") or "")
        if active_rev_id not in rev_by_id:
            active_rev_id = str(revisions[0]["id"])
            st.session_state["active_revision_id"] = active_rev_id
        active_rev = rev_by_id[active_rev_id]
        rev_id = str(active_rev["id"])
        st.session_state["layout_plan_selector"] = active_layout_id
        st.session_state["layout_revision_selector"] = rev_id

        draft_shapes_key = f"layout_shapes_draft_{rev_id}"
        draft_layers_key = f"layout_layers_draft_{rev_id}"
        selected_shape_id_key = f"layout_selected_shape_{rev_id}"
        canvas_key = f"layout_canvas_{rev_id}"

        persisted_layers = [dict(l) for l in list_layout_layers(rev_id)]
        persisted_shapes = [dict(s) for s in list_layout_shapes(rev_id)]

    w_in = float(active_rev.get("scale_width_in") or 2400.0)
    h_in = float(active_rev.get("scale_height_in") or 1200.0)
    w_px = int(active_rev.get("image_width_px") or 2400)
    h_px = int(active_rev.get("image_height_px") or 1200)
    unit = str(active_rev.get("unit") or "feet")

    px_per_in_x = (w_px / w_in) if w_in > 0 else 1.0
    px_per_in_y = (h_px / h_in) if h_in > 0 else 1.0

    selected_shape_id: str | None = st.session_state.get(selected_shape_id_key)

    all_project_pitches = list_project_yamazumi_pitches(project_id)
    project_pitches = [
        p for p in all_project_pitches
        if not effective_scenario_id or str(p.get("scenario_id") or "") == str(effective_scenario_id)
    ]
    cross_scenario_pitch_aliases: dict[str, str] = {}
    if effective_scenario_id and project_pitches:
        pitch_by_id_all = {str(p.get("pitch_id") or p.get("id") or ""): p for p in all_project_pitches}
        active_pitch_ids = {str(p.get("pitch_id") or p.get("id") or "") for p in project_pitches}
        active_by_sec_num = {
            (str(p.get("section_id") or "").strip(), str(p.get("pitch_number") or "").strip().lower()): str(p.get("pitch_id") or p.get("id") or "")
            for p in project_pitches
            if str(p.get("section_id") or "").strip()
        }
        active_by_area_num = {
            (str(p.get("area_name") or "").strip().lower(), str(p.get("pitch_number") or "").strip().lower()): str(p.get("pitch_id") or p.get("id") or "")
            for p in project_pitches
        }
        for s_item in persisted_shapes:
            raw_pid = str(s_item.get("pitch_id") or "")
            if raw_pid and raw_pid not in active_pitch_ids and raw_pid in pitch_by_id_all:
                src_p = pitch_by_id_all[raw_pid]
                sec_id_str = str(src_p.get("section_id") or "").strip()
                pnum_str = str(src_p.get("pitch_number") or "").strip().lower()
                key_an = (
                    str(src_p.get("area_name") or "").strip().lower(),
                    pnum_str,
                )
                mapped_pid = (
                    (active_by_sec_num.get((sec_id_str, pnum_str)) if sec_id_str else None)
                    or active_by_area_num.get(key_an)
                )
                if mapped_pid:
                    cross_scenario_pitch_aliases[raw_pid] = mapped_pid

    st.session_state[draft_shapes_key] = persisted_shapes
    st.session_state[draft_layers_key] = persisted_layers

    other_revs = [r for r in revisions if str(r["id"]) != rev_id]
    cad_file_name = str(active_rev.get("cad_file_name") or "").strip()
    cad_file_path = str(active_rev.get("cad_file_path") or "").strip()
    cad_web_url = str(active_rev.get("cad_web_url") or "").strip()
    has_cad_file = bool(cad_file_path and Path(cad_file_path).is_file())

    if len(revisions) > 1 or has_cad_file or cad_web_url:
        with st.container(border=True):
            rc1, rc2, rc3, rc4, rc5 = st.columns([2.4, 1.4, 1.4, 1.4, 1.1], vertical_alignment="center")
            with rc1:
                rev_labels = {
                    str(r["id"]): f"Rev {r['revision_number']} ({int(r.get('shape_count', 0))} shapes — {format_eastern_timestamp(r.get('created_at'), '%Y-%m-%d')[:10]})"
                    for r in revisions
                }
                rev_ids_list = list(rev_labels.keys())
                sel_rev_idx = rev_ids_list.index(rev_id) if rev_id in rev_ids_list else 0
                chosen_rev_id = st.selectbox(
                    "Active drawing revision",
                    options=rev_ids_list,
                    index=sel_rev_idx,
                    format_func=lambda rid: rev_labels.get(rid, rid),
                    key=f"layout_rev_bar_select_{active_layout_id}",
                    label_visibility="collapsed",
                )
                if chosen_rev_id != rev_id:
                    st.session_state["active_revision_id"] = chosen_rev_id
                    st.rerun()
            with rc2:
                if st.button(
                    "New revision / PDF",
                    icon=":material/add_photo_alternate:",
                    key=f"btn_bar_new_rev_{rev_id}",
                    width="stretch",
                ):
                    st.session_state["_open_pin_map_dialog"] = "cad_revisions"
                    st.rerun()
            with rc3:
                if st.button(
                    "Import shapes",
                    icon=":material/content_copy:",
                    key=f"btn_bar_imp_shapes_{rev_id}",
                    disabled=not bool(other_revs),
                    width="stretch",
                ):
                    st.session_state["_open_pin_map_dialog"] = "import_shapes"
                    st.rerun()
            with rc4:
                if st.button(
                    f"CAD ({cad_file_name[:12]}…)" if has_cad_file else ("CAD link" if cad_web_url else "Attach CAD"),
                    icon=":material/architecture:",
                    key=f"btn_bar_attach_cad_{rev_id}",
                    width="stretch",
                ):
                    st.session_state["_open_pin_map_dialog"] = "attach_cad"
                    st.rerun()
            with rc5:
                if st.button(
                    "Delete rev",
                    icon=":material/delete:",
                    key=f"destructive_btn_bar_del_rev_{rev_id}",
                    disabled=len(revisions) <= 1,
                    width="stretch",
                ):
                    st.session_state["_open_pin_map_dialog"] = "delete_revision"
                    st.rerun()

    pending_dlg = st.session_state.pop("_open_pin_map_dialog", None)
    if pending_dlg == "section_standards":
        _section_standards_dialog(project_id, active_layout_id, unit, effective_editor)
    elif pending_dlg == "cad_revisions":
        _create_revision_dialog(
            project_id,
            current_layout,
            active_rev,
            effective_editor,
            current_draft_shapes=persisted_shapes,
        )
    elif pending_dlg == "import_shapes" and other_revs:
        _import_shapes_dialog(
            project_id,
            current_layout,
            active_rev,
            other_revs,
            effective_editor,
        )
    elif pending_dlg == "attach_cad":
        _attach_cad_dialog(
            project_id,
            str(current_layout["name"]),
            active_rev,
            effective_editor,
        )
    elif pending_dlg == "confirm_detach_cad":
        _confirm_detach_cad_dialog(
            project_id,
            str(current_layout["name"]),
            active_rev,
            effective_editor,
        )
    elif pending_dlg == "delete_revision" and len(revisions) > 1:
        _delete_revision_dialog(
            project_id,
            str(current_layout["name"]),
            active_rev,
            effective_editor,
        )

    section_standards = get_section_pitch_standards(active_layout_id)
    pitch_metrics = (
        get_scenario_pitch_metrics_for_pin_map(project_id, str(effective_scenario_id))
        if effective_scenario_id
        else {}
    )
    for raw_pid, mapped_pid in cross_scenario_pitch_aliases.items():
        if mapped_pid in pitch_metrics:
            pitch_metrics[raw_pid] = pitch_metrics[mapped_pid]
    custom_stencils = list_layout_custom_stencils(project_id)
    pages_payload = [{"id": str(l["id"]), "name": str(l["name"])} for l in layouts]

    notes_lower = str(active_rev.get("notes") or "").lower()
    img_path_str = str(active_rev.get("image_path") or "")
    is_blank_canvas = (
        "blank scaled" in notes_lower
        or "blank_scaled_canvas" in img_path_str.lower()
    )
    img_path = Path(img_path_str) if img_path_str else None
    image_data_url = (
        layout_image_data_url(str(img_path), img_path.stat().st_mtime_ns)
        if (img_path and img_path.is_file() and not is_blank_canvas)
        else ""
    )

    layout_canvas(
        image_url=image_data_url,
        image_width=w_px,
        image_height=h_px,
        scale_factor_px_per_in=px_per_in_x,
        scale_factor_px_per_in_x=px_per_in_x,
        scale_factor_px_per_in_y=px_per_in_y,
        unit=unit,
        shapes=persisted_shapes,
        layers=persisted_layers,
        pitches=project_pitches,
        pitch_metrics=pitch_metrics,
        section_standards=section_standards,
        custom_stencils=custom_stencils,
        selected_shape_id=selected_shape_id,
        pages=pages_payload,
        active_page_id=active_layout_id,
        page_title=str(current_layout["name"]),
        is_blank_canvas=is_blank_canvas,
        key=canvas_key,
        on_select_shape=handle_select_shape,
        on_shape_moved=handle_shape_moved,
        on_canvas_commit=handle_canvas_commit,
    )

    if not embedded_in_pin_map:
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
                            "When", format="MMM DD, YYYY HH:mm", timezone="America/New_York"
                        ),
                    },
                )

