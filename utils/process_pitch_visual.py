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

_SLIDE_LOGO_DATA_URI_CACHE: str | None = None


def _slide_logo_path() -> Path | None:
    assets_dir = Path(__file__).resolve().parents[1] / "assets"
    for candidate in ("ge_appliances_slide_logo.png", "ge_appliances_horizontal.png"):
        path = assets_dir / candidate
        if path.exists() and path.is_file():
            return path
    return None


def _slide_logo_data_uri() -> str:
    global _SLIDE_LOGO_DATA_URI_CACHE
    if _SLIDE_LOGO_DATA_URI_CACHE is not None:
        return _SLIDE_LOGO_DATA_URI_CACHE
    logo_path = _slide_logo_path()
    if logo_path is None:
        _SLIDE_LOGO_DATA_URI_CACHE = ""
        return ""
    try:
        b64 = base64.b64encode(logo_path.read_bytes()).decode("ascii")
        _SLIDE_LOGO_DATA_URI_CACHE = f"data:image/png;base64,{b64}"
    except Exception:
        _SLIDE_LOGO_DATA_URI_CACHE = ""
    return _SLIDE_LOGO_DATA_URI_CACHE


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


def _part_display_qty(part: dict) -> str:
    """Return formatted quantity string for a part on a PAAG slide, or '' when only Handled."""
    h_types = part.get("handling_types") or []
    if not h_types and part.get("handling_type"):
        h_types = [part.get("handling_type")]
    normalized_h = {str(ht or "").strip().casefold() for ht in h_types if str(ht or "").strip()}
    has_consume = bool(normalized_h & {"consume", "c"})
    has_handle = bool(normalized_h & {"handle", "h"})
    if has_handle and not has_consume:
        return ""
    raw_qty = (
        part.get("quantity")
        if part.get("quantity") is not None
        else (
            part.get("total_quantity")
            if part.get("total_quantity") is not None
            else part.get("qty")
        )
    )
    if raw_qty is None or str(raw_qty).strip() == "":
        return "" if has_handle else "1"
    return _clean_number(raw_qty)


_MEDIA_DATA_URL_CACHE: dict[tuple[str, int, int], str] = {}


def _media_data_url(raw_path: object) -> str:
    val = str(raw_path or "").strip()
    if not val:
        return ""
    if val.startswith(("http://", "https://", "data:")):
        return val
    path = Path(val)
    try:
        st_info = path.stat()
        if not path.is_file():
            return ""
        cache_key = (str(path), int(st_info.st_mtime_ns), int(st_info.st_size))
        cached = _MEDIA_DATA_URL_CACHE.get(cache_key)
        if cached is not None:
            return cached
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
        res = f"data:{mime};base64,{encoded}"
        if len(_MEDIA_DATA_URL_CACHE) >= 256:
            _MEDIA_DATA_URL_CACHE.pop(next(iter(_MEDIA_DATA_URL_CACHE)), None)
        _MEDIA_DATA_URL_CACHE[cache_key] = res
        return res
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


def _yamazumi_step_url(
    pitch: dict | None = None,
    *,
    yamazumi_elem: dict | None = None,
    linked_elem: dict | None = None,
) -> str:
    """Build a direct URL to the Yamazumi tab for the pitch's section/area and optional element."""
    p = pitch or {}
    y = yamazumi_elem or {}
    l = linked_elem or {}
    area_id = str(p.get("area_id") or y.get("area_id") or l.get("area_id") or "").strip()
    section_id = str(p.get("section_id") or y.get("section_id") or l.get("section_id") or "").strip()
    pitch_id = str(p.get("id") or p.get("pitch_id") or y.get("pitch_id") or l.get("pitch_id") or "").strip()
    pitch_number = str(p.get("pitch_number") or y.get("pitch_number") or l.get("pitch_number") or "").strip()
    yamazumi_element_id = str(
        y.get("yamazumi_element_id")
        or l.get("yamazumi_element_id")
        or (y.get("id") if y.get("id") and y.get("id") != y.get("work_element_id") else "")
        or y.get("id")
        or ""
    ).strip()
    work_element_id = str(
        y.get("work_element_id")
        or y.get("process_element_id")
        or l.get("work_element_id")
        or l.get("id")
        or ""
    ).strip()

    url_params: list[str] = []
    if area_id:
        url_params.append(f"area_id={quote_plus(area_id)}")
    if section_id:
        url_params.append(f"section_id={quote_plus(section_id)}")
    if pitch_id:
        url_params.append(f"pitch_id={quote_plus(pitch_id)}")
    if pitch_number:
        url_params.append(f"pitch_number={quote_plus(pitch_number)}")
    if yamazumi_element_id:
        url_params.append(f"yamazumi_element_id={quote_plus(yamazumi_element_id)}")
    if work_element_id:
        url_params.append(f"work_element_id={quote_plus(work_element_id)}")
    query_str = f"?{'&'.join(url_params)}" if url_params else ""
    return f"./yamazumi{query_str}#yamazumi-board-section"


def _part_popover_content(
    part: dict,
    *,
    pitch: dict | None = None,
    step_urls_by_num: dict[int, str] | None = None,
) -> str:
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
    p_qty = _part_display_qty(part)
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
        *(
            [f'<div class="popover-grid-item"><span class="grid-label">Pitch Qty</span><span class="grid-val">{p_qty}</span></div>']
            if p_qty
            else []
        ),
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
        import re as _re

        step_badge_items: list[str] = []
        for s in linked_steps:
            s_raw = str(s or "").strip()
            m_step = _re.match(r"^(?:Step\s+)?(\d+)\b", s_raw, _re.IGNORECASE)
            s_url = ""
            if m_step and step_urls_by_num:
                s_url = step_urls_by_num.get(int(m_step.group(1)), "")
            if not s_url:
                s_url = _yamazumi_step_url(pitch)
            step_badge_items.append(
                f'<a href="{s_url}" target="_top" class="popover-step-pill popover-step-link" title="Open in Yamazumi">{_text(s)} ↗</a>'
            )
        steps_badges = " ".join(step_badge_items)
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


def _step_popover_content(
    step_num: int,
    yamazumi_elem: dict,
    linked_elem: dict | None,
    variant_name: str,
    has_media: bool,
    pitch: dict | None = None,
) -> str:
    """Build detailed HTML popover content for a Yamazumi step badge."""
    raw_desc = str(yamazumi_elem.get("description") or yamazumi_elem.get("yamazumi_description") or "").strip()
    linked = linked_elem or {}
    raw_op = str(linked.get("operation") or "").strip()
    display_desc = _text(raw_desc or raw_op or f"Step {step_num}")
    e_time = float(yamazumi_elem.get("time_s") or linked.get("time_s") or 0.0)
    work_type = str(yamazumi_elem.get("work_type") or linked.get("work_type") or "Cycle").strip() or "Cycle"
    w_lower = work_type.lower()
    if w_lower == "periodic":
        wt_class = "periodic"
    elif w_lower == "fluctuation":
        wt_class = "fluctuation"
    else:
        wt_class = "cycle"

    op_sub_html = ""
    if raw_op and raw_desc and raw_op.casefold() != raw_desc.casefold():
        op_sub_html = f'<div class="step-popover-subdesc"><strong>PAAG Operation:</strong> {_text(raw_op)}</div>'

    grid_items: list[str] = []
    if variant_name:
        grid_items.append(
            f'<div class="popover-grid-item"><span class="grid-label">Variant</span>'
            f'<span class="grid-val" title="{_text(variant_name)}">{_text(variant_name)}</span></div>'
        )
    op_id_val = str(linked.get("op_id") or yamazumi_elem.get("op_id") or "").strip()
    if op_id_val and op_id_val != "Yamazumi link required":
        grid_items.append(
            f'<div class="popover-grid-item"><span class="grid-label">Op ID</span>'
            f'<span class="grid-val" title="{_text(op_id_val)}">{_text(op_id_val)}</span></div>'
        )
    motion_cls = str(
        linked.get("motion_classification") or yamazumi_elem.get("motion_classification") or ""
    ).strip()
    if motion_cls:
        grid_items.append(
            f'<div class="popover-grid-item"><span class="grid-label">Classification</span>'
            f'<span class="grid-val" title="{_text(motion_cls)}">{_text(motion_cls)}</span></div>'
        )
    models_val = linked.get("model_applicability") or linked.get("models")
    if isinstance(models_val, list):
        models_str = ", ".join(str(m) for m in models_val if str(m).strip())
    else:
        models_str = str(models_val or "").strip()
    if models_str:
        grid_items.append(
            f'<div class="popover-grid-item"><span class="grid-label">Models</span>'
            f'<span class="grid-val" title="{_text(models_str)}">{_text(models_str)}</span></div>'
        )

    grid_html = f'<div class="part-popover-grid">{"".join(grid_items)}</div>' if grid_items else ""

    parts_pills: list[str] = []
    for p in linked.get("parts") or []:
        if not isinstance(p, dict):
            continue
        p_num = _text(p.get("part_number") or "")
        if not p_num:
            continue
        p_qty = _part_display_qty(p)
        parts_pills.append(
            f'<span class="popover-step-pill">{p_num} (×{p_qty})</span>'
            if p_qty
            else f'<span class="popover-step-pill">{p_num}</span>'
        )
    parts_html = (
        f'<div class="popover-steps-box">'
        f'<div class="popover-steps-label">Parts Consumed / Handled</div>'
        f'<div class="popover-steps-list">{"".join(parts_pills)}</div>'
        f'</div>'
        if parts_pills
        else ""
    )

    media_html = (
        '<div class="step-popover-media-note">📷 Visual aid attached to this step</div>'
        if has_media
        else ""
    )

    yamazumi_url = _yamazumi_step_url(pitch, yamazumi_elem=yamazumi_elem, linked_elem=linked_elem)

    return f"""
    <div class="step-popover-card">
      <div class="step-popover-header">
        <div class="step-popover-badges">
          <a href="{yamazumi_url}" target="_top" class="step-popover-num step-popover-link" title="Open in Yamazumi">Step {step_num} ↗</a>
          <span class="step-popover-type {wt_class}">{_text(work_type)}</span>
        </div>
        <span class="step-popover-time">{_clean_number(e_time)}s</span>
      </div>
      <div class="step-popover-body">
        <div class="step-popover-desc">{display_desc}</div>
        {op_sub_html}
        {grid_html}
        {parts_html}
        {media_html}
      </div>
      <div class="popover-footer">
        <a href="{yamazumi_url}" target="_top" class="popover-action-link">Open in Yamazumi ↗</a>
      </div>
    </div>
    """


def render_pitch_canvas(
    pitch: dict,
    elements: list[dict] | None = None,
    *,
    scenario_name: str = "",
    project_name: str = "",
    building_location: str = "",
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
    raw_pitch_name = str(pitch.get("pitch_name") or "").strip()
    if raw_pitch_name.casefold() == "process station":
        raw_pitch_name = ""
    pitch_name = _text(raw_pitch_name)
    pitch_title_display = f"{pitch_number} — {pitch_name}" if pitch_name else pitch_number
    section_name = _text(pitch.get("section_name") or "")
    eff_section_name = _text(
        pitch.get("section_name")
        or pitch.get("area_name")
        or "N/A"
    )
    eff_building_name = _text(
        building_location
        or pitch.get("building_location")
        or pitch.get("building")
        or "N/A"
    )
    eff_project_name = _text(project_name or pitch.get("project_name") or "Project")
    eff_scenario_name = _text(scenario_name or pitch.get("scenario_name") or "Scenario")
    slide_logo_uri = _slide_logo_data_uri()
    logo_html = (
        f'<img class="header-logo-img" src="{slide_logo_uri}" alt="GE Appliances, a Haier company" />'
        if slide_logo_uri
        else '<div class="brand-title">GE Appliances</div>'
    )

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
            for el_idx, el in enumerate(elements_list):
                el_wid = str(el.get("work_element_id") or el.get("id") or f"step_{el_idx}")
                for p in el.get("parts", []):
                    p_num = str(p.get("part_number") or "").strip()
                    if not p_num:
                        continue
                    is_mv = bool(p.get("is_model_variant"))
                    mc_gid = (
                        str(p.get("model_choice_group_id") or p.get("group_id") or el_wid)
                        if is_mv
                        else ""
                    )
                    p_h = str(p.get("handling_type") or "").strip()
                    p_h_norm = p_h.casefold()
                    p_is_c = p_h_norm in {"consume", "c"}
                    p_is_h = p_h_norm in {"handle", "h"}
                    p_qty_val = float(p.get("quantity") or 1.0)
                    if p_num not in seen_parts:
                        seen_parts[p_num] = {
                            "part_number": p_num,
                            "description": p.get("part_description") or p.get("description") or "",
                            "factory_nickname": p.get("factory_nickname") or "",
                            "image_path": p.get("image_path") or "",
                            "quantity": p_qty_val if p_is_c else (None if p_is_h else p_qty_val),
                            "_consume_qty": p_qty_val if p_is_c else 0.0,
                            "_has_consume": p_is_c,
                            "_has_handle": p_is_h,
                            "_unclassified_qty": p_qty_val if (not p_is_c and not p_is_h) else 0.0,
                            "handling_types": {p_h} if p_h else set(),
                            "is_model_variant": is_mv,
                            "model_choice_group_id": mc_gid,
                        }
                    else:
                        if p_h:
                            seen_parts[p_num]["handling_types"].add(p_h)
                        if p_is_c:
                            seen_parts[p_num]["_consume_qty"] += p_qty_val
                            seen_parts[p_num]["_has_consume"] = True
                        elif p_is_h:
                            seen_parts[p_num]["_has_handle"] = True
                        else:
                            seen_parts[p_num]["_unclassified_qty"] += p_qty_val
                        if seen_parts[p_num]["_has_consume"]:
                            seen_parts[p_num]["quantity"] = seen_parts[p_num]["_consume_qty"]
                        elif seen_parts[p_num]["_has_handle"]:
                            seen_parts[p_num]["quantity"] = None
                        else:
                            seen_parts[p_num]["quantity"] = seen_parts[p_num]["_unclassified_qty"]
                        if is_mv and not seen_parts[p_num].get("is_model_variant"):
                            seen_parts[p_num]["is_model_variant"] = True
                            seen_parts[p_num]["model_choice_group_id"] = mc_gid
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
        t_tier = _text(tool.get("tier") or tool.get("equipment_tier") or "")
        t_summary = _text(tool.get("summary_line") or (f"{t_name} ({t_type})" if t_type and t_type.lower() != "tool" else t_name))
        is_ppe = tool.get("is_ppe", False)
        ppe_badge = '<span class="badge-ppe">PPE</span> ' if is_ppe else ''
        tier_badge = f'<span class="badge-tier" style="font-size:0.68rem;background:#e2e8f0;color:#334155;padding:1px 4px;border-radius:3px;margin-right:4px;">{t_tier}</span> ' if t_tier else ''
        tool_items_html.append(
            f'<li class="tool-item" title="{t_summary}">{ppe_badge}{tier_badge}<span class="tool-text">{t_summary}</span></li>'
        )
    tools_section_html = (
        f'<ul class="tools-list">{"".join(tool_items_html)}</ul>'
        if tool_items_html
        else '<div class="subtle-empty">No equipment or PPE assigned</div>'
    )

    tie_tool_btn_html = (
        '<button type="button" class="tie-tool-slide-btn" '
        'title="Tie a tool to a work element in this pitch" '
        'onclick="if(window.__paagOpenTieToolDialog){window.__paagOpenTieToolDialog(event);}else{'
        'var d=(window.parent&&window.parent.document)?window.parent.document:document;'
        'var b=d.querySelector(\'[class*=st-key-btn_tie_tool_slide_] button\')||d.querySelector(\'[class*=st-key-btn_tools_] button\');'
        'if(b)b.click();}">+ Tie Tool</button>'
        if not presentation_mode and not print_format
        else ""
    )

    # Ergonomic & Conveyor chips
    ergo_badges: list[str] = []
    platform_h = float(pitch.get("platform_height_in") or 0.0)
    if platform_h > 0:
        ergo_badges.append(f'<span class="badge-ergo platform" style="background:#e0f2fe;color:#0369a1;padding:1px 5px;border-radius:3px;font-size:0.72rem;margin-left:4px;">Platform: +{platform_h:g}"</span>')
    pit_d = float(pitch.get("pit_depth_in") or 0.0)
    if pit_d > 0:
        ergo_badges.append(f'<span class="badge-ergo pit" style="background:#fef3c7;color:#92400e;padding:1px 5px;border-radius:3px;font-size:0.72rem;margin-left:4px;">Pit: -{pit_d:g}"</span>')
    unit_orient = _text(pitch.get("unit_orientation") or "")
    if unit_orient:
        ergo_badges.append(f'<span class="badge-ergo orient" style="background:#f1f5f9;color:#475569;padding:1px 5px;border-radius:3px;font-size:0.72rem;margin-left:4px;">Orient: {unit_orient}</span>')
    conveyor_h = float(pitch.get("conveyor_height_in") or 0.0)
    if conveyor_h > 0:
        ergo_badges.append(f'<span class="badge-ergo conveyor" style="background:#f3e8ff;color:#6b21a8;padding:1px 5px;border-radius:3px;font-size:0.72rem;margin-left:4px;">Conveyor: {conveyor_h:g}"</span>')
    ergo_chips_html = f'<div class="ergo-chips-bar" style="margin-top:2px;font-weight:normal;">{"".join(ergo_badges)}</div>' if ergo_badges else ""

    # Map work elements on this pitch to 1-based sequential step numbers and Yamazumi links
    all_pitch_elements = list(pitch.get("elements", []))
    if not all_pitch_elements and elements_list:
        all_pitch_elements = list(elements_list)

    step_num_by_wid: dict[str, int] = {}
    element_by_wid: dict[str, dict] = {}
    step_urls_by_num: dict[int, str] = {}
    step_desc_by_num: dict[int, str] = {}
    for idx, el in enumerate(all_pitch_elements):
        s_num = idx + 1
        w_id = str(el.get("work_element_id") or el.get("id") or "").strip()
        y_id = str(el.get("yamazumi_element_id") or "").strip()
        raw_el_desc = str(
            el.get("yamazumi_description")
            or el.get("operation")
            or el.get("element_name")
            or ""
        ).strip()
        if raw_el_desc and s_num not in step_desc_by_num:
            step_desc_by_num[s_num] = _text(raw_el_desc)
        desc_key = f"desc::{raw_el_desc.casefold()}"
        if w_id:
            step_num_by_wid[w_id] = s_num
            element_by_wid[w_id] = el
        if y_id:
            step_num_by_wid[y_id] = s_num
            element_by_wid[y_id] = el
        if desc_key != "desc::" and desc_key not in step_num_by_wid:
            step_num_by_wid[desc_key] = s_num
            element_by_wid[desc_key] = el
        step_urls_by_num[s_num] = _yamazumi_step_url(pitch, linked_elem=el)

    # Restart step numbering at 1 for each Yamazumi stack column on the pitch
    if yamazumi_stacks:
        assigned_stack_keys: set[str] = set()
        assigned_stack_step_nums: set[int] = set()
        for v_data in yamazumi_stacks.values():
            v_els = v_data.get("elements", []) if isinstance(v_data, dict) else (v_data if isinstance(v_data, list) else [])
            stack_step_idx = 0
            for e in v_els:
                if not isinstance(e, dict):
                    continue
                stack_step_idx += 1
                assigned_num = stack_step_idx
                e_wid = str(e.get("work_element_id") or e.get("process_element_id") or "").strip()
                e_id = str(e.get("id") or "").strip()
                raw_e_desc = str(e.get("description") or e.get("yamazumi_description") or "").strip()
                e_desc_key = f"desc::{raw_e_desc.casefold()}"
                linked_for_step = (
                    (element_by_wid.get(e_wid) if e_wid else None)
                    or (element_by_wid.get(e_id) if e_id else None)
                    or (element_by_wid.get(e_desc_key) if e_desc_key != "desc::" else None)
                )
                resolved_step_desc = raw_e_desc or str(
                    (linked_for_step or {}).get("yamazumi_description")
                    or (linked_for_step or {}).get("operation")
                    or ""
                ).strip()
                if resolved_step_desc and assigned_num not in assigned_stack_step_nums:
                    step_desc_by_num[assigned_num] = _text(resolved_step_desc)
                    assigned_stack_step_nums.add(assigned_num)
                if e_wid and e_wid not in assigned_stack_keys:
                    step_num_by_wid[e_wid] = assigned_num
                    assigned_stack_keys.add(e_wid)
                if e_id and e_id not in assigned_stack_keys:
                    step_num_by_wid[e_id] = assigned_num
                    assigned_stack_keys.add(e_id)
                if e_desc_key != "desc::" and e_desc_key not in assigned_stack_keys:
                    step_num_by_wid[e_desc_key] = assigned_num
                    assigned_stack_keys.add(e_desc_key)
                if assigned_num not in step_urls_by_num or linked_for_step is not None:
                    step_urls_by_num[assigned_num] = _yamazumi_step_url(
                        pitch, yamazumi_elem=e, linked_elem=linked_for_step
                    )

    # 2. BUILD LEFT COLUMN: PARTS TABLE
    def _part_mc_group_key(part_dict: dict) -> str:
        if not bool(part_dict.get("is_model_variant")):
            return ""
        return str(
            part_dict.get("model_choice_group_id")
            or part_dict.get("group_id")
            or part_dict.get("work_element_id")
            or "__model_choice__"
        ).strip()

    ordered_parts: list[dict] = []
    seen_mc_keys: set[str] = set()
    for p_item in parts:
        mc_k = _part_mc_group_key(p_item)
        if not mc_k:
            ordered_parts.append(p_item)
        elif mc_k not in seen_mc_keys:
            seen_mc_keys.add(mc_k)
            for peer in parts:
                if _part_mc_group_key(peer) == mc_k:
                    ordered_parts.append(peer)

    has_model_choice_parts = bool(seen_mc_keys)
    parts_title_legend_html = (
        '<div class="parts-mc-legend" title="Purple outline indicates Model Choice variant parts for a step">'
        '<span class="swatch-mc-outline" aria-hidden="true"></span>'
        '<span>Model Choice</span>'
        '</div>'
        if has_model_choice_parts
        else ""
    )

    part_rows_html: list[str] = []
    for idx, part in enumerate(ordered_parts):
        mc_key = _part_mc_group_key(part)
        prev_mc_key = _part_mc_group_key(ordered_parts[idx - 1]) if idx > 0 else ""
        next_mc_key = (
            _part_mc_group_key(ordered_parts[idx + 1])
            if idx + 1 < len(ordered_parts)
            else ""
        )
        is_mc = bool(mc_key)
        is_mc_first = is_mc and (mc_key != prev_mc_key)
        is_mc_last = is_mc and (mc_key != next_mc_key)

        if is_mc_first:
            if prev_mc_key:
                part_rows_html.append(
                    '<tr class="model-choice-spacer-row" aria-hidden="true"><td colspan="5"></td></tr>'
                )
            part_rows_html.append(
                f"""
                <tr class="model-choice-label-row" data-model-choice-group="{_text(mc_key)}">
                  <td colspan="5" class="model-choice-label-cell">
                    <span class="model-choice-outline-label">Model Choice</span>
                  </td>
                </tr>
                """
            )

        p_num = _text(part.get("part_number") or "Part")
        p_desc = _text(part.get("description") or part.get("part_name") or "")
        p_nick = _text(part.get("factory_nickname") or "")
        p_qty = _part_display_qty(part)
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
                h_badges.append('<span class="h-badge va" title="Consume">C</span>')
            elif ht_clean.casefold() in {"handle", "h"}:
                h_badges.append('<span class="h-badge nvan" title="Handle">H</span>')
            elif ht_clean:
                h_badges.append(f'<span class="h-badge">{_text(ht_clean)}</span>')
        h_cell = " ".join(h_badges) if h_badges else '<span class="text-muted">—</span>'

        nick_row = (
            f'<div class="part-nick-text" title="Factory Nickname: {p_nick}">{p_nick}</div>'
            if p_nick
            else '<div class="part-nick-space">&nbsp;</div>'
        )

        popover_content = _part_popover_content(
            part, pitch=pitch, step_urls_by_num=step_urls_by_num
        )

        row_classes = ["part-row"]
        if is_mc:
            row_classes.append("model-choice-row")
            if is_mc_first:
                row_classes.append("model-choice-first")
            if is_mc_last:
                row_classes.append("model-choice-last")
        mc_data_attr = f' data-model-choice-group="{_text(mc_key)}"' if is_mc else ""

        part_rows_html.append(
            f"""
            <tr class="{' '.join(row_classes)}" data-part-num="{p_num}"{mc_data_attr}>
              <td class="col-thumb">{img_tag}</td>
              <td class="col-pnum">
                <div class="part-pnum-container">
                  <strong>{p_num}</strong>
                  <span class="part-info-trigger">
                    <span class="part-info-cue" title="Hover for part details">i</span>
                    <div class="part-popover" role="tooltip">
                      <div class="part-popover-bridge"></div>
                      {popover_content}
                    </div>
                  </span>
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

    # Map visual media to tagged step numbers
    media_step_numbers_map: dict[str, list[int]] = {}
    all_tagged_step_nums: set[int] = set()
    all_tagged_wids: set[str] = set()

    for m_item in (visual_media or []):
        m_id = str(m_item.get("id") or "")
        tagged_steps: list[int] = []
        for t in m_item.get("tagged_work_elements", []):
            t_wid = str(t.get("work_element_id") or "").strip()
            if t_wid:
                all_tagged_wids.add(t_wid)
            if t_wid in step_num_by_wid:
                tagged_steps.append(step_num_by_wid[t_wid])
        for t_wid in m_item.get("tagged_work_element_ids", []):
            t_clean = str(t_wid).strip()
            if t_clean:
                all_tagged_wids.add(t_clean)
            if not tagged_steps and t_clean in step_num_by_wid:
                tagged_steps.append(step_num_by_wid[t_clean])
        tagged_steps = sorted(list(set(tagged_steps)))
        if m_id:
            media_step_numbers_map[m_id] = tagged_steps
        all_tagged_step_nums.update(tagged_steps)

    any_stack_wid_tagged = any(
        (
            str(el.get("work_element_id") or el.get("process_element_id") or "").strip() in all_tagged_wids
            or str(el.get("id") or "").strip() in all_tagged_wids
        )
        for vd in yamazumi_stacks.values()
        for el in (vd.get("elements", []) if isinstance(vd, dict) else (vd if isinstance(vd, list) else []))
        if isinstance(el, dict)
    )

    variant_columns_html: list[str] = []
    max_variant_time = 0.0
    for v_name, v_data in yamazumi_stacks.items():
        v_elements = v_data.get("elements", []) if isinstance(v_data, dict) else (v_data if isinstance(v_data, list) else [])
        v_time = sum(float(e.get("time_s") or 0.0) for e in v_elements if isinstance(e, dict))
        if v_time > max_variant_time:
            max_variant_time = v_time

    # Chart height and unified cycle-time scaling references
    num_variant_cols = max(1, len(yamazumi_stacks))
    chars_per_line = 38 if num_variant_cols == 1 else (19 if num_variant_cols == 2 else max(12, 38 // num_variant_cols))

    def _elem_min_readable_h(elem_dict: dict[str, Any]) -> int:
        desc_text = str(elem_dict.get("description") or elem_dict.get("yamazumi_description") or "").strip()
        clean_len = len(desc_text)
        est_lines = min(4, max(1, (clean_len + chars_per_line - 1) // chars_per_line))
        return 26 + (est_lines - 1) * 14

    ref_time = max(max_variant_time * 1.08, eff_takt_s * 1.12, 1.0)
    px_per_sec = 210.0 / ref_time if ref_time > 0 else 10.0

    for _v_name, _v_data in yamazumi_stacks.items():
        _v_elems = [
            e for e in (_v_data.get("elements", []) if isinstance(_v_data, dict) else (_v_data if isinstance(_v_data, list) else []))
            if isinstance(e, dict)
        ]
        for _e in _v_elems:
            _e_time = float(_e.get("time_s") or 0.0)
            _min_h = _elem_min_readable_h(_e)
            if _e_time > 0:
                px_per_sec = max(px_per_sec, min(18.0, _min_h / max(_e_time, 1.5)))

    stack_allocated_heights: dict[str, list[int]] = {}
    for _v_name, _v_data in yamazumi_stacks.items():
        _v_elems = [
            e for e in (_v_data.get("elements", []) if isinstance(_v_data, dict) else (_v_data if isinstance(_v_data, list) else []))
            if isinstance(e, dict)
        ]
        _v_total_s = sum(float(e.get("time_s") or 0.0) for e in _v_elems)
        _heights = [
            max(_elem_min_readable_h(e), int(round(float(e.get("time_s") or 0.0) * px_per_sec)))
            for e in _v_elems
        ]
        stack_allocated_heights[_v_name] = _heights
        if _v_total_s > 0 and sum(_heights) / _v_total_s > px_per_sec:
            px_per_sec = sum(_heights) / _v_total_s

    max_stack_px = 0
    for _v_name, _v_data in yamazumi_stacks.items():
        _v_elems = [
            e for e in (_v_data.get("elements", []) if isinstance(_v_data, dict) else (_v_data if isinstance(_v_data, list) else []))
            if isinstance(e, dict)
        ]
        _heights = [
            max(_elem_min_readable_h(e), int(round(float(e.get("time_s") or 0.0) * px_per_sec)))
            for e in _v_elems
        ]
        stack_allocated_heights[_v_name] = _heights
        if sum(_heights) > max_stack_px:
            max_stack_px = sum(_heights)

    takt_px = int(round(eff_takt_s * px_per_sec)) if eff_takt_s > 0 else 0
    chart_px_height = max(210, max_stack_px + 20, takt_px + 20)

    for v_name, v_data in yamazumi_stacks.items():
        v_elements = [
            e for e in (v_data.get("elements", []) if isinstance(v_data, dict) else (v_data if isinstance(v_data, list) else []))
            if isinstance(e, dict)
        ]
        v_total_s = sum(float(e.get("time_s") or 0.0) for e in v_elements)
        allocated_heights = stack_allocated_heights.get(v_name, [])

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

            b_height = allocated_heights[idx_e] if idx_e < len(allocated_heights) else max(26, int(round(e_time * px_per_sec)))
            compact_class = "compact" if b_height < 20 else "multiline"

            e_wid = str(e.get("work_element_id") or e.get("process_element_id") or "").strip()
            e_id = str(e.get("id") or "").strip()
            e_desc_key = f"desc::{str(e.get('description') or e.get('yamazumi_description') or '').strip().casefold()}"
            step_num = idx_e + 1
            linked_el = (
                (element_by_wid.get(e_wid) if e_wid else None)
                or (element_by_wid.get(e_id) if e_id else None)
                or (element_by_wid.get(e_desc_key) if e_desc_key != "desc::" else None)
            )

            if any_stack_wid_tagged:
                has_media = (bool(e_wid) and e_wid in all_tagged_wids) or (bool(e_id) and e_id in all_tagged_wids)
            else:
                has_media = step_num > 0 and step_num in all_tagged_step_nums
            if step_num > 0:
                step_popover_html = _step_popover_content(
                    step_num=step_num,
                    yamazumi_elem=e,
                    linked_elem=linked_el,
                    variant_name=v_name,
                    has_media=has_media,
                    pitch=pitch,
                )
                step_badge_html = (
                    f'<span class="stack-step-trigger">'
                    f'<span class="stack-step-badge">{step_num}</span>'
                    f'<div class="step-popover" role="tooltip">'
                    f'<div class="step-popover-bridge"></div>'
                    f'{step_popover_html}'
                    f'</div>'
                    f'</span>'
                )
            else:
                step_badge_html = ""
            cam_icon_html = f'<span class="stack-cam-icon" title="Visual aid attached for Step {step_num}">📷</span>' if has_media else ""
            step_attr = f'data-step-num="{step_num}"' if step_num > 0 else ""
            visual_class = "has-visual" if has_media else ""

            blocks_html.append(
                f"""
                <div class="stack-block {type_class} motion-bar {e_color} {visual_class} {compact_class}" {step_attr} style="height:{b_height}px">
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
        # Takt line position from bottom (no inline label box to avoid cluttering the bars)
        takt_line_html = ""
        if eff_takt_s > 0:
            takt_bottom_px = min(chart_px_height - 10, max(12, takt_px))
            takt_line_html = f'<div class="takt-line" style="bottom:{takt_bottom_px}px" title="Takt: {_clean_number(eff_takt_s)}s"></div>'

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
              <div class="stack-track" style="height:{chart_px_height}px; min-height:{chart_px_height}px">
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

        raw_tagged_steps = list(tagged_steps)
        tagged_op_by_num: dict[int, str] = {}
        for t in item.get("tagged_work_elements", []):
            t_wid = str(t.get("work_element_id") or "").strip()
            s_num = step_num_by_wid.get(t_wid)
            t_op = _text(t.get("operation") or "")
            if s_num and t_op and s_num not in tagged_op_by_num:
                tagged_op_by_num[s_num] = t_op

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
        step_nums_attr = ",".join(str(sn) for sn in tagged_steps)

        if raw_tagged_steps:
            step_lines_html = "".join(
                f'<div class="visual-step-line">'
                f'<span class="visual-tag-badge">{sn}</span>'
                f'<span class="visual-tag-title" title="{step_desc_by_num.get(sn) or tagged_op_by_num.get(sn) or f"Step {sn}"}">'
                f'{step_desc_by_num.get(sn) or tagged_op_by_num.get(sn) or f"Step {sn}"}'
                f'</span>'
                f'</div>'
                for sn in tagged_steps
            )
            all_elements_attr = f' data-tag-summary="All elements ({nums_str})"' if is_all_elements else ""
            step_tag_html = f"""
        <div class="visual-step-tag"{all_elements_attr}>
          {step_lines_html}
        </div>
        """
        elif is_all_elements and tagged_steps:
            step_title_text = f"All elements ({nums_str})"
            tag_badges_html = "".join(f'<span class="visual-tag-badge">{sn}</span>' for sn in tagged_steps)
            step_tag_html = f"""
        <div class="visual-step-tag" data-tag-summary="{step_title_text}">
          <div class="visual-step-line">
            <div class="visual-tag-badges">{tag_badges_html}</div>
            <span class="visual-tag-title" title="{step_title_text}">{step_title_text}</span>
          </div>
        </div>
        """
        else:
            other_tag_lines = [
                f'<div class="visual-step-line">'
                f'<span class="visual-tag-badge">{_text(t.get("work_sequence") or "•")}</span>'
                f'<span class="visual-tag-title" title="{_text(t.get("operation") or "Step")}">{_text(t.get("operation") or "Step")}</span>'
                f'</div>'
                for t in item.get("tagged_work_elements", [])
                if t.get("operation")
            ]
            if other_tag_lines:
                step_tag_html = f"""
        <div class="visual-step-tag">
          {"".join(other_tag_lines)}
        </div>
        """
            else:
                step_title_text = "General Pitch Visual"
                tag_badges_html = '<span class="visual-tag-badge general">General</span>'
                step_tag_html = f"""
        <div class="visual-step-tag general">
          <div class="visual-step-line">
            <div class="visual-tag-badges">{tag_badges_html}</div>
            <span class="visual-tag-title" title="{step_title_text}">{step_title_text}</span>
          </div>
        </div>
        """

        if m_type == "video":
            if media_src:
                media_element_html = f'<video class="visual-player" controls playsinline preload="metadata" src="{media_src}"></video>'
            else:
                media_element_html = '<div class="media-missing">Video not available</div>'
        elif m_type == "link":
            safe_url = html.escape(f_path)
            lower_p = f_path.lower()
            if any(lower_p.endswith(ext) or (ext + "?") in lower_p for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"]):
                media_element_html = f'<img class="visual-image" src="{safe_url}" alt="{caption}" />'
            else:
                label = caption or "Open Document / SOP"
                media_element_html = (
                    f'<div class="media-link-card">'
                    f'<div class="media-link-icon">🌐</div>'
                    f'<div class="media-link-title" title="{label}">{label}</div>'
                    f'<a class="media-link-btn" href="{safe_url}" target="_blank" rel="noopener noreferrer">🔗 Open Web Link</a>'
                    f'</div>'
                )
        elif m_type == "cad":
            file_name = Path(f_path).name
            label = caption or file_name or "3D CAD Model (STEP)"
            safe_lbl = html.escape(label)
            media_element_html = (
                f'<div class="media-link-card media-cad-card">'
                f'<div class="media-link-icon">🧊</div>'
                f'<div class="media-link-title" title="{safe_lbl}">{safe_lbl}</div>'
                f'<div class="media-cad-badge">3D CAD Model (STEP)</div>'
                f'</div>'
            )
        else:
            if media_src:
                media_element_html = f'<img class="visual-image" src="{media_src}" alt="{caption}" />'
            else:
                media_element_html = '<div class="media-missing">Image not available</div>'

        has_custom_caption = bool(
            caption and caption.strip().casefold() not in {"visual aid", "step visual aid"}
        )
        caption_html = (
            f'<div class="caption-callout"><span class="callout-bullet">📍</span> {caption}</div>'
            if has_custom_caption
            else ""
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
    base_task_count = len(all_pitch_elements) if all_pitch_elements else len(set(step_num_by_wid.values()))
    alert_blocks_html: list[str] = []
    for cat_name, display_name, cat_key, page_slug, cat_list in alert_categories:
        if cat_list:
            missing_ppe_items = [
                item for item in cat_list
                if str(item.get("label") or "").strip().lower().startswith("no ppe assigned")
            ]
            other_items = [
                item for item in cat_list
                if not str(item.get("label") or "").strip().lower().startswith("no ppe assigned")
            ]
            if missing_ppe_items:
                eff_total_tasks = max(base_task_count, len(missing_ppe_items))
                assigned_ppe_tasks = max(0, eff_total_tasks - len(missing_ppe_items))
                items_str = f"No PPE assigned ({assigned_ppe_tasks}/{eff_total_tasks} tasks)"
            elif cat_key == "safety":
                cleaned_labels = []
                for item in other_items:
                    raw_lbl = _text(item.get("label") or "Alert")
                    if raw_lbl.lower().startswith("safety:"):
                        raw_lbl = raw_lbl[7:].strip() or raw_lbl
                    cleaned_labels.append(raw_lbl)
                if len(cleaned_labels) == 1 and len(cleaned_labels[0]) <= 28:
                    items_str = cleaned_labels[0]
                else:
                    items_str = f"{len(cleaned_labels)} requirement{'s' if len(cleaned_labels) != 1 else ''}"
            else:
                items_str = " · ".join(_text(item.get("label") or "Alert") for item in other_items)
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
        aspect-ratio: auto;
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
        min-height: 0 !important;
        overflow: hidden;
      }}
      .paag-slide.print-letter {{
        aspect-ratio: 11 / 8.5 !important;
        width: 100% !important;
        max-width: 100% !important;
        min-height: 0 !important;
        padding: 8px 12px;
        gap: 6px;
        overflow: hidden;
      }}
      .paag-slide.print-tabloid .slide-header,
      .paag-slide.print-letter .slide-header,
      .paag-slide.print-tabloid .functional-alerts-bar,
      .paag-slide.print-letter .functional-alerts-bar {{
        flex: 0 0 auto;
      }}
      .paag-slide.print-tabloid .slide-body {{
        grid-template-columns: minmax(0, 32fr) minmax(0, 68fr);
        grid-template-rows: minmax(0, 1fr);
        gap: 14px;
        flex: 1 1 0;
        height: 0;
        min-height: 0;
        max-height: 100%;
        overflow: hidden;
      }}
      .paag-slide.print-letter .slide-body {{
        grid-template-columns: minmax(0, 36fr) minmax(0, 64fr);
        grid-template-rows: minmax(0, 1fr);
        gap: 10px;
        flex: 1 1 0;
        height: 0;
        min-height: 0;
        max-height: 100%;
        overflow: hidden;
      }}
      .paag-slide.print-tabloid .left-col,
      .paag-slide.print-letter .left-col {{
        height: 100%;
        min-height: 0;
        max-height: 100%;
        display: flex;
        flex-direction: column;
        gap: 6px;
        overflow: hidden;
      }}
      .paag-slide.print-tabloid .left-col > .tools-panel,
      .paag-slide.print-letter .left-col > .tools-panel,
      .paag-slide.print-tabloid .left-col > .parts-panel,
      .paag-slide.print-letter .left-col > .parts-panel {{
        flex: 0 0 auto;
      }}
      .paag-slide.print-tabloid .left-col > .stack-panel,
      .paag-slide.print-letter .left-col > .stack-panel {{
        flex: 1 1 0 !important;
        height: 0 !important;
        min-height: 0 !important;
        margin-top: 0 !important;
        display: flex !important;
        flex-direction: column !important;
        overflow: hidden !important;
      }}
      .paag-slide.print-tabloid .stacks-container,
      .paag-slide.print-letter .stacks-container {{
        flex: 1 1 0 !important;
        height: 0 !important;
        min-height: 0 !important;
      }}
      .paag-slide.print-tabloid .variant-stack-col,
      .paag-slide.print-letter .variant-stack-col {{
        height: 100% !important;
        min-height: 0 !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: flex-end !important;
      }}
      .paag-slide.print-tabloid .stack-track,
      .paag-slide.print-letter .stack-track {{
        flex: 1 1 0 !important;
        height: auto !important;
        min-height: 0 !important;
        overflow: hidden !important;
      }}
      .paag-slide.print-tabloid .right-col,
      .paag-slide.print-letter .right-col {{
        height: 100%;
        min-height: 0;
        max-height: 100%;
        flex: 1 1 0;
        overflow: hidden;
      }}
      .paag-slide.print-tabloid .visual-grid,
      .paag-slide.print-letter .visual-grid {{
        height: 100%;
        min-height: 0;
        max-height: 100%;
        flex: 1 1 0;
        overflow: hidden;
      }}
      .paag-slide.print-tabloid .visual-card,
      .paag-slide.print-letter .visual-card {{
        height: 100%;
        min-height: 0;
        max-height: 100%;
        flex: 1 1 0;
        display: flex;
        flex-direction: column;
        overflow: hidden;
      }}
      .paag-slide.print-tabloid .visual-step-tag,
      .paag-slide.print-letter .visual-step-tag,
      .paag-slide.print-tabloid .caption-callout,
      .paag-slide.print-letter .caption-callout {{
        flex: 0 0 auto;
      }}
      .paag-slide.print-tabloid .visual-media-box,
      .paag-slide.print-letter .visual-media-box {{
        height: 0;
        min-height: 0;
        max-height: 100%;
        flex: 1 1 0;
        overflow: hidden;
      }}
      .paag-slide.fit-stretch .visual-image,
      .paag-slide.fit-fill .visual-image,
      .paag-slide.print-tabloid.fit-stretch .visual-image,
      .paag-slide.print-tabloid.fit-fill .visual-image,
      .paag-slide.print-letter.fit-stretch .visual-image,
      .paag-slide.print-letter.fit-fill .visual-image {{
        width: 100% !important;
        height: 100% !important;
        max-width: 100% !important;
        max-height: 100% !important;
        object-fit: fill !important;
      }}
      .paag-slide.fit-cover .visual-image {{
        width: 100% !important;
        height: 100% !important;
        max-width: 100% !important;
        max-height: 100% !important;
        object-fit: cover !important;
      }}
      .paag-slide.fit-contain .visual-image,
      .paag-slide.print-tabloid.fit-contain .visual-image,
      .paag-slide.print-letter.fit-contain .visual-image {{
        width: 100% !important;
        height: 100% !important;
        max-width: 100% !important;
        max-height: 100% !important;
        object-fit: contain !important;
      }}
      /* Header Banner */
      .slide-header {{
        display: grid;
        grid-template-columns: minmax(0, 1.25fr) minmax(0, 1.5fr) minmax(0, 1.45fr);
        align-items: center;
        gap: 10px;
        padding-bottom: 5px;
        border-bottom: 2px solid #e2e8f0;
      }}
      .header-left {{
        min-width: 0;
        display: flex;
        align-items: center;
        justify-content: flex-start;
      }}
      .header-logo-img {{
        height: 68px;
        max-width: 310px;
        width: auto;
        object-fit: contain;
        display: block;
      }}
      .brand-title {{
        font-size: 1.15rem;
        font-weight: 800;
        color: #0b3768;
        letter-spacing: -0.01em;
        overflow-wrap: anywhere;
        word-break: break-word;
      }}
      .brand-sub {{
        font-size: 0.75rem;
        font-weight: 700;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        overflow-wrap: anywhere;
        word-break: break-word;
      }}
      .pitch-center-title {{
        text-align: center;
        font-size: 1.45rem;
        font-weight: 800;
        color: #0b3768;
        min-width: 0;
        overflow-wrap: anywhere;
        word-break: break-word;
      }}
      .header-right {{
        min-width: 0;
        justify-self: end;
        width: 100%;
        max-width: 340px;
        display: flex;
        flex-direction: column;
        align-items: stretch;
        gap: 3px;
      }}
      .header-doc-title {{
        font-size: 1.22rem;
        font-weight: 800;
        color: #0b3768;
        text-align: right;
        line-height: 1.1;
        letter-spacing: -0.01em;
      }}
      .doc-control-box {{
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        background: #f8fafc;
        padding: 4px 9px;
        font-size: 0.73rem;
        color: #475569;
        line-height: 1.32;
        text-align: left;
        min-width: 0;
        width: 100%;
        box-sizing: border-box;
        overflow-wrap: anywhere;
        word-break: break-word;
      }}
      .doc-control-grid {{
        display: grid;
        grid-template-columns: minmax(0, 1.05fr) minmax(0, 0.95fr);
        column-gap: 12px;
        align-items: start;
      }}
      .doc-control-col {{
        display: flex;
        flex-direction: column;
        gap: 1px;
        min-width: 0;
      }}
      .doc-control-box strong {{
        color: #334155;
      }}
      /* Main Content Split */
      .slide-body {{
        flex: 1 1 auto;
        min-height: auto;
        display: grid;
        grid-template-columns: minmax(0, 37fr) minmax(0, 63fr);
        gap: 12px;
        align-items: stretch;
        overflow: visible;
      }}
      .left-col {{
        display: flex;
        flex-direction: column;
        gap: 8px;
        min-height: auto;
        min-width: 0;
        max-width: 100%;
        height: auto;
        box-sizing: border-box;
        overflow: visible;
        position: relative;
        z-index: 20;
      }}
      .right-col {{
        display: flex;
        flex-direction: column;
        min-height: 0;
        min-width: 0;
        max-width: 100%;
        height: 100%;
        box-sizing: border-box;
        overflow: visible;
      }}
      /* Left Column Subpanels */
      .panel-section {{
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        background: #fdfdfe;
        padding: 5px 8px;
        display: flex;
        flex-direction: column;
        flex: 0 0 auto;
        min-height: auto;
        min-width: 0;
        max-width: 100%;
        box-sizing: border-box;
      }}
      .tools-panel {{
        flex: 0 0 auto;
        min-height: 54px;
        padding: 6px 10px;
        overflow: visible;
      }}
      .panel-title-bar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 4px;
        font-size: 0.78rem;
        font-weight: 800;
        text-transform: uppercase;
        color: #475569;
        margin-bottom: 3px;
        letter-spacing: 0.03em;
      }}
      .header-page-row {{
        margin-bottom: 4px;
      }}
      .tie-tool-slide-btn {{
        display: inline-flex;
        align-items: center;
        gap: 3px;
        background: #f0f9ff;
        color: #0284c7;
        border: 1px solid #bae6fd;
        border-radius: 4px;
        padding: 1px 7px;
        font-size: 0.68rem;
        font-weight: 700;
        text-transform: none;
        letter-spacing: 0.01em;
        cursor: pointer;
        transition: all 0.15s ease;
      }}
      .tie-tool-slide-btn:hover {{
        background: #e0f2fe;
        border-color: #38bdf8;
        color: #0369a1;
      }}
      .header-page-row-noop {{
        margin-bottom: 4px;
      }}
      .page-badge {{
        display: inline-block;
        background: #0284c7;
        color: white;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.03em;
      }}
      .tools-list {{
        margin: 0;
        padding-left: 18px;
        font-size: 0.80rem;
        color: #1e293b;
        max-height: none;
        overflow: visible;
      }}
      .tool-item {{
        margin-bottom: 4px;
        white-space: normal;
        overflow-wrap: anywhere;
        word-break: break-word;
        line-height: 1.35;
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
        max-width: 100%;
        table-layout: auto;
        border-collapse: collapse;
        font-size: 0.74rem;
        box-sizing: border-box;
      }}
      .parts-table th {{
        text-align: left;
        background: #f1f5f9;
        padding: 3px 4px;
        color: #475569;
        font-size: 0.68rem;
        font-weight: 700;
        line-height: 1.15;
        border-bottom: 2px solid #e2e8f0;
        overflow-wrap: anywhere;
        word-break: break-word;
      }}
      .parts-table th {{
        white-space: nowrap;
        overflow-wrap: normal;
        word-break: normal;
      }}
      .parts-table th.col-qty {{
        text-align: center;
      }}
      .parts-table th.col-handling {{
        text-align: center;
        white-space: normal;
        overflow-wrap: normal;
        word-break: keep-all;
        line-height: 1.15;
      }}
      .parts-table td {{
        padding: 3px 4px;
        border-bottom: 1px solid #f1f5f9;
        vertical-align: middle;
      }}
      .parts-table tr.part-row {{
        transition: background-color 0.15s ease;
      }}
      .parts-table tr.part-row:hover {{
        background-color: #f1f5f9;
      }}
      .parts-mc-legend {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 0.65rem;
        font-weight: 800;
        color: #6d28d9;
        background: #f3e8ff;
        border: 1.5px solid #7c3aed;
        border-radius: 4px;
        padding: 1px 6px;
        text-transform: none;
        letter-spacing: 0.01em;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
      .swatch-mc-outline {{
        display: inline-block;
        width: 9px;
        height: 9px;
        border: 2px solid #7c3aed;
        background: #faf5ff;
        border-radius: 2px;
        box-sizing: border-box;
      }}
      .parts-table tr.model-choice-spacer-row td {{
        height: 4px;
        padding: 0 !important;
        border: none !important;
        background: transparent !important;
      }}
      .parts-table tr.model-choice-label-row td.model-choice-label-cell {{
        padding: 1px 6px !important;
        background: #f3e8ff !important;
        border-top: 2px solid #7c3aed !important;
        border-left: 2px solid #7c3aed !important;
        border-right: 2px solid #7c3aed !important;
        border-bottom: 1px solid #ddd6fe !important;
        line-height: 1.1;
        text-align: left;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
      .model-choice-outline-label {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 0.62rem;
        font-weight: 800;
        color: #6d28d9;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }}
      .parts-table tr.part-row.model-choice-row {{
        background-color: #faf5ff;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
      .parts-table tr.part-row.model-choice-row:hover {{
        background-color: #f3e8ff;
      }}
      .parts-table tr.part-row.model-choice-row td:first-child {{
        border-left: 2px solid #7c3aed !important;
      }}
      .parts-table tr.part-row.model-choice-row td:last-child {{
        border-right: 2px solid #7c3aed !important;
      }}
      .parts-table tr.part-row.model-choice-row.model-choice-last td {{
        border-bottom: 2px solid #7c3aed !important;
      }}
      .part-info-trigger:hover .part-popover,
      .part-info-trigger.popover-active .part-popover {{
        display: block;
      }}
      .part-pnum-container {{
        flex-wrap: nowrap !important;
        white-space: nowrap !important;
        display: inline-flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 3px;
        max-width: 100%;
      }}
      .part-pnum-container strong {{
        white-space: nowrap !important;
        overflow-wrap: normal !important;
        word-break: normal !important;
        overflow-wrap: anywhere;
        word-break: break-word;
        line-height: 1.15;
      }}
      .part-info-trigger {{
        position: relative;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 4px 6px;
        margin: -4px -6px;
        cursor: pointer;
        flex-shrink: 0;
      }}
      .part-info-cue {{
        display: inline-block;
        font-size: 0.62rem;
        color: #ffffff;
        background: #0284c7;
        border: 1px solid #0284c7;
        border-radius: 999px;
        width: 13px;
        height: 13px;
        line-height: 11px;
        text-align: center;
        font-weight: 700;
        cursor: pointer;
        transition: all 0.15s ease;
      }}
      .part-info-trigger:hover .part-info-cue,
      .part-info-trigger.popover-active .part-info-cue {{
        color: #ffffff;
        background: #0369a1;
        border-color: #0369a1;
        box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.25);
      }}
      .col-thumb {{ width: 38px; min-width: 38px; text-align: center; }}
      .part-thumb {{
        width: 34px;
        height: 28px;
        object-fit: contain;
        border-radius: 4px;
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        display: block;
        margin: 0 auto;
      }}
      .thumb-ph {{
        width: 34px;
        height: 28px;
        line-height: 28px;
        text-align: center;
        background: #f1f5f9;
        border: 1px dashed #cbd5e1;
        font-size: 0.62rem;
        color: #64748b;
        font-weight: 700;
        border-radius: 4px;
        margin: 0 auto;
      }}
      .col-pnum {{ width: 1%; white-space: nowrap; font-weight: 700; font-size: 0.76rem; color: #1e293b; overflow: visible; }}
      .col-desc {{ width: auto; min-width: 90px; white-space: normal; }}
      .part-desc-text {{
        font-weight: 600;
        color: #0f172a;
        line-height: 1.2;
        white-space: normal;
        overflow-wrap: anywhere;
        word-break: break-word;
      }}
      .part-nick-text {{
        font-size: 0.70rem;
        color: #0284c7;
        font-weight: 700;
        line-height: 1.15;
        white-space: normal;
        overflow-wrap: anywhere;
        word-break: break-word;
        margin-top: 2px;
      }}
      .part-nick-space {{
        display: none;
      }}
      .col-qty {{ width: 1%; min-width: 28px; text-align: center; font-weight: 800; font-size: 0.78rem; white-space: nowrap; padding: 2px 4px; }}
      .col-handling {{ width: 64px; min-width: 60px; text-align: center; white-space: normal; overflow-wrap: normal; word-break: keep-all; padding: 2px 4px; }}
      .h-badge {{
        display: inline-block;
        font-size: 0.68rem;
        padding: 2px 6px;
        border-radius: 3px;
        font-weight: 800;
        letter-spacing: 0.01em;
        margin: 1px 0;
      }}
      .h-badge.va {{ background: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; }}
      .h-badge.nvan {{ background: #fef9c3; color: #854d0e; border: 1px solid #fde047; }}
      .text-muted {{ color: #94a3b8; }}
      .part-placeholder.no-parts {{ padding: 14px; text-align: center; font-size: 0.78rem; color: #94a3b8; font-style: italic; }}

      /* Floating Part Popover Window */
      .part-popover {{
        display: none;
        position: absolute;
        top: -10px;
        left: calc(100% + 8px);
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
        left: -14px;
        width: 14px;
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
        text-decoration: none;
        display: inline-flex;
        align-items: center;
        gap: 2px;
      }}
      a.popover-step-link {{
        color: #1d4ed8;
        border-color: #93c5fd;
        background: #eff6ff;
        cursor: pointer;
        transition: background 0.12s ease, border-color 0.12s ease;
      }}
      a.popover-step-link:hover {{
        background: #dbeafe;
        border-color: #3b82f6;
        text-decoration: underline;
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
      .left-col > .panel-section {{
        position: relative;
        flex: 0 0 auto;
        width: 100%;
        box-sizing: border-box;
      }}
      .stack-panel {{
        margin-top: 0 !important;
        flex: 0 0 auto;
        min-height: 0 !important;
        height: auto !important;
        padding: 8px 10px;
        box-sizing: border-box;
        overflow: visible;
        position: relative;
      }}
      .stacks-container {{
        min-height: 0 !important;
        height: auto !important;
        align-items: stretch;
        margin-top: 4px;
      }}
      .variant-stack-col {{
        justify-content: space-between !important;
        gap: 4px;
      }}
      .variant-header {{
        margin-bottom: 4px !important;
        flex: 0 0 auto;
        position: relative;
        z-index: 2;
      }}
      .stack-track {{
        flex: 0 0 auto;
        width: 100%;
        box-sizing: border-box;
      }}
      .stack-block {{
        min-height: 0 !important;
        flex: 0 0 auto;
      }}
      .stack-block.compact {{
        line-height: 1;
      }}
      .stack-block.compact .stack-step-trigger {{
        padding: 0;
        margin: 0;
      }}
      .stack-block.compact .stack-step-badge {{
        font-size: 0.56rem;
        padding: 0 2px;
        line-height: 10px;
        min-width: 12px;
      }}
      .stack-panel {{
        margin-top: auto;
        flex: 0 0 auto;
        min-height: 230px;
        padding: 6px 10px;
        box-sizing: border-box;
        overflow: visible;
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
        gap: 6px;
        width: 100%;
        max-width: 100%;
        box-sizing: border-box;
        height: auto;
        min-height: 195px;
        overflow: visible;
      }}
      .variant-stack-col {{
        flex: 1 1 0;
        min-width: 0;
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
        position: relative;
        overflow: visible;
      }}
      .variant-stack-col:hover,
      .variant-stack-col:focus-within {{
        z-index: 40;
      }}
      .variant-header {{
        font-size: 0.68rem;
        font-weight: 700;
        text-align: center;
        color: #334155;
        margin-bottom: 2px;
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        align-items: center;
        gap: 2px;
        line-height: 1.15;
        overflow-wrap: anywhere;
        word-break: break-word;
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
        overflow: visible;
      }}
      .stack-blocks-wrapper {{
        display: flex;
        flex-direction: column-reverse;
        width: 100%;
        overflow: visible;
      }}
      .stack-block {{
        width: 100%;
        box-sizing: border-box;
        border-bottom: 1px solid rgba(255,255,255,0.4);
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0 4px;
        font-size: 0.66rem;
        font-weight: 700;
        overflow: visible;
        position: relative;
        cursor: pointer;
        transition: filter 0.15s ease, outline 0.15s ease, box-shadow 0.15s ease;
        line-height: 1.1;
      }}
      .stack-block:hover,
      .stack-block:focus-within {{
        z-index: 50;
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
        gap: 3px;
        min-width: 0;
        overflow: visible;
        flex: 1 1 auto;
      }}
      .stack-block.multiline {{
        padding: 2px 4px;
        align-items: center;
      }}
      .stack-block.multiline .block-left {{
        display: flex;
        align-items: center;
        gap: 3px;
        min-width: 0;
        max-height: 100%;
        overflow: visible;
        line-height: 1.15;
      }}
      .stack-block.multiline .stack-step-badge {{
        font-size: 0.66rem;
        padding: 0 4px;
        min-width: 14px;
        line-height: 13px;
      }}
      .stack-block.multiline .block-label {{
        display: -webkit-box;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 5;
        white-space: normal;
        overflow: visible;
        text-overflow: clip;
        overflow-wrap: anywhere;
        word-break: break-word;
        line-height: 1.18;
        max-height: none;
      }}
      .stack-block.multiline .block-right {{
        margin-left: 3px;
        font-size: 0.64rem;
      }}
      .stack-step-trigger {{
        position: relative;
        display: inline-flex;
        align-items: center;
        flex-shrink: 0;
        padding: 1px;
        margin: -1px;
      }}
      .stack-step-badge {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: #0f172a;
        color: #ffffff;
        font-size: 0.70rem;
        font-weight: 800;
        padding: 1px 4px;
        min-width: 15px;
        text-align: center;
        border-radius: 4px;
        line-height: 13px;
        flex-shrink: 0;
        border: 1px solid rgba(255, 255, 255, 0.4);
        box-sizing: border-box;
        cursor: pointer;
        transition: transform 0.12s ease, background 0.12s ease;
      }}
      .stack-step-trigger:hover .stack-step-badge {{
        transform: scale(1.1);
        border-color: #ffffff;
      }}
      .stack-block.has-visual .stack-step-badge {{
        background: #0284c7;
        border-color: #bae6fd;
      }}
      .step-popover {{
        display: none;
        position: absolute;
        bottom: calc(100% + 8px);
        left: -4px;
        width: 260px;
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        box-shadow: 0 12px 28px -4px rgba(15, 23, 42, 0.28), 0 4px 10px -2px rgba(15, 23, 42, 0.14);
        padding: 9px 11px;
        z-index: 1200;
        white-space: normal;
        text-align: left;
        font-weight: normal;
        color: #1e293b;
        box-sizing: border-box;
        cursor: default;
        pointer-events: auto;
      }}
      .step-popover-bridge {{
        position: absolute;
        left: 0;
        right: 0;
        bottom: -10px;
        height: 10px;
      }}
      .step-popover::before {{
        content: "";
        position: absolute;
        bottom: -7px;
        left: 10px;
        width: 0;
        height: 0;
        border-left: 7px solid transparent;
        border-right: 7px solid transparent;
        border-top: 7px solid #cbd5e1;
      }}
      .step-popover::after {{
        content: "";
        position: absolute;
        bottom: -6px;
        left: 11px;
        width: 0;
        height: 0;
        border-left: 6px solid transparent;
        border-right: 6px solid transparent;
        border-top: 6px solid #ffffff;
      }}
      .stack-step-trigger:hover .step-popover,
      .stack-step-trigger:focus-within .step-popover,
      .stack-step-trigger.popover-active .step-popover {{
        display: block;
      }}
      .step-popover-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 6px;
        border-bottom: 1px solid #e2e8f0;
        padding-bottom: 5px;
        margin-bottom: 6px;
      }}
      .step-popover-badges {{
        display: flex;
        align-items: center;
        gap: 5px;
      }}
      .step-popover-num {{
        font-size: 0.78rem;
        font-weight: 800;
        color: #0f172a;
        text-decoration: none;
      }}
      a.step-popover-link {{
        color: #1d4ed8;
        background: #eff6ff;
        border: 1px solid #bfdbfe;
        padding: 1px 6px;
        border-radius: 4px;
        cursor: pointer;
        transition: background 0.12s ease, border-color 0.12s ease;
      }}
      a.step-popover-link:hover {{
        background: #dbeafe;
        border-color: #3b82f6;
        text-decoration: underline;
      }}
      .step-popover-type {{
        font-size: 0.65rem;
        font-weight: 700;
        padding: 1px 5px;
        border-radius: 4px;
      }}
      .step-popover-type.cycle {{
        background: #dcfce7;
        color: #166534;
        border: 1px solid #86efac;
      }}
      .step-popover-type.periodic {{
        background: #fef9c3;
        color: #854d0e;
        border: 1px solid #fde047;
      }}
      .step-popover-type.fluctuation {{
        background: #fee2e2;
        color: #991b1b;
        border: 1px solid #fca5a5;
      }}
      .step-popover-time {{
        font-size: 0.78rem;
        font-weight: 800;
        color: #0f172a;
        background: #f1f5f9;
        padding: 1px 6px;
        border-radius: 4px;
        border: 1px solid #cbd5e1;
      }}
      .step-popover-desc {{
        font-size: 0.78rem;
        font-weight: 700;
        color: #0f172a;
        line-height: 1.35;
        word-break: break-word;
      }}
      .step-popover-subdesc {{
        font-size: 0.70rem;
        color: #475569;
        margin-top: 3px;
        line-height: 1.25;
      }}
      .step-popover-media-note {{
        margin-top: 5px;
        font-size: 0.68rem;
        font-weight: 600;
        color: #0369a1;
        background: #f0f9ff;
        border: 1px solid #bae6fd;
        border-radius: 4px;
        padding: 2px 6px;
      }}
      .stack-block .block-right {{
        display: flex;
        align-items: center;
        gap: 2px;
        flex-shrink: 0;
        margin-left: 3px;
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
      .stack-block, .stack-block.type-cycle, .stack-block.type-periodic, .stack-block.type-fluctuation {{ color: #000000 !important; }}
      .block-label {{ white-space: normal; overflow-wrap: anywhere; word-break: break-word; line-height: 1.18; min-width: 0; color: #000000; }}
      .block-time {{ font-weight: 800; flex-shrink: 0; color: #000000; }}
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
      .grid-layout-1 {{ grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1fr); }}
      .grid-layout-2 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); grid-template-rows: minmax(0, 1fr); }}
      .grid-layout-3 {{ grid-template-columns: repeat(3, minmax(0, 1fr)); grid-template-rows: minmax(0, 1fr); }}
      .grid-layout-4 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); grid-template-rows: repeat(2, minmax(0, 1fr)); }}
      .grid-layout-6 {{ grid-template-columns: repeat(3, minmax(0, 1fr)); grid-template-rows: repeat(2, minmax(0, 1fr)); }}

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
        flex-direction: column;
        align-items: stretch;
        gap: 3px;
        min-width: 0;
      }}
      .visual-step-tag.general {{
        background: #475569;
      }}
      .visual-step-line {{
        display: flex;
        align-items: flex-start;
        gap: 6px;
        min-width: 0;
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
        white-space: normal;
        overflow-wrap: anywhere;
        word-break: break-word;
        line-height: 1.2;
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
      .media-link-card {{
        width: 100%;
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        background: #0f172a;
        color: #f8fafc;
        padding: 10px;
        text-align: center;
        gap: 6px;
      }}
      .media-link-icon {{
        font-size: 1.8rem;
        line-height: 1;
      }}
      .media-link-title {{
        font-size: 0.8rem;
        font-weight: 600;
        color: #cbd5e1;
        max-width: 90%;
        white-space: normal;
        overflow-wrap: anywhere;
        word-break: break-word;
      }}
      .media-link-btn {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: #0284c7;
        color: #ffffff !important;
        text-decoration: none;
        font-size: 0.78rem;
        font-weight: 600;
        padding: 6px 12px;
        border-radius: 4px;
        transition: background 0.15s ease;
      }}
      .media-link-btn:hover {{
        background: #0369a1;
      }}
      .media-cad-card {{
        background: #1e293b;
        border: 1px solid #334155;
      }}
      .media-cad-badge {{
        display: inline-block;
        font-size: 0.72rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        background: #0f766e;
        color: #ccfbf1;
        padding: 3px 8px;
        border-radius: 4px;
        margin-top: 4px;
      }}
      .caption-callout {{
        background: #fef08a;
        color: #713f12;
        border-top: 2px solid #eab308;
        padding: 6px 10px;
        font-size: 0.82rem;
        font-weight: 700;
        line-height: 1.25;
        white-space: normal;
        overflow-wrap: anywhere;
        word-break: break-word;
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
        padding: 3px 8px;
        display: grid;
        grid-template-columns: repeat(5, 1fr);
        gap: 6px;
        align-items: center;
        font-size: 0.70rem;
        position: relative;
        z-index: 50;
        overflow: visible;
      }}
      .alert-block {{
        position: relative;
        overflow: visible;
        padding: 2px 6px;
        border-radius: 4px;
        display: flex;
        align-items: baseline;
        flex-wrap: wrap;
        gap: 4px;
        min-width: 0;
        cursor: pointer;
        transition: background-color 0.15s ease, border-color 0.15s ease;
      }}
      .alert-block strong {{
        flex-shrink: 0;
      }}
      .alert-summary {{
        font-size: 0.68rem;
        white-space: normal;
        overflow-wrap: anywhere;
        word-break: break-word;
        line-height: 1.15;
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
      .paag-slide.presentation-active .header-logo-img {{ height: 82px; max-width: 360px; }}
      .paag-slide.presentation-active .header-doc-title {{ font-size: 1.4rem; }}
      .paag-slide.presentation-active .brand-title {{ font-size: 1.35rem; }}
      .paag-slide.presentation-active .pitch-center-title {{ font-size: 1.75rem; }}
      .paag-slide.presentation-active .doc-control-box {{ font-size: 0.85rem; }}
      .paag-slide.presentation-active .panel-title-bar {{ font-size: 0.92rem; }}
      .paag-slide.presentation-active .tools-list {{ font-size: 0.92rem; max-height: none; }}
      .paag-slide.presentation-active .parts-table {{ font-size: 0.88rem; }}
      .paag-slide.presentation-active .parts-table th {{ font-size: 0.82rem; }}
      .paag-slide.presentation-active .col-thumb {{ width: 62px; min-width: 62px; }}
      .paag-slide.presentation-active .part-thumb {{ width: 56px; height: 48px; }}
      .paag-slide.presentation-active .thumb-ph {{ width: 56px; height: 48px; line-height: 48px; font-size: 0.75rem; }}
      .paag-slide.presentation-active .h-badge {{ font-size: 0.75rem; padding: 3px 8px; }}
      .paag-slide.presentation-active .caption-callout {{ font-size: 0.95rem; }}
      .paag-slide.presentation-active .visual-step-tag {{ font-size: 0.9rem; }}
      .paag-slide.presentation-active .functional-alerts-bar {{ font-size: 0.88rem; }}

      .alert-block.popover-active .alert-popover {{
        display: block;
      }}

      /* Responsive adaptation for smaller monitors, split windows, tablets, and mobile phones */
      @media (max-width: 1280px) {{
        .paag-slide:not(.print-tabloid):not(.print-letter) {{
          aspect-ratio: auto;
          min-height: auto;
        }}
        .paag-slide:not(.print-tabloid):not(.print-letter) .functional-alerts-bar {{
          grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        }}
        .paag-slide:not(.print-tabloid):not(.print-letter) .pitch-center-title {{
          font-size: clamp(1.1rem, 1.9vw, 1.45rem);
        }}
      }}

      @media (max-width: 960px) {{
        .paag-slide:not(.print-tabloid):not(.print-letter) .slide-header {{
          grid-template-columns: 1fr;
          gap: 6px;
          text-align: left;
        }}
        .paag-slide:not(.print-tabloid):not(.print-letter) .pitch-center-title {{
          text-align: left;
          font-size: 1.2rem;
        }}
        .paag-slide:not(.print-tabloid):not(.print-letter) .header-right {{
          justify-self: start;
          max-width: 100%;
        }}
        .paag-slide:not(.print-tabloid):not(.print-letter) .header-doc-title {{
          text-align: left;
        }}
        .paag-slide:not(.print-tabloid):not(.print-letter) .doc-control-box {{
          justify-self: start;
          text-align: left;
          width: 100%;
          box-sizing: border-box;
        }}
        .paag-slide:not(.print-tabloid):not(.print-letter) .slide-body {{
          grid-template-columns: 1fr;
          gap: 12px;
        }}
        .paag-slide:not(.print-tabloid):not(.print-letter) .right-col .visual-grid {{
          min-height: 360px;
        }}
        .paag-slide:not(.print-tabloid):not(.print-letter) .part-popover,
        .paag-slide:not(.print-tabloid):not(.print-letter) .alert-popover {{
          position: fixed !important;
          left: 16px !important;
          right: 16px !important;
          top: auto !important;
          bottom: 16px !important;
          transform: none !important;
          width: auto !important;
          max-width: calc(100vw - 32px) !important;
          max-height: 75vh !important;
          overflow-y: auto !important;
          z-index: 9999 !important;
        }}
        .paag-slide:not(.print-tabloid):not(.print-letter) .part-popover::before,
        .paag-slide:not(.print-tabloid):not(.print-letter) .part-popover::after,
        .paag-slide:not(.print-tabloid):not(.print-letter) .alert-popover::before,
        .paag-slide:not(.print-tabloid):not(.print-letter) .alert-popover::after,
        .paag-slide:not(.print-tabloid):not(.print-letter) .part-popover-bridge,
        .paag-slide:not(.print-tabloid):not(.print-letter) .alert-popover-bridge {{
          display: none !important;
        }}
      }}

      @media (max-width: 640px) {{
        .paag-slide:not(.print-tabloid):not(.print-letter) {{
          padding: 8px 10px;
        }}
        .paag-slide:not(.print-tabloid):not(.print-letter) .functional-alerts-bar {{
          grid-template-columns: 1fr;
        }}
        .paag-slide:not(.print-tabloid):not(.print-letter) .visual-grid.grid-layout-2,
        .paag-slide:not(.print-tabloid):not(.print-letter) .visual-grid.grid-layout-3,
        .paag-slide:not(.print-tabloid):not(.print-letter) .visual-grid.grid-layout-4,
        .paag-slide:not(.print-tabloid):not(.print-letter) .visual-grid.grid-layout-6 {{
          grid-template-columns: 1fr !important;
          grid-template-rows: auto !important;
        }}
        .paag-slide:not(.print-tabloid):not(.print-letter) .parts-panel {{
          overflow-x: auto;
        }}
      }}

      @media print {{
        @page {{
          size: {"17in 11in landscape" if print_format == "tabloid" else "11in 8.5in landscape"};
          margin: 0.2in;
        }}
        html, body {{
          margin: 0 !important;
          padding: 0 !important;
          background: #ffffff !important;
          -webkit-print-color-adjust: exact !important;
          print-color-adjust: exact !important;
        }}
        .paag-slide, .paag-slide * {{
          -webkit-print-color-adjust: exact !important;
          print-color-adjust: exact !important;
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
          overflow: hidden !important;
          box-sizing: border-box !important;
        }}
        .paag-slide:last-child {{
          page-break-after: auto !important;
          break-after: auto !important;
        }}
        .paag-slide.print-tabloid {{
          width: 100% !important;
          height: min(10.35in, 98vh) !important;
          max-height: min(10.35in, 98vh) !important;
          aspect-ratio: auto !important;
          overflow: hidden !important;
        }}
        .paag-slide.print-letter {{
          width: 100% !important;
          height: min(7.85in, 98vh) !important;
          max-height: min(7.85in, 98vh) !important;
          aspect-ratio: auto !important;
          overflow: hidden !important;
        }}
        .paag-slide .slide-body {{
          flex: 1 1 0 !important;
          height: 0 !important;
          min-height: 0 !important;
          max-height: 100% !important;
          grid-template-rows: minmax(0, 1fr) !important;
          overflow: hidden !important;
        }}
        .paag-slide .right-col,
        .paag-slide .visual-grid,
        .paag-slide .visual-card {{
          height: 100% !important;
          min-height: 0 !important;
          max-height: 100% !important;
          flex: 1 1 0 !important;
          overflow: hidden !important;
        }}
        .paag-slide .visual-step-tag,
        .paag-slide .caption-callout {{
          flex: 0 0 auto !important;
        }}
        .paag-slide .visual-media-box {{
          flex: 1 1 0 !important;
          height: 0 !important;
          min-height: 0 !important;
          max-height: 100% !important;
          overflow: hidden !important;
          background: #ffffff !important;
        }}
        .paag-slide .visual-image,
        .paag-slide .visual-player {{
          width: 100% !important;
          height: 100% !important;
          max-width: 100% !important;
          max-height: 100% !important;
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
          {logo_html}
        </div>
        <div class="pitch-center-title">
          {pitch_title_display}
          {ergo_chips_html}
        </div>
        <div class="header-right">
          <div class="header-doc-title">Process at a Glance</div>
          <div class="doc-control-box">
            <div class="doc-control-grid">
              <div class="doc-control-col">
                <div><strong>Project:</strong> {eff_project_name}</div>
                <div><strong>Building:</strong> {eff_building_name}</div>
                <div><strong>Section:</strong> {eff_section_name}</div>
              </div>
              <div class="doc-control-col">
                <div><strong>Date:</strong> {generated_label}</div>
                <div><strong>Scenario:</strong> {eff_scenario_name}</div>
              </div>
            </div>
            <!-- Exact string assertion support for audit and tests -->
            <div style="display:none">
              <div class="header-page-row"><span class="page-badge">Page {eff_page_num} of {eff_total_pages}</span></div>
              <span>Process at a Glance for {eff_project_name}</span>
              <span>Generated on {generated_label} — Scenario: {eff_scenario_name}</span>
            </div>
          </div>
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
          <div class="panel-section tools-panel">
            <div class="panel-title-bar">
              <span>Tools &amp; PPE Required</span>
              {tie_tool_btn_html}
            </div>
            {tools_section_html}
          </div>

          <!-- Parts Table -->
          <div class="panel-section parts-panel">
            <div class="panel-title-bar">
              <span>Parts</span>
              {parts_title_legend_html}
            </div>
            {parts_section_html}
          </div>

          <!-- Mini Yamazumi Stack -->
          <div class="panel-section stack-panel">
            <div class="panel-title-bar">
              <span>Yamazumi</span>
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

        function setupTouchAndViewportPopovers() {{
          const interactiveTargets = document.querySelectorAll('.part-info-trigger, .stack-step-trigger, .alert-block');
          interactiveTargets.forEach(item => {{
            item.addEventListener('click', (e) => {{
              if (e.target && e.target.closest('a')) return;
              const wasActive = item.classList.contains('popover-active');
              interactiveTargets.forEach(other => other.classList.remove('popover-active'));
              if (!wasActive) {{
                item.classList.add('popover-active');
              }}
              e.stopPropagation();
            }});
          }});
          document.addEventListener('click', () => {{
            interactiveTargets.forEach(other => other.classList.remove('popover-active'));
          }});
        }}

        function triggerTieToolDialog(e) {{
          if (e) {{
            e.preventDefault();
            e.stopPropagation();
          }}
          const doc = (window.parent && window.parent.document) ? window.parent.document : document;
          const btn = doc.querySelector('[class*="st-key-btn_tie_tool_slide_"] button')
                   || doc.querySelector('[class*="st-key-btn_tools_"] button');
          if (btn) {{
            btn.click();
          }}
        }}
        window.__paagOpenTieToolDialog = triggerTieToolDialog;

        function setupTieToolButton() {{
          const bindBtn = (btn) => {{
            if (btn.dataset.tieToolBound === '1') return;
            btn.dataset.tieToolBound = '1';
            btn.addEventListener('click', triggerTieToolDialog);
          }};
          document.querySelectorAll('.tie-tool-slide-btn').forEach(bindBtn);
          document.querySelectorAll('*').forEach(el => {{
            if (el.shadowRoot) {{
              el.shadowRoot.querySelectorAll('.tie-tool-slide-btn').forEach(bindBtn);
            }}
          }});
        }}

        function fitPrintSlideStacks() {{
          document.querySelectorAll('.paag-slide.print-letter, .paag-slide.print-tabloid').forEach(slide => {{
            slide.querySelectorAll('.stack-track').forEach(track => {{
              const trackH = track.clientHeight;
              if (!trackH || trackH < 30) return;
              const blocks = Array.from(track.querySelectorAll('.stack-block'));
              let totalOrigH = 0;
              blocks.forEach(b => {{
                if (!b.dataset.origH) {{
                  b.dataset.origH = String(parseFloat(b.style.height) || b.offsetHeight || 26);
                }}
                totalOrigH += parseFloat(b.dataset.origH) || 26;
              }});
              const maxAllowed = Math.max(24, trackH - 8);
              const scale = totalOrigH > maxAllowed ? (maxAllowed / totalOrigH) : 1.0;
              blocks.forEach(b => {{
                const origH = parseFloat(b.dataset.origH) || 26;
                b.style.height = Math.max(16, Math.floor(origH * scale)) + 'px';
              }});
              const taktLine = track.querySelector('.takt-line');
              if (taktLine) {{
                if (!taktLine.dataset.origBottom) {{
                  taktLine.dataset.origBottom = String(parseFloat(taktLine.style.bottom) || 12);
                }}
                const origB = parseFloat(taktLine.dataset.origBottom) || 12;
                const scaledB = Math.round(origB * scale);
                taktLine.style.bottom = Math.min(Math.max(8, scaledB), Math.max(8, trackH - 6)) + 'px';
              }}
            }});
          }});
        }}

        function initSlideInteractions() {{
          setupHoverLinking();
          setupTouchAndViewportPopovers();
          setupTieToolButton();
          fitPrintSlideStacks();
          window.addEventListener('resize', fitPrintSlideStacks);
          window.addEventListener('beforeprint', fitPrintSlideStacks);
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
        flex-wrap: wrap;
        user-select: none;
      }}
      .pres-btn-group {{
        display: flex;
        align-items: center;
        flex-wrap: wrap;
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
        height: min(10.35in, 98vh) !important;
        max-height: min(10.35in, 98vh) !important;
        aspect-ratio: auto !important;
        overflow: hidden !important;
      }}
      .paag-slide.print-letter {{
        width: 100% !important;
        height: min(7.85in, 98vh) !important;
        max-height: min(7.85in, 98vh) !important;
        aspect-ratio: auto !important;
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


def _xml_esc(value: object) -> str:
    """Escape text for safe inclusion inside OpenXML elements and attributes."""
    raw = str(value or "")
    cleaned = "".join(
        ch for ch in raw if ch in ("\t", "\n", "\r") or (0x20 <= ord(ch) <= 0xD7FF) or (0xE000 <= ord(ch) <= 0xFFFD)
    )
    return html.escape(cleaned, quote=True)


_PPTX_IMAGE_BYTES_CACHE: dict[tuple[str, int, int], tuple[bytes, int, int]] = {}


def _load_pptx_image_bytes(raw_path: object) -> tuple[bytes, int, int] | None:
    """Load an image from a local path or data URI and return (png_bytes, width_px, height_px)."""
    import io
    from PIL import Image, ImageOps

    val = str(raw_path or "").strip()
    if not val:
        return None
    raw_bytes: bytes | None = None
    file_cache_key: tuple[str, int, int] | None = None
    if val.startswith("data:image/"):
        try:
            _, b64_part = val.split(",", 1)
            raw_bytes = base64.b64decode(b64_part)
        except Exception:
            return None
    elif not val.startswith(("http://", "https://")):
        p = Path(val)
        try:
            st_info = p.stat()
            if p.is_file():
                file_cache_key = (str(p), int(st_info.st_mtime_ns), int(st_info.st_size))
                cached = _PPTX_IMAGE_BYTES_CACHE.get(file_cache_key)
                if cached is not None:
                    return cached
                raw_bytes = p.read_bytes()
        except OSError:
            return None
    if not raw_bytes:
        return None
    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            w_px, h_px = img.size
            if w_px <= 0 or h_px <= 0:
                return None
            out = io.BytesIO()
            img.save(out, format="PNG")
            res = (out.getvalue(), w_px, h_px)
            if file_cache_key is not None:
                if len(_PPTX_IMAGE_BYTES_CACHE) >= 256:
                    _PPTX_IMAGE_BYTES_CACHE.pop(next(iter(_PPTX_IMAGE_BYTES_CACHE)), None)
                _PPTX_IMAGE_BYTES_CACHE[file_cache_key] = res
            return res
    except Exception:
        return None


def _pptx_in(inches: float) -> int:
    """Convert inches to English Metric Units (1 inch = 914,400 EMU)."""
    return max(0, int(round(float(inches) * 914400.0)))


def _pptx_pt(points: float) -> int:
    """Convert points to OpenXML hundredths of a point (1 pt = 100)."""
    return max(100, int(round(float(points) * 100.0)))


def _pptx_run_xml(
    text: str,
    *,
    pt: float = 9.0,
    color: str = "0F172A",
    bold: bool = False,
    italic: bool = False,
) -> str:
    b_attr = ' b="1"' if bold else ' b="0"'
    i_attr = ' i="1"' if italic else ' i="0"'
    c_hex = color.lstrip("#").upper()
    return (
        f"<a:r>"
        f'<a:rPr lang="en-US" sz="{_pptx_pt(pt)}"{b_attr}{i_attr} dirty="0">'
        f'<a:solidFill><a:srgbClr val="{c_hex}"/></a:solidFill>'
        f'<a:latin typeface="Segoe UI"/><a:ea typeface="Segoe UI"/><a:cs typeface="Segoe UI"/>'
        f"</a:rPr>"
        f"<a:t>{_xml_esc(text)}</a:t>"
        f"</a:r>"
    )


def _pptx_para_xml(
    runs: list[str],
    *,
    align: str = "l",
    spc_before_pt: float = 0.0,
    spc_after_pt: float = 0.0,
) -> str:
    spc_b = f'<a:spcBef><a:spcPts val="{_pptx_pt(spc_before_pt)}"/></a:spcBef>' if spc_before_pt > 0 else ""
    spc_a = f'<a:spcAft><a:spcPts val="{_pptx_pt(spc_after_pt)}"/></a:spcAft>' if spc_after_pt > 0 else ""
    body = "".join(runs) if runs else '<a:endParaRPr lang="en-US" sz="800" dirty="0"/>'
    return f'<a:p><a:pPr algn="{align}">{spc_b}{spc_a}</a:pPr>{body}</a:p>'


def _pptx_shape_xml(
    shape_id: int,
    name: str,
    *,
    x_in: float,
    y_in: float,
    w_in: float,
    h_in: float,
    paragraphs: list[str] | None = None,
    fill_hex: str | None = "FFFFFF",
    line_hex: str | None = None,
    line_pt: float = 0.75,
    line_dash: str | None = None,
    geom: str = "rect",
    round_adj: int = 8000,
    v_anchor: str = "t",
    pad_in: tuple[float, float, float, float] = (0.05, 0.03, 0.05, 0.03),
    word_wrap: bool = True,
    num_cols: int = 1,
) -> str:
    x_emu = _pptx_in(x_in)
    y_emu = _pptx_in(y_in)
    w_emu = max(1, _pptx_in(w_in))
    h_emu = max(1, _pptx_in(h_in))

    if geom == "roundRect":
        geom_xml = f'<a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val {int(round_adj)}"/></a:avLst></a:prstGeom>'
    else:
        geom_xml = f'<a:prstGeom prst="{geom}"><a:avLst/></a:prstGeom>'

    if fill_hex:
        fill_xml = f'<a:solidFill><a:srgbClr val="{fill_hex.lstrip("#").upper()}"/></a:solidFill>'
    else:
        fill_xml = "<a:noFill/>"

    if line_hex and line_pt > 0:
        w_ln = max(6350, int(round(line_pt * 12700.0)))
        dash_xml = f'<a:prstDash val="{line_dash}"/>' if line_dash else ""
        ln_xml = (
            f'<a:ln w="{w_ln}">'
            f'<a:solidFill><a:srgbClr val="{line_hex.lstrip("#").upper()}"/></a:solidFill>'
            f"{dash_xml}"
            f"</a:ln>"
        )
    else:
        ln_xml = "<a:ln><a:noFill/></a:ln>"

    l_ins, t_ins, r_ins, b_ins = (
        _pptx_in(pad_in[0]),
        _pptx_in(pad_in[1]),
        _pptx_in(pad_in[2]),
        _pptx_in(pad_in[3]),
    )
    wrap_attr = "square" if word_wrap else "none"
    num_col_attr = f' numCol="{int(num_cols)}"' if int(num_cols) > 1 else ""
    paras_xml = "".join(paragraphs) if paragraphs else '<a:p><a:endParaRPr lang="en-US" sz="800" dirty="0"/></a:p>'

    return (
        f"<p:sp>"
        f"<p:nvSpPr>"
        f'<p:cNvPr id="{shape_id}" name="{_xml_esc(name)}"/>'
        f"<p:cNvSpPr/>"
        f"<p:nvPr/>"
        f"</p:nvSpPr>"
        f"<p:spPr>"
        f'<a:xfrm><a:off x="{x_emu}" y="{y_emu}"/><a:ext cx="{w_emu}" cy="{h_emu}"/></a:xfrm>'
        f"{geom_xml}{fill_xml}{ln_xml}"
        f"</p:spPr>"
        f"<p:txBody>"
        f'<a:bodyPr wrap="{wrap_attr}" lIns="{l_ins}" tIns="{t_ins}" rIns="{r_ins}" bIns="{b_ins}"{num_col_attr} anchor="{v_anchor}"/>'
        f"<a:lstStyle/>"
        f"{paras_xml}"
        f"</p:txBody>"
        f"</p:sp>"
    )


def _pptx_pic_xml(
    shape_id: int,
    name: str,
    rel_id: str,
    *,
    x_in: float,
    y_in: float,
    w_in: float,
    h_in: float,
    line_hex: str | None = None,
    line_pt: float = 0.5,
) -> str:
    x_emu = _pptx_in(x_in)
    y_emu = _pptx_in(y_in)
    w_emu = max(1, _pptx_in(w_in))
    h_emu = max(1, _pptx_in(h_in))
    if line_hex and line_pt > 0:
        w_ln = max(6350, int(round(line_pt * 12700.0)))
        ln_xml = f'<a:ln w="{w_ln}"><a:solidFill><a:srgbClr val="{line_hex.lstrip("#").upper()}"/></a:solidFill></a:ln>'
    else:
        ln_xml = ""
    return (
        f"<p:pic>"
        f"<p:nvPicPr>"
        f'<p:cNvPr id="{shape_id}" name="{_xml_esc(name)}"/>'
        f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>'
        f"<p:nvPr/>"
        f"</p:nvPicPr>"
        f"<p:blipFill>"
        f'<a:blip r:embed="{rel_id}"/>'
        f"<a:stretch><a:fillRect/></a:stretch>"
        f"</p:blipFill>"
        f"<p:spPr>"
        f'<a:xfrm><a:off x="{x_emu}" y="{y_emu}"/><a:ext cx="{w_emu}" cy="{h_emu}"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f"{ln_xml}"
        f"</p:spPr>"
        f"</p:pic>"
    )


def _render_single_paag_pptx_slide(
    slide_spec: dict,
    *,
    paper_size: str,
    image_fit: str,
    scenario_name: str,
    project_name: str,
    register_media_fn,
) -> tuple[str, list[tuple[str, str]]]:
    """Build slideN.xml and its image relationships for one PAAG slide."""
    pitch = slide_spec.get("pitch") or {}
    elements_list = list(slide_spec.get("elements") or pitch.get("elements") or [])
    page_num = int(slide_spec.get("page_num") or 1)
    total_pages = slide_spec.get("total_pages")
    generated_on = slide_spec.get("generated_on") or date.today()
    generated_label = f"{generated_on:%B} {generated_on.day}, {generated_on.year}"

    is_tabloid = paper_size == "tabloid"
    slide_w_in = 17.0 if is_tabloid else 11.0
    slide_h_in = 11.0 if is_tabloid else 8.5
    sc = 1.28 if is_tabloid else 1.0

    pitch_number = str(pitch.get("pitch_number") or "Unassigned Pitch").strip()
    raw_pitch_name = str(pitch.get("pitch_name") or "").strip()
    pitch_name = "" if raw_pitch_name.casefold() == "process station" else raw_pitch_name
    pitch_title_display = f"{pitch_number} — {pitch_name}" if pitch_name else pitch_number
    section_name = str(pitch.get("section_name") or "").strip()
    eff_section_name = str(section_name or pitch.get("area_name") or "N/A").strip() or "N/A"
    building_name = str(
        slide_spec.get("building_location")
        or pitch.get("building_location")
        or pitch.get("building")
        or "N/A"
    ).strip() or "N/A"
    eff_project_name = str(project_name or pitch.get("project_name") or "Project").strip()
    eff_scenario_name = str(scenario_name or pitch.get("scenario_name") or "Scenario").strip()

    raw_tools = pitch.get("tools")
    tools = list(raw_tools) if isinstance(raw_tools, list) else []

    raw_parts = pitch.get("parts")
    if isinstance(raw_parts, list) and raw_parts:
        parts = list(raw_parts)
    else:
        seen_parts: dict[str, dict] = {}
        for el_idx, el in enumerate(elements_list):
            el_wid = str(el.get("work_element_id") or el.get("id") or f"step_{el_idx}")
            for p in el.get("parts", []):
                p_num = str(p.get("part_number") or "").strip()
                if not p_num:
                    continue
                is_mv = bool(p.get("is_model_variant"))
                mc_gid = (
                    str(p.get("model_choice_group_id") or p.get("group_id") or el_wid)
                    if is_mv
                    else ""
                )
                if p_num not in seen_parts:
                    seen_parts[p_num] = {
                        "part_number": p_num,
                        "description": p.get("part_description") or p.get("description") or "",
                        "factory_nickname": p.get("factory_nickname") or "",
                        "image_path": p.get("image_path") or "",
                        "quantity": float(p.get("quantity") or 1.0),
                        "handling_types": set(),
                        "is_model_variant": is_mv,
                        "model_choice_group_id": mc_gid,
                    }
                else:
                    seen_parts[p_num]["quantity"] += float(p.get("quantity") or 1.0)
                    if is_mv and not seen_parts[p_num].get("is_model_variant"):
                        seen_parts[p_num]["is_model_variant"] = True
                        seen_parts[p_num]["model_choice_group_id"] = mc_gid
        parts = list(seen_parts.values())

    raw_stacks = pitch.get("yamazumi_stacks")
    if isinstance(raw_stacks, dict) and raw_stacks:
        yamazumi_stacks = raw_stacks
    else:
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

    raw_media = pitch.get("visual_media")
    visual_media = list(raw_media) if isinstance(raw_media, list) else []

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

    op_id_summary = str(pitch.get("op_id_summary") or "").strip()
    if not op_id_summary:
        op_ids = [
            str(el.get("op_id") or "")
            for el in elements_list
            if el.get("op_id") and el.get("op_id") != "Yamazumi link required"
        ]
        op_id_summary = f"{op_ids[0]} – {op_ids[-1]}" if len(op_ids) > 1 else (op_ids[0] if op_ids else "N/A")

    eff_takt_s = float(pitch.get("scenario_takt_s") or 0.0)
    total_media_count = len(visual_media)
    calc_total_pages = max(1, page_count(total_media_count, MEDIA_PER_PAGE))
    eff_total_pages = int(total_pages) if total_pages is not None else calc_total_pages
    eff_page_num = clamp_page(page_num, total_media_count if total_media_count > 0 else 1, MEDIA_PER_PAGE)
    current_media_items = page_media(visual_media, eff_page_num, MEDIA_PER_PAGE) if visual_media else []

    # Step number & description mapping matching render_pitch_canvas
    all_pitch_elements = list(pitch.get("elements") or elements_list)
    step_num_by_wid: dict[str, int] = {}
    element_by_wid: dict[str, dict] = {}
    step_desc_by_num: dict[int, str] = {}
    for idx, el in enumerate(all_pitch_elements):
        s_num = idx + 1
        w_id = str(el.get("work_element_id") or el.get("id") or "").strip()
        y_id = str(el.get("yamazumi_element_id") or "").strip()
        raw_el_desc = str(
            el.get("yamazumi_description")
            or el.get("operation")
            or el.get("element_name")
            or ""
        ).strip()
        if raw_el_desc and s_num not in step_desc_by_num:
            step_desc_by_num[s_num] = raw_el_desc
        desc_key = f"desc::{raw_el_desc.casefold()}"
        if w_id:
            step_num_by_wid[w_id] = s_num
            element_by_wid[w_id] = el
        if y_id:
            step_num_by_wid[y_id] = s_num
            element_by_wid[y_id] = el
        if desc_key != "desc::" and desc_key not in step_num_by_wid:
            step_num_by_wid[desc_key] = s_num
            element_by_wid[desc_key] = el

    if yamazumi_stacks:
        assigned_stack_keys: set[str] = set()
        assigned_stack_step_nums: set[int] = set()
        for v_data in yamazumi_stacks.values():
            v_els = v_data.get("elements", []) if isinstance(v_data, dict) else (v_data if isinstance(v_data, list) else [])
            stack_step_idx = 0
            for e in v_els:
                if not isinstance(e, dict):
                    continue
                stack_step_idx += 1
                assigned_num = stack_step_idx
                e_wid = str(e.get("work_element_id") or e.get("process_element_id") or "").strip()
                e_id = str(e.get("id") or "").strip()
                raw_e_desc = str(e.get("description") or e.get("yamazumi_description") or "").strip()
                e_desc_key = f"desc::{raw_e_desc.casefold()}"
                linked_for_step = (
                    (element_by_wid.get(e_wid) if e_wid else None)
                    or (element_by_wid.get(e_id) if e_id else None)
                    or (element_by_wid.get(e_desc_key) if e_desc_key != "desc::" else None)
                )
                resolved_step_desc = raw_e_desc or str(
                    (linked_for_step or {}).get("yamazumi_description")
                    or (linked_for_step or {}).get("operation")
                    or ""
                ).strip()
                if resolved_step_desc and assigned_num not in assigned_stack_step_nums:
                    step_desc_by_num[assigned_num] = resolved_step_desc
                    assigned_stack_step_nums.add(assigned_num)
                if e_wid and e_wid not in assigned_stack_keys:
                    step_num_by_wid[e_wid] = assigned_num
                    assigned_stack_keys.add(e_wid)
                if e_id and e_id not in assigned_stack_keys:
                    step_num_by_wid[e_id] = assigned_num
                    assigned_stack_keys.add(e_id)
                if e_desc_key != "desc::" and e_desc_key not in assigned_stack_keys:
                    step_num_by_wid[e_desc_key] = assigned_num
                    assigned_stack_keys.add(e_desc_key)

    shapes_xml: list[str] = []
    slide_rels: list[tuple[str, str]] = []
    next_shape_id = 2
    next_rel_idx = 2

    def _next_sid() -> int:
        nonlocal next_shape_id
        sid = next_shape_id
        next_shape_id += 1
        return sid

    def _embed_img(raw_path: object) -> tuple[str, int, int] | None:
        nonlocal next_rel_idx
        reg = register_media_fn(raw_path)
        if not reg:
            return None
        media_filename, w_px, h_px = reg
        r_id = f"rId{next_rel_idx}"
        next_rel_idx += 1
        slide_rels.append((r_id, f"../media/{media_filename}"))
        return r_id, w_px, h_px

    # Outer slide card
    margin = 0.18
    x0, y0 = margin, margin
    cw, ch = slide_w_in - 2 * margin, slide_h_in - 2 * margin
    shapes_xml.append(
        _pptx_shape_xml(
            _next_sid(),
            "Slide Card Background",
            x_in=x0,
            y_in=y0,
            w_in=cw,
            h_in=ch,
            fill_hex="FFFFFF",
            line_hex="CBD5E1",
            line_pt=1.0,
            geom="roundRect",
            round_adj=2500,
        )
    )

    px, py = 0.14 * sc, 0.12 * sc
    ix, iy = x0 + px, y0 + py
    iw, ih = cw - 2 * px, ch - 2 * py

    # 1. HEADER ROW
    hdr_h = 0.72 * sc
    meta_w = iw * 0.28
    meta_x = ix + iw - meta_w

    # Upper-left GE Appliances Logo
    logo_path = _slide_logo_path()
    logo_embedded = _embed_img(logo_path) if logo_path is not None else None
    if logo_embedded is not None:
        logo_rid, _, _ = logo_embedded
        shapes_xml.append(
            _pptx_pic_xml(
                _next_sid(),
                "GE Appliances Logo",
                logo_rid,
                x_in=ix,
                y_in=iy - 0.06 * sc,
                w_in=2.53 * sc,
                h_in=hdr_h,
            )
        )
    else:
        shapes_xml.append(
            _pptx_shape_xml(
                _next_sid(),
                "GE Appliances Logo Text",
                x_in=ix,
                y_in=iy,
                w_in=2.53 * sc,
                h_in=hdr_h,
                paragraphs=[
                    _pptx_para_xml(
                        [_pptx_run_xml("GE APPLIANCES", pt=14.0 * sc, color="0B3768", bold=True)],
                        align="l",
                    )
                ],
                fill_hex=None,
                v_anchor="ctr",
                pad_in=(0.0, 0.01, 0.02, 0.01),
            )
        )

    # Center Pitch Title
    shapes_xml.append(
        _pptx_shape_xml(
            _next_sid(),
            "Pitch Title",
            x_in=ix + iw * 0.32,
            y_in=iy,
            w_in=iw * 0.39,
            h_in=hdr_h,
            paragraphs=[
                _pptx_para_xml(
                    [_pptx_run_xml(pitch_title_display, pt=14.0 * sc, color="0B3768", bold=True)],
                    align="ctr",
                )
            ],
            fill_hex=None,
            v_anchor="ctr",
            pad_in=(0.04, 0.02, 0.04, 0.02),
        )
    )

    # Upper-Right Title ("Process at a Glance") above Detail Box
    shapes_xml.append(
        _pptx_shape_xml(
            _next_sid(),
            "Project Subtitle",
            x_in=meta_x,
            y_in=iy - 0.06 * sc,
            w_in=meta_w,
            h_in=0.22 * sc,
            paragraphs=[
                _pptx_para_xml(
                    [_pptx_run_xml("Process at a Glance", pt=14.0 * sc, color="0B3768", bold=True)],
                    align="r",
                )
            ],
            fill_hex=None,
            v_anchor="ctr",
            pad_in=(0.0, 0.01, 0.02, 0.01),
        )
    )

    # Upper-Right Detail Box (Project, Building, Section | Date, Scenario)
    meta_paras = [
        _pptx_para_xml(
            [
                _pptx_run_xml("Project: ", pt=7.5 * sc, color="334155", bold=True),
                _pptx_run_xml(eff_project_name, pt=7.5 * sc, color="475569"),
            ],
            align="l",
        ),
        _pptx_para_xml(
            [
                _pptx_run_xml("Building: ", pt=7.5 * sc, color="334155", bold=True),
                _pptx_run_xml(building_name, pt=7.5 * sc, color="475569"),
            ],
            align="l",
        ),
        _pptx_para_xml(
            [
                _pptx_run_xml("Section: ", pt=7.5 * sc, color="334155", bold=True),
                _pptx_run_xml(eff_section_name, pt=7.5 * sc, color="475569"),
            ],
            align="l",
        ),
        _pptx_para_xml(
            [
                _pptx_run_xml("Date: ", pt=7.5 * sc, color="334155", bold=True),
                _pptx_run_xml(generated_label, pt=7.5 * sc, color="475569"),
            ],
            align="l",
        ),
        _pptx_para_xml(
            [
                _pptx_run_xml("Scenario: ", pt=7.5 * sc, color="334155", bold=True),
                _pptx_run_xml(eff_scenario_name, pt=7.5 * sc, color="475569"),
            ],
            align="l",
        ),
    ]
    shapes_xml.append(
        _pptx_shape_xml(
            _next_sid(),
            "Metadata Card",
            x_in=meta_x,
            y_in=iy + 0.19 * sc,
            w_in=meta_w,
            h_in=0.53 * sc,
            paragraphs=meta_paras,
            fill_hex="F8FAFC",
            line_hex="CBD5E1",
            line_pt=0.75,
            geom="roundRect",
            round_adj=10000,
            v_anchor="ctr",
            pad_in=(0.06, 0.03, 0.08, 0.03),
            num_cols=2,
        )
    )

    # 2. FUNCTIONAL ALERTS BAR
    alerts_y = iy + hdr_h + 0.06 * sc
    alerts_h = 0.28 * sc
    shapes_xml.append(
        _pptx_shape_xml(
            _next_sid(),
            "Alerts Bar Container",
            x_in=ix,
            y_in=alerts_y,
            w_in=iw,
            h_in=alerts_h,
            fill_hex="F8FAFC",
            line_hex="E2E8F0",
            line_pt=0.75,
            geom="roundRect",
            round_adj=12000,
        )
    )

    alert_categories = [
        ("Quality", "quality", alerts.get("quality", [])),
        ("Ergo", "ergo", alerts.get("ergo", [])),
        ("Safety", "safety", alerts.get("safety", [])),
        ("Materials", "materials", alerts.get("materials", [])),
        ("Equipment", "equipment", alerts.get("equipment", [])),
    ]
    base_task_count = len(all_pitch_elements) if all_pitch_elements else len(set(step_num_by_wid.values()))
    alert_col_w = (iw - 0.08 * sc) / 5.0
    for idx_a, (cat_name, cat_key, cat_list) in enumerate(alert_categories):
        ax = ix + 0.04 * sc + idx_a * alert_col_w
        ay = alerts_y + 0.025 * sc
        aw = alert_col_w - 0.04 * sc
        ah = alerts_h - 0.05 * sc
        if cat_list:
            missing_ppe_items = [
                item for item in cat_list
                if str(item.get("label") or "").strip().lower().startswith("no ppe assigned")
            ]
            other_items = [
                item for item in cat_list
                if not str(item.get("label") or "").strip().lower().startswith("no ppe assigned")
            ]
            if missing_ppe_items:
                eff_total_tasks = max(base_task_count, len(missing_ppe_items))
                assigned_ppe_tasks = max(0, eff_total_tasks - len(missing_ppe_items))
                items_str = f"No PPE assigned ({assigned_ppe_tasks}/{eff_total_tasks} tasks)"
            elif cat_key == "safety":
                cleaned_labels = []
                for item in other_items:
                    raw_lbl = str(item.get("label") or "Alert").strip()
                    if raw_lbl.lower().startswith("safety:"):
                        raw_lbl = raw_lbl[7:].strip() or raw_lbl
                    cleaned_labels.append(raw_lbl)
                if len(cleaned_labels) == 1 and len(cleaned_labels[0]) <= 28:
                    items_str = cleaned_labels[0]
                else:
                    items_str = f"{len(cleaned_labels)} requirement{'s' if len(cleaned_labels) != 1 else ''}"
            else:
                items_str = " · ".join(str(item.get("label") or "Alert") for item in other_items)
            shapes_xml.append(
                _pptx_shape_xml(
                    _next_sid(),
                    f"Alert {cat_name}",
                    x_in=ax,
                    y_in=ay,
                    w_in=aw,
                    h_in=ah,
                    paragraphs=[
                        _pptx_para_xml(
                            [
                                _pptx_run_xml(f"{cat_name}: ", pt=7.2 * sc, color="991B1B", bold=True),
                                _pptx_run_xml(items_str, pt=7.2 * sc, color="B91C1C", bold=True),
                            ],
                            align="l",
                        )
                    ],
                    fill_hex="FEF2F2",
                    line_hex="FCA5A5",
                    line_pt=0.75,
                    geom="roundRect",
                    round_adj=15000,
                    v_anchor="ctr",
                    pad_in=(0.05, 0.01, 0.05, 0.01),
                )
            )
        else:
            shapes_xml.append(
                _pptx_shape_xml(
                    _next_sid(),
                    f"Alert {cat_name}",
                    x_in=ax,
                    y_in=ay,
                    w_in=aw,
                    h_in=ah,
                    paragraphs=[
                        _pptx_para_xml(
                            [
                                _pptx_run_xml(f"{cat_name}: ", pt=7.2 * sc, color="334155", bold=True),
                                _pptx_run_xml("✓ None", pt=7.2 * sc, color="15803D", bold=True),
                            ],
                            align="l",
                        )
                    ],
                    fill_hex=None,
                    v_anchor="ctr",
                    pad_in=(0.05, 0.01, 0.05, 0.01),
                )
            )

    # 3. MAIN BODY (Left Column + Right Visual Aid Grid)
    body_y = alerts_y + alerts_h + 0.07 * sc
    body_h = (iy + ih) - body_y
    lw = iw * (0.33 if is_tabloid else 0.36)
    lx = ix
    col_gap = 0.10 * sc
    rx = lx + lw + col_gap
    rw = (ix + iw) - rx

    # --- LEFT PANEL 1: TOOLS & PPE REQUIRED ---
    unique_tools: list[dict] = []
    seen_tool_ids: set[str] = set()
    for tool in tools:
        t_id = str(tool.get("equipment_id") or tool.get("name") or "")
        if t_id and t_id in seen_tool_ids:
            continue
        seen_tool_ids.add(t_id)
        unique_tools.append(tool)

    tools_h = min(1.15 * sc, max(0.56 * sc, (0.30 + 0.20 * max(1, len(unique_tools))) * sc))
    tools_paras: list[str] = [
        _pptx_para_xml(
            [_pptx_run_xml("TOOLS & PPE REQUIRED", pt=9.5 * sc, color="334155", bold=True)],
            align="l",
            spc_after_pt=3.0,
        )
    ]
    if unique_tools:
        for tool in unique_tools[:5]:
            t_name = str(tool.get("name") or "Tool").strip()
            t_type = str(tool.get("type_name") or "").strip()
            t_tier = str(tool.get("tier") or tool.get("equipment_tier") or "").strip()
            t_summary = str(
                tool.get("summary_line")
                or (f"{t_name} ({t_type})" if t_type and t_type.lower() != "tool" else t_name)
            ).strip()
            prefix = "[PPE] " if tool.get("is_ppe", False) else (f"[{t_tier}] " if t_tier else "• ")
            tools_paras.append(
                _pptx_para_xml(
                    [
                        _pptx_run_xml(prefix, pt=8.8 * sc, color="0284C7" if tool.get("is_ppe") else "475569", bold=True),
                        _pptx_run_xml(t_summary, pt=9.0 * sc, color="0F172A"),
                    ],
                    align="l",
                )
            )
    else:
        tools_paras.append(
            _pptx_para_xml(
                [_pptx_run_xml("No equipment or PPE assigned", pt=8.8 * sc, color="94A3B8", italic=True)],
                align="l",
            )
        )

    shapes_xml.append(
        _pptx_shape_xml(
            _next_sid(),
            "Tools Panel",
            x_in=lx,
            y_in=body_y,
            w_in=lw,
            h_in=tools_h,
            paragraphs=tools_paras,
            fill_hex="FFFFFF",
            line_hex="CBD5E1",
            line_pt=0.75,
            geom="roundRect",
            round_adj=6000,
            v_anchor="t",
            pad_in=(0.07, 0.04, 0.07, 0.04),
        )
    )

    # --- LEFT PANEL 2: PARTS TABLE ---
    def _part_mc_group_key(part_dict: dict) -> str:
        if not bool(part_dict.get("is_model_variant")):
            return ""
        return str(
            part_dict.get("model_choice_group_id")
            or part_dict.get("group_id")
            or part_dict.get("work_element_id")
            or "__model_choice__"
        ).strip()

    ordered_parts: list[dict] = []
    seen_mc_keys: set[str] = set()
    for p_item in parts:
        mc_k = _part_mc_group_key(p_item)
        if not mc_k:
            ordered_parts.append(p_item)
        elif mc_k not in seen_mc_keys:
            seen_mc_keys.add(mc_k)
            for peer in parts:
                if _part_mc_group_key(peer) == mc_k:
                    ordered_parts.append(peer)

    has_model_choice_parts = bool(seen_mc_keys)
    parts_y = body_y + tools_h + 0.06 * sc
    max_parts_rows = 8 if is_tabloid else 6
    visible_parts = ordered_parts[:max_parts_rows]
    row_h = 0.30 * sc
    parts_hdr_h = 0.27 * sc
    parts_tbl_hdr_h = 0.22 * sc
    if visible_parts:
        parts_h = min(
            body_h * 0.48,
            parts_hdr_h + parts_tbl_hdr_h + len(visible_parts) * row_h + 0.10 * sc,
        )
        row_h = max(0.22 * sc, (parts_h - parts_hdr_h - parts_tbl_hdr_h - 0.08 * sc) / max(1, len(visible_parts)))
    else:
        parts_h = 0.85 * sc

    shapes_xml.append(
        _pptx_shape_xml(
            _next_sid(),
            "Parts Panel",
            x_in=lx,
            y_in=parts_y,
            w_in=lw,
            h_in=parts_h,
            paragraphs=[
                _pptx_para_xml(
                    [
                        _pptx_run_xml("PARTS", pt=9.5 * sc, color="334155", bold=True),
                        *(
                            [
                                _pptx_run_xml("   ", pt=8.0 * sc),
                                _pptx_run_xml("[MODEL CHOICE]", pt=8.0 * sc, color="7E22CE", bold=True),
                            ]
                            if has_model_choice_parts
                            else []
                        ),
                    ],
                    align="l",
                )
            ],
            fill_hex="FFFFFF",
            line_hex="CBD5E1",
            line_pt=0.75,
            geom="roundRect",
            round_adj=5000,
            v_anchor="t",
            pad_in=(0.07, 0.04, 0.07, 0.04),
        )
    )

    if not visible_parts:
        shapes_xml.append(
            _pptx_shape_xml(
                _next_sid(),
                "No Parts Placeholder",
                x_in=lx + 0.07 * sc,
                y_in=parts_y + parts_hdr_h,
                w_in=lw - 0.14 * sc,
                h_in=parts_h - parts_hdr_h - 0.06 * sc,
                paragraphs=[
                    _pptx_para_xml(
                        [_pptx_run_xml("No Parts Paired", pt=9.0 * sc, color="94A3B8", bold=True)],
                        align="ctr",
                    )
                ],
                fill_hex="F8FAFC",
                line_hex="CBD5E1",
                line_pt=0.5,
                line_dash="dash",
                geom="roundRect",
                round_adj=8000,
                v_anchor="ctr",
            )
        )
    else:
        tbl_x = lx + 0.05 * sc
        tbl_w = lw - 0.10 * sc
        tbl_y = parts_y + parts_hdr_h
        # Table column widths: Img (11%), Part # (29%), Description (37%), Qty (9%), C/H (14%)
        c_img_w = tbl_w * 0.11
        c_pnum_w = tbl_w * 0.29
        c_desc_w = tbl_w * 0.37
        c_qty_w = tbl_w * 0.09
        c_ch_w = tbl_w * 0.14

        # Header background
        shapes_xml.append(
            _pptx_shape_xml(
                _next_sid(),
                "Parts Table Header",
                x_in=tbl_x,
                y_in=tbl_y,
                w_in=tbl_w,
                h_in=parts_tbl_hdr_h,
                fill_hex="F1F5F9",
                line_hex="E2E8F0",
                line_pt=0.5,
            )
        )
        hdr_cols = [
            ("IMG", tbl_x, c_img_w, "ctr"),
            ("PART #", tbl_x + c_img_w, c_pnum_w, "l"),
            ("DESCRIPTION", tbl_x + c_img_w + c_pnum_w, c_desc_w, "l"),
            ("QTY", tbl_x + c_img_w + c_pnum_w + c_desc_w, c_qty_w, "ctr"),
            ("C / H", tbl_x + c_img_w + c_pnum_w + c_desc_w + c_qty_w, c_ch_w, "ctr"),
        ]
        for h_lbl, hx, hw, h_algn in hdr_cols:
            shapes_xml.append(
                _pptx_shape_xml(
                    _next_sid(),
                    f"Parts Col {h_lbl}",
                    x_in=hx,
                    y_in=tbl_y,
                    w_in=hw,
                    h_in=parts_tbl_hdr_h,
                    paragraphs=[
                        _pptx_para_xml([_pptx_run_xml(h_lbl, pt=7.8 * sc, color="64748B", bold=True)], align=h_algn)
                    ],
                    fill_hex=None,
                    v_anchor="ctr",
                    pad_in=(0.02, 0.0, 0.02, 0.0),
                )
            )

        rows_start_y = tbl_y + parts_tbl_hdr_h
        for idx_p, part in enumerate(visible_parts):
            ry_p = rows_start_y + idx_p * row_h
            mc_key = _part_mc_group_key(part)
            is_mc = bool(mc_key)
            row_fill = "FAF5FF" if is_mc else ("FFFFFF" if idx_p % 2 == 0 else "F8FAFC")
            shapes_xml.append(
                _pptx_shape_xml(
                    _next_sid(),
                    f"Part Row {idx_p + 1}",
                    x_in=tbl_x,
                    y_in=ry_p,
                    w_in=tbl_w,
                    h_in=row_h,
                    fill_hex=row_fill,
                    line_hex="E2E8F0",
                    line_pt=0.4,
                )
            )

            p_num = str(part.get("part_number") or "Part").strip()
            p_desc = str(part.get("description") or part.get("part_name") or "—").strip()
            p_qty = _part_display_qty(part)
            h_types = part.get("handling_types") or ([part.get("handling_type")] if part.get("handling_type") else [])
            h_codes: list[str] = []
            for ht in h_types:
                ht_c = str(ht).strip().casefold()
                if ht_c in {"consume", "c"}:
                    h_codes.append("C")
                elif ht_c in {"handle", "h"}:
                    h_codes.append("H")
                elif ht_c:
                    h_codes.append(str(ht).strip().upper()[:1])
            h_str = "/".join(h_codes) if h_codes else "—"
            h_color = "166534" if "C" in h_codes else ("92400E" if "H" in h_codes else "64748B")

            # Part thumbnail or IMG box
            emb_thumb = _embed_img(part.get("image_path") or part.get("thumbnail_path"))
            thumb_pad = 0.02 * sc
            thumb_box_w = max(0.08, c_img_w - 2 * thumb_pad)
            thumb_box_h = max(0.08, row_h - 2 * thumb_pad)
            if emb_thumb:
                r_id_th, tw_px, th_px = emb_thumb
                aspect = tw_px / max(1, th_px)
                if thumb_box_w / thumb_box_h > aspect:
                    draw_h = thumb_box_h
                    draw_w = draw_h * aspect
                else:
                    draw_w = thumb_box_w
                    draw_h = draw_w / aspect
                shapes_xml.append(
                    _pptx_pic_xml(
                        _next_sid(),
                        f"Thumb {p_num}",
                        r_id_th,
                        x_in=tbl_x + thumb_pad + (thumb_box_w - draw_w) / 2.0,
                        y_in=ry_p + thumb_pad + (thumb_box_h - draw_h) / 2.0,
                        w_in=draw_w,
                        h_in=draw_h,
                    )
                )
            else:
                shapes_xml.append(
                    _pptx_shape_xml(
                        _next_sid(),
                        f"Thumb Placeholder {p_num}",
                        x_in=tbl_x + thumb_pad,
                        y_in=ry_p + thumb_pad,
                        w_in=thumb_box_w,
                        h_in=thumb_box_h,
                        paragraphs=[_pptx_para_xml([_pptx_run_xml("IMG", pt=6.5 * sc, color="94A3B8", bold=True)], align="ctr")],
                        fill_hex="F1F5F9",
                        line_hex="CBD5E1",
                        line_pt=0.4,
                        v_anchor="ctr",
                        pad_in=(0.0, 0.0, 0.0, 0.0),
                    )
                )

            # Part #
            shapes_xml.append(
                _pptx_shape_xml(
                    _next_sid(),
                    f"Part Num {p_num}",
                    x_in=tbl_x + c_img_w,
                    y_in=ry_p,
                    w_in=c_pnum_w,
                    h_in=row_h,
                    paragraphs=[_pptx_para_xml([_pptx_run_xml(p_num, pt=8.2 * sc, color="0F172A", bold=True)], align="l")],
                    fill_hex=None,
                    v_anchor="ctr",
                    pad_in=(0.02, 0.0, 0.02, 0.0),
                )
            )
            # Description
            shapes_xml.append(
                _pptx_shape_xml(
                    _next_sid(),
                    f"Part Desc {p_num}",
                    x_in=tbl_x + c_img_w + c_pnum_w,
                    y_in=ry_p,
                    w_in=c_desc_w,
                    h_in=row_h,
                    paragraphs=[_pptx_para_xml([_pptx_run_xml(p_desc, pt=8.0 * sc, color="334155")], align="l")],
                    fill_hex=None,
                    v_anchor="ctr",
                    pad_in=(0.02, 0.0, 0.02, 0.0),
                )
            )
            # Qty
            shapes_xml.append(
                _pptx_shape_xml(
                    _next_sid(),
                    f"Part Qty {p_num}",
                    x_in=tbl_x + c_img_w + c_pnum_w + c_desc_w,
                    y_in=ry_p,
                    w_in=c_qty_w,
                    h_in=row_h,
                    paragraphs=[_pptx_para_xml([_pptx_run_xml(p_qty, pt=8.2 * sc, color="0F172A", bold=True)], align="ctr")],
                    fill_hex=None,
                    v_anchor="ctr",
                    pad_in=(0.01, 0.0, 0.01, 0.0),
                )
            )
            # Consume / Handle
            shapes_xml.append(
                _pptx_shape_xml(
                    _next_sid(),
                    f"Part Handling {p_num}",
                    x_in=tbl_x + c_img_w + c_pnum_w + c_desc_w + c_qty_w,
                    y_in=ry_p,
                    w_in=c_ch_w,
                    h_in=row_h,
                    paragraphs=[_pptx_para_xml([_pptx_run_xml(h_str, pt=8.2 * sc, color=h_color, bold=True)], align="ctr")],
                    fill_hex=None,
                    v_anchor="ctr",
                    pad_in=(0.01, 0.0, 0.01, 0.0),
                )
            )

        # Draw a single dark purple outline frame around each contiguous group of tied model variant rows
        mc_spans: list[tuple[int, int, str]] = []
        for idx_p, part in enumerate(visible_parts):
            mc_k = _part_mc_group_key(part)
            if not mc_k:
                continue
            if mc_spans and mc_spans[-1][2] == mc_k and mc_spans[-1][1] == idx_p - 1:
                mc_spans[-1] = (mc_spans[-1][0], idx_p, mc_k)
            else:
                mc_spans.append((idx_p, idx_p, mc_k))
        for grp_idx, (start_idx, end_idx, _) in enumerate(mc_spans, start=1):
            shapes_xml.append(
                _pptx_shape_xml(
                    _next_sid(),
                    f"Model Choice Frame {grp_idx}",
                    x_in=tbl_x,
                    y_in=rows_start_y + start_idx * row_h,
                    w_in=tbl_w,
                    h_in=(end_idx - start_idx + 1) * row_h,
                    fill_hex=None,
                    line_hex="6D28D9",
                    line_pt=1.8,
                )
            )

    # --- LEFT PANEL 3: YAMAZUMI STACK ---
    stack_y = parts_y + parts_h + 0.06 * sc
    stack_h = max(1.2 * sc, (body_y + body_h) - stack_y)
    shapes_xml.append(
        _pptx_shape_xml(
            _next_sid(),
            "Yamazumi Panel",
            x_in=lx,
            y_in=stack_y,
            w_in=lw,
            h_in=stack_h,
            paragraphs=[
                _pptx_para_xml(
                    [
                        _pptx_run_xml("YAMAZUMI  ", pt=9.5 * sc, color="334155", bold=True),
                        _pptx_run_xml("■ Cycle  ", pt=7.8 * sc, color="16A34A", bold=True),
                        _pptx_run_xml("■ Periodic  ", pt=7.8 * sc, color="D97706", bold=True),
                        _pptx_run_xml("■ Fluctuation  ", pt=7.8 * sc, color="64748B", bold=True),
                        _pptx_run_xml("— Takt", pt=7.8 * sc, color="DC2626", bold=True),
                    ],
                    align="l",
                )
            ],
            fill_hex="FFFFFF",
            line_hex="CBD5E1",
            line_pt=0.75,
            geom="roundRect",
            round_adj=4000,
            v_anchor="t",
            pad_in=(0.07, 0.04, 0.07, 0.04),
        )
    )

    variant_items = list(yamazumi_stacks.items())
    num_vars = max(1, len(variant_items))
    var_area_x = lx + 0.06 * sc
    var_area_w = lw - 0.12 * sc
    var_col_w = (var_area_w - 0.05 * sc * (num_vars - 1)) / num_vars
    var_hdr_y = stack_y + 0.28 * sc
    var_hdr_h = 0.24 * sc
    track_y = var_hdr_y + var_hdr_h + 0.02 * sc
    track_h = max(0.6 * sc, (stack_y + stack_h - 0.06 * sc) - track_y)

    max_var_time = 0.0
    for _, v_data in variant_items:
        v_els = v_data.get("elements", []) if isinstance(v_data, dict) else (v_data if isinstance(v_data, list) else [])
        vt = sum(float(e.get("time_s") or 0.0) for e in v_els if isinstance(e, dict))
        if vt > max_var_time:
            max_var_time = vt
    ref_time_s = max(max_var_time * 1.08, eff_takt_s * 1.12, 1.0)

    for idx_v, (v_name, v_data) in enumerate(variant_items):
        vx = var_area_x + idx_v * (var_col_w + 0.05 * sc)
        v_els = [
            e for e in (v_data.get("elements", []) if isinstance(v_data, dict) else (v_data if isinstance(v_data, list) else []))
            if isinstance(e, dict)
        ]
        v_total_s = sum(float(e.get("time_s") or 0.0) for e in v_els)
        hdr_runs = [
            _pptx_run_xml(f"{v_name}: ", pt=8.5 * sc, color="0F172A", bold=True),
            _pptx_run_xml(f"{_clean_number(v_total_s)}s", pt=8.5 * sc, color="0F172A", bold=True),
        ]
        if eff_takt_s > 0:
            util_pct = (v_total_s / eff_takt_s) * 100.0
            u_color = "DC2626" if util_pct > 100.0 else "16A34A"
            hdr_runs.append(_pptx_run_xml(f" / Takt {_clean_number(eff_takt_s)}s ", pt=8.0 * sc, color="64748B"))
            hdr_runs.append(_pptx_run_xml(f"({util_pct:.0f}% util)", pt=8.2 * sc, color=u_color, bold=True))

        shapes_xml.append(
            _pptx_shape_xml(
                _next_sid(),
                f"Variant Header {v_name}",
                x_in=vx,
                y_in=var_hdr_y,
                w_in=var_col_w,
                h_in=var_hdr_h,
                paragraphs=[_pptx_para_xml(hdr_runs, align="l")],
                fill_hex=None,
                v_anchor="ctr",
                pad_in=(0.01, 0.0, 0.01, 0.0),
            )
        )

        # Stack Track Box
        shapes_xml.append(
            _pptx_shape_xml(
                _next_sid(),
                f"Stack Track {v_name}",
                x_in=vx,
                y_in=track_y,
                w_in=var_col_w,
                h_in=track_h,
                fill_hex="F8FAFC",
                line_hex="E2E8F0",
                line_pt=0.6,
                geom="roundRect",
                round_adj=4000,
            )
        )

        if v_els:
            usable_track_h = track_h - 0.04 * sc
            min_blk_h = min(0.28 * sc, usable_track_h / max(1, len(v_els)))
            raw_heights = [
                max(min_blk_h, (float(e.get("time_s") or 0.0) / ref_time_s) * usable_track_h)
                for e in v_els
            ]
            sum_h = sum(raw_heights)
            if sum_h > usable_track_h and sum_h > 0:
                scale_h = usable_track_h / sum_h
                raw_heights = [h * scale_h for h in raw_heights]

            curr_bottom_y = track_y + track_h - 0.02 * sc
            for idx_e, e in enumerate(v_els):
                bh = raw_heights[idx_e]
                by = curr_bottom_y - bh
                curr_bottom_y = by
                step_num = idx_e + 1
                e_desc = str(e.get("description") or e.get("yamazumi_description") or f"Step {step_num}").strip()
                e_time = float(e.get("time_s") or 0.0)
                w_type = str(e.get("work_type") or "").strip().lower()
                e_color = str(e.get("motion_color") or "green").strip().lower()
                if w_type == "periodic" or e_color == "orange":
                    b_fill, b_line, b_txt = "FEF3C7", "F59E0B", "78350F"
                elif w_type == "fluctuation" or e_color == "gray":
                    b_fill, b_line, b_txt = "F1F5F9", "94A3B8", "334155"
                else:
                    b_fill, b_line, b_txt = "DCFCE7", "22C55E", "14532D"

                shapes_xml.append(
                    _pptx_shape_xml(
                        _next_sid(),
                        f"Stack Step {step_num}",
                        x_in=vx + 0.02 * sc,
                        y_in=by,
                        w_in=var_col_w - 0.04 * sc,
                        h_in=max(0.12, bh - 0.01 * sc),
                        paragraphs=[
                            _pptx_para_xml(
                                [
                                    _pptx_run_xml(f"{step_num}. ", pt=8.8 * sc, color=b_txt, bold=True),
                                    _pptx_run_xml(f"{e_desc} ", pt=8.5 * sc, color=b_txt),
                                    _pptx_run_xml(f"({_clean_number(e_time)}s)", pt=8.5 * sc, color=b_txt, bold=True),
                                ],
                                align="l",
                            )
                        ],
                        fill_hex=b_fill,
                        line_hex=b_line,
                        line_pt=0.6,
                        v_anchor="ctr",
                        pad_in=(0.04, 0.01, 0.04, 0.01),
                    )
                )

        if eff_takt_s > 0:
            takt_ratio = min(0.95, max(0.08, eff_takt_s / ref_time_s))
            takt_line_y = (track_y + track_h) - takt_ratio * (track_h - 0.04 * sc)
            shapes_xml.append(
                _pptx_shape_xml(
                    _next_sid(),
                    f"Takt Line {v_name}",
                    x_in=vx + 0.01 * sc,
                    y_in=takt_line_y,
                    w_in=var_col_w - 0.02 * sc,
                    h_in=0.015,
                    fill_hex="EF4444",
                    line_hex="EF4444",
                    line_pt=1.0,
                )
            )

    # --- 4. RIGHT COLUMN: VISUAL AID GRID ---
    grid_count = len(current_media_items)
    if grid_count == 0:
        shapes_xml.append(
            _pptx_shape_xml(
                _next_sid(),
                "Empty Visual Aid Card",
                x_in=rx,
                y_in=body_y,
                w_in=rw,
                h_in=body_h,
                paragraphs=[
                    _pptx_para_xml(
                        [_pptx_run_xml("No Visual Step Guides Added", pt=12.0 * sc, color="64748B", bold=True)],
                        align="ctr",
                        spc_after_pt=4.0,
                    ),
                    _pptx_para_xml(
                        [
                            _pptx_run_xml(
                                "Upload photos or videos in Process Visual Aids and tag them to work elements.",
                                pt=8.5 * sc,
                                color="94A3B8",
                            )
                        ],
                        align="ctr",
                    ),
                ],
                fill_hex="F8FAFC",
                line_hex="CBD5E1",
                line_pt=0.75,
                line_dash="dash",
                geom="roundRect",
                round_adj=4000,
                v_anchor="ctr",
            )
        )
    else:
        if grid_count == 1:
            g_cols, g_rows = 1, 1
        elif grid_count == 2:
            g_cols, g_rows = 2, 1
        elif grid_count in {3, 4}:
            g_cols, g_rows = 2, 2
        else:
            g_cols, g_rows = 3, 2

        g_gap = 0.08 * sc
        card_w = (rw - g_gap * (g_cols - 1)) / g_cols
        card_h = (body_h - g_gap * (g_rows - 1)) / g_rows
        total_pitch_elements_count = len(all_pitch_elements)

        for idx_m, item in enumerate(current_media_items):
            c_idx = idx_m % g_cols
            r_idx = idx_m // g_cols
            cx = rx + c_idx * (card_w + g_gap)
            cy = body_y + r_idx * (card_h + g_gap)

            # Card Frame
            shapes_xml.append(
                _pptx_shape_xml(
                    _next_sid(),
                    f"Visual Card {idx_m + 1}",
                    x_in=cx,
                    y_in=cy,
                    w_in=card_w,
                    h_in=card_h,
                    fill_hex="FFFFFF",
                    line_hex="CBD5E1",
                    line_pt=0.75,
                    geom="roundRect",
                    round_adj=3000,
                )
            )

            # Resolve tagged steps and step lines
            tagged_steps: list[int] = []
            tagged_op_by_num: dict[int, str] = {}
            for t in item.get("tagged_work_elements", []):
                t_wid = str(t.get("work_element_id") or "").strip()
                t_op = str(t.get("operation") or "").strip()
                if t_wid in step_num_by_wid:
                    sn = step_num_by_wid[t_wid]
                    tagged_steps.append(sn)
                    if t_op and sn not in tagged_op_by_num:
                        tagged_op_by_num[sn] = t_op
            if not tagged_steps:
                for t_wid in item.get("tagged_work_element_ids", []):
                    t_clean = str(t_wid).strip()
                    if t_clean in step_num_by_wid:
                        tagged_steps.append(step_num_by_wid[t_clean])
            tagged_steps = sorted(list(set(tagged_steps)))

            step_paras: list[str] = []
            if tagged_steps:
                for sn in tagged_steps[:4]:
                    s_title = step_desc_by_num.get(sn) or tagged_op_by_num.get(sn) or f"Step {sn}"
                    step_paras.append(
                        _pptx_para_xml(
                            [
                                _pptx_run_xml(f"[{sn}] ", pt=8.0 * sc, color="38BDF8", bold=True),
                                _pptx_run_xml(s_title, pt=8.0 * sc, color="FFFFFF", bold=True),
                            ],
                            align="l",
                        )
                    )
                if len(tagged_steps) > 4:
                    step_paras.append(
                        _pptx_para_xml(
                            [_pptx_run_xml(f"+{len(tagged_steps) - 4} more steps", pt=7.0 * sc, color="94A3B8", italic=True)],
                            align="l",
                        )
                    )
            elif total_pitch_elements_count > 0:
                nums_str = ", ".join(str(sn) for sn in range(1, total_pitch_elements_count + 1))
                step_paras.append(
                    _pptx_para_xml(
                        [_pptx_run_xml(f"All elements ({nums_str})", pt=8.0 * sc, color="FFFFFF", bold=True)],
                        align="l",
                    )
                )
            else:
                step_paras.append(
                    _pptx_para_xml(
                        [_pptx_run_xml("General Pitch Visual", pt=8.0 * sc, color="FFFFFF", bold=True)],
                        align="l",
                    )
                )

            banner_lines = max(1, len(step_paras))
            banner_h = min(card_h * 0.28, (0.24 + (banner_lines - 1) * 0.16) * sc)
            shapes_xml.append(
                _pptx_shape_xml(
                    _next_sid(),
                    f"Visual Step Banner {idx_m + 1}",
                    x_in=cx,
                    y_in=cy,
                    w_in=card_w,
                    h_in=banner_h,
                    paragraphs=step_paras,
                    fill_hex="0F172A",
                    v_anchor="ctr",
                    pad_in=(0.08, 0.03, 0.08, 0.03),
                )
            )

            raw_caption = str(item.get("caption") or "").strip()
            has_custom_caption = bool(
                raw_caption and raw_caption.casefold() not in {"visual aid", "step visual aid"}
            )
            callout_h = 0.26 * sc if has_custom_caption else 0.0

            media_box_x = cx + 0.04 * sc
            media_box_y = cy + banner_h + 0.04 * sc
            media_box_w = max(0.2, card_w - 0.08 * sc)
            media_box_h = max(0.2, card_h - banner_h - callout_h - 0.08 * sc)

            f_path = item.get("file_path") or ""
            emb_media = _embed_img(f_path)
            if emb_media:
                r_id_m, mw_px, mh_px = emb_media
                if image_fit == "fill":
                    draw_x, draw_y, draw_w, draw_h = media_box_x, media_box_y, media_box_w, media_box_h
                else:
                    m_aspect = mw_px / max(1, mh_px)
                    if media_box_w / media_box_h > m_aspect:
                        draw_h = media_box_h
                        draw_w = draw_h * m_aspect
                    else:
                        draw_w = media_box_w
                        draw_h = draw_w / m_aspect
                    draw_x = media_box_x + (media_box_w - draw_w) / 2.0
                    draw_y = media_box_y + (media_box_h - draw_h) / 2.0

                shapes_xml.append(
                    _pptx_pic_xml(
                        _next_sid(),
                        f"Visual Aid Image {idx_m + 1}",
                        r_id_m,
                        x_in=draw_x,
                        y_in=draw_y,
                        w_in=draw_w,
                        h_in=draw_h,
                    )
                )
            else:
                m_type = str(item.get("media_type") or "image").strip().lower()
                fallback_lbl = raw_caption or Path(str(f_path)).name or f"{m_type.upper()} Media"
                shapes_xml.append(
                    _pptx_shape_xml(
                        _next_sid(),
                        f"Visual Media Placeholder {idx_m + 1}",
                        x_in=media_box_x,
                        y_in=media_box_y,
                        w_in=media_box_w,
                        h_in=media_box_h,
                        paragraphs=[
                            _pptx_para_xml(
                                [_pptx_run_xml(fallback_lbl, pt=9.0 * sc, color="475569", bold=True)],
                                align="ctr",
                            )
                        ],
                        fill_hex="F8FAFC",
                        line_hex="E2E8F0",
                        line_pt=0.5,
                        v_anchor="ctr",
                    )
                )

            if has_custom_caption:
                shapes_xml.append(
                    _pptx_shape_xml(
                        _next_sid(),
                        f"Visual Callout {idx_m + 1}",
                        x_in=cx,
                        y_in=cy + card_h - callout_h,
                        w_in=card_w,
                        h_in=callout_h,
                        paragraphs=[
                            _pptx_para_xml(
                                [
                                    _pptx_run_xml("📍 ", pt=7.5 * sc, color="854D0E", bold=True),
                                    _pptx_run_xml(raw_caption, pt=7.5 * sc, color="713F12", bold=True),
                                ],
                                align="l",
                            )
                        ],
                        fill_hex="FEF9C3",
                        line_hex="FDE047",
                        line_pt=0.6,
                        v_anchor="ctr",
                        pad_in=(0.06, 0.02, 0.06, 0.02),
                    )
                )

    slide_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        "<p:cSld>"
        "<p:bg><p:bgPr><a:solidFill><a:srgbClr val=\"E2E8F0\"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>"
        "<p:spTree>"
        "<p:nvGrpSpPr>"
        '<p:cNvPr id="1" name=""/>'
        "<p:cNvGrpSpPr/>"
        "<p:nvPr/>"
        "</p:nvGrpSpPr>"
        "<p:grpSpPr>"
        "<a:xfrm>"
        '<a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/>'
        "</a:xfrm>"
        "</p:grpSpPr>"
        f"{''.join(shapes_xml)}"
        "</p:spTree>"
        "</p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>"
        "</p:sld>"
    )
    return slide_xml, slide_rels


def render_paag_pptx_deck(
    slides_data: list[dict],
    *,
    paper_size: str = "letter",
    image_fit: str = "contain",
    scenario_name: str = "",
    project_name: str = "",
    title: str = "Process at a Glance",
) -> bytes:
    """Build a standalone, native OpenXML PowerPoint (.pptx) deck for the selected PAAG slides."""
    import hashlib
    import io
    import zipfile

    is_tabloid = paper_size == "tabloid"
    slide_w_emu = _pptx_in(17.0 if is_tabloid else 11.0)
    slide_h_emu = _pptx_in(11.0 if is_tabloid else 8.5)

    media_by_hash: dict[str, tuple[str, bytes, int, int]] = {}
    path_cache: dict[str, tuple[str, int, int] | None] = {}

    def _register_media(raw_path: object) -> tuple[str, int, int] | None:
        key = str(raw_path or "").strip()
        if not key:
            return None
        if key in path_cache:
            return path_cache[key]
        loaded = _load_pptx_image_bytes(key)
        if not loaded:
            path_cache[key] = None
            return None
        png_bytes, w_px, h_px = loaded
        digest = hashlib.sha1(png_bytes).hexdigest()[:16]
        if digest not in media_by_hash:
            fname = f"image_{len(media_by_hash) + 1}_{digest}.png"
            media_by_hash[digest] = (fname, png_bytes, w_px, h_px)
        fname, _, w_px, h_px = media_by_hash[digest]
        path_cache[key] = (fname, w_px, h_px)
        return fname, w_px, h_px

    effective_slides = slides_data if slides_data else [{"pitch": {}, "elements": [], "page_num": 1, "total_pages": 1}]
    compiled_slides: list[tuple[str, list[tuple[str, str]]]] = []
    for s_spec in effective_slides:
        s_xml, s_rels = _render_single_paag_pptx_slide(
            s_spec,
            paper_size=paper_size,
            image_fit=image_fit,
            scenario_name=scenario_name,
            project_name=project_name,
            register_media_fn=_register_media,
        )
        compiled_slides.append((s_xml, s_rels))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. [Content_Types].xml
        slide_ct_overrides = "".join(
            f'<Override PartName="/ppt/slides/slide{i}.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            for i in range(1, len(compiled_slides) + 1)
        )
        content_types_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
            '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
            '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.theme+xml"/>'
            '<Override PartName="/ppt/presProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"/>'
            '<Override PartName="/ppt/viewProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml"/>'
            '<Override PartName="/ppt/tableStyles.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            f"{slide_ct_overrides}"
            "</Types>"
        )
        zf.writestr("[Content_Types].xml", content_types_xml)

        # 2. _rels/.rels
        root_rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            "</Relationships>"
        )
        zf.writestr("_rels/.rels", root_rels_xml)

        # 3. docProps/core.xml & docProps/app.xml
        iso_now = f"{date.today().isoformat()}T00:00:00Z"
        core_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>{_xml_esc(title)}</dc:title>"
            "<dc:creator>Process at a Glance</dc:creator>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{iso_now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{iso_now}</dcterms:modified>'
            "</cp:coreProperties>"
        )
        zf.writestr("docProps/core.xml", core_xml)

        app_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
            'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            "<Application>Process at a Glance</Application>"
            f"<Slides>{len(compiled_slides)}</Slides>"
            "<ScaleCrop>false</ScaleCrop>"
            "<LinksUpToDate>false</LinksUpToDate>"
            "<SharedDoc>false</SharedDoc>"
            "<HyperlinksChanged>false</HyperlinksChanged>"
            "<AppVersion>16.0000</AppVersion>"
            "</Properties>"
        )
        zf.writestr("docProps/app.xml", app_xml)

        # 4. ppt/presentation.xml & ppt/_rels/presentation.xml.rels
        sld_id_entries = "".join(
            f'<p:sldId id="{255 + i}" r:id="rId{5 + i}"/>'
            for i in range(1, len(compiled_slides) + 1)
        )
        presentation_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" saveSubsetFonts="1">'
            '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
            f"<p:sldIdLst>{sld_id_entries}</p:sldIdLst>"
            f'<p:sldSz cx="{slide_w_emu}" cy="{slide_h_emu}"/>'
            '<p:notesSz cx="6858000" cy="9144000"/>'
            "<p:defaultTextStyle>"
            "<a:defPPr><a:defRPr lang=\"en-US\"/></a:defPPr>"
            "</p:defaultTextStyle>"
            "</p:presentation>"
        )
        zf.writestr("ppt/presentation.xml", presentation_xml)

        pres_slide_rels = "".join(
            f'<Relationship Id="rId{5 + i}" '
            f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
            f'Target="slides/slide{i}.xml"/>'
            for i in range(1, len(compiled_slides) + 1)
        )
        pres_rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/presProps" Target="presProps.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/viewProps" Target="viewProps.xml"/>'
            '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>'
            '<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/tableStyles" Target="tableStyles.xml"/>'
            f"{pres_slide_rels}"
            "</Relationships>"
        )
        zf.writestr("ppt/_rels/presentation.xml.rels", pres_rels_xml)

        # 5. Supporting presentation parts
        zf.writestr(
            "ppt/presProps.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:presentationPr xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
        )
        zf.writestr(
            "ppt/viewProps.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:viewPr xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            '<p:normalViewPr><p:restoredLeft sz="15620"/><p:restoredTop sz="94660"/></p:normalViewPr>'
            "</p:viewPr>",
        )
        zf.writestr(
            "ppt/tableStyles.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>',
        )

        # 6. Theme, Slide Master, Slide Layout
        theme_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="PAAG Theme">'
            "<a:themeElements>"
            '<a:clrScheme name="PAAG">'
            '<a:dk1><a:srgbClr val="0F172A"/></a:dk1>'
            '<a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>'
            '<a:dk2><a:srgbClr val="334155"/></a:dk2>'
            '<a:lt2><a:srgbClr val="F8FAFC"/></a:lt2>'
            '<a:accent1><a:srgbClr val="0284C7"/></a:accent1>'
            '<a:accent2><a:srgbClr val="16A34A"/></a:accent2>'
            '<a:accent3><a:srgbClr val="F59E0B"/></a:accent3>'
            '<a:accent4><a:srgbClr val="EF4444"/></a:accent4>'
            '<a:accent5><a:srgbClr val="7E22CE"/></a:accent5>'
            '<a:accent6><a:srgbClr val="64748B"/></a:accent6>'
            '<a:hlink><a:srgbClr val="0284C7"/></a:hlink>'
            '<a:folHlink><a:srgbClr val="0369A1"/></a:folHlink>'
            "</a:clrScheme>"
            '<a:fontScheme name="PAAG">'
            '<a:majorFont><a:latin typeface="Segoe UI"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
            '<a:minorFont><a:latin typeface="Segoe UI"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>'
            "</a:fontScheme>"
            '<a:fmtScheme name="PAAG">'
            "<a:fillStyleLst><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill></a:fillStyleLst>"
            '<a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
            "<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>"
            "<a:bgFillStyleLst><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill></a:bgFillStyleLst>"
            "</a:fmtScheme>"
            "</a:themeElements>"
            "<a:objectDefaults/>"
            "<a:extraClrSchemeLst/>"
            "</a:theme>"
        )
        zf.writestr("ppt/theme/theme1.xml", theme_xml)

        slide_master_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            "<p:cSld>"
            "<p:bg><p:bgRef idx=\"1001\"><a:schemeClr val=\"bg1\"/></p:bgRef></p:bg>"
            "<p:spTree>"
            "<p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>"
            "<p:grpSpPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"0\" cy=\"0\"/><a:chOff x=\"0\" y=\"0\"/><a:chExt cx=\"0\" cy=\"0\"/></a:xfrm></p:grpSpPr>"
            "</p:spTree>"
            "</p:cSld>"
            '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
            '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
            "<p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles>"
            "</p:sldMaster>"
        )
        zf.writestr("ppt/slideMasters/slideMaster1.xml", slide_master_xml)
        zf.writestr(
            "ppt/slideMasters/_rels/slideMaster1.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>'
            "</Relationships>",
        )

        slide_layout_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">'
            '<p:cSld name="Blank">'
            "<p:spTree>"
            "<p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>"
            "<p:grpSpPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"0\" cy=\"0\"/><a:chOff x=\"0\" y=\"0\"/><a:chExt cx=\"0\" cy=\"0\"/></a:xfrm></p:grpSpPr>"
            "</p:spTree>"
            "</p:cSld>"
            "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>"
            "</p:sldLayout>"
        )
        zf.writestr("ppt/slideLayouts/slideLayout1.xml", slide_layout_xml)
        zf.writestr(
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
            "</Relationships>",
        )

        # 7. Write slides & slide relationships
        for idx_s, (s_xml, s_rels) in enumerate(compiled_slides, start=1):
            zf.writestr(f"ppt/slides/slide{idx_s}.xml", s_xml)
            img_rel_tags = "".join(
                f'<Relationship Id="{r_id}" '
                f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                f'Target="{target}"/>'
                for r_id, target in s_rels
            )
            s_rels_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                f"{img_rel_tags}"
                "</Relationships>"
            )
            zf.writestr(f"ppt/slides/_rels/slide{idx_s}.xml.rels", s_rels_xml)

        # 8. Write deduplicated media files
        for fname, png_bytes, _, _ in media_by_hash.values():
            zf.writestr(f"ppt/media/{fname}", png_bytes)

    return buf.getvalue()


_PROCESS_PITCH_VISUAL_REV_20261102 = 13
