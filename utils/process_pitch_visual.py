from __future__ import annotations

import base64
import html
import mimetypes
from datetime import date
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus


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


SOURCE_CODE_LABELS: dict[str, str] = {
    "1": "1 - Purchased Part",
    "+1": "+1 - Purchased Asm",
    "2": "2",
    "2.4": "2.4 - From AP3",
    "3": "3 - Mfg Part",
    "4": "4",
    "5": "5 - Asm (Disassembly no)",
    "6": "6 - Asm (Disassembly yes)",
    "7": "7",
    "8": "8 - Component of Purchased Asm",
}


def _part_popover_content(part: dict) -> str:
    p_num = _text(part.get("part_number") or "Part")
    p_desc = _text(part.get("description") or part.get("part_name") or "")
    p_nick = _text(part.get("factory_nickname") or "")
    p_windchill = _text(part.get("official_windchill_part_name") or "")
    p_rev = _text(part.get("revision") or "")
    p_make_buy = _text(part.get("make_buy") or "")
    p_subsystem = _text(part.get("subsystem") or "")
    p_src_code = str(part.get("source_code") or "").strip()
    p_pits_id = _text(part.get("pits_tracker_number") or "")
    p_part_code = _text(part.get("part_code") or "")
    p_weight = part.get("weight_lb")
    p_model_app = _text(part.get("model_applicability") or "")
    p_de = _text(part.get("design_engineer") or "")
    p_te = _text(part.get("technology_engineer") or "")
    p_ame = _text(part.get("ame_tooling_engineer") or "")
    p_buyer = _text(part.get("buyer_gcl") or "")
    p_pmqe = _text(part.get("pmqe_aqe") or "")
    p_notes = _text(part.get("notes") or "")
    p_qty = _clean_number(part.get("quantity") or part.get("total_quantity") or part.get("qty") or 1)
    p_img_url = _media_data_url(part.get("image_path") or part.get("thumbnail_path"))

    is_asm_group = bool(part.get("is_assembly_group"))
    mini_bom = part.get("mini_bom") or []
    if not is_asm_group:
        import re
        if (
            bool(mini_bom)
            or bool(re.search(r"G\d{2,}", p_num, re.IGNORECASE))
            or str(p_make_buy).strip().casefold() in {"make", "asm", "subassembly"}
            or p_src_code in {"+1", "5", "6"}
        ):
            is_asm_group = True

    # Handling classification
    h_types = part.get("handling_types") or []
    if not h_types and part.get("handling_type"):
        h_types = [part.get("handling_type")]
    h_labels = []
    for ht in h_types:
        ht_clean = str(ht).strip()
        if ht_clean.casefold() in {"consume", "c"}:
            h_labels.append("Consume (VA)")
        elif ht_clean.casefold() in {"handle", "h"}:
            h_labels.append("Handle (NVAN)")
        elif ht_clean:
            h_labels.append(ht_clean)
    handling_str = ", ".join(h_labels) if h_labels else "Unclassified"

    src_code_display = SOURCE_CODE_LABELS.get(p_src_code, p_src_code)

    # Badges
    badges_html = []
    if is_asm_group:
        badges_html.append('<span class="popover-badge asm-group">Assembly Group</span>')
    if p_rev:
        badges_html.append(f'<span class="popover-badge rev">Rev {p_rev}</span>')
    if p_make_buy:
        badges_html.append(f'<span class="popover-badge make-buy">{p_make_buy}</span>')
    for ht in h_types:
        ht_clean = str(ht).strip()
        if ht_clean.casefold() in {"consume", "c"}:
            badges_html.append('<span class="h-badge va">Consume</span>')
        elif ht_clean.casefold() in {"handle", "h"}:
            badges_html.append('<span class="h-badge nvan">Handle</span>')
        elif ht_clean:
            badges_html.append(f'<span class="h-badge">{_text(ht_clean)}</span>')

    # Media preview (Enlarged banner)
    img_preview_html = (
        f'<div class="popover-image-banner"><img src="{p_img_url}" alt="{p_num}" class="popover-large-img" /></div>'
        if p_img_url
        else '<div class="popover-no-image-cue"><span>📷 No CAD image attached</span></div>'
    )

    # Grid items
    grid_items = [
        f'<div class="popover-grid-item"><span class="grid-label">Pitch Qty</span><span class="grid-val">{p_qty}</span></div>',
        f'<div class="popover-grid-item"><span class="grid-label">Handling</span><span class="grid-val">{handling_str}</span></div>',
    ]
    if p_subsystem:
        grid_items.append(
            f'<div class="popover-grid-item"><span class="grid-label">Subsystem</span><span class="grid-val" title="{p_subsystem}">{p_subsystem}</span></div>'
        )
    if src_code_display:
        grid_items.append(
            f'<div class="popover-grid-item"><span class="grid-label">Source Code</span><span class="grid-val" title="{src_code_display}">{src_code_display}</span></div>'
        )
    if p_pits_id:
        grid_items.append(
            f'<div class="popover-grid-item"><span class="grid-label">PITS ID</span><span class="grid-val">{p_pits_id}</span></div>'
        )
    if p_part_code:
        grid_items.append(
            f'<div class="popover-grid-item"><span class="grid-label">Part Code</span><span class="grid-val">{p_part_code}</span></div>'
        )
    if p_weight is not None:
        try:
            w_val = float(p_weight)
            if w_val > 0:
                grid_items.append(
                    f'<div class="popover-grid-item"><span class="grid-label">Weight</span><span class="grid-val">{_clean_number(w_val)} lb</span></div>'
                )
        except (ValueError, TypeError):
            pass
    if p_model_app and p_model_app.strip().casefold() != "all":
        grid_items.append(
            f'<div class="popover-grid-item"><span class="grid-label">Models</span><span class="grid-val" title="{p_model_app}">{p_model_app}</span></div>'
        )

    # Dedicated Assigned Engineers Section
    eng_items_html = [
        f"""<div class="eng-item">
              <span class="eng-role-tag de">DE</span>
              <div class="eng-info">
                <span class="eng-title">Design Engineer</span>
                <span class="eng-val" title="{p_de or '—'}">{p_de or '—'}</span>
              </div>
            </div>""",
        f"""<div class="eng-item">
              <span class="eng-role-tag te">TE</span>
              <div class="eng-info">
                <span class="eng-title">Technology Engineer</span>
                <span class="eng-val" title="{p_te or '—'}">{p_te or '—'}</span>
              </div>
            </div>""",
    ]
    if p_ame:
        eng_items_html.append(
            f"""<div class="eng-item">
                  <span class="eng-role-tag ame">AME</span>
                  <div class="eng-info">
                    <span class="eng-title">AME / Tooling</span>
                    <span class="eng-val" title="{p_ame}">{p_ame}</span>
                  </div>
                </div>"""
        )
    if p_pmqe:
        eng_items_html.append(
            f"""<div class="eng-item">
                  <span class="eng-role-tag aqe">AQE</span>
                  <div class="eng-info">
                    <span class="eng-title">PMQE / AQE</span>
                    <span class="eng-val" title="{p_pmqe}">{p_pmqe}</span>
                  </div>
                </div>"""
        )
    if p_buyer:
        eng_items_html.append(
            f"""<div class="eng-item">
                  <span class="eng-role-tag buyer">Buyer</span>
                  <div class="eng-info">
                    <span class="eng-title">Buyer / GCL</span>
                    <span class="eng-val" title="{p_buyer}">{p_buyer}</span>
                  </div>
                </div>"""
        )

    engineers_section_html = f"""
    <div class="popover-engineers-section">
      <div class="popover-section-label">Assigned Engineers (Parts Catalog)</div>
      <div class="popover-engineers-grid">
        {''.join(eng_items_html)}
      </div>
    </div>
    """

    # Assembly Mini-BOM Makeup Section
    minibom_section_html = ""
    if is_asm_group:
        if mini_bom:
            rows_html = []
            for item in mini_bom:
                c_num = _text(item.get("part_number") or "")
                c_desc = _text(item.get("description") or item.get("factory_nickname") or "—")
                c_qty = _clean_number(item.get("quantity") or 1)
                c_eng = _text(item.get("design_engineer") or item.get("technology_engineer") or "")
                rows_html.append(
                    f"""<tr>
                          <td class="minibom-pnum">{c_num}</td>
                          <td class="minibom-desc" title="{c_desc}">{c_desc}</td>
                          <td class="minibom-qty">×{c_qty}</td>
                          <td class="minibom-eng" title="{c_eng or '—'}">{c_eng or '—'}</td>
                        </tr>"""
                )
            minibom_section_html = f"""
            <div class="popover-minibom-section">
              <div class="popover-section-label">
                <span>Mini BOM Makeup</span>
                <span class="minibom-count-pill">{len(mini_bom)} component{'s' if len(mini_bom) != 1 else ''}</span>
              </div>
              <div class="minibom-scroll">
                <table class="minibom-table">
                  <thead>
                    <tr>
                      <th>Part #</th>
                      <th>Description</th>
                      <th class="qty-th">Qty</th>
                      <th>Engineer</th>
                    </tr>
                  </thead>
                  <tbody>
                    {''.join(rows_html)}
                  </tbody>
                </table>
              </div>
            </div>
            """
        else:
            minibom_section_html = """
            <div class="popover-minibom-section">
              <div class="popover-section-label">Mini BOM Makeup</div>
              <div class="minibom-empty-note">Assembly group number — no child components defined in Assemblies or PITS BOM yet.</div>
            </div>
            """

    # Linked steps
    linked_steps = part.get("linked_steps") or []
    linked_steps_html = ""
    if linked_steps:
        steps_badges = " ".join(
            f'<span class="popover-step-pill">{_text(s)}</span>' for s in linked_steps
        )
        linked_steps_html = f"""
        <div class="popover-steps-box">
          <div class="popover-steps-label">Used In Process Step(s):</div>
          <div class="popover-steps-list">{steps_badges}</div>
        </div>
        """

    # Notes
    notes_html = (
        f'<div class="popover-notes-box"><strong>Notes:</strong> {p_notes}</div>'
        if p_notes
        else ""
    )

    # Nickname banner
    nick_html = (
        f'<div class="popover-nick-banner">🏷️ Factory Nickname: <strong>{p_nick}</strong></div>'
        if p_nick
        else ""
    )

    # Official Windchill CAD name if distinct
    cad_html = (
        f'<div class="popover-cad-name">Official CAD: {p_windchill}</div>'
        if p_windchill and p_windchill != p_desc
        else ""
    )

    p_id = str(part.get("part_id") or part.get("id") or "").strip()
    raw_p_num = str(part.get("part_number") or "").strip()
    url_params = []
    if p_id:
        url_params.append(f"part_id={quote_plus(p_id)}")
    if raw_p_num and raw_p_num != "Part":
        url_params.append(f"part_number={quote_plus(raw_p_num)}")
    query_str = f"?{'&'.join(url_params)}" if url_params else ""
    parts_catalog_url = f"./parts{query_str}#part-details-section"

    return f"""
    <div class="part-popover-card">
      <div class="part-popover-header">
        {img_preview_html}
        <div class="part-popover-title-row">
          <span class="part-popover-num">{p_num}</span>
          <div class="part-popover-badges">{' '.join(badges_html)}</div>
        </div>
        {nick_html}
      </div>
      <div class="part-popover-body">
        <div class="popover-part-desc">{p_desc or 'No description available'}</div>
        {cad_html}
        <div class="part-popover-grid">
          {''.join(grid_items)}
        </div>
        {engineers_section_html}
        {minibom_section_html}
        {linked_steps_html}
        {notes_html}
      </div>
      <div class="popover-footer">
        <a href="{parts_catalog_url}" target="_top" class="popover-action-link">Open in Parts Catalog ↗</a>
      </div>
    </div>
    """


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
                w_type = str(el.get("work_type") or "").strip()
                color = str(el.get("motion_color") or "").strip().lower()
                if w_type.lower() == "cycle":
                    color = "green"
                elif not color or color not in {"green", "orange", "gray"}:
                    color = "green" if not w_type or w_type.lower() == "cycle" else "gray"
                stack_elements.append({
                    "id": el.get("work_element_id") or el.get("id"),
                    "description": el.get("yamazumi_description") or el.get("operation") or "",
                    "time_s": float(el.get("time_s") or 0.0),
                    "motion_color": color,
                    "motion_classification": el.get("motion_classification") or ("Cycle" if color == "green" else "Unclassified"),
                    "work_type": w_type or ("Cycle" if color == "green" else ""),
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

        popover_content = _part_popover_content(part)

        part_rows_html.append(
            f"""
            <tr class="part-row" data-part-num="{p_num}">
              <td class="col-thumb">{img_tag}</td>
              <td class="col-pnum">
                <div class="part-pnum-container">
                  <strong>{p_num}</strong>
                  <span class="part-info-cue" title="Hover for part details">i</span>
                  <div class="part-popover" role="tooltip">
                    <div class="part-popover-bridge"></div>
                    {popover_content}
                  </div>
                </div>
              </td>
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
    # Map work elements on this pitch to 1-based sequential step numbers
    all_pitch_elements = list(pitch.get("elements", []))
    if not all_pitch_elements and elements_list:
        all_pitch_elements = list(elements_list)

    step_num_by_wid: dict[str, int] = {}
    for idx, el in enumerate(all_pitch_elements):
        s_num = idx + 1
        w_id = str(el.get("work_element_id") or el.get("id") or "").strip()
        y_id = str(el.get("yamazumi_element_id") or "").strip()
        if w_id:
            step_num_by_wid[w_id] = s_num
        if y_id:
            step_num_by_wid[y_id] = s_num

    # If step_num_by_wid is still empty, populate from yamazumi_stacks
    if not step_num_by_wid and yamazumi_stacks:
        cur_idx = 1
        for v_data in yamazumi_stacks.values():
            v_els = v_data.get("elements", []) if isinstance(v_data, dict) else (v_data if isinstance(v_data, list) else [])
            for e in v_els:
                if not isinstance(e, dict):
                    continue
                e_wid = str(e.get("work_element_id") or e.get("process_element_id") or e.get("id") or "").strip()
                if e_wid and e_wid not in step_num_by_wid:
                    step_num_by_wid[e_wid] = cur_idx
                    cur_idx += 1

    # Map visual media to tagged step numbers
    media_step_numbers_map: dict[str, list[int]] = {}
    all_tagged_step_nums: set[int] = set()

    for m_item in (visual_media or []):
        m_id = str(m_item.get("id") or "")
        tagged_steps: list[int] = []
        for t in m_item.get("tagged_work_elements", []):
            t_wid = str(t.get("work_element_id") or "").strip()
            if t_wid in step_num_by_wid:
                tagged_steps.append(step_num_by_wid[t_wid])
        if not tagged_steps:
            for t_wid in m_item.get("tagged_work_element_ids", []):
                t_clean = str(t_wid).strip()
                if t_clean in step_num_by_wid:
                    tagged_steps.append(step_num_by_wid[t_clean])
        tagged_steps = sorted(list(set(tagged_steps)))
        if m_id:
            media_step_numbers_map[m_id] = tagged_steps
        all_tagged_step_nums.update(tagged_steps)

    variant_columns_html: list[str] = []
    max_variant_time = 0.0
    for v_name, v_data in yamazumi_stacks.items():
        v_elements = v_data.get("elements", []) if isinstance(v_data, dict) else (v_data if isinstance(v_data, list) else [])
        v_time = sum(float(e.get("time_s") or 0.0) for e in v_elements if isinstance(e, dict))
        if v_time > max_variant_time:
            max_variant_time = v_time

    # Chart height references
    ref_time = max(max_variant_time, eff_takt_s, 1.0)
    chart_px_height = 175

    for v_name, v_data in yamazumi_stacks.items():
        v_elements = [
            e for e in (v_data.get("elements", []) if isinstance(v_data, dict) else (v_data if isinstance(v_data, list) else []))
            if isinstance(e, dict)
        ]
        v_total_s = sum(float(e.get("time_s") or 0.0) for e in v_elements)
        n_elems = len(v_elements)

        # Properly scale element heights to ensure all blocks fit within chart_px_height without clipping
        allocated_heights: list[int] = []
        if n_elems > 0:
            target_stack_h = (
                int(round(chart_px_height * min(1.0, v_total_s / ref_time)))
                if ref_time > 0 and v_total_s > 0
                else min(chart_px_height, n_elems * 24)
            )
            target_stack_h = max(target_stack_h, n_elems * 8)
            target_stack_h = min(target_stack_h, chart_px_height)

            desired_min = 18
            if n_elems * desired_min > target_stack_h:
                desired_min = max(7, target_stack_h // n_elems)

            raw_heights = [
                chart_px_height * (float(e.get("time_s") or 0.0) / ref_time) if ref_time > 0 else (target_stack_h / n_elems)
                for e in v_elements
            ]
            allocated_heights = [max(desired_min, int(round(h))) for h in raw_heights]
            total_alloc = sum(allocated_heights)

            if total_alloc > chart_px_height and total_alloc > 0:
                scale_factor = chart_px_height / total_alloc
                allocated_heights = [max(7, int(h * scale_factor)) for h in allocated_heights]
                drift = chart_px_height - sum(allocated_heights)
                if drift != 0 and allocated_heights:
                    allocated_heights[-1] = max(7, allocated_heights[-1] + drift)
            elif total_alloc > target_stack_h and target_stack_h >= n_elems * desired_min:
                scale_factor = target_stack_h / total_alloc
                allocated_heights = [max(desired_min, int(h * scale_factor)) for h in allocated_heights]

        blocks_html: list[str] = []
        for idx_e, e in enumerate(v_elements):
            e_desc = _text(e.get("description") or e.get("yamazumi_description") or "")
            e_time = float(e.get("time_s") or 0.0)
            work_type = str(e.get("work_type") or "").strip()
            work_type_lower = work_type.lower()
            if work_type_lower == "periodic":
                type_class = "type-periodic"
                e_color = "orange"
            elif work_type_lower == "fluctuation":
                type_class = "type-fluctuation"
                e_color = "gray"
            elif work_type_lower == "cycle":
                # Cycle work on Yamazumi: keep it green, no orange or gray classifications
                type_class = "type-cycle"
                e_color = "green"
            else:
                e_color = str(e.get("motion_color") or "green").strip().lower()
                if e_color not in {"green", "orange", "gray"}:
                    e_color = "green"
                if e_color == "green":
                    type_class = "type-cycle"
                elif e_color == "orange":
                    type_class = "type-periodic"
                elif e_color == "gray":
                    type_class = "type-fluctuation"
                else:
                    type_class = "type-cycle"

            b_height = allocated_heights[idx_e] if idx_e < len(allocated_heights) else (max(16, int(chart_px_height * (e_time / ref_time))) if ref_time > 0 else 16)
            compact_class = "compact" if b_height < 15 else ""

            e_wid = str(e.get("work_element_id") or e.get("process_element_id") or e.get("id") or "").strip()
            step_num = step_num_by_wid.get(e_wid, 0)
            if step_num == 0:
                step_num = step_num_by_wid.get(str(e.get("id") or "").strip(), 0)

            has_media = step_num > 0 and step_num in all_tagged_step_nums
            step_badge_html = f'<span class="stack-step-badge">{step_num}</span>' if step_num > 0 else ""
            cam_icon_html = f'<span class="stack-cam-icon" title="Visual aid attached for Step {step_num}">📷</span>' if has_media else ""
            step_attr = f'data-step-num="{step_num}"' if step_num > 0 else ""
            visual_class = "has-visual" if has_media else ""
            step_prefix = f"Step {step_num} · " if step_num > 0 else ""
            media_info = " · 📷 Visual aid attached" if has_media else ""

            blocks_html.append(
                f"""
                <div class="stack-block {type_class} motion-bar {e_color} {visual_class} {compact_class}" {step_attr} style="height:{b_height}px" title="{step_prefix}{e_desc} · {_clean_number(e_time)} s · {work_type or 'Cycle'}{media_info}">
                  <div class="block-left">
                    {step_badge_html}
                    <span class="block-label">{e_desc}</span>
                  </div>
                  <div class="block-right">
                    {cam_icon_html}
                    <span class="block-time">{_clean_number(e_time)}s</span>
                  </div>
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
    total_pitch_elements_count = len(all_pitch_elements)

    for item in current_media_items:
        m_type = item.get("media_type") or "image"
        caption = _text(item.get("caption") or "")
        f_path = item.get("file_path") or ""
        media_src = _media_data_url(f_path)

        m_id = str(item.get("id") or "")
        tagged_steps = media_step_numbers_map.get(m_id)
        if tagged_steps is None:
            tagged_steps = []
            for t in item.get("tagged_work_elements", []):
                t_wid = str(t.get("work_element_id") or "").strip()
                if t_wid in step_num_by_wid:
                    tagged_steps.append(step_num_by_wid[t_wid])
            if not tagged_steps:
                for t_wid in item.get("tagged_work_element_ids", []):
                    t_clean = str(t_wid).strip()
                    if t_clean in step_num_by_wid:
                        tagged_steps.append(step_num_by_wid[t_clean])
            tagged_steps = sorted(list(set(tagged_steps)))

        # Determine if selected on all elements (or general for all pitch elements)
        is_all_elements = False
        if total_pitch_elements_count > 0:
            if len(tagged_steps) >= total_pitch_elements_count or len(tagged_steps) == 0:
                is_all_elements = True
                if not tagged_steps:
                    tagged_steps = list(range(1, total_pitch_elements_count + 1))
        elif not tagged_steps:
            is_all_elements = True

        nums_str = ", ".join(str(sn) for sn in tagged_steps)

        if is_all_elements and tagged_steps:
            step_title_text = f"All elements ({nums_str})"
            tag_badges_html = "".join(f'<span class="visual-tag-badge">{sn}</span>' for sn in tagged_steps)
            is_general = False
        elif tagged_steps:
            pitch_tag_labels = [
                _text(t.get("operation") or f"Step {step_num_by_wid.get(str(t.get('work_element_id') or '').strip(), t.get('work_sequence', ''))}")
                for t in item.get("tagged_work_elements", [])
                if str(t.get("work_element_id") or "").strip() in step_num_by_wid
            ]
            tag_labels = pitch_tag_labels or [
                _text(t.get("operation") or f"Step {t.get('work_sequence', '')}")
                for t in item.get("tagged_work_elements", [])
            ]
            step_title_text = " · ".join(tag_labels) if tag_labels else f"Steps {nums_str}"
            tag_badges_html = "".join(f'<span class="visual-tag-badge">{sn}</span>' for sn in tagged_steps)
            is_general = False
        else:
            step_title_text = "General Pitch Visual"
            tag_badges_html = '<span class="visual-tag-badge general">General</span>'
            is_general = True

        step_nums_attr = ",".join(str(sn) for sn in tagged_steps)

        step_tag_html = f"""
        <div class="visual-step-tag {'general' if is_general else ''}">
          <div class="visual-tag-badges">{tag_badges_html}</div>
          <span class="visual-tag-title" title="{step_title_text}">{step_title_text}</span>
        </div>
        """

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
            <article class="visual-card" data-step-nums="{step_nums_attr}">
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
        ("Quality", "Quality", "quality", "functional_quality", alerts.get("quality", [])),
        ("Ergo", "Ergonomics", "ergo", "functional_ergonomics", alerts.get("ergo", [])),
        ("Safety", "Safety", "safety", "functional_safety", alerts.get("safety", [])),
        ("Materials", "Materials", "materials", "functional_materials", alerts.get("materials", [])),
        ("Equipment", "Equipment", "equipment", "functional_equipment", alerts.get("equipment", [])),
    ]
    alert_blocks_html: list[str] = []
    for cat_name, display_name, cat_key, page_slug, cat_list in alert_categories:
        if cat_list:
            items_str = " · ".join(_text(item.get("label") or "Alert") for item in cat_list)
            first_detail = _text(cat_list[0].get("detail") or cat_list[0].get("label") or "")

            popover_items_html = []
            for item in cat_list:
                item_label = html.escape(_text(item.get("label") or "Alert"))
                item_detail = html.escape(_text(item.get("detail") or ""))
                popover_items_html.append(
                    f"""
                    <div class="popover-item active">
                      <div class="popover-item-title">{item_label}</div>
                      {f'<div class="popover-item-desc">{item_detail}</div>' if item_detail and item_detail != item_label else ''}
                    </div>
                    """
                )

            popover_html = f"""
            <div class="alert-popover" role="tooltip">
              <div class="popover-header">
                <span class="popover-category">{display_name} Alerts</span>
                <span class="popover-count-badge active">{len(cat_list)} flagged</span>
              </div>
              <div class="popover-items-list">
                {"".join(popover_items_html)}
              </div>
              <div class="popover-footer">
                <a href="./{page_slug}" target="_top" class="popover-action-link">Open {display_name} Review ↗</a>
              </div>
            </div>
            """

            alert_blocks_html.append(
                f"""
                <div class="alert-block active {cat_key}" title="{html.escape(first_detail)}">
                  <strong>{cat_name}:</strong> <span class="alert-summary">{items_str}</span>
                  {popover_html}
                </div>
                """
            )
        else:
            popover_html = f"""
            <div class="alert-popover" role="tooltip">
              <div class="popover-header">
                <span class="popover-category">{display_name} Status</span>
                <span class="popover-count-badge clear">✓ Nominal</span>
              </div>
              <div class="popover-items-list">
                <div class="popover-item clear">
                  <div class="popover-item-desc">All checks passed. No open risks, unclassified materials, or missing specifications detected for this pitch.</div>
                </div>
              </div>
              <div class="popover-footer">
                <a href="./{page_slug}" target="_top" class="popover-action-link">Open {display_name} Review ↗</a>
              </div>
            </div>
            """

            alert_blocks_html.append(
                f"""
                <div class="alert-block clear {cat_key}">
                  <strong>{cat_name}:</strong> <span class="alert-ok">✓ None</span>
                  {popover_html}
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
        min-height: 680px;
        height: auto;
        padding: 10px 14px;
        border: 1px solid rgba(128,128,128,0.3);
        border-radius: 12px;
        background: #ffffff;
        color: #1a1f2c;
        display: flex;
        flex-direction: column;
        gap: 8px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        box-shadow: 0 4px 16px rgba(0,0,0,0.06);
        overflow: visible;
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
        padding-bottom: 5px;
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
        overflow: visible;
      }}
      .left-col {{
        display: flex;
        flex-direction: column;
        gap: 8px;
        min-height: 0;
        height: 100%;
        overflow: visible;
      }}
      .right-col {{
        display: flex;
        flex-direction: column;
        min-height: 0;
        height: 100%;
        overflow: visible;
      }}
      /* Left Column Subpanels */
      .panel-section {{
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        background: #fdfdfe;
        padding: 4px 8px;
        display: flex;
        flex-direction: column;
        min-height: 0;
      }}
      .panel-title-bar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 0.78rem;
        font-weight: 800;
        text-transform: uppercase;
        color: #475569;
        margin-bottom: 3px;
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
        font-size: 0.78rem;
        color: #1e293b;
        max-height: 52px;
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
        flex: 0 0 auto;
        overflow: visible;
      }}
      .parts-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.76rem;
      }}
      .parts-table th {{
        text-align: left;
        background: #f1f5f9;
        padding: 3px 5px;
        color: #475569;
        font-size: 0.70rem;
        font-weight: 700;
        border-bottom: 2px solid #e2e8f0;
      }}
      .parts-table td {{
        padding: 2px 5px;
        border-bottom: 1px solid #f1f5f9;
        vertical-align: middle;
      }}
      .parts-table tr.part-row {{
        cursor: pointer;
        transition: background-color 0.15s ease;
      }}
      .parts-table tr.part-row:hover {{
        background-color: #f1f5f9;
      }}
      .parts-table tr.part-row:hover .part-info-cue {{
        opacity: 1;
        background: #0284c7;
        color: #ffffff;
      }}
      .parts-table tr.part-row:hover .part-popover,
      .part-pnum-container:hover .part-popover {{
        display: block;
      }}
      .part-pnum-container {{
        position: relative;
        display: inline-flex;
        align-items: center;
        gap: 4px;
      }}
      .part-info-cue {{
        display: inline-block;
        font-size: 0.62rem;
        color: #94a3b8;
        background: #f1f5f9;
        border: 1px solid #cbd5e1;
        border-radius: 999px;
        width: 13px;
        height: 13px;
        line-height: 11px;
        text-align: center;
        font-weight: 700;
        cursor: pointer;
        transition: all 0.15s ease;
      }}
      .parts-table tr.part-row:hover .part-info-cue {{
        color: #ffffff;
        background: #0284c7;
        border-color: #0284c7;
      }}
      .col-thumb {{ width: 44px; min-width: 44px; text-align: center; }}
      .part-thumb {{
        width: 38px;
        height: 32px;
        object-fit: contain;
        border-radius: 4px;
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        display: block;
        margin: 0 auto;
      }}
      .thumb-ph {{
        width: 38px;
        height: 32px;
        line-height: 32px;
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

      /* Floating Part Popover Window */
      .part-popover {{
        display: none;
        position: absolute;
        top: -10px;
        left: calc(100% + 14px);
        width: 410px;
        max-width: 440px;
        background: #ffffff;
        color: #1e293b;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        box-shadow: 0 12px 28px -4px rgba(0, 0, 0, 0.28), 0 8px 10px -6px rgba(0, 0, 0, 0.15);
        padding: 10px 12px;
        z-index: 1000;
        white-space: normal;
        text-align: left;
        font-weight: normal;
        box-sizing: border-box;
        cursor: default;
        pointer-events: auto;
      }}
      .part-popover-bridge {{
        position: absolute;
        top: 0;
        bottom: 0;
        left: -18px;
        width: 18px;
      }}
      .parts-table tr.part-row:nth-child(n+4):nth-last-child(-n+3) .part-popover {{
        top: auto;
        bottom: -10px;
      }}
      .part-popover::before {{
        content: "";
        position: absolute;
        top: 18px;
        left: -7px;
        width: 0;
        height: 0;
        border-top: 7px solid transparent;
        border-bottom: 7px solid transparent;
        border-right: 7px solid #cbd5e1;
      }}
      .part-popover::after {{
        content: "";
        position: absolute;
        top: 19px;
        left: -6px;
        width: 0;
        height: 0;
        border-top: 6px solid transparent;
        border-bottom: 6px solid transparent;
        border-right: 6px solid #ffffff;
      }}
      .parts-table tr.part-row:nth-child(n+4):nth-last-child(-n+3) .part-popover::before {{
        top: auto;
        bottom: 18px;
      }}
      .parts-table tr.part-row:nth-child(n+4):nth-last-child(-n+3) .part-popover::after {{
        top: auto;
        bottom: 19px;
      }}
      .part-popover-header {{
        border-bottom: 1px solid #e2e8f0;
        padding-bottom: 6px;
        margin-bottom: 6px;
      }}
      .part-popover-title-row {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 6px;
        flex-wrap: wrap;
      }}
      .part-popover-num {{
        font-size: 1.05rem;
        font-weight: 800;
        color: #0f172a;
        letter-spacing: -0.01em;
      }}
      .part-popover-badges {{
        display: flex;
        align-items: center;
        gap: 4px;
        flex-wrap: wrap;
      }}
      .popover-badge {{
        font-size: 0.68rem;
        font-weight: 700;
        padding: 1px 6px;
        border-radius: 4px;
        letter-spacing: 0.02em;
      }}
      .popover-badge.rev {{
        background: #f1f5f9;
        color: #475569;
        border: 1px solid #cbd5e1;
      }}
      .popover-badge.make-buy {{
        background: #e0f2fe;
        color: #0369a1;
        border: 1px solid #bae6fd;
      }}
      .popover-badge.asm-group {{
        background: #eff6ff;
        color: #1d4ed8;
        border: 1px solid #bfdbfe;
        font-weight: 800;
      }}
      .popover-nick-banner {{
        margin-top: 4px;
        font-size: 0.74rem;
        font-weight: 600;
        color: #0369a1;
        background: #f0f9ff;
        padding: 2px 7px;
        border-radius: 4px;
        border: 1px solid #bae6fd;
      }}
      .part-popover-body {{
        font-size: 0.74rem;
        color: #334155;
        max-height: 480px;
        overflow-y: auto;
        scrollbar-width: thin;
      }}
      .popover-image-banner {{
        width: 100%;
        height: 140px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        margin-bottom: 8px;
        box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.03);
      }}
      .popover-large-img {{
        max-width: 100%;
        max-height: 100%;
        object-fit: contain;
        transition: transform 0.2s ease;
      }}
      .popover-image-banner:hover .popover-large-img {{
        transform: scale(1.05);
      }}
      .popover-no-image-cue {{
        font-size: 0.68rem;
        color: #94a3b8;
        background: #f8fafc;
        border: 1px dashed #cbd5e1;
        border-radius: 4px;
        padding: 4px 8px;
        margin-bottom: 8px;
        text-align: center;
      }}
      .popover-part-desc {{
        font-weight: 600;
        font-size: 0.78rem;
        color: #0f172a;
        line-height: 1.3;
      }}
      .popover-cad-name {{
        font-size: 0.68rem;
        color: #64748b;
        margin-top: 2px;
      }}
      .part-popover-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 4px 8px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 5px;
        padding: 6px 8px;
        margin-top: 5px;
        margin-bottom: 5px;
      }}
      .popover-grid-item {{
        display: flex;
        flex-direction: column;
      }}
      .grid-label {{
        font-size: 0.65rem;
        font-weight: 700;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.03em;
      }}
      .grid-val {{
        font-size: 0.73rem;
        font-weight: 600;
        color: #1e293b;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }}
      .popover-engineers-section {{
        margin-top: 8px;
        padding-top: 8px;
        border-top: 1px solid #e2e8f0;
      }}
      .popover-section-label {{
        font-size: 0.66rem;
        font-weight: 700;
        color: #475569;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-bottom: 5px;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }}
      .popover-engineers-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 4px 6px;
      }}
      .eng-item {{
        display: flex;
        align-items: center;
        gap: 5px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 4px;
        padding: 3px 6px;
        min-width: 0;
      }}
      .eng-role-tag {{
        font-size: 0.60rem;
        font-weight: 800;
        text-transform: uppercase;
        background: #0284c7;
        color: #ffffff;
        padding: 1px 4px;
        border-radius: 3px;
        flex-shrink: 0;
      }}
      .eng-role-tag.de {{ background: #2563eb; }}
      .eng-role-tag.te {{ background: #0891b2; }}
      .eng-role-tag.ame {{ background: #d97706; }}
      .eng-role-tag.aqe {{ background: #059669; }}
      .eng-role-tag.buyer {{ background: #7c3aed; }}
      .eng-info {{
        display: flex;
        flex-direction: column;
        min-width: 0;
      }}
      .eng-title {{
        font-size: 0.60rem;
        color: #64748b;
        font-weight: 600;
        line-height: 1;
      }}
      .eng-val {{
        font-size: 0.72rem;
        font-weight: 700;
        color: #1e293b;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        line-height: 1.2;
        margin-top: 1px;
      }}
      .popover-minibom-section {{
        margin-top: 8px;
        padding-top: 8px;
        border-top: 1px solid #e2e8f0;
      }}
      .minibom-count-pill {{
        font-size: 0.62rem;
        font-weight: 700;
        color: #1d4ed8;
        background: #dbeafe;
        padding: 1px 5px;
        border-radius: 8px;
      }}
      .minibom-scroll {{
        max-height: 140px;
        overflow-y: auto;
        border: 1px solid #e2e8f0;
        border-radius: 5px;
        background: #ffffff;
        scrollbar-width: thin;
      }}
      .minibom-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.70rem;
      }}
      .minibom-table th {{
        background: #f8fafc;
        color: #475569;
        font-weight: 700;
        padding: 3px 6px;
        border-bottom: 1px solid #e2e8f0;
        position: sticky;
        top: 0;
        z-index: 1;
        text-align: left;
      }}
      .minibom-table th.qty-th {{
        text-align: right;
      }}
      .minibom-table td {{
        padding: 3px 6px;
        border-bottom: 1px solid #f1f5f9;
        color: #1e293b;
        vertical-align: middle;
      }}
      .minibom-table tr:last-child td {{
        border-bottom: none;
      }}
      .minibom-table tr:hover td {{
        background: #f8fafc;
      }}
      .minibom-pnum {{
        font-weight: 700;
        color: #0284c7;
        font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
        white-space: nowrap;
      }}
      .minibom-desc {{
        color: #475569;
        max-width: 130px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }}
      .minibom-qty {{
        font-weight: 800;
        text-align: right;
        white-space: nowrap;
        color: #0f172a;
      }}
      .minibom-eng {{
        color: #64748b;
        font-size: 0.65rem;
        max-width: 80px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }}
      .minibom-empty-note {{
        font-size: 0.70rem;
        color: #64748b;
        font-style: italic;
        padding: 6px 8px;
        background: #f8fafc;
        border-radius: 4px;
        border: 1px dashed #cbd5e1;
      }}
      .popover-steps-box {{
        margin-top: 5px;
        padding: 5px 7px;
        background: #f1f5f9;
        border-radius: 5px;
        font-size: 0.72rem;
      }}
      .popover-steps-label {{
        font-weight: 700;
        color: #0f172a;
        font-size: 0.68rem;
        text-transform: uppercase;
        margin-bottom: 3px;
      }}
      .popover-steps-list {{
        display: flex;
        flex-wrap: wrap;
        gap: 3px;
      }}
      .popover-step-pill {{
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-radius: 3px;
        padding: 1px 5px;
        font-size: 0.7rem;
        font-weight: 600;
        color: #1e293b;
      }}
      .popover-notes-box {{
        margin-top: 5px;
        padding: 4px 7px;
        background: #fffbeb;
        border: 1px solid #fef3c7;
        border-radius: 4px;
        font-size: 0.71rem;
        color: #92400e;
        line-height: 1.3;
      }}
      /* Mini Yamazumi Stack */
      .stack-panel {{
        margin-top: auto;
        flex: 0 0 auto;
        min-height: 230px;
        padding: 6px 10px;
        box-sizing: border-box;
      }}
      .stack-panel .panel-title-bar {{
        margin-bottom: 4px;
        font-size: 0.80rem;
      }}
      .yam-legend {{
        display: flex;
        align-items: center;
        gap: 6px;
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
        width: 10px;
        height: 10px;
        border-radius: 2px;
      }}
      .swatch-mini.cycle {{ background: #35c84a; }}
      .swatch-mini.periodic {{ background: #ffd54f; border: 1px solid rgba(0,0,0,0.15); }}
      .swatch-mini.fluctuation {{ background: #ef5350; }}

      .stacks-container {{
        display: flex;
        gap: 8px;
        height: auto;
        min-height: 195px;
        overflow-x: auto;
      }}
      .variant-stack-col {{
        flex: 1 1 0;
        min-width: 90px;
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
      }}
      .variant-header {{
        font-size: 0.70rem;
        font-weight: 700;
        text-align: center;
        color: #334155;
        margin-bottom: 2px;
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        align-items: center;
        gap: 3px;
        line-height: 1.15;
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
        padding: 0 4px;
        font-size: 0.68rem;
        font-weight: 700;
        overflow: hidden;
        position: relative;
        cursor: pointer;
        transition: filter 0.15s ease, outline 0.15s ease, box-shadow 0.15s ease;
        line-height: 1.1;
      }}
      .stack-block.compact {{
        padding: 0 2px;
        font-size: 0.60rem;
      }}
      .stack-block.compact .stack-step-badge {{
        font-size: 0.58rem;
        padding: 0 2px;
        line-height: 11px;
        min-width: 12px;
      }}
      .stack-block.compact .stack-cam-icon {{
        font-size: 0.55rem;
      }}
      .stack-block .block-left {{
        display: flex;
        align-items: center;
        gap: 4px;
        min-width: 0;
        overflow: hidden;
        flex: 1 1 auto;
      }}
      .stack-step-badge {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: #0f172a;
        color: #ffffff;
        font-size: 0.74rem;
        font-weight: 800;
        padding: 1px 5px;
        min-width: 17px;
        text-align: center;
        border-radius: 4px;
        line-height: 14px;
        flex-shrink: 0;
        border: 1px solid rgba(255, 255, 255, 0.4);
        box-sizing: border-box;
      }}
      .stack-block.has-visual .stack-step-badge {{
        background: #0284c7;
        border-color: #bae6fd;
      }}
      .stack-block .block-right {{
        display: flex;
        align-items: center;
        gap: 3px;
        flex-shrink: 0;
        margin-left: 4px;
      }}
      .stack-cam-icon {{
        font-size: 0.65rem;
        display: inline-flex;
        align-items: center;
        opacity: 0.95;
      }}
      .stack-block.highlighted {{
        outline: 2px solid #0284c7;
        filter: brightness(1.2);
        box-shadow: 0 0 8px rgba(2, 132, 199, 0.7);
        z-index: 10;
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
      .motion-bar.green {{ background: #35c84a; }}
      .motion-bar.orange {{ background: #ea580c; }}
      .motion-bar.gray {{ background: #64748b; }}
      .block-label {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }}
      .block-time {{ font-weight: 800; flex-shrink: 0; }}
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
        position: relative;
        transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
      }}
      .visual-card.highlighted {{
        border-color: #0284c7 !important;
        box-shadow: 0 0 12px rgba(2, 132, 199, 0.45) !important;
        transform: translateY(-1px);
      }}
      .visual-step-tag {{
        background: #1e293b;
        color: #f8fafc;
        padding: 4px 8px;
        font-size: 0.80rem;
        font-weight: 700;
        display: flex;
        align-items: center;
        gap: 6px;
        min-width: 0;
      }}
      .visual-step-tag.general {{
        background: #475569;
      }}
      .visual-tag-badges {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        flex-shrink: 0;
      }}
      .visual-tag-badge {{
        background: #0284c7;
        color: #ffffff;
        font-size: 0.78rem;
        font-weight: 800;
        padding: 2px 6px;
        min-width: 18px;
        text-align: center;
        border-radius: 4px;
        line-height: 15px;
        border: 1px solid #38bdf8;
        box-sizing: border-box;
      }}
      .visual-tag-badge.general {{
        background: #64748b;
        border-color: #94a3b8;
      }}
      .visual-tag-title {{
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex: 1 1 auto;
        min-width: 0;
      }}
      .visual-media-box {{
        flex: 1 1 0;
        min-height: 0;
        background: #000000;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        position: relative;
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

      /* Top Functional Alerts Banner */
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
        position: relative;
        z-index: 50;
        overflow: visible;
      }}
      .alert-block {{
        position: relative;
        overflow: visible;
        padding: 3px 6px;
        border-radius: 4px;
        display: flex;
        align-items: center;
        gap: 4px;
        min-width: 0;
        cursor: pointer;
        transition: background-color 0.15s ease, border-color 0.15s ease;
      }}
      .alert-block strong {{
        flex-shrink: 0;
      }}
      .alert-summary {{
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        min-width: 0;
        flex: 1 1 auto;
      }}
      .alert-block.active {{
        background: #fee2e2;
        color: #991b1b;
        font-weight: 700;
        border: 1px solid #f87171;
      }}
      .alert-block.active:hover {{
        background: #fecaca;
        border-color: #ef4444;
      }}
      .alert-block.clear {{
        color: #475569;
        border: 1px solid transparent;
      }}
      .alert-block.clear:hover {{
        background: #e2e8f0;
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

      /* Alert Hover Popovers */
      .alert-popover {{
        display: none;
        position: absolute;
        top: calc(100% + 5px);
        left: 0;
        width: 320px;
        max-width: 85vw;
        background: #ffffff;
        color: #1e293b;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.25), 0 8px 10px -6px rgba(0, 0, 0, 0.15);
        padding: 10px 12px;
        z-index: 1000;
        white-space: normal;
        text-align: left;
        font-weight: normal;
        box-sizing: border-box;
        cursor: default;
      }}
      .alert-popover::before {{
        content: "";
        position: absolute;
        top: -6px;
        left: 0;
        right: 0;
        height: 6px;
      }}
      .functional-alerts-bar .alert-block:nth-child(4) .alert-popover,
      .functional-alerts-bar .alert-block:nth-child(5) .alert-popover {{
        left: auto;
        right: 0;
      }}
      .alert-block:hover .alert-popover {{
        display: block;
      }}
      .popover-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding-bottom: 6px;
        margin-bottom: 8px;
        border-bottom: 1px solid #e2e8f0;
      }}
      .popover-category {{
        font-weight: 800;
        font-size: 0.82rem;
        color: #0f172a;
      }}
      .popover-count-badge {{
        font-size: 0.68rem;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 10px;
      }}
      .popover-count-badge.active {{
        background: #fee2e2;
        color: #991b1b;
        border: 1px solid #f87171;
      }}
      .popover-count-badge.clear {{
        background: #dcfce7;
        color: #166534;
        border: 1px solid #86efac;
      }}
      .popover-items-list {{
        display: flex;
        flex-direction: column;
        gap: 6px;
        max-height: 190px;
        overflow-y: auto;
        margin-bottom: 8px;
      }}
      .popover-item {{
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 5px;
        padding: 6px 8px;
      }}
      .popover-item.active {{
        border-left: 3px solid #ef4444;
      }}
      .popover-item.clear {{
        border-left: 3px solid #22c55e;
        color: #475569;
        font-size: 0.74rem;
      }}
      .popover-item-title {{
        font-weight: 700;
        font-size: 0.76rem;
        color: #0f172a;
        margin-bottom: 2px;
      }}
      .popover-item-desc {{
        font-size: 0.72rem;
        color: #475569;
        line-height: 1.35;
      }}
      .popover-footer {{
        padding-top: 6px;
        border-top: 1px solid #f1f5f9;
        display: flex;
        justify-content: flex-end;
      }}
      .popover-action-link {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 0.72rem;
        font-weight: 700;
        color: #0284c7;
        text-decoration: none;
        padding: 3px 8px;
        border-radius: 4px;
        background: #f0f9ff;
        border: 1px solid #bae6fd;
        transition: all 0.15s ease;
      }}
      .popover-action-link:hover {{
        background: #0284c7;
        color: #ffffff;
        text-decoration: none;
      }}

      /* Presentation & Print rules */
      .paag-slide.presentation-active {{
        min-height: 750px;
        height: auto;
        padding: 14px 18px;
        gap: 10px;
        overflow: visible;
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
        .alert-popover {{
          display: none !important;
        }}
        .part-popover,
        .part-popover-portal {{
          display: none !important;
        }}
        .visual-tag-badge {{
          background: #0284c7 !important;
          color: #ffffff !important;
          border: 1px solid #000000 !important;
          -webkit-print-color-adjust: exact !important;
          print-color-adjust: exact !important;
        }}
        .stack-step-badge {{
          background: #0f172a !important;
          color: #ffffff !important;
          border: 1px solid #000000 !important;
          -webkit-print-color-adjust: exact !important;
          print-color-adjust: exact !important;
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

      <!-- Functional Alerts Banner (Top, under header, above visual aids and parts) -->
      <div class="functional-alerts-bar" role="region" aria-label="Functional Alerts">
        {"".join(alert_blocks_html)}
      </div>

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

      <script>
      (function() {{
        function setupHoverLinking() {{
          const blocks = document.querySelectorAll('.stack-block[data-step-num]');
          const cards = document.querySelectorAll('.visual-card[data-step-nums]');
          if (!blocks.length || !cards.length) return;

          blocks.forEach(block => {{
            block.addEventListener('mouseenter', () => {{
              const num = block.getAttribute('data-step-num');
              if (!num) return;
              cards.forEach(card => {{
                const nums = (card.getAttribute('data-step-nums') || '').split(',');
                if (nums.includes(num)) {{
                  card.classList.add('highlighted');
                }}
              }});
            }});
            block.addEventListener('mouseleave', () => {{
              cards.forEach(card => card.classList.remove('highlighted'));
            }});
          }});

          cards.forEach(card => {{
            card.addEventListener('mouseenter', () => {{
              const nums = (card.getAttribute('data-step-nums') || '').split(',');
              blocks.forEach(block => {{
                const num = block.getAttribute('data-step-num');
                if (num && nums.includes(num)) {{
                  block.classList.add('highlighted');
                }}
              }});
            }});
            card.addEventListener('mouseleave', () => {{
              blocks.forEach(block => block.classList.remove('highlighted'));
            }});
          }});
        }}

        function initSlideInteractions() {{
          setupHoverLinking();
        }}

        if (document.readyState === 'loading') {{
          document.addEventListener('DOMContentLoaded', initSlideInteractions);
        }} else {{
          initSlideInteractions();
        }}
      }})();
      </script>
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

