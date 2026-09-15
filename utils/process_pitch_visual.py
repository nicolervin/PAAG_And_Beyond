from __future__ import annotations

import base64
import html
import mimetypes
from datetime import date
from pathlib import Path
from typing import Iterable


ELEMENTS_PER_PAGE = 5


def page_count(element_count: int, page_size: int = ELEMENTS_PER_PAGE) -> int:
    return max(1, (max(0, int(element_count)) + page_size - 1) // page_size)


def clamp_page(page_num: int, element_count: int) -> int:
    return min(max(1, int(page_num or 1)), page_count(element_count))


def page_for_element(
    elements: Iterable[dict], work_element_id: str, page_size: int = ELEMENTS_PER_PAGE
) -> int:
    target = str(work_element_id or "").strip()
    for index, element in enumerate(elements):
        if str(element.get("work_element_id") or "").strip() == target:
            return index // page_size + 1
    raise ValueError("The selected Work Element is no longer assigned to this pitch.")


def page_elements(
    elements: list[dict], page_num: int, page_size: int = ELEMENTS_PER_PAGE
) -> list[dict]:
    current = clamp_page(page_num, len(elements))
    start = (current - 1) * page_size
    return elements[start : start + page_size]


def _text(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _clean_number(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _text(value)
    return f"{number:g}"


def _image_data_url(raw_path: object) -> str:
    path = Path(str(raw_path or ""))
    try:
        if not path.is_file():
            return ""
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except OSError:
        return ""


def _part_images(parts: list[dict]) -> str:
    images: list[str] = []
    for part in parts:
        part_number = _text(part.get("part_number") or "Part")
        source = _image_data_url(part.get("image_path"))
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
    elements: list[dict],
    *,
    scenario_name: str,
    generated_on: date | None = None,
) -> str:
    """Render one escaped, read-only 16:9 pitch page."""
    cards: list[str] = []
    max_time = max((float(row.get("time_s") or 0) for row in elements), default=0.0)
    for element in elements[:ELEMENTS_PER_PAGE]:
        duration = max(0.0, float(element.get("time_s") or 0))
        bar_height = 28 if max_time <= 0 else max(28, round(76 * duration / max_time))
        tags: list[str] = []
        if element.get("ergonomics_risk"):
            tags.append('<span class="tag ergo">Ergo Risk</span>')
        tags.extend(_torque_badge(item) for item in element.get("torque_requirements", []))
        tag_html = "".join(tags) or '<span class="tag none">No review tags</span>'
        models = element.get("models") or ["All models"]
        model_text = ", ".join(_text(value) for value in models)
        color = str(element.get("motion_color") or "gray")
        if color not in {"green", "orange", "gray"}:
            color = "gray"
        header = " — ".join(
            (
                _text(pitch.get("pitch_number") or "Unassigned"),
                _text(element.get("op_id") or "Yamazumi link required"),
                _text(element.get("yamazumi_description") or element.get("operation")),
            )
        )
        cards.append(
            f"""
            <article class="element-card">
              <header>{header}</header>
              <div class="card-body">
                <div class="parts">{_part_images(element.get("parts", []))}</div>
                <div class="motion">
                  <div class="motion-bar {color}" style="height:{bar_height}px"></div>
                  <div><strong>{_text(element.get('motion_classification'))}</strong><br>
                  {_text(element.get('yamazumi_description'))} · {_clean_number(duration)} s</div>
                </div>
                <div class="models"><strong>Models</strong><br>{model_text}</div>
              </div>
              <footer class="tags">{tag_html}</footer>
            </article>"""
        )
    generated = generated_on or date.today()
    generated_label = f"{generated:%B} {generated.day}, {generated.year}"
    return f"""
    <style>
      .pitch-canvas {{ aspect-ratio:16/9; box-sizing:border-box; width:100%; min-height:560px;
        padding:12px; border:1px solid rgba(128,128,128,.35); border-radius:12px;
        background:var(--secondary-background-color, #f7f8fa); display:flex; flex-direction:column; gap:7px; }}
      .element-card {{ flex:1 1 0; min-height:0; overflow:hidden; border:1px solid rgba(128,128,128,.3);
        border-radius:8px; background:var(--background-color, white); padding:6px 9px; display:flex; flex-direction:column; }}
      .element-card>header {{ font-size:.84rem; font-weight:700; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
      .card-body {{ flex:1; min-height:0; display:grid; grid-template-columns:1.25fr 1.4fr 1fr; gap:10px; align-items:center; }}
      .parts {{ height:58px; display:flex; gap:5px; overflow:hidden; }}
      figure {{ margin:0; height:58px; min-width:68px; position:relative; }}
      figure img {{ width:68px; height:43px; object-fit:contain; border-radius:4px; background:#eee; }}
      figcaption {{ font-size:.58rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:68px; }}
      .part-placeholder {{ width:68px; height:51px; background:#d8dadd; color:#555; border-radius:4px;
        display:flex; flex-direction:column; justify-content:center; align-items:center; text-align:center; font-size:.65rem; }}
      .part-placeholder.no-parts {{ width:100%; max-width:150px; font-weight:650; }}
      .part-placeholder small {{ font-size:.55rem; max-width:62px; overflow:hidden; text-overflow:ellipsis; }}
      .motion {{ display:flex; gap:8px; align-items:center; font-size:.68rem; line-height:1.2; }}
      .motion-bar {{ width:18px; min-height:28px; max-height:76px; border-radius:4px 4px 2px 2px; flex:none; }}
      .motion-bar.green {{ background:#2e7d32; }} .motion-bar.orange {{ background:#ed8b00; }}
      .motion-bar.gray {{ background:#8b9198; }}
      .models {{ font-size:.66rem; line-height:1.25; max-height:42px; overflow:hidden; }}
      .tags {{ display:flex; gap:5px; flex-wrap:wrap; min-height:16px; }}
      .tag {{ border-radius:999px; padding:1px 7px; font-size:.58rem; background:#e8eaed; color:#333; }}
      .tag.ergo {{ background:#f8d7da; color:#9b1c24; }} .tag.torque {{ background:#dbeafe; color:#174ea6; }}
      .tag.none {{ color:#666; }}
      .snapshot {{ margin-top:auto; text-align:right; font-size:.62rem; color:#697077; padding-right:2px; }}
      @media (max-width:800px) {{ .pitch-canvas {{ aspect-ratio:auto; min-height:720px; }}
        .card-body {{ grid-template-columns:1fr 1.2fr; }} .models {{ grid-column:1 / -1; }} }}
      @media print {{ .pitch-canvas {{ aspect-ratio:16/9; break-inside:avoid; min-height:0; }} }}
    </style>
    <section class="pitch-canvas" aria-label="Pitch visual summary">
      {''.join(cards) if cards else '<div class="part-placeholder no-parts">No Process work is linked to this pitch.</div>'}
      <div class="snapshot">Generated on {_text(generated_label)} — Scenario: {_text(scenario_name)}</div>
    </section>
    """
