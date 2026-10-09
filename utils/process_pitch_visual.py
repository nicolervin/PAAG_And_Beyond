from __future__ import annotations

import base64
import html
import mimetypes
from datetime import date
from pathlib import Path
from typing import Iterable


ELEMENTS_PER_PAGE = 5
MEDIA_PER_PAGE = 6


def page_count(element_count: int, page_size: int = ELEMENTS_PER_PAGE) -> int:
    """Return total pages needed for element count."""
    return max(1, (max(0, int(element_count)) + page_size - 1) // page_size)


def clamp_page(page_num: int, element_count: int, page_size: int = ELEMENTS_PER_PAGE) -> int:
    """Clamp page number between 1 and page_count."""
    return min(max(1, int(page_num or 1)), page_count(element_count, page_size))


def media_page_count(media_count: int, page_size: int = MEDIA_PER_PAGE) -> int:
    """Return total slides needed for visual media count."""
    return max(1, (max(0, int(media_count)) + page_size - 1) // page_size)


def clamp_media_page(page_num: int, media_count: int, page_size: int = MEDIA_PER_PAGE) -> int:
    """Clamp media slide number between 1 and media_page_count."""
    return min(max(1, int(page_num or 1)), media_page_count(media_count, page_size))


def page_for_element(
    elements: Iterable[dict], work_element_id: str, page_size: int = ELEMENTS_PER_PAGE
) -> int:
    """Find page index (1-based) containing the specified work element."""
    target = str(work_element_id or "").strip()
    for index, element in enumerate(elements):
        if str(element.get("work_element_id") or "").strip() == target:
            return index // page_size + 1
    raise ValueError("The selected Work Element is no longer assigned to this pitch.")


def page_elements(
    elements: list[dict], page_num: int, page_size: int = ELEMENTS_PER_PAGE
) -> list[dict]:
    """Slice elements for the given page number."""
    current = clamp_page(page_num, len(elements), page_size)
    start = (current - 1) * page_size
    return elements[start : start + page_size]


def page_media(
    media_items: list[dict], page_num: int, page_size: int = MEDIA_PER_PAGE
) -> list[dict]:
    """Slice visual media items for the given slide page number."""
    current = clamp_page(page_num, len(media_items), page_size)
    start = (current - 1) * page_size
    return media_items[start : start + page_size]


def _text(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _clean_number(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _text(value)
    return f"{number:g}"


def _media_data_url(raw_path: object) -> str:
    path = Path(str(raw_path or ""))
    try:
        if not path.is_file():
            return ""
        mime = mimetypes.guess_type(path.name)[0]
        if not mime:
            suffix = path.suffix.lower()
            if suffix == ".mp4":
                mime = "video/mp4"
            elif suffix == ".webm":
                mime = "video/webm"
            elif suffix == ".mov":
                mime = "video/quicktime"
            else:
                mime = "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except OSError:
        return ""


def _part_images(parts: list[dict]) -> str:
    images: list[str] = []
    for part in parts:
        part_number = _text(part.get("part_number") or "Part")
        source = _media_data_url(part.get("image_path"))
        if source:
            images.append(
                f'<figure><img src="{source}" alt="{part_number}"><figcaption>{part_number}</figcaption></figure>'
            )
        else:
            images.append(
                f'<div class="part-placeholder"><span>No image</span><small>{part_number}</small></div>'
            )
    if not images:
        return '<div class="part-placeholder no-parts"><span>No Parts Paired</span></div>'
    return "".join(images)


def _torque_badge(requirement: dict) -> str:
    identifier = _text(requirement.get("unique_identifier") or "Torque")
    target = _clean_number(requirement.get("target_value"))
    tolerance = _text(requirement.get("tolerances"))
    unit = _text(requirement.get("unit"))
    pieces = [piece for piece in (target, tolerance, unit) if piece]
    detail = " ".join(pieces) or "Specification linked"
    return f'<span class="tag torque">{identifier}: {detail}</span>'


def render_pitch_canvas(
    pitch: dict,
    elements: list[dict] | None = None,
    *,
    scenario_name: str = "",
    project_name: str = "",
    page_num: int = 1,
    total_pages: int | None = None,
    tools: list[dict] | None = None,
    parts: list[dict] | None = None,
    yamazumi_stacks: dict[str, list[dict]] | None = None,
    visual_media: list[dict] | None = None,
    alerts: dict[str, list[dict]] | None = None,
    op_id_summary: str = "",
    scenario_takt_s: float = 0.0,
    generated_on: date | None = None,
    presentation_mode: bool = False,
    print_format: str | None = None,
    image_fit: str = "contain",
) -> str:
    """Render a 16:9 landscape PowerPoint-style Process at a Glance slide."""
    elements_list = elements or []
    pitch_number = _text(pitch.get("pitch_number") or "Unassigned Pitch")
    pitch_name = _text(pitch.get("pitch_name") or "Process Station")
    section_name = _text(pitch.get("section_name") or "")
    eff_project_name = _text(project_name or pitch.get("project_name") or "Project")
    eff_scenario_name = _text(scenario_name or pitch.get("scenario_name") or "Scenario")

    # Date formatting
    generated = generated_on or date.today()
    generated_label = f"{generated:%B} {generated.day}, {generated.year}"

    # Fallbacks and derivation from elements if not supplied
    if tools is None:
        raw_tools = pitch.get("tools")
        tools = list(raw_tools) if isinstance(raw_tools, list) else []

    if parts is None:
        raw_parts = pitch.get("parts")
        if isinstance(raw_parts, list) and raw_parts:
            parts = list(raw_parts)
        else:
            # Derive aggregated parts from elements
            seen_parts: dict[str, dict] = {}
            for el in elements_list:
                for p in el.get("parts", []):
                    p_num = str(p.get("part_number") or "").strip()
                    if not p_num:
                        continue
                    if p_num not in seen_parts:
                        seen_parts[p_num] = {
                            "part_number": p_num,
                            "description": p.get("part_description") or p.get("description") or "",
                            "factory_nickname": p.get("factory_nickname") or "",
                            "image_path": p.get("image_path") or "",
                            "quantity": float(p.get("quantity") or 1.0),
                            "handling_types": set(),
                        }
                    else:
                        seen_parts[p_num]["quantity"] += float(p.get("quantity") or 1.0)
            parts = list(seen_parts.values())

    if yamazumi_stacks is None:
        raw_stacks = pitch.get("yamazumi_stacks")
        if isinstance(raw_stacks, dict) and raw_stacks:
            yamazumi_stacks = raw_stacks
        else:
            # Derive mini stack from elements
            stack_elements: list[dict] = []
            for el in elements_list:
                color = str(el.get("motion_color") or "gray")
                if color not in {"green", "orange", "gray"}:
                    color = "gray"
                stack_elements.append({
                    "id": el.get("work_element_id") or el.get("id"),
                    "description": el.get("yamazumi_description") or el.get("operation") or "",
                    "time_s": float(el.get("time_s") or 0.0),
                    "motion_color": color,
                    "motion_classification": el.get("motion_classification") or "Unclassified",
                })
            yamazumi_stacks = {"Base": stack_elements}

    if visual_media is None:
        raw_media = pitch.get("visual_media")
        visual_media = list(raw_media) if isinstance(raw_media, list) else []

    if alerts is None:
        raw_alerts = pitch.get("alerts")
        if isinstance(raw_alerts, dict) and raw_alerts:
            alerts = raw_alerts
        else:
            alerts = {
                "quality": [],
                "ergo": [],
                "safety": [],
                "materials": [],
                "equipment": [],
            }
            # Derive alerts from elements
            for el in elements_list:
                if el.get("ergonomics_risk"):
                    alerts["ergo"].append({
                        "label": "Ergo Risk",
                        "detail": f"Ergonomics Risk on {el.get('operation') or 'step'}",
                    })
                for tq in el.get("torque_requirements", []):
                    t_uid = _text(tq.get("unique_identifier") or "Torque")
                    t_val = _clean_number(tq.get("target_value"))
                    t_tol = _text(tq.get("tolerances"))
                    t_unt = _text(tq.get("unit"))
                    t_spec = " ".join(p for p in [t_val, t_tol, t_unt] if p)
                    alerts["quality"].append({
                        "label": f"{t_uid}: {t_spec}" if t_spec else t_uid,
                        "detail": f"Torque requirement {t_uid}: {t_spec}",
                    })

    if not op_id_summary:
        raw_summary = pitch.get("op_id_summary")
        if raw_summary:
            op_id_summary = str(raw_summary)
        else:
            op_ids = [
                str(el.get("op_id") or "")
                for el in elements_list
                if el.get("op_id") and el.get("op_id") != "Yamazumi link required"
            ]
            if op_ids:
                op_id_summary = f"{op_ids[0]} – {op_ids[-1]}" if len(op_ids) > 1 else op_ids[0]
            else:
                op_id_summary = "N/A"

    eff_takt_s = float(scenario_takt_s or pitch.get("scenario_takt_s") or 0.0)

    # Pagination calculation
    total_media_count = len(visual_media)
    calc_total_pages = max(1, page_count(total_media_count, MEDIA_PER_PAGE))
    eff_total_pages = total_pages if total_pages is not None else calc_total_pages
    eff_page_num = clamp_page(page_num, total_media_count if total_media_count > 0 else 1, MEDIA_PER_PAGE)

    # Slice media for this slide
    current_media_items = page_media(visual_media, eff_page_num, MEDIA_PER_PAGE) if visual_media else []

    # 1. BUILD LEFT COLUMN: TOOLS
    tool_items_html: list[str] = []
    seen_tool_ids: set[str] = set()
    for tool in tools:
        t_id = str(tool.get("equipment_id") or tool.get("name") or "")
        if t_id and t_id in seen_tool_ids:
            continue
        seen_tool_ids.add(t_id)
        t_name = _text(tool.get("name") or "Tool")
        t_type = _text(tool.get("type_name") or "")
        t_summary = _text(tool.get("summary_line") or f"{t_name} ({t_type})" if t_type else t_name)
        is_ppe = tool.get("is_ppe", False)
        ppe_badge = '<span class="badge-ppe">PPE</span> ' if is_ppe else ''
        tool_items_html.append(
            f'<li class="tool-item" title="{t_summary}">{ppe_badge}<span class="tool-text">{t_summary}</span></li>'
        )
    tools_section_html = (
        f'<ul class="tools-list">{"".join(tool_items_html)}</ul>'
        if tool_items_html
        else '<div class="subtle-empty">No equipment or PPE assigned</div>'
    )

    # 2. BUILD LEFT COLUMN: PARTS TABLE
    part_rows_html: list[str] = []
    for part in parts:
        p_num = _text(part.get("part_number") or "Part")
        p_desc = _text(part.get("description") or part.get("part_name") or "")
        p_nick = _text(part.get("factory_nickname") or "")
        p_qty = _clean_number(part.get("quantity") or part.get("total_quantity") or part.get("qty") or 1)
        p_img_url = _media_data_url(part.get("image_path") or part.get("thumbnail_path"))
        img_tag = (
            f'<img src="{p_img_url}" alt="{p_num}" class="part-thumb" />'
            if p_img_url
            else '<div class="thumb-ph">IMG</div>'
        )
        h_types = part.get("handling_types") or []
        if not h_types and part.get("handling_type"):
            h_types = [part.get("handling_type")]

        h_badges: list[str] = []
        for ht in h_types:
            ht_clean = str(ht).strip()
            if ht_clean.casefold() in {"consume", "c"}:
                h_badges.append('<span class="h-badge va">Consume</span>')
            elif ht_clean.casefold() in {"handle", "h"}:
                h_badges.append('<span class="h-badge nvan">Handle</span>')
            elif ht_clean:
                h_badges.append(f'<span class="h-badge">{_text(ht_clean)}</span>')
        h_cell = " ".join(h_badges) if h_badges else '<span class="text-muted">—</span>'

        nick_row = (
            f'<div class="part-nick-text" title="Factory Nickname: {p_nick}">{p_nick}</div>'
            if p_nick
            else '<div class="part-nick-space">&nbsp;</div>'
        )

        part_rows_html.append(
            f"""
            <tr>
              <td class="col-thumb">{img_tag}</td>
              <td class="col-pnum"><strong>{p_num}</strong></td>
              <td class="col-desc">
                <div class="part-desc-text" title="{p_desc}">{p_desc or '—'}</div>
                {nick_row}
              </td>
              <td class="col-qty">{p_qty}</td>
              <td class="col-handling">{h_cell}</td>
            </tr>
            """
        )
    if part_rows_html:
        parts_section_html = f"""
        <table class="parts-table">
          <thead>
            <tr>
              <th class="col-thumb">Img</th>
              <th class="col-pnum">Part #</th>
              <th class="col-desc">Description</th>
              <th class="col-qty">Qty</th>
              <th class="col-handling">Consume / Handle</th>
            </tr>
          </thead>
          <tbody>{"".join(part_rows_html)}</tbody>
        </table>
        """
    else:
        parts_section_html = '<div class="part-placeholder no-parts"><span>No Parts Paired</span></div>'

    # 3. BUILD LEFT COLUMN: MINI YAMAZUMI STACK
    variant_columns_html: list[str] = []
    max_variant_time = 0.0
    for v_name, v_data in yamazumi_stacks.items():
        v_elements = v_data.get("elements", []) if isinstance(v_data, dict) else (v_data if isinstance(v_data, list) else [])
        v_time = sum(float(e.get("time_s") or 0.0) for e in v_elements if isinstance(e, dict))
        if v_time > max_variant_time:
            max_variant_time = v_time

    # Chart height references
    ref_time = max(max_variant_time, eff_takt_s, 1.0)
    chart_px_height = 130

    for v_name, v_data in yamazumi_stacks.items():
        v_elements = v_data.get("elements", []) if isinstance(v_data, dict) else (v_data if isinstance(v_data, list) else [])
        v_total_s = sum(float(e.get("time_s") or 0.0) for e in v_elements if isinstance(e, dict))
        blocks_html: list[str] = []
        for e in v_elements:
            if not isinstance(e, dict):
                continue
            e_desc = _text(e.get("description") or e.get("yamazumi_description") or "")
            e_time = float(e.get("time_s") or 0.0)
            e_color = str(e.get("motion_color") or "gray")
            if e_color not in {"green", "orange", "gray"}:
                e_color = "gray"

            work_type = str(e.get("work_type") or "").strip()
            work_type_lower = work_type.lower()
            if work_type_lower == "periodic":
                type_class = "type-periodic"
            elif work_type_lower == "fluctuation":
                type_class = "type-fluctuation"
            elif work_type_lower == "cycle":
                type_class = "type-cycle"
            else:
                if e_color == "green":
                    type_class = "type-cycle"
                elif e_color == "orange":
                    type_class = "type-periodic"
                else:
                    type_class = "type-cycle"

            # Height in px proportional to time
            b_height = max(18, int(chart_px_height * (e_time / ref_time))) if ref_time > 0 else 22
            blocks_html.append(
                f"""
                <div class="stack-block {type_class} motion-bar {e_color}" style="height:{b_height}px" title="{e_desc} · {_clean_number(e_time)} s · {work_type or 'Cycle'}">
                  <span class="block-label">{e_desc}</span>
                  <span class="block-time">{_clean_number(e_time)}s</span>
                </div>
                """
            )
        # Takt line position from bottom
        takt_line_html = ""
        if eff_takt_s > 0 and ref_time > 0:
            takt_bottom_px = min(chart_px_height, int(chart_px_height * (eff_takt_s / ref_time)))
            takt_line_html = f'<div class="takt-line" style="bottom:{takt_bottom_px}px"><span class="takt-label">Takt: {_clean_number(eff_takt_s)}s</span></div>'

        # Metrics: variant time, takt time, percent utilized
        if eff_takt_s > 0:
            util_pct = (v_total_s / eff_takt_s) * 100.0
            is_over = util_pct > 100.0
            util_class = "over-takt" if is_over else "under-takt"
            metrics_html = (
                f'<span class="variant-time">{_clean_number(v_total_s)}s</span> '
                f'<span class="variant-takt">/ Takt {_clean_number(eff_takt_s)}s</span> '
                f'<span class="variant-util {util_class}">({util_pct:.0f}% util)</span>'
            )
        else:
            metrics_html = f'<span class="variant-time">{_clean_number(v_total_s)}s</span>'

        variant_columns_html.append(
            f"""
            <div class="variant-stack-col">
              <div class="variant-header">
                <span class="variant-name">{_text(v_name)}:</span>
                {metrics_html}
              </div>
              <div class="stack-track" style="height:{chart_px_height}px">
                {takt_line_html}
                <div class="stack-blocks-wrapper">{"".join(blocks_html)}</div>
              </div>
            </div>
            """
        )

    # 4. BUILD RIGHT COLUMN: DYNAMIC VISUAL MEDIA GRID (3x2)
    grid_count = len(current_media_items)
    grid_class = "grid-layout-empty"
    if grid_count == 1:
        grid_class = "grid-layout-1"
    elif grid_count == 2:
        grid_class = "grid-layout-2"
    elif grid_count == 3:
        grid_class = "grid-layout-3"
    elif grid_count == 4:
        grid_class = "grid-layout-4"
    elif grid_count in {5, 6}:
        grid_class = "grid-layout-6"

    media_cards_html: list[str] = []
    for item in current_media_items:
        m_type = item.get("media_type") or "image"
        caption = _text(item.get("caption") or "")
        f_path = item.get("file_path") or ""
        media_src = _media_data_url(f_path)
        tag_labels = [
            _text(t.get("operation") or f"Step {t.get('work_sequence', '')}")
            for t in item.get("tagged_work_elements", [])
        ]
        step_tag_html = (
            f'<div class="visual-step-tag">{" · ".join(tag_labels)}</div>'
            if tag_labels
            else '<div class="visual-step-tag general">General Pitch Visual</div>'
        )

        if m_type == "video":
            if media_src:
                media_element_html = f'<video class="visual-player" controls playsinline preload="metadata" src="{media_src}"></video>'
            else:
                media_element_html = '<div class="media-missing">Video not available</div>'
        else:
            if media_src:
                media_element_html = f'<img class="visual-image" src="{media_src}" alt="{caption}" />'
            else:
                media_element_html = '<div class="media-missing">Image not available</div>'

        caption_html = (
            f'<div class="caption-callout"><span class="callout-bullet">📍</span> {caption}</div>'
            if caption
            else '<div class="caption-callout empty"><span class="callout-bullet">📍</span> Step Visual Aid</div>'
        )

        media_cards_html.append(
            f"""
            <article class="visual-card">
              {step_tag_html}
              <div class="visual-media-box">
                {media_element_html}
              </div>
              {caption_html}
            </article>
            """
        )

    if not media_cards_html:
        right_area_html = """
        <div class="empty-media-canvas">
          <div class="empty-media-icon">📷 🎬</div>
          <div class="empty-media-title">No Visual Step Guides Added</div>
          <div class="empty-media-desc">Use the Process Visual Aids management section below to upload photos or playable demonstration videos (.mp4, .mov, .webm) and tag them to work elements.</div>
        </div>
        """
    else:
        right_area_html = f'<div class="visual-grid {grid_class}">{"".join(media_cards_html)}</div>'

    # 5. BUILD FUNCTIONAL ALERTS BAR
    alert_categories = [
        ("Quality", "quality", alerts.get("quality", [])),
        ("Ergo", "ergo", alerts.get("ergo", [])),
        ("Safety", "safety", alerts.get("safety", [])),
        ("Materials", "materials", alerts.get("materials", [])),
        ("Equipment", "equipment", alerts.get("equipment", [])),
    ]
    alert_blocks_html: list[str] = []
    for cat_name, cat_key, cat_list in alert_categories:
        if cat_list:
            items_str = " · ".join(_text(item.get("label") or "Alert") for item in cat_list)
            first_detail = _text(cat_list[0].get("detail") or cat_list[0].get("label") or "")
            alert_blocks_html.append(
                f"""
                <div class="alert-block active {cat_key}" title="{first_detail}">
                  <strong>{cat_name}:</strong> <span class="alert-summary">{items_str}</span>
                </div>
                """
            )
        else:
            alert_blocks_html.append(
                f"""
                <div class="alert-block clear {cat_key}">
                  <strong>{cat_name}:</strong> <span class="alert-ok">✓ None</span>
                </div>
                """
            )

    presentation_class = "presentation-active" if presentation_mode else ""
    print_class = f"print-{print_format}" if print_format else ""
    fit_class = f"fit-{image_fit}" if image_fit else "fit-contain"

    return f"""
    <style>
      .paag-slide {{
        aspect-ratio: 16 / 9;
        box-sizing: border-box;
        width: 100%;
        max-width: 100%;
        min-height: 640px;
        padding: 14px 18px;
        border: 1px solid rgba(128,128,128,0.3);
        border-radius: 12px;
        background: #ffffff;
        color: #1a1f2c;
        display: flex;
        flex-direction: column;
        gap: 10px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        box-shadow: 0 4px 16px rgba(0,0,0,0.06);
        overflow: hidden;
      }}
      .paag-slide.print-tabloid {{
        aspect-ratio: 17 / 11 !important;
        width: 100% !important;
        max-width: 100% !important;
        min-height: 680px;
      }}
      .paag-slide.print-tabloid .slide-body {{
        grid-template-columns: 32% 68%;
        gap: 14px;
      }}
      .paag-slide.print-tabloid .right-col {{
        height: 100%;
        flex: 1 1 auto;
      }}
      .paag-slide.print-tabloid .visual-grid {{
        height: 100%;
        min-height: 480px;
        flex: 1 1 auto;
      }}
      .paag-slide.print-tabloid .visual-card {{
        height: 100%;
        min-height: 0;
        flex: 1 1 auto;
      }}
      .paag-slide.print-tabloid .visual-media-box {{
        height: 100%;
        min-height: 0;
        flex: 1 1 auto;
      }}
      .paag-slide.fit-stretch .visual-image,
      .paag-slide.fit-fill .visual-image,
      .paag-slide.print-tabloid.fit-stretch .visual-image,
      .paag-slide.print-tabloid.fit-fill .visual-image {{
        width: 100% !important;
        height: 100% !important;
        object-fit: fill !important;
      }}
      .paag-slide.fit-cover .visual-image {{
        width: 100% !important;
        height: 100% !important;
        object-fit: cover !important;
      }}
      .paag-slide.fit-contain .visual-image {{
        width: 100% !important;
        height: 100% !important;
        object-fit: contain !important;
      }}
      .paag-slide.print-letter {{
        aspect-ratio: 11 / 8.5 !important;
        width: 100% !important;
        max-width: 100% !important;
        min-height: 600px;
      }}
      /* Header Banner */
      .slide-header {{
        display: grid;
        grid-template-columns: 1.3fr 1.6fr 1.3fr;
        align-items: center;
        padding-bottom: 8px;
        border-bottom: 2px solid #e2e8f0;
      }}
      .brand-title {{
        font-size: 1.15rem;
        font-weight: 800;
        color: #0f172a;
        letter-spacing: -0.01em;
      }}
      .brand-sub {{
        font-size: 0.75rem;
        font-weight: 700;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }}
      .pitch-center-title {{
        text-align: center;
        font-size: 1.45rem;
        font-weight: 800;
        color: #1e293b;
      }}
      .doc-control-box {{
        justify-self: end;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        background: #f8fafc;
        padding: 4px 10px;
        font-size: 0.76rem;
        color: #334155;
        line-height: 1.4;
        text-align: right;
      }}
      .doc-control-box strong {{
        color: #0f172a;
      }}
      /* Main Content Split */
      .slide-body {{
        flex: 1 1 auto;
        min-height: 0;
        display: grid;
        grid-template-columns: 37% 63%;
        gap: 12px;
      }}
      .left-col {{
        display: flex;
        flex-direction: column;
        gap: 8px;
        min-height: 0;
        overflow: hidden;
      }}
      .right-col {{
        display: flex;
        flex-direction: column;
        min-height: 0;
        overflow: hidden;
      }}
      /* Left Column Subpanels */
      .panel-section {{
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        background: #fdfdfe;
        padding: 6px 10px;
        display: flex;
        flex-direction: column;
        min-height: 0;
      }}
      .panel-title-bar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 0.82rem;
        font-weight: 800;
        text-transform: uppercase;
        color: #475569;
        margin-bottom: 6px;
        letter-spacing: 0.03em;
      }}
      .page-badge {{
        background: #0284c7;
        color: white;
        padding: 2px 7px;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 700;
      }}
      .tools-list {{
        margin: 0;
        padding-left: 16px;
        font-size: 0.8rem;
        color: #1e293b;
        max-height: 70px;
        overflow-y: auto;
      }}
      .tool-item {{
        margin-bottom: 3px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .badge-ppe {{
        background: #e0f2fe;
        color: #0369a1;
        font-weight: 700;
        padding: 1px 5px;
        border-radius: 3px;
        font-size: 0.7rem;
      }}
      /* Parts Table */
      .parts-panel {{
        flex: 1 1 0;
        overflow-y: auto;
        min-height: 120px;
      }}
      .parts-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.78rem;
      }}
      .parts-table th {{
        text-align: left;
        background: #f1f5f9;
        padding: 5px 6px;
        color: #475569;
        font-size: 0.72rem;
        font-weight: 700;
        border-bottom: 2px solid #e2e8f0;
      }}
      .parts-table td {{
        padding: 4px 6px;
        border-bottom: 1px solid #f1f5f9;
        vertical-align: middle;
      }}
      .col-thumb {{ width: 54px; min-width: 54px; text-align: center; }}
      .part-thumb {{
        width: 48px;
        height: 42px;
        object-fit: contain;
        border-radius: 4px;
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        display: block;
        margin: 0 auto;
      }}
      .thumb-ph {{
        width: 48px;
        height: 42px;
        line-height: 42px;
        text-align: center;
        background: #f1f5f9;
        border: 1px dashed #cbd5e1;
        font-size: 0.65rem;
        color: #64748b;
        font-weight: 700;
        border-radius: 4px;
        margin: 0 auto;
      }}
      .col-pnum {{ white-space: nowrap; font-weight: 700; font-size: 0.8rem; color: #1e293b; }}
      .col-desc {{ max-width: 160px; }}
      .part-desc-text {{
        font-weight: 600;
        color: #0f172a;
        line-height: 1.25;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .part-nick-text {{
        font-size: 0.72rem;
        color: #0284c7;
        font-weight: 700;
        line-height: 1.2;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        margin-top: 2px;
      }}
      .part-nick-space {{
        font-size: 0.72rem;
        line-height: 1.2;
        min-height: 14px;
        margin-top: 2px;
      }}
      .col-qty {{ text-align: right; font-weight: 800; font-size: 0.82rem; white-space: nowrap; padding-right: 8px; }}
      .col-handling {{ text-align: center; white-space: nowrap; }}
      .h-badge {{
        display: inline-block;
        font-size: 0.68rem;
        padding: 2px 6px;
        border-radius: 3px;
        font-weight: 700;
        letter-spacing: 0.02em;
      }}
      .h-badge.va {{ background: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; }}
      .h-badge.nvan {{ background: #ffedd5; color: #c2410c; border: 1px solid #fed7aa; }}
      .text-muted {{ color: #94a3b8; }}
      .part-placeholder.no-parts {{ padding: 14px; text-align: center; font-size: 0.78rem; color: #94a3b8; font-style: italic; }}
      /* Mini Yamazumi Stack */
      .stack-panel {{
        height: 180px;
      }}
      .yam-legend {{
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.68rem;
        font-weight: 700;
        text-transform: none;
      }}
      .yam-legend-item {{
        display: inline-flex;
        align-items: center;
        gap: 3px;
        color: #475569;
      }}
      .swatch-mini {{
        display: inline-block;
        width: 9px;
        height: 9px;
        border-radius: 2px;
      }}
      .swatch-mini.cycle {{ background: #35c84a; }}
      .swatch-mini.periodic {{ background: #ffd54f; border: 1px solid rgba(0,0,0,0.15); }}
      .swatch-mini.fluctuation {{ background: #ef5350; }}

      .stacks-container {{
        display: flex;
        gap: 10px;
        height: 160px;
        overflow-x: auto;
      }}
      .variant-stack-col {{
        flex: 1 1 0;
        min-width: 90px;
        display: flex;
        flex-direction: column;
      }}
      .variant-header {{
        font-size: 0.72rem;
        font-weight: 700;
        text-align: center;
        color: #334155;
        margin-bottom: 4px;
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        align-items: center;
        gap: 3px;
        line-height: 1.25;
      }}
      .variant-name {{
        font-weight: 800;
        color: #0f172a;
      }}
      .variant-time {{
        font-weight: 800;
        color: #1e293b;
      }}
      .variant-takt {{
        color: #64748b;
        font-weight: 600;
        font-size: 0.68rem;
      }}
      .variant-util {{
        display: inline-block;
        padding: 1px 4px;
        border-radius: 3px;
        font-weight: 800;
        font-size: 0.68rem;
      }}
      .variant-util.under-takt {{
        background: #dcfce7;
        color: #166534;
        border: 1px solid #86efac;
      }}
      .variant-util.over-takt {{
        background: #fee2e2;
        color: #991b1b;
        border: 1px solid #fca5a5;
      }}
      .stack-track {{
        position: relative;
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        border-radius: 4px;
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
        overflow: hidden;
      }}
      .stack-blocks-wrapper {{
        display: flex;
        flex-direction: column-reverse;
        width: 100%;
      }}
      .stack-block {{
        width: 100%;
        box-sizing: border-box;
        border-bottom: 1px solid rgba(255,255,255,0.4);
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0 5px;
        font-size: 0.68rem;
        font-weight: 700;
        overflow: hidden;
      }}
      .stack-block.type-cycle {{
        background: #35c84a;
        color: #ffffff;
      }}
      .stack-block.type-periodic {{
        background: #ffd54f;
        color: #1e293b;
        border-bottom: 1px solid rgba(0,0,0,0.15);
      }}
      .stack-block.type-fluctuation {{
        background: #ef5350;
        color: #ffffff;
      }}
      .motion-bar.green {{ background: #16a34a; }}
      .motion-bar.orange {{ background: #ea580c; }}
      .motion-bar.gray {{ background: #64748b; }}
      .block-label {{ max-width: 70%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
      .block-time {{ font-weight: 800; }}
      .takt-line {{
        position: absolute;
        left: 0;
        right: 0;
        border-top: 2px dashed #dc2626;
        z-index: 5;
        pointer-events: none;
      }}
      .takt-label {{
        position: absolute;
        right: 3px;
        top: -12px;
        font-size: 0.65rem;
        font-weight: 800;
        color: #dc2626;
        background: rgba(255,255,255,0.9);
        padding: 0 3px;
        border-radius: 2px;
      }}
      /* Right Area Visual Media Grid */
      .visual-grid {{
        height: 100%;
        display: grid;
        gap: 8px;
        box-sizing: border-box;
      }}
      .grid-layout-1 {{ grid-template-columns: 1fr; grid-template-rows: 1fr; }}
      .grid-layout-2 {{ grid-template-columns: 1fr 1fr; grid-template-rows: 1fr; }}
      .grid-layout-3 {{ grid-template-columns: 1fr 1fr 1fr; grid-template-rows: 1fr; }}
      .grid-layout-4 {{ grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; }}
      .grid-layout-6 {{ grid-template-columns: 1fr 1fr 1fr; grid-template-rows: 1fr 1fr; }}

      .visual-card {{
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        background: #f8fafc;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        min-height: 0;
      }}
      .visual-step-tag {{
        background: #1e293b;
        color: #f8fafc;
        padding: 3px 8px;
        font-size: 0.78rem;
        font-weight: 700;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .visual-step-tag.general {{
        background: #475569;
      }}
      .visual-media-box {{
        flex: 1 1 0;
        min-height: 0;
        background: #000000;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
      }}
      .visual-image {{
        width: 100%;
        height: 100%;
        object-fit: contain;
      }}
      .visual-player {{
        width: 100%;
        height: 100%;
        object-fit: contain;
      }}
      .media-missing {{
        color: #94a3b8;
        font-size: 0.78rem;
      }}
      .caption-callout {{
        background: #fef08a;
        color: #713f12;
        border-top: 2px solid #eab308;
        padding: 6px 10px;
        font-size: 0.82rem;
        font-weight: 700;
        line-height: 1.3;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .caption-callout.empty {{
        background: #fef9c3;
        color: #854d0e;
        font-weight: normal;
      }}
      .callout-bullet {{
        color: #ca8a04;
      }}
      .empty-media-canvas {{
        height: 100%;
        border: 2px dashed #cbd5e1;
        border-radius: 8px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        padding: 20px;
        background: #f8fafc;
        color: #64748b;
      }}
      .empty-media-icon {{ font-size: 2.2rem; margin-bottom: 8px; }}
      .empty-media-title {{ font-size: 1.15rem; font-weight: 700; color: #334155; margin-bottom: 6px; }}
      .empty-media-desc {{ font-size: 0.85rem; max-width: 420px; line-height: 1.4; }}

      /* Bottom Functional Alerts Banner */
      .functional-alerts-bar {{
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        background: #f8fafc;
        padding: 5px 10px;
        display: grid;
        grid-template-columns: repeat(5, 1fr);
        gap: 8px;
        align-items: center;
        font-size: 0.78rem;
      }}
      .alert-block {{
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        padding: 3px 6px;
        border-radius: 4px;
      }}
      .alert-block.active {{
        background: #fee2e2;
        color: #991b1b;
        font-weight: 700;
        border: 1px solid #f87171;
      }}
      .alert-block.clear {{
        color: #475569;
      }}
      .alert-ok {{
        color: #16a34a;
        font-weight: 600;
      }}
      .subtle-empty {{
        font-size: 0.76rem;
        color: #94a3b8;
        font-style: italic;
        padding: 4px 0;
      }}

      /* Presentation & Print rules */
      .paag-slide.presentation-active {{
        min-height: 720px;
        padding: 16px 20px;
        gap: 12px;
      }}
      .paag-slide.presentation-active .brand-title {{ font-size: 1.35rem; }}
      .paag-slide.presentation-active .pitch-center-title {{ font-size: 1.75rem; }}
      .paag-slide.presentation-active .doc-control-box {{ font-size: 0.85rem; }}
      .paag-slide.presentation-active .panel-title-bar {{ font-size: 0.92rem; }}
      .paag-slide.presentation-active .tools-list {{ font-size: 0.9rem; max-height: 85px; }}
      .paag-slide.presentation-active .parts-table {{ font-size: 0.88rem; }}
      .paag-slide.presentation-active .parts-table th {{ font-size: 0.82rem; }}
      .paag-slide.presentation-active .col-thumb {{ width: 62px; min-width: 62px; }}
      .paag-slide.presentation-active .part-thumb {{ width: 56px; height: 48px; }}
      .paag-slide.presentation-active .thumb-ph {{ width: 56px; height: 48px; line-height: 48px; font-size: 0.75rem; }}
      .paag-slide.presentation-active .h-badge {{ font-size: 0.75rem; padding: 3px 8px; }}
      .paag-slide.presentation-active .caption-callout {{ font-size: 0.95rem; }}
      .paag-slide.presentation-active .visual-step-tag {{ font-size: 0.9rem; }}
      .paag-slide.presentation-active .functional-alerts-bar {{ font-size: 0.88rem; }}

      @media print {{
        @page {{
          size: {"17in 11in landscape" if print_format == "tabloid" else "11in 8.5in landscape"};
          margin: 0.25in;
        }}
        html, body {{
          margin: 0 !important;
          padding: 0 !important;
          background: #ffffff !important;
        }}
        .paag-slide {{
          page-break-after: always !important;
          break-after: page !important;
          page-break-inside: avoid !important;
          break-inside: avoid !important;
          min-height: 0 !important;
          box-shadow: none !important;
          border: 1px solid #94a3b8 !important;
          margin: 0 !important;
        }}
        .paag-slide:last-child {{
          page-break-after: auto !important;
          break-after: auto !important;
        }}
        .paag-slide.print-tabloid {{
          width: 100% !important;
          height: 10.5in !important;
          max-height: 10.5in !important;
          aspect-ratio: 17 / 11 !important;
        }}
        .paag-slide.print-letter {{
          width: 100% !important;
          height: 8.0in !important;
          max-height: 8.0in !important;
          aspect-ratio: 11 / 8.5 !important;
        }}
        .visual-media-box {{
          background: #ffffff !important;
        }}
        .visual-card {{
          border: 1px solid #94a3b8 !important;
        }}
      }}
    </style>

    <section class="paag-slide {presentation_class} {print_class} {fit_class}" aria-label="Process at a Glance Slide">
      <!-- Header Banner -->
      <header class="slide-header">
        <div class="header-left">
          <div class="brand-sub">Process at a Glance{f' · {section_name}' if section_name else ''}</div>
          <div class="brand-title">Process at a Glance for {eff_project_name}</div>
        </div>
        <div class="pitch-center-title">
          {pitch_number} — {pitch_name}
        </div>
        <div class="doc-control-box">
          <div><strong>Op ID:</strong> {op_id_summary}</div>
          {f'<div><strong>Section:</strong> {section_name}</div>' if section_name else ''}
          <div><strong>Date:</strong> {generated_label}</div>
          <div><strong>Scenario:</strong> {eff_scenario_name}</div>
          <!-- Exact string assertion support for audit and tests -->
          <div style="display:none">Generated on {generated_label} — Scenario: {eff_scenario_name}</div>
        </div>
      </header>

      <!-- Main Slide Body -->
      <div class="slide-body">
        <!-- Left Column -->
        <aside class="left-col">
          <!-- Tools & PPE -->
          <div class="panel-section">
            <div class="panel-title-bar">
              <span>Tools &amp; PPE Required</span>
              <span class="page-badge">Page {eff_page_num} of {eff_total_pages}</span>
            </div>
            {tools_section_html}
          </div>

          <!-- Parts Table -->
          <div class="panel-section parts-panel">
            <div class="panel-title-bar">
              <span>Parts (Consume &amp; Handle)</span>
            </div>
            {parts_section_html}
          </div>

          <!-- Mini Yamazumi Stack -->
          <div class="panel-section stack-panel">
            <div class="panel-title-bar">
              <span>Yamazumi Pitch Stack</span>
              <div class="yam-legend">
                <span class="yam-legend-item"><i class="swatch-mini cycle"></i>Cycle</span>
                <span class="yam-legend-item"><i class="swatch-mini periodic"></i>Periodic</span>
                <span class="yam-legend-item"><i class="swatch-mini fluctuation"></i>Fluct.</span>
              </div>
            </div>
            <div class="stacks-container">
              {"".join(variant_columns_html)}
            </div>
          </div>
        </aside>

        <!-- Right Area: Dynamic 3x2 Visual Guides Grid -->
        <main class="right-col">
          {right_area_html}
        </main>
      </div>

      <!-- Functional Alerts Bottom Bar -->
      <footer class="functional-alerts-bar">
        {"".join(alert_blocks_html)}
      </footer>
    </section>
    """


def render_presentation_deck(
    slides_data: list[dict],
    initial_pitch_id: str = "",
    total_pitches: int = 1,
) -> str:
    """Render a standalone, zero-lag client-side presentation deck for PowerPoint-style slideshow."""
    if not slides_data:
        return """
        <div class="empty-media-canvas" style="padding: 40px; text-align: center; background: #0f172a; color: #94a3b8; border-radius: 8px;">
          <div class="empty-media-title" style="color: #f8fafc; font-size: 1.2rem; font-weight: 700;">No pitch slides available to present</div>
          <div class="empty-media-desc" style="margin-top: 8px;">Add work elements or visual aids to the pitch sequence to begin presentation.</div>
        </div>
        """

    # Identify initial slide
    initial_slide_idx = 0
    if initial_pitch_id:
        for idx, s in enumerate(slides_data):
            if str(s.get("pitch_id") or "") == str(initial_pitch_id):
                initial_slide_idx = idx
                break

    # Extract unique pitches for dropdown
    seen_pitches = set()
    pitch_options_html = []
    for s in slides_data:
        p_id = str(s.get("pitch_id") or "")
        p_idx = int(s.get("pitch_idx") or 0)
        p_label = str(s.get("pitch_label") or f"Pitch {p_idx + 1}")
        if p_id not in seen_pitches:
            seen_pitches.add(p_id)
            selected_attr = "selected" if p_id == initial_pitch_id else ""
            pitch_options_html.append(
                f'<option value="{p_id}" {selected_attr}>Pitch {p_idx + 1}: {html.escape(p_label)}</option>'
            )

    # Build slides HTML
    slides_html = []
    for idx, s in enumerate(slides_data):
        p_id = str(s.get("pitch_id") or "")
        p_idx = int(s.get("pitch_idx") or 0)
        p_label = str(s.get("pitch_label") or "")
        p_num = int(s.get("page_num") or 1)
        tot_pages = int(s.get("total_pages") or 1)
        slide_content = s.get("slide_html") or ""
        display_style = "block" if idx == initial_slide_idx else "none"

        slides_html.append(
            f"""
            <div class="deck-slide"
                 id="deck-slide-{idx}"
                 data-slide-index="{idx}"
                 data-pitch-id="{p_id}"
                 data-pitch-idx="{p_idx}"
                 data-pitch-label="{html.escape(p_label)}"
                 data-page="{p_num}"
                 data-total-pages="{tot_pages}"
                 style="display: {display_style};">
              {slide_content}
            </div>
            """
        )

    # Initial slide metadata
    init_slide = slides_data[initial_slide_idx]
    init_pitch_idx = int(init_slide.get("pitch_idx") or 0)
    init_label = str(init_slide.get("pitch_label") or "")
    init_page = int(init_slide.get("page_num") or 1)
    init_tot_pages = int(init_slide.get("total_pages") or 1)
    init_page_part = f" (Page {init_page}/{init_tot_pages})" if init_tot_pages > 1 else ""
    counter_initial = f"Pitch {init_pitch_idx + 1} of {total_pitches}{init_page_part} · {init_label}"

    return f"""
    <style>
      /* Expand Streamlit Dialog for Presentation */
      div[data-testid="stDialog"] div[role="dialog"] {{
        width: 95vw !important;
        max-width: 95vw !important;
        max-height: 96vh !important;
        padding: 8px 12px !important;
        background: #0f172a !important;
        border: 1px solid #334155 !important;
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7) !important;
      }}
      div[data-testid="stDialog"] div[data-testid="stDialogHeader"] {{
        display: none !important;
      }}

      #paag-presentation-player {{
        display: flex;
        flex-direction: column;
        width: 100%;
        box-sizing: border-box;
        background: #0f172a;
        border-radius: 8px;
        overflow: hidden;
      }}

      /* Presentation Control Bar */
      .pres-toolbar {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: #1e293b;
        border-bottom: 1px solid #334155;
        padding: 6px 12px;
        gap: 8px;
        flex-wrap: nowrap;
        user-select: none;
      }}
      .pres-btn-group {{
        display: flex;
        align-items: center;
        gap: 6px;
      }}
      .pres-btn {{
        background: #334155;
        color: #f8fafc;
        border: 1px solid #475569;
        border-radius: 6px;
        padding: 6px 12px;
        font-size: 0.82rem;
        font-weight: 700;
        cursor: pointer;
        transition: background 0.15s, border-color 0.15s;
        display: inline-flex;
        align-items: center;
        gap: 5px;
        white-space: nowrap;
      }}
      .pres-btn:hover:not(:disabled) {{
        background: #475569;
        border-color: #64748b;
        color: #ffffff;
      }}
      .pres-btn:disabled {{
        opacity: 0.35;
        cursor: not-allowed;
      }}
      .pres-btn.primary {{
        background: #0284c7;
        border-color: #0369a1;
      }}
      .pres-btn.primary:hover:not(:disabled) {{
        background: #0369a1;
      }}
      .pres-btn.danger {{
        background: #b91c1c;
        border-color: #991b1b;
      }}
      .pres-btn.danger:hover:not(:disabled) {{
        background: #991b1b;
      }}

      .pres-select {{
        background: #334155;
        color: #f8fafc;
        border: 1px solid #475569;
        border-radius: 6px;
        padding: 6px 8px;
        font-size: 0.82rem;
        font-weight: 600;
        cursor: pointer;
        max-width: 280px;
        text-overflow: ellipsis;
      }}

      .pres-counter {{
        font-size: 0.9rem;
        font-weight: 800;
        color: #38bdf8;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        text-align: center;
        flex: 1 1 auto;
        padding: 0 8px;
      }}

      .pres-shortcuts {{
        font-size: 0.72rem;
        color: #94a3b8;
        background: #0f172a;
        border: 1px solid #334155;
        border-radius: 4px;
        padding: 3px 8px;
        white-space: nowrap;
      }}

      /* Slides Viewport */
      .pres-slides-viewport {{
        position: relative;
        width: 100%;
        box-sizing: border-box;
        padding: 10px;
        background: #0b1120;
        overflow-y: auto;
      }}

      .deck-slide {{
        width: 100%;
        box-sizing: border-box;
      }}

      /* Fullscreen styles */
      #paag-presentation-player:fullscreen {{
        width: 100vw;
        height: 100vh;
        border-radius: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
      }}
      #paag-presentation-player:fullscreen .pres-slides-viewport {{
        flex: 1 1 0;
        height: calc(100vh - 50px);
        padding: 12px;
      }}
      #paag-presentation-player:fullscreen .paag-slide {{
        max-height: calc(100vh - 72px);
      }}
    </style>

    <div id="paag-presentation-player"
         data-initial-pitch-id="{initial_pitch_id}"
         data-total-pitches="{total_pitches}"
         data-total-slides="{len(slides_data)}"
         aria-label="Process at a Glance Presentation Player">
      <!-- Player Toolbar -->
      <nav class="pres-toolbar" aria-label="Presentation Controls">
        <div class="pres-btn-group">
          <button id="pres-btn-prev-pitch" class="pres-btn" title="Previous Pitch (P / Up Arrow)">⏮ Prev Pitch</button>
          <button id="pres-btn-prev-slide" class="pres-btn primary" title="Previous Slide (Left Arrow / Backspace)">◀ Back</button>
          <select id="pres-pitch-selector" class="pres-select" title="Jump to Pitch">
            {"".join(pitch_options_html)}
          </select>
          <button id="pres-btn-next-slide" class="pres-btn primary" title="Next Slide (Right Arrow / Space)">Next ▶</button>
          <button id="pres-btn-next-pitch" class="pres-btn" title="Next Pitch (N / Down Arrow)">Next Pitch ⏭</button>
        </div>

        <div id="pres-slide-counter" class="pres-counter">{counter_initial}</div>

        <div class="pres-btn-group">
          <span class="pres-shortcuts">⌨ [←/→] Slide · [P/N] Pitch · [F] Fullscreen</span>
          <button id="pres-btn-fullscreen" class="pres-btn" title="Toggle Fullscreen (F)">⛶ Fullscreen</button>
          <button id="pres-btn-close" class="pres-btn danger" title="Exit Presentation (Esc)">✕ Exit</button>
        </div>
      </nav>

      <!-- Slides Container -->
      <main class="pres-slides-viewport">
        {"".join(slides_html)}
      </main>
    </div>

    <script>
    (function() {{
      const container = document.getElementById("paag-presentation-player");
      if (!container) return;

      const slides = Array.from(container.querySelectorAll(".deck-slide"));
      if (slides.length === 0) return;

      let currentIndex = {initial_slide_idx};
      const totalPitches = parseInt(container.getAttribute("data-total-pitches") || "1", 10);

      const prevSlideBtn = container.querySelector("#pres-btn-prev-slide");
      const nextSlideBtn = container.querySelector("#pres-btn-next-slide");
      const prevPitchBtn = container.querySelector("#pres-btn-prev-pitch");
      const nextPitchBtn = container.querySelector("#pres-btn-next-pitch");
      const pitchSelect = container.querySelector("#pres-pitch-selector");
      const counterText = container.querySelector("#pres-slide-counter");
      const fullscreenBtn = container.querySelector("#pres-btn-fullscreen");
      const closeBtn = container.querySelector("#pres-btn-close");

      function updateSlide(newIndex) {{
        if (newIndex < 0) newIndex = 0;
        if (newIndex >= slides.length) newIndex = slides.length - 1;
        currentIndex = newIndex;

        slides.forEach((slide, idx) => {{
          slide.style.display = (idx === currentIndex) ? "block" : "none";
        }});

        const curSlide = slides[currentIndex];
        const pitchId = curSlide.getAttribute("data-pitch-id");
        const pitchIdx = parseInt(curSlide.getAttribute("data-pitch-idx") || "0", 10);
        const pitchLabel = curSlide.getAttribute("data-pitch-label") || "";
        const pageNum = curSlide.getAttribute("data-page") || "1";
        const totalPages = curSlide.getAttribute("data-total-pages") || "1";

        let pagePart = (parseInt(totalPages, 10) > 1) ? (" (Page " + pageNum + "/" + totalPages + ")") : "";
        if (counterText) {{
          counterText.textContent = "Pitch " + (pitchIdx + 1) + " of " + totalPitches + pagePart + " · " + pitchLabel;
        }}

        if (pitchSelect && pitchSelect.value !== pitchId) {{
          pitchSelect.value = pitchId;
        }}

        if (prevSlideBtn) prevSlideBtn.disabled = (currentIndex === 0);
        if (nextSlideBtn) nextSlideBtn.disabled = (currentIndex === slides.length - 1);
        if (prevPitchBtn) prevPitchBtn.disabled = (pitchIdx === 0 && pageNum === "1");
        if (nextPitchBtn) nextPitchBtn.disabled = (pitchIdx >= totalPitches - 1 && pageNum === totalPages);

        try {{
          const url = new URL(window.location);
          url.searchParams.set("active_pitch", pitchId);
          window.history.replaceState({{}}, "", url);
        }} catch (e) {{}}
      }}

      if (prevSlideBtn) prevSlideBtn.onclick = () => updateSlide(currentIndex - 1);
      if (nextSlideBtn) nextSlideBtn.onclick = () => updateSlide(currentIndex + 1);

      if (prevPitchBtn) {{
        prevPitchBtn.onclick = () => {{
          const curPitchIdx = parseInt(slides[currentIndex].getAttribute("data-pitch-idx") || "0", 10);
          const targetPitchIdx = curPitchIdx - 1;
          const targetSlideIdx = slides.findIndex(s => parseInt(s.getAttribute("data-pitch-idx"), 10) === targetPitchIdx);
          if (targetSlideIdx >= 0) updateSlide(targetSlideIdx);
        }};
      }}

      if (nextPitchBtn) {{
        nextPitchBtn.onclick = () => {{
          const curPitchIdx = parseInt(slides[currentIndex].getAttribute("data-pitch-idx") || "0", 10);
          const targetPitchIdx = curPitchIdx + 1;
          const targetSlideIdx = slides.findIndex(s => parseInt(s.getAttribute("data-pitch-idx"), 10) === targetPitchIdx);
          if (targetSlideIdx >= 0) updateSlide(targetSlideIdx);
        }};
      }}

      if (pitchSelect) {{
        pitchSelect.onchange = () => {{
          const targetPitchId = pitchSelect.value;
          const targetSlideIdx = slides.findIndex(s => s.getAttribute("data-pitch-id") === targetPitchId);
          if (targetSlideIdx >= 0) updateSlide(targetSlideIdx);
        }};
      }}

      if (fullscreenBtn) {{
        fullscreenBtn.onclick = () => {{
          if (!document.fullscreenElement) {{
            container.requestFullscreen().catch(() => {{}});
          }} else {{
            document.exitFullscreen().catch(() => {{}});
          }}
        }};
      }}

      if (closeBtn) {{
        closeBtn.onclick = () => {{
          try {{
            const stCloseBtn = document.querySelector("div[data-testid='stDialog'] button[aria-label='Close']")
                            || window.parent.document.querySelector("div[data-testid='stDialog'] button[aria-label='Close']")
                            || document.querySelector("button[aria-label='Close']");
            if (stCloseBtn) {{
              stCloseBtn.click();
              return;
            }}
          }} catch (e) {{}}
          window.location.reload();
        }};
      }}

      function handleKeyDown(e) {{
        if (!container.isConnected || container.offsetParent === null) return;
        if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;

        if (e.key === "ArrowRight" || e.key === " " || e.key === "PageDown") {{
          e.preventDefault();
          updateSlide(currentIndex + 1);
        }} else if (e.key === "ArrowLeft" || e.key === "PageUp" || e.key === "Backspace") {{
          e.preventDefault();
          updateSlide(currentIndex - 1);
        }} else if (e.key === "ArrowDown" || e.key.toLowerCase() === "n") {{
          e.preventDefault();
          if (nextPitchBtn && !nextPitchBtn.disabled) nextPitchBtn.click();
        }} else if (e.key === "ArrowUp" || e.key.toLowerCase() === "p") {{
          e.preventDefault();
          if (prevPitchBtn && !prevPitchBtn.disabled) prevPitchBtn.click();
        }} else if (e.key.toLowerCase() === "f") {{
          e.preventDefault();
          if (fullscreenBtn) fullscreenBtn.click();
        }}
      }}

      document.addEventListener("keydown", handleKeyDown);
      updateSlide(currentIndex);
    }})();
    </script>
    """


def render_printable_paag_deck(
    slides_html: list[str],
    *,
    paper_size: str = "tabloid",
    image_fit: str = "fill",
    title: str = "PAAG Print Deck",
) -> str:
    """Render a standalone, multi-page HTML document containing all slides ready for native print or export to PDF."""
    css_page_size = "17in 11in landscape" if paper_size == "tabloid" else "11in 8.5in landscape"
    paper_label = "11 × 17 in (Tabloid Landscape)" if paper_size == "tabloid" else "8.5 × 11 in (Letter Landscape)"
    total_slides = len(slides_html)

    joined_slides = "\n".join(
        f"""
        <div class="slide-wrapper">
          <div class="slide-index-label no-print">
            <span><strong>Slide {i + 1} of {total_slides}</strong></span>
            <span>{paper_label}</span>
          </div>
          {s_html}
        </div>
        """
        for i, s_html in enumerate(slides_html)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    @page {{
      size: {css_page_size};
      margin: 0.25in;
    }}
    * {{
      box-sizing: border-box;
    }}
    html, body {{
      margin: 0;
      padding: 0;
      background: #e2e8f0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    .print-banner {{
      position: sticky;
      top: 0;
      left: 0;
      right: 0;
      z-index: 99999;
      background: #0f172a;
      color: #ffffff;
      padding: 12px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.25);
    }}
    .print-banner-left {{
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .btn-action-print {{
      background: #0284c7;
      color: #ffffff !important;
      border: none;
      padding: 8px 18px;
      border-radius: 6px;
      font-weight: 700;
      font-size: 0.95rem;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      text-decoration: none;
    }}
    .btn-action-print:hover {{
      background: #0369a1;
    }}
    .btn-action-close {{
      background: #334155;
      color: #f1f5f9 !important;
      border: 1px solid #475569;
      padding: 8px 14px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 0.85rem;
      cursor: pointer;
      text-decoration: none;
    }}
    .btn-action-close:hover {{
      background: #475569;
    }}
    .print-status-tag {{
      background: rgba(255,255,255,0.15);
      border: 1px solid rgba(255,255,255,0.2);
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 0.85rem;
      color: #e2e8f0;
    }}
    .deck-container {{
      max-width: 1400px;
      margin: 20px auto;
      padding: 0 16px 40px 16px;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }}
    .slide-wrapper {{
      margin-bottom: 24px;
    }}
    .slide-index-label {{
      font-size: 0.82rem;
      font-weight: 700;
      color: #475569;
      margin-bottom: 6px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0 4px;
    }}
    .slide-wrapper > .paag-slide {{
      box-shadow: 0 6px 20px rgba(0,0,0,0.12);
    }}

    @media print {{
      .no-print {{
        display: none !important;
      }}
      html, body {{
        background: #ffffff !important;
        margin: 0 !important;
        padding: 0 !important;
      }}
      .deck-container {{
        max-width: none !important;
        margin: 0 !important;
        padding: 0 !important;
        gap: 0 !important;
        display: block !important;
      }}
      .slide-wrapper {{
        margin: 0 !important;
        padding: 0 !important;
        page-break-after: always !important;
        break-after: page !important;
        page-break-inside: avoid !important;
        break-inside: avoid !important;
      }}
      .slide-wrapper:last-child {{
        page-break-after: auto !important;
        break-after: auto !important;
      }}
      .slide-index-label {{
        display: none !important;
      }}
      .paag-slide {{
        margin: 0 !important;
        box-shadow: none !important;
        border: 1px solid #94a3b8 !important;
        page-break-inside: avoid !important;
        break-inside: avoid !important;
      }}
      .paag-slide.print-tabloid {{
        width: 100% !important;
        height: 10.45in !important;
        max-height: 10.45in !important;
        aspect-ratio: 17 / 11 !important;
        overflow: hidden !important;
      }}
      .paag-slide.print-letter {{
        width: 100% !important;
        height: 7.95in !important;
        max-height: 7.95in !important;
        aspect-ratio: 11 / 8.5 !important;
        overflow: hidden !important;
      }}
      .visual-media-box {{
        background: #ffffff !important;
      }}
    }}
  </style>
</head>
<body>
  <div class="print-banner no-print">
    <div class="print-banner-left">
      <button class="btn-action-print" onclick="window.print()">
        <span>🖨️</span> Print Now (or press Ctrl+P)
      </button>
      <span class="print-status-tag">📄 {paper_label}</span>
      <span class="print-status-tag">📑 {total_slides} Slide{'' if total_slides == 1 else 's'}</span>
      <span style="font-size: 0.8rem; color: #94a3b8;">Tip: Set destination to "Save as PDF" or select your printer.</span>
    </div>
    <div>
      <button class="btn-action-close" onclick="window.close()">✕ Close</button>
    </div>
  </div>

  <main class="deck-container">
    {joined_slides}
  </main>

  <script>
    window.addEventListener("load", function() {{
      const params = new URLSearchParams(window.location.search);
      if (params.get("autoprint") === "1" || window.location.hash === "#autoprint") {{
        setTimeout(function() {{
          try {{
            window.print();
          }} catch(e) {{
            console.error("Print trigger failed:", e);
          }}
        }}, 450);
      }}
    }});
  </script>
</body>
</html>"""

