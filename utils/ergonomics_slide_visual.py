from __future__ import annotations

import base64
import html
import mimetypes
from datetime import date
from pathlib import Path
from typing import Any


def _text(value: object) -> str:
    """Safely escape text for HTML display."""
    return html.escape(str(value or ""), quote=True)


def _media_data_url(raw_path: object) -> str:
    """Convert an image or video file path to a base64 data URL for self-contained rendering."""
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
            elif suffix in {".jpg", ".jpeg"}:
                mime = "image/jpeg"
            elif suffix == ".png":
                mime = "image/png"
            elif suffix == ".webp":
                mime = "image/webp"
            else:
                mime = "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except OSError:
        return ""


def get_risk_colors(risk: str) -> dict[str, str]:
    """Return styling colors for an ergonomics risk classification."""
    clean_risk = str(risk or "").strip().lower()
    if clean_risk == "favorable red":
        return {
            "bg": "#7f1d1d",
            "fg": "#fecaca",
            "border": "#b91c1c",
            "badge_bg": "#fef2f2",
            "badge_fg": "#991b1b",
            "badge_border": "#f87171",
            "label": "Favorable Red",
            "icon": "⚠️",
        }
    if clean_risk == "red":
        return {
            "bg": "#dc2626",
            "fg": "#ffffff",
            "border": "#991b1b",
            "badge_bg": "#fee2e2",
            "badge_fg": "#b91c1c",
            "badge_border": "#ef4444",
            "label": "Red (High Risk)",
            "icon": "🚨",
        }
    if clean_risk == "favorable green":
        return {
            "bg": "#065f46",
            "fg": "#a7f3d0",
            "border": "#059669",
            "badge_bg": "#ecfdf5",
            "badge_fg": "#047857",
            "badge_border": "#34d399",
            "label": "Favorable Green",
            "icon": "✓",
        }
    if clean_risk == "green":
        return {
            "bg": "#16a34a",
            "fg": "#ffffff",
            "border": "#15803d",
            "badge_bg": "#dcfce7",
            "badge_fg": "#15803d",
            "badge_border": "#22c55e",
            "label": "Green (Low Risk)",
            "icon": "✓",
        }
    return {
        "bg": "#475569",
        "fg": "#f1f5f9",
        "border": "#334155",
        "badge_bg": "#f1f5f9",
        "badge_fg": "#475569",
        "badge_border": "#cbd5e1",
        "label": "Not yet assessed",
        "icon": "⏳",
    }


def get_status_colors(status: str) -> dict[str, str]:
    """Return styling colors for an ergonomics review status."""
    clean_status = str(status or "").strip().lower()
    if clean_status in {"closed (engineering)", "closed (admin)"}:
        return {"bg": "#dcfce7", "fg": "#166534", "border": "#86efac", "label": status}
    if clean_status == "validation":
        return {"bg": "#e0e7ff", "fg": "#3730a3", "border": "#a5b4fc", "label": status}
    if clean_status == "pending":
        return {"bg": "#fef3c7", "fg": "#92400e", "border": "#fcd34d", "label": status}
    if clean_status == "open":
        return {"bg": "#ffedd5", "fg": "#9a3412", "border": "#fdba74", "label": status}
    return {"bg": "#f1f5f9", "fg": "#475569", "border": "#cbd5e1", "label": status or "Started"}


def render_ergonomics_slide(
    summary: dict,
    *,
    page_num: int = 1,
    total_pages: int = 1,
    presentation_mode: bool = False,
    print_format: str | None = None,
    image_fit: str = "contain",
    generated_on: date | None = None,
) -> str:
    """Render a 16:9 landscape Ergonomics Review slide."""
    review = summary.get("review") or {}
    work_info = summary.get("work_info") or {}
    parts = summary.get("parts") or []
    equipment = summary.get("equipment") or []
    media_list = summary.get("media") or []
    hazards = summary.get("hazards") or []

    project_name = _text(summary.get("project_name") or "PAAG Project")
    scenario_name = _text(summary.get("scenario_name") or "Scenario")
    takt_time_s = float(summary.get("takt_time_s") or 0.0)
    takt_unit = _text(summary.get("takt_time_unit") or "seconds")

    risk_classification = str(review.get("risk_classification") or "Not yet assessed")
    risk_colors = get_risk_colors(risk_classification)

    status = str(review.get("status") or "Started")
    status_colors = get_status_colors(status)

    reviewer = _text(review.get("reviewer") or "Unassigned")
    notes = _text(review.get("notes") or "")
    due_date = _text(review.get("requested_due_date") or "")

    # Date formatting
    gen_date = generated_on or date.today()
    gen_date_str = f"{gen_date:%B} {gen_date.day}, {gen_date.year}"

    # Operation & Pitch info
    is_linked = bool(review.get("work_element_id"))
    legacy_desc = _text(review.get("legacy_description") or "")
    pitch_num = _text(work_info.get("pitch_number") or "")
    pitch_name = _text(work_info.get("pitch_name") or "")
    section_name = _text(work_info.get("section_name") or "")
    area_name = _text(work_info.get("area_name") or "")
    cycle_time = float(work_info.get("time_s") or work_info.get("cycle_time") or 0.0)

    # Pitch location line
    location_parts = [p for p in [pitch_num, pitch_name, section_name] if p]
    if is_linked and legacy_desc:
        location_parts.append(f"Legacy Concern: {legacy_desc}")
    location_line = " · ".join(location_parts) if location_parts else ("Unassigned Pitch" if is_linked else "Unlinked Item")

    # Title header text
    if is_linked:
        op_desc = _text(work_info.get("operation") or "Process Step")
        title_prefix = f"Pitch {pitch_num}" if pitch_num else "Process Step"
        slide_title = f"{title_prefix}: {op_desc}"
    else:
        op_desc = legacy_desc or "Unlinked Ergonomics Concern"
        slide_title = f"Unlinked Concern: {op_desc}" if legacy_desc else "Unlinked Ergonomics Concern"

    # Hazard tags HTML
    if hazards:
        hazard_chips_html = "".join(
            f'<span class="ergo-hazard-chip">{_text(h)}</span>' for h in hazards
        )
    else:
        hazard_chips_html = '<span class="text-muted" style="font-size:0.82rem;">No specific hazards tagged</span>'

    # Parts HTML & Heavy lift calculation
    part_rows_html = []
    has_heavy_part = summary.get("has_heavy_part", False)
    max_part_weight = float(summary.get("max_part_weight") or 0.0)
    total_parts_weight = float(summary.get("total_parts_weight") or 0.0)

    for p in parts:
        p_num = _text(p.get("part_number") or "Part")
        p_desc = _text(p.get("description") or "")
        p_qty = float(p.get("quantity") or 1.0)
        p_wt = p.get("weight_lb")
        wt_str = f"{float(p_wt):.1f} lbs" if p_wt is not None else "—"
        is_heavy = float(p_wt or 0.0) >= 33.0 or (float(p_wt or 0.0) * p_qty) >= 33.0
        wt_badge_class = "wt-heavy" if is_heavy else ""

        part_rows_html.append(
            f"""
            <tr>
              <td><strong>{p_num}</strong></td>
              <td class="col-desc" title="{p_desc}">{p_desc or '—'}</td>
              <td style="text-align:center;">{p_qty:g}</td>
              <td style="text-align:right;"><span class="ergo-wt-badge {wt_badge_class}">{wt_str}</span></td>
            </tr>
            """
        )

    parts_table_html = (
        f"""
        <table class="ergo-parts-table">
          <thead>
            <tr>
              <th>Part #</th>
              <th>Description</th>
              <th style="text-align:center;">Qty</th>
              <th style="text-align:right;">Weight</th>
            </tr>
          </thead>
          <tbody>
            {''.join(part_rows_html)}
          </tbody>
        </table>
        """
        if part_rows_html
        else '<div class="subtle-empty">No parts linked to this work element</div>'
    )

    # Equipment HTML
    eq_badges_html = []
    for eq in equipment:
        e_name = _text(eq.get("name") or "Equipment")
        e_type = _text(eq.get("type_name") or "")
        eq_badges_html.append(
            f'<span class="ergo-eq-badge" title="{e_type}">{e_name}</span>'
        )
    equipment_section_html = (
        f'<div class="ergo-eq-container">{" ".join(eq_badges_html)}</div>'
        if eq_badges_html
        else '<div class="subtle-empty">No ergonomic equipment or lift assists linked</div>'
    )

    # Cycle Time vs Takt Time gauge
    takt_pct = min(100, int((cycle_time / takt_time_s * 100))) if takt_time_s > 0 else 0
    takt_bar_color = "#dc2626" if takt_pct > 100 else "#16a34a" if takt_pct > 0 else "#94a3b8"
    time_gauge_html = f"""
    <div class="ergo-time-card">
      <div class="time-header">
        <span class="time-title">Cycle Time vs Takt Time</span>
        <span class="time-vals"><strong>{cycle_time:g}s</strong> / {takt_time_s:g} {takt_unit} ({takt_pct}%)</span>
      </div>
      <div class="time-bar-track">
        <div class="time-bar-fill" style="width: {takt_pct}%; background-color: {takt_bar_color};"></div>
      </div>
    </div>
    """

    # Visual Media Cards HTML
    media_cards_html = []
    media_count = len(media_list)
    if media_count == 1:
        grid_class = "media-grid-1"
    elif media_count == 2:
        grid_class = "media-grid-2"
    elif media_count == 3:
        grid_class = "media-grid-3"
    else:
        grid_class = "media-grid-4"

    for idx, item in enumerate(media_list[:4]):
        m_type = str(item.get("media_type") or "image").lower()
        caption = _text(item.get("caption") or "")
        seq = item.get("sequence", (idx + 1) * 10)
        data_url = item.get("data_url") or _media_data_url(item.get("file_path"))

        if m_type == "video":
            media_content = f"""
            <video class="ergo-media-item video" controls playsinline preload="metadata">
              <source src="{data_url}" type="video/mp4">
              Your browser does not support the video tag.
            </video>
            """
        else:
            media_content = f"""
            <img class="ergo-media-item image" src="{data_url}" alt="{caption or 'Ergonomics Visual Aid'}" />
            """

        caption_block = (
            f"""
            <div class="ergo-callout-box">
              <span class="callout-seq">#{seq}</span>
              <span class="callout-text">{caption}</span>
            </div>
            """
            if caption
            else ""
        )

        media_cards_html.append(
            f"""
            <div class="ergo-media-card">
              <div class="ergo-media-wrapper {image_fit}">
                {media_content}
              </div>
              {caption_block}
            </div>
            """
        )

    if not media_cards_html:
        visual_grid_html = """
        <div class="ergo-empty-visual">
          <div class="empty-icon">📷</div>
          <div class="empty-title">No Visual Aids Attached</div>
          <div class="empty-desc">Upload photos, annotated screenshots, or video clips in the Visual Aids manager below to display them on this Ergonomics slide.</div>
        </div>
        """
    else:
        visual_grid_html = f"""
        <div class="ergo-visual-grid {grid_class}">
          {''.join(media_cards_html)}
        </div>
        """

    # Heavy Lift Alert Banner
    heavy_alert_html = ""
    if has_heavy_part:
        heavy_alert_html = f"""
        <div class="ergo-heavy-alert">
          <span class="alert-icon">⚠️</span>
          <strong>Manual Material Handling Warning:</strong> Component weight ({max_part_weight:.1f} lbs) meets or exceeds the 33.0 lbs threshold. Verify lift-assist or two-person lift protocol.
        </div>
        """

    presentation_class = "presentation-active" if presentation_mode else ""
    print_class = f"print-{print_format}" if print_format else ""

    return f"""
    <div class="ergo-slide {presentation_class} {print_class} fit-{image_fit}">
      <!-- Slide Header Banner -->
      <div class="ergo-header">
        <div class="header-branding">
          <div class="brand-title">PROCESS AT A GLANCE · ERGONOMICS</div>
          <div class="brand-sub">{project_name} · {scenario_name}</div>
        </div>
        <div class="header-main-title">
          <div class="main-op-title" title="{slide_title}">{slide_title}</div>
          <div class="main-location-title">{location_line}</div>
        </div>
        <div class="header-doc-control">
          <div class="doc-control-row">
            <span class="doc-status-badge" style="background:{status_colors['bg']}; color:{status_colors['fg']}; border:1px solid {status_colors['border']};">
              {status_colors['label']}
            </span>
            <span class="doc-risk-badge" style="background:{risk_colors['bg']}; color:{risk_colors['fg']}; border:1px solid {risk_colors['border']};">
              {risk_colors['icon']} {risk_colors['label']}
            </span>
          </div>
          <div class="doc-meta-row">
            <span>{gen_date_str}</span>
            <span>Reviewer: <strong>{reviewer}</strong></span>
          </div>
        </div>
      </div>

      {heavy_alert_html}

      <!-- Slide Main Content (2 Columns) -->
      <div class="ergo-body">
        <!-- Left Column: Assessment & Physical Demands -->
        <div class="ergo-left-col">
          <!-- Risk & Hazard Assessment Card -->
          <div class="ergo-section-card">
            <div class="card-title">Ergonomic Risk & Hazard Analysis</div>
            <div class="ergo-risk-summary-row">
              <div class="risk-indicator-box" style="background:{risk_colors['badge_bg']}; color:{risk_colors['badge_fg']}; border:1.5px solid {risk_colors['badge_border']};">
                <span class="risk-icon">{risk_colors['icon']}</span>
                <span class="risk-label">{risk_colors['label']}</span>
              </div>
              <div class="ergo-hazards-box">
                {hazard_chips_html}
              </div>
            </div>
          </div>

          <!-- Time & Workstation Context -->
          {time_gauge_html}

          <!-- Parts & Load Analysis -->
          <div class="ergo-section-card">
            <div class="card-title">
              <span>Parts Handled & Weight</span>
              <span class="card-badge">Total: {total_parts_weight:.1f} lbs</span>
            </div>
            {parts_table_html}
          </div>

          <!-- Equipment & Ergonomic Tooling -->
          <div class="ergo-section-card">
            <div class="card-title">Ergonomic Fixtures & Equipment</div>
            {equipment_section_html}
          </div>

          <!-- Assessment Notes & Corrective Actions -->
          <div class="ergo-section-card">
            <div class="card-title">
              <span>Assessment Notes & Action Items</span>
              {f'<span class="card-badge due">Due: {due_date}</span>' if due_date else ''}
            </div>
            <div class="ergo-notes-text">{notes or '<span class="text-muted">No notes or corrective actions recorded yet.</span>'}</div>
          </div>
        </div>

        <!-- Right Column: Visual Aids & Video Grid -->
        <div class="ergo-right-col">
          {visual_grid_html}
        </div>
      </div>

      <!-- Footer Bar -->
      <div class="ergo-footer">
        <span>Process at a Glance · Ergonomics Standard Work Assessment</span>
        <span>Slide 1 of 1 · Review ID: <code style="font-size:0.75rem;">{_text(review.get('id') or '')[:8]}</code></span>
      </div>
    </div>

    <style>
      .ergo-slide {{
        aspect-ratio: 16 / 9;
        box-sizing: border-box;
        width: 100%;
        max-width: 100%;
        min-height: 640px;
        height: auto;
        padding: 12px 16px;
        border: 1px solid rgba(148, 163, 184, 0.35);
        border-radius: 12px;
        background: #ffffff;
        color: #0f172a;
        display: flex;
        flex-direction: column;
        gap: 10px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        box-shadow: 0 4px 18px rgba(0, 0, 0, 0.05);
        overflow: hidden;
      }}

      /* Presentation & Print Overrides */
      .ergo-slide.presentation-active {{
        border: none;
        box-shadow: none;
        border-radius: 0;
        height: 100%;
        max-height: 94vh;
      }}

      .ergo-slide.print-tabloid {{
        aspect-ratio: 17 / 11 !important;
        min-height: 680px;
      }}

      .ergo-slide.print-letter {{
        aspect-ratio: 11 / 8.5 !important;
        min-height: 580px;
      }}

      /* Header */
      .ergo-header {{
        display: grid;
        grid-template-columns: 1.2fr 2fr 1.3fr;
        align-items: center;
        gap: 12px;
        padding-bottom: 8px;
        border-bottom: 2px solid #e2e8f0;
      }}

      .header-branding .brand-title {{
        font-size: 0.78rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        color: #1e3a8a;
      }}

      .header-branding .brand-sub {{
        font-size: 0.74rem;
        color: #64748b;
        margin-top: 1px;
      }}

      .header-main-title {{
        text-align: center;
      }}

      .header-main-title .main-op-title {{
        font-size: 1.15rem;
        font-weight: 800;
        color: #0f172a;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}

      .header-main-title .main-location-title {{
        font-size: 0.82rem;
        font-weight: 600;
        color: #475569;
        margin-top: 2px;
      }}

      .header-doc-control {{
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 4px;
      }}

      .doc-control-row {{
        display: flex;
        gap: 6px;
      }}

      .doc-status-badge {{
        font-size: 0.72rem;
        font-weight: 700;
        padding: 3px 8px;
        border-radius: 6px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }}

      .doc-risk-badge {{
        font-size: 0.75rem;
        font-weight: 800;
        padding: 3px 10px;
        border-radius: 6px;
        letter-spacing: 0.03em;
      }}

      .doc-meta-row {{
        font-size: 0.72rem;
        color: #64748b;
        display: flex;
        gap: 10px;
      }}

      /* Heavy Lift Alert Banner */
      .ergo-heavy-alert {{
        display: flex;
        align-items: center;
        gap: 8px;
        background: #fef2f2;
        border: 1.5px solid #f87171;
        border-radius: 8px;
        padding: 6px 12px;
        color: #991b1b;
        font-size: 0.84rem;
      }}

      .ergo-heavy-alert .alert-icon {{
        font-size: 1.1rem;
      }}

      /* Body 2-Column Layout */
      .ergo-body {{
        display: grid;
        grid-template-columns: 42% 58%;
        gap: 14px;
        flex: 1 1 auto;
        min-height: 0;
        overflow: hidden;
      }}

      .ergo-left-col {{
        display: flex;
        flex-direction: column;
        gap: 8px;
        overflow-y: auto;
        padding-right: 4px;
      }}

      .ergo-right-col {{
        display: flex;
        flex-direction: column;
        min-height: 0;
        height: 100%;
      }}

      /* Section Cards */
      .ergo-section-card {{
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 8px 12px;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }}

      .ergo-section-card .card-title {{
        font-size: 0.76rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #334155;
        display: flex;
        justify-content: space-between;
        align-items: center;
      }}

      .card-badge {{
        font-size: 0.72rem;
        font-weight: 600;
        background: #e2e8f0;
        color: #334155;
        padding: 1px 6px;
        border-radius: 4px;
      }}

      .card-badge.due {{
        background: #fee2e2;
        color: #991b1b;
      }}

      /* Risk & Hazards Box */
      .ergo-risk-summary-row {{
        display: flex;
        gap: 10px;
        align-items: center;
      }}

      .risk-indicator-box {{
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 0.85rem;
        font-weight: 800;
        white-space: nowrap;
      }}

      .ergo-hazards-box {{
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
        align-items: center;
      }}

      .ergo-hazard-chip {{
        display: inline-block;
        background: #e0f2fe;
        color: #0369a1;
        border: 1px solid #bae6fd;
        border-radius: 9999px;
        padding: 2px 8px;
        font-size: 0.74rem;
        font-weight: 600;
      }}

      /* Time Card */
      .ergo-time-card {{
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 6px 12px;
      }}

      .time-header {{
        display: flex;
        justify-content: space-between;
        font-size: 0.74rem;
        color: #475569;
        margin-bottom: 4px;
      }}

      .time-bar-track {{
        height: 6px;
        background: #e2e8f0;
        border-radius: 9999px;
        overflow: hidden;
      }}

      .time-bar-fill {{
        height: 100%;
        border-radius: 9999px;
        transition: width 0.3s ease;
      }}

      /* Parts Table */
      .ergo-parts-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.75rem;
      }}

      .ergo-parts-table th {{
        text-align: left;
        color: #64748b;
        font-weight: 600;
        padding: 3px 6px;
        border-bottom: 1px solid #e2e8f0;
      }}

      .ergo-parts-table td {{
        padding: 4px 6px;
        border-bottom: 1px solid #f1f5f9;
        color: #1e293b;
      }}

      .ergo-parts-table .col-desc {{
        max-width: 140px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}

      .ergo-wt-badge {{
        display: inline-block;
        font-weight: 600;
        padding: 1px 4px;
        border-radius: 4px;
      }}

      .ergo-wt-badge.wt-heavy {{
        background: #fee2e2;
        color: #dc2626;
        font-weight: 800;
        border: 1px solid #fca5a5;
      }}

      /* Equipment Badges */
      .ergo-eq-container {{
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }}

      .ergo-eq-badge {{
        display: inline-block;
        background: #f1f5f9;
        border: 1px solid #cbd5e1;
        color: #334155;
        font-size: 0.74rem;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 6px;
      }}

      /* Notes text */
      .ergo-notes-text {{
        font-size: 0.8rem;
        line-height: 1.4;
        color: #334155;
        max-height: 64px;
        overflow-y: auto;
      }}

      .subtle-empty {{
        font-size: 0.75rem;
        color: #94a3b8;
        font-style: italic;
      }}

      /* Visual Media Grid */
      .ergo-visual-grid {{
        display: grid;
        gap: 10px;
        height: 100%;
        min-height: 0;
        flex: 1 1 auto;
      }}

      .media-grid-1 {{
        grid-template-columns: 1fr;
        grid-template-rows: 1fr;
      }}

      .media-grid-2 {{
        grid-template-columns: 1fr 1fr;
        grid-template-rows: 1fr;
      }}

      .media-grid-3 {{
        grid-template-columns: 1fr 1fr;
        grid-template-rows: 1fr 1fr;
      }}

      .media-grid-3 .ergo-media-card:first-child {{
        grid-row: span 2;
      }}

      .media-grid-4 {{
        grid-template-columns: 1fr 1fr;
        grid-template-rows: 1fr 1fr;
      }}

      .ergo-media-card {{
        display: flex;
        flex-direction: column;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        background: #0f172a;
        overflow: hidden;
        height: 100%;
        min-height: 0;
      }}

      .ergo-media-wrapper {{
        flex: 1 1 auto;
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 0;
        overflow: hidden;
        position: relative;
        background: #090d16;
      }}

      .ergo-media-item {{
        width: 100%;
        height: 100%;
        display: block;
      }}

      .ergo-media-item.image {{
        object-fit: contain;
      }}

      .ergo-media-wrapper.fill .ergo-media-item.image,
      .ergo-media-wrapper.stretch .ergo-media-item.image {{
        object-fit: fill;
      }}

      .ergo-media-wrapper.cover .ergo-media-item.image {{
        object-fit: cover;
      }}

      .ergo-media-item.video {{
        object-fit: contain;
        background: #000000;
      }}

      .ergo-callout-box {{
        background: #fef08a;
        color: #713f12;
        border-top: 1px solid #facc15;
        padding: 4px 10px;
        font-size: 0.74rem;
        display: flex;
        gap: 6px;
        align-items: center;
        flex-shrink: 0;
      }}

      .callout-seq {{
        font-weight: 800;
        background: #eab308;
        color: #ffffff;
        padding: 1px 5px;
        border-radius: 4px;
      }}

      .callout-text {{
        font-weight: 600;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}

      /* Empty State */
      .ergo-empty-visual {{
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        background: #f8fafc;
        border: 2px dashed #cbd5e1;
        border-radius: 8px;
        padding: 24px;
        text-align: center;
      }}

      .ergo-empty-visual .empty-icon {{
        font-size: 2.2rem;
        margin-bottom: 8px;
      }}

      .ergo-empty-visual .empty-title {{
        font-size: 0.95rem;
        font-weight: 700;
        color: #334155;
      }}

      .ergo-empty-visual .empty-desc {{
        font-size: 0.78rem;
        color: #64748b;
        max-width: 320px;
        margin-top: 4px;
        line-height: 1.4;
      }}

      /* Footer */
      .ergo-footer {{
        display: flex;
        justify-content: space-between;
        font-size: 0.7rem;
        color: #94a3b8;
        padding-top: 6px;
        border-top: 1px solid #f1f5f9;
      }}
    </style>
    """


def render_ergonomics_presentation_deck(
    slides_data: list[dict],
    initial_review_id: str = "",
) -> str:
    """Render a standalone, zero-lag client-side presentation deck for Ergonomics reviews."""
    if not slides_data:
        return """
        <div style="padding: 40px; text-align: center; background: #0f172a; color: #94a3b8; border-radius: 8px; font-family: sans-serif;">
          <div style="color: #f8fafc; font-size: 1.2rem; font-weight: 700;">No Ergonomics slides available to present</div>
          <div style="margin-top: 8px;">Ensure there are Ergonomics reviews in this scenario to begin presentation mode.</div>
        </div>
        """

    initial_slide_idx = 0
    if initial_review_id:
        for idx, s in enumerate(slides_data):
            if str(s.get("review_id") or "") == str(initial_review_id):
                initial_slide_idx = idx
                break

    # Build review options for jumper select
    review_options_html = []
    for idx, s in enumerate(slides_data):
        r_id = str(s.get("review_id") or "")
        r_label = str(s.get("review_label") or f"Review {idx + 1}")
        selected_attr = "selected" if idx == initial_slide_idx else ""
        review_options_html.append(
            f'<option value="{idx}" {selected_attr}>{idx + 1}. {html.escape(r_label)}</option>'
        )

    # Build slides HTML
    slides_html = []
    for idx, s in enumerate(slides_data):
        r_id = str(s.get("review_id") or "")
        slide_content = s.get("slide_html") or ""
        display_style = "block" if idx == initial_slide_idx else "none"

        slides_html.append(
            f"""
            <div class="deck-slide"
                 id="ergo-slide-{idx}"
                 data-slide-index="{idx}"
                 data-review-id="{r_id}"
                 style="display: {display_style}; width: 100%; height: 100%;">
              {slide_content}
            </div>
            """
        )

    total_slides = len(slides_data)

    return f"""
    <div id="ergo-presentation-container" class="ergo-deck-container">
      <!-- Presentation Top Controls Bar -->
      <div class="deck-controls-bar">
        <div class="deck-left-controls">
          <button id="ergo-prev-btn" class="deck-nav-btn" title="Previous Slide (Left Arrow, Page Up)">◀ Previous</button>
          <button id="ergo-next-btn" class="deck-nav-btn" title="Next Slide (Right Arrow, Space, Page Down)">Next ▶</button>
          <span class="deck-counter">
            Slide <strong id="ergo-curr-idx">{initial_slide_idx + 1}</strong> of <strong>{total_slides}</strong>
          </span>
        </div>

        <div class="deck-center-controls">
          <label for="ergo-jump-select" style="font-size:0.8rem; color:#cbd5e1; margin-right:6px;">Jump to Review:</label>
          <select id="ergo-jump-select" class="deck-select">
            {''.join(review_options_html)}
          </select>
        </div>

        <div class="deck-right-controls">
          <button id="ergo-fs-btn" class="deck-action-btn" title="Toggle Fullscreen (F)">⛶ Fullscreen</button>
          <span class="deck-shortcut-hint">Shortcuts: ◀ / ▶ Arrow, Space, F, Esc</span>
        </div>
      </div>

      <!-- Slide Display Stage -->
      <div class="deck-stage" id="ergo-deck-stage">
        {''.join(slides_html)}
      </div>
    </div>

    <style>
      .ergo-deck-container {{
        width: 100%;
        height: 88vh;
        min-height: 600px;
        background: #0f172a;
        color: #f8fafc;
        display: flex;
        flex-direction: column;
        border-radius: 8px;
        overflow: hidden;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      }}

      .deck-controls-bar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 16px;
        background: #1e293b;
        border-bottom: 1px solid #334155;
        flex-shrink: 0;
      }}

      .deck-left-controls, .deck-center-controls, .deck-right-controls {{
        display: flex;
        align-items: center;
        gap: 8px;
      }}

      .deck-nav-btn, .deck-action-btn {{
        background: #3b82f6;
        color: #ffffff;
        border: none;
        border-radius: 4px;
        padding: 6px 12px;
        font-size: 0.82rem;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s ease;
      }}

      .deck-nav-btn:hover, .deck-action-btn:hover {{
        background: #2563eb;
      }}

      .deck-select {{
        background: #0f172a;
        color: #f8fafc;
        border: 1px solid #475569;
        border-radius: 4px;
        padding: 5px 10px;
        font-size: 0.8rem;
        max-width: 380px;
        cursor: pointer;
      }}

      .deck-counter {{
        font-size: 0.82rem;
        color: #94a3b8;
        margin-left: 8px;
      }}

      .deck-shortcut-hint {{
        font-size: 0.75rem;
        color: #64748b;
      }}

      .deck-stage {{
        flex: 1 1 auto;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 12px;
        overflow: hidden;
        background: #020617;
      }}
    </style>

    <script>
      (function() {{
        let currentIndex = {initial_slide_idx};
        const totalSlides = {total_slides};

        function showSlide(index) {{
          if (index < 0 || index >= totalSlides) return;
          for (let i = 0; i < totalSlides; i++) {{
            const slide = document.getElementById('ergo-slide-' + i);
            if (slide) {{
              slide.style.display = (i === index) ? 'block' : 'none';
            }}
          }}
          currentIndex = index;
          const idxEl = document.getElementById('ergo-curr-idx');
          if (idxEl) idxEl.innerText = index + 1;
          const selectEl = document.getElementById('ergo-jump-select');
          if (selectEl) selectEl.value = index;
        }}

        const prevBtn = document.getElementById('ergo-prev-btn');
        if (prevBtn) prevBtn.addEventListener('click', () => showSlide(currentIndex - 1));

        const nextBtn = document.getElementById('ergo-next-btn');
        if (nextBtn) nextBtn.addEventListener('click', () => showSlide(currentIndex + 1));

        const jumpSelect = document.getElementById('ergo-jump-select');
        if (jumpSelect) {{
          jumpSelect.addEventListener('change', (e) => {{
            showSlide(parseInt(e.target.value, 10));
          }});
        }}

        const fsBtn = document.getElementById('ergo-fs-btn');
        if (fsBtn) {{
          fsBtn.addEventListener('click', () => {{
            const container = document.getElementById('ergo-presentation-container');
            if (!document.fullscreenElement) {{
              if (container.requestFullscreen) container.requestFullscreen();
            }} else {{
              if (document.exitFullscreen) document.exitFullscreen();
            }}
          }});
        }}

        // Keyboard navigation
        document.addEventListener('keydown', (e) => {{
          if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
          if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') {{
            e.preventDefault();
            showSlide(currentIndex + 1);
          }} else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {{
            e.preventDefault();
            showSlide(currentIndex - 1);
          }} else if (e.key === 'f' || e.key === 'F') {{
            if (fsBtn) fsBtn.click();
          }}
        }});
      }})();
    </script>
    """


def render_printable_ergonomics_deck(
    slides_html: list[str],
    *,
    paper_size: str = "tabloid",
    image_fit: str = "contain",
    title: str = "Ergonomics Assessment Slides",
) -> str:
    """Render a standalone, multi-page HTML document containing all review slides for printing/PDF export."""
    css_page_size = "17in 11in landscape" if paper_size == "tabloid" else "11in 8.5in landscape"
    paper_label = "11 × 17 in (Tabloid Landscape)" if paper_size == "tabloid" else "8.5 × 11 in (Letter Landscape)"
    total_slides = len(slides_html)

    joined_slides = "\n".join(
        f"""
        <div class="print-slide-wrapper">
          <div class="print-slide-header no-print">
            <span><strong>Review Slide {i + 1} of {total_slides}</strong></span>
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
      background: #f1f5f9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    .print-toolbar {{
      position: sticky;
      top: 0;
      z-index: 9999;
      background: #1e293b;
      color: #f8fafc;
      padding: 10px 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    }}
    .print-btn {{
      background: #3b82f6;
      color: #ffffff;
      border: none;
      border-radius: 6px;
      padding: 8px 18px;
      font-size: 0.9rem;
      font-weight: 700;
      cursor: pointer;
    }}
    .print-btn:hover {{
      background: #2563eb;
    }}
    .print-deck-body {{
      max-width: 1200px;
      margin: 20px auto;
      padding: 0 16px;
    }}
    .print-slide-wrapper {{
      page-break-after: always;
      margin-bottom: 24px;
    }}
    .print-slide-wrapper:last-child {{
      page-break-after: auto;
    }}
    .print-slide-header {{
      display: flex;
      justify-content: space-between;
      font-size: 0.8rem;
      color: #64748b;
      margin-bottom: 6px;
    }}
    @media print {{
      .no-print {{
        display: none !important;
      }}
      body {{
        background: #ffffff !important;
      }}
      .print-deck-body {{
        max-width: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
      }}
      .print-slide-wrapper {{
        page-break-after: always !important;
        margin-bottom: 0 !important;
      }}
      .ergo-slide {{
        border: none !important;
        box-shadow: none !important;
      }}
    }}
  </style>
</head>
<body>
  <div class="print-toolbar no-print">
    <div>
      <strong>{html.escape(title)}</strong>
      <span style="margin-left: 12px; font-size: 0.85rem; color: #94a3b8;">{total_slides} slides ({paper_label})</span>
    </div>
    <div>
      <button class="print-btn" onclick="window.print()">🖨️ Print / Save as PDF</button>
    </div>
  </div>

  <div class="print-deck-body">
    {joined_slides}
  </div>
</body>
</html>
"""
